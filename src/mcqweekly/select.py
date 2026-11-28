"""`select`: online population of closed, completed, leveled tickets for a window (frozen to a file for later runs)."""

import datetime
import json
import time
from collections.abc import Callable
from typing import Any

from mcqreport.common import parse_utc
from taskquality.fetch import default_runner, execute_with_retry
from mcqweekly import __version__ as TOOL_VERSION
from mcqweekly.errors import TOOL_ERRORS
from mcqweekly.repos import check_repo

RULES = "closed-completed-cd-v1"
STATE_REASON = "COMPLETED"
# Label names are module constants so a later config change is one edit.
LEVEL_LABELS = ("層級:c", "層級:d")
LIST_LIMIT = 1000
DEFAULT_MAX_TICKETS = 500
MAX_TICKETS_CAP = 5000
LIST_FIELDS = "number,labels,closedAt,stateReason"


class ListFailed(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def level_of(label_names: set[str]) -> str | None:
    """Both levels present → "c" (c is the larger level); otherwise whichever one is present."""
    if LEVEL_LABELS[0] in label_names:
        return "c"
    if LEVEL_LABELS[1] in label_names:
        return "d"
    return None


def label_names(labels: list) -> set[str]:
    names = set()
    for item in labels:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
        elif isinstance(item, str):
            names.add(item)
    return names


def search_dates(window_from: datetime.datetime, window_to: datetime.datetime) -> str:
    """GitHub `closed:` range, widened by one day on each side; exact filtering happens on closedAt."""
    lo = (window_from - datetime.timedelta(days=1)).date().isoformat()
    hi = (window_to + datetime.timedelta(days=1)).date().isoformat()
    return f"closed:{lo}..{hi}"


def parse_items(stdout: str) -> list[dict]:
    """gh issue list JSON. Any shape problem fails the whole repo (list_failed), never a partial list."""
    try:
        items = json.loads(stdout)
    except ValueError:
        raise ListFailed("bad_json") from None
    if not isinstance(items, list):
        raise ListFailed("bad_shape")
    for item in items:
        if not isinstance(item, dict) or type(item.get("number")) is not int:
            raise ListFailed("bad_shape")
        if not isinstance(item.get("labels"), list) or not isinstance(item.get("stateReason"), str):
            raise ListFailed("bad_shape")
        try:
            parse_utc(item.get("closedAt"), "closedAt")
        except TOOL_ERRORS:
            raise ListFailed("bad_shape") from None
    return items


def list_repo(repo: str, window_from, window_to, runner, sleeper, time_func) -> tuple[list[dict], str | None]:
    """Return (raw gh rows, failure_code). One gh call per repo; gh issue list pages internally."""
    argv = [
        "gh", "issue", "list", "-R", repo, "--state", "closed",
        "--search", search_dates(window_from, window_to),
        "--limit", str(LIST_LIMIT), "--json", LIST_FIELDS,
    ]
    try:
        stdout, _stderr, code = execute_with_retry(argv, runner, sleeper, time_func)
    except TOOL_ERRORS as e:
        return [], e.code
    if code != 0:
        return [], "gh_failed"
    try:
        return parse_items(stdout), None
    except ListFailed as e:
        return [], e.code


def build_population(
    repos: list[str],
    window_from: datetime.datetime,
    window_to: datetime.datetime,
    as_of: str,
    max_tickets: int,
    runner: Callable[[list[str]], Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
    time_func: Callable[[], float] | None = None,
) -> dict:
    """Population dict. Repos sorted by lowercase name; tickets by (repo.lower(), number). Content depends only on gh answers and arguments."""
    actual_runner = runner if runner is not None else default_runner
    actual_sleeper = sleeper if sleeper is not None else time.sleep
    actual_time = time_func if time_func is not None else time.time

    repo_rows = []
    tickets = []
    for repo in sorted(repos, key=str.lower):
        check_repo(repo)
        items, failure = list_repo(repo, window_from, window_to, actual_runner, actual_sleeper, actual_time)
        if failure is not None:
            repo_rows.append({"repo": repo, "status": "list_failed", "tickets_seen": 0})
            continue

        eligible = []
        for item in items:
            closed_at = item["closedAt"]
            if not (window_from <= parse_utc(closed_at, "closedAt") < window_to):
                continue
            if item["stateReason"] != STATE_REASON:
                continue
            level = level_of(label_names(item["labels"]))
            if level is None:
                continue
            eligible.append({"ticket": f"{repo}#{item['number']}", "closed_at": closed_at, "level": level})

        status = "truncated" if len(items) >= LIST_LIMIT else "ok"
        eligible.sort(key=lambda t: (t["closed_at"], t["ticket"]))
        if len(eligible) > max_tickets:
            eligible = eligible[:max_tickets]
            status = "truncated"
        repo_rows.append({"repo": repo, "status": status, "tickets_seen": len(items)})
        tickets.extend(eligible)

    tickets.sort(key=lambda t: (t["ticket"].rsplit("#", 1)[0].lower(), int(t["ticket"].rsplit("#", 1)[1])))
    return {
        "kind": "mcq-weekly-population",
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "rules": RULES,
        "window": {"from": _utc(window_from), "to": _utc(window_to)},
        "as_of": as_of,
        "repos": repo_rows,
        "tickets": tickets,
    }


def _utc(value: datetime.datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
