import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

GIT_ID = ["-c", "user.name=qc-test", "-c", "user.email=qc-test@example.invalid",
          "-c", "commit.gpgsign=false"]


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """First rule: HOME and TMPDIR live in a throwaway directory, no system/global git config."""
    home = tmp_path / "home"
    tmp = tmp_path / "tmp"
    home.mkdir()
    tmp.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TMPDIR", str(tmp))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    for k in list(os.environ):
        if k.startswith("GIT_") and k not in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"):
            monkeypatch.delenv(k)


class Repo:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args, cwd=None, env=None, check=True):
        e = {**os.environ, **(env or {})}
        proc = subprocess.run(["git", *GIT_ID, *args], cwd=cwd or self.path, env=e,
                              capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise AssertionError(f"git {args} failed: {proc.stderr}")
        return proc.stdout.strip()

    def commit(self, files, msg="c", delete=()):
        for p, text in files.items():
            f = self.path / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        for p in delete:
            (self.path / p).unlink()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def gitdir(self):
        return Path(self.git("rev-parse", "--absolute-git-dir"))


@pytest.fixture
def make_repo(tmp_path):
    n = [0]

    def make():
        n[0] += 1
        return Repo(tmp_path / f"repo{n[0]}")

    return make


class Result:
    def __init__(self, proc):
        self.rc, self.out, self.err = proc.returncode, proc.stdout, proc.stderr

    def data(self):
        return json.loads(self.out)

    def stable(self):
        """The JSON bytes with `warnings` removed (the determinism contract)."""
        d = self.data()
        d.pop("warnings")
        return json.dumps(d, sort_keys=True, indent=2)


def run_qm(cwd, *args, env=None):
    e = {**os.environ, **(env or {})}
    proc = subprocess.run([sys.executable, "-m", "qmetrics", "diff", "--json", *args],
                          cwd=cwd, env=e, capture_output=True, text=True)
    return Result(proc)


@pytest.fixture
def qm():
    return run_qm
