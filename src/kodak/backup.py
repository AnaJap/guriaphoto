"""Database snapshot helpers for manual and automatic backups."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from kodak.access import require_write_access
from kodak.config import load_config, save_config
from kodak.db import DB_PATH, engine, init_db
from kodak.event_log import log_event

_BACKUP_SUBDIR = "Kodak_Backups"
_BACKUP_LOG = "backup_log.txt"
SCHEDULED_BACKUP_HOURS = (12, 15, 19)


class BackupError(RuntimeError):
    """Raised when a manual backup cannot be completed."""


def backup_storage_dir(cfg: dict[str, Any] | None = None) -> Path | None:
    """Return the concrete folder where backup files are stored."""
    config = cfg or load_config()
    raw = config.get("backup_folder")
    if not raw:
        return None
    return Path(raw).expanduser() / _BACKUP_SUBDIR


def backup_log_path(cfg: dict[str, Any] | None = None) -> Path | None:
    root = backup_storage_dir(cfg)
    return root / _BACKUP_LOG if root is not None else None


def backup_day_dir(root: Path, when: datetime) -> Path:
    """Return ``root/YYYY/MM/YYYY-MM-DD`` for a backup timestamp."""
    return root / f"{when:%Y}" / f"{when:%m}" / f"{when:%Y-%m-%d}"


def snapshot_database_to(destination: Path) -> Path:
    """Create an atomic SQLite snapshot at *destination*."""
    if not DB_PATH.exists():
        raise BackupError("მონაცემთა ბაზა ვერ მოიძებნა.")

    tmp_path: str | None = None
    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{destination.stem}_",
            suffix=".tmp",
            dir=str(destination.parent),
        )
        os.close(fd)

        source = sqlite3.connect(str(DB_PATH))
        target = sqlite3.connect(tmp_path)
        source.backup(target)
        target.commit()
        os.replace(tmp_path, destination)
    except Exception as exc:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
        if tmp_path is not None:
            tmp = Path(tmp_path)
            if tmp.exists():
                tmp.unlink()
        raise BackupError("სარეზერვო ასლის შექმნა ვერ მოხერხდა.") from exc
    else:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
    return destination


def create_manual_backup() -> dict[str, str]:
    require_write_access()
    cfg = load_config()
    root = backup_storage_dir(cfg)
    if root is None:
        raise BackupError("ჯერ სარეზერვო საქაღალდე აირჩიეთ.")

    now = datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d_%H-%M")
    try:
        migrate_legacy_backups(cfg)
        snapshot_path = snapshot_database_to(
            backup_day_dir(root, now) / f"kodak_manual_{stamp}.db"
        )
        _atomic_copy(snapshot_path, root / "kodak_latest.db")
        record = {"path": str(snapshot_path), "at": now.isoformat(timespec="seconds")}
        cfg["last_manual_backup"] = record
        save_config(cfg)
        _append_backup_log("manual_backup", "ok", snapshot_path)
        log_event("manual_backup", "ok", str(snapshot_path))
    except BackupError:
        raise
    except Exception as exc:
        _append_backup_log("manual_backup", "error", detail=str(exc), cfg=cfg)
        log_event("manual_backup", "error", str(exc))
        raise BackupError("სარეზერვო ასლის შექმნა ვერ მოხერხდა.") from exc

    return record


def maybe_create_auto_backup() -> dict[str, str] | None:
    """Create one best-effort automatic backup.

    Kept as a shutdown hook compatibility helper. Scheduled backups use
    ``maybe_create_scheduled_backup`` so each configured hour runs once.
    """
    cfg = load_config()
    root = backup_storage_dir(cfg)
    if root is None:
        return None

    now = datetime.now().astimezone()
    try:
        snapshot_path = snapshot_database_to(
            backup_day_dir(root, now) / f"kodak_auto_{now:%Y-%m-%d_%H-%M}.db"
        )
        _atomic_copy(snapshot_path, root / "kodak_latest.db")
        _append_backup_log("auto_backup", "ok", snapshot_path, cfg=cfg)
        log_event("auto_backup", "ok", str(snapshot_path))
    except Exception as exc:
        _append_backup_log("auto_backup", "error", detail=str(exc), cfg=cfg)
        log_event("auto_backup", "error", str(exc))
        print(f"Kodak auto-backup skipped: {exc}")
        return None

    record = {"path": str(snapshot_path), "at": now.isoformat(timespec="seconds")}
    cfg["last_auto_backup"] = record
    try:
        save_config(cfg)
    except Exception as exc:
        print(f"Kodak auto-backup metadata save failed: {exc}")
    return record


def maybe_create_scheduled_backup(now: datetime | None = None) -> dict[str, str] | None:
    """Create the scheduled backup for the current hour, once per day/hour."""
    current = (now or datetime.now().astimezone()).astimezone()
    if current.hour not in SCHEDULED_BACKUP_HOURS:
        return None

    cfg = load_config()
    root = backup_storage_dir(cfg)
    if root is None:
        return None

    slot = f"{current:%Y-%m-%d}_{current.hour:02d}"
    done = cfg.get("scheduled_backup_slots_done")
    done_slots = [str(item) for item in done] if isinstance(done, list) else []
    if slot in done_slots:
        return None

    stamp = current.strftime("%Y-%m-%d_%H-%M")
    try:
        migrate_legacy_backups(cfg)
        snapshot_path = snapshot_database_to(
            backup_day_dir(root, current) / f"kodak_auto_{stamp}.db"
        )
        _atomic_copy(snapshot_path, root / "kodak_latest.db")
    except Exception as exc:
        _append_backup_log("scheduled_backup", "error", detail=str(exc), cfg=cfg)
        print(f"Kodak scheduled backup skipped: {exc}")
        return None

    record = {"path": str(snapshot_path), "at": current.isoformat(timespec="seconds")}
    cfg["last_auto_backup"] = record
    cfg["scheduled_backup_slots_done"] = [
        item for item in done_slots if not item < f"{current:%Y-%m-%d}_00"
    ][-30:] + [slot]
    try:
        save_config(cfg)
    except Exception as exc:
        _append_backup_log("scheduled_backup", "metadata_error", snapshot_path, str(exc), cfg=cfg)
        print(f"Kodak scheduled backup metadata save failed: {exc}")

    _append_backup_log("scheduled_backup", "ok", snapshot_path, cfg=cfg)
    log_event("scheduled_backup", "ok", str(snapshot_path))
    return record


def clean_backups_between(start: date, end: date) -> dict[str, Any]:
    """Delete partitioned backup DB files whose backup date is in range."""
    require_write_access()
    if end < start:
        raise BackupError("დასრულების თარიღი დაწყების თარიღზე ადრეა.")

    cfg = load_config()
    root = backup_storage_dir(cfg)
    if root is None:
        raise BackupError("ჯერ სარეზერვო საქაღალდე აირჩიეთ.")
    if not root.exists():
        return {"deleted": 0, "bytes": 0, "errors": []}

    deleted, deleted_bytes, errors = _delete_backup_files(
        root,
        [
            path
            for path in _partitioned_backup_files(root)
            if (backup_date := _date_from_partitioned_backup_path(root, path)) is not None
            and start <= backup_date <= end
        ],
        event="cleanup_delete",
        cfg=cfg,
    )

    _remove_empty_backup_dirs(root)
    _append_backup_log(
        "cleanup",
        "ok" if not errors else "partial",
        detail=f"{start.isoformat()}..{end.isoformat()} deleted={deleted}",
        cfg=cfg,
    )
    log_event("backup_cleanup", "ok" if not errors else "partial", f"{start}..{end} deleted={deleted}")
    return {"deleted": deleted, "bytes": deleted_bytes, "errors": errors}


def keep_latest_backups(limit: int) -> dict[str, Any]:
    """Keep only the newest ``limit`` partitioned backup DB files."""
    require_write_access()
    if limit < 1:
        raise BackupError("რაოდენობა უნდა იყოს მინიმუმ 1.")

    cfg = load_config()
    root = backup_storage_dir(cfg)
    if root is None:
        raise BackupError("ჯერ სარეზერვო საქაღალდე აირჩიეთ.")
    if not root.exists():
        return {"deleted": 0, "bytes": 0, "errors": []}

    backups = sorted(
        _partitioned_backup_files(root),
        key=lambda path: (_date_from_partitioned_backup_path(root, path) or date.min, path.name),
        reverse=True,
    )
    to_delete = backups[limit:]
    deleted, deleted_bytes, errors = _delete_backup_files(
        root,
        to_delete,
        event="keep_latest_delete",
        cfg=cfg,
    )

    _remove_empty_backup_dirs(root)
    _append_backup_log(
        "keep_latest",
        "ok" if not errors else "partial",
        detail=f"limit={limit} deleted={deleted}",
        cfg=cfg,
    )
    log_event("backup_keep_latest", "ok" if not errors else "partial", f"limit={limit} deleted={deleted}")
    return {"deleted": deleted, "bytes": deleted_bytes, "errors": errors}


def keep_backups_for_recent_months(months: int, today: date | None = None) -> dict[str, Any]:
    """Keep backups from the current month and the previous ``months - 1`` months."""
    require_write_access()
    if months < 1:
        raise BackupError("თვეების რაოდენობა უნდა იყოს მინიმუმ 1.")

    cfg = load_config()
    root = backup_storage_dir(cfg)
    if root is None:
        raise BackupError("ჯერ სარეზერვო საქაღალდე აირჩიეთ.")
    if not root.exists():
        return {"deleted": 0, "bytes": 0, "errors": []}

    cutoff = _month_start_months_ago(months - 1, today or datetime.now().astimezone().date())
    to_delete = [
        path
        for path in _partitioned_backup_files(root)
        if (backup_date := _date_from_partitioned_backup_path(root, path)) is not None
        and backup_date < cutoff
    ]
    deleted, deleted_bytes, errors = _delete_backup_files(
        root,
        to_delete,
        event="keep_months_delete",
        cfg=cfg,
    )

    _remove_empty_backup_dirs(root)
    _append_backup_log(
        "keep_recent_months",
        "ok" if not errors else "partial",
        detail=f"months={months} cutoff={cutoff.isoformat()} deleted={deleted}",
        cfg=cfg,
    )
    log_event(
        "backup_keep_recent_months",
        "ok" if not errors else "partial",
        f"months={months} cutoff={cutoff.isoformat()} deleted={deleted}",
    )
    return {"deleted": deleted, "bytes": deleted_bytes, "errors": errors}


def _delete_backup_files(
    root: Path,
    paths: list[Path],
    *,
    event: str,
    cfg: dict[str, Any],
) -> tuple[int, int, list[str]]:
    deleted = 0
    deleted_bytes = 0
    errors: list[str] = []
    for path in paths:
        backup_date = _date_from_partitioned_backup_path(root, path)
        if backup_date is None:
            continue
        try:
            size = path.stat().st_size
            path.unlink()
            deleted += 1
            deleted_bytes += size
            _append_backup_log(event, "ok", path, cfg=cfg)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            _append_backup_log(event, "error", path, str(exc), cfg=cfg)

    return deleted, deleted_bytes, errors


def migrate_legacy_backups(cfg: dict[str, Any] | None = None) -> dict[str, int]:
    """Move old flat ``*.db`` backups into the partitioned folder layout."""
    config = cfg or load_config()
    root = backup_storage_dir(config)
    if root is None or not root.exists():
        return {"moved": 0, "skipped": 0}

    moved = 0
    skipped = 0
    for path in root.glob("*.db"):
        if path.name == "kodak_latest.db":
            skipped += 1
            continue
        backup_date = _date_from_backup_filename(path.name)
        if backup_date is None:
            skipped += 1
            continue
        destination = _unique_path(
            root
            / f"{backup_date:%Y}"
            / f"{backup_date:%m}"
            / backup_date.isoformat()
            / path.name
        )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))
            moved += 1
            _append_backup_log("legacy_migrate", "ok", destination, cfg=config)
        except Exception as exc:
            skipped += 1
            _append_backup_log("legacy_migrate", "error", path, str(exc), cfg=config)

    return {"moved": moved, "skipped": skipped}


def restore_database_from(source_path: Path) -> dict[str, str]:
    """Restore the live DB from a selected SQLite backup file.

    A safety snapshot of the current live DB is created first. The selected
    backup is copied into a temp file, atomically swapped into place, and then
    migrated/seeded so the current app version can reopen it safely.
    """
    require_write_access()
    source = Path(source_path).expanduser()
    if not source.exists() or not source.is_file():
        raise BackupError("არჩეული სარეზერვო ფაილი ვერ მოიძებნა.")

    try:
        if source.resolve() == DB_PATH.resolve():
            raise BackupError("არჩეული ფაილი უკვე მიმდინარე მონაცემთა ბაზაა.")
    except OSError:
        pass

    safety_backup = _create_pre_restore_backup()
    tmp_restore: Path | None = None

    try:
        tmp_restore = _clone_sqlite_to_temp(source, DB_PATH.parent, prefix=".restore_")
        engine.dispose()
        os.replace(tmp_restore, DB_PATH)
        init_db()
    except BackupError:
        raise
    except Exception as exc:
        if tmp_restore is not None and tmp_restore.exists():
            tmp_restore.unlink()
        raise BackupError("აღდგენა ვერ მოხერხდა.") from exc

    result = {
        "restored_from": str(source),
        "safety_backup": str(safety_backup),
    }
    _append_backup_log(
        "restore",
        "ok",
        source,
        detail=f"pre_restore={safety_backup}",
    )
    log_event("restore", "ok", f"from={source} pre_restore={safety_backup}")
    return result


def _atomic_copy(source: Path, destination: Path) -> None:
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{destination.stem}_",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, destination)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def _create_pre_restore_backup() -> Path:
    now = datetime.now().astimezone()
    filename = f"kodak_pre_restore_{now:%Y-%m-%d_%H-%M-%S}.db"
    cfg = load_config()

    candidates: list[Path] = []
    configured_root = backup_storage_dir(cfg)
    if configured_root is not None:
        candidates.append(backup_day_dir(configured_root, now))
    candidates.append(DB_PATH.parent)

    last_error: Exception | None = None
    for root in candidates:
        try:
            return snapshot_database_to(root / filename)
        except Exception as exc:
            last_error = exc

    raise BackupError("აღდგენამდე უსაფრთხო ასლის შექმნა ვერ მოხერხდა.") from last_error


def _clone_sqlite_to_temp(source_path: Path, target_dir: Path, *, prefix: str) -> Path:
    tmp_path: str | None = None
    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=prefix, suffix=".db", dir=str(target_dir))
        os.close(fd)

        source = sqlite3.connect(str(source_path))
        target = sqlite3.connect(tmp_path)
        source.backup(target)
        target.commit()
        return Path(tmp_path)
    except Exception as exc:
        if tmp_path is not None:
            tmp = Path(tmp_path)
            if tmp.exists():
                tmp.unlink()
        raise BackupError("არჩეული სარეზერვო ფაილის წაკითხვა ვერ მოხერხდა.") from exc
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()


def _append_backup_log(
    event: str,
    status: str,
    path: Path | None = None,
    detail: str = "",
    *,
    cfg: dict[str, Any] | None = None,
) -> None:
    log_path = backup_log_path(cfg)
    if log_path is None:
        return

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    parts = [now, event, status]
    if path is not None:
        parts.append(str(path))
    if detail:
        parts.append(detail.replace("\n", " "))
    line = " | ".join(parts) + "\n"

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception as exc:
        print(f"Kodak backup log write failed: {exc}")


def _date_from_partitioned_backup_path(root: Path, path: Path) -> date | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 4:
        return None
    try:
        return date.fromisoformat(parts[2])
    except ValueError:
        return None


def _partitioned_backup_files(root: Path) -> list[Path]:
    return [path for path in root.glob("*/*/*/*.db") if path.is_file()]


def _date_from_backup_filename(filename: str) -> date | None:
    parts = filename.split("_")
    for part in parts:
        try:
            return date.fromisoformat(part[:10])
        except ValueError:
            continue
    return None


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for i in range(1, 1000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise BackupError("სარეზერვო ფაილის უნიკალური სახელის შექმნა ვერ მოხერხდა.")


def _month_start_months_ago(months_ago: int, today: date) -> date:
    month_index = today.year * 12 + (today.month - 1) - months_ago
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _remove_empty_backup_dirs(root: Path) -> None:
    for path in sorted(root.glob("*/*/*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    for path in sorted(root.glob("*/*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    for path in sorted(root.glob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
