import asyncio
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.bus import Bus
from mallt.core.db import defer_after_commit, run_after_commit
from mallt.core.enums import ActorType
from mallt.core.errors import AppError, BadRequest, Conflict, NotFound
from mallt.core.ids import uuid7
from mallt.core.kv import KV
from mallt.core.pagination import Page
from mallt.core.ratelimit import hit
from mallt.core.rbac import P, Scope
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.iam.users import IamCustomers
from mallt.modules.orders.cart import CartService, PricedLine
from mallt.modules.orders.enums import CustomerOrderStatus, StoreOrderStatus
from mallt.modules.orders.models import (
    CustomerOrder,
    OrderEvent,
    Payment,
    StoreOrder,
    StoreOrderLine,
)
from mallt.modules.orders.pricing import commission, tax_included
from mallt.modules.orders.repository import OrdersRepository
from mallt.modules.orders.schemas import (
    CustomerOrderOut,
    CustomerStoreOrderOut,
    OrderLineOut,
    OrderStepOut,
    StoreOrderOut,
)
from mallt.modules.orders.state import CUSTOMER_CANCELLABLE, REFUND_STATES, can_transition
from mallt.modules.payments.provider import PaymentProvider
from mallt.modules.printing.service import PrintingService
from mallt.modules.printing.types import PrintableLine, PrintableOrder
from mallt.modules.tenancy.service import TenancyService

S = StoreOrderStatus
log = logging.getLogger(__name__)

PRINT_TRIGGERS = frozenset({S.PAID, S.ACCEPTED, S.READY, S.PICKED_UP})
PICKUP_ATTEMPTS_PER_ORDER = (5, 600)  # tries, per seconds
PICKUP_ATTEMPTS_PER_STORE = (60, 600)


class PaymentFailed(AppError):
    status, default_code, default_title = 402, "payment_failed", "Payment Failed"


class OrderService:
    def __init__(self, session: AsyncSession, kv: KV, bus: Bus, payments: PaymentProvider) -> None:
        self.session = session
        self.kv = kv
        self.bus = bus
        self.payments = payments
        self.repo = OrdersRepository(session)
        self.cart = CartService(session, kv)
        self.catalog = self.cart.catalog
        self.tenancy = TenancyService(session, kv)
        self.authz = AuthzService(session, kv)
        self.customers = IamCustomers(session)
        self.printing = PrintingService(session, kv)
        self._store_names: dict[uuid.UUID, str] = {}

    # ------------------------------------------------------------------ state machine

    def _announce(self, order: StoreOrder, kind: str) -> None:
        message = {
            "type": kind,
            "store_order_id": str(order.id),
            "store_id": str(order.store_id),
            "status": order.status.value,
            "order_no": order.order_no,
        }
        bus, store_ch, cust_ch = (
            self.bus,
            f"store:{order.store_id}",
            f"customer:{order.customer_id}",
        )

        async def publish() -> None:
            await bus.publish(store_ch, message)
            await bus.publish(cust_ch, message)

        defer_after_commit(self.session, publish)

    async def _transition(
        self,
        order: StoreOrder,
        to: StoreOrderStatus,
        actor: ActorType,
        actor_id: uuid.UUID | None,
        reason: str | None = None,
    ) -> None:
        """The only place a store order's status changes."""
        if not can_transition(order.status, to):
            raise Conflict(
                "invalid_transition",
                f"An order that is {order.status.value} cannot become {to.value}.",
            )
        previous, now = order.status, datetime.now(UTC)
        order.status = to
        if reason:
            order.reason = reason
        if to is S.ACCEPTED:
            order.accepted_at = now
        elif to is S.READY:
            order.ready_at = now
        elif to is S.PICKED_UP:
            order.picked_up_at = now
        self.session.add(
            OrderEvent(
                store_order_id=order.id,
                store_id=order.store_id,
                from_status=previous,
                to_status=to,
                actor_type=actor,
                actor_id=actor_id,
                reason=reason,
            )
        )
        await self.session.flush()
        self._announce(order, "order.created" if to is S.PAID else "order.updated")
        if to in PRINT_TRIGGERS:
            await self.printing.on_order_status(await self._printable(order), to.value)
        if to in REFUND_STATES:
            await self._release_stock(order)
            result = await self.payments.refund(
                amount_paise=order.total_paise, reference=str(order.id)
            )
            self.session.add(
                Payment(
                    customer_order_id=order.customer_order_id,
                    store_order_id=order.id,
                    provider=self.payments.name,
                    provider_ref=result.provider_ref,
                    amount_paise=order.total_paise,
                    kind="refund",
                )
            )
            await self._transition(order, S.REFUNDED, ActorType.SYSTEM, None)

    async def _printable(self, order: StoreOrder) -> PrintableOrder:
        if order.store_id not in self._store_names:
            stores = await self.tenancy.stores_by_ids([order.store_id])
            self._store_names[order.store_id] = stores[order.store_id].name
        return PrintableOrder(
            id=order.id,
            organization_id=order.organization_id,
            mall_id=order.mall_id,
            store_id=order.store_id,
            store_name=self._store_names[order.store_id],
            order_no=order.order_no,
            order_date=order.order_date,
            created_at=order.created_at or datetime.now(UTC),
            customer_name=order.customer_name,
            prep_minutes=order.prep_minutes,
            note=order.note,
            subtotal_paise=order.subtotal_paise,
            tax_paise=order.tax_paise,
            total_paise=order.total_paise,
            lines=[
                PrintableLine(
                    name=ln.name,
                    variant_name=ln.variant_name,
                    quantity=ln.quantity,
                    unit_price_paise=ln.unit_price_paise,
                    line_total_paise=ln.line_total_paise,
                    tax_bps=ln.tax_bps,
                    options=[str(o["name"]) for o in ln.options],
                    note=ln.note,
                    allergens=ln.allergens,
                )
                for ln in order.lines
            ],
        )

    async def reprint(
        self, principal: Principal, store_id: uuid.UUID, order_id: uuid.UUID, what: str
    ) -> int:
        order = await self._staff_order(
            principal, store_id, order_id, P.STORE_ORDER_PRINT, write=True
        )
        return await self.printing.reprint(principal, await self._printable(order), what)

    async def _release_stock(self, order: StoreOrder) -> None:
        holds: dict[uuid.UUID, int] = {}
        for ln in order.lines:
            if ln.stock_reserved and ln.variant_id:
                holds[ln.variant_id] = holds.get(ln.variant_id, 0) + ln.stock_reserved
                ln.stock_reserved = 0
        await self.catalog.return_stock(holds)

    # ------------------------------------------------------------------ checkout

    async def checkout(
        self, customer_id: uuid.UUID, mall_slug: str, key: str, note: str | None
    ) -> tuple[CustomerOrderOut, bool]:
        """Returns the order and whether it was newly created (False = idempotent replay)."""
        existing = await self.repo.find_by_idempotency(customer_id, key)
        if existing is not None:
            return await self._customer_view(customer_id, existing.id), False

        mall = await self.cart.mall(mall_slug)
        cart = await self.repo.cart_for_update(customer_id, mall.id)
        if cart is None or not cart.lines:
            raise BadRequest("empty_cart", "Your cart is empty.")
        priced = await self.cart.priced(cart, mall)
        if any(p.problem for p in priced):
            raise Conflict("cart_has_problems", "Some items in your cart are no longer available.")

        contact = await self.customers.contact(customer_id)
        if contact.phone_masked is None:
            raise BadRequest("phone_required", "Verify your mobile number before ordering.")
        org_bps, accept_timeout = await self.tenancy.org_terms(mall.organization_id)
        holds: dict[uuid.UUID, int] = {}
        for p in priced:
            if p.product and p.product.counted:
                holds[p.line.variant_id] = holds.get(p.line.variant_id, 0) + p.line.quantity
        await self.catalog.take_stock(holds)

        order = CustomerOrder(
            id=uuid7(),
            customer_id=customer_id,
            organization_id=mall.organization_id,
            mall_id=mall.id,
            idempotency_key=key,
            total_paise=sum(p.total_paise for p in priced),
            note=note,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(order)
                await self.session.flush()
        except IntegrityError:  # a concurrent request with the same key won
            winner = await self.repo.find_by_idempotency(customer_id, key)
            if winner is None:
                raise
            return await self._customer_view(customer_id, winner.id), False

        by_store: dict[uuid.UUID, list[PricedLine]] = {}
        for p in priced:
            by_store.setdefault(p.line.store_id, []).append(p)
        store_orders: list[StoreOrder] = []
        total_commission = 0
        for store_id, rows in by_store.items():
            store = mall.stores[store_id]
            today = datetime.now(UTC).astimezone(ZoneInfo(store.timezone)).date()
            codes = await self.repo.open_pickup_codes(store_id)
            bps = store.commission_bps if store.commission_bps is not None else org_bps
            subtotal = sum(r.total_paise for r in rows)
            lines = [self._order_line(store_id, i, r) for i, r in enumerate(rows)]
            so = StoreOrder(
                id=uuid7(),
                customer_order_id=order.id,
                customer_id=customer_id,
                organization_id=mall.organization_id,
                mall_id=mall.id,
                store_id=store_id,
                status=S.PENDING_PAYMENT,
                order_date=today,
                order_no=await self.repo.next_order_no(store_id, today),
                pickup_code=self._new_code(codes),
                subtotal_paise=subtotal,
                tax_paise=sum(ln.tax_paise for ln in lines),
                total_paise=subtotal,
                commission_bps=bps,
                commission_paise=commission(subtotal, bps),
                prep_minutes=max((r.product.prep_minutes for r in rows if r.product), default=10),
                customer_name=contact.name,
                customer_phone=contact.phone_masked,
                note=note,
            )
            so.lines = lines
            total_commission += so.commission_paise
            store_orders.append(so)
        order.commission_paise = total_commission
        self.session.add_all(store_orders)
        await self.session.flush()
        for so in store_orders:
            self.session.add(
                OrderEvent(
                    store_order_id=so.id,
                    store_id=so.store_id,
                    from_status=None,
                    to_status=S.PENDING_PAYMENT,
                    actor_type=ActorType.CUSTOMER,
                    actor_id=customer_id,
                )
            )

        result = await self.payments.charge(amount_paise=order.total_paise, reference=str(order.id))
        if not result.ok:
            # Raising rolls the whole request back: no orders, and the held stock is released.
            raise PaymentFailed(detail="The payment did not go through. Please try again.")
        self.session.add(
            Payment(
                customer_order_id=order.id,
                provider=self.payments.name,
                provider_ref=result.provider_ref,
                amount_paise=order.total_paise,
                kind="charge",
            )
        )
        order.status = CustomerOrderStatus.PAID
        for so in store_orders:
            so.accept_by = datetime.now(UTC) + timedelta(seconds=accept_timeout)
            await self._transition(so, S.PAID, ActorType.SYSTEM, None)
        cart.lines.clear()
        await self.session.flush()
        view = await self._customer_view(customer_id, order.id)
        view.mall_slug = mall.slug
        return view, True

    @staticmethod
    def _order_line(store_id: uuid.UUID, position: int, r: PricedLine) -> StoreOrderLine:
        assert r.product and r.variant  # noqa: S101 - checkout refuses lines with problems
        return StoreOrderLine(
            store_id=store_id,
            product_id=r.product.id,
            variant_id=r.variant.id,
            position=position,
            name=r.product.name,
            variant_name=r.variant.name,
            diet=r.product.diet,
            allergens=r.product.allergens,
            options=[{"name": o.name, "price_delta_paise": o.price_delta_paise} for o in r.options],
            quantity=r.line.quantity,
            unit_price_paise=r.unit_price_paise,
            line_total_paise=r.total_paise,
            tax_bps=r.product.tax_bps,
            tax_paise=tax_included(r.total_paise, r.product.tax_bps),
            note=r.line.note,
            stock_reserved=r.line.quantity if r.product.counted else 0,
        )

    @staticmethod
    def _new_code(taken: set[str]) -> str:
        for _ in range(50):
            code = f"{secrets.randbelow(10_000):04d}"
            if code not in taken:
                taken.add(code)
                return code
        raise Conflict("busy", "This store is very busy. Please try again.")  # pragma: no cover

    # ------------------------------------------------------------------ customer reads / cancel

    async def _customer_view(self, customer_id: uuid.UUID, order_id: uuid.UUID) -> CustomerOrderOut:
        order = await self.repo.customer_order(customer_id, order_id)
        if order is None:
            raise NotFound("not_found", "Not found.")
        return (await self._customer_views([order]))[0]

    async def _customer_views(self, orders: list[CustomerOrder]) -> list[CustomerOrderOut]:
        store_orders = [so for o in orders for so in o.store_orders]
        stores = await self.tenancy.stores_by_ids(list({so.store_id for so in store_orders}))
        events = await self.repo.events_for([so.id for so in store_orders])
        out: list[CustomerOrderOut] = []
        for o in orders:
            views = []
            for so in o.store_orders:
                store = stores[so.store_id]
                views.append(
                    CustomerStoreOrderOut(
                        id=so.id,
                        store_slug=store.slug,
                        store_name=store.name,
                        status=so.status,
                        order_no=so.order_no,
                        pickup_code=so.pickup_code,
                        total_paise=so.total_paise,
                        tax_paise=so.tax_paise,
                        prep_minutes=so.prep_minutes,
                        accept_by=so.accept_by,
                        reason=so.reason,
                        note=so.note,
                        created_at=so.created_at,
                        lines=[OrderLineOut.model_validate(x) for x in so.lines],
                        steps=self._steps(events.get(so.id, [])),
                    )
                )
            out.append(
                CustomerOrderOut(
                    id=o.id,
                    status=o.status,
                    total_paise=o.total_paise,
                    created_at=o.created_at,
                    stores=views,
                )
            )
        return out

    @staticmethod
    def _steps(events: list[OrderEvent]) -> list[OrderStepOut]:
        return [OrderStepOut(status=e.to_status, at=e.created_at) for e in events]

    async def get_customer_order(
        self, customer_id: uuid.UUID, order_id: uuid.UUID
    ) -> CustomerOrderOut:
        return await self._customer_view(customer_id, order_id)

    async def list_customer_orders(
        self, customer_id: uuid.UUID, before: uuid.UUID | None, limit: int
    ) -> Page[CustomerOrderOut]:
        rows = await self.repo.customer_orders(customer_id, before, limit + 1)
        page = rows[:limit]
        return Page[CustomerOrderOut](
            items=await self._customer_views(page),
            next_cursor=page[-1].id if len(rows) > limit else None,
        )

    async def customer_cancel(
        self, customer_id: uuid.UUID, store_order_id: uuid.UUID
    ) -> CustomerOrderOut:
        order = await self.repo.store_order(store_order_id, lock=True)
        if order is None or order.customer_id != customer_id:
            raise NotFound("not_found", "Not found.")
        if order.status not in CUSTOMER_CANCELLABLE:
            raise Conflict("invalid_transition", "This order can no longer be cancelled by you.")
        await self._transition(
            order, S.CANCELLED, ActorType.CUSTOMER, customer_id, "Cancelled by customer"
        )
        return await self._customer_view(customer_id, order.customer_order_id)

    # ------------------------------------------------------------------ staff

    async def _scoped_store(
        self, principal: Principal, store_id: uuid.UUID, permission: P, *, write: bool
    ) -> Scope:
        store = await self.tenancy.get_store(principal, store_id)  # unseen tenants: 404
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        self.authz.require(principal, permission, scope)
        if write:
            await self.tenancy.assert_operational(principal, scope)
        return scope

    async def _staff_order(
        self,
        principal: Principal,
        store_id: uuid.UUID,
        order_id: uuid.UUID,
        permission: P,
        *,
        write: bool,
    ) -> StoreOrder:
        await self._scoped_store(principal, store_id, permission, write=write)
        order = await self.repo.store_order(order_id, lock=write)
        if order is None or order.store_id != store_id:
            raise NotFound("not_found", "Not found.")
        return order

    async def _staff_out(self, orders: list[StoreOrder]) -> list[StoreOrderOut]:
        events = await self.repo.events_for([o.id for o in orders])
        return [
            StoreOrderOut(
                id=o.id,
                store_id=o.store_id,
                order_no=o.order_no,
                status=o.status,
                customer_name=o.customer_name,
                customer_phone=o.customer_phone,
                total_paise=o.total_paise,
                tax_paise=o.tax_paise,
                prep_minutes=o.prep_minutes,
                accept_by=o.accept_by,
                accepted_at=o.accepted_at,
                ready_at=o.ready_at,
                picked_up_at=o.picked_up_at,
                reason=o.reason,
                note=o.note,
                created_at=o.created_at,
                lines=[OrderLineOut.model_validate(x) for x in o.lines],
                steps=self._steps(events.get(o.id, [])),
            )
            for o in orders
        ]

    @staticmethod
    def _open_filter(view: str) -> bool | None:
        return {"active": True, "history": False}.get(view)

    async def list_store_orders(
        self,
        principal: Principal,
        store_id: uuid.UUID,
        view: str,
        before: uuid.UUID | None,
        limit: int,
    ) -> Page[StoreOrderOut]:
        await self._scoped_store(principal, store_id, P.STORE_ORDER_READ, write=False)
        rows = await self.repo.list_store_orders(
            store_id=store_id, open_only=self._open_filter(view), before=before, limit=limit + 1
        )
        return await self._page(rows, limit)

    async def list_org_orders(
        self,
        principal: Principal,
        org_id: uuid.UUID,
        view: str,
        before: uuid.UUID | None,
        limit: int,
    ) -> Page[StoreOrderOut]:
        org = await self.tenancy.get_org(principal, org_id)
        self.authz.require(principal, P.STORE_ORDER_READ, Scope.org(org.id))
        rows = await self.repo.list_store_orders(
            organization_id=org.id,
            open_only=self._open_filter(view),
            before=before,
            limit=limit + 1,
        )
        return await self._page(rows, limit)

    async def list_mall_orders(
        self,
        principal: Principal,
        mall_id: uuid.UUID,
        view: str,
        before: uuid.UUID | None,
        limit: int,
    ) -> Page[StoreOrderOut]:
        mall = await self.tenancy.get_mall(principal, mall_id)
        self.authz.require(principal, P.STORE_ORDER_READ, Scope.mall(mall.organization_id, mall.id))
        rows = await self.repo.list_store_orders(
            mall_id=mall.id, open_only=self._open_filter(view), before=before, limit=limit + 1
        )
        return await self._page(rows, limit)

    async def _page(self, rows: list[StoreOrder], limit: int) -> Page[StoreOrderOut]:
        page = rows[:limit]
        return Page[StoreOrderOut](
            items=await self._staff_out(page),
            next_cursor=page[-1].id if len(rows) > limit else None,
        )

    async def get_store_order(
        self, principal: Principal, store_id: uuid.UUID, order_id: uuid.UUID
    ) -> StoreOrderOut:
        order = await self._staff_order(
            principal, store_id, order_id, P.STORE_ORDER_READ, write=False
        )
        return (await self._staff_out([order]))[0]

    async def advance(
        self,
        principal: Principal,
        store_id: uuid.UUID,
        order_id: uuid.UUID,
        to: StoreOrderStatus,
        *,
        reason: str | None = None,
        permission: P = P.STORE_ORDER_UPDATE,
    ) -> StoreOrderOut:
        order = await self._staff_order(principal, store_id, order_id, permission, write=True)
        await self._transition(order, to, ActorType.STAFF, principal.staff_id, reason)
        return (await self._staff_out([order]))[0]

    async def verify_pickup(
        self, principal: Principal, store_id: uuid.UUID, order_id: uuid.UUID, code: str
    ) -> StoreOrderOut:
        order = await self._staff_order(
            principal, store_id, order_id, P.STORE_ORDER_VERIFY_PICKUP, write=True
        )
        if not can_transition(order.status, S.PICKED_UP):
            raise Conflict("invalid_transition", "This order is not ready for pickup yet.")
        limit, window = PICKUP_ATTEMPTS_PER_ORDER
        await hit(self.kv, f"pickup:order:{order.id}", limit, window, code="pickup_locked")
        limit, window = PICKUP_ATTEMPTS_PER_STORE
        await hit(self.kv, f"pickup:store:{order.store_id}", limit, window, code="pickup_locked")
        if not hmac.compare_digest(code.encode(), order.pickup_code.encode()):
            raise BadRequest("wrong_pickup_code", "That pickup code is not right.")
        await self._transition(order, S.PICKED_UP, ActorType.STAFF, principal.staff_id)
        return (await self._staff_out([order]))[0]

    # ------------------------------------------------------------------ background

    async def sweep_expired(self, limit: int = 50) -> int:
        """Expire orders the store did not accept in time and refund them. Safe to run anywhere."""
        expired = await self.repo.expired_unaccepted(limit)
        for order in expired:
            await self._transition(
                order, S.EXPIRED, ActorType.SYSTEM, None, "The store did not accept in time"
            )
        return len(expired)


async def sweep_loop(app: Any, interval_s: float = 15.0) -> None:
    """Background: expire unaccepted orders. Row locks (SKIP LOCKED) make several API
    containers running this at once safe."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            async with app.state.session_factory() as session:
                service = OrderService(session, app.state.kv, app.state.bus, app.state.payments)
                count = await service.sweep_expired()
                await session.commit()
                await run_after_commit(session)
            if count:
                log.info("expired %d unaccepted order(s)", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("order sweep failed")
