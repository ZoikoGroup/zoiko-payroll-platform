"""
modules/payroll/service.py
--------------------------
Business logic for the Zoiko Payroll module.

Replaces all client-side mock computation (the old `generatePayslips()` in
PayslipsPage.jsx) with real, server-side, persisted calculations. Contribution
rates and tax slabs are stored per-organization in the database (seeded with
sensible defaults on first access) so they are genuinely configurable data,
not hardcoded constants baked into the frontend.

IMPORTANT — payroll tax accuracy disclaimer:
The PF/ESI/PT/TDS calculations implement the standard *simplified* formulas
(flat percentages of basic/gross, progressive slab tax on an annualized
gross with no deductions/exemptions modeled) — see
`engine/standard.py`'s per-country strategies for the actual calculation.
Real statutory payroll (especially TDS, which depends on regime, Section
80C/80D declarations, HRA exemption rules, etc., and Professional Tax,
which is state-specific) is genuinely complex. Before going live, either
have `engine/standard.py` reviewed by a payroll/compliance specialist for
your jurisdiction, or replace it with a certified payroll engine.
"""

import os
import os as _os
import re
import copy
from dataclasses import dataclass
from typing import List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timedelta
from calendar import month_name

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func as sa_func, tuple_, or_, and_, case

from app.modules.payroll.models import (
    PayrollEmployee, EmploymentType, EmployeeStatus,
    PayrollRun, PayslipItem, PayslipAllowanceItem, PayrollAttendanceRecord, PayrollLeaveAllocation,
    PayrollLeaveRequest,
    ContributionRate, TaxSlab, CompanyComplianceDetails, ComplianceDocument, PayrollActivityLog,
    JurisdictionPack, PayrollHoliday, TaxConfigurationAudit,
    PayrollStatus, PayslipStatus, ActivityStatus, ComplianceDocumentStatus,
    PAYROLL_STATUS_ORDER,
    EmployerTaxProfile, ReciprocityRule, SourceArtifact, LocalityDataset, LocalityRate,
    ReportTemplate, ReportTemplateComponent, ReportTemplateComponentField, GeneratedReport,
    StatutoryFilingCalendar,
)
from app.modules.payroll.employee_validation import get_employee_validation_strategy
from app.modules.payroll.schemas import (
    PayrollRunCreate, PayrollRunUpdate, PayslipItemCreate, CompanyDetailsUpdate,
    EmployeeCreate, EmployeeUpdate, BulkEmployeeItem, BulkEmployeeRequest,
    BulkDeleteRequest,
    AttendanceRecordCreate, BulkAttendanceRequest,
    JurisdictionPackUpsert, CanonicalTaxSlabUpsert, CanonicalContributionRateUpsert,
    EmployerTaxProfileUpsert, ReciprocityRuleUpsert, SourceArtifactCreate, LocalityRateUpsert,
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
    FilingCalendarUpsert,
)
from app.core.exceptions import NotFoundException, BadRequestException
from fastapi import HTTPException, status as http_status

# Sourced from engine/standard.py — the real calculation engine — instead of
# redefined here, so there is exactly one place each value can drift from.
# _get_slab_label() below (a display-only helper, not part of calculation)
# is the only other place in this file that still needs the per-country
# deduction constants; it imports the rest of what it needs at its own
# definition further down for the same reason.
from app.modules.payroll.engine.standard import MONTHS_PER_YEAR


# ── Country code normalization ──────────────────────────────────────────
# CompanyComplianceDetails.jurisdiction_country stores full names ("India"),
# but the engine uses 2-letter codes ("IN"). This mapping handles both.

_COUNTRY_NAME_TO_CODE = {
    "india": "IN", "in": "IN",
    "united states": "US", "us": "US", "usa": "US", "united states of america": "US",
    "united kingdom": "UK", "uk": "UK", "great britain": "UK", "gb": "UK",
    "australia": "AU", "au": "AU",
    "germany": "DE", "de": "DE",
    "canada": "CA", "ca": "CA",
}


def _normalize_country(country: str) -> str:
    """Normalize a jurisdiction country to a 2-letter code (IN/US/UK).
    Accepts full names, 2-letter codes, or mixed case."""
    if not country:
        return "IN"
    key = country.strip().lower()
    return _COUNTRY_NAME_TO_CODE.get(key, country.strip().upper()[:2])


def _round2(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── Org-scoping helpers ─────────────────────────────────────────────────

def _apply_org_filter(query, model, organization_id: int = None):
    if organization_id is not None:
        return query.filter(model.organization_id == organization_id)
    return query


def log_activity(db: Session, organization_id: int, description: str,
                  status: ActivityStatus = ActivityStatus.INFO, actor_id: int = None):
    entry = PayrollActivityLog(
        organization_id=organization_id,
        description=description,
        status=status,
        actor_id=actor_id,
    )
    db.add(entry)
    db.commit()
    return entry


# ── Contribution rates / tax slabs (seeded, then DB-backed) ────────────

# Moved to hardcoded_defaults.py (the consolidated home for every
# hardcoded fallback/statutory value in the payroll module) — imported
# back under this exact name so scripts/populate_canonical_tax_v1.py and
# engine/fallback_registry.py, which import it directly from this module,
# keep working unchanged.
from app.modules.payroll.hardcoded_defaults import _CONTRIBUTION_RATES_BY_COUNTRY  # noqa: E402


def _seed_contribution_rates(db: Session, organization_id: int, country: str = "IN") -> List[ContributionRate]:
    defaults = _CONTRIBUTION_RATES_BY_COUNTRY.get(country, [])
    if not defaults:
        import logging
        logging.getLogger("zoiko").warning(
            f"[payroll-seed] no default contribution rates available for country '{country}' — "
            f"org {organization_id} will have zero rates until a canonical tax pack or manual rates are configured."
        )
    rows = []
    for d in defaults:
        row = ContributionRate(organization_id=organization_id, jurisdiction_country=country, **d)
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def _seed_org_rates_for_country(db: Session, organization_id: int, country: str) -> bool:
    """First-use seed for an org+country: pulls from the canonical
    Super-Admin-owned tax pack (engine/tax_resolver.py) when one exists,
    falling back to the hardcoded _CONTRIBUTION_RATES_BY_COUNTRY/
    _TAX_SLABS_BY_COUNTRY dicts otherwise — so a jurisdiction with no
    canonical pack configured yet (a brand-new country Super Admin hasn't
    set up) still seeds exactly as it did before this existed. Returns
    True if canonical data was used."""
    result = sync_org_rates_from_canonical(db, organization_id, country)
    return bool(result.get("synced"))


def get_contribution_rates(
    db: Session, organization_id: int = None, country: str = "IN", tax_regime: str = None,
    filing_status: str = None,
) -> List[ContributionRate]:
    query = db.query(ContributionRate)
    query = _apply_org_filter(query, ContributionRate, organization_id)
    query = query.filter(ContributionRate.jurisdiction_country == country)
    order_priority = []
    if tax_regime:
        # Regime-agnostic rows (tax_regime IS NULL — PF/ESI/PT and every
        # existing row today) always apply; a row tagged for this specific
        # regime ALSO applies and is ordered last, so a caller building a
        # {component_key: row} dict from this list naturally lets the
        # regime-specific row win when both exist for the same key. Rows
        # tagged for the OTHER regime are excluded entirely.
        query = query.filter(or_(ContributionRate.tax_regime.is_(None), ContributionRate.tax_regime == tax_regime))
        order_priority.append(ContributionRate.tax_regime.isnot(None))
    if filing_status:
        # Same convention as tax_regime above (US-specific need; NULL/unused
        # by every other jurisdiction so this branch never runs for them):
        # filing-status-agnostic rows always apply, a row tagged for THIS
        # filing status also applies and wins the dict collapse, rows
        # tagged for a DIFFERENT filing status are excluded entirely. An
        # org that hasn't configured any filing-status-specific row is
        # completely unaffected — the filter matches every row exactly as
        # if it weren't there.
        query = query.filter(or_(ContributionRate.filing_status.is_(None), ContributionRate.filing_status == filing_status))
        order_priority.append(ContributionRate.filing_status.isnot(None))
    rows = query.order_by(*order_priority, ContributionRate.sort_order).all() if order_priority else query.order_by(ContributionRate.sort_order).all()
    if not rows and organization_id:
        if not _seed_org_rates_for_country(db, organization_id, country):
            _seed_contribution_rates(db, organization_id, country)
        rows = (
            db.query(ContributionRate)
            .filter(ContributionRate.organization_id == organization_id, ContributionRate.jurisdiction_country == country)
            .order_by(ContributionRate.sort_order)
            .all()
        )
    return rows


# Moved to hardcoded_defaults.py — imported back under this exact name,
# same reasoning as _CONTRIBUTION_RATES_BY_COUNTRY above.
from app.modules.payroll.hardcoded_defaults import _TAX_SLABS_BY_COUNTRY  # noqa: E402


def _seed_tax_slabs(db: Session, organization_id: int, country: str = "IN") -> List[TaxSlab]:
    defaults = _TAX_SLABS_BY_COUNTRY.get(country, [])
    if not defaults:
        import logging
        logging.getLogger("zoiko").warning(
            f"[payroll-seed] no default tax slabs available for country '{country}' — "
            f"org {organization_id} will have zero income-tax slabs until a canonical tax pack or manual slabs are configured."
        )
    rows = []
    for d in defaults:
        row = TaxSlab(organization_id=organization_id, jurisdiction_country=country, **d)
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def get_tax_slabs(db: Session, organization_id: int = None, country: str = "IN", tax_regime: str = None) -> List[TaxSlab]:
    query = db.query(TaxSlab)
    query = _apply_org_filter(query, TaxSlab, organization_id)
    query = query.filter(TaxSlab.jurisdiction_country == country)
    if tax_regime:
        # Same regime-agnostic-plus-specific pattern as get_contribution_rates.
        query = query.filter(or_(TaxSlab.tax_regime.is_(None), TaxSlab.tax_regime == tax_regime))
    rows = query.order_by(TaxSlab.sort_order).all()
    if not rows and organization_id:
        if not _seed_org_rates_for_country(db, organization_id, country):
            _seed_tax_slabs(db, organization_id, country)
        rows = (
            db.query(TaxSlab)
            .filter(TaxSlab.organization_id == organization_id, TaxSlab.jurisdiction_country == country)
            .order_by(TaxSlab.sort_order)
            .all()
        )
    return rows


# Known contribution components get a stable key so re-applying the same
# component (e.g. re-uploading a corrected PF notice) updates the existing
# row instead of creating a duplicate. Anything else falls back to a
# slugified label — good enough to avoid exact-duplicate rows, but two
# differently-worded labels for the same real-world component will still
# create two rows; that requires the label matching used at extraction
# time to be more consistent, which is a document-parsing concern, not
# something this function can fix.
_KNOWN_COMPONENT_KEYS = {
    "provident fund": "pf", "epf": "pf",
    "esi": "esi", "employee state insurance": "esi",
    "professional tax": "pt", "pt": "pt",
    "tds": "tds", "income tax": "tds",
    "gratuity": "gratuity",
    # US-specific
    "social security": "social_security", "ss": "social_security",
    "medicare": "medicare",
    # UK-specific
    "national insurance": "ni_employee", "ni": "ni_employee",
    "pension": "employer_pension", "workplace pension": "employer_pension",
}


def _strip_trailing_paren(label: str) -> str:
    """"Employee State Insurance (ESI)" -> "employee state insurance" — used
    to match two ContributionRate rows for the same real-world component
    saved under labels that differ only by a trailing abbreviation. Only
    strips the trailing parenthetical and requires the rest of the label to
    match exactly, unlike a substring/synonym search — "ESI Wage Ceiling
    (monthly)" strips to "esi wage ceiling", which correctly stays distinct
    from "employee state insurance" rather than colliding on "esi"."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", (label or "")).strip().lower()


# Component keys the engine reads via an EXACT, hardcoded, case-sensitive
# string (engine/standard.py / engine/countries/*.py, e.g.
# `rate_map.get("pf")`, `rate_map.get("medicare-levy")`). A canonical row
# saved with any other casing (Super Admin typing "PF"/"Pf"/"ESI" in
# Statutory Rates) is invisible to those lookups — a real, confirmed bug:
# a dedup pass once kept an uppercase-cased survivor over the correctly-
# cased one, silently zeroing PF/ESI/PT for an organization. Normalizing
# at the ONE place these keys are ever written (here) prevents that
# recurring, rather than patching every read site. Named parameter keys
# (standard_deduction, esi_wage_ceiling, ...) are already lowercase by
# convention and simply pass through unchanged — this set intentionally
# only covers the short, exact-match generic component keys.
_KNOWN_ENGINE_COMPONENT_KEYS = {
    "pf", "esi", "pt", "tds", "cpp", "ei", "super", "pension", "medicare",
    "medicare-levy", "social-insurance", "national-insurance",
    "employer-pension", "social-security", "futa",
}


def _normalize_engine_component_key(key: str) -> str:
    if key and key.lower() in _KNOWN_ENGINE_COMPONENT_KEYS:
        return key.lower()
    return key


def _component_key_for_label(label: str) -> str:
    normalized = (label or "").strip().lower()
    for phrase, key in _KNOWN_COMPONENT_KEYS.items():
        if phrase in normalized:
            return key
    slug = "".join(c if c.isalnum() else "-" for c in normalized).strip("-")
    return slug[:20] or "custom"


def _parse_rate_value(text: str) -> dict:
    """Parses an extracted rate's display text ("12%", "0.75%",
    "₹200/month (fixed)", "—") into the numeric field the calculation
    engine actually reads. Percentage text becomes `rate_pct`; a bare
    currency/number becomes `flat_amount` (e.g. Professional Tax, which
    is a fixed amount, not a percentage). Unparseable text (e.g. "—",
    "As per slab") returns {} — deliberately NOT zero, since a missing
    rate should be treated as "not yet configured", not "configured at
    0%", by the caller."""
    if not text:
        return {}
    cleaned = text.strip()
    if "%" in cleaned:
        match = re.search(r"[\d.]+", cleaned)
        if match:
            return {"rate_pct": Decimal(match.group())}
        return {}
    # No percentage sign — look for a plain number (possibly with a
    # currency symbol/commas) and treat it as a flat amount.
    match = re.search(r"[\d,]+(?:\.\d+)?", cleaned)
    if match:
        return {"flat_amount": Decimal(match.group().replace(",", ""))}
    return {}


def apply_extracted_rate(db: Session, organization_id: int, kind: str, row: dict, country_code: str = "IN") -> dict:
    """Promote a single row from ComplianceDocumentUpload's extracted
    preview into the org's active ContributionRate/TaxSlab configuration —
    the tables get_contribution_rates()/get_tax_slabs() actually read from
    for real payslip calculation. `row` is the same dict shape the
    frontend already renders (see ApplyExtractedRateRequest).

    IMPORTANT: get_contribution_rates()/get_tax_slabs() filter on
    `jurisdiction_country`, and the calculation engine reads the numeric
    `employee_rate_pct`/`employer_rate_pct`/`flat_amount` fields — NOT the
    display-text `employee_share`/`employer_share` fields. A row saved
    without both of these is invisible to real payroll runs even though
    it appears "applied" in the UI — this was a real bug (rates vanishing
    from payroll runs after being applied) fixed here."""
    if kind == "contributionRate":
        label = row.get("label", "")
        component_key = _component_key_for_label(label)
        existing = (
            db.query(ContributionRate)
            .filter(ContributionRate.organization_id == organization_id,
                    ContributionRate.component_key == component_key,
                    ContributionRate.jurisdiction_country == country_code)
            .first()
        )

        employee_parsed = _parse_rate_value(row.get("employee", ""))
        employer_parsed = _parse_rate_value(row.get("employer", ""))

        fields = dict(
            label=label,
            employee_share=row.get("employee", ""),
            employer_share=row.get("employer", ""),
            total=row.get("total", ""),
            jurisdiction_country=country_code,
        )
        # Percentage-based components (PF, ESI, etc.) — employee/employer
        # sides are independent, so set whichever parsed.
        if "rate_pct" in employee_parsed:
            fields["employee_rate_pct"] = employee_parsed["rate_pct"]
        if "rate_pct" in employer_parsed:
            fields["employer_rate_pct"] = employer_parsed["rate_pct"]
        # Flat-amount components (Professional Tax) — only one side is
        # normally populated; prefer whichever side actually parsed.
        flat = employee_parsed.get("flat_amount") or employer_parsed.get("flat_amount")
        if flat is not None:
            fields["flat_amount"] = flat

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            db.add(ContributionRate(organization_id=organization_id, component_key=component_key, **fields))
        db.commit()
        return {"applied": True, "componentKey": component_key,
                "message": f"Applied to active contribution rates ({component_key})."}

    if kind == "taxSlab":
        # min/max values arrive as currency-prefixed, comma-grouped strings
        # (e.g. "₹4,00,000") from _extract_tax_slabs. Strip everything
        # except digits and a single decimal point before converting.
        def _strip_to_decimal(raw):
            if raw is None:
                return None
            cleaned = re.sub(r"[^\d.]", "", str(raw))
            if not cleaned or cleaned == ".":
                return None
            return Decimal(cleaned)

        min_amount = _strip_to_decimal(row.get("min", "0"))
        if min_amount is None:
            return {"applied": False, "componentKey": None,
                    "message": f"Could not parse slab lower bound: {row.get('min')!r}"}

        max_raw = row.get("max")
        max_amount = None
        if max_raw not in (None, "", "—"):
            if str(max_raw).strip().lower() in ("above", "and above"):
                max_amount = None  # open-ended top band
            else:
                max_amount = _strip_to_decimal(max_raw)
                if max_amount is None:
                    return {"applied": False, "componentKey": None,
                            "message": f"Could not parse slab upper bound: {max_raw!r}"}

        existing = (
            db.query(TaxSlab)
            .filter(TaxSlab.organization_id == organization_id,
                    TaxSlab.jurisdiction_country == country_code,
                    TaxSlab.min_amount == min_amount,
                    TaxSlab.max_amount == max_amount)
            .first()
        )
        rate_label = row.get("rate", "")
        # rate_pct actually drives _calculate_annual_tax — rate_label is
        # display-only. Parse it best-effort from "5%" style labels rather
        # than defaulting to 0, which would silently zero out tax on this
        # band. "Nil"/unparseable labels correctly fall back to 0%.
        try:
            rate_pct = Decimal(rate_label.strip().rstrip("%")) if "%" in rate_label else Decimal("0")
        except Exception:
            rate_pct = Decimal("0")
        fields = dict(rate_label=rate_label, tax_formula=row.get("tax", ""), rate_pct=rate_pct,
                      jurisdiction_country=country_code)
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            next_sort = db.query(TaxSlab).filter(TaxSlab.organization_id == organization_id).count() + 1
            db.add(TaxSlab(organization_id=organization_id, min_amount=min_amount, max_amount=max_amount,
                            sort_order=next_sort, **fields))
        db.commit()
        return {"applied": True, "componentKey": None, "message": "Applied to active tax slabs."}

    return {"applied": False, "componentKey": None, "message": f"Unknown kind: {kind!r}"}


def list_jurisdiction_packs(db: Session, country: str, state: str = None) -> List[JurisdictionPack]:
    """Packs for a given jurisdiction. state=None returns country-level
    packs only — it does NOT also return every state-level pack under that
    country, since those are meant to layer on top of (not replace) the
    country pack. Callers needing the full stack should request both."""
    query = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == country)
    if state:
        query = query.filter(JurisdictionPack.jurisdiction_state == state)
    else:
        query = query.filter(JurisdictionPack.jurisdiction_state.is_(None))
    return query.order_by(JurisdictionPack.version.desc()).all()


def upsert_jurisdiction_pack(db: Session, data: "JurisdictionPackUpsert", actor_id: Optional[int] = None) -> JurisdictionPack:
    """Create or update a pack. When `data.id` is provided (editing an
    existing pack in place), the lookup is by primary key — the only way
    packId/version themselves can be safely renamed, since every dependent
    row (canonical ContributionRate/TaxSlab, TaxConfigurationAudit,
    PayslipItem snapshots) references jurisdiction_pack_id, the integer
    id, never the packId string. Without `data.id`, lookup falls back to
    (pack_id, version) — matches the UniqueConstraint, and is what "create"
    and "new version" still use.

    This intentionally does NOT silently bump the version on every save:
    per the spec's lifecycle model (Section 17), a new version should be a
    deliberate act, not an accidental side effect of editing metadata.

    When the (pack_id, version) pair doesn't exist yet AND another version
    of the same pack_id already does, the new row's previous_version_id is
    set to the latest prior version automatically — this is what gives
    Compliance its version chain (1.0 -> 1.1 -> 2.0) without ever mutating
    or deleting an earlier row.
    """
    existing = None
    if data.id:
        existing = db.query(JurisdictionPack).filter(JurisdictionPack.id == data.id).first()
    if not existing:
        existing = (
            db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == data.packId, JurisdictionPack.version == data.version)
            .first()
        )
    fields = dict(
        pack_id=data.packId,
        version=data.version,
        jurisdiction_country=data.jurisdictionCountry,
        jurisdiction_state=data.jurisdictionState,
        jurisdiction_locality=data.jurisdictionLocality,
        pack_type=data.packType,
        status=data.status,
        effective_from=data.effectiveFrom,
        effective_to=data.effectiveTo,
        compliance_owner=data.complianceOwner,
        engineering_owner=data.engineeringOwner,
        source_references=data.sourceReferences,
        regulatory_authority=data.regulatoryAuthority,
        compliance_category=data.complianceCategory,
        change_summary=data.changeSummary,
        next_review_date=data.nextReviewDate,
        policy_defaults=data.policyDefaults,
        tax_year=data.taxYear,
        tax_regime=data.taxRegime,
        default_tax_regime=data.defaultTaxRegime,
        approved_by_id=data.approvedById,
        currency=data.currency,
    )
    if existing:
        # A tax pack's own metadata (effective_from/to, tax_year, ...) is
        # part of what makes a published release resolvable for a given
        # date — editing it in place on an Active+ pack is the same class
        # of immutability violation as editing its rate rows (see
        # _require_editable_pack). Status transitions themselves still go
        # through set_jurisdiction_pack_status, not this function, so this
        # does not block Approve/Activate.
        if existing.pack_type == "tax":
            _require_editable_pack(existing)
        # Snapshot the row's values BEFORE mutating it — using `fields`
        # (the incoming/new values) here was a real bug: old_value and
        # new_value ended up identical for every pack-level edit, making
        # the Audit tab's diff meaningless.
        old_value = {k: (str(getattr(existing, k)) if getattr(existing, k) is not None else None) for k in fields}
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.updated_by_id = actor_id
        row = existing
        db.commit()
        db.refresh(row)
        record_tax_audit(
            db, actor_id=actor_id, action="update", entity_type="jurisdiction_pack", entity_id=row.id,
            jurisdiction_pack_id=row.id, tax_version=row.version, legal_reference=row.source_references,
            old_value=old_value, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
            reason=data.reason,
        )
        return row

    previous = (
        db.query(JurisdictionPack)
        .filter(JurisdictionPack.pack_id == data.packId)
        .order_by(JurisdictionPack.created_at.desc())
        .first()
    )
    row = JurisdictionPack(
        previous_version_id=previous.id if previous else None,
        created_by_id=actor_id, updated_by_id=actor_id,
        **fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if previous and fields.get("pack_type") == "tax":
        # Pre-populate the new version with the prior version's canonical
        # rates/slabs instead of leaving it empty. Without this, the
        # immutability guard above would make "create a new version" for a
        # one-line correction prohibitively tedious (retyping every rate),
        # which would just push Super Admins back toward editing Active
        # packs in place — defeating the guard's purpose.
        _clone_pack_rates(db, source_pack_id=previous.id, target_pack_id=row.id)
    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="jurisdiction_pack", entity_id=row.id,
        jurisdiction_pack_id=row.id, tax_version=row.version, legal_reference=row.source_references,
        old_value=None, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
        reason=data.reason,
    )
    return row


# ── Tax Configuration Audit ──────────────────────────────────────────────

def record_tax_audit(
    db: Session, *, actor_id: Optional[int], action: str, entity_type: str, entity_id: int,
    jurisdiction_pack_id: Optional[int] = None, tax_version: Optional[str] = None,
    legal_reference: Optional[str] = None, old_value: Optional[dict] = None,
    new_value: Optional[dict] = None, reason: Optional[str] = None,
) -> None:
    """One canonical write path for every mutation to a Super-Admin-owned
    canonical tax/contribution/pack row. Called explicitly at each mutation
    site (matching this module's existing style of explicit service
    functions) rather than via an ORM event hook, so every audit entry is
    traceable to the exact line that produced it."""
    db.add(TaxConfigurationAudit(
        actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
        jurisdiction_pack_id=jurisdiction_pack_id, tax_version=tax_version,
        legal_reference=legal_reference, old_value=old_value, new_value=new_value, reason=reason,
    ))
    db.commit()


def list_tax_configuration_audit(
    db: Session, jurisdiction_pack_id: Optional[int] = None, entity_type: Optional[str] = None,
) -> List[TaxConfigurationAudit]:
    query = db.query(TaxConfigurationAudit)
    if jurisdiction_pack_id:
        query = query.filter(TaxConfigurationAudit.jurisdiction_pack_id == jurisdiction_pack_id)
    if entity_type:
        query = query.filter(TaxConfigurationAudit.entity_type == entity_type)
    return query.order_by(TaxConfigurationAudit.created_at.desc()).all()


# ── Canonical Tax Rates (Super Admin-owned; organization_id IS NULL) ────
# These are the government-mandated values. Org-scoped ContributionRate/
# TaxSlab rows (organization_id set) are populated FROM these via
# sync_org_rates_from_canonical (engine/tax_resolver.py) — the engine's
# read path (get_contribution_rates/get_tax_slabs below) is unchanged.

# A pack in one of these statuses is still being drafted/reviewed — its
# canonical rows may be freely created/edited. Once it reaches Active (or
# beyond), it is a "published statutory release": corrections must go
# through a new pack version (upsert_jurisdiction_pack with no `id`/a new
# `version`), never an in-place row edit. Before this guard existed,
# upsert_canonical_tax_slab/upsert_canonical_contribution_rate had no
# status check at all — editing a row on an Active pack silently changed
# what the live resolver returns for every not-yet-generated or
# still-Draft payslip, including ones for past pay periods already within
# the pack's effective window. This is the fix for that.
_EDITABLE_PACK_STATUSES = ("Draft", "In Review", "QA", "Approved")


def _require_editable_pack(pack: "JurisdictionPack") -> None:
    if pack.status not in _EDITABLE_PACK_STATUSES:
        raise BadRequestException(
            f"Pack {pack.pack_id} v{pack.version} is {pack.status} — its rates are no "
            "longer editable. Create a new pack version (\"New Version\") to make changes; "
            "published statutory releases must not be edited in place."
        )


def _clone_pack_rates(db: Session, source_pack_id: int, target_pack_id: int) -> None:
    """Copies every canonical ContributionRate/TaxSlab row from
    source_pack_id onto target_pack_id as brand-new rows (fresh ids). Used
    when a new JurisdictionPack version is created, so a Super Admin
    starting a correction gets the prior version's rates pre-populated
    instead of an empty pack — without this, the immutability guard above
    would make "create a new version" prohibitively tedious (retyping
    every rate/slab from scratch) and Super Admins would be pushed back
    toward editing Active packs in place."""
    for row in db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == source_pack_id,
        ContributionRate.organization_id.is_(None),
    ).all():
        clone = ContributionRate(
            organization_id=None, jurisdiction_pack_id=target_pack_id,
            jurisdiction_country=row.jurisdiction_country, jurisdiction_state=row.jurisdiction_state,
            jurisdiction_locality=row.jurisdiction_locality, tax_regime=row.tax_regime,
            filing_status=row.filing_status,
            component_key=row.component_key, label=row.label,
            employee_share=row.employee_share, employer_share=row.employer_share, total=row.total,
            employee_rate_pct=row.employee_rate_pct, employer_rate_pct=row.employer_rate_pct,
            flat_amount=row.flat_amount, text_value=row.text_value, sort_order=row.sort_order,
        )
        db.add(clone)
    for row in db.query(TaxSlab).filter(
        TaxSlab.jurisdiction_pack_id == source_pack_id,
        TaxSlab.organization_id.is_(None),
    ).all():
        clone = TaxSlab(
            organization_id=None, jurisdiction_pack_id=target_pack_id,
            jurisdiction_country=row.jurisdiction_country, jurisdiction_state=row.jurisdiction_state,
            jurisdiction_locality=row.jurisdiction_locality, tax_regime=row.tax_regime,
            filing_status=row.filing_status,
            min_amount=row.min_amount, max_amount=row.max_amount,
            rate_pct=row.rate_pct, rate_label=row.rate_label, tax_formula=row.tax_formula,
            rule_type=row.rule_type, formula_expression=row.formula_expression,
            flat_amount=row.flat_amount, adjustment_amount=row.adjustment_amount,
            ni_category=row.ni_category, employer_rate_pct=row.employer_rate_pct,
            sort_order=row.sort_order,
        )
        db.add(clone)
    db.commit()

def _org_uses_canonical_tax_pack(db: Session, organization_id: int) -> bool:
    """True only if this org's CompanyComplianceDetails.active_pack_id
    currently points at a pack_type="tax" JurisdictionPack — i.e. Super
    Admin has explicitly run "Apply Tax & Sync Rates" (assign_pack_to_
    organizations) for this org at least once. Gates
    _resolve_effective_rate_inputs below so canonical, date-resolved rates
    only ever replace an org's cached rates for orgs actually opted into
    canonical tracking — every other org's numbers are completely
    unaffected by that function.

    Known limitation (pre-existing, not introduced here): active_pack_id
    is a single FK shared across pack types (see its TODO comment on
    CompanyComplianceDetails, models.py) — if Super Admin later assigns a
    policy pack to an org previously on a tax pack, this can under-detect.
    Accepted as-is rather than solved here."""
    if not organization_id:
        return False
    hit = (
        db.query(JurisdictionPack.id)
        .join(CompanyComplianceDetails, CompanyComplianceDetails.active_pack_id == JurisdictionPack.id)
        .filter(CompanyComplianceDetails.organization_id == organization_id, JurisdictionPack.pack_type == "tax")
        .first()
    )
    return hit is not None


def _pack_to_tax_snapshot(rates, slabs, pack) -> dict:
    """Build the {tax_policy_pack_id, tax_policy_version, tax_rule_snapshot}
    dict from an already-resolved canonical pack + its rates/slabs.
    Extracted out of _resolve_tax_snapshot so a caller that already
    resolved a pack via _resolve_effective_rate_inputs (to get the actual
    calculation numbers) can reuse that same resolution for the metadata
    instead of a second resolve_tax_configuration query — the numbers and
    the metadata can then never disagree on which pack version applied."""
    if not pack:
        return {"tax_policy_pack_id": None, "tax_policy_version": None, "tax_rule_snapshot": None}

    def _dec(v):
        return str(v) if v is not None else None

    snapshot = {
        "packId": pack.pack_id,
        "version": pack.version,
        "contributionRates": [
            {
                "componentKey": r.component_key, "label": r.label,
                "employeeRatePct": _dec(r.employee_rate_pct), "employerRatePct": _dec(r.employer_rate_pct),
                "flatAmount": _dec(r.flat_amount),
            }
            for r in rates
        ],
        "taxSlabs": [
            {
                "minAmount": _dec(s.min_amount), "maxAmount": _dec(s.max_amount), "ratePct": _dec(s.rate_pct),
                "ruleType": s.rule_type, "formulaExpression": s.formula_expression,
            }
            for s in slabs
        ],
    }
    return {"tax_policy_pack_id": pack.id, "tax_policy_version": pack.version, "tax_rule_snapshot": snapshot}


def _resolve_effective_rate_inputs(
    db: Session, organization_id: int, country: str, payroll_date,
    org_opted_in: bool, state: Optional[str] = None, tax_regime: Optional[str] = None,
    filing_status: Optional[str] = None,
):
    """Rate/slab resolution for one calculation, gated on org_opted_in.

    If the org has opted into canonical tax-pack tracking
    (_org_uses_canonical_tax_pack) and a canonical pack with at least one
    rate or slab resolves for (country, state, tax_regime, payroll_date),
    use those canonical rows DIRECTLY (no DB write) — this is what makes
    the calculation agree with whichever pack version was actually in
    force on payroll_date, even if the org's own cached ContributionRate/
    TaxSlab rows have since been re-synced to a newer pack version.

    Otherwise (not opted in, or no canonical pack resolves for this exact
    date/state/regime) falls through to get_contribution_rates/
    get_tax_slabs exactly as before this existed — byte-for-byte unchanged
    for that population.

    `filing_status` (US-specific, NULL for every other country): threaded
    into get_contribution_rates so a filing-status-tagged ContributionRate
    row (e.g. a MFJ-specific medicare_addl_thresh) wins over the generic
    row for a matching employee — see get_contribution_rates' docstring.
    NOT YET threaded into the org_opted_in/canonical-pack branch above
    (resolve_tax_configuration) — a canonical-pack-opted-in US org's
    filing-status-specific ContributionRate rows are not yet distinguished
    from each other in that path. Flagged as a known follow-up, not
    silently unhandled: this only affects orgs that have BOTH opted into
    canonical tax packs AND configured filing-status-specific rates, an
    empty set as of this change.

    Returns (rate_map, slabs, canonical_rates_or_None, pack_or_None).
    canonical_rates is the raw list (not the dict) so a caller can build a
    tax snapshot via _pack_to_tax_snapshot without a second query; pack is
    None whenever canonical resolution wasn't used, signalling the caller
    to fall back to its own existing tax-snapshot logic unchanged."""
    if org_opted_in:
        from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
        canonical_rates, canonical_slabs, pack = resolve_tax_configuration(
            db, country, state=state, tax_regime=tax_regime, payroll_date=payroll_date,
        )
        if pack is not None and (canonical_rates or canonical_slabs):
            # Normalized at read time too (not just at the write paths in
            # upsert_canonical_contribution_rate/sync_org_rates_from_canonical)
            # as defense in depth — a canonical row saved before either fix
            # existed can still carry a wrong-cased key on disk; this
            # guarantees the live calculation path never misses it even so.
            return {_normalize_engine_component_key(r.component_key): r for r in canonical_rates}, canonical_slabs, canonical_rates, pack
    rate_map = {
        _normalize_engine_component_key(r.component_key): r
        for r in get_contribution_rates(db, organization_id, country, tax_regime=tax_regime, filing_status=filing_status)
    }
    slabs = get_tax_slabs(db, organization_id, country, tax_regime=tax_regime)
    return rate_map, slabs, None, None


def get_state_scoped_config(db: Session, country: str, state: Optional[str]) -> Tuple[dict, list]:
    """Region-specific rates/slabs for a country+state combination — a
    DELIBERATELY SEPARATE, simpler lookup from _resolve_effective_rate_inputs
    above: it queries canonical (organization_id IS NULL) ContributionRate/
    TaxSlab rows directly by (jurisdiction_country, jurisdiction_state),
    bypassing the JurisdictionPack winner-take-all resolution entirely.

    Why separate rather than folded into the existing canonical/org/
    fallback tiering: that system already has a known limitation (a
    state-specific pack's rows entirely REPLACE the country-level pack's
    rows if one resolves, rather than layering) — fixing that is a larger,
    separate change. This function instead answers a narrower question —
    "is there a region-specific rate/slab for a component that only
    exists at the region level" (India's state-specific Professional Tax,
    US state income tax, UK's Scotland tax bands) — additively, without
    touching or risking that existing tiering logic at all.

    Returns ({}, []) if state is falsy or nothing is configured for it —
    every existing calculation is completely unaffected until a country
    calculator explicitly reads ctx.state_rate_map/ctx.state_slabs AND a
    real region-scoped row has been seeded for that specific state."""
    if not state:
        return {}, []
    rate_rows = (
        db.query(ContributionRate)
        .filter(
            ContributionRate.organization_id.is_(None),
            ContributionRate.jurisdiction_country == country,
            ContributionRate.jurisdiction_state == state,
        )
        .order_by(ContributionRate.sort_order)
        .all()
    )
    slab_rows = (
        db.query(TaxSlab)
        .filter(
            TaxSlab.organization_id.is_(None),
            TaxSlab.jurisdiction_country == country,
            TaxSlab.jurisdiction_state == state,
        )
        .order_by(TaxSlab.sort_order, TaxSlab.min_amount)
        .all()
    )
    state_rate_map = {_normalize_engine_component_key(r.component_key): r for r in rate_rows}
    return state_rate_map, slab_rows


# ── US: locality (county/municipal/school-district) tax ─────────────────
# Deliberately manual-entry (see LocalityRateUpsert's own docstring) — no
# address-to-code geocoding exists or is attempted here. Simplified
# lifecycle: exactly one "Active" LocalityDataset per (country, state),
# auto-created the first time a rate is entered for that state — the full
# Draft/Staged/Active/Retired workflow the standard's §10 data contract
# describes is not implemented; this is a real, disclosed simplification.

def _get_or_create_locality_dataset(db: Session, country: str, state: str) -> LocalityDataset:
    dataset = (
        db.query(LocalityDataset)
        .filter(
            LocalityDataset.jurisdiction_country == country,
            LocalityDataset.jurisdiction_state == state,
            LocalityDataset.status == "Active",
        )
        .order_by(LocalityDataset.created_at.desc())
        .first()
    )
    if dataset:
        return dataset
    dataset = LocalityDataset(
        jurisdiction_country=country, jurisdiction_state=state,
        version="MANUAL-1", status="Active",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def list_locality_rates(db: Session, country: str, state: str) -> List[LocalityRate]:
    return (
        db.query(LocalityRate)
        .join(LocalityDataset, LocalityRate.locality_dataset_id == LocalityDataset.id)
        .filter(
            LocalityDataset.jurisdiction_country == country,
            LocalityDataset.jurisdiction_state == state,
            LocalityDataset.status == "Active",
        )
        .order_by(LocalityRate.locality_code)
        .all()
    )


def upsert_locality_rate(db: Session, data: LocalityRateUpsert, actor_id: Optional[int] = None) -> LocalityRate:
    dataset = _get_or_create_locality_dataset(db, data.jurisdictionCountry, data.jurisdictionState)
    if data.sourceDocumentId:
        dataset.source_document_id = data.sourceDocumentId
    if data.effectiveFrom:
        dataset.effective_from = data.effectiveFrom
    if data.effectiveTo:
        dataset.effective_to = data.effectiveTo
    fields = dict(
        locality_code=data.localityCode, locality_type=data.localityType,
        locality_name=data.localityName, resident_rate_pct=data.residentRatePct,
        nonresident_rate_pct=data.nonresidentRatePct, flat_amount=data.flatAmount,
        tax_collector_id=data.taxCollectorId,
    )
    action = "update" if data.id else "create"
    old_value = None
    if data.id:
        row = db.query(LocalityRate).filter(LocalityRate.id == data.id).first()
        if not row:
            raise NotFoundException("LocalityRate", data.id)
        old_value = {k: (str(getattr(row, k)) if getattr(row, k) is not None else None) for k in fields}
        for k, v in fields.items():
            setattr(row, k, v)
    else:
        row = LocalityRate(locality_dataset_id=dataset.id, **fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action=action, entity_type="locality_rate", entity_id=row.id,
        old_value=old_value, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
    )
    return row


def delete_locality_rate(db: Session, rate_id: int, actor_id: Optional[int] = None) -> None:
    row = db.query(LocalityRate).filter(LocalityRate.id == rate_id).first()
    if not row:
        raise NotFoundException("LocalityRate", rate_id)
    old_value = {
        "localityCode": row.locality_code, "localityType": row.locality_type,
        "residentRatePct": str(row.resident_rate_pct) if row.resident_rate_pct is not None else None,
        "flatAmount": str(row.flat_amount) if row.flat_amount is not None else None,
    }
    db.delete(row)
    db.commit()
    record_tax_audit(
        db, actor_id=actor_id, action="delete", entity_type="locality_rate", entity_id=rate_id,
        old_value=old_value, new_value=None,
    )


def get_locality_rate(db: Session, country: str, locality_code: Optional[str], as_of=None) -> Optional[LocalityRate]:
    """Engine-facing resolver — the US-specific analog of
    get_employer_tax_profiles. Returns None (today's exact behavior for
    every employee, since no employee has work_locality set yet) whenever
    locality_code is falsy or nothing matches an Active dataset effective
    on `as_of`."""
    if not locality_code:
        return None
    as_of = as_of or date.today()
    return (
        db.query(LocalityRate)
        .join(LocalityDataset, LocalityRate.locality_dataset_id == LocalityDataset.id)
        .filter(
            LocalityDataset.jurisdiction_country == country,
            LocalityDataset.status == "Active",
            LocalityRate.locality_code == locality_code,
        )
        .filter(or_(LocalityDataset.effective_from.is_(None), LocalityDataset.effective_from <= as_of))
        .filter(or_(LocalityDataset.effective_to.is_(None), LocalityDataset.effective_to >= as_of))
        .first()
    )


# ── US: employer-specific tax profile (SUI and similar) ─────────────────

def get_employer_tax_profiles(
    db: Session, organization_id: int, jurisdiction_id: Optional[str], as_of=None,
) -> dict:
    """Tenant-specific, agency-assigned rates for one org+jurisdiction
    (e.g. "US-CA") — SUI's employer_rate_pct/taxable_wage_base, keyed by
    component_code ("SUI", "ETT", ...). DELIBERATELY separate from
    ContributionRate/rate_map (see EmployerTaxProfile's own docstring):
    an org choosing a different PF % is a policy decision; a SUI rate is a
    statutory fact assigned by a government agency, with its own account
    number and evidence trail.

    Returns {} if jurisdiction_id is falsy or nothing is configured — every
    existing org (none of which has an EmployerTaxProfile row, since this
    table didn't exist before this function) is completely unaffected."""
    if not jurisdiction_id:
        return {}
    as_of = as_of or date.today()
    rows = (
        db.query(EmployerTaxProfile)
        .filter(
            EmployerTaxProfile.organization_id == organization_id,
            EmployerTaxProfile.jurisdiction_id == jurisdiction_id,
            EmployerTaxProfile.effective_from <= as_of,
        )
        .filter(or_(EmployerTaxProfile.effective_to.is_(None), EmployerTaxProfile.effective_to >= as_of))
        .all()
    )
    return {row.component_code: row for row in rows}


def list_employer_tax_profiles(db: Session, organization_id: Optional[int] = None, jurisdiction_id: Optional[str] = None) -> List[EmployerTaxProfile]:
    """Super Admin/Tax Ops list view — every profile for an org, or every
    org's profile for one jurisdiction, or (both filters) the exact set
    get_employer_tax_profiles would resolve from at any date."""
    query = db.query(EmployerTaxProfile)
    if organization_id is not None:
        query = query.filter(EmployerTaxProfile.organization_id == organization_id)
    if jurisdiction_id:
        query = query.filter(EmployerTaxProfile.jurisdiction_id == jurisdiction_id)
    return query.order_by(EmployerTaxProfile.effective_from.desc()).all()


def upsert_employer_tax_profile(db: Session, data: EmployerTaxProfileUpsert, actor_id: Optional[int] = None) -> EmployerTaxProfile:
    """Create or update a tenant-specific, agency-assigned rate profile.
    Per the standard's §6.2 ("never infer... the authoritative source is
    the agency-issued rate notice"), this is Tax Ops data entry against a
    real notice — there is no "canonical default" layer for this table at
    all (see EmployerTaxProfile's own model docstring).

    Audited via the SAME record_tax_audit trail as canonical rates/slabs
    (jurisdiction_pack_id left None — this table has no pack) — before
    this, a Super Admin changing an employer's SUI rate left no history
    of who changed what, unlike every canonical rate edit."""
    fields = dict(
        organization_id=data.organizationId, jurisdiction_id=data.jurisdictionId,
        component_code=data.componentCode, taxable_wage_base=data.taxableWageBase,
        rate_source=data.rateSource, employer_rate_pct=data.employerRatePct,
        assessment_rate_pct=data.assessmentRatePct,
        effective_from=data.effectiveFrom, effective_to=data.effectiveTo,
        agency_account_id=data.agencyAccountId, reimbursable_status=data.reimbursableStatus,
        source_document_id=data.sourceDocumentId,
    )
    action = "update" if data.id else "create"
    old_value = None
    if data.id:
        row = db.query(EmployerTaxProfile).filter(EmployerTaxProfile.id == data.id).first()
        if not row:
            raise NotFoundException("EmployerTaxProfile", data.id)
        old_value = {k: (str(getattr(row, k)) if getattr(row, k) is not None else None) for k in fields}
        for k, v in fields.items():
            setattr(row, k, v)
    else:
        row = EmployerTaxProfile(**fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action=action, entity_type="employer_tax_profile", entity_id=row.id,
        old_value=old_value, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
    )
    return row


def delete_employer_tax_profile(db: Session, profile_id: int, actor_id: Optional[int] = None) -> None:
    row = db.query(EmployerTaxProfile).filter(EmployerTaxProfile.id == profile_id).first()
    if not row:
        raise NotFoundException("EmployerTaxProfile", profile_id)
    old_value = {
        "organizationId": row.organization_id, "jurisdictionId": row.jurisdiction_id,
        "componentCode": row.component_code,
        "employerRatePct": str(row.employer_rate_pct) if row.employer_rate_pct is not None else None,
        "taxableWageBase": str(row.taxable_wage_base) if row.taxable_wage_base is not None else None,
    }
    db.delete(row)
    db.commit()
    record_tax_audit(
        db, actor_id=actor_id, action="delete", entity_type="employer_tax_profile", entity_id=profile_id,
        old_value=old_value, new_value=None,
    )


# ── US: cross-state reciprocity ──────────────────────────────────────────

def resolve_reciprocity(
    db: Session, resident_jurisdiction: Optional[str], work_jurisdiction: Optional[str], as_of=None,
) -> Optional[ReciprocityRule]:
    """A directional agreement record (see ReciprocityRule's own docstring)
    for this exact resident/work jurisdiction pair, effective on `as_of` —
    per the standard's §8.2, reciprocity is data, never embedded in state
    calculation code. Returns None (no reciprocity — today's exact
    behavior for every employee, since this table is empty until Tax Ops
    configures a real agreement) whenever either jurisdiction is falsy,
    they're the same jurisdiction (no cross-state question to answer), or
    no matching row is effective on this date."""
    if not resident_jurisdiction or not work_jurisdiction or resident_jurisdiction == work_jurisdiction:
        return None
    as_of = as_of or date.today()
    return (
        db.query(ReciprocityRule)
        .filter(
            ReciprocityRule.resident_jurisdiction == resident_jurisdiction,
            ReciprocityRule.work_jurisdiction == work_jurisdiction,
            ReciprocityRule.effective_from <= as_of,
        )
        .filter(or_(ReciprocityRule.effective_to.is_(None), ReciprocityRule.effective_to >= as_of))
        .order_by(ReciprocityRule.effective_from.desc())
        .first()
    )


def _reciprocity_certificate_satisfied(employee, rule: ReciprocityRule, as_of) -> bool:
    """Whether THIS employee actually satisfies the rule's certificate
    requirement — a reciprocity agreement existing is not enough by
    itself; the standard's §8.1 step 5 is explicit that withholding is
    only suppressed "when the required certificate is satisfied." An
    employee with no certificate on file, or an expired one, is taxed as
    if no agreement existed at all — never assumed compliant."""
    if not rule.certificate_required:
        return True
    if not getattr(employee, "reciprocity_certificate_on_file", False):
        return False
    expiry = getattr(employee, "reciprocity_certificate_expiry", None)
    if expiry is not None and expiry < as_of:
        return False
    return True


def _resolve_us_reciprocity(
    db: Session, employee, country: str, work_state: Optional[str], as_of=None,
) -> dict:
    """US-specific (returns the all-False/empty defaults for every other
    country, and for a US employee with no distinct residence_state):
    resolves whether reciprocity suppresses this employee's work-state
    withholding, and if so, the RESIDENT state's rate/slab config to use
    instead. Returns a dict of PayrollContext kwargs so call sites can
    **-splat it directly rather than threading four separate params."""
    empty = dict(reciprocity_suppresses_work_state=False, resident_state_rate_map={}, resident_state_slabs=[])
    if country != "US":
        return empty
    residence_state = getattr(employee, "residence_state", None) or work_state
    if not residence_state or not work_state or residence_state == work_state:
        return empty
    as_of = as_of or date.today()
    rule = resolve_reciprocity(db, f"{country}-{residence_state}", f"{country}-{work_state}", as_of=as_of)
    if rule is None or not _reciprocity_certificate_satisfied(employee, rule, as_of):
        return empty
    resident_rate_map, resident_slabs = get_state_scoped_config(db, country, residence_state)
    return dict(
        reciprocity_suppresses_work_state=True,
        resident_state_rate_map=resident_rate_map, resident_state_slabs=resident_slabs,
    )


def list_reciprocity_rules(db: Session) -> List[ReciprocityRule]:
    """Full platform-wide list — small enough (one row per real-world
    state pair, not per-org) that there's no filtering need yet."""
    return db.query(ReciprocityRule).order_by(ReciprocityRule.resident_jurisdiction, ReciprocityRule.work_jurisdiction).all()


def upsert_reciprocity_rule(db: Session, data: ReciprocityRuleUpsert, actor_id: Optional[int] = None) -> ReciprocityRule:
    fields = dict(
        resident_jurisdiction=data.residentJurisdiction, work_jurisdiction=data.workJurisdiction,
        agreement_type=data.agreementType, employee_certificate=data.employeeCertificate,
        certificate_required=data.certificateRequired, result_when_valid=data.resultWhenValid,
        effective_from=data.effectiveFrom, effective_to=data.effectiveTo,
        source_document_id=data.sourceDocumentId,
    )
    action = "update" if data.id else "create"
    old_value = None
    if data.id:
        row = db.query(ReciprocityRule).filter(ReciprocityRule.id == data.id).first()
        if not row:
            raise NotFoundException("ReciprocityRule", data.id)
        old_value = {k: (str(getattr(row, k)) if getattr(row, k) is not None else None) for k in fields}
        for k, v in fields.items():
            setattr(row, k, v)
    else:
        row = ReciprocityRule(**fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action=action, entity_type="reciprocity_rule", entity_id=row.id,
        old_value=old_value, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
    )
    return row


def delete_reciprocity_rule(db: Session, rule_id: int, actor_id: Optional[int] = None) -> None:
    row = db.query(ReciprocityRule).filter(ReciprocityRule.id == rule_id).first()
    if not row:
        raise NotFoundException("ReciprocityRule", rule_id)
    old_value = {
        "residentJurisdiction": row.resident_jurisdiction, "workJurisdiction": row.work_jurisdiction,
        "agreementType": row.agreement_type, "employeeCertificate": row.employee_certificate,
    }
    db.delete(row)
    db.commit()
    record_tax_audit(
        db, actor_id=actor_id, action="delete", entity_type="reciprocity_rule", entity_id=rule_id,
        old_value=old_value, new_value=None,
    )


# ── Source Evidence (ZP-TAX-US-2026-001 §14) ──────────────────────────────
# Platform-wide (not US-only) — one row per official publication a
# statutory value was taken from. Immutable in spirit (no update function):
# a correction should be a NEW artifact with `superseded_by_id` pointing
# forward from the old one, not an edit to what was actually retrieved —
# same "don't silently rewrite evidence" reasoning as the immutability
# guard on canonical rate/slab rows.

def list_source_artifacts(db: Session) -> List[SourceArtifact]:
    return db.query(SourceArtifact).order_by(SourceArtifact.created_at.desc()).all()


def create_source_artifact(db: Session, data: SourceArtifactCreate, actor_id: Optional[int] = None) -> SourceArtifact:
    fields = dict(
        agency=data.agency, title=data.title, form_number=data.formNumber,
        source_url=data.sourceUrl, publication_date=data.publicationDate,
        checksum_sha256=data.checksumSha256,
    )
    row = SourceArtifact(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="source_artifact", entity_id=row.id,
        old_value=None, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
    )
    return row


def mark_source_artifact_reviewed(db: Session, artifact_id: int, reviewer_id: int) -> SourceArtifact:
    """A distinct, lightweight action — same "I, this specific person,
    reviewed this" pattern as set_jurisdiction_pack_approver — rather than
    a side effect of any other edit."""
    row = db.query(SourceArtifact).filter(SourceArtifact.id == artifact_id).first()
    if not row:
        raise NotFoundException("SourceArtifact", artifact_id)
    row.reviewer_id = reviewer_id
    row.reviewer_approved_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=reviewer_id, action="review", entity_type="source_artifact", entity_id=row.id,
        old_value={"reviewerId": None}, new_value={"reviewerId": reviewer_id},
    )
    return row


# ── UK: centralized configuration resolver ─────────────────────────────
# One resolver for every UK calculation entry point (preview, generation,
# recalculation, manual payslip) — see build_context_from_employee's
# callers. Layers, in precedence order:
#   UK National (canonical or org-synced, via _resolve_effective_rate_inputs —
#       already org-override-aware, so "organization override" isn't a
#       separate step here, it falls out of calling this with the real
#       organization_id)
#       overridden-by
#   Sub-jurisdiction (England/Scotland/Wales/Northern Ireland, via
#       get_state_scoped_config)
# "Employee-specific statutory profile" (tax_code/ni_category/
# study_loan_plan) isn't a rate_map layer either — engine/countries/uk.py
# reads those straight off PayrollContext and applies them at calculation
# time (tax-code interpretation, NI category bands), not as a config
# merge step. Hardcoded module constants in uk.py remain the emergency
# fallback of last resort, used only when NOTHING resolves at any layer —
# resolve_jurisdiction_parameter already logs when that happens.
_UK_SUB_JURISDICTIONS = {
    "england": "England", "scotland": "Scotland", "wales": "Wales", "northern ireland": "Northern Ireland",
}
# ZP-TAX-UK-2026-27-001 section 6.1: the S/C tax-code prefix is the ONLY
# HMRC-sanctioned region signal ("Do not infer a Scottish or Welsh tax
# regime from the employer's office or worksite"). No prefix means
# England/Northern Ireland/main UK PAYE — this map only ever names the
# two nations that actually have a distinct prefix.
_UK_TAX_CODE_REGION_PREFIX = {"S": "Scotland", "C": "Wales"}


def _normalize_uk_sub_jurisdiction(work_state: Optional[str]) -> Optional[str]:
    """The ONE place a UK jurisdiction name is ever compared against —
    engine/countries/uk.py itself never does `if work_state == "Scotland"`;
    it only reads whatever this resolver already put into
    ctx.state_slabs/ctx.state_rate_map. Unrecognized/blank work_state
    resolves to None (no sub-jurisdiction — national rules only), exactly
    like today's behavior for any non-Scotland employee."""
    if not work_state:
        return None
    return _UK_SUB_JURISDICTIONS.get(work_state.strip().lower())


def _resolve_org_jurisdiction_state_fallback(db: Session, organization_id: int, country: str) -> Optional[str]:
    """The organization's own configured jurisdiction state (Company
    Details / Compliance) — used ONLY as a fallback when an employee has
    no work_state of their own set. Real-world default: most employees
    work wherever the organization itself is registered unless told
    otherwise, so a state-scoped component (India's Professional Tax, US
    state income tax, ...) shouldn't silently resolve to nothing just
    because the employee record's work_state field was never filled in.
    Only applies when the org's own jurisdiction country matches —
    otherwise this org has no state to offer for THIS country anyway."""
    if not organization_id:
        return None
    compliance = (
        db.query(CompanyComplianceDetails)
        .filter(CompanyComplianceDetails.organization_id == organization_id)
        .first()
    )
    if not compliance or not compliance.jurisdiction_state:
        return None
    if _normalize_country(compliance.jurisdiction_country) != _normalize_country(country):
        return None
    return compliance.jurisdiction_state



# ZP-TAX-CA-2026-001 §5 — Province of Employment (POE). Covers the
# single-physical-establishment, remote-attachment, and payroll-fallback
# cases the current data model supports (PayrollEmployee.work_state,
# remote_work_agreement/remote_attachment_province, and the org's own
# configured jurisdiction state). The doc's multi-establishment time-
# weighting and the CA-XP "beyond limits of any province/territory"
# branch still require establishment records nothing in this schema
# captures, and are deliberately NOT implemented here rather than
# guessed at.
_CA_PROVINCES_TERRITORIES = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"}


def _resolve_ca_poe_with_source(
    work_state: Optional[str], org_jurisdiction_state: Optional[str],
    remote_work_agreement: bool = False, remote_attachment_province: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """Returns (poe_result, poe_reason) using the doc's own machine-
    readable reason-code vocabulary, checked in the doc's own §5
    precedence order: PHYSICAL_SINGLE (the employee's own recorded
    work_state — treated as their one physical reporting establishment)
    wins first; REMOTE_ATTACHED (a full-time remote-work agreement is on
    file, with a declared attachment province) only applies when there's
    no physical work_state — an employee who reports somewhere physical
    is never overridden by a stale/unrelated remote-agreement flag;
    PAYROLL_FALLBACK (neither of the above; falls back to the org's own
    jurisdiction state, same fallback every other country already uses);
    or UNRESOLVED (nothing is a recognized province/territory code —
    returns None rather than passing bad data through to jurisdiction-
    scoped config lookup). remote_agreement_effective_from is stored as
    evidence but not enforced against the payroll date here — no other
    employee declaration field (TD1, tax_code, w4_filing_status, ...) in
    this codebase enforces its own effective-dating at this layer either,
    only the current value is ever read."""
    if work_state and work_state.strip().upper() in _CA_PROVINCES_TERRITORIES:
        return work_state.strip().upper(), "PHYSICAL_SINGLE"
    if remote_work_agreement and remote_attachment_province and remote_attachment_province.strip().upper() in _CA_PROVINCES_TERRITORIES:
        return remote_attachment_province.strip().upper(), "REMOTE_ATTACHED"
    if org_jurisdiction_state and org_jurisdiction_state.strip().upper() in _CA_PROVINCES_TERRITORIES:
        return org_jurisdiction_state.strip().upper(), "PAYROLL_FALLBACK"
    return None, "UNRESOLVED"


def _resolve_country_aware_state(country: str, employee, literal_state: Optional[str], db: Session = None, organization_id: int = None) -> Optional[str]:
    """The value actually passed to _resolve_effective_rate_inputs's/
    get_state_scoped_config's `state` param for rate/slab lookup.

    Base layer (every country): if the employee has no work_state of
    their own, fall back to the organization's own configured
    jurisdiction state (_resolve_org_jurisdiction_state_fallback) —
    without this, a state-scoped component silently computes to zero for
    every employee who was never assigned a work_state, even when the
    organization itself has a clear, single jurisdiction on file.

    UK layer (on top): the tax-code-prefix-derived sub-jurisdiction wins
    over either of the above when the employee's own HMRC code carries
    one — see _resolve_uk_sub_jurisdiction_with_source.

    CA layer (on top): resolved via the POE reason-code resolver above
    (physical work_state -> remote attachment -> payroll fallback)
    instead of the raw fallback chain, so an unrecognized province code
    resolves to no jurisdiction rather than being passed through as-is
    — see _resolve_ca_poe_with_source."""
    org_fallback_state = None
    if not literal_state and db is not None:
        org_fallback_state = _resolve_org_jurisdiction_state_fallback(db, organization_id, country)
    effective_state = literal_state or org_fallback_state

    if country == "UK":
        sub_jurisdiction, _source = _resolve_uk_sub_jurisdiction_with_source(getattr(employee, "tax_code", None), effective_state)
        return sub_jurisdiction
    if country == "CA":
        poe_result, _reason = _resolve_ca_poe_with_source(
            literal_state, org_fallback_state,
            remote_work_agreement=bool(getattr(employee, "remote_work_agreement", False)),
            remote_attachment_province=getattr(employee, "remote_attachment_province", None),
        )
        return poe_result
    return effective_state


def _resolve_uk_sub_jurisdiction_with_source(tax_code: Optional[str], work_state: Optional[str]) -> tuple[Optional[str], str]:
    """Region determination per ZP-TAX-UK-2026-27-001 AC-03/AC-04: the
    employee's own HMRC tax-code prefix wins whenever it's present —
    work_state (a worksite/location field) is only a fallback for an
    employee who has no tax code yet (e.g. a brand-new starter still
    pending their first HMRC notice). Returns (sub_jurisdiction, source)
    where source is "TAX_CODE_PREFIX" or "WORK_STATE_FALLBACK", so the
    caller can persist and display which rule actually decided."""
    from app.modules.payroll.engine.countries.uk import interpret_tax_code

    region_prefix = interpret_tax_code(tax_code, Decimal("0"))["region_prefix"]
    if region_prefix:
        return _UK_TAX_CODE_REGION_PREFIX[region_prefix], "TAX_CODE_PREFIX"
    return _normalize_uk_sub_jurisdiction(work_state), "WORK_STATE_FALLBACK"


@dataclass
class ResolvedUKPayrollConfiguration:
    """Return type of resolve_uk_configuration() — field names deliberately
    match build_context_from_employee()'s kwargs so a caller can spread
    the relevant ones straight in. `source_map` and the two pack
    references exist for traceability (Section 16: a payslip should be
    able to name which pack version applied) — snapshotting them onto the
    payslip is the caller's job, this resolver only exposes them."""
    rate_map: dict
    slabs: list
    state_rate_map: dict
    state_slabs: list
    sub_jurisdiction: Optional[str]
    sub_jurisdiction_source: str
    national_pack: Optional["JurisdictionPack"]
    sub_pack: Optional["JurisdictionPack"]
    canonical_rates: list
    source_map: dict


def resolve_uk_configuration(
    db: Session, organization_id: int, employee, payroll_date, tax_regime: Optional[str] = None,
) -> "ResolvedUKPayrollConfiguration":
    """The one centralized UK configuration resolver. Every UK calculation
    entry point should call this instead of assembling rate_map/slabs/
    state_rate_map/state_slabs ad hoc — see preview_payroll_run,
    _compute_payslip_values, and add_payslip_item, all updated to call
    this."""
    org_opted_in = _org_uses_canonical_tax_pack(db, organization_id)
    national_rate_map, national_slabs, canonical_rates, national_pack = _resolve_effective_rate_inputs(
        db, organization_id, "UK", payroll_date, org_opted_in, state=None, tax_regime=tax_regime,
    )

    sub_jurisdiction, sub_jurisdiction_source = _resolve_uk_sub_jurisdiction_with_source(
        getattr(employee, "tax_code", None), getattr(employee, "work_state", None),
    )
    sub_rate_map, sub_slabs = get_state_scoped_config(db, "UK", sub_jurisdiction)

    source_map = {key: "NATIONAL" for key in national_rate_map}
    source_map.update({key: "SUB_JURISDICTION" for key in sub_rate_map})
    # Sub-jurisdiction rate_map rows are layered OVER national, not a
    # replacement — real UK NI/Pension/thresholds aren't devolved at all
    # (this dict is empty for every sub-jurisdiction today), but a future
    # genuinely devolved parameter would correctly take precedence here
    # without any code change.
    resolved_rate_map = {**national_rate_map, **sub_rate_map}

    sub_pack = None
    if sub_jurisdiction:
        sub_pack = (
            db.query(JurisdictionPack)
            .filter(
                JurisdictionPack.jurisdiction_country == "UK",
                JurisdictionPack.jurisdiction_state == sub_jurisdiction,
                JurisdictionPack.pack_type == "tax",
                JurisdictionPack.status == "Active",
            )
            .order_by(JurisdictionPack.id.desc())
            .first()
        )

    return ResolvedUKPayrollConfiguration(
        rate_map=resolved_rate_map, slabs=national_slabs,
        state_rate_map=sub_rate_map, state_slabs=sub_slabs,
        sub_jurisdiction=sub_jurisdiction, sub_jurisdiction_source=sub_jurisdiction_source,
        national_pack=national_pack, sub_pack=sub_pack,
        canonical_rates=canonical_rates or [], source_map=source_map,
    )


def sync_org_rates_from_canonical(
    db: Session, organization_id: int, country: str, state: Optional[str] = None,
    tax_regime: Optional[str] = None, payroll_date=None,
) -> dict:
    """Populate an org's own ContributionRate/TaxSlab rows (the ones the
    engine actually reads) FROM the canonical Super-Admin-owned rows for
    this jurisdiction, via engine/tax_resolver.py. Extends the exact
    pattern super_admin/service.py's seed_global_statutory_rates_from_defaults
    already established — idempotent, safe to call repeatedly.

    No-ops (returns synced=False) if no canonical tax pack exists yet for
    this jurisdiction, leaving the org's existing rows/hardcoded-default
    seed path completely untouched — this function only ever ADDS a new
    source, it never removes the fallback.
    """
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    country = _normalize_country(country)
    canonical_rates, canonical_slabs, pack = resolve_tax_configuration(
        db, country, state=state, tax_regime=tax_regime, payroll_date=payroll_date,
    )
    if not pack:
        return {"synced": False, "reason": "no canonical tax pack configured for this jurisdiction"}

    # Additive state layer (India's state-scoped Professional Tax, etc.):
    # resolve_tax_configuration above is winner-take-all — for a state
    # whose own pack has no income-tax slabs (e.g. Telangana's PT-only
    # pack), it correctly returns the COUNTRY pack instead (the 2026-08-21
    # PT-pack-override fix), which means a single sync call can never
    # produce both the country's income-tax brackets AND the state's own
    # PT_FLAT brackets — whichever call happened last would wipe the
    # other's rows out of this org's cache (TaxSlab sync below is a full
    # delete-then-recreate per (org, country), not additive). Folding in
    # get_state_scoped_config's rows here — the SAME additive lookup the
    # live engine already uses for ctx.state_rate_map/ctx.state_slabs —
    # closes that gap: MARGINAL_RATE rows are excluded from this extra
    # layer so a state that legitimately has its OWN real income-tax pack
    # (UK Scotland) never gets its rows duplicated (they're already in
    # canonical_slabs via resolve_tax_configuration itself in that case).
    if state:
        state_rate_map, state_slabs = get_state_scoped_config(db, country, state)
        existing_rate_keys = {_normalize_engine_component_key(cr.component_key) for cr in canonical_rates}
        canonical_rates = canonical_rates + [
            cr for key, cr in state_rate_map.items() if key not in existing_rate_keys
        ]
        existing_slab_ids = {s.id for s in canonical_slabs}
        canonical_slabs = canonical_slabs + [
            s for s in state_slabs
            if s.id not in existing_slab_ids and getattr(s, "rule_type", None) not in (None, "MARGINAL_RATE")
        ]

    for cr in canonical_rates:
        existing = (
            db.query(ContributionRate)
            .filter(
                ContributionRate.organization_id == organization_id,
                ContributionRate.jurisdiction_country == country,
                ContributionRate.component_key == cr.component_key,
            )
            .first()
        )
        if not existing and cr.label:
            # The canonical row's component_key may not be spelled the same
            # way as the org's existing row for the same real-world
            # component (e.g. Super Admin typed "PF"/"ESI"/"PT" in
            # Statutory Rates while the org's own seed used "pf"/"esi"/
            # "pt", or the labels differ only by a trailing abbreviation —
            # "Employee State Insurance" vs "Employee State Insurance
            # (ESI)") — an exact-key miss would otherwise INSERT a second,
            # visibly-duplicate row instead of updating the org's existing
            # one. Matching on the label with any trailing "(...)" suffix
            # stripped catches that, WITHOUT the false-positive risk a
            # broader substring/synonym search would have here — e.g. it
            # must never conflate the unrelated "ESI Wage Ceiling
            # (monthly)" Tax Parameter with the "esi" contribution rate
            # just because both mention "ESI"; stripping only a trailing
            # parenthetical and requiring the REST of the label to match
            # exactly avoids that (their non-parenthetical text differs).
            wanted_key = _strip_trailing_paren(cr.label)
            for candidate in (
                db.query(ContributionRate)
                .filter(ContributionRate.organization_id == organization_id, ContributionRate.jurisdiction_country == country)
                .all()
            ):
                if candidate.label and _strip_trailing_paren(candidate.label) == wanted_key:
                    existing = candidate
                    break
        fields = dict(
            # Normalized here too, not just at the canonical write path —
            # a canonical row saved before that fix existed can still carry
            # a wrong-cased key, and every sync is the self-healing point
            # for exactly that (matches the label-based dedup pass below,
            # which already exists to clean up this same class of issue).
            component_key=_normalize_engine_component_key(cr.component_key),
            label=cr.label, employee_share=cr.employee_share, employer_share=cr.employer_share,
            total=cr.total, employee_rate_pct=cr.employee_rate_pct, employer_rate_pct=cr.employer_rate_pct,
            flat_amount=cr.flat_amount, sort_order=cr.sort_order,
            jurisdiction_pack_id=pack.id,
        )
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            db.add(ContributionRate(organization_id=organization_id, jurisdiction_country=country, **fields))
    db.flush()

    # Self-healing cleanup: a sync from before the label-fallback match
    # above (or a manual edit) may have already left two rows for the same
    # real-world component under different component_key spellings — same
    # label, two different values shown side by side on the org's
    # Compliance page. Collapse any such group down to the most-recently-
    # touched row (the one this sync just updated, or the latest manual
    # edit) so re-running this sync actually converges instead of leaving
    # old duplicates to drift forever.
    rows = (
        db.query(ContributionRate)
        .filter(ContributionRate.organization_id == organization_id, ContributionRate.jurisdiction_country == country)
        .all()
    )
    by_label: dict = {}
    for row in rows:
        if not row.label:
            continue
        key = _strip_trailing_paren(row.label)
        if not key:
            continue
        by_label.setdefault(key, []).append(row)
    def _last_touched(row):
        ts = row.updated_at or row.created_at
        # (has-a-timestamp, timestamp-or-placeholder, id) — every row compares
        # on the same shape regardless of whether ts ended up None, and id
        # (monotonically increasing, always set) breaks ties deterministically.
        return (ts is not None, ts or row.id, row.id)

    for group in by_label.values():
        if len(group) <= 1:
            continue
        group.sort(key=_last_touched, reverse=True)
        for stale in group[1:]:
            db.delete(stale)

    if canonical_slabs:
        # TaxSlab has no natural per-bracket unique key (brackets are
        # replaced as a whole set when the canonical version changes) —
        # the org's cached copy is fully regenerable from canonical data,
        # so replace-in-place is safe here, unlike ContributionRate above.
        db.query(TaxSlab).filter(
            TaxSlab.organization_id == organization_id, TaxSlab.jurisdiction_country == country,
        ).delete()
        for ts in canonical_slabs:
            db.add(TaxSlab(
                organization_id=organization_id, jurisdiction_country=country,
                min_amount=ts.min_amount, max_amount=ts.max_amount, rate_pct=ts.rate_pct,
                rate_label=ts.rate_label, tax_formula=ts.tax_formula, sort_order=ts.sort_order,
                rule_type=ts.rule_type, formula_expression=ts.formula_expression,
                # PT_FLAT (flat_amount/adjustment_amount) and NI_BAND
                # (ni_category/employer_rate_pct) fields were added to the
                # TaxSlab model after this copy list was first written and
                # were never added here — every org-scoped PT_FLAT/NI_BAND
                # row synced through this path silently lost its actual
                # amount/category, even though it was correctly selected
                # and copied for every other field.
                flat_amount=ts.flat_amount, adjustment_amount=ts.adjustment_amount,
                ni_category=ts.ni_category, employer_rate_pct=ts.employer_rate_pct,
                # Each slab keeps its OWN originating pack id (a state
                # layer row folded in above came from a different pack
                # than `pack` itself) rather than being force-tagged with
                # the single resolved `pack.id` — otherwise a state PT
                # bracket's traceability would wrongly point at the
                # country income-tax pack it has nothing to do with.
                jurisdiction_pack_id=getattr(ts, "jurisdiction_pack_id", None) or pack.id,
            ))

    db.commit()
    return {
        "synced": True, "packId": pack.pack_id, "packVersion": pack.version,
        "contributionRates": len(canonical_rates), "taxSlabs": len(canonical_slabs),
    }


def list_canonical_tax_slabs(
    db: Session, jurisdiction_pack_id: Optional[int] = None, country: Optional[str] = None,
) -> List[TaxSlab]:
    query = db.query(TaxSlab).filter(TaxSlab.organization_id.is_(None))
    if jurisdiction_pack_id:
        query = query.filter(TaxSlab.jurisdiction_pack_id == jurisdiction_pack_id)
    if country:
        query = query.filter(TaxSlab.jurisdiction_country == _normalize_country(country))
    return query.order_by(TaxSlab.sort_order, TaxSlab.min_amount).all()


def upsert_canonical_tax_slab(db: Session, data: CanonicalTaxSlabUpsert, actor_id: Optional[int] = None) -> TaxSlab:
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == data.jurisdictionPackId).first()
    if not pack:
        raise NotFoundException("JurisdictionPack", data.jurisdictionPackId)
    if pack.pack_type != "tax":
        raise BadRequestException("Canonical tax slabs can only be attached to a pack_type='tax' JurisdictionPack.")
    _require_editable_pack(pack)

    fields = dict(
        jurisdiction_country=_normalize_country(data.jurisdictionCountry),
        jurisdiction_state=data.jurisdictionState,
        jurisdiction_locality=data.jurisdictionLocality,
        tax_regime=data.taxRegime,
        filing_status=data.filingStatus,
        min_amount=data.minAmount, max_amount=data.maxAmount,
        rate_pct=data.ratePct, rate_label=data.rateLabel, tax_formula=data.taxFormula,
        rule_type=data.ruleType, formula_expression=data.formulaExpression,
        flat_amount=data.flatAmount, adjustment_amount=data.adjustmentAmount,
        ni_category=data.niCategory, employer_rate_pct=data.employerRatePct,
        sort_order=data.sortOrder, jurisdiction_pack_id=data.jurisdictionPackId,
    )
    action = "update" if data.id else "create"
    old_value = None
    if data.id:
        row = db.query(TaxSlab).filter(TaxSlab.id == data.id, TaxSlab.organization_id.is_(None)).first()
        if not row:
            raise NotFoundException("Canonical TaxSlab", data.id)
        # Snapshot every field this call can mutate, not just 3 of ~13 —
        # the old narrow capture meant a changed rule_type, formula_expression,
        # label, or jurisdiction_state was invisible in the audit trail.
        old_value = {k: (str(getattr(row, k)) if getattr(row, k) is not None else None) for k in fields}
        for k, v in fields.items():
            setattr(row, k, v)
    else:
        row = TaxSlab(organization_id=None, **fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action=action, entity_type="tax_slab", entity_id=row.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version,
        old_value=old_value, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
        reason=data.reason,
    )
    return row


def list_canonical_contribution_rates(
    db: Session, jurisdiction_pack_id: Optional[int] = None, country: Optional[str] = None,
) -> List[ContributionRate]:
    query = db.query(ContributionRate).filter(ContributionRate.organization_id.is_(None))
    if jurisdiction_pack_id:
        query = query.filter(ContributionRate.jurisdiction_pack_id == jurisdiction_pack_id)
    if country:
        query = query.filter(ContributionRate.jurisdiction_country == _normalize_country(country))
    return query.order_by(ContributionRate.sort_order).all()


def upsert_canonical_contribution_rate(
    db: Session, data: CanonicalContributionRateUpsert, actor_id: Optional[int] = None,
) -> ContributionRate:
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == data.jurisdictionPackId).first()
    if not pack:
        raise NotFoundException("JurisdictionPack", data.jurisdictionPackId)
    if pack.pack_type != "tax":
        raise BadRequestException("Canonical contribution rates can only be attached to a pack_type='tax' JurisdictionPack.")
    _require_editable_pack(pack)

    # employee_rate_pct/employer_rate_pct store the plain percentage number
    # (12.00 for 12%), matching every other ContributionRate row in the
    # system (org-scoped rows, the _CONTRIBUTION_RATES_BY_COUNTRY seed
    # dicts) — the engine divides by 100 itself at calculation time
    # (engine/standard.py: `basic * (pf_rate.employee_rate_pct / 100)`).
    # Dividing again here would silently store a value 100x too small.
    employee_pct = data.employeeSharePct
    employer_pct = data.employerSharePct
    # A flat-amount-only row has no employee/employer percentage to sum —
    # the old unconditional f"{... or 0}%" silently displayed "0%" for
    # every one of these instead of the real amount. Two different shapes
    # share the same flatAmount slot though: most (Professional Tax,
    # Standard Deduction, ESI Wage Ceiling, Section 87A limits) are genuine
    # currency thresholds, but a few Tax Parameters (surcharge_cap_pct,
    # cess_pct, ...) are percentages that just happen to be stored via
    # flatAmount too — the "_pct" component_key suffix is the existing,
    # already-established convention distinguishing the two.
    is_flat_only = employee_pct is None and employer_pct is None and data.flatAmount is not None
    if is_flat_only and data.componentKey.endswith("_pct"):
        total_display = f"{data.flatAmount}%"
    elif is_flat_only:
        total_display = f"{_get_currency_symbol(data.jurisdictionCountry)}{data.flatAmount:,.2f}"
    else:
        total_display = f"{(employee_pct or 0) + (employer_pct or 0)}%"
    fields = dict(
        jurisdiction_country=_normalize_country(data.jurisdictionCountry),
        jurisdiction_state=data.jurisdictionState,
        jurisdiction_locality=data.jurisdictionLocality,
        tax_regime=data.taxRegime,
        filing_status=data.filingStatus,
        component_key=_normalize_engine_component_key(data.componentKey), label=data.label,
        employee_share=f"{data.employeeSharePct}%" if data.employeeSharePct is not None else "",
        employer_share=f"{data.employerSharePct}%" if data.employerSharePct is not None else "",
        total=total_display,
        employee_rate_pct=employee_pct, employer_rate_pct=employer_pct, flat_amount=data.flatAmount,
        text_value=data.textValue,
        sort_order=data.sortOrder, jurisdiction_pack_id=data.jurisdictionPackId,
    )
    action = "update" if data.id else "create"
    old_value = None
    if data.id:
        row = db.query(ContributionRate).filter(ContributionRate.id == data.id, ContributionRate.organization_id.is_(None)).first()
        if not row:
            raise NotFoundException("Canonical ContributionRate", data.id)
        # Full-field snapshot (see the matching comment in
        # upsert_canonical_tax_slab) — was previously just 3 of ~13 fields.
        old_value = {k: (str(getattr(row, k)) if getattr(row, k) is not None else None) for k in fields}
        for k, v in fields.items():
            setattr(row, k, v)
    else:
        row = ContributionRate(organization_id=None, **fields)
        db.add(row)
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action=action, entity_type="contribution_rate", entity_id=row.id,
        jurisdiction_pack_id=pack.id, tax_version=pack.version,
        old_value=old_value, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
        reason=data.reason,
    )
    return row


def delete_canonical_contribution_rate(db: Session, rate_id: int, actor_id: Optional[int] = None) -> None:
    """Permanently remove one canonical ContributionRate row from a tax
    pack. Unlike hard-deleting a whole JurisdictionPack, this needs no
    org-assignment/payslip-history guard: org-scoped ContributionRate rows
    are point-in-time SNAPSHOT copies (via sync_org_rates_from_canonical),
    not live references back to this row, and PayslipItem's historical
    snapshot (tax_rule_snapshot) is a JSON copy of the values, not an FK —
    so deleting this row can never retroactively change an org's already-
    synced rates or an already-issued payslip's recorded figures."""
    row = db.query(ContributionRate).filter(ContributionRate.id == rate_id, ContributionRate.organization_id.is_(None)).first()
    if not row:
        raise NotFoundException("Canonical ContributionRate", rate_id)
    old_value = {
        "componentKey": row.component_key, "label": row.label,
        "employee_rate_pct": str(row.employee_rate_pct) if row.employee_rate_pct is not None else None,
        "employer_rate_pct": str(row.employer_rate_pct) if row.employer_rate_pct is not None else None,
        "flat_amount": str(row.flat_amount) if row.flat_amount is not None else None,
    }
    jurisdiction_pack_id = row.jurisdiction_pack_id
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == jurisdiction_pack_id).first() if jurisdiction_pack_id else None
    db.delete(row)
    db.commit()
    record_tax_audit(
        db, actor_id=actor_id, action="delete", entity_type="contribution_rate", entity_id=rate_id,
        jurisdiction_pack_id=jurisdiction_pack_id, tax_version=pack.version if pack else None,
        old_value=old_value, new_value=None,
    )


def delete_canonical_tax_slab(db: Session, slab_id: int, actor_id: Optional[int] = None) -> None:
    """Permanently remove one canonical TaxSlab row from a tax pack — same
    no-retroactive-effect reasoning as delete_canonical_contribution_rate."""
    row = db.query(TaxSlab).filter(TaxSlab.id == slab_id, TaxSlab.organization_id.is_(None)).first()
    if not row:
        raise NotFoundException("Canonical TaxSlab", slab_id)
    old_value = {
        "min_amount": str(row.min_amount), "max_amount": str(row.max_amount) if row.max_amount is not None else None,
        "rate_pct": str(row.rate_pct), "rate_label": row.rate_label,
    }
    jurisdiction_pack_id = row.jurisdiction_pack_id
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == jurisdiction_pack_id).first() if jurisdiction_pack_id else None
    db.delete(row)
    db.commit()
    record_tax_audit(
        db, actor_id=actor_id, action="delete", entity_type="tax_slab", entity_id=slab_id,
        jurisdiction_pack_id=jurisdiction_pack_id, tax_version=pack.version if pack else None,
        old_value=old_value, new_value=None,
    )


def get_active_tax_configuration_for_display(db: Session, country: str, state: Optional[str] = None) -> dict:
    """Read-only: the canonical rates/slabs from whichever tax pack is
    currently Active for this jurisdiction — powers the Statutory Rates
    page's "Platform Default Rates" summary. This is the exact same
    resolution the live payroll engine uses (resolve_tax_configuration),
    just surfaced for display; it never writes anything. Editing these
    values happens on the Compliance page's Rates editor.

    Returns {"pack": None, "rates": [], "slabs": []} when no canonical
    tax pack is Active for this jurisdiction yet — an expected, valid
    state (see resolve_tax_configuration's own docstring), not an error."""
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    country = _normalize_country(country)
    rates, slabs, pack = resolve_tax_configuration(db, country, state=state, payroll_date=date.today())
    return {"pack": pack, "rates": rates, "slabs": slabs}


def list_all_jurisdiction_packs(
    db: Session, country: Optional[str] = None, state: Optional[str] = None,
    status: Optional[str] = None, search: Optional[str] = None, pack_type: Optional[str] = None,
) -> List[JurisdictionPack]:
    """Cross-jurisdiction policy list for Super Admin Compliance — unlike
    list_jurisdiction_packs (which requires a single country and returns
    every version of its packs), this spans every jurisdiction and, per
    pack_id, returns only the latest version — i.e. one row per policy,
    which is what a review/listing screen needs. Use
    get_jurisdiction_pack_versions() to drill into one policy's history.

    `pack_type` ("tax" | "policy") lets the Taxes and Policies tabs query
    this same table with different filters instead of needing two tables.

    Once `country` is scoped, `state` follows the same "None means
    country-level only" convention list_jurisdiction_packs already uses —
    NOT "every state mixed together" — otherwise a jurisdiction-detail view
    scoped to e.g. India with no state picked would silently show
    Telangana's and Maharashtra's packs blended into one list, breaking
    the per-state isolation the jurisdiction-first UI depends on. Only
    when no country is given at all (a genuine global cross-jurisdiction
    browse) does an absent state leave every state unfiltered."""
    query = db.query(JurisdictionPack)
    if country:
        query = query.filter(JurisdictionPack.jurisdiction_country == country)
        if state:
            query = query.filter(JurisdictionPack.jurisdiction_state == state)
        else:
            query = query.filter(JurisdictionPack.jurisdiction_state.is_(None))
    elif state:
        query = query.filter(JurisdictionPack.jurisdiction_state == state)
    if status:
        query = query.filter(JurisdictionPack.status == status)
    if pack_type:
        query = query.filter(JurisdictionPack.pack_type == pack_type)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                JurisdictionPack.pack_id.ilike(like),
                JurisdictionPack.jurisdiction_country.ilike(like),
                JurisdictionPack.compliance_category.ilike(like),
                JurisdictionPack.regulatory_authority.ilike(like),
            )
        )
    rows = query.order_by(JurisdictionPack.pack_id, JurisdictionPack.created_at.desc()).all()

    latest_by_pack_id = {}
    for row in rows:
        if row.pack_id not in latest_by_pack_id:
            latest_by_pack_id[row.pack_id] = row
    return list(latest_by_pack_id.values())


def get_jurisdiction_pack_versions(db: Session, pack_id: str) -> List[JurisdictionPack]:
    """Full version history for one policy, oldest first — nothing is ever
    overwritten (see upsert_jurisdiction_pack), so this reconstructs the
    complete traceable chain."""
    return (
        db.query(JurisdictionPack)
        .filter(JurisdictionPack.pack_id == pack_id)
        .order_by(JurisdictionPack.created_at.asc())
        .all()
    )


def set_jurisdiction_pack_status(db: Session, pack_row_id: int, status: str, actor_id: Optional[int] = None) -> JurisdictionPack:
    row = db.query(JurisdictionPack).filter(JurisdictionPack.id == pack_row_id).first()
    if not row:
        raise NotFoundException("JurisdictionPack", pack_row_id)
    if status == "Active" and row.pack_type == "tax":
        # Prevent two simultaneously-Active tax versions for the same
        # country+state+tax_year+regime (Phase 22 duplicate/overlap guard).
        conflict = (
            db.query(JurisdictionPack)
            .filter(
                JurisdictionPack.id != row.id,
                JurisdictionPack.pack_type == "tax",
                JurisdictionPack.status == "Active",
                JurisdictionPack.jurisdiction_country == row.jurisdiction_country,
                JurisdictionPack.jurisdiction_state == row.jurisdiction_state,
                JurisdictionPack.tax_year == row.tax_year,
                JurisdictionPack.tax_regime == row.tax_regime,
            )
            .first()
        )
        if conflict:
            raise BadRequestException(
                f"Pack {conflict.pack_id} v{conflict.version} is already Active for this "
                f"country/state/tax year/regime — supersede it before activating a new version."
            )
        # Minimum viable maker-checker gate (ZP-TAX-UK-2026-27-001 section
        # 19.2: "author cannot self-approve a production statutory
        # version"). `row.updated_by_id` here is whoever last edited the
        # pack's substance — captured BEFORE this call's own
        # `row.updated_by_id = actor_id` assignment below can overwrite
        # it, so activating a pack doesn't retroactively count as
        # approving your own edit.
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This pack needs a distinct approver before it can go Active — "
                "use \"Approve\" (a different Super Admin than whoever last edited it)."
            )
    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    if row.pack_type == "tax":
        record_tax_audit(
            db, actor_id=actor_id, action="status_change", entity_type="jurisdiction_pack", entity_id=row.id,
            jurisdiction_pack_id=row.id, tax_version=row.version,
            old_value={"status": old_status}, new_value={"status": status},
        )
    return row


def set_jurisdiction_pack_approver(db: Session, pack_row_id: int, actor_id: Optional[int] = None) -> JurisdictionPack:
    """Sets approved_by_id to the calling Super Admin — a distinct,
    lightweight action from the general Edit flow so it means something:
    "I, this specific person, reviewed and approve this configuration."

    Auto-advances status Draft -> Approved so the two-step maker-checker
    sequence (editor drafts -> a DIFFERENT Super Admin approves -> status
    visibly reflects that -> that pack can then be moved to Active) is
    reflected without a separate manual dropdown pick for the first step.
    Only fires from Draft — a pack someone deliberately moved to "In
    Review"/"QA" first keeps that status; approving it still records the
    approver (still required before Active, per set_jurisdiction_pack_status's
    gate below), it just doesn't overwrite a status chosen on purpose.
    Approving a pack already past Draft (Approved/Active/...) does not
    move it backwards."""
    row = db.query(JurisdictionPack).filter(JurisdictionPack.id == pack_row_id).first()
    if not row:
        raise NotFoundException("JurisdictionPack", pack_row_id)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "Draft":
        row.status = "Approved"
    db.commit()
    db.refresh(row)
    if row.pack_type == "tax":
        record_tax_audit(
            db, actor_id=actor_id, action="update", entity_type="jurisdiction_pack", entity_id=row.id,
            jurisdiction_pack_id=row.id, tax_version=row.version,
            old_value={"approved_by_id": old_approver, "status": old_status},
            new_value={"approved_by_id": actor_id, "status": row.status},
            reason="Approver set",
        )
    return row


def get_pack_applicable_organizations(db: Session, pack_row_id: int) -> List[dict]:
    """Organizations currently assigned to this policy version, via the
    existing CompanyComplianceDetails.active_pack_id column — reused as-is
    rather than introducing a new assignment table."""
    from app.modules.organizations.models import Organization

    rows = (
        db.query(Organization.id, Organization.organization_name, Organization.organization_code)
        .join(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == Organization.id)
        .filter(CompanyComplianceDetails.active_pack_id == pack_row_id)
        .all()
    )
    return [{"id": r.id, "organizationName": r.organization_name, "organizationCode": r.organization_code} for r in rows]


def get_organizations_eligible_for_pack(db: Session, pack_row_id: int) -> List[dict]:
    """Organizations whose own jurisdiction matches this pack's, for the
    "Apply Tax & Sync Rates" / "Assign Policy" picker — so a Telangana-only
    Professional Tax pack only ever lists Telangana organizations, not
    every organization on the platform.

    An org's jurisdiction is its own CompanyComplianceDetails
    jurisdiction_country/jurisdiction_state when set (the same field every
    other Compliance query in this codebase treats as authoritative);
    falls back to deriving it from Organization.country/state (the same
    mapping get_company_details' lazy backfill uses) for an org that
    hasn't opened Compliance yet and so has no compliance row at all, or
    one still at its blank/default jurisdiction.

    Country-level packs (jurisdiction_state is None) match any organization
    in that country, regardless of state; a state-level pack only matches
    organizations in that exact state.
    """
    from app.modules.organizations.models import Organization

    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == pack_row_id).first()
    if not pack:
        raise NotFoundException("JurisdictionPack", pack_row_id)

    rows = (
        db.query(Organization, CompanyComplianceDetails)
        .outerjoin(CompanyComplianceDetails, CompanyComplianceDetails.organization_id == Organization.id)
        .all()
    )

    eligible = []
    for org, details in rows:
        country_code = details.jurisdiction_country if details and details.jurisdiction_country else None
        state = details.jurisdiction_state if details and details.jurisdiction_state else None
        if not country_code:
            country_code = org.country and _COUNTRY_NAME_TO_JURISDICTION_CODE.get(org.country.strip().lower())
            state = org.state or None
        if country_code != pack.jurisdiction_country:
            continue
        if pack.jurisdiction_state and state != pack.jurisdiction_state:
            continue
        eligible.append({"id": org.id, "organizationName": org.organization_name, "organizationCode": org.organization_code})
    return eligible


def hard_delete_jurisdiction_pack(db: Session, pack_row_id: int) -> dict:
    """Permanently delete a Tax or Policy pack — the pack row itself, its
    canonical ContributionRate/TaxSlab rows, and its TaxConfigurationAudit
    trail. Unlike set_jurisdiction_pack_status("Retired"), nothing about
    this pack survives.

    Blocked (BadRequestException) in either of two cases, both checked
    BEFORE anything is touched:
      1. Any organization is currently assigned to this pack
         (CompanyComplianceDetails.active_pack_id) — reuses
         get_pack_applicable_organizations, the same check the "Assign"
         UI already uses to show who's on a pack.
      2. Any payslip, for any organization, past or present, was ever
         generated using this pack's rates (PayslipItem.tax_policy_pack_id)
         — per the model's own comment on that column, a payslip's figures
         "MUST NOT change... reproducible even if the pack row is later
         retired," so a pack with real payroll history is retirable, never
         deletable.

    When neither block applies, two more FK relationships are cleaned up
    (not blocked on, since neither is organization or payslip data):
      - Any OTHER org's own ContributionRate/TaxSlab row that still
        carries a stale jurisdiction_pack_id pointing at this pack (left
        over from a past sync to a component_key the org's *current*
        pack no longer has) gets that pointer nulled — the org's actual
        rate values are untouched, only the provenance breadcrumb clears.
        Safe specifically because block #1 above already confirmed no
        org is CURRENTLY assigned to this pack.
      - Any other JurisdictionPack whose previous_version_id points at
        this one (version-chain metadata) gets that pointer nulled.
    """
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == pack_row_id).first()
    if not pack:
        raise NotFoundException("JurisdictionPack", pack_row_id)

    assigned_orgs = get_pack_applicable_organizations(db, pack.id)
    if assigned_orgs:
        names = ", ".join(o["organizationName"] for o in assigned_orgs[:5])
        raise BadRequestException(
            f"{pack.pack_id} v{pack.version} is still assigned to {len(assigned_orgs)} "
            f"organization(s) ({names}{'…' if len(assigned_orgs) > 5 else ''}) — unassign them before deleting."
        )

    has_payslip_history = (
        db.query(PayslipItem.id).filter(PayslipItem.tax_policy_pack_id == pack.id).first() is not None
    )
    if has_payslip_history:
        raise BadRequestException(
            f"{pack.pack_id} v{pack.version} has real payroll history — at least one payslip was "
            f"generated using its rates and must keep referencing it. Retire it instead of deleting."
        )

    db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.isnot(None),
    ).update({"jurisdiction_pack_id": None}, synchronize_session=False)
    db.query(TaxSlab).filter(
        TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.isnot(None),
    ).update({"jurisdiction_pack_id": None}, synchronize_session=False)
    db.query(JurisdictionPack).filter(JurisdictionPack.previous_version_id == pack.id).update(
        {"previous_version_id": None}, synchronize_session=False,
    )

    db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.jurisdiction_pack_id == pack.id).delete()
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).delete()

    pack_id_label, version_label = pack.pack_id, pack.version
    db.delete(pack)
    db.commit()

    import logging
    logging.getLogger("zoiko").info(
        f"[compliance] Super Admin permanently deleted jurisdiction pack {pack_id_label} v{version_label} (id={pack_row_id})."
    )
    return {"packId": pack_id_label, "version": version_label}


# ── Report Templates (jurisdiction-wide; Super Admin-authored) ──────────
# Lifecycle: Draft -> Review -> Approved -> Published -> Active -> Superseded.
# Mirrors JurisdictionPack's versioning/maker-checker/audit conventions
# above, with its own vocabulary and its own component/field structure
# (see models.py's ReportTemplate docstring for why) instead of
# ContributionRate/TaxSlab rows.

# Real, already-computed columns a report field is allowed to map to — the
# enforcement point for "never a fabricated statutory value." Each entry:
# field_key -> (label, field_type, aggregatable).
_PAYSLIP_ITEM_FIELD_CATALOG = {
    "employee_name": ("Employee Name", "text", False),
    "department": ("Department", "text", False),
    "designation": ("Designation", "text", False),
    "pan": ("PAN", "text", False),
    "uan": ("UAN", "text", False),
    "bank_name": ("Bank Name", "text", False),
    "bank_account": ("Bank Account", "text", False),
    "basic_salary": ("Basic Salary", "currency", True),
    "hra": ("HRA", "currency", True),
    "special_allowance": ("Special Allowance", "currency", True),
    "overtime": ("Overtime", "currency", True),
    "additional_compensation": ("Additional Compensation", "currency", True),
    "gross_pay": ("Gross Pay", "currency", True),
    "payable_days": ("Payable Days", "text", False),
    "total_working_days": ("Total Working Days", "text", False),
    "pf": ("Provident Fund (Employee)", "currency", True),
    "esi": ("ESI (Employee)", "currency", True),
    "professional_tax": ("Professional Tax", "currency", True),
    "tds": ("TDS / Income Tax Withheld", "currency", True),
    "surcharge": ("Surcharge", "currency", True),
    "cess": ("Health & Education Cess", "currency", True),
    "social_security": ("Social Security", "currency", True),
    "medicare": ("Medicare", "currency", True),
    "federal_income_tax": ("Federal Income Tax", "currency", True),
    "state_income_tax": ("State Income Tax", "currency", True),
    "local_tax": ("Local Tax", "currency", True),
    "state_disability_insurance": ("State Disability Insurance", "currency", True),
    "ni_employee": ("National Insurance (Employee)", "currency", True),
    "study_loan_deduction": ("Student/Postgraduate Loan Deduction", "currency", True),
    "employee_pension": ("Workplace Pension (Employee)", "currency", True),
    "church_tax": ("Church Tax", "currency", True),
    "cpp2": ("CPP2", "currency", True),
    "total_deductions": ("Total Deductions", "currency", True),
    "employer_pf": ("Provident Fund (Employer)", "currency", True),
    "employer_esi": ("ESI (Employer)", "currency", True),
    "employer_social_security": ("Social Security (Employer)", "currency", True),
    "employer_medicare": ("Medicare (Employer)", "currency", True),
    "employer_pension": ("Pension (Employer)", "currency", True),
    "employer_ni": ("National Insurance (Employer)", "currency", True),
    "employer_futa": ("FUTA (Employer)", "currency", True),
    "employer_sui": ("SUI (Employer)", "currency", True),
    "net_pay": ("Net Pay", "currency", True),
}

_PAYROLL_RUN_FIELD_CATALOG = {
    "run_code": ("Run Code", "text", False),
    "period_label": ("Period", "text", False),
    "period_start": ("Period Start", "date", False),
    "period_end": ("Period End", "date", False),
    "pay_date": ("Pay Date", "date", False),
    "employee_count": ("Employee Count", "text", False),
    "total_gross": ("Total Gross Pay", "currency", False),
    "total_deductions": ("Total Deductions", "currency", False),
    "total_taxes": ("Total Taxes", "currency", False),
    "total_employer_contribution": ("Total Employer Contribution", "currency", False),
    "total_net": ("Total Net Pay", "currency", False),
}

_EMPLOYER_PROFILE_FIELD_CATALOG = {
    "name": ("Employer Name", "text", False),
    "type": ("Employer Type", "text", False),
    "tax_no": ("Tax Registration Number", "text", False),
    "employer_id": ("Employer / Registration ID", "text", False),
    "address": ("Registered Address", "text", False),
    "industry": ("Industry", "text", False),
    "email": ("Employer Email", "text", False),
    "phone": ("Employer Phone", "text", False),
}

_REPORT_FIELD_ALLOWED_COLUMNS = {
    "PAYSLIP_ITEM": _PAYSLIP_ITEM_FIELD_CATALOG,
    "PAYROLL_RUN": _PAYROLL_RUN_FIELD_CATALOG,
    "EMPLOYER_PROFILE": _EMPLOYER_PROFILE_FIELD_CATALOG,
}

# Which PAYSLIP_ITEM fields are actually relevant per country — narrows the
# Super Admin's "available data fields" picker to a sensible subset only.
# upsert_report_field's validation always accepts any real column in the
# catalogs above regardless of country, since a field being real is what
# matters, not whether this file guesses it's "typical" for a jurisdiction.
_PAYSLIP_FIELDS_BY_COUNTRY = {
    "IN": ["employee_name", "department", "designation", "pan", "uan", "bank_name", "bank_account",
           "basic_salary", "hra", "special_allowance", "overtime", "additional_compensation", "gross_pay",
           "payable_days", "total_working_days", "pf", "esi", "professional_tax", "tds", "surcharge", "cess",
           "total_deductions", "employer_pf", "employer_esi", "net_pay"],
    "UK": ["employee_name", "department", "designation", "bank_name", "bank_account",
           "basic_salary", "hra", "special_allowance", "overtime", "additional_compensation", "gross_pay",
           "tds", "ni_employee", "study_loan_deduction", "employee_pension", "total_deductions",
           "employer_ni", "employer_pension", "net_pay"],
    "US": ["employee_name", "department", "designation", "bank_name", "bank_account",
           "basic_salary", "hra", "special_allowance", "overtime", "additional_compensation", "gross_pay",
           "federal_income_tax", "state_income_tax", "local_tax", "social_security", "medicare",
           "state_disability_insurance", "total_deductions",
           "employer_social_security", "employer_medicare", "employer_futa", "employer_sui", "net_pay"],
    # CPP/QPP -> social_security/employer_social_security, EI/QPIP ->
    # esi/employer_esi (the same reused PayrollResult fields India's PF/
    # ESI already populate — see engine/countries/canada.py's own
    # "Reused PayrollResult fields" docstring), CPP2/QPP2 -> cpp2,
    # NWT/Nunavut territorial tax -> local_tax, workers' compensation ->
    # employer_sui. See _PAYSLIP_FIELD_LABEL_OVERRIDES below for the
    # country-appropriate display labels on the reused fields.
    "CA": ["employee_name", "department", "designation", "bank_name", "bank_account",
           "basic_salary", "hra", "special_allowance", "overtime", "additional_compensation", "gross_pay",
           "federal_income_tax", "state_income_tax", "local_tax", "social_security", "esi", "cpp2",
           "total_deductions", "employer_social_security", "employer_esi", "employer_sui", "net_pay"],
}
_DEFAULT_PAYSLIP_FIELDS = list(_PAYSLIP_ITEM_FIELD_CATALOG.keys())

# Per-country display-label overrides for a field this country reuses
# under a different name than the catalog's original (first) owner —
# e.g. Canada's EI/QPIP reuses India's "esi"/"employer_esi" fields, and
# its workers' compensation reuses US's "employer_sui" field. Never
# changes which PayslipItem column is read, only the label shown in the
# Report Template field picker.
_PAYSLIP_FIELD_LABEL_OVERRIDES = {
    "CA": {
        "esi": "Employment Insurance (Employee)",
        "employer_esi": "Employment Insurance (Employer)",
        "employer_sui": "Workers' Compensation (Employer)",
    },
}


def get_available_report_data_fields(country: str) -> List[dict]:
    """The enumerable, backend-owned list a Report Template Field's
    data-mapping dropdown must be populated from — never free-typed.
    Always includes every PAYROLL_RUN/EMPLOYER_PROFILE field (period/
    employer info are the same shape for every jurisdiction) plus the
    PAYSLIP_ITEM fields this country actually populates."""
    country = _normalize_country(country)
    payslip_keys = _PAYSLIP_FIELDS_BY_COUNTRY.get(country, _DEFAULT_PAYSLIP_FIELDS)
    label_overrides = _PAYSLIP_FIELD_LABEL_OVERRIDES.get(country, {})
    items = []
    for key in payslip_keys:
        label, field_type, aggregatable = _PAYSLIP_ITEM_FIELD_CATALOG[key]
        label = label_overrides.get(key, label)
        items.append({"key": key, "label": label, "dataSourceKind": "PAYSLIP_ITEM", "sourceColumn": key,
                      "fieldType": field_type, "aggregatable": aggregatable})
    for key, (label, field_type, aggregatable) in _PAYROLL_RUN_FIELD_CATALOG.items():
        items.append({"key": key, "label": label, "dataSourceKind": "PAYROLL_RUN", "sourceColumn": key,
                      "fieldType": field_type, "aggregatable": aggregatable})
    for key, (label, field_type, aggregatable) in _EMPLOYER_PROFILE_FIELD_CATALOG.items():
        items.append({"key": key, "label": label, "dataSourceKind": "EMPLOYER_PROFILE", "sourceColumn": key,
                      "fieldType": field_type, "aggregatable": aggregatable})
    return items


# Report components a report of a given type is allowed to have — same
# "never a generic unrelated dropdown" enforcement as the field catalog
# above, just for components instead of fields. Keyed by report_type;
# falls back to a generic set for an unrecognized type.
_REPORT_COMPONENTS_BY_TYPE = {
    "TDS": [
        ("employer_info", "Employer Information"), ("employee_info", "Employee Information"),
        ("earnings", "Earnings"), ("deductions", "Deductions"), ("tax", "Tax"),
        ("contributions", "Contributions"), ("employer_contributions", "Employer Contributions"),
        ("ytd", "Year-to-Date"),
    ],
    "P60": [
        ("employer_info", "Employer Information"), ("employee_info", "Employee Information"),
        ("earnings", "Earnings"), ("tax", "Tax"), ("contributions", "National Insurance"),
        ("employer_contributions", "Employer Contributions"), ("ytd", "Year-to-Date"),
    ],
    "941": [
        ("employer_info", "Employer Information"), ("employee_info", "Employee Information"),
        ("earnings", "Earnings"), ("tax", "Federal Tax"), ("contributions", "Social Security & Medicare"),
        ("employer_contributions", "Employer Contributions"),
    ],
    # Distinct report_type keys for named forms that would otherwise share
    # the generic "TDS" category — report_type is the disambiguating key
    # Organizations select by (see list_available_reports_for_org), so two
    # differently-named reports (a per-employee certificate vs. an
    # aggregate quarterly statement) must not collide under one key.
    "FORM_130": [
        ("employer_info", "Employer Information"), ("employee_info", "Employee Information"),
        ("earnings", "Earnings"), ("tax", "Tax"), ("ytd", "Year-to-Date"),
    ],
    "FORM_138": [
        ("employer_info", "Employer Information"), ("tax", "Tax"), ("contributions", "Contributions"),
    ],
    "EPS_FPS": [
        ("employer_info", "Employer Information"), ("contributions", "Contributions"),
        ("employer_contributions", "Employer Contributions"),
    ],
}
_DEFAULT_REPORT_COMPONENTS = [
    ("employer_info", "Employer Information"), ("employee_info", "Employee Information"),
    ("earnings", "Earnings"), ("deductions", "Deductions"), ("tax", "Tax"),
    ("contributions", "Contributions"), ("employer_contributions", "Employer Contributions"),
    ("ytd", "Year-to-Date"),
]


def get_available_report_components(report_type: str) -> List[dict]:
    """The enumerable component catalog for a given report type — Super
    Admin can only add components from this list, never a free-typed or
    unrelated one."""
    options = _REPORT_COMPONENTS_BY_TYPE.get((report_type or "").upper(), _DEFAULT_REPORT_COMPONENTS)
    return [{"key": key, "label": label} for key, label in options]


_EDITABLE_TEMPLATE_STATUSES = ("Draft", "Review", "Approved")


def _require_editable_report_template(template: "ReportTemplate") -> None:
    if template.status not in _EDITABLE_TEMPLATE_STATUSES:
        raise BadRequestException(
            f"Template {template.template_key} v{template.version} is {template.status} — it is no "
            "longer editable. Create a new version (\"New Version\") to make changes; "
            "published report templates must not be edited in place."
        )


def list_report_templates(
    db: Session, country: Optional[str] = None, state: Optional[str] = None,
    reporting_year: Optional[str] = None, report_type: Optional[str] = None,
    status: Optional[str] = None, search: Optional[str] = None,
) -> List[ReportTemplate]:
    """Cross-jurisdiction template list — latest version per template_key,
    same convention as list_all_jurisdiction_packs."""
    query = db.query(ReportTemplate)
    if country:
        query = query.filter(ReportTemplate.jurisdiction_country == country)
        if state:
            query = query.filter(ReportTemplate.jurisdiction_state == state)
        else:
            query = query.filter(ReportTemplate.jurisdiction_state.is_(None))
    elif state:
        query = query.filter(ReportTemplate.jurisdiction_state == state)
    if reporting_year:
        query = query.filter(ReportTemplate.reporting_year == reporting_year)
    if report_type:
        query = query.filter(ReportTemplate.report_type == report_type)
    if status:
        query = query.filter(ReportTemplate.status == status)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(ReportTemplate.name.ilike(like), ReportTemplate.template_key.ilike(like)))
    rows = query.order_by(ReportTemplate.template_key, ReportTemplate.created_at.desc()).all()

    latest_by_key = {}
    for row in rows:
        if row.template_key not in latest_by_key:
            latest_by_key[row.template_key] = row
    return list(latest_by_key.values())


def get_report_template_versions(db: Session, template_key: str) -> List[ReportTemplate]:
    return (
        db.query(ReportTemplate)
        .filter(ReportTemplate.template_key == template_key)
        .order_by(ReportTemplate.created_at.asc())
        .all()
    )


def get_report_template(db: Session, template_id: int) -> ReportTemplate:
    row = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not row:
        raise NotFoundException("ReportTemplate", template_id)
    return row


def get_report_template_detail(db: Session, template_id: int) -> dict:
    """Full template with nested components+fields, assembled explicitly
    (ReportTemplate has no ORM `.components` relationship — deliberately
    kept out of the model to keep it a plain identity/metadata row, same
    as JurisdictionPack) — used by the Super Admin authoring UI's detail
    view."""
    template = get_report_template(db, template_id)
    components = (
        db.query(ReportTemplateComponent)
        .filter(ReportTemplateComponent.report_template_id == template_id)
        .order_by(ReportTemplateComponent.sort_order)
        .all()
    )
    component_dicts = []
    for component in components:
        fields = (
            db.query(ReportTemplateComponentField)
            .filter(ReportTemplateComponentField.component_id == component.id)
            .order_by(ReportTemplateComponentField.sort_order)
            .all()
        )
        component_dicts.append({
            "id": component.id, "report_template_id": component.report_template_id,
            "component_key": component.component_key, "label": component.label,
            "component_category": component.component_category, "sort_order": component.sort_order,
            "fields": fields,
        })
    return {
        "id": template.id, "template_key": template.template_key, "name": template.name,
        "report_type": template.report_type, "jurisdiction_country": template.jurisdiction_country,
        "jurisdiction_state": template.jurisdiction_state, "jurisdiction_locality": template.jurisdiction_locality,
        "reporting_year": template.reporting_year, "version": template.version, "status": template.status,
        "description": template.description, "regulatory_authority": template.regulatory_authority,
        "effective_from": template.effective_from, "effective_to": template.effective_to,
        "change_summary": template.change_summary, "source_references": template.source_references,
        "reconciliation_tolerance": template.reconciliation_tolerance, "approved_by_id": template.approved_by_id,
        "created_by_id": template.created_by_id, "updated_by_id": template.updated_by_id,
        "previous_version_id": template.previous_version_id, "created_at": template.created_at,
        "updated_at": template.updated_at, "components": component_dicts,
    }


def _clone_report_template_structure(db: Session, source_template_id: int, target_template_id: int) -> None:
    """Copies every component+field from source onto target as brand-new
    rows — same rationale as _clone_pack_rates: without this, creating a
    new version for a one-field correction would force re-authoring the
    entire template from scratch."""
    components = (
        db.query(ReportTemplateComponent)
        .filter(ReportTemplateComponent.report_template_id == source_template_id)
        .order_by(ReportTemplateComponent.sort_order)
        .all()
    )
    for component in components:
        new_component = ReportTemplateComponent(
            report_template_id=target_template_id,
            component_key=component.component_key, label=component.label,
            component_category=component.component_category, sort_order=component.sort_order,
        )
        db.add(new_component)
        db.flush()
        fields = (
            db.query(ReportTemplateComponentField)
            .filter(ReportTemplateComponentField.component_id == component.id)
            .order_by(ReportTemplateComponentField.sort_order)
            .all()
        )
        for field in fields:
            db.add(ReportTemplateComponentField(
                component_id=new_component.id, field_key=field.field_key, label=field.label,
                field_type=field.field_type, data_source_kind=field.data_source_kind,
                source_column=field.source_column, aggregation=field.aggregation,
                enum_values=field.enum_values, format_hint=field.format_hint,
                is_required=field.is_required, sort_order=field.sort_order,
            ))
    db.commit()


def upsert_report_template(db: Session, data: "ReportTemplateUpsert", actor_id: Optional[int] = None) -> ReportTemplate:
    """Create or update a Report Template, or create a new version — same
    id-first-then-(template_key, version) lookup, same "version bump is a
    deliberate act" contract, as upsert_jurisdiction_pack."""
    existing = None
    if data.id:
        existing = db.query(ReportTemplate).filter(ReportTemplate.id == data.id).first()
    if not existing:
        existing = (
            db.query(ReportTemplate)
            .filter(ReportTemplate.template_key == data.templateKey, ReportTemplate.version == data.version)
            .first()
        )
    fields = dict(
        template_key=data.templateKey, name=data.name, report_type=data.reportType,
        jurisdiction_country=data.jurisdictionCountry, jurisdiction_state=data.jurisdictionState,
        jurisdiction_locality=data.jurisdictionLocality, reporting_year=data.reportingYear,
        version=data.version, status=data.status, description=data.description,
        regulatory_authority=data.regulatoryAuthority, effective_from=data.effectiveFrom,
        effective_to=data.effectiveTo, change_summary=data.changeSummary,
        source_references=data.sourceReferences, document_scope=data.documentScope,
        source_document_id=data.sourceDocumentId, reconciliation_tolerance=data.reconciliationTolerance,
        approved_by_id=data.approvedById,
    )
    if existing:
        _require_editable_report_template(existing)
        old_value = {k: (str(getattr(existing, k)) if getattr(existing, k) is not None else None) for k in fields}
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.updated_by_id = actor_id
        row = existing
        db.commit()
        db.refresh(row)
        record_tax_audit(
            db, actor_id=actor_id, action="update", entity_type="report_template", entity_id=row.id,
            tax_version=row.version, legal_reference=row.source_references,
            old_value=old_value, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
            reason=data.reason,
        )
        return row

    previous = (
        db.query(ReportTemplate)
        .filter(ReportTemplate.template_key == data.templateKey)
        .order_by(ReportTemplate.created_at.desc())
        .first()
    )
    row = ReportTemplate(
        previous_version_id=previous.id if previous else None,
        created_by_id=actor_id, updated_by_id=actor_id,
        **fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if previous:
        _clone_report_template_structure(db, source_template_id=previous.id, target_template_id=row.id)
    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="report_template", entity_id=row.id,
        tax_version=row.version, legal_reference=row.source_references,
        old_value=None, new_value={k: (str(v) if v is not None else None) for k, v in fields.items()},
        reason=data.reason,
    )
    return row


def upsert_report_component(
    db: Session, report_template_id: int, data: "ReportTemplateComponentUpsert", actor_id: Optional[int] = None,
) -> ReportTemplateComponent:
    template = get_report_template(db, report_template_id)
    _require_editable_report_template(template)

    allowed = {item["key"] for item in get_available_report_components(template.report_type)}
    if data.componentKey not in allowed:
        raise BadRequestException(
            f"'{data.componentKey}' is not an available component for report type {template.report_type!r}."
        )

    existing = None
    if data.id:
        existing = db.query(ReportTemplateComponent).filter(
            ReportTemplateComponent.id == data.id, ReportTemplateComponent.report_template_id == report_template_id,
        ).first()
    if not existing:
        # Falls back to the natural key (report_template_id, component_key)
        # — matches upsert_report_template's own id-first-then-natural-key
        # lookup, and makes re-running a seed script idempotent instead of
        # hitting uq_report_component_template_key on the second run.
        existing = db.query(ReportTemplateComponent).filter(
            ReportTemplateComponent.report_template_id == report_template_id,
            ReportTemplateComponent.component_key == data.componentKey,
        ).first()
    fields = dict(component_key=data.componentKey, label=data.label,
                  component_category=data.componentCategory, sort_order=data.sortOrder)
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing
    row = ReportTemplateComponent(report_template_id=report_template_id, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_report_component(db: Session, component_id: int, actor_id: Optional[int] = None) -> None:
    component = db.query(ReportTemplateComponent).filter(ReportTemplateComponent.id == component_id).first()
    if not component:
        raise NotFoundException("ReportTemplateComponent", component_id)
    template = get_report_template(db, component.report_template_id)
    _require_editable_report_template(template)
    db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.component_id == component_id).delete()
    db.delete(component)
    db.commit()


def upsert_report_field(
    db: Session, component_id: int, data: "ReportTemplateFieldUpsert", actor_id: Optional[int] = None,
) -> ReportTemplateComponentField:
    """The allow-list enforcement point: source_column must be a real,
    already-computed column for the chosen data_source_kind — this is
    what makes "never a fabricated statutory value" an enforced API
    contract rather than a UI convention."""
    component = db.query(ReportTemplateComponent).filter(ReportTemplateComponent.id == component_id).first()
    if not component:
        raise NotFoundException("ReportTemplateComponent", component_id)
    template = get_report_template(db, component.report_template_id)
    _require_editable_report_template(template)

    catalog = _REPORT_FIELD_ALLOWED_COLUMNS.get(data.dataSourceKind)
    if not catalog:
        raise BadRequestException(f"Unknown data source kind {data.dataSourceKind!r}.")
    if data.sourceColumn not in catalog:
        raise BadRequestException(
            f"'{data.sourceColumn}' is not a recognized {data.dataSourceKind} field — "
            "select a field from the available data fields list."
        )
    if data.aggregation and data.aggregation not in ("SUM_RUN", "SUM_YTD"):
        raise BadRequestException(f"Unknown aggregation {data.aggregation!r}.")
    if data.aggregation and not catalog[data.sourceColumn][2]:
        raise BadRequestException(f"'{data.sourceColumn}' is not a numeric field and cannot be aggregated.")

    existing = None
    if data.id:
        existing = db.query(ReportTemplateComponentField).filter(
            ReportTemplateComponentField.id == data.id, ReportTemplateComponentField.component_id == component_id,
        ).first()
    if not existing:
        # Same natural-key fallback as upsert_report_component, for the
        # same idempotency reason (uq_report_field_component_key).
        existing = db.query(ReportTemplateComponentField).filter(
            ReportTemplateComponentField.component_id == component_id,
            ReportTemplateComponentField.field_key == data.fieldKey,
        ).first()
    fields = dict(
        field_key=data.fieldKey, label=data.label, field_type=data.fieldType,
        data_source_kind=data.dataSourceKind, source_column=data.sourceColumn, aggregation=data.aggregation,
        enum_values=data.enumValues, format_hint=data.formatHint, is_required=data.isRequired,
        sort_order=data.sortOrder,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing
    row = ReportTemplateComponentField(component_id=component_id, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_report_field(db: Session, field_id: int, actor_id: Optional[int] = None) -> None:
    field = db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.id == field_id).first()
    if not field:
        raise NotFoundException("ReportTemplateComponentField", field_id)
    component = db.query(ReportTemplateComponent).filter(ReportTemplateComponent.id == field.component_id).first()
    if component:
        template = get_report_template(db, component.report_template_id)
        _require_editable_report_template(template)
    db.delete(field)
    db.commit()


def set_report_template_status(db: Session, template_id: int, status: str, actor_id: Optional[int] = None) -> ReportTemplate:
    row = get_report_template(db, template_id)
    if status in ("Published", "Active"):
        # Minimum viable maker-checker gate, same contract as
        # set_jurisdiction_pack_status: author cannot self-approve.
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This template needs a distinct approver before it can be Published/Activated — "
                "use \"Approve\" (a different Super Admin than whoever last edited it)."
            )
    if status == "Active":
        conflict = (
            db.query(ReportTemplate)
            .filter(
                ReportTemplate.id != row.id,
                ReportTemplate.status == "Active",
                ReportTemplate.jurisdiction_country == row.jurisdiction_country,
                ReportTemplate.jurisdiction_state == row.jurisdiction_state,
                ReportTemplate.reporting_year == row.reporting_year,
                ReportTemplate.report_type == row.report_type,
            )
            .first()
        )
        if conflict:
            raise BadRequestException(
                f"Template {conflict.template_key} v{conflict.version} is already Active for this "
                f"jurisdiction/reporting year/report type — supersede it before activating a new version."
            )
    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="report_template", entity_id=row.id,
        tax_version=row.version, old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_report_template_approver(db: Session, template_id: int, actor_id: Optional[int] = None) -> ReportTemplate:
    """Sets approved_by_id to the calling Super Admin — a distinct action
    from general editing, same semantics as set_jurisdiction_pack_approver.
    Auto-advances Draft -> Approved only; leaves any later status alone."""
    row = get_report_template(db, template_id)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "Draft":
        row.status = "Approved"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="report_template", entity_id=row.id,
        tax_version=row.version, old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status}, reason="Approver set",
    )
    return row


def get_report_template_audit(db: Session, template_id: int) -> List[TaxConfigurationAudit]:
    return (
        db.query(TaxConfigurationAudit)
        .filter(TaxConfigurationAudit.entity_type == "report_template", TaxConfigurationAudit.entity_id == template_id)
        .order_by(TaxConfigurationAudit.created_at.desc())
        .all()
    )


def hard_delete_report_template(db: Session, template_id: int) -> dict:
    row = get_report_template(db, template_id)
    has_generated_history = (
        db.query(GeneratedReport.id).filter(GeneratedReport.report_template_id == row.id).first() is not None
    )
    if has_generated_history:
        raise BadRequestException(
            f"{row.template_key} v{row.version} has generated reports referencing it and must keep "
            "existing — supersede it instead of deleting."
        )
    if row.status in ("Published", "Active"):
        raise BadRequestException(
            f"{row.template_key} v{row.version} is {row.status} — supersede it before deleting."
        )
    db.query(ReportTemplate).filter(ReportTemplate.previous_version_id == row.id).update(
        {"previous_version_id": None}, synchronize_session=False,
    )
    component_ids = [
        c.id for c in db.query(ReportTemplateComponent.id)
        .filter(ReportTemplateComponent.report_template_id == row.id).all()
    ]
    if component_ids:
        db.query(ReportTemplateComponentField).filter(
            ReportTemplateComponentField.component_id.in_(component_ids)
        ).delete(synchronize_session=False)
    db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == row.id).delete(synchronize_session=False)
    template_key_label, version_label = row.template_key, row.version
    db.delete(row)
    db.commit()
    return {"templateKey": template_key_label, "version": version_label}


# ── Statutory Filing Calendar (jurisdiction-wide; Super Admin-authored) ──
# A genuinely new concept — no due-date/deadline asset existed anywhere in
# this codebase before. Follows the exact same versioning/maker-checker
# conventions as ReportTemplate above (never edit a published due date in
# place; a correction is a new row chained via previous_version_id; only
# one Active row per period, enforced here rather than by a DB
# constraint, matching JurisdictionPack's own overlap-guard pattern).

_EDITABLE_FILING_CALENDAR_STATUSES = ("Draft",)


def list_filing_calendar(
    db: Session, country: Optional[str] = None, state: Optional[str] = None,
    report_type: Optional[str] = None, reporting_year: Optional[str] = None, status: Optional[str] = None,
) -> List[StatutoryFilingCalendar]:
    query = db.query(StatutoryFilingCalendar)
    if country:
        query = query.filter(StatutoryFilingCalendar.jurisdiction_country == country)
    if state:
        query = query.filter(StatutoryFilingCalendar.jurisdiction_state == state)
    if report_type:
        query = query.filter(StatutoryFilingCalendar.report_type == report_type)
    if reporting_year:
        query = query.filter(StatutoryFilingCalendar.reporting_year == reporting_year)
    if status:
        query = query.filter(StatutoryFilingCalendar.status == status)
    return query.order_by(StatutoryFilingCalendar.due_date.asc()).all()


def get_filing_calendar_entry(db: Session, entry_id: int) -> StatutoryFilingCalendar:
    row = db.query(StatutoryFilingCalendar).filter(StatutoryFilingCalendar.id == entry_id).first()
    if not row:
        raise NotFoundException("StatutoryFilingCalendar", entry_id)
    return row


def upsert_filing_calendar_entry(
    db: Session, data: "FilingCalendarUpsert", actor_id: Optional[int] = None,
) -> StatutoryFilingCalendar:
    existing = db.query(StatutoryFilingCalendar).filter(StatutoryFilingCalendar.id == data.id).first() if data.id else None
    if not existing:
        # Falls back to the natural key when no id is given — same
        # reasoning as ReportTemplate/Component/Field's own id-first-then-
        # natural-key lookup: without this, re-running a seed script (or
        # any repeat call) would create an unbounded number of duplicate
        # Draft rows for the same period instead of updating the one
        # already-Draft entry (a genuinely published/Active entry is still
        # protected by _require_editable_filing_calendar_status below —
        # this only ever finds/updates a still-editable Draft row).
        existing = (
            db.query(StatutoryFilingCalendar)
            .filter(
                StatutoryFilingCalendar.jurisdiction_country == data.jurisdictionCountry,
                StatutoryFilingCalendar.jurisdiction_state == data.jurisdictionState,
                StatutoryFilingCalendar.report_type == data.reportType,
                StatutoryFilingCalendar.reporting_year == data.reportingYear,
                StatutoryFilingCalendar.period_key == data.periodKey,
                StatutoryFilingCalendar.status.in_(_EDITABLE_FILING_CALENDAR_STATUSES),
            )
            .order_by(StatutoryFilingCalendar.created_at.desc())
            .first()
        )
    fields = dict(
        jurisdiction_country=data.jurisdictionCountry, jurisdiction_state=data.jurisdictionState,
        report_type=data.reportType, reporting_year=data.reportingYear,
        period_key=data.periodKey, period_label=data.periodLabel, due_date=data.dueDate,
        status=data.status, source_document_id=data.sourceDocumentId,
    )
    if existing:
        if existing.status not in _EDITABLE_FILING_CALENDAR_STATUSES:
            raise BadRequestException(
                f"Filing calendar entry for {existing.report_type} {existing.period_key} {existing.reporting_year} "
                f"is {existing.status} — create a corrected entry instead of editing a published due date in place."
            )
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.updated_by_id = actor_id
        db.commit()
        db.refresh(existing)
        return existing

    previous = (
        db.query(StatutoryFilingCalendar)
        .filter(
            StatutoryFilingCalendar.jurisdiction_country == data.jurisdictionCountry,
            StatutoryFilingCalendar.jurisdiction_state == data.jurisdictionState,
            StatutoryFilingCalendar.report_type == data.reportType,
            StatutoryFilingCalendar.reporting_year == data.reportingYear,
            StatutoryFilingCalendar.period_key == data.periodKey,
        )
        .order_by(StatutoryFilingCalendar.created_at.desc())
        .first()
    )
    row = StatutoryFilingCalendar(
        previous_version_id=previous.id if previous else None,
        created_by_id=actor_id, updated_by_id=actor_id, **fields,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def set_filing_calendar_status(db: Session, entry_id: int, status: str, actor_id: Optional[int] = None) -> StatutoryFilingCalendar:
    row = get_filing_calendar_entry(db, entry_id)
    if status == "Active":
        conflict = (
            db.query(StatutoryFilingCalendar)
            .filter(
                StatutoryFilingCalendar.id != row.id,
                StatutoryFilingCalendar.status == "Active",
                StatutoryFilingCalendar.jurisdiction_country == row.jurisdiction_country,
                StatutoryFilingCalendar.jurisdiction_state == row.jurisdiction_state,
                StatutoryFilingCalendar.report_type == row.report_type,
                StatutoryFilingCalendar.reporting_year == row.reporting_year,
                StatutoryFilingCalendar.period_key == row.period_key,
            )
            .first()
        )
        if conflict:
            raise BadRequestException(
                f"An Active due-date entry already exists for {row.report_type} {row.period_key} "
                f"{row.reporting_year} — supersede it before activating a new one."
            )
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    return row


def get_upcoming_filing_dates_for_org(db: Session, organization_id: int, limit: int = 10) -> List[StatutoryFilingCalendar]:
    """Org-facing: this org's own jurisdiction's upcoming Active filing
    obligations, soonest first. Never guessed/hardcoded client-side — the
    frontend just renders whatever this returns."""
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    state = getattr(company, "jurisdiction_state", None) or None

    query = (
        db.query(StatutoryFilingCalendar)
        .filter(
            StatutoryFilingCalendar.jurisdiction_country == country,
            StatutoryFilingCalendar.status == "Active",
            StatutoryFilingCalendar.due_date >= date.today(),
        )
        .filter(or_(StatutoryFilingCalendar.jurisdiction_state.is_(None), StatutoryFilingCalendar.jurisdiction_state == state))
    )
    return query.order_by(StatutoryFilingCalendar.due_date.asc()).limit(limit).all()


# ── Report Template Resolution + Generation (Organization consumption) ──

def get_applicable_report_template(
    db: Session, country: str, state: Optional[str], reporting_year: str, report_type: str,
    as_of: Optional[date] = None,
) -> Optional[ReportTemplate]:
    """Mirrors engine/tax_resolver.py's _find_active_tax_pack: prefers an
    exact state match, falls back to the country-level (state IS NULL)
    template, filters on report_type/reporting_year and effective dates.
    Falls back to a Published (not yet Active) template only when no
    Active version exists — a Published template is a legitimate preview
    candidate, but an Active version always wins when both exist. Returns
    None (never raises) when nothing resolves."""
    country = _normalize_country(country)
    as_of = as_of or date.today()

    def _query(state_filter, statuses):
        q = (
            db.query(ReportTemplate)
            .filter(
                ReportTemplate.jurisdiction_country == country,
                ReportTemplate.reporting_year == reporting_year,
                ReportTemplate.report_type == report_type,
                ReportTemplate.status.in_(statuses),
            )
        )
        q = state_filter(q)
        q = q.filter(
            (ReportTemplate.effective_from.is_(None)) | (ReportTemplate.effective_from <= as_of),
        ).filter(
            (ReportTemplate.effective_to.is_(None)) | (ReportTemplate.effective_to >= as_of),
        )
        return q.order_by(ReportTemplate.updated_at.desc()).first()

    for statuses in (["Active"], ["Published"]):
        if state:
            template = _query(lambda q: q.filter(ReportTemplate.jurisdiction_state == state), statuses)
            if template:
                return template
        template = _query(lambda q: q.filter(ReportTemplate.jurisdiction_state.is_(None)), statuses)
        if template:
            return template
    return None


def list_available_reports_for_org(db: Session, organization_id: int, reporting_year: str) -> List[dict]:
    """Distinct (reportType, name) combinations with a Published/Active
    template covering this org's jurisdiction + reporting year — the real,
    backend-owned list the Org's "Report" dropdown must populate from
    (never a hardcoded frontend list of report names)."""
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    state = getattr(company, "jurisdiction_state", None) or None

    query = (
        db.query(ReportTemplate)
        .filter(
            ReportTemplate.jurisdiction_country == country,
            ReportTemplate.reporting_year == reporting_year,
            ReportTemplate.status.in_(["Published", "Active"]),
        )
        .filter(or_(ReportTemplate.jurisdiction_state.is_(None), ReportTemplate.jurisdiction_state == state))
    )
    seen = {}
    for row in query.all():
        seen.setdefault(row.report_type, row.name)
    return [{"reportType": rt, "name": name} for rt, name in seen.items()]


def get_applicable_report_template_for_org(
    db: Session, organization_id: int, reporting_year: str, report_type: str, payroll_run_id: Optional[int] = None,
) -> dict:
    """Org-facing wrapper: resolves the org's own jurisdiction from
    CompanyComplianceDetails (the same lookup every other org-scoped
    Compliance query in this file uses) before calling
    get_applicable_report_template, and — when a payroll_run_id is given —
    also runs validate_report_generation_context for it. Keeps the router
    thin, matching this module's convention of routers passing only
    organization_id/params and services doing every lookup themselves."""
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    state = getattr(company, "jurisdiction_state", None) or None

    template = get_applicable_report_template(db, country, state, reporting_year, report_type)
    validation = None
    if template and payroll_run_id:
        run = db.query(PayrollRun).filter(PayrollRun.id == payroll_run_id, PayrollRun.organization_id == organization_id).first()
        if not run:
            raise NotFoundException("PayrollRun", payroll_run_id)
        validation = validate_report_generation_context(db, organization_id, template, run)
    return {"template": template, "validation": validation}


def validate_report_generation_context(
    db: Session, organization_id: int, template: ReportTemplate, run: PayrollRun, reporting_period: Optional[str] = None,
) -> dict:
    """Real backend-computed validation object — the frontend must never
    guess these booleans client-side. Returns the same shape regardless
    of pass/fail so the UI always has something to render."""
    reasons = []
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    org_country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    org_state = getattr(company, "jurisdiction_state", None) or None

    jurisdiction_match = (org_country == template.jurisdiction_country) and (
        template.jurisdiction_state is None or template.jurisdiction_state == org_state
    )
    if not jurisdiction_match:
        reasons.append(
            f"Organization jurisdiction ({org_country}{'/' + org_state if org_state else ''}) does not "
            f"match this template's jurisdiction ({template.jurisdiction_country}"
            f"{'/' + template.jurisdiction_state if template.jurisdiction_state else ''})."
        )

    try:
        run_status_index = PAYROLL_STATUS_ORDER.index(PayrollStatus(run.status))
    except ValueError:
        run_status_index = -1
    approved_index = PAYROLL_STATUS_ORDER.index(PayrollStatus.APPROVED)
    run_finalized = run_status_index >= approved_index
    if not run_finalized:
        reasons.append(f"Payroll run {run.run_code or run.id} is {run.status} — it must be Approved or later.")

    period_match = True
    if reporting_period and run.period_label != reporting_period:
        period_match = False
        reasons.append(f"Selected period ({reporting_period}) does not match this run's period ({run.period_label}).")

    template_published = template.status in ("Published", "Active")
    if not template_published:
        reasons.append(f"Template {template.template_key} v{template.version} is {template.status}, not Published/Active.")

    return {
        "jurisdictionMatch": jurisdiction_match, "runFinalized": run_finalized,
        "periodMatch": period_match, "templatePublished": template_published, "reasons": reasons,
    }


def _resolve_field_value(
    db: Session, field: ReportTemplateComponentField, run: PayrollRun, item: Optional[PayslipItem],
    company: Optional[CompanyComplianceDetails], organization_id: int,
):
    if field.data_source_kind == "PAYROLL_RUN":
        value = getattr(run, field.source_column, None)
    elif field.data_source_kind == "EMPLOYER_PROFILE":
        value = getattr(company, field.source_column, None) if company else None
    elif field.data_source_kind == "PAYSLIP_ITEM":
        if field.aggregation == "SUM_RUN":
            total = sum(
                (Decimal(str(getattr(i, field.source_column, 0) or 0)) for i in (run.payslip_items or [])),
                Decimal("0"),
            )
            value = float(total)
        elif field.aggregation == "SUM_YTD" and item is not None:
            # Approximated as "this employee's runs within the same calendar
            # year up to and including this run" — a real sum over real
            # rows, not fabricated data, but a simplification where a
            # jurisdiction's fiscal year doesn't start January 1 (e.g.
            # India Apr-Mar, UK Apr-Apr). Revisit if/when PayrollRun gains
            # its own fiscal-year assignment.
            year_start = date(run.period_end.year, 1, 1) if run.period_end else None
            ytd_query = (
                db.query(PayslipItem)
                .join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
                .filter(
                    PayslipItem.organization_id == organization_id,
                    PayslipItem.employee_id == item.employee_id,
                    PayrollRun.period_end <= run.period_end,
                )
            )
            if year_start:
                ytd_query = ytd_query.filter(PayrollRun.period_end >= year_start)
            total = sum(
                (Decimal(str(getattr(i, field.source_column, 0) or 0)) for i in ytd_query.all()),
                Decimal("0"),
            )
            value = float(total)
        else:
            value = getattr(item, field.source_column, None) if item else None
    else:
        value = None
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    return value


def _compute_report_reconciliation(run: PayrollRun, rendered_data: dict, tolerance: Optional[float]) -> dict:
    """Rendering-consistency check against the run's own aggregates — NOT
    an independent statutory recomputation, since no second calculation
    path exists anywhere in this codebase. Documented as such in the
    stored result."""
    tolerance_dec = Decimal(str(tolerance)) if tolerance is not None else Decimal("0")
    run_totals = {
        "grossPay": float(run.total_gross or 0), "totalDeductions": float(run.total_deductions or 0),
        "totalNet": float(run.total_net or 0),
    }
    totals = rendered_data.get("totals", {})
    report_totals = {
        "grossPay": float(totals.get("gross_pay", 0) or 0),
        "totalDeductions": float(totals.get("total_deductions", 0) or 0),
        "totalNet": float(totals.get("net_pay", 0) or 0),
    }
    field_diffs = []
    mismatch = False
    for key in ("grossPay", "totalDeductions", "totalNet"):
        delta = Decimal(str(run_totals[key])) - Decimal(str(report_totals[key]))
        if abs(delta) > tolerance_dec:
            mismatch = True
        field_diffs.append({"field": key, "runSum": run_totals[key], "reportSum": report_totals[key], "delta": float(delta)})

    row_count_run = len(run.payslip_items or [])
    row_count_report = len(rendered_data.get("employees", []))
    if row_count_run != row_count_report:
        mismatch = True

    return {
        "checkedAt": datetime.utcnow().isoformat(), "runTotals": run_totals, "reportTotals": report_totals,
        "rowCountRun": row_count_run, "rowCountReport": row_count_report, "fieldDiffs": field_diffs,
        "status": "MISMATCH" if mismatch else "MATCH",
        "note": "Rendering-consistency check against PayrollRun/PayslipItem aggregates — the same single "
                "source of truth the report was generated from, not an independent recomputation.",
    }


def generate_report_from_template(
    db: Session, organization_id: int, report_template_id: int, payroll_run_id: int,
    reporting_period: Optional[str] = None, actor_id: Optional[int] = None,
) -> GeneratedReport:
    template = get_report_template(db, report_template_id)
    run = (
        db.query(PayrollRun)
        .filter(PayrollRun.id == payroll_run_id, PayrollRun.organization_id == organization_id)
        .first()
    )
    if not run:
        raise NotFoundException("PayrollRun", payroll_run_id)

    validation = validate_report_generation_context(db, organization_id, template, run, reporting_period)
    if not (validation["jurisdictionMatch"] and validation["runFinalized"] and validation["periodMatch"] and validation["templatePublished"]):
        raise BadRequestException(
            "; ".join(validation["reasons"]) or "This run/template combination is not valid for report generation."
        )

    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    components = (
        db.query(ReportTemplateComponent)
        .filter(ReportTemplateComponent.report_template_id == template.id)
        .order_by(ReportTemplateComponent.sort_order)
        .all()
    )
    component_snapshots = []
    employee_values: dict = {}
    header_values: dict = {}
    totals: dict = {}
    items = run.payslip_items or []

    for component in components:
        fields = (
            db.query(ReportTemplateComponentField)
            .filter(ReportTemplateComponentField.component_id == component.id)
            .order_by(ReportTemplateComponentField.sort_order)
            .all()
        )
        field_snapshots = []
        for field in fields:
            field_snapshots.append({
                "fieldKey": field.field_key, "label": field.label, "type": field.field_type,
                "dataSourceKind": field.data_source_kind, "sourceColumn": field.source_column,
                "aggregation": field.aggregation,
            })
            if field.data_source_kind in ("PAYROLL_RUN", "EMPLOYER_PROFILE") or field.aggregation == "SUM_RUN":
                header_values[field.field_key] = _resolve_field_value(db, field, run, None, company, organization_id)
                if field.aggregation == "SUM_RUN":
                    totals[field.source_column] = header_values[field.field_key]
            else:
                # Plain PAYSLIP_ITEM field, or SUM_YTD (per-employee).
                for item in items:
                    per_emp = employee_values.setdefault(
                        item.id, {"employeeId": item.employee_id, "payslipItemId": item.id,
                                  "employeeName": item.employee_name, "values": {}},
                    )
                    per_emp["values"][field.field_key] = _resolve_field_value(db, field, run, item, company, organization_id)
        component_snapshots.append({"componentKey": component.component_key, "label": component.label, "fields": field_snapshots})

    # Always populate these three for reconciliation, even if the template
    # itself doesn't map them — a report with no explicit gross/deduction/
    # net field mappings must still be reconcilable against the run.
    if "gross_pay" not in totals:
        totals["gross_pay"] = float(sum((Decimal(str(i.gross_pay or 0)) for i in items), Decimal("0")))
    if "total_deductions" not in totals:
        totals["total_deductions"] = float(sum((Decimal(str(i.total_deductions or 0)) for i in items), Decimal("0")))
    if "net_pay" not in totals:
        totals["net_pay"] = float(sum((Decimal(str(i.net_pay or 0)) for i in items), Decimal("0")))

    rendered_data = {
        "templateSnapshot": {"templateKey": template.template_key, "version": template.version, "components": component_snapshots},
        "employer": header_values,
        "period": {
            "periodLabel": run.period_label,
            "periodStart": run.period_start.isoformat() if run.period_start else None,
            "periodEnd": run.period_end.isoformat() if run.period_end else None,
            "payDate": run.pay_date.isoformat() if run.pay_date else None,
        },
        "employees": list(employee_values.values()),
        "totals": totals,
    }
    reconciliation = _compute_report_reconciliation(run, rendered_data, float(template.reconciliation_tolerance) if template.reconciliation_tolerance is not None else None)

    distinct_pack_ids = {i.tax_policy_pack_id for i in items if i.tax_policy_pack_id}
    applicable_pack_id = next(iter(distinct_pack_ids)) if len(distinct_pack_ids) == 1 else None
    applicable_pack_version = None
    if applicable_pack_id:
        pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == applicable_pack_id).first()
        applicable_pack_version = pack.version if pack else None
    if len(distinct_pack_ids) > 1:
        rendered_data["metadata"] = {"taxPacksUsed": list(distinct_pack_ids)}

    existing = (
        db.query(GeneratedReport)
        .filter(
            GeneratedReport.organization_id == organization_id, GeneratedReport.payroll_run_id == payroll_run_id,
            GeneratedReport.report_template_id == report_template_id, GeneratedReport.status == "Generated",
        )
        .first()
    )
    if existing:
        existing.status = "Superseded"
        db.add(existing)

    row = GeneratedReport(
        organization_id=organization_id, report_template_id=template.id, template_version=template.version,
        report_type=template.report_type, payroll_run_id=run.id,
        jurisdiction_country=template.jurisdiction_country, jurisdiction_state=template.jurisdiction_state,
        reporting_year=template.reporting_year, reporting_period=reporting_period or run.period_label,
        applicable_tax_pack_id=applicable_pack_id, applicable_tax_pack_version=applicable_pack_version,
        status="Generated", generated_by_id=actor_id,
        rendered_data=rendered_data, reconciliation=reconciliation,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    row.document_scope = template.document_scope
    return row


def _attach_document_scope(db: Session, rows: List[GeneratedReport]) -> List[GeneratedReport]:
    """Sets a transient (non-persisted) `document_scope` attribute on each
    row from its ReportTemplate — lets GeneratedReportResponse expose
    whether a report is PER_EMPLOYEE (certificate + ZIP download) or
    AGGREGATE (single-document download) without a schema migration or a
    second round-trip from the frontend."""
    template_ids = {r.report_template_id for r in rows}
    scopes = {
        t.id: t.document_scope
        for t in db.query(ReportTemplate.id, ReportTemplate.document_scope).filter(ReportTemplate.id.in_(template_ids)).all()
    } if template_ids else {}
    for row in rows:
        row.document_scope = scopes.get(row.report_template_id, "AGGREGATE")
    return rows


def get_generated_reports(
    db: Session, organization_id: int, payroll_run_id: Optional[int] = None,
    report_type: Optional[str] = None, status: Optional[str] = None,
) -> List[GeneratedReport]:
    query = db.query(GeneratedReport).filter(GeneratedReport.organization_id == organization_id)
    if payroll_run_id:
        query = query.filter(GeneratedReport.payroll_run_id == payroll_run_id)
    if report_type:
        query = query.filter(GeneratedReport.report_type == report_type)
    if status:
        query = query.filter(GeneratedReport.status == status)
    rows = query.order_by(GeneratedReport.generated_at.desc()).all()
    return _attach_document_scope(db, rows)


def get_generated_report(db: Session, organization_id: int, generated_report_id: int) -> GeneratedReport:
    row = (
        db.query(GeneratedReport)
        .filter(GeneratedReport.id == generated_report_id, GeneratedReport.organization_id == organization_id)
        .first()
    )
    if not row:
        raise NotFoundException("GeneratedReport", generated_report_id)
    _attach_document_scope(db, [row])
    return row


def void_generated_report(db: Session, organization_id: int, generated_report_id: int, reason: str, actor_id: Optional[int] = None) -> GeneratedReport:
    row = get_generated_report(db, organization_id, generated_report_id)
    row.status = "Void"
    row.notes = reason
    db.commit()
    db.refresh(row)
    return row


def _format_certificate_field_value(value, field_type: str, currency_symbol: str) -> str:
    """Presentation formatting only — the value itself is whatever
    generate_report_from_template already resolved and stored; this
    function never computes anything, only formats for display."""
    if value is None:
        return "-"
    if field_type == "currency":
        try:
            return f"{currency_symbol} {float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if field_type == "percentage":
        try:
            return f"{float(value):.2f}%"
        except (TypeError, ValueError):
            return str(value)
    if field_type == "boolean":
        return "Yes" if value else "No"
    return str(value)


def generate_report_certificate_pdf_bytes(db: Session, organization_id: int, generated_report_id: int, employee_id: int) -> bytes:
    """Renders a single-employee, form-shaped statutory certificate (e.g.
    India's Form 130 TDS certificate, UK's P60) — modeled directly on
    generate_payslip_pdf_bytes's header/sub-header/bordered-detail-grid
    layout (the only other single-record document in this codebase),
    reusing the same font/color primitives, but fed from a GeneratedReport
    snapshot instead of a live payslip. Only valid for a template whose
    document_scope is PER_EMPLOYEE — an AGGREGATE report (e.g. Form 138)
    has no single-employee document to render this way."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
    import io

    report = get_generated_report(db, organization_id, generated_report_id)
    template = get_report_template(db, report.report_template_id)
    if template.document_scope != "PER_EMPLOYEE":
        raise BadRequestException(
            f"{template.name} is an AGGREGATE report (one document for the whole run) — "
            "there is no per-employee certificate to render for it."
        )
    employee_entry = next(
        (e for e in report.rendered_data.get("employees", []) if e.get("employeeId") == employee_id), None,
    )
    if not employee_entry:
        raise NotFoundException("Employee entry in generated report", employee_id)

    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    company_name = getattr(company, "name", None) or "Company Name"
    sym = _get_currency_symbol(_normalize_country(report.jurisdiction_country))
    period = report.rendered_data.get("period", {})
    field_defs = {
        f["fieldKey"]: f
        for component in report.rendered_data.get("templateSnapshot", {}).get("components", [])
        for f in (component.get("fields") or [])
    }

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    base_font = _register_rupee_font(c)
    F = base_font or "Helvetica"
    FB = f"{base_font}-Bold" if base_font else "Helvetica-Bold"

    navy = colors.HexColor("#1e3a8a")
    gray_100 = colors.HexColor("#F3F4F6")
    gray_300 = colors.HexColor("#D1D5DB")
    gray_500 = colors.HexColor("#6B7280")
    gray_900 = colors.HexColor("#111827")
    white = colors.white

    card_margin = 6 * mm
    margin_l = 14 * mm
    margin_r = width - 14 * mm
    page_w = margin_r - margin_l
    col_mid = width / 2
    y = height - card_margin

    # ── 1. HEADER — navy banner, employer name ──
    header_h = 22 * mm
    c.setFillColor(navy)
    c.rect(card_margin, y - header_h, width - 2 * card_margin, header_h, fill=True, stroke=False)
    c.setFillColor(white)
    c.setFont(FB, 18)
    c.drawString(margin_l + 5 * mm, y - 9 * mm, company_name.upper())
    c.setFont(F, 10)
    c.drawString(margin_l + 5 * mm, y - 16 * mm, "Statutory Certificate — Not a payment instrument")
    y -= header_h

    # ── 2. SUB-HEADER — report name + period ──
    sub_h = 14 * mm
    c.setFillColor(gray_100)
    c.rect(card_margin, y - sub_h, width - 2 * card_margin, sub_h, fill=True, stroke=False)
    c.setFillColor(gray_900)
    c.setFont(FB, 16)
    c.drawCentredString(col_mid, y - 5.5 * mm, template.name.upper())
    c.setFont(F, 10)
    c.setFillColor(gray_500)
    c.drawCentredString(
        col_mid, y - 11.5 * mm,
        f"Reporting Year {report.reporting_year} · Period {period.get('periodLabel', report.reporting_period or '-')} "
        f"· Template v{report.template_version}",
    )
    y -= sub_h + 9 * mm

    # ── 3. EMPLOYEE DETAILS — bordered grid, same primitive as payslips ──
    c.setFillColor(gray_900)
    c.setFont(FB, 13)
    c.drawString(margin_l, y, "Employee Details")
    y -= 6 * mm

    row_h = 8.5 * mm
    label_w = page_w * 0.22
    value_w = page_w * 0.28
    col_x = [margin_l, margin_l + label_w, margin_l + label_w + value_w,
             margin_l + 2 * label_w + value_w, margin_r]

    def draw_row(y_top, cells):
        c.setStrokeColor(gray_300)
        c.setLineWidth(0.4)
        c.rect(margin_l, y_top - row_h, page_w, row_h, fill=False, stroke=True)
        for cx in col_x[1:-1]:
            c.line(cx, y_top, cx, y_top - row_h)
        baseline = y_top - row_h / 2 - 1.5 * mm
        for i, (lbl, val) in enumerate(cells):
            lx, vx = col_x[i * 2], col_x[i * 2 + 1]
            c.setFillColor(gray_900)
            c.setFont(FB, 9.5)
            c.drawString(lx + 3 * mm, baseline, lbl)
            c.setFont(F, 9.5)
            c.drawString(vx + 3 * mm, baseline, str(val)[:40])

    draw_row(y, [("Employee Name", employee_entry.get("employeeName") or "-"), ("Employee ID", str(employee_id))])
    y -= row_h

    # ── 4. STATUTORY COMPONENTS — one labeled section + bordered rows per
    # ReportTemplateComponent, in the exact order Super Admin configured
    # them (mirrors the payslip's Earnings/Deductions mini-tables, but as
    # single-column label:value rows since a certificate's fields aren't
    # naturally a two-column employee-detail grid). ──
    y -= 6 * mm
    for component in report.rendered_data.get("templateSnapshot", {}).get("components", []):
        fields = component.get("fields") or []
        if not fields:
            continue
        c.setFillColor(gray_900)
        c.setFont(FB, 12)
        c.drawString(margin_l, y, component.get("label", ""))
        y -= 6 * mm

        c.setFillColor(navy)
        c.rect(margin_l, y - 8 * mm, page_w, 8 * mm, fill=True, stroke=False)
        c.setFillColor(white)
        c.setFont(FB, 9.5)
        c.drawString(margin_l + 3 * mm, y - 8 * mm + 2.7 * mm, "Item")
        c.drawRightString(margin_r - 3 * mm, y - 8 * mm + 2.7 * mm, "Value")
        y -= 8 * mm

        for field in fields:
            value = employee_entry.get("values", {}).get(field["fieldKey"])
            field_type = field_defs.get(field["fieldKey"], {}).get("type", "text")
            display = _format_certificate_field_value(value, field_type, sym)
            c.setStrokeColor(gray_300)
            c.setLineWidth(0.3)
            c.rect(margin_l, y - 8 * mm, page_w, 8 * mm, fill=False, stroke=True)
            c.setFillColor(gray_900)
            c.setFont(F, 9.5)
            c.drawString(margin_l + 3 * mm, y - 8 * mm + 2.7 * mm, field.get("label", field["fieldKey"]))
            c.drawRightString(margin_r - 3 * mm, y - 8 * mm + 2.7 * mm, display)
            y -= 8 * mm
        y -= 5 * mm

        if y < 30 * mm:
            c.showPage()
            y = height - card_margin

    # ── 5. FOOTER ──
    c.setStrokeColor(gray_300)
    c.setLineWidth(0.5)
    c.line(margin_l, 15 * mm, margin_r, 15 * mm)
    c.setFillColor(gray_500)
    c.setFont(F, 8)
    c.drawCentredString(col_mid, 11 * mm, "This is a system-generated statutory report. It does not require a signature.")
    c.drawCentredString(col_mid, 8 * mm, f"{company_name} | Confidential | Generated {report.generated_at.strftime('%d-%b-%Y') if report.generated_at else '-'}")

    c.showPage()
    c.save()
    return buf.getvalue()


def assign_pack_to_organizations(db: Session, pack_row_id: int, organization_ids: List[int], actor_id: Optional[int] = None) -> dict:
    """Bulk-assign a policy/tax version as the active pack for each given
    org, get-or-creating their CompanyComplianceDetails row exactly like
    every other Compliance write path does (get_or_create_email_settings,
    get_company_details, etc.) rather than requiring the org to have
    configured Compliance first.

    For a TAX pack specifically, this is also the deliberate "push these
    rates to organizations" action (e.g. a new fiscal year's version):
    beyond the active_pack_id label, it force-syncs each org's own
    ContributionRate/TaxSlab rows from this pack's canonical values via
    sync_org_rates_from_canonical — overwriting whatever they had before,
    not just filling in empty rows. Nothing changes for any org until
    Super Admin explicitly does this; activating/deprecating a canonical
    pack alone never touches an org's live payroll numbers.

    For a POLICY pack, the equivalent push is sync_org_policy_from_pack —
    it force-applies every field the pack has explicitly locked
    (allowOverride=False) onto each org's EXISTING PayrollPolicy, so an
    org that already had its own policy actually starts reflecting Super
    Admin's locked values immediately instead of only being blocked from
    diverging further on its next edit. Overridable fields are left alone.
    """
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == pack_row_id).first()
    if not pack:
        raise NotFoundException("JurisdictionPack", pack_row_id)
    is_tax = pack.pack_type == "tax"

    updated = 0
    for org_id in organization_ids:
        details = (
            db.query(CompanyComplianceDetails)
            .filter(CompanyComplianceDetails.organization_id == org_id)
            .first()
        )
        if not details:
            details = CompanyComplianceDetails(organization_id=org_id)
            db.add(details)
        details.active_pack_id = pack.id
        updated += 1
        # Activity log is per-org by design (organization_id is required) —
        # each affected org gets its own "policy applied" entry rather than
        # one untethered platform-wide log row.
        log_activity(
            db, org_id,
            f"Compliance {'tax' if is_tax else 'policy'} {pack.pack_id} v{pack.version} applied by Super Admin.",
            ActivityStatus.INFO, actor_id=actor_id,
        )
    db.commit()

    rates_synced = 0
    if is_tax:
        for org_id in organization_ids:
            result = sync_org_rates_from_canonical(
                db, org_id, pack.jurisdiction_country, state=pack.jurisdiction_state,
            )
            if result.get("synced"):
                rates_synced += 1
                log_activity(
                    db, org_id,
                    f"Tax rates synced from {pack.pack_id} v{pack.version} ({result.get('contributionRates', 0)} "
                    f"contribution rate(s), {result.get('taxSlabs', 0)} tax slab(s)).",
                    ActivityStatus.INFO, actor_id=actor_id,
                )
        db.commit()
    else:
        from app.modules.payroll.policy.service import sync_org_policy_from_pack

        for org_id in organization_ids:
            result = sync_org_policy_from_pack(db, org_id)
            if result.get("synced"):
                rates_synced += 1
                log_activity(
                    db, org_id,
                    f"Policy defaults synced from {pack.pack_id} v{pack.version} (locked fields applied).",
                    ActivityStatus.INFO, actor_id=actor_id,
                )
        db.commit()

    return {"updated": updated, "isTax": is_tax, "ratesSynced": rates_synced}


# _IN_STANDARD_DEDUCTION/_IN_REBATE_87A_LIMIT/_US_STANDARD_DEDUCTION/
# _UK_PERSONAL_ALLOWANCE/_UK_PA_TAPER_THRESHOLD: sourced from
# engine/standard.py (the real calculation engine's own constants) rather
# than redefined here — _get_slab_label() below is display-only (the
# payroll-preview endpoint's "which bracket does this land in" label) and
# is the only remaining user of these in this file.
#
# The rest of what used to live in this section — a second, independent
# _calculate_annual_tax()/_apply_section_87a_rebate()/
# _calculate_annual_tax_in/us/uk(), and the fully-reimplemented
# _calculate_employee_monthly_payroll() (superseded by
# engine.resolver.calculate_payroll(), per that function's own docstring,
# and confirmed to have zero remaining callers anywhere in this codebase)
# has been removed — those were a second, drifting copy of exactly what
# engine/standard.py's per-country strategies already do, not a
# necessary or reachable code path.
from app.modules.payroll.engine.standard import (
    _IN_STANDARD_DEDUCTION, _IN_REBATE_87A_LIMIT,
    _US_STANDARD_DEDUCTION,
    _UK_PERSONAL_ALLOWANCE, _UK_PA_TAPER_THRESHOLD,
)


def _resolve_calculation_mode(db: Session, organization_id: int, calculation_mode: str = None) -> str:
    """Resolve the calculation mode for a payroll operation.

    If *calculation_mode* is already provided (from the request), use it
    directly.  Otherwise, look up the organisation's active policy via
    ``policy.service.get_active_policy`` and read its ``calculation_mode``.
    Falls back to ``"standard"`` if no policy is found."""
    if calculation_mode:
        return calculation_mode
    try:
        from app.modules.payroll.policy.service import get_active_policy
        policy = get_active_policy(db, organization_id)
        return policy.calculation_mode or "standard"
    except Exception:
        return "standard"


def preview_payroll_run(db: Session, organization_id: int, employee_ids: List[int], country: str = "IN",
                         period_start=None, period_end=None, calculation_mode: str = None) -> dict:
    """Dry-run payroll calculation: returns per-employee breakdowns without
    writing anything to the database. Uses the strategy-based payroll engine,
    so preview == persisted by construction.

    Fixed 30-Day Payroll Model:
        PAYROLL_DAYS = 30
        Per Day Salary = Monthly Gross / 30
        Attendance Deduction = Unpaid Leave Days × Per Day Salary

    period_start/period_end are optional because a preview can happen
    before a run (and its period) exists. When provided, unpaid leave days
    are counted from attendance records. When omitted, no attendance
    deduction is applied."""
    from app.modules.payroll.engine.resolver import calculate_payroll, build_context_from_employee

    country = _normalize_country(country)
    calculation_mode = _resolve_calculation_mode(db, organization_id, calculation_mode)
    # Same canonical-pack substitution generate_payslips_for_run uses (see
    # _resolve_effective_rate_inputs) — a preview should show the same
    # numbers a real run for this same period would produce. No run row
    # exists yet during preview, so period_end (falling back to today, the
    # resolver's own default) stands in for the eventual run.pay_date.
    org_opted_in = _org_uses_canonical_tax_pack(db, organization_id)
    rate_map, slabs, _canonical_rates, _pack = _resolve_effective_rate_inputs(
        db, organization_id, country, period_end or date.today(), org_opted_in,
    )
    allowance_components = _resolve_allowance_components(db, organization_id)

    employees = db.query(PayrollEmployee).filter(
        PayrollEmployee.id.in_(employee_ids),
        PayrollEmployee.organization_id == organization_id,
        PayrollEmployee.status == EmployeeStatus.ACTIVE,
        or_(
            PayrollEmployee.date_of_joining == None,
            PayrollEmployee.date_of_joining <= (period_start or date.today()),
        ),
    ).all()

    # Batch-fetch every employee's attendance rows for the period in ONE query
    # instead of 2 queries per employee (unpaid-leave count + rewards/bonus
    # sum) — same fix already applied to generate_payslips_for_run, extended
    # here since preview/recalculate is hit on every wizard click.
    attendance_by_employee: dict = {}
    if period_start and period_end and period_end >= period_start:
        all_records = db.query(PayrollAttendanceRecord).filter(
            PayrollAttendanceRecord.organization_id == organization_id,
            PayrollAttendanceRecord.employee_id.in_([e.id for e in employees]),
            PayrollAttendanceRecord.date >= period_start,
            PayrollAttendanceRecord.date <= period_end,
        ).all()
        for rec in all_records:
            attendance_by_employee.setdefault(rec.employee_id, []).append(rec)

    results = []
    totals = {
        "count": 0,
        "totalGross": Decimal("0"),
        "totalTax": Decimal("0"),
        "totalContributions": Decimal("0"),
        "totalNet": Decimal("0"),
    }
    # Per-distinct-work_state cache, same reasoning as generate_payslips_for_run's
    # cache below — a preview batch can span several employees' states
    # (e.g. one in Scotland, one in England); without this, a region-scoped
    # employee (Scotland's own tax bands, India's state PT, ...) would
    # silently get NATIONAL-only figures here while a real run for the
    # same employee correctly used their region's config — exactly the
    # "preview must never disagree with a real run" gap this closes.
    _state_scoped_cache: dict = {}

    for emp in employees:
        ctc = Decimal(str(getattr(emp, "ctc", 0) or 0))
        monthly_gross = _round2(ctc / MONTHS_PER_YEAR) if ctc else Decimal("0")

        # Fixed 30-Day: count unpaid leave days from attendance records
        unpaid_leave_days = (
            _count_unpaid_leave_days(
                db, organization_id, emp.id, period_start, period_end,
                records=attendance_by_employee.get(emp.id, []),
            )
            if period_start and period_end else 0
        )

        # Full monthly salary split — no proration in the 30-day model
        stored_basic = getattr(emp, "basic", None)
        stored_hra = getattr(emp, "hra", None)
        if stored_basic is not None and stored_hra is not None:
            monthly_basic = _round2(Decimal(str(stored_basic)) / MONTHS_PER_YEAR)
            monthly_hra   = _round2(Decimal(str(stored_hra)) / MONTHS_PER_YEAR)
            basic   = monthly_basic
            hra     = monthly_hra
        else:
            basic_pct, hra_pct = _resolve_salary_split_pct(db, organization_id)
            basic     = _round2(monthly_gross * basic_pct / 100)
            hra       = _round2(monthly_gross * hra_pct / 100)
        # Named allowance components (Transport/Medical/Other/...) are carved
        # out of gross next, in both branches above — Special Allowance is
        # still exactly the same remainder it always was, just computed
        # after these named slices too. Empty `allowance_components` (the
        # common case — no org has configured any yet) makes this a no-op.
        allowance_items, allowance_total = _compute_allowance_components(allowance_components, monthly_gross)
        special = _round2(monthly_gross - basic - hra - allowance_total)

        is_active = emp.status == EmployeeStatus.ACTIVE
        overtime = Decimal("0")
        additional_compensation = (
            _sum_attendance_extras(
                db, organization_id, emp.id, period_start, period_end,
                records=attendance_by_employee.get(emp.id, []),
            )
            if is_active and period_start and period_end else Decimal("0")
        )
        # allowance_total is folded back in here (rather than left inside
        # `special`) so total gross reconstructs correctly — this is a
        # redistribution of where the money sits within gross (Basic/HRA/
        # named allowances/Special), not a change to gross itself.
        gross = basic + hra + special + allowance_total + overtime + additional_compensation

        work_state = getattr(emp, "work_state", None)
        resolution_state = _resolve_country_aware_state(country, emp, work_state, db=db, organization_id=organization_id)
        if resolution_state not in _state_scoped_cache:
            _state_scoped_cache[resolution_state] = get_state_scoped_config(db, country, resolution_state)
        state_rate_map, state_slabs = _state_scoped_cache[resolution_state]

        # Delegate to the strategy engine
        ctx = build_context_from_employee(
            emp, gross=gross, basic=basic, hra=hra,
            special_allowance=special, overtime=overtime,
            additional_compensation=additional_compensation,
            unpaid_leave_days=unpaid_leave_days,
            country=country, rate_map=rate_map, slabs=slabs,
            work_state=work_state, state_rate_map=state_rate_map, state_slabs=state_slabs,
        )
        calc = calculate_payroll(ctx, calculation_mode)

        employee_name = getattr(emp, "name", None) or f"Employee #{emp.id}"

        results.append({
            "employeeId": emp.id,
            "employeeName": employee_name,
            "department": getattr(emp, "department", None),
            "attendanceStatus": "active" if is_active else "inactive",
            "payableDays": float(calc.payable_days),
            "totalWorkingDays": float(calc.payroll_days),
            "unpaidLeaveDays": calc.unpaid_leave_days,
            "attendanceDeduction": float(calc.attendance_deduction),
            "perDaySalary": float(calc.per_day_salary),
            "monthlyGross": float(calc.gross),
            "allowanceItems": [{"key": i["key"], "label": i["label"], "amount": float(i["amount"])} for i in allowance_items],
            "monthlyTax": float(calc.tds),
            "monthlyPf": float(calc.employee_pf),
            "monthlyEsi": float(calc.employee_esi),
            "monthlyPt": float(calc.professional_tax),
            "monthlySocialSecurity": float(calc.social_security),
            "monthlyMedicare": float(calc.medicare),
            "monthlyNi": float(calc.ni_employee),
            "monthlyEmployeePension": float(calc.employee_pension),
            # UK: same "preview must never disagree with the final persisted
            # payslip" reasoning as monthlyEmployeePension above — the
            # Student Loan deduction genuinely reduces net_pay but had no
            # preview-screen column, so it only showed up as an unexplained
            # drop in Net Pay once the run was actually generated.
            "monthlyStudyLoanDeduction": float(calc.study_loan_deduction),
            # total_deductions includes tds; subtract it here so "Contributions"
            # and "Taxes" are non-overlapping components that add up to the
            # actual total deduction, matching how the UI displays them side
            # by side (see get_bank_transfer_summary for the same tds overlap).
            "monthlyContributions": float(calc.total_deductions - calc.tds),
            "monthlyNet": float(calc.net_pay),
            "employerPf": float(calc.employer_pf),
            "employerEsi": float(calc.employer_esi),
            "employerSs": float(calc.employer_social_security),
            "employerMedicare": float(calc.employer_medicare),
            "employerPension": float(calc.employer_pension),
            "employeePension": float(calc.employee_pension),
            "employerNi": float(calc.employer_ni),
            "taxSlabRate": _get_slab_label(calc.gross * MONTHS_PER_YEAR, slabs, country, annual_tax=calc.annual_tax),
        })

        totals["count"] += 1
        totals["totalGross"] += calc.gross
        totals["totalTax"] += calc.tds
        totals["totalContributions"] += calc.total_deductions - calc.tds
        totals["totalNet"] += calc.net_pay

    return {
        "employees": results,
        "totals": {
            "count": totals["count"],
            "totalGross": float(totals["totalGross"]),
            "totalTax": float(totals["totalTax"]),
            "totalContributions": float(totals["totalContributions"]),
            "totalNet": float(totals["totalNet"]),
        },
        "calculationMode": calculation_mode,
    }


def _get_slab_label(annual_income: Decimal, slabs: List[TaxSlab], country: str = "IN",
                     annual_tax: Decimal = None) -> str:
    """Return the rate label of the applicable tax slab for display.
    When annual_tax is provided and equals 0 (e.g. after Section 87A
    rebate), returns a rebate-aware label instead of the raw bracket."""
    if country == "IN":
        taxable = max(Decimal("0"), annual_income - _IN_STANDARD_DEDUCTION)
    elif country == "US":
        taxable = max(Decimal("0"), annual_income - _US_STANDARD_DEDUCTION)
    elif country == "UK":
        pa = _UK_PERSONAL_ALLOWANCE
        if annual_income > _UK_PA_TAPER_THRESHOLD:
            taper = (annual_income - _UK_PA_TAPER_THRESHOLD) / Decimal("2")
            pa = max(Decimal("0"), pa - taper)
        taxable = max(Decimal("0"), annual_income - pa)
    else:
        taxable = annual_income

    if annual_tax is not None and annual_tax == Decimal("0"):
        if country == "IN" and taxable <= _IN_REBATE_87A_LIMIT:
            return "Nil (87A rebate)"

    # `slabs` here is the org's/pack's FULL TaxSlab set — unlike the actual
    # calculation path (engine/countries/uk.py's calculate(), shared.py's
    # _calculate_annual_tax), which each filter NI_BAND/PT_FLAT/SURCHARGE
    # rows out before doing bracket math, this display-only lookup never
    # did. Once a UK pack has real NI_BAND rows (Section D), this label
    # could pick an NI category band instead of an income-tax bracket —
    # same class of bug _pack_has_income_tax_slabs was written to guard
    # against elsewhere, just missed here.
    bracket_slabs = [s for s in slabs if getattr(s, "rule_type", None) not in ("NI_BAND", "PT_FLAT", "SURCHARGE")]
    for slab in sorted(bracket_slabs, key=lambda s: s.min_amount):
        upper = slab.max_amount if slab.max_amount is not None else taxable
        if taxable <= upper:
            return slab.rate_label or "—"
    return bracket_slabs[-1].rate_label if bracket_slabs else "—"


# ── Company Holidays (shared calendar for LOP proration + Attendance/Leave pages) ──
# Seeded per (organization_id, country, year) from _DEFAULT_HOLIDAYS_BY_COUNTRY,
# mirroring _seed_contribution_rates/get_contribution_rates exactly: query
# first, seed only when the filtered query comes back empty, so re-calling
# never duplicates. Scoped by country (not just organization_id) so an
# Enterprise org with more than one onboarded jurisdiction can hold each
# country's holidays independently without colliding on the same date.

def _easter_sunday(year: int) -> date:
    """Western/Gregorian Easter Sunday (Anonymous Gregorian algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """weekday: Monday=0..Sunday=6. n=1..5 for the 1st/2nd/... occurrence,
    n=-1 for the last occurrence in the month."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return date(year, month, 1 + offset + (n - 1) * 7)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def _resolve_holiday_date(entry: dict, year: int) -> date:
    rule = entry["rule"]
    if rule == "fixed":
        return date(year, entry["month"], entry["day"])
    if rule == "nth_weekday":
        return _nth_weekday_of_month(year, entry["month"], entry["weekday"], entry["n"])
    if rule == "easter_offset":
        return _easter_sunday(year) + timedelta(days=entry["offset_days"])
    raise ValueError(f"Unknown holiday date rule: {rule}")


# weekday: Monday=0 .. Sunday=6 (matches date.weekday()).
_DEFAULT_HOLIDAYS_BY_COUNTRY = {
    "IN": [
        {"name": "Republic Day", "rule": "fixed", "month": 1, "day": 26},
        {"name": "Ambedkar Jayanti", "rule": "fixed", "month": 4, "day": 14},
        {"name": "Labour Day", "rule": "fixed", "month": 5, "day": 1},
        {"name": "Independence Day", "rule": "fixed", "month": 8, "day": 15},
        {"name": "Gandhi Jayanti", "rule": "fixed", "month": 10, "day": 2},
        {"name": "Christmas", "rule": "fixed", "month": 12, "day": 25},
    ],
    "US": [
        {"name": "New Year's Day", "rule": "fixed", "month": 1, "day": 1},
        {"name": "Memorial Day", "rule": "nth_weekday", "month": 5, "weekday": 0, "n": -1},
        {"name": "Independence Day", "rule": "fixed", "month": 7, "day": 4},
        {"name": "Labor Day", "rule": "nth_weekday", "month": 9, "weekday": 0, "n": 1},
        {"name": "Thanksgiving", "rule": "nth_weekday", "month": 11, "weekday": 3, "n": 4},
        {"name": "Christmas Day", "rule": "fixed", "month": 12, "day": 25},
    ],
    "UK": [
        {"name": "New Year's Day", "rule": "fixed", "month": 1, "day": 1},
        {"name": "Good Friday", "rule": "easter_offset", "offset_days": -2},
        {"name": "Early May Bank Holiday", "rule": "nth_weekday", "month": 5, "weekday": 0, "n": 1},
        {"name": "Summer Bank Holiday", "rule": "nth_weekday", "month": 8, "weekday": 0, "n": -1},
        {"name": "Christmas Day", "rule": "fixed", "month": 12, "day": 25},
    ],
    "AU": [
        {"name": "New Year's Day", "rule": "fixed", "month": 1, "day": 1},
        {"name": "Australia Day", "rule": "fixed", "month": 1, "day": 26},
        {"name": "ANZAC Day", "rule": "fixed", "month": 4, "day": 25},
        {"name": "Christmas Day", "rule": "fixed", "month": 12, "day": 25},
        {"name": "Boxing Day", "rule": "fixed", "month": 12, "day": 26},
    ],
    "CA": [
        {"name": "New Year's Day", "rule": "fixed", "month": 1, "day": 1},
        {"name": "Canada Day", "rule": "fixed", "month": 7, "day": 1},
        {"name": "Labour Day", "rule": "nth_weekday", "month": 9, "weekday": 0, "n": 1},
        {"name": "Thanksgiving", "rule": "nth_weekday", "month": 10, "weekday": 0, "n": 2},
        {"name": "Christmas Day", "rule": "fixed", "month": 12, "day": 25},
    ],
    "DE": [
        {"name": "New Year's Day", "rule": "fixed", "month": 1, "day": 1},
        {"name": "Good Friday", "rule": "easter_offset", "offset_days": -2},
        {"name": "Easter Monday", "rule": "easter_offset", "offset_days": 1},
        {"name": "German Unity Day", "rule": "fixed", "month": 10, "day": 3},
        {"name": "Christmas Day", "rule": "fixed", "month": 12, "day": 25},
    ],
}


def _seed_holidays_for_country(db: Session, organization_id: int, country: str, year: int) -> List[PayrollHoliday]:
    defaults = _DEFAULT_HOLIDAYS_BY_COUNTRY.get(country, [])
    if not defaults:
        import logging
        logging.getLogger("zoiko").warning(
            f"[payroll-seed] no default holidays available for country '{country}' — "
            f"org {organization_id} will have zero seeded holidays for {year} until configured manually."
        )
    rows = []
    for d in defaults:
        row = PayrollHoliday(
            organization_id=organization_id, country=country, category="National",
            date=_resolve_holiday_date(d, year), name=d["name"],
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def list_holidays(db: Session, organization_id: int, year: int = None) -> List[PayrollHoliday]:
    """Returns every holiday saved for this org (all jurisdictions it has —
    relevant for Enterprise orgs with more than one onboarded country).
    Lazily seeds the org's currently-active jurisdiction's defaults for
    `year` (or the current year if not given) the first time that
    (organization, country, year) combination has no rows yet."""
    target_year = year or date.today().year
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first()
    country = _normalize_country(getattr(company, "jurisdiction_country", None))

    existing_for_year = db.query(PayrollHoliday).filter(
        PayrollHoliday.organization_id == organization_id,
        PayrollHoliday.country == country,
        PayrollHoliday.date >= date(target_year, 1, 1),
        PayrollHoliday.date <= date(target_year, 12, 31),
    ).first()
    if not existing_for_year:
        _seed_holidays_for_country(db, organization_id, country, target_year)

    query = db.query(PayrollHoliday).filter(PayrollHoliday.organization_id == organization_id)
    if year:
        query = query.filter(
            PayrollHoliday.date >= date(year, 1, 1),
            PayrollHoliday.date <= date(year, 12, 31),
        )
    return query.order_by(PayrollHoliday.date).all()


def bulk_upsert_holidays(db: Session, organization_id: int, holidays: list) -> List[PayrollHoliday]:
    """holidays: list of objects/dicts with .date / .name (or ["date"]/["name"]).
    Admin-added/edited holidays are tagged with the org's current jurisdiction
    and category="Company" — distinct from category="National" seeded
    defaults — without ever overwriting country/category on rows that
    already exist (only `name` is updated on conflict, as before)."""
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first()
    country = _normalize_country(getattr(company, "jurisdiction_country", None))

    result = []
    for h in holidays:
        h_date = h.date if hasattr(h, "date") else h["date"]
        h_name = h.name if hasattr(h, "name") else h.get("name")
        row = db.query(PayrollHoliday).filter(
            PayrollHoliday.organization_id == organization_id,
            PayrollHoliday.country == country,
            PayrollHoliday.date == h_date,
        ).first()
        if row:
            row.name = h_name
        else:
            row = PayrollHoliday(
                organization_id=organization_id, country=country, category="Company",
                date=h_date, name=h_name,
            )
            db.add(row)
        result.append(row)
    db.commit()
    for row in result:
        db.refresh(row)
    return result


def delete_holiday(db: Session, organization_id: int, holiday_id: int) -> None:
    row = db.query(PayrollHoliday).filter(
        PayrollHoliday.id == holiday_id, PayrollHoliday.organization_id == organization_id,
    ).first()
    if not row:
        raise NotFoundException(f"Holiday {holiday_id} not found.")
    db.delete(row)
    db.commit()


def _get_holiday_dates(db: Session, organization_id: int, period_start, period_end) -> set:
    rows = db.query(PayrollHoliday.date).filter(
        PayrollHoliday.organization_id == organization_id,
        PayrollHoliday.date >= period_start,
        PayrollHoliday.date <= period_end,
    ).all()
    return {r[0] for r in rows}


# ── Payslip generation (real computation, replaces client-side mock) ──

def _count_unpaid_leave_days(db: Session, organization_id: int, employee_id: int,
                             period_start, period_end, records: List["PayrollAttendanceRecord"] = None) -> int:
    """Count unpaid leave days for this employee within the pay period.

    Uses the Fixed 30-Day Payroll Model:
        PAYROLL_DAYS = 30
        Per Day Salary = Monthly Gross / 30
        Attendance Deduction = Unpaid Leave Days × Per Day Salary
        Payable Days = 30 − Unpaid Leave Days

    Only "absent" status or "leave" with leave_type="unpaid" (or None for
    backwards compatibility) count as unpaid leave. Paid/sick/casual leaves
    do NOT reduce payable days.

    Returns 0 if the period is missing/invalid.

    `records`: pass this employee's attendance rows for the period if the
    caller already batch-fetched them for many employees at once (see
    generate_payslips_for_run) — avoids one query per employee. Queries the
    DB itself only when `records` is None (e.g. the single-employee
    regenerate_employee_payslip path, where batching doesn't help).
    """
    if not period_start or not period_end or period_end < period_start:
        return 0

    if records is None:
        records = db.query(PayrollAttendanceRecord).filter(
            PayrollAttendanceRecord.organization_id == organization_id,
            PayrollAttendanceRecord.employee_id == employee_id,
            PayrollAttendanceRecord.date >= period_start,
            PayrollAttendanceRecord.date <= period_end,
        ).all()
    unpaid_count = 0
    for r in records:
        if r.status == "absent":
            unpaid_count += 1
        elif r.status == "leave" and r.leave_type in ("unpaid", None):
            unpaid_count += 1
    return unpaid_count


def _sum_attendance_extras(db: Session, organization_id: int, employee_id: int,
                            period_start, period_end, records: List["PayrollAttendanceRecord"] = None) -> Decimal:
    """Sums rewards + bonus + other_compensation recorded on this
    employee's attendance for the run's pay period. This is real,
    user-entered compensation data (from the Attendance screen) that was
    previously captured but never reached gross pay — fixed here so what
    a user enters is actually what gets paid.

    `records`: see _count_unpaid_leave_days — pass pre-fetched rows to avoid
    a per-employee query when generating a whole run at once.
    """
    if records is None:
        records = db.query(PayrollAttendanceRecord).filter(
            PayrollAttendanceRecord.organization_id == organization_id,
            PayrollAttendanceRecord.employee_id == employee_id,
            PayrollAttendanceRecord.date >= period_start,
            PayrollAttendanceRecord.date <= period_end,
        ).all()
    total = Decimal("0")
    for r in records:
        total += Decimal(str(r.rewards or 0)) + Decimal(str(r.bonus or 0)) + Decimal(str(r.other_compensation or 0))
    return _round2(total)


def _resolve_tax_snapshot(db: Session, country: str, payroll_date, state=None, tax_regime=None) -> dict:
    """Historical payroll safety (Phase 16): freeze which canonical tax
    pack applied on this payslip's actual pay date, AND the exact rate/
    slab VALUES it held then — not just an id pointer, so this payslip's
    numbers stay reproducible even if the pack is later edited, superseded,
    or retired. No-ops cleanly (all None) when no canonical tax pack has
    been configured for this jurisdiction yet.

    Resolves its own pack independently — used by callers that haven't
    already resolved one via _resolve_effective_rate_inputs. A caller that
    HAS already resolved a pack (for the actual calculation numbers)
    should call _pack_to_tax_snapshot directly instead, to avoid a second
    resolve_tax_configuration query and guarantee the numbers and this
    metadata can never name different pack versions."""
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    rates, slabs, pack = resolve_tax_configuration(
        db, country, state=state, tax_regime=tax_regime, payroll_date=payroll_date,
    )
    return _pack_to_tax_snapshot(rates, slabs, pack)


def _compute_payslip_values(db: Session, run: PayrollRun, employee, rate_map, slabs, country: str = "IN",
                             calculation_mode: str = "standard", attendance_records: List["PayrollAttendanceRecord"] = None,
                             allowance_components: list = None, resolved_pack=None,
                             state_rate_map: dict = None, state_slabs: list = None,
                             employer_tax_profiles: dict = None, reciprocity: dict = None,
                             locality_rate=None) -> dict:
    """Compute every payslip figure for an employee within a run and return
    them as a dict, without touching the database. Shared by initial payslip
    generation (_generate_single_payslip) and recalculation
    (regenerate_employee_payslip) so both always produce identical figures.

    `attendance_records`: this employee's pre-fetched attendance rows for the
    run's period, if the caller already batched them across employees (see
    generate_payslips_for_run) — avoids 2 queries per employee. None means
    "query for this employee alone" (regenerate_employee_payslip's path).

    `resolved_pack`: (canonical_rates, slabs, pack) if the caller already
    resolved a canonical tax pack via _resolve_effective_rate_inputs to get
    rate_map/slabs above — reused here for the tax-snapshot metadata via
    _pack_to_tax_snapshot instead of a second resolve_tax_configuration
    query, so the numbers and the metadata can never disagree on which
    pack version applied. None (the default) means the caller wasn't
    opted into canonical tracking / no pack resolved — falls back to
    _resolve_tax_snapshot's own independent resolution, exactly as before
    this parameter existed.

    `allowance_components`: the org's configured components (see
    _resolve_allowance_components), pre-fetched once per run by the caller —
    this is org-level, not per-employee, so it's threaded through the same
    way rate_map/slabs already are rather than re-queried per employee."""
    from app.modules.payroll.engine.resolver import calculate_payroll, build_context_from_employee

    ctc = Decimal(str(getattr(employee, "ctc", 0) or 0))
    monthly_gross = _round2(ctc / MONTHS_PER_YEAR) if ctc else Decimal("0")

    # Fixed 30-Day: count unpaid leave days only (no weekday/holiday logic)
    unpaid_leave_days = _count_unpaid_leave_days(
        db, run.organization_id, employee.id, run.period_start, run.period_end, records=attendance_records
    )

    # Full monthly salary split — no proration in the 30-day model
    stored_basic = getattr(employee, "basic", None)
    stored_hra = getattr(employee, "hra", None)
    if stored_basic is not None and stored_hra is not None:
        basic   = _round2(Decimal(str(stored_basic)) / MONTHS_PER_YEAR)
        hra     = _round2(Decimal(str(stored_hra)) / MONTHS_PER_YEAR)
    else:
        basic_pct, hra_pct = _resolve_salary_split_pct(db, run.organization_id)
        basic     = _round2(monthly_gross * basic_pct / 100)
        hra       = _round2(monthly_gross * hra_pct / 100)
    # Named allowance components carved out of gross next — Special
    # Allowance is still exactly the remainder, just computed after these
    # named slices too. None/empty makes this a no-op (unchanged behavior).
    allowance_items, allowance_total = _compute_allowance_components(allowance_components or [], monthly_gross)
    special = _round2(monthly_gross - basic - hra - allowance_total)

    is_active = employee.status == EmployeeStatus.ACTIVE
    overtime  = Decimal("0")
    additional_compensation = (
        _sum_attendance_extras(db, run.organization_id, employee.id, run.period_start, run.period_end, records=attendance_records)
        if is_active else Decimal("0")
    )
    # allowance_total folded back in here so total gross reconstructs
    # correctly — see the identical comment in preview_payroll_run.
    gross = basic + hra + special + allowance_total + overtime + additional_compensation

    # Delegate to the strategy engine
    work_state = getattr(employee, "work_state", None)
    ctx = build_context_from_employee(
        employee, gross=gross, basic=basic, hra=hra,
        special_allowance=special, overtime=overtime,
        additional_compensation=additional_compensation,
        unpaid_leave_days=unpaid_leave_days,
        country=country, rate_map=rate_map, slabs=slabs,
        work_state=work_state, state_rate_map=state_rate_map, state_slabs=state_slabs,
        employer_tax_profiles=employer_tax_profiles,
        locality_rate=locality_rate,
        **(reciprocity or {}),
    )
    result = calculate_payroll(ctx, calculation_mode)

    employee_name = getattr(employee, "name", None) or f"Employee #{employee.id}"
    if resolved_pack is not None:
        resolved_rates, resolved_slabs, pack = resolved_pack
        tax_snapshot = _pack_to_tax_snapshot(resolved_rates, resolved_slabs, pack)
    else:
        tax_snapshot = _resolve_tax_snapshot(db, country, run.pay_date)

    return {
        "employee_name": employee_name,
        "department": getattr(employee, "department", None),
        "designation": getattr(employee, "designation", None),
        "date_of_joining": getattr(employee, "date_of_joining", None),
        "bank_name": getattr(employee, "bank_name", None),
        "bank_account": getattr(employee, "bank_account", None),
        "pan": getattr(employee, "pan", None),
        "uan": getattr(employee, "uan", None),
        "ifsc": getattr(employee, "ifsc", None),
        "country_code": country,
        "work_state": work_state,
        "work_locality": getattr(employee, "work_locality", None),
        "compliance_fields": dict(getattr(employee, "compliance_fields", None) or {}),
        **tax_snapshot,
        "allowance_items": [
            PayslipAllowanceItem(key=i["key"], label=i["label"], amount=i["amount"]) for i in allowance_items
        ],
        "basic_salary": result.basic,
        "hra": result.hra,
        "special_allowance": result.special_allowance,
        "overtime": result.overtime,
        "additional_compensation": result.additional_compensation,
        "payable_days": Decimal(result.payable_days),
        "total_working_days": Decimal(result.payroll_days),
        "gross_pay": result.gross,
        "pf": result.employee_pf,
        "esi": result.employee_esi,
        "professional_tax": result.professional_tax,
        "social_security": result.social_security,
        "medicare": result.medicare,
        "ni_employee": result.ni_employee,
        "study_loan_deduction": result.study_loan_deduction,
        "employee_pension": result.employee_pension,
        "church_tax": result.church_tax,
        "cpp2": result.cpp2,
        "tds": result.tds,
        "surcharge": result.surcharge,
        "cess": result.cess,
        "federal_income_tax": result.federal_income_tax,
        "state_income_tax": result.state_income_tax,
        "local_tax": result.local_tax,
        "state_disability_insurance": result.state_disability_insurance,
        "total_deductions": result.total_deductions,
        "employer_pf": result.employer_pf,
        "employer_esi": result.employer_esi,
        "employer_social_security": result.employer_social_security,
        "employer_medicare": result.employer_medicare,
        "employer_pension": result.employer_pension,
        "employer_ni": result.employer_ni,
        "employer_futa": result.employer_futa,
        "employer_sui": result.employer_sui,
        "net_pay": result.net_pay,
        "unpaid_leave_days": result.unpaid_leave_days,
        "attendance_deduction": result.attendance_deduction,
        "per_day_salary": result.per_day_salary,
    }


def _generate_single_payslip(db: Session, run: PayrollRun, employee, rate_map, slabs, country: str = "IN",
                              calculation_mode: str = "standard", payslip_number: str = None,
                              attendance_records: List["PayrollAttendanceRecord"] = None,
                              allowance_components: list = None, resolved_pack=None,
                              state_rate_map: dict = None, state_slabs: list = None,
                              employer_tax_profiles: dict = None, reciprocity: dict = None,
                              locality_rate=None) -> PayslipItem:
    """Generate a single payslip using the strategy-based payroll engine.

    Fixed 30-Day Payroll Model:
        PAYROLL_DAYS = 30
        Per Day Salary = Monthly Gross / 30
        Attendance Deduction = Unpaid Leave Days × Per Day Salary
        Payable Days = 30 − Unpaid Leave Days

    Salary components (basic, hra, special) are full monthly amounts — no
    proration.  Attendance deduction is a separate line item.  Statutory
    deductions are computed on the full gross by the resolved strategy.

    `resolved_pack`: passed straight through to _compute_payslip_values —
    see its docstring.
    """
    values = _compute_payslip_values(
        db, run, employee, rate_map, slabs, country, calculation_mode,
        attendance_records=attendance_records, allowance_components=allowance_components,
        resolved_pack=resolved_pack, state_rate_map=state_rate_map, state_slabs=state_slabs,
        employer_tax_profiles=employer_tax_profiles, reciprocity=reciprocity,
        locality_rate=locality_rate,
    )

    item = PayslipItem(
        payroll_run_id=run.id,
        employee_id=employee.id,
        organization_id=run.organization_id,
        payslip_number=payslip_number,
        status=PayslipStatus.PENDING,
        **values,
    )
    db.add(item)
    return item


def _recompute_run_aggregates(db: Session, run: PayrollRun):
    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    run.employee_count = len(items)
    run.total_gross = sum((i.gross_pay for i in items), Decimal("0"))
    run.total_deductions = sum((i.total_deductions for i in items), Decimal("0"))
    run.total_taxes = sum((i.tds for i in items), Decimal("0"))
    run.total_employer_contribution = sum(
        (i.employer_pf + i.employer_esi + i.employer_social_security + i.employer_medicare + i.employer_pension
         + i.employer_ni + i.employer_futa + i.employer_sui for i in items),
        Decimal("0"),
    )
    run.total_net = sum((i.net_pay for i in items), Decimal("0"))
    db.commit()
    db.refresh(run)
    return run


def _resolve_run_calc_inputs(db: Session, run: PayrollRun, organization_id: int = None) -> str:
    """Calculation mode for generating payslips within a run. Used by both a
    full run generation and a single-employee regeneration so the two never
    resolve it differently.

    Jurisdiction/rate-map/slab lookups are NOT resolved here — they used to
    be, from the org's single CompanyComplianceDetails.jurisdiction_country,
    which meant every employee in a run was calculated (and later
    displayed) under the org's one default country regardless of that
    employee's own PayrollEmployee.country_code. See
    _resolve_employee_calc_inputs for the per-employee resolution that
    replaced it."""
    return getattr(run, "calculation_mode", None) or _resolve_calculation_mode(db, organization_id)


def _resolve_employee_calc_inputs(
    db: Session, organization_id: int, employee, cache: dict = None,
    payroll_date=None, org_opted_in: bool = False,
):
    """Per-employee jurisdiction + rate-map/slab resolution for payslip
    generation — an employee's own country_code overrides the org default
    (_resolve_employee_country), the same override employee create/update
    already honor. `cache` (keyed by resolved country/state/tax_regime)
    lets a batch caller reuse rate_map/slabs across employees who share a
    jurisdiction instead of re-querying/re-resolving per employee.

    `payroll_date`/`org_opted_in`: passed through to
    _resolve_effective_rate_inputs so an org that has opted into canonical
    tax-pack tracking gets rates/slabs from whichever pack version was
    actually in force on `payroll_date`, not just whatever is currently
    cached in the org's own ContributionRate/TaxSlab rows. `org_opted_in`
    defaults to False so any existing caller that hasn't been updated to
    pass it keeps today's exact behavior.

    Returns (country, rate_map, slabs, pack, state, state_rate_map,
    state_slabs, employer_tax_profiles, reciprocity) — pack is the resolved
    canonical JurisdictionPack when one was used, else None (see
    _resolve_effective_rate_inputs); state_rate_map/state_slabs are the
    separate, additive region-scoped lookup (see get_state_scoped_config) —
    {}/[] when the employee has no work_state or nothing is configured for
    it; employer_tax_profiles is the US-specific tenant/agency-assigned
    overlay (see get_employer_tax_profiles) — {} for every non-US employee
    and for any US employee whose org has no configured profile; reciprocity
    is a dict of PayrollContext kwargs (see _resolve_us_reciprocity) —
    resolved fresh per employee, deliberately NOT part of the cached tuple
    below, since two employees sharing the same work_state can have
    different residence_state values (one genuinely a cross-state
    commuter, one not), so caching by work_state alone would silently
    apply one employee's reciprocity outcome to another's; locality_rate
    is the US-specific manually-entered local tax rate for this employee's
    own work_locality (see get_locality_rate) — also resolved fresh per
    employee for the same reason, None unless the employee has
    work_locality set AND a matching rate exists."""
    country = _resolve_employee_country(db, organization_id, getattr(employee, "country_code", None))
    state = getattr(employee, "work_state", None)
    tax_regime = getattr(employee, "tax_regime", None)
    # US-specific (NULL/unused for every other country): Form W-4 filing
    # status. Included in cache_key below because two employees sharing the
    # same (country, state, tax_regime) can still have DIFFERENT filing
    # statuses once filing-status-specific ContributionRate/TaxSlab rows
    # exist — without this, a batch run would silently reuse one
    # employee's filing-status-resolved rate_map for another's.
    filing_status = getattr(employee, "w4_filing_status", None)
    # Falls back to the organization's own configured jurisdiction state
    # when the employee has no work_state of their own (every country);
    # UK's resolution state is additionally tax-code-prefix-derived
    # (ZP-TAX-UK-2026-27-001 AC-03/AC-04) — see _resolve_country_aware_state.
    # `state` itself (returned below, used for ctx.work_state) stays the
    # employee's literal worksite field either way — only which rate/slab
    # pack gets selected changes.
    resolution_state = _resolve_country_aware_state(country, employee, state, db=db, organization_id=organization_id)
    cache_key = (country, resolution_state, tax_regime, filing_status)
    if cache is not None and cache_key in cache:
        rate_map, slabs, canonical_rates, pack, state_rate_map, state_slabs, employer_tax_profiles = cache[cache_key]
    else:
        rate_map, slabs, canonical_rates, pack = _resolve_effective_rate_inputs(
            db, organization_id, country, payroll_date, org_opted_in, state=resolution_state, tax_regime=tax_regime,
            filing_status=filing_status,
        )
        state_rate_map, state_slabs = get_state_scoped_config(db, country, resolution_state)
        # US SUI/etc. and CA workers'-comp/similar employer-specific
        # notices both resolve through the same tenant-specific-rate
        # mechanism (jurisdiction_id stays None for every other country,
        # so get_employer_tax_profiles is a no-op there): "US-<state>" or
        # "CA-<province>" rather than by pack/regime. CA-D06/AC-24: never
        # a global-default rate, only an employer-specific notice.
        jurisdiction_id = f"{country}-{resolution_state}" if (country in ("US", "CA") and resolution_state) else None
        employer_tax_profiles = get_employer_tax_profiles(db, organization_id, jurisdiction_id, as_of=payroll_date)
        if cache is not None:
            cache[cache_key] = (rate_map, slabs, canonical_rates, pack, state_rate_map, state_slabs, employer_tax_profiles)
    resolved_pack = (canonical_rates, slabs, pack) if pack is not None else None
    reciprocity = _resolve_us_reciprocity(db, employee, country, resolution_state, as_of=payroll_date)
    # US-specific, resolved fresh per employee (not cached, same reasoning
    # as reciprocity above) — each employee has their own work_locality.
    locality_rate = (
        get_locality_rate(db, country, getattr(employee, "work_locality", None), as_of=payroll_date)
        if country == "US" else None
    )
    return country, rate_map, slabs, resolved_pack, state, state_rate_map, state_slabs, employer_tax_profiles, reciprocity, locality_rate


def generate_payslips_for_run(db: Session, run: PayrollRun, organization_id: int = None, employee_ids: List[int] = None) -> PayrollRun:
    """Generate a payslip for every Active employee in the org (or only the
    specified employee_ids if provided). Idempotent: re-running skips
    employees who already have a payslip in this run."""
    calculation_mode = _resolve_run_calc_inputs(db, run, organization_id)
    # Org-level, not per-employee — resolved once for the whole run, same as
    # rate_map/slabs are cached per-jurisdiction below.
    allowance_components = _resolve_allowance_components(db, organization_id)
    # Org-level, resolved once — gates whether _resolve_employee_calc_inputs
    # is even allowed to substitute canonical, date-resolved rates for this
    # org's own cached rates (see _org_uses_canonical_tax_pack).
    org_opted_in = _org_uses_canonical_tax_pack(db, organization_id)

    employees_query = db.query(PayrollEmployee).filter(
        PayrollEmployee.status == EmployeeStatus.ACTIVE,
        PayrollEmployee.organization_id == organization_id,
    )
    if employee_ids:
        employees_query = employees_query.filter(PayrollEmployee.id.in_(employee_ids))
    # Exclude employees whose date_of_joining is after the pay period start
    employees_query = employees_query.filter(
        or_(
            PayrollEmployee.date_of_joining == None,
            PayrollEmployee.date_of_joining <= run.period_start,
        )
    )
    employees = employees_query.all()

    existing_ids = {
        row.employee_id for row in
        db.query(PayslipItem.employee_id).filter(PayslipItem.payroll_run_id == run.id).all()
    }

    # Batch-fetch every remaining employee's attendance rows for the run's
    # period in ONE query instead of 2 queries per employee (unpaid-leave
    # count + rewards/bonus sum) — a 200-employee run previously issued 400
    # extra round trips here, all synchronously inside the create-run request.
    pending_employee_ids = [e.id for e in employees if e.id not in existing_ids]
    attendance_by_employee: dict = {}
    if pending_employee_ids and run.period_start and run.period_end and run.period_end >= run.period_start:
        all_records = db.query(PayrollAttendanceRecord).filter(
            PayrollAttendanceRecord.organization_id == run.organization_id,
            PayrollAttendanceRecord.employee_id.in_(pending_employee_ids),
            PayrollAttendanceRecord.date >= run.period_start,
            PayrollAttendanceRecord.date <= run.period_end,
        ).all()
        for rec in all_records:
            attendance_by_employee.setdefault(rec.employee_id, []).append(rec)

    # Pre-generate unique payslip numbers for this batch to avoid duplicate key
    # violations within the same uncommitted transaction (DB count can't see
    # unflushed rows, so calling generate_business_code once per employee
    # would return the same number for everyone). Called once up front instead,
    # and its own sequence digits are reused as the starting point below —
    # NOT discarded — otherwise every batch would restart at 00001 and collide
    # with any other run's payslips generated in the same calendar month.
    base_payslip_code = ""
    seq = 1
    if run.organization_id:
        from app.core.code_generation import generate_business_code
        full_code = generate_business_code(
            db, run.organization_id, "PSL", PayslipItem, "payslip_number", "%Y%m", 5,
        )
        if len(full_code) > 5:
            base_payslip_code = full_code[:-5]
            seq = int(full_code[-5:])
        else:
            base_payslip_code = full_code
    # Cache rate_map/slabs by resolved (country, state, tax_regime) so
    # employees who share a jurisdiction (the common case) don't each
    # re-query/re-resolve — only distinct jurisdictions actually present in
    # this batch pay that cost.
    calc_cache: dict = {}
    for emp in employees:
        if emp.id in existing_ids:
            continue
        country, rate_map, slabs, resolved_pack, _state, state_rate_map, state_slabs, employer_tax_profiles, reciprocity, locality_rate = _resolve_employee_calc_inputs(
            db, organization_id, emp, cache=calc_cache,
            payroll_date=run.pay_date, org_opted_in=org_opted_in,
        )
        payslip_number = f"{base_payslip_code}{seq:05d}" if base_payslip_code else None
        _generate_single_payslip(
            db, run, emp, rate_map, slabs, country, calculation_mode, payslip_number=payslip_number,
            attendance_records=attendance_by_employee.get(emp.id, []),
            allowance_components=allowance_components, resolved_pack=resolved_pack,
            state_rate_map=state_rate_map, state_slabs=state_slabs, employer_tax_profiles=employer_tax_profiles,
            reciprocity=reciprocity, locality_rate=locality_rate,
        )
        seq += 1

    db.commit()
    return _recompute_run_aggregates(db, run)


def regenerate_employee_payslip(db: Session, run_id: int, employee_id: int, organization_id: int,
                                 actor_id: int = None) -> PayrollRun:
    """Recalculate a single employee's payslip within an existing run —
    e.g. after correcting their bank details — without touching anyone
    else's payslip in that run. Only allowed while the run is still
    editable (Draft/Review), matching the lock already enforced when
    extending a run with new employees (create_payroll_run) and when
    deleting a payslip (delete_payslip)."""
    run_query = db.query(PayrollRun).filter(PayrollRun.id == run_id)
    run_query = _apply_org_filter(run_query, PayrollRun, organization_id)
    run = run_query.first()
    if not run:
        raise NotFoundException(f"Payroll run {run_id} not found.")
    if run.status not in (PayrollStatus.DRAFT, PayrollStatus.REVIEW):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="This payroll run has moved past Review and is locked. Reopen it before recalculating an employee's payslip.",
        )

    employee = get_employee_by_id(db, employee_id, organization_id)

    existing_item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id,
        PayslipItem.employee_id == employee.id,
    ).first()
    if not existing_item:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="This employee doesn't have a payslip in this run yet — add them to the run instead of recalculating.",
        )

    calculation_mode = _resolve_run_calc_inputs(db, run, organization_id)
    org_opted_in = _org_uses_canonical_tax_pack(db, organization_id)
    country, rate_map, slabs, resolved_pack, _state, state_rate_map, state_slabs, employer_tax_profiles, reciprocity, locality_rate = _resolve_employee_calc_inputs(
        db, organization_id, employee, payroll_date=run.pay_date, org_opted_in=org_opted_in,
    )
    allowance_components = _resolve_allowance_components(db, organization_id)
    values = _compute_payslip_values(
        db, run, employee, rate_map, slabs, country, calculation_mode,
        allowance_components=allowance_components, resolved_pack=resolved_pack,
        state_rate_map=state_rate_map, state_slabs=state_slabs, employer_tax_profiles=employer_tax_profiles,
        reciprocity=reciprocity, locality_rate=locality_rate,
    )
    for field, value in values.items():
        setattr(existing_item, field, value)
    existing_item.status = PayslipStatus.PENDING
    db.commit()
    run = _recompute_run_aggregates(db, run)

    log_activity(
        db, organization_id,
        f"Recalculated payslip for '{employee.name}' in run '{run.period_label}'.",
        ActivityStatus.INFO, actor_id=actor_id,
    )
    return run


# ── Employees ────────────────────────────────────────────────────────────
# PayrollEmployee is owned entirely by payroll — organization_id is required
# (not optional) since every payroll employee must belong to a tenant.

# Shared "visible employee" filter — single source of truth for which
# payroll employees are considered visible/active in every screen.
# Currently scoped to organization_id (no employees hidden by status),
# but adding an exclusion here (e.g. filtering out Inactive) will apply
# uniformly across the Employees list, Attendance, and Leave Management.
def _apply_employee_filter(query, organization_id):
    return query.filter(PayrollEmployee.organization_id == organization_id)


def get_employees(db: Session, organization_id: int,
                   search: str = None, department: str = None, status: str = None,
                   limit: int = None, offset: int = None) -> List[PayrollEmployee]:
    query = _apply_employee_filter(db.query(PayrollEmployee), organization_id)
    if department:
        query = query.filter(PayrollEmployee.department == department)
    if status:
        query = query.filter(PayrollEmployee.status == status)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (PayrollEmployee.name.ilike(like)) |
            (PayrollEmployee.employee_code.ilike(like))
        )
    query = query.order_by(PayrollEmployee.name)
    # limit/offset are optional — omitting them preserves the exact prior
    # "return everything" behavior for existing callers; pass them to bound
    # the result set for orgs with very large employee counts.
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    return query.all()


def get_employee_by_id(db: Session, employee_id: int, organization_id: int) -> PayrollEmployee:
    employee = db.query(PayrollEmployee).filter(
        PayrollEmployee.id == employee_id,
        PayrollEmployee.organization_id == organization_id,
    ).first()
    if not employee:
        raise NotFoundException(f"Employee {employee_id} not found.")
    return employee


from app.modules.payroll.hardcoded_defaults import _DEFAULT_BASIC_PCT, _DEFAULT_HRA_PCT  # noqa: E402


def _resolve_salary_split_pct(db: Session, organization_id: Optional[int]) -> tuple:
    """Basic/HRA-as-percentage-of-CTC. This is an organizational
    compensation-structure choice (not a tax law figure), so it lives on
    the org's own PayrollPolicy (basic_pct/hra_pct — Super Admin can set a
    default and lock it via policy_defaults, same mechanism as
    calculation_mode; the org can override when allowed). Falls back to
    the platform default 50%/40% split (Special Allowance remainder: 10%) if no
    policy exists yet or organization_id is unavailable — every org with its
    own PayrollPolicy basic_pct/hra_pct is unaffected by this constant either way."""
    if not organization_id:
        return _DEFAULT_BASIC_PCT, _DEFAULT_HRA_PCT
    try:
        from app.modules.payroll.policy.service import get_active_policy
        policy = get_active_policy(db, organization_id)
        basic_pct = policy.basic_pct if policy.basic_pct is not None else _DEFAULT_BASIC_PCT
        hra_pct = policy.hra_pct if policy.hra_pct is not None else _DEFAULT_HRA_PCT
        return basic_pct, hra_pct
    except Exception:
        return _DEFAULT_BASIC_PCT, _DEFAULT_HRA_PCT


def _resolve_allowance_components(db: Session, organization_id: Optional[int]) -> list:
    """The org's Super-Admin-defined named allowance components (Transport,
    Medical, Other, or any custom slug — see PolicyAllowanceComponent),
    each computed as a percentage of monthly gross or a flat monthly
    amount. Returns [] for any org with no policy/components configured —
    Special Allowance then stays the exact same plain remainder it always
    was, zero behavior change until an org actually adds one."""
    if not organization_id:
        return []
    try:
        from app.modules.payroll.policy.service import get_active_policy
        policy = get_active_policy(db, organization_id)
        return [
            {"key": c.key, "label": c.label, "pct": c.pct, "flat_amount": c.flat_amount}
            for c in (policy.allowance_components or [])
        ]
    except Exception:
        return []


def _compute_allowance_components(components: list, monthly_gross: Decimal) -> tuple:
    """Given the org's configured components and this employee's monthly
    gross, returns (list of {key,label,amount} dicts, total amount) — the
    total is what gets subtracted from gross before Special Allowance takes
    the remainder."""
    items = []
    total = Decimal("0")
    for c in components:
        if c.get("pct") is not None:
            amount = _round2(monthly_gross * Decimal(str(c["pct"])) / 100)
        elif c.get("flat_amount") is not None:
            amount = _round2(Decimal(str(c["flat_amount"])))
        else:
            continue
        items.append({"key": c["key"], "label": c["label"], "amount": amount})
        total += amount
    return items, total


def _default_basic_hra_from_ctc(ctc, db: Session = None, organization_id: Optional[int] = None) -> tuple:
    """Basic/HRA split applied when an employee is created without them —
    computed once here so the employee's own Basic/HRA columns carry a
    real number instead of staying blank."""
    ctc_val = Decimal(str(ctc or 0))
    basic_pct, hra_pct = _resolve_salary_split_pct(db, organization_id) if db else (_DEFAULT_BASIC_PCT, _DEFAULT_HRA_PCT)
    return _round2(ctc_val * basic_pct / 100), _round2(ctc_val * hra_pct / 100)


def _fill_missing_basic_hra(fields: dict, db: Session = None, organization_id: Optional[int] = None) -> None:
    """Mutates `fields` in place, filling only whichever of basic/hra is
    actually missing — a value the caller did provide is never overwritten."""
    if fields.get("basic") is None or fields.get("hra") is None:
        default_basic, default_hra = _default_basic_hra_from_ctc(fields.get("ctc"), db, organization_id)
        if fields.get("basic") is None:
            fields["basic"] = default_basic
        if fields.get("hra") is None:
            fields["hra"] = default_hra


def _resolve_employee_country(db: Session, organization_id: int, explicit_country_code: Optional[str]) -> str:
    """Per-employee jurisdiction override if given, else the org's default —
    same fallback pattern _resolve_employee_calc_inputs uses for payroll
    calculation's country resolution."""
    if explicit_country_code:
        return _normalize_country(explicit_country_code)
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first()
    return _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")


def check_duplicate_employee_identifiers(
    db: Session, organization_id: int, email: Optional[str], country_code: str,
    pan: Optional[str], compliance_fields: dict, exclude_employee_id: int = None,
) -> None:
    """Cross-employee duplicate check within the org — email always, plus
    whichever single identifier is that jurisdiction's dedup key (PAN for
    India's dedicated column, or the compliance_fields key named by each
    Strategy's `duplicate_field` for the other five countries).

    Pushes the match into the SQL WHERE clause (via the `->>` JSON operator
    for compliance_fields) instead of loading every employee in the org —
    this runs on every single employee create/update, so a full-table load
    here scaled linearly with org size on every write."""
    email_norm = (email or "").strip().lower()
    pan_norm = (pan or "").strip().upper()
    strategy = get_employee_validation_strategy(country_code)
    dup_id = strategy.get_duplicate_identifier(compliance_fields)

    if not email_norm and not pan_norm and not dup_id:
        return

    conditions = []
    if email_norm:
        conditions.append(sa_func.lower(sa_func.trim(PayrollEmployee.email)) == email_norm)
    if pan_norm:
        conditions.append(sa_func.upper(sa_func.trim(PayrollEmployee.pan)) == pan_norm)
    if dup_id:
        field, value = dup_id
        conditions.append(PayrollEmployee.compliance_fields.op("->>")(field) == value)

    query = db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == organization_id, or_(*conditions),
    )
    if exclude_employee_id:
        query = query.filter(PayrollEmployee.id != exclude_employee_id)

    for existing in query.all():
        if email_norm and (existing.email or "").strip().lower() == email_norm:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                detail=f"An employee with email '{email}' already exists in this organization.",
            )
        if pan_norm and (existing.pan or "").strip().upper() == pan_norm:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                detail=f"An employee with PAN '{pan_norm}' already exists in this organization.",
            )
        if dup_id:
            field, value = dup_id
            if (existing.compliance_fields or {}).get(field) == value:
                raise HTTPException(
                    http_status.HTTP_409_CONFLICT,
                    detail=f"An employee with {field.upper()} '{value}' already exists in this organization.",
                )


def create_employee(db: Session, data: EmployeeCreate, organization_id: int) -> PayrollEmployee:
    employee_data = data.model_dump()

    country_code = _resolve_employee_country(db, organization_id, employee_data.get("country_code"))
    employee_data["country_code"] = country_code
    _fill_missing_basic_hra(employee_data, db, organization_id)
    strategy = get_employee_validation_strategy(country_code)
    employee_data["compliance_fields"] = strategy.validate(employee_data.get("compliance_fields") or {})
    employee_data.update(strategy.sync_to_columns(employee_data["compliance_fields"]))

    check_duplicate_employee_identifiers(
        db, organization_id, employee_data.get("email"), country_code,
        employee_data.get("pan"), employee_data["compliance_fields"],
    )

    if not employee_data.get("employee_code"):
        from app.core.code_generation import generate_employee_code
        employee_data["employee_code"] = generate_employee_code(db, organization_id=organization_id)
    existing = db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == organization_id,
        PayrollEmployee.employee_code == employee_data["employee_code"],
    ).first()
    if existing:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            detail=f"Employee code '{employee_data['employee_code']}' already exists in this organization.",
        )

    employee = PayrollEmployee(organization_id=organization_id, **employee_data)
    db.add(employee)
    db.commit()
    db.refresh(employee)

    try:
        log_activity(db, organization_id, f"Employee '{employee.name}' added.",
                     ActivityStatus.INFO)
    except Exception:
        pass

    return employee


def update_employee(db: Session, employee_id: int, data: EmployeeUpdate, organization_id: int) -> PayrollEmployee:
    employee = get_employee_by_id(db, employee_id, organization_id)
    updates = data.model_dump(exclude_unset=True)

    country_code = _resolve_employee_country(
        db, organization_id, updates.get("country_code", employee.country_code)
    )
    if "compliance_fields" in updates or "country_code" in updates:
        strategy = get_employee_validation_strategy(country_code)
        merged_compliance = {**(employee.compliance_fields or {}), **(updates.get("compliance_fields") or {})}
        updates["compliance_fields"] = strategy.validate(merged_compliance)
        updates["country_code"] = country_code
        updates.update(strategy.sync_to_columns(updates["compliance_fields"]))

    check_duplicate_employee_identifiers(
        db, organization_id,
        updates.get("email", employee.email), country_code,
        updates.get("pan", employee.pan), updates.get("compliance_fields", employee.compliance_fields or {}),
        exclude_employee_id=employee.id,
    )

    for field, value in updates.items():
        if value == "":
            continue
        setattr(employee, field, value)
    db.commit()
    db.refresh(employee)
    return employee


FIELD_MAP = {
    "name": "name",
    "email": "email",
    "phone": "phone",
    "department": "department",
    "designation": "designation",
    "employmentType": "employment_type",
    "status": "status",
    "dateOfJoining": "date_of_joining",
    "ctc": "ctc",
    "basic": "basic",
    "hra": "hra",
    "bankName": "bank_name",
    "bankAccountNumber": "bank_account",
    "panNumber": "pan",
    "uan": "uan",
    "ifscCode": "ifsc",
    "countryCode": "country_code",
}


def _next_employee_start_num(db: Session, organization_id: int) -> int:
    return db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == organization_id
    ).count() + 1


def _map_employee_row(row: BulkEmployeeItem) -> dict:
    mapped = {}
    for camel_field, snake_field in FIELD_MAP.items():
        value = getattr(row, camel_field, None)
        if value is not None:
            if camel_field == "dateOfJoining":
                try:
                    from datetime import date
                    mapped[snake_field] = date.fromisoformat(str(value))
                except (ValueError, TypeError):
                    mapped[snake_field] = None
            else:
                mapped[snake_field] = value
    return mapped


def bulk_create_employees(db: Session, data: BulkEmployeeRequest, organization_id: int) -> dict:
    from app.core.code_generation import generate_employee_code

    created_employees = []
    failed = []

    # Pre-generate employee codes for this whole batch — mirrors
    # generate_payslips_for_run's "call the code generator once up front,
    # then increment its own sequence digits in memory" pattern. Calling
    # generate_employee_code per row did 4 DB round-trips (an advisory
    # lock + an org lookup + two COUNT queries) for every single employee,
    # which dominates bulk-import time on large sheets, and it would have
    # returned the *same* code for every row anyway (its COUNT queries
    # can't see this batch's own unflushed inserts within the same
    # transaction) had rows not already failed loudly on the resulting
    # unique-constraint violation.
    first_code = generate_employee_code(db, organization_id=organization_id)
    seq_match = re.search(r"(\d+)$", first_code)
    if seq_match:
        code_prefix = first_code[: -len(seq_match.group(1))]
        seq_width = len(seq_match.group(1))
        next_seq = int(seq_match.group(1))
    else:
        code_prefix, seq_width, next_seq = first_code, 0, None

    for row in data.employees:
        if not row.name or not row.email:
            failed.append({
                "row": {"email": row.email, "name": row.name},
                "reason": "Employee name and email are required.",
            })
            continue

        mapped = _map_employee_row(row)

        # Same jurisdiction resolution/validation/duplicate-check the
        # single-employee create_employee() runs — previously this bulk
        # path skipped it entirely, so every bulk-imported employee landed
        # as implicitly India-only regardless of what the sheet said.
        country_code = _resolve_employee_country(db, organization_id, mapped.get("country_code"))
        mapped["country_code"] = country_code
        _fill_missing_basic_hra(mapped, db, organization_id)
        try:
            strategy = get_employee_validation_strategy(country_code)
            mapped["compliance_fields"] = strategy.validate(row.complianceFields or {})
            mapped.update(strategy.sync_to_columns(mapped["compliance_fields"]))
            check_duplicate_employee_identifiers(
                db, organization_id, mapped.get("email"), country_code,
                mapped.get("pan"), mapped["compliance_fields"],
            )
        except Exception as exc:
            failed.append({
                "row": {"email": row.email, "name": row.name},
                "reason": getattr(exc, "detail", None) or str(exc),
            })
            continue

        if next_seq is not None:
            mapped["employee_code"] = f"{code_prefix}{next_seq:0{seq_width}d}"
            next_seq += 1
        else:
            mapped["employee_code"] = first_code
        mapped["organization_id"] = organization_id

        # A savepoint per row (not a full db.rollback()) so one bad row
        # only undoes its own flush — previously a single failure rolled
        # back the *entire* session (discarding every already-flushed
        # employee earlier in this same batch) and then aborted the whole
        # import immediately, silently dropping the rest of the sheet.
        try:
            with db.begin_nested():
                employee = PayrollEmployee(**mapped)
                db.add(employee)
                db.flush()
            created_employees.append(employee)
        except Exception as exc:
            failed.append({
                "row": {"email": row.email, "name": row.name},
                "reason": str(exc),
            })

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        return {"created": 0, "employees": [], "failed": [{"row": {}, "reason": str(exc)}]}

    for emp in created_employees:
        db.refresh(emp)

    # Use a dedicated session for activity logging so a log failure
    # cannot rollback/expire the employee objects in the main session.
    log_db = None
    try:
        from app.database import SessionLocal as _LogSession
        log_db = _LogSession()
        log_activity(log_db, organization_id,
                     f"Bulk created {len(created_employees)} employees.",
                     ActivityStatus.INFO)
    except Exception:
        if log_db:
            log_db.rollback()
    finally:
        if log_db:
            log_db.close()

    return {"created": len(created_employees), "employees": created_employees, "failed": failed}


def bulk_update_employees(db: Session, data: BulkEmployeeRequest, organization_id: int) -> dict:
    """Partial bulk update, keyed by `id`. Reuses the same FIELD_MAP/
    _map_employee_row mapping bulk_create_employees uses — only the write
    path differs (lookup + setattr, mirroring the single-employee
    update_employee, instead of insert)."""
    updated_employees = []
    failed = []

    # One IN(...) lookup for the whole batch instead of one SELECT per row —
    # the per-row round trip was the dominant cost on large bulk-update
    # sheets, same class of fix as bulk_create_employees's code
    # pre-generation.
    requested_ids = [row.id for row in data.employees if row.id]
    employees_by_id = {}
    if requested_ids:
        existing = db.query(PayrollEmployee).filter(
            PayrollEmployee.id.in_(requested_ids),
            PayrollEmployee.organization_id == organization_id,
        ).all()
        employees_by_id = {emp.id: emp for emp in existing}

    for row in data.employees:
        if not row.id:
            failed.append({"row": {"id": row.id, "name": row.name}, "reason": "No employee ID provided — cannot update."})
            continue

        employee = employees_by_id.get(row.id)
        if not employee:
            failed.append({"row": {"id": row.id, "name": row.name}, "reason": f"No employee found with ID {row.id} in this organization."})
            continue

        mapped = _map_employee_row(row)

        # Same jurisdiction resolution/validation/duplicate-check
        # update_employee() runs — only when this row actually touches
        # country/compliance data, mirroring update_employee's own
        # exclude_unset-style "only revalidate what changed" behavior.
        try:
            if "country_code" in mapped or row.complianceFields is not None:
                country_code = _resolve_employee_country(
                    db, organization_id, mapped.get("country_code", employee.country_code)
                )
                strategy = get_employee_validation_strategy(country_code)
                merged_compliance = {**(employee.compliance_fields or {}), **(row.complianceFields or {})}
                mapped["compliance_fields"] = strategy.validate(merged_compliance)
                mapped["country_code"] = country_code
                mapped.update(strategy.sync_to_columns(mapped["compliance_fields"]))
            check_duplicate_employee_identifiers(
                db, organization_id,
                mapped.get("email", employee.email),
                mapped.get("country_code", employee.country_code),
                mapped.get("pan", employee.pan),
                mapped.get("compliance_fields", employee.compliance_fields or {}),
                exclude_employee_id=employee.id,
            )
        except Exception as exc:
            failed.append({
                "row": {"id": row.id, "name": row.name},
                "reason": getattr(exc, "detail", None) or str(exc),
            })
            continue

        try:
            with db.begin_nested():
                for column, value in mapped.items():
                    if value == "":
                        continue
                    setattr(employee, column, value)
                db.flush()
            updated_employees.append(employee)
        except Exception as exc:
            failed.append({"row": {"id": row.id, "name": row.name}, "reason": str(exc)})

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        return {"updated": 0, "employees": [], "failed": failed + [{"row": {}, "reason": str(exc)}]}

    for emp in updated_employees:
        db.refresh(emp)

    log_db = None
    try:
        from app.database import SessionLocal as _LogSession
        log_db = _LogSession()
        log_activity(log_db, organization_id,
                     f"Bulk updated {len(updated_employees)} employees.",
                     ActivityStatus.INFO)
    except Exception:
        if log_db:
            log_db.rollback()
    finally:
        if log_db:
            log_db.close()

    return {"updated": len(updated_employees), "employees": updated_employees, "failed": failed}


def delete_employee(db: Session, employee_id: int, organization_id: int):
    employee = get_employee_by_id(db, employee_id, organization_id)
    has_payslips = db.query(PayslipItem.id).filter(PayslipItem.employee_id == employee_id).first()
    if has_payslips:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            detail="Cannot delete an employee who already has payslip history. Set status to Inactive instead.",
        )
    # Clear FK-dependent records before deleting the employee.
    # flush() ensures these DELETE statements hit the DB before the
    # employee DELETE runs at commit time, avoiding FK violations.
    db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.employee_id == employee_id,
    ).delete(synchronize_session=False)
    db.query(PayrollLeaveAllocation).filter(
        PayrollLeaveAllocation.employee_id == employee_id,
    ).delete(synchronize_session=False)
    db.query(PayrollLeaveRequest).filter(
        PayrollLeaveRequest.employee_id == employee_id,
    ).delete(synchronize_session=False)
    db.flush()
    db.delete(employee)
    db.commit()


def bulk_delete_employees(db: Session, data: BulkDeleteRequest, organization_id: int) -> dict:
    deleted = []
    failed = []

    for emp_id in data.employee_ids:
        try:
            employee = get_employee_by_id(db, emp_id, organization_id)
            has_payslips = db.query(PayslipItem.id).filter(PayslipItem.employee_id == emp_id).first()
            if has_payslips:
                failed.append({"id": emp_id, "reason": "Has payslip history — set status to Inactive instead."})
                continue

            # Clear FK-dependent records before deleting the employee.
            # flush() ensures these DELETE statements hit the DB before the
            # per-employee DELETE runs at commit time, avoiding FK violations.
            db.query(PayrollAttendanceRecord).filter(
                PayrollAttendanceRecord.employee_id == emp_id,
            ).delete(synchronize_session=False)
            db.query(PayrollLeaveAllocation).filter(
                PayrollLeaveAllocation.employee_id == emp_id,
            ).delete(synchronize_session=False)
            db.query(PayrollLeaveRequest).filter(
                PayrollLeaveRequest.employee_id == emp_id,
            ).delete(synchronize_session=False)
            db.flush()

            db.delete(employee)
            deleted.append(emp_id)
        except NotFoundException:
            failed.append({"id": emp_id, "reason": "Not found."})

    if deleted:
        db.commit()

    if deleted:
        try:
            log_activity(db, organization_id, f"Bulk deleted {len(deleted)} employees.",
                         ActivityStatus.INFO)
        except Exception:
            pass

    return {"deleted": deleted, "failed": failed}


# ── Payroll Runs ────────────────────────────────────────────────────────

def create_payroll_run(db: Session, created_by: int, data: PayrollRunCreate, organization_id: int = None) -> PayrollRun:
    # Resolve and store the calculation mode on the run for auditing
    calculation_mode = _resolve_calculation_mode(db, organization_id, data.calculation_mode)

    # Resolve which employees this request actually targets — an explicit
    # subset (single/selected employee run), or every active employee when
    # none is given ("all employees").
    if data.employeeIds:
        target_employee_ids = set(data.employeeIds)
    else:
        target_employee_ids = {
            row.id for row in db.query(PayrollEmployee.id).filter(
                PayrollEmployee.organization_id == organization_id,
                PayrollEmployee.status == EmployeeStatus.ACTIVE,
            ).all()
        }

    # ── Existing-run guard: only one PayrollRun per org+period. If one
    # already exists, extend it with whichever requested employees aren't
    # already in it (covers running payroll for one employee today and a
    # different employee in the same period later), rather than blocking
    # outright — that only happens when every requested employee is already
    # covered, which is a genuine duplicate request. ──
    duplicate_query = db.query(PayrollRun).filter(
        PayrollRun.period_start <= data.period_end,
        PayrollRun.period_end >= data.period_start,
    )
    duplicate_query = _apply_org_filter(duplicate_query, PayrollRun, organization_id)
    existing_run = duplicate_query.first()

    if existing_run is not None:
        covered_ids = {
            row.employee_id for row in db.query(PayslipItem.employee_id).filter(
                PayslipItem.payroll_run_id == existing_run.id,
            ).all()
        }
        new_employee_ids = target_employee_ids - covered_ids
        # Once a run has moved past Review (Approved/Authorized/Paid/Closed),
        # treat it as locked — don't silently add payslips into an
        # already-approved run. Direct the user to the existing run instead.
        is_editable = existing_run.status in (PayrollStatus.DRAFT, PayrollStatus.REVIEW)
        if not new_employee_ids or not data.auto_generate_payslips or not is_editable:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Payroll Run for this payroll period already exists. See run '{existing_run.period_label}' (ID {existing_run.id}).",
            )

        att_count = db.query(PayrollAttendanceRecord).filter(
            PayrollAttendanceRecord.organization_id == organization_id,
            PayrollAttendanceRecord.employee_id.in_(new_employee_ids),
            PayrollAttendanceRecord.date >= data.period_start,
            PayrollAttendanceRecord.date <= data.period_end,
        ).count()
        if att_count == 0:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="No attendance records found for the selected period and employees. Please record attendance before creating a payroll run.",
            )

        run = generate_payslips_for_run(db, existing_run, organization_id, employee_ids=list(new_employee_ids))
        log_activity(
            db, organization_id,
            f"Added {len(new_employee_ids)} employee(s) to existing payroll run '{run.period_label}'.",
            ActivityStatus.INFO, actor_id=created_by,
        )
        return run

    # ── No run exists for this period yet — create a fresh one ──
    if data.employeeIds:
        att_count = db.query(PayrollAttendanceRecord).filter(
            PayrollAttendanceRecord.organization_id == organization_id,
            PayrollAttendanceRecord.employee_id.in_(data.employeeIds),
            PayrollAttendanceRecord.date >= data.period_start,
            PayrollAttendanceRecord.date <= data.period_end,
        ).count()
        if att_count == 0:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="No attendance records found for the selected period and employees. Please record attendance before creating a payroll run.",
            )

    payload = data.model_dump(exclude={"auto_generate_payslips", "schedule", "employeeIds", "totals", "calculation_mode"})
    run = PayrollRun(created_by=created_by, calculation_mode=calculation_mode, **payload)
    if organization_id is not None:
        run.organization_id = organization_id
        from app.core.code_generation import generate_business_code
        run.run_code = generate_business_code(db, organization_id, "PY", PayrollRun, "run_code", "%Y%m")
    db.add(run)
    db.commit()
    db.refresh(run)

    if data.auto_generate_payslips:
        run = generate_payslips_for_run(db, run, organization_id, employee_ids=data.employeeIds)

    log_activity(db, organization_id, f"Payroll run '{run.period_label}' created.",
                 ActivityStatus.INFO, actor_id=created_by)
    return run


def get_payroll_runs(db: Session, organization_id: int = None, year: int = None, month: int = None,
                      limit: int = None, offset: int = None) -> List[PayrollRun]:
    query = db.query(PayrollRun).order_by(PayrollRun.period_start.desc())
    query = _apply_org_filter(query, PayrollRun, organization_id)
    if year and month:
        from datetime import date as _date
        month_start = _date(year, month, 1)
        if month == 12:
            month_end = _date(year + 1, 1, 1)
        else:
            month_end = _date(year, month + 1, 1)
        query = query.filter(PayrollRun.period_start >= month_start, PayrollRun.period_start < month_end)
    elif year:
        from datetime import date as _date
        year_start = _date(year, 1, 1)
        year_end = _date(year + 1, 1, 1)
        query = query.filter(PayrollRun.period_start >= year_start, PayrollRun.period_start < year_end)
    # limit/offset optional — unset preserves current "return everything"
    # behavior; bounds the result set for orgs with long payroll history.
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    return query.all()


def get_payroll_run_by_id(db: Session, run_id: int, organization_id: int = None) -> PayrollRun:
    query = db.query(PayrollRun).filter(PayrollRun.id == run_id)
    query = _apply_org_filter(query, PayrollRun, organization_id)
    run = query.first()
    if not run:
        raise NotFoundException(f"Payroll run {run_id} not found.")
    return run


def _resolve_user_name(db: Session, user_id: Optional[int]) -> Optional[str]:
    """Resolve a created_by/approved_by id to a display name.

    These FKs reference the app-wide `employees` table (the logged-in user),
    not payroll's own PayrollEmployee master data — see models.py note.
    """
    if not user_id:
        return None
    from app.modules.auth.models import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    return f"{user.first_name} {user.last_name}".strip()


def get_payroll_run_detail(db: Session, run_id: int, organization_id: int = None) -> PayrollRun:
    """Same as get_payroll_run_by_id, enriched with resolved creator/approver
    names for the Run Details view. Kept separate from get_payroll_run_by_id
    so every other caller of that function isn't paying for the extra lookups."""
    run = get_payroll_run_by_id(db, run_id, organization_id)
    run.created_by_name = _resolve_user_name(db, run.created_by)
    run.approved_by_name = _resolve_user_name(db, run.approved_by)
    run.authorized_by_name = _resolve_user_name(db, run.authorized_by)
    run.paid_by_name = _resolve_user_name(db, run.paid_by)
    return run


def update_payroll_run(db: Session, run_id: int, data: PayrollRunUpdate, organization_id: int = None) -> PayrollRun:
    run = get_payroll_run_by_id(db, run_id, organization_id)
    if run.status in (PayrollStatus.PAID, PayrollStatus.CLOSED):
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"Cannot edit a run that is already {run.status.value}.")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(run, field, value)
    db.commit()
    db.refresh(run)
    return run


# ── Payroll email notifications ─────────────────────────────────────────
# Best-effort only: a failed/slow email must never block a real payroll
# action (approval, payment), so every call here is isolated in its own
# try/except and logged, not raised. Gated per-org by is_notification_enabled
# so an admin can opt out (mail/service.py, PayrollEmailSettings).

def _notify_payroll_run_approved(db: Session, run: "PayrollRun", organization_id: int) -> None:
    import logging
    logger = logging.getLogger("zoiko")
    try:
        from app.modules.payroll.mail.service import is_notification_enabled
        if organization_id and not is_notification_enabled(db, organization_id, "run_approved"):
            return
        from app.services.email_service import send_payroll_run_approved_email

        items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
        # Batch the employee lookup instead of one query per payslip item —
        # avoids an N+1 (e.g. 200 queries for a 200-employee run).
        employee_ids = {item.employee_id for item in items}
        employees_by_id = {
            e.id: e for e in db.query(PayrollEmployee).filter(PayrollEmployee.id.in_(employee_ids)).all()
        } if employee_ids else {}
        for item in items:
            employee = employees_by_id.get(item.employee_id)
            if not employee or not employee.email:
                continue
            try:
                send_payroll_run_approved_email(
                    employee.email, item.employee_name or employee.name,
                    run.period_label, organization_id=organization_id, db=db,
                )
            except Exception as exc:
                logger.warning(f"[payroll-mail] run-approved email failed for employee {employee.id}: {exc}")
    except Exception as exc:
        logger.warning(f"[payroll-mail] run-approved notification pass failed for run {run.id}: {exc}")


def _notify_payslips_ready(db: Session, run: "PayrollRun", organization_id: int) -> None:
    import logging
    logger = logging.getLogger("zoiko")
    try:
        from app.modules.payroll.mail.service import is_notification_enabled
        if organization_id and not is_notification_enabled(db, organization_id, "payslip_ready"):
            return
        from app.services.email_service import send_payslip_ready_email

        items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
        # Batch the employee lookup instead of one query per payslip item —
        # avoids an N+1 (e.g. 200 queries for a 200-employee run).
        employee_ids = {item.employee_id for item in items}
        employees_by_id = {
            e.id: e for e in db.query(PayrollEmployee).filter(PayrollEmployee.id.in_(employee_ids)).all()
        } if employee_ids else {}
        for item in items:
            employee = employees_by_id.get(item.employee_id)
            if not employee or not employee.email:
                continue
            try:
                pdf_bytes = generate_payslip_pdf_bytes(db, item.id, organization_id)
            except Exception as exc:
                logger.warning(f"[payroll-mail] payslip PDF generation failed for payslip {item.id}: {exc}")
                pdf_bytes = None
            try:
                send_payslip_ready_email(
                    employee.email, item.employee_name or employee.name,
                    run.period_label, organization_id=organization_id, db=db,
                    pdf_bytes=pdf_bytes,
                    pdf_filename=f"{item.payslip_number or 'payslip'}.pdf" if pdf_bytes else None,
                )
            except Exception as exc:
                logger.warning(f"[payroll-mail] payslip-ready email failed for employee {employee.id}: {exc}")
    except Exception as exc:
        logger.warning(f"[payroll-mail] payslip-ready notification pass failed for run {run.id}: {exc}")


def _run_notifications_in_background(run_id: int, organization_id: int, kind: str) -> None:
    """Entry point for BackgroundTasks — runs AFTER the HTTP response is sent,
    so it needs its own DB session (the request's session is closed by then
    via get_db's `finally: db.close()`)."""
    import logging
    from app.database import SessionLocal
    logger = logging.getLogger("zoiko")
    db = SessionLocal()
    try:
        run = db.query(PayrollRun).filter(PayrollRun.id == run_id).first()
        if not run:
            return
        if kind == "approved":
            _notify_payroll_run_approved(db, run, organization_id)
        elif kind == "paid":
            _notify_payslips_ready(db, run, organization_id)
    except Exception as exc:
        logger.warning(f"[payroll-mail] background notification pass failed for run {run_id}: {exc}")
    finally:
        db.close()


def advance_payroll_run_status(
    db: Session, run_id: int, approver_id: int, organization_id: int = None,
    background_tasks: "BackgroundTasks" = None,
) -> PayrollRun:
    """Moves a run one step forward in its lifecycle
    (Draft → Review → Approved → Authorized → Paid → Closed).
    Backs the single "Approve" button in the UI.

    Notification emails (and, for the Paid transition, payslip PDF generation)
    are dispatched via `background_tasks` when the caller provides one, so the
    HTTP response doesn't wait on N blocking SMTP sends / PDF renders for an
    n-employee run. Falls back to running them inline if no background_tasks
    is passed (e.g. from a script or test)."""
    run = get_payroll_run_by_id(db, run_id, organization_id)
    current_idx = PAYROLL_STATUS_ORDER.index(run.status)
    if current_idx >= len(PAYROLL_STATUS_ORDER) - 1:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="This run has already reached its final status.")

    next_status = PAYROLL_STATUS_ORDER[current_idx + 1]
    run.status = next_status
    if next_status == PayrollStatus.APPROVED:
        run.approved_by = approver_id
        run.approved_at = datetime.utcnow()
    if next_status == PayrollStatus.AUTHORIZED:
        run.authorized_by = approver_id
        run.authorized_at = datetime.utcnow()
    if next_status == PayrollStatus.PAID:
        run.paid_by = approver_id
        run.processed_at = datetime.utcnow()
        db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).update(
            {PayslipItem.status: PayslipStatus.PAID, PayslipItem.paid_at: datetime.utcnow()}
        )
    db.commit()
    db.refresh(run)

    log_activity(db, organization_id, f"Payroll run '{run.period_label}' advanced to {next_status.value}.",
                 ActivityStatus.SUCCESS, actor_id=approver_id)

    notify_kind = "approved" if next_status == PayrollStatus.APPROVED else (
        "paid" if next_status == PayrollStatus.PAID else None
    )
    if notify_kind:
        if background_tasks is not None:
            background_tasks.add_task(_run_notifications_in_background, run.id, organization_id, notify_kind)
        elif notify_kind == "approved":
            _notify_payroll_run_approved(db, run, organization_id)
        else:
            _notify_payslips_ready(db, run, organization_id)

    return run


def delete_payroll_run(db: Session, run_id: int, organization_id: int = None):
    run = get_payroll_run_by_id(db, run_id, organization_id)
    if run.status != PayrollStatus.DRAFT:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="Only Draft runs can be deleted.")
    db.delete(run)
    db.commit()


def delete_payslip(db: Session, payslip_id: int, organization_id: int = None):
    query = db.query(PayslipItem)
    query = _apply_org_filter(query, PayslipItem, organization_id)
    query = query.filter(PayslipItem.id == payslip_id)
    item = query.first()
    if not item:
        raise NotFoundException(f"Payslip {payslip_id} not found.")
    run = db.query(PayrollRun).filter(PayrollRun.id == item.payroll_run_id).first()
    if run and run.status != PayrollStatus.DRAFT:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="Only payslips in Draft runs can be deleted.")
    db.delete(item)
    db.commit()


# ── Payslip Items ──────────────────────────────────────────────────────

def add_payslip_item(db: Session, run_id: int, data: PayslipItemCreate, organization_id: int = None) -> PayslipItem:
    run = get_payroll_run_by_id(db, run_id, organization_id)
    employee = db.query(PayrollEmployee).filter(
        PayrollEmployee.id == data.employee_id,
        PayrollEmployee.organization_id == organization_id,
    ).first()
    if not employee:
        raise NotFoundException(f"Employee {data.employee_id} not found.")

    # Employee's own jurisdiction overrides the org default — same
    # resolution generate_payslips_for_run/regenerate_employee_payslip
    # already use (_resolve_employee_country). Previously this looked only
    # at the org's compliance details, silently ignoring an employee's own
    # country_code override for manually-added payslips specifically.
    country = _resolve_employee_country(db, organization_id, getattr(employee, "country_code", None))

    # Same canonical-pack substitution generate_payslips_for_run uses (see
    # _resolve_effective_rate_inputs) — a manually-added payslip should be
    # governed by the same period-correct rates a normal run would use.
    org_opted_in = _org_uses_canonical_tax_pack(db, organization_id)
    work_state = getattr(employee, "work_state", None)
    resolution_state = _resolve_country_aware_state(country, employee, work_state, db=db, organization_id=organization_id)
    rate_map, slabs, canonical_rates, pack = _resolve_effective_rate_inputs(
        db, organization_id, country, run.pay_date, org_opted_in,
        state=resolution_state, tax_regime=getattr(employee, "tax_regime", None),
        filing_status=getattr(employee, "w4_filing_status", None),
    )
    # Region-specific rules (Scotland's own tax bands, India's state PT,
    # ...) — the SAME call generate_payslips_for_run's per-employee
    # compute already makes. Without this, a manually-added payslip for a
    # region-scoped employee could silently use national-only figures
    # while a real run for the same employee correctly used their
    # region's config.
    state_rate_map, state_slabs = get_state_scoped_config(db, country, resolution_state)
    jurisdiction_id = f"{country}-{resolution_state}" if (country in ("US", "CA") and resolution_state) else None
    employer_tax_profiles = get_employer_tax_profiles(db, organization_id, jurisdiction_id, as_of=run.pay_date)
    reciprocity = _resolve_us_reciprocity(db, employee, country, resolution_state, as_of=run.pay_date)
    locality_rate = (
        get_locality_rate(db, country, getattr(employee, "work_locality", None), as_of=run.pay_date)
        if country == "US" else None
    )

    calculation_mode = getattr(run, "calculation_mode", None) or _resolve_calculation_mode(db, organization_id)
    gross = data.basic_salary + (data.hra or 0) + (data.special_allowance or 0) + (data.overtime or 0)

    # Delegate to the strategy engine (no attendance data for manual payslips)
    from app.modules.payroll.engine.resolver import calculate_payroll, build_context_from_employee
    ctx = build_context_from_employee(
        employee, gross=gross, basic=data.basic_salary,
        hra=data.hra or Decimal("0"), special_allowance=data.special_allowance or Decimal("0"),
        overtime=data.overtime or Decimal("0"),
        unpaid_leave_days=0,
        country=country, rate_map=rate_map, slabs=slabs,
        work_state=work_state, state_rate_map=state_rate_map, state_slabs=state_slabs,
        employer_tax_profiles=employer_tax_profiles,
        locality_rate=locality_rate,
        **reciprocity,
    )
    calc = calculate_payroll(ctx, calculation_mode)

    employee_name = getattr(employee, "name", None) or ""
    if pack is not None:
        tax_snapshot = _pack_to_tax_snapshot(canonical_rates, slabs, pack)
    else:
        tax_snapshot = _resolve_tax_snapshot(db, country, run.pay_date)

    item = PayslipItem(
        payroll_run_id=run_id,
        employee_id=data.employee_id,
        organization_id=organization_id,
        employee_name=employee_name,
        department=getattr(employee, "department", None),
        designation=getattr(employee, "designation", None),
        date_of_joining=getattr(employee, "date_of_joining", None),
        bank_name=getattr(employee, "bank_name", None),
        bank_account=getattr(employee, "bank_account", None),
        pan=getattr(employee, "pan", None),
        uan=getattr(employee, "uan", None),
        ifsc=getattr(employee, "ifsc", None),
        country_code=country,
        compliance_fields=dict(getattr(employee, "compliance_fields", None) or {}),
        **tax_snapshot,
        basic_salary=calc.basic,
        hra=calc.hra,
        special_allowance=calc.special_allowance,
        overtime=calc.overtime,
        gross_pay=calc.gross,
        pf=calc.employee_pf,
        esi=calc.employee_esi,
        professional_tax=calc.professional_tax,
        social_security=calc.social_security,
        medicare=calc.medicare,
        ni_employee=calc.ni_employee,
        employee_pension=calc.employee_pension,
        tds=calc.tds,
        # US: broken-out federal/state/local tax — added alongside tds
        # above so a manually-added US payslip doesn't reintroduce the
        # same "totals right, detail columns silently zero" gap this field
        # split was specifically meant to close (see engine/countries/us.py).
        federal_income_tax=calc.federal_income_tax,
        state_income_tax=calc.state_income_tax,
        local_tax=calc.local_tax,
        state_disability_insurance=calc.state_disability_insurance,
        total_deductions=calc.total_deductions,
        employer_pf=calc.employer_pf,
        employer_esi=calc.employer_esi,
        employer_social_security=calc.employer_social_security,
        employer_medicare=calc.employer_medicare,
        employer_pension=calc.employer_pension,
        employer_sui=calc.employer_sui,
        net_pay=calc.net_pay,
        unpaid_leave_days=calc.unpaid_leave_days,
        attendance_deduction=calc.attendance_deduction,
        per_day_salary=calc.per_day_salary,
        payable_days=Decimal(calc.payable_days),
        total_working_days=Decimal(calc.payroll_days),
        status=PayslipStatus.PENDING,
        notes=data.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    _recompute_run_aggregates(db, run)
    return item


def get_payslips_for_run(db: Session, run_id: int, organization_id: int = None) -> List[PayslipItem]:
    get_payroll_run_by_id(db, run_id, organization_id)  # 404s if missing/not in org
    query = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run_id)
    return _apply_org_filter(query, PayslipItem, organization_id).all()


def get_run_leave_summary(db: Session, run_id: int, organization_id: int = None) -> dict:
    """Read-only Leave Summary for the Run Details view, per employee, for the
    run's pay period. Does NOT touch PayslipItem/payroll calculations — this
    is a supplementary query against attendance records only, because
    PayslipItem itself only tracks unpaid_leave_days (the one figure that
    actually affects pay), not a paid/sick/casual breakdown."""
    run = get_payroll_run_by_id(db, run_id, organization_id)
    items = get_payslips_for_run(db, run_id, organization_id)
    employee_ids = [item.employee_id for item in items]
    if not employee_ids:
        return {}

    query = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == organization_id,
        PayrollAttendanceRecord.employee_id.in_(employee_ids),
        PayrollAttendanceRecord.date >= run.period_start,
        PayrollAttendanceRecord.date <= run.period_end,
    )
    summary = {
        emp_id: {"present": 0, "absent": 0, "paidLeave": 0, "unpaidLeave": 0, "sickLeave": 0, "casualLeave": 0}
        for emp_id in employee_ids
    }
    for record in query.all():
        bucket = summary[record.employee_id]
        if record.status == "present":
            bucket["present"] += 1
        elif record.status == "absent":
            bucket["absent"] += 1
        elif record.status == "leave":
            leave_key = {
                "paid": "paidLeave", "unpaid": "unpaidLeave",
                "sick": "sickLeave", "casual": "casualLeave",
            }.get(record.leave_type, "unpaidLeave")
            bucket[leave_key] += 1
    return summary


# ── Bank Transfer File (post-approval) ──────────────────────────────────
# See app/modules/payroll/bank_export/ for the exporter implementations.
# This section only assembles rows from already-computed PayslipItem/
# PayrollRun data and hands them to an exporter — it never recomputes pay.

def get_bank_transfer_summary(db: Session, run_id: int, organization_id: int = None) -> dict:
    """Read-only preview shown in the Approval Dialog before a file is generated."""
    from app.modules.payroll.policy.service import get_active_policy

    run = get_payroll_run_by_id(db, run_id, organization_id)
    items = get_payslips_for_run(db, run_id, organization_id)
    policy = get_active_policy(db, organization_id)
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first()

    return {
        "runId": run.id,
        "period": run.period_label,
        "totalEmployees": len(items),
        "grossPayroll": float(run.total_gross or 0),
        # run.total_deductions already includes tds (run.total_taxes is the
        # same tds amount, kept separately only for the "Total Taxes" stat) —
        # adding both here double-counted tds and made Gross − Deductions
        # come out short of the (correct) Net Payroll shown below.
        "totalDeductions": float(run.total_deductions or 0),
        "netPayroll": float(run.total_net or 0),
        "paymentDate": run.pay_date,
        "bankFormat": policy.bank_export_format,
        "companyName": getattr(company, "name", None) or "",
    }


def _build_bank_export_rows(run: PayrollRun, items: List[PayslipItem], company, org_currency: str = None) -> list:
    from app.modules.payroll.bank_export import BankExportRow

    # Use the org's explicit currency override if set, otherwise derive
    # from the jurisdiction — implements the Super Admin → Org Admin
    # inheritance model for currency.
    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    currency_code = org_currency or _get_currency_code(country)
    company_name = getattr(company, "name", None) or ""

    rows = []
    for item in items:
        rows.append(BankExportRow(
            employee_name=item.employee_name,
            employee_id=str(item.employee_id),
            bank_name=item.bank_name or "",
            account_number=item.bank_account or "",
            ifsc=item.ifsc or "",
            branch=None,   # not captured anywhere upstream — left blank rather than fabricated
            amount=float(item.net_pay or 0),
            reference_number=item.payslip_number or f"RUN{run.id}-{item.employee_id}",
            narration=f"Salary {run.period_label}",
            payment_date=run.pay_date.isoformat(),
            currency=currency_code,
            company_name=company_name,
        ))
    return rows


def generate_bank_transfer_file(db: Session, run_id: int, organization_id: int = None, actor_id: int = None,
                                 format_override: Optional[str] = None):
    """Returns (file_bytes, content_type, file_extension, filename) for the
    run's bank transfer file. Defaults to the format configured on the org's
    active Banking Policy (PayrollPolicy.bank_export_format); pass
    format_override to download the same run's data in a different format
    (csv/xlsx/txt/pdf) without changing that policy setting."""
    from app.modules.payroll.bank_export import get_exporter
    from app.modules.payroll.policy.service import get_active_policy

    run = get_payroll_run_by_id(db, run_id, organization_id)
    items = get_payslips_for_run(db, run_id, organization_id)
    policy = get_active_policy(db, organization_id)
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first()

    # Resolve the org's explicit currency override for bank exports.
    from app.modules.organizations.models import Organization
    org_row = db.query(Organization).filter(Organization.id == organization_id).first()
    org_currency = org_row.currency if org_row else None

    export_format = format_override or policy.bank_export_format
    rows = _build_bank_export_rows(run, items, company, org_currency=org_currency)
    try:
        exporter = get_exporter(export_format)
    except ValueError as exc:
        raise BadRequestException(str(exc))
    file_bytes = exporter.generate(rows)

    log_activity(
        db, organization_id,
        f"Bank transfer file ({export_format.upper()}) generated for run '{run.period_label}'.",
        ActivityStatus.SUCCESS, actor_id=actor_id,
    )
    filename = f"bank-transfer_{run.run_code or run.id}.{exporter.file_extension}"
    return file_bytes, exporter.content_type, exporter.file_extension, filename


def _resolve_org_country(db: Session, organization_id: int = None) -> str:
    """The org's current jurisdiction country — payslips/runs don't snapshot
    a country of their own, so this always reflects the org's *current*
    Compliance setting, same as the PDF generators already do."""
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first() if organization_id else None
    return _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")


def _serialize_payslip(item: PayslipItem, run: PayrollRun, country: str = None) -> dict:
    # additional_compensation (and, defensively, the other money columns) can
    # be NULL on rows created before that column existed — the model's
    # `default=0` only applies to new INSERTs, not to pre-existing rows. An
    # unguarded None here fails PayslipItemResponse's Decimal validation and
    # was taking down the *entire* payslip list/detail response with a 500,
    # not just the affected row. Coalesce to 0 so old rows still serialize.
    z = Decimal("0")
    return {
        "id": item.id,
        "runId": item.payroll_run_id,
        "payslipNumber": item.payslip_number,
        "employee": item.employee_name,
        "employeeId": item.employee_id,
        "department": item.department,
        "designation": item.designation,
        "dateOfJoining": item.date_of_joining,
        "country": country,
        "workState": item.work_state,
        "workLocality": item.work_locality,
        "period": run.period_label,
        "payDate": run.pay_date,
        "salary": item.gross_pay or z,
        "basicPay": item.basic_salary or z,
        "hra": item.hra or z,
        "specialAllowance": item.special_allowance or z,
        "allowanceItems": [
            {"key": a.key, "label": a.label, "amount": a.amount or z} for a in (item.allowance_items or [])
        ],
        "overtime": item.overtime or z,
        "additionalCompensation": item.additional_compensation or z,
        "payableDays": item.payable_days,        # None on old rows generated before this
        "totalWorkingDays": item.total_working_days,  # column existed — genuinely unknown, not 0
        "unpaidLeaveDays": item.unpaid_leave_days,
        "attendanceDeduction": item.attendance_deduction or z,
        "tds": item.tds or z,
        "surcharge": item.surcharge or z,
        "cess": item.cess or z,
        # US: federal/state/local income tax broken out separately — `tds`
        # above remains the correct COMBINED total for backward
        # compatibility (existing reports/consumers that sum `tds` still
        # get the right total). Zero for every non-US payslip and for any
        # US payslip generated before this split existed (see
        # jurisdictionLabels.js's getIncomeTaxLines for how the frontend
        # falls back to the combined `tds` line in that case).
        "federalIncomeTax": item.federal_income_tax or z,
        "stateIncomeTax": item.state_income_tax or z,
        "localTax": item.local_tax or z,
        "stateDisabilityInsurance": item.state_disability_insurance or z,
        "pf": item.pf or z,
        "esi": item.esi or z,
        "professionalTax": item.professional_tax or z,
        "socialSecurity": item.social_security or z,
        "medicare": item.medicare or z,
        "niEmployee": item.ni_employee or z,
        "employeePension": item.employee_pension or z,
        # UK: Student/Postgraduate Loan deduction — correctly reduces net_pay
        # (engine/standard.py's total_employee_deductions) since it was
        # calculated, but was never added to this dict, so it never reached
        # any payslip API response despite being a real, persisted column.
        "studyLoanDeduction": item.study_loan_deduction or z,
        "employerPf": item.employer_pf or z,
        "employerEsi": item.employer_esi or z,
        "employerSs": item.employer_social_security or z,
        "employerMedicare": item.employer_medicare or z,
        "employerPension": item.employer_pension or z,
        # UK: employer-side National Insurance — same "computed, persisted,
        # never serialized" gap as studyLoanDeduction above.
        "employerNi": item.employer_ni or z,
        "totalDeductions": item.total_deductions or z,
        "netPay": item.net_pay or z,
        "bankName": item.bank_name,
        "bankAccount": item.bank_account,
        "pan": item.pan,
        "uan": item.uan,
        "ifsc": item.ifsc,
        "complianceFields": item.compliance_fields or {},
        "status": item.status,
        "notes": item.notes,
    }


def list_payslips(db: Session, organization_id: int = None, search: str = None,
                   period: str = None, employee_id: int = None) -> List[dict]:
    query = (
        db.query(PayslipItem, PayrollRun)
        .join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
        .options(selectinload(PayslipItem.allowance_items))
    )
    query = _apply_org_filter(query, PayslipItem, organization_id)
    if period:
        query = query.filter(PayrollRun.period_label == period)
    if employee_id:
        query = query.filter(PayslipItem.employee_id == employee_id)
    if search:
        query = query.filter(PayslipItem.employee_name.ilike(f"%{search}%"))

    rows = query.order_by(PayrollRun.pay_date.desc()).all()
    # Each payslip's own snapshotted country_code (its employee's jurisdiction
    # at generation time) takes priority — falls back to the org's current
    # default only for rows generated before that column existed.
    org_country = _resolve_org_country(db, organization_id)
    return [_serialize_payslip(item, run, country=item.country_code or org_country) for item, run in rows]


def get_payslip_by_id(db: Session, payslip_id: int, organization_id: int = None) -> dict:
    query = (
        db.query(PayslipItem, PayrollRun)
        .join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
        .options(selectinload(PayslipItem.allowance_items))
    )
    query = query.filter(PayslipItem.id == payslip_id)
    query = _apply_org_filter(query, PayslipItem, organization_id)
    row = query.first()
    if not row:
        raise NotFoundException(f"Payslip {payslip_id} not found.")
    item, run = row
    country = item.country_code or _resolve_org_country(db, organization_id)
    return _serialize_payslip(item, run, country=country), item, run


def _get_currency_symbol(country: str) -> str:
    """Return the currency symbol for a jurisdiction country code or ISO 4217 code."""
    # First check if it's already an ISO currency code
    _iso_to_sym = {
        "INR": "\u20b9", "USD": "$", "GBP": "\u00a3",
        "AUD": "A$", "EUR": "\u20ac", "CAD": "C$",
        "AED": "AED", "BDT": "\u09f3", "BHD": "BHD", "BRL": "R$",
        "CHF": "CHF", "CNY": "\u00a5", "DKK": "kr", "GHS": "\u20b5",
        "HKD": "HK$", "JPY": "\u00a5", "KES": "KSh", "KRW": "\u20a9",
        "KWD": "KWD", "LKR": "\u20a8", "MXN": "MX$", "MYR": "RM",
        "NGN": "\u20a6", "NOK": "kr", "NPR": "\u20a8", "NZD": "NZ$",
        "OMR": "OMR", "PKR": "\u20a8", "QAR": "QAR", "RWF": "RF",
        "SAR": "SAR", "SEK": "kr", "SGD": "S$", "THB": "\u0e3f",
        "TZS": "TSh", "UGX": "USh", "ZAR": "R",
    }
    if country and country.upper() in _iso_to_sym:
        return _iso_to_sym[country.upper()]
    return {
        "IN": "\u20b9", "US": "$", "UK": "\u00a3",
        "AU": "A$", "DE": "\u20ac", "CA": "C$",
    }.get(country, "$")


def _get_currency_code(country: str) -> str:
    """Return the ISO currency code for a jurisdiction country code.
    Also passes through ISO 4217 codes unchanged."""
    _iso_codes = {
        "INR", "USD", "GBP", "AUD", "EUR", "CAD", "AED", "BDT", "BHD",
        "BRL", "CHF", "CNY", "DKK", "GHS", "HKD", "JPY", "KES", "KRW",
        "KWD", "LKR", "MXN", "MYR", "NGN", "NOK", "NPR", "NZD", "OMR",
        "PKR", "QAR", "RWF", "SAR", "SEK", "SGD", "THB", "TZS", "UGX", "ZAR",
    }
    if country and country.upper() in _iso_codes:
        return country.upper()
    return {
        "IN": "INR", "US": "USD", "UK": "GBP",
        "AU": "AUD", "DE": "EUR", "CA": "CAD",
    }.get(country, "USD")


def get_currency_for_jurisdiction(jurisdiction_code: str) -> str:
    """Public wrapper — returns the ISO 4217 currency code for a jurisdiction."""
    return _get_currency_code(jurisdiction_code)


def _amount_to_words(amount):
    """Convert a numeric amount to Indian English words for payslip display."""
    amount = int(round(float(amount or 0)))
    if amount == 0:
        return "Zero"
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
            "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
            "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty",
            "Sixty", "Seventy", "Eighty", "Ninety"]

    def _two_digits(n):
        if n < 20:
            return ones[n]
        return (tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")).strip()

    def _three_digits(n):
        if n == 0:
            return ""
        if n < 100:
            return _two_digits(n)
        return (ones[n // 100] + " Hundred"
                + (" " + _two_digits(n % 100) if n % 100 else ""))

    neg = amount < 0
    amount = abs(amount)

    crore, amount = divmod(amount, 10_000_000)
    lakh, amount = divmod(amount, 100_000)
    thousand, hundred = divmod(amount, 1000)

    parts = []
    if crore > 0:
        parts.append(_two_digits(crore) + (" Crore" if crore == 1 else " Crores"))
    if lakh > 0:
        parts.append(_two_digits(lakh) + (" Lakh" if lakh == 1 else " Lakhs"))
    if thousand > 0:
        parts.append(_two_digits(thousand) + " Thousand")
    if hundred > 0:
        parts.append(_three_digits(hundred))
    result = " ".join(parts).strip()
    if neg:
        result = "Minus " + result
    return result


def _register_rupee_font(c):
    """Attempt to register a Unicode-capable TTF font (regular + bold) so the
    rupee symbol renders correctly.  Falls back silently to Helvetica if no
    suitable font is found."""
    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
         "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
        ("/usr/share/fonts/TTF/DejaVuSans.ttf",
         "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
        (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf"),
         os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arialbd.ttf")),
        (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "tahoma.ttf"),
         os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "tahomabd.ttf")),
        ("/System/Library/Fonts/Supplemental/Arial.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ]
    for regular_path, bold_path in candidates:
        if not os.path.isfile(regular_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("RupeeFont", regular_path))
        except Exception:
            continue
        try:
            bold_source = bold_path if os.path.isfile(bold_path) else regular_path
            pdfmetrics.registerFont(TTFont("RupeeFont-Bold", bold_source))
        except Exception:
            pdfmetrics.registerFont(TTFont("RupeeFont-Bold", regular_path))
        return "RupeeFont"
    return None


def _payslip_identity_rows(country: str, data: dict) -> list:
    """Country-appropriate identity/bank-routing fields for the payslip's
    three PAN/UAN/IFSC row slots. India uses its own dedicated pan/uan/ifsc
    columns; every other jurisdiction reads its own identifiers out of the
    compliance_fields snapshot (see employee_validation.py for the full
    per-country field list) — those fields previously never appeared on a
    non-India payslip at all, which always showed blank PAN/UAN/IFSC rows
    regardless of the employee's actual jurisdiction."""
    if country == "IN":
        return [("PAN / Tax ID", data.get("pan")), ("UAN", data.get("uan")), ("IFSC", data.get("ifsc"))]
    cf = data.get("complianceFields") or {}
    rows_by_country = {
        "US": [("SSN", cf.get("ssn")), ("Filing Status", cf.get("w4_filing_status")), ("ABA Routing No.", cf.get("aba_routing_number"))],
        "UK": [("NINO", cf.get("nino")), ("Tax Code", cf.get("paye_tax_code")), ("Sort Code", cf.get("sort_code"))],
        "AU": [("TFN", cf.get("tfn")), ("Super Fund USI", cf.get("super_fund_usi")), ("BSB Code", cf.get("bsb_code"))],
        "CA": [("SIN", cf.get("sin")), ("Province", cf.get("province")), ("Transit No.", cf.get("transit_number"))],
        "DE": [("Steuer-ID", cf.get("steuer_id")), ("Steuerklasse", cf.get("steuerklasse")), ("IBAN", cf.get("iban"))],
    }
    return rows_by_country.get(country, [("Tax ID", None), ("Reference", None), ("Routing", None)])


def generate_payslip_pdf_bytes(db: Session, payslip_id: int, organization_id: int = None) -> bytes:
    """Renders a professional PDF payslip document styled after the Nova Tech
    Solutions template: navy blue header, bordered grid tables, side-by-side
    earnings/deductions, summary box, net-in-words, and disclaimer footer.
    Requires ``reportlab``."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    data, item, run = get_payslip_by_id(db, payslip_id, organization_id)

    # ── Company info for header ──
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first() if organization_id else None
    company_name = getattr(company, "name", None) or "Company Name"
    company_address = getattr(company, "address", None) or ""

    # data["country"] is get_payslip_by_id()'s already-resolved country —
    # the payslip's own snapshotted jurisdiction (its employee's country at
    # generation time), not the org's current default. Re-deriving it here
    # from the org's CompanyComplianceDetails (as this used to do) meant a
    # non-default-jurisdiction employee's PDF showed the wrong currency,
    # income-tax label, and statutory terminology.
    country = _normalize_country(data.get("country") or "IN")
    sym = _get_currency_symbol(country)

    def fmt(val):
        v = float(val or 0)
        if v == 0:
            return f"{sym} 0.00"
        return f"{sym} {v:,.2f}"

    def fmt_plain(val):
        return f"{float(val or 0):,.2f}"

    def fmt_date(v):
        if not v:
            return "-"
        if isinstance(v, str):
            try:
                v = datetime.strptime(v[:10], "%Y-%m-%d").date()
            except Exception:
                return v
        try:
            return v.strftime("%d-%b-%Y")
        except Exception:
            return str(v)

    def mask_account(acc):
        if not acc:
            return "-"
        s = str(acc)
        if len(s) <= 4:
            return s
        return "X" * (len(s) - 4) + s[-4:]

    currency_word = {"IN": "Rupees", "US": "Dollars", "UK": "Pounds"}.get(country, "")

    # ── Build earnings & deduction items (pre-computed for layout) ──
    earnings_items = [
        ("Basic Salary", data["basicPay"]),
        ("House Rent Allowance (HRA)", data["hra"]),
    ]
    # Named allowance components (Transport/Medical/Other/...), if this org
    # has any configured — shown as their own line items, same as Overtime/
    # Additional Compensation below. Special Allowance stays the final
    # catch-all, listed after these named slices.
    for allowance in data.get("allowanceItems") or []:
        earnings_items.append((allowance["label"], allowance["amount"]))
    earnings_items.append(("Special Allowance", data["specialAllowance"]))
    ov = float(data.get("overtime", 0) or 0)
    if ov > 0:
        earnings_items.append(("Overtime", ov))
    add_comp = float(data.get("additionalCompensation", 0) or 0)
    if add_comp > 0:
        earnings_items.append(("Additional Compensation", add_comp))
    earnings_total = float(data["salary"] or 0)

    deduction_items = []
    attendance_ded = float(data.get("attendanceDeduction", 0) or 0)
    if attendance_ded > 0:
        unpaid_days = data.get("unpaidLeaveDays")
        lbl = "LOP Deduction"
        if unpaid_days:
            lbl += f" ({float(unpaid_days):g} day{'s' if float(unpaid_days) != 1 else ''})"
        deduction_items.append((lbl, attendance_ded))
    # Every jurisdiction routes its income-tax withholding through the same
    # `tds` field (India-named historically) — label it with each
    # jurisdiction's own plain term (not a generic "Income Tax" gloss) so a
    # German/UK/Australian/etc. payslip reads the way that country's own
    # payslips actually do.
    income_tax_labels = {
        "IN": "TDS", "US": "Federal Withholding", "UK": "PAYE",
        "AU": "PAYG", "DE": "Lohnsteuer", "CA": "Federal Tax",
    }
    # US: federal/state/local are stored (and shown here) as three separate
    # lines instead of one combined "Federal Withholding" figure — `tds`
    # remains the correct combined total, only used here as a fallback for
    # a payslip generated before this split existed (all three would be
    # exactly 0 in that case, never partially populated), so an old US
    # payslip's PDF is unaffected. Same fallback rule as
    # jurisdictionLabels.js's getIncomeTaxLines on the frontend.
    us_split_total = float(data.get("federalIncomeTax", 0) or 0) + float(data.get("stateIncomeTax", 0) or 0) + float(data.get("localTax", 0) or 0)
    if country == "US" and us_split_total > 0:
        income_tax_line_items = [
            ("Federal Withholding", "federalIncomeTax"),
            ("State Tax", "stateIncomeTax"),
            ("Local Tax", "localTax"),
        ]
    else:
        income_tax_line_items = [(income_tax_labels.get(country, "TDS"), "tds")]
    pf_esi_labels = {
        "DE": {"pf": "Pension Insurance", "esi": "Social Insurance (Health / Unemployment / Care)"},
        "CA": {"esi": "Employment Insurance (EI)"},
    }.get(country, {})
    for lbl, key in [
        *income_tax_line_items,
        (pf_esi_labels.get("pf", "Provident Fund (PF)"), "pf"),
        (pf_esi_labels.get("esi", "Employee State Insurance (ESI)"), "esi"),
        ("Professional Tax", "professionalTax"),
    ]:
        v = float(data.get(key, 0) or 0)
        if v > 0:
            deduction_items.append((lbl, v))
    other_labels = {
        "CA": {"socialSecurity": "Canada Pension Plan (CPP)"},
        "AU": {"medicare": "Medicare Levy"},
    }.get(country, {})
    for lbl, key in [
        (other_labels.get("socialSecurity", "Social Security"), "socialSecurity"),
        (other_labels.get("medicare", "Medicare"), "medicare"),
        ("National Insurance", "niEmployee"),
        # UK: Workplace Pension (employee side) and Student/Postgraduate
        # Loan — both correctly computed/persisted but previously invisible
        # on every UK payslip PDF (see _serialize_payslip's own fix note).
        ("Workplace Pension", "employeePension"),
        ("Student Loan Deduction", "studyLoanDeduction"),
    ]:
        v = float(data.get(key, 0) or 0)
        if v > 0:
            deduction_items.append((lbl, v))
    # Employer-side contributions (Employer PF/ESI/Social Security/Medicare/
    # Pension/NI) are deliberately NOT shown here — this is the employee's
    # own payslip, and none of these are amounts deducted from the
    # employee's pay. They were previously mixed into this same
    # "Deductions" list (mislabeled, since they're the employer's own
    # cost, not the employee's) — removed at Venu's request. They remain
    # visible to admins on the Payroll Register / Run Detail views, which
    # are internal cost-review screens, not the payslip document itself.
    deductions_total = float(data["totalDeductions"] or 0)

    import io
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # ── Font setup: register Unicode font for rupee symbol ──
    base_font = _register_rupee_font(c)
    F = base_font or "Helvetica"
    FB = f"{base_font}-Bold" if base_font else "Helvetica-Bold"
    try:
        c.setFont(FB, 9)
    except Exception:
        FB = F

    # ── Colors ──
    navy = colors.HexColor("#1e3a8a")
    value_blue = colors.HexColor("#1d4ed8")
    gray_100 = colors.HexColor("#F3F4F6")
    gray_300 = colors.HexColor("#D1D5DB")
    gray_500 = colors.HexColor("#6B7280")
    gray_900 = colors.HexColor("#111827")
    green_600 = colors.HexColor("#16A34A")
    green_bg = colors.HexColor("#ECFDF5")
    white = colors.white

    card_margin = 6 * mm
    card_x = card_margin
    card_r_edge = width - card_margin
    card_w = card_r_edge - card_x

    margin_l = 14 * mm
    margin_r = width - 14 * mm
    page_w = margin_r - margin_l
    col_mid = width / 2
    y = height - card_margin
    card_top = y

    # ── Compute dynamic gaps so content fills the A4 page ──
    cell_h = 9.0 * mm
    hdr_h = 10.0 * mm
    row_h = 9.0 * mm
    sum_row_h = 9.5 * mm
    pd_row_h = 9.0 * mm

    min_gap_after_sub = 9 * mm
    min_gap_after_emp = 11 * mm
    min_gap_after_tables = 6 * mm
    min_gap_after_summary = 5 * mm
    min_gap_after_net_words = 7 * mm
    min_gap_after_payment = 3 * mm

    earnings_table_h = hdr_h + len(earnings_items) * cell_h + cell_h
    deductions_table_h = hdr_h + len(deduction_items) * cell_h + cell_h
    table_h = max(earnings_table_h, deductions_table_h)

    total_min_content = (
        24 * mm +           # header
        14 * mm +           # sub-header
        6 * mm +            # employee details heading
        5 * row_h +         # 5 employee rows
        6 * mm +            # earnings heading
        table_h +
        3 * sum_row_h +     # summary
        6 * mm +            # net-in-words heading
        8 * mm +            # net-in-words text
        2 * pd_row_h        # payment details table body
        + min_gap_after_sub + min_gap_after_emp + min_gap_after_tables
        + min_gap_after_summary + min_gap_after_net_words + min_gap_after_payment
    )
    available_h = (height - card_margin) - 10 * mm
    extra_h = max(0, available_h - total_min_content)
    per_gap = extra_h / 6 if extra_h > 0 else 0

    gap_after_sub = min_gap_after_sub + per_gap
    gap_after_emp = min_gap_after_emp + per_gap
    gap_after_tables = min_gap_after_tables + per_gap
    gap_after_summary = min_gap_after_summary + per_gap
    gap_after_net_words = min_gap_after_net_words + per_gap
    gap_after_payment = min_gap_after_payment + per_gap

    # ══════════════════════════════════════════════════════════════════════
    # 1. HEADER - Navy banner, left-aligned company name/address
    # ══════════════════════════════════════════════════════════════════════
    header_h = 24 * mm
    c.setFillColor(navy)
    c.rect(card_x, y - header_h, card_w, header_h, fill=True, stroke=False)

    c.setFillColor(white)
    c.setFont(FB, 20)
    c.drawString(margin_l + 5 * mm, y - 9 * mm, company_name.upper())
    if company_address:
        c.setFont(F, 10.5)
        c.drawString(margin_l + 5 * mm, y - 16 * mm, company_address)
    y -= header_h

    # ══════════════════════════════════════════════════════════════════════
    # 2. SUB-HEADER - Gray band, centered "PAYSLIP" + "Salary Month"
    # ══════════════════════════════════════════════════════════════════════
    sub_h = 14 * mm
    c.setFillColor(gray_100)
    c.rect(card_x, y - sub_h, card_w, sub_h, fill=True, stroke=False)

    c.setFillColor(gray_900)
    c.setFont(FB, 18)
    c.drawCentredString(col_mid, y - 5.5 * mm, "PAYSLIP")
    c.setFont(FB, 10.5)
    c.setFillColor(gray_500)
    salary_month = run.period_start.strftime("%B %Y")
    c.drawCentredString(col_mid, y - 11.5 * mm, f"Salary Month : {salary_month}")
    y -= sub_h + gap_after_sub

    # ══════════════════════════════════════════════════════════════════════
    # 3. EMPLOYEE DETAILS - plain heading + full-width grid table
    # ══════════════════════════════════════════════════════════════════════
    c.setFillColor(gray_900)
    c.setFont(FB, 13.5)
    c.drawString(margin_l, y, "Employee Details")
    y -= 6 * mm

    label_w = page_w * 0.20
    value_w = page_w * 0.30
    col_x = [margin_l, margin_l + label_w, margin_l + label_w + value_w,
             margin_l + 2 * label_w + value_w, margin_r]

    def draw_detail_row(y_top, row_h, cells):
        """cells: [(label, value), (label, value)]. Draws one bordered row."""
        c.setStrokeColor(gray_300)
        c.setLineWidth(0.4)
        c.rect(margin_l, y_top - row_h, page_w, row_h, fill=False, stroke=True)
        for cx in col_x[1:-1]:
            c.line(cx, y_top, cx, y_top - row_h)
        baseline = y_top - row_h / 2 - 1.6 * mm
        for i, (lbl, val) in enumerate(cells):
            lx = col_x[i * 2]
            vx = col_x[i * 2 + 1]
            c.setFillColor(gray_900)
            c.setFont(FB, 10)
            c.drawString(lx + 3 * mm, baseline, lbl)
            c.setFillColor(gray_900)
            c.setFont(F, 10)
            c.drawString(vx + 3 * mm, baseline, str(val))

    id_row1, id_row2, id_row3 = _payslip_identity_rows(country, data)
    emp_rows = [
        [("Employee Name", data["employee"]), ("Employee ID", str(data["employeeId"]))],
        [("Department", data["department"] or "-"), ("Designation", data.get("designation") or "-")],
        [("Date of Joining", fmt_date(data.get("dateOfJoining"))), (id_row1[0], id_row1[1] or "-")],
        [(id_row2[0], id_row2[1] or "-"), ("Bank", data.get("bankName") or "-")],
        [("Account No.", mask_account(data["bankAccount"])), (id_row3[0], id_row3[1] or "-")],
    ]
    for row in emp_rows:
        draw_detail_row(y, row_h, row)
        y -= row_h
    y -= gap_after_emp

    # ══════════════════════════════════════════════════════════════════════
    # 4. EARNINGS & DEDUCTIONS - plain headings + navy-header mini tables
    # ══════════════════════════════════════════════════════════════════════
    half_w = page_w / 2 - 1 * mm
    table_l = margin_l
    table_r = margin_l + half_w + 2 * mm

    c.setFillColor(gray_900)
    c.setFont(FB, 13.5)
    c.drawString(margin_l, y, "Earnings")
    c.drawString(table_r, y, "Deductions")
    y -= 6 * mm

    # Draw EARNINGS table
    ey = y
    c.setFillColor(navy)
    c.rect(table_l, ey - hdr_h, half_w, hdr_h, fill=True, stroke=False)
    c.setFillColor(white)
    c.setFont(FB, 9.5)
    c.drawString(table_l + 3 * mm, ey - hdr_h + 3.3 * mm, "Component")
    c.drawRightString(table_l + half_w - 3 * mm, ey - hdr_h + 3.3 * mm, f"Amount ({sym})")
    ey -= hdr_h

    for lbl, val in earnings_items:
        c.setStrokeColor(gray_300)
        c.setLineWidth(0.3)
        c.rect(table_l, ey - cell_h, half_w, cell_h, fill=False, stroke=True)
        c.setFillColor(gray_900)
        c.setFont(F, 10)
        c.drawString(table_l + 3 * mm, ey - cell_h + 3.1 * mm, lbl)
        c.drawRightString(table_l + half_w - 3 * mm, ey - cell_h + 3.1 * mm, fmt_plain(val))
        ey -= cell_h

    # Earnings total row
    c.setFillColor(navy)
    c.rect(table_l, ey - cell_h, half_w, cell_h, fill=True, stroke=False)
    c.setFillColor(white)
    c.setFont(FB, 10)
    c.drawString(table_l + 3 * mm, ey - cell_h + 3.1 * mm, "Total Earnings")
    c.drawRightString(table_l + half_w - 3 * mm, ey - cell_h + 3.1 * mm, fmt_plain(earnings_total))
    ey -= cell_h

    # Draw DEDUCTIONS table
    dy = y
    c.setFillColor(navy)
    c.rect(table_r, dy - hdr_h, half_w, hdr_h, fill=True, stroke=False)
    c.setFillColor(white)
    c.setFont(FB, 9.5)
    c.drawString(table_r + 3 * mm, dy - hdr_h + 3.3 * mm, "Component")
    c.drawRightString(table_r + half_w - 3 * mm, dy - hdr_h + 3.3 * mm, f"Amount ({sym})")
    dy -= hdr_h

    for lbl, val in deduction_items:
        c.setStrokeColor(gray_300)
        c.setLineWidth(0.3)
        c.rect(table_r, dy - cell_h, half_w, cell_h, fill=False, stroke=True)
        c.setFillColor(gray_900)
        c.setFont(F, 10)
        c.drawString(table_r + 3 * mm, dy - cell_h + 3.1 * mm, lbl)
        c.drawRightString(table_r + half_w - 3 * mm, dy - cell_h + 3.1 * mm, fmt_plain(val))
        dy -= cell_h

    # Deductions total row
    c.setFillColor(navy)
    c.rect(table_r, dy - cell_h, half_w, cell_h, fill=True, stroke=False)
    c.setFillColor(white)
    c.setFont(FB, 10)
    c.drawString(table_r + 3 * mm, dy - cell_h + 3.1 * mm, "Total Deductions")
    c.drawRightString(table_r + half_w - 3 * mm, dy - cell_h + 3.1 * mm, fmt_plain(deductions_total))
    dy -= cell_h

    # Sync y to the lower of the two tables
    y = min(ey, dy) - gap_after_tables

    # ══════════════════════════════════════════════════════════════════════
    # 5. SUMMARY BOX - right half only: Gross / Deductions / NET PAY
    # ══════════════════════════════════════════════════════════════════════
    sum_row_h = 9.5 * mm
    sum_x = table_r
    sum_w = half_w

    c.setStrokeColor(gray_300)
    c.setLineWidth(0.5)

    # Row 1: Gross Salary
    c.rect(sum_x, y - sum_row_h, sum_w, sum_row_h, fill=False, stroke=True)
    c.setFillColor(gray_900)
    c.setFont(FB, 10.5)
    c.drawString(sum_x + 3 * mm, y - sum_row_h + 3.3 * mm, "Gross Salary")
    c.drawRightString(sum_x + sum_w - 3 * mm, y - sum_row_h + 3.3 * mm, fmt(earnings_total))
    y -= sum_row_h

    # Row 2: Total Deductions
    c.rect(sum_x, y - sum_row_h, sum_w, sum_row_h, fill=False, stroke=True)
    c.setFillColor(gray_900)
    c.setFont(FB, 10.5)
    c.drawString(sum_x + 3 * mm, y - sum_row_h + 3.3 * mm, "Total Deductions")
    c.drawRightString(sum_x + sum_w - 3 * mm, y - sum_row_h + 3.3 * mm, fmt(deductions_total))
    y -= sum_row_h

    # Row 3: Net Pay (green highlighted)
    c.setFillColor(green_bg)
    c.rect(sum_x, y - sum_row_h, sum_w, sum_row_h, fill=True, stroke=False)
    c.setStrokeColor(green_600)
    c.setLineWidth(0.8)
    c.rect(sum_x, y - sum_row_h, sum_w, sum_row_h, fill=False, stroke=True)
    c.setFillColor(green_600)
    c.setFont(FB, 13)
    c.drawString(sum_x + 3 * mm, y - sum_row_h + 3.3 * mm, "NET PAY")
    c.drawRightString(sum_x + sum_w - 3 * mm, y - sum_row_h + 3.3 * mm, fmt(data["netPay"]))
    y -= sum_row_h

    y -= gap_after_summary

    # ══════════════════════════════════════════════════════════════════════
    # 6. NET SALARY IN WORDS
    # ══════════════════════════════════════════════════════════════════════
    words = _amount_to_words(float(data["netPay"] or 0))
    c.setFillColor(gray_900)
    c.setFont(FB, 12)
    c.drawString(margin_l, y, "Net Salary in Words")
    y -= 6 * mm
    c.setFont(F, 12)
    suffix = f"{currency_word} Only." if currency_word else "Only."
    c.drawString(margin_l, y, f"{words} {suffix}")
    y -= gap_after_net_words

    # ══════════════════════════════════════════════════════════════════════
    # 7. PAYMENT DETAILS - 2x2 table (label row + value row)
    # ══════════════════════════════════════════════════════════════════════
    pd_row_h = 9.0 * mm
    c.setStrokeColor(gray_300)
    c.setLineWidth(0.4)
    c.rect(margin_l, y - 2 * pd_row_h, page_w, 2 * pd_row_h, fill=False, stroke=True)
    c.line(col_mid, y, col_mid, y - 2 * pd_row_h)
    c.line(margin_l, y - pd_row_h, margin_r, y - pd_row_h)

    c.setFillColor(gray_900)
    c.setFont(FB, 10)
    c.drawString(margin_l + 3 * mm, y - pd_row_h + 3.2 * mm, "Payment Mode")
    c.drawString(col_mid + 3 * mm, y - pd_row_h + 3.2 * mm, "Salary Credit Date")

    c.setFont(F, 10.5)
    c.drawString(margin_l + 3 * mm, y - 2 * pd_row_h + 3.2 * mm, "Bank Transfer (NEFT)")
    c.drawString(col_mid + 3 * mm, y - 2 * pd_row_h + 3.2 * mm, fmt_date(data["payDate"]))
    y -= 2 * pd_row_h + gap_after_payment

    # ══════════════════════════════════════════════════════════════════════
    # 9. FOOTER - separator line + disclaimer
    # ══════════════════════════════════════════════════════════════════════
    c.setStrokeColor(gray_300)
    c.setLineWidth(0.4)
    c.line(margin_l, 10 * mm, margin_r, 10 * mm)
    c.setFont(F, 9.5)
    c.setFillColor(gray_500)
    c.drawCentredString(width / 2, 6.5 * mm,
                        "This is a computer-generated payslip and does not require a signature.")

    # ══════════════════════════════════════════════════════════════════════
    # 10. OUTER CARD FRAME - subtle border around the whole document
    # ══════════════════════════════════════════════════════════════════════
    card_bottom = card_margin
    c.setStrokeColor(gray_300)
    c.setLineWidth(0.8)
    c.rect(card_x, card_bottom, card_w, card_top - card_bottom, fill=0, stroke=1)

    c.showPage()
    c.save()
    return buf.getvalue()



def _enrich_attendance_record(db: Session, record: PayrollAttendanceRecord, organization_id: int) -> dict:
    """Attach employee name/name fields to an AttendanceRecordResponse (scoped to tenant)."""
    employee = _apply_employee_filter(
        db.query(PayrollEmployee).filter(PayrollEmployee.id == record.employee_id),
        organization_id,
    ).first()
    name = getattr(employee, "name", None) if employee else None
    department = getattr(employee, "department", None) if employee else None
    designation = getattr(employee, "designation", None) if employee else None
    return {
        "id": record.id,
        "employee_id": record.employee_id,
        "name": name,
        "department": department,
        "designation": designation,
        "date": record.date,
        "check_in": record.check_in,
        "check_out": record.check_out,
        "status": record.status,
        "leave_type": record.leave_type,
        "hours": record.hours,
        "rewards": record.rewards,
        "bonus": record.bonus,
        "other_compensation": record.other_compensation,
        "notes": record.notes,
    }


def _normalize_name(s: str) -> str:
    """Collapse whitespace and lowercase for comparison."""
    import re
    return re.sub(r"\s+", " ", s.strip().lower())


# ── Attendance ↔ Leave Sync Helpers ──────────────────────────────────


def _sync_attendance_to_leave(
    db: Session,
    employee_id: int,
    date_val: date,
    status: str,
    leave_type: Optional[str],
    is_half_day: bool,
    organization_id: int,
) -> Optional[int]:
    """Sync a single attendance record to the Leaves module.

    Returns the PayrollLeaveRequest id if one was created/updated, else None.
    No-op for present/absent/holiday/weekend statuses.
    """
    if status not in ("leave",):
        return None

    resolved_leave_type = _resolve_leave_type(leave_type, is_half_day)
    if not resolved_leave_type:
        return None

    existing = _find_matching_leave_request(db, employee_id, date_val, organization_id)

    if existing:
        return existing.id

    leave_req = PayrollLeaveRequest(
        organization_id=organization_id,
        employee_id=employee_id,
        leave_type=resolved_leave_type,
        start_date=date_val,
        end_date=date_val,
        days=1,
        reason="Auto-created from attendance",
        status="approved",
    )
    from app.core.code_generation import generate_business_code
    leave_req.request_code = generate_business_code(db, organization_id, "LV", PayrollLeaveRequest, "request_code")
    db.add(leave_req)
    db.flush()

    _update_leave_balance(db, employee_id, resolved_leave_type, organization_id)

    try:
        log_activity(db, organization_id,
            f"Leave auto-created from attendance: emp={employee_id}, type={resolved_leave_type}, date={date_val}.",
            ActivityStatus.INFO)
    except Exception:
        pass

    return leave_req.id


def _sync_attendance_update_to_leave(
    db: Session,
    record: PayrollAttendanceRecord,
    organization_id: int,
) -> None:
    """When attendance is updated, sync the change to linked leave request."""
    old_status = record.status
    old_leave_type = record.leave_type
    old_is_half_day = record.is_half_day
    leave_req_id = record.leave_request_id

    if leave_req_id and old_status != "leave":
        record.leave_request_id = None
        db.flush()
        _maybe_remove_leave_request(db, leave_req_id, organization_id)
        return

    if old_status == "leave":
        resolved = _resolve_leave_type(old_leave_type, old_is_half_day)
        if leave_req_id:
            _update_existing_leave_request(db, leave_req_id, resolved, organization_id)
        else:
            new_id = _sync_attendance_to_leave(
                db, record.employee_id, record.date, old_status, old_leave_type, old_is_half_day, organization_id,
            )
            if new_id:
                record.leave_request_id = new_id


def _resolve_leave_type(leave_type: Optional[str], is_half_day: bool) -> Optional[str]:
    """Map attendance leave_type + is_half_day to PayrollLeaveRequest leave_type.

    Falls back to "unpaid" when no explicit type is set (or an unrecognized
    value like "lop" is passed), matching the Attendance page's own display
    convention where a missing leave_type is shown as an unpaid leave. This
    ensures every "leave" status always produces a matching PayrollLeaveRequest
    instead of silently skipping the Leave Management sync.
    """
    if is_half_day:
        return leave_type or "unpaid"
    if leave_type in ("paid", "unpaid", "sick", "casual", "compOff"):
        return leave_type
    return "unpaid"


def _backfill_orphaned_leave_syncs(db: Session, organization_id: int) -> int:
    """Create missing PayrollLeaveRequest rows for attendance records marked
    "leave" that were never synced — e.g. records saved before
    _resolve_leave_type() defaulted a blank leave_type to "unpaid", which used
    to silently skip the sync. Idempotent (matches existing requests via
    _find_matching_leave_request), so it's safe to call on every fetch.
    """
    # with_for_update() serializes concurrent callers on Postgres: two page-load
    # requests hitting this at once would otherwise both see the same
    # not-yet-linked row and each create their own PayrollLeaveRequest for it,
    # producing duplicates. Postgres re-checks the WHERE clause once a lock is
    # released, so the second caller correctly sees the row as no longer
    # orphaned. SQLite (dev fallback) silently ignores this clause; its
    # coarser whole-database write lock is the only guard there.
    orphans = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == organization_id,
        PayrollAttendanceRecord.status == "leave",
        PayrollAttendanceRecord.leave_request_id.is_(None),
    ).with_for_update().all()
    if not orphans:
        return 0

    synced = 0
    for rec in orphans:
        if rec.leave_request_id:
            continue
        req_id = _sync_attendance_to_leave(
            db, rec.employee_id, rec.date, rec.status, rec.leave_type, rec.is_half_day, organization_id,
        )
        if req_id:
            rec.leave_request_id = req_id
            synced += 1

    if synced:
        db.commit()
    return synced


def _dedupe_auto_created_leave_requests(db: Session, organization_id: int) -> int:
    """Merge duplicate auto-created leave requests for the same employee +
    type + date range. These can only arise from the backfill race above (now
    closed) creating more than one request before either committed. Keeps the
    oldest row, re-links any attendance records pointing at a duplicate, and
    deletes the rest. Idempotent — safe to call on every fetch."""
    rows = db.query(PayrollLeaveRequest).filter(
        PayrollLeaveRequest.organization_id == organization_id,
        PayrollLeaveRequest.reason == "Auto-created from attendance",
    ).order_by(PayrollLeaveRequest.id.asc()).all()

    groups: dict[tuple, list] = {}
    for r in rows:
        key = (r.employee_id, r.leave_type, r.start_date, r.end_date)
        groups.setdefault(key, []).append(r)

    removed = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        keeper, *dupes = group
        for dup in dupes:
            db.query(PayrollAttendanceRecord).filter(
                PayrollAttendanceRecord.leave_request_id == dup.id,
            ).update({"leave_request_id": keeper.id}, synchronize_session=False)
            db.delete(dup)
            removed += 1

    if removed:
        db.commit()
    return removed


def _recompute_leave_balances_used(db: Session, organization_id: int) -> None:
    """Recompute each employee's per-type "used" day count from approved
    PayrollLeaveRequest rows — the authoritative source — instead of trusting
    it to have been correctly incremented in place elsewhere. Cheap, and safe
    to call on every Leave Management fetch.

    Also seeds a PayrollLeaveAllocation row (default totals matching the
    frontend's own LEAVE_TYPES fallback: paid 20 / unpaid 10 / sick 12 /
    compOff 5) for any employee who doesn't have one yet — without it, there
    is nothing for the "used" recompute below to write into, and the Leave
    Management page silently falls back to displaying frontend-only defaults
    for every employee.
    """
    DEFAULT_LEAVE_TOTALS = {"paid": 20, "unpaid": 10, "sick": 12, "compOff": 5}

    allocations = db.query(PayrollLeaveAllocation).filter(
        PayrollLeaveAllocation.organization_id == organization_id,
    ).all()

    existing_emp_ids = {a.employee_id for a in allocations}
    all_emp_ids = {
        row.id for row in db.query(PayrollEmployee.id).filter(
            PayrollEmployee.organization_id == organization_id,
        ).all()
    }
    missing_emp_ids = all_emp_ids - existing_emp_ids
    dirty = bool(missing_emp_ids)
    if missing_emp_ids:
        for emp_id in missing_emp_ids:
            alloc = PayrollLeaveAllocation(
                organization_id=organization_id,
                employee_id=emp_id,
                leave_balances={lt: {"used": 0, "total": total} for lt, total in DEFAULT_LEAVE_TOTALS.items()},
            )
            db.add(alloc)
            allocations.append(alloc)
        db.flush()

    if not allocations:
        return

    approved = db.query(
        PayrollLeaveRequest.employee_id,
        PayrollLeaveRequest.leave_type,
        sa_func.sum(PayrollLeaveRequest.days),
    ).filter(
        PayrollLeaveRequest.organization_id == organization_id,
        PayrollLeaveRequest.status == "approved",
    ).group_by(
        PayrollLeaveRequest.employee_id, PayrollLeaveRequest.leave_type,
    ).all()

    used_by_emp: dict[int, dict[str, int]] = {}
    for emp_id, lt, total_days in approved:
        used_by_emp.setdefault(emp_id, {})[lt] = int(total_days or 0)

    for alloc in allocations:
        emp_used = used_by_emp.get(alloc.employee_id, {})
        updated = copy.deepcopy(alloc.leave_balances or {})
        row_changed = False
        for lt, used_days in emp_used.items():
            if lt in updated and updated[lt].get("used", 0) != used_days:
                updated[lt]["used"] = used_days
                row_changed = True
        if row_changed:
            alloc.leave_balances = updated
            dirty = True

    if dirty:
        db.commit()


def _find_matching_leave_request(
    db: Session,
    employee_id: int,
    date_val: date,
    organization_id: int,
) -> Optional[PayrollLeaveRequest]:
    """Find an existing approved leave request covering this employee+date."""
    return db.query(PayrollLeaveRequest).filter(
        PayrollLeaveRequest.organization_id == organization_id,
        PayrollLeaveRequest.employee_id == employee_id,
        PayrollLeaveRequest.start_date <= date_val,
        PayrollLeaveRequest.end_date >= date_val,
        PayrollLeaveRequest.status == "approved",
    ).first()


def _update_leave_balance(
    db: Session,
    employee_id: int,
    leave_type: str,
    organization_id: int,
) -> None:
    """Deduct one day from leave balance. Prevents negative balance."""
    alloc = db.query(PayrollLeaveAllocation).filter(
        PayrollLeaveAllocation.organization_id == organization_id,
        PayrollLeaveAllocation.employee_id == employee_id,
    ).first()
    if not alloc:
        return
    # Deep-copy before mutating: `leave_balances` is a plain JSON column (no
    # MutableDict tracking), so reassigning the SAME dict object SQLAlchemy
    # already has loaded is a no-op — it never gets flushed to the DB.
    balances = copy.deepcopy(alloc.leave_balances or {})
    if leave_type not in balances:
        return
    used = balances[leave_type].get("used", 0)
    total = balances[leave_type].get("total", 0)
    if used < total:
        balances[leave_type]["used"] = used + 1
        alloc.leave_balances = balances


def _restore_leave_balance(
    db: Session,
    employee_id: int,
    leave_type: str,
    organization_id: int,
) -> None:
    """Restore one day from leave balance (attendance reverted from leave)."""
    alloc = db.query(PayrollLeaveAllocation).filter(
        PayrollLeaveAllocation.organization_id == organization_id,
        PayrollLeaveAllocation.employee_id == employee_id,
    ).first()
    if not alloc:
        return
    balances = copy.deepcopy(alloc.leave_balances or {})
    if leave_type not in balances:
        return
    used = balances[leave_type].get("used", 0)
    if used > 0:
        balances[leave_type]["used"] = used - 1
        alloc.leave_balances = balances


def _maybe_remove_leave_request(db: Session, leave_request_id: int, organization_id: int) -> None:
    """Remove an auto-created leave request if no attendance records link to it."""
    if not leave_request_id:
        return
    linked = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.leave_request_id == leave_request_id,
    ).first()
    if linked:
        return
    req = db.query(PayrollLeaveRequest).filter(
        PayrollLeaveRequest.id == leave_request_id,
        PayrollLeaveRequest.organization_id == organization_id,
    ).first()
    if req and req.reason == "Auto-created from attendance":
        lt = req.leave_type
        db.delete(req)
        _restore_leave_balance(db, req.employee_id, lt, organization_id)


def _update_existing_leave_request(
    db: Session,
    leave_request_id: int,
    new_leave_type: Optional[str],
    organization_id: int,
) -> None:
    """Update leave type on an existing auto-created leave request."""
    if not leave_request_id:
        return
    req = db.query(PayrollLeaveRequest).filter(
        PayrollLeaveRequest.id == leave_request_id,
        PayrollLeaveRequest.organization_id == organization_id,
    ).first()
    if req and req.reason == "Auto-created from attendance" and new_leave_type:
        old_lt = req.leave_type
        req.leave_type = new_leave_type
        if old_lt != new_leave_type:
            _restore_leave_balance(db, req.employee_id, old_lt, organization_id)
            _update_leave_balance(db, req.employee_id, new_leave_type, organization_id)


def _sync_leave_to_attendance(
    db: Session,
    leave_request: PayrollLeaveRequest,
    organization_id: int,
) -> None:
    """Create/update attendance records for a leave request's date range."""
    current = date.today()
    d = leave_request.start_date
    while d <= leave_request.end_date:
        existing = db.query(PayrollAttendanceRecord).filter(
            PayrollAttendanceRecord.organization_id == organization_id,
            PayrollAttendanceRecord.employee_id == leave_request.employee_id,
            PayrollAttendanceRecord.date == d,
        ).first()
        if existing:
            old_status = existing.status
            old_leave_type = existing.leave_type
            existing.status = "leave"
            existing.leave_type = leave_request.leave_type
            existing.leave_request_id = leave_request.id
            if old_status == "leave" and old_leave_type != leave_request.leave_type:
                _restore_leave_balance(db, existing.employee_id, old_leave_type, organization_id)
                _update_leave_balance(db, existing.employee_id, leave_request.leave_type, organization_id)
        else:
            rec = PayrollAttendanceRecord(
                organization_id=organization_id,
                employee_id=leave_request.employee_id,
                date=d,
                status="leave",
                leave_type=leave_request.leave_type,
                leave_request_id=leave_request.id,
            )
            db.add(rec)
        d += timedelta(days=1)
    db.flush()


def _remove_linked_attendance(
    db: Session,
    leave_request: PayrollLeaveRequest,
    organization_id: int,
) -> None:
    """Revert attendance records linked to a rejected/cancelled leave request."""
    records = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == organization_id,
        PayrollAttendanceRecord.employee_id == leave_request.employee_id,
        PayrollAttendanceRecord.leave_request_id == leave_request.id,
    ).all()
    for rec in records:
        old_lt = rec.leave_type
        rec.status = "absent"
        rec.leave_type = None
        rec.leave_request_id = None
        if old_lt:
            _restore_leave_balance(db, rec.employee_id, old_lt, organization_id)
    db.flush()


def bulk_save_attendance(db: Session, data: BulkAttendanceRequest, organization_id: int) -> dict:
    """Upsert attendance records for a date. Matches on (employee_id, date)
    to update existing records instead of creating duplicates.

    Returns a dict with saved records and skipped-row details so the frontend
    can surface exactly what succeeded and what didn't."""
    # ── 1. Single query: fetch all payroll employees for this org ──────
    emp_rows = db.query(
        PayrollEmployee.id,
        PayrollEmployee.name,
        PayrollEmployee.employee_code,
        PayrollEmployee.status,
    ).filter(PayrollEmployee.organization_id == organization_id).all()

    valid_emp_ids = {row.id for row in emp_rows}
    inactive_emp_ids = {row.id for row in emp_rows if row.status and row.status.lower() != "active"}

    # code→id (e.g. "ZOI_3E00001"→5) for employee_code resolution
    code_to_id: dict[str, int] = {}
    # id→normalized_name for post-resolution cross-validation
    id_to_normalized_name: dict[int, str] = {}
    for row in emp_rows:
        if row.employee_code:
            code_to_id[row.employee_code.strip()] = row.id
        id_to_normalized_name[row.id] = _normalize_name((row.name or "").strip())

    # name→id (normalised full name)
    name_to_id: dict[str, int] = {}
    # first token→[ids], last token→[ids] for fuzzy fallback (tokens derived
    # from the single `name` field — no separate first/last columns anymore)
    first_name_to_ids: dict[str, list[int]] = {}
    last_name_to_ids: dict[str, list[int]] = {}
    # normalized full name→id (for reversed-name matching)
    all_names_normalized: dict[str, int] = {}

    for row in emp_rows:
        full = (row.name or "").strip()
        parts = full.split()
        fn = parts[0] if parts else ""
        ln = parts[-1] if len(parts) > 1 else ""
        full_n = _normalize_name(full)
        if full_n:
            name_to_id[full_n] = row.id
            all_names_normalized[full_n] = row.id
        # Also index reversed token order (e.g. "Shaik Ashraf" for "Ashraf Shaik")
        if len(parts) > 1:
            reversed_n = _normalize_name(" ".join([parts[-1]] + parts[:-1]))
            if reversed_n and reversed_n != full_n:
                all_names_normalized[reversed_n] = row.id
        if fn.lower() in first_name_to_ids:
            first_name_to_ids[fn.lower()].append(row.id)
        else:
            first_name_to_ids[fn.lower()] = [row.id]
        if ln.lower() in last_name_to_ids:
            last_name_to_ids[ln.lower()].append(row.id)
        else:
            last_name_to_ids[ln.lower()] = [row.id]

    # ── 2. Resolve employee IDs & build upsert payloads ────────────────
    to_upsert: list[dict] = []          # dicts with employee_id, date_val, mapped fields
    skipped_details: list[dict] = []

    for item in data.records:
        payload = item.model_dump()
        employee_id = payload.pop("employeeId")
        record_name = (payload.pop("name", None) or "").strip()
        date_val = payload.pop("date")

        # --- resolve employee_id ---
        resolved = False
        if employee_id and employee_id in valid_emp_ids:
            resolved = True
        elif employee_id and isinstance(employee_id, str) and employee_id.strip() in code_to_id:
            employee_id = code_to_id[employee_id.strip()]
            resolved = True
        elif employee_id and isinstance(employee_id, str) and employee_id.strip().lower() in {k.lower(): v for k, v in code_to_id.items()}:
            for k, v in code_to_id.items():
                if k.lower() == employee_id.strip().lower():
                    employee_id = v
                    resolved = True
                    break
        elif record_name:
            norm = _normalize_name(record_name)
            # 1. exact full-name match (first last)
            rid = name_to_id.get(norm)
            if rid:
                employee_id = rid
                resolved = True
            else:
                # 2. reversed order (last first)
                rid = all_names_normalized.get(norm)
                if rid:
                    employee_id = rid
                    resolved = True
                else:
                    # 3. first-name only (unambiguous)
                    first_part = record_name.split()[0].lower() if record_name else ""
                    candidates = first_name_to_ids.get(first_part, [])
                    if len(candidates) == 1:
                        employee_id = candidates[0]
                        resolved = True
                    else:
                        # 4. last-name only (unambiguous)
                        last_part = record_name.split()[-1].lower() if record_name else ""
                        ln_candidates = last_name_to_ids.get(last_part, [])
                        if len(ln_candidates) == 1:
                            employee_id = ln_candidates[0]
                            resolved = True

        if not resolved:
            skipped_details.append({
                "rowName": record_name or None,
                "rowId": employee_id if employee_id else None,
                "reason": "No matching employee found",
                "date": date_val,
            })
            continue

        # ── Check: is the employee active? ──
        if employee_id and employee_id in inactive_emp_ids:
            skipped_details.append({
                "rowName": record_name or None,
                "rowId": employee_id,
                "reason": "Employee is not active",
                "date": date_val,
            })
            continue

        # ── Cross-validate: does the uploaded name match the resolved employee? ──
        if record_name and employee_id in id_to_normalized_name:
            resolved_name_n = id_to_normalized_name[employee_id]
            uploaded_name_n = _normalize_name(record_name)
            if resolved_name_n and uploaded_name_n and resolved_name_n != uploaded_name_n:
                uploaded_words = set(uploaded_name_n.split())
                resolved_words = set(resolved_name_n.split())
                # Allow partial matches (e.g. first-name-only uploads) — only
                # flag when NO meaningful word (≥3 chars) overlaps.
                overlap = [w for w in uploaded_words if len(w) >= 3 and w in resolved_words]
                if not overlap:
                    skipped_details.append({
                        "rowName": record_name or None,
                        "rowId": employee_id,
                        "reason": f"Name mismatch: employee {employee_id} is \"{resolved_name_n}\", not \"{record_name}\"",
                        "date": date_val,
                    })
                    continue

        is_half_day = payload.pop("isHalfDay", False)
        to_upsert.append({
            "employee_id": employee_id,
            "date_val": date_val,
            "check_in": payload.pop("checkIn", None),
            "check_out": payload.pop("checkOut", None),
            "status": payload.pop("status", "present"),
            "leave_type": payload.pop("leaveType", None),
            "is_half_day": is_half_day,
            "hours": payload.pop("hours", None),
            "rewards": payload.pop("rewards", Decimal("0")),
            "bonus": payload.pop("bonus", Decimal("0")),
            "other_compensation": payload.pop("otherCompensation", Decimal("0")),
            "notes": payload.pop("notes", None),
        })

    if not to_upsert:
        return {
            "saved": 0,
            "skipped": len(skipped_details),
            "skippedDetails": skipped_details,
            "records": [],
        }

    # ── 3. Batch-fetch existing records (single query instead of N) ────
    emp_date_pairs = {(r["employee_id"], r["date_val"]) for r in to_upsert}
    existing_records = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == organization_id,
        tuple_(
            PayrollAttendanceRecord.employee_id,
            PayrollAttendanceRecord.date,
        ).in_(emp_date_pairs),
    ).all()
    existing_map: dict[tuple, PayrollAttendanceRecord] = {
        (r.employee_id, r.date): r for r in existing_records
    }

    results = []
    sync_actions: list[dict] = []
    for r in to_upsert:
        key = (r["employee_id"], r["date_val"])
        mapped = {k: v for k, v in r.items() if k not in ("employee_id", "date_val")}
        existing = existing_map.get(key)
        if existing:
            prev_status = existing.status
            prev_leave_type = existing.leave_type
            for field, value in mapped.items():
                setattr(existing, field, value)
            results.append(existing)
            if prev_status != existing.status or prev_leave_type != existing.leave_type:
                sync_actions.append({
                    "record": existing,
                    "prev_status": prev_status,
                    "prev_leave_type": prev_leave_type,
                })
        else:
            rec = PayrollAttendanceRecord(
                organization_id=organization_id,
                employee_id=r["employee_id"],
                date=r["date_val"],
                **mapped,
            )
            db.add(rec)
            results.append(rec)
            sync_actions.append({
                "record": rec,
                "prev_status": None,
                "prev_leave_type": None,
            })

    db.flush()

    for sa in sync_actions:
        rec = sa["record"]
        prev_status = sa["prev_status"]
        prev_leave_type = sa["prev_leave_type"]
        if rec.status == "leave" and prev_status != "leave":
            req_id = _sync_attendance_to_leave(
                db, rec.employee_id, rec.date, rec.status, rec.leave_type, rec.is_half_day, organization_id,
            )
            if req_id:
                rec.leave_request_id = req_id
        elif rec.status == "leave" and prev_status == "leave" and rec.leave_type != prev_leave_type:
            _sync_attendance_update_to_leave(db, rec, organization_id)
        elif prev_status == "leave" and rec.status != "leave":
            _maybe_remove_leave_request(db, rec.leave_request_id, organization_id)
            rec.leave_request_id = None

    db.commit()
    for r in results:
        db.refresh(r)

    # ── 4. Batch-enrich employee details (single query instead of N) ──
    all_emp_ids = list({r.employee_id for r in results})
    emp_detail_rows = db.query(PayrollEmployee).filter(
        PayrollEmployee.id.in_(all_emp_ids),
    ).all()
    emp_detail_map = {e.id: e for e in emp_detail_rows}

    enriched = []
    for r in results:
        emp = emp_detail_map.get(r.employee_id)
        name = getattr(emp, "name", None) if emp else None
        enriched.append({
            "id": r.id,
            "employee_id": r.employee_id,
            "name": name,
            "department": getattr(emp, "department", None) if emp else None,
            "designation": getattr(emp, "designation", None) if emp else None,
            "date": r.date,
            "check_in": r.check_in,
            "check_out": r.check_out,
            "status": r.status,
            "leave_type": r.leave_type,
            "is_half_day": r.is_half_day,
            "leave_request_id": r.leave_request_id,
            "hours": r.hours,
            "rewards": r.rewards,
            "bonus": r.bonus,
            "other_compensation": r.other_compensation,
            "notes": r.notes,
        })

    return {
        "saved": len(enriched),
        "skipped": len(skipped_details),
        "skippedDetails": skipped_details,
        "records": enriched,
    }


def get_attendance_records(
    db: Session,
    organization_id: int,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    employee_id: Optional[int] = None,
) -> List[dict]:
    """Fetch attendance records with optional date range and employee filter."""
    query = db.query(
        PayrollAttendanceRecord,
        PayrollEmployee.name,
        PayrollEmployee.department,
        PayrollEmployee.designation,
    ).outerjoin(
        PayrollEmployee,
        (PayrollAttendanceRecord.employee_id == PayrollEmployee.id) &
        (PayrollEmployee.organization_id == organization_id)
    ).filter(
        PayrollAttendanceRecord.organization_id == organization_id
    )
    if start_date:
        query = query.filter(PayrollAttendanceRecord.date >= start_date)
    if end_date:
        query = query.filter(PayrollAttendanceRecord.date <= end_date)
    if employee_id:
        query = query.filter(PayrollAttendanceRecord.employee_id == employee_id)

    rows = query.order_by(PayrollAttendanceRecord.date.desc()).all()
    return [
        {
            "id": record.id,
            "employee_id": record.employee_id,
            "name": name,
            "department": department,
            "designation": designation,
            "date": record.date,
            "check_in": record.check_in,
            "check_out": record.check_out,
            "status": record.status,
            "leave_type": record.leave_type,
            "is_half_day": record.is_half_day,
            "leave_request_id": record.leave_request_id,
            "hours": record.hours,
            "rewards": record.rewards,
            "bonus": record.bonus,
            "other_compensation": record.other_compensation,
            "notes": record.notes,
        }
        for record, name, department, designation in rows
    ]


def clear_attendance_records(
    db: Session,
    organization_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """Delete attendance records for the given organization, optionally scoped to a date range.
    Also cleans up orphaned auto-created leave requests."""
    from datetime import date as _date
    q = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == organization_id
    )
    if start_date:
        q = q.filter(PayrollAttendanceRecord.date >= _date.fromisoformat(start_date))
    if end_date:
        q = q.filter(PayrollAttendanceRecord.date <= _date.fromisoformat(end_date))

    linked_ids = [r.leave_request_id for r in q.all() if r.leave_request_id]
    deleted = q.delete(synchronize_session=False)

    if linked_ids:
        orphaned = db.query(PayrollLeaveRequest).filter(
            PayrollLeaveRequest.id.in_(linked_ids),
            PayrollLeaveRequest.reason == "Auto-created from attendance",
        ).all()
        for req in orphaned:
            still_linked = db.query(PayrollAttendanceRecord).filter(
                PayrollAttendanceRecord.leave_request_id == req.id,
            ).first()
            if not still_linked:
                db.delete(req)

    db.commit()
    return deleted


def get_attendance_summary(db: Session, organization_id: int) -> dict:
    """Aggregate today's attendance counts."""
    today = date.today()
    records = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == organization_id,
        PayrollAttendanceRecord.date == today,
    ).all()
    total = len(records)
    present = sum(1 for r in records if r.status == "present")
    absent = sum(1 for r in records if r.status == "absent")
    leave = sum(1 for r in records if r.status == "leave")
    return {
        "total": total,
        "present": present,
        "absent": absent,
        "leave": leave,
    }


# ── Compliance Documents ────────────────────────────────────────────

# Legacy local-disk location for compliance documents. Production stores
# uploads in Cloud Storage via app/core/object_storage.py; this constant is
# kept only so old local-dev rows/paths still resolve.
_COMPLIANCE_DOC_UPLOAD_DIR = _os.environ.get(
    "PAYROLL_COMPLIANCE_DOC_UPLOAD_DIR",
    os.path.join(_os.environ.get("UPLOAD_BASE_DIR", "/tmp/uploads"), "payroll_compliance_documents"),
)


def list_compliance_documents(
    db: Session,
    organization_id: int,
    *,
    country: Optional[str] = None,
) -> List[ComplianceDocument]:
    query = db.query(ComplianceDocument).filter(ComplianceDocument.organization_id == organization_id)
    if country:
        query = query.filter(ComplianceDocument.country == country)
    return query.order_by(ComplianceDocument.uploaded_at.desc()).all()


def delete_compliance_document(db: Session, document_id: int, organization_id: int) -> None:
    from app.core.object_storage import delete_ref

    doc = db.query(ComplianceDocument).filter(
        ComplianceDocument.id == document_id,
        ComplianceDocument.organization_id == organization_id,
    ).first()
    if not doc:
        raise NotFoundException("Compliance document", document_id)

    delete_ref(doc.file_path)

    db.delete(doc)
    db.commit()
    log_activity(db, organization_id, f"Compliance document '{doc.title}' deleted.", ActivityStatus.INFO)


def _ocr_image_file(image_data: bytes) -> str:
    # NOTE: previously this caught every exception (including a missing
    # `pytesseract`/`PIL` package or a missing system `tesseract` binary)
    # and returned "", which was indistinguishable from "OCR ran and found
    # no statutory rates in the image." Letting it raise means
    # upload_compliance_document() now records a real "failed" status +
    # error message instead of silently pretending extraction succeeded.
    import io as _io

    from PIL import Image  # type: ignore
    import pytesseract  # type: ignore

    image = Image.open(_io.BytesIO(image_data))
    try:
        text = pytesseract.image_to_string(image)
    finally:
        image.close()
    return text or ""


def _extract_text_from_uploaded_document(file_ref: str) -> str:
    """Extract raw text from a stored upload. `file_ref` is whatever the
    DB row holds — a gs:// Cloud Storage URI (production) or a local path
    (dev/tests); both resolve to bytes via the object-storage layer."""
    if not file_ref:
        return ""

    from app.core.object_storage import read_bytes

    data = read_bytes(file_ref)

    ext = _os.path.splitext(file_ref)[1].lower()
    if ext == ".txt":
        return data.decode("utf-8", errors="ignore")
    if ext == ".csv":
        return data.decode("utf-8", errors="ignore")
    if ext in {".pdf"}:
        import io as _io

        import pypdf  # type: ignore
        reader = pypdf.PdfReader(_io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        return _ocr_image_file(data)
    return ""


_DASH_TOKENS = {"—", "–", "-", "n/a", "N/A", "\ufffd"}

# Per-jurisdiction vocabulary. This is the fix for the core bug: the old
# code only knew about India's components (PF/ESI/PT/TDS), so uploading a
# US or UK notice silently returned [] no matter what was in the document —
# which then let the *frontend's* generic policy fallback quietly display
# whichever country's canned numbers happened to be selected in the UI tab,
# mislabeled as "extracted from this document". Detecting the document's
# own jurisdiction and only matching that jurisdiction's real statutory
# components closes that gap.
#
# Each component is ("key", "match pattern", "display label", "pct" | "flat").
# "pct"  components pull percentage cells (employee / employer / total).
# "flat" components pull currency-amount cells (e.g. a flat monthly fee).
_COUNTRY_EXTRACTION_CONFIG = {
    "IN": {
        "currency": "₹",
        "detect": r"jurisdiction:\s*india",
        "components": [
            ("pf",  r"provident fund|\bpf\b(?!\w)", "Employee Provident Fund (EPF)", "pct"),
            ("esi", r"state insurance|\besi\b", "Employee State Insurance (ESI)", "pct"),
            ("pt",  r"professional tax", "Professional Tax (PT)", "flat"),
            ("lwf", r"labour welfare fund", "Labour Welfare Fund", "flat"),
            ("tds", r"\btds\b", "TDS / Income Tax", "pct"),
        ],
    },
    "US": {
        "currency": "$",
        "detect": r"jurisdiction:\s*united states",
        "components": [
            ("social_security", r"social security", "Social Security (FICA)", "pct"),
            ("medicare",        r"medicare", "Medicare (FICA)", "pct"),
            ("futa",            r"federal unemployment|\bfuta\b", "Federal Unemployment (FUTA)", "pct"),
            ("sui",             r"state unemployment|\bsui\b", "State Unemployment Insurance (SUI)", "pct"),
            ("sdi",             r"\bsdi\b|state disability", "State Disability Insurance (SDI)", "pct"),
        ],
    },
    "UK": {
        "currency": "£",
        "detect": r"jurisdiction:\s*united kingdom",
        "components": [
            ("national_insurance", r"national insurance|ni contributions|\bnic\b|class 1\s+ni", "National Insurance", "pct"),
            ("pension",            r"pension\s+auto.?enrolment|workplace\s+pension|auto.?enrolment(?!\s+declaration)", "Workplace Pension (Auto-Enrolment)", "pct"),
            ("apprenticeship_levy",r"apprenticeship levy", "Apprenticeship Levy", "pct"),
            ("ssp",                r"statutory sick pay|\bssp\b", "Statutory Sick Pay (SSP)", "flat"),
        ],
    },
}

_SECTION_END_MARKERS = {
    "IN": "Income Tax Slabs",
    "US": "Federal Income Tax Brackets",
    "UK": "Income Tax Bands",
}


def detect_country_from_text(text: str) -> Optional[str]:
    """Detects the jurisdiction a compliance document is actually *about*
    by reading its own content, rather than trusting the currently-selected
    UI tab. Falls back to None (unknown) if no known jurisdiction phrase is
    found — callers should fall back to the country the user supplied on
    upload in that case."""
    if not text:
        return None
    for code, cfg in _COUNTRY_EXTRACTION_CONFIG.items():
        if re.search(cfg["detect"], text, re.I):
            return code
    return None


def _strip_parenthetical_notes(line: str) -> str:
    # Wage-base / threshold notes like "(up to $176,100 wage base)" or
    # "(above £242/week)" sit inside parentheses next to the real rate and
    # would otherwise get mistaken for a second employee/employer column.
    return re.sub(r"\([^)]*\)", " ", line)


def _extract_contribution_rates(text: str, country: Optional[str]) -> List[dict]:
    """Per-jurisdiction extraction of statutory contribution rates.

    Many PDFs render table cells as individual text lines (pypdf outputs
    each cell on a separate line), so after finding the component keyword
    on a line we scan the next several lines for the cell values instead
    of requiring everything on the same line.

    Reads the first three real cells positionally — employee share,
    employer share, total — so the column order in the PDF must match
    (Component / Employee / Employer / Total).
    """
    cfg = _COUNTRY_EXTRACTION_CONFIG.get(country)
    if not cfg:
        return []

    rates: List[dict] = []
    lines = text.splitlines()
    n = len(lines)

    for key, pattern, label, kind in cfg["components"]:
        if kind == "pct":
            cell_re = re.compile(r"\d+(?:\.\d+)?\s*%\+?|—|–|\ufffd|N/A", re.I)
        else:
            cell_re = re.compile(
                rf"{re.escape(cfg['currency'])}\s?[\d,]+(?:\.\d+)?(?:/\w+)?|—|–|\ufffd|N/A",
                re.I,
            )

        for i, line in enumerate(lines):
            if not re.search(pattern, line, re.I):
                continue
            # Found the component line — collect cell values from subsequent lines
            cells: List[str] = []
            for j in range(i + 1, min(i + 8, n)):
                candidate = _strip_parenthetical_notes(lines[j]).strip()
                if not candidate:
                    continue
                found = cell_re.findall(candidate)
                if found:
                    cells.extend(found)
                if len(cells) >= 3:
                    break
            if not cells:
                break
            employee = cells[0] if len(cells) > 0 else "—"
            employer = cells[1] if len(cells) > 1 else "—"
            total    = cells[2] if len(cells) > 2 else (employer if len(cells) == 2 else employee)
            rates.append({
                "id": key,
                "label": label,
                "employee": "—" if employee in _DASH_TOKENS else employee,
                "employer": "—" if employer in _DASH_TOKENS else employer,
                "total": total,
            })
            break
    return rates


def _extract_tax_slabs(text: str, country: Optional[str]) -> List[dict]:
    """Parses the income-tax slab table using the correct currency symbol
    for the document's own jurisdiction (previously this hardcoded ₹ onto
    every document, so a US or UK slab table came back stamped with rupee
    signs on dollar/pound figures). Scoped to the slab section only, so
    unrelated numbers elsewhere in the document (reference numbers, dates)
    can't be mistaken for a slab row."""
    currency = _COUNTRY_EXTRACTION_CONFIG.get(country, {}).get("currency", "")
    marker = _SECTION_END_MARKERS.get(country)
    section = text.split(marker, 1)[1] if marker and marker in text else text
    section = section.split("Compliance Requirements", 1)[0]

    slabs: List[dict] = []
    pattern = re.compile(
        re.escape(currency) + r"?\s?([\d,]+)\s*(?:-|to|–|—)\s*([\d,]+|above)\s*(nil|\d+(?:\.\d+)?%)",
        re.I,
    )
    for i, match in enumerate(pattern.finditer(section)):
        low, high, rate = match.groups()
        rate_label = "Nil" if rate.lower() == "nil" else rate
        slabs.append({
            "id": f"doc-slab-{i}",
            "min": f"{currency}{low}",
            "max": "Above" if high.lower() == "above" else f"{currency}{high}",
            "rate": rate_label,
            "tax": f"{rate_label} in this band",
        })
    return slabs


def _extract_requirements(text: str) -> List[dict]:
    """Pulls short freeform lines that look like compliance requirements
    (contain words like 'must'/'shall'/'required'). Capped so a large
    document doesn't dump its entire body into the preview."""
    requirements: List[dict] = []
    keywords = ("must", "shall", "required", "mandatory", "due by", "deadline")
    for line in text.splitlines():
        clean = line.strip()
        if not clean or len(clean) > 200:
            continue
        if any(k in clean.lower() for k in keywords):
            requirements.append({"label": clean[:150]})
        if len(requirements) >= 5:
            break
    return requirements


_ENTITY_RULES = {
    "UK": [
        ("name",
         [r"(?:company|employer|organisation|business)\s+name\s*:\s*(.+)"],
         [r"^company\s+(legal\s+)?name$", r"^employer\s+name$"]),
        ("registrationNumber",
         [r"(?:company\s+registration\s+(?:number|no)|crn|registration\s+no)\s*:?\s*([a-z0-9/]+(?:\s+[a-z0-9/]+)*)"],
         [r"^companies\s+house\s+(number|no)$", r"^company\s+registration\s+(number|no)$"]),
        ("vatNumber",
         [r"vat\s+(?:registration\s+)?(?:number|no)\s*:?\s*((?:gb)?\d{9,12})"],
         [r"^vat\s+(?:registration\s+)?(?:number|no)$"]),
        ("payeReference",
         [r"paye\s+(?:reference|ref|no)\s*:?\s*([\d/]+[a-z0-9]*)"],
         [r"^paye\s+reference$"]),
        ("utr",
         [r"(?:utr|unique\s+taxpayer\s+reference)\s*:?\s*(\d{10})"],
         [r"^unique\s+taxpayer\s+reference$", r"^utr$"]),
        ("address",
         [r"(?:registered\s+(?:office|address)|business\s+address)\s*:?\s*(.+)"],
         [r"^registered\s+(?:office|address)$", r"^business\s+address$"]),
        ("accountsReferenceDate",
         [r"(?:accounts\s+reference\s+date|ard|accounting\s+ref)\s*:?\s*(.+)"],
         [r"^accounts\s+reference\s+date$", r"^ard$"]),
    ],
    "IN": [
        ("name",
         [r"(?:company|employer|organisation|business)\s+name\s*:\s*(.+)"],
         [r"^company\s+(legal\s+)?name$", r"^employer\s+name$", r"^name\s+of\s+(the\s+)?(company|employer)$"]),
        ("pan",
         [r"pan\s+(?:number|no)?\s*:?\s*([a-z]{5}\d{4}[a-z])"],
         [r"^pan\s+(?:number|no)?$", r"^permanent\s+account\s+number$"]),
        ("tan",
         [r"tan\s+(?:number|no)?\s*:?\s*([a-z]{4}\d{5}[a-z])"],
         [r"^tan\s+(?:number|no)?$", r"^tax\s+deduction\s+account\s+number$"]),
        ("gst",
         [r"gst\s+(?:number|no|in)?\s*:?\s*(\d{2}[a-z]{5}\d{4}[a-z]\d[z][a-z\d])"],
         [r"^gst\s+(?:number|no|in)?$", r"^gstin$"]),
        ("pfCode",
         [r"(?:pf|provident\s+fund)\s+(?:code|number|no|account)\s*:?\s*([a-z0-9/]+(?:\s+[a-z0-9/]+)*)"],
         [r"^pf\s+(?:code|number|no|account)", r"^provident\s+fund\s+(?:code|number|no|account)"]),
        ("esiCode",
         [r"(?:esi|state\s+insurance)\s+(?:code|number|no)\s*:?\s*([a-z0-9/]+(?:\s+[a-z0-9/]+)*)"],
         [r"^esi\s+(?:code|number|no)", r"^state\s+insurance\s+(?:code|number|no)"]),
        ("address",
         [r"(?:registered\s+(?:office|address)|business\s+address)\s*:?\s*(.+)"],
         [r"^registered\s+(?:office|address)$", r"^business\s+address$"]),
    ],
    "US": [
        ("name",
         [r"(?:company|employer|organisation|business)\s+name\s*:\s*(.+)"],
         [r"^company\s+(legal\s+)?name$", r"^employer\s+name$", r"^business\s+name$"]),
        ("ein",
         [r"(?:ein|employer\s+identification\s+number|federal\s+id)\s*:?\s*(\d{2}[-\s]?\d{7})"],
         [r"^ein$", r"^employer\s+identification\s+number$", r"^federal\s+(?:id|identification)\s+number$"]),
        ("stateId",
         [r"(?:state\s+(?:id|identification|number)|unemployment\s+(?:id|account))\s*:?\s*([a-z0-9]+(?:[-/][a-z0-9]+)*)"],
         [r"^state\s+(?:id|identification|number)$", r"^unemployment\s+(?:id|account\s+number)$"]),
        ("naicsCode",
         [r"naics\s*(?:code)?\s*:?\s*(\d{6})"],
         [r"^naics\s+code$"]),
        ("address",
         [r"(?:registered\s+(?:office|address)|business\s+address|legal\s+address)\s*:?\s*(.+)"],
         [r"^registered\s+(?:office|address)$", r"^business\s+address$", r"^legal\s+address$"]),
    ],
}


def _extract_registered_entity_details(text: str, country: Optional[str] = None) -> dict:
    """Extracts registered-entity metadata from a compliance notice.

    Handles two common PDF text-layouts:
      1.  "Label: Value" on the same line
      2.  "Label" on line N, "Value" on line N+1

    Uses country-specific patterns so each jurisdiction's expected fields
    (UK: Companies House / PAYE / UTR;  IN: PAN / TAN / GST / PF / ESI;
    US: EIN / State ID / NAICS) are matched correctly."""
    rules = _ENTITY_RULES.get(country, _ENTITY_RULES.get("UK", []))
    details: dict = {}
    lines = text.splitlines()
    n = len(lines)

    for key, same_line, next_line in rules:
        # Try same-line first:  "Label: Value"
        for pat in same_line:
            for line in lines:
                m = re.search(pat, line.strip(), re.I)
                if m:
                    val = m.group(1).strip().strip(",;")
                    if val:
                        details[key] = val
                        break
            if key in details:
                break
        if key in details:
            continue
        # Fallback to next-line:  "Label" then value on line below
        for i, line in enumerate(lines):
            stripped = line.strip()
            if any(re.match(pat, stripped, re.I) for pat in next_line):
                if i + 1 < n:
                    val = lines[i + 1].strip().strip(",;")
                    if val:
                        details[key] = val
                break

    return details


def _extract_compliance_data(text: str, country: Optional[str]) -> dict:
    """Assembles the exact `extracted` object the frontend contract in
    payrollService.js documents: { contributionRates, taxSlabs, requirements }.
    `country` should be the jurisdiction *detected from the document's own
    text* (see detect_country_from_text) wherever possible — using the
    uploader's currently-selected UI tab instead is what caused rates from
    the wrong jurisdiction to be shown as "extracted from this document."
    This is returned to the client as a per-document preview only — it does
    NOT write into the org's live ContributionRate/TaxSlab policy tables,
    matching the "reference only, nothing is auto-applied" copy already
    shown in ComplianceDocuments.jsx. Applying extracted values to live
    policy should be an explicit, separate user action if that's wanted."""
    if not text:
        return {"contributionRates": [], "taxSlabs": [], "requirements": []}
    return {
        "contributionRates": _extract_contribution_rates(text, country),
        "taxSlabs": _extract_tax_slabs(text, country),
        "requirements": _extract_requirements(text),
        "registeredEntityDetails": _extract_registered_entity_details(text, country),
    }


def upload_compliance_document(
    db: Session,
    *,
    title: str,
    category: str,
    file_path: str,
    file_name: str,
    file_size: int,
    mime_type: str,
    organization_id: int,
    country: Optional[str] = None,
    description: Optional[str] = None,
    document_type: Optional[str] = None,
    uploaded_by: Optional[int] = None,
) -> ComplianceDocument:
    doc = ComplianceDocument(
        organization_id=organization_id,
        title=title,
        document_type=document_type,
        category=category,
        description=description,
        file_path=file_path,
        file_name=file_name,
        file_size=file_size,
        mime_type=mime_type,
        uploaded_by=uploaded_by,
        country=country,
        status=ComplianceDocumentStatus.PROCESSING.value,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Extraction runs synchronously here (fine for typical single-page
    # notices/PDFs). If this ever needs to handle large multi-page scans,
    # move this to a background task/queue and have the client keep
    # polling GET /compliance/documents — the "processing" status above and
    # the polling loop already in ComplianceDocuments.jsx are built for
    # exactly that, they just weren't being fed real status until now.
    try:
        extracted_text = _extract_text_from_uploaded_document(file_path)

        # Trust the document's own content over whatever jurisdiction tab
        # was active in the UI when the file was dropped — that mismatch
        # (uploading a US notice while the India tab is selected, say) was
        # the actual root cause of "wrong country" extraction results.
        detected_country = detect_country_from_text(extracted_text)
        resolved_country = detected_country or country

        doc.extracted_data = _extract_compliance_data(extracted_text, resolved_country)
        doc.status = ComplianceDocumentStatus.PARSED.value

        # If the document names a jurisdiction that differs from the one it
        # was uploaded under, record what the document actually says so the
        # frontend can show a mismatch warning instead of silently mixing
        # this document's numbers into the wrong tab.
        if detected_country and country and detected_country != country:
            doc.country = detected_country
            doc.error_message = (
                f"This document appears to be for {detected_country}, "
                f"but was uploaded under {country}."
            )
        elif detected_country and not country:
            doc.country = detected_country

        # Populate CompanyComplianceDetails from extracted entity data so
        # the Compliance Overview tab shows jurisdiction, Tax ID, etc.
        # without the user having to fill the form manually.
        try:
            entity = (doc.extracted_data or {}).get("registeredEntityDetails") or {}
            if entity or resolved_country:
                company_row = get_company_details(db, organization_id)
                needs_commit = False

                if entity.get("name") and not company_row.name:
                    company_row.name = entity["name"]
                    needs_commit = True
                if entity.get("address") and not company_row.address:
                    company_row.address = entity["address"]
                    needs_commit = True
                if resolved_country and not company_row.jurisdiction_country:
                    company_row.jurisdiction_country = resolved_country
                    needs_commit = True
                if resolved_country and not company_row.compliance_pack:
                    pack_map = {"IN": "India Statutory", "US": "US Federal & State", "UK": "UK HMRC"}
                    company_row.compliance_pack = pack_map.get(resolved_country, "")
                    needs_commit = True

                # Country-specific tax-id / employer-id mapping
                if resolved_country == "IN":
                    if entity.get("pan") and not company_row.tax_no:
                        company_row.tax_no = entity["pan"].upper()
                        needs_commit = True
                    if entity.get("pfCode") and not company_row.employer_id:
                        company_row.employer_id = entity["pfCode"]
                        needs_commit = True
                elif resolved_country == "UK":
                    if entity.get("utr") and not company_row.tax_no:
                        company_row.tax_no = entity["utr"]
                        needs_commit = True
                    if entity.get("payeReference") and not company_row.employer_id:
                        company_row.employer_id = entity["payeReference"]
                        needs_commit = True
                elif resolved_country == "US":
                    if entity.get("ein") and not company_row.tax_no:
                        company_row.tax_no = entity["ein"]
                        needs_commit = True

                if needs_commit:
                    db.commit()
        except Exception:  # noqa: S110 - best-effort, must not break the upload
            pass
    except Exception as exc:  # noqa: BLE001 - surface it instead of swallowing it
        doc.status = ComplianceDocumentStatus.FAILED.value
        doc.error_message = f"Could not extract text from this document: {exc}"

    db.add(doc)
    db.commit()
    db.refresh(doc)

    log_activity(db, organization_id, f"Compliance document '{title}' uploaded.", ActivityStatus.INFO)
    return doc


# ── Compliance ─────────────────────────────────────────────────────────

# Registration collects a full country name (matches the standalone
# Compliance dropdown's supported set); jurisdiction_country stores the
# 2-letter code that dropdown actually uses as its option value. Mirrors
# enterprise/service.py's SUPPORTED_COUNTRY_CODES universe.
_COUNTRY_NAME_TO_JURISDICTION_CODE = {
    "india": "IN",
    "united states": "US",
    "united kingdom": "UK",
    "australia": "AU",
    "germany": "DE",
    "canada": "CA",
}


def _merge_tax_identifiers(existing: dict | None, incoming: dict | None) -> dict:
    """Merge two tax-identifier maps, keeping existing values for any key that
    is already set — the deduplication rule for compliance sync. New keys (or
    blank values) from registration never overwrite a value the admin already
    entered/overrode in the Compliance tab."""
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if not value:
            continue
        if key not in merged or not merged.get(key):
            merged[key] = value
    return merged or None


def get_company_details(db: Session, organization_id: int) -> CompanyComplianceDetails:
    row = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first()
    if not row:
        row = CompanyComplianceDetails(organization_id=organization_id)
        db.add(row)
        db.commit()
        db.refresh(row)

    # Pre-fill from data the org already gave elsewhere (registration /
    # billing signup) instead of asking them to retype it on this form.
    # Only ever fills fields still at their blank default — never
    # overwrites anything already entered here.
    needs_basic_backfill = not row.name or not row.tax_no or not row.industry or not row.address \
        or not row.employer_id or not row.email or not row.phone or not row.type
    # Legacy rows created before the "" default (see CompanyComplianceDetails)
    # may still carry the old literal "India" placeholder — treat that the
    # same as blank. Deliberately NOT gated on configured_at: configured_at
    # flips true on ANY Compliance save (e.g. saving just the Tax No field),
    # not specifically a deliberate jurisdiction choice, so a row can reach
    # configured_at=True while jurisdiction_country is still just the unset
    # placeholder. Once a real code is present this condition is false
    # forever, so this can never overwrite an actual choice — see the lock
    # in update_company_details for what stops a REAL value being changed,
    # and verify_jurisdiction for how Enterprise mode later owns the field.
    needs_jurisdiction_backfill = (
        row.jurisdiction_country in ("", "India") or not row.jurisdiction_state
    )

    if needs_basic_backfill or needs_jurisdiction_backfill:
        from app.modules.organizations.models import Organization

        org = db.query(Organization).filter(Organization.id == organization_id).first()
        changed = False
        if org and needs_basic_backfill:
            if not row.name and org.organization_name:
                row.name = org.organization_name
                changed = True
            if not row.tax_no and org.tax_no:
                row.tax_no = org.tax_no
                changed = True
            if not row.employer_id and org.registration_number:
                row.employer_id = org.registration_number
                changed = True
            if not row.industry and org.industry:
                row.industry = org.industry
                changed = True
            if not row.type and org.company_type:
                row.type = org.company_type
                changed = True
            if not row.address and org.address:
                row.address = org.address
                changed = True
            if not row.email and org.email:
                row.email = org.email
                changed = True
            if not row.phone and org.phone:
                row.phone = org.phone
                changed = True
        if org and needs_jurisdiction_backfill:
            code = org.country and _COUNTRY_NAME_TO_JURISDICTION_CODE.get(org.country.strip().lower())
            if code and row.jurisdiction_country != code:
                row.jurisdiction_country = code
                changed = True
            if org.state and not row.jurisdiction_state:
                row.jurisdiction_state = org.state
                changed = True
        # Sync the jurisdiction tax/registration IDs captured at registration.
        # Only fills keys the compliance row doesn't already hold (see
        # _merge_tax_identifiers) so a value the admin later overrode is never
        # clobbered by a re-registration/resubmission — reuse, not duplicates.
        if org and org.tax_identifiers:
            merged = _merge_tax_identifiers(row.tax_identifiers, org.tax_identifiers)
            if merged != (row.tax_identifiers or None):
                row.tax_identifiers = merged
                changed = True
        if changed:
            db.commit()
            db.refresh(row)

    # Inherit pack defaults from the Super Admin's jurisdiction pack when
    # fields are still blank — implements the inheritance model for compliance.
    pack_changed = _backfill_compliance_from_pack(row, db)
    if pack_changed:
        db.commit()
        db.refresh(row)

    return row


def _backfill_compliance_from_pack(row: "CompanyComplianceDetails", db: Session) -> bool:
    """Pre-fill compliance fields from the Super Admin's active JurisdictionPack
    when they haven't been set yet. Returns True if any field was changed.

    This implements the Super Admin → Org Admin inheritance model for
    compliance details: the Super Admin declares pack values, the Org Admin
    inherits them by default, and can overwrite where permitted."""
    if not row.active_pack_id:
        return False
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == row.active_pack_id).first()
    if not pack:
        return False

    changed = False
    # Pack ID — the compliance pack identifier
    if not row.compliance_pack and pack.pack_id:
        row.compliance_pack = pack.pack_id
        changed = True
    # Jurisdiction country — inherit from pack if not set
    if not row.jurisdiction_country and pack.jurisdiction_country:
        row.jurisdiction_country = pack.jurisdiction_country
        changed = True
    # State — inherit from pack if not set
    if not row.jurisdiction_state and pack.jurisdiction_state:
        row.jurisdiction_state = pack.jurisdiction_state
        changed = True
    return changed


def update_company_details(db: Session, organization_id: int, data: CompanyDetailsUpdate) -> CompanyComplianceDetails:
    row = get_company_details(db, organization_id)

    # Jurisdiction lock: once a REAL jurisdiction has been chosen, it can no
    # longer be changed through this endpoint — every Payroll sub-module
    # (Employees, Payroll Runs, Payslips, Reports, statutory calculations,
    # currency) is keyed off this single field, so a silent mid-stream switch
    # would invalidate historical payroll data. A real jurisdiction change
    # needs a controlled migration process, not a dropdown edit. Gated on the
    # value itself being real (not blank/legacy "India" placeholder) rather
    # than on configured_at alone — configured_at flips true on ANY Compliance
    # save, not specifically a deliberate jurisdiction choice, so a row can
    # reach configured_at=True while jurisdiction_country is still unset;
    # locking on that would strand the org unable to ever pick one.
    incoming_country = data.jurisdictionCountry
    jurisdiction_already_chosen = row.jurisdiction_country not in (None, "", "India")
    if (
        jurisdiction_already_chosen
        and incoming_country is not None
        and incoming_country != row.jurisdiction_country
    ):
        raise HTTPException(
            http_status.HTTP_423_LOCKED,
            detail="The payroll jurisdiction is locked after Compliance has been configured and cannot be changed here. Changing jurisdictions requires a controlled migration process.",
        )

    field_map = {
        "name": "name", "type": "type", "taxNo": "tax_no", "employerId": "employer_id",
        "address": "address", "industry": "industry", "email": "email", "phone": "phone",
        "jurisdictionCountry": "jurisdiction_country", "jurisdictionState": "jurisdiction_state",
        "compliancePack": "compliance_pack", "schedule": "schedule",
        "settlementBank": "settlement_bank", "settlementAcc": "settlement_acc",
    }
    payload = data.model_dump(exclude_unset=True)
    for camel_field, value in payload.items():
        column = field_map.get(camel_field)
        if column:
            setattr(row, column, value)

    # Edit / Override support for the jurisdiction tax/registration IDs.
    # Values are validated against the org's jurisdiction schema, then stored
    # (the admin is explicitly overriding — replace what's there). Only keys
    # the schema defines are persisted, so unknown/blank keys never create
    # duplicate or junk tax records. The primary identifier is mirrored back
    # into tax_no so payroll footers/reports keep reading a single value.
    tax_identifiers_payload = payload.get("taxIdentifiers")
    if tax_identifiers_payload is not None:
        from app.core.jurisdiction import (
            get_jurisdiction_code,
            primary_tax_value,
            validate_tax_identifiers_or_raise,
        )

        jurisdiction_code = get_jurisdiction_code(
            data.jurisdictionCountry or row.jurisdiction_country
        )
        if jurisdiction_code:
            validated = validate_tax_identifiers_or_raise(jurisdiction_code, tax_identifiers_payload)
        else:
            validated = {k: v for k, v in tax_identifiers_payload.items() if v}
        row.tax_identifiers = validated or None
        # Mirror the primary identifier into the legacy tax_no column unless the
        # caller explicitly overrode taxNo in the same payload.
        if "taxNo" not in payload:
            row.tax_no = primary_tax_value(jurisdiction_code, validated) or row.tax_no

    # First explicit admin save unlocks the mandatory Payroll onboarding gate
    # and locks the jurisdiction in place (see check above) — immutable once
    # set.
    if row.configured_at is None:
        row.configured_at = datetime.utcnow()

    db.commit()
    db.refresh(row)
    log_activity(db, organization_id, "Company compliance details updated.", ActivityStatus.SUCCESS)
    return row


def get_compliance_data(db: Session, organization_id: int) -> dict:
    company = get_company_details(db, organization_id)
    # Placeholder for a future FilingRecord model (statutory filing due-dates,
    # e.g. PF/ESI monthly returns, TDS quarterly returns). Returned as an
    # empty list today rather than fabricated entries.
    filings: List[dict] = []
    return {"company": company, "filings": filings}


# ── Reports ─────────────────────────────────────────────────────────────

def get_payroll_reports(db: Session, organization_id: int = None, **_) -> List[dict]:
    """Build report entries from existing payroll runs."""
    q = db.query(PayrollRun)
    if organization_id is not None:
        q = q.filter(PayrollRun.organization_id == organization_id)
    runs = q.order_by(PayrollRun.period_start.desc()).all()

    reports = []
    for run in runs:
        if run.status in ("Draft",):
            continue
        reports.append({
            "id": run.id,
            "name": f"Payroll Report — {run.period_label}",
            "period": run.period_label,
            "generatedAt": run.updated_at.strftime("%b %d, %Y") if run.updated_at else (
                run.created_at.strftime("%b %d, %Y") if run.created_at else "-"
            ),
            # "available" once the run has passed Review (Approved and every
            # later stage — Authorized/Paid/Closed — are all just as final;
            # this used to only recognize Approved/Paid, so an Authorized or
            # Closed run incorrectly showed as "pending" here.
            "status": "available" if PAYROLL_STATUS_ORDER.index(run.status) >= PAYROLL_STATUS_ORDER.index(PayrollStatus.APPROVED) else "pending",
        })
    return reports


def _get_report_run(db: Session, report_id: int, organization_id: int = None):
    """Fetch the PayrollRun for a report, raising if not found."""
    from app.core.exceptions import NotFoundException
    q = db.query(PayrollRun).filter(PayrollRun.id == report_id)
    if organization_id is not None:
        q = q.filter(PayrollRun.organization_id == organization_id)
    run = q.first()
    if not run:
        raise NotFoundException("Payroll report", report_id)
    return run


# Per-jurisdiction statutory/contribution columns for the Payroll Register
# PDF — (header, PayslipItem field, width_mm). Field choices mirror the same
# per-country reuse already established for generate_payslip_pdf_bytes's
# income_tax_labels/pf_esi_labels dicts (e.g. Germany's pension/combined
# social-insurance fields reuse pf/esi) — so the register and the payslip
# never disagree about which underlying column backs which country's
# statutory line.
# Fields not computed for a country (e.g. professional_tax reused as
# Canada's "Provincial Tax", pending real provincial tax calculation)
# render as 0 — same field-reuse-over-new-columns approach used throughout
# this module. US previously reused "tds" (the COMBINED federal+state+local
# figure) mislabeled as "Fed. Tax", and "professional_tax" (always 0 for a
# US employee — that's India's field) mislabeled as "State Tax" — now that
# federal_income_tax/state_income_tax/local_tax are real, separately-
# computed PayslipItem columns, US reads its own dedicated fields instead.
_STATUTORY_COLUMNS_BY_COUNTRY = {
    "IN": [("PF", "pf", 13), ("ESI", "esi", 11), ("Prof. Tax", "professional_tax", 12), ("TDS", "tds", 13)],
    "US": [("Fed. Tax", "federal_income_tax", 13), ("State Tax", "state_income_tax", 12), ("Local Tax", "local_tax", 12), ("Soc. Security", "social_security", 16), ("Medicare", "medicare", 13)],
    "UK": [("PAYE", "tds", 13), ("Nat'l Insurance", "ni_employee", 19)],
    "AU": [("PAYG", "tds", 13), ("Superannuation", "employer_pension", 19)],
    "DE": [("Income Tax", "tds", 15), ("Pension Ins.", "pf", 15), ("Social Ins.", "esi", 15)],
    "CA": [("CPP", "social_security", 12), ("EI", "esi", 10), ("Fed. Tax", "tds", 14), ("Prov. Tax", "professional_tax", 14)],
}
_DEFAULT_STATUTORY_COLUMNS = [("Income Tax", "tds", 15)]


def generate_report_pdf_bytes(db: Session, report_id: int, organization_id: int = None) -> bytes:
    """Generate a production-level PDF payroll register report.

    Layout (Landscape A4):
      1. Header bar  – Company name, pay period, pay date, status
      2. KPI cards   – Gross, Deductions, Employer Contributions, Net Payable
      3. Employee breakdown table (16 columns) with totals row
      4. Sign-off block – HR Manager & Finance Director signature lines
    """
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as pdf_canvas

    import io

    run = _get_report_run(db, report_id, organization_id)
    items = run.payslip_items or []

    # ── Currency helpers ──
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first() if organization_id else None
    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    # Use the org's explicit currency override if set, otherwise derive
    # from the jurisdiction.
    org_currency_code = None
    if organization_id:
        from app.modules.organizations.models import Organization
        org_row = db.query(Organization).filter(Organization.id == organization_id).first()
        org_currency_code = org_row.currency if org_row else None
    sym = _get_currency_symbol(org_currency_code or country)

    def fmt(val):
        v = float(val or 0)
        return f"{sym} {v:,.2f}"

    # ── Company name ──
    org_name = "—"
    if organization_id is not None:
        from app.modules.organizations.models import Organization
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if org:
            org_name = org.organization_name

    # ── Canvas setup (Landscape A4) ──
    buf = io.BytesIO()
    page_w, page_h = landscape(A4)
    c = pdf_canvas.Canvas(buf, pagesize=landscape(A4))
    width, height = page_w, page_h

    # ── Font setup: register a Unicode-capable font so non-ASCII currency
    # symbols (₹ etc.) actually render instead of silently vanishing under
    # base-14 Helvetica's WinAnsi encoding — same helper the payslip PDF
    # generator already uses. ──
    base_font = _register_rupee_font(c)
    F = base_font or "Helvetica"
    FB = f"{base_font}-Bold" if base_font else "Helvetica-Bold"

    def _draw_col_separators(cx, y_top, h, color=None):
        """Thin vertical rules between every column, for the bordered-grid
        look — drawn per row/header/totals block so it naturally survives
        page breaks without needing cross-page position tracking."""
        c.setStrokeColor(color or slate_200)
        c.setLineWidth(0.3)
        for x in cx:
            c.line(x, y_top, x, y_top - h)

    # ── Palette ──
    teal        = colors.HexColor("#0D9488")
    teal_dark   = colors.HexColor("#0F766E")
    teal_light  = colors.HexColor("#E8F7F5")
    slate_50    = colors.HexColor("#F8FAFC")
    slate_100   = colors.HexColor("#F1F5F9")
    slate_200   = colors.HexColor("#E2E8F0")
    slate_400   = colors.HexColor("#94A3B8")
    slate_600   = colors.HexColor("#475569")
    slate_800   = colors.HexColor("#1E293B")
    white       = colors.white

    margin_l  = 18 * mm
    margin_r  = width - 18 * mm
    content_w = margin_r - margin_l
    # Top margin must leave real, visible padding ABOVE the header bar
    # itself (not just clear the text inside it) — the bar's top edge sits
    # at (y - 5mm + bar_h) = y + 22mm, so y must be low enough that this
    # stays comfortably under the page's physical top edge, or the banner
    # renders flush against the page with its rounded corners clipped off.
    y = height - 28 * mm

    # ════════════════════════════════════════════════════════════════════
    # 1. HEADER BAR
    # ════════════════════════════════════════════════════════════════════
    bar_h = 27 * mm
    c.setFillColor(teal)
    c.roundRect(margin_l, y - 5 * mm, content_w, bar_h, 5, fill=True, stroke=False)

    c.setFillColor(white)
    c.setFont(FB, 20)
    c.drawString(margin_l + 7 * mm, y + 9 * mm, "PAYROLL REGISTER")
    c.setFont(F, 8.5)
    c.drawString(margin_l + 7 * mm, y + 3.5 * mm, "Employee-wise Salary & Statutory Breakdown")

    c.setFont(FB, 9.5)
    c.drawRightString(margin_r - 7 * mm, y + 12 * mm, org_name)
    c.setFont(F, 8)
    c.drawRightString(margin_r - 7 * mm, y + 6.5 * mm, f"Pay Period: {run.period_label}")
    c.drawRightString(margin_r - 7 * mm, y + 2 * mm, f"Pay Date: {run.pay_date}   |   Status: {run.status}")

    y -= bar_h - 2 * mm

    # ════════════════════════════════════════════════════════════════════
    # 2. KPI SUMMARY CARDS
    # ════════════════════════════════════════════════════════════════════
    y -= 5 * mm
    card_h  = 20 * mm
    card_gap = 4 * mm
    kpis = [
        ("Total Gross Pay",        fmt(run.total_gross),               teal),
        ("Total Deductions",       fmt(run.total_deductions),          colors.HexColor("#EF4444")),
        ("Employer Contributions", fmt(run.total_employer_contribution), colors.HexColor("#F59E0B")),
        ("Net Payable",            fmt(run.total_net),                  teal_dark),
    ]
    card_w = (content_w - 3 * card_gap) / 4
    for i, (label, value, accent) in enumerate(kpis):
        cx = margin_l + i * (card_w + card_gap)
        # card background + border for clearer separation from the page
        c.setFillColor(slate_50)
        c.roundRect(cx, y - card_h + 4 * mm, card_w, card_h, 3, fill=True, stroke=False)
        c.setStrokeColor(slate_200)
        c.setLineWidth(0.4)
        c.roundRect(cx, y - card_h + 4 * mm, card_w, card_h, 3, fill=False, stroke=True)
        # accent stripe
        c.setFillColor(accent)
        c.roundRect(cx, y - card_h + 4 * mm, 3, card_h, 1.5, fill=True, stroke=False)
        # label
        c.setFillColor(slate_600)
        c.setFont(FB, 7)
        c.drawString(cx + 6 * mm, y - 0.5 * mm, label.upper())
        # value
        c.setFillColor(slate_800)
        c.setFont(FB, 13)
        c.drawString(cx + 6 * mm, y - 7.5 * mm, value)
        # employee count on first card — always the actual rendered row
        # count, never the (potentially stale) stored run.employee_count.
        if i == 0:
            c.setFillColor(slate_400)
            c.setFont(F, 6.5)
            c.drawString(cx + 6 * mm, y - 13 * mm, f"{len(items)} employees")

    y -= card_h + 5 * mm

    # ════════════════════════════════════════════════════════════════════
    # 3. EMPLOYEE BREAKDOWN TABLE
    # ════════════════════════════════════════════════════════════════════
    # Section title, with a short accent underline for clearer hierarchy
    # between the KPI cards above and the table below.
    c.setFillColor(slate_800)
    c.setFont(FB, 10.5)
    c.drawString(margin_l, y, "Employee Breakdown")
    c.setStrokeColor(teal)
    c.setLineWidth(1.2)
    c.line(margin_l, y - 2 * mm, margin_l + 22 * mm, y - 2 * mm)
    # Enough clearance that the table's own teal header bar (drawn from
    # y - 1mm up to +hdr_h, i.e. ~5.5mm above whatever y is passed in) can't
    # collide with the title/underline above it — 5mm here left them
    # overlapping by ~2.5mm.
    y -= 11 * mm

    if items:
        # total_deductions is always attendance_deduction (LOP) plus exactly
        # these 7 employee-side statutory fields (see StandardStrategy.calculate
        # in engine/standard.py) — unused ones are simply 0 for a given
        # country, so subtracting all 7 universally (rather than only the
        # subset a given jurisdiction renders as its own columns) always
        # isolates just the LOP/attendance deduction, for every jurisdiction.
        def _other_deductions(it):
            total_ded = Decimal(str(it.total_deductions or 0))
            employee_statutory = sum(
                (Decimal(str(getattr(it, f, 0) or 0)) for f in
                 ("pf", "esi", "professional_tax", "tds", "social_security", "medicare", "ni_employee")),
                Decimal("0"),
            )
            return total_ded - employee_statutory

        statutory_cols = _STATUTORY_COLUMNS_BY_COUNTRY.get(country, _DEFAULT_STATUTORY_COLUMNS)

        # Column definitions: (header, width_mm, getter, align).
        # align: "L" left (identity columns), "C" center (day counts),
        # "R" right (all monetary values).
        col_defs = [
            ("ID",         10, lambda it: str(it.employee_id or "-"), "L"),
            ("Employee",   32, lambda it: str(it.employee_name or "-")[:28], "L"),
            ("Paid Days",  12, lambda it: f"{float(it.payable_days or 0):.1f}", "C"),
            ("LOP Days",   12, lambda it: f"{max(float(it.total_working_days or 0) - float(it.payable_days or 0), 0):.1f}", "C"),
            ("Basic",      17, lambda it: fmt(it.basic_salary), "R"),
            ("HRA",        15, lambda it: fmt(it.hra), "R"),
            ("Spl. Allow", 17, lambda it: fmt(it.special_allowance), "R"),
            ("Overtime",   13, lambda it: fmt(it.overtime), "R"),
            ("Addl. Comp", 15, lambda it: fmt(it.additional_compensation), "R"),
            ("Gross",      17, lambda it: fmt(it.gross_pay), "R"),
            *[
                (label, width, (lambda it, f=field: fmt(getattr(it, f, 0))), "R")
                for label, field, width in statutory_cols
            ],
            ("Other Ded.", 15, lambda it: fmt(_other_deductions(it)), "R"),
            ("Net Salary", 19, lambda it: fmt(it.net_pay), "R"),
        ]

        col_x = [margin_l]
        for _, w, _, _ in col_defs:
            col_x.append(col_x[-1] + w * mm)

        row_h   = 5.6 * mm
        hdr_h   = 6.5 * mm
        bottom_limit = 38 * mm  # reserve space for sign-off block

        def _draw_table_header(c, cx, y_pos):
            """Draw the header row with teal background."""
            c.setFillColor(teal)
            c.roundRect(margin_l, y_pos - 1 * mm, content_w, hdr_h, 2, fill=True, stroke=False)
            c.setFillColor(white)
            c.setFont(FB, 6.2)
            for i, (hdr, _, _, align) in enumerate(col_defs):
                if align == "R":
                    c.drawRightString(cx[i + 1] - 1.5 * mm, y_pos + 1.3 * mm, hdr)
                elif align == "C":
                    c.drawCentredString((cx[i] + cx[i + 1]) / 2, y_pos + 1.3 * mm, hdr)
                else:
                    c.drawString(cx[i] + 1.5 * mm, y_pos + 1.3 * mm, hdr)
            _draw_col_separators(cx, y_pos - 1 * mm + hdr_h, hdr_h, color=colors.HexColor("#0B5F58"))
            return y_pos - hdr_h - 1 * mm

        y = _draw_table_header(c, col_x, y)

        # Data rows
        c.setFont(F, 6.0)
        row_idx = 0
        for item in items:
            if y < bottom_limit:
                c.showPage()
                y = height - 18 * mm
                y = _draw_table_header(c, col_x, y)
                c.setFont(F, 6.0)

            # Alternating row background
            if row_idx % 2 == 0:
                c.setFillColor(slate_50)
                c.rect(margin_l, y - 1.5 * mm, content_w, row_h, fill=True, stroke=False)

            c.setFillColor(slate_800)
            for i, (_, _, getter, align) in enumerate(col_defs):
                text = getter(item)
                if align == "R":
                    c.drawRightString(col_x[i + 1] - 1.5 * mm, y, text)
                elif align == "C":
                    c.drawCentredString((col_x[i] + col_x[i + 1]) / 2, y, text)
                else:
                    c.drawString(col_x[i] + 1.5 * mm, y, text)

            _draw_col_separators(col_x, y - 1.5 * mm + row_h, row_h)
            y -= row_h
            row_idx += 1

        # ── Totals / summary box — bordered and set apart from the data
        # rows with a heavier top rule, so it reads as a distinct summary
        # rather than just another table row. ──
        y -= 1 * mm
        c.setStrokeColor(teal)
        c.setLineWidth(1)
        c.line(margin_l, y - 1.5 * mm + row_h + 1 * mm, margin_r, y - 1.5 * mm + row_h + 1 * mm)
        c.setFillColor(slate_100)
        c.rect(margin_l, y - 1.5 * mm, content_w, row_h + 1 * mm, fill=True, stroke=False)
        c.setStrokeColor(slate_400)
        c.setLineWidth(0.4)
        c.rect(margin_l, y - 1.5 * mm, content_w, row_h + 1 * mm, fill=False, stroke=True)
        _draw_col_separators(col_x, y - 1.5 * mm + row_h + 1 * mm, row_h + 1 * mm, color=slate_400)
        c.setFillColor(slate_800)
        c.setFont(FB, 6.2)
        c.drawString(col_x[0] + 1.5 * mm, y, "TOTALS")

        # Summed in Decimal (matching _recompute_run_aggregates) rather than
        # float, so this row can't drift by a cent from the KPI cards above
        # on larger runs. Keyed by column label — not position — so it
        # can't silently misalign if columns are reordered later.
        def _dsum(attr):
            return sum((Decimal(str(getattr(it, attr, 0) or 0)) for it in items), Decimal("0"))

        total_other_ded = sum((_other_deductions(it) for it in items), Decimal("0"))

        totals_by_label = {
            "Basic": _dsum("basic_salary"), "HRA": _dsum("hra"), "Spl. Allow": _dsum("special_allowance"),
            "Overtime": _dsum("overtime"), "Addl. Comp": _dsum("additional_compensation"), "Gross": _dsum("gross_pay"),
            "Other Ded.": total_other_ded, "Net Salary": _dsum("net_pay"),
        }
        for label, field, _width in statutory_cols:
            totals_by_label[label] = _dsum(field)
        for i, (hdr, _, _, _align) in enumerate(col_defs):
            if hdr in totals_by_label:
                c.drawRightString(col_x[i + 1] - 1.5 * mm, y, fmt(totals_by_label[hdr]))

        y -= row_h + 4 * mm
    else:
        c.setFont(F, 8)
        c.setFillColor(slate_600)
        c.drawString(margin_l, y, "No payslip data available for this run.")
        y -= 10 * mm

    # ════════════════════════════════════════════════════════════════════
    # 4. SIGN-OFF BLOCK
    # ════════════════════════════════════════════════════════════════════
    # Always render at the bottom of the last page
    sign_y = 28 * mm
    line_w = 55 * mm

    c.setStrokeColor(slate_200)
    c.setLineWidth(0.5)
    c.line(margin_l, sign_y + 14 * mm, margin_r, sign_y + 14 * mm)

    c.setFillColor(slate_800)
    c.setFont(FB, 7)
    c.drawString(margin_l, sign_y + 8 * mm, "SIGN-OFF")
    c.setFont(F, 6)
    c.setFillColor(slate_600)
    c.drawString(margin_l, sign_y + 3 * mm,
                 f"Generated on {datetime.utcnow().strftime('%b %d, %Y at %H:%M UTC')}   |   "
                 f"Run ID: {run.id}   |   Period: {run.period_label}")

    # HR Manager signature
    c.setStrokeColor(slate_400)
    c.setLineWidth(0.4)
    c.line(margin_l, sign_y - 4 * mm, margin_l + line_w, sign_y - 4 * mm)
    c.setFillColor(slate_600)
    c.setFont(F, 6)
    c.drawString(margin_l, sign_y - 9 * mm, "HR Manager")
    c.setFont(F, 5.5)
    c.drawString(margin_l, sign_y - 13 * mm, "Signature & Date")

    # Finance Director signature
    sig2_x = margin_l + content_w / 2 + 10 * mm
    c.line(sig2_x, sign_y - 4 * mm, sig2_x + line_w, sign_y - 4 * mm)
    c.setFillColor(slate_600)
    c.setFont(F, 6)
    c.drawString(sig2_x, sign_y - 9 * mm, "Finance Director")
    c.setFont(F, 5.5)
    c.drawString(sig2_x, sign_y - 13 * mm, "Signature & Date")

    # ── Footer ──
    c.setFillColor(slate_400)
    c.setFont(F, 5)
    c.drawCentredString(width / 2, 6 * mm, "Confidential — For Internal Use Only")

    c.save()
    return buf.getvalue()


def generate_report_csv_bytes(db: Session, report_id: int, organization_id: int = None) -> bytes:
    """Generate a CSV summary of a payroll run report — statutory columns
    match the jurisdiction-specific set used by generate_report_pdf_bytes
    (same _STATUTORY_COLUMNS_BY_COUNTRY mapping) so the two exports never
    disagree about which columns represent a given country's payroll."""
    import csv
    import io

    run = _get_report_run(db, report_id, organization_id)
    items = run.payslip_items or []

    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first() if organization_id else None
    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    statutory_cols = _STATUTORY_COLUMNS_BY_COUNTRY.get(country, _DEFAULT_STATUTORY_COLUMNS)

    def _other_deductions(it):
        total_ded = Decimal(str(it.total_deductions or 0))
        employee_statutory = sum(
            (Decimal(str(getattr(it, f, 0) or 0)) for f in
             ("pf", "esi", "professional_tax", "tds", "social_security", "medicare", "ni_employee")),
            Decimal("0"),
        )
        return total_ded - employee_statutory

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["Employee", "Department", "Gross Pay"]
        + [label for label, _field, _width in statutory_cols]
        + ["Other Deductions", "Net Pay"]
    )
    for item in items:
        writer.writerow(
            [item.employee_name, item.department or "", float(item.gross_pay or 0)]
            + [float(getattr(item, field, 0) or 0) for _label, field, _width in statutory_cols]
            + [float(_other_deductions(item)), float(item.net_pay or 0)]
        )
    return buf.getvalue().encode("utf-8")


# ── Dashboard ──────────────────────────────────────────────────────────

def get_dashboard_summary(db: Session, organization_id: int = None, year: int = None, month: int = None) -> dict:
    employees_query = db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == organization_id)

    headcount = employees_query.count()
    active_count = employees_query.filter(PayrollEmployee.status == EmployeeStatus.ACTIVE).count()
    on_leave_count = employees_query.filter(PayrollEmployee.status == EmployeeStatus.ON_LEAVE).count()
    inactive_count = employees_query.filter(PayrollEmployee.status == EmployeeStatus.INACTIVE).count()

    now = datetime.utcnow()

    def _month_sum(field, start, end=None):
        q = db.query(sa_func.coalesce(sa_func.sum(field), 0)).filter(PayrollRun.period_start >= start)
        if end:
            q = q.filter(PayrollRun.period_start < end)
        if organization_id is not None:
            q = q.filter(PayrollRun.organization_id == organization_id)
        return q.scalar() or Decimal("0")

    def _pending_count(start, end):
        pq = db.query(PayrollRun).filter(
            PayrollRun.period_start >= start,
            PayrollRun.period_start < end,
            PayrollRun.status.in_([PayrollStatus.REVIEW, PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED]),
        )
        pq = _apply_org_filter(pq, PayrollRun, organization_id)
        return pq.count()

    if year and month:
        this_month_start = date(year, month, 1)
        if month == 12:
            this_month_end = date(year + 1, 1, 1)
        else:
            this_month_end = date(year, month + 1, 1)
        if month == 1:
            prev_month_start = date(year - 1, 12, 1)
        else:
            prev_month_start = date(year, month - 1, 1)

        total_net = _month_sum(PayrollRun.total_net, this_month_start, this_month_end)
        total_gross = _month_sum(PayrollRun.total_gross, this_month_start, this_month_end)
        total_taxes = _month_sum(PayrollRun.total_taxes, this_month_start, this_month_end)
        prev_net = _month_sum(PayrollRun.total_net, prev_month_start, this_month_start)
        pending_approvals = _pending_count(this_month_start, this_month_end)

        change_pct = None
        if prev_net and prev_net > 0:
            change_pct = float(_round2((total_net - prev_net) / prev_net * 100))
    else:
        earliest_q = db.query(sa_func.min(PayrollRun.period_start))
        if organization_id is not None:
            earliest_q = earliest_q.filter(PayrollRun.organization_id == organization_id)
        earliest_date = earliest_q.scalar()

        if earliest_date:
            all_start = date(earliest_date.year, earliest_date.month, 1)
        else:
            all_start = date(now.year, now.month, 1)
        all_end = date(now.year, now.month + 1, 1) if now.month < 12 else date(now.year + 1, 1, 1)

        total_net = _month_sum(PayrollRun.total_net, all_start, all_end)
        total_gross = _month_sum(PayrollRun.total_gross, all_start, all_end)
        total_taxes = _month_sum(PayrollRun.total_taxes, all_start, all_end)
        pending_approvals = _pending_count(all_start, all_end)
        change_pct = None

    return {
        "totalPayrollCost": total_net,
        "totalPayrollCostChangePct": change_pct,
        "totalGross": total_gross,
        "totalTaxes": total_taxes,
        "totalAttendanceDeduction": _compute_attendance_deductions(db, organization_id, year, month),
        "totalNet": total_net,
        "headcount": headcount,
        "activeCount": active_count,
        "onLeaveCount": on_leave_count,
        "inactiveCount": inactive_count,
        "pendingApprovals": pending_approvals,
    }


def _compute_attendance_deductions(db: Session, organization_id: int = None, year: int = None, month: int = None) -> Decimal:
    """Compute total attendance deductions from payslip proration loss.

    Summed entirely at the SQL level (a per-row CASE/arithmetic expression
    aggregated with SUM) instead of pulling every PayslipItem row into Python
    and looping — this ran on every Dashboard poll tick (every 30s per open
    tab) and, with no month filter ("All Months"), scaled linearly with the
    total number of payslips ever generated.

    full_x - x, where full_x = x / (payable_days / total_working_days),
    algebraically simplifies to x * (total_working_days - payable_days) / payable_days
    — avoids computing an intermediate proration_factor per row.
    """
    gross_components = (
        sa_func.coalesce(PayslipItem.basic_salary, 0)
        + sa_func.coalesce(PayslipItem.hra, 0)
        + sa_func.coalesce(PayslipItem.special_allowance, 0)
    )
    att_ded_expr = case(
        (
            and_(
                PayslipItem.payable_days.isnot(None),
                PayslipItem.total_working_days.isnot(None),
                PayslipItem.total_working_days > 0,
                PayslipItem.payable_days > 0,
                PayslipItem.payable_days < PayslipItem.total_working_days,
            ),
            gross_components * (PayslipItem.total_working_days - PayslipItem.payable_days) / PayslipItem.payable_days,
        ),
        else_=0,
    )
    q = db.query(sa_func.coalesce(sa_func.sum(att_ded_expr), 0)).select_from(PayslipItem).join(
        PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id
    )
    q = _apply_org_filter(q, PayslipItem, organization_id)
    if year and month:
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1)
        else:
            month_end = date(year, month + 1, 1)
        q = q.filter(PayrollRun.period_start >= month_start, PayrollRun.period_start < month_end)
    total = q.scalar() or Decimal("0")
    return _round2(Decimal(str(total)))


def get_dashboard_trend(db: Session, organization_id: int = None, months: int = 6, year: int = None, month: int = None) -> List[dict]:
    if year and month:
        start_m = month - months + 1
        start_y = year
        while start_m <= 0:
            start_m += 12
            start_y -= 1
        end_m = month + 1
        end_y = year
        while end_m > 12:
            end_m -= 12
            end_y += 1
        window_start = date(start_y, start_m, 1)
        window_end = date(end_y, end_m, 1)
    else:
        now = datetime.utcnow()
        earliest_q = db.query(sa_func.min(PayrollRun.period_start))
        if organization_id is not None:
            earliest_q = earliest_q.filter(PayrollRun.organization_id == organization_id)
        earliest_date = earliest_q.scalar()
        if earliest_date:
            window_start = date(earliest_date.year, earliest_date.month, 1)
        else:
            window_start = date(now.year, now.month, 1)
        window_end = date(now.year, now.month + 1, 1) if now.month < 12 else date(now.year + 1, 1, 1)

    query = db.query(
        sa_func.extract("year", PayrollRun.period_start).label("y"),
        sa_func.extract("month", PayrollRun.period_start).label("m"),
        sa_func.coalesce(sa_func.sum(PayrollRun.total_gross), 0).label("gross"),
        sa_func.coalesce(sa_func.sum(PayrollRun.total_net), 0).label("net"),
    )
    query = _apply_org_filter(query, PayrollRun, organization_id)
    query = query.filter(PayrollRun.period_start >= window_start, PayrollRun.period_start < window_end)
    rows = query.group_by(
        sa_func.extract("year", PayrollRun.period_start),
        sa_func.extract("month", PayrollRun.period_start),
    ).order_by(
        sa_func.extract("year", PayrollRun.period_start),
        sa_func.extract("month", PayrollRun.period_start),
    ).all()

    buckets = {(int(r.y), int(r.m)): {"gross": Decimal(str(r.gross)), "net": Decimal(str(r.net))} for r in rows}

    ordered_keys = sorted(buckets.keys())

    return [
        {
            "month": f"{month_name[m][:3]} {y}",
            "gross": buckets[(y, m)]["gross"],
            "net": buckets[(y, m)]["net"],
        }
        for (y, m) in ordered_keys
    ]


def get_recent_activity(db: Session, organization_id: int = None, limit: int = 20, year: int = None, month: int = None) -> List[dict]:
    query = db.query(PayrollActivityLog)
    query = _apply_org_filter(query, PayrollActivityLog, organization_id)
    if year and month:
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1)
        else:
            month_end = date(year, month + 1, 1)
        query = query.filter(PayrollActivityLog.created_at >= month_start, PayrollActivityLog.created_at < month_end)
    rows = query.order_by(PayrollActivityLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(row.id),
            "description": row.description,
            "timestamp": row.created_at,
            "status": row.status,
        }
        for row in rows
    ]


def get_dashboard_breakdowns(db: Session, organization_id: int = None, year: int = None, month: int = None) -> dict:
    """Return department, pay-type, and deduction breakdowns from payslip data.

    All sums are computed at the SQL level (GROUP BY / SUM over 2 queries)
    instead of pulling every PayslipItem row into Python and looping over it
    ~13 times — this ran on every Dashboard poll tick (every 30s per open
    tab) and, with no month filter ("All Months"), scaled linearly with the
    total number of payslips ever generated.
    """
    def _scoped(query):
        query = _apply_org_filter(query, PayslipItem, organization_id)
        if year and month:
            month_start = date(year, month, 1)
            month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            query = query.filter(PayrollRun.period_start >= month_start, PayrollRun.period_start < month_end)
        return query

    def _joined(cols):
        return db.query(*cols).select_from(PayslipItem).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)

    # Department breakdown
    dept_col = sa_func.coalesce(PayslipItem.department, "Unassigned")
    dept_rows = _scoped(
        _joined([dept_col.label("dept"), sa_func.coalesce(sa_func.sum(PayslipItem.gross_pay), 0).label("total")])
    ).group_by(dept_col).all()
    dept_map = {row.dept: Decimal(str(row.total)) for row in dept_rows}
    total_gross_all = sum(dept_map.values(), Decimal("0")) or Decimal("1")
    by_department = sorted(
        [{"name": k, "value": round(float(v / total_gross_all * 100), 1), "amount": float(v)}
         for k, v in dept_map.items()],
        key=lambda x: x["value"], reverse=True,
    )

    # Pay-type and deduction sums — a single aggregate row, no per-row loop
    sum_cols = [
        "basic_salary", "hra", "special_allowance", "overtime", "additional_compensation",
        "attendance_deduction", "tds", "pf", "esi", "professional_tax",
        "social_security", "medicare", "ni_employee",
        "federal_income_tax", "state_income_tax", "local_tax",
    ]
    agg_row = _scoped(
        _joined([sa_func.coalesce(sa_func.sum(getattr(PayslipItem, c)), 0).label(c) for c in sum_cols])
    ).first()
    totals = (
        {c: Decimal(str(getattr(agg_row, c))) for c in sum_cols}
        if agg_row else {c: Decimal("0") for c in sum_cols}
    )

    pay_types = [
        {"name": "Basic Salary", "value": float(totals["basic_salary"])},
        {"name": "HRA", "value": float(totals["hra"])},
        {"name": "Special Allowance", "value": float(totals["special_allowance"])},
    ]
    if totals["overtime"] > 0:
        pay_types.append({"name": "Overtime", "value": float(totals["overtime"])})
    if totals["additional_compensation"] > 0:
        pay_types.append({"name": "Additional", "value": float(totals["additional_compensation"])})

    # Attendance deductions — use the stored attendance_deduction column
    total_att_ded = totals["attendance_deduction"]
    attendance_deductions = []
    if total_att_ded > 0:
        attendance_deductions.append({"name": "LOP Deduction", "total": float(total_att_ded)})

    # Also include statutory deductions for reference. Every jurisdiction routes
    # its withholding through the same fields (tds, pf, esi — India-named
    # historically), so label them per the company's jurisdiction country, the
    # same way generate_payslip_pdf_bytes() does, to avoid showing e.g. a
    # German company's Lohnsteuer/pension/social-insurance totals under Indian
    # statutory names.
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first() if organization_id else None
    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    income_tax_labels = {
        "IN": "TDS", "US": "Federal Withholding", "UK": "PAYE",
        "AU": "PAYG", "DE": "Lohnsteuer", "CA": "Federal Tax",
    }
    pf_esi_labels = {
        "DE": {"pf": "Pension Insurance", "esi": "Social Insurance (Health / Unemployment / Care)"},
        "CA": {"esi": "Employment Insurance (EI)"},
    }.get(country, {})
    # US: federal/state/local shown as three separate slices instead of one
    # combined "Federal Withholding" total — falls back to the combined
    # `tds` figure when the split is all-zero (a US org with no payslips
    # generated under this feature yet), same rule generate_payslip_pdf_bytes
    # and jurisdictionLabels.js's getIncomeTaxLines already use.
    us_split_total = totals["federal_income_tax"] + totals["state_income_tax"] + totals["local_tax"]
    if country == "US" and us_split_total > 0:
        income_tax_fields = [
            ("Federal Withholding", "federal_income_tax"),
            ("State Tax", "state_income_tax"),
            ("Local Tax", "local_tax"),
        ]
    else:
        income_tax_fields = [(income_tax_labels.get(country, "TDS"), "tds")]
    deduction_fields = [
        *income_tax_fields,
        (pf_esi_labels.get("pf", "Provident Fund (PF)"), "pf"),
        (pf_esi_labels.get("esi", "Employee State Insurance (ESI)"), "esi"),
        ("Professional Tax", "professional_tax"),
        ("Social Security", "social_security"),
        ("Medicare", "medicare"),
        ("National Insurance", "ni_employee"),
    ]
    stat_deductions = []
    total_stat_ded = Decimal("0")
    for label, field in deduction_fields:
        total_val = totals[field]
        if total_val > 0:
            stat_deductions.append({"name": label, "total": float(total_val)})
            total_stat_ded += total_val
    
    # Combine: attendance deductions first, then statutory
    all_deductions = attendance_deductions + stat_deductions
    total_ded_all = total_att_ded + total_stat_ded
    for d in all_deductions:
        d["pct"] = round(d["total"] / float(total_ded_all or 1) * 100, 1)

    return {
        "byDepartment": by_department,
        "payTypes": pay_types,
        "deductions": all_deductions,
    }


# ── Leave Allocations ─────────────────────────────────────────────────────

def _enrich_leave_allocation(db: Session, record: PayrollLeaveAllocation, organization_id: int) -> dict:
    emp = _apply_employee_filter(
        db.query(PayrollEmployee).filter(PayrollEmployee.id == record.employee_id),
        organization_id,
    ).first()
    return {
        "id": record.id,
        "employeeId": record.employee_id,
        "employeeName": emp.name if emp else None,
        "department": emp.department if emp else None,
        "leaveBalances": record.leave_balances or {},
        "periodLabel": record.period_label,
        "notes": record.notes,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
    }


def bulk_save_leaves(db: Session, data, organization_id: int) -> List[dict]:
    results = []
    for item in data.records:
        payload = item.model_dump()
        employee_id = payload.pop("employeeId")
        leave_balances = payload.pop("leaveBalances", None)
        mapped = {
            "leave_balances": leave_balances,
            "period_label": payload.pop("periodLabel", None),
            "notes": payload.pop("notes", None),
        }

        existing = db.query(PayrollLeaveAllocation).filter(
            PayrollLeaveAllocation.organization_id == organization_id,
            PayrollLeaveAllocation.employee_id == employee_id,
        ).first()

        if existing:
            for field, value in mapped.items():
                if value is not None or field != "leave_balances":
                    setattr(existing, field, value)
            record = existing
        else:
            record = PayrollLeaveAllocation(
                organization_id=organization_id,
                employee_id=employee_id,
                **mapped,
            )
            db.add(record)

        results.append(record)

    db.commit()
    for r in results:
        db.refresh(r)
    return [_enrich_leave_allocation(db, r, organization_id) for r in results]


def get_leave_allocations(
    db: Session,
    organization_id: int,
    *,
    employee_id: Optional[int] = None,
) -> List[dict]:
    _backfill_orphaned_leave_syncs(db, organization_id)
    _dedupe_auto_created_leave_requests(db, organization_id)
    _recompute_leave_balances_used(db, organization_id)

    query = db.query(
        PayrollLeaveAllocation,
        PayrollEmployee.name,
        PayrollEmployee.department,
    ).outerjoin(
        PayrollEmployee,
        (PayrollLeaveAllocation.employee_id == PayrollEmployee.id) &
        (PayrollEmployee.organization_id == organization_id)
    ).filter(
        PayrollLeaveAllocation.organization_id == organization_id
    )
    if employee_id:
        query = query.filter(PayrollLeaveAllocation.employee_id == employee_id)

    rows = query.all()
    return [
        {
            "id": record.id,
            "employeeId": record.employee_id,
            "employeeName": name,
            "department": department,
            "leaveBalances": record.leave_balances or {},
            "periodLabel": record.period_label,
            "notes": record.notes,
            "createdAt": record.created_at,
            "updatedAt": record.updated_at,
        }
        for record, name, department in rows
    ]


def reset_leave_allocations(db: Session, organization_id: int) -> dict:
    """Set every employee's leave balances to empty and delete leave-only attendance records."""
    leaves_reset = db.query(PayrollLeaveAllocation).filter(
        PayrollLeaveAllocation.organization_id == organization_id,
    ).update({"leave_balances": {}}, synchronize_session=False)

    attendance_deleted = db.query(PayrollAttendanceRecord).filter(
        PayrollAttendanceRecord.organization_id == organization_id,
        PayrollAttendanceRecord.status == "leave",
    ).delete(synchronize_session=False)

    db.commit()

    try:
        log_activity(db, organization_id, f"Leave allocations reset for {leaves_reset} employees; {attendance_deleted} leave attendance record(s) cleared.", ActivityStatus.INFO)
    except Exception:
        pass

    return {"leavesReset": leaves_reset, "attendanceCleared": attendance_deleted}


# ── Leave Requests ─────────────────────────────────────────────────────

def _enrich_leave_request(db: Session, record: PayrollLeaveRequest, organization_id: int) -> dict:
    emp = _apply_employee_filter(
        db.query(PayrollEmployee).filter(PayrollEmployee.id == record.employee_id),
        organization_id,
    ).first()
    linked_dates = [
        r.date for r in db.query(PayrollAttendanceRecord.date).filter(
            PayrollAttendanceRecord.leave_request_id == record.id,
        ).all()
    ]
    return {
        "id": record.id,
        "employeeId": record.employee_id,
        "employeeName": emp.name if emp else None,
        "department": emp.department if emp else None,
        "leaveType": record.leave_type,
        "startDate": record.start_date,
        "endDate": record.end_date,
        "days": record.days,
        "reason": record.reason,
        "status": record.status,
        "reviewedBy": record.reviewed_by,
        "reviewedAt": record.reviewed_at,
        "source": record.source,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "linkedAttendanceDates": [str(d) for d in sorted(linked_dates)],
        "isAutoCreated": record.reason == "Auto-created from attendance",
    }


def create_payroll_leave_request(db: Session, data, organization_id: int) -> dict:
    start = data.startDate if hasattr(data, "startDate") else data.start_date
    end = data.endDate if hasattr(data, "endDate") else data.end_date
    days = (end - start).days + 1

    record = PayrollLeaveRequest(
        organization_id=organization_id,
        employee_id=data.employeeId if hasattr(data, "employeeId") else data.employee_id,
        leave_type=data.leaveType if hasattr(data, "leaveType") else data.leave_type,
        start_date=start,
        end_date=end,
        days=max(1, days),
        reason=data.reason if hasattr(data, "reason") else None,
        status="pending",
        source=data.source if hasattr(data, "source") else "manual",
    )
    if organization_id is not None:
        from app.core.code_generation import generate_business_code
        record.request_code = generate_business_code(db, organization_id, "LV", PayrollLeaveRequest, "request_code")
    db.add(record)
    db.commit()
    db.refresh(record)

    try:
        log_activity(db, organization_id, f"Leave request submitted by employee {record.employee_id} ({record.leave_type}, {record.days}d).", ActivityStatus.INFO)
    except Exception:
        pass

    # No email is sent on submission — status emails (approved / rejected)
    # are sent by review_payroll_leave_request once an admin acts on the request.

    return _enrich_leave_request(db, record, organization_id)


def get_payroll_leave_requests(db: Session, organization_id: int, *, employee_id=None, status=None, leave_type=None) -> list:
    _backfill_orphaned_leave_syncs(db, organization_id)
    _dedupe_auto_created_leave_requests(db, organization_id)

    query = db.query(PayrollLeaveRequest).filter(
        PayrollLeaveRequest.organization_id == organization_id,
    )
    if employee_id:
        query = query.filter(PayrollLeaveRequest.employee_id == employee_id)
    if status:
        query = query.filter(PayrollLeaveRequest.status == status)
    if leave_type:
        query = query.filter(PayrollLeaveRequest.leave_type == leave_type)

    rows = query.order_by(PayrollLeaveRequest.created_at.desc()).all()
    return [_enrich_leave_request(db, r, organization_id) for r in rows]


def review_payroll_leave_request(db: Session, request_id: int, data, organization_id: int, reviewer_id: int) -> dict:
    record = db.query(PayrollLeaveRequest).filter(
        PayrollLeaveRequest.id == request_id,
        PayrollLeaveRequest.organization_id == organization_id,
    ).first()
    if not record:
        raise NotFoundException("PayrollLeaveRequest", request_id)

    prev_status = record.status
    new_status = data.status if hasattr(data, "status") else None

    if new_status and new_status in ("approved", "rejected"):
        record.status = new_status
        record.reviewed_by = reviewer_id
        record.reviewed_at = datetime.utcnow()

    # Update leave allocation balances when approved
    if record.status == "approved" and prev_status != "approved":
        _sync_leave_to_attendance(db, record, organization_id)
        alloc = db.query(PayrollLeaveAllocation).filter(
            PayrollLeaveAllocation.organization_id == organization_id,
            PayrollLeaveAllocation.employee_id == record.employee_id,
        ).first()
        if not alloc:
            alloc = PayrollLeaveAllocation(
                organization_id=organization_id,
                employee_id=record.employee_id,
                leave_balances={},
            )
            db.add(alloc)
            db.flush()
        balances = copy.deepcopy(alloc.leave_balances or {})
        lt = record.leave_type
        if lt not in balances:
            balances[lt] = {"used": 0, "total": 0}
        balances[lt]["used"] = balances[lt].get("used", 0) + record.days
        alloc.leave_balances = balances
        try:
            log_activity(db, organization_id,
                f"Leave request #{record.id} approved — attendance auto-created ({record.days}d).",
                ActivityStatus.INFO)
        except Exception:
            pass

    elif record.status == "rejected" and prev_status != "rejected":
        _remove_linked_attendance(db, record, organization_id)
        alloc = db.query(PayrollLeaveAllocation).filter(
            PayrollLeaveAllocation.organization_id == organization_id,
            PayrollLeaveAllocation.employee_id == record.employee_id,
        ).first()
        if alloc and prev_status == "approved":
            balances = copy.deepcopy(alloc.leave_balances or {})
            lt = record.leave_type
            if lt in balances:
                used = balances[lt].get("used", 0)
                balances[lt]["used"] = max(0, used - record.days)
                alloc.leave_balances = balances

    db.commit()
    db.refresh(record)

    try:
        log_activity(db, organization_id, f"Leave request #{record.id} {record.status} by admin ({record.days}d).", ActivityStatus.INFO)
    except Exception:
        pass

    # Best-effort status email — never blocks the review. Sent to the employee
    # only when their request actually transitions (approved / rejected).
    if prev_status != record.status and record.status in ("approved", "rejected"):
        try:
            employee = db.query(PayrollEmployee).filter(PayrollEmployee.id == record.employee_id).first()
            if employee and employee.email:
                from app.services.email_service import (
                    send_leave_request_approved_email,
                    send_leave_request_rejected_email,
                )
                sender = (
                    send_leave_request_approved_email
                    if record.status == "approved"
                    else send_leave_request_rejected_email
                )
                sender(
                    employee.email, employee.name,
                    record.leave_type, str(record.start_date), str(record.end_date),
                    record.days, record.request_code,
                    organization_id=organization_id, db=db,
                )
        except Exception as exc:
            import logging
            logging.getLogger("zoiko").warning(f"[payroll-mail] leave-request status email failed: {exc}")

    return _enrich_leave_request(db, record, organization_id)