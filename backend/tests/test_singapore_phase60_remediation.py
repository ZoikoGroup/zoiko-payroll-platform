"""
tests/test_singapore_phase60_remediation.py
-------------------------------------------
Singapore Phase 6.0 — F1 / F2 / F3 remediation regressions.

  F1  payroll_employees.sgp_wp_levy_tier is String(20): every enumerated
      Singapore Work Permit value fits its column, model == migration, and
      (PostgreSQL, opt-in via P60_PG_URL) "MYS_NAS_PRC" stores, reloads and
      drives the correct Work Permit levy.
  F2  Singapore packs: the approver can never be the activator — seeded or
      edited — while the existing distinct-approver gate still holds and
      other countries keep their existing workflow (owner decision).
  F3  SG-PAYROLL-2026 ends 31 Dec 2026, so SG-PAYROLL-2027 can be activated
      after it and each wage date resolves to its own year's pack.

app.* imports are lazy (tests/_db_safety.py). Expected statutory figures are
read from the seeded pack rows, never typed here.
"""

import os
from datetime import date
from decimal import Decimal

import pytest

A, B, C = 101, 202, 303          # two/three distinct Super Admin actors


def _golden_pass(db, actor=A):
    from app.modules.payroll import service

    run = service.run_golden_test_certification(db, "SG", actor_id=actor)
    assert run.status == "PASS"
    return run


def _seed_2026(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    return pack


def _seed_both(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore, seed_singapore_2027

    p26, p27 = seed_singapore(db), seed_singapore_2027(db)
    db.commit()
    return p26, p27


def _activate(db, pack, approver=B, activator=A):
    from app.modules.payroll import service

    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=approver)
    return service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=activator)


# ══ F1 — Work Permit levy tier column length ═══════════════════════════════

def test_f1_every_enumerated_sg_work_permit_value_fits_its_column():
    from app.modules.payroll.employee_validation import SGEmployeeValidation
    from app.modules.payroll.engine.countries.singapore import WP_SKILLS, WP_TIERS_BY_SECTOR
    from app.modules.payroll.models import PayrollEmployee

    cols = PayrollEmployee.__table__.c
    values = {
        "sgp_wp_levy_tier": set(SGEmployeeValidation.FIELD_SPECS["wp_levy_tier"]["choices"])
                            | {t for tiers in WP_TIERS_BY_SECTOR.values() for t in tiers},
        "sgp_wp_sector": set(SGEmployeeValidation.FIELD_SPECS["wp_sector"]["choices"]) | set(WP_TIERS_BY_SECTOR),
        "sgp_wp_skill_level": set(SGEmployeeValidation.FIELD_SPECS["wp_skill_level"]["choices"]) | set(WP_SKILLS),
    }
    for column, allowed in values.items():
        limit = cols[column].type.length
        too_long = sorted(v for v in allowed if len(v) > limit)
        assert not too_long, (column, limit, too_long)
    assert "MYS_NAS_PRC" in values["sgp_wp_levy_tier"] and cols["sgp_wp_levy_tier"].type.length >= 11


def test_f1_seeded_work_permit_levy_tiers_fit_the_employee_column():
    from app.modules.payroll.models import PayrollEmployee
    from scripts.seed_singapore_canonical_pack import WP_LEVY

    limit = PayrollEmployee.__table__.c.sgp_wp_levy_tier.type.length
    assert all(len(tier) <= limit for _sector, tier, *_rest in WP_LEVY)


def test_f1_migration_declares_the_same_length_as_the_model():
    import importlib.util
    from pathlib import Path

    from app.modules.payroll.models import PayrollEmployee

    path = next(Path(__file__).resolve().parents[1].glob("alembic/versions/a7c2e9f4b1d6_*.py"))
    spec = importlib.util.spec_from_file_location("mig_a7c2e9f4b1d6", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    model = {c.name: c.type.length for c in PayrollEmployee.__table__.columns if c.name.startswith("sgp_wp_")}
    assert dict(mod._COLUMNS) == model


_PG_URL = os.environ.get("P60_PG_URL", "")


@pytest.mark.skipif(not _PG_URL, reason="PostgreSQL verification: set P60_PG_URL to a THROWAWAY 127.0.0.1 p60_* database")
def test_f1_postgresql_stores_mys_nas_prc_and_levies_it(monkeypatch):
    """Real PostgreSQL (String lengths enforced): store, reload and pay a
    construction MYS/NAS/PRC Work Permit holder."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    assert "127.0.0.1" in _PG_URL and "/p60_" in _PG_URL, "refusing a non-throwaway database"
    import app.core.code_generation as codegen
    import app.modules.auth.models  # noqa: F401
    import app.modules.billing.models  # noqa: F401
    import app.modules.organizations.models  # noqa: F401
    from app.database import Base
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service
    from app.modules.payroll.engine.countries.singapore import work_permit_levy_key
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem

    engine = create_engine(_PG_URL)
    # A FRESH throwaway database is expected (the caller creates and drops it;
    # users <-> organizations FKs are circular, so drop_all cannot order them).
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    counter = {"n": 0}

    def _codes(db_, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 100
        return f"P60{prefix}{counter['n']:07d}"
    monkeypatch.setattr(codegen, "generate_business_code", _codes)
    try:
        width = db.execute(text("SELECT character_maximum_length FROM information_schema.columns "
                                "WHERE table_name='payroll_employees' AND column_name='sgp_wp_levy_tier'")).scalar()
        assert width == 20
        from app.core.security import hash_password
        from app.modules.auth.models import User, UserRole

        admins = [User(email=f"p60.{n}@test.local", hashed_password=hash_password("Throwaway-Only-1!"), role=UserRole.SUPER_ADMIN,
                       first_name=n, last_name="P60", phone="", is_active=True) for n in ("maker", "checker")]
        db.add_all(admins)
        db.commit()                                                     # PostgreSQL enforces the users FKs
        maker, checker = (u.id for u in admins)
        pack = _seed_2026(db)
        _golden_pass(db, actor=maker)
        _activate(db, pack, approver=checker, activator=maker)
        org = Organization(organization_name="P60 PG", organization_code="P60PG")
        db.add(org)
        db.commit()
        db.add(CompanyComplianceDetails(organization_id=org.id, jurisdiction_country="SG", active_pack_id=pack.id))
        emp = PayrollEmployee(organization_id=org.id, employee_code="WPMYS", name="WP MYS", country_code="SG",
                              ctc=Decimal("21600"), basic=Decimal("21600"), hra=Decimal("0"), date_of_birth=date(1990, 5, 1),
                              date_of_joining=date(2025, 1, 1), sgp_cpf_residency_status="FOREIGN",
                              sgp_work_pass_type="WORK_PERMIT", sgp_work_pass_issue_date=date(2025, 1, 1),
                              sgp_work_pass_end_date=date(2027, 12, 31), sgp_wp_sector="CONSTRUCTION",
                              sgp_wp_levy_tier="MYS_NAS_PRC", sgp_wp_skill_level="R1", sgp_shg_funds="NONE",
                              compliance_fields={"nric_fin": "G1234500K"})
        db.add(emp)
        db.commit()
        emp_id = emp.id
        db.expire_all()
        assert db.get(PayrollEmployee, emp_id).sgp_wp_levy_tier == "MYS_NAS_PRC"          # no truncation
        run = PayrollRun(organization_id=org.id, period_label="Jan 2026", period_start=date(2026, 1, 1),
                         period_end=date(2026, 1, 31), pay_date=date(2026, 1, 31))
        db.add(run)
        db.commit()
        service.generate_payslips_for_run(db, run, org.id)
        db.commit()
        item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
        rates = service._sg_active_pack_and_rates(db, date(2026, 1, 31))[1]
        assert item.employer_eht == rates[work_permit_levy_key("CONSTRUCTION", "MYS_NAS_PRC", "R1")].flat_amount
        assert item.employee_pension == 0                                                   # foreigner: no CPF
    finally:
        db.close()
        engine.dispose()


# ══ F2 — approver != activator (Singapore) ════════════════════════════════

def test_f2a_seeded_pack_same_approver_and_activator_is_refused(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _seed_2026(db)
    assert pack.updated_by_id is None                                  # seeded: no human editor
    _golden_pass(db)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=A)
    with pytest.raises(BadRequestException, match="cannot also activate"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A)
    db.refresh(pack)
    assert pack.status == "Approved"


def test_f2b_seeded_pack_distinct_approver_and_activator_is_allowed(db):
    pack = _seed_2026(db)
    _golden_pass(db)
    assert _activate(db, pack, approver=B, activator=A).status == "Active"


def test_f2c_edited_pack_same_approver_and_activator_is_refused(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _seed_2026(db)
    _golden_pass(db)
    service.set_jurisdiction_pack_status(db, pack.id, "In Review", actor_id=A)      # a human edit: updated_by = A
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)
    with pytest.raises(BadRequestException, match="cannot also activate"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=B)
    assert service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=C).status == "Active"   # a third admin


def test_f2d_normal_two_person_workflow_is_allowed_and_audited(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit

    pack = _seed_2026(db)
    _golden_pass(db)
    service.set_jurisdiction_pack_status(db, pack.id, "In Review", actor_id=A)      # maker
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)                  # checker approves
    active = service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A)   # maker activates
    assert (active.status, active.approved_by_id) == ("Active", B)
    rows = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack",
                                                   TaxConfigurationAudit.entity_id == pack.id)
            .order_by(TaxConfigurationAudit.id).all())
    approve = [r for r in rows if (r.new_value or {}).get("approved_by_id") == B]
    activation = [r for r in rows if r.action == "status_change" and (r.new_value or {}).get("status") == "Active"]
    assert approve and approve[-1].actor_id == B
    assert len(activation) == 1 and activation[0].actor_id == A and activation[0].tax_version == pack.version


def test_f2e_self_approval_is_still_refused(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _seed_2026(db)
    _golden_pass(db)
    service.set_jurisdiction_pack_status(db, pack.id, "In Review", actor_id=A)
    with pytest.raises(BadRequestException, match="cannot approve"):               # Phase 6.5: refused at Approve
        service.set_jurisdiction_pack_approver(db, pack.id, actor_id=A)             # the submitter approves itself
    db.refresh(pack)
    assert pack.approved_by_id is None
    for actor in (A, C):
        with pytest.raises(BadRequestException, match="distinct approver"):
            service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=actor)


def test_f2_other_countries_keep_checker_activation(db):
    """Owner decision (2026-09-28): F2 is Singapore-only — a non-SG pack's
    checker may still approve and activate (existing workflow)."""
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id="TT-P60-PROBE", jurisdiction_country="TT", version="1.0", pack_type="tax",
                            status="Draft", effective_from=date(2026, 1, 1), updated_by_id=A)
    db.add(pack)
    db.commit()
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)
    assert service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=B).status == "Active"


def test_f2_opt_in_is_singapore_only():
    from app.modules.payroll.service import _APPROVER_NOT_ACTIVATOR_COUNTRIES

    assert _APPROVER_NOT_ACTIVATOR_COUNTRIES == ("SG",)


# ══ F3 — 2026 / 2027 pack effective periods ════════════════════════════════

def test_f3_seeded_windows_do_not_overlap(db):
    p26, p27 = _seed_both(db)
    assert (p26.effective_from, p26.effective_to) == (date(2026, 1, 1), date(2026, 12, 31))
    assert (p27.effective_from, p27.effective_to) == (date(2027, 1, 1), None)
    assert p26.effective_to < p27.effective_from
    assert (p26.pack_id, p26.version, p26.status) == ("SG-PAYROLL-2026", "1.2", "Draft")     # nothing activated


def test_f3_2026_then_2027_packs_both_activate_and_resolve_by_date(db):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    p26, p27 = _seed_both(db)
    _golden_pass(db)
    assert _activate(db, p26).status == "Active"
    assert _activate(db, p27).status == "Active"                     # refused before F3 (open-ended 2026 overlap)
    for day, expected in ((date(2026, 6, 30), p26), (date(2026, 12, 31), p26), (date(2027, 1, 1), p27),
                          (date(2027, 6, 30), p27)):
        assert resolve_tax_configuration(db, "SG", payroll_date=day)[2].id == expected.id, day


def test_f3_payroll_in_each_year_uses_its_own_pack(db, organization, monkeypatch):
    import app.core.code_generation as codegen
    from app.modules.payroll import service
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem

    counter = {"n": 0}

    def _codes(db_, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 100
        return f"P60{prefix}{counter['n']:07d}"
    monkeypatch.setattr(codegen, "generate_business_code", _codes)
    p26, p27 = _seed_both(db)
    _golden_pass(db)
    _activate(db, p26)
    _activate(db, p27)
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="SG", active_pack_id=p26.id))
    db.add(PayrollEmployee(organization_id=organization.id, employee_code="YR", name="Year Split", country_code="SG",
                           ctc=Decimal("72000"), basic=Decimal("72000"), hra=Decimal("0"), date_of_birth=date(1986, 3, 15),
                           date_of_joining=date(2025, 1, 1), sgp_cpf_residency_status="SC", sgp_work_pass_type="NONE",
                           sgp_shg_funds="NONE", compliance_fields={"nric_fin": "S1234567D"}))
    db.commit()
    versions = {}
    for pay_date in (date(2026, 12, 31), date(2027, 1, 31)):
        run = PayrollRun(organization_id=organization.id, period_label=str(pay_date), period_start=pay_date.replace(day=1),
                         period_end=pay_date, pay_date=pay_date)
        db.add(run)
        db.commit()
        service.generate_payslips_for_run(db, run, organization.id)
        db.commit()
        item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
        versions[pay_date.year] = ((item.sgp_calculation_trace or {}).get("pack") or {}, item.tax_policy_version)
    assert p26.version in str(versions[2026][1]) and p27.version in str(versions[2027][1])
    assert versions[2026] != versions[2027]


def test_f3_active_pack_protections_still_hold(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack

    p26, p27 = _seed_both(db)
    _golden_pass(db)
    _activate(db, p26)
    _activate(db, p27)
    with pytest.raises(BadRequestException, match="supersede it with a new version"):
        service.set_jurisdiction_pack_status(db, p26.id, "Draft", actor_id=A)
    overlapping = JurisdictionPack(pack_id="SG-PAYROLL-2026-OVERLAP", jurisdiction_country="SG", version="1.0",
                                   pack_type="tax", status="Draft", effective_from=date(2026, 6, 1), effective_to=None,
                                   source_document_id=p26.source_document_id, updated_by_id=A)
    db.add(overlapping)
    db.commit()
    service.set_jurisdiction_pack_approver(db, overlapping.id, actor_id=B)
    with pytest.raises(BadRequestException, match="already Active"):
        service.set_jurisdiction_pack_status(db, overlapping.id, "Active", actor_id=C)
