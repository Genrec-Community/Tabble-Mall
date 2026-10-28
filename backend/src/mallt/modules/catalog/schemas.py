import re
import uuid
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from mallt.modules.catalog.enums import (
    FOOD_TYPES,
    PRINT_BILL_WHEN,
    PRINT_KOT_WHEN,
    Diet,
    StockMode,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Clock = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Paise = Annotated[int, Field(ge=0, le=10_000_000)]  # up to Rs 1,00,000
FONTS = ("system", "serif", "rounded", "mono")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Window(BaseModel):
    days: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    start: Clock
    end: Clock


class HoursWindow(BaseModel):
    days: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    open: Clock
    close: Clock


# ---- categories ----


class CategoryCreate(BaseModel):
    name: Name
    position: int = Field(default=0, ge=0, le=10_000)


class CategoryUpdate(BaseModel):
    name: Name | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)


class CategoryOut(_Out):
    id: uuid.UUID
    name: str
    position: int


# ---- products ----


class OptionIn(BaseModel):
    id: uuid.UUID | None = None
    name: Name
    price_delta_paise: int = Field(default=0, ge=0, le=1_000_000)
    is_available: bool = True


class OptionGroupIn(BaseModel):
    id: uuid.UUID | None = None
    name: Name
    min_select: int = Field(default=0, ge=0, le=20)
    max_select: int = Field(default=1, ge=1, le=20)
    options: list[OptionIn] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _bounds(self) -> "OptionGroupIn":
        if self.min_select > self.max_select or self.max_select > len(self.options):
            raise ValueError("select bounds must satisfy min <= max <= number of options")
        return self


class VariantIn(BaseModel):
    id: uuid.UUID | None = None
    name: Name
    price_paise: Paise
    stock_count: int | None = Field(default=None, ge=0, le=100_000)


class ProductIn(BaseModel):
    name: Name
    description: LongText | None = None
    category_id: uuid.UUID | None = None
    diet: Diet = Diet.VEG
    allergens: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = (
        None
    )
    prep_minutes: int = Field(default=10, ge=1, le=240)
    tax_bps: int = Field(default=500, ge=0, le=2800)
    stock_mode: StockMode = StockMode.MANUAL
    image_key: str | None = Field(default=None, max_length=300)
    position: int = Field(default=0, ge=0, le=10_000)
    windows: list[Window] = Field(default_factory=list, max_length=7)
    variants: list[VariantIn] = Field(min_length=1, max_length=12)
    option_groups: list[OptionGroupIn] = Field(default_factory=list, max_length=10)


class AvailabilityVariant(BaseModel):
    id: uuid.UUID
    stock_count: int = Field(ge=0, le=100_000)


class AvailabilityUpdate(BaseModel):
    is_available: bool | None = None
    variants: list[AvailabilityVariant] | None = None


class OptionOut(_Out):
    id: uuid.UUID
    name: str
    price_delta_paise: int
    is_available: bool


class OptionGroupOut(_Out):
    id: uuid.UUID
    name: str
    min_select: int
    max_select: int
    options: list[OptionOut]


class VariantOut(_Out):
    id: uuid.UUID
    name: str
    price_paise: int
    stock_count: int | None


class ProductOut(_Out):
    id: uuid.UUID
    store_id: uuid.UUID
    category_id: uuid.UUID | None
    name: str
    description: str | None
    diet: Diet
    allergens: str | None
    prep_minutes: int
    tax_bps: int
    stock_mode: StockMode
    is_available: bool
    image_key: str | None
    image_url: str | None = None
    position: int
    windows: list[Window]
    variants: list[VariantOut]
    option_groups: list[OptionGroupOut]


# ---- images ----


class ImagePresignIn(BaseModel):
    kind: Literal["product", "logo", "banner"]
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


class ImagePresignOut(BaseModel):
    url: str
    key: str
    headers: dict[str, str]
    expires_in: int
    public_url: str


# ---- store settings ----


class Theme(BaseModel):
    """Design tokens only: the storefront renders these through CSS variables."""

    primary: Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")] = "#111827"
    accent: Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")] = "#f97316"
    font: Literal["system", "serif", "rounded", "mono"] = "system"
    template: Literal[1, 2, 3] = 1


class SettingsUpdate(BaseModel):
    is_open: bool | None = None
    is_paused: bool | None = None
    hours: list[HoursWindow] | None = Field(default=None, max_length=14)
    timezone: str | None = None
    food_types: list[str] | None = Field(default=None, max_length=5)
    theme: Theme | None = None
    logo_key: str | None = Field(default=None, max_length=300)
    banner_key: str | None = Field(default=None, max_length=300)
    gstin: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True)] | None = None
    fssai: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    auto_print: bool | None = None
    kot_when: str | None = None
    bill_when: str | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("unknown timezone") from exc
        return v

    @field_validator("food_types")
    @classmethod
    def _food(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and (set(v) - set(FOOD_TYPES) or len(set(v)) != len(v)):
            raise ValueError(f"food_types must be unique values from {list(FOOD_TYPES)}")
        return v

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        if v and not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", v):
            raise ValueError("not a valid GSTIN")
        return v or None

    @field_validator("kot_when")
    @classmethod
    def _kot(cls, v: str | None) -> str | None:
        if v is not None and v not in PRINT_KOT_WHEN:
            raise ValueError(f"kot_when must be one of {list(PRINT_KOT_WHEN)}")
        return v

    @field_validator("bill_when")
    @classmethod
    def _bill(cls, v: str | None) -> str | None:
        if v is not None and v not in PRINT_BILL_WHEN:
            raise ValueError(f"bill_when must be one of {list(PRINT_BILL_WHEN)}")
        return v


class SettingsOut(_Out):
    store_id: uuid.UUID
    is_open: bool
    is_paused: bool
    hours: list[HoursWindow]
    timezone: str
    food_types: list[str]
    theme: Theme
    logo_key: str | None
    banner_key: str | None
    logo_url: str | None = None
    banner_url: str | None = None
    gstin: str | None
    fssai: str | None
    auto_print: bool
    kot_when: str
    bill_when: str
    accepting_orders: bool = False


# ---- public ----


class PublicStoreCardOut(BaseModel):
    slug: str
    name: str
    description: str | None
    food_types: list[str]
    logo_url: str | None
    accepting_orders: bool


class PublicOptionOut(BaseModel):
    id: uuid.UUID
    name: str
    price_delta_paise: int
    available: bool


class PublicOptionGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    min_select: int
    max_select: int
    options: list[PublicOptionOut]


class PublicVariantOut(BaseModel):
    id: uuid.UUID
    name: str
    price_paise: int
    available: bool


class PublicProductOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    diet: Diet
    allergens: str | None
    prep_minutes: int
    image_url: str | None
    available: bool
    unavailable_reason: Literal["sold_out", "not_now"] | None
    variants: list[PublicVariantOut]
    option_groups: list[PublicOptionGroupOut]


class PublicCategoryOut(BaseModel):
    id: uuid.UUID | None
    name: str
    products: list[PublicProductOut]


class PublicStoreOut(BaseModel):
    slug: str
    name: str
    description: str | None
    food_types: list[str]
    logo_url: str | None
    banner_url: str | None
    theme: Theme
    accepting_orders: bool
    hours: list[HoursWindow]


class PublicMenuOut(BaseModel):
    store: PublicStoreOut
    categories: list[PublicCategoryOut]


def theme_from(raw: dict[str, Any] | None) -> Theme:
    return Theme.model_validate(raw or {})


class PublicItemOut(BaseModel):
    """A dish on the mall home page, with the store it comes from."""

    store_slug: str
    store_name: str
    accepting_orders: bool
    product: PublicProductOut


class PublicItemsOut(BaseModel):
    items: list[PublicItemOut]
    next_cursor: uuid.UUID | None = None
