"""Private, durable file writes: 0600 files, 0700 directories, fsync before publish."""

import json
import os
from pathlib import Path

from mcqreport.common import ToolError


def render(obj) -> str:
    """Deterministic JSON: sorted keys, indent 2, UTF-8 text, one trailing newline."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_private_dir(path: Path, parents: bool = False) -> Path:
    """Create (if needed) and chmod a directory to 0700. Symlinks and non-directories are refused."""
    if path.is_symlink():
        raise ToolError("unsafe_path", f"refusing symlinked directory: {path.name}")
    if path.exists() and not path.is_dir():
        raise ToolError("unsafe_path", f"not a directory: {path.name}")
    try:
        path.mkdir(mode=0o700, parents=parents, exist_ok=True)
        os.chmod(path, 0o700)
    except OSError as e:
        raise ToolError("chmod_failed", f"cannot make directory private: {path.name}: {e.strerror}") from None
    return path


def private_existing_file(path: Path) -> None:
    """Tighten an existing file to 0600 (reuse must not leave a wider mode behind)."""
    try:
        os.chmod(path, 0o600)
    except OSError as e:
        raise ToolError("chmod_failed", f"cannot make file private: {path.name}: {e.strerror}") from None


def write_new_file(path: Path, text: str) -> None:
    """Create a new 0600 file (exclusive), write, fsync. Fails if the path already exists."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(path, 0o600)
    except OSError as e:
        raise ToolError("write_failed", f"cannot write {path.name}: {e.strerror}") from None


def replace_atomically(path: Path, text: str) -> None:
    """Write `<path>.tmp` (fsync), os.replace it onto `path`, then fsync the parent directory."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        if os.path.lexists(tmp):
            os.unlink(tmp)
    except OSError as e:
        raise ToolError("write_failed", f"cannot clear {tmp.name}: {e.strerror}") from None
    write_new_file(tmp, text)
    try:
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except OSError as e:
        raise ToolError("write_failed", f"cannot publish {path.name}: {e.strerror}") from None
