import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from mallt.core.db import Base, IdMixin, TimestampMixin
from mallt.core.enums import text_enum
from mallt.modules.printing.enums import JobKind, JobStatus, PrinterConnection, PrinterRole


class _StoreOwned:
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), index=True, nullable=False
    )
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True, nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True, nullable=False)


class PrintAgent(IdMixin, TimestampMixin, _StoreOwned, Base):
    """The program on the store's counter PC. Authenticated by ``<id>.<secret>`` (argon2)."""

    __tablename__ = "print_agents"
    __table_args__ = (UniqueConstraint("store_id", "name", name="uq_print_agents_store_name"),)

    name: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text)
    token_prefix: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[str | None] = mapped_column(Text, nullable=True)


class DetectedPrinter(IdMixin, _StoreOwned, Base):
    """What an agent found on its PC. Replaced wholesale each time the agent reports."""

    __tablename__ = "detected_printers"
    __table_args__ = (UniqueConstraint("agent_id", "key", name="uq_detected_printers_agent_key"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("print_agents.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    connection: Mapped[PrinterConnection] = mapped_column(
        text_enum(PrinterConnection, "detected_connection")
    )
    target: Mapped[str] = mapped_column(Text)
    driver: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    likely_thermal: Mapped[bool] = mapped_column(Boolean, default=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class Printer(IdMixin, TimestampMixin, _StoreOwned, Base):
    __tablename__ = "printers"
    __table_args__ = (UniqueConstraint("store_id", "name", name="uq_printers_store_name"),)

    name: Mapped[str] = mapped_column(Text)
    role: Mapped[PrinterRole] = mapped_column(
        text_enum(PrinterRole, "printer_role"), default=PrinterRole.KITCHEN
    )
    connection: Mapped[PrinterConnection] = mapped_column(
        text_enum(PrinterConnection, "printer_connection")
    )
    target: Mapped[str] = mapped_column(Text)
    # Characters per line: 32 for 58 mm paper, 48 for 80 mm.
    paper_width: Mapped[int] = mapped_column(SmallInteger, default=32, server_default="32")
    layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StoreBillSettings(IdMixin, TimestampMixin, _StoreOwned, Base):
    """What the top and bottom of a printed bill say. No row = defaults."""

    __tablename__ = "store_bill_settings"
    __table_args__ = (UniqueConstraint("store_id", name="uq_store_bill_settings_store_id"),)

    header_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    header_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    header_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    header_extra: Mapped[str | None] = mapped_column(Text, nullable=True)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Normalised greyscale PNG, at most 256 KB. Kept in the database on purpose: printing must
    # never wait on object storage.
    logo_png: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PrintJob(IdMixin, TimestampMixin, _StoreOwned, Base):
    __tablename__ = "print_jobs"
    __table_args__ = (
        Index("ix_print_jobs_store_status", "store_id", "status"),
        # One KOT per order per printer per revision; bills may be reprinted freely.
        Index(
            "uq_print_jobs_ticket",
            "store_order_id",
            "printer_id",
            "revision",
            unique=True,
            postgresql_where=text("kind = 'ticket'"),
        ),
    )

    printer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("printers.id", ondelete="CASCADE"), index=True
    )
    store_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("store_orders.id", ondelete="CASCADE"), index=True, nullable=True
    )
    kind: Mapped[JobKind] = mapped_column(text_enum(JobKind, "print_job_kind"))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[JobStatus] = mapped_column(
        text_enum(JobStatus, "print_job_status"), default=JobStatus.QUEUED
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
