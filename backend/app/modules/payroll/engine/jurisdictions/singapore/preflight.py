"""
engine/jurisdictions/singapore/preflight.py
-------------------------------------------
Singapore payroll-run preflight and exceptions — ZP-SG-ENG-001 §11 stages 1
(Preflight: "Material statutory uncertainty blocks calculate/approve") and
4 (Exceptions: low-wage formula, SPR status change, AW ceiling, PWM/LQS
shortfall, IR21 overdue — "Resolve/block before commit"), SG-030.

Pure: every statutory decision comes from the calculation engine itself —
service.py dry-runs engine/countries/singapore.calculate read-only (or
reads a persisted trace) and hands the trace or the engine's BLOCK here.
This module only turns those into operator checks; it evaluates no rate.

Severity: BLOCK (approval refused), WARN (review, approval allowed), INFO.
"""

from datetime import date

from app.modules.payroll.engine.countries.singapore import (
    SingaporeCalculationBlockedError, resolve_cpf_age_band, resolve_spr_year, _month_end,
)

BLOCK, WARN, INFO = "BLOCK", "WARN", "INFO"
_IR21_HOLD_STATUSES = ("DRAFT", "FILED", "CLEARED", "EXCEPTION")


def check(code, severity, message, employee=None, source=None, action=None):
    out = {"code": code, "severity": severity, "message": message, "source": source, "action": action}
    if employee is not None:
        out.update({"employeeId": employee.get("id"), "employeeCode": employee.get("code")})
    return out


def engine_block_check(employee: dict, exc: SingaporeCalculationBlockedError) -> dict:
    return check(f"ENGINE_BLOCK:{exc.key}", BLOCK, exc.reason, employee, source="engine/countries/singapore.py (fail-closed)",
                 action="Correct the employee fact or statutory configuration named in the message")


def next_month_bounds(month_start: date):
    y, m = (month_start.year + 1, 1) if month_start.month == 12 else (month_start.year, month_start.month + 1)
    nxt = date(y, m, 1)
    return nxt, _month_end(nxt)


def transition_checks(employee: dict, month_start: date, month_end: date, rate_map: dict) -> list:
    """SG-030: an age-band crossing or SPR-year change schedules the next CPF
    content segment — flagged here so the operator sees next month's change
    (the engine applies it automatically; nothing is overridden)."""
    out = []
    nxt_start, nxt_end = next_month_bounds(month_start)
    dob, residency = employee.get("dob"), employee.get("residency")
    if dob and residency in ("SC", "SPR"):
        try:
            now, later = (resolve_cpf_age_band(dob, month_start, month_end, rate_map),
                          resolve_cpf_age_band(dob, nxt_start, nxt_end, rate_map))
            if now != later:
                out.append(check("CPF_AGE_BAND_CHANGES_NEXT_MONTH", INFO,
                                 f"CPF age band changes from {now} to {later} from {nxt_start.isoformat()} "
                                 "(CPF Board: from the first day of the month after the birthday)", employee,
                                 source="cpf_age_band_semantics"))
        except SingaporeCalculationBlockedError:
            pass                                       # the engine block is reported by the dry run itself
    spr = employee.get("spr_date")
    if residency == "SPR" and spr:
        try:
            now, later = resolve_spr_year(spr, month_start, month_end), resolve_spr_year(spr, nxt_start, nxt_end)
            if now != later and (later or 0) <= 3:
                out.append(check("SPR_YEAR_CHANGES_NEXT_MONTH", INFO,
                                 f"SPR year changes from {now} to {later} from {nxt_start.isoformat()} — next month uses "
                                 "a different CPF table", employee, source="CPF Board: SPR year begins on the day of conversion"))
        except SingaporeCalculationBlockedError:
            pass
    return out


def identity_checks(employee: dict) -> list:
    """The CPF EZPay detail record needs the employee's CPF account number
    (S/T-prefixed NRIC, CPF EZPay spec p4) for every CPF/SHG contributor."""
    nric, residency = (employee.get("nric") or "").strip().upper(), employee.get("residency")
    if residency in ("SC", "SPR") and not nric:
        return [check("NRIC_MISSING", BLOCK, "NRIC is required — it is the CPF account number on the EZPay file",
                      employee, source="CPF EZPay (FTP) File Specifications p4", action="Record the employee's NRIC")]
    if residency in ("SC", "SPR") and nric[:1] not in ("S", "T"):
        return [check("CPF_ACCOUNT_PREFIX", BLOCK, "a citizen/SPR CPF account number begins with S or T",
                      employee, source="CPF EZPay (FTP) File Specifications p6 note 4", action="Correct the NRIC")]
    return []


def trace_checks(employee: dict, trace: dict, ir21_case: dict = None, today: date = None) -> list:
    """Exceptions from an engine trace (dry-run or persisted)."""
    out = []
    today = today or date.today()
    cpf = trace.get("cpf") or {}
    if cpf.get("formulaType") in ("ER_ONLY", "PHASE_IN"):
        out.append(check("CPF_LOW_WAGE_FORMULA", INFO, f"low-wage CPF formula {cpf.get('formulaType')} applies "
                         f"(rule {cpf.get('rule')})", employee, source=cpf.get("rule")))
    aw = cpf.get("additionalWages") or {}
    if aw.get("awPaid") not in (None, "0") and aw.get("awSubjectThisPayment") not in (None, aw.get("awPaid")):
        out.append(check("CPF_AW_CEILING_REACHED", INFO, f"AW ceiling {aw.get('awCeiling')} limits CPF on this payment's AW",
                         employee, source="CPF Board AW ceiling (Option A)"))
    if aw.get("excess"):
        out.append(check("CPF_REFUND_APPLICATION", WARN, "excess CPF on AW — a CPF refund application is required",
                         employee, source="CPF Board AW ceiling examples", action="Apply to CPF Board for the refund"))
    month = trace.get("incompleteMonth") or {}
    if month.get("status") == "INCOMPLETE_MONTH":
        out.append(check("EA_INCOMPLETE_MONTH", INFO, f"incomplete month ({', '.join(month.get('reasons') or [])}): "
                         f"S${month.get('monthlyGrossRate')} ÷ {month.get('workingDaysInMonth')} working days × "
                         f"{month.get('daysWorked')} days worked = S${month.get('salary')} ({month.get('workPattern')})",
                         employee, source=month.get("source")))
        if month.get("excludedMonthlyComponentsPaidInFull"):
            items = ", ".join(f"{k} S${v}" for k, v in month["excludedMonthlyComponentsPaidInFull"].items())
            out.append(check("EA_INCOMPLETE_MONTH_EXCLUDED_ALLOWANCES", WARN, f"paid in full in an incomplete month: {items} — "
                             "outside MOM's gross rate of pay (housing / travel / food allowances), so MOM's formula does "
                             "not pro-rate them; confirm the contract", employee, source=month.get("source"),
                             action="Confirm the allowance is payable in full, or record the contractual amount"))
    ot = trace.get("overtime") or {}
    if ot.get("status") == "UNPAID_STATUTORY_MINIMUM":
        out.append(check("EA_OVERTIME_UNPAID", BLOCK, f"{ot.get('hours')} overtime hours for a Part 4 employee — statutory "
                         f"minimum S${ot.get('statutoryMinimum')} is not in this payslip ({ot.get('reason')})", employee,
                         source="MOM Hours of work, overtime and rest day",
                         action="Enable / approve overtime in the payroll policy, or correct the attendance hours"))
    elif ot.get("status") == "PAID":
        out.append(check("EA_OVERTIME_PAID", INFO, f"{ot.get('hours')} overtime hours paid at the Part 4 minimum "
                         f"S${ot.get('statutoryMinimum')}", employee, source="MOM Hours of work, overtime and rest day"))
    elif ot.get("status") == "NOT_PART4":
        out.append(check("EA_OVERTIME_CONTRACTUAL", INFO, f"{ot.get('hours')} overtime hours — not covered by Part 4: "
                         "overtime pay follows the contract (not computed)", employee))
    if ot.get("overLimit"):
        out.append(check("EA_OVERTIME_LIMIT", BLOCK, f"{ot.get('hours')} overtime hours exceed the {ot.get('maxHours')} "
                         "hours / month limit — an MOM overtime exemption is required", employee,
                         source="MOM Hours of work, overtime and rest day"))
    lqs = trace.get("lqs") or {}
    if lqs.get("status") == "BELOW_LQS":
        out.append(check("LQS_SHORTFALL", WARN, f"wages {lqs.get('wagesTested')} below the LQS {lqs.get('threshold')} — the "
                         "employee does not count toward the foreign-worker quota", employee, source=(lqs.get("ref") or {}).get("rule")))
    elif lqs.get("status") == "BLOCKED":
        out.append(check("LQS_NOT_EVALUATED", WARN, lqs.get("detail") or "LQS not evaluated", employee))
    fwl = trace.get("fwl") or {}
    if fwl.get("status") == "BLOCKED":
        out.append(check("FWL_BLOCKED", BLOCK, fwl.get("detail") or "foreign worker levy cannot be computed", employee,
                         source="MOM foreign worker levy", action="Resolve the levy facts / configuration"))
    ir21 = trace.get("ir21") or {}
    if ir21.get("status") in ("TRIGGERED", "TRIGGERED_PAST_CESSATION"):
        if ir21_case is None:
            out.append(check("IR21_CASE_MISSING", BLOCK, f"cessation {ir21.get('cessationDate')} of a non-citizen: Form IR21 "
                             f"must be filed by {ir21.get('fileBy')} and monies withheld — no IR21 case exists", employee,
                             source="IRAS IR21", action="Open the IR21 case (or record it EXEMPT with the category)"))
        elif ir21_case.get("status") == "DRAFT" and ir21.get("fileBy") and date.fromisoformat(ir21["fileBy"]) < today:
            out.append(check("IR21_OVERDUE", WARN, f"Form IR21 was due by {ir21['fileBy']} and is not filed", employee,
                             source="IRAS IR21", action="File the Form IR21"))
    if ir21_case is not None and ir21_case.get("status") in _IR21_HOLD_STATUSES:
        out.append(check("IR21_HOLD", WARN, f"IR21 case {ir21_case.get('id')} ({ir21_case.get('status')}): net pay is "
                         "HELD_FOR_IR21 — excluded from the bank file until released", employee, source="IRAS IR21"))
    if (trace.get("iras") or {}).get("unclassified") not in (None, "0", "0.00"):
        out.append(check("IRAS_UNCLASSIFIED_EARNING", WARN, "an earning has no IRAS item (IR8A readiness)", employee,
                         source="IRAS IR8A explanatory notes", action="Classify the earning (TaxabilityRule iras_*)"))
    return out


def summarize(checks: list) -> dict:
    counts = {s: sum(1 for c in checks if c["severity"] == s) for s in (BLOCK, WARN, INFO)}
    status = "BLOCKED" if counts[BLOCK] else ("REVIEW" if counts[WARN] else "CLEAR")
    return {"status": status, "counts": counts, "checks": checks}
