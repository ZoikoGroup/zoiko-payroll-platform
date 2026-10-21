"""
engine/countries/mexico.py
--------------------------
Mexico payroll calculator (ZP-MX-ENG-001 v1.0). Pure: no ORM, no framework —
everything it reads arrives on the PayrollContext (the mx_* fields in
engine/base.py plus the pack rows in rate_map / slabs), resolved by
mexico_service.

Phase 5: the federal engine (ISR, employment subsidy, SBC, every IMSS branch,
CEAV, INFONAVIT) and the state ISN overlay, composed from
engine/jurisdictions/mexico/. Order: country guard → preflight (every block
reason at once) → hour-based lines → classification → SBC → IMSS / CEAV /
INFONAVIT → ISR + subsidy → ISN → entitlements → result. Every rate, tariff,
threshold and rule is a content row; a missing one BLOCKS (MX-001/MX-003).

Not reachable in production yet: mexico_service.calc_inputs — the only hook
that builds a real Mexican context — still raises MX_ENGINE_NOT_IMPLEMENTED
until Phase 6 wires the run.

Returns the generic keys (`tds` = ISR after subsidy; `mx_employee_total` =
IMSS employee branches + INFONAVIT credit, summed by engine/standard.py) and
one `mx_result` dict (employer totals and the MX-063 trace), like the
Netherlands' `nl_result`.
"""

from __future__ import annotations

from decimal import Decimal

from ..jurisdictions.mexico import (ceav, classification, entitlements, imss, infonavit, isn, isr, labor, preflight,
                                    sbc, special_pay, subsidy, termination, trace)
from ..jurisdictions.mexico.errors import MexicoCalculationBlockedError, MXBlock  # noqa: F401  (re-exported)

__all__ = ["ENGINE_VERSION", "MX_NO_FALLBACK", "MexicoCalculationBlockedError", "MXBlock", "calculate"]

_COUNTRY = "MX"
ENGINE_VERSION = "MX-ENGINE-2026.1"
_ZERO = Decimal("0")

# engine/fallback_registry.py sentinel: Mexico has NO hard-coded statutory
# fallback (master rules 2-3) — a missing pack row BLOCKS. Defined so the
# registry's attribute lookups resolve to a real (None) value.
MX_NO_FALLBACK = None


def calculate(ctx) -> dict:
    if (ctx.country or "").upper() != _COUNTRY:
        return {}
    try:
        return _calculate(ctx)
    except MXBlock as exc:
        if exc.organization_id is None:
            exc.organization_id = getattr(ctx, "mx_organization_id", None)
        raise


def _by_branch(lines, rnd) -> list:
    """Branch / side totals, each rounded once (the emitted amounts)."""
    groups: dict = {}
    for l in lines:
        groups.setdefault((l["branch"], l["side"]), []).append(l)
    return [{"branch": b, "side": s, "amount": rnd(sum((l["amount"] for l in ls), _ZERO)), "lines": ls}
            for (b, s), ls in groups.items()]


def _special_run(ctx, pre) -> dict:
    """Phase 9b: a run that pays ONE special concept on its own (aguinaldo).
    No ordinary period: no IMSS / CEAV / INFONAVIT (contributions are on the
    SBC per contribution day, Phase 5) and no employment subsidy; ISR is the
    transcribed rule's standalone withholding (MX-009); ISN follows the state's
    transcribed inclusion of the concept."""
    on, content, rnd, work_state = pre["on"], pre["content"], pre["round"], pre["work_state"]
    lines = pre["lines"]
    gross = sum((l["amount"] for l in lines), _ZERO)
    if ctx.gross is not None and Decimal(str(ctx.gross)) != gross:
        raise MXBlock("MX_GROSS_MISMATCH", f"the payslip gross {ctx.gross} is not the sum of its special lines {gross}")
    taxable = sum((l["isr_taxable"] for l in lines), _ZERO)
    exempt = sum((l["isr_exempt"] for l in lines), _ZERO)
    if pre["special_run"] == "FINIQUITO":
        # Phase 9c: the finiquito's lines are withheld together by the
        # transcribed finiquito rule (S24 / S25), per concept.
        concept = "FINIQUITO"
        by_concept = {}
        for l in lines:
            by_concept[l["kind"]] = by_concept.get(l["kind"], _ZERO) + l["isr_taxable"]
        withheld = rnd(termination.isr(by_concept, {**pre["facts"], "lines": lines}))
        rule_source = termination.rule_source()
    else:
        concept = special_pay.RUN_CONCEPTS[pre["special_run"]][0]
        rule = special_pay.rule(concept)
        withheld = rnd(special_pay._dec(rule.standalone_isr(taxable, pre["facts"]), "ISR amount"))
        rule_source = f"{rule.source} {rule.source_ref}"
    if withheld < _ZERO:
        raise MXBlock("MX_SPECIAL_PAY_RULE_INVALID", f"the {concept} rule returned a negative withholding")
    state_tax = isn.employer(lines, work_state, ctx.mx_isn_state_pack)
    isn_er = rnd(state_tax["amount"])
    result = {
        "engine_version": ENGINE_VERSION, "pay_date": on, "tariff_period": None, "days_paid": _ZERO,
        "contribution_days": _ZERO, "gross": gross, "isr_taxable": taxable, "isr": withheld, "isr_bracket": None,
        "subsidy": {"eligible": False, "amount": _ZERO, "applied": _ZERO, "remainder": _ZERO, "remainder_rule": None},
        "isr_withheld": withheld, "sbc": {"components": {}, "segments": []}, "imss": [], "risk_premium_pct": None,
        "imss_employee": _ZERO, "imss_employer": _ZERO, "infonavit_employer": _ZERO, "infonavit_employer_lines": [],
        "infonavit_credit": _ZERO, "infonavit_credit_lines": [], "isn": {**state_tax, "amount": isn_er},
        "employee_total": _ZERO, "employer_total": isn_er, "labor": {}, "entitlements": [],
        "concepts": trace.concepts(lines), "rounding_rule": rnd.text,
        "content_rows": trace.content_rows(content, state_tax["content"]), "pack": getattr(ctx, "mx_pack", None),
        "special": {"run_type": pre["special_run"], "concept": concept, "isr_exempt": exempt,
                    "rule_source": rule_source, "detail": getattr(ctx, "mx_special_detail", None)},
    }
    return {"tds": withheld, "mx_employee_total": _ZERO, "mx_result": trace.build(**result)}


def _calculate(ctx) -> dict:
    pre = preflight.run(ctx)
    if pre.get("special_run"):
        return _special_run(ctx, pre)
    on, content, period, rnd, work_state = pre["on"], pre["content"], pre["period"], pre["round"], pre["work_state"]
    profile, policy, zone = ctx.mx_profile, ctx.mx_labor_policy, ctx.mx_min_wage_zone
    daily_salary = Decimal(str(preflight.fact(profile, "mx_daily_salary")))

    # Labour: minimum wage, workweek, hour-based lines (MX-048–MX-050).
    min_wage = labor.minimum_wage(content, daily_salary, zone, preflight.fact(profile, "mx_professional_min_code"))
    week = labor.workweek(content, policy)
    hours = labor.hour_lines(content, ctx.mx_hours, policy, daily_salary)
    lines = pre["lines"] + classification.classify(hours["lines"], ctx.mx_classifications, on, work_state)
    gross = sum((l["amount"] for l in lines), _ZERO)
    if ctx.gross is not None and Decimal(str(ctx.gross)) != gross:
        raise MXBlock("MX_GROSS_MISMATCH",
                      f"the payslip gross {ctx.gross} is not the sum of its classified Mexican lines {gross}")

    # SBC and social security (per contribution segment, MX-021).
    year = sbc.service_year(preflight.fact(profile, "mx_seniority_date"), on)
    base = sbc.compute(daily_salary=daily_salary, policy=policy, seniority_date=preflight.fact(profile, "mx_seniority_date"),
                       on=on, lines=lines, accumulator=ctx.mx_variable_accumulator, segments=period.segments, zone=zone)
    segs = base["segments"]
    premium = imss.risk_premium_rate(ctx.mx_risk_premium, ctx.mx_registration, segs)
    social = imss.contributions(segs, premium)
    ceav_er = ceav.employer(segs, zone)
    housing = infonavit.employer(segs)
    credits = infonavit.credits(ctx.mx_infonavit_notices, period.start, period.end, segs, content)

    # ISR and employment subsidy (pay-date content, MX-013).
    taxable = sum((l["isr_taxable"] for l in lines), _ZERO)
    tax = isr.withholding(taxable, content.isr_tariff(period.tariff))
    sub = subsidy.subsidy(content, period.tariff, period.days_paid, taxable, ctx.mx_month_to_date)
    net_isr = subsidy.offset(content, rnd(tax["isr"]), rnd(sub["amount"]))

    state_tax = isn.employer(lines, work_state, ctx.mx_isn_state_pack)
    benefits = entitlements.entitlements(content, policy, year, daily_salary)

    imss_rows = _by_branch(social["lines"] + ceav_er["lines"], rnd)
    housing_er = rnd(housing["employer"])
    credit_ee = rnd(credits["employee"])
    isn_er = rnd(state_tax["amount"])
    imss_ee = sum((r["amount"] for r in imss_rows if r["side"] == "employee"), _ZERO)
    imss_er = sum((r["amount"] for r in imss_rows if r["side"] == "employer"), _ZERO)
    employee_total = imss_ee + credit_ee
    withholding = net_isr["withholding"]

    result = {
        "engine_version": ENGINE_VERSION, "pay_date": on, "tariff_period": period.tariff,
        "days_paid": period.days_paid, "contribution_days": period.contribution_days,
        "gross": gross, "isr_taxable": taxable, "isr": rnd(tax["isr"]), "isr_bracket": tax["bracket"],
        "subsidy": {**sub, "amount": rnd(sub["amount"]), "applied": net_isr["subsidy_applied"],
                    "remainder": net_isr["remainder"], "remainder_rule": net_isr["rule"]},
        "isr_withheld": withholding,
        "sbc": {"components": base["components"], "segments": segs},
        "imss": [{k: v for k, v in r.items()} for r in imss_rows], "risk_premium_pct": premium,
        "imss_employee": imss_ee, "imss_employer": imss_er,
        "infonavit_employer": housing_er, "infonavit_employer_lines": housing["lines"],
        "infonavit_credit": credit_ee, "infonavit_credit_lines": credits["lines"],
        "isn": {**state_tax, "amount": isn_er},
        "employee_total": employee_total, "employer_total": imss_er + housing_er + isn_er,
        "labor": {"minimum_wage": min_wage, "workweek": week, "overtime": hours["overtime"], "sunday": hours["sunday"]},
        "entitlements": benefits, "concepts": trace.concepts(lines),
        "rounding_rule": rnd.text,
        "content_rows": trace.content_rows(content, *[s["content"] for s in segs if s["content"] is not content],
                                           state_tax["content"]),
        "pack": getattr(ctx, "mx_pack", None),
    }
    return {"tds": withholding, "mx_employee_total": employee_total, "mx_result": trace.build(**result)}
