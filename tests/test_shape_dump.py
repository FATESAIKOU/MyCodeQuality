"""#56: metrics.shape is an iterative dump that never falls back to None. Its text equals ast.dump
on CPython 3.12 (those checks are skipped elsewhere); on every version, shape equality must match
ast.dump equality. All data is synthetic.
"""

import ast
import sys
import textwrap

import pytest

from qmetrics import metrics

PY312 = sys.version_info[:2] == (3, 12)
text_is_ast_dump = pytest.mark.skipif(not PY312, reason="shape text equals ast.dump on 3.12 only")

# 30 adversarial bodies: constant kinds, f-strings, lambda, decorators, match, async, type
# comments, star args, walrus, slices, comprehensions, type params, None inside lists, ...
CASES = [
    "x = 1\ny = -2\nz = 10 ** 30\nw = 0x_ff_ff\n",
    "x = True\ny = None\nz = False\n",
    "x = 1.0\ny = 1e308\nz = -0.0\nw = 1e-7\n",
    "x = 1j\ny = 2.5 + 3j\n",
    "x = 'a\\n\\t\"\\'\u00e9'\ny = '\\u1234\\x00'\n",
    "x = b'\\x00\\xff' + b\"'\"\n",
    "x = ...\ny = a[..., 1]\n",
    "x = f\"a{b!r:>{w}}c{d=}\" 'e' f'{g:x}'\n",
    "x = lambda a, *b, c=1, **d: (a, b, c, d)\n",
    "@dec(1)\n@other.attr\n@x[0]\ndef inner():\n    pass\n",
    "match v:\n    case [1, *r] if r:\n        pass\n    case {'k': q, **kw}:\n        pass\n"
    "    case Point(x=0, y=_) | None:\n        pass\n    case str() as s:\n        pass\n",
    "async def g():\n    async for i in y:\n        await i\n    async with a as b:\n        pass\n"
    "    return [x async for x in z if x]\n",
    "x = 1  # type: int\ny = 2  # type: ignore\n",
    "f(*a, **k)\nz = [*x, *y]\nq = {**a, 'b': 1}\n",
    "if (n := len(a)) > 10:\n    pass\n",
    "x = a[1:2:3, ::-1, :]\ny = a[*b]\n",
    "x = [i for i in a for j in i if j]\ny = {k: v for k, v in b}\nz = (q for q in c)\n",
    "def h[T: int, *Ts, **P](x: T) -> T:\n    return x\ntype X[T] = list[T]\n",
    "def p(a, /, b, *, c=None, d):\n    return a\n",
    "class C(B, metaclass=M):\n    x: int = 1\n    (y): int = 2\n",
    "try:\n    pass\nexcept* ValueError as e:\n    raise X from e\nelse:\n    pass\nfinally:\n    pass\n",
    "with (open(a) as b, open(c) as d):\n    yield from b\n    yield\n",
    "del a.b[c]\nfor (a, *b) in c:\n    global q\n    assert a, 'msg'\n",
    "x = u'x'\ny = 'a' 'b' \"c\"\n",
    "x = ()\ny = []\nz = {}\nreturn_ = (1,)\n",
    "ñ = 1\nµ = ñ + 1\n",
    "import a.b as c\nfrom . import d as e\nnonlocal_ = c\n",
    "x = a if b else c if d else e\ny = not a and (b or c)\n",
    "x = a < b <= c != d is not e in f\n",
    "x = 1 if a else 2\nreturn x\n",
]
assert len(CASES) == 30


def _fn_nodes(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _ref(fn):
    args = ast.arguments(**{f: getattr(fn.args, f) for f in fn.args._fields})
    return ast.dump(ast.Module(body=[args] + fn.body, type_ignores=[]), include_attributes=False)


@text_is_ast_dump
@pytest.mark.parametrize("i", range(len(CASES)))
def test_shape_text_equals_ast_dump_for_adversarial_bodies(i):
    body = textwrap.indent(textwrap.dedent(CASES[i]), "    ")
    src = "def wrapper(p, *q, r: int = 1, **s):\n" + body
    tree = ast.parse(src, type_comments=True)
    fns = _fn_nodes(tree)
    assert fns
    for fn in fns:
        assert metrics.shape(fn) == _ref(fn)


@pytest.mark.parametrize("i", range(len(CASES)))
def test_shape_equality_follows_ast_equality_for_adversarial_bodies(i):
    # every version: function k of the source and function k of a changed copy (one extra
    # statement at the end of the wrapper) agree on equality, whatever ast.dump says
    body = textwrap.indent(textwrap.dedent(CASES[i]), "    ")
    src = "def wrapper(p, *q, r: int = 1, **s):\n" + body
    for a, b in zip(_fn_nodes(ast.parse(src, type_comments=True)),
                    _fn_nodes(ast.parse(src + "    zz = 0\n", type_comments=True))):
        assert (metrics.shape(a) == metrics.shape(b)) is (_ref(a) == _ref(b))


# pairs of functions: shape equality <=> ast.dump equality, checked on whatever Python runs this
EQUIV_PAIRS = [
    ("def f(a):\n    return a\n", "def f(a):\n    return a\n", True),
    ("def f():\n    return\n", "def f():\n    return None\n", False),  # no value vs Constant(None)
    ("def f():\n    return []\n", "def f():\n    return ()\n", False),
    ("def f():\n    x = []\n", "def f():\n    x = [None]\n", False),   # empty list vs one None
    ("def f():\n    x = [1]\n", "def f():\n    x = [1, ]\n", True),
    ("def f():\n    x = 1\n", "def f():\n    x = 1.0\n", False),
    ("def f():\n    x = 1\n", "def f():\n    x = True\n", False),
    ("def f():\n    x = 'a'\n", "def f():\n    x = b'a'\n", False),
    ("def f(*, b):\n    pass\n", "def f(*a):\n    pass\n", False),
    ("def f(*, b=1):\n    pass\n", "def f(*, b=None):\n    pass\n", False),
    ("def f(a, *, b=None):\n    pass\n", "def f(a, *, b=None):\n    pass\n", True),
    ("async def f():\n    return x\n", "def f():\n    return x\n", True),  # shape: arguments + body only
    ("async def f():\n    return x\n", "def f():\n    return y\n", False),
]


@pytest.mark.parametrize("a, b, want", EQUIV_PAIRS)
def test_shape_equality_matches_ast_dump_equality(a, b, want):
    fa, fb = (_fn_nodes(ast.parse(s))[0] for s in (a, b))
    assert (_ref(fa) == _ref(fb)) is want
    assert (metrics.shape(fa) == metrics.shape(fb)) is want


def test_missing_attribute_and_none_give_the_same_shape():
    # an unset `value` (class default None) and value=None dump alike; shape must agree
    a = _fn_nodes(ast.parse("def f():\n    return 1\n"))[0]
    b = _fn_nodes(ast.parse("def f():\n    return 1\n"))[0]
    del a.body[0].value
    b.body[0].value = None
    assert (_ref(a) == _ref(b)) is True
    assert metrics.shape(a) == metrics.shape(b)


@text_is_ast_dump
def test_shape_of_a_function_with_all_argument_kinds_and_defaults():
    src = "def f(a, b=1, /, c=None, *d, e, f=2, **g):\n    return [a, b, c, d, e, f, g]\n"
    fn = _fn_nodes(ast.parse(src))[0]
    assert metrics.shape(fn) == _ref(fn)


def test_shape_is_never_none_for_a_deep_body():
    # 600 nested elifs: ast.dump overflows on this one, the iterative dump does not
    src = "def deep(x):\n    if x == 0:\n        pass\n" + "".join(
        f"    elif x == {i}:\n        pass\n" for i in range(1, 600))
    fn = _fn_nodes(ast.parse(src))[0]
    s = metrics.shape(fn)
    assert isinstance(s, str) and s.startswith("Module(body=[arguments(")
    assert s.count("If(") == 600


@text_is_ast_dump
def test_dump_of_plain_scalars_and_empty_lists_follows_ast_dump():
    for node in (ast.Constant(value=None), ast.Constant(value=b"x"), ast.List(elts=[], ctx=ast.Load()),
                 ast.Name(id="a", ctx=ast.Store()), ast.Pass()):
        assert metrics.dump(node) == ast.dump(node, include_attributes=False)
