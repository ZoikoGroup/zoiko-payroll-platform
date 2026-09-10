"""
tests/test_uk_employer_annual_charges.py
--------------------------------------------
Coverage for service.py's get_uk_employer_charges_summary()/
calculate_uk_employment_allowance()/calculate_uk_class_1a_1b_charge()
(ZP-TAX-UK-2026-27-001 §9.3/§14 gap-closure Phase 6, 2026-09-09) — the
standalone, run-independent Employer Annual Charges functions. DB-
integration style: real ContributionRate/OrganizationYtdAccumulator rows,
exercising the resolution chain into uk.py's calculate_employment_
allowance_net_liability()/calculate_class_1a_1b_charge().
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import ContributionRate, OrganizationYtdAccumulator


def _seed_employment_allowance_cap(db, org_id, cap=Decimal("10500")):
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="empl_allowance_cap", label="Employment Allowance Cap",
        employee_share="—", employer_share="—", total="£10,500",
        flat_amount=cap,
    ))
    db.commit()


def _seed_class_1a_benefits_rate(db, org_id, rate=Decimal("15")):
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="c1a_benefits_rate", label="Class 1A — Benefits Rate",
        employee_share="—", employer_share="15%", total="15%",
        employer_rate_pct=rate,
    ))
    db.commit()


def _seed_class_1a_termination(db, org_id, rate=Decimal("15"), thresh=Decimal("30000")):
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="c1a_term_rate", label="Class 1A — Termination Rate",
        employee_share="—", employer_share="15%", total="15%",
        employer_rate_pct=rate,
    ))
    db.add(ContributionRate(
        organization_id=org_id, jurisdiction_country="UK",
        component_key="c1a_term_thresh", label="Class 1A — Termination Threshold",
        employee_share="—", employer_share="—", total="£30,000",
        flat_amount=thresh,
    ))
    db.commit()


def _seed_employer_ni_accumulator(db, org_id, tax_year, amount):
    db.add(OrganizationYtdAccumulator(
        organization_id=org_id, tax_year=tax_year, tax_component="uk_employer_ni_total",
        ytd_taxable_wages=amount,
    ))
    db.commit()


def test_summary_returns_zeros_for_fresh_org(db, organization):
    result = service.get_uk_employer_charges_summary(db, organization.id, date(2026, 6, 1))
    assert result["tax_year"] == "UK-TY-2026-27"
    assert result["cumulative_employer_ni"] == Decimal("0")
    assert result["cumulative_apprenticeship_levy_pay_bill"] == Decimal("0")


def test_summary_reflects_accumulated_employer_ni(db, organization):
    _seed_employer_ni_accumulator(db, organization.id, "UK-TY-2026-27", Decimal("8000"))
    result = service.get_uk_employer_charges_summary(db, organization.id, date(2026, 6, 1))
    assert result["cumulative_employer_ni"] == Decimal("8000")


def test_employment_allowance_not_eligible_when_not_claimed(db, organization):
    _seed_employment_allowance_cap(db, organization.id)
    _seed_employer_ni_accumulator(db, organization.id, "UK-TY-2026-27", Decimal("8000"))
    result = service.calculate_uk_employment_allowance(db, organization.id, employer_has_claimed=False, as_of=date(2026, 6, 1))
    assert result["eligible"] is False
    assert result["net_liability"] == Decimal("8000")


def test_employment_allowance_reduces_liability_below_cap(db, organization):
    _seed_employment_allowance_cap(db, organization.id)
    _seed_employer_ni_accumulator(db, organization.id, "UK-TY-2026-27", Decimal("8000"))
    result = service.calculate_uk_employment_allowance(db, organization.id, employer_has_claimed=True, as_of=date(2026, 6, 1))
    assert result["eligible"] is True
    assert result["net_liability"] == Decimal("0")
    assert result["allowance_remaining"] == Decimal("2500.00")
    assert result["cumulative_employer_ni"] == Decimal("8000")


def test_employment_allowance_above_cap_leaves_a_net_liability(db, organization):
    _seed_employment_allowance_cap(db, organization.id)
    _seed_employer_ni_accumulator(db, organization.id, "UK-TY-2026-27", Decimal("20000"))
    result = service.calculate_uk_employment_allowance(db, organization.id, employer_has_claimed=True, as_of=date(2026, 6, 1))
    assert result["eligible"] is True
    assert result["net_liability"] == Decimal("9500.00")
    assert result["allowance_remaining"] == Decimal("0")


def test_employment_allowance_fails_closed_when_cap_unconfigured(db, organization):
    _seed_employer_ni_accumulator(db, organization.id, "UK-TY-2026-27", Decimal("8000"))
    result = service.calculate_uk_employment_allowance(db, organization.id, employer_has_claimed=True, as_of=date(2026, 6, 1))
    assert result["eligible"] is False
    assert "not configured" in result["reason"]


def test_class_1a_benefits_charges_full_amount(db, organization):
    _seed_class_1a_benefits_rate(db, organization.id)
    result = service.calculate_uk_class_1a_1b_charge(db, organization.id, "BENEFITS", Decimal("2000"), as_of=date(2026, 6, 1))
    assert result["eligible"] is True
    assert result["charge_amount"] == Decimal("300.00")


def test_class_1a_termination_charges_only_excess_above_threshold(db, organization):
    _seed_class_1a_termination(db, organization.id)
    result = service.calculate_uk_class_1a_1b_charge(db, organization.id, "TERMINATION_AWARDS", Decimal("40000"), as_of=date(2026, 6, 1))
    assert result["eligible"] is True
    # (40000-30000) * 15% = 1500.00
    assert result["charge_amount"] == Decimal("1500.00")


def test_class_1a_termination_below_threshold_is_zero(db, organization):
    _seed_class_1a_termination(db, organization.id)
    result = service.calculate_uk_class_1a_1b_charge(db, organization.id, "TERMINATION_AWARDS", Decimal("20000"), as_of=date(2026, 6, 1))
    assert result["eligible"] is True
    assert result["charge_amount"] == Decimal("0")


def test_class_1a_fails_closed_when_rate_unconfigured(db, organization):
    result = service.calculate_uk_class_1a_1b_charge(db, organization.id, "BENEFITS", Decimal("2000"), as_of=date(2026, 6, 1))
    assert result["eligible"] is False
    assert "not configured" in result["reason"]


def test_unknown_charge_type_raises(db, organization):
    with pytest.raises(BadRequestException):
        service.calculate_uk_class_1a_1b_charge(db, organization.id, "NOT_REAL", Decimal("2000"))


# ── Connected-employer Employment Allowance sharing (ZP-TAX-UK-2026-27- ─
# 001 §14 gap-closure Part 7B, 2026-09-09) ───────────────────────────────

def _make_connected_org(db, code, org_code="TESTORG2"):
    from app.modules.organizations.models import Organization
    org = Organization(organization_name="Second Org", organization_code=org_code, connected_group_code=code)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_ungrouped_org_behaves_exactly_as_before(db, organization):
    # No connected_group_code set — group total must equal this org's own.
    _seed_employment_allowance_cap(db, organization.id)
    _seed_employer_ni_accumulator(db, organization.id, "UK-TY-2026-27", Decimal("8000"))
    result = service.calculate_uk_employment_allowance(db, organization.id, employer_has_claimed=True, as_of=date(2026, 6, 1))
    assert result["connected_group_code"] is None
    assert result["group_cumulative_employer_ni"] == Decimal("8000")
    assert result["net_liability"] == Decimal("0")
    assert result["allowance_remaining"] == Decimal("2500.00")


def test_connected_group_shares_one_cap_instead_of_one_each(db, organization):
    other = _make_connected_org(db, "GROUP-A")
    organization.connected_group_code = "GROUP-A"
    db.commit()

    _seed_employment_allowance_cap(db, organization.id)
    # £8,000 + £6,000 = £14,000 combined — above the shared £10,500 cap,
    # even though NEITHER org alone exceeds it.
    _seed_employer_ni_accumulator(db, organization.id, "UK-TY-2026-27", Decimal("8000"))
    _seed_employer_ni_accumulator(db, other.id, "UK-TY-2026-27", Decimal("6000"))

    result = service.calculate_uk_employment_allowance(db, organization.id, employer_has_claimed=True, as_of=date(2026, 6, 1))
    assert result["group_cumulative_employer_ni"] == Decimal("14000")
    assert result["cumulative_employer_ni"] == Decimal("8000")
    # Group net liability = 14000 - 10500 = 3500; this org's share = 8000/14000.
    assert result["net_liability"] == Decimal("2000.00")


def test_connected_group_proportional_split_sums_to_group_total(db, organization):
    other = _make_connected_org(db, "GROUP-B")
    organization.connected_group_code = "GROUP-B"
    db.commit()

    _seed_employment_allowance_cap(db, organization.id)
    _seed_employment_allowance_cap(db, other.id)
    _seed_employer_ni_accumulator(db, organization.id, "UK-TY-2026-27", Decimal("8000"))
    _seed_employer_ni_accumulator(db, other.id, "UK-TY-2026-27", Decimal("6000"))

    result_a = service.calculate_uk_employment_allowance(db, organization.id, employer_has_claimed=True, as_of=date(2026, 6, 1))
    result_b = service.calculate_uk_employment_allowance(db, other.id, employer_has_claimed=True, as_of=date(2026, 6, 1))
    assert result_a["net_liability"] + result_b["net_liability"] == Decimal("3500.00")


def test_connected_group_below_cap_leaves_both_members_with_no_liability(db, organization):
    other = _make_connected_org(db, "GROUP-C")
    organization.connected_group_code = "GROUP-C"
    db.commit()

    _seed_employment_allowance_cap(db, organization.id)
    _seed_employer_ni_accumulator(db, organization.id, "UK-TY-2026-27", Decimal("3000"))
    _seed_employer_ni_accumulator(db, other.id, "UK-TY-2026-27", Decimal("2000"))

    result = service.calculate_uk_employment_allowance(db, organization.id, employer_has_claimed=True, as_of=date(2026, 6, 1))
    assert result["group_cumulative_employer_ni"] == Decimal("5000")
    assert result["eligible"] is True
    assert result["net_liability"] == Decimal("0")
