"""Switzerland (CH Step 16) — golden cases and final verification.

Every expected figure comes from tests/fixtures/ch_golden/calc_reference.py, an
independent standalone calculator (standard library only, no `app` import),
never from engine output. This file proves:

* each fixture still equals what the reference computes (no drift), and every
  reference scenario has a fixture;
* each golden case passes through the REAL engine via the shared harness, and
  the Super Admin certification run counts them;
* the spec §16 service-level scenarios (end-to-end payslip, corrected tariff,
  ELM rejection, certificate regeneration, 2027 rule isolation) match the
  reference on a real generated payroll;
* readiness reports every gate G1-G7 NOT passed — no evidence exists — while a
  gate can pass on reviewed evidence (so the gates are not hard-wired off).

Every tariff, scheme, canton figure and wage floor is SYNTHETIC.
"""
import ast
import hashlib
import importlib.util
import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.modules.payroll import service, switzerland_service as svc
from app.modules.payroll.hmrc_golden_harness import GoldenCaseMismatch, run_golden_case
from app.modules.payroll.models import (
    ChQstTariffRow, ContributionRate, JurisdictionPack, PayrollRun, SourceArtifact, TaxabilityRule,
)
from tests.test_switzerland_reporting import _approve, _generate, _lohnausweis_template, _make_user, _qst_view
from tests.test_switzerland_service_integration import (  # noqa: F401 (fixture)
    APPROVER, AUTHORIZER, PREPARER, _item, _run, ch,
)

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "ch_golden"
_spec = importlib.util.spec_from_file_location("ch_calc_reference", GOLDEN_DIR / "calc_reference.py")
ref = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ref)

CASE_FILES = sorted(GOLDEN_DIR.glob("*.json"))
SPEC_SCENARIOS = {"alv_cap_mid_year", "bvg_threshold_below", "bvg_threshold_crossed", "nbu_7_5_hours",
                  "nbu_9_hours", "qst_canton_zh_march", "qst_canton_be_april", "qst_corrected_tariff",
                  "geneva_floor_met", "geneva_floor_shortfall", "geneva_floor_out_of_scope",
                  "fak_canton_above_minimum"}


# ── the reference calculator is independent ──────────────────────────────

def test_reference_calculator_imports_nothing_from_the_app():
    tree = ast.parse((GOLDEN_DIR / "calc_reference.py").read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
              {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in modules if m and (m == "app" or m.startswith("app."))}, modules
    assert modules <= {"json", "sys", "datetime", "decimal", "pathlib"}, modules


def test_every_spec_scenario_has_a_fixture_and_no_fixture_drifted():
    assert {p.stem for p in CASE_FILES} == {s["name"] for s in ref.SCENARIOS} == SPEC_SCENARIOS
    for scenario in ref.SCENARIOS:
        on_disk = json.loads((GOLDEN_DIR / f"{scenario['name']}.json").read_text(encoding="utf-8"))
        assert on_disk == json.loads(json.dumps(ref.golden_case(scenario))), \
            f"{scenario['name']}.json drifted from calc_reference.py — re-run calc_reference.py --write"


def test_reference_figures_hand_check():
    # one case re-derived by hand, so the reference itself is checked:
    # 8000: AHV 348 + IV 56 + EO 20 + ALV 88 + BVG 5355*5% = 267.75 + NBU 72 + QST 640
    figures = ref.payslip(next(s for s in ref.SCENARIOS if s["name"] == "qst_canton_zh_march"))
    assert figures["ch_employee_total"] == D("1491.75") and figures["net_pay"] == D("6508.25")
    assert ref.coordinated_salary(D("180000")) == D("64260")          # BVG Art. 8 cap on the salary
    assert ref.coordinated_salary(D("30000")) == D("3780")            # Art. 8 para 2 minimum


# ── the engine reproduces every golden case ──────────────────────────────

@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_golden_case_through_the_production_engine(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    try:
        run_golden_case(case)
    except GoldenCaseMismatch as exc:
        pytest.fail(str(exc))


def test_a_wrong_expectation_is_reported_field_by_field():
    case = json.loads((GOLDEN_DIR / "nbu_9_hours.json").read_text(encoding="utf-8"))
    case["expected"]["ch_uvg_nbu_employee"] = "71.95"
    with pytest.raises(GoldenCaseMismatch) as exc:
        run_golden_case(case)
    assert [d["field"] for d in exc.value.diffs] == ["ch_uvg_nbu_employee"]


def test_super_admin_certification_runs_the_ch_cases(db):
    run = service.run_golden_test_certification(db, "CH", actor_id=None)
    assert (run.status, run.real_case_count, run.passed_cases, run.failed_cases) == ("PASS", 12, 12, 0)


# ── service-level scenarios against a real generated payroll ─────────────

FIXTURE_SCENARIO = next(s for s in ref.SCENARIOS if s["name"] == "qst_canton_zh_march")


def _reference(**over):
    return ref.payslip({**FIXTURE_SCENARIO, **over})


def test_end_to_end_payslip_matches_the_reference(db, ch):  # noqa: F811
    _run_, item = _approve(db, ch, 3)
    totals, expected = item.ch_calculation_snapshot["totalsAll"], _reference()
    for key in ("ch_ahv_employee", "ch_alv_employer", "ch_bvg_employee", "ch_bvg_employer", "ch_uvg_employee",
                "ch_qst_total", "ch_fak_employer", "ch_admin_cost_employer", "ch_employee_total",
                "ch_employer_total"):
        ref_key = {"ch_uvg_employee": "ch_uvg_nbu_employee"}.get(key, key)
        assert D(totals[key]) == expected[ref_key], key
    assert D(str(item.net_pay)) == expected["net_pay"]


def _tariff_b(db, ch):  # noqa: F811
    rows = ref.QST_TARIFFS["CH-ZH"]["B0N"]
    db.add_all([ChQstTariffRow(tariff_file_id=ch.tariff.id, tariff_code="B", children=0, church_tax=False,
                               income_from=lo, income_to=hi, rate_pct=rate, min_tax=mt)
                for lo, hi, rate, mt, _row in rows])
    db.commit()


def test_corrected_tariff_delta_matches_the_reference(db, ch):  # noqa: F811
    _run_, item = _approve(db, ch, 3)
    _tariff_b(db, ch)
    out = svc.create_ch_correction(db, ch.org.id, item.id, "TEST corrected tariff code", ["ch_qst"],
                                   {"ch_qst_tariff_code": "B"}, APPROVER,
                                   idempotency_key=hashlib.sha256(b"golden-corr").hexdigest())
    db.commit()
    before = _reference()
    after = _reference(qst={"canton": "CH-ZH", "table": "CH-ZH", "code": "B0N"})
    assert D(out["delta"]["ch_qst"]["employee"]) == after["ch_qst_total"] - before["ch_qst_total"]   # -160
    assert D(out["columnDelta"]["net_pay"]) == after["net_pay"] - before["net_pay"]
    assert out["changedObligations"] == ["ch_qst"]


def test_elm_rejection_leaves_the_payroll_at_its_reference_figures(db, ch):  # noqa: F811
    _run_, item = _approve(db, ch, 3)
    qst = _qst_view(svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3, actor_id=AUTHORIZER)["submissions"])
    db.commit()
    rejected = svc.transition_ch_elm_submission(db, ch.org.id, qst["submissionId"], "REJECT",
                                                reason="TEST receiver rejected the envelope", actor_id=AUTHORIZER)
    db.commit()
    assert rejected["authorityAckStatus"] == "REJECTED"
    db.refresh(item)
    assert D(str(item.net_pay)) == _reference()["net_pay"]
    assert D(item.ch_calculation_snapshot["totalsAll"]["ch_qst_total"]) == _reference()["ch_qst_total"]


def test_certificate_regeneration_absorbs_the_correction_at_reference_values(db, ch):  # noqa: F811
    creator, approver = _make_user(db, "gold.la@t.ch"), _make_user(db, "gold.la2@t.ch")
    template = _lohnausweis_template(db, creator, approver)
    _march_run, march = _approve(db, ch, 3)
    _approve(db, ch, 4)
    first = _generate(db, ch, template.id, creator.id)
    db.commit()
    qst_box = lambda cert: D({b["boxCode"]: b for b in cert["boxes"]}["BOX_QST_WITHHELD"]["valueExact"])  # noqa: E731
    march_ref, april_ref = _reference(), _reference(pay_date="2026-04-30")
    assert qst_box(first) == march_ref["ch_qst_total"] + april_ref["ch_qst_total"]                     # 1280
    _tariff_b(db, ch)
    out = svc.create_ch_correction(db, ch.org.id, march.id, "TEST corrected tariff code", ["ch_qst"],
                                   {"ch_qst_tariff_code": "B"}, APPROVER,
                                   idempotency_key=hashlib.sha256(b"golden-la").hexdigest())
    db.commit()
    corr_run = db.get(PayrollRun, out["correctionRunId"])
    service.advance_payroll_run_status(db, corr_run.id, PREPARER, ch.org.id)
    service.advance_payroll_run_status(db, corr_run.id, AUTHORIZER, ch.org.id)
    db.commit()
    second = _generate(db, ch, template.id, creator.id)
    db.commit()
    march_corrected = _reference(qst={"canton": "CH-ZH", "table": "CH-ZH", "code": "B0N"})
    assert qst_box(second) == march_corrected["ch_qst_total"] + april_ref["ch_qst_total"]             # 1120
    assert second["supersedesReportIds"] == [first["reportId"]]


def test_a_2027_pack_never_affects_a_2026_calculation(db, ch):  # noqa: F811
    later = JurisdictionPack(pack_id="CH-FEDERAL-2027-SYNTHETIC", jurisdiction_country="CH", version="1.0",
                             pack_type="tax", status="Active", effective_from=date(2027, 1, 1),
                             effective_to=date(2027, 12, 31))
    db.add(later)
    db.flush()
    for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == ch.federal.id).all():
        db.add(ContributionRate(jurisdiction_pack_id=later.id, jurisdiction_country="CH", component_key=r.component_key,
                                label=r.label, employee_share="-", employer_share="-", total="-",
                                employee_rate_pct=D("9.99") if r.component_key == "ch_ahv" else r.employee_rate_pct,
                                employer_rate_pct=r.employer_rate_pct, flat_amount=r.flat_amount))
    db.commit()
    _run_, item = _approve(db, ch, 3)
    assert D(item.ch_calculation_snapshot["totalsAll"]["ch_ahv_employee"]) == _reference()["ch_ahv_employee"]
    assert item.ch_calculation_snapshot["trace"]["resolved_versions"]["federal_pack_id"] == ch.federal.id
    # replaying the frozen 2026 context with the 2027 pack Active changes nothing
    replay = svc.ch_replay(item.ch_calculation_snapshot["frozenContext"]).ch_result["ch_calculation_trace"]
    assert replay["rule_hash"] == item.ch_calculation_snapshot["trace"]["rule_hash"]
    # while a 2027 date does resolve the 2027 pack
    assert svc._active_pack(db, None, date(2027, 3, 31)).id == later.id


# ── readiness: every gate G1-G7 NOT passed ───────────────────────────────

def test_readiness_reports_every_gate_not_passed(db, ch):  # noqa: F811
    # do everything the PLATFORM itself can do: certify the golden cases and
    # classify every obligation — none of it is gate evidence
    service.run_golden_test_certification(db, "CH", actor_id=None)
    for component in ("ch_ktg",):
        db.add(TaxabilityRule(jurisdiction_country="CH", earning_type="base_salary", tax_component=component,
                              is_taxable=True, status="Approved", effective_from=date(2026, 1, 1)))
    db.commit()
    out = svc.get_ch_readiness(db, date(2026, 3, 31))
    assert out["ready"] is False and len(out["blockers"]) == 7
    assert [(g["key"], g["complete"], g["state"]) for g in out["gates"]] == [
        (f"G{i}", False, "EVIDENCE_REQUIRED") for i in range(1, 8)]
    g5 = {c["key"]: c for c in next(g for g in out["gates"] if g["key"] == "G5")["checks"]}
    assert g5["golden_certification"]["passed"] is True        # a PASS run is supporting info only
    labels = " ".join(g["label"] for g in out["gates"])
    for words in ("specialist", "ESTV", "scheme evidence", "Swissdec", "Parallel", "encryption", "Operations"):
        assert words in labels


def _evidence(db, gate, uploader=101, reviewer=202, file_path="evidence.pdf"):
    a = SourceArtifact(agency="Zoiko test", title=f"TEST {gate} evidence", form_number=f"CH-GATE-{gate}",
                       checksum_sha256="0" * 64, file_path=file_path, created_by_id=uploader, reviewer_id=reviewer)
    db.add(a)
    db.commit()
    return a


def test_a_gate_passes_only_on_evidence_reviewed_by_a_second_super_admin(db):
    _evidence(db, "G3", uploader=101, reviewer=101)                       # self-reviewed: not enough
    assert svc.ch_gate_state(db, "G3") == "SUBMITTED"
    _evidence(db, "G3", uploader=101, reviewer=202)
    gates = {g["key"]: g for g in svc.get_ch_readiness(db, date(2026, 3, 31))["gates"]}
    assert gates["G3"]["complete"] is True and gates["G3"]["state"] == "PASS"
    # G2 evidence alone does not pass G2: the ESTV layout and the cantons are still unverified
    _evidence(db, "G2")
    gates = {g["key"]: g for g in svc.get_ch_readiness(db, date(2026, 3, 31))["gates"]}
    assert gates["G2"]["state"] == "PASS" and gates["G2"]["complete"] is False
