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
# Re-recorded again with page compression off and reportlab's bundled Vera font, so
# the pin depends on neither the zlib build nor the host's installed fonts.
PINNED = {
    "UK": "02c863a3d2c99dee118bd2e29537233767e58cebade6ec09c5a70da515e12722",
    "US": "e08ec619d609d6741f0b7df40c96c1a5cd74d62ac4dddc51871ce003f2bf2714",
    "DE": "34f286fb6366a75a1fa050453245ee06cc6a1a71239d5421cbcfb6da8b1f26b1",
    "HK": "632c8435ac3487a461746d7eebb2244b324f165e57f1b10e644e7f0afdfd344e",
    "SG": "8962e4c62984a3823378b4295899b4ef8fb807de2ba720a510bafafac920775b",
    "IN": "7096ead7a552977d9c384e6b31c19c70e9512866415e46ef43650cc6b584a986",
    "NL": "a9ce3e9b37cfa933d21e1686b549a8fe61ec4b90d691771521e8ebbf764e45c7",
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
    # The renderer embeds the first Unicode TTF installed on the host (Arial on
    # Windows, DejaVu/Liberation on Linux), so pin the font to the Vera TTFs that
    # ship inside reportlab itself: the bytes are then the same on every machine.
    import os

    import reportlab

    fonts = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    monkeypatch.setattr(service, "unicode_font_candidates",
                        lambda: [(os.path.join(fonts, "Vera.ttf"), os.path.join(fonts, "VeraBd.ttf"))])
    # reportlab binds a TTF font name only once per process (first registration
    # wins), so a payslip rendered earlier by another test would keep the host
    # font under these names. Unbind them for this test; monkeypatch restores them.
    from reportlab.pdfbase import pdfmetrics

    for name in ("RupeeFont", "RupeeFont-Bold"):
        monkeypatch.delitem(pdfmetrics._fonts, name, raising=False)
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
