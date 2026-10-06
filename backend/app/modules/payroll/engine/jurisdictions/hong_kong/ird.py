"""IRD employer reporting rules (ZP-HK-ENG-001 §7, HK-011; IRD S1 — employer
obligations; PAM 46(e) — departure).

Pure rules only; the case records live in payroll_hk_ird_reporting_cases.

  BIR56A + IR56B  annual, for the year of assessment ending 31 March; the
                  return is normally issued on the first working day of April
                  and is due within one month of issue.
  IR56E           within 3 months of the commencement of employment, where
                  the employee is likely to be chargeable to Salaries Tax.
  IR56F           not later than 1 month before cessation (not used when the
                  employee is leaving Hong Kong — IR56G then applies).
  IR56G           not later than 1 month before the expected departure of an
                  employee leaving HK for > 1 month (none for an employee
                  required to leave HK at frequent intervals).

Filing payloads are an INTERNAL canonical form. The IRD XML schemas are not
archived in this build (G2), so no e-filing file is produced; FILED records
the reference of a filing the operator made through IRD's own channel.
"""

from datetime import date

from app.modules.payroll.engine.jurisdictions.hong_kong.common import (
    add_months, timing_day, timing_months, year_of_assessment, year_of_assessment_bounds,
)

FORM_TYPES = ("BIR56A", "IR56B", "IR56E", "IR56F", "IR56G")
STATUSES = ("DUE", "PREPARED", "VALIDATED", "FILED", "ACCEPTED", "ACKNOWLEDGED", "AMENDED", "SUPPRESSED", "CANCELLED")
FILED_STATES = ("FILED", "ACCEPTED", "ACKNOWLEDGED")
TRANSITIONS = {
    "DUE": ("PREPARED", "SUPPRESSED", "CANCELLED"),
    "PREPARED": ("VALIDATED", "PREPARED", "SUPPRESSED", "CANCELLED"),
    "VALIDATED": ("FILED", "PREPARED", "CANCELLED"),
    "FILED": ("ACCEPTED", "ACKNOWLEDGED", "AMENDED", "REJECTED"),
    # An IRD rejection of a filed return: recorded with its reference, then the
    # case is prepared again and re-filed (the original filing evidence is kept).
    "REJECTED": ("PREPARED",),
    "ACCEPTED": ("AMENDED",),
    "ACKNOWLEDGED": ("AMENDED",),
    "AMENDED": (),
    "SUPPRESSED": (),
    "CANCELLED": (),
}
INTERNAL_SCHEMA_VERSION = "ZOIKO-HK-IR56-INTERNAL-1"
SCHEMA_STATUS = "IRD_SCHEMA_NOT_ARCHIVED — internal payload only; e-filing export gated (G2)"


def due_date(form_type: str, timing: dict, event_date: date = None, ya: str = None,
             return_issue_date: date = None) -> date:
    """The statutory due date of a return, from the pack's reporting-timing
    rows (never a literal in this module — a deadline without pack provenance
    could not be evidenced or replayed)."""
    if form_type == "IR56E":
        return add_months(event_date, timing_months(timing, "ird_ir56e_months"))
    if form_type == "IR56F":
        return add_months(event_date, -timing_months(timing, "ird_ir56f_months_before"))
    if form_type == "IR56G":
        return add_months(event_date, -timing_months(timing, "ird_ir56g_months_before"))
    if form_type in ("BIR56A", "IR56B"):
        issue = return_issue_date or date(
            int(ya[:4]) + 1, timing_day(timing, "ird_return_issue_month"), timing_day(timing, "ird_return_issue_day"))
        return add_months(issue, timing_months(timing, "ird_ir56b_due_months"))
    raise ValueError(form_type)


def annual_year_for_payment(pay_date: date) -> str:
    """The year of assessment a payment is reported in (1 Apr – 31 Mar)."""
    return year_of_assessment(pay_date)


def ir56b_suppression(ya: str, employee_period: tuple, prior_cases: list) -> dict:
    """Should an IR56B for this employee and year be suppressed because a
    FILED IR56F / IR56G already reports the same income?

    employee_period: (start, end) of the employee's employment within the
    year. prior_cases: [{id, formType, status, incomePeriodStart, incomePeriodEnd}].
    Returns {action: FILE | SUPPRESS | RESOLVE, message}."""
    covering = [c for c in prior_cases if c["formType"] in ("IR56F", "IR56G") and c["status"] in FILED_STATES]
    if not covering:
        return {"action": "FILE", "message": None}
    start, end = employee_period
    for c in covering:
        cs, ce = date.fromisoformat(str(c["incomePeriodStart"])), date.fromisoformat(str(c["incomePeriodEnd"]))
        if cs <= start and ce >= end:
            return {"action": "SUPPRESS", "coveringCaseId": c["id"],
                    "message": (f"IR56B for {ya} suppressed: {c['formType']} case #{c['id']} (filed) already reports this "
                                f"employee's income for {cs} – {ce}, which covers the whole of the employee's {ya} "
                                "employment — filing IR56B as well would report the same income twice")}
    c = covering[0]
    return {"action": "RESOLVE", "coveringCaseId": c["id"],
            "message": (f"{c['formType']} case #{c['id']} covers only part of this employee's {ya} income — an IR56B "
                        "cannot be generated automatically; review whether income after the cessation/departure "
                        "notice needs an additional/supplementary form")}


def reconcile(reported_total, payroll_total) -> dict:
    """HK-011: reported remuneration must reconcile EXACTLY to committed payroll."""
    diff = (payroll_total or 0) - (reported_total or 0)
    return {"reported": str(reported_total), "payroll": str(payroll_total), "difference": str(diff),
            "reconciled": diff == 0}


def employee_period_in_year(ya: str, start: date, end: date = None) -> tuple:
    ys, ye = year_of_assessment_bounds(ya)
    return max(start, ys), min(end or ye, ye)


def tax_clearance_required(timing: dict, expected_departure: date, return_date: date = None,
                           frequent_travel: bool = False, likely_chargeable: bool = True) -> dict:
    """IR56G applies to an employee chargeable to Salaries Tax leaving Hong
    Kong for a period exceeding one month (PAM 46(e))."""
    if frequent_travel:
        return {"required": False, "reason": "required in the course of employment to leave HK at frequent intervals"}
    if not likely_chargeable:
        return {"required": False, "reason": "employee not chargeable to Salaries Tax — no notification required"}
    absent_months = timing_months(timing, "ird_ir56g_absence_months")
    if return_date is not None and return_date <= add_months(expected_departure, absent_months):
        return {"required": False, "reason": f"absence does not exceed {absent_months} month"}
    return {"required": True, "fileBy": add_months(
                expected_departure, -timing_months(timing, "ird_ir56g_months_before")).isoformat(),
            "reason": "leaving Hong Kong for more than one month while chargeable to Salaries Tax"}
