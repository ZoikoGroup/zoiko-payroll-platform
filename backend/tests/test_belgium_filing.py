"""Belgium (ZP-BE-ENG-001) Block C1: filings and obligations (spec §10, §16
Dimona/DmfA family; BE-014 / BE-018 / BE-033 .. BE-037; D9).

SYNTHETIC TEST ONLY content (tests/_be_filing_helpers.py: made-up schema
versions TEST-A / TEST-B, a synthetic XSD and renderer). Users: a = maker,
b = checker, c = third person."""
import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException, NotFoundException
from tests._be_filing_helpers import REAL_ARCHIVED_SCHEMA, accept, broken_renderer, install_filing_content
from tests.test_belgium_run_lifecycle import NISS, _approve, _run, world  # noqa: F401  (pytest fixture)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _bf():
    from app.modules.payroll import belgium_filing

    return belgium_filing


def _filings(w, **filters):
    from app.modules.payroll.models import PayrollBeFiling

    return w.db.query(PayrollBeFiling).filter_by(organization_id=w.org, **filters).order_by(PayrollBeFiling.id).all()


def _classification(w):
    from app.modules.payroll.models import PayrollBeEmploymentClassification

    return w.db.query(PayrollBeEmploymentClassification).filter_by(organization_id=w.org, status="ACTIVE").one()


def _source(w):
    from app.modules.payroll.models import SourceArtifact

    row = SourceArtifact(agency="TEST ONLY", title="TEST ONLY operational calendar")
    w.db.add(row)
    w.db.flush()
    return row


def _calendar(w, report_type, period, due, status="Active", sourced=True):
    from app.modules.payroll.models import StatutoryFilingCalendar

    row = StatutoryFilingCalendar(jurisdiction_country="BE", report_type=report_type, reporting_year=period[:4],
                                  period_key=period, period_label=f"TEST ONLY {period}", due_date=due, status=status,
                                  source_document_id=_source(w).id if sourced else None)
    w.db.add(row)
    w.db.commit()
    return row


# ── Dimona (BE-033) ────────────────────────────────────────────────────────
def test_on_time_dimona_in_is_accepted_and_clears_the_preflight(world):
    w = world
    dimona = _filings(w, form_code="DIMONA")
    assert [(f.kind, f.status, f.payload["event"]) for f in dimona] == [("ORIGINAL", "ACCEPTED", "IN")]
    payload = dimona[0].payload
    assert payload["startDate"] == "2025-01-01" and payload["employmentLine"] == "MAIN"
    assert dimona[0].authority == "ONSS" and dimona[0].receipt_ref and dimona[0].mandate_ref == "TEST ONLY"
    assert _bf().dimona_status(w.db, w.org, w.employee.id, "MAIN", date(2026, 3, 31))["ok"]
    assert not [x for x in _bf().exception_queue(w.db, w.org) if x["category"] == "LATE_DIMONA"]
    # rebuilding with nothing changed is a no-op (idempotent)
    again = _bf().build_be_dimona_events(w.db, w.org, w.employee.id, w.a)
    assert [r.id for r in again] == [dimona[0].id] and len(_filings(w, form_code="DIMONA")) == 1


def test_late_and_rejected_dimona_events_reach_the_exception_queue(world):
    from app.modules.payroll import belgium_service as be

    w = world
    line = _classification(w)
    line.employment_line = "SECOND"                           # a new line with no Dimona yet (TEST ONLY edit)
    w.db.commit()
    rows = _bf().build_be_dimona_events(w.db, w.org, w.employee.id, w.a)
    w.db.commit()
    late = [x for x in _bf().exception_queue(w.db, w.org, today="2026-03-01") if x["category"] == "LATE_DIMONA"]
    assert [x["filingId"] for x in late] == [rows[0].id] and late[0]["blocks"] == "payroll"
    bf = _bf()
    bf.validate_be_filing(w.db, w.org, rows[0].id, w.a)
    bf.approve_be_filing(w.db, w.org, rows[0].id, w.b)
    bf.record_be_filing_submission(w.db, w.org, rows[0].id, {"submissionRef": "SUB-LATE"}, w.a)
    with pytest.raises(BadRequestException, match="errorCodes"):
        bf.record_be_filing_response(w.db, w.org, rows[0].id, {"outcome": "REJECTED"}, w.a)
    bf.record_be_filing_response(w.db, w.org, rows[0].id, {"outcome": "REJECTED", "errorCodes": ["TEST-E1"]}, w.a)
    w.db.commit()
    queue = bf.exception_queue(w.db, w.org)
    assert {"REJECTED_FILING", "LATE_DIMONA"} <= {x["category"] for x in queue}
    assert bf.dimona_status(w.db, w.org, w.employee.id, "SECOND", date(2026, 3, 31))["code"] == \
        "BE_DIMONA_IN_NOT_ACCEPTED"
    # a rejected event is followed by a NEW ORIGINAL version linked to it (never an edit)
    line.contract_start_date = date(2025, 1, 2)
    w.db.commit()
    retry = bf.build_be_dimona_events(w.db, w.org, w.employee.id, w.a)[0]
    assert (retry.kind, retry.version, retry.previous_version_id) == ("ORIGINAL", 2, rows[0].id)
    assert rows[0].status == "REJECTED" and rows[0].rejection["codes"] == ["TEST-E1"]
    assert retry.idempotency_key != rows[0].idempotency_key
    assert be                                                     # imported for the seam


def test_a_changed_period_after_acceptance_is_a_linked_update_never_an_overwrite(world):
    w = world
    original = _filings(w, form_code="DIMONA")[0]
    sent = json.dumps(original.payload, sort_keys=True)
    line = _classification(w)
    line.contract_type, line.contract_end_date = "FIXED_TERM", date(2026, 12, 31)
    w.db.commit()
    rows = _bf().build_be_dimona_events(w.db, w.org, w.employee.id, w.a)
    w.db.commit()
    update = [r for r in rows if r.kind == "CORRECTION"]
    out = [r for r in rows if r.payload.get("event") == "OUT"]
    assert len(update) == 1 and update[0].corrects_id == original.id
    assert update[0].payload["event"] == "UPDATE" and update[0].payload["previousEndDate"] is None
    assert update[0].payload["endDate"] == "2026-12-31"
    assert len(out) == 1 and out[0].payload["inFilingId"] == original.id and out[0].period_key == "2026-12-31"
    assert json.dumps(original.payload, sort_keys=True) == sent and original.status == "ACCEPTED"   # untouched
    # cancelling the IN is a CANCELLATION linked to it (reason required)
    with pytest.raises(BadRequestException, match="reason"):
        _bf().build_be_dimona_events(w.db, w.org, w.employee.id, w.a, event="CANCEL")
    cancel = _bf().build_be_dimona_events(w.db, w.org, w.employee.id, w.a, event="CANCEL", reason="TEST ONLY")[0]
    assert (cancel.kind, cancel.corrects_id, cancel.payload["event"]) == ("CANCELLATION", original.id, "CANCEL")


def test_a_line_without_a_contract_start_cannot_be_declared(world):
    w = world
    _classification(w).contract_start_date = None
    w.db.commit()
    with pytest.raises(HTTPException, match="BE_DIMONA_START_MISSING"):
        _bf().build_be_dimona_events(w.db, w.org, w.employee.id, w.a)


# ── state machine, four-eyes, transmission (D9) ────────────────────────────
def _dmfa(w):
    _approve(w, _run(w))
    filing, obligations = _bf().build_be_dmfa(w.db, w.org, "2026Q1", None, w.a)
    w.db.commit()
    return filing, obligations


def test_the_filing_state_machine_and_four_eyes(world):
    bf = _bf()
    w = world
    filing, _o = _dmfa(w)
    with pytest.raises(BadRequestException, match="VALIDATED"):
        bf.approve_be_filing(w.db, w.org, filing.id, w.b)
    with pytest.raises(BadRequestException, match="APPROVED"):
        bf.record_be_filing_submission(w.db, w.org, filing.id, {"submissionRef": "S"}, w.a)
    with pytest.raises(BadRequestException, match="TRANSMITTED"):
        bf.record_be_filing_response(w.db, w.org, filing.id, {"outcome": "ACCEPTED", "receiptRef": "R"}, w.a)
    bf.validate_be_filing(w.db, w.org, filing.id, w.a)
    assert filing.status == "VALIDATED" and filing.schema_version == "TEST-A"
    w.db.commit()                                         # the routes commit; a refused four-eyes attempt rolls back
    with pytest.raises(BadRequestException, match="preparer|approver|four"):
        bf.approve_be_filing(w.db, w.org, filing.id, w.a)               # the maker cannot approve
    bf.approve_be_filing(w.db, w.org, filing.id, w.b)
    assert filing.status == "APPROVED"
    with pytest.raises(HTTPException, match="BE_TRANSMISSION_NOT_CERTIFIED"):
        bf.transmit_be_filing(w.db, w.org, filing.id, w.a)                 # D9: G3 not certified
    bf.record_be_filing_submission(w.db, w.org, filing.id, {"submissionRef": "SUB-1", "mandateRef": "M-1"}, w.a)
    assert bf.record_be_filing_submission(w.db, w.org, filing.id, {"submissionRef": "SUB-1"}, w.a) is filing
    with pytest.raises(HTTPException, match="ALREADY_SUBMITTED"):
        bf.record_be_filing_submission(w.db, w.org, filing.id, {"submissionRef": "SUB-2"}, w.a)
    bf.record_be_filing_response(w.db, w.org, filing.id, {"outcome": "ACCEPTED", "receiptRef": "R-1"}, w.a)
    assert bf.record_be_filing_response(w.db, w.org, filing.id, {"outcome": "ACCEPTED", "receiptRef": "R-1"},
                                        w.a) is filing                      # idempotent retry
    with pytest.raises(HTTPException, match="immutable"):
        bf.record_be_filing_response(w.db, w.org, filing.id, {"outcome": "REJECTED", "errorCodes": ["X"]}, w.a)
    view = bf.get_be_filing(w.db, w.org, filing.id)
    assert (view["status"], view["receiptRef"], view["mandateRef"], view["transmittedById"]) == \
        ("ACCEPTED", "R-1", "M-1", w.a)
    assert view["rendition"] and view["payloadHash"] == bf.canonical_hash(view["payload"])   # BE-037


def test_the_database_refuses_an_approval_by_the_creator(world):
    from sqlalchemy.exc import IntegrityError

    w = world
    filing, _o = _dmfa(w)
    filing.status, filing.schema_version, filing.approved_by_id = "APPROVED", "TEST-A", w.a
    with pytest.raises(IntegrityError):
        w.db.commit()
    w.db.rollback()


def test_filings_are_scoped_to_the_organisation(world):
    from tests._mx_employer_helpers import make_org

    w = world
    filing, _o = _dmfa(w)
    other = make_org(w.db, name="Other BV", code="BEOTHR", admins=1, country="BE").org.id
    with pytest.raises(NotFoundException):
        _bf().get_be_filing(w.db, other, filing.id)
    assert _bf().list_be_filings(w.db, other) == [] and _bf().list_be_obligations(w.db, other) == []


# ── idempotency and personal data (BE-037, spec §15) ───────────────────────
def test_builds_are_idempotent_and_carry_no_personal_data(world):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import TaxConfigurationAudit

    w = world
    be.create_be_identifier(w.db, w.org, "NISS", NISS, w.a, employee_id=w.employee.id)
    w.db.commit()
    filing, obligations = _dmfa(w)
    again, again_obligations = _bf().build_be_dmfa(w.db, w.org, "2026Q1", None, w.a)
    assert again.id == filing.id and again.idempotency_key == filing.idempotency_key
    assert [o.id for o in again_obligations] == [o.id for o in obligations]
    assert len(_filings(w, form_code="DMFA")) == 1
    text = json.dumps([filing.payload, filing.rendition, filing.idempotency_key,
                       [o.obligation_key for o in obligations]], default=str)
    assert NISS not in text and w.employee.name not in filing.idempotency_key
    assert filing.payload["workers"][0]["identifierMasked"] and NISS not in filing.payload["workers"][0][
        "identifierMasked"]
    audits = json.dumps([[a.new_value, a.old_value, a.reason] for a in w.db.query(TaxConfigurationAudit).all()],
                        default=str)
    assert NISS not in audits


# ── schema registry: the 30 Sep / 1 Oct boundary (BE-034) ───────────────────
BOUNDARY = {"DMFA": [("2026-01-01", "2026-09-30", "TEST-A"), ("2026-10-01", None, "TEST-B")]}


def test_the_schema_is_chosen_by_submission_date_across_the_boundary(world, monkeypatch):
    bf = _bf()
    w = world
    filing, _o = _dmfa(w)
    install_filing_content(monkeypatch, versions=BOUNDARY)
    bf.validate_be_filing(w.db, w.org, filing.id, w.a, "2026-09-30")
    assert (filing.status, filing.schema_version) == ("VALIDATED", "TEST-A")
    bf.validate_be_filing(w.db, w.org, filing.id, w.a, "2026-10-01")
    assert (filing.status, filing.schema_version) == ("VALIDATED", "TEST-B")
    bf.validate_be_filing(w.db, w.org, filing.id, w.a, "2026-09-30")
    # validated for 30 Sep, approved on 1 Oct: the schema changed -> back to DRAFT, validate again
    with pytest.raises(HTTPException, match="FILING_SCHEMA_MISMATCH"):
        bf.approve_be_filing(w.db, w.org, filing.id, w.b, on="2026-10-01")
    assert filing.status == "DRAFT" and filing.schema_version is None and "validate again" in filing.validation_note
    # approved on 30 Sep, submitted on 1 Oct: refused the same way
    bf.validate_be_filing(w.db, w.org, filing.id, w.a, "2026-09-30")
    bf.approve_be_filing(w.db, w.org, filing.id, w.b, on="2026-09-30")
    with pytest.raises(HTTPException, match="FILING_SCHEMA_MISMATCH"):
        bf.record_be_filing_submission(w.db, w.org, filing.id, {"submissionRef": "S"}, w.a, on="2026-10-01")
    assert filing.status == "DRAFT"


@pytest.mark.parametrize("case, note", [
    ("pending", "schema version content pending"),
    ("archive", "schema not archived"),
    ("mapping", "no mapping of the canonical payload"),
    ("xsd", "XSD validation failed"),
])
def test_without_signed_archived_mapped_schema_the_filing_stays_draft(world, monkeypatch, case, note):
    bf = _bf()
    w = world
    filing, _o = _dmfa(w)
    if case == "pending":
        install_filing_content(monkeypatch, versions={})
    elif case == "archive":
        install_filing_content(monkeypatch, archived=False)
    elif case == "mapping":
        monkeypatch.setattr(bf, "RENDERERS", {})
    else:
        install_filing_content(monkeypatch, renderer=broken_renderer)
    bf.validate_be_filing(w.db, w.org, filing.id, w.a)
    assert filing.status == "DRAFT" and note in filing.validation_note
    assert any(x["category"] == "FILING_NOT_VALIDATED" for x in bf.exception_queue(w.db, w.org))
    with pytest.raises(BadRequestException, match="VALIDATED"):
        bf.approve_be_filing(w.db, w.org, filing.id, w.b)


def test_a_source_without_an_archived_file_is_not_an_archived_schema(world):
    w = world
    row = {"source_document_id": _source(w).id}
    assert REAL_ARCHIVED_SCHEMA(w.db, row) is None
    assert REAL_ARCHIVED_SCHEMA(w.db, {"source_document_id": None}) is None


# ── DmfA content and the authority calendar (BE-034 / BE-035) ──────────────
def test_dmfa_is_built_from_the_ledger_per_employment_line(world):
    from app.modules.payroll.models import PayrollBeAccumulatorEntry, PayslipItem

    w = world
    filing, obligations = _dmfa(w)
    entries = w.db.query(PayrollBeAccumulatorEntry).filter_by(organization_id=w.org).all()
    ledger = {}
    for e in entries:
        ledger[e.accumulator] = ledger.get(e.accumulator, Decimal("0")) + e.amount
    item = w.db.query(PayslipItem).filter_by(organization_id=w.org).one()
    line = filing.payload["workers"][0]["employmentLines"][0]
    assert (line["employmentLine"], line["jointCommittee"], line["contractType"]) == ("MAIN", "200", "INDEFINITE")
    assert Decimal(line["employeeContribution"]) == ledger["ONSS_EMPLOYEE"]
    assert Decimal(line["bases"]["ONSS_EMPLOYEE_BASE"]) == ledger["ONSS_EMPLOYEE_BASE"]
    employer = Decimal(item.be_calculation_snapshot["be_employer_total"])
    assert Decimal(line["employerContributions"]) == employer and line["coding"] == "PENDING_CONTENT"
    quarter = [o for o in obligations if o.obligation_type == "ONSS_QUARTER"][0]
    assert quarter.amount_due == ledger["ONSS_EMPLOYEE"] + employer
    assert filing.payload["employer"]["enterpriseNumber"] == "0999999999"


def test_no_committed_payroll_no_dmfa(world):
    w = world
    _run(w)                                                    # generated, never approved: nothing in the ledger
    with pytest.raises(HTTPException, match="BE_NO_COMMITTED_PAYROLL"):
        _bf().build_be_dmfa(w.db, w.org, "2026Q1", None, w.a)
    with pytest.raises(BadRequestException, match="YYYYQn"):
        _bf().build_be_dmfa(w.db, w.org, "2026-03", None, w.a)


def test_the_2026_q3_deadline_comes_from_a_calendar_row_never_a_formula(world):
    bf = _bf()
    w = world
    assert bf.due_on(w.db, "DMFA", "2026Q3") == (None, bf.UNSOURCED)            # no "31 October" assumption
    _calendar(w, "BE_DMFA", "2026Q3", date(2026, 10, 30), status="Draft")
    _calendar(w, "BE_DMFA", "2026Q3", date(2026, 10, 30), sourced=False)
    assert bf.due_on(w.db, "DMFA", "2026Q3") == (None, bf.UNSOURCED)            # Draft / unsourced never count
    _calendar(w, "BE_DMFA", "2026Q3", date(2026, 10, 30))
    assert bf.due_on(w.db, "DMFA", "2026Q3") == (date(2026, 10, 30), None)
    assert bf.due_on(w.db, "ONSS_QUARTER", "2026Q3")[0] == date(2026, 10, 30)
    view = bf.calendar_view(w.db, 2026)
    assert [r["used"] for r in view] == [False, False, True]


def test_the_dmfa_due_date_and_overdue_obligations(world):
    bf = _bf()
    w = world
    _calendar(w, "BE_DMFA", "2026Q1", date(2026, 4, 30))
    filing, obligations = _dmfa(w)
    assert filing.due_on == date(2026, 4, 30) and obligations[0].due_on == date(2026, 4, 30)
    overdue = [x for x in bf.exception_queue(w.db, w.org, today="2026-05-01") if x["category"] == "OVERDUE_OBLIGATION"]
    assert [x["obligationId"] for x in overdue] == [obligations[0].id]


# ── acceptance vs settlement (BE-036), advances (BE-018) ───────────────────
def test_accepted_but_unpaid_stays_open_until_paid_and_reconciled(world):
    bf = _bf()
    w = world
    filing, obligations = _dmfa(w)
    quarter = obligations[0]
    accept(w.db, w.org, filing, w.b, w.a, "Q1")
    assert filing.status == "ACCEPTED" and quarter.acceptance_status == "ACCEPTED"
    assert quarter.status == "DUE" and bf.obligation_view(quarter)["open"]           # accepted, unpaid: open
    half = (quarter.amount_due / 2).quantize(Decimal("0.01"))
    bf.record_be_obligation_payment(w.db, w.org, quarter.id, {"amount": str(half), "reference": "BANK-1"}, w.a)
    assert quarter.status == "PART_PAID" and filing.status == "ACCEPTED"
    assert bf.record_be_obligation_payment(w.db, w.org, quarter.id, {"amount": str(half), "reference": "BANK-1"},
                                           w.a) is quarter                                     # idempotent
    with pytest.raises(HTTPException, match="REFERENCE_REUSED"):
        bf.record_be_obligation_payment(w.db, w.org, quarter.id, {"amount": "1", "reference": "BANK-1"}, w.a)
    bf.record_be_obligation_payment(w.db, w.org, quarter.id,
                                    {"amount": str(quarter.amount_due - half), "reference": "BANK-2"}, w.a)
    assert quarter.status == "PAID" and filing.status == "SETTLED"
    w.db.commit()                                         # the routes commit; a refused four-eyes attempt rolls back
    with pytest.raises(BadRequestException):
        bf.reconcile_be_obligation(w.db, w.org, quarter.id, w.a)                       # four-eyes
    bf.reconcile_be_obligation(w.db, w.org, quarter.id, w.b)
    assert quarter.status == "RECONCILED" and quarter.reconciled_by_id == w.b


def test_onss_advances_are_separate_obligations_and_reduce_the_quarter_balance(world):
    bf = _bf()
    w = world
    advance = bf.record_be_onss_advance(w.db, w.org, {"month": "2026-02", "amount": "10", "noticeRef": "N-1"}, w.a)
    assert bf.record_be_onss_advance(w.db, w.org, {"month": "2026-02", "amount": "10", "noticeRef": "N-1"},
                                     w.a) is advance
    with pytest.raises(HTTPException, match="BE_ADVANCE_EXISTS"):
        bf.record_be_onss_advance(w.db, w.org, {"month": "2026-02", "amount": "11", "noticeRef": "N-2"}, w.a)
    with pytest.raises(BadRequestException, match="noticeRef"):
        bf.record_be_onss_advance(w.db, w.org, {"month": "2026-03", "amount": "10"}, w.a)
    _filing, obligations = _dmfa(w)
    quarter = [o for o in obligations if o.obligation_type == "ONSS_QUARTER"][0]
    assert advance.obligation_type == "ONSS_ADVANCE" and advance.id != quarter.id
    total = Decimal(quarter.components["total"])
    assert quarter.components["advances"] == "10.00" and quarter.amount_due == total - Decimal("10")


def test_overpayment_and_a_change_after_payment_raise_variances(world):
    bf = _bf()
    w = world
    filing, obligations = _dmfa(w)
    quarter = obligations[0]
    bf.record_be_obligation_payment(w.db, w.org, quarter.id,
                                    {"amount": str(quarter.amount_due + 1), "reference": "BANK-9"}, w.a)
    assert quarter.status == "OVERPAID"
    variances = bf.list_be_variances(w.db, w.org)
    assert [v["kind"] for v in variances] == ["OVERPAID"] and variances[0]["difference"] == "1.00"
    with pytest.raises(HTTPException, match="FOUR_EYES"):
        bf.resolve_be_variance(w.db, w.org, variances[0]["id"], "refund asked", w.a)
    bf.resolve_be_variance(w.db, w.org, variances[0]["id"], "TEST ONLY refund asked", w.b)
    assert bf.list_be_variances(w.db, w.org)[0]["status"] == "RESOLVED"


# ── correction after an accepted quarter ───────────────────────────────────
def test_a_correction_of_an_accepted_quarter_is_a_linked_dmfa_correction(world):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import PayrollRun, PayslipItem
    from tests.test_belgium_run_lifecycle import _acknowledge_all, _advance

    bf = _bf()
    w = world
    filing, obligations = _dmfa(w)
    accept(w.db, w.org, filing, w.b, w.a, "Q1")
    receipt, sent = filing.receipt_ref, json.dumps(filing.payload, sort_keys=True)
    quarter = obligations[0]
    bf.record_be_obligation_payment(w.db, w.org, quarter.id, {"amount": str(quarter.amount_due), "reference": "B1"},
                                    w.a)
    paid = quarter.amount_due
    original = w.db.query(PayslipItem).filter_by(organization_id=w.org).one()
    out = be.create_be_correction(w.db, w.org, original.id, {
        "reason": "TEST ONLY late raise", "evidenceRef": "TEST ONLY letter", "payDate": "2026-04-30",
        "inputDelta": {"gross": "1100", "basic": "1100"}}, w.a)
    w.db.commit()
    correction_run = w.db.get(PayrollRun, out["runId"])
    _acknowledge_all(w, correction_run)
    _advance(w, correction_run, w.b)
    assert Decimal(w.db.get(PayslipItem, out["payslipItemId"]).be_calculation_snapshot["employerTotalDelta"]) > 0
    fix, fix_obligations = bf.build_be_dmfa(w.db, w.org, "2026Q1", None, w.a)          # same quarter (source period)
    w.db.commit()
    assert (fix.kind, fix.corrects_id, fix.period_key) == ("CORRECTION", filing.id, "2026Q1")
    assert filing.status == "SETTLED" and filing.receipt_ref == receipt                # receipt immutable
    assert json.dumps(filing.payload, sort_keys=True) == sent
    assert fix_obligations[0].id == quarter.id and quarter.amount_due > paid
    assert quarter.status == "PART_PAID" and quarter.filing_id == fix.id
    assert [v["kind"] for v in bf.list_be_variances(w.db, w.org)] == ["CHANGED_AFTER_PAYMENT"]
    # the Q2 DmfA does not double-count the correction
    with pytest.raises(HTTPException, match="BE_NO_COMMITTED_PAYROLL"):
        bf.build_be_dmfa(w.db, w.org, "2026Q2", None, w.a)
    accept(w.db, w.org, fix, w.b, w.a, "Q1FIX")
    assert quarter.acceptance_status == "ACCEPTED"


# ── withholding (FinProf) and Belcotax 281.10 (BE-014) ─────────────────────
def _registration(w):
    from app.modules.payroll.models import PayrollBeEmployerRegistration

    return w.db.query(PayrollBeEmployerRegistration).filter_by(organization_id=w.org, status="ACTIVE").one()


def test_the_withholding_object_follows_the_declared_frequency(world):
    from app.modules.payroll.models import PayrollBeAccumulatorEntry

    bf = _bf()
    w = world
    _approve(w, _run(w))
    with pytest.raises(HTTPException, match="BE_WHT_FREQUENCY_UNKNOWN"):
        bf.build_be_withholding(w.db, w.org, "2026-03", None, w.a)
    _registration(w).withholding_declaration_frequency = "MONTHLY"
    w.db.commit()
    with pytest.raises(HTTPException, match="BE_WHT_PERIOD_MISMATCH"):
        bf.build_be_withholding(w.db, w.org, "2026Q1", None, w.a)
    filing, obligations = bf.build_be_withholding(w.db, w.org, "2026-03", None, w.a)
    withheld = sum((e.amount for e in w.db.query(PayrollBeAccumulatorEntry).filter_by(accumulator="WITHHOLDING")),
                   Decimal("0"))
    assert (filing.form_code, filing.authority, filing.period_key) == ("FINPROF", "SPF_FINANCE", "2026-03")
    assert Decimal(filing.payload["totalWithheld"]) == withheld == obligations[0].amount_due
    assert obligations[0].obligation_type == "WITHHOLDING"


def test_belcotax_fiche_employee_copy_correction_and_cancellation(world):
    from app.modules.payroll.models import PayrollBeAccumulatorEntry

    bf = _bf()
    w = world
    _approve(w, _run(w))
    with pytest.raises(HTTPException, match="BE_INCOME_YEAR_OPEN"):
        bf.build_be_belcotax(w.db, w.org, 2026, None, w.a, today=date(2026, 12, 31))
    fiches = bf.build_be_belcotax(w.db, w.org, 2026, None, w.a, today=date(2027, 1, 15))
    w.db.commit()
    assert len(fiches) == 1 and fiches[0].subject_key == f"E{w.employee.id}" and fiches[0].payload["fiche"] == "281.10"
    copy = bf.employee_copy(w.db, w.org, fiches[0].id)
    assert "withholding.regular" in copy["rendition"]
    with pytest.raises(HTTPException, match="BE_FILING_NOT_SENT"):
        bf.cancel_be_belcotax(w.db, w.org, fiches[0].id, "TEST ONLY", w.a)
    accept(w.db, w.org, fiches[0], w.b, w.a, "BCT")
    entry = w.db.query(PayrollBeAccumulatorEntry).filter_by(accumulator="WITHHOLDING").first()
    entry.amount = entry.amount + 1                           # TEST ONLY: the ledger changed after the fiche
    w.db.commit()
    fix = bf.build_be_belcotax(w.db, w.org, 2026, None, w.a, today=date(2027, 1, 15))[0]
    assert (fix.kind, fix.corrects_id) == ("CORRECTION", fiches[0].id)
    cancel = bf.cancel_be_belcotax(w.db, w.org, fiches[0].id, "TEST ONLY wrong employer", w.a)
    assert (cancel.kind, cancel.corrects_id, cancel.payload["cancelled"]) == ("CANCELLATION", fiches[0].id, True)


def test_the_new_schema_keys_are_catalogued_and_pending_by_default():
    from app.modules.payroll import belgium_filing as bf
    from app.modules.payroll.engine.countries import belgium_content as c

    for form, key in bf.SCHEMA_KEYS.items():
        assert c.KEYS[key][:2] == ("filing", c.KIND_VERSION), key
        assert c.SLAB_SPECS[key]["fields"] == ("name", "effectiveFrom")
    assert bf.RENDERERS == {}                                  # no official mapping is supplied (G-08)
    assert isinstance(bf.adapter_for("ONSS"), bf.UncertifiedAdapter)
