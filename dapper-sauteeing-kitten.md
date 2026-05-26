# Plan: macOS packaging + DB-on-Drive + session lock + backup

## Context

The studio uses one PC at a time but on two different machines (the studio Mac and the manager's home Mac). The simplest setup is to **keep the live SQLite DB inside a Google-Drive-synced folder** — both Macs see the same file, so the manager's PC always shows current data without any manual import step.

The risk in that setup is that someone (the dad, by accident) opens the app on the second PC while the studio Mac still has it open. SQLite over a sync layer with two simultaneous writers can corrupt the database. So we add a **session lock** that detects this and warns the second user.

We also need:
- The main app to be a standalone macOS `.app` (no Python install required)
- Manual + automatic **backup** snapshots, because trusting Google Drive for the only copy of the studio's bookkeeping is asking for trouble

---

## Part 1 — DB path config (Settings folder picker)

### `src/kodak/config.py` (NEW)

JSON store at `~/Library/Application Support/Kodak/config.json` (per-machine, never inside the DB or its synced folder so each Mac keeps its own setting):

```json
{
  "db_folder":       "/Users/.../Google Drive/My Drive/Kodak/",
  "backup_folder":   "/Users/.../Google Drive/My Drive/Kodak_Backups/",
  "last_manual_backup": {"path": "...", "at": "..."},
  "last_auto_backup":   {"path": "...", "at": "..."}
}
```

Helpers: `load_config()`, `save_config()` (atomic via `tmp + os.replace`), `_config_dir()`.

### `src/kodak/db.py` (edit)

Path resolution priority:
1. `KODAK_DB_PATH` env var (dev/CI)
2. `config.json["db_folder"] / "kodak.db"`
3. Default: `<config_dir>/kodak.db` (per-machine local fallback so the app boots even before configuration)
4. Dev override: if `<project>/pyproject.toml` exists alongside the source tree, use `<project>/data/kodak.db` so source-checkout runs hit the dev DB.

Engine creation stays at module import time. Changing `db_folder` requires app restart — Settings UI tells the user.

### Settings UI section: "მონაცემთა ბაზის საქაღალდე"

- Read-only label showing the current resolved DB path.
- **[საქაღალდის შეცვლა]** button → `ft.FilePicker.get_directory_path()`.
- After folder picked, inline confirmation card:
  - **დიახ, გადავიტანო** — copy current `kodak.db` to new location, save `db_folder`, show "გადატვირთეთ აპლიკაცია".
  - **არა, ცარიელი ბაზა** — save `db_folder`; new location gets a fresh DB on next start.
  - **გაუქმება** — discard.

---

## Part 2 — Session lock (the critical safety piece)

A small JSON lock file lives next to the DB: `<db_folder>/kodak.db.lock`.

### Lock file contents

```json
{
  "host":         "MacBook-Pro-Anuka",
  "system_user":  "anajaparidze",
  "kodak_user":   "archil",
  "pid":          12345,
  "started_at":   "2026-05-01T10:00:00+04:00",
  "heartbeat_at": "2026-05-01T10:30:15+04:00"
}
```

### Acquire on startup (in `main.py`, before showing login)

1. Read `kodak.db.lock` if present.
2. If absent → write our lock atomically (`tmp + os.replace`), continue.
3. If present:
   - Parse `heartbeat_at`.
   - **Stale** (heartbeat older than 5 min) → silently overwrite, continue. Log to console: "previous session ended uncleanly".
   - **Fresh** → show modal **conflict dialog**:
     - Title: "სესია უკვე გახსნილია"
     - Body: "ბაზა გახსნილია **${host}**-ზე (**${kodak_user}**), ${heartbeat_ago}-ის წინ. ერთდროულად გახსნა შეიძლება გამოიწვიოს მონაცემთა დაკარგვა."
     - Buttons:
       - **[გაუქმება]** — exit the app cleanly without touching the lock.
       - **[მაინც გახსნა]** — overwrite the lock, continue. (User has explicitly accepted the risk.)

### Heartbeat thread (while running)

Daemon thread refreshes `heartbeat_at` every 60 s. On unhandled exception in the heartbeat (file permissions, drive unmounted), the thread logs and exits — startup detection on the next run will then see a stale lock and recover.

### Release on close

`main.py` `on_window_event="close"` handler:
1. Stop the heartbeat thread.
2. Run auto-backup (Part 3) **before** removing the lock so the lock guarantees the backup we save matches the live DB state.
3. Delete `kodak.db.lock`.
4. Let the window close normally.

### Race / Drive-sync caveats (acknowledged, not solved)

- Two PCs starting at *exactly the same second* before either lock has synced may both succeed. Mitigation: re-read the lock 3 s after writing; if `host`/`pid` doesn't match ours, abort. Probability is low for a 2-user studio; this is a best-effort guard, not a distributed consensus system.
- "Heartbeat older than 5 min" is a heuristic. If Drive sync has a 10-min lag (unusual but possible), a fresh session can look stale. Acceptable risk — the worst case is the second user gets a "previous session ended uncleanly" log line.

---

## Part 3 — Backup (manual + auto, admin-only)

Independent of the main DB location — backups can land on a USB drive, a different Drive folder, anywhere. Surface in the same Settings tab.

### Settings UI section: "სარეზერვო ასლი"

- Backup folder picker (`config.json["backup_folder"]`).
- Last manual + last auto backup info (path, relative time).
- **[ახლავე სარეზერვო ასლის შექმნა]** button (disabled until folder set).
- On click: copy `DB_PATH` → `<backup_folder>/Kodak_Backups/kodak_YYYY-MM-DD_HH-MM.db` AND overwrite `<backup_folder>/Kodak_Backups/kodak_latest.db`. Update `last_manual_backup`. Inline success.

### Auto-backup on close

In the `on_window_event="close"` handler (Part 2 step 2):
- If `backup_folder` is set and reachable, copy `DB_PATH` → `<backup_folder>/Kodak_Backups/kodak_<YYYY-MM-DD>.db` (one stable file per day, overwritten on each close that day → 30-day rolling window of daily snapshots).
- If unreachable (Drive paused, drive unmounted), silently skip; Settings UI shows "last auto-backup" so the user notices.

---

## Part 4 — macOS packaging

### One-time prerequisites

- Full **Xcode** (App Store) → `xcodebuild -runFirstLaunch`.
- **Flutter SDK**: `brew install --cask flutter` → `flutter config --enable-macos-desktop`.
- **flet CLI** in venv: `.venv/bin/pip install "flet[all]"`.

### `pyproject.toml` additions

```toml
[tool.flet]
org       = "com.guriaphoto"
product   = "Kodak"
company   = "Guriaphoto"
copyright = "Copyright (C) 2026 Guriaphoto"

[tool.flet.app]
path = "src/kodak/main.py"
```

### Optional app icon

`assets/icon.png` (1024×1024). Flet auto-bundles it.

### Build

```bash
.venv/bin/flet build macos --project Kodak --product "გურიაფოტო კოდაკი"
```

Output: `build/macos/Kodak.app`. First build ~10 min.

### Distribution

```bash
hdiutil create -volname "Kodak" -srcfolder build/macos/Kodak.app \
  -ov -format UDZO Kodak.dmg
```

First launch on a new Mac: right-click → **Open** to bypass Gatekeeper once.

---

## Files to create / modify

| File | Action | Purpose |
|---|---|---|
| `src/kodak/config.py` | **NEW** | JSON config: `db_folder`, `backup_folder`, last-backup metadata |
| `src/kodak/db.py` | edit | Resolve `DB_PATH` from `config.json` + dev override |
| `src/kodak/session_lock.py` | **NEW** | Lock acquire/release/heartbeat |
| `src/kodak/main.py` | edit | Acquire lock at startup, show conflict dialog, register `on_window_event` for auto-backup + lock release |
| `src/kodak/ui/conflict_dialog.py` | **NEW** | Modal "another session active" UI |
| `src/kodak/ui/settings_view.py` | **NEW** | Admin Settings: DB folder + backup folder + manual backup |
| `src/kodak/ui/shell.py` | edit (`_switch_view`, ~line 230) | Render `SettingsView` for admin at index 4; placeholder for employees |
| `pyproject.toml` | edit | Add `[tool.flet]` blocks |
| `assets/icon.png` | **NEW** (optional) | App icon |

---

## Reusable patterns to lean on

- **DatePicker overlay pattern** in `today_view.py:_HistoryPanel.__init__` (`self._page.overlay.extend([...])`) — same for `ft.FilePicker`. Cache the Settings view in `AppShell._switch_view` (like `_today_view`, `_report_view`) so the FilePicker isn't duplicated on each visit.
- **Inline confirmation row** in `credits_view.py` (forgive credit) — reused for the "copy DB / start fresh / cancel" prompt and "create backup" success.
- **`_placeholder` helper** in `shell.py:238–259` — for the "admin only" Settings message.
- **Atomic file write** (`tmp + os.replace`) — used for both `config.json` and `kodak.db.lock`.

---

## Verification

After Part 1 (DB path):
1. `PYTHONPATH=src .venv/bin/python -c "from kodak.db import DB_PATH; print(DB_PATH)"` — prints dev path.
2. Launch app → Settings → set DB folder to `~/Desktop/test_kodak/`, choose **გადავიტანო**, restart. New path active.

After Part 2 (Session lock):
3. Launch app on Mac A — `kodak.db.lock` appears next to DB.
4. Launch app on Mac B (same Drive folder) → conflict dialog shows Mac A's host + heartbeat.
5. Choose **გაუქმება** — Mac B exits cleanly, lock untouched.
6. Choose **მაინც გახსნა** — Mac B takes over; check Mac A still works (UI doesn't crash, but writes from now will race; this is the "user accepted the risk" path).
7. `kill -9` the app — lock stays. Restart → app silently overrides stale lock and logs "previous session ended uncleanly".
8. Quit cleanly — lock file deleted.

After Part 3 (Backup):
9. As admin, set backup folder. Click **ახლავე სარეზერვო ასლის შექმნა** → confirm `<folder>/Kodak_Backups/kodak_<ts>.db` and `kodak_latest.db` exist; both open in DB Browser.
10. Quit app → confirm `kodak_<today>.db` got refreshed.
11. Login as employee → Settings is admin-only.

After Part 4 (Packaging):
12. `.venv/bin/flet build macos`, ~10 min. `open build/macos/Kodak.app` → full flow works.
13. Use Settings to point DB folder at `~/Google Drive/My Drive/Kodak/`. Quit. Open the same `.app` on a second Mac (mounted DMG → /Applications) configured with the same Drive folder. Verify same data appears, lock-conflict dialog fires when launched simultaneously.
14. Build DMG (`hdiutil`), test install on a clean account.

---

## Risks & notes

- **SQLite + cloud sync**: even with the session lock, SQLite over Google Drive is more fragile than local. Risks: Drive uploading mid-write (rare with default DELETE journal mode + small DB), conflicts from two laptops both edited offline. Mitigations: session lock prevents the common case; daily auto-backup gives a recovery point; the manual backup button gives an explicit "snapshot now" before risky edits. **Strongest recommendation**: keep WAL mode OFF (it's off by default in SQLAlchemy). The default DELETE journal mode keeps the DB in a single file, which Drive syncs more reliably.
- **Lock TTL**: 5 min stale threshold + 60 s heartbeat. Tune later if Drive sync proves laggier.
- **Force-open is destructive**: when user clicks **მაინც გახსნა**, both PCs are technically writing. We log this loudly. The auto-backup at next clean close gives a recovery snapshot.
- **`on_window_event` reliability**: Flet's close handler runs on graceful close (window X, Cmd-Q). It does *not* run on `kill -9` or power loss. The next-launch stale-lock detection covers those cases. But the auto-backup also won't run, which is why the user should still hit the manual backup button periodically.
- **First-run UX**: if `db_folder` isn't set, app uses `<config_dir>/kodak.db` (always works). Settings tab guides the user to point it at Drive on first admin launch.
- **Auth tokens are not involved**: no Turso, no cloud accounts. All data flow is plain file I/O over Google Drive's local sync agent.
- **Windows packaging**: out of scope. `config.py` Windows branch is wired for later. Win 7 not supported (Flutter requires Win 10+).
