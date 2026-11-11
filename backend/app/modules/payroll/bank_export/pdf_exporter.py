from typing import List
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.modules.payroll.bank_export.base import IBankExporter, BankExportRow


def _routing_value(r: BankExportRow) -> str:
    """Jurisdiction routing value; falls back to the ifsc slot for rows
    built without the routing fields (India / legacy callers)."""
    return r.routing_value if r.routing_value is not None else (r.ifsc or "")


class PDFExporter(IBankExporter):
    content_type = "application/pdf"
    file_extension = "pdf"

    def generate(self, rows: List[BankExportRow], *, evaluation: bool = False) -> bytes:
        import io
        from reportlab.lib import colors
        from reportlab.pdfbase.pdfmetrics import stringWidth

        from app.core.exceptions import BadRequestException
        from app.modules.payroll.pdf_fonts import needs_unicode, unicode_font

        # PL-023: Polish (and any non-cp1252) names need a Unicode TrueType
        # font; without one the PDF is refused rather than printed wrongly.
        fonts = unicode_font()
        if fonts is None:
            texts = [rows[0].company_name if rows else ""]
            for r in rows:
                texts += [r.employee_name, r.employee_id, r.bank_name, r.account_number, _routing_value(r)]
            if needs_unicode(texts):
                raise BadRequestException("BANK_PDF_UNICODE_FONT_MISSING: the bank file contains characters the "
                                          "built-in PDF font cannot print and no Unicode font is installed; use "
                                          "the CSV / XML export or install a Unicode font (e.g. DejaVu Sans).")
            fonts = ("Helvetica", "Helvetica-Bold")
        regular, bold = fonts

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4

        def _watermark():
            if not evaluation:
                return
            text = "PREVIEW — EVALUATION ONLY"
            size = 30
            c.saveState()
            c.setFillColor(colors.HexColor("#1E3A8A"))
            c.setStrokeColor(colors.HexColor("#1E3A8A"))
            c.setFont(bold, size)
            try:
                c.setFillAlpha(0.25)
                c.setStrokeAlpha(0.25)
            except Exception:
                pass
            c.translate(width / 2, height / 2)
            c.rotate(45)
            tw = stringWidth(text, bold, size)
            c.drawCentredString(0, 0, text)
            c.restoreState()

        c.setFont(bold, 14)
        c.drawString(20 * mm, height - 20 * mm, "Bank Transfer File")

        c.setFont(regular, 8)
        y = height - 30 * mm
        c.drawString(20 * mm, y, f"Company: {rows[0].company_name if rows else 'N/A'}")
        c.drawString(120 * mm, y, f"Payment Date: {rows[0].payment_date if rows else 'N/A'}")
        y -= 6 * mm

        routing_label = rows[0].routing_label if rows else "IFSC"
        headers = ["Name", "ID", "Bank", "Account", routing_label, "Amount", "Currency"]
        col_x = [20 * mm, 45 * mm, 65 * mm, 90 * mm, 115 * mm, 140 * mm, 165 * mm]

        c.setFont(bold, 7)
        for i, h in enumerate(headers):
            c.drawString(col_x[i], y, h)
        y -= 4 * mm

        c.setFont(regular, 7)
        total = 0.0
        for r in rows:
            if y < 20 * mm:
                _watermark()
                c.showPage()
                y = height - 20 * mm
                c.setFont(regular, 7)
            vals = [r.employee_name, r.employee_id, r.bank_name, r.account_number, _routing_value(r), f"{r.amount:.2f}", r.currency]
            for i, v in enumerate(vals):
                c.drawString(col_x[i], y, str(v)[:25])
            y -= 4 * mm
            total += r.amount

        y -= 4 * mm
        c.setFont(bold, 8)
        c.drawString(20 * mm, y, f"Total Employees: {len(rows)}")
        c.drawString(100 * mm, y, f"Total Amount: {rows[0].currency if rows else ''} {total:.2f}")

        _watermark()
        c.save()
        return buf.getvalue()
