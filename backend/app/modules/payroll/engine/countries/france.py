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
   chomage/AGS (4×PASS, YTD-accumulated), CSG/CRDS (98.25% base up to
   4×PASS annual, then full base, deductible split preserved — FR-017),
   Agirc-Arrco T1/T2 + CEG + CET + Apec (monthly PSS tranches — FR-019),
   SIRET-scoped AT/MP and versement mobilité — FR-013, FNAL/CFP by
   governed effectif — FR-015.

3. Returns three separate nets (FR-042): net social, net imposable
   (returns non-deductible CSG to the taxable base — FR-017) and net à
   payer (net social − PAS). Pas customer-visible.

4. Computes the 2026 réduction générale dégressive unique (RGDU) as a
   year-to-date accumulator (FR-023) using the décret n° 2026-509 frozen
   1-January SMIC reference (FR-024), producing gross theoretical relief,
   Urssaf/Agirc-Arrco split, monthly delta and cumulative total (FR-026).

Rate values are DATA, resolved through `ctx.rate_map` with the published
2026 fallbacks in `hardcoded_defaults._FR_*`. This module never varies a
rate by hand: personalized PAS and SIRET establishment rates arrive
pre-resolved via `ctx.france_pas` / `ctx.france_establishment`, selected
by the same resolver that must NOT be per-tenant-editable (FR-008/FR-013).

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
    _FR_QUADRUPLE_PASS_ANNUAL,
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


def _pct(rate: Decimal) -> Decimal:
    # Coerce defensive exactly like germany.py's Decimal(u1_rate) call sites —
    # rate_map rows may surface str or Decimal depending on the caller.
    return Decimal(str(rate)) / Decimal("100")


# ── PAS ────────────────────────────────────────────────────────────────

def _compute_pas(ctx: PayrollContext, net_imposable: Decimal, net_social: Decimal) -> dict:
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
        abatement = min(_FR_PAS_SHORT_CONTRACT_ABATEMENT, pas_base)
        pas_base = pas_base - abatement

    withheld = Decimal("0")
    exempt = False
    # Apprentice/trainee exemption threshold (spec §4): only when the
    # resolver confirmed eligibility AND the annualised remuneration stays
    # under the legal threshold.
    if pas.get("apprentice") and net_social * MONTHS_PER_YEAR <= _FR_PAS_APPRENTICE_THRESHOLD:
        exempt = True
        withheld = Decimal("0")
    else:
        withheld = _round2(rate * pas_base / Decimal("100"))
        withheld = max(Decimal("0"), min(withheld, net_social))

    return {
        "rate_type": rate_type,
        "rate_pct": rate,
        "rate_id": pas.get("rate_id") or None,
        "grid_version": pas.get("grid_version") or None,
        "apprentice_exempt": exempt,
        "pas_base": _round2(pas_base),
        "pas_base_gross": _round2(net_imposable),
        "short_contract_abatement": _round2(abatement),
        "withheld": withheld,
    }


# ── RGDU (2026 réduction générale dégressive unique, FR-023/FR-026) ────

def _rgdu_coefficient(remuneration_ytd: Decimal, smic_reference_ytd: Decimal, tdelta: Decimal) -> Decimal:
    if remuneration_ytd <= Decimal("0"):
        return Decimal("0")
    bracket = (Decimal("0.5")) * (Decimal("3") * smic_reference_ytd / remuneration_ytd - Decimal("1"))
    if bracket <= Decimal("0"):
        return Decimal("0")  # at/above 3×SMIC → out of the eligibility envelope
    coefficient = _FR_RGDU_TMIN + tdelta * (min(bracket, Decimal("1")) ** _FR_RGDU_POWER)
    return min(coefficient, _FR_RGDU_TMIN + tdelta)


def _compute_rgdu(ctx: PayrollContext, employer_reducible: Decimal, employer_atmp_vm: Decimal, retraite_share: Decimal) -> dict:
    """RGDU as a YTD accumulator (FR-023). `employer_reducible` is the sum
    of employer contributions actually eligible for the reduction (used to
    cap relief at theoretical contributions), `employer_atmp_vm` the
    excluded lines (AT/MP, versement mobilité) — reported but never
    reduced (FR-026), and `retraite_share` the Agirc-Arrco/CEG/CET/Apec
    employer portion so the Urssaf/Agirc-Arrco relief split is weighted on
    the reducible contributions only."""
    establishment = ctx.france_establishment or {}
    fnal_0p50 = str(establishment.get("fnal_class", "")) == "0p50"
    tdelta = _FR_RGDU_TDELTA_FNAL_0P50 if fnal_0p50 else _FR_RGDU_TDELTA_FNAL_0P10

    ytd = ctx.france_ytd or {}
    remuneration_before = Decimal(str(ytd.get("rgdu_remuneration") or 0))
    smic_reference_before = Decimal(str(ytd.get("rgdu_smic_reference") or 0))
    relief_granted_before = Decimal(str(ytd.get("rgdu_relief") or 0))

    working_hours = getattr(ctx, "france_working_hours", None)
    overtime_hours = getattr(ctx, "france_overtime_hours", None) or Decimal("0")

    remuneration_ytd = remuneration_before + ctx.gross
    smic_reference_period = (
        _FR_SMIC_2026_ANNUAL_FROZEN * _hours_ratio(working_hours)
        + _FR_SMIC_2026_HOURLY_FROZEN * Decimal(str(overtime_hours))
    )
    smic_reference_ytd = smic_reference_before + smic_reference_period

    if remuneration_ytd >= _FR_RGDU_ELIGIBILITY_MULTIPLE * smic_reference_ytd:
        return {
            "eligible": False, "reason": "remuneration_at_or_above_3x_smic",
            "annual_remuneration": _round2(remuneration_ytd),
            "annual_smic_reference": _round2(smic_reference_ytd),
            "coefficient": Decimal("0"), "theoretical_relief": Decimal("0"),
            "already_granted": _round2(relief_granted_before),
            "monthly_delta": Decimal("0"),
            "relief_urssaf": Decimal("0"), "relief_agirc": Decimal("0"),
            "tdelta": tdelta, "fnal_class": establishment.get("fnal_class"),
        }

    coefficient = _rgdu_coefficient(remuneration_ytd, smic_reference_ytd, tdelta)
    theoretical_ytd = _round2(coefficient * remuneration_ytd)
    theoretical_ytd = min(theoretical_ytd, employer_reducible)  # relief never exceeds reducible contributions
    monthly_delta = max(Decimal("0"), theoretical_ytd - relief_granted_before)

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
        "fnal_class": establishment.get("fnal_class"),
        "theoretical_relief": _round2(theoretical_ytd),
        "already_granted": _round2(relief_granted_before),
        "monthly_delta": _round2(monthly_delta),
        "relief_urssaf": _round2(relief_urssaf),
        "relief_agirc": _round2(relief_agirc),
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
    missing_est = [
        k for k in ("siret", "at_mp_rate_pct")
        if establishment.get(k) in (None, "")
    ]
    if establishment.get("fnal_class") not in ("0p10", "0p50"):
        missing_est.append("fnal_class")
    if establishment.get("cfp_class") not in ("0p55", "1p00"):
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
    org_id = getattr(ctx, "france_organization_id", None)

    # ── Ceiling inputs (content) ──────────────────────────────────────
    pss_monthly = _FR_PASS_MONTHLY * _hours_ratio(getattr(ctx, "france_working_hours", None))
    four_pass_monthly = _FR_QUADRUPLE_PASS_ANNUAL / MONTHS_PER_YEAR * _hours_ratio(getattr(ctx, "france_working_hours", None))
    gross = ctx.gross

    # cumulées-4-PASS annual-envelope state (chomage/AGS/CSG boundary)
    ytd = ctx.france_ytd or {}
    pass_used_before = Decimal(str(ytd.get("pass_used") or 0))
    eligible_4pass_before = max(Decimal("0"), _FR_QUADRUPLE_PASS_ANNUAL - pass_used_before)

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
    t2_base = min(max(gross - pss_monthly, Decimal("0")), _FR_PASS_MONTHLY * Decimal("8") - pss_monthly)
    cet_base = (gross if gross > pss_monthly else Decimal("0"))  # CET only when remuneration exceeds T1 (FR-021)
    apec_base = (min(gross, _FR_PASS_MONTHLY * Decimal("4")) if ctx.france_cadre else Decimal("0"))

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

    # CSG/CRDS — 98.25% factor on qualifying salary up to the 4×PASS
    # annual envelope, full base above (FR-016 base builder; launch = all
    # qualifying). Deductible split preserved (FR-017).
    csg_factor = _FR_CSG_BASE_FACTOR_98_25 / Decimal("100")
    in_envelope = min(gross, eligible_4pass_before)
    above_envelope = max(Decimal("0"), gross - in_envelope)
    csg_base = _round2(in_envelope * csg_factor + above_envelope)

    csg_deductible = _round2(csg_base * _pct(_required(rate_map, "fr_csg_deductible", "employee", _FR_CSG_EE_DEDUCTIBLE, missing, ctx)))
    csg_nondeductible = _round2(csg_base * _pct(_required(rate_map, "fr_csg_nondeductible", "employee", _FR_CSG_EE_NONDEDUCTIBLE, missing, ctx)))
    crds = _round2(csg_base * _pct(_required(rate_map, "fr_crds", "employee", _FR_CRDS_EE, missing, ctx)))

    # ── Employer-only contributions ───────────────────────────────────
    sante_er_rate = (
        _required(rate_map, "fr_sante_er", "employer", _FR_SANTE_ER_STANDARD, missing, ctx)
        if int(establishment.get("effectif") or 0) >= 11
        else _required(rate_map, "fr_sante_er_reduced", "employer", _FR_SANTE_ER_REDUCED, missing, ctx)
    )
    if int(establishment.get("effectif") or 0) < 11 and _FR_SANTE_REDUCED_2_5_SMIC_BAND:
        band_ceiling = _FR_SMIC_2026_ANNUAL_FROZEN / MONTHS_PER_YEAR * Decimal("2.5")
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

    fnal_rate = _FR_FNAL_ER_0P50 if establishment.get("fnal_class") == "0p50" else _FR_FNAL_ER_0P10
    fnal_base = gross if establishment.get("fnal_class") == "0p50" else vieillesse_capped_base
    fnal_er = _round2(fnal_base * _pct(_required(rate_map, f"fr_fnal_er_{establishment.get('fnal_class')}", "employer", fnal_rate, missing, ctx)))

    cfp_rate = _FR_CFP_ER_1P00 if establishment.get("cfp_class") == "1p00" else _FR_CFP_ER_0P55
    cfp_er = _round2(vieillesse_capped_base * _pct(_required(rate_map, f"fr_cfp_er_{establishment.get('cfp_class')}", "employer", cfp_rate, missing, ctx)))

    appr_er = _round2(gross * _pct(_required(rate_map, "fr_apprentissage_er", "employer", _FR_APPRENTISSAGE_ER, missing, ctx)))
    appr_balance_er = _round2(gross * _pct(_required(rate_map, "fr_apprentissage_balance_er", "employer", _FR_APPRENTISSAGE_BALANCE_ER, missing, ctx)))

    atmp_er = _round2(gross * Decimal(str(establishment.get("at_mp_rate_pct"))) / Decimal("100"))

    vm_disclosures = []
    vm_er = Decimal("0")
    vm_rate_pct = establishment.get("vm_rate_pct")
    if vm_rate_pct not in (None, ""):
        vm_er = _round2(gross * Decimal(str(vm_rate_pct)) / Decimal("100"))
    else:
        vm_disclosures.append("versement_mobilite: no rate for SIRET; liability unresolved for this period")

    # ── NETS (FR-042: three separate values, never one "net") ──────────
    employee_ss_total = (
        vieillesse_capped_ee + vieillesse_uncapped_ee
        + agirc_t1_ee + agirc_t2_ee + ceg_t1_ee + ceg_t2_ee + cet_ee + apec_ee
        + csg_deductible + csg_nondeductible + crds
    )
    net_social = _round2(gross - employee_ss_total)
    net_imposable = _round2(net_social + csg_nondeductible)  # non-deductible CSG returns to taxable base (FR-017)

    # ── Labor compliance (FR-044/FR-039) ───────────────────────────────
    working_hours = ctx.france_working_hours
    effective_hours = working_hours if working_hours is not None else _FULL_TIME_HOURS
    smic_minimum = _round2(_smic_hourly(pay_date) * effective_hours)
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

    # ── PAS (authority rate, FR-008/FR-010) ─────────────────────────────
    pas_result = _compute_pas(ctx, net_imposable, net_social)
    pas_withheld = pas_result["withheld"]
    net_a_payer = _round2(net_social - pas_withheld)

    # ── Employer total + RGDU relief (FR-026) ──────────────────────────
    employer_reducible = (
        vieillesse_capped_er + vieillesse_uncapped_er + sante_er + famille_er + csa_er
        + chomage_er + ags_er + fnal_er + cfp_er + appr_er + appr_balance_er
        + agirc_t1_er + agirc_t2_er + ceg_t1_er + ceg_t2_er + cet_er + apec_er
    )
    retraite_share = agirc_t1_er + agirc_t2_er + ceg_t1_er + ceg_t2_er + cet_er + apec_er
    employer_atmp_vm = atmp_er + vm_er
    rgdu = _compute_rgdu(ctx, employer_reducible, employer_atmp_vm, retraite_share)
    relief = rgdu["monthly_delta"]
    employer_after_relief = max(Decimal("0"), _round2(employer_reducible + employer_atmp_vm - relief))

    if missing:
        raise FranceCalculationBlockedError(
            "MANDATORY_RATE_NOT_CONFIGURED",
            "France payroll block — mandatory 2026 contribution rate(s) have no configured "
            "rate_map row and no published default (FR-027): " + ", ".join(sorted(missing)),
        )

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
        {"family": "cfp", "code": "CFP", "base": vieillesse_capped_base, "ee": Decimal("0"), "er": cfp_er},
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

    result.update({
        "fr_net_social": net_social,
        "fr_net_imposable": net_imposable,
        "fr_employee_total": _round2(employee_ss_total + pas_withheld),
        "fr_employer_total": employer_after_relief,
        "fr_employer_theoretical": _round2(employer_reducible + employer_atmp_vm),
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
            "cfp": _round2(vieillesse_capped_base),
            "pas": _round2(pas_result["pas_base"]),
            "net_social": net_social,
            "net_imposable": net_imposable,
            "net_a_payer": _round2(net_a_payer),
        },
        "fr_pas_withheld": pas_withheld,
        "fr_pas_rate_type": pas_result["rate_type"],
        "fr_pas_rate_pct": pas_result["rate_pct"],
        "fr_pas_rate_id": pas_result["rate_id"],
        "fr_calculation_snapshot": {
            "pay_date": pay_date.isoformat(),
            "employment": "REGULAR",
            "social_coverage": ctx.france_social_coverage,
            "siret": establishment.get("siret"),
            "effectif": establishment.get("effectif"),
            "smic_minimum": _smic_hourly(pay_date),
            "smic_monthly": _smic_monthly(pay_date),
            "pss_monthly": _round2(pss_monthly),
            "csg_base": csg_base,
            "csg_base_factor": _FR_CSG_BASE_FACTOR_98_25,
            "net_a_payer": net_a_payer,
            "rgdu": rgdu,
            "relief_granted_period": relief,
            "employer_before_relief": _round2(employer_reducible + employer_atmp_vm),
            "disclosures": vm_disclosures,
        },
        "fr_rgdu": rgdu,
    })

    return result