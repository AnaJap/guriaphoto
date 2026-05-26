"""ნისია screen — master-detail credits list with inline payment and forgive panels."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import flet as ft

from kodak.access import is_read_only
from kodak.db import get_session
from kodak.models.credit import Credit, CreditPayment
from kodak.models.enums import CreditStatus, Role
from kodak.models.user import User
from kodak.services.credits import (
    delete_credit_payment,
    forgive_credit,
    list_credits_by_filter,
    list_payments_for_credit,
    record_payment,
    reopen_forgiven_credit,
    sync_initial_credit_statuses,
    update_credit_payment,
)
from kodak.ui.geo import fmt_date, fmt_short_date, picker_date
from kodak.ui.theme import (
    ACCENT_GOLD,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
)

_STATUS_COLOR = {
    CreditStatus.active:   "#E53935",   # red — nothing paid yet
    CreditStatus.partial:  "#FFB300",   # gold — partially paid
    CreditStatus.cleared:  "#4CAF50",   # green — done
    CreditStatus.forgiven: "#9575CD",   # purple — pardoned
}
_STATUS_LABEL = {
    CreditStatus.active:   "აქტიური",
    CreditStatus.partial:  "ნაწილობრივი",
    CreditStatus.cleared:  "დახურული",
    CreditStatus.forgiven: "ნაპატიები",
}

# filter_mode → (chip label, summary label)
_FILTER_META = {
    "all":      ("ყველა",       "ყველა ნისია"),
    "active":   ("აქტიური",     "აქტიური ნისია"),
    "partial":  ("ნაწილობრივი", "ნაწილობრივ გადახდილი"),
    "cleared":  ("დახურული",    "დახურული ნისია"),
    "forgiven": ("ნაპატიები",   "ნაპატიები ნისია"),
}


class CreditsView:
    def __init__(self, page: ft.Page, user: User) -> None:
        self._page = page
        self._user = user
        self._can_write = not is_read_only()
        self._is_admin = user.role == Role.admin and self._can_write
        self._selected: Credit | None = None
        self._filter_mode: str = "active"
        self._search_query: str = ""
        self._start_date: dt.date | None = None
        self._end_date: dt.date | None = None
        # When non-None, the detail panel shows inline forgive-confirmation
        self._confirm_forgive: bool = False
        self._editing_payment_id: int | None = None
        self._confirm_delete_payment_id: int | None = None

        self._credits: list[Credit] = []

        # ── Left panel controls ───────────────────────────────────────
        self._summary_text = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self._search_field = ft.TextField(
            hint_text="ძებნა გვარით ან კოდით…",
            border_radius=RADIUS_MD,
            text_size=13,
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._on_search_change,
            height=42,
        )
        self._from_label = ft.Text("", size=12, weight=ft.FontWeight.W_600)
        self._to_label = ft.Text("", size=12, weight=ft.FontWeight.W_600)
        self._list_col = ft.Column(
            spacing=SPACE_SM,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._filter_row = ft.Row(spacing=SPACE_XS, wrap=True)

        today = dt.date.today()
        self._dp_start = ft.DatePicker(
            value=today,
            first_date=dt.date(2020, 1, 1),
            last_date=today,
            help_text="დაწყების თარიღი",
            confirm_text="კარგი",
            cancel_text="გაუქმება",
            on_change=self._on_start_picked,
        )
        self._dp_end = ft.DatePicker(
            value=today,
            first_date=dt.date(2020, 1, 1),
            last_date=today,
            help_text="დასრულების თარიღი",
            confirm_text="კარგი",
            cancel_text="გაუქმება",
            on_change=self._on_end_picked,
        )
        self._page.overlay.extend([self._dp_start, self._dp_end])
        self._page.update()

        # ── Right panel ───────────────────────────────────────────────
        self._detail_area = ft.Container(expand=True)

        self._load_credits()
        self._rebuild_filter_row()
        self._sync_date_labels()
        self._rebuild_list()
        self._detail_area.content = self._empty_detail()

    # ──────────────────────────────────────────────── public

    def build(self) -> ft.Control:
        self._refresh_without_updates()
        left = ft.Container(
            content=ft.Column(
                controls=[
                    self._summary_text,
                    self._filter_row,
                    self._search_field,
                    self._build_date_filters(),
                    ft.Container(height=SPACE_XS),
                    self._list_col,
                ],
                spacing=SPACE_SM,
                expand=True,
            ),
            width=540,
            padding=ft.padding.only(right=SPACE_LG),
        )

        return ft.Column(
            controls=[
                ft.Text("ნისია", size=28, weight=ft.FontWeight.W_700),
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

    # ─────────────────────────────────────────── data loading

    def _load_credits(self) -> None:
        with get_session() as session:
            if self._can_write:
                sync_initial_credit_statuses(session)
            self._credits = list_credits_by_filter(
                session,
                self._filter_mode,
                start_date=self._start_date,
                end_date=self._end_date,
                search=self._search_query,
            )

    def _refresh_without_updates(self) -> None:
        selected_id = self._selected.id if self._selected is not None else None
        self._load_credits()
        if selected_id is not None:
            self._selected = next(
                (credit for credit in self._credits if credit.id == selected_id),
                None,
            )
        self._rebuild_filter_row()
        self._sync_date_labels()
        self._rebuild_list()
        self._detail_area.content = (
            self._build_detail(self._selected)
            if self._selected is not None
            else self._empty_detail()
        )

    # ──────────────────────────────────────────── search + dates

    def _build_date_filters(self) -> ft.Control:
        from_btn = _filter_btn(
            ft.Icons.CALENDAR_TODAY_OUTLINED,
            self._from_label,
            lambda e: self._open_picker("start"),
        )
        to_btn = _filter_btn(
            ft.Icons.EVENT_OUTLINED,
            self._to_label,
            lambda e: self._open_picker("end"),
        )
        clear_btn = ft.Container(
            content=ft.Icon(
                ft.Icons.CLOSE,
                size=15,
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            tooltip="თარიღის ფილტრის გასუფთავება",
            width=34,
            height=34,
            alignment=ft.Alignment(0, 0),
            border_radius=RADIUS_SM,
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            on_click=self._clear_dates,
            ink=True,
        )
        return ft.Row(
            controls=[
                from_btn,
                ft.Text("–", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                to_btn,
                clear_btn,
            ],
            spacing=SPACE_XS,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _open_picker(self, which: str) -> None:
        today = dt.date.today()
        self._dp_start.last_date = today
        self._dp_end.last_date = today
        if which == "start":
            self._dp_start.value = self._start_date or today
            self._dp_start.open = True
            self._dp_start.update()
        else:
            self._dp_end.value = self._end_date or today
            self._dp_end.open = True
            self._dp_end.update()

    def _on_start_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        picked = picker_date(raw)
        picked = min(picked, dt.date.today())
        self._start_date = picked
        if self._end_date is not None and self._start_date > self._end_date:
            self._end_date = self._start_date
        self._apply_filter_change()

    def _on_end_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        picked = picker_date(raw)
        picked = min(picked, dt.date.today())
        self._end_date = picked
        if self._start_date is not None and self._end_date < self._start_date:
            self._start_date = self._end_date
        self._apply_filter_change()

    def _clear_dates(self, e=None) -> None:
        if self._start_date is None and self._end_date is None:
            return
        self._start_date = None
        self._end_date = None
        self._apply_filter_change()

    def _sync_date_labels(self) -> None:
        self._from_label.value = (
            fmt_short_date(self._start_date) if self._start_date else "საწყისი"
        )
        self._to_label.value = (
            fmt_short_date(self._end_date) if self._end_date else "დასასრული"
        )

    def _on_search_change(self, e) -> None:
        self._search_query = (e.control.value or "").strip()
        self._apply_filter_change()

    def _apply_filter_change(self) -> None:
        self._clear_selection()
        self._load_credits()
        self._rebuild_filter_row()
        self._sync_date_labels()
        self._rebuild_list()
        self._summary_text.update()
        self._filter_row.update()
        self._from_label.update()
        self._to_label.update()
        self._list_col.update()
        self._detail_area.content = self._empty_detail()
        self._detail_area.update()

    def _clear_selection(self) -> None:
        self._selected = None
        self._confirm_forgive = False
        self._editing_payment_id = None
        self._confirm_delete_payment_id = None

    # ──────────────────────────────────────────── filter row

    def _rebuild_filter_row(self) -> None:
        # Summary text
        count = len(self._credits)
        label = _FILTER_META[self._filter_mode][1]
        total_original = sum(c.original_amount for c in self._credits)
        total_remaining = sum(c.remaining_amount for c in self._credits)
        if self._filter_mode in ("active", "partial", "all"):
            self._summary_text.value = (
                f"{count} {label}  ·  დარჩენილი ₾{total_remaining:.2f}"
                if count else f"{label} არ არის"
            )
        elif self._filter_mode == "cleared":
            self._summary_text.value = (
                f"{count} {label}  ·  სულ ₾{total_original:.2f}"
                if count else f"{label} არ არის"
            )
        else:
            self._summary_text.value = (
                f"{count} {label}  ·  თანხა ₾{total_original:.2f}"
                if count else f"{label} არ არის"
            )

        # Filter chips
        chips: list[ft.Control] = []
        for mode, (chip_label, _) in _FILTER_META.items():
            active = self._filter_mode == mode

            def on_click(e, m=mode):
                if self._filter_mode == m:
                    return
                self._filter_mode = m
                self._apply_filter_change()

            chips.append(ft.Container(
                content=ft.Text(
                    chip_label, size=12, weight=ft.FontWeight.W_600,
                    color=ft.Colors.ON_PRIMARY if active else ft.Colors.ON_SURFACE_VARIANT,
                ),
                bgcolor=ft.Colors.PRIMARY if active else ft.Colors.SURFACE_CONTAINER,
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=6),
                on_click=on_click,
                ink=not active,
            ))

        self._filter_row.controls = chips

    # ──────────────────────────────────────────── credit list

    def _rebuild_list(self) -> None:
        if not self._credits:
            self._list_col.controls = [
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=40,
                                    color=ft.Colors.OUTLINE),
                            ft.Text("ნისია არ არის", size=14,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=SPACE_SM,
                        tight=True,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER,
                    border_radius=RADIUS_LG,
                    padding=ft.padding.all(SPACE_LG * 2),
                    alignment=ft.Alignment(0, 0),
                )
            ]
        else:
            self._list_col.controls = [
                self._credit_card(c) for c in self._credits
            ]

    def _credit_card(self, credit: Credit) -> ft.Container:
        selected = self._selected is not None and self._selected.id == credit.id
        status_color = _STATUS_COLOR.get(credit.status, ft.Colors.OUTLINE)
        paid = credit.original_amount - credit.remaining_amount
        progress = float(paid / credit.original_amount) if credit.original_amount else 0.0
        is_closed = credit.status in (CreditStatus.cleared, CreditStatus.forgiven)
        display_amount = credit.original_amount if is_closed else credit.remaining_amount
        amount_meta = (
            f"სულ ₾{credit.original_amount:.2f}"
            if is_closed
            else f"დარჩ. ₾{credit.remaining_amount:.2f} · სულ ₾{credit.original_amount:.2f}"
        )

        def on_click(e, c=credit):
            self._selected = c
            self._confirm_forgive = False
            self._editing_payment_id = None
            self._confirm_delete_payment_id = None
            self._rebuild_list()
            self._list_col.update()
            self._show_detail(c)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                credit.code, size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    _STATUS_LABEL.get(credit.status, ""),
                                    size=10, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.WHITE,
                                ),
                                bgcolor=status_color,
                                border_radius=RADIUS_SM,
                                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                            ),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(
                                credit.customer_surname, size=15,
                                weight=ft.FontWeight.W_600, expand=True,
                            ),
                            ft.Text(
                                f"₾{display_amount:.2f}", size=16,
                                weight=ft.FontWeight.W_700, color=status_color,
                            ),
                        ],
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(
                                fmt_date(credit.date), size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                            ),
                            ft.Text(
                                amount_meta,
                                size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                    ),
                    ft.ProgressBar(
                        value=progress,
                        color=status_color,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                        height=4,
                        border_radius=ft.border_radius.all(2),
                    ),
                ],
                spacing=SPACE_XS,
                tight=True,
            ),
            bgcolor=ft.Colors.PRIMARY_CONTAINER if selected else ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_MD),
            on_click=on_click,
            ink=True,
        )

    # ──────────────────────────────────────────── detail panel

    def _empty_detail(self) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
                            size=48, color=ft.Colors.OUTLINE),
                    ft.Text("აირჩიეთ ნისია სიიდან",
                            size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=SPACE_SM,
                tight=True,
            ),
            alignment=ft.Alignment(0, -0.3),
            expand=True,
        )

    def _show_detail(self, credit: Credit) -> None:
        self._detail_area.content = self._build_detail(credit)
        self._detail_area.update()

    def _build_detail(self, credit: Credit) -> ft.Control:
        with get_session() as session:
            payments = list_payments_for_credit(session, credit.id)

        paid = sum((p.amount for p in payments), Decimal("0")).quantize(Decimal("0.01"))
        progress = float(paid / credit.original_amount) if credit.original_amount else 0.0
        status_color = _STATUS_COLOR.get(credit.status, ft.Colors.OUTLINE)
        is_open = credit.status in (CreditStatus.active, CreditStatus.partial)
        is_forgiven = credit.status == CreditStatus.forgiven

        # ── Payment history rows ──────────────────────────────────────
        history_rows = self._build_payment_history_rows(credit, payments)

        # ── Bottom action section ─────────────────────────────────────
        bottom_section: list[ft.Control] = []

        if is_open and self._can_write:
            # Payment form
            amount_field = ft.TextField(
                label="თანხა  ₾",
                value=str(credit.remaining_amount),
                border_radius=RADIUS_MD,
                keyboard_type=ft.KeyboardType.NUMBER,
                text_size=14,
                expand=True,
            )
            note_field = ft.TextField(
                label="შენიშვნა  (სურვილისამებრ)",
                border_radius=RADIUS_MD,
                text_size=13,
                expand=True,
            )
            pay_feedback = ft.Text("", size=12)

            def on_pay(e):
                pay_feedback.color = ft.Colors.ERROR
                raw = (amount_field.value or "").strip().replace(",", ".")
                try:
                    amount = Decimal(raw)
                except Exception:
                    pay_feedback.value = "შეიყვანეთ სწორი თანხა."
                    pay_feedback.update()
                    return
                try:
                    with get_session() as session:
                        record_payment(
                            session,
                            credit_id=credit.id,
                            amount=amount,
                            date_paid=dt.date.today(),
                            notes=note_field.value.strip() or None,
                            created_by_user_id=self._user.id,
                        )
                        updated = session.get(type(credit), credit.id)
                        self._selected = updated
                except ValueError as exc:
                    pay_feedback.value = str(exc)
                    pay_feedback.update()
                    return

                self._load_credits()
                self._rebuild_filter_row()
                self._rebuild_list()
                self._filter_row.update()
                self._summary_text.update()
                self._list_col.update()

                if self._selected and self._selected.status in (
                    CreditStatus.active, CreditStatus.partial
                ):
                    self._show_detail(self._selected)
                else:
                    self._selected = None
                    self._detail_area.content = _closed_confirmation("სრულად დაიფარა!")
                    self._detail_area.update()

            pay_btn = _action_btn("გადახდა", ACCENT_GOLD, on_pay)

            bottom_section = [
                ft.Divider(height=1),
                ft.Text("გადახდა", size=13, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Row(controls=[amount_field]),
                ft.Row(controls=[note_field]),
                ft.Row(controls=[pay_btn]),
                pay_feedback,
            ]

            # Admin-only: forgive button or confirmation row
            if self._is_admin:
                if self._confirm_forgive:
                    # Inline confirmation
                    def on_forgive_confirm(e):
                        try:
                            with get_session() as session:
                                forgive_credit(
                                    session,
                                    credit_id=credit.id,
                                    forgiven_by_user_id=self._user.id,
                                )
                        except ValueError as exc:
                            return
                        self._confirm_forgive = False
                        self._selected = None
                        self._load_credits()
                        self._rebuild_filter_row()
                        self._rebuild_list()
                        self._filter_row.update()
                        self._summary_text.update()
                        self._list_col.update()
                        self._detail_area.content = _closed_confirmation("ნისია ნაპატიებია.")
                        self._detail_area.update()

                    def on_forgive_cancel(e):
                        self._confirm_forgive = False
                        self._show_detail(credit)

                    bottom_section += [
                        ft.Container(height=SPACE_XS),
                        ft.Container(
                            content=ft.Column(
                                controls=[
                                    ft.Row(
                                        controls=[
                                            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED,
                                                    size=16, color="#E53935"),
                                            ft.Text(
                                                "დარწმუნებული ხართ? ₾"
                                                f"{credit.remaining_amount:.2f} "
                                                "პატიება გაიცემა — ეს "
                                                "გაუქმებელია.",
                                                size=12,
                                                color=ft.Colors.ON_SURFACE_VARIANT,
                                                expand=True,
                                            ),
                                        ],
                                        spacing=SPACE_XS,
                                        vertical_alignment=ft.CrossAxisAlignment.START,
                                    ),
                                    ft.Row(
                                        controls=[
                                            _action_btn(
                                                "დიახ, პატიება",
                                                "#E53935",
                                                on_forgive_confirm,
                                                expand=True,
                                            ),
                                            _action_btn(
                                                "გაუქმება",
                                                ft.Colors.SURFACE_CONTAINER_HIGH,
                                                on_forgive_cancel,
                                                text_color=ft.Colors.ON_SURFACE,
                                                expand=True,
                                            ),
                                        ],
                                        spacing=SPACE_SM,
                                    ),
                                ],
                                spacing=SPACE_SM,
                                tight=True,
                            ),
                            bgcolor=ft.Colors.ERROR_CONTAINER,
                            border_radius=RADIUS_MD,
                            padding=ft.padding.all(SPACE_MD),
                        ),
                    ]
                else:
                    def on_forgive_click(e):
                        self._confirm_forgive = True
                        self._show_detail(credit)

                    bottom_section += [
                        ft.Container(height=SPACE_XS),
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.DO_NOT_DISTURB_ALT,
                                            size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                                    ft.Text("ნისიის პატიება", size=12,
                                            color=ft.Colors.ON_SURFACE_VARIANT),
                                ],
                                spacing=SPACE_XS,
                                tight=True,
                            ),
                            on_click=on_forgive_click,
                            ink=True,
                            border_radius=RADIUS_SM,
                            bgcolor=ft.Colors.SURFACE_CONTAINER,
                            padding=ft.padding.symmetric(
                                horizontal=SPACE_MD, vertical=SPACE_SM
                            ),
                        ),
                    ]

        elif is_open:
            bottom_section = [
                ft.Container(height=SPACE_SM),
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.VISIBILITY_OUTLINED, size=18, color=ft.Colors.OUTLINE),
                        ft.Text(
                            "მხოლოდ ნახვის რეჟიმში გადახდა და პატიება გამორთულია.",
                            size=13,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                    spacing=SPACE_XS,
                ),
            ]

        elif is_forgiven:
            # Show who forgave and when
            forgiven_at_str = (
                credit.forgiven_at.strftime("%d/%m/%Y %H:%M")
                if credit.forgiven_at else "—"
            )
            bottom_section = [
                ft.Container(height=SPACE_SM),
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.DO_NOT_DISTURB_ALT,
                                    size=16, color="#9575CD"),
                            ft.Text(
                                f"ნაპატიებია  {forgiven_at_str}",
                                size=13, color="#9575CD",
                            ),
                        ],
                        spacing=SPACE_XS,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER,
                    border_radius=RADIUS_MD,
                    padding=ft.padding.all(SPACE_MD),
                ),
            ]
            if self._is_admin:
                reopen_feedback = ft.Text("", size=12, color=ft.Colors.ERROR)

                def on_reopen(e):
                    try:
                        with get_session() as session:
                            updated = reopen_forgiven_credit(session, credit.id)
                    except ValueError as exc:
                        reopen_feedback.value = str(exc)
                        reopen_feedback.update()
                        return
                    self._refresh_after_credit_change(updated)

                bottom_section += [
                    ft.Row(
                        controls=[
                            _action_btn(
                                "პატიების გაუქმება",
                                ACCENT_GOLD,
                                on_reopen,
                                expand=True,
                            ),
                        ],
                    ),
                    reopen_feedback,
                ]
        else:
            # Cleared
            bottom_section = [
                ft.Container(height=SPACE_SM),
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.CHECK_CIRCLE, size=18, color="#4CAF50"),
                        ft.Text("ნისია დახურულია", size=13, color="#4CAF50"),
                    ],
                    spacing=SPACE_XS,
                ),
            ]

        return ft.Column(
            controls=[
                # Header
                ft.Text(credit.customer_surname, size=22, weight=ft.FontWeight.W_700),
                ft.Text(
                    f"{credit.code}  ·  {fmt_date(credit.date)}",
                    size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Container(height=SPACE_SM),
                # Amounts
                ft.Row(
                    controls=[
                        _amount_chip("სულ", f"₾{credit.original_amount:.2f}",
                                     ft.Colors.ON_SURFACE_VARIANT),
                        _amount_chip("გადახდილი", f"₾{paid:.2f}",
                                     ft.Colors.PRIMARY),
                        _amount_chip("დარჩენილი", f"₾{credit.remaining_amount:.2f}",
                                     status_color),
                    ],
                    spacing=SPACE_SM,
                    wrap=True,
                ),
                ft.Container(height=SPACE_XS),
                ft.ProgressBar(
                    value=progress,
                    color=status_color,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                    height=6,
                    border_radius=ft.border_radius.all(3),
                ),
                ft.Container(height=SPACE_MD),
                # Payment history
                ft.Text("გადახდების ისტორია", size=13, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Container(
                    content=ft.Column(controls=history_rows, spacing=SPACE_XS, tight=True),
                    bgcolor=ft.Colors.SURFACE_CONTAINER,
                    border_radius=RADIUS_MD,
                    padding=ft.padding.all(SPACE_MD),
                ),
                *bottom_section,
            ],
            spacing=SPACE_SM,
            scroll=ft.ScrollMode.AUTO,
        )

    def _build_payment_history_rows(
        self,
        credit: Credit,
        payments: list[CreditPayment],
    ) -> list[ft.Control]:
        if not payments:
            return [
                ft.Text(
                    "გადახდები ჯერ არ ყოფილა",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                )
            ]

        return [
            self._payment_edit_row(credit, p)
            if self._editing_payment_id == p.id
            else self._payment_row(credit, p)
            for p in payments
        ]

    def _payment_row(self, credit: Credit, payment: CreditPayment) -> ft.Control:
        can_correct = self._is_admin and credit.status in (
            CreditStatus.cleared,
            CreditStatus.forgiven,
        )

        controls: list[ft.Control] = [
            ft.Text(
                fmt_date(payment.date),
                size=12,
                color=ft.Colors.ON_SURFACE_VARIANT,
                width=110,
            ),
            ft.Text(
                payment.notes or "",
                size=12,
                color=ft.Colors.ON_SURFACE_VARIANT,
                expand=True,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            ft.Text(
                f"₾{payment.amount:.2f}",
                size=13,
                weight=ft.FontWeight.W_600,
                color=ft.Colors.PRIMARY,
                width=86,
                text_align=ft.TextAlign.RIGHT,
            ),
        ]

        if can_correct:
            def on_edit(e, payment_id=payment.id):
                self._editing_payment_id = payment_id
                self._confirm_delete_payment_id = None
                self._show_detail(credit)

            controls.append(
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.EDIT_OUTLINED,
                        size=14,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    on_click=on_edit,
                    ink=True,
                    border_radius=RADIUS_SM,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                    padding=ft.padding.all(5),
                    width=28,
                    height=28,
                    alignment=ft.Alignment(0, 0),
                )
            )

        return ft.Row(
            controls=controls,
            spacing=SPACE_XS,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _payment_edit_row(self, credit: Credit, payment: CreditPayment) -> ft.Control:
        amount_field = ft.TextField(
            label="თანხა ₾",
            value=str(payment.amount),
            border_radius=RADIUS_MD,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_size=13,
            expand=True,
        )
        date_field = ft.TextField(
            label="თარიღი",
            value=payment.date.isoformat(),
            hint_text="YYYY-MM-DD",
            border_radius=RADIUS_MD,
            text_size=13,
            width=150,
        )
        note_field = ft.TextField(
            label="შენიშვნა",
            value=payment.notes or "",
            border_radius=RADIUS_MD,
            text_size=13,
            expand=True,
        )
        feedback = ft.Text("", size=12, color=ft.Colors.ERROR)
        confirm_delete = self._confirm_delete_payment_id == payment.id

        def on_cancel(e=None):
            self._editing_payment_id = None
            self._confirm_delete_payment_id = None
            self._show_detail(credit)

        def on_save(e):
            raw_amount = (amount_field.value or "").strip().replace(",", ".")
            try:
                amount = Decimal(raw_amount)
            except Exception:
                feedback.value = "შეიყვანეთ სწორი თანხა."
                feedback.update()
                return

            raw_date = (date_field.value or "").strip()
            try:
                paid_date = dt.date.fromisoformat(raw_date)
            except ValueError:
                feedback.value = "თარიღი უნდა იყოს YYYY-MM-DD ფორმატში."
                feedback.update()
                return

            try:
                with get_session() as session:
                    updated = update_credit_payment(
                        session,
                        payment.id,
                        amount=amount,
                        date_paid=paid_date,
                        notes=(note_field.value or "").strip() or None,
                    )
            except ValueError as exc:
                feedback.value = str(exc)
                feedback.update()
                return

            self._editing_payment_id = None
            self._confirm_delete_payment_id = None
            self._refresh_after_credit_change(updated)

        def on_delete_click(e):
            self._confirm_delete_payment_id = payment.id
            self._show_detail(credit)

        def on_delete_confirm(e):
            try:
                with get_session() as session:
                    updated = delete_credit_payment(session, payment.id)
            except ValueError as exc:
                feedback.value = str(exc)
                feedback.update()
                return

            self._editing_payment_id = None
            self._confirm_delete_payment_id = None
            self._refresh_after_credit_change(updated)

        delete_controls = [
            _compact_btn("წაშლა", ft.Colors.ERROR, on_delete_click, expand=True),
        ]
        if confirm_delete:
            delete_controls = [
                ft.Text("წავშალო?", size=12, color=ft.Colors.ERROR, expand=True),
                _compact_btn("დიახ", ft.Colors.ERROR, on_delete_confirm),
                _compact_btn(
                    "არა",
                    ft.Colors.SURFACE_CONTAINER_HIGH,
                    lambda e: on_cancel(),
                    text_color=ft.Colors.ON_SURFACE,
                ),
            ]

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[amount_field, date_field],
                        spacing=SPACE_XS,
                    ),
                    ft.Row(controls=[note_field]),
                    ft.Row(
                        controls=[
                            _compact_btn("შენახვა", ACCENT_GOLD, on_save, expand=True),
                            _compact_btn(
                                "გაუქმება",
                                ft.Colors.SURFACE_CONTAINER_HIGH,
                                on_cancel,
                                text_color=ft.Colors.ON_SURFACE,
                                expand=True,
                            ),
                        ],
                        spacing=SPACE_XS,
                    ),
                    ft.Row(controls=delete_controls, spacing=SPACE_XS),
                    feedback,
                ],
                spacing=SPACE_XS,
                tight=True,
            ),
            bgcolor=ft.Colors.SURFACE,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=RADIUS_MD,
            padding=ft.padding.all(SPACE_SM),
        )

    def _refresh_after_credit_change(self, updated: Credit) -> None:
        self._selected = updated
        self._confirm_forgive = False
        if not self._status_allowed_by_current_filter(updated.status):
            if updated.status in (CreditStatus.active, CreditStatus.partial):
                self._filter_mode = "active"
            elif updated.status == CreditStatus.cleared:
                self._filter_mode = "cleared"
            elif updated.status == CreditStatus.forgiven:
                self._filter_mode = "forgiven"

        self._load_credits()
        self._rebuild_filter_row()
        self._rebuild_list()
        self._filter_row.update()
        self._summary_text.update()
        self._list_col.update()
        self._show_detail(updated)

    def _status_allowed_by_current_filter(self, status: CreditStatus) -> bool:
        if self._filter_mode == "all":
            return True
        if self._filter_mode == "active":
            return status in (CreditStatus.active, CreditStatus.partial)
        if self._filter_mode == "partial":
            return status == CreditStatus.partial
        if self._filter_mode == "cleared":
            return status == CreditStatus.cleared
        if self._filter_mode == "forgiven":
            return status == CreditStatus.forgiven
        return False


# ─────────────────────────────────────────────── helpers

def _filter_btn(icon: str, label: ft.Text, on_click) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(icon, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                label,
            ],
            spacing=SPACE_XS,
            tight=True,
        ),
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border_radius=RADIUS_SM,
        padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=7),
        on_click=on_click,
        ink=True,
    )


def _action_btn(
    label: str,
    bgcolor,
    on_click,
    *,
    text_color=ft.Colors.WHITE,
    expand: bool = False,
) -> ft.Container:
    return ft.Container(
        content=ft.Text(
            label, size=13, weight=ft.FontWeight.W_600,
            color=text_color, text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=bgcolor,
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_LG, vertical=SPACE_MD),
        alignment=ft.Alignment(0, 0),
        on_click=on_click,
        ink=True,
        expand=expand,
    )


def _compact_btn(
    label: str,
    bgcolor,
    on_click,
    *,
    text_color=ft.Colors.WHITE,
    expand: bool = False,
) -> ft.Container:
    return ft.Container(
        content=ft.Text(
            label,
            size=12,
            weight=ft.FontWeight.W_600,
            color=text_color,
            text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=bgcolor,
        border_radius=RADIUS_SM,
        padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=6),
        alignment=ft.Alignment(0, 0),
        on_click=on_click,
        ink=True,
        expand=expand,
    )


def _amount_chip(label: str, value: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(label, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(value, size=15, weight=ft.FontWeight.W_700, color=color),
            ],
            spacing=2,
            tight=True,
        ),
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
    )


def _closed_confirmation(message: str) -> ft.Control:
    is_forgiven = "ნაპატიებია" in message
    color = "#9575CD" if is_forgiven else "#4CAF50"
    icon = ft.Icons.DO_NOT_DISTURB_ALT if is_forgiven else ft.Icons.CHECK_CIRCLE
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Icon(icon, size=52, color=color),
                ft.Text(message, size=16, weight=ft.FontWeight.W_600, color=color),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=SPACE_SM,
            tight=True,
        ),
        alignment=ft.Alignment(0, -0.3),
        expand=True,
    )
