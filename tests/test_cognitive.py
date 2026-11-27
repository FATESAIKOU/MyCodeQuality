"""M1 cognitive complexity: contracts C-M1..C-M5, C-M11, C-M12. All data is synthetic."""
import ast
import json
import subprocess
import sys
import textwrap

from qmetrics import cli, cognitive, metrics


def scores(src):
    return cognitive.scores(ast.parse(textwrap.dedent(src)))


def value(src, name="f"):
    vals = {q: v for (q, k), v in scores(src).items() if k == 0}
    return vals[name]


def many_ifs(name, n):
    return f"def {name}(x):\n" + "".join(f"    if x == {i}:\n        pass\n" for i in range(n))


def run_repo(cwd, *args):
    return subprocess.run([sys.executable, "-m", "qmetrics", "repo", *args],
                          cwd=cwd, capture_output=True, text=True)


# ---- C-M1: rule table R1..R16, one hand-counted value per row ----

def test_C_M1_R1_if_is_structural_and_nests():
    assert value("def f(c, d):\n    if c:\n        if d:\n            pass\n") == 3  # 1 + (1+1)


def test_C_M1_R2_R3_elif_and_else_are_hybrid():
    assert value("def f(c, d):\n    if c:\n        pass\n    elif d:\n        pass\n    else:\n        pass\n") == 3


def test_C_M1_R2_elif_test_is_at_the_parent_nesting():
    src = "def f(c, d, e):\n    if c:\n        pass\n    elif (d if e else d):\n        pass\n"
    assert value(src) == 3  # if 1, elif 1 (no nesting), ternary in the elif test at nesting 0 (1)


def test_C_M1_R2_elif_under_a_loop_is_hybrid_not_nested():
    src = "def f(xs, c, d):\n    for x in xs:\n        if c:\n            pass\n        elif d:\n            pass\n"
    assert value(src) == 4  # for 1, if 1 + nesting 1, elif 1 (no nesting term)


def test_C_M1_R3a_else_with_deeper_if_is_not_elif():
    nested = "def f(c, d):\n    if c:\n        pass\n    else:\n        if d:\n            pass\n"
    flat = "def f(c, d):\n    if c:\n        pass\n    elif d:\n        pass\n"
    assert value(nested) == 4  # 1 + else 1 + inner if (1 + nesting 1)
    assert value(flat) == 2  # 1 + elif 1, same column, no nesting


def test_C_M1_R4_loops_are_structural_and_nest():
    assert value("def f(xs):\n    for x in xs:\n        if x:\n            pass\n") == 3
    assert value("def f(a, b):\n    while a:\n        if b:\n            pass\n") == 3


def test_C_M1_R4_async_for_nests_its_body():
    assert value("async def f(xs, a):\n    async for x in xs:\n        if a:\n            pass\n") == 3


def test_C_M1_R5_loop_else_is_hybrid():
    assert value("def f(xs):\n    for x in xs:\n        pass\n    else:\n        pass\n") == 2
    assert value("def f(a):\n    while a:\n        pass\n    else:\n        pass\n") == 2


def test_C_M1_R6_try_body_and_finally_do_not_nest_or_count():
    assert value("def f():\n    try:\n        x = 1\n    finally:\n        y = 2\n") == 0
    assert value("def f(a):\n    try:\n        if a:\n            pass\n    finally:\n        pass\n") == 1
    assert value("def f(a):\n    try:\n        pass\n    finally:\n        if a:\n            pass\n") == 1


def test_C_M1_R7_each_handler_counts_once_regardless_of_types():
    src = "def f():\n    try:\n        pass\n    except (A, B):\n        pass\n    except C:\n        pass\n"
    assert value(src) == 2
    # the exception type is an expression and is scored like one (boolean sequence here)
    assert value("def f():\n    try:\n        pass\n    except A and B:\n        pass\n") == 2


def test_C_M1_R7_try_with_two_handlers_each_holding_an_if_is_seven():
    src = ("def f(a, b, c):\n    try:\n        if a:\n            pass\n"
           "    except E1:\n        if b:\n            pass\n"
           "    except E2:\n        if c:\n            pass\n")
    assert value(src) == 7  # try's if (1); each handler 1 + its if (1 + nesting 1)


def test_C_M1_R7_except_star_handler_is_scored_like_except():
    src = "def f(a):\n    try:\n        pass\n    except* E:\n        if a:\n            pass\n"
    assert value(src) == 3  # except* (1) + the if in its body (1 + nesting 1)


def test_C_M1_R8_try_else_is_hybrid():
    assert value("def f():\n    try:\n        pass\n    except E:\n        pass\n    else:\n        pass\n") == 2


def test_C_M1_R9_ternary_nests():
    assert value("def f(a, b, c, d, e):\n    return a if b else (c if d else e)\n") == 3
    assert value("def f(a, b, c):\n    return g(a if b else c)\n") == 1


def test_C_M1_R10_match_is_one_increment_for_all_cases():
    three = "def f(v):\n    match v:\n        case 1:\n            pass\n        case 2:\n            pass\n        case _:\n            pass\n"
    assert value(three) == 1
    guarded = "def f(v, a, b):\n    match v:\n        case 1 if a and b:\n            pass\n"
    assert value(guarded) == 2  # match 1 + guard's boolean sequence 1
    body_if = "def f(v, a):\n    match v:\n        case 1:\n            if a:\n                pass\n"
    assert value(body_if) == 3  # match 1 + if (1 + nesting 1)


def test_C_M1_R11_boolean_sequences():
    assert value("def f(a, b, c, d):\n    return a and b or c and d\n") == 3
    assert value("def f(a, b, c, d):\n    return a or b and c or d\n") == 3  # in-order: or, and, or
    assert value("def f(a, b, c):\n    return a and b and c\n") == 1
    assert value("def f(a, b, c):\n    return a and not (b and c)\n") == 2
    # Known difference from SonarQube: the AST has no parentheses, so this is one run
    assert value("def f(a, b, c):\n    return (a and b) and c\n") == 1


def test_C_M1_R12_nested_function_nests_unless_wrapper():
    src = "def f(a):\n    x = a\n    def g():\n        if x:\n            pass\n    return g\n"
    assert value(src) == 2  # g's if at nesting 1, because f is not a wrapper


def test_C_M1_R13_lambda_body_nests_and_adds_nothing_itself():
    assert value("def f(g):\n    return lambda x: (x if g else x)\n") == 2
    assert value("def f():\n    return lambda: 0\n") == 0


def test_C_M1_R14_class_in_function_restarts_method_nesting():
    src = ("def f(c):\n    class K:\n        def m(self, d):\n            if d:\n                pass\n"
           "    return K\n")
    assert value(src) == 1  # the method's if at nesting 0


def test_C_M1_R15_comprehensions_add_nothing():
    assert value("def f(xs):\n    return [x for x in xs if x]\n") == 0
    assert value("def f(xs):\n    return [[y for y in x] for x in xs]\n") == 0


def test_C_M1_R16_with_jumps_await_yield_walrus_add_nothing():
    src = textwrap.dedent("""\
        def f(xs, cm):
            with cm:
                for x in xs:
                    if x:
                        break
                    continue
            return (yield)

        async def g(cm):
            async with cm:
                await cm
                raise ValueError
            z = (w := 3)
            assert z, "msg"
    """)
    got = {q: v for (q, _), v in scores(src).items()}
    assert got["f"] == 3  # the for (1) and the if nested in it (1 + nesting 1); with, break, continue, yield add nothing
    assert got["g"] == 0


def test_C_M1_R16_async_with_adds_nothing_and_does_not_nest():
    assert value("async def f(cm, a):\n    async with cm:\n        if a:\n            pass\n") == 1


def test_C_M1_R17_recursion_is_not_counted():
    assert value("def f(n):\n    return f(n - 1)\n") == 0


def test_C_M1_R18_signature_decorators_and_annotations_are_not_counted():
    src = ("@deco(a if b else c)\n"
           "def f(x=(1 if y else 2), *, z: (int if w else str) = 0) -> (p and q):\n"
           "    pass\n")
    assert value(src) == 0


def test_C_M1_keys_are_units_with_metrics_funcs_keys():
    src = textwrap.dedent("""\
        def dup():
            pass

        def dup():
            def inner():
                pass

        class K:
            def m(self):
                pass

        if True:
            def under_if():
                pass
    """)
    tree = ast.parse(src)
    got = cognitive.scores(tree)
    assert set(got) == {("dup", 0), ("dup", 1), ("K.m", 0), ("under_if", 0)}
    assert set(got) <= set(metrics.funcs(tree))
    assert not any("<locals>" in q for q, _ in got)


def test_C_M1_same_name_defs_under_different_parents_are_all_counted():
    # #31: the top-level f (value 6) and the f under `if a` get different keys (k 0 and 1),
    # so neither unit is dropped
    src = ("def f(a, b, c):\n    if a:\n        if b:\n            if c:\n                pass\n"
           "if a:\n    def f():\n        pass\n")
    assert scores(src) == {("f", 0): 6, ("f", 1): 0}


# ---- C-M1: long expressions must not raise RecursionError (the repo run must still exit 0) ----

def test_C_M1_long_binop_chain_does_not_break_repo(make_repo):
    r = make_repo()
    plus = "def f(a):\n    if a:\n        pass\n    return " + " + ".join(["a"] * 900) + "\n"
    r.commit({"src/a.py": plus})
    res = run_repo(r.path, "--json")
    assert res.returncode == 0, res.stderr[-500:]
    out = json.loads(res.stdout)
    assert out["parse_failures"] == []
    assert out["totals"]["functions"] == 1
    assert out["totals"]["cognitive_units"] == 1
    assert out["totals"]["cognitive"] == 1  # the one if; the + chain adds nothing
    assert out["counts"]["deep_functions"] == 0
    assert out["counts"]["long_functions"] == 0
    assert out["counts"]["complex_functions"] == 0


def test_C_M1_long_method_chain_does_not_break_repo(make_repo):
    r = make_repo()
    chain = "def g(a):\n    if a:\n        pass\n    return " + ".".join(["a(1)"] * 400) + "\n"
    r.commit({"src/b.py": chain})
    res = run_repo(r.path, "--json")
    assert res.returncode == 0, res.stderr[-500:]
    out = json.loads(res.stdout)
    assert out["parse_failures"] == []
    assert out["totals"]["functions"] == 1
    assert out["totals"]["cognitive"] == 1
    assert out["counts"]["deep_functions"] == 0
    assert out["counts"]["complex_functions"] == 0


# ---- C-M2: nested functions, decorators (Appendix A), wrapper boundary ----

def test_C_M2_appendix_a_python_examples_total_1_2_1():
    src = textwrap.dedent("""\
        def tagged_wrapper(func):
            def inner(*args, **kwargs):
                if func:
                    pass
                return func(*args, **kwargs)
            return inner

        def mixed_prelude(func):
            my_var = func * 2
            def inner(*args, **kwargs):
                if func:
                    pass
                return func(*args, **kwargs)
            return inner

        def wrapper_factory(func):
            def tagged_wrapper(func):
                def inner(*args, **kwargs):
                    if func:
                        pass
                    return func(*args, **kwargs)
                return inner
            return tagged_wrapper
    """)
    assert value(src, "tagged_wrapper") == 1
    assert value(src, "mixed_prelude") == 2
    assert value(src, "wrapper_factory") == 1


def test_C_M2_wrapper_boundary_cases():
    only_def = "def f(func):\n    def inner():\n        if func:\n            pass\n    return inner\n"
    doc_def = ("def f(func):\n    \"\"\"doc\"\"\"\n    def inner():\n        if func:\n            pass\n"
               "    return inner\n")
    call_ret = ("def f(func):\n    def inner():\n        if func:\n            pass\n    return inner()\n")
    assert value(only_def) == 1  # wrapper: inner's if at nesting 0
    assert value(doc_def) == 2  # docstring is a statement, so not a wrapper
    assert value(call_ret) == 2  # `return inner()` is not `return <name>`


def test_C_M2_nested_function_is_merged_into_outer_unit():
    src = "def outer(a):\n    x = a\n    def inner():\n        if x:\n            pass\n    return inner\n"
    got = scores(src)
    assert set(got) == {("outer", 0)}
    assert got[("outer", 0)] == 2


def test_C_M2_class_in_function_and_lambda_nesting():
    src = ("def f(g):\n    class K:\n        def m(self, d):\n            if d:\n                pass\n"
           "    h = lambda x: (x if g else x)\n    return K, h\n")
    assert value(src) == 3  # method's if (1) + lambda's ternary at nesting 1 (2)


# ---- C-M3: threshold and denominators (repo level) ----

def test_C_M3_threshold_15_not_listed_16_listed_and_denominators(make_repo):
    r = make_repo()
    r.commit({
        "src/a.py": many_ifs("f15", 15) + "\ndef g():\n    def h():\n        pass\n",
        "src/b.py": many_ifs("f16", 16),
    })
    d = run_repo(r.path, "--json")
    assert d.returncode == 0, d.stderr
    out = json.loads(d.stdout)
    assert out["totals"]["cognitive_units"] == 3  # f15, g (h is merged into g), f16
    assert out["totals"]["functions"] == 4  # the summary-level count still includes h
    assert out["totals"]["cognitive"] == 15 + 0 + 16
    assert out["counts"]["complex_functions"] == 1
    assert out["ratios"]["complex_functions"] == {"num": 1, "den": 3}
    complex_findings = [f for f in out["findings"] if f["kind"] == "complex_function"]
    assert complex_findings == [{"kind": "complex_function", "file": "src/b.py", "function": "f16", "value": 16}]


# ---- C-M4: missing values and not applicable ----

def test_C_M4_parse_failure_makes_new_fields_null(make_repo):
    r = make_repo()
    r.commit({"src/a.py": many_ifs("f16", 16), "src/b.py": "def broken(:\n"})
    res = run_repo(r.path, "--json")
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["totals"]["cognitive_units"] is None
    assert out["totals"]["cognitive"] is None
    assert out["counts"] is None
    assert out["ratios"] is None
    assert out["findings"] is None
    assert [p["file"] for p in out["parse_failures"]] == ["src/b.py"]


def test_C_M4_no_python_files_gives_zero_and_null_ratio(make_repo):
    r = make_repo()
    r.commit({"src/README.txt": "nothing here\n", "tests/test_x.py": "def test_x():\n    pass\n"})
    out = json.loads(run_repo(r.path, "--json").stdout)
    assert out["applicable"] is False
    assert out["totals"]["cognitive_units"] == 0
    assert out["totals"]["cognitive"] == 0
    assert out["counts"]["complex_functions"] == 0
    assert out["ratios"]["complex_functions"] is None


# ---- C-M5: additive only; old items keep their values (repo level) ----

def test_C_M5_old_items_unchanged_and_new_items_added(make_repo):
    r = make_repo()
    deep = ("def fn_deep():\n    if True:\n        if True:\n            if True:\n"
            "                if True:\n                    return 42\n")
    r.commit({"src/a.py": deep, "tests/test_app.py": "def test_one():\n    pass\n"})
    out = json.loads(run_repo(r.path, "--json").stdout)

    assert out["schema_version"] == 1
    assert out["applicable"] is True
    assert out["totals"]["files"] == 1
    assert out["totals"]["functions"] == 1
    assert out["totals"]["tests"] == 1
    assert out["counts"]["long_files"] == 0
    assert out["counts"]["long_functions"] == 0
    assert out["counts"]["deep_functions"] == 1
    assert out["counts"]["ast_dup_functions"] == 0
    assert out["counts"]["dup_windows"] == 0
    assert out["counts"]["smell_events"] == 1  # the new complexity item is not in smell_events
    assert out["ratios"]["long_files"] == {"num": 0, "den": 1}
    assert out["ratios"]["deep_functions"] == {"num": 1, "den": 1}
    assert out["parse_failures"] == []
    assert [f for f in out["findings"] if f["kind"] != "complex_function"] == [
        {"kind": "deep_function", "file": "src/a.py", "function": "fn_deep", "value": 4}
    ]

    assert out["totals"]["cognitive_units"] == 1
    assert out["totals"]["cognitive"] == 1 + 2 + 3 + 4
    assert out["counts"]["complex_functions"] == 0
    assert out["ratios"]["complex_functions"] == {"num": 0, "den": 1}


def test_C_M5_smell_events_excludes_complex_functions(make_repo):
    r = make_repo()
    r.commit({"src/a.py": many_ifs("f16", 16)})
    out = json.loads(run_repo(r.path, "--json").stdout)
    assert out["counts"]["complex_functions"] == 1
    assert out["counts"]["smell_events"] == 0  # the new item is not part of smell_events


# ---- C-M11: deterministic; no clock or network (in-process, stubbed) ----

def test_C_M11_same_bytes_twice_and_no_clock_or_network(make_repo, monkeypatch, capsys):
    import socket
    import time

    r = make_repo()
    r.commit({"src/a.py": many_ifs("f16", 16)})
    argv = ["repo", "--repo", str(r.path), "--json"]

    assert cli.main(argv) == 0
    first = capsys.readouterr().out
    assert cli.main(argv) == 0
    assert capsys.readouterr().out == first

    def forbidden(*args, **kwargs):
        raise RuntimeError("clock or network touched during repo analysis")

    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert cli.main(argv) == 0
    assert capsys.readouterr().out == first


# ---- C-M12: qmetrics diff and gate do not change ----

def test_C_M12_diff_and_gate_ignore_complexity(make_repo, qm, tmp_path):
    r = make_repo()
    base = r.commit({"src/a.py": "x = 0\n"})
    head = r.commit({"src/b.py": many_ifs("f16", 16)})
    d = qm(r.path, "--base", base, "--head", head).data()
    assert d["schema_version"] == 2
    assert "cognitive" not in json.dumps(d)
    assert "complex" not in json.dumps(d)

    f = tmp_path / "q.json"
    f.write_text(json.dumps(d))
    g = subprocess.run([sys.executable, "-I", "-m", "qmetrics", "gate", "--file", str(f),
                        "--event", "pull_request", "--labels-json", "[]"],
                       capture_output=True, text=True)
    assert g.returncode == 0, g.stdout + g.stderr
