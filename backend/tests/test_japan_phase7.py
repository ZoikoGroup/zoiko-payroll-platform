"""Japan Phase 7: the read routes the screens need (bonus reports, employee
summary) and the payslip snapshot the run detail renders. Synthetic values."""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import NotFoundException
from app.modules.payroll import japan_service as jp
from app.modules.payroll.models import (
    PayrollEmployee, PayrollJpAttendanceApproval, PayrollJpSocialInsuranceEvent,
    PayrollJpWorkerTaxProfile, PayrollRun, PayslipItem,
)


@pytest.fixture()
def employee(db, organization):
    row = PayrollEmployee(organization_id=organization.id, employee_code="JP-P7-1",
                          name="Synthetic Employee", country_code="JP")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _bonus_event(db, organization, employee, paid_on, due_on, status="CREATED"):
    row = PayrollJpSocialInsuranceEvent(
        organization_id=organization.id, employee_id=employee.id, event_type="BONUS",
        effective_from=paid_on, bonus_paid_on=paid_on, sba_amount=Decimal("500000"),
        report_due_on=due_on, submission_status=status, created_by_id=1)
    db.add(row)
    db.commit()
    return row


def test_bonus_reports_are_listed_oldest_due_first_with_an_overdue_flag(db, organization, employee):
    _bonus_event(db, organization, employee, date(2026, 7, 10), date(2026, 7, 15))
    _bonus_event(db, organization, employee, date(2026, 6, 10), date(2026, 6, 15), status="ACCEPTED")
    _bonus_event(db, organization, employee, date(2026, 12, 10), date(2026, 12, 15))

    rows = jp.list_bonus_reports(db, organization.id, today=date(2026, 8, 1))
    assert [r["reportDueOn"] for r in rows] == ["2026-06-15", "2026-07-15", "2026-12-15"]
    assert [r["overdue"] for r in rows] == [False, True, False]     # an accepted report is never overdue
    assert rows[1]["sbaAmount"] == "500000"

    open_rows = jp.list_bonus_reports(db, organization.id, status="OPEN", today=date(2026, 8, 1))
    assert [r["reportDueOn"] for r in open_rows] == ["2026-07-15", "2026-12-15"]


def test_bonus_reports_are_scoped_to_the_organisation(db, organization, employee):
    _bonus_event(db, organization, employee, date(2026, 7, 10), date(2026, 7, 15))
    assert jp.list_bonus_reports(db, organization.id + 1) == []


def test_employee_summary_reports_missing_active_and_ambiguous_versions(db, organization, employee):
    got = jp.employee_summary(db, organization.id, employee.id, as_of=date(2026, 6, 15))
    assert got["taxProfile"] == {"state": "MISSING", "row": None}
    assert got["countryCode"] == "JP" and got["myNumbers"] == []

    for start in (date(2026, 1, 1), date(2026, 4, 1)):
        db.add(PayrollJpWorkerTaxProfile(
            organization_id=organization.id, employee_id=employee.id, effective_from=start,
            residency_status="RESIDENT", declaration_class="PRIMARY", dependants_count=0,
            status="ACTIVE"))
    db.add(PayrollJpAttendanceApproval(
        organization_id=organization.id, employee_id=employee.id, period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30), fingerprint="0" * 64, row_count=20, status="REQUESTED",
        created_by_id=1))
    db.commit()
    got = jp.employee_summary(db, organization.id, employee.id, as_of=date(2026, 6, 15))
    # Two ACTIVE versions in force are reported as ambiguous, never resolved.
    assert got["taxProfile"]["state"] == "AMBIGUOUS" and got["taxProfile"]["count"] == 2
    assert got["attendanceApprovals"][0]["status"] == "REQUESTED"
    assert got["attendanceApprovals"][0]["rowCount"] == 20


def test_employee_summary_refuses_another_organisations_employee(db, organization, employee):
    with pytest.raises(NotFoundException):
        jp.employee_summary(db, organization.id + 1, employee.id)


def test_new_routes_sit_behind_the_japan_router_guard():
    from app.modules.payroll.japan_org_router import router

    paths = {route.path for route in router.routes}
    assert {"/japan/bonus-reports", "/japan/employees/{employee_id}/summary"} <= paths
    assert any(getattr(dep.dependency, "__name__", "") == "require_japan_tenant"
               for dep in router.dependencies)


def _payslip(db, organization, employee, country, snapshot):
    run = PayrollRun(organization_id=organization.id, period_label="2026-06",
                     period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                     pay_date=date(2026, 6, 25), status="Draft")
    db.add(run)
    db.flush()
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code=country,
                       jp_calculation_snapshot=snapshot)
    db.add(item)
    db.commit()
    return item, run


def test_payslip_carries_the_jp_result_without_the_frozen_inputs(db, organization, employee):
    from app.modules.payroll.service import _serialize_payslip

    snapshot = {"jp_wht": "5000", "jp_bonus": None, "trace": {"jurisdiction": "JP"},
                "frozenContext": {"rateMap": {"jp_epi_total": {"flat_amount": "18.3"}}}}
    item, run = _payslip(db, organization, employee, "JP", snapshot)
    got = _serialize_payslip(item, run, "JP")["jpCalculationSnapshot"]
    assert got["jp_wht"] == "5000" and got["trace"] == {"jurisdiction": "JP"}
    assert "frozenContext" not in got


def test_payslip_snapshot_is_gated_to_japan(db, organization, employee):
    from app.modules.payroll.service import _serialize_payslip

    item, run = _payslip(db, organization, employee, "ZA", {"jp_wht": "1"})
    assert _serialize_payslip(item, run, "ZA")["jpCalculationSnapshot"] is None
