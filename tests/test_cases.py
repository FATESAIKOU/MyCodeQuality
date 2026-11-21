"""The 7 synthetic calibration cases (fake data); every case starts from the same base."""
import pytest


def body(tag, n, indent="    "):
    return "".join(f"{indent}value_{tag}_{i} = compute_{tag}({i})\n" for i in range(n))


def fn(name, tag, n, indent=""):
    return f"{indent}def {name}():\n" + body(tag, n, indent + "    ")


BLOCK_X = "".join(f"shared_line_{i} = shared_call({i})\n" for i in range(6))
BLOCK_M = "".join(f"twin_line_{i} = twin_call({i})\n" for i in range(6))
HELPER = "def helper(a, b):\n" + "".join(f"    a = a + b * {i}\n" for i in range(5)) + "    return a\n"
COPY = HELPER.replace("def helper", "def helper_again").replace(" * ", "*")  # same AST, other text
FILLER = "".join(f"filler_{i} = {i}\n" for i in range(8))


def classes(b_len):
    return "class A:\n" + fn("run", "a", 59, "    ") + "\nclass B:\n" + fn("run", "b", b_len, "    ")


BASE = {"src/m.py": classes(9), "src/x.py": BLOCK_X + HELPER, "src/g.py": fn("g", "g", 20),
        "src/y.py": FILLER, "src/w.py": BLOCK_X.replace("shared", "moved")}
cut = BLOCK_X.index("shared_line_3")
CASES = {
    "qualname": ({"src/m.py": classes(54)}, [], {"crossing_50": 1}),
    "pure-deletion": ({"src/g.py": fn("g", "g", 15)}, [], {"changed_fns": 1}),
    "non-adjacent-hunks": ({"src/y.py": BLOCK_X[:cut] + FILLER + BLOCK_X[cut:]}, [], {"dup_windows": 0}),
    "two-new-copies": ({"src/p.py": BLOCK_M, "src/q.py": BLOCK_M}, [], {"dup_windows": 0}),
    "real-copy": ({"src/r.py": "# copied\n" + BLOCK_X}, [], {"dup_windows": 1}),
    "ast-dup": ({"src/s.py": COPY}, [], {"ast_dup": 1, "dup_windows": 0}),
    "move": ({"src/z.py": BLOCK_X.replace("shared", "moved")}, ["src/w.py"], {"dup_windows": 0}),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_synthetic_case(name, make_repo, qm):
    files, delete, expected = CASES[name]
    repo = make_repo()
    base = repo.commit(BASE, "base")
    head = repo.commit(files, name, delete=delete)
    r = qm(repo.path, "--base", base, "--head", head)
    assert r.rc == 0, r.err
    counts = r.data()["counts"]
    assert {k: counts[k] for k in expected} == expected
    # the same numbers in merge-commit mode (first parent = base)
    r2 = qm(repo.path, "--merge", head)
    assert r2.data()["counts"] == counts


def test_same_name_in_other_class_is_not_confused(make_repo, qm):
    """A.run disappears while B.run grows past 50: pairing must use the qualified name."""
    repo = make_repo()
    base = repo.commit({"src/m.py": classes(9)}, "base")
    head = repo.commit({"src/m.py": "class B:\n" + fn("run", "b", 54, "    ")})
    d = qm(repo.path, "--base", base, "--head", head).data()
    assert d["counts"]["crossing_50"] == 1
    assert [e["function"] for e in d["events"] if e["kind"] == "crossing_50"] == ["B.run"]


def test_copy_inside_the_same_file_is_not_a_cross_file_duplicate(make_repo, qm):
    repo = make_repo()
    base = repo.commit({"src/x.py": BLOCK_X}, "base")
    head = repo.commit({"src/x.py": BLOCK_X + "gap = 0\n" + BLOCK_X})
    assert qm(repo.path, "--base", base, "--head", head).data()["counts"]["dup_windows"] == 0
