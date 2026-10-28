import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mallt.modules.orders.enums import StoreOrderStatus
from mallt.modules.orders.models import (
    Cart,
    CartLine,
    CustomerOrder,
    OrderCounter,
    OrderEvent,
    StoreOrder,
)
from mallt.modules.orders.state import OPEN_STATES

_ORDER_LOAD = (selectinload(StoreOrder.lines),)


class OrdersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- cart ----

    async def get_cart(self, customer_id: uuid.UUID, mall_id: uuid.UUID) -> Cart | None:
        stmt = (
            select(Cart)
            .where(Cart.customer_id == customer_id, Cart.mall_id == mall_id)
            .options(selectinload(Cart.lines))
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def cart_for_update(self, customer_id: uuid.UUID, mall_id: uuid.UUID) -> Cart | None:
        """The cart, locked so two simultaneous checkouts cannot both consume it."""
        stmt = (
            select(Cart)
            .where(Cart.customer_id == customer_id, Cart.mall_id == mall_id)
            .options(selectinload(Cart.lines))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_cart(self, cart: Cart) -> Cart:
        stmt = (
            insert(Cart)
            .values(
                id=cart.id,
                customer_id=cart.customer_id,
                organization_id=cart.organization_id,
                mall_id=cart.mall_id,
            )
            .on_conflict_do_nothing(constraint="uq_carts_customer_id_mall")
        )
        await self.session.execute(stmt)
        found = await self.get_cart(cart.customer_id, cart.mall_id)
        if found is None:  # pragma: no cover - the row was just inserted
            raise RuntimeError("cart vanished")
        return found

    async def get_line(self, customer_id: uuid.UUID, line_id: uuid.UUID) -> CartLine | None:
        stmt = (
            select(CartLine)
            .join(Cart, Cart.id == CartLine.cart_id)
            .where(CartLine.id == line_id, Cart.customer_id == customer_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ---- orders ----

    async def next_order_no(self, store_id: uuid.UUID, day: date) -> int:
        stmt = (
            insert(OrderCounter)
            .values(store_id=store_id, day=day, last_no=1)
            .on_conflict_do_update(
                index_elements=[OrderCounter.store_id, OrderCounter.day],
                set_={"last_no": OrderCounter.last_no + 1},
            )
            .returning(OrderCounter.last_no)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def open_pickup_codes(self, store_id: uuid.UUID) -> set[str]:
        stmt = select(StoreOrder.pickup_code).where(
            StoreOrder.store_id == store_id, StoreOrder.status.in_(OPEN_STATES)
        )
        return set((await self.session.execute(stmt)).scalars())

    async def find_by_idempotency(self, customer_id: uuid.UUID, key: str) -> CustomerOrder | None:
        stmt = select(CustomerOrder).where(
            CustomerOrder.customer_id == customer_id, CustomerOrder.idempotency_key == key
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def customer_order(
        self, customer_id: uuid.UUID, order_id: uuid.UUID
    ) -> CustomerOrder | None:
        stmt = (
            select(CustomerOrder)
            .where(CustomerOrder.id == order_id, CustomerOrder.customer_id == customer_id)
            .options(selectinload(CustomerOrder.store_orders).selectinload(StoreOrder.lines))
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def customer_orders(
        self, customer_id: uuid.UUID, before: uuid.UUID | None, limit: int
    ) -> list[CustomerOrder]:
        stmt = (
            select(CustomerOrder)
            .where(CustomerOrder.customer_id == customer_id)
            .options(selectinload(CustomerOrder.store_orders).selectinload(StoreOrder.lines))
            .order_by(CustomerOrder.id.desc())
            .limit(limit)
        )
        if before is not None:
            stmt = stmt.where(CustomerOrder.id < before)
        return list((await self.session.execute(stmt)).scalars())

    async def store_order(self, order_id: uuid.UUID, *, lock: bool = False) -> StoreOrder | None:
        stmt = (
            select(StoreOrder)
            .where(StoreOrder.id == order_id)
            .options(*_ORDER_LOAD)
            .execution_options(populate_existing=True)
        )
        if lock:
            stmt = stmt.with_for_update(of=StoreOrder)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_store_orders(
        self,
        *,
        store_id: uuid.UUID | None = None,
        mall_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        open_only: bool | None,
        before: uuid.UUID | None,
        limit: int,
    ) -> list[StoreOrder]:
        stmt = (
            select(StoreOrder)
            .options(*_ORDER_LOAD)
            .order_by(StoreOrder.id.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        if store_id is not None:
            stmt = stmt.where(StoreOrder.store_id == store_id)
        if mall_id is not None:
            stmt = stmt.where(StoreOrder.mall_id == mall_id)
        if organization_id is not None:
            stmt = stmt.where(StoreOrder.organization_id == organization_id)
        if open_only is True:
            stmt = stmt.where(StoreOrder.status.in_(OPEN_STATES))
        elif open_only is False:
            stmt = stmt.where(StoreOrder.status.not_in(OPEN_STATES))
        else:
            stmt = stmt.where(StoreOrder.status != StoreOrderStatus.PENDING_PAYMENT)
        if before is not None:
            stmt = stmt.where(StoreOrder.id < before)
        return list((await self.session.execute(stmt)).scalars())

    async def events_for(self, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[OrderEvent]]:
        if not order_ids:
            return {}
        stmt = (
            select(OrderEvent)
            .where(OrderEvent.store_order_id.in_(order_ids))
            .order_by(OrderEvent.created_at, OrderEvent.id)
        )
        out: dict[uuid.UUID, list[OrderEvent]] = {}
        for event in (await self.session.execute(stmt)).scalars():
            out.setdefault(event.store_order_id, []).append(event)
        return out

    async def expired_unaccepted(self, limit: int) -> list[StoreOrder]:
        stmt = (
            select(StoreOrder)
            .where(
                StoreOrder.status == StoreOrderStatus.PAID, StoreOrder.accept_by < datetime.now(UTC)
            )
            .options(*_ORDER_LOAD)
            .order_by(StoreOrder.accept_by)
            .limit(limit)
            .with_for_update(skip_locked=True, of=StoreOrder)
            .execution_options(populate_existing=True)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def add(self, *objs: object) -> None:
        self.session.add_all(objs)
        await self.session.flush()
