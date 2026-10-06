"""
engine/jurisdictions/singapore/labour.py
----------------------------------------
Singapore labour-pay controls — ZP-SG-ENG-001 §12, SG-034 (no generic
minimum wage; PWM/LQS conditional), SG-035 (Part IV overtime from workman /
manager-executive status and basic salary), SG-037 (deductions). Pure:
every statutory number is a RulePack row (ContributionRate, resolved for
the wage month and passed in as `rates`) with a MOM SourceArtifact:

  MOM "Employment Act: who it covers" — Part 4 covers a workman earning a
    monthly basic salary ≤ ea_part4_workman_basic_max, a non-workman ≤
    ea_part4_non_workman_basic_max; not managers/executives.
  MOM "Hours of work, overtime and rest day" — overtime ≥
    ea_overtime_rate_multiplier × hourly basic rate; monthly-rated hourly
    basic rate = (12 × monthly basic) / (52 × ea_normal_weekly_hours);
    non-workmen capped at ea_overtime_non_workman_salary_cap /
    ea_overtime_non_workman_hourly_cap; ≤ ea_overtime_max_hours_month.
  MOM "Paying salary" — salary within salary_payment_deadline_days after
    the salary period, overtime within overtime_payment_deadline_days.
  MOM "Allowable salary deductions" — total ≤ ea_deduction_max_pct of the
    salary for the period (excluding absence, advances/loans, co-operative
    payments); migrant-worker levy and other work-pass costs never deducted.
  MOM "Annual leave" / "Sick leave" — entitlement tables.
  Progressive Wage Model sector pages — pwm__<SECTOR>__<GROUP>__<LEVEL>
    rows (flat_amount = monthly floor; text_value = BASIC | GROSS).

A missing rule row never becomes a default: the check reports
NOT_EVALUATED and the Compliance Centre shows the gap.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from app.modules.payroll.engine.jurisdictions.singapore.preflight import BLOCK, INFO, WARN, check

_Z = Decimal("0")
PWM_KEY_PREFIX = "pwm__"
PWM_SECTORS = ("CLEANING", "SECURITY", "LANDSCAPE", "LIFT_ESCALATOR", "RETAIL", "FOOD_SERVICES", "WASTE_MANAGEMENT",
               "OPW_ADMIN", "OPW_DRIVER")
# Sectors whose MOM page states the part-time basis: "pro-rated on a 44-hours
# basis" (food services, retail) / "pro-rated based on a 44-hour work week
# basis" (security). Other sectors say only "will be pro-rated" — not evaluated.
PWM_PART_TIME_44H_SECTORS = ("FOOD_SERVICES", "RETAIL", "SECURITY",
                             # MOM OPW notes §4: hourly = monthly gross × 12 / (52 × 44)
                             "OPW_ADMIN", "OPW_DRIVER")
PWM_OT_RATE_PREFIX = "pwo_"          # per-hour PWM overtime rate of pay (waste management ladder)
# Sectors whose MOM "Total PWM Gross Wage Requirement" for overtime hours is a
# published table (sgp_pwm_overtime_schedules): retail, food services, OPWs.
PWM_OT_TABLE_SECTORS = ("RETAIL", "FOOD_SERVICES", "OPW_ADMIN", "OPW_DRIVER")


def pwm_overtime_rate_key(sector: str, group: str, level: str) -> str:
    return f"{PWM_OT_RATE_PREFIX}{sector}__{group}__{level}"
PWM_FULL_TIME_MIN_WEEKLY_HOURS = Decimal("35")   # MOM: full-time = 35–44 hours per week
# Sectors whose PWM wage requirement is a GROSS wage (basic + allowances +
# productivity incentives, excluding overtime / bonus / AWS / reimbursements).
_PWM_AVERAGING_SECTORS = ("RETAIL",)          # MOM retail page: 3-month averaging permitted


def pwm_key(sector: str, group: str, level: str) -> str:
    return f"{PWM_KEY_PREFIX}{sector}__{group}__{level}"


def _amount(rates, key):
    row = rates.get(key)
    return None if row is None or row.flat_amount is None else Decimal(str(row.flat_amount))


def _ref(rates, key):
    row = rates.get(key)
    return None if row is None else {"key": key, "rowId": getattr(row, "id", None),
                                     "sourceDocumentId": getattr(row, "source_document_id", None)}


# ── Part IV coverage and overtime (SG-035) ──────────────────────────────

def part4_coverage(workman, manager_executive, monthly_basic: Decimal, rates: dict) -> dict:
    if manager_executive == "YES":
        return {"status": "NOT_COVERED", "reason": "managers and executives are not covered by Part 4"}
    if workman not in ("YES", "NO"):
        return {"status": "UNDETERMINED", "reason": "workman / non-workman status not recorded"}
    key = "ea_part4_workman_basic_max" if workman == "YES" else "ea_part4_non_workman_basic_max"
    limit = _amount(rates, key)
    if limit is None:
        return {"status": "NOT_EVALUATED", "reason": f"{key} not configured"}
    covered = monthly_basic <= limit
    return {"status": "COVERED" if covered else "NOT_COVERED", "threshold": str(limit), "basicSalary": str(monthly_basic),
            "reason": f"{'workman' if workman == 'YES' else 'non-workman'} basic salary "
                      f"{'≤' if covered else '>'} S${limit}", "ref": _ref(rates, key)}


def overtime_minimum_hourly(workman, monthly_basic: Decimal, rates: dict):
    """Minimum overtime rate per hour for a Part 4 monthly-rated employee:
    multiplier × (12 × basic) / (52 × normal weekly hours); non-workmen are
    capped at the published hourly cap. Displayed to the cent (the source
    states no rounding for the uncapped figure) — pay is never computed here."""
    mult, hours = _amount(rates, "ea_overtime_rate_multiplier"), _amount(rates, "ea_normal_weekly_hours")
    if mult is None or hours is None:
        return None
    if workman != "YES":
        cap_salary, cap_hourly = _amount(rates, "ea_overtime_non_workman_salary_cap"), _amount(rates, "ea_overtime_non_workman_hourly_cap")
        if cap_salary is None or cap_hourly is None:
            return None
        if monthly_basic >= cap_salary:
            return {"hourlyBasic": str(cap_hourly), "minimumOvertimeHourly": str((cap_hourly * mult).quantize(Decimal("0.01"))),
                    "basis": f"non-workman cap: salary S${cap_salary} / hourly S${cap_hourly} (MOM)"}
    hourly = Decimal(12) * monthly_basic / (Decimal(52) * hours)
    return {"hourlyBasic": str(hourly.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "minimumOvertimeHourly": str((hourly * mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "basis": f"{mult} × (12 × monthly basic) / (52 × {hours})"}


def overtime_hours_from_attendance(records, expected_daily_hours, minimum_overtime_minutes=0) -> dict:
    """Hours worked beyond the normal daily hours, from the attendance
    records' own `hours` (MOM: "Overtime work is all work in excess of the
    normal hours of work (excluding breaks)"). The normal daily hours are the
    organization policy's expected hours for the employee's category; a
    day's excess below the policy's minimum overtime minutes is not counted.
    Weekly-average (44 h over 2 / 3 weeks) arrangements and rest-day /
    public-holiday work are not evaluated here."""
    expected = Decimal(str(expected_daily_hours or 0))
    minimum = Decimal(str(minimum_overtime_minutes or 0)) / Decimal(60)
    total, days, unparsed = _Z, [], 0
    for r in records or []:
        if (getattr(r, "status", "present") or "present") != "present" or not getattr(r, "hours", None):
            continue
        try:
            worked = Decimal(str(r.hours).strip())
        except Exception:
            unparsed += 1
            continue
        excess = worked - expected
        if excess > _Z and excess >= minimum:
            total += excess
            days.append({"date": r.date.isoformat() if getattr(r, "date", None) else None, "hours": str(excess)})
    return {"hours": total, "days": days, "unparsedRecords": unparsed, "expectedDailyHours": str(expected)}


def statutory_overtime_pay(workman, monthly_basic: Decimal, hours: Decimal, rates: dict):
    """Part 4 minimum overtime pay: hours × multiplier × hourly basic rate
    ((12 × monthly basic) / (52 × normal weekly hours); non-workmen at or
    above the salary cap use the published hourly cap). MOM states no rounding
    for the uncapped hourly rate, so the amount is rounded UP to the cent —
    never below the statutory minimum. None when a rule row is missing."""
    mult, weekly = _amount(rates, "ea_overtime_rate_multiplier"), _amount(rates, "ea_normal_weekly_hours")
    if mult is None or weekly is None:
        return None
    hourly = Decimal(12) * monthly_basic / (Decimal(52) * weekly)
    basis = f"{mult} × (12 × monthly basic) / (52 × {weekly})"
    if workman != "YES":
        cap_salary, cap_hourly = _amount(rates, "ea_overtime_non_workman_salary_cap"), _amount(rates, "ea_overtime_non_workman_hourly_cap")
        if cap_salary is None or cap_hourly is None:
            return None
        if monthly_basic >= cap_salary:
            hourly, basis = cap_hourly, f"{mult} × non-workman hourly cap S${cap_hourly}"
    amount = (Decimal(hours) * mult * hourly).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return {"amount": amount, "hourlyBasic": str(hourly.quantize(Decimal("0.0001"))), "multiplier": str(mult),
            "hours": str(hours), "basis": basis, "rounding": "rounded up to the cent (never below the statutory minimum)"}


# ── Salary timing (§12) ─────────────────────────────────────────────────

def salary_timing_check(employee, period_end: date, pay_date: date, date_of_leaving, rates) -> list:
    out = []
    days = _amount(rates, "salary_payment_deadline_days")
    if days is None:
        return [check("EA_SALARY_DEADLINE_NOT_EVALUATED", WARN, "salary_payment_deadline_days not configured", employee)]
    deadline = period_end + timedelta(days=int(days))
    if pay_date > deadline:
        out.append(check("EA_SALARY_LATE", WARN, f"pay date {pay_date.isoformat()} is after the Employment Act deadline "
                         f"{deadline.isoformat()} ({int(days)} days after the salary period) — late payment is an offence",
                         employee, source="MOM Paying salary", action="Move the pay date on or before the deadline"))
    if date_of_leaving is not None and period_end >= date_of_leaving >= period_end.replace(day=1):
        out.append(check("EA_FINAL_SALARY_TIMING", INFO, "final salary: on the last day of employment when notice is served "
                         "or the employer terminates (within 3 working days if not possible); within 7 days when the "
                         "employee resigns without notice — the reason for leaving is not captured, confirm the date",
                         employee, source="MOM Paying salary"))
    return out


# ── Deductions (SG-037) ─────────────────────────────────────────────────

def deduction_check(employee, gross: Decimal, statutory_employee: Decimal, absence: Decimal, total_deductions: Decimal,
                    rates: dict) -> list:
    """Employee deductions other than CPF / SHG (statutory) and absence are
    not captured with a reason/consent in this payroll: any such amount needs
    the SG-037 evidence and must stay within the 50% cap."""
    other = (total_deductions or _Z) - (statutory_employee or _Z) - (absence or _Z)
    if other <= _Z:
        return []
    cap = rates.get("ea_deduction_max_pct")
    pct = None if cap is None or cap.employer_rate_pct is None else Decimal(str(cap.employer_rate_pct))
    out = [check("EA_DEDUCTION_EVIDENCE_REQUIRED", WARN, f"S${other} of non-statutory deductions — each needs a reason, "
                 "legal/consent basis and evidence; migrant-worker levy, work-pass, security-bond, medical-insurance, "
                 "repatriation and compulsory-training costs may never be recovered", employee,
                 source="MOM Allowable salary deductions", action="Attach the deduction basis or remove it")]
    if pct is not None and gross > _Z and other > gross * pct:
        out.append(check("EA_DEDUCTION_CAP_EXCEEDED", BLOCK, f"non-statutory deductions S${other} exceed {pct * 100}% of the "
                         f"salary S${gross}", employee, source="MOM Allowable salary deductions"))
    return out


# ── PWM (SG-034) ────────────────────────────────────────────────────────

def _detailed(result: dict, **details) -> dict:
    """Attach the figures a check was decided on (Phase 5.6/5.7 reports read
    them instead of re-deriving the floor) — Decimal kept as a string."""
    result["details"] = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in details.items()}
    return result


def pwm_check(employee, facts: dict, wages: dict, rates: dict) -> list:
    """facts: pwm_sector, pwm_group, pwm_job_level, residency, employment_type,
    part4 (coverage status), overtime_paid (bool). wages: basic, gross_ex_ot
    (Decimal). PWM covers Singapore citizens and PRs (MOM sector pages);
    part-time floors are pro-rated and not evaluated here."""
    sector = facts.get("pwm_sector")
    if not sector or sector == "NONE":
        return []
    if facts.get("residency") not in ("SC", "SPR"):
        return [check("PWM_NOT_APPLICABLE_FOREIGN", INFO, "PWM wage requirements cover Singapore citizens and PRs", employee)]
    group, level = facts.get("pwm_group"), facts.get("pwm_job_level")
    if not group or not level:
        return [check("PWM_CLASSIFICATION_INCOMPLETE", WARN, f"PWM sector {sector} recorded without group / job level",
                      employee, action="Record the PWM group and job level")]
    key = pwm_key(sector, group, level)
    row = rates.get(key)
    if row is None or row.flat_amount is None:
        return [check("PWM_FLOOR_NOT_CONFIGURED", WARN, f"no PWM wage row {key} in force for the wage month", employee,
                      source="MOM PWM", action="Check the classification against the MOM sector table")]
    if wages.get("no_pay_leave"):
        return [check("PWM_INCOMPLETE_MONTH_NOT_EVALUATED", WARN, "no-pay leave this month — the PWM monthly floor is for "
                      "a full month and no pro-rating rule is evaluated here", employee, source=key)]
    note = []
    if wages.get("incomplete_month"):
        # Phase 5.2: the floor is a monthly wage rate; in an incomplete month
        # the contractual monthly rate is evaluated (the salary paid is MOM's
        # incomplete-month pro rata of that rate).
        note = [check("PWM_INCOMPLETE_MONTH_RATE_EVALUATED", INFO, "incomplete month — the PWM floor is evaluated on the "
                      "monthly rate of pay; the salary paid is MOM's incomplete-month pro rata", employee, source=key)]
    basis = (getattr(row, "text_value", None) or "BASIC").upper()
    floor = Decimal(str(row.flat_amount))
    if (facts.get("employment_type") or "") == "Part-time":
        hours = facts.get("contractual_weekly_hours")
        try:
            hours = Decimal(str(hours)) if hours not in (None, "") else None
        except Exception:  # noqa: BLE001 — an unparsable figure is "not recorded"
            hours = None
        if sector not in PWM_PART_TIME_44H_SECTORS or hours is None or hours <= _Z:
            why = ("the MOM page states no part-time basis for this sector" if sector not in PWM_PART_TIME_44H_SECTORS
                   else "contractual weekly hours are not recorded")
            return [check("PWM_PART_TIME_NOT_EVALUATED", WARN, f"part-time PWM wages are pro-rated — {why}; the floor is "
                          "not evaluated", employee, source=key)]
        if hours < PWM_FULL_TIME_MIN_WEEKLY_HOURS:
            floor = floor * hours / Decimal("44")
            note = note + [check("PWM_PART_TIME_PRO_RATED", INFO, f"part-time floor = monthly floor × {hours} ÷ 44 "
                                 f"contractual hours (MOM {sector} PWM page)", employee, source=key)]
    tested = wages["basic"] if basis == "BASIC" else wages["gross_ex_ot"]
    out = list(note)
    if tested < floor:
        severity = WARN if sector in _PWM_AVERAGING_SECTORS else BLOCK
        extra = " — retail permits 3-month averaging; confirm the average meets the requirement" if severity == WARN else ""
        out.append(_detailed(check("PWM_SHORTFALL", severity, f"{basis.lower()} wage S${tested} below the PWM floor S${floor} "
                                   f"({sector} {group} {level}){extra}", employee, source=key,
                                   action="Pay at least the PWM wage for the job level"),
                             basis=basis, testedWage=tested, floor=floor, averagingPermitted=severity == WARN))
    else:
        out.append(_detailed(check("PWM_MET", INFO, f"{basis.lower()} wage S${tested} ≥ PWM floor S${floor} ({level})",
                                   employee, source=key),
                             basis=basis, testedWage=tested, floor=floor, averagingPermitted=sector in _PWM_AVERAGING_SECTORS))
    hours = Decimal(str(facts.get("overtime_hours") or 0))
    part_time = (facts.get("employment_type") or "") == "Part-time"
    if facts.get("part4") == "COVERED" and hours > _Z and sector in PWM_OT_TABLE_SECTORS and not part_time:
        # MOM: for Part 4 full-time employees the requirement is the Total PWM
        # Gross Wage Requirement for the month's overtime hours (rounded down),
        # compared with gross wages INCLUDING overtime pay; pay the higher of it
        # and the Employment Act overtime rate.
        req = facts.get("overtime_gross_requirement") or {}
        if req.get("status") == "FOUND":
            total = Decimal(str(wages.get("gross_ex_ot") or 0)) + Decimal(str(wages.get("overtime") or 0))
            required = Decimal(str(req["required"]))
            ref = f"sgp_pwm_overtime_schedules#{req['scheduleId']} (source {req['sourceDocumentId']}, sha256 {req['sha256'][:12]}…)"
            ot_details = dict(grossIncludingOvertime=total, required=required, overtimeHours=req["hours"],
                              scheduleId=req["scheduleId"], averagingPermitted=sector in _PWM_AVERAGING_SECTORS)
            if total < required:
                severity = WARN if sector in _PWM_AVERAGING_SECTORS else BLOCK
                extra = " — retail permits 3-month averaging; confirm the average meets it" if severity == WARN else ""
                out.append(_detailed(check("PWM_OVERTIME_GROSS_SHORTFALL", severity, f"gross wage incl. overtime S${total} below the "
                                           f"Total PWM Gross Wage Requirement S${required} for {req['hours']} OT hours "
                                           f"({req['roleLabel']}, from {req['effectiveFrom']}){extra}", employee, source=ref,
                                           action="Pay at least the Total PWM Gross Wage Requirement for the overtime hours"),
                                     **ot_details))
            else:
                out.append(_detailed(check("PWM_OVERTIME_GROSS_MET", INFO, f"gross wage incl. overtime S${total} ≥ Total PWM Gross "
                                           f"Wage Requirement S${required} for {req['hours']} OT hours ({req['roleLabel']})",
                                           employee, source=ref), **ot_details))
        else:
            out.append(check("PWM_OVERTIME_GROSS_NOT_EVALUATED", WARN, "no MOM overtime gross schedule in force for this "
                             f"job level, month and {req.get('hours', int(hours))} OT hours — never assumed compliant",
                             employee, source=key))
    elif facts.get("part4") == "COVERED" and facts.get("overtime_paid"):
        rate_row = rates.get(pwm_overtime_rate_key(sector, group, level))
        if sector == "WASTE_MANAGEMENT" and rate_row is not None and rate_row.flat_amount is not None and hours > _Z:
            # MOM waste ladder: an "OT Rate of Pay" per hour, paid as the higher
            # of it and the Employment Act 1.5 × basic hourly rate.
            paid = Decimal(str(facts.get("overtime_amount") or 0)) / hours
            minimum = Decimal(str(rate_row.flat_amount))
            if paid < minimum:
                out.append(check("PWM_OVERTIME_RATE_SHORTFALL", BLOCK, f"overtime paid at S${paid.quantize(Decimal('0.01'))}"
                                 f"/h, below the PWM overtime rate of pay S${minimum}/h ({level})", employee,
                                 source=pwm_overtime_rate_key(sector, group, level),
                                 action="Pay overtime at the higher of the PWM rate and the Employment Act rate"))
            else:
                out.append(check("PWM_OVERTIME_RATE_MET", INFO, f"overtime paid at S${paid.quantize(Decimal('0.01'))}/h ≥ "
                                 f"PWM overtime rate S${minimum}/h", employee, source=pwm_overtime_rate_key(sector, group, level)))
        elif basis == "GROSS":
            out.append(check("PWM_OVERTIME_GROSS_NOT_EVALUATED", WARN, "PWM total gross wage requirements for overtime "
                             "hours are published as separate MOM tables and are not evaluated", employee, source=key))
    return out


# ── Leave entitlement minimums (§12) ─────────────────────────────────────

def _completed_months(start: date, on: date) -> int:
    months = (on.year - start.year) * 12 + (on.month - start.month)
    if on.day < start.day:
        months -= 1
    return max(months, 0)


def annual_leave_minimum(date_of_joining: date, on: date, rates: dict):
    """Statutory annual leave for the current year of service (MOM table);
    None when a row is missing or service < the minimum months."""
    if date_of_joining is None:
        return None
    months = _completed_months(date_of_joining, on)
    minimum = _amount(rates, "ea_leave_min_service_months")
    if minimum is None or months < minimum:
        return {"days": 0, "completedMonths": months, "basis": "less than the minimum service"} if minimum is not None else None
    year = months // 12 + 1
    key = f"ea_annual_leave_year_{min(year, 8)}"
    days = _amount(rates, key)
    return None if days is None else {"days": int(days), "serviceYear": year, "completedMonths": months, "ref": _ref(rates, key)}


def sick_leave_minimum(date_of_joining: date, on: date, rates: dict):
    if date_of_joining is None:
        return None
    months = _completed_months(date_of_joining, on)
    minimum = _amount(rates, "ea_leave_min_service_months")
    if minimum is None:
        return None
    if months < minimum:
        return {"outpatient": 0, "hospitalisation": 0, "completedMonths": months}
    step = min(months, 6)
    op, hosp = _amount(rates, f"ea_sick_leave_outpatient_month_{step}"), _amount(rates, f"ea_sick_leave_hospital_month_{step}")
    if op is None or hosp is None:
        return None
    return {"outpatient": int(op), "hospitalisation": int(hosp), "completedMonths": months}


# ── Salary deductions (SG-037, Phase 5.1 WS5) ───────────────────────────
# MOM "Allowable salary deductions" (retrieved 2026-09-24). Each category:
# evidence = what must be recorded before the deduction may run; cap =
# RulePack row limiting it (share of the salary for the period); in_total_cap
# = counted in the 50% total cap (MOM excludes absence, recovery of
# advances / loans / overpaid salary / unearned benefits and co-operative
# payments). Anything not listed — and every work-pass cost MOM prohibits
# (levy, work pass renewal, security bond, medical insurance, repatriation,
# compulsory training, medical fees, a condition of employment) — BLOCKS.
SG_DEDUCTION_CATEGORIES = {
    "COURT_ORDER": {"evidence": "court order / valid authority reference", "cap": None, "in_total_cap": True},
    "TAX_AGENT_RECOVERY": {"evidence": "appointment as agent for tax recovery", "cap": None, "in_total_cap": True},
    "DAMAGE_LOSS": {"evidence": "inquiry held — employee given the opportunity to explain", "cap": "ea_damage_deduction_max_pct",
                    "in_total_cap": True, "one_time": True},
    "ACCOMMODATION": {"evidence": "employee's acceptance of the accommodation", "cap": "ea_accommodation_amenities_max_pct",
                      "in_total_cap": True, "cap_group": "ACCOMMODATION_AMENITIES"},
    "AMENITIES_SERVICES": {"evidence": "Commissioner for Labour approval and employee acceptance",
                           "cap": "ea_accommodation_amenities_max_pct", "in_total_cap": True,
                           "cap_group": "ACCOMMODATION_AMENITIES"},
    "ADVANCE": {"evidence": "advance record", "cap": "ea_advance_instalment_max_pct", "in_total_cap": False,
                "max_months": "ea_advance_max_months"},
    "LOAN": {"evidence": "loan agreement", "cap": "ea_loan_instalment_max_pct", "in_total_cap": False},
    "OVERPAID_SALARY": {"evidence": "record of the overpayment / unearned benefit", "cap": None, "in_total_cap": False},
    "COOPERATIVE": {"evidence": "employee's written consent", "cap": None, "in_total_cap": False},
    "CONSENTED_OTHER": {"evidence": "employee's written, withdrawable consent (for the employee's benefit)",
                        "cap": None, "in_total_cap": True},
}
SG_PROHIBITED_DEDUCTIONS = ("LEVY", "WORK_PASS", "SECURITY_BOND", "MEDICAL_INSURANCE", "REPATRIATION",
                            "COMPULSORY_TRAINING", "MEDICAL_FEES", "EMPLOYMENT_CONDITION")


def _pct(rates, key):
    row = rates.get(key)
    return None if row is None or row.employer_rate_pct is None else Decimal(str(row.employer_rate_pct))


def evaluate_salary_deductions(orders: list, salary: Decimal, rates: dict, final_payment: bool = False) -> dict:
    """orders: [{id, category, amount, rate_pct, evidence_ref, evidence_date,
    start_date, total_to_collect, collected_before}]. Returns {"lines",
    "total", "errors"}; any error means the payroll must not run (the
    engine BLOCKS) — an invalid deduction never passes silently."""
    lines, errors = [], []
    group_totals, total_capped = {}, _Z
    for o in orders:
        cat = (o.get("category") or "").upper()
        ref = f"deduction {o.get('id')} ({cat or 'no category'})"
        if cat in SG_PROHIBITED_DEDUCTIONS:
            errors.append(f"{ref}: MOM prohibits recovering {cat.lower().replace('_', ' ')} costs from the employee")
            continue
        rule = SG_DEDUCTION_CATEGORIES.get(cat)
        if rule is None:
            errors.append(f"{ref}: not an authorised Employment Act deduction category")
            continue
        if not (o.get("evidence_ref") or "").strip() or o.get("evidence_date") is None:
            errors.append(f"{ref}: {rule['evidence']} must be recorded (reference and date) before it is deducted")
            continue
        amount = Decimal(str(o.get("amount") or 0))
        if o.get("rate_pct") is not None:
            amount = (salary * Decimal(str(o["rate_pct"])) / Decimal(100)).quantize(Decimal("0.01"))
        remaining = None
        if o.get("total_to_collect") is not None:
            remaining = Decimal(str(o["total_to_collect"])) - Decimal(str(o.get("collected_before") or 0))
            amount = min(amount, max(remaining, _Z))
        if rule.get("one_time") and Decimal(str(o.get("collected_before") or 0)) > _Z:
            errors.append(f"{ref}: a damage/loss deduction is a one-time lump sum — already deducted")
            continue
        if amount <= _Z:
            continue
        if rule["cap"]:
            cap = _pct(rates, rule["cap"])
            if cap is None:
                errors.append(f"{ref}: rule row {rule['cap']} not configured")
                continue
            key = rule.get("cap_group") or cat
            group_totals[key] = group_totals.get(key, _Z) + amount
            if group_totals[key] > salary * cap:
                errors.append(f"{ref}: exceeds {cap * 100}% of the salary S${salary} for the period (MOM)")
                continue
        if rule.get("in_total_cap"):
            total_capped += amount
        lines.append({"id": o.get("id"), "category": cat, "amount": str(amount), "evidenceRef": o.get("evidence_ref"),
                      "remainingAfter": str(remaining - amount) if remaining is not None else None})
    total_cap = _pct(rates, "ea_deduction_max_pct")
    if lines and total_cap is None:
        errors.append("ea_deduction_max_pct not configured")
    elif total_cap is not None and not final_payment and total_capped > salary * total_cap:
        errors.append(f"authorised deductions S${total_capped} exceed {total_cap * 100}% of the salary S${salary} "
                      "for the period (MOM; excludes absence, advances, loans, overpaid salary, co-operative payments)")
    total = sum((Decimal(line["amount"]) for line in lines), _Z)
    return {"lines": lines, "total": total, "errors": errors, "capBase": str(salary)}
