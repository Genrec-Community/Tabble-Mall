import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

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


# ---- customers ----

Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class OtpRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=20)


class OtpRequested(BaseModel):
    expires_in: int


class OtpVerify(BaseModel):
    phone: str = Field(min_length=1, max_length=20)
    otp: str = Field(pattern=r"^\d{6}$")


class GoogleLogin(BaseModel):
    id_token: str = Field(min_length=1, max_length=4096)


class CustomerMe(BaseModel):
    id: uuid.UUID
    phone_masked: str | None
    has_phone: bool
    name: str | None
    email: str | None


class CustomerUpdate(BaseModel):
    name: PersonName | None = None
    email: Email | None = None
