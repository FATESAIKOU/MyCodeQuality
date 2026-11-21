"""Modes, code_change, parse failures, not-applicable."""
import json


def test_real_merge_commit_uses_first_parent(make_repo, qm):
    repo = make_repo()
    repo.commit({"src/a.py": "x = 0\n"}, "base")
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit({"src/f.py": "def f():\n    return 1\n"}, "feature")
    repo.git("checkout", "-q", "main")
    main_tip = repo.commit({"src/a.py": "x = 1\n"}, "main moves")
    repo.git("merge", "-q", "--no-ff", "-m", "merge", "feature")
    merge = repo.git("rev-parse", "HEAD")
    d = qm(repo.path, "--merge", merge).data()
    assert (d["basis"], d["base"], d["head"]) == ("first_parent", main_tip, merge)
    assert d["code_change"] is True


def test_pr_mode_uses_merge_base(make_repo, qm):
    repo = make_repo()
    fork = repo.commit({"src/a.py": "x = 0\n"}, "base")
    repo.git("checkout", "-q", "-b", "feature")
    head = repo.commit({"src/f.py": "def f():\n    return 1\n"}, "feature")
    repo.git("checkout", "-q", "main")
    repo.commit({"src/a.py": "x = 1\n"}, "main moves")
    d = qm(repo.path, "--pr-base", "main", "--pr-head", "feature").data()
    assert (d["basis"], d["base"], d["head"]) == ("merge_base", fork, head)
    assert d["counts"]["changed_fns"] == 1


def test_comment_only_and_tests_only_are_not_code_changes(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 0\n", "tests/test_a.py": "def test_one():\n    pass\n"}, "base")
    c1 = repo.commit({"src/a.py": "x = 0  # note\n"}, "comment")
    c2 = repo.commit({"tests/test_a.py": "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n"}, "tests")
    assert qm(repo.path, "--base", base, "--head", c1).data()["code_change"] is False
    d = qm(repo.path, "--base", c1, "--head", c2).data()
    assert (d["code_change"], d["tests_touched"], d["net_new_tests"]) == (False, True, 1)


def test_src_and_tests_options(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"lib/a.py": "x = 0\n", "t/test_a.py": "def test_one():\n    pass\n"}, "base")
    head = repo.commit({"lib/a.py": "x = 1\n", "t/test_a.py": "def test_one():\n    pass\n\ndef test_two():\n    pass\n"})
    d = qm(repo.path, "--base", base, "--head", head, "--src", "lib", "--tests", "t").data()
    assert (d["code_change"], d["net_new_tests"], d["applicable"]) == (True, 1, True)


def test_unparsable_file_is_listed_not_guessed(make_repo, qm):
    repo = make_repo()
    fine = "def f():\n    return 1\n"
    base = repo.commit({"src/ok.py": fine, "src/bad.py": "def g(:\n"}, "base")
    head = repo.commit({"src/ok.py": fine + "\n\ndef h():\n    return 2\n", "src/bad.py": "def g(:\n    pass\n"})
    d = qm(repo.path, "--base", base, "--head", head).data()
    assert d["parse_failures"] == [{"file": "src/bad.py", "side": "base", "scope": "src"},
                                   {"file": "src/bad.py", "side": "head", "scope": "src"}]
    assert {e["file"] for e in d["events"]} == {"src/ok.py"}
    assert d["code_change"] is True  # decided by the parsable file only
    assert set(d["counts"].values()) == {None} and d["grew_over50"] is None


def test_unparsable_only_gives_unknown_code_change(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/bad.py": "def g(:\n"}, "base")
    head = repo.commit({"src/bad.py": "def g(:\n    pass\n"})
    r = qm(repo.path, "--base", base, "--head", head)
    d = r.data()
    assert r.rc == 0
    assert d["code_change"] is None and len(d["parse_failures"]) == 2
    assert set(d["counts"].values()) == {None} and d["grew_over50"] is None
    assert d["events"] == []


def test_bad_parse_is_not_false(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 1\n"}, "base")
    head = repo.commit({"src/a.py": "def x(:\n"})
    r = qm(repo.path, "--base", base, "--head", head)
    assert r.rc == 0
    d = r.data()
    assert d["code_change"] is None
    assert d["parse_failures"] == [{"file": "src/a.py", "side": "head", "scope": "src"}]


def test_unchanged_unparsable_reference_nulls_counts_only(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/old.py": "def g(:\n", "src/a.py": "x = 1\n"}, "base")
    head = repo.commit({"src/a.py": "x = 2\n"})
    d = qm(repo.path, "--base", base, "--head", head).data()
    assert d["code_change"] is True
    assert set(d["counts"].values()) == {None}
    assert d["parse_failures"] == [{"file": "src/old.py", "side": "base", "scope": "src"},
                                   {"file": "src/old.py", "side": "head", "scope": "src"}]


def test_events_of_parsable_files_kept_when_incomplete(make_repo, qm):
    repo = make_repo()

    def f(n):
        return "def f():\n" + "".join(f"    v{i} = {i}\n" for i in range(n))

    base = repo.commit({"src/f.py": f(45), "src/bad.py": "def g(:\n"}, "base")
    head = repo.commit({"src/f.py": f(55), "src/bad.py": "def g(:\n    pass\n"})
    d = qm(repo.path, "--base", base, "--head", head).data()
    assert d["counts"]["crossing_50"] is None
    assert [e["file"] for e in d["events"] if e["kind"] == "crossing_50"] == ["src/f.py"]


def test_summary_marks_unknown(make_repo):
    import subprocess, sys
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 1\n", "tests/test_a.py": "def test_a(:\n"}, "base")
    head = repo.commit({"src/a.py": "def x(:\n", "tests/test_a.py": "def test_a(:\n    pass\n"})
    proc = subprocess.run([sys.executable, "-m", "qmetrics", "diff", "--base", base, "--head", head],
                          cwd=repo.path, capture_output=True, text=True)
    assert proc.returncode == 0
    out = proc.stdout
    assert "INCOMPLETE:" in out
    assert "code_change: unknown" in out and "net_new_tests: unknown" in out
    assert "crossing_50: unknown" in out and "grew_over50: unknown" in out
    assert "code_change: false" not in out
    assert "parse_failure (src, head): src/a.py -> undetermined" in out


def test_schema_version_is_2(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 1\n"}, "base")
    head = repo.commit({"src/a.py": "x = 2\n"})
    assert qm(repo.path, "--base", base, "--head", head).data()["schema_version"] == 2


def test_string_is_not_a_test(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 1\n", "tests/test_a.py": "x = 1\n"}, "base")
    head = repo.commit({"tests/test_a.py": 'x = 1\ns = """\ndef test_fake():\n    pass\n"""\n'})
    assert qm(repo.path, "--base", base, "--head", head).data()["net_new_tests"] == 0


def test_net_new_tests_counts_methods_and_async(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 1\n",
                        "tests/test_a.py": "def test_old():\n    pass\n"}, "base")
    head = repo.commit({"tests/test_a.py": "class T:\n    def test_m(self):\n        pass\n\n\n"
                                           "async def test_a():\n    pass\n"})
    assert qm(repo.path, "--base", base, "--head", head).data()["net_new_tests"] == 1


def test_net_new_tests_unknown_on_test_syntax_error(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 1\n", "tests/test_a.py": "def test_a():\n    pass\n"}, "base")
    head = repo.commit({"src/a.py": "x = 2\n", "tests/test_a.py": "def test_a(:\n"})
    d = qm(repo.path, "--base", base, "--head", head).data()
    assert d["net_new_tests"] is None
    assert d["parse_failures"] == [{"file": "tests/test_a.py", "side": "head", "scope": "tests"}]
    assert d["code_change"] is True and d["counts"]["changed_fns"] == 0
    assert d["grew_over50"] == 0


def test_deleted_test_file_counts_negative(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 1\n",
                        "tests/test_a.py": "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n"}, "base")
    head = repo.commit({}, "rm", delete=["tests/test_a.py"])
    assert qm(repo.path, "--base", base, "--head", head).data()["net_new_tests"] == -2


def test_whole_function_deletion_is_changed(make_repo, qm):
    repo = make_repo()
    f = "def f():\n" + "".join(f"    v{i} = {i}\n" for i in range(19))
    base = repo.commit({"src/a.py": f + "\nX = 1\n"}, "base")
    head = repo.commit({"src/a.py": "X = 1\n"})
    d = qm(repo.path, "--base", base, "--head", head).data()
    assert d["code_change"] is True and d["counts"]["changed_fns"] == 1
    assert d["events"] == [{"file": "src/a.py", "function": "f", "kind": "changed_function",
                            "before": 20, "after": 0}]


def test_deleted_file_functions_are_changed(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.py": "def f():\n    return 1\n\n\ndef g():\n    return 2\n",
                        "src/b.py": "x = 1\n"}, "base")
    head = repo.commit({}, "rm", delete=["src/a.py"])
    d = qm(repo.path, "--base", base, "--head", head).data()
    assert d["counts"]["changed_fns"] == 2 and d["code_change"] is True


def test_incomplete_run_is_byte_identical(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 1\n", "src/bad.py": "def g(:\n"}, "base")
    head = repo.commit({"src/a.py": "def x(:\n", "src/bad.py": "def g(:\n    pass\n"})
    a = qm(repo.path, "--base", base, "--head", head)
    b = qm(repo.path, "--base", base, "--head", head)
    assert a.out == b.out and a.data()["code_change"] is None


def test_no_python_under_src_is_not_applicable(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/a.js": "var a = 1;\n"}, "base")
    head = repo.commit({"src/a.js": "var a = 2;\n"})
    r = qm(repo.path, "--base", base, "--head", head)
    assert r.rc == 0
    assert r.data()["applicable"] is False and r.data()["code_change"] is False


def test_summary_output_without_json_flag(make_repo):
    import subprocess, sys, os
    repo = make_repo()
    base = repo.commit({"src/a.py": "x = 0\n"}, "base")
    head = repo.commit({"src/a.py": "x = 1\n"})
    proc = subprocess.run([sys.executable, "-m", "qmetrics", "diff", "--base", base, "--head", head],
                          cwd=repo.path, capture_output=True, text=True)
    assert proc.returncode == 0
    assert "code_change: true" in proc.stdout and not proc.stdout.lstrip().startswith("{")


def test_crossing_1000_and_depth_events(make_repo, qm):
    repo = make_repo()
    deep = "def d(a):\n    if a:\n        for i in a:\n            while i:\n                if i:\n                    return 1\n"
    base = repo.commit({"src/big.py": "x = 1\n" * 999, "src/d.py": "def d(a):\n    return a\n"}, "base")
    head = repo.commit({"src/big.py": "x = 1\n" * 1001, "src/d.py": deep})
    d = qm(repo.path, "--base", base, "--head", head).data()
    assert d["counts"]["crossing_1000"] == 1
    assert d["counts"]["crossing_depth4"] == 1
    assert d["counts"]["smell_events"] == 2
    ev = [e for e in d["events"] if e["kind"] == "crossing_1000"][0]
    assert (ev["file"], ev["before"], ev["after"]) == ("src/big.py", 999, 1001)


def test_grew_over50_is_reported_only(make_repo, qm):
    repo = make_repo()

    def f(n):
        return "def f():\n" + "".join(f"    v{i} = {i}\n" for i in range(n))

    base = repo.commit({"src/f.py": f(60)}, "base")
    head = repo.commit({"src/f.py": f(115)})
    d = qm(repo.path, "--base", base, "--head", head).data()
    assert d["grew_over50"] == 1
    assert d["counts"]["smell_events"] == 0
    assert json.dumps(d)  # plain data
