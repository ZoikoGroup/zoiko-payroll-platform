"""Regression tests for the wrong-result defects found by the 2026-10-14 HK gap audit
(docs/hk-evidence/HK_IMPLEMENTATION_GAP_MATRIX.md, D-A … D-H). TEST data only; app modules
are imported inside the tests (collection-order hazard)."""
from datetime import date
from decimal import Decimal as D

from tests.test_hong_kong_e2e import (  # noqa: F401  (hk is a fixture)
    CHECKER, MAKER, _employee, _item, _month, _profile, _spaced_codes, hk,
)


# ── D-A: contractual overtime is paid and flows into every statutory base ─────────────────────
# Wireframe §4 "Contractual overtime: do not invent a statutory universal overtime premium; apply
# contract/collective terms while including hours/earnings correctly for minimum-wage and wage
# calculations"; §10 "Contract overtime"; Labour Department Concise Guide ch.3 (wages include
# overtime pay; archived sources/ld_cg_03, sha256 dd61788183c75fca…).

def _overtime_hours(db, org_id, emp_id, days=10, total="10", overtime="2"):
    from app.modules.payroll import hong_kong_service

    hong_kong_service.record_work_hours(db, org_id, emp_id, [
        {"date": date(2026, 4, d).isoformat(), "hours": total, "overtimeHours": overtime} for d in range(1, days + 1)],
        MAKER.id)


def test_d_a_contractual_overtime_is_paid_and_counted_in_every_base(db, hk, monkeypatch):
    _spaced_codes(monkeypatch)
    emp = _employee(db, hk.org.id, "DA1", ctc=D("240000"))                     # HK$20,000 a month
    _profile(db, emp, hk.org.id, "2026-01-16", hkgContractualOvertimeHourlyRate="150")
    _overtime_hours(db, hk.org.id, emp.id)                                      # 10 days x 2 h = 20 h
    run = _month(db, hk.org, 4)
    item = _item(db, run, emp)
    assert D(str(item.overtime)) == D("3000.00")                                # 20 h x HK$150 (contract rate)
    trace = item.hk_calculation_trace
    ot = trace["workerFacts"]["overtime"]
    assert ot["status"] == "PAID" and D(ot["hours"]) == D("20") and D(ot["hourlyRate"]) == D("150")
    for obligation in ("EO_WAGES", "MPF_RI", "SMW_WAGES"):                   # per-obligation classification
        line = next(l for l in trace["classification"][obligation]["lines"] if l["component"] == "overtime")
        assert line["treatment"] == "INCLUDED" and D(line["amount"]) == D("3000.00")
    assert D(trace["classification"]["EO_WAGES"]["included"]) == D("23000.00")
    current = trace["mpf"]["currentPeriod"]
    assert D(current["relevantIncome"]) == D("23000.00") and current["branch"] == "WITHIN_LEVELS"
    assert D(trace["mpf"]["employee"]) == D("1150.00") and D(trace["mpf"]["employer"]) == D("1150.00")
    assert D(trace["ird"]["reportable"]["SALARY_WAGES"]) == D("11000.00")    # basic 8,000 + overtime 3,000
    assert D(trace["result"]["gross"]) == D("23000.00")


def test_d_a_overtime_hours_without_a_contract_rate_pay_nothing_and_block(db, hk, monkeypatch):
    from app.modules.payroll import hong_kong_service

    _spaced_codes(monkeypatch)
    emp = _employee(db, hk.org.id, "DA2", ctc=D("240000"))
    _profile(db, emp, hk.org.id, "2026-01-16")                                  # no overtime rate recorded
    _overtime_hours(db, hk.org.id, emp.id, days=3)
    from app.modules.payroll.models import PayrollStatus

    run = _month(db, hk.org, 4, status=PayrollStatus.DRAFT)
    item = _item(db, run, emp)
    assert D(str(item.overtime)) == D("0")
    assert item.hk_calculation_trace["workerFacts"]["overtime"]["status"] == "RATE_NOT_RECORDED"
    checks = hong_kong_service.hk_payroll_preflight(db, hk.org.id, run.id)["checks"]
    block = [c for c in checks if c["code"] == "HK_OVERTIME_RATE_NOT_RECORDED" and c["employeeId"] == emp.id]
    assert block and block[0]["severity"] == "BLOCK" and "contractual overtime hourly rate" in block[0]["action"]
