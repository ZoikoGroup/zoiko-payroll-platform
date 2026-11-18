"""United Arab Emirates migration ad01fc67ce44 (ZP-AE-ENG-001): one nullable
column, payslip_items.ae_calculation_snapshot.

Proves on SQLite: the column exists on the model and is added literally; the
migration is additive and idempotent both ways (replay over the full model
schema is a no-op, downgrade removes only the column, upgrade restores it);
migrations/create_all builds a fresh database with it; the deploy drift filter
explains it; it is the single head; no UAE table exists (every UAE value lives
in the canonical pack, every UAE employee fact on payroll_employees)."""
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "alembic" / "versions"
REVISION = "ad01fc67ce44"
PARENT = "c3e8a1d5f7b2"
FILENAME = f"{REVISION}_ae_foundation.py"
COLUMN = "ae_calculation_snapshot"


def _load():
    path = VERSIONS / FILENAME
    spec = importlib.util.spec_from_file_location(f"rev_{REVISION}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metadata():
    from app.database import Base
    import app.modules.organizations.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.payroll.models  # noqa: F401
    import app.modules.billing.models  # noqa: F401
    import app.modules.communications.models  # noqa: F401
    return Base.metadata


@pytest.fixture()
def model_engine():
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
    metadata.create_all(engine)
    yield engine
    engine.dispose()


def _run(engine, fn_name):
    module = _load()
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, fn_name)()


def _cols(engine, table="payslip_items"):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_column_is_on_the_model_and_added_literally():
    assert COLUMN in {c.name for c in _metadata().tables["payslip_items"].columns}
    text = (VERSIONS / FILENAME).read_text(encoding="utf-8")
    assert f'op.add_column("payslip_items", sa.Column("{COLUMN}"' in text


def test_no_uae_tables_or_employee_columns():
    metadata = _metadata()
    assert not [t for t in metadata.tables if t.startswith("payroll_ae_")]
    for table in ("payroll_employees", "payroll_employee_statutory_profiles", "payroll_runs"):
        assert not [c.name for c in metadata.tables[table].columns if c.name.startswith("ae_")], table


def test_replay_is_a_no_op_and_round_trip_touches_only_the_column(model_engine):
    tables_before = set(sa.inspect(model_engine).get_table_names())
    cols_before = _cols(model_engine)
    _run(model_engine, "upgrade")
    assert _cols(model_engine) == cols_before
    _run(model_engine, "downgrade")
    assert _cols(model_engine) == cols_before - {COLUMN}
    assert {"be_calculation_snapshot", "my_calculation_snapshot"} <= _cols(model_engine)   # neighbours untouched
    _run(model_engine, "downgrade")                                                       # idempotent both ways
    _run(model_engine, "upgrade")
    _run(model_engine, "upgrade")
    assert _cols(model_engine) == cols_before
    assert set(sa.inspect(model_engine).get_table_names()) == tables_before


def test_create_all_builds_a_fresh_database_with_the_column(tmp_path):
    """migrations/create_all against a throwaway SQLite file (subprocess, so the
    app's global engine is bound to that file and never to backend/.env)."""
    target = tmp_path / "fresh.db"
    env = dict(os.environ, PAYROLL_DATABASE_URL=f"sqlite:///{target.as_posix()}")
    done = subprocess.run([sys.executable, "-m", "migrations.create_all.create_all"], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    engine = sa.create_engine(f"sqlite:///{target.as_posix()}")
    try:
        assert COLUMN in _cols(engine)
    finally:
        engine.dispose()


def test_deploy_drift_filter_explains_the_column():
    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(BACKEND)
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    assert tables == set()
    assert columns == {"payslip_items": {COLUMN}}


def test_revision_is_the_single_child_of_the_previous_head():
    module = _load()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    # The report-template content editor (d7a3f1c9e5b2) also grows from PARENT on main;
    # merge 2855a70a9ed6 rejoins the two.
    assert sorted(children) == sorted([FILENAME, "d7a3f1c9e5b2_report_template_content_editor.py"])


def test_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert list(script.get_heads()) == ["2855a70a9ed6"]   # merge: this revision + d7a3f1c9e5b2
    assert set(script.get_revision("2855a70a9ed6").down_revision) == {REVISION, "d7a3f1c9e5b2"}


def test_migration_is_listed_in_the_manifest():
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{FILENAME}|{REVISION}|{PARENT}|" in manifest
