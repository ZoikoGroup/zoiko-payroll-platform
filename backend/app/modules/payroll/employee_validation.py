"""
modules/payroll/employee_validation.py
---------------------------------------
Jurisdiction-specific validation for PayrollEmployee onboarding — Strategy
Pattern, one class per supported country, dispatched by a factory function.

Reuse notes (this module is deliberately additive, not a rewrite):
- Country codes (IN/US/UK/AU/DE/CA) match exactly what
  `service._normalize_country()` already produces — callers must normalize
  first and pass the 2-letter code in here, so this module never needs to
  import service.py itself (avoids a circular import; service.py imports
  from here instead).
- India's PAN/UAN/IFSC keep living on PayrollEmployee's own dedicated
  columns (pan/uan/ifsc) — real production data already exists there. Only
  the OTHER five countries' identifiers are modeled here, stored in the new
  PayrollEmployee.compliance_fields JSON column.
- This module only validates and normalizes a compliance payload; it does
  not touch the database. Duplicate-identifier lookups live in service.py
  (check_duplicate_employee_identifiers) next to the other employee
  queries, reusing the existing db.query(PayrollEmployee) pattern rather
  than introducing a parallel data-access layer here.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Optional

from app.core.exceptions import BadRequestException


def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


class EmployeeValidationStrategy:
    """Base Strategy. FIELD_SPECS maps compliance_fields key -> spec dict:
        required: bool
        pattern: compiled regex, or None for free-text/choice fields
        error: message shown when pattern fails
        choices: optional list of allowed values (choice fields)
        upper: normalize to uppercase before validating/storing
        strip_chars: characters to strip before pattern-matching (e.g. "- " for SIN/sort codes)
    `duplicate_field` names the one field (if any) checked for cross-employee
    duplicates in this jurisdiction, beyond email (which is always checked).
    """

    country_code: str = ""
    FIELD_SPECS: dict = {}
    duplicate_field: Optional[str] = None

    # Maps a compliance_fields key to the PayrollEmployee dedicated column
    # it should ALSO populate, for strategies whose engine calculator
    # reads that column directly (e.g. UK's engine/countries/uk.py reads
    # tax_code/ni_category/study_loan_plan/study_loan_balance off
    # PayrollContext, not off compliance_fields — without this map, a
    # value submitted through complianceFields never reaches the engine
    # at all). Empty for every strategy with no such dedicated-column
    # consumer.
    FIELD_COLUMN_MAP: dict = {}
    # Optional per-field value translation applied only to the copy going
    # into the dedicated column (the compliance_fields value itself stays
    # exactly as entered) — e.g. UK's "Plan 2" -> "UK_PLAN2". A dict does
    # a lookup (falling back to the original value if unmapped); a
    # callable is invoked directly (used for e.g. numeric-string -> Decimal).
    FIELD_VALUE_MAP: dict = {}

    @classmethod
    def validate(cls, compliance: dict) -> dict:
        compliance = dict(compliance or {})
        errors = []
        cleaned = {}
        for key, spec in cls.FIELD_SPECS.items():
            raw = _clean(compliance.get(key))
            if raw is None:
                if spec.get("required"):
                    errors.append(f"{key} is required for {cls.country_code} employees.")
                continue
            if spec.get("strip_chars"):
                for ch in spec["strip_chars"]:
                    raw = raw.replace(ch, "")
            if spec.get("upper"):
                raw = raw.upper()
            choices = spec.get("choices")
            if choices and raw not in choices:
                errors.append(f"{key} must be one of {choices} (got {raw!r}).")
                continue
            pattern = spec.get("pattern")
            if pattern and not pattern.match(raw):
                errors.append(spec.get("error", f"{key} format is invalid.") + f" (got {raw!r})")
                continue
            cleaned[key] = raw
        if errors:
            raise BadRequestException("; ".join(errors))
        return cleaned

    @classmethod
    def get_duplicate_identifier(cls, compliance: dict):
        if not cls.duplicate_field:
            return None
        value = _clean((compliance or {}).get(cls.duplicate_field))
        return (cls.duplicate_field, value) if value else None

    @classmethod
    def sync_to_columns(cls, cleaned: dict) -> dict:
        """Returns {column_name: value} for whichever compliance_fields
        keys FIELD_COLUMN_MAP names and `cleaned` (the already-validated
        compliance dict) actually has a value for. A caller merges this
        into the same dict it's about to persist onto PayrollEmployee
        (employee_data / updates / mapped) — plain-dict-based rather than
        ORM-based so it works uniformly at every call site, including the
        ones that build a dict before the ORM row even exists (create,
        bulk upsert). Empty dict for every strategy with no
        FIELD_COLUMN_MAP (every country except UK today) — a complete
        no-op, doesn't touch compliance_fields itself."""
        result = {}
        for field_key, column_name in cls.FIELD_COLUMN_MAP.items():
            if field_key not in cleaned:
                continue
            value = cleaned[field_key]
            mapper = cls.FIELD_VALUE_MAP.get(field_key)
            if callable(mapper):
                value = mapper(value)
            elif isinstance(mapper, dict):
                value = mapper.get(value, value)
            result[column_name] = value
        return result


class INEmployeeValidation(EmployeeValidationStrategy):
    """India's pan/uan/ifsc live on dedicated PayrollEmployee columns, not
    here — this only covers the fields that don't already have a column."""
    country_code = "IN"
    FIELD_SPECS = {
        "esi_number": {
            "pattern": re.compile(r"^\d{10}(\d{7})?$"),
            "error": "ESI number must be 10 or 17 digits.",
        },
        "tax_regime": {"choices": ["Old", "New"]},
    }
    duplicate_field = None  # PAN (the real dedup key) is a dedicated column — checked separately


class USEmployeeValidation(EmployeeValidationStrategy):
    country_code = "US"
    FIELD_SPECS = {
        "ssn": {
            "required": True,
            "strip_chars": " ",
            "pattern": re.compile(r"^\d{3}-\d{2}-\d{4}$"),
            "error": "SSN must be in the format 123-45-6789.",
        },
        "flsa_status": {"required": True, "choices": ["Exempt", "Non-Exempt"]},
        "w4_filing_status": {
            "choices": ["Single", "Married Filing Jointly", "Married Filing Separately", "Head of Household"],
        },
        "aba_routing_number": {
            "pattern": re.compile(r"^\d{9}$"),
            "error": "ABA routing number must be exactly 9 digits.",
        },
        "state_tax_jurisdiction": {
            "required": True, "upper": True,
            "pattern": re.compile(r"^[A-Z]{2}$"),
            "error": "State tax jurisdiction must be a 2-letter state code (e.g. CA, NY).",
        },
        # Reciprocity (see service.py's _resolve_us_reciprocity): only
        # meaningfully different from state_tax_jurisdiction for a genuine
        # multi-state commuter (e.g. lives in PA, works in NJ) — optional,
        # since most employees' residence and work state are the same and
        # the engine already falls back to work_state when this is unset.
        "residence_state": {
            "upper": True,
            "pattern": re.compile(r"^[A-Z]{2}$"),
            "error": "Residence state must be a 2-letter state code (e.g. PA).",
        },
        "reciprocity_certificate_on_file": {"choices": ["true", "false", "True", "False"]},
        "reciprocity_certificate_expiry": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
            "error": "Certificate expiry must be in YYYY-MM-DD format.",
        },
        # Optional — only meaningful once Tax Ops has entered a matching
        # LocalityRate for this code (see service.py's get_locality_rate /
        # Super Admin's Locality Rates panel). No format is enforced since
        # real-world locality codes vary widely (county FIPS, municipal
        # short codes, PSD codes) — free text, same convention as
        # employeeCertificate on ReciprocityRule.
        "work_locality": {},
    }
    duplicate_field = "ssn"

    # The fix for the same class of dead-plumbing gap UK's FIELD_COLUMN_MAP
    # already closed (see UKEmployeeValidation below): state_tax_jurisdiction
    # and w4_filing_status were previously stored ONLY in compliance_fields
    # JSON — PayrollEmployee.work_state (the column engine/countries/us.py
    # and the state-scoped-config resolver actually read) and the new
    # w4_filing_status column (engine/countries/us.py's filing-status-aware
    # federal bracket/threshold resolution) never received a value, so a
    # US employee's declared state/filing-status was silently ignored by
    # every calculation.
    FIELD_COLUMN_MAP = {
        "state_tax_jurisdiction": "work_state",
        "w4_filing_status": "w4_filing_status",
        # Without these three, the reciprocity engine (fully built and
        # tested — see service.py:_resolve_us_reciprocity, resolve_reciprocity)
        # had no way to ever actually activate for a real employee: Super
        # Admin could configure a perfectly correct PA/NJ agreement, but no
        # org admin had any path to mark an employee as a cross-state
        # commuter or record their certificate — the exact same class of
        # dead-plumbing gap as state_tax_jurisdiction/w4_filing_status above.
        "residence_state": "residence_state",
        "reciprocity_certificate_on_file": "reciprocity_certificate_on_file",
        "reciprocity_certificate_expiry": "reciprocity_certificate_expiry",
        # Same dead-plumbing gap, for Locality: PayrollEmployee.work_locality
        # (the column service.py's get_locality_rate/_resolve_employee_calc_inputs
        # and add_payslip_item actually read) previously had no path to be
        # set from an org admin's compliance_fields entry.
        "work_locality": "work_locality",
    }
    FIELD_VALUE_MAP = {
        # Compact codes matching what engine/countries/us.py and
        # ContributionRate/TaxSlab.filing_status rows use — the
        # compliance_fields value itself stays the human-readable choice
        # exactly as entered (same convention as UK's student_loan_plan).
        "w4_filing_status": {
            "Single": "SINGLE",
            "Married Filing Jointly": "MFJ",
            "Married Filing Separately": "MFS",
            "Head of Household": "HOH",
        },
        # PayrollEmployee.reciprocity_certificate_on_file is a real Boolean
        # column (not a string) — same conversion-lambda convention as UK's
        # study_loan_balance below.
        "reciprocity_certificate_on_file": lambda v: str(v).lower() == "true",
        "reciprocity_certificate_expiry": lambda v: date.fromisoformat(v) if v else None,
    }


class UKEmployeeValidation(EmployeeValidationStrategy):
    country_code = "UK"
    FIELD_SPECS = {
        "nino": {
            "required": True, "upper": True, "strip_chars": " ",
            # Standard NINO structure: two letters (excluding D,F,I,Q,U,V as
            # first letter; O never second), six digits, one suffix letter A-D.
            "pattern": re.compile(r"^[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\d{6}[A-D]$"),
            "error": "NINO must look like QQ123456C.",
        },
        "paye_tax_code": {
            "required": True, "upper": True,
            # ZP-TAX-UK-2026-27-001 section 6.2/6.3: standard/K-code
            # allowance codes, 0T, and the flat-rate override families
            # BR/D0/D1 (rUK), SBR/SD0-3 (Scotland), CBR/CD0/CD1 (Wales) —
            # the leading S/C is the ONE HMRC-sanctioned region signal,
            # never inferred from worksite (see service.py's
            # _resolve_uk_sub_jurisdiction_with_source).
            "pattern": re.compile(r"^([SC]?K\d{1,6}|[SC]?\d{1,4}[LMNPTY]|[SC]?0T|BR|D0|D1|SBR|SD[0-3]|CBR|CD0|CD1|NT)$"),
            "error": "PAYE tax code format looks incorrect (e.g. 1257L, S1257L, C1257L, SD1, CBR).",
        },
        "student_loan_plan": {"choices": ["None", "Plan 1", "Plan 2", "Plan 4", "Plan 5", "Postgraduate"]},
        "auto_enrolment_pension": {"choices": ["true", "false", "True", "False"]},
        "sort_code": {
            "required": True, "strip_chars": "- ",
            "pattern": re.compile(r"^\d{6}$"),
            "error": "Sort code must be 6 digits (e.g. 123456 or 12-34-56).",
        },
        # All 16 letters from ZP-TAX-UK-2026-27-001 section 8.2 (AC-10).
        # Rate DATA for a category beyond A is a separate, additive seed
        # (uk.py's _resolve_ni_bands reads whatever NI_BAND rows exist for
        # the category actually set here) — this just makes every real
        # HMRC letter selectable; it was previously accepted with no
        # validation at all.
        "ni_category": {"choices": ["A", "B", "C", "D", "E", "F", "H", "I", "J", "K", "L", "M", "N", "S", "V", "Z"]},
        "study_loan_balance": {
            "pattern": re.compile(r"^\d+(\.\d{1,2})?$"),
            "error": "Student/Postgraduate Loan balance must be a number.",
        },
    }
    duplicate_field = "nino"

    # The fix for the dead-plumbing gap: PayrollContext.tax_code/
    # ni_category/study_loan_plan/study_loan_balance are real columns
    # engine/countries/uk.py genuinely reads — but until this map existed,
    # nothing ever copied a validated complianceFields value into them.
    FIELD_COLUMN_MAP = {
        "paye_tax_code": "tax_code",
        "ni_category": "ni_category",
        "student_loan_plan": "study_loan_plan",
        "study_loan_balance": "study_loan_balance",
    }
    FIELD_VALUE_MAP = {
        "student_loan_plan": {
            "Plan 1": "UK_PLAN1", "Plan 2": "UK_PLAN2", "Plan 4": "UK_PLAN4", "Plan 5": "UK_PLAN5",
            "Postgraduate": "UK_POSTGRAD", "None": None,
        },
        "study_loan_balance": lambda v: Decimal(v) if v else None,
    }


class AUEmployeeValidation(EmployeeValidationStrategy):
    country_code = "AU"
    FIELD_SPECS = {
        "tfn": {
            "required": True, "strip_chars": " ",
            "pattern": re.compile(r"^\d{8,9}$"),
            "error": "TFN must be 8 or 9 digits.",
        },
        "help_stsl_debt": {"choices": ["true", "false", "True", "False"]},
        "super_fund_usi": {
            "upper": True,
            "pattern": re.compile(r"^[A-Z0-9]{8,14}$"),
            "error": "Super fund USI looks incorrect.",
        },
        "super_member_number": {"pattern": re.compile(r"^[A-Za-z0-9]{1,20}$"), "error": "Member number looks incorrect."},
        "bsb_code": {
            "required": True, "strip_chars": "- ",
            "pattern": re.compile(r"^\d{6}$"),
            "error": "BSB code must be 6 digits (e.g. 123456 or 123-456).",
        },
    }
    duplicate_field = "tfn"


class CAEmployeeValidation(EmployeeValidationStrategy):
    country_code = "CA"
    FIELD_SPECS = {
        "sin": {
            "required": True, "strip_chars": "- ",
            "pattern": re.compile(r"^\d{9}$"),
            "error": "SIN must be 9 digits (e.g. 123-456-789).",
        },
        "td1_claim_amount": {"pattern": re.compile(r"^\d+(\.\d{1,2})?$"), "error": "TD1 claim amount must be a number."},
        "province": {
            "required": True, "upper": True,
            "choices": ["ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"],
        },
        "transit_number": {
            "pattern": re.compile(r"^\d{5}$"),
            "error": "Transit number must be 5 digits.",
        },
        "financial_institution_number": {
            "pattern": re.compile(r"^\d{3}$"),
            "error": "Financial institution number must be 3 digits.",
        },
    }
    duplicate_field = "sin"


class DEEmployeeValidation(EmployeeValidationStrategy):
    country_code = "DE"
    FIELD_SPECS = {
        "steuer_id": {
            "required": True, "strip_chars": " ",
            "pattern": re.compile(r"^\d{11}$"),
            "error": "Steuer-ID must be exactly 11 digits.",
        },
        "rv_nummer": {
            "upper": True, "strip_chars": " ",
            # 2-digit area + 6-digit birthdate (TTMMJJ) + 1 letter + 3-digit serial = 12 chars
            "pattern": re.compile(r"^\d{8}[A-Z]\d{3}$"),
            "error": "RV-Nummer must be 12 characters (8 digits, 1 letter, 3 digits).",
        },
        "steuerklasse": {"required": True, "upper": True, "choices": ["I", "II", "III", "IV", "V", "VI"]},
        "krankenkasse": {"required": True},
        "iban": {
            "required": True, "upper": True, "strip_chars": " ",
            "pattern": re.compile(r"^DE\d{20}$"),
            "error": "German IBAN must be DE followed by 20 digits.",
        },
        "bic": {
            "upper": True, "strip_chars": " ",
            "pattern": re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$"),
            "error": "BIC must be 8 or 11 characters.",
        },
    }
    duplicate_field = "steuer_id"


_STRATEGIES = {
    "IN": INEmployeeValidation,
    "US": USEmployeeValidation,
    "UK": UKEmployeeValidation,
    "AU": AUEmployeeValidation,
    "CA": CAEmployeeValidation,
    "DE": DEEmployeeValidation,
}


def get_employee_validation_strategy(country_code: str) -> EmployeeValidationStrategy:
    """Factory/dispatcher — country_code must already be normalized to a
    2-letter code (callers use service._normalize_country() first, exactly
    like every other jurisdiction-aware lookup in service.py)."""
    strategy = _STRATEGIES.get((country_code or "").upper())
    if strategy is None:
        raise BadRequestException(
            f"Unsupported country code '{country_code}'. Supported: {', '.join(_STRATEGIES)}."
        )
    return strategy
