import uuid

from pydantic import BaseModel


class Page[T](BaseModel):
    """Keyset page. IDs are UUIDv7 so ordering by id is ordering by creation time."""

    items: list[T]
    next_cursor: uuid.UUID | None = None
