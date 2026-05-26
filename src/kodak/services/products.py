"""Product management — admin CRUD with price versioning."""

from __future__ import annotations

import datetime as dt

from sqlmodel import Session, func, select

from kodak.access import require_write_access
from kodak.models.price_history import ProductPriceHistory
from kodak.models.product import Product
from kodak.models.transaction import LineItem
from kodak.models.user import User


def list_all_products_admin(session: Session) -> list[Product]:
    """All products including inactive, ordered by sort_order then name."""
    return list(
        session.exec(select(Product).order_by(Product.sort_order, Product.name)).all()
    )


def save_product(
    session: Session,
    product: Product,
    changed_by_user_id: int | None = None,
) -> Product:
    """Create or update a product.

    Price-change history must be recorded by the caller *before* mutating
    the product object (see products_view.py on_save), because once the
    in-session object is modified the old value is no longer accessible here.
    """
    require_write_access()
    product.updated_at = dt.datetime.now(dt.UTC)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def record_price_change(
    session: Session,
    product_id: int,
    old_price,
    new_price,
    changed_by_user_id: int | None = None,
) -> None:
    """Write a ProductPriceHistory row. Call before mutating the product."""
    require_write_access()
    session.add(
        ProductPriceHistory(
            product_id=product_id,
            old_price=old_price,
            new_price=new_price,
            changed_by_user_id=changed_by_user_id,
        )
    )


def product_usage_count(session: Session, product_id: int) -> int:
    """Return the number of LineItems that reference this product."""
    return session.exec(
        select(func.count()).where(LineItem.product_id == product_id)
    ).one()


def delete_product(session: Session, product_id: int) -> str:
    """Delete a product.

    - If it has been sold at least once: marks inactive (soft delete).
    - If it has never been sold: removes the row entirely (hard delete).

    Returns 'deactivated' or 'deleted'.
    """
    require_write_access()
    product = session.get(Product, product_id)
    if product is None:
        return "not_found"

    if product_usage_count(session, product_id) > 0:
        product.active = False
        product.updated_at = dt.datetime.now(dt.UTC)
        session.add(product)
        session.commit()
        return "deactivated"
    else:
        session.delete(product)
        session.commit()
        return "deleted"


def get_price_history(
    session: Session, product_id: int
) -> list[tuple[ProductPriceHistory, User | None]]:
    """Return price-change records for a product, newest first."""
    rows = list(
        session.exec(
            select(ProductPriceHistory)
            .where(ProductPriceHistory.product_id == product_id)
            .order_by(ProductPriceHistory.changed_at.desc())
        ).all()
    )
    if not rows:
        return []

    user_ids = {r.changed_by_user_id for r in rows if r.changed_by_user_id}
    users: dict[int, User] = {}
    if user_ids:
        users = {
            u.id: u
            for u in session.exec(select(User).where(User.id.in_(user_ids))).all()
        }

    return [(r, users.get(r.changed_by_user_id)) for r in rows]
