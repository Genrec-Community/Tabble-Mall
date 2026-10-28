"""Imports every module's ORM models so Alembic autogenerate sees all tables."""

from mallt.core.db import Base

__all__ = ["Base"]
