"""
tests/test_germany_overtime_edge_cases.py
-------------------------------------------
Closing-out P2 gap coverage for the Germany overtime/shift-premium
subsystem (classifier.py, wage_tax.py, social_insurance.py,
premium_component.py under
engine/jurisdictions/germany/overtime/) — scenarios confirmed NOT covered
by test_germany_overtime.py / test_germany_overtime_tax_delta.py:

1. Night + Sunday concurrence (same physical segment tagged with BOTH
   categories) — proves the architecture and proves the two premium
   percentages genuinely SUM (R 3b Abs. 3 LStH's verified concurrence
   rule already coded in wage_tax.py/social_insurance.py), not max()'d,
   not first-picked. Includes a dedicated DST spring-forward variant.
2. Night+holiday, Sunday+holiday, Night+Sunday+holiday. A national-holiday
   REGISTRY genuinely exists in this codebase (PayrollHoliday,
   category="National", queried directly by classifier.py's
   `_is_safe_national_de_holiday`) — this is NOT a Land-specific holiday
   invention, it is the codebase's own already-implemented, already-used
   mechanism (the same one behind the seeded New Year's/Good Friday/etc.
   national defaults). These tests seed one PayrollHoliday row directly
   (an isolated per-test SQLite DB — see conftest.py) and exercise the
   REAL classification + wage-tax + social-insurance calculation chain.
   Night+Holiday hits the same verified one-night+one-other concurrence
   rule as Night+Sunday (SUMMED). Sunday+Holiday (no night) and the 3-way
   Night+Sunday+Holiday combination are NOT covered by the verified R 3b
   LStH text — wage_tax.py/social_insurance.py deliberately fail closed
   (STATUTORY_RULE_UNRESOLVED) for both; these tests prove that real,
   already-implemented fail-closed behavior end to end through to a
   blocked attachment, never a fabricated amount.
3. Missing Grundlohn (EmployeeStatutoryProfile.de_grundlohn_hourly absent
   or None) for an employee with real overtime hours — zero test coverage
   confirmed before this file. Proves the actual, already-implemented
   behavior: INSUFFICIENT_DATA on both the wage-tax and social-insurance
   calculation, NONE on the combined premium component, and a rejected
   attach — a genuinely fail-closed chain, NOT a defect (no source change
   made; see the final report for this finding).
4. Two real GermanyOvertimeWorkRecord rows for one employee, taken through
   the REAL classify -> wage-tax -> social-insurance -> premium-component
   -> attach pipeline (not hand-built components), proving the sums land
   on the payslip without double-counting.
5. Detach + recalculate via the REAL service.regenerate_employee_payslip
   (not the piecewise simulation test_germany_overtime_tax_delta.py's own
   test_recalculation_preserves_overtime_tax_deltas uses) against a REAL
   service.create_payroll_run-generated payslip — proves net pay returns
   to exactly its pre-overtime base figure with exactly one payslip row
   (updated in place, never duplicated).

Fixture conventions follow test_germany_overtime.py (direct PayrollEmployee/
GermanyOvertimePremiumComponent construction, bare PayslipItem where a full
payroll run isn't needed) and test_germany_overtime_tax_delta.py, plus — for
the one scenario that genuinely needs a full payroll run (#5) — the same
maker-checker registry-publishing pattern already proven in
test_germany_full_business_acceptance.py (kept self-contained here rather
than importing across test files).
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.engine.jurisdictions.germany.overtime.classifier import build_time_segments
from app.modules.payroll.models import (
    EmployeeStatutoryProfile, GermanyOvertimePremiumComponent, PayrollAttendanceRecord,
    PayrollEmployee, PayrollHoliday, PayrollRun, PayslipAllowanceItem, PayslipItem, SourceArtifact,
)
from app.modules.payroll.schemas import (
    EmployeeCreate, EmployeeStatutoryProfileCreate, GermanyContributionCeilingCreate,
    GermanyHealthFundCreate, GermanyOvertimeGrundlohnCapCreate,
    GermanyOvertimePremiumCategoryCreate, GermanyOvertimeWorkRecordCreate,
    GermanyPvConfigurationCreate, PayrollRunCreate,
)

BERLIN = ZoneInfo("Europe/Berlin")


# ═══════════════════════════════════════════════════════════════════════
# Shared fixture helpers — same shapes as test_germany_overtime.py /
# test_germany_overtime_tax_delta.py.
# ═══════════════════════════════════════════════════════════════════════

class _FakeWorkRecord:
    def __init__(self, start, end):
        self.start_datetime = start
        self.end_datetime = end


def _make_employee(db, org_id, code="DE-OT-EDGE-01"):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code="DE", ctc=72000, basic=6000, hra=0, status="Active",
        date_of_joining=date(2026, 1, 1),
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_profile(db, emp, org_id, de_grundlohn_hourly, effective_from=date(2026, 1, 1)):
    profile = EmployeeStatutoryProfile(
        organization_id=org_id, employee_id=emp.id, country_code="DE",
        effective_from=effective_from, de_grundlohn_hourly=de_grundlohn_hourly,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _make_bare_run(db, org_id, period_start=date(2026, 1, 1)):
    run = PayrollRun(
        organization_id=org_id, period_label="Jan 2026", period_start=period_start,
        period_end=date(2026, 1, 31), pay_date=date(2026, 2, 1), status="Draft",
        calculation_mode="standard",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _make_bare_payslip_item(db, run, emp, org_id):
    item = PayslipItem(
        payroll_run_id=run.id, employee_id=emp.id, organization_id=org_id,
        employee_name=emp.name, gross_pay=Decimal("0.00"), total_deductions=Decimal("0.00"),
        net_pay=Decimal("0.00"), pf=Decimal("0.00"), esi=Decimal("0.00"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _make_work_record(db, emp, org_id, start, end, hours=Decimal("2.00"), approval="APPROVED"):
    row = service.create_germany_overtime_work_record(
        db, emp.id, org_id,
        GermanyOvertimeWorkRecordCreate(
            work_date=start.date(), start_datetime=start, end_datetime=end,
            hours=hours, entry_source="MANUAL",
        ),
        actor_id=1,
    )
    if approval and row.hr_approval_status != approval:
        row = service.set_germany_overtime_work_record_approval(db, row.id, org_id, approval, actor_id=1)
    return row


def _classify(db, org_id, work_record, tz=BERLIN):
    """Real classification through the service layer. SQLite's
    DateTime(timezone=True) doesn't preserve tzinfo across a commit/refresh
    (see test_germany_overtime.py's own note on this) — the work_record
    object is still the SAME identity-mapped Python object at this point
    (no intervening commit after this reassignment), so restoring the
    ORIGINAL tzinfo here reproduces the exact aware datetime this record
    was created with, exactly like every other test in this suite that
    calls the real classifier through the service layer."""
    work_record.start_datetime = work_record.start_datetime.replace(tzinfo=tz)
    work_record.end_datetime = work_record.end_datetime.replace(tzinfo=tz)
    return service.classify_and_list_germany_overtime_time_segments(db, work_record.id, org_id, actor_id=1)


def _seed_national_holiday(db, org_id, on_date, name="TEST_FIXTURE_NATIONAL_HOLIDAY"):
    """Seeds one PayrollHoliday row via the SAME category="National"
    mechanism classifier.py's `_is_safe_national_de_holiday` already reads
    for HOLIDAY_STANDARD (see that function + the classifier module's own
    docstring on why only category="National" is trusted). This is NOT a
    new/invented holiday concept — it is this codebase's existing,
    already-wired national-holiday registry; only the row's own date is a
    test fixture value, not a real German public holiday."""
    row = PayrollHoliday(organization_id=org_id, country="DE", category="National", date=on_date, name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _publish_overtime_category(db, category_code, pct, maker=1, checker=2):
    source = SourceArtifact(agency="Test Fixture", title=f"{category_code} rate", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    row = service.create_overtime_premium_category_record(
        db, GermanyOvertimePremiumCategoryCreate(
            category_code=category_code, wage_tax_free_pct=Decimal(pct),
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_overtime_premium_category_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_overtime_premium_category_approver(db, row.id, actor_id=checker)
    return service.set_overtime_premium_category_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_overtime_grundlohn_cap(db, dimension, amount, maker=1, checker=2):
    source = SourceArtifact(agency="Test Fixture", title=f"{dimension} cap", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    row = service.create_overtime_grundlohn_cap_record(
        db, GermanyOvertimeGrundlohnCapCreate(
            dimension=dimension, hourly_cap_amount=Decimal(amount),
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_overtime_grundlohn_cap_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_overtime_grundlohn_cap_approver(db, row.id, actor_id=checker)
    return service.set_overtime_grundlohn_cap_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_all_overtime_registries(db):
    """The real, verified 2026 rates (scripts/seed_germany_2026_registries.py's
    own _OVERTIME_PREMIUM_CATEGORY_MATRIX / _OVERTIME_GRUNDLOHN_CAP_MATRIX) —
    never a hand-invented percentage."""
    _publish_overtime_category(db, "NIGHT_STANDARD", "25.00")
    _publish_overtime_category(db, "NIGHT_EXTENDED", "40.00")
    _publish_overtime_category(db, "SUNDAY", "50.00")
    _publish_overtime_category(db, "HOLIDAY_STANDARD", "125.00")
    _publish_overtime_category(db, "HOLIDAY_SPECIAL", "150.00")
    _publish_overtime_grundlohn_cap(db, "WAGE_TAX", "50.00")
    _publish_overtime_grundlohn_cap(db, "SOCIAL_INSURANCE", "25.00")


# ═══════════════════════════════════════════════════════════════════════
# 1. Night + Sunday concurrence — architecture + real percentage stacking.
# ═══════════════════════════════════════════════════════════════════════

def test_classifier_saturday_night_crossing_into_sunday_produces_concurrent_categories(db):
    """A single physical time range can carry BOTH a night tag and a
    Sunday tag simultaneously — proven by the classifier emitting two
    dict rows (one per category) sharing the identical segment_start/
    segment_end, which wage_tax.py's own _group_segments_by_physical_range
    then groups back together. Not a single "categories" list field on
    one row — multiple rows over the same physical range, by design (see
    classifier.py's own docstring: "never sums or max()'s... emits one
    segment row per applicable category over the same physical time
    range")."""
    # 2026-01-03 is a Saturday; 2026-01-04 is a Sunday.
    start = datetime(2026, 1, 3, 22, 0, tzinfo=BERLIN)
    end = datetime(2026, 1, 4, 6, 0, tzinfo=BERLIN)
    segments = build_time_segments(db, _FakeWorkRecord(start, end))

    grouped = {}
    for s in segments:
        grouped.setdefault((s["segment_start"], s["segment_end"]), set()).add(s["premium_category"])
    ranges = sorted(grouped)
    assert len(ranges) == 3

    # 22:00 Sat -> 00:00 Sun: Saturday night only, not yet Sunday.
    assert grouped[ranges[0]] == {"NIGHT_STANDARD"}
    # 00:00 -> 04:00 Sun: NIGHT_EXTENDED (began before midnight) + SUNDAY,
    # concurrently, on the identical physical range.
    assert grouped[ranges[1]] == {"NIGHT_EXTENDED", "SUNDAY"}
    # 04:00 -> 06:00 Sun: NIGHT_STANDARD + SUNDAY, concurrently.
    assert grouped[ranges[2]] == {"NIGHT_STANDARD", "SUNDAY"}


def test_classifier_night_sunday_concurrence_across_dst_spring_forward_uses_real_elapsed_hours(db):
    """2026-03-29 is the DST spring-forward Sunday (02:00 CET jumps
    directly to 03:00 CEST — that hour never happens). The classifier's
    own docstring documents a discovered CPython same-tzinfo subtraction
    bug this module works around via _seconds_between's UTC-normalized
    subtraction; this test proves that fix on a genuine Night+Sunday
    concurrent segment straddling the gap: the wall-clock 00:00-04:00
    window is only 3 REAL hours, not 4."""
    start = datetime(2026, 3, 28, 22, 0, tzinfo=BERLIN)   # Saturday, before the gap
    end = datetime(2026, 3, 29, 6, 0, tzinfo=BERLIN)      # Sunday, after the gap
    segments = build_time_segments(db, _FakeWorkRecord(start, end))

    grouped = {}
    for s in segments:
        key = (s["segment_start"], s["segment_end"])
        grouped.setdefault(key, {"categories": set(), "hours": s["hours"]})
        grouped[key]["categories"].add(s["premium_category"])
    ranges = sorted(grouped)
    assert len(ranges) == 3

    pre_midnight, spanning_gap, post_gap = (grouped[r] for r in ranges)
    assert pre_midnight["categories"] == {"NIGHT_STANDARD"}
    assert pre_midnight["hours"] == Decimal("2")

    # The gap-spanning segment: NIGHT_EXTENDED + SUNDAY concurrently, and
    # genuinely only 3 elapsed hours across the spring-forward jump.
    assert spanning_gap["categories"] == {"NIGHT_EXTENDED", "SUNDAY"}
    assert spanning_gap["hours"] == Decimal("3")

    assert post_gap["categories"] == {"NIGHT_STANDARD", "SUNDAY"}
    assert post_gap["hours"] == Decimal("2")


def test_night_sunday_concurrence_sums_wage_tax_and_si_percentages_end_to_end(db, organization):
    """End-to-end through the REAL classify -> wage-tax -> social-insurance
    -> premium-component chain: proves the two premium percentages
    genuinely SUM (R 3b Abs. 3 LStH's verified rule), not max()'d/
    first-picked, with real Euro amounts."""
    _publish_all_overtime_registries(db)
    emp = _make_employee(db, organization.id, code="DE-OT-EDGE-NSUN")
    _make_profile(db, emp, organization.id, de_grundlohn_hourly=Decimal("80.00"))

    start = datetime(2026, 1, 3, 22, 0, tzinfo=BERLIN)
    end = datetime(2026, 1, 4, 6, 0, tzinfo=BERLIN)
    wr = _make_work_record(db, emp, organization.id, start, end, hours=Decimal("8.00"))
    _classify(db, organization.id, wr)

    wage_tax_results = service.calculate_and_list_germany_overtime_wage_tax(db, wr.id, organization.id, actor_id=1)
    si_results = service.calculate_and_list_germany_overtime_social_insurance(db, wr.id, organization.id, actor_id=1)
    assert len(wage_tax_results) == 3
    assert all(r.calculation_status == "CALCULATED" for r in wage_tax_results)
    assert all(r.calculation_status == "CALCULATED" for r in si_results)

    single = [r for r in wage_tax_results if r.concurrent_category_code is None]
    assert len(single) == 1
    assert single[0].primary_category_code == "NIGHT_STANDARD"
    assert single[0].combined_tax_free_pct == Decimal("25.00")
    assert single[0].gross_qualifying_premium_amount == Decimal("40.00")     # 0.25 * 80 * 2h
    assert single[0].tax_free_premium_amount == Decimal("25.00")            # 0.25 * 50(cap) * 2h
    assert single[0].taxable_premium_amount == Decimal("15.00")

    concurrent_by_primary = {r.primary_category_code: r for r in wage_tax_results if r.concurrent_category_code is not None}
    assert set(concurrent_by_primary) == {"NIGHT_EXTENDED", "NIGHT_STANDARD"}

    extended = concurrent_by_primary["NIGHT_EXTENDED"]
    assert extended.concurrent_category_code == "SUNDAY"
    assert extended.combined_tax_free_pct == Decimal("90.00")               # 40 + 50, summed
    assert extended.gross_qualifying_premium_amount == Decimal("288.00")    # 0.90 * 80 * 4h
    assert extended.tax_free_premium_amount == Decimal("180.00")            # 0.90 * 50(cap) * 4h
    assert extended.taxable_premium_amount == Decimal("108.00")

    standard_concurrent = concurrent_by_primary["NIGHT_STANDARD"]
    assert standard_concurrent.concurrent_category_code == "SUNDAY"
    assert standard_concurrent.combined_tax_free_pct == Decimal("75.00")    # 25 + 50, summed
    assert standard_concurrent.gross_qualifying_premium_amount == Decimal("120.00")   # 0.75 * 80 * 2h
    assert standard_concurrent.tax_free_premium_amount == Decimal("75.00")
    assert standard_concurrent.taxable_premium_amount == Decimal("45.00")

    si_concurrent = {r.primary_category_code: r for r in si_results if r.concurrent_category_code is not None}
    assert si_concurrent["NIGHT_EXTENDED"].si_contributory_premium_amount == Decimal("198.00")   # 288 - 0.90*25(cap)*4
    assert si_concurrent["NIGHT_STANDARD"].si_contributory_premium_amount == Decimal("82.50")    # 120 - 0.75*25(cap)*2

    components = service.build_germany_overtime_premium_components(db, wr.id, organization.id, actor_id=1)
    assert len(components) == 3
    assert all(c.combination_status == "COMPLETE" for c in components)
    total_gross = sum((c.gross_premium_amount for c in components), Decimal("0.00"))
    assert total_gross == Decimal("40.00") + Decimal("288.00") + Decimal("120.00")


# ═══════════════════════════════════════════════════════════════════════
# 2. Holiday concurrence — real PayrollHoliday registry, not invented.
# ═══════════════════════════════════════════════════════════════════════

def test_night_plus_national_holiday_concurrence_also_sums_like_night_plus_sunday(db, organization):
    """A national holiday (non-Sunday) concurring with night work hits the
    SAME verified one-night+one-other concurrence rule as Night+Sunday —
    summed, never max()'d."""
    _publish_all_overtime_registries(db)
    emp = _make_employee(db, organization.id, code="DE-OT-EDGE-HOL1")
    _make_profile(db, emp, organization.id, de_grundlohn_hourly=Decimal("80.00"))
    _seed_national_holiday(db, organization.id, date(2026, 11, 4))   # a Wednesday, not a Sunday

    start = datetime(2026, 11, 4, 20, 0, tzinfo=BERLIN)
    end = datetime(2026, 11, 5, 2, 0, tzinfo=BERLIN)
    wr = _make_work_record(db, emp, organization.id, start, end, hours=Decimal("6.00"))
    _classify(db, organization.id, wr)

    wage_tax_results = service.calculate_and_list_germany_overtime_wage_tax(db, wr.id, organization.id, actor_id=1)
    assert len(wage_tax_results) == 2
    assert all(r.calculation_status == "CALCULATED" for r in wage_tax_results)

    by_primary = {r.primary_category_code: r for r in wage_tax_results}
    standard = by_primary["NIGHT_STANDARD"]
    assert standard.concurrent_category_code == "HOLIDAY_STANDARD"
    assert standard.combined_tax_free_pct == Decimal("150.00")   # 25 + 125

    extended = by_primary["NIGHT_EXTENDED"]
    assert extended.concurrent_category_code == "HOLIDAY_STANDARD"
    assert extended.combined_tax_free_pct == Decimal("165.00")   # 40 + 125

    service.calculate_and_list_germany_overtime_social_insurance(db, wr.id, organization.id, actor_id=1)
    components = service.build_germany_overtime_premium_components(db, wr.id, organization.id, actor_id=1)
    assert all(c.combination_status == "COMPLETE" for c in components)


def test_sunday_plus_national_holiday_without_night_fails_closed_never_fabricated(db, organization):
    """Sunday + Holiday with NO night involved is explicitly NOT covered
    by the verified R 3b LStH text — wage_tax.py/social_insurance.py must
    fail closed (STATUTORY_RULE_UNRESOLVED), never sum/max/first-pick, and
    that must propagate all the way to a blocked attach."""
    _publish_all_overtime_registries(db)
    emp = _make_employee(db, organization.id, code="DE-OT-EDGE-HOL2")
    _make_profile(db, emp, organization.id, de_grundlohn_hourly=Decimal("80.00"))
    _seed_national_holiday(db, organization.id, date(2026, 11, 1))   # a real Sunday

    start = datetime(2026, 11, 1, 9, 0, tzinfo=BERLIN)
    end = datetime(2026, 11, 1, 17, 0, tzinfo=BERLIN)
    wr = _make_work_record(db, emp, organization.id, start, end, hours=Decimal("8.00"))
    _classify(db, organization.id, wr)

    wage_tax_results = service.calculate_and_list_germany_overtime_wage_tax(db, wr.id, organization.id, actor_id=1)
    assert len(wage_tax_results) == 1
    assert wage_tax_results[0].calculation_status == "STATUTORY_RULE_UNRESOLVED"
    assert wage_tax_results[0].gross_qualifying_premium_amount is None
    assert wage_tax_results[0].taxable_premium_amount is None

    si_results = service.calculate_and_list_germany_overtime_social_insurance(db, wr.id, organization.id, actor_id=1)
    assert si_results[0].calculation_status == "STATUTORY_RULE_UNRESOLVED"

    components = service.build_germany_overtime_premium_components(db, wr.id, organization.id, actor_id=1)
    assert len(components) == 1
    assert components[0].combination_status == "NONE"
    assert components[0].gross_premium_amount is None

    run = _make_bare_run(db, organization.id)
    item = _make_bare_payslip_item(db, run, emp, organization.id)
    with pytest.raises(BadRequestException):
        service.attach_germany_overtime_premium_component_to_payslip(
            db, components[0].id, item.id, organization.id, actor_id=1,
        )


def test_night_sunday_holiday_three_way_concurrence_fails_closed(db, organization):
    """A night shift on a date that is simultaneously Sunday AND a
    national holiday: 3 concurrent categories. Not covered by the verified
    text either (only ONE night + ONE other is verified) — must fail
    closed exactly like Sunday+Holiday above, never silently pick two of
    the three or invent a 3-way sum."""
    _publish_all_overtime_registries(db)
    emp = _make_employee(db, organization.id, code="DE-OT-EDGE-HOL3")
    _make_profile(db, emp, organization.id, de_grundlohn_hourly=Decimal("80.00"))
    _seed_national_holiday(db, organization.id, date(2026, 11, 1))   # a Sunday

    start = datetime(2026, 11, 1, 20, 0, tzinfo=BERLIN)
    end = datetime(2026, 11, 1, 23, 0, tzinfo=BERLIN)
    wr = _make_work_record(db, emp, organization.id, start, end, hours=Decimal("3.00"))
    _classify(db, organization.id, wr)

    wage_tax_results = service.calculate_and_list_germany_overtime_wage_tax(db, wr.id, organization.id, actor_id=1)
    assert len(wage_tax_results) == 1
    result = wage_tax_results[0]
    assert result.calculation_status == "STATUTORY_RULE_UNRESOLVED"
    assert result.gross_qualifying_premium_amount is None

    si_results = service.calculate_and_list_germany_overtime_social_insurance(db, wr.id, organization.id, actor_id=1)
    assert si_results[0].calculation_status == "STATUTORY_RULE_UNRESOLVED"


# ═══════════════════════════════════════════════════════════════════════
# 3. Missing Grundlohn — confirmed zero prior coverage. Proves the real,
# fail-closed behavior (NOT a defect — no source change made).
# ═══════════════════════════════════════════════════════════════════════

def test_missing_grundlohn_profile_fails_closed_never_fabricates_zero_premium(db, organization):
    """No EmployeeStatutoryProfile at all for an employee with real,
    classified overtime hours: resolve_employee_statutory_profile returns
    None, so both wage_tax.py and social_insurance.py set
    calculation_status=INSUFFICIENT_DATA with every amount left None (not
    a fabricated 0.00) — premium_component.py then combines that into
    combination_status=NONE, and attach rejects it outright. Genuinely
    fail-closed at every layer; no defect found."""
    _publish_all_overtime_registries(db)
    emp = _make_employee(db, organization.id, code="DE-OT-EDGE-NOGL")
    # Deliberately NO EmployeeStatutoryProfile row at all.

    start = datetime(2026, 1, 6, 22, 0, tzinfo=BERLIN)   # plain Tuesday-night NIGHT_STANDARD
    end = datetime(2026, 1, 7, 0, 0, tzinfo=BERLIN)
    wr = _make_work_record(db, emp, organization.id, start, end, hours=Decimal("2.00"))
    _classify(db, organization.id, wr)

    wage_tax_results = service.calculate_and_list_germany_overtime_wage_tax(db, wr.id, organization.id, actor_id=1)
    assert len(wage_tax_results) == 1
    assert wage_tax_results[0].calculation_status == "INSUFFICIENT_DATA"
    assert wage_tax_results[0].actual_grundlohn_hourly is None
    assert wage_tax_results[0].gross_qualifying_premium_amount is None
    assert wage_tax_results[0].taxable_premium_amount is None

    si_results = service.calculate_and_list_germany_overtime_social_insurance(db, wr.id, organization.id, actor_id=1)
    assert si_results[0].calculation_status == "INSUFFICIENT_DATA"
    assert si_results[0].gross_qualifying_premium_amount is None

    components = service.build_germany_overtime_premium_components(db, wr.id, organization.id, actor_id=1)
    assert len(components) == 1
    assert components[0].combination_status == "NONE"
    assert components[0].gross_premium_amount is None

    run = _make_bare_run(db, organization.id)
    item = _make_bare_payslip_item(db, run, emp, organization.id)
    with pytest.raises(BadRequestException):
        service.attach_germany_overtime_premium_component_to_payslip(
            db, components[0].id, item.id, organization.id, actor_id=1,
        )
    db.refresh(item)
    assert item.gross_pay == Decimal("0.00")   # nothing was ever applied


def test_profile_exists_but_grundlohn_explicitly_not_on_file_also_fails_closed(db, organization):
    """A distinct data-state from "no profile at all": the profile row
    exists (other statutory attributes are recorded) but de_grundlohn_hourly
    itself was never captured (None) — same INSUFFICIENT_DATA fail-closed
    path, proven separately since it's a genuinely different code
    condition (`profile is None or profile.de_grundlohn_hourly is None`)."""
    _publish_all_overtime_registries(db)
    emp = _make_employee(db, organization.id, code="DE-OT-EDGE-NOGL2")
    _make_profile(db, emp, organization.id, de_grundlohn_hourly=None)

    start = datetime(2026, 1, 6, 22, 0, tzinfo=BERLIN)
    end = datetime(2026, 1, 7, 0, 0, tzinfo=BERLIN)
    wr = _make_work_record(db, emp, organization.id, start, end, hours=Decimal("2.00"))
    _classify(db, organization.id, wr)

    wage_tax_results = service.calculate_and_list_germany_overtime_wage_tax(db, wr.id, organization.id, actor_id=1)
    assert wage_tax_results[0].calculation_status == "INSUFFICIENT_DATA"


# ═══════════════════════════════════════════════════════════════════════
# 4. Two real GermanyOvertimeWorkRecords, full engine chain, one payslip —
# no double counting.
# ═══════════════════════════════════════════════════════════════════════

def test_two_overtime_work_records_end_to_end_sum_on_payslip_without_double_counting(db, organization):
    _publish_all_overtime_registries(db)
    emp = _make_employee(db, organization.id, code="DE-OT-EDGE-MULTI")
    _make_profile(db, emp, organization.id, de_grundlohn_hourly=Decimal("80.00"))
    run = _make_bare_run(db, organization.id)
    item = _make_bare_payslip_item(db, run, emp, organization.id)

    # WR1: Sunday daytime (SUNDAY only, 50%).
    wr1 = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 4, 9, 0, tzinfo=BERLIN), datetime(2026, 1, 4, 11, 0, tzinfo=BERLIN),
        hours=Decimal("2.00"),
    )
    # WR2: weekday night (NIGHT_STANDARD only, 25%).
    wr2 = _make_work_record(
        db, emp, organization.id,
        datetime(2026, 1, 6, 22, 0, tzinfo=BERLIN), datetime(2026, 1, 7, 0, 0, tzinfo=BERLIN),
        hours=Decimal("2.00"),
    )

    components = []
    for wr in (wr1, wr2):
        _classify(db, organization.id, wr)
        service.calculate_and_list_germany_overtime_wage_tax(db, wr.id, organization.id, actor_id=1)
        service.calculate_and_list_germany_overtime_social_insurance(db, wr.id, organization.id, actor_id=1)
        built = service.build_germany_overtime_premium_components(db, wr.id, organization.id, actor_id=1)
        assert len(built) == 1
        assert built[0].combination_status == "COMPLETE"
        components.append(built[0])

    expected_gross = Decimal("80.00") + Decimal("40.00")   # 0.50*80*2 (WR1) + 0.25*80*2 (WR2)
    for c in components:
        service.attach_germany_overtime_premium_component_to_payslip(db, c.id, item.id, organization.id, actor_id=1)

    db.refresh(item)
    assert item.gross_pay == expected_gross

    # Both components roll up into the SAME PayslipAllowanceItem line (see
    # attach_germany_overtime_premium_component_to_payslip's own docstring:
    # "Multiple components MAY roll up into the SAME PayslipAllowanceItem
    # ... each attach adds this component's own amount to that line's
    # total exactly once") — one line, summed, never a second competing
    # line and never a silently-dropped amount.
    allowance_rows = (
        db.query(PayslipAllowanceItem)
        .filter(PayslipAllowanceItem.payslip_item_id == item.id)
        .all()
    )
    assert len(allowance_rows) == 1
    assert allowance_rows[0].amount == expected_gross

    attached_components = (
        db.query(GermanyOvertimePremiumComponent)
        .filter(GermanyOvertimePremiumComponent.work_record_id.in_([wr1.id, wr2.id]))
        .all()
    )
    assert len(attached_components) == 2
    assert all(c.attachment_status == "ATTACHED" for c in attached_components)
    assert sum((c.applied_gross_delta for c in attached_components), Decimal("0.00")) == expected_gross


# ═══════════════════════════════════════════════════════════════════════
# 5. Detach + real regenerate_employee_payslip — net pay back to base,
# exactly one payslip row.
# ═══════════════════════════════════════════════════════════════════════

def _make_source_artifact(db):
    source = SourceArtifact(agency="Test Fixture", title="Overtime edge-case source", checksum_sha256=None)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _publish_ceiling(db, branch, monthly, annual, maker=1, checker=2):
    source = _make_source_artifact(db)
    row = service.create_contribution_ceiling_record(
        db, GermanyContributionCeilingCreate(
            branch=branch, monthly_ceiling=monthly, annual_ceiling=annual,
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_contribution_ceiling_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_contribution_ceiling_approver(db, row.id, actor_id=checker)
    return service.set_contribution_ceiling_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_health_fund(db, health_fund_id="EDGE-FUND", rate=Decimal("1.7000"), maker=1, checker=2):
    source = _make_source_artifact(db)
    row = service.create_health_fund_record(
        db, GermanyHealthFundCreate(
            health_fund_id=health_fund_id, fund_name="Edge Test Fund",
            supplementary_rate_pct=rate, effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_health_fund_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_health_fund_approver(db, row.id, actor_id=checker)
    return service.set_health_fund_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_pv_configuration(db, maker=1, checker=2):
    source = _make_source_artifact(db)
    row = service.create_pv_configuration_record(
        db, GermanyPvConfigurationCreate(
            child_category="CHILDLESS", is_saxony=False,
            total_rate_pct=Decimal("4.2000"), standard_employee_rate_pct=Decimal("2.4000"),
            employer_rate_pct=Decimal("1.8000"), saxony_employee_rate_pct=Decimal("2.9000"),
            saxony_employer_rate_pct=Decimal("1.3000"),
            effective_from=date(2026, 1, 1), authority_source_id=source.id,
        ), actor_id=maker,
    )
    row = service.set_pv_configuration_status(db, row.id, "VERIFIED", actor_id=maker)
    row = service.set_pv_configuration_approver(db, row.id, actor_id=checker)
    return service.set_pv_configuration_status(db, row.id, "PUBLISHED", actor_id=checker)


def _publish_run_registries(db):
    _publish_ceiling(db, "GKV_PV", Decimal("5812.50"), Decimal("69750.00"))
    _publish_ceiling(db, "RV_ALV", Decimal("8450.00"), Decimal("101400.00"))
    _publish_health_fund(db)
    _publish_pv_configuration(db)


def _create_real_employee(db, org_id, seq=1, code="DE-OT-EDGE-RUN", gross=5000):
    """Real onboarding through service.create_employee (not raw
    PayrollEmployee(...) construction) — needed here because
    service.create_payroll_run's real generation path exercises the full
    DE validation/calculation pipeline, unlike the bare-PayslipItem tests
    above."""
    data = EmployeeCreate(
        employee_code=code, name=f"Overtime RunTest {code}", country_code="DE",
        date_of_joining=date(2025, 6, 1), ctc=Decimal(str(gross)) * 12,
        basic=Decimal(str(gross)), hra=Decimal("0"),
        compliance_fields={
            "steuer_id": f"{20000000000 + seq}",
            "steuerklasse": "I",
            "krankenkasse": "AOK Bayern",
            "iban": f"DE{seq:020d}",
        },
    )
    return service.create_employee(db, data, organization_id=org_id)


def _make_real_profile(db, emp, org_id):
    return service.create_employee_statutory_profile_version(
        db, emp.id, org_id, EmployeeStatutoryProfileCreate(
            effective_from=date(2026, 1, 1), de_tax_class="I", de_church_tax_liable=False,
            de_child_count=0, de_childless=True, de_saxony=False,
            de_health_insurance_status="PUBLIC", de_health_fund_code="EDGE-FUND",
            de_pension_insurance_exempt=False, de_unemployment_insurance_exempt=False,
            de_employment_classification="REGULAR",
        ), actor_id=None,
    )


def test_detach_and_regenerate_employee_payslip_returns_net_pay_to_base_single_row(db, organization, monkeypatch):
    """The REAL service.regenerate_employee_payslip path (not
    test_germany_overtime_tax_delta.py's own piecewise simulation of it)
    against a REAL service.create_payroll_run-generated payslip: attach an
    approved overtime premium, confirm it moved gross/net, detach it, then
    recalculate — net pay must return to EXACTLY its pre-overtime base
    figure, and the run must still hold exactly one payslip row for this
    employee (updated in place, never duplicated)."""
    # generate_business_code's real implementation takes a Postgres
    # advisory lock (pg_advisory_xact_lock) — not available on this test's
    # SQLite database. Same stub test_germany_full_business_acceptance.py
    # already uses for the identical reason.
    import app.core.code_generation as code_generation

    def _fake_business_code(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        return f"TEST{prefix}00001"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake_business_code)

    org_id = organization.id
    _publish_run_registries(db)
    emp = _create_real_employee(db, org_id)
    _make_real_profile(db, emp, org_id)
    db.add(PayrollAttendanceRecord(
        organization_id=org_id, employee_id=emp.id, date=date(2026, 1, 10),
        status="present", check_in="09:00", check_out="18:00",
    ))
    db.commit()

    run_data = PayrollRunCreate(
        periodStart=date(2026, 1, 1), periodEnd=date(2026, 1, 31), payDate=date(2026, 2, 1),
        employeeIds=[emp.id], auto_generate_payslips=True,
    )
    run = service.create_payroll_run(db, created_by=1, data=run_data, organization_id=org_id)

    item_before = (
        db.query(PayslipItem)
        .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id)
        .one()
    )
    base_gross = item_before.gross_pay
    base_net = item_before.net_pay
    assert base_net is not None

    work_record = service.create_germany_overtime_work_record(
        db, emp.id, org_id,
        GermanyOvertimeWorkRecordCreate(
            work_date=date(2026, 1, 20),
            start_datetime=datetime(2026, 1, 20, 18, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 1, 20, 21, 0, tzinfo=timezone.utc),
            hours=Decimal("3.00"), entry_source="MANUAL",
        ),
        actor_id=1,
    )
    work_record = service.set_germany_overtime_work_record_approval(db, work_record.id, org_id, "APPROVED", actor_id=1)
    # Directly-constructed COMPLETE component — same sanctioned bypass of
    # the wage-tax/SI sub-engines test_germany_overtime.py's own module
    # docstring documents (this scenario is about the attach/detach/
    # recalculate lifecycle, not re-proving the sub-engine math already
    # covered above).
    component = GermanyOvertimePremiumComponent(
        organization_id=org_id, work_record_id=work_record.id,
        segment_start=work_record.start_datetime, segment_end=work_record.end_datetime,
        work_date_local=work_record.work_date, qualifying_hours=Decimal("3.0000"),
        combination_status="COMPLETE",
        gross_premium_amount=Decimal("150.00"), wage_tax_free_amount=Decimal("0.00"),
        wage_taxable_amount=Decimal("150.00"), si_exempt_amount=Decimal("0.00"),
        si_contributory_amount=Decimal("150.00"),
    )
    db.add(component)
    db.commit()
    db.refresh(component)

    service.attach_germany_overtime_premium_component_to_payslip(
        db, component.id, item_before.id, org_id, actor_id=1,
    )
    db.refresh(item_before)
    assert item_before.gross_pay == base_gross + Decimal("150.00")
    assert item_before.net_pay != base_net

    service.detach_germany_overtime_premium_component_from_payslip(db, component.id, org_id, actor_id=1)
    service.regenerate_employee_payslip(db, run.id, emp.id, org_id, actor_id=1)

    items_after = (
        db.query(PayslipItem)
        .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id)
        .all()
    )
    assert len(items_after) == 1
    item_after = items_after[0]
    assert item_after.id == item_before.id
    assert item_after.gross_pay == base_gross
    assert item_after.net_pay == base_net
