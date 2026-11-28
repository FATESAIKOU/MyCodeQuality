"""mcq-weekly contracts: input validation, permission failures, entry points (PYTHONPATH and installed script)."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import mcqweekly.fsio as fsio
from mcqweekly.cli import main
from mcqweekly.repos import load_repos
from mcqweekly.errors import TOOL_ERRORS
from weekly_helpers import FROM, TO, list_runner, write_repos

SRC = Path(__file__).resolve().parent.parent / "src"


@pytest.mark.parametrize("payload", [
    {"kind": "mcq-weekly-repos", "schema_version": 1, "repos": []},
    {"kind": "mcq-weekly-repos", "schema_version": True, "repos": ["a/b"]},
    {"kind": "mcq-weekly-repos", "schema_version": 1, "repos": ["noslash"]},
    {"kind": "mcq-weekly-repos", "schema_version": 1, "repos": ["a/b/c"]},
    {"kind": "mcq-weekly-repos", "schema_version": 1, "repos": [1]},
    {"kind": "other", "schema_version": 1, "repos": ["a/b"]},
])
def test_bad_repos_inputs_are_rejected(tmp_path, payload):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TOOL_ERRORS) as err:
        load_repos(str(path))
    assert err.value.code == "bad_repos"


@pytest.mark.parametrize("n", ["0", "5001", "x"])
def test_max_tickets_bounds_exit_2(tmp_path, n):
    repos = write_repos(tmp_path / "r.json", ["a/b"])
    argv = ["select", "--repos", str(repos), "--from", FROM, "--to", TO, "--as-of", TO,
            "--max-tickets", n, "--out", str(tmp_path / "o.json")]
    assert main(argv, runner=list_runner({})) == 2


def test_bad_as_of_and_out_inside_repo_exit_2(tmp_path):
    repos = write_repos(tmp_path / "r.json", ["a/b"])
    base = ["select", "--repos", str(repos), "--from", FROM, "--to", TO]
    assert main(base + ["--as-of", "yesterday", "--out", str(tmp_path / "o.json")], runner=list_runner({"a/b": []})) == 2

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert main(base + ["--as-of", TO, "--out", str(repo / "o.json")], runner=list_runner({"a/b": []})) == 2
    assert not (repo / "o.json").exists()


def test_bad_population_shapes_exit_2(tmp_path):
    from weekly_helpers import write_population, ticket_row
    from mcqweekly.run import load_population

    good = write_population(tmp_path / "p.json", ["acme/alpha"], [ticket_row("acme/alpha#1")])
    data = json.loads(good.read_text(encoding="utf-8"))
    variants = [
        {**data, "rules": "other"},
        {**data, "schema_version": True},
        {**data, "tickets": [{"ticket": "acme/alpha#1", "closed_at": FROM, "level": "x"}]},
        {**data, "tickets": [{"ticket": "other/x#1", "closed_at": FROM, "level": "c"}]},
        {**data, "repos": [{"repo": "acme/alpha", "status": "weird", "tickets_seen": 0}]},
        {**data, "window": {"from": TO, "to": FROM}},
    ]
    for i, variant in enumerate(variants):
        path = tmp_path / f"bad{i}.json"
        path.write_text(json.dumps(variant), encoding="utf-8")
        with pytest.raises(TOOL_ERRORS):
            load_population(str(path))


def test_chmod_failure_is_exit_2(tmp_path, monkeypatch):
    target = tmp_path / "d"

    def boom(path, mode):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(fsio.os, "chmod", boom)
    with pytest.raises(TOOL_ERRORS) as err:
        fsio.ensure_private_dir(target)
    assert err.value.code == "chmod_failed"


def test_pythonpath_entry_point_runs(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run([sys.executable, "-m", "mcqweekly", "--help"], capture_output=True, text=True, env=env)
    assert proc.returncode == 0 and "select" in proc.stdout and "run" in proc.stdout


def test_installed_console_script_runs_when_installed(tmp_path):
    script = Path(sys.executable).parent / "mcq-weekly"
    if not script.exists() and shutil.which("mcq-weekly") is None:
        pytest.skip("mcq-weekly console script is not installed in this environment")
    exe = str(script) if script.exists() else shutil.which("mcq-weekly")
    proc = subprocess.run([exe, "--help"], capture_output=True, text=True)
    assert proc.returncode == 0 and "select" in proc.stdout
