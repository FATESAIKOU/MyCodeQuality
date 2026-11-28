"""Tests for review line grammar and test vectors (N38 / #67).

Validates tests/vectors/review_lines.json against DEFAULT_CONFIG and extract_verdicts_detailed.
All synthetic data (vendor/model-x, acme/widgets).
"""

import ast
import json
from pathlib import Path
import re

import pytest

from taskquality.conventions import DEFAULT_CONFIG, extract_verdicts_detailed

ROOT = Path(__file__).resolve().parent.parent
VECTORS_FILE = ROOT / "tests" / "vectors" / "review_lines.json"
DOCS_PERIODIC = ROOT / "docs" / "periodic.md"
DOCS_REVIEW_LINES = ROOT / "docs" / "review-lines.md"

REQUIRED_KEYS = [
    "id",
    "line",
    "parsed",
    "role",
    "model",
    "note",
    "verdict_class",
    "head",
    "counts_as_review",
    "unparsed",
    "nonstandard",
    "structure_note",
]

KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _load_vectors():
    assert VECTORS_FILE.is_file(), f"Vectors file not found: {VECTORS_FILE}"
    data = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))
    assert data.get("kind") == "mcq-review-line-vectors", f"bad kind: {data.get('kind')}"
    assert data.get("schema_version") == 1, f"bad schema_version: {data.get('schema_version')}"
    return data["vectors"]


VECTORS = _load_vectors()


def test_vectors_file_metadata_and_structure():
    """Verify file-level schema, count, unique kebab-case IDs, and fixed keys."""
    raw = VECTORS_FILE.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["kind"] == "mcq-review-line-vectors"
    assert data["schema_version"] == 1

    vectors = data["vectors"]
    assert len(vectors) >= 40, f"Expected at least 40 vectors, got {len(vectors)}"

    seen_ids = set()
    for v in vectors:
        vid = v["id"]
        assert KEBAB_RE.fullmatch(vid), f"ID '{vid}' is not kebab-case"
        assert vid not in seen_ids, f"Duplicate vector ID: '{vid}'"
        seen_ids.add(vid)

        assert list(v.keys()) == REQUIRED_KEYS, f"Keys or key order mismatch in {vid}: {list(v.keys())}"


def test_docs_periodic_table_rows_present_in_vectors():
    """Every row of §1 table in docs/periodic.md (inside backticks) must appear in vector lines."""
    lines = DOCS_PERIODIC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## 1."))
    table_lines = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            table_lines.append(line)

    docs_rows = []
    for row in table_lines[2:]:
        cell = row.strip().strip("|").split("|")[0]
        m = re.search(r"`([^`]+)`", cell)
        assert m, f"Could not find backtick pattern in row: {row}"
        docs_rows.append(m.group(1))

    assert len(docs_rows) > 0, f"Expected rows in docs/periodic.md §1, got {len(docs_rows)}"

    vector_lines = {v["line"] for v in VECTORS}
    for row_line in docs_rows:
        assert row_line in vector_lines, f"docs/periodic.md row not found in vectors: {row_line!r}"


def test_docs_review_lines_pattern_matches_default_config():
    """Verify verdict_pattern copied in docs/review-lines.md matches DEFAULT_CONFIG exactly."""
    text = DOCS_REVIEW_LINES.read_text(encoding="utf-8")
    m = re.search(r"```python\n(r?[\"\x27].*?[\"\x27])\n```", text)
    assert m, "Could not find python code block with pattern in docs/review-lines.md"
    doc_pattern = ast.literal_eval(m.group(1))
    assert doc_pattern == DEFAULT_CONFIG["verdict_pattern"]


def test_docs_review_lines_referenced_vector_ids_exist():
    """Verify vector IDs referenced in docs/review-lines.md (§7 tables) all exist in review_lines.json."""
    text = DOCS_REVIEW_LINES.read_text(encoding="utf-8")
    assert "## 7. 範例對照（取自測試向量）" in text
    s7 = text.split("## 7. 範例對照（取自測試向量）")[1]
    doc_vector_ids = re.findall(r"^\|\s*`([a-z0-9-]+)`\s*\|", s7, re.MULTILINE)
    assert len(doc_vector_ids) > 0, "No vector IDs found in docs/review-lines.md §7"
    vector_ids = {v["id"] for v in VECTORS}
    for vid in doc_vector_ids:
        assert vid in vector_ids, f"Vector ID '{vid}' in docs/review-lines.md not found in review_lines.json"


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_review_line_vector(vector):
    """Verify each review line vector matches extract_verdicts_detailed and DEFAULT_CONFIG."""
    line = vector["line"]
    pr = {
        "id": "acme/widgets#1",
        "comments": [{"id": 1, "created_at": "2030-01-01T00:00:00Z", "first_line": line}],
    }
    info = extract_verdicts_detailed(pr, None, DEFAULT_CONFIG)

    pat = re.compile(DEFAULT_CONFIG["verdict_pattern"])
    m = pat.match(line)
    parsed = bool(m and all(m.group(g) is not None for g in ("role", "model", "verdict", "head")))

    if parsed:
        role = m.group("role")
        model = m.group("model")
        note = m.group("note")
        raw_v = m.group("verdict").strip()
        if raw_v in DEFAULT_CONFIG["pass_verdicts"]:
            v_class = "pass"
        elif raw_v in DEFAULT_CONFIG["fail_verdicts"]:
            v_class = "fail"
        else:
            v_class = "other"
        head = m.group("head").lower()
    else:
        role = None
        model = None
        note = None
        v_class = None
        head = None

    counts_as_review = len(info["verdicts"]) == 1
    unparsed = info["unparsed_verdict_lines"] == 1
    nonstandard = info["nonstandard_verdict_lines"] == 1
    structure_note = info["structure_note_verdicts"] == 1

    if counts_as_review:
        v = info["verdicts"][0]
        assert v["role"] == role
        assert v["model"] == model
        assert v["verdict"] == v_class
        assert v["head"] == head

    actual = {
        "id": vector["id"],
        "line": line,
        "parsed": parsed,
        "role": role,
        "model": model,
        "note": note,
        "verdict_class": v_class,
        "head": head,
        "counts_as_review": counts_as_review,
        "unparsed": unparsed,
        "nonstandard": nonstandard,
        "structure_note": structure_note,
    }

    assert vector == actual
