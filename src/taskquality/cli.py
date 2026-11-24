"""taskquality CLI: `taskquality fetch`, `taskquality score`, and `taskquality defaults`."""

import argparse
import re
import sys

from taskquality.conventions import DEFAULT_CONFIG
from taskquality.fetch import fetch_snapshot
from taskquality.formats import (
    ToolError,
    parse_pr_id,
    read_json_file,
    render_json,
    validate_config,
    validate_input,
    validate_snapshot,
)
from taskquality.score import score_ticket

EXIT_OK = 0
EXIT_TOOL_ERROR = 2


class TaskQualityArgumentParser(argparse.ArgumentParser):
    """Custom parser raising ToolError on argument parsing errors."""

    def error(self, message: str):
        raise ToolError("bad_arguments", message)


def build_parser() -> argparse.ArgumentParser:
    p = TaskQualityArgumentParser(prog="taskquality", description="Task quality metrics for a ticket.")
    sub = p.add_subparsers(dest="cmd", required=True)

    # fetch
    f = sub.add_parser("fetch", help="fetch ticket snapshot from GitHub API")
    f.add_argument("--ticket", required=True, help="ticket identifier, OWNER/REPO#N")
    f.add_argument("--search-repo", action="append", nargs="*", default=[], help="filter candidate PRs by repo (optional, repeatable)")
    f.add_argument("--pr", action="append", nargs="*", default=[], help="explicit PR identifier to include, OWNER/REPO#N (optional, repeatable)")
    f.add_argument("--out", required=True, help="output path for snapshot JSON")

    # score
    s = sub.add_parser("score", help="calculate task quality metrics for a ticket snapshot")
    s.add_argument("--snapshot", required=True, help="path to taskquality snapshot JSON")
    s.add_argument("--input", default=None, help="path to external input JSON (optional)")
    s.add_argument("--config", default=None, help="path to custom config JSON (optional)")
    s.add_argument("--json", action="store_true", help="output JSON report")

    # defaults
    sub.add_parser("defaults", help="print built-in default config JSON")

    return p


def _one_line(text: str) -> str:
    """Tool errors are one stderr line: escape control characters."""
    return re.sub(r"[\x00-\x1f\x7f]", lambda m: repr(m.group())[1:-1], text)


def render_score_summary(report: dict) -> str:
    out = [
        f"taskquality {report['tool_version']} (schema {report['schema_version']})",
        f"ticket {report['ticket']}",
        f"status: {report['status']}",
        f"clean: {'unknown' if report['clean'] is None else str(report['clean']).lower()}",
    ]
    m = report["metrics"]
    out.append(f"prs: merged={m['prs_merged']} open={m['prs_open']} closed_unmerged={m['prs_closed_unmerged']}")

    def fmt_v(val):
        if val is None:
            return "unknown"
        if isinstance(val, dict) and "num" in val and "den" in val:
            return f"{val['num']}/{val['den']}"
        return str(val)

    out.append(
        f"review_first_pass: {fmt_v(m['review_first_pass'])} "
        f"fix_rounds: {fmt_v(m['fix_rounds'])} "
        f"re_reviews: {fmt_v(m['re_reviews'])}"
    )
    out.append(f"ci_first_green: {fmt_v(m['ci_first_green'])} prs_without_ci: {m['prs_without_ci']}")
    out.append(f"cycle_seconds: {fmt_v(m['cycle_seconds'])} rework_prs: {fmt_v(m['rework_prs'])}")
    if report["missing"]:
        out.append(f"missing fields: {len(report['missing'])}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except ToolError as e:
        sys.stderr.write(f"taskquality: error {e.code}: {_one_line(e.message)}\n")
        return EXIT_TOOL_ERROR

    if args.cmd == "defaults":
        sys.stdout.write(render_json(DEFAULT_CONFIG))
        return EXIT_OK

    if args.cmd == "fetch":
        try:
            parse_pr_id(args.ticket, "bad_arguments")
            search_repos = []
            for item in args.search_repo:
                if isinstance(item, list):
                    search_repos.extend(item)
                else:
                    search_repos.append(item)
            for r in search_repos:
                if not isinstance(r, str) or "/" not in r:
                    raise ToolError("bad_arguments", f"invalid search repo format: {r!r}")

            explicit_prs = []
            for item in args.pr:
                if isinstance(item, list):
                    explicit_prs.extend(item)
                else:
                    explicit_prs.append(item)
            for p in explicit_prs:
                parse_pr_id(p, "bad_arguments")

            fetch_snapshot(
                ticket=args.ticket,
                out_path=args.out,
                search_repos=search_repos if search_repos else None,
                explicit_prs=explicit_prs if explicit_prs else None,
            )
        except ToolError as e:
            sys.stderr.write(f"taskquality: error {e.code}: {_one_line(e.message)}\n")
            return EXIT_TOOL_ERROR
        return EXIT_OK

    if args.cmd == "score":
        try:
            snapshot = read_json_file(args.snapshot, "snapshot")
            validate_snapshot(snapshot)

            input_data = None
            if args.input:
                input_data = read_json_file(args.input, "input")
                validate_input(input_data, snapshot["ticket"])

            if args.config:
                config = read_json_file(args.config, "config")
                validate_config(config)
            else:
                config = DEFAULT_CONFIG

            report = score_ticket(snapshot, input_data, config)
        except ToolError as e:
            sys.stderr.write(f"taskquality: error {e.code}: {_one_line(e.message)}\n")
            return EXIT_TOOL_ERROR

        sys.stdout.write(render_json(report) if args.json else render_score_summary(report))
        return EXIT_OK

    return EXIT_TOOL_ERROR


if __name__ == "__main__":
    sys.exit(main())
