import uuid
from datetime import UTC, datetime, timedelta

from mallt.modules.offers.pricing import (
    ComboRule,
    ComboRuleItem,
    OfferRule,
    QuoteLine,
    quote,
    split,
)

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
A, B = uuid.uuid4(), uuid.uuid4()
BURGER, CHAI, FRIES = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def offer(store: uuid.UUID = A, **over: object) -> OfferRule:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "store_id": store,
        "title": "10% off",
        "code": None,
        "kind": "percent",
        "value": 1000,
        "max_discount_paise": None,
        "min_subtotal_paise": 0,
        "per_customer_limit": None,
        "starts_at": None,
        "ends_at": None,
        "is_active": True,
    }
    base.update(over)
    return OfferRule(**base)  # type: ignore[arg-type]


def lines() -> list[QuoteLine]:
    return [
        QuoteLine(A, BURGER, 2, 12000),
        QuoteLine(A, FRIES, 1, 8000),
        QuoteLine(B, CHAI, 1, 3000),
    ]


def test_split_is_exact_and_proportional() -> None:
    assert split(100, {A: 1, B: 2}) == {A: 33, B: 67}
    assert sum(split(999, {A: 7, B: 13}).values()) == 999


def test_no_offers_means_no_discount() -> None:
    q = quote(lines(), [], [], now=NOW)
    assert q.stores[A].total_paise == 32000 and q.stores[B].total_paise == 3000
    assert q.discount_paise == 0 and q.coupon_status == "none"


def test_automatic_percent_offer_with_cap_comes_off_its_store_only() -> None:
    q = quote(lines(), [offer(max_discount_paise=2500)], [], now=NOW)
    assert q.stores[A].discount_paise == 2500  # 10% of 32,000 = 3,200, capped
    assert q.stores[B].discount_paise == 0


def test_best_offer_wins_and_minimum_is_respected() -> None:
    flat = offer(kind="flat", value=5000, title="₹50 off", min_subtotal_paise=30000)
    pct = offer(value=1000)
    q = quote(lines(), [flat, pct], [], now=NOW)
    assert q.stores[A].discounts[0].name == "₹50 off" and q.stores[A].offer_id == flat.id
    high_min = offer(kind="flat", value=5000, min_subtotal_paise=50000)
    assert quote(lines(), [high_min], [], now=NOW).stores[A].discount_paise == 0


def test_inactive_and_out_of_window_offers_do_not_apply() -> None:
    off = [
        offer(is_active=False),
        offer(starts_at=NOW + timedelta(hours=1)),
        offer(ends_at=NOW),
    ]
    assert quote(lines(), off, [], now=NOW).discount_paise == 0


def test_coupon_needs_its_code_and_reports_status() -> None:
    coupon = offer(code="CHAI20", store=B, value=2000, title="20% off chai")
    assert quote(lines(), [coupon], [], now=NOW).stores[B].discount_paise == 0
    q = quote(lines(), [coupon], [], now=NOW, code=" chai20 ")
    assert q.stores[B].discount_paise == 600 and q.coupon_status == "applied"
    bad = quote(lines(), [coupon], [], now=NOW, code="NOPE")
    assert bad.coupon_status == "invalid" and bad.discount_paise == 0


def test_coupon_for_a_store_not_in_cart_or_below_minimum() -> None:
    coupon = offer(code="SAVE", store=uuid.uuid4())
    assert quote(lines(), [coupon], [], now=NOW, code="SAVE").coupon_status == "not_eligible"
    big = offer(code="BIG", store=B, min_subtotal_paise=10000)
    q = quote(lines(), [big], [], now=NOW, code="BIG")
    assert q.coupon_status == "not_eligible" and "₹70 more" in (q.coupon_message or "")


def test_per_customer_limit() -> None:
    once = offer(code="FIRST", per_customer_limit=1)
    q = quote(lines(), [once], [], now=NOW, code="FIRST", uses={once.id: 1})
    assert q.discount_paise == 0 and q.coupon_status == "not_eligible"


def test_combo_saving_is_split_across_stores_by_their_items() -> None:
    combo = ComboRule(
        id=uuid.uuid4(),
        name="Burger + Chai",
        price_paise=12000,
        items=(ComboRuleItem(A, BURGER, 1), ComboRuleItem(B, CHAI, 1)),
        is_active=True,
        starts_at=None,
        ends_at=None,
    )
    q = quote(lines(), [], [combo], now=NOW)
    # regular 15,000 → 12,000: saving 3,000 split 12:3 → 2,400 + 600
    assert q.stores[A].discount_paise == 2400 and q.stores[B].discount_paise == 600
    assert q.stores[A].discounts[0].kind == "combo"


def test_combo_needs_every_item_and_store_offer_applies_after_it() -> None:
    combo = ComboRule(
        uuid.uuid4(),
        "Fries + Chai x2",
        5000,
        (ComboRuleItem(A, FRIES, 1), ComboRuleItem(B, CHAI, 2)),
        True,
        None,
        None,
    )
    assert quote(lines(), [], [combo], now=NOW).discount_paise == 0  # only one chai
    combo2 = ComboRule(
        uuid.uuid4(),
        "Burger + Chai",
        12000,
        (ComboRuleItem(A, BURGER, 1), ComboRuleItem(B, CHAI, 1)),
        True,
        None,
        None,
    )
    q = quote(lines(), [offer()], [combo2], now=NOW)
    # A: 32,000 - 2,400 combo = 29,600, then 10% = 2,960
    assert q.stores[A].discount_paise == 2400 + 2960


def test_store_part_never_drops_below_one_rupee() -> None:
    q = quote([QuoteLine(B, CHAI, 1, 3000)], [offer(B, kind="flat", value=9000)], [], now=NOW)
    assert q.stores[B].total_paise == 100
