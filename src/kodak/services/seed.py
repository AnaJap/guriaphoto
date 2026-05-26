"""Default product catalog for გურიაფოტო კოდაკი.

Prices are placeholder starting points — update them via the Products tab.
seed_products() is incremental: it only inserts rows that don't exist yet,
so re-running never overwrites prices Archil has already edited.
"""

from __future__ import annotations

from decimal import Decimal

from sqlmodel import Session, and_, select

from kodak.access import require_write_access
from kodak.models.enums import ProductCategory
from kodak.models.product import Product

_PRODUCTS = [
    # ── ფოტო სურათი ───────────────────────────────────────────────────
    dict(category=ProductCategory.photo, name="პასპორტი",   size_label="3×4",   price="1.50", sort=10),
    dict(category=ProductCategory.photo, name="ფოტო",       size_label="4×6",   price="2.00", sort=11),
    dict(category=ProductCategory.photo, name="ფოტო",       size_label="9×13",  price="2.50", sort=12),
    dict(category=ProductCategory.photo, name="ფოტო",       size_label="10×15", price="3.00", sort=13),
    dict(category=ProductCategory.photo, name="ფოტო",       size_label="13×18", price="5.00", sort=14),
    dict(category=ProductCategory.photo, name="ფოტო",       size_label="15×21", price="7.00", sort=15),
    dict(category=ProductCategory.photo, name="ფოტო",       size_label="20×30", price="9.00", sort=16),
    dict(category=ProductCategory.photo, name="ფოტო",       size_label="30×40", price="14.00", sort=17),

    # ── გადიდება ───────────────────────────────────────────────────────
    dict(category=ProductCategory.enlargement, name="გადიდება", size_label="A4",    price="5.00",  sort=20),
    dict(category=ProductCategory.enlargement, name="გადიდება", size_label="A3",    price="8.00",  sort=21),
    dict(category=ProductCategory.enlargement, name="გადიდება", size_label="30×40", price="15.00", sort=22),
    dict(category=ProductCategory.enlargement, name="გადიდება", size_label="40×50", price="22.00", sort=23),
    dict(category=ProductCategory.enlargement, name="გადიდება", size_label="50×70", price="30.00", sort=24),
    dict(category=ProductCategory.enlargement, name="გადიდება", size_label="60×90", price="45.00", sort=25),

    # ── ჩარჩო ─────────────────────────────────────────────────────────
    dict(category=ProductCategory.frame, name="ჩარჩო", size_label="9×13",  price="6.00",  sort=30),
    dict(category=ProductCategory.frame, name="ჩარჩო", size_label="10×15", price="8.00",  sort=31),
    dict(category=ProductCategory.frame, name="ჩარჩო", size_label="13×18", price="12.00", sort=32),
    dict(category=ProductCategory.frame, name="ჩარჩო", size_label="15×21", price="15.00", sort=33),
    dict(category=ProductCategory.frame, name="ჩარჩო", size_label="20×30", price="20.00", sort=34),
    dict(category=ProductCategory.frame, name="ჩარჩო", size_label="30×40", price="30.00", sort=35),
    dict(category=ProductCategory.frame, name="ჩარჩო", size_label="A4",    price="14.00", sort=36),
    dict(category=ProductCategory.frame, name="ჩარჩო", size_label="A3",    price="22.00", sort=37),

    # ── ლამინირება ─────────────────────────────────────────────────────
    dict(category=ProductCategory.lamination, name="ლამინირება", size_label="სავიზიტო", price="0.50", sort=40),
    dict(category=ProductCategory.lamination, name="ლამინირება", size_label="A6",       price="1.50", sort=41),
    dict(category=ProductCategory.lamination, name="ლამინირება", size_label="A5",       price="2.50", sort=42),
    dict(category=ProductCategory.lamination, name="ლამინირება", size_label="A4",       price="4.00", sort=43),
    dict(category=ProductCategory.lamination, name="ლამინირება", size_label="A3",       price="6.00", sort=44),
    dict(category=ProductCategory.lamination, name="ლამინირება", size_label="A2",       price="10.00", sort=45),

    # ── ქსეროქსი ──────────────────────────────────────────────────────
    dict(category=ProductCategory.photocopy, name="ქსეროქსი",  size_label="A4 შავ-თეთრი", price="0.20", sort=50),
    dict(category=ProductCategory.photocopy, name="ქსეროქსი",  size_label="A4 ფერადი",    price="0.50", sort=51),
    dict(category=ProductCategory.photocopy, name="ქსეროქსი",  size_label="A3 შავ-თეთრი", price="0.40", sort=52),
    dict(category=ProductCategory.photocopy, name="ქსეროქსი",  size_label="A3 ფერადი",    price="1.00", sort=53),
    dict(category=ProductCategory.photocopy, name="სკანირება",  size_label="A4",           price="0.50", sort=54),
    dict(category=ProductCategory.photocopy, name="სკანირება",  size_label="A3",           price="1.00", sort=55),

    # ── ალბომი ────────────────────────────────────────────────────────
    dict(category=ProductCategory.album, name="ალბომი", size_label="პატარა",   price="15.00", sort=60),
    dict(category=ProductCategory.album, name="ალბომი", size_label="საშუალო",  price="25.00", sort=61),
    dict(category=ProductCategory.album, name="ალბომი", size_label="დიდი",     price="40.00", sort=62),
    dict(category=ProductCategory.album, name="ფოტოწიგნი", size_label="A4",   price="50.00", sort=63),

    # ── CD / DVD ──────────────────────────────────────────────────────
    dict(category=ProductCategory.cd, name="CD",  size_label=None,  price="3.00", sort=70),
    dict(category=ProductCategory.cd, name="DVD", size_label="DVD", price="5.00", sort=71),

    # ── სხვა ──────────────────────────────────────────────────────────
    dict(category=ProductCategory.other, name="USB ფლეში",    size_label=None,       price="10.00", sort=80),
    dict(category=ProductCategory.other, name="კალენდარი",    size_label="კედლის",  price="20.00", sort=81),
    dict(category=ProductCategory.other, name="კალენდარი",    size_label="მაგიდის", price="15.00", sort=82),
    dict(category=ProductCategory.other, name="ფოტოჭიქა",     size_label=None,       price="25.00", sort=83),
    dict(category=ProductCategory.other, name="ფოტომაისური",  size_label=None,       price="35.00", sort=84),
]


def seed_products(session: Session) -> None:
    """Insert any products from the defaults list that don't exist yet.

    Lookup key is (category, size_label) — matching the DB unique constraint.
    Existing rows (and any prices Archil has already edited) are never touched.
    """
    require_write_access()
    for row in _PRODUCTS:
        exists = session.exec(
            select(Product).where(
                and_(
                    Product.category == row["category"],
                    Product.size_label == row.get("size_label"),
                    Product.name == row["name"],
                )
            )
        ).first()
        if exists is None:
            session.add(Product(
                category=row["category"],
                name=row["name"],
                size_label=row.get("size_label"),
                unit_price=Decimal(row["price"]),
                sort_order=row["sort"],
            ))
    session.commit()
