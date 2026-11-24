import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from mallt.core.db import Base, IdMixin, TimestampMixin


class PlatformFeature(Base):
    """A feature switch the platform owner changed. Keys come from ``core/features.py``."""

    __tablename__ = "platform_features"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class FeaturedSpot(IdMixin, TimestampMixin, Base):
    """A store featured on its mall's home page, granted by the platform owner.

    Stores pay the mall owner for this outside MallT; ``amount_paise`` only records what was
    agreed, for the owner's own bookkeeping. MallT moves no money here."""

    __tablename__ = "featured_spots"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
