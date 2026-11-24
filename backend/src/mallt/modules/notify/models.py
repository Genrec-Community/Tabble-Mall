import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from mallt.core.db import Base, IdMixin, TimestampMixin


class PushSubscription(IdMixin, TimestampMixin, Base):
    """A browser's Web Push endpoint for one customer (the installed app or a tab)."""

    __tablename__ = "push_subscriptions"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)


class NotifyPrefs(TimestampMixin, Base):
    """What a customer agreed to be told on, beyond the order page itself."""

    __tablename__ = "notify_prefs"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    whatsapp: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Notification(IdMixin, TimestampMixin, Base):
    """Outbox of messages to a customer (push, WhatsApp). Written in the order's transaction,
    sent after commit and retried by the sweeper, so ordering never waits on a phone."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_due", "status", "next_attempt_at"),)

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)  # confirmed | ready | receipt | cancelled
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text, default="pending")  # pending | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
