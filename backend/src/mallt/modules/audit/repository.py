from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.audit.models import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, entry: AuditLog) -> None:
        self.session.add(entry)
