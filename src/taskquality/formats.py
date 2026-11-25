"""Formats, serialization, and schema validation for taskquality files."""

import datetime
import hashlib
import json
import re
from pathlib import Path

RECOGNIZED_CONFIG_KEYS = frozenset([
    "ci_green_conclusions",
    "ci_workflows",
    "fail_verdicts",
    "github_review_role",
    "kind",
    "pass_verdicts",
    "review_roles",
    "rework_keywords",
    "schema_version",
    "ticket_ref_keywords",
    "verdict_pattern",
    "verdict_sources",
])

ISO_UTC_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z\Z")
PR_ID_RE = re.compile(r"^([^#]+)#(\d+)\Z")
HEX_HEAD_RE = re.compile(r"^[0-9a-f]{7,40}\Z")
VALID_USAGE_ROLES = frozenset(["impl", "review", "arch", "pm", "other"])
USAGE_INT_KEYS = frozenset([
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_micro_usd",
])


class ToolError(Exception):
    """Exit code 2 tool error with code and message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_iso_utc(ts: str) -> datetime.datetime:
    """Validate YYYY-MM-DDTHH:MM:SSZ and return datetime without calling clock."""
    if not isinstance(ts, str):
        raise ToolError("bad_time", f"timestamp must be a string: {ts!r}")
    m = ISO_UTC_RE.match(ts)
    if not m:
        raise ToolError("bad_time", f"timestamp must be YYYY-MM-DDTHH:MM:SSZ: {ts!r}")
    year, month, day, hour, minute, second = (int(g) for g in m.groups())
    try:
        return datetime.datetime(
            year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc
        )
    except ValueError as e:
        raise ToolError("bad_time", f"invalid calendar time: {ts!r}: {e}") from e


def parse_pr_id(pr_id: str, err_code: str = "snapshot_bad_shape") -> tuple[str, int]:
    """Parse owner/repo#number into (owner/repo, number)."""
    if not isinstance(pr_id, str):
        raise ToolError(err_code, f"PR id must be string: {pr_id!r}")
    m = PR_ID_RE.match(pr_id)
    if not m or "/" not in m.group(1):
        raise ToolError(err_code, f"PR id must match owner/repo#number: {pr_id!r}")
    return m.group(1), int(m.group(2))


def read_json_file(path: str | Path, kind_name: str) -> dict:
    """Read a JSON file, returning dict or raising ToolError."""
    p = Path(path)
    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ToolError("file_not_json", f"file is not valid UTF-8/JSON ({path}): {e}") from e
    except OSError as e:
        raise ToolError("file_unreadable", f"cannot read {path}: {e}") from e

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ToolError("file_not_json", f"file is not valid JSON ({path}): {e}") from e

    if not isinstance(data, dict):
        raise ToolError(f"{kind_name}_bad_shape", f"{kind_name} must be a JSON object ({path})")
    return data


def validate_snapshot(snap: dict) -> None:
    """Validate snapshot structure."""
    if not isinstance(snap, dict):
        raise ToolError("snapshot_bad_shape", "snapshot must be a JSON object")
    if snap.get("kind") != "taskquality-snapshot" or snap.get("schema_version") != 1:
        raise ToolError("snapshot_bad_shape", "snapshot must have kind='taskquality-snapshot' and schema_version=1")
    ticket = snap.get("ticket")
    if not isinstance(ticket, str) or not PR_ID_RE.match(ticket) or "/" not in ticket.split("#")[0]:
        raise ToolError("snapshot_bad_shape", f"snapshot has invalid ticket: {ticket!r}")
    prs = snap.get("prs")
    if not isinstance(prs, list):
        raise ToolError("snapshot_bad_shape", "snapshot prs must be a list")

    for pr in prs:
        if not isinstance(pr, dict):
            raise ToolError("snapshot_bad_shape", "PR item must be an object")
        if "id" not in pr or not isinstance(pr["id"], str):
            raise ToolError("snapshot_bad_shape", "PR id is required and must be a string")
        parse_pr_id(pr["id"], "snapshot_bad_shape")

        if "title" not in pr or not isinstance(pr["title"], str):
            raise ToolError("snapshot_bad_shape", "PR title is required and must be a string")
        if "body" not in pr or not isinstance(pr["body"], str):
            raise ToolError("snapshot_bad_shape", "PR body is required and must be a string")
        state = pr.get("state")
        if not isinstance(state, str) or state not in ("open", "closed"):
            raise ToolError("snapshot_bad_shape", "PR state must be 'open' or 'closed'")
        head_sha = pr.get("head_sha")
        if not isinstance(head_sha, str) or not head_sha:
            raise ToolError("snapshot_bad_shape", "PR head_sha is required and must be a non-empty string")

        if "created_at" not in pr or pr["created_at"] is None:
            raise ToolError("snapshot_bad_shape", "PR created_at is required")
        parse_iso_utc(pr["created_at"])

        merged_at = pr.get("merged_at")
        if merged_at is not None:
            parse_iso_utc(merged_at)
        closed_at = pr.get("closed_at")
        if closed_at is not None:
            parse_iso_utc(closed_at)

        comments = pr.get("comments")
        if not isinstance(comments, list):
            raise ToolError("snapshot_bad_shape", "PR comments must be a list")
        for c in comments:
            if not isinstance(c, dict):
                raise ToolError("snapshot_bad_shape", "comment item must be an object")
            if "id" not in c or isinstance(c["id"], bool) or not isinstance(c["id"], int):
                raise ToolError("snapshot_bad_shape", "comment id must be an integer")
            if "first_line" not in c or not isinstance(c["first_line"], str):
                raise ToolError("snapshot_bad_shape", "comment first_line must be a string")
            if "created_at" not in c or c["created_at"] is None:
                raise ToolError("snapshot_bad_shape", "comment created_at is required")
            parse_iso_utc(c["created_at"])

        reviews = pr.get("reviews")
        if not isinstance(reviews, list):
            raise ToolError("snapshot_bad_shape", "PR reviews must be a list")
        for r in reviews:
            if not isinstance(r, dict):
                raise ToolError("snapshot_bad_shape", "review item must be an object")
            if "id" not in r or isinstance(r["id"], bool) or not isinstance(r["id"], int):
                raise ToolError("snapshot_bad_shape", "review id must be an integer")
            if "state" not in r or not isinstance(r["state"], str):
                raise ToolError("snapshot_bad_shape", "review state must be a string")
            commit_id = r.get("commit_id")
            if not isinstance(commit_id, str) or not commit_id:
                raise ToolError("snapshot_bad_shape", f"review commit_id must be a non-empty string: {commit_id!r}")
            if "submitted_at" not in r or r["submitted_at"] is None:
                raise ToolError("snapshot_bad_shape", "review submitted_at is required")
            parse_iso_utc(r["submitted_at"])

        ci_runs = pr.get("ci_runs")
        if not isinstance(ci_runs, list):
            raise ToolError("snapshot_bad_shape", "PR ci_runs must be a list")
        for run in ci_runs:
            if not isinstance(run, dict):
                raise ToolError("snapshot_bad_shape", "ci_run item must be an object")
            if "run_id" not in run or isinstance(run["run_id"], bool) or not isinstance(run["run_id"], int):
                raise ToolError("snapshot_bad_shape", "ci_run run_id must be an integer")
            if "workflow" not in run or not isinstance(run["workflow"], str):
                raise ToolError("snapshot_bad_shape", "ci_run workflow must be a string")
            run_head = run.get("head_sha")
            if not isinstance(run_head, str) or not run_head:
                raise ToolError("snapshot_bad_shape", "ci_run head_sha must be a non-empty string")
            run_attempt = run.get("run_attempt")
            if run_attempt is None or isinstance(run_attempt, bool) or not isinstance(run_attempt, int):
                raise ToolError("snapshot_bad_shape", f"ci_run run_attempt must be an integer: {run_attempt!r}")
            if "created_at" not in run or run["created_at"] is None:
                raise ToolError("snapshot_bad_shape", "ci_run created_at is required")
            parse_iso_utc(run["created_at"])
            status = run.get("status")
            if not isinstance(status, str):
                raise ToolError("snapshot_bad_shape", "ci_run status must be a string")
            conclusion = run.get("conclusion")
            if conclusion is not None and not isinstance(conclusion, str):
                raise ToolError("snapshot_bad_shape", "ci_run conclusion must be a string or null")


def validate_input(input_data: dict, snapshot_ticket: str) -> None:
    """Validate input structure and ticket match."""
    if not isinstance(input_data, dict):
        raise ToolError("input_bad_shape", "input must be a JSON object")
    if input_data.get("kind") != "taskquality-input" or input_data.get("schema_version") != 1:
        raise ToolError("input_bad_shape", "input must have kind='taskquality-input' and schema_version=1")
    in_ticket = input_data.get("ticket")
    if in_ticket != snapshot_ticket:
        raise ToolError("ticket_mismatch", f"snapshot ticket ({snapshot_ticket}) does not match input ticket ({in_ticket})")

    if "started_at" in input_data and input_data["started_at"] is not None:
        parse_iso_utc(input_data["started_at"])

    if "prs" in input_data and input_data["prs"] is not None:
        if not isinstance(input_data["prs"], dict):
            raise ToolError("input_bad_shape", "input.prs must be an object")
        for prid, pr_override in input_data["prs"].items():
            parse_pr_id(prid, "input_bad_shape")
            if not isinstance(pr_override, dict):
                raise ToolError("input_bad_shape", f"input.prs.{prid} must be an object")
            if "verdicts" in pr_override and pr_override["verdicts"] is not None:
                if not isinstance(pr_override["verdicts"], list):
                    raise ToolError("input_bad_shape", f"input.prs.{prid}.verdicts must be a list or null")
                for v in pr_override["verdicts"]:
                    if not isinstance(v, dict):
                        raise ToolError("input_bad_shape", "verdict item must be an object")
                    if "at" not in v or v["at"] is None:
                        raise ToolError("input_bad_shape", "verdict at is required")
                    parse_iso_utc(v["at"])
                    if "role" not in v or not isinstance(v["role"], str) or not v["role"]:
                        raise ToolError("input_bad_shape", "verdict item missing role")
                    v_val = v.get("verdict")
                    if not isinstance(v_val, str) or v_val not in ("pass", "fail", "other"):
                        raise ToolError("input_bad_shape", f"invalid verdict value: {v_val!r}")
                    head = v.get("head")
                    if not isinstance(head, str) or not HEX_HEAD_RE.match(head):
                        raise ToolError("input_bad_shape", f"verdict head must be 7-40 lowercase hex digits: {head!r}")
            if "rework" in pr_override and pr_override["rework"] is not None:
                if not isinstance(pr_override["rework"], bool):
                    raise ToolError("input_bad_shape", f"input.prs.{prid}.rework must be a boolean or null")

    if "usage" in input_data and input_data["usage"] is not None:
        if not isinstance(input_data["usage"], list):
            raise ToolError("input_bad_shape", "input.usage must be a list or null")
        for item in input_data["usage"]:
            if not isinstance(item, dict):
                raise ToolError("input_bad_shape", "usage item must be an object")
            provider = item.get("provider")
            if not isinstance(provider, str) or not provider:
                raise ToolError("input_bad_shape", f"usage item provider must be a non-empty string: {provider!r}")
            model = item.get("model")
            if not isinstance(model, str) or not model:
                raise ToolError("input_bad_shape", f"usage item model must be a non-empty string: {model!r}")
            role = item.get("role")
            if not isinstance(role, str) or role not in VALID_USAGE_ROLES:
                raise ToolError("input_bad_shape", f"invalid usage role: {role!r}")
            if "pr" in item and item["pr"] is not None:
                parse_pr_id(item["pr"], "input_bad_shape")
            for key in USAGE_INT_KEYS:
                if key in item and item[key] is not None:
                    val = item[key]
                    if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                        raise ToolError("input_bad_shape", f"usage item {key} must be a non-negative integer or null: {val!r}")

    if "counters" in input_data and input_data["counters"] is not None:
        if not isinstance(input_data["counters"], dict):
            raise ToolError("input_bad_shape", "input.counters must be an object or null")
        for k, v in input_data["counters"].items():
            if not isinstance(k, str):
                raise ToolError("input_bad_shape", f"counter key must be a string: {k!r}")
            if v is not None:
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    raise ToolError("input_bad_shape", f"counter {k} value must be a non-negative integer or null: {v!r}")


def validate_config(cfg: dict) -> None:
    """Validate config structure and compile regex."""
    if not isinstance(cfg, dict):
        raise ToolError("config_bad_shape", "config must be a JSON object")
    if cfg.get("kind") != "taskquality-config" or cfg.get("schema_version") != 1:
        raise ToolError("config_bad_shape", "config must have kind='taskquality-config' and schema_version=1")

    required_keys = [
        "ticket_ref_keywords",
        "verdict_sources",
        "github_review_role",
        "verdict_pattern",
        "review_roles",
        "pass_verdicts",
        "fail_verdicts",
        "rework_keywords",
        "ci_workflows",
        "ci_green_conclusions",
    ]
    for k in required_keys:
        if k not in cfg:
            raise ToolError("config_bad_shape", f"config missing required key: {k}")

    list_str_keys = [
        "ticket_ref_keywords",
        "review_roles",
        "pass_verdicts",
        "fail_verdicts",
        "rework_keywords",
        "ci_green_conclusions",
    ]
    for k in list_str_keys:
        val = cfg[k]
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            raise ToolError("config_bad_shape", f"config {k} must be a list of strings")

    gh_role = cfg["github_review_role"]
    if not isinstance(gh_role, str) or not gh_role:
        raise ToolError("config_bad_shape", "config github_review_role must be a non-empty string")

    ci_wf = cfg["ci_workflows"]
    if ci_wf is not None:
        if not isinstance(ci_wf, list) or not all(isinstance(x, str) for x in ci_wf):
            raise ToolError("config_bad_shape", "config ci_workflows must be null or a list of strings")

    sources = cfg.get("verdict_sources")
    if not isinstance(sources, list) or len(sources) == 0:
        raise ToolError("config_bad_shape", "verdict_sources must be a non-empty list")
    if not all(isinstance(s, str) for s in sources):
        raise ToolError("config_bad_shape", "verdict_sources elements must be strings")
    if len(sources) != len(set(sources)):
        raise ToolError("config_bad_shape", "verdict_sources cannot contain duplicates")
    for s in sources:
        if s not in ("comments", "reviews"):
            raise ToolError("config_bad_shape", f"invalid verdict_sources element: {s!r}")

    pat_str = cfg.get("verdict_pattern")
    if not isinstance(pat_str, str):
        raise ToolError("config_bad_shape", "verdict_pattern must be a string")
    try:
        compiled = re.compile(pat_str)
    except re.error as e:
        raise ToolError("bad_pattern", f"cannot compile verdict_pattern: {e}") from e

    required_groups = {"role", "model", "verdict", "head"}
    if not required_groups.issubset(compiled.groupindex.keys()):
        raise ToolError("config_bad_shape", f"verdict_pattern missing required named groups: {required_groups}")


def calculate_config_digest(cfg: dict) -> str:
    """Calculate sha256 config digest on recognized keys only."""
    filtered = {k: cfg[k] for k in RECOGNIZED_CONFIG_KEYS if k in cfg}
    canonical = json.dumps(filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{h}"


def render_json(obj: dict) -> str:
    """Deterministic JSON output with sorted keys, 2 spaces indent, and trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
