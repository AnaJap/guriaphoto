"""Products tab — catalog viewer for employees, price editor for admin."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import flet as ft

from kodak.access import is_read_only
from kodak.db import get_session
from kodak.models.enums import ProductCategory, Role
from kodak.models.product import Product
from kodak.models.user import User
from kodak.services.pricing import list_active_products
from kodak.services.products import (
    delete_product,
    get_price_history,
    list_all_products_admin,
    product_usage_count,
    record_price_change,
    save_product,
)
from kodak.ui.geo import fmt_short_date
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


class ProductsView:
    def __init__(self, user: User) -> None:
        self._user = user
        self._can_write = not is_read_only()
        self._is_admin = user.role == Role.admin and self._can_write
        self._products: list[Product] = []
        self._selected_id: int | None = None   # None = nothing, -1 = adding new
        self._filter_cat: ProductCategory | None = None

        self._cat_row = ft.Row(spacing=SPACE_XS, scroll=ft.ScrollMode.AUTO)
        self._list_col = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        self._detail_area = ft.Container(expand=True)

        self._load()
        self._rebuild_cat_row()
        self._rebuild_list()
        self._detail_area.content = self._empty_detail()

    # ─────────────────────────────────────────────── public

    def build(self) -> ft.Control:
        add_btn: list[ft.Control] = []
        if self._is_admin:
            add_btn = [
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.ADD, size=15, color=ft.Colors.WHITE),
                            ft.Text("ახალი", size=13, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.WHITE),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    bgcolor=ft.Colors.PRIMARY,
                    border_radius=RADIUS_MD,
                    padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
                    on_click=self._on_add,
                    ink=True,
                )
            ]

        left = ft.Container(
            content=ft.Column(
                controls=[
                    self._cat_row,
                    ft.Container(height=SPACE_XS),
                    self._list_col,
                ],
                spacing=SPACE_SM,
                expand=True,
            ),
            width=360,
            padding=ft.padding.only(right=SPACE_LG),
        )

        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("პროდუქტები", size=28, weight=ft.FontWeight.W_700),
                        *add_btn,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=SPACE_MD),
                ft.Row(
                    controls=[
                        left,
                        ft.VerticalDivider(width=1, thickness=1),
                        ft.Container(
                            content=self._detail_area,
                            expand=True,
                            padding=ft.padding.only(left=SPACE_LG),
                        ),
                    ],
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ],
            expand=True,
            spacing=0,
        )

    # ──────────────────────────────────────────── data

    def _load(self) -> None:
        with get_session() as session:
            if self._is_admin:
                self._products = list_all_products_admin(session)
            else:
                self._products = list_active_products(session)

    # ──────────────────────────────────────────── category tabs

    def _rebuild_cat_row(self) -> None:
        seen: list[ProductCategory] = []
        for p in self._products:
            if p.category not in seen:
                seen.append(p.category)
        tabs = [self._cat_chip(None, "ყველა")]
        for cat in seen:
            tabs.append(self._cat_chip(cat, _CAT_LABEL.get(cat, cat.value.title())))
        self._cat_row.controls = tabs

    def _cat_chip(self, cat: ProductCategory | None, label: str) -> ft.Container:
        active = self._filter_cat == cat

        def on_click(e, c=cat):
            self._filter_cat = c
            self._rebuild_cat_row()
            self._rebuild_list()
            self._cat_row.update()
            self._list_col.update()

        return ft.Container(
            content=ft.Text(
                label, size=12, weight=ft.FontWeight.W_600,
                color=ft.Colors.ON_PRIMARY if active else ft.Colors.ON_SURFACE_VARIANT,
            ),
            bgcolor=ft.Colors.PRIMARY if active else ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_SM,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=6),
            on_click=on_click,
            ink=True,
        )

    # ──────────────────────────────────────────── product list

    def _rebuild_list(self) -> None:
        visible = [
            p for p in self._products
            if self._filter_cat is None or p.category == self._filter_cat
        ]

        if not visible:
            self._list_col.controls = [
                ft.Container(
                    content=ft.Text("პროდუქტები არ არის", size=14,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                    padding=ft.padding.all(SPACE_LG * 2),
                    alignment=ft.Alignment(0, 0),
                )
            ]
            return

        # Group by category preserving order
        grouped: dict[ProductCategory, list[Product]] = {}
        for p in visible:
            grouped.setdefault(p.category, []).append(p)

        rows: list[ft.Control] = []
        for cat, items in grouped.items():
            rows.append(
                ft.Container(
                    content=ft.Text(
                        _CAT_LABEL.get(cat, cat.value.title()).upper(),
                        size=11, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    padding=ft.padding.only(top=SPACE_MD, bottom=SPACE_XS, left=SPACE_XS),
                )
            )
            for p in items:
                rows.append(self._product_row(p))

        self._list_col.controls = rows

    def _product_row(self, p: Product) -> ft.Container:
        selected = self._selected_id == p.id
        inactive = not p.active

        def on_click(e, prod=p):
            if not self._is_admin:
                return
            self._selected_id = prod.id
            self._rebuild_list()
            self._list_col.update()
            self._show_edit(prod)

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=8, height=8, border_radius=4,
                        bgcolor="#4CAF50" if p.active else ft.Colors.OUTLINE_VARIANT,
                    ),
                    ft.Text(
                        f"{p.name}  {p.size_label or ''}".strip(),
                        size=13, expand=True,
                        color=ft.Colors.ON_SURFACE_VARIANT if inactive else None,
                    ),
                    ft.Text(
                        f"₾{p.unit_price:.2f}",
                        size=13, weight=ft.FontWeight.W_600,
                        color=ft.Colors.OUTLINE if inactive else ft.Colors.PRIMARY,
                    ),
                ],
                spacing=SPACE_SM,
            ),
            bgcolor=(
                ft.Colors.PRIMARY_CONTAINER if selected
                else ft.Colors.SURFACE_CONTAINER_LOW if inactive
                else ft.Colors.SURFACE_CONTAINER
            ),
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM + 2),
            on_click=on_click if self._is_admin else None,
            ink=self._is_admin,
        )

    # ──────────────────────────────────────────── detail panel

    def _empty_detail(self) -> ft.Control:
        msg = (
            "აირჩიეთ პროდუქტი სიიდან\nან დაამატეთ ახალი"
            if self._is_admin
            else "პროდუქტების სია"
        )
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.PHOTO_CAMERA_OUTLINED, size=48,
                            color=ft.Colors.OUTLINE),
                    ft.Text(msg, size=14, color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=SPACE_SM,
                tight=True,
            ),
            alignment=ft.Alignment(0, -0.3),
            expand=True,
        )

    def _show_edit(self, product: Product) -> None:
        self._detail_area.content = self._build_form(product)
        self._detail_area.update()

    def _on_add(self, e) -> None:
        self._selected_id = -1
        self._rebuild_list()
        self._list_col.update()
        self._detail_area.content = self._build_form(None)
        self._detail_area.update()

    def _build_form(self, product: Product | None) -> ft.Control:
        is_new = product is None

        # Load usage count and price history for existing products
        usage_count = 0
        history_rows: list[ft.Control] = []
        if not is_new:
            with get_session() as session:
                usage_count = product_usage_count(session, product.id)
                history = get_price_history(session, product.id)
            if history:
                for h, user in history:
                    who = user.full_name if user else "—"
                    history_rows.append(ft.Row(
                        controls=[
                            ft.Text(fmt_short_date(h.changed_at.date()), size=11,
                                    color=ft.Colors.ON_SURFACE_VARIANT, width=90),
                            ft.Text(f"\u20be{h.old_price:.2f}", size=11,
                                    color=ft.Colors.ON_SURFACE_VARIANT, width=56,
                                    text_align=ft.TextAlign.RIGHT),
                            ft.Icon(ft.Icons.ARROW_FORWARD, size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(f"\u20be{h.new_price:.2f}", size=11,
                                    weight=ft.FontWeight.W_600, width=56),
                            ft.Text(who, size=11,
                                    color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                        ],
                        spacing=SPACE_XS,
                    ))
            else:
                history_rows = [
                    ft.Text("ფასის ცვლილება არ ყოფილა", size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT)
                ]

        name_field = ft.TextField(
            label="სახელი",
            value=product.name if product else "",
            border_radius=RADIUS_MD,
            text_size=14,
            expand=True,
        )
        size_field = ft.TextField(
            label="ზომა  (სურვილისამებრ)",
            value=product.size_label or "" if product else "",
            border_radius=RADIUS_MD,
            text_size=14,
            expand=True,
        )
        price_field = ft.TextField(
            label="ფასი  ₾",
            value=str(product.unit_price) if product else "",
            border_radius=RADIUS_MD,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_size=14,
            expand=True,
        )

        # Category chip selector
        edit_cat: list[ProductCategory] = [
            product.category if product
            else (self._filter_cat or ProductCategory.photo)
        ]
        cat_chip_row = ft.Row(spacing=SPACE_XS, wrap=True)

        def rebuild_cat_chips() -> None:
            chips = []
            for cat in ProductCategory:
                sel = edit_cat[0] == cat

                def on_cat(e, c=cat):
                    edit_cat[0] = c
                    rebuild_cat_chips()
                    cat_chip_row.update()

                chips.append(ft.Container(
                    content=ft.Text(
                        _CAT_LABEL.get(cat, cat.value.title()),
                        size=11, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_PRIMARY if sel else ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    bgcolor=ft.Colors.PRIMARY if sel else ft.Colors.SURFACE_CONTAINER,
                    border_radius=RADIUS_SM,
                    padding=ft.padding.symmetric(horizontal=SPACE_SM + 2, vertical=4),
                    on_click=on_cat,
                    ink=True,
                ))
            cat_chip_row.controls = chips

        rebuild_cat_chips()

        # Active toggle
        active_state: list[bool] = [product.active if product else True]
        active_row = ft.Row(spacing=SPACE_SM)

        def rebuild_active_toggle() -> None:
            is_on = active_state[0]

            def toggle(e):
                active_state[0] = not active_state[0]
                rebuild_active_toggle()
                active_row.update()

            active_row.controls = [
                ft.Text("სტატუსი:", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Container(
                    content=ft.Text(
                        "● აქტიური" if is_on else "○ გამორთული",
                        size=13, weight=ft.FontWeight.W_600,
                        color="#4CAF50" if is_on else ft.Colors.OUTLINE,
                    ),
                    on_click=toggle,
                    ink=True,
                    border_radius=RADIUS_SM,
                    padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=4),
                    bgcolor=ft.Colors.SURFACE_CONTAINER,
                ),
            ]

        rebuild_active_toggle()

        feedback = ft.Text("", size=12)

        def on_save(e) -> None:
            feedback.color = ft.Colors.ERROR
            name = name_field.value.strip()
            if not name:
                feedback.value = "სახელი სავალდებულოა."
                feedback.update()
                return
            try:
                price = Decimal(price_field.value.strip().replace(",", "."))
                if price < 0:
                    raise ValueError()
            except Exception:
                feedback.value = "შეიყვანეთ სწორი ფასი."
                feedback.update()
                return

            with get_session() as session:
                if is_new:
                    p = Product(
                        category=edit_cat[0],
                        name=name,
                        size_label=size_field.value.strip() or None,
                        unit_price=price,
                        active=active_state[0],
                    )
                else:
                    p = session.get(Product, product.id)
                    # Record history BEFORE mutating — old price still readable
                    if p.unit_price != price:
                        record_price_change(
                            session,
                            product_id=p.id,
                            old_price=p.unit_price,
                            new_price=price,
                            changed_by_user_id=self._user.id,
                        )
                    p.category = edit_cat[0]
                    p.name = name
                    p.size_label = size_field.value.strip() or None
                    p.unit_price = price
                    p.active = active_state[0]
                saved = save_product(session, p, changed_by_user_id=self._user.id)
                self._selected_id = saved.id

            # Refresh the detail panel to show updated price history
            self._load()
            self._rebuild_cat_row()
            self._rebuild_list()
            self._cat_row.update()
            self._list_col.update()
            feedback.color = ft.Colors.PRIMARY
            feedback.value = "შენახულია ✓"
            feedback.update()
            # Reload form to show updated history
            with get_session() as session:
                refreshed = session.get(Product, self._selected_id)
            if refreshed:
                self._detail_area.content = self._build_form(refreshed)
                self._detail_area.update()

        def on_cancel(e) -> None:
            self._selected_id = None
            self._rebuild_list()
            self._list_col.update()
            self._detail_area.content = self._empty_detail()
            self._detail_area.update()

        # ── delete button + inline confirmation ──────────────────────
        confirm_row = ft.Row(visible=False, spacing=SPACE_SM,
                             vertical_alignment=ft.CrossAxisAlignment.CENTER)
        delete_row  = ft.Row(spacing=SPACE_SM)

        def show_confirm(e) -> None:
            delete_row.visible  = False
            confirm_row.visible = True
            delete_row.update()
            confirm_row.update()

        def hide_confirm(e) -> None:
            confirm_row.visible = False
            delete_row.visible  = True
            confirm_row.update()
            delete_row.update()

        def on_confirm_delete(e) -> None:
            with get_session() as session:
                result = delete_product(session, product.id)
            self._selected_id = None
            self._load()
            self._rebuild_cat_row()
            self._rebuild_list()
            self._cat_row.update()
            self._list_col.update()
            msg = "გამორთულია ✓" if result == "deactivated" else "წაშლილია ✓"
            self._detail_area.content = self._empty_detail()
            self._detail_area.update()

        if not is_new:
            if usage_count > 0:
                del_label   = f"გამორთვა  ({usage_count} გაყიდვაში)"
                del_bgcolor = ft.Colors.OUTLINE_VARIANT
                del_fgcolor = ft.Colors.ON_SURFACE_VARIANT
            else:
                del_label   = "წაშლა"
                del_bgcolor = ft.Colors.ERROR_CONTAINER
                del_fgcolor = ft.Colors.ERROR

            delete_row.controls = [
                ft.Container(
                    content=ft.Text(del_label, size=12, color=del_fgcolor),
                    bgcolor=del_bgcolor,
                    border_radius=RADIUS_MD,
                    padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
                    on_click=show_confirm,
                    ink=True,
                )
            ]
            confirm_row.controls = [
                ft.Text("დარწმუნებული ხართ?", size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Container(
                    content=ft.Text("კი", size=12, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.WHITE),
                    bgcolor=ft.Colors.ERROR,
                    border_radius=RADIUS_MD,
                    padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
                    on_click=on_confirm_delete,
                    ink=True,
                ),
                ft.Container(
                    content=ft.Text("არა", size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                    border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=RADIUS_MD,
                    padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
                    on_click=hide_confirm,
                    ink=True,
                ),
            ]

        title = "ახალი პროდუქტი" if is_new else f"{product.name}  {product.size_label or ''}".strip()

        # ── price history section ────────────────────────────────────
        history_section: list[ft.Control] = []
        if not is_new:
            history_section = [
                ft.Divider(height=SPACE_MD),
                ft.Text("ფასის ისტორია", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                *history_rows,
            ]

        return ft.Column(
            controls=[
                ft.Text(title, size=20, weight=ft.FontWeight.W_700),
                ft.Container(height=SPACE_XS),
                ft.Text("კატეგორია", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                cat_chip_row,
                ft.Row(controls=[name_field]),
                ft.Row(controls=[size_field]),
                ft.Row(controls=[price_field]),
                active_row,
                ft.Container(height=SPACE_XS),
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Text(
                                "შენახვა", size=14, weight=ft.FontWeight.W_600,
                                color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER,
                            ),
                            bgcolor=ACCENT_GOLD,
                            border_radius=RADIUS_MD,
                            padding=ft.padding.symmetric(
                                horizontal=SPACE_LG, vertical=SPACE_MD),
                            alignment=ft.Alignment(0, 0),
                            on_click=on_save,
                            ink=True,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.Text(
                                "გაუქმება", size=14,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                            border_radius=RADIUS_MD,
                            padding=ft.padding.symmetric(
                                horizontal=SPACE_LG, vertical=SPACE_MD),
                            alignment=ft.Alignment(0, 0),
                            on_click=on_cancel,
                            ink=True,
                            expand=True,
                        ),
                    ],
                    spacing=SPACE_SM,
                ),
                feedback,
                delete_row,
                confirm_row,
                *history_section,
            ],
            spacing=SPACE_SM,
            scroll=ft.ScrollMode.AUTO,
        )
