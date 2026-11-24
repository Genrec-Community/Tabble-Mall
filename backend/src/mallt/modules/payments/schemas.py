import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from mallt.modules.payments.enums import PayoutStatus, TaskKind, TaskStatus


def _upper(pattern: str) -> Any:
    return StringConstraints(strip_whitespace=True, to_upper=True, pattern=pattern)


class PayoutAccountCreate(BaseModel):
    """A store's bank details for its Zoho connected account. Sent once to Zoho; MallT keeps only
    the masked parts."""

    model_config = ConfigDict(extra="forbid")

    account_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)
    ]
    email: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.\w+$"),
    ]
    pan: Annotated[str, _upper(r"^[A-Za-z]{5}[0-9]{4}[A-Za-z]$")]
    mcc: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{4}$")] = Field(
        default="5814", description="Merchant category code; 5814 = fast food restaurants"
    )
    business_description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)
    ]
    ifsc: Annotated[str, _upper(r"^[A-Za-z]{4}0[A-Za-z0-9]{6}$")]
    account_number: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{9,18}$")]


class PayoutAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: uuid.UUID
    provider: str
    account_name: str
    email: str
    pan_masked: str
    bank_masked: str
    ifsc: str
    mcc: str
    status: PayoutStatus
    review_status: str
    created_at: datetime
    updated_at: datetime


class PaymentTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_id: uuid.UUID
    customer_order_id: uuid.UUID
    store_order_id: uuid.UUID
    kind: TaskKind
    status: TaskStatus
    amount_paise: int
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    next_attempt_at: datetime
    order_label: str | None = None
    store_name: str | None = None
    provider_ref: str | None = None


class PaymentsOverviewOut(BaseModel):
    accounts: list[PayoutAccountOut]
    failed_tasks: list[PaymentTaskOut]
    retrying_tasks: list[PaymentTaskOut] = Field(default_factory=list)


class StorePayoutSummaryOut(BaseModel):
    """All amounts in paise, over the store's whole history."""

    sales_paise: int  # what customers paid for this store's items (paid orders)
    fees_paise: int  # the 0.50% gateway fee on those
    paid_out_paise: int  # sent to the store's bank account
    on_the_way_paise: int  # queued or being retried
    failed_paise: int  # transfers that need a person (see the platform admin)
    taken_back_paise: int  # transfers reversed because the order was refunded
    refunded_paise: int  # returned to customers


class StorePayoutRowOut(BaseModel):
    store_order_id: uuid.UUID
    order_label: str | None
    created_at: datetime
    order_total_paise: int
    fee_paise: int
    payout_paise: int
    transfer_status: TaskStatus
    refund_paise: int | None = None
    refund_status: TaskStatus | None = None


class StorePayoutsOut(BaseModel):
    summary: StorePayoutSummaryOut
    items: list[StorePayoutRowOut]
    next_cursor: uuid.UUID | None = None


class PaymentConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]


class WebhookAckOut(BaseModel):
    ok: bool = True
