"""Byte-for-byte pins of the payslip PDF for the countries that are NOT Mexico
(Recibo de nómina v2.0, docs/mexico/MEXICO_RECIBO_REPORT.md): adding the
dedicated Mexican renderer must not change a single byte of the UK, US, DE,
HK, SG, IN or NL documents.

reportlab is put in invariant mode (fixed creation date and document id) so a
PDF is a pure function of its inputs; the payslip rows are SYNTHETIC and
inserted directly (no engine run), so the pins only cover the renderers. The
hashes were recorded from the code BEFORE the Mexican renderer was added."""

import hashlib
from datetime import date
from decimal import Decimal as D

import pytest

# Recorded at 6d081c9 (before the Mexican renderer), invariant mode.
PINNED = {
    "UK": "e85c08392ecf7659f7857c20c3c230797574745242b00ff7ab8cb03f0d20388b",
    "US": "a75b6cb007e6890cb896785c6741f67a381354ec7d3ca3bf5f2153d3f18fc19e",
    "DE": "b500323df06d76b716f91ed342faf967af10aa0de4d833d7a5b8b61fe1d3d300",
    "HK": "dd3968b9e1cc4b5fc11520606f1bbf72b68ac66aa860e9b9dda4b15b5f0f1db2",
    "SG": "540fe16775ac3138d0d104fa5f49a805dbcabc0526d81e3e44cbfc2611fc226d",
    "IN": "5c8af57c687b19719a2ad448a9f280871849944316a2d21dd8142c1c23658a49",
    "NL": "689cf02730b015034d82c82c58d8b10f9bf7e4b34ec84cf2b94506fb8d5c55e3",
}


def _render(db, organization, country, monkeypatch):
    from reportlab import rl_config

    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    monkeypatch.setattr(rl_config, "invariant", 1)
    emp = PayrollEmployee(organization_id=organization.id, name="Pin Employee", employee_code=f"PIN-{country}",
                          email=f"pin-{country.lower()}@example.com", country_code=country)
    db.add(emp)
    db.flush()
    run = PayrollRun(organization_id=organization.id, period_label="Oct 1-31, 2026", period_start=date(2026, 10, 1),
                     period_end=date(2026, 10, 31), pay_date=date(2026, 10, 31), status="Approved")
    db.add(run)
    db.flush()
    item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
                       employee_name="Pin Employee", country_code=country, status="Pending",
                       basic_salary=D("3000.00"), hra=D("0"), special_allowance=D("500.00"), overtime=D("0"),
                       gross_pay=D("3500.00"), tds=D("400.00"), total_deductions=D("400.00"), net_pay=D("3100.00"))
    db.add(item)
    db.commit()
    return service.generate_payslip_pdf_bytes(db, item.id, organization.id)


@pytest.mark.parametrize("country", sorted(PINNED))
def test_payslip_pdf_bytes_are_pinned(db, organization, country, monkeypatch):
    pdf = _render(db, organization, country, monkeypatch)
    assert pdf.startswith(b"%PDF")
    assert hashlib.sha256(pdf).hexdigest() == PINNED[country], f"{country} payslip PDF bytes changed"
