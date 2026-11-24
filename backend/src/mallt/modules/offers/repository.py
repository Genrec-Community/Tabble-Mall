import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mallt.modules.offers.models import Combo, Offer


class OffersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: Offer | Combo) -> None:
        self.session.add(row)
        await self.session.flush()

    async def store_offers(self, store_id: uuid.UUID) -> list[Offer]:
        stmt = (
            select(Offer)
            .where(Offer.store_id == store_id, Offer.is_archived.is_(False))
            .order_by(Offer.id.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def offer(self, offer_id: uuid.UUID) -> Offer | None:
        row = await self.session.get(Offer, offer_id)
        return None if row is None or row.is_archived else row

    async def code_taken(self, store_id: uuid.UUID, code: str, except_id: uuid.UUID | None) -> bool:
        stmt = select(Offer.id).where(
            Offer.store_id == store_id, Offer.code == code, Offer.is_archived.is_(False)
        )
        if except_id is not None:
            stmt = stmt.where(Offer.id != except_id)
        return (await self.session.execute(stmt.limit(1))).first() is not None

    async def live_offers(self, store_ids: list[uuid.UUID], now: datetime) -> list[Offer]:
        if not store_ids:
            return []
        stmt = select(Offer).where(
            Offer.store_id.in_(store_ids),
            Offer.is_active.is_(True),
            Offer.is_archived.is_(False),
            or_(Offer.starts_at.is_(None), Offer.starts_at <= now),
            or_(Offer.ends_at.is_(None), Offer.ends_at > now),
        )
        return list((await self.session.execute(stmt)).scalars())

    async def mall_combos(self, mall_id: uuid.UUID, *, live_at: datetime | None) -> list[Combo]:
        stmt = (
            select(Combo)
            .where(Combo.mall_id == mall_id, Combo.is_archived.is_(False))
            .options(selectinload(Combo.items))
            .order_by(Combo.id.desc())
        )
        if live_at is not None:
            stmt = stmt.where(
                Combo.is_active.is_(True),
                or_(Combo.starts_at.is_(None), Combo.starts_at <= live_at),
                or_(Combo.ends_at.is_(None), Combo.ends_at > live_at),
            )
        return list((await self.session.execute(stmt)).scalars())

    async def combo(self, combo_id: uuid.UUID) -> Combo | None:
        stmt = select(Combo).where(Combo.id == combo_id).options(selectinload(Combo.items))
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None or row.is_archived else row
