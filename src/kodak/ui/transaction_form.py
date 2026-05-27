"""Transaction entry form — split-panel POS layout.

Left panel  : product picker with category filter chips + tappable product cards.
Right panel : live order summary — qty steppers, running total, credit preview, confirm.

Prices are always loaded fresh from the DB at build() time so a price change
made in the Products tab is immediately reflected here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable

import flet as ft

from kodak import clock
from kodak.access import is_read_only
from kodak.db import get_session
from kodak.models.enums import ProductCategory
from kodak.models.product import Product
from kodak.models.user import User
from kodak.services.pricing import list_active_products
from kodak.services.transactions import LineItemInput, create_transaction
from kodak.ui.theme import (
    ACCENT_GOLD,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
)

_CAT_LABEL: dict[ProductCategory, str] = {
    ProductCategory.photo:       "ფოტო",
    ProductCategory.enlargement: "გადიდება",
    ProductCategory.frame:       "ჩარჩო",
    ProductCategory.lamination:  "ლამინირება",
    ProductCategory.cd:          "CD",
    ProductCategory.photocopy:   "ქსეროქსი",
    ProductCategory.album:       "ალბომი",
    ProductCategory.other:       "სხვა",
}


class TransactionForm:
    """Renders and manages the daily transaction entry UI."""

    def __init__(self, user: User, on_saved: Callable[[], None]) -> None:
        self._user     = user
        self._on_saved = on_saved

        # Product data — intentionally empty until _load_products() is called
        # in build() so prices are always fetched fresh from the DB.
        self._products:   list[Product]              = []
        self._by_id:      dict[int, Product]         = {}
        self._categories: list[ProductCategory]      = []

        self._active_cat: ProductCategory | None = None  # None = All
        self._cart:       dict[int, int]         = {}    # product_id → qty

        # ── UI controls (created once, updated in-place) ─────────────
        self._surname_field = ft.TextField(
            label="გვარი",
            border_radius=RADIUS_MD,
            text_size=14,
            expand=True,
            on_change=self._clear_feedback,
        )
        self._received_field = ft.TextField(
            label="გადახდილი თანხა  ₾  *",
            border_radius=RADIUS_MD,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_size=14,
            expand=True,
            on_change=self._on_received_change,
        )
        self._notes_field = ft.TextField(
            label="შენიშვნა",
            hint_text="სურვილისამებრ",
            border_radius=RADIUS_MD,
            text_size=13,
            expand=True,
        )
        self._cart_col    = ft.Column(spacing=SPACE_XS, scroll=ft.ScrollMode.AUTO)
        self._total_val   = ft.Text("₾0.00", size=22, weight=ft.FontWeight.W_700)
        self._credit_label = ft.Text("", size=12, color=ACCENT_GOLD)
        self._credit_row  = ft.Row(
            controls=[
                ft.Icon(ft.Icons.INFO_OUTLINE, size=14, color=ACCENT_GOLD),
                self._credit_label,
            ],
            spacing=SPACE_XS,
            visible=False,
        )
        self._feedback    = ft.Text("", size=12)
        self._cat_row     = ft.Row(spacing=SPACE_XS, scroll=ft.ScrollMode.AUTO)
        self._product_wrap = ft.Row(wrap=True, spacing=SPACE_SM, run_spacing=SPACE_SM)

    # ────────────────────────────────────────────────── data

    def _load_products(self) -> None:
        """Fetch current prices from DB — the single source of truth."""
        with get_session() as session:
            self._products = list_active_products(session)
        self._by_id = {p.id: p for p in self._products}
        seen: list[ProductCategory] = []
        for p in self._products:
            if p.category not in seen:
                seen.append(p.category)
        self._categories = seen

    # ────────────────────────────────────────────────── public

    def build(self) -> ft.Control:
        if is_read_only():
            return ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(ft.Icons.VISIBILITY_OUTLINED, size=44, color=ft.Colors.OUTLINE),
                        ft.Text(
                            "მხოლოდ ნახვის რეჟიმი",
                            size=16,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Text(
                            "ახალი შეკვეთის დამატება ხელმისაწვდომია მხოლოდ რედაქტირების სესიაში.",
                            size=13,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=SPACE_SM,
                    tight=True,
                ),
                alignment=ft.Alignment(0, -0.2),
                expand=True,
            )

        # Load fresh prices every time the form is built — ensures a price
        # change in the Products tab is immediately visible here.
        self._load_products()
        self._rebuild_cat_row()
        self._rebuild_product_wrap()

        left = ft.Column(
            controls=[
                ft.Text(
                    "შეეხეთ პროდუქტს დასამატებლად",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                self._cat_row,
                ft.Container(height=SPACE_XS),
                # Scrollable grid: takes the remaining height and scrolls
                # internally so cards never get clipped at the bottom.
                ft.Column(
                    controls=[self._product_wrap],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
            ],
            spacing=SPACE_SM,
            expand=True,
        )

        right = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        "შეკვეთა",
                        size=11,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    self._surname_field,
                    ft.Divider(height=1),
                    ft.Container(content=self._cart_col, height=200),
                    ft.Divider(height=1),
                    ft.Row(
                        controls=[
                            ft.Text("სულ", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                            self._total_val,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    self._received_field,
                    self._credit_row,
                    self._notes_field,
                    ft.Container(height=SPACE_XS),
                    _confirm_btn(self._on_confirm),
                    self._feedback,
                ],
                spacing=SPACE_SM,
            ),
            width=300,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_LG),
        )

        return ft.Row(
            controls=[
                ft.Container(
                    content=left,
                    expand=True,
                    padding=ft.padding.only(right=SPACE_LG),
                ),
                right,
            ],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    # ─────────────────────────────────────────── builders

    def _rebuild_cat_row(self) -> None:
        tabs = [self._cat_chip(None, "ყველა")]
        for cat in self._categories:
            tabs.append(self._cat_chip(cat, _CAT_LABEL.get(cat, cat.value.title())))
        self._cat_row.controls = tabs

    def _cat_chip(self, cat: ProductCategory | None, label: str) -> ft.Container:
        active = self._active_cat == cat

        def on_click(e, c=cat):
            self._active_cat = c
            self._rebuild_cat_row()
            self._rebuild_product_wrap()
            self._cat_row.update()
            self._product_wrap.update()

        return ft.Container(
            content=ft.Text(
                label,
                size=12,
                weight=ft.FontWeight.W_600,
                color=ft.Colors.ON_PRIMARY if active else ft.Colors.ON_SURFACE_VARIANT,
            ),
            bgcolor=ft.Colors.PRIMARY if active else ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_SM,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=6),
            on_click=on_click,
            ink=True,
        )

    def _rebuild_product_wrap(self) -> None:
        visible = [
            p for p in self._products
            if self._active_cat is None or p.category == self._active_cat
        ]
        self._product_wrap.controls = [self._product_card(p) for p in visible]

    def _product_card(self, p: Product) -> ft.Container:
        qty = self._cart.get(p.id, 0)
        in_cart = qty > 0

        def on_click(e, pid=p.id):
            self._cart[pid] = self._cart.get(pid, 0) + 1
            self._full_refresh()

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        p.name,
                        size=12,
                        weight=ft.FontWeight.W_600,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(
                        p.size_label or "",
                        size=10,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.Text(
                        f"₾{p.unit_price:.2f}",
                        size=13,
                        weight=ft.FontWeight.W_700,
                        color=ACCENT_GOLD if in_cart else ft.Colors.PRIMARY,
                    ),
                    ft.Text(
                        f"× {qty}" if in_cart else " ",
                        size=11,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                ],
                spacing=2,
                tight=True,
            ),
            width=110,
            bgcolor=ft.Colors.PRIMARY_CONTAINER if in_cart else ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_MD,
            padding=ft.padding.all(SPACE_SM + 2),
            on_click=on_click,
            ink=True,
        )

    # ───────────────────────────────────────────── cart

    def _rebuild_cart(self) -> None:
        rows: list[ft.Control] = []
        for pid, qty in list(self._cart.items()):
            if qty <= 0:
                continue
            p = self._by_id[pid]
            line_total = (p.unit_price * qty).quantize(Decimal("0.01"))

            def dec(e, pid=pid):
                if self._cart.get(pid, 0) <= 1:
                    self._cart.pop(pid, None)
                else:
                    self._cart[pid] -= 1
                self._full_refresh()

            def inc(e, pid=pid):
                self._cart[pid] = self._cart.get(pid, 0) + 1
                self._full_refresh()

            rows.append(
                ft.Row(
                    controls=[
                        ft.Text(
                            f"{p.name} {p.size_label or ''}".strip(),
                            size=12,
                            expand=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        _stepper_btn("−", dec),
                        ft.Text(
                            str(qty),
                            size=13,
                            weight=ft.FontWeight.W_600,
                            width=22,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        _stepper_btn("+", inc),
                        ft.Text(
                            f"₾{line_total:.2f}",
                            size=12,
                            weight=ft.FontWeight.W_600,
                            width=54,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ],
                    spacing=SPACE_XS,
                )
            )
        self._cart_col.controls = rows

    # ──────────────────────────────────────── refresh

    def _full_refresh(self) -> None:
        """Rebuild product grid + cart + totals and push all updates."""
        self._rebuild_product_wrap()
        self._rebuild_cart()
        total = self._total()
        self._total_val.value = f"₾{total:.2f}"
        self._update_credit_row(total)
        self._product_wrap.update()
        self._cart_col.update()
        self._total_val.update()
        self._credit_row.update()

    def _update_credit_row(self, total: Decimal) -> None:
        received = self._parse_received()
        if received is not None and Decimal("0") <= received < total:
            shortfall = (total - received).quantize(Decimal("0.01"))
            self._credit_label.value = f"ნისია დაფიქსირდება: ₾{shortfall:.2f}"
            self._credit_row.visible = True
        else:
            self._credit_row.visible = False

    # ──────────────────────────────────────── helpers

    def _total(self) -> Decimal:
        return sum(
            (self._by_id[pid].unit_price * qty).quantize(Decimal("0.01"))
            for pid, qty in self._cart.items()
            if qty > 0
        ) or Decimal("0.00")

    def _parse_received(self) -> Decimal | None:
        raw = (self._received_field.value or "").strip().replace(",", ".")
        if not raw:
            return None
        try:
            return Decimal(raw)
        except Exception:
            return None

    # ─────────────────────────────────────── events

    def _clear_feedback(self, e) -> None:
        if self._feedback.value:
            self._feedback.value = ""
            self._feedback.update()

    def _on_received_change(self, e) -> None:
        self._update_credit_row(self._total())
        self._credit_row.update()

    def _on_confirm(self, e) -> None:
        self._feedback.color = ft.Colors.ERROR

        surname = (self._surname_field.value or "").strip()
        if not surname:
            self._feedback.value = "გვარი სავალდებულოა."
            self._feedback.update()
            return

        items = [
            LineItemInput(product_id=pid, quantity=qty)
            for pid, qty in self._cart.items()
            if qty > 0
        ]
        if not items:
            self._feedback.value = "დაამატეთ მინიმუმ ერთი პროდუქტი."
            self._feedback.update()
            return

        received = self._parse_received()
        if received is None:
            self._feedback.value = "გადახდილი თანხა სავალდებულოა (0 თუ სრულად ნისია)."
            self._feedback.update()
            return
        if received < 0:
            self._feedback.value = "თანხა არ შეიძლება იყოს უარყოფითი."
            self._feedback.update()
            return

        notes_raw = (self._notes_field.value or "").strip()
        notes = notes_raw[:128] or None

        try:
            with get_session() as session:
                result = create_transaction(
                    session,
                    date=clock.today(),
                    customer_surname=surname,
                    items=items,
                    amount_received=received,
                    notes=notes,
                    created_by_user_id=self._user.id,
                )
        except Exception as exc:
            self._feedback.value = str(exc)
            self._feedback.update()
            return

        saved_total = sum(li.line_total for li in result.line_items)
        credit = result.credit

        self._cart.clear()
        self._surname_field.value = ""
        self._received_field.value = ""
        self._notes_field.value = ""
        self._surname_field.update()
        self._received_field.update()
        self._notes_field.update()
        self._full_refresh()

        if credit:
            msg = f"✓ შენახულია — ნისია {credit.code}: ₾{credit.remaining_amount:.2f}"
        else:
            msg = f"✓ შენახულია — ₾{saved_total:.2f} მიღებულია სრულად."

        self._feedback.color = ft.Colors.PRIMARY
        self._feedback.value = msg
        self._feedback.update()

        self._on_saved()


# ─────────────────────────────────────────────── helpers

def _stepper_btn(label: str, on_click) -> ft.Container:
    return ft.Container(
        content=ft.Text(label, size=15, weight=ft.FontWeight.W_600),
        on_click=on_click,
        ink=True,
        border_radius=RADIUS_SM,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=2),
        alignment=ft.Alignment(0, 0),
        width=28,
        height=28,
    )


def _confirm_btn(on_click) -> ft.Container:
    return ft.Container(
        content=ft.Text(
            "დადასტურება",
            size=14,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.WHITE,
            text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=ACCENT_GOLD,
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_LG, vertical=SPACE_MD),
        alignment=ft.Alignment(0, 0),
        on_click=on_click,
        ink=True,
        expand=True,
    )
