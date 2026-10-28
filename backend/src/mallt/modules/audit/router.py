import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from mallt.core.db import SessionDep
from mallt.modules.audit.reader import AuditReader
from mallt.modules.audit.schemas import AuditPage
from mallt.modules.iam.deps import KvDep, Staff

router = APIRouter(prefix="/api/v1", tags=["audit"])

Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(min_length=1, max_length=200)]


@router.get("/orgs/{org_id}/audit")
async def list_org_audit(
    org_id: uuid.UUID,
    principal: Staff,
    session: SessionDep,
    kv: KvDep,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> AuditPage:
    return await AuditReader(session, kv).for_org(principal, org_id, cursor, limit)


@router.get("/admin/audit")
async def list_all_audit(
    principal: Staff,
    session: SessionDep,
    kv: KvDep,
    organization_id: uuid.UUID | None = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> AuditPage:
    return await AuditReader(session, kv).everything(principal, organization_id, cursor, limit)
