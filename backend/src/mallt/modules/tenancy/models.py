import uuid

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mallt.core.db import Base, IdMixin, TimestampMixin
from mallt.core.enums import ActiveStatus, text_enum


class Organization(IdMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[ActiveStatus] = mapped_column(
        text_enum(ActiveStatus, "org_status"), default=ActiveStatus.ACTIVE
    )
    # Platform commission in basis points (500 = 5%). Stored now, used when payments land.
    commission_bps: Mapped[int] = mapped_column(Integer, default=500, server_default="500")
    # Seconds a store has to accept a paid order before it expires and is refunded.
    accept_timeout_s: Mapped[int] = mapped_column(Integer, default=300, server_default="300")


class Mall(IdMixin, TimestampMixin, Base):
    __tablename__ = "malls"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)  # the QR code URL: /m/{slug}
    status: Mapped[ActiveStatus] = mapped_column(
        text_enum(ActiveStatus, "mall_status"), default=ActiveStatus.ACTIVE
    )
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)


class Store(IdMixin, TimestampMixin, Base):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("mall_id", "slug", name="uq_stores_mall_id_slug"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    status: Mapped[ActiveStatus] = mapped_column(
        text_enum(ActiveStatus, "store_status"), default=ActiveStatus.ACTIVE
    )
    # Per-store commission override in basis points; NULL means use the organization's.
    commission_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
