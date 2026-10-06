"""
tests/test_ytd_posting_lifecycle.py
------------------------------------
Shared (every YTD jurisdiction) year-to-date posting lifecycle — Phase 4A:
a payslip's accumulator postings are recorded in its ytd_snapshot
("ytdPostings"); deleting the payslip reverses them (or refuses when a later
payslip already built on them); a legacy payslip without postings is
restored only where its snapshot proves the prior value. The foreign key
payroll_ytd_accumulators.last_updated_payslip_id is never left dangling.

Postings here go through the REAL accumulator writers (US absolute
_upsert_us_ytd_accumulator, UK employer-level additive
_upsert_uk_org_levy_ytd) wrapped exactly as _generate_single_payslip wraps
them. Imports are lazy (inside each test) — see conftest.py.
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

    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=code, country_code=country, compliance_fields={})
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _payslip(db, org, emp, run, country, us_ss_after=None, uk_levy_increment=None):
    """Posted like _generate_single_payslip: capture → real writer(s) → record."""
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


def test_postings_are_recorded_with_before_after_and_previous_writer(db, organization):
    emp = _employee(db, organization, "USP1", "US")
    jan = _payslip(db, organization, emp, _run(db, organization, date(2026, 1, 31), "Jan"), "US", us_ss_after="5000")
    feb = _payslip(db, organization, emp, _run(db, organization, date(2026, 2, 28), "Feb"), "US", us_ss_after="11000")
    ss = next(p for p in feb.ytd_snapshot["ytdPostings"] if p["component"] == "social_security")
    assert (ss["mode"], ss["created"], ss["before"]["wages"], ss["after"]["wages"], ss["prevWriter"]) == (
        "absolute", False, "5000.00", "11000.00", jan.id)
    assert next(p for p in jan.ytd_snapshot["ytdPostings"] if p["component"] == "social_security")["created"] is True


def test_delete_one_two_three_payslips_latest_first_restores_exact_totals(db, organization):
    from fastapi import HTTPException
    from app.modules.payroll import service

    emp = _employee(db, organization, "USP3", "US")
    slips = [_payslip(db, organization, emp, _run(db, organization, date(2026, m, 28), f"M{m}"), "US", us_ss_after=str(5000 * m))
             for m in (1, 2, 3)]
    assert _us_rows(db, emp)["social_security"] == (D("15000.00"), slips[2].id)
    for earlier in slips[:2]:                                   # an earlier payslip cannot be deleted first
        with pytest.raises(HTTPException) as exc:
            service.delete_payslip(db, earlier.id, organization.id)
        assert exc.value.status_code == 409 and "later payslip" in exc.value.detail
    service.delete_payslip(db, slips[2].id, organization.id)
    assert _us_rows(db, emp)["social_security"] == (D("10000.00"), slips[1].id)
    service.delete_payslip(db, slips[1].id, organization.id)
    assert _us_rows(db, emp)["social_security"] == (D("5000.00"), slips[0].id)
    service.delete_payslip(db, slips[0].id, organization.id)
    assert _us_rows(db, emp) == {}                              # rows it created are removed — nothing orphaned


def test_delete_then_recreate_posts_again_from_the_restored_total(db, organization):
    from app.modules.payroll import service

    emp = _employee(db, organization, "USP4", "US")
    _payslip(db, organization, emp, _run(db, organization, date(2026, 1, 31), "Jan"), "US", us_ss_after="5000")
    feb_run = _run(db, organization, date(2026, 2, 28), "Feb")
    feb = _payslip(db, organization, emp, feb_run, "US", us_ss_after="11000")
    service.delete_payslip(db, feb.id, organization.id)
    again = _payslip(db, organization, emp, feb_run, "US", us_ss_after="9000")
    assert _us_rows(db, emp)["social_security"] == (D("9000.00"), again.id)


def test_employer_level_additive_rows_lose_only_the_deleted_payslips_increment(db, organization):
    from app.modules.payroll import service

    a, b = _employee(db, organization, "UKL1", "UK"), _employee(db, organization, "UKL2", "UK")
    run = _run(db, organization, date(2026, 5, 31), "May")
    first = _payslip(db, organization, a, run, "UK", uk_levy_increment="3000")
    second = _payslip(db, organization, b, run, "UK", uk_levy_increment="4500")
    assert _uk_levy(db, organization) == (D("7500.00"), second.id)
    service.delete_payslip(db, first.id, organization.id)         # additive: order-independent
    assert _uk_levy(db, organization) == (D("4500.00"), second.id)
    service.delete_payslip(db, second.id, organization.id)
    assert _uk_levy(db, organization) == (D("0.00"), None)          # previous writer deleted → NULL, never dangling


def test_payslip_without_any_ytd_deletes_normally(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    emp = _employee(db, organization, "INP1", "IN")
    item = _payslip(db, organization, emp, _run(db, organization, date(2026, 5, 31), "May"), "IN")
    assert item.ytd_snapshot is None                                 # nothing posted → nothing stored
    service.delete_payslip(db, item.id, organization.id)
    assert db.get(PayslipItem, item.id) is None


def test_legacy_payslip_is_restored_from_its_snapshot_or_refused(db, organization):
    from fastapi import HTTPException
    from app.modules.payroll import service
    from app.modules.payroll.models import OrganizationYtdAccumulator, PayrollYtdAccumulator, PayslipItem

    emp = _employee(db, organization, "USLEG", "US")
    run = _run(db, organization, date(2026, 3, 31), "Mar")
    legacy = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name="x",
                         country_code="US", net_pay=D("1"),
                         ytd_snapshot={"social_security": {"ytd_before": "4000", "ytd_after": "9000"}})
    db.add(legacy)
    db.flush()
    db.add(PayrollYtdAccumulator(employee_id=emp.id, tax_year="US-CY-2026", tax_component="social_security",
                                 ytd_taxable_wages=D("9000"), last_updated_payslip_id=legacy.id))
    db.commit()
    service.delete_payslip(db, legacy.id, organization.id)
    assert _us_rows(db, emp)["social_security"] == (D("4000.00"), None)

    org_legacy = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id, employee_name="y",
                             country_code="UK", net_pay=D("1"))
    db.add(org_legacy)
    db.flush()
    db.add(OrganizationYtdAccumulator(organization_id=organization.id, tax_year="UK-TY-2026-27", tax_component="appr_levy_pay_bill",
                                      ytd_taxable_wages=D("3000"), last_updated_payslip_id=org_legacy.id))
    db.commit()
    with pytest.raises(HTTPException) as exc:                       # an unrecorded increment is never guessed
        service.delete_payslip(db, org_legacy.id, organization.id)
    assert exc.value.status_code == 409 and "cannot be reversed safely" in exc.value.detail
    assert db.get(PayslipItem, org_legacy.id) is not None


# ── Phase 4A WS4: shared payslip PDF identifiers ──────────────────────────

def _pdf_text(db, org, country, compliance_fields):
    import io
    import pypdf
    from app.modules.payroll import service
    from app.modules.payroll.models import PayslipItem

    emp = _employee(db, org, f"PDF{country}", country)
    run = _run(db, org, date(2026, 6, 30), f"Jun {country}")
    item = PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=org.id, employee_name=emp.name,
                       country_code=country, compliance_fields=compliance_fields, basic_salary=D("5000"),
                       gross_pay=D("5000"), total_deductions=D("0"), net_pay=D("5000"))
    db.add(item)
    db.commit()
    pdf = service.generate_payslip_pdf_bytes(db, item.id, org.id)
    return "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def test_us_payslip_pdf_prints_only_the_last_four_ssn_digits(db, organization):
    """California Labor Code §226(a)(7): "only the last four digits of their
    social security number"."""
    text = _pdf_text(db, organization, "US", {"ssn": "123-45-6789", "w4_filing_status": "SINGLE"})
    assert "XXX-XX-6789" in text and "123-45-6789" not in text


def test_unverified_identifiers_are_unchanged_on_the_pdf(db, organization):
    """UK NINO (and AU/CA/DE/IN identifiers): no authoritative payslip-content
    source could be verified in Phase 4A, so the output is deliberately unchanged."""
    text = _pdf_text(db, organization, "UK", {"nino": "AB123456C", "paye_tax_code": "1257L", "sort_code": "40-12-34"})
    assert "AB123456C" in text
