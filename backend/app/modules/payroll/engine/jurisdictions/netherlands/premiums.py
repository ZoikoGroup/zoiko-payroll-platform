"""
engine/jurisdictions/netherlands/premiums.py
---------------------------------------------
Employee insurance premium calculations (ZP-NL-ENG-001 NL-015..NL-018).

AWf (NL-015, spec §6 / S6):
  - Low rate ONLY for a WRITTEN INDEFINITE-term contract that is not an
    on-call / standby contract, or where a recorded statutory exception
    applies. Every other contract (fixed-term of any length, unwritten,
    on-call) pays the HIGH rate. Admin CANNOT simply pick "low": the class is
    derived from contract facts.

Aof (NL-017):
  - Rate depends on employer size class for the 2024 basis year:
      * SMALL (2024 premium wage < threshold) → 6.27%
      * LARGE → 7.63%
    Size class comes from employer's premium decision row.

Wko (NL-006):
  - Fixed 0.50% on relevant premium wage.

Whk (NL-018):
  - Employer-specific, from Belastingdienst decision (WGA + ZW Flex).
  - Employee share (if any) becomes a separate NET deduction.
  - Fails closed if employer decision row is missing or not ACTIVE.

All calculations use VCR base_increment from vcr.advance() multiplied by
the applicable rate. Rates are read from the active NL-PAYROLL-2026 pack.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from .vcr import VcrResult, VcrFamily


def round_eur(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class AwfContractFacts:
    """Contract facts that determine AWf rate (NL-015)."""
    is_permanent: bool                    # indefinite contract
    fixed_term_months: Optional[int]      # if fixed-term, duration in months
    has_written_contract: bool
    is_on_call_no_guaranteed_hours: bool
    is_standby_contract: bool

    statutory_exception_code: Optional[str] = None  # recorded low-rate exception (S6)

    def qualifies_for_low_rate(self) -> bool:
        """NL-015: written indefinite non-on-call contract, or a recorded statutory exception."""
        return self.low_rate_reason() is not None

    def low_rate_reason(self) -> Optional[str]:
        if self.statutory_exception_code:
            return f"statutory exception {self.statutory_exception_code}"
        if (self.is_permanent and self.has_written_contract
                and not self.is_on_call_no_guaranteed_hours and not self.is_standby_contract):
            return "written indefinite-term contract, not on-call"
        return None


@dataclass(frozen=True)
class EmployerPremiumDecision:
    """Employer's premium decision row (payroll_nl_employer_premium_decisions)."""
    aof_size_class: str                   # "SMALL" or "LARGE"
    whk_wga_pct: Optional[Decimal]        # WGA %
    whk_wga_employee_recoverable_pct: Optional[Decimal]  # employee-recoverable part of WGA
    whk_zw_flex_pct: Optional[Decimal]    # ZW Flex %
    # Note: Whk total = WGA + ZW Flex (employer); employee share is recoverable part


@dataclass(frozen=True)
class EwPremiumRates:
    """Rates read from the active NL-PAYROLL-2026 pack."""
    awf_low_pct: Decimal      # 2.74
    awf_high_pct: Decimal     # 7.74
    aof_small_pct: Decimal    # 6.27
    aof_large_pct: Decimal    # 7.63
    wko_pct: Decimal          # 0.50


class PremiumConfigurationError(ValueError):
    """A statutory premium rate is not configured in the active pack — the
    engine blocks; there is no fallback rate (spec NL-003/NL-017)."""


_RATE_KEYS = {
    "awf_low_pct": "nl_awf_low_pct",
    "awf_high_pct": "nl_awf_high_pct",
    "aof_small_pct": "nl_aof_low_pct",
    "aof_large_pct": "nl_aof_high_pct",
    "wko_pct": "nl_wko_pct",
}


def _rate_value(entry) -> Optional[Decimal]:
    """A rate_map entry is either a ContributionRate-like row (employer premium
    -> employer_rate_pct) or a plain number (tests / frozen context)."""
    if entry is None:
        return None
    for attr in ("employer_rate_pct", "employee_rate_pct"):
        value = getattr(entry, attr, None)
        if value is not None:
            return Decimal(str(value))
    if isinstance(entry, (int, float, str, Decimal)):
        return Decimal(str(entry))
    return None


def get_rates_from_pack(rate_map: dict) -> EwPremiumRates:
    """Extract NL premium rates from the engine rate_map. A missing key
    raises PremiumConfigurationError — never a default rate."""
    values = {}
    missing = []
    for field_name, key in _RATE_KEYS.items():
        value = _rate_value(rate_map.get(key))
        if value is None:
            missing.append(key)
        values[field_name] = value
    if missing:
        raise PremiumConfigurationError(f"NL premium rate(s) not configured in the active pack: {', '.join(missing)}")
    return EwPremiumRates(**values)


@dataclass(frozen=True)
class EiPremiumResult:
    """Result for one premium in one period."""
    premium: str          # "awf" | "aof" | "wko" | "whk"
    base_increment: Decimal
    rate_pct: Decimal
    amount: Decimal       # round_eur(base_increment * rate_pct / 100)
    vcr_family: str       # "EI"


def calculate_awf(
    vcr_result: VcrResult,
    contract: AwfContractFacts,
    rates: EwPremiumRates,
) -> EiPremiumResult:
    """AWf premium for this period."""
    if contract.qualifies_for_low_rate():
        rate = rates.awf_low_pct
    else:
        rate = rates.awf_high_pct
    amount = round_eur(vcr_result.base_increment * rate / Decimal("100"))
    return EiPremiumResult(
        premium="awf",
        base_increment=vcr_result.base_increment,
        rate_pct=rate,
        amount=amount,
        vcr_family=VcrFamily.EI,
    )


def calculate_aof(
    vcr_result: VcrResult,
    decision: EmployerPremiumDecision,
    rates: EwPremiumRates,
) -> EiPremiumResult:
    """Aof premium for this period (NL-017)."""
    if decision.aof_size_class == "SMALL":
        rate = rates.aof_small_pct
    elif decision.aof_size_class == "LARGE":
        rate = rates.aof_large_pct
    else:
        raise ValueError(f"Unknown Aof size class: {decision.aof_size_class}")
    amount = round_eur(vcr_result.base_increment * rate / Decimal("100"))
    return EiPremiumResult(
        premium="aof",
        base_increment=vcr_result.base_increment,
        rate_pct=rate,
        amount=amount,
        vcr_family=VcrFamily.EI,
    )


def calculate_wko(
    vcr_result: VcrResult,
    rates: EwPremiumRates,
) -> EiPremiumResult:
    """Wko premium for this period (fixed 0.50%)."""
    rate = rates.wko_pct
    amount = round_eur(vcr_result.base_increment * rate / Decimal("100"))
    return EiPremiumResult(
        premium="wko",
        base_increment=vcr_result.base_increment,
        rate_pct=rate,
        amount=amount,
        vcr_family=VcrFamily.EI,
    )


@dataclass(frozen=True)
class WhkResult:
    """Whk result splits employer/employee parts (NL-018)."""
    employer_wga: Decimal
    employer_zw_flex: Decimal
    employer_total: Decimal
    employee_recoverable: Decimal  # net deduction from employee
    vcr_family: str = VcrFamily.EI


def calculate_whk(
    vcr_result: VcrResult,
    decision: EmployerPremiumDecision,
) -> WhkResult:
    """
    Whk = WGA + ZW Flex (both employer-paid).
    Employee-recoverable part of WGA becomes a separate net deduction.
    Fails closed if decision missing (NL-018).
    """
    if decision.whk_wga_pct is None or decision.whk_zw_flex_pct is None:
        raise ValueError("Whk decision missing WGA or ZW Flex rate — cannot calculate (NL-018)")

    base = vcr_result.base_increment
    wga = round_eur(base * decision.whk_wga_pct / Decimal("100"))
    zw_flex = round_eur(base * decision.whk_zw_flex_pct / Decimal("100"))
    employer_total = wga + zw_flex

    employee_recoverable = Decimal("0")
    if (decision.whk_wga_employee_recoverable_pct is not None
            and decision.whk_wga_employee_recoverable_pct > decision.whk_wga_pct):
        raise ValueError("Whk employee-recoverable % cannot exceed the WGA premium % (NL-018)")
    if decision.whk_wga_employee_recoverable_pct is not None:
        employee_recoverable = round_eur(base * decision.whk_wga_employee_recoverable_pct / Decimal("100"))

    return WhkResult(
        employer_wga=wga,
        employer_zw_flex=zw_flex,
        employer_total=employer_total,
        employee_recoverable=employee_recoverable,
    )


@dataclass(frozen=True)
class EiPeriodResult:
    """All employee-insurance premiums for one period."""
    awf: EiPremiumResult
    aof: EiPremiumResult
    wko: EiPremiumResult
    whk: WhkResult
    ei_base_increment: Decimal  # shared VCR EI base increment


def calculate_ei_period(
    vcr_result: VcrResult,
    contract: AwfContractFacts,
    decision: EmployerPremiumDecision,
    rates: EwPremiumRates,
) -> EiPeriodResult:
    """Calculate all EI premiums for a single period."""
    awf_res = calculate_awf(vcr_result, contract, rates)
    aof_res = calculate_aof(vcr_result, decision, rates)
    wko_res = calculate_wko(vcr_result, rates)
    whk_res = calculate_whk(vcr_result, decision)

    return EiPeriodResult(
        awf=awf_res,
        aof=aof_res,
        wko=wko_res,
        whk=whk_res,
        ei_base_increment=vcr_result.base_increment,
    )