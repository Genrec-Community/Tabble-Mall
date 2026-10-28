import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from mallt.core.enums import ActiveStatus
from mallt.core.rbac import SYSTEM_ROLES, ScopeType
from mallt.modules.iam.users import AssignmentInfo, StaffRecord
from mallt.modules.tenancy.schemas import Name


class StaffCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    display_name: Name
    email: str | None = Field(default=None, max_length=200)
    role_key: str = Field(min_length=1, max_length=40)


class RoleAssign(BaseModel):
    role_key: str = Field(min_length=1, max_length=40)
    scope_type: ScopeType
    scope_id: uuid.UUID | None = None  # omitted only for platform-level roles


class AssignmentOut(BaseModel):
    id: uuid.UUID
    role_key: str
    role_name: str
    scope_type: ScopeType
    organization_id: uuid.UUID | None
    mall_id: uuid.UUID | None
    store_id: uuid.UUID | None

    @classmethod
    def of(cls, a: AssignmentInfo) -> "AssignmentOut":
        return cls(
            id=a.id,
            role_key=a.role_key,
            role_name=SYSTEM_ROLES[a.role_key].name,
            scope_type=a.scope.type,
            organization_id=a.scope.organization_id,
            mall_id=a.scope.mall_id,
            store_id=a.scope.store_id,
        )


class StaffOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    status: ActiveStatus
    must_change_password: bool
    totp_enabled: bool
    last_login_at: datetime | None
    grants: list[AssignmentOut]

    @classmethod
    def of(cls, r: StaffRecord) -> "StaffOut":
        return cls(
            id=r.id,
            username=r.username,
            display_name=r.display_name,
            email=r.email,
            status=r.status,
            must_change_password=r.must_change_password,
            totp_enabled=r.totp_enabled,
            last_login_at=r.last_login_at,
            grants=[AssignmentOut.of(a) for a in r.assignments],
        )


class StaffCreatedOut(BaseModel):
    staff: StaffOut
    temp_password: str  # shown once; they must change it at first login


class TempPasswordOut(BaseModel):
    temp_password: str


class RoleOut(BaseModel):
    key: str
    name: str
    scope_type: ScopeType
    permissions: list[str]
    grantable_by: list[str]  # role keys whose holders may hand this role out
