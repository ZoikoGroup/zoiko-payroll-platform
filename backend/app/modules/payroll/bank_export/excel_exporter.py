import io
from typing import List

from openpyxl import Workbook

from app.modules.payroll.bank_export.base import IBankExporter, BankExportRow

_HEADERS = [
    "Employee Name", "Employee ID", "Bank Name", "Account Number", "IFSC", "Branch",
    "Amount", "Reference Number", "Narration", "Payment Date", "Currency", "Company Name",
]


class ExcelExporter(IBankExporter):
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    file_extension = "xlsx"

    def generate(self, rows: List[BankExportRow]) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Bank Transfer"
        ws.append(_HEADERS)
        for r in rows:
            ws.append([
                r.employee_name, r.employee_id, r.bank_name, r.account_number, r.ifsc, r.branch or "",
                float(r.amount), r.reference_number, r.narration, r.payment_date, r.currency, r.company_name,
            ])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
