"""mcq-weekly select: eligibility rules, window edges, list failures, truncation, determinism (fake gh runner only)."""

import json

import pytest

from mcqweekly.cli import main
from weekly_helpers import FROM, TO, issue_row, list_runner, write_repos

R1 = "acme/alpha"
R2 = "acme/beta"


def run_select(tmp_path, repos, by_repo, max_tickets=None, name="population.json"):
    repos_file = write_repos(tmp_path / "repos.json", repos)
    out = tmp_path / name
    argv = ["select", "--repos", str(repos_file), "--from", FROM, "--to", TO,
            "--as-of", "2026-11-28T06:00:00Z", "--out", str(out)]
    if max_tickets is not None:
        argv += ["--max-tickets", str(max_tickets)]
    runner = list_runner(by_repo)
    code = main(argv, runner=runner)
    return code, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None), runner


def test_eligibility_rules_and_window_edges(tmp_path):
    rows = [
        issue_row(1, "2026-11-22T10:00:00Z", ("層級:c",)),                   # eligible, level c
        issue_row(2, "2026-11-22T10:00:00Z", ("層級:d",)),                   # eligible, level d
        issue_row(3, "2026-11-22T10:00:00Z", ("層級:c", "層級:d")),           # both labels -> c
        issue_row(4, "2026-11-22T10:00:00Z", ("bug",)),                      # no level label
        issue_row(5, "2026-11-22T10:00:00Z", ("層級:c",), reason="NOT_PLANNED"),
        issue_row(6, TO, ("層級:c",)),                                       # to is excluded
        issue_row(7, FROM, ("層級:c",)),                                     # from is included
        issue_row(8, "2026-11-20T23:59:59Z", ("層級:c",)),                   # before window
        issue_row(9, "2026-11-22T10:00:00Z", ("層級:x",)),                   # unknown level label
    ]
    code, pop, _ = run_select(tmp_path, [R1], {R1: rows})
    assert code == 0
    got = {t["ticket"]: t["level"] for t in pop["tickets"]}
    assert got == {f"{R1}#1": "c", f"{R1}#2": "d", f"{R1}#3": "c", f"{R1}#7": "c"}
    assert pop["repos"] == [{"repo": R1, "status": "ok", "tickets_seen": 9}]
    assert pop["rules"] == "closed-completed-cd-v1"


def test_truncation_at_1000_rows_is_conservative(tmp_path):
    rows999 = [issue_row(n, "2026-11-22T10:00:00Z") for n in range(1, 1000)]
    code, pop, _ = run_select(tmp_path, [R1], {R1: rows999}, max_tickets=5000)
    assert code == 0 and pop["repos"][0]["status"] == "ok"

    rows1000 = rows999 + [issue_row(1000, "2026-11-22T10:00:00Z")]
    code, pop, _ = run_select(tmp_path, [R1], {R1: rows1000}, max_tickets=5000, name="p1000.json")
    assert code == 3
    assert pop["repos"][0]["status"] == "truncated"
    assert pop["repos"][0]["tickets_seen"] == 1000
    assert len(pop["tickets"]) == 1000  # rows are still kept; the repo is marked


def test_list_failure_is_per_repo_and_others_continue(tmp_path):
    ok_row = issue_row(1, "2026-11-22T10:00:00Z")
    code, pop, _ = run_select(tmp_path, [R1, R2], {
        R1: ("", "gh: something (HTTP 500)", 1),
        R2: [ok_row],
    })
    assert code == 3
    statuses = {r["repo"]: r["status"] for r in pop["repos"]}
    assert statuses == {R1: "list_failed", R2: "ok"}
    assert [t["ticket"] for t in pop["tickets"]] == [f"{R2}#1"]


@pytest.mark.parametrize("stdout", [
    "not json",                                                    # partial/garbled output
    json.dumps({"number": 1}),                                     # not a list
    json.dumps([{"number": 1, "labels": [], "closedAt": "bad", "stateReason": "COMPLETED"}]),
    json.dumps([{"number": "1", "labels": [], "closedAt": FROM, "stateReason": "COMPLETED"}]),
])
def test_bad_list_output_fails_the_repo_not_a_partial_list(tmp_path, stdout):
    code, pop, _ = run_select(tmp_path, [R1, R2], {R1: (stdout, "", 0), R2: [issue_row(1, FROM)]})
    assert code == 3
    assert {r["repo"]: r["status"] for r in pop["repos"]}[R1] == "list_failed"
    assert all(t["ticket"].startswith(R2) for t in pop["tickets"])


def test_max_tickets_keeps_earliest_and_marks_truncated(tmp_path):
    rows = [issue_row(n, f"2026-11-2{n}T10:00:00Z") for n in (1, 2, 3, 4)]
    code, pop, _ = run_select(tmp_path, [R1], {R1: rows}, max_tickets=2)
    assert code == 3
    assert pop["repos"][0]["status"] == "truncated"
    assert [t["ticket"] for t in pop["tickets"]] == [f"{R1}#1", f"{R1}#2"]


def test_repo_order_does_not_change_population_bytes(tmp_path):
    by_repo = {R1: [issue_row(2, "2026-11-22T10:00:00Z"), issue_row(1, "2026-11-23T10:00:00Z")],
               R2: [issue_row(5, "2026-11-22T10:00:00Z")]}
    run_select(tmp_path, [R1, R2], by_repo, name="a.json")
    run_select(tmp_path, [R2, R1], by_repo, name="b.json")
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_case_insensitive_duplicate_repo_is_usage_error(tmp_path, capsys):
    code, pop, runner = run_select(tmp_path, [R1, R1.upper()], {R1: []})
    assert code == 2 and pop is None and runner.calls == []
    assert "bad_repos" in capsys.readouterr().err


def test_bad_repos_file_and_bad_window_exit_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"kind": "wrong", "schema_version": 1, "repos": ["a/b"]}', encoding="utf-8")
    argv = ["select", "--repos", str(bad), "--from", FROM, "--to", TO, "--as-of", TO, "--out", str(tmp_path / "o.json")]
    assert main(argv, runner=list_runner({})) == 2
    good = write_repos(tmp_path / "good.json", [R1])
    argv = ["select", "--repos", str(good), "--from", TO, "--to", FROM, "--as-of", TO, "--out", str(tmp_path / "o.json")]
    assert main(argv, runner=list_runner({})) == 2
