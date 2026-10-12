"""
tests/test_germany_payslip_surface.py
--------------------------------------
Phase 8BM — coverage for the Germany payslip SURFACE (the places a
computed Germany payroll value actually becomes visible):

1. PayslipItem.church_tax (Kirchensteuer) is computed and persisted by the
   engine, but `_serialize_payslip` never emitted it and
   `PayslipItemResponse` had no field for it — so FastAPI's
   response_model filtering silently stripped the value from every payslip
   API response (and the PDF read a snake_case key that never existed in
   the data dict, i.e. a dead branch). See service.py's own fix note.
   These tests pin that the serialized dict carries "churchTax" and that
   the response schema round-trips it (the exact contract FastAPI
   enforces with response_model=PayslipItemResponse).

2. A statutorily-blocked payslip (PayslipStatus.FAILED — Phase 8BI's
   sentinel for Germany PAP unavailable / no effective statutory profile)
   holds ZERO monetary figures. generate_payslip_pdf_bytes previously
   rendered it through the normal layout, fabricating a €0.00 payslip
   document. It must instead render the explicit blocked-state document:
   no "0.00" anywhere, no gross/net figures, and the already-redacted
   blocker surfaced for operator traceability.

The PDF asserts use pypdf text extraction (reportlab compresses its
content streams, so substring checks on the raw bytes are unreliable).
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll import service
from app.modules.payroll.models import (
    PayrollEmployee, PayrollRun, PayslipItem, PayslipStatus,
)
from app.modules.payroll.schemas import PayslipItemResponse


def _make_de_employee(db, org_id, code="DE-PSL"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=5000 * 12, basic=5000, hra=0, status="Active",
        date_of_joining=date(2026, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_de_run(db, org_id):
    run = PayrollRun(
        organization_id=org_id, period_label="Jan 2026",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        pay_date=date(2026, 2, 1), status="Draft",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _make_de_item(db, run, emp, org_id, **overrides):
    fields = dict(
        payroll_run_id=run.id, employee_id=emp.id, organization_id=org_id,
        employee_name=emp.name, country_code="DE",
        basic_salary=5000, gross_pay=5000, total_deductions=800, net_pay=4200,
        tds=350, pf=0, esi=0, professional_tax=0,
        status=PayslipStatus.PENDING,
    )
    fields.update(overrides)
    item = PayslipItem(**fields)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _pdf_text(pdf_bytes: bytes) -> str:
    import io
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def test_serializer_emits_church_tax_and_schema_round_trips(db, organization):
    emp = _make_de_employee(db, organization.id)
    run = _make_de_run(db, organization.id)
    item = _make_de_item(
        db, run, emp, organization.id,
        church_tax=Decimal("40.20"),
        compliance_fields={"steuer_id": "42/123/45678", "steuerklasse": "I", "iban": "DE89370400440532013000"},
    )

    data = service._serialize_payslip(item, run, country="DE")

    # The key the serializer emits, in the dict FastAPI validates and the
    # PDF generator reads ("churchTax", not the snake_case that never existed).
    assert "churchTax" in data
    assert data["churchTax"] == Decimal("40.20")

    # Exactly what FastAPI does with response_model=PayslipItemResponse:
    # it must not strip the key (otherwise the response would drop it).
    parsed = PayslipItemResponse.model_validate(dict(data))
    assert parsed.churchTax == Decimal("40.20")


def test_serializer_handles_legacy_rows_with_null_church_tax(db, organization):
    emp = _make_de_employee(db, organization.id)
    run = _make_de_run(db, organization.id)
    item = _make_de_item(db, run, emp, organization.id, church_tax=None)

    data = service._serialize_payslip(item, run, country="DE")
    assert data["churchTax"] == Decimal("0")

    parsed = PayslipItemResponse.model_validate(dict(data))
    assert parsed.churchTax == Decimal("0")


def test_serializer_emits_soli_and_schema_round_trips(db, organization):
    """Phase 8BN: PayslipItem.soli must reach the payslip API exactly like
    churchTax above — `_serialize_payslip` emits "soli" and
    `PayslipItemResponse` round-trips it (Soli is informational; tds stays
    the combined Lohnsteuer+Soli total)."""
    emp = _make_de_employee(db, organization.id)
    run = _make_de_run(db, organization.id)
    item = _make_de_item(db, run, emp, organization.id, soli=Decimal("18.79"))

    data = service._serialize_payslip(item, run, country="DE")
    assert "soli" in data
    assert data["soli"] == Decimal("18.79")

    parsed = PayslipItemResponse.model_validate(dict(data))
    assert parsed.soli == Decimal("18.79")


def test_serializer_handles_legacy_rows_with_null_soli(db, organization):
    emp = _make_de_employee(db, organization.id)
    run = _make_de_run(db, organization.id)
    item = _make_de_item(db, run, emp, organization.id, soli=None)

    data = service._serialize_payslip(item, run, country="DE")
    assert data["soli"] == Decimal("0")

    parsed = PayslipItemResponse.model_validate(dict(data))
    assert parsed.soli == Decimal("0")


def test_non_de_payslip_defaults_church_tax_to_zero(db, organization):
    emp = PayrollEmployee(
        organization_id=organization.id, employee_code="IN-PSL",
        name="Indian Employee", country_code="IN", ctc=1000000, basic=50000,
        hra=15000, status="Active", date_of_joining=date(2026, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    run = _make_de_run(db, organization.id)
    item = _make_de_item(
        db, run, emp, organization.id, country_code="IN",
        basic_salary=50000, gross_pay=65000, net_pay=50000, tds=8000,
    )

    data = service._serialize_payslip(item, run, country="IN")
    assert data["churchTax"] == Decimal("0")
    assert PayslipItemResponse.model_validate(dict(data)).churchTax == Decimal("0")


def test_german_pdf_shows_kirchensteuer_line_when_church_tax_is_nonzero(db, organization):
    emp = _make_de_employee(db, organization.id)
    run = _make_de_run(db, organization.id)
    item = _make_de_item(
        db, run, emp, organization.id,
        church_tax=Decimal("40.20"),
        compliance_fields={"steuer_id": "42/123/45678", "steuerklasse": "I", "iban": "DE89370400440532013000"},
    )

    pdf_bytes = service.generate_payslip_pdf_bytes(db, item.id, organization.id)
    assert pdf_bytes[:4] == b"%PDF"

    text = _pdf_text(pdf_bytes)
    assert "Kirchensteuer" in text


def test_blocked_payslip_pdf_renders_blocked_document_with_no_monetary_figures(db, organization):
    emp = _make_de_employee(db, organization.id)
    run = _make_de_run(db, organization.id)
    item = _make_de_item(
        db, run, emp, organization.id,
        status=PayslipStatus.FAILED,
        germany_calculation_snapshot={
            "calculationStatus": "BLOCKED",
            "blockedReasonCode": "GERMANY_PAP_NOT_AVAILABLE",
            "blockedReasonMessage": "No PUBLISHED BMF PAP asset exists for this payroll date.",
            "steps": [],
        },
    )

    pdf_bytes = service.generate_payslip_pdf_bytes(db, item.id, organization.id)
    assert pdf_bytes[:4] == b"%PDF"

    text = _pdf_text(pdf_bytes)
    # The blocked-state document states the blocker explicitly...
    assert "BLOCKED" in text
    assert "GERMANY_PAP_NOT_AVAILABLE" in text
    # ...and must NEVER fabricate monetary figures (the FAILED row holds none).
    assert "0.00" not in text
    assert "Gross Salary" not in text
    assert "Net Pay" not in text


def test_failed_payslip_still_serializes_for_run_detail(db, organization):
    """The run-detail table lists FAILED sentinels with zero money (the
    serializer must not 500 on them), while the PDF deliberately does not
    mirror those zeros as a payslip document."""
    emp = _make_de_employee(db, organization.id)
    run = _make_de_run(db, organization.id)
    # The real Phase 8BI sentinel carries ONLY identity + status + snapshot —
    # every money column stays at its model default (0). Mirror that exactly.
    item = _make_de_item(
        db, run, emp, organization.id,
        status=PayslipStatus.FAILED,
        basic_salary=None, gross_pay=None, total_deductions=None, net_pay=None,
        tds=None, pf=None, esi=None, professional_tax=None,
        germany_calculation_snapshot={"blockedReasonCode": "GERMANY_PAP_NOT_AVAILABLE"},
    )

    data = service._serialize_payslip(item, run, country="DE")
    assert data["status"] == PayslipStatus.FAILED
    assert data["netPay"] == Decimal("0")
    parsed = PayslipItemResponse.model_validate(dict(data))
    assert parsed.status == PayslipStatus.FAILED