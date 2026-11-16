"""Malaysia base builder (ZP-MY-ENG-001 §1, §5-§9).

Builds one independent base per obligation (PCB normal / additional, EPF,
SOCSO, EIS, HRD, minimum-wage basic, overtime-rate base) from the pay
components and the signed MY_EARNING_CLASS rows — never a universal "taxable
gross". Each earning code is classified independently for every obligation
(spec §1). An unclassified component, or a REVIEW component with a non-zero
amount, blocks THAT obligation only (MY-008).
"""
from __future__ import annotations

from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia.pack import ZERO, MyPack, dec, money, upper


def platform_components(ctx) -> dict:
    """The platform's salary structure as Malaysian pay components (Phase 11),
    used when no explicit ``my_components`` are supplied. Gross is built as
    basic + HRA + special allowance + configured allowances + overtime +
    attendance extras (service._compute_payslip_values), so:

      basic                                   -> BASIC_SALARY
      the fixed salary-structure remainder     -> FIXED_ALLOWANCE
        (HRA, special and configured allowances: fixed monthly pay)
      overtime                                -> OVERTIME (needs approved events)
      attendance extras (variable)            -> VARIABLE_ALLOWANCE

    Each is then classified per obligation by the signed earning classes; a
    REVIEW treatment with an amount blocks that obligation — never a guess.
    Returns None when the parts do not reconcile (a negative remainder)."""
    gross, basic = dec(ctx.gross), dec(ctx.basic)
    overtime = dec(getattr(ctx, "overtime", ZERO))
    extras = dec(getattr(ctx, "additional_compensation", ZERO))
    fixed = gross - basic - overtime - extras
    if min(basic, overtime, extras, fixed) < ZERO:
        return None
    parts = {"BASIC_SALARY": basic, "FIXED_ALLOWANCE": fixed, "OVERTIME": overtime, "VARIABLE_ALLOWANCE": extras}
    return {k: v for k, v in parts.items() if v != ZERO or k == "BASIC_SALARY"}


def components(ctx, pack: MyPack) -> dict:
    """{component: amount}. Explicit ``my_components`` must reconcile to gross;
    without them the platform's salary structure is mapped (platform_components)."""
    raw = getattr(ctx, "my_components", None)
    gross = dec(ctx.gross)
    if raw is None:
        mapped = platform_components(ctx)
        if mapped is None:
            pack.block(E.COMPONENTS_UNMAPPED, "gross does not reconcile to the platform salary structure")
        return mapped
    out = {}
    for name, amount in raw.items():
        component = upper(name)
        if component not in content.COMPONENTS:
            pack.block(E.keyed(E.COMPONENT_UNKNOWN, component or "NONE"), "unknown Malaysian pay component")
        value = dec(amount)
        if value < ZERO:
            pack.block(E.keyed(E.COMPONENTS_MISMATCH, component), "a pay component cannot be negative")
        out[component] = out.get(component, ZERO) + value
    if sum(out.values(), ZERO) != gross:
        pack.block(E.COMPONENTS_MISMATCH, "pay components do not add up to gross pay")
    return out


def base(pay: dict, classes: dict, obligation: str, pack: MyPack) -> dict:
    """{"base": Decimal, "lines": [...]} for ONE obligation; blocks on an
    unclassified or REVIEW (non-zero) component."""
    total, lines = ZERO, []
    for component, amount in sorted(pay.items()):
        treatment = classes.get((obligation, component))
        if treatment is None:
            pack.block(E.keyed(E.EARNING_CLASS_MISSING, f"{obligation}:{component}"),
                       "the component is not classified for this obligation")
        if treatment == "REVIEW" and amount != ZERO:
            pack.block(E.keyed(E.EARNING_CLASS_REVIEW, f"{obligation}:{component}"),
                       "the treatment is not signed; a non-zero amount cannot be calculated")
        if treatment == "INCLUDED":
            total += amount
        lines.append({"component": component, "amount": money(amount), "treatment": treatment})
    return {"base": total, "lines": lines}


def trace(entry: dict) -> dict:
    return {"base": money(entry["base"]), "lines": entry["lines"]}
