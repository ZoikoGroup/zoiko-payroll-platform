"""
modules/payroll/engine/countries/singapore.py
-----------------------------------------------
Singapore (SG) — statutory build (ZP-SG-ENG-001 v1.0, verified against the
official CPF Board / IRAS / MOM sources recorded as SourceArtifact rows by
scripts/seed_singapore_canonical_pack.py).

Singapore is NOT a monthly-PAYE jurisdiction: ordinary employment income
tax is assessed by IRAS, so this calculator never populates `tds`. Annual
IRAS reporting (AIS/IR8A) and IR21 tax clearance are separate processes,
outside payroll calculation. What payroll does compute:

  1. CPF — employee + employer contributions, from effective-dated
     `TaxSlab` rows with `rule_type="CPF_RATE_BAND"` (never a single
     headline percentage against gross, SG-005). Column reuse, same
     "repurpose an existing generic column per rule_type" convention as
     AU_PAYG_COEFFICIENT / TT_NIS_CLASS:
       filing_status    = CPF cohort ("SC_SPR3" | "SPR1_GG" | "SPR1_FG" |
                          "SPR1_FF" | "SPR2_GG" | "SPR2_FG" | "SPR2_FF")
       tax_regime       = CPF age band (see _CPF_AGE_BANDS)
       min/max_amount   = total-wage band, lower bound exclusive / upper
                          inclusive (the 0 lower bound is inclusive)
       assessment_basis = formula type: NIL | ER_ONLY | PHASE_IN | FULL
       rate_pct         = FULL: employee %; PHASE_IN: phase-in factor x 100
       employer_rate_pct= employer %
       rate_label       = rule id, e.g. "CPF-2026-SC_SPR3-AGE_LE_55-FULL"
     Reused result fields: `employee_pension` / `employer_pension`.
  2. SDL — 0.25% of total wages, clamped to the configured min/max,
     payable for every employee working in Singapore (foreign employees
     included, even with nil CPF). EMPLOYER COST only — reused field
     `employer_payroll_tax`. The authority's employer-level round-down of
     the monthly total is applied in the statutory output
     (service.generate_sg_sdl_monthly), never per payslip.
  3. SHG — CDAC / ECF / MBMF / SINDA monthly deductions from `TaxSlab`
     rows with `rule_type="SHG_FUND_BAND"` (filing_status = fund code,
     flat_amount = monthly amount). More than one fund may apply (SG-014);
     each fund's residency/pass eligibility is enforced (CPF Board SHG page).
     Reused field (same flat-fee slot Trinidad's Health Surcharge uses):
     `professional_tax`.
  4. Foreign Worker Levy — EMPLOYER COST only (SG-016), never an employee
     deduction. S Pass and Work Permit: the configured monthly levy for a
     full calendar month; for a partial month, MOM's daily rate ((monthly ×
     12) / 365 rounded up to the cent) × days from the pass issue date — a
     pass ending within the month needs the authoritative end-day rule
     (fwl_s_pass_end_day_basis / fwl_work_permit_end_day_basis, not seeded
     → BLOCKED). No pass dates and a partial employment month → BLOCKED.
     Work Permit rates are per MOM sector × levy tier × skill
     (work_permit_levy_key); missing worker facts or no row in force for the
     month → BLOCKED. Reused field (employer-only slot): `employer_eht`.

Compliance checks carried in the trace, never deductions: LQS (for
employers hiring foreign workers) and IR21 eligibility / file-by date. The
IR21 monies hold / clearance / release is the sgp_ir21_cases workflow in
service.py (payment control, outside this calculator).

CPF Additional Wage ceiling — ZP-SG-ENG-001 SG-007 reads "S$102,000 minus
year-to-date OW subject to CPF". The official CPF Board method (AW ceiling
examples, SourceArtifact "CPF Board — Examples for computation of AW
Ceiling"; Option A approved 2026-09-23) is implemented instead, and the
difference is recorded in every trace:
  - At each AW payment the ceiling is ESTIMATED as S$102,000 − [YTD OW
    subject + this month's OW subject × months of employment remaining in
    the year, this month included].
  - In December, or in/after the last month of employment, the same
    formula uses ACTUAL OW (no months remain), and any earlier AW that was
    not yet CPF-subject is caught up first, chronologically, each chunk at
    the contribution rates of the month it was paid (CPF Board examples
    9/12/13/14); then the current month's AW.
  - If the ceiling has fallen below the AW already contributed on, the
    excess is reported as a CPF refund application, never netted here.
  - Contributions for OW and every AW chunk of the month are summed, then
    rounded once (CPF rate table note 4).

Fail-closed (SG-001): every statutory parameter resolves through
resolve_jurisdiction_parameter with NO fallback value ("SG" is in
shared._VALIDATION_ENABLED_COUNTRIES), and every missing CPF/SHG band,
missing employee fact or contradictory fact raises
SingaporeCalculationBlockedError — never a default rate.

Disclosed simplifications (each BLOCKS rather than guesses where the rule
is not given):
  - OW / AW / non-CPF are classified per earning COMPONENT through the
    shared TaxabilityRule table (classify_cpf_wages); with no rule the
    default is salary/allowances = OW, additional_compensation = AW. AWS,
    bonus and AW commission all arrive in additional_compensation, and the
    OW "payable by the 14th of the following month" timing test is not
    evaluated (payable dates are not captured).
  - Wage month (SG-011, resolve_wage_month): the payroll period's month when
    the pay date is on or before the 14th of the following month (OW for
    the employment month); otherwise the wages are AW for the pay-date
    month. A period spanning two calendar months, or AW inside a payslip
    whose OW belongs to the previous month, BLOCKS. Without a period
    (preview / golden vectors) the pay-date month is used. Only Monthly
    payrolls are supported; other frequencies are BLOCKED. Several payslips in one
    wage month (salary + off-cycle/backpay runs) are aggregated: CPF band,
    OW ceiling, rounding, SDL clamp, SHG and the S Pass levy are computed on
    the month's combined wages and each later payslip books the difference
    (month_to_date). The employer-level SDL round-down is applied only in
    service.generate_sg_sdl_monthly.
  - A mid-month SPR conversion needs an approved wage-segmentation method
    (SG-009) and is BLOCKED.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    MissingComplianceConfigurationError,
    resolve_jurisdiction_parameter,
)

_COUNTRY = "SG"
ENGINE_VERSION = "SG-2026.10"

# Fail-closed: no Singapore statutory value has a hardcoded fallback. These
# exist only so fallback_registry.py can list the required keys; each is
# passed as `default=` and is never actually returned, because "SG" is in
# shared._VALIDATION_ENABLED_COUNTRIES (a missing row raises first).
_SG_CPF_OW_CEILING_MONTHLY = None
_SG_CPF_ANNUAL_WAGE_CEILING = None
_SG_SDL_RATE = None
_SG_SDL_MIN_MONTHLY = None
_SG_SDL_MAX_MONTHLY = None

CPF_RATE_BAND = "CPF_RATE_BAND"
SHG_FUND_BAND = "SHG_FUND_BAND"

RESIDENCY_SC = "SC"
RESIDENCY_SPR = "SPR"
RESIDENCY_FOREIGN = "FOREIGN"

WORK_PASS_NONE = "NONE"
FOREIGN_WORK_PASSES = ("EP", "S_PASS", "WORK_PERMIT")

CONTRIBUTION_ARRANGEMENTS = ("GG", "FG", "FF")
SHG_FUNDS = ("CDAC", "ECF", "MBMF", "SINDA")

# CPF Board "Contributions to self-help groups" — who each fund applies to.
# CDAC/ECF: Singapore Citizens and SPRs; MBMF: also foreign employees;
# SINDA: also Employment Pass holders. Keyed by effective residency; for a
# foreigner the value is the set of passes allowed (None = any pass).
_SHG_ELIGIBILITY = {
    "CDAC": {"local": True, "foreign_passes": ()},
    "ECF": {"local": True, "foreign_passes": ()},
    "MBMF": {"local": True, "foreign_passes": None},
    "SINDA": {"local": True, "foreign_passes": ("EP",)},
}

# (key, lower age exclusive, upper age inclusive) — "≤55", ">55–60", ...
_CPF_AGE_BANDS = (
    ("AGE_LE_55", None, 55),
    ("AGE_55_60", 55, 60),
    ("AGE_60_65", 60, 65),
    ("AGE_65_70", 65, 70),
    ("AGE_GT_70", 70, None),
)
_CPF_AGE_BOUNDARIES = (55, 60, 65, 70)

_ONE = Decimal("1")
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

SPEC_CLARIFICATION_SG_007 = (
    "ZP-SG-ENG-001 SG-007 ('S$102,000 minus year-to-date OW subject to CPF') is implemented per the official "
    "CPF Board AW-ceiling method (Option A, approved 2026-09-23): estimated ceiling at each AW payment using "
    "the current OW for the remaining months of employment, final ceiling on actual OW in December or the last "
    "month of employment, shortfall at each AW payment's own contribution rates."
)


class SingaporeCalculationBlockedError(MissingComplianceConfigurationError):
    """A Singapore statutory calculation that must not proceed — missing
    statutory row, missing/contradictory employee fact, or an unsupported
    case. Subclasses MissingComplianceConfigurationError so the existing
    main.py handler returns the same MISSING_COMPLIANCE_CONFIGURATION 400
    every other fail-closed jurisdiction uses."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Singapore calculation blocked ({key}): {reason}",)


def _param(rate_map, key, default, side=None):
    return resolve_jurisdiction_parameter(rate_map, key, default, side=side, country=_COUNTRY)


def _row_ref(row):
    """Provenance of one configured row for the trace — rule id, its own
    effective window and evidence link where the row carries them."""
    if row is None:
        return None
    ref = {}
    for attr, key in (("rate_label", "rule"), ("component_key", "componentKey"), ("id", "rowId"),
                      ("source_document_id", "sourceDocumentId"), ("jurisdiction_pack_id", "packId")):
        value = getattr(row, attr, None)
        if value not in (None, ""):
            ref[key] = value
    for attr, key in (("effective_from", "effectiveFrom"), ("effective_to", "effectiveTo")):
        value = getattr(row, attr, None)
        if value is not None:
            ref[key] = value.isoformat()
    return ref


def _age_on(date_of_birth: date, on: date) -> int:
    return on.year - date_of_birth.year - ((on.month, on.day) < (date_of_birth.month, date_of_birth.day))


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb anniversary in a non-leap year
        return d.replace(year=d.year + years, day=28)


def _month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _leap_day_boundary(date_of_birth: date, month_start: date):
    """(boundary age, year) when a 29 February birth date reaches a CPF
    boundary age in a non-leap year and `month_start` is February or March of
    that year — the only months the observed birthday can change."""
    if (date_of_birth.month, date_of_birth.day) != (2, 29) or month_start.month not in (2, 3):
        return None
    for boundary in _CPF_AGE_BOUNDARIES:
        year = date_of_birth.year + boundary
        if year == month_start.year and not calendar.isleap(year):
            return boundary, year
    return None


def _band_for_age(age: int) -> str:
    for key, lower, upper in _CPF_AGE_BANDS:
        if (lower is None or age > lower) and (upper is None or age <= upper):
            return key
    raise AssertionError(age)  # unreachable — bands cover every age


def resolve_cpf_age_band(date_of_birth: date, month_start: date, month_end: date, rate_map: dict) -> str:
    """Age band for the wage month. Unambiguous whenever the employee's
    age never equals a boundary age (55/60/65/70) during the month. At a
    boundary the configured `cpf_age_band_semantics` rule applies; the
    only supported value is CPF Board's MONTH_AFTER_BIRTHDAY ("new
    contribution rates apply from the first day of the month after the
    employee's 55th, 60th, 65th or 70th birthday"). Without it: BLOCKED.

    Phase 6.10: a 29 February birth date reaching a boundary age in a
    NON-leap year has no birthday that year. Whether CPF observes it on
    28 February or 1 March is not stated by any source the pack holds, and
    it decides which month the new rates start. Only a sourced
    `cpf_leap_day_birthday_basis` row (FEBRUARY | MARCH) decides February
    and March of that year; without one both months are BLOCKED (before,
    _age_on silently chose 1 March)."""
    leap = _leap_day_boundary(date_of_birth, month_start)
    if leap is not None:
        boundary, year = leap
        row = rate_map.get("cpf_leap_day_birthday_basis")
        basis = (getattr(row, "text_value", None) or "").upper() if row is not None else ""
        if basis not in ("FEBRUARY", "MARCH"):
            raise SingaporeCalculationBlockedError(
                "cpf_leap_day_birthday_basis",
                f"the employee's {boundary}th birthday falls on 29 February in {year}, a non-leap year, and no "
                "sourced rule says whether CPF observes it on 28 February or 1 March",
            )
        observed = date(year, 2, 28) if basis == "FEBRUARY" else date(year, 3, 1)
        return _band_for_age(boundary + 1 if observed < month_start else boundary - 1)
    ages = {_age_on(date_of_birth, month_start), _age_on(date_of_birth, month_end)}
    if not any(a in _CPF_AGE_BOUNDARIES for a in ages):
        return _band_for_age(max(ages))

    row = rate_map.get("cpf_age_band_semantics")
    semantics = getattr(row, "text_value", None) if row is not None else None
    if semantics != "MONTH_AFTER_BIRTHDAY":
        raise SingaporeCalculationBlockedError(
            "cpf_age_band_semantics",
            "employee is at a CPF age-band boundary this wage month and no authoritative "
            "age-band rule is configured",
        )
    # The higher band applies only once the boundary birthday fell before
    # this wage month began (i.e. from the month AFTER the birthday month).
    completed = _age_on(date_of_birth, month_start - timedelta(days=1))
    return _band_for_age(completed + 1 if completed in _CPF_AGE_BOUNDARIES else completed)


def resolve_spr_year(spr_effective_date: date, month_start: date, month_end: date):
    """SPR year per ZP-SG-ENG-001 §3 / CPF Board: the second year begins on
    the first day of the month after the first anniversary of SPR
    conversion, the third year the first day of the month after the second
    anniversary. Returns None when SPR status has not begun by the end of
    the wage month (not yet CPF-eligible). A conversion part-way through
    the wage month is BLOCKED (SG-009)."""
    if spr_effective_date > month_end:
        return None
    if spr_effective_date > month_start:
        raise SingaporeCalculationBlockedError(
            "sgp_spr_effective_date",
            "SPR status begins part-way through the wage month — an approved wage-segmentation "
            "method is required (SG-009)",
        )
    year1_end = _month_end(_add_years(spr_effective_date, 1))
    year2_end = _month_end(_add_years(spr_effective_date, 2))
    if month_end <= year1_end:
        return 1
    if month_end <= year2_end:
        return 2
    return 3


def resolve_cpf_cohort(ctx: PayrollContext, month_start: date, month_end: date):
    """Returns (cohort, effective_residency). cohort is the CPF cohort key
    ("SC_SPR3", "SPR1_GG", ...) or None when CPF is not payable (foreign
    employee / SPR status not yet begun). effective_residency is SC, SPR
    (in force this month) or FOREIGN. Missing or contradictory statutory
    facts BLOCK (SG-001)."""
    residency = ctx.sgp_cpf_residency_status
    work_pass = ctx.sgp_work_pass_type
    if residency not in (RESIDENCY_SC, RESIDENCY_SPR, RESIDENCY_FOREIGN):
        raise SingaporeCalculationBlockedError(
            "sgp_cpf_residency_status", "citizenship/SPR/foreign status is required for the CPF cohort",
        )
    if work_pass not in (WORK_PASS_NONE,) + FOREIGN_WORK_PASSES:
        raise SingaporeCalculationBlockedError(
            "sgp_work_pass_type", "work pass type is required (NONE for citizens/SPRs)",
        )

    if residency == RESIDENCY_FOREIGN:
        if work_pass == WORK_PASS_NONE:
            raise SingaporeCalculationBlockedError(
                "sgp_work_pass_type", "a foreign employee must have an EP, S Pass or Work Permit",
            )
        return None, RESIDENCY_FOREIGN
    if residency == RESIDENCY_SC:
        if work_pass != WORK_PASS_NONE:
            raise SingaporeCalculationBlockedError(
                "sgp_work_pass_type", "a Singapore Citizen cannot hold a work pass — contradictory facts",
            )
        return "SC_SPR3", RESIDENCY_SC

    # SPR
    if ctx.sgp_spr_effective_date is None:
        raise SingaporeCalculationBlockedError(
            "sgp_spr_effective_date", "SPR effective date is required to derive the SPR year",
        )
    spr_year = resolve_spr_year(ctx.sgp_spr_effective_date, month_start, month_end)
    if spr_year is None:
        # SPR status not yet begun: still a work-pass holder this month.
        if work_pass == WORK_PASS_NONE:
            raise SingaporeCalculationBlockedError(
                "sgp_work_pass_type",
                "SPR status begins after this wage month but no work pass is recorded — contradictory facts",
            )
        return None, RESIDENCY_FOREIGN
    if work_pass != WORK_PASS_NONE:
        raise SingaporeCalculationBlockedError(
            "sgp_work_pass_type", "an employee with SPR status in force cannot hold a work pass — contradictory facts",
        )
    if spr_year >= 3:
        return "SC_SPR3", RESIDENCY_SPR
    arrangement = ctx.sgp_cpf_contribution_arrangement or "GG"  # G/G is the default first two years (§3)
    if arrangement not in CONTRIBUTION_ARRANGEMENTS:
        raise SingaporeCalculationBlockedError(
            "sgp_cpf_contribution_arrangement", f"unknown CPF contribution arrangement {arrangement!r}",
        )
    return f"SPR{spr_year}_{arrangement}", RESIDENCY_SPR


def _in_band(row, amount: Decimal) -> bool:
    lower_ok = amount >= row.min_amount if row.min_amount == _ZERO else amount > row.min_amount
    upper_ok = row.max_amount is None or amount <= row.max_amount
    return lower_ok and upper_ok


def select_cpf_band(slabs, cohort: str, age_band: str, total_wages: Decimal):
    rows = [
        s for s in slabs
        if getattr(s, "rule_type", None) == CPF_RATE_BAND
        and getattr(s, "filing_status", None) == cohort
        and getattr(s, "tax_regime", None) == age_band
    ]
    matches = [r for r in rows if _in_band(r, total_wages)]
    if len(matches) != 1:
        raise SingaporeCalculationBlockedError(
            f"cpf:{cohort}:{age_band}",
            "CPF rate unavailable for employee cohort — authoritative CPF rule required "
            f"(cohort {cohort}, age band {age_band}, total wages {total_wages})"
            if not matches else
            f"overlapping CPF rules for cohort {cohort}, age band {age_band} — configuration invalid",
        )
    return matches[0]


def _dollar_half_up(value: Decimal) -> Decimal:
    return value.quantize(_ONE, rounding=ROUND_HALF_UP)


def _dollar_down(value: Decimal) -> Decimal:
    return value.quantize(_ONE, rounding=ROUND_FLOOR)


def cpf_raw_for_row(row, wages_subject: Decimal):
    """(total_raw, employee_raw) for one CPF_RATE_BAND row applied to the
    month's wages subject to CPF — unrounded; rounding happens once per
    month over every OW/AW chunk (CPF rate table note 4). The row itself
    was selected by total wages BEFORE capping (CPF Board AW example 16)."""
    basis = getattr(row, "assessment_basis", None)
    employer_pct = (row.employer_rate_pct or _ZERO) / _HUNDRED
    if basis == "NIL":
        return _ZERO, _ZERO
    if basis == "ER_ONLY":
        return employer_pct * wages_subject, _ZERO
    if basis == "PHASE_IN":
        employee_raw = (row.rate_pct / _HUNDRED) * (wages_subject - row.min_amount)
        return employer_pct * wages_subject + employee_raw, employee_raw
    if basis == "FULL":
        employee_pct = row.rate_pct / _HUNDRED
        return (employee_pct + employer_pct) * wages_subject, employee_pct * wages_subject
    raise SingaporeCalculationBlockedError(
        f"cpf_formula:{row.rate_label}", f"unknown CPF formula type {basis!r} on rule {row.rate_label}",
    )


def round_cpf(total_raw: Decimal, employee_raw: Decimal):
    """SG-008 / CPF rate table steps 1–3: total to the nearest dollar,
    employee share rounded down, employer = total − employee."""
    total = _dollar_half_up(total_raw)
    employee = _dollar_down(employee_raw)
    return total, employee, total - employee


def calculate_cpf(row, total_wages: Decimal, cpf_base: Decimal):
    """Single-row convenience (no AW catch-up): FULL rows apply to the
    capped OW + subject AW (`cpf_base`); low-wage rows to total wages."""
    wages = cpf_base if getattr(row, "assessment_basis", None) == "FULL" else total_wages
    return round_cpf(*cpf_raw_for_row(row, wages))


def calculate_sdl(rate_map: dict, total_wages: Decimal) -> Decimal:
    """SDL: rate × total wages, clamped to [min, max] — employer cost."""
    rate = _param(rate_map, "sdl", _SG_SDL_RATE, side="employer")
    minimum = _param(rate_map, "sdl_min_monthly", _SG_SDL_MIN_MONTHLY)
    maximum = _param(rate_map, "sdl_max_monthly", _SG_SDL_MAX_MONTHLY)
    if total_wages <= _ZERO:
        return _ZERO
    return min(max(_round2(rate * total_wages), minimum), maximum)


def parse_shg_instruction(value):
    """`sgp_shg_funds` holds an authority/HR-derived fund code list
    ("CDAC", "MBMF,SINDA", or "NONE") — never race/religion attributes
    (SG-015) — optionally with the employee's instructed monthly amount for
    a fund ("MBMF=10.00"): CPF Board SHG page, "Employees who do not wish to
    contribute or wish to contribute a different amount can contact the
    respective SHGs". The instructed amount replaces that fund's band
    amount; no alternate value is ever assumed (employee_validation requires
    the SHG evidence reference with it). Unset BLOCKS: the SHG
    determination must be made explicitly. Returns (codes, {fund: amount})."""
    if value is None or not str(value).strip():
        raise SingaporeCalculationBlockedError(
            "sgp_shg_funds", "SHG determination is required (use NONE when no fund applies)",
        )
    codes, overrides = [], {}
    for part in (p.strip().upper() for p in str(value).split(",") if p.strip()):
        code, _, amount = part.partition("=")
        code = code.strip()
        if amount:
            try:
                instructed = Decimal(amount.strip())
            except Exception:
                raise SingaporeCalculationBlockedError("sgp_shg_funds", f"invalid SHG instructed amount in {value!r}")
            if instructed < _ZERO or instructed != instructed.quantize(Decimal("0.01")):
                raise SingaporeCalculationBlockedError("sgp_shg_funds", f"invalid SHG instructed amount in {value!r}")
            overrides[code] = instructed
        codes.append(code)
    if codes == ["NONE"]:
        return [], {}
    unknown = [c for c in codes if c not in SHG_FUNDS]
    if unknown or "NONE" in codes:
        raise SingaporeCalculationBlockedError("sgp_shg_funds", f"invalid SHG fund code(s) {value!r}")
    return list(dict.fromkeys(codes)), overrides


def parse_shg_funds(value):
    return parse_shg_instruction(value)[0]


def validate_shg_eligibility(funds, effective_residency: str, work_pass: str) -> None:
    """A fund code the employee cannot legally belong to (CPF Board SHG
    page) is a contradictory fact — BLOCKED, never silently dropped."""
    for fund in funds:
        rule = _SHG_ELIGIBILITY[fund]
        if effective_residency in (RESIDENCY_SC, RESIDENCY_SPR):
            continue
        allowed = rule["foreign_passes"]
        if allowed is not None and work_pass not in allowed:
            raise SingaporeCalculationBlockedError(
                "sgp_shg_funds",
                f"{fund} applies only to Singapore Citizens / SPRs"
                + (f" and {', '.join(allowed)} holders" if allowed else "")
                + f" — not to a foreign employee on {work_pass} (contradictory facts)",
            )


def calculate_shg(slabs, funds, total_wages: Decimal) -> dict:
    return {fund: row.flat_amount for fund, row in shg_rows_for(slabs, funds, total_wages).items()}


def shg_rows_for(slabs, funds, total_wages: Decimal) -> dict:
    out = {}
    for fund in funds:
        rows = [s for s in slabs if getattr(s, "rule_type", None) == SHG_FUND_BAND and getattr(s, "filing_status", None) == fund]
        matches = [r for r in rows if _in_band(r, total_wages)]
        if len(matches) != 1:
            raise SingaporeCalculationBlockedError(
                f"shg:{fund}",
                f"{fund} contribution band unavailable for total wages {total_wages} — authoritative SHG rule required"
                if not matches else f"overlapping {fund} bands — configuration invalid",
            )
        out[fund] = matches[0]
    return out


def _is_final_month(ctx, month_start: date, month_end: date) -> bool:
    """December, or the last month of employment — or any later month of the
    same year (AW paid after leaving, CPF Board examples 7/8/9) — where the
    AW ceiling is re-calculated on ACTUAL OW."""
    if month_start.month == 12:
        return True
    leaving = getattr(ctx, "date_of_leaving", None)
    return leaving is not None and leaving.year == month_start.year and leaving <= month_end


def _remaining_months_after(ctx, month_start: date) -> int:
    """Months of employment still to come in the calendar year AFTER this
    wage month, for the OW estimate (CPF Board: "estimate the AW ceiling by
    using the current year's estimated monthly OW")."""
    end_month = 12
    leaving = getattr(ctx, "date_of_leaving", None)
    if leaving is not None and leaving.year == month_start.year:
        end_month = leaving.month
    return max(end_month - month_start.month, 0)


def _ledger_remainders(ledger):
    """Earlier AW payments of the year not yet fully CPF-subject, oldest
    first. Each entry is ONE AW payment (several may share a wage month,
    e.g. a salary run and an off-cycle bonus run) and carries the rates,
    rule and pack in force when that payment was made — so two same-month
    payments under different rates each keep their own shortfall rate."""
    rows = []
    for entry in sorted(ledger or [], key=lambda e: (e["month"], str(e.get("paymentId") or ""))):
        remaining = Decimal(str(entry["awPaid"])) - Decimal(str(entry.get("awSubjected", "0")))
        if remaining > _ZERO:
            rows.append((entry, remaining))
    return rows


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "", "None") else _ZERO


def month_to_date(ctx, wage_month: str) -> dict:
    """Earlier payments of this wage month (ctx.sgp_month_to_date — prior
    payslips' persisted traces), summed. CPF, SDL, SHG and the S Pass levy
    are all defined per CALENDAR MONTH of total wages (CPF rate tables;
    CPF Board SDL page "0.25% of the monthly total wages"; MOM monthly
    levy), so a second payment in the month is calculated on the month's
    combined wages and books only the difference. Traces written before
    this existed carry the same fields, so they sum the same way."""
    out = {
        "payments": [], "ow_actual": _ZERO, "aw_actual": _ZERO, "ow_subject": _ZERO, "aw_current_subject": _ZERO,
        "shortfall_total_raw": _ZERO, "shortfall_employee_raw": _ZERO,
        "employee_cpf": _ZERO, "employer_cpf": _ZERO, "sdl": _ZERO, "fwl": _ZERO, "shg": {},
        "cohorts": set(), "age_bands": set(),
    }
    for entry in ctx.sgp_month_to_date or []:
        if entry.get("wageMonth") != wage_month:
            continue
        inputs, cpf, result = entry.get("inputs") or {}, entry.get("cpf") or {}, entry.get("result") or {}
        aw = cpf.get("additionalWages") or {}
        out["payments"].append(entry.get("paymentId"))
        out["ow_actual"] += _dec(inputs.get("ordinaryWages"))
        out["aw_actual"] += _dec(inputs.get("additionalWages"))
        out["ow_subject"] += _dec(cpf.get("owSubject"))
        out["aw_current_subject"] += _dec(aw.get("awSubjectThisPayment"))
        for alloc in aw.get("allocations") or []:
            if alloc.get("kind") == "SHORTFALL":
                amount = _dec(alloc.get("amount"))
                out["shortfall_total_raw"] += _dec(alloc.get("totalRatePct")) / _HUNDRED * amount
                out["shortfall_employee_raw"] += _dec(alloc.get("employeeRatePct")) / _HUNDRED * amount
        out["employee_cpf"] += _dec(result.get("employeeCpf"))
        out["employer_cpf"] += _dec(result.get("employerCpf"))
        out["sdl"] += _dec(result.get("sdl"))
        out["fwl"] += _dec(result.get("fwl"))
        for fund, detail in ((entry.get("shg") or {}).get("funds") or {}).items():
            out["shg"][fund] = out["shg"].get(fund, _ZERO) + _dec((detail or {}).get("amount"))
        out["cohorts"].add(entry.get("cohort"))
        if cpf.get("ageBand"):
            out["age_bands"].add(cpf["ageBand"])
    return out


def _book_difference(key: str, month_amount: Decimal, booked: Decimal) -> Decimal:
    """This payment's share of a monthly amount = month total − already
    booked. A negative difference means an earlier payment of the month
    was over-charged: that is a correction/refund, never netted here."""
    diff = month_amount - booked
    if diff < _ZERO:
        raise SingaporeCalculationBlockedError(
            key, f"the month's recalculated {key} ({month_amount}) is below the amount already booked on earlier "
                 f"payslips of the same wage month ({booked}) — correct the earlier payslip; refunds are not netted",
        )
    return diff


def calculate_cpf_month(ctx, row, cohort, age_band, month_start, month_end, ow_actual, aw_actual, total_wages, mtd=None):
    """The CPF engine for one wage month — OW ceiling, Option A AW ceiling
    (estimated / final), catch-up of earlier AW at each payment's own
    rates, excess reporting, single rounding. `total_wages` and the OW
    ceiling are the MONTH's (earlier same-month payments in `mtd` plus this
    one); the contribution returned is this payment's difference.
    Returns (totals, ytd, trace)."""
    rate_map = ctx.rate_map
    mtd = mtd or month_to_date(ctx, month_start.strftime("%Y-%m"))
    ow_ceiling = _param(rate_map, "cpf_ow_ceiling_monthly", _SG_CPF_OW_CEILING_MONTHLY)
    annual_ceiling = _param(rate_map, "cpf_annual_wage_ceiling", _SG_CPF_ANNUAL_WAGE_CEILING)
    month_ow_subject = min(mtd["ow_actual"] + ow_actual, ow_ceiling)
    # This payment's OW subject: the room left under the MONTHLY ceiling.
    ow_subject = max(month_ow_subject - mtd["ow_subject"], _ZERO)

    ytd_ow_before = ctx.ytd_cpf_ow_subject_before
    ytd_aw_subject_before = ctx.ytd_cpf_aw_subject_before
    ytd_aw_paid_before = ctx.ytd_cpf_aw_paid_before
    if ytd_aw_paid_before is None and ytd_aw_subject_before is not None:
        ytd_aw_paid_before = ytd_aw_subject_before  # no separate paid figure loaded → no outstanding AW known
    ytd_loaded = ytd_ow_before is not None and ytd_aw_subject_before is not None
    if aw_actual > _ZERO and not ytd_loaded:
        raise SingaporeCalculationBlockedError(
            "ytd_cpf_accumulator", "Additional Wages need the YTD CPF accumulator to apply the annual AW ceiling",
        )

    is_final = _is_final_month(ctx, month_start, month_end)
    current_is_full = getattr(row, "assessment_basis", None) == "FULL"
    employee_pct = row.rate_pct if current_is_full else None
    total_pct = (row.rate_pct + (row.employer_rate_pct or _ZERO)) if current_is_full else None

    aw = {"awPaid": str(aw_actual), "ceilingBasis": None}
    allocations = []
    excess = None
    current_aw_subject = _ZERO
    shortfall_total = _ZERO
    total_raw = employee_raw = _ZERO

    if ytd_loaded:
        months_after = 0 if is_final else _remaining_months_after(ctx, month_start)
        # ytd_ow_before already holds earlier same-month OW subject; the
        # forward estimate uses the whole month's OW subject.
        estimated_annual_ow = ytd_ow_before + ow_subject + month_ow_subject * months_after
        ceiling = max(annual_ceiling - estimated_annual_ow, _ZERO)
        room = ceiling - ytd_aw_subject_before
        aw.update({
            "ceilingBasis": "FINAL_ACTUAL" if is_final else "ESTIMATED",
            "ytdOwSubjectBefore": str(ytd_ow_before), "ytdAwSubjectBefore": str(ytd_aw_subject_before),
            "ytdAwPaidBefore": str(ytd_aw_paid_before),
            "owSubjectThisMonth": str(month_ow_subject), "estimatedMonthsRemaining": months_after,
            "annualOwUsed": str(estimated_annual_ow), "annualWageCeiling": str(annual_ceiling),
            "awCeiling": str(ceiling), "awCeilingRemaining": str(max(room, _ZERO)),
        })
        if room < _ZERO:
            # Ceiling fell below AW already contributed on (e.g. OW rose) —
            # CPF Board: submit a refund application. Never netted here.
            excess = {
                "excessAwSubject": str(-room),
                "treatment": "REFUND_APPLICATION_REQUIRED — excess CPF on AW is not netted from this payroll",
            }
        available = max(room, _ZERO)

        if is_final:
            outstanding = ytd_aw_paid_before - ytd_aw_subject_before
            remainders = _ledger_remainders(getattr(ctx, "sgp_aw_ledger", None))
            if outstanding > _ZERO and sum((r for _, r in remainders), _ZERO) != outstanding:
                raise SingaporeCalculationBlockedError(
                    "sgp_aw_ledger",
                    "earlier AW not yet CPF-subject exists but the per-payment AW ledger (prior payslip traces) does "
                    "not reconcile to the YTD accumulator — the final AW-ceiling true-up cannot be computed",
                )
            for entry, remaining in remainders:
                if available <= _ZERO:
                    break
                if entry.get("formulaType") != "FULL":
                    raise SingaporeCalculationBlockedError(
                        "sgp_aw_ledger",
                        f"AW paid in {entry['month']} was under a {entry.get('formulaType')} (low-wage) CPF row — the "
                        "shortfall rate for that payment is not defined by a full-rate row",
                    )
                take = min(remaining, available)
                available -= take
                shortfall_total += take
                e_pct, t_pct = Decimal(str(entry["eePct"])), Decimal(str(entry["totalPct"]))
                total_raw += t_pct / _HUNDRED * take
                employee_raw += e_pct / _HUNDRED * take
                allocations.append({
                    "kind": "SHORTFALL", "sourceMonth": entry["month"], "sourcePaymentId": entry.get("paymentId"),
                    "amount": str(take),
                    "employeeRatePct": str(e_pct), "totalRatePct": str(t_pct), "rule": entry.get("rule"),
                    "ruleRef": entry.get("ruleRef"),
                    "reason": "AW ceiling re-calculated on actual OW (December / last month of employment); "
                              "shortfall at the contribution rates of the month the AW was paid",
                })

        current_aw_subject = min(aw_actual, available)

    # The month's wages subject — OW under the monthly ceiling plus every
    # current-AW chunk of the month — at the ONE row the month's total wages
    # select; earlier same-month shortfalls keep their own rates. Rounded
    # once for the month; this payment books month total − already booked.
    wages_subject = month_ow_subject + mtd["aw_current_subject"] + current_aw_subject
    row_total_raw, row_employee_raw = cpf_raw_for_row(row, wages_subject if current_is_full else min(total_wages, wages_subject))
    total_raw += row_total_raw + mtd["shortfall_total_raw"]
    employee_raw += row_employee_raw + mtd["shortfall_employee_raw"]
    if current_aw_subject > _ZERO:
        allocations.append({
            "kind": "CURRENT", "sourceMonth": month_start.strftime("%Y-%m"), "amount": str(current_aw_subject),
            "employeeRatePct": None if employee_pct is None else str(employee_pct),
            "totalRatePct": None if total_pct is None else str(total_pct), "rule": row.rate_label,
        })

    month_total, month_employee, month_employer = round_cpf(total_raw, employee_raw)
    total = _book_difference("cpf_total", month_total, mtd["employee_cpf"] + mtd["employer_cpf"])
    employee = _book_difference("cpf_employee", month_employee, mtd["employee_cpf"])
    employer = _book_difference("cpf_employer", month_employer, mtd["employer_cpf"])
    ytd = dict(
        ow_after=(ytd_ow_before + ow_subject) if ytd_loaded else None,
        aw_subject_after=(ytd_aw_subject_before + current_aw_subject + shortfall_total) if ytd_loaded else None,
        aw_paid_after=(ytd_aw_paid_before + aw_actual) if ytd_loaded else None,
    )
    aw.update({"awSubjectThisPayment": str(current_aw_subject), "shortfallAwSubject": str(shortfall_total),
               "allocations": allocations, "excess": excess})
    if aw_actual > _ZERO:
        # This payment's own ledger entry — later final-month true-ups read
        # it from this payslip's persisted trace. service._load_sg_aw_ledger
        # stamps paymentId (the payslip) on it and grows awSubjected by every
        # later SHORTFALL allocation naming that sourcePaymentId.
        aw["ledgerEntry"] = {
            "month": month_start.strftime("%Y-%m"), "awPaid": str(aw_actual), "awSubjected": str(current_aw_subject),
            "formulaType": row.assessment_basis, "rule": row.rate_label, "ruleRef": _row_ref(row),
            "eePct": None if employee_pct is None else str(employee_pct),
            "totalPct": None if total_pct is None else str(total_pct),
        }
    trace = {
        "cohort": cohort, "ageBand": age_band, "rule": row.rate_label, "formulaType": row.assessment_basis,
        "ruleRef": _row_ref(row),
        "employeeRatePct": str(row.rate_pct), "employerRatePct": str(row.employer_rate_pct),
        "owActual": str(ow_actual), "owCeiling": str(ow_ceiling), "owSubject": str(ow_subject),
        "owCeilingRef": _row_ref(rate_map.get("cpf_ow_ceiling_monthly")),
        "annualCeilingRef": _row_ref(rate_map.get("cpf_annual_wage_ceiling")),
        "wagesSubjectThisMonth": str(wages_subject + shortfall_total),
        "additionalWages": aw,
        "rounding": {
            "totalRaw": str(total_raw), "employeeRaw": str(employee_raw),
            "total": str(total), "employee": str(employee), "employer": str(employer),
            "method": "total to nearest dollar (half up); employee share rounded down; employer = total − employee; "
                      "OW and all AW chunks of the month summed before rounding",
        },
        "specClarification": SPEC_CLARIFICATION_SG_007,
    }
    if mtd["payments"]:
        trace["rounding"].update({
            "monthTotal": str(month_total), "monthEmployee": str(month_employee), "monthEmployer": str(month_employer),
            "bookedEarlierThisMonth": {"employee": str(mtd["employee_cpf"]), "employer": str(mtd["employer_cpf"])},
            "method": trace["rounding"]["method"] + "; the month is recalculated on all its payments and this "
                      "payslip books month total − amounts already booked this month",
        })
        trace["monthOwSubject"] = str(month_ow_subject)
        trace["monthTotalWages"] = str(total_wages)
    return (total, employee, employer), ytd, trace


# Work Permit levy (Phase 5 STEP 8) — MOM "<sector> sector: Work Permit
# requirements" pages (retrieved 2026-09-24, hashed SourceArtifacts): the
# monthly levy by sector × levy tier (MOM-allocated quota tier for
# services/manufacturing; source category for construction/process) ×
# skill (Higher-skilled R1 / Basic-skilled R2); marine shipyard has one
# tier. Every page: "The daily levy rate only applies to Work Permit
# holders who did not work for a full calendar month … (Monthly levy rate x
# 12) / 365 = rounding up to the nearest cent"; MOM "Foreign worker quota
# and levy requirements": liability "will start from the day the Temporary
# Work Permit or Work Permit is issued … It ends when the permit is
# cancelled or expires" — the end day's inclusivity is not stated, so a
# permit ending within the month needs fwl_work_permit_end_day_basis (not
# seeded → BLOCKED). Rates are ContributionRate rows keyed by
# work_permit_levy_key(); no rate is hard-coded here.
WP_TIERS_BY_SECTOR = {
    "SERVICES": ("TIER_1", "TIER_2", "TIER_3"),
    "MANUFACTURING": ("TIER_1", "TIER_2", "TIER_3"),
    "CONSTRUCTION": ("NTS", "MYS_NAS_PRC", "OFFSITE", "NO_CERT"),
    "PROCESS": ("NTS", "MYS_NAS_PRC"),
    "MARINE_SHIPYARD": ("ALL",),
}
WP_SKILLS = ("R1", "R2")


def work_permit_levy_key(sector: str, tier: str, skill: str) -> str:
    """ContributionRate.component_key of a Work Permit monthly levy row. A
    construction permit issued without the required certification is levied
    one rate regardless of source/skill (MOM construction page) → skill ANY."""
    return f"fwl_wp__{sector}__{tier}__{'ANY' if tier == 'NO_CERT' else skill}"


def _work_permit_levy(ctx, month_start, month_end):
    sector = getattr(ctx, "sgp_wp_sector", None)
    skill = getattr(ctx, "sgp_wp_skill_level", None)
    tier = getattr(ctx, "sgp_wp_levy_tier", None) or ("ALL" if sector == "MARINE_SHIPYARD" else None)
    if sector not in WP_TIERS_BY_SECTOR or skill not in WP_SKILLS or tier is None:
        return _ZERO, {"status": "BLOCKED", "detail": "Work Permit levy needs the worker's MOM sector, skill level (R1/R2) "
                       "and levy tier as allocated on the MOM levy bill — not recorded"}
    if tier not in WP_TIERS_BY_SECTOR[sector]:
        return _ZERO, {"status": "BLOCKED", "detail": f"levy tier {tier} does not exist for the {sector} sector (MOM)"}
    key = work_permit_levy_key(sector, tier, skill)
    row = _row_in_force(ctx.rate_map.get(key), month_end)
    if row is None or row.flat_amount is None:
        return _ZERO, {"status": "BLOCKED", "detail": f"BLOCKED — AUTHORITATIVE VALUE REQUIRED: no MOM Work Permit levy row "
                       f"{key} in force for {month_start.strftime('%Y-%m')}", "levyKey": key}
    amount, trace = _pass_levy(ctx, row, month_start, month_end, "fwl_work_permit_end_day_basis", "Work Permit")
    trace.update({"levyKey": key, "sector": sector, "tier": tier, "skill": skill})
    return amount, trace


def _fwl(ctx, effective_residency, month_start, month_end):
    """Foreign Worker Levy — employer cost only (SG-016)."""
    work_pass = ctx.sgp_work_pass_type
    if effective_residency != RESIDENCY_FOREIGN:
        return _ZERO, {"status": "NOT_APPLICABLE"}
    if work_pass == "EP":
        return _ZERO, {"status": "NOT_APPLICABLE", "detail": "No foreign worker levy for Employment Pass holders"}
    if work_pass == "WORK_PERMIT":
        return _work_permit_levy(ctx, month_start, month_end)
    # S Pass
    row = ctx.rate_map.get("fwl_s_pass_monthly")
    if row is None or row.flat_amount is None:
        return _ZERO, {"status": "BLOCKED", "detail": "BLOCKED — AUTHORITATIVE VALUE REQUIRED: fwl_s_pass_monthly not configured"}
    return _pass_levy(ctx, row, month_start, month_end, "fwl_s_pass_end_day_basis", "S Pass")


def _pass_levy(ctx, row, month_start, month_end, end_basis_key, label):
    issued = getattr(ctx, "sgp_work_pass_issue_date", None)
    ends = getattr(ctx, "sgp_work_pass_end_date", None)
    if issued is None and ends is None:
        # Pass validity not captured: a month the employment fully spans is
        # levied in full; a partial month is never guessed from employment dates.
        joined = getattr(ctx, "date_of_joining", None)
        leaving = getattr(ctx, "date_of_leaving", None)
        if (joined is not None and joined > month_start) or (leaving is not None and leaving < month_end):
            return _ZERO, {"status": "BLOCKED", "detail": f"Partial month — MOM's daily {label} levy runs from pass issue to "
                           "cancellation; pass validity dates are not captured, so the levy is not calculated",
                           "ref": _row_ref(row)}
        return row.flat_amount, {"status": "CALCULATED", "amount": str(row.flat_amount), "treatment": "EMPLOYER_COST",
                                 "basis": "FULL_MONTH", "ref": _row_ref(row)}
    return _s_pass_levy_for_validity(ctx, row, issued, ends, month_start, month_end, end_basis_key=end_basis_key, label=label)


def _ceil_cent(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def _s_pass_levy_for_validity(ctx, row, issued, ends, month_start, month_end,
                              end_basis_key="fwl_s_pass_end_day_basis", label="S Pass"):
    """S Pass levy from the pass validity window (SourceArtifact
    mom_spass_levy, MOM "S Pass quota and levy requirements"): "The levy
    liability starts from the day the S Pass is issued and ends when the
    pass is cancelled or expires"; a full calendar month is the monthly
    rate; otherwise "The daily levy rate … (Monthly levy rate x 12) / 365 =
    rounding up to the nearest cent" per day of liability. The issue day is
    levied. For a CANCELLED pass MOM's cancellation pages state "When levy
    stops: 1 day before cancellation" — the `*_cancellation_end_day_basis`
    row (EXCLUSIVE, sourced). For an EXPIRED pass, or when the end reason is
    not captured, the end-day rule is NOT published, so the pass needs the
    `fwl_s_pass_end_day_basis` / `fwl_work_permit_end_day_basis` row
    (INCLUSIVE | EXCLUSIVE) — not seeded, so that case BLOCKS until an
    authoritative value is recorded."""
    monthly = row.flat_amount
    ref = _row_ref(row)
    base = {"treatment": "EMPLOYER_COST", "ref": ref, "passIssueDate": issued.isoformat() if issued else None,
            "passEndDate": ends.isoformat() if ends else None}
    if (issued is not None and issued > month_end) or (ends is not None and ends < month_start):
        return _ZERO, {**base, "status": "CALCULATED", "amount": "0", "basis": "PASS_NOT_VALID_THIS_MONTH"}
    start = max(issued or month_start, month_start)
    end = month_end
    if ends is not None and ends <= month_end:
        reason = (getattr(ctx, "sgp_work_pass_end_reason", None) or "").upper() or None
        rule_key = end_basis_key.replace("_end_day_basis", "_cancellation_end_day_basis") if reason == "CANCELLED" \
            else end_basis_key
        basis_row = ctx.rate_map.get(rule_key)
        end_basis = getattr(basis_row, "text_value", None) if basis_row is not None else None
        base["endReason"] = reason
        if end_basis not in ("INCLUSIVE", "EXCLUSIVE"):
            what = ("cancellation" if reason == "CANCELLED" else "expiry" if reason == "EXPIRED"
                    else "cancellation / expiry (end reason not captured)")
            return _ZERO, {**base, "status": "BLOCKED",
                           "detail": f"BLOCKED — AUTHORITATIVE VALUE REQUIRED: the pass ends within this month by {what} "
                                     f"and no {label} end-day rule is configured ({rule_key})"}
        end = ends if end_basis == "INCLUSIVE" else ends - timedelta(days=1)
        base["endDayBasis"] = end_basis
        base["endDayBasisRef"] = _row_ref(basis_row)
    days = max((end - start).days + 1, 0)
    month_days = (month_end - month_start).days + 1
    if days == month_days:
        return monthly, {**base, "status": "CALCULATED", "amount": str(monthly), "basis": "FULL_MONTH"}
    daily = _ceil_cent(monthly * 12 / Decimal("365"))
    amount = daily * days
    return amount, {**base, "status": "CALCULATED", "amount": str(amount), "basis": "DAILY",
                    "dailyRate": str(daily), "daysLevied": days, "monthDays": month_days,
                    "leviedFrom": start.isoformat(), "leviedTo": end.isoformat(),
                    "method": "(monthly levy × 12) / 365 rounded up to the nearest cent, × days of liability in the month"}


def _row_in_force(row, on: date):
    """Defensive effective-window check on a single rate_map row — the
    canonical resolver already filters by date, but an org-scoped rate_map
    is not date-aware, and a row outside its own window must never be used."""
    if row is None:
        return None
    start, end = getattr(row, "effective_from", None), getattr(row, "effective_to", None)
    if (start is not None and start > on) or (end is not None and end < on):
        return None
    return row


def _lqs(ctx, effective_residency, ow_actual, wage_date=None):
    """LQS check for employers hiring foreign workers — a compliance flag,
    never a deduction or pay adjustment. Evaluated for the wage month."""
    wage_date = wage_date or ctx.pay_date
    hires_foreign = getattr(ctx, "sgp_employer_hires_foreign_workers", None)
    if not hires_foreign:
        return {"status": "NOT_APPLICABLE" if hires_foreign is False else "NOT_EVALUATED",
                "detail": "Employer does not hire foreign workers" if hires_foreign is False
                else "Employer foreign-workforce status not supplied"}
    if effective_residency == RESIDENCY_FOREIGN:
        return {"status": "NOT_APPLICABLE", "detail": "LQS applies to local employees only"}
    if (getattr(ctx, "employment_type", None) or "") == "Part-time":
        row = _row_in_force(ctx.rate_map.get("lqs_part_time_hourly"), wage_date)
        if row is None or row.flat_amount is None:
            return {"status": "BLOCKED", "detail": "BLOCKED — AUTHORITATIVE VALUE REQUIRED: no part-time LQS row for this date"}
        hours = (getattr(ctx, "sgp_employment_facts", None) or {}).get("hoursWorked")
        if not hours or Decimal(str(hours)) <= _ZERO:
            return {"status": "BLOCKED", "threshold": str(row.flat_amount), "ref": _row_ref(row),
                    "detail": "Part-time LQS is an hourly test (monthly gross ÷ total hours worked) — no attendance hours "
                              "recorded for the month"}
        # MOM LQS page: "(total monthly gross wages) ÷ (total hours worked for the month)".
        hourly = (ow_actual / Decimal(str(hours))).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
        return {"status": "MEETS_LQS" if hourly >= row.flat_amount else "BELOW_LQS", "threshold": str(row.flat_amount),
                "hoursWorked": str(hours), "hourlyGross": str(hourly), "wagesTested": str(ow_actual), "ref": _row_ref(row),
                "basis": "part-time: monthly gross wages (excluding Additional Wages) ÷ attendance hours worked"}
    row = _row_in_force(ctx.rate_map.get("lqs_full_time_monthly"), wage_date)
    if row is None or row.flat_amount is None:
        return {"status": "BLOCKED", "detail": "BLOCKED — AUTHORITATIVE VALUE REQUIRED: no full-time LQS row for this date"}
    status = "MEETS_LQS" if ow_actual >= row.flat_amount else "BELOW_LQS"
    return {"status": status, "threshold": str(row.flat_amount), "wagesTested": str(ow_actual),
            "basis": "monthly gross wages excluding Additional Wages", "ref": _row_ref(row),
            "note": "Full-time (35–44 h/week); the MOM overtime uplift above 44 h/week needs hours worked and is not evaluated"}


def _ir21(ctx, effective_residency, month_end):
    leaving = getattr(ctx, "date_of_leaving", None)
    if effective_residency == RESIDENCY_SC:
        return {"status": "NOT_REQUIRED", "detail": "Singapore Citizen"}
    if leaving is None:
        return {"status": "NOT_TRIGGERED", "detail": "No cessation recorded (overseas posting / departure > 3 months are not captured)"}
    lead = ctx.rate_map.get("ir21_filing_lead_months")
    months = int(lead.flat_amount) if lead is not None and lead.flat_amount is not None else None
    file_by = ir21_file_by(leaving, months) if months is not None else None
    return {
        "status": "TRIGGERED" if leaving >= month_end.replace(day=1) else "TRIGGERED_PAST_CESSATION",
        "cessationDate": leaving.isoformat(),
        "fileBy": file_by.isoformat() if file_by else None,
        "workflow": "Open an IR21 case (sgp_ir21_cases): monies due are held from the date the employer is aware "
                    "until IRAS clearance and an approved release — the case, not this trace, controls payment",
        "ref": _row_ref(lead),
    }


def ir21_file_by(trigger_date: date, lead_months: int) -> date:
    """IRAS: file the Form IR21 at least `lead_months` (the pack's
    ir21_filing_lead_months, one month) before cessation / overseas posting
    / departure — the same calendar date that many months earlier, clamped
    to the month's last day."""
    m = trigger_date.month - lead_months
    y = trigger_date.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return trigger_date.replace(year=y, month=m, day=min(trigger_date.day, calendar.monthrange(y, m)[1]))


# CPF wage classification (SG-010/SG-011) — which earning components are
# Ordinary Wages, Additional Wages or not CPF wages at all. Components are
# the same named pay components AU/CA classify (engine/countries/
# australia.py _calculate_au_program_wages); rules come from the shared
# TaxabilityRule table (tax_component "cpf_ordinary_wages" /
# "cpf_additional_wages", is_taxable = belongs to that class).
CPF_OW_COMPONENT = "cpf_ordinary_wages"
CPF_AW_COMPONENT = "cpf_additional_wages"
_DEFAULT_WAGE_CLASS = {
    "basic": "OW", "hra": "OW", "special_allowance": "OW", "overtime": "OW", "named_allowances": "OW",
    "additional_compensation": "AW",
}
# A named allowance (the org's PolicyAllowanceComponent, one PayslipAllowanceItem
# per payslip) is its own earning component "allowance:<key>" — default OW
# like every other monthly allowance; a TaxabilityRule on that earning_type
# reclassifies just that allowance.
ALLOWANCE_COMPONENT_PREFIX = "allowance:"


def _default_wage_class(component: str) -> str:
    return "OW" if component.startswith(ALLOWANCE_COMPONENT_PREFIX) else _DEFAULT_WAGE_CLASS[component]


def earning_components(ctx: PayrollContext, _raw: bool = False) -> tuple:
    """The payslip's earning components (conservation: they always sum to
    exactly ctx.gross) and their display labels. Named allowances are the
    remainder of gross; when the per-allowance breakdown is supplied
    (sgp_named_allowance_items) each allowance becomes its own component and
    only an unexplained remainder stays "named_allowances". A breakdown that
    exceeds the remainder is not trusted (kept as one lump)."""
    # A caller that passes basic = gross with additional compensation on top
    # (preview/golden contexts) has basic reduced by the overshoot, so no
    # dollar is ever counted twice.
    basic = ctx.basic or _ZERO
    named_allowances = ctx.gross - basic - ctx.hra - ctx.special_allowance - ctx.overtime - ctx.additional_compensation
    if named_allowances < _ZERO:
        basic = max(basic + named_allowances, _ZERO)
        named_allowances = _ZERO
    components = {
        "basic": basic, "hra": ctx.hra, "special_allowance": ctx.special_allowance,
        "overtime": ctx.overtime, "additional_compensation": ctx.additional_compensation,
    }
    labels = {}
    items = [{**i, "amount": Decimal(str(i.get("amount") or 0))} for i in (getattr(ctx, "sgp_named_allowance_items", None) or [])]
    items = [i for i in items if i["amount"] > _ZERO]
    itemised = sum((Decimal(str(i["amount"])) for i in items), _ZERO)
    if items and itemised <= named_allowances:
        for i in items:
            key = f"{ALLOWANCE_COMPONENT_PREFIX}{i['key']}"
            components[key] = components.get(key, _ZERO) + Decimal(str(i["amount"]))
            labels[key] = i.get("label") or i["key"]
        named_allowances -= itemised
    components["named_allowances"] = named_allowances
    if _raw:
        return components, labels
    # Incomplete month (Phase 5.2): joining after the 1st, leaving before the
    # month end or no-pay leave — the salary payable is MOM's incomplete-month
    # salary, and CPF is computed on the Total Wages PAYABLE for the month
    # (CPF Board rate tables), so the unearned part of each gross-rate
    # component leaves the earning components.
    month = incomplete_month(ctx, components)
    if month is not None:
        for key, take in month["_allocation"].items():
            components[key] = components[key] - take
    return components, labels


def _raw_earning_components(ctx: PayrollContext) -> tuple:
    """earning_components before the incomplete-month reduction."""
    return earning_components(ctx, _raw=True)


# MOM "Calculation of Salary for Incomplete Month of Work" (incomplete-month.xls,
# 2025 / 2026 tables): Monday–Friday working days; a 5.5-day week works half a
# day on Saturday; a 6-day week works Saturday; Sunday is the default rest day.
# Public holidays that fall on a normal working day are working days. Weights
# are per weekday (Monday = 0).
SG_WORK_PATTERNS = {
    "5_DAY": {0: Decimal("1"), 1: Decimal("1"), 2: Decimal("1"), 3: Decimal("1"), 4: Decimal("1")},
    "5_5_DAY": {0: Decimal("1"), 1: Decimal("1"), 2: Decimal("1"), 3: Decimal("1"), 4: Decimal("1"), 5: Decimal("0.5")},
    "6_DAY": {0: Decimal("1"), 1: Decimal("1"), 2: Decimal("1"), 3: Decimal("1"), 4: Decimal("1"), 5: Decimal("1")},
}
# Rest / non-working days the MOM table assumes for each pattern.
_SG_PATTERN_REST_DAYS = {"5_DAY": ("SAT", "SUN"), "5_5_DAY": ("SUN",), "6_DAY": ("SUN",)}
INCOMPLETE_MONTH_SOURCE = ("MOM 'Monthly and daily salary: definitions and calculation' (incomplete month of work); "
                           "MOM 'Calculation of Salary for Incomplete Month of Work' table (incomplete-month.xls)")


def working_days(start: date, end: date, pattern: str) -> Decimal:
    """MOM working days between start and end inclusive for a work pattern
    (rest and non-working days excluded; public holidays included)."""
    weights = SG_WORK_PATTERNS[pattern]
    total, day = _ZERO, start
    while day <= end:
        total += weights.get(day.weekday(), _ZERO)
        day += timedelta(days=1)
    return total


def _employment_month(ctx: PayrollContext) -> tuple:
    """The calendar month the salary is for: the payroll period's month, or
    the pay-date month when no period is supplied."""
    anchor = getattr(ctx, "period_end", None) or ctx.pay_date
    return anchor.replace(day=1), _month_end(anchor)


def incomplete_month(ctx: PayrollContext, components: dict = None):
    """None for a complete month of work; otherwise MOM's incomplete-month
    salary:  monthly gross rate of pay ÷ working days in the month × days
    actually worked. "Incomplete month" (MOM): starts work after the first
    day of the month, leaves before the last day, or takes no-pay leave of
    one or more days. The monthly gross rate is the earning components whose
    eaGrossRate basis is INCLUDED (wage_bases — allowances in; overtime,
    bonus / AWS, reimbursements and travel / food / housing allowances out);
    the excluded monthly components are recorded, not pro-rated (no MOM
    rule). Days actually worked = working days of employment in the month
    less no-pay days (public holidays and paid leave count as worked).
    Fail-closed: no work pattern, a non-default rest day, a part-time
    employee, or unpaid days without their dates BLOCK."""
    if ctx.pay_date is None and getattr(ctx, "period_end", None) is None:
        return None
    month_start, month_end = _employment_month(ctx)
    joined, leaving = getattr(ctx, "date_of_joining", None), getattr(ctx, "date_of_leaving", None)
    start = max(month_start, joined) if joined else month_start
    end = min(month_end, leaving) if leaving else month_end
    if components is None:
        components, _labels = _raw_earning_components(ctx)
    if start > end:
        # Outside the employment: only payments carrying no salary for the
        # month (e.g. AW paid after leaving — CPF Board example 9) are valid.
        salary_parts = [k for k, a in components.items() if (a or _ZERO) > _ZERO
                        and wage_bases(k, _component_class(ctx, k)[0])["eaGrossRate"] == "INCLUDED"]
        if not salary_parts:
            return None
        raise SingaporeCalculationBlockedError(
            "employment_period",
            f"the employee is not employed during {month_start.strftime('%Y-%m')} (joined "
            f"{joined.isoformat() if joined else '—'}, left {leaving.isoformat() if leaving else '—'}) but the payslip carries salary ({', '.join(salary_parts)}) — no salary is payable for that month",
        )
    facts = getattr(ctx, "sgp_employment_facts", None) or {}
    unpaid_count = max(getattr(ctx, "unpaid_leave_days", 0) or 0, 0)
    if unpaid_count and "unpaidDates" not in facts:
        raise SingaporeCalculationBlockedError(
            "no_pay_leave_dates",
            f"{unpaid_count} no-pay day(s) without their dates — MOM's incomplete-month salary counts working days, "
            "so each no-pay date is needed",
        )
    unpaid_dates = sorted({date.fromisoformat(str(d)) for d in facts.get("unpaidDates") or []})
    in_employment = [d for d in unpaid_dates if start <= d <= end]
    reasons = [r for r, on in (("JOINED_AFTER_FIRST_DAY", start > month_start), ("LEFT_BEFORE_LAST_DAY", end < month_end),
                                 ("NO_PAY_LEAVE", bool(in_employment))) if on]
    if not reasons:
        return None
    pattern = facts.get("workPattern")
    if pattern not in SG_WORK_PATTERNS:
        raise SingaporeCalculationBlockedError(
            "ea_work_pattern",
            f"incomplete month ({', '.join(reasons)}): MOM's incomplete-month salary needs the working days of the "
            f"month — record the employee's work pattern (ea_work_pattern: {' / '.join(SG_WORK_PATTERNS)})",
        )
    rest_day = facts.get("restDay")
    if rest_day and rest_day not in _SG_PATTERN_REST_DAYS[pattern]:
        raise SingaporeCalculationBlockedError(
            "ea_rest_day",
            f"rest day {rest_day} with a {pattern} work pattern — MOM's working-day table assumes a Monday–Friday week "
            "with Sunday as the rest day; a different week needs the employer's own day schedule, which is not captured",
        )
    if (getattr(ctx, "employment_type", None) or "").strip().lower().replace("-", "_").replace(" ", "_") == "part_time":
        raise SingaporeCalculationBlockedError(
            "employment_type",
            "incomplete month for a part-time employee — MOM's formula is for monthly-rated full-time employees; the "
            "part-time rule is not evaluated (BLOCKED — AUTHORITATIVE EVIDENCE REQUIRED)",
        )
    weights = SG_WORK_PATTERNS[pattern]
    month_days = working_days(month_start, month_end, pattern)
    employed_days = working_days(start, end, pattern)
    counted = [d for d in in_employment if weights.get(d.weekday(), _ZERO) > _ZERO]
    # A half-day no-pay leave is half a day (MOM: a half-day is 5 hours or
    # less), never more than the day itself (a 5.5-day week's Saturday).
    half_days = {date.fromisoformat(str(d)) for d in facts.get("unpaidHalfDayDates") or []}
    no_pay_days = sum((min(weights[d.weekday()], Decimal("0.5")) if d in half_days else weights[d.weekday()]
                       for d in counted), _ZERO)
    days_worked = max(employed_days - no_pay_days, _ZERO)
    gross_rate_parts, excluded = {}, {}
    for key, amount in components.items():
        amount = max(amount or _ZERO, _ZERO)
        if not amount:
            continue
        cls, _source = _component_class(ctx, key)
        if wage_bases(key, cls)["eaGrossRate"] == "INCLUDED":
            gross_rate_parts[key] = amount
        elif key not in ("overtime", "additional_compensation") and cls == "OW":
            excluded[key] = amount
    gross_rate = sum(gross_rate_parts.values(), _ZERO)
    salary = (gross_rate * days_worked / month_days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if month_days else _ZERO
    deduction = gross_rate - salary
    # The unearned amount leaves each gross-rate component in proportion;
    # the cent remainder goes to the largest component (basic on a tie).
    allocation, allocated = {}, _ZERO
    if deduction > _ZERO and gross_rate > _ZERO:
        for key, amount in gross_rate_parts.items():
            take = min(_round2(deduction * amount / gross_rate), amount)
            allocation[key] = take
            allocated += take
        largest = max(gross_rate_parts, key=lambda k: (gross_rate_parts[k], k == "basic"))
        allocation[largest] = min(allocation[largest] + (deduction - allocated), gross_rate_parts[largest])
    monthly = {**gross_rate_parts, **excluded}
    pwm_basic = sum((a for k, a in monthly.items()
                     if wage_bases(k, _component_class(ctx, k)[0])["pwmBasis"] == "BASIC_AND_GROSS"), _ZERO)
    pwm_gross = sum((a for k, a in monthly.items()
                     if wage_bases(k, _component_class(ctx, k)[0])["pwmBasis"] in ("BASIC_AND_GROSS", "GROSS")), _ZERO)
    return {
        "status": "INCOMPLETE_MONTH", "reasons": reasons, "workPattern": pattern,
        "month": month_start.strftime("%Y-%m"), "employedFrom": start.isoformat(), "employedTo": end.isoformat(),
        "workingDaysInMonth": str(month_days), "workingDaysEmployed": str(employed_days), "noPayDays": str(no_pay_days),
        "noPayDates": [d.isoformat() for d in counted],
        "noPayHalfDayDates": sorted(d.isoformat() for d in counted if d in half_days),
        "noPayDatesNotCounted": [d.isoformat() for d in unpaid_dates if d not in counted],
        "daysWorked": str(days_worked), "monthlyGrossRate": str(gross_rate),
        "grossRateComponents": {k: str(v) for k, v in gross_rate_parts.items()},
        "excludedMonthlyComponentsPaidInFull": {k: str(v) for k, v in excluded.items()},
        "salary": str(salary), "deduction": str(deduction),
        "perDayGrossRate": str(_round2(gross_rate / month_days)) if month_days else "0",
        "monthlyRatesForPwm": {"basic": str(pwm_basic), "grossExOvertime": str(pwm_gross)},
        "formula": "monthly gross rate of pay ÷ working days in the month × days actually worked",
        "rounding": "salary to the cent, half-up — platform convention (MOM states no rounding rule)",
        "source": INCOMPLETE_MONTH_SOURCE,
        "_allocation": allocation,
    }


def incomplete_month_deduction(ctx: PayrollContext) -> Decimal:
    """The part of the monthly gross rate not payable this month (0 for a
    complete month) — what the payslip deducts in place of the platform's
    generic per-day attendance deduction."""
    month = incomplete_month(ctx)
    return Decimal(month["deduction"]) if month else _ZERO


def _incomplete_month_trace(ctx: PayrollContext) -> dict:
    month = incomplete_month(ctx)
    if month is None:
        return {"status": "COMPLETE_MONTH"}
    return {k: v for k, v in month.items() if not k.startswith("_")}


def _component_class(ctx: PayrollContext, key: str) -> tuple:
    """(CPF class, source) of one earning component — the shared
    TaxabilityRule rows over the default class; True in both classes BLOCKS."""
    rules = ctx.sgp_cpf_wage_classification or {}
    ow_flag = (rules.get(CPF_OW_COMPONENT) or {}).get(key)
    aw_flag = (rules.get(CPF_AW_COMPONENT) or {}).get(key)
    if ow_flag is True and aw_flag is True:
        raise SingaporeCalculationBlockedError(
            f"cpf_wage_classification:{key}",
            f"earning component {key!r} is configured as BOTH Ordinary and Additional Wages — contradictory TaxabilityRule rows",
        )
    default = _default_wage_class(key)
    if ow_flag is True:
        return "OW", "rule"
    if aw_flag is True:
        return "AW", "rule"
    if (default == "OW" and ow_flag is False) or (default == "AW" and aw_flag is False):
        return "NON_CPF", "rule"
    return default, "default"


def classify_cpf_wages(ctx: PayrollContext):
    """Returns (ow, aw, non_cpf, per-component classification trace).
    Default (no rule): ZP-SG-ENG-001 §4 — monthly salary and allowances are
    OW, AWS/bonus/other additional compensation is AW. A True rule moves a
    component into that class; a False rule on its default class makes it
    non-CPF (e.g. a true expense reimbursement); True in BOTH classes is a
    contradictory configuration and BLOCKS. Timing tests (OW payable by the
    14th of the following month) need payable dates, which are not captured."""
    components, labels = earning_components(ctx)
    totals = {"OW": _ZERO, "AW": _ZERO, "NON_CPF": _ZERO}
    detail = {}
    for key, amount in components.items():
        amount = max(amount or _ZERO, _ZERO)
        cls, source = _component_class(ctx, key)
        totals[cls] += amount
        if amount:
            detail[key] = {"amount": str(amount), "class": cls, "source": source, **wage_bases(key, cls)}
            if key in labels:
                detail[key]["label"] = labels[key]
    return totals["OW"], totals["AW"], totals["NON_CPF"], detail


def wage_bases(component: str, cpf_class: str) -> dict:
    """Per-earning statutory wage bases besides CPF (Phase 5.1 WS3):
      pwmBasis — MOM PWM pages: basic wage = the basic component; gross wage
        = basic + allowances + productivity incentives, EXCLUDING overtime,
        bonus / AWS and reimbursements (a NON_CPF item is treated as a
        reimbursement);
      eaGrossRate — MOM "Monthly and daily salary": gross rate of pay
        includes allowances but EXCLUDES overtime, bonus / AWS, reimbursements
        and travel, food and housing allowances (the platform's HRA is a
        housing allowance; other named allowances are included unless
        classified NON_CPF)."""
    if component in ("overtime", "additional_compensation") or cpf_class in ("AW", "NON_CPF"):
        return {"pwmBasis": "EXCLUDED", "eaGrossRate": "EXCLUDED"}
    if component == "basic":
        return {"pwmBasis": "BASIC_AND_GROSS", "eaGrossRate": "INCLUDED"}
    return {"pwmBasis": "GROSS", "eaGrossRate": "EXCLUDED" if component == "hra" else "INCLUDED"}


# IRAS employment-income classification (SG-020) — which Form IR8A item each
# earning component is reported under, independent of its CPF class. Items
# per IRAS "Explanatory Notes for completion of Form IR8A & Appendix 8A for
# the year ended 31 Dec 2026" (YA2027): a) gross salary, fees, leave pay,
# wages and overtime pay; b) bonus; c) director's fees; d1) allowances
# ("taxable unless specifically exempted", housing allowance listed); d3)
# lump-sum gratuity / notice pay / ex-gratia; and the gross commission field
# of the AIS file ("Additional specifications for TXT and XML file format",
# Aug 2024, 4.2.4). Same shared TaxabilityRule mechanism as the CPF classes:
# tax_component = one of IRAS_CATEGORIES, is_taxable = reported there.
# "iras_exempt" = not reportable employment income (exempt / concession).
IRAS_CATEGORIES = (
    "iras_gross_salary", "iras_bonus", "iras_director_fees", "iras_allowances",
    "iras_gross_commission", "iras_lump_sum", "iras_exempt",
)
IRAS_UNCLASSIFIED = "UNCLASSIFIED"
# SG-002: "complex equity compensation, employee share-option tax-deemed-
# exercise calculations" are outside the first release. An earning the
# organization classifies here (TaxabilityRule) BLOCKS — never calculated.
IRAS_SHARE_PLAN_CATEGORY = "iras_share_plan_gains"
# SG-002 employment classes — only STANDARD is calculated.
SG_SUPPORTED_EMPLOYMENT_CLASS = "STANDARD"
SG_UNSUPPORTED_EMPLOYMENT_CLASSES = {
    "PLATFORM_WORKER": "platform-worker CPF", "SEAFARER": "seafarer / special employment classes",
    "OVERSEAS_ONLY": "overseas-only contracts", "EOR": "employer-of-record legal employment",
}
_DEFAULT_IRAS_CATEGORY = {
    "basic": "iras_gross_salary", "overtime": "iras_gross_salary",
    "hra": "iras_allowances", "special_allowance": "iras_allowances", "named_allowances": "iras_allowances",
    "additional_compensation": "iras_bonus",
}


def _default_iras_category(component: str) -> str:
    return "iras_allowances" if component.startswith(ALLOWANCE_COMPONENT_PREFIX) else _DEFAULT_IRAS_CATEGORY[component]


def classify_iras_earnings(ctx: PayrollContext) -> tuple:
    """Returns ({category: amount}, {component: {amount, category, source}}).
    A True rule places the component in that item; True in two items is a
    contradictory configuration and BLOCKS (as for CPF); a False rule on
    the default item with no True elsewhere leaves the amount UNCLASSIFIED —
    never guessed: annual IR8A readiness then fails for that employee."""
    rules = getattr(ctx, "sgp_iras_classification", None) or {}
    components, labels = earning_components(ctx)
    totals: dict = {}
    detail = {}
    for key, amount in components.items():
        amount = max(amount or _ZERO, _ZERO)
        if not amount:
            continue
        if (rules.get(IRAS_SHARE_PLAN_CATEGORY) or {}).get(key) is True:
            raise SingaporeCalculationBlockedError(
                f"iras_classification:{key}",
                f"earning component {key!r} is classified as share-plan / share-option income — complex equity "
                "compensation is not supported in this release (SG-002; Appendix 8B)",
            )
        chosen = [c for c in IRAS_CATEGORIES if (rules.get(c) or {}).get(key) is True]
        if len(chosen) > 1:
            raise SingaporeCalculationBlockedError(
                f"iras_classification:{key}",
                f"earning component {key!r} is configured under more than one IRAS item {chosen} — contradictory "
                "TaxabilityRule rows",
            )
        default = _default_iras_category(key)
        if chosen:
            category, source = chosen[0], "rule"
        elif (rules.get(default) or {}).get(key) is False:
            category, source = IRAS_UNCLASSIFIED, "rule"
        else:
            category, source = default, "default"
        totals[category] = totals.get(category, _ZERO) + amount
        detail[key] = {"amount": str(amount), "category": category, "source": source}
        if key in labels:
            detail[key]["label"] = labels[key]
    return totals, detail


# SG-011 — which calendar month a payslip's wages belong to. CPF Board
# ("What payments attract CPF contributions"; "Mistakes by Employers when
# Determining CPF Contributions", last updated 20 Aug 2024, item 10):
# wages are Ordinary Wages for a month only if (1) they are for the
# employee's employment in that month AND (2) they are payable by the 14th
# of the following month; wages not classified as OW are AW for the month
# (the guide's examples: April OT payable 10 May = OW for April; April OT
# payable 30 May = AW for May). A payment covering two calendar months
# must be apportioned per calendar month first. The employment month is the
# payroll run's period; the payable date is taken as the run's pay date.
def resolve_wage_month(pay_date: date, period_start: date = None, period_end: date = None):
    """Returns (wage_month_start, wage_month_end, ow_late, basis). With no
    period supplied (preview, golden vectors) the pay-date month is used, as
    before. BLOCKS a period spanning two calendar months (apportionment by
    calendar month needs per-day earnings data that is not captured)."""
    if period_end is None:
        return pay_date.replace(day=1), _month_end(pay_date), False, {"rule": "PAY_DATE_MONTH", "detail": "no payroll period supplied"}
    if period_start is not None and (period_start.year, period_start.month) != (period_end.year, period_end.month):
        raise SingaporeCalculationBlockedError(
            "payroll_period",
            f"the payroll period {period_start.isoformat()}–{period_end.isoformat()} spans two calendar months — CPF "
            "requires the wages to be apportioned per calendar month before OW/AW classification (CPF Board), and "
            "per-month earnings are not captured",
        )
    employment_start = period_end.replace(day=1)
    nm_year, nm_month = (employment_start.year + 1, 1) if employment_start.month == 12 else (employment_start.year, employment_start.month + 1)
    deadline = date(nm_year, nm_month, 14)
    basis = {"employmentMonth": employment_start.strftime("%Y-%m"), "payableDate": pay_date.isoformat(),
             "owPayableBy": deadline.isoformat()}
    if pay_date <= deadline:
        return employment_start, _month_end(employment_start), False, {
            **basis, "rule": "OW_FOR_EMPLOYMENT_MONTH", "detail": "payable by the 14th of the following month"}
    return pay_date.replace(day=1), _month_end(pay_date), True, {
        **basis, "rule": "LATE_OW_IS_AW_FOR_PAYABLE_MONTH",
        "detail": "payable after the 14th of the following month — not OW; AW for the month payable"}


def calculate(ctx: PayrollContext) -> dict:
    """Singapore: CPF (cohort × age band × wage band, OW/AW ceilings,
    statutory rounding) + SDL (employer cost) + SHG + FWL (employer cost).
    No `tds`. Returns the result fields plus the full calculation trace."""
    if (ctx.pay_frequency or "Monthly") != "Monthly":
        raise SingaporeCalculationBlockedError(
            "pay_frequency", "only Monthly payrolls are supported — calendar-month CPF aggregation is not built",
        )
    if ctx.pay_date is None:
        raise SingaporeCalculationBlockedError("pay_date", "the wage month (pay date) is required to select CPF rules")
    facts = getattr(ctx, "sgp_employment_facts", None) or {}
    employment_class = facts.get("employmentClass")
    if employment_class and employment_class != SG_SUPPORTED_EMPLOYMENT_CLASS:
        raise SingaporeCalculationBlockedError(
            "employment_class",
            f"employment class {employment_class} — "
            f"{SG_UNSUPPORTED_EMPLOYMENT_CLASSES.get(employment_class, 'this class')} is not supported in this release (SG-002)",
        )
    if facts.get("statutoryChangeBlock"):
        block = facts["statutoryChangeBlock"]
        raise SingaporeCalculationBlockedError(
            "statutory_fact_change",
            f"{block['field']} changed from {block['old']!r} to {block['new']!r} effective {block['effectiveDate']}, within "
            f"the wage month — no published segmentation rule applies to it, so the change is never applied to the "
            "whole month (SG-045)",
        )

    rate_map = ctx.rate_map
    slabs = ctx.slabs
    month_start, month_end, ow_late, wage_month_basis = resolve_wage_month(
        ctx.pay_date, getattr(ctx, "period_start", None), getattr(ctx, "period_end", None))

    ow_actual, aw_actual, non_cpf, wage_classes = classify_cpf_wages(ctx)
    if ow_late and ow_actual > _ZERO:
        # Not payable by the 14th of the following month → not OW (CPF Board).
        aw_actual, ow_actual = aw_actual + ow_actual, _ZERO
        for detail in wage_classes.values():
            if detail["class"] == "OW":
                detail.update({"class": "AW", "source": "late_ow"})
    elif aw_actual > _ZERO and wage_month_basis.get("rule") == "OW_FOR_EMPLOYMENT_MONTH" and             (ctx.pay_date.year, ctx.pay_date.month) != (month_start.year, month_start.month):
        # The OW belongs to the employment month but AW is "AW for the month"
        # it is payable — one payslip would span two CPF months; the month of
        # such AW is not stated by the source for this case.
        raise SingaporeCalculationBlockedError(
            "aw_wage_month",
            f"this payslip's OW belongs to {month_start.strftime('%Y-%m')} (payable by the 14th) but it also carries "
            f"Additional Wages payable in {ctx.pay_date.strftime('%Y-%m')} — pay the AW in a separate payslip of its own month",
        )
    total_wages = ow_actual + aw_actual   # CPF total wages (TW) — non-CPF items excluded
    iras_totals, iras_classes = classify_iras_earnings(ctx)

    month_facts = _incomplete_month_trace(ctx)
    unpayable = Decimal(month_facts.get("deduction") or "0")
    trace = {
        "engine": ENGINE_VERSION,
        "incompleteMonth": month_facts,
        "wageMonth": month_start.strftime("%Y-%m"),
        "wageMonthBasis": wage_month_basis,
        "inputs": {
            "gross": str(ctx.gross), "ordinaryWages": str(ow_actual), "additionalWages": str(aw_actual),
            "nonCpfWages": str(non_cpf), "wageClassification": wage_classes,
            "irasClassification": iras_classes,
            "residencyStatus": ctx.sgp_cpf_residency_status, "workPass": ctx.sgp_work_pass_type,
            "sprEffectiveDate": ctx.sgp_spr_effective_date.isoformat() if ctx.sgp_spr_effective_date else None,
            "contributionArrangement": ctx.sgp_cpf_contribution_arrangement, "shgFunds": ctx.sgp_shg_funds,
            "employmentType": getattr(ctx, "employment_type", None),
            "employmentClass": employment_class or SG_SUPPORTED_EMPLOYMENT_CLASS,
            "employmentClassBasis": "RECORDED" if employment_class else "NOT_RECORDED_TREATED_AS_STANDARD",
            **({"statutoryFactsApplied": facts["statutoryFactsApplied"]} if facts.get("statutoryFactsApplied") else {}),
            "dateOfLeaving": ctx.date_of_leaving.isoformat() if getattr(ctx, "date_of_leaving", None) else None,
        },
    }

    cohort, effective_residency = resolve_cpf_cohort(ctx, month_start, month_end)
    trace["cohort"] = cohort or "NOT_CPF_ELIGIBLE"
    trace["effectiveResidency"] = effective_residency

    # Earlier payslips of this wage month: every monthly amount below is
    # computed on the MONTH's combined wages, and this payslip books the
    # difference (no second SHG/levy, one SDL clamp, one CPF band + rounding).
    mtd = month_to_date(ctx, trace["wageMonth"])
    month_ow = mtd["ow_actual"] + ow_actual
    month_total_wages = month_ow + mtd["aw_actual"] + aw_actual
    if mtd["payments"]:
        if mtd["cohorts"] - {trace["cohort"]}:
            raise SingaporeCalculationBlockedError(
                "cpf_cohort_within_month",
                f"an earlier payslip of {trace['wageMonth']} used CPF cohort {sorted(c or '' for c in mtd['cohorts'])}, "
                f"this one resolves {trace['cohort']} — status facts changed within the month; correct the earlier payslip",
            )
        trace["monthToDate"] = {
            "earlierPayments": mtd["payments"], "ordinaryWagesEarlier": str(mtd["ow_actual"]),
            "additionalWagesEarlier": str(mtd["aw_actual"]), "monthTotalWages": str(month_total_wages),
            "basis": "CPF, SDL, SHG and the S Pass levy are monthly amounts: recalculated on the month's combined "
                     "wages; this payslip books the difference from amounts already booked this month",
        }

    funds = parse_shg_funds(ctx.sgp_shg_funds)
    validate_shg_eligibility(funds, effective_residency, ctx.sgp_work_pass_type)

    employee_cpf = employer_cpf = _ZERO
    ytd = dict(ow_after=None, aw_subject_after=None, aw_paid_after=None)
    if cohort is not None:
        if ctx.date_of_birth is None:
            raise SingaporeCalculationBlockedError("date_of_birth", "date of birth is required for the CPF age band")
        age_band = resolve_cpf_age_band(ctx.date_of_birth, month_start, month_end, rate_map)
        if mtd["age_bands"] - {age_band}:
            raise SingaporeCalculationBlockedError(
                "cpf_age_band_within_month",
                f"an earlier payslip of {trace['wageMonth']} used age band {sorted(mtd['age_bands'])}, this one {age_band}",
            )
        row = select_cpf_band(slabs, cohort, age_band, month_total_wages)
        (total_cpf, employee_cpf, employer_cpf), ytd, cpf_trace = calculate_cpf_month(
            ctx, row, cohort, age_band, month_start, month_end, ow_actual, aw_actual, month_total_wages, mtd=mtd,
        )
        age_rule = rate_map.get("cpf_age_band_semantics")
        cpf_trace["ageBandRule"] = getattr(age_rule, "text_value", None) if age_rule is not None else None
        trace["cpf"] = cpf_trace
    else:
        trace["cpf"] = {"status": "NOT_PAYABLE", "detail": "No CPF for foreign employees (or SPR status not yet in force)"}

    month_sdl = calculate_sdl(rate_map, month_total_wages)
    sdl = _book_difference("sdl", month_sdl, mtd["sdl"])
    trace["sdl"] = {"base": str(month_total_wages), "amount": str(sdl), "treatment": "EMPLOYER_COST",
                    "rateRef": _row_ref(rate_map.get("sdl")), "minRef": _row_ref(rate_map.get("sdl_min_monthly")),
                    "maxRef": _row_ref(rate_map.get("sdl_max_monthly")),
                    "employerAggregateRounding": "Applied to the employer's monthly total in the SG_SDL_MONTHLY "
                                                 "statutory output (CPF Board SDL page, step 2: rounded down to the "
                                                 "nearest dollar) — not per payslip"}
    if mtd["payments"]:
        trace["sdl"].update({"monthAmount": str(month_sdl), "bookedEarlierThisMonth": str(mtd["sdl"])})

    shg_rows = shg_rows_for(slabs, funds, month_total_wages)
    if set(mtd["shg"]) - set(shg_rows):
        raise SingaporeCalculationBlockedError(
            "shg_funds_within_month", f"an earlier payslip of {trace['wageMonth']} deducted SHG for "
            f"{sorted(mtd['shg'])}; this one applies {sorted(shg_rows)} — SHG determination changed within the month",
        )
    _codes, shg_instructed = parse_shg_instruction(ctx.sgp_shg_funds)
    shg_month = {f: shg_instructed.get(f, r.flat_amount) for f, r in shg_rows.items()}
    shg_amounts = {f: _book_difference(f"shg:{f}", shg_month[f], mtd["shg"].get(f, _ZERO)) for f in shg_rows}
    shg_total = sum(shg_amounts.values(), _ZERO)
    trace["shg"] = {"funds": {f: {"amount": str(shg_amounts[f]), "ref": _row_ref(r),
                                  "basis": "EMPLOYEE_INSTRUCTION" if f in shg_instructed else "BAND",
                                  **({"bandAmount": str(r.flat_amount)} if f in shg_instructed else {})}
                              for f, r in shg_rows.items()},
                    "total": str(_round2(shg_total)), "treatment": "EMPLOYEE_DEDUCTION"}
    if mtd["payments"]:
        trace["shg"]["monthlyAmounts"] = {f: str(shg_month[f]) for f in shg_rows}

    fwl_month, trace["fwl"] = _fwl(ctx, effective_residency, month_start, month_end)
    fwl_amount = _book_difference("fwl", fwl_month, mtd["fwl"]) if trace["fwl"].get("status") == "CALCULATED" else fwl_month
    if mtd["payments"] and trace["fwl"].get("status") == "CALCULATED":
        trace["fwl"].update({"amount": str(fwl_amount), "monthlyLevy": str(fwl_month), "bookedEarlierThisMonth": str(mtd["fwl"])})
    if getattr(ctx, "sgp_overtime_facts", None):
        trace["overtime"] = ctx.sgp_overtime_facts
    salary_deductions = _ZERO
    if getattr(ctx, "sgp_deduction_orders", None):
        from app.modules.payroll.engine.jurisdictions.singapore.labour import evaluate_salary_deductions

        salary = _round2(ctx.gross - unpayable)
        final = bool(getattr(ctx, "date_of_leaving", None) and month_start <= ctx.date_of_leaving <= month_end)
        ded = evaluate_salary_deductions(ctx.sgp_deduction_orders, salary, rate_map, final_payment=final)
        if ded["errors"]:
            raise SingaporeCalculationBlockedError("salary_deductions", "; ".join(ded["errors"]))
        salary_deductions = ded["total"]
        trace["salaryDeductions"] = {"lines": ded["lines"], "total": str(ded["total"]), "capBase": ded["capBase"],
                                     "finalPayment": final, "source": "MOM Allowable salary deductions"}
    trace["lqs"] = _lqs(ctx, effective_residency, month_ow, wage_date=month_end)
    trace["ir21"] = _ir21(ctx, effective_residency, month_end)
    trace["iras"] = {"totals": {c: str(v) for c, v in sorted(iras_totals.items())},
                     "unclassified": str(iras_totals.get(IRAS_UNCLASSIFIED, _ZERO)),
                     "basis": "Form IR8A items per IRAS explanatory notes (YA2027); amounts as paid in this payslip"}
    trace["result"] = {
        "employeeCpf": str(employee_cpf), "employerCpf": str(employer_cpf), "shg": str(_round2(shg_total)),
        "sdl": str(sdl), "fwl": str(fwl_amount),
        "employeeDeductions": str(employee_cpf + _round2(shg_total) + salary_deductions),
        "netPay": str(_round2(ctx.gross - unpayable - employee_cpf - _round2(shg_total) - salary_deductions)),
        "employerCost": str(_round2(ctx.gross - unpayable + employer_cpf + sdl + fwl_amount)),
    }

    return dict(
        employee_pension=employee_cpf,        # CPF (Employee)
        employer_pension=employer_cpf,        # CPF (Employer)
        professional_tax=_round2(shg_total),  # SHG — employee deduction
        employer_payroll_tax=sdl,             # SDL — employer cost
        employer_eht=fwl_amount,              # Foreign Worker Levy — employer cost
        sgp_salary_deductions_total=salary_deductions,   # Employment Act authorised deductions (trace: lines)
        # MOM incomplete-month salary (Phase 5.2): standard.py deducts this in
        # place of the platform's generic per-day attendance deduction.
        sgp_incomplete_month_deduction=unpayable,
        **({"sgp_working_days": Decimal(month_facts["workingDaysInMonth"]), "sgp_days_worked": Decimal(month_facts["daysWorked"]),
            "sgp_per_day_gross_rate": Decimal(month_facts["perDayGrossRate"])} if month_facts["status"] == "INCOMPLETE_MONTH" else {}),
        ytd_cpf_ow_subject_after=ytd["ow_after"],
        ytd_cpf_aw_subject_after=ytd["aw_subject_after"],
        ytd_cpf_aw_paid_after=ytd["aw_paid_after"],
        sgp_calculation_trace=trace,
    )
