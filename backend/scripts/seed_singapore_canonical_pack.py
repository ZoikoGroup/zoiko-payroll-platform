"""
scripts/seed_singapore_canonical_pack.py
-------------------------------------------------
Seeds the canonical (organization_id IS NULL) Singapore tax pack
SG-PAYROLL-2026 — JurisdictionPack + ContributionRate + TaxSlab rows +
SourceArtifact evidence — the same DB-driven shape every other country's
canonical pack uses (see seed_caribbean_canonical_packs.py).

Sources (every value traceable to one of them):
  - ZP-SG-ENG-001 v1.0 (22 Sep 2026) — the implementation specification.
  - Official CPF Board / IRAS / MOM publications, retrieved 2026-09-23 and
    recorded as SourceArtifact rows (authority, URL, retrieval time,
    SHA-256 of the retrieved bytes) — see SOURCES below. Where a source
    added a value the specification did not state (CPF low-wage rows,
    SPR year 1/2 tables, the age-band rule, the pre-July LQS), no conflict
    with the specification existed; the one conflict found (AW ceiling
    timing, SG-007) was resolved by explicit approval (Option A) and is
    implemented in engine/countries/singapore.py, not here.

Versioning: v1.0 (specification values only) and v1.1 (official CPF /
IRAS / MOM values, 2026-09-23) are left untouched; this seed writes v1.2 as
a NEW Draft version (previous_version_id → v1.1) because Phase 5 adds
statutory values (Work Permit levy, PWM, Employment Act evidence links). Neither is ever set Active here — activation goes
through the existing Super Admin workflow: a distinct approver
(maker-checker), a linked SourceArtifact, and a passing SG golden-vector
certification run (set_jurisdiction_pack_status). Re-running refuses to
touch a version that has left Draft.

Deliberately NOT seeded (BLOCKED — AUTHORITATIVE VALUE REQUIRED):
  - Work Permit levy before 24 Sep 2026 for services / manufacturing /
    process / marine shipyard (MOM states no effective date).
  - The S Pass / Work Permit EXPIRY end-day basis (MOM does not state whether
    the expiry day is levied). The CANCELLATION rule is seeded: MOM's
    cancellation pages — "When levy stops: 1 day before cancellation".
(The part-time LQS rate before 1 July 2026 IS seeded — MOM COS 2024
factsheet, $10.50/h from 1 July 2024 — see the lqs_part_time_hourly rows.)

Idempotent — touches only SG rows under the v1.1 pack (plus the one SG AIS
filing-calendar row and SG evidence artifacts matched by URL + hash), never
any other country and never org-scoped rows.

Usage:
    python -m scripts.seed_singapore_canonical_pack
"""
import sys
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, initialize_database
from app.modules.payroll.models import (
    ContributionRate, JurisdictionPack, SourceArtifact, StatutoryFilingCalendar, TaxSlab,
)
from app.modules.payroll.engine.countries.singapore import work_permit_levy_key
from app.modules.payroll.engine.jurisdictions.singapore.labour import pwm_key, pwm_overtime_rate_key
from scripts._local_db_guard import assert_local_database

CODE = "SG"
PACK_ID = "SG-PAYROLL-2026"
PACK_VERSION = "1.2"
PREVIOUS_VERSION = "1.1"
TAX_YEAR = "2026"
EFFECTIVE_FROM = date(2026, 1, 1)
# Phase 6.0 F3: the 2026 pack ends on 31 Dec 2026. Open-ended, it overlapped
# SG-PAYROLL-2027 (from 1 Jan 2027) for ever, so the overlap guard in
# set_jurisdiction_pack_status refused to activate the 2027 pack.
EFFECTIVE_TO = date(2026, 12, 31)
LQS_CHANGE = date(2026, 7, 1)
SPEC = "ZP-SG-ENG-001 v1.0 (22 Sep 2026)"
RETRIEVED_AT = datetime(2026, 9, 23, 10, 23, 44, tzinfo=timezone.utc)
# Phase 5 sources (keys in PHASE5_SOURCE_KEYS) were retrieved 2026-09-24.
RETRIEVED_AT_PHASE5 = datetime(2026, 9, 24, 9, 0, 0, tzinfo=timezone.utc)
# Phase 5.3 / 5.4 sources (keys in LATER_SOURCE_KEYS) were retrieved 2026-09-25.
RETRIEVED_AT_PHASE53 = datetime(2026, 9, 25, 9, 0, 0, tzinfo=timezone.utc)
RETRIEVED_AT_CLOSURE = datetime(2026, 9, 29, 6, 0, 0, tzinfo=timezone.utc)
# MOM publishes no effective date for the current services / manufacturing /
# process / marine shipyard Work Permit levy tables: they are evidenced only
# as in force when retrieved, so earlier wage months fail closed (BLOCKED)
# rather than assume the rate applied all year.
WP_EVIDENCED_FROM = date(2026, 9, 24)
WP_CONSTRUCTION_FROM = date(2024, 1, 1)   # MOM construction page: "From 1 January 2024, the levy rate is as follows"

# key -> (agency, title, url, sha256 of the retrieved bytes, publication date)
# HTML pages are dynamic: the hash evidences the exact bytes retrieved.
SOURCES = {
    "cpf_rate_tables": (
        "CPF Board", "CPF Contribution Rate Tables from 1 January 2026 (Tables 1–5)",
        "https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/CPFcontributionratesfrom1Jan2026.pdf",
        "7ab21a34bd830be773b5bf39020f590d61e744fb7df6c91922352cef82789496", None,
    ),
    "cpf_how_much": (
        "CPF Board", "How much CPF contributions to pay (age-group rule; SPR year definition)",
        "https://www.cpf.gov.sg/employer/employer-obligations/how-much-cpf-contributions-to-pay",
        "c8c94a62178d7dc3edb960fb3686ba351eedfcfbe12f8675c0ead3b402fd080e", None,
    ),
    "cpf_what_payments": (
        "CPF Board", "What payments attract CPF contributions (OW/AW, OW ceiling, AW ceiling formula)",
        "https://www.cpf.gov.sg/employer/employer-obligations/what-payments-attract-cpf-contributions",
        "3a5795e639edfb9b0af2969982bd98dfb4a0967b646e5b6f77da1c9cc95f9c18", None,
    ),
    "cpf_aw_examples": (
        "CPF Board", "Examples for computation of Additional Wage (AW) Ceiling (2026)",
        "https://www.cpf.gov.sg/service/sfc/servlet.shepherd/document/download/069IW00000M1wtJYAR",
        "98fc7777d8c6fb0f76f4770217570e26e94e91533345d98db7b1c451c8721220", None,
    ),
    "cpf_sdl": (
        "CPF Board", "Skills Development Levy",
        "https://www.cpf.gov.sg/employer/employer-obligations/skills-development-levy",
        "2801e71d024a570c7d156c0cebb67509ffec44b91e2c99fa865c0cc453314c96", None,
    ),
    "cpf_shg": (
        "CPF Board", "Contributions to self-help groups (CDAC / ECF / MBMF / SINDA rates and eligibility)",
        "https://www.cpf.gov.sg/employer/employer-obligations/contributions-to-self-help-groups",
        "fd7c2768f1da797f17d1896567d71e42fffd6b3733aba4ab9bf89d267fd36595", date(2026, 9, 22),
    ),
    "mom_lqs": (
        "MOM", "Local Qualifying Salary",
        "https://www.mom.gov.sg/employment-practices/progressive-wage-model/local-qualifying-salary",
        "60f08866d40056429d79e70f1bda97ad7fd7cd9d3d212b0ae99b98430ec07429", None,
    ),
    "mom_lqs_factsheet": (
        "MOM", "Factsheet: Lower-Wage Workers Policy Announcements at COS 2026 (LQS raised from $1,600 to $1,800 from 1 July 2026)",
        "https://www.mom.gov.sg/-/media/mom/documents/press-releases/2026/factsheet-on-lower-wage-workers-03032026.pdf",
        "2a98b39e30b111daacf944712a9eb3fdae18192f0a864c79c8b6cd265ed502fa", date(2026, 3, 3),
    ),
    "mom_spass_levy": (
        "MOM", "S Pass quota and levy requirements (levy harmonised to $650 since 1 Sep 2025)",
        "https://www.mom.gov.sg/passes-and-permits/s-pass/quota-and-levy/levy-and-quota-requirements",
        "4916192e09c3f20ec56fdf5e6994cebc6cb27b77d55a0d0026080de662e392ad", date(2026, 2, 19),
    ),
    "iras_ais": (
        "IRAS", "Join the Auto-Inclusion Scheme (AIS) for Employment Income (5+ employees; YA2027 by 1 Mar 2027)",
        "https://www.iras.gov.sg/taxes/individual-income-tax/employers/auto-inclusion-scheme-(ais)-for-employment-income/join-the-auto-inclusion-scheme-(ais)-for-employment-income",
        "69e5e7151931e99ae5905e6d191024930a9fc00e91ccf0d892722a32a5b9695e", None,
    ),
    "iras_ir21": (
        "IRAS", "Tax Clearance for Employees (IR21) — notify at least one month in advance; departure > 3 months",
        "https://www.iras.gov.sg/taxes/individual-income-tax/employers/tax-clearance-for-foreign-spr-employees-(ir21)/tax-clearance-for-employees",
        "8b2fd2a8dc37d21d493cd30500452f0efd71951d5d9ccb778fabb674acb82680", None,
    ),
}

_MOM = "https://www.mom.gov.sg"
_WP = _MOM + "/passes-and-permits/work-permit-for-foreign-worker"
_EP = _MOM + "/employment-practices"
_PHASE5_SOURCES = {
    "cpf_ezpay_ftp_spec": (
        "CPF Board", "CPF EZPay (FTP) File Specifications (effective from 16 January 2025)",
        "https://www.cpf.gov.sg/content/dam/web/employer/making-cpf-contributions/documents/CPFEZPayFTPSpecifications.pdf",
        "1ddd242b7893d37b0e62456c629fdc39d08f720c33c6c47d45684213815c8a89", date(2025, 1, 16),
    ),
    "cpf_rate_tables_2027": (
        "CPF Board", "CPF Contribution Rate Tables from 1 January 2027 (Tables 1–5)",
        "https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/jan2027cpfcontributionrates.pdf",
        "16ac89e7e45b0e281f5b0977be35224b8b2ead83ead6b3bf5e1da72a61b469e3", None,
    ),
    "cpf_enforcement": (
        "CPF Board", "Enforcement and penalties for non-compliance (due date last day of the month; enforcement after the 14th)",
        "https://www.cpf.gov.sg/employer/compliance-and-rectifications/enforcement-and-penalties-for-non-compliance",
        "30b1e542a76a9cf580848bd39e5c1a8251d3afc50d04d00983207cad9486bc48", date(2026, 8, 5),
    ),
    "mom_wp_services": ("MOM", "Services sector: Work Permit requirements (quota and levy)",
                        _WP + "/sector-specific-rules/services-sector-requirements",
                        "191030a4161c3575cf8850aa161374de98ce96fc2d1dd9b53007608fc805e08e", date(2026, 9, 16)),
    "mom_wp_manufacturing": ("MOM", "Manufacturing sector: Work Permit requirements (quota and levy)",
                             _WP + "/sector-specific-rules/manufacturing-sector-requirements",
                             "024a2fbe99926c359dc2d9d26464f84b4ea3cd485397786dcbbe78ebcf720bba", date(2026, 9, 14)),
    "mom_wp_construction": ("MOM", "Construction sector: Work Permit requirements (levy from 1 January 2024)",
                            _WP + "/sector-specific-rules/construction-sector-requirements",
                            "cc4d83eccbf0f4ff945f7aa7612799738c05ad746aba218c31cc069ea78a85c2", date(2026, 7, 3)),
    "mom_wp_process": ("MOM", "Process sector: Work Permit requirements (quota and levy)",
                       _WP + "/sector-specific-rules/process-sector-requirements",
                       "caeb02b0b470c54e3664d345d14380734a27bb2bef13f0fd980ee235ce75dbc3", date(2026, 7, 1)),
    "mom_wp_marine": ("MOM", "Marine shipyard sector: Work Permit requirements (quota and levy)",
                      _WP + "/sector-specific-rules/marine-sector-requirements",
                      "ea9794241a81735e3073338bbc8353c058c94e9e1559ba5176cf91ea23d28453", date(2026, 7, 1)),
    "mom_fwl_pay": ("MOM", "Paying the foreign worker levy (by the 17th of the following month)",
                    _WP + "/foreign-worker-levy/paying-the-levy",
                    "a89efb7d8ac2b4fe9c0ed25cd8074afc8c44de16000833ddab14d65bb491eb31", date(2026, 7, 8)),
    "mom_fwl": ("MOM", "Foreign worker quota and levy requirements (levy liability from issue until cancellation/expiry)",
                _WP + "/foreign-worker-levy/what-is-the-foreign-worker-levy",
                "0b047bd60f408ab6f08948de54aae3ae2556abd83c1e7f831ae66be5ff43fb8b", date(2026, 7, 1)),
    "mom_ea_paying_salary": ("MOM", "Paying salary (at least monthly; within 7 days; overtime within 14 days; final salary)",
                             _EP + "/salary/paying-salary",
                             "3fa3d95622c3a34f78e9248697bc726f69fa74618ff654ca58a9a07e67d4c148", date(2026, 1, 30)),
    "mom_ea_deductions": ("MOM", "Allowable salary deductions (types, 25% / 50% limits, prohibited migrant-worker deductions)",
                          _EP + "/salary/salary-deductions",
                          "f659e2c81ad1db8a1e94c432d334daafaaffb5e2d19d9e36a320876e6bf62b0a", date(2024, 12, 16)),
    "mom_ea_hours": ("MOM", "Hours of work, overtime and rest day (Part 4: 1.5× hourly basic rate; 72 h/month)",
                     _EP + "/hours-of-work-overtime-and-rest-days",
                     "624199970809bb12d1abbdcb51bb4cd29b02fa2819ca702c6228086658f31ccc", date(2025, 7, 24)),
    "mom_ea_coverage": ("MOM", "Employment Act: who it covers (Part 4: workman ≤ $4,500, non-workman ≤ $2,600)",
                        _EP + "/employment-act/who-is-covered",
                        "660b75f02d4007661c8c5c81a58ca90055521b08872c9cc4fe64b833082bb21d", date(2025, 7, 24)),
    "mom_ea_payslips": ("MOM", "Itemised pay slips (items 1–12; issue within 3 working days)",
                        _EP + "/salary/itemised-payslips",
                        "25d64f39c6c54b6ec079c1cb2820dce4b4431ef3a202ed8164217784bc1beffa", date(2024, 3, 14)),
    "mom_ea_annual_leave": ("MOM", "Annual leave eligibility and entitlement (7 days year 1 to 14 days year 8)",
                            _EP + "/leave/annual-leave/eligibility-and-entitlement",
                            "8930dba22d874edb827381102b8d6e9f764f9f4d9725682816cb69002e88c6c4", date(2023, 4, 17)),
    "mom_ea_sick_leave": ("MOM", "Sick leave eligibility and entitlement (14 outpatient / 60 hospitalisation)",
                          _EP + "/leave/sick-leave/eligibility-and-entitlement",
                          "2c43e0142927b7cae78003aec44b46163d70111b4d4a2d07d714a0940a781e6d", date(2026, 1, 12)),
    "mom_ea_public_holidays": ("MOM", "Public holidays: entitlement and pay (11 paid public holidays)",
                               _EP + "/public-holidays-entitlement-and-pay",
                               "8d4228053174249deebe65f100308cf573f994f4a968f3935202baddf9521753", date(2025, 7, 30)),
    "mom_public_holidays_list": ("MOM", "Public holidays 2025 / 2026 / 2027 (with observed-day notes)",
                                 _EP + "/public-holidays",
                                 "c81bb6fa4e630bbbaf141c31efb72b1479c45bf5bb9546c62aa629c32fab6c34", date(2026, 6, 19)),
    "mom_ea_monthly_daily": ("MOM", "Monthly and daily salary: definitions and calculation",
                             _EP + "/salary/monthly-and-daily-salary",
                             "8861d26b215aac05178f2c34dd6100691f092dbe51e1e09f3c24df8ef56bb2ce", date(2025, 12, 8)),
    "mom_pwm_cleaning": ("MOM", "Progressive Wage Model for the cleaning sector", _EP + "/progressive-wage-model/cleaning-sector",
                         "24708b877d43f292d1249bfb1d85270179c64dbbe134e3562f70fe43de8e2560", date(2026, 9, 1)),
    "mom_pwm_security": ("MOM", "Progressive Wage Model for the security sector", _EP + "/progressive-wage-model/security-sector",
                         "f0cfa07d2b74139d559f7672581373c5f5fd22dbfa18b830d56269d5293f3d4a", date(2026, 9, 1)),
    "mom_pwm_landscape": ("MOM", "Progressive Wage Model for the landscape sector", _EP + "/progressive-wage-model/landscape-sector",
                          "63fa33995e40dd6b46724e0409845e05afc8757ec1dee61f9323fda079b2d7df", date(2026, 9, 1)),
    "mom_pwm_lift_escalator": ("MOM", "Progressive Wage Model for the lift and escalator sector",
                               _EP + "/progressive-wage-model/lift-and-escalator-sector",
                               "4d5e7f6210e13153258fdeb58d17df1c60c193d8d265528b7674660d6005fd1c", date(2026, 9, 1)),
    "mom_pwm_retail": ("MOM", "Progressive Wage Model for the retail sector", _EP + "/progressive-wage-model/retail-sector",
                       "7bd3627f1fd672a98dcb3189c1b1472a644712c9c4f36bdfdeec565e592d6684", date(2026, 9, 1)),
    "mom_pwm_food_services": ("MOM", "Progressive Wage Model for the food services sector",
                              _EP + "/progressive-wage-model/food-services-sector",
                              "b05f5914e7b00281aaac22f686b082d95ae011d4e1dc52e0a8fc8ac8182c6d51", date(2026, 9, 1)),
    "mom_opw": ("MOM", "Occupational Progressive Wages for administrators and drivers",
                _EP + "/progressive-wage-model/occupational-pws-for-administrators-and-drivers",
                "37b2e3058ba8cdfd265a358ea83976c3f60edc901b9c8cc2f04bcfa263f7d7c7", date(2026, 9, 1)),
    "mom_employment_records": ("MOM", "Employment records: what and how long to keep",
                               _EP + "/employment-records",
                               "de0ad65a83c314c646d2fbe680c9c4590ce9d158ffeac4ce40e163074d612349", date(2024, 3, 14)),
    "iras_record_keeping": ("IRAS", "Record Keeping Requirements (companies: at least 5 years from the relevant YA)",
                            "https://www.iras.gov.sg/taxes/corporate-income-tax/basics-of-corporate-income-tax/record-keeping-requirements",
                            "b4c26f777cd2933321775fdacc5df1d2530d06f5b6dcec2c19bb0479566fecc3", date(2026, 1, 22)),
    "mom_cos2024_foreign_workforce": (
        "MOM", "Factsheet: Foreign Workforce Policy Announcements at COS 2024 (LQS $1,600 / $10.50 per hour from 1 Jul 2024)",
        "https://www.mom.gov.sg/-/media/mom/documents/budget2024/factsheet-on-foreign-workforce-policies.pdf",
        "5822ec2358b5a262e089268aa4d463398a2db49e4fda7f3988d844fc71542f96", None),
    "mom_pwm_waste_ot": ("MOM", "PWM wage ladder for waste collection and materials recovery (gross wage excl. OT; OT rate of pay)",
                         "https://www.mom.gov.sg/-/media/mom/documents/employment-practices/pwm/waste-management-pwm-ot-rate-of-pay.pdf",
                         "f8f15e391847eb6127c41df7630704c2bec4747919c4bbe58a1013e761d18af6", None),
    "mom_pwm_ot_opw_pre_jul26": ("MOM", "Total PWM Gross Wage Requirement for overtime hours — Occupational PWs, 1 Mar 2023 – 30 Jun 2026",
        "https://www.mom.gov.sg/-/media/mom/documents/employment-practices/pwm/gross-wage-requirements-ot-opw.pdf",
        "06a843079369d58a103748967099d410f1c857c954350765b69ddc191e6794b3", None),
    "mom_pwm_ot_opw_from_jul26": ("MOM", "Total PWM Gross Wage Requirement for overtime hours — Occupational PWs, from 1 Jul 2026 (NWC 2025/2026)",
        "https://www.mom.gov.sg/-/media/mom/documents/employment-practices/pwm/item-1--nwc-20252026-guidelines-opw-ot-hours.pdf",
        "f7a6a5808a6ebd33486e0feac093f83577e7ab305843132c0244f7eabf65fd88", None),
    "mom_pwm_ot_fs_pre_jul26": ("MOM", "Food services PWM gross wage requirements for overtime hours, 1 Mar 2023 – 30 Jun 2026",
        "https://www.mom.gov.sg/-/media/mom/documents/employment-practices/pwm/gross-wage-requirements-ot-fs_2023.pdf",
        "2573b18755c5eee969d912ec6836d073d56f21bf88764524182e0c3f6e5511e5", None),
    "mom_pwm_ot_fs_from_jul26": ("MOM", "Food services PWM gross wage requirements for overtime hours, from 1 Jul 2026 (TCF 16 Mar 2026)",
        "https://www.mom.gov.sg/-/media/mom/documents/employment-practices/pwm/gross-wage-requirements-ot-fs.pdf",
        "08b210c92e6503e687e761e4737cea2b3bee1234b0a0940124acacd4d5f71113", None),
    "mom_pwm_ot_retail_pre_sep25": ("MOM", "Retail PWM gross wage requirements for overtime hours, 1 Sep 2022 – 31 Aug 2025",
        "https://www.mom.gov.sg/-/media/mom/documents/employment-practices/pwm/gross-wage-requirements-ot-retail-pwm.pdf",
        "744935ec56d8b19087e5d3489d83230b6373fe786810c04e6b131a3524904fe5", None),
    "mom_pwm_ot_retail_from_sep25": ("MOM", "Retail PWM gross wage requirements for overtime hours, from 1 Sep 2025 (TCR 11 Aug 2025)",
        "https://www.mom.gov.sg/-/media/mom/documents/employment-practices/pwm/tcr-recommendations-report-ot-wages-250811.pdf",
        "c011590a95a3947682486ccf6b813f93da5bbdb7d49cd83531c60ad517f4e10b", None),
    "mom_pwm_waste": ("MOM", "Progressive Wage Model for the waste management sector",
                      _EP + "/progressive-wage-model/waste-management-sector",
                      "86da9971e35c248f137e61dbeaa75a8b43941f5a2a01a7f514bcb28464f8e0e6", date(2026, 9, 1)),
    "iras_ir8a_notes_ya2027": (
        "IRAS", "Explanatory Notes for completion of Form IR8A & Appendix 8A for the year ended 31 Dec 2026 (YA2027)",
        "https://www.iras.gov.sg/docs/default-source/individual-income-tax/employers/explanatory-notes-on-form-ir8a-and-appendix-8a-for-ya2027.pdf?sfvrsn=7ae73f3a_5",
        "22f42c89b63ba14253309679c4c311554175ed1bd6753e5d42edd3c61c1dc2b0", None,
    ),
    "iras_ais_file_notes": (
        "IRAS", "Additional specifications for TXT and XML file format (Aug 2024, v1.0)",
        "https://www.iras.gov.sg/docs/default-source/default-document-library/things-to-note-for-both-txt-and-xml.pdf?sfvrsn=3cac4216_21",
        "f56c65e0811c15e10dd7b2accfb08a08b17aaf33443618196b8e488963d11cd4", date(2024, 8, 1),
    ),
    # Phase 6.8 (G3): the IR8A Revision / Amendment methods (myTax Portal
    # "Modify previously submitted data"); retrieved 2026-09-28.
    "iras_ais_modification_guide": (
        "IRAS", "Quick Guide on using Submit Employment Income Records Digital Service (Revision and Amendment submission methods)",
        "https://www.iras.gov.sg/media/docs/default-source/uploadedfiles/pdf/quick-guide-on-making-ais-amendments-at-mytax-portal-(online-application).pdf",
        "a419da57237d20e0b08aadfe9e96adf37bf38924ba2aee11fde53f82da5f01df", date(2025, 9, 15),
    ),
    "pdpc_nric": (
        "PDPC", "Advisory Guidelines on the PDPA for NRIC and other National Identification Numbers (31 Aug 2018)",
        "https://www.pdpc.gov.sg/-/media/files/pdpc/pdf-files/advisory-guidelines/advisory-guidelines-for-nric-numbers---310818.pdf",
        "b839a916a70243891b2dd4d1df1afdc7f1de0cc6eb2dd8875157821189a8c3b8", date(2018, 8, 31),
    ),
    # Production closure (retrieved 2026-09-29; SHA-256 of the retrieved HTML;
    # publication date = the page's "Last Updated").
    "mom_spass_cancel": (
        "MOM", "Cancel an S Pass — \"When levy stops: 1 day before cancellation\"",
        "https://www.mom.gov.sg/passes-and-permits/s-pass/cancel-a-pass",
        "5c71ac70d3b9d764320cc261d8987e36d2e6009bc95a5f549d0c7c3e3a3e704b", date(2025, 9, 15),
    ),
    "mom_wp_cancel": (
        "MOM", "Cancel a Work Permit — \"Your worker's levy will be charged until 1 day before the pass cancellation\"",
        _WP + "/cancel-a-work-permit",
        "2bc8e148258cde0041feec1f08c87c5acb9b2d24fe008f5175189b7700a52d11", date(2026, 8, 5),
    ),
}
LATER_SOURCE_KEYS = frozenset({"mom_opw", "mom_employment_records", "iras_record_keeping",
                               "mom_cos2024_foreign_workforce", "mom_pwm_waste_ot",
                               *(f"mom_{n}" for n in ("pwm_ot_opw_pre_jul26", "pwm_ot_opw_from_jul26", "pwm_ot_fs_pre_jul26", "pwm_ot_fs_from_jul26", "pwm_ot_retail_pre_sep25", "pwm_ot_retail_from_sep25"))})
CLOSURE_SOURCE_KEYS = frozenset({"mom_spass_cancel", "mom_wp_cancel"})
PHASE5_SOURCE_KEYS = frozenset(_PHASE5_SOURCES) - LATER_SOURCE_KEYS - CLOSURE_SOURCE_KEYS
SOURCES.update(_PHASE5_SOURCES)

# Work Permit monthly levy (MOM sector pages above): (sector, tier, skill,
# monthly S$, source key, effective_from). Skill R1 = Higher-skilled, R2 =
# Basic-skilled; ANY = the construction no-certification rate "regardless
# of their source country/region". MOM's published daily rates are NOT
# seeded — the engine derives them with MOM's own formula, and the tests
# prove the formula reproduces every published daily figure.
WP_LEVY = (
    ("SERVICES", "TIER_1", "R2", "450", "mom_wp_services", WP_EVIDENCED_FROM),
    ("SERVICES", "TIER_1", "R1", "300", "mom_wp_services", WP_EVIDENCED_FROM),
    ("SERVICES", "TIER_2", "R2", "600", "mom_wp_services", WP_EVIDENCED_FROM),
    ("SERVICES", "TIER_2", "R1", "400", "mom_wp_services", WP_EVIDENCED_FROM),
    ("SERVICES", "TIER_3", "R2", "800", "mom_wp_services", WP_EVIDENCED_FROM),
    ("SERVICES", "TIER_3", "R1", "600", "mom_wp_services", WP_EVIDENCED_FROM),
    ("MANUFACTURING", "TIER_1", "R2", "370", "mom_wp_manufacturing", WP_EVIDENCED_FROM),
    ("MANUFACTURING", "TIER_1", "R1", "250", "mom_wp_manufacturing", WP_EVIDENCED_FROM),
    ("MANUFACTURING", "TIER_2", "R2", "470", "mom_wp_manufacturing", WP_EVIDENCED_FROM),
    ("MANUFACTURING", "TIER_2", "R1", "350", "mom_wp_manufacturing", WP_EVIDENCED_FROM),
    ("MANUFACTURING", "TIER_3", "R2", "650", "mom_wp_manufacturing", WP_EVIDENCED_FROM),
    ("MANUFACTURING", "TIER_3", "R1", "550", "mom_wp_manufacturing", WP_EVIDENCED_FROM),
    ("CONSTRUCTION", "NTS", "R1", "500", "mom_wp_construction", WP_CONSTRUCTION_FROM),
    ("CONSTRUCTION", "NTS", "R2", "900", "mom_wp_construction", WP_CONSTRUCTION_FROM),
    ("CONSTRUCTION", "MYS_NAS_PRC", "R1", "300", "mom_wp_construction", WP_CONSTRUCTION_FROM),
    ("CONSTRUCTION", "MYS_NAS_PRC", "R2", "700", "mom_wp_construction", WP_CONSTRUCTION_FROM),
    ("CONSTRUCTION", "OFFSITE", "R1", "250", "mom_wp_construction", WP_CONSTRUCTION_FROM),
    ("CONSTRUCTION", "OFFSITE", "R2", "370", "mom_wp_construction", WP_CONSTRUCTION_FROM),
    ("CONSTRUCTION", "NO_CERT", "ANY", "900", "mom_wp_construction", WP_EVIDENCED_FROM),
    ("PROCESS", "NTS", "R1", "300", "mom_wp_process", WP_EVIDENCED_FROM),
    ("PROCESS", "NTS", "R2", "650", "mom_wp_process", WP_EVIDENCED_FROM),
    ("PROCESS", "MYS_NAS_PRC", "R1", "200", "mom_wp_process", WP_EVIDENCED_FROM),
    ("PROCESS", "MYS_NAS_PRC", "R2", "450", "mom_wp_process", WP_EVIDENCED_FROM),
    ("MARINE_SHIPYARD", "ALL", "R1", "350", "mom_wp_marine", WP_EVIDENCED_FROM),
    ("MARINE_SHIPYARD", "ALL", "R2", "500", "mom_wp_marine", WP_EVIDENCED_FROM),
)


# Employment Act rule rows (engine/jurisdictions/singapore/labour.py reads
# them; nothing is hard-coded there). (component_key, label, source key,
# kwargs) — same shape as RATES.
EA_RULES = (
    ("ea_part4_workman_basic_max", "Part 4 coverage: workman monthly basic salary up to (S$)", "mom_ea_coverage",
     dict(flat_amount="4500")),
    ("ea_part4_non_workman_basic_max", "Part 4 coverage: non-workman monthly basic salary up to (S$)", "mom_ea_coverage",
     dict(flat_amount="2600")),
    ("ea_overtime_rate_multiplier", "Overtime: at least this multiple of the hourly basic rate", "mom_ea_hours",
     dict(flat_amount="1.5")),
    ("ea_normal_weekly_hours", "Hourly basic rate divisor: 52 × this many hours (monthly-rated)", "mom_ea_hours",
     dict(flat_amount="44")),
    ("ea_overtime_non_workman_salary_cap", "Non-workman overtime rate capped at this salary level (S$)", "mom_ea_hours",
     dict(flat_amount="2600")),
    ("ea_overtime_non_workman_hourly_cap", "Non-workman overtime rate capped at this hourly rate (S$)", "mom_ea_hours",
     dict(flat_amount="13.60")),
    ("ea_overtime_max_hours_month", "Maximum overtime hours per month", "mom_ea_hours", dict(flat_amount="72")),
    ("ea_deduction_max_pct", "Total deductions may not exceed this share of the salary for the period", "mom_ea_deductions",
     dict(employer_rate_pct="0.50")),
    ("ea_damage_deduction_max_pct", "Damage/loss deduction may not exceed this share of one month's salary", "mom_ea_deductions",
     dict(employer_rate_pct="0.25")),
    ("ea_accommodation_amenities_max_pct", "Accommodation + amenities deductions may not exceed this share of the salary",
     "mom_ea_deductions", dict(employer_rate_pct="0.25")),
    ("ea_advance_instalment_max_pct", "Advance recovery: each instalment may not exceed this share of the salary",
     "mom_ea_deductions", dict(employer_rate_pct="0.25")),
    ("ea_advance_max_months", "Advance recovery spread over not more than this many months", "mom_ea_deductions",
     dict(flat_amount="12")),
    ("ea_loan_instalment_max_pct", "Loan recovery: each instalment may not exceed this share of the salary",
     "mom_ea_deductions", dict(employer_rate_pct="0.25")),
    ("ea_payslip_issue_working_days", "Itemised payslip: within this many working days of payment", "mom_ea_payslips",
     dict(flat_amount="3")),
    ("ea_leave_min_service_months", "Paid annual / sick leave after this many months of service", "mom_ea_annual_leave",
     dict(flat_amount="3")),
    *((f"ea_annual_leave_year_{y}", f"Annual leave — {'8th year and thereafter' if y == 8 else f'year {y} of service'} (days)",
       "mom_ea_annual_leave", dict(flat_amount=str(6 + y))) for y in range(1, 9)),
    *((f"ea_sick_leave_outpatient_month_{m}", f"Paid outpatient sick leave after {m}{'+' if m == 6 else ''} months (days)",
       "mom_ea_sick_leave", dict(flat_amount=str(d))) for m, d in ((3, 5), (4, 8), (5, 11), (6, 14))),
    *((f"ea_sick_leave_hospital_month_{m}", f"Paid hospitalisation leave after {m}{'+' if m == 6 else ''} months (days)",
       "mom_ea_sick_leave", dict(flat_amount=str(d))) for m, d in ((3, 15), (4, 30), (5, 45), (6, 60))),
    ("ea_public_holidays_per_year", "Paid public holidays per year", "mom_ea_public_holidays", dict(flat_amount="11")),
    ("fwl_payment_due_day", "Foreign worker levy: pay by this day of the following month (or the next working day)",
     "mom_fwl_pay", dict(flat_amount="17")),
)

# Progressive Wage Model monthly wage floors — full-time (35–44 h/week)
# employees, MOM sector pages (retrieved 2026-09-24). Only the windows that
# overlap 2026–2027 wage months are seeded. (sector, group, level, MOM job
# title, basis BASIC|GROSS, ((from, to, S$), ...), source key). GROSS =
# basic + allowances + productivity incentives, excluding overtime, bonus /
# AWS and reimbursements (MOM definition on the retail / food / waste /
# in-house security pages). "Left to market forces" levels have no floor.
def _jul(y):
    return (date(y, 7, 1), date(y + 1, 6, 30))


def _cal(y):
    return (date(y, 1, 1), date(y, 12, 31))


def _sep(y):
    return (date(y, 9, 1), date(y + 1, 8, 31))


def _windows(spans, amounts):
    return tuple((f, t, a) for (f, t), a in zip(spans, amounts))


_JUL_25_27 = (_jul(2025), _jul(2026), _jul(2027))
_FNB = ((date(2025, 3, 1), date(2026, 6, 30)), _jul(2026), _jul(2027))
# Waste management PWM "OT Rate of Pay" (MOM wage ladder PDF, retrieved
# 2026-09-25): the minimum hourly overtime pay per job level, effective 1 July
# of each year — windows aligned with the waste gross-wage rows below.
PWM_WASTE_OT_RATES = tuple(
    (g, lvl, title, _windows(_JUL_25_27, amts)) for g, lvl, title, amts in (
        ("COLLECTION", "CREW", "Crew", ("19.90", "21.56", "23.21")),
        ("COLLECTION", "SENIOR_CREW", "Senior Crew", ("21.48", "23.13", "24.78")),
        ("COLLECTION", "TEAM_LEAD", "Team lead", ("23.05", "24.70", "26.35")),
        ("COLLECTION", "SUPERVISOR", "Supervisor", ("25.02", "26.67", "28.32")),
        ("COLLECTION", "DRIVER", "Driver", ("22.26", "23.92", "25.57")),
        ("COLLECTION", "HOOKLIFT_DRIVER", "Hooklift driver", ("23.05", "24.70", "26.35")),
        ("COLLECTION", "SENIOR_DRIVER", "Senior driver", ("24.62", "26.28", "27.93")),
        ("MRF", "SORTER", "Sorter", ("19.12", "20.77", "22.42")),
        ("MRF", "SENIOR_SORTER_OPERATOR", "Senior sorter / Machine operator", ("20.69", "22.34", "23.99")),
        ("MRF", "TEAM_LEAD", "Team Lead", ("22.26", "23.92", "25.57")),
        ("MRF", "PLANT_SUPERVISOR", "Plant supervisor", ("23.84", "25.49", "27.14")),
    ))
PWM_FLOORS = (
    # Cleaning (basic wage) — Group 1 office/commercial, Group 2 F&B, Group 3 conservancy, in-house.
    *(("CLEANING", g, lvl, title, "BASIC", _windows(_JUL_25_27, amts), "mom_pwm_cleaning") for g, lvl, title, amts in (
        ("G1", "SUPERVISOR", "Supervisor", ("2700", "2870", "3040")),
        ("G1", "MULTI_SKILLED", "Multi-skilled Cleaner / Machine Operator", ("2530", "2700", "2870")),
        ("G1", "OUTDOOR_HEALTH_RESTROOM", "Outdoor / Healthcare / Restroom Cleaner", ("2325", "2495", "2665")),
        ("G1", "GENERAL_INDOOR", "General / Indoor Cleaner", ("1910", "2080", "2250")),
        ("G2", "SUPERVISOR", "Supervisor", ("2700", "2870", "3040")),
        ("G2", "MULTI_SKILLED", "Multi-skilled Cleaner / Machine Operator", ("2530", "2700", "2870")),
        ("G2", "DISHWASHER_RESTROOM_REFUSE", "Dishwasher / Restroom Cleaner / Refuse Collector", ("2325", "2495", "2665")),
        ("G2", "TABLE_TOP", "Table-top Cleaner", ("2010", "2180", "2350")),
        ("G2", "GENERAL", "General Cleaner", ("1910", "2080", "2250")),
        ("G3", "TRUCK_DRIVER", "Truck Driver (Class 4/5)", ("2830", "3040", "3250")),
        ("G3", "SUPERVISOR_MECH_DRIVER", "Supervisor / Mechanical Driver (Class 3)", ("2700", "2870", "3040")),
        ("G3", "MULTI_SKILLED_REFUSE", "Multi-skilled Cleaner / Machine Operator / Refuse Collector", ("2530", "2700", "2870")),
        ("G3", "GENERAL_RESTROOM", "General Cleaner / Restroom Cleaner", ("2325", "2495", "2665")),
        ("INHOUSE", "SUPERVISOR_MECH_DRIVER", "Supervisor / Mechanical Driver", ("2700", "2870", "3040")),
        ("INHOUSE", "MULTI_SKILLED", "Multi-skilled Cleaner / Machine Operator", ("2530", "2700", "2870")),
        ("INHOUSE", "OUTDOOR_HEALTH_RESTROOM", "Outdoor / Healthcare / Restroom / Dishwasher / Refuse Collector (F&B)",
         ("2325", "2495", "2665")),
        ("INHOUSE", "TABLE_TOP", "Table-top Cleaner (F&B)", ("2010", "2180", "2350")),
        ("INHOUSE", "GENERAL_INDOOR", "General / Indoor Cleaner", ("1910", "2080", "2250")),
    )),
    # Security — outsourced full-time (basic wage), in-house full-time (gross wage excl. overtime); calendar years.
    *(("SECURITY", "OUTSOURCED", lvl, title, "BASIC", _windows((_cal(2026), _cal(2027)), amts), "mom_pwm_security")
      for lvl, title, amts in (
          ("SENIOR_SUPERVISOR", "Senior security supervisor", ("3990", "4210")),
          ("SUPERVISOR", "Security supervisor", ("3690", "3910")),
          ("SENIOR_OFFICER", "Senior security officer", ("3390", "3610")),
          ("OFFICER", "Security officer", ("3090", "3310")))),
    *(("SECURITY", "INHOUSE", lvl, title, "GROSS", _windows((_cal(2026), _cal(2027)), amts), "mom_pwm_security")
      for lvl, title, amts in (
          ("SUPERVISOR", "Security supervisor", ("2905", "3065")),
          ("SENIOR_OFFICER", "Senior security officer", ("2675", "2835")),
          ("OFFICER", "Security officer", ("2475", "2635")))),
    # Landscape (basic wage).
    *(("LANDSCAPE", "ALL", lvl, title, "BASIC", _windows(_JUL_25_27, amts), "mom_pwm_landscape") for lvl, title, amts in (
        ("SUPERVISOR", "Landscape supervisor / Senior Landscape Specialist", ("2900", "3060", "3220")),
        ("ASSISTANT_SUPERVISOR", "Assistant landscape supervisor / Landscape Specialist", ("2545", "2685", "2825")),
        ("TECHNICIAN", "Landscape technician", ("2330", "2490", "2650")),
        ("WORKER", "Landscape worker", ("1950", "2095", "2240")))),
    # Lift and escalator (basic wage).
    *(("LIFT_ESCALATOR", "ALL", lvl, title, "BASIC", _windows(_JUL_25_27, amts), "mom_pwm_lift_escalator") for lvl, title, amts in (
        ("PRINCIPAL_SPECIALIST", "Principal lift and escalator (L&E) Specialist", ("3590", "3720", "3935")),
        ("SUPERVISOR", "L&E Supervisor", ("3445", "3660", "3875")),
        ("SENIOR_SPECIALIST", "Senior L&E Specialist", ("3215", "3420", "3620")),
        ("SPECIALIST", "L&E Specialist", ("2880", "3090", "3280")),
        ("ASSISTANT_SPECIALIST", "Assistant lift and escalator Specialist", ("2525", "2750", "2915")))),
    # Retail (gross wage excl. overtime; September windows).
    *(("RETAIL", "ALL", lvl, title, "GROSS", _windows((_sep(2025), _sep(2026), _sep(2027)), amts), "mom_pwm_retail")
      for lvl, title, amts in (
          ("ASSISTANT_SUPERVISOR", "Assistant retail supervisor", ("2790", "2950", "3100")),
          ("SENIOR_CASHIER_ASSISTANT", "Senior cashier / Senior retail assistant", ("2535", "2680", "2820")),
          ("ASSISTANT_CASHIER", "Retail assistant / Cashier", ("2305", "2435", "2565")))),
    # Food services (gross wage excl. overtime).
    *(("FOOD_SERVICES", g, lvl, title, "GROSS", _windows(_FNB, amts), "mom_pwm_food_services") for g, lvl, title, amts in (
        ("A_QUICK", "COOK", "Cook (QS)", ("2330", "2470", "2610")),
        ("A_QUICK", "KITCHEN_COUNTER", "Kitchen assistant (QS) / Food service counter attendant", ("2155", "2295", "2435")),
        ("A_QUICK", "STALL_ASSISTANT", "Food / drink stall assistant", ("2080", "2220", "2360")),
        ("B_KITCHEN", "COOK", "Cook (FS)", ("2380", "2520", "2660")),
        ("B_KITCHEN", "KITCHEN_ASSISTANT", "Kitchen assistant (FS)", ("2180", "2320", "2460")),
        ("B_WAITER", "WAITER_SUPERVISOR", "Waiter Supervisor", ("2730", "2875", "3020")),
        ("B_WAITER", "WAITER", "Waiter", ("2180", "2320", "2460")))),
    # Occupational PWs (MOM OPW page, 1 Sep 2026): monthly gross wage excl.
    # overtime for full-time administrators and drivers (35–44 h/week).
    *(("OPW_ADMIN", "ALL", lvl, title, "GROSS", _windows((_jul(2024), _jul(2025), _jul(2026), _jul(2027)), amts),
       "mom_opw") for lvl, title, amts in (
          ("SUPERVISOR", "Administrative supervisor", ("2980", "3160", "3340", "3520")),
          ("EXECUTIVE", "Administrative executive", ("2390", "2580", "2760", "2940")),
          ("ASSISTANT", "Administrative assistant", ("1800", "1980", "2170", "2360")))),
    *(("OPW_DRIVER", "ALL", lvl, title, "GROSS", _windows(((date(2023, 3, 1), date(2024, 6, 30)), _jul(2024), _jul(2025)), amts),
       "mom_opw") for lvl, title, amts in (
          ("SPECIALISED_DRIVER", "Specialised driver (before 1 Jul 2026)", ("1850", "2085", "2320")),
          ("GENERAL_DRIVER", "General driver (before 1 Jul 2026)", ("1750", "1970", "2190")))),
    *(("OPW_DRIVER", g, lvl, title, "GROSS", _windows((_jul(2026), _jul(2027)), amts), "mom_opw") for g, lvl, title, amts in (
        ("GROUP_A", "LEVEL_2", "Group A (Class 3 or below) Level 2 driver", ("2485", "2665")),
        ("GROUP_A", "LEVEL_1", "Group A (Class 3 or below) Level 1 driver", ("2370", "2550")),
        ("GROUP_B", "LEVEL_2", "Group B (Class 4 or above) Level 2 driver", ("2555", "2790")),
        ("GROUP_B", "LEVEL_1", "Group B (Class 4 or above) Level 1 driver", ("2505", "2690")))),
    # Waste management (gross wage excl. overtime) — collection and materials recovery (MRF).
    *(("WASTE_MANAGEMENT", g, lvl, title, "GROSS", _windows(_JUL_25_27, amts), "mom_pwm_waste") for g, lvl, title, amts in (
        ("COLLECTION", "SENIOR_DRIVER", "Senior driver", ("3330", "3540", "3750")),
        ("COLLECTION", "HOOKLIFT_DRIVER", "Hooklift driver", ("3130", "3340", "3550")),
        ("COLLECTION", "DRIVER", "Driver", ("3030", "3240", "3450")),
        ("COLLECTION", "SUPERVISOR", "Supervisor", ("3280", "3490", "3700")),
        ("COLLECTION", "TEAM_LEAD", "Team lead", ("3030", "3240", "3450")),
        ("COLLECTION", "SENIOR_CREW", "Senior Crew", ("2830", "3040", "3250")),
        ("COLLECTION", "CREW", "Crew", ("2630", "2840", "3050")),
        ("MRF", "PLANT_SUPERVISOR", "Plant supervisor", ("3130", "3340", "3550")),
        ("MRF", "TEAM_LEAD", "Team Lead", ("2930", "3140", "3350")),
        ("MRF", "SENIOR_SORTER_OPERATOR", "Senior sorter / Machine operator", ("2730", "2940", "3150")),
        ("MRF", "SORTER", "Sorter", ("2530", "2740", "2950")))),
)


# CPF Board rate tables from 1 Jan 2026 — per age band:
# (employer % for > $50–500, phase-in factor for > $500–750,
#  total % for > $750, employee % for > $750). Employer % above $750 is
# total − employee and must equal the > $50–500 employer % (asserted).
_ABOVE_65 = ("AGE_65_70", "AGE_GT_70")  # Tables 2/3 publish one "Above 65" group
CPF_TABLES = {
    # Table 1 — Singapore Citizens / SPR 3rd year onwards. Also the F/F
    # rates for 1st/2nd-year SPRs (Tables 4/5 notes: "refer to Table 1").
    "SC_SPR3": {
        "AGE_LE_55": ("17", "0.6", "37", "20"), "AGE_55_60": ("16", "0.54", "34", "18"),
        "AGE_60_65": ("12.5", "0.375", "25", "12.5"), "AGE_65_70": ("9", "0.225", "16.5", "7.5"),
        "AGE_GT_70": ("7.5", "0.15", "12.5", "5"),
    },
    # Table 2 — SPR 1st year, graduated (G/G).
    "SPR1_GG": {
        "AGE_LE_55": ("4", "0.15", "9", "5"), "AGE_55_60": ("4", "0.15", "9", "5"),
        "AGE_60_65": ("3.5", "0.15", "8.5", "5"), **{b: ("3.5", "0.15", "8.5", "5") for b in _ABOVE_65},
    },
    # Table 3 — SPR 2nd year, graduated (G/G).
    "SPR2_GG": {
        "AGE_LE_55": ("9", "0.45", "24", "15"), "AGE_55_60": ("6", "0.375", "18.5", "12.5"),
        "AGE_60_65": ("3.5", "0.225", "11", "7.5"), **{b: ("3.5", "0.15", "8.5", "5") for b in _ABOVE_65},
    },
    # Table 4 — SPR 1st year, full employer & graduated employee (F/G).
    "SPR1_FG": {
        "AGE_LE_55": ("17", "0.15", "22", "5"), "AGE_55_60": ("16", "0.15", "21", "5"),
        "AGE_60_65": ("12.5", "0.15", "17.5", "5"), "AGE_65_70": ("9", "0.15", "14", "5"),
        "AGE_GT_70": ("7.5", "0.15", "12.5", "5"),
    },
    # Table 5 — SPR 2nd year, full employer & graduated employee (F/G).
    "SPR2_FG": {
        "AGE_LE_55": ("17", "0.45", "32", "15"), "AGE_55_60": ("16", "0.375", "28.5", "12.5"),
        "AGE_60_65": ("12.5", "0.225", "20", "7.5"), "AGE_65_70": ("9", "0.15", "14", "5"),
        "AGE_GT_70": ("7.5", "0.15", "12.5", "5"),
    },
}
CPF_TABLES["SPR1_FF"] = CPF_TABLES["SC_SPR3"]
CPF_TABLES["SPR2_FF"] = CPF_TABLES["SC_SPR3"]
# CPF Board "CPF Contribution Rate Table from 1 January 2027" (Tables 1–5,
# retrieved 2026-09-24, sha256 16ac89e7…) — same shape as CPF_TABLES. The
# 1 Jan 2027 change raises the above-55-to-65 rates (CPF Board: "There are no
# changes to the graduated contribution rates for first and second year
# SPRs"); Tables 4/5 F/G carry the new full employer rates. F/F = Table 1.
CPF_TABLES_2027 = {
    "SC_SPR3": {
        "AGE_LE_55": ("17", "0.6", "37", "20"), "AGE_55_60": ("16.5", "0.57", "35.5", "19"),
        "AGE_60_65": ("13", "0.39", "26", "13"), "AGE_65_70": ("9", "0.225", "16.5", "7.5"),
        "AGE_GT_70": ("7.5", "0.15", "12.5", "5"),
    },
    "SPR1_GG": {
        "AGE_LE_55": ("4", "0.15", "9", "5"), "AGE_55_60": ("4", "0.15", "9", "5"),
        "AGE_60_65": ("3.5", "0.15", "8.5", "5"), **{b: ("3.5", "0.15", "8.5", "5") for b in _ABOVE_65},
    },
    "SPR2_GG": {
        "AGE_LE_55": ("9", "0.45", "24", "15"), "AGE_55_60": ("6", "0.375", "18.5", "12.5"),
        "AGE_60_65": ("3.5", "0.225", "11", "7.5"), **{b: ("3.5", "0.15", "8.5", "5") for b in _ABOVE_65},
    },
    "SPR1_FG": {
        "AGE_LE_55": ("17", "0.15", "22", "5"), "AGE_55_60": ("16.5", "0.15", "21.5", "5"),
        "AGE_60_65": ("13", "0.15", "18", "5"), "AGE_65_70": ("9", "0.15", "14", "5"),
        "AGE_GT_70": ("7.5", "0.15", "12.5", "5"),
    },
    "SPR2_FG": {
        "AGE_LE_55": ("17", "0.45", "32", "15"), "AGE_55_60": ("16.5", "0.375", "29", "12.5"),
        "AGE_60_65": ("13", "0.225", "20.5", "7.5"), "AGE_65_70": ("9", "0.15", "14", "5"),
        "AGE_GT_70": ("7.5", "0.15", "12.5", "5"),
    },
}
CPF_TABLES_2027["SPR1_FF"] = CPF_TABLES_2027["SC_SPR3"]
CPF_TABLES_2027["SPR2_FF"] = CPF_TABLES_2027["SC_SPR3"]

CPF_TABLE_NAMES = {"SC_SPR3": "Table 1", "SPR1_FF": "Table 1", "SPR2_FF": "Table 1",
                   "SPR1_GG": "Table 2", "SPR2_GG": "Table 3", "SPR1_FG": "Table 4", "SPR2_FG": "Table 5"}

# Backward-compatible view (SC/SPR3+ full-rate rows) — (age band, employee %, employer %).
CPF_FULL_RATES_SC_SPR3 = tuple(
    (band, ee, format((Decimal(total) - Decimal(ee)).normalize(), "f"))
    for band, (_er, _f, total, ee) in CPF_TABLES["SC_SPR3"].items()
)

# CPF Board SHG page — (upper bound of monthly total wages or None, monthly
# contribution S$). Identical to ZP-SG-ENG-001 §5.
SHG_BANDS = {
    "CDAC": ((2000, "0.50"), (3500, "1"), (5000, "1.50"), (7500, "2"), (None, "3")),
    "ECF": ((1000, "2"), (1500, "4"), (2500, "6"), (4000, "9"), (7000, "12"), (10000, "16"), (None, "20")),
    "MBMF": ((1000, "3"), (2000, "4.50"), (3000, "6.50"), (4000, "15"), (6000, "19.50"), (8000, "22"),
             (10000, "24"), (None, "26")),
    "SINDA": ((1000, "1"), (1500, "3"), (2500, "5"), (4500, "7"), (7500, "9"), (10000, "12"), (15000, "18"),
              (None, "30")),
}

# (component_key, label, source key or None = specification only, kwargs).
# ContributionRate percentages are FRACTIONS (0.0025 = 0.25%).
RATES = (
    ("cpf_ow_ceiling_monthly", "CPF Ordinary Wage ceiling (monthly)", "cpf_rate_tables", dict(flat_amount="8000")),
    ("cpf_annual_wage_ceiling", "CPF annual wage ceiling (AW ceiling = this − total OW subject to CPF for the year)",
     "cpf_what_payments", dict(flat_amount="102000")),
    ("cpf_age_band_semantics", "CPF age-group change: from the first day of the month after the 55th/60th/65th/70th birthday",
     "cpf_how_much", dict(text_value="MONTH_AFTER_BIRTHDAY")),
    ("cpf_enforcement_day_following_month", "CPF enforcement: unpaid after this day of the following month", "cpf_enforcement",
     dict(flat_amount="14")),
    ("sdl", "Skills Development Levy (employer cost)", "cpf_sdl", dict(employer_rate_pct="0.0025")),
    ("sdl_min_monthly", "SDL minimum per employee (monthly)", "cpf_sdl", dict(flat_amount="2")),
    ("sdl_max_monthly", "SDL maximum per employee (monthly)", "cpf_sdl", dict(flat_amount="11.25")),
    ("fwl_s_pass_monthly", "Foreign Worker Levy — S Pass (monthly, employer cost)", "mom_spass_levy",
     dict(flat_amount="650")),
    # MOM cancellation pages: "When levy stops: 1 day before cancellation" —
    # the cancellation day is NOT levied. Expiry has no published rule.
    ("fwl_s_pass_cancellation_end_day_basis", "S Pass levy end day on CANCELLATION (levy stops 1 day before)",
     "mom_spass_cancel", dict(text_value="EXCLUSIVE")),
    ("fwl_work_permit_cancellation_end_day_basis", "Work Permit levy end day on CANCELLATION (levy stops 1 day before)",
     "mom_wp_cancel", dict(text_value="EXCLUSIVE")),
    ("lqs_full_time_monthly", "Local Qualifying Salary — full-time (monthly)", "mom_lqs_factsheet",
     dict(flat_amount="1600", effective_from=EFFECTIVE_FROM, effective_to=date(2026, 6, 30))),
    ("lqs_full_time_monthly", "Local Qualifying Salary — full-time (monthly)", "mom_lqs_factsheet",
     dict(flat_amount="1800", effective_from=LQS_CHANGE)),
    # MOM COS 2024 factsheet: "At least $10.50 per hour for part-time local
    # workers … implemented from 1 July 2024" — in force for Jan–Jun 2026.
    ("lqs_part_time_hourly", "Local Qualifying Salary — part-time (hourly)", "mom_cos2024_foreign_workforce",
     dict(flat_amount="10.50", effective_from=EFFECTIVE_FROM, effective_to=LQS_CHANGE - timedelta(days=1))),
    ("lqs_part_time_hourly", "Local Qualifying Salary — part-time (hourly)", "mom_lqs",
     dict(flat_amount="10.50", effective_from=LQS_CHANGE)),
    ("ais_mandatory_employee_threshold", "IRAS AIS mandatory threshold (employees)", "iras_ais", dict(flat_amount="5")),
    # Record-retention MINIMUMS (SG-046 retention report; nothing is deleted):
    # MOM — employment / salary records "For current employees: Latest two
    # years. For ex-employees: Last two years, to be kept for one year after
    # the employee leaves employment"; IRAS — company records "for at least 5
    # years from the relevant Year of Assessment".
    ("retention_mom_records_years", "MOM employment records — latest years kept", "mom_employment_records",
     dict(flat_amount="2")),
    ("retention_mom_after_leaving_years", "MOM employment records — years kept after leaving", "mom_employment_records",
     dict(flat_amount="1")),
    ("retention_iras_years_from_ya", "IRAS business records — minimum years from the relevant YA", "iras_record_keeping",
     dict(flat_amount="5")),
    ("ais_submission_mode", "IRAS AIS submission mode", None, dict(text_value="EXPORT_ONLY")),
    ("salary_payment_deadline_days", "Salary payment deadline (days after salary period)", "mom_ea_paying_salary",
     dict(flat_amount="7")),
    ("overtime_payment_deadline_days", "Overtime payment deadline (days after salary period)", "mom_ea_paying_salary",
     dict(flat_amount="14")),
    ("ir21_departure_trigger_months", "IR21 trigger: departure longer than (months)", "iras_ir21", dict(flat_amount="3")),
    ("ir21_filing_lead_months", "IR21 filing: at least (months) before cessation/departure", "iras_ir21",
     dict(flat_amount="1")),
)


def _dec(value):
    return Decimal(str(value)) if value is not None else None


def _display_pct(fraction):
    return f"{(fraction * 100).normalize()}%" if fraction is not None else "—"


def _upsert_sources(db) -> dict:
    """One SourceArtifact per official document, matched by URL + hash so a
    re-run never duplicates and a changed document becomes a NEW artifact
    (never an edit of what was actually retrieved). Unreviewed: an
    independent reviewer must still mark each one reviewed."""
    ids = {}
    for key, (agency, title, url, sha256, published) in SOURCES.items():
        row = (
            db.query(SourceArtifact)
            .filter(SourceArtifact.source_url == url, SourceArtifact.checksum_sha256 == sha256)
            .first()
        )
        if row is None:
            row = SourceArtifact(
                agency=agency, title=title, source_url=url, checksum_sha256=sha256,
                publication_date=published,
                retrieved_at=(RETRIEVED_AT_CLOSURE if key in CLOSURE_SOURCE_KEYS
                              else RETRIEVED_AT_PHASE53 if key in LATER_SOURCE_KEYS
                              else RETRIEVED_AT_PHASE5 if key in PHASE5_SOURCE_KEYS else RETRIEVED_AT),
            )
            db.add(row)
            db.flush()
        ids[key] = row.id
    return ids


def _spec_2026():
    return {"pack_id": PACK_ID, "version": PACK_VERSION, "previous_version": PREVIOUS_VERSION,
            "effective_from": EFFECTIVE_FROM, "effective_to": EFFECTIVE_TO, "tax_year": TAX_YEAR, "cpf_tables": CPF_TABLES,
            "cpf_source": "cpf_rate_tables", "cpf_year": "2026", "summary": None}


def _spec_2027():
    return {"pack_id": "SG-PAYROLL-2027", "version": "1.0", "previous_version": None,
            "effective_from": date(2027, 1, 1), "effective_to": None, "tax_year": "2027", "cpf_tables": CPF_TABLES_2027,
            "cpf_source": "cpf_rate_tables_2027", "cpf_year": "2027",
            "summary": ("v1.0 — CPF Board contribution rate tables from 1 January 2027 (Tables 1–5; senior rates raised "
                        "for ages above 55 to 65). Every other row (ceilings, SDL, SHG, levies, LQS, PWM, Employment "
                        "Act) is the same current, open-ended official value the 2026 pack carries — no 2027 change "
                        "is published for them.")}


def _upsert_pack(db, source_ids, spec=None):
    spec = spec or _spec_2026()
    pack_id, version = spec["pack_id"], spec["version"]
    pack = (
        db.query(JurisdictionPack)
        .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == version)
        .first()
    )
    if pack is not None and pack.status != "Draft":
        raise SystemExit(
            f"{pack_id} v{version} is {pack.status!r}, not Draft — refusing to rewrite a pack that has "
            "entered review/approval. Create a new version from Super Admin instead."
        )
    created = pack is None
    if created:
        previous = None
        if spec["previous_version"]:
            previous = (
                db.query(JurisdictionPack)
                .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == spec["previous_version"])
                .first()
            )
        pack = JurisdictionPack(pack_id=pack_id, jurisdiction_country=CODE, version=version,
                                previous_version_id=previous.id if previous else None)
        db.add(pack)
    pack.jurisdiction_state = None
    pack.pack_type = "tax"
    pack.status = "Draft"
    pack.effective_from = spec["effective_from"]
    pack.effective_to = spec.get("effective_to")
    pack.tax_year = spec["tax_year"]
    pack.currency = "SGD"
    pack.regulatory_authority = "CPF Board; IRAS; MOM"
    pack.compliance_category = "CPF / SDL / SHG / FWL / LQS / IRAS AIS / IR21"
    pack.compliance_owner = "Super Admin — Singapore build"
    pack.source_document_id = source_ids[spec["cpf_source"]]
    pack.change_summary = (
        f"v1.2 — Phase 5: MOM Work Permit levy (5 sectors), Progressive Wage Model floors, Employment Act evidence "
        "(salary deadlines, overtime, deductions), CPF EZPay spec; plus v1.1 — "
        f"{SPEC} and official CPF Board / IRAS / MOM sources retrieved 2026-09-23: full CPF rate tables "
        "(Tables 1–5: Citizens/SPR3+, SPR 1st/2nd year G/G and F/G, F/F = Table 1) incl. every low-wage row; "
        "age-group rule (month after birthday); OW/annual ceilings; SDL; SHG; S Pass levy; LQS (S$1,600 to "
        "30 Jun 2026, S$1,800 from 1 Jul 2026); AIS; IR21. AW ceiling per the CPF Board method (Option A). "
        "Still BLOCKED: Work Permit levy before 24 Sep 2026 outside construction; pass EXPIRY end-day basis "
        "(the CANCELLATION rule is sourced from MOM's cancellation pages)."
    )
    if spec["summary"]:
        pack.change_summary = spec["summary"]
    pack.source_references = (
        f"{SPEC}; " + "; ".join(f"{a} — {t} <{u}> sha256:{h}" for a, t, u, h, _p in SOURCES.values())
    )
    db.flush()

    # The existing canonical rows are NOT bulk-deleted any more (final
    # completion programme): the canonical rows are staged as before and
    # _reconcile_pack_rows keeps every existing row that already holds the
    # canonical values, so a re-run changes nothing.
    prior = {model: [i for (i,) in db.query(model.id).filter(model.jurisdiction_pack_id == pack.id,
                                                              model.organization_id.is_(None))]
             for model in (ContributionRate, TaxSlab)}
    return pack, created, prior


_ROW_BOOKKEEPING = {"id", "created_at", "updated_at"}


def _reconcile_pack_rows(db, pack, prior) -> dict:
    """Keep the pack's rows that already hold the canonical values; replace
    only the ones that differ. `prior` = the row ids present before this run
    staged the canonical rows. After a flush both sets are re-read from the
    database (one type / scale per column) and paired by every value column:
    a matched staged row is dropped again inside this transaction (the
    existing row is never touched — same id, no UPDATE), an unmatched staged
    row stays (insert), an unmatched existing row is deleted (it no longer
    matches the canonical values, e.g. an edit made to the Draft)."""
    db.flush()
    db.expire_all()
    changes = {}
    for model in (ContributionRate, TaxSlab):
        columns = [c.name for c in model.__table__.columns if c.name not in _ROW_BOOKKEEPING]
        old_ids = set(prior[model])
        rows = (db.query(model).filter(model.jurisdiction_pack_id == pack.id, model.organization_id.is_(None))
                .order_by(model.id).all())
        existing = {}
        for row in rows:
            if row.id in old_ids:
                existing.setdefault(tuple(getattr(row, c) for c in columns), []).append(row)
        inserted = 0
        for row in rows:
            if row.id in old_ids:
                continue
            match = existing.get(tuple(getattr(row, c) for c in columns))
            if match:
                match.pop(0)                     # identical existing row kept as-is
                db.delete(row)                   # the staged duplicate never persists
            else:
                inserted += 1
        deleted = 0
        for leftovers in existing.values():
            for row in leftovers:
                db.delete(row)
                deleted += 1
        changes[model.__tablename__] = {"inserted": inserted, "deleted": deleted}
    db.flush()
    return changes


def _add_rate(db, pack, sort_order, component_key, label, source_id, flat_amount=None, employer_rate_pct=None,
              text_value=None, effective_from=None, effective_to=None):
    if len(label) > 100:   # ContributionRate.label is String(100) — PostgreSQL enforces it, SQLite does not
        raise SystemExit(f"ContributionRate label longer than 100 characters: {label!r}")
    employer = _dec(employer_rate_pct)
    flat = _dec(flat_amount)
    display = str(flat) if flat is not None else (text_value or _display_pct(employer))
    db.add(ContributionRate(
        jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
        component_key=component_key, label=label,
        employee_share="—" if employer is not None else display,
        employer_share=_display_pct(employer) if employer is not None else "—",
        total=_display_pct(employer) if employer is not None else display,
        employer_rate_pct=employer, flat_amount=flat, text_value=text_value,
        effective_from=effective_from, effective_to=effective_to, sort_order=sort_order,
        source_document_id=source_id,
    ))


def _add_cpf_rows(db, pack, source_id, tables=None, year="2026") -> int:
    count = 0
    for cohort, bands in (tables or CPF_TABLES).items():
        table = CPF_TABLE_NAMES[cohort]
        for sort, (age_band, (er_low, factor, total, ee)) in enumerate(bands.items(), start=1):
            er_full = Decimal(total) - Decimal(ee)
            if er_full != Decimal(er_low):
                raise SystemExit(f"CPF {cohort}/{age_band}: employer {er_full}% (> $750) != {er_low}% (> $50–500) — table typo")
            factor_pct = Decimal(factor) * 100
            rows = (
                ("NIL", Decimal("0"), Decimal("50"), Decimal("0"), None, "Total wages ≤ S$50: no CPF"),
                ("ER_ONLY", Decimal("50"), Decimal("500"), Decimal("0"), Decimal(er_low),
                 f"> S$50–500: total {er_low}% (TW), employee nil"),
                ("PHASE_IN", Decimal("500"), Decimal("750"), factor_pct, Decimal(er_low),
                 f"> S$500–750: total {er_low}% (TW) + {factor} (TW − 500); employee {factor} (TW − 500)"),
                ("FULL", Decimal("750"), None, Decimal(ee), er_full,
                 f"> S$750: total {total}% / employee {ee}% of capped OW + subject AW"),
            )
            for i, (basis, lo, hi, rate_pct, er_pct, formula) in enumerate(rows):
                db.add(TaxSlab(
                    jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
                    rule_type="CPF_RATE_BAND", filing_status=cohort, tax_regime=age_band, assessment_basis=basis,
                    min_amount=lo, max_amount=hi, rate_pct=rate_pct, employer_rate_pct=er_pct,
                    rate_label=f"CPF-{year}-{cohort}-{age_band}-{basis}",
                    tax_formula=f"{table}: {formula}", sort_order=sort * 10 + i, source_document_id=source_id,
                ))
                count += 1
    return count


def _add_shg_rows(db, pack, source_id) -> int:
    count = 0
    for fund, bands in SHG_BANDS.items():
        lower = Decimal("0")
        for i, (upper, amount) in enumerate(bands, start=1):
            upper_dec = _dec(upper)
            band_text = (f"> S${lower:,.0f}" if lower else "") + (
                f"{' – ' if lower else '≤ '}S${upper_dec:,.0f}" if upper_dec is not None else ""
            )
            db.add(TaxSlab(
                jurisdiction_pack_id=pack.id, jurisdiction_country=CODE, organization_id=None,
                rule_type="SHG_FUND_BAND", filing_status=fund,
                min_amount=lower, max_amount=upper_dec, rate_pct=Decimal("0"), flat_amount=Decimal(amount),
                rate_label=f"SHG-2026-{fund}-B{i}", tax_formula=f"{band_text}: S${amount}/month",
                sort_order=i, source_document_id=source_id,
            ))
            lower = upper_dec if upper_dec is not None else lower
            count += 1
    return count


def _upsert_ais_filing_calendar(db, source_id):
    """2026 income → YA2027 AIS/IR8A submission due 1 March 2027."""
    row = (
        db.query(StatutoryFilingCalendar)
        .filter(
            StatutoryFilingCalendar.jurisdiction_country == CODE,
            StatutoryFilingCalendar.report_type == "IR8A",
            StatutoryFilingCalendar.reporting_year == TAX_YEAR,
            StatutoryFilingCalendar.period_key == "ANNUAL",
        )
        .first()
    )
    if row is not None and row.status != "Draft":
        return  # never rewrite a reviewed/approved calendar row
    if row is None:
        row = StatutoryFilingCalendar(
            jurisdiction_country=CODE, report_type="IR8A", reporting_year=TAX_YEAR, period_key="ANNUAL",
        )
        db.add(row)
    row.period_label = "YA2027 (2026 income) — AIS / IR8A, Appendix 8A/8B"
    row.due_date = date(2027, 3, 1)
    row.status = "Draft"
    row.source_document_id = source_id


PWM_OVERTIME_DATA = Path(__file__).with_name("sg_pwm_overtime_schedules.json")


def seed_pwm_overtime_schedules(db, source_ids) -> dict:
    """SG-018: MOM's "Total PWM Gross Wage Requirement" overtime tables
    (0–72 OT hours) into sgp_pwm_overtime_schedules — one row per published
    cell, from the data file extracted from the six retrieved MOM PDFs (each
    PDF's sha256 must equal its SourceArtifact's). Idempotent: an existing
    row is never rewritten; only missing rows are inserted."""
    from app.modules.payroll.models import SgpPwmOvertimeSchedule

    data = json.loads(PWM_OVERTIME_DATA.read_text(encoding="utf8"))
    existing = {
        (r.sector, r.occupation_group, r.job_level, r.effective_from, r.overtime_hours, r.source_document_id)
        for r in db.query(SgpPwmOvertimeSchedule.sector, SgpPwmOvertimeSchedule.occupation_group,
                          SgpPwmOvertimeSchedule.job_level, SgpPwmOvertimeSchedule.effective_from,
                          SgpPwmOvertimeSchedule.overtime_hours, SgpPwmOvertimeSchedule.source_document_id).all()
    }
    inserted = total = 0
    new_rows = []
    for sched in data["schedules"]:
        key = f"mom_{sched['source']}"
        if SOURCES[key][3] != sched["sha256"]:
            raise SystemExit(f"PWM overtime data {sched['source']}: sha256 differs from the registered source")
        source_id = source_ids[key]
        eff_from, eff_to = date.fromisoformat(sched["effective_from"]), date.fromisoformat(sched["effective_to"])
        for hours, amount in enumerate(sched["amounts"]):
            total += 1
            if (sched["sector"], sched["group"], sched["level"], eff_from, hours, source_id) in existing:
                continue
            new_rows.append(dict(
                jurisdiction_country=CODE, sector=sched["sector"], occupation_group=sched["group"],
                job_level=sched["level"], role_label=sched["role"], effective_from=eff_from, effective_to=eff_to,
                overtime_hours=hours, required_gross=Decimal(str(amount)), source_document_id=source_id,
                source_sha256=sched["sha256"], retrieved_at=RETRIEVED_AT_PHASE53, status="Active"))
            inserted += 1
    if new_rows:
        from sqlalchemy import insert

        db.execute(insert(SgpPwmOvertimeSchedule), new_rows)     # one executemany, not 6,132 ORM objects
    db.flush()
    return {"rows": total, "inserted": inserted, "schedules": len(data["schedules"])}


def _ensure_service_registry_row(db) -> str:
    """Singapore's jurisdiction_service_registry row, PLANNED, created only
    when missing — an existing row (whatever its availability) is never
    changed; the PLANNED -> AVAILABLE step belongs to the owner. The shared
    seed_jurisdiction_service_registry overwrites every country's row, so it is
    not the tool for a production database."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "SG").first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country="SG", availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


def seed_singapore(db, spec=None) -> JurisdictionPack:
    from app.modules.payroll.service import record_tax_audit

    spec = spec or _spec_2026()
    source_ids = _upsert_sources(db)
    pack, created, prior = _upsert_pack(db, source_ids, spec)
    for i, (component_key, label, source_key, kwargs) in enumerate(RATES, start=1):
        _add_rate(db, pack, i, component_key, label, source_ids.get(source_key), **kwargs)
    for j, (sector, tier, skill, monthly, source_key, effective_from) in enumerate(WP_LEVY, start=len(RATES) + 1):
        _add_rate(db, pack, j, work_permit_levy_key(sector, tier, skill),
                  f"Foreign Worker Levy — Work Permit, {sector.replace('_', ' ').title()} {tier} {skill} (monthly, employer cost)",
                  source_ids[source_key], flat_amount=monthly, effective_from=effective_from)
    j = len(RATES) + len(WP_LEVY)
    for component_key, label, source_key, kwargs in EA_RULES:
        j += 1
        _add_rate(db, pack, j, component_key, label, source_ids[source_key], **kwargs)
    for sector, group, level, title, basis, windows, source_key in PWM_FLOORS:
        key = pwm_key(sector, group, level)
        if len(key) > 50:
            raise SystemExit(f"PWM component key too long: {key}")
        for eff_from, eff_to, amount in windows:
            j += 1
            _add_rate(db, pack, j, key, f"PWM {sector.replace('_', ' ').title()} — {title} ({basis.lower()} wage)",
                      source_ids[source_key], flat_amount=amount, text_value=basis,
                      effective_from=eff_from, effective_to=eff_to)
    for group, level, title, windows in PWM_WASTE_OT_RATES:
        key = pwm_overtime_rate_key("WASTE_MANAGEMENT", group, level)
        if len(key) > 50:
            raise SystemExit(f"PWM overtime-rate component key too long: {key}")
        for eff_from, eff_to, amount in windows:
            j += 1
            _add_rate(db, pack, j, key, f"PWM waste management — {title} (overtime rate of pay per hour)",
                      source_ids["mom_pwm_waste_ot"], flat_amount=amount, effective_from=eff_from, effective_to=eff_to)
    cpf_rows = _add_cpf_rows(db, pack, source_ids[spec["cpf_source"]], spec["cpf_tables"], spec["cpf_year"])
    shg_rows = _add_shg_rows(db, pack, source_ids["cpf_shg"])
    row_changes = _reconcile_pack_rows(db, pack, prior)
    _ensure_service_registry_row(db)
    if spec["tax_year"] == TAX_YEAR:
        _upsert_ais_filing_calendar(db, source_ids["iras_ais"])   # YA2027; YA2028 not yet published
        pwm_ot = seed_pwm_overtime_schedules(db, source_ids)
    else:
        pwm_ot = {"rows": 0, "inserted": 0, "schedules": 0}
    db.flush()
    record_tax_audit(
        db, actor_id=None, action="create" if created else "update", entity_type="jurisdiction_pack",
        entity_id=pack.id, jurisdiction_pack_id=pack.id, tax_version=pack.version,
        legal_reference=SPEC,
        old_value=None,
        new_value={
            "status": pack.status, "previousVersionId": str(pack.previous_version_id),
            "contributionRates": str(len(RATES) + len(WP_LEVY) + len(EA_RULES) + sum(len(w[5]) for w in PWM_FLOORS)
                                     + sum(len(w[3]) for w in PWM_WASTE_OT_RATES)),
            "cpfRateBands": str(cpf_rows), "shgBands": str(shg_rows),
            "pwmOvertimeRows": str(pwm_ot["rows"]), "pwmOvertimeInserted": str(pwm_ot["inserted"]),
            "sourceArtifacts": str(len(source_ids)),
            "rowChanges": row_changes,
        },
        reason=f"Canonical Singapore pack {spec['pack_id']} v{spec['version']} seeded from {SPEC} + official CPF Board/IRAS/MOM sources "
               "(scripts/seed_singapore_canonical_pack.py) — Draft.",
        auto_commit=False,
    )
    return pack


def seed_singapore_2027(db) -> JurisdictionPack:
    """SG-PAYROLL-2027 v1.0 (Draft) — the 1 Jan 2027 CPF tables."""
    return seed_singapore(db, _spec_2027())


def main() -> None:
    assert_local_database("seed_singapore_canonical_pack")
    initialize_database()
    db = SessionLocal()
    try:
        pack = seed_singapore(db)
        pack27 = seed_singapore_2027(db)
        db.commit()
        print(f"Seeded {PACK_ID} v{PACK_VERSION} (id={pack.id}) and {pack27.pack_id} v{pack27.version} "
              f"(id={pack27.id}) as Draft.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
