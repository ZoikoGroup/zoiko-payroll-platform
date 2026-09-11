"""
tests/test_ca_associated_employer_group.py
---------------------------------------------
Coverage for Canada's associated-employer-group exemption sharing
(ZP-TAX-CA-2026-001 §15, gap-closure Phase 6, 2026-09-11) — Ontario EHT /
BC EHT / Manitoba HE Levy / NL HAPSET's "associated employers share
exemption." Reuses the exact same Organization.connected_group_code +
_connected_group_member_ids/_sum_org_ytd_component_across_orgs mechanism
UK's Apprenticeship Levy sharing already established and tests (see
test_uk_apprenticeship_levy_accumulator.py), gated behind the NEW
_CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES switch (on top of the pre-existing,
still-off _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, EmployerTaxProfile
import app.modules.payroll.engine.countries.shared as shared


@pytest.fixture(autouse=True)
def _restore_ca_group_switches():
    original_org_levy = set(shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES)
    original_group = set(shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES)
    yield
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.update(original_org_levy)
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.clear()
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.update(original_group)


def _make_connected_org(db, code, org_code="CAGRP2"):
    from app.modules.organizations.models import Organization
    org = Organization(organization_name="CA Group Org", organization_code=org_code, connected_group_code=code)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


# ── _ca_org_levy_read_inputs: group-aware summation ──────────────────────

def test_on_eht_ungrouped_org_unaffected(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.add("CA")
    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 5, 1), {"on_eht": Decimal("500000")})
    db.commit()
    inputs = service._ca_org_levy_read_inputs(db, organization.id, date(2026, 6, 1), "ON")
    assert inputs["on_eht_ytd_remuneration_before"] == Decimal("500000")


def test_on_eht_summed_across_connected_group_when_switch_on(db, organization):
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.add("CA")
    other = _make_connected_org(db, "CA-GROUP-A")
    organization.connected_group_code = "CA-GROUP-A"
    db.commit()

    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 5, 1), {"on_eht": Decimal("600000")})
    service._upsert_ca_org_levy_ytd(db, other.id, date(2026, 5, 1), {"on_eht": Decimal("700000")})
    db.commit()

    # Both members must see the SAME combined group total, not just their
    # own contribution — mirrors UK's identical test for the Apprenticeship
    # Levy pay bill.
    inputs_a = service._ca_org_levy_read_inputs(db, organization.id, date(2026, 6, 1), "ON")
    inputs_b = service._ca_org_levy_read_inputs(db, other.id, date(2026, 6, 1), "ON")
    assert inputs_a["on_eht_ytd_remuneration_before"] == Decimal("1300000")
    assert inputs_b["on_eht_ytd_remuneration_before"] == Decimal("1300000")


def test_on_eht_group_summation_dormant_when_switch_off(db, organization):
    # _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES on, but _CA_ASSOCIATED_
    # GROUP_ENABLED_COUNTRIES off — group summation must NOT kick in even
    # though the org has a connected_group_code set.
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.discard("CA")  # simulate the switch OFF
    other = _make_connected_org(db, "CA-GROUP-B", org_code="CAGRP3")
    organization.connected_group_code = "CA-GROUP-B"
    db.commit()

    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 5, 1), {"on_eht": Decimal("600000")})
    service._upsert_ca_org_levy_ytd(db, other.id, date(2026, 5, 1), {"on_eht": Decimal("700000")})
    db.commit()

    inputs_a = service._ca_org_levy_read_inputs(db, organization.id, date(2026, 6, 1), "ON")
    assert inputs_a["on_eht_ytd_remuneration_before"] == Decimal("600000")  # own total only


def test_qc_hsf_never_group_summed_even_when_switch_on(db, organization):
    # §15's associated-employer sharing rule does NOT extend to Quebec
    # HSF (its own sliding-rate mechanism has no such provision in the
    # document) — must stay per-org even with the switch on.
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.add("CA")
    other = _make_connected_org(db, "CA-GROUP-C", org_code="CAGRP4")
    organization.connected_group_code = "CA-GROUP-C"
    db.commit()

    service._upsert_ca_org_levy_ytd(db, organization.id, date(2026, 5, 1), {"qc_hsf": Decimal("400000")})
    service._upsert_ca_org_levy_ytd(db, other.id, date(2026, 5, 1), {"qc_hsf": Decimal("900000")})
    db.commit()

    inputs_a = service._ca_org_levy_read_inputs(db, organization.id, date(2026, 6, 1), "QC")
    assert inputs_a["qc_hsf_ytd_remuneration_before"] == Decimal("400000")  # own total only, not 1,300,000


# ── canada.py: exemption-allocation scaling ───────────────────────────────

@dataclass
class _ProfileStub:
    employer_rate_pct: Optional[Decimal] = None


def test_ca_apply_levy_exemption_allocation_dormant_by_default():
    from app.modules.payroll.engine.countries.canada import _ca_apply_levy_exemption_allocation
    from app.modules.payroll.engine.base import PayrollContext

    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.discard("CA")  # simulate the switch OFF
    ctx = PayrollContext(gross=Decimal("1000"), basic=Decimal("1000"), country="CA")
    # Switch off entirely -> full exemption passed through unchanged,
    # even if (hypothetically) a profile existed.
    ctx.employer_tax_profiles = {"ON_EHT_EXEMPTION_ALLOCATION_PCT": _ProfileStub(employer_rate_pct=Decimal("40"))}
    result = _ca_apply_levy_exemption_allocation(Decimal("1000000"), ctx, "ON_EHT_EXEMPTION_ALLOCATION_PCT")
    assert result == Decimal("1000000")


def test_ca_apply_levy_exemption_allocation_defaults_to_full_when_unconfigured():
    from app.modules.payroll.engine.countries.canada import _ca_apply_levy_exemption_allocation
    from app.modules.payroll.engine.base import PayrollContext

    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.add("CA")
    ctx = PayrollContext(gross=Decimal("1000"), basic=Decimal("1000"), country="CA")
    result = _ca_apply_levy_exemption_allocation(Decimal("1000000"), ctx, "ON_EHT_EXEMPTION_ALLOCATION_PCT")
    assert result == Decimal("1000000")


def test_ca_apply_levy_exemption_allocation_scales_by_configured_share():
    from app.modules.payroll.engine.countries.canada import _ca_apply_levy_exemption_allocation
    from app.modules.payroll.engine.base import PayrollContext

    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.add("CA")
    ctx = PayrollContext(gross=Decimal("1000"), basic=Decimal("1000"), country="CA")
    ctx.employer_tax_profiles = {"ON_EHT_EXEMPTION_ALLOCATION_PCT": _ProfileStub(employer_rate_pct=Decimal("40"))}
    result = _ca_apply_levy_exemption_allocation(Decimal("1000000"), ctx, "ON_EHT_EXEMPTION_ALLOCATION_PCT")
    assert result == Decimal("400000.00")


def test_ca_apply_levy_exemption_allocation_end_to_end_via_calculate():
    # Full round-trip through calculate(): two "employers" (simulated via
    # two calls) sharing one $1,000,000 exemption 60/40 — the 40% member
    # gets $400,000 of exemption applied against the SAME group-wide
    # remuneration-before figure, materially different from getting the
    # full $1,000,000 it would see standalone. YTD-before is deliberately
    # placed BETWEEN the two exemption levels (900,000): with the full
    # $1,000,000 exemption neither before nor after this period crosses
    # it (period EHT = $0), but with only a $400,000 allocated share both
    # points are already well past it (period EHT > $0) — a flat
    # exemption that applies identically to both "before" and "after"
    # otherwise cancels out of the INCREMENTAL amount entirely, so the
    # test must straddle the exemption boundary to actually prove the
    # allocation changes anything.
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.standard import StandardStrategy

    shared._CA_ASSOCIATED_GROUP_ENABLED_COUNTRIES.add("CA")
    strategy = StandardStrategy()
    eht_bands = [{"min_amount": Decimal("0"), "max_amount": None, "rate_pct": Decimal("1.95"), "rule_type": "ON_EHT_BAND"}]
    from dataclasses import dataclass as _dc

    @_dc
    class _Slab:
        min_amount: Decimal
        max_amount: Optional[Decimal]
        rate_pct: Decimal
        rule_type: str = "ON_EHT_BAND"

    @_dc
    class _Rate:
        flat_amount: Optional[Decimal] = None
        employee_rate_pct: Optional[Decimal] = None
        employer_rate_pct: Optional[Decimal] = None

    state_slabs = [_Slab(Decimal("0"), None, Decimal("1.95"))]
    state_rate_map = {"on_eht_exemption": _Rate(flat_amount=Decimal("1000000"))}

    ctx_40pct_share = PayrollContext(
        gross=Decimal("50000"), basic=Decimal("50000"), country="CA", work_state="ON",
        state_slabs=state_slabs, state_rate_map=state_rate_map,
        on_eht_ytd_remuneration_before=Decimal("900000"),
        employer_tax_profiles={"ON_EHT_EXEMPTION_ALLOCATION_PCT": _ProfileStub(employer_rate_pct=Decimal("40"))},
    )
    result_40pct = strategy.calculate(ctx_40pct_share)
    # Full exemption (unconfigured) case, same inputs otherwise, for comparison.
    ctx_full_exemption = PayrollContext(
        gross=Decimal("50000"), basic=Decimal("50000"), country="CA", work_state="ON",
        state_slabs=state_slabs, state_rate_map=state_rate_map,
        on_eht_ytd_remuneration_before=Decimal("900000"),
    )
    result_full = strategy.calculate(ctx_full_exemption)
    # Full $1,000,000 exemption: 900,000 and 950,000 both stay under it ->
    # $0 EHT this period. 40% ($400,000) share: both points are already
    # past it -> real EHT owed. Exact expected value: (950000-400000)*
    # 1.95% - (900000-400000)*1.95% = 50000*1.95% = 975.00.
    assert result_full.employer_eht == Decimal("0")
    assert result_40pct.employer_eht == Decimal("975.00")
