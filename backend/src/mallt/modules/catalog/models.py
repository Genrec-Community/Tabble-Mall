import uuid
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mallt.core.db import Base, IdMixin, TimestampMixin
from mallt.core.enums import text_enum
from mallt.modules.catalog.enums import Diet, StockMode


class _StoreOwned:
    """Every store-owned table carries the full tenant chain (AGENTS.md §5)."""

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), index=True, nullable=False
    )
    mall_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("malls.id"), index=True, nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stores.id"), index=True, nullable=False)


class StoreSettings(IdMixin, TimestampMixin, _StoreOwned, Base):
    """One row per store (created on first read). Theme is design tokens only, never CSS."""

    __tablename__ = "store_settings"
    __table_args__ = (UniqueConstraint("store_id", name="uq_store_settings_store_id"),)

    is_open: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # [{"days": [0..6], "open": "09:00", "close": "22:00"}], local time; empty = always open.
    hours: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    timezone: Mapped[str] = mapped_column(
        Text, default="Asia/Kolkata", server_default="Asia/Kolkata"
    )
    food_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    theme: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    logo_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    banner_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    gstin: Mapped[str | None] = mapped_column(Text, nullable=True)
    fssai: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Printing preferences (the print agent itself lives in the printing module).
    auto_print: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    kot_when: Mapped[str] = mapped_column(Text, default="accepted", server_default="accepted")
    bill_when: Mapped[str] = mapped_column(Text, default="ready", server_default="ready")


class MenuCategory(IdMixin, TimestampMixin, _StoreOwned, Base):
    __tablename__ = "menu_categories"
    __table_args__ = (
        UniqueConstraint("store_id", "name", name="uq_menu_categories_store_id_name"),
    )

    name: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Product(IdMixin, TimestampMixin, _StoreOwned, Base):
    __tablename__ = "products"

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("menu_categories.id", ondelete="SET NULL"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    diet: Mapped[Diet] = mapped_column(text_enum(Diet, "product_diet"), default=Diet.VEG)
    allergens: Mapped[str | None] = mapped_column(Text, nullable=True)
    prep_minutes: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    tax_bps: Mapped[int] = mapped_column(Integer, default=500, server_default="500")
    stock_mode: Mapped[StockMode] = mapped_column(
        text_enum(StockMode, "product_stock_mode"), default=StockMode.MANUAL
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    image_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # [{"days": [0..6], "start": "07:00", "end": "11:00"}]; empty = whenever the store is open.
    windows: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    variants: Mapped[list["ProductVariant"]] = relationship(
        order_by="ProductVariant.position", cascade="all, delete-orphan", lazy="raise"
    )
    option_groups: Mapped[list["OptionGroup"]] = relationship(
        order_by="OptionGroup.position", cascade="all, delete-orphan", lazy="raise"
    )


class ProductVariant(IdMixin, TimestampMixin, _StoreOwned, Base):
    __tablename__ = "product_variants"

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    price_paise: Mapped[int] = mapped_column(BigInteger)
    # Only meaningful when the product's stock_mode is COUNTED.
    stock_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class OptionGroup(IdMixin, TimestampMixin, _StoreOwned, Base):
    __tablename__ = "option_groups"

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    min_select: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_select: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    options: Mapped[list["Option"]] = relationship(
        order_by="Option.position", cascade="all, delete-orphan", lazy="raise"
    )


class Option(IdMixin, TimestampMixin, _StoreOwned, Base):
    __tablename__ = "options"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("option_groups.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    price_delta_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
