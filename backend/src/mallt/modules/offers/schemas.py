import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Code = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9]{3,20}$"),
]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _OfferFields(BaseModel):
    title: Title
    code: Code | None = None
    kind: Literal["percent", "flat"]
    # percent: basis points (1000 = 10%); flat: paise
    value: int = Field(gt=0, le=10_000_000)
    max_discount_paise: int | None = Field(default=None, gt=0)
    min_subtotal_paise: int = Field(default=0, ge=0)
    per_customer_limit: int | None = Field(default=None, ge=1, le=100)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _check(self) -> "_OfferFields":
        if self.kind == "percent" and self.value > 10_000:
            raise ValueError("A percentage offer can be at most 100%.")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("The offer must end after it starts.")
        return self


class OfferCreate(_OfferFields):
    pass


class OfferUpdate(_OfferFields):
    pass


class OfferActiveUpdate(BaseModel):
    is_active: bool


class OfferOut(_Out):
    id: uuid.UUID
    store_id: uuid.UUID
    title: str
    code: str | None
    kind: str
    value: int
    max_discount_paise: int | None
    min_subtotal_paise: int
    per_customer_limit: int | None
    starts_at: datetime | None
    ends_at: datetime | None
    is_active: bool
    created_at: datetime


class ComboItemIn(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=10)


class ComboCreate(BaseModel):
    name: Title
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = (
        None
    )
    price_paise: int = Field(gt=0)
    items: list[ComboItemIn] = Field(min_length=2, max_length=8)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True


class ComboUpdate(ComboCreate):
    pass


class ComboItemOut(BaseModel):
    product_id: uuid.UUID
    product_name: str
    store_id: uuid.UUID
    store_slug: str
    store_name: str
    quantity: int
    regular_price_paise: int  # the item's lowest price now, for "save ₹X"


class ComboOut(BaseModel):
    id: uuid.UUID
    mall_id: uuid.UUID
    name: str
    description: str | None
    price_paise: int
    regular_price_paise: int
    starts_at: datetime | None
    ends_at: datetime | None
    is_active: bool
    items: list[ComboItemOut]


class PublicOfferOut(BaseModel):
    """An offer a customer may see: automatic ones and coupons alike."""

    id: uuid.UUID
    store_slug: str
    store_name: str
    title: str
    code: str | None
    kind: str
    value: int
    max_discount_paise: int | None
    min_subtotal_paise: int
    ends_at: datetime | None


class PublicOffersOut(BaseModel):
    offers: list[PublicOfferOut]
    combos: list[ComboOut]
