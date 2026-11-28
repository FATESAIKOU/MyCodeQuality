"""mcq-weekly CLI: `mcq-weekly select` (online population) and `mcq-weekly run` (offline-capable table build).

Exit codes: 0 complete; 2 usage, config, privacy or write error; 3 failed tickets or incomplete population (output still written).
"""

import argparse
import sys
from types import SimpleNamespace

from mcqreport.common import ToolError, parse_utc
from mcqweekly._table import load_table_api
from mcqweekly.errors import TOOL_ERRORS
from mcqweekly.fsio import render, replace_atomically
from mcqweekly.repos import load_repos
from mcqweekly.run import EXIT_INCOMPLETE, EXIT_OK, run_weekly
from mcqweekly.safety import private_location
from mcqweekly.select import DEFAULT_MAX_TICKETS, MAX_TICKETS_CAP, build_population

EXIT_TOOL_ERROR = 2


class WeeklyArgumentParser(argparse.ArgumentParser):
    """Argument errors become ToolError so they exit 2 with the one-line stderr format."""

    def error(self, message: str):
        raise ToolError("bad_arguments", message)


def build_parser() -> argparse.ArgumentParser:
    p = WeeklyArgumentParser(prog="mcq-weekly", description="Weekly quality table driver for closed tickets.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sel = sub.add_parser("select", help="query GitHub once and freeze the population of eligible tickets")
    sel.add_argument("--repos", required=True, help="repos JSON (kind mcq-weekly-repos)")
    sel.add_argument("--from", dest="window_from", required=True, help="window start, UTC YYYY-MM-DDTHH:MM:SSZ (included)")
    sel.add_argument("--to", dest="window_to", required=True, help="window end, UTC YYYY-MM-DDTHH:MM:SSZ (excluded)")
    sel.add_argument("--as-of", required=True, help="caller's label for the data cut-off (a marker only; gh always reads the current state)")
    sel.add_argument("--max-tickets", type=int, default=DEFAULT_MAX_TICKETS, help=f"per repo, 1..{MAX_TICKETS_CAP}")
    sel.add_argument("--out", required=True, help="population JSON to write (must be outside git worktrees)")

    run = sub.add_parser("run", help="build snapshots, reports and the weekly table from a frozen population")
    run.add_argument("--population", required=True, help="population JSON written by select")
    run.add_argument("--work", required=True, help="private work directory (must be outside git worktrees)")
    run.add_argument("--costs", default=None, help="cost-export directory with <owner>__<repo>__<n>.json inputs (optional)")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--refetch", action="store_true", help="re-fetch snapshots instead of reusing them")
    mode.add_argument("--offline", action="store_true", help="never call gh; missing snapshots become failed tickets")
    return p


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def cmd_select(args, deps) -> int:
    lo = parse_utc(args.window_from, "--from")
    hi = parse_utc(args.window_to, "--to")
    if not lo < hi:
        raise ToolError("bad_window", "--from must be before --to")
    parse_utc(args.as_of, "--as-of")
    if not 1 <= args.max_tickets <= MAX_TICKETS_CAP:
        raise ToolError("bad_arguments", f"--max-tickets must be 1..{MAX_TICKETS_CAP}")
    repos = load_repos(args.repos)
    out = private_location(args.out, "--out")
    population = build_population(
        repos, lo, hi, args.as_of, args.max_tickets,
        runner=deps.runner, sleeper=deps.sleeper, time_func=deps.time_func,
    )
    replace_atomically(out, render(population))
    truncated = sum(1 for r in population["repos"] if r["status"] == "truncated")
    failed = sum(1 for r in population["repos"] if r["status"] == "list_failed")
    sys.stderr.write(
        f"mcq-weekly: select repos={len(repos)} tickets={len(population['tickets'])} "
        f"truncated={truncated} list_failed={failed}\n"
    )
    return EXIT_INCOMPLETE if truncated or failed else EXIT_OK


def cmd_run(args, deps) -> int:
    table_api = deps.table_api if deps.table_api is not None else load_table_api()
    code = run_weekly(
        args.population, args.work, args.costs,
        refetch=args.refetch, offline=args.offline, table_api=table_api,
        runner=deps.runner, sleeper=deps.sleeper, time_func=deps.time_func,
    )
    sys.stderr.write(f"mcq-weekly: run exit={code}\n")
    return code


def main(argv=None, *, runner=None, sleeper=None, time_func=None, table_api=None) -> int:
    """Injection points (tests and callers): gh runner, sleeper, clock for rate-limit math, table API."""
    deps = SimpleNamespace(runner=runner, sleeper=sleeper, time_func=time_func, table_api=table_api)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.cmd == "select":
            return cmd_select(args, deps)
        return cmd_run(args, deps)
    except TOOL_ERRORS as e:
        sys.stderr.write(f"mcq-weekly: error {e.code}: {_one_line(e.message)}\n")
        return EXIT_TOOL_ERROR
    except Exception as e:
        sys.stderr.write(f"mcq-weekly: error internal_error: {type(e).__name__}\n")
        return EXIT_TOOL_ERROR
