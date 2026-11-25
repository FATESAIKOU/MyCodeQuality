"""Module import graph for Python source: cycles, fan-in/out and package Ca/Ce/I (stdlib `ast` only).

Input: {repo path: ast.Module} for the .py files under the src prefix, and that prefix
(`metrics.prefix_of(--src)`). No git, no file access, no repo/cli: the caller parses the files.
Module names are relative to the import root (design 4.2, point 0):
- `<src>/__init__.py` exists and `--src` has a directory name: the name is prefixed with that
  name, e.g. `acme/widgets.py` -> `acme.widgets`.
- otherwise names start under `--src`; a `--src` with no directory name (`.`) gets no prefix.

Decisions (design 9, Q-M2): imports inside functions and under `TYPE_CHECKING` are edges like any
other import. Re-export edges are dropped: X -> P where P is an `__init__` module and X's name
starts with `P.`. The same filtered edge set feeds edges, cycles, fan and Ca/Ce.
"""

import ast
from collections import defaultdict

INIT = "__init__"


def analyze(trees, prefix):
    """-> {"arch": {...}, "findings": [...], "warnings": [...]} for the modules under prefix.

    trees: {repo path: ast.Module}; prefix: "" or "dir/" (from metrics.prefix_of).
    """
    dirname = prefix.rstrip("/").rsplit("/", 1)[-1] if prefix else ""
    has_init = bool(dirname) and (prefix + INIT + ".py") in trees
    mods, shadowed = _modules(trees, prefix, [dirname] if has_init else [])
    names = sorted(mods)
    edges, unres_a, unres_b = _edges(mods, trees, _suffixes(names), dirname)
    adj, fan_in = _adjacency(names, edges)

    comps = [c for c in _sccs(names, {n: sorted(adj[n]) for n in names}) if len(c) >= 2]
    findings = [{"kind": "import_cycle", "file": mods[n][0], "function": None, "value": len(c)}
                for c in comps for n in c]

    arch = {
        "modules": len(names),
        "edges": len(edges),
        "cycles": len(comps),
        "modules_in_cycles": sum(len(c) for c in comps),
        "max_fan_in": max((fan_in[n] for n in names), default=0),
        "max_fan_out": max((len(adj[n]) for n in names), default=0),
        "unresolved_internal_like": unres_a,
        "unresolved_self_prefix": unres_b,
        "shadowed_files": sorted(shadowed),
        "packages": _packages(mods, edges),
    }
    warnings = []
    if unres_a or unres_b:
        warnings.append("arch_import_root_suspect")
    if shadowed:
        warnings.append("arch_module_shadowed")
    return {"arch": arch, "findings": findings, "warnings": sorted(warnings)}


def _modules(trees, prefix, pre):
    """-> ({module name: (path, is_package)}, shadowed paths). `pre` is the dir-name prefix, if any.

    A name from both `x.py` and `x/__init__.py` goes to the package; the other file is shadowed.
    """
    mods, shadowed = {}, []
    for path in sorted(trees):
        rel = path[len(prefix):-len(".py")].split("/")
        is_pkg = rel[-1] == INIT
        if is_pkg:
            rel = rel[:-1]
        name = ".".join(pre + [p for p in rel if p])
        if not name:
            continue  # a root `__init__.py` with no directory name has no module name
        if name not in mods:
            mods[name] = (path, is_pkg)
        elif is_pkg and not mods[name][1]:
            shadowed.append(mods[name][0])
            mods[name] = (path, True)
        else:
            shadowed.append(path)
    return mods, shadowed


def _edges(mods, trees, suffixes, dirname):
    """-> (edges, unresolved_internal_like, unresolved_self_prefix), re-export edges dropped."""
    raw = set()  # (importer, target) before the re-export filter
    unres_a = unres_b = 0
    for m in sorted(mods):
        path, is_pkg = mods[m]
        for target, cands in _targets(m, is_pkg, trees[path], mods):
            if target is not None:
                raw.add((m, target))
            else:
                a, b = _signals(cands, mods, suffixes, dirname)
                unres_a, unres_b = unres_a + a, unres_b + b
    edges = {(m, t) for m, t in raw if m != t and not (mods[t][1] and m.startswith(t + "."))}
    return edges, unres_a, unres_b


def _targets(m, is_pkg, tree, mods):
    """(target, candidates) per import alias in module m.

    target is the module the alias resolves to, or None. candidates are the dotted names an
    unresolved alias could have meant; only absolute imports give candidates (signals are absolute-only).
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield _longest(alias.name, mods), [alias.name]
        elif isinstance(node, ast.ImportFrom):
            yield from _from_targets(m, is_pkg, node, mods)


def _from_targets(m, is_pkg, node, mods):
    """(target, candidates) per alias of one `from ... import ...` statement."""
    base = _from_base(m, is_pkg, node.level)
    if base is None:
        return  # relative import above the import root
    module = ".".join(base + (node.module.split(".") if node.module else []))
    for alias in node.names:
        sub = ".".join(p for p in (module, alias.name) if p) if alias.name != "*" else ""
        if sub and sub in mods:
            yield sub, []
            continue
        target = _longest(module, mods) if module else None
        if target is None and node.level == 0:
            yield None, [c for c in (sub, module) if c]
        else:
            yield target, []


def _adjacency(names, edges):
    """-> (adj: module -> set of imported modules, fan_in: module -> number of importing modules)."""
    adj = {n: set() for n in names}
    fan_in = defaultdict(int)
    for m, t in edges:
        adj[m].add(t)
        fan_in[t] += 1
    return adj, fan_in


def _packages(mods, edges):
    """Per package: modules, Ca (outside modules importing it), Ce (its modules importing outside), I = Ce/(Ca+Ce)."""
    pkg_of = {n: n if mods[n][1] else n.rpartition(".")[0] for n in mods}
    ca, ce = defaultdict(set), defaultdict(set)
    for m, t in edges:
        if pkg_of[m] != pkg_of[t]:
            ca[pkg_of[t]].add(m)
            ce[pkg_of[m]].add(m)
    members = defaultdict(int)
    for n in mods:
        members[pkg_of[n]] += 1
    packages = []
    for p in sorted(members):
        den = len(ca[p]) + len(ce[p])
        packages.append({
            "package": p, "modules": members[p], "ca": len(ca[p]), "ce": len(ce[p]),
            "instability": {"num": len(ce[p]), "den": den} if den else None,
        })
    return packages


def _from_base(m, is_pkg, level):
    """Package parts that a `from .x import` (level) starts from; None when it climbs above the import root."""
    if level == 0:
        return []
    parts = m.split(".") if is_pkg else m.split(".")[:-1]
    up = level - 1
    if up > len(parts):  # `...` from a depth-1 package climbs above the import root: no edge
        return None
    return parts[:len(parts) - up]


def _longest(dotted, mods):
    """The longest dotted prefix of `dotted` (itself first) that is a module, or None."""
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in mods:
            return cand
    return None


def _suffixes(names):
    """Every dotted suffix of every module name, e.g. `a.src.acme.y` gives `src.acme.y`, `acme.y`, `y`."""
    out = set()
    for n in names:
        parts = n.split(".")
        for i in range(1, len(parts)):
            out.add(".".join(parts[i:]))
    return out


def _signals(cands, mods, suffixes, dirname):
    """(a, b) for one unresolved import alias; each signal counts at most once per alias.

    (a) a candidate with two or more segments is the tail of some module name (root too shallow).
    (b) a candidate starts with the `--src` directory name and the rest resolves (namespace package).
    """
    a = any(len(c.split(".")) >= 2 and c in suffixes for c in cands)
    b = False
    if dirname:
        for c in cands:
            first, _, rest = c.partition(".")
            if first == dirname and rest and _longest(rest, mods) is not None:
                b = True
    return int(a), int(b)


def _sccs(nodes, adj):
    """Tarjan's strongly connected components (iterative, see _Tarjan)."""
    t = _Tarjan(adj)
    for root in nodes:
        if root not in t.index:
            t.visit(root)
    return t.out


class _Tarjan:
    """Iterative Tarjan's SCC: an explicit work stack, so a long import chain cannot hit the recursion limit."""

    def __init__(self, adj):
        self.adj = adj
        self.index, self.low, self.on, self.stack, self.out = {}, {}, set(), [], []

    def visit(self, root):
        self._open(root)
        work = [(root, iter(self.adj[root]))]
        while work:
            v, it = work[-1]
            w = self._next_unvisited(v, it)
            if w is not None:
                self._open(w)
                work.append((w, iter(self.adj[w])))
                continue
            work.pop()
            if work:
                u = work[-1][0]
                self.low[u] = min(self.low[u], self.low[v])
            if self.low[v] == self.index[v]:
                self.out.append(self._pop_component(v))

    def _next_unvisited(self, v, it):
        """Scan v's remaining edges; return the first unvisited target, or None when they run out."""
        for w in it:
            if w not in self.index:
                return w
            if w in self.on:
                self.low[v] = min(self.low[v], self.index[w])
        return None

    def _open(self, v):
        self.index[v] = self.low[v] = len(self.index)  # indexes are handed out in visit order
        self.stack.append(v)
        self.on.add(v)

    def _pop_component(self, v):
        comp = []
        while True:
            w = self.stack.pop()
            self.on.discard(w)
            comp.append(w)
            if w == v:
                break
        return sorted(comp)
