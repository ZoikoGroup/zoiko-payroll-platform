import csv
import io
from typing import List

from app.modules.payroll.bank_export.base import IBankExporter, BankExportRow

_HEADERS = [
    "Employee Name", "Employee ID", "Bank Name", "Account Number", "IFSC", "Branch",
    "Amount", "Reference Number", "Narration", "Payment Date", "Currency", "Company Name",
]


def _headers(routing_label: str) -> list:
    """The 12-column header row with the routing column (index 4) set to
    the jurisdiction's canonical code name. India passes "IFSC", keeping
    its output byte-identical to the pre-multi-jurisdiction export."""
    headers = list(_HEADERS)
    headers[4] = routing_label
    return headers


def _routing_value(r: BankExportRow) -> str:
    """Jurisdiction routing value; falls back to the ifsc slot for rows
    built without the routing fields (India / legacy callers)."""
    return r.routing_value if r.routing_value is not None else (r.ifsc or "")


class CSVExporter(IBankExporter):
    content_type = "text/csv"
    file_extension = "csv"

    def generate(self, rows: List[BankExportRow], *, evaluation: bool = False) -> bytes:
        routing_label = rows[0].routing_label if rows else "IFSC"
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_headers(routing_label))
        for r in rows:
            writer.writerow([
                r.employee_name, r.employee_id, r.bank_name, r.account_number, _routing_value(r), r.branch or "",
                f"{r.amount:.2f}", r.reference_number, r.narration, r.payment_date, r.currency, r.company_name,
            ])
        return buf.getvalue().encode("utf-8")
