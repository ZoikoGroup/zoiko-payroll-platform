"""Belgium pay components and independent bases (ZP-BE-ENG-001 BE-006 /
BE-007 / BE-008 / BE-009; Block A3). Pure.

* Every paid amount is one of the closed component codes
  (belgium_content.COMPONENTS); a free-text or unknown earning is refused
  (BE-008) and the components must add up to the platform gross.
* Each obligation's base is built ONLY from the signed earning-class matrix
  (BE_EARNING_CLASS rows: obligation x component -> INCLUDED / EXCLUDED /
  REVIEW). A paid component with no signed treatment, or a REVIEW treatment,
  blocks (BE-006). Bases are independent (BE-007): one never derives from
  another.
* Exceptional remuneration never feeds the regular withholding base
  (BE-011): a component INCLUDED in both blocks.
* The source period of arrears / corrections is kept separate from the pay
  date (BE-009) and travels in the trace and the ledger.
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.countries import belgium_content as content
from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium.pack import ZERO, BePack, as_date, dec, upper

# Obligations the engine builds a base for (others are not calculated in A3).
ENGINE_OBLIGATIONS = ("ONSS_EMPLOYEE", "ONSS_EMPLOYER", "ONSS_MANUAL_108", "WITHHOLDING_REGULAR",
                      "WITHHOLDING_EXCEPTIONAL", "HOLIDAY_BASE", "SECTOR_MIN_WAGE")
# Components whose amount relates to an earlier period (BE-009).
SOURCE_PERIOD_COMPONENTS = ("ARREARS",)
# The platform's own pay fields (PayrollContext attributes) a PLATFORM_FIELD
# mapping names; named policy allowances arrive as be_allowance_items (G-28).
PLATFORM_PAY_FIELDS = ("basic", "hra", "special_allowance", "overtime", "additional_compensation")


def _mapped_pay(ctx, pack: BePack) -> dict:
    """{BE component: amount} from the platform pay through the organisation's
    ACTIVE mappings (G-28). Any non-zero platform amount without a mapping
    blocks (BE-008) — nothing is assumed to be salary."""
    mappings = getattr(ctx, "be_component_mappings", None) or {}
    sources = [("PLATFORM_FIELD", name, getattr(ctx, name, None)) for name in PLATFORM_PAY_FIELDS]
    sources += [("POLICY_ALLOWANCE", str(i.get("key")), i.get("amount"))
                for i in (getattr(ctx, "be_allowance_items", None) or [])]
    pay: dict = {}
    for source, key, amount in sources:
        value = dec(amount)
        if value == ZERO:
            continue
        code = mappings.get(f"{source}:{key}")
        if code is None:
            pack.block(E.COMPONENT_UNMAPPED, f"{source}:{key}",
                       "this platform pay component has no ACTIVE Belgian component mapping (G-28, BE-008)")
        pay[code] = pay.get(code, ZERO) + value
    return pay


def components(ctx, pack: BePack) -> dict:
    """{component: Decimal} for this payslip, validated against gross."""
    gross = dec(getattr(ctx, "gross", None))
    raw = getattr(ctx, "be_components", None)        # explicit Belgian earning lines, when supplied
    if raw is None:
        raw = _mapped_pay(ctx, pack)
    pay: dict = {}
    for code, amount in raw.items():
        code = upper(code)
        if code not in content.COMPONENTS:
            pack.block(E.COMPONENT_UNKNOWN, code or "BLANK", "free-text or unknown earnings are refused (BE-008)")
        value = dec(amount)
        if value < ZERO:
            pack.block(E.COMPONENT_UNKNOWN, code, "a negative earning is a correction, not a pay component")
        pay[code] = pay.get(code, ZERO) + value
    if sum(pay.values(), ZERO) != gross:
        pack.block(E.COMPONENTS_MISMATCH, "gross", "the Belgian pay components do not add up to gross pay")
    if pay.get("BENEFIT_IN_KIND", ZERO) != ZERO:
        pack.block(E.BENEFIT_IN_KIND_UNSUPPORTED, "BENEFIT_IN_KIND",
                   "benefits in kind (company car and other BIK valuation) are not calculated in release 1 (G-27)")
    periods = getattr(ctx, "be_source_periods", None) or {}
    for code in SOURCE_PERIOD_COMPONENTS:
        if pay.get(code, ZERO) != ZERO:
            period = periods.get(code) or {}
            start, end = as_date(period.get("start")), as_date(period.get("end"))
            if start is None or end is None or end < start:
                pack.block(E.SOURCE_PERIOD_MISSING, code, "arrears need the period they relate to (BE-009)")
    return pay


def build(pay: dict, classes: dict, pack: BePack, manual: bool) -> dict:
    """{"bases": {obligation: Decimal}, "detail": {obligation: [components]}}."""
    obligations = [o for o in ENGINE_OBLIGATIONS if manual or o != "ONSS_MANUAL_108"]
    bases, detail = {}, {}
    for obligation in obligations:
        total, included = ZERO, []
        for code, amount in sorted(pay.items()):
            if amount == ZERO:
                continue
            treatment = classes.get((obligation, code))
            if treatment is None:
                pack.block(E.EARNING_CLASS_MISSING, f"{obligation}:{code}",
                           "no signed earning classification for this component and obligation (BE-006)")
            if treatment == "REVIEW":
                pack.block(E.EARNING_CLASS_REVIEW, f"{obligation}:{code}",
                           "the earning classification is REVIEW: a specialist must decide it (BE-006)")
            if treatment == "INCLUDED":
                total += amount
                included.append(code)
        bases[obligation], detail[obligation] = total, included
    both = set(detail["WITHHOLDING_REGULAR"]) & set(detail["WITHHOLDING_EXCEPTIONAL"])
    if both:
        pack.block(E.EARNING_CLASS_CONFLICT, ",".join(sorted(both)),
                   "exceptional remuneration can never also be in the regular withholding base (BE-011)")
    return {"bases": bases, "detail": detail}


def source_periods(ctx, pay: dict) -> dict:
    periods = getattr(ctx, "be_source_periods", None) or {}
    out = {}
    for code in sorted(pay):
        period = periods.get(code)
        if period:
            out[code] = {"start": str(as_date(period.get("start"))), "end": str(as_date(period.get("end")))}
    return out


def trace(built: dict) -> dict:
    return {o: {"amount": str(Decimal(v)), "components": built["detail"][o]} for o, v in built["bases"].items()}
