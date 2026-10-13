"""Netherlands (ZP-NL-ENG-001 Phases 5–7) end to end through the real payroll service.

The engine tests prove the arithmetic; these prove the WIRING: the NL canonical
pack feeding rate_map/slabs, resolve_nl_calc_inputs feeding the engine, the
payslip snapshot, a non-mutating preview, the approval preflight + fingerprint,
the COMMIT of the VCR / vacation / WKR ledgers exactly once, the recalculation
lock after commit, the 13 platform hooks, and the Phase 6/7 records.

In-memory SQLite only (the `db` fixture). The wage-tax rows are a SYNTHETIC
plumbing fixture (the official 2026 tables are gate G1); every other figure is
the spec's own 2026 content (netherlands_content.py).
"""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from app.modules.payroll import jurisdiction_hooks, netherlands_service as nl, service
from app.modules.payroll.engine.countries.netherlands_content import (
    NL_CAR_ADDITION_BANDS, NL_MIN_WAGE_RATES, NL_PERIOD_MAXIMA, NL_SCALAR_CONTENT, NL_WKR_BANDS,
)
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.models import (
    CompanyComplianceDetails, ContributionRate, EmployeeStatutoryProfile, JurisdictionPack, PayrollEmployee,
    PayrollNlContractVersion, PayrollNlEmployerProfile, PayrollNlTaxCreditInstruction, PayrollNlTaxTableFile,
    PayrollNlTaxTableRow, PayrollNlVacationAllowanceLedger, PayrollNlVcrSnapshot, PayrollNlWkrAccumulator,
    PayrollRun, PayrollStatus, PayslipItem, TaxSlab,
)

PREPARER, APPROVER, AUTHORIZER = 801, 802, 803


def _stub_codes(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _pack(db):
    pack = JurisdictionPack(pack_id="NL-PAYROLL-TEST", jurisdiction_country="NL", version="1.0", pack_type="tax",
                            status="Active", effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    db.add(pack)
    db.flush()
    for key, label, ee, er, flat, text, _src, _g1 in NL_SCALAR_CONTENT:
        db.add(ContributionRate(jurisdiction_pack_id=pack.id, jurisdiction_country="NL", organization_id=None,
                                component_key=key, label=label[:100], employee_share="-", employer_share="-", total="-",
                                employee_rate_pct=D(ee) if ee else None, employer_rate_pct=D(er) if er else None,
                                flat_amount=D(flat) if flat else None, text_value=text))
    order = 0

    def slab(rule, key, *, rate="0", lo="0", hi=None, amount=None, eff_from=None, eff_to=None):
        nonlocal order
        order += 1
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, jurisdiction_country="NL", organization_id=None, rule_type=rule,
                       filing_status=key, min_amount=D(lo), max_amount=D(hi) if hi else None, rate_pct=D(rate),
                       flat_amount=D(amount) if amount else None, rate_label=f"TEST {rule} {key}", tax_formula="-",
                       effective_from=eff_from, effective_to=eff_to, sort_order=order))

    for cohort, amount, eff_from, eff_to, _s, _g in NL_MIN_WAGE_RATES:
        slab("NL_MIN_WAGE", cohort, amount=amount, eff_from=eff_from, eff_to=eff_to)
    for code, amount, _s, _g in NL_PERIOD_MAXIMA:
        slab("NL_PERIOD_MAX", code, amount=amount)
    for kind, lo, hi, rate, _s, _g in NL_WKR_BANDS:
        slab("NL_WKR_BAND", kind, lo=lo, hi=hi, rate=rate)
    for car_class, rate, eff_from, eff_to, _s, _g in NL_CAR_ADDITION_BANDS:
        slab("NL_CAR_ADDITION", car_class, rate=rate, eff_from=eff_from, eff_to=eff_to)
    db.flush()
    return pack


def _table(db, pack):
    """SYNTHETIC plumbing table (monthly WHITE/NL): €1,325.08 from €5,000 with
    the credit = the spec's F1 published result; NOT the official table."""
    f = PayrollNlTaxTableFile(jurisdiction_pack_id=pack.id, tax_year=2026, table_color="WHITE", table_kind="PERIOD",
                              period="MONTH", residence_variant="NL", source_filename="SYNTHETIC.csv",
                              file_sha256="c" * 64, row_count=3, status="ACTIVE", effective_from=date(2026, 1, 1))
    db.add(f)
    db.flush()
    for n, (lo, hi, credit, amount) in enumerate([("0", "5000", True, "1000.00"), ("5000", None, True, "1325.08"),
                                                  ("0", None, False, "1900.00")], start=1):
        db.add(PayrollNlTaxTableRow(file_id=f.id, row_no=n, wage_from=D(lo), wage_to=D(hi) if hi else None,
                                    aow_cohort="BELOW_AOW", with_tax_credit=credit, withholding_amount=D(amount),
                                    row_sha256=f"{n:064d}"))
    db.flush()
    return f


@pytest.fixture()
def nlx(db, organization, monkeypatch):
    _stub_codes(monkeypatch)
    org = organization
    pack = _pack(db)
    table = _table(db, pack)
    db.add(CompanyComplianceDetails(organization_id=org.id, jurisdiction_country="Netherlands", active_pack_id=pack.id))
    db.add(PayrollNlEmployerProfile(organization_id=org.id, effective_from=date(2026, 1, 1), legal_name="TEST BV",
                                    loonheffingennummer="123456789L01", registration_verified_at=date(2026, 1, 2),
                                    cao_status="NONE"))
    emp = PayrollEmployee(organization_id=org.id, employee_code="NL-001", name="Test Werknemer", country_code="NL",
                          ctc=D("60000"), basic=D("60000"), hra=D("0"), date_of_birth=date(1990, 5, 15),
                          date_of_joining=date(2025, 1, 1), pay_frequency="Monthly",
                          compliance_fields={"bsn": "111222333"})
    db.add(emp)
    db.flush()
    db.add(EmployeeStatutoryProfile(employee_id=emp.id, organization_id=org.id, country_code="NL",
                                    effective_from=date(2026, 1, 1), nl_table_color="WHITE", nl_residence_variant="NL",
                                    nl_zvw_path="EMPLOYER_LEVY", nl_ei_insured=True, nl_cross_border_status="NONE",
                                    nl_contract_hours_per_week=D("40"), nl_bsn_verified_at=date(2026, 1, 2)))
    db.add(PayrollNlTaxCreditInstruction(organization_id=org.id, employee_id=emp.id, apply_tax_credit=True,
                                         signed_at=date(2025, 12, 20), effective_from=date(2026, 1, 1)))
    db.add(PayrollNlContractVersion(organization_id=org.id, employee_id=emp.id, version=1, contract_term="INDEFINITE",
                                    written_record=True, on_call=False, start_date=date(2025, 1, 1),
                                    effective_from=date(2025, 1, 1)))
    decision = nl.create_premium_decision(db, organization_id=org.id, tax_year=2026, aof_size_class="SMALL",
                                          aof_basis_year=2024, aof_basis_premium_wage=D("500000"),
                                          decision_reference="BD-WHK-TEST", decision_date=date(2025, 11, 1),
                                          effective_from=date(2026, 1, 1), actor_id=PREPARER,
                                          whk_wga_pct=D("0.5000"), whk_zw_flex_pct=D("0.2000"))
    nl.activate_premium_decision(db, decision.id, org.id, actor_id=APPROVER)
    nl.create_earning_classification(db, organization_id=None, earning_code="base_salary",
                                     effective_from=date(2026, 1, 1), remuneration_type="REGULAR", wage_tax=True,
                                     employee_insurance_wage=True, zvw_wage=True, pensionable=True,
                                     wkr_treatment="WAGE", vacation_allowance_basis=True, minimum_wage_reckonable=True)
    db.commit()
    return SimpleNamespace(org=org, emp=emp, pack=pack, table=table, decision=decision)


def _run(db, org, month, created_by=PREPARER):
    end = date(2026, month, 30 if month in (4, 6, 9, 11) else 31)
    run = PayrollRun(organization_id=org.id, period_label=f"2026-{month:02d}", period_start=date(2026, month, 1),
                     period_end=end, pay_date=end, created_by=created_by,
                     attendance_override_reason="TEST synthetic run - no attendance records")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _item(db, run, emp):
    return db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()


def _approve(db, run, org):
    service.advance_payroll_run_status(db, run.id, PREPARER, org.id)   # Draft -> Review
    service.advance_payroll_run_status(db, run.id, APPROVER, org.id)   # Review -> Approved
    db.refresh(run)
    return run


# ── generation and snapshot ────────────────────────────────────────────────

def test_generation_writes_the_snapshot_and_keeps_employer_cost_out_of_net(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    item = _item(db, run, nlx.emp)
    snap = item.nl_calculation_snapshot
    assert item.country_code == "NL" and snap is not None
    assert D(str(item.gross_pay)) == D("5000.00")
    assert snap["wageTax"]["total"] == "1325.08"
    assert snap["employeeInsurance"] == {**snap["employeeInsurance"], "awf": "137.00", "aof": "313.50", "wko": "25.00",
                                         "awfClass": "LOW"}
    assert snap["zvw"]["employerLevy"] == "305.00"
    assert D(str(item.net_pay)) == D("3674.92")           # employer premiums never reduce net (NL-035)
    assert snap["inputs"]["wageTaxTable"]["fileId"] == nlx.table.id
    assert snap["vcr"]["after"]["EI"]["revision"] == 1


def test_preview_and_generation_never_commit_ledgers(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    assert db.query(PayrollNlVcrSnapshot).count() == 0     # NL-033: only COMMIT writes the series
    assert db.query(PayrollNlVacationAllowanceLedger).count() == 0


def test_serialised_payslip_exposes_the_snapshot(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    from app.modules.payroll.schemas import PayslipItemResponse
    data = PayslipItemResponse.model_validate(service._serialize_payslip(_item(db, run, nlx.emp), run, "NL")).model_dump()
    assert data["nlCalculationSnapshot"]["totals"]["netPay"] == "3674.92"


# ── approval, commit, lock ─────────────────────────────────────────────────

def test_approval_commits_the_ledgers_exactly_once(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    _approve(db, run, nlx.org)
    assert run.status == PayrollStatus.APPROVED
    assert run.nl_approval_fingerprint["fingerprint"]
    ei = db.query(PayrollNlVcrSnapshot).filter_by(family="EI").one()
    assert (ei.revision, ei.cumulative_base, ei.base_increment) == (1, D("5000.00"), D("5000.00"))
    assert db.query(PayrollNlVcrSnapshot).filter_by(family="ZVW_LEVY").count() == 1
    vac = db.query(PayrollNlVacationAllowanceLedger).one()
    assert (vac.entry_type, vac.amount, vac.balance_after) == ("ACCRUAL", D("400.00"), D("400.00"))  # 8 % of 5000
    wkr = db.query(PayrollNlWkrAccumulator).one()
    assert wkr.fiscal_wage_cumulative == D("5000.00") and wkr.free_space_available == D("100.00")   # 2 % of 5000
    assert nl.nl_commit_run(db, run)["alreadyCommitted"] is True                                    # idempotent


def test_next_month_reads_the_committed_series(db, nlx):
    march = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, march, nlx.org.id)
    _approve(db, march, nlx.org)
    april = _run(db, nlx.org, 4)
    service.generate_payslips_for_run(db, april, nlx.org.id)
    snap = _item(db, april, nlx.emp).nl_calculation_snapshot
    assert snap["vcr"]["before"]["EI"]["revision"] == 1
    assert snap["vcr"]["after"]["EI"]["revision"] == 2
    assert snap["vacationAllowance"]["priorBalance"] == "400.00"


def test_committed_run_is_locked_against_recalculation(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    _approve(db, run, nlx.org)
    with pytest.raises(HTTPException) as exc:
        jurisdiction_hooks.call("NL", "calc_inputs", db, run, nlx.emp, None)
    assert exc.value.status_code == 409 and "correction" in exc.value.detail


def test_stale_vcr_blocks_approval(db, nlx):
    a = _run(db, nlx.org, 3)
    b = _run(db, nlx.org, 4)
    service.generate_payslips_for_run(db, a, nlx.org.id)
    service.generate_payslips_for_run(db, b, nlx.org.id)          # both calculated on revision 0
    _approve(db, a, nlx.org)
    service.advance_payroll_run_status(db, b.id, PREPARER, nlx.org.id)
    with pytest.raises(HTTPException) as exc:
        service.advance_payroll_run_status(db, b.id, APPROVER, nlx.org.id)
    assert exc.value.status_code == 409 and "vcr_stale" in exc.value.detail


def test_cao_unknown_blocks_approval(db, nlx):
    db.query(PayrollNlEmployerProfile).update({"cao_status": "UNKNOWN"})
    db.commit()
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    service.advance_payroll_run_status(db, run.id, PREPARER, nlx.org.id)
    with pytest.raises(HTTPException) as exc:
        service.advance_payroll_run_status(db, run.id, APPROVER, nlx.org.id)
    assert "cao_status" in exc.value.detail


# ── fail-closed surfacing ─────────────────────────────────────────────────

def test_missing_premium_decision_fails_the_payslip_closed(db, nlx):
    db.query(nl.PayrollNlEmployerPremiumDecision).update({"status": "SUPERSEDED"})
    db.commit()
    run = _run(db, nlx.org, 3)
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        service.generate_payslips_for_run(db, run, nlx.org.id)
    assert exc.value.key == "nl_premium_decision"


def test_missing_bsn_uses_the_anonymous_rate(db, nlx):
    nlx.emp.compliance_fields = {}
    db.commit()
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    snap = _item(db, run, nlx.emp).nl_calculation_snapshot
    assert snap["wageTax"]["total"] == "2600.00" and snap["wageTax"]["anonymous"] is True


# ── hooks, Phase 6/7 records ──────────────────────────────────────────────

def test_every_platform_hook_is_registered():
    names = ("retention_settings", "service_registry_transition", "statutory_summary", "pack_activation_refusal",
             "statutory_editors", "template_activation_refusal", "calc_inputs", "payment_treatment",
             "before_run_transition", "pack_holidays", "statutory_profile_errors", "statutory_profile_values",
             "payslip_hold_view")
    for name in names:
        assert callable(jurisdiction_hooks.get("NL", name)), name
    assert jurisdiction_hooks.call("NL", "retention_settings").country == "NL"


def test_statutory_summary_reports_open_gates(db):
    summary = jurisdiction_hooks.call("NL", "statutory_summary", db)
    assert [g["gate"] for g in summary["gates"]] == [f"G{i}" for i in range(1, 9)]
    assert all(g["state"] == "OPEN" for g in summary["gates"]) and summary["available"] is False


def test_profile_errors_validate_vocabulary():
    errors = nl._nl_statutory_profile_errors(SimpleNamespace(nl_zvw_path="employer", nl_table_color="WHITE",
                                                             nl_cross_border_status=None,
                                                             nl_vacation_allowance_pct=None,
                                                             nl_voluntary_extra_withholding=D("-1"),
                                                             nl_contract_hours_per_week=None))
    assert any("nl_zvw_path" in e for e in errors) and any("only ADD" in e for e in errors)


def test_premium_decision_four_eyes(db, nlx):
    d = nl.create_premium_decision(db, organization_id=nlx.org.id, tax_year=2026, aof_size_class="LARGE",
                                   aof_basis_year=2024, aof_basis_premium_wage=D("1"), decision_reference="X",
                                   decision_date=date(2026, 1, 1), effective_from=date(2026, 7, 1), actor_id=PREPARER,
                                   whk_wga_pct=D("1"), whk_zw_flex_pct=D("1"))
    with pytest.raises(BadRequestException, match="four-eyes"):
        nl.activate_premium_decision(db, d.id, nlx.org.id, actor_id=PREPARER)


def test_awf_derivation_matches_the_engine_rule():
    assert nl._derive_awf_class("INDEFINITE", True, False, None, None)[0] == "LOW"
    assert nl._derive_awf_class("FIXED", True, False, D("40"), None)[0] == "HIGH"
    assert nl._derive_awf_class("FIXED", True, False, D("40"), "BBL")[0] == "LOW"
    assert nl._derive_awf_class("INDEFINITE", True, True, None, None)[0] == "HIGH"


def test_termination_settlement_transition_payment_and_four_eyes(db, nlx):
    s = nl.prepare_termination_settlement(
        db, organization_id=nlx.org.id, employee_id=nlx.emp.id, termination_date=date(2026, 9, 30),
        reason="redundancy", initiated_by="EMPLOYER", service_months=60, monthly_salary=D("5000"),
        annual_salary=D("60000"), unused_leave_hours=D("16"), hourly_wage=D("28.85"), actor_id=PREPARER)
    assert s.transition_payment_amount == D("8333.33")                # 5000 x 1/3 x 5 years
    assert s.leave_payout == D("461.60") and s.status == "DRAFT"
    with pytest.raises(BadRequestException, match="four-eyes"):
        nl.approve_termination_settlement(db, s.id, nlx.org.id, actor_id=PREPARER)
    assert nl.approve_termination_settlement(db, s.id, nlx.org.id, actor_id=APPROVER).status == "APPROVED"
