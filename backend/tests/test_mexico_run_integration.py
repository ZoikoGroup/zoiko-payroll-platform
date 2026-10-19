"""Mexico Phase 6 — payroll run integration end to end on SYNTHETIC content:
generate (snapshot + money columns), the blocked sentinel + preflight
exceptions, preview non-mutation (MX-039), approval fingerprint + commit
(MX-039/040), reset, the downstream-lifecycle hook, lifecycles kept
separate (MX-041), deletion guards and the bank hold."""

from datetime import date
from decimal import Decimal as D

import pytest

from tests import _mx_run_helpers as rh


def test_generate_writes_the_mexican_snapshot_and_money_columns(db, monkeypatch):
    w = rh.world(db, monkeypatch)
    (item,) = rh.generate(db, w)
    snap = item.mx_calculation_snapshot
    assert item.status.lower() == "pending" and item.country_code == "MX"
    assert snap["inputHash"] and set(snap["components"]) >= {"content", "profile", "earnings", "bankInstruction"}
    res = snap["result"]
    assert D(res["gross"]) == D("600") * 15 == D(str(item.gross_pay))          # CALENDAR: 15 days
    assert D(str(item.basic_salary)) == D("9000")
    assert D(res["isr_withheld"]) == D(str(item.tds))
    assert res["pay_date"] == "2026-06-15" and res["tariff_period"] == "QUINCENAL_15"
    assert res["pack"]["pack_id"] == "MX-PAYROLL-TEST"


def test_fixed_salary_days_convention_uses_15(db, monkeypatch):
    w = rh.world(db, monkeypatch, convention="FIXED", period=(date(2026, 6, 16), date(2026, 6, 30)),
                 pay_date=date(2026, 6, 30))
    (item,) = rh.generate(db, w)
    res = item.mx_calculation_snapshot["result"]
    assert D(res["days_paid"]) == 15 and D(res["contribution_days"]) == 15


def test_unset_convention_blocks_into_a_sentinel_with_exceptions(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch, convention=None)
    (item,) = rh.generate(db, w)
    assert item.status.lower() == "failed" and item.mx_calculation_snapshot["blocked"] is True
    assert D(str(item.gross_pay or 0)) == 0 and D(str(item.net_pay or 0)) == 0      # nothing fabricated
    pre = mexico_run_service.run_preflight(db, w.run)
    assert [e["code"] for e in pre["exceptions"]] == ["MX_SALARY_DAYS_CONVENTION_UNSET"]
    assert pre["blocking"] == 1 and pre["failedItems"] == 1


def test_engine_block_lists_every_reason(db, monkeypatch):
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    w = rh.world(db, monkeypatch)
    db.query(C).delete()
    db.commit()
    (item,) = rh.generate(db, w)
    codes = {e["code"] for e in mexico_run_service.run_preflight(db, w.run)["exceptions"]}
    assert "MX_CLASSIFICATION_MISSING" in codes and item.status.lower() == "failed"


def test_regenerate_after_the_fix_clears_the_exceptions(db, monkeypatch):
    from app.modules.payroll import mexico_run_service, service

    w = rh.world(db, monkeypatch, convention=None)
    rh.generate(db, w)
    w.policy.salary_days_convention = "CALENDAR"
    db.commit()
    service.regenerate_employee_payslip(db, w.run.id, w.employee.id, w.org.id)
    (item,) = rh.mx_items(db, w.run)
    assert item.status.lower() == "pending" and not item.mx_calculation_snapshot.get("blocked")
    assert mexico_run_service.run_preflight(db, w.run)["exceptions"] == []


def test_pay_frequency_mismatch_and_unmapped_code_block(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch, freq="05")            # MONTHLY profile, quincenal run
    rh.generate(db, w)
    assert [e["code"] for e in mexico_run_service.run_preflight(db, w.run)["exceptions"]] == ["MX_PAY_FREQUENCY_MISMATCH"]
    w2 = rh.world(db, monkeypatch, freq="99", code="MXRUN2")
    rh.generate(db, w2)
    assert [e["code"] for e in mexico_run_service.run_preflight(db, w2.run)["exceptions"]] == \
        ["MX_PAY_FREQUENCY_MAPPING_MISSING"]


def test_absence_blocks(db, monkeypatch):
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import PayrollAttendanceRecord

    w = rh.world(db, monkeypatch)
    db.add(PayrollAttendanceRecord(organization_id=w.org.id, employee_id=w.employee.id, date=date(2026, 6, 3),
                                   status="absent"))
    db.commit()
    rh.generate(db, w)
    codes = [e["code"] for e in mexico_run_service.run_preflight(db, w.run)["exceptions"]]
    assert "MX_ABSENCE_RULES_MISSING" in codes


def test_variable_salary_needs_an_approved_opening_balance(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch, salary_type="VARIABLE")
    rh.generate(db, w)
    assert [e["code"] for e in mexico_run_service.run_preflight(db, w.run)["exceptions"]] == \
        ["MX_VARIABLE_OPENING_BALANCE_MISSING"]
    doc = _doc(db, w)
    row = mexico_run_service.record_opening_balance(
        db, w.org.id, w.employee.id, {"bimester": "2026-B2", "variable_total": "6100", "days": "61",
                                      "evidence_document_id": doc.id}, w.users[0].id)
    with pytest.raises(Exception):                                       # recorder cannot approve
        mexico_run_service.approve_opening_balance(db, w.org.id, row["id"], w.users[0].id)
    mexico_run_service.approve_opening_balance(db, w.org.id, row["id"], w.users[1].id)
    from app.modules.payroll import service

    service.regenerate_employee_payslip(db, w.run.id, w.employee.id, w.org.id)
    (item,) = rh.mx_items(db, w.run)
    assert D(item.mx_calculation_snapshot["result"]["sbc"]["components"]["variable_daily"]) == 100


def _doc(db, w):
    from tests._mx_employer_helpers import evidence_doc

    return evidence_doc(db, w.org.id)


# ── approval, commit, reset ──────────────────────────────────────────────────

def _approve(db, w):
    rh.generate(db, w)
    rh.advance(db, w)          # Draft → Review
    return rh.advance(db, w)   # Review → Approved (fingerprint + commit)


def test_approval_stores_the_fingerprint_and_commits_every_ledger(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch)
    run = _approve(db, w)
    fp = run.mx_approval_fingerprint
    assert run.status == "Approved" and fp["committedAt"] and fp["fingerprint"] and len(fp["items"]) == 1
    counts = mexico_run_service.ledger_counts(db, run)
    assert counts["imssBranchLines"] >= 14 and counts["isnLiabilities"] == 1 and counts["sbcHistory"] == 1
    assert counts["variableAccumulators"] == 1 and counts["benefitAccruals"] == 3
    assert mexico_run_service.commit_run(db, run, None) == {"committed": False, "reason": "already committed"}


def test_approval_refused_while_blocked_or_stale(db, monkeypatch):
    w = rh.world(db, monkeypatch, convention=None)
    rh.generate(db, w)
    rh.advance(db, w)
    with pytest.raises(Exception) as exc:
        rh.advance(db, w)
    assert exc.value.key == "MX_PREFLIGHT_BLOCKED"

    w2 = rh.world(db, monkeypatch, code="MXSTALE")
    rh.generate(db, w2)
    rh.advance(db, w2)
    w2.policy.aguinaldo_days = D("20")               # inputs change after generation
    db.commit()
    with pytest.raises(Exception) as exc:
        rh.advance(db, w2)
    assert exc.value.key == "MX_PAYSLIP_STALE"


@pytest.mark.parametrize("change", ["uma", "classification", "premium", "notice", "work_state", "bank"])
def test_every_bound_component_invalidates_the_approval(db, monkeypatch, change):
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import (
        ContributionRate, EmployeeStatutoryProfile, PayrollMxEarningClassification, PayrollMxInfonavitNotice,
        PayrollMxRiskPremium,
    )

    w = rh.world(db, monkeypatch)
    run = _approve(db, w)
    assert mexico_run_service.run_status(db, run)["payroll"]["approvalInvalidated"] is False
    if change == "uma":
        db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == w.pack.id,
                                          ContributionRate.component_key == "mx_uma_daily").update({"flat_amount": D("101")})
    elif change == "classification":
        db.query(PayrollMxEarningClassification).update({"version": 2})
    elif change == "premium":
        db.query(PayrollMxRiskPremium).update({"premium_rate_pct": D("0.6")})
    elif change == "notice":
        db.add(PayrollMxInfonavitNotice(organization_id=w.org.id, employee_id=w.employee.id, credit_number="C1",
                                        notice_type="SUSPENSION", effective_from=date(2026, 1, 1),
                                        authority_reference="SYNTHETIC", status="RECORDED"))
    elif change == "work_state":
        db.query(EmployeeStatutoryProfile).filter(EmployeeStatutoryProfile.employee_id == w.employee.id).update(
            {"mx_work_municipality": "Benito Juárez"})
    elif change == "bank":
        w.employee.bank_account = "000111222333"
    db.commit()
    status = mexico_run_service.run_status(db, run)
    assert status["payroll"]["approvalInvalidated"] is True and status["payroll"]["drift"]


def test_unrelated_change_does_not_invalidate(db, monkeypatch):
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import ContributionRate

    w = rh.world(db, monkeypatch)
    run = _approve(db, w)
    db.add(ContributionRate(jurisdiction_country="NL", component_key="nl_unrelated", label="x", employee_share="—",
                            employer_share="—", total="—", flat_amount=D("1")))
    db.commit()
    assert mexico_run_service.run_status(db, run)["payroll"]["approvalInvalidated"] is False


def test_authorize_and_pay_stay_refused(db, monkeypatch):
    w = rh.world(db, monkeypatch)
    _approve(db, w)
    with pytest.raises(Exception) as exc:
        rh.advance(db, w)
    assert exc.value.key == "MX_RUN_NOT_SUPPORTED"


def test_reset_removes_the_runs_ledgers_and_returns_to_review(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch)
    run = _approve(db, w)
    out = mexico_run_service.reset_run(db, run, w.users[0].id, "correct the daily salary")
    assert out["status"] == "Review" and sum(out["removed"].values()) > 0
    assert all(v == 0 for v in mexico_run_service.ledger_counts(db, run).values())
    assert run.mx_approval_fingerprint is None
    rh.advance(db, w)                                       # re-approval commits again
    assert mexico_run_service.ledger_counts(db, run)["isnLiabilities"] == 1


def test_reset_refused_once_a_downstream_lifecycle_acted(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch)
    run = _approve(db, w)
    monkeypatch.setattr(mexico_run_service, "run_downstream_actions", lambda db, run: ["CFDI 1 STAMPED"])
    with pytest.raises(Exception) as exc:
        mexico_run_service.reset_run(db, run, w.users[0].id, "x")
    assert "MX_RESET_DOWNSTREAM_ACTED" in str(getattr(exc.value, "detail", exc.value))
    assert mexico_run_service.ledger_counts(db, run)["isnLiabilities"] == 1
    assert mexico_run_service.run_downstream_actions.__module__  # hook exists for Phases 7, 8, 10


def test_reset_needs_a_reason_and_a_committed_run(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch)
    rh.generate(db, w)
    with pytest.raises(Exception):
        mexico_run_service.reset_run(db, w.run, w.users[0].id, "x")       # not approved
    run = _approve(db, rh.world(db, monkeypatch, code="MXR2"))
    with pytest.raises(Exception):
        mexico_run_service.reset_run(db, run, None, "  ")


# ── lifecycles, deletion, bank hold ──────────────────────────────────────────

def test_four_lifecycles_are_separate(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch)
    rh.generate(db, w)
    before = mexico_run_service.run_status(db, w.run)
    rh.advance(db, w)
    rh.advance(db, w)
    after = mexico_run_service.run_status(db, w.run)
    for lane in ("cfdi", "authorities", "bank"):
        assert before[lane] == after[lane]
    assert before["payroll"]["status"] == "Draft" and after["payroll"]["status"] == "Approved"


def test_delete_paths_work_before_approval_and_cascade_exceptions(db, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollMxPreflightException

    from sqlalchemy import text

    w = rh.world(db, monkeypatch, convention=None)
    db.commit()
    db.execute(text("PRAGMA foreign_keys=ON"))           # SQLite enforces FK actions only when asked
    (item,) = rh.generate(db, w)
    assert db.query(PayrollMxPreflightException).count() == 1
    service.delete_payslip(db, item.id, w.org.id)
    db.expire_all()
    assert db.query(PayrollMxPreflightException).count() == 0
    rh.generate(db, w)
    service.delete_payroll_run(db, w.run.id, w.org.id)
    assert db.query(PayrollMxPreflightException).count() == 0


def test_delete_refused_once_committed(db, monkeypatch):
    from app.modules.payroll import service

    w = rh.world(db, monkeypatch)
    run = _approve(db, w)
    (item,) = rh.mx_items(db, run)
    for fn, arg in ((service.delete_payslip, item.id), (service.delete_payroll_run, run.id)):
        with pytest.raises(Exception) as exc:
            fn(db, arg, w.org.id)
        assert "committed" in str(getattr(exc.value, "detail", exc.value))


def test_every_mexican_payment_is_held(db, monkeypatch):
    from app.modules.payroll import mexico_run_service

    w = rh.world(db, monkeypatch)
    (item,) = rh.generate(db, w)
    assert mexico_run_service.payment_treatment(db, w.org.id, w.run, [item]) == {item.id: "MX_BANK_SETTLEMENT_PHASE10"}


# ── preview never mutates (MX-039) ───────────────────────────────────────────

def test_preview_writes_nothing_and_is_deterministic(db, monkeypatch):
    from sqlalchemy import event

    from app.modules.payroll import service

    from app.modules.payroll.policy.models import PayrollPolicy

    w = rh.world(db, monkeypatch)
    # OOS-8, Mexico side: a brand-new organisation has no payroll policy yet;
    # a Mexican preview reads it read-only and must NOT create one.
    assert db.query(PayrollPolicy).filter(PayrollPolicy.organization_id == w.org.id).count() == 0
    writes = []

    def _listen(conn, cursor, statement, *a):
        if statement.strip().split()[0].upper() in ("INSERT", "UPDATE", "DELETE"):
            writes.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _listen)
    try:
        first = service.preview_payroll_run(db, w.org.id, [w.employee.id], "MX", *rh.PERIOD, pay_date=rh.PAY_DATE)
        second = service.preview_payroll_run(db, w.org.id, [w.employee.id], "MX", *rh.PERIOD, pay_date=rh.PAY_DATE)
    finally:
        event.remove(engine, "before_cursor_execute", _listen)
    assert writes == [] and not db.new and not db.dirty and not db.deleted
    assert db.query(PayrollPolicy).filter(PayrollPolicy.organization_id == w.org.id).count() == 0
    row = first["employees"][0] if "employees" in first else first["results"][0]
    assert row.get("mxPreview") and first == second


def test_preview_without_the_runs_pay_date_is_refused(db, monkeypatch):
    """MX-004: the pay date selects the law; a preview never assumes the
    period end (or today) stands for it."""
    from app.modules.payroll import service

    w = rh.world(db, monkeypatch)
    for kwargs in ({}, {"pay_date": None}):
        with pytest.raises(Exception) as exc:
            service.preview_payroll_run(db, w.org.id, [w.employee.id], "MX", *rh.PERIOD, **kwargs)
        assert getattr(exc.value, "key", "") == "MX_PAY_DATE_MISSING"


def test_preview_uses_the_runs_pay_date_not_the_period_end(db, monkeypatch):
    """A June 1–15 period paid on 1 July takes its pay-date law from the July
    rows: a rounding rule that changes on 1 July must reach the preview
    (contribution segments still use the period's own dates, MX-021)."""
    from datetime import date

    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate

    w = rh.world(db, monkeypatch)
    old = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == w.pack.id,
                                            ContributionRate.component_key == "mx_rounding_rule").one()
    old.effective_to = date(2026, 6, 30)
    db.add(ContributionRate(jurisdiction_pack_id=w.pack.id, jurisdiction_country="MX", component_key="mx_rounding_rule",
                            label="rounding", employee_share="—", employer_share="—", total="—", text_value="HALF_UP:1",
                            effective_from=date(2026, 7, 1)))
    db.commit()
    june = service.preview_payroll_run(db, w.org.id, [w.employee.id], "MX", *rh.PERIOD, pay_date=rh.PAY_DATE)
    july = service.preview_payroll_run(db, w.org.id, [w.employee.id], "MX", *rh.PERIOD, pay_date=date(2026, 7, 1))
    rj, rl = ((x.get("employees") or x.get("results"))[0]["mxPreview"] for x in (june, july))
    assert (rj["pay_date"], rj["rounding_rule"]) == ("2026-06-15", "HALF_UP:0.01")
    assert (rl["pay_date"], rl["rounding_rule"]) == ("2026-07-01", "HALF_UP:1")
    assert rl["sbc"]["segments"][0]["start"] == "2026-06-01"          # contributions keep the period's dates
