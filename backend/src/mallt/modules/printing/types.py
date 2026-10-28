"""What printing needs to know about an order, without depending on the orders module."""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class PrintableLine:
    name: str
    variant_name: str
    quantity: int
    unit_price_paise: int
    line_total_paise: int
    tax_bps: int
    options: list[str] = field(default_factory=list)
    note: str | None = None
    allergens: str | None = None


@dataclass(frozen=True)
class PrintableOrder:
    id: uuid.UUID
    organization_id: uuid.UUID
    mall_id: uuid.UUID
    store_id: uuid.UUID
    store_name: str
    order_no: int
    order_date: date
    created_at: datetime
    customer_name: str | None
    prep_minutes: int
    note: str | None
    subtotal_paise: int
    tax_paise: int
    total_paise: int
    lines: list[PrintableLine]


@dataclass(frozen=True)
class PrintPrefs:
    auto_print: bool
    kot_when: str  # paid | accepted
    bill_when: str  # accepted | ready | picked_up | manual
    gstin: str | None
    fssai: str | None
    timezone: str
