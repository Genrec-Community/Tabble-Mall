"""Group orders: friends share one link. Each member fills their own cart in the mall and pays
their own share with a normal checkout; the group only ties those carts and orders together.

The link's token is the only key: anyone signed in who has it may join while the group is open.
Members see each other's first names and dishes, never phone numbers.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.errors import Conflict, NotFound
from mallt.core.ids import uuid7
from mallt.core.kv import KV
from mallt.modules.iam.users import IamCustomers
from mallt.modules.orders.cart import CartService, group_live
from mallt.modules.orders.models import Cart, GroupOrder
from mallt.modules.orders.repository import OrdersRepository
from mallt.modules.orders.schemas import (
    GroupLineOut,
    GroupMemberOut,
    GroupOrderOut,
)
from mallt.modules.platform.service import FeatureService

GROUP_LIFETIME = timedelta(hours=6)
MAX_MEMBERS = 20


class GroupService:
    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.session = session
        self.repo = OrdersRepository(session)
        self.cart = CartService(session, kv)
        self.customers = IamCustomers(session)
        self.features = FeatureService(session)

    async def _group(self, token: str) -> GroupOrder:
        await self.features.require("group_orders")
        group = await self.repo.group_by_token(token)
        if group is None:
            raise NotFound("not_found", "This group link is not valid.")
        return group

    async def _my_cart(self, customer_id: uuid.UUID, group: GroupOrder) -> Cart:
        cart = await self.repo.get_cart(customer_id, group.mall_id)
        if cart is None:
            cart = await self.repo.create_cart(
                Cart(
                    id=uuid7(),
                    customer_id=customer_id,
                    organization_id=group.organization_id,
                    mall_id=group.mall_id,
                )
            )
        return cart

    async def create(
        self, customer_id: uuid.UUID, mall_slug: str, name: str | None
    ) -> GroupOrderOut:
        await self.features.require("group_orders")
        mall = await self.cart.mall(mall_slug)
        existing = await self.repo.get_cart(customer_id, mall.id)
        if existing and existing.group_order_id:
            current = await self.repo.group(existing.group_order_id)
            if current and current.host_customer_id == customer_id and current.status == "open":
                if group_live(current):
                    return await self.view(customer_id, current.token)
        group = GroupOrder(
            id=uuid7(),
            organization_id=mall.organization_id,
            mall_id=mall.id,
            host_customer_id=customer_id,
            token=secrets.token_urlsafe(9),
            name=name or None,
            status="open",
            expires_at=datetime.now(UTC) + GROUP_LIFETIME,
        )
        self.session.add(group)
        await self.session.flush()
        cart = await self._my_cart(customer_id, group)
        cart.group_order_id = group.id
        await self.session.flush()
        return await self.view(customer_id, group.token)

    async def join(self, customer_id: uuid.UUID, token: str) -> GroupOrderOut:
        group = await self._group(token)
        cart = await self._my_cart(customer_id, group)
        if cart.group_order_id != group.id:
            if group.status != "open" or not group_live(group):
                raise Conflict("group_closed", "This group order is closed.")
            if len(await self.repo.group_carts(group.id)) >= MAX_MEMBERS:
                raise Conflict("group_full", "This group is full.")
            cart.group_order_id = group.id
            await self.session.flush()
        return await self.view(customer_id, token)

    async def leave(self, customer_id: uuid.UUID, token: str) -> None:
        group = await self._group(token)
        cart = await self.repo.get_cart(customer_id, group.mall_id)
        if cart is not None and cart.group_order_id == group.id:
            cart.group_order_id = None
            await self.session.flush()

    async def close(self, customer_id: uuid.UUID, token: str) -> GroupOrderOut:
        group = await self._group(token)
        if group.host_customer_id != customer_id:
            raise NotFound("not_found", "This group link is not valid.")
        group.status = "closed"
        await self.session.flush()
        return await self.view(customer_id, token)

    async def view(self, customer_id: uuid.UUID, token: str) -> GroupOrderOut:
        group = await self._group(token)
        carts = await self.repo.group_carts(group.id)
        joined = any(c.customer_id == customer_id for c in carts)
        if not joined and (group.status != "open" or not group_live(group)):
            # Once closed, a stranger with the link learns nothing about who is in it.
            raise Conflict("group_closed", "This group order is closed.")
        paid = await self.repo.group_paid(group.id)
        member_ids = list(dict.fromkeys([c.customer_id for c in carts] + list(paid)))
        names = await self.customers.first_names(member_ids)
        mall = await self.cart.mall_by_id(group.mall_id)
        by_customer = {c.customer_id: c for c in carts}
        members: list[GroupMemberOut] = []
        for cid in member_ids:
            cart = by_customer.get(cid)
            lines: list[GroupLineOut] = []
            total = 0
            if cart is not None and cart.lines and mall is not None:
                for p in await self.cart.priced(cart, mall):
                    if p.problem:
                        continue
                    store = mall.stores.get(p.line.store_id)
                    lines.append(
                        GroupLineOut(
                            store_name=store.name if store else "",
                            product_name=p.product.name if p.product else "",
                            variant_name=p.variant.name if p.variant else "",
                            quantity=p.line.quantity,
                        )
                    )
                    total += p.total_paise
            members.append(
                GroupMemberOut(
                    name=names.get(cid, "Guest"),
                    is_you=cid == customer_id,
                    is_host=cid == group.host_customer_id,
                    item_count=sum(ln.quantity for ln in lines),
                    total_paise=total,
                    paid_paise=paid.get(cid, 0),
                    lines=lines,
                )
            )
        members.sort(key=lambda m: (not m.is_host, not m.is_you, m.name))
        status = group.status if group_live(group) else "expired"
        return GroupOrderOut(
            id=group.id,
            token=group.token,
            name=group.name,
            mall_slug=mall.slug if mall else "",
            status=status,
            expires_at=group.expires_at,
            is_host=group.host_customer_id == customer_id,
            joined=joined,
            members=members,
        )
