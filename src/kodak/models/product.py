"""Product catalog — photo prints, enlargements, frames, lamination, etc.

Each product carries a current unit price. When a line item is written,
the price is snapshotted onto the line item so historical totals never
shift when the price list is updated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel, UniqueConstraint

from kodak.models.enums import ProductCategory


class Product(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("category", "size_label", name="uq_product_cat_size"),)

    id: int | None = Field(default=None, primary_key=True)
    category: ProductCategory = Field(index=True)
    name: str
    size_label: str | None = Field(default=None, index=True)
    unit_price: Decimal = Field(default=Decimal("0"), max_digits=10, decimal_places=2)
    sort_order: int = Field(default=0)
    stock_item_id: int | None = Field(default=None, foreign_key="stockitem.id", index=True)
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
