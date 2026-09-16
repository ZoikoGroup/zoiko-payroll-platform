import io
from typing import List

from openpyxl import Workbook

from app.modules.payroll.bank_export.base import IBankExporter, BankExportRow

_HEADERS = [
    "Employee Name", "Employee ID", "Bank Name", "Account Number", "IFSC", "Branch",
    "Amount", "Reference Number", "Narration", "Payment Date", "Currency", "Company Name",
]


def _routing_value(r: BankExportRow) -> str:
    """Jurisdiction routing value; falls back to the ifsc slot for rows
    built without the routing fields (India / legacy callers)."""
    return r.routing_value if r.routing_value is not None else (r.ifsc or "")


class ExcelExporter(IBankExporter):
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    file_extension = "xlsx"

    def generate(self, rows: List[BankExportRow], *, evaluation: bool = False) -> bytes:
        routing_label = rows[0].routing_label if rows else "IFSC"
        headers = list(_HEADERS)
        headers[4] = routing_label
        wb = Workbook()
        ws = wb.active
        ws.title = "Bank Transfer"
        ws.append(headers)
        for r in rows:
            ws.append([
                r.employee_name, r.employee_id, r.bank_name, r.account_number, _routing_value(r), r.branch or "",
                float(r.amount), r.reference_number, r.narration, r.payment_date, r.currency, r.company_name,
            ])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
