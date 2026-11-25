"""C-P15: public files must not contain private names.

The guard compares sha256 hashes of candidate words against tests/private_name_hashes.txt.
It is meant to stop accidental leaks, not to keep the list secret.
Failures report file and line only, never the matched word.
"""

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HASH_FILE = Path(__file__).resolve().parent / "private_name_hashes.txt"

# Synthetic names used only to check the scanner itself. Their hashes are not in HASH_FILE.
SYNTHETIC_NAMES = ["acmeprivate", "xyz", "pdq"]

SEGMENT_RE = re.compile(r"[A-Za-z0-9]+")
COMPOUND_RE = re.compile(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)+")
CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+")
HASH_RE = re.compile(r"[0-9a-f]{64}")


def _sha(word):
    return hashlib.sha256(word.lower().encode("utf-8")).hexdigest()


def _candidates(text):
    """Lowercased candidate words for one piece of text."""
    found = set()
    for segment in SEGMENT_RE.findall(text):
        found.add(segment)
        pieces = CAMEL_RE.findall(segment)
        for i in range(len(pieces)):
            for j in range(i + 1, len(pieces) + 1):
                found.add("".join(pieces[i:j]))
    for compound in COMPOUND_RE.findall(text):
        found.add(re.sub(r"[-_.]", "", compound))
        parts = re.split(r"[-_.]", compound)
        for i in range(len(parts)):
            for j in range(i + 1, len(parts) + 1):
                found.add("".join(parts[i:j]))
    return {word.lower() for word in found}


def _hits(text, hashes):
    return bool(hashes & {_sha(word) for word in _candidates(text)})


def _load_hashes(path):
    hashes = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            hashes.add(line)
    return hashes


def _tracked_text_files(root=ROOT):
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    for name in out.split("\0"):
        if not name or name == "uv.lock":
            continue
        data = (root / name).read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        yield name, text


def _scan(files, hashes):
    """Return (file, line number) for every line that hits a hash."""
    hits = []
    for name, text in files:
        for lineno, line in enumerate(text.splitlines(), 1):
            if _hits(line, hashes):
                hits.append((name, lineno))
    return hits


def test_C_P15_hash_list_is_well_formed():
    lines = [
        raw.strip()
        for raw in HASH_FILE.read_text(encoding="utf-8").splitlines()
        if raw.strip() and not raw.strip().startswith("#")
    ]
    assert lines, "hash list is empty"
    for line in lines:
        assert HASH_RE.fullmatch(line), "entry is not a 64-char lowercase sha256"


def test_C_P15_public_files_contain_no_listed_names():
    hashes = _load_hashes(HASH_FILE)
    hits = _scan(_tracked_text_files(), hashes)
    assert hits == [], f"listed name found at (file, line): {hits}"


@pytest.mark.parametrize(
    "text",
    [
        "成本管理模組（如 AcmePrivate）",
        "由 PM 或 AcmePrivate 把",
        "修正AcmePrivate產生",
        "acme-private",
        "acme_private",
        "acme.private",
        "AcmePrivateModule",
        "AcmePrivate2",
        "XYZGatewayClient",
        "AcmePDQTool",
    ],
)
def test_C_P15_synthetic_names_are_caught(text):
    synthetic = {_sha(name) for name in SYNTHETIC_NAMES}
    assert _hits(text, synthetic), text


@pytest.mark.parametrize("text", ["acme private", "Acmeprivatex"])
def test_C_P15_controls_are_not_caught(text):
    synthetic = {_sha(name) for name in SYNTHETIC_NAMES}
    assert not _hits(text, synthetic), text


@pytest.mark.parametrize(
    "text",
    ["zephyr-tool.md", "my-zephyr-tool", "zephyr_tool.core", "zephyr.tool-v2"],
)
def test_C_P15_compound_parts_are_combined(text):
    synthetic = {_sha("zephyrtool")}
    assert _hits(text, synthetic), text


@pytest.mark.parametrize("text", ["zephyr tool", "zephyrtoolbox"])
def test_C_P15_compound_controls_are_not_caught(text):
    synthetic = {_sha("zephyrtool")}
    assert not _hits(text, synthetic), text


def test_C_P15_scan_scope_includes_tests_and_root_files(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    fillers = {f"a{i}.txt": "nothing here\n" for i in range(1, 7)}
    files = {
        **fillers,
        "tests/hit_test.py": "# zephyr_tool\n",
        "zz_top.md": "see ZephyrTool\n",
    }
    for name, body in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    hits = _scan(_tracked_text_files(tmp_path), {_sha("zephyrtool")})
    assert sorted(hits) == [("tests/hit_test.py", 1), ("zz_top.md", 1)]


def test_C_P15_real_scan_list_includes_guard_and_periodic_doc():
    names = {name for name, _ in _tracked_text_files()}
    assert "tests/test_public_names.py" in names
    assert "docs/periodic.md" in names


def test_C_P15_scanner_ignores_its_own_hash_list_and_test():
    hashes = _load_hashes(HASH_FILE)
    files = [
        (p.name, p.read_text(encoding="utf-8"))
        for p in (HASH_FILE, Path(__file__))
    ]
    assert _scan(files, hashes) == []
