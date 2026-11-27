"""
tests/test_payslip_template_diagnostics.py
------------------------------------------
Why a payslip falls back to the standard format (exact-layout work, P6):

  * preview / Sample PDF with a real payslip (payslipId, org-scoped) render
    that payslip with the draft's settings, or return a diagnostic:
    TIE_OUT_MISMATCH (with the amounts and, for LWF, the explanation),
    PAYSLIP_BLOCKED, BELGIUM, RENDER_ERROR, ENGINE_FAILURE;
  * the 404 / 409 from the rendered-payslip path carry the same reason;
  * downloads / e-mails still never fail: template_pdf_or_none returns None
    and logs the reason.
"""
import logging
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.organizations.models import Organization
from app.modules.payroll import payslip_template_service as tpl
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

_HTML = tpl.STARTERS["CLASSIC_NAVY"]["html"]
_CSS = tpl.STARTERS["CLASSIC_NAVY"]["css"]


def _org(db, code):
    org = Organization(organization_name=f"Org {code}", organization_code=code, country="IN")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _payslip(db, org, *, country="IN", lwf=None, status="Pending"):
    emp = PayrollEmployee(organization_id=org.id, employee_code=f"E-{org.id}-{country}", name="Asha Rao",
                          country_code=country, ctc=Decimal("960000"))
    db.add(emp)
    run = PayrollRun(organization_id=org.id, run_code=f"RUN-{org.id}-{country}-{status}", period_label="June 2026",
                     pay_date=date(2026, 6, 30), period_start=date(2026, 6, 1),
                     period_end=date(2026, 6, 30), status="Draft")
    db.add(run)
    db.flush()
    lwf = lwf or Decimal("0")
    item = PayslipItem(
        organization_id=org.id, payroll_run_id=run.id, employee_id=emp.id, employee_name="Asha Rao",
        country_code=country, basic_salary=Decimal("50000"), hra=Decimal("20000"),
        special_allowance=Decimal("10000"), gross_pay=Decimal("80000"),
        tds=Decimal("5000"), pf=Decimal("1800"), professional_tax=Decimal("200"), employee_lwf=lwf,
        total_deductions=Decimal("7000") + lwf, net_pay=Decimal("73000") - lwf, status=status,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_preview_with_a_real_payslip_renders_it(db):
    org = _org(db, "DG_A")
    item = _payslip(db, org)
    out = tpl.preview(_HTML, _CSS, None, "IN", db=db, organization_id=org.id, payslip_id=item.id)
    assert out["diagnostics"] is None
    assert "Asha Rao" in out["renderedHtml"] and "₹ 73,000.00" in out["renderedHtml"]
    assert "Sample Employee" not in out["renderedHtml"]


def test_sample_preview_has_no_diagnostics():
    out = tpl.preview(_HTML, _CSS, None, "IN")
    assert out["diagnostics"] is None and "Sample Employee" in out["renderedHtml"]


def test_tie_out_mismatch_explains_lwf(db):
    org = _org(db, "DG_B")
    item = _payslip(db, org, lwf=Decimal("25"))
    out = tpl.preview(_HTML, _CSS, None, "IN", db=db, organization_id=org.id, payslip_id=item.id)
    d = out["diagnostics"]
    assert out["renderedHtml"] == "" and d["code"] == "TIE_OUT_MISMATCH"
    assert d["detail"]["storedTotalDeductions"] == 7025.0 and d["detail"]["deductionLines"] == 7000.0
    assert d["detail"]["deductionsDifference"] == 25.0 and d["detail"]["earningsDifference"] == 0.0
    assert any("Labour Welfare Fund" in e for e in d["detail"]["explanation"])
    with pytest.raises(HTTPException) as exc:
        tpl.preview_pdf(_HTML, _CSS, None, "IN", db=db, organization_id=org.id, payslip_id=item.id)
    assert exc.value.status_code == 409 and exc.value.detail["code"] == "TIE_OUT_MISMATCH"


def test_blocked_and_belgian_payslips(db):
    org = _org(db, "DG_C")
    blocked = _payslip(db, org, status="Failed")
    out = tpl.preview(_HTML, _CSS, None, "IN", db=db, organization_id=org.id, payslip_id=blocked.id)
    assert out["diagnostics"]["code"] == "PAYSLIP_BLOCKED"
    be = _payslip(db, org, country="BE")
    out = tpl.preview(_HTML, _CSS, None, "IN", db=db, organization_id=org.id, payslip_id=be.id)
    assert out["diagnostics"]["code"] == "BELGIUM"


def test_other_organisations_payslip_is_not_found(db):
    org_a, org_b = _org(db, "DG_D1"), _org(db, "DG_D2")
    item = _payslip(db, org_a)
    with pytest.raises(HTTPException) as exc:
        tpl.preview(_HTML, _CSS, None, "IN", db=db, organization_id=org_b.id, payslip_id=item.id)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        tpl.preview(_HTML, _CSS, None, "IN", db=db, organization_id=org_a.id, payslip_id="abc")
    assert exc.value.status_code == 400


def test_render_error_with_real_data(db):
    org = _org(db, "DG_E")
    item = _payslip(db, org)
    # Fine with sample data (payable_days is a number there), fails on None.
    html = _HTML + "{{ payroll.payable_days + 1 }}"
    assert tpl.preview(html, _CSS, None, "IN")["diagnostics"] is None
    out = tpl.preview(html, _CSS, None, "IN", db=db, organization_id=org.id, payslip_id=item.id)
    assert out["diagnostics"]["code"] == "RENDER_ERROR" and out["renderedHtml"] == ""


def test_engine_failure_is_a_diagnostic(monkeypatch):
    def boom(*_a, **_k):
        raise tpl.PdfRenderError("engine down")
    monkeypatch.setattr(tpl, "html_to_pdf", boom)
    with pytest.raises(HTTPException) as exc:
        tpl.preview_pdf(_HTML, _CSS, None, "IN")
    assert exc.value.status_code == 422 and exc.value.detail["code"] == "ENGINE_FAILURE"
    assert "engine down" in exc.value.detail["message"]


def test_rendered_path_carries_the_reason_and_downloads_never_fail(db, caplog):
    org = _org(db, "DG_F")
    item = _payslip(db, org, lwf=Decimal("25"))
    with pytest.raises(HTTPException) as exc:
        tpl.render_payslip(db, org.id, item.id)
    assert exc.value.status_code == 404 and exc.value.detail["reason"] == "NOT_ASSIGNED"
    t = tpl.create_template(db, org.id, None, {"starter": "CLASSIC_NAVY"})
    tpl.publish_template(db, org.id, t["id"], None)
    tpl.assign_template(db, org.id, None, t["id"], None)
    with pytest.raises(HTTPException) as exc:
        tpl.render_payslip(db, org.id, item.id)
    assert exc.value.detail["code"] == "TEMPLATE_NOT_REPRESENTABLE"
    assert exc.value.detail["reason"] == "TIE_OUT_MISMATCH" and exc.value.detail["detail"]["deductionsDifference"] == 25.0
    with caplog.at_level(logging.INFO, logger="zoiko_payroll.payslip_templates"):
        assert tpl.template_pdf_or_none(db, item.id, org.id) is None
    assert "TIE_OUT_MISMATCH" in caplog.text


def test_engine_failure_on_download_falls_back_and_logs(db, caplog, monkeypatch):
    org = _org(db, "DG_G")
    item = _payslip(db, org)
    t = tpl.create_template(db, org.id, None, {"starter": "CLASSIC_NAVY"})
    tpl.publish_template(db, org.id, t["id"], None)
    tpl.assign_template(db, org.id, None, t["id"], None)

    def boom(*_a, **_k):
        raise tpl.PdfRenderError("engine down")
    monkeypatch.setattr(tpl, "html_to_pdf", boom)
    with caplog.at_level(logging.WARNING, logger="zoiko_payroll.payslip_templates"):
        assert tpl.template_pdf_or_none(db, item.id, org.id) is None
    assert "ENGINE_FAILURE" in caplog.text
