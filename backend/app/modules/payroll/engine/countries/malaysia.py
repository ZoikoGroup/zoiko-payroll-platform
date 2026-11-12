"""modules/payroll/engine/countries/malaysia.py
---------------------------------------------
Malaysia (ZP-MY-ENG-001) — the calculation orchestrator over the bounded rule
modules in engine/jurisdictions/malaysia/ (no monolithic "Malaysia formula").
Pure: immutable inputs + signed content + accumulator snapshot ->
deterministic result and trace. No ORM, no clock, no network.

Order (spec §12 / §13 gross-to-net):
  coverage per obligation (MY-004 / MY-008) -> pay components -> one base per
  obligation -> EPF (Third Schedule) -> PERKESO Act 4 (own / foreign-worker
  schedule, wage ceiling) -> EIS Act 800 -> HRD levy (employer cost) -> PCB
  (Phase 4; blocks until the HASiL specification is archived) -> minimum-wage
  test -> net, employer cost, accumulator deltas, exceptions, hashes.

MY-008: every obligation is evaluated on its own. If any obligation is
blocked, the payslip is refused with MY_OBLIGATIONS_BLOCKED, naming each
blocked obligation and its reason (``blocked``) and carrying what was computed
(``partial``) — a net is never built on a skipped obligation.

Platform mapping (standard.py):
  tds                   PCB (+ CP38 from Phase 4)
  my_employee_total     EPF employee + SOCSO employee + EIS employee — the ONLY
                        other employee deduction key (employee_esi /
                        employee_pension are deliberately NOT set: standard.py
                        sums them too, which would double count)
  employer_pension      EPF employer
  employer_esi          SOCSO employer + EIS employer
  employer_payroll_tax  HRD levy (employer cost; never in net pay, MY-015)
  my_result             coverage, bases, schedule rows used, trace, hashes
"""
from __future__ import annotations

import hashlib
import json

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.engine.jurisdictions.malaysia import applicability as _applicability
from app.modules.payroll.engine.jurisdictions.malaysia import bases as _bases
from app.modules.payroll.engine.jurisdictions.malaysia import eis as _eis
from app.modules.payroll.engine.jurisdictions.malaysia import epf as _epf
from app.modules.payroll.engine.jurisdictions.malaysia import errors as E
from app.modules.payroll.engine.jurisdictions.malaysia import hrd as _hrd
from app.modules.payroll.engine.jurisdictions.malaysia import minimum_wage as _minimum_wage
from app.modules.payroll.engine.jurisdictions.malaysia import pcb as _pcb
from app.modules.payroll.engine.jurisdictions.malaysia import perkeso as _perkeso
from app.modules.payroll.engine.jurisdictions.malaysia.errors import MYCalculationBlockedError  # noqa: F401 (re-export)
from app.modules.payroll.engine.jurisdictions.malaysia.pack import ZERO, MyPack, as_date, field, money
from app.modules.payroll.engine.jurisdictions.malaysia.periods import legal_periods

ENGINE_BUILD = "MY-ENGINE-P3-2026.11"
_PROFILE_FIELDS = ("contract_type", "pay_frequency", "citizenship", "date_of_birth", "tax_residence",
                   "work_pass_type", "work_pass_valid_to", "epf_member_class", "socso_category", "eis_state",
                   "manual_worker", "normal_hours_week", "status", "effective_from", "effective_to")
_REGISTRATION_FIELDS = ("hrd_category", "hrd_category_from", "verification_state", "status", "effective_from",
                        "effective_to")
_DECLARATION_FIELDS = ("id", "declaration_type", "tax_year", "status", "effective_from", "effective_to", "value")


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _sha(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _record(record, names) -> dict:
    return None if record is None else {n: field(record, n) for n in names}


def calculate(ctx: PayrollContext) -> dict:
    org = getattr(ctx, "my_organization_id", None)
    pay_date = as_date(getattr(ctx, "my_pay_date", None) or getattr(ctx, "pay_date", None))
    if pay_date is None:
        raise MYCalculationBlockedError(E.PAY_DATE_MISSING, "the pay date decides every Malaysian rule", org)
    start, end = as_date(getattr(ctx, "period_start", None)), as_date(getattr(ctx, "period_end", None))
    if start is None or end is None or end < start:
        raise MYCalculationBlockedError(E.PERIOD_MISSING, "the pay period decides the wage / contribution month "
                                        "(MY-006)", org)
    pack = MyPack(ctx.rate_map, ctx.slabs, org, pay_date)
    applicability = _applicability.determine(ctx, pack, pay_date, start, end)
    coverage, blocked = applicability["coverage"], dict(applicability["blocked"])
    profile = applicability["profile"]
    pay = _bases.components(ctx, pack)
    classes = pack.earning_classes()
    declarations = getattr(ctx, "my_declarations", None) or []
    results, base_trace = {}, {}

    def attempt(name, fn):
        try:
            results[name] = fn()
        except MYCalculationBlockedError as exc:
            blocked[name] = {"code": exc.key, "reason": exc.reason}

    def base_of(obligation):
        entry = _bases.base(pay, classes, obligation, pack)
        base_trace[obligation] = _bases.trace(entry)
        return entry["base"]

    if "EPF" in coverage:
        attempt("EPF", lambda: _epf.compute(pack, base_of("EPF"), coverage["EPF"], declarations, end)
                if coverage["EPF"]["applies"] else None)
    if "SOCSO" in coverage:
        attempt("SOCSO", lambda: _perkeso.compute(pack, base_of("SOCSO"), coverage["SOCSO"])
                if coverage["SOCSO"]["applies"] else None)
    if "EIS" in coverage:
        attempt("EIS", lambda: _eis.compute(pack, base_of("EIS")) if coverage["EIS"]["applies"] else None)
    if "HRD" in coverage:
        attempt("HRD", lambda: _hrd.compute(pack, base_of("HRD"), coverage["HRD"])
                if coverage["HRD"]["applies"] else None)
    attempt("PCB", lambda: _pcb.compute(pack, normal=base_of("PCB_NORMAL"), additional=base_of("PCB_ADDITIONAL"),
                                        epf=results.get("EPF"), declarations=declarations, profile=profile,
                                        residence=_applicability.residence(profile)))
    minimum_wage = None
    try:
        minimum_wage = _minimum_wage.check(pack, base_of("MIN_WAGE_BASIC"), pay, profile,
                                           getattr(ctx, "my_assignment", None), start, end,
                                           getattr(ctx, "unpaid_leave_days", 0))
    except MYCalculationBlockedError as exc:
        blocked["MIN_WAGE"] = {"code": exc.key, "reason": exc.reason}

    def side(name, key):
        result = results.get(name)
        return result[key] if result else ZERO

    trace = {
        "jurisdiction": "MY", "spec": content.SPEC, "payDate": pay_date.isoformat(),
        "period": [start.isoformat(), end.isoformat()], "legalPeriods": legal_periods(pay_date, end),
        "contractType": applicability["contractType"], "payFrequency": applicability["payFrequency"],
        "coverage": coverage, "bases": base_trace,
        "components": {k: money(v) for k, v in sorted(pay.items())},
        "obligations": {name: (r or {}).get("trace") for name, r in results.items()},
        "minimumWage": minimum_wage and {k: v for k, v in minimum_wage.items() if k != "exception"},
        "rounding": pack.rounding_events, "contentUsed": pack.used(),
    }
    if blocked:
        detail = "; ".join(f"{name}: {b['code']}" for name, b in sorted(blocked.items()))
        raise MYCalculationBlockedError(E.OBLIGATIONS_BLOCKED, f"obligation(s) blocked - {detail}", org,
                                        blocked=blocked, partial=trace)

    gross = sum(pay.values(), ZERO)
    employee_total = side("EPF", "employee") + side("SOCSO", "employee") + side("EIS", "employee")
    pcb = results["PCB"]["pcb"]
    net = gross - pcb - employee_total
    exceptions = [minimum_wage["exception"]] if minimum_wage and minimum_wage["exception"] else []
    if net < ZERO:
        exceptions.append({"code": E.EXC_NEGATIVE_NET, "detail": "statutory deductions exceed gross pay"})
    deltas = {"EPF_EE": side("EPF", "employee"), "EPF_ER": side("EPF", "employer"),
              "SOCSO_EE": side("SOCSO", "employee"), "SOCSO_ER": side("SOCSO", "employer"),
              "EIS_EE": side("EIS", "employee"), "EIS_ER": side("EIS", "employer"),
              "HRD_LEVY": side("HRD", "employer"), "PCB_PAID": pcb}
    inputs = {"payDate": pay_date.isoformat(), "period": trace["period"], "gross": str(gross),
              "components": trace["components"], "profile": _record(profile, _PROFILE_FIELDS),
              "registration": _record(applicability["registration"], _REGISTRATION_FIELDS),
              "assignment": _record(getattr(ctx, "my_assignment", None), ("labour_territory", "holiday_state",
                                                                           "effective_from", "effective_to")),
              "declarations": sorted((_record(d, _DECLARATION_FIELDS) for d in declarations), key=_canonical),
              "ytd": {k: str(v) for k, v in sorted((getattr(ctx, "my_ytd", None) or {}).items())},
              "unpaidLeaveDays": getattr(ctx, "unpaid_leave_days", 0)}
    hashes = {"input": _sha(inputs), "content": _sha(pack.used()), "engineBuild": ENGINE_BUILD}
    trace["hashes"] = hashes
    result = {
        "my_pcb": money(pcb),
        "my_epf": {"employee": money(side("EPF", "employee")), "employer": money(side("EPF", "employer"))},
        "my_socso": {"employee": money(side("SOCSO", "employee")), "employer": money(side("SOCSO", "employer"))},
        "my_eis": {"employee": money(side("EIS", "employee")), "employer": money(side("EIS", "employer"))},
        "my_hrd": money(side("HRD", "employer")),
        "my_employee_total": money(employee_total),
        "my_employer_total": money(side("EPF", "employer") + side("SOCSO", "employer") + side("EIS", "employer")
                                   + side("HRD", "employer")),
        "my_net": money(net),
        "coverage": coverage,
        "accumulatorDeltas": {k: money(v) for k, v in sorted(deltas.items())},
        "exceptions": exceptions, "hashes": hashes, "trace": trace,
    }
    return {
        "tds": pcb,
        "my_employee_total": employee_total,
        "employer_pension": side("EPF", "employer"),
        "employer_esi": side("SOCSO", "employer") + side("EIS", "employer"),
        "employer_payroll_tax": side("HRD", "employer"),
        "my_result": result,
    }
