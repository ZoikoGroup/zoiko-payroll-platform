"""Belgium (ZP-BE-ENG-001) Block K1: employee documents on the shared report-template mechanism.

Three documents, each a payroll_report_templates row (components + fields describe the layout; labels are content
keys for nl / fr / de, D10) rendered by this module from COMMITTED data only — nothing is recalculated:

  INDIVIDUAL_ACCOUNT       the annual individual account (individuele rekening / compte individuel): employer and
                           employee identification (NISS masked), every committed payslip of the year (runs and
                           corrections) and the totals by ledger component, ONSS employee / employer, withholding,
                           net paid — from the committed ledger (payroll_be_accumulator_entries) and the approved
                           payslips;
  BELCOTAX_EMPLOYEE_COPY   the employee copy of the 281.10 fiche: the employee-facing amounts of the fiche payload,
                           the dependants the year's calculations used, and the correction / cancellation lineage;
  HOLIDAY_CERTIFICATE      the holiday certificate (BE-027) from payroll_be_holiday_certificates; only an APPROVED
                           certificate (immutable, the table's rule) is issued.

Gating (unchanged): a template is seeded Draft; PREVIEW (JSON / PDF, watermarked "PREVIEW — TEMPLATE NOT
APPROVED") works now for testing; GENERATION (the employee-facing document, stored in payroll_generated_reports)
needs an Active template, and activation is decided by template_activation_refusal. No statutory value lives here.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import belgium_service as be

INDIVIDUAL_ACCOUNT = "INDIVIDUAL_ACCOUNT"
BELCOTAX_EMPLOYEE_COPY = "BELCOTAX_EMPLOYEE_COPY"
HOLIDAY_CERTIFICATE = "HOLIDAY_CERTIFICATE"
PREVIEW_LABEL = "PREVIEW — TEMPLATE NOT APPROVED"
_COMMITTED = ("APPROVED", "AUTHORIZED", "PAID", "CLOSED")

_EMPLOYER = ("employer", "be.report.employer", (
    ("legal_name", "be.report.employer.legal_name", "text", "BE_RECORDS", "registration.legal_name", True),
    ("enterprise_number", "be.report.employer.enterprise_number", "text", "BE_RECORDS",
     "registration.enterprise_number", True),
    ("employer_onss_masked", "be.report.employer.onss_number", "text", "BE_RECORDS", "registration.onss (masked)",
     False)))
_EMPLOYEE = ("employee", "be.report.employee", (
    ("employee_name", "be.report.employee.name", "text", "BE_RECORDS", "payroll_employees.name", True),
    ("employee_code", "be.report.employee.code", "text", "BE_RECORDS", "payroll_employees.employee_code", True),
    ("identifier_masked", "be.report.employee.niss", "text", "BE_RECORDS", "identifier vault (masked)", True)))

# (template key, name, document version, components: (key, label, ((field, label, type, source kind, column, req))))
TEMPLATES = {
    INDIVIDUAL_ACCOUNT: (be.BE_INDIVIDUAL_ACCOUNT_KEY, "Individual account (BE)", "BE-INDIVIDUAL-ACCOUNT-A", (
        ("document", "be.report.document", (
            ("document_version", "be.report.document.version", "text", "BE_RECORDS", "document version", True),
            ("reporting_year", "be.report.document.year", "text", "BE_RECORDS", "reporting year", True))),
        _EMPLOYER, _EMPLOYEE,
        ("periods", "be.report.individual_account.periods", (
            ("period_lines", "be.report.individual_account.period_lines", "text", "BE_LEDGER",
             "committed payslips + ledger entries per payslip", True),)),
        ("totals", "be.report.individual_account.totals", (
            ("gross_total", "be.report.total.gross", "currency", "BE_SNAPSHOT", "payslip_items.gross_pay", True),
            ("component_totals", "be.report.total.components", "text", "BE_LEDGER", "ledger accumulators", True),
            ("onss_employee_total", "be.report.total.onss_employee", "currency", "BE_LEDGER", "ONSS_EMPLOYEE", True),
            ("work_bonus_social_total", "be.report.total.work_bonus_social", "currency", "BE_LEDGER",
             "WORK_BONUS_SOCIAL", True),
            ("employer_contributions_total", "be.report.total.employer_contributions", "currency", "BE_SNAPSHOT",
             "be_employer_total / employerTotalDelta", True),
            ("withholding_total", "be.report.total.withholding", "currency", "BE_LEDGER",
             "WITHHOLDING + WITHHOLDING_EXCEPTIONAL", True),
            ("net_paid_total", "be.report.total.net_paid", "currency", "BE_SNAPSHOT", "payslip_items.net_pay", True))),
    )),
    BELCOTAX_EMPLOYEE_COPY: ("BE-BELCOTAX-EMPLOYEE-COPY", "Belcotax fiche — employee copy (BE)", "BE-FICHE-COPY-A", (
        ("document", "be.report.document", (
            ("document_version", "be.report.document.version", "text", "BE_RECORDS", "document version", True),
            ("income_year", "be.report.fiche.income_year", "text", "BE_FILING", "payroll_be_filings.period_key", True),
            ("fiche_kind", "be.report.fiche.kind", "text", "BE_FILING", "payroll_be_filings.kind", True),
            ("fiche_version", "be.report.fiche.version", "text", "BE_FILING", "payroll_be_filings.version", True),
            ("fiche_status", "be.report.fiche.status", "text", "BE_FILING", "payroll_be_filings.status", True))),
        ("employer", "be.report.employer", (
            ("legal_name", "be.report.employer.legal_name", "text", "BE_FILING", "payload.employer.legalName", True),
            ("enterprise_number", "be.report.employer.enterprise_number", "text", "BE_FILING",
             "payload.employer.enterpriseNumber", True))),
        ("employee", "be.report.employee", (
            ("employee_name", "be.report.employee.name", "text", "BE_RECORDS", "payroll_employees.name", True),
            ("identifier_masked", "be.report.employee.niss", "text", "BE_FILING", "payload.worker.identifierMasked",
             True))),
        ("amounts", "be.report.fiche.amounts", (
            ("regular_taxable", "be.report.fiche.regular_taxable", "currency", "BE_FILING",
             "payload.remuneration.regularTaxable", True),
            ("exceptional_taxable", "be.report.fiche.exceptional_taxable", "currency", "BE_FILING",
             "payload.remuneration.exceptionalTaxable", True),
            ("withholding_regular", "be.report.fiche.withholding_regular", "currency", "BE_FILING",
             "payload.withholding.regular", True),
            ("withholding_exceptional", "be.report.fiche.withholding_exceptional", "currency", "BE_FILING",
             "payload.withholding.exceptional", True),
            ("onss_employee", "be.report.fiche.onss_employee", "currency", "BE_FILING", "payload.onssEmployee", True),
            ("work_bonus_social", "be.report.fiche.work_bonus_social", "currency", "BE_FILING",
             "payload.workBonus.social", True),
            ("work_bonus_fiscal", "be.report.fiche.work_bonus_fiscal", "currency", "BE_FILING",
             "payload.workBonus.fiscal", True),
            ("coding", "be.report.fiche.coding", "text", "BE_FILING", "payload.coding (box codes: content, G-08)",
             True))),
        ("dependants", "be.report.fiche.dependants", (
            ("dependants_used", "be.report.fiche.dependants_used", "text", "BE_SNAPSHOT",
             "frozenContext.lists.be_declarations (DEPENDANTS) of the year's committed payslips", True),)),
        ("lineage", "be.report.fiche.lineage", (
            ("lineage", "be.report.fiche.lineage_versions", "text", "BE_FILING",
             "payroll_be_filings (same employee + year): kind / version / status / corrects", True),)),
    )),
    HOLIDAY_CERTIFICATE: ("BE-HOLIDAY-CERTIFICATE", "Holiday certificate (BE)", "BE-HOLIDAY-CERTIFICATE-A", (
        ("document", "be.report.document", (
            ("document_version", "be.report.document.version", "text", "BE_RECORDS", "document version", True),)),
        _EMPLOYER, _EMPLOYEE,
        ("certificate", "be.report.holiday.certificate", (
            ("direction", "be.report.holiday.direction", "text", "BE_HOLIDAY_CERT", "direction (IN / OUT)", True),
            ("service_year", "be.report.holiday.service_year", "text", "BE_HOLIDAY_CERT", "service_year", True),
            ("issued_on", "be.report.holiday.issued_on", "date", "BE_HOLIDAY_CERT", "issued_on", False),
            ("prior_employer_ref", "be.report.holiday.prior_employer", "text", "BE_HOLIDAY_CERT",
             "prior_employer_ref (IN only)", False),
            ("status", "be.report.holiday.status", "text", "BE_HOLIDAY_CERT", "status", True),
            ("approved_at", "be.report.holiday.approved_at", "date", "BE_HOLIDAY_CERT", "approved_at", False))),
        ("amounts", "be.report.holiday.amounts", (
            ("gross_base_amount", "be.report.holiday.gross_base", "currency", "BE_HOLIDAY_CERT", "gross_base_amount",
             False),
            ("simple_pay_amount", "be.report.holiday.simple_pay", "currency", "BE_HOLIDAY_CERT", "simple_pay_amount",
             False),
            ("double_pay_amount", "be.report.holiday.double_pay", "currency", "BE_HOLIDAY_CERT", "double_pay_amount",
             False),
            ("days_paid", "be.report.holiday.days_paid", "text", "BE_HOLIDAY_CERT", "days_paid", False))),
    )),
}


def _s(value) -> Optional[str]:
    return None if value is None else str(value)


def _models():
    from app.modules.payroll import models

    return models


# ── templates (Draft only; activation stays with template_activation_refusal) ──
def be_seed_report_templates(db: Session, reporting_year: str, actor_id=None) -> list:
    """The three Belgian employee-document templates for `reporting_year`, created DRAFT with their components and
    fields when missing (an existing template — any status — is never changed)."""
    m = _models()
    out = []
    for report_type, (key, name, version, components) in TEMPLATES.items():
        template = (db.query(m.ReportTemplate).filter(m.ReportTemplate.template_key == key,
                                                      m.ReportTemplate.reporting_year == str(reporting_year))
                    .order_by(m.ReportTemplate.id).first())
        if template is None:
            template = m.ReportTemplate(
                template_key=key, name=name, report_type=report_type, jurisdiction_country=be.BE,
                reporting_year=str(reporting_year), version="1.0", status="Draft", document_scope="EMPLOYEE",
                description=f"{name}: rendered from committed Belgian payroll only (document {version}); labels are "
                            "nl / fr / de content keys (D10). Employee-facing only once Active.")
            db.add(template)
            db.flush()
            be._audit(db, actor_id, "created", "be_report_template", template.id,
                      new={"key": key, "year": str(reporting_year), "type": report_type})
        if template.status == "Draft" and not db.query(m.ReportTemplateComponent).filter(
                m.ReportTemplateComponent.report_template_id == template.id).first():
            for order, (ckey, clabel, fields) in enumerate(components):
                component = m.ReportTemplateComponent(report_template_id=template.id, component_key=ckey,
                                                      label=clabel, component_category="jurisdiction_specific",
                                                      sort_order=order)
                db.add(component)
                db.flush()
                for forder, (fkey, flabel, ftype, kind, column, required) in enumerate(fields):
                    db.add(m.ReportTemplateComponentField(
                        component_id=component.id, field_key=fkey, label=flabel, field_type=ftype,
                        data_source_kind=kind, source_column=column[:50], is_required=required, sort_order=forder))
            db.flush()
        out.append(template)
    return out


def _template(db: Session, report_type: str, reporting_year: str):
    m = _models()
    key = TEMPLATES[report_type][0]
    rows = (db.query(m.ReportTemplate).filter(m.ReportTemplate.template_key == key,
                                              m.ReportTemplate.jurisdiction_country == be.BE,
                                              m.ReportTemplate.reporting_year == str(reporting_year))
            .order_by(m.ReportTemplate.id.desc()).all())
    return next((t for t in rows if t.status == "Active"), rows[0] if rows else None)


def be_required_fields(report_type: str) -> dict:
    """{component: [required field keys]} of a document type."""
    return {ckey: [f[0] for f in fields if f[5]] for ckey, _label, fields in TEMPLATES[report_type][3]}


# ── shared identification blocks ──
def _employee_block(db: Session, organization_id: int, employee) -> dict:
    return {"employee_name": employee.name, "employee_code": employee.employee_code,
            "identifier_masked": be._be_identifier_masked(db, organization_id, employee.id)
            or "held in the identifier vault (not printed)"}


def _employer_block(db: Session, organization_id: int, legal_entity_id, on: date) -> dict:
    from app.modules.payroll import be_identifiers as bid

    reg = be._be_registration_for(db, organization_id, legal_entity_id, on)
    if reg is None:
        raise BadRequestException("No Belgian employer registration is in force for the document date.")
    return {"legal_name": reg.legal_name, "enterprise_number": reg.enterprise_number,
            "employer_onss_masked": bid.masked(bid.ONSS) if getattr(reg, "onss_number_vault_id", None) else None}


# ── data (committed only) ──
def be_individual_account_data(db: Session, organization_id: int, employee_id: int, year) -> dict:
    """The individual account of one employee for one calendar year, from committed payroll only."""
    m = _models()
    year = int(year)
    employee = be._employee(db, organization_id, employee_id)
    runs = {r.id: r for r in db.query(m.PayrollRun).filter(m.PayrollRun.organization_id == organization_id,
                                                           m.PayrollRun.pay_date >= date(year, 1, 1),
                                                           m.PayrollRun.pay_date <= date(year, 12, 31)).all()
            if be._run_status(r).upper() in _COMMITTED}
    items = be.be_snapshot_facts(
        db, (m.PayslipItem.employee_id == employee.id, m.PayslipItem.payroll_run_id.in_(sorted(runs) or [0])),
        order_by=(m.PayslipItem.id,), correctionOf="correctionOf", employerTotal="be_employer_total",
        employerTotalDelta="employerTotalDelta") if runs else []
    Entry = be._models().PayrollBeAccumulatorEntry
    ledger = {}
    for e in db.query(Entry).filter(Entry.organization_id == organization_id, Entry.employee_id == employee.id,
                                    Entry.year == year, Entry.entry_kind.in_(("RUN", "CORRECTION"))).all():
        bucket = ledger.setdefault(e.payslip_item_id, {})
        bucket[e.accumulator] = bucket.get(e.accumulator, Decimal("0")) + Decimal(str(e.amount))
    lines, totals = [], {}
    gross = net = employer = Decimal("0")
    for item in items:
        run = runs[item.payroll_run_id]
        employer_part = Decimal(str((item.employerTotalDelta if item.correctionOf else item.employerTotal) or 0))
        components = ledger.get(item.id, {})
        for name, amount in components.items():
            totals[name] = totals.get(name, Decimal("0")) + amount
        gross += Decimal(str(item.gross_pay or 0))
        net += Decimal(str(item.net_pay or 0))
        employer += employer_part
        lines.append({"payslipId": item.id, "payDate": run.pay_date.isoformat(), "period": run.period_label,
                      "kind": "CORRECTION" if item.correctionOf else "RUN", "correctionOf": item.correctionOf,
                      "gross": _s(item.gross_pay), "net": _s(item.net_pay), "employerContributions": _s(employer_part),
                      "components": {k: _s(v) for k, v in sorted(components.items())}})
    withholding = totals.get("WITHHOLDING", Decimal("0")) + totals.get("WITHHOLDING_EXCEPTIONAL", Decimal("0"))
    return _document(INDIVIDUAL_ACCOUNT, {
        "document": {"document_version": TEMPLATES[INDIVIDUAL_ACCOUNT][2], "reporting_year": str(year)},
        "employer": _employer_block(db, organization_id, employee.legal_entity_id, date(year, 12, 31)),
        "employee": _employee_block(db, organization_id, employee),
        "periods": {"period_lines": lines},
        "totals": {"gross_total": _s(gross), "component_totals": {k: _s(v) for k, v in sorted(totals.items())},
                   "onss_employee_total": _s(totals.get("ONSS_EMPLOYEE", Decimal("0"))),
                   "work_bonus_social_total": _s(totals.get("WORK_BONUS_SOCIAL", Decimal("0"))),
                   "employer_contributions_total": _s(employer), "withholding_total": _s(withholding),
                   "net_paid_total": _s(net)},
    }, scope=f"E{employee.id}:{year}", year=str(year), employee_id=employee.id)


def be_belcotax_copy_data(db: Session, organization_id: int, filing_id: int) -> dict:
    """The employee copy of a 281.10 fiche: its employee-facing payload fields, the dependants the year's committed
    calculations used, and the correction / cancellation lineage of the fiche."""
    from app.modules.payroll import belgium_filing as bf

    m = _models()
    row = bf._filing(db, organization_id, filing_id)
    if row.form_code != "BELCOTAX":
        raise BadRequestException("Only a Belcotax fiche has an employee copy.")
    payload = row.payload or {}
    employee_id = int(str(row.subject_key or "E0")[1:] or 0)
    employee = be._employee(db, organization_id, employee_id)
    F = row.__class__
    lineage = [{"filingId": f.id, "kind": f.kind, "version": f.version, "status": f.status,
                "correctsId": f.corrects_id}
               for f in db.query(F).filter(F.organization_id == organization_id, F.form_code == "BELCOTAX",
                                           F.period_key == row.period_key, F.subject_key == row.subject_key)
               .order_by(F.id).all()]
    year = int(row.period_key)
    runs = [r.id for r in db.query(m.PayrollRun).filter(m.PayrollRun.organization_id == organization_id,
                                                        m.PayrollRun.pay_date >= date(year, 1, 1),
                                                        m.PayrollRun.pay_date <= date(year, 12, 31)).all()
            if be._run_status(r).upper() in _COMMITTED]
    facts = be.be_snapshot_facts(db, (m.PayslipItem.employee_id == employee.id, m.PayslipItem.payroll_run_id.in_(
        runs or [0])), order_by=(m.PayslipItem.id,), declarations=("frozenContext", "lists")) if runs else []
    dependants = None
    for f in facts:                                     # the latest committed calculation of the year that used one
        for d in ((f.declarations or {}).get("be_declarations") or []):
            if str(d.get("declaration_type") or "").upper() == "DEPENDANTS":
                dependants = (d.get("value") or {}).get("count")
    remuneration, withholding = payload.get("remuneration") or {}, payload.get("withholding") or {}
    bonus = payload.get("workBonus") or {}
    employer = payload.get("employer") or {}
    return _document(BELCOTAX_EMPLOYEE_COPY, {
        "document": {"document_version": TEMPLATES[BELCOTAX_EMPLOYEE_COPY][2], "income_year": row.period_key,
                     "fiche_kind": row.kind, "fiche_version": row.version, "fiche_status": row.status},
        "employer": {"legal_name": employer.get("legalName"), "enterprise_number": employer.get("enterpriseNumber")},
        "employee": {"employee_name": employee.name,
                     "identifier_masked": (payload.get("worker") or {}).get("identifierMasked")
                     or "held in the identifier vault (not printed)"},
        "amounts": {"regular_taxable": remuneration.get("regularTaxable"),
                    "exceptional_taxable": remuneration.get("exceptionalTaxable"),
                    "withholding_regular": withholding.get("regular"),
                    "withholding_exceptional": withholding.get("exceptional"),
                    "onss_employee": payload.get("onssEmployee"), "work_bonus_social": bonus.get("social"),
                    "work_bonus_fiscal": bonus.get("fiscal"), "coding": payload.get("coding")},
        "dependants": {"dependants_used": _s(dependants) if dependants is not None else "none declared"},
        "lineage": {"lineage": lineage},
    }, scope=f"F{row.subject_key}:{row.period_key}", year=row.period_key, employee_id=employee.id,
        demo=bool(payload.get("demo")))


def be_holiday_certificate_data(db: Session, organization_id: int, certificate_id: int) -> dict:
    """The holiday certificate (BE-027) as recorded; an APPROVED certificate is immutable (the table's rule)."""
    C = be._models().PayrollBeHolidayCertificate
    row = db.query(C).filter(C.id == certificate_id, C.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Belgian holiday certificate")
    employee = be._employee(db, organization_id, row.employee_id)
    on = row.issued_on or date(int(row.service_year), 12, 31)
    return _document(HOLIDAY_CERTIFICATE, {
        "document": {"document_version": TEMPLATES[HOLIDAY_CERTIFICATE][2]},
        "employer": _employer_block(db, organization_id, employee.legal_entity_id, on),
        "employee": _employee_block(db, organization_id, employee),
        "certificate": {"direction": row.direction, "service_year": _s(row.service_year),
                        "issued_on": row.issued_on.isoformat() if row.issued_on else None,
                        "prior_employer_ref": row.prior_employer_ref, "status": row.status,
                        "approved_at": row.approved_at.isoformat() if getattr(row, "approved_at", None) else None},
        "amounts": {"gross_base_amount": _s(row.gross_base_amount), "simple_pay_amount": _s(row.simple_pay_amount),
                    "double_pay_amount": _s(row.double_pay_amount), "days_paid": _s(row.days_paid)},
    }, scope=f"C{row.id}", year=_s(row.service_year), employee_id=employee.id, certificate_status=row.status)


def _document(report_type: str, sections: dict, **meta) -> dict:
    return {"reportType": report_type, "documentVersion": TEMPLATES[report_type][2], "sections": sections,
            "_meta": meta}


def _build(db: Session, organization_id: int, report_type: str, params: dict) -> dict:
    """Explicit dispatch (the route registry's call graph follows named calls, not a table of lambdas)."""
    p = dict(params or {})
    try:
        if report_type == INDIVIDUAL_ACCOUNT:
            return be_individual_account_data(db, organization_id, int(p.get("employeeId")), p.get("year"))
        if report_type == BELCOTAX_EMPLOYEE_COPY:
            return be_belcotax_copy_data(db, organization_id, int(p.get("filingId")))
        if report_type == HOLIDAY_CERTIFICATE:
            return be_holiday_certificate_data(db, organization_id, int(p.get("certificateId")))
    except (TypeError, ValueError):
        raise BadRequestException("Missing or invalid document parameters.")
    raise BadRequestException(f"Unknown Belgian document {report_type!r}; one of {', '.join(TEMPLATES)}.")


# ── preview (now, for testing) and generation (only with an Active template) ──
def be_report_preview(db: Session, organization_id: int, report_type: str, params: dict) -> dict:
    """The document as it would be issued, marked PREVIEW unless its template is Active. Writes nothing."""
    from app.modules.payroll import belgium_demo

    doc = _build(db, organization_id, report_type, params)
    meta = doc.pop("_meta")
    template = _template(db, report_type, meta.get("year") or "")
    active = template is not None and template.status == "Active"
    demo = bool(meta.get("demo")) or belgium_demo.be_is_demo_org(organization_id)
    return {**doc, "preview": not active, "templateKey": TEMPLATES[report_type][0],
            "templateStatus": template.status if template is not None else "NOT SEEDED",
            "watermarks": ([PREVIEW_LABEL] if not active else []) + ([belgium_demo.DEMO_LABEL] if demo else [])}


def be_report_generate(db: Session, organization_id: int, report_type: str, params: dict, actor_id=None):
    """The employee-facing document: refused unless the template is Active (template_activation_refusal decides
    activation). A holiday certificate is issued only when APPROVED. One live document per scope (the previous is
    superseded, never edited)."""
    from app.modules.payroll import service

    doc = _build(db, organization_id, report_type, params)
    meta = doc.pop("_meta")
    if report_type == HOLIDAY_CERTIFICATE and meta.get("certificate_status") != "APPROVED":
        raise BadRequestException("Only an APPROVED holiday certificate is issued (an approved one is immutable).")
    template = _template(db, report_type, meta.get("year") or "")
    if template is None:
        raise BadRequestException("The Belgian document template is not seeded for this year.")
    template = service.require_active_report_template(
        db, template.id, country=be.BE, report_types=(report_type,),
        wrong_country_message=lambda t: f"Template {t.template_key} is not a Belgian template.",
        wrong_type_message=lambda t: f"Template {t.template_key} is not a {report_type} template.")
    GeneratedReport = _models().GeneratedReport
    previous = service.supersede_live_reports(db, organization_id, report_type, scope_key=meta["scope"],
                                              jurisdiction_country=be.BE, reporting_year=meta.get("year"))
    if previous:
        db.flush()
    row = GeneratedReport(organization_id=organization_id, report_template_id=template.id,
                          template_version=template.version, report_type=report_type, payroll_run_id=None,
                          employee_id=meta.get("employee_id"), scope_key=meta["scope"], jurisdiction_country=be.BE,
                          reporting_year=meta.get("year"), status="Generated", generated_by_id=actor_id,
                          rendered_data={**doc, "supersedesReportIds": previous or []})
    db.add(row)
    db.flush()
    be._audit(db, actor_id, "generated", "be_report", row.id, new={"type": report_type, "scope": meta["scope"]})
    return row


# ── PDF ──
def be_report_pdf(view: dict) -> bytes:
    """A plain PDF of a previewed / generated document (sections as label / value tables), watermarked as listed."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from app.modules.payroll.service import _draw_evaluation_watermark

    styles = getSampleStyleSheet()
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8),
                       ("VALIGN", (0, 0), (-1, -1), "TOP")])
    story = [Paragraph(escape(TEMPLATES[view["reportType"]][1]), styles["Title"])]
    story += [Paragraph(f"<b>{escape(w)}</b>", styles["Heading2"]) for w in view.get("watermarks") or []]
    for section, values in view["sections"].items():
        story += [Spacer(1, 3 * mm), Paragraph(escape(section.replace("_", " ").title()), styles["Heading3"])]
        rows = []
        for key, value in values.items():
            if isinstance(value, list):
                text = "<br/>".join(escape(", ".join(f"{k}: {v}" for k, v in entry.items() if v is not None))
                                    for entry in value) or "-"
            elif isinstance(value, dict):
                text = "<br/>".join(escape(f"{k}: {v}") for k, v in value.items()) or "-"
            else:
                text = escape("-" if value in (None, "") else str(value))
            rows.append([escape(key.replace("_", " ")), Paragraph(text, styles["BodyText"])])
        story.append(Table(rows, colWidths=[50 * mm, 120 * mm], style=grid))

    def stamp(canvas, _doc):
        width, height = A4
        for mark in view.get("watermarks") or []:
            _draw_evaluation_watermark(canvas, width, height, text=mark)

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, title=TEMPLATES[view["reportType"]][1]).build(
        story, onFirstPage=stamp, onLaterPages=stamp)
    return buf.getvalue()
