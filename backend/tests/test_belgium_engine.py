"""Belgium (ZP-BE-ENG-001) Block A3: the calculation engine.

SYNTHETIC signed packs only (tests/_be_engine_helpers.py — TEST ONLY codes and
figures, never the spec's proposed values; the real seeded Draft pack is never
signed or activated). Expected figures are hand-derived from those fake rows:

  white-collar, gross 1000: employee ONSS 10% = 100, social work bonus 30
  -> 70; taxable 1000 - 70 = 930; scale 10% = 93; fiscal work bonus
  30 x 0.5 = 15 -> withholding 78; net 1000 - 78 - 70 = 852; employer lines
  base 100 + wage moderation 100 + special 0 + fund 10 = 210.
"""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests._be_engine_helpers import PAY, TEST, build_pack, context, rate, records, slab


def _calc(ctx, mode="standard"):
    from app.modules.payroll.engine.resolver import calculate_payroll

    return calculate_payroll(ctx, mode)


def _blocked(ctx):
    from app.modules.payroll.engine.countries.belgium import BECalculationBlockedError

    with pytest.raises(BECalculationBlockedError) as raised:
        _calc(ctx)
    return raised.value.key


def _manual():
    return dict(records()["be_profile"], worker_category="MANUAL")


def test_white_collar_result_and_platform_mapping():
    r = _calc(context())
    b = r.be_result
    assert (r.tds, r.net_pay, r.employer_esi, r.employer_pension) == (Decimal("78.00"), Decimal("852.00"),
                                                                       Decimal("210.00"), Decimal("0"))
    assert r.total_deductions == Decimal("148.00")                 # tds + be_employee_total only, never doubled
    assert (b["be_onss_employee"], b["be_social_work_bonus"], b["be_employee_total"]) == ("100.00", "30.00", "70.00")
    assert b["be_net"] == "852.00" and b["employmentLine"] == "MAIN"
    assert r.employee_esi == Decimal("0") and r.employee_pension == Decimal("0")
    json.dumps(b)


# ── 108% base: manual only (BE-016) ─────────────────────────────────────────
def test_white_collar_is_never_on_the_manual_base_and_manual_is():
    white = _calc(context()).be_result
    manual = _calc(context(be_profile=_manual())).be_result
    assert white["trace"]["onss"]["manualBase"] is False and white["trace"]["onss"]["employeeBase"] == "1000"
    assert "ONSS_MANUAL_108_BASE" not in white["accumulatorDeltas"]
    assert manual["trace"]["onss"]["manualBase"] is True
    assert manual["trace"]["onss"]["employeeBase"] == "1100.00"      # base + the signed TEST uplift of 10%
    assert manual["accumulatorDeltas"]["ONSS_MANUAL_108_BASE"] == "1100.00"
    assert manual["be_onss_employee"] == "110.00"


def test_manual_holiday_contributions_are_obligation_deltas_only():
    white = _calc(context())
    manual = _calc(context(be_profile=_manual()))
    assert white.be_result["obligationDeltas"] == {}
    assert manual.be_result["obligationDeltas"] == {"HOLIDAY_FUND_QUARTERLY": "110.00"}
    assert manual.employer_esi == Decimal("231.00")                  # 110 + 110 + 0 + 11: no holiday amount in it


def test_a_manual_category_outside_the_signed_list_is_white_collar():
    pack = build_pack(rates_over={"be_onss_manual_base_categories": rate("be_onss_manual_base_categories",
                                                                        text="EMPLOYEE")})
    r = _calc(context(pack=pack, be_profile=_manual())).be_result
    assert r["trace"]["onss"]["manualBase"] is False


# ── employer composition (BE-019) and work bonuses (BE-012) ────────────────
def test_employer_lines_stay_separate():
    b = _calc(context()).be_result
    assert b["be_onss_employer"] == {"BASE": "100.00", "WAGE_MODERATION": "100.00", "SPECIAL_160": "0"}
    assert b["be_funds"] == {"FUND_A": "10.00"}
    registration = dict(records()["be_registration"], onss_special_160_status="APPLIES")      # G-25
    applies = _calc(context(be_registration=registration))
    assert applies.be_result["be_onss_employer"]["SPECIAL_160"] == "100.00" and applies.employer_esi == Decimal("310.00")
    pension = _calc(context(be_pension_premium=Decimal("1000")))
    assert pension.employer_pension == Decimal("100.00") and pension.employer_esi == Decimal("210.00")


def test_social_and_fiscal_work_bonus_are_independent():
    base = _calc(context()).be_result
    rate_map, slabs = build_pack(drop_slabs=("be_wht_fiscal_work_bonus",),
                                 slabs_over=[slab("be_wht_fiscal_work_bonus", formula="0")])
    no_fiscal = _calc(context(pack=(rate_map, slabs))).be_result
    assert no_fiscal["be_social_work_bonus"] == base["be_social_work_bonus"] == "30.00"
    assert (base["be_fiscal_work_bonus"], no_fiscal["be_fiscal_work_bonus"]) == ("15.00", "0.00")
    assert no_fiscal["be_withholding"] == "93.00" and no_fiscal["be_onss_employee"] == base["be_onss_employee"]
    assert base["accumulatorDeltas"]["WORK_BONUS_SOCIAL"] == "30.00"
    assert base["accumulatorDeltas"]["WORK_BONUS_FISCAL"] == "15.00"


def test_the_social_work_bonus_never_exceeds_the_contribution():
    rate_map, slabs = build_pack(drop_slabs=("be_red_social_work_bonus",),
                                 slabs_over=[slab("be_red_social_work_bonus", flat="1000")])
    b = _calc(context(pack=(rate_map, slabs))).be_result
    assert b["be_social_work_bonus"] == "100.00" and b["be_employee_total"] == "0.00"
    assert "BE_REDUCTION_CAPPED" in {e["code"] for e in b["exceptions"]}


# ── exceptional remuneration (BE-011) ───────────────────────────────────────
def test_exceptional_pay_never_goes_through_the_regular_path():
    r = _calc(context(gross="1500", components={"SALARY": "1000", "BONUS": "500"},
                      be_exceptional_reference=Decimal("10000")))
    b = r.be_result
    # ONSS 150 - 30 = 120, split by ONSS-base share: 80 regular, 40 exceptional
    assert b["accumulatorDeltas"]["WITHHOLDING_TAXABLE"] == "920.00"
    assert b["be_withholding_regular"] == "77.00"
    assert b["be_withholding_exceptional"] == {"EXCEPTIONAL": {"taxable": "460.00", "withholding": "46.00"}}
    assert r.tds == Decimal("123.00")
    assert "BONUS" not in b["trace"]["bases"]["WITHHOLDING_REGULAR"]["components"]


def test_holiday_pay_and_arrears_use_their_own_rules():
    r = _calc(context(gross="1300", components={"SALARY": "1000", "HOLIDAY_PAY_DOUBLE": "200", "ARREARS": "100"},
                      be_source_periods={"ARREARS": {"start": "2025-12-01", "end": "2025-12-31"}}))
    lines = r.be_result["be_withholding_exceptional"]
    assert lines["HOLIDAY_PAY"] == {"taxable": "200.00", "withholding": "20.00"}
    assert set(lines) == {"HOLIDAY_PAY", "ARREARS"}
    assert r.be_result["sourcePeriods"]["ARREARS"] == {"start": "2025-12-01", "end": "2025-12-31"}


def test_exceptional_pay_needs_its_reference_and_arrears_their_period():
    assert _blocked(context(gross="1500", components={"SALARY": "1000", "BONUS": "500"})) == \
        "BE_FACT_MISSING:exceptional_reference"
    assert _blocked(context(gross="1100", components={"SALARY": "1000", "ARREARS": "100"})) == \
        "BE_SOURCE_PERIOD_MISSING:ARREARS"


def test_a_component_in_both_withholding_bases_blocks():
    from app.modules.payroll.engine.countries import belgium_content as c

    rate_map, slabs = build_pack()
    for s in slabs:
        if s["rule_type"] == c.EARNING_CLASS_RULE and s["filing_status"] == "BONUS" \
                and s["tax_regime"] == "WITHHOLDING_REGULAR":
            s["assessment_basis"] = "INCLUDED"
    assert _blocked(context(pack=(rate_map, slabs), gross="1500", components={"SALARY": "1000", "BONUS": "500"},
                            be_exceptional_reference=Decimal("10000"))) == "BE_EARNING_CLASS_CONFLICT:BONUS"


# ── components (BE-006 / BE-008) ────────────────────────────────────────────
@pytest.mark.parametrize("components, gross, code", [
    ({"SALARY": "900", "TIPS": "100"}, "1000", "BE_COMPONENT_UNKNOWN:TIPS"),
    ({"SALARY": "900"}, "1000", "BE_COMPONENTS_MISMATCH:gross"),
    ({"SALARY": "1000", "ECOCHEQUE": "0.01"}, "1000.01", "BE_EARNING_CLASS_MISSING:ONSS_EMPLOYEE:ECOCHEQUE"),
])
def test_free_text_unknown_or_unclassified_pay_blocks(components, gross, code):
    assert _blocked(context(gross=gross, components=components)) == code


def test_a_review_treatment_blocks():
    from app.modules.payroll.engine.countries import belgium_content as c

    rate_map, slabs = build_pack()
    for s in slabs:
        if s["rule_type"] == c.EARNING_CLASS_RULE and s["filing_status"] == "SALARY" \
                and s["tax_regime"] == "ONSS_EMPLOYEE":
            s["assessment_basis"] = "REVIEW"
    assert _blocked(context(pack=(rate_map, slabs))) == "BE_EARNING_CLASS_REVIEW:ONSS_EMPLOYEE:SALARY"


def test_platform_pay_maps_through_the_active_mappings_and_unmapped_pay_blocks():
    """G-28: every non-zero platform amount needs an ACTIVE mapping (BE-008)."""
    assert _blocked(context(overtime=Decimal("50"))) == "BE_COMPONENT_UNMAPPED:PLATFORM_FIELD:overtime"
    assert _blocked(context(be_allowance_items=[{"key": "transport", "amount": "50"}])) == \
        "BE_COMPONENT_UNMAPPED:POLICY_ALLOWANCE:transport"
    mapped = {"PLATFORM_FIELD:basic": "SALARY", "PLATFORM_FIELD:overtime": "SUNDAY_HOLIDAY_PREMIUM"}
    from tests._be_engine_helpers import CLASSES
    assert "SUNDAY_HOLIDAY_PREMIUM" not in CLASSES              # no signed earning class -> it blocks next
    ctx = context(gross="1050", overtime=Decimal("50"), be_component_mappings=mapped)
    ctx.basic = Decimal("1000")                                      # basic 1000 + overtime 50 = gross 1050
    assert _blocked(ctx) == "BE_EARNING_CLASS_MISSING:ONSS_EMPLOYEE:SUNDAY_HOLIDAY_PREMIUM"
    ok = _calc(context(gross="1000", be_component_mappings={"PLATFORM_FIELD:basic": "SALARY"})).be_result
    assert ok["trace"]["bases"]["ONSS_EMPLOYEE"]["components"] == ["SALARY"]


def test_benefits_in_kind_and_applicable_reductions_block():
    """G-27: company car / BIK valuation and structural / target-group reductions
    block whenever they apply; NOT_SUPPORTED is recorded as not applied."""
    assert _blocked(context(gross="1100", components={"SALARY": "1000", "BENEFIT_IN_KIND": "100"})) == \
        "BE_BENEFIT_IN_KIND_UNSUPPORTED:BENEFIT_IN_KIND"
    applies = build_pack(rates_over={"be_red_structural": rate("be_red_structural", text="SLAB_ROWS")})
    assert _blocked(context(pack=applies)) == "BE_REDUCTION_UNSUPPORTED:be_red_structural"
    pending = build_pack(rates_over={"be_red_target_group": rate("be_red_target_group", text="NOT_SUPPORTED",
                                                                 label="x [PENDING G1]")})
    assert _blocked(context(pack=pending)) == "BE_CONTENT_PENDING:be_red_target_group"
    assert _calc(context()).be_result["trace"]["onss"]["reductions"] == {
        "be_red_structural": "NOT_APPLIED", "be_red_target_group": "NOT_APPLIED"}


# ── pending / NOT_SUPPORTED / missing dimension ────────────────────────────
@pytest.mark.parametrize("key", ["be_onss_employee_rate", "be_rounding_withholding", "be_onss_wage_moderation"])
def test_pending_or_not_supported_content_blocks(key):
    pending = build_pack(rates_over={key: dict(build_pack()[0][key], label="x [PENDING G1]")})
    assert _blocked(context(pack=pending)) == f"BE_CONTENT_PENDING:{key}"
    refused = build_pack(rates_over={key: rate(key, text="NOT_SUPPORTED")})
    assert _blocked(context(pack=refused)) == f"BE_FEATURE_BLOCKED:{key}"


def test_a_pending_slab_row_blocks():
    rate_map, slabs = build_pack(drop_slabs=("be_wht_annex3_regular_scale",),
                                 slabs_over=[slab("be_wht_annex3_regular_scale", pct="10.00",
                                                  label="x [PENDING G1]")])
    assert _blocked(context(pack=(rate_map, slabs))).startswith("BE_CONTENT_PENDING:BE_WHT_ANNEX3_REGULAR_SCALE")


def test_a_missing_employer_dimension_blocks():
    rate_map, slabs = build_pack(drop_slabs=("be_onss_employer_base_rate",),
                                 slabs_over=[slab("be_onss_employer_base_rate", pct="10.00", dims="EC=X1;WC=W1")])
    profile = dict(records()["be_profile"], onss_worker_code="W2")
    assert _blocked(context(pack=(rate_map, slabs), be_profile=profile)) == "BE_ROW_MISSING:be_onss_employer_base_rate"


def test_an_invalid_signed_formula_blocks():
    rate_map, slabs = build_pack(drop_slabs=("be_wht_annex3_amendment_2026",),
                                 slabs_over=[slab("be_wht_annex3_amendment_2026", formula="__import__('os')")])
    assert _blocked(context(pack=(rate_map, slabs))) == "BE_FORMULA_INVALID:be_wht_annex3_amendment_2026"


def test_the_resolver_blocks_before_any_money_rule():
    assert _blocked(context(be_registration=None)) == "BE_REGISTRATION_MISSING"


@pytest.mark.parametrize("over, code", [
    ({"be_profile": dict(records()["be_profile"], pay_basis=None)}, "BE_FACT_MISSING:pay_basis"),          # G-22
    ({"be_profile": dict(records()["be_profile"], pay_basis="HOURLY")}, "BE_PAY_BASIS_UNSUPPORTED:HOURLY"),
    ({"be_classifications": [dict(records()["be_classifications"][0], contract_type=None)]},
     "BE_FACT_MISSING:contract_type"),                                                                      # G-23
    ({"be_classifications": [dict(records()["be_classifications"][0], contract_type="STUDENT")]},
     "BE_CONTRACT_UNSUPPORTED:STUDENT"),
    ({"be_registration": dict(records()["be_registration"], onss_special_160_status="UNKNOWN")},
     "BE_SPECIAL_160_UNKNOWN"),                                                                              # G-25
    ({"be_registration": dict(records()["be_registration"], onss_special_160_status=None)},
     "BE_SPECIAL_160_UNKNOWN"),
    ({"be_profile": dict(records()["be_profile"], residency="NON_RESIDENT")}, "BE_NON_RESIDENT_UNSUPPORTED"),  # G-27
])
def test_each_block_b_decision_blocks_the_calculation(over, code):
    assert _blocked(context(**over)) == code


def test_several_employment_lines_block():
    lines = records()["be_classifications"] + [dict(records()["be_classifications"][0], id=4,
                                                    employment_line="SECOND", work_schedule_id=40)]
    assert _blocked(context(be_classifications=lines)) == "BE_MULTI_LINE_UNSUPPORTED"


def test_a_second_line_inside_the_pay_period_blocks_too():
    """G-27: one Active line per employee per PAY PERIOD — a line that ended
    inside the period still counts."""
    ended = dict(records()["be_classifications"][0], id=5, employment_line="SECOND", effective_to="2026-03-10",
                 work_schedule_id=40)
    ctx = context(be_classifications=records()["be_classifications"] + [ended])
    assert _calc(ctx).be_result["employmentLine"] == "MAIN"                   # no period: the pay date decides
    ctx.period_start = date(2026, 3, 1)
    assert _blocked(ctx) == "BE_MULTI_LINE_UNSUPPORTED"


def test_no_pay_date_blocks():
    ctx = context()
    ctx.be_pay_date = None
    ctx.pay_date = None
    assert _blocked(ctx) == "BE_PAY_DATE_MISSING"


# ── mid-year row change (30 Jun / 1 Jul) ────────────────────────────────────
def test_a_row_ending_30_june_and_its_successor_from_1_july():
    rows = [rate("be_onss_employee_rate", employee="10.00", end="2026-06-30"),
            rate("be_onss_employee_rate", employee="20.00", start="2026-07-01")]
    pack = build_pack(rates_over={"be_onss_employee_rate": rows})
    june = _calc(context(pack=pack, pay_date=date(2026, 6, 30))).be_result
    july = _calc(context(pack=pack, pay_date=date(2026, 7, 1))).be_result
    assert (june["be_onss_employee"], july["be_onss_employee"]) == ("100.00", "200.00")
    assert june["hashes"]["content"] != july["hashes"]["content"]


# ── BSSC (D7) ───────────────────────────────────────────────────────────────
def test_the_bssc_is_an_exception_and_never_computed():
    b = _calc(context()).be_result
    assert "BE_BSSC_PENDING" in {e["code"] for e in b["exceptions"]}
    assert not any("BSSC" in k for k in b["be_onss_employer"]) and "BSSC" not in json.dumps(b["accumulatorDeltas"])


def test_the_trace_records_pack_and_interpreter_versions():
    from app.modules.payroll.engine.jurisdictions.belgium.formula import INTERPRETER_VERSION

    b = _calc(context()).be_result
    assert b["trace"]["withholding"]["packVersion"] == "TEST-PACK@1.0"
    assert b["hashes"]["interpreter"] == b["trace"]["withholding"]["interpreterVersion"] == INTERPRETER_VERSION
    assert {u["id"] for u in b["usedRows"]} >= {"be_onss_employee_rate", "be_rounding_onss"}


# ── freeze / replay ─────────────────────────────────────────────────────────
def test_replay_of_a_frozen_snapshot_reproduces_result_and_hashes():
    from app.modules.payroll import belgium_service as be

    rows = [rate("be_onss_employee_rate", employee="10.00", end="2026-06-30"),
            rate("be_onss_employee_rate", employee="20.00", start="2026-07-01")]
    for ctx in (context(), context(be_profile=_manual()),
                context(pack=build_pack(rates_over={"be_onss_employee_rate": rows}), pay_date=date(2026, 7, 31)),
                context(gross="1500", components={"SALARY": "1000", "BONUS": "500"},
                        be_exceptional_reference=Decimal("10000"))):
        original = _calc(ctx)
        frozen = json.loads(json.dumps(be.be_freeze_context(ctx, "standard")))       # as stored
        replayed = be.be_replay(frozen)
        assert replayed.net_pay == original.net_pay and replayed.tds == original.tds
        assert replayed.be_result["hashes"] == original.be_result["hashes"]
        assert replayed.be_result["accumulatorDeltas"] == original.be_result["accumulatorDeltas"]
        snapshot = be.be_payslip_snapshot(original, frozen)
        assert snapshot["frozenContext"] == frozen and be.be_payslip_view(snapshot).get("frozenContext") is None


def test_the_frozen_context_holds_no_vault_or_credential_reference():
    from app.modules.payroll import belgium_service as be

    registration = dict(records()["be_registration"], onss_number_vault_id=77, filing_credential_ref="cred-ref",
                        mandate_refs=["m1"])
    profile = dict(records()["be_profile"], niss_vault_id=88)
    frozen = json.dumps(be.be_freeze_context(context(be_registration=registration, be_profile=profile)))
    for leaked in ("niss_vault_id", "onss_number_vault_id", "cred-ref", "filing_credential_ref", "mandate_refs"):
        assert leaked not in frozen


def test_non_be_contexts_are_untouched():
    from app.modules.payroll.engine.base import PayrollContext

    ctx = PayrollContext(gross=Decimal("1000"), basic=Decimal("1000"), country="IN")
    assert ctx.be_pay_date is None and ctx.be_components is None
    assert _calc(ctx).be_result is None


# ── service: calc inputs, preview vs generate, ledger ──────────────────────
@pytest.fixture
def world(db, monkeypatch):
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="Engine BV", code="BEENGINE", admins=2, country="BE")
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="BE1", name="Test Worker", country_code="BE",
                               employment_type="Full-time", pay_frequency="Monthly", ctc=Decimal("12000"),
                               basic=Decimal("12000"), hra=Decimal("0"), date_of_joining=date(2025, 1, 1))
    db.add(employee)
    db.commit()
    return SimpleNamespace(db=db, org=t.org.id, a=t.users[0].id, b=t.users[1].id, employee=employee)


def _setup_records(w):
    from app.modules.payroll import belgium_service as be

    def two_step(record, approve, *args):
        row = record(*args)
        w.db.commit()
        return approve(w.db, w.org, row.id, w.b)

    reg = two_step(be.record_be_employer_registration, be.approve_be_employer_registration, w.db, w.org,
                   {"effective_from": "2026-01-01", "legal_name": "Engine BV", "enterprise_number": "0999999999",
                    "employer_category_code": "X1", "onss_special_160_status": "NOT_APPLICABLE",
                    "special_160_evidence_ref": "TEST ONLY workforce count"}, w.a, "setup")
    be.verify_be_employer_registration(w.db, w.org, reg.id, w.b, "VERIFIED", "checked")
    two_step(be.record_be_worker_profile, be.approve_be_worker_profile, w.db, w.org, w.employee.id,
             {"effective_from": "2026-01-01", "worker_category": "EMPLOYEE", "onss_worker_code": "W1",
              "residency": "RESIDENT", "pay_basis": "SALARIED"}, w.a, "hire")
    two_step(be.record_be_work_schedule, be.approve_be_work_schedule, w.db, w.org, w.employee.id,
             {"effective_from": "2026-01-01", "regime": "EFFECTIVE", "weekly_hours": "38"}, w.a, "hire")
    two_step(be.record_be_employment_classification, be.approve_be_employment_classification, w.db, w.org,
             w.employee.id, {"effective_from": "2026-01-01", "employment_line": "MAIN", "joint_committee": "200",
                             "function_class": "B", "seniority_months": 0, "contract_type": "INDEFINITE",
                             "contract_start_date": "2026-01-01"}, w.a, "hire")
    for field_name in ("basic", "hra", "special_allowance"):           # G-28: the platform pay fields used
        two_step(be.record_be_component_mapping, be.approve_be_component_mapping, w.db, w.org,
                 {"platform_component_source": "PLATFORM_FIELD", "platform_component_key": field_name,
                  "be_component": "SALARY", "effective_from": "2026-01-01"}, w.a, "mapping")
    w.db.commit()


def test_calc_inputs_come_from_the_records_and_need_a_pay_date(world):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import belgium_service as be

    w = world
    _setup_records(w)
    with pytest.raises(BadRequestException, match="pay date"):
        be.calc_inputs(w.db, None, w.employee, None)
    inputs = be.calc_inputs(w.db, None, w.employee, None, as_of=PAY)
    assert inputs["be_pay_date"] == PAY and inputs["be_profile"]["worker_category"] == "EMPLOYEE"
    assert inputs["be_profile"]["pay_basis"] == "SALARIED"                                        # G-22
    assert inputs["be_classifications"][0]["contract_type"] == "INDEFINITE"                          # G-23
    assert inputs["be_registration"]["onss_special_160_status"] == "NOT_APPLICABLE"                  # G-25
    assert inputs["be_component_mappings"] == {f"PLATFORM_FIELD:{f}": "SALARY"
                                               for f in ("basic", "hra", "special_allowance")}         # G-28
    assert inputs["be_ytd"]["WITHHOLDING"] == Decimal("0")
    assert "niss_vault_id" not in json.dumps(inputs, default=str)
    rate_map, slabs = build_pack()
    from app.modules.payroll.engine.base import PayrollContext
    ctx = PayrollContext(gross=Decimal("1000"), basic=Decimal("1000"), country="BE", rate_map=rate_map,
                         slabs=slabs, pay_date=PAY, **inputs)
    assert _calc(ctx).be_result["be_net"] == "852.00"


def _patch_pack_and_basis(monkeypatch):
    """Test seam only: the synthetic pack instead of the canonical resolver (the
    real Draft pack is never signed or activated). The pay basis comes from the
    recorded worker profile (G-22) — no shortcut."""
    from app.modules.payroll import service

    rate_map, slabs = build_pack()
    # the shared service reads pack rows as objects (ORM rows), so hand it objects
    def row(values):
        numbers = ("min_amount", "max_amount", "rate_pct", "flat_amount", "employee_rate_pct", "employer_rate_pct")
        out = {"tax_regime": None, "assessment_basis": None, "min_amount": "0", "max_amount": None, "rate_pct": "0",
               "flat_amount": None, **values}
        return SimpleNamespace(**{k: (Decimal(v) if k in numbers and v is not None else v) for k, v in out.items()})

    rate_map = {k: row(v) for k, v in rate_map.items()}
    slabs = [row(v) for v in slabs]
    real_resolve = service._resolve_effective_rate_inputs

    def resolve(db, organization_id, country, *args, **kwargs):
        if (country or "").upper() in ("BE", "BELGIUM"):
            return rate_map, slabs, [], None
        return real_resolve(db, organization_id, country, *args, **kwargs)

    monkeypatch.setattr(service, "_resolve_effective_rate_inputs", resolve)
    # SQLite has no pg_advisory_xact_lock: the same fake code generator other
    # SQLite generation tests use (tests/_nz_p6_fixtures.py).
    from app.core import code_generation
    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter):05d}")


def test_preview_and_generate_agree_and_nothing_is_posted_before_commit(world, monkeypatch):
    """G-29: generation writes the payslip and its frozen snapshot only; the
    ledger is posted at run commit (tests/test_belgium_run_lifecycle.py)."""
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollBeAccumulatorEntry, PayrollRun, PayslipItem

    w = world
    _setup_records(w)
    _patch_pack_and_basis(monkeypatch)
    preview = service.preview_payroll_run(w.db, w.org, [w.employee.id], "BE", period_start=date(2026, 3, 1),
                                          period_end=PAY, pay_date=PAY)
    row = preview["employees"][0] if isinstance(preview, dict) and "employees" in preview else preview["results"][0]
    run = PayrollRun(organization_id=w.org, period_label="Mar 2026", period_start=date(2026, 3, 1),
                     period_end=PAY, pay_date=PAY)
    w.db.add(run)
    w.db.commit()
    service.generate_payslips_for_run(w.db, run, w.org)
    item = w.db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
    assert item.be_calculation_snapshot, item.notes
    assert Decimal(str(row["monthlyNet"])) == Decimal(str(item.net_pay)) == Decimal("852.00")
    assert Decimal(str(row["monthlyTax"])) == Decimal(str(item.tds))
    snapshot = item.be_calculation_snapshot
    assert snapshot["frozenContext"]["version"] == 1
    assert be.be_replay(snapshot["frozenContext"]).be_result["hashes"] == snapshot["hashes"]
    assert w.db.query(PayrollBeAccumulatorEntry).count() == 0                    # nothing before commit
    view = service._serialize_payslip(item, run)
    assert view["beCalculationSnapshot"]["be_net"] == "852.00"
    assert "frozenContext" not in view["beCalculationSnapshot"]
    assert be.be_ytd_snapshot(w.db, w.org, w.employee.id, None, date(2026, 4, 30))["WITHHOLDING"] == Decimal("0")


def test_draft_regeneration_and_deletion_post_nothing(world, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollBeAccumulatorEntry, PayrollRun, PayslipItem

    w = world
    _setup_records(w)
    _patch_pack_and_basis(monkeypatch)
    run = PayrollRun(organization_id=w.org, period_label="Mar 2026", period_start=date(2026, 3, 1),
                     period_end=PAY, pay_date=PAY)
    w.db.add(run)
    w.db.commit()
    service.generate_payslips_for_run(w.db, run, w.org)
    service.regenerate_employee_payslip(w.db, run.id, w.employee.id, w.org, actor_id=w.a)
    assert w.db.query(PayrollBeAccumulatorEntry).count() == 0
    item = w.db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one()
    service.delete_payslip(w.db, item.id, w.org)
    assert w.db.query(PayrollBeAccumulatorEntry).count() == 0
