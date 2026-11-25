"""Cognitive complexity per scoring unit, for Python source (stdlib `ast` only).

A scoring unit is a function that is not inside another function (module-level functions and
methods). Functions nested in a unit, lambdas and classes inside it are scored into the unit.
Keys are the `metrics.funcs` keys, restricted to units. No threshold here (see repo.py).

Comments cite the rule-table rows as R1-R18 (rows R17 and R18 are deliberately not counted).
"""

import ast
from collections import defaultdict

from qmetrics.metrics import FN


def scores(tree):
    """-> {(qualname, k): value} for the scoring units of one module AST (None -> {})."""
    if tree is None:
        return {}
    s = _Scorer(tree)
    return {key: s.body(fn.body, 0) for key, fn in _units(tree).items()}


def _units(tree):
    # same walk as metrics.funcs, but a function's body is not entered (its nested defs belong to it)
    out = {}

    def walk(node, prefix):
        seen = defaultdict(int)
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, FN):
                q = prefix + ch.name
                out[(q, seen[q])] = ch
                seen[q] += 1
            elif isinstance(ch, ast.ClassDef):
                walk(ch, prefix + ch.name + ".")
            else:
                walk(ch, prefix)

    walk(tree, "")
    return out


def _scope_defs(nodes):
    # defs reachable from `nodes` without crossing another function, a class, or an expression
    for n in nodes:
        if isinstance(n, FN):
            yield n
        elif isinstance(n, (ast.ClassDef, ast.expr)):
            continue
        else:
            yield from _scope_defs(ast.iter_child_nodes(n))


def _simple_return(s):
    # `return <single name>`: the only statement shape a wrapper may contain besides its def
    return isinstance(s, ast.Return) and isinstance(s.value, ast.Name)


class _Scorer:
    def __init__(self, tree):
        self.zero = set()      # defs directly in a class body: nesting restarts at 0 (R14)
        self.wrappers = set()  # nested defs whose enclosing function is a wrapper (R12)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self.zero.update(id(d) for d in _scope_defs(node.body))
            elif isinstance(node, FN):
                for d in node.body:
                    if isinstance(d, FN) and all(_simple_return(s) for s in node.body if s is not d):
                        self.wrappers.add(id(d))

    def body(self, stmts, nest):
        return sum(self.stmt(s, nest) for s in stmts)

    def else_(self, orelse, nest):
        # R3 / R5 / R8: the else of if, for, while and try is a hybrid +1, no nesting term
        return 1 + self.body(orelse, nest + 1) if orelse else 0

    def stmt(self, node, nest):
        if isinstance(node, ast.If):
            return self.if_(node, nest, elif_=False)
        if isinstance(node, (ast.For, ast.AsyncFor)):  # R4, R5
            return (1 + nest + self.expr(node.iter, nest) + self.body(node.body, nest + 1)
                    + self.else_(node.orelse, nest))
        if isinstance(node, ast.While):  # R4, R5
            return (1 + nest + self.expr(node.test, nest) + self.body(node.body, nest + 1)
                    + self.else_(node.orelse, nest))
        if isinstance(node, (ast.Try, ast.TryStar)):  # R6, R7, R8
            score = self.body(node.body, nest) + self.body(node.finalbody, nest)
            for h in node.handlers:
                score += 1 + nest + (self.expr(h.type, nest) if h.type else 0)
                score += self.body(h.body, nest + 1)
            return score + self.else_(node.orelse, nest)
        if isinstance(node, (ast.With, ast.AsyncWith)):  # R16
            return (sum(self.expr(i.context_expr, nest) for i in node.items)
                    + self.body(node.body, nest))
        if isinstance(node, ast.Match):  # R10: one increment for the whole match
            score = 1 + nest + self.expr(node.subject, nest)
            for case in node.cases:
                if case.guard is not None:
                    score += self.expr(case.guard, nest + 1, bools_only=True)
                score += self.body(case.body, nest + 1)
            return score
        if isinstance(node, FN):  # R12
            if id(node) in self.zero:
                base = 0
            elif id(node) in self.wrappers:
                base = nest
            else:
                base = nest + 1
            return self.body(node.body, base)
        if isinstance(node, ast.ClassDef):  # R14
            return self.body(node.body, nest)
        return sum(self.expr(c, nest) for c in ast.iter_child_nodes(node))

    def if_(self, node, nest, elif_):
        # R1 (if), R2 (elif: same column as the parent if), R3 and R3a (else)
        score = (1 if elif_ else 1 + nest) + self.expr(node.test, nest) \
            + self.body(node.body, nest + 1)
        orelse = node.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If) \
                and orelse[0].col_offset == node.col_offset:
            return score + self.if_(orelse[0], nest, elif_=True)
        return score + self.else_(orelse, nest)

    def expr(self, node, nest, bools_only=False):
        if isinstance(node, ast.BoolOp):  # R11
            return self.boolop(node, nest, bools_only)
        if isinstance(node, ast.IfExp) and not bools_only:  # R9
            return 1 + nest + sum(self.expr(c, nest + 1) for c in (node.test, node.body, node.orelse))
        if isinstance(node, ast.Lambda):  # R13
            return 0 if bools_only else self.expr(node.body, nest + 1)
        # R15, R16 and everything else: no increment, same nesting
        return sum(self.expr(c, nest, bools_only) for c in ast.iter_child_nodes(node))

    def boolop(self, node, nest, bools_only):
        # One increment per run of like operators, counted over the in-order flattening of the
        # whole BoolOp tree (a BoolOp nested directly in another one continues its sequence).
        ops = []
        score = 0

        def walk(b):
            nonlocal score
            for i, v in enumerate(b.values):
                if i:
                    ops.append(type(b.op))
                if isinstance(v, ast.BoolOp):
                    walk(v)
                else:
                    score += self.expr(v, nest, bools_only)

        walk(node)
        runs = sum(1 for i, op in enumerate(ops) if i == 0 or op is not ops[i - 1])
        return runs + score
