import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mallt.core.errors import Conflict
from mallt.modules.catalog.models import (
    MenuCategory,
    OptionGroup,
    Product,
    ProductVariant,
    StoreSettings,
)

_PRODUCT_LOAD = (
    selectinload(Product.variants),
    selectinload(Product.option_groups).selectinload(OptionGroup.options),
)


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- settings ----

    async def get_settings(self, store_id: uuid.UUID) -> StoreSettings | None:
        stmt = select(StoreSettings).where(StoreSettings.store_id == store_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def settings_for_stores(
        self, store_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, StoreSettings]:
        if not store_ids:
            return {}
        stmt = select(StoreSettings).where(StoreSettings.store_id.in_(store_ids))
        return {s.store_id: s for s in (await self.session.execute(stmt)).scalars()}

    async def add(self, obj: object) -> None:
        self.session.add(obj)
        await self.session.flush()

    # ---- categories ----

    async def add_category(self, category: MenuCategory) -> None:
        try:
            async with self.session.begin_nested():
                self.session.add(category)
                await self.session.flush()
        except IntegrityError as exc:
            raise Conflict("category_exists", "A category with that name already exists.") from exc

    async def list_categories(self, store_id: uuid.UUID) -> list[MenuCategory]:
        stmt = (
            select(MenuCategory)
            .where(MenuCategory.store_id == store_id)
            .order_by(MenuCategory.position, MenuCategory.id)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_category(
        self, store_id: uuid.UUID, category_id: uuid.UUID
    ) -> MenuCategory | None:
        stmt = select(MenuCategory).where(
            MenuCategory.store_id == store_id, MenuCategory.id == category_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def flush(self) -> None:
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError as exc:
            raise Conflict("category_exists", "A category with that name already exists.") from exc

    async def delete(self, obj: object) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    # ---- products ----

    async def list_products(
        self, store_id: uuid.UUID, *, include_archived: bool = False
    ) -> list[Product]:
        stmt = (
            select(Product)
            .where(Product.store_id == store_id)
            .options(*_PRODUCT_LOAD)
            .order_by(Product.position, Product.id)
            .limit(500)  # a store menu is small; this bounds a pathological one
        )
        if not include_archived:
            stmt = stmt.where(Product.is_archived.is_(False))
        return list((await self.session.execute(stmt)).scalars())

    async def get_product(self, store_id: uuid.UUID, product_id: uuid.UUID) -> Product | None:
        stmt = (
            select(Product)
            .where(
                Product.store_id == store_id,
                Product.id == product_id,
                Product.is_archived.is_(False),
            )
            .options(*_PRODUCT_LOAD)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def products_by_ids(
        self, mall_id: uuid.UUID, product_ids: list[uuid.UUID]
    ) -> list[Product]:
        if not product_ids:
            return []
        stmt = (
            select(Product)
            .where(Product.mall_id == mall_id, Product.id.in_(product_ids))
            .options(*_PRODUCT_LOAD)
            .execution_options(populate_existing=True)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def take_stock(self, variant_id: uuid.UUID, quantity: int) -> bool:
        """Atomically hold ``quantity`` units; False if there is not enough."""
        stmt = (
            update(ProductVariant)
            .where(ProductVariant.id == variant_id, ProductVariant.stock_count >= quantity)
            .values(stock_count=ProductVariant.stock_count - quantity)
        )
        result = await self.session.execute(stmt)
        return cast(CursorResult[Any], result).rowcount == 1

    async def return_stock(self, variant_id: uuid.UUID, quantity: int) -> None:
        stmt = (
            update(ProductVariant)
            .where(ProductVariant.id == variant_id, ProductVariant.stock_count.is_not(None))
            .values(stock_count=ProductVariant.stock_count + quantity)
        )
        await self.session.execute(stmt)

    async def search_products(
        self,
        store_ids: list[uuid.UUID],
        *,
        q: str | None,
        diet: str | None,
        after: uuid.UUID | None,
        limit: int,
    ) -> list[Product]:
        if not store_ids:
            return []
        stmt = (
            select(Product)
            .where(Product.store_id.in_(store_ids), Product.is_archived.is_(False))
            .options(*_PRODUCT_LOAD)
            .order_by(Product.id)
            .limit(limit)
        )
        if q:
            # Escaped so a customer typing % or _ searches for those characters, not a pattern.
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.where(
                Product.name.ilike(like, escape="\\") | Product.description.ilike(like, escape="\\")
            )
        if diet:
            stmt = stmt.where(Product.diet == diet)
        if after is not None:
            stmt = stmt.where(Product.id > after)
        return list((await self.session.execute(stmt)).scalars())
