"""
modules/payroll/engine/countries/france.py
----------------------------------------------
France production calculation path (ZP-FR-ENG-001, 2026-09-24).

`calculate(ctx)` is the ONE authoritative France entry point
(`engine/standard.py`'s `_COUNTRY_CALC["FR"]` and, through it,
`EnterpriseStrategy` too) — there is no silent second path. It:

1. Blocks on anything genuinely unresolvable (FR-027 / FR-014):
   unsupported social-coverage regime, Alsace-Moselle commune (not
   enabled at launch — spec §scoping), missing SIRET establishment
   facts, missing/unusable PAS rate (authority data — FR-008),
   SMIC or IDCC minimum-wage breach (FR-044/FR-039), or a mandatory
   2026 contribution rate with no configured `rate_map` row and no
   published hardcoded default. It NEVER returns a fabricated
   "zero-because-complete" result.

2. Computes each contribution on its OWN independent statutory base
   (FR-005): vieillesse capped (PSS), vieillesse uncapped (total),
   chomage/AGS (4×PASS, period ceiling), CSG/CRDS (98.25% base within a
   cumulative 4×PSS ceiling, full base above, deductible split preserved —
   FR-017), CFP on total remuneration, CET on T1+T2 (capped at 8 PSS),
   Agirc-Arrco T1/T2 + CEG + CET + Apec (monthly PSS tranches — FR-019),
   SIRET-scoped AT/MP and versement mobilité — FR-013, FNAL/CFP by
   governed effectif — FR-015.

3. Returns three separate nets (FR-042): net social, net imposable
   (returns non-deductible CSG AND CRDS to the taxable base — FR-017) and
   net à payer (net social − PAS), plus `fr_ytd_after` (the RGDU/CSG
   accumulator state after this period) for the service to persist.

4. Computes the 2026 réduction générale dégressive unique (RGDU) as a
   year-to-date accumulator (FR-023) using the décret n° 2026-509 frozen
   1-January SMIC reference (FR-024), producing gross theoretical relief,
   Urssaf/Agirc-Arrco split, monthly delta and cumulative total (FR-026).

Rate AND ceiling/threshold values are DATA (FR-003), resolved through
`ctx.rate_map` — the France canonical JurisdictionPack's ContributionRate
rows (scripts/seed_france_canonical_packs.py), editable by Super Admin in a
Draft pack version — with the published 2026 values in
`hardcoded_defaults._FR_*` as last-resort fallbacks only. Every mandatory
key (rates AND the PASS/SMIC/RGDU/CSG/PAS parameters below) with no
configured row blocks the calculation (FR-027), so a fallback constant can
never silently become the production value. Percent-type parameters
(`employee_rate_pct`/`employer_rate_pct`) are PERCENT numbers (6.90 = 6.90%);
amount-type parameters use `flat_amount`. This module never varies a rate
by hand: personalized PAS and SIRET establishment rates arrive pre-resolved
via `ctx.france_pas` / `ctx.france_establishment` (FR-008/FR-013).

Earning-level base awareness (FR-016 — never "98.25% × gross" as a
universal shortcut; replacement-income strategies FR-018; mutuelle/
prévoyance overlays FR-028; annual RGDU reconciliation and Agirc-Arrco
regularization) are phase-7 service/content layers that feed the same
fields this engine already consumes; see module-level docs in service.py.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    MONTHS_PER_YEAR,
    is_parameter_configured,
    resolve_jurisdiction_parameter,
)
from app.modules.payroll.hardcoded_defaults import (
    _FR_PASS_ANNUAL, _FR_PASS_MONTHLY,
    _FR_SMIC_2026_HOURLY_JAN_MAY, _FR_SMIC_2026_HOURLY_JUN,
    _FR_SMIC_2026_MONTHLY_JAN_MAY, _FR_SMIC_2026_MONTHLY_JUN,
    _FR_SMIC_2026_ANNUAL_FROZEN, _FR_SMIC_2026_HOURLY_FROZEN,
    _FR_SMIC_2026_FULLTIME_HOURS,
    _FR_VIEILLESSE_CAPPED_EE, _FR_VIEILLESSE_CAPPED_ER,
    _FR_VIEILLESSE_UNCAPPED_EE, _FR_VIEILLESSE_UNCAPPED_ER,
    _FR_CHOMAGE_ER, _FR_AGS_ER,
    _FR_SANTE_ER_STANDARD, _FR_SANTE_ER_REDUCED,
    _FR_SANTE_REDUCED_2_5_SMIC_BAND,
    _FR_FAMILLE_ER, _FR_CSA_ER_DEFAULT,
    _FR_FNAL_ER_0P10, _FR_FNAL_ER_0P50,
    _FR_CFP_ER_0P55, _FR_CFP_ER_1P00,
    _FR_APPRENTISSAGE_ER, _FR_APPRENTISSAGE_BALANCE_ER,
    _FR_AGIRC_T1_EE, _FR_AGIRC_T1_ER,
    _FR_AGIRC_T2_EE, _FR_AGIRC_T2_ER,
    _FR_CEG_T1_EE, _FR_CEG_T1_ER,
    _FR_CEG_T2_EE, _FR_CEG_T2_ER,
    _FR_CET_EE, _FR_CET_ER,
    _FR_APEC_EE, _FR_APEC_ER,
    _FR_CSG_EE_DEDUCTIBLE, _FR_CSG_EE_NONDEDUCTIBLE, _FR_CRDS_EE,
    _FR_CSG_BASE_FACTOR_98_25,
    _FR_RGDU_TMIN, _FR_RGDU_TDELTA_FNAL_0P10, _FR_RGDU_TDELTA_FNAL_0P50,
    _FR_RGDU_POWER, _FR_RGDU_ELIGIBILITY_MULTIPLE,
    _FR_PAS_SHORT_CONTRACT_ABATEMENT, _FR_PAS_APPRENTICE_THRESHOLD,
)

_ALSACE_MOSELLE_DEPARTEMENTS = ("57", "67", "68")

_FULL_TIME_HOURS = Decimal(_FR_SMIC_2026_FULLTIME_HOURS)  # 151.67

# Employer-size classes. The stored/admin vocabulary (models.py,
# schemas.py, the Super Admin rate-pack form) is UNDER_50/OVER_50 and
# UNDER_11/OVER_11; the engine's rate keys are named by rate (0p10 = 0.10%).
# Both spellings are accepted so an admin-entered pack never blocks on
# vocabulary alone.
_FNAL_CLASS_ALIASES = {"UNDER_50": "0p10", "OVER_50": "0p50", "0p10": "0p10", "0p50": "0p50"}
_CFP_CLASS_ALIASES = {"UNDER_11": "0p55", "OVER_11": "1p00", "0p55": "0p55", "1p00": "1p00"}


def normalize_fnal_class(value):
    return _FNAL_CLASS_ALIASES.get(str(value)) if value not in (None, "") else None


def normalize_cfp_class(value):
    return _CFP_CLASS_ALIASES.get(str(value)) if value not in (None, "") else None


class FranceCalculationBlockedError(ValueError):
    """Raised whenever France payroll MUST NOT proceed (FR-027: unknown
    mandatory rate = NOT_READY, never zero-as-final). Mirrors the
    GermanyCalculationError contract — callers translate to a block."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ── SMIC / PASS helpers ────────────────────────────────────────────────

def _smic_hourly(pay_date: date) -> Decimal:
    return _FR_SMIC_2026_HOURLY_JUN if pay_date >= date(2026, 6, 1) else _FR_SMIC_2026_HOURLY_JAN_MAY


def _smic_monthly(pay_date: date) -> Decimal:
    return _FR_SMIC_2026_MONTHLY_JUN if pay_date >= date(2026, 6, 1) else _FR_SMIC_2026_MONTHLY_JAN_MAY


def _hours_ratio(working_hours: Decimal) -> Decimal:
    if working_hours is not None and working_hours > Decimal("0"):
        return min(working_hours, _FULL_TIME_HOURS) / _FULL_TIME_HOURS
    return Decimal("1")


# ── rate resolution (content-as-data, FR-027 fail-closed) ──────────────

def _required(rate_map: dict, key: str, side: str, default: Decimal, missing: list, ctx: PayrollContext):
    """Resolve a mandatory rate via rate_map+default; record into `missing`
    when neither a configured row nor the published default is present."""
    if not is_parameter_configured(rate_map, key, side):
        missing.append(key)
    return resolve_jurisdiction_parameter(
        rate_map, key, default, side=side,
        country="FR", organization_id=getattr(ctx, "france_organization_id", None),
    )


def _optional(rate_map: dict, key: str, side: str, default: Decimal, ctx: PayrollContext):
    return resolve_jurisdiction_parameter(
        rate_map, key, default, side=side,
        country="FR", organization_id=getattr(ctx, "france_organization_id", None),
    )


def _amount(rate_map: dict, key: str, default: Decimal, missing: list, ctx: PayrollContext) -> Decimal:
    """Mandatory flat-amount parameter (ceiling, SMIC, threshold) — the
    amount twin of _required(). Row-level effective dating inside the pack
    (tax_resolver.resolve_tax_configuration) is what switches e.g. the SMIC
    on 1 June: the rate_map already holds the row in force on the pay date."""
    return Decimal(str(_required(rate_map, key, None, default, missing, ctx)))


def _ratio(rate_map: dict, key: str, side: str, default_pct: Decimal, missing: list, ctx: PayrollContext) -> Decimal:
    """Mandatory percent parameter returned as a fraction (37.81 → 0.3781).
    Used for RGDU coefficients/CSG factor: ContributionRate.flat_amount is
    Numeric(14,2), which would round 0.3781 to 0.38, so these live in the
    4-decimal percent columns instead."""
    return _pct(_required(rate_map, key, side, default_pct, missing, ctx))


# Parameter keys (FR-003 content catalog). Kept together so the seed
# script, the Super Admin component picker and the engine share one list.
FR_PARAMETER_KEYS = {
    "fr_pass_annual": "amount", "fr_pmss": "amount",
    "fr_smic_hourly": "amount", "fr_smic_monthly": "amount",
    "fr_smic_rgdu_annual": "amount", "fr_smic_rgdu_hourly": "amount",
    "fr_fulltime_monthly_hours": "amount",
    "fr_chomage_ceiling_pass_multiple": "amount",
    "fr_agirc_t2_ceiling_pss_multiple": "amount",
    "fr_apec_ceiling_pss_multiple": "amount",
    "fr_csg_abatement_ceiling_pss_multiple": "amount",
    "fr_csg_base_factor": "employee_pct",
    "fr_rgdu_tmin": "employer_pct", "fr_rgdu_tdelta_lt50": "employer_pct", "fr_rgdu_tdelta_ge50": "employer_pct",
    "fr_rgdu_power": "amount", "fr_rgdu_smic_multiple": "amount",
    "fr_pas_short_contract_abatement": "amount", "fr_pas_apprentice_threshold": "amount",
}


def _pct(rate: Decimal) -> Decimal:
    # Coerce defensive exactly like germany.py's Decimal(u1_rate) call sites —
    # rate_map rows may surface str or Decimal depending on the caller.
    return Decimal(str(rate)) / Decimal("100")


# ── PAS ────────────────────────────────────────────────────────────────

def _compute_pas(ctx: PayrollContext, net_imposable: Decimal, net_social: Decimal,
                 short_contract_abatement: Decimal, apprentice_threshold: Decimal) -> dict:
    pas = ctx.france_pas or {}
    rate_type = pas.get("rate_type")
    rate_pct = pas.get("rate_pct")
    if not rate_type:
        raise FranceCalculationBlockedError(
            "PAS_NOT_RESOLVED",
            "France payroll requires a pre-resolved PAS rate (PERSONALIZED authority rate "
            "from the DGFiP CRM or the legal NEUTRAL grid — ZP-FR-ENG-001 §4). None was "
            "supplied for this employee/pay date; resolve before running France payroll.",
        )
    if rate_type not in ("PERSONALIZED", "NEUTRAL"):
        raise FranceCalculationBlockedError(
            "PAS_TYPE_INVALID",
            f"Unsupported PAS rate_type '{rate_type}' — only PERSONALIZED and NEUTRAL are legal.",
        )
    rate = Decimal(str(rate_pct)) if rate_pct is not None else None
    if rate is None or rate < 0:
        raise FranceCalculationBlockedError(
            "PAS_RATE_MISSING",
            f"France PAS rate_type='{rate_type}' carried no usable rate_pct. "
            "Authority rates are data, never administrator-editable percentages (FR-008).",
        )

    pas_base = net_imposable
    abatement = Decimal("0")
    # Short-contract base abatement (spec §4): only on the NEUTRAL path and
    # only when the resolver confirmed the legal conditions hold.
    if rate_type == "NEUTRAL" and pas.get("short_contract"):
        abatement = min(short_contract_abatement, pas_base)
        pas_base = pas_base - abatement

    exempt = False
    apprentice_exempt_amount = Decimal("0")
    # Apprentice/trainee exemption (spec §4): the legally-eligible
    # remuneration is exempt UP TO the annual threshold (monthly share =
    # threshold / 12) — only the part above it is taxable. Measured on the
    # PAS base (net imposable), never on net social, and never all-or-
    # nothing: a remuneration just above the threshold is taxed only on the
    # excess.
    if pas.get("apprentice"):
        monthly_threshold = _round2(apprentice_threshold / MONTHS_PER_YEAR)
        apprentice_exempt_amount = min(pas_base, monthly_threshold)
        pas_base = pas_base - apprentice_exempt_amount
        exempt = pas_base <= Decimal("0")
    withheld = _round2(rate * pas_base / Decimal("100"))
    withheld = max(Decimal("0"), min(withheld, net_social))

    return {
        "rate_type": rate_type,
        "rate_pct": rate,
        "rate_id": pas.get("rate_id") or None,
        "grid_version": pas.get("grid_version") or None,
        "apprentice_exempt": exempt,
        "apprentice_exempt_amount": _round2(apprentice_exempt_amount),
        "pas_base": _round2(pas_base),
        "pas_base_gross": _round2(net_imposable),
        "short_contract_abatement": _round2(abatement),
        "withheld": withheld,
    }


# ── RGDU (2026 réduction générale dégressive unique, FR-023/FR-026) ────

def _rgdu_coefficient(remuneration_ytd: Decimal, smic_reference_ytd: Decimal, tdelta: Decimal,
                      tmin: Decimal, power: Decimal, multiple: Decimal) -> Decimal:
    if remuneration_ytd <= Decimal("0"):
        return Decimal("0")
    bracket = (Decimal("0.5")) * (multiple * smic_reference_ytd / remuneration_ytd - Decimal("1"))
    if bracket <= Decimal("0"):
        return Decimal("0")  # at/above 3×SMIC → out of the eligibility envelope
    coefficient = tmin + tdelta * (min(bracket, Decimal("1")) ** power)
    return min(coefficient, tmin + tdelta)


def _compute_rgdu(ctx: PayrollContext, params: dict, fnal_class: str,
                  employer_reducible: Decimal, retraite_share: Decimal) -> dict:
    """RGDU as a YTD accumulator (FR-023). `employer_reducible` is the sum
    of the period's employer contributions within the RGDU scope — the
    relief granted this period can never exceed them — and `retraite_share`
    the Agirc-Arrco T1 + CEG T1 employer portion inside that scope, so the
    Urssaf/Agirc-Arrco relief split is weighted on in-scope contributions
    only (FR-026).

    SMIC reference: each period contributes ONE period's worth of the
    frozen annual SMIC (annual / 12, prorated by hours) plus overtime hours
    at the frozen hourly SMIC — never the whole annual amount per period
    (which overstated the reference ~12× and the relief with it)."""
    tdelta = params["tdelta_ge50"] if fnal_class == "0p50" else params["tdelta_lt50"]
    tmin, power, multiple = params["tmin"], params["power"], params["multiple"]

    ytd = ctx.france_ytd or {}
    remuneration_before = Decimal(str(ytd.get("rgdu_remuneration") or 0))
    smic_reference_before = Decimal(str(ytd.get("rgdu_smic_reference") or 0))
    relief_granted_before = Decimal(str(ytd.get("rgdu_relief") or 0))

    working_hours = getattr(ctx, "france_working_hours", None)
    overtime_hours = getattr(ctx, "france_overtime_hours", None) or Decimal("0")

    remuneration_ytd = remuneration_before + ctx.gross
    smic_reference_period = (
        params["smic_annual"] / MONTHS_PER_YEAR * _hours_ratio(working_hours)
        + params["smic_hourly"] * Decimal(str(overtime_hours))
    )
    smic_reference_ytd = smic_reference_before + smic_reference_period

    def _ytd_after(relief_total):
        return {
            "rgdu_remuneration": _round2(remuneration_ytd),
            "rgdu_smic_reference": _round2(smic_reference_ytd),
            "rgdu_relief": _round2(relief_total),
        }

    if remuneration_ytd >= multiple * smic_reference_ytd:
        return {
            "eligible": False, "reason": "remuneration_at_or_above_3x_smic",
            "annual_remuneration": _round2(remuneration_ytd),
            "annual_smic_reference": _round2(smic_reference_ytd),
            "coefficient": Decimal("0"), "theoretical_relief": Decimal("0"),
            "already_granted": _round2(relief_granted_before),
            "monthly_delta": Decimal("0"),
            "relief_urssaf": Decimal("0"), "relief_agirc": Decimal("0"),
            "tdelta": tdelta, "fnal_class": fnal_class,
            "ytd_after": _ytd_after(relief_granted_before),
        }

    coefficient = _rgdu_coefficient(remuneration_ytd, smic_reference_ytd, tdelta, tmin, power, multiple)
    theoretical_ytd = _round2(coefficient * remuneration_ytd)
    # The period's relief (YTD theoretical minus what earlier periods
    # already granted) never exceeds THIS period's in-scope contributions.
    monthly_delta = min(max(Decimal("0"), theoretical_ytd - relief_granted_before), employer_reducible)

    urssaf_bucket = max(Decimal("0"), employer_reducible - retraite_share)
    agirc_bucket = retraite_share
    total_bucket = urssaf_bucket + agirc_bucket
    if total_bucket > Decimal("0"):
        relief_urssaf = _round2(monthly_delta * (urssaf_bucket / total_bucket))
        relief_agirc = max(Decimal("0"), monthly_delta - relief_urssaf)
    else:
        relief_urssaf, relief_agirc = Decimal("0"), Decimal("0")

    return {
        "eligible": True,
        "annual_remuneration": _round2(remuneration_ytd),
        "annual_smic_reference": _round2(smic_reference_ytd),
        "smic_reference_period": _round2(smic_reference_period),
        "overtime_hours": Decimal(str(overtime_hours)),
        "coefficient": coefficient,
        "tdelta": tdelta,
        "fnal_class": fnal_class,
        "theoretical_relief": _round2(theoretical_ytd),
        "already_granted": _round2(relief_granted_before),
        "monthly_delta": _round2(monthly_delta),
        "relief_urssaf": _round2(relief_urssaf),
        "relief_agirc": _round2(relief_agirc),
        "ytd_after": _ytd_after(relief_granted_before + monthly_delta),
    }


def calculate(ctx: PayrollContext) -> dict:
    """France production calculation — see module docstring. Raises
    FranceCalculationBlockedError for every non-runnable condition; returns
    employee-side and employer-side totals plus the France informational
    fields engine/standard.py propagates onto PayrollResult."""
    missing = []
    result = {}

    pay_date = ctx.france_payroll_date or ctx.pay_date
    if pay_date is None:
        raise FranceCalculationBlockedError(
            "PAYROLL_DATE_MISSING",
            "France calculation requires france_payroll_date (or generic pay_date).",
        )

    if ctx.france_social_coverage != "GENERAL":
        raise FranceCalculationBlockedError(
            "SOCIAL_COVERAGE_UNSUPPORTED",
            f"France launch supports the GENERAL metropolitan social regime only; "
            f"got social_coverage='{ctx.france_social_coverage}' (FR-014).",
        )

    establishment = ctx.france_establishment or {}
    fnal_class = normalize_fnal_class(establishment.get("fnal_class"))
    cfp_class = normalize_cfp_class(establishment.get("cfp_class"))
    missing_est = [
        k for k in ("siret", "at_mp_rate_pct")
        if establishment.get(k) in (None, "")
    ]
    if fnal_class is None:
        missing_est.append("fnal_class")
    if cfp_class is None:
        missing_est.append("cfp_class")
    if missing_est:
        raise FranceCalculationBlockedError(
            "ESTABLISHMENT_INCOMPLETE",
            "SIRET-scoped employer facts missing/invalid for this period (FR-013): " + ", ".join(missing_est),
        )

    commune_insee = str(establishment.get("commune_insee", ""))
    if commune_insee[:2] in _ALSACE_MOSELLE_DEPARTEMENTS:
        raise FranceCalculationBlockedError(
            "ALSACE_MOSELLE_NOT_ENABLED",
            "Alsace-Moselle departements (57/67/68) are NOT part of the France launch scope "
            "(ZP-FR-ENG-001 scoping) — local health and apprenticeship variations must be "
            "explicitly enabled before payroll may run there.",
        )

    rate_map = ctx.rate_map or {}

    # ── Statutory parameters (FR-003 content, pack rows) ──────────────
    pass_annual = _amount(rate_map, "fr_pass_annual", _FR_PASS_ANNUAL, missing, ctx)
    pmss = _amount(rate_map, "fr_pmss", _FR_PASS_MONTHLY, missing, ctx)
    smic_hourly = _amount(rate_map, "fr_smic_hourly", _smic_hourly(pay_date), missing, ctx)
    smic_monthly = _amount(rate_map, "fr_smic_monthly", _smic_monthly(pay_date), missing, ctx)
    full_time_hours = _amount(rate_map, "fr_fulltime_monthly_hours", _FULL_TIME_HOURS, missing, ctx)
    chomage_multiple = _amount(rate_map, "fr_chomage_ceiling_pass_multiple", Decimal("4"), missing, ctx)
    t2_multiple = _amount(rate_map, "fr_agirc_t2_ceiling_pss_multiple", Decimal("8"), missing, ctx)
    apec_multiple = _amount(rate_map, "fr_apec_ceiling_pss_multiple", Decimal("4"), missing, ctx)
    csg_abatement_multiple = _amount(rate_map, "fr_csg_abatement_ceiling_pss_multiple", Decimal("4"), missing, ctx)
    csg_factor = _ratio(rate_map, "fr_csg_base_factor", "employee", _FR_CSG_BASE_FACTOR_98_25, missing, ctx)
    rgdu_params = {
        "tmin": _ratio(rate_map, "fr_rgdu_tmin", "employer", _FR_RGDU_TMIN * 100, missing, ctx),
        "tdelta_lt50": _ratio(rate_map, "fr_rgdu_tdelta_lt50", "employer", _FR_RGDU_TDELTA_FNAL_0P10 * 100, missing, ctx),
        "tdelta_ge50": _ratio(rate_map, "fr_rgdu_tdelta_ge50", "employer", _FR_RGDU_TDELTA_FNAL_0P50 * 100, missing, ctx),
        "power": _amount(rate_map, "fr_rgdu_power", _FR_RGDU_POWER, missing, ctx),
        "multiple": _amount(rate_map, "fr_rgdu_smic_multiple", _FR_RGDU_ELIGIBILITY_MULTIPLE, missing, ctx),
        "smic_annual": _amount(rate_map, "fr_smic_rgdu_annual", _FR_SMIC_2026_ANNUAL_FROZEN, missing, ctx),
        "smic_hourly": _amount(rate_map, "fr_smic_rgdu_hourly", _FR_SMIC_2026_HOURLY_FROZEN, missing, ctx),
    }
    pas_short_contract_abatement = _amount(rate_map, "fr_pas_short_contract_abatement", _FR_PAS_SHORT_CONTRACT_ABATEMENT, missing, ctx)
    pas_apprentice_threshold = _amount(rate_map, "fr_pas_apprentice_threshold", _FR_PAS_APPRENTICE_THRESHOLD, missing, ctx)

    # ── Ceilings (FR-012: period PSS prorated by hours; every multiple of
    # the PSS is prorated the same way so part-time T2/Apec/4×PASS limits
    # stay consistent with T1) ─────────────────────────────────────────
    working_hours = getattr(ctx, "france_working_hours", None)
    ratio = (min(working_hours, full_time_hours) / full_time_hours
             if working_hours is not None and working_hours > Decimal("0") else Decimal("1"))
    pss_monthly = pmss * ratio
    four_pass_monthly = pass_annual * chomage_multiple / MONTHS_PER_YEAR * ratio
    gross = ctx.gross

    ytd = ctx.france_ytd or {}

    # ── Employee-side contributions (independent bases, FR-005) ───────
    vieillesse_capped_base = min(gross, pss_monthly)
    vieillesse_uncapped_base = gross
    chomage_base = min(gross, four_pass_monthly)

    vieillesse_capped_ee = _round2(vieillesse_capped_base * _pct(_required(rate_map, "fr_vieillesse_capped_ee", "employee", _FR_VIEILLESSE_CAPPED_EE, missing, ctx)))
    vieillesse_uncapped_ee = _round2(vieillesse_uncapped_base * _pct(_required(rate_map, "fr_vieillesse_uncapped_ee", "employee", _FR_VIEILLESSE_UNCAPPED_EE, missing, ctx)))

    vieillesse_capped_er = _round2(vieillesse_capped_base * _pct(_required(rate_map, "fr_vieillesse_capped_er", "employer", _FR_VIEILLESSE_CAPPED_ER, missing, ctx)))
    vieillesse_uncapped_er = _round2(vieillesse_uncapped_base * _pct(_required(rate_map, "fr_vieillesse_uncapped_er", "employer", _FR_VIEILLESSE_UNCAPPED_ER, missing, ctx)))

    # Agirc-Arrco T1/T2 + CEG + CET + Apec (monthly PSS tranches, FR-019)
    t1_base = min(gross, pss_monthly)
    t2_base = min(max(gross - pss_monthly, Decimal("0")), pss_monthly * t2_multiple - pss_monthly)
    # CET (FR-021): applies only when remuneration exceeds T1; its base is
    # then T1 + T2 (i.e. capped at 8 PSS), never the uncapped gross.
    cet_base = (t1_base + t2_base) if gross > pss_monthly else Decimal("0")
    apec_base = (min(gross, pss_monthly * apec_multiple) if ctx.france_cadre else Decimal("0"))

    agirc_t1_ee = _round2(t1_base * _pct(_required(rate_map, "fr_agirc_t1_ee", "employee", _FR_AGIRC_T1_EE, missing, ctx)))
    agirc_t1_er = _round2(t1_base * _pct(_required(rate_map, "fr_agirc_t1_er", "employer", _FR_AGIRC_T1_ER, missing, ctx)))
    agirc_t2_ee = _round2(t2_base * _pct(_required(rate_map, "fr_agirc_t2_ee", "employee", _FR_AGIRC_T2_EE, missing, ctx)))
    agirc_t2_er = _round2(t2_base * _pct(_required(rate_map, "fr_agirc_t2_er", "employer", _FR_AGIRC_T2_ER, missing, ctx)))
    ceg_t1_ee = _round2(t1_base * _pct(_required(rate_map, "fr_ceg_t1_ee", "employee", _FR_CEG_T1_EE, missing, ctx)))
    ceg_t1_er = _round2(t1_base * _pct(_required(rate_map, "fr_ceg_t1_er", "employer", _FR_CEG_T1_ER, missing, ctx)))
    ceg_t2_ee = _round2(t2_base * _pct(_required(rate_map, "fr_ceg_t2_ee", "employee", _FR_CEG_T2_EE, missing, ctx)))
    ceg_t2_er = _round2(t2_base * _pct(_required(rate_map, "fr_ceg_t2_er", "employer", _FR_CEG_T2_ER, missing, ctx)))
    cet_ee = _round2(cet_base * _pct(_required(rate_map, "fr_cet_ee", "employee", _FR_CET_EE, missing, ctx)))
    cet_er = _round2(cet_base * _pct(_required(rate_map, "fr_cet_er", "employer", _FR_CET_ER, missing, ctx)))
    apec_ee = _round2(apec_base * _pct(_required(rate_map, "fr_apec_ee", "employee", _FR_APEC_EE, missing, ctx)))
    apec_er = _round2(apec_base * _pct(_required(rate_map, "fr_apec_er", "employer", _FR_APEC_ER, missing, ctx)))

    # CSG/CRDS — the 98.25% factor applies to qualifying salary within a
    # CUMULATIVE 4×PSS ceiling (4 × PSS × periods elapsed this year,
    # regularised against YTD gross), full base above it (FR-016/§6). A
    # January high earner therefore gets the abatement on at most 4×PSS,
    # not on the whole remaining annual 4×PASS envelope.
    csg_gross_before = Decimal(str(ytd.get("csg_gross") or 0))
    periods_before = int(ytd.get("periods") or 0)
    cumulative_ceiling = pss_monthly * csg_abatement_multiple * Decimal(periods_before + 1)
    in_envelope = max(Decimal("0"), min(gross, cumulative_ceiling - csg_gross_before))
    above_envelope = max(Decimal("0"), gross - in_envelope)
    csg_base = _round2(in_envelope * csg_factor + above_envelope)

    csg_deductible = _round2(csg_base * _pct(_required(rate_map, "fr_csg_deductible", "employee", _FR_CSG_EE_DEDUCTIBLE, missing, ctx)))
    csg_nondeductible = _round2(csg_base * _pct(_required(rate_map, "fr_csg_nondeductible", "employee", _FR_CSG_EE_NONDEDUCTIBLE, missing, ctx)))
    crds = _round2(csg_base * _pct(_required(rate_map, "fr_crds", "employee", _FR_CRDS_EE, missing, ctx)))

    # ── Employer-only contributions ───────────────────────────────────
    # Health employer rate: logic unchanged pending G1 sign-off (the
    # reduced-rate predicate is a remuneration threshold under current law,
    # not a headcount band — flagged, not guessed).
    sante_er_rate = (
        _required(rate_map, "fr_sante_er", "employer", _FR_SANTE_ER_STANDARD, missing, ctx)
        if int(establishment.get("effectif") or 0) >= 11
        else _required(rate_map, "fr_sante_er_reduced", "employer", _FR_SANTE_ER_REDUCED, missing, ctx)
    )
    if int(establishment.get("effectif") or 0) < 11 and _FR_SANTE_REDUCED_2_5_SMIC_BAND:
        band_ceiling = rgdu_params["smic_annual"] / MONTHS_PER_YEAR * Decimal("2.5")
        low = min(gross, band_ceiling)
        high = max(Decimal("0"), gross - low)
        sante_er = _round2(
            low * _pct(sante_er_rate)
            + high * _pct(_required(rate_map, "fr_sante_er", "employer", _FR_SANTE_ER_STANDARD, missing, ctx))
        )
    else:
        sante_er = _round2(gross * _pct(sante_er_rate))

    famille_er = _round2(gross * _pct(_required(rate_map, "fr_famille_er", "employer", _FR_FAMILLE_ER, missing, ctx)))
    csa_er = _round2(gross * _pct(_required(rate_map, "fr_csa_er", "employer", _FR_CSA_ER_DEFAULT, missing, ctx)))

    chomage_er = _round2(chomage_base * _pct(_required(rate_map, "fr_chomage_er", "employer", _FR_CHOMAGE_ER, missing, ctx)))
    ags_er = _round2(chomage_base * _pct(_required(rate_map, "fr_ags_er", "employer", _FR_AGS_ER, missing, ctx)))

    fnal_rate = _FR_FNAL_ER_0P50 if fnal_class == "0p50" else _FR_FNAL_ER_0P10
    fnal_base = gross if fnal_class == "0p50" else vieillesse_capped_base
    fnal_er = _round2(fnal_base * _pct(_required(rate_map, f"fr_fnal_er_{fnal_class}", "employer", fnal_rate, missing, ctx)))

    # CFP (formation professionnelle) is due on total remuneration, not the
    # PSS-capped base.
    cfp_rate = _FR_CFP_ER_1P00 if cfp_class == "1p00" else _FR_CFP_ER_0P55
    cfp_base = gross
    cfp_er = _round2(cfp_base * _pct(_required(rate_map, f"fr_cfp_er_{cfp_class}", "employer", cfp_rate, missing, ctx)))

    appr_er = _round2(gross * _pct(_required(rate_map, "fr_apprentissage_er", "employer", _FR_APPRENTISSAGE_ER, missing, ctx)))
    appr_balance_er = _round2(gross * _pct(_required(rate_map, "fr_apprentissage_balance_er", "employer", _FR_APPRENTISSAGE_BALANCE_ER, missing, ctx)))

    atmp_rate_pct = Decimal(str(establishment.get("at_mp_rate_pct")))
    atmp_er = _round2(gross * atmp_rate_pct / Decimal("100"))

    vm_disclosures = []
    vm_er = Decimal("0")
    vm_rate_pct = establishment.get("vm_rate_pct")
    if vm_rate_pct not in (None, ""):
        vm_er = _round2(gross * Decimal(str(vm_rate_pct)) / Decimal("100"))
    elif establishment.get("vm_threshold_applies") is False:
        vm_disclosures.append("versement_mobilite: establishment below the 11-employee threshold; not due")
    else:
        # FR-027: unknown mandatory rate = NOT_READY, never a silent zero.
        # Only an explicit "threshold does not apply" (vm_threshold_applies
        # is False) makes a missing VM rate legitimately zero.
        missing.append("versement_mobilite (SIRET rate pack vm_rate_pct)")

    # ── NETS (FR-042: three separate values, never one "net") ──────────
    employee_ss_total = (
        vieillesse_capped_ee + vieillesse_uncapped_ee
        + agirc_t1_ee + agirc_t2_ee + ceg_t1_ee + ceg_t2_ee + cet_ee + apec_ee
        + csg_deductible + csg_nondeductible + crds
    )
    net_social = _round2(gross - employee_ss_total)
    # FR-017: both non-deductible levies — CSG non-déductible AND CRDS —
    # return to the taxable base.
    net_imposable = _round2(net_social + csg_nondeductible + crds)

    # ── Labor compliance (FR-044/FR-039) ───────────────────────────────
    effective_hours = working_hours if working_hours is not None else full_time_hours
    # Full-time: the published monthly SMIC (€1,867.02 from 1 Jun 2026) —
    # hourly × 151.67 rounds to a few cents above it. Part-time: hourly × hours.
    smic_minimum = (smic_monthly if effective_hours >= full_time_hours
                    else _round2(smic_hourly * effective_hours))
    if gross < smic_minimum:
        raise FranceCalculationBlockedError(
            "SMIC_MINIMUM_BREACH",
            f"France payroll block: period gross {gross} is below the applicable SMIC minimum "
            f"{smic_minimum} for {effective_hours}h in {pay_date.isoformat()} (FR-044).",
        )
    if ctx.france_idcc_minimum is not None and gross < Decimal(str(ctx.france_idcc_minimum)):
        raise FranceCalculationBlockedError(
            "IDCC_MINIMUM_BREACH",
            f"France payroll block: period gross {gross} is below the applicable IDCC "
            f"conventional minimum {ctx.france_idcc_minimum} for this classification (FR-039).",
        )

    if missing:
        raise FranceCalculationBlockedError(
            "MANDATORY_RATE_NOT_CONFIGURED",
            "France payroll block — mandatory 2026 content has no configured value in the active "
            "France pack (FR-027): " + ", ".join(sorted(missing)),
        )

    # ── PAS (authority rate, FR-008/FR-010) ─────────────────────────────
    pas_result = _compute_pas(ctx, net_imposable, net_social, pas_short_contract_abatement, pas_apprentice_threshold)
    pas_withheld = pas_result["withheld"]
    net_a_payer = _round2(net_social - pas_withheld)

    # ── Employer total + RGDU relief (FR-026) ──────────────────────────
    # RGDU scope: health, old-age, family, CSA, FNAL, unemployment and the
    # Agirc-Arrco T1 + CEG T1 employer contributions. Outside it: AGS, CFP,
    # apprenticeship tax, Agirc T2/CEG T2/CET/Apec, versement mobilité and
    # AT/MP (AT/MP's reducible share is content-pending — optional
    # fr_rgdu_atmp_reducible_pct row, capped at the establishment's rate).
    atmp_reducible_pct = (
        _optional(rate_map, "fr_rgdu_atmp_reducible_pct", "employer", Decimal("0"), ctx)
        if is_parameter_configured(rate_map, "fr_rgdu_atmp_reducible_pct", "employer") else Decimal("0")
    )
    atmp_reducible = _round2(gross * min(atmp_rate_pct, Decimal(str(atmp_reducible_pct))) / Decimal("100"))
    retraite_share = agirc_t1_er + ceg_t1_er
    rgdu_reducible = (
        vieillesse_capped_er + vieillesse_uncapped_er + sante_er + famille_er + csa_er
        + chomage_er + fnal_er + retraite_share + atmp_reducible
    )
    employer_total_before_relief = _round2(
        vieillesse_capped_er + vieillesse_uncapped_er + sante_er + famille_er + csa_er
        + chomage_er + ags_er + fnal_er + cfp_er + appr_er + appr_balance_er
        + agirc_t1_er + agirc_t2_er + ceg_t1_er + ceg_t2_er + cet_er + apec_er
        + atmp_er + vm_er
    )
    rgdu = _compute_rgdu(ctx, rgdu_params, fnal_class, rgdu_reducible, retraite_share)
    relief = rgdu["monthly_delta"]
    employer_after_relief = max(Decimal("0"), _round2(employer_total_before_relief - relief))

    # ── FR-040 contribution trace + FR-005 bases ──────────────────────
    contributions = [
        {"family": "vieillesse_capped", "code": "YG000", "base": vieillesse_capped_base, "ee": vieillesse_capped_ee, "er": vieillesse_capped_er},
        {"family": "vieillesse_uncapped", "code": "YH000", "base": vieillesse_uncapped_base, "ee": vieillesse_uncapped_ee, "er": vieillesse_uncapped_er},
        {"family": "sante", "code": "PB000", "base": gross, "ee": Decimal("0"), "er": sante_er},
        {"family": "famille", "code": "PA000", "base": gross, "ee": Decimal("0"), "er": famille_er},
        {"family": "csa", "code": "YALT", "base": gross, "ee": Decimal("0"), "er": csa_er},
        {"family": "chomage", "code": "AC1P", "base": chomage_base, "ee": Decimal("0"), "er": chomage_er},
        {"family": "ags", "code": "AGSP", "base": chomage_base, "ee": Decimal("0"), "er": ags_er},
        {"family": "fnal", "code": "FNAL", "base": fnal_base, "ee": Decimal("0"), "er": fnal_er},
        {"family": "cfp", "code": "CFP", "base": cfp_base, "ee": Decimal("0"), "er": cfp_er},
        {"family": "apprentissage", "code": "APP", "base": gross, "ee": Decimal("0"), "er": appr_er + appr_balance_er},
        {"family": "atmp", "code": "ATMP", "base": gross, "ee": Decimal("0"), "er": atmp_er},
        {"family": "versement_mobilite", "code": "VMRR", "base": gross, "ee": Decimal("0"), "er": vm_er},
        {"family": "agirc_t1", "code": "RE1B", "base": t1_base, "ee": agirc_t1_ee, "er": agirc_t1_er},
        {"family": "agirc_t2", "code": "RE2B", "base": t2_base, "ee": agirc_t2_ee, "er": agirc_t2_er},
        {"family": "ceg_t1", "code": "REFV", "base": t1_base, "ee": ceg_t1_ee, "er": ceg_t1_er},
        {"family": "ceg_t2", "code": "REGV", "base": t2_base, "ee": ceg_t2_ee, "er": ceg_t2_er},
        {"family": "cet", "code": "CET", "base": cet_base, "ee": cet_ee, "er": cet_er},
        {"family": "apec", "code": "APEC", "base": apec_base, "ee": apec_ee, "er": apec_er},
        {"family": "csg_deductible", "code": "CSGD", "base": csg_base, "ee": csg_deductible, "er": Decimal("0")},
        {"family": "csg_nondeductible", "code": "CSGN", "base": csg_base, "ee": csg_nondeductible, "er": Decimal("0")},
        {"family": "crds", "code": "CRDS", "base": csg_base, "ee": crds, "er": Decimal("0")},
    ]

    # YTD state after this period — persisted by the service after commit
    # so the next period's CSG ceiling and RGDU accumulate correctly.
    ytd_after = dict(rgdu.get("ytd_after") or {})
    ytd_after.update({
        "csg_gross": _round2(csg_gross_before + gross),
        "periods": periods_before + 1,
    })

    result.update({
        "fr_net_social": net_social,
        "fr_net_imposable": net_imposable,
        "fr_employee_total": _round2(employee_ss_total + pas_withheld),
        "fr_employer_total": employer_after_relief,
        "fr_employer_theoretical": employer_total_before_relief,
        "fr_contributions": contributions,
        # FR-005: independent statutory bases — every contribution is a rate
        # × ITS OWN base; no shared "gross" shorthand anywhere in the trace.
        "fr_bases": {
            "gross": _round2(gross),
            "vieillesse_capped": _round2(vieillesse_capped_base),
            "vieillesse_uncapped": _round2(vieillesse_uncapped_base),
            "chomage_ags_4x_pass": _round2(chomage_base),
            "agirc_t1": _round2(t1_base),
            "agirc_t2": _round2(t2_base),
            "cet": _round2(cet_base),
            "apec": _round2(apec_base),
            "csg_crds": _round2(csg_base),
            "fnal": _round2(fnal_base),
            "cfp": _round2(cfp_base),
            "pas": _round2(pas_result["pas_base"]),
            "net_social": net_social,
            "net_imposable": net_imposable,
            "net_a_payer": _round2(net_a_payer),
        },
        "fr_pas_withheld": pas_withheld,
        "fr_pas_rate_type": pas_result["rate_type"],
        "fr_pas_rate_pct": pas_result["rate_pct"],
        "fr_pas_rate_id": pas_result["rate_id"],
        "fr_ytd_after": ytd_after,
        "fr_calculation_snapshot": {
            "pay_date": pay_date.isoformat(),
            "employment": "REGULAR",
            "social_coverage": ctx.france_social_coverage,
            "siret": establishment.get("siret"),
            "effectif": establishment.get("effectif"),
            "fnal_class": fnal_class,
            "cfp_class": cfp_class,
            "smic_minimum": smic_hourly,
            "smic_monthly": smic_monthly,
            "pss_monthly": _round2(pss_monthly),
            "csg_base": csg_base,
            "csg_base_factor": _round2(csg_factor * 100),
            "net_a_payer": net_a_payer,
            "pas": pas_result,
            "rgdu": rgdu,
            "relief_granted_period": relief,
            "employer_before_relief": employer_total_before_relief,
            "disclosures": vm_disclosures,
        },
        "fr_rgdu": rgdu,
    })

    return result
