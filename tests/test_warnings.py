"""Tests for the two advisory warnings in the taskquality report (`warnings`, §3.0).

- unrecognized_verdict: N verdict lines of the ticket's PRs are `other`.
- ci_workflows_unmatched: a configured ci_workflows name matches no ci_run in the snapshot.
All data is synthetic; the conclusion text is never expected in the output.
"""

import copy
import json
import subprocess
import sys

from taskquality.conventions import DEFAULT_CONFIG
from taskquality.score import score_ticket

TICKET = "acme/widgets#11"


def verdict_line(conclusion, role="審查"):
    return f"{role}：vendor/model-x 結論：{conclusion}（head 1111111）"


def comment(i, line):
    return {"id": i, "created_at": f"2030-01-02T04:0{i}:00Z", "first_line": line}


def ci_run(workflow, run_id=1):
    return {
        "run_id": run_id,
        "workflow": workflow,
        "event": "pull_request",
        "head_sha": "a" * 40,
        "run_attempt": 1,
        "created_at": "2030-01-02T03:01:00Z",
        "status": "completed",
        "conclusion": "success",
    }


def make_pr(n, comments=(), ci_runs=(), title="Closes #11"):
    return {
        "id": f"acme/widgets#{n}",
        "title": title,
        "body": "",
        "state": "closed",
        "created_at": "2030-01-02T03:00:00Z",
        "merged_at": "2030-01-02T05:00:00Z",
        "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "comments": list(comments),
        "reviews": [],
        "ci_runs": list(ci_runs),
    }


def snapshot(*prs):
    return {"kind": "taskquality-snapshot", "schema_version": 1, "ticket": TICKET, "prs": list(prs)}


def config(**changes):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(changes)
    return cfg


def warnings_of(snap, cfg=None):
    return score_ticket(snap, None, cfg or config())["warnings"]


# ---- unrecognized_verdict ---------------------------------------------------

def test_unrecognized_verdict_triggers_on_other_conclusion():
    snap = snapshot(make_pr(21, comments=[comment(1, verdict_line("可以"))]))
    w = warnings_of(snap)
    assert w == [
        "unrecognized_verdict: 1 verdict line(s) matched the pattern "
        "but the conclusion is in neither pass_verdicts nor fail_verdicts"
    ]
    # the conclusion text itself is never echoed
    assert "可以" not in w[0]


def test_unrecognized_verdict_silent_when_all_conclusions_recognized():
    snap = snapshot(make_pr(21, comments=[
        comment(1, verdict_line("要修")),
        comment(2, verdict_line("可以 merge")),
    ]))
    assert warnings_of(snap) == []


def test_unrecognized_verdict_silent_when_custom_pass_verdict_added():
    # the documented fix: add the team's wording to pass_verdicts in a custom config
    snap = snapshot(make_pr(21, comments=[comment(1, verdict_line("可以"))]))
    assert warnings_of(snap, config(pass_verdicts=["可以 merge", "通過", "可以"])) == []


def test_unrecognized_verdict_counts_all_other_lines_of_ticket_prs():
    snap = snapshot(
        make_pr(21, comments=[comment(1, verdict_line("可以")), comment(2, verdict_line("要修")), comment(3, verdict_line("好"))]),
        make_pr(22, comments=[comment(4, verdict_line("ok"))]),
        # not a ticket PR: excluded, so its other line is not counted
        make_pr(23, comments=[comment(5, verdict_line("可以"))], title="Unrelated"),
        # role not in review_roles: filtered before classification, so not counted
        make_pr(24, comments=[comment(6, verdict_line("可以", role="結構審查"))]),
    )
    w = warnings_of(snap)
    assert len(w) == 1
    assert w[0].startswith("unrecognized_verdict: 3 verdict line(s) ")


# ---- ci_workflows_unmatched --------------------------------------------------

def test_ci_workflows_unmatched_triggers_on_renamed_workflow():
    snap = snapshot(make_pr(21, ci_runs=[ci_run("CI")]))
    assert warnings_of(snap, config(ci_workflows=["deploy"])) == ["ci_workflows_unmatched: deploy"]


def test_ci_workflows_unmatched_case_differs_says_so_without_real_name():
    snap = snapshot(make_pr(21, ci_runs=[ci_run("CI")]))
    w = warnings_of(snap, config(ci_workflows=["ci"]))
    assert w == ["ci_workflows_unmatched: ci (case differs from an existing workflow name)"]
    assert "CI" not in w[0]


def test_ci_workflows_unmatched_silent_on_exact_match():
    snap = snapshot(make_pr(21, ci_runs=[ci_run("CI")]))
    assert warnings_of(snap, config(ci_workflows=["CI"])) == []


def test_ci_workflows_unmatched_silent_when_all_names_null():
    snap = snapshot(make_pr(21, ci_runs=[ci_run("CI")]))
    assert warnings_of(snap, config(ci_workflows=None)) == []


def test_ci_workflows_unmatched_silent_when_snapshot_has_no_ci_runs():
    snap = snapshot(make_pr(21, ci_runs=[]))
    assert warnings_of(snap, config(ci_workflows=["ci"])) == []


def test_ci_workflows_unmatched_only_the_missing_name_and_no_duplicates():
    snap = snapshot(make_pr(21, ci_runs=[ci_run("ci")]), make_pr(22, ci_runs=[ci_run("lint", 2)]))
    w = warnings_of(snap, config(ci_workflows=["ci", "deploy", "deploy", "lint"]))
    assert w == ["ci_workflows_unmatched: deploy"]


def test_ci_workflows_match_scope_is_whole_snapshot_including_excluded_pr():
    # the run of a PR that is not a ticket PR (no_ticket_ref) still counts: the hint only asks
    # whether the name exists in the snapshot at all (a deliberate choice, see docs/taskquality.md)
    snap = snapshot(
        make_pr(21, ci_runs=[ci_run("deploy")]),
        make_pr(30, ci_runs=[ci_run("CI", 2)], title="Unrelated"),
    )
    assert warnings_of(snap, config(ci_workflows=["CI"])) == []


def test_ci_workflows_match_scope_includes_run_attempt_other_than_one():
    # a run with run_attempt 2 still counts as a match: the hint is about renames, not retries
    snap = snapshot(
        make_pr(21, ci_runs=[ci_run("deploy")]),
        make_pr(22, ci_runs=[{**ci_run("CI", 2), "run_attempt": 2}]),
    )
    assert warnings_of(snap, config(ci_workflows=["CI"])) == []


# ---- both together ----------------------------------------------------------

def test_warnings_are_sorted_strings_of_both_kinds():
    snap = snapshot(make_pr(21, comments=[comment(1, verdict_line("可以"))], ci_runs=[ci_run("CI")]))
    w = warnings_of(snap, config(ci_workflows=["deploy", "ci"]))
    assert w == [
        "ci_workflows_unmatched: ci (case differs from an existing workflow name)",
        "ci_workflows_unmatched: deploy",
        "unrecognized_verdict: 1 verdict line(s) matched the pattern "
        "but the conclusion is in neither pass_verdicts nor fail_verdicts",
    ]


# ---- CLI: human summary prints warnings, --json carries them -----------------

def run_score(tmp_path, snap, cfg=None, *extra):
    snap_path = tmp_path / "snapshot.json"
    snap_path.write_text(json.dumps(snap), encoding="utf-8")
    args = [sys.executable, "-m", "taskquality.cli", "score", "--snapshot", str(snap_path), *extra]
    if cfg is not None:
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        args += ["--config", str(cfg_path)]
    return subprocess.run(args, capture_output=True, text=True)


def test_cli_summary_prints_warning_lines(tmp_path):
    snap = snapshot(make_pr(21, ci_runs=[ci_run("CI")]))
    proc = run_score(tmp_path, snap, config(ci_workflows=["deploy"]))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == "warning: ci_workflows_unmatched: deploy"


def test_cli_summary_has_no_warning_lines_when_clean(tmp_path):
    snap = snapshot(make_pr(21, comments=[comment(1, verdict_line("要修"))], ci_runs=[ci_run("ci")]))
    proc = run_score(tmp_path, snap, config(ci_workflows=["ci"]))
    assert proc.returncode == 0, proc.stderr
    assert "warning" not in proc.stdout


def test_cli_json_carries_warnings(tmp_path):
    snap = snapshot(make_pr(21, comments=[comment(1, verdict_line("可以"))]))
    proc = run_score(tmp_path, snap, None, "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["warnings"][0].startswith("unrecognized_verdict: 1 ")


def test_cli_summary_keeps_warning_on_one_line_even_with_control_chars(tmp_path):
    # the name is the user's own config string: a newline must not split the summary line
    snap = snapshot(make_pr(21, ci_runs=[ci_run("CI")]))
    proc = run_score(tmp_path, snap, config(ci_workflows=["dep\nloy"]))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == "warning: ci_workflows_unmatched: dep\\nloy"


def test_cli_summary_prints_every_warning_line_in_sorted_order(tmp_path):
    snap = snapshot(make_pr(21, comments=[comment(1, verdict_line("可以"))], ci_runs=[ci_run("CI")]))
    proc = run_score(tmp_path, snap, config(ci_workflows=["deploy", "ci"]))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-3:] == [
        "warning: ci_workflows_unmatched: ci (case differs from an existing workflow name)",
        "warning: ci_workflows_unmatched: deploy",
        "warning: unrecognized_verdict: 1 verdict line(s) matched the pattern "
        "but the conclusion is in neither pass_verdicts nor fail_verdicts",
    ]
