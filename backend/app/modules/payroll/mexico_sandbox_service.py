"""
modules/payroll/mexico_sandbox_service.py
-----------------------------------------
Mexico final mile X2: the platform calculation sandbox. A SYNTHETIC employee
and employer, a pay date, and the content in force on that date (the national
and state packs covering it — Draft allowed, and labelled) run through the
production engine (engine/countries/mexico.calculate). Nothing is written: no
organisation, no payslip, no accumulator, no outbox, no audit row.

The answer is either the engine's full result (the calculation trace) or the
first block it raises, with the decisions that would clear that code (X1).
Today every run stops at MX_ROUNDING_RULE_MISSING — the expected answer.

What-if mode: a candidate value for a decision that is not yet approved
(OPEN or PROPOSED in the register) may be supplied for a pack-row content key
(D-01's mx_rounding_rule, D-03, D-17). It is checked against the decision's
grammar, injected into an in-memory copy of the rows only, never persisted,
and the whole answer is watermarked CANDIDATE — NOT APPROVED — NOT A GOLDEN
VECTOR. A key not linked to such a decision, or a module switch (which would
mean patching code shared with real runs), is refused.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

SANDBOX_MARK = "SANDBOX — SYNTHETIC INPUTS — NOT A PAYSLIP"
CANDIDATE_MARK = "CANDIDATE — NOT APPROVED — NOT A GOLDEN VECTOR"
ZONES = ("GENERAL", "ZLFN")
_NOT_APPROVED = ("OPEN", "PROPOSED")


def _dec(value, label) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise BadRequestException(f"{label} must be a number")
    if not out.is_finite() or out < 0:
        raise BadRequestException(f"{label} must be zero or more")
    return out


def _date(value, label) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise BadRequestException(f"{label} must be an ISO date")


def _pack(db: Session, on: date, state: Optional[str] = None):
    """The Mexico tax pack whose window covers `on` (national, or a state's),
    preferring Active, then the newest; Draft packs are allowed and labelled."""
    from app.modules.payroll.models import JurisdictionPack as J

    q = db.query(J).filter(J.jurisdiction_country == "MX", J.pack_type == "tax",
                           (J.jurisdiction_state == state) if state else J.jurisdiction_state.is_(None))
    packs = [p for p in q.all() if (p.effective_from is None or p.effective_from <= on)
             and (p.effective_to is None or p.effective_to >= on) and p.status not in ("Retired", "Superseded")]
    packs.sort(key=lambda p: (p.status == "Active", p.id), reverse=True)
    return packs[0] if packs else None


def _pack_label(pack) -> Optional[dict]:
    if pack is None:
        return None
    return {"id": pack.id, "packId": pack.pack_id, "version": pack.version, "status": pack.status,
            "draft": pack.status != "Active",
            "label": f"{pack.pack_id} v{pack.version} ({pack.status}"
                     f"{', NOT ACTIVE — treated as in force for the sandbox only' if pack.status != 'Active' else ''})"}


def _candidate(db: Session, candidate: Optional[dict], rate_map: dict) -> Optional[dict]:
    """Apply a not-yet-approved decision's candidate value to the in-memory rows."""
    if not candidate:
        return None
    import re

    from app.modules.payroll import mexico_decision_service as decisions
    from app.modules.payroll.engine.countries import mexico_content as c
    from app.modules.payroll.models import PayrollMxDecision as D

    code = str(candidate.get("decision") or "").strip()
    if not re.fullmatch(r"[A-Z]-?\d{1,2}b?", code):
        raise BadRequestException("candidate.decision must be a decision code such as D-01")
    value = str(candidate.get("value") or "").strip()
    row = (db.query(D).filter(D.code == code, D.status.in_(_NOT_APPROVED)).order_by(D.version.desc()).first())
    if row is None:
        raise BadRequestException(f"what-if is allowed only for a decision not yet approved (OPEN or PROPOSED): "
                                  f"{code or '(none)'} has no such record")
    keys = [k for k in (row.content_keys or []) if k in c.MX_PARAMETER_KEYS]
    if len(keys) != 1:
        raise BadRequestException(f"{code} populates {', '.join(row.content_keys or []) or 'no content key'} — "
                                  "what-if covers one pack-row key only (a module switch is never patched)")
    decisions.validate_answer(row, value)
    rate_map[keys[0]] = {"employee_rate_pct": None, "employer_rate_pct": None, "flat_amount": None,
                         "jurisdiction_state": None, "text_value": value}
    return {"decision": code, "decisionStatus": row.status, "contentKey": keys[0], "value": value,
            "watermark": CANDIDATE_MARK}


def _inputs(data: dict) -> dict:
    on = _date(data.get("payDate"), "payDate")
    start = _date(data.get("periodStart") or on.replace(day=1), "periodStart")
    end = _date(data.get("periodEnd") or on, "periodEnd")
    if end < start:
        raise BadRequestException("periodEnd must not be before periodStart")
    daily = _dec(data.get("dailySalary"), "dailySalary")
    if daily <= 0:
        raise BadRequestException("dailySalary must be more than zero")
    days = _dec(data.get("daysPaid") if data.get("daysPaid") not in (None, "") else (end - start).days + 1,
                "daysPaid")
    zone = str(data.get("zone") or "GENERAL").upper()
    if zone not in ZONES:
        raise BadRequestException(f"zone must be one of {', '.join(ZONES)}")
    return {"on": on, "start": start, "end": end, "daily": daily, "days": days, "zone": zone,
            "state": str(data.get("workState") or "CDMX").upper(),
            "frequency": str(data.get("payFrequencyCode") or "04"),
            "seniority": _date(data.get("seniorityDate") or "2024-01-01", "seniorityDate"),
            "risk": _dec(data.get("riskPremiumPct") if data.get("riskPremiumPct") not in (None, "") else "0.54355",
                         "riskPremiumPct")}


def _context(i: dict, period: str, rate_map: dict, slabs: list, isn_pack, pack):
    from app.modules.payroll.engine.base import PayrollContext

    gross = (i["daily"] * i["days"]).quantize(Decimal("0.0001"))
    salary = {"id": 0, "earning_code": "SANDBOX_SALARY", "version": 1, "effective_from": date(i["on"].year, 1, 1),
              "effective_to": None,
              "status": "ACTIVE", "isr_treatment": "TAXABLE", "isr_exempt_rule_key": None, "sbc_treatment": "FIXED",
              "infonavit_included": True, "isn_default_included": True, "isn_state_overrides": None,
              "ptu_wage_base_included": True, "cfdi_node_type": "PERCEPCION", "cfdi_concept_code": None}
    facts = {
        "mx_payroll_date": i["on"], "mx_payment_period": period,
        "mx_profile": {"mx_daily_salary": i["daily"], "mx_seniority_date": i["seniority"],
                       "mx_work_state": i["state"], "mx_identifier_validation_status": "FORMAT_ONLY",
                       "mx_professional_min_code": None},
        "mx_registration": {"id": 0, "status": "ACTIVE"},
        "mx_risk_premium": {"registration_id": 0, "status": "ACTIVE", "premium_rate_pct": str(i["risk"]),
                            "period_from": date(i["on"].year if i["on"].month >= 3 else i["on"].year - 1, 3, 1),
                            "period_to": date(i["on"].year + (1 if i["on"].month >= 3 else 0), 2, 28)},
        # SYNTHETIC labour policy at the statutory floors the spec's fixtures use (F2: 15 / 12 / 25%).
        "mx_labor_policy": {"ordinary_weekly_hours": "40", "aguinaldo_days": "15", "vacation_premium_pct": "25",
                            "sunday_premium_pct": "25",
                            "vacation_policy": [{"serviceYearFrom": 1, "serviceYearTo": 1, "days": 12},
                                                {"serviceYearFrom": 2, "serviceYearTo": 2, "days": 14},
                                                {"serviceYearFrom": 3, "serviceYearTo": None, "days": 16}]},
        "mx_isn_state_pack": isn_pack,
        "mx_classifications": {"SANDBOX_SALARY": salary},
        "mx_earnings": [{"code": "SANDBOX_SALARY", "kind": "ORDINARY_SALARY", "amount": gross}],
        "mx_period": {"start": i["start"], "end": i["end"], "days_paid": i["days"]},
        "mx_hours": None, "mx_variable_accumulator": {"total": 0, "days": 0}, "mx_min_wage_zone": i["zone"],
        "mx_month_to_date": {"taxable": 0, "subsidy_applied": 0}, "mx_infonavit_notices": [],
        "mx_pack": {"pack_id": pack.pack_id, "version": pack.version, "id": pack.id},
        "mx_organization_id": None,
    }
    return PayrollContext(gross=gross, basic=gross, country="MX", rate_map=rate_map, slabs=slabs, **facts), gross


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _cleared_by(db: Session, code: str, message: str) -> list:
    """The decisions that clear a block: by its code, or — for the generic
    MX_CONTENT_MISSING — by the content key the message names."""
    import re

    from app.modules.payroll import mexico_decision_service as decisions
    from app.modules.payroll.models import PayrollMxDecision as D

    if code != "MX_CONTENT_MISSING":
        return decisions.mx_decisions_for_block(db, code)
    m = re.search(r"no (mx_[a-z0-9_]+) row", message or "")
    return [{"id": r.id, "code": r.code, "version": r.version, "title": r.title, "status": r.status}
            for r in db.query(D).filter(D.status.in_(decisions.LIVE)).order_by(D.code, D.version)
            if m and m.group(1) in (r.content_keys or [])]


def run_mx_sandbox(db: Session, data: dict) -> dict:
    """One sandbox calculation. Reads only; never commits or flushes."""
    from app.modules.payroll import mexico_decision_service as decisions
    from app.modules.payroll import service
    from app.modules.payroll.engine.countries import mexico, mexico_content as c
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    i = _inputs(data or {})
    pack = _pack(db, i["on"])
    marks = [SANDBOX_MARK]
    base = {"inputs": _plain({k: v for k, v in i.items()}), "pack": _pack_label(pack), "watermarks": marks,
            "persisted": False}
    if pack is None:
        return {**base, "outcome": "BLOCKED", "block": {"code": "MX_PACK_MISSING",
                "message": f"no Mexico national pack covers {i['on'].isoformat()}"}, "clearedBy": []}
    rate_map, slabs = service.pack_rows_for_golden(db, pack, i["on"])
    rate_map = copy.deepcopy(rate_map)
    wanted = list(data.get("candidates") or []) + ([data["candidate"]] if data.get("candidate") else [])
    if len({str((w or {}).get("decision")) for w in wanted}) != len(wanted):
        raise BadRequestException("one candidate per decision")
    candidates = [_candidate(db, w, rate_map) for w in wanted]
    if candidates:
        marks.append(CANDIDATE_MARK)
    isn = _pack(db, i["on"], i["state"])
    isn_pack = None
    if isn is not None:
        isn_rates, _isn_slabs = service.pack_rows_for_golden(db, isn, i["on"])
        # A Draft state pack is passed to the engine as in force — for the sandbox only, and labelled.
        isn_pack = {"state": i["state"], "status": "Active", "pack_id": isn.pack_id, "version": isn.version,
                    "rate_map": isn_rates}
    out = {**base, "candidates": candidates, "isnPack": _pack_label(isn)}
    period = c.MX_PAY_FREQUENCY_ISR_PERIOD.get(i["frequency"])
    if period is None:
        code = "MX_PAY_FREQUENCY_MAPPING_MISSING"
        return {**out, "outcome": "BLOCKED", "block": {"code": code, "message":
                f"pay frequency {i['frequency']} has no Art. 96 period mapped"},
                "clearedBy": decisions.mx_decisions_for_block(db, code)}
    ctx, gross = _context(i, period, rate_map, slabs, isn_pack, pack)
    try:
        result = mexico.calculate(ctx)
    except MXBlock as exc:
        reasons = [{"code": code, "message": message, "clearedBy": _cleared_by(db, code, message)}
                   for code, message in exc.reasons]
        first = reasons[0] if reasons else {"code": exc.key, "message": exc.reason, "clearedBy": []}
        return {**out, "outcome": "BLOCKED", "gross": str(gross),
                "block": {"code": first["code"], "message": first["message"], "reasons": reasons},
                "clearedBy": first["clearedBy"]}
    return {**out, "outcome": "CALCULATED", "gross": str(gross), "result": _plain(result)}
