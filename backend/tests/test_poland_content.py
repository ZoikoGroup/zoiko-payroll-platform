"""Contract tests pinning poland_content.py to ZP-PL-ENG-001.

These assert the values and rules the specification states (§2 baseline,
§4 PIT, §5 ZUS/health, §6 employer funds, §7 PPK, §8 labour, §9 sickness,
§10 filing, §15 evidence register), so a content edit that contradicts the
spec fails here before it can reach a pack — and that every value the spec
does NOT give stays empty / PENDING_G1 instead of being guessed. The certified
engine arrives in Phase 3 and is pinned by its own golden fixtures.
"""
import ast
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.payroll.engine.countries import poland_content as content

BACKEND = Path(__file__).resolve().parent.parent


def _scalar(key):
    return {row[0]: row for row in content.POLAND_SCALAR_CONTENT}[key]


def _amount(key):
    return Decimal(_scalar(key)[4])


def _ee(key):
    return Decimal(_scalar(key)[2])


def _er(key):
    return Decimal(_scalar(key)[3])


# ── pack window and evidence register ───────────────────────────────────────
def test_pack_window_is_calendar_2026():
    assert content.PL_2026 == ("PL-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
    assert (content.PACK_STATUS, content.TAX_YEAR, content.CURRENCY) == ("Draft", "2026", "PLN")


def test_evidence_register_is_s1_to_s12_with_official_urls():
    assert content.SOURCE_CODES == tuple(f"S{i}" for i in range(1, 13))
    assert set(content.SOURCE_URLS) == set(content.SOURCE_CODES)
    for url in content.SOURCE_URLS.values():
        assert re.match(r"^https://(www\.|lang\.)?(gov\.pl|podatki\.gov\.pl|zus\.pl|mojeppk\.pl|pip\.gov\.pl)/", url), url


def test_every_row_cites_a_real_evidence_code():
    codes = set(content.SOURCE_CODES)
    for row in content.POLAND_SCALAR_CONTENT:
        assert row[6] in codes, row[0]
    for row in content.POLAND_PIT_BANDS:
        assert row[5] in codes, row[4]
    for row in content.POLAND_EARNING_CLASSES:
        assert row[4] in codes, row[3]
    for form, entry in content.PL_FORM_SCHEMA_CATALOG.items():
        assert entry["evidence"] in codes, form


# ── parameter catalog shape ────────────────────────────────────────────────
def test_every_parameter_is_seeded_exactly_once():
    keys = [row[0] for row in content.POLAND_SCALAR_CONTENT]
    assert len(keys) == len(set(keys))
    assert set(keys) == set(content.POLAND_PARAMETER_KEYS)
    assert all(k.startswith("pl_") for k in keys)


def test_each_value_sits_in_the_slot_its_kind_names():
    slots = {"employee_pct": (2,), "employer_pct": (3,), "pct_pair": (2, 3), "amount": (4,), "text": (5,)}
    for row in content.POLAND_SCALAR_CONTENT:
        filled = tuple(i for i in (2, 3, 4, 5) if row[i] is not None)
        if row[0] in content.POLAND_EMPTY_BY_DESIGN:
            assert filled == () and row[7] is True, row[0]      # empty AND pending, never guessed
            continue
        assert filled == slots[content.POLAND_PARAMETER_KEYS[row[0]]], row[0]


def test_only_listed_rows_may_be_empty():
    empty = {row[0] for row in content.POLAND_SCALAR_CONTENT if all(row[i] is None for i in (2, 3, 4, 5))}
    assert empty == set(content.POLAND_EMPTY_BY_DESIGN)


def test_numbers_are_decimal_strings():
    for row in content.POLAND_SCALAR_CONTENT:
        for i in (2, 3, 4):
            if row[i] is not None:
                assert isinstance(row[i], str), row[0]
                Decimal(row[i])                                   # never a float


def test_values_fit_their_columns():
    for row in content.POLAND_SCALAR_CONTENT:
        assert len(row[0]) <= 50, row[0]                         # component_key String(50)
        assert row[5] is None or len(row[5]) <= 50, row[0]       # text_value String(50)
        assert len(row[1]) + len(" [PENDING G1]") <= 100, row[0]  # label String(100) incl. marker
    for rule in (content.PL_PIT_BAND_RULE, content.PL_EARNING_CLASS_RULE):
        assert len(rule) <= 30
    for obligation, treatment, component, label, _src in content.POLAND_EARNING_CLASSES:
        assert len(component) <= 30 and len(obligation) <= 20 and len(treatment) <= 20
        assert len(label) <= 150
    for row in content.POLAND_PIT_BANDS:
        assert len(row[4]) <= 150


def test_every_row_names_its_date_basis():
    # PL-003: never assume every rule changes on 1 January.
    for row in content.POLAND_SCALAR_CONTENT:
        assert row[10] in content.DATE_BASES, row[0]
    assert content.date_basis("pl_zus_wypadkowe_small_payer") == "CONTRIBUTION_YEAR"
    assert content.date_basis("pl_zus_annual_cap") == "CALENDAR_YEAR"
    assert content.date_basis("pl_min_wage_monthly") == "PAYROLL_MONTH"


# ── policy the spec leaves open stays PENDING_G1 ───────────────────────────
@pytest.mark.parametrize("key", ["pl_rounding_pit", "pl_rounding_zus", "pl_rounding_health", "pl_rounding_ppk",
                                 "pl_health_limitation_rule", "pl_ppk_employer_pit_treatment",
                                 "pl_fp_fs_min_base_rule", "pl_fund_cap_rule", "pl_fund_exemption_rules",
                                 "pl_night_supplement_basis",
                                 "pl_leave_pay_reference_rule", "pl_pit_remittance_due_rule"])
def test_policy_the_spec_does_not_give_is_pending_g1(key):
    row = _scalar(key)
    assert row[5] == "PENDING_G1" and row[7] is True


def test_rounding_is_per_obligation_never_one_helper():
    # PL-004: one rounding row per obligation; none decided by the spec.
    rounding = sorted(k for k in content.POLAND_PARAMETER_KEYS if k.startswith("pl_rounding_"))
    assert rounding == ["pl_rounding_health", "pl_rounding_pit", "pl_rounding_ppk", "pl_rounding_zus"]
    assert all(_scalar(k)[5] in content.ROUNDING_MODES for k in rounding)


def test_scope_is_monthly_umowa_o_prace_only():
    assert _scalar("pl_supported_pay_frequencies")[5] == "MONTHLY"
    assert _scalar("pl_supported_contract_types")[5] == "UMOWA_O_PRACE"
    assert content.CONTRACT_TYPES_SUPPORTED == ("UMOWA_O_PRACE",)
    assert "UMOWA_ZLECENIE" in content.CONTRACT_TYPES_BLOCKED and "UMOWA_O_DZIELO" in content.CONTRACT_TYPES_BLOCKED


# ── spec §2 baseline values ────────────────────────────────────────────────
def test_minimum_wage_and_civil_hourly_floor():
    assert _amount("pl_min_wage_monthly") == Decimal("4806")
    assert _amount("pl_min_hourly_civil") == Decimal("31.40")
    assert _scalar("pl_min_wage_monthly")[8] == date(2026, 1, 1)
    assert _amount("pl_pay_deadline_day") == 10


def test_pit_scale_tax_free_and_reductions():
    assert _amount("pl_pit_tax_free_amount") == Decimal("30000")
    assert _amount("pl_pit_tax_reducing_annual") == Decimal("3600")
    # PLN 30,000 at 12% is the PLN 3,600 reducing amount (S4).
    assert _amount("pl_pit_tax_free_amount") * Decimal("0.12") == _amount("pl_pit_tax_reducing_annual")
    assert [_amount(k) for k in ("pl_pit2_reduction_full", "pl_pit2_reduction_half", "pl_pit2_reduction_third")] \
        == [Decimal("300"), Decimal("150"), Decimal("100")]
    # Monthly full reduction x 12 = annual reducing amount; half/third split it.
    assert _amount("pl_pit2_reduction_full") * 12 == _amount("pl_pit_tax_reducing_annual")
    assert _amount("pl_pit2_reduction_half") * 2 == _amount("pl_pit2_reduction_full")
    assert _amount("pl_pit2_reduction_third") * 3 == _amount("pl_pit2_reduction_full")


def test_pit_bands_match_the_published_scale():
    bands = content.pit_bands()
    assert [(lo, hi, rate, base) for lo, hi, rate, base, *_ in bands] == [
        (Decimal("0"), Decimal("120000"), Decimal("12"), Decimal("0")),
        (Decimal("120000"), None, Decimal("32"), Decimal("10800")),
    ]


def test_published_top_band_base_nets_the_tax_reducing_amount():
    # The convention Phase 3 must honour: 10,800 = 120,000 x 12% - 3,600.
    (lo1, hi1, r1, _b1, *_), (lo2, _hi2, _r2, b2, *_) = content.pit_bands()
    assert hi1 == lo2
    assert hi1 * r1 / 100 - _amount("pl_pit_tax_reducing_annual") == b2


def test_employee_deductible_costs():
    assert _amount("pl_costs_standard_monthly") == Decimal("250")
    assert _amount("pl_costs_commuter_monthly") == Decimal("300")
    for key in ("pl_costs_standard_annual_cap", "pl_costs_standard_multi_annual_cap",
                "pl_costs_commuter_annual_cap", "pl_costs_commuter_multi_annual_cap", "pl_pit0_annual_limit"):
        assert key in content.POLAND_EMPTY_BY_DESIGN                  # spec gives no figure


def test_zus_social_and_health_rates():
    assert (_ee("pl_zus_emerytalne"), _er("pl_zus_emerytalne")) == (Decimal("9.76"), Decimal("9.76"))
    assert (_ee("pl_zus_rentowe"), _er("pl_zus_rentowe")) == (Decimal("1.5"), Decimal("6.5"))
    assert _ee("pl_zus_emerytalne") + _er("pl_zus_emerytalne") == Decimal("19.52")      # spec §5 total
    assert _ee("pl_zus_rentowe") + _er("pl_zus_rentowe") == Decimal("8.00")
    assert _ee("pl_zus_chorobowe") == Decimal("2.45") and _scalar("pl_zus_chorobowe")[3] is None
    assert _ee("pl_health") == Decimal("9") and _scalar("pl_health")[3] is None          # employee-funded
    assert _scalar("pl_health_base_rule")[5] == "GROSS_LESS_EMPLOYEE_SOCIAL"
    assert _scalar("pl_pit_social_deduction_rule")[5] == "EMPLOYEE_SOCIAL_ONLY"


def test_accident_rates_are_employer_only_contribution_year_and_pending():
    for key, value in (("pl_zus_wypadkowe_min", "0.67"), ("pl_zus_wypadkowe_max", "3.33"),
                       ("pl_zus_wypadkowe_small_payer", "1.67")):
        row = _scalar(key)
        assert row[2] is None and Decimal(row[3]) == Decimal(value)
        assert row[7] is True and row[10] == "CONTRIBUTION_YEAR"
    assert _scalar("pl_zus_contribution_year_start")[5] == "04-01"


def test_annual_cap_is_282600():
    assert _amount("pl_zus_annual_cap") == Decimal("282600")


def test_employer_funds():
    assert _er("pl_fp_fs") == Decimal("2.45") and _scalar("pl_fp_fs")[2] is None
    assert _er("pl_fgsp") == Decimal("0.10") and _scalar("pl_fgsp")[2] is None
    assert _er("pl_fep") == Decimal("1.5") and _scalar("pl_fep")[2] is None


def test_ppk_rates():
    assert _ee("pl_ppk_employee_basic") == Decimal("2")
    assert _ee("pl_ppk_employee_reduced_min") == Decimal("0.5")
    assert _ee("pl_ppk_reduced_income_pct_min_wage") == Decimal("120")
    assert _ee("pl_ppk_employee_additional_max") == Decimal("2")
    assert _er("pl_ppk_employer_basic") == Decimal("1.5")
    assert _er("pl_ppk_employer_additional_max") == Decimal("2.5")
    assert _amount("pl_ppk_transfer_day") == 15 and _scalar("pl_ppk_transfer_day")[7] is True


def test_labour_leave_and_sickness_baselines():
    assert (_amount("pl_working_hours_daily"), _amount("pl_working_hours_weekly_avg")) == (8, 40)
    assert (_ee("pl_overtime_premium_standard"), _ee("pl_overtime_premium_high")) == (50, 100)
    assert (_amount("pl_leave_days_base"), _amount("pl_leave_days_senior"),
            _amount("pl_leave_service_years_senior")) == (20, 26, 10)
    assert (_amount("pl_sick_employer_days"), _amount("pl_sick_employer_days_older")) == (33, 14)
    assert _amount("pl_sick_older_age_threshold") == 50 and _scalar("pl_sick_older_age_threshold")[7] is True
    assert (_ee("pl_sick_rate_standard"), _ee("pl_sick_rate_full")) == (80, 100)


def test_filing_deadlines():
    assert _scalar("pl_zus_due_day_classes")[5] == "5,15,20"
    assert [d.replace("DAY_", "") for d in content.ZUS_DEADLINE_CLASSES] == _scalar("pl_zus_due_day_classes")[5].split(",")
    assert _scalar("pl_pit11_authority_due")[5] == "END_JANUARY"
    assert _scalar("pl_pit11_employee_due")[5] == "END_FEBRUARY"
    assert _scalar("pl_pit4r_due")[5] == "END_JANUARY" and _scalar("pl_pit8ar_due")[5] == "END_JANUARY"


def test_form_schema_catalogue_is_empty_until_archived():
    # PL-019: a schema version is never guessed; generation blocks while empty.
    assert set(content.PL_FORM_SCHEMA_CATALOG) == {"DRA", "RCA", "RSA", "RPA", "ZUA", "ZZA", "ZWUA",
                                                  "PIT11", "PIT4R", "PIT8AR"}
    assert all(entry["versions"] == {} for entry in content.PL_FORM_SCHEMA_CATALOG.values())


def test_state_vocabularies_match_spec():
    assert content.PPK_STATES == ("NOT_ELIGIBLE", "ELIGIBLE_NOT_ENROLLED", "ENROLLED", "OPTED_OUT",
                                  "SUSPENDED_BY_LAW", "ENDED")
    assert content.COMPLIANCE_STATES == ("DRAFT", "APPROVED", "SUBMITTED", "ACCEPTED", "REJECTED", "CORRECTED",
                                         "PAID", "RECONCILED")
    assert set(content.PIT0_RELIEFS) <= set(content.DECLARATION_TYPES)


# ── earning classification (separate bases per obligation) ────────────────
def test_every_obligation_classifies_every_component_exactly_once():
    pairs = [(o, c) for (o, _t, c, *_r) in content.POLAND_EARNING_CLASSES]
    assert len(pairs) == len(set(pairs)) == len(content.OBLIGATIONS) * len(content.POLAND_COMPONENTS) == 132
    assert set(pairs) == {(o, c) for o in content.OBLIGATIONS for c in content.POLAND_COMPONENTS}


def test_coverage_obligations_are_the_ten_of_pl_006():
    assert content.COVERAGE_OBLIGATIONS == ("PIT", "EMERYTALNE", "RENTOWE", "CHOROBOWE", "WYPADKOWE", "ZDROWOTNE",
                                            "FP_FS", "FGSP", "FEP", "PPK")
    assert content.OBLIGATIONS[-1] == "MIN_WAGE"


def test_base_pay_is_in_every_base():
    for obligation, treatment, component, *_ in content.POLAND_EARNING_CLASSES:
        if component in ("SALARY", "HOURLY_PAY"):
            assert treatment == "INCLUDED", (obligation, component)


def test_minimum_wage_excludes_overtime_night_and_seniority():
    # PL-015.
    table = {(o, c): t for (o, t, c, *_r) in content.POLAND_EARNING_CLASSES}
    for component in ("OVERTIME_50", "OVERTIME_100", "NIGHT_SUPPLEMENT", "SENIORITY_ALLOWANCE"):
        assert table[("MIN_WAGE", component)] == "EXCLUDED"


def test_unstated_treatments_block_rather_than_guess():
    stated_excluded = {("MIN_WAGE", c) for c in ("OVERTIME_50", "OVERTIME_100", "NIGHT_SUPPLEMENT",
                                                 "SENIORITY_ALLOWANCE")}
    for obligation, treatment, component, *_ in content.POLAND_EARNING_CLASSES:
        if component in ("SALARY", "HOURLY_PAY") or (obligation, component) in stated_excluded:
            continue
        assert treatment == "REVIEW", (obligation, component)
    # Non-cash benefits are never silently excluded from PIT (spec §4).
    table = {(o, c): t for (o, t, c, *_r) in content.POLAND_EARNING_CLASSES}
    assert table[("PIT", "BENEFIT_IN_KIND")] != "EXCLUDED"


def test_ppk_and_fep_follow_the_pension_base():
    # PL-014 (PPK = pension base without the 30x cap) and spec §6 (FEP uses pension-base logic).
    table = {(o, c): t for (o, t, c, *_r) in content.POLAND_EARNING_CLASSES}
    for component in content.POLAND_COMPONENTS:
        assert table[("PPK", component)] == table[("EMERYTALNE", component)], component
        assert table[("FEP", component)] == table[("EMERYTALNE", component)], component


# ── no statutory literal outside the content module ────────────────────────
_LITERALS = ("4806", "282600", "282,600", "9.76", "120000", "10800", "31.40")


@pytest.mark.parametrize("path", ["app/modules/payroll/poland_service.py", "app/modules/payroll/poland_dormancy.py",
                                  "app/modules/payroll/engine/countries/poland.py"])
def test_no_statutory_value_outside_content(path):
    tree = ast.parse((BACKEND / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float)):
            text = str(node.value)
            assert not any(text == lit or re.search(rf"(?<![\d.]){re.escape(lit)}(?![\d.])", text) for lit in _LITERALS), \
                (path, text)


# ── seeding (in-memory SQLite via the `db` fixture) ─────────────────────────
def test_seed_writes_a_draft_pack_with_every_row(db):
    from app.modules.payroll import poland_service as svc
    from app.modules.payroll.models import ContributionRate, SourceArtifact, TaxSlab

    pack = svc.seed_poland_pack(db)
    assert (pack.pack_id, pack.version, pack.status) == ("PL-PAYROLL-2026", "1.0", "Draft")
    assert (pack.jurisdiction_country, pack.pack_type, pack.currency, pack.tax_year) == ("PL", "tax", "PLN", "2026")
    assert (pack.effective_from, pack.effective_to) == (date(2026, 1, 1), date(2026, 12, 31))

    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    assert {r.component_key for r in rates} == set(content.POLAND_PARAMETER_KEYS)
    assert all(r.jurisdiction_country == "PL" and r.organization_id is None for r in rates)
    by_key = {r.component_key: r for r in rates}
    assert by_key["pl_zus_annual_cap"].flat_amount == Decimal("282600")
    assert by_key["pl_zus_emerytalne"].employee_rate_pct == Decimal("9.76")
    assert by_key["pl_zus_rentowe"].employer_rate_pct == Decimal("6.5")
    assert by_key["pl_min_wage_monthly"].effective_from == date(2026, 1, 1)
    assert by_key["pl_supported_contract_types"].text_value == "UMOWA_O_PRACE"
    assert by_key["pl_rounding_pit"].label.endswith("[PENDING G1]")
    assert not by_key["pl_zus_annual_cap"].label.endswith("[PENDING G1]")
    assert by_key["pl_pit0_annual_limit"].total == "NOT CONFIGURED"
    assert by_key["pl_pit0_annual_limit"].flat_amount is None
    assert all(r.source_document_id is not None for r in rates)

    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).all()
    by_rule = {}
    for s in slabs:
        by_rule.setdefault(s.rule_type, []).append(s)
    assert set(by_rule) == {"PL_PIT_BAND", "PL_EARNING_CLASS"}
    assert len(by_rule["PL_PIT_BAND"]) == 2
    top = max(by_rule["PL_PIT_BAND"], key=lambda s: s.min_amount)
    assert top.max_amount is None and top.flat_amount == Decimal("10800") and top.rate_pct == Decimal("32")
    assert len(by_rule["PL_EARNING_CLASS"]) == 132
    ot = [s for s in by_rule["PL_EARNING_CLASS"] if (s.tax_regime, s.filing_status) == ("MIN_WAGE", "OVERTIME_50")]
    assert len(ot) == 1 and ot[0].assessment_basis == "EXCLUDED"

    assert db.query(SourceArtifact).filter(SourceArtifact.form_number.like("ZP-PL-ENG-001 S%")).count() == 12


def test_reseed_is_idempotent_and_refuses_a_pack_that_left_draft(db):
    from app.modules.payroll import poland_service as svc
    from app.modules.payroll.models import ContributionRate, SourceArtifact, TaxSlab

    pack = svc.seed_poland_pack(db)
    first = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count(),
             db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count())
    again = svc.seed_poland_pack(db)
    assert again.id == pack.id
    assert (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).count(),
            db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).count()) == first
    assert db.query(SourceArtifact).filter(SourceArtifact.form_number.like("ZP-PL-ENG-001 S%")).count() == 12

    pack.status = "Active"
    db.flush()
    with pytest.raises(ValueError, match="not Draft"):
        svc.seed_poland_pack(db)


def test_reseed_keeps_org_overrides(db):
    from app.modules.organizations.models import Organization
    from app.modules.payroll import poland_service as svc
    from app.modules.payroll.models import ContributionRate

    pack = svc.seed_poland_pack(db)
    org = Organization(organization_name="PL override org", organization_code="PLOVR")
    db.add(org)
    db.flush()
    db.add(ContributionRate(jurisdiction_pack_id=pack.id, organization_id=org.id, jurisdiction_country="PL",
                            component_key="pl_zus_wypadkowe_small_payer", label="org override",
                            employee_share="—", employer_share="1.67%", total="1.67%",
                            employer_rate_pct=Decimal("1.67")))
    db.flush()
    svc.seed_poland_pack(db)
    assert db.query(ContributionRate).filter(ContributionRate.organization_id == org.id).count() == 1


def test_seed_only_writes_draft(db):
    from app.modules.payroll import poland_service as svc

    with pytest.raises(ValueError, match="only writes Draft"):
        svc.seed_poland_pack(db, status="Active")


# ── activation refusal (becomes the pack_activation_refusal hook in P4) ────
def test_activation_is_refused_while_any_row_is_unsigned(db):
    from app.modules.payroll import poland_service as svc

    pack = svc.seed_poland_pack(db)
    refusal = svc.pl_pack_activation_refusal(db, pack)
    assert refusal and "unsigned or unconfigured" in refusal and "G1" in refusal


def test_activation_refusal_clears_only_when_every_row_is_signed_and_configured(db):
    from app.modules.payroll import poland_service as svc
    from app.modules.payroll.models import ContributionRate

    pack = svc.seed_poland_pack(db)
    rows = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).all()
    # Simulate a fully signed pack (what the G1 console does in Phase 7).
    for r in rows:
        r.label = r.label.replace(svc.PENDING_G1_SUFFIX, "")
        if r.total == svc.NOT_CONFIGURED:
            r.flat_amount, r.total = Decimal("1"), "1"
        if r.text_value == "PENDING_G1":
            r.text_value = "SIGNED"
    db.flush()
    assert svc.pl_pack_activation_refusal(db, pack) is None
    rows[0].source_document_id = None
    db.flush()
    assert "without a source document" in svc.pl_pack_activation_refusal(db, pack)


def test_activation_refusal_ignores_other_countries(db):
    from types import SimpleNamespace

    from app.modules.payroll import poland_service as svc

    assert svc.pl_pack_activation_refusal(db, SimpleNamespace(jurisdiction_country="ZA", id=0)) is None


def test_seed_script_is_guarded_and_never_activates():
    source = (BACKEND / "scripts/seed_poland_canonical_packs.py").read_text(encoding="utf-8")
    assert "assert_local_database(" in source
    assert '"Active"' not in source and "'Active'" not in source
    assert 'availability="PLANNED"' in source
