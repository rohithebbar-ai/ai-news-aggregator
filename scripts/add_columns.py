"""
Option B: Add missing columns to existing articles table (keeps existing rows).
Run from project root: uv run python scripts/add_columns.py
Uses DATABASE_URL from .env.
"""

import os
import sys

from dotenv import load_dotenv
import psycopg2  # type: ignore[import-untyped]

load_dotenv()

# Columns the app expects (repository/schema) that may be missing on an older table
ALTERS = [
    "ADD COLUMN IF NOT EXISTS summary TEXT",
    "ADD COLUMN IF NOT EXISTS raw_content TEXT NOT NULL DEFAULT ''",
    "ADD COLUMN IF NOT EXISTS image TEXT",
    "ADD COLUMN IF NOT EXISTS images JSONB",
    "ADD COLUMN IF NOT EXISTS source_type TEXT",
    "ADD COLUMN IF NOT EXISTS source_url TEXT",
]


def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set in .env", file=sys.stderr)
        sys.exit(1)
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    for alter_sql in ALTERS:
        cur.execute("ALTER TABLE articles " + alter_sql)
    cur.close()
    conn.close()
    print("Done. Missing columns added to articles.")


if __name__ == "__main__":
    main()
