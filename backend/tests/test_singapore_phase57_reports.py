"""
tests/test_singapore_phase57_reports.py
---------------------------------------
Singapore Phase 5.7 — the SG-PWM-COMPLIANCE, SG-LQS-COMPLIANCE and
SG-IR21-REGISTER generators, plus the Super Admin summary's pack section,
Draft-vs-Active distinction and template-lifecycle evidence.

Every generator reuses an existing evaluator — labour.pwm_check on the
preflight's own inputs, the engine's persisted trace["lqs"], the
sgp_ir21_cases lifecycle — so these tests compare the report with that
evaluator rather than re-deriving statutory values. All identifiers are
synthetic. app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date
from decimal import Decimal

import pytest

D = Decimal
MAKER, CHECKER = 101, 202


# ── helpers ────────────────────────────────────────────────────────────────

def _stub_codes(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 100          # spaced apart: batch payslip numbers are base + seq
        return f"T57{prefix}{counter['n']:06d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _active_pack(db, organization=None):
    from app.modules.payroll.models import CompanyComplianceDetails
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    pack.status = "Active"
    if organization is not None:
        db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="SG", active_pack_id=pack.id,
                                        name="Zoiko SG Test Pte Ltd", tax_identifiers={"uen": "201912345K"}))
    db.commit()
    return pack


def _employee(db, org_id, code, **kw):
    from app.modules.payroll.models import PayrollEmployee

    fields = dict(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="SG",
                  ctc=D("120000"), date_of_birth=date(1986, 3, 15), sgp_cpf_residency_status="SC",
                  sgp_work_pass_type="NONE", sgp_shg_funds="NONE", compliance_fields={"nric_fin": "S1234567D"})
    fields.update(kw)
    emp = PayrollEmployee(**fields)
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _other_org(db, code):
    from app.modules.organizations.models import Organization

    org = Organization(organization_name=f"Org {code}", organization_code=code)
    db.add(org)
    db.commit()
    return org


def _finalized_run(db, org_id, pay_date, label):
    from app.modules.payroll.models import PayrollRun, PayrollStatus

    run = PayrollRun(organization_id=org_id, period_label=label, period_start=pay_date.replace(day=1),
                     period_end=pay_date, pay_date=pay_date, status=PayrollStatus.APPROVED)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _generate_payslips(db, organization, pay_date, label):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayrollStatus

    run = PayrollRun(organization_id=organization.id, period_label=label, period_start=pay_date.replace(day=1),
                     period_end=pay_date, pay_date=pay_date)
    db.add(run)
    db.commit()
    service.generate_payslips_for_run(db, run, organization.id)
    run.status = PayrollStatus.APPROVED
    db.commit()
    return run


def _payslip(db, run, employee, trace, gross="2000"):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from app.modules.payroll.models import PayslipItem

    # Phase 6.10: a generated Singapore payslip always pins the pack it was
    # calculated under (reports no longer substitute the pack in force today
    # for an unpinned one), so a hand-built payslip carries the same pin.
    pack = resolve_tax_configuration(db, "SG", payroll_date=run.pay_date)[2]
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=run.organization_id,
                       employee_name=employee.name, country_code="SG", gross_pay=D(gross), net_pay=D(gross),
                       sgp_calculation_trace=trace, tax_policy_pack_id=pack.id if pack else None)
    db.add(item)
    db.commit()
    return item


def _template(db, key, report_type, status="Active"):
    from app.modules.payroll.models import ReportTemplate

    t = ReportTemplate(template_key=key, name=key, report_type=report_type, jurisdiction_country="SG",
                       reporting_year="2026", version="1.0", status=status, document_scope="AGGREGATE")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _wage_trace(basic, overtime="0", hours=None, extra=None):
    trace = {"wageMonth": "2026-07",
             "inputs": {"wageClassification": {"basic": {"amount": str(basic), "class": "OW"},
                                               "overtime": {"amount": str(overtime), "class": "OW"}}}}
    if hours is not None:
        trace["overtime"] = {"hours": str(hours)}
    trace.update(extra or {})
    return trace


# ── RBAC / tenancy wiring ──────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/payroll/singapore/reports/pwm-compliance",
                                  "/api/payroll/singapore/reports/lqs-compliance",
                                  "/api/payroll/singapore/reports/ir21-register"])
def test_generator_routes_use_payroll_operator_rbac_and_the_caller_org(path):
    import inspect

    from app.core.dependencies import get_current_payroll_operator
    from app.main import app

    routes = [r for r in app.routes if getattr(r, "path", None) == path]
    assert [m for r in routes for m in r.methods] == ["POST"]

    def calls(dep, out):
        for d in dep.dependencies:
            out.add(d.call)
            calls(d, out)
        return out
    assert get_current_payroll_operator in calls(routes[0].dependant, set())
    source = inspect.getsource(routes[0].endpoint)
    assert "current_user.organization_id" in source                     # never a client-supplied organization


@pytest.mark.parametrize("role,org", [("employee", 1), (None, 1)])
def test_payroll_operator_dependency_denies_non_operators(role, org):
    from types import SimpleNamespace

    from app.core.dependencies import get_current_payroll_operator
    from app.core.exceptions import ForbiddenException

    with pytest.raises(ForbiddenException):
        get_current_payroll_operator(SimpleNamespace(role=role, organization_id=org, id=9))


@pytest.mark.parametrize("generator,report_type,args", [
    ("generate_sg_pwm_compliance", "SG_PWM_COMPLIANCE", (2026, 7)),
    ("generate_sg_lqs_compliance", "SG_LQS_COMPLIANCE", (2026, 7)),
    ("generate_sg_ir21_register", "SG_IR21_REGISTER", (2026,)),
])
def test_generators_refuse_wrong_type_non_singapore_and_non_active_templates(db, organization, generator, report_type, args):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate

    fn = getattr(service, generator)
    draft = _template(db, f"SG-{report_type}-D", report_type, status="Draft")
    with pytest.raises(BadRequestException, match="not Active"):
        fn(db, organization.id, draft.id, *args)
    wrong = _template(db, "SG-SDL-X", "SG_SDL_MONTHLY")
    with pytest.raises(BadRequestException, match="only for Singapore"):
        fn(db, organization.id, wrong.id, *args)
    foreign = ReportTemplate(template_key=f"UK-{report_type}", name="x", report_type=report_type, jurisdiction_country="UK",
                             reporting_year="2026", version="1.0", status="Active", document_scope="AGGREGATE")
    db.add(foreign)
    db.commit()
    with pytest.raises(BadRequestException, match="only for Singapore"):
        fn(db, organization.id, foreign.id, *args)


# ── SG-PWM-COMPLIANCE ──────────────────────────────────────────────────────

def test_pwm_report_matches_the_preflight_evaluator_end_to_end(db, organization, monkeypatch):
    """A real payroll run: cleaner on basic S$2,000 against the Jul-2026
    floor — the report's result is the same PWM check the preflight runs."""
    from app.modules.payroll import service

    _stub_codes(monkeypatch)
    _active_pack(db, organization)
    cleaner = _employee(db, organization.id, "PWMC", ctc=D("24000"), basic=D("24000"), hra=D("0"),
                        compliance_fields={"nric_fin": "S1234567D", "pwm_sector": "CLEANING", "pwm_group": "G1",
                                           "pwm_job_level": "GENERAL_INDOOR", "ea_workman": "YES",
                                           "ea_manager_executive": "NO"})
    _employee(db, organization.id, "NOPWM")                                   # not PWM-classified → outside report
    run = _generate_payslips(db, organization, date(2026, 7, 31), "Jul 2026")
    preflight = service.sg_payroll_preflight(db, organization.id, run.id)
    pre = [c for c in preflight["checks"] if c.get("employeeId") == cleaner.id and c["code"].startswith("PWM_")]
    template = _template(db, "SG-PWM-COMPLIANCE", "SG_PWM_COMPLIANCE")
    report = service.generate_sg_pwm_compliance(db, organization.id, template.id, 2026, 7, actor_id=MAKER)
    data = report.rendered_data
    assert [r["employeeCode"] for r in data["employeeRows"]] == ["PWMC"]
    row = data["employeeRows"][0]
    assert [c["code"] for c in row["checks"]] == [c["code"] for c in pre]      # identical evaluator + inputs
    assert "PWM_SHORTFALL" in [c["code"] for c in pre]
    assert (row["floorResult"], row["result"], row["floorBasis"]) == ("SHORTFALL", "SHORTFALL", "BASIC")
    assert D(row["floorVariance"]) == D(row["testedWage"]) - D(row["floor"]) < 0
    assert row["nricFinMasked"] == "*****567D" and "S1234567D" not in repr(data)
    assert (data["classification"], data["officialCertification"]) == ("STATUTORY_WORKSPACE", False)
    assert data["pack"]["status"] == "Active" and report.applicable_tax_pack_version == data["pack"]["version"]
    assert data["counts"]["SHORTFALL"] == 1 and report.reporting_period == "2026-07"


def _retail_schedule(db, on):
    from app.modules.payroll.engine.jurisdictions.singapore.labour import pwm_key
    from app.modules.payroll.models import ContributionRate, SgpPwmOvertimeSchedule

    keys = {r.component_key for r in db.query(ContributionRate.component_key)}
    rows = (db.query(SgpPwmOvertimeSchedule)
            .filter(SgpPwmOvertimeSchedule.sector == "RETAIL", SgpPwmOvertimeSchedule.overtime_hours == 10,
                    SgpPwmOvertimeSchedule.effective_from <= on, SgpPwmOvertimeSchedule.effective_to >= on)
            .order_by(SgpPwmOvertimeSchedule.id).all())
    return next(r for r in rows if pwm_key("RETAIL", r.occupation_group, r.job_level) in keys)


# Wages placed relative to the MOM cell itself: S$1 above / below the requirement.
@pytest.mark.parametrize("margin,expected", [(D("1"), "MET"), (D("-1"), "SHORTFALL")])
def test_pwm_overtime_gross_uses_the_mom_schedule_row_rounded_down(db, organization, margin, expected):
    """10.9 overtime hours → MOM rounds down to 10; the requirement is the
    sgp_pwm_overtime_schedules cell in force, with its source and window."""
    from app.modules.payroll import service

    _active_pack(db, organization)
    sched = _retail_schedule(db, date(2026, 7, 31))
    emp = _employee(db, organization.id, "RET", compliance_fields={
        "nric_fin": "T0123456Z", "pwm_sector": "RETAIL", "pwm_group": sched.occupation_group,
        "pwm_job_level": sched.job_level, "ea_workman": "YES", "ea_manager_executive": "NO"})
    run = _finalized_run(db, organization.id, date(2026, 7, 31), "Jul 2026")
    overtime_pay = D("300")
    basic = sched.required_gross + margin - overtime_pay
    _payslip(db, run, emp, _wage_trace(basic, overtime_pay, hours="10.9"))
    template = _template(db, "SG-PWM-COMPLIANCE", "SG_PWM_COMPLIANCE")
    row = service.generate_sg_pwm_compliance(db, organization.id, template.id, 2026, 7).rendered_data["employeeRows"][0]
    assert (row["overtimeHours"], row["overtimeHoursRounded"]) == ("10.9", 10)
    assert D(row["requiredGross"]) == sched.required_gross
    assert D(row["grossIncludingOvertime"]) == basic + overtime_pay
    assert D(row["overtimeVariance"]) == D(row["grossIncludingOvertime"]) - sched.required_gross
    assert row["overtimeResult"] == expected
    assert row["schedule"]["scheduleId"] == sched.id and row["schedule"]["sha256"] == sched.source_sha256
    assert row["schedule"]["effectiveTo"] == sched.effective_to.isoformat() and row["schedule"]["sourceTitle"]
    if expected == "SHORTFALL":
        assert row["averagingWarning"] is True                                  # retail: 3-month averaging (MOM)
    assert row["nricFinMasked"] == "*****456Z"


def test_pwm_report_not_evaluated_and_not_applicable_cases(db, organization):
    from app.modules.payroll import service

    _active_pack(db, organization)
    pwm = {"pwm_sector": "CLEANING", "pwm_group": "G1", "pwm_job_level": "GENERAL_INDOOR", "ea_workman": "YES",
           "ea_manager_executive": "NO", "nric_fin": "S7654321A"}
    twice = _employee(db, organization.id, "TWICE", compliance_fields=pwm)
    foreign = _employee(db, organization.id, "FOR", sgp_cpf_residency_status="FOREIGN", compliance_fields=pwm)
    partial = _employee(db, organization.id, "PART", compliance_fields={**pwm, "pwm_job_level": None})
    notrace = _employee(db, organization.id, "NOTRACE", compliance_fields=pwm)
    r1 = _finalized_run(db, organization.id, date(2026, 7, 15), "Jul A")
    r2 = _finalized_run(db, organization.id, date(2026, 7, 31), "Jul B")
    _payslip(db, r1, twice, _wage_trace("1000"))
    _payslip(db, r2, twice, _wage_trace("1100"))
    _payslip(db, r2, foreign, _wage_trace("3000"))
    _payslip(db, r2, partial, _wage_trace("3000"))
    _payslip(db, r2, notrace, None)
    template = _template(db, "SG-PWM-COMPLIANCE", "SG_PWM_COMPLIANCE")
    rows = {r["employeeCode"]: r for r in
            service.generate_sg_pwm_compliance(db, organization.id, template.id, 2026, 7).rendered_data["employeeRows"]}
    assert rows["TWICE"]["result"] == "NOT_EVALUATED" and "2 payslips" in rows["TWICE"]["reasons"][0]
    assert rows["FOR"]["result"] == "NOT_APPLICABLE"
    assert rows["PART"]["result"] == "NOT_EVALUATED" and rows["PART"]["reasons"]     # classification incomplete
    assert rows["PART"]["floor"] is None                                           # never guessed
    assert rows["NOTRACE"]["result"] == "NOT_EVALUATED" and "trace" in rows["NOTRACE"]["reasons"][0]


def test_pwm_report_without_an_active_pack_evaluates_nothing(db, organization):
    from app.modules.payroll import service
    from scripts.seed_singapore_canonical_pack import seed_singapore

    seed_singapore(db)                                                     # Draft only
    db.commit()
    emp = _employee(db, organization.id, "DRAFTPK", compliance_fields={
        "pwm_sector": "CLEANING", "pwm_group": "G1", "pwm_job_level": "GENERAL_INDOOR"})
    _payslip(db, _finalized_run(db, organization.id, date(2026, 7, 31), "Jul"), emp, _wage_trace("100"))
    template = _template(db, "SG-PWM-COMPLIANCE", "SG_PWM_COMPLIANCE")
    data = service.generate_sg_pwm_compliance(db, organization.id, template.id, 2026, 7).rendered_data
    assert data["pack"] is None
    assert data["employeeRows"][0]["result"] == "NOT_EVALUATED" and data["employeeRows"][0]["floor"] is None


def test_pwm_report_is_tenant_isolated_and_versioned(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import GeneratedReport

    _active_pack(db, organization)
    pwm = {"pwm_sector": "CLEANING", "pwm_group": "G1", "pwm_job_level": "GENERAL_INDOOR"}
    mine = _employee(db, organization.id, "MINE", compliance_fields=pwm)
    other = _other_org(db, "OTHER57")
    stranger = _employee(db, other.id, "STRANGER", compliance_fields=pwm)
    _payslip(db, _finalized_run(db, organization.id, date(2026, 7, 31), "A"), mine, _wage_trace("2500"))
    _payslip(db, _finalized_run(db, other.id, date(2026, 7, 31), "B"), stranger, _wage_trace("2500"))
    template = _template(db, "SG-PWM-COMPLIANCE", "SG_PWM_COMPLIANCE")
    first = service.generate_sg_pwm_compliance(db, organization.id, template.id, 2026, 7)
    assert [r["employeeCode"] for r in first.rendered_data["employeeRows"]] == ["MINE"]
    second = service.generate_sg_pwm_compliance(db, organization.id, template.id, 2026, 7)
    db.refresh(first)
    assert (first.status, second.status) == ("Superseded", "Generated")        # history kept, never overwritten
    assert second.template_version == "1.0"
    assert db.query(GeneratedReport).filter(GeneratedReport.organization_id == other.id).count() == 0


# ── SG-LQS-COMPLIANCE ──────────────────────────────────────────────────────

def test_lqs_report_reads_the_engine_evaluation_end_to_end(db, organization, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    _stub_codes(monkeypatch)
    _active_pack(db, organization)
    monkeypatch.setattr(service, "_sg_employer_hires_foreign_workers", lambda db_, emp_id: True)
    low = _employee(db, organization.id, "LQSLOW", ctc=D("18000"), basic=D("18000"), hra=D("0"))
    ok = _employee(db, organization.id, "LQSOK", ctc=D("30000"), basic=D("30000"), hra=D("0"))
    run = _generate_payslips(db, organization, date(2026, 7, 31), "Jul 2026")
    template = _template(db, "SG-LQS-COMPLIANCE", "SG_LQS_COMPLIANCE")
    data = service.generate_sg_lqs_compliance(db, organization.id, template.id, 2026, 7).rendered_data
    rows = {r["employeeCode"]: r for r in data["employeeRows"]}
    for emp in (low, ok):
        engine = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id,
                                              PayslipItem.employee_id == emp.id).one().sgp_calculation_trace["lqs"]
        row = rows[emp.employee_code]
        assert (row["engineStatus"], row["threshold"], row["wagesConsidered"]) == (
            engine["status"], engine["threshold"], engine["wagesTested"])     # the engine's own figures
    assert (rows["LQSLOW"]["result"], rows["LQSOK"]["result"]) == ("BELOW", "MET")
    assert D(rows["LQSLOW"]["threshold"]) == D("1800")                          # the Jul-2026 pack row, not a constant
    assert rows["LQSOK"]["reference"] and rows["LQSOK"]["headcountBasis"] == "FULL_TIME"
    assert data["counts"] == {"MET": 1, "BELOW": 1, "NOT_EVALUATED": 0, "NOT_APPLICABLE": 0}
    assert data["officialCertification"] is False and "quota" in data["knownGaps"][0]


def test_lqs_report_unsupported_cases_are_explicit(db, organization):
    from app.modules.payroll import service

    _active_pack(db, organization)
    part = _employee(db, organization.id, "PT", employment_type="Part-time")
    blank = _employee(db, organization.id, "BLANK")
    run = _finalized_run(db, organization.id, date(2026, 7, 31), "Jul")
    _payslip(db, run, part, _wage_trace("900", extra={"lqs": {
        "status": "BLOCKED", "threshold": "10.50", "detail": "Part-time LQS is an hourly test — no attendance hours"}}))
    _payslip(db, run, blank, _wage_trace("900"))
    template = _template(db, "SG-LQS-COMPLIANCE", "SG_LQS_COMPLIANCE")
    rows = {r["employeeCode"]: r for r in
            service.generate_sg_lqs_compliance(db, organization.id, template.id, 2026, 7).rendered_data["employeeRows"]}
    assert rows["PT"]["result"] == "NOT_EVALUATED" and "hourly" in rows["PT"]["reason"]
    assert rows["PT"]["headcountBasis"] == "PART_TIME"
    assert rows["BLANK"]["result"] == "NOT_EVALUATED" and rows["BLANK"]["threshold"] is None
    assert rows["BLANK"]["proRating"].startswith("NOT_EVALUATED")


# ── SG-IR21-REGISTER ───────────────────────────────────────────────────────

def test_ir21_register_follows_the_case_lifecycle(db, organization):
    from app.modules.payroll import service

    _active_pack(db, organization)
    ep = _employee(db, organization.id, "EP1", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP",
                   compliance_fields={"nric_fin": "G1234567X"})
    spr = _employee(db, organization.id, "SPR1", sgp_cpf_residency_status="SPR", compliance_fields={"nric_fin": "S7777777B"})
    run = _finalized_run(db, organization.id, date(2026, 9, 30), "Sep")
    _payslip(db, run, ep, _wage_trace("5000"), gross="5000")
    open_case = service.create_sg_ir21_case(db, organization.id, ep.id, "CESSATION", date(2026, 11, 30),
                                            date(2026, 9, 1), actor_id=MAKER)
    closed = service.create_sg_ir21_case(db, organization.id, spr.id, "CESSATION", date(2026, 12, 31),
                                         date(2026, 10, 1), actor_id=MAKER)
    service.transition_sg_ir21_case(db, organization.id, closed.id, "CANCELLED", actor_id=CHECKER, reason="withdrawn")
    template = _template(db, "SG-IR21-REGISTER", "SG_IR21_REGISTER")
    report = service.generate_sg_ir21_register(db, organization.id, template.id, 2026, actor_id=MAKER,
                                               today=date(2026, 11, 5))
    data = report.rendered_data
    rows = {r["caseId"]: r for r in data["caseRows"]}
    a, b = rows[open_case.id], rows[closed.id]
    view = service.serialize_sg_ir21_case(db, open_case)
    assert (a["status"], a["workflowState"], a["holdInForce"]) == ("DRAFT", "OPEN", True)
    assert a["withholdingAmount"] == view["currentHeldAmount"]                  # the lifecycle's own held total
    assert a["fileByDate"] == view["fileByDate"] and a["fileByOverdue"] is True   # 5 Nov > file-by (1 month before)
    assert a["outstandingAction"].startswith("File Form IR21") and a["approvalStatus"] == "NOT_REQUIRED"
    assert (b["status"], b["workflowState"], b["outstandingAction"]) == ("CANCELLED", "CLOSED", None)
    assert b["approvalStatus"] == "APPROVED" and b["makerChecker"] == {
        "preparedById": MAKER, "approvedById": CHECKER, "distinctApprover": True}
    assert b["evidence"]["auditEntries"] >= 2 and b["evidence"]["legalReference"].startswith("IRAS")
    assert a["nricFinMasked"] == "*****567X" and "G1234567X" not in repr(data)
    assert data["openCases"] == 1 and data["overdueFilings"] == 1 and data["officialCertification"] is False
    assert report.scope_key == "IR21_REGISTER:2026"


def test_ir21_register_is_tenant_isolated(db, organization):
    from app.modules.payroll import service

    _active_pack(db, organization)
    other = _other_org(db, "IR21OTHER")
    stranger = _employee(db, other.id, "STR", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="EP")
    service.create_sg_ir21_case(db, other.id, stranger.id, "CESSATION", date(2026, 11, 30), date(2026, 9, 1), actor_id=MAKER)
    template = _template(db, "SG-IR21-REGISTER", "SG_IR21_REGISTER")
    data = service.generate_sg_ir21_register(db, organization.id, template.id, 2026).rendered_data
    assert data["caseRows"] == [] and data["openCases"] == 0


# ── Generic generator still refuses the three types ────────────────────────

@pytest.mark.parametrize("report_type", ["SG_PWM_COMPLIANCE", "SG_LQS_COMPLIANCE", "SG_IR21_REGISTER"])
def test_generic_generator_refuses_dedicated_sg_types(db, organization, report_type):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    t = _template(db, f"SG-{report_type}", report_type)
    with pytest.raises(BadRequestException, match="dedicated Singapore generator"):
        service.generate_report_from_template(db, organization.id, t.id, payroll_run_id=1)


# ── Super Admin summary: pack section, Draft vs Active, lifecycle evidence ─

def test_summary_pack_section_distinguishes_draft_from_active(db):
    from app.modules.payroll import service
    from scripts.seed_singapore_canonical_pack import seed_singapore

    none = service.get_sg_statutory_summary(db, date(2026, 9, 25))["sections"][0]
    assert (none["key"], none["status"]) == ("pack", "NOT_CONFIGURED")
    pack = seed_singapore(db)
    db.commit()
    summary = service.get_sg_statutory_summary(db, date(2026, 9, 25))
    draft = summary["sections"][0]
    assert (draft["status"], draft["inForce"], draft["values"]["valuesFromActivePack"]) == ("BLOCKED", False, False)
    assert "not in force" in draft["notes"][0]
    statutory = [s for s in summary["sections"] if s["key"] in ("cpf", "sdl", "shg", "lqs", "ir21")]
    assert all(s["status"] == "BLOCKED" and s["inForce"] is False and s["configurationStatus"] == "CONFIGURED"
               for s in statutory)
    pack.status = "Active"
    db.commit()
    active = service.get_sg_statutory_summary(db, date(2026, 9, 25))
    assert active["sections"][0]["status"] == "CONFIGURED" and active["sections"][0]["inForce"] is True
    assert next(s for s in active["sections"] if s["key"] == "cpf")["status"] == "CONFIGURED"


def test_summary_exposes_template_lifecycle_evidence(db, monkeypatch):
    import scripts.seed_statutory_report_templates as seed
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate

    monkeypatch.setattr(seed, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed.run()
    t = db.query(ReportTemplate).filter(ReportTemplate.template_key == "SG-PWM-COMPLIANCE").one()
    t.updated_by_id = MAKER
    db.commit()
    service.set_report_template_approver(db, t.id, actor_id=CHECKER)            # Draft → Approved
    service.set_report_template_status(db, t.id, "Published", actor_id=MAKER)   # 5.8: Active only via Published
    service.set_report_template_status(db, t.id, "Active", actor_id=MAKER)
    rows = {r["templateKey"]: r for r in next(
        s for s in service.get_sg_statutory_summary(db, date(2026, 9, 25))["sections"]
        if s["key"] == "reportTemplates")["values"]["templates"]}
    pwm = rows["SG-PWM-COMPLIANCE"]
    assert (pwm["status"], pwm["approvedById"], pwm["generatable"], pwm["editable"]) == ("Active", CHECKER, True, False)
    assert pwm["approvedAt"] and pwm["lastStatusChangeAt"] and pwm["auditEntries"] >= 3
    assert pwm["versionCount"] == 1 and pwm["sourceReferences"]
    assert rows["SG-IR8A"]["approvedAt"] is None and rows["SG-IR8A"]["editable"] is True
    assert all(r["officialCertification"] is False for r in rows.values())
    section = next(s for s in service.get_sg_statutory_summary(db, date(2026, 9, 25))["sections"]
                   if s["key"] == "reportTemplates")
    assert (section["values"]["present"], section["values"]["active"], section["values"]["generatorTypes"]) == (11, 1, 11)
    # Seed re-run leaves the Active template untouched (never demoted).
    seed.run()
    db.refresh(t)
    assert (t.status, t.approved_by_id) == ("Active", CHECKER)
