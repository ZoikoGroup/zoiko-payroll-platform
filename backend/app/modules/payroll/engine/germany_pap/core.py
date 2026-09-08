"""
modules/payroll/engine/germany_pap/core.py
----------------------------------------------
Phase 7 — Germany BMF PAP execution scaffolding + the real, non-PAP,
branch-aware social-insurance (RV/ALV/GKV/PV) calculations, per
ZP-TAX-DE-2026-001.

This is the production Germany statutory-support core of the Germany BMF
PAP subsystem package (`engine/germany_pap/`). Relocated from
`engine/countries/germany_pap.py` in Phase 8E-0A so that
`engine/countries/` holds exactly one canonical country calculator per
jurisdiction (there, `germany.py`); this module is imported by
`countries/germany.py`, by `payroll/service.py`, and by the other
`germany_pap/` sub-modules (interpreter/adapter), never by
`_COUNTRY_CALC`.

PAP SOURCE AVAILABILITY (checked at the start of Phase 7, re-confirmed by
this module's own tests): no BMF 2026 machine PAP source/asset exists
anywhere in this repository, and none has ever been ingested into
PapAlgorithmAsset (the registry is empty in every environment this phase
touched). The supplied Germany specification itself only *references* the
official PAP by publication metadata/URL (§5, §24 Source Register) — it
does not embed the algorithm. Per this phase's explicit "Absolute PAP
Rule": since no real source exists, this module does NOT implement PAP
execution. It implements only the safe boundary — a typed input contract,
an executor *interface*, and a concrete executor that deterministically
reports the block. `resolve_pap_executor()` always returns
`UnavailablePapExecutor` today; a future phase that ingests+approves a
real PAP source must implement a concrete `PapExecutor` and swap it in
here — no other call site should need to change.

This module also implements the four social-insurance branches
(RV/ALV/GKV/PV) for real, because — unlike Lohnsteuer/Soli/Kirchensteuer,
which the spec explicitly requires to be PAP output, not a standalone
formula (§7 "Use PAP output... not a standalone simple 5.5%
multiplication") — RV/ALV/GKV/PV are ordinary percentage-of-capped-wage
contributions with 2026 rates and ceilings the supplied documentation
states explicitly (§9, §10). Computing them does not require inventing or
approximating the PAP.

Known, disclosed scope boundary (re-investigated live, Phase 8L §10-13):
the "reduced" GKV rate (14.00%/7.00%/7.00%) applies, per §243 SGB V, only
to insured persons with NO statutory sick-pay (Krankengeld) entitlement —
confirmed via live research to mean specifically pre-retirement-payment
recipients (Vorruhestandsgeld) and full old-age/occupational-disability
pensioners, never an ordinary active employee. Every employee this
module's "ordinary active employee" scope covers (Phases 2/6/7/8I/8J)
always has statutory Krankengeld entitlement and is therefore always
subject to the general rate — the reduced rate is correctly excluded BY
DEFINITION for this scope, not merely unimplemented, so no
EmployeeStatutoryProfile field was added for it (adding one would invite
selecting a rate that can never legally apply to this module's
population).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


def _r2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── Church tax — Land overlay (ZP-TAX-DE-2026-001 §8) ───────────────────
# Literal 2026 rates from the supplied specification. Keys use the same
# "DE-<ISO 3166-2 subdivision>" convention as
# EmployeeStatutoryProfile.de_church_tax_land's own column comment.
# Baden-Württemberg carries a documented denomination/location exception
# (Bad Wimpfen Roman Catholic treatment) that the spec explicitly says the
# jurisdiction asset "must allow... rather than assuming the general Land
# rate is universal" — NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION as a
# machine-readable exception rule (no exception list/schema is given), so
# it is not implemented; only the general Land rate is applied, and this
# gap is disclosed rather than silently ignored.
CHURCH_TAX_LAND_RATES: dict[str, Decimal] = {
    "DE-BW": Decimal("8"),   # Baden-Württemberg (general rate; see docstring)
    "DE-BY": Decimal("8"),   # Bavaria
    "DE-BE": Decimal("9"),   # Berlin
    "DE-BB": Decimal("9"),   # Brandenburg
    "DE-HB": Decimal("9"),   # Bremen
    "DE-HH": Decimal("9"),   # Hamburg
    "DE-HE": Decimal("9"),   # Hesse
    "DE-MV": Decimal("9"),   # Mecklenburg-Western Pomerania
    "DE-NI": Decimal("9"),   # Lower Saxony
    "DE-NW": Decimal("9"),   # North Rhine-Westphalia
    "DE-RP": Decimal("9"),   # Rhineland-Palatinate
    "DE-SL": Decimal("9"),   # Saarland
    "DE-SN": Decimal("9"),   # Saxony
    "DE-ST": Decimal("9"),   # Saxony-Anhalt
    "DE-SH": Decimal("9"),   # Schleswig-Holstein
    "DE-TH": Decimal("9"),   # Thuringia
}

_GERMANY_PV_CHILD_CATEGORIES = ("CHILDLESS", "1", "2", "3", "4", "5_PLUS")


# ── Exceptions ───────────────────────────────────────────────────────────
# Plain-Python, framework-agnostic (this package has zero FastAPI/ORM
# dependency, matching every other engine/countries/*.py module) — the
# service layer is responsible for translating these into an HTTP error
# (see service.py's germany calculation call sites /
# core.exceptions.GermanyCalculationBlockedException).

class GermanyCalculationError(Exception):
    """Base: the Germany calculation cannot safely produce a compliant
    result. Carries a stable `code` (for API/log consumers) and a
    `trace` — whatever GermanyCalculationTrace had accumulated before the
    blocking condition was hit, so the caller can see exactly which
    branches DID resolve and which one blocked, rather than a bare
    failure with no diagnostic value."""

    def __init__(self, code: str, message: str, trace: Optional["GermanyCalculationTrace"] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.trace = trace


class GermanyStatutoryProfileMissingError(GermanyCalculationError):
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_STATUTORY_PROFILE_MISSING", message, trace)


class GermanyPapNotAvailableError(GermanyCalculationError):
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_PAP_NOT_AVAILABLE", message, trace)


class GermanyPapInvalidError(GermanyCalculationError):
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_PAP_INVALID", message, trace)


class GermanyHealthFundNotAvailableError(GermanyCalculationError):
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_HEALTH_FUND_NOT_AVAILABLE", message, trace)


class GermanyCeilingNotAvailableError(GermanyCalculationError):
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_CEILING_NOT_AVAILABLE", message, trace)


class GermanyPvConfigurationNotAvailableError(GermanyCalculationError):
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_PV_CONFIGURATION_NOT_AVAILABLE", message, trace)


class GermanyUnsupportedEmploymentClassificationError(GermanyCalculationError):
    """Retained for any caller that still names it directly; no longer
    raised by countries/germany.py's calculate() now that Minijob/Midijob
    have a real implementation (Phase 8I) — kept because prior test/report
    references may still exist and this class was never documented as
    removable."""
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_MINIJOB_MIDIJOB_NOT_IMPLEMENTED", message, trace)


class GermanyInvalidEmploymentClassificationError(GermanyCalculationError):
    """de_employment_classification holds a value outside the known
    {REGULAR, MINIJOB, MIDIJOB} vocabulary (Phase 8I §8) — fails closed
    rather than silently treating an unrecognized value as REGULAR."""
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_INVALID_EMPLOYMENT_CLASSIFICATION", message, trace)


class GermanyMinijobThresholdViolationError(GermanyCalculationError):
    """Employee is classified MINIJOB but this period's earnings exceed
    the Minijob upper threshold (Phase 8I §10) — the classification is a
    statutory/employment attribute of the employee, not something this
    engine may silently reclassify based on one month's pay."""
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_MINIJOB_THRESHOLD_VIOLATION", message, trace)


class GermanyMidijobThresholdViolationError(GermanyCalculationError):
    """Employee is classified MIDIJOB but this period's earnings fall
    outside the Midijob corridor (Phase 8I §10)."""
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_MIDIJOB_THRESHOLD_VIOLATION", message, trace)


class GermanyMidijobPvChildlessSaxonyNotSpecifiedError(GermanyCalculationError):
    """Phase 8J raised this for Saxony+childless Midijob PV because its
    derivation of the childless surcharge (CHILDLESS row's own
    employee_rate - employer_rate) is only valid for non-Saxony rows —
    for Saxony it would conflate the surcharge with Saxony's own separate
    employee-only PV premium (§58 Abs. 3 SGB XI). Phase 8L resolved this
    by fetching the primary statutory text directly: §55 Abs. 3 SGB XI
    fixes the childless surcharge at a flat, Land-independent 0.6
    contribution-rate points, so it no longer needs to be derived by
    subtraction at all (see calculate_midijob_pv() and
    hardcoded_defaults._DE_PV_CHILDLESS_SURCHARGE_RATE). No longer
    raised by any production code path — retained (not deleted) in case
    any external caller/report still names it directly, matching this
    codebase's convention for superseded exception classes."""
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_MIDIJOB_PV_CHILDLESS_SAXONY_NOT_SPECIFIED", message, trace)


class GermanyVocationalTraineeMidijobExclusionError(GermanyCalculationError):
    """Phase 8L. §20 Abs. 2a Satz 9 SGB IV excludes anyone employed "zu
    ihrer Berufsausbildung" (Ausbildungsvertrag, Praktikum zur
    Berufsausbildung, duales Studium) from the Übergangsbereich (Midijob)
    regime, regardless of whether their earnings fall inside the
    corridor — confirmed by BSG ruling 15.07.2009. Fails closed rather
    than silently reclassifying, matching every other employment-
    classification guard in this module. Already rejected at write time
    (service._validate_statutory_profile_fields) — this calculation-time
    check exists for any profile row written before that validation
    existed, or written directly against the DB."""
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_VOCATIONAL_TRAINEE_MIDIJOB_EXCLUSION", message, trace)


class GermanyMidijobBaseApplicationNotSpecifiedError(GermanyCalculationError):
    """The supplied Germany 2026 documentation gives exactly two Midijob
    sliding-scale contribution-base formulas (a combined "total" base and
    a combined "employee" base) but does not specify how those two
    aggregate figures are individually apportioned across the four
    independently-rated, independently-ceilinged RV/ALV/GKV/PV branches
    each already implemented by this module for the REGULAR path. Rather
    than inventing a per-branch allocation rule (Phase 8I's own explicit
    "do not reinterpret these formulas without evidence" instruction),
    this fails closed — see calculate_midijob_total_base/
    calculate_midijob_employee_base, which ARE implemented and exercised,
    for the part that genuinely is specified."""
    def __init__(self, message: str, trace=None):
        super().__init__("GERMANY_MIDIJOB_BASE_UNAVAILABLE", message, trace)


# ── Calculation trace (spec §14 / this phase's §14) ─────────────────────

@dataclass
class GermanyCalculationTrace:
    """Structured, append-only record of what this calculation actually
    did — answers every question this phase's §14 lists, minus anything
    that would leak secrets or unnecessary personal data (no bank
    details, no raw IBAN/Steuer-ID are stored here; identifiers only)."""

    employee_id: Optional[int] = None
    organization_id: Optional[int] = None
    payroll_date: Optional[str] = None
    country_code: str = "DE"

    statutory_profile_id: Optional[int] = None
    statutory_profile_effective_from: Optional[str] = None

    # ── Employment classification (Phase 8I) ──
    employment_classification: Optional[str] = None
    monthly_gross_used: Optional[str] = None
    midijob_total_contribution_base: Optional[str] = None
    midijob_employee_contribution_base: Optional[str] = None
    accident_insurance_status: Optional[str] = None

    # ── Phase 8X: earning taxability (spec §15) ─────────────────────────
    # Human-readable summary of the four-dimension classification applied
    # to each earning type that actually entered this run. Always set —
    # "NOT_CONFIGURED" when no PUBLISHED rule existed for an earning type.
    earning_taxability_status: Optional[str] = None
    # Structured, JSON-safe mirror of the classification per earning type —
    # earning_type -> {status, recordId, effectiveFrom, wageTaxTreatment,
    # gkvPvTreatment, rvAlvTreatment, reportingClassification,
    # sourceArtifactId}. Absent/unpublished -> status "NOT_CONFIGURED".
    earning_taxability_detail: Optional[dict] = None

    # ── Tax-data provenance (Phase 8K) ── the ELStAM/manually-entered
    # values actually fed into PapInputContract, so a historical
    # calculation stays reproducible even though PAP itself is blocked.
    # Never a raw Steuer-ID; only the fields already stored on
    # EmployeeStatutoryProfile that this calculation actually read.
    elstam_source: Optional[str] = None
    elstam_fallback_reason: Optional[str] = None
    tax_class_used: Optional[str] = None
    factor_used: Optional[str] = None
    zkf_used: Optional[str] = None
    church_tax_liable_used: Optional[bool] = None

    # ── Phase 8N: ELStAM / employee-withholding-state completion ────────
    jfreib_used: Optional[str] = None
    lzzfreib_used: Optional[str] = None
    jhinzu_used: Optional[str] = None
    lzzhinzu_used: Optional[str] = None
    pkpv_used: Optional[str] = None
    pkpvagz_used: Optional[str] = None
    main_employment_used: Optional[bool] = None

    # ── Phase 8T: bonus/SONSTB routing ──────────────────────────────────
    sonstb_used: Optional[str] = None          # bonus amount actually routed via SONSTB this period (str(Decimal), always set — "0" is a legitimate value, not "unset")
    jre4_used: Optional[str] = None            # None when no bonus this period (JRE4 not applicable then)
    regular_wage_used: Optional[str] = None    # RE4 basis actually fed to the PAP (gross minus sonstb)

    pap_asset_id: Optional[int] = None
    pap_version: Optional[str] = None
    pap_source_content_sha256: Optional[str] = None
    pap_build_identifier: Optional[str] = None
    pap_tax_year: Optional[str] = None

    health_fund_record_id: Optional[int] = None
    health_fund_id: Optional[str] = None
    health_fund_supplementary_rate_pct: Optional[str] = None
    health_fund_name: Optional[str] = None
    health_fund_effective_from: Optional[str] = None
    health_fund_is_average_rate: Optional[bool] = None

    ceiling_gkv_pv_id: Optional[int] = None
    ceiling_rv_alv_id: Optional[int] = None

    ceiling_gkv_pv_monthly: Optional[str] = None
    ceiling_gkv_pv_annual: Optional[str] = None
    ceiling_rv_alv_monthly: Optional[str] = None
    ceiling_rv_alv_annual: Optional[str] = None

    pv_configuration_id: Optional[int] = None
    pv_child_category: Optional[str] = None
    pv_is_saxony: Optional[bool] = None
    pv_configuration_effective_from: Optional[str] = None
    pv_configuration_total_rate_pct: Optional[str] = None
    pv_configuration_standard_employee_rate_pct: Optional[str] = None
    pv_configuration_employer_rate_pct: Optional[str] = None
    pv_configuration_saxony_employee_rate_pct: Optional[str] = None
    pv_configuration_saxony_employer_rate_pct: Optional[str] = None

    steps: list = field(default_factory=list)     # ordered list[str] — human-readable step log
    resolved: dict = field(default_factory=dict)   # branch name -> resolved Decimal amounts (as str)
    warnings: list = field(default_factory=list)
    calculation_status: str = "IN_PROGRESS"        # IN_PROGRESS | COMPLETE | BLOCKED
    blocked_reason_code: Optional[str] = None
    blocked_reason_message: Optional[str] = None

    def step(self, message: str) -> None:
        self.steps.append(message)

    def resolve_ok(self, branch: str, **amounts) -> None:
        self.resolved[branch] = {k: str(v) for k, v in amounts.items()}

    def to_dict(self) -> dict:
        return {
            "employeeId": self.employee_id,
            "organizationId": self.organization_id,
            "payrollDate": self.payroll_date,
            "countryCode": self.country_code,
            "statutoryProfileId": self.statutory_profile_id,
            "statutoryProfileEffectiveFrom": self.statutory_profile_effective_from,
            "papAssetId": self.pap_asset_id,
            "papVersion": self.pap_version,
            "papSourceContentSha256": self.pap_source_content_sha256,
            "papBuildIdentifier": self.pap_build_identifier,
            "papTaxYear": self.pap_tax_year,
            "healthFundRecordId": self.health_fund_record_id,
            "healthFundId": self.health_fund_id,
            "healthFundSupplementaryRatePct": self.health_fund_supplementary_rate_pct,
            "healthFundName": self.health_fund_name,
            "healthFundEffectiveFrom": self.health_fund_effective_from,
            "healthFundIsAverageRate": self.health_fund_is_average_rate,
            "ceilingGkvPvId": self.ceiling_gkv_pv_id,
            "ceilingRvAlvId": self.ceiling_rv_alv_id,
            "ceilingGkvPvMonthly": self.ceiling_gkv_pv_monthly,
            "ceilingGkvPvAnnual": self.ceiling_gkv_pv_annual,
            "ceilingRvAlvMonthly": self.ceiling_rv_alv_monthly,
            "ceilingRvAlvAnnual": self.ceiling_rv_alv_annual,
            "pvConfigurationId": self.pv_configuration_id,
            "pvChildCategory": self.pv_child_category,
            "pvIsSaxony": self.pv_is_saxony,
            "pvConfigurationEffectiveFrom": self.pv_configuration_effective_from,
            "pvConfigurationTotalRatePct": self.pv_configuration_total_rate_pct,
            "pvConfigurationStandardEmployeeRatePct": self.pv_configuration_standard_employee_rate_pct,
            "pvConfigurationEmployerRatePct": self.pv_configuration_employer_rate_pct,
            "pvConfigurationSaxonyEmployeeRatePct": self.pv_configuration_saxony_employee_rate_pct,
            "pvConfigurationSaxonyEmployerRatePct": self.pv_configuration_saxony_employer_rate_pct,
            "employmentClassification": self.employment_classification,
            "monthlyGrossUsed": self.monthly_gross_used,
            "midijobTotalContributionBase": self.midijob_total_contribution_base,
            "midijobEmployeeContributionBase": self.midijob_employee_contribution_base,
            "accidentInsuranceStatus": self.accident_insurance_status,
            "earningTaxabilityStatus": self.earning_taxability_status,
            "earningTaxabilityDetail": self.earning_taxability_detail,
            "elstamSource": self.elstam_source,
            "elstamFallbackReason": self.elstam_fallback_reason,
            "taxClassUsed": self.tax_class_used,
            "factorUsed": self.factor_used,
            "zkfUsed": self.zkf_used,
            "churchTaxLiableUsed": self.church_tax_liable_used,
            "jfreibUsed": self.jfreib_used,
            "lzzfreibUsed": self.lzzfreib_used,
            "jhinzuUsed": self.jhinzu_used,
            "lzzhinzuUsed": self.lzzhinzu_used,
            "pkpvUsed": self.pkpv_used,
            "pkpvagzUsed": self.pkpvagz_used,
            "mainEmploymentUsed": self.main_employment_used,
            "sonstbUsed": self.sonstb_used,
            "jre4Used": self.jre4_used,
            "regularWageUsed": self.regular_wage_used,
            "steps": list(self.steps),
            "resolved": dict(self.resolved),
            "warnings": list(self.warnings),
            "calculationStatus": self.calculation_status,
            "blockedReasonCode": self.blocked_reason_code,
            "blockedReasonMessage": self.blocked_reason_message,
        }


# ── PAP input contract (spec §5, this phase's §9) ───────────────────────

@dataclass
class PapInputContract:
    """Typed representation of the BMF PAP's documented input fields
    (ZP-TAX-DE-2026-001 §5). Every field's source is documented on the
    field itself — never a bare unlabeled value — per this phase's
    explicit instruction. Building this is real, working code (it needs
    no PAP algorithm to exist); *executing* it against the actual PAP is
    what's blocked (see PapExecutor below)."""

    # Employee statutory attributes (source: EmployeeStatutoryProfile)
    stkl: str                              # STKL — tax class I-VI
    af: bool                               # AF — factor-method flag (class IV only)
    f: Optional[Decimal]                   # F — factor, 3 decimals, class IV only
    zkf: Decimal                           # ZKF — child allowance count/factor
    r: str                                 # R — religious-community characteristic (church tax liability + Land)
    krv: bool                              # KRV — pension precaution-allowance marker (de_pension_insurance_exempt)
    alv_marker: bool                       # ALV — unemployment precaution-allowance marker (de_unemployment_insurance_exempt)
    pkv: bool                              # PKV — private health-insurance status marker
    pvs: bool                              # PVS — Saxony care-insurance flag
    pvz: bool                              # PVZ — childless care-insurance surcharge flag
    pva: int                               # PVA — discount count for 2nd-5th qualifying children

    # Payroll-period values (source: payroll run / PayrollContext)
    lzz: int                               # LZZ — pay period: 1 annual, 2 monthly, 3 weekly, 4 daily
    re4_cents: int                         # RE4 — taxable wage for the period, in cents

    # Configuration values (source: resolved registries)
    kvz: Decimal                           # KVZ — health-fund full supplementary contribution rate (GermanyHealthFund)

    # ELStAM allowance/add-back values — Phase 8N. Sourced from
    # EmployeeStatutoryProfile.de_jfreib/de_lzzfreib/de_jhinzu/de_lzzhinzu
    # when set; zero (identical to every pre-8N calculation) when the
    # employee has no recorded allowance/add-back — never invented.
    jfreib_cents: int = 0                  # JFREIB
    lzzfreib_cents: int = 0                # LZZFREIB
    jhinzu_cents: int = 0                  # JHINZU
    lzzhinzu_cents: int = 0                # LZZHINZU

    # Private health/care insurance amounts — Phase 8N. Sourced from
    # EmployeeStatutoryProfile.de_pkpv/de_pkpvagz (spec §6 "2026 ELStAM
    # CHANGE") when set; zero otherwise.
    pkpv_cents: int = 0                    # PKPV
    pkpvagz_cents: int = 0                 # PKPVAGZ

    # Other-remuneration / annualized special payment — zero unless a
    # future phase's bonus/other-remuneration path sets it.
    sonstb_cents: int = 0                  # SONSTB
    jre4_cents: int = 0                    # JRE4

    def field_sources(self) -> dict:
        """Documents where every field's value came from — never exposed
        raw to an unauthorized caller (see PapExecutionResult's own
        docstring), but available for the authenticated QA/diagnostic
        preview endpoint."""
        return {
            "stkl": "EmployeeStatutoryProfile.de_tax_class",
            "af": "EmployeeStatutoryProfile.de_factor is not null",
            "f": "EmployeeStatutoryProfile.de_factor",
            "zkf": "EmployeeStatutoryProfile.de_zkf_override if set, else de_child_count",
            "r": "EmployeeStatutoryProfile.de_church_tax_liable + de_church_tax_land",
            "krv": "EmployeeStatutoryProfile.de_pension_insurance_exempt",
            "alv_marker": "EmployeeStatutoryProfile.de_unemployment_insurance_exempt",
            "pkv": "EmployeeStatutoryProfile.de_health_insurance_status == PRIVATE",
            "pvs": "EmployeeStatutoryProfile.de_saxony",
            "pvz": "EmployeeStatutoryProfile.de_childless",
            "pva": "EmployeeStatutoryProfile.de_child_count (2nd-5th child discount count)",
            "lzz": "payroll run pay frequency (monthly, fixed 30-day model)",
            "re4_cents": "PayrollContext.gross minus germany_sonstb (regular period taxable wage, before PAP allowances)",
            "kvz": "GermanyHealthFund.supplementary_rate_pct (resolved by de_health_fund_code + payroll date)",
            "jfreib_cents": "EmployeeStatutoryProfile.de_jfreib (0 if unset)",
            "lzzfreib_cents": "EmployeeStatutoryProfile.de_lzzfreib (0 if unset)",
            "jhinzu_cents": "EmployeeStatutoryProfile.de_jhinzu (0 if unset)",
            "lzzhinzu_cents": "EmployeeStatutoryProfile.de_lzzhinzu (0 if unset)",
            "pkpv_cents": "EmployeeStatutoryProfile.de_pkpv (0 if unset)",
            "pkpvagz_cents": "EmployeeStatutoryProfile.de_pkpvagz (0 if unset)",
            "sonstb_cents": "PayrollContext.germany_sonstb (PayrollAttendanceRecord.bonus; 0 if none recorded this period)",
            "jre4_cents": "12x regular (non-SONSTB) monthly wage — 0 unless sonstb_cents > 0",
        }


def build_pap_input(
    *, profile, gross_monthly: Decimal, kvz_rate: Decimal, pay_frequency: str = "Monthly",
    sonstb: Optional[Decimal] = None,
) -> PapInputContract:
    """Map an effective EmployeeStatutoryProfile + this period's payroll
    values into the PAP's documented input contract. Real, working code —
    building the input does not require the PAP algorithm to exist.
    Raises GermanyStatutoryProfileMissingError-family validation errors
    (via the caller, which already resolved `profile` is not None) only
    for internally-inconsistent data; the profile's own field-level
    validation already happened at write time (service._validate_statutory_profile_fields)."""
    tax_class = (getattr(profile, "de_tax_class", None) or "").upper()
    factor = getattr(profile, "de_factor", None)
    # Phase 8K note: de_child_count is also the source resolve_pv_child_category()
    # uses for the PV (long-term care) child category. ZKF (income-tax child
    # allowance count) and PV's own child count are legally distinct concepts
    # (EStG vs SGB XI) that happen to be numerically identical for the ordinary
    # case this profile models (a plain integer count of qualifying children,
    # no split-custody half-allowance). de_child_count is an Integer column, so
    # it cannot represent a fractional ZKF (e.g. 0.5 per child under split
    # custody) even if someone tried.
    #
    # Phase 8N: the genuinely split-custody case Phase 8K left out of scope
    # now has its own escape hatch — EmployeeStatutoryProfile.de_zkf_override
    # (a Numeric(4,2), can hold a half-integer) — used for ZKF INSTEAD of
    # de_child_count when set. de_child_count itself is untouched and keeps
    # driving PVA/resolve_pv_child_category() exactly as before; the two
    # concepts remain legally and architecturally distinct, this just gives
    # ZKF a real override path rather than always deriving it.
    child_count = getattr(profile, "de_child_count", None) or 0
    zkf_override = getattr(profile, "de_zkf_override", None)
    zkf_value = Decimal(str(zkf_override)) if zkf_override is not None else Decimal(str(child_count))

    lzz_map = {"Monthly": 2, "Weekly": 3, "Daily": 4, "Annual": 1}
    lzz = lzz_map.get(pay_frequency, 2)

    def _euros_to_cents(value) -> int:
        return int((Decimal(str(value)) * 100).to_integral_value()) if value is not None else 0

    # Phase 8T — SONSTB (other remuneration / bonus, spec §5 PAP input,
    # §15 "Bonus / annual bonus" row: "Other remuneration route... Route
    # through SONSTB/annual PAP method as applicable"). `sonstb` is the
    # bonus portion of THIS period's gross_monthly (sourced from
    # PayrollContext.germany_sonstb, ultimately PayrollAttendanceRecord.bonus
    # — never rewards/other_compensation, which spec does not classify as
    # SONSTB-routed). RE4 (regular wage) must exclude it — the PAP computes
    # regular and other-remuneration tax through genuinely different
    # sub-algorithms, so summing bonus into RE4 as well as SONSTB would
    # double-count it. gross_monthly itself is untouched by this (still the
    # full amount — the employee is still paid it, and it remains
    # RV/ALV/GKV/PV-contributory per spec's own table; only the wage-tax
    # input split changes). JRE4 ("Expected annual regular wage used for
    # other remuneration calculation", spec §5) is only meaningful when a
    # SONSTB payment actually exists this period — annualizing the
    # *regular* (non-SONSTB) portion, per the field's own stated purpose.
    sonstb_amount = Decimal(str(sonstb)) if sonstb else Decimal("0")
    regular_wage = gross_monthly - sonstb_amount

    return PapInputContract(
        stkl=tax_class,
        af=factor is not None,
        f=factor,
        zkf=zkf_value,
        r="CHURCH_TAX_LIABLE" if getattr(profile, "de_church_tax_liable", False) else "NONE",
        krv=bool(getattr(profile, "de_pension_insurance_exempt", False)),
        alv_marker=bool(getattr(profile, "de_unemployment_insurance_exempt", False)),
        pkv=(getattr(profile, "de_health_insurance_status", None) == "PRIVATE"),
        pvs=bool(getattr(profile, "de_saxony", False)),
        pvz=bool(getattr(profile, "de_childless", False)),
        pva=max(0, min(int(child_count), 4)),  # discount count applies to the 2nd-5th child, per spec §10
        lzz=lzz,
        re4_cents=int((regular_wage * 100).to_integral_value()),
        kvz=kvz_rate,
        jfreib_cents=_euros_to_cents(getattr(profile, "de_jfreib", None)),
        lzzfreib_cents=_euros_to_cents(getattr(profile, "de_lzzfreib", None)),
        jhinzu_cents=_euros_to_cents(getattr(profile, "de_jhinzu", None)),
        lzzhinzu_cents=_euros_to_cents(getattr(profile, "de_lzzhinzu", None)),
        pkpv_cents=_euros_to_cents(getattr(profile, "de_pkpv", None)),
        pkpvagz_cents=_euros_to_cents(getattr(profile, "de_pkpvagz", None)),
        sonstb_cents=int((sonstb_amount * 100).to_integral_value()),
        jre4_cents=int((regular_wage * 12 * 100).to_integral_value()) if sonstb_amount > 0 else 0,
    )


def trace_tax_data_used(trace: "GermanyCalculationTrace", profile, pap_input: PapInputContract) -> None:
    """Record, on the trace, exactly which tax-relevant values this
    calculation fed into the PAP input contract (Phase 8K) — independent
    of whether PAP execution itself succeeds or is blocked, so a future
    audit/reproducibility read of the trace always shows what was used,
    not just what would have been computed from it."""
    trace.elstam_source = getattr(profile, "de_elstam_source", None)
    trace.elstam_fallback_reason = getattr(profile, "de_elstam_fallback_reason", None)
    trace.tax_class_used = pap_input.stkl
    trace.factor_used = str(pap_input.f) if pap_input.f is not None else None
    trace.zkf_used = str(pap_input.zkf)
    trace.church_tax_liable_used = pap_input.r == "CHURCH_TAX_LIABLE"
    # Phase 8N: only trace as non-zero when the profile actually carried a
    # value — a 0 cents-in-the-PAP-input value is ambiguous (genuinely
    # zero vs. "not recorded"); reading straight from the profile keeps the
    # trace's own semantics ("what was actually recorded") distinct from
    # the PAP input's semantics ("what value to feed the algorithm").
    trace.jfreib_used = str(getattr(profile, "de_jfreib", None)) if getattr(profile, "de_jfreib", None) is not None else None
    trace.lzzfreib_used = str(getattr(profile, "de_lzzfreib", None)) if getattr(profile, "de_lzzfreib", None) is not None else None
    trace.jhinzu_used = str(getattr(profile, "de_jhinzu", None)) if getattr(profile, "de_jhinzu", None) is not None else None
    trace.lzzhinzu_used = str(getattr(profile, "de_lzzhinzu", None)) if getattr(profile, "de_lzzhinzu", None) is not None else None
    trace.pkpv_used = str(getattr(profile, "de_pkpv", None)) if getattr(profile, "de_pkpv", None) is not None else None
    trace.pkpvagz_used = str(getattr(profile, "de_pkpvagz", None)) if getattr(profile, "de_pkpvagz", None) is not None else None
    trace.main_employment_used = getattr(profile, "de_main_employment", None)
    # Phase 8T — bonus/SONSTB routing, read straight off the already-built
    # PAP input (never re-derived) so the trace can never drift from what
    # was actually fed to the PAP.
    trace.sonstb_used = str(Decimal(pap_input.sonstb_cents) / 100)
    trace.jre4_used = str(Decimal(pap_input.jre4_cents) / 100) if pap_input.jre4_cents else None
    trace.regular_wage_used = str(Decimal(pap_input.re4_cents) / 100)


def check_main_secondary_employment_consistency(*, tax_class: Optional[str], is_main_employment: Optional[bool]) -> Optional[str]:
    """Spec §6: tax class VI is documented as the "secondary employment /
    missing permitted attributes" class. Returns a human-readable warning
    (never raises — spec gives no explicit hard-reject instruction for
    this pairing, unlike the Saxony-flag boundary test) when an employee
    is recorded as MAIN employment (de_main_employment=True) while also
    carrying tax class VI — a combination the spec's own tax-class table
    treats as the secondary-employment case, so worth a QA/Tax-Operations
    review rather than a silent accept. Symmetrically, no warning fires
    for the (equally real) case of a secondary employment on a non-VI
    class, since spec's own class table gives no equivalent statement in
    that direction."""
    if is_main_employment is True and (tax_class or "").upper() == "VI":
        return (
            "Employee is recorded as MAIN/first employment (de_main_employment=True) while tax class is VI — "
            "spec §6 documents class VI for secondary employment / missing permitted attributes. Not blocked "
            "automatically (NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION as a hard-reject rule) — review this "
            "employee's tax-class/employment-relationship classification."
        )
    return None


# ── PAP execution result ────────────────────────────────────────────────

@dataclass
class GermanyPapCalculationResult:
    """Structured PAP execution result (this phase's §13). Never populated
    today — see PapExecutor below — but the shape a future executor must
    fill in. `calculation_trace` is a dict (already redacted via
    GermanyCalculationTrace.to_dict()), never a raw internal object."""

    pap_version: Optional[str] = None
    pap_hash: Optional[str] = None
    pap_build_identifier: Optional[str] = None

    input_reference: Optional[dict] = None     # field_sources(), not raw personal values

    lohnsteuer: Decimal = Decimal("0")
    soli: Decimal = Decimal("0")
    church_tax_assessment_base: Decimal = Decimal("0")

    # Phase 8C-2: every OTHER declared PAP output (STS/SOLZS/BKS —
    # other-remuneration variants of the three fields above — and the six
    # DBA/Vorsorgepauschale-carry-forward outputs VFRB/VFRBS1/VFRBS2/
    # WVFRB/WVFRBO/WVFRBM), so nothing the PAP actually computes is
    # silently discarded even though only the three fields above have a
    # dedicated, named result field today. Keys are the PAP's own output
    # names (uppercase, matching the XML exactly); values are `str(Decimal)`
    # (never raw Decimal, to keep this dict trivially JSON-safe like
    # GermanyCalculationTrace.to_dict() already is). None until an
    # executor actually runs — see germany_pap_adapter.py's output-mapping
    # matrix for which of these are currently deferred vs. required.
    raw_outputs: Optional[dict] = None

    calculation_status: str = "BLOCKED"
    calculation_trace: Optional[dict] = None
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


# ── PAP executor interface (this phase's §8 Outcome B, §13) ─────────────

class PapExecutor(ABC):
    """Interface a future phase implements once a real, approved BMF PAP
    source has been ingested and published. Deliberately abstract here —
    Phase 7 does not (and per the supplied instructions, must not)
    implement a concrete interpreter for the actual algorithm."""

    @abstractmethod
    def execute(self, pap_input: PapInputContract) -> GermanyPapCalculationResult:
        raise NotImplementedError


class UnavailablePapExecutor(PapExecutor):
    """The only PapExecutor implementation that exists in this codebase.
    Always raises — deterministically, with a clear reason — rather than
    ever returning a fabricated result. This is the concrete embodiment of
    this phase's Outcome B: fail safely instead of guessing."""

    def __init__(self, reason: str):
        self._reason = reason

    def execute(self, pap_input: PapInputContract) -> GermanyPapCalculationResult:
        raise GermanyPapNotAvailableError(self._reason)


def resolve_pap_executor(pap_asset) -> PapExecutor:
    """Return the PapExecutor to use for a given resolved (or absent)
    PapAlgorithmAsset. Today this ALWAYS returns UnavailablePapExecutor,
    regardless of `pap_asset`, because no concrete PAP interpreter exists
    in this codebase yet — ingesting and publishing a real PAP asset
    (Phase 3's registry) is necessary but not sufficient; a future phase
    must also implement and register a real PapExecutor here. Kept as a
    function (not a hardcoded call site) so that future phase's change is
    a one-line swap, not a call-site hunt."""
    if pap_asset is None:
        return UnavailablePapExecutor(
            "No PUBLISHED Germany PAP asset is resolvable for this payroll date. "
            "Ingest and publish a BMF 2026 PAP asset via the Phase 3 registry "
            "(/api/super-admin/compliance/germany/pap-assets) before Germany "
            "wage-tax calculation can run."
        )
    return UnavailablePapExecutor(
        f"A PUBLISHED PAP asset exists (id={getattr(pap_asset, 'id', None)}, "
        f"version={getattr(pap_asset, 'pap_version', None)}) but no PAP execution "
        "engine is implemented in this codebase yet. Ingesting/publishing the "
        "asset is necessary but not sufficient — a future phase must implement "
        "a concrete PapExecutor that interprets the actual BMF algorithm before "
        "this asset can be executed."
    )


# ── Social insurance: RV / ALV / GKV / PV (real, non-PAP calculations) ──

def resolve_pv_child_category(profile) -> str:
    """CHILDLESS overrides count-derived categories (spec §10 — childless
    is its own statutory state, not child_count==0). Raises if neither
    flag is recorded, rather than silently defaulting to CHILDLESS."""
    childless = getattr(profile, "de_childless", None)
    child_count = getattr(profile, "de_child_count", None)
    if childless is True:
        return "CHILDLESS"
    if child_count is None:
        raise GermanyStatutoryProfileMissingError(
            "EmployeeStatutoryProfile.de_child_count/de_childless are both unset — "
            "cannot resolve a PV (long-term care insurance) child category."
        )
    if child_count <= 0:
        return "CHILDLESS"
    if child_count >= 5:
        return "5_PLUS"
    return str(child_count)


def _two_sided_rate(rate_map: dict, key: str, default_employee: Decimal, default_employer: Decimal):
    """Same convention germany.py's pre-Phase-7 `calculate()` already used
    for "pension"/"social-insurance": a rate_map component row with its
    own employee_rate_pct/employer_rate_pct, falling back to the
    hardcoded default independently per side."""
    row = rate_map.get(key)
    employee_pct = row.employee_rate_pct if (row and row.employee_rate_pct is not None) else default_employee
    employer_pct = row.employer_rate_pct if (row and row.employer_rate_pct is not None) else default_employer
    return Decimal(employee_pct), Decimal(employer_pct)


def calculate_rv(*, annual_gross: Decimal, ceiling_rv_alv, rate_map: dict, exempt: bool,
                  rv_employee_default: Decimal, rv_employer_default: Decimal, months_per_year: Decimal):
    """Rentenversicherung — spec §9. `exempt` is
    EmployeeStatutoryProfile.de_pension_insurance_exempt (a real statutory
    exemption, not a tax allowance)."""
    if exempt:
        return Decimal("0"), Decimal("0")
    if ceiling_rv_alv is None:
        raise GermanyCeilingNotAvailableError(
            "No PUBLISHED RV_ALV contribution ceiling is resolvable for this payroll date."
        )
    base = min(annual_gross, Decimal(ceiling_rv_alv.annual_ceiling))
    employee_pct, employer_pct = _two_sided_rate(rate_map, "rv_pension", rv_employee_default, rv_employer_default)
    employee = _r2((base * employee_pct / 100) / months_per_year)
    employer = _r2((base * employer_pct / 100) / months_per_year)
    return employee, employer


def calculate_alv(*, annual_gross: Decimal, ceiling_rv_alv, rate_map: dict, exempt: bool,
                   alv_employee_default: Decimal, alv_employer_default: Decimal, months_per_year: Decimal):
    """Arbeitslosenversicherung — spec §9. `exempt` is
    EmployeeStatutoryProfile.de_unemployment_insurance_exempt."""
    if exempt:
        return Decimal("0"), Decimal("0")
    if ceiling_rv_alv is None:
        raise GermanyCeilingNotAvailableError(
            "No PUBLISHED RV_ALV contribution ceiling is resolvable for this payroll date."
        )
    base = min(annual_gross, Decimal(ceiling_rv_alv.annual_ceiling))
    employee_pct, employer_pct = _two_sided_rate(rate_map, "alv_unemployment", alv_employee_default, alv_employer_default)
    employee = _r2((base * employee_pct / 100) / months_per_year)
    employer = _r2((base * employer_pct / 100) / months_per_year)
    return employee, employer


def calculate_gkv(*, annual_gross: Decimal, ceiling_gkv_pv, rate_map: dict, health_insurance_status: Optional[str],
                   health_fund, gkv_employee_default: Decimal, gkv_employer_default: Decimal, months_per_year: Decimal):
    """Statutory health insurance (general rate) + fund-specific
    supplementary contribution (Zusatzbeitrag), spec §9/§11. Privately
    insured employees (PKV) are NOT in statutory GKV at all — returns
    zero, since private premiums are a PAP-side allowance
    (PKPV/PKPVAGZ), not a statutory GKV deduction this engine computes."""
    if health_insurance_status == "PRIVATE":
        return Decimal("0"), Decimal("0"), Decimal("0")
    if health_insurance_status != "PUBLIC":
        raise GermanyStatutoryProfileMissingError(
            "EmployeeStatutoryProfile.de_health_insurance_status must be PUBLIC or "
            "PRIVATE to compute GKV — it is unset."
        )
    if ceiling_gkv_pv is None:
        raise GermanyCeilingNotAvailableError(
            "No PUBLISHED GKV_PV contribution ceiling is resolvable for this payroll date."
        )
    if health_fund is None:
        raise GermanyHealthFundNotAvailableError(
            "Employee is PUBLIC health insurance status but no PUBLISHED "
            "Krankenkasse supplementary-rate record is resolvable for this "
            "employee's de_health_fund_code and payroll date. Per spec's "
            "AVERAGE RATE WARNING (§11), Zoiko Payroll must not silently use "
            "the 2.9% statutory average — the employee's actual fund rate "
            "must be published in the Health Fund Registry."
        )
    base = min(annual_gross, Decimal(ceiling_gkv_pv.annual_ceiling))
    general_employee_pct, general_employer_pct = _two_sided_rate(
        rate_map, "gkv_general", gkv_employee_default, gkv_employer_default,
    )
    general_employee = _r2((base * general_employee_pct / 100) / months_per_year)
    general_employer = _r2((base * general_employer_pct / 100) / months_per_year)

    # Supplementary rate: full rate split 50/50 employee/employer (spec §9's
    # "Health supplementary contribution" row).
    supplementary_full_pct = Decimal(health_fund.supplementary_rate_pct)
    supplementary_half_pct = supplementary_full_pct / 2
    supplementary_employee = _r2((base * supplementary_half_pct / 100) / months_per_year)
    supplementary_employer = _r2((base * supplementary_half_pct / 100) / months_per_year)

    employee = general_employee + supplementary_employee
    employer = general_employer + supplementary_employer
    return employee, employer, supplementary_full_pct


def calculate_pv(*, annual_gross: Decimal, ceiling_gkv_pv, pv_configuration, months_per_year: Decimal):
    """Pflegeversicherung (long-term care insurance) — spec §10. Shares
    the GKV_PV ceiling (spec §9's rate table lists PV's ceiling as "Same
    GKV ceiling"). `pv_configuration` must already be resolved by the
    caller against the employee's (child_category, is_saxony) pair."""
    if ceiling_gkv_pv is None:
        raise GermanyCeilingNotAvailableError(
            "No PUBLISHED GKV_PV contribution ceiling is resolvable for this payroll date."
        )
    if pv_configuration is None:
        raise GermanyPvConfigurationNotAvailableError(
            "No PUBLISHED PV (long-term care insurance) configuration is resolvable "
            "for this employee's child category / Saxony status and payroll date."
        )
    base = min(annual_gross, Decimal(ceiling_gkv_pv.annual_ceiling))
    if pv_configuration.is_saxony:
        employee_pct = Decimal(pv_configuration.saxony_employee_rate_pct)
        employer_pct = Decimal(pv_configuration.saxony_employer_rate_pct)
    else:
        employee_pct = Decimal(pv_configuration.standard_employee_rate_pct)
        employer_pct = Decimal(pv_configuration.employer_rate_pct)
    employee = _r2((base * employee_pct / 100) / months_per_year)
    employer = _r2((base * employer_pct / 100) / months_per_year)
    return employee, employer


# ── Minijob / Midijob (Phase 8I) ─────────────────────────────────────────
# Entirely separate mechanisms from the four branch calculators above —
# see countries/germany.py's calculate() for how classification selects
# between them. Neither reads or writes rate_map (the RV/ALV/GKV
# general-rate override mechanism) — the supplied 2026 documentation gives
# these as fixed statutory percentages, not DB-overridable canonical
# rates, so no resolve_jurisdiction_parameter indirection was introduced
# for them (that would be inventing an override mechanism the spec
# doesn't describe).

def resolve_employment_classification(profile) -> str:
    """REGULAR is the default when unset, matching the pre-Phase-8I
    behavior exactly (countries/germany.py previously inlined this same
    `or "REGULAR"` fallback; now centralized here). Raises
    GermanyInvalidEmploymentClassificationError for any value outside the
    known vocabulary — never silently treated as REGULAR, which would be
    the least-safe possible misclassification."""
    classification = (getattr(profile, "de_employment_classification", None) or "REGULAR").upper()
    if classification not in ("REGULAR", "MINIJOB", "MIDIJOB"):
        raise GermanyInvalidEmploymentClassificationError(
            f"EmployeeStatutoryProfile.de_employment_classification={classification!r} is not one of "
            "REGULAR, MINIJOB, MIDIJOB — cannot safely select a Germany calculation path."
        )
    return classification


def validate_employment_classification_against_earnings(
    classification: str, monthly_gross: Decimal, *, minijob_upper_threshold: Decimal, midijob_upper_threshold: Decimal,
) -> None:
    """Phase 8I §9/§10: the employee's own classification is the
    authoritative statutory attribute — this function never reclassifies
    the employee. It only rejects an internally-inconsistent state (a
    classification that this period's earnings could not possibly
    support) with a structured, specific error, exactly as the phase
    brief requires. Thresholds are passed in (from
    hardcoded_defaults.py, via countries/germany.py) rather than imported
    directly, matching this module's existing parameter-passing pattern."""
    if classification == "MINIJOB" and monthly_gross > minijob_upper_threshold:
        raise GermanyMinijobThresholdViolationError(
            f"Employee is classified MINIJOB but this period's gross earnings ({monthly_gross}) exceed the "
            f"Minijob threshold ({minijob_upper_threshold}). The employee's employment classification "
            "must be corrected before this payroll can be calculated — it is not automatically reclassified."
        )
    if classification == "MIDIJOB":
        if monthly_gross <= minijob_upper_threshold:
            raise GermanyMidijobThresholdViolationError(
                f"Employee is classified MIDIJOB but this period's gross earnings ({monthly_gross}) are at or "
                f"below the Minijob threshold ({minijob_upper_threshold}) — below the Midijob corridor's "
                "own lower bound. The employee's employment classification must be corrected."
            )
        if monthly_gross > midijob_upper_threshold:
            raise GermanyMidijobThresholdViolationError(
                f"Employee is classified MIDIJOB but this period's gross earnings ({monthly_gross}) exceed the "
                f"Midijob corridor's upper bound ({midijob_upper_threshold}). The employee's employment "
                "classification must be corrected before this payroll can be calculated."
            )


def validate_employment_classification_against_vocational_training(classification: str, is_vocational_trainee: bool) -> None:
    """Phase 8L. §20 Abs. 2a Satz 9 SGB IV: an employee engaged for
    vocational training can never be classified MIDIJOB, regardless of
    earnings — this is an eligibility exclusion, not an earnings check,
    so it is a separate function from
    validate_employment_classification_against_earnings rather than a
    branch inside it. Never reclassifies; fails closed."""
    if is_vocational_trainee and classification == "MIDIJOB":
        raise GermanyVocationalTraineeMidijobExclusionError(
            "Employee is classified MIDIJOB but is recorded as employed for vocational training "
            "(de_vocational_trainee) — §20 Abs. 2a Satz 9 SGB IV excludes vocational trainees from the "
            "Übergangsbereich regardless of earnings. The employee's employment classification must be corrected."
        )


@dataclass
class MinijobCalculationResult:
    employer_health: Decimal
    employer_pension: Decimal
    employer_u1: Decimal
    employer_u2: Decimal
    employer_u3: Decimal
    employee_pension_topup: Decimal
    flat_tax: Decimal
    accident_insurance_resolved: bool
    accident_insurance_amount: Optional[Decimal]


def calculate_minijob(
    *, monthly_gross: Decimal, pension_insurance_exempt: bool,
    employer_health_rate: Decimal, employer_pension_rate: Decimal,
    u1_rate: Decimal, u2_rate: Decimal, u3_rate: Decimal,
    employee_pension_topup_rate: Decimal, flat_tax_rate: Decimal,
    accident_insurance_rate_pct: Optional[Decimal] = None,
) -> MinijobCalculationResult:
    """Phase 8I §12-19. All employer figures (health/pension/U1/U2/U3) are
    flat percentages of this period's Minijob gross — never deducted from
    the employee. The employee pension top-up is the ONLY component that
    reduces employee net pay, and only when the employee has not opted
    out (`pension_insurance_exempt`). The flat 2% tax is treated as an
    employer-remitted Pauschsteuer (see hardcoded_defaults.py's own
    disclosed-interpretation comment) — also not an employee deduction.

    Accident insurance is carrier-specific (spec §4) — no Zoiko-wide rate
    exists or is invented. If `accident_insurance_rate_pct` is not
    supplied (true for every caller today, since no carrier-rate
    configuration source exists anywhere in this codebase), the component
    is explicitly marked unresolved (`accident_insurance_resolved=False`,
    `accident_insurance_amount=None`) rather than silently computed as
    zero — per §18's explicit instruction. This does NOT block the rest
    of the Minijob calculation: accident insurance is a pure employer-cost
    figure with no effect on the employee's own payslip, so withholding
    the entire calculation over it would be disproportionate — see
    Phase 8I's own report for this reasoning."""
    employer_health = _r2(monthly_gross * employer_health_rate / Decimal("100"))
    employer_pension = _r2(monthly_gross * employer_pension_rate / Decimal("100"))
    employer_u1 = _r2(monthly_gross * u1_rate / Decimal("100"))
    employer_u2 = _r2(monthly_gross * u2_rate / Decimal("100"))
    employer_u3 = _r2(monthly_gross * u3_rate / Decimal("100"))
    employee_pension_topup = (
        Decimal("0") if pension_insurance_exempt
        else _r2(monthly_gross * employee_pension_topup_rate / Decimal("100"))
    )
    flat_tax = _r2(monthly_gross * flat_tax_rate / Decimal("100"))

    accident_insurance_resolved = accident_insurance_rate_pct is not None
    accident_insurance_amount = (
        _r2(monthly_gross * accident_insurance_rate_pct / Decimal("100"))
        if accident_insurance_resolved else None
    )

    return MinijobCalculationResult(
        employer_health=employer_health, employer_pension=employer_pension,
        employer_u1=employer_u1, employer_u2=employer_u2, employer_u3=employer_u3,
        employee_pension_topup=employee_pension_topup, flat_tax=flat_tax,
        accident_insurance_resolved=accident_insurance_resolved,
        accident_insurance_amount=accident_insurance_amount,
    )


def calculate_midijob_total_base(ae: Decimal, *, multiplier: Decimal, subtrahend: Decimal) -> Decimal:
    """Phase 8I §20. Implemented exactly as the supplied specification
    states: total_base = multiplier x AE - subtrahend (the caller passes
    the literal 2026 coefficients from hardcoded_defaults.py — see
    countries/germany.py — matching this module's existing pattern of
    taking rates as parameters rather than importing hardcoded_defaults.py
    directly, e.g. calculate_rv's rv_employee_default/rv_employer_default).
    No intermediate rounding (Decimal, full precision throughout) — the
    caller rounds only the final monetary result it derives, per this
    codebase's existing convention (_r2 applied at the point money is
    actually assigned, never mid-formula). Clamped at zero — Phase 8I §23
    explicitly requires that a negative base never reach payroll
    deductions; the specification does not describe negative-earnings
    behavior, so this is the one safe invariant the instruction itself
    supplies, not an invented statutory rule."""
    result = (multiplier * ae) - subtrahend
    return max(Decimal("0"), result)


def calculate_midijob_employee_base(ae: Decimal, *, multiplier: Decimal, subtrahend: Decimal) -> Decimal:
    """Phase 8I §20. employee_base = multiplier x AE - subtrahend. Same
    parameter-passing / no-intermediate-rounding / zero-floor treatment as
    calculate_midijob_total_base."""
    result = (multiplier * ae) - subtrahend
    return max(Decimal("0"), result)


def calculate_midijob_branch_contribution(
    total_base: Decimal, employee_base: Decimal, *, combined_rate_pct: Decimal, employee_rate_pct: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Phase 8J — the official 3-step Übergangsbereich branch-contribution
    mechanism (§20 Absatz 2a SGB IV; §2 Absatz 2 BVV), per the joint
    circular "Versicherungs-, beitrags- und melderechtliche Behandlung
    von Beschäftigungsverhältnissen im Übergangsbereich nach § 20
    Absatz 2 SGB IV ab dem 01.01.2023" issued jointly by GKV-Spitzenverband,
    Deutsche Rentenversicherung Bund, and the Bundesagentur für Arbeit,
    Stand 20.12.2022, §4.3.3.1 "Arbeitsentgelt innerhalb des
    Übergangsbereichs" (fetched and read directly this phase; the
    underlying legal mechanism is unchanged for 2026 — only the yearly
    rates/coefficients differ, confirmed against Deutsche Rentenversicherung's
    own "Berechnung Gleitzone, Übergangsbereich - Faktor F" page,
    Stand 19.12.2025, published 29.12.2025, values ab 01.01.2026, which
    independently confirms this project's own total_base formula):

    1. "Gesamtbeitrag für jeden Versicherungszweig": apply HALF
       `combined_rate_pct` to `total_base`, ROUND the result to 2
       decimals, THEN DOUBLE the rounded result. This specific
       round-then-double sequence is legally mandated (§20 Abs. 2a Satz 7
       SGB IV i.V.m. § 123 SGB VI: intermediate results are not rounded
       "nach der Intention des Gesetzgebers" except at this one
       prescribed point) and can differ by up to one cent from simply
       computing `total_base * combined_rate_pct / 100` and rounding
       once — it is therefore implemented exactly as described, never
       simplified.
    2. "Beitragsanteil des Arbeitnehmers": apply `employee_rate_pct`
       (the branch's own existing employee-side rate — e.g. 9.30% for
       RV, the same constant already used for the REGULAR path; NOT
       halved again, since it already IS half of RV's/ALV's symmetric
       combined rate) to `employee_base`, rounded to 2 decimals.
    3. "Beitragsanteil des Arbeitgebers" = step 1 result − step 2
       result (the circular's own words: employer pays "die Differenz"
       — matching this project's own supplied Zoiko documentation's
       "employer pays the difference from total contribution after
       employee share" verbatim).

    Returns (total, employee, employer), all Decimal, all already
    rounded to 2 decimals (step 1's own internal rounding is not
    additionally re-rounded after doubling — doubling an exact multiple
    of 0.01 is still an exact multiple of 0.01)."""
    half_rate = combined_rate_pct / Decimal("2")
    total = _r2(total_base * half_rate / Decimal("100")) * Decimal("2")
    employee = _r2(employee_base * employee_rate_pct / Decimal("100"))
    employer = total - employee
    return total, employee, employer


@dataclass
class MidijobPvResult:
    total: Decimal
    employee: Decimal
    employer: Decimal
    childless_surcharge: Optional[Decimal]   # None when not applicable (not childless)


def calculate_midijob_pv(
    total_base: Decimal, employee_base: Decimal, *, pv_configuration, is_childless: bool,
    childless_surcharge_rate_pct: Optional[Decimal] = None,
) -> MidijobPvResult:
    """Phase 8J/8L — PV (Pflegeversicherung) needs special handling beyond
    calculate_midijob_branch_contribution because of the childless
    surcharge, which the joint circular (§4.3.3.1, step 1) requires to be
    calculated SEPARATELY, applied directly and only to `total_base` (no
    half/double step), and — per step 3's own explicit note — EXCLUDED
    from the employer's share entirely ("Beim Abzug des
    Arbeitnehmerbeitragsanteils ist der Beitragszuschlag für Kinderlose
    [...] nicht zu berücksichtigen"): the surcharge is 100%
    employee-borne, in every case, Midijob included, in every Land,
    including Saxony.

    Phase 8L resolved the one Phase 8J left open (Saxony + childless) by
    fetching the primary statutory text directly:
    §55 Abs. 3 Satz 1 SGB XI (gesetze-im-internet.de/sgb_11/__55.html)
    fixes the surcharge at a flat 0.6 contribution-rate points, with no
    Land-specific variant anywhere in its text — it is added to "der
    Beitragssatz nach Absatz 1", the nationwide BASE rate, before any
    Land-specific split is applied. §58 Abs. 1 SGB XI
    (gesetze-im-internet.de/sgb_11/__58.html) then states plainly "Den
    Beitragszuschlag für Kinderlose nach § 55 Absatz 3 Satz 1 tragen die
    Beschäftigten" — the employee bears it, unconditionally; §58 Abs. 3's
    own Saxony-specific adjustment governs only the ordinary (non-
    surcharge) employer/employee split. So the surcharge is a genuine,
    Land-independent statutory constant (`_DE_PV_CHILDLESS_SURCHARGE_RATE`,
    hardcoded_defaults.py) — not derived by subtracting one registry row's
    fields from another, and not dependent on a second reference row. It
    is simply subtracted back out of the resolved (Saxony or standard)
    CHILDLESS row's own employee_rate/total_rate to recover that row's
    non-surcharge base split, and added back on top as the separate,
    100%-employee-borne, non-doubled amount. See Phase 8L's report §5 for
    the full evidence table."""
    if pv_configuration is None:
        raise GermanyPvConfigurationNotAvailableError(
            "No PUBLISHED PV (long-term care insurance) configuration is resolvable "
            "for this employee's child category / Saxony status and payroll date."
        )
    is_saxony = bool(pv_configuration.is_saxony)

    if is_saxony:
        employee_rate_pct = Decimal(pv_configuration.saxony_employee_rate_pct)
        employer_rate_pct = Decimal(pv_configuration.saxony_employer_rate_pct)
    else:
        employee_rate_pct = Decimal(pv_configuration.standard_employee_rate_pct)
        employer_rate_pct = Decimal(pv_configuration.employer_rate_pct)
    total_rate_pct = Decimal(pv_configuration.total_rate_pct)

    if is_childless:
        if childless_surcharge_rate_pct is None:
            raise GermanyPvConfigurationNotAvailableError(
                "Midijob PV childless-surcharge rate was not supplied to calculate_midijob_pv() — "
                "cannot isolate the childless surcharge from the resolved PV configuration row."
            )
        surcharge_rate_pct = Decimal(childless_surcharge_rate_pct)
        base_total_rate_pct = total_rate_pct - surcharge_rate_pct
        # §58 Abs. 1 SGB XI: the surcharge never touches the employer, in
        # any Land — so employer_rate_pct on the CHILDLESS row already IS
        # the base (non-surcharge) employer rate, unchanged; calculate_
        # midijob_branch_contribution derives the employer amount as
        # total-minus-employee, so only the base employee rate is needed
        # explicitly here.
        base_employee_rate_pct = employee_rate_pct - surcharge_rate_pct
        base_total, base_employee, base_employer = calculate_midijob_branch_contribution(
            total_base, employee_base, combined_rate_pct=base_total_rate_pct, employee_rate_pct=base_employee_rate_pct,
        )
        surcharge_amount = _r2(total_base * surcharge_rate_pct / Decimal("100"))
        return MidijobPvResult(
            total=base_total + surcharge_amount, employee=base_employee + surcharge_amount,
            employer=base_employer, childless_surcharge=surcharge_amount,
        )

    total, employee, employer = calculate_midijob_branch_contribution(
        total_base, employee_base, combined_rate_pct=total_rate_pct, employee_rate_pct=employee_rate_pct,
    )
    return MidijobPvResult(total=total, employee=employee, employer=employer, childless_surcharge=None)


def calculate_midijob_gkv(
    total_base: Decimal, employee_base: Decimal, *, health_insurance_status: Optional[str], health_fund,
    gkv_general_employee_rate: Decimal, gkv_general_employer_rate: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Phase 8J — GKV is the general rate (symmetric, like RV/ALV) PLUS
    the fund-specific supplementary rate, each independently subject to
    the same "half then double" step 1 (the circular's own words: "Dies
    gilt gleichermaßen für die Ermittlung des Zusatzbeitrages") — exactly
    mirroring how the existing, unmodified calculate_gkv() already
    computes the REGULAR path's general+supplementary composition.
    Returns (total, employee, employer, supplementary_rate_pct) — the
    last value is carried through purely for trace/snapshot purposes,
    matching calculate_gkv()'s own existing return shape."""
    if health_insurance_status == "PRIVATE":
        return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    if health_insurance_status != "PUBLIC":
        raise GermanyStatutoryProfileMissingError(
            "EmployeeStatutoryProfile.de_health_insurance_status must be PUBLIC or PRIVATE to compute GKV — it is unset."
        )
    if health_fund is None:
        raise GermanyHealthFundNotAvailableError(
            "Employee is PUBLIC health insurance status but no PUBLISHED Krankenkasse supplementary-rate "
            "record is resolvable for this employee's de_health_fund_code and payroll date."
        )
    supplementary_rate_pct = Decimal(health_fund.supplementary_rate_pct)
    general_combined = gkv_general_employee_rate + gkv_general_employer_rate
    g_total, g_employee, g_employer = calculate_midijob_branch_contribution(
        total_base, employee_base, combined_rate_pct=general_combined, employee_rate_pct=gkv_general_employee_rate,
    )
    s_total, s_employee, s_employer = calculate_midijob_branch_contribution(
        total_base, employee_base, combined_rate_pct=supplementary_rate_pct, employee_rate_pct=supplementary_rate_pct / Decimal("2"),
    )
    return (g_total + s_total, g_employee + s_employee, g_employer + s_employer, supplementary_rate_pct)


def calculate_employer_insolvency_levy(assessment_base_monthly: Decimal, rate_pct: Decimal) -> Decimal:
    """Insolvenzgeldumlage (U3) — spec §14, a flat FEDERAL rate (unlike
    U1/U2's fund/tariff-specific nature per DE-D06), applicable to every
    Germany employment classification, not just Minijob (Phase 8I's own
    calculate_minijob() already computes this same rate for that one
    classification; this sibling function makes it available to
    REGULAR/MIDIJOB too — see countries/germany.py callers). Employer-paid
    only, never deducted from employee net pay, exactly like Minijob's own
    U3 treatment.

    Phase 8U correction: `assessment_base_monthly` MUST already be the
    correct statutory base — independently confirmed this phase via §358
    SGB III (gesetze-im-internet.de, fetched live): "Maßgebend ist das
    Arbeitsentgelt, nach dem die Beiträge zur gesetzlichen
    Rentenversicherung... bemessen werden" (the SAME wage basis RV
    contributions use, i.e. capped at the RV/ALV contribution ceiling —
    NOT raw uncapped gross, which is what Phase 8M's original REGULAR-path
    implementation incorrectly passed). This function itself stays a pure,
    caller-supplies-the-base multiplier (mirroring calculate_rv's own
    "caller resolves/caps the base, this function just applies the rate"
    division of responsibility) — the capping now happens in
    countries/germany.py's REGULAR path (using the SAME ceiling_rv_alv
    already resolved for calculate_rv) and is a correct no-op for MIDIJOB
    (whose own total_base structurally never approaches the ceiling,
    confirmed Phase 8J)."""
    return _r2(assessment_base_monthly * rate_pct / Decimal("100"))


def check_gkv_coverage_threshold(
    *, health_insurance_status: Optional[str], annual_gross: Decimal, jaeg_annual_threshold: Decimal,
) -> Optional[str]:
    """Spec §9 JAEG ("GKV compulsory-insurance threshold... Coverage/status
    determination for ordinary employees") and acceptance criterion #20
    ("JAEG 2026 coverage threshold is represented separately from the
    contribution ceiling"). Returns a human-readable warning (never raises)
    when an employee is recorded PRIVATE (PKV) while this period's
    annualized earnings do not exceed JAEG — i.e. a combination that would
    not ordinarily be lawful (GKV membership is compulsory at/below this
    threshold) — so the calculation trace surfaces it for Tax
    Operations/QA review rather than silently accepting it. Deliberately
    NOT a blocking error: spec §22's explicit boundary-test list gives a
    hard-reject instruction for the analogous Saxony-flag case but states
    no equivalent for JAEG, so inventing a hard block here would itself be
    an unspecified statutory rule, not a disclosed one."""
    if health_insurance_status != "PRIVATE":
        return None
    if annual_gross > jaeg_annual_threshold:
        return None
    return (
        f"Employee is recorded PRIVATE (PKV) health insurance status but this period's annualized gross "
        f"({annual_gross}) does not exceed the JAEG compulsory-insurance threshold ({jaeg_annual_threshold}) — "
        "GKV membership is ordinarily compulsory at or below this threshold. Not blocked automatically "
        "(NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION as a hard-reject rule, unlike the Saxony-flag "
        "boundary test) — review this employee's health-insurance-status classification."
    )


def resolve_church_tax_rate(church_tax_land: Optional[str]) -> Decimal:
    """Spec §8 Land overlay. Raises rather than defaulting to a
    representative rate — church-tax liability is only ever computed for
    an employee explicitly flagged liable (de_church_tax_liable=True), so
    a missing/unrecognized Land at that point is a real configuration gap,
    not something to guess through."""
    if not church_tax_land or church_tax_land not in CHURCH_TAX_LAND_RATES:
        raise GermanyStatutoryProfileMissingError(
            f"EmployeeStatutoryProfile.de_church_tax_land is missing or unrecognized "
            f"({church_tax_land!r}) for an employee flagged de_church_tax_liable=True."
        )
    return CHURCH_TAX_LAND_RATES[church_tax_land]
