from typing import List

from app.modules.payroll.bank_export.base import IBankExporter, BankExportRow

_HEADERS = [
    "EMPLOYEE_NAME", "EMPLOYEE_ID", "BANK_NAME", "ACCOUNT_NUMBER", "IFSC", "BRANCH",
    "AMOUNT", "REFERENCE_NUMBER", "NARRATION", "PAYMENT_DATE", "CURRENCY", "COMPANY_NAME",
]


def _routing_value(r: BankExportRow) -> str:
    """Jurisdiction routing value; falls back to the ifsc slot for rows
    built without the routing fields (India / legacy callers)."""
    return r.routing_value if r.routing_value is not None else (r.ifsc or "")


class TXTExporter(IBankExporter):
    """Pipe-delimited plain text — the common denominator format most banks'
    bulk-upload portals accept when a bank-specific fixed-width spec isn't
    already known."""

    content_type = "text/plain"
    file_extension = "txt"

    def generate(self, rows: List[BankExportRow], *, evaluation: bool = False) -> bytes:
        routing_label = rows[0].routing_label if rows else "IFSC"
        headers = list(_HEADERS)
        headers[4] = routing_label.upper()
        lines = ["|".join(headers)]
        for r in rows:
            lines.append("|".join([
                r.employee_name, r.employee_id, r.bank_name, r.account_number, _routing_value(r), r.branch or "",
                f"{r.amount:.2f}", r.reference_number, r.narration, r.payment_date, r.currency, r.company_name,
            ]))
        return ("\n".join(lines) + "\n").encode("utf-8")
