"""
payroll/mexico_payslip_service.py
---------------------------------
Recibo de nómina v2.0 (docs/mexico/MEXICO_RECIBO_REPORT.md): the Mexican
payslip, built ONCE as a masked view that the PDF renderer
(mexico_payslip_pdf.py), the on-screen payslip and the mobile summary all
read — so the three can never disagree.

Rules this module enforces (each has a test in test_mexico_recibo.py):
  * every figure comes from the committed `mx_calculation_snapshot.result` and
    the payslip row's own totals — nothing statutory is recomputed; the only
    arithmetic is summing printed lines and checking they equal the stored
    totals (a mismatch refuses, it is never "fixed" for display);
  * the CFDI state comes from the payroll_mx_cfdi_documents row, and the UUID,
    stamp time and SAT certificate number ONLY from the stored stamped XML
    (mexico_cfdi_receipt.receipt_from_xml) — payroll approval alone is never
    "issued"; a draft never carries a UUID, seal or QR;
  * the payment state is separate (payroll_mx_payment_items): a stamp is never
    presented as a bank payment;
  * identifiers (RFC, CURP, NSS, registro patronal, postal code) are masked —
    the full values appear only on the printed CFDI receipt (W4-3b);
  * SAT codes come from the approved classification / system-concept mappings;
    a line without one prints "clave pendiente", never an invented code;
  * employer IMSS / INFONAVIT / ISN are shown as employer costs, never as
    employee deductions;
  * rendering writes nothing: no report row, no document change (a duplicate
    is a re-render marked DUPLICADO, never a new issuance).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

RENDERER_VERSION = "MX-RECIBO-2.0.0"
DOCUMENT_CODE = "MX24-PAY-001"
DUPLICATE_CODE = "MX24-PAY-010"
HISTORY_CODE = "MX24-PAY-011"
SUMMARY_CODE = "MX24-PAY-003"
PENDING_CODE = "clave pendiente"
_CENT = Decimal("0.01")
_ZERO = Decimal("0")

MONTHS_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

# The ISR period the engine applied (mexico_run_service.run_period_kind /
# payment_period) — a display label only.
PERIOD_ES = {"DAILY": "diaria", "WEEKLY_7": "semanal", "DECENAL_10": "decenal", "QUINCENAL_15": "quincenal",
             "MONTHLY": "mensual"}
EXTRAORDINARY = ("AGUINALDO", "PTU", "FINIQUITO")

# A display name for an engine concept kind when the line carries no employer
# classification label and no approved SAT code to describe it (UI text only,
# not a statutory value).
KIND_ES = {
    "ORDINARY_SALARY": "Sueldo base", "OVERTIME": "Horas extra", "SUNDAY_PREMIUM": "Prima dominical",
    "REST_DAY": "Días de descanso laborados", "AGUINALDO": "Aguinaldo", "VACATION_PREMIUM": "Prima vacacional",
    "VACATION_PAYOUT": "Vacaciones pagadas", "PTU": "Participación de los trabajadores en las utilidades (PTU)",
    "SEPARATION_SENIORITY_PREMIUM": "Prima de antigüedad", "SEPARATION_INDEMNITY": "Indemnización",
    "SEPARATION_PAYMENT": "Pago por separación", "OTHER": "Otra percepción",
}

DRAFT_RIBBON = ("BORRADOR / NO TIMBRADO · SIN UUID · SIN SELLO SAT · NO FISCALMENTE VÁLIDO · NO ACREDITA PAGO")
STAMPED_STATES = ("STAMPED", "CANCEL_REQUESTED")
CANCELLED_STATES = ("CANCELLED", "REPLACED")
PAYMENT_ES = {"SETTLED": "pagado", "PENDING": "pendiente", "UNKNOWN": "pendiente (resultado sin confirmar)",
              "FAILED": "no pagado (fallido)", "RETURNED": "no pagado (devuelto)"}


# ── formatting ───────────────────────────────────────────────────────────────

def _d(value) -> Decimal:
    if value is None or value == "":
        return _ZERO
    return Decimal(str(value))


def money(value) -> str:
    """es-MX: comma thousands, point decimals — "40,000.00"."""
    return f"{_d(value).quantize(_CENT, rounding=ROUND_HALF_UP):,.2f}"


def _as_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def date_es(v) -> str:
    d = _as_date(v)
    return f"{d.day:02d} {MONTHS_ES[d.month - 1]} {d.year}" if d else "—"


def period_es(start, end, pay) -> str:
    """"01–15 oct 2026 · pago 15 oct" (years / months repeated only when they differ)."""
    s, e, p = _as_date(start), _as_date(end), _as_date(pay)
    if s.year == e.year and s.month == e.month:
        span = f"{s.day:02d}–{e.day:02d} {MONTHS_ES[e.month - 1]} {e.year}"
    elif s.year == e.year:
        span = f"{s.day:02d} {MONTHS_ES[s.month - 1]} – {e.day:02d} {MONTHS_ES[e.month - 1]} {e.year}"
    else:
        span = f"{date_es(s)} – {date_es(e)}"
    paid = f"{p.day:02d} {MONTHS_ES[p.month - 1]}" + ("" if p.year == e.year else f" {p.year}")
    return f"{span} · pago {paid}"


def mask_tail(value, keep: int = 3) -> Optional[str]:
    """All but the last `keep` characters masked (NSS: last 3, per the design)."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    return "*" * max(len(s) - keep, 0) + s[-keep:] if len(s) > keep else "*" * len(s)


# ── data assembly ────────────────────────────────────────────────────────────

def _models():
    from app.modules.payroll import models as m

    return m


def latest_document(db: Session, item_id: int):
    """The payslip's most recent CFDI document (original or replacement)."""
    m = _models()
    return (db.query(m.PayrollMxCfdiDocument).filter(m.PayrollMxCfdiDocument.payslip_item_id == item_id)
            .order_by(m.PayrollMxCfdiDocument.id.desc()).first())


def payment_state(db: Session, item_id: int) -> dict:
    """The payment outcome, kept apart from the stamp (a stamp is not a payment)."""
    m = _models()
    row = (db.query(m.PayrollMxPaymentItem).join(m.PayrollMxPaymentBatch,
                                                 m.PayrollMxPaymentItem.batch_id == m.PayrollMxPaymentBatch.id)
           .filter(m.PayrollMxPaymentItem.payslip_item_id == item_id, m.PayrollMxPaymentBatch.status != "CANCELLED")
           .order_by(m.PayrollMxPaymentItem.id.desc()).first())
    status = row.status if row is not None else None
    return {"status": status or "NONE", "label": PAYMENT_ES.get(status, "pendiente"),
            "paid": status == "SETTLED"}


def _stamp_facts(db: Session, doc) -> dict:
    """UUID / stamp time / SAT certificate number — from the stored stamped XML only."""
    from app.core import object_storage
    from app.modules.payroll import mexico_cfdi_receipt, mexico_cfdi_service

    ref = mexico_cfdi_service.stamped_xml_ref(db, doc)
    if not ref:
        return {"uuid": None, "stampedAt": None, "satCertificate": None, "xmlStored": False}
    try:
        cert = mexico_cfdi_receipt.receipt_from_xml(object_storage.read_bytes(ref))["certification"]
    except BadRequestException:          # stored, but not a stamped CFDI (no TimbreFiscalDigital)
        return {"uuid": None, "stampedAt": None, "satCertificate": None, "xmlStored": False}
    return {"uuid": cert.get("UUID"), "stampedAt": cert.get("FechaTimbrado"),
            "satCertificate": cert.get("NoCertificadoSAT"), "xmlStored": True}


def fiscal_state(db: Session, item_id: int) -> dict:
    doc = latest_document(db, item_id)
    status = doc.status if doc is not None else None
    if status in STAMPED_STATES:
        facts = _stamp_facts(db, doc)
        state = "STAMPED" if facts["xmlStored"] else "STAMPED_XML_MISSING"
    elif status in CANCELLED_STATES:
        facts = _stamp_facts(db, doc)
        state = "CANCELLED"
    else:
        facts = {"uuid": None, "stampedAt": None, "satCertificate": None, "xmlStored": False}
        state = "DRAFT"
    return {"state": state, "documentId": doc.id if doc is not None else None, "documentStatus": status,
            "cancelRequested": status == "CANCEL_REQUESTED", "replacementUuid": getattr(doc, "replaced_by_uuid", None),
            "releaseId": doc.schema_release_id if doc is not None else None, **facts}


def _release_id(db: Session, fiscal: dict) -> Optional[int]:
    if fiscal.get("releaseId"):
        return fiscal["releaseId"]
    from app.modules.payroll import mexico_cfdi_service

    rel = mexico_cfdi_service._active_release(db)
    return rel.id if rel is not None else None


def _approved_code(db: Session, release_id: Optional[int], key: str) -> Optional[str]:
    if release_id is None:
        return None
    from app.modules.payroll import mexico_cfdi_catalog_service

    row = mexico_cfdi_catalog_service.approved_concept(db, release_id, key)
    return row.sat_code if row is not None else None


def _perceptions(db: Session, result: dict, release_id: Optional[int]) -> list:
    from app.modules.payroll.mexico_cfdi_input import SPECIAL_KIND_CONCEPTS
    from app.modules.payroll.models import PayrollMxEarningClassification

    lines = []
    for c in result.get("concepts") or []:
        gross = _d(c.get("gross"))
        if not gross:
            continue
        kind = c.get("kind")
        code = (_approved_code(db, release_id, kind) if kind in SPECIAL_KIND_CONCEPTS
                else c.get("cfdi_concept_code"))
        label = None
        if c.get("classification_id"):
            cls = db.get(PayrollMxEarningClassification, c["classification_id"])
            label = getattr(cls, "label", None)
        label = label or KIND_ES.get(kind) or str(c.get("code") or kind)
        if kind == "ORDINARY_SALARY" and result.get("days_paid") not in (None, ""):
            label = f"{label} ({_d(result['days_paid']).normalize():f} días)"
        lines.append({"satCode": code, "codePending": code is None, "concept": label,
                      "taxed": _d(c.get("isr_taxable")), "exempt": _d(c.get("isr_exempt")), "total": gross})
    return lines


def _deductions(result: dict, item) -> tuple:
    """(lines, total) — the employee's deductions only (employer costs never)."""
    period = PERIOD_ES.get(result.get("tariff_period"), result.get("tariff_period") or "del periodo")
    subsidy = result.get("subsidy") or {}
    applied = _d(subsidy.get("applied"))
    isr_basis = f"Tarifa LISR Art. 96 – periodo {period}"
    if applied:
        isr_basis += f"; ISR de tarifa {money(result.get('isr'))} − subsidio para el empleo aplicado {money(applied)}"
    annual = result.get("annual_adjustment") or {}
    if annual:
        isr_basis += f"; incluye ajuste anual {annual.get('fiscal_year')}"
    lines = [{"key": "ISR_WITHHELD", "concept": "ISR retenido", "amount": _d(result.get("isr_withheld")),
              "basis": isr_basis}]
    imss = _d(result.get("imss_employee"))
    if imss:
        days = result.get("contribution_days")
        lines.append({"key": "IMSS_EMPLOYEE", "concept": "Cuota obrera IMSS", "amount": imss,
                      "basis": f"Cuotas obreras LSS · {days} días cotizados" if days not in (None, "") else
                      "Cuotas obreras LSS"})
    credit = _d(result.get("infonavit_credit"))
    if credit:
        refs = [mask_tail(l.get("authority_reference"), 4) or f"aviso #{l.get('notice_id')}"
                for l in result.get("infonavit_credit_lines") or [] if _d(l.get("amount"))]
        lines.append({"key": "INFONAVIT_CREDIT", "concept": "Crédito INFONAVIT", "amount": credit,
                      "basis": "Aviso de retención en vigor: " + (", ".join(refs) if refs else "registrado")})
    listed = sum((l["amount"] for l in lines), _ZERO)
    total = _d(item.total_deductions)
    other = (total - listed).quantize(_CENT)
    if other < 0:
        raise BadRequestException(f"payslip {item.id}: the snapshot's deductions ({money(listed)}) exceed the payslip's "
                                  f"stored total ({money(total)}) — the recibo is not rendered from inconsistent data")
    if other > 0:
        lines.append({"key": "OTHER_AUTHORISED", "concept": "Otras deducciones autorizadas", "amount": other,
                      "basis": "Registradas en la nómina del periodo"})
    return lines, total


def _parties(db: Session, item, run) -> dict:
    from app.modules.payroll import mexico_employee_service, mexico_employer_service
    from app.modules.payroll.models import PayrollEmployee, PayrollMxImssRegistration

    on = run.pay_date
    employee = db.get(PayrollEmployee, item.employee_id)
    prof = mexico_employee_service._profile_on(db, item.employee_id, on)
    reg = (db.get(PayrollMxImssRegistration, prof.mx_imss_registration_id)
           if prof is not None and prof.mx_imss_registration_id else None)
    version = mexico_employer_service.version_in_force(db, reg.employer_profile_id, on) if reg is not None else None
    ids = (getattr(employee, "compliance_fields", None) or {}) if employee is not None else {}
    cp = getattr(version, "fiscal_postal_code", None)
    return {
        "employer": {
            "name": getattr(version, "legal_name", None),
            "rfc": mask_tail(getattr(version, "rfc", None)),
            "registroPatronal": mask_tail(getattr(reg, "registro_patronal", None)),
            "state": getattr(prof, "mx_work_state", None),
            "postalCode": mask_tail(cp, 2),
            "fiscalRegime": getattr(version, "fiscal_regime_code", None),
        },
        "employee": {
            "name": getattr(employee, "name", None) or item.employee_name,
            "rfc": mask_tail(ids.get("rfc")), "curp": mask_tail(ids.get("curp")), "nss": mask_tail(ids.get("nss")),
            "employeeCode": getattr(employee, "employee_code", None),
            "fiscalRegime": getattr(prof, "mx_receiver_fiscal_regime", None),
        },
    }


def recibo_view(db: Session, item, run, *, duplicate: bool = False) -> dict:
    """The masked, render-ready recibo for one Mexican payslip. Raises
    BadRequestException when the payslip has no committed Mexican result or
    its stored totals do not reconcile — never a fabricated figure."""
    snap = item.mx_calculation_snapshot or {}
    result = snap.get("result") or {}
    if snap.get("blocked") or not result:
        raise BadRequestException(f"payslip {item.id} has no Mexican calculation — no recibo is rendered")

    fiscal = fiscal_state(db, item.id)
    payment = payment_state(db, item.id)
    release_id = _release_id(db, fiscal)
    perceptions = _perceptions(db, result, release_id)
    deductions, deductions_total = _deductions(result, item)
    gross = _d(item.gross_pay)
    net = _d(item.net_pay)
    perception_total = sum((l["total"] for l in perceptions), _ZERO)
    if perception_total.quantize(_CENT) != _d(result.get("gross")).quantize(_CENT) or \
            gross.quantize(_CENT) != _d(result.get("gross")).quantize(_CENT):
        raise BadRequestException(f"payslip {item.id}: the earnings lines ({money(perception_total)}) do not equal the "
                                  f"committed gross ({money(result.get('gross'))}) — the recibo is not rendered")
    if (gross - deductions_total).quantize(_CENT) != net.quantize(_CENT):
        raise BadRequestException(f"payslip {item.id}: gross − deductions ({money(gross - deductions_total)}) is not the "
                                  f"stored net ({money(net)}) — the recibo is not rendered")

    subsidy_applied = _d((result.get("subsidy") or {}).get("applied"))
    other_payments = []
    if subsidy_applied:
        code = _approved_code(db, release_id, "SUBSIDY_APPLIED")
        other_payments.append({"satCode": code, "codePending": code is None, "concept": "Subsidio para el empleo",
                               "amount": subsidy_applied,
                               "note": "Aplicado contra el ISR del periodo (ver ISR retenido); no se suma al devengado"})

    run_type = (getattr(run, "mx_run_type", None) or "ORDINARY").upper()
    extraordinary = run_type in EXTRAORDINARY
    pilot = bool((getattr(run, "mx_approval_fingerprint", None) or {}).get("pilot") or snap.get("pilot"))
    state = fiscal["state"]
    if state == "STAMPED":
        ribbon = "CFDI TIMBRADO" + (" · CANCELACIÓN SOLICITADA" if fiscal["cancelRequested"] else "")
        stamp_word, doc_state = "timbrado", "TIMBRADO"
    elif state == "CANCELLED":
        ribbon = "CFDI CANCELADO · NO ES EL RECIBO VIGENTE"
        if fiscal["replacementUuid"]:
            ribbon += f" · SUSTITUIDO POR {fiscal['replacementUuid']}"
        stamp_word, doc_state = "CFDI cancelado", "CANCELADO"
    elif state == "STAMPED_XML_MISSING":
        # a document row that says STAMPED without a stored, readable stamped XML is never presented as issued
        ribbon = "ESTADO FISCAL NO VERIFICABLE · SIN XML TIMBRADO ALMACENADO · NO SE PRESENTA COMO EMITIDO"
        stamp_word, doc_state = "estado fiscal no verificable", "NO VERIFICABLE"
    else:
        ribbon, stamp_word, doc_state = DRAFT_RIBBON, "NO timbrado", "BORRADOR"
    if duplicate:
        doc_state = f"DUPLICADO · {doc_state}"
    payment_line = f"Pago: {payment['label']}"
    if state in ("STAMPED", "STAMPED_XML_MISSING"):
        ribbon += f" · {payment_line.upper()}"

    if state == "DRAFT":
        sat = {"uuid": "NO DISPONIBLE", "stamp": "SIN TIMBRADO", "seal": "NO DISPONIBLE", "xmlQr": "NO EMITIDOS"}
    elif fiscal["xmlStored"]:
        sat = {"uuid": fiscal["uuid"], "stamp": f"{fiscal['stampedAt']} · certificado SAT {fiscal['satCertificate']}",
               "seal": "Sello SAT en el XML timbrado (ver representación impresa del CFDI)",
               "xmlQr": "XML timbrado almacenado; QR en la representación impresa del CFDI (Anexo 20 I.D)"}
    else:
        sat = {"uuid": "NO DISPONIBLE (XML timbrado no almacenado)", "stamp": "NO DISPONIBLE", "seal": "NO DISPONIBLE",
               "xmlQr": "NO DISPONIBLE"}
    if state == "CANCELLED":
        sat["uuid"] = f"{fiscal['uuid'] or 'NO DISPONIBLE'} (CANCELADO)"

    isn = result.get("isn") or {}
    return {
        "documentCode": DUPLICATE_CODE if duplicate else DOCUMENT_CODE,
        "rendererVersion": RENDERER_VERSION,
        "payslipId": item.id, "runId": run.id, "employeeId": item.employee_id, "duplicate": duplicate,
        "pilot": pilot,
        "title": "Recibo de nómina / Payslip",
        "subtitle": f"Recibo de nómina en español · nómina {'extraordinaria' if extraordinary else 'ordinaria'} · "
                    f"{stamp_word}",
        "ribbon": ribbon,
        "fiscal": {"state": state, "documentState": doc_state, "label": {"DRAFT": "NO TIMBRADO", "STAMPED": "TIMBRADO",
                                                                        "STAMPED_XML_MISSING": "NO VERIFICABLE",
                                                                        "CANCELLED": "CANCELADO"}[state],
                   "cancelRequested": fiscal["cancelRequested"], "replacementUuid": fiscal["replacementUuid"],
                   "current": state != "CANCELLED", "sat": sat},
        "payment": payment,
        "parties": _parties(db, item, run),
        "payroll": {"type": "Extraordinaria" if extraordinary else "Ordinaria", "runType": run_type,
                    "periodicity": PERIOD_ES.get(result.get("tariff_period"), result.get("tariff_period") or "—"),
                    "period": period_es(run.period_start, run.period_end, run.pay_date),
                    "periodStart": run.period_start.isoformat(), "periodEnd": run.period_end.isoformat(),
                    "payDate": run.pay_date.isoformat(), "daysPaid": result.get("days_paid")},
        "perceptions": [{**l, "taxed": money(l["taxed"]), "exempt": money(l["exempt"]), "total": money(l["total"])}
                        for l in perceptions],
        "perceptionTotals": {"taxed": money(sum((l["taxed"] for l in perceptions), _ZERO)),
                             "exempt": money(sum((l["exempt"] for l in perceptions), _ZERO)),
                             "total": money(perception_total)},
        "otherPayments": [{**o, "amount": money(o["amount"])} for o in other_payments],
        "deductions": [{**l, "amount": money(l["amount"])} for l in deductions],
        "totals": {"gross": money(gross), "deductions": money(deductions_total), "net": money(net), "currency": "MXN"},
        "employer": {"imss": money(result.get("imss_employer")), "infonavit": money(result.get("infonavit_employer")),
                     "isn": money(isn.get("amount")), "total": money(result.get("employer_total")),
                     "note": ("APORTACIONES PATRONALES. La aportación patronal INFONAVIT del 5% sobre la base legal, así "
                              "como las cuotas patronales IMSS, son costos del patrón. NO se descuentan del neto del "
                              "trabajador.")},
        "footer": {"confidential": "CONFIDENTIAL", "documentState": doc_state,
                   "issueDate": date_es(datetime.now(timezone.utc)),
                   "snapshotHash": (snap.get("inputHash") or "")[:12] or "—"},
    }


def mobile_summary(view: dict) -> dict:
    """MX24-PAY-003: the few facts a phone screen leads with — each with a
    spoken label for screen readers."""
    t = view["totals"]
    key_lines = [{"label": l["concept"], "amount": l["amount"]} for l in view["deductions"]][:3]
    return {
        "documentCode": SUMMARY_CODE,
        "net": t["net"], "currency": t["currency"], "period": view["payroll"]["period"],
        "fiscalStatus": view["fiscal"]["label"], "paymentStatus": view["payment"]["label"],
        "gross": t["gross"], "deductions": t["deductions"], "keyLines": key_lines,
        "ariaLabel": (f"Neto a pagar {t['net']} pesos mexicanos, periodo {view['payroll']['period']}, "
                      f"CFDI {view['fiscal']['label'].lower()}, pago {view['payment']['label']}"),
    }


def pay_history(db: Session, org_id: int, employee_id: int, start: date, end: date) -> dict:
    """MX24-PAY-011: one employee's committed Mexican payslips whose pay date
    falls in [start, end] — the stored figures, CFDI and payment state per
    period. Read-only."""
    m = _models()
    if end < start:
        raise BadRequestException("the period range ends before it starts")
    rows = (db.query(m.PayslipItem, m.PayrollRun).join(m.PayrollRun, m.PayslipItem.payroll_run_id == m.PayrollRun.id)
            .filter(m.PayslipItem.organization_id == org_id, m.PayslipItem.employee_id == employee_id,
                    m.PayslipItem.mx_calculation_snapshot.isnot(None),
                    m.PayrollRun.pay_date >= start, m.PayrollRun.pay_date <= end)
            .order_by(m.PayrollRun.pay_date, m.PayrollRun.id).all())
    out = []
    for item, run in rows:
        snap = item.mx_calculation_snapshot or {}
        if snap.get("blocked") or not snap.get("result"):
            continue
        fiscal = fiscal_state(db, item.id)
        run_type = (getattr(run, "mx_run_type", None) or "ORDINARY").upper()
        out.append({"payslipId": item.id, "period": period_es(run.period_start, run.period_end, run.pay_date),
                    "type": "Extraordinaria" if run_type in EXTRAORDINARY else "Ordinaria", "runType": run_type,
                    "gross": money(item.gross_pay), "deductions": money(item.total_deductions),
                    "net": money(item.net_pay),
                    "cfdi": {"DRAFT": "NO TIMBRADO", "STAMPED": "TIMBRADO", "STAMPED_XML_MISSING": "NO VERIFICABLE",
                             "CANCELLED": "CANCELADO"}[fiscal["state"]],
                    "payment": payment_state(db, item.id)["label"]})
    employee = db.get(m.PayrollEmployee, employee_id)
    if employee is None or employee.organization_id != org_id:
        raise BadRequestException(f"employee {employee_id} not found")
    return {"documentCode": HISTORY_CODE, "rendererVersion": RENDERER_VERSION,
            "employee": {"name": employee.name, "employeeCode": employee.employee_code},
            "range": {"start": start.isoformat(), "end": end.isoformat(),
                      "label": f"{date_es(start)} – {date_es(end)}"},
            "rows": out, "count": len(out)}
