"""qmetrics CLI: `qmetrics diff` with three ways to name the base and head commits."""

import argparse
import json
import sys

from qmetrics import SCHEMA_VERSION, __version__
from qmetrics import gitio, metrics

EXIT_TOOL_ERROR = 2


def build_parser():
    p = argparse.ArgumentParser(prog="qmetrics", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diff", help="static quality numbers for one base..head diff")
    d.add_argument("--repo", default=".", help="path inside the working tree (default: .)")
    d.add_argument("--merge", metavar="COMMIT", help="merge commit: base is its first parent")
    d.add_argument("--pr-base", metavar="REV", help="PR mode: base end (base = merge-base)")
    d.add_argument("--pr-head", metavar="REV", help="PR mode: head end")
    d.add_argument("--base", metavar="SHA", help="explicit base (needs --head)")
    d.add_argument("--head", metavar="SHA", help="explicit head (needs --base)")
    d.add_argument("--src", default="src")
    d.add_argument("--tests", default="tests")
    d.add_argument("--json", action="store_true", help="print the JSON report instead of the summary")
    return p


def pick_mode(a):
    modes = []
    if a.merge:
        modes.append("merge")
    if a.pr_base or a.pr_head:
        modes.append("pr")
    if a.base or a.head:
        modes.append("given")
    if len(modes) != 1:
        raise gitio.ToolError("bad_arguments", "give exactly one of: --merge | --pr-base+--pr-head | --base+--head")
    if modes[0] == "pr" and not (a.pr_base and a.pr_head):
        raise gitio.ToolError("bad_arguments", "PR mode needs both --pr-base and --pr-head")
    if modes[0] == "given" and not (a.base and a.head):
        raise gitio.ToolError("bad_arguments", "--base and --head must be given together")
    return modes[0]


def run_diff(a):
    mode = pick_mode(a)
    with gitio.make_home() as home:
        git = gitio.Git(a.repo, home)
        warnings = gitio.preflight(git)  # (g) before any base is resolved
        if mode == "merge":
            base, head = gitio.first_parent(git, a.merge)
            basis = "first_parent"
        elif mode == "pr":
            base, head = gitio.merge_base(git, a.pr_base, a.pr_head)
            basis = "merge_base"
        else:
            base, head = gitio.resolve_commit(git, a.base), gitio.resolve_commit(git, a.head)
            basis = "given"
        result = metrics.analyze(git, base, head, a.src, a.tests)
        return {
            "schema_version": SCHEMA_VERSION,
            "tool_version": __version__,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "git_version": git.version(),
            "base": base, "head": head, "basis": basis,
            "src": a.src, "tests": a.tests,
            **result,
            "warnings": warnings,
        }


def render_json(report):
    return json.dumps(report, sort_keys=True, indent=2) + "\n"


def show(v):
    if v is None:
        return "unknown"
    return str(v).lower() if isinstance(v, bool) else str(v)


def render_summary(r):
    out = [f"qmetrics {r['tool_version']} (schema {r['schema_version']}, python {r['python_version']},"
           f" git {r['git_version']})",
           f"base {r['base']} ({r['basis']})", f"head {r['head']}"]
    if r["parse_failures"]:
        out.append(f"INCOMPLETE: {len(r['parse_failures'])} parse failure(s); null values are"
                   " undetermined, listed events are a lower bound")
    if not r["applicable"]:
        out.append(f"not applicable: no .py files under {r['src']}")
    else:
        out.append(f"code_change: {show(r['code_change'])}")
        out += [f"{k}: {show(v)}" for k, v in sorted(r["counts"].items())]
        out.append(f"grew_over50: {show(r['grew_over50'])}")
        for e in r["events"]:
            if e["kind"] != "changed_function":
                out.append(f"  {e['kind']} {e['file']} {e['function'] or '-'} {e['before']} -> {e['after']}")
    out.append(f"tests_touched: {str(r['tests_touched']).lower()}")
    out.append(f"net_new_tests: {show(r['net_new_tests'])}")
    for f in r["parse_failures"]:
        out.append(f"parse_failure ({f['scope']}, {f['side']}): {f['file']} -> undetermined")
    out += [f"warning: {w}" for w in r["warnings"]]
    return "\n".join(out) + "\n"


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        report = run_diff(args)
    except gitio.ToolError as e:
        print(f"qmetrics: error {e.code}: {e.message}", file=sys.stderr)
        return EXIT_TOOL_ERROR
    sys.stdout.write(render_json(report) if args.json else render_summary(report))
    return 0
