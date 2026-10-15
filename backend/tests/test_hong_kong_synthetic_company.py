"""Synthetic Hong Kong company harness (gap-audit STEP 2).

One synthetic HK employer and eight synthetic employees (example.com addresses,
the published HKID check-digit example, invented salaries) run through the
SHARED runtime for April–June 2026: real generate_payslips_for_run months, the
real Review -> Approved lifecycle (so every HK preflight gate applies), then
the cross-output reconciliations every later domain extends:

  * payslip totals = ledger (run totals; bank file + IR56G-held = net);
  * MPF totals = the eMPF batch per contribution period;
  * IRD accumulator (BIR56A / IR56B) = committed pay;
  * no duplicate IR forms.

Local SQLite only (conftest `db`); app.* imported lazily (collection-order hazard).
"""
from datetime import date, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

from tests.test_hong_kong_e2e import (  # noqa: F401  (hk is a fixture)
    CHECKER, INTERNAL_FILING, MAKER, _employee, _profile, _spaced_codes, hk,
)

MONTHS = (4, 5, 6)


def _record(db, org_id, emp, start, end, per_day, weekdays=(0, 1, 2, 3, 4), overtime=None):
    """Verified hours for EVERY day (rest days recorded as 0 h — the minimum-wage test needs the
    whole wage period covered); `overtime` maps a date to its overtime hours."""
    from app.modules.payroll import hong_kong_service

    entries, d = [], start
    while d <= end:
        row = {"date": d.isoformat(), "hours": str(per_day) if d.weekday() in weekdays else "0"}
        if overtime and d in overtime:
            row["hours"] = str(D(per_day) + overtime[d])
            row["overtimeHours"] = str(overtime[d])
        entries.append(row)
        d += timedelta(days=1)
    hong_kong_service.record_work_hours(db, org_id, emp.id, entries, MAKER.id)


def _new(db, org_id, code, name, ctc, joined, **kw):
    return _employee(db, org_id, code, name=name, ctc=D(ctc), date_of_joining=joined,
                     email=f"{code.lower()}@example.com", **kw)


def build_company(db, hk, monkeypatch):
    """The eight synthetic employees. HK1 (the fixture's employee, HK$20,000/month,
    joined 16 Jan 2026) is the overtime earner."""
    _spaced_codes(monkeypatch)
    org = hk.org.id
    e = SimpleNamespace()
    hk.emp.email = "hk1@example.com"
    db.commit()

    # 1. Monthly salaried above the MPF maximum relevant income (HK$50,000 > HK$30,000).
    e.high = _new(db, org, "SC1", "Synthetic Above-Cap", "600000", date(2026, 1, 16))
    _profile(db, e.high, org, "2026-01-16", hkgContractualWeeklyHours="40")
    # 2. Monthly salaried below the MPF minimum relevant income (HK$6,000 < HK$7,100), part-time.
    e.low = _new(db, org, "SC2", "Synthetic Below-Minimum", "72000", date(2026, 1, 16))
    _profile(db, e.low, org, "2026-01-16", hkgContractualWeeklyHours="20")
    # 3. Hourly part-timer near the SMW, across the 1 May 2026 rate change.
    e.hourly = _new(db, org, "SC3", "Synthetic Hourly Part-timer", "48000", date(2026, 1, 16))
    _profile(db, e.hourly, org, "2026-01-16", hkgPayBasis="HOURLY", hkgContractualWeeklyHours="20")
    # 4. Joins 13 Apr 2026: inside the 60-day / 30-day contribution holiday in April.
    e.joiner = _new(db, org, "SC4", "Synthetic New Joiner", "360000", date(2026, 4, 13))
    _profile(db, e.joiner, org, "2026-04-13", hkgContractualWeeklyHours="40")
    # 5. Overtime earner: HK1 with a contractual overtime rate from 1 Apr 2026.
    e.overtime = hk.emp
    _profile(db, e.overtime, org, "2026-04-01", hkgContractualWeeklyHours="40",
             hkgContractualOvertimeHourlyRate="150")
    # 6. Leaver with final pay, staying in Hong Kong (IR56F), resigns 29 May 2026.
    e.leaver = _new(db, org, "SC6", "Synthetic Leaver", "300000", date(2026, 1, 16), date_of_leaving=date(2026, 5, 29))
    _profile(db, e.leaver, org, "2026-01-16", hkgContractualWeeklyHours="40")
    _profile(db, e.leaver, org, "2026-05-01", hkgTerminationDate="2026-05-29", hkgTerminationReason="RESIGNATION")
    # 7. Leaving Hong Kong: IR56G departure, last day 30 Jun 2026, departs 15 Jul 2026.
    e.departing = _new(db, org, "SC7", "Synthetic Departing", "420000", date(2026, 1, 16),
                       date_of_leaving=date(2026, 6, 30))
    _profile(db, e.departing, org, "2026-01-16", hkgContractualWeeklyHours="40")
    _profile(db, e.departing, org, "2026-06-01", hkgTerminationDate="2026-06-30", hkgTerminationReason="RESIGNATION",
             hkgExpectedDepartureDate="2026-07-15")
    # 8. Hired before 1 May 2025 (pre-transition MPF offsetting portion), frozen wage on the profile.
    e.veteran = _new(db, org, "SC8", "Synthetic Pre-2025 Hire", "300000", date(2024, 3, 1))
    _profile(db, e.veteran, org, "2024-03-01", hkgContractualWeeklyHours="40", hkgPreTransitionMonthlyWage="24000",
             hkgPreTransitionWageBasis="LAST_FULL_MONTH", hkgPreTransitionEvidenceRef="SYNTHETIC-PAYROLL-2025-04")

    start, end = date(2026, 3, 1), date(2026, 6, 30)
    for emp, per_day, weekdays in ((e.high, 8, range(5)), (e.low, 4, range(5)), (e.hourly, 5, range(4)),
                                   (e.veteran, 8, range(5))):
        _record(db, org, emp, start, end, per_day, tuple(weekdays))
    _record(db, org, e.joiner, date(2026, 4, 13), end, 8)
    _record(db, org, e.leaver, start, date(2026, 5, 29), 8)
    _record(db, org, e.departing, start, end, 8)
    _record(db, org, e.overtime, start, end, 8,
            overtime={date(2026, m, d): D("2") for m in MONTHS for d in (6, 7, 8, 9, 10)
                      if date(2026, m, d).weekday() < 5})
    return e


def run_month(db, org, m):
    """Generate, then Review -> Approved through the real lifecycle (HK preflight gates apply)."""
    import calendar

    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayrollStatus

    last = calendar.monthrange(2026, m)[1]
    run = PayrollRun(organization_id=org.id, period_label=f"2026-{m:02d}", period_start=date(2026, m, 1),
                     period_end=date(2026, m, last), pay_date=date(2026, m, last))
    db.add(run)
    db.commit()
    service.generate_payslips_for_run(db, run, org.id)
    run.status = PayrollStatus.REVIEW
    db.commit()
    return service.advance_payroll_run_status(db, run.id, MAKER.id, org.id)


def quarter(db, hk, monkeypatch):
    """Build the company, file the departing employee's IR56G (prepared by MAKER, filed by CHECKER),
    run and approve April–June 2026, then raise the IR event cases twice (idempotency)."""
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import PayslipItem

    e = build_company(db, hk, monkeypatch)
    hold = hong_kong_service.identify_departure(db, hk.org.id, e.departing.id, date(2026, 7, 15), MAKER.id,
                                                identified_on=date(2026, 5, 20))
    hold = hong_kong_service.record_ir56g_filed(db, hk.org.id, hold.id, date(2026, 6, 10), "IR56G-SYN-1",
                                                CHECKER.id, submission=INTERNAL_FILING)
    runs = {m: run_month(db, hk.org, m) for m in MONTHS}
    items = {m: {i.employee_id: i for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == runs[m].id)}
             for m in MONTHS}
    controls = []
    for emp in (e.high, e.low, e.hourly, e.joiner, e.overtime, e.leaver, e.departing, e.veteran):
        for _ in range(2):
            hong_kong_service.create_event_cases(db, hk.org.id, emp.id, MAKER.id, controls=controls)
    return SimpleNamespace(e=e, runs=runs, items=items, hold=hold, controls=controls)


def _sum(rows, attr):
    return sum((D(str(getattr(r, attr) or 0)) for r in rows), D("0"))


def _paid(item):
    """Remuneration actually paid: gross less the unpaid-day deduction (not remuneration)."""
    return D(str(item.gross_pay)) - D(str(item.attendance_deduction or 0))


# ── 1. payslip totals = ledger ─────────────────────────────────────────────────────────────────

def test_payslip_totals_equal_the_ledger(db, hk, monkeypatch):
    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.models import PayrollStatus

    q = quarter(db, hk, monkeypatch)
    for m in MONTHS:
        run, items = q.runs[m], list(q.items[m].values())
        assert run.status == PayrollStatus.APPROVED
        for it in items:                                                    # each payslip adds up
            assert D(str(it.gross_pay)) - D(str(it.total_deductions)) == D(str(it.net_pay)), (m, it.employee_id)
        assert (run.total_gross, run.total_net, run.total_employer_contribution) == (
            _sum(items, "gross_pay"), _sum(items, "net_pay"), _sum(items, "employer_pension"))
        # Every dollar of net pay is either in the bank file or held for the IR56G — never both, never lost.
        banked = sum((D(str(round(r.amount, 2))) for r in service._build_bank_export_rows(db, run, items, hk.org.id)),
                     D("0"))
        treatment = hong_kong_service.payment_treatment(db, hk.org.id, run, items)
        held = sum((D(str(it.net_pay)) for it in items if treatment.get(it.id, ("",))[0] == "HELD"), D("0"))
        assert banked + held == D(str(run.total_net)), m
        assert (held > 0) == (m == 6), m                                    # only the departing employee's June pay


# ── 2. MPF totals = eMPF batch per period ──────────────────────────────────────────────────────

def test_mpf_totals_equal_the_empf_batch_for_every_period(db, hk, monkeypatch):
    from app.modules.payroll import hong_kong_service

    q = quarter(db, hk, monkeypatch)
    for m in MONTHS:
        items = list(q.items[m].values())
        covered = [i for i in items if i.hk_calculation_trace["mpf"]["coverage"]["status"] == "COVERED"]
        sub = hong_kong_service.prepare_empf_submission(db, hk.org.id, f"2026-{m:02d}", MAKER.id)
        assert sub.status == "VALIDATED", (m, sub.status)
        assert sub.totals["employees"] == len(covered)
        assert D(sub.totals["employerMandatory"]) == _sum(items, "employer_pension")
        assert D(sub.totals["employeeMandatory"]) == _sum(items, "employee_pension")
        assert {r["payslipId"] for r in sub.rows} == {i.id for i in covered}


# ── 3. IRD accumulator = committed pay ─────────────────────────────────────────────────────────

def test_ird_accumulator_equals_committed_pay(db, hk, monkeypatch):
    from app.modules.payroll import hong_kong_service

    q = quarter(db, hk, monkeypatch)
    paid = {}
    for m in MONTHS:
        for emp_id, it in q.items[m].items():
            paid[emp_id] = paid.get(emp_id, D("0")) + _paid(it)
            # Each payslip's IRD fields carry exactly what was paid.
            reportable = sum((D(v) for v in it.hk_calculation_trace["ird"]["reportable"].values()), D("0"))
            assert reportable == _paid(it), (m, emp_id)
    out = hong_kong_service.generate_annual_return(db, hk.org.id, "2026/27", MAKER.id)
    rec = out["reconciliation"]
    assert D(rec["committedPayrollGross"]) == sum(paid.values(), D("0"))
    assert rec["status"] == "Reconciled" and D(rec["variance"]) == 0
    # The filed IR56G reports the departing employee's income: removed from IR56B — that and nothing else.
    assert D(rec["lessReportedOnIr56fIr56g"]) == paid[q.e.departing.id]
    rows = {r["employeeId"]: r for r in out["employees"]}
    assert rows[q.e.departing.id]["status"] == "SUPPRESSED"
    assert set(rows) == set(paid)                                       # one row per paid employee


# ── 4. no duplicate IR forms ───────────────────────────────────────────────────────────────────

def test_no_duplicate_ir_forms(db, hk, monkeypatch):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import HongKongIrdReportingCase

    q = quarter(db, hk, monkeypatch)
    hong_kong_service.generate_annual_return(db, hk.org.id, "2026/27", MAKER.id)
    out = hong_kong_service.generate_annual_return(db, hk.org.id, "2026/27", MAKER.id)        # regenerated
    live = [c for c in db.query(HongKongIrdReportingCase).filter(HongKongIrdReportingCase.organization_id == hk.org.id)
            if c.status not in ("CANCELLED", "AMENDED")]
    keys = [(c.employee_id, c.form_type, c.year_of_assessment if c.form_type in ("IR56B", "BIR56A") else c.event_date)
            for c in live]
    assert len(keys) == len(set(keys))                                  # one form per employee, form and event
    forms = {}
    for c in live:
        forms.setdefault(c.employee_id, set()).add(c.form_type)
    assert "IR56F" in forms[q.e.leaver.id] and "IR56G" not in forms[q.e.leaver.id]
    assert "IR56G" in forms[q.e.departing.id] and "IR56F" not in forms[q.e.departing.id]
    assert [c["control"] for c in q.controls] == ["IR56G_DEPARTURE_APPLIES"] * 2   # explained, not silent
    # The leaver's open IR56F holds the IR56B for resolution — never two clean forms for one income (D-L).
    [leaver_row] = [r for r in out["employees"] if r["employeeId"] == q.e.leaver.id]
    assert any("IR56F case #" in err for err in leaver_row["validationErrors"])
    # IR56E only where the profile records the commencement as likely chargeable (HK1, the fixture's employee).
    assert forms[q.e.overtime.id] == {"IR56B", "IR56E"}
    for emp in (q.e.high, q.e.low, q.e.hourly, q.e.joiner, q.e.veteran):
        assert forms[emp.id] == {"IR56B"}, emp.employee_code                # nobody else gets an event form


# ── scenario facts the reconciliations rest on (hand-checked, TEST data) ────────────────────────

def test_each_synthetic_scenario_behaves_as_hand_checked(db, hk, monkeypatch):
    q = quarter(db, hk, monkeypatch)
    e, it = q.e, q.items
    for m in MONTHS:
        # above the HK$30,000 maximum relevant income: HK$1,500 each side
        assert (it[m][e.high.id].employee_pension, it[m][e.high.id].employer_pension) == (D("1500.00"), D("1500.00"))
        # below the HK$7,100 minimum: employee nil, employer 5% (HK$300)
        assert (it[m][e.low.id].employee_pension, it[m][e.low.id].employer_pension) == (D("0.00"), D("300.00"))
    # SMW across 1 May 2026: HK$42.10 for April's hours, HK$43.10 from May (pack rows, sourced).
    for m, rate in ((4, D("42.10")), (5, D("43.10")), (6, D("43.10"))):
        smw = it[m][e.hourly.id].hk_calculation_trace["minimumWage"]
        assert smw["status"] == "COMPLIANT" and D(smw["minimumDue"]) == D(smw["hours"]) * rate, m
    # Joiner (13 Apr): 12 unpaid days in April; 60-day rule → nothing until June, then the employer
    # catches up from day one (April 18,000 x 5% = 900; May 1,500) plus June 1,500; employee holiday April–May.
    j4, j5, j6 = it[4][e.joiner.id], it[5][e.joiner.id], it[6][e.joiner.id]
    assert j4.hk_calculation_trace["mpf"]["coverage"]["status"] == "PENDING_60_DAY" and j4.net_pay == D("18000.00")
    assert j5.hk_calculation_trace["mpf"]["currentPeriod"]["employeeBasis"] == "CONTRIBUTION_HOLIDAY"
    assert (j6.employer_pension, j6.employee_pension) == (D("3900.00"), D("1500.00"))
    # Overtime at the contract rate HK$150/h: 10 h in April, 6 h in May and June.
    assert [D(str(it[m][e.overtime.id].overtime)) for m in MONTHS] == [D("1500.00"), D("900.00"), D("900.00")]
    # Leaver: 2 unpaid days after 29 May in the final period, nothing payable in June (D-J).
    assert it[5][e.leaver.id].hk_calculation_trace["workerFacts"]["postLeavingUnpaidDays"] == 2
    assert e.leaver.id not in it[6]
    # Departing employee: IR56G filed by a second person; June pay held, not deducted.
    assert q.hold.state == "IR56G_FILED_HOLD_ACTIVE"
    assert it[6][e.departing.id].net_pay == D("33500.00")
    # Pre-1-May-2025 hire is paid normally.
    assert it[6][e.veteran.id].gross_pay == D("25000.00")
