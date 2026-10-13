"""Netherlands Phase 8 — corrections, back-pay methods and the AWf revision
workflow (ZP-NL-ENG-001 NL-011, NL-016, NL-045, NL-004).

Built on the Phase 5–7 integration fixture (in-memory SQLite; SYNTHETIC
wage-tax rows: 0–5000 -> €1,000.00, 5000+ -> €1,325.08 with the credit).
"""
from datetime import date
from decimal import Decimal as D

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import netherlands_service as nl, service
from app.modules.payroll.models import (
    PayrollNlAwfRevision, PayrollNlContractVersion, PayrollNlTaxTableFile, PayrollNlVacationAllowanceLedger,
    PayrollNlVcrSnapshot, PayrollNlWkrAccumulator, PayrollRun, PayslipItem,
)
from tests.test_netherlands_service_integration import APPROVER, PREPARER, _approve, _item, _run, nlx  # noqa: F401


def _committed_month(db, nlx, month):
    run = _run(db, nlx.org, month)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    _approve(db, run, nlx.org)
    return run, _item(db, run, nlx.emp)


def _correct(db, nlx, item, earnings=None, **kw):
    out = nl.create_nl_correction(db, nlx.org.id, item.id, kw.pop("reason", "salary restated"),
                                  kw.pop("method", "REPROCESS_ORIGINAL_PERIOD"),
                                  kw.pop("corrected_inputs", {"earnings": earnings} if earnings else {}),
                                  kw.pop("actor_id", PREPARER))
    db.commit()
    return out


def _approve_run_id(db, nlx, run_id):
    run = db.query(PayrollRun).filter(PayrollRun.id == run_id).one()
    return _approve(db, run, nlx.org)


# ── replay ────────────────────────────────────────────────────────────────

def test_frozen_inputs_replay_the_original_exactly(db, nlx):
    _, item = _committed_month(db, nlx, 3)
    snap = item.nl_calculation_snapshot
    replay = nl.nl_replay(db, snap["inputs"])
    assert (replay["inputHash"], replay["totals"]) == (snap["inputHash"], snap["totals"])


def test_a_changed_table_file_refuses_replay(db, nlx):
    _, item = _committed_month(db, nlx, 3)
    db.query(PayrollNlTaxTableFile).update({"file_sha256": "d" * 64})
    db.commit()
    with pytest.raises(BadRequestException, match="cannot be replayed exactly"):
        _correct(db, nlx, item, {"base_salary": "4000"})


# ── corrections ───────────────────────────────────────────────────────────

def test_correction_recomputes_the_original_period_and_moves_vcr_at_the_latest_point(db, nlx):
    _, march = _committed_month(db, nlx, 3)
    _committed_month(db, nlx, 4)                     # April already committed on top of March
    out = _correct(db, nlx, march, {"base_salary": "4000"})
    t = out["totals"]
    assert t["gross"] == "-1000.00"
    assert t["wageTax"] == "-325.08"                 # original March table: 1000.00 vs 1325.08
    assert t["netPay"] == "-674.92"
    vcr = out["vcr"]
    assert vcr["increments"]["EI"] == "-1000.00" and vcr["after"]["EI"]["revision"] == 3   # appended, not rewritten
    delta = db.query(PayslipItem).filter(PayslipItem.id == out["deltaPayslipId"]).one()
    corr = delta.nl_calculation_snapshot["correction"]["delta"]
    assert corr["premium_awf"] == "-27.40"           # (5000 - 1000) x 2.74% - 137.00
    assert corr["zvwEr"] == "-61.00"                 # employer levy only — net is not touched by it
    assert D(str(delta.net_pay)) == D("-674.92")


def test_approving_the_correction_commits_append_only_ledgers(db, nlx):
    _, march = _committed_month(db, nlx, 3)
    out = _correct(db, nlx, march, {"base_salary": "4000"})
    _approve_run_id(db, nlx, out["correctionRunId"])
    rows = db.query(PayrollNlVcrSnapshot).filter_by(family="EI").order_by(PayrollNlVcrSnapshot.revision).all()
    assert [(r.revision, r.is_correction, r.base_increment) for r in rows] == [(1, False, D("5000.00")),
                                                                              (2, True, D("-1000.00"))]
    vac = db.query(PayrollNlVacationAllowanceLedger).order_by(PayrollNlVacationAllowanceLedger.id).all()
    assert [(v.entry_type, v.amount, v.balance_after) for v in vac] == [("ACCRUAL", D("400.00"), D("400.00")),
                                                                       ("CORRECTION", D("-80.00"), D("320.00"))]
    assert db.query(PayrollNlWkrAccumulator).order_by(PayrollNlWkrAccumulator.revision.desc()).first() \
        .fiscal_wage_cumulative == D("4000.00")


def test_a_second_correction_builds_on_the_first(db, nlx):
    _, march = _committed_month(db, nlx, 3)
    first = _correct(db, nlx, march, {"base_salary": "4000"})
    _approve_run_id(db, nlx, first["correctionRunId"])
    second = _correct(db, nlx, march, {"base_salary": "4500"})
    assert second["sequence"] == 2 and second["totals"]["gross"] == "500.00"   # relative to 4000, not 5000
    assert second["vcr"]["after"]["EI"]["revision"] == 3


@pytest.mark.parametrize("kwargs,match", [
    ({"method": "RETRO_RATE"}, "no generic retro rate"),
    ({"method": "SPECIAL_REMUNERATION_CURRENT_PERIOD"}, "classified SPECIAL"),
    ({"corrected_inputs": {"withTaxCredit": False}}, "NL-031"),
    ({"corrected_inputs": {"contract": {"agreed_hours_per_week": "20"}}}, "cannot be restated"),
    ({"corrected_inputs": {"earnings": {"base_salary": "5000.00"}}}, "no change"),
    ({"reason": " "}, "needs a reason"),
])
def test_correction_refusals(db, nlx, kwargs, match):
    _, march = _committed_month(db, nlx, 3)
    with pytest.raises(BadRequestException, match=match):
        _correct(db, nlx, march, **kwargs)


def test_uncommitted_payslip_is_recalculated_not_corrected(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    with pytest.raises(BadRequestException, match="not committed"):
        _correct(db, nlx, _item(db, run, nlx.emp), {"base_salary": "4000"})


def test_a_delta_is_never_corrected_directly(db, nlx):
    _, march = _committed_month(db, nlx, 3)
    out = _correct(db, nlx, march, {"base_salary": "4000"})
    with pytest.raises(BadRequestException, match="not a correction delta"):
        _correct(db, nlx, db.query(PayslipItem).get(out["deltaPayslipId"]), {"base_salary": "1"})


def test_correction_runs_are_never_generated_or_recalculated(db, nlx):
    _, march = _committed_month(db, nlx, 3)
    out = _correct(db, nlx, march, {"base_salary": "4000"})
    run = db.query(PayrollRun).get(out["correctionRunId"])
    with pytest.raises(BadRequestException, match="never generated"):
        service.generate_payslips_for_run(db, run, nlx.org.id)
    with pytest.raises(BadRequestException, match="not recalculated"):
        service.regenerate_employee_payslip(db, run.id, nlx.emp.id, nlx.org.id, actor_id=PREPARER)


def test_stale_correction_blocks_approval(db, nlx):
    _, march = _committed_month(db, nlx, 3)
    out = _correct(db, nlx, march, {"base_salary": "4000"})          # computed on EI revision 1
    _committed_month(db, nlx, 4)                                      # series moves to revision 2
    run = db.query(PayrollRun).get(out["correctionRunId"])
    service.advance_payroll_run_status(db, run.id, PREPARER, nlx.org.id)
    with pytest.raises(Exception, match="vcr_stale"):
        service.advance_payroll_run_status(db, run.id, APPROVER, nlx.org.id)


# ── AWf revision (NL-016) ─────────────────────────────────────────────────

def _short_contract(db, nlx):
    db.query(PayrollNlContractVersion).update({"start_date": date(2026, 3, 1), "end_date": date(2026, 4, 20)})
    db.commit()


def test_short_indefinite_contract_revision_flow(db, nlx):
    _short_contract(db, nlx)
    _committed_month(db, nlx, 3)
    found = nl.detect_awf_revisions(db, nlx.org.id, 2026, actor_id=PREPARER)
    db.commit()
    assert [r.trigger_code for r in found] == ["SHORT_INDEFINITE_CONTRACT"]
    rev = found[0]
    assert rev.recomputed_delta["awf"] == "250.00"                  # 5000 x 7.74% - 137.00
    assert nl.detect_awf_revisions(db, nlx.org.id, 2026, actor_id=PREPARER) == []   # idempotent
    with pytest.raises(BadRequestException, match="REVIEWED"):
        nl.apply_awf_revision(db, rev.id, nlx.org.id, actor_id=APPROVER)
    with pytest.raises(BadRequestException, match="four-eyes"):
        nl.review_awf_revision(db, rev.id, nlx.org.id, actor_id=PREPARER)
    nl.review_awf_revision(db, rev.id, nlx.org.id, actor_id=APPROVER)
    result = nl.apply_awf_revision(db, rev.id, nlx.org.id, actor_id=APPROVER)
    db.commit()
    delta = db.query(PayslipItem).get(result["corrections"][0]["deltaPayslipId"])
    assert delta.nl_calculation_snapshot["totals"]["employerPremiums"] == "250.00"
    assert delta.nl_calculation_snapshot["totals"]["netPay"] == "0.00"          # employer liability only (NL-018)
    assert result["corrections"][0]["vcr"]["after"] == {}                        # the series does not move
    corr_run = _approve_run_id(db, nlx, result["correctionRunId"])
    assert corr_run.nl_approval_fingerprint["committedAt"]
    assert nl.nl_commit_run(db, corr_run)["alreadyCommitted"] is True
    assert db.query(PayrollNlAwfRevision).get(rev.id).status == "APPLIED"


def test_excess_hours_revision_detected(db, nlx):
    db.query(PayrollNlContractVersion).update({"agreed_hours_per_week": D("20")})
    db.commit()
    _committed_month(db, nlx, 3)                                      # paid 173.33 h vs agreed 86.67 h
    found = nl.detect_awf_revisions(db, nlx.org.id, 2026, actor_id=PREPARER)
    assert [r.trigger_code for r in found] == ["EXCESS_HOURS"]


def test_dismissal_needs_a_reason(db, nlx):
    _short_contract(db, nlx)
    _committed_month(db, nlx, 3)
    rev = nl.detect_awf_revisions(db, nlx.org.id, 2026, actor_id=PREPARER)[0]
    with pytest.raises(BadRequestException, match="reason"):
        nl.dismiss_awf_revision(db, rev.id, nlx.org.id, actor_id=APPROVER, note="")
    assert nl.dismiss_awf_revision(db, rev.id, nlx.org.id, APPROVER, "contract ended by mutual consent — S6 "
                                   "exception documented").status == "DISMISSED"


def test_back_pay_methods_are_explicit():
    assert set(nl.BACK_PAY_METHODS) == {"REPROCESS_ORIGINAL_PERIOD", "SPECIAL_REMUNERATION_CURRENT_PERIOD"}
