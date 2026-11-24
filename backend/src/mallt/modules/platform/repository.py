import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.platform.models import FeaturedSpot, PlatformFeature


class PlatformRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def feature_rows(self) -> list[PlatformFeature]:
        return list((await self.session.execute(select(PlatformFeature))).scalars())

    async def get_feature(self, key: str) -> PlatformFeature | None:
        return await self.session.get(PlatformFeature, key)

    def add(self, obj: PlatformFeature | FeaturedSpot) -> None:
        self.session.add(obj)

    async def flush(self) -> None:
        await self.session.flush()

    async def list_spots(self, mall_id: uuid.UUID | None) -> list[FeaturedSpot]:
        stmt = select(FeaturedSpot).order_by(FeaturedSpot.id.desc())
        if mall_id is not None:
            stmt = stmt.where(FeaturedSpot.mall_id == mall_id)
        return list((await self.session.execute(stmt)).scalars())

    async def get_spot(self, spot_id: uuid.UUID) -> FeaturedSpot | None:
        return await self.session.get(FeaturedSpot, spot_id)

    async def live_store_ids(self, mall_id: uuid.UUID | None, now: datetime) -> list[uuid.UUID]:
        """Stores (of one mall, or of every mall) whose spot runs now, earliest grant first."""
        stmt = (
            select(FeaturedSpot.store_id)
            .where(
                FeaturedSpot.revoked_at.is_(None),
                FeaturedSpot.starts_at <= now,
                or_(FeaturedSpot.ends_at.is_(None), FeaturedSpot.ends_at > now),
            )
            .order_by(FeaturedSpot.starts_at, FeaturedSpot.id)
        )
        if mall_id is not None:
            stmt = stmt.where(FeaturedSpot.mall_id == mall_id)
        seen: dict[uuid.UUID, None] = {}
        for store_id in (await self.session.execute(stmt)).scalars():
            seen.setdefault(store_id, None)
        return list(seen)
