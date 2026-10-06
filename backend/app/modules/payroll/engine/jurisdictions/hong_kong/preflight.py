"""
engine/jurisdictions/hong_kong/preflight.py
--------------------------------------------
Hong Kong payroll-run preflight and exceptions — ZP-HK-ENG-001 §14 / HK-014
(the run must not be approved while a statutory fact is missing or an
Employment Ordinance obligation is unmet) and §7/§8 (IRD reporting readiness).

Pure: every statutory decision comes from the calculation engine or from the
pure rule modules — this file evaluates NO rate and NO threshold of its own.
It reads the persisted / dry-run `hk_calculation_trace` and the pack's
`rate_map` (already resolved by the service) and turns them into operator
checks, exactly like the Singapore preflight does.

  BLOCK  approval refused   WARN  review, approval allowed   INFO  disclosed

The pack rows are mandatory inputs: a missing row raises
HongKongCalculationBlockedError here rather than falling back to a literal, so
a preflight can never reassure an operator on the strength of a default the
pack does not actually contain.
"""

from datetime import date, timedelta

from app.modules.payroll.engine.jurisdictions.hong_kong import (
    continuous_contract as _cc, ird as _ird, mpf as _mpf, tax_clearance as _tc,
)
from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    HongKongCalculationBlockedError, dec, rate_value, resolve_timing, row_ref,
)

BLOCK, WARN, INFO = "BLOCK", "WARN", "INFO"
# Taken from the rule modules, never restated here: a preflight must not be able
# to disagree with the state machine it is reporting on.
_HOLDING_STATES = _tc.HOLDING_STATES
_FINAL_PAY_BLOCKING_STATES = _tc.FINAL_PAY_BLOCKING_STATES
_OPEN_IRD_STATUSES = tuple(s for s in _ird.STATUSES if s not in _ird.FILED_STATES + ("SUPPRESSED", "CANCELLED"))


def check(code, severity, message, employee=None, source=None, action=None):
    out = {"code": code, "severity": severity, "message": message, "source": source, "action": action}
    if employee is not None:
        out.update({"employeeId": employee.get("id"), "employeeCode": employee.get("code")})
    return out


def engine_block_check(employee: dict, exc: HongKongCalculationBlockedError) -> dict:
    return check(f"ENGINE_BLOCK:{exc.key}", BLOCK, exc.reason, employee,
                 source="engine/countries/hong_kong.py (fail-closed)",
                 action="Correct the employee fact or statutory configuration named in the message")


def pack_checks(rate_map: dict) -> list:
    """Run-level, evaluated once: every statutory parameter set the calculator
    itself needs must BUILD from the pack this run would bind to. The rule
    modules' own `parameters()` / `resolve_timing()` are the authority, so this
    list can never drift from what the engine actually requires — and a
    half-configured pack is reported once, not once per employee.
    """
    out = []
    builders = (("MPF", _mpf.mpf_parameters), ("continuous contract", _cc.parameters))
    for label, builder in builders:
        try:
            builder(rate_map)
        except HongKongCalculationBlockedError as exc:
            out.append(check(f"HK_PACK_INCOMPLETE:{label}", BLOCK,
                             f"the rule pack in force cannot produce the {label} parameters: {exc.reason}",
                             source="tax_resolver (HK canonical pack)",
                             action="Seed / activate a Hong Kong rule pack that contains the rows the engine needs"))
    try:
        resolve_timing(rate_map)
    except HongKongCalculationBlockedError as exc:
        out.append(check("HK_IRD_TIMING_INCOMPLETE", BLOCK,
                         f"the rule pack has no complete IRD reporting-timing rows: {exc.reason}",
                         source="IRD employer obligations / PAM 46(e)",
                         action="Seed / activate a Hong Kong rule pack that contains the reporting-timing rows"))
    try:
        rate_value(rate_map, "eo_wage_payment_days")
    except HongKongCalculationBlockedError as exc:
        out.append(check("HK_PACK_INCOMPLETE:wage payment timing", BLOCK,
                         f"the Employment Ordinance wage-payment deadline cannot be read from the pack: {exc.reason}",
                         source="Employment Ordinance s.25",
                         action="Seed / activate a Hong Kong rule pack that contains eo_wage_payment_days"))
    return out


def wage_payment_timing(pay_date: date, period_end: date, rate_map: dict,
                        termination: date = None) -> dict:
    """Employment Ordinance s.25: wages are due NOT LATER THAN SEVEN DAYS after
    the end of the wage period, and on termination the residual wages fall due
    IMMEDIATELY. The 7 comes from the pack row eo_wage_payment_days.

    Returns {latestPaymentDate, daysAllowed, daysUsed, onTime, terminationTriggered, source}.
    """
    days, row = rate_value(rate_map, "eo_wage_payment_days")
    allowed = int(days)
    latest = period_end + timedelta(days=allowed)
    return {"latestPaymentDate": latest.isoformat(), "daysAllowed": allowed,
            "periodEnd": period_end.isoformat(), "payDate": pay_date.isoformat(),
            "daysUsed": (pay_date - period_end).days, "onTime": pay_date <= latest,
            "terminationTriggered": termination is not None,
            "terminationImmediateDue": termination is not None,
            "source": row_ref(row)}


def identity_checks(employee: dict) -> list:
    """An HK employee must carry an identity document: it is the IRD's employee
    identifier on IR56B / IR56E and the MPF scheme-member reference. Only the
    PRESENCE is checked here — the value itself is masked on every report
    (HK-022 / PCPD HR Code) and never enters a payroll trace."""
    fields = employee.get("identity") or {}
    if not fields.get("hkid") and not fields.get("passport_number"):
        return [check("HK_IDENTITY_MISSING", BLOCK,
                      "no HKID or passport number is recorded — the IRD employee identifier is required for "
                      "IR56B / IR56E reporting", employee, source="IRD employer obligations",
                      action="Record the employee's HKID or passport number")]
    return []


def mpf_checks(employee: dict, mpf: dict) -> list:
    """Coverage / contribution exceptions from the mpf segment of a trace."""
    out = []
    coverage = mpf.get("coverage") or {}
    status = coverage.get("status")
    if status == "EXEMPT" and not (coverage.get("evidenceRef") or coverage.get("exemptionCode") == "EXEMPT_AGE"):
        out.append(check("MPF_EXEMPT_WITHOUT_EVIDENCE", BLOCK,
                         f"MPF status EXEMPT ({coverage.get('exemptionCode') or 'no code recorded'}) with no recorded "
                         "evidence — an exemption cannot be inferred", employee, source="MPFA MPF Coverage",
                         action="Record the exemption evidence reference, or correct the exemption code"))
    elif status == "PENDING_60_DAY":
        out.append(check("MPF_60_DAY_NOT_MET", INFO,
                         f"MPF contributions accrue from the first day but fall due once {coverage.get('sixtyDayDate')} "
                         f"is reached (first contribution by {coverage.get('firstContributionDay')})", employee,
                         source="MPFA Mandatory Contributions — Employees"))
    elif status == "NOT_COVERED_LEFT_BEFORE_60_DAYS":
        out.append(check("MPF_NOT_A_REGULAR_EMPLOYEE", INFO,
                         coverage.get("reason") or "not a regular employee — no MPF liability is manufactured",
                         employee, source="MPFA MPF Coverage"))
    elif status == "COVERED" and mpf.get("accruedPending"):
        out.append(check("MPF_ACCRUED_PENDING", INFO,
                         f"{mpf['accruedPending'].get('employer')} / {mpf['accruedPending'].get('employee')} has accrued "
                         "from a prior period under the 60-day condition and is booked now", employee,
                         source="MPFA Mandatory Contributions — Employees"))
    if mpf.get("catchUp"):
        total = str(sum((dec(x.get("employee")) for x in mpf["catchUp"]), dec(0)))
        out.append(check("MPF_CATCH_UP", INFO,
                         f"{len(mpf['catchUp'])} prior period(s) under the 60-day condition are caught up on this "
                         f"payslip ({total} employee share)", employee, source="MPFA — 60-day rule"))
    current = mpf.get("currentPeriod") or {}
    if current:
        if current.get("employeeBasis") == "CONTRIBUTION_HOLIDAY":
            out.append(check("MPF_CONTRIBUTION_HOLIDAY", INFO,
                             "the employee is inside the statutory contribution holiday: the employer contributes, "
                             "the employee does not", employee, source="MPFA — contribution holiday"))
        elif current.get("branch") == "BELOW_MINIMUM":
            out.append(check("MPF_BELOW_MINIMUM", INFO,
                             f"relevant income {current.get('relevantIncome')} is below the minimum level "
                             f"{current.get('minLevel')}: the employee contributes nothing, the employer still "
                             "contributes 5%", employee, source="MPFA Mandatory Contributions — Employees"))
        elif current.get("branch") == "ABOVE_MAXIMUM":
            out.append(check("MPF_ABOVE_MAXIMUM", INFO,
                             f"relevant income is above the maximum level {current.get('maxLevel')}: both shares are "
                             "capped at 5% of the maximum", employee, source="MPFA Mandatory Contributions — Employees"))
    return out


def minimum_wage_checks(employee: dict, smw: dict) -> list:
    """Statutory Minimum Wage exceptions (the assessment is engine-side; this
    only surfaces it — payroll never silently tops up pay)."""
    out = []
    status = smw.get("status")
    record = smw.get("hoursRecord") or {}
    if record.get("required"):
        out.append(check("SMW_HOURS_RECORD", WARN,
                         f"wages payable for the period are below the hours-record monetary cap "
                         f"({record.get('monthlyCap')}): the employer must keep a record of the hours worked"
                         + (f" — the cap changed inside this period ({record.get('capChangedInPeriod')})"
                            if record.get("capChangedInPeriod") else ""),
                         employee, source="Labour Department Statutory Minimum Wage (hours record)",
                         action="Keep the hours record for the statutory retention period"))
    if status == "BREACH":
        out.append(check("SMW_BREACH", BLOCK,
                         f"wages payable ({smw.get('countableWages')}) are below the statutory minimum for the "
                         f"{smw.get('hours')} hours worked ({smw.get('minimumDue')}); a shortfall of "
                         f"{smw.get('topUpRequired')} is payable", employee,
                         source="Labour Department Statutory Minimum Wage",
                         action="Pay the shortfall, or correct the hours / wage classification"))
    elif status == "NEEDS_CLASSIFICATION_REVIEW":
        out.append(check("SMW_CLASSIFICATION_REVIEW", WARN,
                         f"the minimum-wage position depends on {smw.get('wagesNeedingClassification')} whose treatment "
                         "is not yet certified", employee, source="Labour Department Statutory Minimum Wage",
                         action="Certify the minimum-wage treatment of the flagged earnings"))
    elif status in ("HOURS_NOT_RECORDED", "HOURS_INCOMPLETE"):
        out.append(check("SMW_HOURS_NOT_ASSESSED", WARN,
                         smw.get("detail") or "the minimum-wage test could not be evaluated from the recorded hours",
                         employee, source="Labour Department Statutory Minimum Wage",
                         action="Record verified hours for every day of the wage period"))
    elif status == "COMPLIANT":
        out.append(check("SMW_COMPLIANT", INFO,
                         f"{smw.get('hours')} hours worked; statutory minimum {smw.get('minimumDue')} is met by wages "
                         f"of {smw.get('countableWages')}", employee,
                         source="Labour Department Statutory Minimum Wage"))
    return out


def continuous_contract_checks(employee: dict, cc: dict) -> list:
    """The continuous-contract status the service resolved for this employee.
    SP/LSP, annual and sickness leave pay and holiday pay all hang off it, so an
    undetermined status blocks rather than assuming continuity."""
    if not cc:
        return [check("EO_CC_NOT_ASSESSED", WARN,
                      "continuous-contract status was not assessed for this run — severance / long service and leave "
                      "entitlements cannot be confirmed", employee,
                      source="Labour Department Concise Guide ch.1",
                      action="Record the contractual weekly hours and the daily work-hours history")]
    status = cc.get("status")
    if status == "UNDETERMINED":
        return [check("EO_CC_UNDETERMINED", BLOCK,
                      "continuous-contract status cannot be determined — a week of employment has neither recorded "
                      "hours nor a contractual hours figure (continuity is never assumed)", employee,
                      source="Labour Department Concise Guide ch.1 (4-18 / 4-week 17-68)",
                      action="Record the contractual weekly hours and the work-hours for the four-week window")]
    if status == "NOT_CONTINUOUS":
        return [check("EO_NOT_A_CONTINUOUS_CONTRACT", INFO,
                      f"not a continuous contract as at {cc.get('asOf')} — no statutory severance / long service "
                      "entitlement arises", employee, source="Labour Department Concise Guide ch.1")]
    return [check("EO_CONTINUOUS_CONTRACT", INFO,
                  f"continuous contract since {cc.get('continuousSince')} "
                  f"({cc.get('weeksOfContinuity')} qualifying week(s)) as at {cc.get('asOf')}", employee,
                  source="Labour Department Concise Guide ch.1 (4-18 / 4-week 17-68)")]


def wage_payment_checks(employee: dict, pay_date: date, period_end: date, rate_map: dict,
                        termination: date = None) -> list:
    """Employment Ordinance s.25 — wages are due not later than the pack's
    eo_wage_payment_days after the wage period ends, and on termination the
    residual wages fall due immediately."""
    try:
        timing = wage_payment_timing(pay_date, period_end, rate_map, termination)
    except HongKongCalculationBlockedError as exc:
        return [engine_block_check(employee, exc)]
    src = "Employment Ordinance s.25 (Labour Department Concise Guide ch.3)"
    if timing["terminationTriggered"]:
        return [check("EO_TERMINATION_WAGES_DUE_IMMEDIATELY", BLOCK,
                      f"the employee is leaving — residual wages are due IMMEDIATELY on {timing['payDate']}, not on the "
                      f"ordinary {timing['daysAllowed']}-day cycle", employee, source=src,
                      action="Pay the residual wages now, or record why the payment is deferred")]
    if not timing["onTime"]:
        return [check("EO_WAGE_PAYMENT_LATE", BLOCK,
                      f"wages for the period ending {timing['periodEnd']} are due by {timing['latestPaymentDate']} "
                      f"but this run pays on {timing['payDate']} ({timing['daysUsed']} days after the period end, "
                      f"{timing['daysAllowed']} allowed)", employee, source=src,
                      action="Correct the pay date, or record the reason for the late payment")]
    return [check("EO_WAGE_PAYMENT_TIMING", INFO,
                  f"wages due by {timing['latestPaymentDate']} ({timing['daysAllowed']} days after the period end); "
                  f"this run pays on {timing['payDate']}", employee, source=src)]


def ird_checks(employee: dict, hold: dict = None, ird_cases: list = None, today: date = None) -> list:
    """IRD reporting readiness: the payment control (a legal hold, not a
    deduction) and any overdue employer return."""
    today = today or date.today()
    out = []
    if hold is not None and hold.get("state") in _HOLDING_STATES:
        out.append(check("IR56G_HOLD_ACTIVE", WARN,
                         f"an IR56G tax-clearance hold is ACTIVE (case #{hold.get('id')}, {hold.get('state')}): net pay is "
                         "HELD_FOR_IR56G — excluded from the bank file until an approved release", employee,
                         source="IRD PAM 46(e)",
                         action="File IR56G / obtain the letter of release, then approve the release (four-eyes)"))
    elif hold is not None and hold.get("state") in _FINAL_PAY_BLOCKING_STATES:
        out.append(check("IR56G_NOT_YET_FILED", BLOCK,
                         f"a departure is identified (hold state {hold.get('state')}, IR56G due by "
                         f"{hold.get('filing_deadline')}) but the return is not filed — the final payment is held until "
                         "it is", employee, source="IRD PAM 46(e)",
                         action="File the IR56G notification and record the filing reference"))
    for case in ird_cases or []:
        if case.get("status") in _OPEN_IRD_STATUSES and case.get("dueDate") and \
                date.fromisoformat(str(case["dueDate"])) < today:
            out.append(check(f"IRD_OVERDUE:{case.get('form_type') or case.get('formType')}", WARN,
                             f"{case.get('form_type') or case.get('formType')} (case #{case.get('id')}) was due by "
                             f"{case.get('dueDate')} and is still {case.get('status')}", employee,
                             source="IRD employer obligations",
                             action="File the return through the IRD channel and record the reference"))
    return out


def enrolment_checks(employee: dict, coverage: dict, enrolled: bool, today: date) -> list:
    """MPF enrolment (ZP-HK-ENG-001 §5: a regular employee is enrolled within
    the first 60 days of employment; exception queue "late enrolment risk").
    The deadline is the coverage's own 60th-day date — computed by
    mpf.resolve_coverage from the pack row mpf_regular_employee_days, never a
    literal here. Enrolment is evidenced by a recorded MPF scheme / member
    account reference (Zoiko has no certified eMPF enrolment interface — G2).
    Late enrolment WARNs rather than BLOCKs: wages are never withheld over
    scheme administration."""
    status = (coverage or {}).get("status")
    if status in (None, "EXEMPT", "NOT_COVERED_LEFT_BEFORE_60_DAYS"):
        return []
    deadline = coverage.get("sixtyDayDate")
    if enrolled:
        return [check("MPF_ENROLLED", INFO, "MPF scheme membership is recorded", employee,
                      source="MPFA — Enrolment")]
    if not deadline:
        return []
    if today > date.fromisoformat(str(deadline)[:10]):
        return [check("MPF_ENROLMENT_OVERDUE", WARN,
                      f"no MPF scheme membership is recorded and the enrolment deadline ({deadline}) has passed — "
                      "late enrolment risk", employee, source="MPFA — Enrolment (within the first 60 days)",
                      action="Enrol the employee through eMPF and record the MPF member account")]
    return [check("MPF_ENROLMENT_DUE", WARN, f"enrol the employee in an MPF scheme by {deadline}", employee,
                  source="MPFA — Enrolment (within the first 60 days)",
                  action="Enrol through eMPF and record the MPF member account")]


def trace_checks(employee: dict, trace: dict, *, cc: dict = None, hold: dict = None,
                 ird_cases: list = None, rate_map: dict = None, pay_date: date = None,
                 period_end: date = None, termination: date = None, today: date = None,
                 enrolled: bool = None) -> list:
    """Every HK exception for one employee, from a persisted or dry-run trace
    plus the service-resolved continuous-contract status and IRD state."""
    out = []
    out.extend(mpf_checks(employee, trace.get("mpf") or {}))
    if enrolled is not None:
        out.extend(enrolment_checks(employee, (trace.get("mpf") or {}).get("coverage") or {}, enrolled,
                                    today or date.today()))
    out.extend(minimum_wage_checks(employee, trace.get("minimumWage") or {}))
    out.extend(continuous_contract_checks(employee, cc))
    if rate_map is not None and pay_date is not None and period_end is not None:
        out.extend(wage_payment_checks(employee, pay_date, period_end, rate_map, termination))
    out.extend(ird_checks(employee, hold, ird_cases, today))
    return out


def summarize(checks: list) -> dict:
    counts = {s: sum(1 for c in checks if c["severity"] == s) for s in (BLOCK, WARN, INFO)}
    status = "BLOCKED" if counts[BLOCK] else ("REVIEW" if counts[WARN] else "CLEAR")
    return {"status": status, "counts": counts, "checks": checks}