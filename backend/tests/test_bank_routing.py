"""
tests/test_bank_routing.py
---------------------------
Multi-jurisdiction routing / bank-code abstraction (ZP-MJR-2026-001).

Covers the resolver (bank_routing.py), the schema/property wiring, the
Bank Transfer File exporters' jurisdiction-aware routing column, and the
hard guarantee that India's BTF output stays byte-identical to the
pre-refactor format while every other jurisdiction gets its canonical
routing header and code.
"""

from decimal import Decimal
from datetime import date

from app.modules.payroll import bank_routing as br
from app.modules.payroll.bank_export import BankExportRow, get_exporter


# ── Resolver unit tests ─────────────────────────────────────────────────

def _emp(country=None, ifsc=None, compliance=None):
    from types import SimpleNamespace
    return SimpleNamespace(country_code=country, ifsc=ifsc, compliance_fields=compliance or {})


def test_resolve_routing_india_uses_dedicated_column():
    assert br.resolve_routing(_emp("IN", ifsc="HDFC0001234")) == [
        {"key": "ifsc", "label": "IFSC", "value": "HDFC0001234"},
    ]


def test_resolve_routing_india_empty_ifsc_returns_blank_value():
    assert br.resolve_routing(_emp("IN", ifsc=None)) == [
        {"key": "ifsc", "label": "IFSC", "value": ""},
    ]


def test_resolve_routing_uk_us_from_compliance_fields():
    assert br.resolve_routing(_emp("UK", compliance={"sort_code": "40-12-34"})) == [
        {"key": "sort_code", "label": "Sort code", "value": "40-12-34"},
    ]
    assert br.resolve_routing(_emp("US", compliance={"aba_routing_number": "021000021"})) == [
        {"key": "aba_routing_number", "label": "ABA routing number", "value": "021000021"},
    ]


def test_resolve_routing_canada_returns_transit_and_institution():
    assert br.resolve_routing(_emp("CA", compliance={
        "transit_number": "12345",
        "financial_institution_number": "001",
    })) == [
        {"key": "transit_number", "label": "Transit number", "value": "12345"},
        {"key": "financial_institution_number", "label": "Institution number", "value": "001"},
    ]


def test_resolve_routing_de_and_au():
    assert br.resolve_routing(_emp("DE", compliance={
        "iban": "DE89370400440532013000", "bic": "COBADEFFXXX",
    })) == [
        {"key": "iban", "label": "IBAN", "value": "DE89370400440532013000"},
        {"key": "bic", "label": "BIC", "value": "COBADEFFXXX"},
    ]
    assert br.resolve_routing(_emp("AU", compliance={"bsb_code": "062000"})) == [
        {"key": "bsb_code", "label": "BSB code", "value": "062000"},
    ]


def test_resolve_routing_unknown_country_returns_empty():
    assert br.resolve_routing(_emp(None)) == []
    assert br.resolve_routing(_emp("XX")) == []


def test_resolve_routing_explicit_country_wins():
    obj = _emp(None, ifsc=None)
    assert br.resolve_routing(obj, country="IN") == [
        {"key": "ifsc", "label": "IFSC", "value": ""},
    ]


# ── BTF column label/value unit tests ───────────────────────────────────

def test_btf_routing_label_is_canonical_per_country():
    assert br.btf_routing_label("IN") == "IFSC"
    assert br.btf_routing_label("UK") == "Sort Code"
    assert br.btf_routing_label("US") == "ABA Routing #"
    assert br.btf_routing_label("CA") == "Transit No."
    assert br.btf_routing_label("DE") == "IBAN"
    assert br.btf_routing_label("AU") == "BSB"
    assert br.btf_routing_label("XX") == "Routing Code"


def test_btf_routing_value_single_value_countries():
    assert br.btf_routing_value(_emp("IN", ifsc="HDFC0001234")) == "HDFC0001234"
    assert br.btf_routing_value(_emp("UK", compliance={"sort_code": "40-12-34"})) == "40-12-34"
    assert br.btf_routing_value(_emp("US", compliance={"aba_routing_number": "021000021"})) == "021000021"
    assert br.btf_routing_value(_emp("AU", compliance={"bsb_code": "062000"})) == "062000"


def test_btf_routing_value_canada_combines_transit_institution():
    assert br.btf_routing_value(_emp("CA", compliance={
        "transit_number": "12345", "financial_institution_number": "001",
    })) == "12345-001"
    assert br.btf_routing_value(_emp("CA", compliance={"transit_number": "12345"})) == "12345"
    assert br.btf_routing_value(_emp("CA", compliance={"financial_institution_number": "001"})) == "001"
    assert br.btf_routing_value(_emp("CA", compliance={})) == ""


def test_btf_routing_value_de_combines_iban_bic():
    assert br.btf_routing_value(_emp("DE", compliance={
        "iban": "DE89370400440532013000", "bic": "COBADEFFXXX",
    })) == "DE89370400440532013000 COBADEFFXXX"
    assert br.btf_routing_value(_emp("DE", compliance={"iban": "DE89370400440532013000"})) == "DE89370400440532013000"
    assert br.btf_routing_value(_emp("DE", compliance={})) == ""


def test_payment_mode_labels():
    assert br.payment_mode_label("IN") == "NEFT"
    assert br.payment_mode_label("UK") == "BACS"
    assert br.payment_mode_label("US") == "ACH"
    assert br.payment_mode_label("CA") == "EFT"
    assert br.payment_mode_label("DE") == "SEPA"
    assert br.payment_mode_label("AU") == "Direct Entry"
    assert br.payment_mode_label("XX") == "Bank Transfer"


def test_ifsc_warning_is_soft_not_blocking():
    assert br.ifsc_warning("HDFC0001234") is None
    assert br.ifsc_warning("") is None
    assert br.ifsc_warning(None) is None
    assert br.ifsc_warning("not-correct") is not None


# ── DB-integration tests: model property + payslip snapshot ─────────────

def test_employee_routing_property_and_response(db, organization):
    from app.modules.payroll.models import PayrollEmployee
    from app.modules.payroll.schemas import EmployeeResponse

    employee = PayrollEmployee(
        organization_id=organization.id, employee_code="E001", name="Asha Rao",
        country_code="UK", compliance_fields={"sort_code": "40-12-34"},
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    # From-attributes serialization picks up the computed `routing` property.
    payload = EmployeeResponse.model_validate(employee).model_dump(by_alias=True)
    assert payload["routing"] == [{"key": "sort_code", "label": "Sort code", "value": "40-12-34"}]
    assert payload["ifscCode"] is None
    assert payload["complianceFields"] == {"sort_code": "40-12-34"}

    india = PayrollEmployee(
        organization_id=organization.id, employee_code="E002", name="Raj Sharma",
        country_code="IN", ifsc="HDFC0001234",
    )
    db.add(india)
    db.commit()
    india_payload = EmployeeResponse.model_validate(india).model_dump(by_alias=True)
    assert india_payload["routing"] == [{"key": "ifsc", "label": "IFSC", "value": "HDFC0001234"}]
    assert india_payload["ifscCode"] == "HDFC0001234"


def test_payslip_serialization_includes_routing(db, organization):
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem
    from app.modules.payroll import service

    employee = PayrollEmployee(
        organization_id=organization.id, employee_code="E003", name="Priya Nair",
        country_code="DE", compliance_fields={"iban": "DE89370400440532013000", "bic": "COBADEFFXXX"},
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    run = PayrollRun(
        organization_id=organization.id, period_label="Aug 2026",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31), pay_date=date(2026, 8, 31),
        status="Approved", total_gross=100000, total_deductions=20000, total_net=80000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    item = PayslipItem(
        payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
        employee_name="Priya Nair", basic_salary=60000, gross_pay=100000,
        net_pay=80000, country_code="DE",
        compliance_fields=dict(employee.compliance_fields),
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    payload = service._serialize_payslip(item, run, country="DE")
    assert payload["routing"] == [
        {"key": "iban", "label": "IBAN", "value": "DE89370400440532013000"},
        {"key": "bic", "label": "BIC", "value": "COBADEFFXXX"},
    ]
    assert payload["ifsc"] is None
    assert payload["complianceFields"] == {"iban": "DE89370400440532013000", "bic": "COBADEFFXXX"}


def test_build_bank_export_rows_sets_routing_per_item(db, organization):
    from app.modules.payroll.models import PayrollRun, PayslipItem
    from app.modules.payroll import service

    organization.country = "UK"
    db.commit()

    run = PayrollRun(
        organization_id=organization.id, period_label="Sep 2026",
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30),
        status="Approved", total_gross=100000, total_deductions=10000, total_net=90000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    uk_item = PayslipItem(
        payroll_run_id=run.id, employee_id=1, organization_id=organization.id,
        employee_name="UK Worker", bank_name="HSBC", bank_account="11223344",
        net_pay=50000, country_code="UK",
        compliance_fields={"sort_code": "40-12-34"},
    )
    db.add(uk_item)

    ca_item = PayslipItem(
        payroll_run_id=run.id, employee_id=2, organization_id=organization.id,
        employee_name="CA Worker", bank_name="RBC", bank_account="1234567",
        net_pay=40000, country_code="CA",
        compliance_fields={"transit_number": "12345", "financial_institution_number": "001"},
    )
    db.add(ca_item)
    db.commit()

    rows = service._build_bank_export_rows(db, run, [uk_item, ca_item], organization.id)
    assert rows[0].routing_label == "Sort Code"
    assert rows[0].routing_value == "40-12-34"
    assert rows[1].routing_label == "Transit No."
    assert rows[1].routing_value == "12345-001"
    # Legacy backwards-compat slot stays populated as before.
    assert rows[0].ifsc == ""


# ── Exporter tests ──────────────────────────────────────────────────────

def _row(employee_name="Asha Rao", label="IFSC", value="HDFC0001234", ifsc="HDFC0001234", amount=50000.0, currency="INR"):
    return BankExportRow(
        employee_name=employee_name, employee_id="1", bank_name="XYZ Bank",
        account_number="9876543210", ifsc=ifsc, branch=None, amount=amount,
        reference_number="PSL-1", narration="Salary Aug 2026",
        payment_date="2026-08-31", currency=currency, company_name="Test Co",
        routing_label=label, routing_value=value,
    )


def test_csv_exporter_india_output_byte_identical():
    exporter = get_exporter("csv")
    out = exporter.generate([_row()]).decode("utf-8")
    expected = (
        "Employee Name,Employee ID,Bank Name,Account Number,IFSC,Branch,"
        "Amount,Reference Number,Narration,Payment Date,Currency,Company Name\r\n"
        "Asha Rao,1,XYZ Bank,9876543210,HDFC0001234,,50000.00,PSL-1,"
        "Salary Aug 2026,2026-08-31,INR,Test Co\r\n"
    )
    assert out == expected


def test_txt_exporter_india_output_byte_identical():
    exporter = get_exporter("txt")
    out = exporter.generate([_row()]).decode("utf-8")
    expected = (
        "EMPLOYEE_NAME|EMPLOYEE_ID|BANK_NAME|ACCOUNT_NUMBER|IFSC|BRANCH|"
        "AMOUNT|REFERENCE_NUMBER|NARRATION|PAYMENT_DATE|CURRENCY|COMPANY_NAME\n"
        "Asha Rao|1|XYZ Bank|9876543210|HDFC0001234||50000.00|PSL-1|"
        "Salary Aug 2026|2026-08-31|INR|Test Co\n"
    )
    assert out == expected


def test_csv_exporter_multi_jurisdiction_headers_and_values():
    exporter = get_exporter("csv")
    out = exporter.generate([
        _row(employee_name="UK Worker", label="Sort Code", value="40-12-34", ifsc="", currency="GBP"),
        _row(employee_name="CA Worker", label="Transit No.", value="12345-001", ifsc="", currency="CAD"),
        _row(employee_name="DE Worker", label="IBAN", value="DE89370400440532013000 COBADEFFXXX", ifsc="", currency="EUR"),
    ]).decode("utf-8")
    lines = out.splitlines()
    assert lines[0] == (
        "Employee Name,Employee ID,Bank Name,Account Number,Sort Code,Branch,"
        "Amount,Reference Number,Narration,Payment Date,Currency,Company Name"
    )
    assert "UK Worker,1,XYZ Bank,9876543210,40-12-34,," in out
    assert "CA Worker,1,XYZ Bank,9876543210,12345-001,," in out
    assert "DE Worker,1,XYZ Bank,9876543210,DE89370400440532013000 COBADEFFXXX,," in out


def test_exporter_legacy_row_without_routing_falls_back_to_ifsc():
    exporter = get_exporter("csv")
    legacy = BankExportRow(
        employee_name="Asha Rao", employee_id="1", bank_name="XYZ Bank",
        account_number="9876543210", ifsc="HDFC0001234", branch=None, amount=50000.0,
        reference_number="PSL-1", narration="Salary Aug 2026",
        payment_date="2026-08-31", currency="INR", company_name="Test Co",
    )
    out = exporter.generate([legacy]).decode("utf-8")
    assert "IFSC,Branch" in out.splitlines()[0]
    assert "HDFC0001234," in out.splitlines()[1]


def test_excel_and_pdf_exporters_accept_routing():
    rows = [_row(label="BSB", value="062000", ifsc="", currency="AUD")]
    assert get_exporter("xlsx").generate(rows)[:2] == b"PK"
    pdf = get_exporter("pdf").generate(rows)
    assert pdf.startswith(b"%PDF")


def test_build_bank_export_rows_india_keeps_ifsc_slot(db, organization):
    from app.modules.payroll.models import PayrollRun, PayslipItem
    from app.modules.payroll import service

    organization.country = "IN"
    db.commit()
    run = PayrollRun(
        organization_id=organization.id, period_label="Oct 2026",
        period_start=date(2026, 10, 1), period_end=date(2026, 10, 31), pay_date=date(2026, 10, 31),
        status="Approved", total_gross=100000, total_deductions=10000, total_net=90000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=1, organization_id=organization.id,
        employee_name="IN Worker", bank_name="HDFC", bank_account="123456789",
        ifsc="HDFC0001234", net_pay=90000, country_code="IN",
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    rows = service._build_bank_export_rows(db, run, [item], organization.id)
    assert rows[0].routing_label == "IFSC"
    assert rows[0].routing_value == "HDFC0001234"
    assert rows[0].ifsc == "HDFC0001234"