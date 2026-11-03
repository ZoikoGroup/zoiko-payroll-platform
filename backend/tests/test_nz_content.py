"""Contract tests pinning new_zealand_content.py to ZP-NZ-ENG-001 (Phase 1).

These assert the values the specification states (§2 baseline, §3 PAYE bands,
§4 KiwiSaver/ESCT, §5 student loan/child support, §7 minimum wage, §8 Holidays
Act, §9 payday filing/remittance, §15 evidence register) and the production
safety rule: every row is PENDING G1, nothing the specification does not
reproduce (IRD PAYE method, secondary/ND rates, IETC, variation codes,
lump-sum method, public holidays) is filled, and there is no global rounding.
Also covers the Draft seeder, the activation refusal and the isolated
Employment Leave Act 2026 pack (AC-NZ-08).
"""
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.payroll.engine.countries import new_zealand_content as content


def _scalar(key):
    return {row[0]: row for row in content.NZ_SCALAR_CONTENT}[key]


# ── pack window and evidence register ───────────────────────────────────────
def test_pack_window_is_the_2026_27_tax_year():
    assert content.NZ_2026_27 == ("NZ-PAYROLL-2026-27", date(2026, 4, 1), date(2027, 3, 31))
    assert (content.PACK_STATUS, content.CURRENCY, content.TAX_YEAR) == ("Draft", "NZD", "2026-27")


def test_evidence_register_is_s1_to_s10_with_urls():
    assert content.SOURCE_CODES == tuple(f"S{i}" for i in range(1, 11))
    assert set(content.SOURCE_URLS) == set(content.SOURCE_CODES)
    assert all(url.startswith("https://") for url in content.SOURCE_URLS.values())
    assert content.SOURCE_URLS["S1"].startswith("https://www.ird.govt.nz/")


def test_every_row_cites_a_real_evidence_code():
    codes = set(content.SOURCE_CODES)
    for row in content.NZ_SCALAR_CONTENT:
        assert row[6] in codes, row[0]
    for row in content.NZ_EARNING_CLASSES:
        assert row[4] in codes, row[3]
    for name, table in content.NZ_EMPTY_TABLES.items():
        assert table["source"] is None or table["source"] in codes, name


# ── parameter catalog ───────────────────────────────────────────────────────
def test_every_parameter_is_seeded_exactly_once():
    keys = [row[0] for row in content.NZ_SCALAR_CONTENT]
    assert len(keys) == len(set(keys))
    assert set(keys) == set(content.NZ_PARAMETER_KEYS)


def test_each_value_sits_in_the_slot_its_kind_names():
    slots = {"pct_total": (4,), "amount": (4,), "text": (5,)}
    for row in content.NZ_SCALAR_CONTENT:
        filled = tuple(i for i in (2, 3, 4, 5) if row[i] is not None)
        if row[0] in content.NZ_EMPTY_BY_DESIGN:
            assert filled == (), row[0]
            continue
        assert filled == slots[content.NZ_PARAMETER_KEYS[row[0]]], row[0]


def test_only_listed_rows_may_be_empty():
    empty = {row[0] for row in content.NZ_SCALAR_CONTENT if all(row[i] is None for i in (2, 3, 4, 5))}
    assert empty == set(content.NZ_EMPTY_BY_DESIGN)


def test_every_row_is_pending_g1():
    assert all(row[7] is True for row in content.NZ_SCALAR_CONTENT)


def test_values_parse_and_dates_are_ordered():
    for row in content.NZ_SCALAR_CONTENT:
        if row[4] is not None:
            Decimal(row[4])
        if row[8] is not None and row[9] is not None:
            assert row[8] <= row[9], row[0]


# ── rounding: one row per statutory amount, none stated by the spec ────────
def test_there_is_no_global_rounding_row_and_every_rounding_is_pending():
    rounding = {k for k in content.NZ_PARAMETER_KEYS if k.endswith("_rounding")}
    assert rounding == {"nz_paye_rounding", "nz_acc_rounding", "nz_sl_rounding",
                        "nz_ks_rounding", "nz_esct_rounding", "nz_cs_rounding"}
    for key in rounding:
        assert _scalar(key)[5] == content.PENDING, key


# ── spec-stated values ──────────────────────────────────────────────────────
def test_paye_bands_2026_27():
    assert content.NZ_PAYE_BANDS == (
        ("0", "15600", "10.5000"), ("15600", "53500", "17.5000"), ("53500", "78100", "30.0000"),
        ("78100", "180000", "33.0000"), ("180000", None, "39.0000"))


def test_esct_bands_2026_27():
    assert content.NZ_ESCT_BANDS == (
        ("0", "18720", "10.5000"), ("18720", "64200", "17.5000"), ("64200", "93720", "30.0000"),
        ("93720", "216000", "33.0000"), ("216000", None, "39.0000"))


@pytest.mark.parametrize("bands", [content.NZ_PAYE_BANDS, content.NZ_ESCT_BANDS])
def test_bands_are_contiguous_and_open_ended(bands):
    for (_low, high, _rate), (next_low, _h, _r) in zip(bands, bands[1:]):
        assert high == next_low
    assert bands[0][0] == "0" and bands[-1][1] is None


def test_acc_earner_levy():
    assert _scalar("nz_acc_earner_levy_rate")[4] == "1.7500"
    assert _scalar("nz_acc_max_liable_earnings")[4] == "156641"


def test_kiwisaver_rates_apply_from_payday_1_april_2026():
    assert _scalar("nz_ks_employee_rates")[5] == "3.5,4,6,8,10"
    assert _scalar("nz_ks_temporary_reduction_rate")[4] == "3.0000"
    assert _scalar("nz_ks_default_rate")[4] == "3.5000"
    assert _scalar("nz_ks_employer_min_rate")[4] == "3.5000"
    assert _scalar("nz_ks_employer_min_age")[4] == "16"
    assert _scalar("nz_ks_rate_selection_basis")[5] == "PAYDAY"
    for key in ("nz_ks_default_rate", "nz_ks_employer_min_rate", "nz_ks_employer_min_age"):
        assert key not in content.content_rows_in_force(date(2026, 3, 31)), key   # no pre-April rate → blocks
        assert key in content.content_rows_in_force(date(2026, 4, 1)), key


def test_student_loan():
    assert _scalar("nz_sl_rate")[4] == "12.0000"
    assert _scalar("nz_sl_annual_threshold")[4] == "24128"
    assert [_scalar(f"nz_sl_threshold_{f}")[4] for f in ("weekly", "fortnightly", "four_weekly", "monthly")] == \
        ["464", "928", "1856", "2010.66"]
    assert _scalar("nz_sl_secondary_basis")[5] == "WHOLE_PAYMENT"


def test_child_support_protected_net():
    assert (_scalar("nz_cs_protected_net_pct")[4], _scalar("nz_cs_max_deduction_pct")[4]) == ("60.0000", "40.0000")


def test_minimum_wage_from_1_april_2026():
    assert [_scalar(k)[4] for k in ("nz_min_wage_adult", "nz_min_wage_starting_out", "nz_min_wage_training")] == \
        ["23.95", "19.16", "19.16"]
    assert "nz_min_wage_adult" not in content.content_rows_in_force(date(2026, 3, 31))


def test_payday_filing_and_remittance():
    assert _scalar("nz_payday_filing_working_days")[4] == "2"
    assert _scalar("nz_paper_filing_working_days")[4] == "10"
    assert (_scalar("nz_efiling_threshold")[4], _scalar("nz_efiling_threshold_after_months")[4]) == ("50000", "6")
    assert _scalar("nz_large_employer_threshold")[4] == "500000"
    assert [_scalar(k)[4] for k in ("nz_remit_monthly_due_day", "nz_remit_first_half_due_day",
                                    "nz_remit_second_half_due_day")] == ["20", "20", "5"]
    assert _scalar("nz_remit_december_second_half_due")[5] == "01-15"


def test_holidays_act_baseline():
    expected = {"nz_hol_annual_weeks": "4", "nz_hol_annual_qualifying_months": "12", "nz_hol_sick_days": "10",
                "nz_hol_sick_qualifying_months": "6", "nz_hol_sick_carry_max": "20",
                "nz_hol_bereavement_close_days": "3", "nz_hol_bereavement_other_days": "1",
                "nz_hol_family_violence_days": "10", "nz_hol_payg_pct": "8.0000",
                "nz_hol_cashup_max_weeks": "1", "nz_hol_ph_worked_multiplier": "1.5"}
    assert {k: _scalar(k)[4] for k in expected} == expected
    assert _scalar("nz_record_retention_years")[4] == "6"


def test_scope_and_policy():
    assert _scalar("nz_supported_pay_frequencies")[5] == ",".join(content.PAY_FREQUENCIES)
    assert _scalar("nz_correction_policy")[5] == content.PENDING
    assert _scalar("nz_deduction_precedence")[5] == content.PENDING
    assert content.NZ_EXPORT_SCHEMAS == {}


# ── authority tables, tax codes and earning classes ─────────────────────────
def test_authority_tables_are_empty_and_point_at_their_rule_types():
    for name, table in content.NZ_EMPTY_TABLES.items():
        assert table["rows"] == (), name
        assert table["rule_type"] in content.NZ_TABLE_RULE_TYPES, name
        assert table["gate"] in ("G1", "G2"), name
    assert content.NZ_EMPTY_TABLES["public_holidays"]["gate"] == "G2"
    rule_types = [t["rule_type"] for t in content.NZ_EMPTY_TABLES.values()]
    assert len(rule_types) == len(set(rule_types))                     # one table type each


def test_tax_code_catalogue():
    codes = [row[0] for row in content.NZ_TAX_CODES]
    assert len(codes) == len(set(codes))
    assert set(content.SUPPORTED_TAX_CODES) == {
        "M", "ME", "M SL", "ME SL", "SB", "S", "SH", "ST", "SA",
        "SB SL", "S SL", "SH SL", "ST SL", "SA SL", "ND", "STC"}
    assert set(content.REFUSED_TAX_CODES) == {"CAE", "EDW", "NSW", "WT"}
    for code, _cls, _status, student_loan, ietc, _label in content.NZ_TAX_CODES:
        assert student_loan == code.endswith(" SL"), code
        assert ietc == code.startswith("ME"), code


def test_every_obligation_classifies_every_component_once():
    pairs = [(row[0], row[2]) for row in content.NZ_EARNING_CLASSES]
    assert len(pairs) == len(set(pairs)) == len(content.OBLIGATIONS) * len(content.NZ_COMPONENTS)
    assert all(row[1] in content.TREATMENTS for row in content.NZ_EARNING_CLASSES)


def test_only_stated_treatments_are_decided():
    decided = {(o, c): t for o, t, c, _l, _s in content.NZ_EARNING_CLASSES if t != "REVIEW"}
    for obligation in ("PAYE", "ACC", "KIWISAVER", "STUDENT_LOAN"):
        assert decided[(obligation, "SALARY")] == decided[(obligation, "OVERTIME")] == "INCLUDED"
        assert decided[(obligation, "BONUS")] == decided[(obligation, "LUMP_SUM")] == "LUMP_SUM_PATH"
    assert decided[("MIN_WAGE", "SALARY")] == "INCLUDED"
    assert ("MIN_WAGE", "OVERTIME") not in decided
    assert not any(c in ("ALLOWANCE", "HOLIDAY_PAY", "ACC_COMPENSATION", "REIMBURSEMENT", "OTHER_EARNINGS")
                   for (_o, c) in decided)


def test_regions_are_iso_3166_2_nz():
    assert len(content.NZ_REGIONS) == 17
    assert all(re.fullmatch(r"[A-Z]{3}", code) for code, _name in content.NZ_REGIONS)


def test_ela_2028_pack_is_isolated_from_2026_content():
    assert content.NZ_ELA_2028 == ("NZ-ELA-2028", date(2028, 8, 6), None)
    assert content.ELA_EARLIEST_EFFECTIVE == date(2028, 8, 6)
    assert all(row[8] is None or row[8] < content.ELA_EARLIEST_EFFECTIVE for row in content.NZ_SCALAR_CONTENT)


def test_nz_engine_code_holds_no_statutory_literal():
    """Production safety rule: no rate or threshold in engine code. Every
    numeric value the content states must not appear in an NZ engine file."""
    root = Path(content.__file__).resolve().parents[1]
    sources = [root / "countries" / "new_zealand.py", *sorted((root / "jurisdictions" / "new_zealand").glob("*.py"))]
    values = {row[4] for row in content.NZ_SCALAR_CONTENT if row[4] is not None}
    values |= {v for band in content.NZ_PAYE_BANDS + content.NZ_ESCT_BANDS for v in band if v not in (None, "0")}
    values = {str(Decimal(v).normalize()) for v in values} - {"1", "2", "3", "4", "5", "6", "10", "12", "20"}
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for value in values:
            assert not re.search(rf"(?<![\w.]){re.escape(value)}(?![\w.])", text), f"{value} in {path.name}"


# ── seeder and activation refusal ───────────────────────────────────────────
def test_seed_writes_a_draft_pack_with_every_row(db):
    from app.modules.payroll import new_zealand_service as svc
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    pack = svc.seed_nz_pack(db)
    assert (pack.pack_id, pack.version, pack.status) == ("NZ-PAYROLL-2026-27", "1.0", "Draft")
    assert (pack.jurisdiction_country, pack.pack_type, pack.currency, pack.tax_year) == ("NZ", "tax", "NZD", "2026-27")
    assert (pack.effective_from, pack.effective_to) == (date(2026, 4, 1), date(2027, 3, 31))

    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    assert {r.component_key for r in rates} == set(content.NZ_PARAMETER_KEYS)
    by_key = {r.component_key: r for r in rates}
    assert all(r.label.endswith("[PENDING G1]") for r in rates)
    assert by_key["nz_acc_earner_levy_rate"].flat_amount == Decimal("1.75")
    assert by_key["nz_sl_threshold_monthly"].flat_amount == Decimal("2010.66")
    assert by_key["nz_ks_employer_max_age"].total == "NOT CONFIGURED"
    assert by_key["nz_ks_default_rate"].effective_from == date(2026, 4, 1)

    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).all()
    by_rule = {}
    for slab in slabs:
        by_rule.setdefault(slab.rule_type, []).append(slab)
    assert set(by_rule) == {"NZ_PAYE_BAND", "NZ_ESCT_BAND", "NZ_TAX_CODE", "NZ_EARNING_CLASS"}
    assert [(s.min_amount, s.max_amount, s.rate_pct) for s in sorted(by_rule["NZ_PAYE_BAND"], key=lambda s: s.min_amount)][-1] == \
        (Decimal("180000"), None, Decimal("39"))
    assert len(by_rule["NZ_TAX_CODE"]) == len(content.NZ_TAX_CODES)
    assert {s.filing_status for s in by_rule["NZ_TAX_CODE"] if s.tax_column == "SL"} == {
        c for c in content.SUPPORTED_TAX_CODES if c.endswith(" SL")}
    assert len(by_rule["NZ_EARNING_CLASS"]) == len(content.NZ_EARNING_CLASSES)
    assert all(s.rate_label.endswith("[PENDING G1]") for s in slabs)
    assert db.query(SourceArtifact).filter(SourceArtifact.form_number.like("ZP-NZ-ENG-001 S%")).count() == 10

    ela = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == "NZ-ELA-2028").one()
    assert (ela.status, ela.effective_from, ela.jurisdiction_country) == ("Draft", date(2028, 8, 6), "NZ")
    assert db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == ela.id).count() == 0
    assert db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == ela.id).count() == 0


def test_reseed_is_idempotent_and_refuses_a_pack_that_left_draft(db):
    from app.modules.payroll import new_zealand_service as svc
    from app.modules.payroll.models import ContributionRate, TaxSlab

    pack = svc.seed_nz_pack(db)
    first = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count(),
             db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count())
    assert svc.seed_nz_pack(db).id == pack.id
    assert (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count(),
            db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count()) == first
    pack.status = "Active"
    db.flush()
    with pytest.raises(ValueError, match="not Draft"):
        svc.seed_nz_pack(db)


def test_seed_only_writes_draft(db):
    from app.modules.payroll import new_zealand_service as svc

    with pytest.raises(ValueError, match="only writes Draft"):
        svc.seed_nz_pack(db, status="Active")


def test_activation_is_refused_while_rows_are_pending(db):
    from app.modules.payroll import new_zealand_service as svc

    pack = svc.seed_nz_pack(db)
    assert "PENDING G1" in svc.nz_pack_activation_refusal(db, pack)


def test_activation_is_refused_while_authority_tables_are_empty(db):
    from app.modules.payroll import new_zealand_service as svc
    from app.modules.payroll.models import ContributionRate, TaxSlab

    pack = svc.seed_nz_pack(db)
    for row in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id):
        row.label = row.label.replace(svc.PENDING_G1_SUFFIX, "")
    for row in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id):
        row.rate_label = row.rate_label.replace(svc.PENDING_G1_SUFFIX, "")
    db.flush()
    refusal = svc.nz_pack_activation_refusal(db, pack)
    assert "authority tables are empty" in refusal
    assert "paye_main_method" in refusal and "public_holidays" in refusal
    assert "acc_employer_classifications" not in refusal                # employer content, not national


@pytest.mark.parametrize("today", [date(2026, 11, 3), date(2028, 8, 5)])
def test_ela_2028_pack_cannot_activate_before_6_august_2028(db, today):
    from app.modules.payroll import new_zealand_service as svc
    from app.modules.payroll.models import JurisdictionPack

    svc.seed_nz_pack(db)
    ela = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == "NZ-ELA-2028").one()
    assert "cannot be activated before 2028-08-06" in svc.nz_pack_activation_refusal(db, ela, today=today)


def test_ela_2028_pack_cannot_activate_empty_even_after_its_date(db):
    from app.modules.payroll import new_zealand_service as svc
    from app.modules.payroll.models import JurisdictionPack

    svc.seed_nz_pack(db)
    ela = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == "NZ-ELA-2028").one()
    assert "holds no signed content" in svc.nz_pack_activation_refusal(db, ela, today=date(2028, 8, 6))


def test_activation_refusal_ignores_other_countries(db):
    from types import SimpleNamespace

    from app.modules.payroll import new_zealand_service as svc

    assert svc.nz_pack_activation_refusal(db, SimpleNamespace(jurisdiction_country="JP", id=1, pack_id="x")) is None
    assert svc.nz_pack_activation_refusal(db, None) is None
