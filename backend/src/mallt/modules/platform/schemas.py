import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from mallt.core.enums import ActiveStatus


class FeaturesOut(BaseModel):
    """Public: which features are switched on right now."""

    flags: dict[str, bool]


class FeatureOut(BaseModel):
    key: str
    label: str
    description: str
    group: str
    default: bool
    enabled: bool


class FeatureUpdate(BaseModel):
    enabled: bool


class FeaturedSpotCreate(BaseModel):
    store_id: uuid.UUID
    starts_at: datetime | None = None  # now when left out
    ends_at: datetime | None = None  # never ends when left out
    amount_paise: int = Field(default=0, ge=0, le=10_000_000_00)
    note: str | None = Field(default=None, max_length=200)


class FeaturedSpotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    mall_id: uuid.UUID
    store_id: uuid.UUID
    store_name: str
    mall_name: str
    starts_at: datetime
    ends_at: datetime | None
    amount_paise: int
    note: str | None
    revoked_at: datetime | None
    live: bool


class DirectoryStoreOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: ActiveStatus
    featured: bool


class DirectoryMallOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: ActiveStatus
    stores: list[DirectoryStoreOut]


class DirectoryOrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: ActiveStatus
    malls: list[DirectoryMallOut]


class DirectoryOut(BaseModel):
    orgs: list[DirectoryOrgOut]
