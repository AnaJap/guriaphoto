"""Small append-only event log for session and safety events."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from kodak.config import _config_dir

EVENT_LOG_PATH = _config_dir() / "event_log.txt"


def log_event(event: str, status: str = "ok", detail: str = "") -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    parts = [now, event, status]
    if detail:
        parts.append(detail.replace("\n", " "))
    line = " | ".join(parts) + "\n"
    try:
        EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with Path(EVENT_LOG_PATH).open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception as exc:
        print(f"Kodak event log write failed: {exc}")
