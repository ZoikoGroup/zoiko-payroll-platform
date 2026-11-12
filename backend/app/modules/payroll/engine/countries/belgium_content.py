"""
modules/payroll/engine/countries/belgium_content.py
----------------------------------------------------
Belgium (ZP-BE-ENG-001) statutory content CATALOGUE — keys and vocabularies
only. Pure data, no ORM import. Shared by:

  * belgium_service.seed_belgium_pack (scripts/seed_belgium_canonical_packs.py
    and the Super Admin "seed Draft" action) — writes one placeholder row per
    key into the BE-PAYROLL-2026 canonical pack (Draft);
  * engine/jurisdictions/belgium/pack.py (BePack) — the only reader of pack
    rows inside the engine;
  * be_super_admin.py — the governed signing console (vocabulary checks).

NO STATUTORY VALUE LIVES HERE OR ANYWHERE IN CODE (ZP-BE-ENG-001 §3, BE-010,
BE-039; plan rule 2). Every rate, threshold, band, rounding rule and date is a
signed, effective-dated pack row. Seeded rows carry NO value at all: every
value field is empty and the label carries "[PENDING G1]", so the engine
blocks (BE_CONTENT_PENDING) until a Belgian specialist signs the row at gate
G1. Where the specification states a figure, it is shown to the signer as
display text only — SPEC_PROPOSED below — and is written into the row LABEL as
"spec-proposed: ...", never into a value field. A value the specification does
not give is "none in spec" and stays empty until signed or NOT_SUPPORTED.

Value kinds and where a SIGNED value is stored:
  rate         ContributionRate employee_rate_pct / employer_rate_pct (percent)
  amount       ContributionRate flat_amount
  text-choice  ContributionRate text_value (one of the key's vocabulary)
  date         ContributionRate text_value (ISO date)
  band/formula ContributionRate text_value = SLAB_ROWS (or NOT_SUPPORTED) and
               the content itself as TaxSlab rows of rule_type RULE_TYPES[key]
  table        TaxSlab rows of rule_type RULE_TYPES[key] (one row per entry);
               the ContributionRate row is the signed "complete" marker
NOT_SUPPORTED is a signed decision for every key: the feature stays blocked
at calculation time (BE_FEATURE_BLOCKED).

ONSS employer keys are REFERENCE ONLY: the authoritative rate is resolved by
employer category and worker code (BE-015 / BE-019). No UI or API presents
one all-in employer rate.
"""

from __future__ import annotations

import re
from datetime import date

PACK_STATUS = "Draft"
SPEC = "ZP-BE-ENG-001 v1.0"
COUNTRY = "BE"
CURRENCY = "EUR"
# Pack window: calendar 2026. Rows carry their own effective dates (mid-year
# changes are row windows inside the pack, selected by pay date).
BE_2026 = ("BE-PAYROLL-2026", date(2026, 1, 1), date(2026, 12, 31))
TAX_YEAR = "2026"

PENDING_MARK = "[PENDING G1]"
NOT_SUPPORTED = "NOT_SUPPORTED"
SLAB_ROWS = "SLAB_ROWS"

# ── Evidence register (ZP-BE-ENG-001 §19, S1-S24, reviewed 22 Sep 2026) ────
# Registered as payroll_source_artifacts WITHOUT a checksum: a URL is not
# archived evidence. Archived copies + SHA-256 are attached at gate G1.
SOURCE_REFERENCES = (
    ("S1", "ONSS/RSZ", "2026/3 Social-security contributions",
     "https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/socialsecuritycontributions/contributions.html"),
    ("S2", "ONSS/RSZ", "Social Security TechLib (quarter-specific XML/XSD/rate files)",
     "https://www.socialsecurity.be/site_fr/employer/general/techlib.htm"),
    ("S3", "ONSS/RSZ", "Dimona general",
     "https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/obligations/obligations_nsso/dimona/general.html"),
    ("S4", "ONSS/RSZ", "Dimona declarations, modifications and cancellations",
     "https://www.socialsecurity.be/employer/instructions/dmfa/nl/latest/instructions/obligations/obligations_nsso/dimona/declarations_modifications_cancellations.html"),
    ("S5", "ONSS/RSZ", "DmfA application / deadlines",
     "https://www.socialsecurity.be/site_fr/employer/applics/dmfa/index.htm"),
    ("S6", "ONSS/RSZ", "DmfA general instructions",
     "https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/obligations/obligations_nsso/dmfa/general.html"),
    ("S7", "FPS Employment", "Remuneration (sector wage priority, RMMMG fallback)",
     "https://emploi.belgique.be/fr/themes/remuneration"),
    ("S8", "FPS Employment", "Minimum remuneration / RMMMG",
     "https://emploi.belgique.be/fr/themes/international/detachement/conditions-de-travail-respecter-en-cas-de-detachement-en-1"),
    ("S9", "FPS Employment", "Sector minimum wage database (by sub-committee)",
     "https://emploi.belgique.be/fr/themes/remuneration/salaires-minimums-par-sous-commission-paritaire"),
    ("S10", "FPS Employment", "Index centimes",
     "https://emploi.belgique.be/fr/themes/remuneration/indexation-automatique-des-salaires/index-centimes"),
    ("S11", "FPS Employment", "Wage norm",
     "https://emploi.belgique.be/fr/themes/remuneration/norme-salariale"),
    ("S12", "FPS Employment", "Working time and reduction",
     "https://emploi.belgique.be/fr/themes/reglementation-du-travail/duree-du-travail-et-temps-de-repos/duree-du-travail-et-diminution"),
    ("S13", "FPS Employment", "Annual holidays (minimum paid)",
     "https://employment.belgium.be/en/themes/international/posting/working-conditions-be-respected-case-posting-belgium/minimum-paid"),
    ("S14", "ONSS/RSZ", "Annual-holiday employer obligations",
     "https://www.socialsecurity.be/employer/instructions/dmfa/nl/latest/instructions/obligations/obligations_branches/anualholidays.html"),
    ("S15", "ONSS/RSZ", "Holiday pay remuneration treatment",
     "https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/salary/particularcases/holidaypay.html"),
    ("S16", "FPS Employment", "Sickness / guaranteed salary",
     "https://emploi.belgique.be/fr/themes/contrats-de-travail/suspension-du-contrat-de-travail/causes-de-suspension-propres-au"),
    ("S17", "FPS Employment", "Maternity leave",
     "https://emploi.belgique.be/fr/themes/jours-feries-et-conges/conge-de-maternite"),
    ("S18", "FPS Employment", "Birth leave",
     "https://employment.belgium.be/en/themes/international/posting/working-conditions-be-respected-case-posting-belgium/birth-leave"),
    ("S19", "FPS Employment", "Payslip (fiche de salaire)",
     "https://emploi.belgique.be/fr/themes/reglementation-du-travail/documents-sociaux/fiche-de-salaire"),
    ("S20", "Belgian Official Gazette", "Royal Decree 11 Dec 2025 - Annex III replacement",
     "https://refli.be/fr/lex/2025009487"),
    ("S21", "Belgian Official Gazette", "Royal Decree 24 Jul 2026 - withholding amendments",
     "https://refli.be/fr/lex/2026005690"),
    ("S22", "FPS Finance", "Belcotax 281.10/281.11 XML guidance",
     "https://finance.belgium.be/sites/default/files/downloads/161-belcotax-international-organisations-creation-fiches.pdf"),
    ("S23", "Belgian Data Protection Authority", "Salary data",
     "https://www.dataprotectionauthority.be/citoyen/themes/vie-privee-sur-le-lieu-du-travail/donnees-des-travailleurs/donnees-salariales-"),
    ("S24", "ONSS/RSZ", "2026 worker work-bonus instructions",
     "https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/deductions/workers_reductions/workbonus"),
)
SOURCE_CODES = tuple(code for code, *_ in SOURCE_REFERENCES)

# ── Vocabularies (no statutory values) ────────────────────────────────────
WORKER_CATEGORIES = ("MANUAL", "EMPLOYEE", "APPRENTICE", "STUDENT", "FLEXI", "OCCASIONAL", "OTHER")  # BE-002
PAY_FREQUENCIES = ("MONTHLY", "SEMI_MONTHLY", "FORTNIGHTLY", "WEEKLY")                               # BE-004, G-11
PAY_BASES = ("SALARIED", "HOURLY")                                                                   # BE-004
# Rounding rule vocabulary (unit + mode); WHICH rule applies is G-02 / G-19.
ROUNDING_RULES = ("CENT_HALF_UP", "CENT_DOWN", "EURO_HALF_UP", "EURO_DOWN")
TREATMENTS = ("INCLUDED", "EXCLUDED", "REVIEW")                                                      # BE-006
DECLARATION_TYPES = ("FAMILY_SITUATION", "DEPENDANTS", "NON_RESIDENT_STATUS", "WORK_BONUS_FISCAL_ELECTION")
# Must equal models._BE_ACCUMULATORS (tests/test_belgium_content.py).
ACCUMULATORS = ("WITHHOLDING_TAXABLE", "WITHHOLDING", "WITHHOLDING_EXCEPTIONAL_TAXABLE", "WITHHOLDING_EXCEPTIONAL",
                "ONSS_EMPLOYEE_BASE", "ONSS_EMPLOYEE", "ONSS_EMPLOYER_BASE", "ONSS_MANUAL_108_BASE",
                "WORK_BONUS_SOCIAL", "WORK_BONUS_FISCAL", "HOLIDAY_PAY_BASE")

# Earning classification (BE-006 / BE-007 / BE-008 / BE-009): one row per
# (obligation, component); treatment INCLUDED / EXCLUDED / REVIEW. Every row is
# seeded REVIEW + [PENDING G1]; a non-zero REVIEW component blocks.
COMPONENTS = ("SALARY", "HOURLY_PAY", "OVERTIME_PREMIUM", "SUNDAY_HOLIDAY_PREMIUM", "SECTOR_PREMIUM", "BONUS",
              "THIRTEENTH_MONTH", "HOLIDAY_PAY_SIMPLE", "HOLIDAY_PAY_DOUBLE", "DEPARTURE_HOLIDAY_PAY",
              "GUARANTEED_SALARY", "BIRTH_LEAVE_PAY", "BENEFIT_IN_KIND", "MEAL_VOUCHER_EMPLOYER", "ECOCHEQUE",
              "REIMBURSEMENT", "ARREARS", "PROFIT_SHARING")
# BE-007: one independent base per obligation (no universal "taxable gross").
OBLIGATIONS = ("ONSS_EMPLOYEE", "ONSS_EMPLOYER", "ONSS_MANUAL_108", "WITHHOLDING_REGULAR",
               "WITHHOLDING_EXCEPTIONAL", "HOLIDAY_BASE", "SECTOR_MIN_WAGE", "OVERTIME_BASE", "SICK_PAY_BASE",
               "TAX_FICHE_281_10")

# ── TaxSlab rule types (all <= 30 characters) ─────────────────────────────
EARNING_CLASS_RULE = "BE_EARNING_CLASS"
PUBLIC_HOLIDAY_RULE = "BE_PUBLIC_HOLIDAY"
AUTHORITY_EXAMPLE_RULE = "BE_AUTHORITY_EXAMPLE"

# ── Key catalogue ─────────────────────────────────────────────────────────
# key -> (group, kind, spec reference, short label)
KIND_RATE, KIND_AMOUNT, KIND_TEXT, KIND_BAND, KIND_FORMULA, KIND_DATE, KIND_TABLE = (
    "rate", "amount", "text-choice", "band", "formula", "date", "table")
KINDS = (KIND_RATE, KIND_AMOUNT, KIND_TEXT, KIND_BAND, KIND_FORMULA, KIND_DATE, KIND_TABLE)
SLAB_KINDS = (KIND_BAND, KIND_FORMULA, KIND_TABLE)
# Every onss_employer rate / band key is REFERENCE ONLY. The full statement is
# returned as `referenceNote` by every API view of those rows; the label (100
# characters, shared with the spec-proposed text) carries the short marker.
REFERENCE_NOTE = "reference only; resolved by employer category and worker code (BE-015/BE-019)"
REFERENCE_MARKER = "ref. only (BE-015/BE-019)"

KEYS = {
    # policy
    "be_supported_pay_frequencies": ("policy", KIND_TEXT, "BE-004, G-11", "Supported pay frequencies"),
    "be_supported_pay_bases": ("policy", KIND_TEXT, "BE-004", "Supported pay bases (salaried / hourly)"),
    "be_supported_worker_categories": ("policy", KIND_TEXT, "BE-002, D6, §1", "Supported worker categories"),
    "be_supported_contract_types": ("policy", KIND_TEXT, "BE-002, BE-004", "Supported contract types"),
    "be_rounding_onss": ("policy", KIND_TEXT, "D8, G-02, G-19", "ONSS rounding rule"),
    "be_rounding_withholding": ("policy", KIND_TEXT, "D8, G-02, G-19", "Professional withholding rounding rule"),
    "be_rounding_holiday": ("policy", KIND_TEXT, "D8, G-02, G-19", "Holiday pay rounding rule"),
    "be_bssc_pending": ("policy", KIND_TEXT, "G-06 / G-17 (no spec ID)",
                        "Special social security contribution (awaiting specialist)"),
    # withholding (§5)
    "be_wht_applicability_rule": ("withholding", KIND_TEXT, "§5 stage 1", "Withholding applicability"),
    "be_wht_nonresident_rule": ("withholding", KIND_TEXT, "§5 stage 1", "Non-resident withholding treatment"),
    "be_wht_taxable_basis_rule": ("withholding", KIND_TEXT, "§5 stage 2, BE-007", "Withholding taxable basis"),
    "be_wht_period_strategy": ("withholding", KIND_TEXT, "§5 stage 3", "Withholding period strategy"),
    "be_wht_annex3_regular_scale": ("withholding", KIND_BAND, "§5 stage 4, BE-010, S20",
                                    "Annex III regular withholding scale"),
    "be_wht_annex3_amendment_2026": ("withholding", KIND_FORMULA, "§5 stage 7, §3, S21",
                                     "Annex III amendments (RD 24 Jul 2026)"),
    "be_wht_family_reductions": ("withholding", KIND_BAND, "§5 stage 5", "Family / reduction layer"),
    "be_wht_fiscal_work_bonus": ("withholding", KIND_FORMULA, "§5 stage 7, BE-012", "Fiscal work bonus"),
    "be_wht_exceptional_rule": ("withholding", KIND_BAND, "§5 stage 6, BE-011",
                                "Exceptional remuneration withholding"),
    "be_wht_holiday_pay_rule": ("withholding", KIND_FORMULA, "§5 stage 6, BE-011", "Holiday pay withholding"),
    "be_wht_arrears_rule": ("withholding", KIND_FORMULA, "BE-009, BE-011", "Arrears withholding"),
    "be_wht_overtime_rule": ("withholding", KIND_FORMULA, "§5 stage 7", "Overtime withholding changes"),
    # onss_employee (§6)
    "be_onss_employee_rate": ("onss_employee", KIND_RATE, "§3, §6", "Employee ordinary ONSS contribution"),
    "be_onss_employee_base_rule": ("onss_employee", KIND_TEXT, "BE-007", "Employee ONSS base rule"),
    "be_onss_manual_base_uplift": ("onss_employee", KIND_RATE, "§3, BE-016, S1", "Manual-worker base uplift"),
    "be_onss_manual_base_categories": ("onss_employee", KIND_TEXT, "BE-016",
                                       "Categories on the manual-worker base"),
    # onss_employer (§6, BE-015) — reference only, resolved by employer and worker codes
    "be_onss_supported_employer_categories": ("onss_employer", KIND_TEXT, "BE-015, §2",
                                              "Supported ONSS employer categories"),
    "be_onss_supported_worker_codes": ("onss_employer", KIND_TEXT, "BE-015, §2", "Supported ONSS worker codes"),
    "be_onss_rate_file_quarter": ("onss_employer", KIND_DATE, "BE-015, S2", "ONSS rate file quarter"),
    "be_onss_employer_base_rate": ("onss_employer", KIND_BAND, "§3, §6, BE-015", "Employer base"),
    "be_onss_wage_moderation": ("onss_employer", KIND_RATE, "§6, G-05", "Wage moderation contribution"),
    "be_onss_special_160": ("onss_employer", KIND_RATE, "§6", "Special (workforce-size test)"),
    "be_onss_special_160_threshold_rule": ("onss_employer", KIND_TEXT, "§6, G-05",
                                           "Special contribution workforce test"),
    "be_onss_pension_special": ("onss_employer", KIND_RATE, "§6", "Occupational pension special"),
    "be_onss_company_car": ("onss_employer", KIND_FORMULA, "§6, G-15", "Company car contribution"),
    "be_onss_fund_contributions": ("onss_employer", KIND_BAND, "§6, G-05", "Fund contributions"),
    # reductions (§6)
    "be_red_social_work_bonus": ("reductions", KIND_BAND, "§6, BE-012, S24", "Social work bonus"),
    "be_red_structural": ("reductions", KIND_FORMULA, "§6", "Structural reduction"),
    "be_red_target_group": ("reductions", KIND_BAND, "§6", "Target-group reductions"),
    # holiday (§8)
    "be_hol_entitlement_weeks": ("holiday", KIND_AMOUNT, "§8, S13", "Holiday entitlement (weeks)"),
    "be_hol_wc_simple_rule": ("holiday", KIND_TEXT, "§8", "White-collar simple holiday pay"),
    "be_hol_wc_double_pct": ("holiday", KIND_RATE, "§8, S15", "White-collar double holiday pay"),
    "be_hol_wc_double_contribution_rule": ("holiday", KIND_TEXT, "§8, S15",
                                           "Double holiday pay contribution rule"),
    "be_hol_additional_rule": ("holiday", KIND_FORMULA, "BE-026", "Additional holidays"),
    "be_hol_departure_rule": ("holiday", KIND_FORMULA, "§8, BE-027", "Departure holiday pay"),
    "be_hol_manual_quarterly_contribution": ("holiday", KIND_RATE, "§3, §6, §8, S14",
                                             "Manual-worker holiday contribution (quarterly)"),
    "be_hol_manual_annual_debit": ("holiday", KIND_RATE, "§3, §8, S14",
                                   "Manual-worker holiday contribution (annual debit)"),
    # wages (§7)
    "be_wage_rmmmg": ("wages", KIND_AMOUNT, "§3, §7, S8", "RMMMG fallback (monthly)"),
    "be_wage_rmmmg_min_age": ("wages", KIND_AMOUNT, "§3", "RMMMG minimum age"),
    "be_wage_index_centime_threshold": ("wages", KIND_AMOUNT, "§3, §7, S10", "Index-centime reference threshold"),
    "be_wage_index_centime_rule": ("wages", KIND_FORMULA, "§7, G-10", "Index-centime limitation rule"),
    "be_wage_norm_margin": ("wages", KIND_RATE, "§3, §7, S11", "Wage-norm margin (warning only)"),
    # working_time (§7)
    "be_wt_daily_limit_hours": ("working_time", KIND_AMOUNT, "§7, S12", "Daily working-time limit (hours)"),
    "be_wt_weekly_limit_hours": ("working_time", KIND_AMOUNT, "§7, S12", "Weekly working-time limit (hours)"),
    "be_wt_weekly_reduced_hours": ("working_time", KIND_AMOUNT, "§7, S12", "Reduced weekly hours"),
    "be_ot_threshold_rule": ("working_time", KIND_TEXT, "BE-022", "Overtime threshold rule"),
    "be_ot_premium_weekday": ("working_time", KIND_RATE, "§7", "Overtime premium, weekday / Saturday"),
    "be_ot_premium_sunday_holiday": ("working_time", KIND_RATE, "§7", "Overtime premium, Sunday / public holiday"),
    "be_ot_compensatory_rest_rule": ("working_time", KIND_FORMULA, "§7", "Compensatory rest rule"),
    # absence (§9)
    "be_abs_wc_guaranteed_days": ("absence", KIND_AMOUNT, "§9, S16", "White-collar guaranteed salary days"),
    "be_abs_wc_guaranteed_pct": ("absence", KIND_RATE, "§9, S16", "White-collar guaranteed salary rate"),
    "be_abs_wc_min_contract_months": ("absence", KIND_AMOUNT, "§9, S16", "Guaranteed salary contract condition"),
    "be_abs_manual_day_bands": ("absence", KIND_BAND, "§9, G-07", "Manual-worker guaranteed salary day bands"),
    "be_abs_manual_insurance_cap": ("absence", KIND_AMOUNT, "§9, G-07", "Manual-worker insurance cap"),
    "be_abs_relapse_window_weeks": ("absence", KIND_AMOUNT, "§3, BE-030, S16", "Relapse window (weeks)"),
    "be_abs_maternity_weeks": ("absence", KIND_AMOUNT, "§9, S17", "Maternity leave (weeks)"),
    "be_abs_maternity_multiple_weeks": ("absence", KIND_BAND, "§9, S17",
                                        "Maternity, multiple birth (by children)"),
    "be_abs_birth_leave_days": ("absence", KIND_AMOUNT, "§9, S18", "Birth leave (days)"),
    "be_abs_birth_leave_window_months": ("absence", KIND_AMOUNT, "§9, S18", "Birth leave window (months)"),
    "be_abs_birth_leave_employer_days": ("absence", KIND_AMOUNT, "§9, S18", "Birth leave employer-paid days"),
    # holidays (BE-023, §8)
    "be_public_holidays": ("holidays", KIND_TABLE, "BE-023, §8, G-09", "Public holidays"),
    "be_public_holiday_substitution_rule": ("holidays", KIND_TEXT, "BE-023, G-09", "Public holiday substitution"),
    # earning classification (BE-006 / BE-008)
    "be_bik_valuation_rules": ("earning_class", KIND_FORMULA, "BE-008, G-15", "Benefit-in-kind valuation"),
    "be_meal_voucher_treatment": ("earning_class", KIND_TEXT, "BE-008, G-15", "Meal voucher treatment"),
    "be_ecocheque_treatment": ("earning_class", KIND_TEXT, "BE-008, G-15", "Ecocheque treatment"),
}
GROUPS = ("policy", "withholding", "onss_employee", "onss_employer", "reductions", "holiday", "wages",
          "working_time", "absence", "holidays", "earning_class")
CATEGORY_LABELS = {
    "policy": "Scope, Policy & Rounding", "withholding": "Professional Withholding (Annex III)",
    "onss_employee": "ONSS/RSZ Employee", "onss_employer": "ONSS/RSZ Employer (reference; by employer/worker code)",
    "reductions": "Reductions", "holiday": "Annual Holiday Pay", "wages": "Wages, RMMMG & Indexation",
    "working_time": "Working Time & Overtime", "absence": "Absence & Guaranteed Salary",
    "holidays": "Public Holidays", "earning_class": "Earning Classification",
}

# TaxSlab rule type carrying each band / formula / table key's content.
_RULE_TYPE_OVERRIDES = {"be_abs_maternity_multiple_weeks": "BE_ABS_MATERNITY_MULTIPLE",
                        "be_public_holidays": PUBLIC_HOLIDAY_RULE}
RULE_TYPES = {key: _RULE_TYPE_OVERRIDES.get(key, key.upper())
              for key, (_g, kind, _r, _l) in KEYS.items() if kind in SLAB_KINDS}

# Signed text vocabularies per text-choice key. NOT_SUPPORTED is always also
# accepted. A key not listed has NO vocabulary yet: only NOT_SUPPORTED can be
# signed until the specialist supplies one (same rule as Poland).
LIST_VOCABULARIES = {
    "be_supported_pay_frequencies": PAY_FREQUENCIES,
    "be_supported_pay_bases": PAY_BASES,
    "be_supported_worker_categories": WORKER_CATEGORIES,
}
CHOICE_VOCABULARIES = {
    "be_rounding_onss": ROUNDING_RULES,
    "be_rounding_withholding": ROUNDING_RULES,
    "be_rounding_holiday": ROUNDING_RULES,
}

# ── Display text only (NOT values) ────────────────────────────────────────
# What the specification itself states, shown to the G1 signer in the row
# LABEL as "spec-proposed: ...". Never written to a value field and never read
# by the engine. Keys absent here are "none in spec".
SPEC_PROPOSED = {
    "be_supported_worker_categories": "MANUAL,EMPLOYEE (special regimes blocked)",
    "be_onss_employee_rate": "13.07% ordinary",
    "be_onss_manual_base_uplift": "108% (gross + 8%)",
    "be_onss_manual_base_categories": "MANUAL + assimilated",
    "be_onss_employer_base_rate": "24.92% globalised base",
    "be_onss_special_160": "1.60%",
    "be_onss_pension_special": "8.86%",
    "be_hol_entitlement_weeks": "4 weeks max",
    "be_hol_wc_double_pct": "92% of monthly wage",
    "be_hol_manual_quarterly_contribution": "5.57% quarterly",
    "be_hol_manual_annual_debit": "10.27% annual debit",
    "be_wage_rmmmg": "EUR 2,233.61 from 1 Jul 2026",
    "be_wage_rmmmg_min_age": "18",
    "be_wage_index_centime_threshold": "EUR 4,000 from 1 Jun 2026",
    "be_wage_norm_margin": "0% (2025-2026)",
    "be_wt_daily_limit_hours": "8",
    "be_wt_weekly_limit_hours": "40",
    "be_wt_weekly_reduced_hours": "38",
    "be_ot_premium_weekday": "50%",
    "be_ot_premium_sunday_holiday": "100%",
    "be_abs_wc_guaranteed_days": "30 days",
    "be_abs_wc_guaranteed_pct": "100%",
    "be_abs_wc_min_contract_months": "indefinite or >= 3 months",
    "be_abs_relapse_window_weeks": "8 weeks (from 1 Jan 2026)",
    "be_abs_maternity_weeks": "15 weeks",
    "be_abs_maternity_multiple_weeks": "17-19 weeks (multiple birth)",
    "be_abs_birth_leave_days": "20 days",
    "be_abs_birth_leave_window_months": "4 months",
    "be_abs_birth_leave_employer_days": "3 days",
    "be_public_holidays": "ten statutory holidays; dates none in spec (G-09)",
}

# ── Owner decisions (shown OPEN until reviewed evidence BE-DECISION-<key>) ──
OWNER_DECISIONS = (
    ("G-01", "Consolidated calculation order (specialist confirmation)", True),
    ("G-02", "Rounding rules per obligation", True),
    ("G-06", "Special social security contribution (BSSC)", True),
    ("G-11", "Pay-frequency scope", True),
    ("G-12", "Definition of a high-risk change for four-eyes", True),
    ("G-13", "Legal language of employment documents", True),
    ("G-16", "Identifier formats and check digits (KBO/BCE, ONSS, NISS)", True),
    ("G-21", "Statutory retention periods (employee deletion stays blocked)", True),
)

# ── Joint Committee CBA packs (D3): payroll_collective_agreements ──────────
# agreement_code is the single source of truth for the committee:
#   BE-PC-<committee>[-<sub>]-<version>
# committee: digits with optional dotted sub-numbering (e.g. 200, 124.01);
# sub: one alphanumeric segment; version: digits with optional ".digits".
_AGREEMENT_CODE = re.compile(r"^BE-PC-(\d+(?:\.\d+)?)(?:-([A-Z0-9]+))?-(\d+(?:\.\d+)?)$")


def parse_be_agreement_code(code) -> tuple:
    """(committee, sub_committee_or_None, version) from a Belgian Joint
    Committee agreement code, or ValueError. Pure; the pattern is structural,
    not statutory content."""
    match = _AGREEMENT_CODE.fullmatch(str(code or "").strip().upper())
    if match is None:
        raise ValueError("a Belgian agreement code must be BE-PC-<committee>[-<sub>]-<version> "
                         "(e.g. BE-PC-200-1.0 or BE-PC-124-A-1.0)")
    return match.group(1), match.group(2), match.group(3)


def is_reference_only(key: str) -> bool:
    """onss_employer rate / band keys: never presented as an all-in employer rate."""
    group, kind, _ref, _label = KEYS[key]
    return group == "onss_employer" and kind in (KIND_RATE, KIND_BAND)


def key_label(key: str) -> str:
    """The seeded label: short label + spec-proposed display text (if any),
    plus the reference-only marker on onss_employer rate / band keys."""
    _g, _kind, _ref, label = KEYS[key]
    proposed = SPEC_PROPOSED.get(key)
    text = f"{label} (spec-proposed: {proposed})" if proposed else f"{label} (none in spec)"
    return f"{text} {REFERENCE_MARKER}" if is_reference_only(key) else text


def keys_in_group(group: str) -> tuple:
    return tuple(k for k, (g, *_rest) in KEYS.items() if g == group)
