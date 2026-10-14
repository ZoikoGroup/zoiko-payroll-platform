"""
tests/test_netherlands_loonaangifte.py
---------------------------------------
Loonaangifte return builder (Phase 9) — end-to-end through the real
filing service. Uses the same synthetic wage-tax table plumbing as
test_netherlands_service_integration.py.
"""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from app.modules.payroll import netherlands_filing_service as filings, netherlands_service as nl
from app.modules.payroll.models import (
    PayrollNlAuthorityPayment,
    PayrollNlDigipoortSubmission,
    PayrollNlEmployerProfile,
    PayrollNlLoonaangifteLine,
    PayrollNlLoonaangifteReturn,
    PayrollRun,
    PayrollStatus,
    PayslipItem,
)
from app.modules.payroll.engine.countries.netherlands_content import (
    NL_CAR_ADDITION_BANDS, NL_MIN_WAGE_RATES, NL_PERIOD_MAXIMA, NL_SCALAR_CONTENT, NL_WKR_BANDS,
)
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
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
    """SYNTHETIC plumbing table — same as service integration tests."""
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
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollNlEmployerProfile, PayrollEmployee, EmployeeStatutoryProfile, PayrollNlTaxCreditInstruction, PayrollNlContractVersion
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
    end = date(2026, month, 30 if month in (4, 6, 9, 11) else 31)
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


class TestLoonaangifteReturnBuilder:
    def test_build_regular_return_from_committed_payslip(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        assert ret.status == "READY"
        assert ret.return_type == "REGULAR"
        assert ret.tax_year == 2026
        assert ret.period_code == "202603"
        assert ret.total_payable > D("0")
        assert ret.total_wage_tax == D("1325.08")
        assert ret.total_awf == D("137.00")
        assert ret.total_aof == D("313.50")
        assert ret.total_wko == D("25.00")
        assert ret.total_zvw_employer == D("305.00")
        assert ret.total_whk == D("35.00")          # employer Whk premium (WGA + ZW-flex) on 5000
        assert ret.total_final_levies == D("0")

    def test_build_nil_return(self, db, nlx):
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202601", return_type="NIL", actor_id=801)
        assert ret.return_type == "NIL"
        assert ret.total_payable == D("0")
        assert ret.total_wage_tax == D("0")
        assert ret.status == "READY"

    def test_build_zero_return(self, db, nlx):
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202602", return_type="ZERO", actor_id=801)
        assert ret.return_type == "ZERO"
        assert ret.total_payable == D("0")
        assert ret.status == "READY"

    def test_idempotency_key_prevents_duplicate(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        key = "test-idempotency-key-123"
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret1 = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801,
            idempotency_key=key)
        ret2 = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801,
            idempotency_key=key)
        assert ret1.id == ret2.id

    def test_lines_created_for_regular_return(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        lines = db.query(PayrollNlLoonaangifteLine).filter(
            PayrollNlLoonaangifteLine.return_id == ret.id).all()
        assert len(lines) == 1
        line = lines[0]
        assert line.personnel_number == "NL-001"
        assert line.line_type == "ORIGINAL"
        assert line.wage_tax == D("1325.08")
        assert line.awf_class == "LOW"
        assert line.line_sha256 is not None

    def test_no_lines_for_nil_zero(self, db, nlx):
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202601", return_type="NIL", actor_id=801)
        lines = db.query(PayrollNlLoonaangifteLine).filter(
            PayrollNlLoonaangifteLine.return_id == ret.id).all()
        assert len(lines) == 0

    def test_correction_chain(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        original = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        correction = filings.create_correction_return(db, original.id, actor_id=801)
        assert correction.return_type == "CORRECTION"
        assert correction.correction_of_id == original.id
        assert correction.version == 2
        assert original.status == "CORRECTED"

    def test_reconcile_clean(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        report = filings.reconcile_return(db, ret.id, 801)
        assert report["status"] == "RECONCILED"
        assert ret.journal_reconciled is True

    def test_reconcile_fails_on_mismatch(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        # Tamper with the total
        ret.total_wage_tax = D("9999.99")
        db.flush()
        with pytest.raises(filings.ReconciliationError):
            filings.reconcile_return(db, ret.id, 801)

    def test_mark_filed_requires_reconciled(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        with pytest.raises(filings.FilingError):
            filings.mark_filed(db, ret.id, 801)
        filings.reconcile_return(db, ret.id, 801)
        filed = filings.mark_filed(db, ret.id, 801, digipoort_reference="DIGI-123")
        assert filed.status == "FILED"

    def test_mark_accepted_separate_from_transport(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)
        filings.mark_filed(db, ret.id, 801)
        accepted = filings.mark_accepted(db, ret.id)
        assert accepted.status == "ACCEPTED"

    def test_prepare_and_release_payment(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)
        filings.mark_filed(db, ret.id, 801)
        payment = filings.prepare_authority_payment(db, ret.id, 801, payment_reference="PAY-123")
        assert payment.status == "PREPARED"
        assert payment.amount == ret.total_payable
        with pytest.raises(BadRequestException, match="four-eyes"):
            filings.release_payment(db, payment.id, 801)
        released = filings.release_payment(db, payment.id, 802)
        assert released.status == "RELEASED"

    def test_settle_payment(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        filings.reconcile_return(db, ret.id, 801)
        filings.mark_filed(db, ret.id, 801)
        payment = filings.prepare_authority_payment(db, ret.id, 801, payment_reference="PAY-123")
        filings.release_payment(db, payment.id, 802)
        settled = filings.settle_payment(db, payment.id, bank_reference="BANK-456", settlement_evidence="MT103")
        assert settled.status == "SETTLED"
        assert settled.bank_reference == "BANK-456"
        assert settled.reconciled_at is not None

    def test_period_code_generation(self):
        assert filings.period_code_for(2026, date(2026, 3, 1), "MONTH") == "202603"
        assert filings.period_code_for(2026, date(2026, 1, 1), "FOUR_WEEK").startswith("2026W")

    def test_due_dates(self):
        due, pay_due = filings.due_dates_for(2026, date(2026, 3, 1), "MONTH")
        assert due == date(2026, 4, 30)
        assert pay_due == date(2026, 4, 30)

    def test_xml_payload_generated(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        assert ret.payload_xml is not None
        assert ret.payload_sha256 is not None
        assert "<Loonaangifte" in ret.payload_xml
        assert "123456789L01" in ret.payload_xml


class TestListAndQuery:
    def test_list_returns(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        results = filings.list_returns(db, nlx.org.id, tax_year=2026)
        assert len(results) == 1
        assert results[0].id == ret.id

    def test_get_return_with_lines(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        ret = filings.build_loonaangifte_return(
            db, organization_id=nlx.org.id, employer_profile_id=employer.id,
            tax_year=2026, period_code="202603", return_type="REGULAR", actor_id=801)
        loaded_ret, lines = filings.get_return_with_lines(db, ret.id)
        assert loaded_ret.id == ret.id
        assert len(lines) == 1


class TestCommittedPayrollOnly:
    """Phase 9 correction (2026-10-14): returns use committed payroll only,
    the engine's own wage bases, and never count a correction twice."""

    def _employer(self, db, nlx):
        return db.query(PayrollNlEmployerProfile).filter(PayrollNlEmployerProfile.organization_id == nlx.org.id).one()

    def test_uncommitted_run_is_not_filed(self, db, nlx):
        from app.modules.payroll import service
        run = PayrollRun(organization_id=nlx.org.id, period_label="2026-03", period_start=date(2026, 3, 1),
                         period_end=date(2026, 3, 31), pay_date=date(2026, 3, 31), created_by=801,
                         attendance_override_reason="TEST")
        db.add(run)
        db.commit()
        service.generate_payslips_for_run(db, run, nlx.org.id)      # calculated, never approved
        with pytest.raises(BadRequestException, match="no committed Dutch payroll"):
            filings.build_loonaangifte_return(db, organization_id=nlx.org.id,
                                              employer_profile_id=self._employer(db, nlx).id, tax_year=2026,
                                              period_code="202603", return_type="REGULAR", actor_id=801)

    def test_wage_bases_come_from_the_engine(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        ret = filings.build_loonaangifte_return(db, organization_id=nlx.org.id,
                                                employer_profile_id=self._employer(db, nlx).id, tax_year=2026,
                                                period_code="202603", return_type="REGULAR", actor_id=801)
        line = db.query(PayrollNlLoonaangifteLine).filter_by(return_id=ret.id).one()
        assert (line.wage_lb_phf, line.wage_sv, line.wage_zvw) == (D("5000.00"), D("5000.00"), D("5000.00"))
        assert line.hours == D("173.33")                      # the frozen contract hours, not a default

    def test_correction_is_never_counted_twice(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        employer = self._employer(db, nlx)
        original = filings.build_loonaangifte_return(db, organization_id=nlx.org.id, employer_profile_id=employer.id,
                                                     tax_year=2026, period_code="202603", return_type="REGULAR",
                                                     actor_id=801)
        item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
        out = nl.create_nl_correction(db, nlx.org.id, item.id, "salary restated", "REPROCESS_ORIGINAL_PERIOD",
                                      {"earnings": {"base_salary": "4000"}}, 801)
        db.commit()
        corr_run = db.query(PayrollRun).filter(PayrollRun.id == out["correctionRunId"]).one()
        from app.modules.payroll import service
        service.advance_payroll_run_status(db, corr_run.id, 801, nlx.org.id)
        service.advance_payroll_run_status(db, corr_run.id, 802, nlx.org.id)
        # the regular return for the same period is unchanged: the delta is not a line of its own
        assert filings.reconcile_return(db, original.id, 801)["status"] == "RECONCILED"
        correction = filings.create_correction_return(db, original.id, actor_id=801)
        lines = db.query(PayrollNlLoonaangifteLine).filter_by(return_id=correction.id).all()
        assert len(lines) == 1 and lines[0].line_type == "CORRECTION"
        assert lines[0].wage_lb_phf == D("4000.00")
        assert correction.total_wage_tax == D("1000.00")      # replaced, not 1325.08 + (-325.08) + ...

    def test_default_idempotency_key_is_deterministic(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        kwargs = dict(organization_id=nlx.org.id, employer_profile_id=self._employer(db, nlx).id, tax_year=2026,
                      period_code="202603", return_type="REGULAR", actor_id=801)
        assert filings.build_loonaangifte_return(db, **kwargs).id == filings.build_loonaangifte_return(db, **kwargs).id

    def test_december_due_date(self):
        assert filings.due_dates_for(2026, date(2026, 12, 1), "MONTH") == (date(2027, 1, 31), date(2027, 1, 31))
        assert filings.due_dates_for(2026, date(2026, 3, 1), "MONTH") == (date(2026, 4, 30), date(2026, 4, 30))

    def test_payload_values_are_escaped(self, db, nlx):
        _run_and_approve(db, nlx, 3)
        employer = self._employer(db, nlx)
        employer.loonheffingennummer = "123<&>L01"
        db.flush()
        ret = filings.build_loonaangifte_return(db, organization_id=nlx.org.id, employer_profile_id=employer.id,
                                                tax_year=2026, period_code="202603", return_type="REGULAR",
                                                actor_id=801)
        assert "123&lt;&amp;&gt;L01" in ret.payload_xml and "not-gegevensspecificaties" in ret.payload_xml

