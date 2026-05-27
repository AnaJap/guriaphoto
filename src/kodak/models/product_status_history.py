"""Product activity-status audit log."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class ProductStatusHistory(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    old_active: bool
    new_active: bool
    changed_by_user_id: int | None = Field(
        default=None, foreign_key="user.id", index=True
    )
    changed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
