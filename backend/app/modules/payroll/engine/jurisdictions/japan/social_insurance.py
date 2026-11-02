"""Japan social-insurance contributions (ZP-JP-ENG-001, JP-009/JP-010)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP

from app.modules.payroll.engine.jurisdictions.japan.errors import JapanCalculationBlockedError

ZERO = Decimal("0")
HUNDRED = Decimal("100")
PENDING = "PENDING_G1"
_RULE_HEALTH = "JP_HEALTH_RATE"
_RULE_SMR = "JP_SMR_GRADE"
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


class SIResult(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _field(value, name):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _upper(value):
    return "" if value is None else str(value).strip().upper()


def _as_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _block(pack, key: str, reason: str):
    if hasattr(pack, "block"):
        return pack.block(key, reason)
    raise JapanCalculationBlockedError(key, reason, getattr(pack, "organization_id", None))


def _row(pack, key):
    if isinstance(pack, dict):
        return pack.get(key)
    rate_map = getattr(pack, "rate_map", None)
    if isinstance(rate_map, dict):
        return rate_map.get(key)
    return None


def _in_force(row, as_of):
    if row is None or as_of is None:
        return True
    start = _as_date(_field(row, "effective_from"))
    end = _as_date(_field(row, "effective_to"))
    return (start is None or start <= as_of) and (end is None or end >= as_of)


def _total(pack, key, as_of, required=True):
    row = _row(pack, key)
    if row is None or not _in_force(row, as_of):
        if required:
            _block(pack, key, "no configured row is in force for the pay date")
        return None
    value = _field(row, "flat_amount")
    if value is None:
        if required:
            _block(pack, key, "row has no total rate configured")
        return None
    return _dec(value)


def _amount(pack, key, as_of, required=True):
    row = _row(pack, key)
    if row is None or not _in_force(row, as_of):
        if required:
            _block(pack, key, "no configured row is in force for the pay date")
        return None
    value = _field(row, "flat_amount")
    if value is None:
        if required:
            _block(pack, key, "row has no amount configured")
        return None
    return _dec(value)


def _split(pack, key, as_of):
    row = _row(pack, key)
    if row is None or not _in_force(row, as_of):
        _block(pack, key, "no split rule is in force")
    value = _upper(_field(row, "text_value"))
    if not value or value == PENDING:
        _block(pack, key, "employee / employer split is PENDING_G1")
    if value != "EQUAL":
        _block(pack, key, f"unsupported split rule {value!r}")
    return value


def _rounder(pack, rounding, key):
    if isinstance(rounding, dict):
        rounding = rounding.get(key)
    if callable(rounding):
        return rounding
    round_row = _row(pack, key)
    if round_row is None:
        _block(pack, key, "no rounding row is configured")
    text = _upper(_field(round_row, "text_value"))
    if not text or text == PENDING:
        _block(pack, key, "rounding is PENDING_G1")
    unit = Decimal("1")
    mode_name = text
    if text.startswith("DOWN_") and text[5:].isdigit():
        unit = Decimal(text[5:])
        mode_name = "DOWN"
    mode = _MODES.get(mode_name)
    if mode is None:
        _block(pack, key, f"unsupported rounding rule {text!r}")
    return lambda value: (value / unit).quantize(Decimal("1"), rounding=mode) * unit


def _rounded(value, rounder, key, field, events):
    before = value
    after = rounder(value)
    if after != before:
        events.append({"field": field, "row": key, "before": str(before), "after": str(after)})
    return after


def _age_on(born, on):
    if born is None or on is None:
        return None
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def _smr(enrollment, pack, as_of, slabs, kind):
    """The statutory SMR for one scheme. Health and pension SMR are separate
    statutory amounts (JP-010): above the pension grade ceiling they differ,
    so pension is never charged on the health SMR or vice versa."""
    kind = kind.upper()
    value = _field(enrollment, f"smr_{kind.lower()}_amount")
    if value is not None:
        return _dec(value)
    grade = _field(enrollment, f"smr_{kind.lower()}_grade")
    if grade is not None:
        matches = [row for row in (slabs or [])
                   if _upper(_field(row, "rule_type")) == _RULE_SMR
                   and _upper(_field(row, "filing_status")) == kind
                   and str(_field(row, "tax_table_number")) == str(grade)
                   and _in_force(row, as_of)]
        if matches:
            matches.sort(key=lambda row: _as_date(_field(row, "effective_from")) or date.min)
            return _dec(_field(matches[-1], "flat_amount"))
    _block(pack, f"jp_smr_{kind.lower()}",
           f"no {kind.lower()} standard monthly remuneration (SMR) is recorded")


def _health_rate(registration, enrollment, pack, as_of, slabs):
    insurer_type = _upper(_field(registration, "health_insurer_type"))
    if insurer_type not in ("KYOKAI_KENPO", "HEALTH_INSURANCE_SOCIETY"):
        _block(pack, "jp_health_rate", "employer health-insurer type is missing or unsupported")
    if insurer_type == "KYOKAI_KENPO":
        state = str(_field(registration, "health_insurer_prefecture") or "").strip()
        if not state:
            _block(pack, "jp_health_rate", "Kyokai Kenpo requires a prefecture JIS code")
    else:
        state = str(_field(registration, "health_insurer_code")
                    or _field(enrollment, "health_insurer_code") or "").strip()
        if not state:
            _block(pack, "jp_health_rate", "health-insurance society code is missing")
    rows = [row for row in (slabs or [])
            if _upper(_field(row, "rule_type")) == _RULE_HEALTH
            and _upper(_field(row, "tax_regime")) == insurer_type
            and str(_field(row, "jurisdiction_state") or "").strip() == state
            and _in_force(row, as_of)]
    if not rows:
        _block(pack, "jp_health_rate",
               f"no {insurer_type} health rate for {state!r} is in force")
    rows.sort(key=lambda row: _as_date(_field(row, "effective_from")) or date.min)
    return rows[-1]


def monthly_contributions(enrollment, registration, pack, as_of=None, rounding=None,
                          date_of_birth=None, on=None, slabs=None):
    """Return monthly EPI, health, care and child-support contributions."""
    as_of = on or as_of
    if as_of is None:
        _block(pack, "pay_date", "payment date is required")
    date_of_birth = _as_date(
        date_of_birth or _field(enrollment, "date_of_birth")
        or _field(registration, "date_of_birth") or getattr(pack, "date_of_birth", None))
    slabs = slabs if slabs is not None else getattr(pack, "slabs", None)
    health_enabled = _field(enrollment, "health_eligible") is True
    pension_enabled = _field(enrollment, "pension_eligible") is True
    care_state = _upper(_field(enrollment, "care_state"))
    child_state = _upper(_field(enrollment, "child_support_state"))
    # Care insurance and the child-support contribution are levied on the
    # health SMR; pension on the pension SMR.
    needs_health_smr = health_enabled or care_state == "COVERED" or child_state == "COVERED"
    smr_health = _smr(enrollment, pack, as_of, slabs, "HEALTH") if needs_health_smr else ZERO
    smr_pension = _smr(enrollment, pack, as_of, slabs, "PENSION") if pension_enabled else ZERO
    insurer_type = _upper(_field(registration, "health_insurer_type"))
    events = []
    trace = {"smrHealth": str(smr_health), "smrPension": str(smr_pension), "careAge": None,
             "healthRate": None, "roundingEvents": events}

    pension_total = ZERO
    if pension_enabled:
        pension_total = _total(pack, "jp_epi_total", as_of)
        _split(pack, "jp_epi_split_rule", as_of)
    pension_each = pension_total / 2 if pension_total else ZERO

    health_total = ZERO
    health_row = None
    if health_enabled:
        health_row = _health_rate(registration, enrollment, pack, as_of, slabs)
        health_total = _dec(_field(health_row, "rate_pct"))
        if _upper(_field(registration, "health_insurer_type")) == "KYOKAI_KENPO":
            low = _total(pack, "jp_kyokai_health_total_min", as_of)
            high = _total(pack, "jp_kyokai_health_total_max", as_of)
            if health_total < low or health_total > high:
                _block(pack, "jp_health_rate",
                       f"Kyokai Kenpo rate {health_total} is outside the signed bounds {low}-{high}")
        _split(pack, "jp_health_split_rule", as_of)
        trace["healthRate"] = {"ratePct": str(health_total),
                               "insurerType": _upper(_field(registration, "health_insurer_type")),
                               "state": str(_field(health_row, "jurisdiction_state") or "")}
    health_each = health_total / 2 if health_total else ZERO

    care_total = ZERO
    age = _age_on(date_of_birth, as_of)
    if age is None:
        for source in (enrollment, registration):
            direct = _field(source, "age")
            if isinstance(direct, int):
                age = direct
                break
    trace["careAge"] = age
    if care_state == "COVERED" and insurer_type != "KYOKAI_KENPO":
        # Only Kyokai Kenpo's care rate is in the evidence register (S12);
        # a health-insurance society sets its own (JP-009).
        _block(pack, "jp_kyokai_care_total",
               f"no care-insurance rate is configured for health insurer type {insurer_type or 'unknown'}")
    if care_state == "COVERED":
        if age is None:
            _block(pack, "jp_date_of_birth", "date of birth is required for care insurance")
        min_age = int(_amount(pack, "jp_care_min_age", as_of))
        max_age = int(_amount(pack, "jp_care_max_age", as_of))
        if min_age <= age <= max_age:
            care_total = _total(pack, "jp_kyokai_care_total", as_of)
            _split(pack, "jp_care_split_rule", as_of)
    care_each = care_total / 2 if care_total else ZERO

    child_total = ZERO
    if child_state == "COVERED":
        if insurer_type != "KYOKAI_KENPO":
            _block(pack, "jp_kyokai_child_support_total",
                   f"no child-support rate is configured for health insurer type {insurer_type or 'unknown'}")
        row = _row(pack, "jp_kyokai_child_support_total")
        if row is None:
            # Not configured at all is a misconfiguration, not "not yet in force".
            _block(pack, "jp_kyokai_child_support_total", "no child-support contribution row is configured")
        if _in_force(row, as_of):
            child_total = _dec(_field(row, "flat_amount"))
            if _field(row, "flat_amount") is None:
                _block(pack, "jp_kyokai_child_support_total", "row has no total rate configured")
            _split(pack, "jp_child_support_split_rule", as_of)
    child_each = child_total / 2 if child_total else ZERO

    health_scale = smr_health / HUNDRED
    pension_scale = smr_pension / HUNDRED
    buckets = {
        "epi": (pension_each * pension_scale, "jp_si_employee_share_rounding"),
        "health": (health_each * health_scale, "jp_si_employee_share_rounding"),
        "care": (care_each * health_scale, "jp_si_employee_share_rounding"),
        "child_support": (child_each * health_scale, "jp_si_employee_share_rounding"),
    }
    amounts = {}
    for name, (raw, rounding_key) in buckets.items():
        if raw <= ZERO:
            amounts[name] = (ZERO, ZERO)
            continue
        rounder = _rounder(pack, rounding, rounding_key)
        employee = _rounded(raw, rounder, rounding_key, f"jp_{name}_employee", events)
        employer = _rounded(raw, rounder, rounding_key, f"jp_{name}_employer", events)
        amounts[name] = (employee, employer)

    employee_total = sum(value[0] for value in amounts.values())
    employer_total = sum(value[1] for value in amounts.values())
    trace["rateRows"] = {
        "epi": "jp_epi_total" if pension_total else None,
        "health": "JP_HEALTH_RATE" if health_total else None,
        "care": "jp_kyokai_care_total" if care_total else None,
        "childSupport": "jp_kyokai_child_support_total" if child_total else None,
    }
    trace["rates"] = {
        "epiTotal": str(pension_total), "healthTotal": str(health_total),
        "careTotal": str(care_total), "childSupportTotal": str(child_total),
    }
    result = SIResult(
        epi_employee=amounts["epi"][0], epi_employer=amounts["epi"][1],
        health_employee=amounts["health"][0], health_employer=amounts["health"][1],
        care_employee=amounts["care"][0], care_employer=amounts["care"][1],
        child_support_employee=amounts["child_support"][0],
        child_support_employer=amounts["child_support"][1],
        employee_total=employee_total, employer_total=employer_total, smr=smr_health,
        smr_health=smr_health, smr_pension=smr_pension, trace=trace,
    )
    result["epi"] = {"employee": amounts["epi"][0], "employer": amounts["epi"][1]}
    result["health"] = {"employee": amounts["health"][0], "employer": amounts["health"][1]}
    result["care"] = {"employee": amounts["care"][0], "employer": amounts["care"][1]}
    result["child_support"] = {"employee": amounts["child_support"][0],
                               "employer": amounts["child_support"][1]}
    return result
