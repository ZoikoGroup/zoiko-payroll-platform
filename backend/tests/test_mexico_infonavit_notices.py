"""Mexico Phase 4b — INFONAVIT credit notices (MX-031/MX-032): a credit
deduction exists only from the authority's notice with evidence; method and
value are copied from it; one open notice per credit; MODIFICACION
supersedes, SUSPENSION closes; tenant isolation. SYNTHETIC data."""

from datetime import date
from decimal import Decimal

import pytest

from tests._mx_employer_helpers import (
    ORG_BASE, enable_mx_onboarding, evidence_doc, http, make_org, new_mx_employee, principal,
)


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    enable_mx_onboarding(monkeypatch)


def _notice(db, org_id, emp_id, **over):
    from app.modules.payroll import mexico_employee_service as svc

    data = {"credit_number": "CR-SYN-1", "notice_type": "RETENCION", "discount_method": "PERCENTAGE",
            "discount_value": "20", "effective_from": date(2026, 3, 1), "authority_reference": "AVISO-SYN-1"}
    data.update(over)
    return svc.record_infonavit_notice(db, org_id, emp_id, data, 701)


def _setup(db):
    t = make_org(db)
    return t, new_mx_employee(db, t.org.id), evidence_doc(db, t.org.id)


def test_evidence_is_required(db):
    from app.core.exceptions import BadRequestException

    t, emp, _doc = _setup(db)
    with pytest.raises(BadRequestException, match="attach the INFONAVIT notice itself"):
        _notice(db, t.org.id, emp.id)


def test_retencion_needs_method_and_value_suspension_none(db):
    from app.core.exceptions import BadRequestException

    t, emp, doc = _setup(db)
    with pytest.raises(BadRequestException, match="discount method"):
        _notice(db, t.org.id, emp.id, discount_method=None, evidence_document_id=doc.id)
    with pytest.raises(BadRequestException, match="no open notice"):
        _notice(db, t.org.id, emp.id, notice_type="SUSPENSION", discount_method=None, discount_value=None,
                evidence_document_id=doc.id)


def test_lifecycle_retencion_modificacion_suspension(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_employee_service as svc

    t, emp, doc = _setup(db)
    first = _notice(db, t.org.id, emp.id, evidence_document_id=doc.id)
    with pytest.raises(BadRequestException, match="already has an open notice"):
        _notice(db, t.org.id, emp.id, evidence_document_id=doc.id)
    _notice(db, t.org.id, emp.id, notice_type="MODIFICACION", discount_value="25", effective_from=date(2026, 7, 1),
            evidence_document_id=doc.id)
    _notice(db, t.org.id, emp.id, notice_type="SUSPENSION", discount_method=None, discount_value=None,
            effective_from=date(2026, 9, 1), evidence_document_id=doc.id)
    rows = svc.list_infonavit_notices(db, t.org.id, emp.id)
    assert [(r["noticeType"], r["status"]) for r in rows] == [
        ("RETENCION", "SUPERSEDED"), ("MODIFICACION", "CLOSED"), ("SUSPENSION", "CLOSED")]
    assert rows[0]["effectiveTo"] == "2026-06-30" and Decimal(first["discountValue"]) == Decimal("20")


def test_notice_routes_over_http_and_isolation(db):
    t, emp, doc = _setup(db)
    other = make_org(db, name="Other", code="OTHER")
    body = {"creditNumber": "CR-SYN-2", "noticeType": "RETENCION", "discountMethod": "FIXED_AMOUNT",
            "discountValue": "150", "effectiveFrom": "2026-03-01", "authorityReference": "AVISO-2",
            "evidenceDocumentId": doc.id}
    with http(db, principal(t.org.id)) as c:
        r = c.post(f"{ORG_BASE}/employees/{emp.id}/infonavit-notices", json=body)
        assert r.status_code == 200, r.text
        record = c.get(f"{ORG_BASE}/employees/{emp.id}").json()
        assert record["infonavitNotices"][0]["creditNumber"] == "CR-SYN-2"
        assert all("*" in v for v in record["identifiers"].values())          # masked
    with http(db, principal(other.org.id, user_id=880)) as c:
        assert c.get(f"{ORG_BASE}/employees/{emp.id}").status_code == 404
        assert c.post(f"{ORG_BASE}/employees/{emp.id}/infonavit-notices", json=body).status_code == 404
    with http(db, principal(t.org.id, user_id=702, role="payroll_admin")) as c:
        assert c.post(f"{ORG_BASE}/employees/{emp.id}/infonavit-notices", json=body).status_code == 403
