"""Belgium (ZP-BE-ENG-001) Block L2: the payslip header, section and net-pay labels carry real content keys.

The on-screen view (frontend bePayslipLines.js BE_PAYSLIP_LABELS) and the PDF (belgium_payslip_pdf
BE_PAYSLIP_LABEL_KEYS) use one key set; every PDF section title is keyed, and the guide names the keys
without a "proposed" note.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS = {"be.payslip.header", "be.payslip.net", "be.payslip.section.bases", "be.payslip.section.employee",
        "be.payslip.section.employer", "be.payslip.section.obligations"}


def test_the_frontend_and_the_pdf_use_the_same_label_keys():
    from app.modules.payroll.belgium_payslip_pdf import BE_PAYSLIP_LABEL_KEYS

    js = (ROOT / "frontend/src/modules/payroll/PayRollRuns/bePayslipLines.js").read_text(encoding="utf-8")
    block = js.split("export const BE_PAYSLIP_LABELS", 1)[1].split("};", 1)[0]
    assert set(re.findall(r'"(be\.payslip\.[a-z.]+)"', block)) == KEYS
    assert set(BE_PAYSLIP_LABEL_KEYS.values()) == KEYS


def test_every_pdf_section_title_is_keyed():
    from app.modules.payroll.belgium_payslip_pdf import BE_PAYSLIP_LABEL_KEYS, be_payslip_sections

    assert {title for title, _lines in be_payslip_sections({})} <= set(BE_PAYSLIP_LABEL_KEYS)


def test_the_guide_has_no_proposed_keys_left():
    guide = (ROOT / "docs/belgium/guides/PAYSLIP_EXPLAINER.md").read_text(encoding="utf-8")
    assert "proposed key" not in guide
    for key in ("be.payslip.header", "be.payslip.net"):
        assert key in guide
