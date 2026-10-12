from app.modules.payroll.bank_export.base import IBankExporter
from app.modules.payroll.bank_export.csv_exporter import CSVExporter
from app.modules.payroll.bank_export.excel_exporter import ExcelExporter
from app.modules.payroll.bank_export.txt_exporter import TXTExporter
from app.modules.payroll.bank_export.pdf_exporter import PDFExporter

# NOTE (Prompt 3): every exporter below generates FILE BYTES only — none of
# them moves money. If a future engineer adds a live transfer integration
# (a BankAPIExporter that calls a bank's disbursement API instead of
# returning bytes), it MUST call billing.entitlements.require_production_workspace()
# before submitting any transfer, so EVALUATION workspaces can never send
# real payments. Register it here so the same format-key lookup covers it.

_EXPORTERS = {
    "csv": CSVExporter,
    "xlsx": ExcelExporter,
    "txt": TXTExporter,
    "pdf": PDFExporter,
}


def get_exporter(format_key: str) -> IBankExporter:
    cls = _EXPORTERS.get((format_key or "csv").lower())
    if not cls:
        raise ValueError(f"Unsupported bank export format: {format_key!r}")
    return cls()
