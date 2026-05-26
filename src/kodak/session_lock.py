"""Best-effort single-session guard for SQLite over synced storage."""

from __future__ import annotations

import getpass
import json
import os
import platform
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

_STALE_AFTER = timedelta(minutes=5)
_HEARTBEAT_EVERY_SECONDS = 60
_VERIFY_AFTER_WRITE_SECONDS = 3


@dataclass(slots=True)
class SessionLockInfo:
    host: str
    system_user: str
    kodak_user: str | None
    mode: str
    pid: int
    started_at: str
    heartbeat_at: str
    lock_id: str


@dataclass(slots=True)
class AcquireResult:
    acquired: bool
    conflict: SessionLockInfo | None = None


class SessionLock:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock_path = Path(f"{db_path}.lock")
        self._info: SessionLockInfo | None = None
        self._write_guard = threading.Lock()
        self._stop_event = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    def acquire(self, *, force: bool = False) -> AcquireResult:
        existing = self._read_lock()
        if existing is not None:
            if self._is_stale(existing):
                print("Kodak: previous session ended uncleanly.")
            elif not force:
                return AcquireResult(acquired=False, conflict=existing)

        info = self._new_info(kodak_user=self._info.kodak_user if self._info else None)
        self._info = info
        self._write_lock(info)

        time.sleep(_VERIFY_AFTER_WRITE_SECONDS)
        current = self._read_lock()
        if current is not None and not self._matches_self(current):
            self._info = None
            return AcquireResult(acquired=False, conflict=current)

        return AcquireResult(acquired=True)

    def start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        if self._info is None:
            raise RuntimeError("Cannot start heartbeat before acquiring the lock.")

        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="kodak-session-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def set_kodak_user(self, username: str | None) -> None:
        if self._info is None:
            return
        self._info = replace(self._info, kodak_user=username)
        try:
            current = self._read_lock()
            if current is None or self._matches_self(current):
                self._write_lock(self._info)
        except Exception as exc:
            print(f"Kodak session lock update failed: {exc}")

    def release(self, before_release: Callable[[], object] | None = None) -> None:
        self._stop_event.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2)
        self._heartbeat_thread = None

        if before_release is not None:
            try:
                before_release()
            except Exception as exc:
                print(f"Kodak shutdown hook failed: {exc}")

        try:
            current = self._read_lock()
            if current is not None and self._matches_self(current) and self._lock_path.exists():
                self._lock_path.unlink()
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"Kodak session lock cleanup failed: {exc}")

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(_HEARTBEAT_EVERY_SECONDS):
            if self._info is None:
                return
            try:
                current = self._read_lock()
                if current is not None and not self._matches_self(current):
                    print("Kodak session lock ownership changed; stopping heartbeat.")
                    return
                self._info = replace(self._info, heartbeat_at=_now_iso())
                self._write_lock(self._info)
            except Exception as exc:
                print(f"Kodak session heartbeat stopped: {exc}")
                return

    def _read_lock(self) -> SessionLockInfo | None:
        return read_session_lock(self._db_path)

    def _write_lock(self, info: SessionLockInfo) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_guard:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".kodak_lock_",
                suffix=".tmp",
                dir=str(self._lock_path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(asdict(info), handle, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self._lock_path)
            except Exception:
                tmp = Path(tmp_path)
                if tmp.exists():
                    tmp.unlink()
                raise

    def _matches_self(self, info: SessionLockInfo) -> bool:
        if self._info is None:
            return False
        return info.lock_id == self._info.lock_id

    def _is_stale(self, info: SessionLockInfo) -> bool:
        return is_stale_lock(info)

    def _new_info(self, *, kodak_user: str | None) -> SessionLockInfo:
        now = _now_iso()
        return SessionLockInfo(
            host=platform.node() or "unknown-host",
            system_user=getpass.getuser(),
            kodak_user=kodak_user,
            mode="edit",
            pid=os.getpid(),
            started_at=now,
            heartbeat_at=now,
            lock_id=str(uuid.uuid4()),
        )


def describe_heartbeat_age(timestamp: str) -> str:
    try:
        then = datetime.fromisoformat(timestamp)
    except ValueError:
        return "უცნობი დროის"
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - then.astimezone(UTC)
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "რამდენიმე წამის"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} წუთის"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} საათის"
    days = hours // 24
    return f"{days} დღის"


def is_stale_lock(info: SessionLockInfo) -> bool:
    try:
        heartbeat = datetime.fromisoformat(info.heartbeat_at)
    except ValueError:
        return True
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    return datetime.now(UTC) - heartbeat.astimezone(UTC) > _STALE_AFTER


def read_session_lock(db_path: Path) -> SessionLockInfo | None:
    lock_path = Path(f"{db_path}.lock")
    if not lock_path.exists():
        return None
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return SessionLockInfo(
            host=str(raw["host"]),
            system_user=str(raw["system_user"]),
            kodak_user=str(raw["kodak_user"]) if raw.get("kodak_user") else None,
            mode=str(raw.get("mode") or "edit"),
            pid=int(raw["pid"]),
            started_at=str(raw["started_at"]),
            heartbeat_at=str(raw["heartbeat_at"]),
            lock_id=str(raw.get("lock_id") or raw["started_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
