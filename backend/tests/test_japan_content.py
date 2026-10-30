"""Contract tests pinning japan_content.py to ZP-JP-ENG-001 (Phase 1).

These assert the values and rules the specification states (§2 calendars and
rates, §5 social insurance, §6 labour, §15 evidence register) and the
production safety rule: every row is PENDING G1, nothing the specification
does not reproduce (NTA tables, SMR grades, prefectural health rates, minimum
wages) is filled, and there is no global rounding (JP-002). Also covers the
Draft seeder, the dormancy switch and fail-closed dispatch.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.countries import japan_content as content


def _scalar(key):
    return {row[0]: row for row in content.JP_SCALAR_CONTENT}[key]


# ── pack window and evidence register ───────────────────────────────────────
def test_pack_window_is_the_2026_calendar_year():
    assert content.JP_2026 == ("JP-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
    assert content.PACK_STATUS == "Draft"
    assert content.CURRENCY == "JPY"


def test_evidence_register_is_s1_to_s17_with_urls():
    assert content.SOURCE_CODES == tuple(f"S{i}" for i in range(1, 18))
    assert set(content.SOURCE_URLS) == set(content.SOURCE_CODES)
    assert all(url.startswith("https://") for url in content.SOURCE_URLS.values())


def test_every_row_cites_a_real_evidence_code():
    codes = set(content.SOURCE_CODES)
    for row in content.JP_SCALAR_CONTENT:
        assert row[6] in codes, row[0]
    for row in content.JP_EARNING_CLASSES:
        assert row[4] in codes, row[3]
    for name, table in content.JP_EMPTY_TABLES.items():
        assert table["source"] is None or table["source"] in codes, name


# ── parameter catalog ───────────────────────────────────────────────────────
def test_every_parameter_is_seeded_exactly_once():
    keys = [row[0] for row in content.JP_SCALAR_CONTENT]
    assert len(keys) == len(set(keys))
    assert set(keys) == set(content.JP_PARAMETER_KEYS)


def test_each_value_sits_in_the_slot_its_kind_names():
    slots = {"pct_pair": (2, 3), "pct_total": (4,), "amount": (4,), "text": (5,)}
    for row in content.JP_SCALAR_CONTENT:
        filled = tuple(i for i in (2, 3, 4, 5) if row[i] is not None)
        if row[0] in content.JP_EMPTY_BY_DESIGN:
            assert filled == (), row[0]
            continue
        assert filled == slots[content.JP_PARAMETER_KEYS[row[0]]], row[0]


def test_only_listed_rows_may_be_empty():
    empty = {row[0] for row in content.JP_SCALAR_CONTENT if all(row[i] is None for i in (2, 3, 4, 5))}
    assert empty == set(content.JP_EMPTY_BY_DESIGN)


def test_every_row_is_pending_g1():
    # Production safety rule: nothing is active because the spec states it.
    assert all(row[7] is True for row in content.JP_SCALAR_CONTENT)


def test_values_parse_and_dates_are_ordered():
    for row in content.JP_SCALAR_CONTENT:
        for i in (2, 3, 4):
            if row[i] is not None:
                Decimal(row[i])
        if row[8] is not None and row[9] is not None:
            assert row[8] <= row[9], row[0]


# ── JP-002: no global rounding ──────────────────────────────────────────────
def test_there_is_no_global_rounding_row():
    keys = set(content.JP_PARAMETER_KEYS)
    assert not {"jp_rounding_mode", "jp_rounding_precision"} & keys
    rounding = {k for k in keys if k.endswith("_rounding")}
    assert rounding == {"jp_wht_rounding", "jp_si_employee_share_rounding",
                        "jp_ei_employee_share_rounding", "jp_sba_rounding"}
    for key in rounding:
        assert _scalar(key)[5] in content.ROUNDING_RULES, key


def test_only_the_stated_rounding_rule_is_filled():
    assert _scalar("jp_sba_rounding")[5] == "DOWN_1000"
    assert _scalar("jp_sba_rounding_unit")[4] == "1000"
    for key in ("jp_wht_rounding", "jp_si_employee_share_rounding", "jp_ei_employee_share_rounding"):
        assert _scalar(key)[5] == content.PENDING, key


# ── spec-stated values (§2, §5, §6) ─────────────────────────────────────────
def test_social_insurance_values():
    assert _scalar("jp_epi_total")[4] == "18.3000"
    assert _scalar("jp_epi_split_rule")[5] == "EQUAL"
    assert _scalar("jp_epi_sba_monthly_cap")[4] == "1500000"
    assert _scalar("jp_health_sba_annual_cap")[4] == "5730000"
    assert (_scalar("jp_kyokai_health_total_min")[4], _scalar("jp_kyokai_health_total_max")[4]) == \
        ("9.2100", "10.5500")
    assert _scalar("jp_kyokai_care_total")[4] == "1.6200"
    assert _scalar("jp_care_split_rule")[5] == content.PENDING        # the spec states no care split
    assert (_scalar("jp_care_min_age")[4], _scalar("jp_care_max_age")[4]) == ("40", "64")


def test_child_support_starts_april_2026():
    row = _scalar("jp_kyokai_child_support_total")
    assert row[4] == "0.2300" and row[8] == date(2026, 4, 1)
    assert "jp_kyokai_child_support_total" not in content.content_rows_in_force(date(2026, 3, 31))
    assert "jp_kyokai_child_support_total" in content.content_rows_in_force(date(2026, 4, 1))


def test_no_generic_health_rate_exists():
    # JP-009: the health rate comes from insurer + prefecture, never a default.
    assert not any(k.startswith("jp_health") and content.JP_PARAMETER_KEYS[k] in ("pct_pair", "pct_total")
                   for k in content.JP_PARAMETER_KEYS)
    assert content.JP_EMPTY_TABLES["kyokai_health_rates"]["rows"] == ()


def test_employment_insurance_fy2026():
    general = _scalar("jp_ei_general")
    assert (general[2], general[3]) == ("0.5000", "0.8500")
    assert Decimal(general[2]) + Decimal(general[3]) == Decimal("1.35")      # 13.5/1000
    assert _scalar("jp_ei_agriculture_sake_total")[4] == "1.5500"
    assert _scalar("jp_ei_construction_total")[4] == "1.6500"
    for key in ("jp_ei_general", "jp_ei_agriculture_sake_total", "jp_ei_construction_total",
                "jp_ei_agriculture_sake", "jp_ei_construction"):
        assert (_scalar(key)[8], _scalar(key)[9]) == (date(2026, 4, 1), date(2027, 3, 31)), key
    # FY2025 rates are not in the spec: January–March 2026 has no EI row.
    assert not any(k.startswith("jp_ei_") and k != "jp_ei_employee_share_rounding"
                   for k in content.content_rows_in_force(date(2026, 3, 31)))


def test_labour_premiums_and_hours():
    assert (_scalar("jp_statutory_hours_per_day")[4], _scalar("jp_statutory_hours_per_week")[4]) == ("8", "40")
    assert _scalar("jp_overtime_premium_pct")[4] == "25"
    assert (_scalar("jp_overtime_60h_threshold_hours")[4], _scalar("jp_overtime_over_60h_premium_pct")[4]) == \
        ("60", "50")
    assert _scalar("jp_statutory_holiday_premium_pct")[4] == "35"
    assert (_scalar("jp_night_premium_pct")[4], _scalar("jp_night_window")[5]) == ("25", "22:00-05:00")


def test_calendars_and_due_dates():
    assert _scalar("jp_resident_tax_collection_months")[5] == "06-05"
    assert (_scalar("jp_smr_determination_months")[5], _scalar("jp_smr_report_month")[5],
            _scalar("jp_smr_application_months")[5]) == ("04-06", "07", "09-08")
    assert _scalar("jp_wht_remittance_due_day")[4] == "10"
    assert _scalar("jp_wht_due_non_business_day_rule")[5] == content.PENDING
    assert _scalar("jp_si_remittance_due")[5] == "LAST_DAY_FOLLOWING_MONTH"
    assert _scalar("jp_bonus_report_days")[4] == "5"
    assert _scalar("jp_statutory_reports_due")[5] == "01-31"


def test_scope_and_method():
    assert _scalar("jp_supported_pay_frequencies")[5] == "MONTHLY"
    assert "DAILY" in content.PAY_FREQUENCIES_BLOCKED
    assert _scalar("jp_withholding_method")[5] in content.WITHHOLDING_METHODS


# ── authority tables are empty until archived evidence arrives ──────────────
def test_authority_tables_are_empty():
    assert all(t["rows"] == () for t in content.JP_EMPTY_TABLES.values())
    assert {"wht_monthly_table", "wht_bonus_rate_table", "year_end_adjustment", "smr_grades_health",
            "smr_grades_pension", "kyokai_health_rates", "minimum_wage"} <= set(content.JP_EMPTY_TABLES)


def test_authority_tables_point_at_their_taxslab_rule_types():
    assert set(content.JP_TABLE_RULE_TYPES) == {
        "JP_WHT_MONTHLY", "JP_WHT_CMP_EID", "JP_WHT_CMP_RATE",
        "JP_HEALTH_RATE", "JP_SMR_GRADE",
    }
    assert all(len(rule_type) <= 30 for rule_type in content.JP_TABLE_RULE_TYPES)
    assert content.JP_EMPTY_TABLES["wht_monthly_table"]["rule_type"] == "JP_WHT_MONTHLY"
    assert set(content.JP_EMPTY_TABLES["wht_computer_method"]["rule_types"]) == {
        "JP_WHT_CMP_EID", "JP_WHT_CMP_RATE",
    }
    assert content.JP_EMPTY_TABLES["kyokai_health_rates"]["rule_type"] == "JP_HEALTH_RATE"
    assert content.JP_EMPTY_TABLES["smr_grades_health"]["rule_type"] == "JP_SMR_GRADE"
    assert content.JP_EMPTY_TABLES["smr_grades_pension"]["rule_type"] == "JP_SMR_GRADE"


def test_computer_method_scalars_are_present_and_empty_until_g1():
    for key in ("jp_wht_cmp_basic_deduction", "jp_wht_cmp_dependant_deduction"):
        assert key in content.JP_PARAMETER_KEYS
        assert key in content.JP_EMPTY_BY_DESIGN
        row = _scalar(key)
        assert row[4] is None and row[5] is None


def test_prefectures_are_the_47_jis_codes():
    codes = [code for code, _ in content.JP_PREFECTURES]
    assert codes == [f"{i:02d}" for i in range(1, 48)]


# ── earning classification ──────────────────────────────────────────────────
def test_every_obligation_classifies_every_component_once():
    seen = {(o, c) for (o, _t, c, _l, _s) in content.JP_EARNING_CLASSES}
    assert len(seen) == len(content.JP_EARNING_CLASSES)
    assert seen == {(o, c) for o in content.OBLIGATIONS for c in content.JP_COMPONENTS}
    assert all(t in content.TREATMENTS for (_o, t, _c, _l, _s) in content.JP_EARNING_CLASSES)


def test_only_stated_treatments_are_decided():
    decided = {(o, c): t for (o, t, c, _l, _s) in content.JP_EARNING_CLASSES if t != "REVIEW"}
    assert decided == {("WHT", "SALARY"): "INCLUDED", ("WHT", "BONUS"): "BONUS_PATH",
                       ("SI", "SALARY"): "INCLUDED", ("SI", "BONUS"): "BONUS_PATH",
                       ("EI", "SALARY"): "INCLUDED"}


# ── seeder (Draft only) ─────────────────────────────────────────────────────
def test_seed_writes_a_draft_pack_with_every_row(db):
    from app.modules.payroll import japan_service as svc
    from app.modules.payroll.models import ContributionRate, SourceArtifact, TaxSlab

    pack = svc.seed_japan_pack(db)
    assert (pack.pack_id, pack.version, pack.status) == ("JP-PAYROLL-2026", "1.0", "Draft")
    assert (pack.jurisdiction_country, pack.pack_type, pack.currency) == ("JP", "tax", "JPY")
    assert (pack.effective_from, pack.effective_to) == (date(2026, 1, 1), date(2026, 12, 31))

    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    assert {r.component_key for r in rates} == set(content.JP_PARAMETER_KEYS)
    by_key = {r.component_key: r for r in rates}
    assert all(r.label.endswith("[PENDING G1]") for r in rates)
    assert by_key["jp_epi_total"].flat_amount == Decimal("18.3") and by_key["jp_epi_total"].total == "18.3000% total"
    assert by_key["jp_ei_general"].employee_rate_pct == Decimal("0.5")
    assert by_key["jp_ei_general"].employer_rate_pct == Decimal("0.85")
    assert by_key["jp_ei_construction"].total == "NOT CONFIGURED"
    assert by_key["jp_resident_tax_collection_months"].text_value == "06-05"
    assert by_key["jp_kyokai_child_support_total"].effective_from == date(2026, 4, 1)

    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).all()
    assert {s.rule_type for s in slabs} == {"JP_EARNING_CLASS"}          # no table row is invented
    assert len(slabs) == len(content.JP_EARNING_CLASSES)
    assert db.query(SourceArtifact).filter(SourceArtifact.form_number.like("ZP-JP-ENG-001 S%")).count() == 17


def test_reseed_is_idempotent_and_refuses_a_pack_that_left_draft(db):
    from app.modules.payroll import japan_service as svc
    from app.modules.payroll.models import ContributionRate

    pack = svc.seed_japan_pack(db)
    first = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count()
    assert svc.seed_japan_pack(db).id == pack.id
    assert db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count() == first
    pack.status = "Active"
    db.flush()
    with pytest.raises(ValueError, match="not Draft"):
        svc.seed_japan_pack(db)


def test_seed_only_writes_draft(db):
    from app.modules.payroll import japan_service as svc

    with pytest.raises(ValueError, match="only writes Draft"):
        svc.seed_japan_pack(db, status="Active")


# ── jurisdiction identity, dormancy and fail-closed dispatch ───────────────
@pytest.mark.parametrize("value", ["JP", "jp", "Japan", " japan ", "Nippon"])
def test_japan_resolves_to_jp(value):
    from app.core.jurisdiction import REGISTRATION_COUNTRIES, get_jurisdiction_code

    assert get_jurisdiction_code(value) == "JP"
    assert "Japan" not in REGISTRATION_COUNTRIES                      # never registrable while dormant


def test_entering_japan_is_refused_while_dormant(monkeypatch):
    from app.config import settings
    from app.modules.payroll import japan_dormancy as d

    assert settings.JP_TENANT_ONBOARDING_ENABLED is False
    assert d.entering_japan_refusal("India", "Japan") == d.DORMANT_MESSAGE
    assert d.entering_japan_refusal("JP", "Japan") is None                      # already Japanese
    assert d.entering_japan_refusal("India", "Brazil") is None                  # not Japan
    monkeypatch.setattr(settings, "JP_TENANT_ONBOARDING_ENABLED", True)
    assert d.entering_japan_refusal("India", "Japan") is None


def test_country_change_into_japan_is_blocked(db):
    from app.modules.payroll.engine.tax_resolver import get_jurisdiction_change_block_reason

    assert "Japan is not open" in get_jurisdiction_change_block_reason(db, "India", "Japan")


@pytest.mark.parametrize("value", ["JP", "Japan"])
def test_company_jurisdiction_cannot_become_japan(db, value):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import CompanyDetailsUpdate
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="JP Test Org", code="JPTEST", country=None)
    service.get_company_details(db, t.org.id)
    with pytest.raises(BadRequestException, match="Japan is not open"):
        service.update_company_details(db, t.org.id, CompanyDetailsUpdate(jurisdictionCountry=value))
    assert (service.get_company_details(db, t.org.id).jurisdiction_country or "") not in ("JP", "Japan")


def test_backfill_never_makes_an_org_japanese(db):
    from app.modules.organizations.models import Organization
    from app.modules.payroll import service
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="JP Backfill Org", code="JPBACK", country=None)
    db.get(Organization, t.org.id).country = "Japan"
    db.commit()
    assert (service.get_company_details(db, t.org.id).jurisdiction_country or "") not in ("JP", "Japan")


def test_japan_dispatch_is_fail_closed():
    from app.modules.payroll.engine import standard
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries import japan
    from app.modules.payroll.engine.resolver import calculate_payroll

    assert standard._COUNTRY_CALC["JP"] is japan.calculate
    assert standard._COUNTRY_CALC["JP"] is not standard._calc_generic
    ctx = PayrollContext(country="JP", pay_frequency="Monthly", pay_date=date(2026, 1, 31),
                         basic=Decimal("300000"), gross=Decimal("300000"))
    for mode in ("simple", "standard"):
        with pytest.raises(japan.JPCalculationBlockedError):
            calculate_payroll(ctx, calculation_mode=mode)


def test_japan_is_not_yet_a_hooked_statutory_module():
    from app.modules.payroll import jurisdiction_hooks

    assert not jurisdiction_hooks.has_module("JP")                   # hooks arrive in Phase 5
