"""Restore configuration tables from a snapshot made by export_config.py.

Destructive: the tables in the snapshot are emptied and refilled. Merging would
leave a mix of old and restored rows with no way to tell them apart, which is
worse than either outcome.

Dry run by default — nothing is written without --replace.

Usage:
    python scripts/import_config.py data/backups/config-backup-20260730-040000.json
    python scripts/import_config.py <file> --replace
    python scripts/import_config.py <file> --replace --tables reminders,triggers
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.backup import TABLES, restore_config, summarise  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore bot configuration from a snapshot.")
    parser.add_argument("snapshot", help="path to a config-backup-*.json file")
    parser.add_argument(
        "--replace", action="store_true", help="actually write (without this it is a dry run)"
    )
    parser.add_argument(
        "--tables", help=f"comma-separated subset to restore (default: {','.join(TABLES)})"
    )
    args = parser.parse_args()

    db_path = os.getenv("DB_PATH", "data/points.db")
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    try:
        payload = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read snapshot: {exc}", file=sys.stderr)
        sys.exit(1)

    tables = tuple(t.strip() for t in args.tables.split(",")) if args.tables else TABLES
    unknown = set(tables) - set(TABLES)
    if unknown:
        print(f"Unknown table(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        sys.exit(1)

    print(f"Snapshot from : {payload.get('created_at', 'unknown')}")
    print(f"Contains      : {summarise(payload)}")
    print(f"Target DB     : {db_path}")
    print(f"Tables to wipe: {', '.join(tables)}")

    if not args.replace:
        print("\nDry run — nothing written. Re-run with --replace to restore.")
        return

    written = restore_config(db_path, payload, tables)
    if not written:
        print("\nNothing restored: the snapshot has no rows for those tables.")
        return
    print("\nRestored: " + ", ".join(f"{t}: {n}" for t, n in sorted(written.items())))


if __name__ == "__main__":
    main()
