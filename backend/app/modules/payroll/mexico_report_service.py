"""
mexico_report_service.py
------------------------
Mexico dedicated report generators (completion programme W4-2 = Phase 12b,
plan D2). The reports whose subject is one of Mexico's own tables — CFDI
lifecycle, authority liabilities, IMSS movements, SUA periods, ISN returns,
vacation ledgers, PTU cycles, the annual-adjustment employer year — are built
here from those services' own views (never recomputed), and persisted as
immutable GeneratedReport rows with supersession, as Hong Kong's are.

The generic payslip-column generator refuses these report types
(service.MX_DEDICATED_GENERATOR_REPORT_TYPES): a plain wage list under a
statutory title is not the report.

Every report whose official layout's source is not saved says so on its face
("not an official file"). No report carries a full RFC, CURP or NSS (MX-061):
the views used expose names, employee ids and masked identifiers only.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

MX = "MX"
NOT_OFFICIAL = ("NOT AN OFFICIAL FILE — the official layout's source is not saved (gap register C8 / C9 / B10); "
                "this is a register of Zoiko's own records.")
# report type -> (needs, official-layout note or None)
MX_REPORT_SPECS = {
    "MX_CFDI_STATUS": ((), None),
    "MX_ISR_WITHHOLDING": (("period_key",), "SAT declaration: no file layout in scope. " + NOT_OFFICIAL),
    "MX_IDSE": ((), "NOT AN IDSE FILE. " + NOT_OFFICIAL),
    "MX_SUA": (("period_key",), "NOT A SUA FILE. " + NOT_OFFICIAL),
    "MX_SIPARE": (("period_key",), "NOT A SIPARE FILE. " + NOT_OFFICIAL),
    "MX_VACATION": ((), None),
    "MX_PTU": (("cycle_id",), None),
    "MX_ISN_RETURN": (("period_key",), "NOT THE STATE RETURN FORM. " + NOT_OFFICIAL),
}
# The annual-adjustment employer-year view (plan §3 T + D): the MX_ANNUAL_ISR template is also a
# template-engine report (the per-run section), so it is generated here only through mx_report_generate.
MX_ANNUAL_EMPLOYER_YEAR = "MX_ANNUAL_ISR"


def _mx_report_models():
    from app.modules.payroll import models

    return models


def _mx_report_template(db: Session, template_id: int, report_type_ok) -> "object":
    """The Mexico template, of a dedicated type, Active (the shared rule)."""
    from app.modules.payroll import service

    types = tuple(report_type_ok)
    return service.require_active_report_template(
        db, template_id, country=MX, report_types=types,
        wrong_country_message=lambda t: f"Template {t.template_key} is a {t.jurisdiction_country!r} template — Mexico "
                                        f"reports are generated only against an 'MX' template.",
        wrong_type_message=lambda t: f"This template is a {t.report_type!r} template, not one of {', '.join(types)}.")


def _mx_report_write(db: Session, organization_id: int, template, scope_key: str, rendered_data: dict,
                     reporting_year: str, reporting_period: Optional[str], actor_id: Optional[int]):
    """One live report per logical scope: a previous Generated row is flipped
    to Superseded, never edited (the Hong Kong rule, HK-011)."""
    from app.modules.payroll import service

    GeneratedReport = _mx_report_models().GeneratedReport
    previous = service.supersede_live_reports(
        db, organization_id, template.report_type, scope_key=scope_key, jurisdiction_country=MX,
        reporting_year=reporting_year, reporting_period=reporting_period)
    if previous:
        db.flush()
        rendered_data = {**rendered_data, "supersedesReportIds": previous}
    row = GeneratedReport(
        organization_id=organization_id, report_template_id=template.id, template_version=template.version,
        report_type=template.report_type, payroll_run_id=None, employee_id=None, scope_key=scope_key,
        jurisdiction_country=MX, jurisdiction_state=template.jurisdiction_state,
        reporting_year=reporting_year, reporting_period=reporting_period,
        status="Generated", generated_by_id=actor_id, rendered_data=rendered_data, reconciliation=None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mx_report_period(params: dict) -> str:
    period = str((params or {}).get("period_key") or "").strip()
    if not period or len(period) != 7 or period[4] != "-":
        raise BadRequestException("period_key must be YYYY-MM (the first month of a bimester for SUA / SIPARE)")
    return period


def _mx_report_employees(db: Session, org_id: int) -> list:
    m = _mx_report_models()
    return (db.query(m.PayrollEmployee)
            .filter(m.PayrollEmployee.organization_id == org_id, m.PayrollEmployee.country_code == MX)
            .order_by(m.PayrollEmployee.id).all())


def _mx_report_body(db: Session, org_id: int, template, params: dict) -> tuple:
    """(scope_key, reporting_year, reporting_period, data) from the service views."""
    from app.modules.payroll import (mexico_benefits_service, mexico_cfdi_service, mexico_filing_service,
                                     mexico_imss_service, mexico_ptu_service)

    rtype = template.report_type
    if rtype == "MX_CFDI_STATUS":
        as_of = date.today().isoformat()
        return "ORG", as_of[:4], as_of, {"lifecycle": mexico_cfdi_service.lifecycle_overview(db, org_id)}
    if rtype in ("MX_ISR_WITHHOLDING", "MX_SIPARE"):
        period = _mx_report_period(params)
        authorities = ("SAT_ISR",) if rtype == "MX_ISR_WITHHOLDING" else ("IMSS", "IMSS_RCV", "INFONAVIT")
        rows = [mexico_filing_service.liability_view(db, mexico_filing_service._liability(db, org_id, r["id"]),
                                                     with_sources=True)
                for r in mexico_filing_service.list_liabilities(db, org_id, period) if r["authority"] in authorities]
        return f"PERIOD:{period}", period[:4], period, {"liabilities": rows}
    if rtype == "MX_IDSE":
        rows = mexico_imss_service.list_movements(db, org_id)
        period = str((params or {}).get("period_key") or "").strip()
        if period:
            rows = [r for r in rows if str(r.get("eventDate") or "").startswith(period)]
        return f"MOVEMENTS:{period or 'ALL'}", (period or date.today().isoformat())[:4], period or "ALL", \
            {"movements": rows}
    if rtype == "MX_SUA":
        period = _mx_report_period(params)
        m = _mx_report_models()
        P = m.PayrollMxSuaPeriod
        periods = (db.query(P).filter(P.organization_id == org_id, P.period_key == period).order_by(P.id).all())
        return f"PERIOD:{period}", period[:4], period, \
            {"suaPeriods": [mexico_filing_service.sua_view(db, p, detail=True) for p in periods]}
    if rtype == "MX_ISN_RETURN":
        period = _mx_report_period(params)
        rows = [r for r in mexico_filing_service.list_isn_returns(db, org_id)
                if r["periodKey"] == period and r["stateCode"] == template.jurisdiction_state]
        return f"PERIOD:{template.jurisdiction_state}:{period}", period[:4], period, {"returns": rows}
    if rtype == "MX_VACATION":
        as_of = date.today().isoformat()
        ledgers = []
        for emp in _mx_report_employees(db, org_id):
            ledger = mexico_benefits_service.ledger(db, org_id, emp.id)
            ledgers.append({"employeeId": emp.id, "employeeName": emp.name, "ledger": ledger})
        return "ORG", as_of[:4], as_of, {"employees": ledgers}
    if rtype == "MX_PTU":
        try:
            cycle_id = int((params or {}).get("cycle_id"))
        except (TypeError, ValueError):
            raise BadRequestException("cycle_id is required for the PTU distribution report")
        cycle = mexico_ptu_service.get_cycle(db, org_id, cycle_id)
        year = str(cycle.get("fiscalYear") or "")
        return f"CYCLE:{cycle_id}", year, year, {"cycle": cycle}
    raise BadRequestException(f"{rtype} has no dedicated Mexico generator")


def mx_report_generate(db: Session, org_id: int, template_id: int, params: Optional[dict],
                       actor_id: Optional[int]) -> dict:
    """Generate one dedicated Mexico report (or the annual-adjustment
    employer-year view) from an Active MX template. Refused for an organisation
    the filing guard refuses (dormant, a pilot never files)."""
    from app.modules.payroll import mexico_annual_service, mexico_filing_service

    mexico_filing_service.guard(db, org_id)
    params = params or {}
    template = _mx_report_template(db, template_id, tuple(MX_REPORT_SPECS) + (MX_ANNUAL_EMPLOYER_YEAR,))
    if template.report_type == MX_ANNUAL_EMPLOYER_YEAR:
        try:
            employer_id, year = int(params.get("employer_profile_id")), int(params.get("fiscal_year"))
        except (TypeError, ValueError):
            raise BadRequestException("employer_profile_id and fiscal_year are required for the annual adjustment view")
        scope, ryear, rperiod = f"EMPLOYER:{employer_id}:{year}", str(year), "ANNUAL"
        data, note = {"employerYear": mexico_annual_service.employer_year_view(db, org_id, employer_id, year)}, None
    else:
        needs, note = MX_REPORT_SPECS[template.report_type]
        missing = [n for n in needs if params.get(n) in (None, "")]
        if missing:
            raise BadRequestException(f"{template.template_key} needs {', '.join(missing)}")
        scope, ryear, rperiod, data = _mx_report_body(db, org_id, template, params)
    rendered = {"templateSnapshot": {"templateKey": template.template_key, "version": template.version,
                                     "reportType": template.report_type},
                "generatedAt": datetime.now(timezone.utc).isoformat(), "officialLayout": note, "data": data}
    row = _mx_report_write(db, org_id, template, scope, rendered, ryear, rperiod, actor_id)
    return {"reportId": row.id, "templateKey": template.template_key, "reportType": row.report_type,
            "scopeKey": row.scope_key, "reportingYear": row.reporting_year, "reportingPeriod": row.reporting_period,
            "status": row.status, "officialLayout": note, "renderedData": row.rendered_data}


# ═══ W4-3a (Phase 12c, plan E6 / D3): the Mexico template activation gate ═══
# Replaces the permanent refusal. A Mexico template becomes Active only when
# (1) every release gate its report rests on is SIGNED (reviewed evidence,
# mexico_service.gate_states), (2) the statutory content it reports is Active
# (the national pack of its year; the state's ISN pack for an ISN return), and
# (3) for a template-engine report, every field is a catalogued Mexico path that
# resolves on a real committed Mexican payslip of its run type. Today nothing
# passes (no gate is signed, no pack Active) — by design.
MX_REPORT_GATES = {
    "MX_REGISTER": ("G1", "G2", "G3"), "MX_EMPLOYER_COST": ("G2", "G3", "G4"), "MX_JOURNAL": ("G8",),
    "MX_SUBSIDY": ("G1",), "MX_IMSS": ("G2",), "MX_INFONAVIT": ("G3",), "MX_AGUINALDO": ("G1", "G5"),
    "MX_FINIQUITO": ("G1", "G5"), "MX_ANNUAL_ISR": ("G1",), "MX_CFDI_RECEIPT": ("G1",), "MX_CFDI_STATUS": ("G1", "G6"),
    "MX_ISR_WITHHOLDING": ("G1",), "MX_IDSE": ("G2",), "MX_SUA": ("G2",), "MX_SIPARE": ("G2", "G3"),
    "MX_VACATION": ("G5",), "MX_PTU": ("G5",), "MX_ISN_RETURN": ("G4",),
}
# The run type whose committed payslips prove a template-engine report's fields.
MX_REPORT_RUN_TYPES = {"MX_AGUINALDO": ("AGUINALDO",), "MX_FINIQUITO": ("FINIQUITO",),
                       "MX_ANNUAL_ISR": ("ORDINARY",)}


def _mx_report_fields(db: Session, template) -> list:
    m = _mx_report_models()
    out = []
    for comp in db.query(m.ReportTemplateComponent).filter(m.ReportTemplateComponent.report_template_id == template.id):
        out += db.query(m.ReportTemplateComponentField).filter(m.ReportTemplateComponentField.component_id == comp.id).all()
    return out


def _mx_report_fields_proven(db: Session, template) -> Optional[str]:
    """None when every snapshot field resolves on a committed Mexican payslip of
    the report's run type; else why not (a keyed path needs only its list)."""
    from app.modules.payroll import service

    fields = [f for f in _mx_report_fields(db, template) if f.data_source_kind == "PAYSLIP_ITEM_JSON"]
    if not fields:
        return None
    catalog = service._PAYSLIP_ITEM_JSON_FIELD_CATALOG.get(MX, {})
    stray = [f.source_column for f in fields if f.source_column not in catalog]
    if stray:
        return f"fields outside the Mexico snapshot catalog: {', '.join(stray[:3])}"
    m = _mx_report_models()
    run_types = MX_REPORT_RUN_TYPES.get(template.report_type, ("ORDINARY", "CORRECTION"))
    rows = (db.query(m.PayslipItem, m.PayrollRun).join(m.PayrollRun, m.PayslipItem.payroll_run_id == m.PayrollRun.id)
            .filter(m.PayslipItem.mx_calculation_snapshot.isnot(None)).order_by(m.PayslipItem.id.desc()).limit(500))
    needs_annual = template.report_type == "MX_ANNUAL_ISR"
    for item, run in rows:
        if (run.mx_run_type or "ORDINARY") not in run_types or not (run.mx_approval_fingerprint or {}).get("committedAt"):
            continue
        snap = {"mx_calculation_snapshot": item.mx_calculation_snapshot}
        if needs_annual and not ((snap["mx_calculation_snapshot"].get("result") or {}).get("annual_adjustment")):
            continue
        missing = []
        for f in fields:
            segments = [s for s in f.source_column.split(".") if s]
            if "[" in f.source_column:
                cut = next(i for i, s in enumerate(segments) if "[" in s)
                parent = service._report_json_walk(snap, segments[:cut])
                if not (parent and isinstance(parent[0], dict)
                        and isinstance(parent[0].get(segments[cut].split("[")[0]), list)):
                    missing.append(f.source_column)
            elif not service._report_json_walk(snap, segments):
                missing.append(f.source_column)
        if not missing:
            return None
    return (f"no committed Mexican {'/'.join(run_types).lower()} payslip resolves every field yet — a field is proven "
            f"on a real committed payslip before the template goes live")


def mx_report_activation_refusal(db: Session, template) -> Optional[str]:
    from app.modules.payroll import mexico_service

    reasons = []
    gates = MX_REPORT_GATES.get(getattr(template, "report_type", None))
    if gates is None:
        return (f"Mexico report-template activation is refused: {getattr(template, 'report_type', None)!r} is not a "
                f"Mexico report type this release can activate.")
    states = {g["gate"]: g["state"] for g in mexico_service.gate_states(db)}
    unsigned = [g for g in gates if states.get(g) != "SIGNED"]
    if unsigned:
        reasons.append(f"release gate(s) {', '.join(unsigned)} not SIGNED")
    m = _mx_report_models()
    year = str(template.reporting_year)
    pack_ids = [f"MX-PAYROLL-{year}"]
    if template.report_type == "MX_ISN_RETURN" and template.jurisdiction_state:
        pack_ids.append(f"MX-ISN-{template.jurisdiction_state}-{year}")
    for pack_id in pack_ids:
        active = (db.query(m.JurisdictionPack).filter(m.JurisdictionPack.pack_id == pack_id,
                                                      m.JurisdictionPack.status == "Active").first())
        if active is None:
            reasons.append(f"pack {pack_id} is not Active")
    if template.report_type not in MX_REPORT_SPECS and template.report_type != "MX_CFDI_RECEIPT":
        if not _mx_report_fields(db, template):
            reasons.append("the template has no fields")
        else:
            proof = _mx_report_fields_proven(db, template)
            if proof:
                reasons.append(proof)
    if reasons:
        return "Mexico report-template activation is refused: " + "; ".join(reasons) + "."
    return None
