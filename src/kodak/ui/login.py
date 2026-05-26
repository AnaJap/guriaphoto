"""Login screen — user picker + 4-digit PIN pad."""

from __future__ import annotations

from typing import Callable

import flet as ft
from sqlmodel import select

from kodak.db import get_session
from kodak.models.enums import Role
from kodak.models.user import User
from kodak.services.auth import verify_pin
from kodak.ui.theme import (
    RADIUS_LG,
    RADIUS_MD,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    get_active_theme_runtime,
)

_PIN_LENGTH = 4
_PAD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "✓"]

# Per-user avatar: (emoji, background hex).
# Falls back to initials + primary color for unknown usernames.
_AVATARS: dict[str, tuple[str, str]] = {
    "archil":  ("📸", "#5D4037"),   # the boss with a camera
    "mamuka":  ("🎞️",  "#1565C0"),  # the film-roll guy
    "khatuna": ("🌸",  "#880E4F"),  # blossom
}

# Kodak brand red/yellow used only in the logo widget
_KODAK_RED    = "#ED1C24"
_KODAK_YELLOW = "#F5A623"


class LoginView:
    """User picker + PIN pad. Calls on_login(user) on successful authentication."""

    def __init__(self, on_login: Callable[[User], None]) -> None:
        self._on_login = on_login
        self._selected: User | None = None
        self._pin: list[str] = []

        with get_session() as session:
            self._users = list(
                session.exec(select(User).where(User.active == True).order_by(User.id)).all()
            )

        self._error_text    = ft.Text("", color=ft.Colors.ERROR, size=13)
        self._dot_row       = ft.Row(spacing=SPACE_MD, alignment=ft.MainAxisAlignment.CENTER)
        self._selected_label = ft.Text("", size=18, weight=ft.FontWeight.W_600)
        self._pin_section   = ft.Column(
            visible=False,
            spacing=SPACE_MD,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._user_row = ft.Row(
            spacing=SPACE_LG,
            wrap=True,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        self._build_user_cards()
        self._build_pin_section()

    # ------------------------------------------------------------------ public

    def build(self) -> ft.Control:
        runtime = get_active_theme_runtime()

        panel = ft.Container(
            content=ft.Column(
                controls=[
                    _kodak_logo(),
                    ft.Container(height=SPACE_SM),
                    ft.Text(
                        "აირჩიეთ სახელი შესასვლელად",
                        size=15,
                        color=runtime.muted_text,
                    ),
                    ft.Container(height=SPACE_LG),
                    self._user_row,
                    ft.Container(height=SPACE_SM),
                    self._pin_section,
                ],
                spacing=SPACE_SM,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            border_radius=24,
            padding=ft.padding.symmetric(horizontal=SPACE_LG * 2, vertical=SPACE_LG * 2),
            width=760,
            shadow=ft.BoxShadow(
                blur_radius=32,
                spread_radius=0,
                color="#24160A1A",
                offset=ft.Offset(0, 16),
            ),
        )

        scrollable_panel = ft.Column(
            controls=[
                ft.Container(
                    content=panel,
                    alignment=ft.Alignment(0, 0),
                    padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_LG),
                )
            ],
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Stack(
            controls=[
                ft.Container(
                    width=380,
                    height=380,
                    border_radius=190,
                    bgcolor=_with_alpha(runtime.accent, 0.12),
                    left=-40,
                    top=40,
                ),
                ft.Container(
                    width=320,
                    height=320,
                    border_radius=160,
                    bgcolor=_with_alpha(runtime.sidebar_bg, 0.18),
                    right=40,
                    top=110,
                ),
                ft.Container(
                    width=480,
                    height=180,
                    border_radius=90,
                    bgcolor=_with_alpha(runtime.accent, 0.08),
                    right=120,
                    bottom=30,
                ),
                ft.Container(
                    content=scrollable_panel,
                    alignment=ft.Alignment(0, -0.08),
                    expand=True,
                ),
            ],
            expand=True,
        )

    # --------------------------------------------------------------- builders

    def _build_user_cards(self) -> None:
        self._user_row.controls = [self._make_user_card(u) for u in self._users]

    def _make_user_card(self, user: User) -> ft.Container:
        runtime = get_active_theme_runtime()
        emoji, bg = _AVATARS.get(user.username, (user.full_name[0], "#455A64"))
        is_admin  = user.role == Role.admin
        selected = self._selected is not None and self._selected.id == user.id

        def on_click(e, u=user):
            self._select_user(u)

        # Avatar circle
        circle = ft.Container(
            content=ft.Text(emoji, size=42),
            bgcolor=bg,
            width=96,
            height=96,
            border_radius=48,
            alignment=ft.Alignment(0, 0),
        )

        # Admin gets a small gold star badge in the top-right corner
        if is_admin:
            avatar: ft.Control = ft.Stack(
                controls=[
                    circle,
                    ft.Container(
                        content=ft.Text("★", size=13, color=ft.Colors.WHITE),
                        bgcolor=runtime.accent,
                        width=26,
                        height=26,
                        border_radius=13,
                        alignment=ft.Alignment(0, 0),
                        right=0,
                        top=2,
                    ),
                ],
                width=96,
                height=96,
            )
        else:
            avatar = circle

        return ft.Container(
            content=ft.Column(
                controls=[
                    avatar,
                    ft.Text(
                        user.full_name,
                        size=15,
                        weight=ft.FontWeight.W_600,
                        color=None if selected else runtime.muted_text,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=SPACE_MD,
                tight=True,
            ),
            padding=ft.padding.all(SPACE_LG),
            border_radius=RADIUS_LG,
            bgcolor=runtime.sidebar_active_bg if selected else runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border if not selected else runtime.accent),
            shadow=ft.BoxShadow(
                blur_radius=18 if selected else 0,
                spread_radius=0,
                color=_with_alpha(runtime.accent, 0.18),
                offset=ft.Offset(0, 10),
            ),
            on_click=on_click,
            ink=True,
            width=180,
        )

    def _make_pad_btn(self, key: str) -> ft.Container:
        runtime = get_active_theme_runtime()
        if key == "⌫":
            inner: ft.Control = ft.Icon(ft.Icons.BACKSPACE_OUTLINED, size=22)
        elif key == "✓":
            inner = ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=22, color=runtime.accent)
        else:
            inner = ft.Text(key, size=22, weight=ft.FontWeight.W_600)

        def on_click(e, k=key):
            if k == "⌫":
                self._on_backspace(e)
            elif k == "✓":
                self._on_submit(e)
            else:
                self._on_digit(k)

        return ft.Container(
            content=inner,
            width=80,
            height=64,
            border_radius=RADIUS_MD,
            alignment=ft.Alignment(0, 0),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            on_click=on_click,
            ink=True,
        )

    def _build_pin_section(self) -> None:
        pad_buttons = [self._make_pad_btn(key) for key in _PAD_KEYS]

        pad_grid = ft.Column(
            controls=[
                ft.Row(pad_buttons[0:3], alignment=ft.MainAxisAlignment.CENTER, spacing=SPACE_XS),
                ft.Row(pad_buttons[3:6], alignment=ft.MainAxisAlignment.CENTER, spacing=SPACE_XS),
                ft.Row(pad_buttons[6:9], alignment=ft.MainAxisAlignment.CENTER, spacing=SPACE_XS),
                ft.Row(pad_buttons[9:12], alignment=ft.MainAxisAlignment.CENTER, spacing=SPACE_XS),
            ],
            spacing=SPACE_XS,
        )

        self._pin_section.controls = [
            self._selected_label,
            ft.Text(
                "შეიყვანეთ PIN",
                size=13,
                color=get_active_theme_runtime().muted_text,
            ),
            self._dot_row,
            pad_grid,
            self._error_text,
        ]

    # ----------------------------------------------------------------- events

    def _select_user(self, user: User) -> None:
        self._selected = user
        self._pin = []
        self._error_text.value = ""
        self._selected_label.value = user.full_name
        self._build_user_cards()
        self._pin_section.visible = True
        self._refresh_dots()
        self._user_row.update()
        self._pin_section.update()

    def _on_digit(self, digit: str) -> None:
        if len(self._pin) >= _PIN_LENGTH:
            return
        self._pin.append(digit)
        self._error_text.value = ""
        self._refresh_dots()
        self._dot_row.update()
        self._error_text.update()
        if len(self._pin) == _PIN_LENGTH:
            self._submit()

    def _on_backspace(self, e) -> None:
        if self._pin:
            self._pin.pop()
            self._refresh_dots()
            self._dot_row.update()

    def _on_submit(self, e) -> None:
        self._submit()

    def _submit(self) -> None:
        if not self._selected or not self._pin:
            return
        pin_str = "".join(self._pin)
        with get_session() as session:
            user = verify_pin(session, self._selected.username, pin_str)
        if user:
            self._on_login(user)
        else:
            self._pin = []
            self._error_text.value = "არასწორი PIN — სცადეთ თავიდან"
            self._refresh_dots()
            self._dot_row.update()
            self._error_text.update()

    def _refresh_dots(self) -> None:
        runtime = get_active_theme_runtime()
        self._dot_row.controls = [
            ft.Container(
                width=14, height=14, border_radius=7,
                bgcolor=runtime.accent if i < len(self._pin)
                        else runtime.panel_border,
            )
            for i in range(_PIN_LENGTH)
        ]


# ─────────────────────────────────────── Kodak logo widget

def _kodak_logo() -> ft.Control:
    """Kodak-style logo: red K badge + wordmark + Georgian studio name."""
    runtime = get_active_theme_runtime()
    k_badge = ft.Container(
        content=ft.Text(
            "K",
            size=30,
            weight=ft.FontWeight.W_900,
            color=ft.Colors.WHITE,
        ),
        bgcolor=_KODAK_RED,
        width=54,
        height=54,
        border_radius=10,
        alignment=ft.Alignment(0, 0),
        # Yellow bottom stripe — Kodak's signature two-tone
        border=ft.border.only(bottom=ft.BorderSide(6, _KODAK_YELLOW)),
    )

    wordmark = ft.Column(
        controls=[
            ft.Text(
                "KODAK",
                size=28,
                weight=ft.FontWeight.W_900,
                color=_KODAK_RED,
            ),
            ft.Text(
                "გურიაფოტო კოდაკი",
                size=12,
                color=runtime.muted_text,
                weight=ft.FontWeight.W_500,
            ),
        ],
        spacing=0,
        tight=True,
    )

    return ft.Row(
        controls=[k_badge, wordmark],
        spacing=SPACE_MD,
        alignment=ft.MainAxisAlignment.CENTER,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _with_alpha(color: str, alpha: float) -> str:
    raw = color.lstrip("#")
    pct = max(0, min(255, round(alpha * 255)))
    return f"#{pct:02X}{raw.upper()}"
