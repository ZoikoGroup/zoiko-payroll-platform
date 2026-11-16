"""Malaysia engine (ZP-MY-ENG-001 Phase 3): national contributions from signed
schedule ROWS (MY-005 / MY-011), coverage per obligation with reason codes
(MY-004 / MY-026), a missing fact failing only its obligation (MY-008), the
wage ceiling on its own base (MY-013), the LINDUNG phase by contribution month
(MY-014), HRD from the registered category (MY-016), and PCB blocked until the
HASiL specification is archived (MY-009). Schedules are TEST rows
(tests/_my_engine_helpers.py) — never certifying values."""
from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll.engine.countries import malaysia
from app.modules.payroll.engine.countries.malaysia import MYCalculationBlockedError
from tests._my_engine_helpers import (assignment, build_pack, ctx, foreign_profile, profile, registration)


def _blocked(context) -> MYCalculationBlockedError:
    with pytest.raises(MYCalculationBlockedError) as raised:
        malaysia.calculate(context)
    return raised.value


@pytest.fixture
def with_pcb(monkeypatch):
    """Stand-in PCB (Phase 4 builds the real one from the HASiL specification)."""
    from app.modules.payroll.engine.jurisdictions.malaysia import pcb

    monkeypatch.setattr(pcb, "compute", lambda pack, **_: {"pcb": Decimal("100.00"), "trace": {"stub": True}})


# ── PCB blocks until the specification is archived ─────────────────────────
def test_pcb_blocks_and_everything_else_is_still_computed():
    error = _blocked(ctx())
    assert error.key == "MY_OBLIGATIONS_BLOCKED"
    assert error.blocked == {"PCB": {"code": "MY_PCB_SPEC_NOT_ARCHIVED", "reason": error.blocked["PCB"]["reason"]}}
    obligations = error.partial["obligations"]
    assert (obligations["EPF"]["employee"], obligations["EPF"]["employer"]) == ("550.00", "650.00")
    assert obligations["EPF"]["method"] == "THIRD_SCHEDULE" and obligations["EPF"]["rows"]
    assert (obligations["SOCSO"]["employee"], obligations["SOCSO"]["employer"]) == ("24.75", "86.65")
    assert (obligations["EIS"]["employee"], obligations["EIS"]["employer"]) == ("9.90", "9.90")
    assert obligations["HRD"]["levy"] == "50.00"                               # 1% x 5,000, employer cost


def test_full_result_and_net_with_a_stand_in_pcb(with_pcb):
    from app.modules.payroll.engine.resolver import calculate_payroll

    out = malaysia.calculate(ctx())
    r = out["my_result"]
    assert r["my_net"] == "4315.35"                     # 5000 - PCB 100 - (550 + 24.75 + 9.90)
    assert (out["tds"], out["my_employee_total"]) == (Decimal("100.00"), Decimal("584.65"))
    assert (out["employer_pension"], out["employer_esi"], out["employer_payroll_tax"]) == \
        (Decimal("650"), Decimal("96.55"), Decimal("50.00"))
    assert r["accumulatorDeltas"]["HRD_LEVY"] == "50.00" and r["exceptions"] == []
    assert r["trace"]["legalPeriods"]["PCB"] == {"basis": "DEDUCTION_MONTH", "period": "2026-03"}
    result = calculate_payroll(ctx(), "standard")                                # no double count in standard.py
    assert result.net_pay == Decimal("4315.35") and result.tds == Decimal("100.00")
    assert result.my_result["my_net"] == "4315.35"
    assert malaysia.calculate(ctx())["my_result"]["hashes"] == r["hashes"]     # deterministic


def test_wage_ceiling_caps_only_perkeso_and_eis(with_pcb):
    r = malaysia.calculate(ctx(gross="7000"))["my_result"]
    socso = r["trace"]["obligations"]["SOCSO"]
    assert socso["capped"] is True and socso["contributionWage"] == "6000.00"
    assert (r["my_socso"]["employee"], r["my_eis"]["employee"]) == ("29.75", "11.90")
    assert r["my_epf"]["employee"] == "770.00" and r["my_hrd"] == "70.00"     # EPF / HRD on the full wage


# ── foreign workers ───────────────────────────────────────────────────────
@pytest.mark.parametrize("pay_date, employee", [(date(2026, 5, 31), "0.00"), (date(2026, 6, 30), "37.50")])
def test_foreign_workers_use_their_own_schedule_and_lindung_phase(with_pcb, pay_date, employee):
    start = date(pay_date.year, pay_date.month, 1)
    r = malaysia.calculate(ctx(profile_=foreign_profile(), pay_date=pay_date, start=start, end=pay_date))["my_result"]
    assert r["coverage"]["EIS"] == {"applies": False, "reason": "EIS_FOREIGN_EXCLUDED"}
    assert r["trace"]["obligations"]["SOCSO"]["rule"] == "MY_FW_SOCSO_SCHEDULE"
    assert r["my_socso"]["employee"] == employee                               # phase chosen by the month
    assert r["my_epf"] == {"employee": "100.00", "employer": "100.00"}          # Part F 2% / 2% direct
    assert r["trace"]["obligations"]["EPF"]["method"] == "PART_F_DIRECT"


def test_a_foreign_worker_never_takes_the_local_path():
    error = _blocked(ctx(profile_=foreign_profile(socso_category="EI_AND_INVALIDITY", eis_state="COVERED")))
    assert error.blocked["SOCSO"]["code"] == "MY_FACT_CONFLICT:socso_category"
    assert error.blocked["EIS"]["code"] == "MY_FACT_CONFLICT:eis_state"
    assert "EPF" in error.partial["obligations"]                               # unaffected obligation computed


def test_non_malaysian_epf_starts_only_from_its_effective_wage_month(with_pcb):
    pack = build_pack(overrides={"my_epf_rate_non_malaysian": {}})
    old = ctx(pack=pack, profile_=foreign_profile(), pay_date=date(2026, 3, 31))
    assert malaysia.calculate(old)["my_result"]["coverage"]["EPF"]["applies"] is True
    rate_map, slabs = pack
    rate_map["my_epf_rate_non_malaysian"]["effective_from"] = date(2026, 4, 1)  # not yet in force in March
    later = malaysia.calculate(ctx(pack=(rate_map, slabs), profile_=foreign_profile()))["my_result"]
    assert later["coverage"]["EPF"] == {"applies": False, "reason": "EPF_NON_MALAYSIAN_BEFORE_EFFECTIVE_DATE"}


# ── MY-008: a missing fact fails only its own obligation ───────────────────
@pytest.mark.parametrize("change, obligation, code", [
    ({"epf_member_class": None}, "EPF", "MY_FACT_MISSING:epf_member_class"),
    ({"socso_category": None}, "SOCSO", "MY_FACT_MISSING:socso_category"),
    ({"eis_state": None}, "EIS", "MY_FACT_MISSING:eis_state"),
    ({"epf_member_class": "MY_60_PLUS"}, "EPF", "MY_FACT_CONFLICT:epf_member_class"),
    ({"date_of_birth": None}, "EPF", "MY_FACT_MISSING:date_of_birth"),
])
def test_a_missing_or_contradictory_fact_blocks_only_its_obligation(change, obligation, code):
    error = _blocked(ctx(profile_=profile(**change)))
    assert error.blocked[obligation]["code"] == code
    others = {"EPF", "SOCSO", "EIS", "HRD"} - {obligation} - set(error.blocked)
    assert others and all(name in error.partial["obligations"] for name in others)


def test_turning_60_in_the_wage_month_needs_the_signed_transition_rule():
    born = profile(date_of_birth=date(1966, 3, 15))                            # 60 on 15 March 2026
    error = _blocked(ctx(profile_=born, pack=build_pack(overrides={"my_epf_age_transition_rule": {"text_value": None}})))
    assert error.blocked["EPF"]["code"] == "MY_EPF_AGE_TRANSITION"
    error = _blocked(ctx(profile_=born))                                       # rule: age at month start (59)
    assert "EPF" not in error.blocked and error.partial["obligations"]["EPF"]["memberClass"] == "MY_PR_BELOW_60"


def test_eis_age_outside_the_signed_bounds_is_a_conflict():
    error = _blocked(ctx(profile_=profile(date_of_birth=date(1960, 1, 1), epf_member_class="MY_60_PLUS")))
    assert error.blocked["EIS"]["code"] == "MY_FACT_CONFLICT:eis_state"
    assert error.partial["obligations"]["EPF"]["employer"] == "200.00"          # the 60+ schedule row


def test_review_treatment_with_an_amount_blocks_the_obligations_that_need_it():
    error = _blocked(ctx(gross="5100", components={"BASIC_SALARY": Decimal("5000"), "BENEFIT_IN_KIND": Decimal("100")}))
    assert error.blocked["EPF"]["code"] == "MY_EARNING_CLASS_REVIEW:EPF:BENEFIT_IN_KIND"
    assert error.blocked["SOCSO"]["code"] == "MY_EARNING_CLASS_REVIEW:SOCSO:BENEFIT_IN_KIND"


def test_an_unsigned_schedule_row_blocks_its_obligation():
    rate_map, slabs = build_pack()
    for s in slabs:
        if s["rule_type"] == "MY_EIS_SCHEDULE":
            s["rate_label"] += " [PENDING G1]"
    error = _blocked(ctx(pack=(rate_map, slabs)))
    assert error.blocked["EIS"]["code"].startswith("MY_PACK_UNSIGNED:MY_EIS_SCHEDULE")


def test_no_band_or_above_the_schedule_blocks_never_a_percentage():
    assert _blocked(ctx(gross="25000")).blocked["EPF"]["code"] == "MY_EPF_ABOVE_SCHEDULE"
    error = _blocked(ctx(pack=build_pack(schedules=[s for s in __import__("tests._my_engine_helpers", fromlist=["x"])
                                                    .TEST_SCHEDULES if s[0] != "MY_EIS_SCHEDULE"])))
    assert error.blocked["EIS"]["code"] == "MY_TABLE_EMPTY:MY_EIS_SCHEDULE"


# ── HRD (employer cost, registered category) ───────────────────────────────
def test_hrd_follows_the_registered_category(with_pcb):
    assert malaysia.calculate(ctx(registration_=registration(hrd_category="NOT_REGISTERED")))["my_result"][
        "my_hrd"] == "0.00"
    assert malaysia.calculate(ctx(registration_=registration(hrd_category="OPTIONAL_REGISTERED")))["my_result"][
        "my_hrd"] == "25.00"
    error = _blocked(ctx(registration_=registration(hrd_category_from=date(2026, 6, 1))))
    assert error.blocked["HRD"]["code"] == "MY_HRD_CATEGORY_NOT_IN_FORCE"
    excluded = build_pack(overrides={"my_hrd_non_malaysian_rule": {"text_value": "MALAYSIAN_EMPLOYEES_ONLY"}})
    r = malaysia.calculate(ctx(pack=excluded, profile_=foreign_profile()))["my_result"]
    assert r["coverage"]["HRD"] == {"applies": False, "reason": "HRD_NON_MALAYSIAN_EXCLUDED"}


# ── minimum wage (exception, never silent) ─────────────────────────────────
def test_minimum_wage_breach_and_not_evaluated_are_exceptions(with_pcb):
    r = malaysia.calculate(ctx(gross="1500"))["my_result"]
    assert [e["code"] for e in r["exceptions"]] == ["MIN_WAGE_BREACH"]
    part = malaysia.calculate(ctx(start=date(2026, 3, 10)))["my_result"]
    assert part["exceptions"][0]["code"] == "MIN_WAGE_NOT_EVALUATED"
    part_time = malaysia.calculate(ctx(profile_=profile(normal_hours_week=Decimal("30"))))["my_result"]
    assert "part-time hours" in part_time["exceptions"][0]["detail"]
    sabah = malaysia.calculate(ctx(assignment_=assignment("SABAH", "SBH")))["my_result"]
    assert sabah["trace"]["minimumWage"]["territory"] == "SABAH" and sabah["exceptions"] == []


# ── whole-payslip refusals ─────────────────────────────────────────────────
@pytest.mark.parametrize("change, code", [
    ({"contract_type": "DOMESTIC"}, "MY_UNSUPPORTED_DOMESTIC"),
    ({"contract_type": "GIG_PLATFORM"}, "MY_UNSUPPORTED_CONTRACT:GIG_PLATFORM"),
    ({"pay_frequency": "WEEKLY"}, "MY_PAY_FREQUENCY_UNSUPPORTED:WEEKLY"),
    ({"status": "DRAFT"}, "MY_PROFILE_NOT_ACTIVE"),
])
def test_unsupported_workers_are_refused(change, code):
    assert _blocked(ctx(profile_=profile(**change))).key == code


def test_missing_inputs_are_refused():
    assert _blocked(ctx(pay_date=None, my_pay_date=None)).key == "MY_PAY_DATE_MISSING"
    assert _blocked(ctx(start=None)).key == "MY_PERIOD_MISSING"
    assert _blocked(ctx(gross="5000", components={"BASIC_SALARY": Decimal("4000")})).key == "MY_COMPONENTS_MISMATCH"
    assert _blocked(ctx(components={"SALARY": Decimal("5000")})).key == "MY_COMPONENT_UNKNOWN:SALARY"


def test_no_statutory_number_in_the_engine_modules():
    import pathlib
    import re

    folder = pathlib.Path(malaysia.__file__).parents[1] / "jurisdictions" / "malaysia"
    files = list(folder.glob("*.py")) + [pathlib.Path(malaysia.__file__)]
    for path in files:
        text = re.sub(r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.S)
        code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
        for literal in ("1700", "5000", "6000", "20000", "4000", "0.75", "0.2", "0.5", " 11", " 13", " 12",
                        " 30", " 45", " 98", " 60", " 18", " 90"):
            assert literal not in code, (path.name, literal)
