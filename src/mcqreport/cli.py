"""mcq-report CLI: `mcq-report index`, `mcq-report name {code,task}`, `mcq-report select`, `mcq-report table`.

Stdlib only. Does not import qmetrics or taskquality, and does not read the clock: times come from --now and friends.
"""

import argparse
import json
import os
import re
import sys

from mcqreport.common import ToolError, parse_utc, read_json_file, render_json
from mcqreport.index import build_index
from mcqreport.names import code_name, task_name
from mcqreport.selection import EVENTS, select_tickets, summary_text
from mcqreport.table import build_table, render_md

EXIT_OK = 0
EXIT_TOOL_ERROR = 2


class MCQArgumentParser(argparse.ArgumentParser):
    """Argument errors become ToolError so they exit with code 2 like every other tool error."""

    def error(self, message: str):
        raise ToolError("bad_arguments", message)


def build_parser() -> argparse.ArgumentParser:
    p = MCQArgumentParser(prog="mcq-report", description="Artifact index, names, and ticket selection for periodic quality reports.")
    sub = p.add_subparsers(dest="cmd", required=True)

    # index
    ix = sub.add_parser("index", help="write index.json for one artifact")
    ix.add_argument("--report", required=True, choices=["code", "task"])
    ix.add_argument("--repo", required=True, help="OWNER/REPO the artifact belongs to")
    ix.add_argument("--qmetrics-ref", required=True)
    ix.add_argument("--python-version", required=True)
    ix.add_argument("--rev", default=None, help="code: commit SHA")
    ix.add_argument("--target", default=None, help="code: target path")
    ix.add_argument("--ticket", default=None, help="task: OWNER/REPO#N")
    ix.add_argument("--search-repo", action="append", default=[], help="task: repo searched by fetch (repeatable)")
    ix.add_argument("--file", action="append", required=True, help="file to list in the index (repeatable)")
    ix.add_argument("--out", required=True, help="output path for index.json")

    # name
    nm = sub.add_parser("name", help="print the artifact name")
    nm_sub = nm.add_subparsers(dest="kind", required=True)

    nc = nm_sub.add_parser("code", help="code report name")
    nc.add_argument("--repo", required=True)
    nc.add_argument("--target", required=True)
    nc.add_argument("--committed-at", required=True, help="committer date of the commit, UTC YYYY-MM-DDTHH:MM:SSZ")
    nc.add_argument("--rev", required=True)

    nt = nm_sub.add_parser("task", help="task report name")
    nt.add_argument("--ticket", required=True, help="OWNER/REPO#N")
    nt.add_argument("--closed-at", required=True, help="ticket closedAt, UTC")
    nt.add_argument("--run-at", required=True, help="time this run computes the name (UTC)")
    nt.add_argument("--report", required=True, help="taskquality-report.json (status and missing are read from it)")
    nt.add_argument("--snapshot", required=True, help="taskquality-snapshot.json (its bytes are hashed)")
    nt.add_argument("--settle-days", type=int, default=2)

    # select
    sl = sub.add_parser("select", help="choose tickets for the task-quality workflow")
    sl.add_argument("--event", required=True, choices=list(EVENTS))
    sl.add_argument("--repo", required=True, help="OWNER/REPO of the calling repository")
    sl.add_argument("--now", required=True, help="current time, UTC (from the workflow; this command never reads the clock)")
    sl.add_argument("--backfill-days", type=int, default=7)
    sl.add_argument("--max-tickets", type=int, default=20)
    sl.add_argument("--gh-issues", default=None, help="schedule: gh issue list JSON; issues: gh issue view JSON")
    sl.add_argument("--gh-artifacts", default=None, help="gh api --paginate --slurp artifacts JSON (schedule and issues)")
    sl.add_argument("--tickets", default=None, help="workflow_dispatch: space-separated ticket numbers")
    sl.add_argument("--summary", default=None, help="write the job summary text here (default: stderr)")

    # table
    tb = sub.add_parser("table", help="weekly table from a directory of taskquality reports")
    tb.add_argument("--reports", required=True, help="directory of taskquality-report *.json (one per ticket)")
    tb.add_argument("--from", dest="window_from", required=True, help="window start, UTC (written to the output only)")
    tb.add_argument("--to", dest="window_to", required=True, help="window end, UTC (written to the output only)")
    tb.add_argument("--costs", default=None, help="cost export directory (not supported yet)")
    tb.add_argument("--population", default=None, help="mcq-weekly-population JSON: closed_at per ticket")
    tb.add_argument("--out", required=True, help="output table JSON")
    tb.add_argument("--md", default=None, help="output Markdown table")

    return p


def _one_line(text: str) -> str:
    """Tool errors are one stderr line: escape control characters."""
    return re.sub(r"[\x00-\x1f\x7f]", lambda m: repr(m.group())[1:-1], text)


def _run_index(args) -> int:
    index = build_index(
        args.report,
        repo=args.repo,
        qmetrics_ref=args.qmetrics_ref,
        python_version=args.python_version,
        file_paths=args.file,
        rev=args.rev,
        target=args.target,
        ticket=args.ticket,
        search_repos=args.search_repo or None,
    )
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_json(index))
    return EXIT_OK


def _run_name(args) -> int:
    if args.kind == "code":
        name = code_name(args.repo, args.target, args.committed_at, args.rev)
    else:
        report = read_json_file(args.report, "report")
        if not isinstance(report, dict) or not isinstance(report.get("status"), str):
            raise ToolError("bad_report", "report needs a string status")
        missing = report.get("missing", [])
        if not isinstance(missing, list):
            raise ToolError("bad_report", "report missing must be a list")
        reasons = [m.get("reason") for m in missing if isinstance(m, dict)]
        with open(args.snapshot, "rb") as fh:
            snapshot = fh.read()
        name = task_name(args.ticket, args.closed_at, args.run_at, report["status"], reasons, snapshot, args.settle_days)
    sys.stdout.write(name + "\n")
    return EXIT_OK


def _read_required(path, label):
    if path is None:
        raise ToolError("bad_arguments", f"{label} is required for this event")
    return read_json_file(path, label)


def _run_select(args) -> int:
    gh_issues = gh_artifacts = None
    if args.event != "workflow_dispatch":
        gh_issues = _read_required(args.gh_issues, "gh-issues")
        gh_artifacts = _read_required(args.gh_artifacts, "gh-artifacts")
    result = select_tickets(
        args.event,
        repo=args.repo,
        now=args.now,
        gh_issues=gh_issues,
        gh_artifacts=gh_artifacts,
        tickets=args.tickets,
        backfill_days=args.backfill_days,
        max_tickets=args.max_tickets,
    )
    sys.stdout.write(json.dumps(result, sort_keys=True, allow_nan=False) + "\n")
    text = summary_text(args.event, result, args.max_tickets)
    if args.summary:
        with open(args.summary, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    else:
        sys.stderr.write(text)
    return EXIT_OK


def _load_reports(directory):
    """Every *.json in the directory: a taskquality-report, one per ticket. Sorted by file name."""
    if not os.path.isdir(directory):
        raise ToolError("bad_reports_dir", f"not a directory: {directory}")
    reports, seen = [], set()
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not name.endswith(".json") or not os.path.isfile(path):
            continue
        report = read_json_file(path, name)
        if not isinstance(report, dict) or report.get("kind") != "taskquality-report":
            raise ToolError("bad_report", f"{name} is not a taskquality-report")
        ticket = report.get("ticket")
        if not isinstance(ticket, str):
            raise ToolError("bad_report", f"{name} needs a string ticket")
        if ticket in seen:
            raise ToolError("duplicate_ticket", f"more than one report for {ticket}")
        seen.add(ticket)
        reports.append(report)
    return reports


def _load_population(path):
    """closed_at per ticket from an mcq-weekly-population file. Other fields are not read here."""
    population = read_json_file(path, "population")
    if not isinstance(population, dict) or population.get("kind") != "mcq-weekly-population":
        raise ToolError("bad_population", "population is not an mcq-weekly-population")
    tickets = population.get("tickets")
    if not isinstance(tickets, list):
        raise ToolError("bad_population", "population tickets must be a list")
    closed = {}
    for item in tickets:
        if not isinstance(item, dict) or not isinstance(item.get("ticket"), str):
            raise ToolError("bad_population", "each population ticket needs a string ticket")
        value = item.get("closed_at")
        if value is not None:
            parse_utc(value, "closed_at")
        closed[item["ticket"]] = value
    return closed


def _run_table(args) -> int:
    if args.costs is not None:
        raise ToolError("not_supported", "--costs is not supported yet")
    parse_utc(args.window_from, "--from")
    parse_utc(args.window_to, "--to")
    window = {"from": args.window_from, "to": args.window_to}
    reports = _load_reports(args.reports)
    closed_at = _load_population(args.population) if args.population is not None else None
    table = build_table(reports, window, closed_at=closed_at)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_json(table))
    if args.md is not None:
        with open(args.md, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_md(table))
    return EXIT_OK


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.cmd == "index":
            return _run_index(args)
        if args.cmd == "name":
            return _run_name(args)
        if args.cmd == "table":
            return _run_table(args)
        return _run_select(args)
    except ToolError as e:
        sys.stderr.write(f"mcq-report: error {e.code}: {_one_line(e.message)}\n")
        return EXIT_TOOL_ERROR
    except OSError as e:
        sys.stderr.write(f"mcq-report: error unreadable: {_one_line(str(e))}\n")
        return EXIT_TOOL_ERROR
    except (ValueError, OverflowError, RecursionError) as e:
        # Last line of defence for input that slips past the explicit checks: still one line, still exit 2.
        sys.stderr.write(f"mcq-report: error bad_input: {_one_line(str(e))}\n")
        return EXIT_TOOL_ERROR


if __name__ == "__main__":
    sys.exit(main())
