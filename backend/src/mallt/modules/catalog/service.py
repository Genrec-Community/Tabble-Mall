import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActorType
from mallt.core.errors import BadRequest, Conflict, NotFound
from mallt.core.ids import uuid7
from mallt.core.kv import KV
from mallt.core.rbac import P, Scope
from mallt.core.storage import Storage
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.catalog.availability import in_hours, store_accepting
from mallt.modules.catalog.enums import StockMode
from mallt.modules.catalog.models import (
    MenuCategory,
    Option,
    OptionGroup,
    Product,
    ProductVariant,
    StoreSettings,
)
from mallt.modules.catalog.repository import CatalogRepository
from mallt.modules.catalog.schemas import (
    AvailabilityUpdate,
    CategoryCreate,
    CategoryUpdate,
    ImagePresignIn,
    ImagePresignOut,
    OptionGroupIn,
    ProductIn,
    PublicCategoryOut,
    PublicItemOut,
    PublicItemsOut,
    PublicMenuOut,
    PublicOptionGroupOut,
    PublicOptionOut,
    PublicProductOut,
    PublicStoreCardOut,
    PublicStoreOut,
    PublicVariantOut,
    SettingsOut,
    SettingsUpdate,
    theme_from,
)
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.tenancy.models import Store
from mallt.modules.tenancy.service import TenancyService

_PROFILE_FIELDS = {
    "hours",
    "timezone",
    "food_types",
    "gstin",
    "fssai",
    "auto_print",
    "kot_when",
    "bill_when",
}
_THEME_FIELDS = {"theme", "logo_key", "banner_key"}
_OPERATIONAL_FIELDS = {"is_open", "is_paused"}


def store_prefix(store: Store) -> str:
    return f"org/{store.organization_id}/store/{store.id}/"


class CatalogService:
    def __init__(self, session: AsyncSession, kv: KV, storage: Storage) -> None:
        self.repo = CatalogRepository(session)
        self.tenancy = TenancyService(session, kv)
        self.authz = AuthzService(session, kv)
        self.audit = AuditService(session)
        self.storage = storage

    # ---- access ----

    async def _store(
        self, principal: Principal, store_id: uuid.UUID, permission: P, *, write: bool = False
    ) -> tuple[Store, Scope]:
        store = await self.tenancy.get_store(principal, store_id)  # unseen tenants: 404
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        self.authz.require(principal, permission, scope)
        if write:
            await self.tenancy.assert_operational(principal, scope)
        return store, scope

    def _check_key(self, store: Store, key: str | None) -> None:
        if key is not None and not key.startswith(store_prefix(store)):
            raise BadRequest("bad_image_key", "That image does not belong to this store.")

    async def _record(
        self,
        principal: Principal,
        action: str,
        target: str,
        target_id: uuid.UUID,
        scope: Scope,
        after: dict[str, Any] | None = None,
    ) -> None:
        await self.audit.record(
            actor=Actor(ActorType.STAFF, principal.staff_id),
            action=action,
            target_type=target,
            target_id=target_id,
            scope=scope,
            before=None,
            after=after,
        )

    # ---- settings ----

    async def _settings(self, store: Store) -> StoreSettings:
        row = await self.repo.get_settings(store.id)
        if row is None:
            row = StoreSettings(
                organization_id=store.organization_id,
                mall_id=store.mall_id,
                store_id=store.id,
                hours=[],
                food_types=[],
                theme={},
            )
            await self.repo.add(row)
        return row

    def settings_out(self, row: StoreSettings) -> SettingsOut:
        out = SettingsOut.model_validate(
            {**{c: getattr(row, c) for c in SettingsOut.model_fields if hasattr(row, c)}}
            | {"theme": theme_from(row.theme)}
        )
        out.logo_url = self.storage.public_url(row.logo_key) if row.logo_key else None
        out.banner_url = self.storage.public_url(row.banner_key) if row.banner_key else None
        out.accepting_orders = store_accepting(
            row.is_open, row.is_paused, row.hours, row.timezone, datetime.now(UTC)
        )
        return out

    async def get_settings(self, principal: Principal, store_id: uuid.UUID) -> SettingsOut:
        store, _ = await self._store(principal, store_id, P.STORE_PRODUCT_READ)
        return self.settings_out(await self._settings(store))

    async def update_settings(
        self, principal: Principal, store_id: uuid.UUID, data: SettingsUpdate
    ) -> SettingsOut:
        changes = data.model_dump(exclude_unset=True)
        store = await self.tenancy.get_store(principal, store_id)
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        needs = {
            P.STORE_PROFILE_UPDATE: _PROFILE_FIELDS,
            P.STORE_THEME_UPDATE: _THEME_FIELDS,
            P.STORE_ORDER_UPDATE: _OPERATIONAL_FIELDS,
        }
        for permission, fields in needs.items():
            if changes.keys() & fields:
                self.authz.require(principal, permission, scope)
        if not changes:
            self.authz.require(principal, P.STORE_PRODUCT_READ, scope)
        await self.tenancy.assert_operational(principal, scope)
        row = await self._settings(store)
        if "logo_key" in changes:
            self._check_key(store, changes["logo_key"])
        if "banner_key" in changes:
            self._check_key(store, changes["banner_key"])
        for field, value in changes.items():
            if field == "theme" and value is not None:
                value = theme_from(value).model_dump()
            if field == "hours" and value is not None:
                value = [dict(w) for w in value]
            setattr(row, field, value)
        if changes:
            await self.repo.session.flush()
            await self._record(
                principal,
                "store.settings_updated",
                "store",
                store.id,
                scope,
                after={k: v for k, v in changes.items() if k != "theme"},
            )
        return self.settings_out(row)

    # ---- images ----

    async def presign(
        self, principal: Principal, store_id: uuid.UUID, data: ImagePresignIn
    ) -> ImagePresignOut:
        permission = P.STORE_PRODUCT_WRITE if data.kind == "product" else P.STORE_THEME_UPDATE
        store, _ = await self._store(principal, store_id, permission, write=True)
        ext = data.content_type.split("/")[1]
        key = f"{store_prefix(store)}{data.kind}/{uuid7()}.{ext}"
        up = self.storage.presign_put(key, data.content_type)
        return ImagePresignOut(
            url=up.url,
            key=up.key,
            headers=up.headers,
            expires_in=up.expires_in,
            public_url=self.storage.public_url(key),
        )

    # ---- categories ----

    async def list_categories(
        self, principal: Principal, store_id: uuid.UUID
    ) -> list[MenuCategory]:
        store, _ = await self._store(principal, store_id, P.STORE_PRODUCT_READ)
        return await self.repo.list_categories(store.id)

    async def create_category(
        self, principal: Principal, store_id: uuid.UUID, data: CategoryCreate
    ) -> MenuCategory:
        store, scope = await self._store(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        category = MenuCategory(
            organization_id=store.organization_id,
            mall_id=store.mall_id,
            store_id=store.id,
            name=data.name,
            position=data.position,
        )
        await self.repo.add_category(category)
        await self._record(
            principal, "category.created", "category", category.id, scope, {"name": category.name}
        )
        return category

    async def _category(self, store: Store, category_id: uuid.UUID) -> MenuCategory:
        category = await self.repo.get_category(store.id, category_id)
        if category is None:
            raise NotFound("not_found", "Not found.")
        return category

    async def update_category(
        self,
        principal: Principal,
        store_id: uuid.UUID,
        category_id: uuid.UUID,
        data: CategoryUpdate,
    ) -> MenuCategory:
        store, scope = await self._store(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        category = await self._category(store, category_id)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in changes.items():
            setattr(category, field, value)
        await self.repo.flush()
        await self._record(principal, "category.updated", "category", category.id, scope, changes)
        return category

    async def delete_category(
        self, principal: Principal, store_id: uuid.UUID, category_id: uuid.UUID
    ) -> None:
        store, scope = await self._store(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        category = await self._category(store, category_id)
        # Products keep existing (FK is SET NULL); make the in-session rows agree.
        for product in await self.repo.list_products(store.id):
            if product.category_id == category.id:
                product.category_id = None
        await self.repo.delete(category)
        await self._record(principal, "category.deleted", "category", category_id, scope)

    # ---- products ----

    async def _validate_product(self, store: Store, data: ProductIn) -> None:
        self._check_key(store, data.image_key)
        if (
            data.category_id is not None
            and await self.repo.get_category(store.id, data.category_id) is None
        ):
            raise BadRequest("unknown_category", "That category does not exist in this store.")
        if data.stock_mode == StockMode.COUNTED and any(
            v.stock_count is None for v in data.variants
        ):
            raise BadRequest(
                "stock_count_required", "Counted stock needs a count for every variant."
            )

    @staticmethod
    def _owned(store: Store) -> dict[str, uuid.UUID]:
        return {
            "organization_id": store.organization_id,
            "mall_id": store.mall_id,
            "store_id": store.id,
        }

    def _apply(self, product: Product, store: Store, data: ProductIn) -> None:
        product.name = data.name
        product.description = data.description
        product.category_id = data.category_id
        product.diet = data.diet
        product.allergens = data.allergens or None
        product.prep_minutes = data.prep_minutes
        product.tax_bps = data.tax_bps
        product.stock_mode = data.stock_mode
        product.image_key = data.image_key
        product.position = data.position
        product.windows = [w.model_dump() for w in data.windows]
        owned = self._owned(store)

        variants = {v.id: v for v in product.variants}
        seen: set[uuid.UUID] = set()
        for position, item in enumerate(data.variants):
            if item.id is not None:
                variant = variants.get(item.id)
                if variant is None:
                    raise BadRequest(
                        "unknown_variant", "That variant does not belong to this product."
                    )
            else:
                variant = ProductVariant(**owned)
                product.variants.append(variant)
            variant.name, variant.price_paise, variant.position = (
                item.name,
                item.price_paise,
                position,
            )
            variant.stock_count = item.stock_count if data.stock_mode == StockMode.COUNTED else None
            variant.is_active = True
            if item.id is not None:
                seen.add(item.id)
        for vid, variant in variants.items():
            if vid not in seen:
                variant.is_active = False  # carts and past orders may still reference it

        groups = {g.id: g for g in product.option_groups}
        kept: set[uuid.UUID] = set()
        for position, g_in in enumerate(data.option_groups):
            group = self._group(product, groups, g_in, owned, position)
            if g_in.id is not None:
                kept.add(g_in.id)
            options = {o.id: o for o in group.options}
            o_kept: set[uuid.UUID] = set()
            for o_pos, o_in in enumerate(g_in.options):
                if o_in.id is not None:
                    option = options.get(o_in.id)
                    if option is None:
                        raise BadRequest(
                            "unknown_option", "That option does not belong to this group."
                        )
                    o_kept.add(o_in.id)
                else:
                    option = Option(**owned)
                    group.options.append(option)
                option.name, option.position = o_in.name, o_pos
                option.price_delta_paise, option.is_available = (
                    o_in.price_delta_paise,
                    o_in.is_available,
                )
            for oid, option in options.items():
                if oid not in o_kept:
                    group.options.remove(option)
        for gid, group in groups.items():
            if gid not in kept:
                product.option_groups.remove(group)

    @staticmethod
    def _group(
        product: Product,
        groups: dict[uuid.UUID, OptionGroup],
        item: OptionGroupIn,
        owned: dict[str, uuid.UUID],
        position: int,
    ) -> OptionGroup:
        if item.id is not None:
            group = groups.get(item.id)
            if group is None:
                raise BadRequest(
                    "unknown_option_group", "That group does not belong to this product."
                )
        else:
            group = OptionGroup(**owned)
            group.options = []
            product.option_groups.append(group)
        group.name, group.min_select, group.max_select = item.name, item.min_select, item.max_select
        group.position = position
        return group

    def product_out(self, product: Product) -> dict[str, Any]:
        out = {
            c: getattr(product, c)
            for c in (
                "id",
                "store_id",
                "category_id",
                "name",
                "description",
                "diet",
                "allergens",
                "prep_minutes",
                "tax_bps",
                "stock_mode",
                "is_available",
                "image_key",
                "position",
                "windows",
            )
        }
        out["image_url"] = self.storage.public_url(product.image_key) if product.image_key else None
        out["variants"] = [v for v in product.variants if v.is_active]
        out["option_groups"] = product.option_groups
        return out

    async def list_products(
        self, principal: Principal, store_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        store, _ = await self._store(principal, store_id, P.STORE_PRODUCT_READ)
        return [self.product_out(p) for p in await self.repo.list_products(store.id)]

    async def _product(self, store: Store, product_id: uuid.UUID) -> Product:
        product = await self.repo.get_product(store.id, product_id)
        if product is None:
            raise NotFound("not_found", "Not found.")
        return product

    async def get_product(
        self, principal: Principal, store_id: uuid.UUID, product_id: uuid.UUID
    ) -> dict[str, Any]:
        store, _ = await self._store(principal, store_id, P.STORE_PRODUCT_READ)
        return self.product_out(await self._product(store, product_id))

    async def create_product(
        self, principal: Principal, store_id: uuid.UUID, data: ProductIn
    ) -> dict[str, Any]:
        store, scope = await self._store(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        await self._validate_product(store, data)
        product = Product(**self._owned(store))
        product.variants, product.option_groups = [], []
        self._apply(product, store, data)
        await self.repo.add(product)
        await self._record(
            principal, "product.created", "product", product.id, scope, {"name": product.name}
        )
        return self.product_out(await self._product(store, product.id))

    async def update_product(
        self, principal: Principal, store_id: uuid.UUID, product_id: uuid.UUID, data: ProductIn
    ) -> dict[str, Any]:
        store, scope = await self._store(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        product = await self._product(store, product_id)
        await self._validate_product(store, data)
        self._apply(product, store, data)
        await self.repo.session.flush()
        await self._record(
            principal, "product.updated", "product", product.id, scope, {"name": product.name}
        )
        self.repo.session.expire(product)
        return self.product_out(await self._product(store, product_id))

    async def archive_product(
        self, principal: Principal, store_id: uuid.UUID, product_id: uuid.UUID
    ) -> None:
        store, scope = await self._store(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        product = await self._product(store, product_id)
        product.is_archived = True
        await self.repo.session.flush()
        await self._record(principal, "product.archived", "product", product.id, scope)

    async def set_availability(
        self,
        principal: Principal,
        store_id: uuid.UUID,
        product_id: uuid.UUID,
        data: AvailabilityUpdate,
    ) -> dict[str, Any]:
        store, scope = await self._store(principal, store_id, P.STORE_STOCK_UPDATE, write=True)
        product = await self._product(store, product_id)
        if data.is_available is not None:
            product.is_available = data.is_available
        if data.variants:
            by_id = {v.id: v for v in product.variants}
            for item in data.variants:
                variant = by_id.get(item.id)
                if variant is None or product.stock_mode != StockMode.COUNTED:
                    raise BadRequest("unknown_variant", "Cannot set stock for that variant.")
                variant.stock_count = item.stock_count
        await self.repo.session.flush()
        await self._record(
            principal,
            "product.availability",
            "product",
            product.id,
            scope,
            data.model_dump(mode="json", exclude_unset=True),
        )
        return self.product_out(product)

    # ---- public (customer) ----

    async def public_cards(self, mall_slug: str) -> list[PublicStoreCardOut]:
        _, stores = await self.tenancy.public_directory(mall_slug)
        settings = await self.repo.settings_for_stores([s.id for s in stores])
        now = datetime.now(UTC)
        cards = []
        for store in stores:
            row = settings.get(store.id)
            cards.append(
                PublicStoreCardOut(
                    slug=store.slug,
                    name=store.name,
                    description=store.description,
                    food_types=row.food_types if row else [],
                    logo_url=self.storage.public_url(row.logo_key)
                    if row and row.logo_key
                    else None,
                    accepting_orders=store_accepting(
                        row.is_open, row.is_paused, row.hours, row.timezone, now
                    )
                    if row
                    else True,
                )
            )
        return cards

    async def public_items(
        self,
        mall_slug: str,
        *,
        q: str | None,
        diet: str | None,
        food_type: str | None,
        store: str | None,
        after: uuid.UUID | None,
        limit: int,
    ) -> PublicItemsOut:
        """Dishes from every open store of a mall, for the mall home page (search and filters)."""
        _, stores = await self.tenancy.public_directory(mall_slug)
        settings = await self.repo.settings_for_stores([s.id for s in stores])
        now = datetime.now(UTC)
        wanted = [
            s
            for s in stores
            if (store is None or s.slug == store)
            and (food_type is None or (s.id in settings and food_type in settings[s.id].food_types))
        ]
        by_id = {s.id: s for s in wanted}
        rows = await self.repo.search_products(
            list(by_id), q=q, diet=diet, after=after, limit=limit + 1
        )
        page = rows[:limit]
        items: list[PublicItemOut] = []
        for product in page:
            st = by_id[product.store_id]
            row = settings.get(st.id)
            tz = ZoneInfo(row.timezone if row else "Asia/Kolkata")
            accepting = (
                store_accepting(row.is_open, row.is_paused, row.hours, row.timezone, now)
                if row
                else True
            )
            items.append(
                PublicItemOut(
                    store_slug=st.slug,
                    store_name=st.name,
                    accepting_orders=accepting,
                    product=self._public_product(product, now.astimezone(tz)),
                )
            )
        return PublicItemsOut(items=items, next_cursor=page[-1].id if len(rows) > limit else None)

    async def public_menu(self, mall_slug: str, store_slug: str) -> PublicMenuOut:
        _, stores = await self.tenancy.public_directory(mall_slug)
        store = next((s for s in stores if s.slug == store_slug), None)
        if store is None:
            raise NotFound("not_found", "Not found.")
        row = await self._settings(store)
        now = datetime.now(UTC)
        accepting = store_accepting(row.is_open, row.is_paused, row.hours, row.timezone, now)
        local_now = now.astimezone(ZoneInfo(row.timezone))
        categories = {c.id: c for c in await self.repo.list_categories(store.id)}
        grouped: dict[uuid.UUID | None, list[PublicProductOut]] = {}
        for product in await self.repo.list_products(store.id):
            grouped.setdefault(product.category_id, []).append(
                self._public_product(product, local_now)
            )
        out: list[PublicCategoryOut] = [
            PublicCategoryOut(id=cid, name=categories[cid].name, products=grouped[cid])
            for cid in categories
            if cid in grouped
        ]
        if None in grouped:
            out.append(PublicCategoryOut(id=None, name="Others", products=grouped[None]))
        return PublicMenuOut(
            store=PublicStoreOut(
                slug=store.slug,
                name=store.name,
                description=store.description,
                food_types=row.food_types,
                theme=theme_from(row.theme),
                accepting_orders=accepting,
                hours=row.hours,
                logo_url=self.storage.public_url(row.logo_key) if row.logo_key else None,
                banner_url=self.storage.public_url(row.banner_key) if row.banner_key else None,
            ),
            categories=out,
        )

    def _public_product(self, product: Product, local_now: datetime) -> PublicProductOut:
        counted = product.stock_mode == StockMode.COUNTED
        variants = [v for v in product.variants if v.is_active]
        reason: str | None = None
        if not product.is_available or (
            counted and all((v.stock_count or 0) <= 0 for v in variants)
        ):
            reason = "sold_out"
        elif not in_hours(product.windows, local_now, "start", "end"):
            reason = "not_now"
        return PublicProductOut(
            id=product.id,
            name=product.name,
            description=product.description,
            diet=product.diet,
            allergens=product.allergens,
            prep_minutes=product.prep_minutes,
            image_url=self.storage.public_url(product.image_key) if product.image_key else None,
            available=reason is None,
            unavailable_reason=reason,
            variants=[
                PublicVariantOut(
                    id=v.id,
                    name=v.name,
                    price_paise=v.price_paise,
                    available=not counted or (v.stock_count or 0) > 0,
                )
                for v in variants
            ],
            option_groups=[
                PublicOptionGroupOut(
                    id=g.id,
                    name=g.name,
                    min_select=g.min_select,
                    max_select=g.max_select,
                    options=[
                        PublicOptionOut(
                            id=o.id,
                            name=o.name,
                            price_delta_paise=o.price_delta_paise,
                            available=o.is_available,
                        )
                        for o in g.options
                    ],
                )
                for g in product.option_groups
            ],
        )


# ---- what the ordering module may know about the menu (a read-only, priced snapshot) ----


@dataclass(frozen=True)
class OrderableOption:
    id: uuid.UUID
    name: str
    price_delta_paise: int
    available: bool


@dataclass(frozen=True)
class OrderableGroup:
    id: uuid.UUID
    name: str
    min_select: int
    max_select: int
    options: dict[uuid.UUID, OrderableOption]


@dataclass(frozen=True)
class OrderableVariant:
    id: uuid.UUID
    name: str
    price_paise: int
    stock_count: int | None


@dataclass(frozen=True)
class OrderableStore:
    id: uuid.UUID
    organization_id: uuid.UUID
    mall_id: uuid.UUID
    slug: str
    name: str
    timezone: str
    accepting: bool
    commission_bps: int | None
    gstin: str | None


@dataclass(frozen=True)
class OrderableMall:
    id: uuid.UUID
    organization_id: uuid.UUID
    slug: str
    stores: dict[uuid.UUID, OrderableStore]


@dataclass(frozen=True)
class OrderableProduct:
    id: uuid.UUID
    store: OrderableStore
    name: str
    diet: str
    allergens: str | None
    prep_minutes: int
    tax_bps: int
    counted: bool
    available_now: bool  # not archived, switched on, inside its time window
    variants: dict[uuid.UUID, OrderableVariant]  # active variants only
    groups: dict[uuid.UUID, OrderableGroup]


class OrderingCatalog:
    """The only door the ordering module uses to read the menu or hold stock."""

    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.repo = CatalogRepository(session)
        self.tenancy = TenancyService(session, kv)

    async def mall_stores(self, mall_slug: str) -> "OrderableMall":
        """The active mall and its active stores (404 for unknown or suspended)."""
        mall, stores = await self.tenancy.public_directory(mall_slug)
        settings = await self.repo.settings_for_stores([s.id for s in stores])
        now = datetime.now(UTC)
        out: dict[uuid.UUID, OrderableStore] = {}
        for s in stores:
            row = settings.get(s.id)
            out[s.id] = OrderableStore(
                id=s.id,
                organization_id=s.organization_id,
                mall_id=s.mall_id,
                slug=s.slug,
                name=s.name,
                timezone=row.timezone if row else "Asia/Kolkata",
                accepting=store_accepting(row.is_open, row.is_paused, row.hours, row.timezone, now)
                if row
                else True,
                commission_bps=s.commission_bps,
                gstin=row.gstin if row else None,
            )
        return OrderableMall(mall.id, mall.organization_id, mall.slug, out)

    async def products(
        self,
        mall_id: uuid.UUID,
        stores: dict[uuid.UUID, OrderableStore],
        product_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, OrderableProduct]:
        now = datetime.now(UTC)
        out: dict[uuid.UUID, OrderableProduct] = {}
        for p in await self.repo.products_by_ids(mall_id, product_ids):
            store = stores.get(p.store_id)
            if store is None:
                continue
            local = now.astimezone(ZoneInfo(store.timezone))
            out[p.id] = OrderableProduct(
                id=p.id,
                store=store,
                name=p.name,
                diet=p.diet.value,
                allergens=p.allergens,
                prep_minutes=p.prep_minutes,
                tax_bps=p.tax_bps,
                counted=p.stock_mode == StockMode.COUNTED,
                available_now=(
                    not p.is_archived
                    and p.is_available
                    and in_hours(p.windows, local, "start", "end")
                ),
                variants={
                    v.id: OrderableVariant(v.id, v.name, v.price_paise, v.stock_count)
                    for v in p.variants
                    if v.is_active
                },
                groups={
                    g.id: OrderableGroup(
                        g.id,
                        g.name,
                        g.min_select,
                        g.max_select,
                        {
                            o.id: OrderableOption(o.id, o.name, o.price_delta_paise, o.is_available)
                            for o in g.options
                        },
                    )
                    for g in p.option_groups
                },
            )
        return out

    async def take_stock(self, holds: dict[uuid.UUID, int]) -> None:
        """Hold counted stock for several variants at once; all or nothing (caller rolls back)."""
        for variant_id in sorted(holds):  # fixed order so two checkouts cannot deadlock
            if not await self.repo.take_stock(variant_id, holds[variant_id]):
                raise Conflict("out_of_stock", "An item just sold out.")

    async def return_stock(self, holds: dict[uuid.UUID, int]) -> None:
        for variant_id in sorted(holds):
            await self.repo.return_stock(variant_id, holds[variant_id])


@dataclass(frozen=True)
class StorePrintPrefs:
    auto_print: bool
    kot_when: str
    bill_when: str
    gstin: str | None
    fssai: str | None
    timezone: str


async def print_prefs(session: AsyncSession, store_id: uuid.UUID) -> StorePrintPrefs:
    """A store's printing preferences (defaults when it never saved settings)."""
    row = await CatalogRepository(session).get_settings(store_id)
    if row is None:
        return StorePrintPrefs(True, "accepted", "ready", None, None, "Asia/Kolkata")
    return StorePrintPrefs(
        row.auto_print, row.kot_when, row.bill_when, row.gstin, row.fssai, row.timezone
    )
