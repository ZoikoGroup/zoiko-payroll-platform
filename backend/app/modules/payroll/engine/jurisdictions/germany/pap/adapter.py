"""
modules/payroll/engine/jurisdictions/germany/pap/adapter.py
------------------------------------------------------------
Phase 8C-2 — the bridge between Zoiko payroll data (EmployeeStatutoryProfile,
resolved registries, PayrollContext) and the exact BMF PAP input/output
contract, built against the real, independently re-verified 2026 artifact
(`Lohnsteuer2026.xml`, SHA-256
`63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4`,
re-confirmed `SOURCE_HASH_MATCH` this phase — see
docs/PHASE_8C_2_GERMANY_PAP_CONTRACT_INTEGRATION_REPORT.md).

(Relocated from `engine/countries/germany_pap_adapter.py` in Phase 8E-0A
into the `engine/germany_pap/` subsystem package.)

LAYERING, STRICT: `germany_pap_interpreter.py` (Phase 8C-1) knows nothing
about Zoiko — it is a generic engine over "PAP field name -> value" dicts.
THIS module owns every Zoiko-specific concept (EmployeeStatutoryProfile,
PapInputContract, GermanyPapCalculationResult, GermanyHealthFund) and is
the only place that translates between them and the interpreter's raw
environment. `germany.py`/`germany_pap.py`'s production calculation path
is untouched by this phase — nothing here is wired into
`resolve_pap_executor()`.

FOUR MANDATORY OPEN ITEMS this phase addresses explicitly (see the Phase
8C-2 report for full evidence):

  A. XML/PDF date discrepancy — STILL UNRESOLVED. Preserved as an
     explicit, non-bypassable open condition: `PAP_SOURCE_FINALITY`
     below is "OPEN", not silently treated as final.
  B. VJAHR typo (`defaul="0"` instead of `default="0"` in the official
     XML) — handled ONLY here, as an explicit, named, documented adapter
     constant (`_VJAHR_ORDINARY_EMPLOYEE_VALUE`), never as generic typo
     tolerance in the interpreter.
  C. Factor path (`af`/`f`) — traced directly against the real artifact
     this phase (see `_FACTOR_PATH_EVIDENCE` and the report §9): `af`
     gates the effect, `f` only matters when `af != 0`, and the PAP
     itself resets `f = 1` whenever `af == 0` — the "factor only valid
     for tax class IV" rule is a STATUTORY rule Zoiko must enforce
     (already does, at profile-write time, Phase 2), not something the
     PAP algorithm enforces on its own.
  D. Full 35-input classification — every official input is classified
     below as one of DIRECTLY_MAPPED / DERIVED / DEFAULTED / DEFERRED /
     NOT_APPLICABLE / UNSUPPORTED, with evidence (see
     `PAP_INPUT_CLASSIFICATION`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.modules.payroll.engine.jurisdictions.germany.pap.core import (
    GermanyPapCalculationResult,
    GermanyPapInvalidError,
    PapExecutor,
    PapInputContract,
)
from app.modules.payroll.engine.jurisdictions.germany.pap.interpreter import (
    PapExecutionContext,
    PapProgram,
    run_program,
)

# ═════════════════════════════════════════════════════════════════════
# A. SOURCE FINALITY — explicit, non-bypassable open condition
# ═════════════════════════════════════════════════════════════════════
# Phase 8B found the official XML's internal "Stand" comment
# (2025-10-23 12:40) predates the official PDF's final publication date
# ("Stand: 12.11.2025 (endgültig)") by roughly three weeks. Phase 8C-1's
# spot-check of 7 statutory constants found no VALUE discrepancy, but a
# spot-check of 7 constants out of a 40-page/628-element document is not
# a full reconciliation. This phase did not obtain new evidence that
# closes this gap (no BMF revision-history page was found stating the
# XML was updated after 23 Oct 2025, and no dated republish of the XML
# was observed — re-verified this phase via a fresh, independent
# download: identical SHA-256, identical Last-Modified header). Per this
# phase's explicit instruction, this is preserved as an OPEN condition,
# not silently resolved by "the hash still matches, so it must be fine."
PAP_SOURCE_FINALITY = "OPEN"


def assert_pap_source_finality_resolved() -> None:
    """Any future call site that would move Germany PAP calculation
    toward production (registering a real PapExecutor in
    resolve_pap_executor, publishing a PapAlgorithmAsset for real use)
    MUST call this first. It always raises today, by design — there is
    no evidence yet that would let it return normally. This function
    exists so that gate is a single, auditable choke point rather than a
    convention someone could forget."""
    if PAP_SOURCE_FINALITY != "RESOLVED":
        raise GermanyPapInvalidError(
            "PAP_SOURCE_FINALITY is OPEN: the ingested XML's internal 'Stand' date "
            "(2025-10-23) has not been reconciled against the official PDF's later "
            "final publication date (2025-11-12). Production use is blocked until "
            "this is resolved with authoritative evidence (a byte-level PDF/XML "
            "content comparison, or direct BMF confirmation) — see Phase 8C-2 report §4."
        )


# ═════════════════════════════════════════════════════════════════════
# B. VJAHR — explicit, isolated, documented adapter decision
# ═════════════════════════════════════════════════════════════════════
# The real XML declares <INPUT name="VJAHR" type="int" defaul="0"/> — a
# genuine typo in the official source (the interpreter correctly detects
# this and refuses to guess; see germany_pap_interpreter.py's fail-closed
# behavior and the Phase 8C-1 report §21). VJAHR ("year the pension
# benefit was first granted") is meaningful ONLY for a pension recipient
# (Versorgungsempfänger) — see the field cluster classified NOT_APPLICABLE
# below (VBEZ/VBEZM/VBEZS/VBS/ZMVB/AJAHR/ALTER1), all of which govern the
# same pension-benefit scope and all of which correctly default to
# zero/0 in the official artifact.
#
# Zoiko's EmployeeStatutoryProfile.de_employment_classification already
# distinguishes REGULAR from MINIJOB/MIDIJOB (Phase 2) but has NO
# pension-recipient concept at all — because Zoiko's Germany scope, as of
# this phase, is ordinary ACTIVE employees only (Phase 0/1 scope; pension
# payroll was never in scope for any phase through 8C-2). For that scope,
# VBEZ (pension benefits within RE4) is unconditionally zero (no field
# exists to set it otherwise), which makes VJAHR statutorily irrelevant
# for every employee this adapter is ever called for today — not a guess,
# a direct consequence of VBEZ having no non-zero source. This is exactly
# the "scope-proven non-applicability" defaulting origin this phase's
# instructions require (§25), and it is the ONLY defaulting origin used
# for VJAHR — this is NOT a "probably zero" guess.
_VJAHR_ORDINARY_EMPLOYEE_VALUE = 0

# Phase 2 architecture consolidation: the Roman-numeral tax-class label
# (Zoiko/PapInputContract's "I".."VI") to the official numeric STKL field
# value (1-6) is a fixed structural lookup table from the PAP's own field
# spec (§5) — not a statutory rate/threshold, so it belongs as a plain
# module constant, not a registry row. Previously written out twice in
# this file (build_pap_environment() and InterpreterPapExecutor.execute()
# each had their own identical copy); consolidated to one definition so
# the two mappers can never silently drift apart on this lookup.
_STKL_BY_TAX_CLASS = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}


# ═════════════════════════════════════════════════════════════════════
# C. FACTOR PATH — traced directly against the real 2026 artifact
# ═════════════════════════════════════════════════════════════════════
# Confirmed this phase by direct inspection of the re-verified XML's
# exec/expr attributes (see Phase 8C-2 report §9 for the full quoted
# evidence):
#
#   MRE4JL:     IF af == 0 THEN f = 1        (algorithm itself neutralizes
#                                              f whenever af is not set —
#                                              no STKL check inside this
#                                              specific rule)
#   MBERECH:    LSTJAHR = ST.multiply(f).setScale(0, ROUND_DOWN)
#               JBMG    = ST.multiply(f).setScale(0, ROUND_DOWN)
#   MSONST:     STS = ....multiply(f)....     (other-remuneration path,
#                                              deferred — see SONSTB)
#   MSOLZSTS:   SOLZSBMG = ST.multiply(f).setScale(0, ROUND_DOWN)
#
# Conclusions:
#   1. `af` is the real gate; `f` only has an effect when `af != 0`.
#   2. The PAP algorithm does NOT itself restrict af/f to STKL==IV — that
#      restriction is a STATUTORY rule (ZP-TAX-DE-2026-001 §6: "Factor can
#      only be used with class IV"), which Zoiko already enforces at
#      EmployeeStatutoryProfile write time (Phase 2's
#      `_validate_statutory_profile_fields`: "de_factor may only be set
#      when de_tax_class == IV") — this adapter does NOT need to
#      re-enforce it inside the PAP environment construction, but DOES
#      re-validate it defensively before execution (see
#      `validate_pap_environment`) since a PAP execution is a
#      higher-stakes operation than an ordinary field write.
#   3. Factor multiplication happens on the already-tariff-computed tax
#      (`ST`), rounded to whole currency units AFTER multiplication
#      (`setScale(0, ROUND_DOWN)` — truncation, not rounding to nearest).
#   4. The official artifact declares `f` as Java `type="double"`, not
#      `BigDecimal` — Zoiko's interpreter (Phase 8C-1) faithfully mirrors
#      this (`float` internally for "double"-typed inputs), which is a
#      faithful reproduction of the AUTHORITATIVE algorithm's own numeric
#      type, not a Zoiko-introduced float/Decimal violation. `f` is
#      converted to `Decimal` again inside the algorithm itself via
#      `BigDecimal.valueOf(f)` before any arithmetic — exactly matching
#      real BMF reference behavior.
#
# Zoiko's existing `EmployeeStatutoryProfile.de_factor` (Numeric(6,4),
# Phase 2) is SUFFICIENT to represent `f` — no schema change is required.
# `af` is DERIVED (not a stored column): `af = 1 if de_factor is not None
# else 0`, exactly as Phase 7's `build_pap_input()` already computed it.
_FACTOR_PATH_EVIDENCE = (
    "af gates f; PAP resets f=1 when af==0 (MRE4JL); f multiplies the "
    "tariff tax in MBERECH/MSONST/MSOLZSTS, rounded DOWN to whole "
    "currency units after multiplication; class-IV-only restriction is "
    "statutory (Zoiko-enforced), not PAP-enforced."
)


# ═════════════════════════════════════════════════════════════════════
# D. FULL 35-INPUT CLASSIFICATION
# ═════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PapInputClassification:
    scope: str          # DIRECTLY_MAPPED | DERIVED | DEFAULTED | DEFERRED | NOT_APPLICABLE | UNSUPPORTED
    zoiko_source: str
    evidence: str


# ── Phase 8BE correction notice ─────────────────────────────────────────
# This dict and build_pap_environment() below are the ORIGINAL Phase 8C-2
# mapper. They are TEST-ONLY — confirmed this phase that production never
# calls build_pap_environment(); the real, currently-used input mapper is
# engine/countries/germany.py -> germany_pap/core.py:build_pap_input(),
# which is materially more complete (Phase 8N/8T additions). Concretely,
# JFREIB/LZZFREIB/JHINZU/LZZHINZU/PKPV/PKPVAGZ are labelled DEFERRED below,
# but build_pap_input() DOES map all six from real EmployeeStatutoryProfile
# columns (de_jfreib/de_lzzfreib/de_jhinzu/de_lzzhinzu/de_pkpv/de_pkpvagz,
# added Phase 8N) — this dict's DEFERRED label describes ONLY this unused
# path, not current production input-completeness. Do not cite this dict
# as evidence of what production does or doesn't map — a prior phase's own
# forensic report did exactly that and was corrected by this note. Kept
# (not deleted) because its own test file (test_germany_pap_adapter.py)
# still exercises it and InterpreterPapExecutor's isolated-test construction
# depends on it; a future cleanup phase should either delete this dead
# path or reconcile it to call build_pap_input() directly instead of
# maintaining two divergent mappers.
PAP_INPUT_CLASSIFICATION: dict = {
    "STKL":     PapInputClassification("DIRECTLY_MAPPED", "EmployeeStatutoryProfile.de_tax_class", "I-VI -> 1-6 lookup table"),
    "af":       PapInputClassification("DERIVED", "EmployeeStatutoryProfile.de_factor is not null", "1 if de_factor set else 0 (Phase 7's build_pap_input already did this)"),
    "f":        PapInputClassification("DIRECTLY_MAPPED", "EmployeeStatutoryProfile.de_factor", "Numeric(6,4) column, sufficient for the PAP's 3-decimal factor; see §C above"),
    "LZZ":      PapInputClassification("DERIVED", "payroll run pay frequency", "Monthly->2 / Weekly->3 / Daily->4 / Annual->1 lookup table"),
    "RE4":      PapInputClassification("DERIVED", "PayrollContext.gross (period taxable wage)", "EUR -> cents (int(gross*100))"),
    "JFREIB":   PapInputClassification("DEFERRED", "None in THIS unused mapper — build_pap_input() maps EmployeeStatutoryProfile.de_jfreib (Phase 8N)", "NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION for this test-only path; PAP's own default=0 applies here only"),
    "LZZFREIB": PapInputClassification("DEFERRED", "None in THIS unused mapper — build_pap_input() maps de_lzzfreib (Phase 8N)", "same as JFREIB"),
    "JHINZU":   PapInputClassification("DEFERRED", "None in THIS unused mapper — build_pap_input() maps de_jhinzu (Phase 8N)", "same as JFREIB"),
    "LZZHINZU": PapInputClassification("DEFERRED", "None in THIS unused mapper — build_pap_input() maps de_lzzhinzu (Phase 8N)", "same as JFREIB"),
    "ZKF":      PapInputClassification("DIRECTLY_MAPPED", "EmployeeStatutoryProfile.de_child_count (or de_zkf_override when set, Phase 8N)", "Direct count, per spec §5/§6; fractional ZKF (split custody) passed via de_zkf_override, never truncated"),
    "R":        PapInputClassification("DERIVED", "EmployeeStatutoryProfile.de_church_tax_liable", "boolean -> 0/1; see §17 rationale below (lossy but proven sufficient for the PAP's own R>0 branch)"),
    "KVZ":      PapInputClassification("DIRECTLY_MAPPED", "GermanyHealthFund.supplementary_rate_pct (resolved registry, Phase 4)", "Full rate, matches PAP's own 'full applicable rate, split occurs in-algorithm' contract"),
    "PKV":      PapInputClassification("DERIVED", "EmployeeStatutoryProfile.de_health_insurance_status", "'PRIVATE' -> 1, 'PUBLIC' -> 0"),
    "PKPV":     PapInputClassification("DEFERRED", "None in THIS unused mapper — build_pap_input() maps EmployeeStatutoryProfile.de_pkpv (Phase 8N)", "NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION for this test-only path; PAP's own default=0 applies here only"),
    "PKPVAGZ":  PapInputClassification("DEFERRED", "None in THIS unused mapper — build_pap_input() maps de_pkpvagz (Phase 8N)", "same as PKPV"),
    "PVS":      PapInputClassification("DIRECTLY_MAPPED", "EmployeeStatutoryProfile.de_saxony", "boolean -> 0/1"),
    "PVZ":      PapInputClassification("DIRECTLY_MAPPED", "EmployeeStatutoryProfile.de_childless", "boolean -> 0/1"),
    "PVA":      PapInputClassification("DERIVED", "EmployeeStatutoryProfile.de_child_count", "clamp(child_count, 0, 4) — spec §10 discount count for 2nd-5th child"),
    "KRV":      PapInputClassification("DIRECTLY_MAPPED", "EmployeeStatutoryProfile.de_pension_insurance_exempt", "boolean -> 0/1"),
    "ALV":      PapInputClassification("DIRECTLY_MAPPED", "EmployeeStatutoryProfile.de_unemployment_insurance_exempt", "boolean -> 0/1"),
    "SONSTB":   PapInputClassification("DEFERRED", "None — other-remuneration/bonus path not implemented", "PAP's own default=0 applies; STS/SOLZS/BKS outputs correspondingly always 0"),
    "JRE4":     PapInputClassification("DEFERRED", "None", "required only when SONSTB != 0; deferred with it"),
    "JRE4ENT":  PapInputClassification("NOT_APPLICABLE", "None", "§24 Nr.1 compensation / §19a equity benefits within JRE4 — severance/equity-comp edge case, out of ordinary-employee scope; PAP default=0 applies"),
    "JVBEZ":    PapInputClassification("NOT_APPLICABLE", "None", "pension benefits within JRE4 — pension-recipient scope, not modeled; PAP default=0 applies"),
    "MBV":      PapInputClassification("NOT_APPLICABLE", "None", "non-taxable §19a equity benefit — edge case, not modeled; PAP default=0 applies"),
    "AJAHR":    PapInputClassification("NOT_APPLICABLE", "None", "§24a age-relief year — pension-scope; PAP default=0 applies"),
    "ALTER1":   PapInputClassification("NOT_APPLICABLE", "None", "§24a age-64 flag — pension-scope; PAP default=0 applies"),
    "SONSTENT": PapInputClassification("NOT_APPLICABLE", "None", "§24 Nr.1 compensation within SONSTB — severance edge case; PAP default=0 applies"),
    "STERBE":   PapInputClassification("NOT_APPLICABLE", "None", "death benefit within SONSTB — pension-scope edge case; PAP default=0 applies"),
    "VBEZ":     PapInputClassification("NOT_APPLICABLE", "None", "pension benefits within RE4 — no Zoiko field represents an active employee having this; PAP default=0 applies"),
    "VBEZM":    PapInputClassification("NOT_APPLICABLE", "None", "pension-scope reference amount; PAP default=0 applies"),
    "VBEZS":    PapInputClassification("NOT_APPLICABLE", "None", "pension-scope special payment; PAP default=0 applies"),
    "VBS":      PapInputClassification("NOT_APPLICABLE", "None", "pension benefits within SONSTB; PAP default=0 applies"),
    "VJAHR":    PapInputClassification("DEFAULTED", "Zoiko adapter constant _VJAHR_ORDINARY_EMPLOYEE_VALUE=0", "Official XML has a typo (defaul= not default=) with NO functioning PAP default; Zoiko explicitly supplies 0, justified by VBEZ's scope-proven zero (§B above) — NOT a guess"),
    "ZMVB":     PapInputClassification("NOT_APPLICABLE", "None", "months pension benefit paid — pension-scope; PAP default=0 applies"),
}

# Sanity: this dict must have exactly the 35 official inputs the real
# artifact declares (re-verified this phase — see the report §3/§16).
assert len(PAP_INPUT_CLASSIFICATION) == 35, "PAP_INPUT_CLASSIFICATION must classify exactly the 35 official inputs"


def build_pap_environment(
    *, profile, gross_monthly: Decimal, kvz_rate: Decimal, pay_frequency: str = "Monthly",
) -> dict:
    """Zoiko payroll inputs -> the raw environment dict `run_program()`
    expects, keyed by the PAP's OWN field names (not PapInputContract's
    snake_case names). Only the fields classified DIRECTLY_MAPPED or
    DERIVED above are set explicitly (14 fields); every DEFERRED/
    NOT_APPLICABLE field is deliberately OMITTED so the interpreter
    applies the PAP's own declared default (proven correct in Phase
    8C-1's real-artifact run) — except VJAHR, whose official default is
    broken (typo) and is therefore supplied explicitly here, and only
    here, per §B above."""
    tax_class = (getattr(profile, "de_tax_class", None) or "").upper()
    stkl = _STKL_BY_TAX_CLASS.get(tax_class)
    if stkl is None:
        raise GermanyPapInvalidError(f"Cannot map EmployeeStatutoryProfile.de_tax_class={tax_class!r} to an official STKL value 1-6.")

    factor = getattr(profile, "de_factor", None)
    child_count = getattr(profile, "de_child_count", None) or 0
    # Phase 8BE: mirror core.py:build_pap_input()'s real ZKF logic — a
    # split-custody employee may have a legally fractional ZKF (e.g. 0.5)
    # recorded via the Phase 8N de_zkf_override escape hatch, which the
    # Integer de_child_count column cannot represent. Before this fix,
    # this (test-only) mapper always used the truncating Integer column
    # regardless of de_zkf_override, silently rounding a legitimate 0.5
    # down to 0 for any test exercising this path.
    zkf_override = getattr(profile, "de_zkf_override", None)
    zkf_value = Decimal(str(zkf_override)) if zkf_override is not None else Decimal(child_count)

    lzz_map = {"Monthly": 2, "Weekly": 3, "Daily": 4, "Annual": 1}
    lzz = lzz_map.get(pay_frequency)
    if lzz is None:
        raise GermanyPapInvalidError(f"Unsupported pay frequency for PAP LZZ mapping: {pay_frequency!r}")

    health_status = getattr(profile, "de_health_insurance_status", None)

    return {
        "STKL": stkl,
        "af": 1 if factor is not None else 0,
        "f": float(factor) if factor is not None else 1.0,
        "LZZ": lzz,
        "RE4": Decimal(int((gross_monthly * 100).to_integral_value())),
        "ZKF": zkf_value,
        "R": 1 if bool(getattr(profile, "de_church_tax_liable", False)) else 0,
        "KVZ": Decimal(kvz_rate),
        "PKV": 1 if health_status == "PRIVATE" else 0,
        "PVS": 1 if bool(getattr(profile, "de_saxony", False)) else 0,
        "PVZ": 1 if bool(getattr(profile, "de_childless", False)) else 0,
        "PVA": Decimal(max(0, min(int(child_count), 4))),
        "KRV": 1 if bool(getattr(profile, "de_pension_insurance_exempt", False)) else 0,
        "ALV": 1 if bool(getattr(profile, "de_unemployment_insurance_exempt", False)) else 0,
        "VJAHR": _VJAHR_ORDINARY_EMPLOYEE_VALUE,
    }


# ═════════════════════════════════════════════════════════════════════
# OUTPUT MAPPING
# ═════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PapOutputClassification:
    meaning: str
    required_now: bool
    zoiko_field: Optional[str]


PAP_OUTPUT_CLASSIFICATION: dict = {
    "LSTLZZ":  PapOutputClassification("Lohnsteuer for the pay period (regular wage)", True, "lohnsteuer"),
    "SOLZLZZ": PapOutputClassification("Solidaritätszuschlag for the pay period", True, "soli"),
    "BK":      PapOutputClassification("Church-tax assessment base, regular wage", True, "church_tax_assessment_base"),
    "STS":     PapOutputClassification("Lohnsteuer for other remuneration (SONSTB)", False, None),
    "SOLZS":   PapOutputClassification("Soli on other remuneration", False, None),
    "BKS":     PapOutputClassification("Church-tax assessment base, other remuneration", False, None),
    "VFRB":    PapOutputClassification("Vorsorgepauschale carry-forward (DBA)", False, None),
    "VFRBS1":  PapOutputClassification("Vorsorgepauschale carry-forward, other remuneration 1 (DBA)", False, None),
    "VFRBS2":  PapOutputClassification("Vorsorgepauschale carry-forward, other remuneration 2 (DBA)", False, None),
    "WVFRB":   PapOutputClassification("Vorsorgepauschale carry-forward, annual (DBA)", False, None),
    "WVFRBO":  PapOutputClassification("Vorsorgepauschale carry-forward, other (DBA)", False, None),
    "WVFRBM":  PapOutputClassification("Vorsorgepauschale carry-forward, monthly (DBA)", False, None),
}

_REQUIRED_OUTPUTS = {name for name, c in PAP_OUTPUT_CLASSIFICATION.items() if c.required_now}


def map_pap_outputs(context: PapExecutionContext) -> dict:
    """PapExecutionContext -> a plain dict of every declared output the
    program actually produced, as `str(Decimal)` values — nothing is
    discarded (§27 of this phase's brief). The caller (InterpreterPapExecutor
    below) extracts the three currently-required fields into
    GermanyPapCalculationResult's named fields and stores the rest in
    `raw_outputs`."""
    outputs = context.outputs()
    return {name: str(value) for name, value in outputs.items()}


# ═════════════════════════════════════════════════════════════════════
# VALIDATION
# ═════════════════════════════════════════════════════════════════════

def validate_pap_environment(profile, environment: dict) -> None:
    """Pre-execution validation — prevents malformed/statutorily-invalid
    inputs from ever reaching the interpreter. Does NOT reproduce any
    part of the tax calculation itself (per this phase's explicit
    instruction) — only structural/statutory-rule checks."""
    stkl = environment.get("STKL")
    if stkl not in (1, 2, 3, 4, 5, 6):
        raise GermanyPapInvalidError(f"Invalid STKL: {stkl!r} (must be 1-6).")

    af = environment.get("af")
    f = environment.get("f")
    if af == 1:
        if stkl != 4:
            # Statutory rule (spec §6: "Factor can only be used with
            # class IV") — the PAP itself does not enforce this (§C
            # above), so the adapter must, before execution.
            raise GermanyPapInvalidError(
                f"Factor method (af=1) may only be used with STKL=4 (tax class IV); got STKL={stkl}."
            )
        if f is None or not (0 < f <= 1):
            raise GermanyPapInvalidError(f"Invalid factor f={f!r}: must be in (0, 1] when af=1.")

    for bool_field in ("R", "PKV", "PVS", "PVZ", "KRV", "ALV"):
        value = environment.get(bool_field)
        if value not in (0, 1):
            raise GermanyPapInvalidError(f"Invalid {bool_field}={value!r}: must be 0 or 1.")

    kvz = environment.get("KVZ")
    if kvz is not None and kvz < 0:
        raise GermanyPapInvalidError(f"Invalid KVZ={kvz!r}: must be non-negative.")

    re4 = environment.get("RE4")
    if re4 is not None and re4 < 0:
        raise GermanyPapInvalidError(f"Invalid RE4={re4!r}: must be non-negative.")

    lzz = environment.get("LZZ")
    if lzz not in (1, 2, 3, 4):
        raise GermanyPapInvalidError(f"Invalid LZZ={lzz!r} (must be 1-4).")


# ═════════════════════════════════════════════════════════════════════
# PapExecutor — FOR ISOLATED TESTING ONLY, NOT WIRED IN
# ═════════════════════════════════════════════════════════════════════
# Moved here from germany_pap_interpreter.py (Phase 8C-1 placed a
# minimal version there; this phase relocates it to where the
# Zoiko-specific mapping it depends on actually belongs — see this
# module's own docstring). Still never referenced by
# resolve_pap_executor() (germany_pap.py) — Germany production payroll
# remains exclusively on UnavailablePapExecutor.

class InterpreterPapExecutor(PapExecutor):
    """A real PapExecutor backed by the Phase 8C-1 interpreter and this
    phase's full input/output adapter, bound to one pre-loaded,
    pre-hash-verified PapProgram. Constructed only by this phase's own
    isolated tests — never by `resolve_pap_executor()`."""

    def __init__(self, program: PapProgram, expected_source_sha256: str):
        if program.source_sha256 != expected_source_sha256:
            raise GermanyPapInvalidError(
                f"PAP source hash mismatch: program was parsed from a source hashing to "
                f"{program.source_sha256}, but {expected_source_sha256} was expected. "
                "Refusing to execute a PAP program whose source does not match its "
                "recorded provenance."
            )
        self._program = program

    def execute(self, pap_input: PapInputContract) -> GermanyPapCalculationResult:
        # This adapter is built to accept a `profile`-shaped object
        # (EmployeeStatutoryProfile or a test double) directly via
        # build_pap_environment — but PapExecutor's interface contract
        # (Phase 7) is `execute(pap_input: PapInputContract)`. Bridge the
        # two here: PapInputContract already carries every field
        # build_pap_environment needs, just under different (snake_case)
        # names, so translate directly rather than requiring a second
        # profile object the interface doesn't have.
        stkl = _STKL_BY_TAX_CLASS.get(pap_input.stkl)
        if stkl is None:
            raise GermanyPapInvalidError(f"Cannot map PapInputContract.stkl={pap_input.stkl!r} to an official STKL value.")

        environment = {
            "STKL": stkl,
            "af": 1 if pap_input.af else 0,
            "f": float(pap_input.f) if pap_input.f is not None else 1.0,
            "LZZ": pap_input.lzz,
            "RE4": Decimal(pap_input.re4_cents),
            "ZKF": Decimal(pap_input.zkf),
            "R": 1 if pap_input.r == "CHURCH_TAX_LIABLE" else 0,
            "KVZ": Decimal(pap_input.kvz),
            "PKV": 1 if pap_input.pkv else 0,
            "PVS": 1 if pap_input.pvs else 0,
            "PVZ": 1 if pap_input.pvz else 0,
            "PVA": Decimal(pap_input.pva),
            "KRV": 1 if pap_input.krv else 0,
            "ALV": 1 if pap_input.alv_marker else 0,
            "VJAHR": _VJAHR_ORDINARY_EMPLOYEE_VALUE,
        }
        validate_pap_environment(profile=None, environment=environment)

        missing = _REQUIRED_OUTPUTS - set(self._program.outputs)
        if missing:
            raise GermanyPapInvalidError(f"Loaded PAP program does not declare expected output(s): {missing}")

        context = run_program(self._program, {k: v for k, v in environment.items() if k in self._program.inputs})
        raw_outputs = map_pap_outputs(context)

        return GermanyPapCalculationResult(
            pap_version=self._program.version_number,
            pap_hash=self._program.source_sha256,
            input_reference=pap_input.field_sources(),
            lohnsteuer=Decimal(raw_outputs.get("LSTLZZ", "0")),
            soli=Decimal(raw_outputs.get("SOLZLZZ", "0")),
            church_tax_assessment_base=Decimal(raw_outputs.get("BK", "0")),
            raw_outputs=raw_outputs,
            calculation_status="COMPLETE",
            calculation_trace={
                "methodSequence": list(context.trace.method_sequence),
                "evalCount": context.trace.eval_count,
                "papVersion": context.trace.pap_version,
                "papSourceSha256": context.trace.pap_source_sha256,
                "papSourceFinality": PAP_SOURCE_FINALITY,
            },
        )
