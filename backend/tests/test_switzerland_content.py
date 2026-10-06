"""
tests/test_switzerland_content.py
---------------------------------
Coverage for the Step 3 Switzerland catalog: the Draft canonical content
(switzerland_content.py), the canonical-pack seed (seed_switzerland_
canonical_packs.py), the jurisdiction schema / name maps (core/jurisdiction.py
as schema-only, never REGISTRATION_COUNTRIES) and the employee-level AHV/AVS
EAN-13 validator (employee_validation.py). Content values are asserted against
the published 2026 federal statutory figures the module cites (S1-S10); every
row is needs_g1 and every pack seeds as Draft.
"""
import re

import pytest

from app.core.exceptions import BadRequestException
from app.core.jurisdiction import (
    CODE_TO_COUNTRY_NAME, COUNTRY_NAME_TO_CODE, JURISDICTION_TAX_SCHEMAS, REGISTRATION_COUNTRIES,
    get_jurisdiction_code,
)
from app.modules.billing.models import JurisdictionServiceRegistry
from app.modules.payroll.employee_validation import (
    CHEmployeeValidation, get_employee_validation_strategy, mask_identifier, swiss_ahv_number_is_valid,
)
from app.modules.payroll.engine.countries.switzerland_content import (
    CH_AHV, CH_ALV, CH_BVG, CH_CANTON_CODES, CH_CANTON_PARAMETER_KEYS, CH_CANTONS, CH_FEDERAL_PARAMETER_KEYS,
    CH_FEDERAL_SEED_2026, CH_KTG, CH_LA, CH_OBLIGATIONS, CH_PARAMETER_KEYS, CH_QST, CH_QST_ANNUAL_MODEL_CANTONS,
    CH_QST_MODELS, CH_SCHEME_TYPES, CH_SOURCES, CH_UVG, CH_WAGE_FLOOR, CH_YTD_COMPONENTS,
)
from app.modules.payroll.models import ContributionRate, JurisdictionPack
from scripts.seed_switzerland_canonical_packs import FEDERAL_PACK_ID, FUTURE_PACK_ID, seed_switzerland

# The 26 Swiss cantons, ISO 3166-2:CH.
ISO_CANTONS = {
    "CH-AG", "CH-AI", "CH-AR", "CH-BE", "CH-BL", "CH-BS", "CH-FR", "CH-GE", "CH-GL", "CH-GR",
    "CH-JU", "CH-LU", "CH-NE", "CH-NW", "CH-OW", "CH-SG", "CH-SH", "CH-SO", "CH-SZ", "CH-TG",
    "CH-TI", "CH-UR", "CH-VD", "CH-VS", "CH-ZG", "CH-ZH",
}


# ── Content catalog ─────────────────────────────────────────────────────────

def test_26_cantons_cover_the_exact_iso_sets():
    assert len(CH_CANTONS) == 26
    assert len(CH_CANTON_CODES) == 26
    assert len(set(CH_CANTON_CODES)) == 26          # no duplicates
    assert set(CH_CANTON_CODES) == ISO_CANTONS
    assert {code for code, _name in CH_CANTONS} == set(CH_CANTON_CODES)


def test_canton_codes_and_names_are_well_formed():
    for code, name in CH_CANTONS:
        assert re.fullmatch(r"CH-[A-Z]{2}", code), code
        assert len(name) <= 40, name
    assert len({name for _code, name in CH_CANTONS}) == 26   # unique names too


def test_qst_models_and_annual_model_cantons():
    assert CH_QST_MODELS == ("MONTHLY", "ANNUAL")
    assert CH_QST_ANNUAL_MODEL_CANTONS <= set(CH_CANTON_CODES)
    assert CH_QST_ANNUAL_MODEL_CANTONS == {"CH-FR", "CH-GE", "CH-TI", "CH-VD", "CH-VS"}


def test_scheme_types_are_the_five_swiss_plugins():
    assert len(CH_SCHEME_TYPES) == 5
    assert CH_SCHEME_TYPES == ("COMPENSATION_OFFICE", "FAK", "BVG_PLAN", "UVG_POLICY", "KTG_POLICY")


def test_ytd_components_and_obligations_vocabulary():
    assert CH_YTD_COMPONENTS == (CH_AHV, CH_ALV, CH_UVG, CH_BVG, CH_KTG, CH_QST)
    assert CH_OBLIGATIONS == (CH_AHV, CH_ALV, CH_BVG, CH_UVG, CH_KTG, CH_QST, CH_LA, CH_WAGE_FLOOR)
    assert len(set(CH_OBLIGATIONS)) == len(CH_OBLIGATIONS)
    # CH_LA and CH_WAGE_FLOOR are declaration/classification vocabulary — they
    # are obligations but never rate rows.
    assert CH_LA not in CH_PARAMETER_KEYS
    assert CH_WAGE_FLOOR not in CH_PARAMETER_KEYS


def test_parameter_keys_cover_federal_and_canton_keys_without_drift():
    federal_keys = {row[0] for row in CH_FEDERAL_SEED_2026}
    assert set(CH_FEDERAL_PARAMETER_KEYS) == federal_keys
    assert set(CH_CANTON_PARAMETER_KEYS) == {"ch_qst_model", "ch_qst_tariff_file_id",
                                             "ch_fak_child", "ch_fak_education", "ch_fak_employee_pct"}
    assert set(CH_PARAMETER_KEYS) == federal_keys | set(CH_CANTON_PARAMETER_KEYS)


def test_every_federal_row_is_sourced_g1_flagged_and_well_shaped():
    refs = {ref for ref, _title, _url in CH_SOURCES}
    for row in CH_FEDERAL_SEED_2026:
        key, label, ee, er, flat, source, needs_g1 = row
        assert key in CH_FEDERAL_PARAMETER_KEYS, key
        assert source in refs, key
        assert needs_g1 is True, key        # nothing here is sourceable yet — all Draft
        assert len(key) <= 50, key
        assert len(label) <= 100, label
        # exactly one value kind per row (either pct pair, ee-only, or flat)
        assert sum(v is not None for v in (ee, er, flat)) >= 1, key
        assert not ((er is not None and flat is not None) or (ee is not None and flat is not None)), key


def test_federal_values_match_the_published_2026_figures():
    rows = {row[0]: row for row in CH_FEDERAL_SEED_2026}
    # S1-S3 — federal contribution pairs (employee / employer).
    assert rows["ch_ahv"][2] == "4.35" and rows["ch_ahv"][3] == "4.35"
    assert rows["ch_iv"][2] == "0.70" and rows["ch_iv"][3] == "0.70"
    assert rows["ch_eo"][2] == "0.25" and rows["ch_eo"][3] == "0.25"
    # S4 — ALV.
    assert rows["ch_alv"][2] == "1.10" and rows["ch_alv"][3] == "1.10"
    assert rows["ch_alv_ceiling"][4] == "148200.00"
    # S5 — UVG.
    assert rows["ch_uvg_ceiling"][4] == "148200.00"
    assert rows["ch_nbu_min_weekly_hours"][4] == "8.00"
    # S6 — BVG 2026 measures.
    assert rows["ch_bvg_entry_threshold"][4] == "22680.00"
    assert rows["ch_bvg_coordination_deduction"][4] == "26460.00"
    assert rows["ch_bvg_upper_salary"][4] == "90720.00"
    assert rows["ch_bvg_min_coordinated"][4] == "3780.00"
    # S7 — EO parental allowance.
    assert rows["ch_eo_parental_pct"][2] == "80.00"
    assert rows["ch_eo_daily_cap"][4] == "220.00"
    # S8 — FAK federal minimums and threshold.
    assert rows["ch_fak_child_min"][4] == "215.00"
    assert rows["ch_fak_education_min"][4] == "268.00"
    assert rows["ch_fak_earnings_threshold_month"][4] == "630.00"
    assert rows["ch_fak_earnings_threshold_year"][4] == "7560.00"
    # S10 — Swiss rounding convention.
    assert rows["ch_rounding_rule"][4] == "0.05"


# ── AHV/AVS EAN-13 validator ─────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "756.1234.5678.97",
    "7569217076985",        # 756.9217.0769.85 — check digit computed end to end
    "756.9217.0769.85",
    "756  1234 5678 97",    # spacing tolerated
])
def test_ahv_numbers_with_correct_check_digit_are_valid(value):
    assert swiss_ahv_number_is_valid(value)


@pytest.mark.parametrize("value", [
    "756.1234.5678.98",     # wrong EAN-13 check digit
    "757.1234.5678.97",     # wrong national prefix (not 756)
    "756.1234.5678",        # only 12 digits
    "756.1234.5678.971",    # 14 digits
    "756.1234.5678.9X",     # non-digit check position
    "0", "text", "",
])
def test_ahv_numbers_with_bad_shapes_are_invalid(value):
    assert not swiss_ahv_number_is_valid(value)


def test_ahv_number_none_is_invalid():
    assert not swiss_ahv_number_is_valid(None)
    assert not swiss_ahv_number_is_valid("")


def test_ch_employee_strategy_required_dispatch_and_check_digit():
    assert get_employee_validation_strategy("CH") is CHEmployeeValidation
    with pytest.raises(BadRequestException):
        CHEmployeeValidation.validate({})
    cleaned = CHEmployeeValidation.validate({"ahv_number": "756.1234.5678.97"})
    assert cleaned["ahv_number"] == "7561234567897"
    with pytest.raises(BadRequestException, match="check digit"):
        CHEmployeeValidation.validate({"ahv_number": "756.1234.5678.98"})


def test_ch_employee_strategy_masks_and_deduplicates_ahv():
    assert CHEmployeeValidation.duplicate_field == "ahv_number"
    assert CHEmployeeValidation.SENSITIVE_FIELDS == ("ahv_number",)
    mask = mask_identifier("7561234567897")
    assert mask.endswith("7897") and "7561234567897" not in mask


# ── Jurisdiction schema (schema only — NEVER registration) ─────────────────

def test_ch_jurisdiction_schema_is_present_and_chf():
    schema = JURISDICTION_TAX_SCHEMAS["CH"]
    assert schema["currency"] == "CHF"
    keys = [f["key"] for f in schema["fields"]]
    assert keys == ["uid", "ahv_employer_number", "compensation_office"]
    assert next(f for f in schema["fields"] if f["primary"])["key"] == "uid"


def test_ch_uid_pattern_accepts_real_format_only():
    uid = next(f for f in JURISDICTION_TAX_SCHEMAS["CH"]["fields"] if f["key"] == "uid")
    assert re.fullmatch(uid["pattern"], "CHE-123.456.789")
    assert not re.fullmatch(uid["pattern"], "CHE-123.456.78")
    assert not re.fullmatch(uid["pattern"], "123.456.789")


def test_ch_stays_out_of_registration_countries():
    assert all(c.lower() != "switzerland" for c in REGISTRATION_COUNTRIES)
    assert "CH" not in REGISTRATION_COUNTRIES


def test_name_maps_resolve_switzerland():
    assert COUNTRY_NAME_TO_CODE["switzerland"] == "CH"
    assert COUNTRY_NAME_TO_CODE["swiss confederation"] == "CH"
    assert CODE_TO_COUNTRY_NAME["CH"] == "Switzerland"
    assert get_jurisdiction_code("Switzerland") == "CH"
    assert get_jurisdiction_code("switzerland") == "CH"
    assert get_jurisdiction_code("CH") == "CH"


# ── Canonical-pack seed on the isolated SQLite fixture ─────────────────────

def _ch_pack_counts(db):
    counts = {}
    for pack in db.query(JurisdictionPack).all():
        counts[pack.pack_id] = (db.query(ContributionRate)
                                .filter(ContributionRate.jurisdiction_pack_id == pack.id).count())
    counts["_pack_total"] = db.query(JurisdictionPack).count()
    return counts


def test_ch_seed_writes_federal_pack_as_draft_with_all_18_rates(db):
    out = seed_switzerland(db)
    db.flush()
    federal = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == FEDERAL_PACK_ID).one()
    assert federal.status == "Draft"
    assert federal.jurisdiction_state is None
    assert str(federal.effective_from) == "2026-01-01"
    rates = (db.query(ContributionRate)
             .filter(ContributionRate.jurisdiction_pack_id == federal.id,
                     ContributionRate.organization_id.is_(None)).all())
    assert len(rates) == len(CH_FEDERAL_SEED_2026) == len(CH_FEDERAL_PARAMETER_KEYS) == 18
    assert {r.component_key for r in rates} == set(CH_FEDERAL_PARAMETER_KEYS)
    assert all(r.jurisdiction_country == "CH" for r in rates)
    assert all(r.jurisdiction_state is None for r in rates)      # country-scoped
    assert out["federal"].id == federal.id


def test_ch_seed_writes_26_canton_scaffold_packs(db):
    seed_switzerland(db)
    db.flush()
    packs = (db.query(JurisdictionPack)
             .filter(JurisdictionPack.pack_id.in_([f"{c}-PAYROLL-2026" for c in CH_CANTON_CODES])).all())
    assert len(packs) == 26
    for pack in packs:
        assert pack.status == "Draft"
        assert pack.jurisdiction_state in set(CH_CANTON_CODES)
        rows = (db.query(ContributionRate)
                .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                        ContributionRate.organization_id.is_(None)).all())
        assert len(rows) == len(CH_CANTON_PARAMETER_KEYS) == 5
        assert {r.component_key for r in rows} == set(CH_CANTON_PARAMETER_KEYS)
        assert all(r.jurisdiction_country == "CH" for r in rows)
        assert all(r.jurisdiction_state == pack.jurisdiction_state for r in rows)
        # inert scaffolds: every value cell is NULL so the engine cannot
        # calculate from a canton parameter yet.
        assert all(r.employee_rate_pct is None for r in rows)
        assert all(r.employer_rate_pct is None for r in rows)
        assert all(r.flat_amount is None for r in rows)


def test_ch_seed_writes_future_change_watch_pack_with_no_rows(db):
    seed_switzerland(db)
    db.flush()
    future = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == FUTURE_PACK_ID).one()
    assert future.status == "Draft"
    assert future.jurisdiction_state is None
    assert str(future.effective_from) == "2027-07-01"
    rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == future.id).count()
    assert rows == 0


def test_ch_registry_row_is_created_planned_only_once(db):
    seed_switzerland(db)
    db.flush()
    rows = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "CH").all()
    assert len(rows) == 1
    assert rows[0].availability == "PLANNED"
    assert rows[0].payment_execution_responsibility == "NOT_OFFERED"


def test_ch_seed_is_idempotent_on_rerun(db):
    seed_switzerland(db)
    db.flush()
    first = _ch_pack_counts(db)
    seed_switzerland(db)
    db.flush()
    assert _ch_pack_counts(db) == first
    assert db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "CH").count() == 1


def test_ch_seed_refuses_to_rewrite_a_pack_that_left_draft(db):
    seed_switzerland(db)
    db.flush()
    federal = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == FEDERAL_PACK_ID).one()
    federal.status = "Active"
    db.flush()
    with pytest.raises(SystemExit):
        seed_switzerland(db)