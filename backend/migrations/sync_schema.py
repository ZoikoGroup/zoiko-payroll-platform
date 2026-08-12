"""
migrations/sync_schema.py
-------------------------
Non-destructive schema sync for databases that were created *before* the SQL
models grew new columns. There is deliberately no alembic in this platform
(`create_all` only builds fresh, empty databases and never alters existing
tables), so a table like `organizations` can silently lag the model — which
produces errors such as ``column organizations.city does not exist`` when a
model gains city/state/country/company_type/logo_path columns.

This script inspects every table registered on ``Base.metadata``, compares it
against the live database, and ``ALTER TABLE ... ADD COLUMN`` for each missing
column. It never drops, renames, or alters existing columns or rows.

Usage:
    python -m migrations.sync_schema

Run from the backend/ directory (module-style so imports resolve).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # type: ignore[import]

import app.database  # noqa: F401  (registers every model on Base.metadata)
from app.database import Base, engine  # noqa: E402

# JSON is stored as JSONB on PostgreSQL (JSON is fine on SQLite).
_JSON_TYPE = "JSONB" if engine.dialect.name == "postgresql" else "JSON"


def _column_ddl(column) -> str:
    base_type = type(column.type).__name__
    length = getattr(column.type, "length", None)
    if base_type == "String" and length:
        col_type = f"VARCHAR({length})"
    elif base_type == "Integer":
        col_type = "INTEGER"
    elif base_type == "Boolean":
        col_type = "BOOLEAN"
    elif base_type in ("DateTime",):
        col_type = "TIMESTAMP"
    elif base_type == "Text":
        col_type = "TEXT"
    elif base_type == "JSON":
        col_type = _JSON_TYPE
    elif base_type == "Numeric":
        precision = getattr(column.type, "precision", None)
        scale = getattr(column.type, "scale", None)
        if precision is not None and scale is not None:
            col_type = f"NUMERIC({precision}, {scale})"
        elif precision is not None:
            col_type = f"NUMERIC({precision})"
        else:
            col_type = "NUMERIC"
    else:
        col_type = column.type.compile(dialect=engine.dialect)

    # Existing rows must get a value, so newly added columns are always
    # nullable regardless of the model (a sync helper, not a migration
    # framework — safe > strict).
    return f'"{column.name}" {col_type} NULL'


def sync_schema() -> list[str]:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []

    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {c["name"] for c in inspector.get_columns(table_name)}
        missing = [
            column for column in table.columns
            if column.name not in existing_columns and not column.foreign_keys
        ]
        if not missing:
            continue

        with engine.begin() as conn:
            for column in missing:
                ddl = f'ALTER TABLE "{table_name}" ADD COLUMN {_column_ddl(column)}'
                conn.execute(text(ddl))
                added.append(f"{table_name}.{column.name}")

    return added


def main() -> None:
    added = sync_schema()
    if not added:
        print("Schema is up to date — no columns were added.")
        return
    print(f"Added {len(added)} missing column(s):")
    for name in added:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
