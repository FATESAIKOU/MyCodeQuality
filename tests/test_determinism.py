"""13.3 acceptance: same inputs -> same bytes, whatever the local git setup says."""
import pytest

M0 = """a = 1


def g():
    return 1


b = 1


def h():
    x = 1
    y = 2
    return x + y
"""
M1 = M0.replace("a = 1", "a = 2").replace("b = 1", "b = 2").replace("y = 2", "y = 3")


@pytest.fixture
def hist(make_repo):
    """base -> head edits two spots 7 lines apart plus a function g that sits between them."""
    repo = make_repo()
    repo.commit({"src/m.py": M0, "tests/test_m.py": "def test_a():\n    pass\n"}, "base")
    repo.commit({"src/m.py": M1}, "mid")
    repo.commit({"src/m.py": M1.replace("x + y", "y + x")}, "head")
    repo.base = repo.git("rev-parse", "HEAD~2")
    repo.mid = repo.git("rev-parse", "HEAD~1")
    repo.head = repo.git("rev-parse", "HEAD")
    return repo


def runs(qm, repo, cwd=None, env=None):
    """The three ways to name the commits."""
    cwd = cwd or repo.path
    return [qm(cwd, "--base", repo.base, "--head", repo.head, env=env),
            qm(cwd, "--merge", repo.head, env=env),
            qm(cwd, "--pr-base", repo.base, "--pr-head", repo.head, env=env)]


@pytest.fixture
def clean(hist, qm):
    out = runs(qm, hist)
    assert all(r.rc == 0 for r in out), [r.err for r in out]
    return out


def same_as_clean(results, clean):
    for r, c in zip(results, clean):
        assert r.rc == 0, r.err
        assert r.stable() == c.stable()
    return results


def test_fixture_is_discriminating(clean):
    # only h changes; g sits between two edits, so a merged hunk (interHunkContext) would add it
    d = clean[0].data()
    assert d["counts"]["changed_fns"] == 1
    assert [e["function"] for e in d["events"]] == ["h"]


def test_run_twice_same_bytes(hist, qm, clean):
    again = runs(qm, hist)
    for a, b in zip(clean, again):
        assert a.out == b.out
    assert clean[0].out.endswith("\n")
    for key in ("schema_version", "tool_version", "python_version", "git_version", "base", "head"):
        assert key in clean[0].data()


def test_output_is_sorted_and_has_no_timestamp(clean):
    d = clean[0].data()
    assert list(d) == sorted(d)
    ev = d["events"]
    assert ev == sorted(ev, key=lambda e: (e["file"], e["kind"], e["function"] or "", e["before"], e["after"]))


def test_i_repo_config(hist, qm, clean):
    for k, v in [("diff.interHunkContext", "10"), ("diff.indentHeuristic", "true"),
                 ("diff.algorithm", "patience"), ("diff.renames", "copies"),
                 ("diff.noprefix", "true"), ("diff.relative", "true"), ("color.ui", "always")]:
        hist.git("config", k, v)
    same_as_clean(runs(qm, hist), clean)


def test_i_inter_hunk_context_really_merges(hist):
    """The setting is not a no-op on this fixture: raw git merges the near hunks."""
    n = lambda *o: hist.git("diff", "-U0", *o, hist.base, hist.head, "--", "src/m.py").count("\n@@ ") + 1
    assert n("--inter-hunk-context=0") > n("--inter-hunk-context=10")


def test_ii_attributes_driver_textconv(hist, qm, clean):
    (hist.gitdir() / "info").mkdir(exist_ok=True)
    (hist.gitdir() / "info" / "attributes").write_text("*.py diff=x\n")
    hist.git("config", "diff.x.textconv", "sed -e 1,4d")
    hist.git("config", "diff.x.algorithm", "histogram")
    hist.git("config", "diff.x.xfuncname", "^zzz")
    same_as_clean(runs(qm, hist), clean)


def test_iii_attributes_minus_diff(hist, qm, clean):
    (hist.gitdir() / "info").mkdir(exist_ok=True)
    (hist.gitdir() / "info" / "attributes").write_text("*.py -diff\n")
    same_as_clean(runs(qm, hist), clean)


def test_iv_environment(hist, qm, clean):
    env = {"GIT_CONFIG_PARAMETERS": "'diff.interHunkContext=10'", "GIT_DIFF_OPTS": "--unified=3",
           "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "diff.interHunkContext",
           "GIT_CONFIG_VALUE_0": "10"}
    same_as_clean(runs(qm, hist, env=env), clean)


def test_v_subdirectory(hist, qm, clean):
    sub = hist.path / "src"
    same_as_clean(runs(qm, hist, cwd=sub), clean)
    same_as_clean([qm(hist.path, "--repo", str(sub), "--base", hist.base, "--head", hist.head)],
                  clean[:1])


@pytest.mark.parametrize("use", ["true", "false"])
@pytest.mark.parametrize("kind", ["replace-commit", "graft", "replace-blob"])
def test_vi_replace_refs(hist, qm, clean, kind, use):
    hist.git("config", "core.useReplaceRefs", use)
    if kind == "replace-commit":
        hist.git("replace", hist.head, hist.base)
    elif kind == "graft":
        hist.git("replace", "--graft", hist.head, hist.base)  # head^1 becomes base, not mid
    else:
        old = hist.git("rev-parse", f"{hist.head}:src/m.py")
        new = hist.git("rev-parse", f"{hist.base}:src/m.py")
        hist.git("replace", old, new)
    assert hist.git("for-each-ref", "refs/replace/")
    results = runs(qm, hist)
    same_as_clean(results, clean)
    for r in results:
        assert "replace_refs_present" in r.data()["warnings"]


def test_vi_replace_really_changes_plain_git(hist):
    plain = hist.git("diff", "-U0", hist.base, hist.head, "--", "src/m.py")
    hist.git("replace", hist.head, hist.base)
    assert hist.git("diff", "-U0", hist.base, hist.head, "--", "src/m.py") != plain


def test_x_alternates(hist, qm, clean, tmp_path):
    empty = tmp_path / "empty-objects"
    empty.mkdir()
    (hist.gitdir() / "objects" / "info").mkdir(exist_ok=True)
    (hist.gitdir() / "objects" / "info" / "alternates").write_text(f"{empty}\n")
    results = same_as_clean(runs(qm, hist), clean)
    for r in results:
        assert "alternates_present" in r.data()["warnings"]


def test_clean_repo_has_no_warnings(clean):
    assert all(r.data()["warnings"] == [] for r in clean)
