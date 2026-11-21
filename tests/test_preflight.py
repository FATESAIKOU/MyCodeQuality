"""13.3 (g): history must be complete and clean; tool errors print no quality values."""
import pytest


@pytest.fixture
def abc(make_repo):
    repo = make_repo()
    repo.A = repo.commit({"src/a.py": "x = 0\n"}, "A")
    repo.B = repo.commit({"src/a.py": "x = 1\n"}, "B")
    repo.C = repo.commit({"src/a.py": "x = 2\n"}, "C")
    return repo


def modes(repo):
    return [("--merge", repo.C), ("--pr-base", repo.B, "--pr-head", repo.C)]


def assert_tool_error(r, code):
    assert r.rc != 0
    assert r.out == "", "tool errors print no quality values"
    assert f"error {code}:" in r.err
    assert len(r.err.strip().splitlines()) == 1


def test_clean_baseline(abc, qm):
    for m in modes(abc):
        r = qm(abc.path, *m)
        assert r.rc == 0
        assert r.data()["base"] == abc.B


def test_vii_grafts(abc, qm):
    (abc.gitdir() / "info").mkdir(exist_ok=True)
    (abc.gitdir() / "info" / "grafts").write_text(f"{abc.C} {abc.A}\n")
    # sanity: plain git really does move the parent to A
    assert abc.git("rev-parse", f"{abc.C}^1") == abc.A
    for m in modes(abc):
        assert_tool_error(qm(abc.path, *m), "grafts_present")
    assert_tool_error(qm(abc.path, "--base", abc.B, "--head", abc.C), "grafts_present")


def test_viii_shallow(abc, qm):
    (abc.gitdir() / "shallow").write_text(abc.C + "\n")
    for m in modes(abc):
        assert_tool_error(qm(abc.path, *m), "shallow_repository")


def test_ix_worktree_shared_gitdir(abc, qm, tmp_path):
    wt = tmp_path / "wt"
    abc.git("worktree", "add", "-q", "--detach", str(wt), abc.C)
    (abc.gitdir() / "info").mkdir(exist_ok=True)
    (abc.gitdir() / "info" / "grafts").write_text(f"{abc.C} {abc.A}\n")
    for m in modes(abc):
        assert_tool_error(qm(wt, *m), "grafts_present")
    (abc.gitdir() / "info" / "grafts").unlink()
    (abc.gitdir() / "shallow").write_text(abc.C + "\n")
    for m in modes(abc):
        assert_tool_error(qm(wt, *m), "shallow_repository")


def test_ix_worktree_clean_works(abc, qm, tmp_path):
    wt = tmp_path / "wt"
    abc.git("worktree", "add", "-q", "--detach", str(wt), abc.C)
    assert qm(wt, "--merge", abc.C).data()["base"] == abc.B


def test_unknown_and_bad_arguments(abc, qm):
    assert_tool_error(qm(abc.path, "--merge", "no-such-rev"), "unknown_revision")
    assert_tool_error(qm(abc.path, "--merge=--evil"), "bad_revision")
    assert_tool_error(qm(abc.path, "--merge", abc.A), "no_parent")
    assert_tool_error(qm(abc.path), "bad_arguments")
    assert_tool_error(qm(abc.path, "--merge", abc.C, "--base", abc.A, "--head", abc.C), "bad_arguments")
    assert_tool_error(qm(abc.path, "--pr-base", abc.A), "bad_arguments")


def test_not_a_repository(tmp_path, qm):
    d = tmp_path / "plain"
    d.mkdir()
    assert_tool_error(qm(d, "--merge", "HEAD"), "not_a_repository")
