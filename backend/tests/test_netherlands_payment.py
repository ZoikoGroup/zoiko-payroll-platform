"""
tests/test_netherlands_payment.py
----------------------------------
SEPA payment batch tests (Phase 10).
"""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import Session

from app.modules.payroll import netherlands_payment_service as pay, netherlands_service as nl
from app.modules.payroll import netherlands_filing_service as filings
from app.modules.payroll.models import (
    PayrollNlPaymentBatch,
    PayrollNlPaymentItem,
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
                                    cao_status="NONE", bank_iban_token="NL91ABNA0417164300", bank_bic="ABNANL2A"))
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


class TestSalaryPaymentBatch:
    def test_create_salary_batch_from_committed_run(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)

        batch = pay.create_salary_payment_batch(db, run.id, 801)
        assert batch.status == "SUBMITTED"
        assert batch.payroll_run_id == run.id
        assert batch.pain001_sha256 is not None

    def test_idempotency_key_prevents_duplicate(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        key = "test-salary-batch-key-123"

        batch1 = pay.create_salary_payment_batch(db, run.id, 801, idempotency_key=key)
        batch2 = pay.create_salary_payment_batch(db, run.id, 801, idempotency_key=key)
        assert batch1.id == batch2.id

    def test_payment_items_created(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)

        batch = pay.create_salary_payment_batch(db, run.id, 801)
        items = db.query(PayrollNlPaymentItem).filter(
            PayrollNlPaymentItem.batch_id == batch.id).all()
        assert len(items) == 1
        item = items[0]
        assert item.employee_id == nlx.emp.id
        assert item.amount > D("0")
        assert item.status == "PENDING"
        assert item.end_to_end_id is not None

    def test_batch_requires_committed_run(self, db, nlx):
        from app.modules.payroll import service
        PREPARER = 801
        end = date(2026, 3, 31)
        run = PayrollRun(organization_id=nlx.org.id, period_label="2026-03", period_start=date(2026, 3, 1),
                         period_end=end, pay_date=end, created_by=PREPARER,
                         attendance_override_reason="TEST")
        db.add(run)
        db.commit()
        db.refresh(run)
        service.generate_payslips_for_run(db, run, nlx.org.id)
        # NOT approved -> not committed

        with pytest.raises(pay.PaymentServiceError):
            pay.create_salary_payment_batch(db, run.id, 801)

    def test_batch_requires_employer_iban(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        # Remove employer IBAN
        from app.modules.payroll.models import PayrollNlEmployerProfile
        profile = db.query(PayrollNlEmployerProfile).filter(
            PayrollNlEmployerProfile.organization_id == nlx.org.id).one()
        profile.bank_iban_token = None
        db.commit()

        with pytest.raises(pay.PaymentServiceError, match="Employer IBAN"):
            pay.create_salary_payment_batch(db, run.id, 801)


class TestAuthorityPaymentBatch:
    def test_create_authority_batch(self, db, nlx):
        batch = pay.create_authority_payment_batch(
            db,
            organization_id=nlx.org.id,
            authority_payments=[
                {"payment_reference": "LOONHEFFING-202603", "amount": D("5000.00"),
                 "creditor_name": "Belastingdienst", "creditor_iban": "NL03RABO0000000001",
                 "creditor_bic": "RABONL2U"},
                {"payment_reference": "AWF-202603", "amount": D("2000.00"),
                 "creditor_name": "UWV", "creditor_iban": "NL98INGB0000000002",
                 "creditor_bic": "INGBNL2A"},
            ],
            actor_id=801,
        )
        assert batch.status == "SUBMITTED"
        assert batch.organization_id == nlx.org.id

    def test_authority_payment_items_created(self, db, nlx):
        batch = pay.create_authority_payment_batch(
            db,
            organization_id=nlx.org.id,
            authority_payments=[
                {"payment_reference": "LOONHEFFING-202603", "amount": D("5000.00"),
                 "creditor_name": "Belastingdienst", "creditor_iban": "NL03RABO0000000001"},
            ],
            actor_id=801,
        )
        items = db.query(PayrollNlPaymentItem).filter(
            PayrollNlPaymentItem.batch_id == batch.id).all()
        assert len(items) == 1
        item = items[0]
        assert item.amount == D("5000.00")
        assert item.end_to_end_id is not None


class TestBatchLifecycle:
    def test_submit_batch(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        batch = pay.create_salary_payment_batch(db, run.id, 801)
        pay.submit_payment_batch(db, batch.id, 801)
        db.refresh(batch)
        assert batch.submitted_at is not None

    def test_reconcile_batch(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        batch = pay.create_salary_payment_batch(db, run.id, 801)
        pay.submit_payment_batch(db, batch.id, 801)
        reconciled = pay.reconcile_payment_batch(db, batch.id, bank_reference="BANK-123")
        assert reconciled.status == "SETTLED"
        assert reconciled.reconciled_at is not None

    def test_handle_payment_return(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        batch = pay.create_salary_payment_batch(db, run.id, 801)
        items = db.query(PayrollNlPaymentItem).filter(
            PayrollNlPaymentItem.batch_id == batch.id).all()
        item = items[0]

        returned = pay.handle_payment_return(db, batch.id, item.end_to_end_id, "AM04 - Insufficient funds")
        assert returned.status == "RETURNED"
        assert returned.return_reason == "AM04 - Insufficient funds"

    def test_get_batch_with_items(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        batch = pay.create_salary_payment_batch(db, run.id, 801)
        loaded_batch, items = pay.get_batch_with_items(db, batch.id)
        assert loaded_batch.id == batch.id
        assert len(items) == 1

    def test_list_payment_batches(self, db, nlx):
        run = _run_and_approve(db, nlx, 3)
        batch = pay.create_salary_payment_batch(db, run.id, 801)
        results = pay.list_payment_batches(db, nlx.org.id)
        assert len(results) == 1
        assert results[0].id == batch.id