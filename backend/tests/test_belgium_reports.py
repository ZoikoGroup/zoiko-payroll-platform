"""Belgium (ZP-BE-ENG-001) Block K1: employee documents (individual account, 281.10 employee copy, holiday
certificate) on the report-template mechanism.

Synthetic DEMO data only. Each document renders from committed data with every required field, the NISS masked
(never a digit), the document version recorded; previews are marked while the template is not Active; generation
is refused until the template is Active (template_activation_refusal decides that, unchanged); an approved
holiday certificate is immutable and only an approved one is issued."""
import json
import re
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException

NISS = "12312312312"  # privacy-scan: allow (synthetic TEST ONLY value)
YEAR = "2026"


def _rep():
    from app.modules.payroll import belgium_reports

    return belgium_reports


@pytest.fixture
def world(db, monkeypatch):
    from app.config import settings
    from app.core import code_generation
    from app.modules.payroll import belgium_demo, belgium_service as be
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter) * 1000:05d}")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "f" * 32)
    t = make_org(db, name="DEMO Reports BV", code="BEREP", admins=2, country="BE")
    monkeypatch.setattr(settings, "BE_DEMO_ORG_IDS", str(t.org.id))
    belgium_demo.be_seed_demo_pack(db)
    db.commit()
    out = belgium_demo.be_seed_demo_month(db, t.org.id, t.users[0].id, t.users[1].id)
    employee = db.query(PayrollEmployee).filter_by(organization_id=t.org.id).order_by(PayrollEmployee.id).first()
    be.create_be_identifier(db, t.org.id, "NISS", NISS, t.users[0].id, employee_id=employee.id)
    db.commit()
    _rep().be_seed_report_templates(db, YEAR, t.users[0].id)
    db.commit()
    return t, out, employee


def _assert_required(view, report_type):
    for component, fields in _rep().be_required_fields(report_type).items():
        assert component in view["sections"], component
        for field in fields:
            assert field in view["sections"][component], (component, field)
            assert view["sections"][component][field] not in (None, ""), (component, field)


def _no_niss(blob):
    text = json.dumps(blob) if not isinstance(blob, (bytes, str)) else (blob if isinstance(blob, str) else "")
    assert NISS not in text and not re.search(r"(?<!\d)\d{11}(?!\d)", text)


def test_templates_are_seeded_draft_with_their_layout_and_activation_stays_refused(db, world):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponent

    t = world[0]
    rows = _rep().be_seed_report_templates(db, YEAR, t.users[0].id)                     # idempotent
    assert {r.report_type for r in rows} == {"INDIVIDUAL_ACCOUNT", "BELCOTAX_EMPLOYEE_COPY", "HOLIDAY_CERTIFICATE"}
    assert all(r.status == "Draft" and r.jurisdiction_country == "BE" for r in rows)
    assert db.query(ReportTemplate).filter_by(jurisdiction_country="BE", reporting_year=YEAR).count() == 3
    for r in rows:
        keys = {c.component_key for c in db.query(ReportTemplateComponent).filter_by(report_template_id=r.id)}
        assert set(_rep().be_required_fields(r.report_type)) <= keys
    assert be._be_template_activation_refusal(db, rows[0])                                # gate unchanged


def test_the_individual_account_comes_from_committed_data_only(db, world):
    from app.modules.payroll import belgium_service as be

    t, _out, employee = world
    view = _rep().be_report_preview(db, t.org.id, "INDIVIDUAL_ACCOUNT", {"employeeId": employee.id, "year": YEAR})
    _assert_required(view, "INDIVIDUAL_ACCOUNT")
    _no_niss(view)
    assert view["documentVersion"] == "BE-INDIVIDUAL-ACCOUNT-A" and view["preview"] is True
    assert "PREVIEW — TEMPLATE NOT APPROVED" in view["watermarks"]
    emp = view["sections"]["employee"]
    assert emp["identifier_masked"] and not re.search(r"\d", emp["identifier_masked"])
    lines = view["sections"]["periods"]["period_lines"]
    assert lines and all(line["kind"] == "RUN" for line in lines)
    totals = view["sections"]["totals"]
    # never recomputed: the totals are the committed ledger's own sums and the payslips' stored figures
    Entry = be._models().PayrollBeAccumulatorEntry
    ledger = {}
    for e in db.query(Entry).filter_by(organization_id=t.org.id, employee_id=employee.id, year=int(YEAR)):
        ledger[e.accumulator] = ledger.get(e.accumulator, Decimal("0")) + Decimal(str(e.amount))
    assert {k: Decimal(v) for k, v in totals["component_totals"].items()} == ledger
    assert Decimal(totals["onss_employee_total"]) == ledger.get("ONSS_EMPLOYEE", Decimal("0"))
    assert Decimal(totals["net_paid_total"]) == sum(Decimal(line["net"]) for line in lines)
    pdf = _rep().be_report_pdf(view)
    assert pdf.startswith(b"%PDF")


def test_the_281_10_employee_copy_shows_amounts_dependants_and_lineage(db, world):
    from app.modules.payroll import belgium_filing as bf

    t, _out, employee = world
    fiches = bf.build_be_belcotax(db, t.org.id, int(YEAR), None, t.users[0].id, today=date(2027, 1, 15))
    db.commit()
    fiche = next(f for f in fiches if f.subject_key == f"E{employee.id}")
    view = _rep().be_report_preview(db, t.org.id, "BELCOTAX_EMPLOYEE_COPY", {"filingId": fiche.id})
    _assert_required(view, "BELCOTAX_EMPLOYEE_COPY")
    _no_niss(view)
    assert view["sections"]["amounts"]["withholding_regular"] == fiche.payload["withholding"]["regular"]
    assert view["sections"]["dependants"]["dependants_used"] == "none declared"
    assert [e["kind"] for e in view["sections"]["lineage"]["lineage"]] == ["ORIGINAL"]
    correction = bf.correct_filing(db, fiche, {**fiche.payload, "note": "TEST ONLY"}, fiche.run_ids, t.users[0].id)
    db.commit()
    lineage = _rep().be_report_preview(db, t.org.id, "BELCOTAX_EMPLOYEE_COPY",
                                       {"filingId": correction.id})["sections"]["lineage"]["lineage"]
    assert [e["kind"] for e in lineage] == ["ORIGINAL", "CORRECTION"] and lineage[1]["correctsId"] == fiche.id
    with pytest.raises(BadRequestException):
        dmfa = next(iter(bf.list_be_filings(db, t.org.id, form_code="DMFA")))
        _rep().be_report_preview(db, t.org.id, "BELCOTAX_EMPLOYEE_COPY", {"filingId": dmfa["id"]})


def test_the_holiday_certificate_is_issued_only_when_approved_and_stays_immutable(db, world):
    from app.modules.payroll import belgium_service as be

    t, _out, employee = world
    row = be.record_be_holiday_certificate(db, t.org.id, employee.id, {
        "direction": "IN", "service_year": 2025, "issued_on": "2026-01-15", "prior_employer_ref": "TEST ONLY BV",
        "gross_base_amount": "1000.00", "simple_pay_amount": "100.00", "double_pay_amount": "92.00",
        "days_paid": "5"}, t.users[0].id, "TEST ONLY certificate")
    db.commit()
    draft = _rep().be_report_preview(db, t.org.id, "HOLIDAY_CERTIFICATE", {"certificateId": row.id})
    _assert_required(draft, "HOLIDAY_CERTIFICATE")
    _no_niss(draft)
    assert draft["sections"]["certificate"]["status"] == "DRAFT"
    assert draft["sections"]["certificate"]["prior_employer_ref"] == "TEST ONLY BV"
    with pytest.raises(BadRequestException, match="APPROVED"):
        _rep().be_report_generate(db, t.org.id, "HOLIDAY_CERTIFICATE", {"certificateId": row.id}, t.users[0].id)
    be.approve_be_holiday_certificate(db, t.org.id, row.id, t.users[1].id)
    db.commit()
    with pytest.raises(BadRequestException, match="immutable"):
        be.approve_be_holiday_certificate(db, t.org.id, row.id, t.users[1].id)
    first = _rep().be_report_preview(db, t.org.id, "HOLIDAY_CERTIFICATE", {"certificateId": row.id})
    second = _rep().be_report_preview(db, t.org.id, "HOLIDAY_CERTIFICATE", {"certificateId": row.id})
    assert first == second and first["sections"]["certificate"]["status"] == "APPROVED"


def test_generation_needs_an_active_template_and_supersedes_never_edits(db, world):
    from app.modules.payroll.models import GeneratedReport, ReportTemplate

    t, _out, employee = world
    params = {"employeeId": employee.id, "year": YEAR}
    with pytest.raises(Exception, match="(?i)active"):
        _rep().be_report_generate(db, t.org.id, "INDIVIDUAL_ACCOUNT", params, t.users[0].id)
    db.rollback()
    # test-only: stand in for a completed approval workflow (the real activation stays with the hook)
    template = db.query(ReportTemplate).filter_by(report_type="INDIVIDUAL_ACCOUNT", reporting_year=YEAR).one()
    template.status = "Active"
    db.commit()
    preview = _rep().be_report_preview(db, t.org.id, "INDIVIDUAL_ACCOUNT", params)
    assert preview["preview"] is False and "PREVIEW — TEMPLATE NOT APPROVED" not in preview["watermarks"]
    one = _rep().be_report_generate(db, t.org.id, "INDIVIDUAL_ACCOUNT", params, t.users[0].id)
    db.commit()
    two = _rep().be_report_generate(db, t.org.id, "INDIVIDUAL_ACCOUNT", params, t.users[0].id)
    db.commit()
    assert db.get(GeneratedReport, one.id).status == "Superseded" and two.status == "Generated"
    assert two.rendered_data["supersedesReportIds"] == [one.id]
    assert two.rendered_data["documentVersion"] == "BE-INDIVIDUAL-ACCOUNT-A"
    _no_niss(two.rendered_data)
