"""Ireland statutory catalog <-> engine contract (ZP-IE-ENG-001 Phase 1).

engine/countries/ireland.py's IE_PARAMETER_KEYS is the authoritative list of
keys the calculator reads out of rate_map, and _Pack.assert_complete()
hard-blocks every Ireland run (IE_STATUTORY_CONTENT_NOT_CONFIGURED) when any
of them is unconfigured. hardcoded_defaults.py's _CONTRIBUTION_RATES_BY_COUNTRY
["IE"] is the seed catalog for those keys. These tests exist so the two can
never silently drift: a new engine key with no seeded row, or a seeded row the
engine never reads, both fail here rather than in production.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path
import re

import pytest

from app.modules.payroll.engine.countries.ireland import (
    IE_PARAMETER_KEYS,
    NMW_BAND_KEYS,
    PAYE_BASES,
    PRSI_LAUNCH_SUBCLASSES,
)
from app.modules.payroll.hardcoded_defaults import _CONTRIBUTION_RATES_BY_COUNTRY

IE_ROWS = _CONTRIBUTION_RATES_BY_COUNTRY["IE"]

# IE-003: PRSI is selected by PAY DATE, never by earning period, so these six
# keys carry a pre-1-October window and a from-1-October window.
PRSI_STEPPED_UP_1_OCT_2026 = (
    "ie_prsi_ax_ee_pct",
    "ie_prsi_ax_er_pct",
    "ie_prsi_al_ee_pct",
    "ie_prsi_al_er_pct",
    "ie_prsi_a1_ee_pct",
    "ie_prsi_a1_er_pct",
)

PRE_STEP_UP = (date(2026, 1, 1), date(2026, 9, 30))
POST_STEP_UP = (date(2026, 10, 1), None)


def _rows_for(key):
    return [r for r in IE_ROWS if r["component_key"] == key]


def test_catalog_covers_every_engine_parameter_key():
    missing = sorted(set(IE_PARAMETER_KEYS) - {r["component_key"] for r in IE_ROWS})
    assert not missing, f"Ireland seed catalog is missing engine keys: {missing}"


def test_catalog_has_no_keys_the_engine_never_reads():
    unknown = sorted({r["component_key"] for r in IE_ROWS} - set(IE_PARAMETER_KEYS))
    assert not unknown, f"Ireland seed catalog has keys the engine never reads: {unknown}"


def test_catalog_values_match_the_verified_engine_fixture():
    """The authoritative in-repo 2026 values are the ones
    tests/test_engine_ireland.py::ie_pack feeds the calculator and that the
    30 golden assertions run against. This test proves the SHIPPED seed
    catalog carries those same numbers, so a new organisation seeding from
    hardcoded_defaults.py gets the rates the golden tests certify.

    A magnitude-based sanity check is deliberately not used here: legitimate
    sub-1% statutory rates exist (USC band 1 is 0.5%), so no threshold can
    distinguish a correct 0.50 from a 50% written as 0.50.
    """
    from tests.test_engine_ireland import ie_pack

    default_fixture = ie_pack()
    stepped_up_fixture = ie_pack(prsi_from_1_oct=True)
    for key, kind in IE_PARAMETER_KEYS.items():
        for row in _rows_for(key):
            # The pre-1-October window is what ie_pack() returns by default; the
            # step-up window is only in ie_pack(prsi_from_1_oct=True).
            is_post_window = row.get("effective_from") == date(2026, 10, 1)
            expected = stepped_up_fixture[key] if is_post_window else default_fixture[key]
            if kind == "employee_pct":
                actual = row.get("employee_rate_pct")
            elif kind == "employer_pct":
                actual = row.get("employer_rate_pct")
            else:
                actual = row.get("flat_amount")
            assert actual in (
                expected.employee_rate_pct,
                expected.employer_rate_pct,
                expected.flat_amount,
            ), (
                f"{key} catalog value {actual} (from {row.get('effective_from')}) disagrees "
                f"with the golden fixture (ee={expected.employee_rate_pct}, "
                f"er={expected.employer_rate_pct}, amount={expected.flat_amount})"
            )


def test_percent_keys_seed_percentage_points_not_fractions():
    """The engine divides every *_pct by 100 itself (_Pack._side_pct), so the
    catalog holds percentage points (20.00 == 20%). A genuine 0% is legal and
    real (PRSI Class A0: only the employer contributes)."""
    for row in IE_ROWS:
        key = row["component_key"]
        kind = IE_PARAMETER_KEYS[key]
        for side in ("employee", "employer"):
            if kind != f"{side}_pct":
                continue
            value = row.get(f"{side}_rate_pct")
            assert value is not None, f"{key} has no {side}_rate_pct"
            assert Decimal(0) <= value <= Decimal(100), (
                f"{key} {side}_rate_pct {value} is not a valid percentage"
            )


def test_prsi_stepped_up_keys_have_two_disjoint_windows():
    for key in PRSI_STEPPED_UP_1_OCT_2026:
        rows = _rows_for(key)
        assert len(rows) == 2, f"{key} must exist in both PRSI windows, got {len(rows)}"
        pre = [r for r in rows if (r.get("effective_from"), r.get("effective_to")) == PRE_STEP_UP]
        post = [r for r in rows if (r.get("effective_from"), r.get("effective_to")) == POST_STEP_UP]
        assert len(pre) == 1 and len(post) == 1, f"{key} windows are not {[ (r.get('effective_from'), r.get('effective_to')) for r in rows ]}"


def test_prsi_step_up_actually_raises_rates():
    for key in PRSI_STEPPED_UP_1_OCT_2026:
        pre, post = _rows_for(key)
        pre_value = pre.get("employee_rate_pct") or pre.get("employer_rate_pct")
        post_value = post.get("employee_rate_pct") or post.get("employer_rate_pct")
        assert post_value > pre_value, f"{key} did not increase on 1 October 2026 ({pre_value} -> {post_value})"


def test_non_stepped_up_keys_are_not_row_dated():
    """Only PRSI changed mid-year in the 2026 catalogue. A stray effective date
    on any other key would silently hide it from a pay date outside that
    window, which is a hard block rather than a fallback."""
    for row in IE_ROWS:
        if row["component_key"] in PRSI_STEPPED_UP_1_OCT_2026:
            continue
        assert row.get("effective_from") is None, f"{row['component_key']} is unexpectedly row-dated"
        assert row.get("effective_to") is None, f"{row['component_key']} is unexpectedly row-dated"


def test_every_engine_side_is_actually_seeded():
    """_Pack reads employee_pct/employer_pct/amount per the IE_PARAMETER_KEYS
    kind. A key declared 'amount' but seeded as a rate (or vice versa) makes
    is_parameter_configured() report it as missing and blocks the run."""
    for key, kind in IE_PARAMETER_KEYS.items():
        rows = _rows_for(key)
        assert rows, f"{key} has no catalog row"
        for row in rows:
            if kind == "employee_pct":
                assert row.get("employee_rate_pct") is not None
            elif kind == "employer_pct":
                assert row.get("employer_rate_pct") is not None
            else:
                assert row.get("flat_amount") is not None


def test_every_prsi_launch_subclass_is_fully_paired():
    for subclass in PRSI_LAUNCH_SUBCLASSES:
        lower = subclass.lower()
        assert IE_PARAMETER_KEYS[f"ie_prsi_{lower}_ee_pct"] == "employee_pct"
        assert IE_PARAMETER_KEYS[f"ie_prsi_{lower}_er_pct"] == "employer_pct"
        assert _rows_for(f"ie_prsi_{lower}_ee_pct")
        assert _rows_for(f"ie_prsi_{lower}_er_pct")


def test_nmw_band_keys_are_all_seeded():
    for band_key in NMW_BAND_KEYS.values():
        assert IE_PARAMETER_KEYS[band_key] == "amount"
        assert _rows_for(band_key), f"NMW band key {band_key} is not seeded"


def test_ie_uses_the_generic_ytd_accumulator():
    """shared.py's _YTD_ACCUMULATOR_ENABLED_COUNTRIES gates service.py's
    _load_<cc>_ytd/_upsert_<cc>_ytd_accumulator pair, all of which read and
    write the generic PayrollYtdAccumulator.

    Ireland joined that set on 2026-09-28. It used to hold out behind its own
    payroll_ie_ytd_accumulators table, on the argument that USC has a payable
    base AND a paid figure, PRSI has no employee tax, and MyFutureFund needs a
    threshold-crossing date. That argument mirrored nothing in the UK or AU
    equivalents, which already ride the shared table, and the component key
    turns out to carry the meaning on its own: a reader looks at
    ie_prsi_reckonable and knows ytd_taxable_wages is the reckonable total
    with no employee tax anywhere in sight, without having to remember which
    half of the pair this country happens to use.
    """
    from app.modules.payroll.engine.countries.shared import _YTD_ACCUMULATOR_ENABLED_COUNTRIES

    assert "IE" in _YTD_ACCUMULATOR_ENABLED_COUNTRIES, (
        "Ireland's cumulative USC/PRSI/MyFutureFund state must ride the "
        "generic PayrollYtdAccumulator, like every other jurisdiction"
    )


def test_ie_has_no_dedicated_ytd_accumulator_table():
    """The dedicated table is gone and must not come back.

    Pinning this as a test rather than relying on the absence of a file: a
    dedicated Ireland YTD table is a plausible-looking "fix" for anyone who
    finds an IE accumulator confusing, and it is the one duplication this
    refactor exists to remove. Likewise for the three dead tables — dead
    schema is dead schema, and a test that fails when someone reintroduces it
    is the only thing that keeps a refactor from silently reverting.
    """
    import app.modules.payroll.models as payroll_models

    for removed in (
        "IrelandYtdAccumulator",
        "EmployerIrelandProfile",
        "IrelandRevenueSubmission",
        "IrelandRevenueMonthlyReturn",
    ):
        assert not hasattr(payroll_models, removed), (
            f"{removed} was removed in the 2026-09-28 Ireland schema refactor "
            f"(7 IE tables -> 3) and must not be reintroduced"
        )


def test_ie_ytd_component_map_is_exhaustive_and_load_bearing():
    """Every component Ireland writes has a defined, distinct meaning.

    This is the invariant that makes the generic table work for Ireland. If a
    component is added to service.py's _IE_YTD_COMPONENTS without a matching
    row here, or if two components were given the same name, the accumulator
    would silently stop being interpretable — which is precisely the failure
    mode the old column-per-figure layout had, and precisely what this test
    exists to prevent.
    """
    from app.modules.payroll.service import _IE_YTD_COMPONENTS

    assert len(set(_IE_YTD_COMPONENTS)) == len(_IE_YTD_COMPONENTS), (
        "duplicate Ireland YTD component key"
    )
    assert set(_IE_YTD_COMPONENTS) == {
        "ie_usc_payable",      # -> ytd_taxable_wages (USC's own payable base)
        "ie_usc_paid",         # -> ytd_tax_withheld
        "ie_prsi_reckonable",  # -> ytd_taxable_wages (no employee tax exists)
        "ie_prsi_weeks",       # -> ytd_tax_withheld (contribution weeks)
        "ie_mff_earnings",     # -> ytd_taxable_wages
    }


def test_mff_threshold_crossing_is_reconstructible_from_the_payslip():
    """IE-020's "record the payroll that crossed the threshold" survives the
    removal of payroll_ie_ytd_accumulators.mff_threshold_crossed_at_pay_date.

    That column was never read by anything. The requirement is met instead by
    data the engine already produces on every branch and service.py already
    snapshots verbatim onto the payslip, so the crossing payroll is a query
    over finalized payslips rather than a mutable running row. This test fails
    if a future change drops any of the three values the reconstruction needs.
    """
    import inspect

    from app.modules.payroll.engine.countries import ireland as ie_engine

    src = inspect.getsource(ie_engine.calculate_myfuturefund)
    for required in ("threshold", "earnings_ytd_before", "earnings_ytd_after"):
        assert required in src, (
            f"calculate_myfuturefund must return {required!r} on every branch, "
            f"or IE-020's threshold crossing stops being reconstructible from "
            f"the payslip snapshot"
        )

    from app.modules.payroll import service as payroll_service

    snapshot_src = inspect.getsource(payroll_service._ie_payslip_snapshot)
    assert "ie_calculation_trace" in snapshot_src, (
        "the trace must be snapshotted verbatim or the MyFutureFund threshold "
        "crossing cannot be reconstructed from the payslip"
    )


def test_paye_basis_and_scope_constants_are_intact():
    assert PAYE_BASES == ("CUMULATIVE", "WEEK_1", "EMERGENCY")
    assert PRSI_LAUNCH_SUBCLASSES == ("A0", "AX", "AL", "A1")


@pytest.mark.parametrize("row", IE_ROWS, ids=[r["component_key"] for r in IE_ROWS])
def test_catalog_rows_are_orm_constructor_safe(row):
    """_seed_contribution_rates() does ContributionRate(**row) and
    scripts/populate_canonical_tax_v1.py does the same, so every key here must
    be a real ContributionRate column — a typo would 500 on first seed."""
    from app.modules.payroll.models import ContributionRate

    columns = {c.name for c in ContributionRate.__table__.columns}
    unknown = sorted(set(row) - columns)
    assert not unknown, f"row {row['component_key']} has non-column keys: {unknown}"


# --- Report/persistence surface -------------------------------------------
#
# engine/countries/ireland.py returns ~20 ie_* figures, but PayslipItem has
# no ie_* scalar columns, so they are persisted as one JSON snapshot column
# (the same choice germany_calculation_snapshot / fr_calculation_snapshot /
# au_calculation_trace already made) and surfaced to report templates through
# the generic "PAYSLIP_ITEM_JSON" dotted-path data source.
#
# These tests exist because the alternative is silent, and silent is what
# happened before: every Irish figure except PAYE, employer PRSI and PRSC was
# computed and then discarded at payslip write time, so a ROS submission could
# only ever carry three figures.


def test_ie_calculation_snapshot_column_exists_and_is_the_only_new_one():
    from app.modules.payroll.models import PayslipItem

    columns = {c.name for c in PayslipItem.__table__.columns}
    assert "ie_calculation_snapshot" in columns
    # The deliberate alternative was a dozen scalar ie_* columns. Pin that it
    # did not happen, so a future "let's just add the columns" change is a
    # visible test failure rather than a quiet table-widening.
    assert not [c for c in columns if c.startswith("ie_") and c != "ie_calculation_snapshot"]


def test_snapshot_is_none_for_every_non_ireland_result():
    """The gate is ie_employee_total, so a non-Irish (or pre-column) result
    writes NULL and leaves every other country's payslip untouched."""
    from app.modules.payroll.service import _ie_payslip_snapshot

    class _NotIreland:
        ie_employee_total = None

    assert _ie_payslip_snapshot(_NotIreland()) is None


def _contains_decimal(value) -> bool:
    """Recursive Decimal leak check for a JSON-bound snapshot."""
    if isinstance(value, Decimal):
        return True
    if isinstance(value, dict):
        return any(_contains_decimal(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_decimal(v) for v in value)
    return False


def test_snapshot_carries_the_applied_rpn_and_every_tax_head():
    """IE-045 forbids reconstructing a historical result from current
    content, so the RPN actually applied must be frozen on the payslip —
    that is the whole point of the column."""
    from app.modules.payroll.service import _ie_payslip_snapshot

    class _Ireland:
        ie_employee_total = Decimal("500.00")
        ie_rpn_number = "RPN-2026-0001"
        ie_rpn_snapshot_id = 42
        ie_rpn_hash = "abc123"
        ie_rpn_issued_at = "2026-01-05"
        ie_paye_basis = "CUMULATIVE"
        ie_paye = Decimal("533.33")
        ie_paye_unrounded = Decimal("533.3333")
        ie_standard_rate_pay = Decimal("1000.00")
        ie_higher_rate_pay = Decimal("0.00")
        ie_tax_credit_applied = Decimal("1880.00")
        ie_usc = Decimal("160.00")
        ie_usc_unrounded = Decimal("160.0")
        ie_prsi_class = "A1"
        ie_prsi_declaration = "A1"
        ie_employee_prsi = Decimal("39.00")
        ie_employer_prsi = Decimal("83.57")
        ie_prsi_ax_credit = Decimal("0.00")
        ie_prsi_contribution_weeks = 1
        ie_prsi_weekly_reckonable = Decimal("900.00")
        ie_mff_employee = Decimal("4.50")
        ie_mff_employer = Decimal("9.00")
        ie_mff_state_topup = Decimal("4.50")
        ie_mff_status = "CONTRIBUTORY"
        ie_mff_contributory = True
        ie_mff_ceased_reason = None
        ie_lpt = Decimal("0.00")
        ie_lpt_instructed = False
        ie_lpt_rate_pct = None
        ie_employee_pension = Decimal("0.00")
        ie_employer_pension = Decimal("0.00")
        ie_nmw_rate = Decimal("12.70")
        ie_nmw_band = "20_PLUS"
        ie_effective_hourly = Decimal("20.00")
        ie_tax_year = 2026
        ie_calculation_trace = {"paye": {"band": "STANDARD"}}
        ie_ytd_after = {"usc_payable_ytd": Decimal("160.00")}

    snap = _ie_payslip_snapshot(_Ireland())

    assert snap["rpn"]["rpn_number"] == "RPN-2026-0001"
    assert snap["rpn"]["raw_hash"] == "abc123"
    assert snap["paye"]["basis"] == "CUMULATIVE"
    # Money is stored as a STRING, not a float — _jsonable_decimal's
    # house convention (the same one Canada's ytd_snapshot uses) so a
    # persisted statutory figure never picks up binary-float drift.
    assert snap["usc"]["amount"] == "160.00"
    assert snap["prsi"]["subclass"] == "A1"
    assert snap["myfuturefund"]["status"] == "CONTRIBUTORY"
    assert snap["lpt"]["instructed"] is False
    assert snap["calculation"] == {"paye": {"band": "STANDARD"}}
    # No Decimal may survive: the column is JSON, so a raw Decimal would
    # fail to serialize and lose the whole payslip write.
    assert isinstance(snap["ytd_after"]["usc_payable_ytd"], str)
    assert not _contains_decimal(snap), "snapshot still holds a Decimal"


def test_every_ie_json_report_path_resolves_against_a_real_column():
    """A PAYSLIP_ITEM_JSON source_column is "<column>.<path...>". If the
    first segment is not a real column the field would silently render blank
    for every payslip, so the segment is validated against the ORM."""
    from app.modules.payroll.models import PayslipItem
    from app.modules.payroll.service import _PAYSLIP_ITEM_JSON_FIELD_CATALOG

    columns = {c.name for c in PayslipItem.__table__.columns}
    paths = _PAYSLIP_ITEM_JSON_FIELD_CATALOG["IE"]
    assert paths, "Ireland must expose its per-head snapshot figures to reports"
    for path in paths:
        column_name, _, _rest = path.partition(".")
        assert column_name in columns, f"{path} does not start at a real PayslipItem column"


def test_ie_report_fields_expose_usc_prsi_mff_and_lpt():
    """The regression this whole column exists to prevent: a ROS template
    must be able to bind USC, PRSI, MyFutureFund and LPT, not just PAYE."""
    from app.modules.payroll.service import get_available_report_data_fields

    ie = {f["sourceColumn"] for f in get_available_report_data_fields("IE")}
    for required in (
        "ie_calculation_snapshot.usc.amount",
        "ie_calculation_snapshot.prsi.employee",
        "ie_calculation_snapshot.prsi.employer",
        "ie_calculation_snapshot.myfuturefund.employee",
        "ie_calculation_snapshot.myfuturefund.employer",
        "ie_calculation_snapshot.lpt.amount",
        "ie_calculation_snapshot.employee_total",
    ):
        assert required in ie, f"Ireland reports cannot bind {required}"


def test_ie_scalar_payslip_fields_are_all_real_columns():
    """_PAYSLIP_FIELDS_BY_COUNTRY is looked up with a strict
    catalog[key] in get_available_report_data_fields, so a key with no
    matching column would KeyError the whole Report Template field picker."""
    from app.modules.payroll.models import PayslipItem
    from app.modules.payroll.service import (
        _PAYSLIP_FIELDS_BY_COUNTRY,
        _PAYSLIP_ITEM_FIELD_CATALOG,
    )

    columns = {c.name for c in PayslipItem.__table__.columns}
    for key in _PAYSLIP_FIELDS_BY_COUNTRY["IE"]:
        assert key in _PAYSLIP_ITEM_FIELD_CATALOG, f"{key} missing from the field catalog"
        assert key in columns, f"{key} is not a real PayslipItem column"


def test_ie_reused_generic_columns_show_irish_labels():
    """tds/social-security/pension columns belong to other countries in the
    catalog, so Ireland needs overrides or the picker misnames Irish money."""
    from app.modules.payroll.service import get_available_report_data_fields

    labels = {f["sourceColumn"]: f["label"] for f in get_available_report_data_fields("IE")}
    assert labels["tds"] == "PAYE"
    assert labels["employer_social_security"].startswith("PRSI")
    assert "PRSC" in labels["employee_pension"]


# --- Seeded ROS report templates ------------------------------------------
#
# Parsed from the seed script's own source rather than a database, so this
# runs in the normal unit suite. The point is drift detection: a template
# that binds a component the report type does not allow, or a field the
# country does not offer, would otherwise only fail when a Super Admin
# opened the field picker in a browser — long after the seed had run.

_IE_SEED_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_statutory_report_templates.py"
_SEED_CALL_RE = re.compile(
    r'_seed_template\(\s*db,\s*template_key="([^"]+)".*?report_type="([A-Z_0-9]+)",\s*'
    r'country="([A-Z]{2})",\s*reporting_year="([\w-]+)",\s*'
    r'document_scope="([A-Z_]+)",\s*components=\[(.*?)\n            \],',
    re.DOTALL,
)
_FIELD_TUPLE_RE = re.compile(
    r'\("([a-z_0-9]+)", "[^"]*", "(text|currency|date)", '
    r'"(PAYROLL_RUN|EMPLOYER_PROFILE|PAYSLIP_ITEM|PAYSLIP_ITEM_JSON|PAYROLL_EMPLOYEE)", '
    r'"([a-zA-Z_0-9.]+)", (None|"SUM_RUN"|"SUM_YTD")\)'
)
_COMPONENT_RE = re.compile(r'\("([a-z_]+)", "[^"]*", \[')


def _ireland_seed_calls():
    source = _IE_SEED_SCRIPT.read_text(encoding="utf-8")
    start = source.index("Ireland (ZP-IE-ENG-001) — Revenue Online System (ROS) templates.")
    return _SEED_CALL_RE.findall(source[start:])


def test_ie_seeds_ros_templates():
    calls = _ireland_seed_calls()
    assert len(calls) == 6, f"expected the 6 Ireland ROS templates, found {len(calls)}"
    assert all(c[2] == "IE" for c in calls)


@pytest.mark.parametrize(
    "template_key,report_type,country,_year,scope,components",
    _ireland_seed_calls(),
    ids=[c[0] for c in _ireland_seed_calls()],
)
def test_ie_seeded_template_components_and_fields_are_offered(template_key, report_type, country, _year, scope, components):
    from app.modules.payroll.service import (
        get_available_report_components,
        get_available_report_data_fields,
    )

    allowed_components = {c["key"] for c in get_available_report_components(report_type)}
    allowed_fields = {f["key"] for f in get_available_report_data_fields(country)}

    for component_key, _label, _fields in _COMPONENT_RE.findall(components) and [
        (m.group(1), None, None) for m in _COMPONENT_RE.finditer(components)
    ]:
        assert component_key in allowed_components, (
            f"{template_key}: component '{component_key}' is not allowed for report_type {report_type}"
        )

    fields = _FIELD_TUPLE_RE.findall(components)
    assert fields, f"{template_key} has no fields"
    for field_key, field_type, _kind, source_column, aggregation in fields:
        assert source_column in allowed_fields, (
            f"{template_key}: field '{field_key}' binds '{source_column}', "
            f"which {country} does not offer"
        )
        # An AGGREGATE template's currency rows must sum. A PER_EMPLOYEE one
        # must not (see DE-LSTB's own convention) — summing an employee's
        # weekly reckonable band or NAERSA status across a run is meaningless.
        if scope == "AGGREGATE" and field_type == "currency":
            assert aggregation != "None", (
                f"{template_key}: AGGREGATE currency field '{field_key}' has no aggregation"
            )


def test_ie_prsi_schedule_is_per_employee_not_aggregate():
    """PRSI sub-class and weekly reckonable pay are per-employee facts, so
    the schedule must not be seeded as an AGGREGATE document."""
    calls = {c[0]: c for c in _ireland_seed_calls()}
    assert calls["IE-PRSI-SCHEDULE"][4] == "PER_EMPLOYEE"
    assert calls["IE-MFF-SCHEDULE"][4] == "PER_EMPLOYEE"
    assert calls["IE-LPT-SCHEDULE"][4] == "PER_EMPLOYEE"
    # The period roll-up is the one that genuinely is aggregate.
    assert calls["IE-ROS-PAYROLL"][4] == "AGGREGATE"


def test_ie_mff_state_topup_is_never_in_a_deductions_component():
    """IE-018: the 0.5% State contribution is administered by the
    State/NAERSA and is never deducted from the employee. It must live in
    its own informational component, never alongside PAYE/PRSI."""
    calls = {c[0]: c for c in _ireland_seed_calls()}
    mff_components = calls["IE-MFF-SCHEDULE"][5]
    assert "myfuturefund_state" in _COMPONENT_RE.findall(mff_components) or any(
        m.group(1) == "myfuturefund_state" for m in _COMPONENT_RE.finditer(mff_components)
    )
    # And it must not appear in the ROS payroll summary's totals at all.
    assert "state_topup" not in calls["IE-ROS-PAYROLL"][5]
    assert "state_topup" not in calls["IE-ROS-EMP-CERT"][5]
