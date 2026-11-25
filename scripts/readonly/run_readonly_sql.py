"""READ-ONLY: run a .sql file of SELECT statements against the app's configured
database and print each result (optionally also as CSV).

It writes, updates or deletes NOTHING. Safety: it refuses a file containing any
write / DDL keyword or any statement that is not a pure SELECT / WITH, runs
every statement inside a READ ONLY transaction (PostgreSQL), and always rolls
back. Prefer running it with a read-only database role.

Usage (from any directory; it finds backend/ next to this scripts/ folder):
    python scripts/readonly/run_readonly_sql.py scripts/readonly/de_usage_check.sql
    python scripts/readonly/run_readonly_sql.py <file.sql> --csv out/prefix
"""
import csv
import os
import re
import sys

SCRIPT_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend")


def find_backend() -> str:
    """The backend directory (holds app/ and .env): next to this scripts/ folder, else from the current directory."""
    here = os.getcwd()
    for candidate in (SCRIPT_BACKEND, here, os.path.join(here, "backend")):
        if os.path.isdir(os.path.join(candidate, "app")):
            return os.path.abspath(candidate)
    raise SystemExit("Could not find the backend directory (the folder that contains app/).")

WRITES = re.compile(r"\b(insert|update|delete|merge|drop|alter|truncate|create|grant|revoke|copy|vacuum|call|do)\b",
                    re.IGNORECASE)


def statements(sql: str) -> list:
    body = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = os.path.abspath(sys.argv[1])                       # resolved before changing directory
    if not os.path.isfile(path):
        raise SystemExit(f"SQL file not found: {path}")
    prefix = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
    prefix = os.path.abspath(prefix) if prefix else None
    stmts = statements(open(path, encoding="utf-8").read())
    for s in stmts:
        if not re.match(r"^(select|with)\b", s, re.IGNORECASE) or WRITES.search(re.sub(r"'[^']*'", "''", s)):
            print(f"REFUSED: not a pure SELECT statement:\n{s[:200]}")
            return 1
    backend = find_backend()
    os.chdir(backend)                                         # the app reads backend/.env
    sys.path.insert(0, backend)
    from sqlalchemy import text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        for n, s in enumerate(stmts, start=1):
            result = db.execute(text(s))
            cols = list(result.keys())
            rows = result.fetchall()
            print(f"\n=== query {n}: {len(rows)} row(s) ===")
            print(" | ".join(cols))
            for r in rows:
                print(" | ".join("" if v is None else str(v) for v in r))
            if prefix:
                with open(f"{prefix}_{n}.csv", "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(cols)
                    w.writerows(rows)
    finally:
        db.rollback()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
