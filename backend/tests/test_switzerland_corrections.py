"""Switzerland (CH Step 13) — append-only payslip corrections.

A correction replays the payslip's FROZEN calculation context (no pack,
tariff or scheme resolved today), books the per-obligation delta as a new
payslip in a correction run, posts additive YTD deltas and links ELM
correction envelopes. The original payslip is never modified. A QST tariff
correction only LISTS the months it affects — nothing is recalculated.

Built on the Step 12 integration fixture. Every value is SYNTHETIC.
"""
import uuid
from datetime import date
from decimal import Decimal as D

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service, switzerland_service as svc
from app.modules.payroll.models import (
    ChElmSubmission, ChQstTariffFile, ChQstTariffRow, ContributionRate, JurisdictionPack, PayrollRun,
    PayrollYtdAccumulator, PayslipItem,
)
from tests.test_hong_kong_governance import _http
from tests.test_switzerland_service_integration import (  # noqa: F401 (fixture)
    APPROVER, AUTHORIZER, PREPARER, _item, _run, _ytd, ch,
)

ALL_OBLIGATIONS = sorted(svc.CH_CORRECTION_OBLIGATIONS)


def _finalized(db, ch, month=3):  # noqa: F811
    run = _run(db, ch.org, month)
    service.generate_payslips_for_run(db, run, ch.org.id)
    service.advance_payroll_run_status(db, run.id, PREPARER, ch.org.id)     # Review
    service.advance_payroll_run_status(db, run.id, APPROVER, ch.org.id)     # Approved
    return run, _item(db, run, ch.emp)


def _tariff_b(db, ch):  # noqa: F811
    """Tariff code B in the same (synthetic) file: 6 % from 5000."""
    db.add_all([ChQstTariffRow(tariff_file_id=ch.tariff.id, tariff_code="B", children=0, church_tax=False,
                               income_from=D("0"), income_to=D("5000"), rate_pct=D("1")),
                ChQstTariffRow(tariff_file_id=ch.tariff.id, tariff_code="B", children=0, church_tax=False,
                               income_from=D("5000"), income_to=None, rate_pct=D("6"))])
    db.commit()


def _correct(db, ch, item, corrected, obligations=("ch_qst",), reason="TEST tariff code was wrong"):  # noqa: F811
    out = svc.create_ch_correction(db, ch.org.id, item.id, reason, list(obligations), corrected, APPROVER,
                                   idempotency_key=uuid.uuid4().hex, correlation_id="corr-test")
    db.commit()
    return out


def _frozen_columns(item):
    return {c: getattr(item, c) for c in ("gross_pay", "total_deductions", "net_pay", "status", "payroll_run_id")}


# ── replay ───────────────────────────────────────────────────────────────

def test_replaying_the_frozen_context_reproduces_hashes_and_amounts(db, ch):  # noqa: F811
    _run_, item = _finalized(db, ch)
    snap = item.ch_calculation_snapshot
    assert snap["frozenContext"]["version"] == 1 and snap["frozenContext"]["rateMap"]["ch_ahv"]
    for _ in range(2):
        replay = svc.ch_replay(snap["frozenContext"])
        trace = replay.ch_result["ch_calculation_trace"]
        assert (trace["input_hash"], trace["rule_hash"]) == (snap["trace"]["input_hash"], snap["trace"]["rule_hash"])
        assert svc._ch_totals_all(replay.ch_result) == snap["totalsAll"]
        assert replay.net_pay == item.net_pay


def test_a_later_pack_never_affects_a_2026_correction(db, ch):  # noqa: F811
    _run_, item = _finalized(db, ch)
    _tariff_b(db, ch)
    # the 2026 federal pack is superseded and a "2027" pack (higher AHV) is
    # Active and — wrongly — dated to cover 2026 too
    ch.federal.status = "Superseded"
    later = JurisdictionPack(pack_id="CH-FEDERAL-2027-TEST", jurisdiction_country="CH", version="1.0",
                             pack_type="tax", status="Active", effective_from=date(2026, 1, 1),
                             effective_to=date(2027, 12, 31))
    db.add(later)
    db.flush()
    for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == ch.federal.id).all():
        db.add(ContributionRate(jurisdiction_pack_id=later.id, jurisdiction_country="CH", component_key=r.component_key,
                                label=r.label, employee_share="-", employer_share="-", total="-",
                                employee_rate_pct=D("5.0") if r.component_key == "ch_ahv" else r.employee_rate_pct,
                                employer_rate_pct=r.employer_rate_pct, flat_amount=r.flat_amount))
    db.commit()
    # the live path really would use it — so the test is not vacuous
    live = service.preview_payroll_run(db, ch.org.id, [ch.emp.id], "CH", date(2026, 3, 1), date(2026, 3, 31))
    row = (live.get("employees") or live.get("results"))[0]
    assert row["switzerland"]["trace"]["resolved_versions"]["federal_pack_id"] == later.id
    out = _correct(db, ch, item, {"ch_qst_tariff_code": "B"})
    assert out["changedObligations"] == ["ch_qst"]                          # AHV untouched by the 2027 rate
    delta = db.get(PayslipItem, out["deltaPayslipId"]).ch_calculation_snapshot
    assert delta["trace"]["resolved_versions"]["federal_pack_id"] == ch.federal.id
    assert delta["frozenContext"]["rateMap"]["ch_ahv"]["employee_rate_pct"] == \
        item.ch_calculation_snapshot["frozenContext"]["rateMap"]["ch_ahv"]["employee_rate_pct"]
    assert out["newRuleHash"] == out["originalRuleHash"]                    # same rules, restated input only


# ── the correction itself ────────────────────────────────────────────────

def test_qst_tariff_code_correction_delta_and_ytd(db, ch):  # noqa: F811
    run, item = _finalized(db, ch)
    _tariff_b(db, ch)
    before_cols, before_snap = _frozen_columns(item), item.ch_calculation_snapshot
    qst_before = _ytd(db, ch.emp, "ch_qst")
    out = _correct(db, ch, item, {"ch_qst_tariff_code": "B"})
    # 8000 x 8 % = 640 -> 8000 x 6 % = 480
    assert D(out["delta"]["ch_qst"]["employee"]) == D("-160") and D(out["delta"]["ch_qst"]["employer"]) == 0
    assert D(out["columnDelta"]["net_pay"]) == D("160") and D(out["columnDelta"]["total_deductions"]) == D("-160")
    assert D(out["columnDelta"]["gross_pay"]) == D("0")
    assert _ytd(db, ch.emp, "ch_qst") == (qst_before[0], qst_before[1] - D("160"))     # additive delta
    delta_item = db.get(PayslipItem, out["deltaPayslipId"])
    corr = delta_item.ch_calculation_snapshot["correction"]
    assert {k: corr[k] for k in ("originalPayslipId", "originalRunId", "obligations")} == {
        "originalPayslipId": item.id, "originalRunId": run.id, "obligations": ["ch_qst"]}
    assert corr["originalRuleHash"] == before_snap["trace"]["rule_hash"] and corr["newRuleHash"]
    assert corr["reason"] == "TEST tariff code was wrong"
    assert delta_item.ch_calculation_snapshot["trace"]["qst"]["tariff_code"] == "B"
    corr_run = db.get(PayrollRun, out["correctionRunId"])
    assert corr_run.notes.startswith(svc.CH_CORRECTION_MARKER) and svc.is_ch_correction_run(corr_run)
    assert (delta_item.ytd_snapshot or {})                                   # postings recorded (reversible)
    # the original is never modified
    db.refresh(item)
    assert _frozen_columns(item) == before_cols and item.ch_calculation_snapshot == before_snap


def test_earnings_correction_must_declare_every_obligation_it_changes(db, ch):  # noqa: F811
    _run_, item = _finalized(db, ch)
    with pytest.raises(BadRequestException) as exc:
        _correct(db, ch, item, {"earnings": {"base_salary": "9000"}}, obligations=("ch_qst",))
    assert "ch_ahv" in exc.value.detail and "declare" in exc.value.detail
    out = _correct(db, ch, item, {"earnings": {"base_salary": "9000"}}, obligations=ALL_OBLIGATIONS,
                   reason="TEST March salary was 9000")
    assert D(out["delta"]["ch_ahv"]["employee"]) == D("43.50")               # 1000 x 4.35 %
    assert D(out["columnDelta"]["gross_pay"]) == D("1000")
    assert D(out["ytdDelta"]["ch_ahv"]["wages"]) == D("1000")


def test_a_second_correction_builds_on_the_first(db, ch):  # noqa: F811
    _run_, item = _finalized(db, ch)
    _tariff_b(db, ch)
    first = _correct(db, ch, item, {"ch_qst_tariff_code": "B"})
    second = _correct(db, ch, item, {"ch_qst_tariff_code": "A"}, reason="TEST reverted after review")
    assert second["sequence"] == 2 and D(second["delta"]["ch_qst"]["employee"]) == D("160")
    assert D(first["delta"]["ch_qst"]["employee"]) + D(second["delta"]["ch_qst"]["employee"]) == D("0")
    assert [c["sequence"] for c in svc.list_ch_corrections(db, ch.org.id, item.id)] == [1, 2]
    with pytest.raises(BadRequestException, match="no change"):
        _correct(db, ch, item, {"ch_qst_tariff_code": "A"})


@pytest.mark.parametrize("case, expected", [
    ("unknown_input", "not correctable"),
    ("unknown_obligation", "affectedObligations"),
    ("no_reason", "reason"),
])
def test_correction_input_refusals(db, ch, case, expected):  # noqa: F811
    _run_, item = _finalized(db, ch)
    kwargs = {"unknown_input": dict(corrected={"ch_ahv_rate": "9"}),
              "unknown_obligation": dict(corrected={"ch_qst_tariff_code": "B"}, obligations=("ch_payroll_tax",)),
              "no_reason": dict(corrected={"ch_qst_tariff_code": "B"}, reason=" ")}[case]
    with pytest.raises(BadRequestException, match=expected):
        _correct(db, ch, item, **kwargs)


def test_only_finalized_originals_can_be_corrected(db, ch):  # noqa: F811
    draft = _run(db, ch.org, 3)
    service.generate_payslips_for_run(db, draft, ch.org.id)
    with pytest.raises(BadRequestException, match="not finalized"):
        _correct(db, ch, _item(db, draft, ch.emp), {"ch_qst_tariff_code": "B"})


def test_a_correction_delta_is_never_corrected_or_recalculated(db, ch):  # noqa: F811
    _run_, item = _finalized(db, ch)
    _tariff_b(db, ch)
    out = _correct(db, ch, item, {"ch_qst_tariff_code": "B"})
    delta_item = db.get(PayslipItem, out["deltaPayslipId"])
    with pytest.raises(BadRequestException, match="not a correction delta"):
        _correct(db, ch, delta_item, {"ch_qst_tariff_code": "A"})
    with pytest.raises(BadRequestException, match="Swiss correction delta"):
        service.regenerate_employee_payslip(db, out["correctionRunId"], ch.emp.id, ch.org.id)


def test_a_drifted_frozen_context_is_refused(db, ch):  # noqa: F811
    _run_, item = _finalized(db, ch)
    snap = dict(item.ch_calculation_snapshot)
    snap["trace"] = {**snap["trace"], "rule_hash": "0" * 64}
    item.ch_calculation_snapshot = snap
    db.commit()
    with pytest.raises(BadRequestException, match="drifted"):
        _correct(db, ch, item, {"ch_qst_tariff_code": "B"})


def test_later_payslips_are_listed_not_recalculated(db, ch):  # noqa: F811
    _run_, march = _finalized(db, ch, 3)
    _april_run, april = _finalized(db, ch, 4)
    _tariff_b(db, ch)
    april_before = (_frozen_columns(april), april.ch_calculation_snapshot)
    out = _correct(db, ch, march, {"ch_qst_tariff_code": "B"})
    assert out["laterPayslipsNotRecalculated"] == [april.id]
    db.refresh(april)
    assert (_frozen_columns(april), april.ch_calculation_snapshot) == april_before


def test_elm_submissions_of_the_changed_domains_get_a_correction_envelope(db, ch):  # noqa: F811
    _run_, item = _finalized(db, ch)
    _tariff_b(db, ch)
    qst = ChElmSubmission(organization_id=ch.org.id, domain="QST", canton="CH-ZH", period_key="2026-03",
                          transport_status="ACKNOWLEDGED", idempotency_key="elm-qst-2026-03")
    ahv = ChElmSubmission(organization_id=ch.org.id, domain="AHV", period_key="2026-03",
                          transport_status="ACKNOWLEDGED", idempotency_key="elm-ahv-2026-03")
    db.add_all([qst, ahv])
    db.commit()
    out = _correct(db, ch, item, {"ch_qst_tariff_code": "B"})
    assert [(e["domain"], e["correctionOfId"]) for e in out["elmCorrections"]] == [("QST", qst.id)]
    link = db.get(ChElmSubmission, out["elmCorrections"][0]["submissionId"])
    assert link.correction_of_id == qst.id and link.transport_status == "NOT_SENT"
    assert link.correlation_id == "corr-test"


# ── QST tariff correction: affected months listed, nothing recalculated ──

def test_tariff_correction_lists_affected_months_without_recalculating(db, ch):  # noqa: F811
    _r3, march = _finalized(db, ch, 3)
    _r4, april = _finalized(db, ch, 4)
    before = {p.id: (_frozen_columns(p), p.ch_calculation_snapshot) for p in (march, april)}
    corrected = ChQstTariffFile(canton="CH-ZH", file_sha256="c" * 64, status="APPROVED", row_count=1,
                                format_version="ESTV_FIXED_WIDTH_V1", approved_by_id=APPROVER,
                                effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    db.add(corrected)
    db.flush()
    db.add(ChQstTariffRow(tariff_file_id=corrected.id, tariff_code="A", children=0, church_tax=False,
                          income_from=D("0"), income_to=None, rate_pct=D("7")))
    db.commit()
    view = svc.activate_qst_tariff_file(db, corrected.id, AUTHORIZER, reason="TEST corrected ESTV file")
    assert view["supersededImpact"] == [{"tariffFileId": ch.tariff.id, "months": ["2026-03", "2026-04"],
                                         "payslipCount": 2, "autoRecalculated": False}]
    for p in (march, april):
        db.refresh(p)
        assert (_frozen_columns(p), p.ch_calculation_snapshot) == before[p.id]          # untouched
    impact = svc.qst_tariff_affected_payslips(db, ch.tariff.id)
    assert impact["status"] == "SUPERSEDED" and [a["payslipId"] for a in impact["affected"]] == [march.id, april.id]
    # a superseded file still replays the original exactly
    trace = svc.ch_replay(march.ch_calculation_snapshot["frozenContext"]).ch_result["ch_calculation_trace"]
    assert trace["rule_hash"] == march.ch_calculation_snapshot["trace"]["rule_hash"]


# ── API ──────────────────────────────────────────────────────────────────

def test_correction_route_is_idempotent_and_audited(db, ch):  # noqa: F811
    from types import SimpleNamespace

    from app.modules.payroll.models import TaxConfigurationAudit

    _run_, item = _finalized(db, ch)
    _tariff_b(db, ch)
    admin = SimpleNamespace(id=APPROVER, organization_id=ch.org.id, role="org_admin", is_active=True)
    body = {"originalPayslipId": item.id, "reason": "TEST wrong tariff code", "affectedObligations": ["ch_qst"],
            "correctedInputs": {"ch_qst_tariff_code": "B"}}
    with _http(db, admin) as c:
        first = c.post("/api/payroll/switzerland/corrections", json=body, headers={"Idempotency-Key": "corr-1"})
        again = c.post("/api/payroll/switzerland/corrections", json=body, headers={"Idempotency-Key": "corr-1"})
        assert c.post("/api/payroll/switzerland/corrections", json=body).status_code == 400   # no key
        chain = c.get(f"/api/payroll/switzerland/payslips/{item.id}/corrections").json()
    assert first.status_code == 200, first.text
    assert again.headers["Idempotent-Replayed"] == "true" and again.json() == first.json()
    assert len(chain) == 1 and db.query(PayrollRun).filter(PayrollRun.notes.like("[CH-CORRECTION]%")).count() == 1
    audit = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "ch_payslip_correction").one()
    assert audit.entity_id == first.json()["deltaPayslipId"] and audit.reason == "TEST wrong tariff code"
    assert db.query(PayrollYtdAccumulator).count() > 0
