"""
tests/test_singapore_phase610_immutability.py
---------------------------------------------
Singapore Phase 6.10 — historical immutability across two genuinely
DIFFERENT statutory packs (the 2026 and 2027 CPF tables), end to end through
real payroll generation and real report generators.

  Cycle 1 (Dec 2026) under Pack A (SG-PAYROLL-2026) -> payslip + SDL and CPF
  contribution reports. The figures equal golden vector
  cpf_2026_age57_ow_5000_december.
  Pack B (SG-PAYROLL-2027) is Active, and Pack A's live rows are then edited.
  Cycle 2 (Jan 2027) -> uses Pack B: golden cpf_2027_age57_ow_5000_january.
  Replaying cycle 1 (payslip regeneration) and regenerating its reports ->
  unchanged, still pinned to Pack A and to the same template version; the
  original report's rendered data is untouched (it is Superseded, not edited).

Expected figures are the golden fixtures' own (CPF Board tables), never typed
here. app.* imports are lazy (tests/_db_safety.py).
"""

import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

A = 101
GOLDEN = Path(__file__).parent / "fixtures" / "sg_golden"


def _golden(name):
    return json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _codes(monkeypatch):
    import app.core.code_generation as code_generation

    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _run(db, org_id, pay_date):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun, PayrollStatus

    run = PayrollRun(organization_id=org_id, period_label=pay_date.strftime("%Y-%m"),
                     period_start=pay_date.replace(day=1), period_end=pay_date, pay_date=pay_date)
    db.add(run)
    db.commit()
    service.generate_payslips_for_run(db, run, org_id)
    run.status = PayrollStatus.APPROVED
    db.commit()
    db.refresh(run)
    return run


def _figures(item):
    return {"employee_pension": item.employee_pension, "employer_pension": item.employer_pension,
            "employer_payroll_tax": item.employer_payroll_tax, "net_pay": item.net_pay, "gross_pay": item.gross_pay,
            "pack": item.tax_policy_pack_id, "version": item.tax_policy_version}


def test_history_stays_on_pack_a_while_new_payroll_uses_pack_b(db, monkeypatch):
    import scripts.seed_statutory_report_templates as seed_templates
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service
    from app.modules.payroll.models import (CompanyComplianceDetails, ContributionRate, GeneratedReport,
                                            PayrollEmployee, PayslipItem, ReportTemplate)
    from scripts.seed_singapore_canonical_pack import seed_singapore, seed_singapore_2027

    pack_a, pack_b = seed_singapore(db), seed_singapore_2027(db)
    pack_a.status = pack_b.status = "Active"           # activation governance is covered by the 6.10 gate tests
    db.commit()
    monkeypatch.setattr(seed_templates, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed_templates.run()
    for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG"):
        t.status, t.approved_by_id = "Active", 202
    db.commit()
    tpl = {t.template_key: t for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG")}

    dec, jan = _golden("cpf_2026_age57_ow_5000_december"), _golden("cpf_2027_age57_ow_5000_january")
    ctx = dec["context"]
    org = Organization(organization_name="Immutability Pte Ltd", organization_code="SGIMM", country="Singapore")
    db.add(org)
    db.commit()
    db.add(CompanyComplianceDetails(organization_id=org.id, jurisdiction_country="SG"))
    emp = PayrollEmployee(organization_id=org.id, employee_code="IMM1", name="Employee IMM1", country_code="SG",
                          ctc=D(ctx["gross"]) * 12, date_of_birth=date.fromisoformat(ctx["date_of_birth"]),
                          sgp_cpf_residency_status=ctx["sgp_cpf_residency_status"], sgp_work_pass_type="NONE",
                          sgp_shg_funds="NONE", compliance_fields={"nric_fin": "S1234567D"})
    db.add(emp)
    db.commit()

    # ── Cycle 1: December 2026 under Pack A ────────────────────────────────
    run1 = _run(db, org.id, date(2026, 12, 31))
    item1 = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run1.id).one()
    before = _figures(item1)
    assert before["pack"] == pack_a.id
    assert (before["employee_pension"], before["employer_pension"]) == (
        D(dec["expected"]["employee_pension"]), D(dec["expected"]["employer_pension"]))
    sdl1 = service.generate_sg_sdl_monthly(db, org.id, tpl["SG-SDL-MONTHLY"].id, 2026, 12, actor_id=A)
    cpf1 = service.generate_report_from_template(db, org.id, tpl["SG-CPF-CONTRIBUTION"].id, run1.id, actor_id=A)
    frozen = {r.id: (json.dumps(r.rendered_data, sort_keys=True, default=str), r.applicable_tax_pack_id,
                     r.template_version) for r in (sdl1, cpf1)}

    # ── Pack A's live rows are edited later (never allowed to reach history) ─
    cap = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack_a.id,
                                             ContributionRate.component_key == "sdl_max_monthly").one())
    cap.flat_amount = D("99")
    db.commit()

    # ── Cycle 2: January 2027 under Pack B ─────────────────────────────────
    run2 = _run(db, org.id, date(2027, 1, 31))
    item2 = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run2.id).one()
    assert item2.tax_policy_pack_id == pack_b.id
    assert (item2.employee_pension, item2.employer_pension) == (
        D(jan["expected"]["employee_pension"]), D(jan["expected"]["employer_pension"]))
    assert (item2.employee_pension, item2.employer_pension) != (before["employee_pension"], before["employer_pension"])

    # ── History is locked: an approved run's payslip cannot be recalculated in place ─
    with pytest.raises(Exception, match="locked"):
        service.regenerate_employee_payslip(db, run1.id, emp.id, org.id)
    db.rollback()
    db.expire_all()
    stored = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run1.id).one()
    assert _figures(stored) == before
    # ── Replay cycle 1 on its frozen statutory snapshot: identical, the later edit never applied ─
    replay = service._sg_frozen_recompute(db, run1, emp, stored, org.id)
    for field in ("employee_pension", "employer_pension", "employer_payroll_tax", "net_pay"):
        assert D(str(replay[field])) == before[field], field

    # ── Regenerate cycle 1's reports: same figures, same pack, same template version ─
    sdl2 = service.generate_sg_sdl_monthly(db, org.id, tpl["SG-SDL-MONTHLY"].id, 2026, 12, actor_id=A)
    cpf2 = service.generate_report_from_template(db, org.id, tpl["SG-CPF-CONTRIBUTION"].id, run1.id, actor_id=A)
    for old, new in ((sdl1, sdl2), (cpf1, cpf2)):
        db.refresh(old)
        body, pack_id, version = frozen[old.id]
        assert json.dumps(old.rendered_data, sort_keys=True, default=str) == body     # the original is never edited
        assert old.status == "Superseded" and new.status != "Superseded"
        assert (new.applicable_tax_pack_id, new.template_version) == (pack_id, version) == (pack_a.id, old.template_version)
    assert json.dumps(sdl2.rendered_data.get("totals") or sdl2.rendered_data, sort_keys=True, default=str).count("99") == \
        json.dumps(sdl1.rendered_data.get("totals") or sdl1.rendered_data, sort_keys=True, default=str).count("99")
    assert db.query(GeneratedReport).filter(GeneratedReport.organization_id == org.id).count() == 4
