"""
modules/payroll/engine/germany_internal_tax.py
-------------------------------------------------
Phase 8BR — Germany INTERNAL functional wage-tax calculator.

THIS IS NOT THE OFFICIAL BMF PAP. It is a clearly-separated, disclosed,
internal reference implementation of the *statutory formulas* Germany's
wage-tax procedure is built on (Einkommensteuertarif, section 32a EStG;
Solidaritaetszuschlag, SolzG 1995; the annualize -> tariff -> de-annualize
mechanics of section 39b EStG). Every one of those formulas is the text of
a published law, not the Bundesministerium der Finanzen's own certified
"Programmablaufplan" (PAP) software/XML artifact — which remains
genuinely unavailable in this repository (see germany_pap/core.py's
resolve_pap_executor() and docs/GERMANY_PAP_8_GATE_EVIDENCE_MATRIX.md) and
stays gated exactly as before. This module exists so that a Regular or
Midijob Germany employee is not permanently blocked from ever running
payroll merely because the *certified* artifact hasn't been licensed/
ingested — see docs/PHASE_8BR_GERMANY_FUNCTIONAL_PAYROLL_COMPLETION_REPORT.md.

Every result this module produces carries
`pap_version="INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2023"` (never a
version string that could be mistaken for an official BMF release) and a
non-empty `warnings` list disclosing every simplification versus the real
withholding procedure. Nothing here is presented as, or should ever be
represented as, "BMF certified" / "PAP compliant" output.

PROVENANCE OF EVERY CONSTANT (do not change without updating this list
and the phase report):

- Grundfreibetrag EUR 10,908 and all 5 tariff-zone boundaries/
  coefficients: section 32a EStG, 2023 assessment year (BGBl. 2022 I
  S. 2230) — the most recent full tariff this codebase's author can state
  with high confidence from the published law text. THIS IS OLDER than
  the 2026 social-insurance rates already configured elsewhere in this
  Germany jurisdiction (see hardcoded_defaults.py's Phase 7 SI constants)
  — a disclosed, deliberate choice: shipping a verified-older tariff
  beats fabricating unverified newer bracket numbers. See "Known
  limitations" below and the effective-dating note on
  `resolve_income_tax_tariff()`.
- Arbeitnehmer-Pauschbetrag EUR 1,230/year: section 9a EStG, in force
  since 2023.
- Sonderausgaben-Pauschbetrag EUR 36/year (single): section 10c EStG,
  unchanged for decades.
- Kinderfreibetrag + BEA (Betreuungs-/Erziehungs-/Ausbildungsbedarf)
  combined EUR 8,952/year per full ZKF unit: section 32 Abs. 6 EStG, 2023.
  Used ONLY for the section 51a EStG Soli/Kirchensteuer assessment-base
  reduction, never for the wage-tax withholding base itself (matching the
  real law's own split treatment — ZKF is a "counting" allowance for
  surcharges only, not a wage-tax deduction; Kindergeld is the actual
  monthly benefit).
- Solidaritaetszuschlag exemption threshold EUR 18,130 (single) /
  EUR 36,260 (Splitting, class III): SAME constant already resolved in
  this codebase's hardcoded_defaults.py (`_DE_SOLI_THRESHOLD`) — reused,
  not re-invented, per this phase's explicit "use authoritative values
  already present in the repository" instruction.
- Solidaritaetszuschlag mitigation-zone rate 11.9%: section 4 Satz 2
  SolzG 1995, as amended 2021 — unchanged since.
- Entlastungsbetrag fuer Alleinerziehende EUR 4,260/year (first child) +
  EUR 240/year per additional child: section 24b Abs. 2 EStG, as amended
  by the Jahressteuergesetz 2022 (in force since 2023-01-01, unchanged
  through at least 2026 assessment years) — Phase 8BT.

KNOWN, DISCLOSED LIMITATIONS (Category A/B per the phase report's own
taxonomy — tracked, not hidden):

1. Tax year mismatch: the income-tax tariff below is the 2023 assessment
   year; the rest of this Germany jurisdiction's statutory config targets
   2026. Every calculation this module performs is labeled with this tax
   year explicitly. Updating to a later, source-verified tariff is a
   pure data change (see resolve_income_tax_tariff) — Category B, blocked
   on acquiring/verifying the exact newer zone coefficients, not on any
   code limitation.
2. Vorsorgepauschale (pension/health/care insurance deduction estimate)
   is APPROXIMATED as this period's actual computed employee RV+ALV+GKV+PV
   contributions (annualized) rather than the BMF PAP's own distinct
   formula (which has its own floors/caps that can diverge from actual
   contributions in edge cases, e.g. very low earners or those above the
   contribution ceiling). Disclosed via `warnings`.
3. Tax classes V and VI do not receive this module's Arbeitnehmer-
   Pauschbetrag/Sonderausgaben-Pauschbetrag/Vorsorgepauschale treatment
   the same way I/II/III/IV do (V: Vorsorgepauschale only, no basic
   allowances; VI: no allowances at all) but the real, certified PAP uses
   a materially more complex "vervielfaeltigende" (multiplying) procedure
   for V/VI wage-tax cards that this module does NOT replicate exactly.
   Every V/VI result carries an explicit warning
   ("GERMANY_TAX_CLASS_V_VI_APPROXIMATE").
4. [CLOSED, Phase 8BT] Tax class II's Entlastungsbetrag fuer
   Alleinerziehende (section 24b EStG, 2023 amount, unchanged through at
   least 2026) is now modeled: EUR 4,260/year for the first child plus
   EUR 240/year for each additional child, derived from
   EmployeeStatutoryProfile.de_child_count. No separate eligibility flag
   is needed — Tax Class II is ITSELF the eligibility signal under German
   law (section 38b Abs. 1 Nr. 2 EStG: the Finanzamt only assigns Class II
   to an employee who already qualifies for the Entlastungsbetrag), so
   `de_tax_class == "II"` is a sufficient and correct precondition. See
   `_class_allowances()`.
5. Splittingverfahren (Class III) is computed using only this employee's
   own recorded allowances, not a joint assessment with a spouse's
   payroll record (this platform models one employee, not a married
   couple) — the doubling/halving mechanics of section 32a Abs. 5 EStG
   itself are applied correctly; only the *allowance* inputs are
   necessarily this employee's own.

None of the above numbers are fabricated: each is either the literal text
of German tax law or an already-computed value elsewhere in this same
calculation run. Where the official procedure is genuinely more complex
than what is implemented, that gap is named, not silently smoothed over.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Optional

from app.modules.payroll.engine.germany_pap.core import (
    GermanyCalculationError,
    GermanyPapCalculationResult,
    PapExecutor,
    PapInputContract,
)

TAX_YEAR_LABEL = "2023-ESTG-32A"
PROVENANCE_VERSION = "INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-2023"

# section 32a EStG, 2023 assessment year.
_GRUNDFREIBETRAG = Decimal("10908")
_ZONE2_UPPER = Decimal("15999")
_ZONE3_UPPER = Decimal("62809")
_ZONE4_UPPER = Decimal("277825")
_ZONE2_A = Decimal("979.18")
_ZONE2_B = Decimal("1400")
_ZONE3_A = Decimal("192.59")
_ZONE3_B = Decimal("2397")
_ZONE3_C = Decimal("966.53")
_ZONE4_RATE = Decimal("0.42")
_ZONE4_SUB = Decimal("9972.98")
_ZONE5_RATE = Decimal("0.45")
_ZONE5_SUB = Decimal("18307.73")

# section 9a EStG (2023) / section 10c EStG.
ARBEITNEHMER_PAUSCHBETRAG = Decimal("1230")
SONDERAUSGABEN_PAUSCHBETRAG = Decimal("36")

# section 32 Abs. 6 EStG (2023) — Kinderfreibetrag + BEA, per full ZKF unit.
# Used only for the section 51a Soli/Kirchensteuer assessment-base reduction.
KINDERFREIBETRAG_PLUS_BEA = Decimal("8952")

# SolzG 1995 section 4 Satz 2 mitigation-zone rate.
SOLI_MILDERUNGSZONE_RATE = Decimal("11.9")

# section 24b Abs. 2 EStG (2023, unchanged through at least 2026) —
# Entlastungsbetrag fuer Alleinerziehende. Tax Class II only.
ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_BASE = Decimal("4260")
ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_PER_ADDITIONAL_CHILD = Decimal("240")


def _floor_euro(value: Decimal) -> Decimal:
    return value.to_integral_value(rounding=ROUND_FLOOR)


def _round_cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class GermanyInternalTariffNotAvailableError(GermanyCalculationError):
    """Raised when `resolve_income_tax_tariff()` is asked for a payroll
    date this module has no verified tariff version for (today: any date
    before 2023-01-01 — this module's only version is open-ended from
    that date forward). Fails closed rather than silently applying a
    tariff whose zone coefficients were never verified as correct for
    that period — the same 'never guess a statutory value' discipline
    every other Germany registry in this codebase already follows.
    Inherits GermanyCalculationError (not a bare Exception) so
    countries/germany.py's existing `except GermanyCalculationError:
    _block(...)` handling catches it and records a clean, structured
    FAILED payslip — never an unhandled 500."""

    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_INTERNAL_TARIFF_NOT_AVAILABLE", message, trace)


# Effective-dated tariff registry — deliberately structured as a real,
# date-scoped list (even with only one entry today) rather than bare
# module constants, so a future phase that source-verifies a later
# assessment year's exact zone coefficients adds a second entry (a pure
# data change) instead of redesigning this resolution mechanism. Mirrors
# this Germany jurisdiction's own established pattern (Phase 8BK's
# Minijob/Midijob parameter registry started exactly this way: one
# hardcoded version first, registry-ized once more versions existed).
_TARIFF_VERSIONS = [
    {
        "tax_year": TAX_YEAR_LABEL,
        "effective_from": date(2023, 1, 1),
        "effective_to": None,  # open-ended: the most recent verified tariff, still applies until a newer one is added
        "grundfreibetrag": _GRUNDFREIBETRAG,
        "zone2_upper": _ZONE2_UPPER, "zone3_upper": _ZONE3_UPPER, "zone4_upper": _ZONE4_UPPER,
        "zone2_a": _ZONE2_A, "zone2_b": _ZONE2_B,
        "zone3_a": _ZONE3_A, "zone3_b": _ZONE3_B, "zone3_c": _ZONE3_C,
        "zone4_rate": _ZONE4_RATE, "zone4_sub": _ZONE4_SUB,
        "zone5_rate": _ZONE5_RATE, "zone5_sub": _ZONE5_SUB,
        "source": "section 32a EStG, 2023 assessment year (BGBl. 2022 I S. 2230)",
    },
]


def resolve_income_tax_tariff(payroll_date: "date") -> dict:
    """Resolves the tariff version effective for `payroll_date` — the
    payroll RUN's pay date, never wall-clock today() (matching every other
    effective-dated resolution in this Germany jurisdiction). Raises
    GermanyInternalTariffNotAvailableError for any date this module has no
    verified version for, rather than silently reusing the nearest one."""
    for version in _TARIFF_VERSIONS:
        if payroll_date < version["effective_from"]:
            continue
        if version["effective_to"] is not None and payroll_date >= version["effective_to"]:
            continue
        return version
    raise GermanyInternalTariffNotAvailableError(
        f"No verified internal EStG section 32a tariff is available for payroll date {payroll_date} — "
        f"this module's earliest verified version is effective from {_TARIFF_VERSIONS[0]['effective_from']}. "
        "Refusing to guess an earlier tariff's zone coefficients rather than risk an unverified figure."
    )


def compute_grundtarif_annual_tax(zve: Decimal, tariff: dict = None) -> Decimal:
    """The unmodified section 32a EStG zone tariff (Grundtarif) — Tax
    Classes I/II/IV/VI (VI without any prior deduction applied) and the
    per-half computation inside Splittingverfahren (Class III) all reduce
    to this same function. `tariff` is a resolved version dict from
    `resolve_income_tax_tariff()`/`_TARIFF_VERSIONS`; defaults to this
    module's only version (the 2023 constants) so every pre-existing call
    site and test that doesn't pass a date-resolved tariff keeps working
    unchanged."""
    t = tariff or _TARIFF_VERSIONS[0]
    zve = _floor_euro(max(Decimal("0"), zve))
    grundfreibetrag = t["grundfreibetrag"]
    if zve <= grundfreibetrag:
        return Decimal("0")
    if zve <= t["zone2_upper"]:
        y = (zve - grundfreibetrag) / Decimal("10000")
        tax = (t["zone2_a"] * y + t["zone2_b"]) * y
    elif zve <= t["zone3_upper"]:
        z = (zve - t["zone2_upper"]) / Decimal("10000")
        tax = (t["zone3_a"] * z + t["zone3_b"]) * z + t["zone3_c"]
    elif zve <= t["zone4_upper"]:
        tax = t["zone4_rate"] * zve - t["zone4_sub"]
    else:
        tax = t["zone5_rate"] * zve - t["zone5_sub"]
    return _floor_euro(tax)


def compute_tax_for_class(zve: Decimal, tax_class: str, tariff: dict = None) -> Decimal:
    """Applies the class-specific tariff MECHANICS (not allowances — those
    are subtracted from `zve` by the caller before this is invoked) —
    i.e. only the Splittingverfahren halving/doubling of section 32a Abs.
    5 EStG for Class III: HALVE the (assumed-joint) income, apply the
    ordinary tariff, then DOUBLE the result — never the other way around.
    Since the tariff is progressive (convex), halving first and doubling
    after always yields LESS tax than the plain Grundtarif on the same
    zvE (the whole point of Splitting) — computing tariff(2x)/2 instead
    would produce MORE tax, the opposite of the statute. Every other
    class uses the plain Grundtarif."""
    if tax_class == "III":
        return 2 * compute_grundtarif_annual_tax(zve / 2, tariff)
    return compute_grundtarif_annual_tax(zve, tariff)


def compute_soli(base_tax: Decimal, is_splitting: bool, soli_threshold_single: Decimal, soli_rate_pct: Decimal) -> Decimal:
    """SolzG 1995 sections 3-4: exempt below the Freigrenze, full rate
    above the Milderungszone, capped at the mitigation-zone amount in
    between. `soli_threshold_single` is the caller-resolved single-filer
    threshold (already present in this codebase as `_DE_SOLI_THRESHOLD`);
    doubled here for Splitting per SolzG section 3 Abs. 3."""
    threshold = soli_threshold_single * 2 if is_splitting else soli_threshold_single
    if base_tax <= threshold:
        return Decimal("0")
    full_rate_soli = base_tax * soli_rate_pct / Decimal("100")
    mitigation_soli = (base_tax - threshold) * SOLI_MILDERUNGSZONE_RATE / Decimal("100")
    return _round_cents(min(full_rate_soli, mitigation_soli))


@dataclass
class InternalTaxBreakdown:
    """Full calculation trace for the internal wage-tax path — surfaced
    onto GermanyCalculationTrace so the same auditability/diagnosability
    this Germany jurisdiction already gives PAP output also applies here."""

    annual_wage_before_deductions: Decimal
    arbeitnehmer_pauschbetrag: Decimal
    sonderausgaben_pauschbetrag: Decimal
    vorsorgepauschale_proxy: Decimal
    # section 24b EStG, Tax Class II only — 0 for every other class.
    # Tracked as its own field (not folded silently into
    # arbeitnehmer_pauschbetrag) so it is independently traceable end to
    # end, per this codebase's "no silent drops" standard.
    entlastungsbetrag_alleinerziehende: Decimal
    zve_for_lohnsteuer: Decimal
    zve_for_surcharges: Decimal
    annual_lohnsteuer: Decimal
    annual_surcharge_base_tax: Decimal
    annual_soli: Decimal
    tax_class: str
    warnings: list
    # Structured (not prose-embedded) disclosure of every simplification
    # applied to THIS specific calculation — a consumer that wants to
    # detect "was any approximation used" programmatically (e.g. to flag
    # a payslip for review) should read this list, not regex the
    # `warnings` text. Empty for Tax Classes I/III/IV with no children
    # (fully faithful to the statute); non-empty for II/V/VI.
    approximation_codes: list


def compute_entlastungsbetrag_alleinerziehende(child_count: int) -> Decimal:
    """section 24b Abs. 2 EStG: EUR 4,260/year for the first child, plus
    EUR 240/year for each additional child in the same household. Tax
    Class II ITSELF is the eligibility signal under German law (section
    38b Abs. 1 Nr. 2 EStG — the Finanzamt only assigns Class II to an
    employee already meeting the Entlastungsbetrag criteria), so this
    function takes no separate eligibility flag; the caller only invokes
    it for tax_class == "II". `child_count` <= 0 returns 0 (defensively —
    Class II without any recorded child would itself be a data
    inconsistency the profile layer should catch, not something this
    calculator should paper over with a fabricated relief amount)."""
    if child_count <= 0:
        return Decimal("0")
    additional_children = max(0, child_count - 1)
    return (
        ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_BASE
        + additional_children * ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_PER_ADDITIONAL_CHILD
    )


def _class_allowances(tax_class: str, arbeitnehmer_pauschbetrag: Decimal, sonderausgaben_pauschbetrag: Decimal,
                       vorsorgepauschale_proxy: Decimal, child_count: int = 0) -> tuple[Decimal, list, list]:
    """Returns (total_allowance, warnings, approximation_codes) for the
    wage-tax base — the class-specific allowance rule documented in this
    module's docstring (limitation #3). `approximation_codes` is the
    STRUCTURED counterpart to the prose `warnings` — a consumer that wants
    to detect "was any approximation applied" programmatically should read
    this list, never regex the warning text."""
    warnings: list = []
    if tax_class == "VI":
        warnings.append(
            "GERMANY_TAX_CLASS_V_VI_APPROXIMATE: Tax Class VI receives NO allowances in this internal "
            "calculator (Arbeitnehmer-Pauschbetrag/Sonderausgaben-Pauschbetrag/Vorsorgepauschale all "
            "excluded), matching the statutory 'no allowances' characterization of Class VI, but the "
            "certified BMF PAP applies a materially more complex multiplying procedure for VI wage-tax "
            "cards that this module does not replicate exactly."
        )
        return Decimal("0"), warnings, ["GERMANY_TAX_CLASS_V_VI_APPROXIMATE"]
    if tax_class == "V":
        warnings.append(
            "GERMANY_TAX_CLASS_V_VI_APPROXIMATE: Tax Class V receives ONLY the Vorsorgepauschale proxy "
            "in this internal calculator (no Arbeitnehmer-Pauschbetrag/Sonderausgaben-Pauschbetrag/child "
            "allowance) — the certified BMF PAP applies a materially more complex multiplying procedure "
            "for Class V wage-tax cards that this module does not replicate exactly."
        )
        return vorsorgepauschale_proxy, warnings, ["GERMANY_TAX_CLASS_V_VI_APPROXIMATE"]
    if tax_class == "II":
        entlastungsbetrag = compute_entlastungsbetrag_alleinerziehende(child_count)
        if entlastungsbetrag == 0:
            warnings.append(
                "GERMANY_TAX_CLASS_II_NO_CHILD_RECORDED: Tax Class II ordinarily implies Entlastungsbetrag "
                "fuer Alleinerziehende eligibility (section 38b Abs. 1 Nr. 2 EStG), but "
                "EmployeeStatutoryProfile.de_child_count is 0/unset for this employee, so no relief amount "
                "could be computed — verify the employee's child count is recorded correctly."
            )
            return arbeitnehmer_pauschbetrag + sonderausgaben_pauschbetrag + vorsorgepauschale_proxy, warnings, [
                "GERMANY_TAX_CLASS_II_NO_CHILD_RECORDED",
            ]
        warnings.append(
            f"GERMANY_TAX_CLASS_II_ENTLASTUNGSBETRAG_APPLIED: section 24b EStG Entlastungsbetrag fuer "
            f"Alleinerziehende of EUR {entlastungsbetrag}/year applied (EUR "
            f"{ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_BASE} base + EUR "
            f"{max(0, child_count - 1) * ENTLASTUNGSBETRAG_ALLEINERZIEHENDE_PER_ADDITIONAL_CHILD} for "
            f"{max(0, child_count - 1)} additional child(ren)), derived from de_child_count={child_count}."
        )
        return (
            arbeitnehmer_pauschbetrag + sonderausgaben_pauschbetrag + vorsorgepauschale_proxy + entlastungsbetrag,
            warnings, [],
        )
    return arbeitnehmer_pauschbetrag + sonderausgaben_pauschbetrag + vorsorgepauschale_proxy, warnings, []


def calculate_internal_wage_tax(
    *, tax_class: str, zkf: Decimal, annual_wage: Decimal, vorsorgepauschale_proxy: Decimal,
    soli_threshold_single: Decimal, soli_rate_pct: Decimal, tariff: dict = None, child_count: int = 0,
) -> InternalTaxBreakdown:
    """Pure function (no I/O, deterministic, Decimal-only) implementing
    this module's whole internal wage-tax/Soli procedure. `annual_wage` is
    the caller's already-fully-assembled ELStAM-adjusted annual wage
    (regular + SONSTB + JHINZU/LZZHINZU - JFREIB/LZZFREIB, per
    build_pap_input's own documented field sources) — this function does
    not re-derive it from PapInputContract directly, so it stays testable
    independent of the PAP input-contract shape. `tariff` is a resolved
    version dict from `resolve_income_tax_tariff()`; defaults to this
    module's only version when the caller has no payroll date to resolve
    against (e.g. a unit test), so every pre-existing call site keeps
    working unchanged."""
    tax_class = (tax_class or "I").upper()
    resolved_tariff = tariff or _TARIFF_VERSIONS[0]
    warnings: list = [
        f"INTERNAL_FUNCTIONAL_REFERENCE: computed via section 32a/39b EStG {resolved_tariff['tax_year']} tariff, "
        "NOT the certified BMF Programmablaufplan (PAP). Not suitable as an official/certified withholding "
        "figure without independent verification.",
    ]

    approximation_codes: list = ["GERMANY_TARIFF_YEAR_NOT_CURRENT"]
    lohnsteuer_allowance, class_warnings, class_approximation_codes = _class_allowances(
        tax_class, ARBEITNEHMER_PAUSCHBETRAG, SONDERAUSGABEN_PAUSCHBETRAG, vorsorgepauschale_proxy, child_count,
    )
    warnings.extend(class_warnings)
    approximation_codes.extend(class_approximation_codes)
    if tax_class != "VI" and vorsorgepauschale_proxy > 0:
        approximation_codes.append("GERMANY_VORSORGEPAUSCHALE_PROXY_APPROXIMATE")
    entlastungsbetrag = compute_entlastungsbetrag_alleinerziehende(child_count) if tax_class == "II" else Decimal("0")

    zve_for_lohnsteuer = annual_wage - lohnsteuer_allowance
    annual_lohnsteuer = compute_tax_for_class(zve_for_lohnsteuer, tax_class, resolved_tariff)

    # section 51a EStG: Soli/Kirchensteuer use a SEPARATE assessment base
    # that additionally subtracts the child allowance (ZKF), even though
    # ZKF never reduces the wage-tax withholding base itself above.
    child_allowance = (zkf or Decimal("0")) * KINDERFREIBETRAG_PLUS_BEA
    zve_for_surcharges = zve_for_lohnsteuer - child_allowance
    annual_surcharge_base_tax = compute_tax_for_class(zve_for_surcharges, tax_class, resolved_tariff)

    annual_soli = compute_soli(
        annual_surcharge_base_tax, is_splitting=(tax_class == "III"),
        soli_threshold_single=soli_threshold_single, soli_rate_pct=soli_rate_pct,
    )

    return InternalTaxBreakdown(
        annual_wage_before_deductions=annual_wage,
        arbeitnehmer_pauschbetrag=(ARBEITNEHMER_PAUSCHBETRAG if tax_class not in ("V", "VI") else Decimal("0")),
        sonderausgaben_pauschbetrag=(SONDERAUSGABEN_PAUSCHBETRAG if tax_class not in ("V", "VI") else Decimal("0")),
        vorsorgepauschale_proxy=vorsorgepauschale_proxy if tax_class != "VI" else Decimal("0"),
        entlastungsbetrag_alleinerziehende=entlastungsbetrag,
        zve_for_lohnsteuer=zve_for_lohnsteuer,
        zve_for_surcharges=zve_for_surcharges,
        annual_lohnsteuer=annual_lohnsteuer,
        annual_surcharge_base_tax=annual_surcharge_base_tax,
        annual_soli=annual_soli,
        tax_class=tax_class,
        warnings=warnings,
        approximation_codes=approximation_codes,
    )


class InternalGermanyWageTaxCalculator(PapExecutor):
    """A PapExecutor implementation — same interface the future certified
    PAP executor will one day implement — backed by this module's internal
    statutory-formula calculator instead of the certified BMF artifact.
    Deliberately a DIFFERENT concrete class from UnavailablePapExecutor:
    `resolve_pap_executor()` (germany_pap/core.py) is untouched and still
    always returns UnavailablePapExecutor for the *official* PAP path —
    see countries/germany.py's calculate(), which now catches
    GermanyPapNotAvailableError specifically and falls back to THIS
    executor, rather than this class being reachable through
    resolve_pap_executor() itself. This keeps the 'official PAP resolution'
    and 'internal functional fallback' concerns cleanly separated, per
    this phase's explicit instruction not to conflate the two."""

    def __init__(self, *, soli_threshold_single: Decimal, soli_rate_pct: Decimal, payroll_date: "date" = None):
        self._soli_threshold_single = soli_threshold_single
        self._soli_rate_pct = soli_rate_pct
        # Phase 8BS: the tariff itself is now resolved against the
        # payroll RUN's pay date (never wall-clock today()) via
        # resolve_income_tax_tariff() — a real effective-dating mechanism
        # (see _TARIFF_VERSIONS), even though only one verified version
        # exists today. `None` falls back to that one version directly
        # (e.g. a caller/test with no real payroll date), matching every
        # pre-existing call site's behavior unchanged.
        self._tariff = resolve_income_tax_tariff(payroll_date) if payroll_date is not None else _TARIFF_VERSIONS[0]

    def execute(self, pap_input: PapInputContract) -> GermanyPapCalculationResult:
        regular_wage_annual = Decimal(pap_input.re4_cents) / 100 * 12
        sonstb_annual = Decimal(pap_input.sonstb_cents) / 100
        jhinzu = Decimal(pap_input.jhinzu_cents) / 100
        lzzhinzu_annual = Decimal(pap_input.lzzhinzu_cents) / 100 * 12
        jfreib = Decimal(pap_input.jfreib_cents) / 100
        lzzfreib_annual = Decimal(pap_input.lzzfreib_cents) / 100 * 12

        annual_wage = (
            regular_wage_annual + sonstb_annual + jhinzu + lzzhinzu_annual - jfreib - lzzfreib_annual
        )
        vorsorgepauschale_proxy = Decimal(getattr(pap_input, "vorsorgepauschale_annual_cents", 0)) / 100

        breakdown = calculate_internal_wage_tax(
            tax_class=pap_input.stkl, zkf=pap_input.zkf, annual_wage=annual_wage,
            vorsorgepauschale_proxy=vorsorgepauschale_proxy,
            soli_threshold_single=self._soli_threshold_single, soli_rate_pct=self._soli_rate_pct,
            tariff=self._tariff, child_count=getattr(pap_input, "child_count", 0),
        )

        return GermanyPapCalculationResult(
            # Dynamic on the resolved tariff's own tax year — stays
            # accurate automatically if a future phase adds a newer
            # verified tariff version rather than silently going stale.
            pap_version=f"INTERNAL_FUNCTIONAL_REFERENCE-ESTG32A-{self._tariff['tax_year'].split('-')[0]}",
            pap_hash=None,
            pap_build_identifier="internal-tax-calculator-v1",
            input_reference=pap_input.field_sources(),
            lohnsteuer=breakdown.annual_lohnsteuer,
            soli=breakdown.annual_soli,
            church_tax_assessment_base=breakdown.annual_surcharge_base_tax,
            raw_outputs={
                "ZVE_LOHNSTEUER": str(breakdown.zve_for_lohnsteuer),
                "ZVE_SURCHARGES": str(breakdown.zve_for_surcharges),
                "VORSORGEPAUSCHALE_PROXY": str(breakdown.vorsorgepauschale_proxy),
                "ARBEITNEHMER_PAUSCHBETRAG": str(breakdown.arbeitnehmer_pauschbetrag),
                "SONDERAUSGABEN_PAUSCHBETRAG": str(breakdown.sonderausgaben_pauschbetrag),
                "ENTLASTUNGSBETRAG_ALLEINERZIEHENDE": str(breakdown.entlastungsbetrag_alleinerziehende),
                "TAX_YEAR": self._tariff["tax_year"],
                "TARIFF_EFFECTIVE_FROM": str(self._tariff["effective_from"]),
                # Structured (non-prose) disclosure — a comma-joined string
                # since raw_outputs is a flat str->str dict; see
                # calculate_internal_wage_tax's own docstring for the
                # canonical list source (InternalTaxBreakdown.approximation_codes).
                "REFERENCE_APPROXIMATION": ",".join(breakdown.approximation_codes) if breakdown.approximation_codes else "NONE",
            },
            calculation_status="COMPLETE",
            calculation_trace=None,
            warnings=breakdown.warnings,
            errors=[],
        )
