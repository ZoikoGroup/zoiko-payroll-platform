"""
tests/test_bwm_aggregation_edge_cases.py
--------------------------------------------
Commercial Billing & Subscription Operating Standard Part 3 (blocker #3):
"employment-relationship identity, same-month deduplication, rehire,
transfer, final-pay, and retroactivity."

Exercises billing/bwm.py's aggregate_billing_month() directly against a
real (in-memory) database — not mocked — per the prompt's own instruction
that these are real correctness bugs waiting to overcharge or undercharge
a customer, not edge cases to defer.

Findings, verified by the tests below (not assumed):
  - Same-month dedup / rehire (same employee_id): ALREADY correct by
    construction — aggregate_billing_month iterates PayrollEmployee rows
    (one row = one BWM record per month via the UniqueConstraint-backed
    upsert), so toggling one employee's status within a month can never
    produce two records for them. See test_same_employee_toggled_within_month_counts_once.
  - Final pay in a later month: ALREADY correct — the TERMINATED_ARCHIVE
    branch explicitly checks for production payslip activity in that
    month. See test_terminated_archive_counts_only_with_production_activity.
  - Retroactivity: ALREADY correct — aggregate_billing_month takes
    billing_month as an explicit parameter and upserts in place; calling
    it again for a past month after a correction updates that past
    month's row, not "today's". See test_retroactive_correction_updates_past_month.
  - Transfer between legal entities: NOT REPRESENTABLE in the current
    schema, not a bug in bwm.py. BillingWorkerMonthRecord.employer_entity_id
    exists but nothing ever sets it, and PayrollEmployee has no legal-
    entity relationship at all (LegalEntity, added for MAX_ENTITIES
    enforcement, has no FK to PayrollEmployee). See
    test_transfer_between_entities_is_not_representable_today for the
    documenting assertion — this is a real, disclosed gap, not a passing
    test of behavior that doesn't exist.

    What genuinely IS a same-month-rehire risk, and is NOT covered by
    "one row per employee_id": a rehire modeled as a brand-new
    PayrollEmployee row (new employee_id) for the same physical person.
    Nothing in this schema can detect "these two employee_ids are the same
    person" — there is no person-identity concept independent of the
    employment-relationship row. This is a process/data-entry question,
    not something aggregate_billing_month can or should guess at; flagged
    here rather than silently assumed away.
"""

from datetime import date

import pytest

from app.modules.billing import bwm
from app.modules.billing.models import BillingWorkerMonthRecord
from app.modules.payroll.models import (
    PayrollEmployee,
    PayrollRun,
    PayrollScopeStatus,
    PayrollStatus,
    PayslipItem,
)


def _make_employee(db, org, code, scope_status=None, status="Active"):
    emp = PayrollEmployee(
        organization_id=org.id,
        employee_code=code,
        name=f"Employee {code}",
        status=status,
    )
    if scope_status is not None:
        emp.payroll_scope_status = scope_status
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org, period_start, period_end, pay_date, status=PayrollStatus.AUTHORIZED.value):
    run = PayrollRun(
        organization_id=org.id,
        period_label=f"{period_start.isoformat()}..{period_end.isoformat()}",
        period_start=period_start,
        period_end=period_end,
        pay_date=pay_date,
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _make_payslip(db, org, run, employee):
    item = PayslipItem(
        payroll_run_id=run.id,
        employee_id=employee.id,
        organization_id=org.id,
        employee_name=employee.name,
    )
    db.add(item)
    db.commit()
    return item


def test_same_employee_toggled_within_month_counts_once(db, organization):
    """Rehire modeled the only way this schema can represent it (the SAME
    employee_id, reactivated) must never double-count within one month —
    aggregate_billing_month iterates PayrollEmployee rows, not events, so
    this holds by construction. Verified directly rather than assumed."""
    emp = _make_employee(db, organization, "E1", scope_status=PayrollScopeStatus.ACTIVE.value)
    month = date(2026, 6, 1)

    result_first_call = bwm.aggregate_billing_month(db, organization.id, month)
    assert result_first_call["counted"] == 1

    # "Rehire" within the same month: terminate then reactivate the SAME row.
    emp.payroll_scope_status = PayrollScopeStatus.TERMINATED_ARCHIVE.value
    db.commit()
    emp.payroll_scope_status = PayrollScopeStatus.ACTIVE.value
    db.commit()

    result_second_call = bwm.aggregate_billing_month(db, organization.id, month)
    assert result_second_call["counted"] == 1
    assert result_second_call["created"] == 0  # updated the existing row, not a new one

    records = (
        db.query(BillingWorkerMonthRecord)
        .filter(BillingWorkerMonthRecord.organization_id == organization.id, BillingWorkerMonthRecord.billing_month == month)
        .all()
    )
    assert len(records) == 1
    assert records[0].payroll_employee_id == emp.id
    assert records[0].counted is True


def test_terminated_archive_counts_only_with_production_activity(db, organization):
    """Final pay in a later month: a TERMINATED_ARCHIVE employee still
    counts for a month where a non-draft payslip exists, even though
    they're no longer active."""
    emp = _make_employee(db, organization, "E2", scope_status=PayrollScopeStatus.TERMINATED_ARCHIVE.value)
    month = date(2026, 7, 1)

    # No production activity yet this month -> excluded.
    result_no_activity = bwm.aggregate_billing_month(db, organization.id, month)
    assert result_no_activity["counted"] == 0
    assert result_no_activity["excluded"] == 1

    record = db.query(BillingWorkerMonthRecord).filter(BillingWorkerMonthRecord.payroll_employee_id == emp.id).first()
    assert record.counted is False
    assert record.reason_code == "TERMINATED_ARCHIVE_NO_ACTIVITY"

    # A final-pay run lands in the same month, status AUTHORIZED (non-draft).
    run = _make_run(db, organization, date(2026, 7, 1), date(2026, 7, 31), date(2026, 7, 31))
    _make_payslip(db, organization, run, emp)

    result_with_activity = bwm.aggregate_billing_month(db, organization.id, month)
    assert result_with_activity["counted"] == 1
    assert result_with_activity["excluded"] == 0

    db.refresh(record)
    assert record.counted is True
    assert record.reason_code is None


def test_excluded_scope_statuses_never_count(db, organization):
    """DRAFT/FUTURE_DATED/VOIDED/TEST/DEMO employees are excluded outright,
    every month, regardless of payslip activity."""
    month = date(2026, 8, 1)
    for status in (
        PayrollScopeStatus.DRAFT.value,
        PayrollScopeStatus.FUTURE_DATED.value,
        PayrollScopeStatus.VOIDED.value,
        PayrollScopeStatus.TEST.value,
        PayrollScopeStatus.DEMO.value,
    ):
        emp = _make_employee(db, organization, f"E-{status}", scope_status=status)
        run = _make_run(db, organization, date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 31))
        _make_payslip(db, organization, run, emp)

    result = bwm.aggregate_billing_month(db, organization.id, month)
    assert result["counted"] == 0
    assert result["excluded"] == 5

    for record in db.query(BillingWorkerMonthRecord).filter(BillingWorkerMonthRecord.billing_month == month).all():
        assert record.counted is False


def test_retroactive_correction_updates_past_month_not_processing_month(db, organization):
    """A correction processed "today" for a PAST period must adjust that
    past month's BWM record — aggregate_billing_month takes billing_month
    as an explicit parameter and upserts in place, so calling it again for
    the corrected past month (not "today") is how a caller gets this
    right. Verifies the upsert actually updates in place rather than
    creating a duplicate for the same past month."""
    emp = _make_employee(db, organization, "E3", scope_status=PayrollScopeStatus.ACTIVE.value)
    past_month = date(2026, 3, 1)

    first = bwm.aggregate_billing_month(db, organization.id, past_month)
    assert first["counted"] == 1

    # A correction weeks later excludes this employee retroactively for
    # that same past month.
    emp.payroll_scope_status = PayrollScopeStatus.VOIDED.value
    db.commit()

    second = bwm.aggregate_billing_month(db, organization.id, past_month)
    assert second["created"] == 0  # same record, updated
    assert second["counted"] == 0
    assert second["excluded"] == 1

    records = (
        db.query(BillingWorkerMonthRecord)
        .filter(BillingWorkerMonthRecord.organization_id == organization.id, BillingWorkerMonthRecord.billing_month == past_month)
        .all()
    )
    assert len(records) == 1, "retroactive correction must update the existing past-month row, not create a second one"
    assert records[0].counted is False


def test_transfer_between_entities_is_not_representable_today(db, organization):
    """Documenting assertion, not a passing behavioral test: this schema
    has no PayrollEmployee -> LegalEntity relationship at all (LegalEntity
    was added purely for MAX_ENTITIES counting — see organizations/models.py),
    and BillingWorkerMonthRecord.employer_entity_id is never set by any
    code path. "Transfer between legal entities mid-month" cannot
    double-count today because there is nothing to attribute an employee
    to per-entity in the first place — this is a real, disclosed schema
    gap, not a bug in aggregate_billing_month."""
    assert not hasattr(PayrollEmployee, "legal_entity_id")

    emp = _make_employee(db, organization, "E4", scope_status=PayrollScopeStatus.ACTIVE.value)
    month = date(2026, 9, 1)
    bwm.aggregate_billing_month(db, organization.id, month)

    record = db.query(BillingWorkerMonthRecord).filter(BillingWorkerMonthRecord.payroll_employee_id == emp.id).first()
    assert record.employer_entity_id is None, "nothing in this codebase ever sets employer_entity_id yet"
