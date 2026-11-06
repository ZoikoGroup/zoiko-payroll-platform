"""Poland applicability and coverage (ZP-PL-ENG-001 §3, PL-001 / PL-002 / PL-006).

Applicability precedes calculation. The contract label is an INPUT checked
against the signed scope rows; the obligations themselves come from the
approved worker profile's coverage facts and the employer registration —
never derived from the label. For each obligation the result is
``{"applies": bool, "reason": code}``. A missing high-risk fact (other
insurance titles, A1 certificate, student / pensioner status, any coverage
flag) BLOCKS: the lowest-cost treatment is never guessed (spec §3 control).
"""
from __future__ import annotations

from datetime import date

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.pack import PlPack, as_date, field, in_window, upper

_COVERAGE_FLAGS = {"EMERYTALNE": "cov_pension", "RENTOWE": "cov_disability", "CHOROBOWE": "cov_sickness",
                   "WYPADKOWE": "cov_accident", "ZDROWOTNE": "cov_health"}
_REQUIRED_FACTS = ("other_titles_declared", "a1_certificate", "is_student", "is_pensioner")


def _require_active(pack: PlPack, record, missing: str, inactive: str, name: str, on: date) -> None:
    if record is None:
        pack.block(missing, f"no {name} is on record")
    if upper(field(record, "status")) != "ACTIVE":
        pack.block(inactive, f"the {name} is not ACTIVE (four-eyes approval required)")
    if not in_window(field(record, "effective_from"), field(record, "effective_to"), on):
        pack.block(inactive, f"the {name} is not in force on the pay date")


def determine(ctx, pack: PlPack, pay_date: date) -> dict:
    profile = getattr(ctx, "pl_profile", None)
    registration = getattr(ctx, "pl_registration", None)
    _require_active(pack, profile, E.PROFILE_MISSING, E.PROFILE_NOT_ACTIVE, "worker statutory profile", pay_date)
    _require_active(pack, registration, E.REGISTRATION_MISSING, E.REGISTRATION_NOT_ACTIVE,
                    "employer registration", pay_date)

    # Scope (spec §1, D2): signed scope rows, never assumed.
    contract = upper(field(profile, "contract_type"))
    if contract not in pack.text_list("pl_supported_contract_types"):
        pack.block(E.keyed(E.CONTRACT_UNSUPPORTED, contract or "NONE"),
                   "only the certified contract types are calculated (PL-002); others are gated")
    frequency = upper(field(profile, "pay_frequency")) or "MONTHLY"
    if frequency not in pack.text_list("pl_supported_pay_frequencies"):
        pack.block(E.keyed(E.FREQUENCY_UNSUPPORTED, frequency), "only the certified pay frequency is calculated")
    if upper(field(profile, "tax_residency")) != "RESIDENT":
        pack.block(E.NON_RESIDENT_UNSUPPORTED, "non-resident PIT is outside the certified scope")

    # High-risk facts must be KNOWN (spec §3 classification control).
    for name in _REQUIRED_FACTS:
        if field(profile, name) is None:
            pack.block(E.keyed(E.FACT_MISSING, name), "required coverage fact is not recorded")
    if field(profile, "other_titles_declared") is True:
        pack.block(E.MULTI_TITLE_UNSUPPORTED, "multi-title insurance aggregation is separately gated (spec §1)")
    if field(profile, "a1_certificate") is True:
        pack.block(E.A1_UNSUPPORTED, "posted-worker / A1 scenarios are separately gated (spec §1)")

    obligations = {"PIT": {"applies": True, "reason": E.R_RESIDENT_EMPLOYMENT}}
    for obligation, flag in _COVERAGE_FLAGS.items():
        value = field(profile, flag)
        if value is None:
            pack.block(E.keyed(E.COVERAGE_UNKNOWN, obligation), "coverage is not determined for this obligation")
        obligations[obligation] = {"applies": value is True, "reason": E.R_COVERED if value else E.R_NOT_COVERED}

    accident = None
    if obligations["WYPADKOWE"]["applies"]:
        rate = field(registration, "accident_rate_pct")
        if rate in (None, "") or not in_window(field(registration, "accident_rate_from"),
                                               field(registration, "accident_rate_to"), pay_date):
            pack.block(E.ACCIDENT_RATE_MISSING, "no evidenced accident rate covers the pay date (contribution year)")
        accident = {"ratePct": str(rate), "source": upper(field(registration, "accident_rate_source")),
                    "from": str(as_date(field(registration, "accident_rate_from"))),
                    "to": str(as_date(field(registration, "accident_rate_to")) or "")}

    exemption = field(profile, "fund_exemption_code")
    for obligation, flag in (("FP_FS", "fp_fs_applicable"), ("FGSP", "fgsp_applicable")):
        value = field(registration, flag)
        if value is None:
            pack.block(E.keyed(E.FUND_APPLICABILITY_UNKNOWN, obligation),
                       "the employer registration does not decide this fund (PL-011)")
        if value is True and exemption:
            # Named exemption rules with exact periods are not in the spec (§6).
            pack.block(E.keyed(E.FUND_EXEMPTION_UNSIGNED, obligation),
                       "a named employer-fund exemption needs signed exemption rules")
        obligations[obligation] = {"applies": value is True,
                                   "reason": E.R_EMPLOYER_LIABLE if value else E.R_EMPLOYER_NOT_LIABLE}

    fep = field(profile, "fep_qualifying") is True and in_window(field(profile, "fep_from"),
                                                                  field(profile, "fep_to"), pay_date)
    obligations["FEP"] = {"applies": fep, "reason": E.R_FEP_EVIDENCED if fep else E.R_FEP_NO_EVIDENCE}

    ppk = getattr(ctx, "pl_ppk", None)
    state = upper(field(ppk, "state"))
    if not state or state not in content.PPK_STATES:
        pack.block(E.PPK_STATE_MISSING, "the PPK participation state is not recorded (spec §7)")
    obligations["PPK"] = {"applies": state == "ENROLLED",
                          "reason": E.R_PPK_ENROLLED if state == "ENROLLED" else E.R_PPK_NOT_ENROLLED + state}

    if tuple(obligations) != content.COVERAGE_OBLIGATIONS:          # PL-006: one decision per obligation
        raise RuntimeError("Poland applicability did not decide every obligation")
    return {"obligations": obligations, "contractType": contract, "payFrequency": frequency,
            "accident": accident, "profile": profile, "registration": registration}
