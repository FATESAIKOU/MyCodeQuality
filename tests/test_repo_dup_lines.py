"""PR-M3 (duplicate lines): contracts C-M10 (values), C-M11 (determinism, no clock/network), C-M12 (diff/gate unchanged)."""

import json
import subprocess
import sys
import time
from types import SimpleNamespace

from conftest import Result
from qmetrics import cli, metrics


def run_repo(cwd, *args):
    proc = subprocess.run([sys.executable, "-m", "qmetrics", "repo", "--json", *args],
                          cwd=cwd, capture_output=True, text=True)
    return Result(proc)


def block(tag, n=8):
    return "\n".join(f"{tag}_row_{i} = {100 + i}" for i in range(n))


def test_C_M10_two_files_share_eight_rows(make_repo):
    shared = block("alpha")
    r = make_repo()
    r.commit({"src/a.py": shared + "\n", "src/b.py": "# b\n" + shared + "\n"})
    d = run_repo(r.path).data()
    assert d["counts"]["dup_windows"] == 3
    assert d["counts"]["dup_lines"] == 16  # rows, not windows: 8 per file
    assert d["ratios"]["dup_lines"] == {"num": 16, "den": d["totals"]["lines"]}
    assert d["totals"]["lines"] == 17  # 8 in a.py, 1 comment + 8 in b.py


def test_C_M10_same_file_duplicate_counts_zero(make_repo):
    shared = block("inner")
    r = make_repo()
    r.commit({"src/only.py": f"{shared}\n\n{shared}\n"})
    d = run_repo(r.path).data()
    assert d["counts"]["dup_windows"] == 0
    assert d["counts"]["dup_lines"] == 0
    assert d["ratios"]["dup_lines"] == {"num": 0, "den": d["totals"]["lines"]}


def test_C_M10_three_files_share_one_block(make_repo):
    shared = block("tri")
    r = make_repo()
    r.commit({
        "src/f1.py": shared + "\n",
        "src/f2.py": shared + "\n",
        "src/f3.py": shared + "\n",
    })
    d = run_repo(r.path).data()
    assert d["counts"]["dup_windows"] == 3
    assert d["counts"]["dup_lines"] == 24  # 8 rows in each of the three files, each row once


def test_C_M10_overlapping_duplicates_count_each_row_once(make_repo):
    # a and b share all 10 rows (5 windows); c shares only the first 6 rows (window 0).
    # Window rows add up to 30 per file, but distinct rows are 10 + 10 + 6 = 26.
    ten = block("ov", 10)
    six = block("ov", 6)
    r = make_repo()
    r.commit({
        "src/a.py": ten + "\n",
        "src/b.py": ten + "\n",
        "src/c.py": six + "\n" + "unique_c_tail = 999\n",
    })
    d = run_repo(r.path).data()
    assert d["counts"]["dup_windows"] == 5
    assert d["counts"]["dup_lines"] == 26


def test_C_M10_blank_and_comment_rows_are_not_counted(make_repo):
    # rows are interleaved with blank and comment lines; only the 8 valid rows count per file
    interleaved = "\n".join(f"{row}\n\n# note {i}" for i, row in enumerate(block("gap").split("\n")))
    r = make_repo()
    r.commit({"src/a.py": interleaved + "\n", "src/b.py": interleaved + "\n"})
    d = run_repo(r.path).data()
    assert d["counts"]["dup_windows"] == 3
    assert d["counts"]["dup_lines"] == 16
    assert d["totals"]["lines"] == 48  # 24 physical lines per file
    assert d["ratios"]["dup_lines"] == {"num": 16, "den": 48}


def test_C_M10_denominator_zero_gives_null(make_repo):
    r = make_repo()
    r.commit({"src/empty.py": "", "tests/test_x.py": "def test_x():\n    pass\n"})
    d = run_repo(r.path).data()
    assert d["applicable"] is True
    assert d["totals"]["lines"] == 0
    assert d["counts"]["dup_lines"] == 0
    assert d["ratios"]["dup_lines"] is None


def test_C_M10_not_applicable_counts_zero_ratio_null(make_repo):
    r = make_repo()
    r.commit({"src/README.txt": "no python\n", "tests/test_x.py": "def test_x():\n    pass\n"})
    d = run_repo(r.path).data()
    assert d["applicable"] is False
    assert d["counts"]["dup_lines"] == 0
    assert d["ratios"]["dup_lines"] is None


def test_C_M10_syntax_error_gives_null_counts(make_repo):
    r = make_repo()
    r.commit({"src/bad.py": "def broken(:\n", "src/ok.py": block("x") + "\n"})
    d = run_repo(r.path).data()
    assert d["counts"] is None
    assert d["ratios"] is None


def test_C_M10_window_lines_keys_equal_windows():
    text = "\n".join(["a = 1", "# c", "", "bb = 22", "ccc = 333", "dddd = 4444",
                      "e = 5", "ffff = 6666", "gg = 77"])
    lines = metrics.lines_of(text)
    assert set(metrics.window_lines(lines)) == metrics.windows(lines)
    rows = metrics.window_lines(lines)
    # the first window covers the 6 valid rows (1, 4, 5, 6, 7, 8), skipping the comment and blank
    first = min(rows, key=lambda w: min(rows[w]))
    assert rows[first] == {1, 4, 5, 6, 7, 8}


def test_C_M11_twice_same_bytes(make_repo):
    shared = block("det")
    r = make_repo()
    r.commit({"src/a.py": shared + "\n", "src/b.py": "# b\n" + shared + "\n"})
    first = run_repo(r.path)
    second = run_repo(r.path)
    assert first.rc == 0 and second.rc == 0
    assert first.out == second.out


def test_C_M11_no_clock_no_network(make_repo, monkeypatch):
    import socket

    shared = block("clk")
    r = make_repo()
    r.commit({"src/a.py": shared + "\n", "src/b.py": "# b\n" + shared + "\n"})

    def forbidden(*args, **kwargs):
        raise RuntimeError("forbidden clock or network call during repo analysis")

    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    report = cli.run_repo(SimpleNamespace(repo=str(r.path), rev="HEAD", src="src", tests="tests"))
    assert report["counts"]["dup_lines"] == 16
    assert json.loads(cli.render_json(report))["counts"]["dup_lines"] == 16


def test_C_M12_diff_output_has_no_dup_lines(make_repo):
    shared = block("diffdup")
    r = make_repo()
    r.commit({"src/a.py": "x = 1\n", "tests/test_a.py": "def test_a():\n    pass\n"})
    base = r.git("rev-parse", "HEAD")
    r.commit({"src/a.py": "x = 1\n" + shared + "\n", "src/b.py": shared + "\n"})
    proc = subprocess.run([sys.executable, "-m", "qmetrics", "diff", "--json",
                           "--base", base, "--head", "HEAD"],
                          cwd=r.path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "dup_lines" not in proc.stdout
