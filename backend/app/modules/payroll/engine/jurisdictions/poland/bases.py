"""Poland base builder (ZP-PL-ENG-001 §11 "Base builder", PL-008 / PL-014 / PL-015).

Builds one independent base per obligation (PIT, EMERYTALNE, RENTOWE,
CHOROBOWE, WYPADKOWE, ZDROWOTNE, FP_FS, FGSP, FEP, PPK, MIN_WAGE) from the pay
components and the signed PL_EARNING_CLASS rows — never a universal "taxable
gross". Every line keeps its inclusion reason. A component that is unknown,
unclassified, or classified REVIEW with a non-zero amount BLOCKS.
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland.pack import ZERO, PlPack, dec, money, upper


def components(ctx, pack: PlPack) -> dict:
    """{component: amount}. Explicit ``pl_components`` must reconcile to gross;
    without them only a pure base-salary gross is mapped (SALARY = basic)."""
    raw = getattr(ctx, "pl_components", None)
    gross = dec(ctx.gross)
    if raw is None:
        if dec(ctx.basic) != gross or dec(getattr(ctx, "overtime", ZERO)) != ZERO:
            pack.block(E.COMPONENTS_UNMAPPED, "gross contains pay that is not mapped to a Polish pay component")
        return {"SALARY": gross}
    out = {}
    for name, amount in raw.items():
        component = upper(name)
        if component not in content.POLAND_COMPONENTS:
            pack.block(E.keyed(E.COMPONENT_UNKNOWN, component or "NONE"), "unknown Polish pay component")
        value = dec(amount)
        if value < ZERO:
            pack.block(E.keyed(E.COMPONENTS_MISMATCH, component), "a pay component cannot be negative")
        out[component] = out.get(component, ZERO) + value
    if sum(out.values(), ZERO) != gross:
        pack.block(E.COMPONENTS_MISMATCH, "pay components do not add up to gross pay")
    return out


def build(pay: dict, classes: dict, pack: PlPack) -> dict:
    """{obligation: {"base": Decimal, "lines": [{component, amount, treatment}]}}."""
    out = {}
    for obligation in content.OBLIGATIONS:
        base, lines = ZERO, []
        for component, amount in sorted(pay.items()):
            treatment = classes.get((obligation, component))
            if treatment is None:
                pack.block(E.keyed(E.EARNING_CLASS_MISSING, f"{obligation}:{component}"),
                           "the component is not classified for this obligation")
            if treatment == "REVIEW" and amount != ZERO:
                pack.block(E.keyed(E.EARNING_CLASS_REVIEW, f"{obligation}:{component}"),
                           "the treatment is not signed; a non-zero amount cannot be calculated")
            if treatment == "INCLUDED":
                base += amount
            lines.append({"component": component, "amount": money(amount), "treatment": treatment})
        out[obligation] = {"base": base, "lines": lines}
    return out


def trace(bases: dict) -> dict:
    return {name: {"base": money(b["base"]), "lines": b["lines"]} for name, b in bases.items()}


def as_decimal(bases: dict, obligation: str) -> Decimal:
    return bases[obligation]["base"]
