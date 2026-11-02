"""Japan (ZP-JP-ENG-001) monthly salary engine - pure and fail-closed."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import japan_content as content
from app.modules.payroll.engine.jurisdictions.japan import bonus as _bonus
from app.modules.payroll.engine.jurisdictions.japan import employment_insurance as _ei
from app.modules.payroll.engine.jurisdictions.japan import labour as _labour
from app.modules.payroll.engine.jurisdictions.japan import resident_tax as _resident_tax
from app.modules.payroll.engine.jurisdictions.japan import smr_lifecycle as _lifecycle
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
            # The bonus itself never reaches a monthly base (calculate() takes
            # it out first); any other component routed here is misconfigured.
            if amount != ZERO:
                pack.block(f"jp_earning_class:{obligation}:{component}",
                           f"only BONUS may use the bonus path, not {component}")
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


def _labour_check(ctx: PayrollContext, pack: _Pack, salary_components: list) -> dict:
    """Working time, premium floor and minimum wage for a salary payment.

    The facts come only from the active work-conditions row, the approved
    attendance hours and the signed prefectural minimum-wage row. A missing
    fact blocks; nothing is inferred from gross pay.
    """
    conditions = getattr(ctx, "jp_work_conditions", None)
    if conditions is None:
        pack.block("jp_work_conditions", "no Japan work conditions are in force")
    _status_active(conditions, "jp_work_conditions", pack, ctx.pay_date)

    system = _upper(_field(conditions, "working_time_system"))
    if system != "STANDARD":
        pack.block("jp_working_time_system", f"working-time system {system!r} is not certified")
    week_start = _field(conditions, "week_start_day")
    if not isinstance(week_start, int) or not 0 <= week_start <= 6:
        pack.block("jp_week_start_day", f"week start {week_start!r} is not 0..6")
    prefecture = _upper(_field(conditions, "workplace_prefecture"))
    if not prefecture:
        pack.block("jp_workplace_prefecture", "the workplace prefecture is not recorded")
    scheduled_monthly = _field(conditions, "scheduled_monthly_hours")
    scheduled_daily = _field(conditions, "scheduled_daily_minutes")
    if scheduled_daily is None or int(scheduled_daily) <= 0:
        pack.block("jp_scheduled_daily_minutes", "scheduled daily minutes are not configured")

    daily_hours = pack.require_amount("jp_statutory_hours_per_day")
    weekly_hours = pack.require_amount("jp_statutory_hours_per_week")
    threshold_hours = pack.require_amount("jp_overtime_60h_threshold_hours")
    if min(daily_hours, weekly_hours, threshold_hours) <= ZERO:
        pack.block("jp_statutory_hours", "statutory hour baselines must be positive")
    window = pack.require_text("jp_night_window")
    window_parts = window.split("-", 1)
    if len(window_parts) != 2 or not all(part.strip() for part in window_parts):
        pack.block("jp_night_window", f"night window {window!r} is not HH:MM-HH:MM")
    window_start, window_end = (part.strip() for part in window_parts)
    rates = {
        "within_schedule": pack.require_pct_total("jp_overtime_premium_pct") / 100,
        "statutory": pack.require_pct_total("jp_overtime_premium_pct") / 100,
        "over60": pack.require_pct_total("jp_overtime_over_60h_premium_pct") / 100,
        "holiday": pack.require_pct_total("jp_statutory_holiday_premium_pct") / 100,
        "night": pack.require_pct_total("jp_night_premium_pct") / 100,
    }

    salary_base = sum((amount for name, amount in salary_components if name == "SALARY"), ZERO)
    try:
        hourly = _labour.premium_base_hourly(salary_base, scheduled_monthly)
    except _labour.JapanLabourBlockedError as exc:
        pack.block(exc.key, exc.reason)

    min_row = None
    try:
        min_row = _labour.minimum_wage_row(
            getattr(ctx, "slabs", None), prefecture, ctx.pay_date)
        minimum = _labour.minimum_wage_check(
            hourly, None if min_row is None else _field(min_row, "flat_amount"), prefecture)
    except _labour.JapanLabourBlockedError as exc:
        pack.block(exc.key, exc.reason)

    days = getattr(ctx, "jp_hours", None) or []
    approved = bool(getattr(ctx, "jp_hours_approved", None))
    if days and not approved:
        pack.block("jp_hours_approved",
                   "attendance hours for this period are not approved facts")
    prepared = []
    for raw in days:
        if isinstance(raw, dict):
            row = dict(raw)
            if "night_minutes" not in row and (row.get("check_in") or row.get("check_out")):
                row["night_minutes"] = _labour.night_minutes(
                    row.get("check_in"), row.get("check_out"), window_start, window_end)
            prepared.append(row)
        else:
            prepared.append(raw)
    try:
        breakdown = _labour.classify_hours(
            prepared, week_start, daily_minutes=int(daily_hours * 60),
            weekly_minutes=int(weekly_hours * 60),
            over60_minutes=int(threshold_hours * 60))
    except _labour.JapanLabourBlockedError as exc:
        pack.block(exc.key, exc.reason)

    paid_premium = sum((amount for name, amount in salary_components if name == "OVERTIME"), ZERO)
    if paid_premium and not days:
        pack.block("jp_hours_approved",
                   "overtime is paid but no approved attendance hours are supplied")
    if breakdown.total_overtime_minutes and not approved:
        pack.block("jp_hours_approved",
                   "the attendance hours contain overtime that is not approved")
    categories = (
        bool(breakdown.within_schedule_extra_minutes or breakdown.statutory_overtime_minutes
             or breakdown.over_60_minutes),
        bool(breakdown.statutory_holiday_minutes),
        bool(breakdown.night_minutes),
    )
    if sum(categories) > 1:
        pack.block("jp_premium_combination_rule",
                   "overtime, holiday and night premiums combine but the signed "
                   "combination rule is not configured")
    try:
        floor = _labour.premium_floor(hourly, breakdown, rates)
        _labour.check_premium(paid_premium, floor)
    except _labour.JapanLabourBlockedError as exc:
        pack.block(exc.key, exc.reason)

    return {
        "prefecture": prefecture,
        "weekStartDay": week_start,
        "scheduledDailyMinutes": int(scheduled_daily),
        "scheduledMonthlyHours": str(scheduled_monthly),
        "hourlyBase": str(hourly),
        "minimumWage": str(minimum),
        "minimumWageRow": _row_ref(min_row),
        "statutoryLimits": {
            "dailyMinutes": int(daily_hours * 60),
            "weeklyMinutes": int(weekly_hours * 60),
            "over60Minutes": int(threshold_hours * 60),
        },
        "premiumRates": {key: str(value) for key, value in rates.items()},
        "nightWindow": window,
        "hours": breakdown.as_dict(),
        "premiumPaid": str(paid_premium),
        "premiumFloor": str(floor),
        "hoursApproved": approved,
    }


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


PAYMENT_SALARY = "SALARY"
PAYMENT_BONUS = "BONUS"
PAYMENT_KINDS = (PAYMENT_SALARY, PAYMENT_BONUS)
# Treatments the bonus path supports for each obligation. WHT and SI always
# take the bonus path; EI charges the bonus itself once its class is signed.
_BONUS_TREATMENTS = {
    "WHT": (TREATMENT_BONUS,),
    "SI": (TREATMENT_BONUS,),
    "EI": (TREATMENT_INCLUDED, TREATMENT_EXCLUDED),
}


def _bonus_treatments(classes: dict, pack: _Pack) -> dict:
    out = {}
    for obligation, allowed in _BONUS_TREATMENTS.items():
        treatment = classes.get((obligation, "BONUS"))
        if treatment not in allowed:
            pack.block(f"jp_earning_class:{obligation}:BONUS",
                       f"bonus treatment {treatment!r} is not supported for {obligation}")
        out[obligation] = treatment
    return out


def _bonus_payment(ctx: PayrollContext, applicability: dict, classes: dict, pack: _Pack,
                   amount: Decimal, date_of_birth) -> dict:
    """Social insurance, employment insurance and withholding on a bonus
    (S1/S8), each on its own base and with its own trace."""
    treatments = _bonus_treatments(classes, pack)
    enrollment = applicability["enrollment"]
    si = _si.bonus_contributions(
        amount, enrollment, applicability["registration"], pack, as_of=ctx.pay_date,
        date_of_birth=date_of_birth, slabs=getattr(ctx, "slabs", None),
        ytd_health_sba=getattr(ctx, "jp_ytd_health_sba", None),
        month_pension_sba=getattr(ctx, "jp_month_pension_sba", None))
    if treatments["EI"] == TREATMENT_INCLUDED:
        ei = _ei.monthly_employment_insurance(applicability["eiProfile"], amount, pack,
                                              as_of=ctx.pay_date)
    else:
        ei = _ei.EIResult(employee=ZERO, employer=ZERO, rate_row=None,
                          trace={"treatment": TREATMENT_EXCLUDED, "roundingEvents": []})
    wht_base = amount - si.employee_total - ei.employee
    wht = _bonus.bonus_withholding(
        wht_base, getattr(ctx, "jp_prior_month_pay_after_si", None),
        applicability["declarationClass"], applicability["dependants"],
        getattr(ctx, "slabs", None), pack, as_of=ctx.pay_date)
    insured = (_field(enrollment, "health_eligible") is True
               or _field(enrollment, "pension_eligible") is True)
    report_due = _bonus.bonus_report_due(ctx.pay_date, pack) if insured else None
    return {"amount": amount, "si": si, "ei": ei, "whtBase": wht_base, "wht": wht,
            "reportDue": report_due, "treatments": treatments}


def _no_monthly_obligations():
    """A bonus-only payment: the monthly SMR contributions, monthly withholding
    and resident tax belong to the salary payment of the month, never here."""
    skipped = {"skipped": "bonus payment", "roundingEvents": []}
    si = _si.SIResult(epi_employee=ZERO, epi_employer=ZERO, health_employee=ZERO,
                      health_employer=ZERO, care_employee=ZERO, care_employer=ZERO,
                      child_support_employee=ZERO, child_support_employer=ZERO,
                      employee_total=ZERO, employer_total=ZERO, smr=ZERO, smr_health=ZERO,
                      smr_pension=ZERO, trace=dict(skipped))
    ei = _ei.EIResult(employee=ZERO, employer=ZERO, rate_row=None, trace=dict(skipped))
    wht = _wht.WithholdingResult(tax=ZERO, branch="NONE", row=None, rounding_events=[])
    resident = _resident_tax.RTResult(amount=ZERO, municipality=None, notice_year=None,
                                      version=None, notice_id=None, trace=dict(skipped))
    return si, ei, wht, resident


def calculate(ctx: PayrollContext) -> dict:
    org_id = getattr(ctx, "jp_organization_id", None) or getattr(ctx, "organization_id", None)
    pack = _Pack(getattr(ctx, "rate_map", {}) or {}, org_id, as_of=ctx.pay_date)
    applicability = resolve_applicability(ctx, pack)
    payment_kind = _upper(getattr(ctx, "jp_payment_kind", None)) or PAYMENT_SALARY
    if payment_kind not in PAYMENT_KINDS:
        pack.block("jp_payment_kind", f"payment kind {payment_kind!r} is not SALARY or BONUS")

    components = pay_components(ctx, pack)
    bonus_amount = sum((amount for name, amount in components if name == "BONUS"), ZERO)
    salary_components = [(name, amount) for name, amount in components if name != "BONUS"]
    if payment_kind == PAYMENT_BONUS:
        if salary_components:
            pack.block("jp_payment_kind",
                       "a bonus payment carries salary components "
                       f"({', '.join(name for name, _amount in salary_components)})")
        if bonus_amount == ZERO:
            pack.block("jp_payment_kind", "a bonus payment has no bonus amount")

    exemptions = _lifecycle.exemption_events_in_month(
        getattr(ctx, "jp_social_insurance_events", None), ctx.pay_date)
    if exemptions:
        # Maternity / childcare exemptions waive both shares by month; the
        # month rules are not certified, so the case is never charged or
        # waived by assumption.
        pack.block("JP_SI_EXEMPTION_PENDING",
                   f"a social-insurance exemption event ({', '.join(exemptions)}) covers the pay month")

    classes = _classes(getattr(ctx, "slabs", None))
    bases = {name: obligation_base(name, salary_components, classes, pack)
             for name in ("WHT", "SI", "EI")}

    date_of_birth = getattr(ctx, "jp_date_of_birth", None) or getattr(ctx, "date_of_birth", None)
    method = None
    labour_trace = None
    if payment_kind == PAYMENT_SALARY:
        labour_trace = _labour_check(ctx, pack, salary_components)
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
    else:
        si, ei, wht, resident = _no_monthly_obligations()
        wht_base = ZERO

    bonus = None
    if bonus_amount > ZERO:
        bonus = _bonus_payment(ctx, applicability, classes, pack, bonus_amount, date_of_birth)

    bonus_si_employee = bonus["si"].employee_total if bonus else ZERO
    bonus_si_employer = bonus["si"].employer_total if bonus else ZERO
    bonus_ei_employee = bonus["ei"].employee if bonus else ZERO
    bonus_ei_employer = bonus["ei"].employer if bonus else ZERO
    bonus_wht = bonus["wht"].tax if bonus else ZERO

    tds = wht.tax + bonus_wht
    jp_employee_total = (si.employee_total + ei.employee + resident.amount
                         + bonus_si_employee + bonus_ei_employee)
    jp_employer_total = si.employer_total + ei.employer + bonus_si_employer + bonus_ei_employer
    net = _dec(ctx.gross) - tds - jp_employee_total
    if net < ZERO:
        pack.block("JP_NEGATIVE_NET",
                   f"net pay would be negative ({net}) after statutory deductions")

    rounding_events = list(wht.rounding_events) + list(si.trace.get("roundingEvents") or []) \
        + list(ei.trace.get("roundingEvents") or [])
    bonus_trace = None
    bonus_result = None
    if bonus:
        rounding_events += list(bonus["si"].trace.get("roundingEvents") or []) \
            + list(bonus["ei"].trace.get("roundingEvents") or []) \
            + list(bonus["wht"].rounding_events)
        bonus_trace = {
            "amount": str(bonus["amount"]),
            "treatments": bonus["treatments"],
            "priorMonthPayAfterSi": str(_dec(getattr(ctx, "jp_prior_month_pay_after_si", None))),
            "socialInsurance": bonus["si"].trace,
            "employmentInsurance": bonus["ei"].trace,
            "withholding": {"base": str(bonus["whtBase"]),
                            "ratePct": str(bonus["wht"].rate_pct),
                            "row": _row_ref(bonus["wht"].row),
                            "roundingEvents": bonus["wht"].rounding_events},
            "reportDue": bonus["reportDue"].isoformat() if bonus["reportDue"] else None,
        }
        bsi = bonus["si"]
        bonus_result = {
            "jp_bonus": str(bonus["amount"]),
            "jp_bonus_sba": str(bsi.sba),
            "jp_bonus_health_sba_base": str(bsi.health_sba_base),
            "jp_bonus_pension_sba_base": str(bsi.pension_sba_base),
            "jp_bonus_epi_employee": str(bsi.epi_employee),
            "jp_bonus_epi_employer": str(bsi.epi_employer),
            "jp_bonus_health_employee": str(bsi.health_employee),
            "jp_bonus_health_employer": str(bsi.health_employer),
            "jp_bonus_care_employee": str(bsi.care_employee),
            "jp_bonus_care_employer": str(bsi.care_employer),
            "jp_bonus_child_support_employee": str(bsi.child_support_employee),
            "jp_bonus_child_support_employer": str(bsi.child_support_employer),
            "jp_bonus_si_employee_total": str(bsi.employee_total),
            "jp_bonus_si_employer_total": str(bsi.employer_total),
            "jp_bonus_ei_employee": str(bonus["ei"].employee),
            "jp_bonus_ei_employer": str(bonus["ei"].employer),
            "jp_bonus_wht_base": str(bonus["whtBase"]),
            "jp_bonus_wht_rate_pct": str(bonus["wht"].rate_pct),
            "jp_bonus_wht": str(bonus["wht"].tax),
            "jp_bonus_report_due": bonus["reportDue"].isoformat() if bonus["reportDue"] else None,
        }

    trace = {
        "jurisdiction": _COUNTRY,
        "payDate": ctx.pay_date.isoformat(),
        "payFrequency": applicability["frequency"],
        "paymentKind": payment_kind,
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
        "labour": labour_trace,
        "bonus": bonus_trace,
        "roundingEvents": rounding_events,
        "rateRowsUsed": {
            "withholding": _row_ref(wht.row),
            "bonusWithholding": _row_ref(bonus["wht"].row) if bonus else None,
            "health": si.trace.get("healthRate"),
            "employmentInsurance": _row_ref(ei.rate_row),
        },
        "rateKeys": sorted((getattr(ctx, "rate_map", None) or {}).keys()),
    }

    return {
        "tds": tds,
        "jp_employee_total": jp_employee_total,
        "jp_result": {
            "jp_payment_kind": payment_kind,
            "jp_wht": str(wht.tax),
            "jp_wht_base": str(wht_base),
            "jp_wht_branch": wht.branch,
            "jp_wht_total": str(tds),
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
            "jp_bonus": bonus_result,
            "jp_employee_total": str(jp_employee_total),
            "jp_employer_total": str(jp_employer_total),
            "trace": trace,
        },
    }
