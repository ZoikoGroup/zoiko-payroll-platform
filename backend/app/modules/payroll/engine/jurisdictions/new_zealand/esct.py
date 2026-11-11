"""Employer superannuation contribution tax (spec §4).

The employee's ESCT rate is fixed at the start of the tax year from a
prior-year or estimated basis amount. The stored rate must equal the signed
ESCT band rate for that amount; a disagreement blocks.
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.countries import new_zealand_content as content
from . import errors as E
from .pack import HUNDRED, ZERO, NzPack, dec, field, opt_dec, upper


def band_rate(amount: Decimal, bands: list) -> Decimal:
    """The rate (a percent number) of the band holding `amount`
    (min < amount <= max; max None = open). An amount of zero takes the first band."""
    for band in bands:
        low, high = dec(field(band, "min_amount")), opt_dec(field(band, "max_amount"))
        if (amount > low or amount <= ZERO) and (high is None or amount <= high):
            return dec(field(band, "rate_pct"))
    return dec(field(bands[-1], "rate_pct"))


def resolve_esct_rate(election, pack: NzPack) -> dict:
    bands = pack.table(content.NZ_ESCT_BAND_RULE, "esct_bands")
    rate, basis_amount = field(election, "esct_rate_pct"), field(election, "esct_basis_amount")
    basis = upper(field(election, "esct_basis"))
    if rate is None or basis_amount is None:
        pack.block(E.ESCT_RATE_UNRESOLVED, "the employee's ESCT rate or its basis amount is not recorded")
    if basis not in content.ESCT_BASES:
        pack.block(E.ESCT_RATE_UNRESOLVED, f"ESCT basis {basis or 'missing'!r} is not recognised")
    expected = band_rate(dec(basis_amount), bands)
    if expected != dec(rate):
        pack.block(E.ESCT_RATE_UNRESOLVED,
                   f"the recorded ESCT rate {dec(rate)}% does not match the band rate {expected}% for its basis")
    return {"rate": dec(rate), "basis": basis, "basisAmount": dec(basis_amount),
            "taxYear": field(election, "esct_tax_year")}


def calculate_esct(employer_gross: Decimal, rate: Decimal, pack: NzPack) -> Decimal:
    return pack.rounder("nz_esct_rounding")(employer_gross * rate / HUNDRED)
