"""
tests/test_hong_kong_release_audit.py
-------------------------------------
Gaps found by the final HK release-closure audit (2026-10-01), each fixed and
pinned here:
* HK payslip PDF / payslip ZIP / bank-file downloads are access-logged (HK only), and the
  HK payslip PDF renders (it crashed: 2 identity rows for 3) with HK terminology;
* a correction is refused once the employee is no longer a Hong Kong employee;
* re-preparing an eMPF period supersedes its unsubmitted batches (no duplicate remittance);
* an IRD rejection of a filed return is recordable and re-preparable;
* the IR56B report exposes the per-field breakdown the payload already carries;
* IRD schema readiness: registration, hashing, supersession, validation (synthetic XSD — test only);
* cross-tenant reads of the HK list endpoints return none of the other tenant's data;
* release safety: seeding never activates anything.
"""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk, _employee, _item, _month, _other_org, _profile  # noqa: F401

# FILED needs the external-submission record (how the employer submitted).
INTERNAL_FILING = {"submissionMode": "INTERNAL_PREPARATION_ONLY", "authorizedSigner": "Director (test)"}


def test_hk_payslip_downloads_are_logged_and_other_countries_are_not(db, hk):
    from app.modules.payroll import hk_privacy
    from app.modules.payroll.models import PayrollRun, PayslipItem

    run = _month(db, hk.org, 4)
    item = _item(db, run, hk.emp)
    us_run = PayrollRun(organization_id=hk.org.id, period_label="us", period_start=date(2026, 4, 1),
                        period_end=date(2026, 4, 30), pay_date=date(2026, 4, 30))
    db.add(us_run)
    db.commit()
    us_item = PayslipItem(payroll_run_id=us_run.id, employee_id=hk.emp.id, organization_id=hk.org.id,
                          employee_name="x", country_code="US", gross_pay=D("1"), net_pay=D("1"))
    db.add(us_item)
    db.commit()
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.5"), headers={"user-agent": "t"})
    hk_privacy.log_payslip_access(db, hk.org.id, MAKER.id, [item.id, us_item.id], "DOWNLOAD_PAYSLIPS_ZIP",
                                  request=request, run_id=run.id)
    events = hk_privacy.list_access_events(db, hk.org.id)
    assert [(e["action"], e["resourceId"], e["employeeId"]) for e in events] == [
        ("DOWNLOAD_PAYSLIPS_ZIP", item.id, hk.emp.id)]
    other = _other_org(db, "HKAUDO")
    hk_privacy.log_payslip_access(db, other.id, MAKER.id, [item.id], "DOWNLOAD_PAYSLIP")   # not that tenant's payslip
    assert hk_privacy.list_access_events(db, other.id) == []


def test_hk_payslip_pdf_download_is_logged_over_http(db, hk):
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_org_scoped_principal, get_current_user
    from app.database import get_db
    from app.main import app
    from app.modules.billing.entitlements import require_active_subscription
    from app.modules.payroll import hk_privacy

    item = _item(db, _month(db, hk.org, 4), hk.emp)
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.update({get_db: lambda: db, get_current_user: lambda: operator,
                                     get_current_org_scoped_principal: lambda: operator,
                                     require_active_subscription: lambda: None})
    try:
        res = TestClient(app).get(f"/api/payroll/payslips/{item.id}/download")
        assert res.status_code == 200 and res.content[:5] == b"%PDF-"
        pdf = res.content
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
    assert [e["action"] for e in hk_privacy.list_access_events(db, hk.org.id)] == ["DOWNLOAD_PAYSLIP"]
    # HK terminology on the shared payslip renderer: no Indian payment rail / allowance labels
    import io
    import re

    pypdf = pytest.importorskip("pypdf")
    text = " ".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "MPF Mandatory Contribution (Employee)" in text and "Housing Allowance" in text
    for indian in ("NEFT", "HRA", "LOP", "TDS", "PAN", "Rupees"):
        assert not re.search(r"\b" + indian + r"\b", text), indian


def test_correction_is_refused_once_the_employee_left_the_hk_jurisdiction(db, hk):
    from fastapi import HTTPException

    from app.modules.payroll import hk_corrections

    item = _item(db, _month(db, hk.org, 4), hk.emp)
    hk.emp.country_code = "SG"
    db.commit()
    with pytest.raises(HTTPException, match="no longer a Hong Kong employee") as exc:
        hk_corrections.request_correction(db, hk.org.id, item.id, "x", MAKER.id)
    assert exc.value.status_code == 409


def test_preparing_an_empf_period_again_supersedes_its_unsubmitted_batch(db, hk):
    from app.modules.payroll import hk_service

    _month(db, hk.org, 4)
    first = hk_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    hk.emp.name = "Chan Corrected"           # member data corrected → a different batch (identical data is idempotent)
    db.commit()
    second = hk_service.prepare_empf_submission(db, hk.org.id, "2026-04", MAKER.id)
    db.refresh(first)
    assert first.status == "AMENDED" and any(f"#{second.id}" in e for e in first.validation_errors)
    assert second.status == "VALIDATED"
    live = [s for s in (first, second) if s.status in ("PREPARED", "VALIDATED")]
    assert live == [second]                                       # only one remittable batch per period


def test_an_ird_rejection_is_recorded_then_the_return_is_prepared_and_filed_again(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_service
    from app.modules.payroll.models import HkgIrdReportingCase

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    ar = hk_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    case = db.get(HkgIrdReportingCase, ar["employees"][0]["caseId"])
    hk_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id, filing_reference="IRD-1", submission=INTERNAL_FILING)
    with pytest.raises(BadRequestException, match="rejection reference"):
        hk_service.transition_ird_case(db, hk.org.id, case.id, "REJECTED", MAKER.id)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "REJECTED", MAKER.id, receipt_reference="IRD-REJ-7 format")
    assert case.status == "REJECTED" and case.filing_reference == "IRD-1"            # evidence kept
    with pytest.raises(BadRequestException):
        hk_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id, filing_reference="IRD-2", submission=INTERNAL_FILING)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "PREPARED", MAKER.id)
    assert not any("rejected by the IRD" in e for e in case.validation_errors)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)
    hk_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id, filing_reference="IRD-2", submission=INTERNAL_FILING)
    assert case.status == "FILED" and case.filing_reference == "IRD-2"


def test_ir56b_report_exposes_the_reportable_field_breakdown(db, hk):
    from app.modules.payroll import hk_service, service
    from tests.test_hong_kong_reports import _seeded

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    hk_service.generate_annual_return(db, hk.org.id, "2025/26", None)
    report = service.generate_hong_kong_ir56b(db, hk.org.id, _seeded(db, "HK-IR56B").id, hk.emp.id, "2025/26")
    values = report.rendered_data["employees"][0]["values"]
    assert values["ird_salary_wages"] is not None and values["ird_other_rewards_allowances"] is not None
    assert D(str(values["ird_salary_wages"])) + D(str(values["ird_other_rewards_allowances"])) == D(str(values["total_remuneration"]))


SYNTHETIC_XSD = """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <!-- TEST-ONLY synthetic schema. NOT an IRD schema. -->
  <xs:element name="Doc"><xs:complexType><xs:sequence>
    <xs:element name="Amount" type="xs:decimal"/>
  </xs:sequence></xs:complexType></xs:element>
</xs:schema>"""


def test_ird_schema_registry_hashes_supersedes_and_validates(db, tmp_path):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_ird_schema

    assert {r["status"] for r in hk_ird_schema.readiness(db, "2025/26")} == {"EXTERNAL SCHEMA REQUIRED"}
    xsd = tmp_path / "synthetic.xsd"
    xsd.write_text(SYNTHETIC_XSD, encoding="utf8")
    first = hk_ird_schema.register_schema(db, "IR56B", "2025/26", str(xsd))
    assert hk_ird_schema.register_schema(db, "IR56B", "2025/26", str(xsd)).id == first.id     # idempotent
    rows = {r["form"]: r for r in hk_ird_schema.readiness(db, "2025/26")}
    assert rows["IR56B"]["status"] == "REGISTERED — AWAITING REVIEW" and rows["BIR56A"]["status"] == "EXTERNAL SCHEMA REQUIRED"
    xsd.write_text(SYNTHETIC_XSD.replace("xs:decimal", "xs:integer"), encoding="utf8")
    second = hk_ird_schema.register_schema(db, "IR56B", "2025/26", str(xsd))
    db.refresh(first)
    assert second.id != first.id and first.superseded_by_id == second.id and second.checksum_sha256 != first.checksum_sha256
    assert hk_ird_schema.validate(b"<Doc><Amount>12</Amount></Doc>", str(xsd)) == []
    assert hk_ird_schema.validate(b"<Doc><Amount>x</Amount></Doc>", str(xsd))
    assert hk_ird_schema.validate(b"<Doc>", str(xsd))[0].startswith("not well-formed")
    with pytest.raises(BadRequestException):
        hk_ird_schema.register_schema(db, "P60", "2025/26", str(xsd))


def test_hk_list_endpoints_never_return_another_tenants_data_over_http(db, hk):
    from fastapi.testclient import TestClient

    from app.core.dependencies import get_current_org_scoped_principal, get_current_user
    from app.database import get_db
    from app.main import app
    from app.modules.billing.entitlements import require_active_subscription
    from app.modules.payroll import hk_corrections, hk_privacy, hk_service

    item = _item(db, _month(db, hk.org, 4), hk.emp)
    hk.emp.ctc = hk.emp.ctc + D("24000")
    db.commit()
    hk_corrections.request_correction(db, hk.org.id, item.id, "x", MAKER.id)
    hk_privacy.place_legal_hold(db, hk.org.id, hk.emp.id, "enquiry", None, MAKER.id)
    hk_privacy.record_access(db, hk.org.id, MAKER.id, "VIEW_STATUTORY_PROFILE", "employee_statutory_profile",
                             employee_id=hk.emp.id)
    hk_service.calculate_termination(db, hk.org.id, hk.emp.id, {"terminationDate": "2026-06-30", "reason": "RESIGNATION",
                                                                "postTransitionWage": "20000"}, MAKER.id)
    other = _other_org(db, "HKAUDB")
    intruder = SimpleNamespace(id=CHECKER.id, organization_id=other.id, role="payroll_admin", is_active=True)
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.update({get_db: lambda: db, get_current_user: lambda: intruder,
                                     get_current_org_scoped_principal: lambda: intruder,
                                     require_active_subscription: lambda: None})
    try:
        client = TestClient(app)
        for path in ("/api/payroll/hong-kong/corrections", "/api/payroll/hong-kong/legal-holds",
                     "/api/payroll/hong-kong/access-events", "/api/payroll/hong-kong/termination-results",
                     "/api/payroll/hong-kong/ird/cases", "/api/payroll/hong-kong/tax-clearance",
                     "/api/payroll/hong-kong/empf/submissions"):
            res = client.get(path)
            assert res.status_code == 200 and res.json() == [], path               # no data, not just a status
        assert client.get(f"/api/payroll/hong-kong/employees/{hk.emp.id}/average-wage-snapshots").status_code == 404
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


def test_seeding_never_activates_hong_kong(db):
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all
    from scripts.seed_statutory_report_templates import seed_hong_kong
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack, ReportTemplate

    seed_hong_kong_all(db)
    seed_hong_kong(db)
    db.commit()
    assert {p.status for p in db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "HK")} == {"Draft"}
    assert {t.status for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "HK")} == {"Draft"}
    org = _other_org(db, "HKSAFE")
    out = service.hk_employer_readiness(db, org.id)
    assert out["serviceRegistry"] != "AVAILABLE" and "HK_PACK_NOT_ACTIVE" in {c["code"] for c in out["checks"]}
