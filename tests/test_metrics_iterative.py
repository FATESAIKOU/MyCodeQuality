"""BRIEF #32: depth / funcs / same_ast run without recursion and keep the old outputs.

The expected values below were produced by the previous recursive implementation (HEAD) on the
same synthetic sources and checked by hand where small enough. All data is synthetic.
"""

import ast
import subprocess
import sys
import textwrap

from conftest import Result
from qmetrics import metrics


def tree(src):
    return ast.parse(textwrap.dedent(src))


def fn_rows(src):
    """[(key, start, end, depth, shape is None)] in dict order."""
    return [(k, v[0], v[1], v[2], v[3] is None) for k, v in metrics.funcs(tree(src)).items()]


def chain_src(n):
    return "def method_chain(a):\n    x = a" + "".join(".a(1)" for _ in range(n)) \
        + "\n    y = 1\n    z = 2\n    return x\n"


def elif_src(n):
    s = "def elif_chain(x):\n    if x == 0:\n        return 0\n"
    for i in range(1, n):
        s += f"    elif x == {i}:\n        return {i}\n"
    return s + "    return -1\n"


def nested_if_src(n):
    s = "def f(x):\n"
    ind = "    "
    for i in range(n):
        s += ind + f"if x == {i}:\n"
        ind += "    "
    return s + ind + "return x\n"


# ---- order, names and same-name counting (values from HEAD) ----

def test_funcs_nested_class_and_same_names():
    src = """\
    def f():
        return 1

    class A:
        def f(self):
            return 2

        class B:
            def g(self):
                def h():
                    return 3
                return h

    def f():
        return 4
    """
    assert [r[:4] for r in fn_rows(src)] == [
        (("f", 0), 1, 2, 0),
        (("A.f", 0), 5, 6, 0),
        (("A.B.g", 0), 9, 12, 0),
        (("A.B.g.<locals>.h", 0), 10, 11, 0),
        (("f", 1), 14, 15, 0),
    ]


def test_funcs_defs_under_if_and_try_keep_head_overwrite_rule():
    # Defs under if/try get their own `seen` counter, so the module-level f overwrites ("f", 0)
    src = """\
    if True:
        def f():
            return 1
    else:
        def f():
            return 2

    try:
        def g():
            return 3
    except ValueError:
        pass

    def f():
        return 4
    """
    assert [r[:4] for r in fn_rows(src)] == [
        (("f", 0), 14, 15, 0),
        (("f", 1), 5, 6, 0),
        (("g", 0), 9, 10, 0),
    ]


def test_funcs_async_match_decorator_and_shape_none_for_short_bodies():
    src = """\
    @dec
    async def a(x):
        if x:
            return 1
        return 2

    def m(v):
        match v:
            case 1:
                def k():
                    return 3
                return k
        return None
    """
    assert fn_rows(src) == [
        (("a", 0), 2, 5, 1, True),           # 4 lines: trivial, no shape
        (("m", 0), 7, 13, 1, False),         # match counts as nesting
        (("m.<locals>.k", 0), 10, 11, 0, True),
    ]


# ---- depth ----

def test_depth_nesting_kinds_and_elif_same_level():
    src = """\
    def d(x):
        if x:
            for i in x:
                while i:
                    with i:
                        pass
        elif x > 1:
            pass
        elif x > 2:
            if x:
                pass
        else:
            pass
    """
    assert metrics.depth(tree(src).body[0]) == 4


def test_depth_elif_chain_is_one_level():
    assert metrics.depth(tree(elif_src(3)).body[0]) == 1


# ---- deep inputs: must not raise RecursionError ----

def test_call_chain_900_method_is_measured():
    rows = fn_rows(chain_src(900))
    assert rows == [(("method_chain", 0), 1, 5, 0, True)]  # shape is None: ast.dump would overflow


def test_plus_chain_900_and_elif_600_are_measured():
    plus = "def plus_chain(a):\n    x = " + " + ".join(f"v{i}" for i in range(900)) \
        + "\n    y = 1\n    z = 2\n    return x\n"
    assert fn_rows(plus) == [(("plus_chain", 0), 1, 5, 0, False)]  # ast.dump of this body still fits
    assert fn_rows(elif_src(600)) == [(("elif_chain", 0), 1, 1202, 1, True)]


def test_nested_if_90_depth():
    assert metrics.depth(tree(nested_if_src(90)).body[0]) == 90


def test_shape_is_none_only_when_ast_dump_overflows():
    small = tree("def f(a):\n    x = 1\n    y = 2\n    z = 3\n    return x + y + z\n").body[0]
    assert metrics.shape(small) is not None
    deep = tree(elif_src(600)).body[0]
    assert metrics.shape(deep) is None


# ---- same_ast agrees with ast.dump equality ----

def test_same_ast_matches_ast_dump_verdicts():
    pairs = [
        ("x = 1\n", "x = 1\n", True),
        ("x = 1\n", "x = True\n", False),      # repr differs even though 1 == True
        ("x = 1\n", "x = 1.0\n", False),
        ("a = 'x'\n", "a = b'x'\n", False),
        ("f(a, b)\n", "f(a, b, c)\n", False),
        ("if a:\n    pass\nelse:\n    pass\n", "if a:\n    pass\n", False),
        ("def f(a):\n    return a\n", "def f(a):\n    return a\n", True),
        ("def f(a):\n    return a\n", "async def f(a):\n    return a\n", False),
        (chain_src(900), chain_src(900), True),
        (chain_src(900), chain_src(899), False),
    ]
    for a, b, want in pairs:
        ta, tb = tree(a), tree(b)
        assert metrics.same_ast(ta, tb) is want
        if len(a) < 1000:  # ast.dump itself overflows on the 900-call inputs
            assert (ast.dump(ta, include_attributes=False) == ast.dump(tb, include_attributes=False)) is want


# ---- CLI on deep repos (old code: RecursionError, exit 1) ----

def test_repo_and_diff_exit_zero_on_deep_files(make_repo):
    r = make_repo()
    base = r.commit({"src/base.py": "def g():\n    return 1\n", "tests/test_base.py": "def test_base():\n    pass\n"})
    head = r.commit({"src/chain.py": chain_src(900), "src/plus.py": "def plus_chain(a):\n    x = "
                     + " + ".join(f"v{i}" for i in range(900)) + "\n    y = 1\n    z = 2\n    return x\n",
                     "src/elif.py": elif_src(600)})
    touched = r.commit({"src/chain.py": chain_src(900) + "\ndef extra():\n    return 2\n"})

    rep = Result(subprocess.run([sys.executable, "-m", "qmetrics", "repo", "--json", "--repo", str(r.path),
                                 "--rev", head], capture_output=True, text=True))
    assert rep.rc == 0, rep.err

    for b, h in [(base, head), (head, touched)]:
        proc = subprocess.run([sys.executable, "-m", "qmetrics", "diff", "--json", "--repo", str(r.path),
                               "--base", b, "--head", h], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert "RecursionError" not in proc.stderr
