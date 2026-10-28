import uuid

from fastapi import APIRouter, Response, status

from mallt.core.db import SessionDep
from mallt.core.enums import ActiveStatus
from mallt.core.rbac import ScopeType
from mallt.modules.iam.deps import KvDep, SettingsDep, Staff
from mallt.modules.staff.schemas import (
    AssignmentOut,
    RoleAssign,
    RoleOut,
    StaffCreate,
    StaffCreatedOut,
    StaffOut,
    TempPasswordOut,
)
from mallt.modules.staff.service import StaffService

router = APIRouter(prefix="/api/v1", tags=["staff"])


async def _list(
    principal: Staff,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    t: ScopeType,
    i: uuid.UUID,
) -> list[StaffOut]:
    records = await StaffService(session, settings, kv).list_staff(principal, t, i)
    return [StaffOut.of(r) for r in records]


async def _create(
    principal: Staff,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    t: ScopeType,
    i: uuid.UUID,
    body: StaffCreate,
) -> StaffCreatedOut:
    record, temp = await StaffService(session, settings, kv).create_staff(principal, t, i, body)
    return StaffCreatedOut(staff=StaffOut.of(record), temp_password=temp)


# One pair of routes per scope level; the scope id in the path decides where the person works.


@router.get("/orgs/{org_id}/staff")
async def list_org_staff(
    org_id: uuid.UUID, principal: Staff, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> list[StaffOut]:
    return await _list(principal, session, settings, kv, ScopeType.ORGANIZATION, org_id)


@router.get("/malls/{mall_id}/staff")
async def list_mall_staff(
    mall_id: uuid.UUID, principal: Staff, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> list[StaffOut]:
    return await _list(principal, session, settings, kv, ScopeType.MALL, mall_id)


@router.get("/stores/{store_id}/staff")
async def list_store_staff(
    store_id: uuid.UUID, principal: Staff, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> list[StaffOut]:
    return await _list(principal, session, settings, kv, ScopeType.STORE, store_id)


@router.post("/orgs/{org_id}/staff", status_code=status.HTTP_201_CREATED)
async def create_org_staff(
    org_id: uuid.UUID,
    body: StaffCreate,
    principal: Staff,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
) -> StaffCreatedOut:
    return await _create(principal, session, settings, kv, ScopeType.ORGANIZATION, org_id, body)


@router.post("/malls/{mall_id}/staff", status_code=status.HTTP_201_CREATED)
async def create_mall_staff(
    mall_id: uuid.UUID,
    body: StaffCreate,
    principal: Staff,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
) -> StaffCreatedOut:
    return await _create(principal, session, settings, kv, ScopeType.MALL, mall_id, body)


@router.post("/stores/{store_id}/staff", status_code=status.HTTP_201_CREATED)
async def create_store_staff(
    store_id: uuid.UUID,
    body: StaffCreate,
    principal: Staff,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
) -> StaffCreatedOut:
    return await _create(principal, session, settings, kv, ScopeType.STORE, store_id, body)


@router.post("/staff/{staff_id}/roles", status_code=status.HTTP_201_CREATED)
async def assign_role(
    staff_id: uuid.UUID,
    body: RoleAssign,
    principal: Staff,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
) -> AssignmentOut:
    row = await StaffService(session, settings, kv).assign_role(principal, staff_id, body)
    return AssignmentOut.of(row)


@router.delete("/staff/{staff_id}/roles/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_role(
    staff_id: uuid.UUID,
    assignment_id: uuid.UUID,
    principal: Staff,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
) -> Response:
    await StaffService(session, settings, kv).revoke_role(principal, staff_id, assignment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/staff/{staff_id}/suspend")
async def suspend_staff(
    staff_id: uuid.UUID, principal: Staff, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> StaffOut:
    record = await StaffService(session, settings, kv).set_status(
        principal, staff_id, ActiveStatus.SUSPENDED
    )
    return StaffOut.of(record)


@router.post("/staff/{staff_id}/activate")
async def activate_staff(
    staff_id: uuid.UUID, principal: Staff, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> StaffOut:
    record = await StaffService(session, settings, kv).set_status(
        principal, staff_id, ActiveStatus.ACTIVE
    )
    return StaffOut.of(record)


@router.post("/staff/{staff_id}/reset-password")
async def reset_staff_password(
    staff_id: uuid.UUID, principal: Staff, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> TempPasswordOut:
    temp = await StaffService(session, settings, kv).reset_password(principal, staff_id)
    return TempPasswordOut(temp_password=temp)


@router.get("/roles")
async def list_roles(principal: Staff) -> list[RoleOut]:
    return [
        RoleOut(
            key=r.key,
            name=r.name,
            scope_type=r.scope_type,
            permissions=sorted(p.value for p in r.permissions),
        )
        for r in StaffService.roles()
    ]
