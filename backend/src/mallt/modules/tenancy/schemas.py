import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from mallt.core.enums import ActiveStatus

Slug = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9-]{3,60}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- organizations ----


class OwnerCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    display_name: Name
    email: str | None = Field(default=None, max_length=200)


class OrgCreate(BaseModel):
    name: Name
    slug: Slug
    owner: OwnerCreate


class OrgUpdate(BaseModel):
    name: Name | None = None
    accept_timeout_s: int | None = Field(default=None, ge=60, le=3600)
    commission_bps: int | None = Field(default=None, ge=0, le=10_000)


class OrgOut(_Out):
    id: uuid.UUID
    name: str
    slug: str
    status: ActiveStatus
    commission_bps: int
    accept_timeout_s: int
    created_at: datetime


class OrgCreatedOut(BaseModel):
    org: OrgOut
    owner_username: str
    temp_password: str  # shown once; the owner must change it at first login


# ---- malls ----


class MallCreate(BaseModel):
    name: Name
    slug: Slug
    city: Name | None = None
    address: Text | None = None


class MallUpdate(BaseModel):
    name: Name | None = None
    city: Name | None = None
    address: Text | None = None


class MallOut(_Out):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    status: ActiveStatus
    city: str | None
    address: str | None


# ---- stores ----


class StoreCreate(BaseModel):
    name: Name
    slug: Slug
    description: Text | None = None


class StoreUpdate(BaseModel):
    name: Name | None = None
    description: Text | None = None
    commission_bps: int | None = Field(default=None, ge=0, le=10_000)


class StoreOut(_Out):
    id: uuid.UUID
    organization_id: uuid.UUID
    mall_id: uuid.UUID
    name: str
    slug: str
    status: ActiveStatus
    description: str | None
    commission_bps: int | None


# ---- public (no auth): only what the QR page needs ----


class PublicStoreOut(_Out):
    name: str
    slug: str
    description: str | None


class PublicMallOut(BaseModel):
    name: str
    slug: str
    city: str | None
    stores: list[PublicStoreOut]
