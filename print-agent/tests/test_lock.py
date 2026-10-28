"""One agent per state folder.

Two agents sharing `printed-jobs.log` would each believe a slip was theirs to print,
and a double start (a task that fires twice at logon, a service restarted by hand
while a supervisor is also running) is exactly how that happens. The lock is held by
the OS, so a crash frees it without a cleanup step that a crash would skip.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from print_agent.lock import AlreadyRunning, InstanceLock

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent


def test_a_second_lock_on_the_same_folder_is_refused(tmp_path: Path):
    first = InstanceLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunning):
            InstanceLock(tmp_path).acquire()
    finally:
        first.release()


def test_the_lock_is_free_again_after_release(tmp_path: Path):
    first = InstanceLock(tmp_path)
    first.acquire()
    first.release()

    again = InstanceLock(tmp_path)
    again.acquire()
    again.release()


def test_release_twice_is_harmless(tmp_path: Path):
    lock = InstanceLock(tmp_path)
    lock.acquire()
    lock.release()
    lock.release()


def test_a_different_folder_is_independent(tmp_path: Path):
    a = InstanceLock(tmp_path / "a")
    b = InstanceLock(tmp_path / "b")
    a.acquire()
    try:
        b.acquire()
        b.release()
    finally:
        a.release()


def test_the_folder_is_created_when_it_does_not_exist(tmp_path: Path):
    lock = InstanceLock(tmp_path / "does" / "not" / "exist")
    lock.acquire()
    lock.release()
    assert (tmp_path / "does" / "not" / "exist" / "agent.lock").exists()


def test_the_holders_pid_is_readable_for_support(tmp_path: Path):
    lock = InstanceLock(tmp_path)
    lock.acquire()
    try:
        with open(tmp_path / "agent.lock", "rb") as handle:
            handle.seek(1)  # byte 0 is the locked byte on Windows
            assert handle.read().strip() == str(os.getpid()).encode()
    finally:
        lock.release()


def test_the_context_manager_acquires_and_releases(tmp_path: Path):
    with InstanceLock(tmp_path), pytest.raises(AlreadyRunning):
        InstanceLock(tmp_path).acquire()
    InstanceLock(tmp_path).acquire()


def test_a_folder_that_is_really_a_file_is_an_oserror_not_already_running(
    tmp_path: Path,
):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a folder")
    with pytest.raises(OSError):
        InstanceLock(blocker / "state").acquire()


def test_a_killed_holder_frees_the_lock(tmp_path: Path):
    """The OS releases the lock when the process dies, however it dies."""
    code = (
        "import sys, time; from pathlib import Path; "
        "from print_agent.lock import InstanceLock; "
        "lock = InstanceLock(Path(sys.argv[1])); lock.acquire(); "
        "print('held', flush=True); time.sleep(60)"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=ROOT,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(AlreadyRunning):
            InstanceLock(tmp_path).acquire()
    finally:
        if sys.platform == "win32":
            # A virtualenv's python.exe is a launcher that starts the real interpreter
            # as a child; killing only the launcher would leave the lock held.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(holder.pid)],
                capture_output=True,
                check=False,
            )
        else:
            holder.kill()
        holder.wait()

    freed = InstanceLock(tmp_path)
    freed.acquire()
    freed.release()
