"""
tests/conftest.py
------------------
Test setup shared by every module under backend/tests/.

Scope note: these tests exercise the payroll calculation ENGINE
(engine/standard.py, engine/base.py, engine/resolver.py) directly with
lightweight in-memory rate/slab objects — no database is touched. The
engine is pure (input dataclass in, output dataclass out), so this gives
full coverage of the per-country tax math and the safe formula evaluator
without needing a test database.

DB-dependent paths (engine/tax_resolver.py's pack lookup, service.py's
sync/seed functions, the super_admin/payroll routers) are NOT covered here
yet — they need a disposable test database (SQLite can't host this
schema's Postgres-specific partial unique indexes) and are a natural
follow-up once one is wired up, not something to fake against the live
Neon dev database from a test suite.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
