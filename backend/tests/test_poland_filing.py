"""Poland filing, settlement, reconciliation and journal (ZP-PL-ENG-001 Phase 8;
spec §10, PL-019 / PL-020 / PL-021 / PL-023)."""
import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from tests.test_poland_service import (PAY_DATE, PESEL, _profile, _registration, _run_with_payslip, _setup,
                                       world)  # noqa: F401  (pytest fixture)

ARCHIVED = {"1.0": {"effective_from": "2026-01-01", "effective_to": None, "evidence": "test archive"}}
ACCOUNTS = {"salary_expense": "4010", "employer_zus_expense": "4020", "employer_funds_expense": "4021",
            "employer_ppk_expense": "4022", "zus_payable": "2290", "pit_payable": "2250", "ppk_payable": "2291",
            "other_deductions_payable": "2299", "net_pay_payable": "2310"}


def _paid(w):
    """A PAID-ready run: the golden f1 payslip, PESEL in the vault, approved."""
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.models import PayrollStatus

    _setup(w)
    pl.create_pl_identifier(w.db, w.org, "PESEL", PESEL, w.a, employee_id=w.employee.id)
    w.db.commit()
    run, item = _run_with_payslip(w)
    run.pl_approval_fingerprint = pl.pl_approval_fingerprint(w.db, run)
    pl.before_run_transition(w.db, run, PayrollStatus.PAID, w.b)
    run.status = PayrollStatus.PAID
    w.db.commit()
    return run, item


def _filings(w):
    from app.modules.payroll.models import PayrollPlFiling

    return {f.form_code: f for f in w.db.query(PayrollPlFiling).filter_by(organization_id=w.org)}


def _archive(monkeypatch, forms=("DRA", "RCA", "RSA", "ZUA", "ZWUA", "PIT11", "PIT4R")):
    from app.modules.payroll.engine.countries import poland_content as content

    catalog = {k: {**v, "versions": dict(ARCHIVED) if k in forms else {}}
               for k, v in content.PL_FORM_SCHEMA_CATALOG.items()}
    monkeypatch.setattr(content, "PL_FORM_SCHEMA_CATALOG", catalog)


# ── generation at PAID ─────────────────────────────────────────────────────
def test_paid_builds_monthly_zus_payloads_with_masked_identifiers(world):
    w = world
    run, item = _paid(w)
    filings = _filings(w)
    assert set(filings) == {"DRA", "RCA"}                                      # no employer sick pay -> no RSA
    rca, dra = filings["RCA"], filings["DRA"]
    assert (rca.authority, rca.period_key, rca.status, rca.kind, rca.version) == ("ZUS", "2026-03", "DRAFT",
                                                                                  "ORIGINAL", 1)
    assert rca.schema_version is None and rca.run_ids == [run.id]
    insured = rca.payload["insured"][0]
    assert insured["employeeId"] == w.employee.id and insured["payslipItemIds"] == [item.id]
    assert insured["peselMasked"] and PESEL not in json.dumps(rca.payload) and PESEL not in json.dumps(dra.payload)
    assert insured["insuranceTitleCode"] == "011000"
    s = item.pl_calculation_snapshot
    assert insured["zusEmployee"] == s["pl_zus_employee"] and insured["health"] == s["pl_health"] == "621.29"
    assert sum(Decimal(v) for v in insured["zusEmployee"].values()) == Decimal("1096.80")
    assert dra.payload["insuredCount"] == 1 and dra.payload["dueRule"] == "NOMINAL_DAY_NO_HOLIDAY_SHIFT"
    expected = (sum(Decimal(v) for v in s["pl_zus_employee"].values())
                + sum(Decimal(v) for v in s["pl_zus_employer"].values())
                + Decimal(s["pl_health"]) + sum(Decimal(v) for v in s["pl_funds"].values()))
    assert Decimal(dra.payload["totalDue"]) == expected
    assert dra.due_on is None                                                  # no signed pack in force


def test_rebuilding_the_same_month_is_idempotent(world):
    from app.modules.payroll import poland_filing as plf
    from app.modules.payroll.models import PayrollPlFiling, PayrollPlSettlement

    w = world
    run, _item = _paid(w)
    before = {(f.id, f.payload_hash) for f in w.db.query(PayrollPlFiling)}
    settlements = {(s.id, str(s.amount_due)) for s in w.db.query(PayrollPlSettlement)}
    plf.build_pl_run_filings(w.db, run, w.a)
    from app.modules.payroll import poland_settlement as pss
    pss.build_pl_settlements(w.db, run, w.a)
    w.db.commit()
    assert {(f.id, f.payload_hash) for f in w.db.query(PayrollPlFiling)} == before
    assert {(s.id, str(s.amount_due)) for s in w.db.query(PayrollPlSettlement)} == settlements
    keys = [f.idempotency_key for f in w.db.query(PayrollPlFiling)]
    assert len(keys) == len(set(keys)) and all(len(k) == 64 for k in keys)


# ── PL-019: no archived schema -> preview only ─────────────────────────────
def test_approval_is_refused_while_no_schema_is_archived(world):
    from app.modules.payroll import poland_filing as plf

    w = world
    _paid(w)
    rca = _filings(w)["RCA"]
    with pytest.raises(HTTPException) as raised:
        plf.approve_pl_filing(w.db, w.org, rca.id, w.b)
    assert raised.value.status_code == 409 and "FILING_SCHEMA_MISMATCH" in raised.value.detail
    assert plf.get_pl_filing(w.db, w.org, rca.id)["schemaArchived"] is False
    with pytest.raises(BadRequestException, match="APPROVED"):
        plf.record_pl_filing_submission(w.db, w.org, rca.id, "ZUS-123", w.a)


def test_full_lifecycle_with_an_archived_schema(world, monkeypatch):
    from app.modules.payroll import poland_filing as plf

    w = world
    _paid(w)
    _archive(monkeypatch)
    rca = _filings(w)["RCA"]
    rca.created_by_id = w.a
    w.db.commit()
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        plf.approve_pl_filing(w.db, w.org, rca.id, w.a)                        # creator cannot approve
    w.db.rollback()
    row = plf.approve_pl_filing(w.db, w.org, rca.id, w.b)
    assert (row.status, row.schema_version, row.approved_by_id) == ("APPROVED", "1.0", w.b)
    with pytest.raises(BadRequestException, match="submissionRef"):
        plf.record_pl_filing_submission(w.db, w.org, rca.id, " ", w.a)
    row = plf.record_pl_filing_submission(w.db, w.org, rca.id, "ZUS-2026-03-001", w.a)
    assert row.status == "SUBMITTED"
    assert plf.record_pl_filing_submission(w.db, w.org, rca.id, "ZUS-2026-03-001", w.a) is row   # retry
    with pytest.raises(HTTPException, match="PL_FILING_ALREADY_SUBMITTED"):
        plf.record_pl_filing_submission(w.db, w.org, rca.id, "ZUS-OTHER", w.a)
    with pytest.raises(BadRequestException, match="receiptRef"):
        plf.record_pl_filing_response(w.db, w.org, rca.id, {"outcome": "ACCEPTED"}, w.a)
    with pytest.raises(BadRequestException, match="errorCodes"):
        plf.record_pl_filing_response(w.db, w.org, rca.id, {"outcome": "REJECTED"}, w.a)
    row = plf.record_pl_filing_response(w.db, w.org, rca.id, {"outcome": "ACCEPTED", "receiptRef": "UPO-1"}, w.a)
    assert (row.status, row.receipt_ref) == ("ACCEPTED", "UPO-1")
    assert plf.record_pl_filing_response(w.db, w.org, rca.id, {"outcome": "ACCEPTED", "receiptRef": "UPO-1"},
                                         w.a) is row                           # retry
    with pytest.raises(HTTPException, match="PL_FILING_ALREADY_ANSWERED"):
        plf.record_pl_filing_response(w.db, w.org, rca.id, {"outcome": "REJECTED", "errorCodes": ["X"]}, w.a)


def test_a_tampered_payload_cannot_be_submitted(world, monkeypatch):
    from app.modules.payroll import poland_filing as plf

    w = world
    _paid(w)
    _archive(monkeypatch)
    dra = _filings(w)["DRA"]
    assert dra.created_by_id == w.b                                            # built by whoever marked it PAID
    plf.approve_pl_filing(w.db, w.org, dra.id, w.a)
    dra.payload = {**dra.payload, "totalDue": "1.00"}
    w.db.commit()
    with pytest.raises(HTTPException, match="PAYLOAD_CHANGED_AFTER_APPROVAL"):
        plf.record_pl_filing_submission(w.db, w.org, dra.id, "ZUS-1", w.a)


# ── versioning (PL-020) ────────────────────────────────────────────────────
def test_versions_supersede_correct_and_resubmit(world, monkeypatch):
    from app.modules.payroll import poland_filing as plf

    w = world
    _archive(monkeypatch)
    up = lambda payload: plf.upsert_filing(w.db, w.org, None, "DRA", "2026-04", payload, [1], None, w.a)  # noqa: E731
    v1 = up({"totalDue": "10.00"})
    assert up({"totalDue": "10.00"}) is v1                                     # same payload -> same row
    assert up({"totalDue": "11.00"}) is v1 and v1.payload["totalDue"] == "11.00"   # a DRAFT is regenerated
    plf.approve_pl_filing(w.db, w.org, v1.id, w.b)
    v2 = up({"totalDue": "12.00"})
    assert (v1.status, v2.version, v2.kind, v2.previous_version_id) == ("SUPERSEDED", 2, "ORIGINAL", v1.id)
    plf.approve_pl_filing(w.db, w.org, v2.id, w.b)
    plf.record_pl_filing_submission(w.db, w.org, v2.id, "S-2", w.a)
    plf.record_pl_filing_response(w.db, w.org, v2.id, {"outcome": "ACCEPTED", "receiptRef": "R-2"}, w.a)
    assert up({"totalDue": "12.00"}) is v2                                     # unchanged after acceptance
    c1 = up({"totalDue": "13.00"})
    assert (c1.kind, c1.corrects_id, c1.version, c1.payload["correction"]) == ("CORRECTION", v2.id, 1, True)
    assert up({"totalDue": "13.00"}) is c1                                     # no duplicate correction
    plf.approve_pl_filing(w.db, w.org, c1.id, w.b)
    plf.record_pl_filing_submission(w.db, w.org, c1.id, "S-C1", w.a)
    plf.record_pl_filing_response(w.db, w.org, c1.id, {"outcome": "ACCEPTED", "receiptRef": "R-C1"}, w.a)
    assert v2.status == "CORRECTED"


def test_a_rejected_filing_is_followed_by_a_new_original_version(world, monkeypatch):
    from app.modules.payroll import poland_filing as plf

    w = world
    _archive(monkeypatch)
    v1 = plf.upsert_filing(w.db, w.org, None, "DRA", "2026-05", {"t": "1"}, [], None, w.a)
    plf.approve_pl_filing(w.db, w.org, v1.id, w.b)
    plf.record_pl_filing_submission(w.db, w.org, v1.id, "S-1", w.a)
    row = plf.record_pl_filing_response(w.db, w.org, v1.id, {"outcome": "REJECTED", "errorCodes": ["e12 "],
                                                             "message": "bad base"}, w.a)
    assert row.rejection == {"codes": ["E12"], "message": "bad base"}
    v2 = plf.upsert_filing(w.db, w.org, None, "DRA", "2026-05", {"t": "2"}, [], None, w.a)
    assert (v2.kind, v2.version, v2.previous_version_id, v1.status) == ("ORIGINAL", 2, v1.id, "REJECTED")


# ── registration and annual forms ──────────────────────────────────────────
def test_registration_forms_from_the_profile_and_out_of_scope_forms(world):
    from app.modules.payroll import poland_filing as plf

    w = world
    with pytest.raises(HTTPException, match="PL_PROFILE_MISSING"):
        plf.build_pl_registration_filing(w.db, w.org, w.employee.id, "ZUA", "2026-01-01", w.a)
    _profile(w)
    row = plf.build_pl_registration_filing(w.db, w.org, w.employee.id, "zua", "2026-01-01", w.a)
    assert (row.form_code, row.subject_key, row.due_on) == ("ZUA", f"E{w.employee.id}:2026-01-01", None)
    assert row.payload["coverage"] == {"pension": True, "disability": True, "sickness": True, "accident": True,
                                       "health": True}
    assert plf.build_pl_registration_filing(w.db, w.org, w.employee.id, "ZUA", "2026-01-01", w.a) is row
    with pytest.raises(BadRequestException, match="reason code"):
        plf.build_pl_registration_filing(w.db, w.org, w.employee.id, "ZWUA", "2026-06-30", w.a)
    assert plf.build_pl_registration_filing(w.db, w.org, w.employee.id, "ZWUA", "2026-06-30", w.a,
                                            reason_code="100").payload["reasonCode"] == "100"
    for form in ("RPA", "PIT8AR"):
        with pytest.raises(HTTPException, match="PL_FORM_OUT_OF_SCOPE"):
            plf.build_pl_registration_filing(w.db, w.org, w.employee.id, form, "2026-01-01", w.a)
    with pytest.raises(BadRequestException, match="form must be"):
        plf.build_pl_registration_filing(w.db, w.org, w.employee.id, "DRA", "2026-01-01", w.a)


def test_annual_returns_only_for_a_closed_year_and_matching_ledger(world):
    from app.modules.payroll import poland_filing as plf
    from app.modules.payroll.models import PayrollPlAccumulatorEntry

    w = world
    _paid(w)
    with pytest.raises(HTTPException, match="PL_TAX_YEAR_OPEN"):
        plf.build_pl_annual_filings(w.db, w.org, 2026, None, w.a, today=date(2026, 12, 31))
    rows = plf.build_pl_annual_filings(w.db, w.org, 2026, None, w.a, today=date(2027, 1, 5))
    pit11, pit4r = rows
    assert (pit11.form_code, pit11.authority, pit11.period_key, pit11.subject_key) == ("PIT11", "KAS", "2026",
                                                                                      f"E{w.employee.id}")
    p = pit11.payload
    assert (p["grossRevenue"], p["pitAdvance"], p["healthContribution"]) == ("8000.00", "513.00", "621.29")
    assert p["zusEmployeeDeducted"] == "1096.80" and PESEL not in json.dumps(p) and p["peselMasked"]
    assert pit4r.payload["monthlyAdvances"] == {"2026-03": "513.00"} and pit4r.payload["total"] == "513.00"
    assert plf.build_pl_annual_filings(w.db, w.org, 2026, None, w.a, today=date(2027, 1, 5))[0] is pit11
    entry = w.db.query(PayrollPlAccumulatorEntry).filter_by(accumulator="PIT_ADVANCE").first()
    entry.amount = Decimal("500")
    w.db.commit()
    with pytest.raises(HTTPException, match="PL_LEDGER_MISMATCH"):
        plf.build_pl_annual_filings(w.db, w.org, 2026, None, w.a, today=date(2027, 1, 5))


def test_due_dates_come_from_signed_content_only(world):
    from types import SimpleNamespace

    from app.modules.payroll import poland_filing as plf
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.models import ContributionRate

    w = world
    registration = SimpleNamespace(zus_deadline_class="DAY_15")
    assert plf.zus_due_on(w.db, w.org, "2026-03", registration) is None        # no Active pack
    pack = pl.seed_poland_pack(w.db)
    for row in w.db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id):
        row.label = row.label.replace(pl.PENDING_G1_SUFFIX, "")                  # simulate the G1 signature
    pack.status = "Active"
    w.db.commit()
    assert plf.zus_due_on(w.db, w.org, "2026-03", registration) == date(2026, 4, 15)
    assert plf.zus_due_on(w.db, w.org, "2026-03", SimpleNamespace(zus_deadline_class="DAY_5")) == date(2026, 4, 5)
    assert plf.annual_due_on(w.db, w.org, 2026, "pl_pit11_authority_due") == date(2027, 1, 31)
    from app.modules.payroll import poland_settlement as pss
    assert pss._due_on(w.db, w.org, "PIT", "2026-03", registration) is None    # remittance rule PENDING_G1


# ── settlements and reconciliation ─────────────────────────────────────────
def test_liabilities_from_the_paid_payslips(world):
    from app.modules.payroll import poland_settlement as pss

    w = world
    _run, item = _paid(w)
    s = item.pl_calculation_snapshot
    rows = {r["liabilityType"]: r for r in pss.list_pl_settlements(w.db, w.org)}
    assert set(rows) == {"ZUS", "PIT", "PPK"}
    assert rows["PIT"]["amountDue"] == "513.00" and rows["PPK"]["amountDue"] == "280.00"
    zus = Decimal(rows["ZUS"]["amountDue"])
    assert zus == (Decimal("1096.80") + Decimal("621.29") + sum(Decimal(v) for v in s["pl_zus_employer"].values())
                   + sum(Decimal(v) for v in s["pl_funds"].values()))
    assert rows["ZUS"]["components"]["health"] == "621.29" and rows["ZUS"]["status"] == "DUE"


def test_payments_are_idempotent_and_reconciliation_needs_a_second_person(world):
    from app.modules.payroll import poland_settlement as pss

    w = world
    _paid(w)
    pit = next(r for r in pss.list_pl_settlements(w.db, w.org) if r["liabilityType"] == "PIT")
    pay = {"amount": "500.00", "paidOn": "2026-04-20", "paymentRef": "MT-1"}
    row = pss.record_pl_settlement_payment(w.db, w.org, pit["id"], pay, w.a)
    assert (row.status, str(row.paid_amount)) == ("PART_PAID", "500.00")
    assert pss.record_pl_settlement_payment(w.db, w.org, pit["id"], pay, w.a) is row        # retry
    assert str(row.paid_amount) == "500.00" and len(row.payments) == 1
    with pytest.raises(HTTPException, match="PL_PAYMENT_REF_REUSED"):
        pss.record_pl_settlement_payment(w.db, w.org, pit["id"], {**pay, "amount": "13.00"}, w.a)
    with pytest.raises(BadRequestException, match="greater than zero"):
        pss.record_pl_settlement_payment(w.db, w.org, pit["id"], {**pay, "paymentRef": "X", "amount": "0"}, w.a)
    out = pss.reconcile_pl_settlement(w.db, w.org, pit["id"], w.a)
    variance = out["variance"]
    assert (variance["kind"], variance["difference"], out["settlement"]["status"]) == ("UNDERPAID", "-13.00",
                                                                                       "PART_PAID")
    w.db.commit()
    with pytest.raises(HTTPException, match="PL_VARIANCE_OPEN"):
        pss.reconcile_pl_settlement(w.db, w.org, pit["id"], w.a)
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        pss.resolve_pl_variance(w.db, w.org, variance["id"], "bank fee", w.a)
    w.db.rollback()
    with pytest.raises(BadRequestException, match="reason"):
        pss.resolve_pl_variance(w.db, w.org, variance["id"], "", w.b)
    resolved = pss.resolve_pl_variance(w.db, w.org, variance["id"], "difference paid with April", w.b)
    assert resolved.status == "RESOLVED"
    settled = next(r for r in pss.list_pl_settlements(w.db, w.org) if r["id"] == pit["id"])
    assert settled["status"] == "RECONCILED" and settled["reconciledById"] == w.b


def test_exact_payment_reconciles_and_a_later_change_raises_a_variance(world):
    from app.modules.payroll import poland_settlement as pss

    w = world
    run, item = _paid(w)
    ppk = next(r for r in pss.list_pl_settlements(w.db, w.org) if r["liabilityType"] == "PPK")
    pss.record_pl_settlement_payment(w.db, w.org, ppk["id"], {"amount": "280.00", "paidOn": "2026-04-15",
                                                              "paymentRef": "PPK-1"}, w.a)
    out = pss.reconcile_pl_settlement(w.db, w.org, ppk["id"], w.a)
    assert out["variance"] is None and out["settlement"]["status"] == "RECONCILED"
    with pytest.raises(HTTPException, match="PL_SETTLEMENT_RECONCILED"):
        pss.record_pl_settlement_payment(w.db, w.org, ppk["id"], {"amount": "1", "paidOn": "2026-04-16",
                                                                  "paymentRef": "PPK-2"}, w.a)
    snapshot = dict(item.pl_calculation_snapshot)
    snapshot["pl_ppk_employer"] = {k: ("130.00" if k == "BASIC" else v) for k, v in snapshot["pl_ppk_employer"].items()}
    item.pl_calculation_snapshot = snapshot
    w.db.commit()
    pss.build_pl_settlements(w.db, run, w.a)
    row = next(r for r in pss.list_pl_settlements(w.db, w.org) if r["id"] == ppk["id"])
    assert (row["amountDue"], row["status"], row["reconciledById"]) == ("290.00", "PART_PAID", None)
    variances = pss.list_pl_variances(w.db, w.org, status="open")
    assert [(v["kind"], v["difference"]) for v in variances] == [("CHANGED_AFTER_PAYMENT", "-10.00")]


# ── journal ────────────────────────────────────────────────────────────────
def test_journal_is_blocked_without_the_employers_accounts_and_balances_with_them(world):
    from app.modules.payroll import poland_journal as plj
    from app.modules.payroll.models import PayrollPlEmployerRegistration

    w = world
    run, item = _paid(w)
    item.net_pay = Decimal("5608.91")
    w.db.commit()
    out = plj.build_pl_journal(w.db, w.org, run.id)
    assert out["status"] == "BLOCKED" and "salary_expense" in out["reason"]
    w.db.query(PayrollPlEmployerRegistration).update({"pl_journal_accounts": ACCOUNTS})
    w.db.commit()
    out = plj.build_pl_journal(w.db, w.org, run.id)
    assert out["status"] == "READY" and out["debit"] == out["credit"]
    lines = {l["account"]: (l["side"], Decimal(l["amount"])) for l in out["lines"]}
    assert lines["4010"] == ("DR", Decimal("8000.00")) and lines["2250"] == ("CR", Decimal("513.00"))
    assert lines["2310"] == ("CR", Decimal("5608.91")) and lines["2291"] == ("CR", Decimal("280.00"))
    run.status = "Approved"
    w.db.commit()
    assert plj.build_pl_journal(w.db, w.org, run.id)["status"] == "BLOCKED"


def test_registration_journal_accounts_are_validated(world):
    from app.modules.payroll import poland_service as pl

    w = world
    with pytest.raises(BadRequestException, match="unknown journal account"):
        pl.record_pl_employer_registration(w.db, w.org, {
            "effective_from": "2026-01-01", "legal_name": "X", "nip": "5261040828", "zus_deadline_class": "DAY_15",
            "pl_journal_accounts": {"salary": "4010"}}, w.a, "setup")
    row = _registration(w, pl_journal_accounts={"salary_expense": " 4010 ", "pit_payable": ""})
    assert row.pl_journal_accounts == {"salary_expense": "4010"}


# ── PL-023: Polish letters in bank-export PDFs ─────────────────────────────
def _bank_rows(name):
    from app.modules.payroll.bank_export.base import BankExportRow

    return [BankExportRow(employee_name=name, employee_id="PL1", bank_name="Bank Śląski",
                          account_number="PL61109010140000071219812874",  # privacy-scan: allow
                          ifsc="", branch=None, amount=5608.91, reference_number="R1", narration="Wynagrodzenie",
                          payment_date="2026-03-31", currency="PLN", company_name="Spółka Testowa",
                          routing_label="IBAN / SWIFT", routing_value="BPKOPLPW")]


def test_bank_pdf_uses_a_unicode_font_or_refuses(monkeypatch):
    from app.modules.payroll import pdf_fonts
    from app.modules.payroll.bank_export.pdf_exporter import PDFExporter

    assert pdf_fonts.needs_unicode(["Łukasz Żółć"]) and not pdf_fonts.needs_unicode(["Jan Kowalski", None])
    if pdf_fonts.unicode_font() is not None:
        pdf = PDFExporter().generate(_bank_rows("Łukasz Żółć"))
        assert pdf.startswith(b"%PDF") and b"/FontFile2" in pdf                # an embedded TrueType font
    monkeypatch.setattr(pdf_fonts, "unicode_font", lambda: None)
    with pytest.raises(BadRequestException, match="BANK_PDF_UNICODE_FONT_MISSING"):
        PDFExporter().generate(_bank_rows("Łukasz Żółć"))
    with pytest.raises(BadRequestException, match="BANK_PDF_UNICODE_FONT_MISSING"):
        PDFExporter().generate(_bank_rows("Jan Kowalski"))                     # company / bank name are Polish


# ── router ─────────────────────────────────────────────────────────────────
def test_router_exposes_the_phase_8_routes():
    from app.modules.payroll.pl_org_router import router

    paths = {(m, r.path) for r in router.routes for m in r.methods}
    for method, path in (("GET", "/poland/filings"), ("GET", "/poland/filings/{filing_id}"),
                         ("POST", "/poland/filings/rebuild/{run_id}"), ("POST", "/poland/filings/annual"),
                         ("POST", "/poland/filings/registration"), ("POST", "/poland/filings/{filing_id}/approve"),
                         ("POST", "/poland/filings/{filing_id}/submission"),
                         ("POST", "/poland/filings/{filing_id}/response"), ("GET", "/poland/settlements"),
                         ("POST", "/poland/settlements/{settlement_id}/payments"),
                         ("POST", "/poland/settlements/{settlement_id}/reconcile"), ("GET", "/poland/variances"),
                         ("POST", "/poland/variances/{variance_id}/resolve"),
                         ("GET", "/poland/runs/{run_id}/journal")):
        assert (method, path) in paths, path


def test_database_refuses_an_approved_filing_without_schema_or_second_person(world):
    from sqlalchemy.exc import IntegrityError

    from app.modules.payroll import poland_filing as plf

    w = world
    row = plf.upsert_filing(w.db, w.org, None, "DRA", "2026-06", {"t": "1"}, [], None, w.a)
    w.db.commit()
    for values in ({"status": "APPROVED", "approved_by_id": w.b},                     # no schema version
                   {"status": "APPROVED", "approved_by_id": w.a, "schema_version": "1.0"},   # same person
                   {"status": "SUBMITTED", "approved_by_id": w.b, "schema_version": "1.0"}):  # no reference
        for key, value in values.items():
            setattr(row, key, value)
        with pytest.raises(IntegrityError):
            w.db.commit()
        w.db.rollback()
