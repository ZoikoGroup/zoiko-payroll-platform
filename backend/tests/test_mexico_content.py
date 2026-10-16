"""Mexico (ZP-MX-ENG-001) Phase 1 content — structure, date selection and
transcription checks for engine/countries/mexico_content.py.

Two kinds of test live here:
  * STRUCTURAL tests run now, against the empty content tables and against
    clearly-labelled SYNTHETIC rows (test data, never statutory values).
  * VALUE tests check transcribed content against its saved source and the
    spec. They are skipped while the content table they need is empty; their
    expected figures are read from the spec .docx at run time, never typed
    into this file.

`app.*` is imported inside the tests (collection-order DB-binding hazard)."""

import inspect
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_DOCX = REPO_ROOT / "docs" / "mexico" / "Zoiko_Payroll_Mexico_Engineering_Wireframe_and_Implementation_Specification_v1.0.docx"
MANIFEST = REPO_ROOT / "docs" / "mexico" / "sources" / "SOURCES_MANIFEST.csv"
_AWAITING = "awaiting transcription — this content table is empty until 'start transcription'"


def _c():
    from app.modules.payroll.engine.countries import mexico_content

    return mexico_content


def _need(table, name):
    if not table:
        pytest.skip(f"{name}: {_AWAITING}")


# ── spec reader (value tests read their expectations from the spec) ─────────

def _spec_tables():
    docx = pytest.importorskip("docx")
    return docx.Document(str(SPEC_DOCX)).tables


def _spec_table_rows(first_header: str):
    for table in _spec_tables():
        cells = [[c.text.strip() for c in row.cells] for row in table.rows]
        if cells and cells[0][0].startswith(first_header):
            return cells[1:]
    pytest.fail(f"spec table starting {first_header!r} not found")


def _spec_row(first_header: str, label: str):
    for row in _spec_table_rows(first_header):
        if row[0].startswith(label):
            return row
    pytest.fail(f"spec row {label!r} not found in table {first_header!r}")


def _nums(text: str):
    return [Decimal(t.replace(",", "")) for t in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", text)]


def _money(text: str):
    """Only the figures with decimals (amounts), not years or day numbers."""
    return [Decimal(t.replace(",", "")) for t in re.findall(r"\d{1,3}(?:,\d{3})*\.\d+", text)]


# ── ISR arithmetic checks (Phase 1 plan §3, §6 changes 1–2) ────────────────

def _isr_errors(brackets, exceptions=None, period=None):
    """Continuity and quota-consistency failures of one ordered tariff.
    Bracket i (1-based, i >= 2): lower[i] == upper[i-1] + 0.01 and
    quota[i] == round(quota[i-1] + (upper[i-1] - lower[i-1]) * rate[i-1], 2)
    within 0.01. A quota failure listed in `exceptions` is a documented
    source-wins exception, not an error."""
    exceptions = exceptions or {}
    errors = []
    if not brackets:
        return ["empty tariff"]
    period = period or brackets[0].period
    if Decimal(brackets[0].lower) != Decimal("0.01"):
        errors.append(f"{period}: bracket 1 lower is {brackets[0].lower}, not 0.01")
    if brackets[-1].upper is not None:
        errors.append(f"{period}: last bracket is not open-ended")
    for i in range(1, len(brackets)):
        prev, cur = brackets[i - 1], brackets[i]
        n = i + 1
        if prev.upper is None:
            errors.append(f"{period}: bracket {i} is open-ended but is not last")
            continue
        if Decimal(cur.lower) != Decimal(prev.upper) + Decimal("0.01"):
            errors.append(f"{period}: bracket {n} lower {cur.lower} != bracket {i} upper {prev.upper} + 0.01")
        if Decimal(cur.rate_pct) <= Decimal(prev.rate_pct):
            errors.append(f"{period}: bracket {n} rate does not increase")
        expected = (Decimal(prev.fixed_quota)
                    + (Decimal(prev.upper) - Decimal(prev.lower)) * Decimal(prev.rate_pct) / 100
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(expected - Decimal(cur.fixed_quota)) > Decimal("0.01") and (period, n) not in exceptions:
            errors.append(f"{period}: bracket {n} quota {cur.fixed_quota} != {expected}")
    return errors


def _synthetic_bracket(lower, upper, quota, rate, period="MONTHLY"):
    c = _c()
    return c.IsrBracket(period, lower, upper, quota, rate, None, None, "S2", "SYNTHETIC TEST ROW")


# Synthetic tariff (test data, not law): 0.01–100.00 at 10%, 100.01–200.00 at
# 20%, 200.01+ at 30%. Quota 2 = 0 + (100.00 - 0.01) * 10% = 9.999 -> 10.00;
# quota 3 = 10.00 + (200.00 - 100.01) * 20% = 29.998 -> 30.00.
def _synthetic_tariff():
    return [_synthetic_bracket("0.01", "100.00", "0.00", "10"),
            _synthetic_bracket("100.01", "200.00", "10.00", "20"),
            _synthetic_bracket("200.01", None, "30.00", "30")]


def test_isr_checker_accepts_a_consistent_tariff():
    assert _isr_errors(_synthetic_tariff()) == []


def test_isr_checker_indexes_quotas_from_the_previous_bracket():
    """Directional (review change 2): bracket 2's quota is derived from
    bracket 1's width and rate, bracket 3's from bracket 2's — changing
    bracket 1's rate breaks ONLY bracket 2's quota, and vice versa."""
    t = _synthetic_tariff()
    t[0] = t[0]._replace(rate_pct="15")
    errors = [e for e in _isr_errors(t) if "quota" in e]
    assert len(errors) == 1 and "bracket 2 quota" in errors[0]
    t = _synthetic_tariff()
    t[1] = t[1]._replace(rate_pct="25")
    errors = [e for e in _isr_errors(t) if "quota" in e]
    assert len(errors) == 1 and "bracket 3 quota" in errors[0]


def test_isr_checker_flags_gaps_overlaps_and_closed_tops():
    t = _synthetic_tariff()
    t[1] = t[1]._replace(lower="100.02")
    assert any("bracket 2 lower" in e for e in _isr_errors(t))
    t = _synthetic_tariff()
    t[2] = t[2]._replace(upper="300.00")
    assert any("open-ended" in e for e in _isr_errors(t))


def test_isr_checker_honours_documented_source_wins_exceptions():
    t = _synthetic_tariff()
    t[2] = t[2]._replace(fixed_quota="30.05")
    assert _isr_errors(t) and _isr_errors(t, {("MONTHLY", 3): "log ref"}) == []


# ── catalogue structure ─────────────────────────────────────────────────────

def test_parameter_keys_are_well_formed():
    c = _c()
    longest_marks = len(f" {c.PENDING_G1} {c.PENDING_G2}")
    assert c.MX_PARAMETER_KEYS
    for key, (kind, label, scope) in c.MX_PARAMETER_KEYS.items():
        assert key.startswith("mx_") and len(key) <= 50, key
        assert kind in c.MX_PARAMETER_KINDS, key
        assert scope in ("national", "state"), key
        assert label and len(label) + longest_marks <= 100, key
        assert not re.search(r"\d+(\.\d+)?\s*%|\bMXN\s*\d", label), f"{key}: label must not carry a value"


def test_only_the_ceav_lowest_band_reference_is_pending_g2():
    c = _c()
    assert c.MX_PENDING_G2_KEYS == ("mx_ceav_lowest_band_min_wage_ref",)
    assert c.MX_PARAMETER_KEYS["mx_ceav_lowest_band_min_wage_ref"][0] == "text"


def test_identifiers_and_scope_constants():
    c = _c()
    assert c.MX_ISR_PERIODS == ("DAILY", "WEEKLY_7", "DECENAL_10", "QUINCENAL_15", "MONTHLY")
    assert c.MX_CEAV_SEEDED_YEAR == 2026 and c.MX_CEAV_SCHEDULE_YEARS == tuple(range(2023, 2031))
    assert all(rule.startswith("MX_") for rule in c.MX_SLAB_RULES)
    assert set(c.MX_ISN_CONTENT) == set(c.MX_ISN_STATES_IN_SCOPE) == {"CDMX"}
    assert c.ALL_SOURCE_CODES == tuple(f"S{i}" for i in range(1, 34))      # S24–S33: addendum, pending approval


def test_every_content_row_has_its_declared_shape():
    c = _c()
    shapes = ((c.MX_SCALAR_CONTENT, c.ScalarRow), (c.MX_ISR_TARIFFS, c.IsrBracket), (c.MX_MIN_WAGES, c.MinWageRow),
              (c.MX_ZLFN_MUNICIPALITIES, c.ZlfnMunicipality), (c.MX_CEAV_SCHEDULE, c.CeavBand),
              (c.MX_WORKWEEK, c.WorkweekRow), (c.MX_VACATION_DAYS, c.VacationDaysRow))
    for table, shape in shapes:
        assert all(isinstance(row, shape) for row in table), shape.__name__
    for rows in c.MX_ISN_CONTENT.values():
        assert all(isinstance(row, c.ScalarRow) for row in rows)


def test_every_row_is_sourced_and_g1_flagged():
    c = _c()
    rows = (list(c.MX_SCALAR_CONTENT) + list(c.MX_ISR_TARIFFS) + list(c.MX_MIN_WAGES) + list(c.MX_CEAV_SCHEDULE)
            + list(c.MX_WORKWEEK) + list(c.MX_VACATION_DAYS)
            + [r for rows in c.MX_ISN_CONTENT.values() for r in rows])
    for row in rows:
        assert row.source in c.ALL_SOURCE_CODES and row.source_ref and row.needs_g1 is True, row
    for row in c.MX_SCALAR_CONTENT:
        assert row.key in c.MX_PARAMETER_KEYS and row.pending_g2 == (row.key in c.MX_PENDING_G2_KEYS)


def test_cited_sources_are_verified_files_with_matching_hashes():
    c = _c()
    rows = (list(c.MX_SCALAR_CONTENT) + list(c.MX_ISR_TARIFFS) + list(c.MX_MIN_WAGES) + list(c.MX_CEAV_SCHEDULE)
            + list(c.MX_WORKWEEK) + list(c.MX_VACATION_DAYS)
            + [r for rows in c.MX_ISN_CONTENT.values() for r in rows])
    _need(rows, "provenance")
    from scripts import verify_mexico_sources as v

    verified = {r["code"] for r in v.read_manifest(MANIFEST) if r["status"] == "VERIFIED"}
    assert {row.source for row in rows} <= verified
    assert v.cmd_check(MANIFEST) == []


# ── date selection (MX-004): required argument, never the server clock ─────

def _helpers():
    c = _c()
    return [fn for name, fn in vars(c).items() if callable(fn) and name.endswith("_in_force")]


def test_every_in_force_helper_requires_its_date():
    helpers = _helpers()
    assert len(helpers) >= 9
    for fn in helpers:
        param = inspect.signature(fn).parameters["as_of"]
        assert param.default is inspect.Parameter.empty, fn.__name__


def test_helpers_fail_closed_on_empty_content(monkeypatch):
    c = _c()
    for table in ("MX_SCALAR_CONTENT", "MX_ISR_TARIFFS", "MX_MIN_WAGES", "MX_CEAV_SCHEDULE", "MX_WORKWEEK",
                  "MX_VACATION_DAYS"):
        monkeypatch.setattr(c, table, ())
    monkeypatch.setattr(c, "MX_ISN_CONTENT", {"CDMX": ()})
    on = date(2026, 3, 15)
    for call in (lambda: c.uma_in_force(on), lambda: c.subsidy_in_force(on), lambda: c.min_wages_in_force(on),
                 lambda: c.ceav_bands_in_force(on), lambda: c.workweek_in_force(on),
                 lambda: c.vacation_days_in_force(on), lambda: c.scalar_rows_in_force(on),
                 lambda: c.isr_tariff_in_force("MONTHLY", on), lambda: c.isn_rows_in_force("CDMX", on),
                 lambda: c.isn_rows_in_force("JAL", on)):
        with pytest.raises(c.MexicoContentMissing):
            call()
    with pytest.raises(ValueError):
        c.isr_tariff_in_force("BIWEEKLY", on)
    with pytest.raises(TypeError):
        c.uma_in_force(None)


def _synthetic_scalar(key, value, eff_from, eff_to):
    c = _c()
    return c.ScalarRow(key, None, None, value, None, eff_from, eff_to, "S6", "SYNTHETIC TEST ROW")


def test_today_changes_nothing(monkeypatch):
    """Selection follows the argument. The module's `date` is replaced by one
    whose today() fails — no helper may consult the server clock."""
    c = _c()
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (
        _synthetic_scalar("mx_uma_daily", "1", date(2026, 1, 1), date(2026, 1, 31)),
        _synthetic_scalar("mx_uma_daily", "2", date(2026, 2, 1), date(2026, 12, 31)),
    ))

    class _NoClock(date):
        @classmethod
        def today(cls):
            raise AssertionError("mexico_content consulted the server clock")

    monkeypatch.setattr(c, "date", _NoClock)
    assert c.uma_in_force(date(2026, 1, 31))["daily"] == Decimal("1")
    assert c.uma_in_force(date(2026, 2, 1))["daily"] == Decimal("2")


def test_no_mexico_module_reads_the_server_clock():
    root = Path(__file__).resolve().parents[1] / "app" / "modules" / "payroll" / "engine"
    files = [root / "countries" / "mexico.py", root / "countries" / "mexico_content.py",
             *sorted((root / "jurisdictions" / "mexico").glob("*.py"))]
    for path in files:
        text = path.read_text(encoding="utf-8")
        for forbidden in ("date.today(", "datetime.now(", "datetime.today(", "utcnow("):
            assert forbidden not in text, f"{path.name} uses {forbidden}"


def test_ceav_schedule_selects_its_year_by_date(monkeypatch):
    c = _c()
    rows = tuple(c.CeavBand(y, "1", "UMA", None, None, str(y), date(y, 1, 1), date(y, 12, 31), "S11", "SYNTHETIC")
                 for y in (2025, 2026, 2027))
    monkeypatch.setattr(c, "MX_CEAV_SCHEDULE", rows)
    assert {b.year for b in c.ceav_bands_in_force(date(2026, 12, 31))} == {2026}
    assert {b.year for b in c.ceav_bands_in_force(date(2027, 1, 1))} == {2027}


# ── VALUE tests — skipped until the table they need is transcribed ─────────

def test_every_isr_tariff_is_continuous_and_quota_consistent():
    c = _c()
    _need(c.MX_ISR_TARIFFS, "ISR tariffs")
    errors = []
    for period in c.MX_ISR_PERIODS:
        errors += _isr_errors(c.isr_tariff_in_force(period, date(2026, 6, 30)), c.MX_ISR_ARITHMETIC_EXCEPTIONS, period)
    assert errors == []


def test_monthly_isr_tariff_equals_spec_section_4():
    c = _c()
    _need(c.MX_ISR_TARIFFS, "ISR tariffs")
    spec = []
    for row in _spec_table_rows("2026 monthly ISR bracket"):
        bounds = _nums(row[0])
        spec.append((bounds[0], bounds[1] if len(bounds) > 1 else None, _nums(row[1])[0], _nums(row[2])[0]))
    ours = [(Decimal(b.lower), Decimal(b.upper) if b.upper is not None else None, Decimal(b.fixed_quota),
             Decimal(b.rate_pct)) for b in c.isr_tariff_in_force("MONTHLY", date(2026, 6, 30))]
    assert ours == spec, "spec §4 and S2 disagree — stop and ask (Phase 1 plan §6 change 1)"


def test_uma_changes_on_1_february_2026():
    c = _c()
    _need([r for r in c.MX_SCALAR_CONTENT if r.key.startswith("mx_uma_")], "UMA")
    jan, feb = c.uma_in_force(date(2026, 1, 31)), c.uma_in_force(date(2026, 2, 1))
    jan_spec = _money(_spec_row("Area", "UMA — January")[1])      # daily, monthly
    feb_spec = _money(_spec_row("Area", "UMA — from 1 Feb")[1])   # daily, monthly, annual
    assert [jan["daily"], jan["monthly"]] == jan_spec
    assert [feb["daily"], feb["monthly"], feb["annual"]] == feb_spec
    assert feb["daily"] > jan["daily"]


def test_subsidy_rule_switches_between_january_and_february():
    c = _c()
    _need([r for r in c.MX_SCALAR_CONTENT if r.key.startswith("mx_subsidy_")], "employment subsidy")
    jan, feb = c.subsidy_in_force(date(2026, 1, 31)), c.subsidy_in_force(date(2026, 2, 1))
    spec = _nums(_spec_row("Parameter", "January 2026")[1]) + _nums(_spec_row("Parameter", "February onward")[1])
    assert jan["mx_subsidy_rate_pct"] in spec and feb["mx_subsidy_rate_pct"] in spec
    assert jan["mx_subsidy_rate_pct"] != feb["mx_subsidy_rate_pct"]
    # The amount is computed from the transcribed UMA, never typed in.
    jan_amount = jan["mx_subsidy_rate_pct"] * c.uma_in_force(date(2026, 1, 31))["monthly"] / 100
    feb_amount = feb["mx_subsidy_rate_pct"] * c.uma_in_force(date(2026, 2, 1))["monthly"] / 100
    assert jan_amount != feb_amount


def test_sbc_ceiling_differs_between_january_and_february():
    c = _c()
    rows = c.MX_SCALAR_CONTENT
    _need([r for r in rows if r.key == "mx_sbc_max_uma_multiple"], "SBC ceiling")
    multiple_jan = Decimal(c.scalar_rows_in_force(date(2026, 1, 31))["mx_sbc_max_uma_multiple"].flat_amount)
    multiple_feb = Decimal(c.scalar_rows_in_force(date(2026, 2, 1))["mx_sbc_max_uma_multiple"].flat_amount)
    cap_jan = multiple_jan * c.uma_in_force(date(2026, 1, 31))["daily"]
    cap_feb = multiple_feb * c.uma_in_force(date(2026, 2, 1))["daily"]
    assert cap_feb > cap_jan                                   # MX-021


def test_ceav_2026_bands_equal_spec_section_9_and_schedule_is_complete():
    c = _c()
    _need(c.MX_CEAV_SCHEDULE, "CEAV schedule")
    assert {b.year for b in c.MX_CEAV_SCHEDULE} == set(c.MX_CEAV_SCHEDULE_YEARS)
    spec_rates = [_nums(row[1])[0] for row in _spec_table_rows("SBC band")]
    ours = [Decimal(b.employer_pct) for b in c.ceav_bands_in_force(date(2026, 6, 30))]
    assert ours == spec_rates


def test_workweek_steps_from_2026_to_2027():
    c = _c()
    _need(c.MX_WORKWEEK, "workweek")
    text = _spec_row("Area", "Workweek")[1]
    spec_2026 = Decimal(re.search(r"(\d+)-hour weekly maximum", text).group(1))
    spec_2027 = Decimal(re.search(r"(\d+) hours from 1 Jan 2027", text).group(1))
    h2026 = Decimal(c.workweek_in_force(date(2026, 12, 31)).ordinary_weekly_max_hours)
    h2027 = Decimal(c.workweek_in_force(date(2027, 1, 1)).ordinary_weekly_max_hours)
    assert (h2026, h2027) == (spec_2026, spec_2027) and h2027 < h2026   # MX-048/MX-050


def test_ceav_lowest_band_reference_is_present_and_pending_g2():
    c = _c()
    rows = [r for r in c.MX_SCALAR_CONTENT if r.key == "mx_ceav_lowest_band_min_wage_ref"]
    _need(rows, "CEAV lowest-band reference")
    assert all(r.pending_g2 and r.text_value for r in rows)
    assert {r.key for r in c.MX_SCALAR_CONTENT if r.pending_g2} == {"mx_ceav_lowest_band_min_wage_ref"}
