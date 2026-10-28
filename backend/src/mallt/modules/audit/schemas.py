import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from mallt.core.enums import ActorType


class AuditOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor_type: ActorType
    actor_id: uuid.UUID | None
    actor_username: str | None
    action: str
    target_type: str
    target_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_cursor: str | None = None
