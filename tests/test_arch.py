"""PR-M2 contracts (C-M6 to C-M9, C-M11): import graph, cycles, fan and package Ca/Ce/I.

Pure rules are checked by calling `qmetrics.imports.analyze` on parsed synthetic files; the
CLI-level contracts (null / not applicable, warnings wiring, determinism) run `qmetrics repo`
on a synthetic git repository. Everything is generated here; nothing is copied from elsewhere.
"""

import ast
import json
import subprocess
import sys

import pytest
from conftest import Result

from qmetrics import imports


def arch(files, prefix="src/"):
    """Run the import analysis on {path: source}; `prefix` is the --src prefix."""
    trees = {p: ast.parse(src) for p, src in files.items()}
    return imports.analyze(trees, prefix)


def run_repo(cwd, *args):
    proc = subprocess.run([sys.executable, "-m", "qmetrics", "repo", *args],
                          cwd=cwd, capture_output=True, text=True)
    return Result(proc)


def cycle_findings(out):
    return sorted((f["file"], f["value"]) for f in out["findings"] if f["kind"] == "import_cycle")


def no_floats(value):
    if isinstance(value, float):
        return False
    if isinstance(value, dict):
        return all(no_floats(v) for v in value.values())
    if isinstance(value, list):
        return all(no_floats(v) for v in value)
    return True


# ---- C-M6: resolution -------------------------------------------------------------------

def test_C_M6_forms_import_from_relative_and_self_and_stdlib():
    out = arch({
        "src/acme/__init__.py": "",
        "src/acme/app.py": (
            "import acme.widgets.io\n"        # longest prefix -> acme.widgets.io
            "from acme.widgets import io\n"   # a module name -> the module (same edge again)
            "from acme.widgets import Thing\n"  # a name -> acme.widgets (the package)
            "from . import x\n"               # relative -> acme.x
            "from ..y import z\n"             # two levels up from acme.app -> root module y
            "import os\n"                     # stdlib: not an edge
            "import acme.app\n"               # self: not an edge
        ),
        "src/acme/widgets/__init__.py": "",
        "src/acme/widgets/io.py": "",
        "src/acme/x.py": "",
        "src/y.py": "",
    })
    a = out["arch"]
    assert a["modules"] == 6
    assert a["edges"] == 4  # io, acme.widgets, acme.x, y
    assert a["max_fan_out"] == 4
    assert a["unresolved_internal_like"] == 0
    assert a["unresolved_self_prefix"] == 0
    assert out["warnings"] == []


def test_C_M6_reexport_from_inside_the_package_is_not_an_edge():
    # re-export rule (Q-M2 third item, option B): a child that imports its own __init__ is dropped
    out = arch({
        "src/acme/__init__.py": "from acme.core import run\n",
        "src/acme/core.py": "from acme import VERSION\n",
        "src/acme/widgets/cache.py": "from acme.widgets import Thing\n",
        "src/acme/widgets/__init__.py": "",
    })
    assert out["arch"]["edges"] == 1  # acme -> acme.core only
    assert out["arch"]["cycles"] == 0


def test_C_M6_relative_import_above_the_root_is_not_an_edge():
    # acme.app is in depth-1 package acme: `...q` climbs above the import root, so it is dropped,
    # while `..y` (one level up) lands on the root-level module y (known loose spot, see README)
    out = arch({
        "src/acme/__init__.py": "",
        "src/acme/app.py": "from ...q import z\nfrom ..y import z\n",
        "src/q.py": "",
        "src/y.py": "",
    })
    assert out["arch"]["edges"] == 1  # acme.app -> y only; q is not reached
    assert out["arch"]["max_fan_out"] == 1


def test_C_M6_flat_top_level_modules_under_a_root_package_keep_their_relative_imports():
    # --src . with a root __init__.py: a.py is a flat top-level module, so `.b` and `.` are the root
    out = arch({
        "__init__.py": "",
        "a.py": "from .b import f\nfrom . import c\nfrom .. import q\n",  # `..` climbs above the root
        "b.py": "",
        "c.py": "from .a import x\n",
        "q.py": "",
    }, prefix="")
    assert out["arch"]["modules"] == 4
    assert out["arch"]["edges"] == 3  # a -> b, a -> c, c -> a (`from .. import q` is not an edge)
    assert out["arch"]["cycles"] == 1  # a and c
    assert out["arch"]["modules_in_cycles"] == 2


def test_C_M6_depth_one_package_under_a_root_package_reaches_the_root_module():
    # --src . with a root __init__.py: `from .. import b` in sub/s.py climbs one level to the root
    out = arch({
        "__init__.py": "",
        "sub/__init__.py": "",
        "sub/s.py": "from .. import b\n",
        "b.py": "import sub.s\n",
    }, prefix="")
    assert out["arch"]["modules"] == 3
    assert out["arch"]["edges"] == 2  # sub.s -> b, b -> sub.s
    assert out["arch"]["cycles"] == 1
    assert out["arch"]["modules_in_cycles"] == 2


def test_C_M6_name_that_only_starts_with_a_package_name_is_not_under_it():
    # acme_extra is a sibling module, not a child of package acme: its import of acme is an edge
    out = arch({
        "src/acme/__init__.py": "",
        "src/acme_extra.py": "import acme\n",
    })
    assert out["arch"]["edges"] == 1


def test_C_M6_type_checking_and_else_and_negated_are_all_edges():
    # Q-M2 second item (option A): TYPE_CHECKING is counted; every shape here is a normal import
    out = arch({
        "src/a.py": (
            "import typing\n"
            "if typing.TYPE_CHECKING:\n    import b\n"
            "else:\n    import c\n"
        ),
        "src/d.py": "if not TYPE_CHECKING:\n    import b\n",
        "src/b.py": "",
        "src/c.py": "",
    })
    a = out["arch"]
    assert a["edges"] == 3  # a->b, a->c, d->b
    assert a["max_fan_in"] == 2  # b
    assert a["unresolved_internal_like"] == 0


def test_C_M6_import_root_with_package_init_gets_the_dir_prefix():
    # --src mypkg with mypkg/__init__.py: names are mypkg.db etc., so `import mypkg.db` resolves
    out = arch({
        "mypkg/__init__.py": "",
        "mypkg/db.py": "",
        "mypkg/api.py": "import mypkg.db\nfrom . import db\n",
    }, prefix="mypkg/")
    assert out["arch"]["edges"] == 1  # both forms land on mypkg.db: one pair
    assert out["arch"]["unresolved_internal_like"] == 0
    assert out["warnings"] == []


def test_C_M6_package_init_relative_import_resolves_to_child():
    out = arch({
        "src/acme/__init__.py": "",
        "src/acme/widgets/__init__.py": "from . import cache\n",
        "src/acme/widgets/cache.py": "",
    })
    assert out["arch"]["edges"] == 1
    assert out["arch"]["packages"][1] == {
        "package": "acme.widgets", "modules": 2, "ca": 0, "ce": 0, "instability": None}


def test_C_M6_import_root_too_shallow_signal_a_and_the_right_root():
    files = {
        "services/a/src/acme/x.py": "import acme.y\n",
        "services/a/src/acme/y.py": "",
    }
    wrong = arch(files, prefix="services/")
    assert wrong["arch"]["edges"] == 0
    assert wrong["arch"]["unresolved_internal_like"] == 1
    assert wrong["arch"]["unresolved_self_prefix"] == 0
    assert wrong["warnings"] == ["arch_import_root_suspect"]

    right = arch(files, prefix="services/a/src/")
    assert right["arch"]["edges"] == 1
    assert right["arch"]["unresolved_internal_like"] == 0
    assert right["warnings"] == []


def test_C_M6_from_import_of_a_name_counts_one_signal_per_alias():
    files = {
        "services/a/src/acme/x.py": "from acme import y, z\n",
        "services/a/src/acme/y.py": "",
        "services/a/src/acme/z.py": "",
    }
    out = arch(files, prefix="services/")
    assert out["arch"]["unresolved_internal_like"] == 2  # per alias, not per statement
    assert out["arch"]["edges"] == 0


def test_C_M6_src_dot_gets_no_prefix_and_no_namespace_signal():
    out = arch({
        "__init__.py": "",
        "a.py": "import b\n",
        "b.py": "",
    }, prefix="")
    assert out["arch"]["modules"] == 2  # the root __init__.py has no module name
    assert out["arch"]["edges"] == 1
    assert out["arch"]["unresolved_self_prefix"] == 0
    assert out["warnings"] == []


def test_C_M6_flat_import_under_package_init_is_a_silent_zero():
    # known blind spot, recorded on purpose: scripts/ is a sys.path root with flat imports
    out = arch({
        "scripts/__init__.py": "",
        "scripts/a.py": "import util\n",
        "scripts/util.py": "",
    }, prefix="scripts/")
    assert out["arch"]["edges"] == 0
    assert out["arch"]["unresolved_internal_like"] == 0
    assert out["arch"]["unresolved_self_prefix"] == 0
    assert out["warnings"] == []


def test_C_M6_correct_root_with_stdlib_name_clashes_has_no_signal():  # N1
    out = arch({
        "src/acme/__init__.py": "",
        "src/acme/logging.py": "import logging\nimport warnings\nfrom logging import handlers\n",
        "src/acme/warnings.py": "import warnings\n",
    })
    assert out["arch"]["unresolved_internal_like"] == 0
    assert out["arch"]["unresolved_self_prefix"] == 0
    assert out["warnings"] == []


def test_C_M6_namespace_package_own_name_is_signal_b():
    out = arch({
        "pkgnamespace/cli.py": "from pkgnamespace.rules import check\n",
        "pkgnamespace/rules.py": "def check():\n    pass\n",
    }, prefix="pkgnamespace/")
    assert out["arch"]["edges"] == 0
    assert out["arch"]["unresolved_self_prefix"] == 1
    assert out["arch"]["unresolved_internal_like"] == 0
    assert out["warnings"] == ["arch_import_root_suspect"]


def test_C_M6_signal_b_needs_the_rest_after_the_dir_name_to_resolve():
    # `src.zzz` starts with the --src name, but `zzz` is not a module: no signal
    out = arch({
        "src/acme/__init__.py": "",
        "src/acme/x.py": "import src.zzz\n",
    })
    assert out["arch"]["unresolved_self_prefix"] == 0
    assert out["warnings"] == []


def test_C_M6_relative_import_never_counts_a_signal():
    # `from .zzz import q` is unresolved and its dotted form would match signal (b) if it counted;
    # only absolute imports carry signals
    out = arch({
        "nsdemo/zzz.py": "",
        "nsdemo/nsdemo/app.py": "from .zzz import q\n",
    }, prefix="nsdemo/")
    assert out["arch"]["edges"] == 0
    assert out["arch"]["unresolved_self_prefix"] == 0
    assert out["arch"]["unresolved_internal_like"] == 0
    assert out["warnings"] == []


def test_C_M6_two_plain_files_with_one_name_keep_the_first_and_report_the_second():
    # `a.b.py` and `a/b.py` both name a.b; neither is a package, so the later one is shadowed.
    # Which one survives is not asserted: it is the sorted-first file, not an import-based choice
    out = arch({"src/a.b.py": "", "src/a/b.py": ""})
    assert out["arch"]["modules"] == 1
    assert out["arch"]["shadowed_files"] == ["src/a/b.py"]
    assert out["warnings"] == ["arch_module_shadowed"]


def test_C_M6_name_clash_package_wins_and_is_reported_in_any_order():
    base = {
        "src/a.py": "x = 1\n",
        "src/a/__init__.py": "",
        "src/b.py": "import a\n",
    }
    one = arch(base)
    two = arch(dict(reversed(list(base.items()))))
    assert one == two  # input order does not matter
    assert one["arch"]["shadowed_files"] == ["src/a.py"]
    assert one["arch"]["modules"] == 2
    assert one["arch"]["edges"] == 1  # b -> a (the package)
    assert one["warnings"] == ["arch_module_shadowed"]


# ---- C-M7: cycles ----------------------------------------------------------------------

def test_C_M7_two_cycle_with_a_bystander():
    out = arch({"src/a.py": "import b\n", "src/b.py": "import a\n", "src/c.py": "import a\n"})
    assert out["arch"]["cycles"] == 1
    assert out["arch"]["modules_in_cycles"] == 2
    assert cycle_findings(out) == [("src/a.py", 2), ("src/b.py", 2)]  # c is not in it


def test_C_M7_cross_edge_to_a_finished_component_is_not_a_cycle():
    # a -> b, a -> c, c -> b: b is already finished when c looks at it (a cross edge, not a back edge)
    out = arch({"src/a.py": "import b\nimport c\n", "src/b.py": "", "src/c.py": "import b\n"})
    assert out["arch"]["cycles"] == 0
    assert out["arch"]["modules_in_cycles"] == 0
    assert out["findings"] == []


def test_C_M7_three_cycle_value_is_component_size():
    out = arch({"src/a.py": "import b\n", "src/b.py": "import c\n", "src/c.py": "import a\n"})
    assert out["arch"]["cycles"] == 1
    assert cycle_findings(out) == [("src/a.py", 3), ("src/b.py", 3), ("src/c.py", 3)]


def test_C_M7_reexport_cycle_is_dropped():
    out = arch({
        "src/acme/__init__.py": "from acme.core import run\n",
        "src/acme/core.py": "from acme import VERSION\n",
        "src/acme/util.py": "from acme import VERSION\n",
    })
    assert out["arch"]["cycles"] == 0
    assert out["findings"] == []


def test_C_M7_file_order_does_not_change_the_cycle_output():
    files = {
        "src/acme/__init__.py": "from acme.core import run\n",
        "src/acme/core.py": "from acme import VERSION\n",
        "src/a.py": "import b\n",
        "src/b.py": "import c\n",
        "src/c.py": "import a\n",
        "src/d.py": "import a\n",
    }
    forward = arch(files)
    backward = arch(dict(reversed(list(files.items()))))
    assert json.dumps(forward, sort_keys=True) == json.dumps(backward, sort_keys=True)
    assert forward["arch"]["cycles"] == 1


def test_C_M7_function_level_import_counts_as_a_dependency():
    out = arch({
        "src/a.py": "import b\n",
        "src/b.py": "def f():\n    import a\n",
    })
    assert out["arch"]["cycles"] == 1


def test_C_M7_deep_chain_does_not_hit_the_recursion_limit():  # C-M9 scale, part of the iterative Tarjan
    n = 1500
    files = {f"src/m{i}.py": f"import m{(i + 1) % n}\n" for i in range(n)}
    out = arch(files)
    assert out["arch"]["cycles"] == 1
    assert out["arch"]["modules_in_cycles"] == n
    assert len(out["findings"]) == n
    assert all(f["value"] == n for f in out["findings"])


# ---- C-M8: fan and Ca/Ce/I -----------------------------------------------------------------

M8 = {
    "src/acme/__init__.py": "",
    "src/acme/main.py": "from acme.widgets import cache\n",
    "src/acme/widgets/__init__.py": "from . import cache\n",
    "src/acme/widgets/cache.py": "from acme.widgets import io\n",
    "src/acme/widgets/io.py": "",
    "src/tool.py": "import acme\n",
}


def test_C_M8_fan_and_package_numbers():
    a = arch(M8)["arch"]
    assert a["modules"] == 6
    assert a["edges"] == 4
    assert a["max_fan_in"] == 2  # acme.widgets.cache
    assert a["max_fan_out"] == 1
    assert a["packages"] == [
        {"package": "", "modules": 1, "ca": 0, "ce": 1, "instability": {"num": 1, "den": 1}},
        {"package": "acme", "modules": 2, "ca": 1, "ce": 1, "instability": {"num": 1, "den": 2}},
        {"package": "acme.widgets", "modules": 3, "ca": 1, "ce": 0, "instability": {"num": 0, "den": 1}},
    ]
    assert no_floats(a)


def test_C_M8_package_with_no_edges_has_null_instability():
    a = arch({"src/iso/__init__.py": "", "src/iso/x.py": ""})["arch"]
    assert a["packages"] == [
        {"package": "iso", "modules": 2, "ca": 0, "ce": 0, "instability": None}]


def test_C_M8_ca_counts_importing_modules_not_edges():
    # x imports p.a and p.b: two edges into package p, but one importing module
    a = arch({
        "src/p/__init__.py": "",
        "src/p/a.py": "",
        "src/p/b.py": "",
        "src/x.py": "from p.a import f\nfrom p.b import g\n",
    })["arch"]
    assert a["edges"] == 2
    p = next(row for row in a["packages"] if row["package"] == "p")
    assert p["ca"] == 1
    assert p["ce"] == 0


# ---- C-M9: null and not applicable, through the CLI --------------------------------------

def test_C_M9_unparsable_src_gives_null_arch(make_repo):
    r = make_repo()
    r.commit({"src/a.py": "import b\n", "src/b.py": "def f(:\n"})
    res = run_repo(r.path, "--json")
    assert res.rc == 0, res.err
    d = res.data()
    assert d["arch"] is None
    assert d["findings"] is None
    assert d["warnings"] == []


def test_C_M9_not_applicable_gives_zero_arch(make_repo):
    r = make_repo()
    r.commit({"src/README.txt": "x\n", "tests/test_x.py": "def test_x():\n    pass\n"})
    d = run_repo(r.path, "--json").data()
    assert d["applicable"] is False
    assert d["arch"] == {
        "modules": 0, "edges": 0, "cycles": 0, "modules_in_cycles": 0,
        "max_fan_in": 0, "max_fan_out": 0, "unresolved_internal_like": 0,
        "unresolved_self_prefix": 0, "shadowed_files": [], "packages": [],
    }


def test_C_M9_thousand_module_cycle_through_the_cli(make_repo):
    n = 1500
    r = make_repo()
    r.commit({f"src/m{i}.py": f"import m{(i + 1) % n}\n" for i in range(n)})
    res = run_repo(r.path, "--json")
    assert res.rc == 0, res.err
    d = res.data()
    assert d["arch"]["cycles"] == 1
    assert d["arch"]["modules_in_cycles"] == n
    assert len([f for f in d["findings"] if f["kind"] == "import_cycle"]) == n
    assert all(f["value"] == n for f in d["findings"] if f["kind"] == "import_cycle")


def test_C_M9_import_cycle_findings_are_sorted_among_other_kinds(make_repo):
    # a 56-line function (long_function) in a cycle: import_cycle sorts before long_function
    r = make_repo()
    body = "".join(f"    x{i} = {i}\n" for i in range(55))
    r.commit({"src/a.py": "import b\ndef f():\n" + body, "src/b.py": "import a\n"})
    res = run_repo(r.path, "--json")
    assert res.rc == 0, res.err
    d = res.data()
    assert [(f["kind"], f["file"], f["function"]) for f in d["findings"]] == [
        ("import_cycle", "src/a.py", None),
        ("import_cycle", "src/b.py", None),
        ("long_function", "src/a.py", "f"),
    ]
    assert d["arch"]["cycles"] == 1


# ---- wiring of warnings and the old fields (C-M5, C-M12 for the repo command) ------------

def test_C_M6_warnings_merge_preflight_and_arch_sorted(make_repo, tmp_path):
    r = make_repo()
    r.commit({"services/a/src/acme/x.py": "import acme.y\n",
              "services/a/src/acme/y.py": ""})
    empty = tmp_path / "empty-objects"
    empty.mkdir()
    (r.gitdir() / "objects" / "info").mkdir(exist_ok=True)
    (r.gitdir() / "objects" / "info" / "alternates").write_text(f"{empty}\n")
    d = run_repo(r.path, "--src", "services", "--json").data()
    assert d["warnings"] == ["alternates_present", "arch_import_root_suspect"]


def test_C_M5_old_fields_are_unchanged_by_arch(make_repo):
    # the same synthetic source, with and without an import cycle, has the same counts and ratios
    r = make_repo()
    r.commit({"src/a.py": "def f():\n    return 1\n", "src/b.py": "def g():\n    return 2\n"})
    plain = run_repo(r.path, "--json").data()
    r.commit({"src/a.py": "import b\ndef f():\n    return 1\n", "src/b.py": "import a\ndef g():\n    return 2\n"})
    cyc = run_repo(r.path, "--json").data()
    assert cyc["arch"]["cycles"] == 1
    assert cyc["counts"] == plain["counts"]
    # ratios.dup_lines has den = totals.lines (design §7.1), so the two import lines move it;
    # every other ratio must still match exactly
    assert {k: v for k, v in cyc["ratios"].items() if k != "dup_lines"} == \
        {k: v for k, v in plain["ratios"].items() if k != "dup_lines"}
    assert cyc["ratios"]["dup_lines"]["den"] == cyc["totals"]["lines"]
    assert plain["ratios"]["dup_lines"]["den"] == plain["totals"]["lines"]
    # the two import lines are real source lines, so totals.lines is the only total that moves
    assert {k: v for k, v in cyc["totals"].items() if k != "lines"} == \
        {k: v for k, v in plain["totals"].items() if k != "lines"}


# ---- C-M11: determinism (the M2 part) ------------------------------------------------------

STUB = """
import socket, sys, time
def boom(*args, **kwargs):
    raise RuntimeError("network or clock used")
time.time = boom
socket.socket = boom
from qmetrics.cli import main
sys.exit(main(sys.argv[1:]))
"""


def test_C_M11_same_commit_same_bytes_even_with_clock_and_network_stubbed(make_repo):
    r = make_repo()
    r.commit({"src/a.py": "import b\n", "src/b.py": "import a\n", "src/acme/__init__.py": "",
              "src/acme/x.py": "from acme import y\n", "src/acme/y.py": ""})
    first = run_repo(r.path, "--json")
    second = run_repo(r.path, "--json")
    assert first.rc == 0 and second.rc == 0
    assert first.out == second.out
    stubbed = subprocess.run([sys.executable, "-c", STUB, "repo", "--repo", str(r.path), "--json"],
                             cwd=r.path, capture_output=True, text=True)
    assert stubbed.returncode == 0, stubbed.stderr
    assert json.loads(stubbed.stdout)["arch"] == first.data()["arch"]
