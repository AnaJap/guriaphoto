"""ნისია screen — master-detail credits list with inline payment and forgive panels."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import flet as ft

from kodak import clock
from kodak.access import is_read_only
from kodak.db import get_session
from kodak.models.credit import Credit, CreditPayment
from kodak.models.enums import CreditStatus, Role
from kodak.models.user import User
from kodak.services.credits import (
    CreditPaymentDisplayRow,
    CreditSaleAmounts,
    delete_credit_payment,
    forgive_credit,
    list_credit_sale_amounts,
    list_credit_payments_by_filter,
    list_credits_by_filter,
    list_payments_for_credit,
    list_payments_for_credits,
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
    get_active_theme_runtime,
)

_HEADER_CONTROL_HEIGHT = 34
_DETAIL_WIDTH = 420

_STATUS_COLOR = {
    CreditStatus.active:   "#E53935",   # red — nothing paid yet
    CreditStatus.partial:  "#FFB300",   # gold — partially paid
    CreditStatus.cleared:  "#4CAF50",   # green — done
    CreditStatus.forgiven: "#9575CD",   # purple — pardoned
}
_STATUS_LABEL = {
    CreditStatus.active:   "გადაუხდელი",
    CreditStatus.partial:  "ნაწილობრივ გადახდილი",
    CreditStatus.cleared:  "დახურული",
    CreditStatus.forgiven: "ნაპატიები",
}

# filter_mode → (chip label, summary label)
_FILTER_META = {
    "active":   ("აქტიური",   (CreditStatus.active, CreditStatus.partial)),
    "cleared":  ("დახურული",  (CreditStatus.cleared,)),
    "forgiven": ("ნაპატიები", (CreditStatus.forgiven,)),
}


class CreditsView:
    def __init__(self, page: ft.Page, user: User) -> None:
        self._page = page
        self._user = user
        self._can_write = not is_read_only()
        self._is_admin = user.role == Role.admin and self._can_write
        self._selected: Credit | None = None
        self._view_mode: str = "credits"
        self._status_filters: set[str] = {"active"}
        self._search_query: str = ""
        self._start_date: dt.date | None = None
        self._end_date: dt.date | None = None
        self._date_preset: str | None = None
        # When non-None, the detail panel shows inline forgive-confirmation
        self._confirm_forgive: bool = False
        self._editing_payment_id: int | None = None
        self._confirm_delete_payment_id: int | None = None
        self._expanded_credit_ids: set[int] = set()

        self._credits: list[Credit] = []
        self._payments: list[CreditPaymentDisplayRow] = []
        self._credit_payments_by_id: dict[int, list[CreditPayment]] = {}
        self._sale_amounts_by_credit_id: dict[int, CreditSaleAmounts] = {}

        # ── Left panel controls ───────────────────────────────────────
        self._view_row = ft.Row(spacing=SPACE_XS)
        self._summary_text = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self._list_count_text = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self._date_scope_text = ft.Text(
            "გახსნის თარიღი",
            size=12,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        self._search_field = ft.TextField(
            hint_text="ძებნა გვარით ან კოდით…",
            border_radius=RADIUS_MD,
            text_size=13,
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._on_search_change,
            height=_HEADER_CONTROL_HEIGHT + 4,
        )
        self._from_label = ft.Text("", size=12, weight=ft.FontWeight.W_600)
        self._to_label = ft.Text("", size=12, weight=ft.FontWeight.W_600)
        self._list_col = ft.Column(
            spacing=SPACE_XS,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._filter_row = ft.Row(spacing=SPACE_XS, wrap=True)

        today = clock.today()
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

        self._load_rows()
        self._rebuild_view_row()
        self._rebuild_filter_row()
        self._sync_date_labels()
        self._rebuild_list()
        self._detail_area.content = self._empty_detail()

    # ──────────────────────────────────────────────── public

    def build(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        self._refresh_without_updates()
        left = ft.Container(
            content=self._build_list_panel(runtime),
            expand=True,
        )

        return ft.Column(
            controls=[
                ft.Text("ნისია", size=28, weight=ft.FontWeight.W_700),
                ft.Container(height=SPACE_SM),
                self._build_filter_panel(runtime),
                ft.Container(height=SPACE_SM),
                ft.Row(
                    controls=[
                        left,
                        ft.Container(
                            content=self._detail_area,
                            width=_DETAIL_WIDTH,
                            bgcolor=runtime.panel_bg,
                            border=ft.border.all(1, runtime.panel_border),
                            border_radius=RADIUS_LG,
                            padding=ft.padding.all(SPACE_MD),
                        ),
                    ],
                    spacing=SPACE_MD,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
            ],
            expand=True,
            spacing=0,
        )

    def _build_filter_panel(self, runtime) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            self._view_row,
                            ft.Container(content=self._filter_row, expand=True),
                        ],
                        spacing=SPACE_SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        controls=[
                            ft.Container(content=self._search_field, width=520),
                            ft.Container(expand=True),
                            self._build_date_filters(runtime),
                        ],
                        spacing=SPACE_SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=SPACE_XS,
                tight=True,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, _with_alpha(runtime.accent, 0.10)),
            border_radius=RADIUS_LG,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
        )

    def _build_list_panel(self, runtime) -> ft.Control:
        title = "ნისიები" if self._view_mode == "credits" else "მოტანები"
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(title, size=14, weight=ft.FontWeight.W_700),
                            ft.Container(expand=True),
                            self._list_count_text,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(
                        content=self._list_col,
                        expand=True,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                ],
                spacing=SPACE_XS,
                expand=True,
            ),
            bgcolor=_with_alpha(runtime.accent, 0.03),
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_SM + 2),
            expand=True,
        )

    # ─────────────────────────────────────────── data loading

    def _load_rows(self) -> None:
        with get_session() as session:
            if self._can_write:
                sync_initial_credit_statuses(session)
            if self._view_mode == "payments":
                self._credits = []
                self._payments = list_credit_payments_by_filter(
                    session,
                    start_date=self._start_date,
                    end_date=self._end_date,
                    search=self._search_query,
                )
                payment_credits = [row.credit for row in self._payments]
                self._credit_payments_by_id = list_payments_for_credits(
                    session,
                    [credit.id for credit in payment_credits if credit.id is not None],
                )
                self._sale_amounts_by_credit_id = list_credit_sale_amounts(
                    session,
                    payment_credits,
                )
            else:
                self._payments = []
                self._credits = list_credits_by_filter(
                    session,
                    self._selected_credit_statuses(),
                    start_date=self._start_date,
                    end_date=self._end_date,
                    search=self._search_query,
                )
                self._credit_payments_by_id = list_payments_for_credits(
                    session,
                    [credit.id for credit in self._credits if credit.id is not None],
                )
                self._sale_amounts_by_credit_id = list_credit_sale_amounts(
                    session,
                    self._credits,
                )
                self._expanded_credit_ids.intersection_update(
                    credit.id for credit in self._credits if credit.id is not None
                )

    def _selected_credit_statuses(self) -> set[CreditStatus]:
        statuses: set[CreditStatus] = set()
        for key in self._status_filters:
            statuses.update(_FILTER_META[key][1])
        return statuses

    def _refresh_without_updates(self) -> None:
        selected_id = self._selected.id if self._selected is not None else None
        self._load_rows()
        if selected_id is not None:
            source = (
                self._credits
                if self._view_mode == "credits"
                else [row.credit for row in self._payments]
            )
            self._selected = next((credit for credit in source if credit.id == selected_id), None)
        self._rebuild_view_row()
        self._rebuild_filter_row()
        self._sync_date_labels()
        self._rebuild_list()
        self._detail_area.content = (
            self._build_detail(self._selected)
            if self._selected is not None
            else self._empty_detail()
        )

    # ──────────────────────────────────────────── search + dates

    def _build_date_filters(self, runtime) -> ft.Control:
        today_btn = _preset_btn(
            "დღეს",
            self._date_preset == "today",
            lambda e: self._set_date_preset("today"),
            runtime,
        )
        week_btn = _preset_btn(
            "კვირის",
            self._date_preset == "week",
            lambda e: self._set_date_preset("week"),
            runtime,
        )
        this_month_btn = _preset_btn(
            "ამ თვის",
            self._date_preset == "this_month",
            lambda e: self._set_date_preset("this_month"),
            runtime,
        )
        prev_month_btn = _preset_btn(
            "წინა თვის",
            self._date_preset == "prev_month",
            lambda e: self._set_date_preset("prev_month"),
            runtime,
        )
        from_btn = _filter_btn(
            ft.Icons.CALENDAR_TODAY_OUTLINED,
            self._from_label,
            lambda e: self._open_picker("start"),
            runtime,
        )
        to_btn = _filter_btn(
            ft.Icons.CALENDAR_TODAY_OUTLINED,
            self._to_label,
            lambda e: self._open_picker("end"),
            runtime,
        )
        clear_btn = ft.Container(
            content=ft.Icon(
                ft.Icons.CLOSE,
                size=14,
                color=runtime.muted_text,
            ),
            tooltip="თარიღის ფილტრის გასუფთავება",
            width=_HEADER_CONTROL_HEIGHT,
            height=_HEADER_CONTROL_HEIGHT,
            alignment=ft.Alignment(0, 0),
            border_radius=RADIUS_MD,
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            on_click=self._clear_dates,
            ink=True,
        )
        date_row = ft.Row(
            controls=[
                self._date_scope_text,
                today_btn,
                week_btn,
                this_month_btn,
                prev_month_btn,
                from_btn,
                ft.Text("–", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                to_btn,
                clear_btn,
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return date_row

    def _open_picker(self, which: str) -> None:
        today = clock.today()
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
        self._date_preset = None
        picked = picker_date(raw)
        picked = min(picked, clock.today())
        self._start_date = picked
        if self._end_date is not None and self._start_date > self._end_date:
            self._end_date = self._start_date
        self._apply_filter_change()

    def _on_end_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        self._date_preset = None
        picked = picker_date(raw)
        picked = min(picked, clock.today())
        self._end_date = picked
        if self._start_date is not None and self._end_date < self._start_date:
            self._start_date = self._end_date
        self._apply_filter_change()

    def _clear_dates(self, e=None) -> None:
        if self._start_date is None and self._end_date is None:
            return
        self._date_preset = None
        self._start_date = None
        self._end_date = None
        self._apply_filter_change()

    def _set_date_preset(self, preset: str) -> None:
        today = clock.today()
        self._date_preset = preset
        self._end_date = today
        if preset == "today":
            self._start_date = today
        elif preset == "week":
            self._start_date = today - dt.timedelta(days=today.weekday())
        elif preset == "this_month":
            self._start_date = today.replace(day=1)
        elif preset == "prev_month":
            first_this = today.replace(day=1)
            last_prev = first_this - dt.timedelta(days=1)
            self._start_date = last_prev.replace(day=1)
            self._end_date = last_prev
        else:
            self._start_date = today - dt.timedelta(days=6)
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
        self._load_rows()
        self._rebuild_view_row()
        self._rebuild_filter_row()
        self._sync_date_labels()
        self._rebuild_list()
        _safe_update(self._view_row)
        _safe_update(self._list_count_text)
        _safe_update(self._filter_row)
        _safe_update(self._search_field)
        _safe_update(self._date_scope_text)
        _safe_update(self._from_label)
        _safe_update(self._to_label)
        _safe_update(self._list_col)
        self._detail_area.content = self._empty_detail()
        _safe_update(self._detail_area)

    def _clear_selection(self) -> None:
        self._selected = None
        self._confirm_forgive = False
        self._editing_payment_id = None
        self._confirm_delete_payment_id = None

    # ──────────────────────────────────────────── filter row

    def _rebuild_view_row(self) -> None:
        runtime = get_active_theme_runtime()
        controls: list[ft.Control] = []
        for mode, label in (("credits", "ნისიები"), ("payments", "მოტანები")):
            active = self._view_mode == mode

            def on_click(e, m=mode):
                if self._view_mode == m:
                    return
                self._view_mode = m
                self._apply_filter_change()

            controls.append(
                ft.Container(
                    content=ft.Text(
                        label,
                        size=13,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_PRIMARY
                        if active
                        else ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    bgcolor=runtime.accent
                    if active
                    else _with_alpha(runtime.accent, 0.08),
                    border=ft.border.all(
                        1,
                        runtime.accent if active else _with_alpha(runtime.accent, 0.18),
                    ),
                    border_radius=RADIUS_MD,
                    padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
                    height=_HEADER_CONTROL_HEIGHT,
                    alignment=ft.Alignment(0, 0),
                    on_click=on_click,
                    ink=not active,
                )
            )

        self._view_row.controls = controls
        self._search_field.hint_text = (
            "ძებნა გვარით ან კოდით…"
            if self._view_mode == "credits"
            else "ძებნა გვარით, კოდით ან თანხით…"
        )
        self._date_scope_text.value = (
            "გახსნის თარიღი"
            if self._view_mode == "credits"
            else "მოტანის თარიღი"
        )
        count = len(self._credits) if self._view_mode == "credits" else len(self._payments)
        self._list_count_text.value = f"{count} ჩანაწერი"

    def _rebuild_filter_row(self) -> None:
        runtime = get_active_theme_runtime()
        self._filter_row.visible = self._view_mode == "credits"
        if self._view_mode == "payments":
            count = len(self._payments)
            total = sum((row.amount for row in self._payments), Decimal("0"))
            credit_count = len({row.credit.id for row in self._payments})
            self._summary_text.value = (
                f"{count} მოტანა  ·  სულ ₾{total:.2f}  ·  {credit_count} ნისია"
                if count
                else "მოტანები არ არის"
            )
            return

        count = len(self._credits)
        status_labels = [
            _FILTER_META[key][0]
            for key in _FILTER_META
            if key in self._status_filters
        ]
        label = ", ".join(status_labels) if status_labels else "სტატუსი"
        self._summary_text.value = f"{count} ჩანაწერი" if count else f"{label} არ არის"

        items: list[ft.PopupMenuItem] = []
        for key, (chip_label, _) in _FILTER_META.items():
            active = key in self._status_filters

            def on_click(e, k=key):
                if k in self._status_filters:
                    if len(self._status_filters) == 1:
                        return
                    self._status_filters.remove(k)
                else:
                    self._status_filters.add(k)
                self._apply_filter_change()

            items.append(ft.PopupMenuItem(
                checked=active,
                on_click=on_click,
                height=38,
                content=ft.Row(
                    controls=[
                        ft.Text(
                            chip_label,
                            size=12,
                            weight=ft.FontWeight.W_600,
                            color=ft.Colors.ON_SURFACE,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                ),
            ))

        self._filter_row.controls = [
            ft.PopupMenuButton(
                items=items,
                menu_padding=ft.padding.symmetric(vertical=4),
                content=ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.FILTER_LIST, size=15, color=runtime.accent),
                            ft.Text(
                                label,
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                            ft.Icon(
                                ft.Icons.KEYBOARD_ARROW_DOWN,
                                size=16,
                                color=runtime.muted_text,
                            ),
                        ],
                        spacing=SPACE_XS,
                        tight=True,
                    ),
                    bgcolor=_with_alpha(runtime.accent, 0.035),
                    border=ft.border.all(1, _with_alpha(runtime.accent, 0.12)),
                    border_radius=RADIUS_MD,
                    padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=6),
                    height=_HEADER_CONTROL_HEIGHT,
                    alignment=ft.Alignment(0, 0),
                ),
                padding=0,
            )
        ]

    # ──────────────────────────────────────────── credit list

    def _rebuild_list(self) -> None:
        rows: list[Credit | CreditPaymentDisplayRow]
        if self._view_mode == "payments":
            rows = self._payments
            empty_title = "მოტანები არ არის"
        else:
            rows = self._credits
            empty_title = "ნისია არ არის"

        if not rows:
            self._list_col.controls = [
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=40,
                                    color=ft.Colors.OUTLINE),
                            ft.Text(
                                empty_title,
                                size=14,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
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
            if self._view_mode == "payments":
                self._list_col.controls = [
                    self._payment_list_card(row)
                    for row in self._payments
                ]
            else:
                self._list_col.controls = [
                    self._credit_card(c) for c in self._credits
                ]

    def _credit_amount_story(
        self,
        credit: Credit,
        payments: list[CreditPayment] | None = None,
    ) -> tuple[Decimal, Decimal, float]:
        if payments is None:
            payments = self._credit_payments_by_id.get(credit.id or 0, [])
        sale_amounts = self._sale_amounts_by_credit_id.get(credit.id or 0)
        sale_total = (
            sale_amounts.sale_total
            if sale_amounts is not None
            else credit.original_amount
        )
        initial_paid = (
            sale_amounts.initial_paid
            if sale_amounts is not None
            else Decimal("0")
        )
        repayments_paid = sum((p.amount for p in payments), Decimal("0")).quantize(
            Decimal("0.01")
        )
        paid_total = (initial_paid + repayments_paid).quantize(Decimal("0.01"))
        progress = (
            min(float(paid_total / sale_total), 1.0)
            if sale_total > Decimal("0")
            else 0.0
        )
        return sale_total, paid_total, progress

    def _credit_card(self, credit: Credit) -> ft.Container:
        runtime = get_active_theme_runtime()
        selected = self._selected is not None and self._selected.id == credit.id
        status_color = _STATUS_COLOR.get(credit.status, ft.Colors.OUTLINE)
        credit_id = credit.id or 0
        payments = self._credit_payments_by_id.get(credit_id, [])
        expanded = credit_id in self._expanded_credit_ids
        sale_total, paid_total, progress = self._credit_amount_story(credit, payments)
        is_closed = credit.status in (CreditStatus.cleared, CreditStatus.forgiven)
        display_amount = sale_total if is_closed else credit.remaining_amount
        amount_meta = (
            f"სულ ₾{sale_total:.2f} · გადახდ. ₾{paid_total:.2f}"
            if is_closed
            else f"სულ ₾{sale_total:.2f} · გადახდ. ₾{paid_total:.2f}"
        )

        def on_click(e, c=credit):
            self._selected = c
            self._confirm_forgive = False
            self._editing_payment_id = None
            self._confirm_delete_payment_id = None
            self._rebuild_list()
            _safe_update(self._list_col)
            self._show_detail(c)

        def on_expand(e, cid=credit_id):
            if cid in self._expanded_credit_ids:
                self._expanded_credit_ids.remove(cid)
            else:
                self._expanded_credit_ids.add(cid)
            self._rebuild_list()
            _safe_update(self._list_col)

        payment_preview = self._expanded_payment_preview(payments, status_color, runtime)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(
                                    ft.Icons.KEYBOARD_ARROW_DOWN
                                    if expanded
                                    else ft.Icons.KEYBOARD_ARROW_RIGHT,
                                    size=17,
                                    color=runtime.accent,
                                ),
                                tooltip="მოტანების ნახვა",
                                width=26,
                                height=26,
                                alignment=ft.Alignment(0, 0),
                                border_radius=RADIUS_SM,
                                bgcolor=_with_alpha(runtime.accent, 0.08),
                                border=ft.border.all(1, _with_alpha(runtime.accent, 0.18)),
                                on_click=on_expand,
                                ink=True,
                            ),
                            ft.Text(
                                credit.code, size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                            ),
                            ft.Text(
                                f"{len(payments)} მოტანა",
                                size=10,
                                color=runtime.muted_text,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    _STATUS_LABEL.get(credit.status, ""),
                                    size=9, weight=ft.FontWeight.W_600,
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
                                credit.customer_surname, size=14,
                                weight=ft.FontWeight.W_600, expand=True,
                            ),
                            ft.Text(
                                f"₾{display_amount:.2f}", size=15,
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
                        height=3,
                        border_radius=ft.border_radius.all(2),
                    ),
                    *([payment_preview] if expanded else []),
                ],
                spacing=SPACE_XS + 1,
                tight=True,
            ),
            bgcolor=_with_alpha(runtime.accent, 0.08) if selected else runtime.panel_bg,
            border=ft.border.all(1, runtime.accent if selected else runtime.panel_border),
            border_radius=RADIUS_LG,
            padding=ft.padding.symmetric(horizontal=SPACE_SM + 2, vertical=SPACE_SM),
            on_click=on_click,
            ink=True,
        )

    def _expanded_payment_preview(
        self,
        payments: list[CreditPayment],
        status_color,
        runtime,
    ) -> ft.Container:
        if not payments:
            rows: list[ft.Control] = [
                ft.Text(
                    "მოტანები ჯერ არ ყოფილა",
                    size=11,
                    color=runtime.muted_text,
                )
            ]
        else:
            rows = [
                ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.PAYMENTS_OUTLINED,
                            size=13,
                            color=status_color,
                        ),
                        ft.Text(
                            fmt_date(payment.date),
                            size=11,
                            color=runtime.muted_text,
                            width=102,
                        ),
                        ft.Text(
                            payment.notes or "",
                            size=11,
                            color=runtime.muted_text,
                            expand=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(
                            f"₾{payment.amount:.2f}",
                            size=12,
                            weight=ft.FontWeight.W_700,
                            color=status_color,
                            width=82,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ],
                    spacing=SPACE_XS,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                for payment in payments
            ]

        return ft.Container(
            content=ft.Column(controls=rows, spacing=4, tight=True),
            bgcolor=_with_alpha(runtime.accent, 0.045),
            border=ft.border.all(1, _with_alpha(runtime.accent, 0.14)),
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_XS),
        )

    def _payment_list_card(self, row: CreditPaymentDisplayRow) -> ft.Container:
        runtime = get_active_theme_runtime()
        credit = row.credit
        selected = self._selected is not None and self._selected.id == credit.id
        status_color = _STATUS_COLOR.get(credit.status, ft.Colors.OUTLINE)
        note = (row.notes or "").strip()
        sale_total, paid_total, _ = self._credit_amount_story(credit)
        meta = (
            f"{credit.code} · გახსნილი {fmt_short_date(credit.date)} · "
            f"სულ ₾{sale_total:.2f} · გადახდ. ₾{paid_total:.2f}"
        )

        def on_click(e, c=credit):
            self._selected = c
            self._confirm_forgive = False
            self._editing_payment_id = None
            self._confirm_delete_payment_id = None
            self._rebuild_list()
            _safe_update(self._list_col)
            self._show_detail(c)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                fmt_date(row.date),
                                size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                expand=True,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    _STATUS_LABEL.get(credit.status, ""),
                                    size=9,
                                    weight=ft.FontWeight.W_600,
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
                                credit.customer_surname,
                                size=14,
                                weight=ft.FontWeight.W_600,
                                expand=True,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                f"₾{row.amount:.2f}",
                                size=15,
                                weight=ft.FontWeight.W_700,
                                color=ft.Colors.PRIMARY,
                            ),
                        ],
                    ),
                    ft.Text(
                        meta,
                        size=11,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    *(
                        [
                            ft.Text(
                                note,
                                size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            )
                        ]
                        if note
                        else []
                    ),
                ],
                spacing=SPACE_XS,
                tight=True,
            ),
            bgcolor=_with_alpha(runtime.accent, 0.08) if selected else runtime.panel_bg,
            border=ft.border.all(1, runtime.accent if selected else runtime.panel_border),
            border_radius=RADIUS_LG,
            padding=ft.padding.symmetric(horizontal=SPACE_SM + 2, vertical=SPACE_SM),
            on_click=on_click,
            ink=True,
        )

    # ──────────────────────────────────────────── detail panel

    def _empty_detail(self) -> ft.Control:
        message = (
            "აირჩიეთ ნისია სიიდან"
            if self._view_mode == "credits"
            else "აირჩიეთ მოტანა სიიდან"
        )
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
                            size=48, color=ft.Colors.OUTLINE),
                    ft.Text(message, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
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
        _safe_update(self._detail_area)

    def _build_detail(self, credit: Credit) -> ft.Control:
        with get_session() as session:
            payments = list_payments_for_credit(session, credit.id)

        sale_total, paid, progress = self._credit_amount_story(credit, payments)
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
                    _safe_update(pay_feedback)
                    return
                try:
                    with get_session() as session:
                        record_payment(
                            session,
                            credit_id=credit.id,
                            amount=amount,
                            date_paid=clock.today(),
                            notes=note_field.value.strip() or None,
                            created_by_user_id=self._user.id,
                        )
                        updated = session.get(type(credit), credit.id)
                        self._selected = updated
                except ValueError as exc:
                    pay_feedback.value = str(exc)
                    _safe_update(pay_feedback)
                    return

                self._load_rows()
                self._rebuild_view_row()
                self._rebuild_filter_row()
                self._rebuild_list()
                _safe_update(self._view_row)
                _safe_update(self._filter_row)
                _safe_update(self._list_count_text)
                _safe_update(self._date_scope_text)
                _safe_update(self._list_col)

                if self._selected and self._selected.status in (
                    CreditStatus.active, CreditStatus.partial
                ):
                    self._show_detail(self._selected)
                else:
                    self._selected = None
                    self._detail_area.content = _closed_confirmation("სრულად დაიფარა!")
                    _safe_update(self._detail_area)

            pay_btn = _action_btn("მოტანის დაფიქსირება", ACCENT_GOLD, on_pay)

            bottom_section = [
                ft.Divider(height=1),
                ft.Text("მოტანის დაფიქსირება", size=13, weight=ft.FontWeight.W_600,
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
                        self._load_rows()
                        self._rebuild_view_row()
                        self._rebuild_filter_row()
                        self._rebuild_list()
                        _safe_update(self._view_row)
                        _safe_update(self._filter_row)
                        _safe_update(self._list_count_text)
                        _safe_update(self._date_scope_text)
                        _safe_update(self._list_col)
                        self._detail_area.content = _closed_confirmation("ნისია ნაპატიებია.")
                        _safe_update(self._detail_area)

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
                                                "დარწმუნებული ხართ?",
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
                            "მხოლოდ ნახვის რეჟიმში მოტანა და პატიება გამორთულია.",
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
                clock.to_local(credit.forgiven_at).strftime("%d/%m/%Y %H:%M")
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
                        _safe_update(reopen_feedback)
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
                        _amount_chip("სულ", f"₾{sale_total:.2f}",
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
                ft.Text("მოტანების ისტორია", size=13, weight=ft.FontWeight.W_600,
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
        sale_amounts = self._sale_amounts_by_credit_id.get(credit.id or 0)
        initial_paid = (
            sale_amounts.initial_paid
            if sale_amounts is not None
            else Decimal("0")
        )
        rows: list[ft.Control] = []
        if initial_paid > Decimal("0"):
            rows.append(self._initial_payment_row(credit, initial_paid))

        if not payments:
            if rows:
                return rows
            return [
                ft.Text(
                    "მოტანები ჯერ არ ყოფილა",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                )
            ]

        rows.extend(
            self._payment_edit_row(credit, p)
            if self._editing_payment_id == p.id
            else self._payment_row(credit, p)
            for p in payments
        )
        return rows

    def _initial_payment_row(self, credit: Credit, amount: Decimal) -> ft.Control:
        return ft.Row(
            controls=[
                ft.Text(
                    fmt_date(credit.date),
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    width=110,
                ),
                ft.Text(
                    "დატოვებული თანხა",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    expand=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Text(
                    f"₾{amount:.2f}",
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color=ft.Colors.PRIMARY,
                    width=86,
                    text_align=ft.TextAlign.RIGHT,
                ),
            ],
            spacing=SPACE_XS,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

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
                _safe_update(feedback)
                return

            raw_date = (date_field.value or "").strip()
            try:
                paid_date = dt.date.fromisoformat(raw_date)
            except ValueError:
                feedback.value = "თარიღი უნდა იყოს YYYY-MM-DD ფორმატში."
                _safe_update(feedback)
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
                _safe_update(feedback)
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
                _safe_update(feedback)
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
        if (
            self._view_mode == "credits"
            and not self._status_allowed_by_current_filter(updated.status)
        ):
            for key, (_, statuses) in _FILTER_META.items():
                if updated.status in statuses:
                    self._status_filters = {key}
                    break

        self._load_rows()
        self._rebuild_view_row()
        self._rebuild_filter_row()
        self._rebuild_list()
        _safe_update(self._view_row)
        _safe_update(self._filter_row)
        _safe_update(self._list_count_text)
        _safe_update(self._search_field)
        _safe_update(self._date_scope_text)
        _safe_update(self._list_col)
        self._show_detail(updated)

    def _status_allowed_by_current_filter(self, status: CreditStatus) -> bool:
        return status in self._selected_credit_statuses()


# ─────────────────────────────────────────────── helpers

def _filter_btn(icon: str, label: ft.Text, on_click, runtime) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(icon, size=14, color=runtime.accent),
                label,
            ],
            spacing=SPACE_XS,
            tight=True,
        ),
        bgcolor=runtime.panel_bg,
        border=ft.border.all(1, runtime.panel_border),
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
        height=_HEADER_CONTROL_HEIGHT,
        alignment=ft.Alignment(0, 0),
        on_click=on_click,
        ink=True,
    )


def _preset_btn(label: str, active: bool, on_click, runtime) -> ft.Container:
    return ft.Container(
        content=ft.Text(
            label,
            size=12,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.WHITE if active else ft.Colors.ON_SURFACE_VARIANT,
        ),
        bgcolor=runtime.accent if active else _with_alpha(runtime.accent, 0.08),
        border=ft.border.all(
            1,
            runtime.accent if active else _with_alpha(runtime.accent, 0.18),
        ),
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_SM),
        height=_HEADER_CONTROL_HEIGHT,
        alignment=ft.Alignment(0, 0),
        on_click=on_click,
        ink=not active,
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


def _safe_update(control: ft.Control) -> None:
    try:
        control.update()
    except AssertionError:
        pass


def _with_alpha(color: str, alpha: float) -> str:
    if not isinstance(color, str) or not color.startswith("#"):
        return color
    value = color.lstrip("#")
    if len(value) != 6:
        return color
    opacity = max(0, min(255, round(alpha * 255)))
    return f"#{opacity:02X}{value}"
