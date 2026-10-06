"""
tests/test_hong_kong_report_closure.py
--------------------------------------
Final reporting closure for Hong Kong:
* employer BR number reaches every rendered report (the schema key is br_number);
* the employee termination statement (spec document service) through the shared
  report architecture — APPROVED results only, Active template only, history;
* exact-year template resolution with no fallback; historical reports stay tied
  to their template version; regeneration never picks up a changed statutory
  value (reports read committed payslips, never recalculate);
* the seeded BIR56A / IR56B filing calendar agrees with the engine's own
  pack-driven due dates;
* MPF enrolment state (due / overdue / enrolled / exempt).
"""

from datetime import date
from decimal import Decimal as D

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk, _employee, _item, _month, _other_org, _profile  # noqa: F401


def _seeded(db, key, status="Active"):
    from tests.test_hong_kong_reports import _seeded as seeded

    return seeded(db, key, status)


def _months(db, hk, months=(1, 2, 3)):
    return {m: _month(db, hk.org, m) for m in months}


def test_employer_br_number_is_rendered_on_hk_reports(db, hk):
    from app.modules.payroll import hong_kong_service, service

    _months(db, hk)
    hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", None)
    report = hong_kong_service.generate_hong_kong_ir56b(db, hk.org.id, _seeded(db, "HK-IR56B").id, hk.emp.id, "2025/26")
    assert report.rendered_data["employer"]["employer_br_number"] == "12345678"


def _approved_termination(db, hk):
    from app.modules.payroll import hong_kong_service

    hk.emp.date_of_leaving = date(2026, 6, 30)
    db.commit()
    result = hong_kong_service.calculate_termination(db, hk.org.id, hk.emp.id, {
        "terminationDate": "2026-06-30", "reason": "RESIGNATION", "postTransitionWage": "20000",
        "finalWages": "20000", "annualLeavePay": "3000", "holidayPay": "0"}, MAKER.id)
    return result


def test_termination_statement_renders_only_an_approved_calculation(db, hk):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import hong_kong_service, service

    result = _approved_termination(db, hk)
    tmpl = _seeded(db, "HK-TERMINATION-STATEMENT")
    with pytest.raises(BadRequestException, match="APPROVED"):
        hong_kong_service.generate_hong_kong_termination_statement(db, hk.org.id, tmpl.id, result.id)
    hong_kong_service.approve_termination(db, hk.org.id, result.id, CHECKER.id)
    db.commit()
    report = hong_kong_service.generate_hong_kong_termination_statement(db, hk.org.id, tmpl.id, result.id, MAKER.id)
    values = report.rendered_data["employees"][0]["values"]
    assert report.report_type == "HK_TERMINATION_STATEMENT" and report.employee_id == hk.emp.id
    assert values["evidence_hash"] == result.evidence_hash and values["final_wages"] == 20000.0
    assert values["annual_leave_pay"] == 3000.0 and values["employee_hkid"] != "A123456(3)"
    again = hong_kong_service.generate_hong_kong_termination_statement(db, hk.org.id, tmpl.id, result.id, MAKER.id)
    db.refresh(report)
    assert report.status == "Superseded" and again.status == "Generated"       # history, never overwritten
    with pytest.raises(NotFoundException):
        hong_kong_service.generate_hong_kong_termination_statement(db, _other_org(db, "HKTSO").id, tmpl.id, result.id)


def test_termination_statement_refuses_a_draft_template(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service, service

    result = _approved_termination(db, hk)
    hong_kong_service.approve_termination(db, hk.org.id, result.id, CHECKER.id)
    db.commit()
    draft = _seeded(db, "HK-TERMINATION-STATEMENT", status="Draft")
    with pytest.raises(BadRequestException):
        hong_kong_service.generate_hong_kong_termination_statement(db, hk.org.id, draft.id, result.id)


def test_template_resolution_is_exact_year_with_no_fallback(db, hk):
    from app.modules.payroll import service

    _seeded(db, "HK-IR56B")
    found = service.get_applicable_report_template_for_org(db, hk.org.id, "2025/26", "HK_IR56B")
    assert found["template"] is not None and found["template"].jurisdiction_country == "HK"
    assert service.get_applicable_report_template_for_org(db, hk.org.id, "2026/27", "HK_IR56B")["template"] is None
    assert service.get_applicable_report_template_for_org(db, hk.org.id, "2025/26", "P60")["template"] is None


def test_historical_report_stays_on_its_template_version_and_a_new_version_supersedes(db, hk):
    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.models import ReportTemplate

    _months(db, hk)
    hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", None)
    v1 = _seeded(db, "HK-IR56B")
    first = hong_kong_service.generate_hong_kong_ir56b(db, hk.org.id, v1.id, hk.emp.id, "2025/26")
    v2 = ReportTemplate(template_key="HK-IR56B", name=v1.name, report_type="HK_IR56B", jurisdiction_country="HK",
                        reporting_year="2025/26", version="1.1", status="Active", document_scope="PER_EMPLOYEE")
    db.add(v2)
    db.commit()
    second = hong_kong_service.generate_hong_kong_ir56b(db, hk.org.id, v2.id, hk.emp.id, "2025/26")
    db.refresh(first)
    assert (first.template_version, first.report_template_id) == ("1.0", v1.id)
    assert first.rendered_data["templateSnapshot"]["version"] == "1.0"
    assert second.template_version == "1.1"
    assert first.status == "Superseded" and second.status == "Generated"     # one live report across versions


def test_regeneration_never_uses_a_changed_statutory_value(db, hk):
    """Reports render COMMITTED payslips; editing a pack row afterwards cannot
    change an already-paid period's reported figures."""
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate

    runs = _months(db, hk, (4,))
    tmpl = _seeded(db, "HK-MPF-CONTRIBUTION-RECORD")
    before = hong_kong_service.generate_hong_kong_mpf_contribution_record(db, hk.org.id, tmpl.id, hk.emp.id, "2026-04")
    row = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == hk.packs[1].id,
                                             ContributionRate.component_key == "mpf_employee_rate").one())
    row.employee_rate_pct = D("0.0600")
    db.commit()
    after = hong_kong_service.generate_hong_kong_mpf_contribution_record(db, hk.org.id, tmpl.id, hk.emp.id, "2026-04")
    assert after.rendered_data["totals"] == before.rendered_data["totals"]
    assert _item(db, runs[4], hk.emp).employee_pension == D("1000.00")


def test_seeded_filing_calendar_matches_the_engine_due_dates(db, hk):
    from scripts.seed_statutory_report_templates import seed_hong_kong
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.engine.jurisdictions.hong_kong import ird as hk_ird
    from app.modules.payroll.engine.jurisdictions.hong_kong.common import year_of_assessment_bounds
    from app.modules.payroll.models import StatutoryFilingCalendar

    seed_hong_kong(db)
    rows = db.query(StatutoryFilingCalendar).filter(StatutoryFilingCalendar.jurisdiction_country == "HK").all()
    assert rows
    for r in rows:
        ya = r.period_key.split("-", 1)[1]
        _start, end = year_of_assessment_bounds(ya)
        engine_due = hk_ird.due_date(r.report_type.replace("HK_", ""), hong_kong_service.reporting_timing(db, end), ya=ya)
        assert r.due_date == engine_due, (r.report_type, ya, r.due_date, engine_due)


def _enrolment_codes(db, hk, today):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll import service

    out = hong_kong_service.hk_employer_readiness(db, hk.org.id, today=today)
    return {(c["code"], c.get("employeeCode")) for c in out["checks"] if c["code"].startswith("MPF_ENROL")}


def test_mpf_enrolment_state_due_overdue_and_enrolled(db, hk):
    new = _employee(db, hk.org.id, "HKNEW", date_of_joining=date(2026, 5, 1),
                    compliance_fields={"hkid": "A123456(3)"})                     # no MPF member account
    _profile(db, new, hk.org.id, "2026-05-01")
    assert ("MPF_ENROLMENT_DUE", "HKNEW") in _enrolment_codes(db, hk, date(2026, 6, 1))
    assert ("MPF_ENROLMENT_OVERDUE", "HKNEW") in _enrolment_codes(db, hk, date(2026, 7, 15))
    assert ("MPF_ENROLLED", "HK1") in _enrolment_codes(db, hk, date(2026, 7, 15))  # member account recorded
    new.compliance_fields = {"hkid": "A123456(3)", "mpf_member_account": "MB-NEW"}
    db.commit()
    assert ("MPF_ENROLLED", "HKNEW") in _enrolment_codes(db, hk, date(2026, 7, 15))


def test_mpf_enrolment_deadline_comes_from_the_pack_row(db, hk):
    from app.modules.payroll.models import ContributionRate

    new = _employee(db, hk.org.id, "HKNEW2", date_of_joining=date(2026, 5, 1), compliance_fields={"hkid": "A123456(3)"})
    _profile(db, new, hk.org.id, "2026-05-01")
    row = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == hk.packs[1].id,
                                             ContributionRate.component_key == "mpf_regular_employee_days").one())
    row.flat_amount = D("90")                      # a (test-only) different pack value moves the deadline
    db.commit()
    assert ("MPF_ENROLMENT_DUE", "HKNEW2") in _enrolment_codes(db, hk, date(2026, 7, 15))


def test_exempt_employee_has_no_enrolment_check(db, hk):
    old = _employee(db, hk.org.id, "HKOLD", date_of_birth=date(1955, 1, 1), date_of_joining=date(2026, 5, 1),
                    compliance_fields={"hkid": "A123456(3)"})
    _profile(db, old, hk.org.id, "2026-05-01")
    assert not {c for c in _enrolment_codes(db, hk, date(2026, 7, 15)) if c[1] == "HKOLD"}


def test_empf_contribution_day_comes_from_the_pack_row(db, hk):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import ContributionRate

    _months(db, hk, (4,))
    assert hong_kong_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id).contribution_day == date(2026, 5, 10)
    row = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == hk.packs[1].id,
                                             ContributionRate.component_key == "mpf_contribution_day").one())
    row.flat_amount = D("12")                 # a (test-only) different pack value — no literal in the code
    db.commit()
    assert hong_kong_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id).contribution_day == date(2026, 5, 12)


def test_termination_and_average_wage_lists_let_a_second_operator_find_and_approve(db, hk):
    from app.core.exceptions import NotFoundException
    from app.modules.payroll import hong_kong_service

    result = _approved_termination(db, hk)
    rows = hong_kong_service.list_termination_results(db, hk.org.id)
    assert [r["id"] for r in rows] == [result.id] and rows[0]["status"] == "CALCULATED"
    assert rows[0]["createdById"] == MAKER.id
    hong_kong_service.approve_termination(db, hk.org.id, rows[0]["id"], CHECKER.id)
    assert hong_kong_service.list_termination_results(db, hk.org.id)[0]["status"] == "APPROVED"
    assert hong_kong_service.list_termination_results(db, _other_org(db, "HKLISTO").id) == []
    for m in (1, 2, 3, 4, 5):
        _month(db, hk.org, m)
    snap = hong_kong_service.calculate_average_wage(db, hk.org.id, hk.emp.id, "HOLIDAY_PAY", date(2026, 6, 15), [], MAKER.id)
    hong_kong_service.request_average_wage_override(db, hk.org.id, snap.id, D("700"), "documented error", "EV-1", MAKER.id)
    listed = hong_kong_service.list_average_wage_snapshots(db, hk.org.id, hk.emp.id)
    assert D(listed[0]["overrideRequested"]) == D("700") and listed[0]["overrideRequestedById"] == MAKER.id
    with pytest.raises(NotFoundException):
        hong_kong_service.list_average_wage_snapshots(db, _other_org(db, "HKLISTO2").id, hk.emp.id)
