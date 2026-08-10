import csv
import io
from typing import List

from app.modules.payroll.bank_export.base import IBankExporter, BankExportRow

_HEADERS = [
    "Employee Name", "Employee ID", "Bank Name", "Account Number", "IFSC", "Branch",
    "Amount", "Reference Number", "Narration", "Payment Date", "Currency", "Company Name",
]


class CSVExporter(IBankExporter):
    content_type = "text/csv"
    file_extension = "csv"

    def generate(self, rows: List[BankExportRow]) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_HEADERS)
        for r in rows:
            writer.writerow([
                r.employee_name, r.employee_id, r.bank_name, r.account_number, r.ifsc, r.branch or "",
                f"{r.amount:.2f}", r.reference_number, r.narration, r.payment_date, r.currency, r.company_name,
            ])
        return buf.getvalue().encode("utf-8")
