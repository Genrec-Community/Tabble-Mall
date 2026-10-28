import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.errors import Conflict
from mallt.modules.printing.enums import JobKind, JobStatus, PrinterConnection, PrinterRole
from mallt.modules.printing.models import (
    DetectedPrinter,
    PrintAgent,
    Printer,
    PrintJob,
    StoreBillSettings,
)

LEASE_SECONDS = 120.0
BATCH_SIZE = 20
MAX_ATTEMPTS = 10


class PrintingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_unique(self, obj: object, message: str) -> None:
        try:
            async with self.session.begin_nested():
                self.session.add(obj)
                await self.session.flush()
        except IntegrityError as exc:
            raise Conflict("name_taken", message) from exc

    async def flush_unique(self, message: str) -> None:
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError as exc:
            raise Conflict("name_taken", message) from exc

    # ---- agents ----

    async def agent(self, agent_id: uuid.UUID) -> PrintAgent | None:
        return await self.session.get(PrintAgent, agent_id)

    async def store_agent(self, store_id: uuid.UUID, agent_id: uuid.UUID) -> PrintAgent | None:
        stmt = select(PrintAgent).where(PrintAgent.store_id == store_id, PrintAgent.id == agent_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def agents(self, store_id: uuid.UUID) -> list[PrintAgent]:
        stmt = (
            select(PrintAgent)
            .where(PrintAgent.store_id == store_id)
            .order_by(PrintAgent.is_active.desc(), PrintAgent.name)
        )
        return list((await self.session.execute(stmt)).scalars())

    # ---- detected printers ----

    async def replace_detected(
        self, agent: PrintAgent, items: list[DetectedPrinter], *, scope: set[PrinterConnection]
    ) -> None:
        """Replace what this agent reported for the connection kinds in ``scope`` only: the
        periodic local report must not erase LAN printers found by an on-demand scan, nor the
        reverse."""
        await self.session.execute(
            delete(DetectedPrinter).where(
                DetectedPrinter.agent_id == agent.id, DetectedPrinter.connection.in_(scope)
            )
        )
        self.session.add_all(items)
        await self.session.flush()

    async def detected(self, store_id: uuid.UUID) -> list[tuple[DetectedPrinter, str]]:
        stmt = (
            select(DetectedPrinter, PrintAgent.name)
            .join(PrintAgent, PrintAgent.id == DetectedPrinter.agent_id)
            .where(DetectedPrinter.store_id == store_id, PrintAgent.is_active.is_(True))
            .order_by(DetectedPrinter.likely_thermal.desc(), DetectedPrinter.name)
        )
        return [(d, name) for d, name in (await self.session.execute(stmt)).all()]

    # ---- printers ----

    async def printers(self, store_id: uuid.UUID, *, active_only: bool = False) -> list[Printer]:
        stmt = select(Printer).where(Printer.store_id == store_id).order_by(Printer.name)
        if active_only:
            stmt = stmt.where(Printer.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars())

    async def printer(self, store_id: uuid.UUID, printer_id: uuid.UUID) -> Printer | None:
        stmt = select(Printer).where(Printer.store_id == store_id, Printer.id == printer_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def printers_by_role(self, store_id: uuid.UUID, role: PrinterRole) -> list[Printer]:
        stmt = select(Printer).where(
            Printer.store_id == store_id, Printer.role == role, Printer.is_active.is_(True)
        )
        return list((await self.session.execute(stmt)).scalars())

    # ---- design ----

    async def design(self, store_id: uuid.UUID) -> StoreBillSettings | None:
        stmt = select(StoreBillSettings).where(StoreBillSettings.store_id == store_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ---- jobs ----

    async def insert_job(self, job: PrintJob) -> bool:
        """Queue a job; False if an identical KOT already exists (idempotent)."""
        values = {
            c.name: getattr(job, c.name)
            for c in PrintJob.__table__.columns
            if getattr(job, c.name) is not None
        }
        stmt = insert(PrintJob).values(**values).on_conflict_do_nothing().returning(PrintJob.id)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def next_revision(self, order_id: uuid.UUID, kind: JobKind) -> int:
        stmt = select(func.max(PrintJob.revision)).where(
            PrintJob.store_order_id == order_id, PrintJob.kind == kind
        )
        current = (await self.session.execute(stmt)).scalar()
        return 0 if current is None else int(current) + 1

    async def bill_copies(self, order_id: uuid.UUID) -> int:
        stmt = select(func.count(func.distinct(PrintJob.revision))).where(
            PrintJob.store_order_id == order_id, PrintJob.kind == JobKind.BILL
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def recent_jobs(self, store_id: uuid.UUID, limit: int) -> list[PrintJob]:
        stmt = (
            select(PrintJob)
            .where(PrintJob.store_id == store_id)
            .order_by(PrintJob.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def claim_batch(self, store_id: uuid.UUID, limit: int = BATCH_SIZE) -> list[PrintJob]:
        stale_before = datetime.now(UTC) - timedelta(seconds=LEASE_SECONDS)
        stale = PrintJob.acked_at.is_(None) & (PrintJob.sent_at < stale_before)
        claimable = (PrintJob.status == JobStatus.QUEUED) | (
            PrintJob.status.in_((JobStatus.SENT, JobStatus.FAILED)) & stale
        )
        stmt = (
            select(PrintJob)
            .join(Printer, Printer.id == PrintJob.printer_id)
            .where(
                PrintJob.store_id == store_id,
                Printer.is_active.is_(True),
                PrintJob.attempts < MAX_ATTEMPTS,
                claimable,
            )
            .order_by(PrintJob.created_at, PrintJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True, of=PrintJob)
        )
        jobs = list((await self.session.execute(stmt)).scalars())
        now = datetime.now(UTC)
        for job in jobs:
            job.status = JobStatus.SENT
            job.sent_at = now
            job.attempts += 1
        if jobs:
            await self.session.flush()
        return jobs

    async def scoped_job(self, store_id: uuid.UUID, job_id: uuid.UUID) -> PrintJob | None:
        stmt = select(PrintJob).where(PrintJob.store_id == store_id, PrintJob.id == job_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def unacked(self, store_id: uuid.UUID, job_ids: list[uuid.UUID]) -> list[PrintJob]:
        stmt = select(PrintJob).where(
            PrintJob.store_id == store_id,
            PrintJob.id.in_(job_ids),
            PrintJob.status == JobStatus.SENT,
            PrintJob.acked_at.is_(None),
        )
        return list((await self.session.execute(stmt)).scalars())

    async def printer_with(self, printer_id: uuid.UUID) -> Printer | None:
        return await self.session.get(Printer, printer_id)
