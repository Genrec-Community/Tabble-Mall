import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mallt.core.db import Base, IdMixin
from mallt.core.enums import ActorType, text_enum


class AuditLog(IdMixin, Base):
    """Append-only record of staff actions. No updated_at: rows are never modified."""

    __tablename__ = "audit_logs"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_type: Mapped[ActorType] = mapped_column(text_enum(ActorType, "audit_actor_type"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Deliberately not foreign keys: the log must outlive and never block changes to its subjects.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    mall_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)


# Keyset pagination of an organization's log, newest first.
Index(
    "ix_audit_logs_org_created",
    AuditLog.organization_id,
    AuditLog.created_at.desc(),
    AuditLog.id.desc(),
)
