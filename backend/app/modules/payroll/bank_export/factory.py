from app.modules.payroll.bank_export.base import IBankExporter
from app.modules.payroll.bank_export.csv_exporter import CSVExporter
from app.modules.payroll.bank_export.excel_exporter import ExcelExporter
from app.modules.payroll.bank_export.txt_exporter import TXTExporter
from app.modules.payroll.bank_export.pdf_exporter import PDFExporter

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
