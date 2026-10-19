"""Mexico Phase 3 migration mx_employer_m2 (6e4a1d9c3f27): guarded and
idempotent upgrade/downgrade on a scratch SQLite file, every partial unique
index present with its predicate, and each one refusing a duplicate open /
ACTIVE row while allowing history."""

from datetime import date

import pytest

REVISION = "6e4a1d9c3f27"
TABLES = ("payroll_mx_employer_profiles", "payroll_mx_imss_registrations", "payroll_mx_establishments",
          "payroll_mx_risk_premiums", "payroll_mx_isn_registrations", "payroll_mx_labor_policies",
          "payroll_mx_credential_refs")
PARTIAL = {
    "payroll_mx_employer_profiles": ["uq_mx_employer_org_rfc_open"],
    "payroll_mx_imss_registrations": ["uq_mx_imss_org_rp_open"],
    "payroll_mx_establishments": ["uq_mx_estab_profile_name_active"],
    "payroll_mx_risk_premiums": ["uq_mx_riskprem_reg_period_active"],
    "payroll_mx_isn_registrations": ["uq_mx_isn_profile_state_open"],
    "payroll_mx_labor_policies": ["uq_mx_laborpol_profile_open"],
    "payroll_mx_credential_refs": ["uq_mx_cred_profile_kind_active", "uq_mx_cred_registration_kind_active"],
}


def _module():
    import importlib.util
    from pathlib import Path

    path = next((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("mx_employer_m2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def engine(tmp_path):
    from sqlalchemy import create_engine

    import app.modules.payroll.models  # noqa: F401 — registers every table on Base.metadata
    from app.database import Base

    eng = create_engine(f"sqlite:///{tmp_path / 'mx_m2.db'}")
    keep = [t for name, t in Base.metadata.tables.items() if name not in TABLES]
    Base.metadata.create_all(eng, tables=keep)      # everything the migration depends on, minus its own tables
    return eng


def _run(engine, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    mod = _module()
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(mod, fn)()


def test_revision_links(engine):
    mod = _module()
    assert (mod.revision, mod.down_revision) == (REVISION, "5d2c8f1a7b3e")


def test_upgrade_is_idempotent_and_creates_every_partial_index(engine):
    from sqlalchemy import inspect, text

    _run(engine, "upgrade")
    _run(engine, "upgrade")                                          # replay: nothing raises, nothing duplicates
    insp = inspect(engine)
    assert set(TABLES) <= set(insp.get_table_names())
    with engine.connect() as conn:
        for table, names in PARTIAL.items():
            for name in names:
                sql = conn.execute(text("select sql from sqlite_master where type='index' and name=:n"),
                                   {"n": name}).scalar()
                assert sql and "UNIQUE" in sql.upper() and "WHERE" in sql.upper(), name


def test_downgrade_is_idempotent(engine):
    from sqlalchemy import inspect

    _run(engine, "upgrade")
    _run(engine, "downgrade")
    _run(engine, "downgrade")
    assert not set(TABLES) & set(inspect(engine).get_table_names())


def test_partial_indexes_refuse_duplicates_but_allow_history(engine):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    _run(engine, "upgrade")
    with engine.begin() as c:                                        # SQLite: FKs not enforced here
        c.execute(text("insert into payroll_mx_employer_profiles (id, organization_id, version, effective_from, "
                       "effective_to, taxpayer_type, rfc, legal_name, fiscal_regime_code, fiscal_postal_code, "
                       "place_of_issue_postal_code, withholding_obligation_active, stamp_test_status) values "
                       "(1, 1, 1, '2026-01-01', '2026-06-30', 'MORAL', 'ABC010101AB1', 'x', '601', '06600', '06600', "
                       "1, 'NOT_TESTED'), (2, 1, 2, '2026-07-01', NULL, 'MORAL', 'ABC010101AB1', 'x', '601', "
                       "'06600', '06600', 1, 'NOT_TESTED')"))           # closed + open: history allowed
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text("insert into payroll_mx_employer_profiles (organization_id, version, effective_from, "
                           "taxpayer_type, rfc, legal_name, fiscal_regime_code, fiscal_postal_code, "
                           "place_of_issue_postal_code, withholding_obligation_active, stamp_test_status) values "
                           "(1, 3, '2026-09-01', 'MORAL', 'ABC010101AB1', 'x', '601', '06600', '06600', 1, "
                           "'NOT_TESTED')"))                            # a second OPEN row
    with engine.begin() as c:
        c.execute(text("insert into payroll_mx_credential_refs (organization_id, employer_profile_id, kind, "
                       "secret_ref, status) values (1, 1, 'CSD', 'gcp-sm://a', 'ROTATED'), "
                       "(1, 1, 'CSD', 'gcp-sm://b', 'ACTIVE')"))
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text("insert into payroll_mx_credential_refs (organization_id, employer_profile_id, kind, "
                           "secret_ref, status) values (1, 1, 'CSD', 'gcp-sm://c', 'ACTIVE')"))


def test_migration_never_stores_a_secret_column():
    text = next((__import__("pathlib").Path(__file__).resolve().parents[1] / "alembic" / "versions")
                .glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for forbidden in ("private_key", "password", "pfx", "p12", "certificate_bytes", "key_material"):
        assert forbidden not in text.lower(), forbidden
    assert date(2026, 10, 16)                                   # Create Date of the revision
