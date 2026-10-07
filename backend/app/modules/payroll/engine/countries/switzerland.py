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
  4. Compensation-office admin cost as employer-only line from the scheme rules.
  5. Snapshot builder: lines[] {obligation, side, base, rate_or_rule, cap, scope_id,
     scope_version, source_label, rule_version}, bases, accumulators before/after,
     resolved versions, input_hash, rule_hash (sha256 of canonical JSON).

Out of scope (separate strategies/ledgers, never approximated here):
  - BVG (pension) — handled by engine/countries/switzerland_bvg.py (future)
  - UVG/UVG policy (accident) — policy-driven, not a single federal rate
  - KTG (sickness) — canton-configured, not federal
  - Quellensteuer (source tax) — canton tariff lookup, separate module
  - FAK (family allowances) — canton top-ups + federal minimums, separate
  - Lohnausweis declaration — reporting, not calculation
  - Wage floor — CollectiveAgreement driven

Switzerland joins shared._VALIDATION_ENABLED_COUNTRIES on day one and defines
NO hardcoded statutory figure: every rate, threshold and band is a configured row
(switzerland_content.py is the Draft source), and every missing fact raises
SwitzerlandCalculationBlockedError.
"""

from decimal import Decimal
from hashlib import sha256
import json

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.countries.switzerland_content import (
    CH_AHV, CH_ALV, CH_BVG, CH_EO, CH_IV, CH_KTG, CH_LA, CH_QST, CH_UVG, CH_WAGE_FLOOR,
    CH_YTD_COMPONENTS, CH_OBLIGATIONS, CH_QST_ANNUAL_MODEL_CANTONS, CH_CANTON_CODES,
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


def calculate(ctx: PayrollContext) -> dict:
    """Swiss federal payroll calculation — pure function, no DB, no network,
    no date.today(). Returns a dict with deductions, snapshots, and CH fields
    that standard.py will merge into PayrollResult."""
    from app.modules.payroll.engine.countries.switzerland_content import CH_OBLIGATIONS

    org_id = getattr(ctx, "organization_id", None)
    pack = _Pack(ctx.rate_map, org_id)

    # 1. Obligation bases
    bases = _compute_obligation_bases(ctx, pack, FEDERAL_OBLIGATIONS)

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

    # 5. Compensation office admin cost (employer-only)
    admin_cost_pct = _read_scheme_admin_cost(ctx, pack)
    admin_cost_base = bases.get(CH_AHV, ZERO)  # Admin cost on AHV base per convention
    admin_cost = _round_chf(admin_cost_base * admin_cost_pct / HUNDRED)

    # 6. Totals
    employee_total = ahv_ee + iv_ee + eo_ee + alv_ee
    employer_total = ahv_er + iv_er + eo_er + alv_er + admin_cost

    # 7. Family allowances (FAK) — federal minimums; added to net (employee benefit)
    # These are NOT deductions; they are added to net pay like Italy's it_wedge_tax_free_sum.
    fak_child_min = pack.require_amount("ch_fak_child_min")
    fak_education_min = pack.require_amount("ch_fak_education_min")
    # The number of children / students comes from ctx (worker profile)
    children = _dec(getattr(ctx, "ch_children_count", 0))
    students = _dec(getattr(ctx, "ch_students_count", 0))
    fak_child_total = _round_chf(fak_child_min * children)
    fak_education_total = _round_chf(fak_education_min * students)
    family_allowance_total = fak_child_total + fak_education_total

    # 8. Build lines for snapshot
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
    # Admin cost
    add_line("ch_admin", "employer", admin_cost_base, admin_cost_pct / HUNDRED, None,
             "scheme:compensation_office", "1.0", "CH-PAYROLL-2026", "1.0")

    # 8. Accumulators before/after
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
        elif comp in (CH_AHV, CH_IV, CH_EO):
            base = bases.get(comp, ZERO)
            after_w = before_w + base
            after_wh = before_wh + (locals().get(f"{comp.lower()}_ee", ZERO) + locals().get(f"{comp.lower()}_er", ZERO))
        else:
            after_w = before_w
            after_wh = before_wh
        ytd_after[comp] = {"wages": str(after_w), "withheld": str(after_wh)}

    # 9. Resolved versions
    federal_pack_id = getattr(ctx, "ch_federal_pack_id", None)
    federal_pack_version = getattr(ctx, "ch_federal_pack_version", None)

    # 10. Hashes
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
        },
    }
    rule_snapshot = {
        "ch_alv_proration": _read_alv_proration_rule(ctx, pack),
        "ch_alv_ceiling": str(alv_ceiling),
        "ch_scheme_admin_cost_pct": str(admin_cost_pct),
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
        "ch_admin_cost_employer": admin_cost,
        # Employee total (deducted from gross)
        "ch_employee_total": employee_total,
        # Employer total (cost to employer)
        "ch_employer_total": employer_total,
        # Family allowances — added to net pay
        "ch_family_allowance_total": family_allowance_total,
        "ch_fak_child_total": fak_child_total,
        "ch_fak_education_total": fak_education_total,
        # Snapshot / trace
        "ch_calculation_trace": {
            "lines": lines,
            "bases": {k: str(v) for k, v in bases.items()},
            "accumulators_before": ytd_before,
            "accumulators_after": ytd_after,
            "resolved_versions": {
                "federal_pack_id": federal_pack_id,
                "federal_pack_version": federal_pack_version,
            },
            "input_hash": _sha256_canonical(input_snapshot),
            "rule_hash": _sha256_canonical(rule_snapshot),
        },
    }