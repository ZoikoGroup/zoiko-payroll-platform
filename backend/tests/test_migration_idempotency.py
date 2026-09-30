"""
tests/test_migration_idempotency.py
-----------------------------------
The 2026-09-29 production deploy failed with
`DuplicateTable: relation "payroll_fr_establishments" already exists`:
an earlier, unmerged France/Ireland branch had already run venu's France
and Ireland migrations against production, so replaying them on merge
aborted the whole upgrade.

These migrations are now guarded. This test replays each one against a
database that ALREADY holds the full model schema — production's situation —
and requires every upgrade() to complete without error, in chain order.
"""
import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

# Chain order (each depends on the one before it being applied or skipped).
_GUARDED = [
    "74aeb450aeee",  # France establishments + editable fields
    "b1c2d3e4f5a6",  # Ireland tables + 13 statutory-profile columns
    "c7d4e9f1a2b3",  # payslip_items.ie_calculation_snapshot
    "e5a1c7b9d204",  # Ireland statutory sick leave records
    "9f8e7d6c5b4a",  # recreate Ireland Revenue tables
    "b3c4d5e6f7a8",  # attendance composite index
    "c4d5e6f7a8b9",  # drop Ireland Revenue tables
]


def _load(revision):
    path = next(_VERSIONS.glob(f"{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"_mig_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def existing_schema_engine():
    """A database already at the model schema, like production."""
    # Same model set tests/conftest.py's `db` fixture registers.
    from app.database import Base
    import app.modules.organizations.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.payroll.models  # noqa: F401
    import app.modules.billing.models  # noqa: F401
    import app.modules.communications.models  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _run_upgrades(engine, revisions):
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            for revision in revisions:
                _load(revision).upgrade()


def test_guarded_migrations_replay_cleanly_over_an_existing_schema(existing_schema_engine):
    tables_before = set(inspect(existing_schema_engine).get_table_names())
    assert "payroll_fr_establishments" in tables_before  # the table that broke the deploy

    _run_upgrades(existing_schema_engine, _GUARDED)

    tables_after = set(inspect(existing_schema_engine).get_table_names())
    # Nothing the models declare was dropped by the replay.
    assert tables_before <= tables_after


def test_replaying_twice_is_still_a_no_op(existing_schema_engine):
    """A deploy that fails later and is retried must not trip over itself."""
    _run_upgrades(existing_schema_engine, _GUARDED)
    _run_upgrades(existing_schema_engine, _GUARDED)


def test_every_guarded_migration_keeps_its_literal_create_table_call():
    """test_model_tables_have_migrations and deploy_migrate.sh's stamp walk
    both find a table's migration by scanning for `op.create_table('name'`.
    Guarding must indent those calls, never rename or hide them."""
    for revision in ("74aeb450aeee", "b1c2d3e4f5a6", "e5a1c7b9d204", "9f8e7d6c5b4a"):
        text = next(_VERSIONS.glob(f"{revision}_*.py")).read_text(encoding="utf-8")
        assert "op.create_table(" in text, revision
        assert "if not _has_table(" in text, revision
