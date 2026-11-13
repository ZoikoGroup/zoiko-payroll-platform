"""
payroll/mexico_payslip_pdf.py
-----------------------------
Recibo de nómina v2.0 — the Mexican payslip PDF (A4 portrait, one page for an
ordinary payslip), drawn ONLY from mexico_payslip_service.recibo_view (every
figure, state and masked identifier is decided there). Also the pay-history
extract (MX24-PAY-011). Standard reportlab fonts (WinAnsi), which carry
á é í ó ú ñ Ñ ü – · · — the accents test reads them back out of the PDF.
"""
from __future__ import annotations

import io
from typing import Callable, Optional

NAVY = "#14243F"
TEAL = "#16A091"
TEAL_LIGHT = "#E3F4F1"
ROW_ALT = "#F3F5F8"
GREY = "#5B6676"
RULE = "#D5DBE3"
WARN = "#9A3412"

SERIF, SERIF_BOLD = "Times-Roman", "Times-Bold"
SANS, SANS_BOLD = "Helvetica", "Helvetica-Bold"


class _Doc:
    """A tiny flowing layout over a reportlab canvas: y moves down, a new page
    starts (with the page decorations) when the next block does not fit."""

    def __init__(self, view: dict, watermark: Optional[Callable] = None):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        self.mm = mm
        self.buf = io.BytesIO()
        self.w, self.h = A4
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.c.setTitle(view.get("title", "Recibo de nómina"))
        self.c.setAuthor("Zoiko Payroll")
        self.left, self.right = 14 * mm, self.w - 14 * mm
        self.top, self.bottom = self.h - 11 * mm, 18 * mm
        self.y = self.top
        self.page = 1
        self.view = view
        self.watermark = watermark

    # ── primitives ──
    def color(self, hex_, fill=True):
        from reportlab.lib import colors

        (self.c.setFillColor if fill else self.c.setStrokeColor)(colors.HexColor(hex_))

    def text(self, x, y, s, font=SANS, size=8.5, color=NAVY, align="left", char_space=0):
        self.color(color)
        if char_space:
            t = self.c.beginText()
            t.setFont(font, size)
            t.setCharSpace(char_space)
            width = self.c.stringWidth(s, font, size) + char_space * max(len(s) - 1, 0)
            t.setTextOrigin(x - width if align == "right" else x, y)
            t.textOut(s)
            t.setCharSpace(0)          # Tc persists in the page's text state — reset it for later text
            self.c.drawText(t)
            return
        self.c.setFont(font, size)
        {"left": self.c.drawString, "right": self.c.drawRightString,
         "center": self.c.drawCentredString}[align](x, y, s)

    def wrap(self, s, font, size, width):
        from reportlab.lib.utils import simpleSplit

        return simpleSplit(str(s if s is not None else "—"), font, size, width) or [""]

    def ensure(self, needed):
        if self.y - needed < self.bottom:
            self.finish_page()
            self.c.showPage()
            self.page += 1
            self.y = self.top

    def finish_page(self):
        self.footer()
        if self.watermark is not None:
            self.watermark(self.c, self.w, self.h)

    # ── blocks ──
    def header(self):
        mm, v = self.mm, self.view
        self.text(self.right, self.y, "ZOIKO PAYROLL / GLOBAL DOCUMENT ENGINE / MX–24", SANS_BOLD, 6.5, TEAL,
                  "right", char_space=0.6)
        self.y -= 9 * mm
        self.text(self.left, self.y, "zoiko", SERIF_BOLD, 26, NAVY)
        zw = self.c.stringWidth("zoiko", SERIF_BOLD, 26)
        self.text(self.left + zw + 2 * mm, self.y + 1, "PAYROLL", SANS_BOLD, 10, TEAL, char_space=1.2)
        if v.get("duplicate"):
            self.text(self.right, self.y + 2, "DUPLICADO", SANS_BOLD, 14, WARN, "right", char_space=1.5)
        self.y -= 5.5 * mm
        self.text(self.left, self.y, "COUNTRY PACK 24 / MÉXICO / MXN", SANS_BOLD, 7.5, TEAL, char_space=0.8)
        self.y -= 9 * mm
        self.text(self.left, self.y, v["title"], SERIF_BOLD, 20, NAVY)
        self.y -= 5.5 * mm
        self.text(self.left, self.y, v["subtitle"], SANS, 8.5, GREY)
        self.y -= 4 * mm
        # status ribbon: CFDI status and payment status are separate phrases
        lines = self.wrap(v["ribbon"], SANS_BOLD, 7.8, self.right - self.left - 8 * mm)
        band = 4.5 * mm + 3.6 * mm * len(lines)
        self.color(TEAL_LIGHT)
        self.c.rect(self.left, self.y - band, self.right - self.left, band, fill=1, stroke=0)
        self.color(TEAL)
        self.c.rect(self.left, self.y - band, 1.2 * mm, band, fill=1, stroke=0)
        ty = self.y - 4.2 * mm
        for ln in lines:
            self.text(self.left + 4 * mm, ty, ln, SANS_BOLD, 7.8, NAVY)
            ty -= 3.6 * mm
        self.y -= band + 5 * mm

    def section(self, title):
        self.ensure(18 * self.mm)
        self.y -= 3.5 * self.mm
        self.text(self.left, self.y, title, SERIF_BOLD, 11.5, NAVY)
        self.y -= 1.8 * self.mm
        self.color(TEAL, fill=False)
        self.c.setLineWidth(0.8)
        self.c.line(self.left, self.y, self.left + 18 * self.mm, self.y)
        self.y -= 3.2 * self.mm

    def table(self, widths, header, rows, aligns, *, bold_last=False, size=7.8):
        """widths are fractions of the content width; rows are lists of str."""
        mm = self.mm
        total_w = self.right - self.left
        cols = [f * total_w for f in widths]
        pad = 1.8 * mm
        line_h = 3.3 * mm
        # header
        self.ensure(7 * mm + line_h * 2)
        hh = 5.6 * mm
        self.color(NAVY)
        self.c.rect(self.left, self.y - hh, total_w, hh, fill=1, stroke=0)
        x = self.left
        for i, h in enumerate(header):
            ax = x + pad if aligns[i] == "left" else x + cols[i] - pad
            self.text(ax, self.y - 4 * mm, h, SANS_BOLD, 6.8, "#FFFFFF", aligns[i], char_space=0.3)
            x += cols[i]
        self.y -= hh
        for r_i, row in enumerate(rows):
            last = bold_last and r_i == len(rows) - 1
            font = SANS_BOLD if last else SANS
            wrapped = [self.wrap(cell, font, size, cols[i] - 2 * pad) for i, cell in enumerate(row)]
            rh = max(len(w) for w in wrapped) * line_h + 1.9 * mm
            self.ensure(rh)
            if last:
                self.color(TEAL_LIGHT)
                self.c.rect(self.left, self.y - rh, total_w, rh, fill=1, stroke=0)
            elif r_i % 2 == 1:
                self.color(ROW_ALT)
                self.c.rect(self.left, self.y - rh, total_w, rh, fill=1, stroke=0)
            x = self.left
            for i, lines in enumerate(wrapped):
                ty = self.y - 3.35 * mm
                for ln in lines:
                    ax = x + pad if aligns[i] == "left" else x + cols[i] - pad
                    self.text(ax, ty, ln, font, size, NAVY, aligns[i])
                    ty -= line_h
                x += cols[i]
            self.y -= rh
        self.color(RULE, fill=False)
        self.c.setLineWidth(0.5)
        self.c.line(self.left, self.y, self.right, self.y)
        self.y -= 3.2 * mm

    def totals_boxes(self, items):
        mm = self.mm
        self.ensure(18 * mm)
        gap = 3 * mm
        bw = (self.right - self.left - gap * (len(items) - 1)) / len(items)
        bh = 14 * mm
        for i, (label, value, strong) in enumerate(items):
            x = self.left + i * (bw + gap)
            self.color(NAVY if strong else TEAL_LIGHT)
            self.c.rect(x, self.y - bh, bw, bh, fill=1, stroke=0)
            fg = "#FFFFFF" if strong else NAVY
            self.text(x + 3 * mm, self.y - 4.6 * mm, label, SANS_BOLD, 6.8, fg if strong else TEAL, char_space=0.4)
            self.text(x + bw - 3 * mm, self.y - 10.8 * mm, f"{value} MXN", SERIF_BOLD, 13, fg, "right")
        self.y -= bh + 4 * mm

    def note(self, title, body, extra_lines):
        mm = self.mm
        width = self.right - self.left - 8 * mm
        body_lines = self.wrap(body, SANS, 7.6, width)
        h = 5 * mm + 3.4 * mm * (len(body_lines) + len(extra_lines)) + 2 * mm
        self.ensure(h + 2 * mm)
        self.color(TEAL_LIGHT)
        self.c.rect(self.left, self.y - h, self.right - self.left, h, fill=1, stroke=0)
        ty = self.y - 4.3 * mm
        self.text(self.left + 4 * mm, ty, title, SANS_BOLD, 7.8, NAVY)
        ty -= 3.6 * mm
        for ln in body_lines:
            self.text(self.left + 4 * mm, ty, ln, SANS, 7.6, NAVY)
            ty -= 3.4 * mm
        for label, value in extra_lines:
            self.text(self.left + 4 * mm, ty, label, SANS, 7.6, GREY)
            self.text(self.right - 4 * mm, ty, value, SANS_BOLD, 7.6, NAVY, "right")
            ty -= 3.4 * mm
        self.y -= h + 5 * mm

    def footer(self):
        mm, f = self.mm, self.view["footer"]
        self.color(RULE, fill=False)
        self.c.setLineWidth(0.5)
        self.c.line(self.left, 14 * mm, self.right, 14 * mm)
        self.text(self.left, 10 * mm, f"{f['confidential']} · {f['documentState']} · {f['issueDate']}",
                  SANS_BOLD, 6.8, GREY, char_space=0.3)
        self.text(self.left, 6.6 * mm,
                  f"{self.view['documentCode']} · {self.view['rendererVersion']} · snapshot {f['snapshotHash']}",
                  SANS, 6.3, GREY)
        self.text(self.right, 10 * mm, f"Página {self.page}", SANS, 6.8, GREY, "right")

    def save(self) -> bytes:
        self.finish_page()
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def render_recibo(view: dict, watermark: Optional[Callable] = None) -> bytes:
    d = _Doc(view, watermark)
    d.header()
    p = view["parties"]
    er, ee = p["employer"], p["employee"]

    def dash(v):
        return v if v not in (None, "") else "—"

    d.section("Datos del patrón y del trabajador / Parties")
    d.table([0.5, 0.5], ["EMISOR / EMPLOYER", "RECEPTOR / EMPLOYEE"], [
        [dash(er["name"]), dash(ee["name"])],
        [f"RFC: {dash(er['rfc'])} · Registro patronal: {dash(er['registroPatronal'])}",
         f"RFC: {dash(ee['rfc'])} · CURP: {dash(ee['curp'])}"],
        [f"{dash(er['state'])} · C.P. {dash(er['postalCode'])}",
         f"Empleado: {dash(ee['employeeCode'])} · NSS: {dash(ee['nss'])}"],
        [f"Régimen fiscal: {dash(er['fiscalRegime'])}", f"Régimen fiscal receptor: {dash(ee['fiscalRegime'])}"],
    ], ["left", "left"])
    pr = view["payroll"]
    d.table([0.34, 0.36, 0.30], ["NÓMINA / PERIODO", "FECHA / PAGO", "FISCAL"], [
        [f"{pr['type']} · {pr['periodicity']}", pr["period"], f"CFDI: {view['fiscal']['label']}"],
    ], ["left", "left", "left"])

    d.section("Percepciones / Earnings")
    rows = [[f"{l['satCode'] or 'clave pendiente'} · {l['concept']}", l["taxed"], l["exempt"], l["total"]]
            for l in view["perceptions"]]
    t = view["perceptionTotals"]
    rows.append(["TOTAL PERCEPCIONES", t["taxed"], t["exempt"], t["total"]])
    d.table([0.46, 0.18, 0.18, 0.18], ["CLAVE / CONCEPTO", "GRAVADO MXN", "EXENTO MXN", "TOTAL MXN"], rows,
            ["left", "right", "right", "right"], bold_last=True)

    if view["otherPayments"]:
        d.section("Otros pagos / Other payments")
        d.table([0.46, 0.18, 0.36], ["CLAVE / CONCEPTO", "IMPORTE (MXN)", "NOTA"],
                [[f"{o['satCode'] or 'clave pendiente'} · {o['concept']}", o["amount"], o.get("note") or ""]
                 for o in view["otherPayments"]], ["left", "right", "left"])

    d.section("Deducciones / Employee deductions")
    rows = [[l["concept"], l["amount"], l["basis"]] for l in view["deductions"]]
    rows.append(["TOTAL DEDUCCIONES", view["totals"]["deductions"], ""])
    d.table([0.30, 0.18, 0.52], ["CONCEPTO", "IMPORTE (MXN)", "BASE / JUSTIFICANTE"], rows,
            ["left", "right", "left"], bold_last=True)

    d.section("Resumen / Totals")
    tt = view["totals"]
    d.totals_boxes([("TOTAL DEVENGADO", tt["gross"], False), ("DESCUENTOS DEL TRABAJADOR", tt["deductions"], False),
                    ("NETO A PAGAR", tt["net"], True)])
    e = view["employer"]
    title, _, body = e["note"].partition(". ")
    d.note(title + ".", body, [("Cuotas patronales IMSS (informativo)", f"{e['imss']} MXN"),
                               ("Aportación patronal INFONAVIT (informativo)", f"{e['infonavit']} MXN"),
                               ("Impuesto sobre nómina estatal (informativo)", f"{e['isn']} MXN"),
                               ("Total costo patronal (informativo)", f"{e['total']} MXN")])

    d.section("Timbre fiscal / SAT status")
    s = view["fiscal"]["sat"]
    d.table([0.25, 0.75], ["CONCEPTO", "VALOR"], [
        ["Folio fiscal (UUID)", s["uuid"]], ["Timbre SAT", s["stamp"]], ["Sello SAT", s["seal"]],
        ["XML/QR", s["xmlQr"]], ["Estado de pago", f"Pago: {view['payment']['label']}"],
    ], ["left", "left"])
    return d.save()


def render_history(history: dict) -> bytes:
    view = {"title": "Historial de pagos / Pay history", "documentCode": history["documentCode"],
            "rendererVersion": history["rendererVersion"], "duplicate": False,
            "subtitle": f"{history['employee']['name']} · {history['employee']['employeeCode']} · "
                        f"{history['range']['label']}",
            "ribbon": "EXTRACTO INFORMATIVO · NO ES UN CFDI · LOS IMPORTES SON LOS DE CADA RECIBO REGISTRADO",
            "footer": {"confidential": "CONFIDENTIAL", "documentState": "EXTRACTO",
                       "issueDate": history.get("issueDate", ""), "snapshotHash": "—"}}
    d = _Doc(view)
    d.header()
    d.section("Recibos del periodo / Payslips in range")
    rows = [[r["period"], r["type"], r["gross"], r["deductions"], r["net"], r["cfdi"], r["payment"]]
            for r in history["rows"]] or [["Sin recibos en el rango", "", "", "", "", "", ""]]
    d.table([0.24, 0.12, 0.13, 0.13, 0.13, 0.12, 0.13],
            ["PERIODO", "TIPO", "DEVENGADO", "DESCUENTOS", "NETO", "CFDI", "PAGO"], rows,
            ["left", "left", "right", "right", "right", "left", "left"], size=7.2)
    return d.save()
