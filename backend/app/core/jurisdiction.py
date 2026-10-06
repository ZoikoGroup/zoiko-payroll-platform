"""
core/jurisdiction.py
--------------------
Single source of truth for jurisdiction-aware business registration and tax
identification fields. Used by:

  - Auth registration (app/modules/auth/service.py)  → validates + persists
    the tax IDs submitted on the Register Page.
  - Company Compliance sync (app/modules/payroll/service.py) → backfills /
    overrides tax IDs on the Compliance Details row without duplicating them.
  - The API schema endpoint (app/modules/organizations/router.py) → lets the
    frontend render the exact same fields/patterns without hardcoding.

Every supported jurisdiction declares a small set of tax/registration
identifiers. The "primary" identifier (primary=True) is the one mirrored into
the legacy Organization.tax_no / CompanyComplianceDetails.tax_no columns so
existing payroll footers / reports keep working unchanged.
"""

from typing import Optional

# Countries available on the public registration forms. Mirrors the frontend
# dropdown (frontend/src/utils/registrationRegions.js). Both registration
# flows gate on this allow-list: /auth/register (production, additionally
# requires an Active canonical compliance pack) and /auth/register-trial
# (30-day evaluation, no compliance-pack requirement).
REGISTRATION_COUNTRIES = [
    "India",
    "Germany",
    "Canada",
    "United States",
    "United Kingdom",
    "Australia",
    # Caribbean production jurisdictions (Wave A + adjacent T1), added
    # 2026-09-21 — each has its own JURISDICTION_TAX_SCHEMAS entry below
    # and a dedicated engine/countries/*.py calculator wired into
    # engine/standard.py's _COUNTRY_CALC. The ~25 other Caribbean
    # jurisdictions (Coming Soon) are deliberately NOT listed here — see
    # app/core/caribbean_regions.py, which is the master for those and is
    # never consulted by registration/onboarding.
    "Barbados",
    "Cayman Islands",
    "Dominican Republic",
    "Guyana",
    "Jamaica",
    "Bahamas",
    "Trinidad and Tobago",
    # Puerto Rico (2026-09-23) — dual-jurisdiction (local Hacienda + an
    # independently-computed federal-equivalent layer), architecturally a
    # sibling of the 7 Caribbean entries above, not a US-dependent variant.
    # See engine/countries/puerto_rico.py's own module docstring.
    "Puerto Rico",
    # France (2026-09-24, ZP-FR-ENG-001) — Europe expansion, launch slot #10,
    # metropolitan private-sector wedge. SIREN/SIRET establishment-aware
    # collection keys; engine/countries/france.py wired into _COUNTRY_CALC.
    "France",
    "Ireland",
    # Sweden (ZP-SE-ENG-001) — effective-dated country package, priority
    # market #24. Applicability-first resolution (tax status → tax table/
    # column → social insurance → age cohort → payment date → income type →
    # CBA/plan → reporting period) in engine/countries/sweden.py; Draft packs
    # SE-PAYROLL-2026/2027 seeded by scripts/seed_sweden_canonical_packs.py. Production
    # registration still requires an Active canonical compliance pack, which
    # in turn requires the §16/§37 readiness gates (evidence, certification,
    # four-eyes) — adding the name here never activates Sweden by itself.
    "Sweden",
]

# Keyed by the 2-letter code the rest of the payroll module uses
# ("IN"/"US"/"UK"/"DE"/"AU"). Matches REGISTRATION_COUNTRIES / payroll
# COMPLIANCE_COUNTRIES so a country name and a code always resolve the same.
JURISDICTION_TAX_SCHEMAS = {
    "IN": {
        "label": "GSTIN / PAN / CIN",
        "currency": "INR",
        "fields": [
            {
                "key": "gstin",
                "label": "GSTIN",
                "pattern": r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$",
                "example": "36AAACI1234F1Z9",
                "primary": True,
            },
            {
                "key": "pan",
                "label": "PAN",
                "pattern": r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$",
                "example": "AAACI1234F",
                "primary": False,
            },
            {
                "key": "cin",
                "label": "CIN",
                "pattern": r"^[L|U][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$",
                "example": "U72200TG2020PTC123456",
                "primary": False,
            },
        ],
    },
    "US": {
        "label": "EIN / State Tax ID",
        "currency": "USD",
        "fields": [
            {
                "key": "ein",
                "label": "EIN",
                "pattern": r"^\d{2}-\d{7}$",
                "example": "84-1234567",
                "primary": True,
            },
            {
                "key": "state_tax_id",
                "label": "State Tax ID",
                "pattern": r"^\d{2,15}$",
                "example": "123456789",
                "primary": False,
            },
        ],
    },
    "UK": {
        "label": "Company Registration Number (CRN) / VAT",
        "currency": "GBP",
        "fields": [
            {
                "key": "crn",
                "label": "Company Registration Number (CRN)",
                "pattern": r"^[0-9]{8}$|^[A-Z]{2}[0-9]{6}$",
                "example": "12345678",
                "primary": True,
            },
            {
                "key": "vat_number",
                "label": "VAT Number",
                "pattern": r"^\s*(GB\s*)?[0-9]{3}\s?[0-9]{4}\s?[0-9]{2}\s*$",
                "example": "GB 123 4567 89",
                "primary": False,
            },
        ],
    },
    "DE": {
        "label": "USt-IdNr / Steuernummer / HRB",
        "currency": "EUR",
        "fields": [
            {
                "key": "ust_idnr",
                "label": "USt-IdNr.",
                "pattern": r"^DE[0-9]{9}$",
                "example": "DE312345678",
                "primary": True,
            },
            {
                "key": "steuernummer",
                "label": "Steuernummer",
                "pattern": r"^[0-9]{2,4}/[0-9]{3,5}/[0-9]{4,5}$",
                "example": "143/123/45678",
                "primary": False,
            },
            {
                "key": "hrb",
                "label": "HRB",
                "pattern": r"^HRB\s?[0-9]{1,6}$",
                "example": "HRB 123456",
                "primary": False,
            },
        ],
    },
    "AU": {
        "label": "ABN / ACN",
        "currency": "AUD",
        "fields": [
            {
                "key": "abn",
                "label": "ABN",
                "pattern": r"^\d{2}\s?\d{3}\s?\d{3}\s?\d{3}$",
                "example": "51 824 753 556",
                "primary": True,
            },
            {
                "key": "acn",
                "label": "ACN",
                "pattern": r"^\d{3}\s?\d{3}\s?\d{3}$",
                "example": "008 672 000",
                "primary": False,
            },
        ],
    },
    # ── Caribbean production jurisdictions (2026-09-21) ──────────────────
    # Digit-count patterns below follow each country's own engineering
    # spec (ZP-BB/KY/DO/GY/JM/BS/TT-ENG-001) where it states a length;
    # where the spec explicitly says the exact issuing form/identifier is
    # still unresolved (e.g. Barbados's "acquire the currently issued form
    # instead of hard-coding a form number"), the pattern is deliberately
    # lenient rather than guessing a stricter format that could reject a
    # real, valid ID.
    "BB": {
        "label": "TAMIS TIN / NIS Number",
        "currency": "BBD",
        "fields": [
            {
                "key": "tamis_tin",
                "label": "TAMIS TIN",
                "pattern": r"^\d{9,13}$",
                "example": "1234567890123",
                "primary": True,
            },
            {
                "key": "nis_number",
                "label": "NIS Number",
                "pattern": r"^[A-Za-z0-9-]{4,20}$",
                "example": "NIS-1234567",
                "primary": False,
            },
        ],
    },
    "KY": {
        "label": "NIB Employer Number",
        "currency": "KYD",
        "fields": [
            {
                "key": "nib_employer_number",
                "label": "NIB Employer Number",
                "pattern": r"^[A-Za-z0-9-]{4,20}$",
                "example": "NIB-000123",
                "primary": True,
            },
        ],
    },
    "DO": {
        "label": "RNC (Registro Nacional del Contribuyente)",
        "currency": "DOP",
        "fields": [
            {
                "key": "rnc",
                "label": "RNC",
                "pattern": r"^\d{1,3}-?\d{2}-?\d{5}-?\d{1,2}$|^\d{9,11}$",
                "example": "1-01-12345-6",
                "primary": True,
            },
        ],
    },
    "GY": {
        "label": "GRA TIN / NIS Number",
        "currency": "GYD",
        "fields": [
            {
                "key": "gra_tin",
                "label": "GRA TIN",
                "pattern": r"^\d{7,10}$",
                "example": "1234567",
                "primary": True,
            },
            {
                "key": "nis_number",
                "label": "NIS Number",
                "pattern": r"^[A-Za-z0-9-]{4,20}$",
                "example": "NIS-1234567",
                "primary": False,
            },
        ],
    },
    "JM": {
        "label": "TRN (Taxpayer Registration Number)",
        "currency": "JMD",
        "fields": [
            {
                "key": "trn",
                "label": "TRN",
                "pattern": r"^\d{9}$",
                "example": "123456789",
                "primary": True,
            },
        ],
    },
    "BS": {
        "label": "NIB Employer Number",
        "currency": "BSD",
        "fields": [
            {
                "key": "nib_employer_number",
                "label": "NIB Employer Number",
                "pattern": r"^[A-Za-z0-9-]{4,20}$",
                "example": "NIB-000123",
                "primary": True,
            },
        ],
    },
    "TT": {
        "label": "BIR File Number / NIBTT Employer Number",
        "currency": "TTD",
        "fields": [
            {
                "key": "bir_file_number",
                "label": "BIR File Number",
                "pattern": r"^\d{9,10}$",
                "example": "1234567890",
                "primary": True,
            },
            {
                "key": "nibtt_employer_number",
                "label": "NIBTT Employer Number",
                "pattern": r"^[A-Za-z0-9-]{4,20}$",
                "example": "NIBTT-000123",
                "primary": False,
            },
        ],
    },
    "PR": {
        "label": "Hacienda Employer Identification Number (EIN) / SUTA Account",
        "currency": "USD",
        "fields": [
            {
                "key": "hacienda_ein",
                "label": "Hacienda Employer Identification Number",
                "pattern": r"^\d{9}$",
                "example": "660123456",
                "primary": True,
            },
            {
                "key": "dtrh_suta_account",
                "label": "DTRH SUTA Account Number",
                "pattern": r"^[A-Za-z0-9-]{4,20}$",
                "example": "SUTA-000123",
                "primary": False,
            },
        ],
    },
    # France (2026-09-24, ZP-FR-ENG-001 §11). Primary identifier is the
    # SIREN, mirrored into tax_no; the SIRET is the establishment-level key
    # France breaks its calculation on (FR-002) and is stored on the
    # EmployerFranceProfile / EstablishmentRatePack records, kept here too so
    # registration never loses it. SIRET = SIREN + 5-digit NAC nic.
    "FR": {
        "label": "SIREN / SIRET / TVA intracommunautaire",
        "currency": "EUR",
        "fields": [
            {
                "key": "siren",
                "label": "SIREN",
                "pattern": r"^\d{9}$",
                "example": "552100554",
                "primary": True,
            },
            {
                "key": "siret",
                "label": "SIRET",
                "pattern": r"^\d{14}$",
                "example": "55210055400021",
                "primary": False,
            },
            {
                "key": "vat_intracom",
                "label": "TVA intracommunautaire",
                "pattern": r"^FR[0-9]{11}$",
                "example": "FR23392106162",
                "primary": False,
            },
        ],
    },
    "IE": {
        "label": "Revenue PAYE / PRSI Registration / ROS Sub-User",
        "currency": "EUR",
        "fields": [
            {
                "key": "paye_registration_number",
                "label": "Revenue PAYE Registration Number",
                "pattern": r"^[0-9A-Z]{6,12}$",
                "example": "1234567",
                "primary": True,
            },
            {
                "key": "prsi_registration_number",
                "label": "PRSI Registration Number",
                "pattern": r"^[0-9A-Z]{6,12}$",
                "example": "7654321",
                "primary": False,
            },
            {
                "key": "ros_sub_user_reference",
                "label": "ROS Sub-User Reference",
                "pattern": r"^[A-Za-z0-9._-]{3,64}$",
                "example": "ZOIKO-IE-ROS-01",
                "primary": False,
            },
            {
                "key": "eircode",
                "label": "Eircode",
                "pattern": r"^[A-Z][0-9]{2}\s?[A-Z0-9]{4}$",
                "example": "D02 AF30",
                "primary": False,
            },
        ],
    },
    # Sweden (ZP-SE-ENG-001 §13 "Sweden employer setup" / §11
    # EmployerRegistration). The organisation number is the primary tax ID
    # (mirrored into Organization.tax_no like every other country); the tax
    # account reference is Skatteverket's employer tax-account key used for
    # AGI settlement (spec §10 "Payment"). Personal identity numbers are
    # deliberately NOT collected at employer registration (spec §11
    # EmployerRegistration = org no + tax account; §14 data minimisation):
    # a worker's personnummer lives only on the employee record, masked.
    "SE": {
        "label": "Organisation number / Tax account",
        "currency": "SEK",
        "fields": [
            {
                "key": "employer_org_number",
                "label": "Employer organisation number (organisationsnummer)",
                "pattern": r"^\d{6}-?\d{4}$",
                "example": "556123-4567",
                "primary": True,
            },
            {
                "key": "tax_account_reference",
                "label": "Skatteverket tax account reference",
                "pattern": r"^[0-9A-Z-]{4,30}$",
                "example": "5561234567-0001",
                "primary": False,
            },
        ],
    },
    # Italy (ZP-IT-ENG-001 §17 A–C) — schema only. Deliberately NOT in
    # REGISTRATION_COUNTRIES: Italy stays PLANNED until gates G1–G8 are signed.
    # Codice fiscale of a company is 11 digits (usually equal to the partita
    # IVA); the INPS matricola is 10 digits; the INAIL PAT is 8 digits plus
    # an optional 2-digit check. Formats only — never synthesised (IT-052).
    "IT": {
        "label": "Codice fiscale / Partita IVA / Matricola INPS / PAT INAIL",
        "currency": "EUR",
        "fields": [
            {"key": "codice_fiscale", "label": "Codice fiscale (employer)",
             "pattern": r"^(\d{11}|[A-Z0-9]{16})$", "example": "01234567890", "primary": True},
            {"key": "partita_iva", "label": "Partita IVA",
             "pattern": r"^\d{11}$", "example": "01234567890", "primary": False},
            {"key": "matricola_inps", "label": "Matricola INPS",
             "pattern": r"^\d{10}$", "example": "1234567890", "primary": False},
            {"key": "pat_inail", "label": "PAT INAIL",
             "pattern": r"^\d{8}(\d{2})?$", "example": "12345678", "primary": False},
        ],
    },
    # Singapore (ZP-SG-ENG-001 §9 Employer Registration panels A–E) — schema
    # only. Deliberately NOT in REGISTRATION_COUNTRIES above: the spec's
    # production gates G1–G8 must be evidenced before any Singapore
    # organization can be onboarded. UEN pattern covers the three published
    # UEN shapes (business 8 digits + letter, local company 9 digits +
    # letter, other entity T/S/R-prefixed). CSN per CPF Board "CPF EZPay
    # (FTP) File Specifications" (effective 16 Jan 2025): UEN/NRIC/FIN (9 or
    # 10 bytes) + Payment Type (3, e.g. PTE/AMS/VCT) + Sno (2), e.g.
    # "234567891APTE01" (hyphens tolerated for readability). The remaining
    # keys are the employer's registration SETTINGS (enumerated, validated
    # by pattern; "options" lets the form render a choice list) that the
    # Singapore readiness check (SG-027) reads — none is a statutory rate.
    "SG": {
        "label": "UEN / CPF Submission Number (CSN)",
        "currency": "SGD",
        "fields": [
            {
                "key": "uen",
                "label": "UEN",
                "pattern": r"^(\d{8}[A-Z]|\d{9}[A-Z]|[TSR]\d{2}[A-Z]{2}\d{4}[A-Z])$",
                "example": "201912345K",
                "primary": True,
            },
            {
                "key": "cpf_submission_number",
                "label": "CPF Submission Number (CSN)",
                "pattern": r"^[A-Z0-9]{9,10}-?[A-Z]{3}-?\d{2}$",
                "example": "201912345KPTE01",
                "primary": False,
            },
            {"key": "cpf_ezpay_method", "label": "CPF EZPay submission method", "pattern": r"^(FILE_UPLOAD|ONLINE_FORM)$",
             "example": "FILE_UPLOAD", "primary": False, "options": ["FILE_UPLOAD", "ONLINE_FORM"]},
            {"key": "cpf_payment_method", "label": "CPF payment method", "pattern": r"^(DIRECT_DEBIT|PAYNOW|OTHER)$",
             "example": "DIRECT_DEBIT", "primary": False, "options": ["DIRECT_DEBIT", "PAYNOW", "OTHER"]},
            {"key": "ais_status", "label": "IRAS AIS participation", "pattern": r"^(PARTICIPANT|NOT_PARTICIPATING)$",
             "example": "PARTICIPANT", "primary": False, "options": ["PARTICIPANT", "NOT_PARTICIPATING"]},
            {"key": "ais_submission_mode", "label": "IRAS AIS submission mode", "pattern": r"^(EXPORT_ONLY|DIRECT_API)$",
             "example": "EXPORT_ONLY", "primary": False, "options": ["EXPORT_ONLY", "DIRECT_API"]},
            {"key": "corppass_authorised", "label": "Corppass authorisation for AIS in place", "pattern": r"^(YES|NO)$",
             "example": "YES", "primary": False, "options": ["YES", "NO"]},
            {"key": "annual_reporting_owner", "label": "Annual IRAS reporting owner", "pattern": r"^[A-Za-z0-9 .,'@&()/-]{2,100}$",
             "example": "Finance Manager", "primary": False},
            {"key": "employs_foreign_workers", "label": "Employs EP / S Pass / Work Permit holders", "pattern": r"^(YES|NO)$",
             "example": "NO", "primary": False, "options": ["YES", "NO"]},
            {"key": "mom_sector", "label": "MOM Work Permit sector",
             "pattern": r"^(SERVICES|MANUFACTURING|CONSTRUCTION|PROCESS|MARINE_SHIPYARD|NOT_APPLICABLE)$",
             "example": "SERVICES", "primary": False,
             "options": ["SERVICES", "MANUFACTURING", "CONSTRUCTION", "PROCESS", "MARINE_SHIPYARD", "NOT_APPLICABLE"]},
            {"key": "mom_levy_payment", "label": "MOM levy payment method", "pattern": r"^(GIRO|PAYNOW_QR|NOT_APPLICABLE)$",
             "example": "GIRO", "primary": False, "options": ["GIRO", "PAYNOW_QR", "NOT_APPLICABLE"]},
            {"key": "pwm_applicable", "label": "Progressive Wage Model applies to some employees", "pattern": r"^(YES|NO)$",
             "example": "NO", "primary": False, "options": ["YES", "NO"]},
            {"key": "sdl_payment_route", "label": "SDL payment route", "pattern": r"^(CPF_EZPAY|OTHER)$",
             "example": "CPF_EZPAY", "primary": False, "options": ["CPF_EZPAY", "OTHER"]},
            {"key": "bank_workflow_validated", "label": "Salary bank-payment workflow validated", "pattern": r"^(YES|NO)$",
             "example": "NO", "primary": False, "options": ["YES", "NO"]},
            {"key": "pdpa_controls_approved", "label": "PDPA / NRIC handling controls approved", "pattern": r"^(YES|NO)$",
             "example": "NO", "primary": False, "options": ["YES", "NO"]},
        ],
    },
    # Hong Kong (ZP-HK-ENG-001 §13 HKEmployerRegistration) — schema only.
    # Deliberately NOT in REGISTRATION_COUNTRIES: live Hong Kong payroll stays
    # disabled until release gates G1–G7 are evidenced and the signed pack is
    # activated (and the registry row leaves PLANNED). BR number: the 8-digit
    # Business Registration number. IRD employer's file number: the
    # "6xx-xxxxxxxx" reference printed on BIR56A (format kept lenient — the
    # exact issuing format is a G1 confirmation item). The remaining keys
    # are employer SETTINGS read by the Hong Kong readiness check — none is
    # a statutory rate.
    "HK": {
        "label": "BR Number / IRD Employer's File Number",
        "currency": "HKD",
        "fields": [
            {"key": "br_number", "label": "Business Registration Number", "pattern": r"^\d{8}$",
             "example": "12345678", "primary": True},
            {"key": "ird_employer_file_number", "label": "IRD Employer's File Number",
             "pattern": r"^\d[A-Z0-9]{2}-?\d{6,8}$", "example": "6A1-12345678", "primary": False},
            {"key": "empf_employer_account", "label": "eMPF employer account number",
             "pattern": r"^[A-Za-z0-9-]{4,30}$", "example": "ER-12345678", "primary": False},
            {"key": "mpf_scheme_name", "label": "MPF scheme (trustee) the employer participates in",
             "pattern": r"^[A-Za-z0-9 .,'&()/-]{2,100}$", "example": "Example MPF Master Trust", "primary": False},
            {"key": "empf_submission_channel", "label": "eMPF submission channel",
             "pattern": r"^(EMPF_PLATFORM_MANUAL|NOT_CONFIGURED)$", "example": "EMPF_PLATFORM_MANUAL",
             "primary": False, "options": ["EMPF_PLATFORM_MANUAL", "NOT_CONFIGURED"]},
            {"key": "ird_filing_channel", "label": "IRD employer's return filing channel",
             "pattern": r"^(IRD_ETAX_MANUAL|PAPER|NOT_CONFIGURED)$", "example": "IRD_ETAX_MANUAL",
             "primary": False, "options": ["IRD_ETAX_MANUAL", "PAPER", "NOT_CONFIGURED"]},
            {"key": "ec_insurance_policy_number", "label": "Employees' Compensation insurance policy number",
             "pattern": r"^[A-Za-z0-9/-]{3,40}$", "example": "EC-2026-000123", "primary": False},
            {"key": "ec_insurance_expiry", "label": "Employees' Compensation insurance expiry (YYYY-MM-DD)",
             "pattern": r"^\d{4}-\d{2}-\d{2}$", "example": "2027-06-30", "primary": False},
            {"key": "pics_published", "label": "Employment Personal Information Collection Statement issued",
             "pattern": r"^(YES|NO)$", "example": "NO", "primary": False, "options": ["YES", "NO"]},
            {"key": "bank_workflow_validated", "label": "Salary bank-payment workflow validated",
             "pattern": r"^(YES|NO)$", "example": "NO", "primary": False, "options": ["YES", "NO"]},
        ],
    },
}

# Country name → payroll code. Full names come from the Register Page's
# REGISTRATION_COUNTRIES dropdown; codes from the Compliance jurisdiction
# dropdown. Both forms must resolve to the same schema.
COUNTRY_NAME_TO_CODE = {
    "india": "IN",
    "united states": "US",
    "usa": "US",
    "united kingdom": "UK",
    "uk": "UK",
    "great britain": "UK",
    "germany": "DE",
    "australia": "AU",
    "barbados": "BB",
    "cayman islands": "KY",
    "dominican republic": "DO",
    "guyana": "GY",
    "jamaica": "JM",
    "bahamas": "BS",
    "the bahamas": "BS",
    "trinidad and tobago": "TT",
    "trinidad & tobago": "TT",
    "puerto rico": "PR",
    "france": "FR",
    "ireland": "IE",
    "sweden": "SE",
    "singapore": "SG",
    "hong kong": "HK",
    "hong kong sar": "HK",
    "hong kong, china": "HK",
    "italy": "IT",
    "italia": "IT",
}

CODE_TO_COUNTRY_NAME = {
    "IN": "India",
    "US": "United States",
    "UK": "United Kingdom",
    "DE": "Germany",
    "AU": "Australia",
    "BB": "Barbados",
    "KY": "Cayman Islands",
    "DO": "Dominican Republic",
    "GY": "Guyana",
    "JM": "Jamaica",
    "BS": "Bahamas",
    "TT": "Trinidad and Tobago",
    "PR": "Puerto Rico",
    "FR": "France",
    "IE": "Ireland",
    "SE": "Sweden",
    "SG": "Singapore",
    "HK": "Hong Kong",
    "IT": "Italy",
}

# Mirror of the mappings already used elsewhere (payroll service) so this
# module stays the single reference for jurisdiction-aware tax IDs without
# disturbing those existing code paths.
EXTRA_COUNTRY_NAME_TO_CODE = {
    "canada": "CA",
}

# Exposed for clients that still pass full country names and want every
# supported registration country resolved (IN/US/UK/DE/AU/CA).
ALL_COUNTRY_NAME_TO_CODE = {**COUNTRY_NAME_TO_CODE, **EXTRA_COUNTRY_NAME_TO_CODE}
ALL_CODE_TO_COUNTRY_NAME = {
    **CODE_TO_COUNTRY_NAME,
    "CA": "Canada",
}


def get_jurisdiction_code(country) -> Optional[str]:
    """Resolve a country (full name or 2-letter code) to the payroll
    jurisdiction code used by the tax schemas. Case/whitespace tolerant."""
    if not country:
        return None
    value = str(country).strip()
    upper = value.upper()
    if upper in JURISDICTION_TAX_SCHEMAS:
        return upper
    return ALL_COUNTRY_NAME_TO_CODE.get(value.lower())


def get_jurisdiction_schema(country):
    """Return the tax schema dict for a country name/code, or None when the
    country has no jurisdiction-specific tax schema defined."""
    code = get_jurisdiction_code(country)
    if not code:
        return None
    return JURISDICTION_TAX_SCHEMAS.get(code)


def get_primary_tax_field(country):
    """Return the primary field definition for a jurisdiction, or None."""
    schema = get_jurisdiction_schema(country)
    if not schema:
        return None
    for field in schema["fields"]:
        if field.get("primary"):
            return field
    return schema["fields"][0] if schema["fields"] else None


def primary_tax_value(country, identifiers) -> Optional[str]:
    """Best-effort extraction of the legacy single tax-no string from a set of
    jurisdiction tax IDs. Mirrors the primary identifier so Organization.tax_no
    / CompanyComplianceDetails.tax_no keep feeding payroll footers/reports."""
    if not identifiers or not isinstance(identifiers, dict):
        return None
    primary = get_primary_tax_field(country)
    if primary:
        value = identifiers.get(primary["key"])
        if value:
            return str(value).strip()
    # Fallback: any non-empty value in field order.
    for key in get_jurisdiction_field_keys(country):
        value = identifiers.get(key)
        if value:
            return str(value).strip()
    return None


def get_jurisdiction_field_keys(country):
    schema = get_jurisdiction_schema(country)
    if not schema:
        return []
    return [field["key"] for field in schema["fields"]]


def _normalize_value(raw) -> Optional[str]:
    if raw is None:
        return None
    value = str(raw).strip()
    return value if value else None


def validate_tax_identifiers(country, identifiers) -> tuple:
    """Validate an incoming tax-identifiers dict against a jurisdiction schema.

    Returns ``(normalized, errors)`` where ``normalized`` is a dict of only the
    fields defined for the jurisdiction (non-empty values, whitespace stripped)
    and ``errors`` is a list of ``{"key": ..., "message": ...}``. Values that
    are empty are accepted (all jurisdiction tax IDs are optional — matching
    the pre-existing optional tax_no behaviour); provided values must match
    the jurisdiction pattern.
    """
    schema = get_jurisdiction_schema(country)
    if not schema or not identifiers or not isinstance(identifiers, dict):
        return {}, []

    normalized: dict = {}
    errors: list = []
    for field in schema["fields"]:
        key = field["key"]
        value = _normalize_value(identifiers.get(key))
        if value is None:
            continue
        pattern = field["pattern"]
        import re

        if not re.fullmatch(pattern, value):
            errors.append({
                "key": key,
                "message": f"{field['label']} for {schema['label']} is not in a valid format (e.g. {field['example']}).",
            })
            continue
        normalized[key] = value
    return normalized, errors


def validate_tax_identifiers_or_raise(country, identifiers) -> dict:
    """Server-side validation that raises a 400 on the first bad field.
    Returns the normalized dict on success (may be empty)."""
    from app.core.exceptions import BadRequestException

    normalized, errors = validate_tax_identifiers(country, identifiers)
    if errors:
        raise BadRequestException(errors[0]["message"])
    return normalized
