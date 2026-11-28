"""`run`: per-ticket snapshot reuse/fetch, cost input, score, then publish one run directory via out.json."""

import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcqreport.common import ToolError, parse_utc, read_json_file
from taskquality.conventions import DEFAULT_CONFIG
from taskquality.fetch import default_runner, fetch_snapshot
from taskquality.formats import parse_pr_id, read_json_file as tq_read_json_file, validate_input, validate_snapshot
from taskquality.score import score_ticket
from mcqweekly import __version__ as TOOL_VERSION
from mcqweekly.errors import TOOL_ERRORS
from mcqweekly.fsio import ensure_private_dir, fsync_dir, private_existing_file, render, replace_atomically, write_new_file
from mcqweekly.repos import check_repo, is_v1
from mcqweekly.safety import private_location
from mcqweekly.select import RULES

EXIT_OK = 0
EXIT_INCOMPLETE = 3
REPO_STATUSES = {"ok", "list_failed", "truncated"}
LEVELS = {"c", "d"}


class Counting:
    """Wraps the gh runner: counts invocations and `gh api` requests (no --paginate is used, so one call is one page)."""

    def __init__(self, inner: Callable[[list[str]], Any]):
        self.inner = inner
        self.gh_calls = 0
        self.api_pages = 0

    def __call__(self, argv: list[str]):
        self.gh_calls += 1
        if argv[:2] == ["gh", "api"]:
            self.api_pages += 1
        return self.inner(argv)


class CountSleep:
    def __init__(self, inner: Callable[[float], None]):
        self.inner = inner
        self.waits = 0

    def __call__(self, seconds: float) -> None:
        self.waits += 1
        self.inner(seconds)


def ticket_key(ticket: str) -> tuple[str, int]:
    owner_repo, num = parse_pr_id(ticket, "bad_population")
    return owner_repo.lower(), num


def snapshot_name(ticket: str) -> str:
    owner_repo, num = parse_pr_id(ticket, "bad_population")
    owner, repo = owner_repo.split("/", 1)
    return f"{owner}__{repo}__{num}".lower()


def load_population(path: str) -> dict:
    data = read_json_file(path, "population")
    if data.get("kind") != "mcq-weekly-population" or not is_v1(data.get("schema_version")):
        raise ToolError("bad_population", "population must have kind='mcq-weekly-population' and schema_version=1")
    if data.get("rules") != RULES:
        raise ToolError("bad_population", f"population rules must be {RULES!r}")
    window = data.get("window")
    if not isinstance(window, dict):
        raise ToolError("bad_population", "population window must be an object")
    lo = parse_utc(window.get("from"), "window.from")
    hi = parse_utc(window.get("to"), "window.to")
    if not lo < hi:
        raise ToolError("bad_window", "window.from must be before window.to")
    parse_utc(data.get("as_of"), "as_of")

    repos = data.get("repos")
    if not isinstance(repos, list):
        raise ToolError("bad_population", "population repos must be a list")
    names = {}
    for row in repos:
        if not isinstance(row, dict) or row.get("status") not in REPO_STATUSES:
            raise ToolError("bad_population", "population repo row is malformed")
        if type(row.get("tickets_seen")) is not int or row["tickets_seen"] < 0:
            raise ToolError("bad_population", "population tickets_seen must be a non-negative integer")
        check_repo(row.get("repo"), "bad_population")
        if row["repo"].lower() in names:
            raise ToolError("bad_population", "population repos repeat (case-insensitive)")
        names[row["repo"].lower()] = row["repo"]

    tickets = data.get("tickets")
    if not isinstance(tickets, list):
        raise ToolError("bad_population", "population tickets must be a list")
    seen = set()
    for t in tickets:
        if not isinstance(t, dict) or t.get("level") not in LEVELS:
            raise ToolError("bad_population", "population ticket row is malformed")
        owner_repo, _ = parse_pr_id(t.get("ticket"), "bad_population")
        if owner_repo.lower() not in names:
            raise ToolError("bad_population", "population ticket repo is not in population repos")
        parse_utc(t.get("closed_at"), "closed_at")
        key = ticket_key(t["ticket"])
        if key in seen:
            raise ToolError("bad_population", "population repeats a ticket")
        seen.add(key)
    return data


def load_valid_snapshot(path: Path, ticket: str) -> dict | None:
    """Reuse only a snapshot whose kind, schema, ticket and shape all check out; anything else means 'absent'."""
    try:
        snap = tq_read_json_file(str(path), "snapshot")
        if snap.get("kind") != "taskquality-snapshot" or not is_v1(snap.get("schema_version")):
            return None
        if snap.get("ticket") != ticket:
            return None
        validate_snapshot(snap)
    except TOOL_ERRORS:
        return None
    return snap


def load_cost_input(costs: Path, name: str, ticket: str) -> dict | None:
    path = costs / f"{name}.json"
    if os.path.islink(path):
        target = os.path.realpath(path)
        if os.path.commonpath([target, str(costs)]) != str(costs):
            raise ToolError("unsafe_path", "cost file links outside the costs directory")
    if not os.path.lexists(path):
        return None
    data = tq_read_json_file(str(path), "input")
    validate_input(data, ticket)
    return data


def incomplete_reasons(population: dict, failed: list[dict]) -> list[dict]:
    """Repo-level then ticket-level reasons, one total order: (kind, lowercase name, reason); identical items collapse."""
    found = set()
    for row in population["repos"]:
        if row["status"] != "ok":
            found.add((0, row["repo"].lower(), row["repo"], row["status"]))
    for f in failed:
        found.add((1, f["ticket"].lower(), f["ticket"], f"{f['stage']}:{f['code']}"))
    out = []
    for _kind, _low, name, reason in sorted(found):
        if _kind == 0:
            out.append({"repo": name, "reason": reason})
        else:
            out.append({"ticket": name, "reason": reason})
    return out


def failed_record(ticket: str, stage: str, code: str) -> dict:
    return {"ticket": ticket, "stage": stage, "code": code}


def next_run_dir(runs: Path) -> Path:
    numbers = [int(p.name) for p in runs.iterdir() if p.is_dir() and re.fullmatch(r"[0-9]+", p.name)]
    path = runs / f"{max(numbers, default=0) + 1:03d}"
    try:
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
    except OSError as e:
        raise ToolError("write_failed", f"cannot create run directory: {e.strerror}") from None
    return path


def run_weekly(
    population_path: str,
    work: str,
    costs: str | None,
    refetch: bool,
    offline: bool,
    table_api: Any,
    runner: Callable[[list[str]], Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
    time_func: Callable[[], float] | None = None,
) -> int:
    """Run the weekly table. Returns 0 (complete) or 3 (failed tickets or incomplete population). Raises ToolError for exit 2."""
    if refetch and offline:
        raise ToolError("bad_arguments", "--offline and --refetch are mutually exclusive")
    population = load_population(population_path)
    work_dir = private_location(work, "--work")
    costs_dir = private_location(costs, "--costs") if costs is not None else None
    if costs_dir is not None and not costs_dir.is_dir():
        raise ToolError("costs_missing", "--costs must be an existing directory")
    ensure_private_dir(work_dir, parents=True)
    snapshots = ensure_private_dir(work_dir / "snapshots")
    runs = ensure_private_dir(work_dir / "runs")

    counting = Counting(runner if runner is not None else default_runner)
    sleep_count = CountSleep(sleeper if sleeper is not None else time.sleep)
    actual_time = time_func if time_func is not None else time.time
    search_repos = [row["repo"] for row in population["repos"]]

    reports: list[tuple[str, dict]] = []
    failed: list[dict] = []
    fetched = 0
    reused = 0
    prs = 0
    tickets = sorted(population["tickets"], key=lambda t: ticket_key(t["ticket"]))
    for t in tickets:
        ticket = t["ticket"]
        name = snapshot_name(ticket)
        snap_path = snapshots / f"{name}.json"
        if os.path.islink(snap_path):
            raise ToolError("unsafe_path", "snapshot path is a symlink")

        snapshot = None
        if os.path.lexists(snap_path) and not refetch:
            snapshot = load_valid_snapshot(snap_path, ticket)
            if snapshot is not None:
                private_existing_file(snap_path)
                reused += 1
        if snapshot is None:
            if offline:
                failed.append(failed_record(ticket, "fetch", "offline_missing"))
                continue
            try:
                snapshot = fetch_snapshot(
                    ticket, out_path=snap_path, search_repos=search_repos,
                    runner=counting, sleeper=sleep_count, time_func=actual_time,
                )
            except TOOL_ERRORS as e:
                failed.append(failed_record(ticket, "fetch", e.code))
                continue
            private_existing_file(snap_path)
            fetched += 1

        input_data = None
        if costs_dir is not None:
            try:
                input_data = load_cost_input(costs_dir, name, ticket)
            except TOOL_ERRORS as e:
                failed.append(failed_record(ticket, "cost_input", e.code))
                continue

        try:
            report = score_ticket(snapshot, input_data, DEFAULT_CONFIG)
        except TOOL_ERRORS as e:
            failed.append(failed_record(ticket, "score", e.code))
            continue
        reports.append((name, report))
        prs += len(snapshot["prs"])

    failed = sorted({(f["ticket"], f["stage"], f["code"]): f for f in failed}.values(),
                    key=lambda f: (f["ticket"], f["stage"], f["code"]))
    reasons = incomplete_reasons(population, failed)
    window = population["window"]
    closed_at = {t["ticket"]: t["closed_at"] for t in population["tickets"]}
    try:
        table = table_api.build_table(
            [report for _name, report in reports],
            {"from": window["from"], "to": window["to"]},
            closed_at=closed_at,
            incomplete_reasons=reasons,
        )
        table["failed_tickets"] = failed  # driver key (docs/weekly-driver.md); incomplete and incomplete_reasons come from build_table
        md = table_api.render_md(table)
    except Exception as e:
        raise ToolError("table_failed", f"table step failed: {type(e).__name__}") from None
    if reasons:
        md = md.rstrip("\n") + f"\n\n> 不完整：{len(reasons)} 項（見 table.json 的 incomplete_reasons）\n"
    else:
        md = md.rstrip("\n") + "\n"

    exit_code = EXIT_INCOMPLETE if (failed or reasons) else EXIT_OK
    run = {
        "kind": "mcq-weekly-run",
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "window": window,
        "repos": search_repos,
        "tickets": len(tickets),
        "fetched": fetched,
        "reused": reused,
        "failed": failed,
        "prs": prs,
        "gh_calls": counting.gh_calls,
        "api_pages": counting.api_pages,
        "rate_limit_waits": sleep_count.waits,
        "exit_code": exit_code,
    }

    publish(work_dir, runs, population, reports, table, md, run)
    return exit_code


def publish(work_dir: Path, runs: Path, population: dict, reports, table: dict, md: str, run: dict) -> None:
    """Write everything into a fresh runs/<n>/ (fsync each file, then the directory), then switch out.json atomically."""
    try:
        run_dir = next_run_dir(runs)
        reports_dir = run_dir / "reports"
        reports_dir.mkdir(mode=0o700)
        os.chmod(reports_dir, 0o700)
        for name, report in reports:
            write_new_file(reports_dir / f"{name}.json", render(report))
        fsync_dir(reports_dir)
        write_new_file(run_dir / "population.json", render(population))
        write_new_file(run_dir / "table.json", render(table))
        write_new_file(run_dir / "table.md", md)
        write_new_file(run_dir / "run.json", render(run))
        fsync_dir(run_dir)
    except OSError as e:
        raise ToolError("write_failed", f"cannot write run: {e.strerror}") from None
    replace_atomically(work_dir / "out.json", render({"current": f"runs/{run_dir.name}"}))
