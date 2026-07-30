"""Config backup: dump the bot's configuration tables to a JSON snapshot.

Deliberately talks to SQLite directly instead of going through a repository, so
the standalone scripts in scripts/ can reuse it without importing discord.py.

JSON rather than CSV: the tables have different shapes and nullable columns, and
a restore has to put values back in the right types. One CSV per table would
mean five files and a lot of quoting rules for free-text reminder messages.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Configuration worth restoring. `issues_log` is deliberately absent: it is an
# append-only audit trail that grows without bound and rebuilding it serves no
# purpose. `scores` is included — losing everyone's tally would be the one thing
# people actually notice.
TABLES = ("reminders", "triggers", "whitelist", "guild_config", "scores")

BACKUP_PREFIX = "config-backup-"
BACKUP_SUFFIX = ".json"


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def export_config(db_path: str) -> dict:
    """Read every configuration table into a plain dict."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        present = _existing_tables(conn)
        data = {}
        for table in TABLES:
            # A table can legitimately be missing: `reminders` only exists once
            # the reminders cog has run at least once.
            if table not in present:
                continue
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            data[table] = [dict(r) for r in rows]
    finally:
        conn.close()

    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(Path(db_path).resolve()),
        "tables": data,
    }


def backup_dir_for(db_path: str) -> Path:
    return Path(db_path).resolve().parent / "backups"


def write_backup(db_path: str, keep: int = 14) -> Path:
    """Write a timestamped snapshot and prune old ones. Returns the new file."""
    payload = export_config(db_path)
    dest_dir = backup_dir_for(db_path)
    dest_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = dest_dir / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"

    # Write to a temp file and move into place, so a crash mid-write can't leave
    # a truncated file that looks like a valid backup.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

    prune_backups(dest_dir, keep)
    return path


def prune_backups(dest_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` snapshots. Returns what was removed."""
    if keep <= 0:
        return []
    snapshots = sorted(dest_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))
    stale = snapshots[:-keep] if len(snapshots) > keep else []
    for old in stale:
        old.unlink(missing_ok=True)
    return stale


def summarise(payload: dict) -> str:
    tables = payload.get("tables", {})
    if not tables:
        return "leeg"
    return ", ".join(f"{name}: {len(rows)}" for name, rows in sorted(tables.items()))


def restore_config(db_path: str, payload: dict, tables: tuple[str, ...] = TABLES) -> dict[str, int]:
    """Replace the given tables with the snapshot's contents.

    Destructive by design — a restore that merged would leave you with a mix of
    old and new rows and no way to tell which is which. Callers must confirm.
    """
    data = payload.get("tables", {})
    conn = sqlite3.connect(db_path)
    written: dict[str, int] = {}
    try:
        present = _existing_tables(conn)
        for table in tables:
            rows = data.get(table)
            if not rows or table not in present:
                continue
            columns = list(rows[0].keys())
            placeholders = ", ".join("?" for _ in columns)
            collist = ", ".join(columns)
            conn.execute(f"DELETE FROM {table}")
            conn.executemany(
                f"INSERT INTO {table} ({collist}) VALUES ({placeholders})",
                [tuple(r.get(c) for c in columns) for r in rows],
            )
            written[table] = len(rows)
        conn.commit()
    finally:
        conn.close()
    return written
