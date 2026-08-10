"""
modules/payroll/bank_export/base.py
------------------------------------
IBankExporter interface + the row shape every exporter consumes.

This module is intentionally decoupled from PayrollRun/PayslipItem — the
router/service layer assembles BankExportRow objects from already-computed
payroll data and hands them to an exporter. Adding a new format (or, later,
a real BankAPIExporter that calls out to a bank's API instead of returning
bytes) only means adding one class here and registering it in factory.py —
no changes to payroll calculation or run-approval logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class BankExportRow:
    employee_name: str
    employee_id: str
    bank_name: str
    account_number: str
    ifsc: str
    branch: Optional[str]
    amount: float
    reference_number: str
    narration: str
    payment_date: str
    currency: str
    company_name: str


class IBankExporter(ABC):
    """Every exporter generates file bytes for a full bank transfer batch
    plus declares the content-type/extension the router needs for the
    download response."""

    content_type: str
    file_extension: str

    @abstractmethod
    def generate(self, rows: List[BankExportRow]) -> bytes:
        ...
