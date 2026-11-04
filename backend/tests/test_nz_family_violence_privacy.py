"""New Zealand family-violence leave privacy (ZP-NZ-ENG-001 Phase 5, NZ-023).

No reason text is ever accepted; the leave is restricted, visible only with
NZ_FAMILY_VIOLENCE_VIEW (granted by another org admin, with a reason); every
restricted read is access-logged; and no shared surface (generic leave list,
attendance, allocation, activity log, audit, email, application log) names
it."""
import json
import logging
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException, ForbiddenException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_leave_service as lv
from app.modules.payroll import service
from app.modules.payroll.models import (
    PayrollActivityLog, PayrollAttendanceRecord, PayrollEmployee, PayrollLeaveAllocation, PayrollNzLeaveEvent,
    PersonalDataAccessEvent, TaxConfigurationAudit,
)
from tests._nz_engine_helpers import build_pack

FV = "nz_family_violence"


@pytest.fixture(autouse=True)
def _request_codes(monkeypatch):
    from app.core import code_generation

    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter):05d}")


@pytest.fixture()
def emails(monkeypatch):
    sent = []
    import app.modules.communications.service as comms

    monkeypatch.setattr(comms, "queue_email", lambda *a, **k: sent.append(repr((a, k))))
    return sent


@pytest.fixture()
def setup(db, organization, monkeypatch):
    from app.modules.auth.models import User, UserRole

    rate_map, slabs = build_pack()
    monkeypatch.setattr(nzs, "_nz_pack_in_force",
                        lambda db, on: (rate_map, slabs, SimpleNamespace(tax_year="2026-27")))

    def user(email, role):
        row = User(email=email, hashed_password="x", role=role, organization_id=organization.id, first_name="T",
                   last_name=email[:4], is_active=True)
        db.add(row)
        db.commit()
        return row

    admin_a = user("nz-admin-a@zoikotest.example.com", UserRole.ORG_ADMIN)
    admin_b = user("nz-admin-b@zoikotest.example.com", UserRole.ORG_ADMIN)
    clerk = user("nz-clerk@zoikotest.example.com", UserRole.PAYROLL_ADMIN)
    employee = PayrollEmployee(organization_id=organization.id, employee_code="NZ-1", name="Aroha Ngata",
                               email="aroha@zoikotest.example.com", country_code="NZ")
    db.add(employee)
    db.commit()
    employment = lv.record_nz_employment(db, organization.id, employee.id, {"start_date": date(2025, 5, 12)},
                                         admin_a.id, "hired")
    lv.approve_nz_employment(db, organization.id, employment.id, admin_b.id)
    pattern = nzs.record_nz_work_pattern(db, organization.id, employee.id, {
        "effective_from": date(2025, 5, 12), "pattern_type": "FIXED", "hours_source": "CONTRACT",
        "contracted_days_per_week": 5,
        "weekly_schedule": {"MON": 8, "TUE": 8, "WED": 8, "THU": 8, "FRI": 8, "SAT": 0, "SUN": 0}}, admin_a.id, "x")
    nzs.approve_nz_work_pattern(db, organization.id, pattern.id, admin_b.id)
    lv.vest_entitlements(db, organization.id, date(2026, 6, 1))
    db.commit()
    return SimpleNamespace(org=organization, a=admin_a, b=admin_b, clerk=clerk, employee=employee)


def _fv_request(db, s, reason=None):
    data = SimpleNamespace(employeeId=s.employee.id, leaveType=FV, startDate=date(2026, 6, 1),
                           endDate=date(2026, 6, 2), reason=reason, source="manual")
    req = service.create_payroll_leave_request(db, data, s.org.id)
    service.review_payroll_leave_request(db, req["id"], SimpleNamespace(status="approved"), s.org.id, s.b.id)
    return req


def test_reason_refused_on_create(db, setup):
    with pytest.raises(BadRequestException, match="never records a reason"):
        _fv_request(db, setup, reason="details of the incident")
    assert db.query(PayrollNzLeaveEvent).count() == 0
    from app.modules.payroll.models import PayrollLeaveRequest
    assert db.query(PayrollLeaveRequest).count() == 0                               # refused, not stored


def test_events_hidden_without_permission(db, setup):
    _fv_request(db, setup)
    event = db.query(PayrollNzLeaveEvent).one()
    assert (event.leave_type, event.restricted, event.quantity) == ("FAMILY_VIOLENCE", True, 2)
    assert lv.visible_events(db, setup.org.id, setup.clerk.id, setup.employee.id) == []
    assert db.query(PersonalDataAccessEvent).count() == 0


def test_events_visible_with_permission_and_access_logged(db, setup):
    _fv_request(db, setup)
    lv.grant_family_violence_view(db, setup.org.id, setup.a.id, setup.clerk.id, "case officer")
    events = lv.visible_events(db, setup.org.id, setup.clerk.id, setup.employee.id)
    assert [e["leaveType"] for e in events] == ["FAMILY_VIOLENCE"]
    log = db.query(PersonalDataAccessEvent).one()
    assert (log.action, log.actor_id, log.employee_id, log.purpose, log.jurisdiction_country) == (
        "VIEW_RESTRICTED_LEAVE", setup.clerk.id, setup.employee.id, "NZ_FAMILY_VIOLENCE_LEAVE", "NZ")
    lv.revoke_family_violence_view(db, setup.org.id, setup.b.id, setup.clerk.id, "case closed")
    assert lv.visible_events(db, setup.org.id, setup.clerk.id, setup.employee.id) == []


def test_grant_not_to_self_and_needs_reason(db, setup):
    with pytest.raises(BadRequestException, match="yourself"):
        lv.grant_family_violence_view(db, setup.org.id, setup.a.id, setup.a.id, "self")
    with pytest.raises(BadRequestException, match="reason"):
        lv.grant_family_violence_view(db, setup.org.id, setup.a.id, setup.clerk.id, " ")
    with pytest.raises(ForbiddenException):
        lv.grant_family_violence_view(db, setup.org.id, setup.clerk.id, setup.b.id, "clerk cannot grant")
    lv.grant_family_violence_view(db, setup.org.id, setup.a.id, setup.clerk.id, "case officer")
    with pytest.raises(BadRequestException, match="already holds"):
        lv.grant_family_violence_view(db, setup.org.id, setup.b.id, setup.clerk.id, "again")
    assert [h["userId"] for h in lv.family_violence_view_holders(db, setup.org.id)] == [setup.clerk.id]


def test_generic_leave_list_hides_nz_fv_requests(db, setup):
    req = _fv_request(db, setup)
    rows = service.get_payroll_leave_requests(db, setup.org.id, viewer_id=setup.clerk.id)
    assert req["id"] not in [r["id"] for r in rows]
    assert req["id"] not in [r["id"] for r in service.get_payroll_leave_requests(db, setup.org.id)]
    lv.grant_family_violence_view(db, setup.org.id, setup.a.id, setup.clerk.id, "case officer")
    rows = service.get_payroll_leave_requests(db, setup.org.id, viewer_id=setup.clerk.id)
    assert req["id"] in [r["id"] for r in rows]


def test_balances_omit_fv_without_permission(db, setup):
    _fv_request(db, setup)
    hidden = lv.balances(db, setup.org.id, setup.clerk.id, setup.employee.id)
    assert "familyViolence" not in hidden and hidden["legalEntitlement"] is True
    assert "restricted" not in hidden["planningView"]["balances"]
    assert hidden["planningView"]["label"].startswith("Planning view")
    assert hidden["annual"]["unit"] == "WEEKS"
    lv.grant_family_violence_view(db, setup.org.id, setup.a.id, setup.clerk.id, "case officer")
    shown = lv.balances(db, setup.org.id, setup.clerk.id, setup.employee.id)
    assert shown["familyViolence"]["balance"] == "8"
    assert db.query(PersonalDataAccessEvent).filter(PersonalDataAccessEvent.action == "VIEW_RESTRICTED_LEAVE").count() == 1


def test_logs_and_exports_have_no_fv_detail(db, setup, emails, caplog):
    caplog.set_level(logging.DEBUG)
    req = _fv_request(db, setup)
    service.review_payroll_leave_request(db, req["id"], SimpleNamespace(status="rejected"), setup.org.id, setup.b.id)
    attendance = db.query(PayrollAttendanceRecord).filter(PayrollAttendanceRecord.employee_id == setup.employee.id)
    alloc = db.query(PayrollLeaveAllocation).filter(PayrollLeaveAllocation.employee_id == setup.employee.id).one()
    surfaces = [
        [(r.leave_type, r.notes) for r in attendance],
        alloc.leave_balances,
        [r.description for r in db.query(PayrollActivityLog).all()],
        [(r.entity_type, r.old_value, r.new_value, r.reason) for r in db.query(TaxConfigurationAudit).all()],
        emails,
        caplog.text,
    ]
    blob = json.dumps(surfaces, default=str).lower()
    assert "family" not in blob and "violence" not in blob and FV not in blob
    assert "restricted" in json.dumps(alloc.leave_balances)                           # neutral label only
    assert len(emails) >= 2 and all("restricted" in e for e in emails[-2:])            # approved + rejected mails
