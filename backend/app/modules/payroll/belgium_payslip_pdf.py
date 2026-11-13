"""Belgian payslip PDF (ZP-BE-ENG-001 spec §11; Block H1).

Every Belgian payslip PDF (download, run ZIP, payslip e-mail) is produced here and nowhere else:

  * the content is the payslip's frozen ``be_calculation_snapshot`` only (bases, employee lines, net,
    employer composition, obligations, sector fields, document version) — nothing is computed here;
  * the NISS / BIS is printed only as the snapshot's masked form; a value carrying any digit is never
    printed (a second guard behind the engine's own masking);
  * a DEMO payslip (DEMO pack version, or an organisation on BE_DEMO_ORG_IDS) carries the
    "DEMO — NOT FOR PAYROLL" watermark on every page; an EVALUATION workspace keeps its own watermark;
  * a Belgian payslip without a snapshot is refused with a clear message — never a generic layout.

Payslip templates (main's PR #158) never apply to Belgium: payslip_template_service refuses a BE scope and
refuses to render a Belgian payslip, so the template / xhtml2pdf path cannot emit an unmarked Belgian PDF.
"""
from __future__ import annotations

import io
import re
from typing import Optional

from fastapi import HTTPException, status

from app.modules.payroll import belgium_demo

BE_PAYSLIP_PDF_NO_SNAPSHOT = "BE_PAYSLIP_NO_SNAPSHOT"
BE_TEMPLATE_REFUSAL = ("Belgian payslips use the Belgian statutory payslip layout (spec §11: masked NISS, "
                       "DEMO watermark); organisation payslip templates do not apply to Belgium.")
_DIGIT = re.compile(r"\d")


def be_is_belgian_payslip(item, data: Optional[dict] = None) -> bool:
    country = (getattr(item, "country_code", None) or (data or {}).get("country") or "").strip().upper()
    return country == "BE"


def be_masked_identifier(snapshot: dict) -> str:
    value = str((snapshot or {}).get("identifierMasked") or "").strip()
    if not value or _DIGIT.search(value):
        return "held in the identifier vault (not printed)"
    return value


def be_payslip_is_demo(snapshot: dict, organization_id) -> bool:
    return belgium_demo.be_snapshot_is_demo(snapshot) or belgium_demo.be_is_demo_org(organization_id)


def be_payslip_sections(snapshot: dict) -> list:
    """(title, [(label, amount)]) — the same split as the on-screen view (bePayslipLines.js)."""
    s = snapshot or {}

    def rows(pairs):
        return [(label, amount) for label, amount in pairs
                if amount not in (None, "") and str(amount).strip() not in ("0", "0.00", "0.0")]

    employee = [("Employee ONSS — base", s.get("be_onss_employee")),
                ("Social work bonus — reduction", s.get("be_social_work_bonus")),
                ("Employee ONSS after reduction", s.get("be_employee_total")),
                ("Professional withholding — regular", s.get("be_withholding_regular")),
                ("Fiscal work bonus — reduction (already in the withholding)", s.get("be_fiscal_work_bonus"))]
    for group, line in sorted((s.get("be_withholding_exceptional") or {}).items()):
        employee.append((f"Professional withholding — exceptional ({group.lower().replace('_', ' ')})",
                         (line or {}).get("withholding")))
    employer = [(f"Employer ONSS — {name.lower().replace('_', ' ')}", amount)
                for name, amount in sorted((s.get("be_onss_employer") or {}).items())]
    employer += [(f"Employer fund — {name.lower().replace('_', ' ')}", amount)
                 for name, amount in sorted((s.get("be_funds") or {}).items())]
    employer.append(("Occupational pension — special", s.get("be_pension_special")))
    employer.append(("Employer total", s.get("be_employer_total")))
    return [
        ("Bases", rows((name.lower().replace("_", " "), amount)
                       for name, amount in sorted((s.get("bases") or {}).items()))),
        ("Employee contributions and withholding", rows(employee)),
        ("Net pay", rows([("Net pay", s.get("be_net"))])),
        ("Employer contributions (not deducted)", rows(employer)),
        ("Obligations", rows(sorted((s.get("obligationDeltas") or {}).items()))),
    ]


def be_payslip_pdf_bytes(data: dict, item, run, company_name: str, company_address: str,
                         organization_id, evaluation: bool = False) -> bytes:
    """The Belgian payslip PDF, or 409 BE_PAYSLIP_NO_SNAPSHOT."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from app.modules.payroll.service import _draw_evaluation_watermark

    snapshot = {k: v for k, v in (getattr(item, "be_calculation_snapshot", None) or {}).items()
                if k != "frozenContext"}
    if not snapshot:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "code": BE_PAYSLIP_PDF_NO_SNAPSHOT,
            "message": "This Belgian payslip has no frozen Belgian calculation, so no PDF is produced "
                       "(a generic layout would omit the §11 content). Recalculate the run."})
    demo = be_payslip_is_demo(snapshot, organization_id)
    styles = getSampleStyleSheet()
    sector = snapshot.get("sector") or {}
    story = []
    if demo:
        story.append(Paragraph(f"<b>{escape(belgium_demo.DEMO_LABEL)}</b>", styles["Title"]))
    story += [
        Paragraph(escape(company_name or "Company"), styles["Title"]),
        Paragraph(escape(company_address or ""), styles["Normal"]),
        Paragraph(f"Payslip — {escape(str(data.get('period') or getattr(run, 'period_label', '') or ''))}",
                  styles["Heading2"]),
    ]
    header = [
        ("Employee", data.get("employee") or getattr(item, "employee_name", None)),
        ("Payslip", data.get("payslipNumber") or getattr(item, "payslip_number", None)),
        ("Pay date", data.get("payDate")),
        ("NISS / BIS", be_masked_identifier(snapshot)),
        ("Joint committee", sector.get("jointCommittee")),
        ("Sub-committee", sector.get("subCommittee")),
        ("Function class", sector.get("functionClass")),
        ("Employment line", snapshot.get("employmentLine")),
        ("Document version", snapshot.get("documentVersion")),
    ]
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9)])
    story.append(Table([[label, escape(str(value)) if value not in (None, "") else "-"] for label, value in header],
                       colWidths=[45 * mm, 120 * mm], style=grid))
    for title, lines in be_payslip_sections(snapshot):
        if not lines:
            continue
        story += [Spacer(1, 4 * mm), Paragraph(escape(title), styles["Heading3"])]
        story.append(Table([[escape(label), f"EUR {amount}"] for label, amount in lines],
                           colWidths=[125 * mm, 40 * mm], style=grid))

    def stamp(canvas, doc):
        width, height = A4
        if demo:
            _draw_evaluation_watermark(canvas, width, height, text=belgium_demo.DEMO_LABEL)
        if evaluation:
            _draw_evaluation_watermark(canvas, width, height)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Belgian payslip (DEMO)" if demo else "Belgian payslip")
    doc.build(story, onFirstPage=stamp, onLaterPages=stamp)
    return buf.getvalue()
