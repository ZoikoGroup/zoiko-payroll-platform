from typing import List
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.modules.payroll.bank_export.base import IBankExporter, BankExportRow


class PDFExporter(IBankExporter):
    content_type = "application/pdf"
    file_extension = "pdf"

    def generate(self, rows: List[BankExportRow]) -> bytes:
        import io
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4

        c.setFont("Helvetica-Bold", 14)
        c.drawString(20 * mm, height - 20 * mm, "Bank Transfer File")

        c.setFont("Helvetica", 8)
        y = height - 30 * mm
        c.drawString(20 * mm, y, f"Company: {rows[0].company_name if rows else 'N/A'}")
        c.drawString(120 * mm, y, f"Payment Date: {rows[0].payment_date if rows else 'N/A'}")
        y -= 6 * mm

        headers = ["Name", "ID", "Bank", "Account", "IFSC", "Amount", "Currency"]
        col_x = [20 * mm, 45 * mm, 65 * mm, 90 * mm, 115 * mm, 140 * mm, 165 * mm]

        c.setFont("Helvetica-Bold", 7)
        for i, h in enumerate(headers):
            c.drawString(col_x[i], y, h)
        y -= 4 * mm

        c.setFont("Helvetica", 7)
        total = 0.0
        for r in rows:
            if y < 20 * mm:
                c.showPage()
                y = height - 20 * mm
                c.setFont("Helvetica", 7)
            vals = [r.employee_name, r.employee_id, r.bank_name, r.account_number, r.ifsc, f"{r.amount:.2f}", r.currency]
            for i, v in enumerate(vals):
                c.drawString(col_x[i], y, str(v)[:25])
            y -= 4 * mm
            total += r.amount

        y -= 4 * mm
        c.setFont("Helvetica-Bold", 8)
        c.drawString(20 * mm, y, f"Total Employees: {len(rows)}")
        c.drawString(100 * mm, y, f"Total Amount: {rows[0].currency if rows else ''} {total:.2f}")

        c.save()
        return buf.getvalue()
