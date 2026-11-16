"""Recibo de nómina v2.0 — the dedicated Mexican payslip (docs/mexico/
MEXICO_RECIBO_REPORT.md). SYNTHETIC worlds (the 11b ready world, the mock PAC
and the real builder); every assertion compares against the committed
snapshot, the CFDI document row or the stored stamped XML."""

import io
import re
from datetime import date
from decimal import Decimal as D

import pytest

UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


def _svc():
    from app.modules.payroll import mexico_payslip_service

    return mexico_payslip_service


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def _draft(db, monkeypatch, tmp_path, code):
    from tests import _mx_run_helpers as rh
    from tests.test_mexico_cfdi_builder import _ready_world

    w = _ready_world(db, monkeypatch, tmp_path, code)
    (item,) = rh.mx_items(db, w.run)
    return w, item


def _stamped(db, monkeypatch, tmp_path, code):
    from tests import _mx_run_helpers as rh
    from tests.test_mexico_cfdi_receipt import _stamped as stamp

    w, doc = stamp(db, monkeypatch, tmp_path, code)
    (item,) = rh.mx_items(db, w.run)
    return w, item, doc


def _pdf(db, w, item):
    from app.modules.payroll import service

    return service.generate_payslip_pdf_bytes(db, item.id, w.org.id)


def _money(v):
    return _svc().money(v)


# ── layout and figures ───────────────────────────────────────────────────────

def test_mx_pdf_is_the_recibo_and_has_no_india_layout(db, monkeypatch, tmp_path):
    w, item = _draft(db, monkeypatch, tmp_path, "MXRB01")
    text = _text(_pdf(db, w, item))
    for forbidden in ("HRA", "House Rent", "LOP", "NEFT", "Loss of Pay", "Rupees"):
        assert forbidden not in text
    for required in ("Recibo de nómina / Payslip", "COUNTRY PACK 24 / MÉXICO / MXN", "Percepciones / Earnings",
                     "Deducciones / Employee deductions", "Resumen / Totals", "Timbre fiscal / SAT status",
                     "EMISOR / EMPLOYER", "RECEPTOR / EMPLOYEE", "NÓMINA / PERIODO", "NETO A PAGAR",
                     "MX-RECIBO-2.0.0"):
        assert required in text


def test_every_amount_equals_the_snapshot(db, monkeypatch, tmp_path):
    w, item = _draft(db, monkeypatch, tmp_path, "MXRB02")
    res = item.mx_calculation_snapshot["result"]
    text = _text(_pdf(db, w, item))
    for value in (res["gross"], res["isr_withheld"], res["imss_employee"], res["imss_employer"],
                  res["infonavit_employer"], res["isn"]["amount"], res["employer_total"],
                  item.total_deductions, item.net_pay):
        assert _money(value) in text, value
    view = _svc().recibo_view(db, item, w.run)
    assert view["totals"] == {"gross": _money(item.gross_pay), "deductions": _money(item.total_deductions),
                              "net": _money(item.net_pay), "currency": "MXN"}
    assert view["footer"]["snapshotHash"] == item.mx_calculation_snapshot["inputHash"][:12]


def test_gross_minus_deductions_is_net_and_inconsistent_data_refuses(db, monkeypatch, tmp_path):     # MX-T045
    from app.core.exceptions import BadRequestException

    w, item = _draft(db, monkeypatch, tmp_path, "MXRB03")
    view = _svc().recibo_view(db, item, w.run)
    assert D(view["totals"]["gross"].replace(",", "")) - D(view["totals"]["deductions"].replace(",", "")) == \
        D(view["totals"]["net"].replace(",", ""))
    item.net_pay = item.net_pay + D("1.00")                     # SYNTHETIC corruption: never "fixed" for display
    with pytest.raises(BadRequestException):
        _svc().recibo_view(db, item, w.run)


def test_no_single_opaque_net_figure(db, monkeypatch, tmp_path):
    """Lines are mandatory: a result whose earnings lines do not add up to the
    gross is refused rather than shown as one net figure."""
    from app.core.exceptions import BadRequestException

    w, item = _draft(db, monkeypatch, tmp_path, "MXRB04")
    view = _svc().recibo_view(db, item, w.run)
    assert view["perceptions"] and view["deductions"]
    snap = dict(item.mx_calculation_snapshot)
    snap["result"] = {**snap["result"], "concepts": []}
    item.mx_calculation_snapshot = snap
    with pytest.raises(BadRequestException):
        _svc().recibo_view(db, item, w.run)


def test_employer_infonavit_is_never_a_deduction(db, monkeypatch, tmp_path):                          # MX-T018
    w, item = _draft(db, monkeypatch, tmp_path, "MXRB05")
    res = item.mx_calculation_snapshot["result"]
    view = _svc().recibo_view(db, item, w.run)
    keys = {l["key"] for l in view["deductions"]}
    assert keys <= {"ISR_WITHHELD", "IMSS_EMPLOYEE", "INFONAVIT_CREDIT", "OTHER_AUTHORISED"}
    assert all("patronal" not in l["concept"].lower() for l in view["deductions"])
    assert _money(res["infonavit_employer"]) not in {l["amount"] for l in view["deductions"]}
    assert view["employer"]["infonavit"] == _money(res["infonavit_employer"])
    text = _text(_pdf(db, w, item))
    deductions = text.split("Deducciones / Employee deductions")[1].split("Resumen / Totals")[0]
    assert "INFONAVIT" not in deductions or "Crédito INFONAVIT" in deductions
    assert "NO se descuentan" in text


def test_es_mx_formatting_and_accents(db, monkeypatch, tmp_path):                                     # MX-T043
    s = _svc()
    assert s.money(D("40000")) == "40,000.00" and s.money("1234567.891") == "1,234,567.89"
    assert s.period_es(date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 15)) == "01–15 oct 2026 · pago 15 oct"
    assert s.period_es(date(2026, 9, 26), date(2026, 10, 10), date(2026, 10, 12)) == \
        "26 sep – 10 oct 2026 · pago 12 oct"
    assert s.date_es(date(2026, 1, 5)) == "05 ene 2026"
    w, item = _draft(db, monkeypatch, tmp_path, "MXRB06")
    text = _text(_pdf(db, w, item))
    for word in ("nómina", "Régimen fiscal", "días", "MÉXICO", "Página", "aportación", "VÁLIDO", "patrón", "–", "·"):
        assert word in text, word


# ── identifiers ──────────────────────────────────────────────────────────────

def test_identifiers_are_masked_everywhere(db, monkeypatch, tmp_path):                                # MX-T038
    import json

    from tests.test_mexico_cfdi_builder import GOOD_IDS

    w, item, _doc = _stamped(db, monkeypatch, tmp_path, "MXRB07")
    view = _svc().recibo_view(db, item, w.run)
    blob = json.dumps(view, default=str) + json.dumps(_svc().mobile_summary(view), default=str)
    text = _text(_pdf(db, w, item))
    from app.modules.payroll import mexico_cfdi_service as S

    version, _root, _cred = S._employer_for(db, item, w.run.pay_date)
    for full in (*GOOD_IDS.values(), version.rfc):
        assert full not in blob and full not in text, full
    assert view["parties"]["employee"]["nss"] == "********901"
    assert view["parties"]["employee"]["rfc"].endswith(GOOD_IDS["rfc"][-3:])


# ── CFDI and payment states ──────────────────────────────────────────────────

def test_draft_has_no_uuid_seal_or_qr(db, monkeypatch, tmp_path):                                     # MX-T013
    w, item = _draft(db, monkeypatch, tmp_path, "MXRB08")
    view = _svc().recibo_view(db, item, w.run)
    assert view["fiscal"]["state"] == "DRAFT"
    assert view["fiscal"]["sat"] == {"uuid": "NO DISPONIBLE", "stamp": "SIN TIMBRADO", "seal": "NO DISPONIBLE",
                                     "xmlQr": "NO EMITIDOS"}
    text = _text(_pdf(db, w, item))
    assert "BORRADOR / NO TIMBRADO · SIN UUID · SIN SELLO SAT · NO FISCALMENTE VÁLIDO · NO ACREDITA PAGO" in text
    assert not UUID_RE.search(text) and "verificacfdi" not in text and "CFDI TIMBRADO" not in text


def test_payroll_approval_alone_is_never_issued(db, monkeypatch, tmp_path):
    w, item = _draft(db, monkeypatch, tmp_path, "MXRB09")
    assert w.run.status == "Approved"
    view = _svc().recibo_view(db, item, w.run)
    assert view["fiscal"]["label"] == "NO TIMBRADO" and view["fiscal"]["documentState"] == "BORRADOR"
    assert "NO timbrado" in view["subtitle"]


def test_stamped_reads_the_uuid_from_the_stored_xml_and_keeps_payment_separate(db, monkeypatch, tmp_path):
    from app.core import object_storage
    from app.modules.payroll import mexico_cfdi_service as S

    w, item, doc = _stamped(db, monkeypatch, tmp_path, "MXRB10")
    view = _svc().recibo_view(db, item, w.run)
    assert view["fiscal"]["state"] == "STAMPED" and view["fiscal"]["sat"]["uuid"] == doc.uuid
    assert doc.uuid.encode() in object_storage.read_bytes(S.stamped_xml_ref(db, doc))
    assert view["payment"] == {"status": "NONE", "label": "pendiente", "paid": False}
    text = _text(_pdf(db, w, item))
    assert "CFDI TIMBRADO" in text and "PAGO: PENDIENTE" in text and "Pago: pagado" not in text
    assert doc.uuid in text


def test_stamped_view_does_not_trust_the_document_row_for_the_uuid(db, monkeypatch, tmp_path):
    """If the stored XML is gone, the UUID is NOT taken from the row."""
    w, item, doc = _stamped(db, monkeypatch, tmp_path, "MXRB11")
    monkeypatch.setattr("app.modules.payroll.mexico_cfdi_service.stamped_xml_ref", lambda db, d: None)
    view = _svc().recibo_view(db, item, w.run)
    assert view["fiscal"]["state"] == "STAMPED_XML_MISSING" and doc.uuid not in str(view)


def test_a_settled_payment_is_shown_as_paid_and_never_as_a_stamp(db, monkeypatch, tmp_path):
    from app.modules.payroll.models import PayrollMxPaymentBatch, PayrollMxPaymentItem

    w, item = _draft(db, monkeypatch, tmp_path, "MXRB12")
    b = PayrollMxPaymentBatch(organization_id=w.org.id, payroll_run_id=w.run.id, status="RELEASED",
                              idempotency_key="SYN-RB12")                                       # SYNTHETIC
    db.add(b)
    db.flush()
    db.add(PayrollMxPaymentItem(organization_id=w.org.id, batch_id=b.id, employee_id=item.employee_id,
                                payslip_item_id=item.id, clabe_last4="0000", amount=item.net_pay, status="SETTLED"))
    db.commit()
    view = _svc().recibo_view(db, item, w.run)
    assert view["payment"]["label"] == "pagado" and view["fiscal"]["state"] == "DRAFT"
    assert "BORRADOR / NO TIMBRADO" in view["ribbon"]               # paid does not make it issued


def test_a_cancelled_cfdi_is_never_the_current_receipt(db, monkeypatch, tmp_path):                    # MX-T012
    w, item, doc = _stamped(db, monkeypatch, tmp_path, "MXRB13")
    doc.status, doc.replaced_by_uuid = "CANCELLED", "SYN00000-0000-4000-8000-00000000RB13"         # SYNTHETIC
    db.commit()
    view = _svc().recibo_view(db, item, w.run)
    assert view["fiscal"]["current"] is False and view["fiscal"]["label"] == "CANCELADO"
    text = _text(_pdf(db, w, item))
    assert "CFDI CANCELADO · NO ES EL RECIBO VIGENTE" in text and "SUSTITUIDO POR" in text
    assert "(CANCELADO)" in text and "CFDI TIMBRADO" not in text


def test_no_fake_qr_or_seal(db, monkeypatch, tmp_path):
    w, item, _doc = _stamped(db, monkeypatch, tmp_path, "MXRB14")
    from pypdf import PdfReader

    pdf = _pdf(db, w, item)
    reader = PdfReader(io.BytesIO(pdf))
    assert all("/Annots" not in p for p in reader.pages)          # nothing clickable
    assert all(not p.images for p in reader.pages)                # no QR image on the payslip
    assert "Anexo 20 I.D" in _text(pdf)                          # points at the printed CFDI instead


# ── no writes, duplicate, history, summary, watermark ────────────────────────

def test_rendering_never_writes_or_reissues(db, monkeypatch, tmp_path):
    from app.modules.payroll import service
    from app.modules.payroll.models import GeneratedReport, PayrollMxCfdiDocument, PayrollMxCfdiEvent

    w, item, doc = _stamped(db, monkeypatch, tmp_path, "MXRB15")
    before = (db.query(GeneratedReport).count(), db.query(PayrollMxCfdiDocument).count(),
              db.query(PayrollMxCfdiEvent).count(), doc.status, doc.uuid, doc.updated_at)
    _pdf(db, w, item)
    service.generate_mx_payslip_duplicate_pdf_bytes(db, item.id, w.org.id)
    db.refresh(doc)
    assert (db.query(GeneratedReport).count(), db.query(PayrollMxCfdiDocument).count(),
            db.query(PayrollMxCfdiEvent).count(), doc.status, doc.uuid, doc.updated_at) == before


def test_duplicate_is_marked_and_refuses_non_mexican_or_uncalculated(db, monkeypatch, tmp_path):     # MX24-PAY-010
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    w, item = _draft(db, monkeypatch, tmp_path, "MXRB16")
    text = _text(service.generate_mx_payslip_duplicate_pdf_bytes(db, item.id, w.org.id))
    assert "DUPLICADO" in text and "MX24-PAY-010" in text
    snap = dict(item.mx_calculation_snapshot)
    item.mx_calculation_snapshot = {"blocked": True, "code": "SYN", "reason": "SYNTHETIC"}
    db.commit()
    with pytest.raises(BadRequestException):
        service.generate_mx_payslip_duplicate_pdf_bytes(db, item.id, w.org.id)
    item.mx_calculation_snapshot = snap
    db.commit()


def test_pay_history_extract(db, monkeypatch, tmp_path):                                               # MX24-PAY-011
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_payslip_pdf

    w, item = _draft(db, monkeypatch, tmp_path, "MXRB17")
    h = _svc().pay_history(db, w.org.id, item.employee_id, date(2026, 1, 1), date(2026, 12, 31))
    assert h["count"] == 1 and h["rows"][0]["net"] == _money(item.net_pay) and h["rows"][0]["cfdi"] == "NO TIMBRADO"
    text = _text(mexico_payslip_pdf.render_history(h))
    assert "Historial de pagos" in text and _money(item.net_pay) in text and "NO ES UN CFDI" in text
    assert _svc().pay_history(db, w.org.id, item.employee_id, date(2025, 1, 1), date(2025, 12, 31))["count"] == 0
    with pytest.raises(BadRequestException):
        _svc().pay_history(db, w.org.id + 999, item.employee_id, date(2026, 1, 1), date(2026, 12, 31))
    with pytest.raises(BadRequestException):
        _svc().pay_history(db, w.org.id, item.employee_id, date(2026, 12, 31), date(2026, 1, 1))


def test_mobile_summary_has_spoken_labels(db, monkeypatch, tmp_path):                                # MX24-PAY-003
    w, item = _draft(db, monkeypatch, tmp_path, "MXRB18")
    s = _svc().mobile_summary(_svc().recibo_view(db, item, w.run))
    assert s["net"] == _money(item.net_pay) and s["fiscalStatus"] == "NO TIMBRADO" and s["paymentStatus"] == "pendiente"
    assert _money(item.net_pay) in s["ariaLabel"] and "pesos mexicanos" in s["ariaLabel"]


def test_lines_without_an_approved_code_print_clave_pendiente(db):
    lines = _svc()._perceptions(db, {"days_paid": "15", "concepts": [
        {"code": "SYN_BONUS", "kind": "OTHER", "gross": "100.00", "isr_taxable": "100.00", "isr_exempt": "0",
         "cfdi_concept_code": None, "classification_id": None}]}, None)
    assert lines[0]["satCode"] is None and lines[0]["codePending"] is True


def test_pilot_watermark_stays(db, monkeypatch):
    from app.modules.payroll import service
    from tests import test_mexico_pilot as tp

    w = tp._pilot_world(db, monkeypatch, "MXRB19")
    tp.ah.commit(db, w, w.run)
    (item,) = tp.ah.rh.mx_items(db, w.run)
    drawn = []
    real = service._draw_evaluation_watermark
    monkeypatch.setattr(service, "_draw_evaluation_watermark",
                        lambda c, wd, h, f="Helvetica-Bold", text="": drawn.append(text) or real(c, wd, h, f, text=text))
    _text(service.generate_payslip_pdf_bytes(db, item.id, w.org.id))
    from app.modules.payroll.mexico_pilot_service import PILOT_WATERMARK

    assert PILOT_WATERMARK in drawn


def test_a_blocked_mexican_payslip_keeps_the_blocked_document(db, monkeypatch, tmp_path):
    w, item = _draft(db, monkeypatch, tmp_path, "MXRB20")
    item.mx_calculation_snapshot = {"blocked": True, "code": "SYN", "reason": "SYNTHETIC"}
    db.commit()
    text = _text(_pdf(db, w, item))
    assert "Recibo de nómina / Payslip" not in text and "HRA" not in text


# ── routes ───────────────────────────────────────────────────────────────────

def test_recibo_routes_are_org_scoped_and_masked(db, monkeypatch, tmp_path):
    from tests._mx_employer_helpers import http, principal
    from tests.test_mexico_cfdi_builder import GOOD_IDS

    w, item = _draft(db, monkeypatch, tmp_path, "MXRB21")
    base = "/api/payroll/mexico"
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        r = c.get(f"{base}/payslips/{item.id}/recibo")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["view"]["totals"]["net"] == _money(item.net_pay) and body["summary"]["documentCode"] == "MX24-PAY-003"
        assert all(v not in r.text for v in GOOD_IDS.values())
        dup = c.get(f"{base}/payslips/{item.id}/recibo/duplicate")
        assert dup.status_code == 200 and dup.headers["content-type"] == "application/pdf"
        assert dup.headers["cache-control"] == "no-store" and "DUPLICADO" in _text(dup.content)
        h = c.get(f"{base}/employees/{item.employee_id}/pay-history", params={"start": "2026-01-01", "end": "2026-12-31"})
        assert h.status_code == 200 and h.json()["count"] == 1
        hp = c.get(f"{base}/employees/{item.employee_id}/pay-history",
                   params={"start": "2026-01-01", "end": "2026-12-31", "format": "pdf"})
        assert hp.status_code == 200 and "Historial de pagos" in _text(hp.content)
        assert c.get(f"{base}/payslips/{item.id + 999}/recibo").status_code == 404


def test_an_ordinary_recibo_is_one_page_in_every_state(db, monkeypatch, tmp_path):
    from pypdf import PdfReader

    w, item, doc = _stamped(db, monkeypatch, tmp_path, "MXRB22")
    assert len(PdfReader(io.BytesIO(_pdf(db, w, item))).pages) == 1
    doc.status, doc.replaced_by_uuid = "CANCELLED", "SYN00000-0000-4000-8000-00000000RB22"
    db.commit()
    assert len(PdfReader(io.BytesIO(_pdf(db, w, item))).pages) == 1
