"""Handing queued jobs to a connected agent and recording what came back.

A lease, not a handoff: a claimed job is SENT, and a SENT job unanswered for LEASE_SECONDS is
claimable again, so a crashed agent cannot lose a slip. The duplicate this can cause is absorbed
by the agent, which dedupes on the job id. Only an ack sets ``Printer.last_printed_at``.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.printing.enums import JobStatus
from mallt.modules.printing.models import PrintJob
from mallt.modules.printing.repository import PrintingRepository

log = logging.getLogger(__name__)


class PrintQueue:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = PrintingRepository(session)
        self.session = session

    async def claim(self, store_id: uuid.UUID) -> list[dict[str, Any]]:
        frames = []
        for job in await self.repo.claim_batch(store_id):
            printer = await self.repo.printer_with(job.printer_id)
            if printer is None:  # pragma: no cover - FK cascade removes the job first
                continue
            frames.append(
                {
                    "job_id": str(job.id),
                    "printer_id": str(printer.id),
                    "printer_name": printer.name,
                    "connection": printer.connection.value,
                    "target": printer.target,
                    "paper_width": printer.paper_width,
                    "layout": printer.layout or {},
                    "kind": job.kind.value,
                    "attempt": job.attempts,
                    "payload": job.payload,
                }
            )
        return frames

    async def mark_printed(self, store_id: uuid.UUID, job_id: uuid.UUID) -> None:
        job = await self.repo.scoped_job(store_id, job_id)
        if job is None:
            log.info("ack for unknown job %s", job_id)
            return
        if job.status is not JobStatus.PRINTED:
            job.status = JobStatus.PRINTED
            job.acked_at = datetime.now(UTC)
            job.last_error = None
            printer = await self.repo.printer_with(job.printer_id)
            if printer is not None:
                printer.last_printed_at = job.acked_at
        await self.session.flush()

    async def mark_failed(self, store_id: uuid.UUID, job_id: uuid.UUID, error: str) -> None:
        job = await self.repo.scoped_job(store_id, job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED
        job.last_error = error[:500]
        await self.session.flush()

    async def requeue_unacked(self, store_id: uuid.UUID, job_ids: list[uuid.UUID]) -> int:
        if not job_ids:
            return 0
        jobs: list[PrintJob] = await self.repo.unacked(store_id, job_ids)
        for job in jobs:
            job.status = JobStatus.QUEUED
        await self.session.flush()
        return len(jobs)
