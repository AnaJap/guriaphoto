"""Modal dialog shown when another Kodak session is already active."""

from __future__ import annotations

from typing import Callable

import flet as ft

from kodak.session_lock import SessionLockInfo, describe_heartbeat_age, is_stale_lock
from kodak.ui.theme import RADIUS_MD, SPACE_MD, SPACE_SM, SPACE_XS


def build_conflict_dialog(
    info: SessionLockInfo,
    *,
    on_cancel: Callable[[ft.ControlEvent], None],
    on_open_read_only: Callable[[ft.ControlEvent], None],
    on_retry: Callable[[ft.ControlEvent], None],
    on_force_open: Callable[[ft.ControlEvent], None],
) -> ft.AlertDialog:
    kodak_user = info.kodak_user or "უცნობი მომხმარებელი"
    stale = is_stale_lock(info)
    body = (
        f"ბაზა გახსნილია {info.host}-ზე ({kodak_user}), "
        f"{describe_heartbeat_age(info.heartbeat_at)} წინ. "
        "რედაქტირება ერთდროულად მხოლოდ ერთ კომპიუტერზეა დაშვებული."
    )

    return ft.AlertDialog(
        modal=True,
        open=True,
        title=ft.Text("სესია უკვე გახსნილია", weight=ft.FontWeight.W_700),
        content=ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(body, size=14),
                    ft.Container(height=SPACE_XS),
                    ft.Text(
                        f"კომპიუტერი: {info.host}",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.Text(
                        f"სისტემური მომხმარებელი: {info.system_user}",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.Text(
                        "შეგიძლიათ გახსნათ მხოლოდ ნახვის რეჟიმში. ცვლილებების შეტანა "
                        "გამორთული იქნება.",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                ],
                spacing=SPACE_SM,
                tight=True,
            ),
            width=420,
        ),
        actions_alignment=ft.MainAxisAlignment.END,
        action_button_padding=ft.padding.symmetric(horizontal=SPACE_XS),
        shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
        actions=[
            ft.TextButton("გაუქმება", on_click=on_cancel),
            ft.TextButton("ხელახლა ცდა", on_click=on_retry),
            ft.FilledButton("მხოლოდ ნახვა", on_click=on_open_read_only),
            *(
                [
                    ft.FilledButton(
                        "ძველი სესიის გადაბარება",
                        on_click=on_force_open,
                        style=ft.ButtonStyle(
                            bgcolor=ft.Colors.ERROR_CONTAINER,
                            color=ft.Colors.ON_ERROR_CONTAINER,
                            padding=ft.padding.symmetric(
                                horizontal=SPACE_MD,
                                vertical=SPACE_SM,
                            ),
                        ),
                    )
                ]
                if stale
                else []
            ),
        ],
    )
