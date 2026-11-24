import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mallt.core.db import Base, IdMixin, TimestampMixin


class Offer(IdMixin, TimestampMixin, Base):
    """A store's discount on its own share of an order. With a code it is a coupon; without one
    it applies by itself. The store bears it (MallT keeps and gives no money)."""

    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("kind IN ('percent', 'flat')", name="kind"),
        CheckConstraint("value > 0", name="value_positive"),
        Index("ix_offers_store_code", "store_id", "code"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)  # upper-case; None = automatic
    kind: Mapped[str] = mapped_column(Text)  # percent (value in basis points) | flat (paise)
    value: Mapped[int] = mapped_column(Integer)
    max_discount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_subtotal_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    per_customer_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Combo(IdMixin, TimestampMixin, Base):
    """A mall-wide bundle across stores at one price. Each store bears the part of the saving
    that falls on its own items."""

    __tablename__ = "combos"
    __table_args__ = (CheckConstraint("price_paise > 0", name="price_positive"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_paise: Mapped[int] = mapped_column(BigInteger)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    items: Mapped[list["ComboItem"]] = relationship(
        order_by="ComboItem.position", cascade="all, delete-orphan", lazy="raise"
    )


class ComboItem(IdMixin, Base):
    __tablename__ = "combo_items"

    combo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("combos.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
