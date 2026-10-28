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
    # Final mile X3 (spec §7, §10, §13, §14, §20): reports of the run workspace and the compliance centre.
    "MX_RUN_VARIANCE": (("run_id",), None),
    "MX_PREFLIGHT": (("run_id",), None),
    "MX_SBC_MOVEMENTS": ((), None),
    "MX_WORK_RISK": ((), "NOT THE IMSS ANNUAL WORK-RISK DETERMINATION. " + NOT_OFFICIAL),
    "MX_INFONAVIT_NOTICES": ((), None),
    "MX_LABOR_COMPLIANCE": (("run_id",), None),
    "MX_PAYMENT_WORKLIST": (("run_id",), "NOT A BANK FILE (gap register C7): a settlement worklist; each account is "
                                         "shown by its last four digits only."),
    "MX_ID_ACCESS_AUDIT": ((), None),
    # Final mile X4 (spec §22 G8, MX-064): one parallel cycle's differences.
    "MX_PARALLEL_DIFF": (("import_id",), None),
}
# Final mile X3: who holds the D-24 high-value threshold the variance report flags against.
VARIANCE_THRESHOLD_DECISION = "D-24"
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


def _mx_report_run(db: Session, org_id: int, params: dict):
    """The organisation's payroll run named by run_id (never another tenant's)."""
    from app.core.exceptions import NotFoundException

    try:
        run_id = int((params or {}).get("run_id"))
    except (TypeError, ValueError):
        raise BadRequestException("run_id is required")
    run = db.get(_mx_report_models().PayrollRun, run_id)
    if run is None or run.organization_id != org_id:
        raise NotFoundException("payroll run", run_id)
    return run


def _committed(run) -> bool:
    return bool((run.mx_approval_fingerprint or {}).get("committedAt"))


def _employee_refs(db: Session, ids) -> dict:
    """{employee id: reference} — the employee code, never an identifier (MX-061)."""
    m = _mx_report_models()
    rows = db.query(m.PayrollEmployee).filter(m.PayrollEmployee.id.in_(list(ids) or [0])).all()
    return {e.id: e.employee_code or f"#{e.id}" for e in rows}


def _approved_value(db: Session, code: str):
    """The latest APPROVED / TRANSCRIBED answer of a decision, or None (X1)."""
    m = _mx_report_models()
    D = m.PayrollMxDecision
    row = (db.query(D).filter(D.code == code, D.status.in_(("APPROVED", "TRANSCRIBED")))
           .order_by(D.version.desc()).first())
    return row


_VARIANCE_LINES = ("gross", "net", "isr_withheld", "imss_employee", "imss_employer", "infonavit_employer",
                   "infonavit_credit", "isn", "employer_total")


def _variance_values(item) -> dict:
    from decimal import Decimal

    res = ((item.mx_calculation_snapshot or {}).get("result") or {})

    def d(v):
        return Decimal(str(v)) if v not in (None, "") else Decimal("0")

    return {"gross": d(res.get("gross")), "net": d(item.net_pay), "isr_withheld": d(res.get("isr_withheld")),
            "imss_employee": d(res.get("imss_employee")), "imss_employer": d(res.get("imss_employer")),
            "infonavit_employer": d(res.get("infonavit_employer")), "infonavit_credit": d(res.get("infonavit_credit")),
            "isn": d((res.get("isn") or {}).get("amount")), "employer_total": d(res.get("employer_total"))}


def _run_variance(db: Session, org_id: int, run) -> dict:
    """Spec §13 stage 4: each employee's net, employer cost and statutory lines
    against the prior committed Mexican run. High-value deltas are flagged only
    against the release owner's approved D-24 threshold — never a default."""
    from decimal import Decimal, InvalidOperation

    m = _mx_report_models()
    if not _committed(run):
        raise BadRequestException(f"run {run.id} is not committed — variance compares committed results only")
    prior = None
    for r in (db.query(m.PayrollRun).filter(m.PayrollRun.organization_id == org_id, m.PayrollRun.id != run.id,
                                            m.PayrollRun.pay_date <= run.pay_date)
              .order_by(m.PayrollRun.pay_date.desc(), m.PayrollRun.id.desc())):
        if _committed(r) and (r.pay_date < run.pay_date or r.id < run.id):
            prior = r
            break

    def items(r):
        if r is None:
            return {}
        return {i.employee_id: i for i in db.query(m.PayslipItem).filter(m.PayslipItem.payroll_run_id == r.id,
                                                                         m.PayslipItem.mx_calculation_snapshot.isnot(None))}

    cur, old = items(run), items(prior)
    decision = _approved_value(db, VARIANCE_THRESHOLD_DECISION)
    threshold = None
    if decision is not None:
        try:
            threshold = Decimal(str(decision.chosen_option))
        except (InvalidOperation, ValueError):
            threshold = None
    refs = _employee_refs(db, set(cur) | set(old))
    rows = []
    for emp in sorted(set(cur) | set(old)):
        a = _variance_values(cur[emp]) if emp in cur else None
        b = _variance_values(old[emp]) if emp in old else None
        lines = {k: {"current": str(a[k]) if a else None, "prior": str(b[k]) if b else None,
                     "delta": str(a[k] - b[k]) if a and b else None} for k in _VARIANCE_LINES}
        flag = None
        if threshold is not None and a and b:
            flag = any(abs(a[k] - b[k]) >= threshold for k in ("net", "employer_total"))
        rows.append({"employee": refs.get(emp, f"#{emp}"), "employeeId": emp,
                     "status": "NEW" if b is None else ("LEFT" if a is None else "BOTH"), "lines": lines,
                     "highValue": flag})
    return {"runId": run.id, "priorRunId": prior.id if prior else None, "employees": rows,
            "threshold": {"decision": VARIANCE_THRESHOLD_DECISION, "value": str(threshold) if threshold is not None
                          else None,
                          "note": None if threshold is not None else "the release owner's high-value threshold (D-24) "
                          "is not approved: deltas are shown, none is flagged"}}


def _labor_compliance(db: Session, run) -> dict:
    """Spec §13 stage 3: per committed payslip, the labour checks the engine
    recorded (minimum wage, overtime tiers, Sunday premium) and the benefit
    accruals below the statutory amount. Exceptions are listed, never fixed."""
    from decimal import Decimal

    m = _mx_report_models()
    rows = db.query(m.PayslipItem).filter(m.PayslipItem.payroll_run_id == run.id,
                                          m.PayslipItem.mx_calculation_snapshot.isnot(None)).all()
    refs = _employee_refs(db, {r.employee_id for r in rows})
    accruals = db.query(m.PayrollMxBenefitAccrual).filter(m.PayrollMxBenefitAccrual.payroll_run_id == run.id).all()
    out = []
    for item in rows:
        res = (item.mx_calculation_snapshot or {}).get("result") or {}
        labor = res.get("labor") or {}
        flags = []
        if Decimal(str(item.net_pay or 0)) < 0:
            flags.append("NEGATIVE_NET")
        for w in labor.get("overtime") or []:
            if Decimal(str(w.get("second_tier_hours") or 0)) > 0:
                flags.append(f"TRIPLE_RATE_OVERTIME_WEEK_{w.get('week')}")
        below = [a for a in accruals if a.employee_id == item.employee_id and a.employer_amount < a.statutory_amount]
        flags += [f"{a.concept}_BELOW_STATUTORY" for a in below]
        out.append({"employee": refs.get(item.employee_id, f"#{item.employee_id}"), "employeeId": item.employee_id,
                    "minimumWage": labor.get("minimum_wage"), "workweek": labor.get("workweek"),
                    "overtime": labor.get("overtime") or [], "sunday": labor.get("sunday"),
                    "accruals": [{"concept": a.concept, "period": a.period_key, "statutory": str(a.statutory_amount),
                                  "employer": str(a.employer_amount)} for a in accruals
                                 if a.employee_id == item.employee_id],
                    "exceptions": flags})
    return {"runId": run.id, "employees": out, "withExceptions": sum(1 for e in out if e["exceptions"])}


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
    if rtype == "MX_RUN_VARIANCE":
        run = _mx_report_run(db, org_id, params)
        return f"RUN:{run.id}", str(run.pay_date.year), run.pay_date.isoformat(), _run_variance(db, org_id, run)
    if rtype == "MX_PREFLIGHT":
        from app.modules.payroll import mexico_run_service

        run = _mx_report_run(db, org_id, params)
        view = mexico_run_service.run_preflight(db, run)
        refs = _employee_refs(db, {e.get("employeeId") for e in view["exceptions"] if e.get("employeeId")})
        view["exceptions"] = [{**e, "employee": refs.get(e.get("employeeId"))} for e in view["exceptions"]]
        return f"RUN:{run.id}", str(run.pay_date.year), run.pay_date.isoformat(), {"preflight": view}
    if rtype == "MX_SBC_MOVEMENTS":
        from app.modules.payroll import mexico_imss_service

        m = _mx_report_models()
        hist = (db.query(m.PayrollMxSbcHistory).filter(m.PayrollMxSbcHistory.organization_id == org_id)
                .order_by(m.PayrollMxSbcHistory.employee_id, m.PayrollMxSbcHistory.effective_from).all())
        acc = (db.query(m.PayrollMxVariableAccumulator).filter(m.PayrollMxVariableAccumulator.organization_id == org_id)
               .order_by(m.PayrollMxVariableAccumulator.employee_id, m.PayrollMxVariableAccumulator.bimester_key).all())
        refs = _employee_refs(db, {h.employee_id for h in hist} | {a.employee_id for a in acc})
        as_of = date.today().isoformat()
        return "ORG", as_of[:4], as_of, {
            "sbc": [{"employee": refs.get(h.employee_id), "runId": h.payroll_run_id,
                     "effectiveFrom": h.effective_from.isoformat(), "fixed": str(h.sbc_fixed),
                     "variable": str(h.sbc_variable), "total": str(h.sbc_total), "factor": str(h.factor),
                     "source": h.source, "components": h.components} for h in hist],
            "bimesterAccumulators": [{"employee": refs.get(a.employee_id), "bimester": a.bimester_key,
                                      "variableTotal": str(a.variable_total), "days": str(a.days), "kind": a.kind}
                                     for a in acc],
            "movements": mexico_imss_service.list_movements(db, org_id)}
    if rtype == "MX_WORK_RISK":
        from app.modules.payroll import mexico_employer_service

        regs = []
        for emp in mexico_employer_service.list_employers(db, org_id, masked=True):
            for reg in mexico_employer_service.list_registrations(db, org_id, emp["employerId"], masked=True):
                premiums = reg.pop("riskPremiums", [])
                regs.append({"employer": emp["legalName"], "registration": reg, "premiums": premiums})
        as_of = date.today().isoformat()
        return "ORG", as_of[:4], as_of, {
            "registrations": regs,
            "reviewYearCases": None,
            "note": "Work-risk cases of the review year are not recorded in Zoiko: the IMSS annual determination's "
                    "inputs and form are not a saved source. Premium history only."}
    if rtype == "MX_INFONAVIT_NOTICES":
        from app.modules.payroll import mexico_employee_service

        out = []
        for emp in _mx_report_employees(db, org_id):
            for n in mexico_employee_service.list_infonavit_notices(db, org_id, emp.id):
                masked = {k: v for k, v in n.items() if "credit" not in k.lower() or "number" not in k.lower()}
                number = str(n.get("creditNumber") or n.get("credit_number") or "")
                out.append({**masked, "employee": emp.employee_code or f"#{emp.id}",
                            "creditNumber": f"****{number[-4:]}" if number else None})
        as_of = date.today().isoformat()
        return "ORG", as_of[:4], as_of, {"notices": out,
                                         "rule": "No notice, no credit withholding (spec §10, MX-031)."}
    if rtype == "MX_LABOR_COMPLIANCE":
        run = _mx_report_run(db, org_id, params)
        return f"RUN:{run.id}", str(run.pay_date.year), run.pay_date.isoformat(), _labor_compliance(db, run)
    if rtype == "MX_PAYMENT_WORKLIST":
        m = _mx_report_models()
        run = _mx_report_run(db, org_id, params)
        batches = db.query(m.PayrollMxPaymentBatch).filter(m.PayrollMxPaymentBatch.payroll_run_id == run.id).all()
        items = (db.query(m.PayrollMxPaymentItem)
                 .filter(m.PayrollMxPaymentItem.batch_id.in_([b.id for b in batches] or [0])).all())
        refs = _employee_refs(db, {i.employee_id for i in items})
        return f"RUN:{run.id}", str(run.pay_date.year), run.pay_date.isoformat(), {
            "batches": [{"batchId": b.id, "status": b.status, "fileMode": b.file_mode, "items": b.item_count,
                         "reissueOf": b.reissue_of_batch_id} for b in batches],
            "items": [{"batchId": i.batch_id, "employee": refs.get(i.employee_id), "account": f"****{i.clabe_last4}",
                       "amount": str(i.amount), "status": i.status} for i in items]}
    if rtype == "MX_ID_ACCESS_AUDIT":
        m = _mx_report_models()
        period = str((params or {}).get("period_key") or "").strip()
        q = (db.query(m.PayrollMxCfdiEvent, m.PayrollMxCfdiDocument)
             .join(m.PayrollMxCfdiDocument, m.PayrollMxCfdiEvent.document_id == m.PayrollMxCfdiDocument.id)
             .filter(m.PayrollMxCfdiDocument.organization_id == org_id,
                     m.PayrollMxCfdiEvent.event_type == "RECEIPT_RENDERED")
             .order_by(m.PayrollMxCfdiEvent.occurred_at))
        rows = [(e, d) for e, d in q.all() if not period or (e.occurred_at and e.occurred_at.isoformat()[:7] == period)]
        refs = _employee_refs(db, {d.employee_id for _, d in rows})
        as_of = date.today().isoformat()
        return f"AUDIT:{period or 'ALL'}", (period or as_of)[:4], period or "ALL", {
            "renders": [{"at": e.occurred_at.isoformat() if e.occurred_at else None, "actorId": e.actor_id,
                         "documentId": d.id, "runId": d.payroll_run_id, "employee": refs.get(d.employee_id)}
                        for e, d in rows],
            "note": "Each render of the printed CFDI receipt — the one view that shows RFC / CURP / NSS (MX-061) — is "
                    "recorded here by who and when; no identifier appears in this report."}
    if rtype == "MX_PARALLEL_DIFF":
        from app.modules.payroll import mexico_parallel_service

        try:
            import_id = int(params.get("import_id"))
        except (TypeError, ValueError):
            raise BadRequestException("import_id is required")
        view = mexico_parallel_service.parallel_import_view(db, org_id, import_id)
        run = db.get(_mx_report_models().PayrollRun, view["runId"])
        return f"PARALLEL:{import_id}", str(run.pay_date.year), run.pay_date.isoformat(), view
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
    "MX_RUN_VARIANCE": ("G1", "G8"), "MX_PREFLIGHT": ("G1",), "MX_SBC_MOVEMENTS": ("G2",), "MX_WORK_RISK": ("G2",),
    "MX_INFONAVIT_NOTICES": ("G3",), "MX_LABOR_COMPLIANCE": ("G5",), "MX_PAYMENT_WORKLIST": ("G6",),
    "MX_ID_ACCESS_AUDIT": ("G7",), "MX_PARALLEL_DIFF": ("G8",),
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


def _mx_activation_platform_reasons(db: Session, template) -> Optional[list]:
    """The activation conditions that read no tenant data: the report's gates
    SIGNED, its content pack Active, and (template-engine reports) fields present.
    None = the report type cannot be activated at all."""
    from app.modules.payroll import mexico_service

    reasons = []
    gates = MX_REPORT_GATES.get(getattr(template, "report_type", None))
    if gates is None:
        return None
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
    return reasons


def mx_report_activation_refusal(db: Session, template) -> Optional[str]:
    reasons = _mx_activation_platform_reasons(db, template)
    if reasons is None:
        return (f"Mexico report-template activation is refused: {getattr(template, 'report_type', None)!r} is not a "
                f"Mexico report type this release can activate.")
    if (template.report_type not in MX_REPORT_SPECS and template.report_type != "MX_CFDI_RECEIPT"
            and _mx_report_fields(db, template)):
        proof = _mx_report_fields_proven(db, template)        # reads committed payslips (tenant data)
        if proof:
            reasons.append(proof)
    if reasons:
        return "Mexico report-template activation is refused: " + "; ".join(reasons) + "."
    return None


# ═══ Final mile X3b: the Mexico template library tools ═══════════════════════

def _kind(template) -> str:
    if template.report_type == "MX_CFDI_RECEIPT":
        return "RECEIPT"
    return "DEDICATED" if template.report_type in MX_REPORT_SPECS else "TEMPLATE_ENGINE"


def _mx_templates(db: Session) -> list:
    m = _mx_report_models()
    return (db.query(m.ReportTemplate).filter(m.ReportTemplate.jurisdiction_country == MX)
            .order_by(m.ReportTemplate.template_key, m.ReportTemplate.version).all())


def _catalog_check(db: Session, template) -> str:
    """Every PAYSLIP_ITEM_JSON field is a catalogued Mexico snapshot path — the
    platform-level half of the field proof. The other half (each path resolves
    on a real committed payslip) reads tenant payslips, so it runs only inside
    the activation gate, never on this platform view."""
    from app.modules.payroll import service

    fields = [f for f in _mx_report_fields(db, template) if f.data_source_kind == "PAYSLIP_ITEM_JSON"]
    catalog = service._PAYSLIP_ITEM_JSON_FIELD_CATALOG.get(MX, {})
    stray = [f.source_column for f in fields if f.source_column not in catalog]
    if stray:
        return f"outside the Mexico snapshot catalog: {', '.join(stray[:3])}"
    return f"all {len(fields)} snapshot path(s) catalogued; proven on a committed payslip at activation"


def mx_template_coverage(db: Session) -> list:
    """Per Mexico template: how it is built and its catalogue check. Read-only,
    and it reads no organisation's data (the activation answer per template is
    given by the template lifecycle itself)."""
    out = []
    for t in _mx_templates(db):
        kind = _kind(t)
        fields = _mx_report_fields(db, t)
        out.append({"id": t.id, "templateKey": t.template_key, "version": t.version, "reportType": t.report_type,
                    "state": t.jurisdiction_state, "status": t.status, "kind": kind, "fields": len(fields),
                    "gates": list(MX_REPORT_GATES.get(t.report_type, ())),
                    "fieldProof": ("not applicable — built from service views" if kind != "TEMPLATE_ENGINE"
                                   else "no fields" if not fields else _catalog_check(db, t))})
    return out


SANDBOX_PREVIEW_MARK = "SANDBOX PREVIEW — SYNTHETIC — NOT A REPORT"


def mx_template_sandbox_preview(db: Session, template_id: int, sandbox_input: dict) -> dict:
    """A template-engine template's fields resolved against one sandbox result
    (X2): watermarked, never stored, and only for a CALCULATED sandbox run."""
    from app.core.exceptions import NotFoundException
    from app.modules.payroll import mexico_sandbox_service, service

    t = db.get(_mx_report_models().ReportTemplate, template_id)
    if t is None or t.jurisdiction_country != MX:
        raise NotFoundException("Mexico report template", template_id)
    if _kind(t) != "TEMPLATE_ENGINE":
        raise BadRequestException(f"{t.template_key} is built from Mexico's service views, not from payslip fields — "
                                  "it has no payslip preview")
    run = mexico_sandbox_service.run_mx_sandbox(db, sandbox_input or {})
    marks = list(run["watermarks"]) + [SANDBOX_PREVIEW_MARK]
    if run["outcome"] != "CALCULATED":
        return {"templateKey": t.template_key, "outcome": "BLOCKED", "block": run["block"],
                "clearedBy": run.get("clearedBy", []), "watermarks": marks}
    snap = {"mx_calculation_snapshot": {"result": run["result"]["mx_result"]}}
    rows = []
    m = _mx_report_models()
    for comp in (db.query(m.ReportTemplateComponent).filter(m.ReportTemplateComponent.report_template_id == t.id)
                 .order_by(m.ReportTemplateComponent.id)):
        for f in (db.query(m.ReportTemplateComponentField).filter(m.ReportTemplateComponentField.component_id == comp.id)
                  .order_by(m.ReportTemplateComponentField.id)):
            value = None
            if f.data_source_kind == "PAYSLIP_ITEM_JSON" and f.source_column:
                value = service._report_json_path_value(snap, [x for x in f.source_column.split(".") if x])
            rows.append({"component": comp.component_key, "field": f.field_key, "label": f.label,
                         "source": f.source_column, "sourceKind": f.data_source_kind,
                         "value": None if value is None else str(value),
                         "resolved": value is not None or f.data_source_kind != "PAYSLIP_ITEM_JSON"})
    return {"templateKey": t.template_key, "outcome": "CALCULATED", "fields": rows, "watermarks": marks,
            "candidates": run.get("candidates", []), "pack": run.get("pack")}


def mx_compare_templates(db: Session, from_id: int, to_id: int) -> dict:
    """Read-only diff of two Mexico templates' fields and metadata (any status)."""
    from app.core.exceptions import NotFoundException
    from app.modules.payroll.hong_kong_service import template_content_hash

    m = _mx_report_models()
    a, b = db.get(m.ReportTemplate, from_id), db.get(m.ReportTemplate, to_id)
    for tid, t in ((from_id, a), (to_id, b)):
        if t is None or t.jurisdiction_country != MX:
            raise NotFoundException("Mexico report template", tid)

    def fields(t):
        out = {}
        for c in db.query(m.ReportTemplateComponent).filter(m.ReportTemplateComponent.report_template_id == t.id):
            for f in db.query(m.ReportTemplateComponentField).filter(m.ReportTemplateComponentField.component_id == c.id):
                out[f"{c.component_key}.{f.field_key}"] = {
                    "label": f.label, "type": f.field_type, "sourceKind": f.data_source_kind,
                    "sourceColumn": f.source_column, "aggregation": f.aggregation, "required": bool(f.is_required)}
        return out

    fa, fb = fields(a), fields(b)
    changed = [{"field": k, "changes": {x: {"from": fa[k][x], "to": fb[k][x]} for x in fa[k] if fa[k][x] != fb[k][x]}}
               for k in sorted(set(fa) & set(fb)) if fa[k] != fb[k]]
    meta = {x: {"from": str(getattr(a, x)), "to": str(getattr(b, x))}
            for x in ("template_key", "report_type", "reporting_year", "version", "status", "description")
            if getattr(a, x) != getattr(b, x)}
    return {"from": {"id": a.id, "key": a.template_key, "version": a.version, "status": a.status,
                     "contentHash": template_content_hash(db, a)},
            "to": {"id": b.id, "key": b.template_key, "version": b.version, "status": b.status,
                   "contentHash": template_content_hash(db, b)},
            "added": sorted(set(fb) - set(fa)), "removed": sorted(set(fa) - set(fb)), "changed": changed,
            "metadata": meta, "identical": not (set(fa) ^ set(fb)) and not changed and not meta}


# ═══ Template versions (configuration-versions parity, 2026-10-28) ════════════
# Every version of every Mexico report template, with what the activation gate
# answers for it, and "new version" — a Draft copy of the CHOSEN version (the
# rollback path). The shared upsert_report_template pre-populates a new version
# from the template's LATEST version, so a rollback to an older version needs
# this copy. Activation stays the shared lifecycle behind mx_report_activation_refusal.
_TEMPLATE_COPY_SKIP = {"id", "version", "status", "approved_by_id", "created_by_id", "updated_by_id", "created_at",
                       "updated_at", "previous_version_id", "change_summary"}


def mx_template_versions(db: Session) -> list:
    from app.modules.payroll.hong_kong_service import template_content_hash

    groups = {}
    for t in _mx_templates(db):
        groups.setdefault(t.template_key, {"templateKey": t.template_key, "name": t.name, "reportType": t.report_type,
                                           "state": t.jurisdiction_state, "kind": _kind(t), "versions": []})
        groups[t.template_key]["versions"].append({
            "id": t.id, "version": t.version, "status": t.status, "reportingYear": t.reporting_year,
            "fields": len(_mx_report_fields(db, t)), "contentHash": template_content_hash(db, t),
            "approvedById": t.approved_by_id, "previousVersionId": t.previous_version_id,
            "changeSummary": t.change_summary, "createdAt": t.created_at.isoformat() if t.created_at else None,
            "activationRefusal": _mx_platform_gate_text(db, t)})
    return list(groups.values())


def _mx_platform_gate_text(db: Session, template) -> Optional[str]:
    """What the activation gate already refuses on platform data alone (gates,
    pack, fields). The proof on a real committed payslip reads tenant data, so a
    platform view never runs it: activation itself still does."""
    reasons = _mx_activation_platform_reasons(db, template)
    if reasons is None:
        return "not a Mexico report type this release can activate"
    if reasons:
        return "; ".join(reasons) + " (and the payslip field proof at activation)"
    return None


def mx_template_new_version(db: Session, template_id: int, version: str, reason: str, actor_id: Optional[int]) -> dict:
    from app.core.exceptions import NotFoundException
    from app.modules.payroll import service

    m = _mx_report_models()
    src = db.get(m.ReportTemplate, template_id)
    if src is None or src.jurisdiction_country != MX:
        raise NotFoundException("Mexico report template", template_id)
    version, reason = (version or "").strip(), (reason or "").strip()
    if not version or len(version) > 20:
        raise BadRequestException("A new version needs a version number (at most 20 characters)")
    if not reason:
        raise BadRequestException("A new version needs a reason (the rollback or the change it starts)")
    if actor_id is None:
        raise BadRequestException("A new version needs an identified Super Admin")
    if db.query(m.ReportTemplate).filter(m.ReportTemplate.template_key == src.template_key,
                                         m.ReportTemplate.version == version).first():
        raise BadRequestException(f"{src.template_key} v{version} already exists")
    cols = {c.name: getattr(src, c.name) for c in m.ReportTemplate.__table__.columns
            if c.name not in _TEMPLATE_COPY_SKIP}
    new = m.ReportTemplate(**cols, version=version, status="Draft", previous_version_id=src.id,
                           created_by_id=actor_id, updated_by_id=actor_id,
                           change_summary=f"Copy of v{src.version}: {reason}"[:500])
    db.add(new)
    db.commit()
    db.refresh(new)
    service._clone_report_template_structure(db, source_template_id=src.id, target_template_id=new.id)
    service.record_tax_audit(db, actor_id=actor_id, action="new_version", entity_type="report_template",
                             entity_id=new.id, tax_version=new.version, legal_reference=new.source_references,
                             old_value={"copiedFrom": src.id, "version": src.version},
                             new_value={"version": new.version, "status": "Draft"}, reason=reason)
    return {"id": new.id, "templateKey": new.template_key, "version": new.version, "status": new.status,
            "copiedFrom": {"id": src.id, "version": src.version}, "fields": len(_mx_report_fields(db, new))}
