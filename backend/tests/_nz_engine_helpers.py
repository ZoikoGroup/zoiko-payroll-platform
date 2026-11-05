"""Test helpers for the New Zealand P3 engine.

`build_pack()` turns new_zealand_content into an in-memory rate_map / slabs the
way seed_nz_pack writes them, then (unless pending=True) strips the
"[PENDING G1]" labels and fills every value the specification leaves open
with clearly labelled TEST fixtures. TEST values are fixtures only — they are
never copied into new_zealand_content.py and are not statutory content.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries import new_zealand_content as content

PENDING = " [PENDING G1]"
TEST_ROUNDING = "NEAREST_CENT_HALF_UP"
TEST_PRECEDENCE = "PAYE,ACC_LEVY,STUDENT_LOAN,KS_EMPLOYEE,CHILD_SUPPORT"
TEST_KS_MAX_AGE = "65"                              # TEST fixture
WINDOW_FROM, WINDOW_TO = content.NZ_2026_27[1], content.NZ_2026_27[2]

# Authority tables the specification does not reproduce — TEST rows only.
TEST_TABLES = {
    content.NZ_PAYE_METHOD_RULE: [dict(filing_status=f, flat_amount=n, tax_formula="ANNUALISE_BANDS")
                                  for f, n in (("WEEKLY", 52), ("FORTNIGHTLY", 26), ("FOUR_WEEKLY", 13),
                                               ("MONTHLY", 12))],
    content.NZ_SECONDARY_RATE_RULE: [dict(filing_status=c, rate_pct=r)
                                     for c, r in (("SB", "10.5"), ("S", "17.5"), ("SH", "30"), ("ST", "33"),
                                                  ("SA", "39"))],
    content.NZ_ND_RATE_RULE: [dict(rate_pct="45")],
    content.NZ_IETC_RULE: [dict(min_amount="0", max_amount="24000", flat_amount="0", rate_pct="0"),
                           dict(min_amount="24000", max_amount="44000", flat_amount="520", rate_pct="0"),
                           dict(min_amount="44000", max_amount="48000", flat_amount="520", rate_pct="13"),
                           dict(min_amount="48000", max_amount=None, flat_amount="0", rate_pct="0")],
    content.NZ_CS_VARIATION_RULE: [dict(filing_status="TESTV", tax_formula="INSUFFICIENT_NET",
                                        rate_label="TEST insufficient net pay")],
}


def _rate(row, pending):
    key, label, ee, er, flat, text, _src, _p, eff_from, eff_to = row
    return SimpleNamespace(component_key=key, label=label + (PENDING if pending else ""),
                           employee_rate_pct=ee, employer_rate_pct=er,
                           flat_amount=None if flat is None else Decimal(flat), text_value=text,
                           effective_from=eff_from or WINDOW_FROM, effective_to=eff_to or WINDOW_TO)


def _slab(pending, **kw):
    kw.setdefault("rate_label", "row")
    kw["rate_label"] += PENDING if pending else ""
    for key in ("min_amount", "max_amount", "rate_pct", "flat_amount"):
        if kw.get(key) is not None:
            kw[key] = Decimal(str(kw[key]))
    base = dict(id=None, rule_type=None, filing_status=None, tax_regime=None, assessment_basis=None,
                tax_column=None, tax_table_number=None, tax_formula=None, min_amount=Decimal("0"),
                max_amount=None, rate_pct=Decimal("0"), flat_amount=None, sort_order=0,
                effective_from=WINDOW_FROM, effective_to=WINDOW_TO)
    base.update(kw)
    return SimpleNamespace(**base)


def build_pack(overrides=None, drop_tables=(), pending=False, extra_slabs=()):
    """(rate_map, slabs). pending=True reproduces the shipped (unsigned) content
    without any TEST fill."""
    rate_map = {row[0]: _rate(row, pending) for row in content.NZ_SCALAR_CONTENT}
    if not pending:
        for key, kind in content.NZ_PARAMETER_KEYS.items():
            if key.endswith("_rounding"):
                rate_map[key].text_value = TEST_ROUNDING
        rate_map["nz_deduction_precedence"].text_value = TEST_PRECEDENCE
        rate_map["nz_ks_employer_max_age"].flat_amount = Decimal(TEST_KS_MAX_AGE)
    for key, value in (overrides or {}).items():
        if isinstance(value, str) and content.NZ_PARAMETER_KEYS.get(key) == "text":
            rate_map[key].text_value = value
        elif value is None:
            rate_map[key].flat_amount, rate_map[key].text_value = None, None
        else:
            rate_map[key].flat_amount = Decimal(str(value))

    slabs, ident = [], 0

    def add(**kw):
        nonlocal ident
        ident += 1
        slabs.append(_slab(pending, id=ident, **kw))

    for rule, bands in ((content.NZ_PAYE_BAND_RULE, content.NZ_PAYE_BANDS),
                        (content.NZ_ESCT_BAND_RULE, content.NZ_ESCT_BANDS)):
        for low, high, rate in bands:
            add(rule_type=rule, min_amount=low, max_amount=high, rate_pct=rate)
    for code, income_class, status, sl, ietc, label in content.NZ_TAX_CODES:
        add(rule_type=content.NZ_TAX_CODE_RULE, filing_status=code, tax_regime=income_class,
            assessment_basis=status, tax_column="SL" if sl else None, tax_table_number="IETC" if ietc else None,
            rate_label=label, effective_from=None, effective_to=None)
    for obligation, treatment, component, label, _src in content.NZ_EARNING_CLASSES:
        add(rule_type=content.NZ_EARNING_CLASS_RULE, filing_status=component, tax_regime=obligation,
            assessment_basis=treatment, rate_label=label, effective_from=None, effective_to=None)
    if not pending:
        for rule, rows in TEST_TABLES.items():
            if rule in drop_tables:
                continue
            for row in rows:
                add(rule_type=rule, rate_label=row.get("rate_label", "TEST"),
                    **{k: v for k, v in row.items() if k != "rate_label"})
    for kw in extra_slabs:
        add(**kw)
    return rate_map, slabs


def employer(**kw):
    row = dict(id=1, legal_entity_id=None, status="ACTIVE", effective_from=date(2026, 4, 1), effective_to=None,
               verification_state="VERIFIED")
    row.update(kw)
    return row


def tax_profile(**kw):
    row = dict(id=11, status="ACTIVE", effective_from=date(2026, 4, 1), effective_to=None, tax_code="M",
               tax_code_source="IR330_DECLARATION", ird_number_state="PENDING", residency_status="RESIDENT",
               tailored_rate_pct=None, tailored_valid_from=None, tailored_valid_to=None,
               sl_certificate_type=None, sl_certificate_ref=None, sl_certificate_rate_pct=None,
               sl_certificate_valid_from=None, sl_certificate_valid_to=None,
               min_wage_category="ADULT")
    row.update(kw)
    return row


def kiwisaver(**kw):
    row = dict(id=21, status="ACTIVE", effective_from=date(2026, 4, 1), effective_to=None,
               membership_state="CONTRIBUTING", employee_rate_pct=None, employer_rate_pct=None,
               reduction_ref=None, reduction_from=None, reduction_to=None, employer_matches_reduction=False,
               suspension_ref=None, suspension_from=None, suspension_to=None,
               esct_rate_pct=Decimal("30"), esct_basis="PRIOR_YEAR", esct_basis_amount=Decimal("80730"),
               esct_tax_year="2026-27", employer_contribution_treatment="ESCT",
               settlement_destination="INLAND_REVENUE", complying_fund_ref=None)
    row.update(kw)
    return row


def notice(**kw):
    row = dict(id=31, deduction_type="CHILD_SUPPORT", notice_id="CS-TEST-1", version=1, status="APPROVED",
               amount_per_payday=Decimal("900"), rate_pct=None, effective_from=date(2026, 4, 1),
               effective_to=None)
    row.update(kw)
    return row


def ctx(pack=None, **overrides):
    rate_map, slabs = pack or build_pack()
    values = dict(gross=Decimal("3000"), basic=Decimal("3000"), country="NZ", rate_map=rate_map, slabs=slabs,
                  pay_frequency="Fortnightly", pay_date=date(2026, 4, 8),
                  period_start=date(2026, 3, 26), period_end=date(2026, 4, 8),
                  nz_employer_profile=employer(), nz_tax_profile=tax_profile(), nz_kiwisaver=kiwisaver(),
                  nz_authority_deductions=[], nz_accumulators={"ACC_LIABLE_EARNINGS": Decimal("0")},
                  nz_hours=Decimal("80"), nz_hours_source="WORK_PATTERN",
                  nz_date_of_birth=date(1996, 5, 1), nz_organization_id=1)
    values.update(overrides)
    return PayrollContext(**values)


# ── Phase 6 TEST content (leave pay, extra pay, holiday advance) ─────────────
P6_TEST_VALUES = {
    "nz_hol_awe_lookback_months": 12, "nz_hol_awe_divisor_weeks": 52, "nz_hol_owp_fallback_weeks": 4,
    "nz_hol_adp_lookback_weeks": 52, "nz_hol_owp_method": "AGREEMENT_THEN_FALLBACK",
    "nz_hol_rdp_method": "AGREEMENT_DAILY", "nz_hol_adp_use_rule": "RDP_UNDETERMINABLE_OR_VARIES",
    "nz_hol_final_pay_unvested_method": "PCT_OF_GROSS_SINCE_ANNIVERSARY",
    "nz_out_of_cycle_paye_method": "EXTRA_PAY", "nz_lump_sum_paye_method": "EXTRA_PAY_FOUR_WEEK_ANNUALISE",
    "nz_correction_policy": "COMPENSATING_DELTA",
    # Phase 8 TEST values (filing deadline definition, payload schema version)
    "nz_working_day_rule": "WEEKDAYS_EXCL_PUBLIC_HOLIDAYS_AND_25DEC_15JAN", "nz_filing_payload_version": 1,
}
P6_TEST_SLABS = (
    dict(rule_type=content.NZ_LUMP_SUM_RULE, filing_status="ANNUALISATION_FACTOR", flat_amount="13",
         rate_label="TEST factor"),
    dict(rule_type=content.NZ_LUMP_SUM_RULE, filing_status="SL_ON_EXTRA_PAY", tax_formula="WHOLE",
         rate_label="TEST SL whole"),
    dict(rule_type=content.NZ_LUMP_SUM_RULE, filing_status="IETC_ON_EXTRA_PAY", tax_formula="NONE",
         rate_label="TEST no IETC on extra pay"),
    dict(rule_type=content.NZ_HOLIDAY_ADVANCE_RULE, filing_status="STANDARD", rate_label="TEST standard"),
    dict(rule_type=content.NZ_HOLIDAY_ADVANCE_RULE, filing_status="ALTERNATIVE", rate_label="TEST alternative"),
)


def build_p6_pack(overrides=None, holiday_pay="INCLUDED", extra_slabs=()):
    """The P3 TEST pack plus Phase 6 TEST rows. HOLIDAY_PAY earning classes are
    set to `holiday_pay` in this fixture ONLY (shipped content keeps REVIEW)."""
    values = dict(P6_TEST_VALUES)
    values.update(overrides or {})
    rate_map, slabs = build_pack(overrides=values, extra_slabs=tuple(P6_TEST_SLABS) + tuple(extra_slabs))
    for slab in slabs:
        if slab.rule_type == content.NZ_EARNING_CLASS_RULE and slab.filing_status == "HOLIDAY_PAY" \
                and slab.tax_regime in ("PAYE", "ACC", "KIWISAVER", "STUDENT_LOAN", "HOLIDAY_GROSS"):
            slab.assessment_basis = holiday_pay
        if slab.rule_type == content.NZ_EARNING_CLASS_RULE and slab.filing_status == "HOLIDAY_PAY"                 and slab.tax_regime == "MIN_WAGE":
            slab.assessment_basis = "EXCLUDED"                 # TEST: holiday pay is not pay for hours worked
    return rate_map, slabs


def ledger_rows(weeks=52, weekly="1300", end=date(2026, 9, 30), days=5):
    """Weekly gross-earnings ledger rows ending on `end` (SALARY, INCLUDED)."""
    from datetime import timedelta

    rows = []
    for k in range(weeks):
        period_end = end - timedelta(weeks=k)
        rows.append({"id": k + 1, "payDate": period_end, "periodStart": period_end - timedelta(days=6),
                     "periodEnd": period_end, "component": "SALARY", "amount": Decimal(weekly), "included": True,
                     "treatment": "INCLUDED", "daysWorked": Decimal(days)})
    return rows
