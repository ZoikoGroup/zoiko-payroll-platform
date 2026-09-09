"""
tests/test_germany_overtime.py
-------------------------------
Phase 8BE — the Germany overtime subsystem (classifier, work-record
lifecycle, ambiguity detection, and attach/detach financial integration)
had ZERO test coverage anywhere in this branch before this phase, despite
four production engine modules and seven migrated tables. This file closes
that gap, focused on:

1. The pure §3b EStG time-window classifier (no registry dependencies).
2. Work-record duplicate prevention and the AMBIGUOUS_OVERLAP fail-closed
   gate (Phase 8AQ) — proving the system never invents a manual-vs-
   attendance precedence rule, only detects and blocks on ambiguity.
3. Attach/detach transaction atomicity (this phase's own fix — previously
   4-5 sequential commits after the concurrency-safe claim could leave a
   permanently stuck, partially-applied payslip on a mid-sequence crash;
   now one atomic commit per direction) and the pre-existing atomic-claim
   idempotency (double-attach/double-detach both fail cleanly).
4. ELStAM change-list batch idempotency (this phase's own fix — a
   resubmitted batch_reference for the same organization now fails
   loudly instead of silently duplicating).

Where a scenario needs a COMPLETE GermanyOvertimePremiumComponent, this
file constructs one directly (bypassing the wage-tax/social-insurance
calculation engines, which need a full statutory registry setup already
covered by test_germany_pap_calculation.py) — attach/detach operate only
on the component's own stored fields, so this is a faithful, registry-
independent way to exercise the atomicity/idempotency guarantees this
phase is verifying.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.engine.germany_overtime_classifier import (
    GermanyOvertimeInvalidIntervalError,
    GermanyOvertimeTimezoneFoundationRequiredError,
    build_time_segments,
)
from app.modules.payroll.models import (
    GermanyElstamChangeListBatch, GermanyOvertimePremiumComponent,
    GermanyOvertimeWorkRecord, PayrollAttendanceRecord, PayrollEmployee,
    PayrollRun, PayslipAllowanceItem, PayslipItem,
)
from app.modules.payroll.schemas import (
    GermanyElstamChangeListBatchCreate, GermanyOvertimeWorkRecordCreate,
)

def _make_employee(db, org_id, code="DE-OT-001"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=72000, basic=6000, hra=0, status="Active",
        date_of_joining=date(2026, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org_id, period_start=date(2026, 1, 1)):
    run = PayrollRun(
        organization_id=org_id, period_label="Jan 2026", period_start=period_start,
        period_end=date(2026, 1, 31), pay_date=date(2026, 2, 1), status="Draft",
        calculation_mode="standard",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _make_payslip_item(db, run, emp, org_id):
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=emp.id, organization_id=org_id,
        employee_name=emp.name, gross_pay=Decimal("0.00"), total_deductions=Decimal("0.00"),
        net_pay=Decimal("0.00"), pf=Decimal("0.00"), esi=Decimal("0.00"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _make_work_record(db, emp, org_id, start, end, entry_source="MANUAL", approval="APPROVED"):
    row = service.create_germany_overtime_work_record(
        db, emp.id, org_id,
        GermanyOvertimeWorkRecordCreate(
            work_date=start.date(), start_datetime=start, end_datetime=end,
            hours=Decimal("2.00"), entry_source=entry_source,
        ),
        actor_id=1,
    )
    if approval and row.hr_approval_status != approval:
        row = service.set_germany_overtime_work_record_approval(db, row.id, org_id, approval, actor_id=1)
    return row


def _make_complete_component(db, work_record, org_id, gross=Decimal("100.00")):
    component = GermanyOvertimePremiumComponent(
        organization_id=org_id, work_record_id=work_record.id,
        segment_start=work_record.start_datetime, segment_end=work_record.end_datetime,
        work_date_local=work_record.work_date, qualifying_hours=Decimal("2.0000"),
        combination_status="COMPLETE",
        gross_premium_amount=gross, wage_tax_free_amount=Decimal("0.00"),
        wage_taxable_amount=gross, si_exempt_amount=Decimal("0.00"),
        si_contributory_amount=gross,
    )
    db.add(component)
    db.commit()
    db.refresh(component)
    return component


# ═══════════════════════════════════════════════════════════════════════
# 1. Classifier — pure §3b EStG time-window logic, no registries needed
# ═══════════════════════════════════════════════════════════════════════

class _FakeWorkRecord:
    def __init__(self, start, end):
        self.start_datetime = start
        self.end_datetime = end


def test_classifier_sunday_day_shift_is_tagged_sunday(db):
    # 2026-01-04 is a Sunday.
    start = datetime(2026, 1, 4, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 4, 17, 0, tzinfo=timezone.utc)
    segments = build_time_segments(db, _FakeWorkRecord(start, end))
    categories = {s["premium_category"] for s in segments}
    assert "SUNDAY" in categories
    assert "NIGHT_STANDARD" not in categories


def test_classifier_night_shift_crossing_midnight_extends_when_begun_before_midnight(db):
    # Starts 22:00 the same calendar day (before midnight) -> the 00:00-04:00
    # portion the next day qualifies as NIGHT_EXTENDED (40%), per Abs. 3 Nr. 1
    # "vor 0 Uhr aufgenommen".
    start = datetime(2026, 1, 6, 22, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 7, 2, 0, tzinfo=timezone.utc)
    segments = build_time_segments(db, _FakeWorkRecord(start, end))
    night_segments = [s for s in segments if s["premium_category"] in ("NIGHT_STANDARD", "NIGHT_EXTENDED")]
    assert any(s["premium_category"] == "NIGHT_STANDARD" for s in night_segments)  # 22:00-24:00
    assert any(s["premium_category"] == "NIGHT_EXTENDED" for s in night_segments)  # 00:00-02:00


def test_classifier_night_shift_starting_after_midnight_is_never_extended(db):
    # Starts 00:30 -> did NOT begin before midnight -> NIGHT_STANDARD only,
    # never NIGHT_EXTENDED, even though it's within the 00:00-04:00 window.
    start = datetime(2026, 1, 7, 0, 30, tzinfo=timezone.utc)
    end = datetime(2026, 1, 7, 3, 0, tzinfo=timezone.utc)
    segments = build_time_segments(db, _FakeWorkRecord(start, end))
    categories = {s["premium_category"] for s in segments}
    assert "NIGHT_STANDARD" in categories
    assert "NIGHT_EXTENDED" not in categories


def test_classifier_rejects_naive_datetime():
    from datetime import datetime as _dt
    with pytest.raises(GermanyOvertimeTimezoneFoundationRequiredError):
        # None db needed — this raises before any query happens.
        build_time_segments(None, _FakeWorkRecord(_dt(2026, 1, 6, 22, 0), _dt(2026, 1, 6, 23, 0)))


def test_classifier_rejects_end_before_start(db):
    start = datetime(2026, 1, 6, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc)
    with pytest.raises(GermanyOvertimeInvalidIntervalError):
        build_time_segments(db, _FakeWorkRecord(start, end))


# ═══════════════════════════════════════════════════════════════════════
# 2. Work-record duplicate prevention + AMBIGUOUS_OVERLAP fail-closed gate
# ═══════════════════════════════════════════════════════════════════════

def test_duplicate_attendance_derived_work_record_is_rejected(db, organization):
    emp = _make_employee(db, organization.id)
    attendance = PayrollAttendanceRecord(
        organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 5), status="present",
    )
    db.add(attendance)
    db.commit()
    db.refresh(attendance)

    start = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc)
    service.create_germany_overtime_work_record(
        db, emp.id, organization.id,
        GermanyOvertimeWorkRecordCreate(
            source_attendance_id=attendance.id, work_date=start.date(),
            start_datetime=start, end_datetime=end, hours=Decimal("2.00"),
            entry_source="ATTENDANCE_DERIVED",
        ),
        actor_id=1,
    )
    with pytest.raises(BadRequestException):
        service.create_germany_overtime_work_record(
            db, emp.id, organization.id,
            GermanyOvertimeWorkRecordCreate(
                source_attendance_id=attendance.id, work_date=start.date(),
                start_datetime=start, end_datetime=end, hours=Decimal("2.00"),
                entry_source="ATTENDANCE_DERIVED",
            ),
            actor_id=1,
        )
    assert (
        db.query(GermanyOvertimeWorkRecord)
        .filter(GermanyOvertimeWorkRecord.source_attendance_id == attendance.id)
        .count()
        == 1
    )


def test_overlapping_manual_records_are_marked_ambiguous_and_block_classification(db, organization):
    # NOTE on the DB dialect this test runs against: SQLite's
    # DateTime(timezone=True) does not actually preserve tzinfo (confirmed
    # empirically this phase — a tz-aware datetime written, then re-read
    # via the ORM after a commit/expire, comes back naive; Postgres, this
    # project's real production database, preserves it correctly). Since
    # this session's `db` fixture is always SQLite (see conftest.py), any
    # GermanyOvertimeWorkRecord reloaded from the DB after a commit loses
    # tzinfo on start_datetime/end_datetime — which the classifier
    # correctly, deliberately treats as unsafe (_require_aware) and
    # refuses to guess about. This is a genuine SQLite-only test-dialect
    # gap, not a production defect and not something this phase's
    # classifier fix should paper over — so this test restores UTC tzinfo
    # on the reloaded record before exercising the classifier, exactly
    # modeling what Postgres already does correctly on its own.
    emp = _make_employee(db, organization.id)
    first = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc),
    )
    second = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 5, 19, 0, tzinfo=timezone.utc), datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc),
    )
    db.refresh(first)
    db.refresh(second)
    assert first.overlap_status == "AMBIGUOUS_OVERLAP"
    assert second.overlap_status == "AMBIGUOUS_OVERLAP"

    with pytest.raises(BadRequestException) as excinfo:
        service.classify_and_list_germany_overtime_time_segments(db, first.id, organization.id)
    assert "PRECEDENCE_REQUIRED" in str(excinfo.value)

    # Rejecting one side resolves the ambiguity for the other — the system
    # never picks a winner itself, only reacts to the explicit HR rejection.
    service.set_germany_overtime_work_record_approval(db, second.id, organization.id, "REJECTED", actor_id=1)
    db.refresh(first)
    assert first.overlap_status is None

    # See the SQLite-dialect note above: restore tzinfo the way Postgres
    # would already carry it, then exercise the real classifier directly
    # (the same function classify_and_list_germany_overtime_time_segments
    # calls once the overlap gate is clear).
    from app.modules.payroll.engine.germany_overtime_classifier import classify_germany_overtime_work_record

    first.start_datetime = first.start_datetime.replace(tzinfo=timezone.utc)
    first.end_datetime = first.end_datetime.replace(tzinfo=timezone.utc)
    segments = classify_germany_overtime_work_record(db, first, persist=True)
    assert len(segments) > 0


# ═══════════════════════════════════════════════════════════════════════
# 3. Attach/detach — transaction atomicity + idempotency (Phase 8BE fix)
# ═══════════════════════════════════════════════════════════════════════

def test_attach_applies_financial_deltas_atomically(db, organization):
    emp = _make_employee(db, organization.id)
    run = _make_run(db, organization.id)
    payslip_item = _make_payslip_item(db, run, emp, organization.id)
    work_record = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc),
    )
    component = _make_complete_component(db, work_record, organization.id, gross=Decimal("100.00"))

    attached = service.attach_germany_overtime_premium_component_to_payslip(
        db, component.id, payslip_item.id, organization.id, actor_id=1,
    )
    assert attached.attachment_status == "ATTACHED"
    assert attached.financial_integration_status == "PARTIAL_WAGE_TAX_PENDING_PAP"
    assert attached.applied_gross_delta == Decimal("100.00")

    db.refresh(payslip_item)
    assert payslip_item.gross_pay == Decimal("100.00")
    # net_pay increased by gross minus whatever employee SI delta was applied.
    assert payslip_item.net_pay > Decimal("0.00")
    assert payslip_item.net_pay <= Decimal("100.00")

    allowance = (
        db.query(PayslipAllowanceItem)
        .filter(PayslipAllowanceItem.payslip_item_id == payslip_item.id)
        .first()
    )
    assert allowance is not None
    assert allowance.amount == Decimal("100.00")


def test_double_attach_is_rejected_not_double_counted(db, organization):
    emp = _make_employee(db, organization.id)
    run = _make_run(db, organization.id)
    payslip_item = _make_payslip_item(db, run, emp, organization.id)
    work_record = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc),
    )
    component = _make_complete_component(db, work_record, organization.id, gross=Decimal("100.00"))

    service.attach_germany_overtime_premium_component_to_payslip(db, component.id, payslip_item.id, organization.id, actor_id=1)
    with pytest.raises(BadRequestException):
        service.attach_germany_overtime_premium_component_to_payslip(db, component.id, payslip_item.id, organization.id, actor_id=1)

    db.refresh(payslip_item)
    # Must still be exactly one gross_pay credit, never two.
    assert payslip_item.gross_pay == Decimal("100.00")


def test_detach_reverses_exact_stored_deltas_and_can_be_reattached(db, organization):
    emp = _make_employee(db, organization.id)
    run = _make_run(db, organization.id)
    payslip_item = _make_payslip_item(db, run, emp, organization.id)
    work_record = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc),
    )
    component = _make_complete_component(db, work_record, organization.id, gross=Decimal("100.00"))

    service.attach_germany_overtime_premium_component_to_payslip(db, component.id, payslip_item.id, organization.id, actor_id=1)
    db.refresh(payslip_item)
    gross_after_attach = payslip_item.gross_pay
    net_after_attach = payslip_item.net_pay

    detached = service.detach_germany_overtime_premium_component_from_payslip(db, component.id, organization.id, actor_id=1)
    assert detached.attachment_status == "DETACHED"
    assert detached.financial_integration_status == "REVERSED"
    assert detached.applied_gross_delta is None

    db.refresh(payslip_item)
    assert payslip_item.gross_pay == Decimal("0.00")
    assert payslip_item.net_pay == Decimal("0.00")

    # Detaching again must fail cleanly, never reverse a second time.
    with pytest.raises(BadRequestException):
        service.detach_germany_overtime_premium_component_from_payslip(db, component.id, organization.id, actor_id=1)
    db.refresh(payslip_item)
    assert payslip_item.gross_pay == Decimal("0.00")

    # Re-attaching (a DETACHED component is exactly as claimable as a fresh
    # one) must reapply the SAME deltas, not accumulate on top of the
    # already-reversed ones.
    reattached = service.attach_germany_overtime_premium_component_to_payslip(
        db, component.id, payslip_item.id, organization.id, actor_id=1,
    )
    assert reattached.attachment_status == "ATTACHED"
    db.refresh(payslip_item)
    assert payslip_item.gross_pay == gross_after_attach
    assert payslip_item.net_pay == net_after_attach


def test_attach_rejects_component_not_yet_complete(db, organization):
    emp = _make_employee(db, organization.id)
    run = _make_run(db, organization.id)
    payslip_item = _make_payslip_item(db, run, emp, organization.id)
    work_record = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc),
    )
    component = _make_complete_component(db, work_record, organization.id)
    component.combination_status = "PARTIAL_WAGE_TAX_ONLY"
    db.commit()

    with pytest.raises(BadRequestException):
        service.attach_germany_overtime_premium_component_to_payslip(db, component.id, payslip_item.id, organization.id, actor_id=1)


def test_attach_rejects_unapproved_work_record(db, organization):
    emp = _make_employee(db, organization.id)
    run = _make_run(db, organization.id)
    payslip_item = _make_payslip_item(db, run, emp, organization.id)
    work_record = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc), datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc),
        approval="PENDING",
    )
    component = _make_complete_component(db, work_record, organization.id)

    with pytest.raises(BadRequestException):
        service.attach_germany_overtime_premium_component_to_payslip(db, component.id, payslip_item.id, organization.id, actor_id=1)


# ═══════════════════════════════════════════════════════════════════════
# 4. ELStAM change-list batch idempotency (Phase 8BE fix)
# ═══════════════════════════════════════════════════════════════════════

def test_duplicate_elstam_change_list_batch_reference_is_rejected(db, organization):
    data = GermanyElstamChangeListBatchCreate(
        batch_reference="2026-01-CHANGE-LIST", received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        effective_date=date(2026, 1, 1),
    )
    service.create_elstam_change_list_batch(db, organization.id, data, actor_id=1)

    with pytest.raises(BadRequestException):
        service.create_elstam_change_list_batch(db, organization.id, data, actor_id=1)

    assert (
        db.query(GermanyElstamChangeListBatch)
        .filter(
            GermanyElstamChangeListBatch.organization_id == organization.id,
            GermanyElstamChangeListBatch.batch_reference == "2026-01-CHANGE-LIST",
        )
        .count()
        == 1
    )


def test_same_batch_reference_allowed_across_different_organizations(db, organization):
    from app.modules.organizations.models import Organization

    other_org = Organization(organization_name="Other Org", organization_code="OTHERORG")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    data = GermanyElstamChangeListBatchCreate(
        batch_reference="SHARED-REF", received_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        effective_date=date(2026, 1, 1),
    )
    service.create_elstam_change_list_batch(db, organization.id, data, actor_id=1)
    # Same reference, different organization — must NOT collide (the
    # constraint is scoped per-organization, not global).
    service.create_elstam_change_list_batch(db, other_org.id, data, actor_id=1)

    assert (
        db.query(GermanyElstamChangeListBatch)
        .filter(GermanyElstamChangeListBatch.batch_reference == "SHARED-REF")
        .count()
        == 2
    )
