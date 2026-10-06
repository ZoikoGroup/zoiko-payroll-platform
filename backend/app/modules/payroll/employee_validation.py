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
    # compliance_fields keys that are personal national/tax/social-insurance
    # identifiers — masked in every API response (mask_compliance_fields).
    # Bank details (routing codes, IBAN, account numbers) are NOT in scope
    # here: they also feed the `routing` display and bank transfer files.
    SENSITIVE_FIELDS: tuple = ()

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
            # Generic numeric-range bound — opt-in via "min"/"max" on a
            # FIELD_SPEC entry (e.g. Arizona's employee-elected withholding
            # percentage, statutory range 0.5-3.5). No existing field
            # defines either key, so this is a no-op for every spec that
            # predates it.
            min_val, max_val = spec.get("min"), spec.get("max")
            if min_val is not None or max_val is not None:
                try:
                    numeric = Decimal(raw)
                except Exception:
                    errors.append(spec.get("error", f"{key} must be a number.") + f" (got {raw!r})")
                    continue
                if (min_val is not None and numeric < min_val) or (max_val is not None and numeric > max_val):
                    errors.append(spec.get("error", f"{key} must be between {min_val} and {max_val}.") + f" (got {raw!r})")
                    continue
            cleaned[key] = raw
        if errors:
            raise BadRequestException("; ".join(errors))
        cls._validate_combination(cleaned)
        return cleaned

    @classmethod
    def _validate_combination(cls, cleaned: dict) -> None:
        """Cross-field checks that can't be expressed as a single
        FIELD_SPEC entry (two fields individually valid but incompatible
        together). No-op by default; a subclass overrides only where it
        genuinely needs one. Best-effort: only sees fields present in
        THIS validation call — the engine-layer calculation is the
        authoritative guard against an incompatible combination that
        reaches the database via separate updates (see e.g. uk.py's
        calculate() for the Postgraduate Loan double-count guard)."""
        pass

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
    SENSITIVE_FIELDS = ('esi_number',)
    FIELD_SPECS = {
        "esi_number": {
            "pattern": re.compile(r"^\d{10}(\d{7})?$"),
            "error": "ESI number must be 10 or 17 digits.",
        },
        "tax_regime": {"choices": ["Old", "New"]},
    }
    duplicate_field = None  # PAN (the real dedup key) is a dedicated column — checked separately

    # Same dead-plumbing gap US's state_tax_jurisdiction/w4_filing_status
    # and UK's own FIELD_COLUMN_MAP entries were added to close: without
    # this, tax_regime lived ONLY in compliance_fields JSON, never reached
    # the dedicated PayrollEmployee.tax_regime column india.py and
    # service.py's rate/slab resolution actually read — every India
    # employee's Old/New regime election was silently ignored, with
    # service.py's own effective_tax_regime fallback quietly defaulting
    # every employee to "New" regardless of what was selected on the form.
    FIELD_COLUMN_MAP = {
        "tax_regime": "tax_regime",
    }


class USEmployeeValidation(EmployeeValidationStrategy):
    country_code = "US"
    SENSITIVE_FIELDS = ('ssn',)
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
        # Form W-4 Step 2 "Multiple Jobs or Spouse Works" checkbox (ZP-TAX-
        # US-2026-001 §3.3) — optional; unset/false means the standard
        # bracket table applies exactly as before this field existed.
        "w4_step2_checkbox": {"choices": ["true", "false", "True", "False"]},
        # Which Form W-4 vintage this employee actually filed — real column
        # (models.py's w4_form_vintage), read by us.py to pick the correct
        # pre-2020-allowance path AND North Dakota's two different bracket
        # tables. Previously collected nowhere in the org-facing form at
        # all (found 2026-09-15 Org Admin onboarding-guidance audit); unset
        # defaults to the current post-2020 table, same as before this
        # field had any UI path.
        "w4_form_vintage": {"choices": ["2020 or later (current form)", "Pre-2020 (legacy form)"]},
        # Federal W-4 §3.4 controls (ZP-TAX-US-2026-001, gap-closure Plan
        # Phase 2d) — all optional; unset means each is a complete no-op
        # in engine/countries/us.py, never a guessed value.
        "w4_allowances_claimed": {
            "min": Decimal("0"),
            "error": "W-4 allowances claimed must be zero or a positive whole number.",
        },
        "is_nonresident_alien": {"choices": ["true", "false", "True", "False"]},
        "w4_dependents_credit_annual": {
            "min": Decimal("0"),
            "error": "W-4 Step 3 dependents credit must be zero or positive.",
        },
        "w4_other_income_annual": {
            "min": Decimal("0"),
            "error": "W-4 Step 4(a) other income must be zero or positive.",
        },
        "w4_extra_withholding_per_period": {
            "min": Decimal("0"),
            "error": "W-4 Step 4(c) extra withholding must be zero or positive.",
        },
        # Connecticut CT-W4 Withholding Code — only meaningful for CT
        # employees; optional (unset means $0 CT withholding, same as
        # today, never a guessed code).
        "ct_withholding_code": {"upper": True, "choices": ["A", "B", "C", "D", "F"]},
        # New Jersey NJ-W4 Rate Table letter — only meaningful for NJ
        # employees; optional (unset means $0 NJ withholding, never a
        # guessed table).
        "nj_rate_table": {"upper": True, "choices": ["A", "B", "C", "D", "E"]},
        # Kansas Form K-4 certified dependent count — only meaningful for
        # KS employees; optional (unset means 0 dependents, never a
        # guessed count — see models.PayrollEmployee.ks_k4_dependents).
        "ks_k4_dependents": {
            "min": Decimal("0"),
            "error": "Kansas K-4 dependent count must be zero or a positive whole number.",
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
        # City/local-level residence (currently only meaningful for New
        # York's Yonkers resident surcharge, see us.py) — optional, free
        # text like work_locality above, since no employee has a value
        # today and unset means "no city-level residence on file," never
        # a guess.
        "residence_locality": {},
        "reciprocity_certificate_on_file": {"choices": ["true", "false", "True", "False"]},
        "reciprocity_certificate_expiry": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
            "error": "Certificate expiry must be in YYYY-MM-DD format.",
        },
        # Pennsylvania Act 32 Residency Certification Form (DCED-CLGS-32-6)
        # — pure recordkeeping, optional; never read by any calculation.
        "residency_certification_on_file": {"choices": ["true", "false", "True", "False"]},
        "residency_certification_date": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
            "error": "Residency certification date must be in YYYY-MM-DD format.",
        },
        # Optional — only meaningful once Tax Ops has entered a matching
        # LocalityRate for this code (see service.py's get_locality_rate /
        # Super Admin's Locality Rates panel). No format is enforced since
        # real-world locality codes vary widely (county FIPS, municipal
        # short codes, PSD codes) — free text, same convention as
        # employeeCertificate on ReciprocityRule.
        "work_locality": {},
        # Arizona Form A-4 employee election (ZP-TAX-US-2026-001 §4
        # Matrix) — statutory range 0.5%-3.5%. Optional: unset means "no
        # A-4 on file," and engine/countries/us.py falls back to the
        # document's own 2.0% no-form default, exactly as before this
        # field existed. Only meaningful for AZ employees, but not
        # restricted to work_state=="AZ" here — a value entered for a
        # non-AZ employee is simply never read (us.py only consults it
        # for states whose canonical slab is a single FLAT_RATE row).
        "state_income_tax_election_pct": {
            "min": Decimal("0.5"), "max": Decimal("3.5"),
            "error": "Arizona Form A-4 withholding election must be between 0.5% and 3.5%.",
        },
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
        "w4_step2_checkbox": "w4_step2_checkbox",
        "w4_form_vintage": "w4_form_vintage",
        "w4_allowances_claimed": "w4_allowances_claimed",
        "is_nonresident_alien": "is_nonresident_alien",
        "w4_dependents_credit_annual": "w4_dependents_credit_annual",
        "w4_other_income_annual": "w4_other_income_annual",
        "w4_extra_withholding_per_period": "w4_extra_withholding_per_period",
        "residency_certification_on_file": "residency_certification_on_file",
        "residency_certification_date": "residency_certification_date",
        "ct_withholding_code": "ct_withholding_code",
        "nj_rate_table": "nj_rate_table",
        "ks_k4_dependents": "ks_k4_dependents",
        # Without these three, the reciprocity engine (fully built and
        # tested — see service.py:_resolve_us_reciprocity, resolve_reciprocity)
        # had no way to ever actually activate for a real employee: Super
        # Admin could configure a perfectly correct PA/NJ agreement, but no
        # org admin had any path to mark an employee as a cross-state
        # commuter or record their certificate — the exact same class of
        # dead-plumbing gap as state_tax_jurisdiction/w4_filing_status above.
        "residence_state": "residence_state",
        "residence_locality": "residence_locality",
        "reciprocity_certificate_on_file": "reciprocity_certificate_on_file",
        "reciprocity_certificate_expiry": "reciprocity_certificate_expiry",
        # Same dead-plumbing gap, for Locality: PayrollEmployee.work_locality
        # (the column service.py's get_locality_rate/_resolve_employee_calc_inputs
        # and add_payslip_item actually read) previously had no path to be
        # set from an org admin's compliance_fields entry.
        "work_locality": "work_locality",
        # Same dead-plumbing shape: PayrollEmployee.state_income_tax_election_pct
        # (the column engine/countries/us.py's AZ-election override actually
        # reads) previously didn't exist at all — see that column's own
        # docstring in models.py.
        "state_income_tax_election_pct": "state_income_tax_election_pct",
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
        "state_income_tax_election_pct": lambda v: Decimal(v) if v else None,
        "w4_step2_checkbox": lambda v: str(v).lower() == "true",
        # Compact codes matching what us.py's `ctx.w4_form_vintage ==
        # "PRE_2020"` check literally compares against — same
        # human-readable-in-compliance_fields/compact-in-column split as
        # w4_filing_status above.
        "w4_form_vintage": {
            "2020 or later (current form)": "2020_PLUS",
            "Pre-2020 (legacy form)": "PRE_2020",
        },
    }


class UKEmployeeValidation(EmployeeValidationStrategy):
    country_code = "UK"
    SENSITIVE_FIELDS = ('nino',)
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
        # ZP-TAX-UK-2026-27-001 §10.2: a Postgraduate Loan repaid
        # CONCURRENTLY with an undergraduate plan (two separate deduction
        # lines) — distinct from student_loan_plan == "Postgraduate"
        # (a standalone Postgraduate-only employee, already fully handled
        # by that single field). See _validate_combination below for the
        # guard against setting both at once.
        "has_postgrad_loan": {"choices": ["true", "false", "True", "False"]},
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
        "has_postgrad_loan": "has_postgrad_loan",
    }
    FIELD_VALUE_MAP = {
        "student_loan_plan": {
            "Plan 1": "UK_PLAN1", "Plan 2": "UK_PLAN2", "Plan 4": "UK_PLAN4", "Plan 5": "UK_PLAN5",
            "Postgraduate": "UK_POSTGRAD", "None": None,
        },
        "study_loan_balance": lambda v: Decimal(v) if v else None,
        "has_postgrad_loan": lambda v: str(v).strip().lower() == "true",
    }

    @classmethod
    def _validate_combination(cls, cleaned: dict) -> None:
        # A standalone Postgraduate-only employee (student_loan_plan ==
        # "Postgraduate") is already fully handled by that one field —
        # also setting has_postgrad_loan would double-deduct the same
        # loan. Only catches the case where both are submitted together
        # in this same request; see the base class docstring for why the
        # engine-layer guard (uk.py's calculate()) is the authoritative one.
        if cleaned.get("student_loan_plan") == "Postgraduate" and cleaned.get("has_postgrad_loan", "").lower() == "true":
            raise BadRequestException(
                "has_postgrad_loan cannot be enabled when student_loan_plan is already 'Postgraduate' — "
                "that employee's Postgraduate Loan is already fully represented by student_loan_plan alone. "
                "Set student_loan_plan to an undergraduate plan (or 'None') before enabling the concurrent "
                "Postgraduate Loan flag."
            )


class AUEmployeeValidation(EmployeeValidationStrategy):
    country_code = "AU"
    SENSITIVE_FIELDS = ('tfn', 'super_member_number')
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
        # ZP-TAX-AU-2026-27-001 §14 declarations. Previously AU had no
        # FIELD_COLUMN_MAP at all — the same class of dead-plumbing gap
        # UK's paye_tax_code/ni_category and US's w4_filing_status/
        # state_tax_jurisdiction already had before their own fixes:
        # tfn/help_stsl_debt etc. reached compliance_fields JSON but never
        # the PayrollEmployee.au_* columns engine/countries/australia.py's
        # Schedule 1/8 calculator (ZP-TAX-AU-2026-27-001 build) reads.
        "tfn_status": {"choices": ["PROVIDED", "NOT_PROVIDED", "EXEMPTION"]},
        "residency_status": {"choices": ["RESIDENT", "FOREIGN_RESIDENT", "WORKING_HOLIDAY_MAKER"]},
        "tax_free_threshold_claimed": {"choices": ["true", "false", "True", "False"]},
        "medicare_levy_exemption": {"choices": ["FULL", "HALF"]},
        "withholding_variation_pct": {"pattern": re.compile(r"^\d+(\.\d{1,2})?$"), "error": "Withholding variation must be a number."},
        # State/territory of work — drives which of the 8 employer
        # payroll-tax packages (NSW/VIC/QLD/WA/SA/TAS/ACT/NT) an
        # employee's wages are attributed to; reuses the same generic
        # PayrollEmployee.work_state column US/CA already populate.
        "work_state": {
            "upper": True,
            "choices": ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"],
        },
    }
    duplicate_field = "tfn"

    FIELD_COLUMN_MAP = {
        "tfn_status": "au_tfn_status",
        "residency_status": "au_residency_status",
        "tax_free_threshold_claimed": "au_tax_free_threshold_claimed",
        "medicare_levy_exemption": "au_medicare_levy_exemption",
        "withholding_variation_pct": "au_withholding_variation_pct",
        "extra_pay_calendar": "au_extra_pay_calendar",
        "sapto_category": "au_sapto_category",
        "work_state": "work_state",
        # Same shape as UK's has_postgrad_loan reuse of study_loan_plan/
        # study_loan_balance — HELP/HECS is stored in the SAME generic
        # study_loan_plan/study_loan_balance pair UK's Student Loan uses
        # (see models.PayrollEmployee.study_loan_plan's own docstring),
        # never a parallel AU-only field.
        "help_stsl_debt": "study_loan_plan",
    }
    FIELD_VALUE_MAP = {
        "tax_free_threshold_claimed": lambda v: str(v).strip().lower() == "true",
        "withholding_variation_pct": lambda v: Decimal(v) if v else None,
        "help_stsl_debt": lambda v: "AU_HELP" if str(v).strip().lower() == "true" else None,
    }


class CAEmployeeValidation(EmployeeValidationStrategy):
    country_code = "CA"
    SENSITIVE_FIELDS = ('sin',)
    FIELD_SPECS = {
        "sin": {
            "required": True, "strip_chars": "- ",
            "pattern": re.compile(r"^\d{9}$"),
            "error": "SIN must be 9 digits (e.g. 123-456-789).",
        },
        "td1_claim_amount": {"pattern": re.compile(r"^\d+(\.\d{1,2})?$"), "error": "TD1 claim amount must be a number."},
        # ZP-TAX-CA-2026-001 §18: provincial/territorial TD1 and Quebec's
        # own TP-1015.3-V are legally distinct declarations from federal
        # TD1 — same "was collectible nowhere, engine reads it, now wired
        # end to end" gap this promotion already closed for td1_claim_amount.
        "provincial_td1_claim_amount": {"pattern": re.compile(r"^\d+(\.\d{1,2})?$"), "error": "Provincial TD1 claim amount must be a number."},
        "qc_tp1015_claim_amount": {"pattern": re.compile(r"^\d+(\.\d{1,2})?$"), "error": "TP-1015.3-V claim amount must be a number."},
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
        "td1_additional_tax": {"pattern": re.compile(r"^\d+(\.\d{1,2})?$"), "error": "TD1X additional tax must be a number."},
        "cpp_qpp_election_status": {"upper": True, "choices": ["ACTIVE", "STOPPED"]},
        "cpp_election_effective_date": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
            "error": "CPP/QPP election effective date must be YYYY-MM-DD.",
        },
        "remote_work_agreement": {
            "pattern": re.compile(r"^(?i:true|false)$"),
            "error": "Remote work agreement must be true or false.",
        },
        "remote_attachment_province": {
            "upper": True,
            "choices": ["ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"],
        },
        "remote_agreement_effective_from": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
            "error": "Remote agreement effective date must be YYYY-MM-DD.",
        },
    }
    duplicate_field = "sin"
    # Same class of dead-plumbing gap already closed for US
    # (state_tax_jurisdiction) and UK (paye_tax_code/ni_category/etc.)
    # above: "province" and "td1_claim_amount" were previously stored
    # ONLY in compliance_fields JSON — PayrollEmployee.work_state (the
    # column every country's state/province-scoped config resolver
    # actually reads) and the new td1_claim_amount column (the federal
    # BPA override engine/countries/canada.py now reads) never received
    # a value, so a CA employee's declared province and TD1 claim amount
    # were silently invisible to jurisdiction resolution and tax
    # calculation respectively, even though both have always been
    # collectible via the employee form. td1_additional_tax/
    # cpp_qpp_election_status/remote_work_agreement and their supporting
    # fields are NEW as of this promotion — never previously collectible
    # at all, backend or frontend.
    FIELD_COLUMN_MAP = {
        "province": "work_state",
        "td1_claim_amount": "td1_claim_amount",
        "provincial_td1_claim_amount": "provincial_td1_claim_amount",
        "qc_tp1015_claim_amount": "qc_tp1015_claim_amount",
        "td1_additional_tax": "td1_additional_tax",
        "cpp_qpp_election_status": "cpp_qpp_election_status",
        "cpp_election_effective_date": "cpp_election_effective_date",
        "remote_work_agreement": "remote_work_agreement",
        "remote_attachment_province": "remote_attachment_province",
        "remote_agreement_effective_from": "remote_agreement_effective_from",
    }
    FIELD_VALUE_MAP = {
        "td1_claim_amount": lambda v: Decimal(v) if v else None,
        "provincial_td1_claim_amount": lambda v: Decimal(v) if v else None,
        "qc_tp1015_claim_amount": lambda v: Decimal(v) if v else None,
        "td1_additional_tax": lambda v: Decimal(v) if v else None,
        "cpp_election_effective_date": lambda v: date.fromisoformat(v) if v else None,
        "remote_work_agreement": lambda v: str(v).strip().lower() == "true",
        "remote_agreement_effective_from": lambda v: date.fromisoformat(v) if v else None,
    }


class DEEmployeeValidation(EmployeeValidationStrategy):
    country_code = "DE"
    SENSITIVE_FIELDS = ('steuer_id', 'rv_nummer')   # IBAN is also DE's bank routing value — bank details are out of this scope
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


# ── Caribbean production jurisdictions (2026-09-21, fields added 2026-09-22) ──
# Every field below is deliberately NOT required and uses the SAME lenient
# pattern already established in core/jurisdiction.py's JURISDICTION_TAX_
# SCHEMAS for these 7 countries' EMPLOYER-level identifiers — none of the
# 7 engineering specs confirm the exact current issuing form/format for
# the employee-level identifier (e.g. Barbados: "acquire the currently
# issued form and identifier instead of hard-coding a form number"), so a
# strict pattern here would risk rejecting a real, valid ID. Optional
# (not required) for the same reason: onboarding an employee before their
# statutory number is issued/known is a real, common case (see e.g.
# Bahamas/Cayman's own "pending-registration workflow" language) that a
# required field would incorrectly block. Tightening any of these to a
# confirmed real format/requirement is a follow-up once each country's
# exact current form is acquired — same gate the specs themselves impose.
# Bank-routing fields (ZP-MJR-2026-002, 2026-09-24) — same lenient-pattern/
# not-required discipline as the tax IDs above: none of these 7 countries has
# a single confirmed national bank-clearing code format the way IFSC/sort-
# code/ABA do, so `bank_branch_code` is a generic free-text field rather
# than a guessed strict one. Bahamas and Puerto Rico are the two exceptions
# — both ride a NACHA-style 9-digit ACH routing rail (Puerto Rico via the
# US banking system directly), so they get `ach_routing_number` with the
# same shape as USEmployeeValidation's `aba_routing_number` instead.
class BBEmployeeValidation(EmployeeValidationStrategy):
    country_code = "BB"
    SENSITIVE_FIELDS = ('nis_number', 'tamis_tin')
    FIELD_SPECS = {
        "tamis_tin": {
            "pattern": re.compile(r"^\d{9,13}$"),
            "error": "TAMIS TIN must be 9 to 13 digits.",
        },
        "nis_number": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{4,20}$"),
            "error": "NIS number looks incorrect.",
        },
        "bank_branch_code": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{3,20}$"),
            "error": "Bank/branch code looks incorrect.",
        },
    }


class KYEmployeeValidation(EmployeeValidationStrategy):
    country_code = "KY"
    SENSITIVE_FIELDS = ('nib_member_number',)
    FIELD_SPECS = {
        "nib_member_number": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{4,20}$"),
            "error": "NIB member number looks incorrect.",
        },
        "bank_branch_code": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{3,20}$"),
            "error": "Bank/branch code looks incorrect.",
        },
    }


class DOEmployeeValidation(EmployeeValidationStrategy):
    country_code = "DO"
    SENSITIVE_FIELDS = ('cedula',)
    FIELD_SPECS = {
        # Cédula de identidad — the standard Dominican national ID format
        # (000-0000000-0), the one field in this whole Caribbean set with
        # a genuinely well-known, stable official format.
        "cedula": {
            "pattern": re.compile(r"^\d{3}-\d{7}-\d{1}$"),
            "error": "Cédula must be in the format 000-0000000-0.",
        },
        "bank_branch_code": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{3,20}$"),
            "error": "Bank/branch code looks incorrect.",
        },
    }


class GYEmployeeValidation(EmployeeValidationStrategy):
    country_code = "GY"
    SENSITIVE_FIELDS = ('gra_tin', 'nis_number')
    FIELD_SPECS = {
        "gra_tin": {
            "pattern": re.compile(r"^\d{7,10}$"),
            "error": "GRA TIN must be 7 to 10 digits.",
        },
        "nis_number": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{4,20}$"),
            "error": "NIS number looks incorrect.",
        },
        "bank_branch_code": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{3,20}$"),
            "error": "Bank/branch code looks incorrect.",
        },
    }


class JMEmployeeValidation(EmployeeValidationStrategy):
    country_code = "JM"
    SENSITIVE_FIELDS = ('trn',)
    FIELD_SPECS = {
        "trn": {
            "strip_chars": "-",
            "pattern": re.compile(r"^\d{9}$"),
            "error": "TRN must be 9 digits (e.g. 123456789 or 123-456-789).",
        },
        "bank_branch_code": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{3,20}$"),
            "error": "Bank/branch code looks incorrect.",
        },
    }


class BSEmployeeValidation(EmployeeValidationStrategy):
    country_code = "BS"
    SENSITIVE_FIELDS = ('nib_number',)
    FIELD_SPECS = {
        "nib_number": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{4,20}$"),
            "error": "NIB number looks incorrect.",
        },
        "ach_routing_number": {
            "pattern": re.compile(r"^\d{9}$"),
            "error": "ACH routing number must be exactly 9 digits.",
        },
    }


class TTEmployeeValidation(EmployeeValidationStrategy):
    country_code = "TT"
    SENSITIVE_FIELDS = ('bir_file_number', 'nibtt_number')
    FIELD_SPECS = {
        "bir_file_number": {
            "pattern": re.compile(r"^\d{9,10}$"),
            "error": "BIR file number must be 9 to 10 digits.",
        },
        "nibtt_number": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{4,20}$"),
            "error": "NIBTT number looks incorrect.",
        },
        "bank_branch_code": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{3,20}$"),
            "error": "Bank/branch code looks incorrect.",
        },
    }


class PREmployeeValidation(EmployeeValidationStrategy):
    country_code = "PR"
    FIELD_SPECS = {
        # US Social Security Number — Puerto Rico employees are US
        # citizens and are issued a real federal SSN, not a
        # territory-specific ID (ZP-PR-ENG-001 §2's "Worker identity"
        # object).
        "ssn": {
            "pattern": re.compile(r"^\d{3}-?\d{2}-?\d{4}$"),
            "error": "Social Security Number must be in the format 000-00-0000.",
        },
        "ach_routing_number": {
            "pattern": re.compile(r"^\d{9}$"),
            "error": "ACH routing number must be exactly 9 digits.",
        },
    }


class FREmployeeValidation(EmployeeValidationStrategy):
    """France (ZP-FR-ENG-001 §13/§15). The `nir` is authority identity
    (FR-037: never 'fixed' by synthesising a statutory identifier) and the
    employing establishment flows through the employee's `siret`. Both are
    format-validated here; the payroll-side mandatory-data gate (which
    blocks when NIR is unknown rather than guessing) lives in service.py,
    exactly as France's launch run-workspace requires (section 13:
    "Missing NIR material exceptions block approval")."""
    country_code = "FR"
    FIELD_SPECS = {
        "nir": {
            "pattern": re.compile(r"^\d{15}$"),
            "error": "NIR (numéro d'inscription au répertoire) must be exactly 15 digits.",
            "required": True,
        },
        "siret": {
            "pattern": re.compile(r"^\d{14}$"),
            "error": "SIRET must be exactly 14 digits.",
        },
        "nif": {
            "pattern": re.compile(r"^[0-9A-Za-z]{12}$"),
            "error": "FV/IFU-style foreign tax identifier is not valid (12 alphanumeric).",
        },
        "iban": {
            "upper": True, "strip_chars": " ",
            # FR (2) + 12 bank/branch digits + 11 account + 2 key = 27 chars
            "pattern": re.compile(r"^FR\d{12}[0-9A-Z]{11}\d{2}$"),
            "error": "French IBAN must be FR followed by 25 characters (12 digits, 11 alphanumeric, 2 digits).",
        },
        "bic": {
            "upper": True, "strip_chars": " ",
            "pattern": re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$"),
            "error": "BIC must be 8 or 11 characters.",
        },
    }


class IEEmployeeValidation(EmployeeValidationStrategy):
    """Ireland (ZP-IE-ENG-001 §9).

    Deliberately does NOT expose a manual MyFutureFund enrolment toggle
    (IE-018/IE-021, §9 "MyFutureFund"): NAERSA is the eligibility authority
    and payroll only applies a notified status. PRSI class is restricted to
    the certified launch cohort (A0/AX/AL/A1) so an uncertified class can
    never pass validation and reach the engine as if it were supported
    (IE-016) — anything outside this set is rejected here and therefore
    BLOCKED at preflight. RPN values (credits, rate bands, LPT) are
    likewise absent by design: they are authority-supplied and come from a
    frozen RpnSnapshot, never from an admin-typed field (IE-004)."""
    country_code = "IE"
    duplicate_field = "ppsn"
    FIELD_SPECS = {
        "ppsn": {
            "upper": True,
            "pattern": re.compile(r"^\d{7}[A-Z]?$"),
            "error": "PPSN must be 7 digits (an optional trailing letter is accepted for non-individual registrations).",
        },
        "employer_reference": {
            "pattern": re.compile(r"^[A-Za-z0-9-]{3,32}$"),
            "error": "Employer Reference must be 3-32 letters, digits or hyphens.",
        },
        "revenue_employment_id": {
            "upper": True,
            "pattern": re.compile(r"^[A-Z0-9-]{3,64}$"),
            "error": "Revenue Employment Identifier must be 3-64 letters, digits or hyphens.",
        },
        "prsi_class": {
            "choices": ["A0", "AX", "AL", "A1"],
        },
        "prsi_exemption_reference": {
            "pattern": re.compile(r"^[A-Za-z0-9/._-]{3,64}$"),
            "error": "PRSI exemption evidence reference looks incorrect.",
        },
        "usc_status": {
            "choices": ["Standard", "Reduced", "Exempt"],
        },
        "pension_scheme_reference": {
            "upper": True,
            "pattern": re.compile(r"^[A-Z0-9-]{3,64}$"),
            "error": "Pension scheme reference must be 3-64 letters, digits or hyphens.",
        },
        "pension_qualifying_exemption_reference": {
            "upper": True,
            "pattern": re.compile(r"^[A-Z0-9-]{3,64}$"),
            "error": "Qualifying pension exemption must cite a scheme reference (IE-021 — a bare checkbox is not an exemption).",
        },
        "pension_qualifying_exemption_effective_from": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
            "error": "Qualifying pension exemption effective date must be YYYY-MM-DD.",
        },
        "contracted_weekly_hours": {
            "pattern": re.compile(r"^\d{1,2}(\.\d{1,2})?$"),
            "error": "Contracted weekly hours must be a number (IE-035 requires working-hours evidence for the minimum-wage check).",
        },
        "sector_wage_order": {
            "choices": ["NONE", "ERO", "SEO"],
        },
        "iban": {
            "upper": True, "strip_chars": " ",
            "pattern": re.compile(r"^IE\d{2}[A-Z]{4}\d{6}\d{8}\d{2}$"),
            "error": "Irish IBAN must be IE followed by 22 characters (4 letters, then 16 digits).",
        },
        "bic": {
            "upper": True, "strip_chars": " ",
            "pattern": re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$"),
            "error": "BIC must be 8 or 11 characters.",
        },
    }

    @classmethod
    def _validate_combination(cls, cleaned: dict) -> None:
        errors = []
        claimed = cleaned.get("pension_qualifying_exemption_reference")
        if claimed and not cleaned.get("pension_qualifying_exemption_effective_from"):
            errors.append(
                "pension_qualifying_exemption_effective_from is required when a qualifying "
                "pension exemption is claimed."
            )
        if cleaned.get("pension_qualifying_exemption_effective_from") and not claimed:
            errors.append(
                "pension_qualifying_exemption_reference is required when a qualifying "
                "pension exemption effective date is supplied."
            )
        if errors:
            raise BadRequestException("; ".join(errors))


# ── Singapore (ZP-SG-ENG-001, 2026-09-23) ────────────────────────────────
# The CPF cohort facts are NOT required here, same reasoning as the
# Caribbean strategies above (onboarding before every fact is known is a
# real case) — engine/countries/singapore.py is the authoritative guard and
# BLOCKS the calculation while any of them is missing or contradictory.
# NRIC/FIN is a synthetic-safe structural check only (prefix letter, 7
# digits, suffix letter); no checksum is asserted since the spec doesn't
# supply one.
class SGEmployeeValidation(EmployeeValidationStrategy):
    country_code = "SG"
    SENSITIVE_FIELDS = ('nric_fin',)
    FIELD_SPECS = {
        "nric_fin": {
            "upper": True, "strip_chars": " ",
            "pattern": re.compile(r"^[STFGM]\d{7}[A-Z]$"),
            "error": "NRIC/FIN must be a letter (S/T/F/G/M), 7 digits and a letter.",
        },
        "cpf_residency_status": {"upper": True, "choices": ["SC", "SPR", "FOREIGN"]},
        "spr_effective_date": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
            "error": "SPR effective date must be YYYY-MM-DD.",
        },
        "cpf_contribution_arrangement": {"upper": True, "choices": ["GG", "FG", "FF"]},
        "work_pass_type": {"upper": True, "choices": ["NONE", "EP", "S_PASS", "WORK_PERMIT"]},
        # Work pass validity (MOM: S Pass levy liability runs from the day
        # the pass is issued until it is cancelled or expires).
        "work_pass_issue_date": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
            "error": "Work pass issue date must be YYYY-MM-DD.",
        },
        "work_pass_end_date": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
            "error": "Work pass end (cancellation/expiry) date must be YYYY-MM-DD.",
        },
        # Why the pass ends on work_pass_end_date: MOM states the levy stops
        # 1 day before a CANCELLATION; the expiry-day rule is not published.
        "work_pass_end_reason": {"upper": True, "strip_chars": " ", "pattern": re.compile(r"^(CANCELLED|EXPIRED)$"),
                                 "error": "Work pass end reason: CANCELLED or EXPIRED"},
        # Authority/HR-derived fund codes only (SG-015) — never race/religion.
        "shg_funds": {
            "upper": True, "strip_chars": " ",
            "pattern": re.compile(r"^(NONE|(CDAC|ECF|MBMF|SINDA)(=\d{1,4}(\.\d{1,2})?)?(,(CDAC|ECF|MBMF|SINDA)(=\d{1,4}(\.\d{1,2})?)?)*)$"),
            "error": "SHG funds must be NONE or a comma-separated list of CDAC, ECF, MBMF, SINDA — optionally with the "
                     "employee's SHG-instructed monthly amount, e.g. MBMF=10.00.",
        },
        # SHG opt-out / alternate-amount instruction evidence (SG-014) — the
        # reference to the signed form, never the form's personal content.
        "shg_evidence_ref": {
            "strip_chars": " ", "pattern": re.compile(r"^[A-Za-z0-9 ._/-]{1,60}$"),
            "error": "SHG evidence reference: up to 60 letters, digits or . _ / -",
        },
        # Work Permit levy classification (MOM sector pages) — engine-read,
        # mapped to the sgp_wp_* columns below.
        "wp_sector": {"upper": True, "choices": ["SERVICES", "MANUFACTURING", "CONSTRUCTION", "PROCESS", "MARINE_SHIPYARD"]},
        "wp_skill_level": {"upper": True, "choices": ["R1", "R2"]},
        "wp_levy_tier": {"upper": True,
                         "choices": ["TIER_1", "TIER_2", "TIER_3", "NTS", "MYS_NAS_PRC", "OFFSITE", "NO_CERT", "ALL"]},
        # Employment Act facts (MOM "Employment Act: who it covers"; SG-035) —
        # Part 4 coverage is COMPUTED from these plus basic salary, never typed.
        "ea_workman": {"upper": True, "choices": ["YES", "NO"]},
        "ea_manager_executive": {"upper": True, "choices": ["YES", "NO"]},
        "ea_contractual_weekly_hours": {
            "pattern": re.compile(r"^\d{1,2}(\.\d{1,2})?$"), "error": "Contractual weekly hours must be a number, e.g. 44",
        },
        "ea_rest_day": {"upper": True, "choices": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]},
        # MOM incomplete-month salary (Phase 5.2): the work week the MOM
        # working-day table covers — Mon–Fri, plus a Saturday half day
        # (5.5) or a Saturday (6); Sunday the rest day.
        "ea_work_pattern": {"upper": True, "choices": ["5_DAY", "5_5_DAY", "6_DAY"]},
        # SG-002 release scope: only STANDARD employment is calculated; the
        # other classes are recorded so the engine can refuse them (BLOCKED).
        # Not recorded = treated as STANDARD with a preflight warning.
        "employment_class": {"upper": True, "choices": ["STANDARD", "PLATFORM_WORKER", "SEAFARER", "OVERSEAS_ONLY", "EOR"]},
        # SG-045: the date a change to a statutory fact (residency, work pass,
        # Employment Act status, SHG, employment class) takes effect — required
        # with such a change, audited, never stored on the employee.
        "statutory_change_effective_date": {
            "pattern": re.compile(r"^\d{4}-\d{2}-\d{2}$"), "error": "Statutory change effective date: YYYY-MM-DD",
        },
        # Progressive Wage Model classification (MOM PWM sector pages; SG-034).
        "pwm_sector": {"upper": True, "choices": ["CLEANING", "SECURITY", "LANDSCAPE", "LIFT_ESCALATOR", "RETAIL",
                                                  "FOOD_SERVICES", "WASTE_MANAGEMENT", "OPW_ADMIN", "OPW_DRIVER",
                                                  "NONE"]},
        "pwm_group": {"upper": True, "strip_chars": " ", "pattern": re.compile(r"^[A-Z0-9_]{1,30}$"),
                      "error": "PWM group: a code such as OFFICE_COMMERCIAL, OUTSOURCED, CATEGORY_A"},
        "pwm_job_level": {"upper": True, "strip_chars": " ", "pattern": re.compile(r"^[A-Z0-9_]{1,40}$"),
                          "error": "PWM job level: a code such as GENERAL_CLEANER, SECURITY_OFFICER"},
    }
    duplicate_field = "nric_fin"
    FIELD_COLUMN_MAP = {
        "cpf_residency_status": "sgp_cpf_residency_status",
        "spr_effective_date": "sgp_spr_effective_date",
        "cpf_contribution_arrangement": "sgp_cpf_contribution_arrangement",
        "work_pass_type": "sgp_work_pass_type",
        "shg_funds": "sgp_shg_funds",
        "work_pass_issue_date": "sgp_work_pass_issue_date",
        "work_pass_end_date": "sgp_work_pass_end_date",
        "wp_sector": "sgp_wp_sector",
        "wp_skill_level": "sgp_wp_skill_level",
        "wp_levy_tier": "sgp_wp_levy_tier",
    }
    FIELD_VALUE_MAP = {
        "spr_effective_date": lambda v: date.fromisoformat(v) if v else None,
        "work_pass_issue_date": lambda v: date.fromisoformat(v) if v else None,
        "work_pass_end_date": lambda v: date.fromisoformat(v) if v else None,
    }

    @classmethod
    def _validate_combination(cls, cleaned: dict) -> None:
        residency = cleaned.get("cpf_residency_status")
        work_pass = cleaned.get("work_pass_type")
        if residency == "SC" and work_pass and work_pass != "NONE":
            raise BadRequestException("A Singapore Citizen cannot hold a work pass — set work_pass_type to NONE.")
        if residency == "FOREIGN" and work_pass == "NONE":
            raise BadRequestException("A foreign employee must have an EP, S Pass or Work Permit.")
        if residency == "SPR" and not cleaned.get("spr_effective_date"):
            raise BadRequestException("spr_effective_date is required for an SPR employee.")
        if "=" in (cleaned.get("shg_funds") or "") and not cleaned.get("shg_evidence_ref"):
            raise BadRequestException("An SHG instructed (alternate) amount needs the SHG evidence reference "
                                      "(shg_evidence_ref) — the amount is the employee's instruction to the SHG.")
        wp_facts = [k for k in ("wp_sector", "wp_skill_level", "wp_levy_tier") if cleaned.get(k)]
        if wp_facts and work_pass != "WORK_PERMIT":
            raise BadRequestException("Work Permit levy fields apply to Work Permit holders only.")
        if cleaned.get("wp_sector") and cleaned.get("wp_levy_tier"):
            from app.modules.payroll.engine.countries.singapore import WP_TIERS_BY_SECTOR

            if cleaned["wp_levy_tier"] not in WP_TIERS_BY_SECTOR[cleaned["wp_sector"]]:
                raise BadRequestException(
                    f"Levy tier {cleaned['wp_levy_tier']} does not exist for the {cleaned['wp_sector']} sector (MOM) — "
                    f"expected one of {', '.join(WP_TIERS_BY_SECTOR[cleaned['wp_sector']])}.")
        if cleaned.get("ea_workman") == "YES" and cleaned.get("ea_manager_executive") == "YES":
            raise BadRequestException("An employee cannot be both a workman and a manager/executive (Employment Act).")
        issued, ends = cleaned.get("work_pass_issue_date"), cleaned.get("work_pass_end_date")
        if (issued or ends) and work_pass in (None, "NONE"):
            raise BadRequestException("Work pass dates need a work pass (EP, S Pass or Work Permit).")
        if issued and ends and ends < issued:
            raise BadRequestException("The work pass end date cannot be before its issue date.")


def hkid_check_digit_valid(value: str) -> bool:
    """Hong Kong Identity Card check digit — the published mod-11 scheme:
    one or two prefix letters (A=10 … Z=35; a single-letter prefix is
    padded with a space = 36), six digits, check digit 0-9 or A (=10).
    Weights 9..2 over the 8 positions; the check digit makes the weighted
    sum divisible by 11. "A123456(3)" / "A1234563" are both accepted."""
    raw = re.sub(r"[()\s]", "", str(value or "").upper())
    m = re.fullmatch(r"([A-Z]{1,2})([0-9]{6})([0-9A])", raw)
    if not m:
        return False
    letters, digits, check = m.groups()
    chars = ([" "] if len(letters) == 1 else []) + list(letters) + list(digits)
    values = [36 if c == " " else (ord(c) - 55 if c.isalpha() else int(c)) for c in chars]
    total = sum(v * w for v, w in zip(values, range(9, 1, -1)))
    expected = (11 - total % 11) % 11
    return (10 if check == "A" else int(check)) == expected


class HKEmployeeValidation(EmployeeValidationStrategy):
    """Hong Kong (ZP-HK-ENG-001 §3, §15). Identity is collected only for the
    statutory purposes (IRD IR56 forms, eMPF enrolment — HK-022 data
    minimisation) and masked in every API response (SENSITIVE_FIELDS).
    Statutory FACTS (MPF exemption, residency, departure …) are NOT here:
    they live on the effective-dated EmployeeStatutoryProfile hkg_* columns."""
    country_code = "HK"
    SENSITIVE_FIELDS = ("hkid", "passport_number")
    duplicate_field = "hkid"
    FIELD_SPECS = {
        "hkid": {
            "pattern": re.compile(r"^[A-Z]{1,2}[0-9]{6}\(?[0-9A]\)?$"),
            "upper": True, "strip_chars": " ",
            "error": "HKID must look like A123456(3) — one or two letters, six digits and a check digit.",
        },
        "passport_number": {
            "pattern": re.compile(r"^[A-Z0-9]{5,20}$"), "upper": True, "strip_chars": " ",
            "error": "Passport number must be 5–20 letters/digits.",
        },
        "passport_country": {"pattern": re.compile(r"^[A-Z]{2,3}$"), "upper": True,
                             "error": "Passport issuing country must be a 2- or 3-letter code."},
        "mpf_member_account": {"pattern": re.compile(r"^[A-Za-z0-9-]{4,30}$"),
                               "error": "eMPF / MPF member account number looks incorrect."},
        # Salary bank routing (bank_routing.ROUTING_FIELDS["HK"]): HKICL clearing
        # and branch codes are 3 digits each.
        "bank_code": {"pattern": re.compile(r"^\d{3}$"), "error": "HK bank (clearing) code must be 3 digits."},
        "branch_code": {"pattern": re.compile(r"^\d{3}$"), "error": "HK branch code must be 3 digits."},
    }

    @classmethod
    def _validate_combination(cls, cleaned: dict) -> None:
        hkid = cleaned.get("hkid")
        if hkid and not hkid_check_digit_valid(hkid):
            raise BadRequestException(f"HKID {hkid!r} fails the check-digit test.")
        if cleaned.get("passport_number") and not cleaned.get("passport_country"):
            raise BadRequestException("passport_country is required with passport_number.")

# ── Sweden (ZP-SE-ENG-001, 2026-09-30) ────────────────────────────────────
# Only identity/registration-shaped facts live here: every withholding
# fact (tax status, table/column, decision, SINK, CBA) is an effective-
# dated EmployeeStatutoryProfile (se_* columns) version, never a bare
# compliance field — same split as IE/SG above. The engine
# (engine/countries/sweden.py) is the authoritative guard that BLOCKS a
# calculation while a required worker fact is missing (spec §5), so
# onboarding stays possible before every fact is known.
class SEEmployeeValidation(EmployeeValidationStrategy):
    """Sweden (ZP-SE-ENG-001 §2/§11).

    personnummer/coordination number is a structural check only (no Luhn
    checksum asserted — a coordination number adds 60 to the day of birth,
    and the spec supplies no checksum rule), and it is SENSITIVE: masked
    in every API response like every other national identifier. The
    residence municipality code is kept here (not only on the profile) so
    onboarding can capture it before a statutory profile version exists —
    SE-002 forbids deriving it from workplace location, so it is entered,
    never computed."""
    country_code = "SE"
    duplicate_field = "swedish_id_number"
    SENSITIVE_FIELDS = ('swedish_id_number',)
    FIELD_SPECS = {
        "swedish_id_number": {
            "upper": True, "strip_chars": " ",
            # YYMMDD or YYYYMMDD, optional separator (- ; + marks a person aged
            # 100 or over), then 4 digits. A coordination number has the same
            # shape with the day of birth + 60, so it passes the same check.
            "pattern": re.compile(r"^(\d{6}|\d{8})[-+]?\d{4}$"),
            "error": "Swedish identity number must be YYMMDD or YYYYMMDD followed by 4 digits (personnummer or "
                     "coordination number), optionally separated by - (or + for a person aged 100 or over).",
        },
        "employer_reference": {
            "upper": True,
            "pattern": re.compile(r"^[A-Za-z0-9-]{3,32}$"),
            "error": "Employer Reference must be 3-32 letters, digits or hyphens.",
        },
        "residence_municipality_code": {
            "pattern": re.compile(r"^\d{4}$"),
            "error": "Residence municipality must be the 4-digit Skatteverket municipality code (SE-002 — never derived from workplace location).",
        },
    }


# Italy (ZP-IT-ENG-001 §18) — codice fiscale check character (DM 23/12/1976):
# odd positions (1st, 3rd, ...) use this table, even positions the plain
# value (digits 0-9, letters A=0..Z=25); the sum modulo 26 gives the letter.
_IT_CF_ODD = dict(zip(
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    (1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 1, 0, 5, 7, 9, 13, 15, 17, 19, 21,
     2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23)))


def italian_codice_fiscale_is_valid(value: str) -> bool:
    """Shape AND check character. The shape allows omocodia (digits replaced
    by L-V letters), which the check character covers the same way."""
    if not value or not re.match(r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-EHLMPRST][0-9LMNPQRSTUV]{2}"
                                 r"[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$", value):
        return False
    total = sum(_IT_CF_ODD[c] if i % 2 == 0 else (int(c) if c.isdigit() else ord(c) - 65)
                for i, c in enumerate(value[:15]))
    return chr(total % 26 + 65) == value[15]


class ITEmployeeValidation(EmployeeValidationStrategy):
    """Italy (ZP-IT-ENG-001 §18).

    The codice fiscale is validated in shape AND check character, because
    IT-052 makes a wrong one blocking for tax and UniEmens reporting and
    forbids synthesising one — a typo must be caught at entry, not at the
    annual CU. It is SENSITIVE (masked in API responses). The tax domicile is
    entered as codes (ISTAT region, cadastral comune) and kept separate from
    the worksite (IT-013). No field here sets a rate: classifications are
    resolved against configured content, and an unconfigured one blocks the
    calculation (IT-002)."""
    country_code = "IT"
    duplicate_field = "codice_fiscale"
    SENSITIVE_FIELDS = ('codice_fiscale',)
    FIELD_SPECS = {
        "codice_fiscale": {
            "upper": True, "strip_chars": " ",
            "pattern": re.compile(r"^[A-Z0-9]{16}$"),
            "error": "Codice fiscale must be 16 letters and digits.",
        },
        "worker_class": {"upper": True, "pattern": re.compile(r"^[A-Z_]{3,30}$"),
                         "error": "INPS worker class: a code such as OPERAIO, IMPIEGATO, QUADRO"},
        "contract_type": {"upper": True, "choices": ["INDETERMINATO", "DETERMINATO", "APPRENDISTATO"]},
        "tfr_destination": {"upper": True, "choices": ["AZIENDA", "FONDO_PENSIONE", "FONDO_TESORERIA"]},
        "tax_domicile_region": {"pattern": re.compile(r"^(0[1-9]|1[0-9]|20)$"),
                                "error": "Tax domicile region: the 2-digit ISTAT region code (01-20)."},
        "tax_domicile_comune": {"upper": True, "pattern": re.compile(r"^[A-Z]\d{3}$"),
                                "error": "Tax domicile comune: the 4-character cadastral code, e.g. F205."},
        "contractual_weekly_hours": {"pattern": re.compile(r"^\d{1,2}(\.\d{1,2})?$"),
                                     "error": "Contractual weekly hours must be a number, e.g. 40 or 24.5."},
        "cnel_code": {"upper": True, "pattern": re.compile(r"^[A-Z0-9]{1,20}$"),
                      "error": "CNEL contract code: up to 20 letters and digits."},
        "cnel_level": {"upper": True, "pattern": re.compile(r"^[A-Z0-9 ._-]{1,20}$"),
                       "error": "CCNL level: up to 20 characters."},
    }

    @classmethod
    def _validate_combination(cls, cleaned: dict) -> None:
        cf = cleaned.get("codice_fiscale")
        if cf and not italian_codice_fiscale_is_valid(cf):
            raise BadRequestException("Codice fiscale check character does not match — check the code "
                                      "against the employee's tessera sanitaria (IT-052).")
        if cleaned.get("tfr_destination") == "FONDO_PENSIONE" and not cleaned.get("pension_fund"):
            raise BadRequestException("A pension-fund TFR destination needs the fund named (pension_fund).")


def swiss_ahv_number_is_valid(value: str) -> bool:
    """Shape AND EAN-13 check digit. The AHV/AVS number is the 13-digit EAN-13
    with the 756 (Switzerland) national prefix — e.g. 756.9217.0769.85 is
    digits 7569217076985; the 13th digit is the standard EAN-13 check digit
    (weights 1, 3, 1, 3, ... from the FIRST digit of the 12-digit payload).
    Tolerates the printed dot/space formatting; refuses every other shape."""
    raw = re.sub(r"[.\s-]", "", str(value or ""))
    if not re.fullmatch(r"756\d{10}", raw):
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(raw[:12]))
    return (10 - total % 10) % 10 == int(raw[12])


class CHEmployeeValidation(EmployeeValidationStrategy):
    """Switzerland — AHV/AVS number.

    The AHV/AVS number is validated in shape AND EAN-13 check digit, because a
    wrong one breaks the compensation office (Ausgleichskasse) contribution
    accounting and the Lohnausweis — a typo must be caught at entry against the
    AHV insurance card (AHV-Ausweis), never at the first AHV payment. It is
    SENSITIVE (masked in API responses) and the duplicate check key. No federal
    wage floor or income tax is captured here: source tax (Quellensteuer) and
    FAK top-ups are canton pack content (CH-PAYROLL-2026 canton packs), the
    federal rates resolve from the CH federal pack, and Switzerland has no
    federal statutory minimum wage (CH_WAGE_FLOOR)."""
    country_code = "CH"
    duplicate_field = "ahv_number"
    SENSITIVE_FIELDS = ('ahv_number',)
    FIELD_SPECS = {
        "ahv_number": {
            "required": True,
            # 756 national prefix + 10 digits + 1 EAN-13 check digit, dots/spaces
            # tolerated in entry (756.9217.0769.85) — stripped before matching.
            "strip_chars": ". ",
            "pattern": re.compile(r"^756\d{10}$"),
            "error": "AHV number must be the 13-digit AHV/AVS number 756.XXXX.XXXX.XX from the AHV insurance card.",
        },
    }

    @classmethod
    def _validate_combination(cls, cleaned: dict) -> None:
        n = cleaned.get("ahv_number")
        if n and not swiss_ahv_number_is_valid(n):
            raise BadRequestException("AHV number fails the EAN-13 check digit — check the number against the "
                                      "employee's AHV insurance card (AHV-Ausweis).")


_STRATEGIES = {
    "IN": INEmployeeValidation,
    "US": USEmployeeValidation,
    "UK": UKEmployeeValidation,
    "AU": AUEmployeeValidation,
    "CA": CAEmployeeValidation,
    "DE": DEEmployeeValidation,
    "BB": BBEmployeeValidation,
    "KY": KYEmployeeValidation,
    "DO": DOEmployeeValidation,
    "GY": GYEmployeeValidation,
    "JM": JMEmployeeValidation,
    "BS": BSEmployeeValidation,
    "TT": TTEmployeeValidation,
    "PR": PREmployeeValidation,
    "FR": FREmployeeValidation,
    "IE": IEEmployeeValidation,
    "SG": SGEmployeeValidation,
    "HK": HKEmployeeValidation,
    "SE": SEEmployeeValidation,
    "IT": ITEmployeeValidation,
    "CH": CHEmployeeValidation,
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


# ── Sensitive identifier masking (shared, every jurisdiction) ───────────

def mask_identifier(value) -> Optional[str]:
    """First character and last 4 kept, the rest masked — the masking the
    Singapore IR8A extract already used (S1234567D -> S****567D). Values
    of 5 characters or fewer are masked entirely."""
    if value is None or value == "":
        return None
    value = str(value)
    return value[0] + "*" * max(len(value) - 5, 0) + value[-4:] if len(value) > 5 else "*" * len(value)


def mask_nric_fin(value) -> Optional[str]:
    """Singapore NRIC / FIN — PDPC "Advisory Guidelines on the PDPA for NRIC
    and other National Identification Numbers" (31 Aug 2018) §5.2: a partial
    NRIC is "up to the last 3 numerical digits and checksum" (e.g. "567A"
    of S1234567A). Everything else, including the S/T/F/G/M prefix, is
    masked: S1234567D -> *****567D."""
    if value is None or value == "":
        return None
    value = str(value)
    return "*" * (len(value) - 4) + value[-4:] if len(value) > 4 else "*" * len(value)


# Field-specific maskers — only Singapore's nric_fin differs from the
# shared mask_identifier; every other field (and country) is unchanged.
_FIELD_MASKERS = {"nric_fin": mask_nric_fin}


def _mask_field(key, value):
    return _FIELD_MASKERS.get(key, mask_identifier)(value)


SENSITIVE_COMPLIANCE_FIELDS = frozenset(f for cls in _STRATEGIES.values() for f in cls.SENSITIVE_FIELDS)


def mask_compliance_fields(compliance_fields):
    """Copy of compliance_fields with every sensitive identifier masked —
    for API responses only; the stored values (used by server-side filing
    and report generation) are never changed."""
    if not isinstance(compliance_fields, dict):
        return compliance_fields
    return {k: (_mask_field(k, v) if k in SENSITIVE_COMPLIANCE_FIELDS and v not in (None, "") else v)
            for k, v in compliance_fields.items()}


def restore_masked_compliance_fields(incoming, stored):
    """An edit form round-trips the masked value it was shown; a sensitive
    field whose incoming value is exactly the mask of the stored value is
    therefore unchanged, and keeps the stored value (a masked string must
    never overwrite a real identifier). Any other value is a genuine edit."""
    if not isinstance(incoming, dict) or not isinstance(stored, dict):
        return incoming
    out = dict(incoming)
    for key in SENSITIVE_COMPLIANCE_FIELDS & set(out):
        original = stored.get(key)
        if original not in (None, "") and out[key] == _mask_field(key, original):
            out[key] = original
    return out


# Top-level PayrollEmployee columns holding a personal account or tax
# identifier (India's PAN / UAN, every country's bank account number) —
# masked in API responses exactly like SENSITIVE_COMPLIANCE_FIELDS.
SENSITIVE_EMPLOYEE_COLUMNS = ("bank_account", "pan", "uan")


def restore_masked_employee_columns(values, employee):
    """Same round-trip rule as restore_masked_compliance_fields, for the
    top-level columns: an incoming value equal to the mask of the stored
    value is unchanged and keeps the stored value."""
    if not isinstance(values, dict) or employee is None:
        return values
    out = dict(values)
    for key in SENSITIVE_EMPLOYEE_COLUMNS:
        original = getattr(employee, key, None)
        if key in out and original not in (None, "") and out[key] == mask_identifier(original):
            out[key] = original
        elif isinstance(out.get(key), str) and "*" in out[key]:
            # A masked-looking value that is not this employee's own mask
            # would otherwise be stored verbatim (these columns have no
            # format validator) — refuse it rather than corrupt the record.
            raise BadRequestException(f"{key} looks masked — enter the full value to change it.")
    return out


def mask_routing(routing):
    """`routing` display rows: bank ROUTING codes stay visible; an entry that
    is itself an account identifier (IBAN) is masked."""
    if not isinstance(routing, list):
        return routing
    return [({**r, "value": mask_identifier(r.get("value"))} if isinstance(r, dict) and r.get("key") == "iban" and r.get("value")
             else r) for r in routing]
