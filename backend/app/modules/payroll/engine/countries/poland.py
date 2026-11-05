"""modules/payroll/engine/countries/poland.py
-------------------------------------------
Poland (ZP-PL-ENG-001) — the calculation orchestrator over the bounded rule
modules in engine/jurisdictions/poland/ (spec §11: no monolithic "Poland
formula" class). Pure: immutable inputs + approved content + accumulator
snapshot -> deterministic result and trace. No ORM, no clock, no network
(PL-021).

Order (spec §12 "Calculation detail"):
  applicability (PL-006) -> pay components -> one base per obligation ->
  ZUS social (30x cap on pension/disability only) -> health (own base) ->
  PPK (uncapped pension base) -> PIT (cumulative, statements, costs, relief) ->
  employer funds -> net, employer cost, accumulator deltas, exceptions, hashes.

Platform mapping (standard.py):
  tds                   PIT advance
  pl_employee_total     ZUS employee (pension + disability + sickness) + health
                        + PPK employee — the ONLY other employee deduction key;
                        employee_esi / employee_pension are deliberately NOT
                        set (standard.py sums them too, which would double count)
  employer_esi          ZUS employer (pension + disability + accident)
  employer_payroll_tax  FP/FS + FGSP + FEP
  employer_pension      PPK employer
  pl_result             every base, component, decision, trace and hash

Labour-law checks (Phase 5): minimum wage on the MIN_WAGE base x FTE,
overtime only with its events, night supplement blocked until signed, pay
timing — breaches are run exceptions, never silent. Sickness / benefits
arrive in Phase 6.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import poland_content as content
from app.modules.payroll.engine.jurisdictions.poland import applicability as _applicability
from app.modules.payroll.engine.jurisdictions.poland import bases as _bases
from app.modules.payroll.engine.jurisdictions.poland import employer_funds as _funds
from app.modules.payroll.engine.jurisdictions.poland import errors as E
from app.modules.payroll.engine.jurisdictions.poland import health as _health
from app.modules.payroll.engine.jurisdictions.poland import labour as _labour
from app.modules.payroll.engine.jurisdictions.poland import pit as _pit
from app.modules.payroll.engine.jurisdictions.poland import ppk as _ppk
from app.modules.payroll.engine.jurisdictions.poland import zus as _zus
from app.modules.payroll.engine.jurisdictions.poland.errors import PLCalculationBlockedError  # noqa: F401 (re-export)
from app.modules.payroll.engine.jurisdictions.poland.pack import ZERO, PlPack, as_date, dec, field, money

ENGINE_BUILD = "PL-ENGINE-P3-2026.11"


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _sha(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _record(record, names) -> dict:
    return None if record is None else {n: field(record, n) for n in names}


_PROFILE_FIELDS = ("contract_type", "pay_frequency", "tax_residency", "fte_numerator", "fte_denominator", "cov_pension", "cov_disability",
                   "cov_sickness", "cov_accident", "cov_health", "other_titles_declared", "a1_certificate",
                   "is_student", "is_pensioner", "fep_qualifying", "fep_from", "fep_to", "fund_exemption_code",
                   "status", "effective_from", "effective_to")
_REGISTRATION_FIELDS = ("accident_rate_pct", "accident_rate_source", "accident_rate_from", "accident_rate_to",
                        "fp_fs_applicable", "fgsp_applicable", "ppk_employer_additional_pct", "status",
                        "effective_from", "effective_to")
_DECLARATION_FIELDS = ("id", "declaration_type", "status", "effective_from", "effective_to", "value")


def calculate(ctx: PayrollContext) -> dict:
    organization_id = getattr(ctx, "pl_organization_id", None)
    pay_date = as_date(getattr(ctx, "pl_pay_date", None) or getattr(ctx, "pay_date", None))
    if pay_date is None:
        raise PLCalculationBlockedError(E.PAY_DATE_MISSING, "the pay date decides every Polish rule (PL-003)",
                                        organization_id)
    pack = PlPack(ctx.rate_map, ctx.slabs, organization_id, pay_date)

    applicability = _applicability.determine(ctx, pack, pay_date)
    pay = _bases.components(ctx, pack)
    bases = _bases.build(pay, pack.earning_classes(), pack)
    _labour.night_supplement(pack, pay)
    overtime = _labour.overtime(pack, pay, getattr(ctx, "pl_overtime_events", None))
    minimum_wage = _labour.minimum_wage(pack, bases, applicability["profile"], getattr(ctx, "unpaid_leave_days", 0))
    pay_timing = _labour.pay_timing(pack, pay_date, getattr(ctx, "period_end", None))
    ytd = getattr(ctx, "pl_ytd", None)
    if ytd is None:
        pack.block(E.YTD_MISSING, "the year-to-date accumulator snapshot is not supplied")
    declarations = getattr(ctx, "pl_declarations", None) or []
    zus_round = pack.rounder("pl_rounding_zus")

    zus = _zus.compute(pack, bases, applicability, ytd, zus_round)
    health = _health.compute(pack, bases, applicability, zus["employeeTotal"])
    ppk = _ppk.compute(pack, bases, applicability, declarations, pay_date, pack.rounder("pl_rounding_ppk"))
    ppk_taxable = ppk["employerTotal"] if ppk["employerPitTreatment"] == "TAXABLE_EMPLOYEE_INCOME" else ZERO
    pit = _pit.compute(pack, bases, declarations, ytd, zus["employeeTotal"], ppk_taxable, pay_date)
    ytd_pension = dec(ytd["ZUS_CAP_PENSION_BASE"]) if ytd.get("ZUS_CAP_PENSION_BASE") is not None else None
    funds = _funds.compute(pack, bases, applicability, zus, ytd_pension, zus_round)

    gross = dec(ctx.gross)
    employee_total = zus["employeeTotal"] + health["amount"] + ppk["employeeTotal"]
    employer_total = zus["employerTotal"] + funds["total"] + ppk["employerTotal"]
    net = gross - pit["advance"] - employee_total

    exceptions = list(ppk["exceptions"])
    exceptions += [check["exception"] for check in (minimum_wage, pay_timing) if check["exception"]]
    if net < ZERO:
        exceptions.append({"code": E.EXC_NEGATIVE_NET, "detail": "statutory deductions exceed gross pay"})
    if zus["capCrossed"]:
        exceptions.append({"code": E.EXC_ANNUAL_CAP_CROSSED,
                           "detail": "the pension/disability annual base limit is reached in this run"})

    deltas = dict(pit["deltas"])
    if zus["pension"] is not None:
        deltas["ZUS_CAP_PENSION_BASE"] = zus["pension"]["assessed"]
    if zus["disability"] is not None:
        deltas["ZUS_CAP_DISABILITY_BASE"] = zus["disability"]["assessed"]
    if applicability["obligations"]["PPK"]["applies"]:
        deltas["PPK_EMPLOYEE"] = ppk["employeeTotal"]
        deltas["PPK_EMPLOYER"] = ppk["employerTotal"]
    unknown = set(deltas) - set(content.ACCUMULATORS)
    if unknown:
        raise RuntimeError(f"unknown Poland accumulator(s): {sorted(unknown)}")

    inputs = {
        "payDate": pay_date.isoformat(), "gross": str(gross), "components": {k: str(v) for k, v in pay.items()},
        "profile": _record(applicability["profile"], _PROFILE_FIELDS),
        "registration": _record(applicability["registration"], _REGISTRATION_FIELDS),
        "ppkState": field(getattr(ctx, "pl_ppk", None), "state"),
        "overtimeEvents": getattr(ctx, "pl_overtime_events", None),
        "unpaidLeaveDays": getattr(ctx, "unpaid_leave_days", 0),
        "periodEnd": getattr(ctx, "period_end", None),
        "declarations": sorted((_record(d, _DECLARATION_FIELDS) for d in declarations), key=_canonical),
        "ytd": {k: str(v) for k, v in sorted(ytd.items())},
    }
    used = pack.used()
    hashes = {"input": _sha(inputs), "content": _sha(used), "engineBuild": ENGINE_BUILD}

    obligations = {name: dict(o) for name, o in applicability["obligations"].items()}
    trace = {
        "jurisdiction": "PL", "spec": content.SPEC, "payDate": pay_date.isoformat(),
        "contractType": applicability["contractType"], "payFrequency": applicability["payFrequency"],
        "applicability": obligations, "bases": _bases.trace(bases), "zus": zus["trace"],
        "health": health["trace"], "ppk": ppk["trace"], "pit": pit["trace"], "funds": funds["trace"],
        "labour": {"minimumWage": {k: v for k, v in minimum_wage.items() if k != "exception"},
                   "overtime": overtime, "payTiming": {k: v for k, v in pay_timing.items() if k != "exception"}},
        "rounding": pack.rounding_events, "contentUsed": used, "hashes": hashes,
    }
    result = {
        "pl_pit_advance": money(pit["advance"]),
        "pl_pit_base": money(pit["base"]),
        "pl_zus_employee": {k: money(v) for k, v in zus["employee"].items()},
        "pl_zus_employer": {k: money(v) for k, v in zus["employer"].items()},
        "pl_health": money(health["amount"]),
        "pl_health_base": money(health["base"]),
        "pl_ppk_employee": {k: money(v) for k, v in ppk["employee"].items()},
        "pl_ppk_employer": {k: money(v) for k, v in ppk["employer"].items()},
        "pl_funds": {k: money(v) for k, v in funds["amounts"].items()},
        "pl_employee_total": money(employee_total),
        "pl_employer_total": money(employer_total),
        "pl_net": money(net),
        "obligations": obligations,
        "accumulatorDeltas": {k: money(v) for k, v in sorted(deltas.items())},
        "exceptions": exceptions,
        "hashes": hashes,
        "trace": trace,
    }
    return {
        "tds": pit["advance"],
        "pl_employee_total": employee_total,
        "employer_esi": zus["employerTotal"],
        "employer_payroll_tax": funds["total"],
        "employer_pension": ppk["employerTotal"],
        "pl_result": result,
    }
