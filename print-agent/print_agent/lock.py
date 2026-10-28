"""One agent per state folder.

The record of printed jobs (`store.py`) is only a guarantee while exactly one process
reads and writes it. Two agents on one folder would each load the same record, each be
handed a redelivered job, and each print it. A task that fires twice at logon, or a
service started by hand beside a running supervisor, is how that happens on a store PC
nobody can log into.

The lock is an operating-system file lock held for the life of the process, not a
pid file that is checked and trusted. A process that is killed, crashes or loses power
frees it with no cleanup step -- which is the only kind of lock that survives the
failures this exists for. The holder's pid is written beside it purely so a support
person can see who has it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType
from typing import IO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class AlreadyRunning(Exception):
    """Another agent holds this state folder."""


def _lock(handle: IO[bytes]) -> None:
    """Take the exclusive lock without waiting. Raises `OSError` if it is held."""
    if sys.platform == "win32":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class InstanceLock:
    """Holds `<state_dir>/agent.lock` for as long as it is acquired."""

    def __init__(self, state_dir: Path) -> None:
        self._path = state_dir / "agent.lock"
        self._handle: IO[bytes] | None = None

    def acquire(self) -> None:
        """Take the lock, or raise `AlreadyRunning`.

        `OSError` is deliberately *not* turned into `AlreadyRunning`: a folder that
        cannot be created or a file that cannot be opened is a different fault, and
        the caller tells the admin about it in different words.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        try:
            # The locked byte has to exist on Windows; a space costs nothing.
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b" ")
                handle.flush()
            try:
                _lock(handle)
            except OSError:
                raise AlreadyRunning(
                    f"another print-agent is already running here ({self._path}). "
                    "Stop it first, or wait for it to finish starting."
                ) from None
            handle.seek(1)
            handle.truncate()
            handle.write(f"{os.getpid()}\n".encode())
            handle.flush()
        except BaseException:
            handle.close()
            raise
        self._handle = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            _unlock(handle)
        finally:
            handle.close()

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
