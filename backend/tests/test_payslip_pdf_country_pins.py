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

# Re-recorded 2026-11-13 when origin/main was merged into rugvedh: main's
# payslip_line_items refactor changed every country's PDF. The merged code renders
# exactly the bytes origin/main renders for these countries (checked side by side), so
# the Mexican Recibo dispatch still changes none of them. (First recorded at 6d081c9.)
PINNED = {
    "UK": "612f7977eaf726f2bc0c5892f5b909800ca0d7ad4e54f4f8f26c94a3e6d62016",
    "US": "a8beaac486777dcc32c306a80ecf714c94685a09e2570b67f63f12a91d59447f",
    "DE": "75d3f257c5700c818cb929d002158cabeedb746e3567b5df2e5b16154f1c6ff9",
    "HK": "398137dc36848c51bcdcfada657212cdb41d5b647760481159d09928448851f4",
    "SG": "1aaf1f33a46b467e653c33dfdbe5087d9358b07258a2a1645305b52cefb42cf6",
    "IN": "1e306447cb81d79d1878f9e6deb0da70d4ded448e78d360968b7a29fc7914cfb",
    "NL": "d21ce206bdf8cf0bb2206261ac94d913b744014e03e31633b6dcbeecebd01ef1",
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
