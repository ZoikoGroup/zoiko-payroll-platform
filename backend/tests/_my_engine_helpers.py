"""Malaysia engine test helpers (ZP-MY-ENG-001 Phase 3).

build_pack() turns malaysia_content.py into a SIGNED in-memory pack (labels
without the [PENDING G1] marker). Where the specification gives no value, the
TEST_TEXT / TEST_AMOUNTS below stand in, and the contribution schedules are
TEST rows — every one of them clearly labelled "TEST — not certifying". They
exist only to exercise the engine; real rows come from the official documents
(EPF Third Schedule, PERKESO / EIS schedules) and are signed at gate G1.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import malaysia_content as content

PAY_DATE = date(2026, 3, 31)
START, END = date(2026, 3, 1), date(2026, 3, 31)
TEST_TEXT = {
    "my_rounding_pcb": "SEN_HALF_UP", "my_rounding_epf_direct": "RINGGIT_UP", "my_rounding_socso": "SEN_HALF_UP",
    "my_rounding_eis": "SEN_HALF_UP", "my_rounding_hrd": "SEN_HALF_UP",
    "my_epf_direct_calc_rule": "NON_MALAYSIAN_PART_F_ONLY", "my_epf_age_transition_rule": "AGE_AT_WAGE_MONTH_START",
    "my_eis_age_rule": "AGE_AT_WAGE_MONTH_START", "my_hrd_non_malaysian_rule": "LEVY_ON_ALL_COVERED_WAGES",
}
LABEL = "TEST — not certifying"

# (rule, class, lo, hi, employee, employer, effective_from, effective_to)
TEST_SCHEDULES = (
    ("MY_EPF_SCHEDULE", "MY_PR_BELOW_60", "0", "4900", "0", "0", None, None),
    ("MY_EPF_SCHEDULE", "MY_PR_BELOW_60", "4900", "5000", "550", "650", None, None),
    ("MY_EPF_SCHEDULE", "MY_PR_BELOW_60", "5000", "20000", "770", "840", None, None),
    ("MY_EPF_SCHEDULE", "MY_60_PLUS", "0", "20000", "0", "200", None, None),
    ("MY_SOCSO_SCHEDULE", "EI_AND_INVALIDITY", "0", "4900", "0", "0", None, None),
    ("MY_SOCSO_SCHEDULE", "EI_AND_INVALIDITY", "4900", "5000", "24.75", "86.65", None, None),
    ("MY_SOCSO_SCHEDULE", "EI_AND_INVALIDITY", "5000", "6000", "29.75", "104.15", None, None),
    ("MY_SOCSO_SCHEDULE", "EI_ONLY", "0", "6000", "0", "74.37", None, None),
    ("MY_EIS_SCHEDULE", "COVERED", "0", "4900", "0", "0", None, None),
    ("MY_EIS_SCHEDULE", "COVERED", "4900", "5000", "9.90", "9.90", None, None),
    ("MY_EIS_SCHEDULE", "COVERED", "5000", "6000", "11.90", "11.90", None, None),
    ("MY_FW_SOCSO_SCHEDULE", "FOREIGN_WORKER", "0", "6000", "0", "62.50", None, date(2026, 5, 31)),
    ("MY_FW_SOCSO_SCHEDULE", "FOREIGN_WORKER", "0", "6000", "37.50", "62.50", date(2026, 6, 1), None),
)


def _rate(row, territory, overrides):
    key, label, ee, er, flat, text = row[:6]
    eff_from, eff_to = row[8], row[9]
    if key in TEST_TEXT:
        text = TEST_TEXT[key]
    values = {"employee_rate_pct": ee, "employer_rate_pct": er, "flat_amount": flat, "text_value": text}
    values.update(overrides.get(key, {}))
    return {"id": key, "component_key": key, "label": label, "jurisdiction_state": territory,
            "effective_from": eff_from, "effective_to": eff_to,
            **{k: (Decimal(str(v)) if v is not None and k != "text_value" else v) for k, v in values.items()}}


def build_pack(overrides=None, schedules=TEST_SCHEDULES, unsigned=(), treatments=None):
    """(rate_map, slabs): every row signed except keys in `unsigned`."""
    overrides = overrides or {}
    rate_map = {}
    for row in content.MALAYSIA_SCALAR_CONTENT:
        rate = _rate(row, row[11], overrides)
        if rate["component_key"] in unsigned:
            rate["label"] += " [PENDING G1]"
        rate_map[rate["component_key"]] = rate
    slabs, n = [], 0
    for (rule, cls, lo, hi, ee, er, eff_from, eff_to) in schedules:
        for side, amount in (("EMPLOYEE", ee), ("EMPLOYER", er)):
            n += 1
            slabs.append({"id": n, "rule_type": rule, "filing_status": cls, "tax_regime": side,
                          "min_amount": Decimal(lo), "max_amount": Decimal(hi) if hi is not None else None,
                          "flat_amount": Decimal(amount), "rate_label": f"{rule} {cls} {side} {LABEL}",
                          "effective_from": eff_from, "effective_to": eff_to, "sort_order": n})
    for (obligation, treatment, component, label, _src) in content.MALAYSIA_EARNING_CLASSES:
        n += 1
        treatment = (treatments or {}).get((obligation, component), treatment)
        slabs.append({"id": n, "rule_type": content.MY_EARNING_CLASS_RULE, "filing_status": component,
                      "tax_regime": obligation, "assessment_basis": treatment, "rate_label": label,
                      "min_amount": Decimal("0"), "sort_order": n})
    return rate_map, slabs


def profile(**overrides):
    values = dict(contract_type="CONTRACT_OF_SERVICE", pay_frequency="MONTHLY", citizenship="CITIZEN",
                  date_of_birth=date(1990, 1, 1), tax_residence="RESIDENT", work_pass_type=None,
                  work_pass_valid_to=None, epf_member_class="MY_PR_BELOW_60", socso_category="EI_AND_INVALIDITY",
                  eis_state="COVERED", manual_worker=False, normal_hours_week=Decimal("45"), status="ACTIVE",
                  effective_from=date(2026, 1, 1), effective_to=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def foreign_profile(**overrides):
    values = dict(citizenship="NON_CITIZEN", work_pass_type="EMPLOYMENT_PASS", epf_member_class="NONMY_POST_1998",
                  socso_category="FOREIGN_WORKER", eis_state="FOREIGN_EXCLUDED", tax_residence="NON_RESIDENT")
    values.update(overrides)
    return profile(**values)


def registration(**overrides):
    values = dict(hrd_category="COMPULSORY", hrd_category_from=date(2025, 1, 1), verification_state="VERIFIED",
                  status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def assignment(territory="PENINSULAR_LABUAN", state="SGR"):
    return SimpleNamespace(labour_territory=territory, holiday_state=state, status="ACTIVE",
                           effective_from=date(2026, 1, 1), effective_to=None)


def ctx(gross="5000", components=None, pack=None, pay_date=PAY_DATE, start=START, end=END, profile_=None,
        registration_=None, assignment_=None, declarations=(), **extra):
    rate_map, slabs = pack or build_pack()
    gross = Decimal(str(gross))
    values = dict(gross=gross, basic=gross, country="MY", rate_map=rate_map, slabs=slabs, pay_date=pay_date,
                  my_pay_date=pay_date, period_start=start, period_end=end,
                  my_profile=profile_ or profile(), my_registration=registration_ or registration(),
                  my_assignment=assignment_ if assignment_ is not None else assignment(),
                  my_components=components if components is not None else {"BASIC_SALARY": gross},
                  my_declarations=list(declarations), my_ytd={}, my_organization_id=1, my_employee_id=1)
    values.update(extra)
    return PayrollContext(**values)
