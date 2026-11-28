"""N10a (#61): usage.by_role_model, weighted_micro_units / weighted_null_rows, and the agent key."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOKEN_KEYS = [
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_micro_usd",
]

SNAPSHOT = {
    "kind": "taskquality-snapshot",
    "schema_version": 1,
    "ticket": "acme/widgets#11",
    "prs": [
        {
            "id": "acme/widgets#21",
            "title": "Add widget cache",
            "body": "Closes #11",
            "state": "closed",
            "created_at": "2030-01-02T03:00:00Z",
            "merged_at": "2030-01-02T05:00:00Z",
            "closed_at": "2030-01-02T05:00:00Z",
            "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "comments": [],
            "reviews": [],
            "ci_runs": [],
        },
    ],
}

SECRET_AGENT = "secret-agent-name-1"


def _item(role, model, **extra):
    base = {
        "pr": "acme/widgets#21",
        "role": role,
        "provider": "vendor",
        "model": model,
        "input_tokens": 100,
        "output_tokens": 10,
        "cache_read_tokens": 0,
        "cache_write_tokens": 1,
        "cost_micro_usd": 5,
    }
    base.update(extra)
    return base


ABSENT = object()


def _run(tmp_path, usage_value, *, json_out=True, name="input.json"):
    snap_p = tmp_path / "snap.json"
    snap_p.write_text(json.dumps(SNAPSHOT))
    inp = {"kind": "taskquality-input", "schema_version": 1, "ticket": "acme/widgets#11"}
    if usage_value is not ABSENT:
        inp["usage"] = usage_value
    in_p = tmp_path / name
    in_p.write_text(json.dumps(inp))
    args = [sys.executable, "-m", "taskquality.cli", "score", "--snapshot", str(snap_p), "--input", str(in_p)]
    if json_out:
        args.append("--json")
    return subprocess.run(args, capture_output=True, text=True)


def _report(tmp_path, usage_value):
    proc = _run(tmp_path, usage_value)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _assert_bad_shape(proc):
    assert proc.returncode == 2, proc.stderr
    assert proc.stdout == ""
    assert "error input_bad_shape" in proc.stderr


# --- by_role_model rows, ordering, and sums ---------------------------------

TWO_BY_TWO = [
    _item("review", "model-y", input_tokens=200, output_tokens=20, cache_write_tokens=2, cost_micro_usd=6),
    _item("impl", "model-y"),
    _item("impl", "model-x", input_tokens=40, output_tokens=4, cache_write_tokens=0, cost_micro_usd=1),
    _item("review", "model-x", input_tokens=60, output_tokens=6, cache_write_tokens=3, cost_micro_usd=2),
    # second impl/model-y item: the group must sum, not keep one row
    _item("impl", "model-y", input_tokens=7, output_tokens=1, cache_write_tokens=0, cost_micro_usd=9),
]


def test_by_role_model_rows_and_order(tmp_path):
    rep = _report(tmp_path, TWO_BY_TWO)
    rows = rep["usage"]["by_role_model"]
    assert [(r["role"], r["provider"], r["model"]) for r in rows] == [
        ("impl", "vendor", "model-x"),
        ("impl", "vendor", "model-y"),
        ("review", "vendor", "model-x"),
        ("review", "vendor", "model-y"),
    ]
    impl_y = rows[1]
    assert impl_y["input_tokens"] == 107
    assert impl_y["output_tokens"] == 11
    assert impl_y["cache_write_tokens"] == 1
    assert impl_y["cost_micro_usd"] == 14
    assert rows[0] == {
        "role": "impl", "provider": "vendor", "model": "model-x",
        "input_tokens": 40, "output_tokens": 4, "cache_read_tokens": 0,
        "cache_write_tokens": 0, "cost_micro_usd": 1,
    }
    # every row carries exactly the three id keys plus the token keys
    for r in rows:
        assert set(r) == {"role", "provider", "model", *TOKEN_KEYS}


def test_by_role_model_and_by_model_sum_to_totals(tmp_path):
    usage = _report(tmp_path, TWO_BY_TWO)["usage"]
    for t_k in TOKEN_KEYS:
        assert sum(r[t_k] for r in usage["by_role_model"]) == usage["totals"][t_k]
        assert sum(r[t_k] for r in usage["by_model"]) == usage["totals"][t_k]


# --- null propagation, no new missing items ---------------------------------

def test_null_token_propagates_without_new_missing(tmp_path):
    with_null = [_item("review", "model-y", cache_write_tokens=None), _item("impl", "model-y")]
    rep = _report(tmp_path, with_null)
    rows = {(r["role"], r["model"]): r for r in rep["usage"]["by_role_model"]}
    assert rows[("review", "model-y")]["cache_write_tokens"] is None
    assert rows[("impl", "model-y")]["cache_write_tokens"] == 1
    # by_role_model never adds a missing entry
    assert not [m for m in rep["missing"] if m["field"].startswith("usage.by_role_model")]
    cw = sorted(m["field"] for m in rep["missing"] if m["field"].endswith(".cache_write_tokens"))
    assert cw == [
        "usage.by_model[vendor,model-y].cache_write_tokens",
        "usage.totals.cache_write_tokens",
    ]


def test_missing_key_is_null_and_adds_no_missing_row(tmp_path):
    item_no_key = _item("review", "model-y")
    del item_no_key["cache_write_tokens"]
    rep = _report(tmp_path, [item_no_key, _item("impl", "model-y")])
    rows = {(r["role"], r["model"]): r for r in rep["usage"]["by_role_model"]}
    assert rows[("review", "model-y")]["cache_write_tokens"] is None
    assert rows[("impl", "model-y")]["cache_write_tokens"] == 1
    assert not [m for m in rep["missing"] if m["field"].startswith("usage.by_role_model")]
    # by_model reports the same group as input_missing (unchanged behavior)
    assert {"field": "usage.by_model[vendor,model-y].cache_write_tokens", "reason": "input_missing"} in rep["missing"]


# --- weighted_micro_units ----------------------------------------------------

def test_weighted_partial_null_and_null_rows(tmp_path):
    usage = [
        _item("impl", "model-y", weighted_micro_units=300),
        _item("impl", "model-y", weighted_micro_units=None),   # free model row inside a priced group
        _item("review", "model-y", weighted_micro_units=None),  # whole group null
        _item("review", "model-x"),                             # key absent, but other rows carry it
        _item("impl", "model-x", weighted_micro_units=70),
    ]
    rep = _report(tmp_path, usage)
    u = rep["usage"]
    by_model = {r["model"]: r for r in u["by_model"]}
    assert by_model["model-y"]["weighted_micro_units"] == 300
    assert by_model["model-y"]["weighted_null_rows"] == 2
    assert by_model["model-x"]["weighted_micro_units"] == 70
    assert by_model["model-x"]["weighted_null_rows"] == 1

    rows = {(r["role"], r["model"]): r for r in u["by_role_model"]}
    assert rows[("impl", "model-y")]["weighted_micro_units"] == 300
    assert rows[("impl", "model-y")]["weighted_null_rows"] == 1
    assert rows[("review", "model-y")]["weighted_micro_units"] is None
    assert rows[("review", "model-y")]["weighted_null_rows"] == 1
    assert rows[("review", "model-x")]["weighted_micro_units"] is None
    assert rows[("review", "model-x")]["weighted_null_rows"] == 1
    assert rows[("impl", "model-x")]["weighted_null_rows"] == 0

    assert u["totals"]["weighted_micro_units"] == 370
    assert u["totals"]["weighted_null_rows"] == 3

    # weighted never enters missing
    assert not [m for m in rep["missing"] if "weighted" in m["field"]]


def test_weighted_all_values(tmp_path):
    usage = [
        _item("impl", "model-y", weighted_micro_units=10),
        _item("review", "model-y", weighted_micro_units=20),
    ]
    u = _report(tmp_path, usage)["usage"]
    assert u["totals"]["weighted_micro_units"] == 30
    assert u["totals"]["weighted_null_rows"] == 0
    assert all(r["weighted_null_rows"] == 0 for r in u["by_model"] + u["by_role_model"])


def test_weighted_keys_absent_when_no_item_carries_them(tmp_path):
    u = _report(tmp_path, TWO_BY_TWO)["usage"]
    for block in (u["totals"], *u["by_model"], *u["by_role_model"]):
        assert "weighted_micro_units" not in block
        assert "weighted_null_rows" not in block


# --- validation --------------------------------------------------------------

@pytest.mark.parametrize("bad", [-1, "5", True, 1.5])
def test_weighted_bad_value_is_input_bad_shape(tmp_path, bad):
    proc = _run(tmp_path, [_item("impl", "model-y", weighted_micro_units=bad)])
    _assert_bad_shape(proc)


@pytest.mark.parametrize("bad", ["", 5, ["x"]])
def test_agent_bad_value_is_input_bad_shape(tmp_path, bad):
    proc = _run(tmp_path, [_item("impl", "model-y", agent=bad)])
    _assert_bad_shape(proc)


def test_agent_null_is_accepted_and_same_bytes_as_absent(tmp_path):
    usage_null = [_item("impl", "model-y", agent=None, weighted_micro_units=3)]
    usage_absent = [_item("impl", "model-y", weighted_micro_units=3)]
    with_null = _run(tmp_path, usage_null, name="agent_null.json")
    without = _run(tmp_path, usage_absent, name="agent_absent.json")
    assert with_null.returncode == 0, with_null.stderr
    assert with_null.stdout == without.stdout
    assert with_null.stderr == without.stderr == ""


def test_agent_never_appears_in_any_output(tmp_path):
    usage = [
        _item("impl", "model-y", agent=SECRET_AGENT, weighted_micro_units=3),
        _item("review", "model-y", agent=SECRET_AGENT),
    ]
    for as_json in (True, False):
        proc = _run(tmp_path, usage, json_out=as_json)
        assert proc.returncode == 0, proc.stderr
        assert SECRET_AGENT not in proc.stdout
        assert SECRET_AGENT not in proc.stderr


@pytest.mark.parametrize("as_json", [True, False])
@pytest.mark.parametrize(
    "bad, secret",
    [
        ({"x": "secret-agent-name-2"}, "secret-agent-name-2"),
        (["secret-agent-name-3"], "secret-agent-name-3"),
    ],
)
def test_agent_only_error_names_key_not_value(tmp_path, bad, secret, as_json):
    proc = _run(tmp_path, [_item("impl", "model-y", agent=bad)], json_out=as_json)
    _assert_bad_shape(proc)
    assert "agent" in proc.stderr
    assert secret not in proc.stdout
    assert secret not in proc.stderr


# --- byte stability ----------------------------------------------------------

def test_no_usage_and_null_usage_have_no_new_keys(tmp_path):
    absent = _run(tmp_path, ABSENT, name="absent.json")
    null = _run(tmp_path, None, name="null.json")
    assert absent.returncode == 0 and null.returncode == 0
    for proc in (absent, null):
        rep = json.loads(proc.stdout)
        assert rep["usage"] is None
        assert "by_role_model" not in proc.stdout
        assert "weighted" not in proc.stdout
    # the only difference is the existing missing reason (input_missing vs input_null)
    assert absent.stdout.replace("input_missing", "input_null") == null.stdout.replace("input_missing", "input_null")


DATA_DIR = Path(__file__).resolve().parent / "data"


@pytest.mark.parametrize("case", ["absent", "null"])
@pytest.mark.parametrize("mode", ["json", "summary"])
def test_no_usage_matches_main_bytes(tmp_path, case, mode):
    # expected stdout was captured from main (v0.5.0, 1442e97) with the same synthetic input,
    # then updated by #62 (add-only keys: first_review_head_stale, ci_runs, first_review_head_stale_prs)
    usage = ABSENT if case == "absent" else None
    proc = _run(tmp_path, usage, json_out=(mode == "json"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    expected = (DATA_DIR / f"n10a_baseline_{case}_{mode}.txt").read_bytes()
    assert proc.stdout.encode("utf-8") == expected


def test_usage_without_weighted_adds_only_by_role_model(tmp_path):
    rep = _report(tmp_path, TWO_BY_TWO)
    assert "weighted" not in json.dumps(rep)
    assert set(rep["usage"]) == {"by_model", "by_role_model", "totals"}


def test_output_is_deterministic(tmp_path):
    usage = TWO_BY_TWO + [_item("impl", "model-x", weighted_micro_units=None)]
    first = _run(tmp_path, usage, name="a.json")
    second = _run(tmp_path, usage, name="b.json")
    assert first.returncode == 0
    assert first.stdout == second.stdout
    assert first.stderr == second.stderr
