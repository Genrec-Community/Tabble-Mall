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


class PaymentsOverviewOut(BaseModel):
    accounts: list[PayoutAccountOut]
    failed_tasks: list[PaymentTaskOut]


class PaymentConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]


class WebhookAckOut(BaseModel):
    ok: bool = True
