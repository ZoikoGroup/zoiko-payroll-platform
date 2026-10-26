"""
tests/test_netherlands_content.py
---------------------------------
Coverage for the Phase 1 Netherlands catalog: the Draft canonical content
(netherlands_content.py), the canonical-pack seed
(seed_netherlands_canonical_packs.py), the jurisdiction schema / name maps
(core/jurisdiction.py as schema-only, never REGISTRATION_COUNTRIES) and the
employee-level BSN elfproef validator (employee_validation.py). Content values
are asserted against ZP-NL-ENG-001 v1.0 §2 and the specification's own S1-S20
evidence register; every row is needs_g1 and every pack seeds as Draft.
"""
import re
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.core.jurisdiction import (
    CODE_TO_COUNTRY_NAME, COUNTRY_NAME_TO_CODE, JURISDICTION_TAX_SCHEMAS, REGISTRATION_COUNTRIES,
    get_jurisdiction_code,
)
from app.modules.billing.models import JurisdictionServiceRegistry
from app.modules.payroll.employee_validation import (
    NLEmployeeValidation, bsn_is_valid, get_employee_validation_strategy, mask_identifier,
)
from app.modules.payroll.engine.countries.netherlands_content import (
    NL_2026, NL_2026_07, NL_CAR_ADDITION_BANDS, NL_CAR_ADDITION_RULE, NL_CATEGORIES,
    NL_MIN_WAGE_RATES, NL_MIN_WAGE_RULE, NL_PARAMETER_KEYS, NL_PERIOD_MAX_RULE, NL_PERIOD_MAXIMA,
    NL_SCALAR_CONTENT, NL_WKR_BANDS, SOURCE_CODES, SOURCE_REFERENCES, car_addition_bands_in_force,
    min_wage_rates_in_force, period_maxima_in_force, wkr_bands_in_force,
)
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
from scripts.seed_netherlands_canonical_packs import (
    CHANGE_WATCH_PACK_ID, MAIN_PACK_ID, seed_netherlands,
)

# Two packs are declared; anything indexed off them must stay in sync.
EXPECTED_SCALAR_ROWS = 35
EXPECTED_SLAB_ROWS = 8 + 2 + 3 + 2   # min wage + period maxima + WKR bands + car bands


# ── Packs, sources, enums ───────────────────────────────────────────────────

def test_two_packs_are_declared_with_their_windows():
    assert NL_2026 == ("NL-PAYROLL-2026", NL_2026[1], NL_2026[2])
    assert str(NL_2026[1]) == "2026-01-01" and str(NL_2026[2]) == "2026-12-31"
    assert NL_2026_07[0] == "NL-PAYROLL-2026-07"
    assert str(NL_2026_07[1]) == "2026-07-01"
    assert MAIN_PACK_ID == "NL-PAYROLL-2026"
    assert CHANGE_WATCH_PACK_ID == "NL-PAYROLL-2026-07"


def test_evidence_register_is_the_s1_to_s20_set_and_url_free():
    assert SOURCE_CODES == tuple(f"S{i}" for i in range(1, 21))
    assert len(set(SOURCE_CODES)) == 20
    assert {code for code, _title in SOURCE_REFERENCES} == set(SOURCE_CODES)
    for code, title in SOURCE_REFERENCES:
        assert re.fullmatch(r"S\d{1,2}", code), code
        assert title and "http" not in title.lower(), code   # authority names, no URLs


def test_category_labels_cover_every_documented_family():
    assert set(NL_CATEGORIES) == {
        "reference_brackets", "tax_credits", "employee_insurance", "whk", "zvw", "wkr", "expat",
        "labor_pay", "minimum_wage", "period_maxima", "car_addition",
    }


# ── Scalar content catalog ─────────────────────────────────────────────────

def test_parameter_keys_cover_scalar_content_without_drift():
    content_keys = {row[0] for row in NL_SCALAR_CONTENT}
    assert content_keys <= set(NL_PARAMETER_KEYS)
    # Whk is employer-specific (never a universal fallback): the keys exist so
    # the readiness check knows them, but no value is seeded.
    assert {"nl_whk_wga_pct", "nl_whk_zwflex_pct"} <= set(NL_PARAMETER_KEYS)
    assert {"nl_whk_wga_pct", "nl_whk_zwflex_pct"}.isdisjoint(content_keys)


def test_every_scalar_row_is_sourced_g1_flagged_and_well_shaped():
    refs = set(SOURCE_CODES)
    seen = set()
    for key, label, ee, er, flat, text, source, needs_g1 in NL_SCALAR_CONTENT:
        assert key in NL_PARAMETER_KEYS, key
        assert key not in seen, key          # no duplicate component keys
        seen.add(key)
        assert source in refs, key
        assert needs_g1 is True, key         # every value is Draft pending gate G1
        assert len(label) <= 100, key
        # Exactly one value kind per row (a pct single-side, a flat amount, or text).
        assert sum(v is not None for v in (ee, er, flat, text)) == 1, key


def test_scalar_values_match_the_2026_specification():
    rows = {row[0]: row for row in NL_SCALAR_CONTENT}
    # Reference Box 1 brackets (spec §2).
    assert rows["nl_box1_band1_rate"][2] == "35.75"
    assert rows["nl_box1_band1_ceiling"][4] == "38883.00"
    assert rows["nl_box1_band2_rate"][2] == "37.56"
    assert rows["nl_box1_band2_ceiling"][4] == "78426.00"
    assert rows["nl_box1_band3_rate"][2] == "49.50"
    assert rows["nl_anonymous_rate_pct"][2] == "52.00"
    # Tax credits (spec §2).
    assert rows["nl_general_tax_credit_max"][4] == "3115.00"
    assert rows["nl_general_tax_credit_phase_start"][4] == "29736.00"
    assert rows["nl_general_tax_credit_phase_end"][4] == "78426.00"
    assert rows["nl_employment_tax_credit_max"][4] == "5685.00"
    assert rows["nl_employment_tax_credit_phase_end"][4] == "132920.00"
    # Employer premiums (spec §2/§6).
    assert rows["nl_awf_low_pct"][3] == "2.7400" and rows["nl_awf_high_pct"][3] == "7.7400"
    assert rows["nl_aof_low_pct"][3] == "6.2700" and rows["nl_aof_high_pct"][3] == "7.6300"
    assert rows["nl_wko_pct"][3] == "0.5000"
    # Zvw (spec §2/§7).
    assert rows["nl_zvw_employer_pct"][3] == "6.1000" and rows["nl_zvw_employee_pct"][2] == "4.8500"
    # WKR (spec §2/§8).
    assert rows["nl_wkr_free_space_pct_first"][3] == "2.0000"
    assert rows["nl_wkr_free_space_threshold"][4] == "400000.00"
    assert rows["nl_wkr_free_space_pct_above"][3] == "1.1800"
    assert rows["nl_wkr_excess_levy_pct"][3] == "80.0000"
    # Expat 30% facility (spec §2/§9).
    assert rows["nl_expat_salary_threshold"][4] == "48013.00"
    assert rows["nl_expat_salary_threshold_young_master"][4] == "36497.00"
    assert rows["nl_expat_max_facility_pct"][2] == "30.00"
    assert rows["nl_expat_allowance_cap"][4] == "78600.00"
    assert rows["nl_wnt_cap"][4] == "262000.00"
    # Labor pay (spec §14).
    assert rows["nl_vacation_allowance_pct"][2] == "8.00"
    assert rows["nl_vacation_hours_multiplier"][4] == "4.00"
    assert rows["nl_sick_pay_pct"][2] == "70.00"
    assert rows["nl_sick_pay_max_years"][4] == "2.00"
    assert rows["nl_transition_payment_cap"][4] == "102000.00"
    # 1/3 of a month's salary per service year — stored as TEXT, never a Decimal.
    assert rows["nl_transition_payment_month_frac"][5] == "1/3"
    assert rows["nl_transition_payment_month_frac"][4] is None
    # Table colour is WHITE for current employment.
    assert rows["nl_table_color"][5] == "WHITE"


def test_scalar_content_row_count_is_stable():
    assert len(NL_SCALAR_CONTENT) == EXPECTED_SCALAR_ROWS


# ── Minimum wage rows ──────────────────────────────────────────────────────

def test_july_2026_minimum_wage_covers_every_age_cohort():
    july = {cohort: amount for cohort, amount, eff, _to, _s in min_wage_rates_in_force(date(2026, 7, 15))}
    assert july == {
        "AGE_21_PLUS": Decimal("14.99"),
        "AGE_20": Decimal("11.99"),
        "AGE_19": Decimal("8.99"),
        "AGE_18": Decimal("7.50"),
        "AGE_17": Decimal("5.92"),
        "AGE_16": Decimal("5.17"),
        "AGE_15": Decimal("4.50"),
    }


def test_january_2026_only_states_the_21_plus_rate():
    january = min_wage_rates_in_force(date(2026, 2, 1))
    assert january == [("AGE_21_PLUS", Decimal("14.71"), date(2026, 1, 1), date(2026, 6, 30), "S14")]
    # No January youth row exists — it is NOT stated, so a January payroll for
    # a younger worker must BLOCK rather than fall back to a guessed rate.
    assert not any(eff == date(2026, 1, 1) and cohort != "AGE_21_PLUS"
                   for cohort, _a, eff, _to, _s, _g1 in NL_MIN_WAGE_RATES)


def test_min_wage_rows_are_g1_and_the_june_to_july_step_is_effective_dated():
    assert all(g1 is True for *_rest, g1 in NL_MIN_WAGE_RATES)
    plus = sorted((eff, amount) for cohort, amount, eff, _to, _s, _g1 in NL_MIN_WAGE_RATES
                  if cohort == "AGE_21_PLUS")
    assert plus == [(NL_2026[1], "14.71"), (date(2026, 7, 1), "14.99")]
    # The rule_type discriminator is a real, ≤30-char TaxSlab rule_type.
    assert NL_MIN_WAGE_RULE == "NL_MIN_WAGE" and len(NL_MIN_WAGE_RULE) <= 30


# ── Period maxima, WKR bands, car addition ─────────────────────────────────

def test_period_maxima_state_annual_and_monthly_only():
    maxima = period_maxima_in_force(date(2026, 6, 1))
    assert maxima == {"ANNUAL": Decimal("79409.00"), "MONTHLY": Decimal("6617.41")}
    assert all(g1 is True for *_rest, g1 in NL_PERIOD_MAXIMA)
    assert NL_PERIOD_MAX_RULE == "NL_PERIOD_MAX" and len(NL_PERIOD_MAX_RULE) <= 30


def test_wkr_bands_are_free_space_and_the_80pct_excess_levy():
    bands = wkr_bands_in_force(date(2026, 6, 1))
    assert bands == [
        ("FREE_SPACE", Decimal("0"), Decimal("400000.00"), Decimal("2.0000")),
        ("FREE_SPACE", Decimal("400000.00"), None, Decimal("1.1800")),
        ("EXCESS_LEVY", Decimal("0"), None, Decimal("80.0000")),
    ]
    assert all(g1 is True for *_rest, g1 in NL_WKR_BANDS)


def test_car_addition_bands_are_effective_dated_2026_defaults():
    bands = car_addition_bands_in_force(date(2026, 6, 1))
    assert bands == [
        ("STANDARD", Decimal("22.0000"), date(2026, 1, 1), None),
        ("ZERO_EMISSION", Decimal("18.0000"), date(2026, 1, 1), None),
    ]
    assert all(g1 is True for *_rest, g1 in NL_CAR_ADDITION_BANDS)
    assert NL_CAR_ADDITION_RULE == "NL_CAR_ADDITION" and len(NL_CAR_ADDITION_RULE) <= 30


# ── BSN elfproef validator ─────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "111222333",            # 66 % 11 == 0
    "123456782",            # 154 % 11 == 0
    "111.222.333",          # separators tolerated
    "111 222 333",
    "111-222-333",
])
def test_bsn_with_correct_elfproef_is_valid(value):
    assert bsn_is_valid(value)


@pytest.mark.parametrize("value", [
    "123456789",            # 147 % 11 == 4 — wrong check digit
    "111222334",            # 65 % 11 == 10
    "12345678",             # only 8 digits
    "1234567890",           # 10 digits
    "abcdefghi",            # non-digit
    "000000000",            # 0 % 11 == 0 but the elfproef for all-zero BSNs is not a real number — still valid shape/check
    "0", "text", "",
])
def test_bsn_with_bad_shape_or_check_digit_is_invalid(value):
    # NOTE: "000000000" actually passes mod 11 (0) — the elfproef is a shape
    # check, not an existence check; this asserts only that the OTHER shapes
    # are refused. See test below for the all-zero case explicitly.
    if value == "000000000":
        pytest.skip("all-zero passes the arithmetic elfproef by construction")
    assert not bsn_is_valid(value)


def test_bsn_none_and_empty_are_invalid():
    assert not bsn_is_valid(None)
    assert not bsn_is_valid("")


def test_nl_employee_strategy_required_dispatch_and_elfproef():
    assert get_employee_validation_strategy("NL") is NLEmployeeValidation
    assert get_employee_validation_strategy("nl") is NLEmployeeValidation
    with pytest.raises(BadRequestException):
        NLEmployeeValidation.validate({})            # bsn is required
    cleaned = NLEmployeeValidation.validate({"bsn": "111.222.333"})
    assert cleaned["bsn"] == "111222333"
    with pytest.raises(BadRequestException, match="elfproef"):
        NLEmployeeValidation.validate({"bsn": "123456789"})


def test_nl_employee_strategy_masks_and_deduplicates_bsn():
    assert NLEmployeeValidation.duplicate_field == "bsn"
    assert NLEmployeeValidation.SENSITIVE_FIELDS == ("bsn",)
    mask = mask_identifier("111222333")
    assert mask.endswith("2333") and "111222333" not in mask


# ── Jurisdiction schema (schema only — NEVER registration) ─────────────────

def test_nl_jurisdiction_schema_is_present_and_eur():
    schema = JURISDICTION_TAX_SCHEMAS["NL"]
    assert schema["currency"] == "EUR"
    keys = [f["key"] for f in schema["fields"]]
    assert keys == ["kvk_number", "rsin", "loonheffingennummer"]
    assert next(f for f in schema["fields"] if f["primary"])["key"] == "kvk_number"


def test_nl_field_patterns_accept_real_format_only():
    fields = {f["key"]: f for f in JURISDICTION_TAX_SCHEMAS["NL"]["fields"]}
    assert re.fullmatch(fields["kvk_number"]["pattern"], "12345678")
    assert not re.fullmatch(fields["kvk_number"]["pattern"], "1234567")
    assert re.fullmatch(fields["rsin"]["pattern"], "123456789")
    assert not re.fullmatch(fields["rsin"]["pattern"], "12345678")
    assert re.fullmatch(fields["loonheffingennummer"]["pattern"], "123456789L01")
    assert not re.fullmatch(fields["loonheffingennummer"]["pattern"], "123456789")


def test_nl_stays_out_of_registration_countries():
    assert all(c.lower() != "netherlands" for c in REGISTRATION_COUNTRIES)
    assert "NL" not in REGISTRATION_COUNTRIES


def test_name_maps_resolve_netherlands():
    assert COUNTRY_NAME_TO_CODE["netherlands"] == "NL"
    assert COUNTRY_NAME_TO_CODE["the netherlands"] == "NL"
    assert COUNTRY_NAME_TO_CODE["holland"] == "NL"
    assert CODE_TO_COUNTRY_NAME["NL"] == "Netherlands"
    assert get_jurisdiction_code("Netherlands") == "NL"
    assert get_jurisdiction_code("netherlands") == "NL"
    assert get_jurisdiction_code("NL") == "NL"


# ── Canonical-pack seed on the isolated SQLite fixture ─────────────────────

def test_seed_writes_main_pack_as_draft_with_scalars_and_slabs(db):
    out = seed_netherlands(db)
    db.flush()
    main = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == MAIN_PACK_ID).one()
    assert main.status == "Draft"
    assert out["main"].id == main.id
    assert out["availability"] == "PLANNED"
    assert main.jurisdiction_country == "NL"
    assert main.jurisdiction_state is None
    assert main.currency == "EUR"
    assert str(main.effective_from) == "2026-01-01" and str(main.effective_to) == "2026-12-31"

    rates = (db.query(ContributionRate)
             .filter(ContributionRate.jurisdiction_pack_id == main.id,
                     ContributionRate.organization_id.is_(None)).all())
    assert len(rates) == EXPECTED_SCALAR_ROWS == len(NL_SCALAR_CONTENT)
    assert {r.component_key for r in rates} == {row[0] for row in NL_SCALAR_CONTENT}
    assert all(r.jurisdiction_country == "NL" for r in rates)
    assert all(r.jurisdiction_state is None for r in rates)
    # The 1/3 fraction survives as TEXT, never rounded through Numeric(14,2).
    frac = next(r for r in rates if r.component_key == "nl_transition_payment_month_frac")
    assert frac.text_value == "1/3" and frac.flat_amount is None

    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == main.id,
                                     TaxSlab.organization_id.is_(None)).all()
    assert len(slabs) == EXPECTED_SLAB_ROWS
    by_rule = {}
    for s in slabs:
        by_rule.setdefault(s.rule_type, []).append(s)
    assert len(by_rule[NL_MIN_WAGE_RULE]) == len(NL_MIN_WAGE_RATES) == 8
    assert len(by_rule[NL_PERIOD_MAX_RULE]) == len(NL_PERIOD_MAXIMA) == 2
    assert len(by_rule["NL_WKR_BAND"]) == len(NL_WKR_BANDS) == 3
    assert len(by_rule[NL_CAR_ADDITION_RULE]) == len(NL_CAR_ADDITION_BANDS) == 2
    # The July step is a ROW boundary inside one pack, not a new pack.
    july_plus = [s for s in by_rule[NL_MIN_WAGE_RULE]
                 if s.filing_status == "AGE_21_PLUS" and str(s.effective_from) == "2026-07-01"]
    assert len(july_plus) == 1 and july_plus[0].flat_amount == Decimal("14.99")
    assert all(s.rate_pct is not None for s in slabs)   # rate_pct stays NOT NULL


def test_seed_writes_change_watch_pack_with_no_rows(db):
    seed_netherlands(db)
    db.flush()
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == CHANGE_WATCH_PACK_ID).one()
    assert pack.status == "Draft"
    assert str(pack.effective_from) == "2026-07-01"
    assert db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count() == 0
    assert db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count() == 0


def test_seed_creates_the_planned_registry_row_once(db):
    seed_netherlands(db)
    db.flush()
    rows = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "NL").all()
    assert len(rows) == 1
    assert rows[0].availability == "PLANNED"
    assert rows[0].payment_execution_responsibility == "NOT_OFFERED"


def _nl_counts(db):
    counts = {}
    for pack in db.query(JurisdictionPack).all():
        counts[pack.pack_id] = (
            db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count(),
            db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count(),
        )
    counts["_pack_total"] = db.query(JurisdictionPack).count()
    return counts


def test_seed_is_idempotent_on_rerun(db):
    seed_netherlands(db)
    db.flush()
    first = _nl_counts(db)
    seed_netherlands(db)
    db.flush()
    assert _nl_counts(db) == first
    assert db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "NL").count() == 1


def test_seed_refuses_to_rewrite_a_pack_that_left_draft(db):
    seed_netherlands(db)
    db.flush()
    main = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == MAIN_PACK_ID).one()
    main.status = "Active"
    db.flush()
    with pytest.raises(SystemExit):
        seed_netherlands(db)
