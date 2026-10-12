"""
tests/test_singapore_pwm_retail_averaging.py
--------------------------------------------
Singapore final closure (2026-09-29): MOM Retail PWM 3-month averaging.

Source: MOM Tripartite Cluster for Retail Industry report (Aug 2025), Annex D
"Averaging of Gross Wages":
  §1 only Retail PWM workers;
  §2 compliant in a month if (a) that month's gross wage (incl. overtime) >=
     that month's PWM wage requirement (incl. overtime), OR (b) the average of
     the past 3 months' gross wages >= the average of the same months'
     requirements;
  §3 averaging applies across a Retail role change, not across a change to a
     non-Retail job;
  §4 new employees: averaging starts in the 3rd month; footnote 2: an
     incomplete first month counts with a pro-rated requirement.

The requirement is the MOM Gross Wage Requirement for the month's overtime
hours (sgp_pwm_overtime_schedules; 0 hours = the retail PWM wage, S$2,305 for
a Retail assistant / Cashier from Sep 2025). Before this pass a retail
shortfall was only flagged and the average never computed, because only the
CURRENT job role was held; each payslip now records its own month's role.

app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date
from decimal import Decimal as D

import pytest

from tests.test_singapore_phase57_reports import _active_pack, _employee, _finalized_run, _payslip, _template

CASHIER, SENIOR = "ASSISTANT_CASHIER", "SENIOR_CASHIER_ASSISTANT"
REQ = {CASHIER: D("2305"), SENIOR: D("2535")}           # MOM schedule, 0 OT hours, in force Sep 2025 – Aug 2026


def _retail(db, organization, code="RET", joined=date(2026, 1, 1), level=CASHIER):
    return _employee(db, organization.id, code, date_of_joining=joined, compliance_fields={
        "nric_fin": "S1234567D", "pwm_sector": "RETAIL", "pwm_group": "ALL", "pwm_job_level": level,
        "ea_workman": "YES", "ea_manager_executive": "NO"})


def _trace(month, gross, level=CASHIER, sector="RETAIL", overtime="0", hours=None, employment="Full-time",
           classified=True, incomplete=None, group="ALL"):
    trace = {"wageMonth": f"2026-{month:02d}",
             "inputs": {"wageClassification": {"basic": {"amount": str(gross), "class": "OW"},
                                               "overtime": {"amount": str(overtime), "class": "OW"}}}}
    if hours is not None:
        trace["overtime"] = {"hours": str(hours)}
    if classified:
        trace["pwmClassification"] = {"sector": sector, "group": group, "level": level, "employmentType": employment}
    if incomplete:
        trace["incompleteMonth"] = incomplete
    return trace


def _pay(db, organization, emp, month, **kw):
    end = {5: 31, 6: 30, 7: 31}[month]
    run = _finalized_run(db, organization.id, date(2026, month, end), f"2026-{month:02d} {emp.employee_code}")
    return _payslip(db, run, emp, _trace(month, **kw))


def _july_row(db, organization, code="RET"):
    from app.modules.payroll import service

    template = _template(db, f"SG-PWM-AVG-{code}", "SG_PWM_COMPLIANCE")
    data = service.generate_sg_pwm_compliance(db, organization.id, template.id, 2026, 7).rendered_data
    return next(r for r in data["employeeRows"] if r["employeeCode"] == code), data


def test_a_july_shortfall_is_met_by_the_three_month_average(db, organization):
    _active_pack(db, organization)
    emp = _retail(db, organization)
    _pay(db, organization, emp, 5, gross="2400")
    _pay(db, organization, emp, 6, gross="2400")
    _pay(db, organization, emp, 7, gross="2200")                    # (a) fails: 2,200 < 2,305
    row, data = _july_row(db, organization)
    avg = row["averaging"]
    assert (row["result"], avg["status"], row["averagingWarning"]) == ("MET_BY_AVERAGING", "MET", False)
    assert [D(m["requirement"]) for m in avg["months"]] == [REQ[CASHIER]] * 3
    assert (D(avg["averageGrossPaid"]), D(avg["averageRequirement"])) == (D("2333.33"), D("2305.00"))   # 7,000 / 3 vs 6,915 / 3
    assert [m["wageMonth"] for m in avg["months"]] == ["2026-05", "2026-06", "2026-07"]
    assert "Annex D" in avg["source"] and data["counts"]["MET_BY_AVERAGING"] == 1


def test_an_average_below_the_requirement_stays_a_shortfall(db, organization):
    _active_pack(db, organization)
    emp = _retail(db, organization)
    for month, gross in ((5, "2305"), (6, "2305"), (7, "2200")):   # 6,810 < 6,915
        _pay(db, organization, emp, month, gross=gross)
    row, _ = _july_row(db, organization)
    assert (row["result"], row["averaging"]["status"], row["averagingWarning"]) == ("SHORTFALL", "SHORTFALL", False)


def test_averaging_follows_each_months_own_retail_role_and_overtime(db, organization):
    """§3: a retail role change is averaged across — each month uses ITS role;
    overtime hours select the Gross Wage Requirement for that month."""
    from app.modules.payroll.models import SgpPwmOvertimeSchedule

    _active_pack(db, organization)
    emp = _retail(db, organization, level=SENIOR)                   # promoted: the CURRENT record says Senior
    two_hours = db.query(SgpPwmOvertimeSchedule).filter(
        SgpPwmOvertimeSchedule.sector == "RETAIL", SgpPwmOvertimeSchedule.job_level == SENIOR,
        SgpPwmOvertimeSchedule.overtime_hours == 2, SgpPwmOvertimeSchedule.effective_from <= date(2026, 7, 31),
        SgpPwmOvertimeSchedule.effective_to >= date(2026, 7, 31)).one().required_gross
    _pay(db, organization, emp, 5, gross="2400", level=CASHIER)      # still a cashier in May
    _pay(db, organization, emp, 6, gross="2700", level=SENIOR)
    _pay(db, organization, emp, 7, gross="2400", level=SENIOR, overtime="100", hours="2.5")
    row, _ = _july_row(db, organization)
    months = row["averaging"]["months"]
    assert [m["jobLevel"] for m in months] == [CASHIER, SENIOR, SENIOR]
    assert [D(m["requirement"]) for m in months] == [REQ[CASHIER], REQ[SENIOR], two_hours]   # 2.5 h rounds down to 2
    total_paid, total_req = D("2400") + D("2700") + D("2500"), REQ[CASHIER] + REQ[SENIOR] + two_hours
    assert row["averaging"]["status"] == ("MET" if total_paid >= total_req else "SHORTFALL")


def test_the_first_two_months_of_employment_are_never_averaged(db, organization):
    _active_pack(db, organization)
    emp = _retail(db, organization, joined=date(2026, 6, 1))        # July = month 2
    _pay(db, organization, emp, 6, gross="3000")
    _pay(db, organization, emp, 7, gross="2200")
    row, _ = _july_row(db, organization)
    assert (row["result"], row["averaging"]["status"]) == ("SHORTFALL", "NOT_YET_APPLICABLE")
    assert "3rd month" in row["averaging"]["reasons"][0] and row["averagingWarning"] is False


def test_an_incomplete_first_month_counts_with_a_pro_rated_requirement(db, organization):
    _active_pack(db, organization)
    emp = _retail(db, organization, joined=date(2026, 5, 15))        # July = month 3
    first = {"status": "INCOMPLETE_MONTH", "daysWorked": "12", "workingDaysInMonth": "21", "noPayDays": "0",
             "monthlyRatesForPwm": {"basic": "2400", "grossExOvertime": "2400"}}
    _pay(db, organization, emp, 5, gross="2400", incomplete=first)
    _pay(db, organization, emp, 6, gross="2400")
    _pay(db, organization, emp, 7, gross="2250")
    row, _ = _july_row(db, organization)
    may = row["averaging"]["months"][0]
    assert may["proRatedFirstMonth"] is True
    assert (D(may["requirement"]), D(may["grossPaid"])) == (D("1317.14"), D("1371.43"))   # 2,305 / 2,400 × 12 ÷ 21
    assert row["averaging"]["status"] == "MET"                      # 6,021.43 ≥ 5,927.14


@pytest.mark.parametrize("case, expected, reason", [
    ("legacy", "NOT_EVALUATED", "before the per-month PWM classification"),
    ("non_retail", "NOT_APPLICABLE", "not a Retail PWM job"),
    ("part_time", "NOT_EVALUATED", "part-time"),
    ("missing", "NOT_EVALUATED", "0 finalized payslips"),
    ("no_pay_leave", "NOT_EVALUATED", "incomplete month other than the first"),
    ("ot_without_hours", "NOT_EVALUATED", "overtime paid without its hours"),
])
def test_months_the_source_does_not_cover_are_never_averaged(db, organization, case, expected, reason):
    _active_pack(db, organization)
    emp = _retail(db, organization)
    may = {"legacy": dict(classified=False), "non_retail": dict(sector="FOOD_SERVICES"),
           "part_time": dict(employment="Part-time"),
           "no_pay_leave": dict(incomplete={"status": "INCOMPLETE_MONTH", "daysWorked": "18", "workingDaysInMonth": "21",
                                            "noPayDays": "3", "monthlyRatesForPwm": {"grossExOvertime": "3000"}}),
           "ot_without_hours": dict(overtime="200")}.get(case)
    if case != "missing":
        _pay(db, organization, emp, 5, gross="3000", **may)
    _pay(db, organization, emp, 6, gross="3000")
    _pay(db, organization, emp, 7, gross="2200")
    row, _ = _july_row(db, organization)
    assert (row["result"], row["averaging"]["status"]) == ("SHORTFALL", expected)
    assert reason in row["averaging"]["reasons"][0]
    assert row["averagingWarning"] is (expected == "NOT_EVALUATED")    # an unevaluated shortfall stays flagged


def test_a_non_retail_shortfall_is_never_averaged(db, organization):
    _active_pack(db, organization)
    emp = _employee(db, organization.id, "CLN", date_of_joining=date(2026, 1, 1), compliance_fields={
        "nric_fin": "S1234567D", "pwm_sector": "CLEANING", "pwm_group": "G1", "pwm_job_level": "GENERAL_INDOOR",
        "ea_workman": "YES", "ea_manager_executive": "NO"})
    for month in (5, 6, 7):
        _pay(db, organization, emp, month, gross="1000" if month == 7 else "5000", sector="CLEANING", group="G1",
             level="GENERAL_INDOOR")
    row, _ = _july_row(db, organization, "CLN")
    assert row["result"] == "SHORTFALL" and "averaging" not in row


def test_the_payslip_records_its_own_month_classification(db, organization):
    """Capture: the calculation writes the classification in force; a later
    reclassification never changes what an earlier payslip records."""
    from app.modules.payroll.service import _sg_trace_with_pwm_classification

    emp = _retail(db, organization)
    trace = {"wageMonth": "2026-07"}
    captured = _sg_trace_with_pwm_classification(trace, emp)
    assert captured["pwmClassification"] == {"sector": "RETAIL", "group": "ALL", "level": CASHIER,
                                             "employmentType": emp.employment_type}
    assert "pwmClassification" not in trace                                            # a copy, never mutated
    assert _sg_trace_with_pwm_classification(None, emp) is None                         # other countries untouched
    emp.compliance_fields = {**emp.compliance_fields, "pwm_job_level": SENIOR}
    assert captured["pwmClassification"]["level"] == CASHIER


def test_a_real_payroll_run_records_the_classification_and_the_report_reads_it(db, organization, monkeypatch):
    from app.modules.payroll.models import PayslipItem
    from tests.test_singapore_phase57_reports import _generate_payslips, _stub_codes

    _stub_codes(monkeypatch)
    _active_pack(db, organization)
    emp = _employee(db, organization.id, "LIVE", ctc=D("24000"), basic=D("24000"), hra=D("0"),
                    date_of_joining=date(2026, 1, 1),
                    compliance_fields={"nric_fin": "S1234567D", "pwm_sector": "RETAIL", "pwm_group": "ALL",
                                       "pwm_job_level": CASHIER, "ea_workman": "YES", "ea_manager_executive": "NO"})
    run = _generate_payslips(db, organization, date(2026, 7, 31), "Jul 2026 live")
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()
    assert item.sgp_calculation_trace["pwmClassification"]["level"] == CASHIER
    emp.compliance_fields = {**emp.compliance_fields, "pwm_job_level": SENIOR}          # promoted afterwards
    db.commit()
    row, _ = _july_row(db, organization, "LIVE")
    assert row["jobLevel"] == CASHIER                                                    # the month's own role
