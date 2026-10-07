"""Switzerland (CH Step 12) end to end through the real payroll service.

The engine / resolver tests prove the arithmetic and the fail-closed facts;
these prove the WIRING: the federal canonical pack feeding the CH rate map,
resolve_ch_calc_inputs + the QST tariff lookup feeding switzerland.py, the
payslip snapshot, YTD posted exactly once (and re-posted, never added, on a
regenerate), the approval preflight + fingerprint at run transitions, the
locks on approved runs, and the Super Admin readiness / preview routes.

In-memory SQLite only (the `db` fixture). Every rate, tariff and scheme value
is SYNTHETIC (the federal rows come from the Draft content catalog).
"""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.payroll import service, switzerland_service
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.engine.countries.switzerland_content import CH_FEDERAL_SEED_2026
from app.modules.payroll.models import (
    ChEntityProfile, ChQstTariffFile, ChQstTariffRow, ChSchemeProfile, CompanyComplianceDetails, ContributionRate,
    EmployeeStatutoryProfile, JurisdictionPack, PayrollEmployee, PayrollRun, PayrollYtdAccumulator, PayslipItem,
    TaxabilityRule, TaxConfigurationAudit,
)
from tests.test_hong_kong_governance import SA_A, _http

PREPARER, APPROVER, AUTHORIZER = 701, 702, 703
COMPONENTS = ("ch_ahv", "ch_iv", "ch_eo", "ch_alv", "ch_uvg", "ch_bvg", "ch_qst")


def _stub_codes(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _pack(db, pack_id, canton=None, rows=()):
    pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country="CH", jurisdiction_state=canton, version="1.0",
                            pack_type="tax", status="Active", effective_from=date(2026, 1, 1),
                            effective_to=date(2026, 12, 31))
    db.add(pack)
    db.flush()
    for key, ee, er, amount, text in rows:
        db.add(ContributionRate(jurisdiction_pack_id=pack.id, jurisdiction_country="CH", jurisdiction_state=canton,
                                organization_id=None, component_key=key, label=f"TEST {key}", employee_share="-",
                                employer_share="-", total="-", employee_rate_pct=ee, employer_rate_pct=er,
                                flat_amount=amount, text_value=text))
    db.flush()
    return pack


def _scheme(db, org_id, scheme_type, code, rules, version="1.0"):
    s = ChSchemeProfile(organization_id=org_id, scheme_type=scheme_type, scheme_code=code, name=f"TEST {code}",
                        rules=rules, version=version, status="LIVE", effective_from=date(2026, 1, 1))
    db.add(s)
    db.flush()
    return s


@pytest.fixture()
def ch(db, organization, monkeypatch):
    """A fully configured Swiss employer + one QST-liable, BVG-insured worker
    in Zurich, resolvable for March / April 2026."""
    _stub_codes(monkeypatch)
    org = organization
    federal_rows = [(key, D(ee) if ee else None, D(er) if er else None, D(flat) if flat else None, None)
                    for key, _l, ee, er, flat, _s, _g in CH_FEDERAL_SEED_2026]
    federal = _pack(db, "CH-FEDERAL-TEST", rows=federal_rows)
    tariff = ChQstTariffFile(canton="CH-ZH", file_sha256="b" * 64, status="ACTIVE", row_count=2,
                             format_version="ESTV_FIXED_WIDTH_V1",
                             effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    db.add(tariff)
    db.flush()
    db.add_all([ChQstTariffRow(tariff_file_id=tariff.id, tariff_code="A", children=0, church_tax=False,
                               income_from=D("0"), income_to=D("5000"), rate_pct=D("2"), min_tax=None),
                ChQstTariffRow(tariff_file_id=tariff.id, tariff_code="A", children=0, church_tax=False,
                               income_from=D("5000"), income_to=None, rate_pct=D("8"), min_tax=None)])
    zh = _pack(db, "CH-ZH-TEST", "CH-ZH", rows=[("ch_qst_model", None, None, None, "MONTHLY"),
                                               ("ch_qst_tariff_file_id", None, None, None, str(tariff.id))])
    comp = _scheme(db, None, "COMPENSATION_OFFICE", "SVA-TEST", {"admin_cost_pct": "1.0"})
    fak = _scheme(db, org.id, "FAK", "FAK-TEST", {"employer_pct": "1.2"})
    bvg = _scheme(db, org.id, "BVG_PLAN", "BVG-TEST", {
        "entry_rules": {}, "insured_salary_def": "AHV salary less coordination deduction",
        "coordination": {"mode": "STATUTORY"},
        "bands": [{"age_from": 18, "age_to": 65, "employee_pct": "5", "employer_pct": "5", "component": "MANDATORY"}]})
    uvg = _scheme(db, org.id, "UVG_POLICY", "UVG-TEST", {"insurer": "TEST", "risk_classes": [
        {"code": "A1", "bu_employer_pct": "0.3", "nbu_pct": "0.9", "nbu_employee_share_pct": "100"}]})
    db.add(ChEntityProfile(organization_id=org.id, uid="CHE-123.456.789", seat_canton="CH-ZH",
                           canton_registrations=[{"canton": "CH-ZH"}], compensation_office_scheme_id=comp.id,
                           fak_scheme_id=fak.id, effective_from=date(2026, 1, 1)))
    for component in COMPONENTS:
        db.add(TaxabilityRule(jurisdiction_country="CH", earning_type="base_salary", tax_component=component,
                              is_taxable=True, status="Approved", effective_from=date(2026, 1, 1),
                              treatment="PERIODIC" if component == "ch_qst" else None))
    db.add(CompanyComplianceDetails(organization_id=org.id, jurisdiction_country="Switzerland",
                                    active_pack_id=federal.id))
    emp = PayrollEmployee(organization_id=org.id, employee_code="CH-001", name="Test Worker", country_code="CH",
                          ctc=D("96000"), basic=D("96000"), hra=D("0"), date_of_birth=date(1990, 5, 1),
                          date_of_joining=date(2025, 1, 1), pay_frequency="Monthly")
    db.add(emp)
    db.flush()
    db.add(EmployeeStatutoryProfile(
        employee_id=emp.id, organization_id=org.id, country_code="CH", effective_from=date(2026, 1, 1),
        ch_work_canton="CH-ZH", ch_residence_canton="CH-ZH", ch_residence_country="CH", ch_qst_canton="CH-ZH",
        ch_qst_subject="YES", ch_qst_tariff_code="A", ch_children_count=0, ch_church_tax=False,
        ch_bvg_plan_scheme_id=bvg.id, ch_uvg_policy_scheme_id=uvg.id, ch_uvg_risk_class="A1",
        ch_weekly_hours=D("42")))
    db.commit()
    return SimpleNamespace(org=org, emp=emp, federal=federal, zh=zh, tariff=tariff, comp=comp, fak=fak, bvg=bvg,
                           uvg=uvg)


def _run(db, org, month, created_by=PREPARER):
    end = date(2026, month, 30 if month in (4, 6, 9, 11) else 31)
    run = PayrollRun(organization_id=org.id, period_label=f"2026-{month:02d}", period_start=date(2026, month, 1),
                     period_end=end, pay_date=end, created_by=created_by,
                     attendance_override_reason="TEST synthetic run - no attendance records")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _item(db, run, emp):
    return db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one()


def _ytd(db, emp, component, year=2026):
    row = (db.query(PayrollYtdAccumulator)
           .filter(PayrollYtdAccumulator.employee_id == emp.id, PayrollYtdAccumulator.tax_year == f"CH-CY-{year}",
                   PayrollYtdAccumulator.tax_component == component).one_or_none())
    return None if row is None else (D(str(row.ytd_taxable_wages)), D(str(row.ytd_tax_withheld)))


# ── generation, snapshot, YTD ────────────────────────────────────────────

def test_run_generation_writes_the_snapshot_and_a_consistent_net_pay(db, ch):
    run = _run(db, ch.org, 3)
    service.generate_payslips_for_run(db, run, ch.org.id)
    item = _item(db, run, ch.emp)
    snap = item.ch_calculation_snapshot
    assert item.country_code == "CH" and snap is not None
    assert D(str(item.gross_pay)) == D("8000.00")
    totals = snap["totals"]
    assert D(str(item.net_pay)) == D("8000.00") - D(totals["ch_employee_total"])
    obligations = {ln["obligation"] for ln in snap["trace"]["lines"]}
    assert {"ch_ahv", "ch_alv", "ch_bvg_mandatory", "ch_uvg_bu", "ch_qst_periodic", "ch_fak", "ch_admin"} <= obligations
    qst = snap["trace"]["qst"]
    assert qst["tariff_file_id"] == ch.tariff.id and qst["file_sha256"] == "b" * 64 and D(qst["rate_pct"]) == D("8")
    assert D(totals["ch_qst_total"]) == D("640.00")                  # 8000 x 8 % (band from 5000)
    assert snap["trace"]["resolved_versions"]["federal_pack_id"] == ch.federal.id


def test_ytd_is_posted_once_and_the_next_month_reads_it(db, ch):
    march = _run(db, ch.org, 3)
    service.generate_payslips_for_run(db, march, ch.org.id)
    first = _ytd(db, ch.emp, "ch_ahv")
    assert first[0] == D("8000.00")
    assert _ytd(db, ch.emp, "ch_qst") == (D("8000.00"), D("640.00"))
    april = _run(db, ch.org, 4)
    service.generate_payslips_for_run(db, april, ch.org.id)
    assert _ytd(db, ch.emp, "ch_ahv")[0] == D("16000.00")
    before = _item(db, april, ch.emp).ch_calculation_snapshot["trace"]["accumulators_before"]["ch_ahv"]
    assert D(before["wages"]) == first[0]                            # April consumed exactly what March posted


def test_regenerate_is_idempotent(db, ch):
    run = _run(db, ch.org, 3)
    service.generate_payslips_for_run(db, run, ch.org.id)
    snap1, ytd1 = _item(db, run, ch.emp).ch_calculation_snapshot, _ytd(db, ch.emp, "ch_ahv")
    assert ytd1 == (D("8000.00"), D(snap1["trace"]["accumulators_after"]["ch_ahv"]["withheld"]))
    for _ in range(2):
        service.regenerate_employee_payslip(db, run.id, ch.emp.id, ch.org.id, actor_id=PREPARER)
    item = _item(db, run, ch.emp)
    assert _ytd(db, ch.emp, "ch_ahv") == ytd1                        # re-posted, never added twice
    assert item.ch_calculation_snapshot["totals"] == snap1["totals"]
    assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).count() == 1


def test_a_blocked_worker_surfaces_like_italy(db, ch):
    db.query(TaxabilityRule).filter(TaxabilityRule.tax_component == "ch_ahv").update({"status": "Draft"})
    db.commit()
    run = _run(db, ch.org, 3)
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        service.generate_payslips_for_run(db, run, ch.org.id)
    assert exc.value.key == "ch_taxability:ch_ahv"


def test_canton_work_state_never_replaces_the_federal_rate_map(db, ch):
    ch.emp.work_state = "CH-ZH"                                       # legacy field, never used for CH
    db.commit()
    run = _run(db, ch.org, 3)
    service.generate_payslips_for_run(db, run, ch.org.id)
    assert _item(db, run, ch.emp).ch_calculation_snapshot["totals"]["ch_employee_total"] is not None


def test_preview_payroll_run_carries_the_swiss_snapshot(db, ch):
    out = service.preview_payroll_run(db, ch.org.id, [ch.emp.id], "CH", date(2026, 3, 1), date(2026, 3, 31))
    row = out["employees"][0] if "employees" in out else out["results"][0]
    assert D(row["switzerland"]["totals"]["ch_qst_total"]) == D("640")
    assert db.query(PayrollYtdAccumulator).count() == 0               # a preview writes nothing


# ── approval: preflight, four-eyes, fingerprint ──────────────────────────

def _to_review(db, ch, month=3):
    run = _run(db, ch.org, month)
    service.generate_payslips_for_run(db, run, ch.org.id)
    service.advance_payroll_run_status(db, run.id, PREPARER, ch.org.id)          # Draft -> Review
    return run


def test_preparer_cannot_approve_and_preflight_reruns_every_check(db, ch):
    run = _to_review(db, ch)
    with pytest.raises(HTTPException) as exc:
        service.advance_payroll_run_status(db, run.id, PREPARER, ch.org.id)
    assert exc.value.status_code == 409 and "preparer" in exc.value.detail
    ch.uvg.status = "RETIRED"                                            # a fact breaks after generation
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.advance_payroll_run_status(db, run.id, APPROVER, ch.org.id)
    assert "ch_uvg_policy" in exc.value.detail
    db.refresh(run)
    assert run.status == "Review"


def test_approval_stores_the_fingerprint_and_an_unchanged_run_authorizes(db, ch):
    run = _to_review(db, ch)
    service.advance_payroll_run_status(db, run.id, APPROVER, ch.org.id)
    stored = switzerland_service.ch_stored_approval(db, run)
    assert set(stored["components"]) == {"inputs", "ruleHashes", "schemeVersions", "payslips"}
    service.advance_payroll_run_status(db, run.id, AUTHORIZER, ch.org.id)
    db.refresh(run)
    assert run.status == "Authorized"


def test_fingerprint_mismatch_blocks_authorize_and_returns_the_run_to_review(db, ch):
    run = _to_review(db, ch)
    service.advance_payroll_run_status(db, run.id, APPROVER, ch.org.id)
    item = _item(db, run, ch.emp)
    item.net_pay = D(str(item.net_pay)) + D("100")                        # tampered after approval
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.advance_payroll_run_status(db, run.id, AUTHORIZER, ch.org.id)
    assert exc.value.status_code == 409 and "payslips" in exc.value.detail
    db.refresh(run)
    assert run.status == "Review" and run.approved_by is None
    audit = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "ch_run_approval")
             .order_by(TaxConfigurationAudit.id.desc()).first())
    assert audit.action == "status_change" and audit.new_value["changed"] == ["payslips"]


def test_a_scheme_change_after_approval_also_invalidates_it(db, ch):
    run = _to_review(db, ch)
    service.advance_payroll_run_status(db, run.id, APPROVER, ch.org.id)
    ch.bvg.status = "RETIRED"
    db.commit()
    v2 = _scheme(db, ch.org.id, "BVG_PLAN", "BVG-TEST", ch.bvg.rules, version="2.0")
    db.query(EmployeeStatutoryProfile).update({"ch_bvg_plan_scheme_id": v2.id})
    db.commit()
    with pytest.raises(HTTPException) as exc:
        service.advance_payroll_run_status(db, run.id, AUTHORIZER, ch.org.id)
    assert "schemeVersions" in exc.value.detail


def test_approved_ch_runs_refuse_add_and_recalculate(db, ch):
    from app.modules.payroll.schemas import PayslipItemCreate

    run = _to_review(db, ch)
    service.advance_payroll_run_status(db, run.id, APPROVER, ch.org.id)
    with pytest.raises(HTTPException) as exc:
        service.regenerate_employee_payslip(db, run.id, ch.emp.id, ch.org.id)
    assert exc.value.status_code in (400, 409)
    with pytest.raises(HTTPException) as exc:
        service._ch_refuse_locked_run(run, "CH")
    assert exc.value.status_code == 409 and "Approved" in exc.value.detail
    service._ch_refuse_locked_run(run, "IT")                              # other countries untouched
    data = PayslipItemCreate.model_validate({"employee_id": ch.emp.id, "basic_salary": "8000"})
    with pytest.raises(HTTPException) as exc:
        service.add_payslip_item(db, run.id, data, ch.org.id)
    assert exc.value.status_code == 409


def test_runs_without_ch_payslips_skip_every_ch_hook(db, ch):
    run = _run(db, ch.org, 3)                                             # no payslips at all
    service.advance_payroll_run_status(db, run.id, PREPARER, ch.org.id)
    service.advance_payroll_run_status(db, run.id, PREPARER, ch.org.id)   # self-approval allowed: no CH payslip
    db.refresh(run)
    assert run.status == "Approved" and switzerland_service.ch_stored_approval(db, run) is None


# ── Super Admin: readiness + calculation preview ─────────────────────────

def test_readiness_reports_gates_and_per_canton_status(db, ch):
    with _http(db, SA_A) as c:
        out = c.get("/api/super-admin/compliance/switzerland/readiness", params={"on": "2026-03-31"}).json()
    gates = {g["key"]: g for g in out["gates"]}
    assert list(gates) == ["G1", "G2", "G3", "G4", "G5", "G6", "G7"] and out["ready"] is False
    assert gates["G2"]["complete"] is False and "approved" in gates["G2"]["detail"]   # no distinct approver yet
    assert gates["G4"]["complete"] is False and "VERIFY AGAINST ESTV SPEC" in gates["G4"]["detail"]
    assert gates["G5"]["complete"] is False and gates["G5"]["detail"] == "Missing: ch_ktg"   # no KTG rule here
    zh = next(c for c in out["cantons"] if c["canton"] == "CH-ZH")
    assert zh["packId"] == ch.zh.id and zh["qstModel"] == "MONTHLY" and zh["tariffFileStatus"] == "ACTIVE"
    assert zh["ready"] is False and zh["fak"]["child"]["amount"] is None              # FAK amounts unset
    assert len(out["cantons"]) == 26


def test_super_admin_calculation_preview_is_read_only(db, ch):
    body = {"organizationId": ch.org.id, "employeeId": ch.emp.id, "payDate": "2026-03-31"}
    with _http(db, SA_A) as c:
        out = c.post("/api/super-admin/compliance/switzerland/calculation-preview", json=body).json()
        assert out["blocked"] is False and out["result"]["gross"] == "8000.00"
        assert D(out["switzerland"]["totals"]["ch_qst_total"]) == D("640")
        db.query(TaxabilityRule).filter(TaxabilityRule.tax_component == "ch_alv").update({"status": "Draft"})
        db.commit()
        blocked = c.post("/api/super-admin/compliance/switzerland/calculation-preview", json=body).json()
    assert blocked["blocked"] is True and blocked["blockedKey"] == "ch_taxability:ch_alv"
    assert db.query(PayslipItem).count() == 0 and db.query(PayrollYtdAccumulator).count() == 0
