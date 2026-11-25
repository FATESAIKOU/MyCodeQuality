"""G-4 static metrics, code-change decision and test counts for one base..head diff.

Definitions follow the frozen prototype (design 5.5): functions are keyed by qualified
name; a changed function overlaps an added line (or its old twin overlaps a deleted line);
6-line duplicate windows are taken from one hunk only and must also exist in another
file at the base and still be there at the head.
"""

import ast
import re
from collections import defaultdict

from qmetrics.gitio import DIFF_OPTS, split_z

NEST = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match,
        ast.TryStar)
FN = (ast.FunctionDef, ast.AsyncFunctionDef)
WIN = 6
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def prefix_of(path):
    p = path.strip("/")
    return "" if p in ("", ".") else p + "/"


def lines_of(text):
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def parse(data):
    """-> (tree, ok). Missing file is (None, True); unparsable is (None, False)."""
    if data is None:
        return None, True
    try:
        return ast.parse(data), True
    except (SyntaxError, ValueError, RecursionError):
        return None, False


def depth(n, d=0):
    # an `elif` is an If inside the parent's orelse: same depth, not one deeper
    elifs = {id(n.orelse[0])} if isinstance(n, ast.If) and len(n.orelse) == 1 \
        and isinstance(n.orelse[0], ast.If) else set()
    best = d
    for ch in ast.iter_child_nodes(n):
        if isinstance(ch, (*FN, ast.ClassDef, ast.Lambda)):
            continue
        step = 1 if isinstance(ch, NEST) and id(ch) not in elifs else 0
        best = max(best, depth(ch, d + step))
    return best


def shape(fn):
    args = ast.arguments(**{f: getattr(fn.args, f) for f in fn.args._fields})
    return ast.dump(ast.Module(body=[args] + fn.body, type_ignores=[]), include_attributes=False)


def funcs(tree):
    """-> {(qualname, k): (start, end, depth, shape)}; k numbers same-name defs in one scope."""
    out = {}

    def walk(node, prefix):
        seen = defaultdict(int)
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, FN):
                q = prefix + ch.name
                key = (q, seen[q])
                seen[q] += 1
                big = ch.end_lineno - ch.lineno + 1 >= 5  # trivial bodies are not a copy signal
                out[key] = (ch.lineno, ch.end_lineno, depth(ch), shape(ch) if big else None)
                walk(ch, q + ".<locals>.")
            elif isinstance(ch, ast.ClassDef):
                walk(ch, prefix + ch.name + ".")
            else:
                walk(ch, prefix)  # defs under if/try at module or class level

    if tree is not None:
        walk(tree, "")
    return out


def windows(lines):
    ks = []
    for x in lines:
        s = x.strip()
        if s and not s.startswith("#") and len(s) >= 4:
            ks.append(s)
    return {tuple(ks[i:i + WIN]) for i in range(len(ks) - WIN + 1)}


def window_lines(lines):
    """-> {window: set of 1-based line numbers of its rows}; the keys are exactly `windows`."""
    ks = []
    for n, x in enumerate(lines, 1):
        s = x.strip()
        if s and not s.startswith("#") and len(s) >= 4:
            ks.append((n, s))
    out = {}
    for i in range(len(ks) - WIN + 1):
        rows = ks[i:i + WIN]
        out.setdefault(tuple(s for _, s in rows), set()).update(n for n, _ in rows)
    return out


def list_tree(git, rev, prefix):
    """path -> blob sha of the .py files under prefix at rev (symlinks and submodules skipped)."""
    args = ["ls-tree", "-r", "-z", rev]
    if prefix:
        args += ["--", prefix.rstrip("/")]
    out = {}
    for rec in split_z(git.out(*args)):
        meta, _, path = rec.partition("\t")
        mode, typ, sha = meta.split()
        if typ == "blob" and mode != "120000" and path.endswith(".py") and path.startswith(prefix):
            out[path] = sha
    return out


def hunks(git, base, head, path):
    diff = git.out("diff", *DIFF_OPTS, "-U0", base, head, "--", ":(literal)" + path)
    # an omitted count means 1; an explicit 0 means a pure add/delete side
    return [(int(a), int(b or 1) if b != "0" else 0, int(c), int(d or 1) if d != "0" else 0)
            for a, b, c, d in HUNK.findall(diff.decode("utf-8", "replace"))]


def count_tests(tree):
    """Number of functions named test_* (methods and nested defs included) in a module."""
    if tree is None:
        return 0
    return sum(1 for n in ast.walk(tree) if isinstance(n, FN) and n.name.startswith("test_"))


def analyze(git, base, head, src, tests):
    sp, tp = prefix_of(src), prefix_of(tests)
    names = sorted(split_z(git.out("diff", "--name-only", "-z", *DIFF_OPTS, base, head,
                                   "--", sp.rstrip("/") or ".", tp.rstrip("/") or ".")))
    src_changed = [f for f in names if f.startswith(sp) and f.endswith(".py")]
    tests_changed = [f for f in names if f.startswith(tp)]

    tb, th = list_tree(git, base, sp), list_tree(git, head, sp)
    tests_py = [f for f in tests_changed if f.endswith(".py")]
    ttb, tth = (list_tree(git, base, tp), list_tree(git, head, tp)) if tests_py else ({}, {})
    texts = git.read_blobs(list(tb.values()) + list(th.values())
                           + [ttb[f] for f in tests_py if f in ttb]
                           + [tth[f] for f in tests_py if f in tth])
    cache = {}

    def tree_of(sha):
        if sha not in cache:
            cache[sha] = parse(texts[sha])
        return cache[sha]

    def text_of(sha):
        return texts[sha].decode("utf-8", "replace") if sha else ""

    # existing code: windows / shapes present at the base and still in the same file at the head
    still_win = defaultdict(set)
    still_shape = set()
    for f, sb in tb.items():
        sa = th.get(f)
        if sa is None:
            continue
        for w in windows(lines_of(text_of(sb))) & windows(lines_of(text_of(sa))):
            still_win[w].add(f)
        before_shapes = {v[3] for v in funcs(tree_of(sb)[0]).values()}
        after_shapes = {v[3] for v in funcs(tree_of(sa)[0]).values()}
        still_shape |= (before_shapes & after_shapes) - {None}

    events, failures = [], []
    for f in sorted(set(tb) | set(th)):  # every parsed source blob, changed or reference
        for side, shas in (("base", tb), ("head", th)):
            if f in shas and not tree_of(shas[f])[1]:
                failures.append({"file": f, "side": side, "scope": "src"})
    changed_failed = {x["file"] for x in failures} & set(src_changed)
    code_change = False
    for f in src_changed:
        sb, sa = tb.get(f), th.get(f)
        pb, okb = tree_of(sb) if sb else (None, True)
        pa, oka = tree_of(sa) if sa else (None, True)
        if not (okb and oka):
            continue  # undetermined: no guessing, no events
        if (pb is None) != (pa is None) or (
                pb is not None and ast.dump(pb, include_attributes=False)
                != ast.dump(pa, include_attributes=False)):
            code_change = True
        if sa is None:  # whole file deleted: every function is a changed function
            for k, (s, e, _, _) in sorted(funcs(pb).items()):
                events.append({"file": f, "function": k[0], "kind": "changed_function",
                               "before": e - s + 1, "after": 0})
            continue
        after, before = text_of(sa), text_of(sb)
        n_after, n_before = len(lines_of(after)), len(lines_of(before))
        if n_after > 1000 and not n_before > 1000:
            events.append({"file": f, "function": None, "kind": "crossing_1000",
                           "before": n_before, "after": n_after})
        fa, fb = funcs(pa), funcs(pb)
        hs = hunks(git, base, head, f)
        added = {i for a, b, c, d in hs for i in range(c, c + d)}
        deleted = {i for a, b, c, d in hs for i in range(a, a + b)}
        touched_old = {k for k, (s, e, _, _) in fb.items() if deleted & set(range(s, e + 1))}
        for k, (s, e, d, sh) in sorted(fa.items()):
            if not (added & set(range(s, e + 1)) or k in touched_old):
                continue
            ln = e - s + 1
            pl, pd = (fb[k][1] - fb[k][0] + 1, fb[k][2]) if k in fb else (0, 0)
            ev = {"file": f, "function": k[0]}
            events.append({**ev, "kind": "changed_function", "before": pl, "after": ln})
            if ln > 50 and pl <= 50:
                events.append({**ev, "kind": "crossing_50", "before": pl, "after": ln})
            if d >= 4 and pd < 4:
                events.append({**ev, "kind": "crossing_depth4", "before": pd, "after": d})
            if pl > 50 and ln - pl >= 50:
                events.append({**ev, "kind": "grew_over50", "before": pl, "after": ln})
            if k not in fb and sh is not None and sh in still_shape:
                events.append({**ev, "kind": "ast_dup", "before": 0, "after": ln})
        for k, (s, e, _, _) in sorted(fb.items()):
            if k not in fa:  # function deleted from a file that stays
                events.append({"file": f, "function": k[0], "kind": "changed_function",
                               "before": e - s + 1, "after": 0})
        alines = lines_of(after)
        dup = 0
        for a, b, c, d in hs:
            block = alines[c - 1:c - 1 + d] if d else []
            dup += sum(1 for w in windows(block) if still_win.get(w, set()) - {f})
        if dup:
            events.append({"file": f, "function": None, "kind": "dup_windows",
                           "before": 0, "after": dup})

    net_tests = 0
    for f in tests_py:
        for side, shas in (("base", ttb), ("head", tth)):
            if f in shas and not tree_of(shas[f])[1]:
                failures.append({"file": f, "side": side, "scope": "tests"})
        net_tests += (count_tests(tree_of(tth[f])[0] if f in tth else None)
                      - count_tests(tree_of(ttb[f])[0] if f in ttb else None))
    events.sort(key=lambda e: (e["file"], e["kind"], e["function"] or "", e["before"], e["after"]))
    failures.sort(key=lambda x: (x["file"], x["side"], x["scope"]))
    src_unknown = any(x["scope"] == "src" for x in failures)
    tests_unknown = any(x["scope"] == "tests" for x in failures)
    if code_change is False and changed_failed:
        code_change = None

    def total(kind):
        return sum(e["after"] if kind == "dup_windows" else 1 for e in events if e["kind"] == kind)

    counts = {
        "changed_fns": sum(1 for e in events if e["kind"] == "changed_function"),
        "crossing_50": total("crossing_50"), "crossing_depth4": total("crossing_depth4"),
        "dup_windows": total("dup_windows"), "crossing_1000": total("crossing_1000"),
        "ast_dup": total("ast_dup"),
    }
    counts["smell_events"] = (counts["crossing_50"] + counts["crossing_depth4"]
                              + counts["dup_windows"] + counts["crossing_1000"] + counts["ast_dup"])
    grew = sum(1 for e in events if e["kind"] == "grew_over50")
    if src_unknown:  # undetermined: null, never a made-up 0
        counts = dict.fromkeys(counts)
        grew = None
    return {
        "applicable": bool(tb or th),
        "code_change": code_change,
        "counts": counts,
        "events": events,
        "grew_over50": grew,
        "net_new_tests": None if tests_unknown else net_tests,
        "parse_failures": failures,
        "tests_touched": bool(tests_changed),
    }
