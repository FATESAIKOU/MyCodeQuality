"""Repository-wide static code quality metrics at a single commit."""

from collections import defaultdict
from qmetrics import metrics


def analyze(git, rev, src, tests):
    sp = metrics.prefix_of(src)
    tp = metrics.prefix_of(tests)

    src_blobs = metrics.list_tree(git, rev, sp)
    tests_blobs = metrics.list_tree(git, rev, tp)

    all_shas = list(src_blobs.values()) + list(tests_blobs.values())
    texts = git.read_blobs(all_shas)

    cache = {}

    def text_of(sha):
        return texts[sha].decode("utf-8", "replace") if sha else ""

    def tree_of(sha):
        if sha not in cache:
            cache[sha] = metrics.parse(texts[sha])
        return cache[sha]

    src_failures = []
    for f in sorted(src_blobs):
        _, ok = tree_of(src_blobs[f])
        if not ok:
            src_failures.append({"file": f, "scope": "src"})

    tests_failures = []
    for f in sorted(tests_blobs):
        _, ok = tree_of(tests_blobs[f])
        if not ok:
            tests_failures.append({"file": f, "scope": "tests"})

    parse_failures = sorted(src_failures + tests_failures, key=lambda x: (x["file"], x["scope"]))

    applicable = bool(src_blobs)

    files_count = len(src_blobs)
    lines_count = sum(len(metrics.lines_of(text_of(src_blobs[f]))) for f in src_blobs)

    if tests_failures:
        tests_count = None
    else:
        tests_count = sum(metrics.count_tests(tree_of(tests_blobs[f])[0]) for f in tests_blobs)

    if src_failures:
        totals = {
            "files": files_count,
            "lines": lines_count,
            "functions": None,
            "tests": tests_count,
        }
        return {
            "applicable": applicable,
            "totals": totals,
            "counts": None,
            "ratios": None,
            "findings": None,
            "parse_failures": parse_failures,
        }

    if not applicable:
        totals = {
            "files": 0,
            "lines": 0,
            "functions": 0,
            "tests": tests_count,
        }
        counts = {
            "long_files": 0,
            "long_functions": 0,
            "deep_functions": 0,
            "ast_dup_functions": 0,
            "dup_windows": 0,
            "smell_events": 0,
        }
        ratios = {
            "long_files": None,
            "long_functions": None,
            "deep_functions": None,
            "ast_dup_functions": None,
        }
        return {
            "applicable": False,
            "totals": totals,
            "counts": counts,
            "ratios": ratios,
            "findings": [],
            "parse_failures": parse_failures,
        }

    findings = []
    long_files = 0
    file_windows = {}
    window_files = defaultdict(set)
    shape_groups = defaultdict(list)
    all_funcs = []

    for f in sorted(src_blobs):
        text = text_of(src_blobs[f])
        lines = metrics.lines_of(text)
        n_lines = len(lines)
        if n_lines > 1000:
            long_files += 1
            findings.append({"kind": "long_file", "file": f, "function": None, "value": n_lines})

        wins = metrics.windows(lines)
        file_windows[f] = wins
        for w in wins:
            window_files[w].add(f)

        tree, _ = tree_of(src_blobs[f])
        fn_dict = metrics.funcs(tree)
        for (qname, k), (start, end, d, sh) in sorted(fn_dict.items()):
            fn_len = end - start + 1
            all_funcs.append((f, qname, fn_len, d, sh))
            if fn_len > 50:
                findings.append({"kind": "long_function", "file": f, "function": qname, "value": fn_len})
            if d >= 4:
                findings.append({"kind": "deep_function", "file": f, "function": qname, "value": d})
            if sh is not None:
                shape_groups[sh].append((f, qname))

    long_functions = sum(1 for _, _, fn_len, _, _ in all_funcs if fn_len > 50)
    deep_functions = sum(1 for _, _, _, d, _ in all_funcs if d >= 4)

    # ast_dup_functions
    ast_dup_functions = 0
    for sh, group in shape_groups.items():
        if len(group) >= 2:
            ast_dup_functions += len(group) - 1
            for f, qname in group:
                findings.append({
                    "kind": "ast_dup_function",
                    "file": f,
                    "function": qname,
                    "value": len(group),
                })

    # dup_windows
    counted_windows = {w for w, files in window_files.items() if len(files) >= 2}
    dup_windows = len(counted_windows)
    for f in sorted(src_blobs):
        shared = file_windows[f] & counted_windows
        if shared:
            findings.append({
                "kind": "dup_windows",
                "file": f,
                "function": None,
                "value": len(shared),
            })

    smell_events = long_files + long_functions + deep_functions + ast_dup_functions + dup_windows

    counts = {
        "long_files": long_files,
        "long_functions": long_functions,
        "deep_functions": deep_functions,
        "ast_dup_functions": ast_dup_functions,
        "dup_windows": dup_windows,
        "smell_events": smell_events,
    }

    totals = {
        "files": files_count,
        "lines": lines_count,
        "functions": len(all_funcs),
        "tests": tests_count,
    }

    ratios = {
        "long_files": {"num": long_files, "den": totals["files"]} if totals["files"] > 0 else None,
        "long_functions": {"num": long_functions, "den": totals["functions"]} if totals["functions"] > 0 else None,
        "deep_functions": {"num": deep_functions, "den": totals["functions"]} if totals["functions"] > 0 else None,
        "ast_dup_functions": {"num": ast_dup_functions, "den": totals["functions"]} if totals["functions"] > 0 else None,
    }

    findings.sort(key=lambda x: (x["kind"], x["file"], x["function"] or "", x["value"]))

    return {
        "applicable": True,
        "totals": totals,
        "counts": counts,
        "ratios": ratios,
        "findings": findings,
        "parse_failures": parse_failures,
    }
