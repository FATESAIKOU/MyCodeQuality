"""Locks for current behavior: conventions tables (C-P1, C-P2) and config digest constants (C-P7).

These tests do not change program behavior. They pin what the code does today,
so an accidental change to the built-in config, the digest, or the matching rules fails here.
"""

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from taskquality.conventions import DEFAULT_CONFIG, extract_verdicts_detailed, match_ticket_ref

SNAPSHOT = {
    "kind": "taskquality-snapshot",
    "schema_version": 1,
    "ticket": "acme/widgets#11",
    "prs": [],
}

BUILTIN_DIGEST = "sha256:d81a3345c0f0d7c2b0630be4dc96f4f4c9d999b3f09ff644079308deef9a520e"
DEFAULTS_STDOUT_SHA256 = "48c08ca4819713126c9ed92619e06b4f3e1a478f84aa3dc55a0b1ed5afd0ac43"
V1_CI_WORKFLOWS_DIGEST = "sha256:42fd5527841fe9253b4a5ec0e9378b5adcbc693118727117eeee0c14d6753bc3"


def run_tq(*args):
    return subprocess.run(
        [sys.executable, "-m", "taskquality.cli", *args],
        capture_output=True,
        text=True,
    )


# C-P1: review line convention, one row of the §1 table in docs/periodic.md per case.
# Each row: (line, pattern recognizes it, role, verdict class counted in 審查; None = not counted).
C_P1_ROWS = [
    ("審查：anthropic/claude-sonnet-5-5 結論：可以 merge（head 4cac21d）", True, "審查", "pass"),
    ("審查：anthropic/claude-sonnet-5-5（pipe a, high） 結論：可以 merge（head 1234567）", True, "審查", "pass"),
    ("審查：anthropic/claude-sonnet-5-5 結論：要修（head 30b3c96）", True, "審查", "fail"),
    ("審查：google/gemini-4-hydrogen-medium 結論：要退回（head 30b3c96a1b2c3d4e5f60718293a4b5c6d7e8f901）", True, "審查", "fail"),
    ("審查：anthropic/claude-sonnet-5-5 結論：要修（head 30b3c96） 高 1、中 3，報告見 REPORT-12-review.md", True, "審查", "fail"),
    ("審查：anthropic/claude-sonnet-5-5 結論：可以 merge （head 4cac21d）", True, "審查", "pass"),
    ("結構審查：anthropic/claude-opus-5-5 結論：通過（head 7c3e45b）", True, "結構審查", None),
    ("審查:anthropic/claude-sonnet-5-5 結論：可以 merge（head 4cac21d）", False, None, None),
    ("審查：anthropic/claude-sonnet-5-5結論：可以 merge（head 4cac21d）", False, None, None),
    ("審查：anthropic/claude-sonnet-5-5　結論：可以 merge（head 4cac21d）", False, None, None),
    ("審查：anthropic/claude-sonnet-5-5 結論：可以 merge(head 4cac21d)", False, None, None),
    ("審查：anthropic/claude-sonnet-5-5 結論：可以 merge（head 4CAC21D）", False, None, None),
    ("審查：anthropic/claude-sonnet-5-5 結論：可以 merge（head 4cac21）", False, None, None),
    ("審查：anthropic/claude-sonnet-5-5 結論：可以 merge（head: 4cac21d）", False, None, None),
    ("審查：anthropic/claude-sonnet-5-5 結論：可以 merge（head 4cac21d；無高）", True, "審查", "pass"),
    ("審查：anthropic/claude-sonnet-5-5 結論：可以 merge（無阻擋項）（head 4cac21d）", False, None, None),
    ("審查：anthropic/claude-sonnet-5-5 結論：要修（輕）（head e786beb）", False, None, None),
    ("審查：google/Gemini 4 Hydrogen (Medium) 結論：可以 merge（head 8521f31）", False, None, None),
    ("審查（第一輪）：anthropic/claude-sonnet-5-5 結論：要修（head 9a05dc4）", False, None, None),
    ("**審查**：anthropic/claude-sonnet-5-5 結論：可以 merge（head 4cac21d）", False, None, None),
    (" 審查：anthropic/claude-sonnet-5-5 結論：可以 merge（head 4cac21d）", False, None, None),
    ("審查：google/gemini-4-hydrogen-medium 結論：可以 merge", False, None, None),
    ("審查：anthropic/claude-sonnet-5-5 結論：可以merge（head 4cac21d）", True, "審查", "other"),
    ("審查：anthropic/claude-sonnet-5-5 結論：可以（head 4cac21d）", True, "審查", "other"),
]


@pytest.mark.parametrize("row", C_P1_ROWS, ids=[f"row-{i + 1:02d}" for i in range(len(C_P1_ROWS))])
def test_C_P1_review_line_table(row):
    line, recognized, role, verdict = row
    m = re.compile(DEFAULT_CONFIG["verdict_pattern"]).match(line)
    assert (m is not None) == recognized, line
    if recognized:
        assert m.group("role") == role, line

    pr = {
        "id": "acme/widgets#21",
        "comments": [{"id": 1, "created_at": "2030-01-02T04:00:00Z", "first_line": line}],
    }
    info = extract_verdicts_detailed(pr, None, DEFAULT_CONFIG)
    verdicts = info["verdicts"]
    if verdict is None:
        assert verdicts == [], line
    else:
        assert [(v["role"], v["verdict"]) for v in verdicts] == [(role, verdict)], line


# C-P2: §2 table in docs/periodic.md, one row per case. Ticket is acme/widgets#310, PR is in acme/widgets.
C_P2_ROWS = [
    (["Closes #310", "closes #310", "CLOSES: #310", "Fixes #310", "Resolves #310", "Refs #310", "ref #310"], True),
    (["Closes acme/widgets#310", "Closes acme/Widgets#310"], True),
    (["Refs https://github.com/acme/widgets/issues/310"], True),
    (["本單 Refs #310。", "修正closes #310"], True),
    (["Closes #222, closes #310"], True),
    (["Closes #222, #310"], False),
    (["Closes:#310", "Refs#310"], False),
    # row-08 現行結果：全形冒號後面有沒有空白，都不算（False）
    (["Closes：#310", "Closes： #310"], False),
    (["（#310 調查；#222）", "(#310, #222)", "feat(#310): add cache"], False),
    (["#310", "See #310", "Part of #310", "Related: #310", "Implements #310", "關閉 #310"], False),
    (["Closes https://github.com/acme/widgets/pull/310"], False),
    (["Refs other/repo#310"], False),
]


def _c_p2_match(body, title=""):
    return match_ticket_ref(
        title=title,
        body=body,
        pr_repo="acme/widgets",
        ticket="acme/widgets#310",
        keywords=DEFAULT_CONFIG["ticket_ref_keywords"],
    )


@pytest.mark.parametrize(
    "bodies, expected",
    C_P2_ROWS,
    ids=[f"row-{i + 1:02d}" for i in range(len(C_P2_ROWS))],
)
def test_C_P2_ticket_ref_table(bodies, expected):
    for body in bodies:
        assert _c_p2_match(body) is expected, body


def test_C_P2_ticket_ref_in_title_only():
    assert _c_p2_match(body="", title="Add cache (closes #310)") is True


DOCS_PERIODIC = Path(__file__).resolve().parent.parent / "docs" / "periodic.md"


def _docs_table_markers(section):
    """Marker (✅ ❌ ⚠ or "") of each data row in the table under `## <section>`."""
    lines = DOCS_PERIODIC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## {section}"))
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            rows.append(line)
    markers = []
    for row in rows[2:]:  # skip header and |---| separator
        result = row.strip().strip("|").split("|")[1]
        found = re.search("[✅❌⚠]", result)
        markers.append(found.group(0) if found else "")
    return markers


def _c_p1_expected_marker(recognized, verdict):
    if not recognized:
        return "❌"
    if verdict == "other":
        return "⚠"
    if verdict is None:
        return ""
    return "✅"


def test_docs_tables_match_test_rows():
    c_p1 = _docs_table_markers("1.")
    assert len(c_p1) == len(C_P1_ROWS)
    assert c_p1 == [_c_p1_expected_marker(rec, verdict) for _, rec, _, verdict in C_P1_ROWS]
    c_p2 = _docs_table_markers("2.")
    assert len(c_p2) == len(C_P2_ROWS)
    assert c_p2 == ["✅" if expected else "❌" for _, expected in C_P2_ROWS]


# C-P7: config digest and built-in defaults are locked to literal values.
def test_C_P7_builtin_config_digest_literal(tmp_path):
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps(SNAPSHOT))

    r = run_tq("score", "--snapshot", str(snap), "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["config_digest"] == BUILTIN_DIGEST


def test_C_P7_defaults_stdout_bytes_literal():
    r = subprocess.run(
        [sys.executable, "-m", "taskquality.cli", "defaults"],
        capture_output=True,
    )
    assert r.returncode == 0, r.stderr
    assert hashlib.sha256(r.stdout).hexdigest() == DEFAULTS_STDOUT_SHA256


def test_C_P7_digest_algorithm_v1_ci_workflows(tmp_path):
    defaults = json.loads(run_tq("defaults").stdout)
    cfg = copy.deepcopy(defaults)
    cfg["ci_workflows"] = ["ci"]
    p_cfg = tmp_path / "config.json"
    p_cfg.write_text(json.dumps(cfg))
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps(SNAPSHOT))

    r = run_tq("score", "--snapshot", str(snap), "--config", str(p_cfg), "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["config_digest"] == V1_CI_WORKFLOWS_DIGEST


def test_C_P7_digest_ignores_unrecognized_key(tmp_path):
    defaults = json.loads(run_tq("defaults").stdout)
    cfg = copy.deepcopy(defaults)
    cfg["ci_workflows"] = ["ci"]
    cfg["x_unknown"] = 1
    p_cfg = tmp_path / "config.json"
    p_cfg.write_text(json.dumps(cfg))
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps(SNAPSHOT))

    r = run_tq("score", "--snapshot", str(snap), "--config", str(p_cfg), "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["config_digest"] == V1_CI_WORKFLOWS_DIGEST
