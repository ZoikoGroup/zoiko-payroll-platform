"""Every Singapore schema object the models declare must be delivered by a
checked-in Alembic migration.

Regression for the Phase 6.8 gap: models.SgpIr8aModification declared the
``sgp_ir8a_modifications`` table while its migration was parked outside this
tree, so a database built by ``alembic upgrade head`` lacked a table the ORM
uses (the SQLite suite never noticed — it builds tables with create_all).

Metadata-only: parses the migration files and reads SQLAlchemy metadata; no
database is touched. ``app`` is imported lazily inside the tests (see the
collection-order DB-binding hazard in tests/conftest.py).
"""

import re
from pathlib import Path

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _migration_sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(_VERSIONS_DIR.glob("*.py")))


def _sg_metadata():
    from app.database import Base
    import app.modules.payroll.models  # noqa: F401  (registers the tables)
    return Base.metadata


def test_every_sgp_table_has_a_create_table_migration():
    sources = _migration_sources()
    created = set(re.findall(r"create_table\(\s*['\"]([a-z0-9_]+)['\"]", sources))
    sg_tables = sorted(t for t in _sg_metadata().tables if t.startswith("sgp_"))
    assert "sgp_ir8a_modifications" in sg_tables
    assert [t for t in sg_tables if t not in created] == []


def test_every_sgp_column_on_a_shared_table_is_added_by_a_migration():
    """``sgp_*`` columns on shared tables (payroll_employees, payslip_items)
    are added by the inspector-guarded Singapore migrations, whose column
    names are string literals in the migration file."""
    sources = _migration_sources()
    literals = set(re.findall(r"['\"](sgp_[a-z0-9_]+)['\"]", sources))
    missing = sorted(
        f"{name}.{col.name}"
        for name, table in _sg_metadata().tables.items()
        if not name.startswith("sgp_")
        for col in table.columns
        if col.name.startswith("sgp_") and col.name not in literals
    )
    assert missing == []
