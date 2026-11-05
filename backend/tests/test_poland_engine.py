"""Poland engine (ZP-PL-ENG-001 Phase 3): fail-closed behaviour, separation of
bases, caps, statements, determinism and hashes. Golden numbers live in
test_poland_golden.py."""
from datetime import date
from decimal import Decimal

import pytest

from tests._pl_engine_helpers import DEFAULT_DECLARATIONS, build_pack, ctx, declaration

from app.modules.payroll.engine.countries.poland import PLCalculationBlockedError, calculate


def _blocks(context, prefix):
    with pytest.raises(PLCalculationBlockedError) as raised:
        calculate(context)
    assert raised.value.key.startswith(prefix), raised.value.key
    return raised.value


def _pl(context):
    return calculate(context)["pl_result"]


# ── content governance ─────────────────────────────────────────────────────
def test_the_shipped_unsigned_pack_never_calculates():
    _blocks(ctx(pack=build_pack(signed=False)), "PL_PACK_UNSIGNED")


@pytest.mark.parametrize("key", ["pl_rounding_pit", "pl_rounding_zus", "pl_rounding_health", "pl_rounding_ppk"])
def test_an_unsigned_rounding_rule_blocks(key):
    _blocks(ctx(pack=build_pack({key: "PENDING_G1"})), f"PL_ROUNDING_PENDING:{key}")


@pytest.mark.parametrize("key", ["pl_health_limitation_rule", "pl_ppk_employer_pit_treatment",
                                 "pl_fp_fs_min_base_rule", "pl_fund_cap_rule"])
def test_an_unsigned_policy_blocks(key):
    _blocks(ctx(pack=build_pack({key: "PENDING_G1"})), f"PL_POLICY_PENDING:{key}")


@pytest.mark.parametrize("key", ["pl_costs_standard_annual_cap", "pl_zus_annual_cap"])
def test_an_empty_amount_blocks(key):
    _blocks(ctx(pack=build_pack({key: None})), f"PL_ROW_MISSING:{key}")


def test_a_pay_date_outside_the_pack_blocks():
    _blocks(ctx(pay_date=date(2027, 1, 31), registration_overrides={"accident_rate_to": None}), "PL_ROW_MISSING")


def test_no_pay_date_blocks():
    _blocks(ctx(pay_date=None), "PL_PAY_DATE_MISSING")


# ── applicability (PL-002, PL-006, spec §3 high-risk control) ──────────────
@pytest.mark.parametrize("fact", ["other_titles_declared", "a1_certificate", "is_student", "is_pensioner"])
def test_a_missing_high_risk_fact_blocks(fact):
    _blocks(ctx(profile_overrides={fact: None}), f"PL_FACT_MISSING:{fact}")


@pytest.mark.parametrize("flag, obligation", [("cov_pension", "EMERYTALNE"), ("cov_disability", "RENTOWE"),
                                              ("cov_sickness", "CHOROBOWE"), ("cov_accident", "WYPADKOWE"),
                                              ("cov_health", "ZDROWOTNE")])
def test_unknown_coverage_blocks_rather_than_guessing(flag, obligation):
    _blocks(ctx(profile_overrides={flag: None}), f"PL_COVERAGE_UNKNOWN:{obligation}")


@pytest.mark.parametrize("overrides, code", [
    ({"contract_type": "UMOWA_ZLECENIE"}, "PL_CONTRACT_UNSUPPORTED:UMOWA_ZLECENIE"),
    ({"contract_type": "UMOWA_O_DZIELO"}, "PL_CONTRACT_UNSUPPORTED"),
    ({"pay_frequency": "WEEKLY"}, "PL_FREQUENCY_UNSUPPORTED"),
    ({"tax_residency": "NON_RESIDENT"}, "PL_NON_RESIDENT_UNSUPPORTED"),
    ({"other_titles_declared": True}, "PL_MULTI_TITLE_UNSUPPORTED"),
    ({"a1_certificate": True}, "PL_A1_UNSUPPORTED"),
    ({"status": "DRAFT"}, "PL_PROFILE_NOT_ACTIVE"),
    ({"effective_from": date(2026, 4, 1)}, "PL_PROFILE_NOT_ACTIVE"),
    ({"fund_exemption_code": "AGE_60_64"}, "PL_FUND_EXEMPTION_UNSIGNED"),
])
def test_unsupported_or_unapproved_profiles_block(overrides, code):
    _blocks(ctx(profile_overrides=overrides), code)


@pytest.mark.parametrize("overrides, code", [
    ({"status": "DRAFT"}, "PL_REGISTRATION_NOT_ACTIVE"),
    ({"fp_fs_applicable": None}, "PL_FUND_APPLICABILITY_UNKNOWN:FP_FS"),
    ({"fgsp_applicable": None}, "PL_FUND_APPLICABILITY_UNKNOWN:FGSP"),
    ({"accident_rate_pct": None}, "PL_ACCIDENT_RATE_MISSING"),
])
def test_registration_gaps_block(overrides, code):
    _blocks(ctx(registration_overrides=overrides), code)


def test_missing_profile_registration_and_ppk_state_block():
    _blocks(ctx(pl_profile=None), "PL_PROFILE_MISSING")
    _blocks(ctx(pl_registration=None), "PL_REGISTRATION_MISSING")
    _blocks(ctx(ppk_state=None), "PL_PPK_STATE_MISSING")


def test_accident_rate_follows_the_contribution_year():
    # The 2025/26 rate ends 31 March 2026; April needs the next contribution year's rate.
    _blocks(ctx(pay_date=date(2026, 4, 30)), "PL_ACCIDENT_RATE_MISSING")
    pl = _pl(ctx(pay_date=date(2026, 4, 30), registration_overrides={
        "accident_rate_pct": Decimal("0.93"), "accident_rate_from": date(2026, 4, 1),
        "accident_rate_to": date(2027, 3, 31)}))
    assert pl["pl_zus_employer"]["WYPADKOWE"] == "74.40"                       # 8000 x 0.93%


def test_every_obligation_has_a_decision_and_a_reason():
    pl = _pl(ctx())
    assert list(pl["obligations"]) == ["PIT", "EMERYTALNE", "RENTOWE", "CHOROBOWE", "WYPADKOWE", "ZDROWOTNE",
                                       "FP_FS", "FGSP", "FEP", "PPK"]
    assert all(set(o) == {"applies", "reason"} and o["reason"] for o in pl["obligations"].values())


def test_coverage_false_switches_off_only_that_obligation():
    pl = _pl(ctx(profile_overrides={"cov_sickness": False}))
    assert pl["pl_zus_employee"]["CHOROBOWE"] == "0.00"
    assert pl["pl_zus_employee"]["EMERYTALNE"] == "780.80"
    assert pl["obligations"]["CHOROBOWE"] == {"applies": False, "reason": "PROFILE_COVERAGE_FALSE"}


# ── components and bases ───────────────────────────────────────────────────
def test_components_must_add_up_to_gross():
    _blocks(ctx(components={"SALARY": Decimal("7000")}), "PL_COMPONENTS_MISMATCH")


def test_unmapped_gross_blocks():
    _blocks(ctx(components=None, pl_components=None, basic=Decimal("7000")), "PL_COMPONENTS_UNMAPPED")


def test_unknown_component_blocks():
    _blocks(ctx(components={"COMMISSION": Decimal("8000")}), "PL_COMPONENT_UNKNOWN:COMMISSION")


@pytest.mark.parametrize("component", ["OVERTIME_50", "BONUS", "BENEFIT_IN_KIND", "SICK_PAY_EMPLOYER"])
def test_unsigned_treatment_blocks_when_non_zero(component):
    _blocks(ctx(components={"SALARY": Decimal("7000"), component: Decimal("1000")}),
            f"PL_EARNING_CLASS_REVIEW:PIT:{component}")


def test_a_zero_review_component_is_harmless():
    pl = _pl(ctx(components={"SALARY": Decimal("8000"), "BONUS": Decimal("0")}))
    assert pl["pl_net"] == "5608.91"


def test_each_obligation_keeps_its_own_base():
    # A signed treatment that includes a bonus for PIT only must not reach ZUS / health / PPK.
    classes = {("PIT", "BONUS"): "INCLUDED"}
    for obligation in ("EMERYTALNE", "RENTOWE", "CHOROBOWE", "WYPADKOWE", "ZDROWOTNE", "FP_FS", "FGSP",
                       "FEP", "PPK", "MIN_WAGE"):
        classes[(obligation, "BONUS")] = "EXCLUDED"
    pl = _pl(ctx(gross="9000", components={"SALARY": Decimal("8000"), "BONUS": Decimal("1000")},
                 pack=build_pack(classes=classes)))
    assert pl["pl_zus_employee"]["EMERYTALNE"] == "780.80"                    # 8000 only
    assert pl["pl_ppk_employee"]["BASIC"] == "160.00"
    assert pl["trace"]["bases"]["PIT"]["base"] == "9000.00"
    assert pl["pl_pit_base"] == "7773.00"                                   # 9120 - 1096.80 - 250


TEST_PREMIUM_MAP = "DAILY=50,WEEKLY=100,NIGHT=100,SUNDAY_HOLIDAY=100,COMP_TIME_FAILED=50"   # TEST fixture


def test_minimum_wage_base_excludes_overtime():
    classes = {(o, "OVERTIME_50"): "INCLUDED" for o in ("PIT", "EMERYTALNE", "RENTOWE", "CHOROBOWE", "WYPADKOWE",
                                                         "ZDROWOTNE", "FP_FS", "FGSP", "FEP", "PPK")}
    events = [{"kind": "DAILY", "event_ref": "2026-03-10", "hours": "20", "hourly_rate": "50"}]   # 20 x 50 x 150%
    pl = _pl(ctx(gross="9500", components={"SALARY": Decimal("8000"), "OVERTIME_50": Decimal("1500")},
                 pack=build_pack({"pl_overtime_premium_map": TEST_PREMIUM_MAP}, classes=classes),
                 pl_overtime_events=events))
    assert pl["trace"]["bases"]["MIN_WAGE"]["base"] == "8000.00"             # PL-015
    assert pl["trace"]["bases"]["EMERYTALNE"]["base"] == "9500.00"
    assert pl["trace"]["labour"]["overtime"]["status"] == "MATCHED"


# ── ZUS cap and accumulators ───────────────────────────────────────────────
def test_pension_and_disability_caps_use_their_own_accumulators():
    pl = _pl(ctx(ytd_overrides={"ZUS_CAP_PENSION_BASE": "282600", "ZUS_CAP_DISABILITY_BASE": "0"}))
    assert pl["pl_zus_employee"]["EMERYTALNE"] == "0.00"
    assert pl["pl_zus_employee"]["RENTOWE"] == "120.00"


def test_ppk_base_ignores_the_cap():
    pl = _pl(ctx(ytd_overrides={"ZUS_CAP_PENSION_BASE": "282600", "ZUS_CAP_DISABILITY_BASE": "282600"}))
    assert pl["pl_ppk_employee"]["BASIC"] == "160.00" and pl["trace"]["ppk"]["capped"] is False


def test_missing_ytd_blocks():
    _blocks(ctx(pl_ytd=None), "PL_YTD_MISSING")
    context = ctx()
    del context.pl_ytd["ZUS_CAP_PENSION_BASE"]
    _blocks(context, "PL_YTD_MISSING:ZUS_CAP_PENSION_BASE")


def test_accumulator_deltas_are_what_was_assessed():
    pl = _pl(ctx(ytd_overrides={"ZUS_CAP_PENSION_BASE": "278000", "ZUS_CAP_DISABILITY_BASE": "278000"}))
    assert pl["accumulatorDeltas"]["ZUS_CAP_PENSION_BASE"] == "4600.00"
    assert pl["accumulatorDeltas"]["PIT_TAXABLE_INCOME"] == "7156.00"
    assert set(pl["accumulatorDeltas"]) <= {
        "PIT_TAXABLE_INCOME", "PIT_ADVANCE", "PIT_COSTS_USED", "PIT0_EXEMPT_UNDER26", "PIT0_EXEMPT_RETURN",
        "PIT0_EXEMPT_FAMILY4", "PIT0_EXEMPT_SENIOR", "ZUS_CAP_PENSION_BASE", "ZUS_CAP_DISABILITY_BASE",
        "SICK_DAYS_EMPLOYER", "PPK_EMPLOYEE", "PPK_EMPLOYER"}


# ── PIT statements, costs, reliefs ─────────────────────────────────────────
@pytest.mark.parametrize("allocation, advance", [("FULL", "513.00"), ("HALF", "663.00"), ("THIRD", "713.00")])
def test_pit2_allocation(allocation, advance):
    pl = _pl(ctx(declarations=[declaration("PIT2", {"allocation": allocation})]))
    assert pl["pl_pit_advance"] == advance                                  # 812.76 - 300/150/100


def test_unapproved_or_expired_pit2_is_ignored():
    for d in (declaration("PIT2", {"allocation": "FULL"}, status="RECEIVED"),
              declaration("PIT2", {"allocation": "FULL"}, effective_to=date(2026, 2, 28))):
        assert _pl(ctx(declarations=[d]))["pl_pit_advance"] == "813.00"


def test_pit2_continues_without_annual_resubmission():
    # PL-007: a statement from an earlier year stays effective until changed.
    d = declaration("PIT2", {"allocation": "FULL"}, effective_from=date(2023, 1, 1))
    assert _pl(ctx(declarations=[d]))["pl_pit_advance"] == "513.00"


def test_invalid_or_conflicting_statements_block():
    _blocks(ctx(declarations=[declaration("PIT2", {"allocation": "QUARTER"})]), "PL_PIT2_INVALID")
    _blocks(ctx(declarations=[declaration("PIT2", {"allocation": "FULL"}),
                              declaration("PIT2", {"allocation": "HALF"})]), "PL_DECLARATION_CONFLICT:PIT2")
    _blocks(ctx(declarations=[declaration("HIGHER_RATE_REQUEST")]), "PL_HIGHER_RATE_UNSIGNED")


def test_costs_cap_and_multiple_employments():
    # Standard cap (TEST 3000) used up: no costs -> 8120 - 1096.80 = 7023.20 -> 7023.
    assert _pl(ctx(ytd_overrides={"PIT_COSTS_USED": "3000"}))["pl_pit_base"] == "7023.00"
    multi = _pl(ctx(ytd_overrides={"PIT_COSTS_USED": "3000"},
                    declarations=[*DEFAULT_DECLARATIONS, declaration("COSTS_MULTIPLE", ident=9)]))
    assert multi["pl_pit_base"] == "6773.00"                                 # multi cap 4500 still open
    assert _pl(ctx(ytd_overrides={"PIT_COSTS_USED": "2900"}))["trace"]["pit"]["employeeCosts"]["applied"] == "100.00"


def test_relief_is_pit_only_and_a_crossing_month_blocks():
    reliefs = [*DEFAULT_DECLARATIONS, declaration("PIT0_UNDER26", ident=5)]
    _blocks(ctx(declarations=reliefs, ytd_overrides={"PIT0_EXEMPT_UNDER26": "80000"}), "PL_PIT0_PARTIAL_UNSIGNED")
    exhausted = _pl(ctx(declarations=reliefs, ytd_overrides={"PIT0_EXEMPT_UNDER26": "85528"}))
    assert exhausted["pl_pit_advance"] == "513.00"
    waived = _pl(ctx(declarations=[*reliefs, declaration("PIT0_WAIVER", ident=6)]))
    assert waived["pl_pit_advance"] == "513.00"
    _blocks(ctx(declarations=[*reliefs, declaration("PIT0_SENIOR", ident=7)]), "PL_DECLARATION_CONFLICT:PIT0")


# ── PPK ────────────────────────────────────────────────────────────────────
def test_reduced_ppk_rate_lapses_when_the_income_test_fails():
    d = [*DEFAULT_DECLARATIONS, declaration("PPK_REDUCED_RATE", {"ratePct": "0.5", "otherSourcesIncome": "0"},
                                            ident=3)]
    pl = _pl(ctx(declarations=d))                                           # 8000 > 5767.20
    assert pl["pl_ppk_employee"]["BASIC"] == "160.00"
    assert [e["code"] for e in pl["exceptions"]] == ["PPK_ANOMALY"]
    other = [*DEFAULT_DECLARATIONS, declaration("PPK_REDUCED_RATE", {"ratePct": "0.5", "otherSourcesIncome": "1000"},
                                                ident=3)]
    assert _pl(ctx(gross="5000", declarations=other))["pl_ppk_employee"]["BASIC"] == "100.00"   # 6000 > limit


@pytest.mark.parametrize("value", [{"ratePct": "0.4", "otherSourcesIncome": "0"}, {"ratePct": "0.5"},
                                   {"ratePct": "x", "otherSourcesIncome": "0"}])
def test_invalid_reduced_rate_statement_blocks(value):
    _blocks(ctx(declarations=[declaration("PPK_REDUCED_RATE", value)]), "PL_PPK_DECLARATION_INVALID")


def test_additional_ppk_rates():
    pl = _pl(ctx(declarations=[*DEFAULT_DECLARATIONS, declaration("PPK_ADDITIONAL", {"ratePct": "1"}, ident=4)],
                 registration_overrides={"ppk_employer_additional_pct": Decimal("0.5")}))
    assert pl["pl_ppk_employee"] == {"BASIC": "160.00", "ADDITIONAL": "80.00"}
    assert pl["pl_ppk_employer"] == {"BASIC": "120.00", "ADDITIONAL": "40.00"}
    _blocks(ctx(registration_overrides={"ppk_employer_additional_pct": Decimal("3")}), "PL_PPK_RATE_INVALID")


def test_employer_ppk_pit_policy_is_honoured():
    taxable = _pl(ctx())
    not_taxable = _pl(ctx(pack=build_pack({"pl_ppk_employer_pit_treatment": "NOT_TAXABLE"})))
    assert taxable["trace"]["pit"]["incomeClassification"]["employerPpkAsIncome"] == "120.00"
    assert not_taxable["trace"]["pit"]["incomeClassification"]["employerPpkAsIncome"] == "0.00"
    assert not_taxable["pl_pit_base"] == "6653.00"


@pytest.mark.parametrize("state", ["NOT_ELIGIBLE", "ELIGIBLE_NOT_ENROLLED", "OPTED_OUT", "SUSPENDED_BY_LAW", "ENDED"])
def test_only_enrolled_participants_contribute(state):
    pl = _pl(ctx(ppk_state=state))
    assert pl["pl_ppk_employee"]["BASIC"] == "0.00"
    assert pl["obligations"]["PPK"] == {"applies": False, "reason": f"PPK_STATE_{state}"}


# ── employer funds ─────────────────────────────────────────────────────────
def test_fp_fs_minimum_base_and_fgsp():
    pl = _pl(ctx(gross="4000"))
    assert pl["pl_funds"]["FP_FS"] == "0.00" and pl["pl_funds"]["FGSP"] == "4.00"
    assert pl["trace"]["funds"]["FP_FS"]["reason"] == "BASE_BELOW_MINIMUM_WAGE"


def test_employer_not_liable_switches_funds_off():
    pl = _pl(ctx(registration_overrides={"fp_fs_applicable": False, "fgsp_applicable": False}))
    assert pl["pl_funds"] == {"FP_FS": "0.00", "FGSP": "0.00", "FEP": "0.00"}


def test_fep_needs_evidenced_work_in_force():
    assert _pl(ctx(profile_overrides={"fep_qualifying": False}))["pl_funds"]["FEP"] == "0.00"   # PL-012
    lapsed = _pl(ctx(profile_overrides={"fep_qualifying": True, "fep_from": date(2025, 1, 1),
                                        "fep_to": date(2025, 12, 31)}))
    assert lapsed["pl_funds"]["FEP"] == "0.00"


def test_funds_are_separate_lines_never_one_burden_rate():
    pl = _pl(ctx())
    assert set(pl["pl_funds"]) == {"FP_FS", "FGSP", "FEP"}
    assert {"FP_FS", "FGSP", "FEP"} <= set(pl["trace"]["funds"])


# ── determinism, hashes, platform ──────────────────────────────────────────
def test_same_input_same_result_and_hashes():
    first, second = _pl(ctx()), _pl(ctx())
    assert first == second
    assert len(first["hashes"]["input"]) == 64 and first["hashes"]["engineBuild"].startswith("PL-ENGINE")


def test_hashes_move_with_inputs_and_content():
    base = _pl(ctx())["hashes"]
    assert _pl(ctx(gross="8001"))["hashes"]["input"] != base["input"]
    rate_map, slabs = build_pack()
    for s in slabs:
        if s.rule_type == "PL_PIT_BAND" and s.max_amount is None:
            s.rate_pct = Decimal("33")
    assert _pl(ctx(pack=(rate_map, slabs)))["hashes"]["content"] != base["content"]


def test_result_never_carries_identifiers():
    text = str(_pl(ctx()))
    for forbidden in ("pesel", "nip", "iban", "nrs"):
        assert forbidden not in text.lower()


def test_simple_mode_is_blocked():
    from app.modules.payroll.engine.resolver import calculate_payroll

    with pytest.raises(PLCalculationBlockedError) as raised:
        calculate_payroll(ctx(), "simple")
    assert raised.value.key == "PL_SIMPLE_MODE_UNSUPPORTED"


def test_engine_modules_are_pure():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "modules" / "payroll" / "engine"
    files = list((root / "jurisdictions" / "poland").glob("*.py")) + [root / "countries" / "poland.py"]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert not name.startswith(("sqlalchemy", "app.database", "app.modules.payroll.models",
                                            "requests", "httpx", "urllib")), (path.name, name)
            if isinstance(node, ast.Attribute) and node.attr in ("now", "today", "utcnow"):
                raise AssertionError(f"{path.name} reads the clock")
