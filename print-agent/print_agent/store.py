"""What has already come out of a printer.

This file is where AGENT.md rule 9 -- print jobs are idempotent by job id, a reconnect
must not reprint a ticket that already came out -- is actually enforced. Everything
else about the queue (the lease, the attempt cap, the partial unique indexes) narrows
how often a job is delivered twice. None of it can make the count one, because the
server cannot know whether an unacked job reached paper: the ack is the only evidence,
and losing it is exactly the case this exists for.

**The record is on disk, not in memory.** The event that loses an ack is usually the
same event that ends the process -- the PC was rebooted, the agent was killed, the
power went. An in-memory set would forget precisely when it was needed.

**A job we have already printed is acked, not ignored.** Both halves matter. Not
printing it is the no-duplicate guarantee; acking it anyway is what stops the server
handing it back every time the lease expires, for ten attempts, and then giving up with
a job the kitchen never sees resolved.

**Recorded after the bytes are accepted, before the ack is sent.** The other order --
record first, then print -- turns a crash mid-job into a slip that is marked done and
never printed, which is the one failure a kitchen cannot detect. This order can instead
produce a duplicate, in the window between the printer accepting a job and this write:
a slip somebody throws away.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: Ids kept before the log is compacted. A job can only be redelivered while the server
#: still holds it -- a 120s lease, ten attempts -- so the useful horizon is minutes.
#: Thousands of entries is already far past it; the cap exists so a year of service does
#: not read a multi-megabyte file at every start, not to expire anything.
MAX_ENTRIES: Final = 5000

#: How many entries survive a compaction. Kept well below the cap so compaction is
#: rare rather than happening on every append once the file is full.
KEEP_ENTRIES: Final = 2000


class PrintedJobs:
    """The set of job ids this agent has put on paper.

    An append-only text file rather than a database or a JSON document: appending one
    line is the smallest write that can be made, needs no schema, and leaves a file a
    support person can read over the phone. A rewritten JSON document would risk
    losing every id to one truncated write -- and this file losing its contents
    silently re-arms every job the server may still resend.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._ids: set[str] = set()
        self._order: list[str] = []

    def load(self) -> None:
        """Read the log, tolerating anything that is not a line we wrote.

        A missing file is the normal first start. A *corrupt* file is also not fatal:
        the worst a dropped id costs is one duplicate slip, while refusing to start
        would cost a kitchen every slip until someone logs in to the PC.
        """
        try:
            raw = self._path.read_text(encoding="ascii", errors="replace")
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning(
                "could not read %s (%s) - starting with an empty record", self._path, exc
            )
            return

        for line in raw.splitlines():
            value = line.strip()
            if value and value not in self._ids:
                self._ids.add(value)
                self._order.append(value)

        if len(self._order) > MAX_ENTRIES:
            self._compact()

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    def record(self, job_id: str) -> None:
        """Note that this job reached a printer.

        Flushed and `fsync`ed before returning. Print volume is a few jobs a minute at
        the very busiest, so the cost is nothing, and without it a power cut leaves the
        record of a slip that exists in a buffer that does not -- which is the exact
        duplicate this class is here to prevent.

        A failed write is logged and swallowed. The paper is already out; raising here
        would turn a successful print into a reported failure and have the server hand
        the job back, which produces the duplicate rather than avoiding it.
        """
        if job_id in self._ids:
            return
        self._ids.add(job_id)
        self._order.append(job_id)

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="ascii") as handle:
                handle.write(f"{job_id}\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            logger.warning(
                "could not record job %s as printed (%s) - a restart may reprint it",
                job_id,
                exc,
            )
            return

        if len(self._order) > MAX_ENTRIES:
            self._compact()

    def _compact(self) -> None:
        """Rewrite the file with only the most recent ids.

        Written to a sibling and renamed over, so a failure leaves the old complete
        file rather than a half-written one. `os.replace` is atomic on both platforms
        we ship to, which `Path.rename` is not on Windows when the target exists.
        """
        keep = self._order[-KEEP_ENTRIES:]
        temporary = self._path.with_suffix(self._path.suffix + ".new")
        try:
            with temporary.open("w", encoding="ascii") as handle:
                handle.write("".join(f"{job_id}\n" for job_id in keep))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as exc:
            logger.warning("could not compact %s (%s)", self._path, exc)
            return

        self._order = keep
        self._ids = set(keep)
