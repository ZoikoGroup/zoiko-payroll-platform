"""Mexico engineering sweep S1 — decisions as configuration. Every pending
decision has its options built; the APPROVED answer in the register (four-eyes)
switches the behaviour with no code change; unanswered, the case keeps blocking
with its own code. One test per option path. SYNTHETIC values; the answers
here are test inputs, not decisions."""

from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_mexico_router import SA_A

SA_B_ID = SA_A.id + 1
DOCS = Path(__file__).resolve().parents[2] / "docs" / "mexico"


def _C():
    from app.modules.payroll import mexico_decision_config

    return mexico_decision_config


def answer(db, code, value):
    """Propose (SA_A) and approve (a second Super Admin) one answer."""
    from app.modules.payroll import mexico_decision_service as S
    from app.modules.payroll.models import PayrollMxDecision as M

    S.seed_decisions(db)
    db.commit()
    row = db.query(M).filter(M.code == code).order_by(M.version.desc()).first()
    if row.status in ("APPROVED", "TRANSCRIBED"):                     # re-answering: open a new version first
        S.revise_mx_decision(db, row.id, SA_A.id)
        db.commit()
        row = db.query(M).filter(M.code == code).order_by(M.version.desc()).first()
    S.propose_mx_decision(db, row.id, {"chosen_option": value, "rationale": "SYNTHETIC", "cited_sources": ["S1"]},
                          SA_A.id)
    S.approve_mx_decision(db, row.id, SA_B_ID)
    db.commit()


def run_with(db, fn):
    with _C().applying(db):
        return fn()


def _code(exc_info):
    return exc_info.value.key


class _Content:
    """SYNTHETIC content: the UMA 117.31, minimum wages GENERAL 315.04 / ZLFN 440.87."""

    def __init__(self, rows=None):
        self.rows = rows or {}

    def amount(self, key):
        return {"mx_uma_daily": D("117.31")}[key]

    def min_wage(self, zone):
        return {"GENERAL": D("315.04"), "ZLFN": D("440.87")}[zone]

    def has(self, key):
        return key in self.rows

    def text(self, key):
        return self.rows[key]


# ── the register ─────────────────────────────────────────────────────────

def test_every_pending_decision_is_configured(db):
    from app.modules.payroll import mexico_decision_service as S

    pending = {r["code"] for r in S.parse_decisions((DOCS / "DECISIONS_PENDING.md").read_text(encoding="utf-8"),
                                                    (DOCS / "MEXICO_COMPLETION_GAP_REGISTER.md").read_text(encoding="utf-8"))}
    assert pending <= set(_C().config()), pending - set(_C().config())


@pytest.mark.parametrize("code,good,bad", [
    ("D-03", "ZONE", "SOMETHING"), ("D-09", "CALENDAR_MONTH", "31"), ("D-12", "IMSS_SBC", "GUESS"),
    ("D-14", "EXCESS=REDISTRIBUTED;AVERAGE=OVER_THREE", "EXCESS=REDISTRIBUTED"),
    ("D-06", "VACATION_PAYOUT=IN;SEPARATION_PAYMENT=OUT;SEPARATION_INDEMNITY=IN", "VACATION_PAYOUT=MAYBE"),
    ("D-28", ";".join(f"{p}=SINGLE" for p in ("EMPLOYER_VERSION", "ESTABLISHMENT", "IMSS_REGISTRATION",
                                               "INFONAVIT_MODEL", "LABOR_POLICY_ACTIVATION", "CREDENTIAL")),
     "CREDENTIAL=FOUR_EYES"),
    ("D-23", "INTERIM_SECOND_SUPER_ADMIN", "GATE_OWNER_ROLE"),
])
def test_the_register_accepts_only_the_options_built(db, code, good, bad):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_decision_service as S
    from app.modules.payroll.models import PayrollMxDecision as M

    S.seed_decisions(db)
    db.commit()
    row = db.query(M).filter(M.code == code).one()
    S.validate_answer(row, good)
    with pytest.raises(BadRequestException):
        S.validate_answer(row, bad)
    view = S.view(row)
    assert view["configuration"]["changes"] and view["allowedValues"]


def test_an_approved_answer_is_in_force_and_its_ticket_says_so(db):
    from app.modules.payroll import mexico_decision_service as S
    from app.modules.payroll.models import PayrollMxDecision as M

    assert _C().answers_in_force(db) == {}
    answer(db, "D-07", "UMA")
    answers = _C().answers_in_force(db)
    assert answers["D-07"]["value"] == "UMA" and answers["D-07"]["version"] == 1
    t = S.ticket(db.query(M).filter(M.code == "D-07").one())
    assert t["inForce"] is True and "nothing to transcribe" in t["then"]


def test_a_proposed_answer_is_not_in_force(db):
    from app.modules.payroll import mexico_decision_service as S
    from app.modules.payroll.models import PayrollMxDecision as M

    S.seed_decisions(db)
    db.commit()
    row = db.query(M).filter(M.code == "D-07").one()
    S.propose_mx_decision(db, row.id, {"chosen_option": "UMA", "rationale": "x", "cited_sources": ["S1"]}, SA_A.id)
    assert "D-07" not in _C().answers_in_force(db)


# ── unanswered: each case keeps its own block ────────────────────────────

def test_unanswered_switches_keep_blocking_with_their_codes(db):
    from app.modules.payroll.engine.countries import mexico_rules as r
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    facts = {"content": _Content(), "zone": "GENERAL", "daily_salary": D("500"), "pay_date": date(2026, 2, 10)}
    for fn, code in ((lambda: r.reference_wage(facts), "MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED"),
                     (lambda: r.monthly_ordinary_income(facts), "MX_MONTHLY_ORDINARY_INCOME_UNDECIDED"),
                     (lambda: r.service_years(date(2020, 1, 1), date(2026, 6, 1)), "MX_SERVICE_YEARS_COUNT_UNDECIDED"),
                     (lambda: r.indemnity_daily_salary(facts), "MX_INDEMNITY_SALARY_UNDECIDED")):
        with pytest.raises(MXBlock) as e:
            run_with(db, fn)
        assert _code(e) == code


# ── each option's path ──────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [("UMA", D("117.31")), ("ZONE_MIN_WAGE", D("440.87"))])
def test_d07_reference_wage(db, value, expected):
    from app.modules.payroll.engine.countries import mexico_rules as r

    answer(db, "D-07", value)
    assert run_with(db, lambda: r.reference_wage({"content": _Content(), "zone": "ZLFN"})) == expected


@pytest.mark.parametrize("value,cap", [("UMA", D("234.62")), ("ZONE_MIN_WAGE", D("630.08"))])
def test_d07b_seniority_premium_cap(db, value, cap):
    from app.modules.payroll.engine.countries import mexico_rules as r

    answer(db, "D-07b", value)
    salary = run_with(db, lambda: r.seniority_premium_daily_salary(
        {"content": _Content(), "zone": "GENERAL", "daily_salary": D("5000")}))
    assert salary == cap                                                           # capped at 2 × the reference


@pytest.mark.parametrize("value,expected", [("30", D("15000")), ("30.4", D("15200")), ("CALENDAR_MONTH", D("14000"))])
def test_d09_monthly_ordinary_income(db, value, expected):
    from app.modules.payroll.engine.countries import mexico_rules as r

    answer(db, "D-09", value)
    facts = {"daily_salary": D("500"), "pay_date": date(2026, 2, 10)}                 # February 2026: 28 days
    assert run_with(db, lambda: r.monthly_ordinary_income(facts)) == expected


def test_d08_art_96_monthly_method(db, monkeypatch):
    from app.modules.payroll.engine.countries import mexico_rules as r

    monkeypatch.setattr(r, "monthly_isr", lambda base, facts: base * D("0.10"))       # SYNTHETIC tariff
    answer(db, "D-08", "ART_96_MONTHLY")
    facts = {"month_to_date": {"taxable": D("10000"), "isr_withheld": D("900")}}
    isr = run_with(db, lambda: r.SPECIAL_PAY_RULES["AGUINALDO"].standalone_isr(D("5000"), facts))
    assert isr == D("600")                                                          # 10% × 15000 − 900


def test_d08_per_employer_method(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_employer_service as E
    from app.modules.payroll.engine.countries import mexico_rules as r
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    monkeypatch.setattr(r, "monthly_isr", lambda base, facts: base * D("0.10"))       # SYNTHETIC tariff
    answer(db, "D-08", "PER_EMPLOYER")
    facts = {"month_to_date": {"taxable": D("10000"), "isr_withheld": D("900")},
             "employer_special_pay_method": "ART_96_MONTHLY"}
    isr = run_with(db, lambda: r.SPECIAL_PAY_RULES["AGUINALDO"].standalone_isr(D("5000"), facts))
    assert isr == D("600")                                                          # the employer's method
    with pytest.raises(MXBlock) as e:                                               # the policy names none
        run_with(db, lambda: r.SPECIAL_PAY_RULES["AGUINALDO"].standalone_isr(D("5000"), {}))
    assert _code(e) == "MX_SPECIAL_PAY_METHOD_UNDECIDED"
    assert E._special_pay_method("rlisr_174") == "RLISR_174" and E._special_pay_method("") is None
    with pytest.raises(BadRequestException):
        E._special_pay_method("PER_EMPLOYER")                                       # a policy names a real method


def test_d12_imss_sbc_and_operator_entered(db):
    from app.modules.payroll.engine.countries import mexico_rules as r
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    answer(db, "D-12", "IMSS_SBC")
    assert run_with(db, lambda: r.indemnity_daily_salary({"sbc_daily": D("612.5")})) == D("612.5")
    with pytest.raises(MXBlock) as e:
        run_with(db, lambda: r.indemnity_daily_salary({}))
    assert _code(e) == "MX_INDEMNITY_SALARY_SBC_MISSING"
    answer(db, "D-12", "OPERATOR_ENTERED")                                          # a new version, approved
    facts = {"operator_indemnity_daily_salary": D("700"), "operator_indemnity_evidence": "SYN-LETTER-1"}
    assert run_with(db, lambda: r.indemnity_daily_salary(facts)) == D("700")
    with pytest.raises(MXBlock) as e:
        run_with(db, lambda: r.indemnity_daily_salary({"operator_indemnity_daily_salary": D("700")}))
    assert _code(e) == "MX_INDEMNITY_SALARY_NOT_ENTERED"


@pytest.mark.parametrize("value,years", [("PROPORTIONAL", D("6.5")), ("COMPLETED", D("6"))])
def test_d13_service_years(db, value, years):
    from app.modules.payroll.engine.countries import mexico_rules as r

    answer(db, "D-13", value)
    got = run_with(db, lambda: r.service_years(date(2020, 1, 1), date(2026, 7, 2)))
    assert got.quantize(D("0.1")) == years


def _ptu_workers():
    # Worker 1 has a tiny salary base, so its share exceeds 90 days of its salary (the Art. 127 VIII cap).
    return [{"employee_id": 1, "days": D("365"), "salary_by_kind": {"PTU_WAGE_BASE": D("3650")}},
            {"employee_id": 2, "days": D("365"), "salary_by_kind": {"PTU_WAGE_BASE": D("365000")}},
            {"employee_id": 3, "days": D("365"), "salary_by_kind": {"PTU_WAGE_BASE": D("365000")}}]


@pytest.mark.parametrize("excess", ["UNDISTRIBUTED", "REDISTRIBUTED"])
def test_d14_cap_excess(db, excess):
    from app.modules.payroll.engine.countries import mexico_rules as r

    answer(db, "D-14", f"EXCESS={excess};AVERAGE=OVER_THREE")
    out = run_with(db, lambda: r.LftPtuRule().allocate(D("30000"), _ptu_workers(), 2026))
    capped = next(w for w in out["workers"] if w["employee_id"] == 1)
    assert capped["cap_applied"] and capped["final_amount"] == D("900")            # 90 days × 10.00
    paid = sum(w["final_amount"] for w in out["workers"])
    cent = D("0.01")
    if excess == "UNDISTRIBUTED":
        assert out["residue"] > cent and (paid + out["residue"]).quantize(cent) == D("30000")
    else:                                                          # full precision: a remainder below a cent at most
        assert abs(out["residue"]) < cent and paid.quantize(cent) == D("30000") and "shared" in out["residue_rule"]
        assert all(w["final_amount"] <= D(w["cap_reference"]["cap"]) for w in out["workers"])


@pytest.mark.parametrize("reading,due", [("LFT_74_715", date(2026, 5, 7)), ("CFF_12", date(2026, 5, 8))])
def test_d16_business_days(db, reading, due):
    from app.modules.payroll import mexico_due_dates as dd

    assert run_with(db, lambda: dd.movement_due(date(2026, 4, 29)))[0] is None     # unanswered: unsourced
    answer(db, "D-16", reading)
    got, rule = run_with(db, lambda: dd.movement_due(date(2026, 4, 29)))           # 30 Apr, 4, 5?, 6, 7 / 8 May
    assert got == due and "S10" in rule


@pytest.mark.parametrize("rule,expected", [("DAILY_SALARY_OVER_JORNADA_HOURS", D("100")),     # 800 ÷ 8 (Art. 61)
                                           ("WEEKLY_HOURS_OVER_DAYS", D("80")),                # 800 ÷ (60 h ÷ 6 days)
                                           ("EMPLOYER_DAILY_HOURS", D("125"))])                # 800 ÷ 6.4
def test_d17_hourly_rate(db, rule, expected):
    from app.modules.payroll.engine.jurisdictions.mexico import labor

    content = _Content({"mx_hourly_rate_rule": rule})
    policy = {"ordinary_weekly_hours": D("60"), "weekly_schedule": {"mon": 10, "tue": 10, "wed": 10, "thu": 10,
                                                                    "fri": 10, "sat": 10, "sun": 0},
              "hourly_rate_daily_hours": "6.4"}                    # SYNTHETIC figures, not a lawful week
    assert labor.hourly_rate(content, {"workday_type_code": "01"}, D("800"), policy) == expected


@pytest.mark.parametrize("value", ["PERIOD_DAYS", "ANNUALISED_365"])
def test_d18_fixed_sbc_rule(db, value):
    from app.modules.payroll.engine.jurisdictions.mexico import decision_rules as dr
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    assert dr.sbc_fixed_integration_rule(None) is None
    answer(db, "D-18", value)
    rule = run_with(db, lambda: dr.sbc_fixed_integration_rule(None))
    line = {"code": "BONO", "amount": D("1500"), "payments_per_year": 12}
    facts = {"segments": [{"days": 15}]}
    expected = D("100") if value == "PERIOD_DAYS" else D("1500") * 12 / 365
    assert rule.daily_amount(line, facts) == expected
    if value == "ANNUALISED_365":
        with pytest.raises(MXBlock):
            rule.daily_amount({"code": "BONO", "amount": D("1500")}, facts)


@pytest.mark.parametrize("value,days", [("FIXED_DAYS_PRORATED", D("7.5")), ("CALENDAR_DAYS_WORKED", D("8"))])
def test_d19_fixed_days_at_termination(db, value, days):
    from app.modules.payroll.engine.jurisdictions.mexico import decision_rules as dr

    answer(db, "D-19", value)
    rule = run_with(db, lambda: dr.fixed_days_termination_rule(None))
    assert rule.days_paid("QUINCENAL_15", date(2026, 6, 1), date(2026, 6, 16), date(2026, 6, 8)) == days


@pytest.mark.parametrize("value,expected", [("TEXT", "14300"), ("PADDED", "0000014300.000000")])
def test_d20_qr_total(db, value, expected):
    from app.modules.payroll import mexico_cfdi_receipt as rc

    assert rc.qr_total("14300.00") == "14300"                                      # unanswered: the text's form
    answer(db, "D-20", value)
    assert run_with(db, lambda: rc.qr_total("14300.00")) == expected


def test_d21_readings_and_keep_refusing(db):
    from app.modules.payroll import mexico_cfdi_input as ci
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    answer(db, "D-21", "SWAPPED")
    assert run_with(db, lambda: ci._inconsistent_offsets("x", {}, -6, -7)) == (-7, -6)
    answer(db, "D-21", "KEEP_REFUSING")
    with pytest.raises(MXBlock) as e:
        run_with(db, lambda: ci._inconsistent_offsets("x", {}, -6, -7))
    assert _code(e) == "MX_CFDI_TIMEZONE_RULE_INVALID"


@pytest.mark.parametrize("value,expected", [("MONTHLY_TOTAL_LESS_WITHHELD", D("600")), ("INCREMENTAL_MONTHLY", D("500"))])
def test_d22_finiquito_payout(db, monkeypatch, value, expected):
    from app.modules.payroll.engine.countries import mexico_rules as r

    monkeypatch.setattr(r, "monthly_isr", lambda base, facts: base * D("0.10"))
    answer(db, "D-22", value)
    facts = {"month_to_date": {"taxable": D("10000"), "isr_withheld": D("900")}}
    assert run_with(db, lambda: r._ordinary_payout_isr(D("5000"), facts)) == expected


def test_d02_daily_pay_frequency(db):
    from app.modules.payroll import mexico_run_service as rs
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    prof = SimpleNamespace(mx_pay_frequency_code="01")
    with pytest.raises(MXBlock):
        run_with(db, lambda: rs.payment_period(prof, date(2026, 6, 1), date(2026, 6, 1)))
    answer(db, "D-02", "DAILY")
    assert run_with(db, lambda: rs.payment_period(prof, date(2026, 6, 1), date(2026, 6, 1))) == "DAILY"


@pytest.mark.parametrize("ref,zone,unit", [("GENERAL", "ZLFN", D("315.04")), ("ZONE", "ZLFN", D("440.87")),
                                           ("UMA", "ZLFN", D("117.31"))])
def test_d03_ceav_band_one_unit(db, ref, zone, unit):
    from app.modules.payroll.engine.jurisdictions.mexico import ceav

    content = _Content({"mx_ceav_lowest_band_min_wage_ref": ref})
    assert ceav._unit_amount(content, "SM", D("117.31"), zone) == unit


def test_pack_row_decisions_fill_only_a_missing_row(db):
    answer(db, "D-01", "HALF_UP:0.01")
    answers = _C().answers_in_force(db)
    empty, carried = {}, {"mx_rounding_rule": {"text_value": "HALF_EVEN:0.01"}}
    assert _C().overlay_pack_rows([empty, carried], answers) == ["D-01"]
    assert empty["mx_rounding_rule"]["text_value"] == "HALF_UP:0.01"
    assert carried["mx_rounding_rule"]["text_value"] == "HALF_EVEN:0.01"            # a transcribed row wins


def test_the_sandbox_calculates_with_approved_d01_and_d03_and_no_candidates(db):
    from app.modules.payroll import mexico_decision_service, mexico_sandbox_service
    from scripts.seed_mexico_canonical_packs import seed_mexico

    seed_mexico(db)
    mexico_decision_service.seed_decisions(db)
    db.commit()
    data = {"payDate": "2026-06-15", "periodStart": "2026-06-01", "periodEnd": "2026-06-15", "dailySalary": "600",
            "zone": "GENERAL", "workState": "CDMX", "payFrequencyCode": "04", "seniorityDate": "2026-01-01"}
    # The canonical 2026 pack now transcribes the rounding and CEAV rows, so
    # the sandbox can calculate before any decision-register answers exist.
    initial = mexico_sandbox_service.run_mx_sandbox(db, data)
    assert initial["outcome"] == "CALCULATED" and initial["approvedDecisions"] == {}
    answer(db, "D-01", "HALF_UP:0.01")
    answer(db, "D-03", "GENERAL")
    out = mexico_sandbox_service.run_mx_sandbox(db, data)
    assert out["outcome"] == "CALCULATED" and out["candidates"] == []
    # Transcribed canonical pack rows take precedence over decision overlays;
    # the approved choices are still recorded in the decision trace.
    assert out["approvedPackRows"] == [] and set(out["approvedDecisions"]) == {"D-01", "D-03"}
    assert D(out["result"]["mx_result"]["isr_withheld"]) == D("726.36")            # = the X2 what-if (D-01 brief)


@pytest.mark.parametrize("value,included", [("IN", True), ("OUT", False)])
def test_d06_cdmx_isn_inclusion(db, value, included):
    from app.modules.payroll.engine.jurisdictions.mexico import special_pay
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    with pytest.raises(MXBlock):
        run_with(db, lambda: special_pay.isn_included("CDMX", "VACATION_PAYOUT"))
    answer(db, "D-06", f"VACATION_PAYOUT={value};SEPARATION_PAYMENT=OUT;SEPARATION_INDEMNITY=IN")
    assert run_with(db, lambda: special_pay.isn_included("CDMX", "VACATION_PAYOUT")) is included
    assert run_with(db, lambda: special_pay.isn_included("CDMX", "SEPARATION_INDEMNITY")) is True
    assert run_with(db, lambda: special_pay.isn_included("CDMX", "AGUINALDO")) is True   # transcribed, unchanged


@pytest.mark.parametrize("value,expected", [("IMSS_SBC", D("650")), ("LFT_84_INTEGRATED", D("629.589"))])
def test_c4_sdi_sources(db, value, expected):
    from app.modules.payroll import mexico_cfdi_input as ci

    result = {"sbc": {"components": {"daily_salary": "600", "factor": "1.049315"},
                      "segments": [{"sbc": "640"}, {"sbc": "650"}]}}
    assert ci.SDI_SOURCES[value](result, None) == expected


def test_c4_operator_entered_sdi(db):
    from app.modules.payroll import mexico_cfdi_input as ci
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    prof = SimpleNamespace(mx_sdi_operator_entered=D("712.40"), mx_sdi_evidence_ref="SYN-CONTRACT-1")
    assert ci.SDI_SOURCES["OPERATOR_ENTERED"]({}, prof) == D("712.40")
    for bad in (SimpleNamespace(mx_sdi_operator_entered=D("712.40"), mx_sdi_evidence_ref=None),
                SimpleNamespace(mx_sdi_operator_entered=None, mx_sdi_evidence_ref="SYN")):
        with pytest.raises(MXBlock):
            ci.SDI_SOURCES["OPERATOR_ENTERED"]({}, bad)
    assert "OPERATOR_ENTERED" in _C().spec("C4")["options"]                         # D-12 (c)'s counterpart


@pytest.mark.parametrize("raw,delta,base,scope,strict,expected", [
    ("1500", "1500", "9000", "net", False, True),           # a bare number: MXN, D-24 counts ">="
    ("1500", "1500", "9000", "net", True, False),           # D-25 counts ">"
    ("PERCENT:10", "899", "9000", "net", False, False),
    ("PERCENT:10", "900", "9000", "net", False, True),
    ("PERCENT:10", "1", "0", "net", False, True),           # against a zero base: over any percentage
    ("AMOUNT:5000;PERCENT:10", "1000", "9000", "net", False, True),     # either one
    ("AMOUNT:1;NET=AMOUNT:5000", "100", "9000", "net", False, False),  # the line's own rule replaces the default
    ("AMOUNT:1;NET=AMOUNT:5000", "100", "9000", "employer_total", False, True),
    ("NET=AMOUNT:5", "100", "9000", "employer_total", False, None),    # no rule covers it
])
def test_d24_d25_threshold_rules(db, raw, delta, base, scope, strict, expected):
    rules = _C().threshold("D-24", raw)
    assert _C().exceeds(rules, D(delta), D(base), scope, strict) is expected


@pytest.mark.parametrize("bad", ["", "PERCENT:", "RATIO:3", "-1", "AMOUNT:x", "NET=PERCENT:-2"])
def test_d24_d25_threshold_grammar_refuses(db, bad):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException):
        _C().parse("D-25", bad)


def test_c12_sindicalizado(db):
    from app.modules.payroll import mexico_cfdi_input as ci
    from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

    prof = SimpleNamespace(mx_union_member=True)
    assert run_with(db, lambda: ci.sindicalizado(prof)) is None                    # unanswered / OMIT
    answer(db, "C12", "FROM_PROFILE")
    assert run_with(db, lambda: ci.sindicalizado(prof)) == "Sí"
    assert run_with(db, lambda: ci.sindicalizado(SimpleNamespace(mx_union_member=False))) == "No"
    with pytest.raises(MXBlock):
        run_with(db, lambda: ci.sindicalizado(SimpleNamespace(mx_union_member=None)))


# ── governance decisions ─────────────────────────────────────────────────

def test_d26_general_availability_needs_a_second_super_admin_once_answered(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_service

    answer(db, "D-26", "FOUR_EYES")
    with pytest.raises(BadRequestException, match="MX_FOUR_EYES_PROPOSED"):
        mexico_service.transition_mx_service_registry(db, "AVAILABLE", "SYNTHETIC", SA_A.id)
    with pytest.raises(BadRequestException, match="MX_FOUR_EYES_REQUIRED"):
        mexico_service.transition_mx_service_registry(db, "AVAILABLE", "SYNTHETIC", SA_A.id)
    with pytest.raises(BadRequestException) as e:                                  # confirmed: reaches the GA gate
        mexico_service.transition_mx_service_registry(db, "AVAILABLE", "SYNTHETIC", SA_B_ID)
    assert "FOUR_EYES" not in str(e.value)


def test_d27_archiving_an_active_classification(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_service
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    from tests.test_mexico_classifications import _data

    made = mexico_service.create_classification(db, _data(), SA_A.id)
    row = db.get(C, made["id"])
    row.status = "ACTIVE"            # SYNTHETIC state: approval needs a VERIFIED SAT catalog (not saved yet)
    db.commit()
    answer(db, "D-27", "FOUR_EYES")
    with pytest.raises(BadRequestException, match="MX_FOUR_EYES_PROPOSED"):
        mexico_service.archive_classification(db, row.id, SA_A.id, "SYNTHETIC")
    assert mexico_service.archive_classification(db, row.id, SA_B_ID, "SYNTHETIC")["status"] == "ARCHIVED"


def test_d28_per_item_second_org_admin(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_two_person

    parts = {p: "SINGLE" for p in ("EMPLOYER_VERSION", "ESTABLISHMENT", "IMSS_REGISTRATION", "INFONAVIT_MODEL",
                                   "LABOR_POLICY_ACTIVATION", "CREDENTIAL")}
    parts["INFONAVIT_MODEL"] = "FOUR_EYES"
    answer(db, "D-28", ";".join(f"{k}={v}" for k, v in parts.items()))
    assert mexico_two_person.mode(db, "D-28", "CREDENTIAL") == "SINGLE"
    kw = dict(decision="D-28", part="INFONAVIT_MODEL", action="set_infonavit_model", entity_type="mx_x", entity_id=5,
              payload={"model": "A"}, second="a second org admin")
    with pytest.raises(BadRequestException, match="MX_FOUR_EYES_PROPOSED"):
        mexico_two_person.require(db, actor_id=1, **kw)
    with pytest.raises(BadRequestException, match="MX_FOUR_EYES_PROPOSED"):          # a different change: its own
        mexico_two_person.require(db, actor_id=2, **{**kw, "payload": {"model": "B"}})
    mexico_two_person.require(db, actor_id=2, **kw)                                  # same change, other admin: runs
    db.commit()
    with pytest.raises(BadRequestException, match="MX_FOUR_EYES_PROPOSED"):          # the proposal was used once
        mexico_two_person.require(db, actor_id=3, **kw)


def test_d28_four_eyes_only_once_the_organisation_is_live(db):
    from datetime import date

    from app.core.exceptions import BadRequestException
    from app.modules.organizations.models import Organization
    from app.modules.payroll import mexico_two_person
    from app.modules.payroll.models import PayrollRun

    org = Organization(organization_name="SYNTHETIC", organization_code="MXS1LIVE", workspace_type="EVALUATION")
    db.add(org)
    db.flush()
    run = PayrollRun(organization_id=org.id, period_label="SYNTHETIC", period_start=date(2026, 6, 1),
                     period_end=date(2026, 6, 15), pay_date=date(2026, 6, 15), status="Review")
    db.add(run)
    db.commit()
    parts = {p: "SINGLE" for p in ("EMPLOYER_VERSION", "ESTABLISHMENT", "IMSS_REGISTRATION", "INFONAVIT_MODEL",
                                   "LABOR_POLICY_ACTIVATION", "CREDENTIAL")}
    parts["CREDENTIAL"] = "FOUR_EYES_WHEN_LIVE"
    answer(db, "D-28", ";".join(f"{k}={v}" for k, v in parts.items()))
    kw = dict(decision="D-28", part="CREDENTIAL", action="create_credential", entity_type="mx_y", entity_id=9,
              payload={"kind": "CSD"}, second="a second org admin", organization_id=org.id)
    assert not mexico_two_person.organization_is_live(db, org.id)
    mexico_two_person.require(db, actor_id=1, **kw)                  # not live (a run only in Review): runs alone
    run.status = "Approved"
    db.commit()
    assert mexico_two_person.organization_is_live(db, org.id)
    with pytest.raises(BadRequestException, match="MX_FOUR_EYES_PROPOSED"):          # live: a second admin
        mexico_two_person.require(db, actor_id=1, **kw)
    with pytest.raises(BadRequestException, match="MX_FOUR_EYES_REQUIRED"):
        mexico_two_person.require(db, actor_id=1, **kw)
    mexico_two_person.require(db, actor_id=2, **kw)


def test_a_payslip_records_the_answers_it_was_calculated_with(db, monkeypatch):
    from app.modules.payroll import mexico_run_service, mexico_service
    from tests import _mx_authority_helpers as ah

    w = ah.committed_world(db, monkeypatch, code="MXS1REC")
    before = mexico_service.calc_inputs(db, w.run, w.employee)        # the hook: applies the answers
    answer(db, "D-07", "UMA")
    after = mexico_service.calc_inputs(db, w.run, w.employee)
    assert "decisions" not in before["mx_input_components"] and after["mx_decisions"]["D-07"]["value"] == "UMA"
    assert mexico_run_service.input_hash(before["mx_input_components"]) != \
        mexico_run_service.input_hash(after["mx_input_components"])
    snap = mexico_run_service.payslip_snapshot({}, after)
    assert snap["decisions"] == {"D-07": {"version": 1, "value": "UMA"}}
