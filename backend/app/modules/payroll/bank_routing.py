"""
modules/payroll/bank_routing.py
--------------------------------
Multi-jurisdiction routing / bank-code abstraction (ZP-MJR-2026-001).

Each jurisdiction's salary payment uses one canonical routing code:

    IN -> IFSC               UK -> Sort Code      US -> ABA routing number
    CA -> Transit + Institution Number   DE -> IBAN + BIC   AU -> BSB

This module is the single source of truth for:

  * the per-country routing fields exposed on employee/payslip APIs,
  * the Bank Transfer File (BTF) routing column header and value, and
  * the payslip payment-mode label (NEFT/BACS/ACH/EFT/SEPA/Direct Entry).

Storage stays exactly as today — nothing is renamed or duplicated:

  * India keeps its dedicated `ifsc` column (PayrollEmployee.ifsc →
    PayslipItem.ifsc), snapshotted at run generation.
  * Every other country keeps its codes in the per-country
    `compliance_fields` JSON, already validated by
    employee_validation.py's Strategy classes and snapshotted onto
    PayslipItem.compliance_fields at run generation.

This module is deliberately standalone (no imports from payroll models or
service) so both `models.py` (which exposes a computed `routing` property)
and `service.py` / `bank_export/*` can consume it with zero import-cycle
risk. It is pure — a routing resolution never touches the database.
"""

import re
from typing import List, Optional

# ── Jurisdiction registry ────────────────────────────────────────────────

# Countries with a canonical salary-payment routing code in scope.
# Caribbean production jurisdictions (ZP-MJR-2026-002, 2026-09-24):
# Barbados/Cayman/Dominican Republic/Guyana/Jamaica/Trinidad have no
# confirmed national bank-clearing standard, so they route through a
# generic `bank_branch_code` field; Bahamas and Puerto Rico both ride a
# NACHA-style 9-digit ACH rail (Puerto Rico via the US banking system
# directly) and route through `ach_routing_number`.
# France (ZP-FR-ENG-001, 2026-09-24) joins DE on the SEPA rail: IBAN + BIC
# read from compliance_fields, exactly like every non-India country.
ROUTING_COUNTRIES = ("IN", "UK", "US", "CA", "DE", "AU", "BB", "KY", "DO", "GY", "JM", "BS", "TT", "PR", "FR")

# Per-country routing fields, in display order. `key` is the storage key:
# "ifsc" is India's dedicated top-level column; every other key is read
# from that country's `compliance_fields` JSON.
ROUTING_FIELDS = {
    "IN": [{"key": "ifsc", "label": "IFSC"}],                              # dedicated column
    "UK": [{"key": "sort_code", "label": "Sort code"}],
    "US": [{"key": "aba_routing_number", "label": "ABA routing number"}],
    "CA": [
        {"key": "transit_number", "label": "Transit number"},
        {"key": "financial_institution_number", "label": "Institution number"},
    ],
    "DE": [
        {"key": "iban", "label": "IBAN"},
        {"key": "bic", "label": "BIC"},
    ],
    "FR": [
        {"key": "iban", "label": "IBAN"},
        {"key": "bic", "label": "BIC"},
    ],
    "AU": [{"key": "bsb_code", "label": "BSB code"}],
    "BB": [{"key": "bank_branch_code", "label": "Bank/Branch Code"}],
    "KY": [{"key": "bank_branch_code", "label": "Bank/Branch Code"}],
    "DO": [{"key": "bank_branch_code", "label": "Bank/Branch Code"}],
    "GY": [{"key": "bank_branch_code", "label": "Bank/Branch Code"}],
    "JM": [{"key": "bank_branch_code", "label": "Bank/Branch Code"}],
    "TT": [{"key": "bank_branch_code", "label": "Bank/Branch Code"}],
    "BS": [{"key": "ach_routing_number", "label": "ACH Routing #"}],
    "PR": [{"key": "ach_routing_number", "label": "ACH Routing #"}],
}

# Canonical name used as the BTF routing column header per country. India
# must stay literally "IFSC" so India bank-transfer output remains
# byte-identical to what it was before this abstraction existed.
BTF_ROUTING_LABEL = {
    "IN": "IFSC",
    "UK": "Sort Code",
    "US": "ABA Routing #",
    "CA": "Transit No.",
    "DE": "IBAN",
    "AU": "BSB",
    "FR": "IBAN",
    "BB": "Bank/Branch Code",
    "KY": "Bank/Branch Code",
    "DO": "Bank/Branch Code",
    "GY": "Bank/Branch Code",
    "JM": "Bank/Branch Code",
    "TT": "Bank/Branch Code",
    "BS": "ACH Routing #",
    "PR": "ACH Routing #",
}

# Payment rail shown on the payslip for each jurisdiction.
PAYMENT_MODE_LABEL = {
    "IN": "NEFT",
    "UK": "BACS",
    "US": "ACH",
    "CA": "EFT",
    "DE": "SEPA",
    "AU": "Direct Entry",
    "FR": "SEPA",
    "BB": "EFT",
    "KY": "EFT",
    "DO": "EFT",
    "GY": "EFT",
    "JM": "EFT",
    "TT": "EFT",
    "BS": "ACH",
    "PR": "ACH",
}


# ── Helpers ──────────────────────────────────────────────────────────────

def normalize_country(country: Optional[str]) -> Optional[str]:
    """Upper-case a country code; returns None for empty/unknown values."""
    if not country:
        return None
    code = str(country).strip().upper()
    return code if code in ROUTING_FIELDS else None


def _country_of(obj, country: Optional[str] = None) -> Optional[str]:
    """Resolve the effective country for an employee/payslip-like object.

    An explicit `country` argument wins (BTF/resolution callers know the
    org's jurisdiction even when a legacy row has a NULL snapshotted
    country); otherwise the object's own `country_code` is used."""
    if country:
        return normalize_country(country)
    return normalize_country(getattr(obj, "country_code", None))


def _field_value(obj, key: str) -> str:
    """Read one routing value from an employee/payslip-like object.

    India's `ifsc` is a dedicated top-level column; every other key lives
    in the per-country `compliance_fields` JSON. Both are snapshotted onto
    PayslipItem at run generation, so this one accessor works identically
    for PayrollEmployee and PayslipItem (and anything else that exposes
    `.ifsc` / `.compliance_fields`)."""
    if key == "ifsc":
        value = getattr(obj, "ifsc", None)
        return str(value) if value is not None else ""
    fields = dict(getattr(obj, "compliance_fields", None) or {})
    value = fields.get(key)
    return str(value) if value is not None else ""


# ── Public API ───────────────────────────────────────────────────────────

def resolve_routing(obj, country: Optional[str] = None) -> List[dict]:
    """The employee/payslip routing block: [{key, label, value}, ...].

    Additive API surface — callers keep `ifsc`/`ifscCode`/`complianceFields`
    exactly as before and may additionally read `routing` for a
    jurisdiction-correct list of routing codes. Returns [] when the
    object's country is unknown or has no routing fields configured."""
    effective = _country_of(obj, country)
    if not effective:
        return []
    return [
        {"key": spec["key"], "label": spec["label"], "value": _field_value(obj, spec["key"])}
        for spec in ROUTING_FIELDS[effective]
    ]


def btf_routing_value(obj, country: Optional[str] = None) -> str:
    """The single combined BTF routing-column value for one row.

    Keeps BTF at exactly 12 columns for every jurisdiction:

      IN  ifsc
      UK  sort_code
      US  aba_routing_number
      CA  "{transit_number}-{financial_institution_number}"  (e.g. 12345-001)
      DE  "{iban} {bic}"                                     (IBAN alone if no BIC on file)
      AU  bsb_code

    Always returns a string (empty when nothing is on file) so exporters
    never need their own None-handling."""
    effective = _country_of(obj, country)
    if effective == "CA":
        transit = _field_value(obj, "transit_number")
        institution = _field_value(obj, "financial_institution_number")
        if transit and institution:
            return f"{transit}-{institution}"
        return transit or institution
    if effective == "DE":
        iban = _field_value(obj, "iban")
        bic = _field_value(obj, "bic")
        if iban and bic:
            return f"{iban} {bic}"
        return iban or bic
    fields = ROUTING_FIELDS.get(effective, [])
    if not fields:
        return ""
    return _field_value(obj, fields[0]["key"])


def btf_routing_label(country: Optional[str] = None) -> str:
    """The BTF routing column header for a country (canonical code name)."""
    return BTF_ROUTING_LABEL.get(normalize_country(country) or "", "Routing Code")


def payment_mode_label(country: Optional[str] = None) -> str:
    """Payslip payment-mode label (NEFT/BACS/ACH/EFT/SEPA/Direct Entry)."""
    return PAYMENT_MODE_LABEL.get(normalize_country(country) or "", "Bank Transfer")


# ── Soft (non-blocking) IFSC guidance ────────────────────────────────────

_IN_IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def ifsc_warning(ifsc: Optional[str]) -> Optional[str]:
    """Non-blocking IFSC-format advisory.

    Deliberately NOT enforced on the write path: legacy/messy values are
    never rejected (India's dedicated column predates any pattern), but
    screen-level helpers can flag a likely typo without stopping a save."""
    if not ifsc:
        return None
    if _IN_IFSC_PATTERN.match(str(ifsc).upper()):
        return None
    return "IFSC format looks incorrect (e.g. HDFC0001234) — please verify before payment."