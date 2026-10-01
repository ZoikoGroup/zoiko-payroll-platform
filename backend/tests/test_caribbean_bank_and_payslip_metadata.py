"""
tests/test_caribbean_bank_and_payslip_metadata.py
----------------------------------------------------
ZP-MJR-2026-002 (2026-09-24) — closes the gap found when the 8 newer
jurisdictions (Barbados/Cayman Islands/Dominican Republic/Guyana/Jamaica/
Bahamas/Trinidad & Tobago/Puerto Rico) went live: the Bank Transfer File and
Payslip PDF/dashboard label tables were never extended to cover them, so
every one of these countries got a blank BTF routing column, a USD/$
default currency, a colliding 2-letter country code for some full names
(e.g. "Cayman Islands" -> "CA", the same as Canada's), and India-labeled
statutory deductions ("TDS", "PAN", "Provident Fund (PF)").

Covers: currency resolution, country-name normalization, bank-routing
resolution/BTF columns, the payslip identity-row helper, and the payslip
PDF's statutory labels for each of the 8 countries.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import bank_routing as br
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem, PayslipStatus


CARIBBEAN_CODES = ["BB", "KY", "DO", "GY", "JM", "BS", "TT", "PR"]

FULL_NAMES = {
    "BB": "Barbados", "KY": "Cayman Islands", "DO": "Dominican Republic",
    "GY": "Guyana", "JM": "Jamaica", "BS": "Bahamas",
    "TT": "Trinidad and Tobago", "PR": "Puerto Rico",
}

EXPECTED_CURRENCY = {
    "BB": "BBD", "KY": "KYD", "DO": "DOP", "GY": "GYD",
    "JM": "JMD", "BS": "BSD", "TT": "TTD", "PR": "USD",
}

EXPECTED_ROUTING_KEY = {
    "BB": "bank_branch_code", "KY": "bank_branch_code", "DO": "bank_branch_code",
    "GY": "bank_branch_code", "JM": "bank_branch_code", "TT": "bank_branch_code",
    "BS": "ach_routing_number", "PR": "ach_routing_number",
}


# ── Fix 1: currency resolution ──────────────────────────────────────────

def test_currency_code_correct_for_every_caribbean_jurisdiction():
    for code, expected in EXPECTED_CURRENCY.items():
        assert service._get_currency_code(code) == expected, code


def test_currency_symbol_is_not_the_usd_default():
    # Every one of these 7 previously fell through to the "$"/USD default —
    # Puerto Rico is the one legitimate exception (it really is USD).
    for code in ["BB", "KY", "DO", "GY", "JM", "BS", "TT"]:
        assert service._get_currency_symbol(code) != "$", code
        assert service._get_currency_code(code) != "USD", code


# ── Fix 2: full-name normalization, including the Cayman/Canada collision ──

def test_normalize_country_resolves_full_names_without_collision():
    for code, name in FULL_NAMES.items():
        assert service._normalize_country(name) == code, name
    # The specific bug: "Cayman Islands"[:2].upper() == "CA", Canada's real
    # code — must not collide.
    assert service._normalize_country("Cayman Islands") != service._normalize_country("Canada")


def test_jurisdiction_code_for_org_country_backfill_helper():
    for code, name in FULL_NAMES.items():
        assert service._jurisdiction_code_for_org_country(name) == code, name
    assert service._jurisdiction_code_for_org_country(None) is None
    assert service._jurisdiction_code_for_org_country("India") == "IN"


# ── Fix 3: bank routing ─────────────────────────────────────────────────

def _emp(country, compliance):
    from types import SimpleNamespace
    return SimpleNamespace(country_code=country, ifsc=None, compliance_fields=compliance)


def test_routing_fields_defined_for_every_caribbean_jurisdiction():
    for code in CARIBBEAN_CODES:
        assert code in br.ROUTING_COUNTRIES
        assert br.ROUTING_FIELDS[code][0]["key"] == EXPECTED_ROUTING_KEY[code]
        assert br.btf_routing_label(code) != "Routing Code"
        assert br.payment_mode_label(code) != "Bank Transfer"


def test_resolve_and_btf_routing_value_lenient_countries():
    for code in ["BB", "KY", "DO", "GY", "JM", "TT"]:
        key = EXPECTED_ROUTING_KEY[code]
        obj = _emp(code, {key: "BRANCH-042"})
        assert br.resolve_routing(obj) == [{"key": key, "label": "Bank/Branch Code", "value": "BRANCH-042"}]
        assert br.btf_routing_value(obj) == "BRANCH-042"


def test_resolve_and_btf_routing_value_ach_countries():
    for code in ["BS", "PR"]:
        key = EXPECTED_ROUTING_KEY[code]
        obj = _emp(code, {key: "021000021"})
        assert br.resolve_routing(obj) == [{"key": key, "label": "ACH Routing #", "value": "021000021"}]
        assert br.btf_routing_value(obj) == "021000021"


def test_build_bank_export_rows_jamaica_currency_and_routing(db, organization):
    organization.country = "Jamaica"
    db.commit()

    run = PayrollRun(
        organization_id=organization.id, period_label="Sep 2026",
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30),
        status="Approved", total_gross=100000, total_deductions=10000, total_net=90000,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    item = PayslipItem(
        payroll_run_id=run.id, employee_id=1, organization_id=organization.id,
        employee_name="JM Worker", bank_name="NCB", bank_account="1122334455",
        net_pay=90000, country_code="JM",
        compliance_fields={"trn": "123456789", "bank_branch_code": "NCB-042"},
    )
    db.add(item)
    db.commit()

    rows = service._build_bank_export_rows(db, run, [item], organization.id)
    assert rows[0].routing_label == "Bank/Branch Code"
    assert rows[0].routing_value == "NCB-042"
    assert rows[0].currency == "JMD"


# ── Fix 5: identity rows ────────────────────────────────────────────────

def test_payslip_identity_rows_real_values_no_none_labels():
    cases = {
        "BB": {"tamis_tin": "1234567890"},
        "KY": {"nib_member_number": "NIB-1"},
        "DO": {"cedula": "001-1234567-8"},
        "GY": {"gra_tin": "1234567"},
        "JM": {"trn": "123456789"},
        "BS": {"nib_number": "NIB-2"},
        "TT": {"bir_file_number": "1234567890"},
        "PR": {"ssn": "660-12-3456"},
    }
    for code, cf in cases.items():
        rows = service._payslip_identity_rows(code, {"complianceFields": cf})
        assert len(rows) == 3
        for label, _value in rows:
            assert label is not None, f"{code} produced a None row label"


# ── Fix 4: payslip PDF statutory labels ─────────────────────────────────

def _pdf_text(pdf_bytes: bytes) -> str:
    import io
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _make_item(db, org_id, run, **overrides):
    fields = dict(
        payroll_run_id=run.id, employee_id=1, organization_id=org_id,
        employee_name="Test Employee", basic_salary=100000, gross_pay=100000,
        total_deductions=20000, net_pay=80000,
        tds=0, pf=0, esi=0, professional_tax=0, social_security=0,
        status=PayslipStatus.PENDING,
    )
    fields.update(overrides)
    item = PayslipItem(**fields)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _make_run(db, org_id, label="Sep 2026"):
    run = PayrollRun(
        organization_id=org_id, period_label=label,
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
        pay_date=date(2026, 9, 30), status="Draft",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_jamaica_pdf_shows_paye_nis_nht_education_tax_not_india_terms(db, organization):
    run = _make_run(db, organization.id)
    item = _make_item(
        db, organization.id, run, country_code="JM",
        tds=Decimal("5000"), social_security=Decimal("3000"),
        employee_pension=Decimal("2000"), ni_employee=Decimal("2250"),
        compliance_fields={"trn": "123456789"},
    )
    pdf_bytes = service.generate_payslip_pdf_bytes(db, item.id, organization.id)
    assert pdf_bytes[:4] == b"%PDF"
    text = _pdf_text(pdf_bytes)
    assert "PAYE" in text
    assert "NIS" in text
    assert "National Housing Trust" in text
    assert "Education Tax" in text
    assert "TDS" not in text
    assert "Provident Fund" not in text


def test_dominican_republic_pdf_shows_isr_sfs_pension_svds(db, organization):
    run = _make_run(db, organization.id)
    item = _make_item(
        db, organization.id, run, country_code="DO",
        tds=Decimal("4000"), social_security=Decimal("1500"),
        employee_pension=Decimal("1200"),
        compliance_fields={"cedula": "001-1234567-8"},
    )
    pdf_bytes = service.generate_payslip_pdf_bytes(db, item.id, organization.id)
    text = _pdf_text(pdf_bytes)
    assert "ISR" in text
    assert "SFS" in text
    assert "SVDS" in text


def test_trinidad_pdf_shows_health_surcharge_not_professional_tax(db, organization):
    run = _make_run(db, organization.id)
    item = _make_item(
        db, organization.id, run, country_code="TT",
        tds=Decimal("3000"), professional_tax=Decimal("100"),
        social_security=Decimal("500"),
        compliance_fields={"bir_file_number": "1234567890"},
    )
    pdf_bytes = service.generate_payslip_pdf_bytes(db, item.id, organization.id)
    text = _pdf_text(pdf_bytes)
    assert "Health Surcharge" in text
    assert "Professional Tax" not in text
    assert "PAYE" in text


def test_barbados_pdf_shows_paye_nis_and_rr_levy(db, organization):
    run = _make_run(db, organization.id)
    item = _make_item(
        db, organization.id, run, country_code="BB",
        tds=Decimal("6000"), social_security=Decimal("2000"),
        employee_pension=Decimal("500"),
        compliance_fields={"tamis_tin": "1234567890"},
    )
    pdf_bytes = service.generate_payslip_pdf_bytes(db, item.id, organization.id)
    text = _pdf_text(pdf_bytes)
    assert "PAYE" in text
    assert "NIS" in text
    assert "Reserve" in text


def test_bahamas_pdf_has_no_income_tax_line_and_shows_nib(db, organization):
    # Bahamas genuinely has no personal income tax (bahamas.py's own
    # docstring): tds is always 0, so no income-tax label should render.
    run = _make_run(db, organization.id)
    item = _make_item(
        db, organization.id, run, country_code="BS",
        tds=Decimal("0"), social_security=Decimal("800"),
        compliance_fields={"nib_number": "NIB-1"},
    )
    pdf_bytes = service.generate_payslip_pdf_bytes(db, item.id, organization.id)
    text = _pdf_text(pdf_bytes)
    assert "NIB" in text
    assert "TDS" not in text


def test_puerto_rico_pdf_shows_hacienda_withholding(db, organization):
    run = _make_run(db, organization.id)
    item = _make_item(
        db, organization.id, run, country_code="PR",
        tds=Decimal("7000"), social_security=Decimal("3000"), medicare=Decimal("1000"),
        compliance_fields={"ssn": "660-12-3456"},
    )
    pdf_bytes = service.generate_payslip_pdf_bytes(db, item.id, organization.id)
    text = _pdf_text(pdf_bytes)
    assert "Hacienda" in text
    assert "Social Security" in text
    assert "Medicare" in text
