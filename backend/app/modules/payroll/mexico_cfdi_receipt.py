"""
mexico_cfdi_receipt.py
----------------------
The printed representation of a stamped Mexican payroll CFDI (completion
programme W4-3b = Phase 12c, plan D4: "MX-CFDI-NOMINA-RECEIPT").

Rendered ON DEMAND, only from the STORED STAMPED XML (the PAC's answer, kept
by mexico_cfdi_service._store_stamped_xml), never from engine figures, and
never stored as a report body: it carries the RFC / CURP / NSS a receipt must
show (MX-061's one exception), so each render is a fresh PDF for the caller.

What it prints, and where each rule is written (saved sources only):
  * CFF Art. 29-A I–IV (S35, PDF p. 57): issuer RFC, name, fiscal regime and
    place of issue; folio and the SAT and issuer seals; date; receiver RFC,
    name, postal code and use.
  * RMF 2026 rule 2.7.1.7 (S1, PDF pp. 99–100): I the QR built per Anexo 20
    I.D (or the folio fiscal); II the issuer's and the SAT's CSD serials;
    III the legend "Este documento es una representación impresa de un CFDI";
    IV the issue and certification date-times; V the original chain of the
    SAT's certification complement.
  * RMF 2026 rule 2.7.5.2 (S1, PDF p. 162): at least the folio fiscal and the
    employer's and employee's RFC.
  * Anexo 20 I.D (S30, PDF pp. 66–67): QR = the verification URL with id, re,
    rr, tt, fe; printed in a square no smaller than 2.75 cm.

What the saved sources do NOT give (listed on the receipt, which is then
"NOT AN OFFICIAL FILE"): the formation rule of the SAT certification chain
(rule 2.7.1.7 V) — the guides show only examples; and the exact zero-padding
of the QR total (Anexo 20 I.D's text says "omitir los ceros no significativos"
while its own example pads — DECISIONS_PENDING D-20; the text is followed).
"""

from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

LEGEND = "Este documento es una representación impresa de un CFDI"
VERIFY_URL = "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"     # Anexo 20 I.D (S30 p. 67)
QR_MIN_CM = 2.75
NOT_OFFICIAL = "NOT AN OFFICIAL FILE"
MISSING_CHAIN = ("RMF 2.7.1.7 V — the original chain of the SAT certification complement: its formation rule is not "
                 "in the saved sources (only examples), so it is not printed")
SOURCES = ("S35 CFF Art. 29-A (PDF p. 57)", "S1 RMF 2026 rule 2.7.1.7 (PDF pp. 99-100)",
           "S1 RMF 2026 rule 2.7.5.2 (PDF p. 162)", "S30 Anexo 20 I.D (PDF pp. 66-67)")


def _local(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


def _find(root, name):
    return next((el for el in root.iter() if _local(el) == name), None)


def _all(root, name) -> list:
    return [el for el in root.iter() if _local(el) == name]


def qr_total(total: str) -> str:
    """Anexo 20 I.D: the total with "los ceros no significativos" omitted (D-20)."""
    try:
        d = Decimal(str(total))
    except (InvalidOperation, ValueError):
        raise BadRequestException("the stamped CFDI's Total is not a number")
    return format(d.normalize(), "f")


def qr_payload(uuid: str, issuer_rfc: str, receiver_rfc: str, total: str, issuer_seal: str) -> str:
    """The QR content, in Anexo 20 I.D's order: URL, id, re, rr, tt, fe."""
    return (f"{VERIFY_URL}?id={uuid}&re={issuer_rfc}&rr={receiver_rfc}&tt={qr_total(total)}"
            f"&fe={(issuer_seal or '')[-8:]}")


def receipt_from_xml(xml: bytes) -> dict:
    """Every printed element, read from the stamped XML only."""
    from lxml import etree

    root = etree.fromstring(xml)
    if _local(root) != "Comprobante":
        raise BadRequestException("the stored document is not a CFDI")
    issuer, receiver, tfd = _find(root, "Emisor"), _find(root, "Receptor"), _find(root, "TimbreFiscalDigital")
    nomina = _find(root, "Nomina")
    if tfd is None or not tfd.get("UUID"):
        raise BadRequestException("the stored CFDI carries no TimbreFiscalDigital — it is not stamped")
    a = root.get

    def lines(parent_name, child_name, fields):
        parent = _find(nomina, parent_name) if nomina is not None else None
        return [{k: el.get(k) for k in fields} for el in (_all(parent, child_name) if parent is not None else [])]

    nom_receiver = _find(nomina, "Receptor") if nomina is not None else None
    nom_issuer = _find(nomina, "Emisor") if nomina is not None else None
    out = {
        "legend": LEGEND,
        "issuer": {"rfc": issuer.get("Rfc"), "name": issuer.get("Nombre"), "regime": issuer.get("RegimenFiscal"),
                   "placeOfIssue": a("LugarExpedicion"),
                   "registroPatronal": nom_issuer.get("RegistroPatronal") if nom_issuer is not None else None},
        "receiver": {"rfc": receiver.get("Rfc"), "name": receiver.get("Nombre"),
                     "postalCode": receiver.get("DomicilioFiscalReceptor"), "regime": receiver.get("RegimenFiscalReceptor"),
                     "use": receiver.get("UsoCFDI"),
                     "curp": nom_receiver.get("Curp") if nom_receiver is not None else None,
                     "nss": nom_receiver.get("NumSeguridadSocial") if nom_receiver is not None else None,
                     "employeeNumber": nom_receiver.get("NumEmpleado") if nom_receiver is not None else None},
        "comprobante": {k: a(k) for k in ("Version", "Serie", "Folio", "Fecha", "SubTotal", "Descuento", "Total", "Moneda",
                                          "TipoDeComprobante", "Exportacion", "MetodoPago", "NoCertificado")},
        "nomina": None if nomina is None else {
            **{k: nomina.get(k) for k in ("Version", "TipoNomina", "FechaPago", "FechaInicialPago", "FechaFinalPago",
                                          "NumDiasPagados", "TotalPercepciones", "TotalDeducciones", "TotalOtrosPagos")},
            "percepciones": lines("Percepciones", "Percepcion",
                                  ("TipoPercepcion", "Clave", "Concepto", "ImporteGravado", "ImporteExento")),
            "deducciones": lines("Deducciones", "Deduccion", ("TipoDeduccion", "Clave", "Concepto", "Importe")),
            "otrosPagos": lines("OtrosPagos", "OtroPago", ("TipoOtroPago", "Clave", "Concepto", "Importe")),
        },
        "certification": {k: tfd.get(k) for k in ("UUID", "FechaTimbrado", "RfcProvCertif", "NoCertificadoSAT",
                                                   "SelloCFD", "SelloSAT")},
        "issuerSeal": a("Sello"),
    }
    out["qr"] = qr_payload(tfd.get("UUID"), out["issuer"]["rfc"], out["receiver"]["rfc"], a("Total"), a("Sello"))
    out["missing"] = [MISSING_CHAIN]
    out["officialStatus"] = NOT_OFFICIAL if out["missing"] else None
    out["sources"] = list(SOURCES)
    return out


def mx_cfdi_receipt_data(db: Session, org_id: int, document_id: int) -> dict:
    """The receipt of one STAMPED document of the organisation (never stored)."""
    from app.core import object_storage
    from app.modules.payroll import mexico_cfdi_service, mexico_filing_service

    mexico_filing_service.guard(db, org_id)
    m = mexico_cfdi_service._models()
    doc = db.get(m.PayrollMxCfdiDocument, document_id)
    if doc is None or doc.organization_id != org_id:
        raise NotFoundException(f"CFDI document {document_id} not found")
    if doc.status not in ("STAMPED", "CANCEL_REQUESTED", "CANCELLED", "REPLACED"):
        raise BadRequestException(f"CFDI {document_id} is {doc.status} — only a stamped CFDI has a printed receipt")
    ref = mexico_cfdi_service.stamped_xml_ref(db, doc)
    if not ref:
        raise BadRequestException(f"CFDI {document_id} has no stored stamped XML — the receipt is rendered only from "
                                  f"it (never from engine figures)")
    data = receipt_from_xml(object_storage.read_bytes(ref))
    data["documentStatus"] = doc.status
    return data


def mx_cfdi_receipt_pdf(db: Session, org_id: int, document_id: int) -> bytes:
    """The receipt as a PDF, with the Anexo 20 QR (≥ 2.75 cm) — built in memory."""
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfgen import canvas

    d = mx_cfdi_receipt_data(db, org_id, document_id)
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    y = height - 2 * cm

    qr_size = 3.0 * cm                                           # ≥ 2.75 cm (Anexo 20 I.D)
    qr_bottom = height - 2 * cm - qr_size

    page = 1

    def watermark():
        if d["officialStatus"]:                                  # on every page
            pdf.saveState()
            pdf.setFont("Helvetica-Bold", 28)
            pdf.setFillGray(0.85)
            pdf.translate(width / 2, height / 2)
            pdf.rotate(35)
            pdf.drawCentredString(0, 0, d["officialStatus"])
            pdf.restoreState()

    def line(text, size=9, bold=False, gap=0.45):
        """Wrapped, never cut: the seals must print whole (CFF Art. 29-A)."""
        nonlocal y, page
        font = "Helvetica-Bold" if bold else "Helvetica"
        rows = [""]

        def fits(candidate):                                     # rows beside the QR are narrower (page 1)
            beside_qr = page == 1 and y - (len(rows) - 1) * size * 1.2 > qr_bottom
            room = width - 4 * cm - (qr_size + 0.5 * cm if beside_qr else 0)
            return pdfmetrics.stringWidth(candidate, font, size) <= room

        for word in str(text).split(" "):                        # by word; a seal longer than a row by character
            joined = f"{rows[-1]} {word}" if rows[-1] else word
            if fits(joined):
                rows[-1] = joined
                continue
            if rows[-1]:
                rows.append("")
            if fits(word):
                rows[-1] = word
            else:
                for ch in word:
                    if not fits(rows[-1] + ch):
                        rows.append("")
                    rows[-1] += ch
        for i, row in enumerate(rows):
            if y < 2 * cm:
                pdf.showPage()
                page += 1
                y = height - 2 * cm
                watermark()
            pdf.setFont(font, size)
            pdf.drawString(2 * cm, y, row)
            y -= (gap * cm) if i == len(rows) - 1 else size * 1.2

    watermark()
    widget = QrCodeWidget(d["qr"])
    bx0, by0, bx1, by1 = widget.getBounds()
    drawing = Drawing(qr_size, qr_size, transform=[qr_size / (bx1 - bx0), 0, 0, qr_size / (by1 - by0), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, pdf, width - 2 * cm - qr_size, qr_bottom)
    line("CFDI de nómina", 13, True, 0.7)
    line(d["legend"], 9, True)
    c, i, r, t = d["comprobante"], d["issuer"], d["receiver"], d["certification"]
    line(f"Folio fiscal (UUID): {t['UUID']}")
    line(f"Serie / Folio: {c.get('Serie') or ''} {c.get('Folio') or ''}   Fecha de emisión: {c.get('Fecha')}   "
         f"Lugar de expedición: {i.get('placeOfIssue')}")
    line(f"Emisor: {i['name']}   RFC: {i['rfc']}   Régimen fiscal: {i['regime']}   Registro patronal: "
         f"{i.get('registroPatronal') or ''}")
    line(f"Receptor: {r['name']}   RFC: {r['rfc']}   CURP: {r.get('curp') or ''}   NSS: {r.get('nss') or ''}")
    line(f"Código postal: {r['postalCode']}   Régimen: {r['regime']}   Uso CFDI: {r['use']}   No. empleado: "
         f"{r.get('employeeNumber') or ''}")
    n = d["nomina"] or {}
    if n:
        line(f"Nómina {n.get('Version')} tipo {n.get('TipoNomina')}: pago {n.get('FechaPago')}, periodo "
             f"{n.get('FechaInicialPago')} a {n.get('FechaFinalPago')}, días pagados {n.get('NumDiasPagados')}", gap=0.6)
        line("Percepciones", 10, True)
        for p in n["percepciones"]:
            line(f"  {p['TipoPercepcion']} {p['Clave']} {p['Concepto']}   gravado {p['ImporteGravado']}   exento "
                 f"{p['ImporteExento']}")
        line("Deducciones", 10, True)
        for p in n["deducciones"]:
            line(f"  {p['TipoDeduccion']} {p['Clave']} {p['Concepto']}   {p['Importe']}")
        if n["otrosPagos"]:
            line("Otros pagos", 10, True)
            for p in n["otrosPagos"]:
                line(f"  {p['TipoOtroPago']} {p['Clave']} {p['Concepto']}   {p['Importe']}")
        line(f"Total percepciones {n.get('TotalPercepciones')}   Total deducciones {n.get('TotalDeducciones')}   "
             f"Total otros pagos {n.get('TotalOtrosPagos') or '0'}", gap=0.6)
    line(f"Subtotal {c.get('SubTotal')}   Descuento {c.get('Descuento') or '0'}   Total {c.get('Total')} "
         f"{c.get('Moneda')}", 10, True, 0.7)
    line(f"No. de serie del CSD del emisor: {c.get('NoCertificado') or ''}   No. de serie del CSD del SAT: "
         f"{t.get('NoCertificadoSAT') or ''}")
    line(f"Fecha y hora de certificación: {t.get('FechaTimbrado') or ''}   RFC del proveedor de certificación: "
         f"{t.get('RfcProvCertif') or ''}")
    line(f"Sello digital del CFDI: {d['issuerSeal'] or ''}", 7)
    line(f"Sello del SAT: {t.get('SelloSAT') or ''}", 7, gap=0.6)
    for missing in d["missing"]:
        line(f"Falta / missing: {missing}", 7)
    pdf.setFont("Helvetica", 6)
    pdf.drawString(2 * cm, 1.2 * cm, "Sources: " + "; ".join(d["sources"]))
    pdf.showPage()
    pdf.save()
    return buf.getvalue()
