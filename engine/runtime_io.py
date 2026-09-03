"""Small Linux runtime primitives shared by worker and storage code."""

from __future__ import annotations

import fcntl
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def exclusive_file_lock(path: Path, *, blocking: bool = True) -> Iterator[bool]:
    """Hold an advisory exclusive lock for the lifetime of the context."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock_file:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(lock_file.fileno(), flags)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def try_singleton_lock(path: Path) -> Iterator[bool]:
    """Return the nonblocking lock context used by singleton processes."""
    return exclusive_file_lock(path, blocking=False)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Fsync and atomically replace a text file using a unique sibling temp file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, raw_temp = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as temp_file:
            temp_file.write(text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        temp_path.chmod(existing_mode)
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
