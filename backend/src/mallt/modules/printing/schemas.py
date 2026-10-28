import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from mallt.modules.printing.enums import JobKind, JobStatus, PrinterConnection, PrinterRole

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Scale = Field(default=None, ge=1, le=4)
Str20 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]
Str60 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)]
Str120 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Str200 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Target = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
PaperWidth = Literal[32, 42, 48]  # characters per line: 58 mm, 72 mm, 80 mm


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- agents ----


class AgentCreate(_Strict):
    name: Name


class AgentOut(_Out):
    id: uuid.UUID
    name: str
    is_active: bool
    token_prefix: str
    last_seen_at: datetime | None
    version: str | None
    online: bool = False
    created_at: datetime


class AgentCreatedOut(BaseModel):
    agent: AgentOut
    token: str  # shown once; the server keeps only a hash


# ---- detected printers ----


class DetectedPrinterOut(BaseModel):
    agent_id: uuid.UUID
    agent_name: str
    key: str
    name: str
    connection: PrinterConnection
    target: str
    driver: str | None
    is_default: bool
    likely_thermal: bool


class ScanOut(BaseModel):
    requested: bool


# ---- printers ----


class PrinterLayout(_Strict):
    """Per-printer hardware layout. Only fields that are set are stored."""

    font: Literal["a", "b"] | None = None
    text_width: int | None = Scale
    text_height: int | None = Scale
    heading_width: int | None = Scale
    heading_height: int | None = Scale
    item_width: int | None = Scale
    item_height: int | None = Scale
    line_spacing: int | None = Field(default=None, ge=0, le=255)
    left_margin: int | None = Field(default=None, ge=0, le=600)
    print_width_dots: int | None = Field(default=None, ge=96, le=832)
    rule_char: Literal["-", "=", "*", "_", "."] | None = None
    feed_before: int | None = Field(default=None, ge=0, le=10)
    feed_after: int | None = Field(default=None, ge=0, le=20)
    cut: Literal["full", "partial", "none"] | None = None
    copies: int | None = Field(default=None, ge=1, le=5)
    qr_size: int | None = Field(default=None, ge=2, le=16)
    open_drawer: bool | None = None
    beep: bool | None = None
    bold_items: bool | None = None

    def stored(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class PrinterCreate(_Strict):
    name: Name
    role: PrinterRole = PrinterRole.KITCHEN
    connection: PrinterConnection
    target: Target
    paper_width: PaperWidth = 32
    layout: PrinterLayout | None = None

    @field_validator("target")
    @classmethod
    def _no_control_chars(cls, v: str) -> str:
        if any(ord(c) < 32 for c in v):
            raise ValueError("target contains control characters")
        return v


class PrinterUpdate(_Strict):
    name: Name | None = None
    role: PrinterRole | None = None
    target: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    paper_width: PaperWidth | None = None
    layout: PrinterLayout | None = None
    is_active: bool | None = None


class PrinterOut(_Out):
    id: uuid.UUID
    name: str
    role: PrinterRole
    connection: PrinterConnection
    target: str
    paper_width: int
    layout: PrinterLayout
    is_active: bool
    last_printed_at: datetime | None


# ---- design (bill header/footer/logo and which lines print) ----


class SlipOptions(_Strict):
    # bill: which parts print
    show_logo: bool | None = None
    show_customer: bool | None = None
    show_unit_price: bool | None = None
    show_item_notes: bool | None = None
    show_tax_breakdown: bool | None = None
    show_invoice_no: bool | None = None
    show_item_numbers: bool | None = None
    show_date: bool | None = None
    # bill: what it is called
    bill_title: str | None = Field(default=None, max_length=24)
    tax_invoice_title: str | None = Field(default=None, max_length=24)
    subtotal_label: str | None = Field(default=None, max_length=20)
    total_label: str | None = Field(default=None, max_length=20)
    order_label: str | None = Field(default=None, max_length=16)
    currency_symbol: str | None = Field(default=None, max_length=4)
    # kitchen ticket
    ticket_title: str | None = Field(default=None, max_length=24)
    ticket_show_store: bool | None = None
    ticket_show_time: bool | None = None
    ticket_show_eta: bool | None = None
    ticket_show_customer: bool | None = None
    ticket_show_allergens: bool | None = None

    @field_validator(
        "bill_title",
        "tax_invoice_title",
        "subtotal_label",
        "total_label",
        "order_label",
        "currency_symbol",
        "ticket_title",
    )
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v is not None else None

    def stored(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v not in (None, "")}


class DesignIn(_Strict):
    header_name: Str60 | None = None
    header_address: Str200 | None = None
    header_phone: Str20 | None = None
    header_extra: Str60 | None = None
    footer_text: Str120 | None = None
    options: SlipOptions = SlipOptions()


class DesignOut(BaseModel):
    header_name: str | None
    header_address: str | None
    header_phone: str | None
    header_extra: str | None
    footer_text: str | None
    options: SlipOptions
    has_logo: bool


# ---- jobs ----


class PrintJobOut(_Out):
    id: uuid.UUID
    printer_id: uuid.UUID
    store_order_id: uuid.UUID | None
    kind: JobKind
    status: JobStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    acked_at: datetime | None


class ReprintIn(_Strict):
    what: Literal["ticket", "bill"]
