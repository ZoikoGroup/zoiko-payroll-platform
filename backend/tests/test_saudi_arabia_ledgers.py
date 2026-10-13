"""Saudi Arabia separate ledgers (ZP-SA-ENG-001 §7/§12) — the service wiring
for employer GOSI registration, employee contracts, the monthly GOSI liability,
the EOS accrual ledger, final settlement and the WPS SIE extract.

These are the ledgers the engine deliberately does NOT compute (it never
approximates them). Each test drives the real service functions against the
isolated SQLite `db` fixture with a minimal configured pack, so what is proven
here is the wiring and the governance (idempotency, fail-closed skips, the
Art. 87 resignation fraction), not the statutory arithmetic — which the golden
vectors and eos.py's own tests cover.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import saudi_arabia_service as svc
from app.modules.payroll.engine.jurisdictions.saudi_arabia import eos as _eos
from app.modules.payroll.models import (
    ContributionRate,
    JurisdictionPack,
    PayrollEmployee,
    PayrollRun,
    PayslipItem,
)


# Spec §13: amounts in flat_amount; resignation fractions EXACT in text_value.
EOS_ROWS = {
    "sa_eos_first_5_years_months": (Decimal("0.5"), None),
    "sa_eos_after_5_years_months": (Decimal("1.0"), None),
    "sa_eos_resign_frac_under_2": (None, "0"),
    "sa_eos_resign_frac_2_to_5": (None, "1/3"),
    "sa_eos_resign_frac_5_to_10": (None, "2/3"),
    "sa_eos_resign_frac_10_plus": (None, "1"),
}


def _pack(db):
    pack = JurisdictionPack(pack_id="SA-PAYROLL-2026", version="1.0",
                            jurisdiction_country="SA", pack_type="tax",
                            effective_from=date(2026, 1, 1), status="Active")
    db.add(pack)
    db.flush()
    for key, (flat, text) in EOS_ROWS.items():
        db.add(ContributionRate(
            organization_id=None, component_key=key, label=key,
            employee_share="-", employer_share="-", total="-",
            flat_amount=flat, text_value=text, jurisdiction_country="SA", jurisdiction_pack_id=pack.id))
    db.flush()
    return pack


def _employee(db, organization, *, joining=date(2020, 1, 1), basic="10000", code="E1"):
    emp = PayrollEmployee(organization_id=organization.id, employee_code=code, name=f"Emp {code}",
                          date_of_joining=joining, basic=Decimal(basic), country_code="SA")
    db.add(emp)
    db.flush()
    return emp


def _run(db, organization, *, status="Approved", start=date(2026, 3, 1), end=date(2026, 3, 31)):
    run = PayrollRun(organization_id=organization.id, period_label="Mar 2026",
                     period_start=start, period_end=end, pay_date=end, status=status)
    db.add(run)
    db.flush()
    return run


def _payslip(db, organization, run, employee, *, gross="10000", net="8000", snapshot=None):
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name=employee.name, country_code="SA",
        gross_pay=Decimal(gross), net_pay=Decimal(net),
        sa_calculation_snapshot=snapshot if snapshot is not None else _gosi_snapshot())
    db.add(item)
    db.flush()
    return item


def _gosi_snapshot(*, pension_ee="950", pension_er="1050", saned_ee="75", saned_er="75",
                   oh_er="200", contributory="10000"):
    return {
        "gosi": {
            "employeePension": pension_ee, "employerPension": pension_er,
            "employeeSocialSecurity": saned_ee, "employerSocialSecurity": saned_er,
            "employerOccupationalHazard": oh_er,
        },
        "calculation": {"contributoryWage": contributory},
    }


# ── Employer GOSI registration (versioned) ──────────────────────────────────
def test_employer_profile_requires_gosi_code(db, organization):
    with pytest.raises(Exception):
        svc.create_sa_employer_profile(db, organization.id, {"effectiveFrom": "2026-01-01"})


def test_employer_profile_versions_close_the_open_row(db, organization):
    first = svc.create_sa_employer_profile(db, organization.id, {
        "effectiveFrom": "2026-01-01", "gosiEmployerCode": "GOSI-1"})
    db.refresh(first)
    assert first.status == "DRAFT" and first.effective_to is None

    second = svc.create_sa_employer_profile(db, organization.id, {
        "effectiveFrom": "2026-07-01", "gosiEmployerCode": "GOSI-2"})
    db.refresh(first)
    db.refresh(second)
    assert first.effective_to == date(2026, 6, 30)
    assert first.status == "SUPERSEDED"
    assert second.previous_version_id == first.id

    approved = svc.approve_sa_employer_profile(db, organization.id, second.id, actor_id=9)
    assert approved.status == "APPROVED" and approved.approved_by_id == 9


# ── Employee contract (versioned) ───────────────────────────────────────────
def test_contract_type_is_validated(db, organization):
    emp = _employee(db, organization)
    with pytest.raises(Exception):
        svc.create_sa_contract_version(db, organization.id, emp.id, {"contractType": "FREELANCE"})


def test_contract_version_in_force(db, organization):
    emp = _employee(db, organization)
    svc.create_sa_contract_version(db, organization.id, emp.id, {
        "effectiveFrom": "2026-01-01", "contractType": "LIMITED", "basicWage": "9000",
        "housingAllowance": "3000"})
    contract = svc.get_sa_contract_version(db, emp.id, as_of=date(2026, 3, 1))
    assert contract.contract_type == "LIMITED"
    assert contract.housing_allowance == Decimal("3000.00")


# ── GOSI liability monthly reconciliation ───────────────────────────────────
def test_gosi_liability_aggregates_and_is_idempotent(db, organization):
    run = _run(db, organization)
    emp = _employee(db, organization)
    _payslip(db, organization, run, emp, gross="10000")

    row = svc.build_sa_gosi_liability(db, organization.id, run.id)
    assert row.contribution_month == date(2026, 3, 1)
    assert row.pension_employee == Decimal("950")
    assert row.pension_employer == Decimal("1050")
    assert row.saned_employee == Decimal("75")
    assert row.occupational_hazard_employer == Decimal("200")
    assert row.total_due == Decimal("2350")
    assert row.contributory_wages == Decimal("10000")

    again = svc.build_sa_gosi_liability(db, organization.id, run.id)
    assert again.id == row.id
    assert len(svc.list_sa_gosi_liabilities(db, organization.id)) == 1

    paid = svc.mark_sa_gosi_liability_paid(db, organization.id, row.id, payment_reference="PAY-1")
    assert paid.status == "PAID" and paid.payment_reference == "PAY-1"


def test_gosi_liability_blocks_on_uncommitted_run(db, organization):
    run = _run(db, organization, status="Draft")
    _employee(db, organization)
    with pytest.raises(Exception):
        svc.build_sa_gosi_liability(db, organization.id, run.id)


# ── EOS accrual ledger ──────────────────────────────────────────────────────
def test_eos_accrual_uses_contract_base_and_is_incremental(db, organization):
    _pack(db)
    run = _run(db, organization, start=date(2026, 3, 1), end=date(2026, 3, 31))
    emp = _employee(db, organization, joining=date(2020, 1, 1))
    svc.create_sa_contract_version(db, organization.id, emp.id, {
        "effectiveFrom": "2026-01-01", "contractType": "UNLIMITED",
        "basicWage": "10000", "housingAllowance": "5000"})
    _payslip(db, organization, run, emp)

    out = svc.accrue_sa_eos_for_run(db, organization.id, run.id)
    assert len(out["entries"]) == 1 and not out["skipped"]
    entry = out["entries"][0]
    assert entry.eos_base == Decimal("15000.00")
    assert entry.accrual_months > 0
    assert entry.eos_award_accrued > 0
    assert entry.cumulative_award == entry.eos_award_accrued

    # The recorded accrual equals the increment of the Art. 84/85 award.
    rate_rows = svc._sa_eos_rate_rows(db, _pack_lookup(db))
    years_start = svc._service_years(emp.date_of_joining, run.period_start)
    years_end = svc._service_years(emp.date_of_joining, run.period_end)
    expected = (_eos.eos_award(Decimal("15000"), years_end, rate_rows)["months"]
                - _eos.eos_award(Decimal("15000"), years_start, rate_rows)["months"]) * Decimal("15000")
    assert entry.eos_award_accrued == expected.quantize(Decimal("0.01"))


def test_eos_accrual_skips_employee_without_joining_date(db, organization):
    _pack(db)
    run = _run(db, organization)
    emp = _employee(db, organization, joining=None)
    svc.create_sa_contract_version(db, organization.id, emp.id, {
        "effectiveFrom": "2026-01-01", "contractType": "UNLIMITED", "basicWage": "10000"})
    _payslip(db, organization, run, emp)

    out = svc.accrue_sa_eos_for_run(db, organization.id, run.id)
    assert not out["entries"]
    assert out["skipped"][0]["employeeId"] == emp.id


def _pack_lookup(db):
    return svc.latest_sa_tax_pack(db)


# ── Final settlement ────────────────────────────────────────────────────────
def test_final_settlement_termination_pays_full_award(db, organization):
    _pack(db)
    emp = _employee(db, organization, joining=date(2020, 1, 1))
    svc.create_sa_contract_version(db, organization.id, emp.id, {
        "effectiveFrom": "2026-01-01", "contractType": "UNLIMITED",
        "basicWage": "10000", "housingAllowance": "5000"})

    row = svc.build_sa_final_settlement(db, organization.id, {
        "employeeId": emp.id, "terminationDate": "2026-01-01",
        "terminationType": "TERMINATION", "unusedLeavePay": "2000", "deductions": "500"})

    rate_rows = svc._sa_eos_rate_rows(db, svc.latest_sa_tax_pack(db))
    years = svc._service_years(emp.date_of_joining, date(2026, 1, 1))
    expected_award = _eos.eos_award(Decimal("15000"), years, rate_rows)["award"]
    assert row.eos_award == expected_award
    assert row.total_due == expected_award + Decimal("2000")
    assert row.net_payable == row.total_due - Decimal("500")
    assert row.deadline_date == date(2026, 1, 8)  # 7 days for termination


def test_final_settlement_resignation_pro_rates_by_band(db, organization):
    _pack(db)
    emp = _employee(db, organization, joining=date(2023, 1, 1))
    svc.create_sa_contract_version(db, organization.id, emp.id, {
        "effectiveFrom": "2026-01-01", "contractType": "LIMITED", "basicWage": "10000"})

    row = svc.build_sa_final_settlement(db, organization.id, {
        "employeeId": emp.id, "terminationDate": "2026-01-01", "terminationType": "RESIGNATION"})

    rate_rows = svc._sa_eos_rate_rows(db, svc.latest_sa_tax_pack(db))
    years = svc._service_years(emp.date_of_joining, date(2026, 1, 1))
    award = _eos.eos_award(Decimal("10000"), years, rate_rows)
    expected = _eos.settlement_amount(award, True, years, rate_rows)["payable"]
    assert row.eos_award == expected
    assert row.deadline_date == date(2026, 1, 15)  # 14 days for resignation


def test_final_settlement_four_eyes_and_pay(db, organization):
    _pack(db)
    emp = _employee(db, organization, joining=date(2020, 1, 1))
    svc.create_sa_contract_version(db, organization.id, emp.id, {
        "effectiveFrom": "2026-01-01", "contractType": "UNLIMITED", "basicWage": "10000"})
    row = svc.build_sa_final_settlement(db, organization.id, {
        "employeeId": emp.id, "terminationDate": "2026-02-01", "terminationType": "TERMINATION"})

    approved = svc.approve_sa_final_settlement(db, organization.id, row.id, actor_id=5)
    assert approved.status == "APPROVED"
    with pytest.raises(Exception):
        svc.approve_sa_final_settlement(db, organization.id, row.id, actor_id=6)  # not DRAFT
    paid = svc.pay_sa_final_settlement(db, organization.id, row.id, payment_reference="REF-1")
    assert paid.status == "PAID" and paid.payment_reference == "REF-1"


# ── WPS SIE extract ─────────────────────────────────────────────────────────
def test_wps_file_is_content_addressed_and_deduped(db, organization):
    run = _run(db, organization)
    emp = _employee(db, organization)
    _payslip(db, organization, run, emp, net="8000")

    first = svc.build_sa_wps_file(db, organization.id, run.id)
    second = svc.build_sa_wps_file(db, organization.id, run.id)
    assert first["file"].id == second["file"].id
    assert first["file"].employee_count == 1
    assert first["file"].total_amount == Decimal("8000")
    assert len(svc.list_sa_wps_files(db, organization.id)) == 1


def test_wps_records_observation_for_missing_iban(db, organization):
    run = _run(db, organization)
    emp = _employee(db, organization)
    _payslip(db, organization, run, emp, net="8000")

    out = svc.build_sa_wps_file(db, organization.id, run.id)
    codes = {o["code"] for o in out["observations"]}
    assert svc.SA_WPS_OBSERVATION_MISSING_BANK in codes
    obs = svc.list_sa_wps_observations(db, organization.id, out["file"].id)
    assert len(obs) == 1 and obs[0].observation_code == svc.SA_WPS_OBSERVATION_MISSING_BANK
