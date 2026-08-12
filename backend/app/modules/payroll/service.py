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
The PF/ESI/PT/TDS calculations below implement the standard *simplified*
formulas (flat percentages of basic/gross, progressive slab tax on an
annualized gross with no deductions/exemptions modeled). Real statutory
payroll (especially TDS, which depends on regime, Section 80C/80D
declarations, HRA exemption rules, etc., and Professional Tax, which is
state-specific) is genuinely complex. Before going live, either replace
`_calculate_annual_tax` / `_generate_single_payslip` with a certified
payroll engine, or have these formulas reviewed by a payroll/compliance
specialist for your jurisdiction.
"""

import os
import os as _os
import re
import copy
from typing import List, Optional
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timedelta
from calendar import month_name

from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func, tuple_, or_, and_, case

from app.modules.payroll.models import (
    PayrollEmployee, EmploymentType, EmployeeStatus,
    PayrollRun, PayslipItem, PayrollAttendanceRecord, PayrollLeaveAllocation,
    PayrollLeaveRequest,
    ContributionRate, TaxSlab, CompanyComplianceDetails, ComplianceDocument, PayrollActivityLog,
    JurisdictionPack, PayrollHoliday,
    PayrollStatus, PayslipStatus, ActivityStatus, ComplianceDocumentStatus,
    PAYROLL_STATUS_ORDER,
)
from app.modules.payroll.employee_validation import get_employee_validation_strategy
from app.modules.payroll.schemas import (
    PayrollRunCreate, PayrollRunUpdate, PayslipItemCreate, CompanyDetailsUpdate,
    EmployeeCreate, EmployeeUpdate, BulkEmployeeItem, BulkEmployeeRequest,
    BulkDeleteRequest,
    AttendanceRecordCreate, BulkAttendanceRequest,
    JurisdictionPackUpsert,
)
from app.core.exceptions import NotFoundException, BadRequestException
from fastapi import HTTPException, status as http_status


ESI_MONTHLY_WAGE_CEILING = Decimal("21000")  # employees above this gross are ESI-exempt
MONTHS_PER_YEAR = Decimal("12")


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

_CONTRIBUTION_RATES_BY_COUNTRY = {
    "IN": [
        dict(component_key="pf", label="Employee Provident Fund (EPF)",
             employee_share="12% of Basic", employer_share="12% of Basic", total="24% of Basic",
             employee_rate_pct=Decimal("12.00"), employer_rate_pct=Decimal("12.00"), sort_order=1),
        dict(component_key="esi", label="Employee State Insurance (ESI)",
             employee_share="0.75% of Gross", employer_share="3.25% of Gross", total="4% of Gross",
             employee_rate_pct=Decimal("0.75"), employer_rate_pct=Decimal("3.25"), sort_order=2),
        dict(component_key="pt", label="Professional Tax (PT)",
             employee_share="₹200/month (fixed)", employer_share="—", total="₹200",
             flat_amount=Decimal("200.00"), sort_order=3),
        dict(component_key="tds", label="TDS / Income Tax",
             employee_share="As per income slab", employer_share="—", total="As per slab",
             sort_order=4),
    ],
    "US": [
        dict(component_key="social-security", label="Social Security",
             employee_share="6.2%", employer_share="6.2%", total="12.4%",
             employee_rate_pct=Decimal("6.20"), employer_rate_pct=Decimal("6.20"), sort_order=1),
        dict(component_key="medicare", label="Medicare",
             employee_share="1.45%", employer_share="1.45%", total="2.9%",
             employee_rate_pct=Decimal("1.45"), employer_rate_pct=Decimal("1.45"), sort_order=2),
        dict(component_key="futa", label="Federal Unemployment (FUTA)",
             employee_share="—", employer_share="6.0%", total="6.0%",
             employer_rate_pct=Decimal("6.00"), sort_order=3),
        dict(component_key="federal-income-tax", label="Federal Income Tax",
             employee_share="As per W-4", employer_share="—", total="As per W-4",
             sort_order=4),
    ],
    "UK": [
        dict(component_key="national-insurance", label="National Insurance",
             employee_share="8% (primary) / 2% (upper)", employer_share="13.8%", total="21.8% (employee) + 13.8%",
             employee_rate_pct=Decimal("8.00"), employer_rate_pct=Decimal("13.80"), sort_order=1),
        dict(component_key="employer-pension", label="Workplace Pension (Employer)",
             employee_share="—", employer_share="3% minimum", total="3%",
             employer_rate_pct=Decimal("3.00"), sort_order=2),
    ],
    # Representative defaults — Enterprise Policy jurisdictions. Unlike US/UK
    # above (display-only; the engine's US/UK calculators use hardcoded
    # constants), these component_keys are the actual keys _calc_australia/
    # _calc_germany/_calc_canada read from rate_map — genuinely
    # configuration-driven. Verify/adjust against current statutory rates
    # before relying on these for real payroll.
    "AU": [
        dict(component_key="super", label="Superannuation Guarantee",
             employee_share="—", employer_share="11.5%", total="11.5%",
             employer_rate_pct=Decimal("11.50"), sort_order=1),
        dict(component_key="medicare-levy", label="Medicare Levy",
             employee_share="2.0%", employer_share="—", total="2.0%",
             employee_rate_pct=Decimal("2.00"), sort_order=2),
        dict(component_key="income-tax", label="Income Tax (PAYG)",
             employee_share="As per income slab", employer_share="—", total="As per slab",
             sort_order=3),
    ],
    "DE": [
        dict(component_key="pension", label="Pension Insurance (Rentenversicherung)",
             employee_share="9.3%", employer_share="9.3%", total="18.6%",
             employee_rate_pct=Decimal("9.30"), employer_rate_pct=Decimal("9.30"), sort_order=1),
        dict(component_key="social-insurance", label="Social Insurance (Health / Unemployment / Care)",
             employee_share="9.0%", employer_share="9.0%", total="18.0%",
             employee_rate_pct=Decimal("9.00"), employer_rate_pct=Decimal("9.00"), sort_order=2),
        dict(component_key="income-tax", label="Income Tax (Lohnsteuer)",
             employee_share="As per income slab", employer_share="—", total="As per slab",
             sort_order=3),
    ],
    "CA": [
        dict(component_key="cpp", label="Canada Pension Plan (CPP)",
             employee_share="5.95%", employer_share="5.95%", total="11.9%",
             employee_rate_pct=Decimal("5.95"), employer_rate_pct=Decimal("5.95"), sort_order=1),
        dict(component_key="ei", label="Employment Insurance (EI)",
             employee_share="1.66%", employer_share="2.32%", total="3.98%",
             employee_rate_pct=Decimal("1.66"), employer_rate_pct=Decimal("2.32"), sort_order=2),
        dict(component_key="income-tax", label="Federal Income Tax",
             employee_share="As per income slab", employer_share="—", total="As per slab",
             sort_order=3),
    ],
}


def _seed_contribution_rates(db: Session, organization_id: int, country: str = "IN") -> List[ContributionRate]:
    defaults = _CONTRIBUTION_RATES_BY_COUNTRY.get(country, _CONTRIBUTION_RATES_BY_COUNTRY["IN"])
    rows = []
    for d in defaults:
        row = ContributionRate(organization_id=organization_id, jurisdiction_country=country, **d)
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def get_contribution_rates(db: Session, organization_id: int = None, country: str = "IN") -> List[ContributionRate]:
    query = db.query(ContributionRate)
    query = _apply_org_filter(query, ContributionRate, organization_id)
    query = query.filter(ContributionRate.jurisdiction_country == country)
    rows = query.order_by(ContributionRate.sort_order).all()
    if not rows and organization_id:
        rows = _seed_contribution_rates(db, organization_id, country)
    return rows


_TAX_SLABS_BY_COUNTRY = {
    "IN": [
        # FY 2025-26 New Regime — standard deduction of ₹75,000 already
        # factored into the effective taxable income passed to the engine.
        dict(min_amount=Decimal("0"),        max_amount=Decimal("400000"),   rate_pct=Decimal("0"),   rate_label="Nil",  tax_formula="Basic exemption (up to ₹4L)", sort_order=1),
        dict(min_amount=Decimal("400000"),   max_amount=Decimal("800000"),   rate_pct=Decimal("5"),   rate_label="5%",   tax_formula="5% of income over ₹4L", sort_order=2),
        dict(min_amount=Decimal("800000"),   max_amount=Decimal("1200000"),  rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="₹20,000 + 10% over ₹8L", sort_order=3),
        dict(min_amount=Decimal("1200000"),  max_amount=Decimal("1600000"),  rate_pct=Decimal("15"),  rate_label="15%",  tax_formula="₹60,000 + 15% over ₹12L", sort_order=4),
        dict(min_amount=Decimal("1600000"),  max_amount=Decimal("2000000"),  rate_pct=Decimal("20"),  rate_label="20%",  tax_formula="₹1,20,000 + 20% over ₹16L", sort_order=5),
        dict(min_amount=Decimal("2000000"),  max_amount=Decimal("2400000"),  rate_pct=Decimal("25"),  rate_label="25%",  tax_formula="₹2,00,000 + 25% over ₹20L", sort_order=6),
        dict(min_amount=Decimal("2400000"),  max_amount=None,                rate_pct=Decimal("30"),  rate_label="30%",  tax_formula="₹3,00,000 + 30% over ₹24L", sort_order=7),
    ],
    "US": [
        # Tax Year 2025 — Single filer. Standard deduction $15,000 is
        # applied by _calculate_annual_tax_us before these brackets.
        dict(min_amount=Decimal("0"),       max_amount=Decimal("11925"),    rate_pct=Decimal("10"),  rate_label="10%",  tax_formula="10% of income", sort_order=1),
        dict(min_amount=Decimal("11925"),   max_amount=Decimal("48475"),    rate_pct=Decimal("12"),  rate_label="12%",  tax_formula="$1,192.50 + 12% over $11,925", sort_order=2),
        dict(min_amount=Decimal("48475"),   max_amount=Decimal("103350"),   rate_pct=Decimal("22"),  rate_label="22%",  tax_formula="$5,570.50 + 22% over $48,475", sort_order=3),
        dict(min_amount=Decimal("103350"),  max_amount=Decimal("197300"),   rate_pct=Decimal("24"),  rate_label="24%",  tax_formula="$17,645 + 24% over $103,350", sort_order=4),
        dict(min_amount=Decimal("197300"),  max_amount=Decimal("250525"),   rate_pct=Decimal("32"),  rate_label="32%",  tax_formula="$40,199 + 32% over $197,300", sort_order=5),
        dict(min_amount=Decimal("250525"),  max_amount=Decimal("626350"),   rate_pct=Decimal("35"),  rate_label="35%",  tax_formula="$57,131 + 35% over $250,525", sort_order=6),
        dict(min_amount=Decimal("626350"),  max_amount=None,                rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="$188,364.75 + 37% over $626,350", sort_order=7),
    ],
    "UK": [
        # Tax Year 2025-26. Personal allowance £12,570 (tapered above
        # £100k — handled in _calculate_annual_tax_uk).
        dict(min_amount=Decimal("0"),       max_amount=Decimal("12570"),    rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="Personal allowance", sort_order=1),
        dict(min_amount=Decimal("12570"),   max_amount=Decimal("50270"),    rate_pct=Decimal("20"),  rate_label="20%",  tax_formula="20% of income above £12,570", sort_order=2),
        dict(min_amount=Decimal("50270"),   max_amount=Decimal("125140"),   rate_pct=Decimal("40"),  rate_label="40%",  tax_formula="£7,540 + 40% above £50,270", sort_order=3),
        dict(min_amount=Decimal("125140"),  max_amount=None,                rate_pct=Decimal("45"),  rate_label="45%",  tax_formula="£37,488 + 45% above £125,140", sort_order=4),
    ],
    # Enterprise Policy jurisdictions — representative/simplified brackets,
    # genuinely read by the engine (see _CONTRIBUTION_RATES_BY_COUNTRY note
    # above). Verify against current statutory brackets before production use.
    "AU": [
        # Resident individual rates, simplified (excludes Medicare Levy,
        # calculated separately in _calc_australia).
        dict(min_amount=Decimal("0"),       max_amount=Decimal("18200"),    rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="Tax-free threshold", sort_order=1),
        dict(min_amount=Decimal("18200"),   max_amount=Decimal("45000"),    rate_pct=Decimal("16"),  rate_label="16%",  tax_formula="16% of income above A$18,200", sort_order=2),
        dict(min_amount=Decimal("45000"),   max_amount=Decimal("135000"),   rate_pct=Decimal("30"),  rate_label="30%",  tax_formula="A$4,288 + 30% above A$45,000", sort_order=3),
        dict(min_amount=Decimal("135000"),  max_amount=Decimal("190000"),   rate_pct=Decimal("37"),  rate_label="37%",  tax_formula="A$31,288 + 37% above A$135,000", sort_order=4),
        dict(min_amount=Decimal("190000"),  max_amount=None,                rate_pct=Decimal("45"),  rate_label="45%",  tax_formula="A$51,638 + 45% above A$190,000", sort_order=5),
    ],
    "DE": [
        # Simplified bracket approximation of Germany's continuous income
        # tax formula (real Lohnsteuer uses a smooth curve, not flat bands).
        dict(min_amount=Decimal("0"),       max_amount=Decimal("11000"),    rate_pct=Decimal("0"),   rate_label="0%",   tax_formula="Basic tax-free allowance", sort_order=1),
        dict(min_amount=Decimal("11000"),   max_amount=Decimal("17000"),    rate_pct=Decimal("14"),  rate_label="14%",  tax_formula="14% of income above €11,000", sort_order=2),
        dict(min_amount=Decimal("17000"),   max_amount=Decimal("66000"),    rate_pct=Decimal("30"),  rate_label="30%",  tax_formula="€840 + 30% above €17,000", sort_order=3),
        dict(min_amount=Decimal("66000"),   max_amount=Decimal("277000"),   rate_pct=Decimal("42"),  rate_label="42%",  tax_formula="€15,540 + 42% above €66,000", sort_order=4),
        dict(min_amount=Decimal("277000"),  max_amount=None,                rate_pct=Decimal("45"),  rate_label="45%",  tax_formula="€104,160 + 45% above €277,000", sort_order=5),
    ],
    "CA": [
        # Federal brackets only — provincial tax excluded for simplicity.
        dict(min_amount=Decimal("0"),       max_amount=Decimal("55000"),    rate_pct=Decimal("15"),    rate_label="15%",    tax_formula="15% of income", sort_order=1),
        dict(min_amount=Decimal("55000"),   max_amount=Decimal("111000"),   rate_pct=Decimal("20.5"),  rate_label="20.5%",  tax_formula="C$8,250 + 20.5% above C$55,000", sort_order=2),
        dict(min_amount=Decimal("111000"),  max_amount=Decimal("173000"),   rate_pct=Decimal("26"),    rate_label="26%",    tax_formula="C$19,730 + 26% above C$111,000", sort_order=3),
        dict(min_amount=Decimal("173000"),  max_amount=Decimal("246000"),   rate_pct=Decimal("29"),    rate_label="29%",    tax_formula="C$35,850 + 29% above C$173,000", sort_order=4),
        dict(min_amount=Decimal("246000"),  max_amount=None,                rate_pct=Decimal("33"),    rate_label="33%",    tax_formula="C$57,020 + 33% above C$246,000", sort_order=5),
    ],
}


def _seed_tax_slabs(db: Session, organization_id: int, country: str = "IN") -> List[TaxSlab]:
    defaults = _TAX_SLABS_BY_COUNTRY.get(country, _TAX_SLABS_BY_COUNTRY["IN"])
    rows = []
    for d in defaults:
        row = TaxSlab(organization_id=organization_id, jurisdiction_country=country, **d)
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def get_tax_slabs(db: Session, organization_id: int = None, country: str = "IN") -> List[TaxSlab]:
    query = db.query(TaxSlab)
    query = _apply_org_filter(query, TaxSlab, organization_id)
    query = query.filter(TaxSlab.jurisdiction_country == country)
    rows = query.order_by(TaxSlab.sort_order).all()
    if not rows and organization_id:
        rows = _seed_tax_slabs(db, organization_id, country)
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
    """Create or update a pack, matched by (pack_id, version) — matches
    the UniqueConstraint on JurisdictionPack. This intentionally does NOT
    silently bump the version on every save: per the spec's lifecycle
    model (Section 17), a new version should be a deliberate act, not an
    accidental side effect of editing metadata.

    When the (pack_id, version) pair doesn't exist yet AND another version
    of the same pack_id already does, the new row's previous_version_id is
    set to the latest prior version automatically — this is what gives
    Compliance its version chain (1.0 -> 1.1 -> 2.0) without ever mutating
    or deleting an earlier row.
    """
    existing = (
        db.query(JurisdictionPack)
        .filter(JurisdictionPack.pack_id == data.packId, JurisdictionPack.version == data.version)
        .first()
    )
    fields = dict(
        jurisdiction_country=data.jurisdictionCountry,
        jurisdiction_state=data.jurisdictionState,
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
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.updated_by_id = actor_id
        row = existing
    else:
        previous = (
            db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == data.packId)
            .order_by(JurisdictionPack.created_at.desc())
            .first()
        )
        row = JurisdictionPack(
            pack_id=data.packId, version=data.version,
            previous_version_id=previous.id if previous else None,
            created_by_id=actor_id, updated_by_id=actor_id,
            **fields,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_all_jurisdiction_packs(
    db: Session, country: Optional[str] = None, state: Optional[str] = None,
    status: Optional[str] = None, search: Optional[str] = None,
) -> List[JurisdictionPack]:
    """Cross-jurisdiction policy list for Super Admin Compliance — unlike
    list_jurisdiction_packs (which requires a single country and returns
    every version of its packs), this spans every jurisdiction and, per
    pack_id, returns only the latest version — i.e. one row per policy,
    which is what a review/listing screen needs. Use
    get_jurisdiction_pack_versions() to drill into one policy's history."""
    query = db.query(JurisdictionPack)
    if country:
        query = query.filter(JurisdictionPack.jurisdiction_country == country)
    if state:
        query = query.filter(JurisdictionPack.jurisdiction_state == state)
    if status:
        query = query.filter(JurisdictionPack.status == status)
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
    row.status = status
    row.updated_by_id = actor_id
    db.commit()
    db.refresh(row)
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


def assign_pack_to_organizations(db: Session, pack_row_id: int, organization_ids: List[int], actor_id: Optional[int] = None) -> int:
    """Bulk-assign a policy version as the active pack for each given org,
    get-or-creating their CompanyComplianceDetails row exactly like every
    other Compliance write path does (get_or_create_email_settings,
    get_company_details, etc.) rather than requiring the org to have
    configured Compliance first."""
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.id == pack_row_id).first()
    if not pack:
        raise NotFoundException("JurisdictionPack", pack_row_id)

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
            f"Compliance policy {pack.pack_id} v{pack.version} applied by Super Admin.",
            ActivityStatus.INFO, actor_id=actor_id,
        )
    db.commit()
    return updated


def _calculate_annual_tax(annual_income: Decimal, slabs: List[TaxSlab]) -> Decimal:
    """Progressive slab-based tax on the full annual income. See module
    docstring for the accuracy disclaimer."""
    tax = Decimal("0")
    for slab in sorted(slabs, key=lambda s: s.min_amount):
        lower = slab.min_amount
        upper = slab.max_amount if slab.max_amount is not None else annual_income
        if annual_income <= lower:
            continue
        taxable_in_band = min(annual_income, upper) - lower
        if taxable_in_band > 0:
            tax += taxable_in_band * (slab.rate_pct / Decimal("100"))
    return tax


# ── FY 2025-26 constants (India, New Regime) ────────────────────────────

_IN_STANDARD_DEDUCTION = Decimal("75000")   # ₹75,000 standard deduction
_IN_REBATE_87A_LIMIT = Decimal("1200000")   # Nil tax up to ₹12L taxable income
_IN_REBATE_87A_MAX = Decimal("60000")       # Max rebate = tax on ₹12L = ₹60,000
_IN_SURCHARGE_THRESHOLD = Decimal("50000000")  # 50L — not applied here

# ── Tax Year 2025 constants (US, Single filer) ──────────────────────────

_US_STANDARD_DEDUCTION = Decimal("15000")   # $15,000 standard deduction (single)
_US_SOCIAL_SECURITY_WAGE_BASE = Decimal("176100")  # SS tax only on first $176,100
_US_SOCIAL_SECURITY_RATE = Decimal("6.2")
_US_MEDICARE_RATE = Decimal("1.45")
_US_MEDICARE_ADDITIONAL_RATE = Decimal("0.9")  # Additional Medicare on > $200k

# ── Tax Year 2025-26 constants (UK) ─────────────────────────────────────

_UK_PERSONAL_ALLOWANCE = Decimal("12570")
_UK_PA_TAPER_THRESHOLD = Decimal("100000")  # PA reduces by £1 per £2 over £100k
_UK_NI_PRIMARY_THRESHOLD = Decimal("12570")  # Annual primary threshold
_UK_NI_UPPER_THRESHOLD = Decimal("50270")    # Annual upper earnings limit
_UK_NI_PRIMARY_RATE = Decimal("8")           # 8% (was 12% → cut in 2024)
_UK_NI_UPPER_RATE = Decimal("2")            # 2% (was 2% → unchanged)
_UK_PENSION_MIN_ENPLOYER = Decimal("3")     # Minimum employer contribution


def _apply_section_87a_rebate(annual_tax: Decimal, taxable_income: Decimal) -> Decimal:
    """Section 87A rebate for India New Regime FY 2025-26.
    If taxable income <= ₹12,00,000, rebate = min(annual_tax, ₹60,000),
    and that rebate is SUBTRACTED from tax owed — not returned as-is.
    Since the slabs are calibrated so tax-at-exactly-₹12L equals ₹60,000,
    annual_tax is always <= ₹60,000 whenever taxable_income <= ₹12L, which
    means the rebate always fully cancels the tax (net: ₹0). The previous
    version of this function returned `min(annual_tax, 60000)` directly —
    since that's always just `annual_tax` unchanged in this branch, the
    rebate had silently never reduced anyone's tax at all.
    Marginal relief: if crossing ₹12L causes tax to exceed ₹60,000,
    tax is capped to ₹60,000 + (taxable_income - 12L)."""
    if taxable_income <= _IN_REBATE_87A_LIMIT:
        rebate = min(annual_tax, _IN_REBATE_87A_MAX)
        return annual_tax - rebate
    # Marginal relief: tax on ₹12L is ₹60,000. If actual tax > ₹60,000
    # and the excess is less than the income above ₹12L, cap to ₹60,000.
    tax_on_threshold = _IN_REBATE_87A_MAX  # ₹60,000
    if annual_tax > tax_on_threshold:
        excess_income = taxable_income - _IN_REBATE_87A_LIMIT
        excess_tax = annual_tax - tax_on_threshold
        if excess_tax <= excess_income:
            return tax_on_threshold + excess_tax
        return annual_tax
    return annual_tax


def _calculate_annual_tax_in(annual_gross: Decimal, slabs: List[TaxSlab]) -> Decimal:
    """India-specific annual tax: standard deduction → progressive slabs → Section 87A rebate."""
    taxable = max(Decimal("0"), annual_gross - _IN_STANDARD_DEDUCTION)
    tax = _calculate_annual_tax(taxable, slabs)
    tax = _apply_section_87a_rebate(tax, taxable)
    return max(Decimal("0"), tax)


def _calculate_annual_tax_us(annual_gross: Decimal, slabs: List[TaxSlab]) -> Decimal:
    """US-specific annual tax: standard deduction → progressive federal slabs."""
    taxable = max(Decimal("0"), annual_gross - _US_STANDARD_DEDUCTION)
    return _calculate_annual_tax(taxable, slabs)


def _calculate_annual_tax_uk(annual_gross: Decimal, slabs: List[TaxSlab]) -> Decimal:
    """UK-specific annual tax: personal allowance taper → progressive slabs.
    PA is reduced by £1 for every £2 of income above £100,000."""
    pa = _UK_PERSONAL_ALLOWANCE
    if annual_gross > _UK_PA_TAPER_THRESHOLD:
        taper = (annual_gross - _UK_PA_TAPER_THRESHOLD) / Decimal("2")
        pa = max(Decimal("0"), pa - taper)
    taxable = max(Decimal("0"), annual_gross - pa)
    return _calculate_annual_tax(taxable, slabs)


def _calculate_employee_monthly_payroll(
    gross: Decimal,
    basic: Decimal,
    rate_map: dict,
    slabs: List[TaxSlab],
    country: str = "IN",
    calculation_mode: str = "standard",
) -> dict:
    """DEPRECATED — Use ``app.modules.payroll.engine.resolver.calculate_payroll()``
    instead.  This function is kept only for backward compatibility with any
    external code that may still import it directly.

    Shared payroll calculation engine — used by both payslip generation
    and the preview endpoint. Returns a dict with all breakdown fields.

    When *calculation_mode* is ``"simple"``, all statutory deductions
    (PF, ESI, PT, TDS, NI, etc.) are zeroed out — net equals gross.
    Attendance-based deductions (unpaid leave) are already applied via
    the proration factor in the caller."""
    from app.modules.payroll.models import EmployeeStatus

    employee_pf = Decimal("0")
    employer_pf = Decimal("0")
    employee_esi = Decimal("0")
    employer_esi = Decimal("0")
    professional_tax = Decimal("0")
    social_security = Decimal("0")
    medicare = Decimal("0")
    employer_social_security = Decimal("0")
    employer_medicare = Decimal("0")
    ni_employee = Decimal("0")
    employer_pension = Decimal("0")

    if calculation_mode == "simple":
        # Simple mode: no statutory deductions — net equals gross.
        # Attendance-based deductions (unpaid leave) are already handled
        # via proration_factor in the caller.
        tds = Decimal("0")
        annual_tax = Decimal("0")
        total_deductions = Decimal("0")

    elif country == "IN":
        # ── India: PF, ESI, Professional Tax ──
        pf_rate = rate_map.get("pf")
        employee_pf = _round2(basic * (pf_rate.employee_rate_pct / 100)) if pf_rate and pf_rate.employee_rate_pct else Decimal("0")
        employer_pf = _round2(basic * (pf_rate.employer_rate_pct / 100)) if pf_rate and pf_rate.employer_rate_pct else Decimal("0")

        esi_rate = rate_map.get("esi")
        esi_applicable = gross <= ESI_MONTHLY_WAGE_CEILING
        employee_esi = _round2(gross * (esi_rate.employee_rate_pct / 100)) if esi_rate and esi_rate.employee_rate_pct and esi_applicable else Decimal("0")
        employer_esi = _round2(gross * (esi_rate.employer_rate_pct / 100)) if esi_rate and esi_rate.employer_rate_pct and esi_applicable else Decimal("0")

        pt_rate = rate_map.get("pt")
        professional_tax = pt_rate.flat_amount if pt_rate and pt_rate.flat_amount else Decimal("0")

        annual_gross = gross * MONTHS_PER_YEAR
        annual_tax = _calculate_annual_tax_in(annual_gross, slabs)
        tds = _round2(annual_tax / MONTHS_PER_YEAR)
        total_deductions = employee_pf + employee_esi + professional_tax + tds

    elif country == "US":
        # ── US: Social Security + Medicare (employee + employer) + Federal income tax ──
        annual_gross = gross * MONTHS_PER_YEAR

        # Employee Social Security: 6.2% on first $176,100/year
        annual_ss_wage = min(annual_gross, _US_SOCIAL_SECURITY_WAGE_BASE)
        social_security = _round2((annual_ss_wage * _US_SOCIAL_SECURITY_RATE / Decimal("100")) / MONTHS_PER_YEAR)
        employer_social_security = social_security  # Employer matches

        # Employee Medicare: 1.45% on all wages (no cap)
        medicare = _round2((annual_gross * _US_MEDICARE_RATE / Decimal("100")) / MONTHS_PER_YEAR)
        # Additional Medicare: 0.9% on wages above $200k (employee only, annualized)
        if annual_gross > Decimal("200000"):
            medicare += _round2(((annual_gross - Decimal("200000")) * _US_MEDICARE_ADDITIONAL_RATE / Decimal("100")) / MONTHS_PER_YEAR)
        employer_medicare = _round2((annual_gross * _US_MEDICARE_RATE / Decimal("100")) / MONTHS_PER_YEAR)

        annual_tax = _calculate_annual_tax_us(annual_gross, slabs)
        tds = _round2(annual_tax / MONTHS_PER_YEAR)
        total_deductions = social_security + medicare + tds

    elif country == "UK":
        # ── UK: National Insurance (employee) + employer pension ──
        annual_gross = gross * MONTHS_PER_YEAR

        # Employee NI: 8% between primary threshold and upper threshold, 2% above
        annual_pt = _UK_NI_PRIMARY_THRESHOLD
        annual_ut = _UK_NI_UPPER_THRESHOLD
        ni_basicable = max(Decimal("0"), min(annual_gross, annual_ut) - annual_pt)
        ni_upperable = max(Decimal("0"), annual_gross - annual_ut)
        ni_employee_annual = (ni_basicable * _UK_NI_PRIMARY_RATE / Decimal("100")) + (ni_upperable * _UK_NI_UPPER_RATE / Decimal("100"))
        ni_employee = _round2(ni_employee_annual / MONTHS_PER_YEAR)

        # Employer pension: minimum 3% of gross
        employer_pension = _round2(annual_gross * _UK_PENSION_MIN_ENPLOYER / Decimal("100") / MONTHS_PER_YEAR)

        annual_tax = _calculate_annual_tax_uk(annual_gross, slabs)
        tds = _round2(annual_tax / MONTHS_PER_YEAR)
        total_deductions = ni_employee + tds

    else:
        # Fallback: generic progressive tax only
        annual_gross = gross * MONTHS_PER_YEAR
        annual_tax = _calculate_annual_tax(annual_gross, slabs)
        tds = _round2(annual_tax / MONTHS_PER_YEAR)
        total_deductions = tds

    net_pay = gross - total_deductions

    return {
        "basic": basic,
        "gross": gross,
        "employee_pf": employee_pf,
        "employer_pf": employer_pf,
        "employee_esi": employee_esi,
        "employer_esi": employer_esi,
        "professional_tax": professional_tax,
        "social_security": social_security,
        "medicare": medicare,
        "employer_social_security": employer_social_security,
        "employer_medicare": employer_medicare,
        "ni_employee": ni_employee,
        "employer_pension": employer_pension,
        "tds": tds,
        "annual_tax": annual_tax,
        "total_deductions": total_deductions,
        "net_pay": net_pay,
    }


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
    rate_map = {r.component_key: r for r in get_contribution_rates(db, organization_id, country)}
    slabs = get_tax_slabs(db, organization_id, country)

    employees = db.query(PayrollEmployee).filter(
        PayrollEmployee.id.in_(employee_ids),
        PayrollEmployee.organization_id == organization_id,
        PayrollEmployee.status == EmployeeStatus.ACTIVE,
        or_(
            PayrollEmployee.date_of_joining == None,
            PayrollEmployee.date_of_joining <= (period_start or date.today()),
        ),
    ).all()

    results = []
    totals = {
        "count": 0,
        "totalGross": Decimal("0"),
        "totalTax": Decimal("0"),
        "totalContributions": Decimal("0"),
        "totalNet": Decimal("0"),
    }

    for emp in employees:
        ctc = Decimal(str(getattr(emp, "ctc", 0) or 0))
        monthly_gross = _round2(ctc / MONTHS_PER_YEAR) if ctc else Decimal("0")

        # Fixed 30-Day: count unpaid leave days from attendance records
        unpaid_leave_days = (
            _count_unpaid_leave_days(db, organization_id, emp.id, period_start, period_end)
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
            special = _round2(monthly_gross - basic - hra)
        else:
            basic     = _round2(monthly_gross * Decimal("0.40"))
            hra       = _round2(monthly_gross * Decimal("0.20"))
            special   = _round2(monthly_gross * Decimal("0.40"))

        is_active = emp.status == EmployeeStatus.ACTIVE
        overtime = Decimal("0")
        additional_compensation = (
            _sum_attendance_extras(db, organization_id, emp.id, period_start, period_end)
            if is_active and period_start and period_end else Decimal("0")
        )
        gross = basic + hra + special + overtime + additional_compensation

        # Delegate to the strategy engine
        ctx = build_context_from_employee(
            emp, gross=gross, basic=basic, hra=hra,
            special_allowance=special, overtime=overtime,
            additional_compensation=additional_compensation,
            unpaid_leave_days=unpaid_leave_days,
            country=country, rate_map=rate_map, slabs=slabs,
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
            "monthlyTax": float(calc.tds),
            "monthlyPf": float(calc.employee_pf),
            "monthlyEsi": float(calc.employee_esi),
            "monthlyPt": float(calc.professional_tax),
            "monthlySocialSecurity": float(calc.social_security),
            "monthlyMedicare": float(calc.medicare),
            "monthlyNi": float(calc.ni_employee),
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

    for slab in sorted(slabs, key=lambda s: s.min_amount):
        upper = slab.max_amount if slab.max_amount is not None else taxable
        if taxable <= upper:
            return slab.rate_label or "—"
    return slabs[-1].rate_label if slabs else "—"


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
    defaults = _DEFAULT_HOLIDAYS_BY_COUNTRY.get(country, _DEFAULT_HOLIDAYS_BY_COUNTRY["IN"])
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


def _compute_payslip_values(db: Session, run: PayrollRun, employee, rate_map, slabs, country: str = "IN",
                             calculation_mode: str = "standard", attendance_records: List["PayrollAttendanceRecord"] = None) -> dict:
    """Compute every payslip figure for an employee within a run and return
    them as a dict, without touching the database. Shared by initial payslip
    generation (_generate_single_payslip) and recalculation
    (regenerate_employee_payslip) so both always produce identical figures.

    `attendance_records`: this employee's pre-fetched attendance rows for the
    run's period, if the caller already batched them across employees (see
    generate_payslips_for_run) — avoids 2 queries per employee. None means
    "query for this employee alone" (regenerate_employee_payslip's path)."""
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
        special = _round2(monthly_gross - basic - hra)
    else:
        basic     = _round2(monthly_gross * Decimal("0.40"))
        hra       = _round2(monthly_gross * Decimal("0.20"))
        special   = _round2(monthly_gross * Decimal("0.40"))

    is_active = employee.status == EmployeeStatus.ACTIVE
    overtime  = Decimal("0")
    additional_compensation = (
        _sum_attendance_extras(db, run.organization_id, employee.id, run.period_start, run.period_end, records=attendance_records)
        if is_active else Decimal("0")
    )
    gross = basic + hra + special + overtime + additional_compensation

    # Delegate to the strategy engine
    ctx = build_context_from_employee(
        employee, gross=gross, basic=basic, hra=hra,
        special_allowance=special, overtime=overtime,
        additional_compensation=additional_compensation,
        unpaid_leave_days=unpaid_leave_days,
        country=country, rate_map=rate_map, slabs=slabs,
    )
    result = calculate_payroll(ctx, calculation_mode)

    employee_name = getattr(employee, "name", None) or f"Employee #{employee.id}"

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
        "tds": result.tds,
        "total_deductions": result.total_deductions,
        "employer_pf": result.employer_pf,
        "employer_esi": result.employer_esi,
        "employer_social_security": result.employer_social_security,
        "employer_medicare": result.employer_medicare,
        "employer_pension": result.employer_pension,
        "net_pay": result.net_pay,
        "unpaid_leave_days": result.unpaid_leave_days,
        "attendance_deduction": result.attendance_deduction,
        "per_day_salary": result.per_day_salary,
    }


def _generate_single_payslip(db: Session, run: PayrollRun, employee, rate_map, slabs, country: str = "IN",
                              calculation_mode: str = "standard", payslip_number: str = None,
                              attendance_records: List["PayrollAttendanceRecord"] = None) -> PayslipItem:
    """Generate a single payslip using the strategy-based payroll engine.

    Fixed 30-Day Payroll Model:
        PAYROLL_DAYS = 30
        Per Day Salary = Monthly Gross / 30
        Attendance Deduction = Unpaid Leave Days × Per Day Salary
        Payable Days = 30 − Unpaid Leave Days

    Salary components (basic, hra, special) are full monthly amounts — no
    proration.  Attendance deduction is a separate line item.  Statutory
    deductions are computed on the full gross by the resolved strategy.
    """
    values = _compute_payslip_values(db, run, employee, rate_map, slabs, country, calculation_mode, attendance_records=attendance_records)

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
    run.total_employer_contribution = sum((i.employer_pf + i.employer_esi + i.employer_social_security + i.employer_medicare + i.employer_pension for i in items), Decimal("0"))
    run.total_net = sum((i.net_pay for i in items), Decimal("0"))
    db.commit()
    db.refresh(run)
    return run


def _resolve_run_calc_inputs(db: Session, run: PayrollRun, organization_id: int = None):
    """Shared setup for generating a payslip within a run — jurisdiction
    country, calculation mode, and the country's rate/slab lookups. Used by
    both a full run generation and a single-employee regeneration so the
    two never resolve jurisdiction/rates differently."""
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first() if organization_id else None
    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    calculation_mode = getattr(run, "calculation_mode", None) or _resolve_calculation_mode(db, organization_id)
    rate_map = {r.component_key: r for r in get_contribution_rates(db, organization_id, country)}
    slabs = get_tax_slabs(db, organization_id, country)
    return country, calculation_mode, rate_map, slabs


def generate_payslips_for_run(db: Session, run: PayrollRun, organization_id: int = None, employee_ids: List[int] = None) -> PayrollRun:
    """Generate a payslip for every Active employee in the org (or only the
    specified employee_ids if provided). Idempotent: re-running skips
    employees who already have a payslip in this run."""
    country, calculation_mode, rate_map, slabs = _resolve_run_calc_inputs(db, run, organization_id)

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
    for emp in employees:
        if emp.id in existing_ids:
            continue
        payslip_number = f"{base_payslip_code}{seq:05d}" if base_payslip_code else None
        _generate_single_payslip(
            db, run, emp, rate_map, slabs, country, calculation_mode, payslip_number=payslip_number,
            attendance_records=attendance_by_employee.get(emp.id, []),
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

    country, calculation_mode, rate_map, slabs = _resolve_run_calc_inputs(db, run, organization_id)
    values = _compute_payslip_values(db, run, employee, rate_map, slabs, country, calculation_mode)
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
                   search: str = None, department: str = None, status: str = None) -> List[PayrollEmployee]:
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
    return query.order_by(PayrollEmployee.name).all()


def get_employee_by_id(db: Session, employee_id: int, organization_id: int) -> PayrollEmployee:
    employee = db.query(PayrollEmployee).filter(
        PayrollEmployee.id == employee_id,
        PayrollEmployee.organization_id == organization_id,
    ).first()
    if not employee:
        raise NotFoundException(f"Employee {employee_id} not found.")
    return employee


def _default_basic_hra_from_ctc(ctc) -> tuple:
    """Basic/HRA split applied when an employee is created without them —
    the same 40%/20% ratios _generate_single_payslip falls back to at
    payslip time, computed once here so the employee's own Basic/HRA
    columns carry a real number instead of staying blank."""
    ctc_val = Decimal(str(ctc or 0))
    return _round2(ctc_val * Decimal("0.40")), _round2(ctc_val * Decimal("0.20"))


def _fill_missing_basic_hra(fields: dict) -> None:
    """Mutates `fields` in place, filling only whichever of basic/hra is
    actually missing — a value the caller did provide is never overwritten."""
    if fields.get("basic") is None or fields.get("hra") is None:
        default_basic, default_hra = _default_basic_hra_from_ctc(fields.get("ctc"))
        if fields.get("basic") is None:
            fields["basic"] = default_basic
        if fields.get("hra") is None:
            fields["hra"] = default_hra


def _resolve_employee_country(db: Session, organization_id: int, explicit_country_code: Optional[str]) -> str:
    """Per-employee jurisdiction override if given, else the org's default —
    same fallback pattern _resolve_run_calc_inputs already uses for payroll
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
    Strategy's `duplicate_field` for the other five countries). Loads the
    org's employees once and compares in Python, consistent with how the
    rest of this module already favors simple in-Python comparisons over
    JSON-path SQL operators (see e.g. _count_unpaid_leave_days)."""
    email_norm = (email or "").strip().lower()
    pan_norm = (pan or "").strip().upper()
    strategy = get_employee_validation_strategy(country_code)
    dup_id = strategy.get_duplicate_identifier(compliance_fields)

    if not email_norm and not pan_norm and not dup_id:
        return

    query = db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == organization_id)
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
    _fill_missing_basic_hra(employee_data)

    country_code = _resolve_employee_country(db, organization_id, employee_data.get("country_code"))
    employee_data["country_code"] = country_code
    strategy = get_employee_validation_strategy(country_code)
    employee_data["compliance_fields"] = strategy.validate(employee_data.get("compliance_fields") or {})

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
        _fill_missing_basic_hra(mapped)

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


def get_payroll_runs(db: Session, organization_id: int = None, year: int = None, month: int = None) -> List[PayrollRun]:
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

    # Determine jurisdiction country from org's compliance details
    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id
    ).first() if organization_id else None
    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")

    rate_map = {r.component_key: r for r in get_contribution_rates(db, organization_id, country)}
    slabs = get_tax_slabs(db, organization_id, country)

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
    )
    calc = calculate_payroll(ctx, calculation_mode)

    employee_name = getattr(employee, "name", None) or ""

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
        tds=calc.tds,
        total_deductions=calc.total_deductions,
        employer_pf=calc.employer_pf,
        employer_esi=calc.employer_esi,
        employer_social_security=calc.employer_social_security,
        employer_medicare=calc.employer_medicare,
        employer_pension=calc.employer_pension,
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


def _build_bank_export_rows(run: PayrollRun, items: List[PayslipItem], company) -> list:
    from app.modules.payroll.bank_export import BankExportRow

    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
    currency_code = _get_currency_code(country)
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

    export_format = format_override or policy.bank_export_format
    rows = _build_bank_export_rows(run, items, company)
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
        "period": run.period_label,
        "payDate": run.pay_date,
        "salary": item.gross_pay or z,
        "basicPay": item.basic_salary or z,
        "hra": item.hra or z,
        "specialAllowance": item.special_allowance or z,
        "overtime": item.overtime or z,
        "additionalCompensation": item.additional_compensation or z,
        "payableDays": item.payable_days,        # None on old rows generated before this
        "totalWorkingDays": item.total_working_days,  # column existed — genuinely unknown, not 0
        "unpaidLeaveDays": item.unpaid_leave_days,
        "attendanceDeduction": item.attendance_deduction or z,
        "tds": item.tds or z,
        "pf": item.pf or z,
        "esi": item.esi or z,
        "professionalTax": item.professional_tax or z,
        "socialSecurity": item.social_security or z,
        "medicare": item.medicare or z,
        "niEmployee": item.ni_employee or z,
        "employerPf": item.employer_pf or z,
        "employerEsi": item.employer_esi or z,
        "employerSs": item.employer_social_security or z,
        "employerMedicare": item.employer_medicare or z,
        "employerPension": item.employer_pension or z,
        "totalDeductions": item.total_deductions or z,
        "netPay": item.net_pay or z,
        "bankName": item.bank_name,
        "bankAccount": item.bank_account,
        "pan": item.pan,
        "uan": item.uan,
        "ifsc": item.ifsc,
        "status": item.status,
        "notes": item.notes,
    }


def list_payslips(db: Session, organization_id: int = None, search: str = None,
                   period: str = None, employee_id: int = None) -> List[dict]:
    query = db.query(PayslipItem, PayrollRun).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
    query = _apply_org_filter(query, PayslipItem, organization_id)
    if period:
        query = query.filter(PayrollRun.period_label == period)
    if employee_id:
        query = query.filter(PayslipItem.employee_id == employee_id)
    if search:
        query = query.filter(PayslipItem.employee_name.ilike(f"%{search}%"))

    rows = query.order_by(PayrollRun.pay_date.desc()).all()
    country = _resolve_org_country(db, organization_id)
    return [_serialize_payslip(item, run, country=country) for item, run in rows]


def get_payslip_by_id(db: Session, payslip_id: int, organization_id: int = None) -> dict:
    query = db.query(PayslipItem, PayrollRun).join(PayrollRun, PayslipItem.payroll_run_id == PayrollRun.id)
    query = query.filter(PayslipItem.id == payslip_id)
    query = _apply_org_filter(query, PayslipItem, organization_id)
    row = query.first()
    if not row:
        raise NotFoundException(f"Payslip {payslip_id} not found.")
    item, run = row
    country = _resolve_org_country(db, organization_id)
    return _serialize_payslip(item, run, country=country), item, run


def _get_currency_symbol(country: str) -> str:
    """Return the currency symbol for a jurisdiction country code."""
    return {
        "IN": "\u20b9", "US": "$", "UK": "\u00a3",
        "AU": "A$", "DE": "\u20ac", "CA": "C$",
    }.get(country, "$")


def _get_currency_code(country: str) -> str:
    """Return the ISO currency code for a jurisdiction country code."""
    return {
        "IN": "INR", "US": "USD", "UK": "GBP",
        "AU": "AUD", "DE": "EUR", "CA": "CAD",
    }.get(country, "USD")


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

    country = _normalize_country(getattr(company, "jurisdiction_country", None) or "IN")
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
        ("Special Allowance", data["specialAllowance"]),
    ]
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
    # `tds` field (India-named historically) — label it per-country so a
    # German/Australian/etc. payslip doesn't say "TDS", a purely Indian term.
    income_tax_labels = {
        "US": "Federal Income Tax", "UK": "Income Tax (PAYE)",
        "AU": "Income Tax (PAYG)", "DE": "Income Tax (Lohnsteuer)",
        "CA": "Federal Income Tax",
    }
    pf_esi_labels = {
        "DE": {"pf": "Pension Insurance", "esi": "Social Insurance (Health / Unemployment / Care)"},
        "CA": {"esi": "Employment Insurance (EI)"},
    }.get(country, {})
    for lbl, key in [
        (income_tax_labels.get(country, "Income Tax (TDS)"), "tds"),
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
    ]:
        v = float(data.get(key, 0) or 0)
        if v > 0:
            deduction_items.append((lbl, v))
    empl_labels = {
        "DE": {"employerPf": "Employer Pension Insurance", "employerEsi": "Employer Social Insurance"},
        "CA": {"employerSs": "Employer CPP Contribution", "employerEsi": "Employer EI Contribution"},
        "AU": {"employerPension": "Superannuation (Employer)"},
    }.get(country, {})
    for lbl, key in [
        (empl_labels.get("employerPf", "Employer PF"), "employerPf"),
        (empl_labels.get("employerEsi", "Employer ESI"), "employerEsi"),
        (empl_labels.get("employerSs", "Employer Social Security"), "employerSs"),
        ("Employer Medicare", "employerMedicare"),
        (empl_labels.get("employerPension", "Employer Pension"), "employerPension"),
    ]:
        v = float(data.get(key, 0) or 0)
        if v > 0:
            deduction_items.append((lbl, v))
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

    emp_rows = [
        [("Employee Name", data["employee"]), ("Employee ID", str(data["employeeId"]))],
        [("Department", data["department"] or "-"), ("Designation", data.get("designation") or "-")],
        [("Date of Joining", fmt_date(data.get("dateOfJoining"))), ("PAN / Tax ID", data["pan"] or "-")],
        [("UAN", data.get("uan") or "-"), ("Bank", data.get("bankName") or "-")],
        [("Account No.", mask_account(data["bankAccount"])), ("IFSC", data.get("ifsc") or "-")],
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
    doc = db.query(ComplianceDocument).filter(
        ComplianceDocument.id == document_id,
        ComplianceDocument.organization_id == organization_id,
    ).first()
    if not doc:
        raise NotFoundException("Compliance document", document_id)

    if _os.path.exists(doc.file_path):
        _os.remove(doc.file_path)

    db.delete(doc)
    db.commit()
    log_activity(db, organization_id, f"Compliance document '{doc.title}' deleted.", ActivityStatus.INFO)


def _ocr_image_file(file_path: str) -> str:
    # NOTE: previously this caught every exception (including a missing
    # `pytesseract`/`PIL` package or a missing system `tesseract` binary)
    # and returned "", which was indistinguishable from "OCR ran and found
    # no statutory rates in the image." Letting it raise means
    # upload_compliance_document() now records a real "failed" status +
    # error message instead of silently pretending extraction succeeded.
    from PIL import Image  # type: ignore
    import pytesseract  # type: ignore

    image = Image.open(file_path)
    try:
        text = pytesseract.image_to_string(image)
    finally:
        image.close()
    return text or ""


def _extract_text_from_uploaded_document(file_path: str) -> str:
    if not file_path:
        return ""

    ext = _os.path.splitext(file_path)[1].lower()
    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    if ext == ".csv":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    if ext in {".pdf"}:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(file_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        return _ocr_image_file(file_path)
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
    _os.makedirs(_COMPLIANCE_DOC_UPLOAD_DIR, exist_ok=True)

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

    return row


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
# social-insurance fields reuse pf/esi; every country's income-tax
# withholding reuses tds) — so the register and the payslip never disagree
# about which underlying column backs which country's statutory line.
# Fields not computed for a country (e.g. professional_tax reused as US
# "State Tax"/Canada "Provincial Tax") render as 0 until state/provincial
# tax calculation is added — same field-reuse-over-new-columns approach used
# throughout this module.
_STATUTORY_COLUMNS_BY_COUNTRY = {
    "IN": [("PF", "pf", 13), ("ESI", "esi", 11), ("Prof. Tax", "professional_tax", 12), ("TDS", "tds", 13)],
    "US": [("Fed. Tax", "tds", 14), ("State Tax", "professional_tax", 14), ("Soc. Security", "social_security", 18), ("Medicare", "medicare", 13)],
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
    sym = _get_currency_symbol(country)

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
        "US": "Federal Income Tax", "UK": "Income Tax (PAYE)",
        "AU": "Income Tax (PAYG)", "DE": "Income Tax (Lohnsteuer)",
        "CA": "Federal Income Tax",
    }
    pf_esi_labels = {
        "DE": {"pf": "Pension Insurance", "esi": "Social Insurance (Health / Unemployment / Care)"},
        "CA": {"esi": "Employment Insurance (EI)"},
    }.get(country, {})
    deduction_fields = [
        (income_tax_labels.get(country, "Income Tax (TDS)"), "tds"),
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