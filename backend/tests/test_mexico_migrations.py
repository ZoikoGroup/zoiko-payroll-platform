"""Mexico (ZP-MX-ENG-001) migrations — linear chain, every op guarded,
model <-> migration parity for payroll_mx_*, partial unique indexes present,
upgrade twice is a no-op, downgrade removes only Mexico's tables."""

import ast
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MX_CHAIN = [("5d2c8f1a7b3e", "f4b8d2a6c9e1"), ("6e4a1d9c3f27", "5d2c8f1a7b3e"), ("8b2f6d4e1a93", "6e4a1d9c3f27")]
MX_TABLES = {"payroll_mx_earning_classifications", "payroll_mx_cfdi_schema_releases", "payroll_mx_cfdi_catalog_entries"}
# Phase 3 (mx_employer_m2) — tested in detail by test_mexico_employer_migrations.py
MX_M2_TABLES = {"payroll_mx_employer_profiles", "payroll_mx_imss_registrations", "payroll_mx_establishments",
                "payroll_mx_risk_premiums", "payroll_mx_isn_registrations", "payroll_mx_labor_policies",
                "payroll_mx_credential_refs"}
MX_M3_TABLES = {"payroll_mx_infonavit_notices"}   # + mx_* columns on the shared profile table
MX_M4_TABLES = {"payroll_mx_preflight_exceptions", "payroll_mx_imss_branch_lines", "payroll_mx_isn_liabilities",
                "payroll_mx_sbc_history", "payroll_mx_variable_accumulators", "payroll_mx_benefit_accruals",
                "payroll_mx_approved_hours"}   # Phase 6 mx_run_m4 (tests/test_mexico_run_migrations.py)
MX_M5_TABLES = {"payroll_mx_cfdi_documents", "payroll_mx_cfdi_outbox_items", "payroll_mx_cfdi_events"}   # Phase 7
MX_M6_TABLES = {"payroll_mx_imss_movements", "payroll_mx_authority_liabilities",   # Phase 8
                "payroll_mx_authority_liability_sources", "payroll_mx_sua_periods", "payroll_mx_sua_differences",
                "payroll_mx_isn_returns", "payroll_mx_authority_events"}
MX_M7_TABLES = {"payroll_mx_run_corrections"}   # Phase 9a
MX_M8_TABLES = {"payroll_mx_vacation_records"}   # Phase 9b
MX_M9_TABLES = {"payroll_mx_terminations"}       # Phase 9c
MX_M10_TABLES = {"payroll_mx_ptu_cycles", "payroll_mx_ptu_allocations"}   # Phase 9d
MX_M11_TABLES = {"payroll_mx_annual_isr_adjustments"}                       # Phase 9e
MX_M12_TABLES = {"payroll_mx_payment_batches", "payroll_mx_payment_items"}   # Phase 10a
MX_M13_TABLES = {"payroll_mx_journal_mappings", "payroll_mx_journal_exports"}   # Phase 10b
MX_M14_TABLES = {"payroll_mx_pilot_grants", "payroll_mx_master_copies"}         # Phase 10e
MX_M15_TABLES = {"payroll_mx_master_releases"}                                  # Phase 10f


def _path(rev):
    return next(_VERSIONS.glob(f"{rev}_*.py"))


def _load(rev):
    spec = importlib.util.spec_from_file_location(f"_mx_mig_{rev}", _path(rev))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mx_chain_is_linear():
    for rev, down in MX_CHAIN:
        module = _load(rev)
        assert (module.revision, module.down_revision) == (rev, down)


@pytest.mark.parametrize("rev,tables", [("5d2c8f1a7b3e", MX_TABLES), ("6e4a1d9c3f27", MX_M2_TABLES), ("8b2f6d4e1a93", MX_M3_TABLES)])
def test_every_create_is_guarded_and_literal(rev, tables):
    text = _path(rev).read_text(encoding="utf-8")
    tree = ast.parse(text)
    created = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "create_table"
                and isinstance(node.args[0], ast.Constant)):
            created.add(node.args[0].value)
    assert created == tables
    for table in tables:
        assert f'if not _has_table("{table}"):' in text


def test_models_and_migration_define_the_same_mexico_tables():
    from app.database import Base
    import app.modules.payroll.models  # noqa: F401

    model_tables = {t for t in Base.metadata.tables if t.startswith("payroll_mx_")}
    assert model_tables == MX_TABLES | MX_M2_TABLES | MX_M3_TABLES | MX_M4_TABLES | MX_M5_TABLES | MX_M6_TABLES | MX_M7_TABLES | MX_M8_TABLES | MX_M9_TABLES | MX_M10_TABLES | MX_M11_TABLES | MX_M12_TABLES | MX_M13_TABLES | MX_M14_TABLES | MX_M15_TABLES


@pytest.fixture()
def engine():
    """Every non-Mexico table from the models, so the migration's FK targets
    exist; the Mexico tables are left for the migration to create."""
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    import app.modules.auth.models  # noqa: F401
    import app.modules.billing.models  # noqa: F401
    import app.modules.communications.models  # noqa: F401
    import app.modules.organizations.models  # noqa: F401
    import app.modules.payroll.models  # noqa: F401

    eng = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[t for name, t in Base.metadata.tables.items() if name not in MX_TABLES])
    return eng


def _run(engine, fn_name):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module = _load("5d2c8f1a7b3e")
    with engine.begin() as conn:
        module.op = Operations(MigrationContext.configure(conn))
        getattr(module, fn_name)()


def test_upgrade_twice_then_downgrade(engine):
    before = set(sa.inspect(engine).get_table_names())
    _run(engine, "upgrade")
    _run(engine, "upgrade")                                        # idempotent re-run
    insp = sa.inspect(engine)
    assert MX_TABLES <= set(insp.get_table_names())
    indexes = {i["name"]: i for i in insp.get_indexes("payroll_mx_earning_classifications")}
    assert indexes["uq_mx_earn_canonical_code_eff"]["unique"] and indexes["uq_mx_earn_org_code_eff"]["unique"]
    _run(engine, "downgrade")
    assert set(sa.inspect(engine).get_table_names()) == before


def test_the_migrated_partial_index_refuses_a_duplicate_canonical_row(engine):
    _run(engine, "upgrade")
    insert = sa.text(
        "INSERT INTO payroll_mx_earning_classifications (organization_id, earning_code, label, version, effective_from,"
        " isr_treatment, sbc_treatment, infonavit_included, isn_default_included, ptu_wage_base_included,"
        " cfdi_node_type, status, sha256) VALUES (NULL, 'SUELDO', 'x', :v, '2026-01-01', 'TAXABLE', 'FIXED', 1, 1, 1,"
        " 'PERCEPCION', 'DRAFT', 'h')")
    with engine.begin() as conn:
        conn.execute(insert, {"v": 1})
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert, {"v": 2})
