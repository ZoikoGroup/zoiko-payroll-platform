"""
scripts/seed_germany_2026_registries.py
------------------------------------------
Phase 8P — populate Germany 2026 statutory registries (Contribution
Ceilings, PV Configuration, Health Funds) as DRAFT rows, each linked to a
real SourceArtifact evidence record (see seed_germany_source_evidence.py,
run first/reused here).

Phase 8V — improved source-authority linkage and U2 rate population:

- Contribution ceilings now prefer the SVBezGrV 2026 (primary federal
  regulation) as authority_source_id over the AOK corroboration or the
  Zoiko doc, matching the highest-ranking source in the evidence hierarchy.
- Health fund rows now include U2 (maternity) levy rates where confirmed
  by each fund's own official 2026 Umlagesaetze page — TK 0.44%, DAK
  0.39%, AOK PLUS 0.44%.
- U1 (sickness reimbursement) levy rates are populated into the
  GermanyHealthFundU1Tariff child table (Phase 8W) — U1 is employer-elected
  per tariff (multiple rates per fund), which the deprecated single
  GermanyHealthFund.u1_rate_pct column cannot represent. TK (50/1.3,
  70/2.1, 80/3.2), DAK (with its 2026-09-01 mid-year change — pre-Sep:
  50/1.3, 60/1.9, 70/2.4, 80/3.9; from Sep: 50/0.8, 60/1.0, 70/1.3,
  80/1.8), AOK PLUS (50/2.15, 65/2.95).

Phase 8Y — populates the GermanyEarningTaxabilityRule registry (spec §15,
table created Phase 8T, never previously seeded — see Phase 8X report §15)
with all 9 earning/deduction types, transcribed verbatim from the supplied
document's own §15 matrix (the same document, re-read directly from its XML
this phase; not corroborated externally because the classification IS the
document's own literal text, not a rate this project's hierarchy asks to be
independently confirmed against a government source). One genuine model gap
was found and fixed while transcribing: the wage-tax vocabulary
(_GERMANY_WAGE_TAX_TREATMENTS in service.py) had no value for "Scheme/limit-
specific" (the Occupational pension contribution row's literal Lohnsteuer-
column text) even though the identical phrase already existed in the
social-insurance vocabulary for the same row's other two columns — a single
additive vocabulary value (SCHEME_LIMIT_SPECIFIC) was added, not invented,
since it reuses the spec's own phrase already accepted elsewhere in this
model. These rows, like every other registry this script seeds, are
DRAFT-only and never auto-published.

Phase 8AD — populates the two GLOBAL Germany overtime/shift-premium
statutory registries created this phase: GermanyOvertimePremiumCategory
(the 5 §3b EStG percentage categories: NIGHT_STANDARD 25%, NIGHT_EXTENDED
40%, SUNDAY 50%, HOLIDAY_STANDARD 125%, HOLIDAY_SPECIAL 150%) and
GermanyOvertimeGrundlohnCap (WAGE_TAX €50.00/hour per §3b EStG,
SOCIAL_INSURANCE €25.00/hour per §1 Abs. 1 Satz 1 Nr. 1 SvEV) — both
source-linked to the §3b EStG / §1 SvEV SourceArtifact rows Phase 8Z
already created (found via _find_artifact_id, never duplicated). Every
value transcribed here was independently verified against those same
fetched-live primary-source artifacts before seeding — see the Phase 8AD
report for the verification trail. DRAFT-only, never auto-published, same
as every other registry this script seeds.

WHAT THIS SCRIPT DOES NOT DO, DELIBERATELY:

- It does NOT approve or publish any row. Phase 8O's maker-checker
  enforcement (service.set_contribution_ceiling_status /
  set_pv_configuration_status / set_health_fund_status) requires a
  distinct human approver and rejects PUBLISHED without a linked
  authority_source_id — this script satisfies the evidence precondition
  and leaves the actual approval/publication decision to a real Super
  Admin via the Phase 8O UI (/super-admin/compliance/germany/registries).
  Self-approving here would fabricate a governance decision nobody made.

- It does NOT populate every Krankenkasse in Germany — only the three
  funds this phase independently verified against each fund's own
  official page (TK, DAK-Gesundheit, AOK PLUS). No employee currently has
  a de_health_fund_code referencing any OTHER fund (the real environment's
  EmployeeStatutoryProfile table has zero rows — confirmed by this
  phase's own read-only database audit), so there is no "actually
  required" fund this script is omitting.

- It was NOT run against any shared/remote database this phase (see the
  Phase 8P report's own disclosure) — verified only against the isolated
  SQLite test fixture, per this project's established precedent.

Usage (against whichever DATABASE_URL is configured — never invoked
automatically):

    python -m scripts.seed_germany_2026_registries
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database import SessionLocal, initialize_database
from app.modules.payroll.models import (
    GermanyContributionCeiling, GermanyEarningTaxabilityRule, GermanyHealthFund,
    GermanyHealthFundU1Tariff, GermanyPvConfiguration, SourceArtifact,
    GermanyOvertimePremiumCategory, GermanyOvertimeGrundlohnCap,
    GermanyChurchTaxException,
)
from scripts.seed_germany_source_evidence import seed_germany_source_evidence


def _find_artifact_id(db: Session, agency: str, title_contains: str) -> int | None:
    row = (
        db.query(SourceArtifact)
        .filter(SourceArtifact.agency == agency, SourceArtifact.title.contains(title_contains))
        .first()
    )
    return row.id if row else None


def _find_artifact_id_by_form_number(db: Session, agency: str, form_number: str) -> int | None:
    """Exact form_number lookup — used for the §3b EStG / §1 SvEV rows
    (Phase 8Z), whose `form_number` is a precise citation ("§3b EStG",
    "§1 SvEV") but whose `title` is a long descriptive sentence that does
    NOT contain that exact short string as a contiguous substring (e.g.
    "§1 Abs. 1 Satz 1 Nr. 1 SvEV — SFN-Zuschläge..." does not contain
    "§1 SvEV" verbatim) — _find_artifact_id's title.contains() would
    silently fail to match, so this dedicated exact-match lookup is used
    instead for these two artifacts specifically."""
    row = (
        db.query(SourceArtifact)
        .filter(SourceArtifact.agency == agency, SourceArtifact.form_number == form_number)
        .first()
    )
    return row.id if row else None


# ── Contribution ceilings (spec §9; primary federal regulation SVBezGrV
# 2026 — the highest-ranking official German government source — fetched
# and confirmed Phase 8V; corroborated independently by AOK's Rechengrößen
# page and the BMF PAP XML's embedded MPARA values, Phase 8B) ───────────

def _contribution_ceiling_rows(db: Session) -> list[dict]:
    svbezgrv_id = _find_artifact_id(db, "Bundesministerium der Justiz (gesetze-im-internet.de)", "SVBezGrV 2026")
    aok_id = _find_artifact_id(db, "AOK", "Rechengrößen 2026")
    doc_id = _find_artifact_id(db, "Zoiko Payroll — Germany 2026 Statutory Configuration Pack v1.0", "§9")
    source_id = svbezgrv_id or aok_id or doc_id  # prefer the primary federal regulation
    return [
        dict(
            branch="RV_ALV", monthly_ceiling=Decimal("8450.00"), annual_ceiling=Decimal("101400.00"),
            effective_from=date(2026, 1, 1), authority_source_id=source_id,
        ),
        dict(
            branch="GKV_PV", monthly_ceiling=Decimal("5812.50"), annual_ceiling=Decimal("69750.00"),
            effective_from=date(2026, 1, 1), authority_source_id=source_id,
        ),
    ]


# ── PV configuration (spec §10 — this phase's own source hierarchy ranks
# the supplied document ABOVE external sources for values it states
# directly; the childless-surcharge legal basis is independently confirmed
# via SGB XI §55/§58, Phase 8L) ──────────────────────────────────────────

# (child_category, total, standard_employee, employer, saxony_employee, saxony_employer)
_PV_RATE_MATRIX = [
    ("CHILDLESS", "4.20", "2.40", "1.80", "2.90", "1.30"),
    ("1", "3.60", "1.80", "1.80", "2.30", "1.30"),
    ("2", "3.35", "1.55", "1.80", "2.05", "1.30"),
    ("3", "3.10", "1.30", "1.80", "1.80", "1.30"),
    ("4", "2.85", "1.05", "1.80", "1.55", "1.30"),
    ("5_PLUS", "2.60", "0.80", "1.80", "1.30", "1.30"),
]


def _pv_configuration_rows(db: Session) -> list[dict]:
    doc_id = _find_artifact_id(db, "Zoiko Payroll — Germany 2026 Statutory Configuration Pack v1.0", "§10")
    rows = []
    for category, total, std_emp, employer, sax_emp, sax_employer in _PV_RATE_MATRIX:
        for is_saxony in (False, True):
            rows.append(dict(
                child_category=category, is_saxony=is_saxony,
                total_rate_pct=Decimal(total), standard_employee_rate_pct=Decimal(std_emp),
                employer_rate_pct=Decimal(employer), saxony_employee_rate_pct=Decimal(sax_emp),
                saxony_employer_rate_pct=Decimal(sax_employer),
                effective_from=date(2026, 1, 1), authority_source_id=doc_id,
            ))
    return rows


# ── Health funds (three Krankenkassen independently verified against each
# fund's own official page — never the 2.9% statutory average). U2 rates
# populated from each fund's own 2026 Umlagesätze page. U1 now populated
# into the GermanyHealthFundU1Tariff child table (Phase 8W) — the old
# u1_rate_pct single column remains NULL/deprecated. ─────────────────────

def _health_fund_rows(db: Session) -> list[dict]:
    tk_id = _find_artifact_id(db, "Techniker Krankenkasse (TK)", "Zusatzbeitragssatz")
    dak_id = _find_artifact_id(db, "DAK-Gesundheit", "Zusatzbeitragssatz")
    aokplus_id = _find_artifact_id(db, "AOK PLUS (Sachsen und Thüringen)", "Zusatzbeitragssatz")
    barmer_id = _find_artifact_id(db, "BARMER", "Zusatzbeitragssatz")
    tk_u_id = _find_artifact_id(db, "Techniker Krankenkasse (TK)", "Umlagesätze U1/U2")
    dak_u_id = _find_artifact_id(db, "DAK-Gesundheit", "Umlagesätze U1/U2")
    aokplus_u_id = _find_artifact_id(db, "AOK PLUS (Sachsen und Thüringen)", "Umlagesätze U1/U2")
    return [
        dict(
            health_fund_id="TK", fund_name="Techniker Krankenkasse",
            supplementary_rate_pct=Decimal("2.6900"), is_average_rate=False,
            u1_rate_pct=None,  # deprecated single column stays NULL — see child table
            u2_rate_pct=Decimal("0.4400"),  # single 100%-Erstattungssatz tariff
            effective_from=date(2026, 1, 1), authority_source_id=tk_id,
        ),
        dict(
            health_fund_id="DAK-GESUNDHEIT", fund_name="DAK-Gesundheit",
            supplementary_rate_pct=Decimal("3.2000"), is_average_rate=False,
            u1_rate_pct=None,  # deprecated single column stays NULL — see child table
            u2_rate_pct=Decimal("0.3900"),  # single 100%-Erstattungssatz tariff (ab 01/2026)
            effective_from=date(2026, 1, 1), authority_source_id=dak_id,
        ),
        dict(
            health_fund_id="AOK-PLUS", fund_name="AOK PLUS (Sachsen und Thüringen)",
            supplementary_rate_pct=Decimal("3.1000"), is_average_rate=False,
            u1_rate_pct=None,  # deprecated single column stays NULL — see child table
            u2_rate_pct=Decimal("0.4400"),  # single 100%-Erstattungssatz tariff
            effective_from=date(2026, 1, 1), authority_source_id=aokplus_id,
        ),
        dict(
            # Phase 8AL — resolves the SOURCE_REQUIRED gap Phase 8O/8P left
            # open (see seed_germany_source_evidence.py's own updated
            # module docstring for the primary-source finding).
            health_fund_id="BARMER", fund_name="BARMER",
            supplementary_rate_pct=Decimal("3.2900"), is_average_rate=False,
            u1_rate_pct=None,  # deprecated single column stays NULL — see child table
            u2_rate_pct=Decimal("0.4200"),  # single 100%-Erstattungssatz tariff
            effective_from=date(2026, 1, 1), authority_source_id=barmer_id,
        ),
    ]


# ── U1 tariffs (Phase 8W) ──────────────────────────────────────────────
# Each Krankenkasse publishes multiple U1 tariff options (different
# reimbursement percentages and corresponding levy rates). The employer
# selects one tariff for their employees at that fund. Effective-dated so
# mid-year rate changes (DAK's 2026-09-01 change) are representable without
# overwriting historical rates. All rows DRAFT-only, linked to each fund's
# own Umlagesätze SourceArtifact — never published by the seed script.

def _u1_tariff_rows(db: Session) -> list[dict]:
    tk_u_id = _find_artifact_id(db, "Techniker Krankenkasse (TK)", "Umlagesätze U1/U2")
    dak_u_id = _find_artifact_id(db, "DAK-Gesundheit", "Umlagesätze U1/U2")
    aokplus_u_id = _find_artifact_id(db, "AOK PLUS (Sachsen und Thüringen)", "Umlagesätze U1/U2")
    barmer_u_id = _find_artifact_id(db, "BARMER", "Umlagesätze U1/U2")
    rows = [
        # TK: 50% -> 1.3%, 70% (Regelsatz) -> 2.1%, 80% -> 3.2%
        dict(health_fund_id="TK", tariff_identifier="U1_50", tariff_name="50% Erstattungssatz",
             reimbursement_pct=Decimal("50"), levy_rate_pct=Decimal("1.3000"),
             effective_from=date(2026, 1, 1), authority_source_id=tk_u_id),
        dict(health_fund_id="TK", tariff_identifier="U1_70", tariff_name="70% Erstattungssatz (Regelsatz)",
             reimbursement_pct=Decimal("70"), levy_rate_pct=Decimal("2.1000"),
             effective_from=date(2026, 1, 1), authority_source_id=tk_u_id),
        dict(health_fund_id="TK", tariff_identifier="U1_80", tariff_name="80% Erstattungssatz",
             reimbursement_pct=Decimal("80"), levy_rate_pct=Decimal("3.2000"),
             effective_from=date(2026, 1, 1), authority_source_id=tk_u_id),
        # DAK: pre-2026-09-01 — 50% -> 1.3%, 60% -> 1.9%, 70% (Regelsatz) -> 2.4%, 80% -> 3.9%
        dict(health_fund_id="DAK-GESUNDHEIT", tariff_identifier="U1_50", tariff_name="50% Erstattungssatz (Jan-Aug)",
             reimbursement_pct=Decimal("50"), levy_rate_pct=Decimal("1.3000"),
             effective_from=date(2026, 1, 1), effective_to=date(2026, 8, 31), authority_source_id=dak_u_id),
        dict(health_fund_id="DAK-GESUNDHEIT", tariff_identifier="U1_60", tariff_name="60% Erstattungssatz (Jan-Aug)",
             reimbursement_pct=Decimal("60"), levy_rate_pct=Decimal("1.9000"),
             effective_from=date(2026, 1, 1), effective_to=date(2026, 8, 31), authority_source_id=dak_u_id),
        dict(health_fund_id="DAK-GESUNDHEIT", tariff_identifier="U1_70", tariff_name="70% Erstattungssatz Regelsatz (Jan-Aug)",
             reimbursement_pct=Decimal("70"), levy_rate_pct=Decimal("2.4000"),
             effective_from=date(2026, 1, 1), effective_to=date(2026, 8, 31), authority_source_id=dak_u_id),
        dict(health_fund_id="DAK-GESUNDHEIT", tariff_identifier="U1_80", tariff_name="80% Erstattungssatz (Jan-Aug)",
             reimbursement_pct=Decimal("80"), levy_rate_pct=Decimal("3.9000"),
             effective_from=date(2026, 1, 1), effective_to=date(2026, 8, 31), authority_source_id=dak_u_id),
        # DAK: effective 2026-09-01 — 50% -> 0.8%, 60% -> 1.0%, 70% (Regelsatz) -> 1.3%, 80% -> 1.8%
        dict(health_fund_id="DAK-GESUNDHEIT", tariff_identifier="U1_50", tariff_name="50% Erstattungssatz (ab Sep)",
             reimbursement_pct=Decimal("50"), levy_rate_pct=Decimal("0.8000"),
             effective_from=date(2026, 9, 1), authority_source_id=dak_u_id),
        dict(health_fund_id="DAK-GESUNDHEIT", tariff_identifier="U1_60", tariff_name="60% Erstattungssatz (ab Sep)",
             reimbursement_pct=Decimal("60"), levy_rate_pct=Decimal("1.0000"),
             effective_from=date(2026, 9, 1), authority_source_id=dak_u_id),
        dict(health_fund_id="DAK-GESUNDHEIT", tariff_identifier="U1_70", tariff_name="70% Erstattungssatz Regelsatz (ab Sep)",
             reimbursement_pct=Decimal("70"), levy_rate_pct=Decimal("1.3000"),
             effective_from=date(2026, 9, 1), authority_source_id=dak_u_id),
        dict(health_fund_id="DAK-GESUNDHEIT", tariff_identifier="U1_80", tariff_name="80% Erstattungssatz (ab Sep)",
             reimbursement_pct=Decimal("80"), levy_rate_pct=Decimal("1.8000"),
             effective_from=date(2026, 9, 1), authority_source_id=dak_u_id),
        # AOK PLUS: 50% -> 2.15%, 65% -> 2.95%
        dict(health_fund_id="AOK-PLUS", tariff_identifier="U1_50", tariff_name="50% Erstattungssatz",
             reimbursement_pct=Decimal("50"), levy_rate_pct=Decimal("2.1500"),
             effective_from=date(2026, 1, 1), authority_source_id=aokplus_u_id),
        dict(health_fund_id="AOK-PLUS", tariff_identifier="U1_65", tariff_name="65% Erstattungssatz",
             reimbursement_pct=Decimal("65"), levy_rate_pct=Decimal("2.9500"),
             effective_from=date(2026, 1, 1), authority_source_id=aokplus_u_id),
        # BARMER (Phase 8AL): 50% -> 1.90%, 65% (Regelsatz) -> 2.50%, 80% -> 4.00%
        # — "Eckwerte ab Januar 2026" PDF, Artikelnummer 6221 0126.
        dict(health_fund_id="BARMER", tariff_identifier="U1_50", tariff_name="50% Erstattungssatz",
             reimbursement_pct=Decimal("50"), levy_rate_pct=Decimal("1.9000"),
             effective_from=date(2026, 1, 1), authority_source_id=barmer_u_id),
        dict(health_fund_id="BARMER", tariff_identifier="U1_65", tariff_name="65% Erstattungssatz (Regelsatz)",
             reimbursement_pct=Decimal("65"), levy_rate_pct=Decimal("2.5000"),
             effective_from=date(2026, 1, 1), authority_source_id=barmer_u_id),
        dict(health_fund_id="BARMER", tariff_identifier="U1_80", tariff_name="80% Erstattungssatz",
             reimbursement_pct=Decimal("80"), levy_rate_pct=Decimal("4.0000"),
             effective_from=date(2026, 1, 1), authority_source_id=barmer_u_id),
    ]
    return rows



# ── Earning/deduction taxability (Phase 8Y — spec §15's own "Earnings and
# Deduction Taxability Matrix" table, transcribed verbatim from the docx's
# own XML; the "Notes / router" column becomes reporting_classification
# free text exactly as spec states it, never paraphrased into an enum the
# spec does not itself supply). ─────────────────────────────────────────

# (earning_type, wage_tax_treatment, gkv_pv_treatment, rv_alv_treatment, reporting_classification)
_EARNING_TAXABILITY_MATRIX = [
    (
        "REGULAR_SALARY", "TAXABLE_REGULAR", "CONTRIBUTORY", "CONTRIBUTORY",
        "Subject to caps/status.",
    ),
    (
        "OVERTIME_SHIFT_PREMIUM", "CONDITIONALLY_EXEMPT", "MAY_DIFFER", "MAY_DIFFER",
        "Store tax-free threshold/conditions where applicable; do not blanket-exempt.",
    ),
    (
        "BONUS_ANNUAL_BONUS", "OTHER_REMUNERATION_SONSTB", "CONTRIBUTORY_SUBJECT_TO_ALLOCATION",
        "CONTRIBUTORY_SUBJECT_TO_ALLOCATION", "Route through SONSTB/annual PAP method as applicable.",
    ),
    (
        "PENSION_VERSORGUNGSBEZUG", "SPECIAL_PAP_HANDLING", "COVERAGE_SPECIFIC", "COVERAGE_SPECIFIC",
        "Use VBEZ/JVBEZ and related PAP parameters.",
    ),
    (
        "EQUITY_BENEFIT_19A", "SPECIAL_PAP_HANDLING", "CLASSIFICATION_SPECIFIC", "CLASSIFICATION_SPECIFIC",
        "Use PAP fields for deferred/triggered taxable benefits.",
    ),
    (
        "EXPENSE_REIMBURSEMENT", "CONDITIONALLY_EXEMPT", "OFTEN_NON_CONTRIBUTORY", "OFTEN_NON_CONTRIBUTORY",
        "Evidence/limits required.",
    ),
    (
        # Phase 8Y: spec's literal Lohnsteuer-column text for this row is
        # "Scheme/limit-specific" — the same phrase as its GKV/PV and RV/ALV
        # columns. See the module docstring for the one-value wage-tax
        # vocabulary addition this required.
        "OCCUPATIONAL_PENSION_CONTRIBUTION", "SCHEME_LIMIT_SPECIFIC", "SCHEME_LIMIT_SPECIFIC",
        "SCHEME_LIMIT_SPECIFIC", "Benefit-plan statutory treatment asset.",
    ),
    (
        "GARNISHMENT_ATTACHMENT", "POST_TAX_NO_TAX_IMPACT", "NO_CHANGE_TO_BASE", "NO_CHANGE_TO_BASE",
        "Separate enforcement-order engine; protected amount rules versioned.",
    ),
    (
        "EMPLOYEE_VOLUNTARY_DEDUCTION", "POST_TAX_NO_TAX_IMPACT", "NO_CHANGE_TO_BASE", "NO_CHANGE_TO_BASE",
        "Never use deduction catalog to alter taxability without explicit rule.",
    ),
]


def _earning_taxability_rows(db: Session) -> list[dict]:
    doc_id = _find_artifact_id(db, "Zoiko Payroll — Germany 2026 Statutory Configuration Pack v1.0", "§15")
    return [
        dict(
            earning_type=earning_type, wage_tax_treatment=wage_tax, gkv_pv_treatment=gkv_pv,
            rv_alv_treatment=rv_alv, reporting_classification=notes,
            effective_from=date(2026, 1, 1), authority_source_id=doc_id,
        )
        for earning_type, wage_tax, gkv_pv, rv_alv, notes in _EARNING_TAXABILITY_MATRIX
    ]


# ── Overtime/shift-premium statutory registries (Phase 8AD) ──────────────
# Source-linked to the §3b EStG / §1 SvEV SourceArtifact rows Phase 8Z
# already created — never duplicated (searched first via _find_artifact_id,
# same convention as every other registry in this script).

# (category_code, wage_tax_free_pct) — the exact 5 categories Phase 8Z's
# fetched §3b EStG text distinguishes.
_OVERTIME_PREMIUM_CATEGORY_MATRIX = [
    ("NIGHT_STANDARD", "25.00"),
    ("NIGHT_EXTENDED", "40.00"),
    ("SUNDAY", "50.00"),
    ("HOLIDAY_STANDARD", "125.00"),
    ("HOLIDAY_SPECIAL", "150.00"),
]


def _overtime_premium_category_rows(db: Session) -> list[dict]:
    estg_id = _find_artifact_id_by_form_number(db, "Bundesministerium der Justiz (gesetze-im-internet.de)", "§3b EStG")
    return [
        dict(
            category_code=category_code, wage_tax_free_pct=Decimal(pct),
            effective_from=date(2026, 1, 1), authority_source_id=estg_id,
        )
        for category_code, pct in _OVERTIME_PREMIUM_CATEGORY_MATRIX
    ]


# (dimension, hourly_cap_amount, source form_number to look up)
_OVERTIME_GRUNDLOHN_CAP_MATRIX = [
    ("WAGE_TAX", "50.00", "§3b EStG"),
    ("SOCIAL_INSURANCE", "25.00", "§1 SvEV"),
]


def _overtime_grundlohn_cap_rows(db: Session) -> list[dict]:
    rows = []
    for dimension, amount, form_number in _OVERTIME_GRUNDLOHN_CAP_MATRIX:
        source_id = _find_artifact_id_by_form_number(db, "Bundesministerium der Justiz (gesetze-im-internet.de)", form_number)
        rows.append(dict(
            dimension=dimension, hourly_cap_amount=Decimal(amount),
            effective_from=date(2026, 1, 1), authority_source_id=source_id,
        ))
    return rows


# ── Church tax exceptions (Phase 8AM) ──────────────────────────────────────
# Bad Wimpfen (Baden-Württemberg, PLZ 74206) — Roman Catholic denomination
# exception: 9% Kirchensteuer (Diocese of Mainz BW enclave) instead of BW's
# general 8%. Source-linked to the FinMin BW 2026 circular (FM3-S2442-3/38)
# and the Diocese of Mainz Diözesankirchensteuerrat Beschluss 2025-12-13.
# Effective 2016-01-01, continuously re-confirmed annually. DRAFT-only,
# never auto-published — requires maker-checker approval via Super Admin UI.

def _church_tax_exception_rows(db: Session) -> list[dict]:
    # Use the 2026 FinMin BW circular as the primary authority source
    finmin_2026_id = _find_artifact_id(db, "Finanzministerium Baden-Württemberg", "2026")
    dioezese_id = _find_artifact_id(db, "Bistum Mainz", "Diözesankirchensteuerrat")
    # Prefer the 2026 circular; fall back to Diocese decision if not found
    source_id = finmin_2026_id or dioezese_id
    return [
        dict(
            land_code="DE-BW",
            denomination="ROMAN_CATHOLIC",
            municipality_postal_code="74206",
            scope_description=(
                "Bad Wimpfen — Diocese of Mainz enclave in BW. RC church tax 9% "
                "(vs. BW general 8%) per FinMin BW Erlass 22.5.2026 (FM3-S2442-3/38, "
                "BStBl 2026 I S.869) and Diocese of Mainz Kirchensteuerrat Beschluss "
                "13.12.2025. Applies to wage/income/capital-gains tax per §51a EStG. "
                "Effective 2016-01-01."
            ),
            exception_rate_pct=Decimal("9.00"),
            effective_from=date(2016, 1, 1),
            effective_to=None,  # open-ended, still current
            authority_source_id=source_id,
        ),
    ]


def seed_germany_2026_registries(db: Session) -> dict:
    """Idempotent: skips any row whose natural key already exists. Returns
    a dict of the newly-created rows per registry (empty lists if
    everything already existed). Never approves/publishes — see module
    docstring."""
    seed_germany_source_evidence(db)  # ensure the evidence rows exist/are reused first

    created = {
        "contribution_ceilings": [], "pv_configurations": [], "health_funds": [], "u1_tariffs": [],
        "earning_taxability_rules": [], "overtime_premium_categories": [], "overtime_grundlohn_caps": [],
        "church_tax_exceptions": [],
    }

    for entry in _contribution_ceiling_rows(db):
        existing = (
            db.query(GermanyContributionCeiling)
            .filter(
                GermanyContributionCeiling.branch == entry["branch"],
                GermanyContributionCeiling.effective_from == entry["effective_from"],
            )
            .first()
        )
        if existing:
            continue
        row = GermanyContributionCeiling(**entry, status="DRAFT")
        db.add(row)
        created["contribution_ceilings"].append(row)

    for entry in _pv_configuration_rows(db):
        existing = (
            db.query(GermanyPvConfiguration)
            .filter(
                GermanyPvConfiguration.child_category == entry["child_category"],
                GermanyPvConfiguration.is_saxony == entry["is_saxony"],
                GermanyPvConfiguration.effective_from == entry["effective_from"],
            )
            .first()
        )
        if existing:
            continue
        row = GermanyPvConfiguration(**entry, status="DRAFT")
        db.add(row)
        created["pv_configurations"].append(row)

    for entry in _health_fund_rows(db):
        existing = (
            db.query(GermanyHealthFund)
            .filter(
                GermanyHealthFund.health_fund_id == entry["health_fund_id"],
                GermanyHealthFund.effective_from == entry["effective_from"],
            )
            .first()
        )
        if existing:
            continue
        row = GermanyHealthFund(**entry, status="DRAFT")
        db.add(row)
        created["health_funds"].append(row)

    # Phase 8W — U1 tariff child rows (idempotent by fund+tariff+effective_from)
    for entry in _u1_tariff_rows(db):
        existing = (
            db.query(GermanyHealthFundU1Tariff)
            .filter(
                GermanyHealthFundU1Tariff.health_fund_id == entry["health_fund_id"],
                GermanyHealthFundU1Tariff.tariff_identifier == entry["tariff_identifier"],
                GermanyHealthFundU1Tariff.effective_from == entry["effective_from"],
            )
            .first()
        )
        if existing:
            continue
        row = GermanyHealthFundU1Tariff(**entry, status="DRAFT")
        db.add(row)
        created["u1_tariffs"].append(row)

    # Phase 8Y — earning/deduction taxability rows (idempotent by earning_type+effective_from)
    for entry in _earning_taxability_rows(db):
        existing = (
            db.query(GermanyEarningTaxabilityRule)
            .filter(
                GermanyEarningTaxabilityRule.earning_type == entry["earning_type"],
                GermanyEarningTaxabilityRule.effective_from == entry["effective_from"],
            )
            .first()
        )
        if existing:
            continue
        row = GermanyEarningTaxabilityRule(**entry, status="DRAFT")
        db.add(row)
        created["earning_taxability_rules"].append(row)

    # Phase 8AD — overtime premium categories (idempotent by category_code+effective_from)
    for entry in _overtime_premium_category_rows(db):
        existing = (
            db.query(GermanyOvertimePremiumCategory)
            .filter(
                GermanyOvertimePremiumCategory.category_code == entry["category_code"],
                GermanyOvertimePremiumCategory.effective_from == entry["effective_from"],
            )
            .first()
        )
        if existing:
            continue
        row = GermanyOvertimePremiumCategory(**entry, status="DRAFT")
        db.add(row)
        created["overtime_premium_categories"].append(row)

    # Phase 8AD — overtime Grundlohn caps (idempotent by dimension+effective_from)
    for entry in _overtime_grundlohn_cap_rows(db):
        existing = (
            db.query(GermanyOvertimeGrundlohnCap)
            .filter(
                GermanyOvertimeGrundlohnCap.dimension == entry["dimension"],
                GermanyOvertimeGrundlohnCap.effective_from == entry["effective_from"],
            )
            .first()
        )
        if existing:
            continue
        row = GermanyOvertimeGrundlohnCap(**entry, status="DRAFT")
        db.add(row)
        created["overtime_grundlohn_caps"].append(row)

    # Phase 8AM — church tax exceptions (idempotent by land_code+denomination+municipality_postal_code+effective_from)
    for entry in _church_tax_exception_rows(db):
        existing = (
            db.query(GermanyChurchTaxException)
            .filter(
                GermanyChurchTaxException.land_code == entry["land_code"],
                GermanyChurchTaxException.denomination == entry["denomination"],
                GermanyChurchTaxException.municipality_postal_code == entry["municipality_postal_code"],
                GermanyChurchTaxException.effective_from == entry["effective_from"],
            )
            .first()
        )
        if existing:
            continue
        row = GermanyChurchTaxException(**entry, status="DRAFT")
        db.add(row)
        created["church_tax_exceptions"].append(row)

    any_created = any(created.values())
    if any_created:
        db.commit()
        for rows in created.values():
            for row in rows:
                db.refresh(row)
    return created


def main() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        created = seed_germany_2026_registries(db)
        for registry, rows in created.items():
            print(f"{registry}: created {len(rows)} new DRAFT row(s).")
        print(
            "\nNo row was approved or published — that requires a real, distinct Super Admin "
            "decision via /super-admin/compliance/germany/registries (maker-checker, enforced server-side)."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
