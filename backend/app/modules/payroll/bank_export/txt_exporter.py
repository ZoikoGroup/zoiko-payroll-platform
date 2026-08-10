from typing import List

from app.modules.payroll.bank_export.base import IBankExporter, BankExportRow

_HEADERS = [
    "EMPLOYEE_NAME", "EMPLOYEE_ID", "BANK_NAME", "ACCOUNT_NUMBER", "IFSC", "BRANCH",
    "AMOUNT", "REFERENCE_NUMBER", "NARRATION", "PAYMENT_DATE", "CURRENCY", "COMPANY_NAME",
]


class TXTExporter(IBankExporter):
    """Pipe-delimited plain text — the common denominator format most banks'
    bulk-upload portals accept when a bank-specific fixed-width spec isn't
    already known."""

    content_type = "text/plain"
    file_extension = "txt"

    def generate(self, rows: List[BankExportRow]) -> bytes:
        lines = ["|".join(_HEADERS)]
        for r in rows:
            lines.append("|".join([
                r.employee_name, r.employee_id, r.bank_name, r.account_number, r.ifsc, r.branch or "",
                f"{r.amount:.2f}", r.reference_number, r.narration, r.payment_date, r.currency, r.company_name,
            ]))
        return ("\n".join(lines) + "\n").encode("utf-8")
