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
