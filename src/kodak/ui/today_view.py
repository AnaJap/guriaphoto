"""Today tab — transaction entry + range-history panel with date picker."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import flet as ft
from sqlmodel import select

from kodak.access import is_read_only
from kodak.db import get_session
from kodak.models.credit import Credit, CreditPayment
from kodak.models.enums import CreditStatus, ProductCategory
from kodak.models.transaction import Transaction
from kodak.models.user import User
from kodak.services.credits import list_open_credits
from kodak.services.export import export_history_to_xlsx
from kodak.services.history import (
    RangeSummary,
    TxnDetail,
    list_range_transactions,
    summarize_range,
)
from kodak.services.transactions import delete_transaction, update_transaction
from kodak.ui.geo import fmt_date, fmt_short_date, picker_date
from kodak.ui.theme import (
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    get_active_theme_runtime,
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


class TodayView:
    def __init__(self, page: ft.Page, user: User) -> None:
        self._page = page
        self._user = user
        self._tab = "entry"

        self._stats_row = ft.Row(spacing=SPACE_SM, wrap=True)
        self._stats_row.controls = self._build_stat_cards()

        self._header_area = ft.Container()
        self._tab_row = ft.Row(spacing=SPACE_XS)
        self._rebuild_tab_row()

        self._content = ft.Container(expand=True)
        self._content_shell = ft.Container(content=self._content, expand=True)
        # Don't load TransactionForm here — deferred to build() so prices
        # are always reloaded from the DB when the view becomes active.

        # Cache the history panel so DatePickers aren't duplicated on re-open
        self._history_panel: _HistoryPanel | None = None
        self._cash_view: "CashView | None" = None

    # ──────────────────────────────────────────── public

    def build(self) -> ft.Control:
        # Always reload entry form on (re-)mount so product prices are current.
        self._stats_row.controls = self._build_stat_cards()
        if self._tab == "entry":
            self._content.content = self._make_entry_view()

        today = dt.date.today()
        runtime = get_active_theme_runtime()
        self._sync_layout_chrome(runtime)
        return ft.Column(
            controls=[
                self._header_area,
                self._tab_row,
                self._content_shell,
            ],
            spacing=SPACE_SM,
            expand=True,
        )

    def _sync_layout_chrome(self, runtime=None) -> None:
        runtime = runtime or get_active_theme_runtime()
        expanded = self._tab == "entry"
        self._header_area.content = self._build_header_content(
            dt.date.today(),
            runtime,
            expanded=expanded,
        )
        self._header_area.bgcolor = runtime.panel_bg
        self._header_area.border = ft.border.all(1, runtime.panel_border)
        self._header_area.border_radius = RADIUS_LG + 4
        self._header_area.padding = ft.padding.all(SPACE_MD)

        self._content_shell.bgcolor = runtime.panel_bg
        self._content_shell.border = ft.border.all(1, runtime.panel_border)
        self._content_shell.border_radius = RADIUS_LG + 4
        self._content_shell.padding = ft.padding.all(SPACE_LG if expanded else SPACE_MD)

    def _build_header_content(self, today: dt.date, runtime, *, expanded: bool) -> ft.Control:
        title = ft.Column(
            controls=[
                ft.Text(fmt_date(today), size=12, color=runtime.muted_text),
                ft.Text("დღეს", size=22 if expanded else 20, weight=ft.FontWeight.W_700),
            ],
            spacing=0,
            tight=True,
        )
        controls: list[ft.Control] = [title]
        if expanded:
            controls.extend([ft.Container(height=SPACE_XS), self._stats_row])
        return ft.Column(controls=controls, spacing=SPACE_XS, tight=True)

    # ──────────────────────────────────────────── stats

    def _build_stat_cards(self) -> list[ft.Control]:
        today = dt.date.today()
        with get_session() as session:
            txns = list(session.exec(
                select(Transaction).where(Transaction.date == today)
            ).all())
            new_credits = list(session.exec(
                select(Credit).where(Credit.date == today)
            ).all())
            credit_payments = list(session.exec(
                select(CreditPayment).where(CreditPayment.date == today)
            ).all())
            open_credits = list_open_credits(session)
        sales_cash = sum(t.amount_received for t in txns)
        credit_cash = sum(p.amount for p in credit_payments)
        cashier_income = sales_cash + credit_cash
        runtime = get_active_theme_runtime()
        return [
            _stat_card("დღევანდელი გაყიდვები", str(len(txns)), ft.Icons.RECEIPT_LONG, runtime),
            _stat_card(
                "სალაროს შემოსავალი",
                f"\u20be{cashier_income:.2f}",
                ft.Icons.PAYMENTS,
                runtime,
                note="გაყიდვებში მიღებული + დაბრუნებული ნისიები",
                width=320,
            ),
            _stat_card("ახალი ნისიები", str(len(new_credits)), ft.Icons.POST_ADD, runtime),
            _stat_card("დაბრუნებული ნისიები", str(len(credit_payments)), ft.Icons.REPLAY_CIRCLE_FILLED_OUTLINED, runtime),
            _stat_card("სულ აქტიური ნისიები", str(len(open_credits)), ft.Icons.ACCOUNT_BALANCE_WALLET, runtime),
        ]

    def refresh_stats(self) -> None:
        self._stats_row.controls = self._build_stat_cards()
        self._sync_layout_chrome()
        if self._header_area.page is not None:
            self._header_area.update()
        elif self._stats_row.page is not None:
            self._stats_row.update()

    # ──────────────────────────────────────────── tabs

    def _rebuild_tab_row(self) -> None:
        self._tab_row.controls = [
            self._tab_chip("entry",   "შეყვანა",  ft.Icons.ADD_CIRCLE_OUTLINE),
            self._tab_chip("history", "ისტორია",  ft.Icons.HISTORY),
            self._tab_chip("cash",    "ნაღდი",    ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED),
        ]

    def _tab_chip(self, key: str, label: str, icon: str) -> ft.Container:
        runtime = get_active_theme_runtime()
        active = self._tab == key

        def on_click(e, k=key):
            if self._tab == k:
                return
            self._tab = k
            self._rebuild_tab_row()
            self._sync_layout_chrome()
            if self._header_area.page is not None:
                self._header_area.update()
            if self._content_shell.page is not None:
                self._content_shell.update()
            self._tab_row.update()
            if k == "entry":
                self._content.content = self._make_entry_view()
            elif k == "history":
                self._content.content = self._get_history_panel().build()
            else:
                self._content.content = self._get_cash_view().build()
            self._content.update()

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(icon, size=14,
                            color=ft.Colors.WHITE if active else runtime.muted_text),
                    ft.Text(label, size=13, weight=ft.FontWeight.W_600,
                            color=ft.Colors.WHITE if active else runtime.muted_text),
                ],
                spacing=SPACE_XS,
                tight=True,
            ),
            bgcolor=runtime.accent if active else _with_alpha(runtime.accent, 0.08),
            border=ft.border.all(1, _with_alpha(runtime.accent, 0.20) if not active else runtime.accent),
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=on_click,
            ink=not active,
        )

    # ──────────────────────────────────────────── entry tab

    def _make_entry_view(self) -> ft.Control:
        from kodak.ui.transaction_form import TransactionForm
        return TransactionForm(
            user=self._user,
            on_saved=self._on_saved,
        ).build()

    def _on_saved(self) -> None:
        self.refresh_stats()
        # Invalidate cached history panel so next open sees fresh data
        if self._history_panel is not None:
            self._history_panel.mark_stale()

    # ──────────────────────────────────────────── panel caches

    def _get_cash_view(self) -> "CashView":
        from kodak.ui.cash_view import CashView
        if self._cash_view is None:
            self._cash_view = CashView(user=self._user)
        return self._cash_view

    def _get_history_panel(self) -> "_HistoryPanel":
        if self._history_panel is None:
            self._history_panel = _HistoryPanel(
                self._page,
                self._user,
                on_changed=self.refresh_stats,
            )
        else:
            self._history_panel.reload_if_stale()
        return self._history_panel


# ──────────────────────────────────────────────── history panel

class _HistoryPanel:
    _PRESETS = [
        ("today",      "დღეს"),
        ("week",       "კვირა"),
        ("month",      "ეს თვე"),
        ("last_month", "გასული თვე"),
    ]

    def __init__(self, page: ft.Page, user: User, *, on_changed=None) -> None:
        self._page = page
        self._user = user
        self._on_changed = on_changed
        self._can_edit_records = not is_read_only()
        self._stale = False
        self._mounted = False

        # Search + inline-edit state
        self._rows:           list[TxnDetail] = []
        self._search_query:   str             = ""
        self._editing_txn_id: int | None      = None

        self._search_field = ft.TextField(
            hint_text="ძებნა გვარით…",
            border_radius=RADIUS_MD,
            text_size=13,
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._on_search_change,
            expand=True,
            height=42,
        )

        today = dt.date.today()
        self._start = today
        self._end = today
        self._active_preset: str = "today"

        # ── date pickers (live in page.overlay) ──────────────────────
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

        # Excel export save-dialog (FilePicker lives in page.services)
        self._export_picker = ft.FilePicker()
        self._page.services.append(self._export_picker)
        self._page.update()

        # ── mutable controls ──────────────────────────────────────────
        self._preset_row  = ft.Row(spacing=SPACE_XS, wrap=True)
        self._from_label  = ft.Text("", size=13, weight=ft.FontWeight.W_600)
        self._to_label    = ft.Text("", size=13, weight=ft.FontWeight.W_600)
        self._summary_row = ft.Row(spacing=SPACE_XS, run_spacing=SPACE_XS, wrap=True)
        self._export_feedback = ft.Text("", size=11)
        self._cat_col     = ft.Column(spacing=3, tight=True)
        self._list_col    = ft.Column(spacing=SPACE_XS, scroll=ft.ScrollMode.AUTO, expand=True)
        self._list_count  = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        # Populate controls without calling .update() (not mounted yet)
        self._rebuild_preset_row()
        self._sync_date_labels()
        self._load_data()

    # ── public ───────────────────────────────────────────────────────

    def build(self) -> ft.Control:
        """Return (or re-return) the root Column. Call once after __init__."""
        runtime = get_active_theme_runtime()
        from_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=14,
                            color=runtime.accent),
                    self._from_label,
                ],
                spacing=SPACE_XS,
                tight=True,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=lambda e: self._open_picker("start"),
            ink=True,
        )
        to_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=14,
                            color=runtime.accent),
                    self._to_label,
                ],
                spacing=SPACE_XS,
                tight=True,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=lambda e: self._open_picker("end"),
            ink=True,
        )
        date_row = ft.Row(
            controls=[
                from_btn,
                ft.Text("–", size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                to_btn,
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        export_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.FILE_DOWNLOAD_OUTLINED, size=16,
                            color=ft.Colors.WHITE),
                    ft.Text("Excel-ში ექსპორტი", size=13,
                            weight=ft.FontWeight.W_600, color=ft.Colors.WHITE),
                ],
                spacing=SPACE_XS,
                alignment=ft.MainAxisAlignment.CENTER,
                tight=True,
            ),
            bgcolor=runtime.accent,
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=self._on_export,
            ink=True,
        )

        filters = ft.Column(
            controls=[
                self._preset_row,
                date_row,
                self._summary_row,
                export_btn,
                self._export_feedback,
                ft.Text(
                    "კატეგორიები", size=11, weight=ft.FontWeight.W_600,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                self._cat_col,
            ],
            spacing=SPACE_SM,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        filters_panel = ft.Container(
            content=filters,
            bgcolor=_with_alpha(runtime.accent, 0.025),
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_MD),
            width=330,
        )

        transactions_panel = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("ტრანზაქციები", size=14, weight=ft.FontWeight.W_700),
                            ft.Container(content=self._search_field, expand=True),
                            self._list_count,
                        ],
                        spacing=SPACE_SM,
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

        self._root = ft.Row(
            controls=[
                filters_panel,
                transactions_panel,
            ],
            spacing=SPACE_MD,
            vertical_alignment=ft.CrossAxisAlignment.START,
            expand=True,
        )
        self._mounted = True
        return self._root

    def mark_stale(self) -> None:
        self._stale = True

    def reload_if_stale(self) -> None:
        if self._stale:
            self._editing_txn_id = None
            self._load_data()
            self._flush_ui()
            if self._on_changed is not None:
                self._on_changed()
            self._stale = False

    # ── date picker ──────────────────────────────────────────────────

    def _open_picker(self, which: str) -> None:
        if which == "start":
            self._dp_start.value = self._start
            self._dp_start.open = True
            self._dp_start.update()
        else:
            self._dp_end.value = self._end
            self._dp_end.open = True
            self._dp_end.update()

    def _on_start_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        picked = min(picker_date(raw), dt.date.today())
        self._start = picked
        if self._start > self._end:
            self._end = self._start
        self._active_preset = "custom"
        self._apply_range_change()

    def _on_end_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        picked = min(picker_date(raw), dt.date.today())
        self._end = picked
        if self._end < self._start:
            self._start = self._end
        self._active_preset = "custom"
        self._apply_range_change()

    # ── presets ──────────────────────────────────────────────────────

    def _set_preset(self, preset: str) -> None:
        today = dt.date.today()
        if preset == "today":
            self._start = today
            self._end = today
        elif preset == "week":
            self._start = today - dt.timedelta(days=today.weekday())
            self._end = today
        elif preset == "month":
            self._start = today.replace(day=1)
            self._end = today
        elif preset == "last_month":
            first_this = today.replace(day=1)
            last_prev = first_this - dt.timedelta(days=1)
            self._start = last_prev.replace(day=1)
            self._end = last_prev
        self._active_preset = preset
        self._apply_range_change()

    def _rebuild_preset_row(self) -> None:
        runtime = get_active_theme_runtime()
        chips = []
        for key, label in self._PRESETS:
            active = self._active_preset == key

            def on_click(e, k=key):
                self._set_preset(k)

            chips.append(ft.Container(
                content=ft.Text(
                    label, size=12, weight=ft.FontWeight.W_600,
                    color=ft.Colors.ON_PRIMARY if active else ft.Colors.ON_SURFACE_VARIANT,
                ),
                bgcolor=runtime.accent if active else _with_alpha(runtime.accent, 0.08),
                border=ft.border.all(1, _with_alpha(runtime.accent, 0.18) if not active else runtime.accent),
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=5),
                on_click=on_click,
                ink=not active,
            ))
        # Custom indicator (no button, just a muted chip when active)
        if self._active_preset == "custom":
            chips.append(ft.Container(
                content=ft.Text(
                    "პერიოდი", size=12, weight=ft.FontWeight.W_600,
                    color=ft.Colors.WHITE,
                ),
                bgcolor=runtime.accent,
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=5),
            ))
        self._preset_row.controls = chips

    def _sync_date_labels(self) -> None:
        self._from_label.value = fmt_short_date(self._start)
        self._to_label.value   = fmt_short_date(self._end)

    # ── excel export ──────────────────────────────────────────────────

    def _on_export(self, e) -> None:
        self._page.run_task(self._export_excel)

    async def _export_excel(self) -> None:
        default_name = (
            f"kodak_history_{self._start:%Y-%m-%d}_{self._end:%Y-%m-%d}.xlsx"
        )
        try:
            target = await self._export_picker.save_file(
                dialog_title="შეინახეთ Excel ფაილი",
                file_name=default_name,
                allowed_extensions=["xlsx"],
            )
        except Exception as exc:
            self._set_export_feedback(f"ექსპორტი ვერ მოხერხდა: {exc}", error=True)
            return
        if not target:
            return

        path = Path(target)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")

        # Re-query so the export always reflects the latest saved data.
        with get_session() as session:
            rows = list_range_transactions(session, self._start, self._end)
            summary = summarize_range(
                rows, session=session, start=self._start, end=self._end
            )

        try:
            export_history_to_xlsx(
                path,
                start=self._start,
                end=self._end,
                summary=summary,
                rows=rows,
            )
        except Exception as exc:
            self._set_export_feedback(f"ფაილის შენახვა ვერ მოხერხდა: {exc}", error=True)
            return

        self._set_export_feedback(f"შენახულია: {path.name}")

    def _set_export_feedback(self, message: str, *, error: bool = False) -> None:
        self._export_feedback.value = message
        self._export_feedback.color = ft.Colors.ERROR if error else ft.Colors.PRIMARY
        if self._mounted and self._export_feedback.page is not None:
            self._export_feedback.update()

    # ── data ─────────────────────────────────────────────────────────

    def _apply_range_change(self) -> None:
        """Called whenever the date range or preset changes."""
        self._rebuild_preset_row()
        self._sync_date_labels()
        self._load_data()
        self._flush_ui()

    def _load_data(self) -> None:
        with get_session() as session:
            rows = list_range_transactions(session, self._start, self._end)
            summary = summarize_range(
                rows, session=session, start=self._start, end=self._end
            )
        self._rows = rows
        self._build_summary_controls(summary)
        self._build_cat_controls(summary)
        self._build_list_controls(rows)

    def _build_summary_controls(self, s: RangeSummary) -> None:
        runtime = get_active_theme_runtime()
        self._summary_row.controls = [
            _history_metric(
                "სულ გაყიდვები", str(s.total_txns),
                ft.Icons.RECEIPT_LONG, runtime,
            ),
            _history_metric(
                "ჯამური გაყიდვები", f"₾{s.total_revenue:.2f}",
                ft.Icons.SHOPPING_CART_OUTLINED, runtime,
            ),
            _history_metric(
                "მიღებული გაყიდვებიდან", f"₾{s.received_from_sales:.2f}",
                ft.Icons.PAYMENTS, runtime,
            ),
            _history_metric(
                "დაბრუნებული ნისიები", f"₾{s.credit_received_amount:.2f}",
                ft.Icons.REPLAY_CIRCLE_FILLED_OUTLINED, runtime,
            ),
            _history_metric(
                "ახალი ნისიები", str(s.new_credit_count),
                ft.Icons.POST_ADD, runtime,
            ),
            _history_metric(
                "სალაროში მიღებული", f"₾{s.cashier_received:.2f}",
                ft.Icons.ACCOUNT_BALANCE_WALLET, runtime,
                highlight=True,
            ),
        ]

    def _build_cat_controls(self, s: RangeSummary) -> None:
        runtime = get_active_theme_runtime()
        if not s.categories:
            self._cat_col.controls = []
            return
        max_rev = max(c.revenue for c in s.categories) or Decimal("1")
        rows: list[ft.Control] = []
        for cs in s.categories:
            bar_frac = float(cs.revenue / max_rev)
            rows.append(ft.Row(
                controls=[
                    ft.Text(
                        _CAT_LABEL.get(cs.category, cs.category.value),
                        size=11, width=74,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Stack(
                        controls=[
                            ft.Container(
                                width=88, height=7,
                                bgcolor=_with_alpha(runtime.accent, 0.10),
                                border_radius=4,
                            ),
                            ft.Container(
                                width=max(4, int(88 * bar_frac)),
                                height=7,
                                bgcolor=runtime.accent,
                                border_radius=4,
                            ),
                        ],
                        width=88, height=7,
                    ),
                    ft.Text(
                        str(cs.qty), size=11, width=24,
                        text_align=ft.TextAlign.RIGHT,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.Text(
                        f"\u20be{cs.revenue:.2f}", size=11,
                        weight=ft.FontWeight.W_600, width=54,
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ],
                spacing=SPACE_XS,
            ))
        self._cat_col.controls = rows

    def _build_list_controls(self, rows: list[TxnDetail]) -> None:
        runtime = get_active_theme_runtime()
        # Apply surname search filter
        q = self._search_query
        visible = [r for r in rows if q in r.txn.customer_surname.lower()] if q else rows
        self._list_count.value = f"{len(visible)} ჩანაწერი"

        if not visible:
            msg = "ვერ მოიძებნა" if q else "ამ პერიოდში ჩანაწერი არ არის"
            self._list_col.controls = [
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.RECEIPT_LONG, size=40, color=ft.Colors.OUTLINE),
                            ft.Text(msg, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=SPACE_SM, tight=True,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER,
                    border=ft.border.all(1, runtime.panel_border),
                    border_radius=RADIUS_LG,
                    padding=ft.padding.all(SPACE_LG * 2),
                    alignment=ft.Alignment(0, 0),
                )
            ]
            return

        # Group by date, newest day first
        by_date: dict[dt.date, list[TxnDetail]] = {}
        for r in visible:
            by_date.setdefault(r.txn.date, []).append(r)

        controls: list[ft.Control] = []
        for date in sorted(by_date.keys(), reverse=True):
            day_txns = by_date[date]
            day_total = sum(d.total for d in day_txns)
            controls.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Text(
                                fmt_date(date), size=12,
                                weight=ft.FontWeight.W_600,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                expand=True,
                            ),
                            ft.Text(
                                f"\u20be{day_total:.2f}", size=12,
                                weight=ft.FontWeight.W_700,
                                color=runtime.accent,
                            ),
                        ],
                    ),
                    padding=ft.padding.only(top=SPACE_SM, bottom=2),
                )
            )
            for d in day_txns:
                if self._editing_txn_id == d.txn.id:
                    controls.append(self._build_edit_form(d))
                elif self._can_edit_records:
                    controls.append(self._editable_card(d))
                else:
                    controls.append(_txn_card(d, runtime))

        self._list_col.controls = controls

    # ── search ───────────────────────────────────────────────────────

    def _on_search_change(self, e) -> None:
        self._search_query = (e.control.value or "").strip().lower()
        self._editing_txn_id = None
        self._build_list_controls(self._rows)
        self._list_count.update()
        self._list_col.update()

    # ── editable card (read-only card + edit pencil overlay) ─────────

    def _editable_card(self, d: TxnDetail) -> ft.Stack:
        runtime = get_active_theme_runtime()
        def on_edit(e, txn_id=d.txn.id):
            self._editing_txn_id = txn_id
            self._build_list_controls(self._rows)
            self._list_col.update()

        return ft.Stack(
            controls=[
                _txn_card(d, runtime),
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.EDIT_OUTLINED, size=13,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    on_click=on_edit,
                    ink=True,
                    border_radius=RADIUS_SM,
                    bgcolor=runtime.panel_bg,
                    border=ft.border.all(1, runtime.panel_border),
                    padding=ft.padding.all(5),
                    alignment=ft.Alignment(0, 0),
                    width=26,
                    height=26,
                    right=SPACE_SM,
                    top=SPACE_SM,
                ),
            ],
        )

    # ── inline edit form ─────────────────────────────────────────────

    def _build_edit_form(self, d: TxnDetail) -> ft.Container:
        """Inline card that replaces the read-only card for record editing."""
        runtime = get_active_theme_runtime()
        surname_f = ft.TextField(
            value=d.txn.customer_surname,
            label="გვარი",
            border_radius=RADIUS_MD,
            text_size=13,
            expand=True,
        )
        received_f = ft.TextField(
            value=str(d.txn.amount_received),
            label="გადახდილი  ₾",
            border_radius=RADIUS_MD,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_size=13,
            expand=True,
        )
        notes_f = ft.TextField(
            value=d.txn.notes or "",
            label="შენიშვნა",
            hint_text="სურვილისამებრ",
            border_radius=RADIUS_MD,
            text_size=13,
            expand=True,
        )
        feedback       = ft.Text("", size=12)
        confirm_row    = ft.Row(spacing=SPACE_XS, visible=False)

        # ── line items summary (read-only) ────────────────────────
        item_lines = [
            ft.Row(
                controls=[
                    ft.Text(
                        f"{prod.name} {prod.size_label or ''}".strip(),
                        size=11, expand=True,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.Text(f"×{li.quantity}", size=11, width=28,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(f"\u20be{li.line_total:.2f}", size=11,
                            weight=ft.FontWeight.W_600, width=52,
                            text_align=ft.TextAlign.RIGHT),
                ],
                spacing=SPACE_XS,
            )
            for li, prod in d.items
        ]
        item_lines.append(ft.Row(
            controls=[
                ft.Text("სულ", size=12, expand=True,
                        weight=ft.FontWeight.W_600),
                ft.Text(f"\u20be{d.total:.2f}", size=13,
                        weight=ft.FontWeight.W_700, width=52,
                        text_align=ft.TextAlign.RIGHT),
            ],
            spacing=SPACE_XS,
        ))

        # ── handlers ─────────────────────────────────────────────
        def _cancel(e=None):
            self._editing_txn_id = None
            self._build_list_controls(self._rows)
            self._list_col.update()

        def on_save(e):
            feedback.color = ft.Colors.ERROR
            raw = (received_f.value or "").strip().replace(",", ".")
            try:
                received = Decimal(raw)
            except Exception:
                feedback.value = "შეიყვანეთ სწორი თანხა."
                feedback.update()
                return
            sn = (surname_f.value or "").strip()
            if not sn:
                feedback.value = "გვარი სავალდებულოა."
                feedback.update()
                return
            try:
                with get_session() as session:
                    update_transaction(
                        session,
                        d.txn.id,
                        customer_surname=sn,
                        amount_received=received,
                        notes=(notes_f.value or "").strip() or None,
                    )
            except ValueError as exc:
                feedback.value = str(exc)
                feedback.update()
                return
            self._editing_txn_id = None
            self._load_data()
            self._flush_ui()
            if self._on_changed is not None:
                self._on_changed()

        def on_delete_click(e):
            confirm_row.controls = [
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED,
                        size=14, color=ft.Colors.ERROR),
                ft.Text("დარწმუნებული ხართ?", size=12,
                        color=ft.Colors.ERROR, expand=True),
                _mini_btn("წაშლა", ft.Colors.ERROR, on_delete_confirm),
                _mini_btn("გაუქმება", ft.Colors.SURFACE_CONTAINER_HIGH,
                          lambda e: _hide_confirm(),
                          text_color=ft.Colors.ON_SURFACE),
            ]
            confirm_row.visible = True
            confirm_row.update()

        def _hide_confirm():
            confirm_row.visible = False
            confirm_row.update()

        def on_delete_confirm(e):
            feedback.color = ft.Colors.ERROR
            try:
                with get_session() as session:
                    delete_transaction(session, d.txn.id)
            except ValueError as exc:
                confirm_row.visible = False
                confirm_row.update()
                feedback.value = str(exc)
                feedback.update()
                return
            self._editing_txn_id = None
            self._load_data()
            self._flush_ui()
            if self._on_changed is not None:
                self._on_changed()

        return ft.Container(
            content=ft.Column(
                controls=[
                    # Header row
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.EDIT_OUTLINED, size=13,
                                    color=runtime.accent),
                            ft.Text("რედაქტირება", size=11,
                                    weight=ft.FontWeight.W_600,
                                    color=runtime.accent, expand=True),
                            ft.Text(
                                d.txn.created_at.strftime("%H:%M  ·  ")
                                + fmt_date(d.txn.date),
                                size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                    ),
                    # Line items (read-only)
                    ft.Container(
                        content=ft.Column(
                            controls=item_lines, spacing=3, tight=True,
                        ),
                        bgcolor=_with_alpha(runtime.accent, 0.06),
                        border=ft.border.all(1, runtime.panel_border),
                        border_radius=RADIUS_SM,
                        padding=ft.padding.all(SPACE_SM),
                    ),
                    ft.Divider(height=1),
                    # Editable fields
                    ft.Row(controls=[surname_f]),
                    ft.Row(controls=[received_f]),
                    ft.Row(controls=[notes_f]),
                    # Action buttons
                    ft.Row(
                        controls=[
                            _mini_btn("შენახვა", runtime.accent, on_save,
                                      expand=True),
                            _mini_btn("გაუქმება",
                                      ft.Colors.SURFACE_CONTAINER_HIGH,
                                      _cancel,
                                      text_color=ft.Colors.ON_SURFACE,
                                      expand=True),
                            _mini_btn("წაშლა", ft.Colors.ERROR,
                                      on_delete_click, expand=True),
                        ],
                        spacing=SPACE_XS,
                    ),
                    confirm_row,
                    feedback,
                ],
                spacing=SPACE_SM,
                tight=True,
            ),
            bgcolor=runtime.panel_bg,
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_MD),
            border=ft.border.all(1, runtime.panel_border),
        )

    # ── UI flush ─────────────────────────────────────────────────────

    def _flush_ui(self) -> None:
        """Push control updates to the page (only when mounted)."""
        if not self._mounted:
            return
        self._preset_row.update()
        self._from_label.update()
        self._to_label.update()
        self._summary_row.update()
        self._cat_col.update()
        self._list_count.update()
        self._list_col.update()


# ──────────────────────────────────────────────────── shared helpers

def _txn_card(d: TxnDetail, runtime=None) -> ft.Container:
    runtime = runtime or get_active_theme_runtime()
    time_str = d.txn.created_at.strftime("%H:%M")
    has_credit = d.credit is not None
    credit_cleared = has_credit and d.credit.status == CreditStatus.cleared
    item_summary = ", ".join(
        f"{prod.name} {prod.size_label or ''}".strip() + f" x{li.quantity}"
        for li, prod in d.items
    )

    credit_badges: list[ft.Control] = []
    if has_credit:
        badge_color = "#4CAF50" if credit_cleared else runtime.accent
        badge_text = (
            "ნისია დახურულია"
            if credit_cleared
            else f"ნისია {d.credit.code}  \u20be{d.credit.remaining_amount:.2f}"
        )
        credit_badges = [
            ft.Container(
                content=ft.Text(badge_text, size=11, weight=ft.FontWeight.W_600,
                                color=ft.Colors.WHITE),
                bgcolor=badge_color,
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=3),
            )
        ]

    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Text(time_str, size=11, color=ft.Colors.ON_SURFACE_VARIANT, width=38),
                ft.Column(
                    controls=[
                        ft.Text(d.txn.customer_surname, size=15,
                                weight=ft.FontWeight.W_600),
                        ft.Text(
                            item_summary or "—",
                            size=11,
                            color=runtime.muted_text,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=0,
                    tight=True,
                    expand=True,
                ),
                ft.Column(
                    controls=[
                        ft.Text(
                            f"\u20be{d.total:.2f}",
                            size=15,
                            weight=ft.FontWeight.W_700,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                        ft.Text(
                            f"მიღ. \u20be{d.txn.amount_received:.2f}",
                            size=10,
                            color=runtime.muted_text,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                    ],
                    spacing=0,
                    tight=True,
                    width=94,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                ),
                *credit_badges,
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=runtime.panel_bg,
        border=ft.border.all(1, runtime.panel_border),
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
    )


def _mini_btn(
    label: str,
    bgcolor,
    on_click,
    *,
    text_color=ft.Colors.WHITE,
    expand: bool = False,
) -> ft.Container:
    return ft.Container(
        content=ft.Text(
            label, size=12, weight=ft.FontWeight.W_600,
            color=text_color, text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=bgcolor,
        border_radius=RADIUS_SM,
        padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=6),
        alignment=ft.Alignment(0, 0),
        on_click=on_click,
        ink=True,
        expand=expand,
    )


def _stat_card(
    label: str,
    value: str,
    icon: str,
    runtime=None,
    *,
    note: str | None = None,
    width: int = 186,
) -> ft.Container:
    runtime = runtime or get_active_theme_runtime()
    text_controls: list[ft.Control] = [
        ft.Text(value, size=18, weight=ft.FontWeight.W_700),
        ft.Text(label, size=11, color=runtime.muted_text, max_lines=2),
    ]
    if note:
        text_controls.append(
            ft.Text(
                note,
                size=9,
                color=runtime.muted_text,
                max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
        )
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(
                    content=ft.Icon(icon, size=15, color=runtime.accent),
                    bgcolor=_with_alpha(runtime.accent, 0.10),
                    border_radius=9,
                    padding=ft.padding.all(SPACE_XS + 2),
                ),
                ft.Column(
                    controls=text_controls,
                    spacing=1,
                    tight=True,
                    expand=True,
                ),
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=runtime.panel_bg,
        border=ft.border.all(1, runtime.panel_border),
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
        width=width,
        height=74,
    )


def _history_metric(
    label: str,
    value: str,
    icon: str,
    runtime=None,
    *,
    highlight: bool = False,
) -> ft.Container:
    runtime = runtime or get_active_theme_runtime()
    value_color = runtime.accent if highlight else None
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(icon, size=14, color=runtime.accent),
                ft.Column(
                    controls=[
                        ft.Text(value, size=15, weight=ft.FontWeight.W_700,
                                color=value_color),
                        ft.Text(
                            label, size=10, color=runtime.muted_text,
                            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=0,
                    tight=True,
                    expand=True,
                ),
            ],
            spacing=SPACE_XS,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=_with_alpha(runtime.accent, 0.08) if highlight else runtime.panel_bg,
        border=ft.border.all(
            1, runtime.accent if highlight else runtime.panel_border
        ),
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_SM),
        width=138,
    )


def _with_alpha(color: str, alpha: float) -> str:
    raw = color.lstrip("#")
    pct = max(0, min(255, round(alpha * 255)))
    return f"#{pct:02X}{raw.upper()}"
