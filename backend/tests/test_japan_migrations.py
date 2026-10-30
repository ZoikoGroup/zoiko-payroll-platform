"""Japan foundation migration f686d5128f8a (ZP-JP-ENG-001 Phase 2).

Proves, without a PostgreSQL server:
  * the row-level-security policy the revision applies to each new table is
    the one d7f9b1c3e5a6's classify() derives from the model schema — TENANT
    for employer registrations, WORKER/"org" for the seven employee tables;
  * the tables the migration creates have exactly the model's columns, and
    the two shared snapshot/fingerprint columns exist on the models and are
    added literally by the migration;
  * it is additive and idempotent: replaying it over the full model schema
    is a no-op, and downgrade removes only its own objects;
  * the deploy drift filter explains every Japan object;
  * the vault, registration and resident-tax rules are enforced.
"""
import importlib.util
from datetime import date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
REVISION = "f686d5128f8a"
PARENT = "c2e7a4f9b1d8"   # re-parented 2026-10-30 (was 67c8d7454716)

TENANT = ("payroll_jp_employer_registrations",)
WORKER = (
    "payroll_jp_my_number_vault",
    "payroll_jp_my_number_access_events",
    "payroll_jp_worker_tax_profiles",
    "payroll_jp_social_insurance_enrollments",
    "payroll_jp_social_insurance_events",
    "payroll_jp_employment_insurance_profiles",
    "payroll_jp_resident_tax_assessments",
)
NEW_TABLES = TENANT + WORKER
SHARED = {"payslip_items": "jp_calculation_snapshot", "payroll_runs": "jp_approval_fingerprint"}


def _load(prefix=REVISION):
    path = next(VERSIONS.glob(f"{prefix}_*.py"))
    spec = importlib.util.spec_from_file_location(f"rev_{prefix}", path)
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


@pytest.fixture(scope="module")
def classified():
    metadata = _metadata()
    rls = _load("d7f9b1c3e5a6")
    cols, fks = {}, {}
    for name, table in metadata.tables.items():
        cols[name] = {c.name for c in table.columns}
        fks[name] = {fk.column.table.name for fk in table.foreign_keys}
    rls._schema = lambda bind: (cols, fks, set(metadata.tables))
    worker, tenant = rls.classify(None)
    return rls, worker, set(tenant)


class _CaptureBind:
    class dialect:
        name = "postgresql"

    def __init__(self):
        self.sql = []

    def execute(self, clause, *a, **k):
        self.sql.append(" ".join(str(clause).split()))


def _policies(statements):
    out = {}
    for s in statements:
        if s.startswith("CREATE POLICY"):
            table = s.split(' ON "', 1)[1].split('"', 1)[0]
            out[table] = s.split(" USING ", 1)[1].split(" WITH CHECK ", 1)[0]
    return out


# -- row-level security -----------------------------------------------------
def test_classify_agrees_with_the_policies_the_revision_applies(classified):
    _rls, worker, tenant = classified
    for table in TENANT:
        assert table in tenant and table not in worker, table
    for table in WORKER:
        assert worker.get(table) == "org" and table not in tenant, table


def test_revision_emits_the_derived_policy(classified):
    rls = classified[0]
    bind = _CaptureBind()
    _load()._rls_for_new_tables(bind)
    want = {t: " ".join(rls._TENANT_PREDICATE.split()) for t in TENANT}
    want.update({t: " ".join(rls._worker_predicate("org").split()) for t in WORKER})
    assert _policies(bind.sql) == want
    for table in NEW_TABLES:
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in bind.sql
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in bind.sql


# -- migration <-> model contract (SQLite) ----------------------------------
@pytest.fixture()
def model_engine():
    metadata = _metadata()
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
    metadata.create_all(engine)
    yield engine, metadata
    engine.dispose()


def _run(engine, fn_name):
    module = _load()
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, fn_name)()


def _cols(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_new_tables_match_the_models_exactly(model_engine):
    engine, metadata = model_engine
    with engine.begin() as conn:
        for table in reversed(NEW_TABLES):
            conn.execute(sa.text(f'DROP TABLE "{table}"'))
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table


def test_shared_columns_exist_on_the_models_and_are_added_literally():
    metadata = _metadata()
    for table, column in SHARED.items():
        assert column in {c.name for c in metadata.tables[table].columns}, table
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    assert 'op.add_column("payslip_items", sa.Column("jp_calculation_snapshot"' in text
    assert 'op.add_column("payroll_runs", sa.Column("jp_approval_fingerprint"' in text


def test_replay_over_the_full_model_schema_is_a_no_op(model_engine):
    engine, _metadata_ = model_engine
    before = {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()}
    _run(engine, "upgrade")
    _run(engine, "upgrade")
    assert {t: _cols(engine, t) for t in sa.inspect(engine).get_table_names()} == before


def test_downgrade_removes_only_its_own_objects(model_engine):
    engine, _metadata_ = model_engine
    tables_before = set(sa.inspect(engine).get_table_names())
    _run(engine, "downgrade")
    tables_after = set(sa.inspect(engine).get_table_names())
    assert tables_before - tables_after == set(NEW_TABLES)
    for table, column in SHARED.items():
        assert column not in _cols(engine, table)
    assert "za_calculation_snapshot" in _cols(engine, "payslip_items")     # neighbours untouched
    assert "za_approval_fingerprint" in _cols(engine, "payroll_runs")
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert table in set(sa.inspect(engine).get_table_names()), table
    for table, column in SHARED.items():
        assert column in _cols(engine, table)


def test_deploy_drift_filter_explains_every_jp_object():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(VERSIONS.parents[1])
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    assert set(NEW_TABLES) <= tables
    assert columns["payslip_items"] == {"jp_calculation_snapshot"}
    assert columns["payroll_runs"] == {"jp_approval_fingerprint"}


def test_revision_is_a_single_child_of_the_previous_head():
    module = _load()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)


def test_create_table_names_are_literal_in_the_migration():
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table


# -- vault rules ------------------------------------------------------------
def test_the_vault_has_no_plaintext_like_column():
    metadata = _metadata()
    names = {c.name.lower() for c in metadata.tables["payroll_jp_my_number_vault"].columns}
    for forbidden in ("number", "plaintext", "raw_number", "last4", "last_four", "digits"):
        assert forbidden not in names


def test_the_vault_requires_ciphertext_unless_deleted(model_engine):
    engine, metadata = model_engine
    table = metadata.tables["payroll_jp_my_number_vault"]
    row = dict(organization_id=1, employee_id=1, subject_type="EMPLOYEE", subject_ref="self",
               key_version=1, fingerprint="f" * 64, collected_at=datetime(2026, 4, 1), status="ACTIVE")
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(table.insert().values(**row))
    with engine.begin() as conn:
        conn.execute(table.insert().values(**row, ciphertext="ciphertext"))


def test_the_vault_allows_one_active_row_per_subject(model_engine):
    engine, metadata = model_engine
    table = metadata.tables["payroll_jp_my_number_vault"]
    row = dict(organization_id=1, employee_id=1, subject_type="EMPLOYEE", subject_ref="self",
               ciphertext="ciphertext", key_version=1, fingerprint="f" * 64,
               collected_at=datetime(2026, 4, 1), status="ACTIVE")
    with engine.begin() as conn:
        conn.execute(table.insert().values(**row))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(table.insert().values(**row))
    other = dict(row, subject_ref="dependant-1")
    with engine.begin() as conn:
        conn.execute(table.insert().values(**other))


# -- registration rules -----------------------------------------------------
def _registration(**overrides):
    values = dict(organization_id=1, effective_from=date(2026, 1, 1),
                  health_insurer_type="HEALTH_INSURANCE_SOCIETY",
                  ei_industry_class="GENERAL", status="ACTIVE")
    values.update(overrides)
    return values


def test_kyokai_requires_a_prefecture(model_engine):
    engine, metadata = model_engine
    table = metadata.tables["payroll_jp_employer_registrations"]
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(table.insert().values(**_registration(health_insurer_type="KYOKAI_KENPO")))
    with engine.begin() as conn:
        conn.execute(table.insert().values(**_registration(health_insurer_type="KYOKAI_KENPO",
                                                          health_insurer_prefecture="13")))


def test_only_one_active_registration_row_is_allowed(model_engine):
    engine, metadata = model_engine
    table = metadata.tables["payroll_jp_employer_registrations"]
    with engine.begin() as conn:
        conn.execute(table.insert().values(**_registration()))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(table.insert().values(**_registration()))


# -- resident tax rules -----------------------------------------------------
def _resident(version):
    return dict(organization_id=1, employee_id=1, municipality_code="131016",
                fiscal_notice_year=2026, notice_id="R6-001", version=version,
                received_on=date(2026, 5, 15), first_deduction_month=date(2026, 6, 1),
                monthly_amounts={"2026-06": 1000}, total_amount=12000, source_hash="a" * 64,
                status="IMPORTED")


def test_a_change_notice_is_a_new_version_and_a_duplicate_is_rejected(model_engine):
    engine, metadata = model_engine
    table = metadata.tables["payroll_jp_resident_tax_assessments"]
    with engine.begin() as conn:
        conn.execute(table.insert().values(**_resident(1)))
        conn.execute(table.insert().values(**_resident(2)))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(table.insert().values(**_resident(2)))
