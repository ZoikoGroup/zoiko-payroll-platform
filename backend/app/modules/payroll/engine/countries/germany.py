"""
modules/payroll/engine/countries/germany.py
-----------------------------------------------
Germany production calculation path (Phase 7, ZP-TAX-DE-2026-001).

`calculate(ctx)` is the ONE authoritative Germany production entry point
(`engine/standard.py`'s `_COUNTRY_CALC["DE"]` and, through it,
`EnterpriseStrategy` too) — there is no silent second path. It:

1. Requires an effective EmployeeStatutoryProfile (Phase 2) for the
   employee/payroll date — raises GermanyStatutoryProfileMissingError if
   none exists.
2. Computes RV (pension), ALV (unemployment), GKV (health), and PV
   (long-term care) as four independently-capped branches, each reading
   its own registry (GermanyContributionCeiling branch=GKV_PV/RV_ALV —
   Phase 5, GermanyHealthFund — Phase 4, GermanyPvConfiguration —
   Phase 6) — never one collapsed bucket. These are real, spec-cited 2026
   rate calculations (ZP-TAX-DE-2026-001 §9/§10), not PAP output, per the
   spec's own scoping of what PAP governs vs. what it doesn't.
2a. Computes the employer insolvency levy (U3, spec §14 — a flat federal
    rate applying to every Germany employment classification, unlike
    U1/U2 which remain genuinely fund/tariff-specific and are disclosed
    NOT_CONFIGURED for REGULAR/MIDIJOB, same as accident insurance) for
    REGULAR and MIDIJOB too (Phase 8I already had this for Minijob only —
    see this phase's (8M) gap-closure audit). Also emits a non-blocking
    trace warning (never a hard reject — not specified as one) when an
    employee is recorded PRIVATE health insurance below the JAEG
    compulsory-insurance threshold (spec §9, acceptance criterion #20).
3. Attempts Lohnsteuer/Soli/Kirchensteuer via the official BMF PAP (Phase
   3's PapAlgorithmAsset registry + germany_pap/core.py's executor
   interface) first. Because no certified PAP source exists anywhere in
   this repository (confirmed at the start of Phase 7, re-confirmed by
   Phase 8BR — see docs/GERMANY_PAP_8_GATE_EVIDENCE_MATRIX.md), that
   attempt deterministically raises GermanyPapNotAvailableError — this
   remains the correct, intended behavior for the OFFICIAL path (the
   "Absolute PAP Rule": never fabricate a result claiming to be BMF
   output). Phase 8BR (docs/PHASE_8BR_GERMANY_FUNCTIONAL_PAYROLL_COMPLETION_REPORT.md)
   catches that specific exception and falls back to a clearly-separate
   INTERNAL functional wage-tax calculator (germany_internal_tax.py,
   real section 32a/39b EStG statutory formulas, never presented as
   BMF-certified) so Regular/Midijob payroll is not permanently blocked
   while the certified artifact remains unavailable/unlicensed.

Every raised error carries a GermanyCalculationTrace (germany_pap/core.py)
showing exactly which branches DID resolve before the block, for
diagnosis — see service.py's germany calculation call sites and the
`POST /api/payroll/germany/calculation-preview` diagnostic endpoint.

Phase 4 (docs/PHASE_4_GERMANY_LEGACY_PAP_ARCHITECTURE_DECISION_REPORT.md):
the ORIGINAL pre-Phase-7 calculator (`_calculate_legacy_simplified()` —
collapsed pension+social-insurance bucket, flat-rate church tax off the
legacy PayrollEmployee.church_tax_liable column, generic bracket-table
Lohnsteuer via `_calculate_annual_tax_de()`) was retired after a forensic
audit confirmed zero production/API/migration callers, zero historical
payroll data computed via this path (Germany has never had a real
production employee), and that its own regression test asserted nothing
about calculation correctness — only that the function remained
importable. Its functionality is fully superseded by `calculate()`
below (four independently-capped RV/ALV/GKV/PV branches, the per-Land
CHURCH_TAX_LAND_RATES registry, and the PAP/internal-tariff wage-tax
path), which is strictly more statutorily complete. See that report for
the full evidence trail.
"""

from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import MONTHS_PER_YEAR
from app.modules.payroll.engine.jurisdictions.germany.pap.core import (
    GermanyCalculationError,
    GermanyCalculationTrace,
    GermanyMidijobBaseApplicationNotSpecifiedError,
    GermanyPapNotAvailableError,
    GermanyStatutoryProfileMissingError,
    build_pap_input,
    trace_tax_data_used,
    calculate_alv,
    calculate_employer_insolvency_levy,
    calculate_gkv,
    calculate_midijob_branch_contribution,
    calculate_midijob_employee_base,
    calculate_midijob_gkv,
    calculate_midijob_pv,
    calculate_midijob_total_base,
    calculate_minijob,
    calculate_pv,
    calculate_rv,
    check_gkv_coverage_threshold,
    check_main_secondary_employment_consistency,
    resolve_church_tax_rate,
    resolve_employment_classification,
    resolve_pap_executor,
    resolve_pv_child_category,
    two_sided_rate,
    validate_employment_classification_against_earnings,
    validate_employment_classification_against_vocational_training,
)
from app.modules.payroll.engine.jurisdictions.germany.tax import (
    GermanyInternalTariffNotAvailableError,
    InternalGermanyWageTaxCalculator,
)
# Fallback constants moved to hardcoded_defaults.py — imported back under
# their original names so nothing else needs to change.
from app.modules.payroll.hardcoded_defaults import (
    _DE_SOLI_THRESHOLD, _DE_SOLI_RATE,
    _DE_RV_EMPLOYEE_RATE, _DE_RV_EMPLOYER_RATE,
    _DE_ALV_EMPLOYEE_RATE, _DE_ALV_EMPLOYER_RATE,
    _DE_GKV_GENERAL_EMPLOYEE_RATE, _DE_GKV_GENERAL_EMPLOYER_RATE,
    _DE_MINIJOB_UPPER_THRESHOLD, _DE_MIDIJOB_UPPER_THRESHOLD,
    _DE_MINIJOB_EMPLOYER_HEALTH_RATE, _DE_MINIJOB_EMPLOYER_PENSION_RATE,
    _DE_MINIJOB_U1_RATE, _DE_MINIJOB_U2_RATE, _DE_MINIJOB_U3_RATE,
    _DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE, _DE_MINIJOB_FLAT_TAX_RATE,
    _DE_MIDIJOB_TOTAL_BASE_MULTIPLIER, _DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
    _DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER, _DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
    _DE_PV_CHILDLESS_SURCHARGE_RATE,
    _DE_INSOLVENCY_LEVY_RATE, _DE_JAEG_ANNUAL_THRESHOLD,
)


def _trace_ceiling(trace, branch: str, ceiling) -> None:
    """Capture the actual ceiling VALUES (not just the row id) onto the
    calculation trace so a finalized Germany payslip's statutory context is
    reproducible even if the registry row is later superseded — Phase 8E §24.
    Values are stored as strings (JSON-safe), matching the trace's convention."""
    if ceiling is None:
        return
    try:
        monthly = str(getattr(ceiling, "monthly_ceiling", None))
        annual = str(getattr(ceiling, "annual_ceiling", None))
    except Exception:
        return
    if branch == "gkv_pv":
        trace.ceiling_gkv_pv_monthly = monthly
        trace.ceiling_gkv_pv_annual = annual
    else:
        trace.ceiling_rv_alv_monthly = monthly
        trace.ceiling_rv_alv_annual = annual


def _trace_pv_config(trace, pv_configuration) -> None:
    """Capture the actual PV rate VALUES (not just the row id) onto the
    calculation trace for reproduction — Phase 8E §24. JSON-safe strings."""
    if pv_configuration is None:
        return
    try:
        trace.pv_configuration_effective_from = str(getattr(pv_configuration, "effective_from", None))
        trace.pv_configuration_total_rate_pct = str(getattr(pv_configuration, "total_rate_pct", None))
        trace.pv_configuration_standard_employee_rate_pct = str(
            getattr(pv_configuration, "standard_employee_rate_pct", None)
        )
        trace.pv_configuration_employer_rate_pct = str(getattr(pv_configuration, "employer_rate_pct", None))
        trace.pv_configuration_saxony_employee_rate_pct = str(
            getattr(pv_configuration, "saxony_employee_rate_pct", None)
        )
        trace.pv_configuration_saxony_employer_rate_pct = str(
            getattr(pv_configuration, "saxony_employer_rate_pct", None)
        )
    except Exception:
        return


def _trace_earning_taxability(trace, ctx) -> None:
    """Capture the four-dimension earning taxability classification (spec
    §15) for each earning type that actually entered this calculation onto
    the trace — the same rows that were resolved for this employee on this
    payroll date (via PayrollContext.germany_earning_taxability). Absent /
    unpublished rules surface as NOT_CONFIGURED; the engine never invents a
    classification or gates rate math on one. JSON-safe strings."""
    mapping = getattr(ctx, "germany_earning_taxability", None) or {}
    sonstb = getattr(ctx, "germany_sonstb", None)
    present_types = ["REGULAR_SALARY"]
    if sonstb:
        present_types.append("BONUS_ANNUAL_BONUS")
    classifications = {}
    for earning_type in present_types:
        rule = mapping.get(earning_type)
        if rule is None:
            classifications[earning_type] = {
                "status": "NOT_CONFIGURED",
                "explanation": "no PUBLISHED GermanyEarningTaxabilityRule for this earning type as of this payroll date",
            }
            continue
        classifications[earning_type] = {
            "status": "CONFIGURED",
            "recordId": getattr(rule, "id", None),
            "effectiveFrom": str(getattr(rule, "effective_from", None)),
            "wageTaxTreatment": getattr(rule, "wage_tax_treatment", None),
            "gkvPvTreatment": getattr(rule, "gkv_pv_treatment", None),
            "rvAlvTreatment": getattr(rule, "rv_alv_treatment", None),
            "reportingClassification": getattr(rule, "reporting_classification", None),
            "authoritySourceId": getattr(rule, "authority_source_id", None),
        }
    status_summary = "; ".join(
        f"{et}={cls['status']}"
        for et, cls in (classifications.items() if classifications else [("(no earning data)", "NOT_CONFIGURED")])
    )
    trace.earning_taxability_status = status_summary
    trace.earning_taxability_detail = classifications if classifications else {"no_earning_data": {"status": "NOT_CONFIGURED"}}
    for earning_type, cls in classifications.items():
        if cls.get("status") == "CONFIGURED":
            trace.step(
                f"Earning taxability ({earning_type}): wageTax={cls['wageTaxTreatment']}, "
                f"gkvPv={cls['gkvPvTreatment']}, rvAlv={cls['rvAlvTreatment']}, "
                f"reporting={cls['reportingClassification']} (rule #{cls['recordId']}, eff. {cls['effectiveFrom']})."
            )
        else:
            trace.step(
                f"Earning taxability ({earning_type}): {cls['explanation']}."
            )


def _resolve_minijob_midijob_value(parameters: dict, parameter_code: str, default: Decimal) -> Decimal:
    """Phase 8BK: same 'resolve from the effective-dated registry, fall
    back to the hardcoded default' pattern as two_sided_rate
    (germany_pap/core.py) — see
    service.resolve_all_minijob_midijob_parameters for how `parameters`
    (ctx.germany_minijob_midijob_parameters) is populated. A single
    scalar (not an employee/employer pair): every Minijob/Midijob
    parameter this registry covers is one-sided — a flat rate, a
    threshold, or one formula coefficient — never a two-sided
    employee/employer split the way RV/ALV/GKV are.

    `parameters` is None/empty for every calculation before this phase's
    wiring existed and for any test/context that hasn't threaded it
    through — in both cases this returns `default` unconditionally, so
    behavior is byte-identical to before this phase for every org that
    hasn't published a Minijob/Midijob parameter record (i.e. every real
    org today)."""
    row = (parameters or {}).get(parameter_code)
    if row is not None and row.value is not None:
        return Decimal(row.value)
    return default


def _resolve_church_tax_land_rate(parameters: dict, church_tax_land: Optional[str]) -> Decimal:
    """Phase 8BL: registry-first, hardcoded-fallback resolution for the
    general 16-Land Kirchensteuer rate (CHURCH_TAX_LAND_RATES), same
    pattern as _resolve_minijob_midijob_value above. `church_tax_land`
    still goes through resolve_church_tax_rate's own validation on the
    fallback path — an unrecognized/missing Land code is never silently
    treated as 0% just because no registry override exists; it still
    raises GermanyStatutoryProfileMissingError exactly as before this
    phase."""
    if church_tax_land:
        parameter_code = f"church_tax_rate_{church_tax_land.lower().replace('-', '_')}"
        row = (parameters or {}).get(parameter_code)
        if row is not None and row.value is not None:
            return Decimal(row.value)
    return resolve_church_tax_rate(church_tax_land)


def _calculate_minijob_path(ctx: PayrollContext, profile, trace: GermanyCalculationTrace, _block) -> dict:
    """Phase 8I — Minijob (monthly gross <= EUR 603.00). Entirely
    independent of the BMF PAP: the flat 2% Pauschsteuer is the tax
    treatment (§16 of the phase brief; the ordinary Lohnsteuer/PAP path is
    never reached for a Minijob employee), so this path can reach a real
    COMPLETE calculation_status today even though PAP itself remains
    externally blocked — see the module/phase report for why this is
    correct, not an accidental bypass of the PAP gate (Minijob never
    calls resolve_pap_executor() at all)."""
    monthly_gross = ctx.gross
    trace.monthly_gross_used = str(monthly_gross)
    pension_exempt = bool(getattr(profile, "de_pension_insurance_exempt", False))
    de_parameters = getattr(ctx, "germany_minijob_midijob_parameters", None)

    result = calculate_minijob(
        monthly_gross=monthly_gross, pension_insurance_exempt=pension_exempt,
        employer_health_rate=_resolve_minijob_midijob_value(
            de_parameters, "minijob_employer_health_rate", _DE_MINIJOB_EMPLOYER_HEALTH_RATE,
        ),
        employer_pension_rate=_resolve_minijob_midijob_value(
            de_parameters, "minijob_employer_pension_rate", _DE_MINIJOB_EMPLOYER_PENSION_RATE,
        ),
        u1_rate=_resolve_minijob_midijob_value(de_parameters, "minijob_u1_rate", _DE_MINIJOB_U1_RATE),
        u2_rate=_resolve_minijob_midijob_value(de_parameters, "minijob_u2_rate", _DE_MINIJOB_U2_RATE),
        u3_rate=_resolve_minijob_midijob_value(de_parameters, "minijob_u3_rate", _DE_MINIJOB_U3_RATE),
        employee_pension_topup_rate=_resolve_minijob_midijob_value(
            de_parameters, "minijob_employee_pension_topup_rate", _DE_MINIJOB_EMPLOYEE_PENSION_TOPUP_RATE,
        ),
        flat_tax_rate=_resolve_minijob_midijob_value(
            de_parameters, "minijob_flat_tax_rate", _DE_MINIJOB_FLAT_TAX_RATE,
        ),
        # Accident insurance is never computed as a monthly deduction from
        # this call regardless of whether an EmployerTaxProfile exists —
        # see the trace block below for why (same reasoning as the
        # Regular/Midijob paths, Phase 8AJ).
        accident_insurance_rate_pct=None,
    )
    # Phase 8AJ: a Minijob employee is still covered by the employer's
    # statutory accident insurance — this was previously never checked
    # here (unlike the Regular/Midijob paths, which already read
    # ctx.employer_tax_profiles), silently hiding a configured employer
    # profile from the trace for Minijob employees specifically. Fixed
    # for consistency; no monthly amount is computed here either, for
    # the same reason as Regular/Midijob: German accident insurance is
    # assessed ANNUALLY by the Berufsgenossenschaft against reported wage
    # totals, never withheld per pay period.
    accident_profile = (ctx.employer_tax_profiles or {}).get("DE_ACCIDENT_INSURANCE") if getattr(ctx, "employer_tax_profiles", None) else None
    trace.accident_insurance_status = (
        "CONFIGURED — employer profile on file (annual Berufsgenossenschaft assessment, no monthly deduction computed)"
        if accident_profile else "NOT_CONFIGURED — carrier-specific rate not available"
    )
    trace.resolve_ok(
        "minijob_employer",
        health=result.employer_health, pension=result.employer_pension,
        u1=result.employer_u1, u2=result.employer_u2, u3=result.employer_u3,
        accident_insurance=(
            f"CONFIGURED (rate on file, annual assessment — {accident_profile.employer_rate_pct}%)"
            if accident_profile else "NOT_CONFIGURED"
        ),
    )
    trace.resolve_ok("minijob_employee", pension_topup=result.employee_pension_topup)
    trace.resolve_ok("minijob_tax", flat_tax_employer_remitted=result.flat_tax)
    trace.step("Computed Minijob employer flat contributions (health/pension/U1/U2/U3).")
    trace.step(
        "Computed Minijob employee pension top-up "
        + ("(SKIPPED — employee pension-insurance exempt)." if pension_exempt else "(rate per hardcoded_defaults.py).")
    )
    trace.step("Computed Minijob flat tax (employer-remitted Pauschsteuer — not an employee deduction; rate per hardcoded_defaults.py).")
    # No church-tax treatment for the Minijob flat tax is specified in the
    # supplied documentation (phase brief §17) — not invented.
    trace.step("Church tax: NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION for the Minijob flat-tax treatment.")

    trace.calculation_status = "COMPLETE"
    return dict(
        employee_pf=result.employee_pension_topup,
        employer_pf=result.employer_pension,
        employee_esi=Decimal("0"),
        employer_esi=result.employer_health + result.employer_u1 + result.employer_u2 + result.employer_u3,
        church_tax=Decimal("0"),
        # Minijob flat tax is employer-remitted Pauschsteuer — there is no
        # employee Solidaritätszuschlag on the Minijob path (zero, never
        # fabricated). Persisted via PayrollResult.soli/PayslipItem.soli.
        soli=Decimal("0"),
        tds=Decimal("0"),
        annual_tax=result.flat_tax * MONTHS_PER_YEAR,
        _germany_statutory_profile_id=trace.statutory_profile_id,
        _germany_calculation_snapshot=trace.to_dict(),
    )


def _calculate_midijob_path(ctx: PayrollContext, profile, trace: GermanyCalculationTrace, _block) -> dict:
    """Phase 8J — Midijob (603.01 <= monthly gross <= 2,000.00). RV/ALV/
    GKV/PV branch-level contributions are now computed using the official
    3-step Übergangsbereich mechanism (§20 Abs. 2a SGB IV / §2 Abs. 2 BVV,
    per the joint GKV-Spitzenverband/DRV-Bund/BA circular of 20.12.2022,
    §4.3.3.1 — see calculate_midijob_branch_contribution's own docstring
    for the full citation and Phase 8J's report for the fetched evidence).
    This resolves the gap Phase 8I explicitly, deliberately left open.

    Wage tax (Lohnsteuer/Soli/Kirchensteuer): tries the official BMF PAP
    first, exactly like REGULAR; since no certified PAP asset/executor
    exists in this codebase (unchanged fact), falls back to the internal
    functional wage-tax calculator (germany_internal_tax.py, Phase 8BR) so
    a Midijob employee can reach a COMPLETE calculation and a real
    payslip, clearly labeled INTERNAL_FUNCTIONAL_REFERENCE rather than
    BMF-certified."""
    monthly_gross = ctx.gross
    trace.monthly_gross_used = str(monthly_gross)
    de_parameters = getattr(ctx, "germany_minijob_midijob_parameters", None)

    total_base = calculate_midijob_total_base(
        monthly_gross,
        multiplier=_resolve_minijob_midijob_value(
            de_parameters, "midijob_total_base_multiplier", _DE_MIDIJOB_TOTAL_BASE_MULTIPLIER,
        ),
        subtrahend=_resolve_minijob_midijob_value(
            de_parameters, "midijob_total_base_subtrahend", _DE_MIDIJOB_TOTAL_BASE_SUBTRAHEND,
        ),
    )
    employee_base = calculate_midijob_employee_base(
        monthly_gross,
        multiplier=_resolve_minijob_midijob_value(
            de_parameters, "midijob_employee_base_multiplier", _DE_MIDIJOB_EMPLOYEE_BASE_MULTIPLIER,
        ),
        subtrahend=_resolve_minijob_midijob_value(
            de_parameters, "midijob_employee_base_subtrahend", _DE_MIDIJOB_EMPLOYEE_BASE_SUBTRAHEND,
        ),
    )
    trace.midijob_total_contribution_base = str(total_base)
    trace.midijob_employee_contribution_base = str(employee_base)
    trace.step(f"Computed Midijob total contribution base: {total_base}")
    trace.step(f"Computed Midijob employee contribution base: {employee_base}")

    # ── RV (Rentenversicherung) ──
    # Phase 8BJ: resolves through the SAME rate_map (canonical-tax-pack-
    # aware, effective-dated when an org has opted in — see
    # engine/tax_resolver.py) the REGULAR path's calculate_rv() already
    # uses, via the identical "rv_pension" component key — the statutory
    # rate itself doesn't change based on employment classification, so
    # REGULAR and MIDIJOB must never be able to disagree on it. Falls
    # back to the identical hardcoded 2026 constants when no canonical
    # override resolves, so behavior is byte-identical to before this
    # phase for every org that hasn't opted into a canonical tax pack.
    if bool(getattr(profile, "de_pension_insurance_exempt", False)):
        rv_total = rv_employee = rv_employer = Decimal("0")
        trace.step("Midijob RV skipped — employee pension-insurance exempt.")
    else:
        rv_employee_pct, rv_employer_pct = two_sided_rate(
            ctx.rate_map, "rv_pension", _DE_RV_EMPLOYEE_RATE, _DE_RV_EMPLOYER_RATE,
        )
        rv_combined = rv_employee_pct + rv_employer_pct
        rv_total, rv_employee, rv_employer = calculate_midijob_branch_contribution(
            total_base, employee_base, combined_rate_pct=rv_combined, employee_rate_pct=rv_employee_pct,
        )
        trace.step("Computed Midijob RV (Rentenversicherung) via the official 3-step mechanism.")
    trace.resolve_ok("midijob_rv", total=rv_total, employee=rv_employee, employer=rv_employer)

    # ── ALV (Arbeitslosenversicherung) ── same rate_map consistency as RV above.
    if bool(getattr(profile, "de_unemployment_insurance_exempt", False)):
        alv_total = alv_employee = alv_employer = Decimal("0")
        trace.step("Midijob ALV skipped — employee unemployment-insurance exempt.")
    else:
        alv_employee_pct, alv_employer_pct = two_sided_rate(
            ctx.rate_map, "alv_unemployment", _DE_ALV_EMPLOYEE_RATE, _DE_ALV_EMPLOYER_RATE,
        )
        alv_combined = alv_employee_pct + alv_employer_pct
        alv_total, alv_employee, alv_employer = calculate_midijob_branch_contribution(
            total_base, employee_base, combined_rate_pct=alv_combined, employee_rate_pct=alv_employee_pct,
        )
        trace.step("Computed Midijob ALV (Arbeitslosenversicherung) via the official 3-step mechanism.")
    trace.resolve_ok("midijob_alv", total=alv_total, employee=alv_employee, employer=alv_employer)

    # ── GKV (Krankenversicherung) ── same rate_map consistency as RV/ALV above
    # for the GENERAL rate; the fund-specific supplementary rate is
    # unaffected (already resolved from the separately effective-dated
    # GermanyHealthFund registry inside calculate_midijob_gkv itself).
    health_insurance_status = getattr(profile, "de_health_insurance_status", None)
    gkv_general_employee_pct, gkv_general_employer_pct = two_sided_rate(
        ctx.rate_map, "gkv_general", _DE_GKV_GENERAL_EMPLOYEE_RATE, _DE_GKV_GENERAL_EMPLOYER_RATE,
    )
    try:
        gkv_total, gkv_employee, gkv_employer, kvz_rate = calculate_midijob_gkv(
            total_base, employee_base, health_insurance_status=health_insurance_status, health_fund=ctx.germany_health_fund,
            gkv_general_employee_rate=gkv_general_employee_pct, gkv_general_employer_rate=gkv_general_employer_pct,
        )
    except GermanyCalculationError as exc:
        _block(exc, "Midijob GKV (health insurance) calculation blocked.")
    if ctx.germany_health_fund is not None:
        trace.health_fund_record_id = getattr(ctx.germany_health_fund, "id", None)
        trace.health_fund_id = getattr(ctx.germany_health_fund, "health_fund_id", None)
        trace.health_fund_supplementary_rate_pct = str(getattr(ctx.germany_health_fund, "supplementary_rate_pct", None))
        trace.health_fund_name = getattr(ctx.germany_health_fund, "fund_name", None)
        trace.health_fund_effective_from = str(getattr(ctx.germany_health_fund, "effective_from", None))
    trace.resolve_ok("midijob_gkv", total=gkv_total, employee=gkv_employee, employer=gkv_employer)
    trace.step("Computed Midijob GKV (health insurance) via the official 3-step mechanism.")

    # ── PV (Pflegeversicherung) ──
    if health_insurance_status == "PRIVATE":
        pv_total = pv_employee = pv_employer = Decimal("0")
        trace.step("Skipped Midijob PV — employee is privately health-insured (PKV).")
    else:
        try:
            pv_child_category = resolve_pv_child_category(profile)
        except GermanyCalculationError as exc:
            _block(exc, "Midijob PV child-category resolution blocked.")
        trace.pv_child_category = pv_child_category
        trace.pv_is_saxony = bool(getattr(profile, "de_saxony", False))
        try:
            pv_result = calculate_midijob_pv(
                total_base, employee_base, pv_configuration=ctx.germany_pv_configuration,
                is_childless=(pv_child_category == "CHILDLESS"),
                childless_surcharge_rate_pct=_resolve_minijob_midijob_value(
                    de_parameters, "midijob_pv_childless_surcharge_rate", _DE_PV_CHILDLESS_SURCHARGE_RATE,
                ),
            )
        except GermanyCalculationError as exc:
            _block(exc, "Midijob PV (long-term care insurance) calculation blocked.")
        pv_total, pv_employee, pv_employer = pv_result.total, pv_result.employee, pv_result.employer
        trace.pv_configuration_id = getattr(ctx.germany_pv_configuration, "id", None)
        _trace_pv_config(trace, ctx.germany_pv_configuration)
        trace.resolve_ok(
            "midijob_pv", total=pv_total, employee=pv_employee, employer=pv_employer,
            childless_surcharge=(pv_result.childless_surcharge if pv_result.childless_surcharge is not None else "N/A"),
        )
        trace.step("Computed Midijob PV (Pflegeversicherung) via the official 3-step mechanism.")

    # ── Employer levies (U1/U2/U3/accident insurance, spec §14) ──
    # Phase 8M: U3 (Insolvenzumlage) is a flat FEDERAL rate (unlike U1/U2's
    # fund/tariff-specific nature, DE-D06) and applies to every Germany
    # employment classification per spec §14, not just Minijob.
    # Phase 8U: U3's assessment base is "the wage RV contributions are
    # calculated on" (§358 SGB III, confirmed live) — for Midijob that is
    # `total_base` (the SAME base calculate_midijob_branch_contribution
    # already uses for RV above), never raw monthly_gross.
    employer_insolvency_levy = calculate_employer_insolvency_levy(
        total_base,
        _resolve_minijob_midijob_value(de_parameters, "employer_insolvency_levy_rate", _DE_INSOLVENCY_LEVY_RATE),
    )
    # Phase 8W: U1 now resolves from the employer-selected GermanyHealthFundU1Tariff,
    # falling back to the deprecated GermanyHealthFund.u1_rate_pct for backward
    # compatibility. U2 remains fund-level. Applied to monthly_gross (the employee's
    # actual period earnings), consistent with how Minijob's own U1/U2 are a flat %
    # of period gross.
    u1_rate = None
    u1_tariff_obj = getattr(ctx, "germany_u1_tariff", None)
    if u1_tariff_obj is not None:
        u1_rate = getattr(u1_tariff_obj, "levy_rate_pct", None)
    elif ctx.germany_health_fund is not None:
        u1_rate = getattr(ctx.germany_health_fund, "u1_rate_pct", None)
    u2_rate = getattr(ctx.germany_health_fund, "u2_rate_pct", None) if ctx.germany_health_fund else None
    employer_u1 = _round2(monthly_gross * Decimal(u1_rate) / Decimal("100")) if u1_rate is not None else None
    employer_u2 = _round2(monthly_gross * Decimal(u2_rate) / Decimal("100")) if u2_rate is not None else None
    accident_profile = (ctx.employer_tax_profiles or {}).get("DE_ACCIDENT_INSURANCE") if getattr(ctx, "employer_tax_profiles", None) else None
    trace.accident_insurance_status = (
        "CONFIGURED — employer profile on file (annual Berufsgenossenschaft assessment, no monthly deduction computed)"
        if accident_profile else "NOT_CONFIGURED — carrier-specific rate not available"
    )
    trace.resolve_ok(
        "midijob_employer_levies", u3_insolvency_levy=employer_insolvency_levy,
        u1=(employer_u1 if employer_u1 is not None else "NOT_CONFIGURED — health-fund/tariff-specific rate not available"),
        u2=(employer_u2 if employer_u2 is not None else "NOT_CONFIGURED — health-fund/tariff-specific rate not available"),
        accident_insurance=(
            f"CONFIGURED (rate on file, annual assessment — {accident_profile.employer_rate_pct}%)"
            if accident_profile else "NOT_CONFIGURED"
        ),
    )
    trace.step("Computed Midijob employer insolvency levy (U3) on the total_base RV assessment base.")
    if employer_u1 is not None or employer_u2 is not None:
        u1_source = "employer-selected U1 tariff" if u1_tariff_obj is not None else "deprecated fund-level u1_rate_pct"
        trace.step(f"Computed Midijob U1/U2 from {u1_source}.")

    jaeg_warning = check_gkv_coverage_threshold(
        health_insurance_status=health_insurance_status, annual_gross=monthly_gross * MONTHS_PER_YEAR,
        jaeg_annual_threshold=_DE_JAEG_ANNUAL_THRESHOLD,
    )
    if jaeg_warning:
        trace.warnings.append(jaeg_warning)

    # Ceilings are resolved and traced for consistency with the REGULAR
    # path's own architecture, even though — structurally, for every
    # earnings value inside the Midijob corridor (max AE = 2,000.00/month,
    # i.e. 24,000/year) — total_base/employee_base never approach the
    # RV_ALV (~101,400/year) or GKV_PV (~69,750/year) annual ceilings, so
    # no capping is ever actually triggered (Phase 8J §20's own required
    # interaction check; see the phase report for the numeric proof).
    trace.ceiling_rv_alv_id = getattr(ctx.germany_ceiling_rv_alv, "id", None)
    _trace_ceiling(trace, "rv_alv", ctx.germany_ceiling_rv_alv)
    trace.ceiling_gkv_pv_id = getattr(ctx.germany_ceiling_gkv_pv, "id", None)
    _trace_ceiling(trace, "gkv_pv", ctx.germany_ceiling_gkv_pv)

    # Phase 8BU: see the REGULAR path's identical field for the full
    # rationale — never fabricated as zero; non-empty means the return
    # dict below is PARTIAL, not COMPLETE.
    unavailable_components: list = []

    # ── Church tax (Kirchensteuer) — same resolution as REGULAR ──
    church_tax_liable = bool(getattr(profile, "de_church_tax_liable", False))
    church_tax_rate = None
    if church_tax_liable:
        church_tax_exception = getattr(ctx, "germany_church_tax_exception", None)
        if church_tax_exception is not None:
            church_tax_rate = church_tax_exception.exception_rate_pct
            trace.step(
                f"Resolved church tax EXCEPTION rate: {church_tax_rate}% "
                f"(Land={getattr(profile, 'de_church_tax_land', None)}, "
                f"denomination={getattr(profile, 'de_church_tax_denomination', None)}, "
                f"PLZ={getattr(profile, 'de_church_tax_municipality_postal_code', None)})"
            )
        else:
            try:
                church_tax_rate = _resolve_church_tax_land_rate(de_parameters, getattr(profile, "de_church_tax_land", None))
            except GermanyCalculationError as exc:
                unavailable_components.append("church_tax")
                trace.warnings.append(
                    f"GERMANY_CHURCH_TAX_UNAVAILABLE: {exc.message} Church tax could not be computed; "
                    "all other components (SI, employer levies, wage tax if resolvable) are unaffected."
                )
                trace.step(f"Midijob church tax Land-rate resolution blocked ({exc.code}) — church tax marked UNAVAILABLE, continuing.")
                church_tax_rate = None
            else:
                trace.step(f"Resolved church tax Land rate: {church_tax_rate}%")
        if church_tax_rate is not None:
            trace.church_tax_rate_used = str(church_tax_rate)

    # ── Wage tax: tries the official BMF PAP first, exactly like REGULAR;
    # falls back to the internal functional wage-tax calculator when (as
    # today) no certified PAP asset/executor is available — Phase 8BR.
    trace.pap_asset_id = getattr(ctx.germany_pap_asset, "id", None)
    if ctx.germany_pap_asset is not None:
        trace.pap_source_content_sha256 = getattr(ctx.germany_pap_asset, "source_content_sha256", None)
        trace.pap_build_identifier = getattr(ctx.germany_pap_asset, "build_identifier", None)
        trace.pap_tax_year = getattr(ctx.germany_pap_asset, "tax_year", None)
    pap_input = build_pap_input(
        profile=profile, gross_monthly=ctx.gross, kvz_rate=kvz_rate,
        pay_frequency=getattr(ctx, "pay_frequency", None) or "Monthly",
        sonstb=getattr(ctx, "germany_sonstb", None),
    )
    pap_input.vorsorgepauschale_annual_cents = int(
        ((rv_employee + alv_employee + gkv_employee + pv_employee) * MONTHS_PER_YEAR * 100).to_integral_value()
    )
    trace_tax_data_used(trace, profile, pap_input)
    main_secondary_warning = check_main_secondary_employment_consistency(
        tax_class=pap_input.stkl, is_main_employment=getattr(profile, "de_main_employment", None),
    )
    if main_secondary_warning:
        trace.warnings.append(main_secondary_warning)
    executor = resolve_pap_executor(ctx.germany_pap_asset)
    pap_result = None
    try:
        pap_result = executor.execute(pap_input)
    except GermanyPapNotAvailableError as exc:
        trace.step(
            f"Official BMF PAP unavailable ({exc.message}) — falling back to the internal functional "
            "wage-tax calculator (germany_internal_tax.py, INTERNAL_FUNCTIONAL_REFERENCE, not BMF-certified)."
        )
        try:
            internal_executor = InternalGermanyWageTaxCalculator(
                soli_threshold_single=_DE_SOLI_THRESHOLD, soli_rate_pct=_DE_SOLI_RATE,
                payroll_date=getattr(ctx, "germany_payroll_date", None),
            )
            pap_result = internal_executor.execute(pap_input)
        except GermanyInternalTariffNotAvailableError as tariff_exc:
            # Phase 8BU (Part 21) — see the REGULAR path's identical branch
            # for the full rationale: RV/ALV/GKV/PV/employer-levies above
            # are real and already resolved; do not discard them just
            # because wage tax specifically is unavailable for this date.
            for component in ("wage_tax", "soli", "church_tax"):
                if component not in unavailable_components:
                    unavailable_components.append(component)
            trace.warnings.append(
                f"GERMANY_WAGE_TAX_UNAVAILABLE: {tariff_exc.message} Neither the official BMF PAP nor the "
                "internal functional reference calculator could compute wage tax/Soli for this payroll date; "
                "church tax is also unavailable as a consequence. SI and employer levies above are unaffected."
            )
            trace.step(f"Midijob internal wage-tax fallback also unavailable ({tariff_exc.code}) — wage tax/Soli/church tax marked UNAVAILABLE, continuing.")
        else:
            trace.warnings.extend(pap_result.warnings)
            # Structured (not prose-only) surface for the internal calculator's
            # own working figures and disclosed approximations — a consumer
            # (frontend diagnostic view, audit tooling) can read
            # snapshot.resolved.internal_wage_tax.REFERENCE_APPROXIMATION
            # directly instead of parsing warning text.
            if pap_result.raw_outputs:
                trace.resolve_ok("internal_wage_tax", **pap_result.raw_outputs)
    except GermanyCalculationError as exc:
        _block(exc, "Midijob social-insurance contributions computed successfully (see trace); PAP (Lohnsteuer/Soli) execution blocked.")

    if pap_result is not None:
        trace.pap_version = pap_result.pap_version
        trace.step("Midijob wage tax (Lohnsteuer/Soli) execution complete.")
        monthly_lohnsteuer_soli = _round2((pap_result.lohnsteuer + pap_result.soli) / MONTHS_PER_YEAR)
        annual_tax = pap_result.lohnsteuer + pap_result.soli
        soli_monthly = _round2(pap_result.soli / MONTHS_PER_YEAR)
        church_tax = (
            _round2((pap_result.church_tax_assessment_base * church_tax_rate / Decimal("100")) / MONTHS_PER_YEAR)
            if (church_tax_liable and church_tax_rate is not None) else Decimal("0")
        )
    else:
        monthly_lohnsteuer_soli = Decimal("0")
        annual_tax = Decimal("0")
        soli_monthly = Decimal("0")
        church_tax = Decimal("0")

    trace.unavailable_components = list(unavailable_components)
    if unavailable_components:
        trace.calculation_status = "PARTIALLY_CALCULATED"
        trace.step(f"Midijob calculation PARTIAL — unavailable components: {', '.join(unavailable_components)}.")
    else:
        trace.calculation_status = "COMPLETE"

    return dict(
        employee_pf=rv_employee, employer_pf=rv_employer,
        employee_esi=alv_employee + gkv_employee + pv_employee,
        employer_esi=alv_employer + gkv_employer + pv_employer + employer_insolvency_levy,
        church_tax=church_tax,
        tds=monthly_lohnsteuer_soli, annual_tax=annual_tax,
        soli=soli_monthly,
        _germany_unavailable_components=unavailable_components,
        _germany_statutory_profile_id=trace.statutory_profile_id,
        _germany_calculation_snapshot=trace.to_dict(),
    )


def calculate(ctx: PayrollContext) -> dict:
    """Germany production calculation — see module docstring. Raises a
    GermanyCalculationError subclass (engine/countries/germany_pap.py)
    whenever a required statutory source cannot be resolved; never
    returns a fabricated/partial result. Callers (service.py) are
    responsible for translating a raised error into an HTTP response —
    see GermanyCalculationBlockedException in app.core.exceptions."""
    trace = GermanyCalculationTrace(
        employee_id=getattr(ctx, "germany_employee_id", None),
        organization_id=getattr(ctx, "germany_organization_id", None),
        payroll_date=str(getattr(ctx, "germany_payroll_date", None)) if getattr(ctx, "germany_payroll_date", None) else None,
    )

    def _block(exc: GermanyCalculationError, step_message: str):
        trace.step(step_message)
        trace.calculation_status = "BLOCKED"
        trace.blocked_reason_code = exc.code
        trace.blocked_reason_message = exc.message
        exc.trace = trace
        raise exc

    profile = ctx.germany_statutory_profile
    if profile is None:
        _block(
            GermanyStatutoryProfileMissingError(
                "No effective EmployeeStatutoryProfile exists for this employee as of "
                "the payroll date. Record one via POST /payroll/employees/{id}/statutory-profile "
                "before running Germany payroll for this employee."
            ),
            "No EmployeeStatutoryProfile resolved.",
        )
    trace.statutory_profile_id = getattr(profile, "id", None)
    trace.statutory_profile_effective_from = str(getattr(profile, "effective_from", None))
    trace.step("Resolved EmployeeStatutoryProfile")

    # Phase 8X — trace the four-dimension earning taxability (spec §15) for
    # every earning type this run actually consumes. Fail-closed: surfaces
    # NOT_CONFIGURED when no PUBLISHED rule exists, never invents one, and
    # never alters the settled rate math below.
    _trace_earning_taxability(trace, ctx)

    try:
        classification = resolve_employment_classification(profile)
    except GermanyCalculationError as exc:
        _block(exc, "Employment classification could not be resolved.")
    trace.employment_classification = classification
    trace.step(f"Resolved employment classification: {classification}")

    de_parameters = getattr(ctx, "germany_minijob_midijob_parameters", None)
    try:
        validate_employment_classification_against_earnings(
            classification, ctx.gross,
            minijob_upper_threshold=_resolve_minijob_midijob_value(
                de_parameters, "minijob_upper_threshold", _DE_MINIJOB_UPPER_THRESHOLD,
            ),
            midijob_upper_threshold=_resolve_minijob_midijob_value(
                de_parameters, "midijob_upper_threshold", _DE_MIDIJOB_UPPER_THRESHOLD,
            ),
        )
    except GermanyCalculationError as exc:
        _block(exc, f"Employment classification {classification} is inconsistent with this period's earnings.")

    try:
        validate_employment_classification_against_vocational_training(
            classification, bool(getattr(profile, "de_vocational_trainee", False)),
        )
    except GermanyCalculationError as exc:
        _block(exc, f"Employment classification {classification} is inconsistent with vocational-trainee status.")

    if classification == "MINIJOB":
        return _calculate_minijob_path(ctx, profile, trace, _block)
    if classification == "MIDIJOB":
        return _calculate_midijob_path(ctx, profile, trace, _block)

    annual_gross = ctx.gross * MONTHS_PER_YEAR

    try:
        employee_rv, employer_rv = calculate_rv(
            annual_gross=annual_gross, ceiling_rv_alv=ctx.germany_ceiling_rv_alv, rate_map=ctx.rate_map,
            exempt=bool(getattr(profile, "de_pension_insurance_exempt", False)),
            rv_employee_default=_DE_RV_EMPLOYEE_RATE, rv_employer_default=_DE_RV_EMPLOYER_RATE,
            months_per_year=MONTHS_PER_YEAR,
        )
    except GermanyCalculationError as exc:
        _block(exc, "RV (pension insurance) calculation blocked.")
    trace.ceiling_rv_alv_id = getattr(ctx.germany_ceiling_rv_alv, "id", None)
    _trace_ceiling(trace, "rv_alv", ctx.germany_ceiling_rv_alv)
    trace.resolve_ok("rv", employee=employee_rv, employer=employer_rv)
    trace.step("Computed RV (Rentenversicherung)")

    try:
        employee_alv, employer_alv = calculate_alv(
            annual_gross=annual_gross, ceiling_rv_alv=ctx.germany_ceiling_rv_alv, rate_map=ctx.rate_map,
            exempt=bool(getattr(profile, "de_unemployment_insurance_exempt", False)),
            alv_employee_default=_DE_ALV_EMPLOYEE_RATE, alv_employer_default=_DE_ALV_EMPLOYER_RATE,
            months_per_year=MONTHS_PER_YEAR,
        )
    except GermanyCalculationError as exc:
        _block(exc, "ALV (unemployment insurance) calculation blocked.")
    trace.resolve_ok("alv", employee=employee_alv, employer=employer_alv)
    trace.step("Computed ALV (Arbeitslosenversicherung)")

    health_insurance_status = getattr(profile, "de_health_insurance_status", None)
    try:
        employee_gkv, employer_gkv, kvz_rate = calculate_gkv(
            annual_gross=annual_gross, ceiling_gkv_pv=ctx.germany_ceiling_gkv_pv, rate_map=ctx.rate_map,
            health_insurance_status=health_insurance_status, health_fund=ctx.germany_health_fund,
            gkv_employee_default=_DE_GKV_GENERAL_EMPLOYEE_RATE, gkv_employer_default=_DE_GKV_GENERAL_EMPLOYER_RATE,
            months_per_year=MONTHS_PER_YEAR,
        )
    except GermanyCalculationError as exc:
        _block(exc, "GKV (health insurance) calculation blocked.")
    trace.ceiling_gkv_pv_id = getattr(ctx.germany_ceiling_gkv_pv, "id", None)
    _trace_ceiling(trace, "gkv_pv", ctx.germany_ceiling_gkv_pv)
    if ctx.germany_health_fund is not None:
        trace.health_fund_record_id = getattr(ctx.germany_health_fund, "id", None)
        trace.health_fund_id = getattr(ctx.germany_health_fund, "health_fund_id", None)
        trace.health_fund_supplementary_rate_pct = str(getattr(ctx.germany_health_fund, "supplementary_rate_pct", None))
        trace.health_fund_name = getattr(ctx.germany_health_fund, "fund_name", None)
        trace.health_fund_effective_from = str(getattr(ctx.germany_health_fund, "effective_from", None))
        trace.health_fund_is_average_rate = bool(getattr(ctx.germany_health_fund, "is_average_rate", False))
    trace.resolve_ok("gkv", employee=employee_gkv, employer=employer_gkv)
    trace.step("Computed GKV (statutory health insurance)")

    try:
        pv_child_category = resolve_pv_child_category(profile) if health_insurance_status != "PRIVATE" else None
    except GermanyCalculationError as exc:
        _block(exc, "PV child-category resolution blocked.")

    if health_insurance_status == "PRIVATE":
        employee_pv, employer_pv = Decimal("0"), Decimal("0")
        trace.step("Skipped PV — employee is privately health-insured (PKV).")
    else:
        trace.pv_child_category = pv_child_category
        trace.pv_is_saxony = bool(getattr(profile, "de_saxony", False))
        try:
            employee_pv, employer_pv = calculate_pv(
                annual_gross=annual_gross, ceiling_gkv_pv=ctx.germany_ceiling_gkv_pv,
                pv_configuration=ctx.germany_pv_configuration, months_per_year=MONTHS_PER_YEAR,
            )
        except GermanyCalculationError as exc:
            _block(exc, "PV (long-term care insurance) calculation blocked.")
        trace.pv_configuration_id = getattr(ctx.germany_pv_configuration, "id", None)
        _trace_pv_config(trace, ctx.germany_pv_configuration)
        trace.resolve_ok("pv", employee=employee_pv, employer=employer_pv)
        trace.step("Computed PV (Pflegeversicherung)")

    # ── Employer levies (U1/U2/U3/accident insurance, spec §14) ──
    # Phase 8M: see _calculate_midijob_path's identical block for the full
    # citation — U3 is a flat federal rate the spec applies to every
    # Germany employment classification, not just Minijob.
    # Phase 8U: U3's assessment base is the SAME RV-ceiling-capped wage
    # basis RV contributions use (§358 SGB III, confirmed live this
    # phase) — NOT raw uncapped gross (Phase 8M's original bug for this
    # one path; Minijob's own U3 was always correctly below any
    # conceivable ceiling and needed no such cap).
    u3_assessment_base_monthly = _round2(min(annual_gross, Decimal(ctx.germany_ceiling_rv_alv.annual_ceiling)) / MONTHS_PER_YEAR)
    employer_insolvency_levy = calculate_employer_insolvency_levy(
        u3_assessment_base_monthly,
        _resolve_minijob_midijob_value(de_parameters, "employer_insolvency_levy_rate", _DE_INSOLVENCY_LEVY_RATE),
    )
    # Phase 8U: U1/U2 (health-fund-specific, spec DE-D06) now resolvable
    # when the employee's own resolved GermanyHealthFund record carries
    # published rates (new u1_rate_pct/u2_rate_pct columns) — never a
    # universal/national rate. Still NOT_CONFIGURED when the fund hasn't
    # published one (never silently zero).
    # Phase 8W: U1/U2 resolution — U1 now resolves from the employer-selected
    # GermanyHealthFundU1Tariff (via EmployeeStatutoryProfile.de_u1_tariff_id),
    # falling back to the deprecated GermanyHealthFund.u1_rate_pct for backward
    # compatibility when no tariff selection exists. U2 remains fund-level (single
    # tariff per fund). The U1 tariff takes precedence over the legacy column.
    u1_rate = None
    u1_tariff_obj = getattr(ctx, "germany_u1_tariff", None)
    if u1_tariff_obj is not None:
        u1_rate = getattr(u1_tariff_obj, "levy_rate_pct", None)
    elif ctx.germany_health_fund is not None:
        # Deprecated fallback — retained for backward compatibility only
        u1_rate = getattr(ctx.germany_health_fund, "u1_rate_pct", None)
    u2_rate = getattr(ctx.germany_health_fund, "u2_rate_pct", None) if ctx.germany_health_fund else None
    employer_u1 = _round2(ctx.gross * Decimal(u1_rate) / Decimal("100")) if u1_rate is not None else None
    employer_u2 = _round2(ctx.gross * Decimal(u2_rate) / Decimal("100")) if u2_rate is not None else None
    # Phase 8U: accident insurance is a real, employer-level, carrier/
    # risk-class-specific statutory fact (spec §14) — resolved, when
    # configured, from the SAME EmployerTaxProfile mechanism the standard
    # already uses for US SUI (agency-assigned experience rating; see
    # ctx.employer_tax_profiles's own existing shape). German accident
    # insurance is assessed ANNUALLY by the Berufsgenossenschaft against
    # reported wage totals (Lohnnachweis), not withheld per pay period —
    # no PAP/statutory mechanism computes a monthly deduction from it, so
    # this deliberately traces CONFIGURED/NOT_CONFIGURED and the on-file
    # rate for audit visibility only, never fabricating a monthly amount.
    accident_profile = (ctx.employer_tax_profiles or {}).get("DE_ACCIDENT_INSURANCE") if getattr(ctx, "employer_tax_profiles", None) else None
    trace.accident_insurance_status = (
        f"CONFIGURED — employer profile on file (annual Berufsgenossenschaft assessment, no monthly deduction computed)"
        if accident_profile else "NOT_CONFIGURED — carrier-specific rate not available"
    )
    trace.resolve_ok(
        "employer_levies", u3_insolvency_levy=employer_insolvency_levy,
        u1=(employer_u1 if employer_u1 is not None else "NOT_CONFIGURED — health-fund/tariff-specific rate not available"),
        u2=(employer_u2 if employer_u2 is not None else "NOT_CONFIGURED — health-fund/tariff-specific rate not available"),
        accident_insurance=(
            f"CONFIGURED (rate on file, annual assessment — {accident_profile.employer_rate_pct}%)"
            if accident_profile else "NOT_CONFIGURED"
        ),
    )
    trace.step("Computed employer insolvency levy (U3) on the RV-ceiling-capped assessment base.")
    if employer_u1 is not None or employer_u2 is not None:
        u1_source = "employer-selected U1 tariff" if u1_tariff_obj is not None else "deprecated fund-level u1_rate_pct"
        trace.step(f"Computed employer U1/U2 from {u1_source}.")

    jaeg_warning = check_gkv_coverage_threshold(
        health_insurance_status=health_insurance_status, annual_gross=annual_gross,
        jaeg_annual_threshold=_DE_JAEG_ANNUAL_THRESHOLD,
    )
    if jaeg_warning:
        trace.warnings.append(jaeg_warning)

    # Phase 8BU: components genuinely unavailable for THIS employee this
    # run (never fabricated as zero) — if this list is non-empty by the
    # time the return dict is built, the whole result is PARTIAL, not
    # COMPLETE, even though every OTHER component below is real.
    unavailable_components: list = []

    church_tax_liable = bool(getattr(profile, "de_church_tax_liable", False))
    church_tax_rate = None
    if church_tax_liable:
        # Phase 8AM: check for a pre-resolved sub-Land church-tax exception
        # (e.g. Bad Wimpfen Roman Catholic 9% within Baden-Württemberg's 8%).
        # The resolver in service.py returns a PUBLISHED GermanyChurchTaxException
        # row when all three keys (Land, denomination, municipality postal code)
        # match and the payroll date falls within its effective period. If absent,
        # we fall back to the ordinary Land rate exactly as before this phase.
        church_tax_exception = getattr(ctx, "germany_church_tax_exception", None)
        if church_tax_exception is not None:
            church_tax_rate = church_tax_exception.exception_rate_pct
            trace.step(
                f"Resolved church tax EXCEPTION rate: {church_tax_rate}% "
                f"(Land={getattr(profile, 'de_church_tax_land', None)}, "
                f"denomination={getattr(profile, 'de_church_tax_denomination', None)}, "
                f"PLZ={getattr(profile, 'de_church_tax_municipality_postal_code', None)})"
            )
        else:
            try:
                church_tax_rate = _resolve_church_tax_land_rate(de_parameters, getattr(profile, "de_church_tax_land", None))
            except GermanyCalculationError as exc:
                # Phase 8BU (Part 21 — "do not automatically block unrelated
                # components"): a missing church-tax Land rate is UNRELATED
                # to RV/ALV/GKV/PV/employer levies, all of which have
                # already resolved successfully above at this point in the
                # function. Rather than discarding those real, computed
                # figures via _block()'s immediate raise, this is recorded
                # as a PARTIAL-calculation condition and wage tax is still
                # attempted below — see `unavailable_components` and the
                # PARTIAL-result construction at the end of this function.
                unavailable_components.append("church_tax")
                trace.warnings.append(
                    f"GERMANY_CHURCH_TAX_UNAVAILABLE: {exc.message} Church tax could not be computed; "
                    "all other components (SI, employer levies, wage tax if resolvable) are unaffected."
                )
                trace.step(f"Church tax Land-rate resolution blocked ({exc.code}) — church tax marked UNAVAILABLE, continuing.")
                church_tax_rate = None
            else:
                trace.step(f"Resolved church tax Land rate: {church_tax_rate}%")
        if church_tax_rate is not None:
            trace.church_tax_rate_used = str(church_tax_rate)

    # ── Lohnsteuer / Soli / Kirchensteuer base — requires the real BMF PAP ──
    trace.pap_asset_id = getattr(ctx.germany_pap_asset, "id", None)
    if ctx.germany_pap_asset is not None:
        trace.pap_version = getattr(ctx.germany_pap_asset, "pap_version", None)
        trace.pap_source_content_sha256 = getattr(ctx.germany_pap_asset, "source_content_sha256", None)
        trace.pap_build_identifier = getattr(ctx.germany_pap_asset, "build_identifier", None)
        trace.pap_tax_year = getattr(ctx.germany_pap_asset, "tax_year", None)

    pap_input = build_pap_input(
        profile=profile, gross_monthly=ctx.gross, kvz_rate=kvz_rate,
        pay_frequency=getattr(ctx, "pay_frequency", None) or "Monthly",
        sonstb=getattr(ctx, "germany_sonstb", None),
    )
    pap_input.vorsorgepauschale_annual_cents = int(
        ((employee_rv + employee_alv + employee_gkv + employee_pv) * MONTHS_PER_YEAR * 100).to_integral_value()
    )
    trace_tax_data_used(trace, profile, pap_input)
    main_secondary_warning = check_main_secondary_employment_consistency(
        tax_class=pap_input.stkl, is_main_employment=getattr(profile, "de_main_employment", None),
    )
    if main_secondary_warning:
        trace.warnings.append(main_secondary_warning)
    executor = resolve_pap_executor(ctx.germany_pap_asset)
    pap_result = None
    try:
        pap_result = executor.execute(pap_input)
    except GermanyPapNotAvailableError as exc:
        trace.step(
            f"Official BMF PAP unavailable ({exc.message}) — falling back to the internal functional "
            "wage-tax calculator (germany_internal_tax.py, INTERNAL_FUNCTIONAL_REFERENCE, not BMF-certified)."
        )
        try:
            internal_executor = InternalGermanyWageTaxCalculator(
                soli_threshold_single=_DE_SOLI_THRESHOLD, soli_rate_pct=_DE_SOLI_RATE,
                payroll_date=getattr(ctx, "germany_payroll_date", None),
            )
            pap_result = internal_executor.execute(pap_input)
        except GermanyInternalTariffNotAvailableError as tariff_exc:
            # Phase 8BU (Part 21): the OFFICIAL PAP is unavailable AND the
            # internal functional fallback is ALSO unavailable for this
            # specific payroll date (e.g. a date before the internal
            # calculator's own earliest verified tariff version). RV/ALV/
            # GKV/PV/employer-levies above are still real and already
            # resolved — do not discard them. Wage tax, Soli, and (since
            # it depends on the wage-tax assessment base) church tax are
            # all marked genuinely UNAVAILABLE, never fabricated as zero;
            # the function falls through to the PARTIAL-result branch below.
            for component in ("wage_tax", "soli", "church_tax"):
                if component not in unavailable_components:
                    unavailable_components.append(component)
            trace.warnings.append(
                f"GERMANY_WAGE_TAX_UNAVAILABLE: {tariff_exc.message} Neither the official BMF PAP nor the "
                "internal functional reference calculator could compute wage tax/Soli for this payroll date; "
                "church tax is also unavailable as a consequence (its assessment base depends on wage tax). "
                "SI and employer levies above are unaffected."
            )
            trace.step(f"Internal wage-tax fallback also unavailable ({tariff_exc.code}) — wage tax/Soli/church tax marked UNAVAILABLE, continuing.")
        else:
            trace.warnings.extend(pap_result.warnings)
            # Structured (not prose-only) surface for the internal calculator's
            # own working figures and disclosed approximations — a consumer
            # (frontend diagnostic view, audit tooling) can read
            # snapshot.resolved.internal_wage_tax.REFERENCE_APPROXIMATION
            # directly instead of parsing warning text.
            if pap_result.raw_outputs:
                trace.resolve_ok("internal_wage_tax", **pap_result.raw_outputs)
    except GermanyCalculationError as exc:
        _block(exc, "PAP (Lohnsteuer/Soli) execution blocked.")

    if pap_result is not None:
        trace.pap_version = pap_result.pap_version
        trace.step("Wage tax (Lohnsteuer/Soli) execution complete.")
        monthly_lohnsteuer_soli = _round2((pap_result.lohnsteuer + pap_result.soli) / MONTHS_PER_YEAR)
        annual_tax = pap_result.lohnsteuer + pap_result.soli
        soli_monthly = _round2(pap_result.soli / MONTHS_PER_YEAR)
        church_tax = (
            _round2((pap_result.church_tax_assessment_base * church_tax_rate / Decimal("100")) / MONTHS_PER_YEAR)
            if (church_tax_liable and church_tax_rate is not None) else Decimal("0")
        )
    else:
        # Wage tax (and therefore Soli/church tax) is genuinely
        # UNAVAILABLE for this payroll date — see the
        # GermanyInternalTariffNotAvailableError branch above. Never
        # fabricated as zero-because-successful; the PARTIAL branch below
        # is what actually communicates this to the caller/UI.
        monthly_lohnsteuer_soli = Decimal("0")
        annual_tax = Decimal("0")
        soli_monthly = Decimal("0")
        church_tax = Decimal("0")

    trace.unavailable_components = list(unavailable_components)
    if unavailable_components:
        trace.calculation_status = "PARTIALLY_CALCULATED"
        trace.step(f"Calculation PARTIAL — unavailable components: {', '.join(unavailable_components)}.")
    else:
        trace.calculation_status = "COMPLETE"

    return dict(
        employee_pf=employee_rv, employer_pf=employer_rv,
        employee_esi=employee_alv + employee_gkv + employee_pv,
        employer_esi=employer_alv + employer_gkv + employer_pv + employer_insolvency_levy,
        church_tax=church_tax,
        tds=monthly_lohnsteuer_soli, annual_tax=annual_tax,
        # Soli's monthly amount — informational, already folded into `tds`
        # above (monthly_lohnsteuer_soli = (Lohnsteuer + Soli)/12), carried
        # so service.py can persist it onto PayslipItem.soli without
        # re-deriving it from the (sub-annual) PAP period outputs.
        soli=soli_monthly,
        # Phase 8BU: non-empty ONLY when this is a PARTIAL result (see
        # service.py's consumer, which sets PayslipStatus.PARTIAL and
        # skips computing a fabricated net_pay when this is present).
        _germany_unavailable_components=unavailable_components,
        # Not part of PayrollResult's dataclass fields (read via .get() with
        # a default by engine/standard.py, so harmless to include) — carried
        # through so service.py can persist the Phase 7 statutory snapshot
        # (see service._compute_payslip_values) without a second resolve.
        _germany_statutory_profile_id=trace.statutory_profile_id,
        _germany_calculation_snapshot=trace.to_dict(),
    )
