"""Q1 gate: decision from a qmetrics JSON report, event and PR labels."""
import json
import subprocess
import sys

import pytest

OK = "quality:arch-ok"


def gate(tmp_path, report, event="pull_request", labels=None, raw=None):
    f = tmp_path / "q.json"
    if raw is not None:
        f.write_text(raw)
    elif report is not None:
        f.write_text(json.dumps(report))
    args = ["--file", str(f), "--event", event]
    if labels is not None:
        args += ["--labels-json", labels if isinstance(labels, str) else json.dumps(labels)]
    return subprocess.run([sys.executable, "-I", "-m", "qmetrics", "gate", *args],
                          capture_output=True, text=True)


def rep(c=0, d=0):
    return {"counts": {"crossing_1000": c, "ast_dup": d, "crossing_50": 3}}


@pytest.mark.parametrize("r", [rep(c=1), rep(d=2)])
def test_positive_count_fails(tmp_path, r):
    p = gate(tmp_path, r, labels=[])
    assert p.returncode == 1 and OK in p.stdout


def test_zero_passes(tmp_path):
    assert gate(tmp_path, rep(), labels=[]).returncode == 0


@pytest.mark.parametrize("r", [rep(c=None), rep(d=None), {"counts": {"crossing_1000": None, "ast_dup": None}}])
def test_null_fails(tmp_path, r):
    p = gate(tmp_path, r, labels=[])
    assert p.returncode == 1 and "unknown" in p.stdout and "parse failure" in p.stdout
    assert "fail-closed" in p.stdout and OK in p.stdout
    assert "above 0" not in p.stdout


def test_over_and_null_together_name_both_reasons(tmp_path):
    p = gate(tmp_path, rep(c=3, d=None), labels=[])
    assert p.returncode == 1
    assert "count above 0: crossing_1000=3" in p.stdout and "unknown" in p.stdout and "parse failure" in p.stdout


def test_label_allows_with_notice(tmp_path):
    p = gate(tmp_path, rep(c=1), labels=["x", OK])
    assert p.returncode == 0 and p.stdout.startswith("notice:")
    assert gate(tmp_path, rep(d=None), labels=[OK]).returncode == 0


@pytest.mark.parametrize("label", ["Quality:Arch-OK", "quality:arch-ok2", "quality:arch-o", "xquality:arch-ok",
                                   "quality:arch-ok ", "arch-ok"])
def test_near_labels_do_not_allow(tmp_path, label):
    assert gate(tmp_path, rep(c=1), labels=[label]).returncode == 1


def test_no_labels_option_means_no_label(tmp_path):
    assert gate(tmp_path, rep(c=1)).returncode == 1


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "anything"])
def test_other_events_not_judged(tmp_path, event):
    p = gate(tmp_path, rep(c=5, d=5), event=event, labels=[])
    assert p.returncode == 0 and "not judged" in p.stdout


@pytest.mark.parametrize("kw", [
    {"report": None},                                   # file missing
    {"report": None, "raw": "{not json"},
    {"report": None, "raw": "[]"},
    {"report": {}},                                     # no counts
    {"report": {"counts": []}},
    {"report": {"counts": {"ast_dup": 0}}},             # crossing_1000 missing
    {"report": {"counts": {"crossing_1000": 0}}},       # ast_dup missing
    {"report": {"counts": {"crossing_1000": "0", "ast_dup": 0}}},
    {"report": {"counts": {"crossing_1000": 0, "ast_dup": False}}},
    {"report": {"counts": {"crossing_1000": 0, "ast_dup": -1}}},
    {"report": rep(), "labels": "not json"},
    {"report": rep(), "labels": '{"a": 1}'},
    {"report": rep(), "labels": "[1]"},
])
def test_bad_input_is_tool_error(tmp_path, kw):
    kw.setdefault("labels", [])
    p = gate(tmp_path, **kw)
    assert p.returncode == 2 and p.stdout == ""
    assert p.stderr.startswith("qmetrics: error ") and p.stderr.count("\n") == 1
    assert "Traceback" not in p.stderr


def test_bad_label_input_even_with_zero_counts_is_error_but_ok_on_push(tmp_path):
    assert gate(tmp_path, rep(), labels="zzz").returncode == 2
    assert gate(tmp_path, rep(), event="push", labels="zzz").returncode == 0


def test_deterministic(tmp_path):
    a, b = gate(tmp_path, rep(c=1), labels=[]), gate(tmp_path, rep(c=1), labels=[])
    assert (a.stdout, a.stderr, a.returncode) == (b.stdout, b.stderr, b.returncode)
