"""Flet entry point for the Kodak app."""

from __future__ import annotations

import threading
from pathlib import Path

import flet as ft

from kodak.access import AccessMode, get_access_mode, is_read_only, set_access_mode
from kodak.backup import maybe_create_auto_backup, maybe_create_scheduled_backup
from kodak.config import load_config, save_config
from kodak.db import DB_PATH, init_db
from kodak.event_log import log_event
from kodak.models.enums import Role
from kodak.models.user import User
from kodak.session_lock import SessionLock, SessionLockInfo
from kodak.ui.conflict_dialog import build_conflict_dialog
from kodak.ui.login import LoginView
from kodak.ui.shell import AppShell
from kodak.ui.theme import (
    apply_page_theme,
    default_theme_preference,
    load_user_theme_preference,
    resolve_theme_runtime,
)


def main(page: ft.Page) -> None:
    page.title = "გურიაფოტო კოდაკი"
    page.padding = 0
    page.window.width = 1280
    page.window.height = 800
    page.window.min_width = 1024
    page.window.min_height = 700
    # center() is async in Flet 0.84 — skip it; the OS places the window fine
    # page.window.center()
    apply_page_theme(page, resolve_theme_runtime(default_theme_preference()))
    page.clean()
    page.add(
        ft.Container(
            content=ft.Column(
                controls=[
                    ft.ProgressRing(width=28, height=28),
                    ft.Text("აპლიკაცია იტვირთება…", size=14),
                ],
                spacing=16,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            expand=True,
            alignment=ft.Alignment(0, 0),
        )
    )
    page.update()

    session_lock = SessionLock(DB_PATH)
    shutting_down = False
    backup_scheduler_stop = threading.Event()
    backup_scheduler_thread: threading.Thread | None = None
    active_editor_lock: SessionLockInfo | None = None
    forced_takeover_pending = False
    backup_dir_picker = ft.FilePicker()
    page.services.append(backup_dir_picker)

    def destroy_window() -> None:
        page.window.prevent_close = False
        page.window.destroy()

    def start_backup_scheduler() -> None:
        nonlocal backup_scheduler_thread
        if backup_scheduler_thread is not None and backup_scheduler_thread.is_alive():
            return

        def worker() -> None:
            maybe_create_scheduled_backup()
            while not backup_scheduler_stop.wait(60):
                maybe_create_scheduled_backup()

        backup_scheduler_stop.clear()
        backup_scheduler_thread = threading.Thread(
            target=worker,
            name="kodak-backup-scheduler",
            daemon=True,
        )
        backup_scheduler_thread.start()

    async def prompt_backup_dir_if_needed(user: User) -> None:
        if is_read_only():
            return
        if user.role != Role.admin or user.username != "archil":
            return

        cfg = load_config()
        if cfg.get("backup_folder"):
            return

        selected = await backup_dir_picker.get_directory_path(
            dialog_title="აირჩიეთ სარეზერვო ასლების საქაღალდე",
            initial_directory=str(Path.home()),
        )
        if not selected:
            return

        cfg["backup_folder"] = str(Path(selected).expanduser())
        try:
            save_config(cfg)
        except Exception as exc:
            page.show_dialog(
                ft.AlertDialog(
                    modal=True,
                    open=True,
                    title=ft.Text("სარეზერვო საქაღალდე ვერ შეინახა"),
                    content=ft.Text(str(exc)),
                    actions=[ft.FilledButton("OK", on_click=lambda e: page.pop_dialog())],
                )
            )
            return

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                open=True,
                title=ft.Text("სარეზერვო საქაღალდე შეინახა"),
                content=ft.Text(f"ასლები შეინახება აქ: {selected}"),
                actions=[ft.FilledButton("OK", on_click=lambda e: page.pop_dialog())],
            )
        )

    def show_startup_error(message: str) -> None:
        page.clean()
        page.add(
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(ft.Icons.ERROR_OUTLINE, size=40, color=ft.Colors.ERROR),
                        ft.Text("აპლიკაცია ვერ გაეშვა", size=22, weight=ft.FontWeight.W_700),
                        ft.Text(message, size=13, text_align=ft.TextAlign.CENTER),
                        ft.FilledButton("დახურვა", on_click=lambda e: destroy_window()),
                    ],
                    spacing=16,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
                expand=True,
                alignment=ft.Alignment(0, 0),
            )
        )
        page.update()

    def show_login() -> None:
        session_lock.set_kodak_user(None)
        apply_page_theme(page, resolve_theme_runtime(default_theme_preference()))
        page.clean()
        page.add(LoginView(on_login=on_login).build())
        page.update()

    def request_close() -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        log_event("session_close", "ok", get_access_mode().value)
        backup_scheduler_stop.set()
        if backup_scheduler_thread is not None and backup_scheduler_thread.is_alive():
            backup_scheduler_thread.join(timeout=2)
        session_lock.release()
        destroy_window()

    def on_login(user: User) -> None:
        nonlocal forced_takeover_pending
        if forced_takeover_pending and user.role != Role.admin:
            page.show_dialog(
                ft.AlertDialog(
                    modal=True,
                    open=True,
                    title=ft.Text("გადაბარება მხოლოდ ადმინისტრატორს შეუძლია"),
                    content=ft.Text(
                        "ძველი სესიის გადაბარება დაშვებულია მხოლოდ ადმინისტრატორისთვის."
                    ),
                    actions=[ft.FilledButton("დახურვა", on_click=lambda e: request_close())],
                )
            )
            return
        if forced_takeover_pending and user.role == Role.admin:
            forced_takeover_pending = False

        if not is_read_only():
            session_lock.set_kodak_user(user.username)
        apply_page_theme(page, resolve_theme_runtime(load_user_theme_preference(user.id)))
        page.clean()
        page.add(
            AppShell(
                page=page,
                user=user,
                on_logout=show_login,
                on_request_close=request_close,
                access_mode=get_access_mode(),
                editor_lock=active_editor_lock,
            ).build()
        )
        page.update()
        page.run_task(prompt_backup_dir_if_needed, user)

    def finish_startup(
        access_mode: AccessMode = AccessMode.edit,
        *,
        editor_lock: SessionLockInfo | None = None,
    ) -> None:
        nonlocal shutting_down
        nonlocal active_editor_lock
        active_editor_lock = editor_lock
        set_access_mode(access_mode, editor_lock=editor_lock)

        if access_mode == AccessMode.edit:
            try:
                init_db()
            except Exception as exc:
                session_lock.release()
                show_startup_error(str(exc))
                return
        elif not DB_PATH.exists():
            show_startup_error("მონაცემთა ბაზა ვერ მოიძებნა მხოლოდ ნახვის რეჟიმისთვის.")
            return

        def on_window_event(e: ft.WindowEvent) -> None:
            if e.type != ft.WindowEventType.CLOSE or shutting_down:
                return
            request_close()

        page.window.prevent_close = True
        page.window.on_event = on_window_event
        if access_mode == AccessMode.edit:
            session_lock.start_heartbeat()
            start_backup_scheduler()
            log_event("session_acquire", "ok", str(DB_PATH))
        else:
            log_event("session_read_only", "ok", _describe_editor_lock(editor_lock))
        show_login()

    def prompt_conflict() -> None:
        try:
            outcome = session_lock.acquire()
        except Exception as exc:
            show_startup_error(str(exc))
            return
        if outcome.acquired:
            finish_startup(AccessMode.edit)
            return

        def on_cancel(e: ft.ControlEvent) -> None:
            page.pop_dialog()
            destroy_window()

        def on_open_read_only(e: ft.ControlEvent) -> None:
            page.pop_dialog()
            finish_startup(AccessMode.read_only, editor_lock=outcome.conflict)

        def on_retry(e: ft.ControlEvent) -> None:
            page.pop_dialog()
            prompt_conflict()

        def on_force_open(e: ft.ControlEvent) -> None:
            nonlocal forced_takeover_pending
            page.pop_dialog()
            maybe_create_auto_backup()
            try:
                forced = session_lock.acquire(force=True)
            except Exception as exc:
                show_startup_error(str(exc))
                return
            if forced.acquired:
                log_event("session_stale_takeover", "ok", _describe_editor_lock(outcome.conflict))
                forced_takeover_pending = True
                finish_startup(AccessMode.edit)
                return
            if forced.conflict is not None:
                page.show_dialog(
                    build_conflict_dialog(
                        forced.conflict,
                        on_cancel=on_cancel,
                        on_open_read_only=lambda e: (
                            page.pop_dialog(),
                            finish_startup(AccessMode.read_only, editor_lock=forced.conflict),
                        ),
                        on_retry=on_retry,
                        on_force_open=on_force_open,
                    )
                )

        if outcome.conflict is not None:
            page.show_dialog(
                build_conflict_dialog(
                    outcome.conflict,
                    on_cancel=on_cancel,
                    on_open_read_only=on_open_read_only,
                    on_retry=on_retry,
                    on_force_open=on_force_open,
                )
            )

    prompt_conflict()


def run() -> None:
    ft.run(main)


def _describe_editor_lock(info: SessionLockInfo | None) -> str:
    if info is None:
        return ""
    kodak_user = info.kodak_user or "unknown"
    return f"{info.host} / {kodak_user} / heartbeat={info.heartbeat_at}"


if __name__ == "__main__":
    run()
