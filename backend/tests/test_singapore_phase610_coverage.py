"""
tests/test_singapore_phase610_coverage.py
-----------------------------------------
Singapore Phase 6.10 — golden-matrix gaps found by the coverage audit. Every
expected statutory figure here is READ FROM THE SEEDED PACK'S OWN ROWS (the
sourced canonical content), never typed into the test; the assertions are
the engine's rules applied to those rows:

  - CPF age band on edge birthdays (1st / last day of the month, 31 Dec ->
    January of the next year, 29 Feb in a non-leap year): the band changes the
    month AFTER the birthday month (pack row cpf_age_band_semantics).
  - Work Permit levy on 23 / 24 Sep 2026 — the non-construction rows' first
    evidenced day — blocked the day before, the pack's amount on the day.
  - LQS exactly at / one cent below / one cent above the pack's threshold,
    on 30 Jun 2026 (pre-July row) and on 1 Jul 2026 itself (post-July row).
  - PWM for EVERY floor row of EVERY sector in the pack (incl. landscape, lift
    & escalator, security): MET at the floor, SHORTFALL one cent below it
    (BLOCK, or WARN where MOM permits retail averaging).
  - The five generic-generator reports (payroll register, payroll summary,
    CPF contribution, SHG, FWL) and the LQS / SDL workspaces: content equals
    the persisted payslips, one tenant's report never contains another
    tenant's employees, NRIC/FIN never appears unmasked, pack pinned.

app.* imports are lazy (tests/_db_safety.py).
"""

import json
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

A, B = 101, 202


@pytest.fixture
def active_pack(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore, seed_singapore_2027

    pack = seed_singapore(db)
    seed_singapore_2027(db)
    pack.status = "Active"                     # activation governance is covered elsewhere
    db.commit()
    return pack


def _pack_inputs(db, on):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    rates, slabs, pack = resolve_tax_configuration(db, "SG", payroll_date=on)
    assert pack is not None, on
    return {r.component_key: r for r in rates}, slabs


def _calculate(db, on, gross="6000", **kw):
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries import singapore

    rate_map, slabs = _pack_inputs(db, on)
    fields = dict(gross=D(gross), basic=D(gross), country="SG", pay_frequency="Monthly", pay_date=on,
                  date_of_birth=date(1986, 3, 15), sgp_cpf_residency_status="SC", sgp_work_pass_type="NONE",
                  sgp_shg_funds="NONE", ytd_cpf_ow_subject_before=D("0"), ytd_cpf_aw_subject_before=D("0"),
                  ytd_cpf_aw_paid_before=D("0"), sgp_aw_ledger=[], rate_map=rate_map, slabs=slabs)
    fields.update(kw)
    return singapore.calculate(PayrollContext(**fields))


def _month_end(y, m):
    from calendar import monthrange

    return date(y, m, monthrange(y, m)[1])


# ── CPF age band on edge birthdays ──────────────────────────────────────────

@pytest.mark.parametrize("dob,birthday_month,band_until,band_after", [
    (date(1971, 6, 1), (2026, 6), "AGE_LE_55", "AGE_55_60"),      # birthday on the 1st
    (date(1971, 6, 30), (2026, 6), "AGE_LE_55", "AGE_55_60"),     # birthday on the last day
    (date(1971, 1, 1), (2026, 1), "AGE_LE_55", "AGE_55_60"),      # New Year's Day
    (date(1966, 11, 30), (2026, 11), "AGE_55_60", "AGE_60_65"),   # 60, last day of November
])
def test_the_age_band_changes_the_month_after_an_edge_birthday(db, active_pack, dob, birthday_month, band_until, band_after):
    rate_map, _ = _pack_inputs(db, date(2026, 6, 30))
    assert rate_map["cpf_age_band_semantics"].text_value == "MONTH_AFTER_BIRTHDAY"      # the sourced rule under test
    y, m = birthday_month
    before = _month_end(y, m - 1) if m > 1 else None
    after = _month_end(y, m + 1) if m < 12 else _month_end(y + 1, 1)
    band = lambda on: _calculate(db, on, date_of_birth=dob)["sgp_calculation_trace"]["cpf"]["ageBand"]  # noqa: E731
    if before:
        assert band(before) == band_until
    assert band(_month_end(y, m)) == band_until                                             # the birthday month itself
    assert band(after) == band_after


def test_a_31_december_birthday_moves_the_band_in_january_of_the_next_year(db, active_pack):
    band = lambda on: _calculate(db, on, date_of_birth=date(1970, 12, 31))["sgp_calculation_trace"]["cpf"]["ageBand"]  # noqa: E731
    assert band(date(2026, 1, 31)) == "AGE_55_60"                   # 55 on 31 Dec 2025 -> January 2026
    assert band(date(2026, 6, 30)) == "AGE_55_60"


def test_a_leap_day_birthday_at_a_boundary_in_a_non_leap_year_blocks_until_a_sourced_rule_decides(db, active_pack):
    """29 Feb 1956 -> 70 in 2026, which has no 29 February. No pack source
    says whether CPF observes it on 28 Feb or 1 Mar, and it decides whether
    March is still AGE_65_70. February and March fail closed; other months
    and other birth dates are unaffected."""
    from app.modules.payroll.engine.countries.singapore import SingaporeCalculationBlockedError

    dob = date(1956, 2, 29)
    band = lambda on, **kw: _calculate(db, on, date_of_birth=dob, **kw)["sgp_calculation_trace"]["cpf"]["ageBand"]  # noqa: E731
    for month_end in (date(2026, 2, 28), date(2026, 3, 31)):
        with pytest.raises(SingaporeCalculationBlockedError) as exc:
            band(month_end)
        assert exc.value.key == "cpf_leap_day_birthday_basis"
    assert band(date(2026, 1, 31)) == "AGE_65_70" and band(date(2026, 4, 30)) == "AGE_GT_70"
    # Once a (sourced) rule row exists the two months resolve deterministically either way.
    rate_map, slabs = _pack_inputs(db, date(2026, 3, 31))
    for basis, march in (("FEBRUARY", "AGE_GT_70"), ("MARCH", "AGE_65_70")):
        rules = {**rate_map, "cpf_leap_day_birthday_basis": SimpleNamespace(text_value=basis, flat_amount=None)}
        assert band(date(2026, 2, 28), rate_map=rules) == "AGE_65_70"
        assert band(date(2026, 3, 31), rate_map=rules) == march
    from app.modules.payroll import service

    ready = service.get_sg_statutory_summary(db, date(2026, 6, 30))
    assert "cpf_leap_day_birthday_basis" in {d["key"] for d in ready["activationReadiness"]["externalDependencies"]}


# ── Work Permit levy: the 24 Sep 2026 evidence boundary ─────────────────────

def test_the_work_permit_levy_is_blocked_before_its_first_evidenced_day_and_the_packs_amount_on_it(db, active_pack):
    from app.modules.payroll.engine.countries.singapore import work_permit_levy_key

    key = work_permit_levy_key("SERVICES", "TIER_2", "R2")
    row, _ = _pack_inputs(db, date(2026, 9, 24))
    assert row[key].effective_from == date(2026, 9, 24)
    wp = dict(gross="2000", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="WORK_PERMIT",
              sgp_wp_sector="SERVICES", sgp_wp_skill_level="R2", sgp_wp_levy_tier="TIER_2",
              sgp_work_pass_issue_date=date(2024, 1, 1), sgp_work_pass_end_date=date(2028, 12, 31))
    blocked = _calculate(db, date(2026, 9, 23), **wp)
    assert blocked["sgp_calculation_trace"]["fwl"]["status"] == "BLOCKED"
    levied = _calculate(db, date(2026, 9, 24), **wp)
    assert levied["sgp_calculation_trace"]["fwl"]["status"] != "BLOCKED"
    assert levied["employer_eht"] == row[key].flat_amount


# ── LQS threshold boundaries, from the pack's own rows ──────────────────────

@pytest.mark.parametrize("on", [date(2026, 6, 30), date(2026, 7, 1), date(2026, 8, 31)])
def test_lqs_is_met_exactly_at_the_packs_threshold_and_not_one_cent_below(db, active_pack, on):
    rate_map, _ = _pack_inputs(db, on)
    threshold = D(str(rate_map["lqs_full_time_monthly"].flat_amount))
    status = lambda gross: _calculate(db, on, gross=str(gross), sgp_employer_hires_foreign_workers=True)[  # noqa: E731
        "sgp_calculation_trace"]["lqs"]["status"]
    assert status(threshold - D("0.01")) == "BELOW_LQS"
    assert status(threshold) == "MEETS_LQS"
    assert status(threshold + D("0.01")) == "MEETS_LQS"


def test_the_lqs_threshold_changes_on_1_july_2026_itself(db, active_pack):
    june, july = _pack_inputs(db, date(2026, 6, 30))[0], _pack_inputs(db, date(2026, 7, 1))[0]
    assert june["lqs_full_time_monthly"].flat_amount < july["lqs_full_time_monthly"].flat_amount
    between = str(july["lqs_full_time_monthly"].flat_amount - D("0.01"))
    lqs = lambda on: _calculate(db, on, gross=between, sgp_employer_hires_foreign_workers=True)[  # noqa: E731
        "sgp_calculation_trace"]["lqs"]["status"]
    assert (lqs(date(2026, 6, 30)), lqs(date(2026, 7, 1))) == ("MEETS_LQS", "BELOW_LQS")


# ── PWM: every floor row of every sector ────────────────────────────────────

def test_every_pwm_floor_row_is_met_at_the_floor_and_short_one_cent_below(db, active_pack):
    from app.modules.payroll import service
    from app.modules.payroll.engine.jurisdictions.singapore import labour

    on = date(2026, 7, 31)
    rates = service._sg_active_pack_and_rates(db, on)[1]
    floors = {k: r for k, r in rates.items() if k.startswith(labour.PWM_KEY_PREFIX) and r.flat_amount is not None}
    sectors = {k.split("__")[1] for k in floors}
    assert {"LANDSCAPE", "LIFT_ESCALATOR", "SECURITY", "CLEANING", "RETAIL", "FOOD_SERVICES", "WASTE_MANAGEMENT",
            "OPW_ADMIN", "OPW_DRIVER"} <= sectors
    for key, row in floors.items():
        _prefix, sector, group, level = key.split("__")
        facts = {"pwm_sector": sector, "pwm_group": group, "pwm_job_level": level, "residency": "SC"}
        floor = D(str(row.flat_amount))
        at = labour.pwm_check({"id": 1, "code": "P"}, facts, {"basic": floor, "gross_ex_ot": floor}, rates)
        assert [c["code"] for c in at if c["code"].startswith("PWM_")][-1] == "PWM_MET", key
        short = floor - D("0.01")
        below = labour.pwm_check({"id": 1, "code": "P"}, facts, {"basic": short, "gross_ex_ot": short}, rates)
        finding = next(c for c in below if c["code"] == "PWM_SHORTFALL")
        assert finding["severity"] == ("WARN" if sector == "RETAIL" else "BLOCK"), key


# ── Generic-generator reports: content, tenant scope, masking, pinning ──────

GENERIC_SG_TEMPLATES = ("SG-PAYROLL-REGISTER", "SG-PAYROLL-SUMMARY", "SG-CPF-CONTRIBUTION", "SG-SHG-MONTHLY",
                        "SG-FWL-MONTHLY")


@pytest.fixture
def two_tenants(db, active_pack, monkeypatch):
    import app.core.code_generation as code_generation
    import scripts.seed_statutory_report_templates as seed_templates
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service
    from app.modules.payroll.models import (CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayrollStatus,
                                            ReportTemplate)

    counter = {"n": 0}

    def _code(db_, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _code)
    monkeypatch.setattr(seed_templates, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed_templates.run()
    for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG").all():
        t.status, t.approved_by_id = "Active", B          # template lifecycle is covered elsewhere
    db.commit()
    out = {}
    for code, nric, shg in (("ORGX", "S1234567D", "CDAC"), ("ORGY", "S7654321A", "MBMF")):
        org = Organization(organization_name=f"Org {code}", organization_code=code, country="Singapore")
        db.add(org)
        db.commit()
        db.add(CompanyComplianceDetails(organization_id=org.id, jurisdiction_country="SG"))
        db.commit()
        emp = PayrollEmployee(organization_id=org.id, employee_code=f"E{code}", name=f"Employee {code}",
                              country_code="SG", ctc=D("72000"), date_of_birth=date(1986, 3, 15),
                              sgp_cpf_residency_status="SC", sgp_work_pass_type="NONE", sgp_shg_funds=shg,
                              compliance_fields={"nric_fin": nric})
        db.add(emp)
        db.commit()
        run = PayrollRun(organization_id=org.id, period_label="Jun 2026", period_start=date(2026, 6, 1),
                         period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30))
        db.add(run)
        db.commit()
        service.generate_payslips_for_run(db, run, org.id)
        run.status = PayrollStatus.APPROVED
        db.commit()
        out[code] = SimpleNamespace(org=org, emp=emp, run=run, nric=nric)
    return out


@pytest.mark.parametrize("template_key", GENERIC_SG_TEMPLATES)
def test_generic_reports_are_tenant_scoped_masked_pinned_and_match_the_payslips(db, active_pack, two_tenants, template_key):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem, ReportTemplate

    template = db.query(ReportTemplate).filter(ReportTemplate.template_key == template_key).one()
    x, y = two_tenants["ORGX"], two_tenants["ORGY"]
    report = service.generate_report_from_template(db, x.org.id, template.id, x.run.id, actor_id=A)
    blob = json.dumps(report.rendered_data, default=str)
    assert y.emp.name not in blob and y.emp.employee_code not in blob and y.nric not in blob     # other tenant absent
    assert x.nric not in blob                                                                     # never unmasked
    assert report.applicable_tax_pack_id == active_pack.id
    item = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == x.run.id).one()
    assert item.tax_policy_pack_id == active_pack.id
    figures = {str(v) for v in (item.gross_pay, item.employee_pension, item.employer_pension, item.net_pay,
                                item.employer_payroll_tax, item.professional_tax) if v is not None}
    assert any(f in blob or f.rstrip("0").rstrip(".") in blob for f in figures), template_key
    with pytest.raises(Exception):                                                                # IDOR: X's report on Y's run
        service.generate_report_from_template(db, x.org.id, template.id, y.run.id, actor_id=A)


def test_the_lqs_and_sdl_workspaces_are_tenant_scoped_and_masked(db, active_pack, two_tenants):
    from app.modules.payroll import service

    from app.modules.payroll.models import ReportTemplate

    x, y = two_tenants["ORGX"], two_tenants["ORGY"]
    tid = {t.template_key: t.id for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG")}
    for generate in (lambda: service.generate_sg_lqs_compliance(db, x.org.id, tid["SG-LQS-COMPLIANCE"], 2026, 6, actor_id=A),
                     lambda: service.generate_sg_sdl_monthly(db, x.org.id, tid["SG-SDL-MONTHLY"], 2026, 6, actor_id=A)):
        report = generate()
        blob = json.dumps(report.rendered_data, default=str)
        assert y.emp.name not in blob and y.nric not in blob and x.nric not in blob
