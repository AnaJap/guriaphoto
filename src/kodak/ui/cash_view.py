"""Cash withdrawal tab — log register take-outs and track daily balance."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

import flet as ft

from kodak.access import is_read_only
from kodak.db import get_session
from kodak.models.enums import Role
from kodak.models.user import User
from kodak.services.cash import (
    day_revenue,
    delete_withdrawal,
    list_day_withdrawals,
    log_withdrawal,
    update_withdrawal,
)
from kodak.ui.geo import fmt_date
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


class CashView:
    def __init__(self, user: User) -> None:
        self._user     = user
        self._read_only = is_read_only()
        self._is_admin = user.role == Role.admin and not self._read_only
        self._date     = dt.date.today()
        self._mounted  = False
        self._editing_id: int | None = None   # id of withdrawal being edited

        # ── persistent controls ──────────────────────────────────────
        self._date_label  = ft.Text(
            "", size=14, weight=ft.FontWeight.W_600,
            expand=True, text_align=ft.TextAlign.CENTER,
        )
        self._nav_right = ft.Container(
            border_radius=RADIUS_SM,
            padding=ft.padding.all(SPACE_XS),
            on_click=self._next_day,
        )
        self._balance_row = ft.Row(spacing=SPACE_MD, wrap=True)
        self._form_area   = ft.Container()
        self._list_col    = ft.Column(
            spacing=SPACE_SM, scroll=ft.ScrollMode.AUTO, expand=True,
        )

        # "add" form fields (reused across reloads when shown)
        self._add_amount = ft.TextField(
            label="თანხა  ₾", keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=RADIUS_MD, text_size=15, width=180,
        )
        self._add_note   = ft.TextField(
            label="შენიშვნა  (სურვილისამებრ)",
            border_radius=RADIUS_MD, text_size=14, expand=True,
        )
        self._add_feedback = ft.Text("", size=12)

        self._reload()

    # ── public ──────────────────────────────────────────────────────

    def build(self) -> ft.Control:
        self._update_nav_right()

        nav = ft.Row(
            controls=[
                ft.Container(
                    content=ft.Icon(ft.Icons.CHEVRON_LEFT, size=22),
                    on_click=self._prev_day,
                    ink=True, border_radius=RADIUS_SM,
                    padding=ft.padding.all(SPACE_XS),
                ),
                self._date_label,
                self._nav_right,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        )

        self._root = ft.Column(
            controls=[nav, self._balance_row, self._form_area,
                      ft.Divider(height=1), self._list_col],
            spacing=SPACE_MD,
            expand=True,
        )
        self._mounted = True
        return self._root

    # ── navigation ──────────────────────────────────────────────────

    def _prev_day(self, e) -> None:
        self._editing_id = None
        self._date -= dt.timedelta(days=1)
        self._reload()
        self._flush_ui()

    def _next_day(self, e) -> None:
        if self._date >= dt.date.today():
            return
        self._editing_id = None
        self._date += dt.timedelta(days=1)
        self._reload()
        self._flush_ui()

    # ── data ────────────────────────────────────────────────────────

    def _reload(self) -> None:
        with get_session() as session:
            self._pairs  = list_day_withdrawals(session, self._date)
            revenue      = day_revenue(session, self._date)

        withdrawn = sum(w.amount for w, _ in self._pairs) or Decimal("0")
        balance   = revenue - withdrawn

        self._date_label.value = fmt_date(self._date)
        self._update_nav_right()

        # balance cards
        self._balance_row.controls = [
            _card("შემოსავალი", f"\u20be{revenue:.2f}",   ft.Icons.PAYMENTS,         ACCENT_GOLD),
            _card("გატანა",     f"\u20be{withdrawn:.2f}", ft.Icons.OUTPUT,            ft.Colors.ERROR),
            _card("სალაროში",   f"\u20be{balance:.2f}",   ft.Icons.ACCOUNT_BALANCE,  ft.Colors.PRIMARY),
        ]

        # "add" form: today for everyone, any day for admin
        show_form = not self._read_only and ((self._date == dt.date.today()) or self._is_admin)
        if show_form:
            self._add_amount.value   = ""
            self._add_note.value     = ""
            self._add_feedback.value = ""
            self._form_area.content  = self._build_add_form()
        else:
            self._form_area.content  = None

        # withdrawal list
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        if not self._pairs:
            self._list_col.controls = [
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
                                    size=40, color=ft.Colors.OUTLINE),
                            ft.Text("ამ დღეს გატანა არ ყოფილა",
                                    size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=SPACE_SM, tight=True,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER,
                    border_radius=RADIUS_LG,
                    padding=ft.padding.all(SPACE_LG * 2),
                    alignment=ft.Alignment(0, 0),
                )
            ]
        else:
            self._list_col.controls = [
                self._make_card(w, u) for w, u in self._pairs
            ]

    # ── card factory ────────────────────────────────────────────────

    def _make_card(self, w, u: User) -> ft.Control:
        if self._is_admin and self._editing_id == w.id:
            return self._build_edit_card(w, u)
        return self._build_read_card(w, u)

    def _build_read_card(self, w, u: User) -> ft.Container:
        time_str = w.created_at.strftime("%H:%M")

        row_controls: list[ft.Control] = [
            ft.Text(time_str, size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT, width=40),
            ft.Container(
                content=ft.Text(
                    u.full_name[:1].upper(), size=12,
                    weight=ft.FontWeight.W_700,
                    color=ft.Colors.ON_PRIMARY,
                ),
                bgcolor=ft.Colors.PRIMARY,
                width=28, height=28, border_radius=14,
                alignment=ft.Alignment(0, 0),
            ),
            ft.Text(u.full_name, size=14, weight=ft.FontWeight.W_600, expand=True),
        ]
        if w.note:
            row_controls.append(
                ft.Text(w.note, size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                        expand=True, italic=True)
            )
        row_controls.append(
            ft.Text(f"\u20be{w.amount:.2f}", size=15,
                    weight=ft.FontWeight.W_700, color=ft.Colors.ERROR)
        )
        if self._is_admin:
            row_controls.append(
                ft.Container(
                    content=ft.Icon(ft.Icons.EDIT_OUTLINED, size=15,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                    border_radius=RADIUS_SM,
                    padding=ft.padding.all(4),
                    ink=True,
                    tooltip="რედაქტირება",
                    on_click=lambda e, wid=w.id: self._start_edit(wid),
                )
            )

        return ft.Container(
            content=ft.Row(
                controls=row_controls,
                spacing=SPACE_SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_LG,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM + 2),
        )

    def _build_edit_card(self, w, u: User) -> ft.Container:
        amount_field = ft.TextField(
            label="თანხა  ₾",
            value=str(w.amount),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=RADIUS_MD,
            text_size=14,
            width=160,
        )
        note_field = ft.TextField(
            label="შენიშვნა",
            value=w.note or "",
            border_radius=RADIUS_MD,
            text_size=14,
            expand=True,
        )
        feedback = ft.Text("", size=12)

        def on_save(e) -> None:
            feedback.color = ft.Colors.ERROR
            raw = (amount_field.value or "").strip().replace(",", ".")
            try:
                amount = Decimal(raw)
                if amount <= 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                feedback.value = "სწორი თანხა შეიყვანეთ."
                if self._mounted:
                    feedback.update()
                return
            with get_session() as session:
                update_withdrawal(
                    session, w.id,
                    amount=amount,
                    note=note_field.value.strip() or None,
                )
            self._editing_id = None
            self._reload()
            self._flush_ui()

        def on_delete(e) -> None:
            with get_session() as session:
                delete_withdrawal(session, w.id)
            self._editing_id = None
            self._reload()
            self._flush_ui()

        def on_cancel(e) -> None:
            self._editing_id = None
            self._rebuild_list()
            if self._mounted:
                self._list_col.update()

        time_str = w.created_at.strftime("%H:%M")

        return ft.Container(
            content=ft.Column(
                controls=[
                    # Who + time (read-only header)
                    ft.Row(
                        controls=[
                            ft.Text(time_str, size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT, width=40),
                            ft.Container(
                                content=ft.Text(
                                    u.full_name[:1].upper(), size=12,
                                    weight=ft.FontWeight.W_700,
                                    color=ft.Colors.ON_PRIMARY,
                                ),
                                bgcolor=ft.Colors.PRIMARY,
                                width=28, height=28, border_radius=14,
                                alignment=ft.Alignment(0, 0),
                            ),
                            ft.Text(u.full_name, size=13,
                                    weight=ft.FontWeight.W_600,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=SPACE_SM,
                    ),
                    # Editable fields
                    ft.Row(
                        controls=[amount_field, note_field],
                        spacing=SPACE_SM,
                    ),
                    # Action buttons
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text(
                                    "შენახვა", size=13,
                                    weight=ft.FontWeight.W_600,
                                    color=ft.Colors.WHITE,
                                ),
                                bgcolor=ACCENT_GOLD,
                                border_radius=RADIUS_MD,
                                padding=ft.padding.symmetric(
                                    horizontal=SPACE_LG, vertical=SPACE_SM),
                                on_click=on_save, ink=True,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    "წაშლა", size=13,
                                    weight=ft.FontWeight.W_600,
                                    color=ft.Colors.WHITE,
                                ),
                                bgcolor=ft.Colors.ERROR,
                                border_radius=RADIUS_MD,
                                padding=ft.padding.symmetric(
                                    horizontal=SPACE_LG, vertical=SPACE_SM),
                                on_click=on_delete, ink=True,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    "გაუქმება", size=13,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                                border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                                border_radius=RADIUS_MD,
                                padding=ft.padding.symmetric(
                                    horizontal=SPACE_MD, vertical=SPACE_SM),
                                on_click=on_cancel, ink=True,
                            ),
                            feedback,
                        ],
                        spacing=SPACE_SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=SPACE_SM,
                tight=True,
            ),
            bgcolor=ft.Colors.PRIMARY_CONTAINER,
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_MD),
        )

    def _start_edit(self, withdrawal_id: int) -> None:
        self._editing_id = withdrawal_id
        self._rebuild_list()
        if self._mounted:
            self._list_col.update()

    # ── "add" form ──────────────────────────────────────────────────

    def _build_add_form(self) -> ft.Control:
        def on_submit(e) -> None:
            self._add_feedback.color = ft.Colors.ERROR
            raw = (self._add_amount.value or "").strip().replace(",", ".")
            try:
                amount = Decimal(raw)
                if amount <= 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                self._add_feedback.value = "შეიყვანეთ სწორი თანხა."
                if self._mounted:
                    self._add_feedback.update()
                return

            with get_session() as session:
                log_withdrawal(
                    session,
                    user_id=self._user.id,
                    date=self._date,
                    amount=amount,
                    note=self._add_note.value.strip() or None,
                )

            self._add_feedback.color = ft.Colors.PRIMARY
            self._add_feedback.value = f"\u20be{amount:.2f} — დაფიქსირდა ✓"
            self._reload()
            self._flush_ui()

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        "ახალი გატანა", size=13,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.Row(
                        controls=[self._add_amount, self._add_note],
                        spacing=SPACE_SM,
                    ),
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text(
                                    "გატანა", size=14,
                                    weight=ft.FontWeight.W_600,
                                    color=ft.Colors.WHITE,
                                ),
                                bgcolor=ft.Colors.ERROR,
                                border_radius=RADIUS_MD,
                                padding=ft.padding.symmetric(
                                    horizontal=SPACE_LG, vertical=SPACE_MD),
                                on_click=on_submit, ink=True,
                            ),
                            self._add_feedback,
                        ],
                        spacing=SPACE_MD,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=SPACE_SM,
                tight=True,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_MD),
        )

    # ── UI helpers ──────────────────────────────────────────────────

    def _update_nav_right(self) -> None:
        future = self._date >= dt.date.today()
        self._nav_right.content = ft.Icon(
            ft.Icons.CHEVRON_RIGHT, size=22,
            color=ft.Colors.ON_SURFACE_VARIANT if future else None,
        )
        self._nav_right.ink     = not future
        self._nav_right.opacity = 0.35 if future else 1.0

    def _flush_ui(self) -> None:
        if not self._mounted:
            return
        self._nav_right.update()
        self._date_label.update()
        self._balance_row.update()
        self._form_area.update()
        self._list_col.update()


# ── helpers ─────────────────────────────────────────────────────────────────

def _card(label: str, value: str, icon: str, icon_color) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Icon(icon, size=20, color=icon_color),
                ft.Text(value, size=24, weight=ft.FontWeight.W_700),
                ft.Text(label, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=SPACE_XS,
            tight=True,
        ),
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border_radius=RADIUS_LG,
        padding=ft.padding.all(SPACE_LG),
        width=170,
    )
