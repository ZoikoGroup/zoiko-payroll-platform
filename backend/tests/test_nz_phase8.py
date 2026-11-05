"""New Zealand payday filing, remittance, settlements, run exceptions and the
journal (ZP-NZ-ENG-001 Phase 8; SQLite; NZ-018, NZ-019, D-P8-1..4).

Runs and payslips are built directly with frozen snapshots shaped like the
engine's nz_result (the P3 worked example: fortnightly M SL 3,000 gross)."""
import json
import re
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.exceptions import BadRequestException
from app.modules.payroll import new_zealand_service as nzs
from app.modules.payroll import nz_filing as fil
from app.modules.payroll import nz_journal as jnl
from app.modules.payroll import nz_lifecycle as life
from app.modules.payroll import nz_remittance as rem
from app.modules.payroll.models import (
    PayrollNzCorrection, PayrollNzFiling, PayrollNzRemittance, PayrollNzRemittanceLine, PayrollNzRunException,
    PayrollRun, PayrollStatus, PayslipItem,
)
from tests._nz_p6_fixtures import _request_codes, employ, employer_profile, make_employee, signed  # noqa: F401

D = Decimal
PAYDAY = date(2026, 10, 9)                                    # a Friday
IRD = "49091850"
OBLIGATIONS = {"payeTotal": "653.29", "studentLoan": "248.64", "ksEmployee": "105.00", "ksEmployerGross": "105.00",
               "ksEmployerNet": "73.50", "esct": "31.50", "childSupport": "797.22"}
ACCOUNTS = {k: f"6{n:03d}" for n, k in enumerate(jnl.ACCOUNT_KEYS)}


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(settings, "NZ_IRD_KEYRING", json.dumps({"1": "a" * 32}))
    monkeypatch.setattr(settings, "NZ_IRD_FINGERPRINT_KEY", "f" * 32)


@pytest.fixture()
def world(db, organization, signed):
    employee = make_employee(db, organization)
    employ(db, organization, employee)
    profile = employer_profile(db, organization)
    return organization, employee, profile


def snapshot(scale=1, exceptions=(), result_hash="h1", destination="INLAND_REVENUE", fund=None):
    obligations = {k: str(D(v) * scale) for k, v in OBLIGATIONS.items()}
    return {"taxCode": "M SL", "obligations": obligations, "netPay": str(D("1195.85") * scale),
            "employeeTotal": str(D("1150.86") * scale), "accumulatorDeltas": {"PAYE_GROSS": str(3000 * scale)},
            "kiwisaver": {"destination": destination, "complyingFundRef": fund},
            "childSupport": {"variationCode": None}, "exceptions": list(exceptions),
            "hashes": {"resultHash": result_hash}}


def make_run(db, organization, employee, pay_date=PAYDAY, kind="REGULAR", snap=None, status=PayrollStatus.REVIEW):
    run = PayrollRun(organization_id=organization.id, period_label=f"NZ {pay_date}", period_start=date(2026, 9, 26),
                     period_end=pay_date, pay_date=pay_date, status=status, nz_payment_kind=kind)
    db.add(run)
    db.flush()
    snap = snap or snapshot()
    item = PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="NZ", net_pay=D(snap["netPay"]),
                       nz_calculation_snapshot=snap)
    db.add(item)
    db.commit()
    return run, item


def paid(db, run):
    run.status = PayrollStatus.PAID
    rem.post_run(db, run, 1)
    out = fil.build_filings(db, run, 1)
    db.commit()
    return out


def _conflict_code(exc):
    return re.search(r"\((NZ_[A-Z_]+)\)", exc.value.detail).group(1)


# ── filing deadline (D-P8-2) ────────────────────────────────────────────────
def test_working_days_skip_weekends_holidays_and_the_christmas_period():
    rule = fil.WORKING_DAY_RULE
    assert fil.nz_working_days_after(date(2026, 10, 9), 2, set(), rule) == date(2026, 10, 13)
    assert fil.nz_working_days_after(date(2026, 10, 23), 2, {date(2026, 10, 26)}, rule) == date(2026, 10, 28)
    assert fil.nz_working_days_after(date(2026, 12, 24), 2, set(), rule) == date(2027, 1, 19)
    with pytest.raises(ValueError):
        fil.nz_working_days_after(date(2026, 10, 9), 2, set(), "CALENDAR")


def test_filing_due_on_electronic_paper_and_unsigned(db, signed):
    rate_map, _slabs = signed
    assert fil.filing_due_on(db, PAYDAY, "PAYDAY_GATEWAY") == date(2026, 10, 13)
    assert fil.filing_due_on(db, PAYDAY, "PAPER") == date(2026, 10, 23)
    assert fil.filing_due_on(db, date(2026, 12, 24), "MYIR_FILE_UPLOAD") == date(2027, 1, 19)
    rate_map["nz_working_day_rule"].label += " [PENDING G1]"
    assert fil.filing_due_on(db, PAYDAY, "PAYDAY_GATEWAY") is None


# ── remittance periods and due dates ────────────────────────────────────────
def test_remittance_periods_and_due_dates(signed):
    rate_map, _slabs = signed
    assert rem.period_for(date(2026, 10, 15), "TWICE_MONTHLY") == (date(2026, 10, 1), date(2026, 10, 15))
    assert rem.period_for(date(2026, 10, 16), "TWICE_MONTHLY") == (date(2026, 10, 16), date(2026, 10, 31))
    assert rem.period_for(PAYDAY, "MONTHLY") == (date(2026, 10, 1), date(2026, 10, 31))
    due = rem.remittance_due_on
    assert due(rate_map, date(2026, 10, 1), date(2026, 10, 31), "MONTHLY") == date(2026, 11, 20)
    assert due(rate_map, date(2026, 12, 1), date(2026, 12, 31), "MONTHLY") == date(2027, 1, 20)
    assert due(rate_map, date(2026, 10, 1), date(2026, 10, 15), "TWICE_MONTHLY") == date(2026, 10, 20)
    assert due(rate_map, date(2026, 10, 16), date(2026, 10, 31), "TWICE_MONTHLY") == date(2026, 11, 5)
    assert due(rate_map, date(2026, 12, 16), date(2026, 12, 31), "TWICE_MONTHLY") == date(2027, 1, 15)
    rate_map["nz_remit_monthly_due_day"].label += " [PENDING G1]"
    assert due(rate_map, date(2026, 10, 1), date(2026, 10, 31), "MONTHLY") is None


def test_remittance_class_mismatch_and_preflight(db, world):
    organization, employee, profile = world
    assert rem.class_mismatch(db, profile, PAYDAY) is None
    profile.annual_paye_esct_basis, profile.annual_paye_esct_amount = "PRIOR_YEAR", D("600000")
    db.commit()
    assert "TWICE_MONTHLY" in rem.class_mismatch(db, profile, PAYDAY)
    run, _item = make_run(db, organization, employee)
    assert "NZ_REMITTANCE_CLASS_MISMATCH" in {p["code"] for p in nzs.nz_run_preflight(db, run)}


# ── remittance lines at PAID ────────────────────────────────────────────────
def test_paid_posts_one_line_per_obligation_once(db, world):
    organization, employee, _profile = world
    run, item = make_run(db, organization, employee)
    assert rem.post_run(db, run, 1) == 6
    assert rem.post_run(db, run, 1) == 0                                 # idempotent
    db.commit()
    rows = {r.obligation: r for r in db.query(PayrollNzRemittance)}
    assert set(rows) == {"PAYE", "STUDENT_LOAN", "KS_EMPLOYEE", "KS_EMPLOYER_NET", "ESCT", "CHILD_SUPPORT"}
    assert rows["PAYE"].amount == D("653.29") and rows["PAYE"].due_on == date(2026, 11, 20)
    assert (rows["PAYE"].period_start, rows["PAYE"].status) == (date(2026, 10, 1), "OPEN")
    assert db.query(PayrollNzRemittanceLine).count() == 6


def test_complying_fund_kiwisaver_has_its_own_destination(db, world):
    organization, employee, _profile = world
    run, _item = make_run(db, organization, employee, snap=snapshot(destination="COMPLYING_FUND", fund="FUND-7"))
    rem.post_run(db, run, 1)
    ks = {(r.obligation, r.destination, r.fund_ref) for r in db.query(PayrollNzRemittance)
          if r.obligation.startswith("KS_")}
    assert ks == {("KS_EMPLOYEE", "COMPLYING_FUND", "FUND-7"), ("KS_EMPLOYER_NET", "COMPLYING_FUND", "FUND-7")}


def test_settlement_match_is_four_eyes_and_only_matched_money_pays(db, world):
    organization, employee, _profile = world
    run, _item = make_run(db, organization, employee)
    rem.post_run(db, run, 1)
    db.commit()
    paye = db.query(PayrollNzRemittance).filter(PayrollNzRemittance.obligation == "PAYE").one()
    with pytest.raises(BadRequestException, match="reason"):
        rem.record_settlement(db, organization.id, paye.id, {"amount": "1", "payment_reference": "R"}, 1)
    with pytest.raises(BadRequestException, match="reference"):
        rem.record_settlement(db, organization.id, paye.id, {"amount": "100", "paid_on": "2026-11-18", "reason": "x"}, 1)
    first = rem.record_settlement(db, organization.id, paye.id, {"amount": "600", "paid_on": "2026-11-18",
                                                                 "payment_reference": "IR-1", "reason": "PAYE paid"}, 1)
    db.commit()
    assert paye.status == "OPEN"                                         # recorded is not paid
    with pytest.raises(BadRequestException, match="four-eyes"):
        rem.match_settlement(db, organization.id, first.id, 1)
    rem.match_settlement(db, organization.id, first.id, 2)
    assert (paye.status, paye.settled) == ("PART_PAID", D("600"))
    second = rem.record_settlement(db, organization.id, paye.id, {"amount": "53.29", "paid_on": "2026-11-19",
                                                                  "payment_reference": "IR-2", "reason": "balance"}, 1)
    db.commit()
    rem.match_settlement(db, organization.id, second.id, 2)
    assert paye.status == "PAID"
    with pytest.raises(BadRequestException, match="reason"):
        rem.reverse_settlement(db, organization.id, second.id, 2, " ")
    rem.reverse_settlement(db, organization.id, second.id, 2, "bank recall")
    assert (paye.status, paye.settled) == ("PART_PAID", D("600"))
    view = rem.get_remittance(db, organization.id, paye.id)
    assert [s["status"] for s in view["settlements"]] == ["MATCHED", "REVERSED"] and len(view["lines"]) == 1


# ── payday filing records (NZ-018) ──────────────────────────────────────────
def test_two_runs_on_one_payday_make_one_employment_information(db, world):
    organization, employee, _profile = world
    first, _ = make_run(db, organization, employee)
    [ei] = paid(db, first)
    assert (ei.filing_type, ei.kind, ei.version, ei.status) == (fil.EI, "ORIGINAL", 1, "DRAFT")
    assert ei.due_on == date(2026, 10, 13) and ei.channel == "PAYDAY_GATEWAY"
    second, _ = make_run(db, organization, employee, kind="OUT_OF_CYCLE", snap=snapshot(scale=D("0.5")))
    [again] = paid(db, second)
    assert again.id == ei.id and again.run_ids == sorted([first.id, second.id])      # DRAFT regenerated in place
    [row] = again.payload["employees"]
    assert row["payeIncludingAcc"] == "979.935" and len(row["payslipItemIds"]) == 2
    assert db.query(PayrollNzFiling).count() == 1
    assert fil.build_filings(db, second, 1)[0].id == ei.id                           # same hash: nothing happens


def test_approved_filing_change_makes_a_new_version_and_submitted_an_amendment(db, world):
    organization, employee, _profile = world
    first, _ = make_run(db, organization, employee)
    [v1] = paid(db, first)
    with pytest.raises(BadRequestException, match="four-eyes"):
        fil.approve_filing(db, organization.id, v1.id, 1)
    fil.approve_filing(db, organization.id, v1.id, 2)
    db.commit()
    second, _ = make_run(db, organization, employee, kind="OUT_OF_CYCLE", snap=snapshot(scale=D("0.5")))
    [v2] = paid(db, second)
    assert (v1.status, v2.version, v2.status, v2.previous_version_id) == ("SUPERSEDED", 2, "DRAFT", v1.id)
    v2.status = "SUBMITTED"                                               # as a certified exporter would (G3)
    db.commit()
    third, _ = make_run(db, organization, employee, kind="OUT_OF_CYCLE", snap=snapshot(scale=D("0.25")))
    [amendment] = paid(db, third)
    assert (amendment.kind, amendment.amends_id, amendment.status) == ("AMENDMENT", v2.id, "DRAFT")
    assert fil.build_filings(db, third, 1)[0].id == amendment.id                    # no duplicate amendment


def test_employee_details_lists_starters(db, organization, signed):
    employee = make_employee(db, organization)
    employ(db, organization, employee, start=date(2026, 9, 28))
    employer_profile(db, organization)
    run, _ = make_run(db, organization, employee)
    filings = {f.filing_type: f for f in paid(db, run)}
    assert set(filings) == {fil.EI, fil.ED}
    [starter] = filings[fil.ED].payload["starters"]
    assert (starter["employeeId"], starter["startDate"]) == (employee.id, "2026-09-28")
    assert filings[fil.ED].payload["leavers"] == []


def test_filing_payload_carries_no_ird_digits(db, world):
    organization, employee, _profile = world
    nzs.create_nz_ird_number(db, organization.id, "EMPLOYEE", IRD, 1, employee_id=employee.id)
    db.commit()
    run, _ = make_run(db, organization, employee)
    [ei] = paid(db, run)
    [row] = ei.payload["employees"]
    assert row["irdVaultId"] is not None and row["irdMasked"] and not re.search(r"\d", row["irdMasked"])
    text = json.dumps(fil.filing_view(ei, include_payload=True))
    assert IRD not in text and "091850" not in text


def test_submit_is_refused_until_g3_and_a_response_never_pays(db, world):
    organization, employee, _profile = world
    run, _ = make_run(db, organization, employee)
    [ei] = paid(db, run)
    with pytest.raises(BadRequestException, match="APPROVED"):
        fil.submit_filing(db, organization.id, ei.id, 2)
    fil.approve_filing(db, organization.id, ei.id, 2)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        fil.submit_filing(db, organization.id, ei.id, 2)
    assert exc.value.status_code == 409 and _conflict_code(exc) == "NZ_EXPORT_SCHEMA_NOT_CERTIFIED"
    ei.status = "SUBMITTED"
    db.commit()
    with pytest.raises(BadRequestException, match="outcome"):
        fil.record_authority_response(db, organization.id, ei.id, {"outcome": "MAYBE"}, 2)
    fil.record_authority_response(db, organization.id, ei.id, {"outcome": "accepted", "reference": "IR-REF"}, 2)
    assert (ei.status, ei.authority_reference) == ("ACCEPTED", "IR-REF")
    assert {(r.status, r.settled) for r in db.query(PayrollNzRemittance)} == {("OPEN", D("0"))}   # NZ-019


def test_rejection_keeps_error_codes_and_payroll_unchanged(db, world):
    organization, employee, _profile = world
    run, item = make_run(db, organization, employee)
    [ei] = paid(db, run)
    ei.status = "SUBMITTED"
    db.commit()
    before = dict(item.nz_calculation_snapshot)
    fil.record_authority_response(db, organization.id, ei.id, {"outcome": "REJECTED", "errorCodes": ["e101", " "]}, 2)
    assert (ei.status, ei.authority_errors) == ("REJECTED", ["E101"])
    assert item.nz_calculation_snapshot == before and run.status == PayrollStatus.PAID


# ── corrections (D-P8-3) ────────────────────────────────────────────────────
def test_correction_amends_the_original_payday_and_posts_a_late_delta(db, world):
    organization, employee, _profile = world
    run, item = make_run(db, organization, employee)
    [original] = paid(db, run)
    correction = PayrollNzCorrection(organization_id=organization.id, employee_id=employee.id,
                                     original_payslip_item_id=item.id, reason="missed allowance",
                                     input_delta={}, result_delta={}, status="APPLIED", created_by_id=1)
    db.add(correction)
    db.flush()
    delta = {"payeTotal": "30.00", "studentLoan": "12.00"}
    snap = {"paymentKind": "CORRECTION", "correctionOf": item.id, "correctionId": correction.id,
            "deltas": {"gross": "100.00", "obligations": delta}, "netPay": "58.00", "obligations": delta,
            "exceptions": [], "hashes": {"resultHash": "c1"}}
    fix, _ = make_run(db, organization, employee, pay_date=date(2026, 12, 4), kind="CORRECTION", snap=snap)
    [amendment] = paid(db, fix)
    assert (amendment.kind, amendment.amends_id, amendment.correction_id) == ("AMENDMENT", original.id,
                                                                              correction.id)
    assert amendment.pay_date == PAYDAY and amendment.payload["deltas"] == delta
    paye = db.query(PayrollNzRemittance).filter(PayrollNzRemittance.obligation == "PAYE").one()
    assert (paye.period_start, paye.amount, paye.late) == (date(2026, 10, 1), D("683.29"), True)
    assert {l.source for l in db.query(PayrollNzRemittanceLine)
            .filter(PayrollNzRemittanceLine.run_id == fix.id)} == {"CORRECTION"}
    assert fil.build_filings(db, fix, 1) == []                                       # once per correction


def test_correction_without_an_original_filing_is_refused(db, world):
    organization, employee, _profile = world
    run, item = make_run(db, organization, employee)
    snap = {"paymentKind": "CORRECTION", "correctionOf": item.id, "correctionId": None, "obligations": {},
            "netPay": "0", "exceptions": [], "hashes": {}}
    fix, _ = make_run(db, organization, employee, pay_date=date(2026, 12, 4), kind="CORRECTION", snap=snap)
    with pytest.raises(HTTPException) as exc:
        fil.build_filings(db, fix, 1)
    assert _conflict_code(exc) == "NZ_FILING_MISSING"


# ── run exceptions (D-P8-1) ─────────────────────────────────────────────────
def test_child_support_shortfall_can_be_approved_and_reblocks_on_change(db, world):
    organization, employee, _profile = world
    run, item = make_run(db, organization, employee, snap=snapshot(exceptions=[{"code": "NZ_CS_SHORTFALL",
                                                                                "shortfall": "102.78"}]))
    codes = lambda: {p["code"] for p in nzs.nz_run_preflight(db, run)}          # noqa: E731
    assert "NZ_CS_SHORTFALL" in codes()
    body = {"code": "NZ_CS_SHORTFALL", "payslip_item_id": item.id, "reason": "notice exceeds protected net"}
    row = life.request_run_exception(db, organization.id, run.id, body, 1)
    assert life.request_run_exception(db, organization.id, run.id, body, 1).id == row.id
    db.commit()
    with pytest.raises(BadRequestException, match="four-eyes"):
        life.approve_run_exception(db, organization.id, row.id, 1)
    life.approve_run_exception(db, organization.id, row.id, 2)
    db.commit()
    assert "NZ_CS_SHORTFALL" not in codes()
    item.nz_calculation_snapshot = {**item.nz_calculation_snapshot, "hashes": {"resultHash": "recalculated"}}
    db.commit()
    assert "NZ_CS_SHORTFALL" in codes()                                  # stale approval
    assert [v["status"] for v in life.list_run_exceptions(db, organization.id, run.id)] == ["APPROVED"]


def test_minimum_wage_fail_is_never_approvable(db, world):
    organization, employee, _profile = world
    run, item = make_run(db, organization, employee, snap=snapshot(exceptions=[{"code": "NZ_MIN_WAGE_FAIL"}]))
    with pytest.raises(BadRequestException, match="cannot be approved"):
        life.request_run_exception(db, organization.id, run.id, {"code": "NZ_MIN_WAGE_FAIL",
                                                                 "payslip_item_id": item.id, "reason": "x"}, 1)
    with pytest.raises(BadRequestException, match="no NZ_CS_SHORTFALL"):
        life.request_run_exception(db, organization.id, run.id, {"code": "NZ_CS_SHORTFALL",
                                                                 "payslip_item_id": item.id, "reason": "x"}, 1)
    db.add(PayrollNzRunException(organization_id=organization.id, employee_id=employee.id, run_id=run.id,
                                 payslip_item_id=item.id, code="NZ_MIN_WAGE_FAIL", status="REQUESTED",
                                 run_fingerprint="f" * 64, created_by_id=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_rejecting_an_exception_needs_a_reason(db, world):
    organization, employee, _profile = world
    run, item = make_run(db, organization, employee, snap=snapshot(exceptions=[{"code": "NZ_CS_SHORTFALL"}]))
    row = life.request_run_exception(db, organization.id, run.id, {"code": "NZ_CS_SHORTFALL",
                                                                   "payslip_item_id": item.id, "reason": "x"}, 1)
    with pytest.raises(BadRequestException, match="reason"):
        life.reject_run_exception(db, organization.id, row.id, 2, "")
    assert life.reject_run_exception(db, organization.id, row.id, 2, "pay the notice").status == "REJECTED"
    db.commit()
    again = life.request_run_exception(db, organization.id, run.id, {"code": "NZ_CS_SHORTFALL",
                                                                     "payslip_item_id": item.id, "reason": "y"}, 1)
    db.commit()
    assert again.id != row.id and again.status == "REQUESTED"            # a rejection does not block a new request


# ── journal ─────────────────────────────────────────────────────────────────
def test_journal_is_blocked_until_paid_and_mapped_then_balances(db, world):
    organization, employee, profile = world
    run, _ = make_run(db, organization, employee)
    assert jnl.build_nz_journal(db, organization.id, run.id)["reason"] == "the journal is built for a PAID run"
    paid(db, run)
    blocked = jnl.build_nz_journal(db, organization.id, run.id)
    assert blocked["status"] == "BLOCKED" and "salary_expense" in blocked["reason"]
    with pytest.raises(BadRequestException, match="unknown account"):
        jnl.set_journal_accounts(db, organization.id, profile.id, {"suspense": "9999"}, 1, "map")
    with pytest.raises(BadRequestException, match="reason"):
        jnl.set_journal_accounts(db, organization.id, profile.id, ACCOUNTS, 1, None)
    jnl.set_journal_accounts(db, organization.id, profile.id, ACCOUNTS, 1, "chart of accounts")
    db.commit()
    journal = jnl.build_nz_journal(db, organization.id, run.id)
    assert journal["status"] == "READY" and journal["debit"] == journal["credit"] == "3105.00"
    by_account = {line["account"]: line["amount"] for line in journal["lines"]}
    assert by_account[ACCOUNTS["salary_expense"]] == "3000.00"
    assert by_account[ACCOUNTS["kiwisaver_payable"]] == "178.50"
    assert ACCOUNTS["other_deductions_payable"] not in by_account                   # zero lines are dropped


def test_paid_transition_posts_remittances_and_builds_filings(db, world, monkeypatch):
    organization, employee, _profile = world
    run, _ = make_run(db, organization, employee)
    monkeypatch.setattr(nzs, "post_accumulators", lambda db, run, actor_id: 0)
    run.nz_approval_fingerprint = nzs.nz_approval_fingerprint(db, run)
    nzs.before_run_transition(db, run, PayrollStatus.PAID, 1)
    assert db.query(PayrollNzRemittanceLine).count() == 6
    assert [f.filing_type for f in db.query(PayrollNzFiling)] == [fil.EI]
