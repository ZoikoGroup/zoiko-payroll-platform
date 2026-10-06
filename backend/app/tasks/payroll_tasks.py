"""
app/tasks/payroll_tasks.py
---------------------------
Celery tasks for payroll processing.

Phase 2.2 — parallel per-employee payslip generation via a Celery chord:
a header group of one task per employee, followed by a single callback
that recomputes the run's aggregates exactly once.

Three rules make this safe, and they are the reason this file looks the
way it does:

1. EVERY input comes from the service, not from here. Each header task
   calls `payroll_service.generate_payslip_for_employee`, which resolves
   its inputs through `_resolve_payslip_generation_inputs` — the same
   function the synchronous batch path uses. This module never assembles
   a payslip itself. (The earlier design — a chord task deriving inputs
   from whatever `_resolve_employee_calc_inputs` happened to return — is
   documented in the old NOTE below as unsafe: that helper does not
   resolve ytd_inputs, allowance_components, attendance_records or
   org_levy_inputs, so a chord built on it would silently compute
   payslips that differ from the batch path.)

2. Shared org-level accumulators block parallelism. If any pending
   employee's country has an org-wide read-modify-write accumulator
   (Canada's EHT/party levies, UK Apprenticeship/Employment Levy,
   Australia payroll tax, Jamaica HEART), the header falls back to the
   sequential batch path — a wrong levy band is a persisted, plausible
   figure, not a retryable failure. See
   `payroll_service.parallel_payslip_generation_blocker`.

3. The callback owns the run's totals. Per-employee tasks each commit
   only their own payslip; `_recompute_run_aggregates` runs once in the
   callback so N employees do not trigger N full re-aggregations. There
   is no second commit of the same work anywhere in this file.
"""
from celery import chord, group
from celery import shared_task
from celery.utils.log import get_task_logger
from typing import List, Optional
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.database import SessionLocal
from app.modules.payroll import service as payroll_service
from app.modules.payroll.models import (
    PayrollRun, PayrollStatus, PayrollEmployee, PayslipItem, EmployeeStatus,
)
from app.core.exceptions import NotFoundException

logger = get_task_logger(__name__)


def get_db() -> Session:
    """Get a new database session for the task."""
    return SessionLocal()


# Chord result statuses — the exact strings generate_payslip_for_employee
# returns, plus "error" for an unexpected per-employee failure. Keep the
# three in sync with the service function's contract; the tests in
# tests/test_payslip_chord_tasks.py assert the mapping.
STATUS_GENERATED = "generated"
STATUS_EXISTS = "exists"
STATUS_BLOCKED = "blocked"
STATUS_ERROR = "error"


@shared_task(
    bind=True,
    queue="payroll",
)
def generate_payslips_for_run_task(self, run_id: int, organization_id: int,
                                   employee_ids: Optional[List[int]] = None):
    """Generate payslips for a payroll run.

    Dispatches a Celery chord — a header group of one task per pending
    employee, then `finalize_payroll_run_task` as the callback — when it
    is safe to compute employees concurrently. When it is not (see rule 2
    in this module's docstring), it runs the existing sequential batch
    path instead and returns the same shape of result with
    `parallel: False`, so a caller never has to guess which path ran.

    Deliberately does NOT declare `autoretry_for`. A chord dispatch that
    fails after some header tasks have already committed payslips would be
    re-dispatched wholesale on retry; the idempotency guard inside
    generate_payslip_for_employee would absorb most of that, but a
    retry loop that silently re-runs payroll generation is exactly the
    kind of thing that should surface as a visible failure a human
    resolves, not hide behind backoff.
    """
    db = SessionLocal()
    try:
        run = db.query(PayrollRun).filter(
            PayrollRun.id == run_id,
            PayrollRun.organization_id == organization_id
        ).first()

        if not run:
            raise NotFoundException(f"PayrollRun {run_id} not found")

        if run.status != PayrollStatus.DRAFT.value:
            raise ValueError(f"Cannot generate payslips for run in status {run.status}")

        pending_employees = _pending_employees(db, run, organization_id, employee_ids)
        if not pending_employees:
            # Nothing to generate — but the run still needs its aggregates
            # recomputed (it may have had payslips removed) and its
            # pre-existing payslips counted, which is the callback's job.
            # Run it directly rather than dispatching an empty chord: an
            # empty group is a Celery edge case with no benefit here, and
            # an operator who asked for generation on an empty run should
            # not get silence.
            return finalize_payroll_run_task.apply(
                args=[[], run_id, organization_id, 0]
            ).get()

        blocker = payroll_service.parallel_payslip_generation_blocker(
            db, organization_id, pending_employees)
        if blocker:
            logger.info(
                f"Payroll run {run_id}: parallel generation blocked ({blocker}); "
                f"falling back to the sequential batch path"
            )
            run = payroll_service.generate_payslips_for_run(
                db, run, organization_id, employee_ids)
            return {
                "run_id": run_id,
                "status": "completed",
                "parallel": False,
                "reason": blocker,
                "employee_count": run.employee_count,
            }

        # Payslip numbers MUST be allocated here, in one transaction,
        # before the group is built: generate_business_code counts
        # committed rows, so two workers calling it concurrently would both
        # count the same total and mint the same number. The batch path
        # does the same thing for the same reason.
        payslip_numbers = _allocate_payslip_numbers(
            db, run, len(pending_employees))

        header = group(
            generate_payslip_for_employee_task.s(
                run_id, organization_id, emp.id, payslip_numbers[idx])
            for idx, emp in enumerate(pending_employees)
        )
        callback = finalize_payroll_run_task.s(
            run_id, organization_id, len(pending_employees))
        chord(header)(callback)

        return {
            "run_id": run_id,
            "status": "dispatched",
            "parallel": True,
            "employee_count": len(pending_employees),
        }
    except Exception as exc:
        logger.error(f"Payroll run {run_id} generation dispatch failed: {exc}")
        db.rollback()
        raise
    finally:
        db.close()


def _pending_employees(db: Session, run: PayrollRun, organization_id: int,
                       employee_ids: Optional[List[int]]) -> List[PayrollEmployee]:
    """The exact employee set the batch path would process.

    Duplicated rather than extracted from generate_payslips_for_run only
    in the sense that this function must NOT share its mutations (the
    batch path deletes stale FAILED sentinels as part of its loop); the
    selector itself — Active, in-org, joined on or before period start,
    optionally restricted to employee_ids, excluding anyone who already
    has a non-FAILED payslip — is copied so the chord can never pay out
    to a different set of people than the sequential path would have.

    Replacing both copies with one shared helper is the obvious next step;
    it is left separate here because the batch path's version is
    interleaved with its retry-cleanup and attendance pre-fetch, and
    splitting those out is a larger, separately-testable refactor.
    """
    from sqlalchemy import or_
    from app.modules.payroll.models import PayslipStatus

    employees_query = db.query(PayrollEmployee).filter(
        PayrollEmployee.status == EmployeeStatus.ACTIVE,
        PayrollEmployee.organization_id == organization_id,
    )
    if employee_ids:
        employees_query = employees_query.filter(PayrollEmployee.id.in_(employee_ids))
    employees_query = employees_query.filter(
        or_(
            PayrollEmployee.date_of_joining == None,
            PayrollEmployee.date_of_joining <= run.period_start,
        )
    )
    employees = employees_query.all()

    existing_ids = {
        row.employee_id for row in
        db.query(PayslipItem.employee_id).filter(
            PayslipItem.payroll_run_id == run.id,
            PayslipItem.status != PayslipStatus.FAILED,
        ).all()
    }
    pending = [e for e in employees if e.id not in existing_ids]

    # Same stale-FAILED cleanup the batch path performs, so a retried
    # employee ends up with exactly one payslip row either way.
    retry_candidate_ids = {e.id for e in pending}
    if retry_candidate_ids:
        db.query(PayslipItem).filter(
            PayslipItem.payroll_run_id == run.id,
            PayslipItem.employee_id.in_(retry_candidate_ids),
            PayslipItem.status == PayslipStatus.FAILED,
        ).delete(synchronize_session="fetch")
        db.commit()

    return pending


def _allocate_payslip_numbers(db: Session, run: PayrollRun, count: int) -> List[Optional[str]]:
    """Mint `count` sequential payslip numbers in one transaction.

    Mirrors the batch path's base_code + local sequence arithmetic,
    including its treatment of a blocked employee: the batch path does
    NOT burn a number on an employee whose generation was statutorily
    blocked (it leaves the FAILED row's payslip_number NULL and reuses
    the number for the next employee). Here the number is handed out
    up front because the dispatcher cannot know in advance who will be
    blocked — so a blocked employee leaves a gap rather than a reuse.

    A gap is safe (payslip_number is unique-but-nullable, and no row
    exists for the skipped value); a collision would not be. Choosing the
    gap is choosing the failure mode that cannot corrupt uniqueness.
    """
    if not run.organization_id:
        return [None] * count

    from app.core.code_generation import generate_business_code
    from app.modules.payroll.models import PayslipItem

    full_code = generate_business_code(
        db, run.organization_id, "PSL", PayslipItem, "payslip_number", "%Y%m", 5,
    )
    if len(full_code) > 5:
        base_payslip_code, seq = full_code[:-5], int(full_code[-5:])
    else:
        base_payslip_code, seq = full_code, 1

    numbers = [f"{base_payslip_code}{seq + i:05d}" for i in range(count)]
    db.commit()
    return numbers


@shared_task(
    bind=True,
    queue="payroll",
)
def generate_payslip_for_employee_task(self, run_id: int, organization_id: int,
                                       employee_id: int,
                                       payslip_number: Optional[str] = None):
    """Generate ONE employee's payslip — a Celery chord header member.

    Owns one short transaction: it resolves and writes a single payslip
    and commits nothing else. It never touches run aggregates (rule 3) and
    never computes any input of its own (rule 1).

    An unexpected exception is caught, rolled back and reported as
    `{"status": "error"}` rather than re-raised. This is the one place
    swallowing an exception is correct: a chord whose header member raises
    never invokes its callback, which would leave the run's aggregates
    stale while some payslips are already committed — a state that looks
    complete to every reader of the run row. Returning "error" instead
    keeps the chord whole, and the callback then refuses to advance the
    run past DRAFT (see finalize_payroll_run_task), so the failure stays
    visible and retryable rather than becoming a silent, half-written run.
    """
    db = SessionLocal()
    try:
        run = db.query(PayrollRun).filter(
            PayrollRun.id == run_id,
            PayrollRun.organization_id == organization_id
        ).first()
        if not run:
            return {"status": STATUS_ERROR, "run_id": run_id,
                    "employee_id": employee_id,
                    "error": f"PayrollRun {run_id} not found"}

        result = payroll_service.generate_payslip_for_employee(
            db, run, employee_id, organization_id,
            payslip_number=payslip_number,
        )
        db.commit()
        return {"run_id": run_id, **result}
    except Exception as exc:
        logger.exception(
            f"Per-employee payslip generation failed: run {run_id}, "
            f"employee {employee_id}: {exc}"
        )
        db.rollback()
        return {"status": STATUS_ERROR, "run_id": run_id,
                "employee_id": employee_id, "error": str(exc)}
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="payroll",
)
def finalize_payroll_run_task(self, results: List[dict], run_id: int,
                              organization_id: int, expected_count: int):
    """Chord callback — recomputes the run's aggregates exactly once.

    `results` is supplied by Celery (the chord's collective header
    result); `run_id`, `organization_id` and `expected_count` are bound
    by the dispatcher when the chord is built.

    Status contract:
      * any "error" result, or fewer results than expected → the callback
        raises WITHOUT recomputing, because committing aggregates for a
        run whose generation did not finish would leave the run row
        advertising totals that never covered every employee;
      * all employees accounted for (generated/exists/blocked) →
        _recompute_run_aggregates runs once. "blocked" and "exists" are
        terminal, accounted-for outcomes — a statutorily-refused employee
        is a real result, not a failure to be waited on;
      * run.status is deliberately NOT changed here. The synchronous path
        (generate_payslips_for_run) does not advance DRAFT→REVIEW either;
        that transition belongs to the operator's Approve action, via
        advance_payroll_run_status. An async run that silently skipped
        that review step would be a behavioural fork between the two
        paths, and the review step exists precisely because someone must
        look at the numbers before they are approved.
      * aggregates are recomputed by _recompute_run_aggregates, which
        commits them itself. This callback does not call db.commit() —
        one commit for the totals, none of them a second commit of the
        same work.
    """
    db = SessionLocal()
    try:
        run = db.query(PayrollRun).filter(
            PayrollRun.id == run_id,
            PayrollRun.organization_id == organization_id
        ).first()

        if not run:
            logger.error(f"Run {run_id} not found for finalization")
            return

        results = results or []
        totals = {
            "total": len(results),
            "generated": sum(1 for r in results if r.get("status") == STATUS_GENERATED),
            "exists": sum(1 for r in results if r.get("status") == STATUS_EXISTS),
            "blocked": sum(1 for r in results if r.get("status") == STATUS_BLOCKED),
            "errors": [r for r in results if r.get("status") == STATUS_ERROR],
        }

        if totals["errors"] or len(results) < expected_count:
            # Do NOT recompute here: committing totals now would publish a
            # complete-looking run whose employee_count is short of the
            # people who were supposed to be paid. Raising instead makes
            # the chord fail visibly in the worker/monitoring layer while
            # the run stays DRAFT and retryable.
            logger.error(
                f"Payroll run {run_id} finalization FAILED: "
                f"{len(totals['errors'])} task error(s), "
                f"{len(results)}/{expected_count} results received"
            )
            db.rollback()
            raise RuntimeError(
                f"Payroll run {run_id} incomplete: "
                f"{len(results)}/{expected_count} employees processed, "
                f"{len(totals['errors'])} failed — run left in DRAFT"
            )

        # _recompute_run_aggregates commits and refreshes run itself. No
        # commit follows it here — that would be the double-commit this
        # callback exists to avoid.
        run = payroll_service._recompute_run_aggregates(db, run)

        logger.info(
            f"Payroll run {run_id} finalized: "
            f"{totals['generated']} generated, {totals['exists']} already present, "
            f"{totals['blocked']} blocked, aggregates recomputed"
        )

        return {
            "run_id": run_id,
            "status": "finalized",
            "run_status": run.status,
            "summary": {k: v for k, v in totals.items() if k != "errors"},
        }
    except Exception as exc:
        logger.error(f"Payroll run {run_id} finalization failed: {exc}")
        db.rollback()
        raise
    finally:
        db.close()


@shared_task(
    bind=True,
    queue="payroll",
)
def preview_payroll_run_task(self, organization_id: int, employee_ids: List[int],
                              country: str, period_start: str, period_end: str,
                              calculation_mode: str):
    """
    Generate a payroll preview (dry-run) without persisting.

    Args:
        organization_id: Organization ID
        employee_ids: List of employee IDs to preview
        country: Country code
        period_start: Period start date (ISO format)
        period_end: Period end date (ISO format)
        calculation_mode: Calculation mode

    Returns:
        Preview results
    """
    db = SessionLocal()
    try:
        from datetime import date

        period_start_date = date.fromisoformat(period_start)
        period_end_date = date.fromisoformat(period_end)

        result = payroll_service.preview_payroll_run(
            db, organization_id, employee_ids, country,
            period_start_date, period_end_date, calculation_mode
        )

        return result
    finally:
        db.close()


# NOTE: recalculate_employee_payslip_task is intentionally NOT registered
# yet -- payroll_service has no recalculate_payslip() function, so the task
# would raise AttributeError on first use.


# Periodic task: Daily payroll run status check
@shared_task(
    bind=True,
    queue="payroll",
)
def check_stale_payroll_runs_task(self):
    """
    Periodic task to check for stale payroll runs (stuck in DRAFT/REVIEW too long).
    """
    db = SessionLocal()
    try:
        from app.modules.payroll.models import PayrollRun, PayrollStatus
        from datetime import datetime, timedelta

        stale_threshold = datetime.utcnow() - timedelta(days=7)

        stale_runs = db.query(PayrollRun).filter(
            PayrollRun.status.in_([PayrollStatus.DRAFT.value, PayrollStatus.REVIEW.value]),
            PayrollRun.updated_at < stale_threshold,
        ).all()

        for run in stale_runs:
            # Log or notify about stale run
            logger.warning(f"Stale payroll run detected: {run.id} (org {run.organization_id}, status {run.status})")

        return {"stale_runs_found": len(stale_runs)}
    finally:
        db.close()
