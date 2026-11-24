import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.notify.models import Notification, NotifyPrefs, PushSubscription


class NotifyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_subscription(
        self, customer_id: uuid.UUID, endpoint: str, p256dh: str, auth: str
    ) -> None:
        stmt = insert(PushSubscription).values(
            id=uuid.uuid4(), customer_id=customer_id, endpoint=endpoint, p256dh=p256dh, auth=auth
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[PushSubscription.endpoint],
            set_={
                "customer_id": customer_id,
                "p256dh": p256dh,
                "auth": auth,
                "updated_at": func.now(),
            },
        )
        await self.session.execute(stmt)

    async def delete_subscription(
        self, endpoint: str, customer_id: uuid.UUID | None = None
    ) -> None:
        stmt = delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
        if customer_id is not None:
            stmt = stmt.where(PushSubscription.customer_id == customer_id)
        await self.session.execute(stmt)

    async def subscriptions(self, customer_id: uuid.UUID) -> list[PushSubscription]:
        stmt = select(PushSubscription).where(PushSubscription.customer_id == customer_id)
        return list((await self.session.execute(stmt)).scalars())

    async def prefs(self, customer_id: uuid.UUID) -> NotifyPrefs | None:
        return await self.session.get(NotifyPrefs, customer_id)

    async def set_prefs(self, customer_id: uuid.UUID, whatsapp: bool) -> None:
        stmt = insert(NotifyPrefs).values(customer_id=customer_id, whatsapp=whatsapp)
        stmt = stmt.on_conflict_do_update(
            index_elements=[NotifyPrefs.customer_id],
            set_={"whatsapp": whatsapp, "updated_at": func.now()},
        )
        await self.session.execute(stmt)

    def add(self, row: Notification) -> None:
        self.session.add(row)

    async def next_due(self) -> Notification | None:
        stmt = (
            select(Notification)
            .where(
                Notification.status == "pending", Notification.next_attempt_at <= datetime.now(UTC)
            )
            .order_by(Notification.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
