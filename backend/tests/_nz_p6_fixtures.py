"""Shared SQLite fixtures for the New Zealand Phase 6 service tests: a signed
TEST pack (build_p6_pack), an employee on a FIXED Mon-Fri pattern with a
fortnightly salary of 2,400 (agreement OWP 1,200 / week), an ACTIVE employment
and a year of weekly gross-earnings ledger rows at 1,300."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_leave_service as lv
from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.models import PayrollEmployee, PayrollNzGrossEarningsLedger
from tests._nz_engine_helpers import build_p6_pack

D = Decimal
HOLIDAYS = [dict(rule_type=content.NZ_PUBLIC_HOLIDAY_RULE, effective_from=date(2026, 12, 25), effective_to=None,
                 rate_label="TEST Christmas", jurisdiction_state=None)]


@pytest.fixture(autouse=True)
def _request_codes(monkeypatch):
    from app.core import code_generation

    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter):05d}")


def use_pack(monkeypatch, **overrides):
    rate_map, slabs = build_p6_pack(overrides, extra_slabs=HOLIDAYS)
    monkeypatch.setattr(nzs, "_nz_pack_in_force",
                        lambda db, on: (rate_map, slabs, SimpleNamespace(tax_year="2026-27")))
    return rate_map, slabs


@pytest.fixture()
def signed(monkeypatch):
    return use_pack(monkeypatch)


def make_employee(db, organization, code="NZ-1"):
    row = PayrollEmployee(organization_id=organization.id, employee_code=code, name="Aroha Ngata",
                          date_of_birth=date(1996, 5, 1), country_code="NZ", work_state="Auckland",
                          pay_frequency="Fortnightly", basic=D("2400"))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def employ(db, organization, employee, start=date(2025, 5, 12)):
    row = lv.record_nz_employment(db, organization.id, employee.id, {"start_date": start}, 1, "hired")
    lv.approve_nz_employment(db, organization.id, row.id, 2)
    pattern = nzs.record_nz_work_pattern(db, organization.id, employee.id, {
        "effective_from": start, "pattern_type": "FIXED", "hours_source": "CONTRACT",
        "contracted_hours_per_week": 40, "contracted_days_per_week": 5,
        "weekly_schedule": {"MON": 8, "TUE": 8, "WED": 8, "THU": 8, "FRI": 8, "SAT": 0, "SUN": 0}}, 1, "contract")
    nzs.approve_nz_work_pattern(db, organization.id, pattern.id, 2)
    db.commit()
    return row


def add_ledger(db, organization, employee, employment, end=date(2026, 5, 29), weeks=52, weekly="1300"):
    for k in range(weeks):
        period_end = end - timedelta(weeks=k)
        db.add(PayrollNzGrossEarningsLedger(
            organization_id=organization.id, employee_id=employee.id, employment_id=employment.id,
            pay_date=period_end, period_start=period_end - timedelta(days=6), period_end=period_end,
            component="SALARY", amount=D(weekly), included=True, treatment="INCLUDED",
            reason="HOLIDAY_GROSS:SALARY INCLUDED", days_worked=D(5)))
    db.commit()


def request(db, organization, employee, leave_type, start, end):
    from app.modules.payroll import service

    data = SimpleNamespace(employeeId=employee.id, leaveType=leave_type, startDate=start, endDate=end, reason=None,
                           source="manual")
    req = service.create_payroll_leave_request(db, data, organization.id)
    service.review_payroll_leave_request(db, req["id"], SimpleNamespace(status="approved"), organization.id, 2)
    return req
