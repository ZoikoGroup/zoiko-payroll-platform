"""Synthetic Japan Phase 3 engine tests (ZP-JP-ENG-001).

Every value here is invented for the test. None is a statutory figure.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import japan, japan_content as content
from app.modules.payroll.engine.countries.shared import (
    MissingComplianceConfigurationError,
)
from app.modules.payroll.engine.jurisdictions.japan import (
    employment_insurance,
    resident_tax,
    social_insurance,
    withholding,
)
from app.modules.payroll.engine.standard import StandardStrategy


def D(value):
    return Decimal(str(value))


def _rate(**kw):
    base = dict(component_key=kw.pop("key", ""), employee_rate_pct=None,
                employer_rate_pct=None, flat_amount=None, text_value=None,
                jurisdiction_state=None, effective_from=None, effective_to=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _base_rate_map():
    rate_map = {}
    for (key, _label, ee, er, flat, text, _src, _pending, eff_from, eff_to) in content.JP_SCALAR_CONTENT:
        rate_map[key] = _rate(key=key, employee_rate_pct=None if ee is None else D(ee),
                              employer_rate_pct=None if er is None else D(er),
                              flat_amount=None if flat is None else D(flat),
                              text_value=text, effective_from=eff_from, effective_to=eff_to)
    # Synthetic signed choices for the test.
    for key in ("jp_wht_rounding", "jp_si_employee_share_rounding",
                "jp_ei_employee_share_rounding", "jp_care_split_rule"):
        rate_map[key].text_value = "DOWN" if key.endswith("rounding") else "EQUAL"
    rate_map["jp_withholding_method"].text_value = "TABLES_ONLY"
    return rate_map


def _earning_classes(review_si=False):
    rows = []
    for obligation, treatment, component, label, src in content.JP_EARNING_CLASSES:
        if review_si and obligation == "SI" and component == "SALARY":
            treatment = "REVIEW"
        rows.append(SimpleNamespace(
            rule_type=content.JP_EARNING_CLASS_RULE, tax_regime=obligation,
            filing_status=component, assessment_basis=treatment, min_amount=D(0),
            max_amount=None, rate_pct=D(0), flat_amount=None,
        ))
    return rows


def _slabs(**overrides):
    rows = _earning_classes(overrides.get("review_si", False))
    rows.append(SimpleNamespace(
        rule_type=content.JP_WHT_MONTHLY_RULE, tax_column="PRIMARY",
        tax_table_number="0", min_amount=D(0), max_amount=D("100000000"),
        rate_pct=D(0), flat_amount=D(5000), tax_regime=None, filing_status=None,
    ))
    rows.append(SimpleNamespace(
        rule_type=content.JP_WHT_MONTHLY_RULE, tax_column="SECONDARY",
        tax_table_number="0", min_amount=D(0), max_amount=D("100000000"),
        rate_pct=D(0), flat_amount=D(7000), tax_regime=None, filing_status=None,
    ))
    rows.append(SimpleNamespace(
        rule_type=content.JP_HEALTH_RATE_RULE, tax_regime="KYOKAI_KENPO",
        jurisdiction_state="13", min_amount=D(0), max_amount=None,
        rate_pct=D("10"), flat_amount=None, filing_status=None,
        effective_from=None, effective_to=None,
    ))
    if overrides.get("with_ei_pair") is False:
        pass
    return rows


def _context(**overrides):
    rate_map = overrides.pop("rate_map", None) or _base_rate_map()
    slabs = overrides.pop("slabs", None)
    if slabs is None:
        slabs = _slabs()
    enrollment = SimpleNamespace(
        status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None,
        health_eligible=True, pension_eligible=True, smr_health_amount=D(300000), smr_pension_amount=D(300000),
        smr_health_grade=20, smr_pension_grade=20, care_state="NOT_COVERED",
        child_support_state="EXEMPT", health_insurer_code=None,
    )
    registration = SimpleNamespace(
        status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None,
        health_insurer_type="KYOKAI_KENPO", health_insurer_prefecture="13",
        health_insurer_code=None, ei_industry_class="GENERAL",
    )
    profile = SimpleNamespace(
        status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None,
        residency_status="RESIDENT", declaration_class="PRIMARY", dependants_count=0,
    )
    ei_profile = SimpleNamespace(
        status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None,
        insured=True, industry_class="GENERAL",
    )
    assessments = [SimpleNamespace(
        status="APPROVED", notice_id="NOTICE-1", municipality_code="131016",
        fiscal_notice_year=2026, version=1, first_deduction_month=date(2026, 6, 1),
        monthly_amounts={"2026-06": "10000", "2026-07": "10000"},
    )]
    ctx_kwargs = dict(
        gross=D(300000), basic=D(300000), overtime=D(0), country="JP",
        pay_frequency="MONTHLY", pay_date=date(2026, 6, 15), calendar_days=30,
        rate_map=rate_map, slabs=slabs,
        jp_organization_id=7, jp_employee_id=8, jp_date_of_birth=date(1990, 1, 1),
        jp_employer_registration=registration,
        jp_worker_tax_profile=profile,
        jp_social_insurance_enrollment=enrollment,
        jp_employment_insurance_profile=ei_profile,
        jp_resident_tax_assessments=assessments,
        jp_components={},
    )
    ctx_kwargs.update(overrides)
    return PayrollContext(**ctx_kwargs)


def test_full_monthly_salary_pipeline_and_trace():
    result = japan.calculate(_context())
    jp = result["jp_result"]

    assert result["tds"] == D(5000)
    assert jp["jp_wht_base"] == "256050"
    assert jp["jp_epi_employee"] == "27450"
    assert jp["jp_health_employee"] == "15000"
    assert jp["jp_si_employee_total"] == "42450"
    assert jp["jp_ei_employee"] == "1500"
    assert jp["jp_resident_tax"] == "10000"
    assert jp["jp_employee_total"] == "53950"
    assert jp["trace"]["jurisdiction"] == "JP"
    assert jp["trace"]["tablePackId"] == content.JP_2026[0]
    assert jp["trace"]["withholding"]["branch"] == "TABLE"
    assert jp["trace"]["residentTax"]["noticeId"] == "NOTICE-1"
    assert all("MyNumber" not in key for key in jp)
    assert all("name" not in key.lower() for key in jp)


def test_result_is_deterministic_and_json_serialisable():
    import json

    ctx = _context()
    first = japan.calculate(ctx)
    second = japan.calculate(ctx)
    assert first == second
    json.dumps(first["jp_result"], sort_keys=True)


def test_negative_net_pay_blocks():
    ctx = _context(gross=D(50000), basic=D(50000))
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "JP_NEGATIVE_NET"


def test_standard_result_wires_jp_result_and_employee_total():
    result = StandardStrategy().calculate(_context())
    assert result.tds == D(5000)
    assert result.jp_result["jp_employee_total"] == "53950"
    assert result.total_deductions == D(58950)
    assert result.net_pay == D(241050)


def test_secondary_declaration_uses_the_table_column():
    ctx = _context(jp_worker_tax_profile=SimpleNamespace(
        status="ACTIVE", effective_from=date(2026, 1, 1), residency_status="RESIDENT",
        declaration_class="SECONDARY", dependants_count=0))
    result = japan.calculate(ctx)
    assert result["tds"] == D(7000)
    assert result["jp_result"]["jp_wht_branch"] == "TABLE"


@pytest.mark.parametrize("status,key", [
    ("DRAFT", "jp_worker_tax_profile"),
    ("SUPERSEDED", "jp_worker_tax_profile"),
])
def test_inactive_tax_profile_blocks(status, key):
    ctx = _context(jp_worker_tax_profile=SimpleNamespace(
        status=status, effective_from=date(2026, 1, 1), residency_status="RESIDENT",
        declaration_class="PRIMARY", dependants_count=0))
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == key


def test_non_resident_blocks():
    ctx = _context(jp_worker_tax_profile=SimpleNamespace(
        status="ACTIVE", effective_from=date(2026, 1, 1), residency_status="NON_RESIDENT",
        declaration_class="PRIMARY", dependants_count=0))
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "JP_NON_RESIDENT_UNSUPPORTED"


def test_bonus_blocks_on_the_p4_path():
    ctx = _context(gross=D(300000), jp_components={"BONUS": D(10000)})
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "JP_BONUS_PATH_PENDING_P4"


def test_review_component_blocks():
    ctx = _context(slabs=_slabs(review_si=True))
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "jp_earning_class:SI:SALARY"


def test_missing_resident_tax_notice_blocks():
    ctx = _context(jp_resident_tax_assessments=[])
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "JP_RESIDENT_TAX_NOTICE_MISSING"


def test_ambiguous_resident_tax_notices_block():
    one = SimpleNamespace(status="APPROVED", notice_id="A", municipality_code="131016",
                          fiscal_notice_year=2026, version=1,
                          first_deduction_month=date(2026, 6, 1),
                          monthly_amounts={"2026-06": "10000"})
    two = SimpleNamespace(status="APPROVED", notice_id="B", municipality_code="131016",
                          fiscal_notice_year=2026, version=2,
                          first_deduction_month=date(2026, 6, 1),
                          monthly_amounts={"2026-06": "10000"})
    ctx = _context(jp_resident_tax_assessments=[one, two])
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "JP_RESIDENT_TAX_NOTICE_AMBIGUOUS"


def test_care_insurance_charges_between_40_and_64_and_not_at_65():
    young = _context(jp_date_of_birth=date(1980, 1, 1),
                     jp_social_insurance_enrollment=SimpleNamespace(
                         status="ACTIVE", effective_from=date(2026, 1, 1),
                         health_eligible=True, pension_eligible=True, smr_health_amount=D(300000), smr_pension_amount=D(300000),
                         care_state="COVERED", child_support_state="EXEMPT"))
    result = japan.calculate(young)
    assert result["jp_result"]["jp_care_employee"] == "2430"

    old = _context(jp_date_of_birth=date(1960, 1, 1),
                   jp_social_insurance_enrollment=SimpleNamespace(
                       status="ACTIVE", effective_from=date(2026, 1, 1),
                       health_eligible=True, pension_eligible=True, smr_health_amount=D(300000), smr_pension_amount=D(300000),
                       care_state="COVERED", child_support_state="EXEMPT"))
    old_result = japan.calculate(old)
    assert old_result["jp_result"]["jp_care_employee"] == "0"


def test_child_support_starts_in_april():
    march_rates = _base_rate_map()
    march_rates["jp_ei_general"].effective_from = date(2026, 1, 1)
    march = _context(pay_date=date(2026, 3, 15), rate_map=march_rates,
                     jp_resident_tax_assessments=[SimpleNamespace(
                         status="APPROVED", notice_id="N", municipality_code="131016",
                         fiscal_notice_year=2026, version=1,
                         first_deduction_month=date(2026, 3, 1),
                         monthly_amounts={"2026-03": "10000"})],
                     jp_social_insurance_enrollment=SimpleNamespace(
                         status="ACTIVE", effective_from=date(2026, 1, 1),
                         health_eligible=True, pension_eligible=True, smr_health_amount=D(300000), smr_pension_amount=D(300000),
                         care_state="NOT_COVERED", child_support_state="COVERED"))
    assert japan.calculate(march)["jp_result"]["jp_child_support_employee"] == "0"

    april = _context(pay_date=date(2026, 4, 15),
                     jp_resident_tax_assessments=[SimpleNamespace(
                         status="APPROVED", notice_id="N", municipality_code="131016",
                         fiscal_notice_year=2026, version=1,
                         first_deduction_month=date(2026, 4, 1),
                         monthly_amounts={"2026-04": "10000"})],
                     jp_social_insurance_enrollment=SimpleNamespace(
                         status="ACTIVE", effective_from=date(2026, 1, 1),
                         health_eligible=True, pension_eligible=True, smr_health_amount=D(300000), smr_pension_amount=D(300000),
                         care_state="NOT_COVERED", child_support_state="COVERED"))
    assert japan.calculate(april)["jp_result"]["jp_child_support_employee"] == "345"


def test_pending_rounding_blocks():
    rate_map = _base_rate_map()
    rate_map["jp_si_employee_share_rounding"].text_value = "PENDING_G1"
    ctx = _context(rate_map=rate_map)
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "jp_si_employee_share_rounding"


def test_missing_ei_pair_blocks():
    ctx = _context(jp_employment_insurance_profile=SimpleNamespace(
        status="ACTIVE", effective_from=date(2026, 1, 1), insured=True,
        industry_class="AGRICULTURE_SAKE"))
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "jp_ei_agriculture_sake"


def test_employment_insurance_insufficient_blocks_pair():
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        employment_insurance.monthly_employment_insurance(
            SimpleNamespace(insured=True, industry_class="CONSTRUCTION"), D(100000),
            _base_rate_map(), as_of=date(2026, 6, 15))
    assert exc.value.key == "jp_ei_construction"


def test_resident_tax_never_estimates():
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        resident_tax.resident_tax_for_month([], date(2026, 6, 15))
    assert exc.value.key == "JP_RESIDENT_TAX_NOTICE_MISSING"


def test_withholding_table_and_computer_are_distinct():
    slabs = [SimpleNamespace(
        rule_type=content.JP_WHT_MONTHLY_RULE, tax_column="PRIMARY",
        tax_table_number="0", min_amount=D(0), max_amount=D("1000000"),
        rate_pct=D(0), flat_amount=D(5000),
    )]
    table = withholding.monthly_withholding(
        D(200000), "PRIMARY", 0, "TABLES_ONLY", slabs, _base_rate_map())
    assert table.tax == D(5000)
    assert table.branch == "TABLE"

# ── review fixes (2026-10-30) ────────────────────────────────────────────────

def _enrollment(**kw):
    base = dict(status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None,
                health_eligible=True, pension_eligible=True,
                smr_health_amount=D(300000), smr_pension_amount=D(300000),
                smr_health_grade=None, smr_pension_grade=None, care_state="NOT_COVERED",
                child_support_state="EXEMPT", health_insurer_code=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_pension_uses_its_own_smr_above_the_pension_ceiling():
    # Synthetic: health SMR 1,000,000 while pension SMR is capped at 650,000.
    ctx = _context(gross=D(1200000), basic=D(1200000),
                   jp_social_insurance_enrollment=_enrollment(smr_health_amount=D(1000000),
                                                              smr_pension_amount=D(650000)))
    jp = japan.calculate(ctx)["jp_result"]
    assert (jp["jp_smr_health"], jp["jp_smr_pension"]) == ("1000000", "650000")
    assert D(jp["jp_epi_employee"]) == D(650000) * D("18.3") / 2 / 100       # pension on 650,000
    assert D(jp["jp_health_employee"]) == D(1000000) * D(10) / 2 / 100       # health on 1,000,000


def test_missing_pension_smr_blocks_instead_of_borrowing_the_health_smr():
    ctx = _context(jp_social_insurance_enrollment=_enrollment(smr_pension_amount=None))
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "jp_smr_pension"


def test_care_insurance_blocks_for_a_health_insurance_society():
    slabs = _slabs()
    slabs.append(SimpleNamespace(rule_type=content.JP_HEALTH_RATE_RULE, tax_regime="HEALTH_INSURANCE_SOCIETY",
                                 jurisdiction_state="S-001", min_amount=D(0), max_amount=None,
                                 rate_pct=D(9), flat_amount=None, filing_status=None,
                                 effective_from=None, effective_to=None))
    registration = SimpleNamespace(status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None,
                                   health_insurer_type="HEALTH_INSURANCE_SOCIETY", health_insurer_prefecture=None,
                                   health_insurer_code="S-001", ei_industry_class="GENERAL")
    ctx = _context(slabs=slabs, jp_employer_registration=registration, jp_date_of_birth=date(1976, 1, 1),
                   jp_social_insurance_enrollment=_enrollment(care_state="COVERED"))
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "jp_kyokai_care_total"


def test_missing_child_support_row_blocks():
    rate_map = _base_rate_map()
    del rate_map["jp_kyokai_child_support_total"]
    ctx = _context(rate_map=rate_map, pay_date=date(2026, 7, 15),
                   jp_social_insurance_enrollment=_enrollment(child_support_state="COVERED"))
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(ctx)
    assert exc.value.key == "jp_kyokai_child_support_total"


def test_not_applicable_resident_tax_withholds_nothing_without_a_notice():
    profile = SimpleNamespace(status="ACTIVE", effective_from=date(2026, 1, 1), effective_to=None,
                              residency_status="RESIDENT", declaration_class="PRIMARY", dependants_count=0,
                              resident_tax_collection="NOT_APPLICABLE")
    jp = japan.calculate(_context(jp_worker_tax_profile=profile, jp_resident_tax_assessments=[]))["jp_result"]
    assert D(jp["jp_resident_tax"]) == 0
    assert jp["trace"]["residentTax"]["status"] == "NOT_APPLICABLE"


def test_special_collection_without_a_notice_still_blocks():
    with pytest.raises(MissingComplianceConfigurationError) as exc:
        japan.calculate(_context(jp_resident_tax_assessments=[]))
    assert exc.value.key == "JP_RESIDENT_TAX_NOTICE_MISSING"


def test_change_notice_never_rewrites_earlier_months():
    original = SimpleNamespace(status="SUPERSEDED", notice_id="N-1", municipality_code="131016",
                               fiscal_notice_year=2026, version=1, first_deduction_month=date(2026, 6, 1),
                               monthly_amounts={"2026-06": "10000", "2026-07": "10000"})
    change = SimpleNamespace(status="APPROVED", notice_id="N-1", municipality_code="131016",
                             fiscal_notice_year=2026, version=2, first_deduction_month=date(2026, 7, 1),
                             monthly_amounts={"2026-07": "12000"})
    june = resident_tax.resident_tax_for_month([original, change], date(2026, 6, 15))
    july = resident_tax.resident_tax_for_month([original, change], date(2026, 7, 15))
    assert (june.amount, june.version) == (D(10000), 1)        # replaying June keeps the original
    assert (july.amount, july.version) == (D(12000), 2)


def test_rejected_and_imported_notices_never_govern():
    for status in ("IMPORTED", "REJECTED"):
        row = SimpleNamespace(status=status, notice_id="N-9", municipality_code="131016",
                              fiscal_notice_year=2026, version=1, first_deduction_month=date(2026, 6, 1),
                              monthly_amounts={"2026-06": "10000"})
        with pytest.raises(MissingComplianceConfigurationError):
            resident_tax.resident_tax_for_month([row], date(2026, 6, 15))

