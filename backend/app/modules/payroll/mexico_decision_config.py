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
    from app.modules.payroll import mexico_cfdi_receipt as receipt
    from app.modules.payroll.engine.jurisdictions.mexico import decision_rules as dr
    from app.modules.payroll.engine.jurisdictions.mexico import labor, special_pay

    return {
        "D-01": {"kind": "ROUNDING_RULE", "target": "pack_row:mx_rounding_rule",
                 "options": ["HALF_UP:0.01", "HALF_EVEN:0.01", "HALF_DOWN:1"],
                 "changes": "every emitted amount is rounded by the rule (MODE:QUANTUM); the calculation runs at "
                            "full precision and rounds each line as it is emitted",
                 "needs": None,
                 "notBuilt": {"TOTALS_ONLY": "rounding only the totals would leave payslip lines unrounded, which "
                                             "the CFDI cannot carry (S30 tdCFDI.xsd / S28 nomina12.xsd "
                                             "t_ImporteMXN: 2 decimals per line); the CFDI sources' 'round at the "
                                             "end of the calculation' is what each line already gets"}},
        "D-02": {"kind": "PAY_PERIOD", "target": "service",
                 "options": list(c.MX_ISR_PERIODS) + ["UNMAPPED"],
                 "changes": "pay frequency 01 (Diario) uses the chosen Art. 96 tariff period; UNMAPPED keeps it "
                            "blocked", "needs": None},
        "D-03": {"kind": "ENUM", "target": "pack_row:mx_ceav_lowest_band_min_wage_ref",
                 "options": ["GENERAL", "ZONE", "UMA"],
                 "changes": "the unit of CEAV band 1's '1.0 SM' bound: the general-zone minimum wage, the worker's "
                            "own zone minimum wage, or the UMA", "needs": None},
        "D-04": {"kind": "RECORD", "target": "record", "options": None,
                 "changes": "nothing: the owner confirms (or rejects) each interpretation behind a transcribed row",
                 "needs": "a rejected interpretation needs that row re-transcribed (VALUE)"},
        "D-05": {"kind": "RECORD", "target": "record", "options": None,
                 "changes": "nothing: the G5 owner confirms the 48-hour January-April 2026 row",
                 "needs": "if the row does not stand, the January-April workweek row needs re-transcribing (VALUE)"},
        "D-06": {"kind": "PARTS", "target": "switch",
                 "options": {k: ["IN", "OUT"] for k in special_pay.ISN_D06_CONCEPTS},
                 "changes": "whether vacation paid out, the separation payment and the indemnity are in the CDMX ISN "
                            "base", "needs": None},
        "D-07": {"kind": "ENUM", "target": "switch", "options": list(r.WAGE_REFERENCES),
                 "changes": "the unit of the LISR Art. 93 exempt limits", "needs": None},
        "D-07b": {"kind": "ENUM", "target": "switch", "options": list(r.WAGE_REFERENCES),
                  "changes": "the LFT Art. 486 seniority-premium salary cap's unit", "needs": None},
        "D-08": {"kind": "ENUM", "target": "switch", "options": list(r.WITHHOLDING_METHODS) + [r.PER_EMPLOYER],
                 "changes": "how a special payment paid in its own run is withheld (PER_EMPLOYER: each employer's "
                            "labour policy names its method; a policy that names none blocks)",
                 "needs": "PER_EMPLOYER: each employer's choice on its labour policy (VALUE, per employer)"},
        "D-09": {"kind": "ENUM", "target": "switch", "options": list(r.MONTHLY_INCOME_BASES),
                 "changes": "the monthly ordinary income derived from the daily salary (RLISR 174 II, separation)",
                 "needs": None},
        "D-10": {"kind": "RECORD", "target": "record", "options": None,
                 "changes": "nothing yet",
                 "needs": "the SAF general rules (SOURCE, not saved) and where an employer's size and sector are "
                          "recorded, before the 2026 micro / small-employer benefit can be modelled",
                 "notBuilt": {"ONE_POINT / ONE_PERCENT_OF_RATE": "the benefit's two readings are not switchable: who "
                                                                 "qualifies (size, sector, application, proof) is "
                                                                 "in the SAF rules, which are not saved — modelling "
                                                                 "it without them would invent eligibility"}},
        "D-11": {"kind": "RECORD", "target": "record", "options": None,
                 "changes": "nothing yet",
                 "needs": "each added reason's components transcribed from S26 (VALUE): mutual consent, death "
                          "(Art. 501 payee), Art. 434"},
        "D-12": {"kind": "ENUM", "target": "switch", "options": list(r.INDEMNITY_SALARY_BASES),
                 "changes": "the LFT Art. 89 indemnity daily salary (labour-policy integrated, the IMSS SBC, or the "
                            "figure an operator enters on the termination)",
                 "needs": "OPERATOR_ENTERED: the figure and its evidence on each termination record (data)",
                 "notBuilt": {"VARIABLE_PAY_30_DAY_AVERAGE": "Art. 89 ¶2's average of the last 30 days worked "
                                                             "needs a per-day record of variable pay the platform "
                                                             "does not keep; until it does, OPERATOR_ENTERED "
                                                             "carries that average with its evidence"}},
        "D-13": {"kind": "ENUM", "target": "switch", "options": list(r.SERVICE_YEARS_COUNTS),
                 "changes": "whether a part year counts in LFT Arts. 50, 54, 162 amounts", "needs": None},
        "D-14": {"kind": "PARTS", "target": "switch",
                 "options": {"EXCESS": list(r.PTU_CAP_EXCESS_RULES), "AVERAGE": list(r.PTU_HISTORY_AVERAGES)},
                 "changes": "where a share above the Art. 127 VIII cap goes, and the three-year average for "
                            "fewer years", "needs": None},
        "D-16": {"kind": "ENUM", "target": "switch", "options": list(c.MX_OFFICIAL_HOLIDAY_LISTS),
                 "changes": "the non-business days IMSS movement deadlines skip (LFT Arts. 74 / 715 or CFF Art. 12)",
                 "needs": "each later year's dates transcribed (2026 is); election days and authority vacations are "
                          "not datable from the saved sources"},
        "D-17": {"kind": "ENUM", "target": "pack_row:mx_hourly_rate_rule", "options": list(labor.HOURLY_RATE_RULES),
                 "changes": "how the overtime hourly rate is derived from the daily salary",
                 "needs": "WEEKLY_HOURS_OVER_DAYS: a weekly schedule on the labour policy; EMPLOYER_DAILY_HOURS: the "
                          "employer's daily-hours figure on the labour policy (data)"},
        "D-18": {"kind": "ENUM", "target": "switch", "options": list(dr.SBC_FIXED_RULES),
                 "changes": "how a FIXED periodic SBC item becomes a daily amount (LSS Art. 30 I)",
                 "needs": "ANNUALISED_365: the earning's payments per year, which no input carries today"},
        "D-19": {"kind": "ENUM", "target": "switch", "options": list(dr.FIXED_DAYS_TERMINATION_RULES),
                 "changes": "the salary days of a fixed-days period that ends at termination", "needs": None},
        "D-20": {"kind": "ENUM", "target": "switch", "options": list(receipt.QR_TOTAL_FORMS),
                 "changes": "the QR total form on the printed receipt (Anexo 20 I.D text or its example)",
                 "needs": None},
        "D-21": {"kind": "ENUM", "target": "switch", "options": list(cfdi_input.TIMEZONE_READINGS) + ["KEEP_REFUSING"],
                 "changes": "how a c_CodigoPostal row with inconsistent offsets is read (KEEP_REFUSING keeps the block)",
                 "needs": None,
                 "notBuilt": {"OFFSETS_FROM_TIME_ZONE_LAW": "option (d) reads the offsets from the time-zone law "
                                                           "(Ley del Sistema de Horario), which is not saved as a "
                                                           "source — a SOURCE first, then a table"}},
        "D-22": {"kind": "ENUM", "target": "switch", "options": list(r.FINIQUITO_ORDINARY_METHODS),
                 "changes": "how vacation paid out at termination is withheld against the month", "needs": None},
        "D-23": {"kind": "ENUM", "target": "record", "options": ["INTERIM_SECOND_SUPER_ADMIN"],
                 "changes": "nothing: confirms the interim control (any second Super Admin approves)",
                 "needs": None,
                 "notBuilt": {"GATE_OWNER_ROLE": "a new privileged role is an authorisation change for ZP-PRIV; no "
                                                 "role is invented"}},
        "D-24": {"kind": "THRESHOLD", "target": "service", "options": None,
                 "changes": "the MX-RUN-VARIANCE high-value threshold: a fixed MXN amount (1500 or AMOUNT:1500), a "
                            "percentage of the prior run's figure (PERCENT:10), or both (either flags); per line "
                            "with NET=… / EMPLOYER_TOTAL=…", "needs": None},
        "D-25": {"kind": "THRESHOLD", "target": "service", "options": None,
                 "changes": "the parallel-payroll materiality threshold: a fixed MXN amount (0 = every difference), "
                            "a percentage of the legacy amount (PERCENT:1), or both (either is material); per "
                            "concept with CONCEPT=AMOUNT:… (that concept's rules replace the default)",
                 "needs": None},
        "D-26": {"kind": "ENUM", "target": "governance", "options": ["SINGLE", "FOUR_EYES"],
                 "changes": "whether making Mexico generally available needs a second Super Admin", "needs": None},
        "D-27": {"kind": "ENUM", "target": "governance", "options": ["SINGLE", "FOUR_EYES"],
                 "changes": "whether retiring an Active pack or archiving an Active earning classification needs a "
                            "second Super Admin", "needs": None},
        "D-28": {"kind": "PARTS", "target": "governance",
                 "options": {k: ["SINGLE", "FOUR_EYES", "FOUR_EYES_WHEN_LIVE"]
                             for k in ("EMPLOYER_VERSION", "ESTABLISHMENT", "IMSS_REGISTRATION", "INFONAVIT_MODEL",
                                       "LABOR_POLICY_ACTIVATION", "CREDENTIAL")},
                 "changes": "per organisation-side item, whether a second org admin confirms the change "
                            "(FOUR_EYES_WHEN_LIVE: only once the organisation has a payroll run APPROVED or beyond "
                            "— the brief does not define 'live'; that is the reading used)",
                 "needs": "effective dating of establishments and the INFONAVIT model is not built (a data-model "
                          "change, not a switch)"},
        "C4": {"kind": "ENUM", "target": "switch", "options": ["LFT_84_INTEGRATED", "IMSS_SBC", "OPERATOR_ENTERED"],
               "changes": "the CFDI SalarioDiarioIntegrado source (the same three readings as D-12)",
               "needs": "OPERATOR_ENTERED: each worker's SDI with its evidence on the Mexican profile (VALUE)"},
        "C5": {"kind": "RECORD", "target": "record", "options": None,
               "changes": "nothing here: the SAT codes are proposed and approved per concept in CFDI system concepts",
               "needs": "the SAT code of INFONAVIT_CREDIT, VACATION_PAYOUT, ANNUAL_ADJUSTMENT_REFUND (VALUE, S28)"},
        "C12": {"kind": "ENUM", "target": "switch", "options": ["OMIT", "FROM_PROFILE"],
                "changes": "whether the CFDI carries Sindicalizado (from the worker's Mexican profile)",
                "needs": "FROM_PROFILE: union membership recorded on each worker's profile (data)"},
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


def threshold(code: str, raw: str) -> dict:
    """D-24 / D-25 (sweep S1): `[SCOPE=]AMOUNT:x` or `[SCOPE=]PERCENT:y` pieces
    separated by ';' (a bare number is AMOUNT:x). A scope's own pieces replace
    the default for it; within a scope, any piece exceeded counts."""
    rules = {"default": [], "scoped": {}, "raw": raw}
    for piece in [p.strip() for p in (raw or "").split(";") if p.strip()]:
        scope, _, rule = piece.rpartition("=")
        kind, _, number = rule.rpartition(":")
        kind = (kind or "AMOUNT").strip().upper()
        try:
            value = Decimal(number.strip())
        except (InvalidOperation, ValueError):
            value = None
        if kind not in ("AMOUNT", "PERCENT") or value is None or not value.is_finite() or value < 0:
            raise BadRequestException(f"{code}: {piece!r} — write AMOUNT:<MXN> or PERCENT:<0-100>, optionally "
                                      f"prefixed by SCOPE=, separated by ';' (a bare number is an MXN amount)")
        target = rules["scoped"].setdefault(scope.strip().upper(), []) if scope.strip() else rules["default"]
        target.append((kind, value))
    if not rules["default"] and not rules["scoped"]:
        raise BadRequestException(f"{code}: no threshold given")
    return rules


def exceeds(rules: dict, delta, base, scope: str, strict: bool) -> Optional[bool]:
    """Is |delta| over the threshold for `scope`? None when no rule covers it.
    PERCENT is of |base|; a difference against a zero base is over any percentage."""
    pieces = rules["scoped"].get(str(scope or "").upper(), rules["default"])
    if not pieces:
        return None
    size = abs(Decimal(str(delta)))
    for kind, value in pieces:
        if kind == "AMOUNT" and (size > value if strict else size >= value):
            return True
        if kind == "PERCENT":
            base_size = abs(Decimal(str(base or 0)))
            if base_size == 0 and size > 0:
                return True
            if base_size:
                pct = size * 100 / base_size
                if pct > value if strict else pct >= value:
                    return True
    return False


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
    if kind == "THRESHOLD":
        return threshold(code, raw)
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
