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
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timedelta
from calendar import month_name

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func as sa_func, tuple_, or_, and_, case
from sqlalchemy.exc import IntegrityError

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
    StatutoryFilingCalendar,     EmployeeStatutoryProfile, PapAlgorithmAsset, GermanyHealthFund,
    GermanyContributionCeiling, GermanyPvConfiguration, GermanyPapRelease,
    GermanyElstamChangeListBatch, GermanyElstamImportAttempt, GermanyEarningTaxabilityRule,
    GermanyElsterCertificateConfig, GermanyElsterTransmission,
    GermanyHealthFundU1Tariff, GermanyOvertimeWorkRecord,
    GermanyOvertimePremiumCategory, GermanyOvertimeGrundlohnCap, GermanyOvertimeTimeSegment,
    GermanyOvertimeWageTaxResult, GermanyOvertimeSocialInsuranceResult,
    GermanyOvertimePremiumComponent, GermanyAccidentInsuranceProfile,
    GermanyChurchTaxException, PayrollYtdAccumulator, OrganizationYtdAccumulator,
    EmployeeEstablishment,
)
from app.modules.payroll.engine.germany_pap import production_gate as pap_production_gate
from app.modules.payroll.employee_validation import get_employee_validation_strategy, _STRATEGIES
from app.modules.payroll.schemas import (
    PayrollRunCreate, PayrollRunUpdate, PayslipItemCreate, CompanyDetailsUpdate,
    EmployeeCreate, EmployeeUpdate, BulkEmployeeItem, BulkEmployeeRequest,
    BulkDeleteRequest,
    AttendanceRecordCreate, BulkAttendanceRequest,
    JurisdictionPackUpsert, CanonicalTaxSlabUpsert, CanonicalContributionRateUpsert,
    EmployerTaxProfileUpsert, ReciprocityRuleUpsert, SourceArtifactCreate, LocalityRateUpsert,
    ReportTemplateUpsert, ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
    FilingCalendarUpsert,     EmployeeStatutoryProfileCreate, GermanyHealthFundCreate,
    GermanyContributionCeilingCreate, GermanyPvConfigurationCreate,
    GermanyElstamChangeListBatchCreate, GermanyElstamChangeListBatchStatusUpdate,
    GermanyEarningTaxabilityRuleCreate, GermanyHealthFundU1TariffCreate,
    GermanyOvertimeWorkRecordCreate,
)
from app.core.exceptions import NotFoundException, BadRequestException, GermanyPapGateBlockedException
from fastapi import HTTPException, status as http_status

# Sourced from engine/standard.py — the real calculation engine — instead of
# redefined here, so there is exactly one place each value can drift from.
# _get_slab_label() below (a display-only helper, not part of calculation)
# is the only other place in this file that still needs the per-country
# deduction constants; it imports the rest of what it needs at its own
# definition further down for the same reason.
from app.modules.payroll.engine.standard import MONTHS_PER_YEAR
from app.modules.payroll.engine.countries.shared import _YTD_ACCUMULATOR_ENABLED_COUNTRIES, _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES


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


def _seed_contribution_rates(db: Session, organization_id: int, country: str) -> List[ContributionRate]:
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
    db: Session, organization_id: int = None, *, country: str, tax_regime: str = None,
    filing_status: str = None,
) -> List[ContributionRate]:
    from app.modules.payroll.engine.tax_resolver import _normalize_regime_label

    query = db.query(ContributionRate)
    query = _apply_org_filter(query, ContributionRate, organization_id)
    query = query.filter(ContributionRate.jurisdiction_country == country)
    if filing_status:
        # Filing-status-agnostic rows always apply, a row tagged for THIS
        # filing status also applies and wins the dict collapse, rows
        # tagged for a DIFFERENT filing status are excluded entirely. An
        # org that hasn't configured any filing-status-specific row is
        # completely unaffected — the filter matches every row exactly as
        # if it weren't there.
        query = query.filter(or_(ContributionRate.filing_status.is_(None), ContributionRate.filing_status == filing_status))
    rows = query.order_by(ContributionRate.sort_order).all()
    if tax_regime:
        # Regime-agnostic rows (tax_regime IS NULL — PF/ESI/PT and every
        # existing row today) always apply; a row tagged for this specific
        # regime ALSO applies and is ordered last, so a caller building a
        # {component_key: row} dict from this list naturally lets the
        # regime-specific row win when both exist for the same key. Rows
        # tagged for the OTHER regime are excluded entirely.
        #
        # Filtered here in Python via _normalize_regime_label rather than
        # a plain SQL `==` comparison — a row synced verbatim from a
        # canonical pack (sync_org_rates_from_canonical) can carry a
        # wordier label ("New Tax Regime") than the short "New"/"Old" this
        # function is always called with, and an exact-match filter would
        # silently exclude it rather than just fail to prefer it.
        rows = [
            r for r in rows
            if _normalize_regime_label(r.tax_regime) is None
            or _normalize_regime_label(r.tax_regime) == tax_regime
        ]
        rows.sort(key=lambda r: _normalize_regime_label(r.tax_regime) is not None)
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


def _seed_tax_slabs(db: Session, organization_id: int, country: str) -> List[TaxSlab]:
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


def get_tax_slabs(db: Session, organization_id: int = None, *, country: str, tax_regime: str = None) -> List[TaxSlab]:
    from app.modules.payroll.engine.tax_resolver import _normalize_regime_label

    query = db.query(TaxSlab)
    query = _apply_org_filter(query, TaxSlab, organization_id)
    query = query.filter(TaxSlab.jurisdiction_country == country)
    rows = query.order_by(TaxSlab.sort_order).all()
    if tax_regime:
        # Same regime-agnostic-plus-specific pattern as get_contribution_rates
        # — filtered in Python via _normalize_regime_label (not a plain SQL
        # `==`) so a wordier synced-from-canonical label ("New Tax Regime")
        # still matches the short "New"/"Old" this function is called with.
        rows = [
            r for r in rows
            if _normalize_regime_label(r.tax_regime) is None
            or _normalize_regime_label(r.tax_regime) == tax_regime
        ]
    if not rows and organization_id:
        if not _seed_org_rates_for_country(db, organization_id, country):
            _seed_tax_slabs(db, organization_id, country)
        rows = (
            db.query(TaxSlab)
            .filter(TaxSlab.organization_id == organization_id, TaxSlab.jurisdiction_country == country)
            .order_by(TaxSlab.sort_order)
            .all()
        )
        if tax_regime:
            rows = [
                r for r in rows
                if _normalize_regime_label(r.tax_regime) is None
                or _normalize_regime_label(r.tax_regime) == tax_regime
            ]
    if tax_regime:
        # MARGINAL_RATE brackets are the one rule_type where a regime-
        # specific set REPLACES the shared/NULL set rather than layering
        # on top of it — unlike a scalar override (standard_deduction) or
        # SURCHARGE (only the top tier differs by regime), India's Old
        # and New regime bracket boundaries share no min_amount in
        # common, so summing both tables in the engine's marginal-bracket
        # loop would be wrong, not just imprecise (ZP-TAX-IN-2026-27-001
        # §4.1). When rows tagged for the requested regime exist for
        # MARGINAL_RATE, drop the NULL-tagged ones so only one complete
        # table is ever returned. Strict superset: with no regime-tagged
        # MARGINAL_RATE rows configured for any OTHER country, this
        # changes nothing outside India.
        has_regime_specific_brackets = any(
            r.rule_type == "MARGINAL_RATE" and _normalize_regime_label(r.tax_regime) == tax_regime for r in rows
        )
        if has_regime_specific_brackets:
            rows = [
                r for r in rows
                if not (r.rule_type == "MARGINAL_RATE" and _normalize_regime_label(r.tax_regime) is None)
            ]
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
        currency=data.currency,
    )
    # An inverted effective-date range (effective_to before effective_from)
    # makes the pack permanently unresolvable by _find_active_tax_pack's
    # date filter regardless of its status — it can sit "Active" in the UI
    # while every calculation silently treats it as absent. This exact
    # defect class silently broke India's canonical sync until caught and
    # fixed by hand; validating it here closes the gap at the source
    # instead of relying on someone noticing later.
    if data.effectiveFrom and data.effectiveTo and data.effectiveTo < data.effectiveFrom:
        raise BadRequestException(
            "Effective To date cannot be before Effective From date — this pack would never resolve for any calculation."
        )
    # Real bypass this closes: set_jurisdiction_pack_status's overlap
    # guard, inverted-date guard, and distinct-approver maker-checker gate
    # (below) only ever run when THAT function is the one making a pack
    # Active. This plain create/edit endpoint used to accept
    # status="Active" directly with none of those checks — a tax pack
    # could go live (or be CREATED already live) with an overlapping
    # effective range, an inverted date range, or no approval at all.
    # Every other status is unaffected: "Approved" without a real
    # approved_by_id is cosmetically wrong but harmless, since the Active
    # gate below still separately requires approved_by_id to be set.
    if data.status == "Active" and data.packType == "tax":
        raise BadRequestException(
            "A tax pack cannot be activated through a plain edit — use the dedicated "
            "Activate action, which enforces the overlap/date/maker-checker checks "
            "set_jurisdiction_pack_status requires before any pack goes live."
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
        # A prior approval attested to the pack's substance AT THAT TIME —
        # this edit (rates/slabs are edited via their own upsert
        # functions, which apply the same invalidation) may have changed
        # exactly what that approval was reviewing, so it must not carry
        # over silently. See _invalidate_pack_approval_on_edit's own
        # docstring for the full reasoning.
        _invalidate_pack_approval_on_edit(existing)
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
    auto_commit: bool = True,
) -> None:
    """One canonical write path for every mutation to a Super-Admin-owned
    canonical tax/contribution/pack row. Called explicitly at each mutation
    site (matching this module's existing style of explicit service
    functions) rather than via an ORM event hook, so every audit entry is
    traceable to the exact line that produced it.

    Phase 8AV: `auto_commit=False` lets a caller fold this audit INSERT
    into the SAME transaction/commit as a preceding financial write,
    instead of this function's own independent commit creating a second,
    separate durability boundary. Found needed for real:
    _reapply_attached_germany_overtime_deltas previously committed its
    financial state (gross_pay/net_pay/allowance/component FK, all
    together in ONE commit) and then called this function, whose own
    separate `db.commit()` meant a crash between the two commits would
    leave the financial change durably persisted with NO corresponding
    audit row for it — a real, if narrow, auditability gap (not a
    financial-correctness one — the money itself is never left partially
    applied, since the financial write is genuinely one atomic commit).
    Every OTHER of this function's 77 existing call sites keeps the
    default (`auto_commit=True`, unchanged behavior) — this is additive,
    not a behavior change for any caller that doesn't pass the new
    argument."""
    db.add(TaxConfigurationAudit(
        actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
        jurisdiction_pack_id=jurisdiction_pack_id, tax_version=tax_version,
        legal_reference=legal_reference, old_value=old_value, new_value=new_value, reason=reason,
    ))
    if auto_commit:
        db.commit()
    else:
        db.flush()


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


def _invalidate_pack_approval_on_edit(pack: "JurisdictionPack") -> None:
    """A pack's approval (approved_by_id + "Approved" status) attests that
    a DISTINCT Super Admin reviewed exactly this pack's CURRENT substance —
    set_jurisdiction_pack_status's own maker-checker gate trusts that
    attestation at Active-transition time. "Approved" is deliberately still
    in _EDITABLE_PACK_STATUSES (an approved pack can still be corrected
    before going live), but without this, editing (or deleting) a rate/
    slab row — or the pack's own metadata — after approval would let that
    stale approval silently carry over onto content nobody actually
    re-reviewed: approve, quietly edit, activate, with no one having seen
    the edit. Called from every mutation site that can change what an
    approval was attesting to (upsert_jurisdiction_pack,
    upsert_canonical_contribution_rate/tax_slab, and the two
    delete_canonical_* functions). A no-op for the ordinary create/edit-
    before-ever-approved flow, where approved_by_id is already None."""
    if pack.approved_by_id is not None:
        pack.approved_by_id = None
        if pack.status == "Approved":
            pack.status = "Draft"


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
    the metadata can then never disagree on which pack version applied.

    Captures EVERY field the engine's own resolvers actually read off a
    ContributionRate/TaxSlab row (resolve_jurisdiction_parameter's
    employee_rate_pct/employer_rate_pct/flat_amount/text_value,
    _calculate_annual_tax's filing_status/min_amount/max_amount/rate_pct/
    rule_type/formula_expression, UK NI_BAND's ni_category/
    employer_rate_pct) plus the remaining display/scoping fields — not
    just a handful of numeric values — because
    _reconstruct_rate_map_and_slabs_from_snapshot below must be able to
    rebuild objects the engine can't distinguish from the live ORM rows
    it normally resolves. A THINNER capture here would make historical
    replay (ZP-TAX-CA-2026-001 AC-32) silently pick the wrong row for any
    filing-status/NI-category-tagged bracket once replayed — see
    regenerate_employee_payslip. Payslips generated before this field set
    existed keep their thinner snapshot (unaffected, not backfilled);
    _reconstruct_rate_map_and_slabs_from_snapshot degrades gracefully for
    those (missing fields resolve to None, same as an unset live column)."""
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
                "employeeShare": r.employee_share, "employerShare": r.employer_share, "total": r.total,
                "employeeRatePct": _dec(r.employee_rate_pct), "employerRatePct": _dec(r.employer_rate_pct),
                "flatAmount": _dec(r.flat_amount), "textValue": r.text_value,
                "jurisdictionCountry": r.jurisdiction_country, "jurisdictionState": r.jurisdiction_state,
                "jurisdictionLocality": r.jurisdiction_locality, "taxRegime": r.tax_regime,
                "filingStatus": r.filing_status,
            }
            for r in rates
        ],
        "taxSlabs": [
            {
                "minAmount": _dec(s.min_amount), "maxAmount": _dec(s.max_amount), "ratePct": _dec(s.rate_pct),
                "rateLabel": s.rate_label, "taxFormula": s.tax_formula, "sortOrder": s.sort_order,
                "jurisdictionCountry": s.jurisdiction_country, "jurisdictionState": s.jurisdiction_state,
                "jurisdictionLocality": s.jurisdiction_locality, "taxRegime": s.tax_regime,
                "filingStatus": s.filing_status, "ruleType": s.rule_type, "formulaExpression": s.formula_expression,
                "flatAmount": _dec(s.flat_amount), "adjustmentAmount": _dec(s.adjustment_amount),
                "niCategory": s.ni_category, "employerRatePct": _dec(s.employer_rate_pct),
            }
            for s in slabs
        ],
    }
    return {"tax_policy_pack_id": pack.id, "tax_policy_version": pack.version, "tax_rule_snapshot": snapshot}


class _ReplayContributionRate:
    """A frozen-snapshot stand-in for a live ContributionRate ORM row —
    exposes the exact same attributes resolve_jurisdiction_parameter/
    get_contribution_rates callers read, reconstructed from a
    tax_rule_snapshot's "contributionRates" entries rather than a DB
    query. See _reconstruct_rate_map_and_slabs_from_snapshot."""
    __slots__ = (
        "component_key", "label", "employee_share", "employer_share", "total",
        "employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value",
        "jurisdiction_country", "jurisdiction_state", "jurisdiction_locality",
        "tax_regime", "filing_status",
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))


class _ReplayTaxSlab:
    """A frozen-snapshot stand-in for a live TaxSlab ORM row — see
    _ReplayContributionRate above; same reasoning, for the bracket/NI-band
    side of the engine's resolution instead of the flat-rate side."""
    __slots__ = (
        "min_amount", "max_amount", "rate_pct", "rate_label", "tax_formula",
        "sort_order", "jurisdiction_country", "jurisdiction_state", "jurisdiction_locality",
        "tax_regime", "filing_status", "rule_type", "formula_expression",
        "flat_amount", "adjustment_amount", "ni_category", "employer_rate_pct",
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))


def _reconstruct_rate_map_and_slabs_from_snapshot(snapshot: Optional[dict]) -> tuple[list, list]:
    """The replay half of ZP-TAX-CA-2026-001 AC-32 ("historical replay
    after a statutory update returns the same result using the original
    snapshot"): rebuilds the exact (rates, slabs) lists the engine
    consumed at generation time from a frozen tax_rule_snapshot JSON
    blob, as lightweight objects exposing the SAME attributes the live
    ORM rows _resolve_effective_rate_inputs would have returned instead —
    build_context_from_employee/calculate_payroll can't tell the
    difference. Used by regenerate_employee_payslip so a correction
    (e.g. fixing an employee's bank details) reproduces the ORIGINAL
    numbers even if Super Admin has since edited or superseded the tax
    pack that produced them, instead of silently recalculating against
    whatever rates are live today.

    Returns ([], []) for a missing/empty snapshot — the caller falls
    back to live re-resolution exactly as before this function existed
    (e.g. payslips generated before any canonical pack was in use, or for
    an org never opted into canonical tracking, have no snapshot to
    replay from at all)."""
    if not snapshot:
        return [], []

    def _pdec(v):
        return Decimal(v) if v is not None else None

    rates = [
        _ReplayContributionRate(
            component_key=r.get("componentKey"), label=r.get("label"),
            employee_share=r.get("employeeShare"), employer_share=r.get("employerShare"), total=r.get("total"),
            employee_rate_pct=_pdec(r.get("employeeRatePct")), employer_rate_pct=_pdec(r.get("employerRatePct")),
            flat_amount=_pdec(r.get("flatAmount")), text_value=r.get("textValue"),
            jurisdiction_country=r.get("jurisdictionCountry"), jurisdiction_state=r.get("jurisdictionState"),
            jurisdiction_locality=r.get("jurisdictionLocality"), tax_regime=r.get("taxRegime"),
            filing_status=r.get("filingStatus"),
        )
        for r in (snapshot.get("contributionRates") or [])
        if r.get("componentKey")
    ]
    slabs = [
        _ReplayTaxSlab(
            min_amount=_pdec(s.get("minAmount")), max_amount=_pdec(s.get("maxAmount")), rate_pct=_pdec(s.get("ratePct")),
            rate_label=s.get("rateLabel"), tax_formula=s.get("taxFormula"), sort_order=s.get("sortOrder"),
            jurisdiction_country=s.get("jurisdictionCountry"), jurisdiction_state=s.get("jurisdictionState"),
            jurisdiction_locality=s.get("jurisdictionLocality"), tax_regime=s.get("taxRegime"),
            filing_status=s.get("filingStatus"), rule_type=s.get("ruleType"), formula_expression=s.get("formulaExpression"),
            flat_amount=_pdec(s.get("flatAmount")), adjustment_amount=_pdec(s.get("adjustmentAmount")),
            ni_category=s.get("niCategory"), employer_rate_pct=_pdec(s.get("employerRatePct")),
        )
        for s in (snapshot.get("taxSlabs") or [])
    ]
    return rates, slabs


def _check_missing_required_keys(rate_map: dict, slabs: list, country: str) -> List[dict]:
    """Shared predicate used by BOTH check_jurisdiction_readiness (the
    read-only audit tool) and _resolve_effective_rate_inputs's own dormant
    enforcement call below, so the two can never disagree about what
    "ready" means. Operates on an ALREADY-RESOLVED rate_map/slabs — never
    resolves anything itself, so calling this from inside
    _resolve_effective_rate_inputs can't re-enter it.

    Mirrors resolve_jurisdiction_parameter's own "configured" predicate
    exactly (engine/countries/shared.py) — a row present AND the relevant
    employee_rate_pct/employer_rate_pct/flat_amount actually set — so this
    can never say "ready" when the engine would actually fall back."""
    from app.modules.payroll.engine.fallback_registry import get_required_parameter_keys

    missing = []
    for req in get_required_parameter_keys(country):
        row = rate_map.get(req["key"])
        if req["side"] is not None:
            configured = row is not None and getattr(row, f"{req['side']}_rate_pct", None) is not None
        else:
            configured = row is not None and row.flat_amount is not None
        if not configured:
            missing.append({"key": req["key"], "side": req["side"], "label": req["label"]})
    return missing


def _assert_jurisdiction_ready(rate_map: dict, slabs: list, country: str, organization_id: Optional[int]) -> None:
    """Dormant enforcement — raises only when `country` has been
    explicitly opted into fail-fast validation
    (engine/countries/shared.py's _VALIDATION_ENABLED_COUNTRIES, currently
    empty for every country — see that file's rollout log). While
    dormant, this is a true no-op: every existing calculation proceeds
    exactly as before. Reuses the ONE existing rollout switch rather than
    adding a second one."""
    from app.modules.payroll.engine.countries.shared import (
        _VALIDATION_ENABLED_COUNTRIES, MissingComplianceConfigurationError,
    )

    if country not in _VALIDATION_ENABLED_COUNTRIES:
        return
    missing = _check_missing_required_keys(rate_map, slabs, country)
    if missing or not slabs:
        bad_key = missing[0]["key"] if missing else "tax slabs"
        raise MissingComplianceConfigurationError(bad_key, country, organization_id)


def check_jurisdiction_readiness(
    db: Session, organization_id: int, country: str, state: Optional[str] = None,
    tax_regime: Optional[str] = None, payroll_date=None,
) -> dict:
    """Read-only: is this org's (country, state, tax_regime) combination
    actually ready for payroll calculation to run without falling back to
    ANY hardcoded engine default? Never writes, never raises — the tool
    that was missing when fail-fast validation was briefly enabled for
    India: it broke 35 tests and would have broken that org's next real
    payroll run, because canonical-data completeness alone said nothing
    about whether the ORG'S OWN already-synced rows were complete (see
    engine/countries/shared.py's rollout log for the full incident).

    Uses the exact resolution path real calculation uses
    (_resolve_effective_rate_inputs) and the exact "is this key actually
    configured" predicate (_check_missing_required_keys, shared with the
    dormant enforcement wrapper) — so this can never say "ready" when the
    engine would actually fall back, or vice versa."""
    from datetime import date as date_cls

    as_of = payroll_date or date_cls.today()
    org_opted_in = _org_uses_canonical_tax_pack(db, organization_id)
    rate_map, slabs, _canonical_rates, pack = _resolve_effective_rate_inputs(
        db, organization_id, country, as_of, org_opted_in, state=state, tax_regime=tax_regime,
    )
    missing_keys = _check_missing_required_keys(rate_map, slabs, country)
    return {
        "country": country,
        "state": state,
        "packId": pack.pack_id if pack else None,
        "packVersion": pack.version if pack else None,
        "source": "canonical" if pack else ("org-cached" if rate_map else "none"),
        "ready": not missing_keys and bool(slabs),
        "missingKeys": missing_keys,
        "missingSlabs": not bool(slabs),
    }


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
            canonical_rate_map = {_normalize_engine_component_key(r.component_key): r for r in canonical_rates}
            _assert_jurisdiction_ready(canonical_rate_map, canonical_slabs, country, organization_id)
            return canonical_rate_map, canonical_slabs, canonical_rates, pack
    # India's Old and New regime bracket tables are two complete,
    # mutually exclusive tables (ZP-TAX-IN-2026-27-001 §3: "default/new
    # regime is the default calculation path... unless a valid election
    # requires the old regime") — an employee with no declared regime
    # must resolve against New Regime, never an unfiltered union of both.
    # Scoped to the legacy path only: the canonical-pack branch above
    # keeps the raw (possibly-None) tax_regime unchanged, since today's
    # single not-regime-tagged India pack already correctly matches an
    # unset regime there — forcing "New" through that branch too would
    # stop it matching its own pack.
    effective_tax_regime = tax_regime or ("New" if country == "IN" else None)
    rate_map = {
        _normalize_engine_component_key(r.component_key): r
        for r in get_contribution_rates(db, organization_id, country=country, tax_regime=effective_tax_regime, filing_status=filing_status)
    }
    slabs = get_tax_slabs(db, organization_id, country=country, tax_regime=effective_tax_regime)
    _assert_jurisdiction_ready(rate_map, slabs, country, organization_id)
    return rate_map, slabs, None, None


def _resolve_pack_scoped_rows(db: Session, rows: list, as_of) -> list:
    """Given a list of canonical ORM rows (ContributionRate or TaxSlab)
    that all share the same logical key (one component_key, or one
    TaxSlab rule_type) but may span MORE THAN ONE JurisdictionPack — e.g.
    an H1 package's row and an H2 package's row for the same province's
    same component — picks only the rows belonging to whichever pack is
    BOTH date-effective for `as_of` AND status=="Active" (ties broken by
    most-recently-updated, same convention as tax_resolver.py's
    _find_active_tax_pack). Rows with no jurisdiction_pack_id at all, or
    where every row shares the same single pack (the case for every
    country/state today except a province with genuine H1-vs-H2 data),
    are returned COMPLETELY UNCHANGED — this function can only ever
    narrow an already-ambiguous set once a genuinely qualifying Active
    pack exists; it never regresses a currently-working (even if
    arbitrary) resolution to fewer/empty rows. That's what makes this
    safe to run unconditionally with no rollout switch: found while
    fixing ZP-TAX-CA-2026-001's H1/H2 gap (BC's real 2026 data is split
    across CA-BC-2026-H1/H2, both currently Draft — until one is
    promoted Active, this deliberately falls back to today's behavior
    rather than trusting Draft data in production math)."""
    pack_ids = {getattr(r, "jurisdiction_pack_id", None) for r in rows}
    pack_ids.discard(None)
    if len(pack_ids) <= 1:
        return rows
    as_of = as_of or date.today()
    candidates = (
        db.query(JurisdictionPack)
        .filter(
            JurisdictionPack.id.in_(pack_ids),
            JurisdictionPack.status == "Active",
            (JurisdictionPack.effective_from.is_(None)) | (JurisdictionPack.effective_from <= as_of),
            (JurisdictionPack.effective_to.is_(None)) | (JurisdictionPack.effective_to >= as_of),
        )
        .order_by(JurisdictionPack.updated_at.desc())
        .all()
    )
    if not candidates:
        return rows
    winning_pack_id = candidates[0].id
    return [r for r in rows if getattr(r, "jurisdiction_pack_id", None) == winning_pack_id]


def get_state_scoped_config(db: Session, country: str, state: Optional[str], as_of=None, filing_status: str = None) -> Tuple[dict, list]:
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

    `as_of` (new): when a province has more than one JurisdictionPack's
    worth of canonical rows for the same component_key/rule_type (e.g. a
    province with genuinely different H1 vs H2 values), disambiguates via
    _resolve_pack_scoped_rows instead of silently returning an arbitrary
    row (ContributionRate) or CONCATENATING both packages' brackets
    together into one summed table (TaxSlab) — the exact bug this
    parameter fixes. Grouped independently per component_key/rule_type
    since e.g. Ontario's ON_EHT_BAND rows and its ordinary income-tax
    brackets are functionally separate tables sharing the same
    (country, state) scope. None defaults to today, matching every other
    as_of-accepting lookup in this file.

    Returns ({}, []) if state is falsy or nothing is configured for it —
    every existing calculation is completely unaffected until a country
    calculator explicitly reads ctx.state_rate_map/ctx.state_slabs AND a
    real region-scoped row has been seeded for that specific state.

    `filing_status` (US-specific; NULL for every other caller/jurisdiction,
    exactly like get_contribution_rates' own filing_status parameter):
    a state-scoped parameter (e.g. Colorado's annual_allowance, tagged
    MFJ_OR_QSS vs untagged/"OTHER") can be filing-status-specific the same
    way a country-level one already is. Omitting it (every call site that
    doesn't need it, e.g. sync_org_rates_from_canonical, which wants every
    sibling row, not one collapsed winner) reproduces today's exact
    behavior unchanged."""
    if not state:
        return {}, []
    rate_query = db.query(ContributionRate).filter(
        ContributionRate.organization_id.is_(None),
        ContributionRate.jurisdiction_country == country,
        ContributionRate.jurisdiction_state == state,
    )
    order_priority = []
    if filing_status:
        # Same convention as get_contribution_rates: filing-status-agnostic
        # rows always apply, a row tagged for THIS filing status also
        # applies and is ordered last (so the {key: row} dict comprehension
        # below lets it win), rows tagged for a DIFFERENT filing status are
        # excluded entirely.
        rate_query = rate_query.filter(or_(ContributionRate.filing_status.is_(None), ContributionRate.filing_status == filing_status))
        order_priority.append(ContributionRate.filing_status.isnot(None))
    rate_rows = (
        rate_query.order_by(*order_priority, ContributionRate.sort_order).all()
        if order_priority else rate_query.order_by(ContributionRate.sort_order).all()
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

    rate_rows_by_key: dict = {}
    for r in rate_rows:
        rate_rows_by_key.setdefault(_normalize_engine_component_key(r.component_key), []).append(r)
    resolved_rate_rows = []
    for key_rows in rate_rows_by_key.values():
        resolved_rate_rows.extend(_resolve_pack_scoped_rows(db, key_rows, as_of))

    slab_rows_by_type: dict = {}
    for s in slab_rows:
        slab_rows_by_type.setdefault(getattr(s, "rule_type", None), []).append(s)
    resolved_slab_rows = []
    for type_rows in slab_rows_by_type.values():
        resolved_slab_rows.extend(_resolve_pack_scoped_rows(db, type_rows, as_of))

    state_rate_map = {_normalize_engine_component_key(r.component_key): r for r in resolved_rate_rows}
    return state_rate_map, resolved_slab_rows


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
    of who changed what, unlike every canonical rate edit.

    Phase 8AJ: rate_source="EMPLOYER_NOTICE" (a profile whose authority
    is a specific agency/carrier notice document — e.g. a German
    Berufsgenossenschaft Beitragsbescheid) must carry sourceDocumentId.
    STATE_DEFAULT/NEW_EMPLOYER profiles are unaffected — those
    legitimately have no single notice document to attach."""
    if data.rateSource == "EMPLOYER_NOTICE" and not data.sourceDocumentId:
        raise BadRequestException(
            "An EMPLOYER_NOTICE-sourced profile must reference its source notice document "
            "(sourceDocumentId) — record it as a SourceArtifact first."
        )
    fields = dict(
        organization_id=data.organizationId, jurisdiction_id=data.jurisdictionId,
        component_code=data.componentCode, taxable_wage_base=data.taxableWageBase,
        rate_source=data.rateSource, employer_rate_pct=data.employerRatePct,
        assessment_rate_pct=data.assessmentRatePct,
        effective_from=data.effectiveFrom, effective_to=data.effectiveTo,
        agency_account_id=data.agencyAccountId, reimbursable_status=data.reimbursableStatus,
        source_document_id=data.sourceDocumentId,
        covered_employee_count=data.coveredEmployeeCount,
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


# ── Germany: Accident Insurance Profile maker-checker (Phase 8AJ, 2nd pass)
# See GermanyAccidentInsuranceProfile's own model docstring for why this
# is a separate table from EmployerTaxProfile above. Status vocabulary
# and transition rules are IDENTICAL to GermanyHealthFund's
# (_HEALTH_FUND_ALLOWED_TRANSITIONS) — copied, not inherited, since the
# two models are otherwise unrelated, matching this module's own
# established convention of duplicating this exact small state machine
# per registry (see also GermanyContributionCeiling/GermanyPvConfiguration).

_ACCIDENT_INSURANCE_PROFILE_EDITABLE_STATUSES = ("DRAFT", "VERIFIED", "APPROVED")
_ACCIDENT_INSURANCE_PROFILE_VALID_STATUSES = ("DRAFT", "VERIFIED", "APPROVED", "PUBLISHED", "SUPERSEDED")
_ACCIDENT_INSURANCE_PROFILE_ALLOWED_TRANSITIONS = {
    "DRAFT": {"VERIFIED"},
    "VERIFIED": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "VERIFIED"},
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_accident_insurance_profile(row: GermanyAccidentInsuranceProfile) -> None:
    if row.status not in _ACCIDENT_INSURANCE_PROFILE_EDITABLE_STATUSES:
        raise BadRequestException(
            f"Accident insurance profile #{row.id} (org {row.organization_id}) is {row.status} — no longer "
            "editable. Record a new effective-dated version instead."
        )


def _validate_accident_insurance_profile_no_overlap(
    db: Session, organization_id: int, effective_from: date, effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    """Same overlap-prevention shape as _validate_health_fund_no_overlap,
    keyed by organization_id instead of health_fund_id (this registry's
    identity — one org may have several historical versions, but never
    two overlapping ones)."""
    query = db.query(GermanyAccidentInsuranceProfile).filter(
        GermanyAccidentInsuranceProfile.organization_id == organization_id,
    )
    if exclude_id is not None:
        query = query.filter(GermanyAccidentInsuranceProfile.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing accident "
                f"insurance profile #{existing.id} for this organization ({existing.effective_from} to "
                f"{existing.effective_to or 'open-ended'}). Close or adjust that record first."
            )


def list_germany_accident_insurance_profiles(
    db: Session, organization_id: Optional[int] = None,
) -> List[GermanyAccidentInsuranceProfile]:
    query = db.query(GermanyAccidentInsuranceProfile)
    if organization_id is not None:
        query = query.filter(GermanyAccidentInsuranceProfile.organization_id == organization_id)
    return query.order_by(GermanyAccidentInsuranceProfile.organization_id, GermanyAccidentInsuranceProfile.effective_from.desc()).all()


def get_germany_accident_insurance_profile_by_id(db: Session, record_id: int) -> GermanyAccidentInsuranceProfile:
    row = db.query(GermanyAccidentInsuranceProfile).filter(GermanyAccidentInsuranceProfile.id == record_id).first()
    if not row:
        raise NotFoundException("GermanyAccidentInsuranceProfile", record_id)
    return row


def create_germany_accident_insurance_profile_record(
    db: Session, data: "GermanyAccidentInsuranceProfileCreate", actor_id: Optional[int] = None,
    auto_close_previous: bool = True,
) -> GermanyAccidentInsuranceProfile:
    """Append a new effective-dated DRAFT accident-insurance profile
    version for one organization. Never updates an existing row — same
    auto-close-previous-open-row behavior as create_health_fund_record."""
    if not data.carrier_name or not data.carrier_name.strip():
        raise BadRequestException("carrierName is required.")
    if data.employer_rate_pct is None or data.employer_rate_pct < 0:
        raise BadRequestException("employerRatePct must be a non-negative value.")
    if data.effective_to is not None and data.effective_to < data.effective_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")

    previous_open = (
        db.query(GermanyAccidentInsuranceProfile)
        .filter(
            GermanyAccidentInsuranceProfile.organization_id == data.organization_id,
            GermanyAccidentInsuranceProfile.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(
        auto_close_previous and previous_open and previous_open.effective_from < data.effective_from
    )
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_accident_insurance_profile_no_overlap(
        db, data.organization_id, data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = GermanyAccidentInsuranceProfile(
        organization_id=data.organization_id, carrier_name=data.carrier_name,
        agency_account_id=data.agency_account_id, risk_class_description=data.risk_class_description,
        employer_rate_pct=data.employer_rate_pct,
        effective_from=data.effective_from, effective_to=data.effective_to,
        authority_source_id=data.authority_source_id, status="DRAFT",
        created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_accident_insurance_profile", entity_id=row.id,
        old_value=None,
        new_value={
            "organization_id": data.organization_id, "carrier_name": data.carrier_name,
            "employer_rate_pct": str(data.employer_rate_pct),
            "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
    )
    return row


def _materialize_accident_insurance_profile_to_employer_tax_profile(
    db: Session, row: GermanyAccidentInsuranceProfile, actor_id: Optional[int],
) -> None:
    """Called ONLY when a profile reaches PUBLISHED. Writes the same
    values into the existing EmployerTaxProfile mechanism
    (jurisdiction_id="DE", component_code="DE_ACCIDENT_INSURANCE") the
    Germany engine already reads (engine/countries/germany.py,
    ctx.employer_tax_profiles) — unchanged by this phase. This keeps the
    engine's read path exactly as it was; only the WRITE path gains a
    maker-checker gate in front of it."""
    existing = (
        db.query(EmployerTaxProfile)
        .filter(
            EmployerTaxProfile.organization_id == row.organization_id,
            EmployerTaxProfile.jurisdiction_id == "DE",
            EmployerTaxProfile.component_code == "DE_ACCIDENT_INSURANCE",
        )
        .first()
    )
    fields = dict(
        organization_id=row.organization_id, jurisdiction_id="DE", component_code="DE_ACCIDENT_INSURANCE",
        taxable_wage_base=Decimal("0"), rate_source="EMPLOYER_NOTICE",
        employer_rate_pct=row.employer_rate_pct,
        effective_from=row.effective_from, effective_to=row.effective_to,
        agency_account_id=row.agency_account_id, reimbursable_status="CONTRIBUTORY",
        source_document_id=row.authority_source_id,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        db.add(EmployerTaxProfile(**fields))
    db.commit()


def set_germany_accident_insurance_profile_status(
    db: Session, record_id: int, status: str, actor_id: Optional[int] = None,
) -> GermanyAccidentInsuranceProfile:
    """Advance an accident-insurance profile's lifecycle — identical
    maker-checker principle to set_health_fund_status (distinct approver
    + linked source evidence required before PUBLISHED). On a successful
    transition TO PUBLISHED, also materializes the values into
    EmployerTaxProfile (see helper above) so the already-existing engine
    read path picks them up — the backend remains the sole authority for
    when that happens, never the frontend."""
    row = get_germany_accident_insurance_profile_by_id(db, record_id)
    if status not in _ACCIDENT_INSURANCE_PROFILE_VALID_STATUSES:
        raise BadRequestException(f"Unknown accident insurance profile status: {status!r}.")
    if status not in _ACCIDENT_INSURANCE_PROFILE_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move an accident insurance profile from {row.status} to {status}.")

    if status == "PUBLISHED":
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This accident insurance profile needs a distinct approver before it can be published — "
                "use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.authority_source_id:
            raise BadRequestException(
                "An accident insurance profile cannot be published without a linked source evidence "
                "artifact (authoritySourceId) — record the employer's own notice via "
                "/compliance/source-artifacts first."
            )

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_accident_insurance_profile",
        entity_id=row.id, old_value={"status": old_status}, new_value={"status": status},
    )
    if status == "PUBLISHED":
        _materialize_accident_insurance_profile_to_employer_tax_profile(db, row, actor_id)
    return row


def set_germany_accident_insurance_profile_approver(
    db: Session, record_id: int, actor_id: Optional[int] = None,
) -> GermanyAccidentInsuranceProfile:
    """Sets approved_by_id — same distinct, lightweight action as
    set_health_fund_approver. Auto-advances VERIFIED -> APPROVED only."""
    row = get_germany_accident_insurance_profile_by_id(db, record_id)
    _require_editable_accident_insurance_profile(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "VERIFIED":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_accident_insurance_profile", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


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
    resident_rate_map, resident_slabs = get_state_scoped_config(
        db, country, residence_state, as_of=as_of, filing_status=getattr(employee, "w4_filing_status", None),
    )
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


# ── Germany: Church tax (Kirchensteuer) Land matrix (Phase 8O) ──────────
# Read-only surfacing of germany_pap.core.CHURCH_TAX_LAND_RATES — spec §8.
# Deliberately NOT a new DB-backed registry/lifecycle: there is no
# effective-dated, source-evidenced church-tax table anywhere in this
# codebase (the rates are a bare Python dict, cited to spec §8 directly in
# code), and this phase's own instruction is "if backend support is
# missing, display NOT IMPLEMENTED rather than pretending it is
# supported" — inventing a DRAFT/APPROVED/PUBLISHED lifecycle for data
# that has neither a migration nor a SourceArtifact linkage would be
# exactly that pretense. This function exists only so the Super Admin UI
# has a real endpoint to read the actual values from, instead of
# hardcoding them a second time in the frontend.
def get_church_tax_matrix() -> dict:
    from app.modules.payroll.engine.germany_pap.core import CHURCH_TAX_LAND_RATES

    return {
        "laender": [
            {"code": code, "ratePct": str(rate)} for code, rate in sorted(CHURCH_TAX_LAND_RATES.items())
        ],
        "sourceStatus": "HARDCODED_CONSTANT — no DB-backed registry/lifecycle/source-evidence linkage exists",
        "knownGaps": [
            "Bad Wimpfen (Baden-Württemberg) Roman Catholic denomination/location exception — "
            "IMPLEMENTED (Phase 8AM) as a SEPARATE, additive, source-evidenced maker-checker registry "
            "(GermanyChurchTaxException — see /compliance/germany/church-tax-exceptions), not by editing "
            "this hardcoded per-Land matrix, which remains correct and unchanged for the ordinary case. "
            "Fresh primary-source research located a Tier-2-corroborated (multiple independent reputable "
            "German tax-advisory publishers directly quoting the same official circular reference numbers, "
            "stable 2016-2026 — see docs/PHASE_8AM_..._REPORT.md) confirmation that the Diocese of Mainz's "
            "Baden-Württemberg enclave (encompassing Bad Wimpfen, PLZ 74206) applies a 9% Roman Catholic "
            "Kirchensteuer rate, not Baden-Württemberg's general 8%. An employee only resolves this "
            "exception rate when a matching PUBLISHED GermanyChurchTaxException row exists for their "
            "recorded (Land, denomination, municipality postal code) as of the payroll date — every other "
            "employee continues to resolve the ordinary Land rate exactly as before this phase.",
        ],
    }


# ── Germany: Church Tax Exception registry (Phase 8AM) ──────────────────
# See models.GermanyChurchTaxException's own docstring for the legal
# background (Bad Wimpfen / Diocese of Mainz) and why this is a SEPARATE,
# additive table rather than a rewrite of CHURCH_TAX_LAND_RATES. Global
# (no organization_id) — status vocabulary/transitions copied from
# GermanyHealthFund's (not GermanyAccidentInsuranceProfile's org-scoped
# one), matching this module's own established convention of duplicating
# this exact small state machine per registry.

_CHURCH_TAX_EXCEPTION_EDITABLE_STATUSES = ("DRAFT", "VERIFIED", "APPROVED")
_CHURCH_TAX_EXCEPTION_VALID_STATUSES = ("DRAFT", "VERIFIED", "APPROVED", "PUBLISHED", "SUPERSEDED")
_CHURCH_TAX_EXCEPTION_ALLOWED_TRANSITIONS = {
    "DRAFT": {"VERIFIED"},
    "VERIFIED": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "VERIFIED"},
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_church_tax_exception(row: GermanyChurchTaxException) -> None:
    if row.status not in _CHURCH_TAX_EXCEPTION_EDITABLE_STATUSES:
        raise BadRequestException(
            f"Church tax exception #{row.id} ({row.land_code}/{row.denomination}/"
            f"{row.municipality_postal_code}) is {row.status} — no longer editable. Record a new "
            "effective-dated version instead."
        )


def _validate_church_tax_exception_no_overlap(
    db: Session, land_code: str, denomination: str, municipality_postal_code: str,
    effective_from: date, effective_to: Optional[date], exclude_id: Optional[int] = None,
) -> None:
    """Same "no two overlapping ranges for the same identity" check as
    _validate_health_fund_no_overlap, keyed by the composite natural key
    (land_code, denomination, municipality_postal_code) this registry
    actually needs — a documented exception is scoped to a specific
    denomination AND a specific municipality within a specific Land, not
    to the Land alone."""
    query = db.query(GermanyChurchTaxException).filter(
        GermanyChurchTaxException.land_code == land_code,
        GermanyChurchTaxException.denomination == denomination,
        GermanyChurchTaxException.municipality_postal_code == municipality_postal_code,
    )
    if exclude_id is not None:
        query = query.filter(GermanyChurchTaxException.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing church tax "
                f"exception #{existing.id} for {land_code}/{denomination}/{municipality_postal_code} "
                f"({existing.effective_from} to {existing.effective_to or 'open-ended'}). Close or adjust "
                "that record first."
            )


def list_germany_church_tax_exceptions(
    db: Session, land_code: Optional[str] = None,
) -> List[GermanyChurchTaxException]:
    query = db.query(GermanyChurchTaxException)
    if land_code:
        query = query.filter(GermanyChurchTaxException.land_code == land_code)
    return query.order_by(
        GermanyChurchTaxException.land_code, GermanyChurchTaxException.municipality_postal_code,
        GermanyChurchTaxException.effective_from.desc(),
    ).all()


def get_germany_church_tax_exception_by_id(db: Session, record_id: int) -> GermanyChurchTaxException:
    row = db.query(GermanyChurchTaxException).filter(GermanyChurchTaxException.id == record_id).first()
    if not row:
        raise NotFoundException("GermanyChurchTaxException", record_id)
    return row


def create_germany_church_tax_exception_record(
    db: Session, data: "GermanyChurchTaxExceptionCreate", actor_id: Optional[int] = None,
    auto_close_previous: bool = True,
) -> GermanyChurchTaxException:
    """Append a new effective-dated DRAFT church-tax-exception version.
    Never updates an existing row — same auto-close-previous-open-row
    behavior as create_health_fund_record."""
    if not data.land_code or not data.land_code.strip():
        raise BadRequestException("landCode is required.")
    if not data.denomination or not data.denomination.strip():
        raise BadRequestException("denomination is required.")
    if not data.municipality_postal_code or not data.municipality_postal_code.strip():
        raise BadRequestException("municipalityPostalCode is required.")
    if data.exception_rate_pct is None or data.exception_rate_pct < 0:
        raise BadRequestException("exceptionRatePct must be a non-negative value.")
    if data.effective_to is not None and data.effective_to < data.effective_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")

    previous_open = (
        db.query(GermanyChurchTaxException)
        .filter(
            GermanyChurchTaxException.land_code == data.land_code,
            GermanyChurchTaxException.denomination == data.denomination,
            GermanyChurchTaxException.municipality_postal_code == data.municipality_postal_code,
            GermanyChurchTaxException.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(
        auto_close_previous and previous_open and previous_open.effective_from < data.effective_from
    )
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_church_tax_exception_no_overlap(
        db, data.land_code, data.denomination, data.municipality_postal_code,
        data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = GermanyChurchTaxException(
        land_code=data.land_code, denomination=data.denomination,
        municipality_postal_code=data.municipality_postal_code,
        scope_description=data.scope_description, exception_rate_pct=data.exception_rate_pct,
        effective_from=data.effective_from, effective_to=data.effective_to,
        authority_source_id=data.authority_source_id, status="DRAFT",
        created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_church_tax_exception", entity_id=row.id,
        old_value=None,
        new_value={
            "land_code": data.land_code, "denomination": data.denomination,
            "municipality_postal_code": data.municipality_postal_code,
            "exception_rate_pct": str(data.exception_rate_pct),
            "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
    )
    return row


def set_germany_church_tax_exception_status(
    db: Session, record_id: int, status: str, actor_id: Optional[int] = None,
) -> GermanyChurchTaxException:
    """Advance a church-tax-exception record's lifecycle — identical
    maker-checker principle to set_health_fund_status (distinct approver
    + linked source evidence required before PUBLISHED)."""
    row = get_germany_church_tax_exception_by_id(db, record_id)
    if status not in _CHURCH_TAX_EXCEPTION_VALID_STATUSES:
        raise BadRequestException(f"Unknown church tax exception status: {status!r}.")
    if status not in _CHURCH_TAX_EXCEPTION_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move a church tax exception from {row.status} to {status}.")

    if status == "PUBLISHED":
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This church tax exception needs a distinct approver before it can be published — "
                "use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.authority_source_id:
            raise BadRequestException(
                "A church tax exception cannot be published without a linked source evidence artifact "
                "(authoritySourceId) — record one via /compliance/source-artifacts first."
            )

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_church_tax_exception",
        entity_id=row.id, old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_germany_church_tax_exception_approver(
    db: Session, record_id: int, actor_id: Optional[int] = None,
) -> GermanyChurchTaxException:
    """Sets approved_by_id — same distinct, lightweight action as
    set_health_fund_approver. Auto-advances VERIFIED -> APPROVED only."""
    row = get_germany_church_tax_exception_by_id(db, record_id)
    _require_editable_church_tax_exception(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "VERIFIED":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_church_tax_exception", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


def resolve_germany_church_tax_exception(
    db: Session, land_code: Optional[str], denomination: Optional[str],
    municipality_postal_code: Optional[str], as_of: Optional[date] = None,
) -> Optional[GermanyChurchTaxException]:
    """Return the PUBLISHED exception record applicable on `as_of`
    (defaults to today) for this exact (Land, denomination, postal code)
    combination. Returns None (never raises, never guesses) whenever any
    of the three inputs is missing/blank, or when no PUBLISHED exception
    matches — the caller (engine wiring) must treat None as "no
    documented exception applies here; use the ordinary Land rate,"
    exactly the pre-8AM behavior. This fail-closed-to-the-ordinary-rate
    design is deliberate: an ambiguous or incomplete employee record must
    never accidentally receive (or accidentally be denied) a 1-point-off
    exception rate — see docs/PHASE_8AM_..._REPORT.md §19/§24."""
    if not land_code or not denomination or not municipality_postal_code:
        return None
    as_of = as_of or date.today()
    return (
        db.query(GermanyChurchTaxException)
        .filter(
            GermanyChurchTaxException.land_code == land_code,
            GermanyChurchTaxException.denomination == denomination,
            GermanyChurchTaxException.municipality_postal_code == municipality_postal_code,
            GermanyChurchTaxException.status == "PUBLISHED",
            GermanyChurchTaxException.effective_from <= as_of,
            (GermanyChurchTaxException.effective_to.is_(None)) | (GermanyChurchTaxException.effective_to >= as_of),
        )
        .order_by(GermanyChurchTaxException.effective_from.desc())
        .first()
    )


# ── Germany: BMF PAP Algorithm Asset (ZP-TAX-DE-2026-001 §5, §17, §18) ────
# Container/evidence/lifecycle only — see models.PapAlgorithmAsset's own
# docstring and docs/PHASE_3_GERMANY_PAP_ALGORITHM_ASSET.md. NO PAP
# execution logic exists here or anywhere in this codebase; germany.py is
# unchanged and does not read from this table.

_PAP_EDITABLE_STATUSES = ("DRAFT", "REVIEW", "APPROVED")
_PAP_VALID_STATUSES = ("DRAFT", "REVIEW", "APPROVED", "PUBLISHED", "SUPERSEDED")
# Forward-only, mirroring the spec's own described flow (§18: "Import
# source; verify hash; ... compare previous; approve; publish; rollback
# only by activating prior immutable version") — no "reject to Draft from
# Published" path exists because the spec never describes editing/
# reverting a published asset, only publishing a different (correct)
# immutable version.
_PAP_ALLOWED_TRANSITIONS = {
    "DRAFT": {"REVIEW"},
    "REVIEW": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "REVIEW"},
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_pap_asset(row: PapAlgorithmAsset) -> None:
    if row.status not in _PAP_EDITABLE_STATUSES:
        raise BadRequestException(
            f"PAP asset {row.pap_version} ({row.tax_year}) is {row.status} — no longer editable. "
            "Ingest a new version instead; a published statutory algorithm asset must not be edited in place."
        )


def list_pap_assets(db: Session, jurisdiction_country: str = "DE", tax_year: Optional[str] = None) -> List[PapAlgorithmAsset]:
    query = db.query(PapAlgorithmAsset).filter(PapAlgorithmAsset.jurisdiction_country == jurisdiction_country)
    if tax_year:
        query = query.filter(PapAlgorithmAsset.tax_year == tax_year)
    return query.order_by(PapAlgorithmAsset.tax_year.desc(), PapAlgorithmAsset.created_at.desc()).all()


def get_pap_asset_by_id(db: Session, asset_id: int) -> PapAlgorithmAsset:
    row = db.query(PapAlgorithmAsset).filter(PapAlgorithmAsset.id == asset_id).first()
    if not row:
        raise NotFoundException("PapAlgorithmAsset", asset_id)
    return row


def ingest_pap_asset(
    db: Session, *, jurisdiction_country: str, tax_year: str, pap_version: str,
    effective_from: date, effective_to: Optional[date],
    source_content: bytes, source_agency: str, source_title: str,
    source_url: Optional[str] = None, source_publication_date: Optional[date] = None,
    source_content_path: Optional[str] = None, actor_id: Optional[int] = None,
) -> PapAlgorithmAsset:
    """Ingest a new DRAFT PAP asset version. Computes the SHA-256 of
    `source_content` SERVER-SIDE — this function never accepts a
    caller-supplied checksum (unlike the existing, more permissive
    create_source_artifact, which trusts a client-provided checksumSha256 —
    see Phase 3 report §5 for why that existing pattern is deliberately
    NOT reused verbatim for this higher-stakes asset). Creates a new
    SourceArtifact evidence row alongside the asset (rather than requiring
    one to already exist), so ingestion is a single atomic step.

    Never executes, parses, or interprets `source_content` beyond hashing
    it — this phase stores an evidence-backed algorithm asset, nothing
    more."""
    if effective_to is not None and effective_to < effective_from:
        raise BadRequestException("effective_to must not be before effective_from.")
    if not source_content:
        raise BadRequestException("source_content must not be empty.")

    computed_hash = hashlib.sha256(source_content).hexdigest()

    # Duplicate/conflict protection: identical content already ingested
    # under a DIFFERENT version identity for this jurisdiction is a
    # suspicious relabeling — refuse rather than guess (Phase 3 report §9).
    hash_collision = (
        db.query(PapAlgorithmAsset)
        .filter(
            PapAlgorithmAsset.jurisdiction_country == jurisdiction_country,
            PapAlgorithmAsset.source_content_sha256 == computed_hash,
            PapAlgorithmAsset.pap_version != pap_version,
        )
        .first()
    )
    if hash_collision:
        raise BadRequestException(
            f"This exact source content is already ingested as PAP asset #{hash_collision.id} "
            f"(version {hash_collision.pap_version!r}, status {hash_collision.status}). Identical content "
            "under a different version identity is not permitted — verify the version label."
        )

    existing_identity = (
        db.query(PapAlgorithmAsset)
        .filter(
            PapAlgorithmAsset.jurisdiction_country == jurisdiction_country,
            PapAlgorithmAsset.tax_year == tax_year,
            PapAlgorithmAsset.pap_version == pap_version,
        )
        .first()
    )
    if existing_identity:
        raise BadRequestException(
            f"PAP asset {pap_version!r} for {jurisdiction_country}/{tax_year} already exists (#{existing_identity.id})."
        )

    source = SourceArtifact(
        agency=source_agency, title=source_title, source_url=source_url,
        publication_date=source_publication_date, checksum_sha256=computed_hash,
    )
    db.add(source)
    db.flush()  # assign source.id without a separate partial commit

    row = PapAlgorithmAsset(
        jurisdiction_country=jurisdiction_country, tax_year=tax_year, pap_version=pap_version,
        effective_from=effective_from, effective_to=effective_to, status="DRAFT",
        source_document_id=source.id, source_content_path=source_content_path,
        source_content_sha256=computed_hash, created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="pap_algorithm_asset", entity_id=row.id,
        old_value=None,
        new_value={
            "jurisdiction_country": jurisdiction_country, "tax_year": tax_year, "pap_version": pap_version,
            "effective_from": str(effective_from), "effective_to": str(effective_to) if effective_to else None,
            "source_content_sha256": computed_hash,
        },
    )
    return row


def set_pap_asset_status(db: Session, asset_id: int, status: str, actor_id: Optional[int] = None) -> PapAlgorithmAsset:
    """Advance a PAP asset's lifecycle. Mirrors
    set_jurisdiction_pack_status's exact maker-checker gate and "only one
    currently-published version per scope" conflict guard, under Germany's
    own status vocabulary (see PapAlgorithmAsset's docstring for why the
    vocabulary differs from JurisdictionPack's)."""
    row = get_pap_asset_by_id(db, asset_id)
    if status not in _PAP_VALID_STATUSES:
        raise BadRequestException(f"Unknown PAP asset status: {status!r}.")
    if status not in _PAP_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move a PAP asset from {row.status} to {status}.")

    if status == "PUBLISHED":
        conflict = (
            db.query(PapAlgorithmAsset)
            .filter(
                PapAlgorithmAsset.id != row.id,
                PapAlgorithmAsset.jurisdiction_country == row.jurisdiction_country,
                PapAlgorithmAsset.tax_year == row.tax_year,
                PapAlgorithmAsset.status == "PUBLISHED",
            )
            .first()
        )
        if conflict:
            raise BadRequestException(
                f"PAP asset #{conflict.id} ({conflict.pap_version}) is already PUBLISHED for "
                f"{row.jurisdiction_country}/{row.tax_year} — supersede it before publishing a new version."
            )
        # Maker-checker: the same "author cannot self-approve" rule
        # set_jurisdiction_pack_status enforces (ZP-TAX-UK-2026-27-001
        # §19.2), applied here to Germany's own vocabulary. row.updated_by_id
        # is read BEFORE this call's own reassignment below.
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This PAP asset needs a distinct approver before it can be published — "
                "use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.source_content_sha256:
            raise BadRequestException("A PAP asset cannot be published without a recorded source content hash.")

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="pap_algorithm_asset", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_pap_asset_approver(db: Session, asset_id: int, actor_id: Optional[int] = None) -> PapAlgorithmAsset:
    """Sets approved_by_id — the same distinct, lightweight "I, this
    specific person, reviewed and approve this" action as
    set_jurisdiction_pack_approver, required before set_pap_asset_status
    will allow a move to PUBLISHED. Auto-advances REVIEW -> APPROVED (only
    from REVIEW — a status chosen on purpose elsewhere is left alone),
    mirroring set_jurisdiction_pack_approver's own Draft -> Approved
    shortcut at the equivalent point in this vocabulary's chain."""
    row = get_pap_asset_by_id(db, asset_id)
    _require_editable_pap_asset(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "REVIEW":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="pap_algorithm_asset", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


def resolve_germany_pap_asset(
    db: Session, payroll_date: date, jurisdiction_country: str = "DE", tax_year: Optional[str] = None,
) -> Optional[PapAlgorithmAsset]:
    """Return the PUBLISHED PAP asset applicable on `payroll_date` — the
    contract a future Germany wage-tax execution phase will call. Returns
    None (never raises) if none is published yet for this
    jurisdiction/date, mirroring engine.tax_resolver.resolve_tax_configuration's
    "no canonical config yet, caller falls back" contract. Does NOT
    execute, parse, or interpret the returned asset in any way — that is
    out of scope for this phase and every phase before a PAP executor
    exists.

    Only status=="PUBLISHED" is resolved — a SUPERSEDED asset is not
    returned even for a historical date within its own effective window,
    deliberately mirroring engine.tax_resolver._find_active_tax_pack's
    already-shipped behavior (Phase 1 confirmed this directly): long-term
    historical reproducibility is guaranteed by the immutable per-payslip
    snapshot, not by re-querying a superseded config row."""
    query = db.query(PapAlgorithmAsset).filter(
        PapAlgorithmAsset.jurisdiction_country == jurisdiction_country,
        PapAlgorithmAsset.status == "PUBLISHED",
        PapAlgorithmAsset.effective_from <= payroll_date,
        (PapAlgorithmAsset.effective_to.is_(None)) | (PapAlgorithmAsset.effective_to >= payroll_date),
    )
    if tax_year:
        query = query.filter(PapAlgorithmAsset.tax_year == tax_year)
    return query.order_by(PapAlgorithmAsset.effective_from.desc()).first()


# ── Germany: BMF PAP Production Release Governance (Phase 8G-1) ──────────
# See models.GermanyPapRelease's own module-level docstring for why this
# is a separate table/lifecycle from PapAlgorithmAsset's statutory one.
# Nothing here changes resolve_pap_executor()'s behavior — germany_pap/
# core.py is never imported by this section, and this section never
# imports from it either, beyond the pure, DB-free
# engine.germany_pap.production_gate module.

_PAP_RELEASE_VALID_STATUSES = (
    "NOT_READY", "READY_FOR_RELEASE", "RELEASE_APPROVED",
    "ACTIVATION_BLOCKED", "ACTIVE", "ROLLBACK_REQUESTED", "ROLLBACK_APPROVED", "ROLLED_BACK",
)
_PAP_RELEASE_ALLOWED_TRANSITIONS = {
    "NOT_READY": {"READY_FOR_RELEASE"},
    "READY_FOR_RELEASE": {"RELEASE_APPROVED", "NOT_READY"},
    "RELEASE_APPROVED": {"ACTIVE", "ACTIVATION_BLOCKED", "NOT_READY"},
    "ACTIVATION_BLOCKED": {"ACTIVE", "ACTIVATION_BLOCKED"},
    # Phase 8H: rollback is now its own maker-checker'd sub-lifecycle,
    # never a direct ACTIVE -> ROLLED_BACK jump, and never a way back into
    # ACTIVE except by activating a (possibly different) RELEASE_APPROVED
    # row through the ordinary path — ROLLED_BACK remains terminal.
    "ACTIVE": {"ROLLBACK_REQUESTED"},
    "ROLLBACK_REQUESTED": {"ROLLBACK_APPROVED", "ACTIVE"},  # ACTIVE = rejected, rollback abandoned
    "ROLLBACK_APPROVED": {"ROLLED_BACK"},
    "ROLLED_BACK": set(),
}
_PAP_RELEASE_FINALITY_STATUSES = ("OPEN", "VERIFIED", "SUPERSEDED", "REJECTED")
_PAP_RELEASE_LICENSING_STATUSES = ("PENDING", "AUTHORIZED", "DENIED")


def get_pap_release_by_id(db: Session, release_id: int) -> GermanyPapRelease:
    row = db.query(GermanyPapRelease).filter(GermanyPapRelease.id == release_id).first()
    if not row:
        raise NotFoundException("GermanyPapRelease", release_id)
    return row


def list_pap_releases(
    db: Session, jurisdiction_country: str = "DE", tax_year: Optional[str] = None,
) -> List[GermanyPapRelease]:
    query = db.query(GermanyPapRelease).join(
        PapAlgorithmAsset, GermanyPapRelease.pap_asset_id == PapAlgorithmAsset.id,
    ).filter(PapAlgorithmAsset.jurisdiction_country == jurisdiction_country)
    if tax_year:
        query = query.filter(PapAlgorithmAsset.tax_year == tax_year)
    return query.order_by(GermanyPapRelease.created_at.desc()).all()


def create_pap_release(db: Session, pap_asset_id: int, actor_id: Optional[int] = None) -> GermanyPapRelease:
    """Start a release/activation-governance attempt for one PAP asset.
    Binds the asset's OWN current source_content_sha256 at creation time —
    never caller-supplied — so a later hash drift on the asset is
    detectable (see _pap_release_gate_snapshot). One release row per
    asset (uq_pap_release_one_per_asset); a second attempt must reuse the
    existing row rather than create a duplicate."""
    asset = get_pap_asset_by_id(db, pap_asset_id)
    existing = db.query(GermanyPapRelease).filter(GermanyPapRelease.pap_asset_id == pap_asset_id).first()
    if existing:
        raise BadRequestException(
            f"A release record (#{existing.id}, status={existing.status}) already exists for PAP asset "
            f"#{pap_asset_id} — reuse it instead of creating a duplicate."
        )
    row = GermanyPapRelease(
        pap_asset_id=pap_asset_id,
        jurisdiction_country=asset.jurisdiction_country,
        tax_year=asset.tax_year,
        bound_source_content_sha256=asset.source_content_sha256,
        status="NOT_READY",
        prepared_by_id=actor_id,
        prepared_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="pap_release", entity_id=row.id,
        old_value=None, new_value={"pap_asset_id": pap_asset_id, "bound_source_content_sha256": row.bound_source_content_sha256},
    )
    return row


def _require_pap_release_editable(row: GermanyPapRelease) -> None:
    if row.status in ("ACTIVE", "ROLLED_BACK"):
        raise BadRequestException(
            f"PAP release #{row.id} is {row.status} — evidence can no longer be edited on this record."
        )


def record_pap_release_source_identity(
    db: Session, release_id: int, actor_id: Optional[int] = None, notes: Optional[str] = None,
) -> GermanyPapRelease:
    row = get_pap_release_by_id(db, release_id)
    _require_pap_release_editable(row)
    row.source_identity_verified = True
    row.source_identity_verified_by_id = actor_id
    row.source_identity_verified_at = datetime.utcnow()
    row.source_identity_notes = notes
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="pap_release", entity_id=row.id,
        old_value=None, new_value={"source_identity_verified": True}, reason="Source identity verified",
    )
    return row


def record_pap_release_source_hash_verification(
    db: Session, release_id: int, actor_id: Optional[int] = None,
) -> GermanyPapRelease:
    """Records that a human independently re-verified the bound hash
    against the live source (Phase 8F's own re-download-and-compare
    method). This does NOT re-compute a hash itself — service.py never
    silently re-downloads BMF source during a release action, matching
    Phase 8F/8G-1's performance rule (no dynamic source downloads during
    payroll/governance operations). It only records the attestation and
    (defensively) refuses if the asset's live hash has since drifted from
    what this release is bound to."""
    row = get_pap_release_by_id(db, release_id)
    _require_pap_release_editable(row)
    asset = get_pap_asset_by_id(db, row.pap_asset_id)
    if not asset.source_content_sha256 or asset.source_content_sha256 != row.bound_source_content_sha256:
        raise BadRequestException(
            "The PAP asset's current source_content_sha256 no longer matches this release's bound hash — "
            "cannot verify. Investigate the drift before proceeding; a new release record may be required."
        )
    row.source_hash_verified = True
    row.source_hash_verified_by_id = actor_id
    row.source_hash_verified_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="pap_release", entity_id=row.id,
        old_value=None, new_value={"source_hash_verified": True, "sha256": row.bound_source_content_sha256},
        reason="Source hash re-verified",
    )
    return row


def record_pap_release_source_finality(
    db: Session, release_id: int, actor_id: Optional[int], status: str,
    authority: Optional[str] = None, reference: Optional[str] = None, notes: Optional[str] = None,
) -> GermanyPapRelease:
    """Records source-finality EVIDENCE on this release row. Deliberately
    independent of, and never writes to, germany_pap.adapter.PAP_SOURCE_FINALITY
    — that module-level constant is a separate, hardcoded, non-bypassable
    code gate (Phase 8C-2) and is not touched anywhere in this phase. This
    field only feeds this release's own gate evaluation (§9)."""
    if status not in _PAP_RELEASE_FINALITY_STATUSES:
        raise BadRequestException(f"Unknown source-finality status: {status!r}.")
    row = get_pap_release_by_id(db, release_id)
    _require_pap_release_editable(row)
    row.source_finality_status = status
    row.source_finality_authority = authority
    row.source_finality_reference = reference
    row.source_finality_verified_by_id = actor_id
    row.source_finality_verified_at = datetime.utcnow()
    row.source_finality_notes = notes
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="pap_release", entity_id=row.id,
        old_value=None, new_value={"source_finality_status": status, "authority": authority, "reference": reference},
        reason="Source finality evidence recorded",
    )
    return row


def record_pap_release_licensing(
    db: Session, release_id: int, actor_id: Optional[int], status: str,
    authority: Optional[str] = None, reference: Optional[str] = None,
    authorization_date: Optional[date] = None, effective_date: Optional[date] = None,
    expiry_date: Optional[date] = None, evidence_location: Optional[str] = None,
    evidence_hash: Optional[str] = None, notes: Optional[str] = None,
) -> GermanyPapRelease:
    """Records licensing/commercial-use authorization EVIDENCE. Real
    authorization must originate outside engineering (legal counsel /
    direct BMF consent) — this function never invents, defaults-to-true,
    or infers a status; the caller must explicitly pass whatever the real
    evidence supports, and "AUTHORIZED" with no reference/evidence_location
    is accepted mechanically but is exactly the kind of unsupported claim
    the phase brief warns against recording — Super Admin process, not
    this function, is responsible for only calling this with real evidence."""
    if status not in _PAP_RELEASE_LICENSING_STATUSES:
        raise BadRequestException(f"Unknown licensing status: {status!r}.")
    row = get_pap_release_by_id(db, release_id)
    _require_pap_release_editable(row)
    row.licensing_status = status
    row.licensing_authority = authority
    row.licensing_reference = reference
    row.licensing_authorization_date = authorization_date
    row.licensing_effective_date = effective_date
    row.licensing_expiry_date = expiry_date
    row.licensing_evidence_location = evidence_location
    row.licensing_evidence_hash = evidence_hash
    row.licensing_notes = notes
    row.licensing_recorded_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="pap_release", entity_id=row.id,
        old_value=None, new_value={"licensing_status": status, "authority": authority, "reference": reference},
        reason="Licensing evidence recorded",
    )
    return row


def record_pap_release_golden_vectors(
    db: Session, release_id: int, actor_id: Optional[int], source_sha256: str, notes: Optional[str] = None,
) -> GermanyPapRelease:
    """Records that golden-vector certification passed for THIS EXACT
    source hash. A certification run against a different hash (a
    different PAP version's bytes) is rejected outright — certifying
    version A must never be accepted as proof for version B (§12)."""
    row = get_pap_release_by_id(db, release_id)
    _require_pap_release_editable(row)
    if not row.bound_source_content_sha256 or source_sha256 != row.bound_source_content_sha256:
        raise BadRequestException(
            "Golden-vector certification hash does not match this release's bound source hash — "
            "certification for a different PAP version/source cannot be accepted here."
        )
    row.golden_vectors_passed = True
    row.golden_vectors_source_sha256 = source_sha256
    row.golden_vectors_verified_by_id = actor_id
    row.golden_vectors_verified_at = datetime.utcnow()
    row.golden_vectors_notes = notes
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="pap_release", entity_id=row.id,
        old_value=None, new_value={"golden_vectors_passed": True, "source_sha256": source_sha256},
        reason="Golden-vector certification recorded",
    )
    return row


def record_pap_release_security_certification(
    db: Session, release_id: int, actor_id: Optional[int] = None, notes: Optional[str] = None,
) -> GermanyPapRelease:
    row = get_pap_release_by_id(db, release_id)
    _require_pap_release_editable(row)
    row.security_certified = True
    row.security_certified_by_id = actor_id
    row.security_certified_at = datetime.utcnow()
    row.security_notes = notes
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="pap_release", entity_id=row.id,
        old_value=None, new_value={"security_certified": True}, reason="Security certification recorded",
    )
    return row


def mark_pap_release_ready(db: Session, release_id: int, actor_id: Optional[int] = None) -> GermanyPapRelease:
    """NOT_READY -> READY_FOR_RELEASE — "I am done preparing evidence,
    ready for an independent checker." Mirrors PapAlgorithmAsset's own
    DRAFT -> REVIEW step."""
    row = get_pap_release_by_id(db, release_id)
    if row.status != "NOT_READY":
        raise BadRequestException(f"Cannot mark a release ready from status {row.status!r}.")
    old_status = row.status
    row.status = "READY_FOR_RELEASE"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="pap_release", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": row.status},
    )
    return row


def approve_pap_release(db: Session, release_id: int, actor_id: Optional[int] = None) -> GermanyPapRelease:
    """Release approval — maker-checker #1. The approver must differ from
    whoever prepared the release (the same "distinct actor" rule every
    other Germany registry's publish step already enforces, e.g.
    set_pap_asset_status). This does NOT evaluate the compound gate and
    does NOT authorize activation — see activate_pap_release for that
    separate, later step (§7/§16 of the phase brief: technical
    certification, licensing, and release approval are different gates)."""
    row = get_pap_release_by_id(db, release_id)
    if row.status != "READY_FOR_RELEASE":
        raise BadRequestException(f"Cannot approve a release from status {row.status!r} — must be READY_FOR_RELEASE.")
    if actor_id is not None and actor_id == row.prepared_by_id:
        raise BadRequestException(
            "This release needs a distinct approver — use a different Super Admin than whoever prepared it."
        )
    row.approved_by_id = actor_id
    row.approved_at = datetime.utcnow()
    row.status = "RELEASE_APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="pap_release", entity_id=row.id,
        old_value={"status": "READY_FOR_RELEASE"}, new_value={"status": "RELEASE_APPROVED", "approved_by_id": actor_id},
        reason="Release approved",
    )
    return row


def reject_pap_release(db: Session, release_id: int, actor_id: Optional[int], reason: Optional[str] = None) -> GermanyPapRelease:
    row = get_pap_release_by_id(db, release_id)
    if row.status not in ("READY_FOR_RELEASE", "RELEASE_APPROVED"):
        raise BadRequestException(f"Cannot reject a release from status {row.status!r}.")
    old_status = row.status
    row.status = "NOT_READY"
    row.rejected_by_id = actor_id
    row.rejected_at = datetime.utcnow()
    row.rejection_reason = reason
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="pap_release", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": "NOT_READY"}, reason=reason or "Release rejected",
    )
    return row


def _pap_release_gate_snapshot(db: Session, row: GermanyPapRelease) -> dict:
    """Builds the input the pure engine.germany_pap.production_gate module
    evaluates. Every derived value re-checks LIVE state (the asset's
    current status/hash) rather than trusting anything cached on the
    release row — fail-closed by construction, per Phase 8G-1 §6/§18."""
    asset = db.query(PapAlgorithmAsset).filter(PapAlgorithmAsset.id == row.pap_asset_id).first()
    hash_ok = bool(
        row.source_hash_verified
        and asset is not None
        and asset.source_content_sha256
        and row.bound_source_content_sha256
        and asset.source_content_sha256 == row.bound_source_content_sha256
    )
    golden_ok = bool(
        row.golden_vectors_passed
        and row.golden_vectors_source_sha256
        and row.golden_vectors_source_sha256 == row.bound_source_content_sha256
        and hash_ok
    )
    release_approved_ok = bool(
        row.approved_by_id is not None
        and row.prepared_by_id is not None
        and row.approved_by_id != row.prepared_by_id
    )
    return {
        "source_identity_verified": bool(row.source_identity_verified),
        "source_hash_verified": hash_ok,
        "source_finality_verified": row.source_finality_status == "VERIFIED",
        "licensing_authorized": row.licensing_status == "AUTHORIZED",
        "asset_approved": bool(asset is not None and asset.status == "PUBLISHED"),
        "golden_vectors_passed": golden_ok,
        "security_certified": bool(row.security_certified),
        "release_approved": release_approved_ok,
    }


def evaluate_pap_release_gate(db: Session, release_id: int) -> "pap_production_gate.GateEvaluationResult":
    """Read-only: evaluates every gate dimension for this release right
    now, without changing any state. Used both by a preview/inspection
    endpoint and internally by activate_pap_release."""
    row = get_pap_release_by_id(db, release_id)
    snapshot = _pap_release_gate_snapshot(db, row)
    return pap_production_gate.evaluate(snapshot)


def activate_pap_release(db: Session, release_id: int, actor_id: Optional[int] = None) -> GermanyPapRelease:
    """Activation — a DISTINCT operation from release approval (§16),
    requiring the full compound gate (§6) to be satisfied AND a distinct
    activator (maker-checker #2, vs whoever approved the release). Even
    on success, this ONLY flips this governance row's own status to
    ACTIVE — it does not call, import, or affect resolve_pap_executor()
    in any way (see germany_pap/production_gate.py's own module
    docstring). No production tax result can ever originate from this
    function."""
    row = get_pap_release_by_id(db, release_id)
    if row.status not in ("RELEASE_APPROVED", "ACTIVATION_BLOCKED"):
        raise BadRequestException(
            f"Cannot activate a release from status {row.status!r} — must be RELEASE_APPROVED or ACTIVATION_BLOCKED."
        )
    result = evaluate_pap_release_gate(db, release_id)
    if not result.is_activation_eligible:
        row.status = "ACTIVATION_BLOCKED"
        db.commit()
        record_tax_audit(
            db, actor_id=actor_id, action="activation_blocked", entity_type="pap_release", entity_id=row.id,
            old_value=None, new_value={"failed_gates": list(result.failed_gates)},
            reason="Activation attempt failed the compound production gate",
        )
        raise GermanyPapGateBlockedException(failed_gates=list(result.failed_gates))

    if actor_id is not None and actor_id == row.approved_by_id:
        raise BadRequestException(
            "Activation needs a distinct actor — use a different Super Admin than whoever approved the release."
        )

    asset = get_pap_asset_by_id(db, row.pap_asset_id)
    conflict = (
        db.query(GermanyPapRelease)
        .join(PapAlgorithmAsset, GermanyPapRelease.pap_asset_id == PapAlgorithmAsset.id)
        .filter(
            GermanyPapRelease.id != row.id,
            GermanyPapRelease.status == "ACTIVE",
            PapAlgorithmAsset.jurisdiction_country == asset.jurisdiction_country,
            PapAlgorithmAsset.tax_year == asset.tax_year,
        )
        .first()
    )
    if conflict:
        raise BadRequestException(
            f"Release #{conflict.id} is already ACTIVE for {asset.jurisdiction_country}/{asset.tax_year} — "
            "roll it back before activating a different release for the same scope."
        )

    row.status = "ACTIVE"
    row.activated_by_id = actor_id
    row.activated_at = datetime.utcnow()
    try:
        db.commit()
    except IntegrityError:
        # True DB-level concurrency backstop (Phase 8H §17-19): the
        # service-layer conflict SELECT above is a defense-in-depth
        # convenience (same pattern PapAlgorithmAsset's PUBLISHED-conflict
        # check already uses), not the actual guarantee — the guarantee is
        # uq_pap_release_one_active_per_scope (models.py), which the
        # database itself enforces even if two concurrent transactions
        # both passed the SELECT check before either committed. Whichever
        # transaction commits second hits this exact branch.
        db.rollback()
        raise BadRequestException(
            f"Another release was activated for {asset.jurisdiction_country}/{asset.tax_year} "
            "concurrently with this request — refusing to create a second ACTIVE release for the same scope."
        )
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="activated", entity_type="pap_release", entity_id=row.id,
        old_value=None, new_value={"status": "ACTIVE", "gates": result.gates},
        reason="All production gates satisfied; release activated",
    )
    return row


def request_pap_rollback(
    db: Session, release_id: int, actor_id: Optional[int], reason: Optional[str] = None,
) -> GermanyPapRelease:
    """Rollback maker-checker step 1 of 3 (Phase 8H). Anyone who can reach
    this Super-Admin-only endpoint may REQUEST a rollback of an ACTIVE
    release; the request alone changes nothing about which release is
    live — only approve_pap_rollback (§ below), by a DISTINCT actor,
    actually performs the rollback."""
    row = get_pap_release_by_id(db, release_id)
    if row.status != "ACTIVE":
        raise BadRequestException(f"Only an ACTIVE release can have a rollback requested (current status: {row.status!r}).")
    row.status = "ROLLBACK_REQUESTED"
    row.rollback_requested_by_id = actor_id
    row.rollback_requested_at = datetime.utcnow()
    row.rollback_reason = reason
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="rollback_requested", entity_type="pap_release", entity_id=row.id,
        old_value={"status": "ACTIVE"}, new_value={"status": "ROLLBACK_REQUESTED"}, reason=reason or "Rollback requested",
    )
    return row


def reject_pap_rollback(
    db: Session, release_id: int, actor_id: Optional[int], reason: Optional[str] = None,
) -> GermanyPapRelease:
    """Abandons a requested rollback — the release simply remains ACTIVE.
    No maker-checker distinctness is required to reject (rejecting is the
    conservative, non-destructive choice; only APPROVING a rollback needs
    a distinct actor from whoever requested it)."""
    row = get_pap_release_by_id(db, release_id)
    if row.status != "ROLLBACK_REQUESTED":
        raise BadRequestException(f"Cannot reject a rollback from status {row.status!r} — must be ROLLBACK_REQUESTED.")
    row.status = "ACTIVE"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="rollback_rejected", entity_type="pap_release", entity_id=row.id,
        old_value={"status": "ROLLBACK_REQUESTED"}, new_value={"status": "ACTIVE"}, reason=reason or "Rollback rejected",
    )
    return row


def approve_pap_rollback(
    db: Session, release_id: int, actor_id: Optional[int], target_release_id: Optional[int] = None,
):
    """Rollback maker-checker step 2/3 of 3 (Phase 8H). The approver MUST
    differ from whoever requested the rollback (`rollback_requested_by_id`)
    — the same minimum-viable distinct-actor rule as release approval and
    activation. On approval, the release moves ROLLBACK_REQUESTED ->
    ROLLBACK_APPROVED -> ROLLED_BACK in one transaction (both status
    values are recorded via separate audit events, matching §22's
    required event list), and never deletes/rewrites any row. Never
    touches any PayslipItem/statutory snapshot — this table has no
    relationship to any payslip table at all. If `target_release_id` is
    given, that release is restored to ACTIVE — but only if it belongs to
    the same country/tax-year scope and was itself previously activated
    (`activated_at` set); otherwise this fails closed rather than
    guessing at a "safe" version to restore."""
    row = get_pap_release_by_id(db, release_id)
    if row.status != "ROLLBACK_REQUESTED":
        raise BadRequestException(f"Cannot approve a rollback from status {row.status!r} — must be ROLLBACK_REQUESTED.")
    if actor_id is not None and actor_id == row.rollback_requested_by_id:
        raise BadRequestException(
            "Rollback approval needs a distinct actor — use a different Super Admin than whoever requested it."
        )

    row.status = "ROLLBACK_APPROVED"
    row.rollback_approved_by_id = actor_id
    row.rollback_approved_at = datetime.utcnow()
    db.commit()
    record_tax_audit(
        db, actor_id=actor_id, action="rollback_approved", entity_type="pap_release", entity_id=row.id,
        old_value={"status": "ROLLBACK_REQUESTED"}, new_value={"status": "ROLLBACK_APPROVED"},
        reason="Rollback approved by a distinct actor",
    )

    old_status = row.status
    row.status = "ROLLED_BACK"
    row.rolled_back_by_id = actor_id
    row.rolled_back_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="rollback_completed", entity_type="pap_release", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": "ROLLED_BACK"}, reason=row.rollback_reason or "Rollback completed",
    )

    restored = None
    if target_release_id is not None:
        if target_release_id == row.id:
            raise BadRequestException("Rollback target must differ from the release being rolled back.")
        target = get_pap_release_by_id(db, target_release_id)
        current_asset = get_pap_asset_by_id(db, row.pap_asset_id)
        target_asset = get_pap_asset_by_id(db, target.pap_asset_id)
        if (target_asset.jurisdiction_country, target_asset.tax_year) != (
            current_asset.jurisdiction_country, current_asset.tax_year,
        ):
            raise BadRequestException("Rollback target must be a release of the same country/tax-year scope.")
        if target.activated_at is None:
            raise BadRequestException(
                "Rollback target was never previously activated — refusing to activate an unproven release."
            )
        if target.status == "ACTIVE":
            raise BadRequestException(f"Rollback target #{target.id} is already ACTIVE.")
        target.status = "ACTIVE"
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise BadRequestException(
                "Another release is already ACTIVE for this scope — cannot restore the rollback target concurrently."
            )
        db.refresh(target)
        record_tax_audit(
            db, actor_id=actor_id, action="rollback_restore", entity_type="pap_release", entity_id=target.id,
            old_value=None, new_value={"status": "ACTIVE", "restored_from_release_id": row.id},
            reason=f"Restored via rollback of release #{row.id}",
        )
        restored = target
    return row, restored


# ── Germany: Krankenkasse (Health Fund) Registry (ZP-TAX-DE-2026-001 §11) ─
# Configuration/registry only — see models.GermanyHealthFund's own
# docstring and docs/PHASE_4_GERMANY_HEALTH_FUND_REGISTRY_REPORT.md. NO
# GKV contribution calculation exists here or anywhere else in this
# codebase; germany.py is unchanged and does not read from this table, and
# EmployeeStatutoryProfile.de_health_fund_code is NOT wired to it (see
# Phase 4 report §3/§22 Q2 for why that connection is deferred).
#
# Status vocabulary — DRAFT/VERIFIED/APPROVED/PUBLISHED/SUPERSEDED — is
# spec §11's own literal status row for THIS registry (deliberately not
# PapAlgorithmAsset's DRAFT/REVIEW/APPROVED/PUBLISHED/SUPERSEDED — "REVIEW"
# vs "VERIFIED" is a real, source-traced difference, not a typo).
#
# Overlap model deliberately differs from PapAlgorithmAsset's (see the
# model's own docstring): every version of a fund's rate — past, current,
# or future — must remain independently resolvable by date, so there is
# no "only one PUBLISHED at a time" guard here. Instead, overlap
# prevention is a general range check across ALL of a fund's rows
# (any status), mirroring EmployeeStatutoryProfile's
# _validate_statutory_profile_no_overlap exactly.

_HEALTH_FUND_EDITABLE_STATUSES = ("DRAFT", "VERIFIED", "APPROVED")
_HEALTH_FUND_VALID_STATUSES = ("DRAFT", "VERIFIED", "APPROVED", "PUBLISHED", "SUPERSEDED")
_HEALTH_FUND_ALLOWED_TRANSITIONS = {
    "DRAFT": {"VERIFIED"},
    "VERIFIED": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "VERIFIED"},
    # PUBLISHED -> SUPERSEDED is reserved for an explicit correction of an
    # erroneously published row — NOT the normal "a later rate now
    # applies" case, which is simply a second, later-effective-dated
    # PUBLISHED row coexisting with this one.
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_health_fund(row: GermanyHealthFund) -> None:
    if row.status not in _HEALTH_FUND_EDITABLE_STATUSES:
        raise BadRequestException(
            f"Health fund record {row.health_fund_id} ({row.effective_from}) is {row.status} — no longer "
            "editable. Record a new effective-dated version instead."
        )


def _validate_health_fund_no_overlap(
    db: Session, health_fund_id: str, effective_from: date, effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    """Same "no two overlapping ranges for the same identity" check as
    EmployeeStatutoryProfile._validate_statutory_profile_no_overlap,
    applied to health_fund_id instead of employee_id — chosen because this
    registry's identity/history shape matches EmployeeStatutoryProfile's,
    not PapAlgorithmAsset's (see the model's own docstring)."""
    query = db.query(GermanyHealthFund).filter(GermanyHealthFund.health_fund_id == health_fund_id)
    if exclude_id is not None:
        query = query.filter(GermanyHealthFund.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing health fund "
                f"record #{existing.id} for {health_fund_id} ({existing.effective_from} to "
                f"{existing.effective_to or 'open-ended'}). Close or adjust that record first."
            )


def list_health_funds(db: Session, health_fund_id: Optional[str] = None) -> List[GermanyHealthFund]:
    query = db.query(GermanyHealthFund)
    if health_fund_id:
        query = query.filter(GermanyHealthFund.health_fund_id == health_fund_id)
    return query.order_by(GermanyHealthFund.health_fund_id, GermanyHealthFund.effective_from.desc()).all()


def get_health_fund_by_id(db: Session, record_id: int) -> GermanyHealthFund:
    row = db.query(GermanyHealthFund).filter(GermanyHealthFund.id == record_id).first()
    if not row:
        raise NotFoundException("GermanyHealthFund", record_id)
    return row


def create_health_fund_record(
    db: Session, data: GermanyHealthFundCreate, actor_id: Optional[int] = None,
    auto_close_previous: bool = True,
) -> GermanyHealthFund:
    """Append a new effective-dated health-fund rate version. Never updates
    an existing row. Mirrors create_employee_statutory_profile_version's
    auto-close-previous-open-row behavior (the same "this fund's rate
    changes on this date going forward" case), not PapAlgorithmAsset's
    manual-supersession requirement — see this module's section header for
    why the two registries use different overlap models."""
    if not data.health_fund_id or not data.health_fund_id.strip():
        raise BadRequestException("healthFundId is required.")
    if not data.fund_name or not data.fund_name.strip():
        raise BadRequestException("fundName is required.")
    if data.supplementary_rate_pct is None or data.supplementary_rate_pct < 0:
        raise BadRequestException("supplementaryRatePct must be a non-negative value.")
    if data.u1_rate_pct is not None and data.u1_rate_pct < 0:
        raise BadRequestException("u1RatePct must not be negative.")
    if data.u2_rate_pct is not None and data.u2_rate_pct < 0:
        raise BadRequestException("u2RatePct must not be negative.")
    if data.effective_to is not None and data.effective_to < data.effective_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")

    previous_open = (
        db.query(GermanyHealthFund)
        .filter(
            GermanyHealthFund.health_fund_id == data.health_fund_id,
            GermanyHealthFund.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(
        auto_close_previous and previous_open and previous_open.effective_from < data.effective_from
    )
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_health_fund_no_overlap(
        db, data.health_fund_id, data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = GermanyHealthFund(
        health_fund_id=data.health_fund_id, fund_name=data.fund_name,
        supplementary_rate_pct=data.supplementary_rate_pct, is_average_rate=data.is_average_rate,
        u1_rate_pct=data.u1_rate_pct, u2_rate_pct=data.u2_rate_pct,
        effective_from=data.effective_from, effective_to=data.effective_to,
        member_applicability=data.member_applicability, payroll_recalc_policy=data.payroll_recalc_policy,
        authority_source_id=data.authority_source_id, status="DRAFT",
        created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_health_fund", entity_id=row.id,
        old_value=None,
        new_value={
            "health_fund_id": data.health_fund_id, "fund_name": data.fund_name,
            "supplementary_rate_pct": str(data.supplementary_rate_pct), "is_average_rate": data.is_average_rate,
            "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
    )
    return row


def set_health_fund_status(db: Session, record_id: int, status: str, actor_id: Optional[int] = None) -> GermanyHealthFund:
    """Advance a health-fund record's lifecycle. Reuses PapAlgorithmAsset's
    maker-checker principle (distinct approver required before PUBLISHED)
    even though the two registries' overlap models differ — that
    principle is identity-shape-independent."""
    row = get_health_fund_by_id(db, record_id)
    if status not in _HEALTH_FUND_VALID_STATUSES:
        raise BadRequestException(f"Unknown health fund record status: {status!r}.")
    if status not in _HEALTH_FUND_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move a health fund record from {row.status} to {status}.")

    if status == "PUBLISHED":
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This health fund record needs a distinct approver before it can be published — "
                "use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.authority_source_id:
            raise BadRequestException(
                "A health fund record cannot be published without a linked source evidence artifact "
                "(authoritySourceId) — record one via /compliance/source-artifacts first."
            )

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_health_fund", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_health_fund_approver(db: Session, record_id: int, actor_id: Optional[int] = None) -> GermanyHealthFund:
    """Sets approved_by_id — same distinct, lightweight action as
    set_pap_asset_approver/set_jurisdiction_pack_approver. Auto-advances
    VERIFIED -> APPROVED only (a status chosen on purpose elsewhere is
    left alone)."""
    row = get_health_fund_by_id(db, record_id)
    _require_editable_health_fund(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "VERIFIED":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_health_fund", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


def resolve_germany_health_fund(db: Session, health_fund_id: str, as_of: Optional[date] = None) -> Optional[GermanyHealthFund]:
    """Return the PUBLISHED rate record applicable on `as_of` (defaults to
    today) for one specific fund. Returns None (never raises) if no
    published record covers that date — the future GKV calculation phase
    must treat that as "no configured rate for this fund/date," never as
    license to fall back to the 2.9% statutory average (spec's own
    "AVERAGE RATE WARNING" — see this module's section header). Unlike
    resolve_germany_pap_asset, a SUPERSEDED record for a DIFFERENT,
    non-overlapping period is irrelevant here by construction (overlap
    prevention already guarantees at most one PUBLISHED row can cover any
    given date for a given fund); SUPERSEDED only ever applies to a
    retracted erroneous row, which correctly must not resolve."""
    as_of = as_of or date.today()
    return (
        db.query(GermanyHealthFund)
        .filter(
            GermanyHealthFund.health_fund_id == health_fund_id,
            GermanyHealthFund.status == "PUBLISHED",
            GermanyHealthFund.effective_from <= as_of,
            (GermanyHealthFund.effective_to.is_(None)) | (GermanyHealthFund.effective_to >= as_of),
        )
        .order_by(GermanyHealthFund.effective_from.desc())
        .first()
    )


# ── Germany: U1 Tariff (Sickness Reimbursement) (Phase 8W) ────────────
# U1 is employer-elected per tariff — each Krankenkasse publishes multiple
# tariff options (different reimbursement percentages and corresponding levy
# rates). This section manages the AVAILABLE tariffs on the fund side and
# the employer's SELECTED tariff on the employee profile side.
#
# Same lifecycle/overlap model as GermanyHealthFund (Phase 4): every tariff
# version — past, current, or future — must remain independently resolvable
# by date for historical payroll. Overlap prevention is a general range
# check across ALL rows for the same (health_fund_id, tariff_identifier)
# pair, not just PUBLISHED rows.

_U1_TARIFF_EDITABLE_STATUSES = ("DRAFT", "VERIFIED", "APPROVED")
_U1_TARIFF_VALID_STATUSES = ("DRAFT", "VERIFIED", "APPROVED", "PUBLISHED", "SUPERSEDED")
_U1_TARIFF_ALLOWED_TRANSITIONS = {
    "DRAFT": {"VERIFIED"},
    "VERIFIED": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "VERIFIED"},
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_u1_tariff(row: GermanyHealthFundU1Tariff) -> None:
    if row.status not in _U1_TARIFF_EDITABLE_STATUSES:
        raise BadRequestException(
            f"U1 tariff {row.tariff_identifier} for {row.health_fund_id} ({row.effective_from}) is {row.status} — no "
            "longer editable. Record a new effective-dated version instead."
        )


def _validate_u1_tariff_no_overlap(
    db: Session, health_fund_id: str, tariff_identifier: str,
    effective_from: date, effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    """No two overlapping ranges for the same (fund, tariff) pair."""
    query = db.query(GermanyHealthFundU1Tariff).filter(
        GermanyHealthFundU1Tariff.health_fund_id == health_fund_id,
        GermanyHealthFundU1Tariff.tariff_identifier == tariff_identifier,
    )
    if exclude_id is not None:
        query = query.filter(GermanyHealthFundU1Tariff.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing U1 tariff "
                f"record #{existing.id} for {health_fund_id}/{tariff_identifier} ({existing.effective_from} to "
                f"{existing.effective_to or 'open-ended'}). Close or adjust that record first."
            )


def list_u1_tariffs(
    db: Session, health_fund_id: Optional[str] = None,
) -> list[GermanyHealthFundU1Tariff]:
    query = db.query(GermanyHealthFundU1Tariff)
    if health_fund_id:
        query = query.filter(GermanyHealthFundU1Tariff.health_fund_id == health_fund_id)
    return query.order_by(
        GermanyHealthFundU1Tariff.health_fund_id,
        GermanyHealthFundU1Tariff.tariff_identifier,
        GermanyHealthFundU1Tariff.effective_from.desc(),
    ).all()


def get_u1_tariff_by_id(db: Session, record_id: int) -> GermanyHealthFundU1Tariff:
    row = db.query(GermanyHealthFundU1Tariff).filter(GermanyHealthFundU1Tariff.id == record_id).first()
    if not row:
        raise NotFoundException("GermanyHealthFundU1Tariff", record_id)
    return row


def create_u1_tariff_record(
    db: Session, data: GermanyHealthFundU1TariffCreate, actor_id: Optional[int] = None,
    auto_close_previous: bool = True,
) -> GermanyHealthFundU1Tariff:
    """Append a new effective-dated U1 tariff version. Never updates an
    existing row. Mirrors create_health_fund_record's auto-close behavior."""
    if not data.health_fund_id or not data.health_fund_id.strip():
        raise BadRequestException("healthFundId is required.")
    if not data.tariff_identifier or not data.tariff_identifier.strip():
        raise BadRequestException("tariffIdentifier is required.")
    if data.reimbursement_pct is None or data.reimbursement_pct < 0 or data.reimbursement_pct > 100:
        raise BadRequestException("reimbursementPct must be between 0 and 100.")
    if data.levy_rate_pct is None or data.levy_rate_pct < 0:
        raise BadRequestException("levyRatePct must be a non-negative value.")
    if data.effective_to is not None and data.effective_to < data.effective_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")

    previous_open = (
        db.query(GermanyHealthFundU1Tariff)
        .filter(
            GermanyHealthFundU1Tariff.health_fund_id == data.health_fund_id,
            GermanyHealthFundU1Tariff.tariff_identifier == data.tariff_identifier,
            GermanyHealthFundU1Tariff.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(
        auto_close_previous and previous_open and previous_open.effective_from < data.effective_from
    )
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_u1_tariff_no_overlap(
        db, data.health_fund_id, data.tariff_identifier, data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = GermanyHealthFundU1Tariff(
        health_fund_id=data.health_fund_id, tariff_identifier=data.tariff_identifier,
        tariff_name=data.tariff_name, reimbursement_pct=data.reimbursement_pct,
        levy_rate_pct=data.levy_rate_pct, effective_from=data.effective_from,
        effective_to=data.effective_to, authority_source_id=data.authority_source_id,
        status="DRAFT", created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_u1_tariff", entity_id=row.id,
        old_value=None,
        new_value={
            "health_fund_id": data.health_fund_id, "tariff_identifier": data.tariff_identifier,
            "reimbursement_pct": str(data.reimbursement_pct), "levy_rate_pct": str(data.levy_rate_pct),
            "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
    )
    return row


def set_u1_tariff_status(
    db: Session, record_id: int, status: str, actor_id: Optional[int] = None,
) -> GermanyHealthFundU1Tariff:
    """Advance a U1 tariff record's lifecycle. Same maker-checker principle
    as set_health_fund_status."""
    row = get_u1_tariff_by_id(db, record_id)
    if status not in _U1_TARIFF_VALID_STATUSES:
        raise BadRequestException(f"Unknown U1 tariff record status: {status!r}.")
    if status not in _U1_TARIFF_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move a U1 tariff record from {row.status} to {status}.")

    if status == "PUBLISHED":
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This U1 tariff record needs a distinct approver before it can be published — "
                "use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.authority_source_id:
            raise BadRequestException(
                "A U1 tariff record cannot be published without a linked source evidence artifact "
                "(authoritySourceId) — record one via /compliance/source-artifacts first."
            )

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_u1_tariff", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_u1_tariff_approver(
    db: Session, record_id: int, actor_id: Optional[int] = None,
) -> GermanyHealthFundU1Tariff:
    """Sets approved_by_id — same pattern as set_health_fund_approver."""
    row = get_u1_tariff_by_id(db, record_id)
    _require_editable_u1_tariff(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "VERIFIED":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_u1_tariff", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


def resolve_germany_u1_tariff(
    db: Session, health_fund_id: str, tariff_identifier: str,
    as_of: Optional[date] = None,
) -> Optional[GermanyHealthFundU1Tariff]:
    """Return the PUBLISHED U1 tariff record applicable on `as_of` (defaults
    to today) for one specific fund + tariff. Returns None (never raises)
    if no published record covers that date."""
    as_of = as_of or date.today()
    return (
        db.query(GermanyHealthFundU1Tariff)
        .filter(
            GermanyHealthFundU1Tariff.health_fund_id == health_fund_id,
            GermanyHealthFundU1Tariff.tariff_identifier == tariff_identifier,
            GermanyHealthFundU1Tariff.status == "PUBLISHED",
            GermanyHealthFundU1Tariff.effective_from <= as_of,
            (GermanyHealthFundU1Tariff.effective_to.is_(None)) | (GermanyHealthFundU1Tariff.effective_to >= as_of),
        )
        .order_by(GermanyHealthFundU1Tariff.effective_from.desc())
        .first()
    )


# ── Germany: Contribution Ceiling Configuration (ZP-TAX-DE-2026-001 §9) ──
# Configuration/registry only — see models.GermanyContributionCeiling's own
# docstring and docs/PHASE_5_GERMANY_CONTRIBUTION_CEILING_CONFIGURATION_REPORT.md.
# Consumed by calculation: _resolve_germany_calc_inputs() resolves these rows
# as_of the payroll date into PayrollContext.germany_ceiling_gkv_pv /
# germany_ceiling_rv_alv, which engine/countries/germany.py passes to
# calculate_rv/alv/gkv/pv (germany_pap/core.py) to cap the contribution bases
# (wired in Phase 7 — an older comment here claiming the engine "does not read
# from this table" was outdated once that wiring landed and has been corrected).
#
# Same lifecycle/overlap model as GermanyHealthFund (Phase 4), not
# PapAlgorithmAsset (Phase 3): every branch's ceiling version — past,
# current, or future — must remain independently resolvable by date, so
# there is no "only one PUBLISHED at a time" guard; overlap prevention is
# a general range check across ALL of a branch's rows, mirroring
# _validate_health_fund_no_overlap exactly, scoped by `branch` instead of
# `health_fund_id`.

_GERMANY_CONTRIBUTION_BRANCHES = ("GKV_PV", "RV_ALV")
_CONTRIBUTION_CEILING_EDITABLE_STATUSES = ("DRAFT", "VERIFIED", "APPROVED")
_CONTRIBUTION_CEILING_VALID_STATUSES = ("DRAFT", "VERIFIED", "APPROVED", "PUBLISHED", "SUPERSEDED")
_CONTRIBUTION_CEILING_ALLOWED_TRANSITIONS = {
    "DRAFT": {"VERIFIED"},
    "VERIFIED": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "VERIFIED"},
    # PUBLISHED -> SUPERSEDED is reserved for an explicit correction of an
    # erroneously published row — NOT the normal "a new year's ceiling now
    # applies" case, which is simply a second, later-effective-dated
    # PUBLISHED row for the same branch coexisting with this one.
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_contribution_ceiling(row: GermanyContributionCeiling) -> None:
    if row.status not in _CONTRIBUTION_CEILING_EDITABLE_STATUSES:
        raise BadRequestException(
            f"Contribution ceiling record for {row.branch} ({row.effective_from}) is {row.status} — no "
            "longer editable. Record a new effective-dated version instead."
        )


def _validate_contribution_ceiling_no_overlap(
    db: Session, branch: str, effective_from: date, effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    """Same "no two overlapping ranges for the same identity" check as
    _validate_health_fund_no_overlap/_validate_statutory_profile_no_overlap,
    applied to `branch` instead of health_fund_id/employee_id."""
    query = db.query(GermanyContributionCeiling).filter(GermanyContributionCeiling.branch == branch)
    if exclude_id is not None:
        query = query.filter(GermanyContributionCeiling.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing contribution "
                f"ceiling record #{existing.id} for {branch} ({existing.effective_from} to "
                f"{existing.effective_to or 'open-ended'}). Close or adjust that record first."
            )


def list_contribution_ceilings(db: Session, branch: Optional[str] = None) -> List[GermanyContributionCeiling]:
    query = db.query(GermanyContributionCeiling)
    if branch:
        query = query.filter(GermanyContributionCeiling.branch == branch)
    return query.order_by(GermanyContributionCeiling.branch, GermanyContributionCeiling.effective_from.desc()).all()


def get_contribution_ceiling_by_id(db: Session, record_id: int) -> GermanyContributionCeiling:
    row = db.query(GermanyContributionCeiling).filter(GermanyContributionCeiling.id == record_id).first()
    if not row:
        raise NotFoundException("GermanyContributionCeiling", record_id)
    return row


def create_contribution_ceiling_record(
    db: Session, data: GermanyContributionCeilingCreate, actor_id: Optional[int] = None,
    auto_close_previous: bool = True,
) -> GermanyContributionCeiling:
    """Append a new effective-dated contribution-ceiling version for one
    branch. Never updates an existing row. Mirrors
    create_health_fund_record's auto-close-previous-open-row behavior."""
    if data.branch not in _GERMANY_CONTRIBUTION_BRANCHES:
        raise BadRequestException(f"branch must be one of {_GERMANY_CONTRIBUTION_BRANCHES}, got {data.branch!r}.")
    if data.monthly_ceiling is None or data.monthly_ceiling <= 0:
        raise BadRequestException("monthlyCeiling must be a positive value.")
    if data.annual_ceiling is None or data.annual_ceiling <= 0:
        raise BadRequestException("annualCeiling must be a positive value.")
    if data.effective_to is not None and data.effective_to < data.effective_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")

    previous_open = (
        db.query(GermanyContributionCeiling)
        .filter(
            GermanyContributionCeiling.branch == data.branch,
            GermanyContributionCeiling.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(
        auto_close_previous and previous_open and previous_open.effective_from < data.effective_from
    )
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_contribution_ceiling_no_overlap(
        db, data.branch, data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = GermanyContributionCeiling(
        branch=data.branch, monthly_ceiling=data.monthly_ceiling, annual_ceiling=data.annual_ceiling,
        effective_from=data.effective_from, effective_to=data.effective_to,
        authority_source_id=data.authority_source_id, status="DRAFT",
        created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_contribution_ceiling", entity_id=row.id,
        old_value=None,
        new_value={
            "branch": data.branch, "monthly_ceiling": str(data.monthly_ceiling),
            "annual_ceiling": str(data.annual_ceiling), "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
    )
    return row


def set_contribution_ceiling_status(
    db: Session, record_id: int, status: str, actor_id: Optional[int] = None,
) -> GermanyContributionCeiling:
    """Advance a contribution-ceiling record's lifecycle. Reuses
    GermanyHealthFund's/PapAlgorithmAsset's maker-checker principle
    (distinct approver required before PUBLISHED)."""
    row = get_contribution_ceiling_by_id(db, record_id)
    if status not in _CONTRIBUTION_CEILING_VALID_STATUSES:
        raise BadRequestException(f"Unknown contribution ceiling status: {status!r}.")
    if status not in _CONTRIBUTION_CEILING_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move a contribution ceiling record from {row.status} to {status}.")

    if status == "PUBLISHED":
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This contribution ceiling record needs a distinct approver before it can be published — "
                "use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.authority_source_id:
            raise BadRequestException(
                "A contribution ceiling record cannot be published without a linked source evidence "
                "artifact (authoritySourceId) — record one via /compliance/source-artifacts first."
            )

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_contribution_ceiling", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_contribution_ceiling_approver(db: Session, record_id: int, actor_id: Optional[int] = None) -> GermanyContributionCeiling:
    """Sets approved_by_id — same distinct, lightweight action as
    set_health_fund_approver/set_pap_asset_approver. Auto-advances
    VERIFIED -> APPROVED only."""
    row = get_contribution_ceiling_by_id(db, record_id)
    _require_editable_contribution_ceiling(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "VERIFIED":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_contribution_ceiling", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


def resolve_germany_contribution_ceiling(
    db: Session, branch: str, as_of: Optional[date] = None,
) -> Optional[GermanyContributionCeiling]:
    """Return the PUBLISHED ceiling record applicable on `as_of` (defaults
    to today) for one specific contribution branch ("GKV_PV" or
    "RV_ALV"). Returns None (never raises) if no published record covers
    that date. A future social-insurance calculation phase would call this
    once per branch — it must never conflate the two branches' results,
    which is exactly what this table's `branch` column exists to prevent."""
    as_of = as_of or date.today()
    return (
        db.query(GermanyContributionCeiling)
        .filter(
            GermanyContributionCeiling.branch == branch,
            GermanyContributionCeiling.status == "PUBLISHED",
            GermanyContributionCeiling.effective_from <= as_of,
            (GermanyContributionCeiling.effective_to.is_(None)) | (GermanyContributionCeiling.effective_to >= as_of),
        )
        .order_by(GermanyContributionCeiling.effective_from.desc())
        .first()
    )


# ── Germany: PV (Long-Term Care Insurance) Child/Saxony Configuration ────
# Configuration/registry only — see models.GermanyPvConfiguration's own
# docstring and docs/PHASE_6_GERMANY_PV_CHILD_SAXONY_EVIDENCE_REPORT.md.
# Consumed by calculation: _resolve_germany_calc_inputs() resolves these rows
# as_of the payroll date into PayrollContext.germany_pv_configuration, which
# engine/countries/germany.py passes to calculate_pv (germany_pap/core.py) to
# compute Pflegeversicherung using the child/Saxony-differentiated rates stored
# here (wired in Phase 7 — an older comment here claiming the engine "does not
# read from this table" was outdated once that wiring landed and has been
# corrected).
#
# Same lifecycle/overlap model as GermanyContributionCeiling (Phase 5) and
# GermanyHealthFund (Phase 4): every configuration version — past, current,
# or future — must remain independently resolvable by date, so overlap
# prevention is a general range check across ALL rows of the same
# (child_category, is_saxony) identity.

_GERMANY_PV_CHILD_CATEGORIES = ("CHILDLESS", "1", "2", "3", "4", "5_PLUS")
_PV_CONFIGURATION_EDITABLE_STATUSES = ("DRAFT", "VERIFIED", "APPROVED")
_PV_CONFIGURATION_VALID_STATUSES = ("DRAFT", "VERIFIED", "APPROVED", "PUBLISHED", "SUPERSEDED")
_PV_CONFIGURATION_ALLOWED_TRANSITIONS = {
    "DRAFT": {"VERIFIED"},
    "VERIFIED": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "VERIFIED"},
    # PUBLISHED -> SUPERSEDED is reserved for an explicit correction of an
    # erroneously published row — NOT the normal "a new year's rates now
    # apply" case, which is simply a second, later-effective-dated
    # PUBLISHED row for the same (child_category, is_saxony) coexisting.
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_pv_configuration(row: GermanyPvConfiguration) -> None:
    if row.status not in _PV_CONFIGURATION_EDITABLE_STATUSES:
        raise BadRequestException(
            f"PV configuration record for {row.child_category} "
            f"({'Saxony' if row.is_saxony else 'standard'}) ({row.effective_from}) is {row.status} — no longer "
            "editable. Record a new effective-dated version instead."
        )


def _validate_pv_configuration_no_overlap(
    db: Session, child_category: str, is_saxony: bool,
    effective_from: date, effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    """Same "no two overlapping ranges for the same identity" check as
    _validate_health_fund_no_overlap / _validate_contribution_ceiling_no_overlap,
    applied to (child_category, is_saxony) instead of health_fund_id / branch."""
    query = db.query(GermanyPvConfiguration).filter(
        GermanyPvConfiguration.child_category == child_category,
        GermanyPvConfiguration.is_saxony == is_saxony,
    )
    if exclude_id is not None:
        query = query.filter(GermanyPvConfiguration.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing PV "
                f"configuration record #{existing.id} for {child_category} "
                f"({'Saxony' if is_saxony else 'standard'}) ({existing.effective_from} to "
                f"{existing.effective_to or 'open-ended'}). Close or adjust that record first."
            )


def list_pv_configurations(
    db: Session, child_category: Optional[str] = None, is_saxony: Optional[bool] = None,
) -> List[GermanyPvConfiguration]:
    query = db.query(GermanyPvConfiguration)
    if child_category:
        query = query.filter(GermanyPvConfiguration.child_category == child_category)
    if is_saxony is not None:
        query = query.filter(GermanyPvConfiguration.is_saxony == is_saxony)
    return query.order_by(
        GermanyPvConfiguration.child_category, GermanyPvConfiguration.is_saxony,
        GermanyPvConfiguration.effective_from.desc(),
    ).all()


def get_pv_configuration_by_id(db: Session, record_id: int) -> GermanyPvConfiguration:
    row = db.query(GermanyPvConfiguration).filter(GermanyPvConfiguration.id == record_id).first()
    if not row:
        raise NotFoundException("GermanyPvConfiguration", record_id)
    return row


def create_pv_configuration_record(
    db: Session, data: GermanyPvConfigurationCreate, actor_id: Optional[int] = None,
    auto_close_previous: bool = True,
) -> GermanyPvConfiguration:
    """Append a new effective-dated PV configuration version. Never updates
    an existing row. Mirrors create_contribution_ceiling_record's
    auto-close-previous-open-row behavior."""
    if data.child_category not in _GERMANY_PV_CHILD_CATEGORIES:
        raise BadRequestException(
            f"childCategory must be one of {_GERMANY_PV_CHILD_CATEGORIES}, got {data.child_category!r}."
        )
    if data.total_rate_pct is None or data.total_rate_pct < 0:
        raise BadRequestException("totalRatePct must be a non-negative value.")
    if data.standard_employee_rate_pct is None or data.standard_employee_rate_pct < 0:
        raise BadRequestException("standardEmployeeRatePct must be a non-negative value.")
    if data.employer_rate_pct is None or data.employer_rate_pct < 0:
        raise BadRequestException("employerRatePct must be a non-negative value.")
    if data.saxony_employee_rate_pct is None or data.saxony_employee_rate_pct < 0:
        raise BadRequestException("saxonyEmployeeRatePct must be a non-negative value.")
    if data.saxony_employer_rate_pct is None or data.saxony_employer_rate_pct < 0:
        raise BadRequestException("saxonyEmployerRatePct must be a non-negative value.")
    if data.effective_to is not None and data.effective_to < data.effective_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")

    previous_open = (
        db.query(GermanyPvConfiguration)
        .filter(
            GermanyPvConfiguration.child_category == data.child_category,
            GermanyPvConfiguration.is_saxony == data.is_saxony,
            GermanyPvConfiguration.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(
        auto_close_previous and previous_open and previous_open.effective_from < data.effective_from
    )
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_pv_configuration_no_overlap(
        db, data.child_category, data.is_saxony,
        data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = GermanyPvConfiguration(
        child_category=data.child_category, is_saxony=data.is_saxony,
        total_rate_pct=data.total_rate_pct,
        standard_employee_rate_pct=data.standard_employee_rate_pct,
        employer_rate_pct=data.employer_rate_pct,
        saxony_employee_rate_pct=data.saxony_employee_rate_pct,
        saxony_employer_rate_pct=data.saxony_employer_rate_pct,
        effective_from=data.effective_from, effective_to=data.effective_to,
        authority_source_id=data.authority_source_id, status="DRAFT",
        created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_pv_configuration", entity_id=row.id,
        old_value=None,
        new_value={
            "child_category": data.child_category, "is_saxony": data.is_saxony,
            "total_rate_pct": str(data.total_rate_pct),
            "standard_employee_rate_pct": str(data.standard_employee_rate_pct),
            "employer_rate_pct": str(data.employer_rate_pct),
            "saxony_employee_rate_pct": str(data.saxony_employee_rate_pct),
            "saxony_employer_rate_pct": str(data.saxony_employer_rate_pct),
            "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
    )
    return row


def set_pv_configuration_status(
    db: Session, record_id: int, status: str, actor_id: Optional[int] = None,
) -> GermanyPvConfiguration:
    """Advance a PV configuration record's lifecycle. Reuses the
    maker-checker principle (distinct approver required before PUBLISHED)."""
    row = get_pv_configuration_by_id(db, record_id)
    if status not in _PV_CONFIGURATION_VALID_STATUSES:
        raise BadRequestException(f"Unknown PV configuration status: {status!r}.")
    if status not in _PV_CONFIGURATION_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move a PV configuration record from {row.status} to {status}.")

    if status == "PUBLISHED":
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This PV configuration record needs a distinct approver before it can be published — "
                "use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.authority_source_id:
            raise BadRequestException(
                "A PV configuration record cannot be published without a linked source evidence "
                "artifact (authoritySourceId) — record one via /compliance/source-artifacts first."
            )

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_pv_configuration", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_pv_configuration_approver(db: Session, record_id: int, actor_id: Optional[int] = None) -> GermanyPvConfiguration:
    """Sets approved_by_id — same distinct, lightweight action as
    set_contribution_ceiling_approver / set_health_fund_approver. Auto-advances
    VERIFIED -> APPROVED only."""
    row = get_pv_configuration_by_id(db, record_id)
    _require_editable_pv_configuration(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "VERIFIED":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_pv_configuration", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


def resolve_germany_pv_configuration(
    db: Session, child_category: str, is_saxony: bool, as_of: Optional[date] = None,
) -> Optional[GermanyPvConfiguration]:
    """Return the PUBLISHED PV configuration applicable on `as_of` (defaults
    to today) for one specific (child_category, is_saxony) pair. Returns
    None (never raises) if no published record covers that date. A future
    PV calculation phase would call this once per employee — it must never
    conflate different child-category or Saxony results."""
    as_of = as_of or date.today()
    return (
        db.query(GermanyPvConfiguration)
        .filter(
            GermanyPvConfiguration.child_category == child_category,
            GermanyPvConfiguration.is_saxony == is_saxony,
            GermanyPvConfiguration.status == "PUBLISHED",
            GermanyPvConfiguration.effective_from <= as_of,
            (GermanyPvConfiguration.effective_to.is_(None)) | (GermanyPvConfiguration.effective_to >= as_of),
        )
        .order_by(GermanyPvConfiguration.effective_from.desc())
        .first()
    )


# ── Germany: Earning/Deduction Taxability (ZP-TAX-DE-2026-001 §15) ──────
# Phase 8T. Four-dimension classification registry — see
# models.GermanyEarningTaxabilityRule's own docstring for why this is a
# new table, not a retrofit of the existing (unused, US-shaped)
# TaxabilityRule model.

# The exact 9 rows from spec §15's own taxability-matrix table — no 10th
# type invented. New earning types require a spec amendment first.
_GERMANY_EARNING_TYPES = (
    "REGULAR_SALARY", "OVERTIME_SHIFT_PREMIUM", "BONUS_ANNUAL_BONUS",
    "PENSION_VERSORGUNGSBEZUG", "EQUITY_BENEFIT_19A", "EXPENSE_REIMBURSEMENT",
    "OCCUPATIONAL_PENSION_CONTRIBUTION", "GARNISHMENT_ATTACHMENT", "EMPLOYEE_VOLUNTARY_DEDUCTION",
)

# Wage-tax dimension — spec §15's own "Lohnsteuer" column vocabulary,
# generalized into named states (never a bare taxable/non-taxable flag).
_GERMANY_WAGE_TAX_TREATMENTS = (
    "TAXABLE_REGULAR",            # ordinary RE4-routed wage tax
    "OTHER_REMUNERATION_SONSTB",  # spec: "Other remuneration route" (bonus/annual bonus)
    "SPECIAL_PAP_HANDLING",       # spec: "Special PAP fields" (pension/Versorgungsbezug, §19a)
    "CONDITIONALLY_EXEMPT",       # spec: "Depends on statutory exemption conditions" / "Taxable or exempt by statutory rule"
    "POST_TAX_NO_TAX_IMPACT",     # spec: "Post-tax statutory deduction" / "Post-net unless statutory scheme says otherwise"
    # Phase 8Y: spec §15's Lohnsteuer column for "Occupational pension
    # contribution" literally reads "Scheme/limit-specific" — the same
    # phrase already used (correctly) in _GERMANY_SI_TREATMENTS below for
    # that row's GKV/PV and RV/ALV columns. The wage-tax vocabulary had no
    # equivalent value, which is a genuine MODEL_LIMITATION discovered
    # while transcribing the §15 matrix literally (not a new statutory
    # concept — the same three columns of the same spec row all read the
    # identical phrase). Adding it here is required for the wage-tax
    # dimension to represent this row's real, spec-stated value.
    "SCHEME_LIMIT_SPECIFIC",      # spec: "Scheme/limit-specific" (occupational pension contribution)
    "NOT_SPECIFIED",              # spec gives no determination for this row
)

# Social-insurance dimension — spec §15 uses the SAME descriptive
# vocabulary for both GKV/PV and RV/ALV columns, so one shared vocabulary
# is used for both (never invented separately per branch).
_GERMANY_SI_TREATMENTS = (
    "CONTRIBUTORY",                # spec: "Generally contributory"
    "CONTRIBUTORY_SUBJECT_TO_ALLOCATION",  # spec: "Contributory subject to allocation rules" (bonus/annual bonus)
    "MAY_DIFFER",                  # spec: "May differ" (overtime/shift premiums)
    "OFTEN_NON_CONTRIBUTORY",      # spec: "Often non-contributory if tax-exempt conditions met"
    "NO_CHANGE_TO_BASE",           # spec: "No change to contribution base by itself" / "No change by default"
    "COVERAGE_SPECIFIC",           # spec: "Coverage-specific" (pension/Versorgungsbezug)
    "CLASSIFICATION_SPECIFIC",     # spec: "Classification-specific" (§19a equity benefit)
    "SCHEME_LIMIT_SPECIFIC",       # spec: "Scheme/limit-specific" (occupational pension contribution)
    "NOT_SPECIFIED",
)

_EARNING_TAXABILITY_EDITABLE_STATUSES = ("DRAFT", "VERIFIED", "APPROVED")
_EARNING_TAXABILITY_VALID_STATUSES = ("DRAFT", "VERIFIED", "APPROVED", "PUBLISHED", "SUPERSEDED")
_EARNING_TAXABILITY_ALLOWED_TRANSITIONS = {
    "DRAFT": {"VERIFIED"},
    "VERIFIED": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "VERIFIED"},
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_earning_taxability_rule(row: GermanyEarningTaxabilityRule) -> None:
    if row.status not in _EARNING_TAXABILITY_EDITABLE_STATUSES:
        raise BadRequestException(
            f"Earning taxability rule for {row.earning_type} ({row.effective_from}) is {row.status} — "
            "no longer editable. Record a new effective-dated version instead."
        )


def _validate_earning_taxability_no_overlap(
    db: Session, earning_type: str, effective_from: date, effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    query = db.query(GermanyEarningTaxabilityRule).filter(GermanyEarningTaxabilityRule.earning_type == earning_type)
    if exclude_id is not None:
        query = query.filter(GermanyEarningTaxabilityRule.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing earning "
                f"taxability rule #{existing.id} for {earning_type} ({existing.effective_from} to "
                f"{existing.effective_to or 'open-ended'}). Close or adjust that record first."
            )


def list_earning_taxability_rules(db: Session, earning_type: Optional[str] = None) -> List[GermanyEarningTaxabilityRule]:
    query = db.query(GermanyEarningTaxabilityRule)
    if earning_type:
        query = query.filter(GermanyEarningTaxabilityRule.earning_type == earning_type)
    return query.order_by(
        GermanyEarningTaxabilityRule.earning_type, GermanyEarningTaxabilityRule.effective_from.desc(),
    ).all()


def get_earning_taxability_rule_by_id(db: Session, record_id: int) -> GermanyEarningTaxabilityRule:
    row = db.query(GermanyEarningTaxabilityRule).filter(GermanyEarningTaxabilityRule.id == record_id).first()
    if not row:
        raise NotFoundException("GermanyEarningTaxabilityRule", record_id)
    return row


def create_earning_taxability_rule(
    db: Session, data: "GermanyEarningTaxabilityRuleCreate", actor_id: Optional[int] = None,
    auto_close_previous: bool = True,
) -> GermanyEarningTaxabilityRule:
    """Append a new effective-dated earning-taxability version. Never
    updates an existing row. Mirrors create_pv_configuration_record's
    auto-close-previous-open-row behavior."""
    if data.earning_type not in _GERMANY_EARNING_TYPES:
        raise BadRequestException(f"earningType must be one of {_GERMANY_EARNING_TYPES}, got {data.earning_type!r}.")
    if data.wage_tax_treatment not in _GERMANY_WAGE_TAX_TREATMENTS:
        raise BadRequestException(f"wageTaxTreatment must be one of {_GERMANY_WAGE_TAX_TREATMENTS}, got {data.wage_tax_treatment!r}.")
    if data.gkv_pv_treatment not in _GERMANY_SI_TREATMENTS:
        raise BadRequestException(f"gkvPvTreatment must be one of {_GERMANY_SI_TREATMENTS}, got {data.gkv_pv_treatment!r}.")
    if data.rv_alv_treatment not in _GERMANY_SI_TREATMENTS:
        raise BadRequestException(f"rvAlvTreatment must be one of {_GERMANY_SI_TREATMENTS}, got {data.rv_alv_treatment!r}.")
    if data.effective_to is not None and data.effective_to < data.effective_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")

    previous_open = (
        db.query(GermanyEarningTaxabilityRule)
        .filter(
            GermanyEarningTaxabilityRule.earning_type == data.earning_type,
            GermanyEarningTaxabilityRule.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(auto_close_previous and previous_open and previous_open.effective_from < data.effective_from)
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_earning_taxability_no_overlap(
        db, data.earning_type, data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = GermanyEarningTaxabilityRule(
        earning_type=data.earning_type,
        wage_tax_treatment=data.wage_tax_treatment,
        gkv_pv_treatment=data.gkv_pv_treatment,
        rv_alv_treatment=data.rv_alv_treatment,
        reporting_classification=data.reporting_classification,
        effective_from=data.effective_from, effective_to=data.effective_to,
        authority_source_id=data.authority_source_id, status="DRAFT",
        created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_earning_taxability_rule", entity_id=row.id,
        old_value=None,
        new_value={
            "earning_type": data.earning_type, "wage_tax_treatment": data.wage_tax_treatment,
            "gkv_pv_treatment": data.gkv_pv_treatment, "rv_alv_treatment": data.rv_alv_treatment,
            "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
    )
    return row


def set_earning_taxability_rule_status(
    db: Session, record_id: int, status: str, actor_id: Optional[int] = None,
) -> GermanyEarningTaxabilityRule:
    """Advance an earning-taxability rule's lifecycle. Reuses the same
    maker-checker principle as every other Germany registry."""
    row = get_earning_taxability_rule_by_id(db, record_id)
    if status not in _EARNING_TAXABILITY_VALID_STATUSES:
        raise BadRequestException(f"Unknown earning taxability rule status: {status!r}.")
    if status not in _EARNING_TAXABILITY_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move an earning taxability rule from {row.status} to {status}.")

    if status == "PUBLISHED":
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This earning taxability rule needs a distinct approver before it can be published — "
                "use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.authority_source_id:
            raise BadRequestException(
                "An earning taxability rule cannot be published without a linked source evidence "
                "artifact (authoritySourceId) — record one via /compliance/source-artifacts first."
            )

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_earning_taxability_rule", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_earning_taxability_rule_approver(db: Session, record_id: int, actor_id: Optional[int] = None) -> GermanyEarningTaxabilityRule:
    """Sets approved_by_id — same distinct, lightweight action as every
    other Germany registry's approver-setter. Auto-advances VERIFIED ->
    APPROVED only."""
    row = get_earning_taxability_rule_by_id(db, record_id)
    _require_editable_earning_taxability_rule(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "VERIFIED":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_earning_taxability_rule", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


def resolve_germany_earning_taxability_rule(
    db: Session, earning_type: str, as_of: Optional[date] = None,
) -> Optional[GermanyEarningTaxabilityRule]:
    """Return the PUBLISHED taxability rule applicable on `as_of` (defaults
    to today) for one earning type. Returns None (never raises) if no
    published record covers that date — a future consumer must treat
    that as NOT_CONFIGURED, never silently assume ordinary taxable
    treatment (spec's own "no invented statutory result" principle)."""
    as_of = as_of or date.today()
    return (
        db.query(GermanyEarningTaxabilityRule)
        .filter(
            GermanyEarningTaxabilityRule.earning_type == earning_type,
            GermanyEarningTaxabilityRule.status == "PUBLISHED",
            GermanyEarningTaxabilityRule.effective_from <= as_of,
            (GermanyEarningTaxabilityRule.effective_to.is_(None)) | (GermanyEarningTaxabilityRule.effective_to >= as_of),
        )
        .order_by(GermanyEarningTaxabilityRule.effective_from.desc())
        .first()
    )


# ── Germany: overtime/shift-premium statutory registries (Phase 8AD) ────
# GLOBAL statutory configuration only — see models.py's
# GermanyOvertimePremiumCategory/GermanyOvertimeGrundlohnCap docstrings.
# Mirrors GermanyContributionCeiling's lifecycle/overlap/maker-checker
# functions exactly (same shape: one string key, effective-dated versions,
# DRAFT->VERIFIED->APPROVED->PUBLISHED->SUPERSEDED). NOT consumed by
# engine/countries/germany.py — that wiring is explicitly out of scope for
# this phase (Phase 8AE/8AF/8AG).

_GERMANY_OVERTIME_PREMIUM_CATEGORIES = (
    "NIGHT_STANDARD", "NIGHT_EXTENDED", "SUNDAY", "HOLIDAY_STANDARD", "HOLIDAY_SPECIAL",
)
_OVERTIME_PREMIUM_CATEGORY_EDITABLE_STATUSES = ("DRAFT", "VERIFIED", "APPROVED")
_OVERTIME_PREMIUM_CATEGORY_VALID_STATUSES = ("DRAFT", "VERIFIED", "APPROVED", "PUBLISHED", "SUPERSEDED")
_OVERTIME_PREMIUM_CATEGORY_ALLOWED_TRANSITIONS = {
    "DRAFT": {"VERIFIED"},
    "VERIFIED": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "VERIFIED"},
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_overtime_premium_category(row: GermanyOvertimePremiumCategory) -> None:
    if row.status not in _OVERTIME_PREMIUM_CATEGORY_EDITABLE_STATUSES:
        raise BadRequestException(
            f"Overtime premium category record for {row.category_code} ({row.effective_from}) is "
            f"{row.status} — no longer editable. Record a new effective-dated version instead."
        )


def _validate_overtime_premium_category_no_overlap(
    db: Session, category_code: str, effective_from: date, effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    query = db.query(GermanyOvertimePremiumCategory).filter(GermanyOvertimePremiumCategory.category_code == category_code)
    if exclude_id is not None:
        query = query.filter(GermanyOvertimePremiumCategory.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing overtime "
                f"premium category record #{existing.id} for {category_code} ({existing.effective_from} to "
                f"{existing.effective_to or 'open-ended'}). Close or adjust that record first."
            )


def list_overtime_premium_categories(db: Session, category_code: Optional[str] = None) -> List[GermanyOvertimePremiumCategory]:
    query = db.query(GermanyOvertimePremiumCategory)
    if category_code:
        query = query.filter(GermanyOvertimePremiumCategory.category_code == category_code)
    return query.order_by(GermanyOvertimePremiumCategory.category_code, GermanyOvertimePremiumCategory.effective_from.desc()).all()


def get_overtime_premium_category_by_id(db: Session, record_id: int) -> GermanyOvertimePremiumCategory:
    row = db.query(GermanyOvertimePremiumCategory).filter(GermanyOvertimePremiumCategory.id == record_id).first()
    if not row:
        raise NotFoundException("GermanyOvertimePremiumCategory", record_id)
    return row


def create_overtime_premium_category_record(
    db: Session, data: "GermanyOvertimePremiumCategoryCreate", actor_id: Optional[int] = None,
    auto_close_previous: bool = True,
) -> GermanyOvertimePremiumCategory:
    """Append a new effective-dated overtime premium-category version.
    Never updates an existing row. Mirrors create_contribution_ceiling_record's
    auto-close-previous-open-row behavior."""
    if data.category_code not in _GERMANY_OVERTIME_PREMIUM_CATEGORIES:
        raise BadRequestException(
            f"category_code must be one of {_GERMANY_OVERTIME_PREMIUM_CATEGORIES}, got {data.category_code!r}."
        )
    if data.wage_tax_free_pct is None or data.wage_tax_free_pct <= 0:
        raise BadRequestException("wage_tax_free_pct must be a positive value.")
    if data.effective_to is not None and data.effective_to < data.effective_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")

    previous_open = (
        db.query(GermanyOvertimePremiumCategory)
        .filter(
            GermanyOvertimePremiumCategory.category_code == data.category_code,
            GermanyOvertimePremiumCategory.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(auto_close_previous and previous_open and previous_open.effective_from < data.effective_from)
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_overtime_premium_category_no_overlap(
        db, data.category_code, data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = GermanyOvertimePremiumCategory(
        category_code=data.category_code, wage_tax_free_pct=data.wage_tax_free_pct,
        effective_from=data.effective_from, effective_to=data.effective_to,
        authority_source_id=data.authority_source_id, status="DRAFT",
        created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_overtime_premium_category", entity_id=row.id,
        old_value=None,
        new_value={
            "category_code": data.category_code, "wage_tax_free_pct": str(data.wage_tax_free_pct),
            "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
    )
    return row


def set_overtime_premium_category_status(
    db: Session, record_id: int, status: str, actor_id: Optional[int] = None,
) -> GermanyOvertimePremiumCategory:
    row = get_overtime_premium_category_by_id(db, record_id)
    if status not in _OVERTIME_PREMIUM_CATEGORY_VALID_STATUSES:
        raise BadRequestException(f"Unknown overtime premium category status: {status!r}.")
    if status not in _OVERTIME_PREMIUM_CATEGORY_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move an overtime premium category record from {row.status} to {status}.")

    if status == "PUBLISHED":
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This overtime premium category record needs a distinct approver before it can be "
                "published — use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.authority_source_id:
            raise BadRequestException(
                "An overtime premium category record cannot be published without a linked source evidence "
                "artifact (authoritySourceId) — record one via /compliance/source-artifacts first."
            )

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_overtime_premium_category", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_overtime_premium_category_approver(db: Session, record_id: int, actor_id: Optional[int] = None) -> GermanyOvertimePremiumCategory:
    row = get_overtime_premium_category_by_id(db, record_id)
    _require_editable_overtime_premium_category(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "VERIFIED":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_overtime_premium_category", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


def resolve_germany_overtime_premium_category(
    db: Session, category_code: str, as_of: Optional[date] = None,
) -> Optional[GermanyOvertimePremiumCategory]:
    """Return the PUBLISHED premium-category record applicable on `as_of`
    (defaults to today). Returns None (never raises) if no published
    record covers that date — fail closed, never a hardcoded percentage."""
    as_of = as_of or date.today()
    return (
        db.query(GermanyOvertimePremiumCategory)
        .filter(
            GermanyOvertimePremiumCategory.category_code == category_code,
            GermanyOvertimePremiumCategory.status == "PUBLISHED",
            GermanyOvertimePremiumCategory.effective_from <= as_of,
            (GermanyOvertimePremiumCategory.effective_to.is_(None)) | (GermanyOvertimePremiumCategory.effective_to >= as_of),
        )
        .order_by(GermanyOvertimePremiumCategory.effective_from.desc())
        .first()
    )


_GERMANY_OVERTIME_GRUNDLOHN_DIMENSIONS = ("WAGE_TAX", "SOCIAL_INSURANCE")
_OVERTIME_GRUNDLOHN_CAP_EDITABLE_STATUSES = ("DRAFT", "VERIFIED", "APPROVED")
_OVERTIME_GRUNDLOHN_CAP_VALID_STATUSES = ("DRAFT", "VERIFIED", "APPROVED", "PUBLISHED", "SUPERSEDED")
_OVERTIME_GRUNDLOHN_CAP_ALLOWED_TRANSITIONS = {
    "DRAFT": {"VERIFIED"},
    "VERIFIED": {"APPROVED", "DRAFT"},
    "APPROVED": {"PUBLISHED", "VERIFIED"},
    "PUBLISHED": {"SUPERSEDED"},
    "SUPERSEDED": set(),
}


def _require_editable_overtime_grundlohn_cap(row: GermanyOvertimeGrundlohnCap) -> None:
    if row.status not in _OVERTIME_GRUNDLOHN_CAP_EDITABLE_STATUSES:
        raise BadRequestException(
            f"Overtime Grundlohn cap record for {row.dimension} ({row.effective_from}) is {row.status} — "
            "no longer editable. Record a new effective-dated version instead."
        )


def _validate_overtime_grundlohn_cap_no_overlap(
    db: Session, dimension: str, effective_from: date, effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    query = db.query(GermanyOvertimeGrundlohnCap).filter(GermanyOvertimeGrundlohnCap.dimension == dimension)
    if exclude_id is not None:
        query = query.filter(GermanyOvertimeGrundlohnCap.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing overtime "
                f"Grundlohn cap record #{existing.id} for {dimension} ({existing.effective_from} to "
                f"{existing.effective_to or 'open-ended'}). Close or adjust that record first."
            )


def list_overtime_grundlohn_caps(db: Session, dimension: Optional[str] = None) -> List[GermanyOvertimeGrundlohnCap]:
    query = db.query(GermanyOvertimeGrundlohnCap)
    if dimension:
        query = query.filter(GermanyOvertimeGrundlohnCap.dimension == dimension)
    return query.order_by(GermanyOvertimeGrundlohnCap.dimension, GermanyOvertimeGrundlohnCap.effective_from.desc()).all()


def get_overtime_grundlohn_cap_by_id(db: Session, record_id: int) -> GermanyOvertimeGrundlohnCap:
    row = db.query(GermanyOvertimeGrundlohnCap).filter(GermanyOvertimeGrundlohnCap.id == record_id).first()
    if not row:
        raise NotFoundException("GermanyOvertimeGrundlohnCap", record_id)
    return row


def create_overtime_grundlohn_cap_record(
    db: Session, data: "GermanyOvertimeGrundlohnCapCreate", actor_id: Optional[int] = None,
    auto_close_previous: bool = True,
) -> GermanyOvertimeGrundlohnCap:
    if data.dimension not in _GERMANY_OVERTIME_GRUNDLOHN_DIMENSIONS:
        raise BadRequestException(
            f"dimension must be one of {_GERMANY_OVERTIME_GRUNDLOHN_DIMENSIONS}, got {data.dimension!r}."
        )
    if data.hourly_cap_amount is None or data.hourly_cap_amount <= 0:
        raise BadRequestException("hourly_cap_amount must be a positive value.")
    if data.effective_to is not None and data.effective_to < data.effective_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom.")

    previous_open = (
        db.query(GermanyOvertimeGrundlohnCap)
        .filter(
            GermanyOvertimeGrundlohnCap.dimension == data.dimension,
            GermanyOvertimeGrundlohnCap.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(auto_close_previous and previous_open and previous_open.effective_from < data.effective_from)
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_overtime_grundlohn_cap_no_overlap(
        db, data.dimension, data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = GermanyOvertimeGrundlohnCap(
        dimension=data.dimension, hourly_cap_amount=data.hourly_cap_amount,
        effective_from=data.effective_from, effective_to=data.effective_to,
        authority_source_id=data.authority_source_id, status="DRAFT",
        created_by_id=actor_id, updated_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_overtime_grundlohn_cap", entity_id=row.id,
        old_value=None,
        new_value={
            "dimension": data.dimension, "hourly_cap_amount": str(data.hourly_cap_amount),
            "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
    )
    return row


def set_overtime_grundlohn_cap_status(
    db: Session, record_id: int, status: str, actor_id: Optional[int] = None,
) -> GermanyOvertimeGrundlohnCap:
    row = get_overtime_grundlohn_cap_by_id(db, record_id)
    if status not in _OVERTIME_GRUNDLOHN_CAP_VALID_STATUSES:
        raise BadRequestException(f"Unknown overtime Grundlohn cap status: {status!r}.")
    if status not in _OVERTIME_GRUNDLOHN_CAP_ALLOWED_TRANSITIONS.get(row.status, set()):
        raise BadRequestException(f"Cannot move an overtime Grundlohn cap record from {row.status} to {status}.")

    if status == "PUBLISHED":
        if not row.approved_by_id or row.approved_by_id == row.updated_by_id:
            raise BadRequestException(
                "This overtime Grundlohn cap record needs a distinct approver before it can be published — "
                "use the approve action with a different Super Admin than whoever last edited it."
            )
        if not row.authority_source_id:
            raise BadRequestException(
                "An overtime Grundlohn cap record cannot be published without a linked source evidence "
                "artifact (authoritySourceId) — record one via /compliance/source-artifacts first."
            )

    old_status = row.status
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_overtime_grundlohn_cap", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def set_overtime_grundlohn_cap_approver(db: Session, record_id: int, actor_id: Optional[int] = None) -> GermanyOvertimeGrundlohnCap:
    row = get_overtime_grundlohn_cap_by_id(db, record_id)
    _require_editable_overtime_grundlohn_cap(row)
    old_approver = row.approved_by_id
    old_status = row.status
    row.approved_by_id = actor_id
    if row.status == "VERIFIED":
        row.status = "APPROVED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_overtime_grundlohn_cap", entity_id=row.id,
        old_value={"approved_by_id": old_approver, "status": old_status},
        new_value={"approved_by_id": actor_id, "status": row.status},
        reason="Approver set",
    )
    return row


def resolve_germany_overtime_grundlohn_cap(
    db: Session, dimension: str, as_of: Optional[date] = None,
) -> Optional[GermanyOvertimeGrundlohnCap]:
    """Return the PUBLISHED Grundlohn cap applicable on `as_of` (defaults
    to today) for one dimension ("WAGE_TAX" or "SOCIAL_INSURANCE"). Returns
    None (never raises) if no published record covers that date — fail
    closed, never a hardcoded €50/€25 fallback."""
    as_of = as_of or date.today()
    return (
        db.query(GermanyOvertimeGrundlohnCap)
        .filter(
            GermanyOvertimeGrundlohnCap.dimension == dimension,
            GermanyOvertimeGrundlohnCap.status == "PUBLISHED",
            GermanyOvertimeGrundlohnCap.effective_from <= as_of,
            (GermanyOvertimeGrundlohnCap.effective_to.is_(None)) | (GermanyOvertimeGrundlohnCap.effective_to >= as_of),
        )
        .order_by(GermanyOvertimeGrundlohnCap.effective_from.desc())
        .first()
    )


# ── Germany: per-employee calculation-input resolver (Phase 7) ─────────
# Phase 8BF — disclosed onboarding gap closure. A Germany employee could
# previously be created (and payroll attempted) with zero visibility into
# whether the GLOBAL statutory registries (health funds, both contribution
# -ceiling branches, PV configuration) had ever been published at all —
# the first sign of an incomplete configuration was a fail-closed
# GermanyCalculationBlockedException at actual payroll-run time. This is
# organization-independent (these four registries are global, not
# per-org — confirmed by this project's own prior forensic audit) and
# deliberately does NOT check per-employee state (statutory profile,
# health-fund code, PAP asset) — that is what preview_germany_calculation
# already covers once an employee exists. This function answers a
# narrower, earlier question: "is Germany payroll configuration even
# possible today, for ANY employee?" Read-only; never creates, seeds, or
# infers a registry row — an incomplete answer here is reported, never
# silently completed.
def get_germany_statutory_configuration_readiness(db: Session, as_of=None) -> dict:
    as_of = as_of or date.today()

    def _has_published(rows, effective_check=True):
        for row in rows:
            if row.status != "PUBLISHED":
                continue
            if not effective_check:
                return True
            effective_to = getattr(row, "effective_to", None)
            if row.effective_from <= as_of and (effective_to is None or as_of <= effective_to):
                return True
        return False

    health_fund_ready = _has_published(list_health_funds(db))
    ceiling_rv_alv_ready = _has_published(list_contribution_ceilings(db, branch="RV_ALV"))
    ceiling_gkv_pv_ready = _has_published(list_contribution_ceilings(db, branch="GKV_PV"))
    pv_configuration_ready = _has_published(list_pv_configurations(db))

    missing = []
    if not health_fund_ready:
        missing.append("No PUBLISHED health fund (Krankenkasse) record is effective as of this date.")
    if not ceiling_rv_alv_ready:
        missing.append("No PUBLISHED RV/ALV contribution ceiling is effective as of this date.")
    if not ceiling_gkv_pv_ready:
        missing.append("No PUBLISHED GKV/PV contribution ceiling is effective as of this date.")
    if not pv_configuration_ready:
        missing.append("No PUBLISHED PV (long-term care) configuration is effective as of this date.")

    return {
        "asOf": str(as_of),
        "ready": not missing,
        "healthFundReady": health_fund_ready,
        "ceilingRvAlvReady": ceiling_rv_alv_ready,
        "ceilingGkvPvReady": ceiling_gkv_pv_ready,
        "pvConfigurationReady": pv_configuration_ready,
        "missing": missing,
    }


# Resolves every Germany registry a calculation might need for ONE
# employee on ONE payroll date, in a single place, so _compute_payslip_values
# and preview_payroll_run can never disagree about which rows applied.
# Deliberately NOT cached across employees (unlike rate_map/slabs in
# _resolve_employee_calc_inputs) — profile/health-fund/PV category are
# genuinely per-employee, so caching by jurisdiction alone would silently
# apply one employee's resolved rows to another's.
#
# Returns a plain dict of ORM rows (or None) — never raises. Whether a
# missing row is fatal is a decision for engine/countries/germany.py
# (the actual calculation), not this resolver — mirrors
# resolve_germany_pap_asset's own "absence is not an error" contract.
def _resolve_germany_calc_inputs(db: Session, organization_id: int, employee, payroll_date) -> dict:
    from app.modules.payroll.engine.germany_pap.core import (
        GermanyCalculationError, resolve_pv_child_category,
    )

    profile = resolve_employee_statutory_profile(db, employee.id, organization_id, as_of=payroll_date)
    pap_asset = resolve_germany_pap_asset(db, payroll_date)
    ceiling_gkv_pv = resolve_germany_contribution_ceiling(db, "GKV_PV", as_of=payroll_date)
    ceiling_rv_alv = resolve_germany_contribution_ceiling(db, "RV_ALV", as_of=payroll_date)

    health_fund = None
    u1_tariff = None
    pv_configuration = None
    church_tax_exception = None
    if profile is not None:
        health_fund_code = getattr(profile, "de_health_fund_code", None)
        if health_fund_code:
            health_fund = resolve_germany_health_fund(db, health_fund_code, as_of=payroll_date)
            # Phase 8W: resolve the employer's selected U1 tariff at this fund
            u1_tariff_id = getattr(profile, "de_u1_tariff_id", None)
            if u1_tariff_id:
                u1_tariff = resolve_germany_u1_tariff(db, health_fund_code, u1_tariff_id, as_of=payroll_date)
        if getattr(profile, "de_health_insurance_status", None) != "PRIVATE":
            try:
                category = resolve_pv_child_category(profile)
                is_saxony = bool(getattr(profile, "de_saxony", False))
                pv_configuration = resolve_germany_pv_configuration(db, category, is_saxony, as_of=payroll_date)
            except GermanyCalculationError:
                # Category itself can't be determined from this profile —
                # left None here; germany.py's calculate() re-derives the
                # category itself and raises the precise
                # GermanyStatutoryProfileMissingError, rather than this
                # resolver guessing or swallowing the real reason.
                pv_configuration = None

        # Phase 8AM — resolve church-tax exception (sub-Land override, e.g.
        # Bad Wimpfen Roman Catholic 9% within Baden-Württemberg's 8%).
        # Only resolved when all three required profile fields are present:
        # de_church_tax_land, de_church_tax_denomination,
        # de_church_tax_municipality_postal_code. Returns None (never
        # raises, never guesses) if any field is missing or no PUBLISHED
        # exception matches — the engine then falls back to the ordinary
        # Land rate exactly as before this phase.
        church_tax_land = getattr(profile, "de_church_tax_land", None)
        church_tax_denomination = getattr(profile, "de_church_tax_denomination", None)
        church_tax_municipality_postal_code = getattr(profile, "de_church_tax_municipality_postal_code", None)
        if church_tax_land and church_tax_denomination and church_tax_municipality_postal_code:
            church_tax_exception = resolve_germany_church_tax_exception(
                db, church_tax_land, church_tax_denomination, church_tax_municipality_postal_code, as_of=payroll_date
            )

    # Phase 8X — resolve the four-dimension earning taxability (spec §15)
    # for the two earning types the current engine actually receives as
    # discrete inputs: REGULAR_SALARY (steady RE4 wage = gross net of the
    # bonus) and BONUS_ANNUAL_BONUS (the SONSTB-routed bonus). Absent /
    # unpublished -> None -> the engine surfaces NOT_CONFIGURED in its
    # trace instead of assuming a classification. Resolving both here keeps
    # the engine/frontend and the batch path agreeing on which rows applied
    # for one employee on one payroll date.
    earning_taxability = {
        "REGULAR_SALARY": resolve_germany_earning_taxability_rule(db, "REGULAR_SALARY", as_of=payroll_date),
        "BONUS_ANNUAL_BONUS": resolve_germany_earning_taxability_rule(db, "BONUS_ANNUAL_BONUS", as_of=payroll_date),
    }

    return dict(
        statutory_profile=profile,
        pap_asset=pap_asset,
        health_fund=health_fund,
        u1_tariff=u1_tariff,
        ceiling_gkv_pv=ceiling_gkv_pv,
        ceiling_rv_alv=ceiling_rv_alv,
        pv_configuration=pv_configuration,
        earning_taxability=earning_taxability,
        church_tax_exception=church_tax_exception,
    )


def preview_germany_calculation(db: Session, organization_id: int, employee_id: int, payroll_date=None) -> dict:
    """Phase 7 QA/diagnostic endpoint (spec's own §27 allowance for "a
    protected diagnostic endpoint... genuinely useful for QA"). Read-only —
    never writes anything, never mutates a finalized payroll, never
    accepts a caller-supplied PAP version/statutory rate (every value is
    server-resolved from the authoritative registries, exactly like a
    real run would). Returns either the full resolved calculation (never
    reachable today — see germany.py) or the block code/message/trace, so
    Tax Operations/QA can see exactly what's missing before attempting a
    real payroll run for this employee."""
    from app.modules.payroll.engine.resolver import calculate_payroll, build_context_from_employee
    from app.modules.payroll.engine.germany_pap.core import GermanyCalculationError

    employee = get_employee_by_id(db, employee_id, organization_id)
    payroll_date = payroll_date or date.today()
    country = _resolve_employee_country(db, organization_id, getattr(employee, "country_code", None))
    if country != "DE":
        raise BadRequestException(
            f"Employee {employee_id}'s resolved country is '{country}', not 'DE' — "
            "this diagnostic endpoint is Germany-specific."
        )

    ctc = Decimal(str(getattr(employee, "ctc", 0) or 0))
    monthly_gross = _round2(ctc / MONTHS_PER_YEAR) if ctc else Decimal("0")
    org_opted_in = _org_uses_canonical_tax_pack(db, organization_id)
    rate_map, slabs, _canonical_rates, _pack = _resolve_effective_rate_inputs(
        db, organization_id, country, payroll_date, org_opted_in,
    )
    resolved = _resolve_germany_calc_inputs(db, organization_id, employee, payroll_date)

    ctx = build_context_from_employee(
        employee, gross=monthly_gross, basic=monthly_gross,
        country=country, rate_map=rate_map, slabs=slabs,
        germany_statutory_profile=resolved["statutory_profile"],
        germany_pap_asset=resolved["pap_asset"],
        germany_health_fund=resolved["health_fund"],
        germany_u1_tariff=resolved["u1_tariff"],
        germany_earning_taxability=resolved["earning_taxability"],
        germany_ceiling_gkv_pv=resolved["ceiling_gkv_pv"],
        germany_ceiling_rv_alv=resolved["ceiling_rv_alv"],
        germany_pv_configuration=resolved["pv_configuration"],
        germany_church_tax_exception=resolved["church_tax_exception"],
        germany_employee_id=employee.id,
        germany_organization_id=organization_id,
        germany_payroll_date=payroll_date,
    )
    try:
        result = calculate_payroll(ctx, "standard")
    except GermanyCalculationError as exc:
        return {
            "employeeId": employee_id,
            "payrollDate": str(payroll_date),
            "blocked": True,
            "blockedReasonCode": exc.code,
            "blockedReasonMessage": exc.message,
            "trace": exc.trace.to_dict() if exc.trace else None,
        }
    return {
        "employeeId": employee_id,
        "payrollDate": str(payroll_date),
        "blocked": False,
        "result": {
            "monthlyGross": float(result.gross),
            "monthlyEmployeePf": float(result.employee_pf),
            "monthlyEmployerPf": float(result.employer_pf),
            "monthlyEmployeeEsi": float(result.employee_esi),
            "monthlyEmployerEsi": float(result.employer_esi),
            "monthlyChurchTax": float(result.church_tax),
            "monthlyTax": float(result.tds),
            "monthlyNet": float(result.net_pay),
        },
        "trace": result.germany_calculation_snapshot,
    }


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
# single-physical-establishment, TRUE multi-establishment (via
# EmployeeEstablishment — see _resolve_ca_multi_establishment_poe),
# remote-attachment, payroll-fallback and CA-XP (Phase 9) cases.
_CA_PROVINCES_TERRITORIES = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"}
# CA-XP (§3: "In Canada beyond limits of a province/territory") — a
# deliberately-typed work_state, not an inferred one. Recognizing it
# here only affects poe_result/poe_reason (the audit snapshot) and which
# state-scoped config attempts to load (none, same as before this
# existed, since "XP" was never a real province) — it does NOT change
# ctx.work_state itself (every calculate() call site already reads the
# employee's RAW work_state directly, not this resolved value, as
# documented everywhere else in this file), so this needs no rollout
# switch: no existing employee could have had "XP" mean anything before
# Phase 8's beyond-province surtax existed to consume it, and the actual
# tax calculation for such an employee is unchanged by this fix — only
# its audit trail improves from the misleading "UNRESOLVED" to the
# doc's own correct "BEYOND_LIMITS" vocabulary.
_CA_BEYOND_LIMITS_CODE = "XP"


def _resolve_ca_multi_establishment_poe(establishments: Optional[list]) -> tuple[Optional[str], str]:
    """§5 step 3: an employee who physically reports to TWO OR MORE
    employer establishments resolves to whichever they spend the most
    time at (EmployeeEstablishment.time_allocation_pct), tie-broken by
    whichever they most recently worked (last_worked_date — NULL/never-
    worked always loses a tie against a real date). `establishments` is
    the raw list of a single employee's EmployeeEstablishment rows (or
    dicts with the same keys — either works, only attribute/dict access
    differs below).

    Returns (None, "UNRESOLVED") when fewer than two ACTIVE, recognized-
    province rows are given: an employee with 0 or 1 such row has no
    "multi" case to resolve, and the caller falls through to the
    existing single-work_state/remote/fallback chain completely
    unaffected, exactly as if this table didn't exist for them."""
    def _get(e, key):
        return e.get(key) if isinstance(e, dict) else getattr(e, key, None)

    active = [
        e for e in (establishments or [])
        if _get(e, "is_active") is not False
        and _get(e, "province")
        and str(_get(e, "province")).strip().upper() in _CA_PROVINCES_TERRITORIES
    ]
    if len(active) < 2:
        return None, "UNRESOLVED"

    def _sort_key(e):
        pct = _get(e, "time_allocation_pct") or Decimal("0")
        last_worked = _get(e, "last_worked_date") or date.min
        return (pct, last_worked)

    best = max(active, key=_sort_key)
    return str(_get(best, "province")).strip().upper(), "PHYSICAL_MULTI"


def _resolve_ca_poe_with_source(
    work_state: Optional[str], org_jurisdiction_state: Optional[str],
    remote_work_agreement: bool = False, remote_attachment_province: Optional[str] = None,
    establishments: Optional[list] = None,
) -> tuple[Optional[str], str]:
    """Returns (poe_result, poe_reason) using the doc's own machine-
    readable reason-code vocabulary, checked in the doc's own §5
    precedence order: BEYOND_LIMITS (work_state is literally the CA-XP
    code "XP" — a deliberate declaration, per §3/§5 step 7, that this
    employer/employee genuinely has no Canadian establishment; see
    _CA_BEYOND_LIMITS_CODE's own comment for why this needs no rollout
    switch) wins first, ahead of every physical-establishment check
    since "XP" is never itself a real province code, so they can never
    collide; PHYSICAL_MULTI (§5 step 3 — two or more active
    EmployeeEstablishment rows on file; see
    _resolve_ca_multi_establishment_poe) next, since a genuinely
    multi-establishment employee's single work_state field is at best a
    stale snapshot of wherever they were last assigned, not this
    resolver's real answer once establishment records exist for them;
    PHYSICAL_SINGLE (the employee's own recorded work_state — treated as
    their one physical reporting establishment) next; REMOTE_ATTACHED (a
    full-time remote-work agreement is on file, with a declared
    attachment province) only applies when there's no physical
    work_state — an employee who reports somewhere physical is never
    overridden by a stale/unrelated remote-agreement flag;
    PAYROLL_FALLBACK (none of the above; falls back to the org's own
    jurisdiction state, same fallback every other country already uses);
    or UNRESOLVED (nothing is a recognized province/territory code and
    no explicit CA-XP declaration either — returns None rather than
    passing bad data through to jurisdiction-scoped config lookup, or
    guessing that an employee with simply-not-yet-entered data is
    somehow genuinely beyond-province). remote_agreement_effective_from
    is stored as evidence but not enforced against the payroll date here
    — no other employee declaration field (TD1, tax_code,
    w4_filing_status, ...) in this codebase enforces its own effective-
    dating at this layer either, only the current value is ever read."""
    if work_state and work_state.strip().upper() == _CA_BEYOND_LIMITS_CODE:
        return _CA_BEYOND_LIMITS_CODE, "BEYOND_LIMITS"
    multi_result, multi_reason = _resolve_ca_multi_establishment_poe(establishments)
    if multi_result:
        return multi_result, multi_reason
    if work_state and work_state.strip().upper() in _CA_PROVINCES_TERRITORIES:
        return work_state.strip().upper(), "PHYSICAL_SINGLE"
    if remote_work_agreement and remote_attachment_province and remote_attachment_province.strip().upper() in _CA_PROVINCES_TERRITORIES:
        return remote_attachment_province.strip().upper(), "REMOTE_ATTACHED"
    if org_jurisdiction_state and org_jurisdiction_state.strip().upper() in _CA_PROVINCES_TERRITORIES:
        return org_jurisdiction_state.strip().upper(), "PAYROLL_FALLBACK"
    return None, "UNRESOLVED"


def _resolve_country_aware_state(country: str, employee, literal_state: Optional[str], db: Session = None, organization_id: int = None) -> tuple[Optional[str], Optional[str]]:
    """Returns (resolution_state, poe_reason) — resolution_state is the
    value actually passed to _resolve_effective_rate_inputs's/
    get_state_scoped_config's `state` param for rate/slab lookup;
    poe_reason is only ever non-None for CA (ZP-TAX-CA-2026-001 §5's
    machine-readable reason-code vocabulary — see
    _resolve_ca_poe_with_source), None for every other country. Callers
    that don't need the reason can discard it (`state, _reason = ...`).

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
    (multi-establishment -> physical work_state -> remote attachment ->
    payroll fallback) instead of the raw fallback chain, so an
    unrecognized province code resolves to no jurisdiction rather than
    being passed through as-is — see _resolve_ca_poe_with_source.
    Previously this reason was computed and immediately discarded
    (ZP-TAX-CA-2026-001 CA-D03/AC-07 require it persisted into the
    calculation snapshot) — see _compute_payslip_values'/
    add_payslip_item's `poe_snapshot`."""
    org_fallback_state = None
    if not literal_state and db is not None:
        org_fallback_state = _resolve_org_jurisdiction_state_fallback(db, organization_id, country)
    effective_state = literal_state or org_fallback_state

    if country == "UK":
        sub_jurisdiction, _source = _resolve_uk_sub_jurisdiction_with_source(getattr(employee, "tax_code", None), effective_state)
        return sub_jurisdiction, None
    if country == "CA":
        establishments = []
        employee_id = getattr(employee, "id", None)
        if db is not None and employee_id:
            establishments = (
                db.query(EmployeeEstablishment)
                .filter(
                    EmployeeEstablishment.employee_id == employee_id,
                    EmployeeEstablishment.is_active.is_(True),
                )
                .all()
            )
        poe_result, reason = _resolve_ca_poe_with_source(
            literal_state, org_fallback_state,
            remote_work_agreement=bool(getattr(employee, "remote_work_agreement", False)),
            remote_attachment_province=getattr(employee, "remote_attachment_province", None),
            establishments=establishments,
        )
        return poe_result, reason
    return effective_state, None


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
    sub_rate_map, sub_slabs = get_state_scoped_config(db, "UK", sub_jurisdiction, as_of=payroll_date)

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
        # Routed through the one canonical pack resolver (engine/tax_resolver.py)
        # instead of this function's own prior ad-hoc query — that query
        # didn't apply effective_from/effective_to filtering the way
        # _find_active_tax_pack does, which is exactly the class of bug
        # that silently made India's canonical pack unresolvable for
        # months (see the Fallback Removal effort). This function has no
        # live callers today, so the fix changes no observable behavior;
        # it closes the gap before this becomes a live one.
        from app.modules.payroll.engine.tax_resolver import find_active_tax_pack
        sub_pack = find_active_tax_pack(db, "UK", state=sub_jurisdiction, as_of=payroll_date)

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
        state_rate_map, state_slabs = get_state_scoped_config(db, country, state, as_of=payroll_date)
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
    _invalidate_pack_approval_on_edit(pack)

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
    _invalidate_pack_approval_on_edit(pack)

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
    # Real gap this closes: this function previously had NO status check
    # at all — a rate could be deleted from a currently-Active, in-force
    # pack, silently zeroing that component for every future calculation
    # against it (no new-version safety net, unlike an edit). Same
    # immutability contract upsert_canonical_contribution_rate already
    # enforces for edits, applied here for deletes too.
    if pack:
        _require_editable_pack(pack)
        _invalidate_pack_approval_on_edit(pack)
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
    # Same real gap/fix as delete_canonical_contribution_rate above — no
    # status check previously existed here at all.
    if pack:
        _require_editable_pack(pack)
        _invalidate_pack_approval_on_edit(pack)
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
        # country+state+regime whose EFFECTIVE DATE RANGES actually overlap
        # (Phase 22 duplicate/overlap guard). Originally compared tax_year
        # equality instead of real date ranges — that blocked legitimate
        # non-overlapping same-year splits (e.g. Canada's CA-2026-H1
        # Jan-Jun / CA-2026-H2 Jul-Dec, both tax_year "2026") from ever
        # being Active together, even though _find_active_tax_pack's own
        # resolver already picks between multiple Active packs by date
        # range. A NULL effective_to is treated as open-ended (unbounded).
        far_future = date(9999, 12, 31)
        far_past = date(1, 1, 1)
        target_from = row.effective_from or far_past
        target_to = row.effective_to or far_future
        conflict = (
            db.query(JurisdictionPack)
            .filter(
                JurisdictionPack.id != row.id,
                JurisdictionPack.pack_type == "tax",
                JurisdictionPack.status == "Active",
                JurisdictionPack.jurisdiction_country == row.jurisdiction_country,
                JurisdictionPack.jurisdiction_state == row.jurisdiction_state,
                JurisdictionPack.tax_regime == row.tax_regime,
                JurisdictionPack.effective_from <= target_to,
                or_(JurisdictionPack.effective_to.is_(None), JurisdictionPack.effective_to >= target_from),
            )
            .first()
        )
        if conflict:
            raise BadRequestException(
                f"Pack {conflict.pack_id} v{conflict.version} is already Active for this "
                f"country/state/regime and its effective dates overlap with this pack's — "
                f"supersede it before activating a new version."
            )
        # Same inverted-date guard as upsert_jurisdiction_pack — belt and
        # suspenders, since a pack saved before that guard existed could
        # still be activated here without ever going back through upsert.
        if row.effective_from and row.effective_to and row.effective_to < row.effective_from:
            raise BadRequestException(
                "This pack's Effective To date is before its Effective From date — "
                "fix the date range before activating it; it would never resolve for any calculation."
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
    """NOT EXPOSED over HTTP — the Super Admin "Hard Delete Pack" UI action
    and its backend route were deliberately removed (Production-Grade
    Refactor: Remove Hardcoded Payroll Fallbacks, Enforce Active Compliance
    Packs). A production compliance pack should never be casually,
    permanently destroyed. Use set_jurisdiction_pack_status(..., "Retired")
    for normal lifecycle retirement instead — every pack resolver already
    filters on status=="Active", so a Retired pack is already unresolvable
    to any calculation or onboarding check, without losing its history.

    This function is kept only as a one-off maintenance escape hatch (e.g.
    cleaning up a test pack created by mistake) — call it directly from a
    script/shell if that's ever genuinely needed. Do not re-add an HTTP
    route to this without explicit product sign-off.

    Permanently delete a Tax or Policy pack — the pack row itself, its
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
    "state_program_deductions": ("State Payroll Programs (e.g. Paid Leave/TDI)", "currency", True),
    "ni_employee": ("National Insurance (Employee)", "currency", True),
    "study_loan_deduction": ("Student/Postgraduate Loan Deduction", "currency", True),
    "postgrad_loan_deduction": ("Postgraduate Loan Deduction (Concurrent)", "currency", True),
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
    "employer_state_program_contributions": ("State Payroll Programs (Employer)", "currency", True),
    "employer_cpp2": ("CPP2 (Employer)", "currency", True),
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
           "tds", "ni_employee", "study_loan_deduction", "postgrad_loan_deduction", "employee_pension", "total_deductions",
           "employer_ni", "employer_pension", "net_pay"],
    "US": ["employee_name", "department", "designation", "bank_name", "bank_account",
           "basic_salary", "hra", "special_allowance", "overtime", "additional_compensation", "gross_pay",
           "federal_income_tax", "state_income_tax", "local_tax", "social_security", "medicare",
           "state_disability_insurance", "state_program_deductions", "total_deductions",
           "employer_social_security", "employer_medicare", "employer_futa", "employer_sui",
           "employer_state_program_contributions", "net_pay"],
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
           "total_deductions", "employer_social_security", "employer_esi", "employer_sui", "employer_cpp2",
           "net_pay"],
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
    # None (not "IN") when nothing is configured anywhere — the query
    # below naturally returns an empty list for a None country rather than
    # showing India's filing calendar to an org that hasn't set one up yet.
    country = _resolve_org_country(db, organization_id)
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
    db: Session, country: Optional[str], state: Optional[str], reporting_year: str, report_type: str,
    as_of: Optional[date] = None,
) -> Optional[ReportTemplate]:
    """Mirrors engine/tax_resolver.py's _find_active_tax_pack: prefers an
    exact state match, falls back to the country-level (state IS NULL)
    template, filters on report_type/reporting_year and effective dates.
    Falls back to a Published (not yet Active) template only when no
    Active version exists — a Published template is a legitimate preview
    candidate, but an Active version always wins when both exist. Returns
    None (never raises) when nothing resolves — including when `country`
    itself is None (caller's jurisdiction isn't configured yet); NOT
    normalized to "IN" in that case, since the query below already
    returns nothing for a None country, exactly the correct outcome."""
    country = _normalize_country(country) if country else None
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
    # None when nothing is configured anywhere — correctly yields an empty
    # report list rather than offering an unconfigured org India's reports.
    country = _resolve_org_country(db, organization_id)
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
    # None when nothing is configured anywhere — get_applicable_report_template
    # correctly resolves to no template (rather than India's) for a None country.
    country = _resolve_org_country(db, organization_id)
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
    # None when nothing is configured anywhere — reported as its own clear
    # reason below rather than silently comparing against an assumed "IN".
    org_country = _resolve_org_country(db, organization_id)
    org_state = getattr(company, "jurisdiction_state", None) or None

    if org_country is None:
        reasons.append("This organization hasn't configured a jurisdiction yet — set it under Compliance > Company Details.")
        jurisdiction_match = False
    else:
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
    ``policy.service.get_active_policy`` — a get-or-create that always
    returns a real policy (auto-seeding a default one on first use), so
    there's no legitimate "no policy configured" failure to swallow here;
    a real error (DB issue, a bug in the seed path) is left to propagate
    rather than being silently hidden behind ``"standard"``."""
    if calculation_mode:
        return calculation_mode
    from app.modules.payroll.policy.service import get_active_policy
    policy = get_active_policy(db, organization_id)
    return policy.calculation_mode or "standard"


def preview_payroll_run(db: Session, organization_id: int, employee_ids: List[int], country: str,
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
    from app.modules.payroll.engine.germany_pap.core import GermanyCalculationError

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
    # Per-distinct-resolved-country cache (Phase 7 fix — see this
    # function's docstring update below). Before this fix, `rate_map`/
    # `slabs` were resolved ONCE for the whole batch using the caller's
    # top-level `country` argument, and every employee's ctx.country was
    # set to that same value regardless of the employee's own
    # `country_code` — a mixed-country batch (or any batch where the
    # caller's `country` didn't match a given employee's actual
    # `country_code`, e.g. a German employee previewed via a page that
    # defaults to the org's country) silently calculated that employee
    # under the WRONG country's rules, or never reached
    # engine/countries/germany.py at all. Preview must never disagree
    # with what generate_payslips_for_run would actually do for the same
    # employee — _resolve_employee_calc_inputs already gets this right;
    # this mirrors it here.
    _country_rate_cache: dict = {country: (rate_map, slabs, _canonical_rates, _pack)}

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

        # Phase 7 fix: resolve THIS employee's own country (falling back to
        # the batch-level `country` exactly like _resolve_employee_country
        # does for every other entry point), not the caller's top-level
        # argument unconditionally — see _country_rate_cache's comment above.
        emp_country = _resolve_employee_country(db, organization_id, getattr(emp, "country_code", None)) or country
        if emp_country not in _country_rate_cache:
            _country_rate_cache[emp_country] = _resolve_effective_rate_inputs(
                db, organization_id, emp_country, period_end or date.today(), org_opted_in,
            )
        emp_rate_map, emp_slabs, _emp_canonical_rates, _emp_pack = _country_rate_cache[emp_country]

        work_state = getattr(emp, "work_state", None)
        # Phase 7 fix (Germany) + Canada filing-status caching (main) both
        # apply here: resolve state/cache-key using THIS employee's own
        # resolved country (emp_country), never the caller's batch-level
        # `country`, and key the cache by (country, state, filing_status)
        # so mixed-country AND mixed-filing-status batches both resolve
        # correctly per employee.
        resolution_state, _poe_reason = _resolve_country_aware_state(emp_country, emp, work_state, db=db, organization_id=organization_id)
        emp_filing_status = getattr(emp, "w4_filing_status", None)
        state_cache_key = (emp_country, resolution_state, emp_filing_status)
        if state_cache_key not in _state_scoped_cache:
            _state_scoped_cache[state_cache_key] = get_state_scoped_config(
                db, emp_country, resolution_state, as_of=period_end or date.today(), filing_status=emp_filing_status,
            )
        state_rate_map, state_slabs = _state_scoped_cache[state_cache_key]

        germany_kwargs = {}
        if emp_country == "DE":
            resolved_de = _resolve_germany_calc_inputs(db, organization_id, emp, period_end or date.today())
            germany_kwargs = dict(
                germany_statutory_profile=resolved_de["statutory_profile"],
                germany_pap_asset=resolved_de["pap_asset"],
                germany_health_fund=resolved_de["health_fund"],
                germany_u1_tariff=resolved_de["u1_tariff"],
                germany_earning_taxability=resolved_de["earning_taxability"],
                germany_ceiling_gkv_pv=resolved_de["ceiling_gkv_pv"],
                germany_ceiling_rv_alv=resolved_de["ceiling_rv_alv"],
                germany_pv_configuration=resolved_de["pv_configuration"],
                germany_church_tax_exception=resolved_de["church_tax_exception"],
                germany_employee_id=emp.id,
                germany_organization_id=organization_id,
                germany_payroll_date=period_end or date.today(),
                germany_sonstb=_sum_attendance_bonus_only(
                    db, organization_id, emp.id, period_start, period_end,
                    records=attendance_by_employee.get(emp.id, []),
                ),
            )

        # Canada YTD — READ ONLY (see _load_ca_ytd's own docstring): this
        # function persists no PayrollRun/PayslipItem, so it must never
        # write to PayrollYtdAccumulator, only reflect its current state.
        # Gated on emp_country (not the batch-level `country`), same
        # per-employee-correctness reasoning as the state resolution above.
        ytd_inputs = (
            _load_ca_ytd(db, emp.id, period_end or date.today(), work_state)
            if emp_country == "CA" else
            _load_uk_director_ytd(db, emp.id, period_end or date.today())
            if emp_country == "UK" else {}
        )

        # Ontario EHT / BC EHT / Manitoba HE Levy / NL HAPSET org-level —
        # READ ONLY, same reasoning as ytd_inputs above: preview persists
        # nothing, so it must reflect the org's current running total
        # without ever incrementing it.
        org_levy_inputs = (
            _ca_org_levy_read_inputs(db, organization_id, period_end or date.today(), work_state)
            if emp_country == "CA" else
            _load_uk_org_levy_ytd(db, organization_id, period_end or date.today())
            if emp_country == "UK" else {}
        )

        employee_name = getattr(emp, "name", None) or f"Employee #{emp.id}"

        # Delegate to the strategy engine
        ctx = build_context_from_employee(
            emp, gross=gross, basic=basic, hra=hra,
            special_allowance=special, overtime=overtime,
            additional_compensation=additional_compensation,
            unpaid_leave_days=unpaid_leave_days,
            country=emp_country, rate_map=emp_rate_map, slabs=emp_slabs,
            work_state=work_state, state_rate_map=state_rate_map, state_slabs=state_slabs,
            **germany_kwargs,
            pay_date=period_end or date.today(),
            **ytd_inputs,
            **org_levy_inputs,
        )
        try:
            calc = calculate_payroll(ctx, calculation_mode)
        except GermanyCalculationError as exc:
            # Preview is diagnostic across a batch — one blocked German
            # employee must not abort the whole preview (unlike a real
            # run, see generate_payslips_for_run, which correctly DOES
            # fail the whole request). Surface the block + trace instead.
            results.append({
                "employeeId": emp.id,
                "employeeName": employee_name,
                "department": getattr(emp, "department", None),
                "attendanceStatus": "active" if is_active else "inactive",
                "blocked": True,
                "blockedReasonCode": exc.code,
                "blockedReasonMessage": exc.message,
                "calculationTrace": exc.trace.to_dict() if exc.trace else None,
            })
            continue

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
            "monthlyEmployeeLwf": float(calc.employee_lwf),
            "monthlyEmployerLwf": float(calc.employer_lwf),
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
            "monthlyPostgradLoanDeduction": float(calc.postgrad_loan_deduction),
            # total_deductions includes tds; subtract it here so "Contributions"
            # and "Taxes" are non-overlapping components that add up to the
            # actual total deduction, matching how the UI displays them side
            # by side (see get_bank_transfer_summary for the same tds overlap).
            "monthlyContributions": float(calc.total_deductions - calc.tds),
            "monthlyNet": float(calc.net_pay),
            "employerPf": float(calc.employer_pf),
            "employerEps": float(calc.employer_eps),
            "employerPfResidual": float(calc.employer_pf_residual),
            "employerEdli": float(calc.employer_edli),
            "employerNps": float(calc.employer_nps),
            "employerEsi": float(calc.employer_esi),
            "employerSs": float(calc.employer_social_security),
            "employerMedicare": float(calc.employer_medicare),
            "employerPension": float(calc.employer_pension),
            "employeePension": float(calc.employee_pension),
            "employerNi": float(calc.employer_ni),
            "employerCpp2": float(calc.employer_cpp2),
            "cppBaseAmount": float(calc.cpp_base_amount),
            "cppFirstAdditionalAmount": float(calc.cpp_first_additional_amount),
            "employerCppBase": float(calc.employer_cpp_base),
            "employerCppFirstAdditional": float(calc.employer_cpp_first_additional),
            "employerEht": float(calc.employer_eht),
            "employerBcEht": float(calc.employer_bc_eht),
            "employerMbHeLevy": float(calc.employer_mb_he_levy),
            "employerNlHapset": float(calc.employer_nl_hapset),
            "employerQcHsf": float(calc.employer_qc_hsf),
            "employerQcLabourStandards": float(calc.employer_qc_labour_standards),
            "taxSlabRate": _get_slab_label(calc.gross * MONTHS_PER_YEAR, emp_slabs, emp_country, annual_tax=calc.annual_tax),
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


def _get_slab_label(annual_income: Decimal, slabs: List[TaxSlab], country: str,
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


def _sum_attendance_bonus_only(db: Session, organization_id: int, employee_id: int,
                                period_start, period_end, records: List["PayrollAttendanceRecord"] = None) -> Decimal:
    """Phase 8T — Germany SONSTB routing (ZP-TAX-DE-2026-001 §15 "Bonus /
    annual bonus... Other remuneration route"). Deliberately narrower than
    _sum_attendance_extras: only the `bonus` field is a genuine statutory
    "Bonus" per the spec's own taxability-matrix row — `rewards` and
    `other_compensation` are NOT reclassified as SONSTB (the spec gives no
    basis to do so), and both remain part of ordinary gross/RE4 exactly as
    before. Same records-reuse convention as _sum_attendance_extras (pass
    pre-fetched rows to avoid a second query when both are needed for the
    same employee/period)."""
    if records is None:
        records = db.query(PayrollAttendanceRecord).filter(
            PayrollAttendanceRecord.organization_id == organization_id,
            PayrollAttendanceRecord.employee_id == employee_id,
            PayrollAttendanceRecord.date >= period_start,
            PayrollAttendanceRecord.date <= period_end,
        ).all()
    return _round2(sum((Decimal(str(r.bonus or 0)) for r in records), Decimal("0")))


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


# ── Canada YTD accumulator (CPP/CPP2/EI, QPP/QPP2/QPIP) ─────────────────
# Dormant until "CA" is added to engine/countries/shared.py's
# _YTD_ACCUMULATOR_ENABLED_COUNTRIES (a plain in-code rollout switch, same
# convention as _VALIDATION_ENABLED_COUNTRIES) — see that file's own
# rollout-log comment for why it isn't flipped on yet.

_CA_YTD_COMPONENTS = ("cpp", "cpp2", "ei", "cpp_basic_exemption")
_QC_YTD_COMPONENTS = ("qpp", "qpp2", "qpip", "qpp_basic_exemption")


def _ca_ytd_tax_year(pay_date, work_state: str = None) -> str:
    """Calendar-year accumulator key — deliberately its own concept, not
    JurisdictionPack.tax_year (a free-text display label like "2026") or
    the report-only SUM_YTD helper's Jan-1 approximation (see
    _resolve_field_value's SUM_YTD branch) — this is the real key an
    accumulator row is looked up/upserted by."""
    prefix = "CA-QC" if (work_state or "").strip().upper() == "QC" else "CA"
    return f"{prefix}-CY-{pay_date.year}"


def _load_ca_ytd(db: Session, employee_id: int, pay_date, work_state: str = None) -> dict:
    """Returns kwargs for build_context_from_employee's ytd_* params —
    empty dict (today, for every employee) when CA hasn't opted into the
    rollout switch, or when no accumulator rows exist yet for this
    employee/tax-year (a brand-new employee's first CA payslip of the
    year). Never guesses/backfills a starting value — see
    engine/countries/shared.py's own rollout-log note on why no
    retroactive backfill is possible."""
    if "CA" not in _YTD_ACCUMULATOR_ENABLED_COUNTRIES:
        return {}
    tax_year = _ca_ytd_tax_year(pay_date, work_state)
    is_qc = (work_state or "").strip().upper() == "QC"
    components = _QC_YTD_COMPONENTS if is_qc else _CA_YTD_COMPONENTS
    rows = (
        db.query(PayrollYtdAccumulator)
        .filter(
            PayrollYtdAccumulator.employee_id == employee_id,
            PayrollYtdAccumulator.tax_year == tax_year,
            PayrollYtdAccumulator.tax_component.in_(components),
        )
        .all()
    )
    by_component = {r.tax_component: r.ytd_taxable_wages for r in rows}
    pension_key, cpp2_key, insurable_key, exemption_key = components
    return dict(
        ytd_pensionable_earnings=by_component.get(pension_key, Decimal("0")),
        ytd_cpp2_pensionable_earnings=by_component.get(cpp2_key, Decimal("0")),
        ytd_insurable_earnings=by_component.get(insurable_key, Decimal("0")),
        ytd_basic_exemption_used=by_component.get(exemption_key, Decimal("0")),
    )


def _upsert_ca_ytd_accumulator(db: Session, employee_id: int, pay_date, work_state: str, result, payslip_id: int = None):
    """Writes this period's post-calculation cumulative YTD values back to
    PayrollYtdAccumulator — get-or-create per (employee, tax_year,
    component), flush (not commit; caller's own transaction boundary
    still governs). No-op if the result carries no YTD figures (i.e. the
    calculation ran dormant — result.ytd_pensionable_earnings is None),
    so calling this unconditionally from every persisting entry point is
    safe even while the rollout switch is off."""
    if result.ytd_pensionable_earnings is None:
        return
    tax_year = _ca_ytd_tax_year(pay_date, work_state)
    is_qc = (work_state or "").strip().upper() == "QC"
    components = _QC_YTD_COMPONENTS if is_qc else _CA_YTD_COMPONENTS
    pension_key, cpp2_key, insurable_key, exemption_key = components
    values = {
        pension_key: result.ytd_pensionable_earnings,
        cpp2_key: result.ytd_cpp2_pensionable_earnings,
        insurable_key: result.ytd_insurable_earnings,
        exemption_key: result.ytd_basic_exemption_used,
    }
    for component, value in values.items():
        if value is None:
            continue
        row = (
            db.query(PayrollYtdAccumulator)
            .filter(
                PayrollYtdAccumulator.employee_id == employee_id,
                PayrollYtdAccumulator.tax_year == tax_year,
                PayrollYtdAccumulator.tax_component == component,
            )
            .first()
        )
        if row is None:
            row = PayrollYtdAccumulator(employee_id=employee_id, tax_year=tax_year, tax_component=component)
            db.add(row)
        row.ytd_taxable_wages = value
        row.last_updated_payslip_id = payslip_id
    db.flush()


# ── UK Directors NIC YTD accumulator (ZP-TAX-UK-2026-27-001 §9.2) ───────
# Dormant until "UK" is added to the SAME shared
# _YTD_ACCUMULATOR_ENABLED_COUNTRIES set Canada uses above (one switch,
# multiple countries — see engine/countries/shared.py). Unlike Canada's
# CPP/EI (which only ever need cumulative WAGES, since a flat rate makes
# "amount already paid" fully re-derivable from wages alone), a
# director's NIC true-up genuinely needs the actual amount already paid
# tracked as its own number — the whole reason the ALTERNATIVE method
# needs a final reconciliation at all is that ordinary per-period
# payments do NOT necessarily match what the annual-cumulative method
# would have produced at the same point. This is the first real consumer
# of PayrollYtdAccumulator.ytd_tax_withheld (already declared, never
# populated by Canada's own upsert above) — no new column needed.
_UK_DIRECTOR_NI_EMPLOYEE_COMPONENT = "uk_director_ni_ee"
_UK_DIRECTOR_NI_EMPLOYER_COMPONENT = "uk_director_ni_er"


def _uk_tax_year(pay_date) -> str:
    """UK's real tax year (6 April Y to 5 April Y+1) — deliberately its
    own concept, not JurisdictionPack.tax_year, same reasoning as
    _ca_ytd_tax_year's own docstring."""
    start_year = pay_date.year if (pay_date.month, pay_date.day) >= (4, 6) else pay_date.year - 1
    return f"UK-TY-{start_year}-{str(start_year + 1)[-2:]}"


def _load_uk_director_ytd(db: Session, employee_id: int, pay_date) -> dict:
    """Returns kwargs for build_context_from_employee's
    ytd_director_ni_* params — empty dict when UK hasn't opted into the
    shared rollout switch, or when no accumulator rows exist yet for this
    employee/tax-year (a director's first UK payslip of the tax year).
    Never guesses/backfills a starting value, same discipline as
    _load_ca_ytd."""
    if "UK" not in _YTD_ACCUMULATOR_ENABLED_COUNTRIES:
        return {}
    tax_year = _uk_tax_year(pay_date)
    rows = (
        db.query(PayrollYtdAccumulator)
        .filter(
            PayrollYtdAccumulator.employee_id == employee_id,
            PayrollYtdAccumulator.tax_year == tax_year,
            PayrollYtdAccumulator.tax_component.in_((_UK_DIRECTOR_NI_EMPLOYEE_COMPONENT, _UK_DIRECTOR_NI_EMPLOYER_COMPONENT)),
        )
        .all()
    )
    by_component = {r.tax_component: r for r in rows}
    employee_row = by_component.get(_UK_DIRECTOR_NI_EMPLOYEE_COMPONENT)
    employer_row = by_component.get(_UK_DIRECTOR_NI_EMPLOYER_COMPONENT)
    if employee_row is None and employer_row is None:
        return {}
    return dict(
        ytd_director_ni_gross=(employee_row or employer_row).ytd_taxable_wages,
        ytd_director_ni_employee_paid=employee_row.ytd_tax_withheld if employee_row else Decimal("0"),
        ytd_director_ni_employer_paid=employer_row.ytd_tax_withheld if employer_row else Decimal("0"),
    )


def _upsert_uk_director_ytd_accumulator(db: Session, employee_id: int, pay_date, result, payslip_id: int = None):
    """Writes this period's post-calculation cumulative YTD values back to
    PayrollYtdAccumulator — get-or-create per (employee, tax_year,
    component), same SET-the-after-value (not add-to-it) and flush-not-
    commit contract as _upsert_ca_ytd_accumulator: the ENGINE (uk.py's
    calculate()) computes the correct post-period cumulative figures —
    this function only ever writes what it's told. No-op if the result
    carries no director YTD figures (result.ytd_director_ni_gross is
    None — either not a director, or the rollout switch is off), so
    calling this unconditionally from every persisting entry point is
    safe regardless."""
    if result.ytd_director_ni_gross is None:
        return
    tax_year = _uk_tax_year(pay_date)
    values = {
        _UK_DIRECTOR_NI_EMPLOYEE_COMPONENT: (result.ytd_director_ni_gross, result.ytd_director_ni_employee_paid),
        _UK_DIRECTOR_NI_EMPLOYER_COMPONENT: (result.ytd_director_ni_gross, result.ytd_director_ni_employer_paid),
    }
    for component, (wages, withheld) in values.items():
        row = (
            db.query(PayrollYtdAccumulator)
            .filter(
                PayrollYtdAccumulator.employee_id == employee_id,
                PayrollYtdAccumulator.tax_year == tax_year,
                PayrollYtdAccumulator.tax_component == component,
            )
            .first()
        )
        if row is None:
            row = PayrollYtdAccumulator(employee_id=employee_id, tax_year=tax_year, tax_component=component)
            db.add(row)
        row.ytd_taxable_wages = wages
        row.ytd_tax_withheld = withheld
        row.last_updated_payslip_id = payslip_id
    db.flush()


# ── Canada org-level employer levy accumulator ──────────────────────────
# Foundational infrastructure for Ontario/BC EHT, Manitoba HE Levy, NL
# HAPSET, and Quebec HSF (ZP-TAX-CA-2026-001 §13/§15/§16) — all banded on
# an ORGANIZATION's aggregate annual remuneration across every employee,
# not any single employee's own pay. No levy calculation reads or writes
# this yet (that's each levy's own future addition); this is deliberately
# built and tested standalone first, same as the per-employee YTD
# accumulator's own plumbing was proven before canada.py's CPP/CPP2/EI
# math was changed to consume it. Dormant behind
# _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES (engine/countries/shared.py) —
# currently empty, so these functions are unreachable from any live
# calculation path until a levy is actually wired to call them.

def _org_ytd_tax_year(pay_date, country: str = "CA") -> str:
    """Calendar-year accumulator key — same convention as _ca_ytd_tax_year,
    deliberately its own concept from JurisdictionPack.tax_year."""
    return f"{country}-CY-{pay_date.year}"


def _load_ca_org_levy_ytd(db: Session, organization_id: int, pay_date, components: tuple) -> dict:
    """Generic org-level aggregate-remuneration YTD reader — the org-level
    counterpart to _load_ca_ytd. Returns {} when the rollout switch is
    off (every org today); once enabled, returns {component:
    ytd_taxable_wages} for every requested component, defaulting an
    unconfigured component to Decimal("0") rather than omitting it, so a
    caller can always safely read every key it asked for."""
    if "CA" not in _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES:
        return {}
    tax_year = _org_ytd_tax_year(pay_date)
    rows = (
        db.query(OrganizationYtdAccumulator)
        .filter(
            OrganizationYtdAccumulator.organization_id == organization_id,
            OrganizationYtdAccumulator.tax_year == tax_year,
            OrganizationYtdAccumulator.tax_component.in_(components),
        )
        .all()
    )
    by_component = {r.tax_component: r.ytd_taxable_wages for r in rows}
    return {c: by_component.get(c, Decimal("0")) for c in components}


def _upsert_ca_org_levy_ytd(db: Session, organization_id: int, pay_date, increments: dict, payslip_id: int = None):
    """Adds this period's taxable-wage contribution to the org's running
    total per component — get-or-create per (org, tax_year, component),
    flush (not commit; caller's transaction boundary governs), safe under
    the same sequential single-transaction per-employee db.flush()
    ordering already proven for the per-employee accumulator inside
    generate_payslips_for_run's loop.

    Unlike _upsert_ca_ytd_accumulator (which SETS an absolute post-period
    value the caller already computed by reading the prior total itself),
    this ADDS an increment: no single employee's calculation has
    visibility into the org's running total across every OTHER employee,
    so the accumulator row itself — not the caller — is the source of
    truth for the aggregate. `increments` maps component -> this
    employee's own contribution this period (typically their period
    gross, or whatever subset of it is levy-subject); a falsy/zero
    increment for a component is skipped, not written as a no-op update."""
    if not increments:
        return
    tax_year = _org_ytd_tax_year(pay_date)
    for component, increment in increments.items():
        if not increment:
            continue
        row = (
            db.query(OrganizationYtdAccumulator)
            .filter(
                OrganizationYtdAccumulator.organization_id == organization_id,
                OrganizationYtdAccumulator.tax_year == tax_year,
                OrganizationYtdAccumulator.tax_component == component,
            )
            .first()
        )
        if row is None:
            row = OrganizationYtdAccumulator(organization_id=organization_id, tax_year=tax_year, tax_component=component)
            db.add(row)
        row.ytd_taxable_wages = (row.ytd_taxable_wages or Decimal("0")) + increment
        row.last_updated_payslip_id = payslip_id
    db.flush()


# One raw work_state maps to at most one of these five org-banded levies
# (ZP-TAX-CA-2026-001 §13/§15) — same (documented, pre-existing) raw-
# work_state gating _calculate_provincial_tax_ca's is_quebec check and
# Ontario EHT's own gate already use, rather than the fully POE-resolved
# province: an employee reached only via the org-jurisdiction-state
# fallback (no work_state of their own) is not caught by this either.
_CA_ORG_LEVY_COMPONENT_BY_WORK_STATE = {
    "ON": "on_eht", "BC": "bc_eht", "MB": "mb_he_levy", "NL": "nl_hapset", "QC": "qc_hsf",
}
# Components whose calculation branches on a per-org employer
# classification (BC's ordinary-vs-charity, Quebec's HSF category) — the
# CompanyComplianceDetails column name to read, keyed by component.
_CA_ORG_LEVY_CLASSIFICATION_FIELD = {
    "bc_eht": "bc_eht_employer_classification",
    "qc_hsf": "qc_hsf_employer_category",
}


def _ca_org_levy_read_inputs(db: Session, organization_id: int, pay_date, work_state: str) -> dict:
    """Resolve the org-level levy accumulator READ (component + employer
    classification where relevant) for whichever single jurisdiction
    this employee's raw work_state maps to, if any — shared by
    generate_payslips_for_run, add_payslip_item and preview_payroll_run
    so the three entry points can never resolve this differently. Returns
    {} when the employee isn't in one of these five jurisdictions, OR
    when the rollout switch is off (_load_ca_org_levy_ytd's own dormancy
    contract) — the caller then passes nothing through to
    build_context_from_employee, and canada.py resolves that levy to 0."""
    component = _CA_ORG_LEVY_COMPONENT_BY_WORK_STATE.get((work_state or "").strip().upper())
    if not component:
        return {}
    org_levy_ytd = _load_ca_org_levy_ytd(db, organization_id, pay_date, (component,))
    if not org_levy_ytd:
        return {}
    inputs = {f"{component}_ytd_remuneration_before": org_levy_ytd[component]}
    classification_field = _CA_ORG_LEVY_CLASSIFICATION_FIELD.get(component)
    if classification_field:
        compliance = db.query(CompanyComplianceDetails).filter(
            CompanyComplianceDetails.organization_id == organization_id,
        ).first()
        inputs[classification_field] = getattr(compliance, classification_field, None)
    return inputs


# ── UK org-level accumulators: Apprenticeship Levy pay bill (§14) AND ───
# Employment Allowance's cumulative employer_ni total (§14) — same
# OrganizationYtdAccumulator table and ADDS-an-increment contract as
# _upsert_ca_org_levy_ytd above (no single employee's calculation has
# visibility into every OTHER employee's contribution this tax year, so
# the accumulator row is the source of truth for the aggregate), but
# keyed by _uk_tax_year (the real 6-April-to-5-April UK tax year) rather
# than _org_ytd_tax_year's calendar-year key — reusing that one directly
# would misalign the Levy's own annual allowance boundary by up to 3
# months. Both components share this one load/upsert pair (rather than a
# second near-identical pair) since every UK employee needs both read
# together at the same call sites. Dormant behind the SAME shared
# _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES switch Canada's EHT uses ("UK"
# not yet added).
_UK_APPR_LEVY_COMPONENT = "uk_appr_levy"
_UK_EMPLOYER_NI_TOTAL_COMPONENT = "uk_employer_ni_total"


def _load_uk_org_levy_ytd(db: Session, organization_id: int, pay_date) -> dict:
    """Returns {} when the shared rollout switch is off, OR when NEITHER
    accumulator row exists yet (org's first UK payslip of the tax year)
    — never guesses/backfills a starting value, same discipline as every
    other YTD loader in this file. Each component still individually
    defaults to Decimal("0") once at least one exists, matching
    _load_ca_org_levy_ytd's own "always return every key asked for"
    convention."""
    if "UK" not in _ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES:
        return {}
    tax_year = _uk_tax_year(pay_date)
    rows = (
        db.query(OrganizationYtdAccumulator)
        .filter(
            OrganizationYtdAccumulator.organization_id == organization_id,
            OrganizationYtdAccumulator.tax_year == tax_year,
            OrganizationYtdAccumulator.tax_component.in_((_UK_APPR_LEVY_COMPONENT, _UK_EMPLOYER_NI_TOTAL_COMPONENT)),
        )
        .all()
    )
    by_component = {r.tax_component: r.ytd_taxable_wages for r in rows}
    return {
        "appr_levy_ytd_pay_bill_before": by_component.get(_UK_APPR_LEVY_COMPONENT, Decimal("0")),
        "employer_ni_ytd_before": by_component.get(_UK_EMPLOYER_NI_TOTAL_COMPONENT, Decimal("0")),
    }


def _upsert_uk_org_levy_ytd(db: Session, organization_id: int, pay_date, gross_increment: Decimal, employer_ni_increment: Decimal = None, payslip_id: int = None):
    """ADDS this employee's own period gross (and, separately, their own
    period employer_ni) to the org's running totals — NOT the "after"
    figures the engine computed for its own math (those mix in the org's
    prior total, which would double-count here). No-op per-component for
    a falsy/zero increment, matching _upsert_ca_org_levy_ytd's own
    convention."""
    tax_year = _uk_tax_year(pay_date)
    for component, increment in (
        (_UK_APPR_LEVY_COMPONENT, gross_increment),
        (_UK_EMPLOYER_NI_TOTAL_COMPONENT, employer_ni_increment),
    ):
        if not increment:
            continue
        row = (
            db.query(OrganizationYtdAccumulator)
            .filter(
                OrganizationYtdAccumulator.organization_id == organization_id,
                OrganizationYtdAccumulator.tax_year == tax_year,
                OrganizationYtdAccumulator.tax_component == component,
            )
            .first()
        )
        if row is None:
            row = OrganizationYtdAccumulator(organization_id=organization_id, tax_year=tax_year, tax_component=component)
            db.add(row)
        row.ytd_taxable_wages = (row.ytd_taxable_wages or Decimal("0")) + increment
        row.last_updated_payslip_id = payslip_id
    db.flush()


def _compute_payslip_values(db: Session, run: PayrollRun, employee, rate_map, slabs, country: str,
                             calculation_mode: str = "standard", attendance_records: List["PayrollAttendanceRecord"] = None,
                             allowance_components: list = None, resolved_pack=None,
                             state_rate_map: dict = None, state_slabs: list = None,
                             employer_tax_profiles: dict = None, reciprocity: dict = None,
                             locality_rate=None, ytd_inputs: dict = None, poe_snapshot: dict = None,
                             org_levy_inputs: dict = None) -> dict:
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
    way rate_map/slabs already are rather than re-queried per employee.

    `ytd_inputs`: Canada CPP/CPP2/EI year-to-date state (see _load_ca_ytd),
    pre-loaded by the caller — this function stays read-only/side-effect-
    free by design (shared by generation AND recalculation), so it never
    queries or writes PayrollYtdAccumulator itself. None (every non-CA
    calculation, and CA until the caller opts in) means no YTD wired."""
    from app.modules.payroll.engine.resolver import calculate_payroll, build_context_from_employee
    from app.modules.payroll.engine.germany_pap.core import GermanyCalculationError
    from app.core.exceptions import GermanyCalculationBlockedException

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
    germany_kwargs = {}
    if country == "DE":
        resolved = _resolve_germany_calc_inputs(db, run.organization_id, employee, run.pay_date)
        germany_kwargs = dict(
            germany_statutory_profile=resolved["statutory_profile"],
            germany_pap_asset=resolved["pap_asset"],
            germany_health_fund=resolved["health_fund"],
            germany_u1_tariff=resolved["u1_tariff"],
            germany_earning_taxability=resolved["earning_taxability"],
            germany_ceiling_gkv_pv=resolved["ceiling_gkv_pv"],
            germany_ceiling_rv_alv=resolved["ceiling_rv_alv"],
            germany_pv_configuration=resolved["pv_configuration"],
            germany_church_tax_exception=resolved["church_tax_exception"],
            germany_employee_id=employee.id,
            germany_organization_id=run.organization_id,
            germany_payroll_date=run.pay_date,
            germany_sonstb=_sum_attendance_bonus_only(
                db, run.organization_id, employee.id, run.period_start, run.period_end, records=attendance_records,
            ),
        )
    ctx = build_context_from_employee(
        employee, gross=gross, basic=basic, hra=hra,
        special_allowance=special, overtime=overtime,
        additional_compensation=additional_compensation,
        unpaid_leave_days=unpaid_leave_days,
        country=country, rate_map=rate_map, slabs=slabs,
        work_state=work_state, state_rate_map=state_rate_map, state_slabs=state_slabs,
        employer_tax_profiles=employer_tax_profiles,
        locality_rate=locality_rate,
        **germany_kwargs,
        pay_date=run.pay_date,
        **(reciprocity or {}),
        **(ytd_inputs or {}),
        **(org_levy_inputs or {}),
    )
    try:
        result = calculate_payroll(ctx, calculation_mode)
    except GermanyCalculationError as exc:
        raise GermanyCalculationBlockedException(
            exc.code, exc.message, trace=(exc.trace.to_dict() if exc.trace else None),
        )

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
        "employee_lwf": result.employee_lwf,
        "employer_lwf": result.employer_lwf,
        "social_security": result.social_security,
        "medicare": result.medicare,
        "ni_employee": result.ni_employee,
        "study_loan_deduction": result.study_loan_deduction,
        "postgrad_loan_deduction": result.postgrad_loan_deduction,
        "employee_pension": result.employee_pension,
        "church_tax": result.church_tax,
        "cpp2": result.cpp2,
        "cpp_base_amount": result.cpp_base_amount,
        "cpp_first_additional_amount": result.cpp_first_additional_amount,
        "tds": result.tds,
        "surcharge": result.surcharge,
        "cess": result.cess,
        "federal_income_tax": result.federal_income_tax,
        "state_income_tax": result.state_income_tax,
        "local_tax": result.local_tax,
        "state_disability_insurance": result.state_disability_insurance,
        "state_program_deductions": result.state_program_deductions,
        "total_deductions": result.total_deductions,
        "employer_pf": result.employer_pf,
        "employer_eps": result.employer_eps,
        "employer_pf_residual": result.employer_pf_residual,
        "employer_edli": result.employer_edli,
        "employer_nps": result.employer_nps,
        "employer_esi": result.employer_esi,
        "employer_social_security": result.employer_social_security,
        "employer_medicare": result.employer_medicare,
        "employer_pension": result.employer_pension,
        "employer_ni": result.employer_ni,
        "employer_futa": result.employer_futa,
        "employer_sui": result.employer_sui,
        "employer_state_program_contributions": result.employer_state_program_contributions,
        "employer_cpp2": result.employer_cpp2,
        "employer_cpp_base": result.employer_cpp_base,
        "employer_cpp_first_additional": result.employer_cpp_first_additional,
        "employer_eht": result.employer_eht,
        "employer_bc_eht": result.employer_bc_eht,
        "employer_mb_he_levy": result.employer_mb_he_levy,
        "employer_nl_hapset": result.employer_nl_hapset,
        "employer_qc_hsf": result.employer_qc_hsf,
        "employer_qc_labour_standards": result.employer_qc_labour_standards,
        "net_pay": result.net_pay,
        "unpaid_leave_days": result.unpaid_leave_days,
        "attendance_deduction": result.attendance_deduction,
        "per_day_salary": result.per_day_salary,
        # Germany (Phase 7) — statutory calculation provenance, frozen onto
        # the PayslipItem so a finalized German payslip can be reproduced
        # even if the underlying registries later change (spec's
        # reproducibility requirement). None for every non-German payslip
        # and for any German payslip generated before this column existed.
        "employee_statutory_profile_id": result.germany_statutory_profile_id,
        "germany_calculation_snapshot": result.germany_calculation_snapshot,
        # Canada YTD — same immutability contract as tax_rule_snapshot
        # above, for the before/after cumulative figures this payslip
        # actually consumed per component. None unless YTD accumulation
        # was actually wired for this calculation (result.
        # ytd_pensionable_earnings is None otherwise — see canada.py).
        # "_ytd_result" is NOT a PayslipItem column — callers that splat
        # this dict into PayslipItem(**values) MUST pop it first; it
        # carries the raw post-period values _upsert_ca_ytd_accumulator
        # needs, so the accumulator write and the frozen snapshot can
        # never disagree.
        "ytd_snapshot": (
            {
                "cpp": {"ytd_before": str(ctx.ytd_pensionable_earnings), "ytd_after": str(result.ytd_pensionable_earnings)},
                "cpp2": {"ytd_before": str(ctx.ytd_cpp2_pensionable_earnings), "ytd_after": str(result.ytd_cpp2_pensionable_earnings)},
                "ei": {"ytd_before": str(ctx.ytd_insurable_earnings), "ytd_after": str(result.ytd_insurable_earnings)},
                "cpp_basic_exemption": {"ytd_before": str(ctx.ytd_basic_exemption_used), "ytd_after": str(result.ytd_basic_exemption_used)},
            } if result.ytd_pensionable_earnings is not None else
            {
                "uk_director_ni_gross": {"ytd_before": str(ctx.ytd_director_ni_gross), "ytd_after": str(result.ytd_director_ni_gross)},
                "uk_director_ni_employee_paid": {"ytd_before": str(ctx.ytd_director_ni_employee_paid), "ytd_after": str(result.ytd_director_ni_employee_paid)},
                "uk_director_ni_employer_paid": {"ytd_before": str(ctx.ytd_director_ni_employer_paid), "ytd_after": str(result.ytd_director_ni_employer_paid)},
            } if result.ytd_director_ni_gross is not None else None
        ),
        "_ytd_result": result if result.ytd_pensionable_earnings is not None else None,
        # Same splat-then-pop contract as "_ytd_result" above, for UK
        # Directors NIC (ZP-TAX-UK-2026-27-001 §9.2) — a separate key
        # since it's gated on a different result field entirely.
        "_uk_director_ytd_result": result if result.ytd_director_ni_gross is not None else None,
        # "_org_levy_result" is NOT a PayslipItem column either — same
        # splat-then-pop contract as "_ytd_result" above. Carries this
        # employee's own period INCREMENT (after − before), not the
        # absolute after-total — _upsert_ca_org_levy_ytd() ADDS onto the
        # org's existing running total (it has no visibility into what
        # any other employee already contributed this year), so writing
        # the absolute after-total here would double-count the before
        # balance on every single payslip.
        "_org_levy_result": ({
            **({"on_eht": result.on_eht_ytd_remuneration_after - ctx.on_eht_ytd_remuneration_before}
               if result.on_eht_ytd_remuneration_after is not None else {}),
            **({"bc_eht": result.bc_eht_ytd_remuneration_after - ctx.bc_eht_ytd_remuneration_before}
               if result.bc_eht_ytd_remuneration_after is not None else {}),
            **({"mb_he_levy": result.mb_he_levy_ytd_remuneration_after - ctx.mb_he_levy_ytd_remuneration_before}
               if result.mb_he_levy_ytd_remuneration_after is not None else {}),
            **({"nl_hapset": result.nl_hapset_ytd_remuneration_after - ctx.nl_hapset_ytd_remuneration_before}
               if result.nl_hapset_ytd_remuneration_after is not None else {}),
            **({"qc_hsf": result.qc_hsf_ytd_remuneration_after - ctx.qc_hsf_ytd_remuneration_before}
               if result.qc_hsf_ytd_remuneration_after is not None else {}),
        } or None),
        # UK Apprenticeship Levy pay-bill increment + Employment
        # Allowance's employer_ni-total increment — (gross_increment,
        # employer_ni_increment) tuple, popped out and written via
        # _upsert_uk_org_levy_ytd separately (UK's own tax-year key
        # format, not _org_ytd_tax_year's calendar-year one) rather than
        # folded into "_org_levy_result", which only ever calls
        # _upsert_ca_org_levy_ytd.
        "_uk_org_levy_increment": (
            result.appr_levy_ytd_pay_bill_after - ctx.appr_levy_ytd_pay_bill_before
            if result.appr_levy_ytd_pay_bill_after is not None else None,
            result.employer_ni_ytd_after - ctx.employer_ni_ytd_before
            if result.employer_ni_ytd_after is not None else None,
        ),
        # ZP-TAX-CA-2026-001 CA-D03/AC-07: persist the POE reason code
        # into the calculation snapshot instead of discarding it (see
        # _resolve_country_aware_state). Passed straight through from the
        # caller, since resolving it is a service.py/DB-layer concern,
        # not something this DB-free calculation function should redo.
        "poe_snapshot": poe_snapshot,
    }


def _generate_single_payslip(db: Session, run: PayrollRun, employee, rate_map, slabs, country: str,
                              calculation_mode: str = "standard", payslip_number: str = None,
                              attendance_records: List["PayrollAttendanceRecord"] = None,
                              allowance_components: list = None, resolved_pack=None,
                              state_rate_map: dict = None, state_slabs: list = None,
                              employer_tax_profiles: dict = None, reciprocity: dict = None,
                              locality_rate=None, ytd_inputs: dict = None, poe_snapshot: dict = None,
                              org_levy_inputs: dict = None) -> PayslipItem:
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
    see its docstring. `ytd_inputs`: same — Canada YTD state, pre-loaded
    by the caller (see _load_ca_ytd); this function is the one place that
    then WRITES the resulting post-period state back to
    PayrollYtdAccumulator, once the new PayslipItem has a real id.
    `org_levy_inputs`: same idea, one level up — pre-loaded org-wide
    running totals (see _load_ca_org_levy_ytd) for levies like Ontario
    EHT that band on the ORGANIZATION's aggregate remuneration rather
    than any single employee's. This function writes the post-period
    org total back via _upsert_ca_org_levy_ytd, same as the per-employee
    accumulator above.
    """
    values = _compute_payslip_values(
        db, run, employee, rate_map, slabs, country, calculation_mode,
        attendance_records=attendance_records, allowance_components=allowance_components,
        resolved_pack=resolved_pack, state_rate_map=state_rate_map, state_slabs=state_slabs,
        employer_tax_profiles=employer_tax_profiles, reciprocity=reciprocity,
        locality_rate=locality_rate, ytd_inputs=ytd_inputs, poe_snapshot=poe_snapshot,
        org_levy_inputs=org_levy_inputs,
    )
    ytd_result = values.pop("_ytd_result", None)
    uk_director_ytd_result = values.pop("_uk_director_ytd_result", None)
    org_levy_result = values.pop("_org_levy_result", None)
    uk_org_levy_increment = values.pop("_uk_org_levy_increment", None)

    item = PayslipItem(
        payroll_run_id=run.id,
        employee_id=employee.id,
        organization_id=run.organization_id,
        payslip_number=payslip_number,
        status=PayslipStatus.PENDING,
        **values,
    )
    db.add(item)
    if ytd_result is not None:
        db.flush()  # need item.id for last_updated_payslip_id
        work_state = getattr(employee, "work_state", None)
        _upsert_ca_ytd_accumulator(db, employee.id, run.pay_date, work_state, ytd_result, payslip_id=item.id)
    if uk_director_ytd_result is not None:
        db.flush()  # need item.id for last_updated_payslip_id
        _upsert_uk_director_ytd_accumulator(db, employee.id, run.pay_date, uk_director_ytd_result, payslip_id=item.id)
    if org_levy_result is not None:
        db.flush()  # need item.id for last_updated_payslip_id
        _upsert_ca_org_levy_ytd(db, run.organization_id, run.pay_date, org_levy_result, payslip_id=item.id)
    uk_gross_increment, uk_employer_ni_increment = uk_org_levy_increment or (None, None)
    if uk_gross_increment is not None or uk_employer_ni_increment is not None:
        db.flush()  # need item.id for last_updated_payslip_id
        _upsert_uk_org_levy_ytd(db, run.organization_id, run.pay_date, uk_gross_increment, uk_employer_ni_increment, payslip_id=item.id)
    return item


def _recompute_run_aggregates(db: Session, run: PayrollRun):
    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).all()
    run.employee_count = len(items)
    run.total_gross = sum((i.gross_pay for i in items), Decimal("0"))
    run.total_deductions = sum((i.total_deductions for i in items), Decimal("0"))
    run.total_taxes = sum((i.tds for i in items), Decimal("0"))
    run.total_employer_contribution = sum(
        (i.employer_pf + i.employer_esi + i.employer_social_security + i.employer_medicare + i.employer_pension
         + i.employer_ni + i.employer_futa + i.employer_sui + i.employer_state_program_contributions
         + i.employer_cpp2 + i.employer_eht
         + i.employer_bc_eht + i.employer_mb_he_levy + i.employer_nl_hapset
         + i.employer_qc_hsf + i.employer_qc_labour_standards
         # India EDLI/NPS: genuinely separate employer-only liabilities,
         # added here. employer_eps/employer_pf_residual are deliberately
         # NOT added — they're an informational breakdown of employer_pf
         # above, already counted once; summing them too would double-count.
         + i.employer_edli + (i.employer_nps or Decimal("0")) + i.employer_lwf + i.employer_apprenticeship_levy for i in items),
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
    state_slabs, employer_tax_profiles, reciprocity, locality_rate,
    poe_reason, poe_result) — pack is the resolved canonical
    JurisdictionPack when one was used, else None (see
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
    resolution_state, poe_reason = _resolve_country_aware_state(country, employee, state, db=db, organization_id=organization_id)
    # No date in this cache key: safe because every caller creates `cache`
    # fresh and passes ONE constant payroll_date for the whole call's
    # lifetime (e.g. generate_payslips_for_run's calc_cache/run.pay_date) —
    # never multiple dates sharing one cache dict.
    cache_key = (country, resolution_state, tax_regime, filing_status)
    if cache is not None and cache_key in cache:
        rate_map, slabs, canonical_rates, pack, state_rate_map, state_slabs, employer_tax_profiles = cache[cache_key]
    else:
        rate_map, slabs, canonical_rates, pack = _resolve_effective_rate_inputs(
            db, organization_id, country, payroll_date, org_opted_in, state=resolution_state, tax_regime=tax_regime,
            filing_status=filing_status,
        )
        state_rate_map, state_slabs = get_state_scoped_config(db, country, resolution_state, as_of=payroll_date, filing_status=filing_status)
        # US/CA-specific (jurisdiction_id stays None, so get_employer_tax_profiles
        # is a no-op, for every other country): tenant-specific SUI/workers'-
        # comp/etc. rates, resolved by (org, "US-<state>"/"CA-<province>")
        # rather than by pack/regime. CA-D06/AC-24: never a global-default
        # rate, only an employer-specific notice.
        # Phase 8U: Germany accident insurance (spec §14) reuses this SAME
        # agency-assigned-rate mechanism as US SUI — an employer's
        # Berufsgenossenschaft-issued risk-class rate is exactly the same
        # statutory shape (assigned by an agency, own account number, own
        # evidence trail) EmployerTaxProfile already models; jurisdiction_id
        # "DE" (no state) resolves it, component_code "DE_ACCIDENT_INSURANCE".
        jurisdiction_id = (
            f"{country}-{resolution_state}" if (country in ("US", "CA") and resolution_state)
            else "DE" if country == "DE"
            else None
        )
        employer_tax_profiles = get_employer_tax_profiles(db, organization_id, jurisdiction_id, as_of=payroll_date)
        # EI's reduced-employer-rate authorization (ZP-TAX-CA-2026-001
        # §11) is a FEDERAL-level fact, not provincial — looked up under
        # the bare country code so an org enters it once, not once per
        # province. Merged into the same employer_tax_profiles dict WCB
        # already uses (component codes never collide) rather than
        # adding a new PayrollContext field just for this.
        if country == "CA":
            employer_tax_profiles = {
                **get_employer_tax_profiles(db, organization_id, "CA", as_of=payroll_date),
                **employer_tax_profiles,
            }
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
    return country, rate_map, slabs, resolved_pack, state, state_rate_map, state_slabs, employer_tax_profiles, reciprocity, locality_rate, poe_reason, resolution_state


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
        country, rate_map, slabs, resolved_pack, _state, state_rate_map, state_slabs, employer_tax_profiles, reciprocity, locality_rate, poe_reason, poe_result = _resolve_employee_calc_inputs(
            db, organization_id, emp, cache=calc_cache,
            payroll_date=run.pay_date, org_opted_in=org_opted_in,
        )
        payslip_number = f"{base_payslip_code}{seq:05d}" if base_payslip_code else None
        ytd_inputs = (
            _load_ca_ytd(db, emp.id, run.pay_date, getattr(emp, "work_state", None))
            if country == "CA" else
            _load_uk_director_ytd(db, emp.id, run.pay_date)
            if country == "UK" else None
        )
        # ZP-TAX-CA-2026-001 CA-D03/AC-07: the POE reason code must be
        # persisted into the calculation snapshot, not just used to pick
        # a rate/slab pack and discarded (see _resolve_country_aware_state).
        poe_snapshot = (
            {"poe_result": poe_result, "poe_reason": poe_reason} if country == "CA" else None
        )
        # Ontario EHT / BC EHT / Manitoba HE Levy / NL HAPSET — see
        # _ca_org_levy_read_inputs's own docstring for the gating
        # rationale. Read fresh per employee (not cached) — the org's
        # running total changes with every prior same-jurisdiction
        # employee processed in this same sequential loop, exactly as
        # proven safe for the per-employee YTD accumulator's own
        # read-then-flush ordering.
        org_levy_inputs = (
            _ca_org_levy_read_inputs(db, organization_id, run.pay_date, getattr(emp, "work_state", None))
            if country == "CA" else
            _load_uk_org_levy_ytd(db, organization_id, run.pay_date)
            if country == "UK" else {}
        )
        _generate_single_payslip(
            db, run, emp, rate_map, slabs, country, calculation_mode, payslip_number=payslip_number,
            attendance_records=attendance_by_employee.get(emp.id, []),
            allowance_components=allowance_components, resolved_pack=resolved_pack,
            state_rate_map=state_rate_map, state_slabs=state_slabs, employer_tax_profiles=employer_tax_profiles,
            reciprocity=reciprocity, locality_rate=locality_rate, ytd_inputs=ytd_inputs, poe_snapshot=poe_snapshot,
            org_levy_inputs=org_levy_inputs or None,
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
    country, rate_map, slabs, resolved_pack, _state, state_rate_map, state_slabs, employer_tax_profiles, reciprocity, locality_rate, poe_reason, poe_result = _resolve_employee_calc_inputs(
        db, organization_id, employee, payroll_date=run.pay_date, org_opted_in=org_opted_in,
    )
    poe_snapshot = {"poe_result": poe_result, "poe_reason": poe_reason} if country == "CA" else None
    allowance_components = _resolve_allowance_components(db, organization_id)
    # Phase 8AS: capture the currently-ATTACHED Germany overtime premium
    # components BEFORE the recompute below. The recompute's
    # setattr(existing_item, "allowance_items", [...]) delete-orphans the
    # persisted overtime allowance line, so afterwards the components can no
    # longer be found by joining through that edge. Captured here, their
    # stored applied_*_delta remain the source of truth for re-applying the
    # exact financial impact after the engine pass.
    attached_ot = _attached_germany_overtime_components_for_item(db, existing_item.id, organization_id)

    # ZP-TAX-CA-2026-001 AC-32 — "historical replay after a statutory
    # update returns the same result using the original snapshot." A
    # correction recalculation must reproduce the ORIGINAL numbers even if
    # Super Admin has since edited/superseded the tax pack that produced
    # them, not silently pick up whatever rates are live today (the
    # pre-existing gap this closes — see _reconstruct_rate_map_and_slabs_
    # from_snapshot's own docstring). Only the country-level
    # rate_map/slabs are replayed this way; state_rate_map/state_slabs,
    # employer_tax_profiles, reciprocity and locality_rate are NOT yet
    # snapshotted anywhere and still re-resolve against current live
    # data — a disclosed, narrower gap than before this fix, not a new
    # one. Falls back to live resolution unchanged whenever no snapshot
    # exists to replay from (every payslip before canonical tracking, or
    # for an org never opted in).
    replaying_from_snapshot = False
    existing_tax_snapshot = getattr(existing_item, "tax_rule_snapshot", None)
    if existing_tax_snapshot:
        replay_rates, replay_slabs = _reconstruct_rate_map_and_slabs_from_snapshot(existing_tax_snapshot)
        if replay_rates or replay_slabs:
            rate_map = {_normalize_engine_component_key(r.component_key): r for r in replay_rates}
            slabs = replay_slabs
            replaying_from_snapshot = True

    # Canada YTD — this is a CORRECTION path, not initial generation: it
    # must NOT read the live accumulator and write a new post-period
    # state, because that would silently cascade into every LATER
    # payslip's own already-frozen ytd_snapshot for this employee/tax-year
    # (a real, separate piece of work — the retroactive-correction
    # cascade — intentionally not built here). Instead, recalculate using
    # THIS payslip's own frozen ytd_snapshot.*_before values (if it has
    # one), reproducing identical CPP/CPP2/EI figures when nothing else
    # about the employee/rates changed. Never write to
    # PayrollYtdAccumulator from this function.
    ytd_inputs = {}
    existing_snapshot = getattr(existing_item, "ytd_snapshot", None)
    if country == "CA" and existing_snapshot:
        component_to_field = {
            "cpp": "ytd_pensionable_earnings", "cpp2": "ytd_cpp2_pensionable_earnings",
            "ei": "ytd_insurable_earnings", "cpp_basic_exemption": "ytd_basic_exemption_used",
        }
        for component, field_name in component_to_field.items():
            before = (existing_snapshot.get(component) or {}).get("ytd_before")
            if before is not None:
                ytd_inputs[field_name] = Decimal(before)

    values = _compute_payslip_values(
        db, run, employee, rate_map, slabs, country, calculation_mode,
        allowance_components=allowance_components, resolved_pack=resolved_pack,
        state_rate_map=state_rate_map, state_slabs=state_slabs, employer_tax_profiles=employer_tax_profiles,
        reciprocity=reciprocity, locality_rate=locality_rate, ytd_inputs=ytd_inputs or None,
        poe_snapshot=poe_snapshot,
    )
    ytd_result = values.pop("_ytd_result", None)
    uk_director_ytd_result = values.pop("_uk_director_ytd_result", None)
    # org_levy_inputs is deliberately never passed above (see the Canada
    # YTD comment) — recalculation must not re-read/re-increment the org's
    # running total, so this always resolves to None (dormant EHT on
    # recalculation) and is popped purely to keep it off existing_item,
    # same as _ytd_result.
    values.pop("_org_levy_result", None)
    values.pop("_uk_org_levy_increment", None)
    if replaying_from_snapshot:
        # _compute_payslip_values always re-derives a tax_snapshot from
        # whatever rate_map/slabs it was given (see its own resolved_pack
        # handling) — since those ARE the replayed rows here, it would
        # reproduce an equivalent snapshot anyway, but this leaves
        # existing_item's own tax_policy_pack_id/tax_policy_version/
        # tax_rule_snapshot completely untouched rather than re-writing
        # them, so the original snapshot's provenance is never at risk of
        # drifting across repeated replays.
        values.pop("tax_policy_pack_id", None)
        values.pop("tax_policy_version", None)
        values.pop("tax_rule_snapshot", None)
    if (ytd_result is not None or uk_director_ytd_result is not None) and not existing_snapshot:
        # Recalculating with YTD wired for the first time on a payslip
        # that was originally generated without it (e.g. the rollout
        # switch flipped on between the original run and this
        # recalculation) — this genuinely differs from a same-input
        # reproduction, so surface it rather than silently accepting
        # whatever number comes out.
        logging.getLogger("zoiko").warning(
            "[ca-ytd-recalc] payslip %s recalculated with YTD accumulation now available but no prior "
            "ytd_snapshot to reproduce from — figures may differ from the original run.",
            existing_item.id,
        )
    for field, value in values.items():
        setattr(existing_item, field, value)
    existing_item.status = PayslipStatus.PENDING

    # Phase 8AT: force the ORM to actually execute the delete-orphan removal
    # of the old allowance_items (staged by the setattr above, not yet sent
    # to the DB — this Session is autoflush=False) BEFORE the reapply below
    # queries PayslipAllowanceItem. Without this flush, that query observes
    # pre-flush DB state, finds the OLD (soon-to-be-deleted) overtime
    # allowance row still present, and reuses/updates that same doomed row
    # instead of creating a fresh one — the row it points the component's
    # payslip_allowance_item_id at is then deleted anyway at the eventual
    # commit (the delete-orphan cascade wins over the later attribute
    # update), leaving the component's FK dangling at a deleted row and the
    # overtime allowance line silently missing from the payslip. Proven by
    # a real DB round-trip in test_germany_8at_financial_integrity_lifecycle.py
    # (a subsequent detach raised NotFoundException("PayslipAllowanceItem")
    # before this fix). Flushing here is safe for every country, not just
    # Germany: it only makes the already-queued delete/insert physically
    # happen earlier in the same transaction — no different data, no
    # different outcome for a payslip with nothing attached.
    db.flush()

    # Phase 8AS: the engine recompute above used `overtime = Decimal("0")`
    # and replaced the payslip's allowance_items/snapshot, so any Germany
    # overtime premium component that was ATTACHED before this recalculation
    # would otherwise be silently erased from the payslip figures while its
    # component row stays ATTACHED. Re-apply the exact stored deltas of the
    # pre-captured attached components to preserve net/gross/SI consistency
    # and the reproduction snapshot (no-op when there are none).
    _reapply_attached_germany_overtime_deltas(db, existing_item, organization_id, attached_ot, actor_id=actor_id)

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


# ── Employee Statutory Profile (effective-dated) ─────────────────────────
# Foundation for jurisdiction-specific, point-in-time-correct employee
# statutory facts — see models.EmployeeStatutoryProfile's docstring and
# docs/PHASE_2_EMPLOYEE_STATUTORY_PROFILE.md. This table is a history, never
# updated in place: the only write operation is "append a new version"
# (create_employee_statutory_profile_version) — there is no update/delete.

_STATUTORY_PROFILE_DE_TAX_CLASSES = {"I", "II", "III", "IV", "V", "VI"}
_STATUTORY_PROFILE_DE_HEALTH_STATUSES = {"PUBLIC", "PRIVATE"}
_STATUTORY_PROFILE_DE_EMPLOYMENT_CLASSES = {"REGULAR", "MINIJOB", "MIDIJOB"}
_STATUTORY_PROFILE_DE_ELSTAM_SOURCES = {"ELSTAM", "FALLBACK_CERTIFICATE"}


def _validate_statutory_profile_fields(country_code: str, data: EmployeeStatutoryProfileCreate) -> None:
    """Field-level validation, independent of DB state. Every Germany check
    here maps to a named spec requirement (ZP-TAX-DE-2026-001) — see
    PHASE_2_EMPLOYEE_STATUTORY_PROFILE.md §12 for the citation."""
    errors = []

    if data.effective_to is not None and data.effective_to < data.effective_from:
        errors.append("effective_to must not be before effective_from.")

    if country_code == "DE":
        if data.de_tax_class is not None and data.de_tax_class not in _STATUTORY_PROFILE_DE_TAX_CLASSES:
            errors.append(f"de_tax_class must be one of {sorted(_STATUTORY_PROFILE_DE_TAX_CLASSES)}.")
        if data.de_factor is not None:
            # Spec §22 boundary test: "ELStAM factor with non-class-IV tax
            # class: reject before PAP invocation."
            if data.de_tax_class != "IV":
                errors.append("de_factor may only be set when de_tax_class is 'IV' (factor method, spec §6).")
            elif not (Decimal("0") < data.de_factor <= Decimal("1")):
                errors.append("de_factor must be greater than 0 and at most 1.")
        if data.de_child_count is not None and data.de_child_count < 0:
            errors.append("de_child_count must not be negative.")
        if data.de_health_insurance_status is not None and data.de_health_insurance_status not in _STATUTORY_PROFILE_DE_HEALTH_STATUSES:
            errors.append(f"de_health_insurance_status must be one of {sorted(_STATUTORY_PROFILE_DE_HEALTH_STATUSES)}.")
        if data.de_employment_classification is not None and data.de_employment_classification not in _STATUTORY_PROFILE_DE_EMPLOYMENT_CLASSES:
            errors.append(f"de_employment_classification must be one of {sorted(_STATUTORY_PROFILE_DE_EMPLOYMENT_CLASSES)}.")
        if data.de_elstam_source is not None:
            if data.de_elstam_source not in _STATUTORY_PROFILE_DE_ELSTAM_SOURCES:
                errors.append(f"de_elstam_source must be one of {sorted(_STATUTORY_PROFILE_DE_ELSTAM_SOURCES)}.")
            # Spec §6 "Fallback certificate": "Store document evidence,
            # effective dates and reason."
            elif data.de_elstam_source == "FALLBACK_CERTIFICATE" and not data.de_elstam_fallback_reason:
                errors.append("de_elstam_fallback_reason is required when de_elstam_source is FALLBACK_CERTIFICATE.")
        # §20 Abs. 2a Satz 9 SGB IV (confirmed live, Phase 8L): an employee
        # engaged for vocational training is excluded from the
        # Übergangsbereich (Midijob) regardless of earnings — reject at
        # write time, same as the factor/class-IV pairing above, rather
        # than only at calculation time.
        if data.de_vocational_trainee and data.de_employment_classification == "MIDIJOB":
            errors.append(
                "de_employment_classification may not be 'MIDIJOB' when de_vocational_trainee is set — "
                "§20 Abs. 2a Satz 9 SGB IV excludes vocational trainees from the Übergangsbereich regardless of earnings."
            )

        # Phase 8N — ELStAM / employee-withholding-state completion.
        # de_zkf_override: spec §5/§6 — a genuine ZKF can be a half-integer
        # (split-custody discount), so this deliberately allows fractional
        # values (unlike de_child_count's plain Integer), but never negative.
        if data.de_zkf_override is not None and data.de_zkf_override < 0:
            errors.append("de_zkf_override must not be negative.")
        # JFREIB/LZZFREIB/JHINZU/LZZHINZU/PKPV/PKPVAGZ — spec §5: all are
        # amounts, never negative (an allowance/add-back/premium/subsidy of
        # less than zero has no statutory meaning).
        for field_name, label in (
            ("de_jfreib", "de_jfreib"), ("de_lzzfreib", "de_lzzfreib"),
            ("de_jhinzu", "de_jhinzu"), ("de_lzzhinzu", "de_lzzhinzu"),
            ("de_pkpv", "de_pkpv"), ("de_pkpvagz", "de_pkpvagz"),
        ):
            value = getattr(data, field_name)
            if value is not None and value < 0:
                errors.append(f"{label} must not be negative.")
        # de_elstam_import_reference/de_elstam_schema_version are provenance
        # metadata, only meaningful when de_elstam_source == "ELSTAM" (spec
        # §7) — not required (a manually-entered ELStAM-sourced row with no
        # structured-import provenance is still valid), but never accepted
        # alongside FALLBACK_CERTIFICATE, which has its own distinct
        # provenance field (de_elstam_fallback_reason).
        if data.de_elstam_source == "FALLBACK_CERTIFICATE" and (
            data.de_elstam_schema_version or data.de_elstam_import_reference
        ):
            errors.append(
                "de_elstam_schema_version/de_elstam_import_reference may not be set when "
                "de_elstam_source is FALLBACK_CERTIFICATE — use de_elstam_fallback_reason instead."
            )

        # Phase 8AB — overtime/premium Grundlohn source (spec-adjacent, §3b
        # EStG / §1 SvEV; ARCHITECTURE_D, Phase 8AA). This is a genuine RATE
        # (an hourly wage), not an allowance/add-back like de_jfreib et al.
        # above — a €0/hour or negative wage has no statutory meaning, so
        # this rejects both, mirroring de_factor's own "> 0" rate-validation
        # precedent above rather than the ">= 0" allowance precedent.
        # Missing (None) is always allowed — Phase 8AB only establishes the
        # source; nothing yet requires it to be present.
        if data.de_grundlohn_hourly is not None and data.de_grundlohn_hourly <= 0:
            errors.append("de_grundlohn_hourly must be greater than 0.")

    if errors:
        raise BadRequestException("; ".join(errors))


def _validate_statutory_profile_no_overlap(
    db: Session, employee_id: int, effective_from: date, effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    """Reject a new period that overlaps any OTHER existing period for this
    employee — the same "no two overlapping ranges" principle as
    JurisdictionPack's Active-pack conflict guard
    (set_jurisdiction_pack_status), applied here at every write since this
    table has no status/lifecycle gate of its own to hang the check on."""
    query = db.query(EmployeeStatutoryProfile).filter(EmployeeStatutoryProfile.employee_id == employee_id)
    if exclude_id is not None:
        query = query.filter(EmployeeStatutoryProfile.id != exclude_id)
    new_end = effective_to or date.max
    for existing in query.all():
        existing_end = existing.effective_to or date.max
        if effective_from <= existing_end and existing.effective_from <= new_end:
            raise BadRequestException(
                f"Period {effective_from} to {effective_to or 'open-ended'} overlaps existing statutory "
                f"profile record #{existing.id} ({existing.effective_from} to "
                f"{existing.effective_to or 'open-ended'}). Close or adjust that record first."
            )


def _attach_main_secondary_consistency_warning(row: Optional[EmployeeStatutoryProfile]) -> Optional[EmployeeStatutoryProfile]:
    """Phase 8AK: sets a TRANSIENT (never persisted — no such column
    exists on the model) attribute the response schema reads via
    from_attributes. Reuses germany_pap.core's own
    check_main_secondary_employment_consistency verbatim — the SAME
    advisory-only check the PAP execution trace already runs — so this
    warning is visible to Tax Ops at profile save/read time, not only
    buried inside a blocked PAP calculation trace. Only meaningful for
    Germany rows; a no-op (None) for every other country."""
    if row is not None and row.country_code == "DE":
        from app.modules.payroll.engine.germany_pap.core import check_main_secondary_employment_consistency

        row.main_secondary_consistency_warning = check_main_secondary_employment_consistency(
            tax_class=row.de_tax_class, is_main_employment=row.de_main_employment,
        )
    return row


def create_employee_statutory_profile_version(
    db: Session, employee_id: int, organization_id: int,
    data: EmployeeStatutoryProfileCreate, actor_id: Optional[int],
    auto_close_previous: bool = True,
) -> EmployeeStatutoryProfile:
    """Append a new effective-dated statutory-profile version. Never updates
    an existing row. When `auto_close_previous` (the default — and the only
    mode the API exposes) and an open-ended (effective_to IS NULL) row
    already exists with an earlier effective_from, it is closed the day
    before this version's effective_from — the "01 Jan Tax Class I, 01 Jul
    Tax Class III" case. A caller inserting an already-closed historical
    correction should pass auto_close_previous=False with an explicit
    effective_to; overlap is validated in both modes."""
    employee = get_employee_by_id(db, employee_id, organization_id)
    country_code = _normalize_country(data.country_code or employee.country_code)
    if country_code not in _STRATEGIES:
        raise BadRequestException(f"Unsupported jurisdiction country_code: {country_code!r}.")

    _validate_statutory_profile_fields(country_code, data)

    previous_open = (
        db.query(EmployeeStatutoryProfile)
        .filter(
            EmployeeStatutoryProfile.employee_id == employee_id,
            EmployeeStatutoryProfile.effective_to.is_(None),
        )
        .first()
    )
    closing_previous = bool(auto_close_previous and previous_open and previous_open.effective_from < data.effective_from)
    if closing_previous:
        previous_open.effective_to = data.effective_from - timedelta(days=1)

    _validate_statutory_profile_no_overlap(
        db, employee_id, data.effective_from, data.effective_to,
        exclude_id=previous_open.id if closing_previous else None,
    )

    row = EmployeeStatutoryProfile(
        employee_id=employee_id, organization_id=organization_id, country_code=country_code,
        effective_from=data.effective_from, effective_to=data.effective_to,
        created_by_id=actor_id, reason=data.reason,
        de_tax_class=data.de_tax_class, de_factor=data.de_factor,
        de_church_tax_liable=data.de_church_tax_liable, de_church_tax_land=data.de_church_tax_land,
        de_church_tax_denomination=data.de_church_tax_denomination,
        de_church_tax_municipality_postal_code=data.de_church_tax_municipality_postal_code,
        de_child_count=data.de_child_count, de_childless=data.de_childless, de_saxony=data.de_saxony,
        de_health_insurance_status=data.de_health_insurance_status, de_health_fund_code=data.de_health_fund_code,
        de_u1_tariff_id=data.de_u1_tariff_id,
        de_pension_insurance_exempt=data.de_pension_insurance_exempt,
        de_unemployment_insurance_exempt=data.de_unemployment_insurance_exempt,
        de_employment_classification=data.de_employment_classification,
        de_elstam_source=data.de_elstam_source, de_elstam_fallback_reason=data.de_elstam_fallback_reason,
        de_vocational_trainee=data.de_vocational_trainee,
        de_zkf_override=data.de_zkf_override,
        de_jfreib=data.de_jfreib, de_lzzfreib=data.de_lzzfreib,
        de_jhinzu=data.de_jhinzu, de_lzzhinzu=data.de_lzzhinzu,
        de_pkpv=data.de_pkpv, de_pkpvagz=data.de_pkpvagz,
        de_main_employment=data.de_main_employment,
        de_elstam_schema_version=data.de_elstam_schema_version,
        de_elstam_import_reference=data.de_elstam_import_reference,
        de_grundlohn_hourly=data.de_grundlohn_hourly,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="employee_statutory_profile", entity_id=row.id,
        old_value=None,
        new_value={
            "employee_id": employee_id, "country_code": country_code,
            "effective_from": str(data.effective_from),
            "effective_to": str(data.effective_to) if data.effective_to else None,
        },
        reason=data.reason,
    )
    return _attach_main_secondary_consistency_warning(row)


def list_employee_statutory_profile_history(db: Session, employee_id: int, organization_id: int) -> List[EmployeeStatutoryProfile]:
    get_employee_by_id(db, employee_id, organization_id)  # 404s + tenant-scopes
    rows = (
        db.query(EmployeeStatutoryProfile)
        .filter(EmployeeStatutoryProfile.employee_id == employee_id)
        .order_by(EmployeeStatutoryProfile.effective_from.desc())
        .all()
    )
    for row in rows:
        _attach_main_secondary_consistency_warning(row)
    return rows


def get_employee_statutory_profile_as_of(
    db: Session, employee_id: int, organization_id: int, as_of: Optional[date] = None,
) -> Optional[EmployeeStatutoryProfile]:
    """Tenant-scoped wrapper around resolve_employee_statutory_profile for
    the API layer — 404s if the employee itself doesn't exist/belong to
    this org, then returns None (not 404) if the employee simply has no
    statutory profile recorded for that date, which is a normal state, not
    an error. Attaches the Phase 8AK advisory consistency warning here
    (the API-facing wrapper), not inside resolve_employee_statutory_profile
    itself, which dozens of internal calculation code paths call and
    should not be touched for this purely cosmetic, API-response-only
    concern."""
    get_employee_by_id(db, employee_id, organization_id)
    return _attach_main_secondary_consistency_warning(
        resolve_employee_statutory_profile(db, employee_id, organization_id, as_of),
    )


def resolve_employee_statutory_profile(
    db: Session, employee_id: int, organization_id: Optional[int] = None, as_of: Optional[date] = None,
) -> Optional[EmployeeStatutoryProfile]:
    """Return the statutory-profile version applicable on `as_of` (defaults
    to today) — answers "what were this employee's statutory attributes on
    the exact payroll date being calculated," the question this whole table
    exists to answer. Returns None (never raises) if no profile has been
    recorded yet for this employee — a jurisdiction/employee with no
    profile behaves exactly as if this table didn't exist. Intended to be
    called by a future Germany calculation phase per-employee, the same way
    _resolve_effective_rate_inputs is called today for jurisdiction rates.
    `organization_id`, if given, additionally tenant-scopes the lookup."""
    as_of = as_of or date.today()
    query = db.query(EmployeeStatutoryProfile).filter(
        EmployeeStatutoryProfile.employee_id == employee_id,
        EmployeeStatutoryProfile.effective_from <= as_of,
        (EmployeeStatutoryProfile.effective_to.is_(None)) | (EmployeeStatutoryProfile.effective_to >= as_of),
    )
    if organization_id is not None:
        query = query.filter(EmployeeStatutoryProfile.organization_id == organization_id)
    return query.order_by(EmployeeStatutoryProfile.effective_from.desc()).first()


# ── Germany: overtime/shift-premium work record (Phase 8AC) ─────────────
# The "work performed" FACT layer of Phase 8AA's ARCHITECTURE_D design.
# Pure capture — no premium/tax/SI calculation anywhere in this section.
# ctx.overtime remains untouched; engine/countries/germany.py never calls
# any function here (confirmed by this phase's own source-inspection test).

_GERMANY_OVERTIME_ENTRY_SOURCES = {"ATTENDANCE_DERIVED", "MANUAL"}
_GERMANY_OVERTIME_APPROVAL_STATUSES = {"PENDING", "APPROVED", "REJECTED"}


def _validate_germany_overtime_work_record_fields(data: "GermanyOvertimeWorkRecordCreate") -> None:
    errors = []
    if data.entry_source not in _GERMANY_OVERTIME_ENTRY_SOURCES:
        errors.append(f"entry_source must be one of {sorted(_GERMANY_OVERTIME_ENTRY_SOURCES)}.")
    if data.end_datetime <= data.start_datetime:
        errors.append("end_datetime must be after start_datetime.")
    if data.hours is not None and data.hours <= 0:
        errors.append("hours must be greater than 0.")
    # entry_source <-> source_attendance_id must agree — this is the ONLY
    # cross-field rule this phase enforces; it is NOT a precedence rule
    # (Phase 8AA/8AB's own explicit "do not invent precedence" instruction
    # governs which of two independently-created records, if both exist for
    # the same employee/date, should win — this phase does not decide that).
    if data.entry_source == "ATTENDANCE_DERIVED" and data.source_attendance_id is None:
        errors.append("source_attendance_id is required when entry_source is ATTENDANCE_DERIVED.")
    if data.entry_source == "MANUAL" and data.source_attendance_id is not None:
        errors.append("source_attendance_id must not be set when entry_source is MANUAL.")
    if errors:
        raise BadRequestException("; ".join(errors))


def create_germany_overtime_work_record(
    db: Session, employee_id: int, organization_id: int,
    data: "GermanyOvertimeWorkRecordCreate", actor_id: Optional[int],
) -> GermanyOvertimeWorkRecord:
    """Record one raw work-time fact. Never computes a premium, tax, or
    SI amount — this table has no such columns (see its own model
    docstring). Germany-scoped only (Phase 8AA §17 — not prematurely
    globalized to other countries without evidence)."""
    employee = get_employee_by_id(db, employee_id, organization_id)
    if _normalize_country(employee.country_code) != "DE":
        raise BadRequestException("Germany overtime work records may only be recorded for DE employees.")

    _validate_germany_overtime_work_record_fields(data)

    if data.source_attendance_id is not None:
        attendance = (
            db.query(PayrollAttendanceRecord)
            .filter(
                PayrollAttendanceRecord.id == data.source_attendance_id,
                PayrollAttendanceRecord.employee_id == employee_id,
                PayrollAttendanceRecord.organization_id == organization_id,
            )
            .first()
        )
        if attendance is None:
            raise BadRequestException("source_attendance_id does not reference an attendance record for this employee.")
        existing = (
            db.query(GermanyOvertimeWorkRecord)
            .filter(GermanyOvertimeWorkRecord.source_attendance_id == data.source_attendance_id)
            .first()
        )
        if existing is not None:
            raise BadRequestException(
                f"Attendance record #{data.source_attendance_id} already has an overtime work record "
                f"(#{existing.id}) — duplicate prevention (Phase 8AA §14)."
            )

    row = GermanyOvertimeWorkRecord(
        organization_id=organization_id, employee_id=employee_id,
        source_attendance_id=data.source_attendance_id, work_date=data.work_date,
        start_datetime=data.start_datetime, end_datetime=data.end_datetime, hours=data.hours,
        entry_source=data.entry_source, hr_approval_status="PENDING", created_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_overtime_work_record", entity_id=row.id,
        old_value=None,
        new_value={
            "employee_id": employee_id, "work_date": str(data.work_date),
            "entry_source": data.entry_source, "hours": str(data.hours),
        },
    )

    # Phase 8AQ — never invents which source "wins"; only detects and
    # flags the ambiguity so it fails closed downstream. See
    # _recompute_germany_overtime_overlap_status's own docstring.
    _recompute_germany_overtime_overlap_status(db, employee_id, organization_id, actor_id)
    db.refresh(row)
    return row


def _recompute_germany_overtime_overlap_status(
    db: Session, employee_id: int, organization_id: int, actor_id: Optional[int],
) -> None:
    """Phase 8AQ, Objective B. Per this phase's own explicit instruction
    ("DO NOT invent precedence... implement a safe technical state that
    prevents ambiguous records from silently becoming payable"), this
    function NEVER decides which of two overlapping work records is
    correct — it only detects physical time overlap between NON-
    REJECTED records for one employee and marks every record in an
    overlapping group AMBIGUOUS_OVERLAP, regardless of entry_source
    (manual vs attendance-derived is irrelevant to whether two records
    physically overlap). A REJECTED record is excluded from overlap
    consideration entirely — HR explicitly rejecting one side of an
    overlap (via the existing set_germany_overtime_work_record_approval
    action, not a new invented mechanism) is the only way an ambiguity
    resolves, and it resolves purely as a side effect of removing one
    of the two records from consideration, never by this function
    picking a "winner."

    Recomputes fresh from scratch for every non-rejected record of this
    employee (rather than incrementally patching) — simpler to reason
    about and correct: a work record's ambiguity depends on the full set
    of its non-rejected siblings, which can change in either direction
    (an overlap can newly appear on create, or resolve when a sibling is
    rejected)."""
    # ALL of this employee's records (including REJECTED ones) must be
    # considered for the WRITE pass below — a just-rejected record's own
    # overlap_status must be cleared too (it is excluded from ambiguity
    # consideration entirely, so it cannot itself remain "ambiguous").
    # Only NON-REJECTED records participate in the actual overlap
    # comparison against each other.
    all_records = (
        db.query(GermanyOvertimeWorkRecord)
        .filter(
            GermanyOvertimeWorkRecord.employee_id == employee_id,
            GermanyOvertimeWorkRecord.organization_id == organization_id,
        )
        .all()
    )
    records = [r for r in all_records if r.hr_approval_status != "REJECTED"]
    ambiguous_ids = set()
    for i, a in enumerate(records):
        for b in records[i + 1:]:
            # Standard half-open interval overlap test.
            if a.start_datetime < b.end_datetime and b.start_datetime < a.end_datetime:
                ambiguous_ids.add(a.id)
                ambiguous_ids.add(b.id)

    changed = False
    for record in all_records:
        new_status = "AMBIGUOUS_OVERLAP" if record.id in ambiguous_ids else None
        if record.overlap_status != new_status:
            old_status = record.overlap_status
            record.overlap_status = new_status
            changed = True
            record_tax_audit(
                db, actor_id=actor_id, action="overlap_status_recompute",
                entity_type="germany_overtime_work_record", entity_id=record.id,
                old_value={"overlap_status": old_status}, new_value={"overlap_status": new_status},
            )
    if changed:
        db.commit()


def list_germany_overtime_work_records(
    db: Session, employee_id: int, organization_id: int,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
) -> List[GermanyOvertimeWorkRecord]:
    get_employee_by_id(db, employee_id, organization_id)  # 404s + tenant-scopes
    query = db.query(GermanyOvertimeWorkRecord).filter(
        GermanyOvertimeWorkRecord.employee_id == employee_id,
        GermanyOvertimeWorkRecord.organization_id == organization_id,
    )
    if date_from is not None:
        query = query.filter(GermanyOvertimeWorkRecord.work_date >= date_from)
    if date_to is not None:
        query = query.filter(GermanyOvertimeWorkRecord.work_date <= date_to)
    return query.order_by(GermanyOvertimeWorkRecord.work_date.desc()).all()


def get_germany_overtime_work_record_by_id(
    db: Session, record_id: int, organization_id: int,
) -> GermanyOvertimeWorkRecord:
    row = (
        db.query(GermanyOvertimeWorkRecord)
        .filter(GermanyOvertimeWorkRecord.id == record_id, GermanyOvertimeWorkRecord.organization_id == organization_id)
        .first()
    )
    if not row:
        raise NotFoundException("GermanyOvertimeWorkRecord", record_id)
    return row


def set_germany_overtime_work_record_approval(
    db: Session, record_id: int, organization_id: int, status: str, actor_id: Optional[int],
) -> GermanyOvertimeWorkRecord:
    """HR/manager sign-off that the recorded hours were legitimately
    worked — explicitly NOT a statutory classification/publication
    decision (Phase 8AA §25's own separation); no maker-checker distinct-
    approver requirement is imposed here, since this is an ordinary
    workflow approval, not a statutory-registry publish."""
    row = get_germany_overtime_work_record_by_id(db, record_id, organization_id)
    if status not in _GERMANY_OVERTIME_APPROVAL_STATUSES:
        raise BadRequestException(f"hr_approval_status must be one of {sorted(_GERMANY_OVERTIME_APPROVAL_STATUSES)}.")
    old_status = row.hr_approval_status
    row.hr_approval_status = status
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_overtime_work_record", entity_id=row.id,
        old_value={"hr_approval_status": old_status}, new_value={"hr_approval_status": status},
    )
    # Phase 8AQ: rejecting a record removes it from overlap consideration
    # entirely — this may resolve (never create) an ambiguity for its
    # former siblings. Recompute regardless of which way status changed,
    # since un-rejecting (PENDING/APPROVED after a prior REJECTED) can
    # equally re-introduce an overlap.
    _recompute_germany_overtime_overlap_status(db, row.employee_id, organization_id, actor_id)
    db.refresh(row)
    return row


# ── Germany: overtime time-window CLASSIFICATION (Phase 8AE) ────────────
# Statutory/calendar classification only — see
# engine/germany_overtime_classifier.py for the full algorithm and its own
# extensive STATUTORY FACT / ENGINEERING DESIGN / UNRESOLVED QUESTION
# documentation. No money is calculated by anything in this section.

def classify_and_list_germany_overtime_time_segments(
    db: Session, record_id: int, organization_id: int, actor_id: Optional[int] = None,
) -> List[GermanyOvertimeTimeSegment]:
    """Tenant-scoped: 404s if the work record doesn't belong to this org.
    Classifies (re-classifying replaces any prior segments for this work
    record — see the classifier module's own docstring for why that is
    safe) and returns the resulting segments.

    Phase 8AQ: fails closed with PRECEDENCE_REQUIRED when
    overlap_status == "AMBIGUOUS_OVERLAP" — this is the earliest point
    in the pipeline (before any money is computed) that can safely
    block an ambiguous record, matching every other "cannot proceed"
    gate in this module (missing Grundlohn, missing category, etc.).
    Reject the wrong sibling record via set_germany_overtime_work_record_approval
    (status="REJECTED") to resolve the ambiguity — this function never
    picks a winner itself."""
    from app.modules.payroll.engine.germany_overtime_classifier import (
        GermanyOvertimeClassificationError, classify_germany_overtime_work_record,
    )

    work_record = get_germany_overtime_work_record_by_id(db, record_id, organization_id)
    if work_record.overlap_status == "AMBIGUOUS_OVERLAP":
        raise BadRequestException(
            "PRECEDENCE_REQUIRED: this work record's time range overlaps another non-rejected "
            "overtime work record for the same employee, and source precedence (manual vs. "
            "attendance-derived) is not resolved. Reject the incorrect record via HR approval "
            "before classification can proceed — the system does not choose a source automatically."
        )
    try:
        return classify_germany_overtime_work_record(db, work_record, persist=True)
    except GermanyOvertimeClassificationError as exc:
        # Found during Phase 8AI's HTTP-contract test: this previously
        # propagated as a raw, unhandled 500 — the same data-state issue
        # (e.g. TIMEZONE_FOUNDATION_REQUIRED) every other fail-closed
        # Germany blocker in this file surfaces as a clean 4xx, not a
        # server crash.
        raise BadRequestException(f"{exc.code}: {exc.message}")


def list_germany_overtime_time_segments(
    db: Session, record_id: int, organization_id: int,
) -> List[GermanyOvertimeTimeSegment]:
    """Tenant-scoped read of whatever classification result (if any)
    already exists — does NOT (re)classify."""
    work_record = get_germany_overtime_work_record_by_id(db, record_id, organization_id)
    return (
        db.query(GermanyOvertimeTimeSegment)
        .filter(GermanyOvertimeTimeSegment.work_record_id == work_record.id)
        .order_by(GermanyOvertimeTimeSegment.segment_start)
        .all()
    )


# ── Germany overtime WAGE-TAX calculation (Phase 8AF) ────────────────────
# WAGE TAX ONLY — no social-insurance treatment anywhere in this section.
# Tenant-scoping happens here (via get_germany_overtime_work_record_by_id)
# BEFORE any calculation logic runs — proven by test.

def calculate_and_list_germany_overtime_wage_tax(
    db: Session, record_id: int, organization_id: int, actor_id: Optional[int] = None,
) -> List[GermanyOvertimeWageTaxResult]:
    from app.modules.payroll.engine.germany_overtime_wage_tax import (
        GermanyOvertimeNotClassifiedError, calculate_germany_overtime_wage_tax,
    )

    work_record = get_germany_overtime_work_record_by_id(db, record_id, organization_id)
    try:
        return calculate_germany_overtime_wage_tax(db, work_record, persist=True, actor_id=actor_id)
    except GermanyOvertimeNotClassifiedError as exc:
        # Phase 8AP fix: this sibling of classify_and_list_germany_overtime_time_segments()
        # never got that function's own Phase 8AI fix — calling wage-tax
        # calculation before classification previously propagated as a
        # raw, unhandled 500 instead of a clean 4xx.
        raise BadRequestException(f"{exc.code}: {exc.message}")


def list_germany_overtime_wage_tax_results(
    db: Session, record_id: int, organization_id: int,
) -> List[GermanyOvertimeWageTaxResult]:
    """Tenant-scoped read of whatever calculation result (if any) already
    exists — does NOT (re)calculate."""
    work_record = get_germany_overtime_work_record_by_id(db, record_id, organization_id)
    return (
        db.query(GermanyOvertimeWageTaxResult)
        .filter(GermanyOvertimeWageTaxResult.work_record_id == work_record.id)
        .order_by(GermanyOvertimeWageTaxResult.segment_start)
        .all()
    )


# ── Germany overtime SOCIAL-INSURANCE calculation (Phase 8AG) ───────────
# SOCIAL INSURANCE ONLY — completely independent of the wage-tax section
# above (no shared row, no shared cap resolution). Tenant-scoping happens
# here (via get_germany_overtime_work_record_by_id) BEFORE any
# calculation logic runs — proven by test.

def calculate_and_list_germany_overtime_social_insurance(
    db: Session, record_id: int, organization_id: int, actor_id: Optional[int] = None,
) -> List[GermanyOvertimeSocialInsuranceResult]:
    from app.modules.payroll.engine.germany_overtime_social_insurance import (
        GermanyOvertimeSINotClassifiedError, calculate_germany_overtime_social_insurance,
    )

    work_record = get_germany_overtime_work_record_by_id(db, record_id, organization_id)
    try:
        return calculate_germany_overtime_social_insurance(db, work_record, persist=True, actor_id=actor_id)
    except GermanyOvertimeSINotClassifiedError as exc:
        # Phase 8AP fix: same sibling gap as calculate_and_list_germany_overtime_wage_tax above.
        raise BadRequestException(f"{exc.code}: {exc.message}")


def list_germany_overtime_social_insurance_results(
    db: Session, record_id: int, organization_id: int,
) -> List[GermanyOvertimeSocialInsuranceResult]:
    """Tenant-scoped read of whatever calculation result (if any) already
    exists — does NOT (re)calculate."""
    work_record = get_germany_overtime_work_record_by_id(db, record_id, organization_id)
    return (
        db.query(GermanyOvertimeSocialInsuranceResult)
        .filter(GermanyOvertimeSocialInsuranceResult.work_record_id == work_record.id)
        .order_by(GermanyOvertimeSocialInsuranceResult.segment_start)
        .all()
    )


# ── Germany overtime PREMIUM COMPONENT (Phase 8AH) ──────────────────────
# Combines Phase 8AF (wage-tax) + Phase 8AG (social-insurance) results —
# see engine/germany_overtime_premium_component.py's own module docstring
# for the full combination/reconciliation design. Building/rebuilding a
# component NEVER touches an already-attached one (payslip_allowance_item_id
# IS NOT NULL) — those are frozen once attached, matching every other
# "finalized" row's immutability guarantee in this codebase
# (tax_rule_snapshot/germany_calculation_snapshot on PayslipItem itself).

def build_germany_overtime_premium_components(
    db: Session, record_id: int, organization_id: int, actor_id: Optional[int] = None,
) -> List[GermanyOvertimePremiumComponent]:
    from app.modules.payroll.engine.germany_overtime_premium_component import (
        GermanyOvertimePremiumComponentNoResultsError, build_premium_component_groups,
    )

    work_record = get_germany_overtime_work_record_by_id(db, record_id, organization_id)
    try:
        groups = build_premium_component_groups(db, work_record)
    except GermanyOvertimePremiumComponentNoResultsError as exc:
        # Phase 8AP fix: same sibling gap as the wage-tax/SI calculation
        # functions above — calling this before either prior calculation
        # step previously propagated as a raw, unhandled 500.
        raise BadRequestException(f"{exc.code}: {exc.message}")

    # Never delete/rebuild a component that has EVER been attached — it
    # is frozen the moment it is first linked to a real payslip line
    # (Phase 8AH §22). Phase 8AQ extended this: a DETACHED component is
    # STILL frozen, not just an ATTACHED one — otherwise a rebuild after
    # a legitimate detach would silently delete-and-recreate the very
    # row whose detach history (detached_at/detached_by_id) this phase
    # exists to preserve, defeating the entire "no silent deletion of
    # payroll history" principle. Only a component that was NEVER
    # attached (attachment_status == "NEVER_ATTACHED") is still
    # considered a draft, safe to delete and recompute on rebuild.
    existing = (
        db.query(GermanyOvertimePremiumComponent)
        .filter(GermanyOvertimePremiumComponent.work_record_id == work_record.id)
        .all()
    )
    attached_ranges = {
        (row.segment_start, row.segment_end)
        for row in existing if row.attachment_status != "NEVER_ATTACHED"
    }
    rebuildable_ids = [row.id for row in existing if row.attachment_status == "NEVER_ATTACHED"]
    if rebuildable_ids:
        db.query(GermanyOvertimePremiumComponent).filter(
            GermanyOvertimePremiumComponent.id.in_(rebuildable_ids),
        ).delete()

    rows = []
    for group in groups:
        key = (group.segment_start, group.segment_end)
        if key in attached_ranges:
            continue  # frozen — leave the already-attached component untouched
        row = GermanyOvertimePremiumComponent(
            organization_id=work_record.organization_id, work_record_id=work_record.id,
            created_by_id=actor_id, **group.as_dict(),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)

    return (
        db.query(GermanyOvertimePremiumComponent)
        .filter(GermanyOvertimePremiumComponent.work_record_id == work_record.id)
        .order_by(GermanyOvertimePremiumComponent.segment_start)
        .all()
    )


def list_germany_overtime_premium_components(
    db: Session, record_id: int, organization_id: int,
) -> List[GermanyOvertimePremiumComponent]:
    """Tenant-scoped read of whatever components (if any) already exist —
    does NOT (re)build."""
    work_record = get_germany_overtime_work_record_by_id(db, record_id, organization_id)
    return (
        db.query(GermanyOvertimePremiumComponent)
        .filter(GermanyOvertimePremiumComponent.work_record_id == work_record.id)
        .order_by(GermanyOvertimePremiumComponent.segment_start)
        .all()
    )


def list_germany_overtime_premium_components_for_batch_attach(
    db: Session,
    organization_id: int,
    employee_id: Optional[int] = None,
    work_date_from: Optional[date] = None,
    work_date_to: Optional[date] = None,
    attachment_state: Optional[str] = None,
) -> List[GermanyOvertimePremiumComponent]:
    """Org-wide (optionally employee/date/attachment-state-filtered) browse
    query for the Phase 8AO batch-attach operator workflow — the frontend
    needs to see candidates ACROSS employees/work records in one screen,
    unlike list_germany_overtime_premium_components above (which is
    correctly scoped to one already-known work record). Read-only, never
    mutates eligibility, and NEVER a substitute for the real server-side
    validation _attach_one_germany_overtime_premium_component always
    re-runs on every actual attach — this is a convenience view only.

    attachment_state: "ATTACHED" | "DETACHED" | "UNATTACHED" | None (all,
    default). Phase 8AQ: "UNATTACHED" means eligible-to-attach — i.e.
    attachment_status "NEVER_ATTACHED" OR "DETACHED" — since a detached
    component is exactly as attachable as one that was never attached
    (see _attach_one_germany_overtime_premium_component's own claim
    logic). "DETACHED" alone is also selectable, for an operator who
    specifically wants to review what was undone.

    Each returned component carries two extra, non-persisted attributes —
    `employee_id`/`employee_name` — set below from the same join, so the
    cross-employee batch-attach screen can render who each row belongs
    to without a second round trip per row. These are plain Python
    attribute assignments (never flushed/committed), read via the
    dedicated GermanyOvertimePremiumComponentEligibleResponse schema's
    from_attributes serialization."""
    if employee_id is not None:
        get_employee_by_id(db, employee_id, organization_id)  # 404s + tenant-scopes

    query = (
        db.query(GermanyOvertimePremiumComponent, GermanyOvertimeWorkRecord.employee_id, PayrollEmployee.name)
        .join(
            GermanyOvertimeWorkRecord,
            GermanyOvertimePremiumComponent.work_record_id == GermanyOvertimeWorkRecord.id,
        )
        .join(PayrollEmployee, PayrollEmployee.id == GermanyOvertimeWorkRecord.employee_id)
        .filter(GermanyOvertimePremiumComponent.organization_id == organization_id)
    )
    if employee_id is not None:
        query = query.filter(GermanyOvertimeWorkRecord.employee_id == employee_id)
    if work_date_from is not None:
        query = query.filter(GermanyOvertimePremiumComponent.work_date_local >= work_date_from)
    if work_date_to is not None:
        query = query.filter(GermanyOvertimePremiumComponent.work_date_local <= work_date_to)
    if attachment_state == "ATTACHED":
        query = query.filter(GermanyOvertimePremiumComponent.attachment_status == "ATTACHED")
    elif attachment_state == "DETACHED":
        query = query.filter(GermanyOvertimePremiumComponent.attachment_status == "DETACHED")
    elif attachment_state == "UNATTACHED":
        query = query.filter(GermanyOvertimePremiumComponent.attachment_status != "ATTACHED")

    rows = query.order_by(
        GermanyOvertimeWorkRecord.employee_id, GermanyOvertimePremiumComponent.work_date_local,
        GermanyOvertimePremiumComponent.segment_start,
    ).all()

    components = []
    for component, emp_id, emp_name in rows:
        component.employee_id = emp_id
        component.employee_name = emp_name
        components.append(component)
    return components


def _germany_overtime_premium_component_trace_dict(component: GermanyOvertimePremiumComponent) -> dict:
    """JSON-safe trace for one component (Phase 8AH §15) — every value is
    a plain str/float/int/None, never a raw ORM instance/Decimal/datetime,
    so this can be embedded directly into PayslipItem.germany_calculation_snapshot."""
    def _n(value):
        return float(value) if value is not None else None

    return {
        "premiumComponentId": component.id,
        "workRecordId": component.work_record_id,
        "segmentStart": component.segment_start.isoformat() if component.segment_start else None,
        "segmentEnd": component.segment_end.isoformat() if component.segment_end else None,
        "workDateLocal": component.work_date_local.isoformat() if component.work_date_local else None,
        "qualifyingHours": _n(component.qualifying_hours),
        "wageTaxResultId": component.wage_tax_result_id,
        "socialInsuranceResultId": component.social_insurance_result_id,
        "combinationStatus": component.combination_status,
        "grossPremiumAmount": _n(component.gross_premium_amount),
        "wageTaxFreeAmount": _n(component.wage_tax_free_amount),
        "wageTaxableAmount": _n(component.wage_taxable_amount),
        "siExemptAmount": _n(component.si_exempt_amount),
        "siContributoryAmount": _n(component.si_contributory_amount),
        "attachmentStatus": component.attachment_status,
        "financialIntegrationStatus": component.financial_integration_status or None,
        "appliedGrossDelta": _n(component.applied_gross_delta),
        "appliedPfDelta": _n(component.applied_pf_delta),
        "appliedEsiDelta": _n(component.applied_esi_delta),
        "attachedAt": component.attached_at.isoformat() if component.attached_at else None,
    }


_OVERTIME_PREMIUM_ALLOWANCE_KEY = "germany_overtime_premium"


# ── Phase 8AR — overtime premium financial integration ───────────────────
# Phase 8AQ's forensic finding: attach/detach only touched
# PayslipAllowanceItem.amount and germany_calculation_snapshot —
# PayslipItem.gross_pay, PayslipItem.total_deductions, and
# PayslipItem.net_pay were never updated. This function computes the
# financial deltas that attach must apply and detach must reverse.

# Germany statutory SI branch rates for REGULAR employees (Phase 7 /
# ZP-TAX-DE-2026-001 §9) — the same values the engine reads from
# hardcoded_defaults.py for its own base-calculation. Using them here for
# the overtime-premium SI delta avoids requiring a second engine pass and
# keeps the integration self-contained. When a future engine phase
# computes full SI including overtime in the base calculation, these
# delta values will be subsumed into that pass.
from app.modules.payroll.hardcoded_defaults import (
    _DE_RV_EMPLOYEE_RATE, _DE_RV_EMPLOYER_RATE,
    _DE_ALV_EMPLOYEE_RATE, _DE_ALV_EMPLOYER_RATE,
    _DE_GKV_GENERAL_EMPLOYEE_RATE, _DE_GKV_GENERAL_EMPLOYER_RATE,
)  # noqa: E402


@dataclass
class _OvertimeFinancialDelta:
    """Computed financial impact of attaching one overtime premium
    component to a payslip. All amounts are in EUR, rounded to 2 decimals.

    wages_tax_delta: additional wage tax attributable to this premium.
        0 when PAP is not available (the accurate computation requires
        PAP's marginal-rate calculation — see status field). Stored on the
        component for future engine integration.
    employee_pf_delta: additional employee-side pension insurance (RV,
        Rentenversicherung) contribution on the SI-contributory portion
        of this premium — mapped onto PayslipItem.pf, matching the engine's
        own field reuse (employee_pf = RV).
    employee_esi_delta: additional employee-side SI contribution (ALV +
        GKV branches) on the SI-contributory portion — mapped onto
        PayslipItem.esi, matching the engine's own field reuse
        (employee_esi = ALV + GKV + PV). PV is excluded because it is
        configuration-dependent (standard/Saxony, childless surcharge).
    employer_si_delta: additional employer-side social insurance (RV + ALV
        + GKV contributions on the SI-contributory portion). Stored for
        audit; not yet applied to PayslipItem because employer-side
        contributions are informational only."""
    gross_delta: Decimal
    wage_tax_delta: Decimal
    employee_pf_delta: Decimal
    employee_esi_delta: Decimal
    employer_si_delta: Decimal
    status: str  # "COMPLETE" or "PARTIAL_WAGE_TAX_PENDING_PAP"


def _compute_overtime_financial_delta(
    component: GermanyOvertimePremiumComponent,
) -> _OvertimeFinancialDelta:
    """Compute the financial impact of attaching one Germany overtime
    premium component to a payslip line.

    The premium component carries five statutory dimensions (Phase 8AF/8AG):
        gross_premium_amount   — total payable overtime premium
        wage_tax_free_amount  — §3b EStG wage-tax-exempt portion
        wage_taxable_amount   — §3b EStG wage-tax-liable portion
        si_exempt_amount      — §1 SvEV SI-exempt portion
        si_contributory_amount — §1 SvEV SI-contributory portion

    This function computes:
        1. gross_delta = gross_premium_amount (the premium increases gross pay)
        2. SI employee-side delta split onto PayslipItem.pf (RV) and
           PayslipItem.esi (ALV + GKV) using statutory REGULAR-employee
           branch rates, applying each to its correct payslip field
           (matching the engine's employee_pf=Rentenversicherung /
           employee_esi=ALV+GKV+PV field reuse)
        3. Wage-tax delta on wage_taxable_amount — NOT COMPUTABLE without
           PAP (see status field); stored as 0 pending engine integration

    PV (Pflegeversicherung) is deliberately excluded from employee_esi_delta
    here: it depends on per-employee configuration (standard vs Saxony,
    childless surcharge) not available at this layer, so contributing its
    default would fabricate a figure. PV delta is deferred to the full
    engine pass.

    Ceiling interactions (the SI-contributory portion may push total monthly
    earnings above a branch ceiling) are intentionally NOT handled here:
    the base payslip's own SI already accounts for the regular salary;
    the overtime premium's additional SI is computed on the contributory
    portion at the general rates. A full engine pass that includes overtime
    in the base SI calculation would handle ceilings correctly — this
    delta-based approach is an approximation for the current architecture.

    When PAP becomes available, the engine will compute a single integrated
    wage-tax result for (regular salary + overtime premium), making this
    separate delta unnecessary. At that point, this function becomes a
    transitional compatibility layer."""
    gross = Decimal(str(component.gross_premium_amount or 0))
    si_contributory = Decimal(str(component.si_contributory_amount or 0))

    # Employee-side SI split onto the two payslip SI fields, using the
    # branch rates for REGULAR employees:
    #   employee_pf_delta  = RV (Rentenversicherung)
    #   employee_esi_delta = ALV (Arbeitslosenversicherung) + GKV general
    # PV is excluded (per-employee config-dependent — see docstring).
    employee_pf_delta = _round2(si_contributory * _DE_RV_EMPLOYEE_RATE / Decimal("100"))
    employee_esi_delta = _round2(
        si_contributory * (_DE_ALV_EMPLOYEE_RATE + _DE_GKV_GENERAL_EMPLOYEE_RATE) / Decimal("100")
    )
    employer_si = _round2(
        si_contributory * (_DE_RV_EMPLOYER_RATE + _DE_ALV_EMPLOYER_RATE + _DE_GKV_GENERAL_EMPLOYER_RATE) / Decimal("100")
    )

    # Wage-tax delta: requires PAP's marginal-rate computation on the
    # taxable amount. Without PAP, this is uncomputable — stored as 0
    # with an explicit PARTIAL status.
    wage_tax = Decimal("0")
    status = "PARTIAL_WAGE_TAX_PENDING_PAP"

    return _OvertimeFinancialDelta(
        gross_delta=gross,
        wage_tax_delta=wage_tax,
        employee_pf_delta=employee_pf_delta,
        employee_esi_delta=employee_esi_delta,
        employer_si_delta=employer_si,
        status=status,
    )


# ── Phase 8AN internal outcome classification (shared by the single-attach
# and batch-attach entry points below) ──────────────────────────────────
# attach_germany_overtime_premium_component_to_payslip() (single-attach)
# never catches these — they ARE NotFoundException/BadRequestException
# (subclasses), so its byte-identical public contract (existing tests'
# `pytest.raises(BadRequestException)`/`pytest.raises(NotFoundException)`)
# holds with zero wrapper logic. batch_attach_germany_overtime_premium_
# components_to_payslips (Phase 8AO) instead does an isinstance check, most
# specific subclass first, to classify each item into the structured
# attached/already_attached/rejected/invalid/failed result buckets its own
# brief requires, without duplicating any validation logic below.
class _OvertimeAttachAlreadyAttached(BadRequestException):
    """The component's payslip_allowance_item_id is already set — either
    seen at the initial check, or lost a concurrent claim race (see the
    atomic compare-and-swap in _claim_germany_overtime_premium_component
    below)."""


class _OvertimeAttachRejected(BadRequestException):
    """The referenced component/payslip pairing is structurally valid,
    but the component is not yet eligible to attach (not COMPLETE,
    underlying work record not APPROVED) or the target payroll run is
    already finalized (PAID/CLOSED)."""


def _claim_germany_overtime_premium_component(
    db: Session, component_id: int, organization_id: int, allowance_item_id: int, actor_id: Optional[int],
) -> bool:
    """Atomic compare-and-swap claim: flips attachment_status to
    "ATTACHED" only if it is not ALREADY "ATTACHED" (covers both
    "NEVER_ATTACHED" and, since Phase 8AQ, "DETACHED" — a detached
    component is exactly as claimable as a fresh one), in one UPDATE
    statement gated by a WHERE clause on that same column. Two
    concurrent callers racing to attach/re-attach the SAME component can
    never both succeed — the database serializes writes to the same
    row, so exactly one UPDATE affects a row (returns rowcount 1) and
    the other affects zero rows (rowcount 0), regardless of backend
    (SQLite or Postgres). Phase 8AQ: also clears detached_at/
    detached_by_id — those fields describe the CURRENT state's most
    recent detach, which no longer applies once re-attached (the full
    history of every past detach remains in the audit log, not in these
    fields — see the model's own docstring). Returns True iff THIS call
    won the claim."""
    result = (
        db.query(GermanyOvertimePremiumComponent)
        .filter(
            GermanyOvertimePremiumComponent.id == component_id,
            GermanyOvertimePremiumComponent.organization_id == organization_id,
            GermanyOvertimePremiumComponent.attachment_status != "ATTACHED",
        )
        .update(
            {
                "attachment_status": "ATTACHED",
                "payslip_allowance_item_id": allowance_item_id,
                "attached_at": datetime.utcnow(),
                "attached_by_id": actor_id,
                "detached_at": None,
                "detached_by_id": None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return result == 1


def _attach_one_germany_overtime_premium_component(
    db: Session, component_id: int, payslip_item_id: int, organization_id: int, actor_id: Optional[int] = None,
) -> GermanyOvertimePremiumComponent:
    """Shared validation + concurrency-safe claim + financial delta
    integration, used by BOTH the single-attach and batch-attach entry
    points below — one architecture, not two. Phase 8AR: this function
    now not only credits the gross_premium_amount to the PayslipAllowanceItem
    line but also computes and applies the financial deltas (gross_pay,
    SI employee deductions, net_pay) to the PayslipItem. Wage-tax delta
    is stored but set to 0 while PAP is BLOCKED_EXTERNAL — the status
    is PARTIAL_WAGE_TAX_PENDING_PAP, visible in the API response and
    the germany_calculation_snapshot trace, so an operator can tell the
    payslip is correct for SI but not yet for final wage tax.

    Raises the real NotFoundException/BadRequestException (or the
    BadRequestException subclasses _OvertimeAttachAlreadyAttached /
    _OvertimeAttachRejected above) — never an opaque internal type — so
    the single-attach wrapper needs zero re-raising logic, and the batch
    wrapper can still classify precisely via isinstance, most specific
    first."""
    component = (
        db.query(GermanyOvertimePremiumComponent)
        .filter(
            GermanyOvertimePremiumComponent.id == component_id,
            GermanyOvertimePremiumComponent.organization_id == organization_id,
        )
        .first()
    )
    if not component:
        raise NotFoundException("GermanyOvertimePremiumComponent", component_id)

    if component.attachment_status == "ATTACHED":
        raise _OvertimeAttachAlreadyAttached("This premium component is already attached to a payslip line.")
    if component.combination_status != "COMPLETE":
        raise _OvertimeAttachRejected(
            f"Only a COMPLETE premium component may be attached to a payslip (current status: "
            f"{component.combination_status!r})."
        )

    work_record = (
        db.query(GermanyOvertimeWorkRecord)
        .filter(
            GermanyOvertimeWorkRecord.id == component.work_record_id,
            GermanyOvertimeWorkRecord.organization_id == organization_id,
        )
        .first()
    )
    if not work_record:
        raise NotFoundException("GermanyOvertimeWorkRecord", component.work_record_id)
    if work_record.hr_approval_status != "APPROVED":
        raise _OvertimeAttachRejected(
            "The underlying GermanyOvertimeWorkRecord must have hr_approval_status=APPROVED before its "
            f"premium component may be attached to a payslip (current status: {work_record.hr_approval_status!r})."
        )

    payslip_item = (
        db.query(PayslipItem)
        .filter(PayslipItem.id == payslip_item_id, PayslipItem.organization_id == organization_id)
        .first()
    )
    if not payslip_item:
        raise NotFoundException("PayslipItem", payslip_item_id)
    if payslip_item.employee_id != work_record.employee_id:
        raise BadRequestException("This payslip does not belong to the same employee as the work record.")

    run = db.query(PayrollRun).filter(PayrollRun.id == payslip_item.payroll_run_id).first()
    if not run:
        raise NotFoundException("PayrollRun", payslip_item.payroll_run_id)
    if not (run.period_start <= component.work_date_local <= run.period_end):
        raise BadRequestException(
            f"The component's work date ({component.work_date_local}) falls outside this payslip's "
            f"payroll run period ({run.period_start} to {run.period_end})."
        )
    if run.status in (PayrollStatus.PAID, PayrollStatus.CLOSED):
        raise _OvertimeAttachRejected(
            f"Cannot attach a new premium component to a payslip whose payroll run is already "
            f"{run.status} — this would silently change a finalized/paid amount."
        )

    # Get-or-create the target allowance line BEFORE claiming the
    # component. Creating an empty (or reusing an existing) allowance
    # line moves no money — amount is only ever changed by the atomic
    # increment below, and only after this call has proven it own the
    # claim. This ordering is what makes the whole operation race-safe:
    # if the claim below loses the race, no amount is ever touched, so a
    # lost race can never double-count a component's money onto the
    # payslip (the exact failure mode Phase 8AO's brief calls out).
    allowance_item = (
        db.query(PayslipAllowanceItem)
        .filter(
            PayslipAllowanceItem.payslip_item_id == payslip_item.id,
            PayslipAllowanceItem.key == _OVERTIME_PREMIUM_ALLOWANCE_KEY,
        )
        .first()
    )
    if not allowance_item:
        allowance_item = PayslipAllowanceItem(
            payslip_item_id=payslip_item.id, key=_OVERTIME_PREMIUM_ALLOWANCE_KEY,
            label="Overtime/Shift Premium (Gross, DE)", amount=Decimal("0.00"),
        )
        db.add(allowance_item)
        try:
            db.commit()
        except IntegrityError:
            # Lost the create race to a concurrent attach targeting the
            # SAME payslip line (uq_payslip_allowance_item_key) — the
            # other caller's row is now the real one; fetch it.
            db.rollback()
            allowance_item = (
                db.query(PayslipAllowanceItem)
                .filter(
                    PayslipAllowanceItem.payslip_item_id == payslip_item.id,
                    PayslipAllowanceItem.key == _OVERTIME_PREMIUM_ALLOWANCE_KEY,
                )
                .first()
            )
        db.refresh(allowance_item)

    won_claim = _claim_germany_overtime_premium_component(
        db, component_id, organization_id, allowance_item.id, actor_id,
    )
    if not won_claim:
        # Someone else attached this exact component between our
        # eligibility check above and this claim — re-check is
        # deliberately not needed: any outcome other than "already
        # attached" would mean the row changed underneath us in some
        # other way, which the unique/claim semantics make impossible.
        raise _OvertimeAttachAlreadyAttached(
            "This premium component was attached by a concurrent request before this one completed."
        )

    # Won the claim — now, and only now, atomically credit the amount
    # AND compute + apply the financial deltas to PayslipItem.
    # Phase 8AR: the gross_premium_amount is credited to the allowance
    # line (unchanged from Phase 8AH) AND the financial deltas (gross,
    # SI employee/employer, wage tax if PAP available) are applied to
    # PayslipItem.gross_pay, PayslipItem.total_deductions,
    # PayslipItem.net_pay, and the component's own financial tracking
    # fields. This is the core Phase 8AR fix — Phase 8AQ's finding that
    # "attach does not update PayslipItem.gross_pay/net_pay".
    #
    # Phase 8BE: steps 1-4 below (allowance credit, PayslipItem update,
    # component financial-tracking update, and the snapshot append) are
    # now ONE atomic transaction (a single db.commit() at the end),
    # deliberately separate from the claim's own commit above. The claim
    # commits first and alone because ITS atomicity is what makes a lost
    # race safe (a loser never touches money — see the comment above);
    # once a caller has won the claim, though, a crash between two of
    # these four money-affecting steps used to leave the component
    # permanently stuck ATTACHED with only some of its financial effects
    # applied and no way to safely retry (a retry would immediately raise
    # _OvertimeAttachAlreadyAttached, since the claim already succeeded).
    # Combining them into one transaction means either all four land
    # together or none do — the only remaining partial state is "claimed,
    # nothing else applied yet", which is safely distinguishable (the
    # component's financial_integration_status/applied_*_delta fields
    # stay at their pre-attach defaults) rather than silently half-correct.

    # 1. Compute the financial delta for this component.
    fin_delta = _compute_overtime_financial_delta(component)

    # 2. Atomically credit the allowance line (unchanged from Phase 8AH).
    db.query(PayslipAllowanceItem).filter(PayslipAllowanceItem.id == allowance_item.id).update(
        {"amount": PayslipAllowanceItem.amount + Decimal(component.gross_premium_amount)},
        synchronize_session=False,
    )

    # 3. Apply the financial deltas to PayslipItem — atomically.
    # gross_pay increases by gross_delta; total_deductions increases by
    # the employee-side SI deltas (pf + esi) plus the wage-tax delta;
    # net_pay increases by the remainder (gross_delta - additional
    # employee deductions). The UPDATE is a single statement to avoid
    # read-modify-write races.
    employee_deduction_delta = fin_delta.employee_pf_delta + fin_delta.employee_esi_delta + fin_delta.wage_tax_delta
    net_delta = fin_delta.gross_delta - employee_deduction_delta
    payslip_update = {
        "gross_pay": PayslipItem.gross_pay + fin_delta.gross_delta,
        "total_deductions": PayslipItem.total_deductions + employee_deduction_delta,
        "net_pay": PayslipItem.net_pay + net_delta,
        # Employee-side SI split onto the two payslip SI fields, matching
        # the engine's field reuse (employee_pf=RV, employee_esi=ALV+GKV+PV).
        # PV is excluded from the esi delta (config-dependent — see the
        # _compute_overtime_financial_delta docstring), so the delta below
        # adds ALV+GKV to the base esi (which already includes base PV).
        "pf": PayslipItem.pf + fin_delta.employee_pf_delta,
        "esi": PayslipItem.esi + fin_delta.employee_esi_delta,
    }
    db.query(PayslipItem).filter(PayslipItem.id == payslip_item.id).update(
        payslip_update, synchronize_session=False,
    )

    # 4. Record the financial integration delta on the component itself
    # for audit and future engine integration. applied_gross_delta /
    # applied_pf_delta / applied_esi_delta hold the EXACT amounts applied
    # so detach can reverse precisely; wage-tax delta (currently 0 while
    # PAP is pending) is reflected in financial_integration_status and the
    # snapshot/audit trace (no dedicated column).
    db.query(GermanyOvertimePremiumComponent).filter(
        GermanyOvertimePremiumComponent.id == component.id,
    ).update(
        {
            "financial_integration_status": fin_delta.status,
            "applied_gross_delta": fin_delta.gross_delta,
            "applied_pf_delta": fin_delta.employee_pf_delta,
            "applied_esi_delta": fin_delta.employee_esi_delta,
        },
        synchronize_session=False,
    )

    db.refresh(component)
    db.refresh(payslip_item)

    snapshot = dict(payslip_item.germany_calculation_snapshot or {})
    existing_components = list(snapshot.get("overtime_premium_components") or [])
    trace_entry = _germany_overtime_premium_component_trace_dict(component)
    trace_entry["financialIntegration"] = {
        "status": fin_delta.status,
        "grossDelta": float(fin_delta.gross_delta),
        "wageTaxDelta": float(fin_delta.wage_tax_delta),
        "employeePfDelta": float(fin_delta.employee_pf_delta),
        "employeeEsiDelta": float(fin_delta.employee_esi_delta),
        "employerSiDelta": float(fin_delta.employer_si_delta),
    }
    existing_components.append(trace_entry)
    snapshot["overtime_premium_components"] = existing_components
    payslip_item.germany_calculation_snapshot = snapshot
    db.commit()

    record_tax_audit(
        db, actor_id=actor_id, action="attach_to_payslip", entity_type="germany_overtime_premium_component",
        entity_id=component.id,
        new_value={
            "payslip_item_id": payslip_item.id,
            "payslip_allowance_item_id": allowance_item.id,
            "financial_integration": {
                "status": fin_delta.status,
                "gross_delta": str(fin_delta.gross_delta),
                "wage_tax_delta": str(fin_delta.wage_tax_delta),
                "employee_pf_delta": str(fin_delta.employee_pf_delta),
                "employee_esi_delta": str(fin_delta.employee_esi_delta),
                "employer_si_delta": str(fin_delta.employer_si_delta),
            },
        },
    )
    db.refresh(component)
    return component


# ── Phase 8AQ / 8AR — detach / reversal ──────────────────────────────────
# Forensic finding Phase 8AQ: the attach path above never touched
# PayslipItem.gross_pay/net_pay — it ONLY ever creates/updates a
# PayslipAllowanceItem row and the germany_calculation_snapshot JSON.
# Phase 8AR FIX: attach now computes and applies financial deltas to
# PayslipItem.gross_pay/total_deductions/net_pay. Detach therefore
# reverses the stored delta values atomically (not recomputing — immune
# to registry changes), plus the PayslipAllowanceItem credit reversal.

class _OvertimeDetachNotAttached(BadRequestException):
    """The component is not currently ATTACHED — never attached, already
    detached, or lost a concurrent detach race (all three surface
    identically: "not attached", never a leak of which case it was)."""


class _OvertimeDetachRejected(BadRequestException):
    """Structurally attached, but detaching is blocked right now — the
    payslip's payroll run is already PAID/CLOSED (mirrors
    _OvertimeAttachRejected's own identical guard on attach)."""


def _detach_one_germany_overtime_premium_component(
    db: Session, component_id: int, organization_id: int, actor_id: Optional[int] = None,
) -> GermanyOvertimePremiumComponent:
    """Reverses attach. Phase 8AR: reverses not only the
    PayslipAllowanceItem credit but also the exact financial deltas
    (gross_pay, SI deductions, net_pay) that attach applied, using the
    STORED delta values on the component (never recomputed — immune to
    registry changes between attach and detach). PayslipItem fields are
    returned to their exact pre-attach state.

    NEVER deletes the component, NEVER nulls
    payslip_allowance_item_id/attached_at/attached_by_id — those remain
    a permanent record of "this was attached here, by whom, when" (Phase
    8AQ's own "no silent deletion of payroll history" principle). Only
    attachment_status/detached_at/detached_by_id change, plus the
    atomic reversal of the money this component contributed.

    Concurrency-safety is symmetric to the attach path: the STATUS claim
    (atomic compare-and-swap, gated on attachment_status == "ATTACHED")
    happens first; the money is reversed only AFTER winning that claim
    — so two concurrent detach attempts on the same component can never
    both succeed, and neither can double-decrement the allowance item.
    A component can only be detached from the SAME attach instance it
    is currently attached under — re-attaching (which clears
    detached_at/detached_by_id and re-sets payslip_allowance_item_id,
    possibly to a different payslip) always precedes any further
    detach, so this decrement is always undoing exactly the credit the
    most recent successful attach added, never a stale one."""
    component = (
        db.query(GermanyOvertimePremiumComponent)
        .filter(
            GermanyOvertimePremiumComponent.id == component_id,
            GermanyOvertimePremiumComponent.organization_id == organization_id,
        )
        .first()
    )
    if not component:
        raise NotFoundException("GermanyOvertimePremiumComponent", component_id)

    if component.attachment_status != "ATTACHED":
        raise _OvertimeDetachNotAttached(
            f"This premium component is not currently attached (status: {component.attachment_status!r})."
        )

    allowance_item = (
        db.query(PayslipAllowanceItem)
        .filter(PayslipAllowanceItem.id == component.payslip_allowance_item_id)
        .first()
    )
    if not allowance_item:
        raise NotFoundException("PayslipAllowanceItem", component.payslip_allowance_item_id)

    payslip_item = (
        db.query(PayslipItem)
        .filter(PayslipItem.id == allowance_item.payslip_item_id, PayslipItem.organization_id == organization_id)
        .first()
    )
    if not payslip_item:
        raise NotFoundException("PayslipItem", allowance_item.payslip_item_id)

    run = db.query(PayrollRun).filter(PayrollRun.id == payslip_item.payroll_run_id).first()
    if not run:
        raise NotFoundException("PayrollRun", payslip_item.payroll_run_id)
    if run.status in (PayrollStatus.PAID, PayrollStatus.CLOSED):
        raise _OvertimeDetachRejected(
            f"Cannot detach a premium component from a payslip whose payroll run is already "
            f"{run.status} — this would silently change a finalized/paid amount."
        )

    gross_amount = component.gross_premium_amount

    won_claim = (
        db.query(GermanyOvertimePremiumComponent)
        .filter(
            GermanyOvertimePremiumComponent.id == component_id,
            GermanyOvertimePremiumComponent.organization_id == organization_id,
            GermanyOvertimePremiumComponent.attachment_status == "ATTACHED",
        )
        .update(
            {
                "attachment_status": "DETACHED",
                "detached_at": datetime.utcnow(),
                "detached_by_id": actor_id,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if won_claim != 1:
        # Lost the race — a concurrent detach (or, impossible given the
        # guards above, some other mutation) won first.
        raise _OvertimeDetachNotAttached(
            "This premium component was detached by a concurrent request before this one completed."
        )

    # Won the claim — now, and only now, atomically reverse the credit
    # AND the financial deltas. Phase 8AR: detach must reverse the exact
    # financial impact that attach applied — Gross Pay, SI deductions,
    # Net Pay, and the component's financial tracking fields. The
    # applied_gross_delta/applied_pf_delta/applied_esi_delta on the
    # component record the EXACT amounts that were applied at attach
    # time, so detach uses THOSE values rather than recomputing (the
    # "original source-of-truth" approach from the prompt).
    #
    # Phase 8BE: steps 1-3 below are now ONE atomic transaction (a single
    # db.commit() at the end, alongside the snapshot update below),
    # mirroring the attach-path fix above and for the identical reason —
    # the STATUS claim already committed above is what makes a lost race
    # safe; once won, a crash between reversing the allowance credit,
    # reversing the PayslipItem deltas, and clearing the component's
    # tracking fields used to be able to leave the payslip in a torn state
    # with no safe retry (a retry would immediately raise
    # _OvertimeDetachNotAttached, since the claim already flipped the
    # status to DETACHED).

    # Read the stored deltas BEFORE reversing — these are the exact
    # amounts that were applied at attach time.
    stored_gross_delta = Decimal(str(component.applied_gross_delta or 0))
    stored_pf_delta = Decimal(str(component.applied_pf_delta or 0))
    stored_esi_delta = Decimal(str(component.applied_esi_delta or 0))
    # Wage-tax delta is NOT persisted in its own column (no such column in
    # the Phase 8AR migration) — it is 0 whenever the status is
    # PARTIAL_WAGE_TAX_PENDING_PAP (the only attach-time status today, since
    # PAP is BLOCKED_EXTERNAL). When a future engine pass stores a real
    # wage-tax delta, the reversal of it will be handled by that pass. The
    # older attached rows written by pre-8AR phases have NULL applied_*
    # columns, so all stored deltas default to 0 and detach reverses nothing
    # extra — exactly correct for those historical rows.
    stored_wage_tax_delta = Decimal("0")

    # 1. Reverse the allowance line credit (unchanged from Phase 8AQ).
    db.query(PayslipAllowanceItem).filter(PayslipAllowanceItem.id == allowance_item.id).update(
        {"amount": PayslipAllowanceItem.amount - Decimal(gross_amount)},
        synchronize_session=False,
    )

    # 2. Reverse the financial deltas on PayslipItem — atomically.
    net_delta = stored_gross_delta - stored_pf_delta - stored_esi_delta - stored_wage_tax_delta
    payslip_update = {
        "gross_pay": PayslipItem.gross_pay - stored_gross_delta,
        "total_deductions": PayslipItem.total_deductions - stored_pf_delta - stored_esi_delta - stored_wage_tax_delta,
        "net_pay": PayslipItem.net_pay - net_delta,
        # Reverse the employee-side SI split onto its two payslip fields.
        "pf": PayslipItem.pf - stored_pf_delta,
        "esi": PayslipItem.esi - stored_esi_delta,
    }
    db.query(PayslipItem).filter(PayslipItem.id == payslip_item.id).update(
        payslip_update, synchronize_session=False,
    )

    # 3. Clear the financial integration tracking on the component.
    db.query(GermanyOvertimePremiumComponent).filter(
        GermanyOvertimePremiumComponent.id == component.id,
    ).update(
        {
            "financial_integration_status": "REVERSED",
            "applied_gross_delta": None,
            "applied_pf_delta": None,
            "applied_esi_delta": None,
        },
        synchronize_session=False,
    )

    db.refresh(payslip_item)
    # A deep copy is required here (unlike the shallow dict()/list() copy
    # the attach path above uses when merely APPENDING a new entry): we
    # are MUTATING an entry that already exists inside the nested
    # structure, and a shallow copy's inner dicts are still the SAME
    # objects SQLAlchemy's change-tracking treats as the "old" value —
    # mutating them in place makes old and new compare equal, so the
    # UPDATE silently never happens. Found by this phase's own test.
    snapshot = copy.deepcopy(payslip_item.germany_calculation_snapshot or {})
    existing_components = snapshot.get("overtime_premium_components") or []
    for entry in existing_components:
        if entry.get("premiumComponentId") == component.id:
            # Marked, never removed — the snapshot must keep showing this
            # component was once attached here, exactly like the DB row.
            entry["detachedAt"] = datetime.utcnow().isoformat()
            # Phase 8AR: record the financial reversal in the snapshot.
            entry["financialIntegration"] = {
                "status": "REVERSED",
                "grossDelta": float(stored_gross_delta),
                "wageTaxDelta": float(stored_wage_tax_delta),
                "pfDelta": float(stored_pf_delta),
                "esiDelta": float(stored_esi_delta),
            }
    snapshot["overtime_premium_components"] = existing_components
    payslip_item.germany_calculation_snapshot = snapshot
    db.commit()

    record_tax_audit(
        db, actor_id=actor_id, action="detach_from_payslip", entity_type="germany_overtime_premium_component",
        entity_id=component.id,
        old_value={"payslip_item_id": payslip_item.id, "payslip_allowance_item_id": allowance_item.id},
        new_value={
            "attachment_status": "DETACHED",
            "financial_reversal": {
                "gross_delta": str(stored_gross_delta),
                "wage_tax_delta": str(stored_wage_tax_delta),
                "pf_delta": str(stored_pf_delta),
                "esi_delta": str(stored_esi_delta),
            },
        },
    )
    db.refresh(component)
    return component


# ── Phase 8AS — regression-recompute financial integrity ────────────────
# Forensic finding Phase 8AS: regenerate_employee_payslip (and only that
# path — full-run generation skips employees that already have a payslip)
# recomputes a payslip by overwriting the engine's values via setattr. Two
# silent financial breakages result when a Germany overtime premium is
# ATTACHED at the time of recompute:
#   1. PayslipItem.allowance_items is a `cascade="all, delete-orphan"`
#      relationship — the setattr of a fresh in-memory allowance list
#      delete-orphans the persisted overtime premium allowance line (the
#      credited amount) while the component keeps attachment_status=ATTACHED
#      and points (payslip_allowance_item_id) at a now-deleted row.
#   2. gross_pay/total_deductions/pf/esi/net_pay and
#      germany_calculation_snapshot are overwritten from the engine, which
#      hardcodes `overtime = Decimal("0")` — so the exact financial deltas
#      attach had applied are silently erased and the snapshot loses the
#      attached-component trace, while the component's applied_*_delta
#      columns still claim them applied.
# Phase 8AS FIX: after a successful engine recompute, re-apply EVERY still
# ATTACHED component's stored deltas (never recomputed — the same source of
# truth detach uses), re-establish their shared overtime allowance line,
# re-point each component's payslip_allowance_item_id at it, and re-merge
# each component's trace into the (now fresh) engine snapshot. This restores
# the RULE 9 invariant net_pay = gross_pay - total_deductions AND the
# net_pay/snapshot/allowance consistency exactly as attach had established it.

def _attached_germany_overtime_components_for_item(
    db: Session, payslip_item_id: int, organization_id: int,
) -> List[GermanyOvertimePremiumComponent]:
    """All Germany overtime premium components currently ATTACHED to a given
    payslip item. Linked through their payslip_allowance_item_id ->
    PayslipAllowanceItem.payslip_item_id edges (multiple components may roll
    up into the same allowance line).

    IMPORTANT: this join is only reliable while the allowance edge still
    exists. regenerate_employee_payslip therefore calls this BEFORE the
    engine recompute (whose setattr of fresh allowance_items delete-orphans
    the overtime line) and passes the captured components to
    _reapply_attached_germany_overtime_deltas — so the pre-captured
    component list (with its stored deltas) is re-applied from the component
    rows themselves, never from the (by-then-deleted) allowance line."""
    return (
        db.query(GermanyOvertimePremiumComponent)
        .join(PayslipAllowanceItem, GermanyOvertimePremiumComponent.payslip_allowance_item_id == PayslipAllowanceItem.id)
        .filter(
            PayslipAllowanceItem.payslip_item_id == payslip_item_id,
            GermanyOvertimePremiumComponent.organization_id == organization_id,
            GermanyOvertimePremiumComponent.attachment_status == "ATTACHED",
        )
        .all()
    )


class _OvertimeReapplyAllowanceItemConflict(BadRequestException):
    """A concurrent regenerate/reapply for the SAME payslip recreated the
    Germany overtime allowance line first (uq_payslip_allowance_item_key)
    — see _reapply_attached_germany_overtime_deltas's own docstring for
    the full account of why this is deliberately NOT retried."""


def _reapply_attached_germany_overtime_deltas(
    db: Session, payslip_item: PayslipItem, organization_id: int,
    attached: List[GermanyOvertimePremiumComponent], actor_id: Optional[int] = None,
) -> int:
    """After the engine recompute in regenerate_employee_payslip has reset a
    payslip to its base (zero-overtime) figures, re-apply the exact stored
    financial deltas of every still-ATTACHED Germany overtime premium
    component. `attached` MUST be the component list captured (via
    _attached_germany_overtime_components_for_item) BEFORE the recompute,
    because the recompute's setattr delete-orphans the allowance line the
    join depends on. Returns the number of components re-applied (0 =>
    no-op).

    Not called by full-run generation (which never touches an existing
    payslip) and never discovers components automatically — this only
    preserves what an explicit operator attach already established.

    Phase 8AV concurrency finding: the allowance-line get-or-create below
    can lose a race to a CONCURRENT direct/standalone call of this same
    function for the SAME payslip (proven by a true 2-connection SQLite
    test — test_get_or_create_overtime_allowance_item_race_two_connections
    isolates the underlying pattern). Two fix approaches were tried and
    REJECTED before landing on the one below, because each introduced a
    WORSE, real financial-integrity defect of its own — proven by the
    same true-concurrency tests, not merely reasoned about:
      (a) db.begin_nested() (SAVEPOINT): SQLAlchemy's Session requires a
          full Session.rollback() after ANY flush exception, even one
          raised inside a savepoint — and that rollback unconditionally
          discards the OUTER transaction's own earlier pending work
          (regenerate_employee_payslip's own engine-recompute flush), not
          just this savepoint's own attempted insert.
      (b) Pre-resolving the allowance item BEFORE the engine recompute
          (so any conflict-recovery rollback would have nothing else
          pending to lose): the delete-orphan cascade from the engine
          recompute's own setattr ALWAYS destroys whatever row was
          pre-resolved anyway (it is linked into
          payslip_item.allowance_items, which the recompute reassigns),
          so the row still needs recreating AFTER that point regardless —
          and making that recreation a real `db.commit()` (needed for a
          safe conflict-rollback) splits what must remain ONE atomic
          financial transaction into two, reopening a window where a
          second concurrent call's own read-modify-write of
          payslip_item.gross_pay/net_pay (a PLAIN Python += on the
          in-memory attribute, not a SQL-level atomic increment) can
          observe the first call's ALREADY-COMMITTED delta as its own
          "base" and add the SAME delta again —
          test_multi_component_concurrent_regenerate_stays_coherent
          caught this for real (167.50 persisted where 133.75 was
          expected — a genuine double-application of one component's
          delta).
    Given both fixes are worse than the original defect, the safest
    correct behavior is: do NOT retry, do NOT swallow the conflict — let
    it fail fast and clearly (a typed, documented exception) so a losing
    concurrent call is rejected outright rather than corrupting financial
    state. This is a real, narrow, DISCLOSED limitation of calling this
    function directly/standalone concurrently for the SAME payslip — NOT
    of the actual production call path (regenerate_employee_payslip),
    which Phase 8AU's own true 2-connection test proved does not hit this
    window in practice (repeated runs, zero flakiness) because SQLite's
    own file-locking serializes the WHOLE function call well before this
    point is ever reached from two connections simultaneously. See the
    Phase 8AV report's own Defects Found / Remaining Gaps for the full
    account, including why PostgreSQL's finer-grained MVCC locking could
    behave differently in ways this environment cannot test."""
    attached = [c for c in attached if c.attachment_status == "ATTACHED"]
    if not attached:
        return 0

    # 1. Re-establish the shared overtime allowance line (the engine recompute
    #    delete-orphaned it). Its credited amount is the SUM of the attached
    #    components' gross premium amounts — exactly what a fresh set of
    #    attach calls would have produced.
    gross_total = sum(
        (Decimal(str(c.gross_premium_amount or 0)) for c in attached), Decimal("0"),
    )
    allowance_item = (
        db.query(PayslipAllowanceItem)
        .filter(
            PayslipAllowanceItem.payslip_item_id == payslip_item.id,
            PayslipAllowanceItem.key == _OVERTIME_PREMIUM_ALLOWANCE_KEY,
        )
        .first()
    )
    if not allowance_item:
        allowance_item = PayslipAllowanceItem(
            payslip_item_id=payslip_item.id, key=_OVERTIME_PREMIUM_ALLOWANCE_KEY,
            label="Overtime/Shift Premium (Gross, DE)", amount=Decimal("0.00"),
        )
        db.add(allowance_item)
        try:
            db.flush()
        except IntegrityError:
            # Deliberately NOT retried — see this function's own docstring
            # for why both a savepoint-based and a pre-resolution-based
            # retry were tried and rejected as each introducing a worse
            # defect. Fail fast and clearly instead.
            raise _OvertimeReapplyAllowanceItemConflict(
                "A concurrent regeneration/reapply already recreated this payslip's Germany overtime "
                "allowance line. Retry this operation."
            )
    allowance_item.amount = gross_total
    db.flush()

    # 2. Re-point each attached component's allowance edge at the restored line.
    for c in attached:
        if c.payslip_allowance_item_id != allowance_item.id:
            c.payslip_allowance_item_id = allowance_item.id

    # 3. Apply the SUM of stored deltas to the payslip fields (same Phase 8AR
    #    math: net = gross - pf - esi - wage_tax; wage_tax stored delta is 0
    #    while PAP is BLOCKED_EXTERNAL). applied_*_delta are the EXACT amounts
    #    recorded at each component's own attach time — never recomputed.
    gross_delta = sum((Decimal(str(c.applied_gross_delta or 0)) for c in attached), Decimal("0"))
    pf_delta = sum((Decimal(str(c.applied_pf_delta or 0)) for c in attached), Decimal("0"))
    esi_delta = sum((Decimal(str(c.applied_esi_delta or 0)) for c in attached), Decimal("0"))
    wage_tax_delta = Decimal("0")
    payslip_item.gross_pay = Decimal(str(payslip_item.gross_pay or 0)) + gross_delta
    payslip_item.pf = Decimal(str(payslip_item.pf or 0)) + pf_delta
    payslip_item.esi = Decimal(str(payslip_item.esi or 0)) + esi_delta
    payslip_item.total_deductions = Decimal(str(payslip_item.total_deductions or 0)) + pf_delta + esi_delta + wage_tax_delta
    payslip_item.net_pay = Decimal(str(payslip_item.net_pay or 0)) + gross_delta - pf_delta - esi_delta - wage_tax_delta

    # 4. Re-merge each attached component's trace into the fresh engine
    #    snapshot (the recompute replaced it), recreating the financial
    #    integration entries attach had written.
    snapshot = dict(payslip_item.germany_calculation_snapshot or {})
    existing_components = list(snapshot.get("overtime_premium_components") or [])
    known_ids = {entry.get("premiumComponentId") for entry in existing_components}
    for c in attached:
        if c.id in known_ids:
            continue
        trace_entry = _germany_overtime_premium_component_trace_dict(c)
        trace_entry["financialIntegration"] = {
            "status": c.financial_integration_status or "PARTIAL_WAGE_TAX_PENDING_PAP",
            "grossDelta": float(Decimal(str(c.applied_gross_delta or 0))),
            "wageTaxDelta": float(0.0),
            "employeePfDelta": float(Decimal(str(c.applied_pf_delta or 0))),
            "employeeEsiDelta": float(Decimal(str(c.applied_esi_delta or 0))),
        }
        existing_components.append(trace_entry)
        known_ids.add(c.id)
    snapshot["overtime_premium_components"] = existing_components
    payslip_item.germany_calculation_snapshot = snapshot

    # Phase 8AV: the audit row is written (flushed, not committed) BEFORE
    # the single commit below, so the financial state AND its audit record
    # land in the SAME atomic transaction — previously this function
    # committed the financial change first, then record_tax_audit's own
    # independent commit wrote the audit row as a SEPARATE durability
    # boundary, so a crash between the two could leave a real, already-
    # persisted financial change with no audit trail for it. auto_commit
    # is FALSE here specifically (this function's own commit below covers
    # it) — every other of record_tax_audit's 77 call sites is unaffected
    # (default auto_commit=True, unchanged behavior).
    record_tax_audit(
        db, actor_id=actor_id, action="reapply_attached_deltas_after_recompute",
        entity_type="payslip_item", entity_id=payslip_item.id,
        new_value={
            "reapplied_component_count": len(attached),
            "applied_gross_delta": str(gross_delta),
            "applied_pf_delta": str(pf_delta),
            "applied_esi_delta": str(esi_delta),
            "allowance_item_id": allowance_item.id,
        },
        auto_commit=False,
    )
    db.commit()
    return len(attached)


def detach_germany_overtime_premium_component_from_payslip(
    db: Session, component_id: int, organization_id: int, actor_id: Optional[int] = None,
) -> GermanyOvertimePremiumComponent:
    """Public, operator-initiated entry point — the exact inverse of
    attach_germany_overtime_premium_component_to_payslip below. Same
    call shape (component_id + organization_id + actor_id), no
    payslip_item_id needed (the component already knows where it's
    attached)."""
    return _detach_one_germany_overtime_premium_component(db, component_id, organization_id, actor_id)


def attach_germany_overtime_premium_component_to_payslip(
    db: Session, component_id: int, payslip_item_id: int, organization_id: int, actor_id: Optional[int] = None,
) -> GermanyOvertimePremiumComponent:
    """Explicit, operator-initiated action — the ONLY way a
    GermanyOvertimePremiumComponent's amount ever reaches a real payslip
    line. Never called automatically during payroll-run generation (Phase
    8AH's own disclosed scope boundary — see engine module docstring and
    docs/PHASE_8AH_..._REPORT.md §12 for why: automatic inclusion would
    require resolving the still-open manual-vs-attendance precedence and
    auto-inclusion-policy product decisions this project has repeatedly
    left open, most recently in Phase 8AC/8AF/8AG).

    Multiple components MAY roll up into the SAME PayslipAllowanceItem
    (one payslip can have more than one qualifying overtime day within
    its period) — each attach adds this component's own amount to that
    line's total exactly once, now via an atomic compare-and-swap claim
    (Phase 8AN) rather than a read-then-write application check, so a
    concurrent duplicate attach of the SAME component can never succeed
    twice or double-count its amount (see
    _attach_one_germany_overtime_premium_component's own docstring).

    Byte-identical public contract to every prior phase: raises
    NotFoundException for a missing/cross-tenant reference,
    BadRequestException for every ineligibility/already-attached/
    finalized-run case — this function is now a thin wrapper over the
    shared helper also used by batch_attach_germany_overtime_premium_
    components_to_payslips (Phase 8AO)."""
    return _attach_one_germany_overtime_premium_component(
        db, component_id, payslip_item_id, organization_id, actor_id,
    )


def batch_attach_germany_overtime_premium_components_to_payslips(
    db: Session,
    items: List[Tuple[int, int]],
    organization_id: int,
    actor_id: Optional[int] = None,
) -> Dict[str, list]:
    """Operator-initiated BATCH attach (Phase 8AO) — still explicit, still
    never automatic: the caller supplies an exact list of
    (component_id, payslip_item_id) pairs it wants attached (e.g. selected
    by a payroll operator reviewing eligible components in the UI), and
    every pair is independently re-validated server-side by the exact
    same rules as the single-attach path — this endpoint trusts nothing
    the frontend claims about eligibility.

    Returns a structured result with five buckets, per Phase 8AO §3:
    - attached: succeeded this call.
    - already_attached: the component was already attached (either
      before this call started, or lost a concurrent claim race to
      another request — both surface identically here, since from this
      caller's point of view the outcome is the same: not attached BY
      this call, but attached).
    - rejected: structurally valid pairing, but not yet eligible
      (component not COMPLETE, work record not APPROVED, or the target
      payroll run is already PAID/CLOSED).
    - invalid: a bad reference — missing/cross-tenant/cross-employee
      component or payslip, wrong payroll period, or a duplicate
      component_id appearing more than once within this SAME batch
      request (only the first occurrence is attempted; every repeat is
      invalid, never silently attempted twice within one call).
    - failed: an unexpected error while processing this one item. Each
      item is committed independently (this is NOT one all-or-nothing
      transaction across the whole batch) — one item's unexpected
      failure never blocks or rolls back any other item already
      attached in the same call. A DB error rolls back only that item's
      own uncommitted work before continuing to the next.

    Every item in every bucket carries componentId/payslipItemId plus a
    safe (non-internal) reason string; attached/already_attached also
    carry the resulting component payload."""
    attached: list = []
    already_attached: list = []
    rejected: list = []
    invalid: list = []
    failed: list = []
    seen_component_ids: set = set()

    for component_id, payslip_item_id in items:
        if component_id in seen_component_ids:
            invalid.append({
                "component_id": component_id, "payslip_item_id": payslip_item_id,
                "reason": "Duplicate component_id within this batch request; only its first occurrence was attempted.",
            })
            continue
        seen_component_ids.add(component_id)

        try:
            component = _attach_one_germany_overtime_premium_component(
                db, component_id, payslip_item_id, organization_id, actor_id,
            )
            attached.append({
                "component_id": component_id, "payslip_item_id": payslip_item_id,
                "reason": None, "component": component,
            })
        except _OvertimeAttachAlreadyAttached as exc:
            db.rollback()
            already_attached.append({
                "component_id": component_id, "payslip_item_id": payslip_item_id, "reason": str(exc),
            })
        except _OvertimeAttachRejected as exc:
            db.rollback()
            rejected.append({
                "component_id": component_id, "payslip_item_id": payslip_item_id, "reason": str(exc),
            })
        except (NotFoundException, BadRequestException) as exc:
            db.rollback()
            invalid.append({
                "component_id": component_id, "payslip_item_id": payslip_item_id, "reason": str(exc.message),
            })
        except Exception:
            db.rollback()
            failed.append({
                "component_id": component_id, "payslip_item_id": payslip_item_id,
                "reason": "An unexpected error occurred while attaching this component; it was not attached.",
            })

    # No separate batch-level audit row here: each successful attach
    # already writes its own record_tax_audit entry inside
    # _attach_one_germany_overtime_premium_component (entity_id = the
    # real component id) — a batch-level row would need a NULL
    # entity_id, which the audit table's schema deliberately disallows
    # (every audit row must point at one real entity). The structured
    # result below is itself the batch-level record for the caller.

    return {
        "attached": attached, "already_attached": already_attached,
        "rejected": rejected, "invalid": invalid, "failed": failed,
    }


# ── Germany ELStAM change-list / structured-import boundary (Phase 8N) ──
# Spec §6 "Change lists" / §7 (this phase's own Step 7/8). Neither function
# below calls ELSTER/BZSt or fabricates ELStAM content — both operate
# exclusively on caller-supplied structured data, exactly like every other
# write path in this module. See engine/germany_pap/elstam.py for the
# still-unimplemented (by design) LIVE connector boundary; this is the
# separate IMPORT/audit boundary for data someone has already obtained and
# validated by hand.

_ELSTAM_CHANGE_LIST_BATCH_VALID_STATUSES = {"RECEIVED", "VALIDATED", "APPLIED", "REJECTED"}
_ELSTAM_CHANGE_LIST_BATCH_ALLOWED_TRANSITIONS = {
    "RECEIVED": {"VALIDATED", "REJECTED"},
    "VALIDATED": {"APPLIED", "REJECTED"},
    "APPLIED": set(),
    "REJECTED": set(),
}


def create_elstam_change_list_batch(
    db: Session, organization_id: int, data: "GermanyElstamChangeListBatchCreate", actor_id: Optional[int] = None,
) -> GermanyElstamChangeListBatch:
    """Record that a monthly ELStAM change list was RECEIVED — metadata
    only (spec §6). Never fans out into per-employee attribute changes;
    those are recorded individually via import_elstam_structured_payload(),
    optionally citing this batch's id.

    Phase 8BE: idempotency guard. Resubmitting the same batch_reference
    for the same organization used to silently create a second, duplicate
    row (no dedup check existed on this path at all). The model's
    uq_germany_elstam_change_list_batch_org_ref constraint now makes that
    an IntegrityError, translated here into a clear, actionable
    BadRequestException — never a raw 500 — so a caller retrying a batch
    upload after a network timeout gets an unambiguous "already recorded"
    answer instead of a duplicate row."""
    row = GermanyElstamChangeListBatch(
        organization_id=organization_id,
        batch_reference=data.batch_reference, source=data.source or "MANUAL_UPLOAD",
        received_at=data.received_at, effective_date=data.effective_date,
        scope_description=data.scope_description,
        processing_status="RECEIVED", created_by_id=actor_id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BadRequestException(
            f"An ELStAM change-list batch with reference {data.batch_reference!r} has already been "
            "recorded for this organization. If this is a genuine resubmission, use a distinct "
            "batch_reference."
        )
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_elstam_change_list_batch", entity_id=row.id,
        old_value=None, new_value={"batch_reference": row.batch_reference, "effective_date": str(row.effective_date)},
    )
    return row


def list_elstam_change_list_batches(db: Session, organization_id: int) -> List[GermanyElstamChangeListBatch]:
    return (
        db.query(GermanyElstamChangeListBatch)
        .filter(GermanyElstamChangeListBatch.organization_id == organization_id)
        .order_by(GermanyElstamChangeListBatch.received_at.desc())
        .all()
    )


def get_elstam_change_list_batch(db: Session, batch_id: int, organization_id: int) -> GermanyElstamChangeListBatch:
    row = (
        db.query(GermanyElstamChangeListBatch)
        .filter(GermanyElstamChangeListBatch.id == batch_id, GermanyElstamChangeListBatch.organization_id == organization_id)
        .first()
    )
    if row is None:
        raise NotFoundException(f"ELStAM change-list batch {batch_id} not found.")
    return row


def set_elstam_change_list_batch_status(
    db: Session, batch_id: int, organization_id: int, data: "GermanyElstamChangeListBatchStatusUpdate",
    actor_id: Optional[int] = None,
) -> GermanyElstamChangeListBatch:
    """Advance a change-list batch's processing lifecycle. Never applies
    any attribute change itself — VALIDATED/APPLIED only record that a
    human has done that work elsewhere (via individual
    import_elstam_structured_payload calls); this function has no
    fan-out/bulk-apply behavior, matching spec's "do not fabricate
    change-list payloads" instruction."""
    row = get_elstam_change_list_batch(db, batch_id, organization_id)
    status = data.status
    if status not in _ELSTAM_CHANGE_LIST_BATCH_VALID_STATUSES:
        raise BadRequestException(f"Unknown ELStAM change-list batch status: {status!r}.")
    if status not in _ELSTAM_CHANGE_LIST_BATCH_ALLOWED_TRANSITIONS.get(row.processing_status, set()):
        raise BadRequestException(f"Cannot move an ELStAM change-list batch from {row.processing_status} to {status}.")

    old_status = row.processing_status
    row.processing_status = status
    if data.validation_result is not None:
        row.validation_result = data.validation_result
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_elstam_change_list_batch", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": status},
    )
    return row


def import_elstam_structured_payload(
    db: Session, employee_id: int, organization_id: int, *,
    schema_version: str, import_reference: Optional[str], change_list_batch_id: Optional[int],
    payload: EmployeeStatutoryProfileCreate, actor_id: Optional[int],
) -> GermanyElstamImportAttempt:
    """Phase 8N structured ELStAM import boundary (spec §7). `payload` is
    caller-supplied structured data (never a live ELSTER/BZSt fetch) —
    validated and written exactly like a normal statutory-profile write
    (create_employee_statutory_profile_version, reused as-is, not
    duplicated). The only new behavior is auditing the ATTEMPT itself:

    - on success: a GermanyElstamImportAttempt row is recorded APPLIED,
      pointing at the new EmployeeStatutoryProfile version.
    - on failure (BadRequestException — unsupported country, invalid
      field, overlapping period, etc.): a GermanyElstamImportAttempt row is
      recorded REJECTED with the validation error BEFORE re-raising — the
      one persisted trace of a rejected import, since a rejected write
      never reaches EmployeeStatutoryProfile at all. Never invents a
      passing result."""
    payload_dict = payload.model_dump(mode="json", by_alias=False)
    try:
        profile = create_employee_statutory_profile_version(db, employee_id, organization_id, payload, actor_id)
    except BadRequestException as exc:
        attempt = GermanyElstamImportAttempt(
            employee_id=employee_id, organization_id=organization_id,
            schema_version=schema_version, import_reference=import_reference,
            change_list_batch_id=change_list_batch_id, payload=payload_dict,
            validation_status="REJECTED", validation_errors={"message": str(exc)},
            created_by_id=actor_id,
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
        raise

    attempt = GermanyElstamImportAttempt(
        employee_id=employee_id, organization_id=organization_id,
        schema_version=schema_version, import_reference=import_reference,
        change_list_batch_id=change_list_batch_id, payload=payload_dict,
        validation_status="APPLIED", applied_statutory_profile_id=profile.id,
        created_by_id=actor_id,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_elstam_import_attempt", entity_id=attempt.id,
        old_value=None, new_value={"employee_id": employee_id, "applied_statutory_profile_id": profile.id},
    )
    return attempt


def list_elstam_import_attempts_for_employee(
    db: Session, employee_id: int, organization_id: int,
) -> List[GermanyElstamImportAttempt]:
    get_employee_by_id(db, employee_id, organization_id)  # 404s + tenant-scopes
    return (
        db.query(GermanyElstamImportAttempt)
        .filter(GermanyElstamImportAttempt.employee_id == employee_id, GermanyElstamImportAttempt.organization_id == organization_id)
        .order_by(GermanyElstamImportAttempt.imported_at.desc())
        .all()
    )


# ── Germany ELSTER transmission boundary (Phase 8BF) ─────────────────────
# See engine/germany_elster.py's own module docstring for the full
# fail-closed design. Nothing below ever calls a real ELSTER endpoint —
# these functions only prepare, validate, and record the deterministic
# BLOCKED_EXTERNAL outcome of attempting to resolve a transmitter. No
# certificate material is ever stored, read, or required to reach
# BLOCKED_EXTERNAL (see resolve_elster_transmitter's own docstring for why
# a "configured" certificate reference does not change this).

def get_elster_certificate_config(db: Session, organization_id: int) -> Optional[GermanyElsterCertificateConfig]:
    """Read-only. None means no config row has ever been created for this
    organization — callers should treat that identically to
    is_configured=False, never as an error."""
    return (
        db.query(GermanyElsterCertificateConfig)
        .filter(GermanyElsterCertificateConfig.organization_id == organization_id)
        .first()
    )


def set_elster_certificate_config(
    db: Session, organization_id: int, certificate_reference: str,
    reference_description: Optional[str], actor_id: Optional[int],
) -> GermanyElsterCertificateConfig:
    """Records ONLY a reference string (e.g. a key-vault path) — never
    accepts or stores certificate/key bytes. See model docstring."""
    if not certificate_reference or not certificate_reference.strip():
        raise BadRequestException("certificate_reference is required and must be a non-empty external reference.")
    row = get_elster_certificate_config(db, organization_id)
    old_value = {"isConfigured": row.is_configured} if row else None
    if row is None:
        row = GermanyElsterCertificateConfig(organization_id=organization_id)
        db.add(row)
    row.certificate_reference = certificate_reference.strip()
    row.reference_description = reference_description
    row.is_configured = True
    row.configured_by_id = actor_id
    row.configured_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="update", entity_type="germany_elster_certificate_config", entity_id=row.id,
        old_value=old_value, new_value={"isConfigured": True},
    )
    return row


_ELSTER_TRANSMISSION_VALID_STATUSES = {
    "DRAFT", "VALIDATED", "BLOCKED_EXTERNAL", "QUEUED", "TRANSMITTED", "ACKNOWLEDGED", "REJECTED",
}


def create_elster_transmission(
    db: Session, organization_id: int, data: "GermanyElsterTransmissionCreate", actor_id: Optional[int] = None,
) -> GermanyElsterTransmission:
    if data.period_end < data.period_start:
        raise BadRequestException("period_end must not be before period_start.")
    row = GermanyElsterTransmission(
        organization_id=organization_id, transmission_type=data.transmission_type,
        period_start=data.period_start, period_end=data.period_end,
        payload_summary=data.payload_summary or {}, status="DRAFT", created_by_id=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="create", entity_type="germany_elster_transmission", entity_id=row.id,
        old_value=None,
        new_value={"transmissionType": row.transmission_type, "periodStart": str(row.period_start), "periodEnd": str(row.period_end)},
    )
    return row


def list_elster_transmissions(db: Session, organization_id: int) -> List[GermanyElsterTransmission]:
    return (
        db.query(GermanyElsterTransmission)
        .filter(GermanyElsterTransmission.organization_id == organization_id)
        .order_by(GermanyElsterTransmission.period_start.desc())
        .all()
    )


def get_elster_transmission_by_id(db: Session, transmission_id: int, organization_id: int) -> GermanyElsterTransmission:
    row = (
        db.query(GermanyElsterTransmission)
        .filter(GermanyElsterTransmission.id == transmission_id, GermanyElsterTransmission.organization_id == organization_id)
        .first()
    )
    if not row:
        raise NotFoundException("GermanyElsterTransmission", transmission_id)
    return row


def validate_elster_transmission(db: Session, transmission_id: int, organization_id: int, actor_id: Optional[int] = None) -> GermanyElsterTransmission:
    """Structural validation ONLY (non-empty type, sane period, non-empty
    payload_summary) — never invents or checks a real ELSTER Datensatz
    schema (no such schema is specified anywhere in this codebase's
    documentation; see the Phase 8BF DEÜV/ELSTER gap-analysis notes)."""
    row = get_elster_transmission_by_id(db, transmission_id, organization_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"Only a DRAFT transmission can be validated (currently {row.status}).")
    errors = []
    if not row.transmission_type or not row.transmission_type.strip():
        errors.append("transmission_type must not be empty.")
    if row.period_end < row.period_start:
        errors.append("period_end must not be before period_start.")
    row.validation_errors = errors or None
    row.status = "REJECTED" if errors else "VALIDATED"
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_elster_transmission", entity_id=row.id,
        old_value={"status": "DRAFT"}, new_value={"status": row.status, "validationErrors": errors},
    )
    return row


def attempt_transmit_elster_transmission(db: Session, transmission_id: int, organization_id: int, actor_id: Optional[int] = None) -> GermanyElsterTransmission:
    """Attempts to resolve and use a real ElsterTransmitter. Today this
    ALWAYS lands on BLOCKED_EXTERNAL (see engine/germany_elster.py) —
    returned as a normal, successfully-recorded result (not an HTTP
    error), since being blocked on a missing external certificate is an
    expected, auditable state, not a caller mistake. Idempotent/retry-safe:
    calling this again on an already-BLOCKED_EXTERNAL row simply re-attempts
    and re-records the same deterministic outcome."""
    from app.modules.payroll.engine.germany_elster import (
        ElsterTransmissionRequest, GermanyElsterUnavailableError, resolve_elster_transmitter,
    )

    row = get_elster_transmission_by_id(db, transmission_id, organization_id)
    if row.status not in ("VALIDATED", "BLOCKED_EXTERNAL"):
        raise BadRequestException(
            f"Only a VALIDATED (or previously BLOCKED_EXTERNAL, for retry) transmission can be "
            f"transmitted (currently {row.status})."
        )
    cert_config = get_elster_certificate_config(db, organization_id)
    transmitter = resolve_elster_transmitter(cert_config)
    request = ElsterTransmissionRequest(
        organization_id=organization_id, transmission_type=row.transmission_type,
        period_start=row.period_start, period_end=row.period_end, payload_summary=row.payload_summary or {},
    )
    old_status = row.status
    try:
        transmitter.transmit(request)
    except GermanyElsterUnavailableError as exc:
        row.status = "BLOCKED_EXTERNAL"
        row.blocked_reason = exc.message
    db.commit()
    db.refresh(row)
    record_tax_audit(
        db, actor_id=actor_id, action="status_change", entity_type="germany_elster_transmission", entity_id=row.id,
        old_value={"status": old_status}, new_value={"status": row.status, "blockedReason": row.blocked_reason},
    )
    return row


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
    calculation's country resolution. Raises rather than silently assigning
    a new employee to India when the org itself has no jurisdiction
    configured anywhere yet — that assignment is permanent on the employee
    record and directly drives which jurisdiction's payroll rules apply."""
    if explicit_country_code:
        return _normalize_country(explicit_country_code)
    return _resolve_org_country(db, organization_id, required=True)


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


# ZP-TAX-CA-2026-001 AC-25: TD1/TD1X/provincial TD1/TP-1015.3/CPT30 data
# must be "schema-versioned and effective-dated" — a bare column
# overwrite has no history at all. update_employee below reuses
# record_tax_audit/TaxConfigurationAudit (entity_type=
# "payroll_employee_declaration") rather than inventing a new audit
# pattern, exactly as that table already tracks Super-Admin-owned
# canonical tax config changes.
def update_employee(db: Session, employee_id: int, data: EmployeeUpdate, organization_id: int, actor_id: Optional[int] = None) -> PayrollEmployee:
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

    # Snapshot old values BEFORE mutating, for the declaration-history
    # audit below — same "old_value from the row, not from `updates`"
    # care upsert_jurisdiction_pack already takes, for the same reason
    # (using the incoming value for both sides makes the diff meaningless).
    declaration_fields = (
        "td1_claim_amount", "provincial_td1_claim_amount", "qc_tp1015_claim_amount", "lsvcc_investment_amount",
    )
    old_declaration_values = {f: getattr(employee, f, None) for f in declaration_fields}

    for field, value in updates.items():
        if value == "":
            continue
        setattr(employee, field, value)
    db.commit()
    db.refresh(employee)

    for field in declaration_fields:
        old_value = old_declaration_values[field]
        new_value = getattr(employee, field, None)
        if old_value != new_value:
            record_tax_audit(
                db, actor_id=actor_id, action="update", entity_type="payroll_employee_declaration",
                entity_id=employee.id,
                old_value={field: str(old_value) if old_value is not None else None},
                new_value={field: str(new_value) if new_value is not None else None},
            )
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

    # Upfront jurisdiction-config guard — refuse to create the run row at
    # all if this org's country has opted into fail-fast validation and
    # isn't ready, rather than letting per-employee resolution inside
    # generate_payslips_for_run raise only after the run row already
    # exists (which would leave an orphaned empty Draft run behind).
    # Dormant while _VALIDATION_ENABLED_COUNTRIES is empty — a no-op for
    # every organization today. The per-employee check inside
    # _resolve_effective_rate_inputs remains the real backstop, since an
    # employee's own country_code override can differ from the org's.
    from app.modules.payroll.engine.countries.shared import (
        _VALIDATION_ENABLED_COUNTRIES, MissingComplianceConfigurationError,
    )
    org_country = _resolve_org_country(db, organization_id)
    if org_country and org_country in _VALIDATION_ENABLED_COUNTRIES:
        readiness = check_jurisdiction_readiness(db, organization_id, org_country)
        if not readiness["ready"]:
            bad_key = readiness["missingKeys"][0]["key"] if readiness["missingKeys"] else "tax slabs"
            raise MissingComplianceConfigurationError(bad_key, org_country, organization_id)

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
    # Phase 8AS: fail-closed — refuse to delete a payslip that has Germany
    # overtime premium components still ATTACHED. Deleting would silently
    # erase money the operator explicitly attached (the credited allowance
    # line and the applied gross/SI/net deltas) while the component rows
    # remain ATTACHED pointing at now-deleted rows. The operator must detach
    # premium components first (detach reverses the money and flips them to
    # DETACHED), then delete the payslip — mirroring the same "never silently
    # destroy an attached financial fact" discipline every attach/detach
    # guard in this module enforces.
    attached_ot = _attached_germany_overtime_components_for_item(db, item.id, organization_id)
    if attached_ot:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            detail=(
                "Cannot delete this payslip: it has Germany overtime premium components "
                "still attached. Detach them first (this reverses their money), then delete."
            ),
        )
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
    resolution_state, poe_reason = _resolve_country_aware_state(country, employee, work_state, db=db, organization_id=organization_id)
    poe_snapshot = {"poe_result": resolution_state, "poe_reason": poe_reason} if country == "CA" else None
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
    state_rate_map, state_slabs = get_state_scoped_config(
        db, country, resolution_state, as_of=run.pay_date, filing_status=getattr(employee, "w4_filing_status", None),
    )
    # Phase 8U: Germany accident insurance (spec §14) reuses this SAME
    # agency-assigned-rate mechanism as US SUI — an employer's
    # Berufsgenossenschaft-issued risk-class rate is exactly the same
    # statutory shape (assigned by an agency, own account number, own
    # evidence trail) EmployerTaxProfile already models; jurisdiction_id
    # "DE" (no state) resolves it, component_code "DE_ACCIDENT_INSURANCE".
    jurisdiction_id = (
        f"{country}-{resolution_state}" if (country in ("US", "CA") and resolution_state)
        else "DE" if country == "DE"
        else None
    )
    employer_tax_profiles = get_employer_tax_profiles(db, organization_id, jurisdiction_id, as_of=run.pay_date)
    # EI's reduced-employer-rate authorization — see the matching comment
    # in _resolve_employee_calc_inputs.
    if country == "CA":
        employer_tax_profiles = {
            **get_employer_tax_profiles(db, organization_id, "CA", as_of=run.pay_date),
            **employer_tax_profiles,
        }
    reciprocity = _resolve_us_reciprocity(db, employee, country, resolution_state, as_of=run.pay_date)
    locality_rate = (
        get_locality_rate(db, country, getattr(employee, "work_locality", None), as_of=run.pay_date)
        if country == "US" else None
    )

    calculation_mode = getattr(run, "calculation_mode", None) or _resolve_calculation_mode(db, organization_id)
    gross = data.basic_salary + (data.hra or 0) + (data.special_allowance or 0) + (data.overtime or 0)

    # Germany (Phase 8E): a manually-added payslip for a Germany employee must
    # consume the SAME effective-dated statutory inputs and fail-closed
    # behavior as a generated run — the same _resolve_germany_calc_inputs the
    # batch path (_compute_payslip_values) uses for DE. Without this, a manual
    # DE payslip would bypass statutory-profile/health-fund/ceiling/PV wiring
    # and could not be reproducibly snapshotted.
    germany_kwargs = {}
    if country == "DE":
        resolved_de = _resolve_germany_calc_inputs(db, organization_id, employee, run.pay_date)
        germany_kwargs = dict(
            germany_statutory_profile=resolved_de["statutory_profile"],
            germany_pap_asset=resolved_de["pap_asset"],
            germany_health_fund=resolved_de["health_fund"],
            germany_u1_tariff=resolved_de["u1_tariff"],
            germany_earning_taxability=resolved_de["earning_taxability"],
            germany_ceiling_gkv_pv=resolved_de["ceiling_gkv_pv"],
            germany_ceiling_rv_alv=resolved_de["ceiling_rv_alv"],
            germany_pv_configuration=resolved_de["pv_configuration"],
            germany_church_tax_exception=resolved_de["church_tax_exception"],
            germany_employee_id=employee.id,
            germany_organization_id=organization_id,
            germany_payroll_date=run.pay_date,
        )

    # Canada YTD — READ before calculating (see _load_ca_ytd's docstring);
    # this path DOES persist a real PayslipItem below, so it also WRITEs
    # the resulting post-period state back once the item has a real id
    # (the "manually add a payslip" path — easy to miss, and CPP/CPP2/EI
    # would silently regress to the old annualized-only behavior here even
    # after the run-generation path is fixed, if this weren't wired too).
    ytd_inputs = (
        _load_ca_ytd(db, employee.id, run.pay_date, work_state) if country == "CA"
        else _load_uk_director_ytd(db, employee.id, run.pay_date) if country == "UK"
        else {}
    )

    # Ontario EHT / BC EHT / Manitoba HE Levy / NL HAPSET org-level read —
    # same helper generate_payslips_for_run's loop uses (see its own
    # docstring): a manually-added payslip for one of these four
    # jurisdictions must consume the org's running total exactly like a
    # normal run would, or the levy would silently regress to 0 here.
    org_levy_inputs = (
        _ca_org_levy_read_inputs(db, organization_id, run.pay_date, work_state) if country == "CA"
        else _load_uk_org_levy_ytd(db, organization_id, run.pay_date) if country == "UK"
        else {}
    )

    # Delegate to the strategy engine (no attendance data for manual payslips)
    from app.modules.payroll.engine.resolver import calculate_payroll, build_context_from_employee
    from app.modules.payroll.engine.germany_pap.core import GermanyCalculationError
    from app.core.exceptions import GermanyCalculationBlockedException
    ctx = build_context_from_employee(
        employee, gross=gross, basic=data.basic_salary,
        hra=data.hra or Decimal("0"), special_allowance=data.special_allowance or Decimal("0"),
        overtime=data.overtime or Decimal("0"),
        unpaid_leave_days=0,
        country=country, rate_map=rate_map, slabs=slabs,
        work_state=work_state, state_rate_map=state_rate_map, state_slabs=state_slabs,
        employer_tax_profiles=employer_tax_profiles,
        locality_rate=locality_rate,
        pay_date=run.pay_date,
        **reciprocity,
        **germany_kwargs,
        **ytd_inputs,
        **org_levy_inputs,
    )
    try:
        calc = calculate_payroll(ctx, calculation_mode)
    except GermanyCalculationError as exc:
        # Same structured 400 the batch path returns — never fabricate a
        # Germany payslip when wage-tax execution is unavailable (§25).
        raise GermanyCalculationBlockedException(
            exc.code, exc.message, trace=(exc.trace.to_dict() if exc.trace else None),
        )

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
        employee_lwf=calc.employee_lwf,
        employer_lwf=calc.employer_lwf,
        social_security=calc.social_security,
        medicare=calc.medicare,
        ni_employee=calc.ni_employee,
        employee_pension=calc.employee_pension,
        # Canada: CPP2 — genuinely missing here before (computed and
        # deducted from net_pay correctly via total_employee_deductions,
        # but never actually written onto a manually-added payslip item,
        # so its own line always showed 0 despite reducing net pay).
        cpp2=calc.cpp2,
        cpp_base_amount=calc.cpp_base_amount,
        cpp_first_additional_amount=calc.cpp_first_additional_amount,
        tds=calc.tds,
        # US: broken-out federal/state/local tax — added alongside tds
        # above so a manually-added US payslip doesn't reintroduce the
        # same "totals right, detail columns silently zero" gap this field
        # split was specifically meant to close (see engine/countries/us.py).
        federal_income_tax=calc.federal_income_tax,
        state_income_tax=calc.state_income_tax,
        local_tax=calc.local_tax,
        state_disability_insurance=calc.state_disability_insurance,
        state_program_deductions=calc.state_program_deductions,
        total_deductions=calc.total_deductions,
        employer_pf=calc.employer_pf,
        employer_eps=calc.employer_eps,
        employer_pf_residual=calc.employer_pf_residual,
        employer_edli=calc.employer_edli,
        employer_nps=calc.employer_nps,
        employer_esi=calc.employer_esi,
        employer_social_security=calc.employer_social_security,
        employer_medicare=calc.employer_medicare,
        employer_pension=calc.employer_pension,
        employer_sui=calc.employer_sui,
        employer_state_program_contributions=calc.employer_state_program_contributions,
        employer_cpp2=calc.employer_cpp2,
        employer_cpp_base=calc.employer_cpp_base,
        employer_cpp_first_additional=calc.employer_cpp_first_additional,
        employer_eht=calc.employer_eht,
        employer_bc_eht=calc.employer_bc_eht,
        employer_mb_he_levy=calc.employer_mb_he_levy,
        employer_nl_hapset=calc.employer_nl_hapset,
        employer_qc_hsf=calc.employer_qc_hsf,
        employer_qc_labour_standards=calc.employer_qc_labour_standards,
        net_pay=calc.net_pay,
        unpaid_leave_days=calc.unpaid_leave_days,
        attendance_deduction=calc.attendance_deduction,
        per_day_salary=calc.per_day_salary,
        payable_days=Decimal(calc.payable_days),
        total_working_days=Decimal(calc.payroll_days),
        # Germany (Phase 7/8E) — frozen statutory provenance, same as the
        # batch path; None for every non-German manual payslip.
        employee_statutory_profile_id=calc.germany_statutory_profile_id,
        germany_calculation_snapshot=calc.germany_calculation_snapshot,
        status=PayslipStatus.PENDING,
        notes=data.notes,
        ytd_snapshot=(
            {
                "cpp": {"ytd_before": str(ctx.ytd_pensionable_earnings), "ytd_after": str(calc.ytd_pensionable_earnings)},
                "cpp2": {"ytd_before": str(ctx.ytd_cpp2_pensionable_earnings), "ytd_after": str(calc.ytd_cpp2_pensionable_earnings)},
                "ei": {"ytd_before": str(ctx.ytd_insurable_earnings), "ytd_after": str(calc.ytd_insurable_earnings)},
                "cpp_basic_exemption": {"ytd_before": str(ctx.ytd_basic_exemption_used), "ytd_after": str(calc.ytd_basic_exemption_used)},
            } if calc.ytd_pensionable_earnings is not None else None
        ),
        poe_snapshot=poe_snapshot,
    )
    db.add(item)
    if calc.ytd_pensionable_earnings is not None:
        db.flush()  # need item.id for last_updated_payslip_id
        _upsert_ca_ytd_accumulator(db, employee.id, run.pay_date, work_state, calc, payslip_id=item.id)
    if calc.ytd_director_ni_gross is not None:
        db.flush()  # need item.id for last_updated_payslip_id
        _upsert_uk_director_ytd_accumulator(db, employee.id, run.pay_date, calc, payslip_id=item.id)
    org_levy_increments = {
        **({"on_eht": calc.on_eht_ytd_remuneration_after - ctx.on_eht_ytd_remuneration_before}
           if calc.on_eht_ytd_remuneration_after is not None else {}),
        **({"bc_eht": calc.bc_eht_ytd_remuneration_after - ctx.bc_eht_ytd_remuneration_before}
           if calc.bc_eht_ytd_remuneration_after is not None else {}),
        **({"mb_he_levy": calc.mb_he_levy_ytd_remuneration_after - ctx.mb_he_levy_ytd_remuneration_before}
           if calc.mb_he_levy_ytd_remuneration_after is not None else {}),
        **({"nl_hapset": calc.nl_hapset_ytd_remuneration_after - ctx.nl_hapset_ytd_remuneration_before}
           if calc.nl_hapset_ytd_remuneration_after is not None else {}),
        **({"qc_hsf": calc.qc_hsf_ytd_remuneration_after - ctx.qc_hsf_ytd_remuneration_before}
           if calc.qc_hsf_ytd_remuneration_after is not None else {}),
    }
    if org_levy_increments:
        db.flush()  # need item.id for last_updated_payslip_id
        _upsert_ca_org_levy_ytd(db, organization_id, run.pay_date, org_levy_increments, payslip_id=item.id)
    if calc.appr_levy_ytd_pay_bill_after is not None or calc.employer_ni_ytd_after is not None:
        db.flush()  # need item.id for last_updated_payslip_id
        uk_levy_increment = (
            calc.appr_levy_ytd_pay_bill_after - ctx.appr_levy_ytd_pay_bill_before
            if calc.appr_levy_ytd_pay_bill_after is not None else None
        )
        uk_employer_ni_increment = (
            calc.employer_ni_ytd_after - ctx.employer_ni_ytd_before
            if calc.employer_ni_ytd_after is not None else None
        )
        _upsert_uk_org_levy_ytd(db, organization_id, run.pay_date, uk_levy_increment, uk_employer_ni_increment, payslip_id=item.id)
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


def _build_bank_export_rows(db: Session, run: PayrollRun, items: List[PayslipItem], organization_id: int, org_currency: str = None) -> list:
    from app.modules.payroll.bank_export import BankExportRow

    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first() if organization_id else None

    # Use the org's explicit currency override if set, otherwise derive
    # from the jurisdiction — implements the Super Admin → Org Admin
    # inheritance model for currency. A bank transfer file is a real
    # payment instruction, so an org with no jurisdiction configured
    # anywhere raises here rather than silently paying out under an
    # assumed (India) currency.
    country = _resolve_org_country(db, organization_id, required=True)
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

    # Resolve the org's explicit currency override for bank exports.
    from app.modules.organizations.models import Organization
    org_row = db.query(Organization).filter(Organization.id == organization_id).first()
    org_currency = org_row.currency if org_row else None

    export_format = format_override or policy.bank_export_format
    rows = _build_bank_export_rows(db, run, items, organization_id, org_currency=org_currency)
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


def _resolve_org_country(db: Session, organization_id: int = None, *, required: bool = False) -> Optional[str]:
    """The org's current jurisdiction country — payslips/runs don't snapshot
    a country of their own, so this always reflects the org's *current*
    Compliance setting, same as the PDF generators already do.

    Prefers CompanyComplianceDetails.jurisdiction_country (set on the
    Compliance page); when that's blank — the default state of every
    organization until someone explicitly saves that page — falls back to
    Organization.country (set at registration, before Compliance Details is
    ever touched) rather than silently assuming India. When NEITHER is set:
    `required=True` raises a clear error (used where guessing wrong has a
    real financial/data-integrity consequence — employee jurisdiction
    assignment, bank export currency); `required=False` (default) returns
    None and leaves the caller's own already-graceful "unknown jurisdiction"
    handling to take over (an empty report list, a neutral $/USD display,
    the generic statutory-column set) instead of a guessed country."""
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first() if organization_id else None
    raw = getattr(company, "jurisdiction_country", None)
    if not raw and organization_id:
        from app.modules.organizations.models import Organization
        org_row = db.query(Organization).filter(Organization.id == organization_id).first()
        raw = getattr(org_row, "country", None)
    if not raw:
        if required:
            raise BadRequestException(
                "This organization hasn't configured a jurisdiction yet — "
                "set it under Compliance > Company Details before continuing."
            )
        return None
    return _normalize_country(raw)


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
        "stateProgramDeductions": item.state_program_deductions or z,
        "pf": item.pf or z,
        "esi": item.esi or z,
        "professionalTax": item.professional_tax or z,
        "employeeLwf": item.employee_lwf or z,
        "employerLwf": item.employer_lwf or z,
        "socialSecurity": item.social_security or z,
        "medicare": item.medicare or z,
        "niEmployee": item.ni_employee or z,
        "employeePension": item.employee_pension or z,
        # Canada: CPP2 — computed and persisted (see PayslipItem.cpp2) and
        # already correctly folded into total_deductions/net_pay, but this
        # dict never actually serialized it, so no payslip API response
        # ever surfaced the number despite it genuinely reducing net pay.
        "cpp2": item.cpp2 or z,
        # UK: Student/Postgraduate Loan deduction — correctly reduces net_pay
        # (engine/standard.py's total_employee_deductions) since it was
        # calculated, but was never added to this dict, so it never reached
        # any payslip API response despite being a real, persisted column.
        "studyLoanDeduction": item.study_loan_deduction or z,
        "postgradLoanDeduction": item.postgrad_loan_deduction or z,
        "employerPf": item.employer_pf or z,
        "employerEps": item.employer_eps or z,
        "employerPfResidual": item.employer_pf_residual or z,
        "employerEdli": item.employer_edli or z,
        "employerNps": item.employer_nps or z,
        "employerEsi": item.employer_esi or z,
        "employerSs": item.employer_social_security or z,
        "employerMedicare": item.employer_medicare or z,
        "employerPension": item.employer_pension or z,
        # UK: employer-side National Insurance — same "computed, persisted,
        # never serialized" gap as studyLoanDeduction above.
        "employerNi": item.employer_ni or z,
        "employerCpp2": item.employer_cpp2 or z,
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
    # Germany: Kirchensteuer (church tax) is a statutory deduction from the
    # employee's pay when de_church_tax_liable is set — persisted in
    # PayslipItem.church_tax and populated by the engine. Only shown when
    # the value is actually nonzero.
    if country == "DE":
        church_tax_val = float(data.get("church_tax", 0) or 0)
        if church_tax_val > 0:
            deduction_items.append(("Kirchensteuer", church_tax_val))
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
        ("Postgraduate Loan Deduction", "postgradLoanDeduction"),
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
        # ZP-TAX-CA-2026-001 §15/AC-20 — BC EHT ordinary-vs-charity/
        # nonprofit classification. See CompanyComplianceDetails' own
        # column comment (models.py) — previously no UI set this at all.
        "bcEhtEmployerClassification": "bc_eht_employer_classification",
        # ZP-TAX-CA-2026-001 §13 — Quebec HSF employer category (GENERAL |
        # PRIMARY_MANUFACTURING | PUBLIC_SECTOR). Same "no UI yet" gap as
        # BC's classification above, now closed the same way.
        "qcHsfEmployerCategory": "qc_hsf_employer_category",
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
    # None when nothing is configured anywhere — _get_currency_symbol below
    # already falls back to a neutral "$" for an unrecognized (including
    # None) country, rather than assuming India.
    country = _resolve_org_country(db, organization_id)
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

    # None when nothing is configured anywhere — .get() below already
    # falls back to the generic statutory-column set for any unrecognized
    # (including None) key, so this correctly avoids showing India-specific
    # columns (PF/ESI/PT) on an unconfigured org's compliance export.
    country = _resolve_org_country(db, organization_id)
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