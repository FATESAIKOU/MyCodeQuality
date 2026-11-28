"""Privacy guard: work, costs and out paths must not sit inside any git worktree."""

import os
from pathlib import Path

from mcqreport.common import ToolError


def real_path(path: str) -> Path:
    return Path(os.path.realpath(path))


def in_git_worktree(real: Path) -> bool:
    """True if this path or any ancestor has a .git entry (directory for a clone, file for a worktree)."""
    for candidate in (real, *real.parents):
        if os.path.lexists(candidate / ".git"):
            return True
    return False


def private_location(path: str, label: str) -> Path:
    """Resolve symlinks and refuse anything that lands inside a git worktree."""
    real = real_path(path)
    if in_git_worktree(real):
        raise ToolError("private_in_repo", f"{label} is inside a git worktree; private output must live outside repos")
    return real
