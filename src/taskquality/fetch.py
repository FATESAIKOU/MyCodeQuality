"""taskquality fetch: retrieve PR and issue data from GitHub API to build a taskquality snapshot."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any, Callable
import urllib.parse

from taskquality.formats import (
    ToolError,
    parse_pr_id,
    render_json,
    validate_snapshot,
)

GRAPHQL_TIMELINE_QUERY = """query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      timelineItems(first: 100, after: $cursor, itemTypes: [CONNECTED_EVENT, CROSS_REFERENCED_EVENT]) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          __typename
          ... on ConnectedEvent {
            subject {
              __typename
              ... on PullRequest {
                number
                repository {
                  nameWithOwner
                }
              }
            }
          }
          ... on CrossReferencedEvent {
            source {
              __typename
              ... on PullRequest {
                number
                repository {
                  nameWithOwner
                }
              }
            }
          }
        }
      }
    }
  }
}"""


def default_runner(argv: list[str]) -> tuple[str, str, int]:
    """Default runner invoking the real gh executable via subprocess."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True)
        return proc.stdout, proc.stderr, proc.returncode
    except FileNotFoundError as e:
        raise ToolError("gh_unavailable", f"gh command not found: {e}") from e
    except OSError as e:
        raise ToolError("gh_failed", f"failed to execute gh: {e}") from e


def normalize_runner_result(res: Any) -> tuple[str, str, int]:
    """Normalize return value from an injected runner into (stdout, stderr, exit_code)."""
    if isinstance(res, (tuple, list)):
        if len(res) == 3:
            return str(res[0]), str(res[1]), int(res[2])
        elif len(res) == 2:
            return str(res[0]), "", int(res[1])
        elif len(res) == 1:
            return str(res[0]), "", 0
    if hasattr(res, "stdout") and (hasattr(res, "returncode") or hasattr(res, "exit_code")):
        stdout = str(getattr(res, "stdout", ""))
        stderr = str(getattr(res, "stderr", ""))
        code = getattr(res, "returncode", None)
        if code is None:
            code = getattr(res, "exit_code", 0)
        return stdout, stderr, int(code)
    if isinstance(res, str):
        return res, "", 0
    raise ValueError(f"unrecognized runner return value: {res!r}")


def invoke_runner(runner: Callable[[list[str]], Any], argv: list[str]) -> tuple[str, str, int]:
    """Invoke runner and map FileNotFoundError to gh_unavailable ToolError."""
    try:
        res = runner(argv)
    except FileNotFoundError as e:
        raise ToolError("gh_unavailable", f"gh command not found: {e}") from e
    except ToolError:
        raise
    except Exception as e:
        raise ToolError("gh_failed", f"error invoking gh runner: {e}") from e
    return normalize_runner_result(res)


def check_rate_limit(stdout: str, stderr: str, code: int) -> tuple[bool, int | None, int | None]:
    """Check if response indicates HTTP 403 or 429 rate limit.

    Returns (is_rate_limited, retry_after_seconds, reset_epoch).
    """
    combined = f"{stdout}\n{stderr}"
    is_429 = code == 429 or bool(re.search(r"\b429\b", combined))
    is_403 = code == 403 or bool(re.search(r"\b403\b", combined))

    m_ra = re.search(r"(?i)retry-after:\s*(\d+)", combined)
    m_reset = re.search(r"(?i)x-ratelimit-reset:\s*(\d+)", combined)

    retry_after = int(m_ra.group(1)) if m_ra else None
    reset_epoch = int(m_reset.group(1)) if m_reset else None

    if (is_429 or is_403) and (retry_after is not None or reset_epoch is not None):
        return True, retry_after, reset_epoch
    if is_429:
        return True, None, None
    return False, None, None


def execute_with_retry(
    argv: list[str],
    runner: Callable[[list[str]], Any],
    sleeper: Callable[[float], None],
    time_func: Callable[[], float],
    max_retries: int = 3,
) -> tuple[str, str, int]:
    """Execute command with runner, retrying up to max_retries on 403/429 rate limits."""
    for attempt in range(max_retries + 1):
        stdout, stderr, code = invoke_runner(runner, argv)
        is_rl, retry_after, reset_epoch = check_rate_limit(stdout, stderr, code)
        if is_rl:
            if attempt < max_retries:
                if retry_after is not None:
                    wait_sec = min(max(0, retry_after), 60)
                elif reset_epoch is not None:
                    wait_sec = min(max(0, reset_epoch - int(time_func())), 60)
                else:
                    wait_sec = min(1, 60)
                sleeper(wait_sec)
                continue
            else:
                raise ToolError("rate_limited", f"GitHub API rate limit exceeded after {max_retries} retries")
        return stdout, stderr, code
    raise ToolError("rate_limited", f"GitHub API rate limit exceeded after {max_retries} retries")


def strip_http_headers(raw: str) -> str:
    """Strip HTTP response status line and headers if present."""
    if raw.startswith("HTTP/"):
        parts = re.split(r"\r?\n\r?\n", raw, maxsplit=1)
        if len(parts) == 2:
            return parts[1]
    return raw


def parse_paginated_json(raw: str) -> list[Any]:
    """Parse paginated JSON output (potentially multiple concatenated JSON arrays/objects)."""
    body = strip_http_headers(raw).strip()
    if not body:
        return []
    decoder = json.JSONDecoder()
    pos = 0
    items: list[Any] = []
    while pos < len(body):
        while pos < len(body) and body[pos].isspace():
            pos += 1
        if pos >= len(body):
            break
        try:
            obj, end_pos = decoder.raw_decode(body, pos)
        except json.JSONDecodeError as e:
            raise ToolError("incomplete_pagination", f"invalid JSON in paginated output: {e}") from e
        pos = end_pos
        if isinstance(obj, list):
            items.extend(obj)
        elif isinstance(obj, dict):
            if "workflow_runs" in obj and isinstance(obj["workflow_runs"], list):
                items.extend(obj["workflow_runs"])
            else:
                items.append(obj)
        else:
            items.append(obj)
    return items


def parse_single_json(raw: str, err_code: str = "gh_failed") -> dict:
    """Parse a single JSON object response."""
    body = strip_http_headers(raw).strip()
    try:
        obj = json.loads(body)
    except json.JSONDecodeError as e:
        raise ToolError(err_code, f"invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ToolError(err_code, "expected JSON object")
    return obj


def fetch_snapshot(
    ticket: str,
    out_path: str | Path,
    search_repos: list[str] | None = None,
    explicit_prs: list[str] | None = None,
    runner: Callable[[list[str]], Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
    time_func: Callable[[], float] | None = None,
) -> dict:
    """Fetch ticket candidate PRs and details to produce a snapshot, atomically writing to out_path."""
    actual_runner = runner if runner is not None else default_runner
    actual_sleeper = sleeper if sleeper is not None else time.sleep
    actual_time = time_func if time_func is not None else time.time

    ticket_owner_repo, ticket_num = parse_pr_id(ticket, "bad_arguments")
    ticket_owner, ticket_repo = ticket_owner_repo.split("/", 1)

    out = Path(out_path).resolve()
    if out.is_dir():
        raise ToolError("out_unwritable", f"--out is a directory: {out}")
    out_dir = out.parent
    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ToolError("out_unwritable", f"cannot create directory {out_dir}: {e}") from e

    # 1. Candidate PRs via GraphQL timelineItems
    cursor = None
    page = 1
    candidate_prs: set[str] = set()

    while True:
        argv = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={GRAPHQL_TIMELINE_QUERY}",
            "-F",
            f"owner={ticket_owner}",
            "-F",
            f"name={ticket_repo}",
            "-F",
            f"number={ticket_num}",
        ]
        if cursor:
            argv.extend(["-F", f"cursor={cursor}"])

        stdout, stderr, code = execute_with_retry(argv, actual_runner, actual_sleeper, actual_time)
        if code != 0:
            combined = f"{stdout}\n{stderr}".lower()
            if page == 1:
                if (
                    "could not resolve to an issue" in combined
                    or "not_found" in combined
                    or "404" in combined
                    or "not found" in combined
                ):
                    raise ToolError("not_found", f"issue not found: {ticket}")
                raise ToolError("gh_failed", f"GraphQL query failed: {stderr.strip()}")
            else:
                raise ToolError(
                    "incomplete_pagination",
                    f"GraphQL pagination failed on page {page}: {stderr.strip()}",
                )

        body = strip_http_headers(stdout).strip()
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            if page > 1:
                raise ToolError("incomplete_pagination", f"invalid JSON on page {page}: {e}") from e
            raise ToolError("gh_failed", f"invalid JSON from GraphQL: {e}") from e

        if "errors" in data and data["errors"]:
            err_msgs = " ".join(e.get("message", "") for e in data["errors"])
            combined = err_msgs.lower()
            if (
                "could not resolve to an issue" in combined
                or "not_found" in combined
                or "not found" in combined
            ):
                raise ToolError("not_found", f"issue not found: {ticket}: {err_msgs}")
            if page > 1:
                raise ToolError("incomplete_pagination", f"GraphQL error on page {page}: {err_msgs}")
            raise ToolError("gh_failed", f"GraphQL error: {err_msgs}")

        repo_obj = data.get("data", {}).get("repository")
        if repo_obj is None:
            raise ToolError("not_found", f"repository or issue not found: {ticket}")
        issue_obj = repo_obj.get("issue")
        if issue_obj is None:
            raise ToolError("not_found", f"issue not found: {ticket}")

        timeline = issue_obj.get("timelineItems", {})
        nodes = timeline.get("nodes", [])
        for node in nodes:
            pr_target = None
            if node.get("__typename") == "ConnectedEvent" or "subject" in node:
                pr_target = node.get("subject")
            elif node.get("__typename") == "CrossReferencedEvent" or "source" in node:
                pr_target = node.get("source")

            if isinstance(pr_target, dict) and "number" in pr_target:
                p_num = pr_target["number"]
                r_info = pr_target.get("repository", {})
                r_name = None
                if isinstance(r_info, dict):
                    r_name = r_info.get("nameWithOwner")
                    if not r_name and "owner" in r_info and "name" in r_info:
                        owner_val = r_info["owner"]
                        owner_str = owner_val.get("login", "") if isinstance(owner_val, dict) else str(owner_val)
                        r_name = f"{owner_str}/{r_info['name']}"
                if r_name:
                    candidate_prs.add(f"{r_name}#{p_num}")

        page_info = timeline.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
        page += 1

    # Filter by search_repos (if specified)
    filtered_prs: set[str] = set()
    if search_repos:
        search_repos_lower = {s.lower() for s in search_repos}
        for pr_id in candidate_prs:
            repo_part, _ = parse_pr_id(pr_id)
            if repo_part.lower() in search_repos_lower:
                filtered_prs.add(pr_id)
    else:
        filtered_prs = set(candidate_prs)

    # Explicit PRs are ALWAYS included (exempt from search-repo filtering)
    if explicit_prs:
        for pr_id in explicit_prs:
            filtered_prs.add(pr_id)

    # Sort candidate PRs deterministically by (owner/repo string, number int)
    sorted_candidate_prs = sorted(
        filtered_prs,
        key=lambda pid: (parse_pr_id(pid)[0], parse_pr_id(pid)[1]),
    )

    prs: list[dict[str, Any]] = []
    for pr_id in sorted_candidate_prs:
        pr_repo, pr_num = parse_pr_id(pr_id)

        # PR details
        pr_argv = ["gh", "api", f"/repos/{pr_repo}/pulls/{pr_num}"]
        pr_out, pr_err, pr_code = execute_with_retry(pr_argv, actual_runner, actual_sleeper, actual_time)
        if pr_code != 0:
            combined = f"{pr_out}\n{pr_err}".lower()
            if "not found" in combined or "404" in combined:
                raise ToolError("not_found", f"PR not found: {pr_id}")
            raise ToolError("gh_failed", f"failed to fetch PR {pr_id}: {pr_err.strip()}")
        pr_data = parse_single_json(pr_out)

        head_obj = pr_data.get("head") or {}
        head_sha = head_obj.get("sha", "")
        head_ref = head_obj.get("ref", "")
        title = pr_data.get("title") or ""
        body = pr_data.get("body") or ""
        state = pr_data.get("state", "closed")
        draft = bool(pr_data.get("draft", False))
        created_at = pr_data["created_at"]
        merged_at = pr_data.get("merged_at")
        closed_at = pr_data.get("closed_at")
        merge_commit_sha = pr_data.get("merge_commit_sha")

        # Comments
        com_argv = ["gh", "api", "--paginate", f"/repos/{pr_repo}/issues/{pr_num}/comments"]
        com_out, com_err, com_code = execute_with_retry(com_argv, actual_runner, actual_sleeper, actual_time)
        if com_code != 0:
            combined = f"{com_out}\n{com_err}".lower()
            if "pagination" in combined:
                raise ToolError("incomplete_pagination", f"pagination failed for comments of {pr_id}: {com_err.strip()}")
            raise ToolError("gh_failed", f"failed to fetch comments for {pr_id}: {com_err.strip()}")
        raw_comments = parse_paginated_json(com_out)
        comments = []
        for c in raw_comments:
            if isinstance(c, dict) and "id" in c and "created_at" in c:
                c_body = c.get("body") or ""
                lines = c_body.splitlines()
                first_line = lines[0] if lines else ""
                comments.append({
                    "id": int(c["id"]),
                    "created_at": c["created_at"],
                    "first_line": first_line,
                })
        comments.sort(key=lambda item: (item["created_at"], item["id"]))

        # Reviews
        rev_argv = ["gh", "api", "--paginate", f"/repos/{pr_repo}/pulls/{pr_num}/reviews"]
        rev_out, rev_err, rev_code = execute_with_retry(rev_argv, actual_runner, actual_sleeper, actual_time)
        if rev_code != 0:
            combined = f"{rev_out}\n{rev_err}".lower()
            if "pagination" in combined:
                raise ToolError("incomplete_pagination", f"pagination failed for reviews of {pr_id}: {rev_err.strip()}")
            raise ToolError("gh_failed", f"failed to fetch reviews for {pr_id}: {rev_err.strip()}")
        raw_reviews = parse_paginated_json(rev_out)
        reviews = []
        for r in raw_reviews:
            if isinstance(r, dict) and "id" in r and r.get("submitted_at") is not None:
                reviews.append({
                    "id": int(r["id"]),
                    "submitted_at": r["submitted_at"],
                    "state": str(r.get("state", "")),
                    "commit_id": str(r.get("commit_id") or ""),
                })
        reviews.sort(key=lambda item: (item["submitted_at"], item["id"]))

        # Commits
        cmt_argv = ["gh", "api", "--paginate", f"/repos/{pr_repo}/pulls/{pr_num}/commits"]
        cmt_out, cmt_err, cmt_code = execute_with_retry(cmt_argv, actual_runner, actual_sleeper, actual_time)
        if cmt_code != 0:
            combined = f"{cmt_out}\n{cmt_err}".lower()
            if "pagination" in combined:
                raise ToolError("incomplete_pagination", f"pagination failed for commits of {pr_id}: {cmt_err.strip()}")
            raise ToolError("gh_failed", f"failed to fetch commits for {pr_id}: {cmt_err.strip()}")
        raw_commits = parse_paginated_json(cmt_out)
        pr_commit_shas = {c["sha"] for c in raw_commits if isinstance(c, dict) and "sha" in c}
        if head_sha:
            pr_commit_shas.add(head_sha)

        # Actions runs
        runs_endpoint = f"/repos/{pr_repo}/actions/runs?event=pull_request"
        if head_ref:
            runs_endpoint += f"&branch={urllib.parse.quote(head_ref, safe='')}"
        run_argv = ["gh", "api", "--paginate", runs_endpoint]
        run_out, run_err, run_code = execute_with_retry(run_argv, actual_runner, actual_sleeper, actual_time)
        if run_code != 0:
            combined = f"{run_out}\n{run_err}".lower()
            if "pagination" in combined:
                raise ToolError("incomplete_pagination", f"pagination failed for workflow runs of {pr_id}: {run_err.strip()}")
            raise ToolError("gh_failed", f"failed to fetch workflow runs for {pr_id}: {run_err.strip()}")
        raw_runs = parse_paginated_json(run_out)

        matching_runs = []
        for r in raw_runs:
            if not isinstance(r, dict):
                continue
            in_prs = any(
                isinstance(p, dict) and p.get("number") == pr_num
                for p in r.get("pull_requests", [])
            )
            in_commits = r.get("head_sha") in pr_commit_shas
            if in_prs or in_commits:
                matching_runs.append(r)

        ci_runs_dict = {}
        for r in matching_runs:
            run_id = int(r["id"])
            run_attempt = int(r.get("run_attempt", 1))

            if run_attempt > 1:
                for k in range(1, run_attempt):
                    att_argv = ["gh", "api", f"/repos/{pr_repo}/actions/runs/{run_id}/attempts/{k}"]
                    att_out, att_err, att_code = execute_with_retry(att_argv, actual_runner, actual_sleeper, actual_time)
                    if att_code != 0:
                        raise ToolError("gh_failed", f"failed to fetch attempt {k} for run {run_id}: {att_err.strip()}")
                    att_data = parse_single_json(att_out)
                    ci_runs_dict[(run_id, k)] = {
                        "run_id": run_id,
                        "workflow": str(att_data.get("name") or r.get("name") or ""),
                        "event": str(att_data.get("event") or r.get("event") or "pull_request"),
                        "head_sha": str(att_data.get("head_sha") or r.get("head_sha") or ""),
                        "run_attempt": k,
                        "created_at": str(att_data.get("created_at") or r.get("created_at")),
                        "status": str(att_data.get("status") or ""),
                        "conclusion": att_data.get("conclusion"),
                    }

            ci_runs_dict[(run_id, run_attempt)] = {
                "run_id": run_id,
                "workflow": str(r.get("name") or ""),
                "event": str(r.get("event") or "pull_request"),
                "head_sha": str(r.get("head_sha") or ""),
                "run_attempt": run_attempt,
                "created_at": str(r.get("created_at")),
                "status": str(r.get("status") or ""),
                "conclusion": r.get("conclusion"),
            }

        ci_runs = list(ci_runs_dict.values())
        ci_runs.sort(key=lambda item: (item["created_at"], item["run_id"], item["run_attempt"]))

        prs.append({
            "id": pr_id,
            "title": title,
            "body": body,
            "state": state,
            "draft": draft,
            "created_at": created_at,
            "merged_at": merged_at,
            "closed_at": closed_at,
            "head_sha": head_sha,
            "merge_commit_sha": merge_commit_sha,
            "comments": comments,
            "reviews": reviews,
            "ci_runs": ci_runs,
        })

    snapshot = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": ticket,
        "prs": prs,
    }

    validate_snapshot(snapshot)
    rendered = render_json(snapshot)

    out = Path(out_path).resolve()
    if out.is_dir():
        raise ToolError("out_unwritable", f"--out is a directory: {out}")
    out_dir = out.parent
    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ToolError("out_unwritable", f"cannot create directory {out_dir}: {e}") from e

    try:
        tmp = tempfile.NamedTemporaryFile("w", dir=out_dir, delete=False, encoding="utf-8")
        tmp_path = Path(tmp.name)
        try:
            tmp.write(rendered)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp_path, out)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
    except OSError as e:
        raise ToolError("out_unwritable", f"cannot write to {out}: {e}") from e

    return snapshot
