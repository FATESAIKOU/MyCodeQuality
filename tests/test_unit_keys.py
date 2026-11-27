"""#31 / #56: unit keys per qualname (defs under if/try/with count in the same walk), and
cognitive._units without recursion at module and class level. All data is synthetic, except the
three stdlib files named below, which are only read and counted.
"""

import ast
import json
import os
import subprocess
import sys
import textwrap

import pytest

from qmetrics import cognitive, metrics


def tree(src):
    return ast.parse(textwrap.dedent(src))


def func_keys(src):
    return list(metrics.funcs(tree(src)))


def unit_keys(src):
    return set(cognitive.scores(tree(src)))


# ---- same-name defs in different blocks of one scope get different k ----

def test_top_level_def_and_def_under_if_get_k0_and_k1():
    src = """\
    def f(a):
        return a
    if X:
        def f(a):
            if a:
                return 1
            return 2
    """
    assert func_keys(src) == [("f", 0), ("f", 1)]
    assert cognitive.scores(tree(src)) == {("f", 0): 0, ("f", 1): 1}


def test_if_else_branches_do_not_overwrite_each_other():
    src = """\
    if X:
        def f():
            return 1
    else:
        def f():
            for i in X:
                pass
    """
    assert func_keys(src) == [("f", 0), ("f", 1)]
    assert cognitive.scores(tree(src)) == {("f", 0): 0, ("f", 1): 1}


def test_try_body_and_except_handler_are_one_scope():
    src = """\
    try:
        def f():
            return 1
    except ValueError:
        def f():
            if X:
                pass
    """
    assert func_keys(src) == [("f", 0), ("f", 1)]
    assert cognitive.scores(tree(src)) == {("f", 0): 0, ("f", 1): 1}


def test_class_body_conditional_methods_are_one_scope():
    src = """\
    class K:
        if X:
            def m(self):
                pass
        else:
            def m(self):
                for i in X:
                    pass
    """
    assert func_keys(src) == [("K.m", 0), ("K.m", 1)]
    assert cognitive.scores(tree(src)) == {("K.m", 0): 0, ("K.m", 1): 1}


def test_same_name_in_different_scopes_does_not_share_a_counter():
    # `f` in a class and `f` at module level have different qualnames: both are k 0
    src = """\
    class C:
        def f(self):
            pass
    if X:
        def f():
            pass
    """
    assert func_keys(src) == [("C.f", 0), ("f", 0)]
    assert unit_keys(src) == {("C.f", 0), ("f", 0)}


def test_nested_defs_under_blocks_inside_a_function_share_the_function_scope():
    src = """\
    def outer(c):
        if c:
            def inner():
                return 1
        def inner():
            if c:
                return 2
        return inner
    """
    assert func_keys(src) == [("outer", 0), ("outer.<locals>.inner", 0), ("outer.<locals>.inner", 1)]
    # nested defs belong to the unit: only outer is a scoring unit
    assert unit_keys(src) == {("outer", 0)}


def test_with_and_for_blocks_count_in_the_enclosing_scope():
    src = """\
    with open(p) as fh:
        def f():
            pass
    for i in X:
        def f():
            pass
    while X:
        def f():
            pass
    """
    assert func_keys(src) == [("f", 0), ("f", 1), ("f", 2)]
    assert unit_keys(src) == {("f", 0), ("f", 1), ("f", 2)}


def test_units_keys_are_the_funcs_keys_outside_nested_functions():
    src = """\
    def f():
        pass
    if X:
        def f():
            pass
    class K:
        if X:
            def m(self):
                def inner():
                    pass
    """
    funcs_keys = set(metrics.funcs(tree(src)))
    units = unit_keys(src)
    assert units == {k for k in funcs_keys if "<locals>" not in k[0]}
    assert units <= funcs_keys


# ---- deep inputs outside functions: no RecursionError, exit 0 ----

def _chain(n):
    return "x = a" + ".b(1)" * n + "\n"


def _plus(n):
    return "x = " + " + ".join(f"v{i}" for i in range(n)) + "\n"


def test_module_level_deep_chain_and_sum_have_no_units_and_do_not_recurse():
    for src in (_chain(900), _plus(2000)):
        assert cognitive.scores(ast.parse(src)) == {}
        assert metrics.funcs(ast.parse(src)) == {}


def test_class_level_deep_chain_and_sum_have_no_units_and_do_not_recurse():
    for src in ("class K:\n    x = a" + ".b(1)" * 900 + "\n", "class K:\n    x = " + " + ".join(
            f"v{i}" for i in range(2000)) + "\n"):
        assert cognitive.scores(ast.parse(src)) == {}
        assert metrics.funcs(ast.parse(src)) == {}


def test_repo_and_diff_exit_zero_with_deep_module_and_class_bodies(make_repo):
    r = make_repo()
    base = r.commit({"src/base.py": "def g():\n    return 1\n", "tests/test_base.py": "def test_base():\n    pass\n"})
    head = r.commit({
        "src/mod.py": _chain(900) + _plus(2000) + "def f():\n    return 1\n",
        "src/cls.py": "class K:\n    x = a" + ".b(1)" * 900 + "\n    y = " + " + ".join(
            f"v{i}" for i in range(2000)) + "\n",
        "src/collide.py": "def f():\n    return 1\nif X:\n    def f():\n        return 2\n",
    })
    rep = subprocess.run([sys.executable, "-m", "qmetrics", "repo", "--json", "--repo", str(r.path),
                          "--rev", head], capture_output=True, text=True)
    assert rep.returncode == 0, rep.stderr
    out = json.loads(rep.stdout)
    assert out["parse_failures"] == []
    # head src: g (base.py), f (mod.py), f and the f under if (collide.py): all four counted
    assert out["totals"]["functions"] == 4
    assert "RecursionError" not in rep.stderr

    proc = subprocess.run([sys.executable, "-m", "qmetrics", "diff", "--json", "--repo", str(r.path),
                           "--base", base, "--head", head], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "RecursionError" not in proc.stderr


# ---- one k per qualname for the whole walk: an outer def repeated in a block, or a redefined class,
# must not overwrite the defs inside it (#31 review: the per-frame numbering lost them) ----

def test_repeated_outer_def_keeps_the_inner_defs_of_both_copies():
    src = """\
    def f():
        def g():
            pass
    if X:
        def f():
            def g():
                pass
    """
    funcs = metrics.funcs(tree(src))
    assert set(funcs) == {("f", 0), ("f.<locals>.g", 0), ("f", 1), ("f.<locals>.g", 1)}
    # def line of each key: the top f, its g, the f under if, and that f's g
    assert [funcs[k][0] for k in [("f", 0), ("f.<locals>.g", 0), ("f", 1), ("f.<locals>.g", 1)]] == [1, 2, 5, 6]
    assert set(cognitive.scores(tree(src))) == {("f", 0), ("f", 1)}


def test_if_else_classes_with_the_same_method_keep_both_methods():
    src = """\
    if X:
        class A:
            def m(self):
                return 1
    else:
        class A:
            def m(self):
                return 2
    """
    assert set(func_keys(src)) == {("A.m", 0), ("A.m", 1)}
    assert cognitive.scores(tree(src)) == {("A.m", 0): 0, ("A.m", 1): 0}


def test_redefined_class_keeps_the_method_of_each_definition():
    src = """\
    class A:
        def m(self):
            pass
    class A:
        def m(self):
            for i in X:
                pass
    """
    assert set(func_keys(src)) == {("A.m", 0), ("A.m", 1)}
    assert cognitive.scores(tree(src)) == {("A.m", 0): 0, ("A.m", 1): 1}


# ---- real files with repeated scopes (stdlib, read only): every def is a key ----

STDLIB_COLLISIONS = ["multiprocessing/context.py", "multiprocessing/heap.py", "test/support/os_helper.py"]


@pytest.mark.parametrize("rel", STDLIB_COLLISIONS)
def test_stdlib_files_with_repeated_scopes_keep_every_def(rel):
    path = os.path.join(os.path.dirname(os.__file__), rel)
    if not os.path.exists(path):
        pytest.skip(f"{rel} is not installed in this interpreter")
    with open(path, encoding="utf-8") as fh:
        t = ast.parse(fh.read())
    defs = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(t))
    assert len(metrics.funcs(t)) == defs
    assert set(cognitive.scores(t)) == {k for k in metrics.funcs(t) if "<locals>" not in k[0]}
