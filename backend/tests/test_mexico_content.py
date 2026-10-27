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
    assert c.ALL_SOURCE_CODES == tuple(f"S{i}" for i in range(1, 35))      # S24–S34: addendum, pending approval


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
        # a cite is CODE or CODE/file (Phase 11d: multi-file codes are cited by file)
        assert row.source.split("/")[0] in c.ALL_SOURCE_CODES and row.source_ref and row.needs_g1 is True, row
    for row in c.MX_SCALAR_CONTENT:
        assert row.key in c.MX_PARAMETER_KEYS and row.pending_g2 == (row.key in c.MX_PENDING_G2_KEYS)


def test_cited_sources_are_saved_files_with_matching_hashes():
    """Every cite resolves to a manifest file usable for a Draft pack (VERIFIED
    with its log entry, or an ARCHIVE_COPY_VERIFIED capture — Phase 11d), and
    every saved file still hashes to its row. Activation additionally needs
    VERIFIED (the sources_verified gate), which no archive copy satisfies."""
    c = _c()
    rows = (list(c.MX_SCALAR_CONTENT) + list(c.MX_ISR_TARIFFS) + list(c.MX_MIN_WAGES) + list(c.MX_CEAV_SCHEDULE)
            + list(c.MX_WORKWEEK) + list(c.MX_VACATION_DAYS)
            + [r for rows in c.MX_ISN_CONTENT.values() for r in rows])
    _need(rows, "provenance")
    from app.modules.payroll import mexico_sources
    from scripts import verify_mexico_sources as v

    usable = mexico_sources.usable(mexico_sources.read_rows(MANIFEST), mexico_sources.DRAFT_STATUSES,
                                   mexico_sources.read_log(MANIFEST))
    assert {row.source for row in rows} <= set(usable)
    assert all("/" in row.source for row in rows)                  # Batch 1 onward: cited by file
    # The source binaries live outside git (team evidence store); where they
    # are checked out, every one must still hash to its manifest row.
    cited = [usable[row.source] for row in rows]
    if not all((MANIFEST.parent / r["file"]).is_file() for r in cited):
        pytest.skip("source binaries not checked out here — hashes checked where they are")
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


def test_the_7_10_and_15_day_tariffs_are_the_daily_tariff_times_days():
    """TL-ISR-2: S2 prints B.II-B.IV as B.I x days — every upper limit and
    quota exactly, the rates unchanged. This replaces the previous-bracket quota
    formula for those three tables (their documented exceptions)."""
    c = _c()
    _need(c.MX_ISR_TARIFFS, "ISR tariffs")
    daily = c.isr_tariff_in_force("DAILY", date(2026, 6, 30))
    for period, days in (("WEEKLY_7", 7), ("DECENAL_10", 10), ("QUINCENAL_15", 15)):
        table = c.isr_tariff_in_force(period, date(2026, 6, 30))
        assert len(table) == len(daily) == 11
        for d, row in zip(daily, table):
            assert row.rate_pct == d.rate_pct
            assert Decimal(row.fixed_quota) == Decimal(d.fixed_quota) * days, (period, row)
            if d.upper is not None:
                assert Decimal(row.upper) == Decimal(d.upper) * days, (period, row)
    # every documented exception is in one of these three tables, nowhere else
    assert {p for p, _ in c.MX_ISR_ARITHMETIC_EXCEPTIONS} <= {"WEEKLY_7", "DECENAL_10", "QUINCENAL_15"}
    assert set(c.MX_ISR_ARITHMETIC_EXCEPTIONS.values()) == {"TL-ISR-2"}


def test_documented_isr_exceptions_are_exactly_the_failing_brackets():
    """No exception hides a bracket that closes, and none is missing."""
    c = _c()
    _need(c.MX_ISR_TARIFFS, "ISR tariffs")
    failing = set()
    for period in c.MX_ISR_PERIODS:
        for e in _isr_errors(c.isr_tariff_in_force(period, date(2026, 6, 30)), {}, period):
            m = re.match(rf"{period}: bracket (\d+) quota", e)
            assert m, e                                          # only quota failures may be excepted
            failing.add((period, int(m.group(1))))
    assert failing == set(c.MX_ISR_ARITHMETIC_EXCEPTIONS)


def test_pay_frequency_map_is_cited_and_never_guesses():
    c = _c()
    _need(c.MX_PAY_FREQUENCY_ISR_PERIOD, "pay-frequency map")
    assert set(c.MX_PAY_FREQUENCY_ISR_PERIOD) == set(c.MX_PAY_FREQUENCY_ISR_PERIOD_SOURCES)
    assert set(c.MX_PAY_FREQUENCY_ISR_PERIOD.values()) <= set(c.MX_ISR_PERIODS)
    for code, (catalog, table, marker) in c.MX_PAY_FREQUENCY_ISR_PERIOD_SOURCES.items():
        assert catalog[0].startswith("S28/") and table[0].startswith("S2/") and marker == c.PENDING_G1
    # 01 Diario is a G1 decision; codes with no Art. 96 table in S2 are never mapped
    assert not {"01", "03", "06", "07", "08", "09", "99"} & set(c.MX_PAY_FREQUENCY_ISR_PERIOD)


def test_monthly_isr_tariff_equals_spec_section_4():
    c = _c()
    _need(c.MX_ISR_TARIFFS, "ISR tariffs")
    spec = []
    for row in _spec_table_rows("2026 monthly ISR bracket"):
        bounds = _nums(row[0])
        spec.append((bounds[0], bounds[1] if len(bounds) > 1 else None, _nums(row[1])[0], _nums(row[2])[0]))
    ours = [(Decimal(b.lower), Decimal(b.upper) if b.upper is not None else None, Decimal(b.fixed_quota),
             Decimal(b.rate_pct)) for b in c.isr_tariff_in_force("MONTHLY", date(2026, 6, 30))]
    # 2026-10-26 rule: the spec is not a source. If S2 and spec §4 ever differ,
    # S2 wins and the difference is listed in the transcription log and the report.
    assert ours == spec, "S2 differs from spec §4 — S2 wins; list the difference (transcription log)"


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


# ── Batch 2 (2026-10-26): IMSS, CEAV, INFONAVIT, minimum wages, LFT, workweek ──

def test_derived_values_are_rebuilt_from_their_printed_components():
    """TL-IMSS-2 / TL-WW-2: no source prints these values. Each is recomputed
    from the printed base and annual steps (S10 Art. 106 + 1995 Transitorio
    DECIMO NOVENO), the printed quota share (Art. 107) or the printed overtime
    premium (S18 Arts. 66 / 68)."""
    c = _c()
    _need(c.MX_DERIVED_VALUES, "derived values")
    rows = {r.key: r for r in c.MX_SCALAR_CONTENT}
    for key, d in c.MX_DERIVED_VALUES.items():
        row = rows[key]
        value = Decimal(row.employer_pct or row.employee_pct or row.flat_amount)
        if "base" in d:
            expected = Decimal(d["base"]) + d["direction"] * d["steps"] * Decimal(d["step"])
        elif "quota" in d:
            expected = Decimal(d["quota"]) * Decimal(d["share"]) / 100
        else:
            expected = 1 + Decimal(d["premium"]) / 100
        assert value == expected, (key, value, expected)
        assert "DERIVED" in row.source_ref or "read as" in row.source_ref, key


def test_vacation_rows_follow_the_art_76_wording():
    """TL-VAC-1: 12 days after the first year, +2 per year up to 20, then +2 per
    five years from the sixth year — rebuilt from MX_VACATION_RULE_NUMBERS."""
    c = _c()
    _need(c.MX_VACATION_DAYS, "vacation schedule")
    first, step, cap, every = (int(x) for x in c.MX_VACATION_RULE_NUMBERS)
    for row in c.vacation_days_in_force(date(2026, 6, 30)):
        y = row.service_year_from
        expected = min(first + step * (y - 1), cap) if y <= 5 else cap + step * ((y - 6) // every + 1)
        assert int(row.days) == expected, row
        if y >= 6:
            assert (row.service_year_to - y + 1) == every and (y - 6) % every == 0
    years = sorted((r.service_year_from, r.service_year_to) for r in c.MX_VACATION_DAYS)
    assert years[0][0] == 1 and all(b[0] == a[1] + 1 for a, b in zip(years, years[1:]))   # no gaps


def test_ceav_schedule_shape_and_steps():
    """S11's table is a scanned image (TL-CEAV-1): 8 bands x 2023-2030, rates rise
    across bands within a year, and each band rises by a near-constant annual
    step (the decree phases the 2023 rates into the 2030 ones)."""
    c = _c()
    _need(c.MX_CEAV_SCHEDULE, "CEAV schedule")
    by_year = {}
    for b in c.MX_CEAV_SCHEDULE:
        by_year.setdefault(b.year, []).append(b)
    assert sorted(by_year) == list(c.MX_CEAV_SCHEDULE_YEARS) and all(len(v) == 8 for v in by_year.values())
    for year, bands in by_year.items():
        rates = [Decimal(b.employer_pct) for b in sorted(bands, key=lambda b: Decimal(b.lower_multiple))]
        assert rates == sorted(rates) and len(set(rates)) == 8, year
    for i in range(8):
        col = [Decimal(sorted(by_year[y], key=lambda b: Decimal(b.lower_multiple))[i].employer_pct)
               for y in sorted(by_year)]
        steps = [b - a for a, b in zip(col, col[1:])]
        assert max(steps) - min(steps) <= Decimal("0.002"), (i, steps)


def test_ceav_2030_column_equals_the_lss_art_168_text_table():
    """The machine-checkable half of TL-CEAV-1: S10 Art. 168 II a) prints the
    final schedule, which must equal S11's 2030 column exactly."""
    c = _c()
    _need(c.MX_CEAV_SCHEDULE, "CEAV schedule")
    from app.modules.payroll import mexico_sources
    from scripts import verify_mexico_sources as v

    cite, year, _ = c.MX_CEAV_TEXT_CROSSCHECK
    row = mexico_sources.usable(mexico_sources.read_rows(MANIFEST), mexico_sources.DRAFT_STATUSES,
                                mexico_sources.read_log(MANIFEST)).get(cite)
    path = MANIFEST.parent / row["file"] if row else None
    if path is None or not path.is_file():
        pytest.skip("S10 binary not checked out here")
    text = v.extract_text(path)
    start = text.index("Cuota Patronal")                        # the rates are in order (labels may drift)
    table = text[start:text.index("b) Los trabajadores", start)]
    printed = re.findall(r"(\d{1,2}\.\d{3})%", table)
    ours = [b.employer_pct for b in sorted((b for b in c.MX_CEAV_SCHEDULE if b.year == year),
                                           key=lambda b: Decimal(b.lower_multiple))]
    assert printed == ours


def test_minimum_wages_zones_and_professions():
    c = _c()
    _need(c.MX_MIN_WAGES, "minimum wages")
    rows = c.min_wages_in_force(date(2026, 6, 30))
    zones = {r.code: r for r in rows if r.kind == "ZONE"}
    assert set(zones) == {"GENERAL", "ZLFN"} and Decimal(zones["ZLFN"].daily_amount) > Decimal(zones["GENERAL"].daily_amount)
    prof = {}
    for r in rows:
        if r.kind == "PROFESSION":
            prof.setdefault(r.code, {})[r.zone] = Decimal(r.daily_amount)
    assert len(prof) == 61 and all(set(z) == {"ZLFN", "GENERAL"} for z in prof.values())
    # S9 resolutivo SEXTO: a ZLFN amount below the ZSMG one would be replaced by it — none is
    assert all(z["ZLFN"] >= z["GENERAL"] for z in prof.values())
    # every professional minimum is at least its zone's general minimum
    assert all(z["GENERAL"] >= Decimal(zones["GENERAL"].daily_amount) for z in prof.values())


def test_zlfn_municipalities_are_federal_entities_and_unique():
    c = _c()
    _need(c.MX_ZLFN_MUNICIPALITIES, "ZLFN municipalities")
    states = {code for code, _ in c.MX_FEDERAL_ENTITIES}
    keys = [(m.state, m.municipality) for m in c.MX_ZLFN_MUNICIPALITIES]
    assert len(keys) == 45 and len(set(keys)) == 45 and {s for s, _ in keys} <= states
    assert {s for s, _ in keys} == {"BCN", "SON", "CHH", "COA", "NLE", "TAM"}
    # "Guerrero" is two different municipalities (Coahuila and Tamaulipas), as S9 lists them
    assert {s for s, m in keys if m == "Guerrero"} == {"COA", "TAM"}


def test_overtime_phase_in_agrees_with_the_workweek_rows():
    c = _c()
    _need(c.MX_WORKWEEK, "workweek")
    for row in c.MX_WORKWEEK:
        on = row.effective_from
        scalar = c.scalar_rows_in_force(on)["mx_overtime_double_weekly_max_hours"].flat_amount
        assert dict(row.overtime_rules)["overtime_weekly_hours"] == scalar, on
    hours = [int(w.ordinary_weekly_max_hours) for w in sorted(c.MX_WORKWEEK, key=lambda w: w.effective_from)]
    assert hours == sorted(hours, reverse=True) and hours[-1] < hours[0]


def test_subsidy_remainder_rule_is_in_the_engine_vocabulary():
    c = _c()
    rows = [r for r in c.MX_SCALAR_CONTENT if r.key == "mx_subsidy_remainder_rule"]
    _need(rows, "subsidy remainder rule")
    from app.modules.payroll.engine.jurisdictions.mexico.subsidy import REMAINDER_RULES

    assert [r.text_value for r in rows] == ["NOT_PAYABLE"] and "NOT_PAYABLE" in REMAINDER_RULES
    assert rows[0].source == "S3/S3_DOF_Decreto_subsidio_empleo_01052024.html"


# ── W1-1 (2026-10-26): SBC floor and INFONAVIT percentage basis ──

def test_sbc_floor_rule_is_in_the_engine_vocabulary_and_cites_lss_art_28():
    c = _c()
    rows = [r for r in c.MX_SCALAR_CONTENT if r.key == "mx_sbc_min_rule"]
    _need(rows, "SBC floor rule")
    from app.modules.payroll.engine.jurisdictions.mexico.sbc import SBC_MIN_RULES

    assert [r.text_value for r in rows] == ["RAISE_TO_ZONE_MIN_WAGE"] and rows[0].text_value in SBC_MIN_RULES
    assert rows[0].source == "S10/S10_IMSS_LSS.pdf" and rows[0].source_ref.startswith("Art. 28")
    assert "limite inferior" in rows[0].source_ref


def test_infonavit_bases_percentage_transcribed_fixed_amount_still_blocks():
    c = _c()
    rows = [r for r in c.MX_SCALAR_CONTENT if r.key == "mx_infonavit_percentage_basis"]
    _need(rows, "INFONAVIT percentage basis")
    from app.modules.payroll.engine.jurisdictions.mexico.infonavit import BASIS_RULES

    assert [r.text_value for r in rows] == ["SBC_TIMES_DAYS"] and rows[0].text_value in BASIS_RULES["PERCENTAGE"][1]
    assert rows[0].source == "S27/S27_DIP_LIFNVT.pdf" and rows[0].source_ref.startswith("Art. 29 III")
    # S27 states no per-period rule for a fixed-amount discount: it stays untranscribed and blocks
    assert not [r for r in c.MX_SCALAR_CONTENT if r.key == "mx_infonavit_fixed_amount_basis"]


def test_ceilings_read_in_uma_cite_the_de_indexation_decree():
    c = _c()
    rows = {r.key: r for r in c.MX_SCALAR_CONTENT if r.key in ("mx_sbc_max_uma_multiple", "mx_imss_em_excess_threshold_uma")}
    _need(rows, "SBC ceiling / E&M threshold")
    assert all("S34 Transitorio Tercero" in r.source_ref for r in rows.values())
    assert "S34" in c.ALL_SOURCE_CODES


# ── W1-2 (2026-10-26): CDMX state ISN ──

def test_cdmx_isn_rate_cites_the_verified_2026_code():
    c = _c()
    rows = c.MX_ISN_CONTENT["CDMX"]
    _need(rows, "CDMX ISN")
    assert [(r.key, r.employer_pct, r.employee_pct) for r in rows] == [("mx_isn_rate_pct", "4", None)]
    assert rows[0].source == "S22/S22_SAF_Codigo_Fiscal_CDMX_2026.pdf" and rows[0].source_ref.startswith("Art. 158")
    assert c.isn_rows_in_force("CDMX", date(2026, 6, 30))["mx_isn_rate_pct"] is rows[0]
    # the 2022 text (3%) is WRONG_VERSION and is never cited
    assert not any("S22_CDMX_Codigo_Fiscal_2026.pdf" in r.source for r in rows)


def test_cdmx_special_pay_isn_inclusion_follows_arts_156_and_157():
    c = _c()
    inc = {concept: entry[0] for (state, concept), entry in c.MX_SPECIAL_PAY_ISN_INCLUSION.items() if state == "CDMX"}
    _need(inc, "CDMX special-pay ISN inclusion")
    assert inc == {"AGUINALDO": True, "VACATION_PREMIUM": True, "SEPARATION_SENIORITY_PREMIUM": True, "PTU": False}
    from app.modules.payroll.engine.jurisdictions.mexico import special_pay
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    assert set(inc) <= set(special_pay.CONCEPTS)
    # not named by Art. 156 or 157: they keep blocking (DECISIONS_PENDING D-06)
    for concept in ("VACATION_PAYOUT", "SEPARATION_PAYMENT", "SEPARATION_INDEMNITY"):
        with pytest.raises(MXBlock) as exc:
            special_pay.isn_included("CDMX", concept)
        assert exc.value.reasons[0][0] == "MX_ISN_SPECIAL_PAY_RULE_MISSING"
    for (state, concept), (included, source, ref) in c.MX_SPECIAL_PAY_ISN_INCLUSION.items():
        assert source == "S22/S22_SAF_Codigo_Fiscal_CDMX_2026.pdf" and ref.startswith(("Art. 156", "Art. 157"))
        assert included == ref.startswith("Art. 156")      # 156 lists what is taxed, 157 what is not
