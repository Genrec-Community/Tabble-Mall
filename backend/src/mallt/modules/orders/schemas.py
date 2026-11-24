import datetime as dt
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from mallt.modules.orders.enums import CustomerOrderStatus, StoreOrderStatus

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=140)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- cart ----


class CartLineIn(BaseModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID
    option_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    quantity: int = Field(ge=1, le=20)
    note: Note | None = None


class CartLineUpdate(BaseModel):
    quantity: int | None = Field(default=None, ge=0, le=20)  # 0 removes the line
    note: Note | None = None


LineProblem = Literal["unavailable", "sold_out", "store_closed"]


class CartLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    variant_name: str
    diet: str
    options: list[str]
    quantity: int
    unit_price_paise: int
    line_total_paise: int
    note: str | None
    problem: LineProblem | None


class DiscountOut(BaseModel):
    kind: Literal["combo", "offer"]
    name: str
    amount_paise: int


class CartStoreOut(BaseModel):
    store_slug: str
    store_name: str
    accepting_orders: bool
    subtotal_paise: int  # the items at menu prices
    discount_paise: int = 0  # offers and combos, borne by this store
    total_paise: int = 0  # subtotal - discount
    discounts: list[DiscountOut] = Field(default_factory=list)
    prep_minutes: int
    lines: list[CartLineOut]


CouponStatus = Literal["applied", "invalid", "not_eligible", "better_offer"]


class CouponOut(BaseModel):
    code: str
    status: CouponStatus
    message: str | None


class CartGroupOut(BaseModel):
    """Set while this cart is the customer's share of a group order."""

    id: uuid.UUID
    token: str
    name: str | None
    is_host: bool


class CartOut(BaseModel):
    mall_slug: str
    stores: list[CartStoreOut]
    items_total_paise: int = 0  # before offers
    discount_paise: int = 0
    total_paise: int  # what the customer pays
    can_checkout: bool
    coupon: CouponOut | None = None
    group: CartGroupOut | None = None


class CouponIn(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class ReorderIn(BaseModel):
    order_id: uuid.UUID


class ReorderOut(BaseModel):
    cart: CartOut
    added: int  # lines put back in the cart
    skipped: list[str]  # dishes that can't be ordered now (gone, sold out, store closed)


class CheckoutIn(BaseModel):
    note: Note | None = None
    # Schedule ahead: when to collect (None = as soon as it's ready).
    pickup_at: datetime | None = None


class PickupSlotsOut(BaseModel):
    """When this cart can be collected: as soon as possible, or one of these times."""

    enabled: bool
    asap_minutes: int
    slots: list[datetime]


# ---- orders ----


class OrderLineOut(_Out):
    name: str
    variant_name: str
    diet: str
    options: list[dict[str, object]]
    quantity: int
    unit_price_paise: int
    line_total_paise: int
    note: str | None


class OrderStepOut(BaseModel):
    status: StoreOrderStatus
    at: datetime


class CustomerStoreOrderOut(BaseModel):
    id: uuid.UUID
    store_slug: str
    store_name: str
    status: StoreOrderStatus
    order_no: int
    pickup_code: str
    subtotal_paise: int = 0
    discount_paise: int = 0
    discounts: list[DiscountOut] = Field(default_factory=list)
    total_paise: int
    tax_paise: int
    prep_minutes: int
    pickup_at: datetime | None = None
    accept_by: datetime | None
    reason: str | None
    note: str | None
    created_at: datetime
    lines: list[OrderLineOut]
    steps: list[OrderStepOut]
    review: "ReviewOut | None" = None


class ZohoCheckoutOut(BaseModel):
    """What the browser passes to Zoho's checkout widget (zpayments.js). No secrets: the API key
    is Zoho's public widget key."""

    account_id: str
    api_key: str
    domain: str
    is_test_mode: bool
    payments_session_id: str
    amount: str
    currency_code: str
    description: str
    # Prefills Zoho's checkout so the customer doesn't type it again. Only ever sent to the
    # customer who owns the order.
    phone: str | None = None
    name: str | None = None


class OrderPaymentOut(BaseModel):
    provider: str
    # When set, the browser must open the provider's checkout with these and then confirm.
    zoho: ZohoCheckoutOut | None = None
    pay_by: datetime | None = None


class CustomerOrderOut(BaseModel):
    id: uuid.UUID
    status: CustomerOrderStatus
    total_paise: int
    discount_paise: int = 0
    pickup_at: datetime | None = None
    group_order_id: uuid.UUID | None = None
    created_at: datetime
    mall_slug: str | None = None
    # Present while the order still has to be paid.
    payment: OrderPaymentOut | None = None
    stores: list[CustomerStoreOrderOut]


class StoreOrderOut(BaseModel):
    """What a store sees. The pickup code is deliberately absent: only the customer has it."""

    id: uuid.UUID
    store_id: uuid.UUID
    order_no: int
    status: StoreOrderStatus
    customer_name: str | None
    customer_phone: str | None
    subtotal_paise: int = 0
    discount_paise: int = 0
    discounts: list[DiscountOut] = Field(default_factory=list)
    total_paise: int
    tax_paise: int
    prep_minutes: int
    pickup_at: datetime | None = None
    accept_by: datetime | None
    accepted_at: datetime | None
    ready_at: datetime | None
    picked_up_at: datetime | None
    reason: str | None
    note: str | None
    created_at: datetime
    lines: list[OrderLineOut]
    steps: list[OrderStepOut]


class ReasonIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class PickupIn(BaseModel):
    code: Annotated[str, StringConstraints(pattern=r"^\d{4}$")]


# ---- reports ----


class ReportTotalsOut(BaseModel):
    orders: int
    items: int
    gross_paise: int  # what customers paid (GST-inclusive)
    tax_paise: int  # the GST inside gross
    taxable_paise: int  # gross minus GST
    gateway_fee_paise: int
    payout_paise: int  # gross minus the gateway fee: what the store receives
    average_order_paise: int
    cancelled_orders: int  # rejected, expired or cancelled after payment (refunded)
    cancelled_paise: int


class BestSellerOut(BaseModel):
    name: str
    variant_name: str
    store_name: str
    quantity: int
    gross_paise: int


class HourOut(BaseModel):
    hour: int  # 0-23, store-local
    orders: int
    gross_paise: int


class DayOut(BaseModel):
    date: dt.date
    orders: int
    gross_paise: int


class GstRateOut(BaseModel):
    tax_bps: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    tax_paise: int
    gross_paise: int


class StoreTotalsOut(BaseModel):
    store_id: uuid.UUID
    store_name: str
    totals: ReportTotalsOut


class SalesReportOut(BaseModel):
    start: dt.date
    end: dt.date
    name: str  # the store's or the mall's
    totals: ReportTotalsOut
    best_sellers: list[BestSellerOut]
    hours: list[HourOut]
    days: list[DayOut]
    gst: list[GstRateOut]
    stores: list[StoreTotalsOut]  # one row per store (a store report has just its own)


class InvoiceLineOut(BaseModel):
    name: str
    variant_name: str
    quantity: int
    unit_price_paise: int
    tax_bps: int
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    total_paise: int


class InvoiceOut(BaseModel):
    """A GST tax invoice for one store order. Never carries the pickup code."""

    invoice_no: str
    order_id: uuid.UUID
    order_no: int
    date: dt.date
    issued_at: datetime
    status: str
    store_name: str
    store_gstin: str | None
    store_fssai: str | None
    customer_name: str | None
    sac: str  # 996331: restaurant and food services
    lines: list[InvoiceLineOut]
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    total_paise: int


# ---- group orders ----


class GroupCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None


class GroupLineOut(BaseModel):
    store_name: str
    product_name: str
    variant_name: str
    quantity: int


class GroupMemberOut(BaseModel):
    """What friends see of each other: a first name and what they picked. Never a phone."""

    name: str
    is_you: bool
    is_host: bool
    item_count: int
    total_paise: int  # still in their cart
    paid_paise: int  # already paid for, in orders of this group
    lines: list[GroupLineOut]


class GroupOrderOut(BaseModel):
    id: uuid.UUID
    token: str
    name: str | None
    mall_slug: str
    status: Literal["open", "closed", "expired"]
    expires_at: datetime
    is_host: bool
    joined: bool
    members: list[GroupMemberOut]


# ---- reviews ----

Comment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Comment | None = None


class ReviewOut(BaseModel):
    rating: int
    comment: str | None
    reply: str | None
    created_at: datetime


class StoreReviewOut(BaseModel):
    """A review as the store and other customers see it: a first name, never a phone."""

    id: uuid.UUID
    store_order_id: uuid.UUID | None = None  # only for the store itself
    order_no: int | None = None
    rating: int
    comment: str | None
    reply: str | None
    customer_name: str
    dishes: list[str]
    created_at: datetime


class ReviewReplyIn(BaseModel):
    reply: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class RatingOut(BaseModel):
    average: float  # 1.0-5.0, one decimal
    count: int


class MallRatingsOut(BaseModel):
    """Ratings for a mall's stores (by slug) and dishes (by product id)."""

    stores: dict[str, RatingOut]
    products: dict[str, RatingOut]


CustomerStoreOrderOut.model_rebuild()
