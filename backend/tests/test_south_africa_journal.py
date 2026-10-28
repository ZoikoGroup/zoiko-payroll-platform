"""South Africa payroll journal (ZP-ZA-ENG-001 §10; Phase 9): balanced
double entry under the employer's own accounts, or BLOCKED. "ZA" is South Africa."""
from datetime import date
from decimal import Decimal

from app.modules.payroll import south_africa_journal as journal
from app.modules.payroll.models import PayrollZaEmployerRegistration

from tests._za_run_helpers import employee, payslip, run

ACCOUNTS = {k: f"GL-{i:03d}" for i, k in enumerate(journal.ACCOUNT_KEYS, start=1)}


def _f1_f2(db, organization):
    r = run(db, organization, status="Paid")
    payslip(db, organization, r, employee(db, organization, "ZA-J1"), "f1_monthly_salary_age_40")
    payslip(db, organization, r, employee(db, organization, "ZA-J2"), "f2_age_68_one_medical_dependant")
    return r


def _side(out, key):
    return next(l for l in out["lines"] if l["accountKey"] == key)


def test_f1_f2_journal_balances(db, organization):
    r = _f1_f2(db, organization)
    out = journal.build_za_journal(db, organization.id, r.id, ACCOUNTS)
    assert out["status"] == "READY" and out["payslipCount"] == 2
    assert out["debitTotal"] == out["creditTotal"] == "81154.24"          # gross 80,000 + UIF er 354.24 + SDL 800
    assert _side(out, "paye_liability") == {"accountKey": "paye_liability", "account": "GL-004",
                                            "side": "CREDIT", "amount": "14190.83"}
    assert _side(out, "uif_liability")["amount"] == "708.48"
    assert _side(out, "net_pay_clearing")["amount"] == "65454.93"
    assert not any(l["accountKey"].startswith("eti_") for l in out["lines"])


def test_missing_account_blocks(db, organization):
    r = _f1_f2(db, organization)
    accounts = {k: v for k, v in ACCOUNTS.items() if k != "sdl_liability"}
    out = journal.build_za_journal(db, organization.id, r.id, accounts)
    assert out["status"] == "BLOCKED" and out["missingAccounts"] == ["sdl_liability"]


def test_no_account_map_on_the_registration_blocks(db, organization):
    r = _f1_f2(db, organization)
    out = journal.build_za_journal(db, organization.id, r.id)
    assert out["status"] == "BLOCKED" and "account map" in out["reason"]


def test_account_map_is_read_from_the_registration(db, organization):
    db.add(PayrollZaEmployerRegistration(organization_id=organization.id, effective_from=date(2026, 3, 1),
                                         paye_reference="7000000000", uif_reference="U000000000",
                                         sdl_reference="L000000000", sdl_liable=True, eti_registered=False,
                                         status="ACTIVE", za_journal_accounts=ACCOUNTS))
    r = _f1_f2(db, organization)
    assert journal.build_za_journal(db, organization.id, r.id)["status"] == "READY"


def test_eti_posts_only_between_the_incentive_accounts(db, organization):
    r = run(db, organization, status="Paid")
    payslip(db, organization, r, employee(db, organization, "ZA-JE"), "f3_eti_first_twelve_months_r5000_is_r1500")
    out = journal.build_za_journal(db, organization.id, r.id, ACCOUNTS)
    assert out["status"] == "READY"
    assert _side(out, "eti_receivable")["amount"] == _side(out, "eti_incentive")["amount"] == "1500.00"
    assert _side(out, "net_pay_clearing")["amount"] == "4950.00"           # ETI never reaches net pay


def test_a_deduction_outside_the_za_result_unbalances_and_blocks(db, organization):
    r = run(db, organization, status="Paid")
    item = payslip(db, organization, r, employee(db, organization, "ZA-JX"), "f1_monthly_salary_age_40")
    item.net_pay = item.net_pay - Decimal("100")                           # e.g. a non-ZA loan deduction
    db.flush()
    out = journal.build_za_journal(db, organization.id, r.id, ACCOUNTS)
    assert out["status"] == "BLOCKED" and out["reason"].startswith("ZA_JOURNAL_UNBALANCED")


def test_authorised_deductions_get_their_own_liability_line(db, organization):
    r = run(db, organization, status="Paid")
    payslip(db, organization, r, employee(db, organization, "ZA-JD"), "f1_monthly_salary_age_40",
            za_deduction_orders=[{"id": 1, "order_type": "GARNISHEE", "authority_type": "COURT_ORDER",
                                  "amount": "500", "evidence_ref": "EAO-1"}])
    out = journal.build_za_journal(db, organization.id, r.id, ACCOUNTS)
    assert out["status"] == "READY"
    assert _side(out, "other_deductions_liability")["amount"] == "500.00"
    assert _side(out, "net_pay_clearing")["amount"] == "38247.30"


def test_registration_accepts_only_known_non_blank_accounts(db, organization):
    import pytest
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import south_africa_service as svc

    base = {"payeReference": "7000000000", "sdlLiable": True, "effectiveFrom": "2026-03-01"}
    row = svc.create_za_employer_registration(db, organization.id, {**base, "journalAccounts": ACCOUNTS})
    assert row.za_journal_accounts == ACCOUNTS
    with pytest.raises(BadRequestException, match="unknown key"):
        svc.create_za_employer_registration(db, organization.id, {**base, "journalAccounts": {"cash": "1"}})
    with pytest.raises(BadRequestException, match="blank"):
        svc.create_za_employer_registration(db, organization.id, {**base, "journalAccounts": {"paye_liability": " "}})
    assert svc.create_za_employer_registration(db, organization.id, base).za_journal_accounts is None
