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
        "prs_closed_unmerged": 0,
        "prs_merged": 1,
        "prs_open": 0,
        "prs_without_ci": 0,
        "re_reviews": 1,
        "review_first_pass": {"den": 1, "num": 0},
        "rework_prs": 0,
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
            "pr": "acme/widgets#21",
            "re_reviews": 1,
            "rework": False,
            "rework_source": "derived",
            "state": "merged",
            "verdicts": 2,
            "verdicts_source": "comments",
        }
    ],
    "schema_version": 1,
    "status": "complete",
    "ticket": "acme/widgets#11",
    "tool_version": "0.3.0",
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
