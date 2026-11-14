"""Malaysia (ZP-MY-ENG-001) Phase 1: the 2026 content catalogue, the Draft seed
and the activation refusal. Values are pinned to the specification; anything
the specification does not state stays empty / PENDING_G1."""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.countries import malaysia_content as c


# ── catalogue shape ────────────────────────────────────────────────────────
def test_keys_are_unique_and_fit_the_column():
    keys = [row[0] for row in c.MALAYSIA_SCALAR_CONTENT]
    assert len(keys) == len(set(keys))
    assert all(len(k) <= 50 and k.startswith("my_") for k in keys)
    assert set(keys) == set(c.ALL_PARAMETER_KINDS)


def test_every_row_names_a_known_source_date_basis_and_territory():
    for row in c.MALAYSIA_SCALAR_CONTENT:
        key, src, basis, territory = row[0], row[6], row[10], row[11]
        assert src in c.SOURCE_CODES, key
        assert basis in c.DATE_BASES, key
        assert territory is None or territory in c.TERRITORIES, key
    assert set(c.SOURCE_URLS) == set(c.SOURCE_CODES) and len(c.SOURCE_CODES) == 15


def test_values_sit_in_the_slot_their_kind_names():
    slots = {"pct_employee": (2,), "pct_employer": (3,), "pct_both": (2, 3), "amount": (4,), "text": (5,)}
    for row in c.MALAYSIA_SCALAR_CONTENT:
        kind = c.ALL_PARAMETER_KINDS[row[0]]
        filled = {i for i in (2, 3, 4, 5) if row[i] is not None}
        assert filled <= set(slots[kind]), row[0]


def test_labour_law_exists_once_per_territory_never_nationally():
    for base in c.MALAYSIA_TERRITORY_KEYS:
        assert base not in c.ALL_PARAMETER_KINDS                          # no "Malaysia" labour row
        rows = [r for r in c.MALAYSIA_SCALAR_CONTENT if r[0].startswith(base + "__")]
        assert sorted(r[11] for r in rows) == sorted(c.TERRITORIES), base
    assert c.territory_key("my_maternity_days", "SABAH") == "my_maternity_days__SBH"
    assert "SABAH" in c.TERRITORIES and "LABUAN" not in c.TERRITORIES       # Labuan follows Peninsular law


def test_holiday_states_are_separate_from_labour_territories():
    assert len(c.HOLIDAY_STATES) == 16 and "LBN" in c.HOLIDAY_STATES
    assert not set(c.HOLIDAY_STATES) & set(c.TERRITORIES)


# ── values pinned to ZP-MY-ENG-001 ─────────────────────────────────────────
def _row(key):
    return next(r for r in c.MALAYSIA_SCALAR_CONTENT if r[0] == key)


@pytest.mark.parametrize("key, ee, er, flat, text", [
    ("my_min_wage_monthly", None, None, "1700", None),                     # §3
    ("my_epf_rate_my_pr_low", "11", "13", None, None),                     # §6
    ("my_epf_rate_my_pr_high", "11", "12", None, None),
    ("my_epf_rate_60_plus", "0", "4", None, None),
    ("my_epf_rate_pr_hist_60_plus_low", "5.5", "6.5", None, None),
    ("my_epf_rate_pr_hist_60_plus_high", "5.5", "6", None, None),
    ("my_epf_rate_non_malaysian", "2", "2", None, None),                   # MY-012: 2%/2%, not 12/12
    ("my_epf_wage_band_threshold", None, None, "5000", None),
    ("my_epf_schedule_upper_wage", None, None, "20000", None),
    ("my_socso_wage_ceiling", None, None, "6000", None),                   # §7
    ("my_eis_rate_ref", "0.2", "0.2", None, None),
    ("my_fw_lindung_employee_rate", "0.75", None, None, None),
    ("my_hrd_rate_compulsory", None, "1", None, None),                     # §8 employer-only
    ("my_hrd_rate_optional", None, "0.5", None, None),
    ("my_pcb_remittance_day", None, None, "15", None),                     # §3 / §11
    ("my_pcb_non_resident_rate", "30", None, None, None),                  # §5
    ("my_clearance_hold_max_days", None, None, "90", None),                # §10
    ("my_ea_due", None, None, None, "END_FEBRUARY"),                       # §11
    ("my_form_e_due", None, None, None, "END_MARCH"),
])
def test_values_stated_by_the_specification(key, ee, er, flat, text):
    row = _row(key)
    assert row[2:6] == (ee, er, flat, text) and row[7] is True


def test_effective_dates_from_the_specification():
    assert _row("my_epf_rate_non_malaysian")[8] == date(2025, 10, 1)      # from October 2025 wages
    assert _row("my_fw_lindung_employee_rate")[8] == date(2026, 6, 1)     # LINDUNG 24 JAM phase 1
    assert c.content_rows_in_force(date(2026, 5, 31)).get("my_fw_lindung_employee_rate") is None
    assert c.content_rows_in_force(date(2026, 6, 1))["my_fw_lindung_employee_rate"]


@pytest.mark.parametrize("territory", ["PENINSULAR_LABUAN", "SABAH", "SARAWAK"])
def test_territorial_values_stated_by_the_specification(territory):
    for base, value in (("my_weekly_hours_max", "45"), ("my_ot_exclusion_wage", "4000"),
                        ("my_maternity_days", "98"), ("my_paternity_days", "7")):
        assert _row(c.territory_key(base, territory))[4] == value


def test_nothing_unstated_is_guessed():
    for key in ("my_rounding_pcb", "my_pcb_spec_version", "my_epf_direct_calc_rule", "my_hrd_base_rule",
                "my_epf_due_rule", "my_transfer_split_rule"):
        assert _row(key)[5] == c.PENDING and _row(key)[7] is False, key
    for territory in c.TERRITORIES:
        for base in ("my_ot_multiplier_workday", "my_ot_multiplier_rest_day", "my_ot_multiplier_public_holiday",
                     "my_hospitalisation_days"):
            row = _row(c.territory_key(base, territory))
            assert row[2:6] == (None, None, None, None) and row[7] is False
    assert {"my_record_retention_years", "my_reconciliation_tolerance"} <= c.MALAYSIA_EMPTY_BY_DESIGN


def test_no_poland_content_leaked_in():
    text = open(c.__file__, encoding="utf-8").read().lower()
    for word in ("zus", "pesel", "ppk", "umowa", "kwap", "sabawar"):
        assert word not in text, word


# ── earning classes and tables ─────────────────────────────────────────────
def test_earning_class_matrix_is_complete_without_duplicates():
    pairs = [(o, comp) for (o, _t, comp, _l, _s) in c.MALAYSIA_EARNING_CLASSES]
    assert len(pairs) == len(c.OBLIGATIONS) * len(c.COMPONENTS) == 96 and len(set(pairs)) == 96
    treatment = {(o, comp): t for (o, t, comp, _l, _s) in c.MALAYSIA_EARNING_CLASSES}
    assert treatment[("HRD", "OVERTIME")] == "EXCLUDED"                    # §8
    assert treatment[("HRD", "FIXED_ALLOWANCE")] == "INCLUDED"
    assert treatment[("PCB_ADDITIONAL", "BONUS")] == "INCLUDED"            # §5
    assert treatment[("PCB_NORMAL", "BONUS")] == "EXCLUDED"
    assert treatment[("MIN_WAGE_BASIC", "OVERTIME")] == "EXCLUDED"         # §9
    assert treatment[("EPF", "BENEFIT_IN_KIND")] == "REVIEW"               # not stated -> blocks


def test_schedules_and_forms_ship_empty():
    assert set(c.SCHEDULE_RULES) <= set(c.REQUIRED_TABLES) and c.MY_PUBLIC_HOLIDAY_RULE in c.REQUIRED_TABLES
    assert all(not entry["versions"] for entry in c.MY_FORM_SCHEMA_CATALOG.values())
    assert set(c.MY_FORM_SCHEMA_CATALOG) == set(c.FILING_FORMS)
    assert all(len(rule) <= 30 for rule in c.SCHEDULE_RULES + c.REQUIRED_TABLES)


# ── Draft seed and activation refusal ──────────────────────────────────────
def test_seed_writes_every_row_unsigned_with_its_territory(db):
    from app.modules.payroll import malaysia_service as mys
    from app.modules.payroll.models import ContributionRate, TaxSlab

    pack = mys.seed_malaysia_pack(db)
    db.commit()
    rates = db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id).all()
    assert len(rates) == len(c.MALAYSIA_SCALAR_CONTENT)
    assert all(r.label.endswith("[PENDING G1]") and r.source_document_id for r in rates)
    by_key = {r.component_key: r for r in rates}
    assert by_key["my_maternity_days__SBH"].jurisdiction_state == "SABAH"
    assert by_key["my_min_wage_monthly"].jurisdiction_state is None
    assert by_key["my_min_wage_monthly"].flat_amount == Decimal("1700")
    assert by_key["my_hospitalisation_days__PEN"].total == mys.NOT_CONFIGURED
    slabs = db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack.id).all()
    assert {s.rule_type for s in slabs} == {c.MY_EARNING_CLASS_RULE} and len(slabs) == 96
    assert all("[PENDING G1]" in s.rate_label for s in slabs)
    assert (pack.status, pack.pack_id, pack.jurisdiction_country) == ("Draft", "MY-PAYROLL-2026", "MY")
    assert mys.seed_malaysia_pack(db).id == pack.id                         # idempotent while Draft
    pack.status = "Active"
    db.commit()
    with pytest.raises(ValueError, match="not Draft"):
        mys.seed_malaysia_pack(db)


def test_activation_is_refused_until_everything_is_signed_and_loaded(db):
    from app.modules.payroll import malaysia_service as mys
    from app.modules.payroll.models import ContributionRate, TaxSlab

    pack = mys.seed_malaysia_pack(db)
    db.commit()
    assert "unsigned or unconfigured" in mys.my_pack_activation_refusal(db, pack)
    for r in db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id):   # simulate full signing
        r.label = r.label.replace(" [PENDING G1]", "")
        if r.total == mys.NOT_CONFIGURED or r.text_value == c.PENDING:
            r.text_value, r.flat_amount, r.total = None, Decimal("1"), "1"
    db.commit()
    assert "unsigned table row" in mys.my_pack_activation_refusal(db, pack)
    for s in db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack.id):
        s.rate_label = s.rate_label.replace(" [PENDING G1]", "")
    db.commit()
    refusal = mys.my_pack_activation_refusal(db, pack)
    assert "MY_EPF_SCHEDULE" in refusal and "MY_PUBLIC_HOLIDAY" in refusal   # schedules are legal content
    assert mys.my_pack_activation_refusal(db, type("P", (), {"jurisdiction_country": "PL"})()) is None


def test_registry_row_is_created_planned_once(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import malaysia_service as mys

    assert mys.ensure_my_service_registry_row(db) == "PLANNED"
    row = db.query(JurisdictionServiceRegistry).filter_by(country="MY").one()
    row.availability = "AVAILABLE"
    assert mys.ensure_my_service_registry_row(db) == "AVAILABLE"            # never changed
