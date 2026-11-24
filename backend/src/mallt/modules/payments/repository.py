import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.ids import uuid7
from mallt.modules.payments.enums import PayoutStatus, TaskStatus
from mallt.modules.payments.models import PaymentTask, PayoutAccount, WebhookEvent


class PaymentsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- payout accounts ----

    async def account_for_store(self, store_id: uuid.UUID) -> PayoutAccount | None:
        stmt = select(PayoutAccount).where(PayoutAccount.store_id == store_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def active_accounts(self, store_ids: list[uuid.UUID]) -> dict[uuid.UUID, PayoutAccount]:
        if not store_ids:
            return {}
        stmt = select(PayoutAccount).where(
            PayoutAccount.store_id.in_(store_ids), PayoutAccount.status == PayoutStatus.ACTIVE
        )
        return {a.store_id: a for a in (await self.session.execute(stmt)).scalars()}

    async def list_accounts(self, limit: int) -> list[PayoutAccount]:
        stmt = select(PayoutAccount).order_by(PayoutAccount.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars())

    # ---- tasks ----

    async def tasks_for_order(
        self, customer_order_id: uuid.UUID, *, lock: bool = False
    ) -> list[PaymentTask]:
        """With ``lock``, waits for a worker running one of them, then sees its outcome."""
        stmt = (
            select(PaymentTask)
            .where(PaymentTask.customer_order_id == customer_order_id)
            .order_by(PaymentTask.id)
            .execution_options(populate_existing=True)
        )
        if lock:
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).scalars())

    async def next_due_task(self) -> PaymentTask | None:
        """The oldest due task that is first in line for its customer order, locked."""
        earlier = PaymentTask.__table__.alias("earlier")
        blocked = (
            select(earlier.c.id)
            .where(
                earlier.c.customer_order_id == PaymentTask.customer_order_id,
                earlier.c.id < PaymentTask.id,
                earlier.c.status == TaskStatus.PENDING.value,
            )
            .exists()
        )
        stmt = (
            select(PaymentTask)
            .where(
                PaymentTask.status == TaskStatus.PENDING,
                PaymentTask.next_attempt_at <= datetime.now(UTC),
                ~blocked,
            )
            .order_by(PaymentTask.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def task_by_ref(self, provider: str, provider_ref: str) -> PaymentTask | None:
        stmt = select(PaymentTask).where(
            PaymentTask.provider == provider, PaymentTask.provider_ref == provider_ref
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def failed_tasks(self, limit: int) -> list[PaymentTask]:
        stmt = (
            select(PaymentTask)
            .where(PaymentTask.status == TaskStatus.FAILED)
            .order_by(PaymentTask.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    # ---- webhooks ----

    async def first_delivery(self, provider: str, event_id: str, event_type: str) -> bool:
        """Record the event; False when it was seen before."""
        stmt = (
            insert(WebhookEvent)
            .values(id=uuid7(), provider=provider, event_id=event_id, event_type=event_type)
            .on_conflict_do_nothing(constraint="uq_payment_webhook_events_event")
            .returning(WebhookEvent.id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None
