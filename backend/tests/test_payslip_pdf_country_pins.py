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
# Re-recorded again with page compression off, so the pin no longer depends on the
# zlib build and matches on every platform.
PINNED = {
    "UK": "42bcf01326a957d5be7ffb6c4d1d05e1addd0b318da61eb0858a55c7feabf27d",
    "US": "143ffbc3d4a016b62f2f7b317a98e8f846ed9ea833e645d75c88f1af1cef5d3d",
    "DE": "dd2a891479f22a0794e3d100c6f49877835e52c64101fc63b59fd7d0e161ff28",
    "HK": "085ef8e25953016449f01dd30e49cedd59a3b4b9330821ef95fd4734975ea2e5",
    "SG": "158310ad85abac42ae1271b06d668a29243b9ea59a5135b827dad38c5fc79518",
    "IN": "bc339db05eae09a89776e843c3f605e7c08966b5459a487531c5a0fea012b7fc",
    "NL": "eda3e9a880db606633089e965a9bbf6ff8043d8b01af4b417653fba8994b8403",
}


def _render(db, organization, country, monkeypatch):
    from reportlab import rl_config

    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    monkeypatch.setattr(rl_config, "invariant", 1)
    # Uncompressed page streams: compressed bytes depend on the zlib build
    # (stock zlib on the Linux CI/production image, zlib-ng in Windows CPython
    # 3.14), so a compressed pin can only ever match one platform.
    monkeypatch.setattr(rl_config, "pageCompression", 0)
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
