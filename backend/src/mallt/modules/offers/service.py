"""Store offers and coupons, and mall-wide combos.

Owner rules (2026-11-24): MallT keeps and gives no money, so a discount always comes out of the
share of the store whose items it is on (see ``pricing``). Each store still pays the gateway's fee
on what it actually receives.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActorType
from mallt.core.errors import BadRequest, Conflict, NotFound
from mallt.core.kv import KV
from mallt.core.rbac import P, Scope
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.catalog.service import OrderableMall, OrderableProduct, OrderingCatalog
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.offers.models import Combo, ComboItem, Offer
from mallt.modules.offers.pricing import (
    ComboRule,
    ComboRuleItem,
    OfferRule,
    Quote,
    QuoteLine,
    quote,
)
from mallt.modules.offers.repository import OffersRepository
from mallt.modules.offers.schemas import (
    ComboCreate,
    ComboItemOut,
    ComboOut,
    ComboUpdate,
    OfferCreate,
    OfferOut,
    OfferUpdate,
    PublicOfferOut,
    PublicOffersOut,
)
from mallt.modules.tenancy.service import TenancyService

UsesLookup = Callable[[list[uuid.UUID]], Awaitable[dict[uuid.UUID, int]]]


def _rule(o: Offer) -> OfferRule:
    return OfferRule(
        id=o.id,
        store_id=o.store_id,
        title=o.title,
        code=o.code,
        kind=o.kind,
        value=o.value,
        max_discount_paise=o.max_discount_paise,
        min_subtotal_paise=o.min_subtotal_paise,
        per_customer_limit=o.per_customer_limit,
        starts_at=o.starts_at,
        ends_at=o.ends_at,
        is_active=o.is_active,
    )


def _combo_rule(c: Combo) -> ComboRule:
    return ComboRule(
        id=c.id,
        name=c.name,
        price_paise=c.price_paise,
        items=tuple(ComboRuleItem(i.store_id, i.product_id, i.quantity) for i in c.items),
        is_active=c.is_active,
        starts_at=c.starts_at,
        ends_at=c.ends_at,
    )


class OffersService:
    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.session = session
        self.repo = OffersRepository(session)
        self.tenancy = TenancyService(session, kv)
        self.authz = AuthzService(session, kv)
        self.audit = AuditService(session)
        self.catalog = OrderingCatalog(session, kv)

    async def _record(
        self,
        principal: Principal,
        action: str,
        target: str,
        target_id: uuid.UUID,
        scope: Scope,
        after: dict[str, Any] | None,
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

    # ---------------------------------------------------------------- store offers (staff)

    async def _store_scope(
        self, principal: Principal, store_id: uuid.UUID, permission: P, *, write: bool
    ) -> Scope:
        store = await self.tenancy.get_store(principal, store_id)  # unseen tenants: 404
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        self.authz.require(principal, permission, scope)
        if write:
            await self.tenancy.assert_operational(principal, scope)
        return scope

    async def list_offers(self, principal: Principal, store_id: uuid.UUID) -> list[OfferOut]:
        await self._store_scope(principal, store_id, P.STORE_PRODUCT_READ, write=False)
        return [OfferOut.model_validate(o) for o in await self.repo.store_offers(store_id)]

    async def _owned_offer(self, store_id: uuid.UUID, offer_id: uuid.UUID) -> Offer:
        offer = await self.repo.offer(offer_id)
        if offer is None or offer.store_id != store_id:
            raise NotFound("not_found", "Not found.")
        return offer

    async def _check_code(
        self, store_id: uuid.UUID, code: str | None, except_id: uuid.UUID | None
    ) -> None:
        if code and await self.repo.code_taken(store_id, code, except_id):
            raise Conflict("code_taken", "Another offer of this store already uses that code.")

    async def create_offer(
        self, principal: Principal, store_id: uuid.UUID, data: OfferCreate
    ) -> OfferOut:
        scope = await self._store_scope(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        await self._check_code(store_id, data.code, None)
        assert scope.organization_id and scope.mall_id  # noqa: S101 - store scope has both
        offer = Offer(
            organization_id=scope.organization_id,
            mall_id=scope.mall_id,
            store_id=store_id,
            **data.model_dump(),
        )
        await self.repo.add(offer)
        await self._record(
            principal, "offer.create", "offer", offer.id, scope, data.model_dump(mode="json")
        )
        return OfferOut.model_validate(offer)

    async def update_offer(
        self, principal: Principal, store_id: uuid.UUID, offer_id: uuid.UUID, data: OfferUpdate
    ) -> OfferOut:
        scope = await self._store_scope(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        offer = await self._owned_offer(store_id, offer_id)
        await self._check_code(store_id, data.code, offer.id)
        for key, value in data.model_dump().items():
            setattr(offer, key, value)
        await self.session.flush()
        await self._record(
            principal, "offer.update", "offer", offer.id, scope, data.model_dump(mode="json")
        )
        return OfferOut.model_validate(offer)

    async def set_offer_active(
        self, principal: Principal, store_id: uuid.UUID, offer_id: uuid.UUID, active: bool
    ) -> OfferOut:
        scope = await self._store_scope(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        offer = await self._owned_offer(store_id, offer_id)
        offer.is_active = active
        await self.session.flush()
        await self._record(
            principal, "offer.update", "offer", offer.id, scope, {"is_active": active}
        )
        return OfferOut.model_validate(offer)

    async def delete_offer(
        self, principal: Principal, store_id: uuid.UUID, offer_id: uuid.UUID
    ) -> None:
        scope = await self._store_scope(principal, store_id, P.STORE_PRODUCT_WRITE, write=True)
        offer = await self._owned_offer(store_id, offer_id)
        offer.is_archived, offer.is_active = True, False  # kept: past orders point at it
        await self.session.flush()
        await self._record(principal, "offer.delete", "offer", offer.id, scope, None)

    # ---------------------------------------------------------------- mall combos (staff)

    async def _mall_scope(
        self, principal: Principal, mall_id: uuid.UUID, permission: P, *, write: bool
    ) -> tuple[Scope, str]:
        mall = await self.tenancy.get_mall(principal, mall_id)  # unseen tenants: 404
        scope = Scope.mall(mall.organization_id, mall.id)
        self.authz.require(principal, permission, scope)
        if write:
            await self.tenancy.assert_operational(principal, scope)
        return scope, mall.slug

    async def _mall(self, slug: str) -> OrderableMall:
        return await self.catalog.mall_stores(slug)

    async def _products(
        self, mall: OrderableMall, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, OrderableProduct]:
        return await self.catalog.products(mall.id, mall.stores, ids)

    async def _combo_out(self, combos: list[Combo], mall: OrderableMall | None) -> list[ComboOut]:
        products: dict[uuid.UUID, OrderableProduct] = {}
        if mall is not None:
            products = await self._products(mall, [i.product_id for c in combos for i in c.items])
        out = []
        for c in combos:
            items = []
            for i in c.items:
                p = products.get(i.product_id)
                price = min((v.price_paise for v in p.variants.values()), default=0) if p else 0
                items.append(
                    ComboItemOut(
                        product_id=i.product_id,
                        product_name=p.name if p else "Unavailable item",
                        store_id=i.store_id,
                        store_slug=p.store.slug if p else "",
                        store_name=p.store.name if p else "",
                        quantity=i.quantity,
                        regular_price_paise=price,
                    )
                )
            out.append(
                ComboOut(
                    id=c.id,
                    mall_id=c.mall_id,
                    name=c.name,
                    description=c.description,
                    price_paise=c.price_paise,
                    regular_price_paise=sum(x.regular_price_paise * x.quantity for x in items),
                    starts_at=c.starts_at,
                    ends_at=c.ends_at,
                    is_active=c.is_active,
                    items=items,
                )
            )
        return out

    async def _mall_or_none(self, slug: str) -> OrderableMall | None:
        try:
            return await self._mall(slug)
        except NotFound:  # a suspended mall still lists its combos to staff
            return None

    async def list_combos(self, principal: Principal, mall_id: uuid.UUID) -> list[ComboOut]:
        _, slug = await self._mall_scope(principal, mall_id, P.STORE_PRODUCT_READ, write=False)
        combos = await self.repo.mall_combos(mall_id, live_at=None)
        return await self._combo_out(combos, await self._mall_or_none(slug))

    async def _apply_combo(
        self, combo: Combo, data: ComboCreate, mall: OrderableMall, scope: Scope
    ) -> None:
        ids = [i.product_id for i in data.items]
        if len(set(ids)) != len(ids):
            raise BadRequest("duplicate_item", "Each dish can be in a combo once.")
        products = await self._products(mall, ids)
        if any(pid not in products for pid in ids):
            raise BadRequest("unknown_product", "Every dish must be on a menu in this mall.")
        regular = sum(
            min(v.price_paise for v in products[i.product_id].variants.values()) * i.quantity
            for i in data.items
            if products[i.product_id].variants
        )
        if data.price_paise >= regular:
            raise BadRequest("no_saving", "A combo must cost less than its dishes bought alone.")
        assert scope.organization_id and scope.mall_id  # noqa: S101 - mall scope has both
        combo.name, combo.description = data.name, data.description
        combo.price_paise = data.price_paise
        combo.starts_at, combo.ends_at, combo.is_active = (
            data.starts_at,
            data.ends_at,
            data.is_active,
        )
        combo.items = [
            ComboItem(
                organization_id=scope.organization_id,
                mall_id=scope.mall_id,
                store_id=products[i.product_id].store.id,
                product_id=i.product_id,
                quantity=i.quantity,
                position=n,
            )
            for n, i in enumerate(data.items)
        ]

    async def create_combo(
        self, principal: Principal, mall_id: uuid.UUID, data: ComboCreate
    ) -> ComboOut:
        scope, slug = await self._mall_scope(principal, mall_id, P.ORG_MALL_MANAGE, write=True)
        mall = await self._mall(slug)
        assert scope.organization_id  # noqa: S101
        combo = Combo(organization_id=scope.organization_id, mall_id=mall_id, items=[])
        await self._apply_combo(combo, data, mall, scope)
        await self.repo.add(combo)
        await self._record(
            principal, "combo.create", "combo", combo.id, scope, data.model_dump(mode="json")
        )
        return (await self._combo_out([combo], mall))[0]

    async def _owned_combo(self, mall_id: uuid.UUID, combo_id: uuid.UUID) -> Combo:
        combo = await self.repo.combo(combo_id)
        if combo is None or combo.mall_id != mall_id:
            raise NotFound("not_found", "Not found.")
        return combo

    async def update_combo(
        self, principal: Principal, mall_id: uuid.UUID, combo_id: uuid.UUID, data: ComboUpdate
    ) -> ComboOut:
        scope, slug = await self._mall_scope(principal, mall_id, P.ORG_MALL_MANAGE, write=True)
        combo = await self._owned_combo(mall_id, combo_id)
        mall = await self._mall(slug)
        await self._apply_combo(combo, data, mall, scope)
        await self.session.flush()
        await self._record(
            principal, "combo.update", "combo", combo.id, scope, data.model_dump(mode="json")
        )
        return (await self._combo_out([combo], mall))[0]

    async def set_combo_active(
        self, principal: Principal, mall_id: uuid.UUID, combo_id: uuid.UUID, active: bool
    ) -> ComboOut:
        scope, slug = await self._mall_scope(principal, mall_id, P.ORG_MALL_MANAGE, write=True)
        combo = await self._owned_combo(mall_id, combo_id)
        combo.is_active = active
        await self.session.flush()
        await self._record(
            principal, "combo.update", "combo", combo.id, scope, {"is_active": active}
        )
        return (await self._combo_out([combo], await self._mall_or_none(slug)))[0]

    async def delete_combo(
        self, principal: Principal, mall_id: uuid.UUID, combo_id: uuid.UUID
    ) -> None:
        scope, _ = await self._mall_scope(principal, mall_id, P.ORG_MALL_MANAGE, write=True)
        combo = await self._owned_combo(mall_id, combo_id)
        combo.is_archived, combo.is_active = True, False
        await self.session.flush()
        await self._record(principal, "combo.delete", "combo", combo.id, scope, None)

    # ---------------------------------------------------------------- customers

    async def public(self, mall_slug: str) -> PublicOffersOut:
        mall = await self._mall(mall_slug)
        now = datetime.now(UTC)
        offers = await self.repo.live_offers(list(mall.stores), now)
        combos = await self.repo.mall_combos(mall.id, live_at=now)
        combo_out = [
            c
            for c in await self._combo_out(combos, mall)
            if all(i.store_slug for i in c.items)  # every dish still on sale
        ]
        offers.sort(key=lambda o: (mall.stores[o.store_id].name, o.code is not None, o.title))
        return PublicOffersOut(
            offers=[
                PublicOfferOut(
                    id=o.id,
                    store_slug=mall.stores[o.store_id].slug,
                    store_name=mall.stores[o.store_id].name,
                    title=o.title,
                    code=o.code,
                    kind=o.kind,
                    value=o.value,
                    max_discount_paise=o.max_discount_paise,
                    min_subtotal_paise=o.min_subtotal_paise,
                    ends_at=o.ends_at,
                )
                for o in offers
            ],
            combos=combo_out,
        )

    async def quote(
        self,
        mall: OrderableMall,
        lines: list[QuoteLine],
        *,
        code: str | None,
        uses: UsesLookup | None,
        enabled: bool = True,
    ) -> Quote:
        """Prices a cart's discounts. ``uses`` tells how often this customer already used each
        limited offer (the ordering module knows; offers doesn't read orders)."""
        if not enabled or not lines:
            return quote(lines, [], [], now=datetime.now(UTC))
        now = datetime.now(UTC)
        store_ids = list({ln.store_id for ln in lines})
        offers = await self.repo.live_offers(store_ids, now)
        combos = await self.repo.mall_combos(mall.id, live_at=now)
        if code:  # a typed code may belong to a store not in the cart: say so, don't call it bad
            offers += [
                o
                for o in await self.repo.live_offers(
                    [s for s in mall.stores if s not in store_ids], now
                )
                if o.code == code.strip().upper()
            ]
        limited = [o.id for o in offers if o.per_customer_limit is not None]
        used = await uses(limited) if uses and limited else {}
        return quote(
            lines,
            [_rule(o) for o in offers],
            [_combo_rule(c) for c in combos],
            now=now,
            code=code,
            uses=used,
        )
