"""South Africa tax directives (ZP-ZA-ENG-001, ZA-007) — capture, four-eyes
approval, revocation and the in-force lookup. "ZA" is South Africa.

The engine's own fail-closed application rules are covered by the golden cases
(directive_fixed_percentage, directive_fixed_amount, directive_wrong_tax_year,
directive_captured_ignored, directive_absent_uses_standard); this module proves
the service governance around them.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import south_africa_service as svc
from app.modules.payroll.models import PayrollEmployee


def _employee(db, organization, *, code="ZA-DIR-1"):
    employee = PayrollEmployee(organization_id=organization.id, employee_code=code,
                               name=f"Employee {code}", date_of_joining=date(2020, 1, 1),
                               basic=Decimal("5000"), country_code="ZA")
    db.add(employee)
    db.flush()
    return employee


def _capture(db, organization, employee, number="D1", **overrides):
    kwargs = dict(organization_id=organization.id, employee_id=employee.id,
                  directive_number=number, directive_type="FIXED_PERCENTAGE", rate_pct="25",
                  tax_year="2027", issue_date=date(2026, 8, 15),
                  effective_from=date(2026, 3, 1), effective_to=date(2027, 2, 28),
                  evidence_sha256="a" * 64, actor_id=1)
    kwargs.update(overrides)
    return svc.capture_za_directive(db, **kwargs)


def _approved(db, organization, employee, number="D1", **overrides):
    row = _capture(db, organization, employee, number, **overrides)
    return svc.approve_za_directive(db, row.id, approver_id=2)


# ── capture ─────────────────────────────────────────────────────────────────
def test_capture_starts_uncaptured_and_needs_evidence(db, organization):
    employee = _employee(db, organization)
    with pytest.raises(Exception) as exc:
        _capture(db, organization, employee, evidence_sha256=None)
    assert "evidence" in str(exc.value)

    row = _capture(db, organization, employee)
    assert row.status == "CAPTURED" and row.created_by_id == 1
    assert row.rate_pct == Decimal("25") and row.amount is None


@pytest.mark.parametrize("overrides", [
    {"directive_type": "SOMETHING_ELSE"},
    {"rate_pct": None},
    {"rate_pct": "101"},
    {"rate_pct": "-1"},
    {"rate_pct": "25", "amount": "10000"},
    {"directive_type": "FIXED_AMOUNT", "rate_pct": None},
    {"directive_type": "FIXED_AMOUNT", "rate_pct": "10", "amount": "10000"},
    {"directive_type": "FIXED_AMOUNT", "rate_pct": None, "amount": "-1"},
    {"tax_year": ""},
    {"directive_number": ""},
    {"effective_from": "2026-03-01", "effective_to": "2026-02-28"},
])
def test_capture_refuses_invalid_directives(db, organization, overrides):
    employee = _employee(db, organization)
    with pytest.raises(Exception):
        _capture(db, organization, employee, **overrides)


def test_directive_number_is_unique_per_organisation(db, organization):
    employee = _employee(db, organization)
    _capture(db, organization, employee, "D1")
    with pytest.raises(Exception) as exc:
        _capture(db, organization, employee, "D1")
    assert "already recorded" in str(exc.value)


def test_capture_refuses_an_employee_outside_the_organisation(db, organization):
    employee = _employee(db, organization)
    with pytest.raises(Exception):
        _capture(db, organization, employee, organization_id=999999)


# ── four-eyes approval ──────────────────────────────────────────────────────
def test_four_eyes_refuses_self_approval(db, organization):
    employee = _employee(db, organization)
    row = _capture(db, organization, employee)
    with pytest.raises(Exception) as exc:
        svc.approve_za_directive(db, row.id, approver_id=1)
    assert "four-eyes" in str(exc.value)


def test_approval_is_one_way_and_records_the_approver(db, organization):
    employee = _employee(db, organization)
    row = _capture(db, organization, employee)
    approved = svc.approve_za_directive(db, row.id, approver_id=2)
    assert approved.status == "APPROVED" and approved.approved_by_id == 2
    assert approved.approved_at is not None
    with pytest.raises(Exception):
        svc.approve_za_directive(db, row.id, approver_id=3)


def test_approving_an_unknown_directive_is_not_found(db):
    with pytest.raises(Exception):
        svc.approve_za_directive(db, 999999, approver_id=2)


# ── in-force lookup ────────────────────────────────────────────────────────
def test_lookup_filters_status_employee_and_effective_window(db, organization):
    first = _employee(db, organization, code="ZA-DIR-1")
    second = _employee(db, organization, code="ZA-DIR-2")

    live = _approved(db, organization, first, "LIVE")
    _capture(db, organization, first, "CAPTURED")
    revoked = _approved(db, organization, first, "REVOKED")
    svc.revoke_za_directive(db, revoked.id, actor_id=3)
    _approved(db, organization, first, "EXPIRED", effective_to=date(2026, 8, 31))
    _approved(db, organization, first, "FUTURE", effective_from=date(2026, 10, 1))
    _approved(db, organization, second, "OTHER-EMP")

    september = svc.za_directives_in_force(db, first.id, date(2026, 9, 30))
    assert [d["id"] for d in september] == [live.id]
    assert all(isinstance(d, dict) for d in september)
    assert september[0]["effective_from"] == date(2026, 3, 1)
    assert september[0]["rate_pct"] == Decimal("25")

    july = svc.za_directives_in_force(db, first.id, date(2026, 7, 15))
    assert sorted(d["directive_number"] for d in july) == ["EXPIRED", "LIVE"]


def test_revocation_keeps_the_evidence_and_removes_it_from_the_lookup(db, organization):
    employee = _employee(db, organization)
    row = _approved(db, organization, employee)
    assert svc.za_directives_in_force(db, employee.id, date(2026, 9, 30))

    revoked = svc.revoke_za_directive(db, row.id, actor_id=3)
    assert revoked.status == "REVOKED"
    assert revoked.evidence_sha256 == "a" * 64
    assert svc.za_directives_in_force(db, employee.id, date(2026, 9, 30)) == []


def test_revoking_an_unknown_directive_is_not_found(db):
    with pytest.raises(Exception):
        svc.revoke_za_directive(db, 999999)
