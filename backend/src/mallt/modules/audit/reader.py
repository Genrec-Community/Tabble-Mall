"""Reading the audit log. Kept apart from AuditService (the write side), which iam imports."""

import base64
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.errors import Unprocessable
from mallt.core.kv import KV
from mallt.core.rbac import P, Scope
from mallt.modules.audit.models import AuditLog
from mallt.modules.audit.repository import AuditRepository
from mallt.modules.audit.schemas import AuditOut, AuditPage
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.iam.users import IamUsers
from mallt.modules.tenancy.service import TenancyService


def encode_cursor(row: AuditLog) -> str:
    raw = f"{row.created_at.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, _, row_id = raw.partition("|")
        return datetime.fromisoformat(stamp), uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Unprocessable("invalid_cursor", "That page cursor is not valid.") from exc


class AuditReader:
    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.repo = AuditRepository(session)
        self.authz = AuthzService(session, kv)
        self.tenancy = TenancyService(session, kv)
        self.users = IamUsers(session)

    async def for_org(
        self, principal: Principal, org_id: uuid.UUID, cursor: str | None, limit: int
    ) -> AuditPage:
        scope: Scope = await self.tenancy.scope_for_org(org_id)  # 404 if it does not exist
        self.authz.require(principal, P.AUDIT_READ, scope)
        return await self._page(org_id, cursor, limit)

    async def everything(
        self,
        principal: Principal,
        org_id: uuid.UUID | None,
        cursor: str | None,
        limit: int,
    ) -> AuditPage:
        self.authz.require(principal, P.AUDIT_READ, Scope.platform())
        return await self._page(org_id, cursor, limit)

    async def _page(self, org_id: uuid.UUID | None, cursor: str | None, limit: int) -> AuditPage:
        before = decode_cursor(cursor) if cursor is not None else None
        rows = await self.repo.page(org_id, before, limit + 1)
        page = rows[:limit]
        names = await self.users.usernames_by_ids({r.actor_id for r in page if r.actor_id})
        items = [
            AuditOut(
                id=r.id,
                created_at=r.created_at,
                actor_type=r.actor_type,
                actor_id=r.actor_id,
                actor_username=names.get(r.actor_id) if r.actor_id else None,
                action=r.action,
                target_type=r.target_type,
                target_id=r.target_id,
                organization_id=r.organization_id,
                before=r.before,
                after=r.after,
            )
            for r in page
        ]
        return AuditPage(
            items=items, next_cursor=encode_cursor(page[-1]) if len(rows) > limit else None
        )
