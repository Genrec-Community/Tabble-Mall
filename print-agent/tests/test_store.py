"""The record of what has already come out of a printer.

This is the file behind AGENT.md rule 9. Everything else in the queue -- the lease, the
attempt cap, the partial unique indexes -- narrows how often a job is *delivered* twice;
only this can make the number of slips one, because the server cannot know whether an
unacked job reached paper.

So the tests here are mostly about survival: across process restarts, across a corrupt
file, across a directory that cannot be written to. In every one of those the wrong
answer is a hotel with two identical slips, or an agent that refuses to start and a
kitchen with none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from print_agent import store as store_module
from print_agent.store import PrintedJobs

pytestmark = pytest.mark.unit

JOB = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def test_a_missing_file_is_the_normal_first_start(tmp_path: Path):
    store = PrintedJobs(tmp_path / "printed-jobs.log")
    store.load()
    assert len(store) == 0
    assert JOB not in store


def test_a_recorded_job_is_remembered(tmp_path: Path):
    store = PrintedJobs(tmp_path / "printed-jobs.log")
    store.load()
    store.record(JOB)
    assert JOB in store
    assert OTHER not in store


def test_the_record_survives_a_restart(tmp_path: Path):
    """The whole reason it is a file.

    The event that loses an ack is usually the event that ends the process -- the PC
    was rebooted, the power went -- so an in-memory set would forget exactly when it
    was needed.
    """
    path = tmp_path / "printed-jobs.log"
    first = PrintedJobs(path)
    first.load()
    first.record(JOB)

    second = PrintedJobs(path)
    second.load()
    assert JOB in second


def test_a_job_is_written_before_the_process_could_end(tmp_path: Path):
    """Flushed and fsynced inside `record`, not at exit.

    Read back through a second reader while the first is still open: if the write were
    buffered, this would see an empty file -- and a power cut in that window is a slip
    that exists on paper and not in the record.
    """
    path = tmp_path / "printed-jobs.log"
    store = PrintedJobs(path)
    store.load()
    store.record(JOB)
    assert path.read_text(encoding="ascii").strip() == JOB


def test_recording_the_same_job_twice_writes_one_line(tmp_path: Path):
    """The client acks an already-printed job, and that path calls nothing here -- but
    a redelivery the client did print once would otherwise grow the file forever."""
    path = tmp_path / "printed-jobs.log"
    store = PrintedJobs(path)
    store.load()
    store.record(JOB)
    store.record(JOB)
    assert path.read_text(encoding="ascii").count(JOB) == 1
    assert len(store) == 1


def test_a_file_with_junk_in_it_still_yields_the_ids(tmp_path: Path):
    """Refusing to start would cost a kitchen every slip until someone logs in to the
    PC. A dropped id costs one duplicate. So the file is read for what it has."""
    path = tmp_path / "printed-jobs.log"
    path.write_text(f"\n{JOB}\n   \n\x00\x01garbage\n{OTHER}\n", encoding="ascii")

    store = PrintedJobs(path)
    store.load()
    assert JOB in store
    assert OTHER in store


def test_duplicate_lines_in_the_file_are_collapsed(tmp_path: Path):
    path = tmp_path / "printed-jobs.log"
    path.write_text(f"{JOB}\n{JOB}\n{JOB}\n", encoding="ascii")
    store = PrintedJobs(path)
    store.load()
    assert len(store) == 1


def test_an_unreadable_file_does_not_stop_the_agent(tmp_path: Path, monkeypatch):
    """A directory where the file should be is one way this happens.

    The agent starting with an empty record risks a duplicate; the agent not starting
    guarantees no slips at all.
    """
    path = tmp_path / "printed-jobs.log"
    path.mkdir()

    store = PrintedJobs(path)
    store.load()
    assert len(store) == 0


def test_a_write_that_fails_does_not_turn_a_print_into_a_failure(tmp_path: Path):
    """The paper is already out when `record` is called.

    Raising here would have the client report the job failed, the server hand it back,
    and the printer produce the duplicate this class exists to prevent.
    """
    path = tmp_path / "sub"
    path.mkdir()
    store = PrintedJobs(path)  # a directory, so every append fails
    store.load()

    store.record(JOB)  # must not raise

    # Still remembered in memory: a restart may reprint it, which is the documented
    # cost, but this process will not.
    assert JOB in store


@pytest.fixture
def small_cap(monkeypatch):
    """Shrink the cap so a compaction can be provoked in a handful of writes.

    The real cap is 5000 and every `record` fsyncs, so filling it took ten seconds --
    in a suite meant to be run constantly, ten seconds nobody waits for. The numbers
    are not what these tests are about: "compacts when over the cap, keeps the newest"
    is the same behaviour at 20 as at 5000.
    """
    monkeypatch.setattr(store_module, "MAX_ENTRIES", 20)
    monkeypatch.setattr(store_module, "KEEP_ENTRIES", 8)
    return 20, 8


def test_the_log_is_compacted_once_it_grows_past_the_cap(
    tmp_path: Path, small_cap: tuple[int, int]
):
    """A year of service should not read a multi-megabyte file at every start.

    The cap is not an expiry: a job can only be redelivered while the server still holds
    it, which is minutes, so what is kept is already far past the useful horizon. That
    is why the assertion is a bound and not an exact count -- compaction keeps the
    newest and the file grows again from there, so what is guaranteed is that it stays
    bounded, not that it sits at one number.
    """
    cap, keep = small_cap
    path = tmp_path / "printed-jobs.log"
    store = PrintedJobs(path)
    store.load()
    for index in range(cap + 5):
        store.record(f"{index:032d}")

    assert keep <= len(store) <= cap
    lines = path.read_text(encoding="ascii").splitlines()
    assert len(lines) == len(store)

    # The most recent survive, which are the ones the server might still resend.
    assert f"{cap + 4:032d}" in store
    assert f"{0:032d}" not in store


def test_compaction_leaves_no_temporary_file_behind(tmp_path: Path, small_cap: tuple[int, int]):
    """Renamed over, not written in place: a failure mid-write would otherwise leave a
    truncated record, which silently re-arms every job the server may resend."""
    cap, _ = small_cap
    path = tmp_path / "printed-jobs.log"
    store = PrintedJobs(path)
    store.load()
    for index in range(cap + 1):
        store.record(f"{index:032d}")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["printed-jobs.log"]


def test_an_oversized_file_is_compacted_at_load(tmp_path: Path, small_cap: tuple[int, int]):
    """The file may already be over the cap when we start -- for instance because the
    process that wrote it was killed before it could compact."""
    cap, keep = small_cap
    path = tmp_path / "printed-jobs.log"
    path.write_text("".join(f"{index:032d}\n" for index in range(cap + 10)), encoding="ascii")

    store = PrintedJobs(path)
    store.load()
    assert len(store) == keep
    assert f"{cap + 9:032d}" in store


def test_the_parent_directory_is_created_if_it_is_missing(tmp_path: Path):
    """`state_dir` can point somewhere that does not exist yet -- a service install
    naming a data folder, for instance. The first print should not be the thing that
    discovers it."""
    store = PrintedJobs(tmp_path / "state" / "printed-jobs.log")
    store.load()
    store.record(JOB)
    assert (tmp_path / "state" / "printed-jobs.log").exists()
