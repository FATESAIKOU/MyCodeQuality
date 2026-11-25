"""Ticket selection for the task-quality workflow (design §3.1). Pure function of its inputs.

The gh output shapes are checked here, and so are the places where gh's real output is awkward:
- `gh issue list` is not sorted by closedAt, so sorting happens here (rule 3).
- A result of exactly LIST_LIMIT rows may be cut off, so it is an error (exit 2).
- `gh api --paginate --slurp` gives one array element per page; anything else is an error.
"""

import datetime
import re

from mcqreport.common import ToolError, check_days, parse_utc
from mcqreport.names import repo_slug, split_repo

LIST_LIMIT = 1000
MAX_TICKETS_CAP = 256
MAX_NUMBER = 999_999_999  # issue and artifact numbers; real ones are far smaller
EVENTS = ("issues", "schedule", "workflow_dispatch")
TICKET_TOKEN_RE = re.compile(r"[1-9][0-9]{0,8}")
FINAL_REST_RE = re.compile(r"([1-9][0-9]{0,8})--[0-9]{8}--final--[0-9a-f]{8}")


def _issue_number_and_state(item, where: str) -> tuple[int, str]:
    """number and stateReason. closedAt is not read here: it is null on open and reopened issues."""
    if not isinstance(item, dict):
        raise ToolError("bad_shape", f"{where} must be an object")
    number = item.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= MAX_NUMBER:
        raise ToolError("bad_shape", f"{where}.number must be a positive integer up to {MAX_NUMBER}")
    state = item.get("stateReason")
    if not isinstance(state, str):
        raise ToolError("bad_shape", f"{where}.stateReason must be a string")
    return number, state


def _parse_issue(item, where: str) -> tuple[int, datetime.datetime, str]:
    number, state = _issue_number_and_state(item, where)
    closed = parse_utc(item.get("closedAt"), f"{where}.closedAt")
    return number, closed, state


def _parse_issue_list(data) -> list[tuple[int, datetime.datetime, str]]:
    if not isinstance(data, list):
        raise ToolError("bad_shape", "gh issue list output must be a JSON array")
    if len(data) >= LIST_LIMIT:
        raise ToolError("list_may_be_truncated", f"{len(data)} rows reached --limit {LIST_LIMIT}; narrow backfill-days")
    return [_parse_issue(item, f"issues[{i}]") for i, item in enumerate(data)]


def _parse_artifacts(data) -> list[dict]:
    """Input is the `--paginate --slurp` array: one page object per element, each with artifacts."""
    if not isinstance(data, list):
        raise ToolError("bad_shape", "artifact list must be the --paginate --slurp array")
    out = []
    for p, page in enumerate(data):
        if not isinstance(page, dict) or not isinstance(page.get("artifacts"), list):
            raise ToolError("bad_shape", f"artifact page {p} has no artifacts array")
        for a, art in enumerate(page["artifacts"]):
            if not isinstance(art, dict) or not isinstance(art.get("name"), str) or not isinstance(art.get("expired"), bool):
                raise ToolError("bad_shape", f"artifact {p}.{a} needs a string name and boolean expired")
            out.append({"name": art["name"], "expired": art["expired"]})
    return out


def _final_tickets(repo: str, artifacts: list[dict]) -> set[int]:
    """Tickets with an unexpired --final-- task artifact in this repo. Expired ones do not count."""
    prefix = f"mcq-task--{repo_slug(repo)}--i"
    found = set()
    for art in artifacts:
        if art["expired"] or not art["name"].startswith(prefix):
            continue
        m = FINAL_REST_RE.fullmatch(art["name"][len(prefix):])
        if m:
            found.add(int(m.group(1)))
    return found


def _sort_key(item):
    number, closed = item[0], item[1]
    return (closed, number)


def select_tickets(
    event: str,
    *,
    repo: str,
    now: str,
    gh_issues=None,
    gh_artifacts=None,
    tickets: str | None = None,
    backfill_days: int = 7,
    max_tickets: int = 20,
) -> dict:
    if event not in EVENTS:
        raise ToolError("bad_arguments", f"event must be one of {', '.join(EVENTS)}: {event!r}")
    split_repo(repo)
    now_dt = parse_utc(now, "now")
    check_days(backfill_days, "backfill-days", 1)
    if max_tickets < 1 or max_tickets > MAX_TICKETS_CAP:
        raise ToolError("bad_arguments", f"max-tickets must be 1..{MAX_TICKETS_CAP}: {max_tickets!r}")

    if event == "workflow_dispatch":
        return _manual(tickets)

    if gh_issues is None or gh_artifacts is None:
        raise ToolError("bad_arguments", f"{event} needs the gh issues and artifacts inputs")
    artifacts = _parse_artifacts(gh_artifacts)

    if event == "issues":
        number, state = _issue_number_and_state(gh_issues, "issue")
        if state == "COMPLETED":
            picked, skipped = [number], []
        else:
            picked, skipped = [], [number]
        return _result(picked, [], [], skipped)

    rows = _parse_issue_list(gh_issues)
    window_start = now_dt - datetime.timedelta(days=backfill_days)
    finals = _final_tickets(repo, artifacts)
    candidates = []
    skipped_final, skipped_not_completed = [], []
    for number, closed, state in rows:
        if state != "COMPLETED":
            skipped_not_completed.append(number)
            continue
        if closed < window_start:
            continue
        if number in finals:
            skipped_final.append(number)
            continue
        candidates.append((number, closed))

    candidates.sort(key=_sort_key)
    numbers = [number for number, _ in candidates]
    return _result(
        numbers[:max_tickets],
        numbers[max_tickets:],
        sorted(skipped_final),
        sorted(skipped_not_completed),
    )


def _manual(tickets) -> dict:
    if tickets is None:
        raise ToolError("bad_arguments", "workflow_dispatch needs --tickets")
    found = set()
    for token in tickets.split():
        if not TICKET_TOKEN_RE.fullmatch(token):
            raise ToolError("bad_ticket", f"ticket must be a positive integer: {token!r}")
        found.add(int(token))
    if len(found) > MAX_TICKETS_CAP:
        raise ToolError("too_many_tickets", f"at most {MAX_TICKETS_CAP} tickets per run, got {len(found)}")
    return _result(sorted(found), [], [], [])


def _result(picked, truncated, skipped_final, skipped_not_completed) -> dict:
    return {
        "tickets": picked,
        "truncated": truncated,
        "skipped_final": skipped_final,
        "skipped_not_completed": skipped_not_completed,
    }


def summary_text(event: str, result: dict, max_tickets: int) -> str:
    """Text for the job summary. A truncation line starts with ::warning:: so Actions shows it."""
    lines = [
        f"## mcq-report select ({event})",
        "",
        f"- tickets: {result['tickets']}",
        f"- skipped (already final): {result['skipped_final']}",
        f"- skipped (not completed): {result['skipped_not_completed']}",
    ]
    if result["truncated"]:
        lines.append(
            f"::warning::max-tickets {max_tickets} reached; {len(result['truncated'])} ticket(s) "
            f"deferred to a later run: {result['truncated']}"
        )
    return "\n".join(lines) + "\n"
