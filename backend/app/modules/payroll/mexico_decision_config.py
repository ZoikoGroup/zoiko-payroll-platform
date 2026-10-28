"""
payroll/mexico_decision_config.py
---------------------------------
Mexico engineering sweep S1: decisions as configuration. Every pending decision
(docs/mexico/DECISIONS_PENDING.md) lists the options built for it here; the
APPROVED answer in the decision register (four-eyes, audited — X1) switches the
engine, report or CFDI behaviour with no code change. While a decision is
unanswered, the case that needs it keeps blocking with its own named code.

Each entry:
  kind     ENUM | PARTS | AMOUNT | ROUNDING_RULE | PAY_PERIOD | RECORD
           (PARTS: "PART=VALUE;PART=VALUE", every part required; RECORD: an
           owner's confirmation the code does not read)
  options  the values built (ENUM / PAY_PERIOD), or {part: values} (PARTS)
  target   "switch" (read through engine decisions.switch), "pack_row:<key>"
           (fills that pack row when the pack has none), "service" (read by a
           service), "governance" (who must confirm an action), "record"
  changes  what answering changes
  needs    what still needs a transcribed VALUE or a SOURCE after answering
           (None = nothing: answering alone completes it)
  notBuilt options the brief lists that are deliberately not built, with why

Answers are applied per calculation through engine/jurisdictions/mexico/
decisions.applied and recorded in the payslip's input components.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException

LIVE_ANSWER = ("APPROVED", "TRANSCRIBED")


def _cfg() -> dict:
    from app.modules.payroll import mexico_cfdi_input as cfdi_input
    from app.modules.payroll.engine.countries import mexico_content as c
    from app.modules.payroll.engine.countries import mexico_rules as r
    from app.modules.payroll.engine.jurisdictions.mexico import labor

    return {
        "D-01": {"kind": "ROUNDING_RULE", "target": "pack_row:mx_rounding_rule",
                 "options": ["HALF_UP:0.01", "HALF_EVEN:0.01", "HALF_DOWN:1"],
                 "changes": "every emitted amount is rounded by the rule (MODE:QUANTUM)",
                 "needs": None},
        "D-02": {"kind": "PAY_PERIOD", "target": "service",
                 "options": list(c.MX_ISR_PERIODS) + ["UNMAPPED"],
                 "changes": "pay frequency 01 (Diario) uses the chosen Art. 96 tariff period; UNMAPPED keeps it "
                            "blocked", "needs": None},
        "D-03": {"kind": "ENUM", "target": "pack_row:mx_ceav_lowest_band_min_wage_ref",
                 "options": ["GENERAL", "ZONE", "UMA"],
                 "changes": "the unit of CEAV band 1's '1.0 SM' bound: the general-zone minimum wage, the worker's "
                            "own zone minimum wage, or the UMA", "needs": None},
        "D-07": {"kind": "ENUM", "target": "switch", "options": list(r.WAGE_REFERENCES),
                 "changes": "the unit of the LISR Art. 93 exempt limits", "needs": None},
        "D-07b": {"kind": "ENUM", "target": "switch", "options": list(r.WAGE_REFERENCES),
                  "changes": "the LFT Art. 486 seniority-premium salary cap's unit", "needs": None},
        "D-08": {"kind": "ENUM", "target": "switch", "options": list(r.WITHHOLDING_METHODS),
                 "changes": "how a special payment paid in its own run is withheld", "needs": None},
        "D-09": {"kind": "ENUM", "target": "switch", "options": list(r.MONTHLY_INCOME_BASES),
                 "changes": "the monthly ordinary income derived from the daily salary (RLISR 174 II, separation)",
                 "needs": None},
        "D-12": {"kind": "ENUM", "target": "switch", "options": list(r.INDEMNITY_SALARY_BASES),
                 "changes": "the LFT Art. 89 indemnity daily salary", "needs": None},
        "D-13": {"kind": "ENUM", "target": "switch", "options": list(r.SERVICE_YEARS_COUNTS),
                 "changes": "whether a part year counts in LFT Arts. 50, 54, 162 amounts", "needs": None},
        "D-14": {"kind": "PARTS", "target": "switch",
                 "options": {"EXCESS": list(r.PTU_CAP_EXCESS_RULES), "AVERAGE": list(r.PTU_HISTORY_AVERAGES)},
                 "changes": "where a share above the Art. 127 VIII cap goes, and the three-year average for "
                            "fewer years", "needs": None},
        "D-17": {"kind": "ENUM", "target": "pack_row:mx_hourly_rate_rule", "options": list(labor.HOURLY_RATE_RULES),
                 "changes": "how the overtime hourly rate is derived from the daily salary", "needs": None},
        "D-21": {"kind": "ENUM", "target": "switch", "options": list(cfdi_input.TIMEZONE_READINGS) + ["KEEP_REFUSING"],
                 "changes": "how a c_CodigoPostal row with inconsistent offsets is read (KEEP_REFUSING keeps the block)",
                 "needs": None},
        "D-22": {"kind": "ENUM", "target": "switch", "options": list(r.FINIQUITO_ORDINARY_METHODS),
                 "changes": "how vacation paid out at termination is withheld against the month", "needs": None},
        "D-24": {"kind": "AMOUNT", "target": "service", "options": None,
                 "changes": "the MX-RUN-VARIANCE high-value threshold", "needs": None},
        "D-25": {"kind": "AMOUNT", "target": "service", "options": None,
                 "changes": "the parallel-payroll materiality threshold", "needs": None},
    }


def config() -> dict:
    return _cfg()


def spec(code: str) -> Optional[dict]:
    return _cfg().get(code)


def _parts(code: str, s: dict, raw: str) -> dict:
    out = {}
    for piece in [p for p in raw.split(";") if p.strip()]:
        if "=" not in piece:
            raise BadRequestException(f"{code}: write each part as PART=VALUE, separated by ';'")
        part, value = (x.strip().upper() for x in piece.split("=", 1))
        if part not in s["options"]:
            raise BadRequestException(f"{code}: unknown part {part!r} (parts: {', '.join(s['options'])})")
        if value not in s["options"][part]:
            raise BadRequestException(f"{code}: {part} must be one of {', '.join(s['options'][part])}")
        out[part] = value
    missing = [p for p in s["options"] if p not in out]
    if missing:
        raise BadRequestException(f"{code}: answer every part ({', '.join(missing)} missing)")
    return out


def parse(code: str, raw: str):
    """The value the consuming code reads, or a refusal naming what is wrong."""
    s = spec(code)
    raw = (raw or "").strip()
    if s is None:
        return raw
    kind = s["kind"]
    if kind == "ROUNDING_RULE":
        from app.modules.payroll.engine.jurisdictions.mexico import rounding
        from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

        try:
            rounding.parse(raw)
        except MXBlock as exc:
            raise BadRequestException(f"{code}: {exc.reason}")
        return raw
    if kind == "AMOUNT":
        try:
            amount = Decimal(raw)
        except (InvalidOperation, ValueError):
            amount = None
        if amount is None or not amount.is_finite() or amount < 0:
            raise BadRequestException(f"{code}: {raw!r} is not an amount (MXN, zero or more)")
        return amount
    if kind in ("ENUM", "PAY_PERIOD"):
        if raw not in s["options"]:
            raise BadRequestException(f"{code}: {raw!r} is not one of {', '.join(s['options'])}")
        return raw
    if kind == "PARTS":
        return _parts(code, s, raw)
    return raw                                                   # RECORD: free text, read by no code


def answers_in_force(db: Session) -> dict:
    """{code: {value, version, id, raw}} — the latest APPROVED / TRANSCRIBED
    answer of each configured decision. An answer the code can no longer read
    (a value removed from the options) is left out, so its case blocks."""
    from app.modules.payroll.models import PayrollMxDecision as D

    out = {}
    configured = _cfg()
    for row in (db.query(D).filter(D.status.in_(LIVE_ANSWER), D.code.in_(list(configured)))
                .order_by(D.code, D.version)):
        if configured[row.code]["kind"] == "RECORD":
            continue
        try:
            value = parse(row.code, row.chosen_option)
        except BadRequestException:
            continue
        out[row.code] = {"value": value, "version": row.version, "id": row.id, "raw": row.chosen_option}
    return out


def fingerprint(answers: dict) -> str:
    """A stable hash of the answers applied (for the payslip input hash)."""
    body = {k: {"version": v["version"], "raw": v["raw"]} for k, v in sorted((answers or {}).items())}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def trace(answers: dict) -> dict:
    """What a payslip records: {code: {version, value}}."""
    return {k: {"version": v["version"], "value": v["raw"]} for k, v in sorted((answers or {}).items())}


@contextmanager
def applying(db: Session):
    """Apply the register's approved answers for the duration of the block
    (yields them). Nested calls reuse the answers already applied."""
    from app.modules.payroll.engine.jurisdictions.mexico import decisions

    current = decisions.in_force()
    if current:
        yield current
        return
    answers = answers_in_force(db)
    with decisions.applied(answers or {}):
        yield answers


def overlay_pack_rows(rate_maps: list, answers: dict) -> list:
    """Fill each rate map's pack-row decisions from approved answers — only where
    the pack has no row for the key (a transcribed row always wins). Returns the
    codes applied."""
    applied = []
    for code, s in _cfg().items():
        target = s["target"]
        if not target.startswith("pack_row:") or code not in (answers or {}):
            continue
        key = target.split(":", 1)[1]
        for rate_map in rate_maps:
            if rate_map is not None and key not in rate_map:
                rate_map[key] = {"employee_rate_pct": None, "employer_rate_pct": None, "flat_amount": None,
                                 "jurisdiction_state": None, "text_value": answers[code]["raw"],
                                 "source": f"DECISION/{code} v{answers[code]['version']}"}
                if code not in applied:
                    applied.append(code)
    return applied
