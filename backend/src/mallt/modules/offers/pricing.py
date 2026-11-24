"""Pure discount arithmetic (integer paise). No database, so it is easy to test.

Rules (owner, 2026-11-24): MallT keeps and gives no money, so every rupee off comes out of the
store whose items it is taken from. A combo's saving is split across its stores in proportion to
the regular price of each store's items in it; a store offer comes off that store's own share.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

MIN_STORE_TOTAL_PAISE = 100  # a store's part never drops below ₹1, so there is always a payment


@dataclass(frozen=True)
class QuoteLine:
    store_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price_paise: int


@dataclass(frozen=True)
class OfferRule:
    id: uuid.UUID
    store_id: uuid.UUID
    title: str
    code: str | None
    kind: str  # percent | flat
    value: int
    max_discount_paise: int | None
    min_subtotal_paise: int
    per_customer_limit: int | None
    starts_at: datetime | None
    ends_at: datetime | None
    is_active: bool

    def live(self, now: datetime) -> bool:
        return (
            self.is_active
            and (self.starts_at is None or self.starts_at <= now)
            and (self.ends_at is None or now < self.ends_at)
        )

    def amount(self, base_paise: int) -> int:
        if base_paise < self.min_subtotal_paise or base_paise <= 0:
            return 0
        if self.kind == "percent":
            off = base_paise * self.value // 10_000
            if self.max_discount_paise is not None:
                off = min(off, self.max_discount_paise)
        else:
            off = self.value
        return max(0, min(off, base_paise))


@dataclass(frozen=True)
class ComboRuleItem:
    store_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int


@dataclass(frozen=True)
class ComboRule:
    id: uuid.UUID
    name: str
    price_paise: int
    items: tuple[ComboRuleItem, ...]
    is_active: bool
    starts_at: datetime | None
    ends_at: datetime | None

    def live(self, now: datetime) -> bool:
        return (
            self.is_active
            and bool(self.items)
            and (self.starts_at is None or self.starts_at <= now)
            and (self.ends_at is None or now < self.ends_at)
        )


@dataclass(frozen=True)
class Discount:
    kind: str  # combo | offer
    name: str
    amount_paise: int
    offer_id: uuid.UUID | None = None
    combo_id: uuid.UUID | None = None


@dataclass
class StoreQuote:
    subtotal_paise: int
    discounts: list[Discount] = field(default_factory=list)
    offer_id: uuid.UUID | None = None

    @property
    def discount_paise(self) -> int:
        return sum(d.amount_paise for d in self.discounts)

    @property
    def total_paise(self) -> int:
        return self.subtotal_paise - self.discount_paise


CouponStatus = str  # none | applied | invalid | not_eligible | better_offer


@dataclass
class Quote:
    stores: dict[uuid.UUID, StoreQuote]
    coupon_code: str | None = None
    coupon_status: CouponStatus = "none"
    coupon_message: str | None = None

    @property
    def discount_paise(self) -> int:
        return sum(s.discount_paise for s in self.stores.values())


def split(amount: int, weights: dict[uuid.UUID, int]) -> dict[uuid.UUID, int]:
    """Split ``amount`` in proportion to ``weights`` (largest remainder, exact total)."""
    total = sum(weights.values())
    if amount <= 0 or total <= 0:
        return {k: 0 for k in weights}
    shares = {k: amount * w // total for k, w in weights.items()}
    left = amount - sum(shares.values())
    by_remainder = sorted(weights, key=lambda k: (-(amount * weights[k] % total), str(k)))
    for k in by_remainder[:left]:
        shares[k] += 1
    return shares


def quote(
    lines: list[QuoteLine],
    offers: list[OfferRule],
    combos: list[ComboRule],
    *,
    now: datetime,
    code: str | None = None,
    uses: dict[uuid.UUID, int] | None = None,
) -> Quote:
    uses = uses or {}
    stores: dict[uuid.UUID, StoreQuote] = {}
    for ln in lines:
        sq = stores.setdefault(ln.store_id, StoreQuote(0))
        sq.subtotal_paise += ln.unit_price_paise * ln.quantity

    # ---- combos: biggest saving first; each item can serve one combo.
    left_qty: dict[uuid.UUID, int] = {}
    cheapest: dict[uuid.UUID, int] = {}
    for ln in lines:
        left_qty[ln.product_id] = left_qty.get(ln.product_id, 0) + ln.quantity
        cheapest[ln.product_id] = min(
            cheapest.get(ln.product_id, ln.unit_price_paise), ln.unit_price_paise
        )

    def regular(c: ComboRule) -> int:
        return sum(cheapest.get(i.product_id, 0) * i.quantity for i in c.items)

    live = [c for c in combos if c.live(now) and all(i.product_id in cheapest for i in c.items)]
    live.sort(key=lambda c: (-(regular(c) - c.price_paise), str(c.id)))
    for combo in live:
        saving = regular(combo) - combo.price_paise
        if saving <= 0:
            continue
        times = min(left_qty.get(i.product_id, 0) // i.quantity for i in combo.items)
        if times <= 0:
            continue
        for i in combo.items:
            left_qty[i.product_id] -= i.quantity * times
        weights: dict[uuid.UUID, int] = {}
        for i in combo.items:
            weights[i.store_id] = weights.get(i.store_id, 0) + cheapest[i.product_id] * i.quantity
        for store_id, amount in split(saving * times, weights).items():
            if amount:
                stores[store_id].discounts.append(
                    Discount("combo", combo.name, amount, combo_id=combo.id)
                )

    # ---- store offers: the best one per store, on what is left after combos.
    typed = code.strip().upper() if code else None
    coupon_store: uuid.UUID | None = None
    coupon_used = False
    coupon_status, coupon_message = "none", None
    matching = [o for o in offers if typed and o.code == typed]
    if typed and not any(o.live(now) for o in matching):
        coupon_status, coupon_message = "invalid", "That coupon code isn't valid right now."
    for store_id, sq in stores.items():
        base = sq.total_paise
        best: tuple[int, OfferRule] | None = None
        for o in offers:
            if o.store_id != store_id or not o.live(now):
                continue
            if o.code is not None and o.code != typed:
                continue
            if o.per_customer_limit is not None and uses.get(o.id, 0) >= o.per_customer_limit:
                continue
            if o.code is not None:
                coupon_store = store_id
            amount = o.amount(base)
            if amount > 0 and (best is None or amount > best[0]):
                best = (amount, o)
        if best is not None:
            amount, o = best
            amount = min(amount, max(0, base - MIN_STORE_TOTAL_PAISE))
            if amount > 0:
                sq.discounts.append(Discount("offer", o.title, amount, offer_id=o.id))
                sq.offer_id = o.id
                coupon_used = coupon_used or o.code is not None
    # Never take a store's part below ₹1 (combos too).
    for sq in stores.values():
        over = MIN_STORE_TOTAL_PAISE - sq.total_paise
        while over > 0 and sq.discounts:
            d = sq.discounts[-1]
            cut = min(over, d.amount_paise)
            over -= cut
            if cut == d.amount_paise:
                sq.discounts.pop()
                if d.offer_id == sq.offer_id:
                    sq.offer_id = None
            else:
                sq.discounts[-1] = Discount(
                    d.kind, d.name, d.amount_paise - cut, d.offer_id, d.combo_id
                )
    if typed and coupon_status == "none":
        if coupon_used:
            coupon_status, coupon_message = "applied", None
        elif coupon_store is None:
            live_match = [o for o in matching if o.live(now)]
            if live_match and all(
                o.per_customer_limit is not None and uses.get(o.id, 0) >= o.per_customer_limit
                for o in live_match
            ):
                coupon_status, coupon_message = (
                    "not_eligible",
                    "You've already used this coupon.",
                )
            else:
                coupon_status, coupon_message = (
                    "not_eligible",
                    "Add something from that restaurant to use this coupon.",
                )
        else:
            o = next(o for o in matching if o.store_id == coupon_store)
            need = o.min_subtotal_paise - stores[coupon_store].subtotal_paise
            if need > 0:
                coupon_status = "not_eligible"
                coupon_message = (
                    f"Add ₹{(need + 99) // 100} more from that restaurant to use this coupon."
                )
            else:
                coupon_status, coupon_message = (
                    "better_offer",
                    "A better offer is already applied.",
                )
    return Quote(stores, typed, coupon_status, coupon_message)
