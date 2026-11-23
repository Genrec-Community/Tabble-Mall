import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from mallt.core.db import Base, IdMixin, TimestampMixin
from mallt.core.enums import text_enum
from mallt.modules.payments.enums import LedgerKind, PayoutStatus, TaskKind, TaskStatus


class PayoutAccount(IdMixin, TimestampMixin, Base):
    """A store's account at the provider (Zoho: a connected account). Holds no full PAN or bank
    account number: those live only at the provider."""

    __tablename__ = "payout_accounts"
    __table_args__ = (UniqueConstraint("store_id", name="uq_payout_accounts_store_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"))
    provider: Mapped[str] = mapped_column(Text)
    account_ref: Mapped[str] = mapped_column(Text)
    account_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    pan_last4: Mapped[str] = mapped_column(Text)
    bank_last4: Mapped[str] = mapped_column(Text)
    ifsc: Mapped[str] = mapped_column(Text)
    mcc: Mapped[str] = mapped_column(Text)
    status: Mapped[PayoutStatus] = mapped_column(
        text_enum(PayoutStatus, "payout_status"), default=PayoutStatus.PENDING
    )
    review_status: Mapped[str] = mapped_column(Text, default="pending")


class PaymentTask(IdMixin, TimestampMixin, Base):
    """Outbox of money movements. Written inside the order's transaction, executed after commit
    and retried by the sweeper, so an order never waits on (or fails because of) the provider.
    Tasks of one customer order run strictly in creation order."""

    __tablename__ = "payment_tasks"
    __table_args__ = (Index("ix_payment_tasks_due", "status", "next_attempt_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True)
    customer_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_orders.id"), index=True
    )
    store_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("store_orders.id"), index=True)
    kind: Mapped[TaskKind] = mapped_column(text_enum(TaskKind, "payment_task_kind"))
    status: Mapped[TaskStatus] = mapped_column(
        text_enum(TaskStatus, "payment_task_status"), default=TaskStatus.PENDING
    )
    provider: Mapped[str] = mapped_column(Text)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    payment_ref: Mapped[str] = mapped_column(Text)
    account_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Refunds: what the provider said was already refunded before our first attempt, so a retry
    # after an unknown outcome can tell whether the first attempt went through.
    baseline_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class LedgerEntry(IdMixin, Base):
    """Append-only record of every money movement, for reconciliation. Never updated."""

    __tablename__ = "ledger_entries"

    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stores.id"), nullable=True, index=True
    )
    customer_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customer_orders.id"), index=True
    )
    store_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("store_orders.id"), nullable=True, index=True
    )
    kind: Mapped[LedgerKind] = mapped_column(text_enum(LedgerKind, "ledger_kind"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    provider: Mapped[str] = mapped_column(Text)
    provider_ref: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WebhookEvent(IdMixin, Base):
    """Seen provider events: a webhook delivered twice is processed once."""

    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_payment_webhook_events_event"),
    )

    provider: Mapped[str] = mapped_column(Text)
    event_id: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
