"""Cognitive complexity per scoring unit, for Python source (stdlib `ast` only).

A scoring unit is a function that is not inside another function (module-level functions and
methods). Functions nested in a unit, lambdas and classes inside it are scored into the unit.
Keys are the `metrics.funcs` keys, restricted to units. No threshold here (see repo.py).

Rule table. The R numbers in the comments below refer to these rows. "+1" is one increment,
"+nest" adds the current nesting level, and "nest" is the nesting level inside the construct.

    R1   if: +1 +nest; its body is nested
    R2   elif: +1, no nest term; the test stays at the parent's nesting
    R3   else: +1, no nest term; its body is nested
    R3a  an else holding one if at a deeper column is not an elif: the else is +1 and the if is nested
    R4   for, async for, while: +1 +nest; body nested
    R5   else of a loop: +1, no nest term
    R6   try body and finally: no increment, no nest
    R7   each except handler: +1 +nest; the handler's type is scored, its body is nested
    R8   else of try: +1, no nest term
    R9   ternary (x if c else y): +1 +nest; its parts are nested
    R10  match: +1 +nest once for the whole match; case guards are scored; case bodies are nested
    R11  boolean operators: +1 per run of like operators (`and` / `or`), over the whole BoolOp tree
    R12  nested def: nested unless its enclosing function is a wrapper (only defs and `return <name>`)
    R13  lambda: no increment itself; its body is nested
    R14  def directly in a class body: nesting restarts at 0
    R15  comprehensions: no increment, no nest
    R16  with, async with, break, continue, return, await, yield, walrus, assert, raise: no increment
    R17  recursion: deliberately not counted
    R18  decorators, default values and annotations: deliberately not counted
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
    # same walk and the same keys as metrics.funcs (one `seen` per walk, keyed by qualname), but a
    # function's body is not entered: its nested defs belong to it
    out = {}
    seen = defaultdict(int)
    todo = [(ast.iter_child_nodes(tree), "")]
    while todo:
        it, prefix = todo[-1]
        ch = next(it, None)
        if ch is None:
            todo.pop()
        elif isinstance(ch, FN):
            q = prefix + ch.name
            out[(q, seen[q])] = ch
            seen[q] += 1
        elif isinstance(ch, ast.ClassDef):
            todo.append((ast.iter_child_nodes(ch), prefix + ch.name + "."))
        else:
            todo.append((ast.iter_child_nodes(ch), prefix))
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
        # explicit stack, not recursion: a long `a + a + …` or method chain must not hit the
        # recursion limit (the rules are the same as the recursive form)
        score = 0
        todo = [(node, nest, bools_only)]
        while todo:
            n, k, bo = todo.pop()
            if isinstance(n, ast.BoolOp):  # R11
                runs, operands = self.boolop(n)
                score += runs
                todo.extend((v, k, bo) for v in operands)
            elif isinstance(n, ast.IfExp) and not bo:  # R9
                score += 1 + k
                todo.extend((c, k + 1, False) for c in (n.test, n.body, n.orelse))
            elif isinstance(n, ast.Lambda):  # R13
                if not bo:
                    todo.append((n.body, k + 1, False))
            else:  # R15, R16 and everything else: no increment, same nesting
                todo.extend((c, k, bo) for c in ast.iter_child_nodes(n))
        return score

    def boolop(self, node):
        # One increment per run of like operators, counted over the in-order flattening of the
        # whole BoolOp tree (a BoolOp nested directly in another one continues its sequence).
        # -> (runs, operands); the operands (non-BoolOp values) are scored by the caller
        ops = []
        operands = []
        todo = [node]  # AST nodes, or an operator class as a marker between two values
        while todo:
            x = todo.pop()
            if isinstance(x, type):
                ops.append(x)
            elif isinstance(x, ast.BoolOp):
                for i in reversed(range(len(x.values))):
                    todo.append(x.values[i])
                    if i:
                        todo.append(type(x.op))
            else:
                operands.append(x)
        runs = sum(1 for i, op in enumerate(ops) if i == 0 or op is not ops[i - 1])
        return runs, operands
