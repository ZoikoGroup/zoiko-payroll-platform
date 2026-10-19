"""
core/authz/fields.py
--------------------
Field-level classification of worker data (ZP-PRIV B04 / C04).

Every PayrollEmployee column is mapped to exactly one class, under BOTH its
DB column name and its camelCase API alias (tests/privacy/test_field_classes
fails when a new column has no class). The classes drive two things:

  * projection — a temporary support user (JIT grant) only ever receives the
    field classes the tenant ticked on approval (default identifier+contact);
    every other key, and every key not in this map, is dropped (fail closed);
  * masking   — inside an allowed class, the dedicated sensitive columns
    (bank_account, pan, uan, ifsc, date_of_birth, address lines, tax_code)
    are masked for any non-operator principal. Tenant payroll operators keep
    full values: bank-file generation needs them.

Class meanings:
  identifier  - who the worker is inside the org: name, code, role, dates
  contact     - email, phone, postal address, residence
  bank        - bank name, account, IFSC/routing
  tax         - national/tax ids, withholding elections, residency, statutory
                attributes, compliance_fields/custom_fields (free-form, may
                hold national ids - treated as the most sensitive class)
  salary      - compensation amounts
  leave       - leave balances, absences, health information
"""

from __future__ import annotations


from typing import Any, Dict, FrozenSet, Iterable

FIELD_IDENTIFIER = "identifier"
FIELD_CONTACT = "contact"
FIELD_BANK = "bank"
FIELD_TAX = "tax"
FIELD_SALARY = "salary"
FIELD_LEAVE = "leave"

FIELD_CLASSES = frozenset({
    FIELD_IDENTIFIER, FIELD_CONTACT, FIELD_BANK, FIELD_TAX, FIELD_SALARY, FIELD_LEAVE,
})

# What a support grant gets unless the tenant ticks more (D.1 step 3).
DEFAULT_SUPPORT_FIELD_CLASSES: FrozenSet[str] = frozenset({FIELD_IDENTIFIER, FIELD_CONTACT})

_IDENTIFIER = (
    "id", "organization_id", "employee_code", "legacy_code", "name", "department",
    "designation", "employment_type", "status", "date_of_joining", "date_of_leaving",
    "gender", "country_code", "pay_frequency", "payroll_scope_status", "is_director",
    "work_state", "work_locality", "legal_entity_id", "pay_group_id",
    "created_at", "updated_at",
)
_CONTACT = (
    "email", "phone", "address_line1", "address_line2", "address_town", "address_county",
    "address_postcode", "residence_state", "residence_locality", "date_of_birth",
)
_BANK = ("bank_name", "bank_account", "ifsc", "routing")
_SALARY = ("ctc", "basic", "hra")
_TAX = (
    "pan", "uan", "tax_residency_status", "director_ni_method", "tax_regime", "tax_code",
    "ni_category", "w4_filing_status", "w4_form_vintage", "w4_step2_checkbox",
    "w4_allowances_claimed", "is_nonresident_alien", "w4_dependents_credit_annual",
    "w4_other_income_annual", "w4_extra_withholding_per_period", "ct_withholding_code",
    "nj_rate_table", "ks_k4_dependents", "td1_claim_amount", "provincial_td1_claim_amount",
    "qc_tp1015_claim_amount", "td1_additional_tax", "td1x_estimated_annual_commission",
    "td1x_estimated_annual_expenses", "lsvcc_investment_amount", "cpp_qpp_election_status",
    "cpp_election_effective_date", "remote_work_agreement", "remote_attachment_province",
    "remote_agreement_effective_from", "reciprocity_certificate_on_file",
    "reciprocity_certificate_expiry", "residency_certification_on_file",
    "residency_certification_date", "state_income_tax_election_pct", "au_tfn_status",
    "au_residency_status", "au_tax_free_threshold_claimed", "au_medicare_levy_exemption",
    "au_withholding_variation_pct", "au_extra_pay_calendar", "au_sapto_category",
    "sgp_cpf_residency_status", "sgp_spr_effective_date", "sgp_cpf_contribution_arrangement",
    "sgp_work_pass_type", "sgp_shg_funds", "sgp_work_pass_issue_date", "sgp_work_pass_end_date",
    "sgp_wp_sector", "sgp_wp_skill_level", "sgp_wp_levy_tier", "study_loan_plan",
    "study_loan_balance", "has_postgrad_loan", "church_tax_liable", "starter_declaration",
    "compliance_fields", "custom_fields",
)

# Dedicated sensitive columns masked for non-operator principals even when
# their class is allowed (B04).
MASKED_COLUMNS: FrozenSet[str] = frozenset({
    "bank_account", "pan", "uan", "ifsc", "routing", "date_of_birth", "tax_code",
    "address_line1", "address_line2", "address_postcode",
})

# Roles that run payroll for their own tenant and need full values.
OPERATOR_ROLES: FrozenSet[str] = frozenset({"org_admin", "payroll_admin"})


def to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def _build() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for cls, names in (
        (FIELD_IDENTIFIER, _IDENTIFIER), (FIELD_CONTACT, _CONTACT), (FIELD_BANK, _BANK),
        (FIELD_SALARY, _SALARY), (FIELD_TAX, _TAX),
    ):
        for n in names:
            out[n] = cls
            out[to_camel(n)] = cls
    return out


# API serialization aliases that differ from the camelCase column name
# (EmployeeResponse writes bankAccount as bankAccountNumber, and so on).
_SERIALIZATION_ALIASES = {"bankAccountNumber": "bank_account", "panNumber": "pan", "ifscCode": "ifsc"}

# column name, camelCase alias AND API alias -> field class.
COLUMN_FIELD_CLASS: Dict[str, str] = _build()
COLUMN_FIELD_CLASS.update({alias: COLUMN_FIELD_CLASS[col] for alias, col in _SERIALIZATION_ALIASES.items()})
MASKED_KEYS: FrozenSet[str] = frozenset(
    MASKED_COLUMNS | {to_camel(c) for c in MASKED_COLUMNS}
    | {alias for alias, col in _SERIALIZATION_ALIASES.items() if col in MASKED_COLUMNS})


def field_class_of(key: str) -> str | None:
    """None for an unmapped key — projection drops it (fail closed)."""
    return COLUMN_FIELD_CLASS.get(key)


def is_masked_for(role: str, key: str) -> bool:
    return role not in OPERATOR_ROLES and key in MASKED_KEYS



def mask_value(value: Any) -> Any:
    """Keep the last 4 characters of a string value; mask everything else."""
    if value is None:
        return None
    s = str(value)
    if len(s) <= 4:
        return "*" * len(s)
    return "*" * (len(s) - 4) + s[-4:]


def project_record(record: Dict[str, Any], allowed: Iterable[str], role: str) -> Dict[str, Any]:
    """Keep only keys whose class is allowed, masking sensitive ones."""
    allowed = frozenset(allowed)
    out: Dict[str, Any] = {}
    for key, value in record.items():
        cls = field_class_of(key)
        if cls is None or cls not in allowed:
            continue
        out[key] = mask_value(value) if is_masked_for(role, key) else value
    return out
