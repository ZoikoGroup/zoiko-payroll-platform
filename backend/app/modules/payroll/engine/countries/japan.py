"""Japan (ZP-JP-ENG-001) monthly salary engine - pure and fail-closed."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import japan_content as content
from app.modules.payroll.engine.jurisdictions.japan import employment_insurance as _ei
from app.modules.payroll.engine.jurisdictions.japan import resident_tax as _resident_tax
from app.modules.payroll.engine.jurisdictions.japan import social_insurance as _si
from app.modules.payroll.engine.jurisdictions.japan import withholding as _wht
from app.modules.payroll.engine.jurisdictions.japan.errors import JapanCalculationBlockedError

_COUNTRY = "JP"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
PENDING = "PENDING_G1"
RESIDENT = "RESIDENT"
ACTIVE = "ACTIVE"
TREATMENT_INCLUDED = "INCLUDED"
TREATMENT_EXCLUDED = "EXCLUDED"
TREATMENT_BONUS = "BONUS_PATH"
TREATMENT_REVIEW = "REVIEW"
_MODES = {
    "DOWN": ROUND_DOWN,
    "ROUND_DOWN": ROUND_DOWN,
    "UP": ROUND_UP,
    "ROUND_UP": ROUND_UP,
    "CEILING": ROUND_CEILING,
    "FLOOR": ROUND_FLOOR,
    "HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "HALF_EVEN": ROUND_HALF_EVEN,
    "BANKERS": ROUND_HALF_EVEN,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
}

JPCalculationBlockedError = JapanCalculationBlockedError


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _upper(value) -> str:
    return "" if value is None else str(value).strip().upper()


def _as_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _field(value, name):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _fact(ctx, profile, name):
    value = getattr(ctx, name, None)
    if value is None or value == "":
        value = _field(profile, name)
    return value


class _Pack:
    def __init__(self, rate_map: dict, organization_id, as_of=None):
        self.rate_map = rate_map or {}
        self.organization_id = organization_id
        self.as_of = as_of

    def block(self, key: str, reason: str):
        raise JPCalculationBlockedError(key, reason, self.organization_id)

    def in_force(self, row, as_of=None) -> bool:
        if row is None:
            return False
        as_of = as_of or self.as_of
        if as_of is None:
            return True
        start = _as_date(_field(row, "effective_from"))
        end = _as_date(_field(row, "effective_to"))
        return (start is None or start <= as_of) and (end is None or end >= as_of)

    def row(self, key: str, as_of=None, required=True):
        row = self.rate_map.get(key)
        if row is None or not self.in_force(row, as_of):
            if required:
                self.block(key, "no configured parameter row is in force for the pay date")
            return None
        return row

    def _row(self, key: str, as_of=None):
        return self.row(key, as_of=as_of)

    def require_amount(self, key: str, as_of=None) -> Decimal:
        value = _field(self.row(key, as_of=as_of), "flat_amount")
        if value is None:
            self.block(key, "row has no amount configured")
        return _dec(value)

    def require_pct_total(self, key: str, as_of=None) -> Decimal:
        value = _field(self.row(key, as_of=as_of), "flat_amount")
        if value is None:
            self.block(key, "row has no total percentage configured")
        return _dec(value)

    def require_pct(self, key: str, side: str, as_of=None) -> Decimal:
        attr = "employee_rate_pct" if side == "employee" else "employer_rate_pct"
        value = _field(self.row(key, as_of=as_of), attr)
        if value is None:
            self.block(key, f"row has no {side} rate configured")
        return _dec(value)

    def require_pair(self, key: str, as_of=None):
        row = self.row(key, as_of=as_of)
        employee = _field(row, "employee_rate_pct")
        employer = _field(row, "employer_rate_pct")
        if employee is None or employer is None:
            self.block(key, "employee / employer rate pair is not configured")
        return _dec(employee), _dec(employer)

    def require_text(self, key: str, allowed=None, as_of=None) -> str:
        value = _upper(_field(self.row(key, as_of=as_of), "text_value"))
        if not value:
            self.block(key, "row has no value configured")
        if allowed is not None and value not in allowed:
            self.block(key, f"{value!r} is not one of {', '.join(allowed)}")
        return value

    def rounder(self, key: str, as_of=None):
        row = self.row(key, as_of=as_of)
        text = _upper(_field(row, "text_value"))
        if not text or text == PENDING:
            self.block(key, "rounding is PENDING_G1")
        unit = Decimal("1")
        mode_name = text
        if text.startswith("DOWN_") and text[5:].isdigit():
            unit = Decimal(text[5:])
            mode_name = "DOWN"
        mode = _MODES.get(mode_name)
        if mode is None:
            self.block(key, f"unsupported rounding rule {text!r}")
        return lambda value: (value / unit).quantize(Decimal("1"), rounding=mode) * unit


JPPack = _Pack


def _status_active(obj, key, pack, pay_date):
    status = _upper(_field(obj, "status"))
    if status and status != ACTIVE:
        pack.block(key, f"row is {status}, not ACTIVE")
    start = _as_date(_field(obj, "effective_from"))
    end = _as_date(_field(obj, "effective_to"))
    if start is not None and start > pay_date:
        pack.block(key, "row is not yet effective on the pay date")
    if end is not None and end < pay_date:
        pack.block(key, "row has expired before the pay date")


def resolve_applicability(ctx: PayrollContext, pack: _Pack) -> dict:
    if ctx.pay_date is None:
        pack.block("pay_date", "payment date is a first-class rule-pack key")
    supported = [part.strip().upper() for part in
                 pack.require_text("jp_supported_pay_frequencies").split(",") if part.strip()]
    frequency = _upper(ctx.pay_frequency)
    if frequency not in supported:
        pack.block("pay_frequency",
                   f"{ctx.pay_frequency!r} pay is not certified (supported: {', '.join(supported)})")

    currency = _upper(getattr(ctx, "currency", None))
    if currency and currency != content.CURRENCY:
        pack.block("currency", f"{currency!r} is not a JPY payroll")

    registration = getattr(ctx, "jp_employer_registration", None)
    if registration is None:
        pack.block("jp_employer_registration", "no Japan employer registration is in force")
    _status_active(registration, "jp_employer_registration", pack, ctx.pay_date)

    profile = getattr(ctx, "jp_worker_tax_profile", None)
    if profile is None:
        pack.block("jp_worker_tax_profile", "no Japan worker tax profile is in force")
    _status_active(profile, "jp_worker_tax_profile", pack, ctx.pay_date)
    residency = _upper(_field(profile, "residency_status"))
    if not residency:
        pack.block("jp_tax_residency", "tax residency is not recorded")
    if residency != RESIDENT:
        pack.block("JP_NON_RESIDENT_UNSUPPORTED",
                   f"tax residency {residency!r} is outside the certified resident cohort")
    declaration = _upper(_field(profile, "declaration_class"))
    if declaration not in content.DECLARATION_CLASSES:
        pack.block("jp_declaration_class",
                   f"declaration class {declaration!r} is not PRIMARY or SECONDARY")
    dependants = _field(profile, "dependants_count")
    if dependants is None:
        dependants = 0
    if not isinstance(dependants, int) or dependants < 0:
        pack.block("jp_dependants_count", f"dependant count {dependants!r} is not a whole number")

    enrollment = getattr(ctx, "jp_social_insurance_enrollment", None)
    if enrollment is None:
        pack.block("jp_social_insurance_enrollment", "no social-insurance enrollment is in force")
    _status_active(enrollment, "jp_social_insurance_enrollment", pack, ctx.pay_date)

    ei_profile = getattr(ctx, "jp_employment_insurance_profile", None)
    if ei_profile is None:
        pack.block("jp_employment_insurance_profile", "no employment-insurance profile is in force")
    _status_active(ei_profile, "jp_employment_insurance_profile", pack, ctx.pay_date)

    return {"frequency": frequency, "residency": residency, "declarationClass": declaration,
            "dependants": dependants, "registration": registration, "profile": profile,
            "enrollment": enrollment, "eiProfile": ei_profile}


def _classes(slabs) -> dict:
    out = {}
    for row in slabs or []:
        if _upper(_field(row, "rule_type")) != content.JP_EARNING_CLASS_RULE:
            continue
        out[(_upper(_field(row, "tax_regime")), _upper(_field(row, "filing_status")))] = \
            _upper(_field(row, "assessment_basis"))
    return out


def pay_components(ctx: PayrollContext, pack: _Pack) -> list:
    named = {_upper(key): _dec(value) for key, value in
             (getattr(ctx, "jp_components", None) or {}).items()}
    unknown = sorted(set(named) - set(content.JP_COMPONENTS))
    if unknown:
        pack.block("jp_components", f"unknown pay component(s) {', '.join(unknown)}")
    amounts = [
        ("SALARY", named.get("SALARY", _dec(ctx.basic))),
        ("OVERTIME", named.get("OVERTIME", _dec(ctx.overtime))),
    ]
    amounts.extend((name, named.get(name, ZERO))
                   for name in ("ALLOWANCE", "COMMUTING_ALLOWANCE", "BONUS"))
    other = named.get("OTHER_EARNINGS")
    if other is None:
        other = _dec(ctx.gross) - sum((amount for _name, amount in amounts), ZERO)
    if other < ZERO:
        pack.block("jp_components", f"the pay components exceed gross by {-other}")
    amounts.append(("OTHER_EARNINGS", other))
    for name, amount in amounts:
        if amount < ZERO:
            pack.block("jp_components", f"pay component {name} is negative ({amount})")
    return [(name, amount) for name, amount in amounts if amount > ZERO]


def obligation_base(obligation: str, components: list, classes: dict, pack: _Pack) -> dict:
    base = ZERO
    lines = []
    for component, amount in components:
        treatment = classes.get((obligation, component))
        if treatment is None:
            pack.block(f"jp_earning_class:{obligation}:{component}",
                       f"pay component {component} ({amount}) has no {obligation} classification")
        if treatment == TREATMENT_REVIEW:
            if amount != ZERO:
                pack.block(f"jp_earning_class:{obligation}:{component}",
                           f"pay component {component} ({amount}) is REVIEW for {obligation}")
            counted = ZERO
        elif treatment == TREATMENT_BONUS:
            if amount != ZERO:
                pack.block("JP_BONUS_PATH_PENDING_P4",
                           f"pay component {component} requires the bonus path (P4)")
            counted = ZERO
        elif treatment == TREATMENT_INCLUDED:
            counted = amount
        elif treatment == TREATMENT_EXCLUDED:
            counted = ZERO
        else:
            pack.block(f"jp_earning_class:{obligation}:{component}",
                       f"treatment {treatment!r} is not valid for {obligation}")
        base += counted
        lines.append({"component": component, "amount": str(amount),
                      "treatment": treatment, "counted": str(counted)})
    return {"base": base, "lines": lines}


def _row_ref(row):
    if row is None:
        return None
    data = {}
    for name in ("id", "rule_type", "component_key", "tax_column", "tax_table_number",
                 "filing_status", "tax_regime", "jurisdiction_state", "min_amount", "max_amount",
                 "flat_amount", "rate_pct", "formula_expression", "effective_from", "effective_to"):
        value = _field(row, name)
        if value is not None:
            data[name] = value.isoformat() if isinstance(value, date) else str(value)
    return data


def calculate(ctx: PayrollContext) -> dict:
    org_id = getattr(ctx, "jp_organization_id", None) or getattr(ctx, "organization_id", None)
    pack = _Pack(getattr(ctx, "rate_map", {}) or {}, org_id, as_of=ctx.pay_date)
    applicability = resolve_applicability(ctx, pack)
    named_bonus = _dec(next((value for key, value in
                             (getattr(ctx, "jp_components", None) or {}).items()
                             if _upper(key) == "BONUS"), ZERO))
    if named_bonus != ZERO:
        pack.block("JP_BONUS_PATH_PENDING_P4",
                   f"bonus amount {named_bonus} belongs to the P4 bonus path")
    components = pay_components(ctx, pack)
    bonus = next(((name, amount) for name, amount in components if name == "BONUS"), None)
    if bonus is not None:
        pack.block("JP_BONUS_PATH_PENDING_P4",
                   f"bonus amount {bonus[1]} belongs to the P4 bonus path")

    classes = _classes(getattr(ctx, "slabs", None))
    bases = {name: obligation_base(name, components, classes, pack)
             for name in ("WHT", "SI", "EI")}

    date_of_birth = getattr(ctx, "jp_date_of_birth", None) or getattr(ctx, "date_of_birth", None)
    si = _si.monthly_contributions(
        applicability["enrollment"], applicability["registration"], pack, as_of=ctx.pay_date,
        date_of_birth=date_of_birth, slabs=getattr(ctx, "slabs", None))
    ei = _ei.monthly_employment_insurance(
        applicability["eiProfile"], bases["EI"]["base"], pack, as_of=ctx.pay_date)

    wht_base = bases["WHT"]["base"] - si.employee_total - ei.employee
    if wht_base < ZERO:
        pack.block("jp_wht_base",
                   f"the withholding base is negative ({wht_base}) after social insurance")
    method = pack.require_text("jp_withholding_method",
                               allowed=content.WITHHOLDING_METHODS)
    wht = _wht.monthly_withholding(
        wht_base, applicability["declarationClass"], applicability["dependants"], method,
        getattr(ctx, "slabs", None), pack)

    resident = _resident_tax.resident_tax_for_month(
        getattr(ctx, "jp_resident_tax_assessments", None), ctx.pay_date,
        collection=_field(applicability["profile"], "resident_tax_collection") or "SPECIAL")

    jp_employee_total = si.employee_total + ei.employee + resident.amount
    net = _dec(ctx.gross) - wht.tax - jp_employee_total
    if net < ZERO:
        pack.block("JP_NEGATIVE_NET",
                   f"net pay would be negative ({net}) after statutory deductions")

    rounding_events = list(wht.rounding_events) + list(si.trace.get("roundingEvents") or []) \
        + list(ei.trace.get("roundingEvents") or [])
    trace = {
        "jurisdiction": _COUNTRY,
        "payDate": ctx.pay_date.isoformat(),
        "payFrequency": applicability["frequency"],
        "residency": applicability["residency"],
        "table_pack_id": content.JP_2026[0],
        "tablePackId": content.JP_2026[0],
        "method": method,
        "declarationClass": applicability["declarationClass"],
        "dependants": applicability["dependants"],
        "bases": {name: {"base": str(value["base"]), "lines": value["lines"]}
                  for name, value in bases.items()},
        "withholding": {"branch": wht.branch, "row": _row_ref(wht.row),
                        "roundingEvents": wht.rounding_events},
        "socialInsurance": si.trace,
        "employmentInsurance": ei.trace,
        "residentTax": resident.trace,
        "roundingEvents": rounding_events,
        "rateRowsUsed": {
            "withholding": _row_ref(wht.row),
            "health": si.trace.get("healthRate"),
            "employmentInsurance": _row_ref(ei.rate_row),
        },
        "rateKeys": sorted((getattr(ctx, "rate_map", None) or {}).keys()),
    }

    return {
        "tds": wht.tax,
        "jp_employee_total": jp_employee_total,
        "jp_result": {
            "jp_wht": str(wht.tax),
            "jp_wht_base": str(wht_base),
            "jp_wht_branch": wht.branch,
            "jp_declaration_class": applicability["declarationClass"],
            "jp_dependants": applicability["dependants"],
            "jp_epi_employee": str(si.epi_employee),
            "jp_epi_employer": str(si.epi_employer),
            "jp_health_employee": str(si.health_employee),
            "jp_health_employer": str(si.health_employer),
            "jp_care_employee": str(si.care_employee),
            "jp_care_employer": str(si.care_employer),
            "jp_child_support_employee": str(si.child_support_employee),
            "jp_child_support_employer": str(si.child_support_employer),
            "jp_si_employee_total": str(si.employee_total),
            "jp_si_employer_total": str(si.employer_total),
            "jp_ei_employee": str(ei.employee),
            "jp_ei_employer": str(ei.employer),
            "jp_ei_base": str(bases["EI"]["base"]),
            "jp_smr_health": str(si.smr_health),
            "jp_smr_pension": str(si.smr_pension),
            "jp_resident_tax": str(resident.amount),
            "jp_resident_tax_notice": {
                "municipality": resident.municipality,
                "noticeYear": resident.notice_year,
                "version": resident.version,
            },
            "jp_employee_total": str(jp_employee_total),
            "jp_employer_total": str(si.employer_total + ei.employer),
            "trace": trace,
        },
    }
