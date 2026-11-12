"""modules/payroll/engine/countries/belgium.py
--------------------------------------------
Belgium (ZP-BE-ENG-001) — the calculation orchestrator over the bounded rule
modules in engine/jurisdictions/belgium/ (Block A3). Pure: immutable inputs +
signed content -> deterministic result, trace and hashes. No ORM, no clock.

Order (implementation plan §8; G-01 awaits specialist confirmation):
  pay date and pack -> applicability resolver (§2, fail closed) -> earning
  classification (BE-006) -> independent bases (BE-007) -> ONSS employee (108%
  base for manual / assimilated workers only) -> social work bonus ->
  withholding taxable basis -> regular withholding -> family layer -> fiscal
  work bonus -> exceptional withholding (separate strategy) -> employer ONSS
  lines kept separate -> net, employer cost, obligation deltas, exceptions,
  hashes.

Supported scope (BE-004, release-1 scope G-27): ordinary RESIDENT payroll on
exactly ONE employment line per pay period; structural / target-group
reductions and benefits in kind (company car) block whenever they apply; the
BSSC only ever raises BE_BSSC_PENDING (D7). Pay basis (G-22) and contract (G-23)
come from the recorded profile / classification; platform pay maps to Belgian
components through the organisation's ACTIVE mappings (G-28); the 1.60% line
follows the employer's recorded status (G-25).

Platform mapping (standard.py):
  tds                 regular + exceptional withholding
  be_employee_total   employee ONSS after the social work bonus — the ONLY other
                      employee deduction key (employee_esi / employee_pension
                      are deliberately not set: standard.py would double count)
  employer_esi        employer ONSS base + wage moderation + special + funds
  employer_pension    occupational-pension special contribution
  be_result           every base, line, decision, exception, used row and hash
Manual-worker holiday contributions go to obligation deltas only.
No statutory value lives in this module: every figure is a signed pack row.
"""
from __future__ import annotations

import hashlib
import json

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import belgium_content as content
from app.modules.payroll.engine.jurisdictions.belgium import applicability as _applicability
from app.modules.payroll.engine.jurisdictions.belgium import bases as _bases
from app.modules.payroll.engine.jurisdictions.belgium import declarations as _declarations
from app.modules.payroll.engine.jurisdictions.belgium import errors as E
from app.modules.payroll.engine.jurisdictions.belgium import formula as _formula
from app.modules.payroll.engine.jurisdictions.belgium import onss as _onss
from app.modules.payroll.engine.jurisdictions.belgium import withholding as _withholding
from app.modules.payroll.engine.jurisdictions.belgium.errors import BECalculationBlockedError
from app.modules.payroll.engine.jurisdictions.belgium.pack import ZERO, BePack, as_date, dec

__all__ = ["BECalculationBlockedError", "calculate", "ENGINE_BUILD"]

ENGINE_BUILD = "BE-ENGINE-A3-2026.11"


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _sha(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _money(value) -> str:
    return str(dec(value))


def calculate(ctx: PayrollContext) -> dict:
    organization_id = getattr(ctx, "be_organization_id", None) or getattr(ctx, "organization_id", None)
    pay_date = as_date(getattr(ctx, "be_pay_date", None) or getattr(ctx, "pay_date", None))
    if pay_date is None:
        raise BECalculationBlockedError(E.PAY_DATE_MISSING, "the pay date selects every Belgian rule (BE-009)",
                                        organization_id)
    pack = BePack(ctx.rate_map, ctx.slabs, organization_id, pay_date)
    period_start = as_date(getattr(ctx, "period_start", None))

    decision = _applicability.require(_applicability.resolve(
        pack, pay_date, registration=getattr(ctx, "be_registration", None),
        profile=getattr(ctx, "be_profile", None), classifications=getattr(ctx, "be_classifications", None) or (),
        schedules=getattr(ctx, "be_schedules", None) or (), units=getattr(ctx, "be_units", None) or {},
        agreements=getattr(ctx, "be_agreements", None) or {},
        declarations=getattr(ctx, "be_declarations", None) or (),
        pay_frequency=getattr(ctx, "be_pay_frequency", None), period_start=period_start), organization_id)
    line = decision["employmentLines"][0]          # the resolver admits exactly one line (G-27)

    pay = _bases.components(ctx, pack)
    manual = decision["worker"]["onssManualBase"] is True
    built = _bases.build(pay, pack.earning_classes(), pack, manual)
    approved = _declarations.approved(pack, getattr(ctx, "be_declarations", None) or (), pay_date)
    onss = _onss.compute(pack, built["bases"], decision, getattr(ctx, "be_pension_premium", None))
    wht = _withholding.compute(pack, pay, built, decision, approved, onss,
                               getattr(ctx, "be_exceptional_reference", None), getattr(ctx, "be_pack_version", None))

    gross = dec(ctx.gross)
    employee_total = onss["employeeNet"]
    employer_total = onss["employerEsi"] + onss["pensionSpecial"]
    net = gross - wht["total"] - employee_total

    exceptions = [{"code": e["code"], "detail": e["reason"]} for e in decision["exceptions"]]
    exceptions += onss["exceptions"]
    if net < ZERO:
        exceptions.append({"code": E.EXC_NEGATIVE_NET, "detail": "statutory deductions exceed gross pay"})

    bases = built["bases"]
    deltas = {"WITHHOLDING_TAXABLE": wht["regularTaxable"], "WITHHOLDING": wht["regular"],
              "WITHHOLDING_EXCEPTIONAL_TAXABLE": wht["exceptionalTaxable"],
              "WITHHOLDING_EXCEPTIONAL": wht["exceptional"],
              "ONSS_EMPLOYEE_BASE": onss["employeeBase"], "ONSS_EMPLOYEE": onss["employeeNet"],
              "ONSS_EMPLOYER_BASE": onss["employerBase"], "WORK_BONUS_SOCIAL": onss["socialWorkBonus"],
              "WORK_BONUS_FISCAL": wht["fiscalWorkBonus"], "HOLIDAY_PAY_BASE": bases["HOLIDAY_BASE"]}
    if manual:
        deltas["ONSS_MANUAL_108_BASE"] = onss["employeeBase"]
    unknown = set(deltas) - set(content.ACCUMULATORS)
    if unknown:
        raise RuntimeError(f"unknown Belgium accumulator(s): {sorted(unknown)}")

    inputs = {
        "payDate": pay_date.isoformat(), "periodStart": getattr(ctx, "period_start", None),
        "periodEnd": getattr(ctx, "period_end", None), "gross": str(gross),
        "components": {k: str(v) for k, v in sorted(pay.items())},
        "sourcePeriods": _bases.source_periods(ctx, pay),
        "decision": {k: decision[k] for k in ("employer", "worker", "employmentLines", "declarations")},
        "pensionPremium": getattr(ctx, "be_pension_premium", None),
        "exceptionalReference": getattr(ctx, "be_exceptional_reference", None),
        "ytd": {k: str(v) for k, v in sorted((getattr(ctx, "be_ytd", None) or {}).items())},
    }
    used = pack.used()
    hashes = {"input": _sha(inputs), "content": _sha(used), "engineBuild": ENGINE_BUILD,
              "interpreter": _formula.INTERPRETER_VERSION}
    trace = {"jurisdiction": "BE", "spec": content.SPEC, "payDate": pay_date.isoformat(),
             "packVersion": getattr(ctx, "be_pack_version", None), "employmentLine": line["employmentLine"],
             "bases": _bases.trace(built), "sourcePeriods": inputs["sourcePeriods"], "onss": onss["trace"],
             "withholding": wht["trace"], "rounding": pack.rounding_events, "contentUsed": used, "hashes": hashes}
    result = {
        "be_withholding": _money(wht["total"]),
        "be_withholding_regular": _money(wht["regular"]),
        "be_withholding_exceptional": {g: {k: _money(v) for k, v in line_.items()}
                                       for g, line_ in wht["exceptionalLines"].items()},
        "be_fiscal_work_bonus": _money(wht["fiscalWorkBonus"]),
        "be_onss_employee": _money(onss["employeeContribution"]),
        "be_social_work_bonus": _money(onss["socialWorkBonus"]),
        "be_onss_employer": {k: _money(v) for k, v in onss["employerLines"].items()},
        "be_funds": {k: _money(v) for k, v in onss["funds"].items()},
        "be_pension_special": _money(onss["pensionSpecial"]),
        "be_employee_total": _money(employee_total),
        "be_employer_total": _money(employer_total),
        "be_net": _money(net),
        "bases": {k: _money(v) for k, v in bases.items()},
        "decision": {"decision": decision["decision"], "confidence": decision["confidence"],
                     "employer": decision["employer"], "worker": decision["worker"],
                     "employmentLines": decision["employmentLines"]},
        "employmentLine": line["employmentLine"],
        "sourcePeriods": inputs["sourcePeriods"],
        "obligationDeltas": {k: _money(v) for k, v in onss["obligationDeltas"].items()},
        "accumulatorDeltas": {k: _money(v) for k, v in sorted(deltas.items())},
        "exceptions": exceptions,
        "usedRows": used,
        "hashes": hashes,
        "trace": trace,
    }
    return {
        "tds": wht["total"],
        "be_employee_total": employee_total,
        "employer_esi": onss["employerEsi"],
        "employer_pension": onss["pensionSpecial"],
        "be_result": result,
    }
