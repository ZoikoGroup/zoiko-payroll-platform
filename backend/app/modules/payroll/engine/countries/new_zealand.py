"""New Zealand (ZP-NZ-ENG-001) payday engine - pure, deterministic and fail-closed.

Pipeline (spec §3-§7): guards -> pay components -> one base per obligation ->
PAYE -> ACC earner levy -> student loan -> KiwiSaver / ESCT -> approved
deduction order -> child support -> minimum-wage check -> result, trace and
hashes. No database, clock, network or settings are read (NZ-022): every
input arrives on the PayrollContext and every statutory value comes from the
resolved pack through NzPack, selected by the payday (NZ-008).

Only REGULAR paydays are calculated (Phase 3); lump sums, holiday pay, final
pay and corrections arrive with Phase 6 and are refused until then.
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


def _organization_id(ctx):
    return getattr(ctx, "nz_organization_id", None) or getattr(ctx, "organization_id", None)


def _require_active(pack: NzPack, record, missing_code: str, name: str, pay_date) -> None:
    if record is None:
        pack.block(missing_code, f"no New Zealand {name} is in force")
    if upper(field(record, "status")) != "ACTIVE" or not in_window(
            field(record, "effective_from"), field(record, "effective_to"), pay_date):
        pack.block(E.keyed(E.PROFILE_NOT_ACTIVE, name.replace(" ", "_")),
                   f"the New Zealand {name} is not ACTIVE on the payday")


def resolve_applicability(ctx: PayrollContext, pack: NzPack) -> dict:
    if ctx.pay_date is None:
        pack.block(E.PAY_DATE_MISSING, "the payday selects every New Zealand rule (NZ-008)")
    frequency = normalise_frequency(ctx.pay_frequency)
    if frequency not in pack.text_list("nz_supported_pay_frequencies"):
        pack.block(E.FREQUENCY_UNSUPPORTED, f"{ctx.pay_frequency!r} pay is not supported")
    currency = upper(getattr(ctx, "currency", None))
    if currency and currency != content.CURRENCY:
        pack.block(E.CURRENCY_UNSUPPORTED, f"{currency} is not an NZD payroll")
    _require_active(pack, ctx.nz_employer_profile, E.EMPLOYER_PROFILE_MISSING, "employer profile", ctx.pay_date)
    _require_active(pack, ctx.nz_tax_profile, E.TAX_PROFILE_MISSING, "tax profile", ctx.pay_date)
    if upper(field(ctx.nz_tax_profile, "residency_status")) != "RESIDENT":
        pack.block(E.NON_RESIDENT_UNSUPPORTED, "non-resident payroll is outside the first release")
    code = _paye.resolve_tax_code(ctx.nz_tax_profile, pack)
    kind = upper(ctx.nz_payment_kind) or REGULAR
    if kind != REGULAR:
        pack.block(E.PAYMENT_KIND_UNSUPPORTED, f"{kind} payments are not available yet")
    return {"frequency": frequency, "taxCode": code, "profile": ctx.nz_tax_profile, "paymentKind": kind}


def _money_map(values: dict) -> dict:
    return {key: money(value) for key, value in values.items()}


def _lines(lines: list) -> list:
    return [{"component": l["component"], "amount": money(l["amount"]), "treatment": l["treatment"],
             "counted": money(l["counted"])} for l in lines]


def calculate(ctx: PayrollContext) -> dict:
    pack = NzPack(ctx.rate_map, ctx.slabs, _organization_id(ctx), ctx.pay_date)
    app = resolve_applicability(ctx, pack)
    pay_date, frequency, code, profile = ctx.pay_date, app["frequency"], app["taxCode"], app["profile"]

    components = _comp.pay_components(ctx, pack)
    classes = _comp.earning_classes(pack)
    bases = {name: _comp.obligation_base(name, components, classes, pack) for name in _comp.BASES}
    notices = list(ctx.nz_authority_deductions or [])

    paye = _paye.calculate_paye(bases["PAYE"]["base"], code, profile, frequency, pay_date, pack)
    acc = _acc.calculate_levy(bases["ACC"]["base"], ctx.nz_accumulators, pack)
    sl = _sl.calculate_student_loan(bases["STUDENT_LOAN"]["base"], code, profile, frequency, pay_date, notices, pack)
    dob = ctx.nz_date_of_birth or getattr(ctx, "date_of_birth", None)
    ks = _ks.calculate_kiwisaver(bases["KIWISAVER"]["base"], ctx.nz_kiwisaver, dob, pay_date, pack)

    order = _prec.precedence(pack)
    gross = dec(ctx.gross)
    amounts = {"PAYE": paye.paye, "ACC_LEVY": acc.levy, "STUDENT_LOAN": sl.deduction, "KS_EMPLOYEE": ks.employee}
    net_before_cs = gross - sum((amounts[item] for item in _prec.before(order, "CHILD_SUPPORT")), ZERO)
    if net_before_cs < ZERO:
        pack.block(E.NEGATIVE_NET, "statutory deductions exceed gross pay; the case needs specialist review")
    cs = _cs.calculate_child_support(net_before_cs, notices, pay_date, pack)
    mw = _mw.check_minimum_wage(bases["MIN_WAGE"]["base"], ctx.nz_hours, ctx.nz_hours_source,
                                field(profile, "min_wage_category"), pack)

    tds = paye.paye + acc.levy
    employee_total = sl.deduction + ks.employee + cs.deduction
    net_pay = gross - tds - employee_total
    exceptions = [e for e in (_mw.exception_for(mw),) if e]
    if cs.shortfall > ZERO:
        exceptions.append({"code": E.EXC_CS_SHORTFALL, "shortfall": money(cs.shortfall),
                           "variationCode": cs.variation_code})

    result = {
        "paymentKind": app["paymentKind"],
        "taxCode": code.code, "incomeClass": code.income_class, "frequency": frequency,
        "payDate": pay_date.isoformat(),
        "bases": {name: money(b["base"]) for name, b in bases.items()},
        "baseLines": {name: _lines(b["lines"]) for name, b in bases.items()},
        "obligations": _money_map({
            "paye": paye.paye, "accLevy": acc.levy, "payeTotal": tds,
            "studentLoan": sl.deduction, "studentLoanStandard": sl.standard, "studentLoanExtra": sl.extra,
            "ksEmployee": ks.employee, "ksEmployerGross": ks.employer_gross, "esct": ks.esct,
            "ksEmployerNet": ks.employer_net, "childSupport": cs.deduction}),
        "employeeTotal": money(employee_total),
        "netPay": money(net_pay),
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
            "ACC_LIABLE_EARNINGS": acc.liable, "PAYE_GROSS": bases["PAYE"]["base"], "PAYE": paye.paye,
            "ACC_LEVY": acc.levy, "KS_GROSS": bases["KIWISAVER"]["base"], "KS_EMPLOYEE": ks.employee,
            "KS_EMPLOYER_GROSS": ks.employer_gross, "ESCT": ks.esct, "STUDENT_LOAN": sl.deduction,
            "CHILD_SUPPORT": cs.deduction}),
        "exceptions": exceptions,
        "trace": {"traceId": getattr(ctx, "trace_id", None), "engineVersion": ENGINE_VERSION,
                  "periodFactor": None if paye.period_factor is None else str(paye.period_factor),
                  "paye": paye.steps, "acc": acc.steps, "studentLoan": sl.steps, "kiwisaver": ks.steps,
                  "childSupport": cs.steps, "minimumWage": mw.steps,
                  "roundingEvents": pack.rounding_events, "rowsUsed": pack.used()},
    }
    result["hashes"] = _hash.hashes(_hash.input_document(ctx, components, ks.age), pack.used(), result)
    return {"tds": tds, "nz_employee_total": employee_total, "employer_pension": ks.employer_gross,
            "nz_result": result}
