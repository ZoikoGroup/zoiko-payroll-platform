"""Malaysia filings, settlements, reconciliation and journal (ZP-MY-ENG-001
Phase 9; MY-021 / MY-022 / MY-028; decision D-5). Amounts are the TEST pack's
(tests/_my_engine_helpers.py) with a stand-in PCB of 100.00 — never certifying."""
import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from tests.test_malaysia_service import (NRIC, PAY_DATE, _registration, _run_with_payslip, _setup, signed_pack,
                                         with_pcb, world)  # noqa: F401  (pytest fixtures)

ARCHIVED = {"1.0": {"effective_from": "2026-01-01", "effective_to": None, "evidence": "test archive"}}
ACCOUNTS = {"salary_expense": "5010", "employer_epf_expense": "5020", "employer_socso_eis_expense": "5021",
            "hrd_levy_expense": "5022", "pcb_payable": "2250", "epf_payable": "2260", "perkeso_payable": "2261",
            "hrd_payable": "2262", "other_deductions_payable": "2299", "net_pay_payable": "2310"}


def _paid(w):
    """A PAID run: the TEST payslip, NRIC in the vault, approved fingerprint."""
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.models import PayrollStatus

    _setup(w)
    my.create_my_identifier(w.db, w.org, "NRIC", NRIC, w.a, employee_id=w.employee.id)
    w.db.commit()
    run, item = _run_with_payslip(w)
    item.net_pay = Decimal(item.my_calculation_snapshot["my_net"])
    run.my_approval_fingerprint = my.my_approval_fingerprint(w.db, run)
    my.before_run_transition(w.db, run, PayrollStatus.PAID, w.b)
    run.status = PayrollStatus.PAID
    w.db.commit()
    return run, item


def _filings(w):
    from app.modules.payroll.models import PayrollMyFiling

    return {f.form_code: f for f in w.db.query(PayrollMyFiling).filter_by(organization_id=w.org, kind="ORIGINAL")}


def _archive(monkeypatch, forms=("PCB_MONTHLY", "EPF_MONTHLY", "PERKESO_EIS_MONTHLY", "HRD_MONTHLY", "EA", "FORM_E",
                                 "CP8D", "CP22A")):
    from app.modules.payroll.engine.countries import malaysia_content as content

    catalog = {k: {**v, "versions": dict(ARCHIVED) if k in forms else {}}
               for k, v in content.MY_FORM_SCHEMA_CATALOG.items()}
    monkeypatch.setattr(content, "MY_FORM_SCHEMA_CATALOG", catalog)


# ── generation at PAID ─────────────────────────────────────────────────────
def test_paid_builds_the_four_monthly_payloads_with_masked_identifiers(world, with_pcb):
    w = world
    run, item = _paid(w)
    filings = _filings(w)
    assert set(filings) == {"PCB_MONTHLY", "EPF_MONTHLY", "PERKESO_EIS_MONTHLY", "HRD_MONTHLY"}
    assert {f.authority for f in filings.values()} == {"HASIL", "EPF", "PERKESO", "HRD"}
    pcb, epf, perkeso, hrd = (filings[k].payload for k in ("PCB_MONTHLY", "EPF_MONTHLY", "PERKESO_EIS_MONTHLY",
                                                            "HRD_MONTHLY"))
    assert pcb["total"] == "100.00" and pcb["employees"][0]["nricMasked"]
    assert (epf["employeeTotal"], epf["employerTotal"]) == ("550.00", "650.00")
    assert epf["members"][0]["wage"] == "5000.00" and epf["members"][0]["payslipItemIds"] == [item.id]
    assert perkeso["socso"] == {"employee": "24.75", "employer": "86.65"}
    assert perkeso["eis"] == {"employee": "9.90", "employer": "9.90"}
    assert (hrd["levy"], hrd["levyBase"]) == ("50.00", "5000.00")
    for f in filings.values():
        assert f.status == "DRAFT" and f.run_ids == [run.id] and f.schema_version is None
        assert NRIC not in json.dumps(f.payload) and f.payload["dueRule"] == "NOMINAL_DAY_NO_HOLIDAY_SHIFT"
    assert filings["PCB_MONTHLY"].due_on is None                               # no signed pack in force


def test_rebuilding_the_same_month_is_idempotent(world, with_pcb):
    from app.modules.payroll import malaysia_filing as myf
    from app.modules.payroll.models import PayrollMyFiling

    w = world
    run, _item = _paid(w)
    before = {f.id: f.payload_hash for f in w.db.query(PayrollMyFiling)}
    rows = myf.build_my_run_filings(w.db, run, w.a)
    assert {r.id: r.payload_hash for r in rows} == before


def test_pcb_due_date_comes_from_the_signed_remittance_day(world, with_pcb, signed_pack):
    w = world
    _paid(w)
    filings = _filings(w)
    assert filings["PCB_MONTHLY"].due_on == date(2026, 4, 15)                  # signed day 15 of the next month
    assert filings["EPF_MONTHLY"].due_on is None                               # EPF due rule is PENDING_G1


# ── approval, submission, response, correction ────────────────────────────
def test_approval_is_refused_until_the_authority_layout_is_archived(world, with_pcb, monkeypatch):
    from app.modules.payroll import malaysia_filing as myf

    w = world
    _paid(w)
    pcb = _filings(w)["PCB_MONTHLY"]
    with pytest.raises(HTTPException) as raised:
        myf.approve_my_filing(w.db, w.org, pcb.id, w.a)
    assert raised.value.status_code == 409 and "FILING_SCHEMA_MISMATCH" in raised.value.detail
    _archive(monkeypatch)
    pcb.created_by_id = w.a
    w.db.commit()
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        myf.approve_my_filing(w.db, w.org, pcb.id, w.a)
    w.db.rollback()
    approved = myf.approve_my_filing(w.db, w.org, pcb.id, w.b)
    assert (approved.status, approved.schema_version) == ("APPROVED", "1.0")
    submitted = myf.record_my_filing_submission(w.db, w.org, pcb.id, "e-PCB-123", w.a)
    assert myf.record_my_filing_submission(w.db, w.org, pcb.id, "e-PCB-123", w.a) is submitted     # idempotent
    with pytest.raises(HTTPException, match="already submitted"):
        myf.record_my_filing_submission(w.db, w.org, pcb.id, "other", w.a)
    with pytest.raises(BadRequestException, match="receiptRef"):
        myf.record_my_filing_response(w.db, w.org, pcb.id, {"outcome": "ACCEPTED"}, w.a)
    accepted = myf.record_my_filing_response(w.db, w.org, pcb.id, {"outcome": "ACCEPTED", "receiptRef": "R-9"}, w.a)
    assert accepted.status == "ACCEPTED"
    changed = {**pcb.payload, "total": "101.00"}
    correction = myf.upsert_filing(w.db, w.org, pcb.legal_entity_id, "PCB_MONTHLY", pcb.period_key, changed,
                                   pcb.run_ids, None, w.a)
    assert (correction.kind, correction.corrects_id, correction.payload["correction"]) == ("CORRECTION", pcb.id, True)


# ── settlements and reconciliation ─────────────────────────────────────────
def test_paid_builds_one_liability_per_authority(world, with_pcb):
    from app.modules.payroll import malaysia_settlement as mss

    w = world
    _paid(w)
    rows = {r["liabilityType"]: r for r in mss.list_my_settlements(w.db, w.org)}
    assert {k: v["amountDue"] for k, v in rows.items()} == {"PCB": "100.00", "EPF": "1200.00",
                                                             "PERKESO": "131.20", "HRD": "50.00"}
    assert rows["PERKESO"]["components"] == {"eisEmployee": "9.90", "eisEmployer": "9.90", "socsoEmployee": "24.75",
                                             "socsoEmployer": "86.65"}
    assert all(r["status"] == "DUE" for r in rows.values())


def test_payments_are_idempotent_and_variances_need_a_second_person(world, with_pcb):
    from app.modules.payroll import malaysia_settlement as mss

    w = world
    _paid(w)
    epf = next(r for r in mss.list_my_settlements(w.db, w.org) if r["liabilityType"] == "EPF")
    mss.record_my_settlement_payment(w.db, w.org, epf["id"], {"paymentRef": "P-1", "amount": "1000",
                                                               "paidOn": "2026-04-10"}, w.a)
    again = mss.record_my_settlement_payment(w.db, w.org, epf["id"], {"paymentRef": "P-1", "amount": "1000",
                                                                       "paidOn": "2026-04-10"}, w.a)
    assert str(again.paid_amount) in ("1000", "1000.00") and again.status == "PART_PAID"
    with pytest.raises(HTTPException, match="already recorded"):
        mss.record_my_settlement_payment(w.db, w.org, epf["id"], {"paymentRef": "P-1", "amount": "5",
                                                                   "paidOn": "2026-04-10"}, w.a)
    out = mss.reconcile_my_settlement(w.db, w.org, epf["id"], w.a)
    assert out["variance"]["kind"] == "UNDERPAID" and out["variance"]["difference"] == "-200.00"
    w.db.commit()
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        mss.resolve_my_variance(w.db, w.org, out["variance"]["id"], "short-paid, topped up next month", w.a)
    w.db.rollback()
    resolved = mss.resolve_my_variance(w.db, w.org, out["variance"]["id"], "short-paid, topped up next month", w.b)
    assert resolved.status == "RESOLVED"
    hrd = next(r for r in mss.list_my_settlements(w.db, w.org) if r["liabilityType"] == "HRD")
    mss.record_my_settlement_payment(w.db, w.org, hrd["id"], {"paymentRef": "H-1", "amount": "50",
                                                               "paidOn": "2026-04-10"}, w.a)
    assert mss.reconcile_my_settlement(w.db, w.org, hrd["id"], w.a)["settlement"]["status"] == "RECONCILED"


# ── journal ────────────────────────────────────────────────────────────────
def test_journal_is_blocked_without_an_account_map_and_balanced_with_one(world, with_pcb):
    from app.modules.payroll import malaysia_journal as myj
    from app.modules.payroll import malaysia_service as my

    w = world
    run, _item = _paid(w)
    blocked = myj.build_my_journal(w.db, w.org, run.id)
    assert blocked["status"] == "BLOCKED" and "no account code" in blocked["reason"]
    with pytest.raises(BadRequestException, match="unknown journal account"):
        my.record_my_employer_registration(w.db, w.org, {
            "effective_from": "2026-03-01", "legal_name": "X", "hasil_employer_no": "E1",
            "hrd_category": "NOT_REGISTERED", "my_journal_accounts": {"zus_payable": "1"}}, w.a, "accounts")
    registration = w.db.query(my._models().PayrollMyEmployerRegistration).filter_by(status="ACTIVE").one()
    registration.my_journal_accounts = ACCOUNTS
    w.db.commit()
    journal = myj.build_my_journal(w.db, w.org, run.id)
    assert journal["status"] == "READY" and journal["debit"] == journal["credit"]
    lines = {line["memo"]: line["amount"] for line in journal["lines"]}
    assert lines["Salaries and wages (gross)"] == "5000.00" and lines["HRD levy payable"] == "50.00"
    assert lines["Net pay payable (incl. any held under tax clearance)"] == "4315.35"


# ── annual and event forms ─────────────────────────────────────────────────
def test_annual_forms_need_a_closed_year_and_a_matching_ledger(world, with_pcb):
    from app.modules.payroll import malaysia_filing as myf
    from app.modules.payroll.models import PayrollMyAccumulatorEntry

    w = world
    _paid(w)
    with pytest.raises(HTTPException, match="MY_TAX_YEAR_OPEN"):
        myf.build_my_annual_filings(w.db, w.org, 2026, None, w.a, today=date(2026, 12, 31))
    rows = myf.build_my_annual_filings(w.db, w.org, 2026, None, w.a, today=date(2027, 1, 5))
    forms = {r.form_code: r for r in rows}
    assert set(forms) == {"EA", "FORM_E", "CP8D"}
    ea = forms["EA"].payload
    assert (ea["pcb"], ea["epfEmployee"], ea["grossRemuneration"]) == ("100.00", "550.00", "5000.00")
    assert forms["CP8D"].payload["employees"][0]["nricMasked"] and NRIC not in json.dumps(ea)
    entry = w.db.query(PayrollMyAccumulatorEntry).filter_by(accumulator="PCB_PAID").one()
    entry.amount = Decimal("99")
    w.db.commit()
    with pytest.raises(HTTPException, match="MY_LEDGER_MISMATCH"):
        myf.build_my_annual_filings(w.db, w.org, 2026, None, w.a, today=date(2027, 1, 5))
    with pytest.raises(HTTPException, match="MY_FORM_OUT_OF_SCOPE"):
        myf.refuse_out_of_scope("ec")


def test_event_forms_come_from_recorded_employer_events(world, signed_pack):
    from app.modules.payroll import malaysia_filing as myf
    from app.modules.payroll import malaysia_service as my

    w = world
    event = my.record_my_employer_event(w.db, w.org, w.employee.id, {
        "event_type": "CP22A", "event_date": "2026-06-30", "clearance_required": True}, w.a, "resigned")
    row = myf.build_my_event_filing(w.db, w.org, event.id, w.a)
    assert (row.form_code, row.authority, row.due_on, row.subject_key) == ("CP22A", "HASIL", date(2026, 5, 31),
                                                                           f"EV{event.id}")
    assert row.payload["clearanceRequired"] is True
    assert myf.build_my_event_filing(w.db, w.org, event.id, w.a).id == row.id       # idempotent
    death = my.record_my_employer_event(w.db, w.org, w.employee.id, {
        "event_type": "DEATH_NOTICE", "event_date": "2026-04-01"}, w.a, "notice")
    with pytest.raises(HTTPException, match="MY_FORM_OUT_OF_SCOPE"):
        myf.build_my_event_filing(w.db, w.org, death.id, w.a)


def test_routes_are_declared():
    from app.modules.payroll.my_org_router import router

    paths = {(sorted(r.methods)[0], r.path) for r in router.routes}
    for method, path in (("GET", "/malaysia/filings"), ("POST", "/malaysia/filings/annual"),
                         ("POST", "/malaysia/filings/{filing_id}/approve"),
                         ("POST", "/malaysia/employer-events/{row_id}/filing"),
                         ("POST", "/malaysia/settlements/{settlement_id}/payments"),
                         ("POST", "/malaysia/variances/{variance_id}/resolve"),
                         ("GET", "/malaysia/runs/{run_id}/journal")):
        assert (method, path) in paths, (method, path)
