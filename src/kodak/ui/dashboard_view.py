"""Dashboards tab — period KPIs plus visual bar reports."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import flet as ft

from kodak.db import get_session
from kodak.models.enums import ProductCategory
from kodak.models.user import User
from kodak.services.dashboard import DashboardData, build_dashboard
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

_PRESETS = [
    ("week", "ეს კვირა"),
    ("month", "ეს თვე"),
    ("last_month", "გასული თვე"),
    ("custom", "↕ პერიოდი"),
]

_CAT_LABEL: dict[ProductCategory, str] = {
    ProductCategory.photo: "ფოტო",
    ProductCategory.enlargement: "გადიდება",
    ProductCategory.frame: "ჩარჩო",
    ProductCategory.lamination: "ლამინირება",
    ProductCategory.cd: "CD",
    ProductCategory.photocopy: "ქსეროქსი",
    ProductCategory.album: "ალბომი",
    ProductCategory.other: "სხვა",
}


class DashboardView:
    def __init__(self, page: ft.Page, user: User) -> None:
        self._page = page
        self._user = user
        self._mounted = False
        self._root: ft.Column | None = None
        self._data: DashboardData | None = None

        today = dt.date.today()
        self._active_preset = "week"
        self._month = today.replace(day=1)
        self._start, self._end = _current_week(today)

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

        self._preset_row = ft.Row(spacing=SPACE_XS, wrap=True)
        self._period_ctrl = ft.Container()
        self._summary_row = ft.Row(spacing=SPACE_SM, wrap=True)
        self._products_col = ft.Column(spacing=SPACE_SM, tight=True)
        self._categories_col = ft.Column(spacing=SPACE_SM, tight=True)
        self._daily_col = ft.Column(spacing=SPACE_SM, tight=True)

        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._load_data()

    def build(self) -> ft.Control:
        if self._root is None:
            self._root = ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=SPACE_MD,
            )
        self._refresh_layout()
        self._mounted = True
        return self._root

    def _refresh_layout(self) -> None:
        runtime = get_active_theme_runtime()
        assert self._root is not None
        self._root.controls = [
            ft.Text("დეშბორდები", size=28, weight=ft.FontWeight.W_700),
            ft.Text(
                "აირჩიეთ პერიოდი და ნახეთ სწრაფი ვიზუალური ჭრილი: ტოპ პროდუქტები, კატეგორიები და დღიური დინამიკა.",
                size=13,
                color=runtime.muted_text,
            ),
            self._section_card(
                "პერიოდი",
                [
                    self._preset_row,
                    self._period_ctrl,
                    ft.Container(height=SPACE_XS),
                    self._summary_row,
                ],
            ),
            ft.ResponsiveRow(
                controls=[
                    ft.Container(
                        content=self._section_card(
                            "ყველაზე გაყიდვადი პროდუქტები",
                            [self._products_col],
                        ),
                        col={"sm": 12, "md": 6},
                    ),
                    ft.Container(
                        content=self._section_card(
                            "კატეგორიების შემოსავალი",
                            [self._categories_col],
                        ),
                        col={"sm": 12, "md": 6},
                    ),
                ],
                columns=12,
                spacing=SPACE_MD,
                run_spacing=SPACE_MD,
            ),
            self._section_card(
                "დღიური დინამიკა",
                [self._daily_col],
            ),
        ]

    def _set_preset(self, preset: str) -> None:
        today = dt.date.today()
        if preset == "week":
            self._start, self._end = _current_week(today)
        elif preset == "month":
            self._month = today.replace(day=1)
            self._start = self._month
            self._end = today
        elif preset == "last_month":
            first_this = today.replace(day=1)
            last_prev = first_this - dt.timedelta(days=1)
            self._month = last_prev.replace(day=1)
            self._start = self._month
            self._end = last_prev
        self._active_preset = preset
        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._load_data()
        self._refresh_view()

    def _rebuild_preset_row(self) -> None:
        runtime = get_active_theme_runtime()
        self._preset_row.controls = []
        for key, label in _PRESETS:
            active = self._active_preset == key

            def on_click(e, preset_id=key):
                self._set_preset(preset_id)

            self._preset_row.controls.append(
                ft.Container(
                    content=ft.Text(
                        label,
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.WHITE if active else runtime.muted_text,
                    ),
                    bgcolor=runtime.accent if active else _with_alpha(runtime.accent, 0.08),
                    border=ft.border.all(
                        1,
                        runtime.accent if active else _with_alpha(runtime.accent, 0.18),
                    ),
                    border_radius=RADIUS_SM,
                    padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=5),
                    on_click=on_click,
                    ink=not active,
                )
            )

    def _rebuild_period_ctrl(self) -> None:
        if self._active_preset == "custom":
            self._period_ctrl.content = self._build_date_pickers()
        else:
            self._period_ctrl.content = self._build_period_label()

    def _build_period_label(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_MONTH_OUTLINED, size=16, color=runtime.accent),
                    ft.Text(
                        f"{fmt_short_date(self._start)} – {fmt_short_date(self._end)}",
                        size=13,
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                spacing=SPACE_XS,
                tight=True,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
        )

    def _build_date_pickers(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        from_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=14, color=runtime.accent),
                    ft.Text(fmt_short_date(self._start), size=13, weight=ft.FontWeight.W_600),
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
                    ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=14, color=runtime.accent),
                    ft.Text(fmt_short_date(self._end), size=13, weight=ft.FontWeight.W_600),
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
        return ft.Row(
            controls=[
                from_btn,
                ft.Text("–", size=16, color=runtime.muted_text),
                to_btn,
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

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
        self._active_preset = "custom"
        self._start = min(picker_date(raw), dt.date.today())
        if self._start > self._end:
            self._end = self._start
        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._load_data()
        self._refresh_view()

    def _on_end_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        self._active_preset = "custom"
        self._end = min(picker_date(raw), dt.date.today())
        if self._end < self._start:
            self._start = self._end
        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._load_data()
        self._refresh_view()

    def _load_data(self) -> None:
        with get_session() as session:
            self._data = build_dashboard(session, self._start, self._end)
        self._build_summary_controls()
        self._build_products_controls()
        self._build_categories_controls()
        self._build_daily_controls()

    def _build_summary_controls(self) -> None:
        runtime = get_active_theme_runtime()
        assert self._data is not None
        self._summary_row.controls = [
            _summary_card("გაყიდვები", str(self._data.total_txns), ft.Icons.RECEIPT_LONG, runtime.accent),
            _summary_card("შემოსავალი", f"\u20be{self._data.total_revenue:.2f}", ft.Icons.PAYMENTS, runtime.accent),
            _summary_card("საშ. ჩეკი", f"\u20be{self._data.avg_ticket:.2f}", ft.Icons.SHOPPING_BAG_OUTLINED, ft.Colors.PRIMARY),
            _summary_card("აქტიური დღეები", str(self._data.active_days), ft.Icons.CALENDAR_VIEW_WEEK_OUTLINED, runtime.muted_text),
        ]

    def _build_products_controls(self) -> None:
        runtime = get_active_theme_runtime()
        assert self._data is not None
        if not self._data.top_products:
            self._products_col.controls = [_empty_state("ამ პერიოდში გაყიდვები არ არის.")]
            return

        max_qty = max(item.qty for item in self._data.top_products) or 1
        leader = self._data.top_products[0]
        self._products_col.controls = [
            ft.Text(
                f"ლიდერი: {leader.label}  •  {leader.qty} ც",
                size=12,
                color=runtime.muted_text,
            ),
            *[
                _metric_bar_row(
                    label=item.label,
                    primary=f"{item.qty} ც",
                    secondary=f"\u20be{item.revenue:.2f}",
                    fraction=item.qty / max_qty,
                    color=runtime.accent,
                )
                for item in self._data.top_products
            ],
        ]

    def _build_categories_controls(self) -> None:
        runtime = get_active_theme_runtime()
        assert self._data is not None
        if not self._data.category_breakdown:
            self._categories_col.controls = [_empty_state("კატეგორიული მონაცემი არ არის.")]
            return

        max_rev = max(item.revenue for item in self._data.category_breakdown) or Decimal("1")
        self._categories_col.controls = [
            _metric_bar_row(
                label=_CAT_LABEL.get(item.category, item.category.value),
                primary=f"\u20be{item.revenue:.2f}",
                secondary=f"{item.qty} ც",
                fraction=float(item.revenue / max_rev),
                color="#1F7A5C",
            )
            for item in self._data.category_breakdown
        ]

    def _build_daily_controls(self) -> None:
        runtime = get_active_theme_runtime()
        assert self._data is not None
        active_days = [point for point in self._data.daily if point.txn_count > 0]
        if not active_days:
            self._daily_col.controls = [_empty_state("ამ პერიოდში დღიური დინამიკა ცარიელია.")]
            return

        max_rev = max(point.revenue for point in active_days) or Decimal("1")
        rows: list[ft.Control] = []
        for point in self._data.daily:
            rows.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Text(
                                fmt_date(point.date),
                                size=12,
                                width=124,
                                color=runtime.muted_text,
                            ),
                            ft.Container(
                                content=ft.Text(
                                    str(point.txn_count),
                                    size=11,
                                    weight=ft.FontWeight.W_700,
                                    color=runtime.accent,
                                ),
                                bgcolor=_with_alpha(runtime.accent, 0.10),
                                border_radius=RADIUS_SM,
                                padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=4),
                                width=40,
                                alignment=ft.Alignment(0, 0),
                            ),
                            ft.Container(
                                content=ft.Stack(
                                    controls=[
                                        ft.Container(
                                            height=10,
                                            bgcolor=_with_alpha(runtime.accent, 0.10),
                                            border_radius=5,
                                        ),
                                        ft.Container(
                                            width=max(
                                                6,
                                                int(220 * float(point.revenue / max_rev)),
                                            ) if point.revenue > 0 else 0,
                                            height=10,
                                            bgcolor=runtime.accent,
                                            border_radius=5,
                                        ),
                                    ],
                                    width=220,
                                    height=10,
                                ),
                                expand=True,
                            ),
                            ft.Text(
                                f"\u20be{point.revenue:.2f}",
                                size=12,
                                width=78,
                                text_align=ft.TextAlign.RIGHT,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Text(
                                f"ჩეკი \u20be{point.avg_ticket:.2f}",
                                size=11,
                                width=84,
                                text_align=ft.TextAlign.RIGHT,
                                color=runtime.muted_text,
                            ),
                        ],
                        spacing=SPACE_SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.symmetric(vertical=2),
                )
            )
        self._daily_col.controls = rows

    def _section_card(self, title: str, controls: list[ft.Control]) -> ft.Control:
        runtime = get_active_theme_runtime()
        return ft.Container(
            content=ft.Column(
                controls=[ft.Text(title, size=18, weight=ft.FontWeight.W_700), *controls],
                spacing=SPACE_SM,
                tight=True,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_LG),
        )

    def _refresh_view(self) -> None:
        if self._root is not None and self._root.page is not None:
            self._refresh_layout()
            self._root.update()


def _current_week(today: dt.date) -> tuple[dt.date, dt.date]:
    start = today - dt.timedelta(days=today.weekday())
    return start, today


def _summary_card(label: str, value: str, icon: str, color: str) -> ft.Control:
    runtime = get_active_theme_runtime()
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(
                    content=ft.Icon(icon, size=18, color=color),
                    bgcolor=_with_alpha(color, 0.10),
                    border_radius=12,
                    padding=ft.padding.all(SPACE_SM),
                ),
                ft.Column(
                    controls=[
                        ft.Text(value, size=22, weight=ft.FontWeight.W_700),
                        ft.Text(label, size=12, color=runtime.muted_text),
                    ],
                    spacing=SPACE_XS,
                    tight=True,
                ),
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=runtime.panel_bg,
        border=ft.border.all(1, runtime.panel_border),
        border_radius=RADIUS_LG,
        padding=ft.padding.all(SPACE_MD),
        width=182,
    )


def _metric_bar_row(
    *,
    label: str,
    primary: str,
    secondary: str,
    fraction: float,
    color: str,
) -> ft.Control:
    runtime = get_active_theme_runtime()
    return ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Text(
                        label,
                        size=12,
                        weight=ft.FontWeight.W_600,
                        expand=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(primary, size=12, weight=ft.FontWeight.W_700),
                    ft.Text(secondary, size=11, color=runtime.muted_text),
                ],
                spacing=SPACE_SM,
            ),
            ft.Stack(
                controls=[
                    ft.Container(
                        height=10,
                        bgcolor=_with_alpha(color, 0.10),
                        border_radius=5,
                    ),
                    ft.Container(
                        width=max(10, int(260 * max(0.0, min(1.0, fraction)))),
                        height=10,
                        bgcolor=color,
                        border_radius=5,
                    ),
                ],
                width=260,
                height=10,
            ),
        ],
        spacing=SPACE_XS,
        tight=True,
    )


def _empty_state(message: str) -> ft.Control:
    runtime = get_active_theme_runtime()
    return ft.Text(message, size=12, color=runtime.muted_text)


def _with_alpha(color: str, alpha: float) -> str:
    raw = color.lstrip("#")
    pct = max(0, min(255, round(alpha * 255)))
    return f"#{pct:02X}{raw.upper()}"
