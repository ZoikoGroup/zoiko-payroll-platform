"""Pay components and per-obligation bases (spec "Critical refinements").

There is no universal "taxable gross": every obligation takes its own base
from the components the signed NZ_EARNING_CLASS rows include. A REVIEW
treatment blocks when its component is non-zero; LUMP_SUM_PATH blocks until
the lump-sum method exists (Phase 6). HOLIDAY_GROSS (Holidays Act gross
earnings, Phase 5) never changes pay, so it never blocks the payslip: an
unreviewed component is recorded as not counted and Phase 6 leave pay refuses
to use it (NZ-017).
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.countries import new_zealand_content as content
from . import errors as E
from .pack import ZERO, NzPack, dec, field, upper

BASES = ("PAYE", "ACC", "KIWISAVER", "STUDENT_LOAN", "MIN_WAGE", "HOLIDAY_GROSS")
RECORD_ONLY = ("HOLIDAY_GROSS",)
INCLUDED, EXCLUDED, LUMP_SUM_PATH, REVIEW = content.TREATMENTS
_DIRECT = ("SALARY", "OVERTIME", "OTHER_EARNINGS")


def pay_components(ctx, pack: NzPack) -> list:
    """[(component, amount)] for every component above zero, in content order."""
    named = {}
    for key, value in (getattr(ctx, "nz_components", None) or {}).items():
        name = upper(key)
        if name not in content.NZ_COMPONENTS:
            pack.block(E.COMPONENTS_INVALID, f"unknown pay component {name!r}")
        named[name] = dec(value)
    amounts = {"SALARY": named["SALARY"] if "SALARY" in named else dec(ctx.basic),
               "OVERTIME": named["OVERTIME"] if "OVERTIME" in named else dec(ctx.overtime)}
    for name in content.NZ_COMPONENTS:
        if name not in _DIRECT:
            amounts[name] = named.get(name, ZERO)
    if "OTHER_EARNINGS" in named:
        amounts["OTHER_EARNINGS"] = named["OTHER_EARNINGS"]
    else:
        amounts["OTHER_EARNINGS"] = dec(ctx.gross) - sum(amounts.values(), ZERO)
    for name, amount in amounts.items():
        if amount < ZERO:
            pack.block(E.COMPONENTS_INVALID,
                       f"pay component {name} is negative" if name != "OTHER_EARNINGS"
                       else "the named pay components exceed gross pay")
    return [(name, amounts[name]) for name in content.NZ_COMPONENTS if amounts[name] > ZERO]


def earning_classes(pack: NzPack) -> dict:
    rows = pack.table(content.NZ_EARNING_CLASS_RULE, "earning_classes")
    return {(upper(field(r, "tax_regime")), upper(field(r, "filing_status"))): upper(field(r, "assessment_basis"))
            for r in rows}


def obligation_base(obligation: str, components: list, classes: dict, pack: NzPack,
                    block_on_review: bool = None) -> dict:
    if block_on_review is None:
        block_on_review = obligation not in RECORD_ONLY
    base, lines = ZERO, []
    for component, amount in components:
        treatment = classes.get((obligation, component))
        if treatment is None:
            pack.block(E.keyed(E.EARNING_CLASS_MISSING, obligation, component),
                       f"{component} has no {obligation} classification")
        if not block_on_review and treatment in (REVIEW, LUMP_SUM_PATH):
            lines.append({"component": component, "amount": amount, "treatment": treatment, "counted": ZERO})
            continue
        if treatment == REVIEW:
            pack.block(E.keyed(E.EARNING_CLASS_REVIEW, obligation, component),
                       f"{component} ({amount}) is REVIEW for {obligation}: it needs a signed treatment")
        if treatment == LUMP_SUM_PATH:
            pack.block(E.LUMP_SUM_UNSUPPORTED,
                       f"{component} is paid on the lump-sum path, which is not available yet")
        if treatment not in (INCLUDED, EXCLUDED):
            pack.block(E.keyed(E.EARNING_CLASS_MISSING, obligation, component),
                       f"unknown treatment {treatment!r}")
        counted = amount if treatment == INCLUDED else ZERO
        base += counted
        lines.append({"component": component, "amount": amount, "treatment": treatment, "counted": counted})
    return {"base": base, "lines": lines}
