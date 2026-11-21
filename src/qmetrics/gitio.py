"""Hardened git access (design 13.3 (a)-(g)): every read goes through `Git`."""

import os
import subprocess
import tempfile


class ToolError(Exception):
    """A tool error: the run stops and no quality values are printed."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# (a) options that go on every `git diff` call
DIFF_OPTS = (
    "--no-color", "--no-ext-diff", "--no-textconv", "--text", "--no-renames",
    "--diff-algorithm=myers", "--inter-hunk-context=0", "--no-indent-heuristic",
    "--no-relative", "--src-prefix=a/", "--dst-prefix=b/",
)

# (b) second line of defence: `-c` overrides, including (f) core.useReplaceRefs
CONFIG_OVERRIDES = (
    "core.quotepath=off", "core.attributesFile=/dev/null", "diff.interHunkContext=0",
    "diff.indentHeuristic=false", "diff.algorithm=myers", "diff.renames=false",
    "diff.noprefix=false", "diff.relative=false", "color.ui=never",
    "core.useReplaceRefs=false",
)


def split_z(data):
    return [p.decode("utf-8", "surrogateescape") for p in data.split(b"\0") if p]


class Git:
    """Runs git with a whitelisted environment, an empty HOME and fixed options."""

    def __init__(self, repo_hint, home):
        # (c) whitelist: nothing else is inherited from the caller's environment
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LC_ALL": "C",
            "HOME": home,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
        self.root = None
        self.root = self._find_root(repo_hint)

    def _argv(self, cwd, args):
        argv = ["git", "--no-replace-objects", "-C", cwd]
        for c in CONFIG_OVERRIDES:
            argv += ["-c", c]
        return argv + list(args)

    def run(self, *args, check=True, stdin=None):
        proc = subprocess.run(self._argv(self.root, args), env=self.env, input=stdin,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            raise ToolError("git_failed", f"git {args[0]} failed: {err[0] if err else proc.returncode}")
        return proc

    def out(self, *args, stdin=None):
        return self.run(*args, stdin=stdin).stdout

    def text(self, *args):
        return self.out(*args).decode("utf-8", "replace").strip()

    def _find_root(self, hint):
        try:
            proc = subprocess.run(self._argv(hint, ["rev-parse", "--show-toplevel"]), env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            raise ToolError("git_unavailable", f"cannot run git: {e}")
        if proc.returncode != 0:
            raise ToolError("not_a_repository", f"not a git working tree: {hint}")
        return proc.stdout.decode("utf-8", "surrogateescape").strip()

    def version(self):
        parts = self.text("--version").split()
        return parts[2] if len(parts) > 2 else "unknown"

    def git_path(self, rel):
        p = self.text("rev-parse", "--git-path", rel)
        return p if os.path.isabs(p) else os.path.join(self.root, p)

    def read_blobs(self, shas):
        """sha -> bytes, one `cat-file --batch` call (no path involved, no textconv)."""
        shas = sorted(set(shas))
        if not shas:
            return {}
        data = self.out("cat-file", "--batch", stdin=("\n".join(shas) + "\n").encode())
        out, pos = {}, 0
        for sha in shas:
            nl = data.index(b"\n", pos)
            head = data[pos:nl].split()
            if len(head) != 3 or head[1] != b"blob":
                raise ToolError("object_missing", f"cannot read blob {sha}")
            size = int(head[2])
            out[sha] = data[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1
        return out


def preflight(git):
    """(g) history must be complete and clean. Returns the warning codes."""
    if os.path.exists(git.git_path("info/grafts")):
        raise ToolError("grafts_present",
                        "info/grafts exists: local history was rewritten, refusing to pick a base")
    if git.text("rev-parse", "--is-shallow-repository") == "true":
        raise ToolError("shallow_repository",
                        "shallow repository: a full history is required (fetch-depth: 0)")
    warnings = []
    if os.path.exists(git.git_path("objects/info/alternates")):
        warnings.append("alternates_present")
    if git.text("for-each-ref", "refs/replace/"):
        warnings.append("replace_refs_present")
    return sorted(warnings)


def resolve_commit(git, spec):
    if spec.startswith("-"):
        raise ToolError("bad_revision", f"not a revision: {spec}")
    proc = git.run("rev-parse", "--verify", "--quiet", spec + "^{commit}", check=False)
    if proc.returncode != 0:
        raise ToolError("unknown_revision", f"cannot resolve a commit: {spec}")
    return proc.stdout.decode().strip()


def first_parent(git, merge):
    head = resolve_commit(git, merge)
    proc = git.run("rev-parse", "--verify", "--quiet", head + "^1^{commit}", check=False)
    if proc.returncode != 0:
        raise ToolError("no_parent", f"commit has no first parent: {merge}")
    return proc.stdout.decode().strip(), head


def merge_base(git, base_ref, head_ref):
    a, b = resolve_commit(git, base_ref), resolve_commit(git, head_ref)
    proc = git.run("merge-base", a, b, check=False)
    out = proc.stdout.decode().strip()
    if proc.returncode != 0 or not out:
        raise ToolError("merge_base_not_found", f"no merge base for {base_ref} and {head_ref}")
    return out, b


def make_home():
    return tempfile.TemporaryDirectory(prefix="qmetrics-home-")
