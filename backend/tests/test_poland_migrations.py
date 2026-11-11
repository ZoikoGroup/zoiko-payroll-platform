"""Poland foundation migration 1ee3bbde33bb (ZP-PL-ENG-001 Phase 2).

Proves, without a PostgreSQL server:
  * the row-level-security policy the revision applies to each new table is the
    one d7f9b1c3e5a6's classify() derives from the model schema — TENANT for
    employer registrations, WORKER/"org" for the six worker tables;
  * the tables the migration creates have exactly the model's columns, and the
    two shared columns exist on the models and are added literally;
  * it is additive and idempotent: replaying it over the full model schema is a
    no-op, and downgrade removes only its own objects;
  * the deploy drift filter explains every Poland object;
  * no statutory number is a CHECK constraint;
  * the vault, employer, worker-profile, declaration, PPK and ledger rules
    (evidence, four-eyes, fail-closed coverage) are enforced by the database.
"""
import importlib.util
import re
from datetime import date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.pool import StaticPool

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
REVISION = "1ee3bbde33bb"
PARENT = "a8cde2482ef0"

TENANT = ("payroll_pl_employer_registrations",)
WORKER = (
    "payroll_pl_identifier_vault",
    "payroll_pl_identifier_access_events",
    "payroll_pl_worker_profiles",
    "payroll_pl_declarations",
    "payroll_pl_ppk_participations",
    "payroll_pl_accumulator_entries",
)
NEW_TABLES = TENANT + WORKER
SHARED = {"payslip_items": {"pl_calculation_snapshot"}, "payroll_runs": {"pl_approval_fingerprint"}}


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


def _indexes(engine, table):
    return {i["name"] for i in sa.inspect(engine).get_indexes(table)}


def test_new_tables_match_the_models_exactly(model_engine):
    engine, metadata = model_engine
    model_indexes = {t: _indexes(engine, t) for t in NEW_TABLES}
    with engine.begin() as conn:
        for table in _load()._TABLES:
            conn.execute(sa.text(f'DROP TABLE "{table}"'))
    _run(engine, "upgrade")
    for table in NEW_TABLES:
        assert _cols(engine, table) == {c.name for c in metadata.tables[table].columns}, table
        assert model_indexes[table] <= _indexes(engine, table), table


def test_shared_columns_exist_on_the_models_and_are_added_literally():
    metadata = _metadata()
    for table, columns in SHARED.items():
        assert columns <= {c.name for c in metadata.tables[table].columns}, table
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    assert 'op.add_column("payslip_items", sa.Column("pl_calculation_snapshot"' in text
    assert 'op.add_column("payroll_runs", sa.Column("pl_approval_fingerprint"' in text


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
    for table, columns in SHARED.items():
        assert not columns & _cols(engine, table)
    assert {"nz_calculation_snapshot", "za_calculation_snapshot"} <= _cols(engine, "payslip_items")  # neighbours
    assert {"nz_approval_fingerprint", "za_approval_fingerprint"} <= _cols(engine, "payroll_runs")
    _run(engine, "upgrade")
    assert set(NEW_TABLES) <= set(sa.inspect(engine).get_table_names())
    for table, columns in SHARED.items():
        assert columns <= _cols(engine, table)


def test_deploy_drift_filter_explains_every_pl_object():
    import os

    from scripts.drift_pending_filter import pending_objects

    here = os.getcwd()
    os.chdir(VERSIONS.parents[1])
    try:
        tables, columns = pending_objects(PARENT)
    finally:
        os.chdir(here)
    # Poland P6 (e11c2c36df17) is pending on the same chain.
    assert tables == set(NEW_TABLES) | {"payroll_pl_incapacity_episodes", "payroll_pl_filings",  # P6, P8
                                        "payroll_pl_settlements", "payroll_pl_reconciliation_variances",
                                        "payroll_pl_parallel_imports", "payroll_pl_parallel_differences",  # P9
                                        "payroll_payslip_templates", "payroll_payslip_template_versions",
                                        "payroll_payslip_template_assignments"}  # + payslip templates (f3a9c1d7e2b4)
    assert columns == {**SHARED, "payslip_items": SHARED["payslip_items"] | {"template_version_id"}}


def test_revision_is_the_single_child_of_the_previous_head():
    module = _load()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)
    children = [p.name for p in VERSIONS.glob("*.py")
                if re.search(rf'down_revision[^\n]*"{PARENT}"', p.read_text(encoding="utf-8"))]
    assert children == [f"{REVISION}_pl_foundation.py"]


def test_create_table_names_are_literal_in_the_migration():
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'op.create_table(\n            "{table}"' in text, table


def test_migration_is_listed_in_the_manifest():
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert f"{REVISION}_pl_foundation.py|{REVISION}|{PARENT}|" in manifest


def test_no_statutory_number_is_a_check_constraint():
    """Spec production safety rule: CHECKs hold enumerations, evidence and date
    order only — never a rate, threshold, cap or wage floor."""
    text = next(VERSIONS.glob(f"{REVISION}_*.py")).read_text(encoding="utf-8")
    checks = re.findall(r'CheckConstraint\((.*?)name=', text, re.S)
    assert checks
    for body in checks:
        assert not re.search(r"\d+\.\d+|\b(?:4806|282600|120000|10800|3600|9\.76|2\.45|1\.5)\b", body), body
        # Only 0 and the 6-character title-code length may appear as bare numbers.
        assert set(re.findall(r"\b\d+\b", body)) <= {"0", "6"}, body


def test_vocabularies_match_the_content_module():
    from app.modules.payroll import models
    from app.modules.payroll.engine.countries import poland_content as content

    module = _load()
    assert module.DECLARATION_TYPES == content.DECLARATION_TYPES == models._PL_DECLARATION_TYPES
    assert module.PPK_STATES == content.PPK_STATES == models._PL_PPK_STATES
    assert module.CONTRACT_TYPES == content.CONTRACT_TYPES_SUPPORTED + content.CONTRACT_TYPES_BLOCKED
    assert module.CONTRACT_TYPES == models._PL_CONTRACT_TYPES
    assert module.ACCUMULATORS == models._PL_ACCUMULATORS == content.ACCUMULATORS
    reliefs = {a.replace("PIT0_EXEMPT_", "PIT0_") for a in module.ACCUMULATORS if a.startswith("PIT0_EXEMPT_")}
    assert reliefs == set(content.PIT0_RELIEFS)


# -- database rules ---------------------------------------------------------
def _insert(engine, metadata, table, **values):
    with engine.begin() as conn:
        conn.execute(metadata.tables[table].insert().values(**values))


def _rejects(engine, metadata, table, **values):
    with pytest.raises(sa.exc.IntegrityError):
        _insert(engine, metadata, table, **values)


_VAULT = dict(organization_id=1, employee_id=1, subject_type="EMPLOYEE", identifier_type="PESEL",
              ciphertext="ciphertext", key_version=1, fingerprint="f" * 64, collected_at=datetime(2026, 11, 5),
              status="ACTIVE")


def test_the_vault_has_no_plaintext_like_column():
    names = {c.name.lower() for c in _metadata().tables["payroll_pl_identifier_vault"].columns}
    for forbidden in ("pesel", "nip", "nrs", "number", "plaintext", "value", "last4", "digits", "iban"):
        assert forbidden not in names


def test_the_vault_requires_ciphertext_unless_deleted(model_engine):
    engine, metadata = model_engine
    _rejects(engine, metadata, "payroll_pl_identifier_vault", **dict(_VAULT, ciphertext=None))
    _insert(engine, metadata, "payroll_pl_identifier_vault", **_VAULT)


def test_the_vault_subject_matches_its_identifier(model_engine):
    engine, metadata = model_engine
    t = "payroll_pl_identifier_vault"
    _rejects(engine, metadata, t, **dict(_VAULT, employee_id=None))
    _rejects(engine, metadata, t, **dict(_VAULT, identifier_type="NRS"))                   # NRS is employer-only
    _rejects(engine, metadata, t, **dict(_VAULT, subject_type="EMPLOYER", employee_id=None))  # employer PESEL
    _insert(engine, metadata, t, **dict(_VAULT, subject_type="EMPLOYER", employee_id=None, identifier_type="NRS"))
    _insert(engine, metadata, t, **dict(_VAULT, identifier_type="NIP", fingerprint="a" * 64))


def test_the_vault_allows_one_active_identifier_per_type_and_no_duplicates(model_engine):
    engine, metadata = model_engine
    t = "payroll_pl_identifier_vault"
    _insert(engine, metadata, t, **_VAULT)
    _rejects(engine, metadata, t, **dict(_VAULT, fingerprint="e" * 64))          # second active PESEL
    _rejects(engine, metadata, t, **dict(_VAULT, employee_id=2))                 # same PESEL, other employee
    _insert(engine, metadata, t, **dict(_VAULT, employee_id=2, fingerprint="e" * 64))
    _insert(engine, metadata, t, **dict(_VAULT, status="DELETED"))               # history kept


def _employer(**overrides):
    values = dict(organization_id=1, effective_from=date(2026, 1, 1), legal_name="Spółka Testowa sp. z o.o.",
                  nip="1234563218", zus_deadline_class="DAY_15", status="DRAFT")
    values.update(overrides)
    return values


def test_employer_registration_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_pl_employer_registrations"
    _rejects(engine, metadata, t, **_employer(zus_deadline_class="DAY_10"))
    # An accident rate needs its source, contribution-year window and evidence.
    _rejects(engine, metadata, t, **_employer(accident_rate_pct=1))
    _rejects(engine, metadata, t, **_employer(accident_rate_pct=1, accident_rate_source="ZUS_NOTICE"))
    _rejects(engine, metadata, t, **_employer(accident_rate_pct=1, accident_rate_source="GUESS",
                                              accident_rate_from=date(2026, 4, 1), accident_rate_evidence_ref="x"))
    _insert(engine, metadata, t, **_employer(accident_rate_pct=1, accident_rate_source="ZUS_NOTICE",
                                             accident_rate_from=date(2026, 4, 1),
                                             accident_rate_to=date(2027, 3, 31), accident_rate_evidence_ref="notice"))
    # ACTIVE needs a different approver; one ACTIVE open row per legal employer.
    _rejects(engine, metadata, t, **_employer(status="ACTIVE"))
    _rejects(engine, metadata, t, **_employer(status="ACTIVE", created_by_id=7, approved_by_id=7))
    _insert(engine, metadata, t, **_employer(status="ACTIVE", created_by_id=7, approved_by_id=8))
    _rejects(engine, metadata, t, **_employer(status="ACTIVE", created_by_id=7, approved_by_id=8))
    _insert(engine, metadata, t, **_employer(status="SUPERSEDED"))


def _profile(**overrides):
    values = dict(organization_id=1, employee_id=1, effective_from=date(2026, 1, 1), contract_type="UMOWA_O_PRACE",
                  status="DRAFT")
    values.update(overrides)
    return values


def test_worker_profile_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_pl_worker_profiles"
    _insert(engine, metadata, t, **_profile())                                   # coverage unknown is storable
    _rejects(engine, metadata, t, **_profile(contract_type="B2B"))
    _rejects(engine, metadata, t, **_profile(insurance_title_code="0110"))
    _rejects(engine, metadata, t, **_profile(fte_numerator=1))
    _rejects(engine, metadata, t, **_profile(fte_numerator=3, fte_denominator=2))
    _rejects(engine, metadata, t, **_profile(other_titles_declared=True))         # needs evidence
    _rejects(engine, metadata, t, **_profile(fep_qualifying=True))                # PL-012: needs evidence
    _rejects(engine, metadata, t, **_profile(fund_exemption_code="AGE"))          # named exemption needs evidence
    _insert(engine, metadata, t, **_profile(insurance_title_code="011000", fte_numerator=1, fte_denominator=2,
                                            other_titles_declared=True, other_titles_evidence_ref="decl",
                                            fep_qualifying=True, fep_evidence_ref="job", fep_from=date(2026, 1, 1)))


def _declaration(**overrides):
    values = dict(organization_id=1, employee_id=1, effective_from=date(2026, 1, 1), declaration_type="PIT2",
                  received_at=datetime(2025, 12, 20), source_channel="PAPER", evidence_ref="scan-1",
                  status="RECEIVED")
    values.update(overrides)
    return values


def test_declaration_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_pl_declarations"
    _insert(engine, metadata, t, **_declaration())
    _rejects(engine, metadata, t, **_declaration(evidence_ref=None))             # PL-005
    _rejects(engine, metadata, t, **_declaration(declaration_type="PIT3"))
    _rejects(engine, metadata, t, **_declaration(source_channel="EMAIL"))
    _rejects(engine, metadata, t, **_declaration(status="APPROVED", created_by_id=3, approved_by_id=3))
    _insert(engine, metadata, t, **_declaration(status="APPROVED", created_by_id=3, approved_by_id=4))
    _rejects(engine, metadata, t, **_declaration(status="WITHDRAWN"))
    _rejects(engine, metadata, t, **_declaration(status="SUPERSEDED"))
    _rejects(engine, metadata, t, **_declaration(effective_to=date(2025, 12, 31)))


def test_ppk_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_pl_ppk_participations"
    base = dict(organization_id=1, employee_id=1, effective_from=date(2026, 1, 1), status="DRAFT")
    _rejects(engine, metadata, t, **dict(base, state="ENROLLED"))                # needs the enrolment date
    _rejects(engine, metadata, t, **dict(base, state="OPTED_OUT"))               # needs the declaration
    _rejects(engine, metadata, t, **dict(base, state="PAUSED"))
    _insert(engine, metadata, t, **dict(base, state="ENROLLED", enrolment_date=date(2026, 1, 1)))
    _insert(engine, metadata, t, **dict(base, state="OPTED_OUT", opt_out_declaration_id=1))


def _entry(**overrides):
    values = dict(organization_id=1, employee_id=1, year=2026, accumulator="ZUS_CAP_PENSION_BASE",
                  pay_date=date(2026, 1, 31), amount=1000, entry_kind="RUN", payslip_item_id=1)
    values.update(overrides)
    return values


def test_ledger_rules(model_engine):
    engine, metadata = model_engine
    t = "payroll_pl_accumulator_entries"
    _insert(engine, metadata, t, **_entry())
    _rejects(engine, metadata, t, **_entry())                                    # one RUN post per payslip
    _rejects(engine, metadata, t, **_entry(payslip_item_id=None))
    _rejects(engine, metadata, t, **_entry(accumulator="TAXABLE_GROSS", payslip_item_id=2))
    # PL-010: prior-employer cap evidence needs evidence + a different approver, cap accumulators only.
    prior = dict(entry_kind="PRIOR_EMPLOYER", payslip_item_id=None)
    _rejects(engine, metadata, t, **_entry(**prior))
    _rejects(engine, metadata, t, **_entry(**prior, evidence_ref="RMUA", created_by_id=5, approved_by_id=5))
    _rejects(engine, metadata, t, **_entry(**prior, accumulator="PIT_TAXABLE_INCOME", evidence_ref="RMUA",
                                           created_by_id=5, approved_by_id=6))
    _insert(engine, metadata, t, **_entry(**prior, evidence_ref="RMUA", created_by_id=5, approved_by_id=6))
    # PL-018: a correction is a linked compensating entry.
    _rejects(engine, metadata, t, **_entry(entry_kind="CORRECTION", payslip_item_id=None))
    _insert(engine, metadata, t, **_entry(entry_kind="CORRECTION", payslip_item_id=None, reverses_id=1,
                                          amount=-1000))


def test_ledger_has_no_updated_at():
    # Append-only: entries are never edited.
    assert "updated_at" not in {c.name for c in _metadata().tables["payroll_pl_accumulator_entries"].columns}
    assert "updated_at" not in {c.name for c in _metadata().tables["payroll_pl_identifier_access_events"].columns}
