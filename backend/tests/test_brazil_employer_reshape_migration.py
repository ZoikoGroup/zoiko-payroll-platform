"""BR Phase 3 migration br_employer_reshape (a6ca8aab2043).

b7a1c9e3d5f2 is on main and may already be applied, so the Phase 3 employer /
establishment shape arrives by this forward revision instead of an in-place
edit. SQLite (dev/test): build the b7a1c9e3d5f2 shape by running that revision
itself, then prove the reshape is idempotent both ways, produces the columns
and constraints the models expect, and REFUSES when either table holds a row
(dropping CPRB / certificate / RAT / FAP would otherwise lose it silently).
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION = "a6ca8aab2043"
FOUNDATION = "b7a1c9e3d5f2"
EMPLOYER = "payroll_br_employer_profiles"
ESTABLISHMENT = "payroll_br_establishments"
# Tables created after b7a1c9e3d5f2 that reference the two reshaped tables.
DEPENDANTS = ("payroll_br_credential_refs", "payroll_br_cprb_options", "payroll_br_risk_assignments",
              "payroll_br_concurrent_inss_declarations", "payroll_br_alimony_orders",
              "payroll_br_vale_transporte_elections")


def _module(revision):
    path = next((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob(f"{revision}_*.py"))
    spec = importlib.util.spec_from_file_location(f"rev_{revision}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, revision, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Operations.context(MigrationContext.configure(conn)):
        getattr(_module(revision), fn)()


def _cols(engine, table):
    return {c["name"]: c for c in sa.inspect(engine).get_columns(table)}


def _indexes(engine, table):
    return {i["name"] for i in sa.inspect(engine).get_indexes(table)}


def _checks(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_check_constraints(table)}


@pytest.fixture()
def foundation_engine(tmp_path):
    """The schema as main has it: b7a1c9e3d5f2's employer / establishment shape."""
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    eng = sa.create_engine(f"sqlite:///{tmp_path / 'reshape.db'}")
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        for table in DEPENDANTS + (ESTABLISHMENT, EMPLOYER):
            c.execute(sa.text(f"DROP TABLE {table}"))
        _run(c, FOUNDATION, "upgrade")          # recreates the two tables in the main shape
    return eng


def _seed_old_employer(engine):
    from sqlalchemy.orm import Session

    from app.modules.organizations.models import Organization

    with Session(engine) as s:
        org = Organization(organization_name="o", organization_code="RSHP")
        s.add(org)
        s.commit()
        org_id = org.id
    with engine.begin() as c:
        c.execute(sa.text(
            f"INSERT INTO {EMPLOYER} (organization_id, cnpj_root, legal_name, tax_classification, cnae_preponderant, "
            "contact_name, contact_cpf, contact_email) VALUES (:o, '12345678', 'X', '99', '6201501', 'C', "
            "'52998224725', 'c@example.com')"), {"o": org_id})


def test_revision_links():
    mod = _module(REVISION)
    assert (mod.revision, mod.down_revision) == (REVISION, "b3f7c1e9d5a2")
    assert _module("64424fd61652").down_revision == REVISION


def test_foundation_is_the_main_shape(foundation_engine):
    emp, est = _cols(foundation_engine, EMPLOYER), _cols(foundation_engine, ESTABLISHMENT)
    assert {"cprb_opted", "cprb_rate_pct", "esocial_cert_alias"} <= set(emp) and "effective_from" not in emp
    assert {"rat_pct", "fap_factor"} <= set(est) and "active_from" not in est


def test_upgrade_reaches_the_model_shape_and_is_idempotent(foundation_engine):
    from app.database import Base

    eng = foundation_engine
    for _ in range(2):
        with eng.begin() as c:
            _run(c, REVISION, "upgrade")
    for table in (EMPLOYER, ESTABLISHMENT):
        assert set(_cols(eng, table)) == {c.name for c in Base.metadata.tables[table].columns}, table
    emp, est = _cols(eng, EMPLOYER), _cols(eng, ESTABLISHMENT)
    assert not emp["effective_from"]["nullable"] and not est["organization_id"]["nullable"]
    assert not est["active_from"]["nullable"] and not est["fpas_evidence_ref"]["nullable"]
    assert {"uq_br_employer_open_version"} <= _indexes(eng, EMPLOYER)
    assert {"uq_br_establishment_active_hq", f"ix_{ESTABLISHMENT}_organization_id"} <= _indexes(eng, ESTABLISHMENT)
    assert {"ck_br_employer_status", "ck_br_employer_dates"} <= _checks(eng, EMPLOYER)
    assert {"ck_br_establishment_fpas_status", "ck_br_establishment_third_pct",
            "ck_br_establishment_dates"} <= _checks(eng, ESTABLISHMENT)
    assert not {"ck_br_establishment_rat", "ck_br_establishment_fap"} & _checks(eng, ESTABLISHMENT)
    uniques = {u["name"] for u in sa.inspect(eng).get_unique_constraints(EMPLOYER)}
    assert "uq_br_employer_org_root_version" in uniques and "uq_br_employer_org" not in uniques
    fks = {fk["name"]: fk for fk in sa.inspect(eng).get_foreign_keys(EMPLOYER)}
    assert fks["fk_br_employer_created_by"]["options"].get("ondelete") == "SET NULL"


def test_downgrade_returns_the_main_shape_and_is_idempotent(foundation_engine):
    eng = foundation_engine
    with eng.begin() as c:
        _run(c, REVISION, "upgrade")
    for _ in range(2):
        with eng.begin() as c:
            _run(c, REVISION, "downgrade")
    emp, est = _cols(eng, EMPLOYER), _cols(eng, ESTABLISHMENT)
    assert {"cprb_opted", "cprb_rate_pct", "esocial_cert_alias"} <= set(emp) and "effective_from" not in emp
    assert {"rat_pct", "fap_factor"} <= set(est) and "organization_id" not in est
    uniques = {u["name"] for u in sa.inspect(eng).get_unique_constraints(EMPLOYER)}
    assert "uq_br_employer_org" in uniques


def test_upgrade_refuses_when_a_table_holds_rows(foundation_engine):
    eng = foundation_engine
    _seed_old_employer(eng)
    with pytest.raises(RuntimeError, match="refuses"):
        with eng.begin() as c:
            _run(c, REVISION, "upgrade")
    assert "cprb_opted" in _cols(eng, EMPLOYER)                       # nothing changed
