import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActorType
from mallt.core.logging import get_client_ip, get_request_id
from mallt.core.rbac import Scope
from mallt.modules.audit.models import AuditLog
from mallt.modules.audit.repository import AuditRepository


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: uuid.UUID | None


class AuditService:
    """Appends audit rows inside the caller's transaction, so an action and its record commit
    or roll back together."""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = AuditRepository(session)

    async def record(
        self,
        *,
        actor: Actor,
        action: str,
        target_type: str,
        target_id: uuid.UUID | None,
        scope: Scope | None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self.repo.add(
            AuditLog(
                actor_type=actor.type,
                actor_id=actor.id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                organization_id=scope.organization_id if scope else None,
                mall_id=scope.mall_id if scope else None,
                store_id=scope.store_id if scope else None,
                before=before,
                after=after,
                ip=get_client_ip(),
                request_id=get_request_id(),
            )
        )
