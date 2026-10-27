"""The printed CFDI payroll receipt (completion W4-3b = Phase 12c, plan D4):
rendered on demand ONLY from the stored stamped XML (the PAC's answer, kept by
mexico_cfdi_service), per CFF Art. 29-A, RMF 2026 rules 2.7.1.7 / 2.7.5.2 and
Anexo 20 I.D (the QR). Never stored as a report. SYNTHETIC worlds, the mock
PAC, and the real builder (the 11b ready world)."""

from decimal import Decimal as D

import pytest


def _R():
    from app.modules.payroll import mexico_cfdi_receipt

    return mexico_cfdi_receipt


def _stamped(db, monkeypatch, tmp_path, code):
    from app.modules.payroll import mexico_cfdi_service as S
    from tests import _mx_cfdi_helpers as ch
    from tests.test_mexico_cfdi_builder import _ready_world

    w = _ready_world(db, monkeypatch, tmp_path, code)
    ch.mock(monkeypatch)
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    (doc,) = ch.docs(db, w.run)
    db.refresh(doc)
    assert doc.status == "STAMPED"
    return w, doc


def test_the_stamped_xml_is_kept_and_the_receipt_reads_only_from_it(db, monkeypatch, tmp_path):
    from app.core import object_storage
    from app.modules.payroll import mexico_cfdi_service as S
    from app.modules.payroll.models import GeneratedReport
    from tests import _mx_cfdi_helpers as ch

    w, doc = _stamped(db, monkeypatch, tmp_path, "MXRCT1")
    assert ch.events(db, doc)[-1] == "STAMPED_XML_STORED"
    ref = S.stamped_xml_ref(db, doc)
    assert ref and ref != doc.xml_storage_ref and doc.uuid.encode() in object_storage.read_bytes(ref)
    before = db.query(GeneratedReport).count()
    r = _R().mx_cfdi_receipt_data(db, w.org.id, doc.id)
    assert r["legend"] == "Este documento es una representación impresa de un CFDI"          # RMF 2.7.1.7 III
    assert r["certification"]["UUID"] == doc.uuid and r["certification"]["NoCertificadoSAT"]    # 2.7.1.7 I, II
    assert r["certification"]["FechaTimbrado"] and r["comprobante"]["Fecha"]                    # 2.7.1.7 IV
    assert r["issuer"]["rfc"] and r["receiver"]["rfc"] and r["receiver"]["use"]                 # 2.7.5.2; CFF 29-A
    assert r["issuer"]["regime"] and r["issuer"]["placeOfIssue"] and r["receiver"]["postalCode"]
    item = __import__("tests._mx_run_helpers", fromlist=["x"]).mx_items(db, w.run)[0]
    assert D(r["nomina"]["TotalPercepciones"]) == D(item.mx_calculation_snapshot["result"]["gross"])
    assert r["nomina"]["percepciones"] and r["nomina"]["deducciones"]
    assert any("2.7.1.7 V" in m for m in r["missing"]) and r["officialStatus"] == "NOT AN OFFICIAL FILE"
    assert db.query(GeneratedReport).count() == before                                          # never stored


def test_the_qr_follows_anexo_20_i_d(db, monkeypatch, tmp_path):
    w, doc = _stamped(db, monkeypatch, tmp_path, "MXRCT2")
    r = _R().mx_cfdi_receipt_data(db, w.org.id, doc.id)
    url, _, query = r["qr"].partition("?")
    assert url == "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"
    assert [p.split("=")[0] for p in query.split("&")] == ["id", "re", "rr", "tt", "fe"]       # the sequence
    params = dict(p.split("=", 1) for p in query.split("&"))
    assert params["id"] == doc.uuid and params["re"] == r["issuer"]["rfc"] and params["rr"] == r["receiver"]["rfc"]
    assert D(params["tt"]) == D(r["comprobante"]["Total"]) and params["fe"] == (r["issuerSeal"] or "")[-8:]


@pytest.mark.parametrize("total,expected", [("14300.000000", "14300"), ("1234.50", "1234.5"), ("0.10", "0.1"),
                                            ("00012.34", "12.34")])
def test_the_qr_total_omits_non_significant_zeros(total, expected):
    assert _R().qr_total(total) == expected                     # Anexo 20 I.D text (its example pads: D-20)


def test_the_pdf_is_built_in_memory_with_the_legend(db, monkeypatch, tmp_path):
    w, doc = _stamped(db, monkeypatch, tmp_path, "MXRCT3")
    pdf = _R().mx_cfdi_receipt_pdf(db, w.org.id, doc.id)
    import io

    from pypdf import PdfReader

    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "NOT AN OFFICIAL FILE" in text and "representación impresa de un CFDI" in text
    assert doc.uuid in text
    r = _R().mx_cfdi_receipt_data(db, w.org.id, doc.id)
    flat = "".join(text.split())                                           # wrapped, never cut (CFF Art. 29-A)
    assert len(r["certification"]["SelloSAT"]) > 300 and r["certification"]["SelloSAT"] in flat
    assert (r["issuerSeal"] or "") in flat


def test_only_a_stamped_document_with_its_stored_xml_has_a_receipt(db, monkeypatch, tmp_path):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import mexico_cfdi_service as S
    from tests import _mx_cfdi_helpers as ch

    w = ch.committed_world(db, monkeypatch, tmp_path, code="MXRCT4")       # SYNTHETIC non-XML payload
    ch.mock(monkeypatch, stamp=["timeout"])
    S.generate(db, w.run, w.users[0].id)
    (doc,) = ch.docs(db, w.run)
    with pytest.raises(BadRequestException, match="only a stamped CFDI"):
        _R().mx_cfdi_receipt_data(db, w.org.id, doc.id)
    ch.mock(monkeypatch)
    ch.process(db, w)                                                      # no outbox item left: stamp now
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    db.refresh(doc)
    if doc.status == "STAMPED":                         # stamped, but its SYNTHETIC payload is no Comprobante
        with pytest.raises(BadRequestException, match="no stored stamped XML|not a CFDI"):
            _R().mx_cfdi_receipt_data(db, w.org.id, doc.id)
    with pytest.raises(NotFoundException):
        _R().mx_cfdi_receipt_data(db, w.org.id, 999999)
