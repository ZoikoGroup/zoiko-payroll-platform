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
import json
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
    "sa_gosi_due_day": (Decimal("15"), None),
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
                   oh_er="200", contributory="10000", month="2026-03"):
    """The engine's real stored shape: saudi_arabia.calculate()["sa_result"],
    persisted as PayslipItem.sa_calculation_snapshot."""
    return {
        "sa_worker_class": "SAUDI", "sa_cohort": "NEW", "sa_contribution_month": month,
        "sa_contributory_wage": contributory,
        "employee_pension": pension_ee, "employer_pension": pension_er,
        "social_security": saned_ee, "employer_social_security": saned_er,
        "employer_occupational_hazard": oh_er,
        "branches": [], "labour": {}, "trace": {},
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


def test_gosi_liability_reads_the_real_engine_snapshot():
    """Regression: the ledger read a {"gosi": ...} shape that no real run
    stores, so every real liability was 0."""
    stored_keys = {"employee_pension", "employer_pension", "social_security", "employer_social_security",
                   "employer_occupational_hazard", "sa_contributory_wage", "sa_contribution_month"}
    assert stored_keys <= set(_gosi_snapshot())
    totals = svc._gosi_snapshot_totals(_gosi_snapshot())
    assert totals["pension_employee"] == Decimal("950") and totals["oh_employer"] == Decimal("200")
    assert svc._gosi_snapshot_totals({"gosi": {"employeePension": "1"}}) is None


def test_gosi_liability_sums_every_run_in_the_month(db, organization):
    first = _run(db, organization)
    second = _run(db, organization)
    _payslip(db, organization, first, _employee(db, organization), gross="10000")
    _payslip(db, organization, second, _employee(db, organization, code="E2"), gross="5000",
             snapshot=_gosi_snapshot(pension_ee="475", pension_er="475", saned_ee="37.50",
                                     saned_er="37.50", oh_er="100", contributory="5000"))

    svc.build_sa_gosi_liability(db, organization.id, first.id)
    row = svc.build_sa_gosi_liability(db, organization.id, second.id)
    assert row.pension_employee == Decimal("1425")
    assert row.contributory_wages == Decimal("15000")
    assert row.total_wages == Decimal("15000")
    assert len(svc.list_sa_gosi_liabilities(db, organization.id)) == 1


def test_gosi_liability_due_date_comes_from_the_pack(db, organization):
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    assert svc.build_sa_gosi_liability(db, organization.id, run.id).due_date is None   # no pack, no guess
    _pack(db)
    assert svc.build_sa_gosi_liability(db, organization.id, run.id).due_date == date(2026, 4, 15)


def test_gosi_liability_paid_month_is_not_rebuilt(db, organization):
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    row = svc.build_sa_gosi_liability(db, organization.id, run.id)
    svc.mark_sa_gosi_liability_paid(db, organization.id, row.id, payment_reference="PAY-1")
    with pytest.raises(Exception):
        svc.build_sa_gosi_liability(db, organization.id, run.id)


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


# ── Corrections: freeze -> replay -> delta (SA-043, regression) ──────────────
def _f2_ctx():
    """A real Saudi engine context: golden case F2 (SAUDI / NEW, SAR 20,000, Jun 2026)."""
    import json
    from pathlib import Path

    from app.modules.payroll.hmrc_golden_harness import build_context

    case = json.loads((Path(__file__).resolve().parent / "fixtures" / "sa_golden"
                       / "f2_saudi_new_20000_jun2026.json").read_text(encoding="utf-8"))
    return build_context(case["context"])


def _f2_payslip(db, organization):
    from app.modules.payroll.engine.resolver import calculate_payroll

    ctx = _f2_ctx()
    frozen = svc.sa_freeze_context(ctx)
    result = calculate_payroll(ctx, "standard")
    run = _run(db, organization, start=date(2026, 6, 1), end=date(2026, 6, 30))
    snapshot = svc.sa_payslip_snapshot(result, frozen=frozen)
    return run, _payslip(db, organization, run, _employee(db, organization), gross="20000", snapshot=snapshot), result


def test_frozen_context_replays_the_original_exactly():
    from app.modules.payroll.engine.resolver import calculate_payroll

    ctx = _f2_ctx()
    frozen = json.loads(json.dumps(svc.sa_freeze_context(ctx)))          # survives a JSON round trip
    original = calculate_payroll(ctx, "standard")
    assert svc.sa_totals_all(svc.sa_replay(frozen)) == svc.sa_totals_all(original)
    assert svc.sa_totals_all(original)["employee_pension"] == "1900.00"   # F2: 9.5% of 20,000


def test_payslip_snapshot_keeps_the_flat_result_and_adds_the_frozen_context(db, organization):
    _run_, item, result = _f2_payslip(db, organization)
    snap = item.sa_calculation_snapshot
    assert snap["employee_pension"] == result.sa_result["employee_pension"]   # GOSI ledger still reads it
    assert snap["frozenContext"]["ctx"]["pay_date"] and snap["frozenContext"]["rateMap"]
    assert snap["totalsAll"] == svc.sa_totals_all(result)


def test_correction_books_the_delta_on_a_new_payslip(db, organization):
    run, item, _result = _f2_payslip(db, organization)
    out = svc.create_sa_correction(db, organization.id, item.id, "Registered wage was 15,000",
                                   ["employee_pension", "employer_pension", "social_security",
                                    "employer_social_security", "employer_occupational_hazard"],
                                   {"contributoryWage": "15000"}, actor_id=7)
    assert Decimal(out["deltas"]["employee_pension"]) == Decimal("-475.00")   # 9.5% of -5,000
    delta = db.get(PayslipItem, out["payslipId"])
    assert delta.sa_calculation_snapshot["correction"]["originalPayslipId"] == item.id
    assert delta.total_deductions == Decimal(out["deltas"]["employee_pension"]) + Decimal(out["deltas"]["social_security"])
    assert delta.employee_pension == Decimal(out["deltas"]["employee_pension"])
    assert [c["payslipId"] for c in svc.list_sa_corrections(db, organization.id, item.id)] == [delta.id]

    # A second correction restates on the latest basis: back to 20,000 reverses it.
    again = svc.create_sa_correction(db, organization.id, item.id, "Revert", sorted(svc.SA_CORRECTION_OBLIGATIONS),
                                     {"contributoryWage": "20000"}, actor_id=7)
    assert Decimal(again["deltas"]["employee_pension"]) == Decimal("475.00")


def test_correction_refuses_undeclared_obligations(db, organization):
    _run_, item, _result = _f2_payslip(db, organization)
    with pytest.raises(Exception, match="does not declare"):
        svc.create_sa_correction(db, organization.id, item.id, "x", ["employee_pension"],
                                 {"contributoryWage": "15000"}, actor_id=7)


def test_correction_refuses_no_change(db, organization):
    _run_, item, _result = _f2_payslip(db, organization)
    with pytest.raises(Exception, match="no change"):
        svc.create_sa_correction(db, organization.id, item.id, "x", ["employee_pension"], {}, actor_id=7)


def test_correction_preview_returns_json_deltas(db, organization):
    _run_, item, _result = _f2_payslip(db, organization)
    frozen = svc._apply_sa_corrected_inputs(db, item.sa_calculation_snapshot["frozenContext"],
                                            {"contributoryWage": "15000"}, organization.id)
    preview = svc.sa_replay(frozen, baseline_totals=item.sa_calculation_snapshot["totalsAll"])
    json.dumps(preview)
    assert Decimal(preview["deltas"]["employee_pension"]) == Decimal("-475.00")


# ── SA-E1: preflight / readiness see the GOSI branches of the real pack ──────
def test_gosi_branches_of_the_seeded_pack_are_found():
    from types import SimpleNamespace

    from app.modules.payroll.engine.countries import saudi_arabia_content as content

    slabs = [SimpleNamespace(rule_type="SA_GOSI_BRANCH", tax_regime=branch)
             for (_cls, branch, *_rest) in content.SA_GOSI_BRANCHES]
    assert svc._missing_gosi_branches(slabs) == []
    assert svc._missing_gosi_branches([s for s in slabs if s.tax_regime != "SANED"]) == ["SANED"]


def test_run_preflight_no_longer_blocks_on_gosi_branches(db, organization):
    pack = svc.seed_saudi_arabia_pack(db)
    pack.status = "Active"
    db.flush()
    run = _run(db, organization)
    _payslip(db, organization, run, _employee(db, organization))
    keys = {b.get("key") for b in svc.sa_run_preflight(db, run)}
    assert "SA_PACK_NOT_ACTIVE" not in keys                            # the pack WAS found, so the check ran
    assert "SA_GOSI_BRANCHES_MISSING" not in keys                      # was raised for every pack


# ── SA-E3: four-eyes compares the approver with the CREATOR ──────────────────
def test_creator_cannot_approve_their_own_employer_profile_or_contract(db, organization):
    profile = svc.create_sa_employer_profile(db, organization.id, {
        "effectiveFrom": "2026-01-01", "gosiEmployerCode": "GOSI-1"}, actor_id=7)
    with pytest.raises(Exception, match="four-eyes"):
        svc.approve_sa_employer_profile(db, organization.id, profile.id, actor_id=7)
    assert svc.approve_sa_employer_profile(db, organization.id, profile.id, actor_id=8).status == "APPROVED"

    emp = _employee(db, organization)
    contract = svc.create_sa_contract_version(db, organization.id, emp.id, {
        "effectiveFrom": "2026-01-01", "contractType": "LIMITED", "basicWage": "9000"}, actor_id=7)
    with pytest.raises(Exception, match="four-eyes"):
        svc.approve_sa_contract_version(db, organization.id, emp.id, contract.id, actor_id=7)
    with pytest.raises(Exception, match="four-eyes"):
        svc.approve_sa_contract_version(db, organization.id, emp.id, contract.id, actor_id=None)


# ── SA-E2: the approval fingerprint binds payslips AND current master data ───
def test_approval_fingerprint_is_stable_stored_and_detects_drift(db, organization):
    from app.modules.payroll.models import EmployeeStatutoryProfile

    run, item, _result = _f2_payslip(db, organization)
    first = svc.sa_approval_fingerprint(db, run)                      # raised KeyError before
    assert first == svc.sa_approval_fingerprint(db, run)               # deterministic
    svc.sa_approval_fingerprint(db, run, store=True)
    assert svc.sa_stored_approval(db, run)["fingerprint"] == first["fingerprint"]   # read where written

    # master data changed after the calculation -> drift
    db.add(EmployeeStatutoryProfile(employee_id=item.employee_id, organization_id=organization.id, country_code="SA",
                                    effective_from=date(2026, 1, 1), sa_worker_class="SAUDI", sa_cohort="LEGACY"))
    db.flush()
    assert svc.sa_approval_fingerprint(db, run)["fingerprint"] != first["fingerprint"]


def test_approval_fingerprint_changes_with_the_payslip(db, organization):
    run, item, _result = _f2_payslip(db, organization)
    first = svc.sa_approval_fingerprint(db, run)["fingerprint"]
    item.net_pay = item.net_pay + 1
    db.flush()
    assert svc.sa_approval_fingerprint(db, run)["fingerprint"] != first
