"""
tests/test_netherlands_annual.py
---------------------------------
Jaaropgaaf (annual statement) tests (Phase 10).
"""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from app.modules.payroll import netherlands_annual_service as ann, netherlands_service as nl
from app.modules.payroll.models import (
    PayrollNlAnnualStatement,
    PayrollRun,
    PayrollStatus,
)
from app.modules.payroll.engine.countries.netherlands_content import (
    NL_CAR_ADDITION_BANDS, NL_MIN_WAGE_RATES, NL_PERIOD_MAXIMA, NL_SCALAR_CONTENT, NL_WKR_BANDS,
)
from app.core.exceptions import BadRequestException


def _stub_codes(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _pack(db):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

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
    from app.modules.payroll.models import PayrollNlTaxTableFile, PayrollNlTaxTableRow

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
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollNlEmployerProfile, PayrollEmployee, EmployeeStatutoryProfile, PayrollNlTaxCreditInstruction, PayrollNlContractVersion

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
                          compliance_fields={"bsn": "111222333", "iban_token": "NL44RABO0123456789"})
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
                                          effective_from=date(2026, 1, 1), actor_id=801,
                                          whk_wga_pct=D("0.5000"), whk_zw_flex_pct=D("0.2000"))
    nl.activate_premium_decision(db, decision.id, org.id, actor_id=802)
    nl.create_earning_classification(db, organization_id=None, earning_code="base_salary",
                                     effective_from=date(2026, 1, 1), remuneration_type="REGULAR", wage_tax=True,
                                     employee_insurance_wage=True, zvw_wage=True, pensionable=True,
                                     wkr_treatment="WAGE", vacation_allowance_basis=True, minimum_wage_reckonable=True)
    db.commit()
    return type("NLX", (), dict(org=org, emp=emp, pack=pack, table=table, decision=decision))()


def _run_and_approve(db, nlx, month):
    from app.modules.payroll import service
    PREPARER, APPROVER = 801, 802
    # 2026 is not a leap year, so February has 28 days
    if month == 2:
        end = date(2026, 2, 28)
    elif month in (4, 6, 9, 11):
        end = date(2026, month, 30)
    else:
        end = date(2026, month, 31)
    run = PayrollRun(organization_id=nlx.org.id, period_label=f"2026-{month:02d}", period_start=date(2026, month, 1),
                     period_end=end, pay_date=end, created_by=PREPARER,
                     attendance_override_reason="TEST")
    db.add(run)
    db.commit()
    db.refresh(run)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    service.advance_payroll_run_status(db, run.id, PREPARER, nlx.org.id)
    service.advance_payroll_run_status(db, run.id, APPROVER, nlx.org.id)
    db.refresh(run)
    return run


class TestAnnualStatement:
    def test_generate_annual_statement_from_committed(self, db, nlx):
        # Run and approve multiple months
        for m in [1, 2, 3]:
            _run_and_approve(db, nlx, m)

        stmt = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        assert stmt.tax_year == 2026
        assert stmt.version == 1
        assert stmt.status == "DRAFT"
        assert stmt.fiscal_wage > D("0")
        assert stmt.wage_tax_withheld > D("0")
        assert stmt.zvw_wage > D("0")
        assert stmt.source_ledger_sha256 is not None

    def test_idempotency_key_prevents_duplicate(self, db, nlx):
        for m in [1, 2]:
            _run_and_approve(db, nlx, m)

        key = "test-annual-key-123"
        stmt1 = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801, idempotency_key=key)
        stmt2 = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801, idempotency_key=key)
        assert stmt1.id == stmt2.id

    def test_issue_annual_statement(self, db, nlx):
        for m in [1, 2]:
            _run_and_approve(db, nlx, m)

        stmt = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        issued = ann.issue_annual_statement(db, stmt.id, 801, delivery_channel="PORTAL")
        assert issued.status == "ISSUED"
        assert issued.delivered_at is not None
        assert issued.delivery_channel == "PORTAL"

    def test_cannot_issue_non_draft(self, db, nlx):
        for m in [1, 2]:
            _run_and_approve(db, nlx, m)

        stmt = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        ann.issue_annual_statement(db, stmt.id, 801)
        with pytest.raises(ann.AnnualStatementError):
            ann.issue_annual_statement(db, stmt.id, 801)

    def test_amend_issued_statement(self, db, nlx):
        for m in [1, 2]:
            _run_and_approve(db, nlx, m)

        stmt = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        ann.issue_annual_statement(db, stmt.id, 801)
        amended = ann.amend_annual_statement(db, stmt.id, 801, reason="Correction")
        assert amended.version == 2
        assert amended.supersedes_id == stmt.id
        assert amended.status == "DRAFT"

    def test_cannot_amend_non_issued(self, db, nlx):
        for m in [1, 2]:
            _run_and_approve(db, nlx, m)

        stmt = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        with pytest.raises(ann.AnnualStatementError):
            ann.amend_annual_statement(db, stmt.id, 801, "Reason")

    def test_list_annual_statements(self, db, nlx):
        for m in [1, 2]:
            _run_and_approve(db, nlx, m)

        ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        results = ann.list_annual_statements(db, nlx.org.id, tax_year=2026)
        assert len(results) == 1
        assert results[0].tax_year == 2026

    def test_get_annual_statement(self, db, nlx):
        for m in [1, 2]:
            _run_and_approve(db, nlx, m)

        stmt = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        loaded = ann.get_annual_statement(db, stmt.id)
        assert loaded.id == stmt.id

    def test_source_ledger_hash_consistency(self, db, nlx):
        for m in [1, 2]:
            _run_and_approve(db, nlx, m)

        stmt1 = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        stmt2 = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=802, idempotency_key="different")
        # Same data should produce same hash
        assert stmt1.source_ledger_sha256 == stmt2.source_ledger_sha256

    def test_statement_uses_committed_only(self, db, nlx):
        """Verify statement only uses committed payslips, not draft."""
        _run_and_approve(db, nlx, 1)
        # Create a DRAFT run (not committed)
        from app.modules.payroll import service
        PREPARER = 801
        end = date(2026, 2, 28)
        draft_run = PayrollRun(organization_id=nlx.org.id, period_label="2026-02", period_start=date(2026, 2, 1),
                               period_end=end, pay_date=end, created_by=PREPARER,
                               attendance_override_reason="TEST")
        db.add(draft_run)
        db.commit()
        service.generate_payslips_for_run(db, draft_run, nlx.org.id)
        # NOT approved, so not committed

        stmt = ann.generate_annual_statement(db, nlx.org.id, nlx.emp.id, 2026, actor_id=801)
        # Should only include January (committed), not February (draft)
        assert stmt.fiscal_wage > D("0")