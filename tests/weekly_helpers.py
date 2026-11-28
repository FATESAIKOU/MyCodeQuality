"""Synthetic helpers for mcq-weekly tests: fake gh runners, repos/population writers, a fake table. Nothing touches the network."""

import json
from pathlib import Path

FROM = "2026-11-21T00:00:00Z"
TO = "2026-11-28T00:00:00Z"
AS_OF = "2026-11-28T06:00:00Z"
GRAPHQL_EMPTY = json.dumps({"data": {"repository": {"issue": {"timelineItems": {"pageInfo": {"hasNextPage": False}, "nodes": []}}}}})


def issue_row(number, closed, labels=("層級:c",), reason="COMPLETED"):
    return {"number": number, "labels": [{"name": name} for name in labels], "closedAt": closed, "stateReason": reason}


def list_runner(by_repo):
    """Fake `gh issue list`: by_repo maps repo -> list of rows (JSON) or a (stdout, stderr, code) tuple."""
    calls = []

    def runner(argv):
        calls.append(argv)
        assert argv[:3] == ["gh", "issue", "list"], argv
        repo = argv[argv.index("-R") + 1]
        answer = by_repo[repo]
        if isinstance(answer, tuple):
            return answer
        return json.dumps(answer), "", 0

    runner.calls = calls
    return runner


def write_repos(path: Path, repos) -> Path:
    path.write_text(json.dumps({"kind": "mcq-weekly-repos", "schema_version": 1, "repos": list(repos)}), encoding="utf-8")
    return path


def write_population(path: Path, repos, tickets, window=(FROM, TO), statuses=None) -> Path:
    statuses = statuses or {}
    pop = {
        "kind": "mcq-weekly-population",
        "schema_version": 1,
        "tool_version": "test",
        "rules": "closed-completed-cd-v1",
        "window": {"from": window[0], "to": window[1]},
        "as_of": AS_OF,
        "repos": [{"repo": r, "status": statuses.get(r, "ok"), "tickets_seen": 0} for r in repos],
        "tickets": tickets,
    }
    path.write_text(json.dumps(pop), encoding="utf-8")
    return path


def ticket_row(ticket, closed_at=FROM, level="c"):
    return {"ticket": ticket, "closed_at": closed_at, "level": level}


def fake_table_api():
    """Stands in for mcqreport.table (#62 not merged). Mirrors the contract: incomplete / incomplete_reasons come from the argument."""

    def build_table(reports, window, closed_at=None, incomplete_reasons=None):
        reasons = list(incomplete_reasons or [])
        return {
            "kind": "mcq-weekly-table",
            "schema_version": 1,
            "tool_version": "fake",
            "window": dict(window),
            "rows": [{"ticket": r["ticket"], "closed_at": (closed_at or {}).get(r["ticket"])} for r in reports],
            "summary": {"tickets": len(reports)},
            "flags": [],
            "incomplete": bool(reasons),
            "incomplete_reasons": reasons,
        }

    def render_md(table):
        lines = ["| ticket | closed_at |", "| --- | --- |"]
        lines += [f"| {r['ticket']} | {r['closed_at']} |" for r in table["rows"]]
        return "\n".join(lines) + "\n"

    from types import SimpleNamespace

    return SimpleNamespace(build_table=build_table, render_md=render_md)


def no_gh_runner(argv):
    raise AssertionError(f"gh must not be called: {argv[:3]}")
