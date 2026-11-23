"""Consistent online backups (SQLite backup API) and offline restore."""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import Paths

BACKUP_PREFIX = "readingclub-backup-"
DB_NAME_IN_ZIP = "readingclub.db"


class BackupError(Exception):
    pass


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def create_backup(paths: Paths, keep: int = 14, label: str = "") -> Path:
    """Write data/backups/readingclub-backup-<ts>.zip containing a consistent
    snapshot of the database plus config.json. Safe while the server runs."""
    paths.ensure()
    if not paths.db_path.exists():
        raise BackupError("No database to back up yet.")
    suffix = f"-{label}" if label else ""
    target = paths.backups_dir / f"{BACKUP_PREFIX}{_timestamp()}{suffix}.zip"
    n = 1
    while target.exists():
        target = paths.backups_dir / f"{BACKUP_PREFIX}{_timestamp()}{suffix}-{n}.zip"
        n += 1
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / DB_NAME_IN_ZIP
        src = sqlite3.connect(str(paths.db_path), timeout=30)
        dst = sqlite3.connect(str(snap))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        manifest = {
            "app_version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database": DB_NAME_IN_ZIP,
        }
        tmp_zip = target.with_suffix(".zip.part")
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap, DB_NAME_IN_ZIP)
            if paths.config_path.exists():
                zf.write(paths.config_path, "config.json")
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        tmp_zip.replace(target)
    prune_backups(paths, keep)
    return target


def list_backups(paths: Paths) -> list[Path]:
    if not paths.backups_dir.exists():
        return []
    return sorted(paths.backups_dir.glob(f"{BACKUP_PREFIX}*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)


def prune_backups(paths: Paths, keep: int) -> None:
    automatic = [p for p in list_backups(paths) if "pre-restore" not in p.name]
    for old in automatic[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def latest_backup_age_hours(paths: Paths) -> float | None:
    backups = list_backups(paths)
    if not backups:
        return None
    age = datetime.now().timestamp() - backups[0].stat().st_mtime
    return age / 3600


def verify_backup(zip_path: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            if DB_NAME_IN_ZIP not in names or "manifest.json" not in names:
                raise BackupError("This file is not a Reading Club backup.")
            with tempfile.TemporaryDirectory() as tmp:
                zf.extract(DB_NAME_IN_ZIP, tmp)
                con = sqlite3.connect(str(Path(tmp) / DB_NAME_IN_ZIP))
                try:
                    result = con.execute("PRAGMA integrity_check").fetchone()[0]
                    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                finally:
                    con.close()
                if result != "ok":
                    raise BackupError(f"Backup database is damaged: {result}")
                if not {"users", "groups", "daily_progress"} <= tables:
                    raise BackupError("Backup database is missing required tables.")
    except zipfile.BadZipFile as exc:
        raise BackupError("The file is not a valid zip archive.") from exc


def restore_backup(paths: Paths, zip_path: Path, restore_config: bool = False) -> Path | None:
    """Replace the live database with the one in `zip_path`.

    MUST be called while the server is stopped. The current database is first
    saved as a 'pre-restore' backup so a restore can itself be undone.
    Returns the path of the safety backup (or None if there was no database).
    """
    zip_path = Path(zip_path)
    verify_backup(zip_path)
    safety = None
    if paths.db_path.exists():
        safety = create_backup(paths, keep=10**6, label="pre-restore")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extract(DB_NAME_IN_ZIP, tmp)
            if restore_config and "config.json" in zf.namelist():
                zf.extract("config.json", tmp)
                shutil.copyfile(Path(tmp) / "config.json", paths.config_path)
        for ext in ("-wal", "-shm"):
            side = Path(str(paths.db_path) + ext)
            if side.exists():
                side.unlink()
        shutil.copyfile(Path(tmp) / DB_NAME_IN_ZIP, paths.db_path)
    return safety
