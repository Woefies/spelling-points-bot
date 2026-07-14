"""
Standalone offline reporter for the bot's flagged-words log.

Reads the `issues_log` table from the bot's SQLite DB and aggregates the
most-frequently flagged words across all guilds, so a human can pick which
words to promote into the default whitelist (Settings.whitelist in
core/config.py).

Stdlib only. No Discord, no bot import.

Usage: python scripts/report_flagged.py [--limit 30] [--min-hits 2] [--lang nl] [--csv data/flagged.csv]
"""

import argparse
import csv
import os
import sys
import sqlite3

# Keep in sync with core/config.py Settings.whitelist
DEFAULT_WHITELIST = {"lol", "haha", "xd", "omg", "brb"}


def fetch_rows(db_path: str, min_hits: int, lang: str | None) -> list[tuple]:
    query = """
        SELECT LOWER(word) AS w, lang, COUNT(*) AS hits,
               COUNT(DISTINCT guild_id) AS guilds,
               COUNT(DISTINCT user_id) AS users,
               MAX(ts) AS last_seen
        FROM issues_log
        GROUP BY LOWER(word), lang
        HAVING COUNT(*) >= ?
    """
    params: list = [min_hits]
    if lang:
        query += " AND lang = ?"
        params.append(lang)
    query += " ORDER BY hits DESC, w ASC"

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(query, params)
        rows = cur.fetchall()
    finally:
        conn.close()
    return [tuple(row) for row in rows]


def write_csv(path: str, rows: list[tuple]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "lang", "hits", "guilds", "users", "last_seen"])
        for row in rows:
            writer.writerow(row)


def print_table(rows: list[tuple]) -> None:
    header = ("WORD", "LANG", "HITS", "GUILDS", "USERS", "LAST SEEN", "NOTE")
    widths = [16, 6, 6, 7, 6, 20, 16]

    def fmt(cols: tuple) -> str:
        return "  ".join(str(c).ljust(w) for c, w in zip(cols, widths))

    print(fmt(header))
    print(fmt(tuple("-" * w for w in widths)))
    for word, lang, hits, guilds, users, last_seen in rows:
        note = "✓ already default" if word in DEFAULT_WHITELIST else ""
        print(fmt((word, lang, hits, guilds, users, last_seen, note)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate the bot's issues_log to find most-frequently flagged words."
    )
    parser.add_argument("--limit", type=int, default=30, help="how many rows to print to console")
    parser.add_argument("--min-hits", type=int, default=1, help="only include words flagged at least N times")
    parser.add_argument("--lang", type=str, default=None, choices=["en", "nl"], help="filter to one language")
    parser.add_argument("--csv", type=str, default=None, help="write full aggregated result to CSV file")
    args = parser.parse_args()

    db_path = os.getenv("DB_PATH", "data/points.db")

    if not os.path.exists(db_path):
        print(f"DB not found at {db_path} — has the bot run yet?", file=sys.stderr)
        sys.exit(1)

    rows = fetch_rows(db_path, args.min_hits, args.lang)

    if not rows:
        print("No flagged words logged yet.")
        sys.exit(0)

    total_words = len({row[0] for row in rows})
    total_events = sum(row[2] for row in rows)
    print(f"{total_words} distinct words, {total_events} total flag events\n")

    print_table(rows[: args.limit])

    if args.csv:
        write_csv(args.csv, rows)
        print(f"\nWrote {len(rows)} rows to {args.csv}")


if __name__ == "__main__":
    main()
