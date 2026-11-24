"""What's popular in a mall: ranked from paid orders, shown through the catalog."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.kv import KV
from mallt.core.storage import Storage
from mallt.modules.catalog.schemas import PopularOut
from mallt.modules.catalog.service import CatalogService, OrderingCatalog
from mallt.modules.orders.repository import OrdersRepository
from mallt.modules.orders.reviews import popularity
from mallt.modules.platform.service import FeatureService

POPULAR_WINDOW = timedelta(days=30)


class DiscoveryService:
    def __init__(self, session: AsyncSession, kv: KV, storage: Storage) -> None:
        self.repo = OrdersRepository(session)
        self.ordering = OrderingCatalog(session, kv)
        self.catalog = CatalogService(session, kv, storage)
        self.features = FeatureService(session)

    async def popular(self, mall_slug: str, limit: int) -> PopularOut:
        mall = await self.ordering.mall_stores(mall_slug)  # 404 for unknown or suspended
        counts = await self.repo.popular_products(
            mall.id, datetime.now(UTC) - POPULAR_WINDOW, limit * 3
        )
        ratings = (
            await self.repo.product_ratings(mall.id)
            if await self.features.is_enabled("reviews")
            else {}
        )
        # Well-liked dishes rise: rank by orders nudged by stars (see reviews.popularity).
        scored = sorted(
            counts,
            key=lambda pc: -popularity(pc[1], *ratings.get(pc[0], (None, 0))),
        )[: limit * 2]
        out = await self.catalog.public_items_by_ids(mall_slug, scored, fill_to=limit)
        for item in out.items:
            avg, n = ratings.get(item.product.id, (None, 0))
            if n:
                item.rating, item.rating_count = round(avg or 0, 1), n
        return out
