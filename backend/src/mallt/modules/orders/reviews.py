"""Ratings and reviews: after collecting, a customer rates that store's part of the order.

A rating counts for the store and for every dish in that store order. Ratings feed the mall's
Popular rail (well-liked dishes rise) and the stars shown on store cards and dishes.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActorType
from mallt.core.errors import Conflict, NotFound
from mallt.core.kv import KV
from mallt.core.pagination import Page
from mallt.core.rbac import P, Scope
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.iam.users import IamCustomers
from mallt.modules.orders.enums import StoreOrderStatus
from mallt.modules.orders.models import Review
from mallt.modules.orders.repository import OrdersRepository
from mallt.modules.orders.schemas import (
    MallRatingsOut,
    RatingOut,
    ReviewIn,
    ReviewOut,
    StoreReviewOut,
)
from mallt.modules.platform.service import FeatureService
from mallt.modules.tenancy.service import TenancyService

EDIT_WINDOW = timedelta(days=7)
# Bayesian prior for ranking: a dish with few ratings is pulled towards 3.5 stars.
PRIOR_STARS, PRIOR_WEIGHT = 3.5, 2


def review_out(r: Review) -> ReviewOut:
    return ReviewOut(rating=r.rating, comment=r.comment, reply=r.reply, created_at=r.created_at)


def rating(avg: float, n: int) -> RatingOut:
    return RatingOut(average=round(avg, 1), count=n)


def popularity(orders: int, avg: float | None, n: int) -> float:
    """How a dish ranks on the Popular rail: orders, nudged by how much people liked it."""
    stars = ((avg or 0) * n + PRIOR_STARS * PRIOR_WEIGHT) / (n + PRIOR_WEIGHT)
    return orders * stars / 5


class ReviewService:
    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.session = session
        self.repo = OrdersRepository(session)
        self.features = FeatureService(session)
        self.tenancy = TenancyService(session, kv)
        self.authz = AuthzService(session, kv)
        self.audit = AuditService(session)
        self.customers = IamCustomers(session)

    # ---- customers ----

    async def rate(
        self, customer_id: uuid.UUID, store_order_id: uuid.UUID, data: ReviewIn
    ) -> ReviewOut:
        await self.features.require("reviews")
        order = await self.repo.store_order(store_order_id)
        if order is None or order.customer_id != customer_id:
            raise NotFound("not_found", "Not found.")
        if order.status is not StoreOrderStatus.PICKED_UP:
            raise Conflict("not_collected", "You can rate an order once you've collected it.")
        review = await self.repo.review_for(store_order_id)
        now = datetime.now(UTC)
        if review is None:
            review = Review(
                organization_id=order.organization_id,
                mall_id=order.mall_id,
                store_id=order.store_id,
                store_order_id=order.id,
                customer_id=customer_id,
                rating=data.rating,
                comment=data.comment or None,
            )
            self.session.add(review)
        else:
            if review.created_at + EDIT_WINDOW < now:
                raise Conflict("review_locked", "Reviews can be changed for 7 days.")
            review.rating, review.comment = data.rating, data.comment or None
        await self.session.flush()
        await self.session.refresh(review)
        return review_out(review)

    async def for_store_orders(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, ReviewOut]:
        return {r.store_order_id: review_out(r) for r in await self.repo.reviews_for(ids)}

    # ---- public ----

    async def mall_ratings(self, mall_slug: str) -> MallRatingsOut:
        mall, stores = await self.tenancy.public_directory(mall_slug)
        if not await self.features.is_enabled("reviews"):
            return MallRatingsOut(stores={}, products={})
        slugs = {s.id: s.slug for s in stores}
        by_store = await self.repo.store_ratings(mall.id)
        by_product = await self.repo.product_ratings(mall.id)
        return MallRatingsOut(
            stores={slugs[sid]: rating(a, n) for sid, (a, n) in by_store.items() if sid in slugs},
            products={str(pid): rating(a, n) for pid, (a, n) in by_product.items()},
        )

    async def public_store_reviews(
        self, mall_slug: str, store_slug: str, limit: int
    ) -> list[StoreReviewOut]:
        _, stores = await self.tenancy.public_directory(mall_slug)
        store = next((s for s in stores if s.slug == store_slug), None)
        if store is None:
            raise NotFound("not_found", "Not found.")
        if not await self.features.is_enabled("reviews"):
            return []
        rows = await self.repo.store_reviews(store.id, before=None, limit=limit, with_text=True)
        return await self._out(rows, staff=False)

    # ---- the store ----

    async def _store_scope(
        self, principal: Principal, store_id: uuid.UUID, permission: P, *, write: bool
    ) -> Scope:
        store = await self.tenancy.get_store(principal, store_id)  # unseen tenants: 404
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        self.authz.require(principal, permission, scope)
        if write:
            await self.tenancy.assert_operational(principal, scope)
        return scope

    async def store_reviews(
        self, principal: Principal, store_id: uuid.UUID, before: uuid.UUID | None, limit: int
    ) -> Page[StoreReviewOut]:
        await self._store_scope(principal, store_id, P.STORE_ORDER_READ, write=False)
        rows = await self.repo.store_reviews(store_id, before=before, limit=limit + 1)
        page = rows[:limit]
        return Page[StoreReviewOut](
            items=await self._out(page, staff=True),
            next_cursor=page[-1].id if len(rows) > limit else None,
        )

    async def reply(
        self, principal: Principal, store_id: uuid.UUID, review_id: uuid.UUID, text: str
    ) -> StoreReviewOut:
        scope = await self._store_scope(principal, store_id, P.STORE_ORDER_UPDATE, write=True)
        review = await self.repo.review(review_id)
        if review is None or review.store_id != store_id:
            raise NotFound("not_found", "Not found.")
        review.reply = text
        await self.session.flush()
        await self.audit.record(
            actor=Actor(ActorType.STAFF, principal.staff_id),
            action="review.reply",
            target_type="review",
            target_id=review.id,
            scope=scope,
            before=None,
            after={"reply": text},
        )
        return (await self._out([review], staff=True))[0]

    async def _out(self, rows: list[Review], *, staff: bool) -> list[StoreReviewOut]:
        names = await self.customers.first_names(list({r.customer_id for r in rows}))
        orders = await self.repo.store_orders_by_ids([r.store_order_id for r in rows])
        return [
            StoreReviewOut(
                id=r.id,
                store_order_id=r.store_order_id if staff else None,
                order_no=orders[r.store_order_id].order_no
                if staff and r.store_order_id in orders
                else None,
                rating=r.rating,
                comment=r.comment,
                reply=r.reply,
                customer_name=names.get(r.customer_id, "Guest"),
                dishes=[ln.name for ln in orders[r.store_order_id].lines]
                if r.store_order_id in orders
                else [],
                created_at=r.created_at,
            )
            for r in rows
        ]
