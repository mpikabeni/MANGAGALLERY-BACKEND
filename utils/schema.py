"""Tiny, idempotent schema upgrade (no Alembic needed).

`db.create_all()` creates missing TABLES but never adds a column to a table that already exists.
The "La Sainte Culture" feature adds a few columns; this helper adds them if they are missing, on
PostgreSQL and SQLite, without touching any data. Safe to run on every start and from several workers.
"""
import logging

from sqlalchemy import inspect, text

log = logging.getLogger("mgfr.schema")

# table -> [(column, DDL), ...]
NEW_COLUMNS = {
    "mangas": [
        ("section", "VARCHAR(30) NOT NULL DEFAULT 'normal'"),
        ("content_type", "VARCHAR(30) NOT NULL DEFAULT 'manga'"),
    ],
    "users": [
        ("adult_confirmed_at", "TIMESTAMP"),
    ],
}
NEW_INDEXES = [
    ("ix_mangas_section", "mangas", "section"),
    ("ix_mangas_content_type", "mangas", "content_type"),
]


def ensure_schema(db):
    insp = inspect(db.engine)
    for table, columns in NEW_COLUMNS.items():
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in columns:
            if name in existing:
                continue
            try:
                with db.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                log.info("Column added: %s.%s", table, name)
            except Exception as exc:  # another worker did it at the same moment
                log.info("Column %s.%s not added (%s)", table, name, str(exc).splitlines()[0][:120])
    for idx, table, column in NEW_INDEXES:
        if not insp.has_table(table):
            continue
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx} ON {table} ({column})"))
        except Exception:
            pass
