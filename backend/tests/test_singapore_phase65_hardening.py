"""
tests/test_singapore_phase65_hardening.py
-----------------------------------------
Singapore Phase 6.5 — closes the three Phase 6.4 engineering findings.

  A  Refused governance actions are audited (Singapore opt-in,
     _REFUSAL_AUDIT_COUNTRIES): a refused pack status change / approval /
     hotfix, a refused report-template transition, and a preparer's refused
     self-approval of an IR8A / IR21 / CPF EZPay step each leave exactly ONE
     TaxConfigurationAudit row (action "refused": actor, time, attempted
     action, current status, reason) and nothing else. Other countries keep
     their existing, unaudited refusals.
  B  A Singapore pack's submitter (the Super Admin who last edited or
     submitted it) cannot approve it — refused at the Approve step, not only
     at activation. Distinct approver accepted and audited; F2 and the
     activation gates are unchanged; other countries unchanged.
  C  SG-IR21-REGISTER / SG-SDL-MONTHLY / SG-IR8A / SG-CPF-EZPAY record the
     pack their payslips were calculated under (PayslipItem.tax_policy_pack_id,
     the generate_report_from_template rule) — never the currently Active
     pack — so a later pack never rewrites a historical report and
     regeneration stays deterministic.

app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date
from decimal import Decimal

import pytest

A, B, C = 101, 202, 303          # distinct Super Admin / operator actors
D = Decimal


def _refused(db, entity_type, entity_id):
    from app.modules.payroll.models import TaxConfigurationAudit

    return (db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.entity_type == entity_type, TaxConfigurationAudit.entity_id == entity_id,
                    TaxConfigurationAudit.action == "refused")
            .order_by(TaxConfigurationAudit.id).all())


def _sg_pack(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    return pack


# ══ A — refused actions are audited ════════════════════════════════════════

def test_a_refused_sg_activation_leaves_one_audit_row_and_no_change(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _sg_pack(db)
    with pytest.raises(BadRequestException, match="passing golden-vector"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A)
    db.refresh(pack)
    assert pack.status == "Draft"
    [row] = _refused(db, "jurisdiction_pack", pack.id)
    assert (row.actor_id, row.old_value, row.new_value) == (A, {"status": "Draft"}, {"attempted": "Active", "result": "REFUSED"})
    assert row.created_at is not None and "golden-vector" in row.reason
    assert (row.jurisdiction_pack_id, row.tax_version) == (pack.id, pack.version)


def test_a_refused_sg_hotfix_is_audited_once_and_keeps_no_phantom_approval(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import PackHotfixActivation

    pack = _sg_pack(db)
    with pytest.raises(BadRequestException, match="passing golden-vector"):
        service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-65", "emergency", actor_id=A)
    with pytest.raises(BadRequestException, match="incident_id"):
        service.activate_jurisdiction_pack_hotfix(db, pack.id, " ", "emergency", actor_id=A)
    db.refresh(pack)
    assert (pack.status, pack.approved_by_id) == ("Draft", None)                    # 6.3 fix still holds
    assert db.query(PackHotfixActivation).count() == 0
    rows = _refused(db, "jurisdiction_pack", pack.id)
    assert [r.new_value for r in rows] == [{"attempted": "Active", "result": "REFUSED", "path": "hotfix"}] * 2
    assert all(r.old_value == {"status": "Draft"} and r.actor_id == A for r in rows)   # one row per refusal


def test_a_refused_sg_template_transition_is_audited(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey="SG-P65-T", name="t", reportType="SG_PAYROLL_REGISTER", jurisdictionCountry="SG",
        reportingYear="2026"), actor_id=A)
    with pytest.raises(BadRequestException, match="requires an Approved"):
        service.set_report_template_status(db, t.id, "Published", actor_id=A)
    [row] = _refused(db, "report_template", t.id)
    assert (row.actor_id, row.old_value, row.new_value["attempted"], row.tax_version) == (A, {"status": "Draft"}, "Published", "1.0")
    assert service.get_report_template(db, t.id).status == "Draft"


def test_a_refused_sg_ezpay_self_approval_is_audited(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import GeneratedReport

    row = GeneratedReport(organization_id=organization.id, report_template_id=1, template_version="1.0",
                          report_type="SG_CPF_EZPAY", jurisdiction_country="SG", reporting_year="2026",
                          reporting_period="2026-05", scope_key="PERIOD:2026-05:ADVICE:01", status="PREPARED",
                          generated_by_id=A, rendered_data={}, reconciliation={})
    db.add(row)
    db.commit()
    with pytest.raises(BadRequestException, match="preparer cannot approve"):
        service.transition_sg_cpf_ezpay(db, organization.id, row.id, "APPROVED", actor_id=A)
    db.refresh(row)
    assert row.status == "PREPARED"
    [audit] = _refused(db, "sg_cpf_ezpay", row.id)
    assert (audit.actor_id, audit.old_value, audit.new_value) == (A, {"status": "PREPARED"},
                                                                  {"attempted": "APPROVED", "result": "REFUSED"})


def test_a_refusal_rolls_back_pending_changes_before_auditing(db):
    """A refused SG activation leaves nothing the call had pending — the
    audit row is its only trace (the Phase 6.3 phantom-approval class)."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack

    pack = _sg_pack(db)
    pack.change_summary = "PENDING-UNCOMMITTED"                                       # never committed
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A)
    assert db.query(JurisdictionPack).get(pack.id).change_summary != "PENDING-UNCOMMITTED"
    assert len(_refused(db, "jurisdiction_pack", pack.id)) == 1


def test_a_other_countries_keep_unaudited_refusals(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack, TaxConfigurationAudit

    us = JurisdictionPack(pack_id="US-P65", jurisdiction_country="US", pack_type="tax", version="1.0", status="Draft")
    db.add(us)
    db.commit()
    with pytest.raises(BadRequestException, match="Source Evidence"):
        service.set_jurisdiction_pack_status(db, us.id, "Active", actor_id=A)
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.action == "refused").count() == 0


# ══ B — pack self-approval refused at the Approve step ═════════════════════

def test_b_submitter_cannot_approve_its_own_sg_pack(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _sg_pack(db)
    service.set_jurisdiction_pack_status(db, pack.id, "In Review", actor_id=A)      # A submits
    with pytest.raises(BadRequestException, match="cannot approve"):
        service.set_jurisdiction_pack_approver(db, pack.id, actor_id=A)
    db.refresh(pack)
    assert (pack.status, pack.approved_by_id) == ("In Review", None)
    [row] = _refused(db, "jurisdiction_pack", pack.id)
    assert (row.actor_id, row.new_value["attempted"], row.old_value) == (A, "approve", {"status": "In Review"})


def test_b_distinct_approver_is_accepted_audited_and_activation_rules_unchanged(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit

    pack = _sg_pack(db)
    assert service.run_golden_test_certification(db, "SG", actor_id=A).status == "PASS"
    service.set_jurisdiction_pack_status(db, pack.id, "In Review", actor_id=A)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)                  # distinct approver
    approval = (db.query(TaxConfigurationAudit)
                .filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack", TaxConfigurationAudit.entity_id == pack.id,
                        TaxConfigurationAudit.action == "update").order_by(TaxConfigurationAudit.id.desc()).first())
    assert (approval.actor_id, approval.new_value["approved_by_id"]) == (B, B) and approval.created_at
    with pytest.raises(BadRequestException, match="cannot also activate"):          # F2 unchanged
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=B)
    assert service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A).status == "Active"
    assert [r.new_value["attempted"] for r in _refused(db, "jurisdiction_pack", pack.id)] == ["Active"]


def test_b_seeded_never_edited_pack_can_be_approved_by_any_super_admin(db):
    from app.modules.payroll import service

    pack = _sg_pack(db)
    assert pack.updated_by_id is None
    assert service.set_jurisdiction_pack_approver(db, pack.id, actor_id=A).approved_by_id == A


def test_b_other_countries_keep_their_existing_approve_behaviour(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack

    us = JurisdictionPack(pack_id="US-P65B", jurisdiction_country="US", pack_type="tax", version="1.0", status="Draft",
                          updated_by_id=A)
    db.add(us)
    db.commit()
    assert service.set_jurisdiction_pack_approver(db, us.id, actor_id=A).approved_by_id == A   # recorded, as before


# ══ C — pack version on the dedicated Singapore reports ════════════════════

def _packs(db):
    from app.modules.payroll.models import JurisdictionPack

    p12 = JurisdictionPack(pack_id="SG-P65", jurisdiction_country="SG", pack_type="tax", version="1.2", status="Active",
                           effective_from=date(2026, 1, 1))
    db.add(p12)
    db.commit()
    return p12


def _later_pack(db):
    from app.modules.payroll.models import JurisdictionPack

    p13 = JurisdictionPack(pack_id="SG-P65", jurisdiction_country="SG", pack_type="tax", version="1.3", status="Active",
                           effective_from=date(2026, 1, 1))
    db.add(p13)
    db.commit()
    return p13


def _template(db, key, report_type):
    from app.modules.payroll.models import ReportTemplate

    t = ReportTemplate(template_key=key, name=key, report_type=report_type, jurisdiction_country="SG",
                       reporting_year="2026", version="1.0", status="Active", document_scope="AGGREGATE")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _payslips(db, organization, pack, codes=("C1", "C2"), pay_date=date(2026, 5, 31)):
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollStatus, PayslipItem
    from tests.test_singapore import _run, _sg_employee

    if not db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization.id).first():
        db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="SG", name="Acme",
                                        tax_identifiers={"uen": "201912345K", "cpf_submission_number": "201912345KPTE01"}))
    run = _run(db, organization, pay_date, f"P65 {organization.id} {pay_date} {pack.version}")
    run.status = PayrollStatus.APPROVED
    items = []
    for code in codes:
        emp = _sg_employee(db, organization.id, f"{code}{organization.id}", compliance_fields={"nric_fin": "S1234567D"})
        item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
                           employee_name=emp.name, country_code="SG", gross_pay=D("6000"), net_pay=D("4800"),
                           employee_pension=D("1200"), employer_pension=D("1020"), employer_payroll_tax=D("11.25"),
                           tax_policy_pack_id=pack.id, tax_policy_version=pack.version,
                           sgp_calculation_trace={"wageMonth": pay_date.strftime("%Y-%m"),
                                                  "inputs": {"ordinaryWages": "6000", "additionalWages": "0"},
                                                  "shg": {"funds": {}}})
        db.add(item)
        items.append(item)
    db.commit()
    return items


def _ir21_case(db, organization, payslip):
    from app.modules.payroll.models import SgpIr21Case

    case = SgpIr21Case(organization_id=organization.id, employee_id=payslip.employee_id, final_payslip_id=payslip.id,
                       trigger_type="CESSATION", trigger_date=date(2026, 5, 31), aware_date=date(2026, 5, 1),
                       file_by_date=date(2026, 5, 31), status="DRAFT", held_amount=D("0"), prepared_by_id=A)
    db.add(case)
    db.commit()
    return case


_GENERATORS = {
    "SG_SDL_MONTHLY": lambda service, db, org, t: service.generate_sg_sdl_monthly(db, org.id, t.id, 2026, 5, actor_id=A),
    "SG_IR8A": lambda service, db, org, t: service.generate_sg_ir8a(db, org.id, t.id, 2026, actor_id=A),
    "SG_CPF_EZPAY": lambda service, db, org, t: service.generate_sg_cpf_ezpay(db, org.id, t.id, 2026, 5, actor_id=A),
    "SG_IR21_REGISTER": lambda service, db, org, t: service.generate_sg_ir21_register(db, org.id, t.id, 2026, actor_id=A,
                                                                                     today=date(2026, 6, 1)),
}


@pytest.mark.parametrize("report_type", sorted(_GENERATORS))
def test_c_dedicated_report_records_the_payslips_pack_and_a_later_pack_never_rewrites_it(db, organization, report_type):
    from app.modules.payroll import service
    from app.modules.payroll.models import GeneratedReport

    p12 = _packs(db)
    items = _payslips(db, organization, p12)
    if report_type == "SG_IR21_REGISTER":
        _ir21_case(db, organization, items[0])
    t = _template(db, f"SG-P65-{report_type}", report_type)
    first = _GENERATORS[report_type](service, db, organization, t)
    assert (first.applicable_tax_pack_id, first.applicable_tax_pack_version) == (p12.id, "1.2")
    _later_pack(db)                                                                     # a newer pack exists now
    db.expire_all()
    assert db.query(GeneratedReport).get(first.id).applicable_tax_pack_version == "1.2"  # history untouched
    again = _GENERATORS[report_type](service, db, organization, t)                      # regeneration
    assert (again.applicable_tax_pack_id, again.applicable_tax_pack_version) == (p12.id, "1.2")
    assert db.query(GeneratedReport).get(first.id).status == "Superseded"


@pytest.mark.parametrize("report_type", ["SG_SDL_MONTHLY", "SG_IR8A", "SG_CPF_EZPAY"])
def test_c_payslips_under_two_packs_record_no_single_version_but_list_both(db, organization, report_type):
    from app.modules.payroll import service

    p12 = _packs(db)
    p13 = _later_pack(db)
    _payslips(db, organization, p12, codes=("M1",))
    _payslips(db, organization, p13, codes=("M2",))
    rep = _GENERATORS[report_type](service, db, organization, _template(db, f"SG-P65M-{report_type}", report_type))
    assert (rep.applicable_tax_pack_id, rep.applicable_tax_pack_version) == (None, None)
    assert rep.rendered_data["metadata"]["taxPacksUsed"] == sorted([p12.id, p13.id])


def test_c_tenant_isolation_each_org_records_its_own_payslips_pack(db, organization):
    from app.modules.payroll import service
    from tests.test_singapore import _other_org

    p12 = _packs(db)
    p13 = _later_pack(db)
    other = _other_org(db, "P65OTHER")
    _payslips(db, organization, p12, codes=("TA",))
    _payslips(db, other, p13, codes=("TB",))
    t = _template(db, "SG-P65-SDL-ISO", "SG_SDL_MONTHLY")
    mine = service.generate_sg_sdl_monthly(db, organization.id, t.id, 2026, 5, actor_id=A)
    theirs = service.generate_sg_sdl_monthly(db, other.id, t.id, 2026, 5, actor_id=A)
    assert (mine.applicable_tax_pack_version, theirs.applicable_tax_pack_version) == ("1.2", "1.3")
    assert mine.rendered_data["employerTotals"]["total_employee_count"] == 1


def test_c_ir21_register_without_payslip_linked_cases_records_no_pack(db, organization):
    from app.modules.payroll import service

    _packs(db)
    rep = service.generate_sg_ir21_register(db, organization.id, _template(db, "SG-P65-IR21-EMPTY", "SG_IR21_REGISTER").id,
                                            2026, actor_id=A)
    assert (rep.applicable_tax_pack_id, rep.applicable_tax_pack_version) == (None, None)


def _released_template(db, country="SG", key="SG-P65-REL", report_type="SG_PAYROLL_REGISTER"):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=key, name="t", reportType=report_type, jurisdictionCountry=country, reportingYear="2026"), actor_id=A)
    service.set_report_template_approver(db, t.id, actor_id=B)
    return service.set_report_template_status(db, t.id, "Published", actor_id=C)


def test_a_editing_a_released_sg_template_in_place_is_refused_and_audited_once(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateComponentUpsert, ReportTemplateUpsert

    t = _released_template(db)
    with pytest.raises(BadRequestException, match="no longer editable"):
        service.upsert_report_template(db, ReportTemplateUpsert(
            templateKey=t.template_key, name="edited", reportType=t.report_type, jurisdictionCountry="SG",
            reportingYear="2026", version="1.0"), actor_id=A)
    with pytest.raises(BadRequestException, match="no longer editable"):
        service.upsert_report_component(db, t.id, ReportTemplateComponentUpsert(
            componentKey="employer_info", label="Employer"), actor_id=A)
    rows = _refused(db, "report_template", t.id)
    assert [(r.actor_id, r.new_value["attempted"], r.old_value["status"]) for r in rows] == [
        (A, "edit", "Published"), (A, "edit", "Published")]                       # one row per attempt
    assert service.get_report_template(db, t.id).name == "t"


def test_a_replacing_a_released_sg_approval_is_refused_and_audited(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _released_template(db)
    with pytest.raises(BadRequestException, match="release evidence"):
        service.set_report_template_approver(db, t.id, actor_id=C)
    [row] = _refused(db, "report_template", t.id)
    assert (row.actor_id, row.new_value["attempted"]) == (C, "approve")
    assert service.get_report_template(db, t.id).approved_by_id == B


def test_a_non_sg_released_template_refusals_stay_unaudited(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import TaxConfigurationAudit

    t = _released_template(db, country="IN", key="IN-P65-REL", report_type="TDS")
    with pytest.raises(BadRequestException, match="release evidence"):
        service.set_report_template_approver(db, t.id, actor_id=C)
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.action == "refused").count() == 0
