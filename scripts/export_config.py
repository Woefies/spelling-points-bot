"""Write a JSON snapshot of the bot's configuration tables.

The bot does this automatically once a day; this is the manual version, for
taking a snapshot right before a risky change.

Usage:
    python scripts/export_config.py
    python scripts/export_config.py --keep 30
    python scripts/export_config.py --stdout        # print instead of writing
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.backup import export_config, summarise, write_backup  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the bot's configuration tables.")
    parser.add_argument("--keep", type=int, default=14, help="how many snapshots to retain")
    parser.add_argument("--stdout", action="store_true", help="print the JSON instead of saving")
    args = parser.parse_args()

    db_path = os.getenv("DB_PATH", "data/points.db")
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path} — has the bot run yet?", file=sys.stderr)
        sys.exit(1)

    if args.stdout:
        print(json.dumps(export_config(db_path), indent=2, ensure_ascii=False))
        return

    path = write_backup(db_path, keep=args.keep)
    print(f"Wrote {path}")
    print(summarise(export_config(db_path)))


if __name__ == "__main__":
    main()
