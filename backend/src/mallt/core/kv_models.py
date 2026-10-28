from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from mallt.core.db import Base


class KvEntry(Base):
    """Postgres fallback for Redis (see core/kv.py)."""

    __tablename__ = "kv_store"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    counter: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
