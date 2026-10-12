"""
scripts/check_schema_drift.py
------------------------------
Compares the live database schema (as introspected via SQLAlchemy's
Inspector) against every column declared on every mapped model class.
Exits non-zero if any table has a column in the DB with no matching model
attribute, or a model attribute with no matching DB column — either
direction is a real drift, not just the DB-ahead case that prompted this
script.

Usage:
    python -m scripts.check_schema_drift
"""
import sys

from sqlalchemy import inspect

from app.database import Base, engine


def main() -> int:
    insp = inspect(engine)
    db_tables = set(insp.get_table_names())
    problems = []

    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if table.name not in db_tables:
            problems.append(f"Model table '{table.name}' has no matching DB table.")
            continue

        db_columns = {c["name"] for c in insp.get_columns(table.name)}
        model_columns = {c.name for c in table.columns}

        db_only = db_columns - model_columns
        model_only = model_columns - db_columns

        if db_only:
            problems.append(f"{table.name}: DB has columns not on the model: {sorted(db_only)}")
        if model_only:
            problems.append(f"{table.name}: model has columns not in the DB: {sorted(model_only)}")

    if problems:
        print("Schema drift detected:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("No schema drift detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())