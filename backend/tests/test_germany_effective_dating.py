"""
tests/test_germany_effective_dating.py
-----------------------------------------
Phase 8BI (P1) — effective-dating architecture/correctness coverage for
Germany's statutory registries (contribution ceilings, PV configuration,
health funds) that had zero direct resolver-level test coverage before
this phase, despite each one implementing the identical "resolve the
PUBLISHED row whose [effective_from, effective_to] window covers a given
date, most-recent-first, never raise" contract.

Scope note (per this phase's own explicit instruction — "do not
introduce current statutory numbers without authoritative source
evidence, do not fabricate missing German statutory values"): every rate
value here is an arbitrary test fixture number, not a real 2026/2027
statutory rate. This file tests SELECTION ARCHITECTURE (which row wins
for a given date), never statutory correctness of the numbers themselves
(that is covered elsewhere, e.g. test_germany_e2e_payroll_scenario.py,
against the documented spec-cited values).

Known, NOT closed by this phase (see the phase report's own "Effective
dating" section for the full design proposal): RV/ALV/GKV *general*
contribution rates and Minijob/Midijob thresholds still resolve through
`ContributionRate`/hardcoded_defaults.py constants with NO effective
dating at all, unlike the three registries tested here. Adding effective
dating to `ContributionRate` would be a cross-jurisdiction schema change
(it backs every country's rates, not just Germany's) — explicitly left
as a documented design proposal, not implemented in this phase, per the
phase's own instruction to stop and explain before any migration whose
semantics/blast-radius aren't narrowly scoped.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import SourceArtifact
from app.modules.payroll.schemas import (
    GermanyContributionCeilingCreate, GermanyHealthFundCreate, GermanyPvConfigurationCreate,
)


def _make_source(db):
    source = SourceArtifact(agency="Test Fixture", title="Effective-dating test source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_ceiling(db, branch, monthly, annual, effective_from, effective_to=None, auto_close_previous=True, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_contribution_ceiling_record(
        db, GermanyContributionCeilingCreate(
            branch=branch, monthly_ceiling=monthly, annual_ceiling=annual,
            effective_from=effective_from, effective_to=effective_to, authority_source_id=source.id,
        ), actor_id=maker, auto_close_previous=auto_close_previous,
    )
    row = service.set_contribution_ceiling_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_contribution_ceiling_approver(db, row.id, actor_id=checker)
    return service.set_contribution_ceiling_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_pv_configuration(db, child_category, effective_from, effective_to=None, is_saxony=False, auto_close_previous=True, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_pv_configuration_record(
        db, GermanyPvConfigurationCreate(
            child_category=child_category, is_saxony=is_saxony,
            total_rate_pct=Decimal("4.2000"), standard_employee_rate_pct=Decimal("2.4000"),
            employer_rate_pct=Decimal("1.8000"), saxony_employee_rate_pct=Decimal("2.9000"),
            saxony_employer_rate_pct=Decimal("1.3000"),
            effective_from=effective_from, effective_to=effective_to, authority_source_id=source.id,
        ), actor_id=maker, auto_close_previous=auto_close_previous,
    )
    row = service.set_pv_configuration_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_pv_configuration_approver(db, row.id, actor_id=checker)
    return service.set_pv_configuration_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_health_fund(db, health_fund_id, rate, effective_from, effective_to=None, auto_close_previous=True, maker=1, checker=2):
    source = _make_source(db)
    row = service.create_health_fund_record(
        db, GermanyHealthFundCreate(
            health_fund_id=health_fund_id, fund_name="Test Fund (fixture)",
            supplementary_rate_pct=rate, effective_from=effective_from, effective_to=effective_to,
            authority_source_id=source.id,
        ), actor_id=maker, auto_close_previous=auto_close_previous,
    )
    row = service.set_health_fund_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_health_fund_approver(db, row.id, actor_id=checker)
    return service.set_health_fund_status(db, row.id, "PUBLISHED", actor_id=checker)


# ══════════════════════════════════════════════════════════════════════════
# GermanyContributionCeiling — the primary registry exercised across every
# required scenario (historical/current/future/boundary/overlap/no-match/
# deterministic); PV configuration and health fund get one confirming test
# each, since all three resolvers share the identical query shape.
# ══════════════════════════════════════════════════════════════════════════

class TestContributionCeilingEffectiveDating:
    def _three_tier_setup(self, db):
        """v1 (historical, closed): 2025-01-01..2025-12-31
        v2 (current, auto-closed by v3's creation): 2026-01-01..2027-05-31
        v3 (future-dated at creation time, becomes current later): 2027-06-01..open"""
        v1 = _publish_ceiling(db, "RV_ALV", Decimal("8000.00"), Decimal("96000.00"), date(2025, 1, 1), date(2025, 12, 31))
        v2 = _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"), date(2026, 1, 1))
        v3 = _publish_ceiling(db, "RV_ALV", Decimal("8700.00"), Decimal("104400.00"), date(2027, 6, 1))
        return v1, v2, v3

    def test_historical_rate_selection(self, db):
        v1, v2, v3 = self._three_tier_setup(db)
        resolved = service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2025, 6, 15))
        assert resolved.id == v1.id
        assert resolved.monthly_ceiling == Decimal("8000.00")

    def test_current_rate_selection(self, db):
        v1, v2, v3 = self._three_tier_setup(db)
        resolved = service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2026, 6, 15))
        assert resolved.id == v2.id

    def test_future_rate_does_not_leak_backward_before_its_own_window(self, db):
        """A future-dated PUBLISHED row must never resolve for a date
        BEFORE its own effective_from, even though it exists in the DB —
        the still-current row must win instead."""
        v1, v2, v3 = self._three_tier_setup(db)
        resolved = service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2027, 1, 1))
        assert resolved.id == v2.id  # NOT v3 — v3 doesn't start until 2027-06-01

    def test_future_dated_row_applies_once_its_own_window_starts(self, db):
        v1, v2, v3 = self._three_tier_setup(db)
        resolved = service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2027, 6, 1))
        assert resolved.id == v3.id
        resolved_later = service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2030, 1, 1))
        assert resolved_later.id == v3.id  # open-ended: still applies arbitrarily far in the future

    def test_boundary_date_at_exact_transition_selects_the_new_row(self, db):
        v1, v2, v3 = self._three_tier_setup(db)
        # v1's last day (inclusive end boundary)
        assert service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2025, 12, 31)).id == v1.id
        # The very next day — v2's first day (inclusive start boundary) —
        # must flip to v2, not still resolve v1.
        assert service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2026, 1, 1)).id == v2.id

    def test_overlapping_effective_periods_are_rejected_at_creation(self, db):
        """The registry must prevent an ambiguous state from ever being
        created — resolution can only be deterministic if overlaps are
        refused up front, not resolved by some tie-breaking rule at
        query time."""
        _publish_ceiling(db, "RV_ALV", Decimal("8000.00"), Decimal("96000.00"), date(2025, 1, 1), date(2025, 12, 31))
        with pytest.raises(BadRequestException, match="overlaps existing"):
            _publish_ceiling(
                db, "RV_ALV", Decimal("8100.00"), Decimal("97200.00"),
                date(2025, 6, 1), date(2025, 8, 31), auto_close_previous=False,
            )

    def test_no_matching_rate_returns_none_not_an_exception(self, db):
        self._three_tier_setup(db)
        # Before any published row's window even begins.
        assert service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2020, 1, 1)) is None
        # A branch with no published rows at all.
        assert service.resolve_germany_contribution_ceiling(db, "GKV_PV", as_of=date(2026, 1, 1)) is None

    def test_resolution_is_deterministic_across_repeated_calls(self, db):
        v1, v2, v3 = self._three_tier_setup(db)
        first = service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2026, 6, 15))
        second = service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2026, 6, 15))
        assert first.id == second.id == v2.id

    def test_branches_are_never_conflated(self, db):
        """RV_ALV and GKV_PV are independent identities — publishing one
        must never affect resolution of the other."""
        rv_alv = _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"), date(2026, 1, 1))
        gkv_pv = _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"), date(2026, 1, 1))
        assert service.resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=date(2026, 3, 1)).id == rv_alv.id
        assert service.resolve_germany_contribution_ceiling(db, "GKV_PV", as_of=date(2026, 3, 1)).id == gkv_pv.id


# ══════════════════════════════════════════════════════════════════════════
# PV configuration and health fund — same resolver shape, one confirming
# scenario each (historical vs. current) rather than repeating the full
# matrix already proven above.
# ══════════════════════════════════════════════════════════════════════════

def test_pv_configuration_resolves_by_effective_date(db):
    old = _publish_pv_configuration(db, "CHILDLESS", date(2025, 1, 1), date(2025, 12, 31))
    new = _publish_pv_configuration(db, "CHILDLESS", date(2026, 1, 1))
    assert service.resolve_germany_pv_configuration(db, "CHILDLESS", is_saxony=False, as_of=date(2025, 6, 1)).id == old.id
    assert service.resolve_germany_pv_configuration(db, "CHILDLESS", is_saxony=False, as_of=date(2026, 6, 1)).id == new.id
    assert service.resolve_germany_pv_configuration(db, "CHILDLESS", is_saxony=False, as_of=date(2020, 1, 1)) is None


def test_health_fund_resolves_by_effective_date(db):
    old = _publish_health_fund(db, "EFF-DATE-FUND", Decimal("1.5000"), date(2025, 1, 1), date(2025, 12, 31))
    new = _publish_health_fund(db, "EFF-DATE-FUND", Decimal("1.7000"), date(2026, 1, 1))
    assert service.resolve_germany_health_fund(db, "EFF-DATE-FUND", as_of=date(2025, 6, 1)).id == old.id
    assert service.resolve_germany_health_fund(db, "EFF-DATE-FUND", as_of=date(2026, 6, 1)).id == new.id
    assert service.resolve_germany_health_fund(db, "NEVER-PUBLISHED-FUND", as_of=date(2026, 6, 1)) is None
