"""modules/payroll/engine/countries/switzerland.py
-------------------------------------------------
Switzerland (CH spec) — fail-closed payroll calculation on the shared engine.

Same doctrine as italy.py / sweden.py: one country file, `calculate(ctx) -> dict`,
no framework or ORM imports. Every statutory value comes from a configured row
(`ctx.rate_map` / `ctx.slabs`), and every missing fact raises
SwitzerlandCalculationBlockedError — a MissingComplianceConfigurationError
subclass, so the existing MISSING_COMPLIANCE_CONFIGURATION 400 handler applies
unchanged.

Calculation order (each step consumes the one before it):
  1. Obligation bases: for each obligation in FEDERAL_OBLIGATIONS (AHV, IV, EO, ALV),
     base[obl] = sum of (earning * classification(earning_type, obl)).
     Missing classification BLOCKS.
  2. AHV, IV, EO as three separate lines — employee + employer each, rates from
     the Active federal pack.
  3. ALV: insured base = min(base, max(0, ceiling - ytd_alv_before)). Separate
     accumulator; proration method read from content rule (blocks if missing).
  4. UVG (accident): compulsory for every employee. BU is employer-only at the
     LIVE UVG_POLICY scheme's risk-class rate; NBU splits the risk-class's NBU
     rate only when ch_weekly_hours meets the pack minimum. Both insured
     earnings are capped by the statutory ceiling via the CH_UVG accumulator.
     A missing policy / risk class BLOCKS.
  5. KTG (sickness): only when a LIVE KTG_POLICY scheme is assigned — the
     policy's rate/split charged on KTG's own classified earnings base.
  6. QST (Quellensteuer — source tax): the canton pack's ch_qst_model selects
     the MONTHLY or ANNUAL strategy. Determination income comes from
     CH_QST-classified earnings, split into PERIODIC and APERIODIC (bonus,
     13th month) by TaxabilityRule.treatment. The tariff ROW (rate_pct /
     min_tax / row_id) is researched by the service (lookup_qst_rate on the
     ACTIVE canton file) and passed in context — the engine never reads a
     canton file. Annual-model arithmetic is PENDING G1 SIGN-OFF.
  7. Compensation-office admin cost as employer-only line from the scheme rules.
  8. Snapshot builder: lines[] {obligation, side, base, rate_or_rule, cap, scope_id,
     scope_version, source_label, rule_version}, bases, accumulators before/after,
     resolved versions, input_hash, rule_hash (sha256 of canonical JSON).

Out of scope (separate strategies/ledgers, never approximated here):
  - FAK (family allowances) — canton top-ups + federal minimums, separate
  - Lohnausweis declaration — reporting, not calculation
  - Wage floor — CollectiveAgreement driven
  - General tax declaration (Bezüger/Veranlagung) — falls back to the
    Quellensteuer tariff as the default and is outside the engine either way

Switzerland joins shared._VALIDATION_ENABLED_COUNTRIES on day one and defines
NO hardcoded statutory figure: every rate, threshold and band is a configured row
(switzerland_content.py is the Draft source), and every missing fact raises
SwitzerlandCalculationBlockedError.
"""

import copy
from decimal import Decimal
from hashlib import sha256
import json

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.countries.switzerland_content import (
    CH_AHV, CH_ALV, CH_BVG, CH_EO, CH_IV, CH_KTG, CH_LA, CH_QST, CH_UVG, CH_WAGE_FLOOR,
    CH_YTD_COMPONENTS, CH_OBLIGATIONS, CH_QST_ANNUAL_MODEL_CANTONS, CH_CANTON_CODES,
    CH_QST_MONTHS_PER_YEAR, CH_QST_PCT_DIVISOR,
    CH_ABSENCE_ALLOWANCE_EARNING, CH_ABSENCE_EARNING_TYPES, CH_EARNING_EMPLOYER_TOPUP,
    CH_FAK_AMOUNT_KEYS, CH_MONTHS_PER_YEAR, CH_WAGE_FLOOR_BASES,
)

# Federal obligations only — the ones this federal calculator handles.
# CH_IV and CH_EO are federal contributions but not in CH_OBLIGATIONS (which is for YTD tracking).
FEDERAL_OBLIGATIONS = (CH_AHV, CH_IV, CH_EO, CH_ALV)

_COUNTRY = "CH"
ZERO = Decimal("0")
HUNDRED = Decimal("100")


class SwitzerlandCalculationBlockedError(MissingComplianceConfigurationError):
    """A Swiss statutory calculation that must not proceed — missing configured
    row, missing or contradictory worker fact, or an unsupported case.
    Subclasses MissingComplianceConfigurationError so the existing main.py
    handler returns the same MISSING_COMPLIANCE_CONFIGURATION 400 every other
    fail-closed jurisdiction uses."""
    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Switzerland calculation blocked ({key}): {reason}",)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def _upper(value) -> str:
    return (value or "").strip().upper()


class _Pack:
    """Typed, fail-closed reader over ctx.rate_map — a configured row is the
    ONLY source of a value, and a missing row blocks (never a default)."""
    def __init__(self, rate_map: dict, organization_id):
        self.rate_map = rate_map or {}
        self.organization_id = organization_id

    def block(self, key: str, reason: str):
        raise SwitzerlandCalculationBlockedError(key, reason, self.organization_id)

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

    def require_text(self, key: str) -> str:
        row = self.rate_map.get(key)
        if row is None:
            self.block(key, "no configured parameter row")
        value = getattr(row, "text_value", None)
        if value is None:
            self.block(key, "row has no text value configured")
        return str(value).strip()


# ── CH_PARAMETER_KEYS parity (mirrors switzerland_content.CH_PARAMETER_KEYS) ──
# Each is a ContributionRate.component_key. Kind: employer_pct | employee_pct |
# amount | text. Rates are PERCENT numbers (4.35 = 4.35%).
CH_PARAMETER_KEYS = {
    # Federal
    "ch_ahv": "employee_pct",
    "ch_iv": "employee_pct",
    "ch_eo": "employee_pct",
    "ch_alv": "employee_pct",
    "ch_alv_ceiling": "amount",
    "ch_uvg_ceiling": "amount",
    "ch_nbu_min_weekly_hours": "amount",
    "ch_bvg_entry_threshold": "amount",
    "ch_bvg_coordination_deduction": "amount",
    "ch_bvg_upper_salary": "amount",
    "ch_bvg_min_coordinated": "amount",
    "ch_fak_child_min": "amount",
    "ch_fak_education_min": "amount",
    "ch_fak_earnings_threshold_month": "amount",
    "ch_fak_earnings_threshold_year": "amount",
    "ch_eo_parental_pct": "employee_pct",
    "ch_eo_daily_cap": "amount",
    "ch_rounding_rule": "amount",
    # Canton (scaffold keys — not read by federal calculator)
    "ch_qst_model": "text",
    "ch_qst_tariff_file_id": "text",
    "ch_fak_child": "amount",
    "ch_fak_education": "amount",
    "ch_fak_employee_pct": "employee_pct",
}


# ── Rounding helper (Swiss 5-Rappen convention: nearest CHF 0.05) ──────────
def _round_chf(value: Decimal) -> Decimal:
    """Round to the nearest 5 Rappen (CHF 0.05)."""
    # Multiply by 20, round to nearest integer, divide by 20
    return (value * Decimal("20")).quantize(Decimal("1"), rounding="ROUND_HALF_UP") / Decimal("20")


def _sha256_canonical(obj) -> str:
    """SHA-256 of canonical JSON (sorted keys, no whitespace)."""
    return sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read_ytd_before(ctx: PayrollContext, component: str) -> Decimal:
    """Read YTD wages for a CH component from context. ctx.ytd is a dict:
    {component: {"wages": Decimal, "withheld": Decimal, "recorded": bool}}."""
    if hasattr(ctx, "ytd") and ctx.ytd and component in ctx.ytd:
        return _dec(ctx.ytd[component].get("wages"))
    return ZERO


def _read_ytd_withheld_before(ctx: PayrollContext, component: str) -> Decimal:
    if hasattr(ctx, "ytd") and ctx.ytd and component in ctx.ytd:
        return _dec(ctx.ytd[component].get("withheld"))
    return ZERO


def _compute_obligation_bases(ctx: PayrollContext, pack: _Pack, obligations) -> dict:
    """base[obl] = sum(earning * classification(earning_type, obl)).
    classification is resolved per earning_type per obligation from ctx.
    Missing classification for any earning that has a non-zero amount BLOCKS."""
    bases = {}
    for obl in obligations:
        total = ZERO
        for earning_type, amount in getattr(ctx, "earnings", {}).items():
            if _dec(amount) == ZERO:
                continue
            # Classification map: {obligation: {earning_type: is_included}}
            # Resolved by service.resolve_ch_calc_inputs -> ctx.ch_classification
            classification_map = getattr(ctx, "ch_classification", {})
            obl_map = classification_map.get(obl, {})
            included = obl_map.get(earning_type)
            if included is None:
                pack.block(f"ch_classification:{obl}:{earning_type}",
                           f"no earning classification for {earning_type} under {obl}")
            if included is True:
                total += _dec(amount)
        bases[obl] = _round2(total)
    return bases


def _read_scheme_admin_cost(ctx: PayrollContext, pack: _Pack) -> Decimal:
    """Compensation office admin cost from the scheme rules (employer-only).
    ctx.ch_scheme_rules is the rules dict from the LIVE COMPENSATION_OFFICE scheme."""
    scheme_rules = getattr(ctx, "ch_scheme_rules", {})
    admin_cost_pct = scheme_rules.get("admin_cost_pct")
    if admin_cost_pct is None:
        pack.block("ch_scheme_admin_cost_pct", "compensation office scheme has no admin_cost_pct")
    return _dec(admin_cost_pct)


def _read_alv_proration_rule(ctx: PayrollContext, pack: _Pack) -> str:
    """ALV proration method from content rule. Returns 'monthly' or 'annual'."""
    rule = getattr(ctx, "ch_alv_proration_rule", None)
    if not rule:
        pack.block("ch_alv_proration_rule", "no ALV proration rule configured")
    rule = rule.strip().lower()
    if rule not in ("monthly", "annual"):
        pack.block("ch_alv_proration_rule", f"invalid ALV proration rule: {rule}")
    return rule


# ── BVG (Berufliche Vorsorge) — occupational pension ──────────────────────
# All BVG logic driven by the LIVE BVG_PLAN scheme rules from ctx.ch_scheme_rules.
# The scheme provides bands (age-based and/or salary-based) with employee/employer
# rates and MANDATORY/EXTRA_MANDATORY types. Pack provides statutory guardrails:
# entry threshold, coordination deduction, upper salary, min coordinated salary.

def _check_bvg_eligibility(ctx: PayrollContext, pack: _Pack) -> bool:
    """BVG mandatory insurance (Art. 2 BVG): age 17+ and annual salary at or
    above the entry threshold from the Active federal pack. The contract-duration
    determination is the resolver's job (employment profile, not re-derived here)."""
    entry_threshold = pack.require_amount("ch_bvg_entry_threshold")
    payroll_date = getattr(ctx, "payroll_date", None)
    if payroll_date is None:
        pack.block("ch_payroll_date", "payroll date is required for BVG eligibility")
    dob = getattr(ctx, "ch_date_of_birth", None)
    if dob is None:
        pack.block("ch_date_of_birth", "date of birth is required for BVG eligibility")
    annual_salary = _dec(getattr(ctx, "ch_annual_salary", None))
    if annual_salary is None or annual_salary <= ZERO:
        pack.block("ch_annual_salary", "annual salary (ctc) is required for BVG eligibility")
    if getattr(ctx, "ch_bvg_exempt", False):
        return False
    # Age check: 17+ (BVG Art. 2/7 — VERIFY AGAINST G1 STATUTORY REVIEW)
    age = payroll_date.year - dob.year - ((payroll_date.month, payroll_date.day) < (dob.month, dob.day))
    if age < 17:
        return False
    # Annual salary threshold
    if annual_salary < entry_threshold:
        return False
    return True


def _bvg_age(ctx: PayrollContext) -> int:
    """Whole years completed at the payroll date. -1 when the facts are absent."""
    payroll_date = getattr(ctx, "payroll_date", None)
    dob = getattr(ctx, "ch_date_of_birth", None)
    if payroll_date is None or dob is None:
        return -1
    return payroll_date.year - dob.year - ((payroll_date.month, payroll_date.day) < (dob.month, dob.day))


def _calculate_coordinated_salary(annual_salary: Decimal, pack: _Pack) -> Decimal:
    """BVG coordinated (insured) salary with statutory guardrails.
    Formula: max(min_coordinated, min(annual_salary - coordination_deduction, upper_salary)).
    Statutory figures come only from the Active federal pack."""
    coordination_deduction = pack.require_amount("ch_bvg_coordination_deduction")
    upper_salary = pack.require_amount("ch_bvg_upper_salary")
    min_coordinated = pack.require_amount("ch_bvg_min_coordinated")
    raw = annual_salary - coordination_deduction
    coordinated = min(max(raw, min_coordinated), upper_salary)
    return _round_chf(coordinated)


def _select_bvg_band(scheme_rules: dict, component: str, age: int, subject: Decimal):
    """The plan band for a component ('MANDATORY' or 'EXTRA_MANDATORY') matching
    the worker's age and — when the band defines one — the subject-salary window.
    A MANDATORY band is legally required and its absence blocks; an absent
    EXTRA_MANDATORY band simply means no extra-mandatory cover is elected.
    Bands come from the LIVE BVG_PLAN scheme rules (BvgBand: component,
    age_from/age_to, optional salary_from/salary_to for EXTRA_MANDATORY)."""
    bands = scheme_rules.get("bands") or []
    if not bands:
        raise SwitzerlandCalculationBlockedError(
            "ch_bvg_plan:bands_missing", "BVG_PLAN scheme has no bands configured", organization_id=None)
    for band in bands:
        if band.get("component") != component:
            continue
        age_from = band.get("age_from")
        age_to = band.get("age_to")
        if age_from is None or age_to is None:
            continue
        if not (age_from <= age <= age_to):
            continue
        salary_from = band.get("salary_from")
        salary_to = band.get("salary_to")
        if salary_from is not None and subject < _dec(salary_from):
            continue
        if salary_to is not None and subject > _dec(salary_to):
            continue
        employee_pct = band.get("employee_pct")
        employer_pct = band.get("employer_pct")
        if employee_pct is None or employer_pct is None:
            raise SwitzerlandCalculationBlockedError(
                "ch_bvg_plan:band_rate_missing",
                f"{component} band ages {age_from}-{age_to} missing employee/employer rate",
                organization_id=None)
        okay, idx = _validate_bvg_scheme_employer_share({"bands": [band]})
        if not okay:
            raise SwitzerlandCalculationBlockedError(
                "ch_bvg_plan:employer_share_invalid",
                f"{component} band {idx} employer share below 50%", organization_id=None)
        return band
    if component == "MANDATORY":
        raise SwitzerlandCalculationBlockedError(
            "ch_bvg_plan:no_matching_band",
            f"no MANDATORY BVG band matches age {age} and subject salary {subject}",
            organization_id=None)
    return None


def _validate_bvg_scheme_employer_share(scheme_rules: dict):
    """Employer pays at least half of each band's total premium. Enforced at
    scheme validation (BvgBand._shape) and re-checked here so a band that ever
    bypassed schema validation can never slip through a calculation."""
    for idx, band in enumerate(scheme_rules.get("bands", [])):
        employee = band.get("employee_pct")
        if employee is None:
            employee = band.get("employee_amount")
        employer = band.get("employer_pct")
        if employer is None:
            employer = band.get("employer_amount")
        if _dec(employer) < _dec(employee):
            return False, idx
    return True, -1


def _calculate_bvg(ctx: PayrollContext, pack: _Pack):
    """BVG contributions for the pay period. Every contribution is a monthly
    proportion of its annual subject: MANDATORY insures the coordinated salary,
    EXTRA_MANDATORY (when elected) insures the plan band's own salary slice.
    Returns a dict with per-band monthly employee/employer amounts and the
    annual subject, or None when the worker is not BVG-insured."""
    if not _check_bvg_eligibility(ctx, pack):
        return None

    scheme_id = getattr(ctx, "ch_bvg_plan_scheme_id", None)
    if scheme_id is None:
        pack.block("ch_bvg_plan:not_assigned", "BVG-eligible worker has no BVG_PLAN scheme assigned")
    scheme_rules = getattr(ctx, "ch_bvg_scheme_rules", None)
    if scheme_rules is None:
        pack.block("ch_bvg_plan:rules_missing", "BVG_PLAN scheme rules not resolved in context")

    age = _bvg_age(ctx)
    annual_salary = _dec(getattr(ctx, "ch_annual_salary", ZERO))
    coordinated = _calculate_coordinated_salary(annual_salary, pack)

    mandatory_band = _select_bvg_band(scheme_rules, "MANDATORY", age, coordinated)
    extra_band = _select_bvg_band(scheme_rules, "EXTRA_MANDATORY", age, annual_salary)

    def _monthly(annual_subject: Decimal, band: dict):
        ee = _round_chf(annual_subject / Decimal("12") * _dec(band["employee_pct"]) / HUNDRED)
        er = _round_chf(annual_subject / Decimal("12") * _dec(band["employer_pct"]) / HUNDRED)
        return ee, er

    mandatory_ee, mandatory_er = _monthly(coordinated, mandatory_band)
    if extra_band is not None:
        floor = _dec(extra_band.get("salary_from", ZERO))
        ceiling = extra_band.get("salary_to")
        extra_subject = max(annual_salary - floor, ZERO)
        if ceiling is not None:
            extra_subject = min(extra_subject, max(_dec(ceiling) - floor, ZERO))
        extra_ee, extra_er = _monthly(extra_subject, extra_band)
    else:
        extra_subject = ZERO
        extra_ee = extra_er = ZERO

    return {
        "mandatory": {"ee": mandatory_ee, "er": mandatory_er, "annual_subject": coordinated, "band": mandatory_band},
        "extra": {"ee": extra_ee, "er": extra_er, "annual_subject": extra_subject, "band": extra_band},
    }


# ── UVG (accident insurance) — policy-driven BU + NBU, statutory ceiling ────
# UVG is compulsory for every employee, so a missing policy or risk class BLOCKS
# (never a default). BU (Berufsunfall) is employer-only at the risk class's BU
# rate. NBU (Nichtberufsunfall) is split employee/employer from the risk
# class's NBU rate, and applies only when the weekly working time meets the
# pack minimum (S5). Both sit under the statutory ceiling, tracked period-over-
# period by the CH_UVG accumulator exactly like ALV.

def _split_premium(pack: _Pack, key: str, rate_pct: Decimal, employee_share_pct: Decimal):
    """(employee rate, employer rate) in salary percent: the employee pays
    `employee_share_pct` percent OF the premium rate, the employer the rest.
    A share outside 0..100 BLOCKS (it would make one side negative)."""
    if not (ZERO <= employee_share_pct <= HUNDRED):
        pack.block(key, f"employee share {employee_share_pct} must be a percentage of the premium (0-100)")
    employee = rate_pct * employee_share_pct / HUNDRED
    return employee, rate_pct - employee


def _calculate_uvg(ctx: PayrollContext, pack: _Pack, uvg_base: Decimal) -> dict:
    """UVG BU + NBU for the period. Returns the split amounts, the capped
    insured base and the policy/pack facts used to derive them; anything
    missing (policy, risk class, weekly hours, statutory figures) BLOCKS."""
    scheme_id = getattr(ctx, "ch_uvg_policy_scheme_id", None)
    if scheme_id is None:
        pack.block("ch_uvg_policy:not_assigned", "no LIVE UVG_POLICY scheme is assigned")
    scheme_rules = getattr(ctx, "ch_uvg_scheme_rules", None)
    if scheme_rules is None:
        pack.block("ch_uvg_policy:rules_missing", "UVG policy rules not resolved in context")
    risk_classes = scheme_rules.get("risk_classes") or []
    wanted = _upper(getattr(ctx, "ch_uvg_risk_class", None))
    risk_class = next((rc for rc in risk_classes if _upper(rc.get("code")) == wanted), None)
    if risk_class is None:
        pack.block("ch_uvg_risk_class:not_found",
                   f"risk class {getattr(ctx, 'ch_uvg_risk_class', None)!r} is not in UVG policy {scheme_id}")
    bu_pct = risk_class.get("bu_employer_pct")
    if bu_pct is None:
        pack.block("ch_uvg_risk_class:bu_rate_missing", "risk class has no BU employer rate")

    ceiling = pack.require_amount("ch_uvg_ceiling")
    ytd_before = _read_ytd_before(ctx, CH_UVG)
    insurable = min(uvg_base, max(ZERO, ceiling - ytd_before))
    bu_employer = _round_chf(insurable * _dec(bu_pct) / HUNDRED)

    min_hours = pack.require_amount("ch_nbu_min_weekly_hours")
    weekly_hours = getattr(ctx, "ch_weekly_hours", None)
    if weekly_hours is None:
        pack.block("ch_weekly_hours", "weekly working time is required to decide NBU applicability")
    nbu_employee = nbu_employer = ZERO
    nbu_ee_pct = nbu_er_pct = ZERO
    if _dec(weekly_hours) >= _dec(min_hours):
        nbu_pct = risk_class.get("nbu_pct")
        nbu_ee_share = risk_class.get("nbu_employee_share_pct")
        if nbu_pct is None or nbu_ee_share is None:
            pack.block("ch_uvg_risk_class:nbu_rate_missing", "risk class has no NBU rate / employee share")
        # nbu_employee_share_pct is the employee's SHARE of the NBU premium
        # (0-100, Step 5 contract — commonly 100: NBU may be charged to the
        # employee in full), never a rate in salary percentage points.
        nbu_ee_pct, nbu_er_pct = _split_premium(pack, "ch_uvg_risk_class:nbu_share", _dec(nbu_pct),
                                                _dec(nbu_ee_share))
        nbu_employee = _round_chf(insurable * nbu_ee_pct / HUNDRED)
        nbu_employer = _round_chf(insurable * nbu_er_pct / HUNDRED)

    return {"bu_employer": bu_employer, "nbu_employee": nbu_employee, "nbu_employer": nbu_employer,
            "insurable": insurable, "ceiling": ceiling, "min_weekly_hours": _dec(min_hours),
            "bu_pct": _dec(bu_pct), "nbu_ee_pct": nbu_ee_pct, "nbu_er_pct": nbu_er_pct}


# ── KTG (sickness daily allowance) — scheme-elected, its own classified base ─
# KTG has no federal rate: it contributes only when a LIVE KTG_POLICY scheme is
# assigned, charging the policy's total rate split by its employee share on
# KTG's own classified earnings base. No policy -> no KTG line, no base demand.

def _calculate_ktg(ctx: PayrollContext, pack: _Pack, ktg_base: Decimal) -> dict | None:
    """KTG contributions when the worker is covered by a LIVE KTG_POLICY
    scheme; None when no policy is assigned. A policy without its rules,
    rate or employee share BLOCKS."""
    if getattr(ctx, "ch_ktg_policy_scheme_id", None) is None:
        return None
    scheme_rules = getattr(ctx, "ch_ktg_scheme_rules", None)
    if scheme_rules is None:
        pack.block("ch_ktg_policy:rules_missing", "KTG policy rules not resolved in context")
    rate_pct = scheme_rules.get("rate_pct")
    if rate_pct is None:
        pack.block("ch_ktg_policy:rate_missing", "KTG policy has no rate_pct")
    employee_share_pct = scheme_rules.get("employee_share_pct")
    if employee_share_pct is None:
        pack.block("ch_ktg_policy:share_missing", "KTG policy has no employee_share_pct")
    # employee_share_pct is the employee's SHARE of the policy premium (0-100)
    ee_pct, er_pct = _split_premium(pack, "ch_ktg_policy:share", _dec(rate_pct), _dec(employee_share_pct))
    return {"employee": _round_chf(ktg_base * ee_pct / HUNDRED),
            "employer": _round_chf(ktg_base * er_pct / HUNDRED),
            "base": ktg_base, "ee_pct": ee_pct, "er_pct": er_pct}


# ── QST (Quellensteuer — source tax) — canton model + tariff row in ctx ──────
# QST is employee-only. The canton pack's ch_qst_model (content vocabulary
# CH_QST_MODELS) selects the strategy: MONTHLY (Monatsmodell, tariff keyed on
# the monthly determination income) or ANNUAL (Jahresmodell: FR/GE/TI/VD/VS,
# annual determination income tariffed, monthly withholding back-apportioned).
# Determination income is CH_QST-classified earnings split into PERIODIC and
# APERIODIC (bonus/13th) by TaxabilityRule.treatment; the tariff ROW itself
# (rate_pct / min_tax / row_id) is researched service-side by lookup_qst_rate
# against the ACTIVE canton file and passed in context — this module never
# touches a canton tariff file. A missing or contradictory fact BLOCKS; a
# worker recorded NO is skipped; a review state never calculates.

def _field(obj, name, default=None):
    """dict-or-object accessor: engine context facts arrive as attribute pairs
    (ch_qst_rate as a dict), so stay symmetric for both shapes."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _require_qst_rate(ctx: PayrollContext, pack: _Pack, aperiodic: bool = False):
    """The tariff row the service researched for this payslip (lookup_qst_rate
    on the ACTIVE file — a SUPERSEDED file replays identically by id). Returns
    (rate_pct, min_tax, row_id). Nothing is defaulted: a missing row BLOCKS."""
    attr = "ch_qst_aperiodic_rate" if aperiodic else "ch_qst_rate"
    row = getattr(ctx, attr, None)
    if not row:
        pack.block(attr, "no QST tariff row was passed in context (service lookup_qst_rate)")
    rate_pct = _field(row, "rate_pct")
    if rate_pct is None:
        pack.block(attr, "the QST tariff row has no rate_pct")
    row_id = _field(row, "row_id")
    if row_id is None:
        pack.block(attr, "the QST tariff row has no row_id (replay identity of the tariff file)")
    min_tax = _field(row, "min_tax")
    return _dec(rate_pct), (_dec(min_tax) if min_tax is not None else None), row_id


def _qst_determination_incomes(ctx: PayrollContext, pack: _Pack):
    """(periodic, aperiodic) CH_QST determination income. The included earning
    types come from the Approved CH_QST classification (ch_classification), and
    PERIODIC vs APERIODIC from TaxabilityRule.treatment. A non-zero included
    earning without a treatment BLOCKS — the split is never guessed."""
    periodic = aperiodic = ZERO
    classification = (getattr(ctx, "ch_classification", {}) or {}).get(CH_QST, {})
    treatments = getattr(ctx, "ch_qst_treatment", {}) or {}
    for earning_type, amount in (getattr(ctx, "earnings", {}) or {}).items():
        if _dec(amount) == ZERO:
            continue
        included = classification.get(earning_type)
        if included is None:
            pack.block(f"ch_classification:{CH_QST}:{earning_type}",
                       f"no earning classification for {earning_type} under {CH_QST}")
        if not included:
            continue
        treatment = _upper(treatments.get(earning_type))
        if treatment not in ("PERIODIC", "APERIODIC"):
            pack.block(f"ch_qst_treatment:{earning_type}",
                       f"QST-classified earning {earning_type} has no PERIODIC/APERIODIC treatment")
        if treatment == "PERIODIC":
            periodic += _dec(amount)
        else:
            aperiodic += _dec(amount)
    return _round2(periodic), _round2(aperiodic)


def _qst_combined_income(ctx: PayrollContext, pack: _Pack, periodic_base: Decimal):
    """Multiple employment (KS 45): each employer withholds on the salary it
    pays at the rate determined on the worker's TOTAL determination income.
    ch_other_employment_pct is the recorded share earned elsewhere, so the
    combined base is a proportional gross-up of this employer's base. Returns
    (combined, own, other_pct); combined == own when not multiple employment."""
    if not getattr(ctx, "ch_multiple_employment", False):
        return periodic_base, periodic_base, None
    other_value = getattr(ctx, "ch_other_employment_pct", None)
    if other_value is None:
        pack.block("ch_other_employment_pct", "multiple employment is flagged — the share of income from "
                                              "other employment (ch_other_employment_pct) is required")
    other_pct = _dec(other_value)
    if not (ZERO < other_pct < Decimal("1")):
        pack.block("ch_other_employment_pct",
                   f"the share of other-employment income must be between 0 and 1, got {other_pct}")
    own_pct = Decimal("1") - other_pct
    return _round2(periodic_base / own_pct), _round2(periodic_base), other_pct


def _qst_apply_rate(base: Decimal, rate_pct: Decimal, min_tax) -> Decimal:
    """QST = determination income * tariff rate (the percentage applies to the
    whole bracket income, an ESTV variant) floored by the row's minimum tax
    when the bracket sets one. Arithmetic parameters come from content."""
    tax = base * rate_pct / CH_QST_PCT_DIVISOR
    if min_tax is not None and tax < min_tax:
        tax = min_tax
    return tax


def _qst_monthly(ctx: PayrollContext, pack: _Pack, periodic_base: Decimal, aperiodic_base: Decimal,
                 periodic_rate: Decimal, periodic_min_tax, aperiodic_rate: Decimal, aperiodic_min_tax) -> dict:
    """MONTHLY model (Monatsmodell, the default). The tariff is keyed on the
    monthly determination income: QST = income * rate (min_tax floor). An
    aperiodic payment is taxed separately on its own amount with its own row."""
    periodic_tax = _round_chf(_qst_apply_rate(periodic_base, periodic_rate, periodic_min_tax))
    aperiodic_tax = ZERO
    if aperiodic_base > ZERO:
        aperiodic_tax = _round_chf(_qst_apply_rate(aperiodic_base, aperiodic_rate, aperiodic_min_tax))
    return {"periodic_tax": periodic_tax, "aperiodic_tax": aperiodic_tax,
            "annual_income": None, "annual_tax": None}


def _qst_annual(ctx: PayrollContext, pack: _Pack, periodic_base: Decimal, aperiodic_base: Decimal,
                periodic_rate: Decimal, periodic_min_tax, aperiodic_rate: Decimal, aperiodic_min_tax) -> dict:
    """ANNUAL model (Jahresmodell: canton packs CH-FR / CH-GE / CH-TI / CH-VD / CH-VS).

    PENDING G1 SIGN-OFF — the annual-model ARITHMETIC below (annualise the
    monthly determination income by CH_QST_MONTHS_PER_YEAR, apply the annual
    tariff with its min_tax floor, then back-apportion the annual tax into the
    monthly withholding by the same divisor) is implemented from the ESTV
    Jahresmodell description as understood at build time and has NOT been
    confirmed by the G1 statutory review. It must be re-verified against the
    published annual tariff files before any real annual-model canton payslip
    is calculated. The aperiodic part is taxed directly on the payment with its
    own row in both models (withheld in the payment month)."""
    annual_income = periodic_base * CH_QST_MONTHS_PER_YEAR
    annual_tax = _qst_apply_rate(annual_income, periodic_rate, periodic_min_tax)
    periodic_tax = _round_chf(annual_tax / CH_QST_MONTHS_PER_YEAR)
    aperiodic_tax = ZERO
    if aperiodic_base > ZERO:
        aperiodic_tax = _round_chf(_qst_apply_rate(aperiodic_base, aperiodic_rate, aperiodic_min_tax))
    return {"periodic_tax": periodic_tax, "aperiodic_tax": aperiodic_tax,
            "annual_income": annual_income, "annual_tax": annual_tax}


_QST_STRATEGIES = {"MONTHLY": _qst_monthly, "ANNUAL": _qst_annual}


def qst_lookup_incomes(ctx) -> dict:
    """The incomes the service must look the QST tariff rows up on, derived
    with the engine's OWN determination logic so the row the service passes
    in context always matches the income the strategy taxes:
      periodic  — the (combined, for multiple employment) monthly
                  determination income; annualised by the content divisor
                  for the ANNUAL model, whose tariff is annual;
      aperiodic — the aperiodic payment itself (its own row), or None.
    Blocks exactly as the calculation would."""
    pack = _Pack(getattr(ctx, "rate_map", None) or {}, getattr(ctx, "organization_id", None))
    # absence allowances can be QST-classified too: the same earnings the
    # calculation will see
    ctx, _applied = _with_absence_earnings(ctx, pack)
    model = _upper(getattr(ctx, "ch_qst_model", None))
    if model not in _QST_STRATEGIES:
        pack.block("ch_qst_model", f"the canton pack does not set a known QST model (got {model!r})")
    periodic_base, aperiodic_base = _qst_determination_incomes(ctx, pack)
    combined, _own, _other = _qst_combined_income(ctx, pack, periodic_base)
    periodic = combined * CH_QST_MONTHS_PER_YEAR if model == "ANNUAL" else combined
    return {"model": model, "periodic": periodic, "aperiodic": aperiodic_base if aperiodic_base > ZERO else None}


def _calculate_qst(ctx: PayrollContext, pack: _Pack) -> dict | None:
    """Quellensteuer for the period; None when the worker is recorded NOT
    QST-liable (ch_qst_subject == NO). A YES subject without the canton / model /
    tariff facts, a review state, or an aperiodic payment without its own rate
    row all BLOCK. The canton pack's ch_qst_model picks the strategy."""
    subject = _upper(getattr(ctx, "ch_qst_subject", None))
    if subject == "NO":
        return None
    if subject != "YES":
        pack.block("ch_qst_subject_review", f"ch_qst_subject is {subject!r} — a review state never calculates")

    canton = getattr(ctx, "ch_qst_canton", None)
    if not canton:
        pack.block("ch_qst_canton", "a QST-liable worker needs a CH-XX QST canton")
    model = _upper(getattr(ctx, "ch_qst_model", None))
    strategy = _QST_STRATEGIES.get(model)
    if strategy is None:
        pack.block("ch_qst_model", f"the canton pack does not set a known QST model (got {model!r})")
    tariff_code = getattr(ctx, "ch_qst_tariff_code", None)
    if not tariff_code:
        pack.block("ch_qst_tariff_code", "a QST-liable worker needs a tariff code")
    tariff_file_id = getattr(ctx, "ch_qst_tariff_file_id", None)
    if tariff_file_id is None:
        pack.block("ch_qst_tariff_file", "no QST tariff file id was passed in context")
    if getattr(ctx, "ch_qst_children", None) is None:
        pack.block("ch_qst_children", "the children count is needed for the QST tariff")
    church = getattr(ctx, "ch_qst_church_tax", None)
    if church is None:
        pack.block("ch_qst_church_tax", "church-tax liability is needed for the QST tariff")

    periodic_base, aperiodic_base = _qst_determination_incomes(ctx, pack)
    combined, own_base, other_pct = _qst_combined_income(ctx, pack, periodic_base)

    periodic_rate, periodic_min_tax, row_id = _require_qst_rate(ctx, pack)
    aperiodic_rate = aperiodic_min_tax = aperiodic_row_id = None
    if aperiodic_base > ZERO:
        aperiodic_rate, aperiodic_min_tax, aperiodic_row_id = _require_qst_rate(ctx, pack, aperiodic=True)

    result = strategy(ctx, pack, own_base, aperiodic_base, periodic_rate, periodic_min_tax,
                      aperiodic_rate, aperiodic_min_tax)
    result.update({
        "model": model, "canton": canton, "tariff_file_id": tariff_file_id,
        "file_sha256": getattr(ctx, "ch_qst_tariff_file_sha256", None),
        "tariff_code": tariff_code,
        "children": getattr(ctx, "ch_qst_children", None),
        "church_tax": bool(church),
        "row_id": row_id, "aperiodic_row_id": aperiodic_row_id,
        "rate_pct": periodic_rate, "min_tax": periodic_min_tax,
        "aperiodic_rate_pct": aperiodic_rate, "aperiodic_min_tax": aperiodic_min_tax,
        "periodic_base": own_base, "aperiodic_base": aperiodic_base,
        "combined_income": combined, "other_employment_pct": other_pct,
    })
    return result


# ── Step 11: absence-benefit earnings ─────────────────────────────────────
# Each absence event's insurer daily allowance (EO / UVG / KTG) and the
# employer's top-up enter the calculation as their OWN earning types, so the
# per-obligation TaxabilityRule classification decides each one separately
# (a missing classification blocks exactly as for any other earning). The
# per-period amounts are prepared service-side from the event rows.

def _with_absence_earnings(ctx: PayrollContext, pack: _Pack):
    events = getattr(ctx, "ch_absence_earnings", None) or []
    if not events:
        return ctx, []
    earnings = dict(getattr(ctx, "earnings", {}) or {})
    for earning_type in CH_ABSENCE_EARNING_TYPES:
        if _dec(earnings.get(earning_type)) != ZERO:
            pack.block(f"ch_absence_earning:{earning_type}",
                       "absence earnings come only from absence events, never as a manual earning")
    applied = []
    for event in events:
        event_id, event_type = _field(event, "event_id"), _upper(_field(event, "event_type"))
        if event_type not in CH_ABSENCE_ALLOWANCE_EARNING:
            pack.block(f"ch_absence_event:{event_id}", f"unknown absence event type {event_type!r}")
        allowance, topup = _dec(_field(event, "allowance")), _dec(_field(event, "topup"))
        if allowance < ZERO or topup < ZERO:
            pack.block(f"ch_absence_event:{event_id}", "absence amounts cannot be negative")
        earning_type = CH_ABSENCE_ALLOWANCE_EARNING[event_type]
        if allowance > ZERO:
            if earning_type is None:
                pack.block(f"ch_absence_event:{event_id}", f"{event_type} carries no insurer allowance")
            earnings[earning_type] = _dec(earnings.get(earning_type)) + allowance
        if topup > ZERO:
            earnings[CH_EARNING_EMPLOYER_TOPUP] = _dec(earnings.get(CH_EARNING_EMPLOYER_TOPUP)) + topup
        applied.append({"event_id": event_id, "event_type": event_type, "earning_type": earning_type,
                        "allowance": str(_round2(allowance)), "topup": str(_round2(topup))})
    # never mutate the caller's context: calculate() stays a pure function
    merged = copy.copy(ctx)
    merged.earnings = earnings
    return merged, applied


# ── Step 11: family allowances (FAK) ─────────────────────────────────────
# Paid ONLY per APPROVED entitlement (the service passes those overlapping the
# period) at the CANTON pack amount. A canton amount below the federal
# minimum BLOCKS — the federal minimum is never substituted. A child recorded
# on the profile without an approved entitlement is paid nothing.

def _canton_param(ctx: PayrollContext, canton, key):
    maps = getattr(ctx, "ch_canton_rate_maps", None) or {}
    return (maps.get(canton) or {}).get(key)


def _calculate_fak_allowances(ctx: PayrollContext, pack: _Pack):
    totals = {allowance_type: ZERO for allowance_type in CH_FAK_AMOUNT_KEYS}
    paid = []
    for ent in getattr(ctx, "ch_fak_entitlements", None) or []:
        ent_id = _field(ent, "id")
        allowance_type = _upper(_field(ent, "allowance_type"))
        basis = _upper(_field(ent, "entitlement_basis")) or "PRIMARY"
        keys = CH_FAK_AMOUNT_KEYS.get(allowance_type)
        if keys is None:
            pack.block(f"ch_fak_{allowance_type.lower() or 'type'}",
                       f"entitlement {ent_id}: no configured amount for {allowance_type or 'an unknown'} allowances")
        canton_key, minimum_key = keys
        canton = _field(ent, "canton") or getattr(ctx, "ch_work_canton", None)
        if canton not in CH_CANTON_CODES:
            pack.block("ch_fak_canton", f"entitlement {ent_id}: no CH-XX canton to pay it from")
        row = _canton_param(ctx, canton, canton_key)
        amount = getattr(row, "flat_amount", None) if row is not None else None
        if amount is None:
            pack.block(f"{canton_key}:{canton}", f"the {canton} pack has no {allowance_type} allowance amount")
        amount = _dec(amount)
        minimum = pack.require_amount(minimum_key)
        if amount < minimum:
            pack.block("ch_fak_below_federal_minimum",
                       f"{canton} {allowance_type} allowance {amount} is below the federal minimum {minimum} "
                       "(the federal minimum is never substituted — correct the canton pack)")
        if basis == "PRIMARY":
            due = amount
        elif basis == "DIFFERENTIAL":
            primary = _field(ent, "primary_amount")
            if primary is None:
                pack.block(f"ch_fak_differential:{ent_id}",
                           "a differential entitlement needs the amount the primary fund pays")
            due = max(ZERO, amount - _dec(primary))
        else:
            pack.block(f"ch_fak_basis:{ent_id}", f"unknown entitlement basis {basis!r}")
        due = _round_chf(due)
        totals[allowance_type] += due
        paid.append({"entitlement_id": ent_id, "allowance_type": allowance_type, "basis": basis, "canton": canton,
                     "canton_amount": str(amount), "federal_minimum": str(minimum),
                     "primary_amount": str(_dec(_field(ent, "primary_amount"))) if basis == "DIFFERENTIAL" else None,
                     "paid": str(due)})
    return totals, paid


def _calculate_fak_contributions(ctx: PayrollContext, pack: _Pack, ahv_base: Decimal) -> dict:
    """Employer FAK contribution at the LIVE FAK scheme's employer_pct on the
    AHV base. An employee share exists ONLY where the work canton's pack
    configures ch_fak_employee_pct (Valais) — never from the scheme alone."""
    rules = getattr(ctx, "ch_fak_scheme_rules", None)
    if rules is None:
        pack.block("ch_fak_scheme", "no LIVE FAK scheme rules")
    employer_pct = rules.get("employer_pct")
    if employer_pct is None:
        pack.block("ch_fak_scheme", "the FAK scheme has no employer_pct")
    canton = getattr(ctx, "ch_work_canton", None)
    row = _canton_param(ctx, canton, "ch_fak_employee_pct")
    employee_pct = getattr(row, "employee_rate_pct", None) if row is not None else None
    employer_pct = _dec(employer_pct)
    employee_pct = _dec(employee_pct) if employee_pct is not None else None
    return {
        "employer_pct": employer_pct, "employee_pct": employee_pct, "canton": canton,
        "employer": _round_chf(ahv_base * employer_pct / HUNDRED),
        "employee": _round_chf(ahv_base * employee_pct / HUNDRED) if employee_pct is not None else ZERO,
    }


# ── Step 11: wage floor ───────────────────────────────────────────────────
# Switzerland has no federal statutory minimum wage. A floor applies only by
# SCOPE: a canton minimum only where the worker's work canton is that canton;
# a GAV / NAV only when assigned to the worker. Countable pay is the
# CH_WAGE_FLOOR-classified earnings; a shortfall BLOCKS (no automatic top-up).

def _floor_amount(ctx: PayrollContext, pack: _Pack, agreement) -> Decimal:
    code = _field(agreement, "agreement_code")
    floor = _field(agreement, "wage_floor") or {}
    scales = floor.get("scales") or []
    occupation, grade = getattr(ctx, "ch_occupation", None), getattr(ctx, "ch_grade", None)
    experience = getattr(ctx, "ch_experience_years", None)
    matches = []
    for scale in scales:
        if scale.get("occupation") is not None and scale["occupation"] != occupation:
            continue
        if scale.get("grade") is not None and scale["grade"] != grade:
            continue
        needed = scale.get("experience_years_from")
        if needed is not None and (experience is None or _dec(experience) < _dec(needed)):
            continue
        matches.append(scale)
    if matches:
        best = max(matches, key=lambda s: (_dec(s.get("experience_years_from")),
                                           s.get("grade") is not None, s.get("occupation") is not None))
        return _dec(best["amount"])
    if floor.get("amount") is not None:
        return _dec(floor["amount"])
    pack.block(f"ch_wage_floor_scale:{code}",
               f"no {code} scale row matches occupation {occupation!r} / grade {grade!r} / experience {experience}")


def _check_wage_floor(ctx: PayrollContext, pack: _Pack) -> dict:
    work = getattr(ctx, "ch_work_canton", None)
    applicable, skipped = [], []
    for a in getattr(ctx, "ch_wage_floor_agreements", None) or []:
        code, kind, canton = _field(a, "agreement_code"), _field(a, "agreement_type"), _field(a, "canton")
        if kind == "CH_CANTON_MINIMUM":
            in_scope = canton is not None and canton == work
            why = f"canton minimum for {canton}; the worker works in {work}"
        elif kind in ("CH_GAV", "CH_NAV"):
            in_scope = bool(_field(a, "assigned")) and (canton is None or canton == work)
            why = "not assigned to this worker" if not _field(a, "assigned") else f"{canton} agreement; work canton {work}"
        else:
            pack.block(f"ch_wage_floor_type:{code}", f"unknown wage-floor agreement type {kind!r}")
        (applicable if in_scope else skipped).append(a if in_scope else {"agreement_code": code, "reason": why})
    if not applicable:
        return {"rule": "NO_MANDATORY_FLOOR",
                "basis": f"no federal statutory minimum wage; no Active canton minimum in scope for {work}; "
                         "no GAV / NAV assigned to this worker",
                "skipped": skipped, "checks": []}
    countable = _compute_obligation_bases(ctx, pack, (CH_WAGE_FLOOR,))[CH_WAGE_FLOOR]
    checks = []
    for a in applicable:
        code = _field(a, "agreement_code")
        basis = _upper((_field(a, "wage_floor") or {}).get("basis"))
        if basis not in CH_WAGE_FLOOR_BASES:
            pack.block(f"ch_wage_floor_basis:{code}", f"unknown wage-floor basis {basis!r}")
        floor = _floor_amount(ctx, pack, a)
        if basis == "HOURLY":
            hours = getattr(ctx, "ch_period_hours", None)
            if hours is None or _dec(hours) <= ZERO:
                pack.block("ch_period_hours", f"{code} is an hourly floor: the hours paid this period are needed")
            denominator = _dec(hours)
            rate = countable / denominator
        elif basis == "MONTHLY":
            denominator, rate = None, countable
        else:
            denominator, rate = None, countable * CH_MONTHS_PER_YEAR
        check = {"agreement_id": _field(a, "id"), "agreement_code": code, "agreement_type": _field(a, "agreement_type"),
                 "version": _field(a, "version"), "basis": basis, "countable_pay": str(countable),
                 "denominator": str(denominator) if denominator is not None else None,
                 "pay_rate": str(_round2(rate)), "floor": str(floor)}
        if rate < floor:
            pack.block("ch_wage_floor_shortfall",
                       f"{code}: {basis.lower()} pay {_round2(rate)} is below the floor {floor} "
                       "(no automatic top-up — correct the pay)")
        checks.append(check)
    return {"rule": "CHECKED", "basis": None, "skipped": skipped, "checks": checks}


def calculate(ctx: PayrollContext) -> dict:
    """Swiss federal payroll calculation — pure function, no DB, no network,
    no date.today(). Returns a dict with deductions, snapshots, and CH fields
    that standard.py will merge into PayrollResult."""
    from app.modules.payroll.engine.countries.switzerland_content import CH_OBLIGATIONS

    org_id = getattr(ctx, "organization_id", None)
    pack = _Pack(ctx.rate_map, org_id)

    # 0. Absence-benefit allowances / top-ups join the earnings as their own
    #    earning types (classified per obligation like any other earning).
    ctx, absence_applied = _with_absence_earnings(ctx, pack)

    # 1. Obligation bases
    bases = _compute_obligation_bases(ctx, pack, FEDERAL_OBLIGATIONS)

    # UVG base is compulsory (accident insurance covers every employee); KTG
    # base is only demanded when a LIVE KTG_POLICY scheme is assigned — both on
    # their own classified earnings, exactly as the Step 6 resolver resolves.
    uvg_base = _compute_obligation_bases(ctx, pack, (CH_UVG,)).get(CH_UVG, ZERO)
    bases[CH_UVG] = uvg_base
    if getattr(ctx, "ch_ktg_policy_scheme_id", None) is not None:
        ktg_base = _compute_obligation_bases(ctx, pack, (CH_KTG,)).get(CH_KTG, ZERO)
        bases[CH_KTG] = ktg_base
    else:
        ktg_base = ZERO

    # 2. Federal rates (AHV, IV, EO, ALV from federal pack)
    ahv_ee_pct = pack.require_pct("ch_ahv", "employee")
    ahv_er_pct = pack.require_pct("ch_ahv", "employer")
    iv_ee_pct = pack.require_pct("ch_iv", "employee")
    iv_er_pct = pack.require_pct("ch_iv", "employer")
    eo_ee_pct = pack.require_pct("ch_eo", "employee")
    eo_er_pct = pack.require_pct("ch_eo", "employer")
    alv_ee_pct = pack.require_pct("ch_alv", "employee")
    alv_er_pct = pack.require_pct("ch_alv", "employer")

    alv_ceiling = pack.require_amount("ch_alv_ceiling")

    # 3. AHV / IV / EO — simple percentage on their obligation base
    ahv_base = bases.get(CH_AHV, ZERO)
    iv_base = bases.get(CH_IV, ZERO)
    eo_base = bases.get(CH_EO, ZERO)

    ahv_ee = _round_chf(ahv_base * ahv_ee_pct / HUNDRED)
    ahv_er = _round_chf(ahv_base * ahv_er_pct / HUNDRED)
    iv_ee = _round_chf(iv_base * iv_ee_pct / HUNDRED)
    iv_er = _round_chf(iv_base * iv_er_pct / HUNDRED)
    eo_ee = _round_chf(eo_base * eo_ee_pct / HUNDRED)
    eo_er = _round_chf(eo_base * eo_er_pct / HUNDRED)

    # 4. ALV — capped by ceiling minus YTD
    alv_base = bases.get(CH_ALV, ZERO)
    ytd_alv_before = _read_ytd_before(ctx, CH_ALV)
    alv_insurable_cap = max(ZERO, alv_ceiling - ytd_alv_before)
    alv_insurable = min(alv_base, alv_insurable_cap)

    alv_proration = _read_alv_proration_rule(ctx, pack)
    # If annual proration, the base is already annualised by the caller via YTD;
    # here we just apply the cap. The proration method affects how the cap is
    # tracked (monthly vs annual YTD accumulator). The pack row
    # ch_alv_proration_method tells us which accumulator to read.
    # For the federal calculator, we just enforce the cap on the insurable base.
    alv_ee = _round_chf(alv_insurable * alv_ee_pct / HUNDRED)
    alv_er = _round_chf(alv_insurable * alv_er_pct / HUNDRED)

    # 5. BVG (occupational pension) — from LIVE BVG_PLAN scheme rules
    lines = []
    def add_line(obligation, side, base, rate_or_rule, cap, scope_id, scope_version, source_label, rule_version):
        lines.append({
            "obligation": obligation,
            "side": side,
            "base": str(_round2(base)),
            "rate_or_rule": str(rate_or_rule),
            "cap": str(_round2(cap)) if cap is not None else None,
            "scope_id": scope_id,
            "scope_version": scope_version,
            "source_label": source_label,
            "rule_version": rule_version,
        })

    # BVG (occupational pension) — from BVG_PLAN scheme. Skipped entirely when
    # the worker is not BVG-insured (salary below entry threshold, under 17, or
    # exempt); an eligible worker without a live plan BLOCKS (fail-closed).
    bvg_result = _calculate_bvg(ctx, pack)
    bvg_mand_ee = bvg_result["mandatory"]["ee"] if bvg_result else ZERO
    bvg_mand_er = bvg_result["mandatory"]["er"] if bvg_result else ZERO
    bvg_extra_ee = bvg_result["extra"]["ee"] if bvg_result else ZERO
    bvg_extra_er = bvg_result["extra"]["er"] if bvg_result else ZERO
    bvg_ee = bvg_mand_ee + bvg_extra_ee
    bvg_er = bvg_mand_er + bvg_extra_er
    # Monthly insured wage fed to the CH_BVG YTD accumulator (no catch-up on a
    # mid-year threshold crossing — only the current period's approach applies).
    bvg_insurable = (_round_chf((bvg_result["mandatory"]["annual_subject"] + bvg_result["extra"]["annual_subject"]) / Decimal("12"))
                     if bvg_result else ZERO)

    # 7. UVG (accident) — BU employer-only + NBU split, capped by the CH_UVG
    #    accumulator's statutory ceiling. Mandatory for every employee.
    uvg = _calculate_uvg(ctx, pack, uvg_base)
    uvg_nbu_applies = (uvg["nbu_employee"] + uvg["nbu_employer"]) > ZERO
    uvg_employee = uvg["nbu_employee"]  # BU has no employee share
    uvg_employer = uvg["bu_employer"] + uvg["nbu_employer"]

    # 8. KTG (sickness) — only when a LIVE KTG_POLICY scheme is assigned; the
    #    policy's rate/split on KTG's own classified base.
    ktg = _calculate_ktg(ctx, pack, ktg_base)
    ktg_employee = ktg["employee"] if ktg else ZERO
    ktg_employer = ktg["employer"] if ktg else ZERO

    # 9. QST (Quellensteuer) — employee-only, canton model + tariff row from ctx.
    #    None when the worker is recorded NOT QST-liable (subject NO); a review
    #    state or a missing canton fact BLOCKS.
    qst = _calculate_qst(ctx, pack)
    qst_periodic = qst["periodic_tax"] if qst else ZERO
    qst_aperiodic = qst["aperiodic_tax"] if qst else ZERO
    qst_total = qst_periodic + qst_aperiodic

    # 10. Compensation office admin cost (employer-only)
    admin_cost_pct = _read_scheme_admin_cost(ctx, pack)
    admin_cost_base = bases.get(CH_AHV, ZERO)  # Admin cost on AHV base per convention
    admin_cost = _round_chf(admin_cost_base * admin_cost_pct / HUNDRED)

    # 10b. FAK contribution (employer from the FAK scheme; employee share only
    #      where the work canton's pack configures one) on the AHV base.
    fak_contrib = _calculate_fak_contributions(ctx, pack, bases.get(CH_AHV, ZERO))

    # 11. Totals
    employee_total = (ahv_ee + iv_ee + eo_ee + alv_ee + bvg_ee + uvg_employee + ktg_employee + qst_total
                      + fak_contrib["employee"])
    employer_total = (ahv_er + iv_er + eo_er + alv_er + bvg_er + admin_cost + uvg_employer + ktg_employer
                      + fak_contrib["employer"])

    # 11b. Family allowances (FAK) — per APPROVED entitlement at the canton
    #      amount; added to net (employee benefit), never deducted.
    fak_totals, fak_paid = _calculate_fak_allowances(ctx, pack)
    fak_child_total = fak_totals["CHILD"]
    fak_education_total = fak_totals["EDUCATION"]
    family_allowance_total = fak_child_total + fak_education_total

    # 11c. Wage floor — a blocking validation, never a top-up.
    wage_floor = _check_wage_floor(ctx, pack)
    absence_total = sum((_dec(ctx.earnings.get(t)) for t in CH_ABSENCE_EARNING_TYPES), ZERO)

    # 12. Build lines for snapshot (AHV/IV/EO/ALV/Admin lines)

    # AHV
    add_line(CH_AHV, "employee", ahv_base, ahv_ee_pct / HUNDRED, None,
             "federal", "1.0", "CH-PAYROLL-2026", "1.0")
    add_line(CH_AHV, "employer", ahv_base, ahv_er_pct / HUNDRED, None,
             "federal", "1.0", "CH-PAYROLL-2026", "1.0")
    # IV
    add_line(CH_IV, "employee", iv_base, iv_ee_pct / HUNDRED, None,
             "federal", "1.0", "CH-PAYROLL-2026", "1.0")
    add_line(CH_IV, "employer", iv_base, iv_er_pct / HUNDRED, None,
             "federal", "1.0", "CH-PAYROLL-2026", "1.0")
    # EO
    add_line(CH_EO, "employee", eo_base, eo_ee_pct / HUNDRED, None,
             "federal", "1.0", "CH-PAYROLL-2026", "1.0")
    add_line(CH_EO, "employer", eo_base, eo_er_pct / HUNDRED, None,
             "federal", "1.0", "CH-PAYROLL-2026", "1.0")
    # ALV
    add_line(CH_ALV, "employee", alv_insurable, alv_ee_pct / HUNDRED, alv_ceiling,
             "federal", "1.0", "CH-PAYROLL-2026", "1.0")
    add_line(CH_ALV, "employer", alv_insurable, alv_er_pct / HUNDRED, alv_ceiling,
             "federal", "1.0", "CH-PAYROLL-2026", "1.0")
    # BVG (mandatory, and extra-mandatory when elected) — scheme-scoped lines
    if bvg_result is not None:
        bvg_scope = f"scheme:bvg_plan:{getattr(ctx, 'ch_bvg_plan_scheme_id', None)}"
        mand_monthly = _round_chf(bvg_result["mandatory"]["annual_subject"] / Decimal("12"))
        add_line("ch_bvg_mandatory", "employee", mand_monthly,
                 _dec(bvg_result["mandatory"]["band"]["employee_pct"]) / HUNDRED, None,
                 bvg_scope, "1.0", "BVG_PLAN scheme", "1.0")
        add_line("ch_bvg_mandatory", "employer", mand_monthly,
                 _dec(bvg_result["mandatory"]["band"]["employer_pct"]) / HUNDRED, None,
                 bvg_scope, "1.0", "BVG_PLAN scheme", "1.0")
        if bvg_result["extra"]["band"] is not None:
            extra_monthly = _round_chf(bvg_result["extra"]["annual_subject"] / Decimal("12"))
            add_line("ch_bvg_extra_mandatory", "employee", extra_monthly,
                     _dec(bvg_result["extra"]["band"]["employee_pct"]) / HUNDRED, None,
                     bvg_scope, "1.0", "BVG_PLAN scheme", "1.0")
            add_line("ch_bvg_extra_mandatory", "employer", extra_monthly,
                     _dec(bvg_result["extra"]["band"]["employer_pct"]) / HUNDRED, None,
                     bvg_scope, "1.0", "BVG_PLAN scheme", "1.0")
    # UVG — policy-scoped lines (BU employer-only; NBU split when it applies)
    uvg_scope = f"scheme:uvg_policy:{getattr(ctx, 'ch_uvg_policy_scheme_id', None)}"
    add_line("ch_uvg_bu", "employer", uvg["insurable"], uvg["bu_pct"] / HUNDRED, uvg["ceiling"],
             uvg_scope, "1.0", "UVG_POLICY scheme", "1.0")
    if uvg_nbu_applies:
        add_line("ch_uvg_nbu", "employee", uvg["insurable"], uvg["nbu_ee_pct"] / HUNDRED, uvg["ceiling"],
                 uvg_scope, "1.0", "UVG_POLICY scheme", "1.0")
        add_line("ch_uvg_nbu", "employer", uvg["insurable"], uvg["nbu_er_pct"] / HUNDRED, uvg["ceiling"],
                 uvg_scope, "1.0", "UVG_POLICY scheme", "1.0")
    # KTG — policy-scoped lines (only when a LIVE KTG_POLICY scheme is assigned)
    if ktg is not None:
        ktg_scope = f"scheme:ktg_policy:{getattr(ctx, 'ch_ktg_policy_scheme_id', None)}"
        add_line("ch_ktg", "employee", ktg_base, ktg["ee_pct"] / HUNDRED, None,
                 ktg_scope, "1.0", "KTG_POLICY scheme", "1.0")
        add_line("ch_ktg", "employer", ktg_base, ktg["er_pct"] / HUNDRED, None,
                 ktg_scope, "1.0", "KTG_POLICY scheme", "1.0")
    # QST — tariff-file-scoped lines (employee only; the source tax has no
    # employer share). Scoped to the exact tariff file so a superseded file is
    # never silently reused for a later period.
    if qst is not None:
        qst_scope = f"qst_tariff:{qst['tariff_file_id']}"
        add_line("ch_qst_periodic", "employee", qst["periodic_base"],
                 qst["rate_pct"] / CH_QST_PCT_DIVISOR, None,
                 qst_scope, str(qst["row_id"]), "QST tariff file", "1.0")
        if qst["aperiodic_base"] > ZERO:
            add_line("ch_qst_aperiodic", "employee", qst["aperiodic_base"],
                     (qst["aperiodic_rate_pct"] or ZERO) / CH_QST_PCT_DIVISOR, None,
                     qst_scope, str(qst["aperiodic_row_id"]), "QST tariff file", "1.0")
    # Admin cost
    add_line("ch_admin", "employer", admin_cost_base, admin_cost_pct / HUNDRED, None,
             "scheme:compensation_office", "1.0", "CH-PAYROLL-2026", "1.0")
    # FAK contribution (employer; employee only where the canton configures it)
    fak_scope = f"scheme:fak:{getattr(ctx, 'ch_fak_scheme_id', None)}"
    add_line("ch_fak", "employer", bases.get(CH_AHV, ZERO), fak_contrib["employer_pct"] / HUNDRED, None,
             fak_scope, "1.0", "FAK scheme", "1.0")
    if fak_contrib["employee_pct"] is not None:
        add_line("ch_fak", "employee", bases.get(CH_AHV, ZERO), fak_contrib["employee_pct"] / HUNDRED, None,
                 f"canton:{fak_contrib['canton']}", "1.0", "canton pack ch_fak_employee_pct", "1.0")
    # Wage floor — an explicit line either way: the floor checked, or why none applies
    if wage_floor["rule"] == "NO_MANDATORY_FLOOR":
        add_line(CH_WAGE_FLOOR, "check", ZERO, "NO_MANDATORY_FLOOR", None,
                 f"canton:{getattr(ctx, 'ch_work_canton', None)}", "1.0", wage_floor["basis"], "1.0")
    for check in wage_floor["checks"]:
        add_line(CH_WAGE_FLOOR, "check", _dec(check["countable_pay"]), f"{check['basis']} floor {check['floor']}",
                 None, f"agreement:{check['agreement_id']}", str(check["version"]), check["agreement_code"], "1.0")

    # 13. Accumulators before/after
    ytd_before = {}
    ytd_after = {}
    for comp in CH_YTD_COMPONENTS:
        before_w = _read_ytd_before(ctx, comp)
        before_wh = _read_ytd_withheld_before(ctx, comp)
        ytd_before[comp] = {"wages": str(before_w), "withheld": str(before_wh)}
        # After: add this period's insurable (for ALV) or base (others)
        if comp == CH_ALV:
            after_w = before_w + alv_insurable
            after_wh = before_wh + alv_ee + alv_er
        elif comp == CH_BVG:
            after_w = before_w + bvg_insurable
            after_wh = before_wh + bvg_ee + bvg_er
        elif comp == CH_UVG:
            after_w = before_w + uvg["insurable"]
            after_wh = before_wh + uvg_employee + uvg_employer
        elif comp == CH_KTG:
            after_w = before_w + ktg_base
            after_wh = before_wh + ktg_employee + ktg_employer
        elif comp == CH_QST:
            qst_wages = qst["periodic_base"] + qst["aperiodic_base"] if qst else ZERO
            after_w = before_w + qst_wages
            after_wh = before_wh + qst_total
        elif comp in (CH_AHV, CH_IV, CH_EO):
            base = bases.get(comp, ZERO)
            after_w = before_w + base
            after_wh = before_wh + (locals().get(f"{comp.lower()}_ee", ZERO) + locals().get(f"{comp.lower()}_er", ZERO))
        else:
            after_w = before_w
            after_wh = before_wh
        ytd_after[comp] = {"wages": str(after_w), "withheld": str(after_wh)}

    # 14. Resolved versions
    federal_pack_id = getattr(ctx, "ch_federal_pack_id", None)
    federal_pack_version = getattr(ctx, "ch_federal_pack_version", None)

    # 15. Hashes
    input_snapshot = {
        "gross": str(ctx.gross),
        "basic": str(ctx.basic),
        "earnings": {k: str(v) for k, v in getattr(ctx, "earnings", {}).items()},
        "bases": {k: str(v) for k, v in bases.items()},
        "rates": {
            "ch_ahv_ee": str(ahv_ee_pct), "ch_ahv_er": str(ahv_er_pct),
            "ch_iv_ee": str(iv_ee_pct), "ch_iv_er": str(iv_er_pct),
            "ch_eo_ee": str(eo_ee_pct), "ch_eo_er": str(eo_er_pct),
            "ch_alv_ee": str(alv_ee_pct), "ch_alv_er": str(alv_er_pct),
            "ch_admin_pct": str(admin_cost_pct),
            "ch_uvg_bu_pct": str(uvg["bu_pct"]),
            "ch_uvg_nbu_ee_pct": str(uvg["nbu_ee_pct"]),
            "ch_uvg_nbu_er_pct": str(uvg["nbu_er_pct"]),
            "ch_ktg_ee_pct": str(ktg["ee_pct"]) if ktg else "0",
            "ch_ktg_er_pct": str(ktg["er_pct"]) if ktg else "0",
            "ch_qst_rate_pct": str(qst["rate_pct"]) if qst else "0",
            "ch_qst_aperiodic_rate_pct": str(qst["aperiodic_rate_pct"]) if qst and qst["aperiodic_base"] > ZERO else "0",
        },
    }
    rule_snapshot = {
        "ch_alv_proration": _read_alv_proration_rule(ctx, pack),
        "ch_alv_ceiling": str(alv_ceiling),
        "ch_scheme_admin_cost_pct": str(admin_cost_pct),
        "ch_bvg_eligible": str(bvg_result is not None),
        "ch_uvg_ceiling": str(uvg["ceiling"]),
        "ch_nbu_min_weekly_hours": str(uvg["min_weekly_hours"]),
        "ch_uvg_nbu_applicable": str(uvg_nbu_applies),
        "ch_ktg_elected": str(ktg is not None),
        "ch_qst_model": qst["model"] if qst else None,
        "ch_qst_canton": qst["canton"] if qst else None,
    }

    qst_trace = {
        "applies": qst is not None,
        "canton": qst["canton"] if qst else None,
        "model": qst["model"] if qst else None,
        "tariff_file_id": qst["tariff_file_id"] if qst else None,
        "file_sha256": qst["file_sha256"] if qst else None,
        "tariff_code": qst["tariff_code"] if qst else None,
        "children": qst["children"] if qst else None,
        "church_tax": qst["church_tax"] if qst else None,
        "row_id": qst["row_id"] if qst else None,
        "periodic_determination_income": str(qst["periodic_base"]) if qst else None,
        "aperiodic_determination_income": str(qst["aperiodic_base"]) if qst else None,
        "aperiodic_row_id": qst["aperiodic_row_id"] if qst else None,
        "rate_pct": str(qst["rate_pct"]) if qst else None,
        "min_tax": str(qst["min_tax"]) if qst and qst["min_tax"] is not None else None,
        "aperiodic_rate_pct": str(qst["aperiodic_rate_pct"]) if qst and qst["aperiodic_rate_pct"] is not None else None,
        "multiple_employment": bool(getattr(ctx, "ch_multiple_employment", False)),
        "other_employment_pct": str(qst["other_employment_pct"]) if qst and qst["other_employment_pct"] is not None else None,
        "combined_determination_income": str(qst["combined_income"]) if qst and qst["combined_income"] != qst["periodic_base"] else None,
        "annual_determination_income": str(_round2(qst["annual_income"])) if qst and qst["annual_income"] is not None else None,
        "annual_tax": str(_round2(qst["annual_tax"])) if qst and qst["annual_tax"] is not None else None,
    }

    return {
        # Deductions
        "ch_ahv_employee": ahv_ee,
        "ch_ahv_employer": ahv_er,
        "ch_iv_employee": iv_ee,
        "ch_iv_employer": iv_er,
        "ch_eo_employee": eo_ee,
        "ch_eo_employer": eo_er,
        "ch_alv_employee": alv_ee,
        "ch_alv_employer": alv_er,
        "ch_bvg_mandatory_employee": bvg_mand_ee,
        "ch_bvg_mandatory_employer": bvg_mand_er,
        "ch_bvg_extra_mandatory_employee": bvg_extra_ee,
        "ch_bvg_extra_mandatory_employer": bvg_extra_er,
        "ch_bvg_employee": bvg_ee,
        "ch_bvg_employer": bvg_er,
        "ch_uvg_bu_employer": uvg["bu_employer"],
        "ch_uvg_nbu_employee": uvg["nbu_employee"],
        "ch_uvg_nbu_employer": uvg["nbu_employer"],
        "ch_uvg_employee": uvg_employee,
        "ch_uvg_employer": uvg_employer,
        "ch_uvg_insurable": uvg["insurable"],
        "ch_ktg_employee": ktg_employee,
        "ch_ktg_employer": ktg_employer,
        "ch_qst_periodic": qst_periodic,
        "ch_qst_aperiodic": qst_aperiodic,
        "ch_qst_total": qst_total,
        "ch_qst_model": qst["model"] if qst else None,
        "ch_qst_determination_periodic": qst["periodic_base"] if qst else ZERO,
        "ch_qst_determination_aperiodic": qst["aperiodic_base"] if qst else ZERO,
        "ch_admin_cost_employer": admin_cost,
        # Employee total (deducted from gross)
        "ch_employee_total": employee_total,
        # Employer total (cost to employer)
        "ch_employer_total": employer_total,
        # Family allowances — added to net pay
        "ch_family_allowance_total": family_allowance_total,
        "ch_fak_child_total": fak_child_total,
        "ch_fak_education_total": fak_education_total,
        "ch_fak_employer": fak_contrib["employer"],
        "ch_fak_employee": fak_contrib["employee"],
        # Absence-benefit earnings (part of gross, each its own earning type)
        "ch_absence_earnings_total": absence_total,
        # Snapshot / trace
        "ch_calculation_trace": {
            "lines": lines,
            "bases": {k: str(v) for k, v in bases.items()},
            "accumulators_before": ytd_before,
            "accumulators_after": ytd_after,
            "qst": qst_trace,
            "fak": {"entitlements": fak_paid, "employer_pct": str(fak_contrib["employer_pct"]),
                    "employee_pct": str(fak_contrib["employee_pct"]) if fak_contrib["employee_pct"] is not None else None},
            "wage_floor": wage_floor,
            "absence": absence_applied,
            "resolved_versions": {
                "federal_pack_id": federal_pack_id,
                "federal_pack_version": federal_pack_version,
            },
            "input_hash": _sha256_canonical(input_snapshot),
            "rule_hash": _sha256_canonical(rule_snapshot),
        },
    }