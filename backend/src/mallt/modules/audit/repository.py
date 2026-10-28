import uuid
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.audit.models import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, entry: AuditLog) -> None:
        self.session.add(entry)

    async def page(
        self,
        organization_id: uuid.UUID | None,
        before: tuple[datetime, uuid.UUID] | None,
        limit: int,
    ) -> list[AuditLog]:
        """Newest first. ``before`` is the (created_at, id) of the last row already seen."""
        stmt = (
            select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
        )
        if organization_id is not None:
            stmt = stmt.where(AuditLog.organization_id == organization_id)
        if before is not None:
            stmt = stmt.where(tuple_(AuditLog.created_at, AuditLog.id) < tuple_(*before))
        return list((await self.session.execute(stmt)).scalars())
