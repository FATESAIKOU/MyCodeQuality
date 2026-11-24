import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import Result


def run_repo(cwd, *args, env=None):
    import os
    e = {**os.environ, **(env or {})}
    proc = subprocess.run([sys.executable, "-m", "qmetrics", "repo", *args],
                          cwd=cwd, env=e, capture_output=True, text=True)
    return Result(proc)


def test_C_A1_synthetic_repo_metrics(make_repo):
    r = make_repo()
    long_body = "\n".join(f"    v_{i} = {i}" for i in range(59))
    a_py = f"""def fn_long():
{long_body}

def fn_deep():
    if True:
        if True:
            if True:
                if True:
                    return 42
"""
    shared_block = "\n".join(f"alpha_shared_line_{i} = {100 + i}" for i in range(10))
    b_py = f"""# file b
{shared_block}
"""
    c_py = f"""# file c
{shared_block}
"""
    d_py = """def ast_one():
    y1 = 10
    y2 = 20
    y3 = 30
    return y1 + y2 + y3

def ast_two():
    y1 = 10
    y2 = 20
    y3 = 30
    return y1 + y2 + y3
"""
    test_py = """def test_one():
    pass

def test_two():
    pass

def test_three():
    pass
"""
    r.commit({
        "src/a.py": a_py,
        "src/b.py": b_py,
        "src/c.py": c_py,
        "src/d.py": d_py,
        "tests/test_app.py": test_py,
    })

    res = run_repo(r.path, "--json")
    assert res.rc == 0, res.err
    d = res.data()

    assert d["kind"] == "qmetrics-repo"
    assert d["schema_version"] == 1
    assert d["applicable"] is True

    totals = d["totals"]
    assert totals["files"] == 4
    assert totals["tests"] == 3

    counts = d["counts"]
    assert counts["long_functions"] == 1
    assert counts["deep_functions"] == 1
    assert counts["dup_windows"] >= 1
    assert counts["ast_dup_functions"] == 1

    expected_smell = (counts["long_files"] + counts["long_functions"] + counts["deep_functions"]
                      + counts["ast_dup_functions"] + counts["dup_windows"])
    assert counts["smell_events"] == expected_smell

    ratios = d["ratios"]
    assert set(ratios.keys()) == {"long_files", "long_functions", "deep_functions", "ast_dup_functions"}
    assert "dup_windows" not in ratios
    assert "smell_events" not in ratios

    assert ratios["long_files"]["den"] == totals["files"]
    assert ratios["long_functions"]["den"] == totals["functions"]
    assert ratios["deep_functions"]["den"] == totals["functions"]
    assert ratios["ast_dup_functions"]["den"] == totals["functions"]


def test_C_A2_thresholds(make_repo):
    r1001 = make_repo()
    lines_1001 = "\n".join(f"x_{i} = {i}" for i in range(1001)) + "\n"
    r1001.commit({"src/a.py": lines_1001})
    d1001 = run_repo(r1001.path, "--json").data()
    assert d1001["counts"]["long_files"] == 1

    r1000 = make_repo()
    lines_1000 = "\n".join(f"x_{i} = {i}" for i in range(1000)) + "\n"
    r1000.commit({"src/a.py": lines_1000})
    d1000 = run_repo(r1000.path, "--json").data()
    assert d1000["counts"]["long_files"] == 0

    r_fn = make_repo()
    body_50 = "\n".join(f"    a_{i} = {i}" for i in range(50))  # 1 (def) + 50 lines = 51 lines
    body_49 = "\n".join(f"    b_{i} = {i}" for i in range(49))  # 1 (def) + 49 lines = 50 lines
    deep_4 = """def d4():
    if True:
        if True:
            if True:
                if True:
                    return 1
"""
    deep_3 = """def d3():
    if True:
        if True:
            if True:
                return 1
"""
    r_fn.commit({
        "src/funcs.py": f"""def f51():
{body_50}

def f50():
{body_49}

{deep_4}
{deep_3}
"""
    })
    dfn = run_repo(r_fn.path, "--json").data()
    assert dfn["counts"]["long_functions"] == 1
    assert dfn["counts"]["deep_functions"] == 1


def test_C_A3_tree_at_rev_uncommitted_and_old_commit(make_repo):
    r = make_repo()
    c1 = r.commit({"src/app.py": "def f1():\n    return 1\n"})
    c2 = r.commit({"src/app.py": "def f1():\n    return 1\n\ndef f2():\n    return 2\n"})

    # Make uncommitted changes in working tree: overwrite src/app.py and add untracked file
    (r.path / "src" / "app.py").write_text("def f_uncommitted():\n    return 'dirty'\n")
    (r.path / "src" / "untracked.py").write_text("def f_untracked():\n    pass\n")

    # HEAD measurement matches commit c2, ignoring working tree
    res_head = run_repo(r.path, "--json")
    assert res_head.rc == 0
    d_head = res_head.data()
    assert d_head["rev"] == c2
    assert d_head["totals"]["functions"] == 2
    assert d_head["totals"]["files"] == 1

    # Measuring c1 reads old tree
    res_c1 = run_repo(r.path, "--rev", c1, "--json")
    assert res_c1.rc == 0
    d_c1 = res_c1.data()
    assert d_c1["rev"] == c1
    assert d_c1["totals"]["functions"] == 1
    assert d_c1["totals"]["files"] == 1


def test_C_A4_determinism_byte_identical_findings_order_no_floats(make_repo):
    r = make_repo()
    body_long = "\n".join(f"    v_{i} = {i}" for i in range(60))
    shared_code = "\n".join(f"shared_ident_{i} = {i}" for i in range(8))
    r.commit({
        "src/z.py": f"""def func_z():
{body_long}
{shared_code}
""",
        "src/a.py": f"""# a
{shared_code}
def ast_fn_1():
    x = 1
    y = 2
    z = 3
    return x + y + z

def ast_fn_2():
    x = 1
    y = 2
    z = 3
    return x + y + z
""",
    })

    res1 = run_repo(r.path, "--json")
    res2 = run_repo(r.path, "--json")
    assert res1.rc == 0
    assert res2.rc == 0
    assert res1.out == res2.out

    d = res1.data()
    findings = d["findings"]
    assert len(findings) > 0

    # dup_windows has one finding per file sharing the counted window
    dup_findings = [f for f in findings if f["kind"] == "dup_windows"]
    dup_files = [f["file"] for f in dup_findings]
    assert len(dup_files) == len(set(dup_files))
    for f in dup_findings:
        assert f["function"] is None
        assert f["value"] > 0

    # findings sorted by (kind, file, function or "", value)
    sorted_findings = sorted(findings, key=lambda x: (x["kind"], x["file"], x["function"] or "", x["value"]))
    assert findings == sorted_findings

    # No floats anywhere
    def check_no_floats(val, path=""):
        assert not isinstance(val, float), f"Found float at {path}: {val}"
        if isinstance(val, dict):
            for k, v in val.items():
                check_no_floats(v, f"{path}.{k}")
        elif isinstance(val, list):
            for i, v in enumerate(val):
                check_no_floats(v, f"{path}[{i}]")

    check_no_floats(d)


def test_C_A5_syntax_error_handling(make_repo):
    # Case 1: syntax error in src
    r_src = make_repo()
    r_src.commit({
        "src/good.py": "def good():\n    return 1\n",
        "src/bad.py": "def broken(:\n",
        "tests/test_t.py": "def test_ok():\n    pass\n",
    })
    res_src = run_repo(r_src.path, "--json")
    assert res_src.rc == 0, res_src.err
    d_src = res_src.data()
    assert d_src["totals"]["files"] == 2
    assert d_src["totals"]["lines"] == 3
    assert d_src["totals"]["functions"] is None
    assert d_src["totals"]["tests"] == 1
    assert d_src["counts"] is None
    assert d_src["ratios"] is None
    assert d_src["findings"] is None
    assert d_src["parse_failures"] == [{"file": "src/bad.py", "scope": "src"}]

    # Case 2: syntax error in tests
    r_tests = make_repo()
    r_tests.commit({
        "src/good.py": "def good():\n    return 1\n",
        "tests/test_bad.py": "def broken(:\n",
    })
    res_tests = run_repo(r_tests.path, "--json")
    assert res_tests.rc == 0, res_tests.err
    d_tests = res_tests.data()
    assert d_tests["totals"]["files"] == 1
    assert d_tests["totals"]["functions"] == 1
    assert d_tests["totals"]["tests"] is None
    assert d_tests["counts"] is not None
    assert d_tests["ratios"] is not None
    assert d_tests["findings"] is not None
    assert d_tests["parse_failures"] == [{"file": "tests/test_bad.py", "scope": "tests"}]


def test_C_A6_no_py_files_not_applicable(make_repo):
    r = make_repo()
    r.commit({
        "src/README.txt": "No python files here\n",
        "tests/test_dummy.py": "def test_dummy():\n    pass\n",
    })
    res = run_repo(r.path, "--json")
    assert res.rc == 0, res.err
    d = res.data()
    assert d["applicable"] is False
    assert d["totals"]["files"] == 0
    assert d["totals"]["lines"] == 0
    assert d["totals"]["functions"] == 0
    assert d["totals"]["tests"] == 1
    assert d["counts"] == {
        "long_files": 0,
        "long_functions": 0,
        "deep_functions": 0,
        "ast_dup_functions": 0,
        "dup_windows": 0,
        "smell_events": 0,
    }
    assert d["ratios"] == {
        "long_files": None,
        "long_functions": None,
        "deep_functions": None,
        "ast_dup_functions": None,
    }
    assert d["findings"] == []
    assert d["parse_failures"] == []


def test_C_A7_shallow_clone_grafts_and_unknown_revision(make_repo, tmp_path):
    r = make_repo()
    r.commit({"src/a.py": "def f():\n    pass\n"}, msg="commit 1")
    c2 = r.commit({"src/a.py": "def f():\n    return 1\n"}, msg="commit 2")

    # Shallow clone with depth 1
    shallow_dir = tmp_path / "shallow_repo"
    import os
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    subprocess.run(["git", "clone", "--depth", "1", f"file://{r.path}", str(shallow_dir)],
                   check=True, capture_output=True, env=env)

    # qmetrics repo succeeds on shallow clone
    res_repo = run_repo(shallow_dir, "--json")
    assert res_repo.rc == 0, res_repo.err

    # qmetrics diff on shallow clone fails with shallow_repository
    proc_diff = subprocess.run([sys.executable, "-m", "qmetrics", "diff", "--base", "HEAD~1", "--head", "HEAD"],
                               cwd=shallow_dir, capture_output=True, text=True, env=env)
    assert proc_diff.returncode == 2
    assert "shallow_repository" in proc_diff.stderr

    # Grafts present in repo
    info_dir = r.gitdir() / "info"
    info_dir.mkdir(parents=True, exist_ok=True)
    grafts_file = info_dir / "grafts"
    grafts_file.write_text("0000000000000000000000000000000000000000\n")
    try:
        res_grafts = run_repo(r.path, "--json")
        assert res_grafts.rc == 2
        assert "grafts_present" in res_grafts.err
    finally:
        grafts_file.unlink()

    # Unknown revision
    res_badrev = run_repo(r.path, "--rev", "invalid_rev_spec_unknown", "--json")
    assert res_badrev.rc == 2
    assert res_badrev.out == ""
    assert "error unknown_revision:" in res_badrev.err


def test_C_A8_diff_and_gate_unchanged(make_repo, tmp_path):
    r = make_repo()
    c1 = r.commit({"src/a.py": "def f():\n    pass\n"})
    c2 = r.commit({"src/a.py": "def f():\n    return 1\n"})
    proc = subprocess.run([sys.executable, "-m", "qmetrics", "diff", "--base", c1, "--head", c2, "--json"],
                          cwd=r.path, capture_output=True, text=True)
    assert proc.returncode == 0
    d = json.loads(proc.stdout)
    assert d["schema_version"] == 2
    assert d["code_change"] is True

    # Gate test
    report_file = tmp_path / "diff_report.json"
    report_file.write_text(proc.stdout)
    proc_gate = subprocess.run([sys.executable, "-m", "qmetrics", "gate",
                                "--file", str(report_file), "--event", "pull_request",
                                "--labels-json", "[]"],
                               capture_output=True, text=True)
    assert proc_gate.returncode in (0, 1)
