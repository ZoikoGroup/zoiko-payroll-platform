"""
tests/test_singapore_completion_programme.py
--------------------------------------------
Singapore jurisdiction completion programme (2026-09-29) — one regression
test (or more) per defect found by the completion audit. Each test fails on
the tree before the fix (see docs/SINGAPORE_FINAL_IMPLEMENTATION_STATUS.md
§15 for the before/after evidence).

  Pack governance   explicit SG tax-pack transition graph; released approval
                    is evidence; status-change reason; hotfix review audited;
                    an org account cannot edit a tax pack through the
                    policy-pack route; a pack's type never changes.
  Template governance  self-approval refused at Approve; a Superseded SG
                    template is never deleted; deletes are audited.
  Reports           PWM / LQS use the payslips' pinned pack; supersession
                    spans template versions; generation / void audited;
                    submitted IR8A cannot be voided; the generic generator
                    needs an Active SG template; IR8A modifications render
                    from the Active template version.
  Operations        CPF EZPay 150-BYTE records (non-ASCII refused); EZPay
                    approval needs an identified approver; IR21 freeze audit
                    rows use the IR21 entity type.
  Super Admin       statutory-operations readiness, LQS quota capability,
                    active template version, pack audit evidence.

All identifiers are synthetic. app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

A, B, C = 101, 202, 303
D = Decimal


# ── helpers ────────────────────────────────────────────────────────────────

def _audits(db, entity_type, entity_id, action=None):
    from app.modules.payroll.models import TaxConfigurationAudit

    q = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == entity_type,
                                               TaxConfigurationAudit.entity_id == entity_id)
    if action:
        q = q.filter(TaxConfigurationAudit.action == action)
    return q.order_by(TaxConfigurationAudit.id).all()


def _sg_pack(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    return pack


def _raw_pack(db, country, status, pack_type="tax", version="1.0"):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id=f"{country}-CP-{version}", version=version, jurisdiction_country=country,
                            pack_type=pack_type, status=status, effective_from=date(2026, 1, 1))
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return pack


# ══ Pack governance ════════════════════════════════════════════════════════

@pytest.mark.parametrize("current,target", [
    ("Superseded", "Draft"), ("Superseded", "Active"), ("Retired", "Active"), ("Retired", "Draft"),
    ("Deprecated", "Active"), ("Draft", "Superseded"), ("Draft", "Foo"),
])
def test_sg_pack_transition_graph_refuses_and_audits(db, current, target):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _raw_pack(db, "SG", current)
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, pack.id, target, actor_id=A)
    db.refresh(pack)
    assert pack.status == current
    [row] = _audits(db, "jurisdiction_pack", pack.id, "refused")
    assert (row.actor_id, row.old_value, row.new_value["attempted"]) == (A, {"status": current}, target)


def test_sg_pack_review_stages_move_freely_and_carry_the_reason(db):
    from app.modules.payroll import service

    pack = _raw_pack(db, "SG", "Draft")
    for target in ("In Review", "QA", "Draft", "Approved", "In Review"):
        assert service.set_jurisdiction_pack_status(db, pack.id, target, actor_id=A, reason=f"to {target}").status == target
    changes = _audits(db, "jurisdiction_pack", pack.id, "status_change")
    assert [c.reason for c in changes] == ["to In Review", "to QA", "to Draft", "to Approved", "to In Review"]


def test_the_transition_graph_is_the_documented_pack_lifecycle():
    from app.modules.payroll.service import TAX_PACK_TRANSITIONS, _EDITABLE_PACK_STATUSES

    assert TAX_PACK_TRANSITIONS["Superseded"] == () and TAX_PACK_TRANSITIONS["Retired"] == ()
    for released in ("Active", "Deprecated", "Retired", "Superseded"):
        assert not set(TAX_PACK_TRANSITIONS[released]) & set(_EDITABLE_PACK_STATUSES)


def test_other_countries_keep_their_free_pack_lifecycle(db):
    from app.modules.payroll import service

    pack = _raw_pack(db, "GB", "Superseded")
    assert service.set_jurisdiction_pack_status(db, pack.id, "Draft", actor_id=A).status == "Draft"
    assert _audits(db, "jurisdiction_pack", pack.id, "refused") == []


@pytest.mark.parametrize("status", ["Active", "Superseded", "Retired"])
def test_released_sg_pack_approval_is_evidence_and_never_replaced(db, status):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _raw_pack(db, "SG", status)
    pack.approved_by_id = B
    db.commit()
    with pytest.raises(BadRequestException, match="release evidence"):
        service.set_jurisdiction_pack_approver(db, pack.id, actor_id=C)
    db.refresh(pack)
    assert (pack.approved_by_id, pack.status) == (B, status)
    [row] = _audits(db, "jurisdiction_pack", pack.id, "refused")
    assert row.new_value["attempted"] == "approve"


def test_other_countries_released_pack_approval_is_unchanged(db):
    from app.modules.payroll import service

    pack = _raw_pack(db, "GB", "Active")
    pack.approved_by_id = B
    db.commit()
    assert service.set_jurisdiction_pack_approver(db, pack.id, actor_id=C).approved_by_id == C


def test_hotfix_cannot_reactivate_a_superseded_sg_pack(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import PackHotfixActivation

    pack = _sg_pack(db)
    assert service.run_golden_test_certification(db, "SG", actor_id=A).status == "PASS"
    pack.status = "Superseded"
    db.commit()
    with pytest.raises(BadRequestException, match="final"):
        service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-CP", "emergency", actor_id=A)
    db.refresh(pack)
    assert (pack.status, pack.approved_by_id) == ("Superseded", None)
    assert db.query(PackHotfixActivation).count() == 0


def test_sg_hotfix_reason_and_review_are_on_the_pack_audit_trail(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import PackHotfixActivation

    pack = _sg_pack(db)
    assert service.run_golden_test_certification(db, "SG", actor_id=A).status == "PASS"
    service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-CP", "CPF table correction", actor_id=A)
    [activation] = db.query(PackHotfixActivation).filter(PackHotfixActivation.jurisdiction_pack_id == pack.id).all()
    [change] = [a for a in _audits(db, "jurisdiction_pack", pack.id, "status_change") if a.new_value == {"status": "Active"}]
    assert change.reason == "Hotfix INC-CP: CPF table correction"
    service.review_pack_hotfix_activation(db, activation.id, "verified", actor_id=B)
    [review] = [a for a in _audits(db, "jurisdiction_pack", pack.id, "update")
                if (a.new_value or {}).get("hotfixActivationId") == activation.id]
    assert (review.actor_id, review.new_value["reviewed"], review.new_value["activatedById"]) == (B, True, A)
    assert review.reason == "Hotfix review: verified"


def test_org_operator_cannot_edit_a_tax_pack_through_the_policy_route(db, organization):
    from app.core.exceptions import ForbiddenException
    from app.modules.payroll.router import upsert_jurisdiction_pack
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    pack = _raw_pack(db, "SG", "Draft")
    payload = JurisdictionPackUpsert(id=pack.id, packId="HIJACK", version="9.9", jurisdictionCountry="SG",
                                     packType="policy", status="Draft", effectiveFrom=date(2020, 1, 1))
    operator = SimpleNamespace(id=A, role="payroll_admin", organization_id=organization.id)
    with pytest.raises(ForbiddenException):
        upsert_jurisdiction_pack(payload, db=db, current_user=operator)
    db.refresh(pack)
    assert (pack.pack_id, pack.version, pack.pack_type, pack.effective_from) == ("SG-CP-1.0", "1.0", "tax", date(2026, 1, 1))


def test_an_existing_packs_type_never_changes(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    for country in ("SG", "GB"):                                   # all countries: security fix
        pack = _raw_pack(db, country, "Draft")
        with pytest.raises(BadRequestException, match="type cannot be changed"):
            service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
                id=pack.id, packId=pack.pack_id, version=pack.version, jurisdictionCountry=country,
                packType="policy", status="Draft"), actor_id=A)
        db.refresh(pack)
        assert pack.pack_type == "tax"


# ══ Template governance ════════════════════════════════════════════════════

def _template(db, key="SG-CP-T", report_type="SG_PAYROLL_REGISTER", status="Draft", version="1.0", country="SG"):
    from app.modules.payroll.models import ReportTemplate

    t = ReportTemplate(template_key=key, name=key, report_type=report_type, jurisdiction_country=country,
                       reporting_year="2026", version=version, status=status, document_scope="AGGREGATE",
                       updated_by_id=A)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def test_sg_template_self_approval_is_refused_at_approve_and_audited(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db)
    with pytest.raises(BadRequestException, match="cannot approve it"):
        service.set_report_template_approver(db, t.id, actor_id=A)
    db.refresh(t)
    assert (t.status, t.approved_by_id) == ("Draft", None)
    [row] = _audits(db, "report_template", t.id, "refused")
    assert row.new_value["attempted"] == "approve"
    assert service.set_report_template_approver(db, t.id, actor_id=B).approved_by_id == B


def test_a_superseded_sg_template_is_never_deleted_and_deletes_are_audited(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate

    old = _template(db, status="Superseded")
    other = _template(db, key="GB-CP-T", status="Superseded", country="GB")      # (created first: SQLite reuses ids)
    with pytest.raises(BadRequestException, match="retained version history"):
        service.hard_delete_report_template(db, old.id, actor_id=A)
    assert db.query(ReportTemplate).filter(ReportTemplate.id == old.id).count() == 1
    draft = _template(db, version="1.1")
    service.hard_delete_report_template(db, draft.id, actor_id=A)
    [row] = _audits(db, "report_template", draft.id, "delete")
    assert (row.actor_id, row.old_value["status"]) == (A, "Draft")
    service.hard_delete_report_template(db, other.id, actor_id=A)                 # other countries unchanged
    assert _audits(db, "report_template", other.id) == []


# ══ Reports ════════════════════════════════════════════════════════════════

def _pwm_setup(db, organization, monkeypatch):
    from tests.test_singapore_phase57_reports import _active_pack, _employee, _generate_payslips, _stub_codes

    _stub_codes(monkeypatch)
    pack = _active_pack(db, organization)
    _employee(db, organization.id, "CPPWM", ctc=D("24000"), basic=D("24000"), hra=D("0"),
              compliance_fields={"nric_fin": "S1234567D", "pwm_sector": "CLEANING", "pwm_group": "G1",
                                 "pwm_job_level": "GENERAL_INDOOR", "ea_workman": "YES", "ea_manager_executive": "NO"})
    _generate_payslips(db, organization, date(2026, 7, 31), "Jul 2026")
    return pack


def test_pwm_report_keeps_the_pinned_pack_after_it_is_superseded(db, organization, monkeypatch):
    """Before: generate_sg_pwm_compliance resolved the pack Active today, so
    once the period's pack was Superseded a regenerated report had no pack
    and every row became NOT_EVALUATED."""
    from app.modules.payroll import service
    from tests.test_singapore_phase57_reports import _template as _t57

    pack = _pwm_setup(db, organization, monkeypatch)
    template = _t57(db, "SG-PWM-COMPLIANCE", "SG_PWM_COMPLIANCE")
    first = service.generate_sg_pwm_compliance(db, organization.id, template.id, 2026, 7, actor_id=A)
    assert first.rendered_data["packBasis"] == "PINNED"
    pack.status = "Superseded"                                   # a later version replaced it
    db.commit()
    second = service.generate_sg_pwm_compliance(db, organization.id, template.id, 2026, 7, actor_id=A)
    assert second.applicable_tax_pack_id == pack.id and second.applicable_tax_pack_version == pack.version
    assert second.rendered_data["employeeRows"] == first.rendered_data["employeeRows"]      # deterministic
    assert second.rendered_data["employeeRows"][0]["result"] == "SHORTFALL"
    db.refresh(first)
    assert first.status == "Superseded"


def test_lqs_report_records_the_pinned_pack(db, organization, monkeypatch):
    from app.modules.payroll import service
    from tests.test_singapore_phase57_reports import _template as _t57

    pack = _pwm_setup(db, organization, monkeypatch)
    template = _t57(db, "SG-LQS-COMPLIANCE", "SG_LQS_COMPLIANCE")
    pack.status = "Superseded"
    db.commit()
    report = service.generate_sg_lqs_compliance(db, organization.id, template.id, 2026, 7, actor_id=A)
    assert (report.applicable_tax_pack_id, report.rendered_data["packBasis"]) == (pack.id, "PINNED")
    assert report.rendered_data["pack"]["status"] == "Superseded"


def test_supersession_spans_template_versions_and_generation_is_audited(db, organization, monkeypatch):
    """Before: supersession was keyed on report_template_id, so a report of
    template v1.0 stayed live beside the v1.1 report for the same month."""
    from app.modules.payroll import service
    from app.modules.payroll.models import GeneratedReport
    from tests.test_singapore_phase57_reports import _template as _t57

    _pwm_setup(db, organization, monkeypatch)
    v10 = _t57(db, "SG-PWM-COMPLIANCE", "SG_PWM_COMPLIANCE")
    first = service.generate_sg_pwm_compliance(db, organization.id, v10.id, 2026, 7, actor_id=A)
    v10.status = "Superseded"
    v11 = _template(db, key="SG-PWM-COMPLIANCE", report_type="SG_PWM_COMPLIANCE", status="Active", version="1.1")
    second = service.generate_sg_pwm_compliance(db, organization.id, v11.id, 2026, 7, actor_id=B)
    live = db.query(GeneratedReport).filter(GeneratedReport.organization_id == organization.id,
                                            GeneratedReport.report_type == "SG_PWM_COMPLIANCE",
                                            GeneratedReport.status == "Generated").all()
    assert [r.id for r in live] == [second.id] and second.template_version == "1.1"
    [created] = _audits(db, "generated_report", second.id, "create")
    assert created.actor_id == B and created.old_value == {"supersededReportIds": [first.id]}
    assert created.new_value["templateVersion"] == "1.1" and created.new_value["packVersion"] == second.applicable_tax_pack_version
    assert len(_audits(db, "generated_report", first.id, "create")) == 1


def test_generic_generator_renders_only_an_active_sg_template(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    published = _template(db, key="SG-PAYROLL-REGISTER", status="Published")
    with pytest.raises(BadRequestException, match="only from the Active version"):
        service.generate_report_from_template(db, organization.id, published.id, 999999, actor_id=A)


def _sg_report(db, organization, report_type, status):
    from app.modules.payroll.models import GeneratedReport

    t = _template(db, key=f"SG-CP-{report_type}", report_type=report_type, status="Active")
    row = GeneratedReport(organization_id=organization.id, report_template_id=t.id, template_version="1.0",
                          report_type=report_type, scope_key="PERIOD:2026-01-01:2026-12-31", jurisdiction_country="SG",
                          reporting_year="2026", status=status, generated_by_id=A, rendered_data={})
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.mark.parametrize("status", ["SUBMITTED_MANUALLY", "UNKNOWN", "ACKNOWLEDGED"])
def test_a_filed_ir8a_extract_cannot_be_voided(db, organization, status):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    row = _sg_report(db, organization, "SG_IR8A", status)
    with pytest.raises(BadRequestException, match="cannot be voided"):
        service.void_generated_report(db, organization.id, row.id, "mistake", actor_id=A)
    db.refresh(row)
    assert row.status == status


def test_voiding_a_sg_report_is_audited(db, organization):
    from app.modules.payroll import service

    row = _sg_report(db, organization, "SG_SDL_MONTHLY", "Generated")
    service.void_generated_report(db, organization.id, row.id, "wrong month", actor_id=B)
    [audit] = _audits(db, "generated_report", row.id, "status_change")
    assert (audit.actor_id, audit.old_value, audit.new_value["status"], audit.reason) == (
        B, {"status": "Generated"}, "Void", "wrong month")


def test_ir8a_modification_renders_from_the_active_template_version(db, organization):
    """Before: create_sg_ir8a_modification required the ORIGINAL's template
    row to still be Active, so after any IR8A template correction an
    acknowledged original could never be revised or amended."""
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate
    from tests.test_singapore_phase68_ir8a_modifications import _employee, _original, _pack, _payslip
    from tests.test_singapore_phase68_ir8a_modifications import _template as _t68

    template = _t68(db)
    pack = _pack(db)
    emp = _employee(db, organization, "CPIR8A")
    _payslip(db, organization, emp, date(2026, 3, 31), "6000", "1200", pack)
    base = _original(db, organization, template)
    _payslip(db, organization, emp, date(2026, 4, 30), "500", "100", pack)       # later income to amend
    template.status = "Superseded"
    corrected = ReportTemplate(template_key=template.template_key, name=template.name, report_type="SG_IR8A",
                               jurisdiction_country="SG", reporting_year=template.reporting_year, version="1.1",
                               status="Active", document_scope=template.document_scope, previous_version_id=template.id)
    db.add(corrected)
    db.commit()
    mod = service.create_sg_ir8a_modification(db, organization.id, base.id, "AMENDMENT", reason="April pay", actor_id=A)
    assert mod["templateVersion"] == "1.1"


# ══ Operations: EZPay / IR21 ═══════════════════════════════════════════════

def _ezpay_employee(name):
    return {"employee_ref": "E1", "account_no": "S1234567D", "name": name, "cpf_total": D("100"),
            "ordinary_wages": D("500"), "additional_wages": D("0"), "employment_status": "E", "shg": {}}


def test_ezpay_refuses_a_non_ascii_name_instead_of_failing_on_encode():
    from app.modules.payroll.engine.jurisdictions.singapore.statutory import ezpay

    csn = ("201912345K", "PTE", "01")
    with pytest.raises(ezpay.EzpayValidationError, match="non-ASCII"):
        ezpay.build_file(csn, "01", "2026-07", datetime(2026, 8, 5, 9, 0), [_ezpay_employee("JOSÉ TAN")], D("0"))
    built = ezpay.build_file(csn, "01", "2026-07", datetime(2026, 8, 5, 9, 0), [_ezpay_employee("JOSE TAN")], D("0"))
    assert all(len(line.encode("ascii")) == ezpay.RECORD_LENGTH for line in built["content"].split("\r\n") if line)
    record = "F" + "É" * (ezpay.RECORD_LENGTH - 1)
    assert any("non-ASCII" in p for p in ezpay.validate_records([record]))


def test_ezpay_approval_needs_an_identified_approver(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    row = _sg_report(db, organization, "SG_CPF_EZPAY", "PREPARED")
    with pytest.raises(BadRequestException, match="distinct approver"):
        service.transition_sg_cpf_ezpay(db, organization.id, row.id, "APPROVED", actor_id=None)
    db.refresh(row)
    assert row.status == "PREPARED"
    assert len(_audits(db, "sg_cpf_ezpay", row.id, "refused")) == 1


def test_ir21_freeze_audit_rows_use_the_ir21_case_entity(db, organization, monkeypatch):
    """Before: the SG-047 freeze wrote entity_type "sg_ir21_case" while every
    other IR21 audit row (and the IR21 register's count) uses "sgp_ir21_case"."""
    from app.modules.payroll import service
    from tests.test_singapore import _foreign, _ir21_org, _open_case

    _ir21_org(db, organization, monkeypatch)
    case = _open_case(db, organization, _foreign(db, organization.id, "CPIR21"))
    service.sg_freeze_after_restore(db, organization.id, "bk-cp", actor_id=A)
    frozen = [a for a in _audits(db, "sgp_ir21_case", case.id, "status_change")
              if (a.new_value or {}).get("status") == "RECONCILE_FIRST"]
    assert len(frozen) == 1 and _audits(db, "sg_ir21_case", case.id) == []


# ══ Super Admin summary ════════════════════════════════════════════════════

def _summary(db, as_of=date(2026, 9, 25)):
    from app.modules.payroll import service

    return service.get_sg_statutory_summary(db, as_of)


def _section(summary, key):
    return next(s for s in summary["sections"] if s["key"] == key)


def test_operations_readiness_reflects_the_service_lifecycles(db):
    from app.modules.payroll import service
    from app.modules.payroll.engine.jurisdictions.singapore.statutory import ezpay

    ops = {i["key"]: i for i in _section(_summary(db), "operations")["values"]["items"]}
    assert set(ops) == {"ir8a", "ais_api", "ir21", "cpf_ezpay", "lqs_quota"}         # closure: + LQS quota
    assert ops["ais_api"]["state"] == "EXTERNAL_INTEGRATION_REQUIRED"
    assert {ops[k]["state"] for k in ("ir8a", "ir21", "cpf_ezpay")} == {"TEMPLATE_MISSING"}       # empty database
    assert ops["cpf_ezpay"]["lifecycle"] == {k: list(v) for k, v in service._SG_EZPAY_TRANSITIONS.items()}
    assert ops["ir21"]["lifecycle"] == {k: sorted(v) for k, v in service._SG_IR21_TRANSITIONS.items()}
    assert any(str(ezpay.RECORD_LENGTH) in c for c in ops["cpf_ezpay"]["controls"])


def test_lqs_quota_is_flagged_not_implemented_without_fabricating_a_value(db):
    lqs = _section(_summary(db), "lqs")
    assert lqs["capabilities"] == {"quotaComputation": "NOT_IMPLEMENTED"}
    assert all(v is None for v in lqs["values"].values())


def test_summary_shows_the_active_version_behind_a_draft_correction(db):
    _template(db, key="SG-IR8A", report_type="SG_IR8A", status="Active", version="1.0")
    _template(db, key="SG-IR8A", report_type="SG_IR8A", status="Draft", version="1.1")
    summary = _summary(db)
    row = next(t for t in _section(summary, "reportTemplates")["values"]["templates"] if t["templateKey"] == "SG-IR8A")
    assert (row["version"], row["status"], row["activeVersion"], row["generatable"]) == ("1.1", "Draft", "1.0", True)
    ir8a = next(i for i in _section(summary, "operations")["values"]["items"] if i["key"] == "ir8a")
    assert ir8a["state"] == "READY"


def test_activation_readiness_carries_the_pack_audit_evidence(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _sg_pack(db)
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, pack.id, "Superseded", actor_id=A)     # Draft -> Superseded: refused
    audit = _summary(db, as_of=pack.effective_from)["activationReadiness"]["statutoryPack"]["audit"]
    assert audit["refused"] == 1 and audit["entries"] >= 1
    assert (audit["hotfixActivations"], audit["unreviewedHotfixes"]) == (0, 0)
