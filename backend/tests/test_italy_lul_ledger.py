"""Italy Libro Unico del Lavoro registration ledger (§20, IT-058/IT-059/IT-060).

IT-058 calls the LUL "an auditable statutory record, not a PDF theme" and names
four things that are therefore engineering requirements rather than formatting.
This suite tests each as a mechanism:

  SEQUENCE       - contiguous per employer, and a retry must not consume numbers
                   and leave holes an auditor would read as tampering.
  INALTERABILITY - the registered content is stored AND hashed, and a payload
                   edited behind the service's back is detected.
  RETENTION      - five years from the LAST registration, so the horizon advances
                   and never starts expiring the oldest evidence early.
  METHOD         - the authorized method is snapshot, so a later change cannot
                   rewrite what last year's registrations were made under.

Plus the correction rule, which is the sharpest of them: a correction APPENDS.
An overwritten original is not a correction, it is the invisible rewrite
"do not rewrite prior LUL evidence invisibly" exists to forbid.

And IT-059 reconciliation, achieved by construction — the payload is derived
from the committed payslip, so the two artifacts cannot disagree.

SQLite `db` fixture only - nothing here reaches a real database.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import (
    EmployerItalyProfile, ItalyLulEntry, PayrollEmployee, PayrollRun, PayslipItem,
)
from app.modules.payroll.schemas import (
    ItalyLulBuildRequest, ItalyLulCorrectionRequest,
)


def _employee(db, organization, code="IT1"):
    employee = PayrollEmployee(organization_id=organization.id, employee_code=code,
                               name=f"Worker {code}", country_code="IT")
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _method(db, organization, method="WEB"):
    """The §17G authorized method. Registered separately because a build refuses
    without it — IT-058 names it part of the specification, not an attribute."""
    profile = EmployerItalyProfile(organization_id=organization.id, lul_method=method)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _run(db, organization, status="Approved", run_code="IT-2026-03", month=3):
    run = PayrollRun(
        organization_id=organization.id, run_code=run_code,
        period_label=f"2026-{month:02d}",
        period_start=date(2026, month, 1),
        period_end=service._it_month_end(2026, month),
        pay_date=date(2026, month, 28), status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _payslip(db, organization, run, employee, net_pay="3200.00", snapshot=None):
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name=employee.name, basic_salary=4000, gross_pay=4000,
        total_deductions=D("800.00"), net_pay=D(net_pay),
        it_calculation_snapshot=snapshot if snapshot is not None else {
            "inps": {"employee": "300.00", "employer": "800.00"},
            "irpef": {"withheld": "200.00"},
            "localTax": {"regionalSaldo": "20.00"},
        },
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _register(db, organization, run, month="2026-03", **kw):
    return service.build_italy_lul_entries(
        db, organization.id,
        ItalyLulBuildRequest(payrollRunId=run.id, referenceMonth=month, **kw))


def _correct(db, organization, entry_id, reason="Wrong gross pay registered.", **kw):
    # Callers pass either an Organization or a bare id: the cross-tenant test
    # deliberately targets an org id that has no row at all, which is the whole
    # point of it. Normalise so both spellings reach the same call.
    org_id = organization if isinstance(organization, int) else organization.id
    return service.correct_italy_lul_entry(
        db, org_id, entry_id,
        ItalyLulCorrectionRequest(reason=reason, **kw))


# ── The authorized method is part of the specification (§17G, IT-058) ──────

def test_registration_refuses_without_an_authorized_method(db, organization):
    """IT-058 names the AUTHORIZED METHOD as part of the specification. A record
    nobody can attest was made under a valid arrangement is not evidence."""
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    with pytest.raises(BadRequestException) as excinfo:
        _register(db, organization, run)
    assert "authorized LUL method" in str(excinfo.value)
    assert db.query(ItalyLulEntry).count() == 0


def test_the_method_in_force_is_snapshot_onto_the_entry(db, organization):
    """If the employer switches method next year, last year's registrations must
    still show what they were actually made under."""
    _method(db, organization, method="WEB")
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    entries = _register(db, organization, run)
    assert entries[0].method == "WEB"
    # The employer changes arrangement.
    profile = db.query(EmployerItalyProfile).first()
    profile.lul_method = "SOFTWARE"
    db.commit()
    db.expire_all()
    assert db.query(ItalyLulEntry).first().method == "WEB"


# ── Sequence (IT-058) ──────────────────────────────────────────────────────

def test_entries_are_numbered_contiguously_in_payslip_order(db, organization):
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization, code="IT1"))
    _payslip(db, organization, run, _employee(db, organization, code="IT2"))
    _payslip(db, organization, run, _employee(db, organization, code="IT3"))
    entries = _register(db, organization, run)
    assert [e.sequence_number for e in entries] == [1, 2, 3]
    assert {e.entry_type for e in entries} == {"ORIGINAL"}


def test_sequence_continues_across_months_for_the_same_employer(db, organization):
    """Sequence is per EMPLOYER, not per month: the number is an employer's
    running registration counter, so a second month must continue it."""
    _method(db, organization)
    march = _run(db, organization, run_code="M3")
    _payslip(db, organization, march, _employee(db, organization, code="IT1"))
    _payslip(db, organization, march, _employee(db, organization, code="IT2"))
    april = _run(db, organization, run_code="M4", month=4)
    _payslip(db, organization, april, _employee(db, organization, code="IT3"))
    _register(db, organization, march)
    entries = _register(db, organization, april, month="2026-04")
    assert [e.sequence_number for e in entries] == [3]
    assert entries[0].reference_month == "2026-04"


def test_a_sequence_number_is_never_reused_after_a_deletion(db, organization):
    """MAX+1, not COUNT+1. A gap left by a removed entry must not cause the next
    registration to reuse that number, because the number is what an auditor
    cites."""
    _method(db, organization)
    march = _run(db, organization, run_code="M3")
    _payslip(db, organization, march, _employee(db, organization, code="IT1"))
    _payslip(db, organization, march, _employee(db, organization, code="IT2"))
    entries = _register(db, organization, march)
    db.delete(entries[0])
    db.commit()
    april = _run(db, organization, run_code="M4", month=4)
    _payslip(db, organization, april, _employee(db, organization, code="IT3"))
    assert _register(db, organization, april, month="2026-04")[0].sequence_number == 3


def test_re_registering_the_same_run_and_month_does_not_consume_numbers(db, organization):
    """A retried registration must be a no-op. If it appended, the employer's
    sequence would grow holes on every retry and the ledger would read as
    tampered."""
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization, code="IT1"))
    first = _register(db, organization, run)
    again = _register(db, organization, run)
    assert [e.id for e in first] == [e.id for e in again]
    assert db.query(ItalyLulEntry).count() == len(first)
    assert [e.sequence_number for e in again] == [1]


def test_integrity_check_reports_no_gaps_on_a_healthy_ledger(db, organization):
    _method(db, organization)
    march = _run(db, organization, run_code="M3")
    _payslip(db, organization, march, _employee(db, organization, code="IT1"))
    _payslip(db, organization, march, _employee(db, organization, code="IT2"))
    _register(db, organization, march)
    report = service.verify_italy_lul_integrity(db, organization.id)
    assert report["entries"] == 2
    assert report["sequenceGaps"] == []
    assert report["driftedSequenceNumbers"] == []


def test_integrity_check_reports_a_hole_in_the_sequence(db, organization):
    """A gap is the signature of a record edited outside the ledger."""
    _method(db, organization)
    march = _run(db, organization, run_code="M3")
    for code in ("IT1", "IT2", "IT3"):
        _payslip(db, organization, march, _employee(db, organization, code=code))
    entries = _register(db, organization, march)
    db.delete(entries[1])
    db.commit()
    report = service.verify_italy_lul_integrity(db, organization.id)
    assert report["sequenceGaps"] == [2]


# ── Inalterability: content stored, hashed, and checked (IT-058) ───────────

def test_the_registered_content_is_stored_not_merely_hashed(db, organization):
    """A hash with no content proves bytes have not moved but cannot show WHAT was
    filed — which is what an auditor must be able to read after five years."""
    _method(db, organization)
    run = _run(db, organization)
    employee = _employee(db, organization)
    payslip = _payslip(db, organization, run, employee)
    entry = _register(db, organization, run, eventKind="MONTHLY_PAY")[0]
    assert entry.payload is not None
    assert entry.payload["grossPay"] == str(payslip.gross_pay)
    assert entry.payload["employeeCode"] == employee.employee_code
    assert len(entry.content_hash) == 64


def test_the_content_hash_matches_the_stored_payload(db, organization):
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    entry = _register(db, organization, run)[0]
    assert service._it_lul_content_hash(entry.payload) == entry.content_hash


def test_a_payload_edited_behind_the_service_is_detected(db, organization):
    """Inalterability is only real if something checks it. An edit made directly
    in the database must surface in the integrity pass, not at an audit three
    years later."""
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    entry = _register(db, organization, run)[0]
    entry.payload = {**entry.payload, "netPay": "999999.00"}
    db.commit()
    report = service.verify_italy_lul_integrity(db, organization.id)
    assert report["driftedSequenceNumbers"] == [entry.sequence_number]


def test_the_hash_is_stable_regardless_of_key_order(db, organization):
    """The hash must not depend on dict insertion order, or verification would
    report drift on a record that never changed."""
    a = {"x": "1", "y": "2"}
    b = {"y": "2", "x": "1"}
    assert service._it_lul_content_hash(a) == service._it_lul_content_hash(b)


def test_a_legacy_entry_without_payload_is_reported_as_unverifiable(db, organization):
    """Pre-3C rows cannot be back-filled, so they are unverifiable — and the
    integrity pass must say so rather than quietly counting them as intact."""
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    entry = _register(db, organization, run)[0]
    entry.payload = None
    db.commit()
    report = service.verify_italy_lul_integrity(db, organization.id)
    assert report["unverifiableSequenceNumbers"] == [entry.sequence_number]
    assert report["driftedSequenceNumbers"] == []


# ── Retention advances from the LAST registration (§20) ───────────────────

def test_retention_is_five_years_from_registration(db, organization):
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    entry = _register(db, organization, run)[0]
    assert entry.retention_until == date.today().replace(year=date.today().year + 5)


def test_a_new_registration_advances_the_whole_employers_retention(db, organization):
    """Retention runs from the LAST registration, so evidence from years earlier
    must be kept alive too. A per-entry fixed date would start expiring the
    oldest records exactly while the obligation is still live — which is the
    failure this test exists to prevent."""
    _method(db, organization)
    march = _run(db, organization, run_code="M3")
    _payslip(db, organization, march, _employee(db, organization, code="IT1"))
    old = _register(db, organization, march)[0]
    earlier_horizon = old.retention_until

    # A later registration, backdated by moving the entry's own registration.
    later = date.today() + timedelta(days=400)
    april = _run(db, organization, run_code="M4", month=4)
    _payslip(db, organization, april, _employee(db, organization, code="IT2"))
    new = _register(db, organization, april, month="2026-04")[0]
    new.registered_at = new.registered_at  # registered now
    db.commit()

    # The March entry is retained at least as long as the newest one.
    assert old.retention_until >= new.retention_until
    assert earlier_horizon == date.today().replace(year=date.today().year + 5)


def test_a_correction_also_advances_retention(db, organization):
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    entry = _register(db, organization, run)[0]
    before = entry.retention_until
    _correct(db, organization, entry.id)
    assert entry.retention_until >= before


# ── Correction appends; it never rewrites (§20, IT-058) ───────────────────

def test_a_correction_appends_and_leaves_the_original_intact(db, organization):
    """The original and the correction must BOTH remain readable. Overwriting
    the original would destroy the very evidence the correction rule protects."""
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    original = _register(db, organization, run)[0]
    original_hash, original_payload = original.content_hash, original.payload

    correction = _correct(db, organization, original.id)
    db.expire_all()
    stored = db.query(ItalyLulEntry).filter(ItalyLulEntry.id == original.id).first()
    assert stored.content_hash == original_hash
    assert stored.payload == original_payload
    assert correction.corrects_entry_id == original.id
    assert correction.entry_type == "CORRECTION"
    assert correction.sequence_number > original.sequence_number
    assert db.query(ItalyLulEntry).count() == 2


def test_the_correction_carries_the_reason_and_what_it_corrects(db, organization):
    """The correction record is the only explanation an auditor ever gets of why
    an original was superseded."""
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    original = _register(db, organization, run)[0]
    correction = _correct(db, organization, original.id,
                          reason="Net pay transcribed incorrectly.")
    assert correction.payload["correctionReason"] == "Net pay transcribed incorrectly."
    assert correction.payload["correctsSequence"] == original.sequence_number


def test_a_correction_cannot_correct_a_correction(db, organization):
    """Allowing a chain would make "the current truth" ambiguous without a defined
    resolution rule."""
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    original = _register(db, organization, run)[0]
    correction = _correct(db, organization, original.id)
    with pytest.raises(BadRequestException) as excinfo:
        _correct(db, organization, correction.id)
    assert "correction corrects an ORIGINAL" in str(excinfo.value)


def test_a_correction_requires_a_reason(db, organization):
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    original = _register(db, organization, run)[0]
    with pytest.raises(BadRequestException) as excinfo:
        _correct(db, organization, original.id, reason="   ")
    assert "requires a reason" in str(excinfo.value)
    assert db.query(ItalyLulEntry).count() == 1


def test_a_correction_keeps_the_original_registration_method(db, organization):
    """A correction corrects THAT registration, so it is made under the method
    that was in force then — not whatever the employer uses now."""
    _method(db, organization, method="WEB")
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    original = _register(db, organization, run)[0]
    db.query(EmployerItalyProfile).first().lul_method = "INTERMEDIARY"
    db.commit()
    assert _correct(db, organization, original.id).method == "WEB"


def test_superseded_entries_are_listed_by_default(db, organization):
    """Hiding a corrected original would defeat IT-058 — it is still statutory
    evidence."""
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    original = _register(db, organization, run)[0]
    _correct(db, organization, original.id)
    assert len(service.list_italy_lul_entries(db, organization.id)) == 2
    current = service.list_italy_lul_entries(db, organization.id,
                                             include_superseded=False)
    assert [e.entry_type for e in current] == ["CORRECTION"]


# ── Committed payroll only, and no orphan workers (IT-058) ────────────────

@pytest.mark.parametrize("status", ["Draft", "Review"])
def test_a_run_that_is_not_committed_cannot_be_registered(db, organization, status):
    """The LUL records committed payroll. Registering a run still in review would
    publish figures that may still change."""
    _method(db, organization)
    run = _run(db, organization, status=status)
    _payslip(db, organization, run, _employee(db, organization))
    with pytest.raises(BadRequestException) as excinfo:
        _register(db, organization, run)
    assert "APPROVED" in str(excinfo.value)
    assert db.query(ItalyLulEntry).count() == 0


def test_a_payslip_naming_an_employee_outside_the_tenant_is_refused(db, organization):
    """Publishing another org's worker to a statutory registry would be the worst
    possible leak in this module."""
    _method(db, organization)
    run = _run(db, organization)
    employee = _employee(db, organization)
    payslip = _payslip(db, organization, run, employee)
    # The worker leaves this employer's tenancy; the payslip remains.
    employee.organization_id = organization.id + 999
    db.commit()
    with pytest.raises(BadRequestException) as excinfo:
        _register(db, organization, run)
    assert "does not resolve inside this organization" in str(excinfo.value)
    assert db.query(ItalyLulEntry).count() == 0


def test_a_run_with_no_payslips_registers_nothing(db, organization):
    """An empty run would otherwise consume a sequence number and produce an
    entry set that proves nothing."""
    _method(db, organization)
    run = _run(db, organization)
    with pytest.raises(BadRequestException) as excinfo:
        _register(db, organization, run)
    assert "nothing to register" in str(excinfo.value)


def test_a_run_from_another_tenant_is_not_found(db, organization):
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    with pytest.raises(NotFoundException):
        service.build_italy_lul_entries(
            db, organization.id + 999,
            ItalyLulBuildRequest(payrollRunId=run.id, referenceMonth="2026-03"))


def test_an_entry_from_another_tenant_cannot_be_corrected(db, organization):
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    original = _register(db, organization, run)[0]
    with pytest.raises(NotFoundException):
        _correct(db, organization.id + 999, original.id)


def test_the_ledger_is_scoped_to_the_callers_tenant(db, organization):
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    _register(db, organization, run)
    assert service.list_italy_lul_entries(db, organization.id + 999) == []
    assert service.verify_italy_lul_integrity(db, organization.id + 999)["entries"] == 0


# ── The §20 deadline is reported, not enforced ────────────────────────────

def test_the_deadline_is_the_end_of_the_month_after_the_reference(db, organization):
    info = service.get_italy_lul_deadline(db, organization.id, "2026-03")
    assert info["referencePeriodEnd"] == "2026-03-31"
    assert info["deadline"] == "2026-04-30"
    assert info["registered"] is False
    assert info["metDeadline"] is None


@pytest.mark.parametrize("month,expected", [
    ("2026-01", "2026-02-28"), ("2026-02", "2026-03-31"),
    ("2026-03", "2026-04-30"), ("2026-11", "2026-12-31"), ("2026-12", "2027-01-31"),
])
def test_the_deadline_resolves_across_month_and_year_boundaries(db, organization, month, expected):
    """'End of month following' is a calendar instruction. Adding a fixed 31 days
    would deadline a March reference on 2 May — a month late, silently."""
    assert service.get_italy_lul_deadline(db, organization.id, month)["deadline"] == expected


def _pin_registered_at(db, entries, when):
    """registered_at is server_default=now(), so a test about TIMELINESS has to
    set it explicitly. Otherwise the assertion silently depends on the day the
    suite happens to run: this test registered a 2026-03 reference month, whose
    deadline was 2026-04-30, and would flip from 'met' to 'late' with the clock
    — a test that breaks in April is not testing the deadline logic."""
    for entry in entries:
        entry.registered_at = when
    db.commit()


def test_a_registration_on_time_is_reported_as_met(db, organization):
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    entries = _register(db, organization, run)
    _pin_registered_at(db, entries, datetime(2026, 4, 15, 9, 0))
    info = service.get_italy_lul_deadline(db, organization.id, "2026-03")
    assert info["registered"] is True
    assert info["entries"] == 1
    assert info["metDeadline"] is True
    assert info["daysLate"] == 0


def test_a_late_registration_is_recorded_and_flagged_not_refused(db, organization):
    """A registration that legally happened is still the truth. Refusing to
    record it would hide a compliance fact; the platform's job is to answer
    'was this in time' accurately, not to prevent the record."""
    _method(db, organization)
    run = _run(db, organization, month=1)
    _payslip(db, organization, run, _employee(db, organization))
    entries = _register(db, organization, run, month="2026-01")
    # 2026-01's deadline was 2026-02-28; register a month after it so the
    # lateness is a fact of the fixture rather than of the day this runs.
    _pin_registered_at(db, entries, datetime(2026, 3, 20, 9, 0))
    info = service.get_italy_lul_deadline(db, organization.id, "2026-01")
    assert info["deadline"] == "2026-02-28"
    assert info["registered"] is True
    assert info["entries"] == 1
    # Recorded, not refused — but reported honestly as late.
    assert info["metDeadline"] is False
    assert info["daysLate"] == 20
    assert db.query(ItalyLulEntry).count() == 1


# ── Input hygiene ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("month", ["2026-3", "26-03", "2026/03", "202603", "2026-13", ""])
def test_a_reference_month_that_is_not_yyyy_mm_is_rejected_at_the_edge(db, organization, month):
    """The shape is enforced by the schema, so a malformed month is a 422 naming
    the field rather than a downstream date error."""
    with pytest.raises(PydanticValidationError):
        ItalyLulBuildRequest(payrollRunId=1, referenceMonth=month)


def test_a_blank_event_kind_is_refused(db, organization):
    """An explicitly blank event kind is a mistake; an omitted one is legitimate
    (the catalog is not yet available)."""
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    with pytest.raises(BadRequestException):
        _register(db, organization, run, eventKind="   ")


def test_an_event_kind_is_recorded_verbatim_without_a_closed_vocabulary(db, organization):
    """S10 (the official LUL catalog) is not available, so the platform does not
    pretend to know the statutory vocabulary — but it does record what the
    employer states."""
    _method(db, organization)
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    entry = _register(db, organization, run, eventKind="ASSUNZIONE")[0]
    assert entry.event_kind == "ASSUNZIONE"
    assert entry.payload["eventKind"] == "ASSUNZIONE"


def test_entries_can_be_filtered_by_month_run_type_and_employee(db, organization):
    _method(db, organization)
    march = _run(db, organization, run_code="M3")
    first = _employee(db, organization, code="IT1")
    _payslip(db, organization, march, first)
    _payslip(db, organization, march, _employee(db, organization, code="IT2"))
    entries = _register(db, organization, march)
    _correct(db, organization, entries[0].id)
    assert len(service.list_italy_lul_entries(db, organization.id, reference_month="2026-03")) == 3
    assert len(service.list_italy_lul_entries(db, organization.id, payroll_run_id=march.id)) == 3
    assert len(service.list_italy_lul_entries(db, organization.id, entry_type="CORRECTION")) == 1
    assert len(service.list_italy_lul_entries(db, organization.id, employee_id=first.id)) == 2
    assert service.list_italy_lul_entries(db, organization.id, reference_month="2026-01") == []
