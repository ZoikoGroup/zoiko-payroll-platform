"""tests/test_ytd_reversal_integrity.py
--------------------------------------
STEP 1 (Switzerland prep) — shared (every YTD jurisdiction) year-to-date
integrity of the two service paths that MUTATE a run after its payslips have
already posted YTD. Two platform-wide defects are closed in service.py:

(a) regenerate_employee_payslip used to reverse the payslip's posted YTD
    AFTER _compute_payslip_values. Ireland and Italy resolve their YTD inputs
    by READING the live accumulator INSIDE that compute (see _resolve_ie_calc_
    inputs / italy_service.resolve_it_calc_inputs), so the recompute saw the
    payslip's own prior posting as its "prior" base and re-posted a
    double-counted period on every recalculation. The reversal now happens
    BEFORE the recompute (_begin_ytd_correction), putting IE/IT on the same
    true pre-this-payslip base the frozen-input jurisdictions (CA/US/SG/AU)
    already used; _finish_ytd_correction re-posts afterwards. Proven below:
    recalculate an ITALY payslip twice and the accumulator must be identical
    each time — and equal to the original generation.

(b) delete_payroll_run deleted a Draft run without reversing its payslips'
    YTD, leaving stale totals and (for employer-level ADDITIVE rows) a
    last_updated_payslip_id pointing at a cascade-removed payslip. It now
    reverses every payslip's postings BEFORE the cascade delete —
    newest-first so additive rows rewind their ownership chain to a row that
    survives — and refuses (fail-closed, exactly like delete_payslip) when a
    later payslip already built on an ABSOLUTE total.

The Italy tests generate real payslips through the full pack-seeded service
path (the same machinery test_italy_service_integration.py runs); the UK/US/
IN tests use the real accumulator writers wrapped exactly as _post_payslip_ytd
wraps them (the test_ytd_posting_lifecycle.py approach). Imports are lazy
(inside each helper) — see conftest.py.
"""
from datetime import date
from decimal import Decimal as D

import pytest


def _run(db, org, pay_date, label):
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=org.id, period_label=label, period_start=pay_date.replace(day=1),
                     period_end=pay_date, pay_date=pay_date)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _employee(db, org, code, country):
    from app.modules.payroll.models import PayrollEmployee

    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=code, country_code=country,
                          compliance_fields={})
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _posted_payslip(db, org, emp, run, country, us_ss_after=None, uk_levy_increment=None):
    """Posted exactly like _generate_single_payslip wraps the real writers:
    capture → real writer(s) → record into ytd_snapshot["ytdPostings"]."""
    from app.modules.payroll import service
    from app.modules.payroll.engine.base import PayrollResult
    from app.modules.payroll.models import PayslipItem

    pre = service._ytd_capture_state(db, emp.id, org.id)
    item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=org.id, employee_name=emp.name,
                       country_code=country, net_pay=D("1"))
    db.add(item)
    db.flush()
    if us_ss_after is not None:
        service._upsert_us_ytd_accumulator(db, emp.id, run.pay_date, PayrollResult(
            ytd_ss_wages_after=D(us_ss_after), ytd_futa_wages_after=min(D(us_ss_after), D("7000")),
            ytd_medicare_wages_after=D(us_ss_after)), payslip_id=item.id)
    if uk_levy_increment is not None:
        service._upsert_uk_org_levy_ytd(db, org.id, run.pay_date, D(uk_levy_increment), None, payslip_id=item.id)
    service._ytd_record_postings(db, item, pre)
    db.commit()
    return item


def _us_rows(db, emp):
    from app.modules.payroll.models import PayrollYtdAccumulator

    return {r.tax_component: (r.ytd_taxable_wages, r.last_updated_payslip_id)
            for r in db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id)}


def _uk_levy(db, org):
    from app.modules.payroll.models import OrganizationYtdAccumulator

    row = db.query(OrganizationYtdAccumulator).filter(OrganizationYtdAccumulator.organization_id == org.id).one_or_none()
    return None if row is None else (row.ytd_taxable_wages, row.last_updated_payslip_id)


# ── full Italy generation (same seed flow as test_italy_service_integration.py) ──

def _stub_codes(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


@pytest.fixture()
def italy_org(db, organization, monkeypatch):
    from app.modules.payroll import italy_service
    from app.modules.payroll.models import CompanyComplianceDetails, EmployerItalyProfile

    _stub_codes(monkeypatch)
    pack = italy_service.seed_italy_pack(db, status="Active")
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="Italy",
                                    active_pack_id=pack.id))
    db.add(EmployerItalyProfile(organization_id=organization.id, csc_code="70501",
                                fund_status={"fund": "FIS", "fisBand": "UP_TO_5"},
                                prior_year_avg_headcount=10))
    db.commit()
    return organization


def _it_employee(db, org):
    from app.modules.payroll.models import EmployeeStatutoryProfile, PayrollEmployee

    emp = PayrollEmployee(organization_id=org.id, employee_code="IT-INT", name="Integrita",
                          country_code="IT", ctc=D("2500") * 12, date_of_joining=date(2025, 1, 1))
    db.add(emp)
    db.flush()
    db.add(EmployeeStatutoryProfile(
        employee_id=emp.id, organization_id=org.id, country_code="IT", effective_from=date(2026, 1, 1),
        it_worker_class="OPERAIO", it_contract_type="INDETERMINATO", it_cigs_applies=False,
        it_tfr_destination="AZIENDA", it_tax_domicile_region="03", it_tax_domicile_comune="F205"))
    db.commit()
    db.refresh(emp)
    return emp


def _it_march_run(db, org):
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=org.id, period_label="2026-03", period_start=date(2026, 3, 1),
                     period_end=date(2026, 3, 31), pay_date=date(2026, 3, 31))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _it_item(db, run, emp):
    from app.modules.payroll.models import PayslipItem

    return (db.query(PayslipItem)
            .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one())


def _it_row(db, emp, year_key, component):
    from app.modules.payroll.models import PayrollYtdAccumulator

    return (db.query(PayrollYtdAccumulator)
            .filter(PayrollYtdAccumulator.employee_id == emp.id,
                    PayrollYtdAccumulator.tax_year == year_key,
                    PayrollYtdAccumulator.tax_component == component).one_or_none())


def _it_acc(db, emp):
    """The employee's whole accumulator as a comparable dict — values,
    withheld AND ownership must all match across a correction."""
    from app.modules.payroll.models import PayrollYtdAccumulator

    return {(r.tax_component, r.tax_year): (str(r.ytd_taxable_wages), str(r.ytd_tax_withheld), r.last_updated_payslip_id)
            for r in db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id)}


# ── defect (a): a recalculation must never stack a period on its own posting ──

def test_italy_recalculation_twice_posts_identical_ytd(db, italy_org):
    """REGENERATION (a): Ireland/Italy read the live accumulator inside the
    recompute — with the reversal now moved BEFORE that compute, the
    recalculated totals must reproduce the original generation exactly, twice
    in a row, instead of re-posting a period that already sits in the base."""
    from app.modules.payroll import italy_service, service

    emp = _it_employee(db, italy_org)
    italy_service.record_opening_balances(db, emp.id, 2026, addreg_saldo_due=D("330"),
                                          addcom_saldo_due=D("110"), addcom_acconto_due=D("90"))
    db.commit()
    run = _it_march_run(db, italy_org)
    service.generate_payslips_for_run(db, run, italy_org.id)
    item = _it_item(db, run, emp)
    assert item.ytd_snapshot["ytdPostings"]                                  # postings recorded at generation
    original = _it_acc(db, emp)
    key = italy_service.tax_year_key(2026)
    assert D(original[("it_irpef", key)][1]) > 0                             # a period really was withheld

    service.regenerate_employee_payslip(db, run.id, emp.id, italy_org.id)
    db.commit()
    assert _it_acc(db, emp) == original                                      # #1: no double-count

    service.regenerate_employee_payslip(db, run.id, emp.id, italy_org.id)
    db.commit()
    assert _it_acc(db, emp) == original                                      # #2: still identical

    item = _it_item(db, run, emp)
    irpef_posting = next(p for p in item.ytd_snapshot["ytdPostings"] if p["component"] == "it_irpef")
    assert D(irpef_posting["after"]["tax"]) == D(original[("it_irpef", key)][1])


def test_india_recalculation_twice_and_delete_run_are_financially_stable(db, organization, monkeypatch):
    """REGENERATION + DELETE, the no-accumulator jurisdiction: a payslip with
    no posting records must not invent YTD during a correction (nothing
    reverses, nothing re-posts) — net pay reproduces exactly — and the run
    still deletes as a clean cascade."""
    from app.modules.payroll import service
    from app.modules.payroll.models import ContributionRate, PayrollRun, PayrollYtdAccumulator, PayslipItem

    _stub_codes(monkeypatch)
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="IN", jurisdiction_state="Maharashtra",
        component_key="pt", label="pt", employee_share="—", employer_share="—", total="—",
        flat_amount=D("200"), employee_rate_pct=None,
    ))
    db.commit()

    emp = _employee(db, organization, "INR1", "IN")
    emp.ctc = D("600000")
    emp.work_state = "Maharashtra"
    db.commit()

    run = PayrollRun(organization_id=organization.id, period_label="Feb",
                     period_start=date(2026, 2, 1), period_end=date(2026, 2, 28), pay_date=date(2026, 2, 28))
    db.add(run)
    db.commit()
    db.refresh(run)

    service.generate_payslips_for_run(db, run, organization.id)
    db.commit()
    first = (db.query(PayslipItem)
             .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one())
    assert first.net_pay == first.net_pay
    assert db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id).count() == 0

    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)
    db.commit()
    second = (db.query(PayslipItem)
              .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one())
    assert second.net_pay == first.net_pay and second.gross_pay == first.gross_pay
    assert db.query(PayrollYtdAccumulator).filter(PayrollYtdAccumulator.employee_id == emp.id).count() == 0

    service.regenerate_employee_payslip(db, run.id, emp.id, organization.id)
    db.commit()
    third = (db.query(PayslipItem)
             .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one())
    assert third.net_pay == second.net_pay

    service.delete_payroll_run(db, run.id, organization.id)
    assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).count() == 0


# ── defect (b): deleting a run must reverse what it posted ──────────────────

def test_italy_delete_run_restores_accumulator_from_opening_balances(db, italy_org):
    """DELETE (absolute employee rows): rows the run CREATED are removed;
    rows it merely UPDATED — the recorded §5 opening balances — return to
    their recorded opening values with no owner."""
    from app.modules.payroll import italy_service, service

    emp = _it_employee(db, italy_org)
    italy_service.record_opening_balances(db, emp.id, 2026, addreg_saldo_due=D("330"),
                                          addcom_saldo_due=D("110"), addcom_acconto_due=D("90"))
    db.commit()
    run = _it_march_run(db, italy_org)
    service.generate_payslips_for_run(db, run, italy_org.id)
    db.commit()
    key = italy_service.tax_year_key(2026)
    assert _it_row(db, emp, key, "it_irpef") is not None                     # the run created this
    assert _it_row(db, emp, key, "it_addreg_saldo").last_updated_payslip_id is not None   # and now owns the opening row

    service.delete_payroll_run(db, run.id, italy_org.id)

    assert _it_row(db, emp, key, "it_irpef") is None                         # created rows gone
    addreg = _it_row(db, emp, key, "it_addreg_saldo")
    assert (addreg.ytd_taxable_wages, addreg.ytd_tax_withheld, addreg.last_updated_payslip_id) == (
        D("330"), D("0"), None)                                              # updated rows restored to their record


def test_uk_delete_run_rewinds_employer_level_rows_without_dangling_owner(db, organization):
    """DELETE (employer-level ADDITIVE rows): two payslips in one Draft run
    add increments to the org's UK apprenticeship-levy row. Deleting the run
    reverses both — newest-first, so ownership rewinds to a row that
    survives — back to zero with NO dangling last_updated_payslip_id."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    run = _run(db, organization, date(2026, 5, 31), "May")
    a = _employee(db, organization, "UKR1", "UK")
    b = _employee(db, organization, "UKR2", "UK")
    first = _posted_payslip(db, organization, a, run, "UK", uk_levy_increment="3000")
    second = _posted_payslip(db, organization, b, run, "UK", uk_levy_increment="4500")
    assert _uk_levy(db, organization) == (D("7500.00"), second.id)

    service.delete_payroll_run(db, run.id, organization.id)

    assert _uk_levy(db, organization) == (D("0.00"), None)                   # neither increment survives, no dangling owner
    assert db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).count() == 0
    assert db.get(PayslipItem, first.id) is None and db.get(PayslipItem, second.id) is None


def test_us_delete_run_refused_when_a_later_payslip_accumulated_on_top(db, organization):
    """DELETE fail-closed (absolute rows, later payslip): a Draft run whose
    absolute total a LATER run's payslip has already built on cannot be
    deleted — reversing would silently abandon that total's provenance. Same
    contract as delete_payslip, and nothing is touched."""
    from fastapi import HTTPException
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    emp = _employee(db, organization, "USR1", "US")
    jan_run = _run(db, organization, date(2026, 1, 31), "Jan")
    feb_run = _run(db, organization, date(2026, 2, 28), "Feb")
    jan = _posted_payslip(db, organization, emp, jan_run, "US", us_ss_after="5000")
    feb = _posted_payslip(db, organization, emp, feb_run, "US", us_ss_after="11000")
    assert _us_rows(db, emp)["social_security"] == (D("11000.00"), feb.id)

    with pytest.raises(HTTPException) as exc:
        service.delete_payroll_run(db, jan_run.id, organization.id)
    assert exc.value.status_code == 409 and "Cannot delete this payroll run" in exc.value.detail

    assert db.get(PayslipItem, jan.id) is not None                           # jan survives its own refusal
    assert _us_rows(db, emp)["social_security"] == (D("11000.00"), feb.id)   # and feb still owns the total