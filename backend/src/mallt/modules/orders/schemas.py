import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from mallt.modules.orders.enums import CustomerOrderStatus, StoreOrderStatus

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=140)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- cart ----


class CartLineIn(BaseModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID
    option_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    quantity: int = Field(ge=1, le=20)
    note: Note | None = None


class CartLineUpdate(BaseModel):
    quantity: int | None = Field(default=None, ge=0, le=20)  # 0 removes the line
    note: Note | None = None


LineProblem = Literal["unavailable", "sold_out", "store_closed"]


class CartLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    variant_name: str
    diet: str
    options: list[str]
    quantity: int
    unit_price_paise: int
    line_total_paise: int
    note: str | None
    problem: LineProblem | None


class CartStoreOut(BaseModel):
    store_slug: str
    store_name: str
    accepting_orders: bool
    subtotal_paise: int
    prep_minutes: int
    lines: list[CartLineOut]


class CartOut(BaseModel):
    mall_slug: str
    stores: list[CartStoreOut]
    total_paise: int
    can_checkout: bool


class CheckoutIn(BaseModel):
    note: Note | None = None


# ---- orders ----


class OrderLineOut(_Out):
    name: str
    variant_name: str
    diet: str
    options: list[dict[str, object]]
    quantity: int
    unit_price_paise: int
    line_total_paise: int
    note: str | None


class OrderStepOut(BaseModel):
    status: StoreOrderStatus
    at: datetime


class CustomerStoreOrderOut(BaseModel):
    id: uuid.UUID
    store_slug: str
    store_name: str
    status: StoreOrderStatus
    order_no: int
    pickup_code: str
    total_paise: int
    tax_paise: int
    prep_minutes: int
    accept_by: datetime | None
    reason: str | None
    note: str | None
    created_at: datetime
    lines: list[OrderLineOut]
    steps: list[OrderStepOut]


class CustomerOrderOut(BaseModel):
    id: uuid.UUID
    status: CustomerOrderStatus
    total_paise: int
    created_at: datetime
    mall_slug: str | None = None
    stores: list[CustomerStoreOrderOut]


class StoreOrderOut(BaseModel):
    """What a store sees. The pickup code is deliberately absent: only the customer has it."""

    id: uuid.UUID
    store_id: uuid.UUID
    order_no: int
    status: StoreOrderStatus
    customer_name: str | None
    customer_phone: str | None
    total_paise: int
    tax_paise: int
    prep_minutes: int
    accept_by: datetime | None
    accepted_at: datetime | None
    ready_at: datetime | None
    picked_up_at: datetime | None
    reason: str | None
    note: str | None
    created_at: datetime
    lines: list[OrderLineOut]
    steps: list[OrderStepOut]


class ReasonIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class PickupIn(BaseModel):
    code: Annotated[str, StringConstraints(pattern=r"^\d{4}$")]
