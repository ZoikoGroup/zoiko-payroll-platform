"""
tests/test_singapore_phase610_fail_closed.py
--------------------------------------------
Singapore Phase 6.10 — defects found by the fail-closed audit, each proven
here against the pre-change behaviour:

  1. Rate source. With no Active pack, or with an org not opted into canonical
     tracking, _resolve_effective_rate_inputs fell through to the org's own
     cached ContributionRate / TaxSlab rows: SG payroll could compute from an
     ungoverned (stale or hand-written) copy while the payslip pinned the
     Active pack. SG now always uses the Active canonical pack and fails closed
     without one.
  2. apply_extracted_rate wrote org-level SG statutory rows from a document
     preview (Payroll Operator route). Refused for SG.
  3. Pack activation. The golden gate was country-scoped and ran every fixture
     against the rates embedded IN the fixture — a pack whose own rows were
     wrong could go Active on a PASS run. G1 was enforced nowhere. Activation
     (normal and hotfix path) now needs G1 accepted, the vectors re-run
     against THIS pack's rows, and a 1st-of-month start.
  4. The PWM / LQS wage-month reports substituted the pack in force today for
     payslips carrying no pinned pack. They now evaluate nothing instead.
  5. PUT /organizations/me (and the Super Admin update) set `country` with no
     gate: any organization could move itself into a PLANNED Singapore.
  6. A payroll run with only a Draft SG pack is refused and commits nothing.

app.* imports are lazy (tests/_db_safety.py). Evidence here is disposable test
data; nothing represents a real regulator or independent-reviewer artifact.
"""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

A, B = 101, 202
JUN = date(2026, 6, 30)


@pytest.fixture(autouse=True)
def _uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_BASE_DIR", str(tmp_path))


@pytest.fixture(autouse=True)
def _codes(monkeypatch):
    import app.core.code_generation as code_generation

    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _seed(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    return pack


def _employee(db, org_id, code="SG610"):
    from app.modules.payroll.models import PayrollEmployee

    emp = PayrollEmployee(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="SG",
                          ctc=D("120000"), date_of_birth=date(1986, 3, 15), sgp_cpf_residency_status="SC",
                          sgp_work_pass_type="NONE", sgp_shg_funds="NONE", compliance_fields={"nric_fin": "S1234567D"})
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _run(db, org_id, pay_date=JUN):
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=org_id, period_label=pay_date.strftime("%Y-%m"),
                     period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _org_row(db, org_id, key, **values):
    from app.modules.payroll.models import ContributionRate

    db.add(ContributionRate(organization_id=org_id, component_key=key, label=key, jurisdiction_country="SG",
                            employee_share="", employer_share="", total="", **values))
    db.commit()


def _accept(db, tag):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import SourceArtifactCreate

    art = service.create_source_artifact(db, SourceArtifactCreate(agency="Test", title=tag, formNumber=tag), actor_id=A)
    service.upload_source_artifact_file(db, art.id, f"{tag}.pdf", "application/pdf", b"test", actor_id=A)
    return service.review_sg_gate_evidence(db, art.id, "ACCEPTED", actor_id=B)


def _pack_row(db, pack, key):
    from app.modules.payroll.models import ContributionRate

    return (db.query(ContributionRate)
            .filter(ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None),
                    ContributionRate.component_key == key).one())


def _refusals(db, pack):
    from app.modules.payroll.models import TaxConfigurationAudit

    return (db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack", TaxConfigurationAudit.entity_id == pack.id,
                    TaxConfigurationAudit.action == "refused").all())


# ── 1. Rate source ──────────────────────────────────────────────────────────

def test_sg_payroll_uses_the_active_pack_even_when_the_org_is_not_opted_in(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    pack = _seed(db)
    pack.status = "Active"
    db.commit()
    # An ungoverned org-level copy that WOULD change SDL (0.25% of 10,000 = 25, capped at 99 instead of 11.25).
    _org_row(db, organization.id, "sdl", employer_rate_pct=D("0.0025"))
    _org_row(db, organization.id, "sdl_min_monthly", flat_amount=D("2"))
    _org_row(db, organization.id, "sdl_max_monthly", flat_amount=D("99"))
    assert service._org_uses_canonical_tax_pack(db, organization.id) is False          # never opted in
    rate_map, _slabs, _raw, resolved = service._resolve_effective_rate_inputs(db, organization.id, "SG", JUN, False)
    assert resolved.id == pack.id and rate_map["sdl_max_monthly"].flat_amount == D("11.25")

    emp = _employee(db, organization.id)
    run = _run(db, organization.id)
    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    assert item.employer_payroll_tax == D("11.25")                                     # the pack's cap, not the org's 99
    assert item.tax_policy_pack_id == pack.id


def test_sg_never_falls_back_to_org_rows_without_an_active_pack(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

    from app.modules.payroll.models import ContributionRate, TaxSlab

    pack = _seed(db)                                                                   # Draft only
    # A complete org-level copy of the pack (what a stale sync would leave behind) — rates AND slabs.
    for row in db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id).all():
        _org_row(db, organization.id, row.component_key, employee_rate_pct=row.employee_rate_pct,
                 employer_rate_pct=row.employer_rate_pct, flat_amount=row.flat_amount, text_value=row.text_value,
                 effective_from=row.effective_from, effective_to=row.effective_to)
    skip = {"id", "organization_id", "jurisdiction_pack_id", "created_at", "updated_at"}
    for slab in db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack.id).all():
        db.add(TaxSlab(organization_id=organization.id,
                       **{c.name: getattr(slab, c.name) for c in TaxSlab.__table__.columns if c.name not in skip}))
    db.commit()
    for opted_in in (False, True):
        with pytest.raises(MissingComplianceConfigurationError):
            service._resolve_effective_rate_inputs(db, organization.id, "SG", JUN, opted_in)


def test_a_payroll_run_with_only_a_draft_pack_is_refused_and_commits_nothing(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    _seed(db)                                                                          # Draft only
    _employee(db, organization.id)
    run = _run(db, organization.id)
    try:
        service.generate_payslips_for_run(db, run, organization.id)
        db.commit()
    except Exception:                                                                  # noqa: BLE001 — refusal is the pass
        db.rollback()
    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    assert all(i.tax_policy_pack_id is None and not i.employee_pension and not i.employer_pension for i in items)
    assert not any(i.net_pay for i in items)


# ── 2. apply_extracted_rate ─────────────────────────────────────────────────

def test_extracted_document_rates_are_never_applied_to_a_singapore_org(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate

    for code in ("SG", "sg", "Singapore"):
        with pytest.raises(BadRequestException, match="Active statutory pack"):
            service.apply_extracted_rate(db, organization.id, "contributionRate",
                                         {"label": "SDL", "employer": "0.5%"}, country_code=code)
    assert db.query(ContributionRate).filter(ContributionRate.organization_id == organization.id).count() == 0
    # Every other country keeps the existing behaviour.
    assert service.apply_extracted_rate(db, organization.id, "contributionRate",
                                        {"label": "PF", "employee": "12%", "employer": "12%"},
                                        country_code="IN")["applied"] is True


# ── 3. Pack activation ──────────────────────────────────────────────────────

def test_the_seeded_packs_reproduce_every_golden_vector_in_their_window(db):
    from app.modules.payroll import service
    from scripts.seed_singapore_canonical_pack import seed_singapore_2027

    p26 = _seed(db)
    p27 = seed_singapore_2027(db)
    db.commit()
    c26, c27 = service.sg_pack_golden_check(db, p26), service.sg_pack_golden_check(db, p27)
    assert (c26["casesInWindow"], c26["failures"]) == (35, []) and c26["passed"] == 35
    assert (c27["casesInWindow"], c27["failures"]) == (2, []) and c27["passed"] == 2


def test_activation_needs_g1_accepted_on_the_normal_and_the_hotfix_path(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _seed(db)
    assert service.run_golden_test_certification(db, "SG", actor_id=A).status == "PASS"
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)
    with pytest.raises(BadRequestException, match="G1"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A)
    with pytest.raises(BadRequestException, match="G1"):
        service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-1", "urgent", actor_id=A)
    db.refresh(pack)
    assert pack.status == "Approved" and len(_refusals(db, pack)) == 2
    _accept(db, "SG-GATE-G1")
    assert service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A).status == "Active"


def test_a_pack_whose_own_rows_break_a_golden_vector_cannot_go_active(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _seed(db)
    _accept(db, "SG-GATE-G1")
    cap = _pack_row(db, pack, "sdl_max_monthly")
    cap.flat_amount = D("12.00")                                                       # a wrong statutory row
    db.commit()
    # The old, fixture-only certification cannot see it:
    assert service.run_golden_test_certification(db, "SG", actor_id=A).status == "PASS"
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)
    with pytest.raises(BadRequestException, match="do not reproduce"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A)
    summary_gates = {g["key"]: g["met"] for g in service.get_sg_statutory_summary(db, JUN)
                     ["activationReadiness"]["statutoryPack"]["activationGates"]}
    assert summary_gates["pack_reproduces_golden_vectors"] is False and summary_gates["g1_evidence_accepted"] is True
    cap.flat_amount = D("11.25")
    db.commit()
    assert service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A).status == "Active"


def test_a_singapore_pack_must_start_on_the_first_of_a_month(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _seed(db)
    _accept(db, "SG-GATE-G1")
    pack.effective_from = date(2026, 1, 15)
    db.commit()
    assert service.run_golden_test_certification(db, "SG", actor_id=A).status == "PASS"
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)
    with pytest.raises(BadRequestException, match="1st of a month"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A)


# ── 4. Wage-month reports ───────────────────────────────────────────────────

def test_wage_month_reports_never_substitute_the_pack_in_force_for_unpinned_payslips(db):
    from app.modules.payroll import service

    pack = _seed(db)
    pack.status = "Active"
    db.commit()
    unpinned = SimpleNamespace(tax_policy_pack_id=None)
    packs = service._sg_report_packs(db, {1: [unpinned]}, JUN)
    assert (packs["basis"], packs["pack"], packs["packIds"], packs["fallback"]) == ("UNPINNED", None, [], None)
    rates, reason = service._sg_employee_pack_rates(packs, [unpinned])
    assert rates == {} and "no pinned statutory pack" in reason


# ── 5. Organization country change ──────────────────────────────────────────

def test_an_existing_org_cannot_move_itself_into_a_planned_singapore(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.organizations import router as org_router
    from app.modules.organizations.models import Organization
    from app.modules.organizations.schemas import OrganizationUpdate
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    _seed(db)                                                                          # registry row: PLANNED
    organization.country = "India"
    db.commit()
    assert get_jurisdiction_change_block_reason(db, "India", "Singapore") is not None
    assert get_jurisdiction_change_block_reason(db, "India", "SG") is not None
    assert get_jurisdiction_change_block_reason(db, "Singapore", "SG") is None         # not entering SG
    assert get_jurisdiction_change_block_reason(db, "India", "Australia") is None       # other countries untouched

    admin = SimpleNamespace(organization_id=organization.id, role="ORG_ADMIN")
    with pytest.raises(BadRequestException, match="not yet available"):
        org_router.update_my_organization(OrganizationUpdate(country="Singapore"), current_user=admin, db=db)
    with pytest.raises(BadRequestException, match="not yet available"):
        org_router.update_organization(organization.id, OrganizationUpdate(country="Singapore"),
                                       current_user=SimpleNamespace(email="sa@example.com", role="SUPER_ADMIN"), db=db)
    db.expire_all()
    assert db.query(Organization).filter(Organization.id == organization.id).one().country == "India"
    renamed = org_router.update_my_organization(OrganizationUpdate(organization_name="Renamed"), current_user=admin, db=db)
    assert renamed.organization_name == "Renamed" and renamed.country == "India"
