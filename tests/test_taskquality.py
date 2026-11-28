"""Tests for taskquality CLI, scoring, conventions, and contracts C-B1 through C-B13."""

import copy
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Golden snapshot (§3.1)
GOLDEN_SNAPSHOT = {
    "kind": "taskquality-snapshot",
    "schema_version": 1,
    "ticket": "acme/widgets#11",
    "prs": [
        {
            "id": "acme/widgets#21",
            "title": "Add widget cache",
            "body": "Closes #11",
            "state": "closed",
            "draft": False,
            "created_at": "2030-01-02T03:00:00Z",
            "merged_at": "2030-01-02T05:00:00Z",
            "closed_at": "2030-01-02T05:00:00Z",
            "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "merge_commit_sha": "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "comments": [
                {
                    "id": 501,
                    "created_at": "2030-01-02T04:00:00Z",
                    "first_line": "審查：vendor/model-x 結論：要修（head 0000000）",
                },
                {
                    "id": 502,
                    "created_at": "2030-01-02T04:50:00Z",
                    "first_line": "審查：vendor/model-x 結論：可以 merge（head 1111111）",
                },
            ],
            "reviews": [
                {
                    "id": 601,
                    "submitted_at": "2030-01-02T04:55:00Z",
                    "state": "APPROVED",
                    "commit_id": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                }
            ],
            "ci_runs": [
                {
                    "run_id": 9001,
                    "workflow": "ci",
                    "event": "pull_request",
                    "head_sha": "0000000ccccccccccccccccccccccccccccccccc",
                    "run_attempt": 1,
                    "created_at": "2030-01-02T03:01:00Z",
                    "status": "completed",
                    "conclusion": "failure",
                },
                {
                    "run_id": 9002,
                    "workflow": "ci",
                    "event": "pull_request",
                    "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "run_attempt": 1,
                    "created_at": "2030-01-02T04:41:00Z",
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
        },
        {
            "id": "acme/widgets#30",
            "title": "Bump deps",
            "body": "see #11",
            "state": "closed",
            "draft": False,
            "created_at": "2030-01-02T03:30:00Z",
            "merged_at": "2030-01-02T03:40:00Z",
            "closed_at": "2030-01-02T03:40:00Z",
            "head_sha": "4444444eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "merge_commit_sha": "5555555fffffffffffffffffffffffffffffffff",
            "comments": [],
            "reviews": [],
            "ci_runs": [],
        },
    ],
}

# Golden input (§3.3)
GOLDEN_INPUT = {
    "kind": "taskquality-input",
    "schema_version": 1,
    "ticket": "acme/widgets#11",
    "started_at": "2030-01-02T02:00:00Z",
    "usage": [
        {
            "pr": "acme/widgets#21",
            "role": "impl",
            "provider": "vendor",
            "model": "model-y",
            "input_tokens": 120000,
            "output_tokens": 8000,
            "cache_read_tokens": 90000,
            "cache_write_tokens": None,
            "cost_micro_usd": 410000,
        }
    ],
    "counters": {"compactions": 2, "sessions": 3},
}

# Golden report (§3.6) expected structure
EXPECTED_GOLDEN_REPORT = {
    "clean": False,
    "counters": {"compactions": 2, "sessions": 3},
    "excluded_prs": [{"pr": "acme/widgets#30", "reason": "no_ticket_ref"}],
    "kind": "taskquality-report",
    "metrics": {
        "approved_head_stale": 0,
        "ci_first_green": {"den": 1, "num": 0},
        "cycle_basis": "input_started_at",
        "cycle_seconds": 10800,
        "fix_rounds": 1,
        "nonstandard_verdict_lines": 0,
        "post_merge_verdicts": 0,
        "prs_closed_unmerged": 0,
        "prs_merged": 1,
        "prs_open": 0,
        "prs_without_ci": 0,
        "re_reviews": 1,
        "review_first_pass": {"den": 1, "num": 0},
        "rework_prs": 0,
        "structure_note_verdicts": 0,
        "unparsed_verdict_lines": 0,
        "unreviewed_merged_prs": 0,
    },
    "missing": [
        {
            "field": "usage.by_model[vendor,model-y].cache_write_tokens",
            "reason": "input_null",
        },
        {"field": "usage.totals.cache_write_tokens", "reason": "input_null"},
    ],
    "prs": [
        {
            "approved_head_stale": False,
            "ci_first_green": False,
            "ci_first_head": "0000000ccccccccccccccccccccccccccccccccc",
            "created_at": "2030-01-02T03:00:00Z",
            "first_review_pass": False,
            "fix_rounds": 1,
            "merged_at": "2030-01-02T05:00:00Z",
            "nonstandard_verdict_lines": 0,
            "post_merge_verdicts": 0,
            "pr": "acme/widgets#21",
            "re_reviews": 1,
            "rework": False,
            "rework_source": "derived",
            "state": "merged",
            "structure_note_verdicts": 0,
            "unparsed_verdict_lines": 0,
            "verdicts": 2,
            "verdicts_source": "comments",
        }
    ],
    "schema_version": 1,
    "status": "complete",
    "ticket": "acme/widgets#11",
    "tool_version": "0.5.0",
    "usage": {
        "by_model": [
            {
                "cache_read_tokens": 90000,
                "cache_write_tokens": None,
                "cost_micro_usd": 410000,
                "input_tokens": 120000,
                "model": "model-y",
                "output_tokens": 8000,
                "provider": "vendor",
            }
        ],
        "by_role_model": [
            {
                "cache_read_tokens": 90000,
                "cache_write_tokens": None,
                "cost_micro_usd": 410000,
                "input_tokens": 120000,
                "model": "model-y",
                "output_tokens": 8000,
                "provider": "vendor",
                "role": "impl",
            }
        ],
        "totals": {
            "cache_read_tokens": 90000,
            "cache_write_tokens": None,
            "cost_micro_usd": 410000,
            "input_tokens": 120000,
            "output_tokens": 8000,
        },
    },
    "warnings": [],
}


def run_tq(*args):
    """Run taskquality CLI via subprocess."""
    proc = subprocess.run(
        [sys.executable, "-m", "taskquality.cli", *args],
        capture_output=True,
        text=True,
    )
    return proc


def assert_tool_error(proc, code: str):
    """Check tool error exit 2, single line stderr, and empty stdout."""
    assert proc.returncode == 2, f"Expected returncode 2, got {proc.returncode}. Stderr: {proc.stderr}"
    assert proc.stdout == "", f"Expected empty stdout on tool error, got: {proc.stdout!r}"
    lines = proc.stderr.splitlines()
    assert len(lines) == 1, f"Expected exactly 1 line on stderr, got: {proc.stderr!r}"
    assert f"taskquality: error {code}:" in lines[0]


def assert_no_floats(obj):
    """Verify that there are no floating point values anywhere in obj."""
    if isinstance(obj, float):
        raise AssertionError(f"Found float value: {obj}")
    if isinstance(obj, dict):
        for v in obj.values():
            assert_no_floats(v)
    elif isinstance(obj, list):
        for v in obj:
            assert_no_floats(v)


# Contract C-B1: Golden test & Variations
def test_c_b1_golden_and_variations(tmp_path):
    snap_p = tmp_path / "snap.json"
    in_p = tmp_path / "input.json"
    snap_p.write_text(json.dumps(GOLDEN_SNAPSHOT))
    in_p.write_text(json.dumps(GOLDEN_INPUT))

    # Base golden test
    r1 = run_tq("score", "--snapshot", str(snap_p), "--input", str(in_p), "--json")
    assert r1.returncode == 0
    d1 = json.loads(r1.stdout)
    assert_no_floats(d1)

    # Check byte-identical determinism
    r2 = run_tq("score", "--snapshot", str(snap_p), "--input", str(in_p), "--json")
    assert r1.stdout == r2.stdout

    # Compare with EXPECTED_GOLDEN_REPORT (except config_digest)
    assert d1["config_digest"].startswith("sha256:")
    assert len(d1["config_digest"]) == 71  # sha256: + 64 hex
    d1_without_digest = {k: v for k, v in d1.items() if k != "config_digest"}
    expected_without_digest = {k: v for k, v in EXPECTED_GOLDEN_REPORT.items() if k != "config_digest"}
    assert d1_without_digest == expected_without_digest

    # Variation 1: input with prs override
    in_var1 = copy.deepcopy(GOLDEN_INPUT)
    in_var1["prs"] = {
        "acme/widgets#21": {
            "verdicts": [
                {
                    "at": "2030-01-02T04:00:00Z",
                    "role": "審查",
                    "model": "vendor/model-x",
                    "verdict": "fail",
                    "head": "0000000",
                },
                {
                    "at": "2030-01-02T04:50:00Z",
                    "role": "審查",
                    "model": "vendor/model-x",
                    "verdict": "pass",
                    "head": "1111111",
                },
            ],
            "rework": False,
        }
    }
    in_var1_p = tmp_path / "input_var1.json"
    in_var1_p.write_text(json.dumps(in_var1))
    r_var1 = run_tq("score", "--snapshot", str(snap_p), "--input", str(in_var1_p), "--json")
    assert r_var1.returncode == 0
    d_var1 = json.loads(r_var1.stdout)
    pr21_var1 = d_var1["prs"][0]
    assert pr21_var1["verdicts_source"] == "input"
    assert pr21_var1["rework_source"] == "input"
    # Other values identical
    pr21_base = d1["prs"][0]
    for k in pr21_base:
        if k not in ("verdicts_source", "rework_source"):
            assert pr21_var1[k] == pr21_base[k]

    # Variation 2: config verdict_sources: ["comments", "reviews"]
    cfg_var2_p = tmp_path / "cfg_var2.json"
    r_def = run_tq("defaults")
    cfg_data = json.loads(r_def.stdout)
    cfg_data["verdict_sources"] = ["comments", "reviews"]
    cfg_var2_p.write_text(json.dumps(cfg_data))

    r_var2 = run_tq(
        "score",
        "--snapshot",
        str(snap_p),
        "--input",
        str(in_p),
        "--config",
        str(cfg_var2_p),
        "--json",
    )
    assert r_var2.returncode == 0
    d_var2 = json.loads(r_var2.stdout)
    pr21_var2 = d_var2["prs"][0]
    assert pr21_var2["verdicts_source"] == "comments+reviews"
    assert pr21_var2["verdicts"] == 3
    assert pr21_var2["re_reviews"] == 1
    for k in pr21_base:
        if k not in ("verdicts_source", "verdicts"):
            assert pr21_var2[k] == pr21_base[k]


# Contract C-B2: Ticket association
def test_c_b2_ticket_association(tmp_path):
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Fixes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#102",
                "title": "Title",
                "body": "see #11 for background",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "b" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#103",
                "title": "Title",
                "body": "Resolves acme/widgets#11 nicely",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "c" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#104",
                "title": "Title",
                "body": "Close: https://github.com/acme/widgets/issues/11",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "d" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    proc = run_tq("score", "--snapshot", str(p), "--json")
    assert proc.returncode == 0
    res = json.loads(proc.stdout)
    included = [x["pr"] for x in res["prs"]]
    excluded = res["excluded_prs"]
    assert included == ["acme/widgets#101", "acme/widgets#103", "acme/widgets#104"]
    assert excluded == [{"pr": "acme/widgets#102", "reason": "no_ticket_ref"}]


# Contract C-B3: Verdict identification & other verdict
def test_c_b3_verdict_identification(tmp_path):
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#10",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T05:00:00Z",
                "head_sha": "abc1234000000000000000000000000000000000",
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T02:00:00Z",
                        "first_line": "審查：m 結論：要修（head abc0000）",
                    },
                    {
                        "id": 2,
                        "created_at": "2030-01-01T03:00:00Z",
                        "first_line": "結構審查：m 結論：通過（head abc1234）",
                    },
                    {
                        "id": 3,
                        "created_at": "2030-01-01T04:00:00Z",
                        "first_line": "審查：m 結論：可以 merge（head abc1234）",
                    },
                ],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#20",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T05:00:00Z",
                "head_sha": "def1234000000000000000000000000000000000",
                "comments": [
                    {
                        "id": 4,
                        "created_at": "2030-01-01T02:00:00Z",
                        "first_line": "審查：m 結論：未知狀態（head def1234）",
                    }
                ],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    proc = run_tq("score", "--snapshot", str(p), "--json")
    assert proc.returncode == 0
    res = json.loads(proc.stdout)

    pr10 = next(x for x in res["prs"] if x["pr"] == "acme/widgets#10")
    # '結構審查' ignored, so verdicts == 2 (fail and pass)
    assert pr10["verdicts"] == 2
    assert pr10["first_review_pass"] is False
    assert pr10["fix_rounds"] == 1

    pr20 = next(x for x in res["prs"] if x["pr"] == "acme/widgets#20")
    # '未知狀態' is not in pass or fail -> other -> fix_rounds is null
    assert pr20["verdicts"] == 1
    assert pr20["first_review_pass"] is None
    assert pr20["fix_rounds"] is None
    missing_fields = [m["field"] for m in res["missing"]]
    assert "prs[acme/widgets#20].fix_rounds" in missing_fields
    assert any(
        m["field"] == "prs[acme/widgets#20].fix_rounds" and m["reason"] == "unrecognized_verdict"
        for m in res["missing"]
    )


# Contract C-B4: Verdict sources & C-B4a Formal reviews
def test_c_b4_verdict_sources(tmp_path):
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#10",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T05:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T02:00:00Z",
                        "first_line": "審查：m 結論：要修（head aaaaaaa）",
                    }
                ],
                "reviews": [],
                "ci_runs": [],
            }
        ],
    }
    p_snap = tmp_path / "snap.json"
    p_snap.write_text(json.dumps(snap))

    # input override with empty array
    inp_empty = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": {"acme/widgets#10": {"verdicts": []}},
    }
    p_inp_empty = tmp_path / "inp_empty.json"
    p_inp_empty.write_text(json.dumps(inp_empty))
    r = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_inp_empty), "--json")
    assert r.returncode == 0
    d = json.loads(r.stdout)["prs"][0]
    assert d["verdicts_source"] == "input"
    assert d["verdicts"] == 0
    assert d["fix_rounds"] is None

    # input override with null
    inp_null = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": {"acme/widgets#10": {"verdicts": None}},
    }
    p_inp_null = tmp_path / "inp_null.json"
    p_inp_null.write_text(json.dumps(inp_null))
    r = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_inp_null), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)
    d = res["prs"][0]
    assert d["verdicts_source"] == "input"
    assert d["verdicts"] is None
    assert d["fix_rounds"] is None
    assert any(
        m["field"] == "prs[acme/widgets#10].verdicts" and m["reason"] == "input_null"
        for m in res["missing"]
    )

    # config with bad verdict_sources
    cfg_bad = copy.deepcopy(DEFAULT_CONFIG if "DEFAULT_CONFIG" in globals() else json.loads(run_tq("defaults").stdout))
    cfg_bad["verdict_sources"] = ["invalid_source"]
    p_cfg_bad = tmp_path / "cfg_bad.json"
    p_cfg_bad.write_text(json.dumps(cfg_bad))
    r_bad = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg_bad))
    assert_tool_error(r_bad, "config_bad_shape")


# Contract C-B4a: Formal reviews
def test_c_b4a_formal_reviews(tmp_path):
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#10",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T05:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T02:00:00Z",
                        "first_line": "審查：m 結論：要修（head aaaaaaa）",
                    }
                ],
                "reviews": [
                    {
                        "id": 10,
                        "submitted_at": "2030-01-01T02:00:00Z",
                        "state": "APPROVED",
                        "commit_id": "a" * 40,
                    },
                    {
                        "id": 11,
                        "submitted_at": "2030-01-01T03:00:00Z",
                        "state": "COMMENTED",
                        "commit_id": "a" * 40,
                    },
                ],
                "ci_runs": [],
            }
        ],
    }
    p_snap = tmp_path / "snap.json"
    p_snap.write_text(json.dumps(snap))

    cfg = json.loads(run_tq("defaults").stdout)
    cfg["verdict_sources"] = ["comments", "reviews"]
    p_cfg = tmp_path / "cfg.json"
    p_cfg.write_text(json.dumps(cfg))

    r = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg), "--json")
    assert r.returncode == 0
    d = json.loads(r.stdout)["prs"][0]
    # At 02:00:00Z: comment is first, review is second.
    # COMMENTED does not enter V.
    # Total verdicts = 2 (comment fail, review pass).
    assert d["verdicts"] == 2
    assert d["first_review_pass"] is False  # first was the comment (fail)

    # Now change github_review_role to a role not in review_roles
    cfg["github_review_role"] = "經理"
    p_cfg.write_text(json.dumps(cfg))
    r2 = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg), "--json")
    assert r2.returncode == 0
    d2 = json.loads(r2.stdout)["prs"][0]
    # Review excluded because "經理" not in review_roles
    assert d2["verdicts"] == 1


# Contract C-B5: review_first_pass
def test_c_b5_review_first_pass(tmp_path):
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#1",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T03:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {"id": 1, "created_at": "2030-01-01T01:30:00Z", "first_line": "審查：m 結論：要修（head aaaaaaa）"},
                    {"id": 2, "created_at": "2030-01-01T02:30:00Z", "first_line": "審查：m 結論：可以 merge（head aaaaaaa）"},
                ],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#2",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T03:00:00Z",
                "head_sha": "b" * 40,
                "comments": [
                    {"id": 3, "created_at": "2030-01-01T02:00:00Z", "first_line": "審查：m 結論：可以 merge（head bbbbbbb）"},
                ],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#3",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T03:00:00Z",
                "head_sha": "c" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    proc = run_tq("score", "--snapshot", str(p), "--json")
    assert proc.returncode == 0
    res = json.loads(proc.stdout)
    m = res["metrics"]
    # PR1: fail, pass (first_pass = False)
    # PR2: pass (first_pass = True)
    # PR3: unreviewed merged PR -> not in den!
    assert m["review_first_pass"] == {"num": 1, "den": 2}
    assert m["unreviewed_merged_prs"] == 1

    # v1 is other -> PR first_review_pass and ticket review_first_pass are null, missing has unrecognized_verdict
    snap_other = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#1",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T03:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {"id": 1, "created_at": "2030-01-01T01:30:00Z", "first_line": "審查：m 結論：未知狀態（head aaaaaaa）"},
                ],
                "reviews": [],
                "ci_runs": [],
            }
        ],
    }
    p_other = tmp_path / "snap_other.json"
    p_other.write_text(json.dumps(snap_other))
    proc_other = run_tq("score", "--snapshot", str(p_other), "--json")
    assert proc_other.returncode == 0
    res_other = json.loads(proc_other.stdout)
    assert res_other["prs"][0]["first_review_pass"] is None
    assert res_other["metrics"]["review_first_pass"] is None
    assert any(
        m["field"] == "prs[acme/widgets#1].first_review_pass" and m["reason"] == "unrecognized_verdict"
        for m in res_other["missing"]
    )
    assert any(
        m["field"] == "metrics.review_first_pass" and m["reason"] == "unrecognized_verdict"
        for m in res_other["missing"]
    )


# Contract C-B6: re_reviews and approved_head_stale
def test_c_b6_re_reviews_and_stale_head(tmp_path):
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#1",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T05:00:00Z",
                "head_sha": "bbbbbbb000000000000000000000000000000000",
                "comments": [
                    {"id": 1, "created_at": "2030-01-01T02:00:00Z", "first_line": "審查：m 結論：要修（head aaaaaaa）"},
                    {"id": 2, "created_at": "2030-01-01T03:00:00Z", "first_line": "審查：m 結論：要修（head aaaaaaa123456789012345678901234567890123）"},
                    {"id": 3, "created_at": "2030-01-01T04:00:00Z", "first_line": "審查：m 結論：可以 merge（head bbbbbbb）"},
                ],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#2",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T05:00:00Z",
                "head_sha": "final00000000000000000000000000000000000",
                "comments": [
                    {"id": 4, "created_at": "2030-01-01T02:00:00Z", "first_line": "審查：m 結論：可以 merge（head ccccccc）"},
                ],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    proc = run_tq("score", "--snapshot", str(p), "--json")
    assert proc.returncode == 0
    res = json.loads(proc.stdout)

    pr1 = next(x for x in res["prs"] if x["pr"] == "acme/widgets#1")
    # heads: aaaaaaa -> aaaaaaa12345... (match, not counted) -> bbbbbbb (different, counted = 1)
    assert pr1["re_reviews"] == 1
    # last pass is bbbbbbb, which matches final head bbbbbbb000... -> approved_head_stale == False
    assert pr1["approved_head_stale"] is False

    pr2 = next(x for x in res["prs"] if x["pr"] == "acme/widgets#2")
    # last pass is oldhead, does not match final000... -> approved_head_stale == True
    assert pr2["approved_head_stale"] is True

    assert res["metrics"]["approved_head_stale"] == 1


# Contract C-B7: CI first green
def test_c_b7_ci_first_green(tmp_path):
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#1",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T05:00:00Z",
                "head_sha": "a" * 40,
                "comments": [{"id": 1, "created_at": "2030-01-01T02:00:00Z", "first_line": "審查：m 結論：可以 merge（head aaaaaaa）"}],
                "reviews": [],
                "ci_runs": [
                    {"run_id": 20, "workflow": "ci", "head_sha": "headB" + "0" * 35, "run_attempt": 1, "created_at": "2030-01-01T01:10:00Z", "status": "completed", "conclusion": "failure"},
                    {"run_id": 10, "workflow": "ci", "head_sha": "headA" + "0" * 35, "run_attempt": 1, "created_at": "2030-01-01T01:10:00Z", "status": "completed", "conclusion": "success"},
                    {"run_id": 10, "workflow": "ci", "head_sha": "headA" + "0" * 35, "run_attempt": 2, "created_at": "2030-01-01T01:20:00Z", "status": "completed", "conclusion": "failure"},
                ],
            }
        ],
    }
    # Same second 01:10:00Z: run_id 10 < run_id 20, so ci_first_head is headA, which succeeded!
    # Attempt 2 failure on run 10 is ignored!
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    proc = run_tq("score", "--snapshot", str(p), "--json")
    assert proc.returncode == 0
    res = json.loads(proc.stdout)
    pr1 = res["prs"][0]
    assert pr1["ci_first_head"] == "headA" + "0" * 35
    assert pr1["ci_first_green"] is True

    # CI runs order reversed -> byte-identical output
    snap_rev = copy.deepcopy(snap)
    snap_rev["prs"][0]["ci_runs"].reverse()
    p_rev = tmp_path / "snap_rev.json"
    p_rev.write_text(json.dumps(snap_rev))
    proc_rev = run_tq("score", "--snapshot", str(p_rev), "--json")
    assert proc_rev.returncode == 0
    assert proc_rev.stdout == proc.stdout

    # ci_incomplete: run on first head is in_progress
    snap_incomp = copy.deepcopy(snap)
    snap_incomp["prs"][0]["ci_runs"] = [
        {"run_id": 10, "workflow": "ci", "head_sha": "headA" + "0" * 35, "run_attempt": 1, "created_at": "2030-01-01T01:10:00Z", "status": "in_progress", "conclusion": None}
    ]
    p_incomp = tmp_path / "snap_incomp.json"
    p_incomp.write_text(json.dumps(snap_incomp))
    proc_incomp = run_tq("score", "--snapshot", str(p_incomp), "--json")
    assert proc_incomp.returncode == 0
    res_incomp = json.loads(proc_incomp.stdout)
    assert res_incomp["prs"][0]["ci_first_green"] is None
    assert res_incomp["metrics"]["ci_first_green"] is None
    assert any(
        m["field"] == "prs[acme/widgets#1].ci_first_green" and m["reason"] == "ci_incomplete"
        for m in res_incomp["missing"]
    )
    assert any(
        m["field"] == "metrics.ci_first_green" and m["reason"] == "ci_incomplete"
        for m in res_incomp["missing"]
    )

    # prs_without_ci counting: PR1 has CI, PR2 does not
    snap_no_ci = copy.deepcopy(snap)
    snap_no_ci["prs"].append({
        "id": "acme/widgets#2",
        "title": "Closes #11",
        "body": "",
        "state": "closed",
        "created_at": "2030-01-01T01:00:00Z",
        "merged_at": "2030-01-01T05:00:00Z",
        "head_sha": "b" * 40,
        "comments": [{"id": 2, "created_at": "2030-01-01T02:00:00Z", "first_line": "審查：m 結論：可以 merge（head bbbbbbb）"}],
        "reviews": [],
        "ci_runs": [],
    })
    p_no_ci = tmp_path / "snap_no_ci.json"
    p_no_ci.write_text(json.dumps(snap_no_ci))
    proc_no_ci = run_tq("score", "--snapshot", str(p_no_ci), "--json")
    assert proc_no_ci.returncode == 0
    res_no_ci = json.loads(proc_no_ci.stdout)
    assert res_no_ci["metrics"]["prs_without_ci"] == 1
    assert res_no_ci["metrics"]["ci_first_green"] == {"num": 1, "den": 1}


# Contract C-B8: Rework derivation
def test_c_b8_rework_derivation(tmp_path):
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#21",
                "title": "Initial",
                "body": "Closes #11",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#22",
                "title": "Fix up",
                "body": "Closes #11\n修正 #21",
                "state": "closed",
                "created_at": "2030-01-01T03:00:00Z",
                "merged_at": "2030-01-01T04:00:00Z",
                "head_sha": "b" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#23",
                "title": "Follow up",
                "body": "Closes #11\n接 #21",
                "state": "closed",
                "created_at": "2030-01-01T03:00:00Z",
                "merged_at": "2030-01-01T04:00:00Z",
                "head_sha": "c" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#24",
                "title": "Another",
                "body": "Closes #11\n修正 #21",
                "state": "closed",
                "created_at": "2030-01-01T01:30:00Z",  # Opened BEFORE #21 merged at 02:00
                "merged_at": "2030-01-01T04:00:00Z",
                "head_sha": "d" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    proc = run_tq("score", "--snapshot", str(p), "--json")
    assert proc.returncode == 0
    res = json.loads(proc.stdout)
    prs = {x["pr"]: x for x in res["prs"]}
    assert prs["acme/widgets#22"]["rework"] is True
    assert prs["acme/widgets#23"]["rework"] is False
    assert prs["acme/widgets#24"]["rework"] is False

    # Case-insensitive owner/repo matching
    snap_case = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "Acme/Widgets#21",
                "title": "Initial",
                "body": "Closes #11",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#22",
                "title": "Fix",
                "body": "Closes #11\n修正 acme/widgets#21",
                "state": "closed",
                "created_at": "2030-01-01T03:00:00Z",
                "merged_at": "2030-01-01T04:00:00Z",
                "head_sha": "b" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    p_case = tmp_path / "snap_case.json"
    p_case.write_text(json.dumps(snap_case))
    r_case = run_tq("score", "--snapshot", str(p_case), "--json")
    assert r_case.returncode == 0
    res_case = json.loads(r_case.stdout)
    assert res_case["prs"][1]["rework"] is True


# Contract C-B9: Cycle seconds and status
def test_c_b9_cycle_and_status(tmp_path):
    # Status in_progress when open PR exists
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#1",
                "title": "Closes #11",
                "body": "",
                "state": "open",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": None,
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            }
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    proc = run_tq("score", "--snapshot", str(p), "--json")
    assert proc.returncode == 0
    res = json.loads(proc.stdout)
    assert res["status"] == "in_progress"
    assert res["clean"] is None
    assert res["metrics"]["cycle_seconds"] is None
    assert any(m["field"] == "clean" and m["reason"] == "pr_open" for m in res["missing"])

    # Status no_prs
    snap_empty = {"kind": "taskquality-snapshot", "schema_version": 1, "ticket": "acme/widgets#11", "prs": []}
    p.write_text(json.dumps(snap_empty))
    r_empty = run_tq("score", "--snapshot", str(p), "--json")
    assert r_empty.returncode == 0
    res_empty = json.loads(r_empty.stdout)
    assert res_empty["status"] == "no_prs"
    assert res_empty["metrics"]["prs_merged"] == 0

    # Status no_merged_pr
    snap_unmerged = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#1",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": None,
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            }
        ],
    }
    p.write_text(json.dumps(snap_unmerged))
    r_unm = run_tq("score", "--snapshot", str(p), "--json")
    assert r_unm.returncode == 0
    res_unm = json.loads(r_unm.stdout)
    assert res_unm["status"] == "no_merged_pr"
    assert res_unm["metrics"]["review_first_pass"] is None


# Contract C-B9a: Clean flag
def test_c_b9a_clean_flag(tmp_path):
    # Single merged PR without verdict -> clean is False
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#1",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [
                    {"run_id": 1, "workflow": "ci", "head_sha": "a" * 40, "run_attempt": 1, "created_at": "2030-01-01T01:10:00Z", "status": "completed", "conclusion": "success"}
                ],
            }
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)
    assert res["clean"] is False

    # Single merged PR without CI run -> clean is False
    snap["prs"][0]["comments"] = [
        {"id": 1, "created_at": "2030-01-01T01:30:00Z", "first_line": "審查：m 結論：可以 merge（head aaaaaaa）"}
    ]
    snap["prs"][0]["ci_runs"] = []
    p.write_text(json.dumps(snap))
    r2 = run_tq("score", "--snapshot", str(p), "--json")
    assert r2.returncode == 0
    res2 = json.loads(r2.stdout)
    assert res2["clean"] is False

    # fix_rounds is null due to other -> clean is null with unrecognized_verdict
    snap["prs"][0]["comments"] = [
        {"id": 1, "created_at": "2030-01-01T01:30:00Z", "first_line": "審查：m 結論：未知狀態（head aaaaaaa）"}
    ]
    snap["prs"][0]["ci_runs"] = [
        {"run_id": 1, "workflow": "ci", "head_sha": "a" * 40, "run_attempt": 1, "created_at": "2030-01-01T01:10:00Z", "status": "completed", "conclusion": "success"}
    ]
    p.write_text(json.dumps(snap))
    r3 = run_tq("score", "--snapshot", str(p), "--json")
    assert r3.returncode == 0
    res3 = json.loads(r3.stdout)
    assert res3["clean"] is None
    assert any(m["field"] == "clean" and m["reason"] == "unrecognized_verdict" for m in res3["missing"])

    # Same null plus rework_prs == 1 -> clean is False!
    inp = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": {"acme/widgets#1": {"rework": True}},
    }
    p_inp = tmp_path / "inp.json"
    p_inp.write_text(json.dumps(inp))
    r4 = run_tq("score", "--snapshot", str(p), "--input", str(p_inp), "--json")
    assert r4.returncode == 0
    res4 = json.loads(r4.stdout)
    assert res4["clean"] is False

    # Two merged PRs: one without verdict, one first pass -> clean is False
    snap_two_prs = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#1",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [
                    {"run_id": 1, "workflow": "ci", "head_sha": "a" * 40, "run_attempt": 1, "created_at": "2030-01-01T01:10:00Z", "status": "completed", "conclusion": "success"}
                ],
            },
            {
                "id": "acme/widgets#2",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "b" * 40,
                "comments": [
                    {"id": 2, "created_at": "2030-01-01T01:30:00Z", "first_line": "審查：m 結論：可以 merge（head bbbbbbb）"}
                ],
                "reviews": [],
                "ci_runs": [
                    {"run_id": 2, "workflow": "ci", "head_sha": "b" * 40, "run_attempt": 1, "created_at": "2030-01-01T01:10:00Z", "status": "completed", "conclusion": "success"}
                ],
            },
        ],
    }
    p_two = tmp_path / "snap_two.json"
    p_two.write_text(json.dumps(snap_two_prs))
    r_two = run_tq("score", "--snapshot", str(p_two), "--json")
    assert r_two.returncode == 0
    res_two = json.loads(r_two.stdout)
    assert res_two["clean"] is False
    assert res_two["metrics"]["unreviewed_merged_prs"] == 1
    assert res_two["metrics"]["review_first_pass"] == {"num": 1, "den": 1}


# Contract C-B10: Missing values & usage
def test_c_b10_missing_and_usage(tmp_path):
    p_snap = tmp_path / "snap.json"
    p_snap.write_text(json.dumps(GOLDEN_SNAPSHOT))

    # Without --input
    r_no_inp = run_tq("score", "--snapshot", str(p_snap), "--json")
    assert r_no_inp.returncode == 0
    res = json.loads(r_no_inp.stdout)
    assert res["usage"] is None
    assert res["counters"] is None
    assert any(m["field"] == "usage" and m["reason"] == "input_missing" for m in res["missing"])
    assert any(m["field"] == "counters" and m["reason"] == "input_missing" for m in res["missing"])

    # Usage with null token -> by_model and totals both null, missing has input_null
    inp_null_token = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "usage": [
            {
                "pr": "acme/widgets#21",
                "role": "impl",
                "provider": "vendor",
                "model": "model-y",
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_tokens": 200,
                "cache_write_tokens": None,
                "cost_micro_usd": 10000,
            }
        ],
    }
    p_inp_null = tmp_path / "inp_null_token.json"
    p_inp_null.write_text(json.dumps(inp_null_token))
    r_null_tok = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_inp_null), "--json")
    assert r_null_tok.returncode == 0
    res_tok = json.loads(r_null_tok.stdout)
    assert res_tok["usage"]["by_model"][0]["cache_write_tokens"] is None
    assert res_tok["usage"]["totals"]["cache_write_tokens"] is None
    assert any(
        m["field"] == "usage.by_model[vendor,model-y].cache_write_tokens" and m["reason"] == "input_null"
        for m in res_tok["missing"]
    )
    assert any(
        m["field"] == "usage.totals.cache_write_tokens" and m["reason"] == "input_null"
        for m in res_tok["missing"]
    )

    # PR layer null propagates to metrics.<field> with same reason
    inp_pr_null = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": {
            "acme/widgets#21": {
                "verdicts": None,
            }
        },
    }
    p_inp_pr_null = tmp_path / "inp_pr_null.json"
    p_inp_pr_null.write_text(json.dumps(inp_pr_null))
    r_pr_null = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_inp_pr_null), "--json")
    assert r_pr_null.returncode == 0
    res_pr_null = json.loads(r_pr_null.stdout)
    pr_entry = next(p for p in res_pr_null["prs"] if p["pr"] == "acme/widgets#21")
    assert pr_entry["first_review_pass"] is None
    assert pr_entry["fix_rounds"] is None
    assert pr_entry["re_reviews"] is None
    assert pr_entry["approved_head_stale"] is None
    assert res_pr_null["metrics"]["review_first_pass"] is None
    assert res_pr_null["metrics"]["fix_rounds"] is None
    assert res_pr_null["metrics"]["re_reviews"] is None
    assert res_pr_null["metrics"]["approved_head_stale"] is None
    for field in ["review_first_pass", "fix_rounds", "re_reviews", "approved_head_stale"]:
        assert any(
            m["field"] == f"metrics.{field}" and m["reason"] == "input_null"
            for m in res_pr_null["missing"]
        )


# Contract C-B11: Tool errors
def test_c_b11_tool_errors(tmp_path):
    p_snap = tmp_path / "snap.json"
    p_snap.write_text(json.dumps(GOLDEN_SNAPSHOT))

    # Snapshot not JSON
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not valid json")
    r1 = run_tq("score", "--snapshot", str(bad_json))
    assert_tool_error(r1, "file_not_json")

    # Wrong kind
    bad_kind = tmp_path / "bad_kind.json"
    bad_kind.write_text(json.dumps({"kind": "wrong", "schema_version": 1}))
    r2 = run_tq("score", "--snapshot", str(bad_kind))
    assert_tool_error(r2, "snapshot_bad_shape")

    # Ticket mismatch
    in_mismatch = copy.deepcopy(GOLDEN_INPUT)
    in_mismatch["ticket"] = "acme/widgets#999"
    p_in_mis = tmp_path / "in_mis.json"
    p_in_mis.write_text(json.dumps(in_mismatch))
    r3 = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_in_mis))
    assert_tool_error(r3, "ticket_mismatch")

    # Bad time with timezone offset (+08:00)
    in_bad_time = copy.deepcopy(GOLDEN_INPUT)
    in_bad_time["started_at"] = "2030-01-02T10:00:00+08:00"
    p_in_bad_time = tmp_path / "in_bad_time.json"
    p_in_bad_time.write_text(json.dumps(in_bad_time))
    r4 = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_in_bad_time))
    assert_tool_error(r4, "bad_time")

    # Bad regex pattern in config
    cfg_bad_pat = json.loads(run_tq("defaults").stdout)
    cfg_bad_pat["verdict_pattern"] = "[unclosed regex"
    p_cfg_bad_pat = tmp_path / "cfg_bad_pat.json"
    p_cfg_bad_pat.write_text(json.dumps(cfg_bad_pat))
    r5 = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg_bad_pat))
    assert_tool_error(r5, "bad_pattern")

    # Snapshot validation: review commit_id not string or empty
    snap_bad_commit = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap_bad_commit["prs"][0]["reviews"] = [{"id": 1, "submitted_at": "2030-01-02T04:55:00Z", "state": "APPROVED", "commit_id": 123}]
    p_bad_commit = tmp_path / "bad_commit.json"
    p_bad_commit.write_text(json.dumps(snap_bad_commit))
    r_bad_c = run_tq("score", "--snapshot", str(p_bad_commit))
    assert_tool_error(r_bad_c, "snapshot_bad_shape")

    snap_empty_commit = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap_empty_commit["prs"][0]["reviews"] = [{"id": 1, "submitted_at": "2030-01-02T04:55:00Z", "state": "APPROVED", "commit_id": ""}]
    p_empty_c = tmp_path / "empty_commit.json"
    p_empty_c.write_text(json.dumps(snap_empty_commit))
    r_empty_c = run_tq("score", "--snapshot", str(p_empty_c))
    assert_tool_error(r_empty_c, "snapshot_bad_shape")

    # Snapshot validation: ci_run run_attempt missing, not int, or bool
    snap_no_attempt = copy.deepcopy(GOLDEN_SNAPSHOT)
    del snap_no_attempt["prs"][0]["ci_runs"][0]["run_attempt"]
    p_no_att = tmp_path / "no_attempt.json"
    p_no_att.write_text(json.dumps(snap_no_attempt))
    r_no_att = run_tq("score", "--snapshot", str(p_no_att))
    assert_tool_error(r_no_att, "snapshot_bad_shape")

    snap_bool_attempt = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap_bool_attempt["prs"][0]["ci_runs"][0]["run_attempt"] = True
    p_bool_att = tmp_path / "bool_attempt.json"
    p_bool_att.write_text(json.dumps(snap_bool_attempt))
    r_bool_att = run_tq("score", "--snapshot", str(p_bool_att))
    assert_tool_error(r_bool_att, "snapshot_bad_shape")

    # Input validation: input.prs PR id bad format -> input_bad_shape
    in_bad_prid = copy.deepcopy(GOLDEN_INPUT)
    in_bad_prid["prs"] = {"invalid_pr_id_format": {"verdicts": []}}
    p_bad_prid = tmp_path / "bad_prid.json"
    p_bad_prid.write_text(json.dumps(in_bad_prid))
    r_bad_prid = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_bad_prid))
    assert_tool_error(r_bad_prid, "input_bad_shape")

    # Input validation: usage not list -> input_bad_shape
    in_bad_usage_type = copy.deepcopy(GOLDEN_INPUT)
    in_bad_usage_type["usage"] = "not_a_list"
    p_bad_utype = tmp_path / "bad_utype.json"
    p_bad_utype.write_text(json.dumps(in_bad_usage_type))
    r_bad_utype = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_bad_utype))
    assert_tool_error(r_bad_utype, "input_bad_shape")

    # Input validation: usage missing provider/model -> input_bad_shape
    in_bad_u_prov = copy.deepcopy(GOLDEN_INPUT)
    in_bad_u_prov["usage"] = [{"role": "impl", "model": "m"}]
    p_bad_uprov = tmp_path / "bad_uprov.json"
    p_bad_uprov.write_text(json.dumps(in_bad_u_prov))
    r_bad_uprov = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_bad_uprov))
    assert_tool_error(r_bad_uprov, "input_bad_shape")

    # Input validation: usage invalid role -> input_bad_shape
    in_bad_role = copy.deepcopy(GOLDEN_INPUT)
    in_bad_role["usage"] = [{"provider": "p", "model": "m", "role": "developer"}]
    p_bad_role = tmp_path / "bad_role.json"
    p_bad_role.write_text(json.dumps(in_bad_role))
    r_bad_role = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_bad_role))
    assert_tool_error(r_bad_role, "input_bad_shape")

    # Input validation: usage tokens is bool / float / negative -> input_bad_shape
    for bad_tok in [True, 1.5, -1]:
        in_bad_tok = copy.deepcopy(GOLDEN_INPUT)
        in_bad_tok["usage"] = [{"provider": "p", "model": "m", "role": "impl", "input_tokens": bad_tok}]
        p_bad_tok = tmp_path / "bad_tok.json"
        p_bad_tok.write_text(json.dumps(in_bad_tok))
        r_bad_tok = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_bad_tok))
        assert_tool_error(r_bad_tok, "input_bad_shape")

    # Input validation: counters not dict or counter value is bool / float / negative -> input_bad_shape
    in_bad_counters = copy.deepcopy(GOLDEN_INPUT)
    in_bad_counters["counters"] = [1, 2, 3]
    p_bad_c = tmp_path / "bad_c.json"
    p_bad_c.write_text(json.dumps(in_bad_counters))
    r_bad_c = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_bad_c))
    assert_tool_error(r_bad_c, "input_bad_shape")

    for bad_cnt in [False, 2.5, -5]:
        in_bad_cnt = copy.deepcopy(GOLDEN_INPUT)
        in_bad_cnt["counters"] = {"runs": bad_cnt}
        p_bad_cnt = tmp_path / "bad_cnt.json"
        p_bad_cnt.write_text(json.dumps(in_bad_cnt))
        r_bad_cnt = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_bad_cnt))
        assert_tool_error(r_bad_cnt, "input_bad_shape")

    # Input validation: verdicts[].head not 7-40 lowercase hex -> input_bad_shape
    for bad_head in ["123456", "ABC1234", "zzzzzzz", "a" * 41]:
        in_bad_head = copy.deepcopy(GOLDEN_INPUT)
        in_bad_head["prs"] = {
            "acme/widgets#21": {
                "verdicts": [{"at": "2030-01-02T04:00:00Z", "role": "審查", "model": "m", "verdict": "pass", "head": bad_head}]
            }
        }
        p_bad_head = tmp_path / "bad_head.json"
        p_bad_head.write_text(json.dumps(in_bad_head))
        r_bad_head = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_bad_head))
        assert_tool_error(r_bad_head, "input_bad_shape")

    # Input validation: verdicts[].verdict not pass/fail/other -> input_bad_shape
    in_bad_vd = copy.deepcopy(GOLDEN_INPUT)
    in_bad_vd["prs"] = {
        "acme/widgets#21": {
            "verdicts": [{"at": "2030-01-02T04:00:00Z", "role": "審查", "model": "m", "verdict": "approved", "head": "aaaaaaa"}]
        }
    }
    p_bad_vd = tmp_path / "bad_vd.json"
    p_bad_vd.write_text(json.dumps(in_bad_vd))
    r_bad_vd = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_bad_vd))
    assert_tool_error(r_bad_vd, "input_bad_shape")


# Contract C-B12: Defaults command
def test_c_b12_defaults_command(tmp_path):
    p_snap = tmp_path / "snap.json"
    p_in = tmp_path / "input.json"
    p_snap.write_text(json.dumps(GOLDEN_SNAPSHOT))
    p_in.write_text(json.dumps(GOLDEN_INPUT))

    r_def = run_tq("defaults")
    assert r_def.returncode == 0
    p_cfg = tmp_path / "default_config.json"
    p_cfg.write_text(r_def.stdout)

    r_without_cfg = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_in), "--json")
    r_with_cfg = run_tq(
        "score",
        "--snapshot",
        str(p_snap),
        "--input",
        str(p_in),
        "--config",
        str(p_cfg),
        "--json",
    )
    assert r_without_cfg.returncode == 0
    assert r_with_cfg.returncode == 0
    assert r_without_cfg.stdout == r_with_cfg.stdout


# Contract C-B13: Score does not read clock or access network
def test_c_b13_no_clock_no_network(tmp_path, monkeypatch):
    p_snap = tmp_path / "snap.json"
    p_in = tmp_path / "input.json"
    p_snap.write_text(json.dumps(GOLDEN_SNAPSHOT))
    p_in.write_text(json.dumps(GOLDEN_INPUT))

    import socket
    import taskquality.formats
    from taskquality.cli import main

    def forbidden(*args, **kwargs):
        raise RuntimeError("Forbidden call to clock/network during score calculation")

    class MockDatetime(datetime.datetime):
        @classmethod
        def now(cls, *args, **kwargs):
            forbidden()

        @classmethod
        def utcnow(cls, *args, **kwargs):
            forbidden()

    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(time, "sleep", forbidden)
    monkeypatch.setattr(taskquality.formats.datetime, "datetime", MockDatetime)
    monkeypatch.setattr(socket, "socket", forbidden)

    # Calling main directly inside Python with monkeypatched clock/network
    rc = main(["score", "--snapshot", str(p_snap), "--input", str(p_in), "--json"])
    assert rc == 0


# Issue 15: metric_missing multi-reason tests
def test_issue15_1_fix_rounds_multi_reason(tmp_path):
    """(1) Two merged PRs with different missing reasons for fix_rounds -> metrics.fix_rounds has 2 missing items."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#15",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T01:30:00Z",
                        "first_line": "審查：m 結論：未知狀態（head " + "a" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [
                    {
                        "run_id": 1,
                        "workflow": "ci",
                        "head_sha": "a" * 40,
                        "run_attempt": 1,
                        "created_at": "2030-01-01T01:10:00Z",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            },
            {
                "id": "acme/widgets#102",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:05:00Z",
                "merged_at": "2030-01-01T02:05:00Z",
                "head_sha": "b" * 40,
                "comments": [
                    {
                        "id": 2,
                        "created_at": "2030-01-01T01:35:00Z",
                        "first_line": "審查：m 結論：可以 merge（head " + "b" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [
                    {
                        "run_id": 2,
                        "workflow": "ci",
                        "head_sha": "b" * 40,
                        "run_attempt": 1,
                        "created_at": "2030-01-01T01:15:00Z",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            },
        ],
    }
    inp = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#15",
        "prs": {
            "acme/widgets#102": {
                "verdicts": None,
            }
        },
    }
    p_snap = tmp_path / "snap.json"
    p_inp = tmp_path / "inp.json"
    p_snap.write_text(json.dumps(snap))
    p_inp.write_text(json.dumps(inp))

    r = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_inp), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)

    assert res["metrics"]["fix_rounds"] is None
    fix_rounds_missing = [
        m for m in res["missing"] if m["field"] == "metrics.fix_rounds"
    ]
    assert len(fix_rounds_missing) == 2
    assert fix_rounds_missing == [
        {"field": "metrics.fix_rounds", "reason": "input_null"},
        {"field": "metrics.fix_rounds", "reason": "unrecognized_verdict"},
    ]


def test_issue15_2_clean_multi_reason(tmp_path):
    """(2) Same scenario clean is null -> clean has 2 missing items."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#15",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T01:30:00Z",
                        "first_line": "審查：m 結論：未知狀態（head " + "a" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [
                    {
                        "run_id": 1,
                        "workflow": "ci",
                        "head_sha": "a" * 40,
                        "run_attempt": 1,
                        "created_at": "2030-01-01T01:10:00Z",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            },
            {
                "id": "acme/widgets#102",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:05:00Z",
                "merged_at": "2030-01-01T02:05:00Z",
                "head_sha": "b" * 40,
                "comments": [
                    {
                        "id": 2,
                        "created_at": "2030-01-01T01:35:00Z",
                        "first_line": "審查：m 結論：可以 merge（head " + "b" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [
                    {
                        "run_id": 2,
                        "workflow": "ci",
                        "head_sha": "b" * 40,
                        "run_attempt": 1,
                        "created_at": "2030-01-01T01:15:00Z",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            },
        ],
    }
    inp = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#15",
        "prs": {
            "acme/widgets#102": {
                "verdicts": None,
            }
        },
    }
    p_snap = tmp_path / "snap.json"
    p_inp = tmp_path / "inp.json"
    p_snap.write_text(json.dumps(snap))
    p_inp.write_text(json.dumps(inp))

    r = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_inp), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)

    assert res["clean"] is None
    clean_missing = [
        m for m in res["missing"] if m["field"] == "clean"
    ]
    assert len(clean_missing) == 2
    assert clean_missing == [
        {"field": "clean", "reason": "input_null"},
        {"field": "clean", "reason": "unrecognized_verdict"},
    ]


def test_issue15_3_same_reason_deduped(tmp_path):
    """(3) Same reason two PRs -> only 1 missing item for fix_rounds and clean."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#15",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T01:30:00Z",
                        "first_line": "審查：m 結論：未知狀態（head " + "a" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [
                    {
                        "run_id": 1,
                        "workflow": "ci",
                        "head_sha": "a" * 40,
                        "run_attempt": 1,
                        "created_at": "2030-01-01T01:10:00Z",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            },
            {
                "id": "acme/widgets#102",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:05:00Z",
                "merged_at": "2030-01-01T02:05:00Z",
                "head_sha": "b" * 40,
                "comments": [
                    {
                        "id": 2,
                        "created_at": "2030-01-01T01:35:00Z",
                        "first_line": "審查：m 結論：其他未知（head " + "b" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [
                    {
                        "run_id": 2,
                        "workflow": "ci",
                        "head_sha": "b" * 40,
                        "run_attempt": 1,
                        "created_at": "2030-01-01T01:15:00Z",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            },
        ],
    }
    p_snap = tmp_path / "snap.json"
    p_snap.write_text(json.dumps(snap))

    r = run_tq("score", "--snapshot", str(p_snap), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)

    assert res["metrics"]["fix_rounds"] is None
    assert res["clean"] is None

    fix_rounds_missing = [
        m for m in res["missing"] if m["field"] == "metrics.fix_rounds"
    ]
    assert len(fix_rounds_missing) == 1
    assert fix_rounds_missing == [
        {"field": "metrics.fix_rounds", "reason": "unrecognized_verdict"},
    ]

    clean_missing = [
        m for m in res["missing"] if m["field"] == "clean"
    ]
    assert len(clean_missing) == 1
    assert clean_missing == [
        {"field": "clean", "reason": "unrecognized_verdict"},
    ]


def test_c_b6_approved_head_stale_fail_different_head(tmp_path):
    """Last verdict is fail and its head is different from PR head_sha -> approved_head_stale is False."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T01:30:00Z",
                        "first_line": "審查：m 結論：要修（head " + "0" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [],
            }
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)
    assert res["prs"][0]["approved_head_stale"] is False
    assert res["metrics"]["approved_head_stale"] == 0


def test_c_b9_cycle_basis_first_pr_created(tmp_path):
    """When started_at is omitted, cycle_basis is 'first_pr_created' and start_ts is min(created_at)."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#102",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:30:00Z",
                "merged_at": "2030-01-01T03:00:00Z",
                "head_sha": "b" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)
    assert res["metrics"]["cycle_basis"] == "first_pr_created"
    assert res["metrics"]["cycle_seconds"] == 7200  # 01:00 to 03:00


def test_c_b9_bad_interval(tmp_path):
    """End time earlier than start time -> cycle_seconds is None and missing reason bad_interval."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            }
        ],
    }
    inp = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "started_at": "2030-01-01T03:00:00Z",  # after merged_at
    }
    p_snap = tmp_path / "snap.json"
    p_inp = tmp_path / "inp.json"
    p_snap.write_text(json.dumps(snap))
    p_inp.write_text(json.dumps(inp))
    r = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_inp), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)
    assert res["metrics"]["cycle_seconds"] is None
    assert any(m["field"] == "metrics.cycle_seconds" and m["reason"] == "bad_interval" for m in res["missing"])


def test_c_b11_file_unreadable(tmp_path):
    """Non-existent or unreadable file raises file_unreadable exit 2."""
    p_nonexistent = tmp_path / "nonexistent.json"
    r = run_tq("score", "--snapshot", str(p_nonexistent))
    assert_tool_error(r, "file_unreadable")


def test_c_b11_bad_arguments(tmp_path):
    """Missing required option or bad option raises bad_arguments exit 2."""
    r1 = run_tq("score")
    assert_tool_error(r1, "bad_arguments")
    r2 = run_tq("score", "--unknown-argument")
    assert_tool_error(r2, "bad_arguments")


def test_c_b4_verdict_sources_reviews_only(tmp_path):
    """When verdict_sources only includes reviews, comments are ignored."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T03:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T01:30:00Z",
                        "first_line": "審查：m 結論：可以 merge（head " + "a" * 7 + "）",
                    }
                ],
                "reviews": [
                    {
                        "id": 2,
                        "submitted_at": "2030-01-01T02:00:00Z",
                        "state": "CHANGES_REQUESTED",
                        "commit_id": "a" * 40,
                    }
                ],
                "ci_runs": [],
            }
        ],
    }
    cfg = json.loads(run_tq("defaults").stdout)
    cfg["verdict_sources"] = ["reviews"]
    p_snap = tmp_path / "snap.json"
    p_cfg = tmp_path / "cfg.json"
    p_snap.write_text(json.dumps(snap))
    p_cfg.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)
    assert res["prs"][0]["verdicts_source"] == "reviews"
    assert res["prs"][0]["verdicts"] == 1
    assert res["prs"][0]["first_review_pass"] is False


def test_c_b8_rework_pr_url(tmp_path):
    """PR rework references an earlier merged PR via full pull URL."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#102",
                "title": "Closes #11",
                "body": "修正 https://github.com/acme/widgets/pull/101",
                "state": "closed",
                "created_at": "2030-01-01T02:30:00Z",
                "merged_at": "2030-01-01T03:00:00Z",
                "head_sha": "b" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)
    pr102 = next(p for p in res["prs"] if p["pr"] == "acme/widgets#102")
    assert pr102["rework"] is True
    assert pr102["rework_source"] == "derived"
    assert res["metrics"]["rework_prs"] == 1


def test_c_b4a_review_dismissed(tmp_path):
    """Review with state DISMISSED is ignored (not in V, not other)."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [],
                "reviews": [
                    {
                        "id": 1,
                        "submitted_at": "2030-01-01T01:30:00Z",
                        "state": "DISMISSED",
                        "commit_id": "a" * 40,
                    }
                ],
                "ci_runs": [],
            }
        ],
    }
    cfg = json.loads(run_tq("defaults").stdout)
    cfg["verdict_sources"] = ["reviews"]
    p_snap = tmp_path / "snap.json"
    p_cfg = tmp_path / "cfg.json"
    p_snap.write_text(json.dumps(snap))
    p_cfg.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)
    assert res["prs"][0]["verdicts"] == 0
    assert res["prs"][0]["first_review_pass"] is None
    assert any(m["field"] == "prs[acme/widgets#101].first_review_pass" and m["reason"] == "no_verdict" for m in res["missing"])


def test_c_b6_approved_head_stale_other(tmp_path):
    """Last verdict is unrecognized (other) -> approved_head_stale is None (unrecognized_verdict)."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#11",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #11",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T01:30:00Z",
                        "first_line": "審查：m 結論：未知狀態（head " + "a" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [],
            }
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)
    assert res["prs"][0]["approved_head_stale"] is None
    assert any(m["field"] == "prs[acme/widgets#101].approved_head_stale" and m["reason"] == "unrecognized_verdict" for m in res["missing"])
    assert any(m["field"] == "metrics.approved_head_stale" and m["reason"] == "unrecognized_verdict" for m in res["missing"])


def test_score_summary_output(tmp_path):
    """Run score without --json produces human-readable summary text and exit 0."""
    snap_p = tmp_path / "snap.json"
    in_p = tmp_path / "input.json"
    snap_p.write_text(json.dumps(GOLDEN_SNAPSHOT))
    in_p.write_text(json.dumps(GOLDEN_INPUT))
    r = run_tq("score", "--snapshot", str(snap_p), "--input", str(in_p))
    assert r.returncode == 0
    assert "taskquality 0.5.0" in r.stdout
    assert "ticket acme/widgets#11" in r.stdout
    assert "status: complete" in r.stdout
    assert "clean: false" in r.stdout
    assert "review_first_pass: 0/1" in r.stdout
    assert "fix_rounds: 1" in r.stdout
    assert "re_reviews: 1" in r.stdout
    assert "missing fields:" in r.stdout


def test_issue15_4_review_first_pass_multi_reason(tmp_path):
    """Two merged PRs with different missing reasons for review_first_pass -> metrics.review_first_pass has 2 missing items."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#15",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T01:30:00Z",
                        "first_line": "審查：m 結論：未知狀態（head " + "a" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#102",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:05:00Z",
                "merged_at": "2030-01-01T02:05:00Z",
                "head_sha": "b" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    inp = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#15",
        "prs": {
            "acme/widgets#102": {
                "verdicts": None,
            }
        },
    }
    p_snap = tmp_path / "snap.json"
    p_inp = tmp_path / "inp.json"
    p_snap.write_text(json.dumps(snap))
    p_inp.write_text(json.dumps(inp))

    r = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_inp), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)

    assert res["metrics"]["review_first_pass"] is None
    rfp_missing = [
        m for m in res["missing"] if m["field"] == "metrics.review_first_pass"
    ]
    assert len(rfp_missing) == 2
    assert rfp_missing == [
        {"field": "metrics.review_first_pass", "reason": "input_null"},
        {"field": "metrics.review_first_pass", "reason": "unrecognized_verdict"},
    ]


def test_issue15_5_approved_head_stale_multi_reason(tmp_path):
    """Two merged PRs with different missing reasons for approved_head_stale -> metrics.approved_head_stale has 2 missing items."""
    snap = {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": "acme/widgets#15",
        "prs": [
            {
                "id": "acme/widgets#101",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:00:00Z",
                "merged_at": "2030-01-01T02:00:00Z",
                "head_sha": "a" * 40,
                "comments": [
                    {
                        "id": 1,
                        "created_at": "2030-01-01T01:30:00Z",
                        "first_line": "審查：m 結論：未知狀態（head " + "a" * 7 + "）",
                    }
                ],
                "reviews": [],
                "ci_runs": [],
            },
            {
                "id": "acme/widgets#102",
                "title": "Closes #15",
                "body": "",
                "state": "closed",
                "created_at": "2030-01-01T01:05:00Z",
                "merged_at": "2030-01-01T02:05:00Z",
                "head_sha": "b" * 40,
                "comments": [],
                "reviews": [],
                "ci_runs": [],
            },
        ],
    }
    inp = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": "acme/widgets#15",
        "prs": {
            "acme/widgets#102": {
                "verdicts": None,
            }
        },
    }
    p_snap = tmp_path / "snap.json"
    p_inp = tmp_path / "inp.json"
    p_snap.write_text(json.dumps(snap))
    p_inp.write_text(json.dumps(inp))

    r = run_tq("score", "--snapshot", str(p_snap), "--input", str(p_inp), "--json")
    assert r.returncode == 0
    res = json.loads(r.stdout)

    assert res["metrics"]["approved_head_stale"] is None
    ahs_missing = [
        m for m in res["missing"] if m["field"] == "metrics.approved_head_stale"
    ]
    assert len(ahs_missing) == 2
    assert ahs_missing == [
        {"field": "metrics.approved_head_stale", "reason": "input_null"},
        {"field": "metrics.approved_head_stale", "reason": "unrecognized_verdict"},
    ]


def test_validation_config_bad_types(tmp_path):
    """validate_config checks types and elements for each key."""
    snap_p = tmp_path / "snap.json"
    snap_p.write_text(json.dumps(GOLDEN_SNAPSHOT))

    base_cfg = json.loads(run_tq("defaults").stdout)

    # ci_workflows: integer instead of list/null
    cfg = copy.deepcopy(base_cfg)
    cfg["ci_workflows"] = 5
    p = tmp_path / "cfg1.json"
    p.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(snap_p), "--config", str(p))
    assert_tool_error(r, "config_bad_shape")

    # ticket_ref_keywords: int instead of list of str
    cfg = copy.deepcopy(base_cfg)
    cfg["ticket_ref_keywords"] = 5
    p = tmp_path / "cfg2.json"
    p.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(snap_p), "--config", str(p))
    assert_tool_error(r, "config_bad_shape")

    # ticket_ref_keywords: null
    cfg = copy.deepcopy(base_cfg)
    cfg["ticket_ref_keywords"] = None
    p = tmp_path / "cfg3.json"
    p.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(snap_p), "--config", str(p))
    assert_tool_error(r, "config_bad_shape")

    # verdict_sources: [{}] unhashable / non-string
    cfg = copy.deepcopy(base_cfg)
    cfg["verdict_sources"] = [{}]
    p = tmp_path / "cfg4.json"
    p.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(snap_p), "--config", str(p))
    assert_tool_error(r, "config_bad_shape")

    # github_review_role: int instead of str
    cfg = copy.deepcopy(base_cfg)
    cfg["github_review_role"] = 123
    p = tmp_path / "cfg5.json"
    p.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(snap_p), "--config", str(p))
    assert_tool_error(r, "config_bad_shape")

    # verdict_pattern: int instead of str
    cfg = copy.deepcopy(base_cfg)
    cfg["verdict_pattern"] = 123
    p = tmp_path / "cfg6.json"
    p.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(snap_p), "--config", str(p))
    assert_tool_error(r, "config_bad_shape")

    # verdict_pattern: missing required named groups
    cfg = copy.deepcopy(base_cfg)
    cfg["verdict_pattern"] = r"^no named groups"
    p = tmp_path / "cfg7.json"
    p.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(snap_p), "--config", str(p))
    assert_tool_error(r, "config_bad_shape")


def test_validation_snapshot_bad_types_and_missing_fields(tmp_path):
    """validate_snapshot checks required fields and types, rejecting None where list/str is expected."""
    # comments is None
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["comments"] = None
    p = tmp_path / "snap_no_comments.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # reviews is None
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["reviews"] = None
    p = tmp_path / "snap_no_reviews.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # ci_runs is None
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["ci_runs"] = None
    p = tmp_path / "snap_no_ci.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # ci_runs[0] missing head_sha
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    del snap["prs"][0]["ci_runs"][0]["head_sha"]
    p = tmp_path / "snap_no_ci_head.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # comments[0].first_line is None
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["comments"][0]["first_line"] = None
    p = tmp_path / "snap_none_first_line.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # PR missing head_sha
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    del snap["prs"][0]["head_sha"]
    p = tmp_path / "snap_no_pr_head.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # PR missing created_at -> snapshot_bad_shape (not bad_time)
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    del snap["prs"][0]["created_at"]
    p = tmp_path / "snap_no_created_at.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # PR missing title
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    del snap["prs"][0]["title"]
    p = tmp_path / "snap_no_title.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # PR missing body
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    del snap["prs"][0]["body"]
    p = tmp_path / "snap_no_body.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # PR invalid state
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["state"] = "unknown_state"
    p = tmp_path / "snap_bad_state.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")


def test_validation_input_verdicts_missing_role(tmp_path):
    """Input verdicts[] missing role raises input_bad_shape."""
    snap_p = tmp_path / "snap.json"
    snap_p.write_text(json.dumps(GOLDEN_SNAPSHOT))

    inp = copy.deepcopy(GOLDEN_INPUT)
    inp["prs"] = {
        "acme/widgets#21": {
            "verdicts": [
                {"at": "2030-01-02T04:00:00Z", "verdict": "pass", "head": "1111111"}
            ]
        }
    }
    p_inp = tmp_path / "inp_no_role.json"
    p_inp.write_text(json.dumps(inp))
    r = run_tq("score", "--snapshot", str(snap_p), "--input", str(p_inp))
    assert_tool_error(r, "input_bad_shape")


def test_validation_trailing_newline_rejected(tmp_path):
    """Trailing newline in ISO timestamp or PR id is rejected."""
    # Trailing newline in created_at -> bad_time
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["created_at"] = "2030-01-02T03:00:00Z\n"
    p = tmp_path / "snap_newline_time.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "bad_time")

    # Trailing newline in ticket -> snapshot_bad_shape
    snap2 = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap2["ticket"] = "acme/widgets#11\n"
    p2 = tmp_path / "snap_newline_ticket.json"
    p2.write_text(json.dumps(snap2))
    r2 = run_tq("score", "--snapshot", str(p2))
    assert_tool_error(r2, "snapshot_bad_shape")


def test_validation_non_utf8_file(tmp_path):
    """Non-UTF-8 file raises file_not_json exit 2 without traceback."""
    bad_utf8 = tmp_path / "bad_utf8.json"
    bad_utf8.write_bytes(b"\xff\xfe\x00\x00non-utf8-data")
    r = run_tq("score", "--snapshot", str(bad_utf8))
    assert_tool_error(r, "file_not_json")


def test_validation_snapshot_ci_runs_conclusion_and_status_types(tmp_path):
    """ci_runs conclusion must be str or null, and status must be str (issue #20 fix 中 1)."""
    # 1. conclusion is list -> snapshot_bad_shape
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["ci_runs"][0]["conclusion"] = []
    p = tmp_path / "snap_ci_conclusion_list.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # 2. conclusion is dict -> snapshot_bad_shape
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["ci_runs"][0]["conclusion"] = {"fail": True}
    p = tmp_path / "snap_ci_conclusion_dict.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # 3. conclusion is int -> snapshot_bad_shape
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["ci_runs"][0]["conclusion"] = 123
    p = tmp_path / "snap_ci_conclusion_int.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # 4. status is null/None -> snapshot_bad_shape
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["ci_runs"][0]["status"] = None
    p = tmp_path / "snap_ci_status_none.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # 5. status is list -> snapshot_bad_shape
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["ci_runs"][0]["status"] = ["completed"]
    p = tmp_path / "snap_ci_status_list.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # 6. status is dict -> snapshot_bad_shape
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["ci_runs"][0]["status"] = {}
    p = tmp_path / "snap_ci_status_dict.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # 7. conclusion is null -> valid, exits 0
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["ci_runs"][0]["conclusion"] = None
    p = tmp_path / "snap_ci_conclusion_none.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert r.returncode == 0


def test_validation_input_usage_role_non_string(tmp_path):
    """input usage[].role non-string (dict/list/int) raises input_bad_shape (issue #20 fix 中 2)."""
    snap_p = tmp_path / "snap.json"
    snap_p.write_text(json.dumps(GOLDEN_SNAPSHOT))

    # 1. role is dict
    inp = copy.deepcopy(GOLDEN_INPUT)
    inp["usage"] = [{"provider": "p", "model": "m", "role": {}}]
    p_inp = tmp_path / "inp_role_dict.json"
    p_inp.write_text(json.dumps(inp))
    r = run_tq("score", "--snapshot", str(snap_p), "--input", str(p_inp))
    assert_tool_error(r, "input_bad_shape")

    # 2. role is list
    inp = copy.deepcopy(GOLDEN_INPUT)
    inp["usage"] = [{"provider": "p", "model": "m", "role": ["impl"]}]
    p_inp = tmp_path / "inp_role_list.json"
    p_inp.write_text(json.dumps(inp))
    r = run_tq("score", "--snapshot", str(snap_p), "--input", str(p_inp))
    assert_tool_error(r, "input_bad_shape")

    # 3. role is int
    inp = copy.deepcopy(GOLDEN_INPUT)
    inp["usage"] = [{"provider": "p", "model": "m", "role": 42}]
    p_inp = tmp_path / "inp_role_int.json"
    p_inp.write_text(json.dumps(inp))
    r = run_tq("score", "--snapshot", str(snap_p), "--input", str(p_inp))
    assert_tool_error(r, "input_bad_shape")


def test_validation_input_verdicts_missing_at(tmp_path):
    """Input verdicts[] missing 'at' or 'at' is null raises input_bad_shape (issue #20 fix 低 3)."""
    snap_p = tmp_path / "snap.json"
    snap_p.write_text(json.dumps(GOLDEN_SNAPSHOT))

    # missing "at" key
    inp = copy.deepcopy(GOLDEN_INPUT)
    inp["prs"] = {
        "acme/widgets#21": {
            "verdicts": [
                {"role": "arch", "verdict": "pass", "head": "1111111"}
            ]
        }
    }
    p_inp = tmp_path / "inp_no_at.json"
    p_inp.write_text(json.dumps(inp))
    r = run_tq("score", "--snapshot", str(snap_p), "--input", str(p_inp))
    assert_tool_error(r, "input_bad_shape")

    # "at": None
    inp["prs"]["acme/widgets#21"]["verdicts"][0]["at"] = None
    p_inp2 = tmp_path / "inp_at_none.json"
    p_inp2.write_text(json.dumps(inp))
    r2 = run_tq("score", "--snapshot", str(snap_p), "--input", str(p_inp2))
    assert_tool_error(r2, "input_bad_shape")


def test_extract_verdicts_unparticipated_group_treated_as_non_matching(tmp_path):
    """Named group in verdict_pattern not participating in match is treated as non-matching (issue #20 fix 低 4)."""
    cfg = json.loads(run_tq("defaults").stdout)
    # Alternation where '要修' does not capture 'verdict'
    cfg["verdict_pattern"] = r"^(?P<role>\S*審查)：(?P<model>\S+) 結論：(?:(?P<verdict>可以 merge)|要修)（head (?P<head>[0-9a-f]{7,40})）"
    p_cfg = tmp_path / "config.json"
    p_cfg.write_text(json.dumps(cfg))

    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    # Comment matches pattern, but group 'verdict' is None
    snap["prs"][0]["comments"] = [
        {"id": 1, "created_at": "2030-01-02T04:00:00Z", "first_line": "審查：m 結論：要修（head 1111111）"}
    ]
    p_snap = tmp_path / "snap.json"
    p_snap.write_text(json.dumps(snap))

    # Must exit 0 without AttributeError, and comment is treated as not matching
    r = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg), "--json")
    assert r.returncode == 0, f"Expected 0, got {r.returncode}, stderr: {r.stderr}"
    data = json.loads(r.stdout)
    assert data["prs"][0]["verdicts"] == 0

    # Comment matches pattern with '可以 merge', group 'verdict' participates
    snap["prs"][0]["comments"] = [
        {"id": 2, "created_at": "2030-01-02T04:00:00Z", "first_line": "審查：m 結論：可以 merge（head 1111111）"}
    ]
    p_snap.write_text(json.dumps(snap))
    r2 = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg), "--json")
    assert r2.returncode == 0
    data2 = json.loads(r2.stdout)
    assert data2["prs"][0]["verdicts"] == 1


def test_validation_unhashable_and_type_checks_across_shapes(tmp_path):
    """Verify unhashable list/dict in pr.state, verdict value, config list_str_keys raise exit 2."""
    # 1. PR state is list or dict
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["state"] = []
    p = tmp_path / "snap_state_list.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    snap["prs"][0]["state"] = {"closed": True}
    p = tmp_path / "snap_state_dict.json"
    p.write_text(json.dumps(snap))
    r = run_tq("score", "--snapshot", str(p))
    assert_tool_error(r, "snapshot_bad_shape")

    # 2. verdict in input prs is list or dict
    snap_p = tmp_path / "snap_ok.json"
    snap_p.write_text(json.dumps(GOLDEN_SNAPSHOT))

    inp = copy.deepcopy(GOLDEN_INPUT)
    inp["prs"] = {
        "acme/widgets#21": {
            "verdicts": [
                {"at": "2030-01-02T04:00:00Z", "role": "arch", "verdict": [], "head": "1111111"}
            ]
        }
    }
    p_inp = tmp_path / "inp_verdict_list.json"
    p_inp.write_text(json.dumps(inp))
    r = run_tq("score", "--snapshot", str(snap_p), "--input", str(p_inp))
    assert_tool_error(r, "input_bad_shape")

    inp["prs"]["acme/widgets#21"]["verdicts"][0]["verdict"] = {}
    p_inp = tmp_path / "inp_verdict_dict.json"
    p_inp.write_text(json.dumps(inp))
    r = run_tq("score", "--snapshot", str(snap_p), "--input", str(p_inp))
    assert_tool_error(r, "input_bad_shape")

    # 3. config list_str_keys containing non-str (e.g. list/dict/int)
    cfg = json.loads(run_tq("defaults").stdout)
    cfg["review_roles"] = [["impl"]]
    p_cfg = tmp_path / "cfg_bad_roles.json"
    p_cfg.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(snap_p), "--config", str(p_cfg))
    assert_tool_error(r, "config_bad_shape")

    cfg = json.loads(run_tq("defaults").stdout)
    cfg["ci_green_conclusions"] = [{"success": True}]
    p_cfg = tmp_path / "cfg_bad_green.json"
    p_cfg.write_text(json.dumps(cfg))
    r = run_tq("score", "--snapshot", str(snap_p), "--config", str(p_cfg))
    assert_tool_error(r, "config_bad_shape")


def test_extract_verdicts_optional_named_group(tmp_path):
    """Optional named group in verdict_pattern can be None without dropping verdict (issue #24)."""
    from taskquality.conventions import extract_verdicts_detailed

    cfg = json.loads(run_tq("defaults").stdout)
    cfg["verdict_pattern"] = (
        r"^(?P<role>\S*審查)：(?P<model>\S+) 結論：(?P<verdict>[^（]+)"
        r"（head (?P<head>[0-9a-f]{7,40})）(?P<note> 備註)?"
    )
    p_cfg = tmp_path / "config.json"
    p_cfg.write_text(json.dumps(cfg))

    # 1. Comment without optional note: note is None, but 4 required groups match
    snap = copy.deepcopy(GOLDEN_SNAPSHOT)
    snap["prs"][0]["comments"] = [
        {"id": 1, "created_at": "2030-01-02T04:00:00Z", "first_line": "審查：m 結論：可以 merge（head 1111111）"}
    ]
    p_snap = tmp_path / "snap.json"
    p_snap.write_text(json.dumps(snap))

    r1 = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg), "--json")
    assert r1.returncode == 0, f"Expected 0, got {r1.returncode}, stderr: {r1.stderr}"
    data1 = json.loads(r1.stdout)
    assert data1["prs"][0]["verdicts"] == 1

    info1 = extract_verdicts_detailed(snap["prs"][0], None, cfg)
    src1, v1 = info1["source"], info1["verdicts"]
    assert src1 == "comments"
    assert len(v1) == 1
    assert v1[0]["verdict"] == "pass"
    assert v1[0]["role"] == "審查"
    assert v1[0]["model"] == "m"
    assert v1[0]["head"] == "1111111"

    # 2. Comment with optional note: note participates in match
    snap["prs"][0]["comments"] = [
        {"id": 2, "created_at": "2030-01-02T04:00:00Z", "first_line": "審查：m 結論：可以 merge（head 1111111） 備註"}
    ]
    p_snap.write_text(json.dumps(snap))

    r2 = run_tq("score", "--snapshot", str(p_snap), "--config", str(p_cfg), "--json")
    assert r2.returncode == 0, f"Expected 0, got {r2.returncode}, stderr: {r2.stderr}"
    data2 = json.loads(r2.stdout)
    assert data2["prs"][0]["verdicts"] == 1

    info2 = extract_verdicts_detailed(snap["prs"][0], None, cfg)
    src2, v2 = info2["source"], info2["verdicts"]
    assert src2 == "comments"
    assert len(v2) == 1
    assert v2[0]["verdict"] == "pass"
    assert v2[0]["role"] == "審查"
    assert v2[0]["model"] == "m"
    assert v2[0]["head"] == "1111111"


