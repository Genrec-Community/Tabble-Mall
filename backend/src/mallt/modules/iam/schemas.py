import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from mallt.core.rbac import ScopeType


class StaffLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=10)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - the OAuth token type, not a secret
    expires_in: int


class GrantOut(BaseModel):
    role_key: str
    scope_type: ScopeType
    organization_id: uuid.UUID | None
    mall_id: uuid.UUID | None
    store_id: uuid.UUID | None
    permissions: list[str]


class StaffMe(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    must_change_password: bool
    totp_enabled: bool
    grants: list[GrantOut]


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpConfirm(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    user_agent: str | None
    ip: str | None
    current: bool
