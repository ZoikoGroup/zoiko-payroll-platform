"""tests/test_germany_tenant_isolation_adversarial.py
--------------------------------------------------
Phase 8BR — Adversarial multi-tenant isolation test suite for Germany payroll.

Proves:
1. Cross-tenant statutory profile creation attempts are rejected (NotFoundException).
2. Cross-tenant statutory profile query (get_employee_statutory_profile_as_of) fails closed (NotFoundException).
3. Cross-tenant statutory profile history listing is strictly isolated (NotFoundException).
4. Cross-tenant ELSTER certificate configurations remain strictly isolated.
5. Cross-tenant Germany summary reports partition data exclusively per tenant.
"""

from datetime import date
from decimal import Decimal
import pytest

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.modules.organizations.models import Organization
from app.modules.payroll import service
from app.modules.payroll.models import (
    EmployeeStatutoryProfile,
    PayrollEmployee,
    PayrollRun,
    PayslipItem,
)
from app.modules.payroll.schemas import (
    EmployeeStatutoryProfileCreate,
)


@pytest.fixture
def org_a(db):
    org = Organization(organization_name="Tenant Alpha DE", organization_code="TENANT_A_DE")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture
def org_b(db):
    org = Organization(organization_name="Tenant Beta DE", organization_code="TENANT_B_DE")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture
def emp_a(db, org_a):
    emp = PayrollEmployee(
        organization_id=org_a.id,
        employee_code="EMP_A_01",
        name="Employee Alpha",
        country_code="DE",
        ctc=Decimal("6240.00"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@pytest.fixture
def emp_b(db, org_b):
    emp = PayrollEmployee(
        organization_id=org_b.id,
        employee_code="EMP_B_01",
        name="Employee Beta",
        country_code="DE",
        ctc=Decimal("6240.00"),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def test_cross_tenant_create_statutory_profile_rejected(db, org_a, org_b, emp_a):
    """Tenant B cannot create a statutory profile for Tenant A's employee."""
    payload = EmployeeStatutoryProfileCreate(
        employee_id=emp_a.id,
        effective_from=date(2026, 1, 1),
        de_tax_class="I",
        de_health_fund_code="TK",
        de_employment_classification="MINIJOB",
    )
    with pytest.raises(NotFoundException):
        service.create_employee_statutory_profile_version(
            db, emp_a.id, org_b.id, payload, actor_id=2
        )


def test_cross_tenant_read_statutory_profile_rejected(db, org_a, org_b, emp_a):
    """Tenant B cannot read Tenant A's employee statutory profile."""
    # Create profile for Employee A under Org A
    payload = EmployeeStatutoryProfileCreate(
        employee_id=emp_a.id,
        effective_from=date(2026, 1, 1),
        de_tax_class="I",
        de_health_fund_code="TK",
        de_employment_classification="MINIJOB",
    )
    profile_a = service.create_employee_statutory_profile_version(
        db, emp_a.id, org_a.id, payload, actor_id=1
    )
    assert profile_a.id is not None

    # Attempt to query profile_a using Org B's organization_id
    with pytest.raises(NotFoundException):
        service.get_employee_statutory_profile_as_of(
            db, emp_a.id, org_b.id, as_of=date(2026, 1, 15)
        )


def test_cross_tenant_list_statutory_profile_history_rejected(db, org_a, org_b, emp_a):
    """Tenant B cannot view history of Tenant A's employee statutory profiles."""
    with pytest.raises(NotFoundException):
        service.list_employee_statutory_profile_history(db, emp_a.id, org_b.id)


def test_cross_tenant_elster_config_isolated(db, org_a, org_b):
    """Tenant B cannot view or mutate Tenant A's ELSTER certificate config."""
    service.set_elster_certificate_config(
        db, org_a.id, "vault://org-a/elster.pfx", "Org A cert", actor_id=1
    )
    # Query Org B's config
    config_b = service.get_elster_certificate_config(db, org_b.id)
    assert config_b is None, "Tenant B must not see Tenant A's ELSTER certificate config"


def test_cross_tenant_germany_summary_report_isolated(db, org_a, org_b, emp_a, emp_b):
    """Payroll summary report partitioned strictly per organization."""
    # Run payroll for Org A
    run_a = PayrollRun(
        organization_id=org_a.id,
        run_code="RUN-A-001",
        period_label="January 2026",
        pay_date=date(2026, 1, 31),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        status="Approved",
    )
    db.add(run_a)
    db.commit()
    db.refresh(run_a)

    item_a = PayslipItem(
        organization_id=org_a.id,
        payroll_run_id=run_a.id,
        employee_id=emp_a.id,
        employee_name=emp_a.name,
        country_code="DE",
        gross_pay=Decimal("520.00"),
        net_pay=Decimal("501.28"),
        status="Calculated",
    )
    db.add(item_a)
    db.commit()

    # Query summary report for Org B
    report_b = service.get_germany_payroll_summary_report(
        db, org_b.id, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
    )
    assert report_b["employeeCounts"]["total"] == 0, "Org B report must not aggregate Org A records"
    assert Decimal(report_b["grossPay"]["amount"]) == Decimal("0")

    # Query summary report for Org A
    report_a = service.get_germany_payroll_summary_report(
        db, org_a.id, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
    )
    assert report_a["employeeCounts"]["total"] == 1
    assert Decimal(report_a["grossPay"]["amount"]) == Decimal("520.00")


# ── Phase 8BW — direct-ID / IDOR adversarial coverage for payslips, runs,
# and the payroll register (Part 5 of the phase brief: "Perform adversarial
# tests... A user -> B payslip / B payroll run / B register / B PDF").
# The tests above already prove statutory-profile/ELSTER-config/summary-
# report isolation; these extend the SAME org_a/org_b/emp_a/emp_b fixtures
# to the payslip/run/register surfaces that were not previously covered by
# an adversarial (not just code-reading) test. ──────────────────────────

@pytest.fixture
def run_and_item_a(db, org_a, emp_a):
    """One real, persisted PayrollRun + PayslipItem owned by Tenant A."""
    run = PayrollRun(
        organization_id=org_a.id, run_code="RUN-A-IDOR", period_label="February 2026",
        pay_date=date(2026, 2, 28), period_start=date(2026, 2, 1), period_end=date(2026, 2, 28),
        status="Approved",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    item = PayslipItem(
        organization_id=org_a.id, payroll_run_id=run.id, employee_id=emp_a.id,
        employee_name=emp_a.name, country_code="DE",
        gross_pay=Decimal("4500.00"), net_pay=Decimal("3200.00"), status="Pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return run, item


def test_cross_tenant_get_payslip_by_id_rejected(db, org_b, run_and_item_a):
    """Tenant B cannot fetch Tenant A's payslip by direct ID (IDOR)."""
    _run, item = run_and_item_a
    with pytest.raises(NotFoundException):
        service.get_payslip_by_id(db, item.id, org_b.id)
    # Sanity: the SAME id resolves fine for its real owner.
    data, fetched_item, _run2 = service.get_payslip_by_id(db, item.id, run_and_item_a[0].organization_id)
    assert fetched_item.id == item.id
    assert data["employee"] == "Employee Alpha"


def test_cross_tenant_download_payslip_pdf_rejected(db, org_b, run_and_item_a):
    """Tenant B cannot download Tenant A's payslip PDF by direct ID."""
    _run, item = run_and_item_a
    with pytest.raises(NotFoundException):
        service.generate_payslip_pdf_bytes(db, item.id, org_b.id)


def test_cross_tenant_delete_payslip_rejected(db, org_b, run_and_item_a):
    """Tenant B cannot delete Tenant A's payslip by direct ID — the payslip
    must still exist afterward, not merely raise (proves this isn't a
    delete-then-fail-to-report-it bug)."""
    _run, item = run_and_item_a
    with pytest.raises(NotFoundException):
        service.delete_payslip(db, item.id, org_b.id)
    still_there = db.query(PayslipItem).filter(PayslipItem.id == item.id).first()
    assert still_there is not None, "Cross-tenant delete attempt must not actually delete the row"


def test_cross_tenant_get_payroll_run_rejected(db, org_b, run_and_item_a):
    """Tenant B cannot fetch Tenant A's payroll run by direct ID."""
    run, _item = run_and_item_a
    with pytest.raises(NotFoundException):
        service.get_payroll_run_by_id(db, run.id, org_b.id)


def test_cross_tenant_payroll_register_pdf_rejected(db, org_b, run_and_item_a):
    """Tenant B cannot generate Tenant A's payroll register PDF by direct
    run ID — the register export must fail closed, not silently render an
    empty/wrong-tenant document."""
    run, _item = run_and_item_a
    with pytest.raises(NotFoundException):
        service.generate_report_pdf_bytes(db, run.id, org_b.id)


def test_cross_tenant_payroll_register_csv_rejected(db, org_b, run_and_item_a):
    """Tenant B cannot generate Tenant A's payroll register CSV by direct
    run ID."""
    run, _item = run_and_item_a
    with pytest.raises(NotFoundException):
        service.generate_report_csv_bytes(db, run.id, org_b.id)


def test_cross_tenant_list_payslips_excludes_other_tenant(db, org_a, org_b, run_and_item_a):
    """List/filter access (not just direct-ID access) must also partition
    strictly per tenant — Tenant B's payslip list must never include a row
    whose organization_id is Tenant A's, even with no filter applied."""
    _run, item = run_and_item_a
    list_b = service.list_payslips(db, org_b.id)
    assert not any(p.get("id") == item.id for p in list_b), "Org B's payslip list must not contain Org A's payslip"
    list_a = service.list_payslips(db, org_a.id)
    assert any(p.get("id") == item.id for p in list_a), "Org A's own list must still contain its own payslip"
