"""What's popular in a mall: ranked from paid orders, shown through the catalog."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.kv import KV
from mallt.core.storage import Storage
from mallt.modules.catalog.schemas import PopularOut
from mallt.modules.catalog.service import CatalogService, OrderingCatalog
from mallt.modules.orders.repository import OrdersRepository

POPULAR_WINDOW = timedelta(days=30)


class DiscoveryService:
    def __init__(self, session: AsyncSession, kv: KV, storage: Storage) -> None:
        self.repo = OrdersRepository(session)
        self.ordering = OrderingCatalog(session, kv)
        self.catalog = CatalogService(session, kv, storage)

    async def popular(self, mall_slug: str, limit: int) -> PopularOut:
        mall = await self.ordering.mall_stores(mall_slug)  # 404 for unknown or suspended
        counts = await self.repo.popular_products(
            mall.id, datetime.now(UTC) - POPULAR_WINDOW, limit * 2
        )
        return await self.catalog.public_items_by_ids(mall_slug, counts, fill_to=limit)
