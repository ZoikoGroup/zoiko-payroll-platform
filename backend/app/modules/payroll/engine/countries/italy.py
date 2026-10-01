"""modules/payroll/engine/countries/italy.py
--------------------------------------------
Italy (ZP-IT-ENG-001) — fail-closed payroll calculation on the shared engine.
Same doctrine as ireland.py / singapore.py / sweden.py / france.py: one country
file, `calculate(ctx) -> dict`, no framework or ORM imports.

Calculation order (each step consumes the one before it):
  1. INPS contributions (§6/§7) from the CLASSIFICATION MATRIX — IVS (the 33%
     FPLD reference, 9.19% employee / 23.81% employer), CIGS where it applies,
     any other configured family for that classification, and FIS (IT-020).
     An unconfigured classification BLOCKS (IT-002).
  2. The additional 1% employee IVS above €56,224, CUMULATIVELY against the
     year-to-date contributory base (IT-016).
  3. The €122,295 contributory ceiling — only for a cohort with evidence
     (IT-017), cumulative, applied to IVS.
  4. Taxable income = gross − employee social contributions.
  5. IRPEF (§3) on a FORECAST annual income (YTD + this period × remaining
     mensilità), less detrazione lavoro and the wedge additional deduction
     (§4), withheld CUMULATIVELY against YTD withholding (IT-005).
  6. The wedge non-taxable sum (§4) — a separate benefit added to net pay,
     never hidden inside IRPEF (IT-009), band chosen on the annual forecast
     and retained in the trace (IT-010).
  7. Regional and municipal surtax (§5) on taxable income at the TAX DOMICILE
     (IT-013), bracketed (IT-014). This year's LIABILITY is traced (it is
     settled at the following year's conguaglio). What is WITHHELD this period
     is the three distinct §5 deductions, each an instalment of an amount
     already determined: the prior-year regional balance, the prior-year
     municipal balance and the current-year municipal advance. All three are
     withheld in full in a termination period.
  8. TFR (§13) — remuneration / 13.5 less the 0.50% INPS offset, with the
     destination validated against the Fondo Tesoreria headcount rule.

Out of scope — each is a separate strategy or ledger, never approximated here:
INAIL (§8), CCNL minimums (§9), conguaglio (IT-006), separate taxation of TFR
and arrears (IT-007/IT-039), prior-employer income (IT-008), the sum/deduction
recovery instalments (IT-011), TFR revaluation, and pension-fund employee
contributions (no per-fund content yet).

Italy joins shared._VALIDATION_ENABLED_COUNTRIES on day one and defines NO
hardcoded statutory figure: every rate, threshold and band is a configured row
(italy_content.py is the Draft source), and every missing fact raises
ItalyCalculationBlockedError — a MissingComplianceConfigurationError subclass,
so the existing MISSING_COMPLIANCE_CONFIGURATION 400 handler applies unchanged.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "IT"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
# §4: the detrazione and the additional deduction are pro-rated "to the work
# period" on a 365-day year, including in leap years.
DAYS_IN_TAX_YEAR = Decimal("365")

# §13 — the three legal TFR destinations (a worker election / legal duty).
TFR_DESTINATION_EMPLOYER = "AZIENDA"
TFR_DESTINATION_FUND = "FONDO_PENSIONE"
TFR_DESTINATION_TESORERIA = "FONDO_TESORERIA"
TFR_DESTINATIONS = (TFR_DESTINATION_EMPLOYER, TFR_DESTINATION_FUND, TFR_DESTINATION_TESORERIA)

# IT-017 — cohorts legally subject to the contributory maximum. Anything else
# set on the profile is unknown evidence and blocks, rather than capping.
CAP_COHORTS = ("POST_1995", "OPZIONE_CONTRIBUTIVA")

# §4 — the contract type decides the detrazione floor (fixed-term is higher).
CONTRACT_PERMANENT = ("INDETERMINATO", "APPRENDISTATO")
CONTRACT_FIXED_TERM = ("DETERMINATO",)

# §7 — the employer's income-support fund position (EmployerItalyProfile.fund_status).
FUND_FIS = "FIS"
FUND_CIG = "CIG"
FUND_SECTOR = "SECTOR_FUND"
FIS_BAND_SMALL = "UP_TO_5"
FIS_BAND_LARGE = "OVER_5"

# Matrix contribution families (ContributionRate.component_key within a scope).
INPS_IVS = "it_inps_ivs"
INPS_CIGS = "it_inps_cigs"

# ── Fallback-registry constants (engine/fallback_registry.py) ─────────────
# Each names the resolver key its registry entry declares. Value is always
# None: Italy has no engine fallback by design (spec §30).
_IT_IVS_ADDITIONAL_PCT = None
_IT_IVS_ADDITIONAL_THRESHOLD = None
_IT_CONTRIBUTORY_CEILING = None
_IT_TFR_DIVISOR = None
_IT_TFR_INPS_OFFSET = None
_IT_TESORERIA_HEADCOUNT_THRESHOLD = None
_IT_DETRAZIONE_MIN_PERMANENT = None
_IT_DETRAZIONE_MIN_FIXED_TERM = None
_IT_MENSILITA_DEFAULT = None
_IT_FIS_SMALL_EMPLOYER = None
_IT_FIS_LARGE_EMPLOYER = None
_IT_ADDREG_SALDO_FIRST_MONTH = None
_IT_ADDREG_SALDO_LAST_MONTH = None
_IT_ADDCOM_SALDO_FIRST_MONTH = None
_IT_ADDCOM_SALDO_LAST_MONTH = None
_IT_ADDCOM_ACCONTO_PCT = None
_IT_ADDCOM_ACCONTO_FIRST_MONTH = None
_IT_ADDCOM_ACCONTO_LAST_MONTH = None
_IT_INPS_DAILY_MINIMUM = None
_IT_INPS_FULL_MONTH_DAYS = None
_IT_INPS_PARTTIME_HOURLY_FACTOR = None

# The backend catalog of scalar Italy parameters — each key is a
# ContributionRate.component_key. Parity with italy_content.IT_PARAMETER_KEYS
# is asserted by tests/test_italy_engine.py (Sweden's SE_PARAMETER_KEYS pattern).
# There is deliberately no national INPS key: the IVS rates exist only as
# classification-scoped rows (IT-002).
IT_PARAMETER_KEYS = {
    "it_ivs_additional_pct": "employee_pct",
    "it_ivs_additional_threshold": "amount",
    "it_contributory_ceiling": "amount",
    "it_tfr_divisor": "amount",
    "it_tfr_inps_offset": "employer_pct",
    "it_tesoreria_headcount_threshold": "amount",
    "it_detrazione_min_permanent": "amount",
    "it_detrazione_min_fixed_term": "amount",
    "it_mensilita_default": "amount",
    "it_fis_small_employer": "employer_pct",
    "it_fis_large_employer": "employer_pct",
    "it_addreg_saldo_first_month": "amount",
    "it_addreg_saldo_last_month": "amount",
    "it_addcom_saldo_first_month": "amount",
    "it_addcom_saldo_last_month": "amount",
    "it_addcom_acconto_pct": "employee_pct",
    "it_addcom_acconto_first_month": "amount",
    "it_addcom_acconto_last_month": "amount",
    # §2/§6 INPS contributory minimum — NOT a wage floor (IT-004).
    "it_inps_daily_minimum": "amount",
    "it_inps_full_month_days": "amount",
    "it_inps_parttime_hourly_factor": "amount",
}

# TaxSlab.rule_type discriminators (mirrors italy_content).
IT_IRPEF_BRACKET_RULE = "IT_IRPEF_BRACKET"
IT_DETR_FIXED_RULE = "IT_DETR_FIXED"
IT_DETR_TAPER_RULE = "IT_DETR_TAPER"
IT_ADDL_FIXED_RULE = "IT_ADDL_DED_FIXED"
IT_ADDL_TAPER_RULE = "IT_ADDL_DED_TAPER"
IT_WEDGE_SUM_RULE = "IT_WEDGE_SUM"
IT_ADDREG_RULE = "IT_ADDREG"
IT_ADDREG_EXEMPT_RULE = "IT_ADDREG_EXEMPT"
IT_ADDCOM_RULE = "IT_ADDCOM"
IT_ADDCOM_EXEMPT_RULE = "IT_ADDCOM_EXEMPT"
REGION_TABLE_PREFIX = "REG_"
COMUNE_TABLE_PREFIX = "COM_"


class ItalyCalculationBlockedError(MissingComplianceConfigurationError):
    """An Italian statutory calculation that must not proceed — missing
    configured row, missing or contradictory worker fact, or an unsupported
    case. Subclasses MissingComplianceConfiguration so the existing main.py
    handler returns the same MISSING_COMPLIANCE_CONFIGURATION 400 every other
    fail-closed jurisdiction uses (same pattern as SwedenCalculationBlockedError)."""

    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Italy calculation blocked ({key}): {reason}",)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _upper(value) -> str:
    return (value or "").strip().upper()


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "1", "yes", "y")


class _Pack:
    """Typed, fail-closed reader over ctx.rate_map — a configured row is the
    ONLY source of a value, and a missing row blocks (never a default)."""

    def __init__(self, rate_map: dict, organization_id):
        self.rate_map = rate_map or {}
        self.organization_id = organization_id

    def block(self, key: str, reason: str):
        raise ItalyCalculationBlockedError(key, reason, self.organization_id)

    def require_pct(self, key: str, side: str) -> Decimal:
        row = self.rate_map.get(key)
        if row is None:
            self.block(key, "no configured contribution-rate row")
        value = getattr(row, f"{side}_rate_pct", None)
        if value is None:
            self.block(key, f"row has no {side} rate percentage configured")
        return Decimal(str(value))

    def require_amount(self, key: str) -> Decimal:
        row = self.rate_map.get(key)
        if row is None:
            self.block(key, "no configured parameter row")
        value = getattr(row, "flat_amount", None)
        if value is None:
            self.block(key, "row has no amount configured")
        return Decimal(str(value))


# ── band helpers ────────────────────────────────────────────────────────────
def _rows(slabs, rule: str, table: str = None) -> list:
    out = [r for r in slabs if (getattr(r, "rule_type", None) or "") == rule]
    if table is not None:
        out = [r for r in out if (getattr(r, "tax_table_number", None) or "") == table]
    return sorted(out, key=lambda r: _dec(getattr(r, "min_amount", None)))


def _check_contiguous(rows, key: str, pack: _Pack, from_zero: bool):
    """Bands must chain without gaps or overlaps: a gap would silently zero
    the rule for everyone whose income falls in it."""
    if from_zero and _dec(getattr(rows[0], "min_amount", None)) != ZERO:
        pack.block(key, "the first configured band does not start at 0")
    for previous, current in zip(rows, rows[1:]):
        previous_max = getattr(previous, "max_amount", None)
        if previous_max is None:
            pack.block(key, "an open-ended band is followed by another band")
        if _dec(previous_max) != _dec(getattr(current, "min_amount", None)):
            pack.block(key, f"bands are not contiguous at {previous_max} — "
                            "a gap or overlap would mis-tax the income inside it")


def _progressive(rows, income: Decimal, key: str, pack: _Pack) -> Decimal:
    """Each band's rate on the slice of income inside it — never one rate on
    the whole amount (§3, IT-014)."""
    _check_contiguous(rows, key, pack, from_zero=True)
    total = ZERO
    for row in rows:
        rate = getattr(row, "rate_pct", None)
        if rate is None:
            pack.block(key, "a configured band declares no rate")
        band_min = _dec(getattr(row, "min_amount", None))
        band_max = getattr(row, "max_amount", None)
        if income <= band_min:
            break
        top = income if band_max is None else min(income, _dec(band_max))
        total += (top - band_min) * Decimal(str(rate)) / HUNDRED
    return total


def _band_for(rows, income: Decimal):
    """The band with min < income ≤ max (statutory "up to" bands), or None
    when income lies outside every band (the rule then yields zero)."""
    for row in rows:
        band_max = getattr(row, "max_amount", None)
        if income > _dec(getattr(row, "min_amount", None)) and (
                band_max is None or income <= _dec(band_max)):
            return row
    return None


def _tapered_amount(fixed_rows, taper_rows, income: Decimal, key: str, pack: _Pack):
    """§4 shape shared by detrazione lavoro and the wedge additional deduction:
    amount = fixed + taper × (max − R) / (max − min) for the band holding R.
    Returns (amount, band_min) — (0, None) when R is outside every band."""
    if not fixed_rows:
        pack.block(key, "no configured bands")
    _check_contiguous(fixed_rows, key, pack, from_zero=False)
    taper_by_min = {_dec(getattr(r, "min_amount", None)): r for r in taper_rows}
    fixed_mins = {_dec(getattr(r, "min_amount", None)) for r in fixed_rows}
    if set(taper_by_min) != fixed_mins or len(taper_by_min) != len(taper_rows):
        pack.block(key, "fixed and taper rows must be seeded as matched pairs, "
                        "one of each per band")
    band = _band_for(fixed_rows, income)
    if band is None:
        return ZERO, None
    band_min = _dec(getattr(band, "min_amount", None))
    band_max = getattr(band, "max_amount", None)
    fixed = getattr(band, "flat_amount", None)
    taper = getattr(taper_by_min[band_min], "flat_amount", None)
    if fixed is None or taper is None:
        pack.block(key, f"band starting at {band_min} has no amount configured")
    amount = Decimal(str(fixed))
    if _dec(taper) != ZERO:
        if band_max is None:
            pack.block(key, "a tapering band must have an upper bound")
        width = _dec(band_max) - band_min
        amount += _dec(taper) * (_dec(band_max) - income) / width
    return amount, band_min


# ── 1-3. INPS contributions ─────────────────────────────────────────────────
def _classification_rows(ctx: PayrollContext, pack: _Pack, profile):
    """§7 / IT-002 — the matrix rows for the employer's CSC (+ CA when the
    employer has one) and the worker's class. Never a national average."""
    employer = getattr(ctx, "italy_employer_profile", None)
    csc = _upper(getattr(employer, "csc_code", None) or getattr(ctx, "it_employer_csc", None))
    ca = _upper(getattr(employer, "ca_code", None) or getattr(ctx, "it_employer_ca", None))
    worker_class = _upper(getattr(profile, "it_worker_class", None))
    if not csc:
        pack.block("it_inps_classification",
                   "the INPS rate depends on the employer's CSC code (spec §7); none is configured")
    if not worker_class:
        pack.block("it_worker_class",
                   "the INPS rate depends on the worker's INPS classification (spec §7)")
    scope = f"CSC_{csc}" + (f"_CA_{ca}" if ca else "")
    in_scope = [r for r in pack.rate_map.values()
                if (getattr(r, "jurisdiction_state", None) or "") == scope]
    if not in_scope:
        pack.block("it_inps_classification",
                   f"no INPS contribution-rate rows configured for {scope} — an unconfigured "
                   "classification never falls back to a national average rate (IT-002)")
    rows = [r for r in in_scope if _upper(getattr(r, "tax_regime", None)) == worker_class]
    if not rows:
        configured = sorted({_upper(getattr(r, "tax_regime", None)) for r in in_scope})
        pack.block("it_worker_class",
                   f"no INPS rows for worker class {worker_class} within {scope} "
                   f"(configured: {', '.join(configured) or 'none'})")
    return scope, rows


def _one_family(rows, family: str, scope: str, worker_class: str, pack: _Pack):
    matches = [r for r in rows if (getattr(r, "component_key", None) or "") == family]
    if len(matches) > 1:
        pack.block("it_inps_classification",
                   f"{len(matches)} {family} rows match {scope}/{worker_class} — ambiguous content")
    return matches[0] if matches else None


def _shares(row, family: str, pack: _Pack):
    employee = getattr(row, "employee_rate_pct", None)
    employer = getattr(row, "employer_rate_pct", None)
    if employee is None and employer is None:
        pack.block(family, "row carries neither an employee nor an employer share")
    return _dec(employee), _dec(employer)


def _fis_row(ctx: PayrollContext, pack: _Pack):
    """§7 / IT-020 — the employer's income-support fund. FIS applies its own
    0.50%/0.80% family by size band; CIG employers carry CIGS via the matrix;
    a sector fund needs its own content, which v1 does not have."""
    employer = getattr(ctx, "italy_employer_profile", None)
    status = getattr(employer, "fund_status", None) or {}
    fund = _upper(status.get("fund") if isinstance(status, dict) else None)
    if not fund:
        pack.block("it_fund_status", "the employer's income-support fund position "
                                     "(FIS / CIG / sector fund) is not captured (IT-001)")
    if fund == FUND_CIG:
        return None, None
    if fund == FUND_SECTOR:
        pack.block("it_fund_status", "sector bilateral-fund rates are not configured; "
                                     "they differ by sector and cannot be assumed (IT-020)")
    if fund != FUND_FIS:
        pack.block("it_fund_status", f"unknown fund position {fund}")
    band = _upper(status.get("fisBand"))
    if band == FIS_BAND_SMALL:
        return "it_fis_small_employer", pack.rate_map.get("it_fis_small_employer")
    if band == FIS_BAND_LARGE:
        return "it_fis_large_employer", pack.rate_map.get("it_fis_large_employer")
    pack.block("it_fund_status", "FIS applies but the employer size band "
                                 "(UP_TO_5 / OVER_5) is not captured")


def resolve_contributory_minimum(ctx: PayrollContext, pack: _Pack) -> dict:
    """§2/§6 — the INPS contributory minimum for this period (IT-004, IT-018).

    Full-time: daily minimum × the contributory days the period covers (the
    service supplies them: a full month, or fewer for a joiner/leaver).
    Part-time: an HOURLY minimum — daily minimum × factor ÷ the CCNL weekly
    hours — times the hours paid; never the daily minimum over a generic
    eight-hour day (IT-018). The minimum only raises the base INPS is paid on;
    it is not a wage floor and is never presented as one (IT-004)."""
    daily = pack.require_amount("it_inps_daily_minimum")
    hours = getattr(ctx, "it_part_time_hours", None)
    if hours is not None:
        weekly = getattr(ctx, "it_ccnl_weekly_hours", None)
        if weekly is None or _dec(weekly) <= ZERO:
            pack.block("it_ccnl_weekly_hours", "a part-time minimum needs the CCNL weekly "
                                               "hours (IT-018); none supplied")
        if _dec(hours) < ZERO:
            pack.block("it_part_time_hours", f"{hours} is not a valid hour count")
        factor = pack.require_amount("it_inps_parttime_hourly_factor")
        hourly = _round2(daily * factor / _dec(weekly))
        return {"minimum": _round2(hourly * _dec(hours)), "basis": "part_time",
                "hourlyMinimum": str(hourly), "hours": str(hours),
                "ccnlWeeklyHours": str(weekly), "dailyMinimum": str(daily)}
    days = getattr(ctx, "it_contributory_days", None)
    if days is None:
        pack.block("it_contributory_days",
                   "the INPS contributory minimum depends on the contributory days the period "
                   "covers (spec §6); none supplied, and part-time hours are not recorded either")
    days = _dec(days)
    full_month = pack.require_amount("it_inps_full_month_days")
    if days < ZERO or days > full_month:
        pack.block("it_contributory_days", f"{days} is outside 0-{full_month} for a monthly period")
    return {"minimum": _round2(daily * days), "basis": "full_time",
            "days": str(days), "dailyMinimum": str(daily)}


def resolve_contributions(ctx: PayrollContext, pack: _Pack, profile) -> dict:
    gross = _dec(ctx.gross)
    actual_base = _dec(getattr(ctx, "it_contributory_base", None)) or gross
    minimum = resolve_contributory_minimum(ctx, pack)
    # §6: contributions are due on the higher of the actual contributory pay
    # and the minimum; the shortfall is a contribution base, never pay.
    base = max(actual_base, minimum["minimum"])
    ytd_base = _dec(getattr(ctx, "it_ytd_contributory_base_prior", None))
    scope, rows = _classification_rows(ctx, pack, profile)
    worker_class = _upper(getattr(profile, "it_worker_class", None))

    # ── 3. ceiling (IT-017): cohort evidence only, cumulative ───────────────
    cohort = _upper(getattr(profile, "it_contributory_cap_cohort", None)) or None
    if cohort and cohort not in CAP_COHORTS:
        pack.block("it_contributory_cap_cohort",
                   f"unknown cap cohort {cohort} (expected one of {', '.join(CAP_COHORTS)}); "
                   "the ceiling is never applied without recognised evidence")
    if cohort:
        ceiling = pack.require_amount("it_contributory_ceiling")
        pension_base = max(ZERO, min(ytd_base + base, ceiling) - min(ytd_base, ceiling))
        pension_ytd_prior = min(ytd_base, ceiling)
        cap_note = f"ceiling {ceiling} applied to IVS for cohort {cohort}"
    else:
        pension_base = base
        pension_ytd_prior = ytd_base
        cap_note = "no cap cohort — IVS on the full contributory base (IT-017)"
    cap_excluded = _round2(base - pension_base)

    # ── 1. IVS + CIGS + other matrix families + FIS ────────────────────────
    ivs_row = _one_family(rows, INPS_IVS, scope, worker_class, pack)
    if ivs_row is None:
        pack.block("it_inps_classification",
                   f"no {INPS_IVS} row for {scope}/{worker_class}; IVS is the mandatory pension family")
    ivs_ee_pct, ivs_er_pct = _shares(ivs_row, INPS_IVS, pack)
    if ivs_ee_pct == ZERO or ivs_er_pct == ZERO:
        pack.block(INPS_IVS, f"IVS row for {scope}/{worker_class} must carry both shares")

    components = []

    def add(key, ee_pct, er_pct, on_base, **extra):
        ee = _round2(ee_pct * on_base / HUNDRED)
        er = _round2(er_pct * on_base / HUNDRED)
        components.append({"key": key, "employeePct": str(ee_pct), "employerPct": str(er_pct),
                           "base": str(on_base), "employee": str(ee), "employer": str(er), **extra})
        return ee, er

    employee = employer = ZERO
    ee, er = add(INPS_IVS, ivs_ee_pct, ivs_er_pct, pension_base, scope=scope)
    employee += ee
    employer += er

    cigs_row = _one_family(rows, INPS_CIGS, scope, worker_class, pack)
    if _truthy(getattr(profile, "it_cigs_applies", None)):
        if cigs_row is None:
            pack.block(INPS_CIGS, f"CIGS applies to this worker but no {INPS_CIGS} row is "
                                  f"configured for {scope}/{worker_class}")
        ee, er = add(INPS_CIGS, *_shares(cigs_row, INPS_CIGS, pack), base)
        employee += ee
        employer += er

    for row in rows:
        family = getattr(row, "component_key", None) or ""
        if family in (INPS_IVS, INPS_CIGS):
            continue
        if not family:
            pack.block("it_inps_classification", f"a matrix row in {scope} has no component_key")
        ee, er = add(family, *_shares(row, family, pack), base)
        employee += ee
        employer += er

    fis_key, fis_row = _fis_row(ctx, pack)
    fis_employee = ZERO
    if fis_key:
        if fis_row is None:
            pack.block(fis_key, "FIS applies but no FIS rate row is configured")
        ee, er = add(fis_key, *_shares(fis_row, fis_key, pack), base)
        employee += ee
        employer += er
        fis_employee = ee

    # ── 2. additional 1% IVS, cumulative (IT-016) ───────────────────────────
    add_pct = pack.require_pct("it_ivs_additional_pct", side="employee")
    threshold = pack.require_amount("it_ivs_additional_threshold")
    excess_before = max(ZERO, pension_ytd_prior - threshold)
    excess_after = max(ZERO, pension_ytd_prior + pension_base - threshold)
    ivs_additional = _round2((excess_after - excess_before) * add_pct / HUNDRED)
    employee += ivs_additional
    components.append({"key": "it_ivs_additional_pct", "employeePct": str(add_pct),
                       "threshold": str(threshold), "ytdBefore": str(pension_ytd_prior),
                       "base": str(excess_after - excess_before),
                       "employee": str(ivs_additional), "employer": "0.00",
                       "crossedThisPeriod": excess_before == ZERO and excess_after > ZERO})

    return {
        "actual_base": actual_base,
        "minimum": minimum,
        "minimum_applied": base > actual_base,
        "scope": scope,
        "causale": getattr(ivs_row, "filing_status", None),
        "fis_employee": _round2(fis_employee),
        "contributory_base": base,
        "pension_base": pension_base,
        "cap_cohort": cohort,
        "capped": cap_excluded > ZERO,
        "cap_excluded": cap_excluded,
        "cap_note": cap_note,
        "ivs_additional": ivs_additional,
        "employee": _round2(employee),
        "employer": _round2(employer),
        "components": components,
    }


# ── 8. TFR ─────────────────────────────────────────────────────────────────
def resolve_tfr(ctx: PayrollContext, pack: _Pack, profile, remuneration: Decimal,
                contributory_base: Decimal) -> dict:
    """§13 — TFR accrues on the worker's actual remuneration (Codice civile
    art. 2120), never on a contributory minimum; the 0.50% INPS offset is a
    contribution, so it follows the contributory base."""
    divisor = pack.require_amount("it_tfr_divisor")
    if divisor <= ZERO:
        pack.block("it_tfr_divisor", "divisor must be positive")
    offset_pct = pack.require_pct("it_tfr_inps_offset", side="employer")
    gross_accrual = remuneration / divisor
    offset = contributory_base * offset_pct / HUNDRED
    net = _round2(gross_accrual - offset)

    destination = _upper(getattr(profile, "it_tfr_destination", None)) or None
    tesoreria_below_threshold = False
    if destination is None:
        # The accrual is owed regardless; an absent election only leaves the
        # ROUTING unresolved, which the filing stage must settle.
        routing_complete = False
    else:
        if destination not in TFR_DESTINATIONS:
            pack.block("it_tfr_destination",
                       f"unsupported TFR destination {destination} "
                       f"(expected one of {', '.join(TFR_DESTINATIONS)})")
        if destination == TFR_DESTINATION_FUND and not getattr(profile, "it_pension_fund", None):
            pack.block("it_pension_fund", "TFR is routed to a pension fund but no fund is named")
        if destination in (TFR_DESTINATION_EMPLOYER, TFR_DESTINATION_TESORERIA):
            employer = getattr(ctx, "italy_employer_profile", None)
            headcount = getattr(employer, "prior_year_avg_headcount", None)
            threshold = pack.require_amount("it_tesoreria_headcount_threshold")
            if headcount is None:
                pack.block("it_prior_year_avg_headcount",
                           "whether TFR may stay with the employer or must go to the Fondo "
                           "Tesoreria depends on the prior-year average headcount (IT-040)")
            below = Decimal(headcount) < threshold
            if destination == TFR_DESTINATION_EMPLOYER and not below:
                pack.block("it_tfr_destination",
                           f"prior-year average headcount {headcount} >= {threshold}: "
                           "unallocated TFR must go to the Fondo Tesoreria, not stay with the employer")
            if destination == TFR_DESTINATION_TESORERIA and below:
                # Section 14 is unambiguous: the obligation arises only at or
                # above the prior-year threshold, so electing Tesoreria below it
                # is a contradiction to refuse, not a case to trace. IT-041's
                # transferred-worker exception is evidence the service must
                # attach (it_tesoreria_transfer_evidence) BEFORE this point — it
                # is never inferred from the bare election.
                if not _truthy(getattr(profile, "it_tesoreria_transfer_evidence", None)):
                    pack.block("it_tfr_destination",
                               f"prior-year average headcount {headcount} is below the "
                               f"{threshold} threshold, so the Fondo Tesoreria obligation does "
                               "not arise (section 14); transferred-worker exceptions require "
                               "explicit evidence (IT-041) and are never inferred from the "
                               "election alone")
                tesoreria_below_threshold = True
        routing_complete = True
    return {
        "gross_accrual": _round2(gross_accrual),
        "inps_offset": _round2(offset),
        "net": net,
        "unrounded": gross_accrual - offset,
        "destination": destination,
        "routing_complete": routing_complete,
        "tesoreria_below_threshold": tesoreria_below_threshold,
    }


# ── 4-6. IRPEF, deductions and the wedge ────────────────────────────────────
def _mensilita(ctx: PayrollContext, pack: _Pack) -> int:
    configured = getattr(ctx, "it_mensilita", None)
    value = Decimal(configured) if configured is not None else pack.require_amount("it_mensilita_default")
    if value < 1 or value != value.to_integral_value():
        pack.block("it_mensilita", f"mensilità must be a whole number ≥ 1, got {value}")
    return int(value)


def resolve_irpef(ctx: PayrollContext, pack: _Pack, profile, taxable: Decimal) -> dict:
    slabs = list(getattr(ctx, "slabs", None) or [])
    total = _mensilita(ctx, pack)
    paid_prior = int(getattr(ctx, "it_mensilita_paid_prior", None) or 0)
    this_period = int(getattr(ctx, "it_period_mensilita", None) or 1)
    ytd_taxable = _dec(getattr(ctx, "it_ytd_taxable_prior", None))
    ytd_withheld = _dec(getattr(ctx, "it_ytd_irpef_withheld_prior", None))
    if this_period < 1 or paid_prior < 0 or paid_prior + this_period > total:
        pack.block("it_mensilita",
                   f"{paid_prior} mensilità already paid + {this_period} now exceeds the "
                   f"{total} configured for the year")
    if paid_prior == 0 and (ytd_taxable or ytd_withheld):
        pack.block("it_ytd_taxable_prior",
                   "year-to-date taxable/withheld amounts exist but no mensilità is recorded as paid")

    days = getattr(ctx, "it_work_days_in_year", None)
    if days is None:
        pack.block("it_work_days_in_year",
                   "detrazione lavoro is pro-rated to the days of employment in the year (§4); "
                   "none supplied")
    days = Decimal(days)
    if days < 1 or days > 366:
        pack.block("it_work_days_in_year", f"{days} is not a valid day count")
    day_share = min(days, DAYS_IN_TAX_YEAR) / DAYS_IN_TAX_YEAR

    # IT-005: forecast the year, don't bracket the month.
    per_mensilita = taxable / Decimal(this_period)
    forecast = ytd_taxable + per_mensilita * Decimal(total - paid_prior)

    brackets = _rows(slabs, IT_IRPEF_BRACKET_RULE)
    if not brackets:
        pack.block("it_irpef_brackets", "no configured IRPEF brackets for the year; Italy has no "
                                        "engine default income-tax rate (§3)")
    tables = {getattr(r, "tax_table_number", None) for r in brackets}
    if len(tables) != 1:
        pack.block("it_irpef_brackets", f"multiple IRPEF tables configured ({sorted(map(str, tables))}); "
                                        "the year's rule pack must resolve to exactly one")
    gross_tax = _progressive(brackets, forecast, "it_irpef_brackets", pack)

    # §4 detrazione lavoro, with the contract-type floor in the lowest band.
    contract = _upper(getattr(profile, "it_contract_type", None))
    if contract not in CONTRACT_PERMANENT + CONTRACT_FIXED_TERM:
        pack.block("it_contract_type",
                   f"contract type {contract or 'none'} is not one of "
                   f"{', '.join(CONTRACT_PERMANENT + CONTRACT_FIXED_TERM)}; the detrazione "
                   "floor depends on it")
    detr_fixed = _rows(slabs, IT_DETR_FIXED_RULE)
    detr_amount, detr_band = _tapered_amount(
        detr_fixed, _rows(slabs, IT_DETR_TAPER_RULE), forecast, "it_detrazione_lavoro", pack)
    detrazione = detr_amount * day_share
    detr_floor_applied = False
    if detr_band is not None and detr_band == _dec(getattr(detr_fixed[0], "min_amount", None)):
        floor_key = ("it_detrazione_min_fixed_term" if contract in CONTRACT_FIXED_TERM
                     else "it_detrazione_min_permanent")
        floor = pack.require_amount(floor_key)
        if detrazione < floor:
            detrazione = floor
            detr_floor_applied = True

    # §4 wedge additional deduction (separate object, IT-009).
    addl_amount, addl_band = _tapered_amount(
        _rows(slabs, IT_ADDL_FIXED_RULE), _rows(slabs, IT_ADDL_TAPER_RULE), forecast,
        "it_wedge_additional_deduction", pack)
    additional = addl_amount * day_share

    net_annual = max(ZERO, gross_tax - detrazione - additional)
    cumulative_due = net_annual * Decimal(paid_prior + this_period) / Decimal(total)
    raw_withholding = _round2(cumulative_due - ytd_withheld)
    withholding = max(ZERO, raw_withholding)

    # §4 wedge non-taxable sum: the percentage band is chosen on the ANNUAL
    # forecast (IT-010), the sum is that percentage of THIS period's income.
    wedge_rows = _rows(slabs, IT_WEDGE_SUM_RULE)
    if not wedge_rows:
        pack.block("it_wedge_tax_free_sum", "no configured non-taxable-sum bands (§4)")
    _check_contiguous(wedge_rows, "it_wedge_tax_free_sum", pack, from_zero=True)
    wedge_band = _band_for(wedge_rows, forecast)
    wedge_pct = _dec(getattr(wedge_band, "rate_pct", None)) if wedge_band is not None else ZERO
    wedge_sum = _round2(taxable * wedge_pct / HUNDRED)

    return {
        "mensilita": total,
        "mensilita_paid_prior": paid_prior,
        "period_mensilita": this_period,
        "forecast": forecast,
        "gross_tax": gross_tax,
        "detrazione": detrazione,
        "detrazione_band_min": detr_band,
        "detrazione_floor_applied": detr_floor_applied,
        "additional": additional,
        "additional_band_min": addl_band,
        "net_annual": net_annual,
        "cumulative_due": cumulative_due,
        "withholding": withholding,
        "over_withheld": -raw_withholding if raw_withholding < ZERO else ZERO,
        "day_share": day_share,
        "wedge_pct": wedge_pct,
        "wedge_sum": wedge_sum,
    }


# ── 7. local surtax liability ───────────────────────────────────────────────
def _local_liability(slabs, rule: str, exempt_rule: str, table: str, income: Decimal,
                     key: str, pack: _Pack) -> Decimal:
    rows = _rows(slabs, rule, table)
    if not rows:
        pack.block(key, f"no surtax content configured for tax domicile {table}; a national "
                        "rate is never substituted (IT-012/IT-013)")
    exemptions = _rows(slabs, exempt_rule, table)
    if len(exemptions) > 1:
        pack.block(key, f"{len(exemptions)} exemption thresholds configured for {table}")
    if exemptions:
        threshold = getattr(exemptions[0], "flat_amount", None)
        if threshold is None:
            pack.block(key, f"exemption row for {table} has no threshold amount")
        if income <= _dec(threshold):
            return ZERO
    return _progressive(rows, income, key, pack)


def resolve_local_tax(ctx: PayrollContext, pack: _Pack, profile, irpef: dict) -> dict:
    region = _upper(getattr(profile, "it_tax_domicile_region", None))
    comune = _upper(getattr(profile, "it_tax_domicile_comune", None))
    if not region:
        pack.block("it_tax_domicile_region",
                   "the regional surtax depends on the TAX DOMICILE region (ISTAT code); the "
                   "workplace is never a substitute (IT-013)")
    if not comune:
        pack.block("it_tax_domicile_comune",
                   "the municipal surtax depends on the TAX DOMICILE comune (cadastral code); "
                   "the workplace is never a substitute (IT-013)")
    slabs = list(getattr(ctx, "slabs", None) or [])
    income = irpef["forecast"]
    regional = _local_liability(slabs, IT_ADDREG_RULE, IT_ADDREG_EXEMPT_RULE,
                                f"{REGION_TABLE_PREFIX}{region}", income, "it_addregionale", pack)
    municipal = _local_liability(slabs, IT_ADDCOM_RULE, IT_ADDCOM_EXEMPT_RULE,
                                 f"{COMUNE_TABLE_PREFIX}{comune}", income, "it_addcomunale", pack)
    # The surtaxes are due only when net IRPEF is due for the year.
    no_irpef = irpef["net_annual"] == ZERO
    return {
        "region": region,
        "comune": comune,
        "regional": ZERO if no_irpef else _round2(regional),
        "municipal": ZERO if no_irpef else _round2(municipal),
        "zero_because_no_irpef": no_irpef,
    }


# §5 — the three distinct local-surtax deductions withheld this period. Each
# is (name, determined amount, already withheld, first-month key, last-month key).
_LOCAL_WITHHOLDINGS = (
    ("addreg_saldo", "it_addreg_saldo_due", "it_addreg_saldo_withheld_prior",
     "it_addreg_saldo_first_month", "it_addreg_saldo_last_month"),
    ("addcom_saldo", "it_addcom_saldo_due", "it_addcom_saldo_withheld_prior",
     "it_addcom_saldo_first_month", "it_addcom_saldo_last_month"),
    ("addcom_acconto", "it_addcom_acconto_due", "it_addcom_acconto_withheld_prior",
     "it_addcom_acconto_first_month", "it_addcom_acconto_last_month"),
)


def _schedule_month(pack: _Pack, key: str) -> int:
    value = pack.require_amount(key)
    if value != value.to_integral_value() or not 1 <= value <= 12:
        pack.block(key, f"must be a pay month 1-12, got {value}")
    return int(value)


def resolve_local_withholding(ctx: PayrollContext, pack: _Pack) -> dict:
    """§5 — what is WITHHELD this period, as distinct deductions.

    Each amount was DETERMINED earlier (the regional and municipal balances at
    the prior year's conguaglio, the municipal advance at the start of this
    year); the engine only spreads what remains over the instalments left in
    its window, so the last instalment takes the exact remainder. A
    termination period withholds everything still outstanding (§22).

    A determined amount the service did not supply BLOCKS: an employee with
    nothing to withhold carries an explicit 0, so an unrecorded amount is
    never read as nothing owed.
    """
    month = ctx.pay_date.month
    terminating = _truthy(getattr(ctx, "it_is_termination_period", None))
    lines = {}
    total = ZERO
    for name, due_key, prior_key, first_key, last_key in _LOCAL_WITHHOLDINGS:
        raw_due = getattr(ctx, due_key, None)
        if raw_due is None:
            pack.block(due_key, "the determined amount to withhold is not recorded for this "
                                "employee (§5); record 0 explicitly when nothing is owed")
        due = _dec(raw_due)
        prior = _dec(getattr(ctx, prior_key, None))
        if due < ZERO or prior < ZERO:
            pack.block(due_key, f"negative amounts (due {due}, withheld {prior})")
        if prior > due:
            pack.block(prior_key, f"{prior} already withheld exceeds the determined {due}")
        first = _schedule_month(pack, first_key)
        last = _schedule_month(pack, last_key)
        if first > last:
            pack.block(first_key, f"window starts in month {first} after it ends in month {last}")
        remaining = due - prior
        if remaining == ZERO:
            instalment, instalments_left, basis = ZERO, 0, "settled"
        elif terminating:
            instalment, instalments_left, basis = _round2(remaining), 1, "termination"
        elif month < first:
            instalment, instalments_left, basis = ZERO, last - first + 1, "window_not_open"
        else:
            # After the window closes the whole remainder falls due at once.
            instalments_left = max(1, last - month + 1)
            instalment = _round2(remaining / Decimal(instalments_left))
            basis = "instalment" if month <= last else "after_window"
        lines[name] = {"due": str(due), "withheldPrior": str(prior),
                       "remainingBefore": str(remaining), "withheldNow": str(instalment),
                       "instalmentsLeft": instalments_left, "window": [first, last],
                       "basis": basis}
        total += instalment
    return {"lines": lines, "total": _round2(total), "terminating": terminating,
            "addreg_saldo": _dec(lines["addreg_saldo"]["withheldNow"]),
            "addcom_saldo": _dec(lines["addcom_saldo"]["withheldNow"]),
            "addcom_acconto": _dec(lines["addcom_acconto"]["withheldNow"])}


def determine_addcom_acconto(ctx: PayrollContext, prior_year_taxable: Decimal, comune: str,
                             prior_year_irpef_due: bool) -> Decimal:
    """§5 — the current-year municipal ADVANCE, determined once at the start of
    the year: the advance percentage of the municipal amount computed on the
    PRIOR year's taxable income with THIS year's comune table (its brackets and
    exemption). Nothing is due when no IRPEF was due for the prior year, the
    same rule resolve_local_tax applies to the liability. Used by the service
    / conguaglio when it opens the year's advance; never by calculate()."""
    pack = _Pack(ctx.rate_map, getattr(ctx, "italy_organization_id", None))
    if not comune:
        pack.block("it_tax_domicile_comune", "the advance is determined at the tax-domicile comune")
    if not prior_year_irpef_due:
        return ZERO
    pct = pack.require_pct("it_addcom_acconto_pct", side="employee")
    slabs = list(getattr(ctx, "slabs", None) or [])
    municipal = _local_liability(slabs, IT_ADDCOM_RULE, IT_ADDCOM_EXEMPT_RULE,
                                 f"{COMUNE_TABLE_PREFIX}{_upper(comune)}", _dec(prior_year_taxable),
                                 "it_addcomunale", pack)
    return _round2(municipal * pct / HUNDRED)


def resolve_fringe(ctx: PayrollContext, profile) -> dict:
    """§11 / IT-032 — the €2,000 per-child exemption needs the EMPLOYEE'S OWN
    declaration; it is never inferred. Only the evidence state is recorded
    here; the annual fringe accumulator is a later ledger."""
    declared = _truthy(getattr(profile, "it_fringe_child_declared", None))
    amount = _dec(getattr(ctx, "it_fringe_amount", None))
    return {"amount": amount, "child_declared": declared,
            "evidence_ok": declared or amount == ZERO}


def calculate(ctx: PayrollContext) -> dict:
    """Italy entry point (standard + enterprise dispatch). Returns the
    deductions/contributions dict standard.py folds into PayrollResult."""
    organization_id = getattr(ctx, "italy_organization_id", None)
    pack = _Pack(ctx.rate_map, organization_id)
    if ctx.pay_date is None:
        pack.block("pay_date", "payment date is a first-class rule-pack key")
    if (ctx.pay_frequency or "").strip().lower() != "monthly":
        pack.block("pay_frequency", f"Italian payroll is monthly (LUL); {ctx.pay_frequency!r} "
                                    "is not supported")
    profile = getattr(ctx, "italy_statutory_profile", None)
    if profile is None:
        pack.block("italy_statutory_profile", "no Italian statutory profile in force for the pay date")

    contributions = resolve_contributions(ctx, pack, profile)
    tfr = resolve_tfr(ctx, pack, profile, contributions["actual_base"],
                      contributions["contributory_base"])
    taxable = _round2(_dec(ctx.gross) - contributions["employee"])
    irpef = resolve_irpef(ctx, pack, profile, taxable)
    local = resolve_local_tax(ctx, pack, profile, irpef)
    local_withheld = resolve_local_withholding(ctx, pack)
    fringe = resolve_fringe(ctx, profile)

    employee_total = _round2(contributions["employee"] + irpef["withholding"]
                             + local_withheld["total"])
    employer_total = _round2(contributions["employer"] + tfr["net"])

    trace = {
        "jurisdiction": _COUNTRY,
        "payDate": ctx.pay_date.isoformat(),
        "incomeYear": ctx.pay_date.year,
        "inpsScope": contributions["scope"],
        "workerClass": getattr(profile, "it_worker_class", None),
        "contractType": getattr(profile, "it_contract_type", None),
        "causale": contributions["causale"],
        "cnelCode": getattr(profile, "it_cnel_code", None),
        "cnelLevel": getattr(profile, "it_cnel_level", None),
        "cigsApplies": getattr(profile, "it_cigs_applies", None),
        "contributoryBase": str(contributions["contributory_base"]),
        "actualContributoryPay": str(contributions["actual_base"]),
        "contributoryMinimum": contributions["minimum"],
        "contributoryMinimumApplied": contributions["minimum_applied"],
        "pensionBase": str(contributions["pension_base"]),
        "capCohort": contributions["cap_cohort"],
        "capNote": contributions["cap_note"],
        "ceilingAppliesTo": "IVS",
        "taxableIncome": str(taxable),
        "mensilita": irpef["mensilita"],
        "mensilitaPaidPrior": irpef["mensilita_paid_prior"],
        "periodMensilita": irpef["period_mensilita"],
        "annualForecast": str(_round2(irpef["forecast"])),
        "irpefGrossAnnual": str(_round2(irpef["gross_tax"])),
        "detrazioneBandMin": None if irpef["detrazione_band_min"] is None else str(irpef["detrazione_band_min"]),
        "detrazioneFloorApplied": irpef["detrazione_floor_applied"],
        "additionalDeductionBandMin": None if irpef["additional_band_min"] is None else str(irpef["additional_band_min"]),
        "dayShare": str(irpef["day_share"]),
        "cumulativeDue": str(_round2(irpef["cumulative_due"])),
        "overWithheld": str(irpef["over_withheld"]),
        "wedgeBandPct": str(irpef["wedge_pct"]),
        "taxDomicileRegion": local["region"],
        "taxDomicileComune": local["comune"],
        "localTaxWithheld": True,
        "localTaxModel": "DETERMINED_AMOUNTS_IN_INSTALMENTS_V2",
        "localWithholding": local_withheld["lines"],
        "terminationPeriod": local_withheld["terminating"],
        "localTaxZeroBecauseNoIrpef": local["zero_because_no_irpef"],
        "tfrDestination": tfr["destination"],
        "tfrRoutingComplete": tfr["routing_complete"],
        "tfrTesoreriaBelowThreshold": tfr["tesoreria_below_threshold"],
        "tfrUnrounded": str(tfr["unrounded"]),
        "fringeEvidenceOk": fringe["evidence_ok"],
        "rateKeys": sorted(ctx.rate_map.keys()),
    }

    return {
        # employer_social_security is the generic PayrollResult slot: what the
        # employer REMITS to INPS. TFR is a reserve, not part of it (IT-057).
        "employer_social_security": contributions["employer"],
        "it_employer_social_security": contributions["employer"],
        "it_employer_contributions": employer_total,
        "it_employee_contributions": contributions["employee"],
        "it_contributory_base": contributions["pension_base"],
        "it_contributory_minimum_applied": contributions["minimum_applied"],
        "it_contributory_capped": contributions["capped"],
        "it_contributory_cap_cohort": contributions["cap_cohort"],
        "it_contributory_cap_amount": contributions["cap_excluded"],
        "it_contributory_cap_note": contributions["cap_note"],
        "it_inps_scope": contributions["scope"],
        "it_inps_components": contributions["components"],
        "it_ivs_additional": contributions["ivs_additional"],
        "it_tfr_amount": tfr["net"],
        "it_tfr_gross_accrual": tfr["gross_accrual"],
        "it_tfr_inps_offset": tfr["inps_offset"],
        "it_tfr_destination": tfr["destination"],
        "it_tfr_routing_complete": tfr["routing_complete"],
        "it_taxable_income": taxable,
        "it_irpef": irpef["withholding"],
        "it_irpef_annual": _round2(irpef["net_annual"]),
        "it_irpef_gross_annual": _round2(irpef["gross_tax"]),
        "it_detrazione_lavoro": _round2(irpef["detrazione"]),
        "it_wedge_additional_deduction": _round2(irpef["additional"]),
        "it_fis_employee": contributions["fis_employee"],
        "it_wedge_tax_free_sum": irpef["wedge_sum"],
        "it_wedge_band_pct": irpef["wedge_pct"],
        "it_regional_tax_annual": local["regional"],
        "it_municipal_tax_annual": local["municipal"],
        "it_local_tax_withheld": True,
        "it_addreg_saldo_withheld": local_withheld["addreg_saldo"],
        "it_addcom_saldo_withheld": local_withheld["addcom_saldo"],
        "it_addcom_acconto_withheld": local_withheld["addcom_acconto"],
        "it_local_tax_withheld_amount": local_withheld["total"],
        "it_tax_domicile_comune": local["comune"],
        "it_tax_domicile_region": local["region"],
        "it_fringe_amount": fringe["amount"],
        "it_fringe_child_declared": fringe["child_declared"],
        "it_employee_total": employee_total,
        "it_calculation_trace": trace,
    }
