"""
modules/payroll/engine/countries/dominican_republic.py
------------------------------------------------------------
Dominican Republic (DO) — Phase 1 statutory build (ZP-DO-ENG-001).

Independent statutory bases (DO-006/DO-007), never merged into one number:
  1. SFS — employee 3.04% / employer 7.09%, capped at the current
     monthly ceiling (RD$232,230 from 1 Feb 2026). Reused fields:
     `social_security` / `employer_social_security`.
  2. Pension (SVDS) — employee 2.87% / employer 7.10%, capped at its own
     independent ceiling (RD$464,460). Reused fields: `employee_pension`
     / `employer_pension`.
  3. Occupational risk (SRL) — employer-only, capped at its own
     independent ceiling (RD$92,892). The employer's actual risk-type
     add-on (I-IV: 0.10/0.15/0.20/0.30 pp) is an agency-assigned,
     employer-specific fact (TSS classifies each employer) — resolved
     from an `EmployerTaxProfile` row (jurisdiction_id="DO",
     component_code="do_srl") when one exists for this org, same
     mechanism US SUI / Germany accident insurance already use; falls
     back to a single configurable default rate (1.10%, risk type I,
     matching the spec's own F1 fixture) when no profile is configured
     yet. Reused field: `employer_payroll_tax`.
  4. INFOTEP — employer-only 1% on the ordinary payroll base, uncapped
     (the separate 0.5% WORKER contribution only applies to covered
     profit/bonus distributions under Law 116-80, not ordinary salary —
     DO-022 — and is therefore not modelled as a recurring deduction
     here). Reused field: `employer_ni`.
  5. ISR — DGII's monthly withholding method: taxable = gross - employee
     SFS - employee pension, then annual bands via `ctx.slabs` (canonical
     TaxSlab rows for country="DO") through the generic
     `_calculate_annual_tax` bracket engine, annualized/de-annualized
     like Barbados/Jamaica. Reused field: `tds`.

The 1 February 2026 ceiling change (DO-009) and the 1 January 2027 ISR
scale change (DO's own "2026/2027 transition control") both require
signed content-boundary testing that isn't built yet — this module
always uses whichever ceiling/band values are currently configured
(canonical or fallback), with no date-based branching of its own.

Validated against ZP-DO-ENG-001 §13 fixture F1 (RD$50,000/mo, risk type
I, the module's own default) and F2's SFS/pension/ISR figures; F2's own
risk-type-II SRL rate (1.15%) is proven separately via a configured
EmployerTaxProfile row — see tests/test_dominican_republic.py.
"""

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext, _round2
from app.modules.payroll.engine.countries.shared import (
    resolve_periods_per_year,
    resolve_jurisdiction_parameter,
    _calculate_annual_tax,
)

_DO_SFS_EMPLOYEE_RATE = Decimal("0.0304")
_DO_SFS_EMPLOYER_RATE = Decimal("0.0709")
_DO_SFS_CEILING = Decimal("232230")

_DO_PENSION_EMPLOYEE_RATE = Decimal("0.0287")
_DO_PENSION_EMPLOYER_RATE = Decimal("0.0710")
_DO_PENSION_CEILING = Decimal("464460")

_DO_SRL_RATE = Decimal("0.0110")  # 1.00% base + 0.10pp risk type I — see module docstring
_DO_SRL_CEILING = Decimal("92892")

_DO_INFOTEP_EMPLOYER_RATE = Decimal("0.01")


def calculate(ctx: PayrollContext) -> dict:
    """Dominican Republic: SFS + pension (each independently capped) +
    SRL (employer-only, capped) + INFOTEP (employer-only, uncapped) +
    ISR (annualized bracket lookup on gross minus employee SFS/pension)."""
    rate_map = ctx.rate_map
    periods_per_year = resolve_periods_per_year(ctx.pay_frequency)
    period_gross = ctx.gross

    sfs_ceiling = resolve_jurisdiction_parameter(rate_map, "do_sfs_ceiling", _DO_SFS_CEILING, country="DO")
    sfs_base = min(period_gross, sfs_ceiling)
    sfs_employee_rate = resolve_jurisdiction_parameter(rate_map, "do_sfs", _DO_SFS_EMPLOYEE_RATE, side="employee", country="DO")
    sfs_employer_rate = resolve_jurisdiction_parameter(rate_map, "do_sfs", _DO_SFS_EMPLOYER_RATE, side="employer", country="DO")
    social_security = _round2(sfs_base * sfs_employee_rate)
    employer_social_security = _round2(sfs_base * sfs_employer_rate)

    pension_ceiling = resolve_jurisdiction_parameter(rate_map, "do_pension_ceiling", _DO_PENSION_CEILING, country="DO")
    pension_base = min(period_gross, pension_ceiling)
    pension_employee_rate = resolve_jurisdiction_parameter(rate_map, "do_pension", _DO_PENSION_EMPLOYEE_RATE, side="employee", country="DO")
    pension_employer_rate = resolve_jurisdiction_parameter(rate_map, "do_pension", _DO_PENSION_EMPLOYER_RATE, side="employer", country="DO")
    employee_pension = _round2(pension_base * pension_employee_rate)
    employer_pension = _round2(pension_base * pension_employer_rate)

    srl_ceiling = resolve_jurisdiction_parameter(rate_map, "do_srl_ceiling", _DO_SRL_CEILING, country="DO")
    srl_base = min(period_gross, srl_ceiling)
    # DO-007's real risk-type add-on (I-IV) is an agency-assigned,
    # employer-specific fact (TSS classifies each employer), not an org
    # policy choice — same EmployerTaxProfile mechanism US SUI / Germany
    # accident insurance already use (see service.py's
    # _resolve_employee_calc_inputs jurisdiction_id resolution). A
    # configured profile OVERRIDES the rate_map/hardcoded default entirely;
    # EmployerTaxProfile.employer_rate_pct is a percentage NUMBER (e.g.
    # 1.10 for 1.10%), not a fraction — divide by 100, matching how
    # engine/countries/us.py reads its own SUI profile.
    srl_profile = (ctx.employer_tax_profiles or {}).get("do_srl")
    if srl_profile is not None and srl_profile.employer_rate_pct is not None:
        srl_rate = srl_profile.employer_rate_pct / Decimal("100")
    else:
        srl_rate = resolve_jurisdiction_parameter(rate_map, "do_srl", _DO_SRL_RATE, side="employer", country="DO")
    employer_payroll_tax = _round2(srl_base * srl_rate)  # SRL — see module docstring

    infotep_rate = resolve_jurisdiction_parameter(rate_map, "do_infotep", _DO_INFOTEP_EMPLOYER_RATE, side="employer", country="DO")
    employer_ni = _round2(period_gross * infotep_rate)   # INFOTEP employer — see module docstring

    isr_base_period = max(period_gross - social_security - employee_pension, Decimal("0"))
    taxable_annualized = isr_base_period * periods_per_year
    tds = _round2(_calculate_annual_tax(taxable_annualized, ctx.slabs) / periods_per_year)

    return dict(
        tds=tds,
        social_security=social_security,
        employer_social_security=employer_social_security,
        employee_pension=employee_pension,
        employer_pension=employer_pension,
        employer_payroll_tax=employer_payroll_tax,
        employer_ni=employer_ni,
    )
