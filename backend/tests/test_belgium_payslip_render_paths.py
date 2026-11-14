"""Belgium (ZP-BE-ENG-001) Block H1: every payslip render path after main's PR #158 (templates).

A Belgian payslip PDF / view is produced only from its frozen be_calculation_snapshot (spec §11), prints the
NISS / BIS masked only, carries the DEMO watermark for a demo payslip, and is never rendered through an
organisation payslip template (HTML view, xhtml2pdf PDF, preview, import / assignment) — those refuse with a
clear message. A Belgian payslip without a snapshot is refused, never printed in a generic layout."""
import io
import re

import pytest
from fastapi import HTTPException

LABEL = "DEMO — NOT FOR PAYROLL"


@pytest.fixture
def demo_month(db, monkeypatch):
    from app.config import settings
    from app.core import code_generation
    from app.modules.payroll import belgium_demo
    from tests._mx_employer_helpers import make_org

    counter = iter(range(1, 10_000))                   # SQLite seam: no PostgreSQL advisory lock
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter):05d}")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    t = make_org(db, name="DEMO Belgium BV", code="BEDEMO", admins=2, country="BE")
    monkeypatch.setattr(settings, "BE_DEMO_ORG_IDS", str(t.org.id))
    belgium_demo.be_seed_demo_pack(db)
    db.commit()
    out = belgium_demo.be_seed_demo_month(db, t.org.id, t.users[0].id, t.users[1].id)
    return t, out


def _pdf_pages(pdf: bytes):
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [((page.filter(lambda o: o.get("object_type") != "char" or not _rotated(o)).extract_text() or ""),
                 "".join(c["text"] for c in page.chars if _rotated(c)))
                for page in doc.pages]


def _rotated(char) -> bool:                                                  # the diagonal watermark glyphs
    return abs((char.get("matrix") or (1, 0))[1]) > 0.5


def test_demo_payslip_pdf_is_watermarked_on_every_page_shows_s11_and_no_niss(db, demo_month):
    from app.modules.payroll import service

    t, out = demo_month
    for payslip_id in out["payslips"]:
        pdf = service.generate_payslip_pdf_bytes(db, payslip_id, t.org.id)
        assert pdf.startswith(b"%PDF")
        pages = _pdf_pages(pdf)
        assert pages
        for text, rotated in pages:
            flat = rotated.replace(" ", "")                                   # the diagonal watermark, every page
            assert flat.startswith("DEMO") and flat.endswith("NOTFORPAYROLL")
        body = "\n".join(text for text, _ in pages)
        assert "BE-PAYSLIP-1" in body and "Net pay" in body and "Employee ONSS" in body
        assert not re.search(r"\d{2}\.?\d{2}\.?\d{2}-?\d{3}\.?\d{2}", body.replace(" ", ""))   # no NISS shape


def test_a_digit_in_the_snapshot_identifier_is_never_printed(db, demo_month):
    from sqlalchemy.orm.attributes import flag_modified

    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    t, out = demo_month
    item = db.get(PayslipItem, out["payslips"][0])
    snap = dict(item.be_calculation_snapshot)
    snap["identifierMasked"] = "85073003300"                             # checksum-invalid synthetic value
    item.be_calculation_snapshot = snap
    flag_modified(item, "be_calculation_snapshot")
    db.commit()
    body = "\n".join(text for text, _ in _pdf_pages(service.generate_payslip_pdf_bytes(db, item.id, t.org.id)))
    assert "85073003300" not in body.replace(" ", "") and "identifier vault" in body


def test_a_belgian_payslip_without_snapshot_is_refused_never_generic(db, demo_month):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    t, out = demo_month
    item = db.get(PayslipItem, out["payslips"][0])
    item.be_calculation_snapshot = None
    db.commit()
    with pytest.raises(HTTPException) as raised:
        service.generate_payslip_pdf_bytes(db, item.id, t.org.id)
    assert raised.value.status_code == 409 and raised.value.detail["code"] == "BE_PAYSLIP_NO_SNAPSHOT"


def test_templates_never_render_or_attach_to_a_belgian_payslip(db, demo_month):
    from app.modules.payroll import payslip_template_service as tpl
    from app.modules.payroll.models import PayslipItem, PayslipTemplateAssignment

    t, out = demo_month
    org, actor = t.org.id, t.users[0].id
    for data in ({"name": "BE layout", "country": "BE"}, {"name": "BE layout", "country": "be"}):
        with pytest.raises(HTTPException, match="do not apply to Belgium"):
            tpl.create_template(db, org, actor, data)
    created = tpl.create_template(db, org, actor, {"name": "All countries"})
    template_id = created.get("id") or created.get("template", {}).get("id")
    tpl.publish_template(db, org, template_id, actor)
    with pytest.raises(HTTPException, match="do not apply to Belgium"):
        tpl.assign_template(db, org, actor, template_id, "BE")
    with pytest.raises(HTTPException, match="do not apply to Belgium"):
        tpl.preview("<p>{{ employee.name }}</p>", None, None, "BE", db, org)
    tpl.assign_template(db, org, actor, template_id, "ALL")                    # covers every country ...
    db.commit()
    assert db.query(PayslipTemplateAssignment).filter_by(organization_id=org).count() == 1
    payslip_id = out["payslips"][0]
    for render in (tpl.render_payslip, tpl.render_payslip_pdf):                 # ... but never a Belgian payslip
        with pytest.raises(HTTPException) as raised:
            render(db, org, payslip_id)
        assert raised.value.status_code == 409 and "Belgium" in raised.value.detail["message"]
    assert tpl.template_pdf_or_none(db, payslip_id, org) is None
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun

    run = db.get(PayrollRun, db.get(PayslipItem, payslip_id).payroll_run_id)
    tpl.freeze_run_templates(db, run)
    db.commit()
    assert all(i.template_version_id is None for i in db.query(PayslipItem).filter_by(payroll_run_id=run.id))
    body = "\n".join(text for text, _ in _pdf_pages(service.generate_payslip_pdf_bytes(db, payslip_id, org)))
    assert "BE-PAYSLIP-1" in body                                               # still the Belgian §11 PDF


def test_download_routes_serve_the_belgian_pdf(db, demo_month, monkeypatch):
    from app.modules.payroll import belgium_payslip_pdf as bpdf
    from app.modules.payroll import service

    t, out = demo_month
    calls = []
    real = bpdf.be_payslip_pdf_bytes
    monkeypatch.setattr(bpdf, "be_payslip_pdf_bytes", lambda *a, **k: calls.append(a) or real(*a, **k))
    for payslip_id in out["payslips"]:
        service.generate_payslip_pdf_bytes(db, payslip_id, t.org.id)            # single download / ZIP / e-mail
    assert len(calls) == len(out["payslips"])
