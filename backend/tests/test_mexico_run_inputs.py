"""Mexico Phase 6 — where the engine inputs come from (plan §3): contribution
segments split at a mid-period row change (MX-021), approved hours with
four-eyes (D1), the month-to-date of committed runs (MX-013), add_payslip_item
(manual amounts never silently replaced), and the org routes. SYNTHETIC."""

from datetime import date
from decimal import Decimal as D

import pytest

from tests import _mx_run_helpers as rh


def test_a_mid_period_uma_change_splits_the_contribution_segments(db, monkeypatch):
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import ContributionRate

    w = rh.world(db, monkeypatch, freq="02", period=(date(2026, 1, 26), date(2026, 2, 1)), pay_date=date(2026, 2, 1))
    old = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == w.pack.id,
                                            ContributionRate.component_key == "mx_uma_daily").one()
    old.effective_to = date(2026, 1, 31)
    db.add(ContributionRate(jurisdiction_pack_id=w.pack.id, jurisdiction_country="MX", component_key="mx_uma_daily",
                            label="UMA", employee_share="—", employer_share="—", total="—", flat_amount=D("110"),
                            effective_from=date(2026, 2, 1)))
    from app.modules.payroll.models import PayrollMxRiskPremium

    db.query(PayrollMxRiskPremium).update({"period_from": date(2026, 1, 1)})     # cover the January days
    db.commit()
    segs = mexico_run_service.segments(db, w.pack, date(2026, 1, 26), date(2026, 2, 1))
    assert [(s["start"], s["days"]) for s in segs] == [(date(2026, 1, 26), D(6)), (date(2026, 2, 1), D(1))]
    assert [s["rate_map"]["mx_uma_daily"]["flat_amount"] for s in segs] == ["100.0000", "110.0000"] or \
        [D(s["rate_map"]["mx_uma_daily"]["flat_amount"]) for s in segs] == [D(100), D(110)]
    (item,) = rh.generate(db, w)
    res = item.mx_calculation_snapshot["result"]
    assert [D(s["uma_daily"]) for s in res["sbc"]["segments"]] == [D(100), D(110)]


def test_period_kinds_from_run_dates():
    from app.modules.payroll.mexico_run_service import run_period_kind as k

    assert k(date(2026, 6, 1), date(2026, 6, 15)) == "QUINCENAL_15"
    assert k(date(2026, 6, 16), date(2026, 6, 30)) == "QUINCENAL_15"
    assert k(date(2026, 2, 16), date(2026, 2, 28)) == "QUINCENAL_15"
    assert k(date(2026, 6, 1), date(2026, 6, 30)) == "MONTHLY"
    assert k(date(2026, 6, 1), date(2026, 6, 7)) == "WEEKLY_7"
    assert k(date(2026, 6, 1), date(2026, 6, 14)) is None           # catorcenal: no Art. 96 tariff


def test_salary_days_convention(monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.mexico_run_service import salary_days

    feb = (date(2026, 2, 1), date(2026, 2, 28))
    assert salary_days("MONTHLY", *feb, "CALENDAR") == 28 and salary_days("MONTHLY", *feb, "FIXED") == 30
    assert salary_days("WEEKLY_7", date(2026, 6, 1), date(2026, 6, 7), None) == 7      # convention not needed
    with pytest.raises(MXBlock) as exc:
        salary_days("QUINCENAL_15", date(2026, 6, 16), date(2026, 6, 30), None)
    assert exc.value.key == "MX_SALARY_DAYS_CONVENTION_UNSET"


# ── approved hours (D1) ──────────────────────────────────────────────────────

def _hours(db, w, **over):
    from app.modules.payroll import mexico_run_service
    from tests._mx_employer_helpers import evidence_doc

    data = {"week_start": date(2026, 6, 1), "ordinary_hours": "40", "overtime_hours": "0", "sundays_worked": "1",
            "rest_days_worked": "0", "evidence_document_id": evidence_doc(db, w.org.id).id}
    data.update(over)
    return mexico_run_service.record_hours(db, w.org.id, w.employee.id, data, w.users[0].id)


def test_hours_need_evidence_and_a_second_approver(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch)
    with pytest.raises(Exception):
        _hours(db, w, evidence_document_id=None)
    row = _hours(db, w)
    with pytest.raises(Exception):
        mexico_run_service.approve_hours(db, w.org.id, row["id"], w.users[0].id)
    assert mexico_run_service.approve_hours(db, w.org.id, row["id"], w.users[1].id)["status"] == "APPROVED"


def test_only_approved_hours_reach_the_payslip(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch)
    rh.classify(db, "MX_SUNDAY_PREMIUM", sbc="VARIABLE")
    _hours(db, w)                                          # DRAFT only
    (item,) = rh.generate(db, w)
    assert item.mx_calculation_snapshot["result"]["labor"]["sunday"] is None
    row = mexico_run_service.list_hours(db, w.org.id, w.employee.id)[0]
    mexico_run_service.approve_hours(db, w.org.id, row["id"], w.users[1].id)
    from app.modules.payroll import service

    service.regenerate_employee_payslip(db, w.run.id, w.employee.id, w.org.id)
    (item,) = rh.mx_items(db, w.run)
    res = item.mx_calculation_snapshot["result"]
    assert D(res["labor"]["sunday"]["amount"]) == D("600") * D("0.25")
    assert D(res["gross"]) == D("9000") + D("150") == D(str(item.gross_pay))


def test_overtime_blocks_without_an_hourly_rate_rule(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch)
    row = _hours(db, w, overtime_hours="5", sundays_worked="0")
    mexico_run_service.approve_hours(db, w.org.id, row["id"], w.users[1].id)
    rh.generate(db, w)
    assert [e["code"] for e in mexico_run_service.run_preflight(db, w.run)["exceptions"]] == ["MX_HOURLY_RATE_RULE_MISSING"]


# ── month to date (MX-013) ───────────────────────────────────────────────────

def test_month_to_date_counts_committed_runs_only(db, monkeypatch):
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import PayrollRun

    w = rh.world(db, monkeypatch)
    first = rh.generate(db, w)[0]
    second = PayrollRun(organization_id=w.org.id, period_label="Jun 16-30, 2026", period_start=date(2026, 6, 16),
                        period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30), status="Draft",
                        created_by=w.users[0].id)
    db.add(second)
    db.commit()
    assert mexico_run_service._month_to_date(db, w.employee.id, second, date(2026, 6, 30))["taxable"] == 0
    rh.advance(db, w)
    rh.advance(db, w)                                       # first run committed
    mtd = mexico_run_service._month_to_date(db, w.employee.id, second, date(2026, 6, 30))
    assert mtd["taxable"] == D(first.mx_calculation_snapshot["result"]["isr_taxable"])


# ── add_payslip_item ─────────────────────────────────────────────────────────

def _item(w, basic):
    from app.modules.payroll.schemas import PayslipItemCreate

    fields = PayslipItemCreate.model_fields
    data = {"employee_id": w.employee.id, "basic_salary": D(basic), "employeeId": w.employee.id, "basicSalary": D(basic)}
    return PayslipItemCreate(**{k: v for k, v in data.items() if k in fields})


def test_add_item_refuses_disagreeing_amounts_and_accepts_the_computed_ones(db, monkeypatch):
    from app.modules.payroll import service

    w = rh.world(db, monkeypatch)
    with pytest.raises(Exception) as exc:
        service.add_payslip_item(db, w.run.id, _item(w, "8000"), w.org.id)
    assert "Mexico computes 9000" in str(getattr(exc.value, "detail", exc.value))
    item = service.add_payslip_item(db, w.run.id, _item(w, "9000"), w.org.id)
    assert item.mx_calculation_snapshot["inputHash"] and D(str(item.gross_pay)) == D("9000")


# ── org routes ───────────────────────────────────────────────────────────────

def test_run_routes(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    w = rh.world(db, monkeypatch, convention=None)
    rh.generate(db, w)
    with http(db, principal(w.org.id, w.users[0].id)) as client:
        pre = client.get(f"{ORG_BASE}/runs/{w.run.id}/preflight").json()
        assert pre["blocking"] == 1 and pre["exceptions"][0]["code"] == "MX_SALARY_DAYS_CONVENTION_UNSET"
        ack = client.post(f"{ORG_BASE}/runs/{w.run.id}/preflight/{pre['exceptions'][0]['id']}/acknowledge",
                          json={"note": "x"})
        assert ack.status_code == 400                       # BLOCK can never be acknowledged
        st = client.get(f"{ORG_BASE}/runs/{w.run.id}/status").json()
        assert st["cfdi"]["status"] == "NOT_STARTED" and st["bank"]["status"] == "HELD"
        assert st["payroll"]["status"] == "Draft"
        assert client.post(f"{ORG_BASE}/runs/{w.run.id}/reset", json={"reason": "x"}).status_code == 400
        assert client.get(f"{ORG_BASE}/employees/{w.employee.id}/hours").json() == []


def test_run_items_api_carries_the_mexican_snapshot(db, monkeypatch):
    """Found by the Phase 6 browser check: the shared payslip response model
    stripped mxCalculationSnapshot (only the service dict had it)."""
    from tests._mx_employer_helpers import http, principal

    w = rh.world(db, monkeypatch)
    rh.generate(db, w)
    w.org.workspace_type = "EVALUATION"
    db.commit()
    with http(db, principal(w.org.id, w.users[0].id)) as client:
        items = client.get(f"/api/payroll/runs/{w.run.id}/items").json()
    snap = items[0].get("mxCalculationSnapshot")
    assert snap and snap["inputHash"] and snap["result"]["pay_date"] == "2026-06-15"
