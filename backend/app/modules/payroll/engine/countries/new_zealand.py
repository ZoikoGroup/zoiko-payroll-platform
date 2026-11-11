"""New Zealand (ZP-NZ-ENG-001) payday engine - pure, deterministic and fail-closed.

Pipeline (spec §3-§7): guards -> pay components -> one base per obligation ->
PAYE -> ACC earner levy -> student loan -> KiwiSaver / ESCT -> approved
deduction order -> child support -> minimum-wage check -> result, trace and
hashes. No database, clock, network or settings are read (NZ-022): every
input arrives on the PayrollContext and every statutory value comes from the
resolved pack through NzPack, selected by the payday (NZ-008).

Payment kinds (Phase 6): REGULAR, OUT_OF_CYCLE, LUMP_SUM,
HOLIDAY_PAY_ADVANCE, FINAL and CORRECTION. Lump sums, final holiday pay and
alternative-method holiday advances are taxed on the extra-pay path; ACC and
KiwiSaver take the combined base so the ACC cap is shared (NZ-013). Leave pay
arrives pre-calculated (nz_leave_lines) and replaces the ordinary pay it
displaces; any top-up must already be in the run's gross.
"""
from __future__ import annotations

from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import new_zealand_content as content
from app.modules.payroll.engine.jurisdictions.new_zealand import acc_earner_levy as _acc
from app.modules.payroll.engine.jurisdictions.new_zealand import child_support as _cs
from app.modules.payroll.engine.jurisdictions.new_zealand import components as _comp
from app.modules.payroll.engine.jurisdictions.new_zealand import deduction_precedence as _prec
from app.modules.payroll.engine.jurisdictions.new_zealand import errors as E
from app.modules.payroll.engine.jurisdictions.new_zealand import extra_pay as _extra
from app.modules.payroll.engine.jurisdictions.new_zealand import hashing as _hash
from app.modules.payroll.engine.jurisdictions.new_zealand import kiwisaver as _ks
from app.modules.payroll.engine.jurisdictions.new_zealand import minimum_wage as _mw
from app.modules.payroll.engine.jurisdictions.new_zealand import paye as _paye
from app.modules.payroll.engine.jurisdictions.new_zealand import student_loan as _sl
from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError
from app.modules.payroll.engine.jurisdictions.new_zealand.pack import (
    ZERO, NzPack, dec, field, in_window, money, normalise_frequency, upper)

__all__ = ["NZCalculationBlockedError", "calculate", "resolve_applicability", "ENGINE_VERSION"]
ENGINE_VERSION = "nz-engine-1"
REGULAR = "REGULAR"
OUT_OF_CYCLE, LUMP_SUM, ADVANCE, FINAL, CORRECTION = (
    "OUT_OF_CYCLE", "LUMP_SUM", "HOLIDAY_PAY_ADVANCE", "FINAL", "CORRECTION")
EXTRA_OBLIGATIONS = ("PAYE", "ACC", "KIWISAVER", "STUDENT_LOAN")


def _organization_id(ctx):
    return getattr(ctx, "nz_organization_id", None) or getattr(ctx, "organization_id", None)


def payday(ctx):
    """The run's payday (NZ-008): nz_pay_date when the service supplied it
    (a preview's pay_date is the period end), else pay_date."""
    return getattr(ctx, "nz_pay_date", None) or ctx.pay_date


def _require_active(pack: NzPack, record, missing_code: str, name: str, pay_date) -> None:
    if record is None:
        pack.block(missing_code, f"no New Zealand {name} is in force")
    if upper(field(record, "status")) != "ACTIVE" or not in_window(
            field(record, "effective_from"), field(record, "effective_to"), pay_date):
        pack.block(E.keyed(E.PROFILE_NOT_ACTIVE, name.replace(" ", "_")),
                   f"the New Zealand {name} is not ACTIVE on the payday")


def resolve_applicability(ctx: PayrollContext, pack: NzPack) -> dict:
    on = payday(ctx)
    if on is None:
        pack.block(E.PAY_DATE_MISSING, "the payday selects every New Zealand rule (NZ-008)")
    frequency = normalise_frequency(ctx.pay_frequency)
    if frequency not in pack.text_list("nz_supported_pay_frequencies"):
        pack.block(E.FREQUENCY_UNSUPPORTED, f"{ctx.pay_frequency!r} pay is not supported")
    currency = upper(getattr(ctx, "currency", None))
    if currency and currency != content.CURRENCY:
        pack.block(E.CURRENCY_UNSUPPORTED, f"{currency} is not an NZD payroll")
    _require_active(pack, ctx.nz_employer_profile, E.EMPLOYER_PROFILE_MISSING, "employer profile", on)
    _require_active(pack, ctx.nz_tax_profile, E.TAX_PROFILE_MISSING, "tax profile", on)
    if upper(field(ctx.nz_tax_profile, "residency_status")) != "RESIDENT":
        pack.block(E.NON_RESIDENT_UNSUPPORTED, "non-resident payroll is outside the first release")
    code = _paye.resolve_tax_code(ctx.nz_tax_profile, pack)
    kind = upper(ctx.nz_payment_kind) or REGULAR
    if kind not in content.PAYMENT_KINDS:
        pack.block(E.PAYMENT_KIND_UNSUPPORTED, f"{kind} is not a New Zealand payment kind")
    return {"frequency": frequency, "taxCode": code, "profile": ctx.nz_tax_profile, "paymentKind": kind}


def _money_map(values: dict) -> dict:
    return {key: money(value) for key, value in values.items()}


def _lines(lines: list) -> list:
    return [{"component": l["component"], "amount": money(l["amount"]), "treatment": l["treatment"],
             "counted": money(l["counted"])} for l in lines]


def _named_components(ctx, kind: str, pack: NzPack) -> dict:
    """The per-payment-kind component view: a LUMP_SUM / HOLIDAY_PAY_ADVANCE
    run's gross is its lump sum / holiday pay; leave pay replaces the ordinary
    pay it displaces (SALARY), and any top-up must already be in gross."""
    named = dict(ctx.nz_components or {})
    gross, options = dec(ctx.gross), ctx.nz_run_options or {}
    if kind == LUMP_SUM and not named:
        comp = upper(options.get("lumpSumComponent")) or "LUMP_SUM"
        if comp not in ("BONUS", "LUMP_SUM"):
            pack.block(E.COMPONENTS_INVALID, f"lump-sum component {comp!r} is not BONUS or LUMP_SUM")
        named = {"SALARY": ZERO, "OVERTIME": ZERO, comp: gross}
    if kind == ADVANCE and not named:
        named = {"SALARY": ZERO, "OVERTIME": ZERO, "HOLIDAY_PAY": gross}
    leave, final = list(ctx.nz_leave_lines or []), list(ctx.nz_final_pay_lines or [])
    if not (leave or final):
        return named
    paid = sum((dec(field(line, "amount")) for line in leave + final), ZERO)
    displaced = sum((dec(field(line, "displaced")) for line in leave), ZERO)
    salary = dec(named["SALARY"]) if "SALARY" in named else dec(ctx.basic)
    if displaced > salary:
        pack.block(E.COMPONENTS_INVALID, "the ordinary pay displaced by leave exceeds the period's salary")
    named["SALARY"] = salary - displaced
    named["HOLIDAY_PAY"] = dec(named.get("HOLIDAY_PAY")) + paid
    named.setdefault("OVERTIME", dec(ctx.overtime))
    shortfall = sum((dec(value) for value in named.values()), ZERO) - gross
    if shortfall > ZERO:
        pack.block(E.LEAVE_TOP_UP_NOT_IN_GROSS,
                   f"holiday pay exceeds the ordinary pay it replaces by {money(shortfall)}: add it to the "
                   "period's gross (additional compensation) before calculating")
    return named


def _split(components: list, classes: dict, kind: str, options, final_amount: Decimal, pack: NzPack) -> tuple:
    """(regular, extra, method): `extra` holds what this payment kind pays on
    the extra-pay path (LUMP_SUM_PATH components, final holiday pay, and all
    of an EXTRA_PAY out-of-cycle or ALTERNATIVE holiday-advance payment)."""
    method = None
    if kind == OUT_OF_CYCLE:
        method = pack.text("nz_out_of_cycle_paye_method", allowed=("EXTRA_PAY", "PERIOD_MAIN"))
    if kind == ADVANCE:
        method = _extra.advance_method(options, pack)
    all_extra = (kind == OUT_OF_CYCLE and method == "EXTRA_PAY") or (kind == ADVANCE and method[0] == "ALTERNATIVE")
    regular, extra, final_left = [], [], final_amount
    for component, amount in components:
        if all_extra or classes.get(("PAYE", component)) == _comp.LUMP_SUM_PATH:
            extra.append((component, amount))
        elif component == "HOLIDAY_PAY" and final_left > ZERO:
            final = min(final_left, amount)
            final_left -= final
            extra.append((component, final))
            if amount > final:
                regular.append((component, amount - final))
        else:
            regular.append((component, amount))
    if kind == LUMP_SUM:
        if regular:
            pack.block(E.LUMP_SUM_MIXED, "a lump sum is its own payment: salary or wages cannot be in it")
        if not extra:
            pack.block(E.COMPONENTS_INVALID, "a lump-sum payment has no lump-sum component")
    return regular, extra, method


def _regular_paye(base: Decimal, code, profile, frequency: str, pay_date, kind: str, method, pack: NzPack):
    """PAYE on the regular base; a STANDARD holiday-pay advance spreads it over
    the periods it covers. No regular base -> no regular PAYE."""
    if base <= ZERO:
        return _paye.PayeResult(ZERO, "NONE", None, [])
    if kind == ADVANCE and method and method[0] == "STANDARD":
        periods = Decimal(method[1])
        per = _paye.calculate_paye(base / periods, code, profile, frequency, pay_date, pack)
        steps = per.steps + [{"step": "advanceSpread", "value": money(per.paye * periods),
                              "note": f"{money(per.paye)} x {method[1]} periods"}]
        return _paye.PayeResult(per.paye * periods, "STANDARD_ADVANCE", per.period_factor, steps)
    return _paye.calculate_paye(base, code, profile, frequency, pay_date, pack)


def calculate(ctx: PayrollContext) -> dict:
    pack = NzPack(ctx.rate_map, ctx.slabs, _organization_id(ctx), payday(ctx))
    app = resolve_applicability(ctx, pack)
    pay_date, frequency, code, profile = payday(ctx), app["frequency"], app["taxCode"], app["profile"]
    kind = app["paymentKind"]

    classes = _comp.earning_classes(pack)
    components = _comp.pay_components(ctx, pack, _named_components(ctx, kind, pack))
    final_amount = sum((dec(field(line, "amount")) for line in ctx.nz_final_pay_lines or []), ZERO)
    regular, extra, method = _split(components, classes, kind, ctx.nz_run_options, final_amount, pack)
    mw_applies = kind in (REGULAR, FINAL, CORRECTION) or (kind == OUT_OF_CYCLE and method == "PERIOD_MAIN")
    bases = {name: _comp.obligation_base(name, components if name == "HOLIDAY_GROSS" else regular, classes, pack)
             if name != "MIN_WAGE" or mw_applies else {"base": ZERO, "lines": []}
             for name in _comp.BASES}
    extra_bases = {name: _comp.extra_base(name, extra, classes, pack) for name in EXTRA_OBLIGATIONS} if extra else {}
    extra_of = {name: extra_bases[name]["base"] if extra else ZERO for name in EXTRA_OBLIGATIONS}
    notices = list(ctx.nz_authority_deductions or [])

    paye = _regular_paye(bases["PAYE"]["base"], code, profile, frequency, pay_date, kind, method, pack)
    xpaye = _extra.extra_pay_paye(extra_of["PAYE"], ctx.nz_prior_four_week_gross, code, profile, frequency,
                                  pay_date, pack)
    acc = _acc.calculate_levy(bases["ACC"]["base"] + extra_of["ACC"], ctx.nz_accumulators, pack)
    sl = _sl.calculate_student_loan(bases["STUDENT_LOAN"]["base"], code, profile, frequency, pay_date, notices, pack)
    xsl, xsl_steps = _extra.extra_pay_student_loan(extra_of["STUDENT_LOAN"], code, profile, pay_date, pack)
    dob = ctx.nz_date_of_birth or getattr(ctx, "date_of_birth", None)
    ks = _ks.calculate_kiwisaver(bases["KIWISAVER"]["base"] + extra_of["KIWISAVER"], ctx.nz_kiwisaver, dob,
                                 pay_date, pack)

    paye_total = paye.paye + xpaye.paye
    sl_total = sl.deduction + xsl
    order = _prec.precedence(pack)
    gross = dec(ctx.gross)
    amounts = {"PAYE": paye_total, "ACC_LEVY": acc.levy, "STUDENT_LOAN": sl_total, "KS_EMPLOYEE": ks.employee}
    net_before_cs = gross - sum((amounts[item] for item in _prec.before(order, "CHILD_SUPPORT")), ZERO)
    if net_before_cs < ZERO:
        pack.block(E.NEGATIVE_NET, "statutory deductions exceed gross pay; the case needs specialist review")
    cs = _cs.calculate_child_support(net_before_cs, notices, pay_date, pack)
    if mw_applies:
        mw = _mw.check_minimum_wage(bases["MIN_WAGE"]["base"], ctx.nz_hours, ctx.nz_hours_source,
                                    field(profile, "min_wage_category"), pack)
    else:
        mw = _mw.MinWageResult("NOT_APPLICABLE", f"{kind} is not a period's pay for hours worked")

    tds = paye_total + acc.levy
    employee_total = sl_total + ks.employee + cs.deduction
    net_pay = gross - tds - employee_total
    exceptions = [e for e in (_mw.exception_for(mw),) if e]
    if cs.shortfall > ZERO:
        exceptions.append({"code": E.EXC_CS_SHORTFALL, "shortfall": money(cs.shortfall),
                           "variationCode": cs.variation_code})

    result = {
        "paymentKind": kind,
        "taxCode": code.code, "incomeClass": code.income_class, "frequency": frequency,
        "payDate": pay_date.isoformat(),
        "bases": {name: money(b["base"]) for name, b in bases.items()},
        "baseLines": {name: _lines(b["lines"]) for name, b in bases.items()},
        "obligations": _money_map({
            "paye": paye_total, "payeRegular": paye.paye, "payeExtra": xpaye.paye, "accLevy": acc.levy,
            "payeTotal": tds, "studentLoan": sl_total, "studentLoanStandard": sl.standard,
            "studentLoanExtra": sl.extra, "studentLoanExtraPay": xsl,
            "ksEmployee": ks.employee, "ksEmployerGross": ks.employer_gross, "esct": ks.esct,
            "ksEmployerNet": ks.employer_net, "childSupport": cs.deduction}),
        "employeeTotal": money(employee_total),
        "netPay": money(net_pay),
        "extraPay": None if not extra else {
            "method": xpaye.method, "bases": {name: money(b["base"]) for name, b in extra_bases.items()},
            "lines": {name: _lines(b["lines"]) for name, b in extra_bases.items()}},
        "leavePay": [dict(line) for line in ctx.nz_leave_lines or []],
        "finalPay": [dict(line) for line in ctx.nz_final_pay_lines or []],
        "runOptions": dict(ctx.nz_run_options or {}),
        "kiwisaver": {"status": ks.status,
                      "employeeRate": None if ks.employee_rate is None else str(ks.employee_rate),
                      "employerRate": None if ks.employer_rate is None else str(ks.employer_rate),
                      "esctRate": None if ks.esct_rate is None else str(ks.esct_rate),
                      "compulsoryEmployer": ks.compulsory_employer, "reductionApplied": ks.reduction_applied,
                      "destination": ks.destination, "complyingFundRef": ks.complying_fund_ref},
        "acc": {"liable": money(acc.liable), "cap": money(acc.cap), "ytdBefore": money(acc.ytd_before),
                "ytdAfter": money(acc.ytd_after), "capCrossed": acc.cap_crossed,
                "capReachedBefore": acc.cap_reached_before},
        "studentLoan": {"basis": sl.basis, "threshold": None if sl.threshold is None else money(sl.threshold)},
        "childSupport": {"required": money(cs.required), "maxAllowed": money(cs.max_allowed),
                         "protectedNet": money(cs.protected_net), "shortfall": money(cs.shortfall),
                         "variationCode": cs.variation_code, "notices": cs.notices},
        "minimumWage": {"status": mw.status, "reason": mw.reason,
                        "effectiveRate": None if mw.effective_rate is None else str(mw.effective_rate),
                        "floor": None if mw.floor is None else str(mw.floor), "category": mw.category,
                        "hours": None if mw.hours is None else str(mw.hours), "hoursSource": mw.hours_source},
        "precedence": order,
        "accumulatorDeltas": _money_map({
            "ACC_LIABLE_EARNINGS": acc.liable, "PAYE_GROSS": bases["PAYE"]["base"] + extra_of["PAYE"],
            "PAYE": paye_total, "ACC_LEVY": acc.levy,
            "KS_GROSS": bases["KIWISAVER"]["base"] + extra_of["KIWISAVER"], "KS_EMPLOYEE": ks.employee,
            "KS_EMPLOYER_GROSS": ks.employer_gross, "ESCT": ks.esct, "STUDENT_LOAN": sl_total,
            "CHILD_SUPPORT": cs.deduction}),
        "exceptions": exceptions,
        "trace": {"traceId": getattr(ctx, "trace_id", None), "engineVersion": ENGINE_VERSION,
                  "periodFactor": None if paye.period_factor is None else str(paye.period_factor),
                  "paye": paye.steps, "extraPaye": xpaye.steps, "acc": acc.steps,
                  "studentLoan": sl.steps + xsl_steps, "kiwisaver": ks.steps,
                  "childSupport": cs.steps, "minimumWage": mw.steps,
                  "roundingEvents": pack.rounding_events, "rowsUsed": pack.used()},
    }
    result["hashes"] = _hash.hashes(_hash.input_document(ctx, components, ks.age), pack.used(), result)
    return {"tds": tds, "nz_employee_total": employee_total, "employer_pension": ks.employer_gross,
            "nz_result": result}
