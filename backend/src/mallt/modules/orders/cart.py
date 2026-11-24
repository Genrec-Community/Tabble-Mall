import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.errors import BadRequest, Conflict, NotFound
from mallt.core.ids import uuid7
from mallt.core.kv import KV
from mallt.modules.catalog.service import (
    OrderableMall,
    OrderableOption,
    OrderableProduct,
    OrderableVariant,
    OrderingCatalog,
)
from mallt.modules.offers.pricing import Quote, QuoteLine
from mallt.modules.offers.service import OffersService
from mallt.modules.orders import schedule
from mallt.modules.orders.models import Cart, CartLine, GroupOrder
from mallt.modules.orders.repository import OrdersRepository
from mallt.modules.orders.schemas import (
    CartGroupOut,
    CartLineIn,
    CartLineOut,
    CartLineUpdate,
    CartOut,
    CartStoreOut,
    CouponOut,
    DiscountOut,
    LineProblem,
    PickupSlotsOut,
    ReorderOut,
)
from mallt.modules.platform.service import FeatureService


def group_live(group: GroupOrder, now: datetime | None = None) -> bool:
    return group.expires_at > (now or datetime.now(UTC))


MAX_LINE_QUANTITY = 20
MAX_CART_LINES = 50


@dataclass(frozen=True)
class PricedLine:
    line: CartLine
    product: OrderableProduct | None
    variant: OrderableVariant | None
    options: list[OrderableOption]
    unit_price_paise: int
    problem: LineProblem | None

    @property
    def total_paise(self) -> int:
        return self.unit_price_paise * self.line.quantity


def _problem(
    product: OrderableProduct | None,
    variant: OrderableVariant | None,
    options: list[OrderableOption],
    option_ids: list[str],
    quantity: int,
) -> LineProblem | None:
    if product is None or variant is None or len(options) != len(option_ids):
        return "unavailable"
    if not product.store.accepting:
        return "store_closed"
    if not product.available_now or not all(o.available for o in options):
        return "unavailable"
    if product.counted and (variant.stock_count or 0) < quantity:
        return "sold_out"
    return None


class CartService:
    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.session = session
        self.repo = OrdersRepository(session)
        self.catalog = OrderingCatalog(session, kv)
        self.offers = OffersService(session, kv)
        self.features = FeatureService(session)

    async def mall(self, mall_slug: str) -> OrderableMall:
        return await self.catalog.mall_stores(mall_slug)

    async def _cart(self, customer_id: uuid.UUID, mall: OrderableMall) -> Cart:
        cart = await self.repo.get_cart(customer_id, mall.id)
        if cart is None:
            cart = await self.repo.create_cart(
                Cart(
                    id=uuid7(),
                    customer_id=customer_id,
                    organization_id=mall.organization_id,
                    mall_id=mall.id,
                )
            )
        return cart

    async def priced(self, cart: Cart, mall: OrderableMall) -> list[PricedLine]:
        products = await self.catalog.products(
            mall.id, mall.stores, list({line.product_id for line in cart.lines})
        )
        out: list[PricedLine] = []
        for line in cart.lines:
            product = products.get(line.product_id)
            variant = product.variants.get(line.variant_id) if product else None
            chosen: list[OrderableOption] = []
            if product:
                by_id = {o.id: o for g in product.groups.values() for o in g.options.values()}
                chosen = [by_id[uuid.UUID(i)] for i in line.option_ids if uuid.UUID(i) in by_id]
            unit = (variant.price_paise if variant else 0) + sum(
                o.price_delta_paise for o in chosen
            )
            problem = _problem(product, variant, chosen, line.option_ids, line.quantity)
            out.append(PricedLine(line, product, variant, chosen, unit, problem))
        return out

    async def view(self, customer_id: uuid.UUID, mall_slug: str) -> CartOut:
        mall = await self.mall(mall_slug)
        cart = await self.repo.get_cart(customer_id, mall.id)
        if cart is None:
            return await self._view(mall, [], None)
        return await self._view(mall, await self.priced(cart, mall), cart)

    async def quote(self, cart: Cart, mall: OrderableMall, priced: list[PricedLine]) -> Quote:
        """The cart's offers and combos. Lines with a problem are left out of the sums."""
        lines = [
            QuoteLine(p.line.store_id, p.line.product_id, p.line.quantity, p.unit_price_paise)
            for p in priced
            if p.problem is None
        ]
        customer_id = cart.customer_id

        async def uses(offer_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
            return await self.repo.offer_uses(customer_id, offer_ids)

        return await self.offers.quote(
            mall,
            lines,
            code=cart.coupon_code,
            uses=uses,
            enabled=await self.features.is_enabled("offers"),
        )

    async def _view(
        self, mall: OrderableMall, priced: list[PricedLine], cart: Cart | None
    ) -> CartOut:
        q = await self.quote(cart, mall, priced) if cart is not None else None
        grouped: dict[uuid.UUID, list[PricedLine]] = {}
        for p in priced:
            grouped.setdefault(p.line.store_id, []).append(p)
        stores: list[CartStoreOut] = []
        for store_id, rows in grouped.items():
            store = mall.stores.get(store_id)
            if store is None:
                continue
            lines = [
                CartLineOut(
                    id=r.line.id,
                    product_id=r.line.product_id,
                    product_name=r.product.name if r.product else "Unavailable item",
                    variant_name=r.variant.name if r.variant else "",
                    diet=r.product.diet if r.product else "veg",
                    options=[o.name for o in r.options],
                    quantity=r.line.quantity,
                    unit_price_paise=r.unit_price_paise,
                    line_total_paise=r.total_paise,
                    note=r.line.note,
                    problem=r.problem,
                )
                for r in rows
            ]
            sq = q.stores.get(store_id) if q else None
            subtotal = sum(x.line_total_paise for x in lines)
            discount = sq.discount_paise if sq else 0
            stores.append(
                CartStoreOut(
                    store_slug=store.slug,
                    store_name=store.name,
                    accepting_orders=store.accepting,
                    subtotal_paise=subtotal,
                    discount_paise=discount,
                    total_paise=subtotal - discount,
                    discounts=[
                        DiscountOut(kind=d.kind, name=d.name, amount_paise=d.amount_paise)
                        for d in (sq.discounts if sq else [])
                    ],
                    prep_minutes=max(
                        (r.product.prep_minutes for r in rows if r.product), default=0
                    ),
                    lines=lines,
                )
            )
        stores.sort(key=lambda s: s.store_name)
        coupon = None
        if q is not None and q.coupon_code and q.coupon_status != "none":
            coupon = CouponOut(
                code=q.coupon_code,
                status=q.coupon_status,
                message=q.coupon_message,
            )
        return CartOut(
            mall_slug=mall.slug,
            stores=stores,
            items_total_paise=sum(s.subtotal_paise for s in stores),
            discount_paise=sum(s.discount_paise for s in stores),
            total_paise=sum(s.total_paise for s in stores),
            can_checkout=bool(stores) and all(x.problem is None for s in stores for x in s.lines),
            coupon=coupon,
            group=await self.group_view(cart) if cart is not None else None,
        )

    async def group_view(self, cart: Cart) -> CartGroupOut | None:
        """The group this cart belongs to, while that group still runs."""
        if cart.group_order_id is None:
            return None
        group = await self.repo.group(cart.group_order_id)
        if group is None or not group_live(group):
            return None
        return CartGroupOut(
            id=group.id,
            token=group.token,
            name=group.name,
            is_host=group.host_customer_id == cart.customer_id,
        )

    async def mall_by_id(self, mall_id: uuid.UUID) -> OrderableMall | None:
        slugs = await self.catalog.tenancy.mall_slugs([mall_id])
        if mall_id not in slugs:
            return None
        try:
            return await self.mall(slugs[mall_id])
        except NotFound:
            return None

    async def pickup_slots(self, customer_id: uuid.UUID, mall_slug: str) -> PickupSlotsOut:
        mall = await self.mall(mall_slug)
        cart = await self.repo.get_cart(customer_id, mall.id)
        priced = await self.priced(cart, mall) if cart else []
        prep = max((p.product.prep_minutes for p in priced if p.product), default=10)
        enabled = await self.features.is_enabled("schedule_ahead")
        stores = [mall.stores[s] for s in {p.line.store_id for p in priced} if s in mall.stores]
        return PickupSlotsOut(
            enabled=enabled,
            asap_minutes=prep,
            slots=schedule.slots(datetime.now(UTC), prep, stores) if enabled and stores else [],
        )

    async def set_coupon(self, customer_id: uuid.UUID, mall_slug: str, code: str | None) -> CartOut:
        mall = await self.mall(mall_slug)
        cart = await self._cart(customer_id, mall)
        cart.coupon_code = code.strip().upper() if code else None
        await self.session.flush()
        return await self._view(mall, await self.priced(cart, mall), cart)

    async def reorder(
        self, customer_id: uuid.UUID, mall_slug: str, order_id: uuid.UUID
    ) -> ReorderOut:
        """Puts a past order's dishes back in the cart, with the same sizes, add-ons and notes.
        Add-ons are matched by name (an order keeps a snapshot, not ids). Whatever can't be
        ordered now is skipped and named, never an error for the whole order."""
        mall = await self.mall(mall_slug)
        order = await self.repo.customer_order(customer_id, order_id)
        if order is None or order.mall_id != mall.id:
            raise NotFound("not_found", "Not found.")
        lines = [ln for so in order.store_orders for ln in so.lines]
        products = await self.catalog.products(
            mall.id, mall.stores, [ln.product_id for ln in lines if ln.product_id]
        )
        added, skipped = 0, []
        for ln in lines:
            product = products.get(ln.product_id) if ln.product_id else None
            names = [str(o.get("name")) for o in ln.options]
            by_name = {
                o.name: o.id
                for g in (product.groups.values() if product else [])
                for o in g.options.values()
            }
            if product is None or ln.variant_id is None or any(n not in by_name for n in names):
                skipped.append(ln.name)
                continue
            data = CartLineIn(
                product_id=product.id,
                variant_id=ln.variant_id,
                option_ids=[by_name[n] for n in names],
                quantity=min(ln.quantity, MAX_LINE_QUANTITY),
                note=ln.note,
            )
            try:
                await self.add_line(customer_id, mall_slug, data)
            except (BadRequest, Conflict, NotFound):
                skipped.append(ln.name)
            else:
                added += 1
        return ReorderOut(
            cart=await self.view(customer_id, mall_slug), added=added, skipped=skipped
        )

    async def add_line(self, customer_id: uuid.UUID, mall_slug: str, data: CartLineIn) -> CartOut:
        mall = await self.mall(mall_slug)
        products = await self.catalog.products(mall.id, mall.stores, [data.product_id])
        product = products.get(data.product_id)
        if product is None:
            raise NotFound("not_found", "Not found.")
        variant = product.variants.get(data.variant_id)
        if variant is None:
            raise BadRequest("unknown_variant", "That size does not exist for this item.")
        option_ids = [str(i) for i in data.option_ids]
        chosen = self._validate_options(product, data)
        problem = _problem(product, variant, chosen, option_ids, data.quantity)
        if problem == "unavailable":
            raise Conflict("unavailable", "That item is not available right now.")
        if problem == "store_closed":
            raise Conflict("store_closed", "This store is not taking orders right now.")
        if problem == "sold_out":
            raise Conflict("sold_out", "That item is sold out.")

        cart = await self._cart(customer_id, mall)
        key = sorted(option_ids)
        for existing in cart.lines:
            if (
                existing.product_id == data.product_id
                and existing.variant_id == data.variant_id
                and sorted(existing.option_ids) == key
                and (existing.note or None) == (data.note or None)
            ):
                merged = existing.quantity + data.quantity
                if merged > MAX_LINE_QUANTITY:
                    raise BadRequest("quantity_too_high", "You can order at most 20 of an item.")
                existing.quantity = merged
                break
        else:
            if len(cart.lines) >= MAX_CART_LINES:
                raise BadRequest("cart_full", "Your cart is full. Remove something first.")
            cart.lines.append(
                CartLine(
                    store_id=product.store.id,
                    product_id=data.product_id,
                    variant_id=data.variant_id,
                    option_ids=option_ids,
                    quantity=data.quantity,
                    note=data.note or None,
                )
            )
        await self.session.flush()
        return await self._view(mall, await self.priced(cart, mall), cart)

    @staticmethod
    def _validate_options(product: OrderableProduct, data: CartLineIn) -> list[OrderableOption]:
        ids = data.option_ids
        if len(set(ids)) != len(ids):
            raise BadRequest("duplicate_option", "Each add-on can be picked once.")
        chosen: list[OrderableOption] = []
        per_group: dict[uuid.UUID, int] = {}
        for oid in ids:
            for group in product.groups.values():
                if oid in group.options:
                    chosen.append(group.options[oid])
                    per_group[group.id] = per_group.get(group.id, 0) + 1
                    break
            else:
                raise BadRequest("unknown_option", "That add-on does not exist for this item.")
        for group in product.groups.values():
            n = per_group.get(group.id, 0)
            if n < group.min_select:
                raise BadRequest("option_required", f"Choose an option for {group.name}.")
            if n > group.max_select:
                raise BadRequest("too_many_options", f"Too many choices for {group.name}.")
        return chosen

    async def update_line(
        self, customer_id: uuid.UUID, mall_slug: str, line_id: uuid.UUID, data: CartLineUpdate
    ) -> CartOut:
        mall = await self.mall(mall_slug)
        line = await self.repo.get_line(customer_id, line_id)
        cart = await self.repo.get_cart(customer_id, mall.id)
        if line is None or cart is None or line.cart_id != cart.id:
            raise NotFound("not_found", "Not found.")
        fields = data.model_fields_set
        if "quantity" in fields and data.quantity is not None:
            if data.quantity == 0:
                cart.lines.remove(next(x for x in cart.lines if x.id == line.id))
            else:
                line.quantity = data.quantity
        if "note" in fields:
            line.note = data.note or None
        await self.session.flush()
        return await self._view(mall, await self.priced(cart, mall), cart)

    async def clear(self, customer_id: uuid.UUID, mall_slug: str) -> None:
        mall = await self.mall(mall_slug)
        cart = await self.repo.get_cart(customer_id, mall.id)
        if cart is not None:
            cart.lines.clear()
            await self.session.flush()
