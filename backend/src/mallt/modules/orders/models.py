import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mallt.core.db import Base, IdMixin, TimestampMixin
from mallt.core.enums import ActorType, text_enum
from mallt.modules.orders.enums import CustomerOrderStatus, FulfilmentType, StoreOrderStatus


class Cart(IdMixin, TimestampMixin, Base):
    __tablename__ = "carts"
    __table_args__ = (UniqueConstraint("customer_id", "mall_id", name="uq_carts_customer_id_mall"),)

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    # A store coupon the customer typed in (upper-case); checked again on every price.
    coupon_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set while this cart is the customer's share of a group order.
    group_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("group_orders.id", ondelete="SET NULL"), index=True, nullable=True
    )

    lines: Mapped[list["CartLine"]] = relationship(
        order_by="CartLine.created_at", cascade="all, delete-orphan", lazy="raise"
    )


class CartLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "cart_lines"

    cart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_variants.id"), index=True)
    option_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    quantity: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CustomerOrder(IdMixin, TimestampMixin, Base):
    """One checkout, one payment. Holds N StoreOrders; stores never see this row."""

    __tablename__ = "customer_orders"
    __table_args__ = (
        UniqueConstraint("customer_id", "idempotency_key", name="uq_customer_orders_idem"),
        Index("ix_customer_orders_unpaid", "status", "pay_by"),
        CheckConstraint("fulfilment_type = 'pickup'", name="pickup_only"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    status: Mapped[CustomerOrderStatus] = mapped_column(
        text_enum(CustomerOrderStatus, "customer_order_status"), default=CustomerOrderStatus.PLACED
    )
    fulfilment_type: Mapped[FulfilmentType] = mapped_column(
        text_enum(FulfilmentType, "fulfilment_type"), default=FulfilmentType.PICKUP
    )
    idempotency_key: Mapped[str] = mapped_column(Text)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    # Retired 2026-11-23 (MallT keeps no money). Never read or written; a later migration drops it.
    commission_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The provider's checkout session and, once paid, its payment id.
    payment_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_session_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_ref: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    # An unpaid order is given up (stock returned) after this.
    pay_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the customer wants to collect (None = as soon as it's ready).
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discount_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    group_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("group_orders.id"), index=True, nullable=True
    )

    store_orders: Mapped[list["StoreOrder"]] = relationship(
        back_populates="customer_order", order_by="StoreOrder.id", lazy="raise"
    )
    payments: Mapped[list["Payment"]] = relationship(lazy="raise")


class StoreOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "store_orders"
    __table_args__ = (
        Index("ix_store_orders_store_status", "store_id", "status"),
        UniqueConstraint("store_id", "order_date", "order_no", name="uq_store_orders_daily_no"),
    )

    customer_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_orders.id"), index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True)
    status: Mapped[StoreOrderStatus] = mapped_column(
        text_enum(StoreOrderStatus, "store_order_status"), default=StoreOrderStatus.PENDING_PAYMENT
    )
    order_date: Mapped[date] = mapped_column(Date)  # store-local calendar day
    order_no: Mapped[int] = mapped_column(Integer)  # 1.. per store per day, shown on slips
    pickup_code: Mapped[str] = mapped_column(Text)
    subtotal_paise: Mapped[int] = mapped_column(BigInteger)  # GST-inclusive prices
    tax_paise: Mapped[int] = mapped_column(BigInteger)  # the GST contained in the total
    # Offers and combos, borne by the store: total = subtotal - discount.
    discount_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # A snapshot of what was taken off: [{"kind", "name", "amount_paise", "offer_id"?}].
    discounts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default=text("'[]'")
    )
    # The store offer used, if any (for per-customer limits).
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offers.id"), index=True, nullable=True
    )
    total_paise: Mapped[int] = mapped_column(BigInteger)
    # Retired 2026-11-23 (MallT keeps no money). Never read or written; dropped later.
    commission_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commission_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The payment gateway's fee for this store's part, borne by the store (owner decision).
    gateway_fee_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    prep_minutes: Mapped[int] = mapped_column(Integer, default=10)
    customer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(Text, nullable=True)  # masked
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accept_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer_order: Mapped[CustomerOrder] = relationship(
        back_populates="store_orders", lazy="raise"
    )
    lines: Mapped[list["StoreOrderLine"]] = relationship(
        order_by="StoreOrderLine.position", cascade="all, delete-orphan", lazy="raise"
    )


Index(
    "ix_store_orders_accept_by",
    StoreOrder.accept_by,
    postgresql_where=text("status = 'paid'"),
)


class GroupOrder(IdMixin, TimestampMixin, Base):
    """Friends order together: each member fills their own cart and pays their own share."""

    __tablename__ = "group_orders"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    host_customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    token: Mapped[str] = mapped_column(Text, unique=True)  # the share link's secret
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="open")  # open | closed
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Review(IdMixin, TimestampMixin, Base):
    """A customer's rating of one collected store order (1-5 stars)."""

    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True)
    store_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("store_orders.id", ondelete="CASCADE"), unique=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The store's one public reply.
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)


class StoreOrderLine(IdMixin, Base):
    """A snapshot: later menu edits never change what was ordered."""

    __tablename__ = "store_order_lines"

    store_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("store_orders.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id"), index=True, nullable=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id"), index=True, nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(Text)
    variant_name: Mapped[str] = mapped_column(Text)
    diet: Mapped[str] = mapped_column(Text)
    allergens: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger)  # variant + options
    line_total_paise: Mapped[int] = mapped_column(BigInteger)
    tax_bps: Mapped[int] = mapped_column(Integer)
    tax_paise: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    stock_reserved: Mapped[int] = mapped_column(Integer, default=0)  # counted stock held


class OrderEvent(IdMixin, Base):
    """Append-only history of every state change."""

    __tablename__ = "order_events"

    store_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("store_orders.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True)
    from_status: Mapped[StoreOrderStatus | None] = mapped_column(
        text_enum(StoreOrderStatus, "order_event_from"), nullable=True
    )
    to_status: Mapped[StoreOrderStatus] = mapped_column(
        text_enum(StoreOrderStatus, "order_event_to")
    )
    actor_type: Mapped[ActorType] = mapped_column(text_enum(ActorType, "order_event_actor"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class OrderCounter(Base):
    """Per-store, per-day running number for the order number printed on slips."""

    __tablename__ = "order_counters"

    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_no: Mapped[int] = mapped_column(Integer, default=0)


class Payment(IdMixin, TimestampMixin, Base):
    __tablename__ = "payments"

    customer_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_orders.id"), index=True
    )
    provider: Mapped[str] = mapped_column(Text)
    provider_ref: Mapped[str] = mapped_column(Text)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(Text, default="charge")  # charge | refund
    store_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("store_orders.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(Text, default="succeeded")
