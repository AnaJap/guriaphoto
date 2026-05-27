"""Report tab — period summary with CSV export."""

from __future__ import annotations

import csv
import datetime as dt
import io
import platform
import subprocess
from decimal import Decimal
from pathlib import Path

import flet as ft

from kodak import clock
from kodak.db import get_session
from kodak.models.enums import ProductCategory
from kodak.models.user import User
from kodak.services.report import ReportData, build_report, last_day_of_month
from kodak.ui.geo import fmt_month_year, fmt_short_date, picker_date
from kodak.ui.theme import (
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
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

_PRESETS = [
    ("month",      "ეს თვე"),
    ("last_month", "გასული თვე"),
    ("custom",     "პერიოდი"),
]


class ReportView:
    def __init__(self, page: ft.Page, user: User) -> None:
        self._page     = page
        self._user     = user
        self._mounted  = False
        self._data: ReportData | None = None

        today = clock.today()
        self._active_preset = "month"
        self._month = today.replace(day=1)          # first day of displayed month
        self._start = self._month
        self._end   = today

        # ── date pickers ───────────────────────────────────────────
        self._dp_start = ft.DatePicker(
            value=self._start,
            first_date=dt.date(2020, 1, 1),
            last_date=today,
            help_text="დაწყება",
            confirm_text="კარგი",
            cancel_text="გაუქმება",
            on_change=self._on_start_picked,
        )
        self._dp_end = ft.DatePicker(
            value=self._end,
            first_date=dt.date(2020, 1, 1),
            last_date=today,
            help_text="დასრულება",
            confirm_text="კარგი",
            cancel_text="გაუქმება",
            on_change=self._on_end_picked,
        )
        self._page.overlay.extend([self._dp_start, self._dp_end])
        self._page.update()

        # ── mutable controls ───────────────────────────────────────
        self._preset_row   = ft.Row(spacing=SPACE_XS, wrap=True)
        self._period_ctrl  = ft.Container()   # month nav OR date pickers
        self._summary_row  = ft.Row(spacing=SPACE_SM, run_spacing=SPACE_SM, wrap=True)
        self._cat_col      = ft.Column(spacing=SPACE_XS, tight=True)
        self._day_col      = ft.Column(spacing=SPACE_XS, scroll=ft.ScrollMode.AUTO, expand=True)
        self._breakdown_col = ft.Column(spacing=SPACE_SM, tight=True)
        self._export_label = ft.Text("", size=12, color=ft.Colors.PRIMARY)

        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._load_data()

    # ── public ────────────────────────────────────────────────────

    def build(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        export_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.DOWNLOAD_OUTLINED, size=16,
                            color=ft.Colors.WHITE),
                    ft.Text("Excel-ში ექსპორტი", size=13, weight=ft.FontWeight.W_600,
                            color=ft.Colors.WHITE),
                ],
                spacing=SPACE_XS, tight=True,
            ),
            bgcolor=runtime.accent,
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=self._export_csv,
            ink=True,
            tooltip="Excel-ში გახსნადი ფაილად შენახვა",
        )

        period_box = ft.Container(
            content=ft.Row(
                controls=[
                    self._preset_row,
                    ft.Container(expand=True),
                    self._period_ctrl,
                ],
                spacing=SPACE_MD,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
        )
        cash_flow_panel = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("სალაროს მოძრაობა", size=14, weight=ft.FontWeight.W_700),
                    self._day_col,
                ],
                spacing=SPACE_SM,
                expand=True,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_MD),
            expand=True,
        )
        breakdown_panel = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("გაყიდვები და ნისიები", size=14, weight=ft.FontWeight.W_700),
                    self._breakdown_col,
                    ft.Divider(height=SPACE_MD),
                    ft.Text("კატეგორიები", size=14, weight=ft.FontWeight.W_700),
                    self._cat_col,
                ],
                spacing=SPACE_SM,
                scroll=ft.ScrollMode.AUTO,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_MD),
            width=390,
        )

        self._root = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("ანგარიშები", size=28, weight=ft.FontWeight.W_700,
                                expand=True),
                        self._export_label,
                        export_btn,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                period_box,
                self._summary_row,
                ft.Row(
                    controls=[
                        cash_flow_panel,
                        breakdown_panel,
                    ],
                    spacing=SPACE_MD,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    expand=True,
                ),
            ],
            spacing=SPACE_SM,
            expand=True,
        )
        self._mounted = True
        return self._root

    # ── presets ───────────────────────────────────────────────────

    def _set_preset(self, preset: str) -> None:
        today = clock.today()
        if preset == "month":
            self._month = today.replace(day=1)
            self._start = self._month
            self._end   = today
        elif preset == "last_month":
            first_this  = today.replace(day=1)
            last_prev   = first_this - dt.timedelta(days=1)
            self._month = last_prev.replace(day=1)
            self._start = self._month
            self._end   = last_prev
        # "custom" keeps current start/end
        self._active_preset = preset
        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._load_data()
        self._flush_ui()

    def _rebuild_preset_row(self) -> None:
        runtime = get_active_theme_runtime()
        chips = []
        for key, label in _PRESETS:
            active = self._active_preset == key

            def on_click(e, k=key):
                self._set_preset(k)

            chips.append(ft.Container(
                content=ft.Text(
                    label, size=12, weight=ft.FontWeight.W_600,
                    color=ft.Colors.ON_PRIMARY if active else ft.Colors.ON_SURFACE_VARIANT,
                ),
                bgcolor=runtime.accent if active else ft.Colors.SURFACE_CONTAINER,
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=5),
                on_click=on_click,
                ink=not active,
            ))
        self._preset_row.controls = chips

    # ── period control (month nav or date pickers) ────────────────

    def _rebuild_period_ctrl(self) -> None:
        if self._active_preset != "custom":
            self._period_ctrl.content = self._build_month_nav()
        else:
            self._period_ctrl.content = self._build_date_pickers()

    def _build_month_nav(self) -> ft.Control:
        future = last_day_of_month(self._month) >= clock.today()

        def prev_month(e):
            # go back one month
            if self._month.month == 1:
                self._month = self._month.replace(year=self._month.year - 1, month=12)
            else:
                self._month = self._month.replace(month=self._month.month - 1)
            self._start = self._month
            self._end   = min(last_day_of_month(self._month), clock.today())
            self._rebuild_period_ctrl()
            self._load_data()
            self._flush_ui()

        def next_month(e):
            if future:
                return
            if self._month.month == 12:
                self._month = self._month.replace(year=self._month.year + 1, month=1)
            else:
                self._month = self._month.replace(month=self._month.month + 1)
            self._start = self._month
            self._end   = min(last_day_of_month(self._month), clock.today())
            self._rebuild_period_ctrl()
            self._load_data()
            self._flush_ui()

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(ft.Icons.CHEVRON_LEFT, size=22),
                        on_click=prev_month,
                        ink=True, border_radius=RADIUS_SM,
                        padding=ft.padding.all(SPACE_XS),
                    ),
                    ft.Text(
                        fmt_month_year(self._month),
                        size=15, weight=ft.FontWeight.W_700,
                        width=180, text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.CHEVRON_RIGHT, size=22,
                            color=ft.Colors.ON_SURFACE_VARIANT if future else None,
                        ),
                        on_click=next_month,
                        ink=not future,
                        border_radius=RADIUS_SM,
                        padding=ft.padding.all(SPACE_XS),
                        opacity=0.35 if future else 1.0,
                    ),
                ],
                spacing=SPACE_XS,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=260,
        )

    def _build_date_pickers(self) -> ft.Control:
        from_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=14,
                            color=ft.Colors.PRIMARY),
                    ft.Text(fmt_short_date(self._start), size=13,
                            weight=ft.FontWeight.W_600),
                ],
                spacing=SPACE_XS, tight=True,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=lambda e: self._open_picker("start"),
            ink=True,
        )
        to_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=14,
                            color=ft.Colors.PRIMARY),
                    ft.Text(fmt_short_date(self._end), size=13,
                            weight=ft.FontWeight.W_600),
                ],
                spacing=SPACE_XS, tight=True,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=lambda e: self._open_picker("end"),
            ink=True,
        )
        return ft.Row(
            controls=[
                from_btn,
                ft.Text("–", size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                to_btn,
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _open_picker(self, which: str) -> None:
        if which == "start":
            self._dp_start.value = self._start
            self._dp_start.open  = True
            self._dp_start.update()
        else:
            self._dp_end.value = self._end
            self._dp_end.open  = True
            self._dp_end.update()

    def _on_start_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        self._start = min(picker_date(raw), clock.today())
        if self._start > self._end:
            self._end = self._start
        self._rebuild_period_ctrl()
        self._load_data()
        self._flush_ui()

    def _on_end_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        self._end = min(picker_date(raw), clock.today())
        if self._end < self._start:
            self._start = self._end
        self._rebuild_period_ctrl()
        self._load_data()
        self._flush_ui()

    # ── data ──────────────────────────────────────────────────────

    def _load_data(self) -> None:
        with get_session() as session:
            self._data = build_report(session, self._start, self._end)
        self._build_summary_controls()
        self._build_breakdown_controls()
        self._build_cat_controls()
        self._build_day_controls()

    def _build_summary_controls(self) -> None:
        d = self._data
        runtime = get_active_theme_runtime()
        self._summary_row.controls = [
            _scard("საწყისი ნაშთი", f"\u20be{d.opening_balance:.2f}",
                   ft.Icons.HISTORY_TOGGLE_OFF, runtime, width=170),
            _scard("პერიოდის შემოსავალი", f"\u20be{d.summary.cashier_received:.2f}",
                   ft.Icons.PAYMENTS, runtime,
                   note="გაყიდვები + დაბრუნებული ნისია", width=220),
            _scard("გატანები", f"\u20be{d.total_withdrawn:.2f}",
                   ft.Icons.OUTPUT, runtime, danger=True, width=150),
            _scard("ნეტო ცვლილება", f"\u20be{d.net_change:.2f}",
                   ft.Icons.DIFFERENCE, runtime,
                   note="შემოსავალი − გატანები", width=180),
            _scard("საბოლოო ნაშთი", f"\u20be{d.closing_balance:.2f}",
                   ft.Icons.ACCOUNT_BALANCE, runtime, highlight=True, width=180),
            _scard("აქტიური ნისია", str(d.active_credit_count),
                   ft.Icons.ACCOUNT_BALANCE_WALLET, runtime,
                   note=f"\u20be{d.active_credit_amount:.2f}", width=160),
        ]

    def _build_breakdown_controls(self) -> None:
        d = self._data
        self._breakdown_col.controls = [
            _kv_row("გაყიდვა ჯამში", f"{d.summary.total_txns} / \u20be{d.summary.total_revenue:.2f}"),
            _kv_row("მიღებული გაყიდვებიდან", f"\u20be{d.sales_received:.2f}"),
            _kv_row("ახალი ნისია", str(d.summary.new_credit_count)),
            _kv_row("გადახდილი ნისია", f"{d.credit_repaid_count} / \u20be{d.credit_repaid:.2f}"),
            _kv_row("ნაპატიები ნისია", f"{d.forgiven_count} / \u20be{d.forgiven_amount:.2f}"),
            _kv_row("აქტიური ნისიის ნაშთი", f"{d.active_credit_count} / \u20be{d.active_credit_amount:.2f}"),
        ]

    def _build_cat_controls(self) -> None:
        cats = self._data.summary.categories
        runtime = get_active_theme_runtime()
        if not cats:
            self._cat_col.controls = [
                ft.Text("მონაცემი არ არის", size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT)
            ]
            return
        max_rev = max(c.revenue for c in cats) or Decimal("1")
        rows: list[ft.Control] = []
        for cs in cats:
            frac = float(cs.revenue / max_rev)
            rows.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(
                                        _CAT_LABEL.get(cs.category, cs.category.value),
                                        size=12,
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                        expand=True,
                                    ),
                                    ft.Text(
                                        str(cs.qty), size=12, width=36,
                                        text_align=ft.TextAlign.RIGHT,
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                    ),
                                    ft.Text(
                                        f"\u20be{cs.revenue:.2f}", size=12,
                                        weight=ft.FontWeight.W_600, width=82,
                                        text_align=ft.TextAlign.RIGHT,
                                    ),
                                ],
                                spacing=SPACE_SM,
                            ),
                            ft.Stack(
                                controls=[
                                    ft.Container(height=5,
                                                 bgcolor=_with_alpha(runtime.accent, 0.08),
                                                 border_radius=3),
                                    ft.Container(width=max(4, int(250 * frac)), height=5,
                                                 bgcolor=runtime.accent, border_radius=3),
                                ],
                                height=5,
                            ),
                        ],
                        spacing=3,
                        tight=True,
                    ),
                    padding=ft.padding.symmetric(vertical=2),
                )
            )
        self._cat_col.controls = rows

    def _build_day_controls(self) -> None:
        days = self._data.days
        if not days:
            self._day_col.controls = [
                ft.Container(
                    content=ft.Text("ამ პერიოდში ჩანაწერი არ არის", size=13,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                    bgcolor=ft.Colors.SURFACE_CONTAINER,
                    border_radius=RADIUS_MD,
                    padding=ft.padding.all(SPACE_MD),
                )
            ]
            return

        rows: list[ft.Control] = [_cash_flow_header()]
        for ds in days:
            rows.append(_cash_flow_row(ds))
        self._day_col.controls = rows

    # ── export ────────────────────────────────────────────────────

    def _export_csv(self, e) -> None:
        if self._data is None:
            return
        d = self._data

        buf = io.StringIO()
        w   = csv.writer(buf)

        w.writerow(["ანგარიშები"])
        w.writerow([f"{fmt_short_date(d.start)} – {fmt_short_date(d.end)}"])
        w.writerow([])

        w.writerow(["შეჯამება"])
        w.writerow(["საწყისი ნაშთი", f"{d.opening_balance:.2f}"])
        w.writerow(["გაყიდვა ჯამში", f"{d.summary.total_txns} / {d.summary.total_revenue:.2f}"])
        w.writerow(["მიღებული გაყიდვებიდან", f"{d.sales_received:.2f}"])
        w.writerow(["გადახდილი ნისია", f"{d.credit_repaid_count} / {d.credit_repaid:.2f}"])
        w.writerow(["პერიოდის შემოსავალი", f"{d.summary.cashier_received:.2f}"])
        w.writerow(["გატანები", f"{d.total_withdrawn:.2f}"])
        w.writerow(["ნეტო ცვლილება", f"{d.net_change:.2f}"])
        w.writerow(["საბოლოო ნაშთი", f"{d.closing_balance:.2f}"])
        w.writerow(["აქტიური ნისია", f"{d.active_credit_count} / {d.active_credit_amount:.2f}"])
        w.writerow([])

        w.writerow(["კატეგორიები"])
        w.writerow(["კატეგორია", "რაოდ.", "შემოსავალი"])
        for cs in d.summary.categories:
            w.writerow([
                _CAT_LABEL.get(cs.category, cs.category.value),
                cs.qty,
                f"{cs.revenue:.2f}",
            ])
        w.writerow([])

        w.writerow(["სალაროს მოძრაობა"])
        w.writerow([
            "თარიღი", "საწყისი ნაშთი", "გაყიდვებიდან მიღებული",
            "დაბრუნებული ნისია", "შემოსავალი", "გატანა",
            "ნეტო ცვლილება", "საბოლოო ნაშთი", "გაყიდვა ჯამში",
            "ახალი ნისია",
        ])
        for ds in d.days:
            w.writerow([
                fmt_short_date(ds.date),
                f"{ds.opening_balance:.2f}",
                f"{ds.sales_received:.2f}",
                f"{ds.credit_repaid:.2f}",
                f"{ds.income:.2f}",
                f"{ds.withdrawn:.2f}",
                f"{ds.net_change:.2f}",
                f"{ds.closing_balance:.2f}",
                f"{ds.txn_count} / {ds.sales_total:.2f}",
                ds.new_credit_count,
            ])

        content  = buf.getvalue()
        filename = f"kodak_{d.start}_{d.end}.csv"
        path     = Path.home() / "Downloads" / filename
        path.write_text(content, encoding="utf-8-sig")

        # open in default app (Numbers / Excel)
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            elif system == "Windows":
                import os
                os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            pass

        self._export_label.value = f"✓  {filename}"
        if self._mounted:
            self._export_label.update()

    # ── UI flush ──────────────────────────────────────────────────

    def _flush_ui(self) -> None:
        if not self._mounted:
            return
        self._preset_row.update()
        self._period_ctrl.update()
        self._summary_row.update()
        self._breakdown_col.update()
        self._cat_col.update()
        self._day_col.update()


# ── helpers ───────────────────────────────────────────────────────────────────

def _scard(
    label: str,
    value: str,
    icon: str,
    runtime,
    *,
    note: str | None = None,
    highlight: bool = False,
    danger: bool = False,
    width: int = 170,
) -> ft.Container:
    color = "#D32F2F" if danger else runtime.accent
    value_color = runtime.accent if highlight else ft.Colors.ERROR if danger else None
    text_controls: list[ft.Control] = [
        ft.Text(value, size=16, weight=ft.FontWeight.W_700, color=value_color),
        ft.Text(label, size=10, color=runtime.muted_text, max_lines=2),
    ]
    if note:
        text_controls.append(
            ft.Text(note, size=8, color=runtime.muted_text,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        )
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(
                    content=ft.Icon(icon, size=14, color=color),
                    bgcolor=_with_alpha(color, 0.10),
                    border_radius=9,
                    padding=ft.padding.all(SPACE_XS + 2),
                ),
                ft.Column(text_controls, spacing=1, tight=True, expand=True),
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=_with_alpha(runtime.accent, 0.08) if highlight else runtime.panel_bg,
        border=ft.border.all(1, runtime.accent if highlight else runtime.panel_border),
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
        width=width,
        height=66,
    )


def _kv_row(label: str, value: str) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Text(label, size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                ft.Text(value, size=12, weight=ft.FontWeight.W_700,
                        text_align=ft.TextAlign.RIGHT),
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
    )


def _cash_flow_header() -> ft.Container:
    return ft.Container(
        content=ft.Row(
            controls=[
                _cell("თარიღი", 120, header=True, align=ft.TextAlign.LEFT),
                _cell("საწყისი", 92, header=True),
                _cell("გაყიდვ.", 92, header=True),
                _cell("ნისია", 82, header=True),
                _cell("შემოს.", 92, header=True),
                _cell("გატანა", 82, header=True),
                _cell("ნეტო", 82, header=True),
                _cell("ნაშთი", 112, header=True),
            ],
            spacing=SPACE_XS,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_XS),
    )


def _cash_flow_row(ds) -> ft.Container:
    runtime = get_active_theme_runtime()
    net_color = ft.Colors.ERROR if ds.net_change < 0 else runtime.accent
    return ft.Container(
        content=ft.Row(
            controls=[
                _cell(fmt_short_date(ds.date), 120, align=ft.TextAlign.LEFT,
                      color=ft.Colors.ON_SURFACE_VARIANT),
                _cell(_money(ds.opening_balance), 92),
                _cell(_money(ds.sales_received), 92),
                _cell(_money(ds.credit_repaid), 82),
                _cell(_money(ds.income), 92, weight=ft.FontWeight.W_700),
                _cell(_money(ds.withdrawn), 82,
                      color=ft.Colors.ERROR if ds.withdrawn else ft.Colors.ON_SURFACE_VARIANT),
                _cell(_money(ds.net_change), 82, color=net_color,
                      weight=ft.FontWeight.W_700),
                _cell(_money(ds.closing_balance), 112,
                      weight=ft.FontWeight.W_700),
            ],
            spacing=SPACE_XS,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=_with_alpha(runtime.accent, 0.04),
        border=ft.border.all(1, runtime.panel_border),
        border_radius=RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_SM),
    )


def _cell(
    text: str,
    width: int,
    *,
    header: bool = False,
    align: ft.TextAlign = ft.TextAlign.RIGHT,
    color=None,
    weight=None,
) -> ft.Text:
    return ft.Text(
        text,
        size=11 if header else 12,
        width=width,
        color=color or ft.Colors.ON_SURFACE_VARIANT if header else color,
        weight=ft.FontWeight.W_700 if header else weight,
        text_align=align,
        no_wrap=True,
        overflow=ft.TextOverflow.ELLIPSIS,
    )


def _money(value: Decimal) -> str:
    return f"\u20be{value:.2f}"


def _with_alpha(color: str, alpha: float) -> str:
    raw = color.lstrip("#")
    pct = max(0, min(255, round(alpha * 255)))
    return f"#{pct:02X}{raw.upper()}"
