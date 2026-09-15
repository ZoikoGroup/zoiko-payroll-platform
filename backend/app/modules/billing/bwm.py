"""
modules/billing/bwm.py
-----------------------
Billable Worker Month (BWM) aggregation — blueprint §4. Compute-only:
this module never calls Stripe or any other gateway, it only
materializes/upserts rows in billing_worker_month_records. Turning those
rows into subscription items/invoice lines is a separate, later concern.

`PayrollEmployee.payroll_scope_status` (payroll/models.py's
`PayrollScopeStatus` enum) drives `counted`/`reason_code` below — read-only
from this module's perspective; payroll itself never branches on it. A
database whose payroll_employees table predates this column (or a row
where the column is NULL) resolves identically to `PayrollScopeStatus.ACTIVE`
— see `_scope_status_of`.
"""

import calendar
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.modules.billing.models import BillingWorkerMonthRecord

# Exclusion vocabulary from blueprint §4, sourced from payroll/models.py's
# PayrollScopeStatus so the two modules can never silently drift apart.
_ARCHIVE_NO_ACTIVITY_REASON = "TERMINATED_ARCHIVE_NO_ACTIVITY"


def _excluded_scope_statuses() -> set:
    from app.modules.payroll.models import PayrollScopeStatus

    return {
        PayrollScopeStatus.DRAFT.value,
        PayrollScopeStatus.FUTURE_DATED.value,
        PayrollScopeStatus.VOIDED.value,
        PayrollScopeStatus.TEST.value,
        PayrollScopeStatus.DEMO.value,
    }


def _archive_scope_status() -> str:
    from app.modules.payroll.models import PayrollScopeStatus

    return PayrollScopeStatus.TERMINATED_ARCHIVE.value


def _last_day_of_month(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _scope_status_of(employee) -> Optional[str]:
    """NULL/missing (a row or column predating payroll_scope_status) reads
    identically to PayrollScopeStatus.ACTIVE — both mean "no exclusion state
    configured", per that column's own docstring in payroll/models.py."""
    status = getattr(employee, "payroll_scope_status", None)
    if status is None:
        return None
    return status.value if hasattr(status, "value") else str(status)


def _has_production_activity(db: Session, payroll_employee_id: int, month_start: date, month_end: date) -> bool:
    """True if a non-draft payroll run produced a payslip for this employee
    with a period overlapping [month_start, month_end] — the "production
    activity that month" test TERMINATED_ARCHIVE employees must pass to
    still be counted (blueprint §4)."""
    from app.modules.payroll.models import PayrollRun, PayrollStatus, PayslipItem

    return (
        db.query(PayslipItem)
        .join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayslipItem.employee_id == payroll_employee_id,
            PayrollRun.status != PayrollStatus.DRAFT.value,
            PayrollRun.period_start <= month_end,
            PayrollRun.period_end >= month_start,
        )
        .first()
        is not None
    )


def _resolve_inclusion(db: Session, employee, month_start: date, month_end: date) -> tuple[bool, Optional[str]]:
    """(counted, reason_code) for one employee for one billing month, per
    blueprint §4's exclusion/dedupe rules."""
    scope_status = _scope_status_of(employee)

    if scope_status in _excluded_scope_statuses():
        return False, scope_status

    if scope_status == _archive_scope_status():
        if _has_production_activity(db, employee.id, month_start, month_end):
            return True, None
        return False, _ARCHIVE_NO_ACTIVITY_REASON

    # No exclusion state configured (or scope_status not recognized) —
    # counted, same as every ordinary active employment relationship.
    return True, None


def aggregate_billing_month(db: Session, organization_id: int, billing_month: date) -> dict:
    """Upsert one billing_worker_month_records row per (organization_id,
    payroll_employee_id, billing_month) for every PayrollEmployee in this
    org. Idempotent — safe to re-run for the same month (uses the Prompt 1
    UniqueConstraint as the dedupe key via a query-then-write upsert, not a
    plain insert).

    `billing_month` may be any date within the target month; it is
    normalized to the first of that month before writing/matching, so
    passing the 1st, 15th, or the last day all resolve to the same row.
    """
    from app.modules.payroll.models import PayrollEmployee

    normalized_month = billing_month.replace(day=1)
    month_end = _last_day_of_month(normalized_month)

    employees = (
        db.query(PayrollEmployee)
        .filter(PayrollEmployee.organization_id == organization_id)
        .all()
    )

    created = 0
    updated = 0
    counted_count = 0
    excluded_count = 0

    for employee in employees:
        counted, reason_code = _resolve_inclusion(db, employee, normalized_month, month_end)
        if counted:
            counted_count += 1
        else:
            excluded_count += 1

        existing = (
            db.query(BillingWorkerMonthRecord)
            .filter(
                BillingWorkerMonthRecord.organization_id == organization_id,
                BillingWorkerMonthRecord.payroll_employee_id == employee.id,
                BillingWorkerMonthRecord.billing_month == normalized_month,
            )
            .first()
        )
        if existing is None:
            db.add(
                BillingWorkerMonthRecord(
                    organization_id=organization_id,
                    # No employer-entity table exists yet in this repo —
                    # see BillingWorkerMonthRecord's own comment in models.py.
                    employer_entity_id=None,
                    payroll_employee_id=employee.id,
                    billing_month=normalized_month,
                    counted=counted,
                    reason_code=reason_code,
                )
            )
            created += 1
        else:
            existing.counted = counted
            existing.reason_code = reason_code
            db.add(existing)
            updated += 1

    db.commit()

    return {
        "organization_id": organization_id,
        "billing_month": normalized_month,
        "employees_seen": len(employees),
        "created": created,
        "updated": updated,
        "counted": counted_count,
        "excluded": excluded_count,
    }
