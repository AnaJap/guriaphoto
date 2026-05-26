"""Price lookup and line-item computation."""

from __future__ import annotations

from decimal import Decimal

from sqlmodel import Session, select

from kodak.models.product import Product


def get_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError(f"Product {product_id} not found")
    return product


def compute_line_total(unit_price: Decimal, quantity: int) -> Decimal:
    return (unit_price * quantity).quantize(Decimal("0.01"))


def list_active_products(session: Session) -> list[Product]:
    return list(session.exec(select(Product).where(Product.active == True).order_by(Product.sort_order, Product.name)).all())
