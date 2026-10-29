"""
modules/payroll/south_africa_service.py
---------------------------------------
South Africa statutory workflows (ZP-ZA-ENG-001) — the ONLY South Africa
service module, on the shared platform the same way Saudi Arabia's
saudi_arabia_service.py and Hong Kong's hong_kong_service.py are. "ZA" is
South Africa; "SA" in this repository is Saudi Arabia.

Scope: seeding the canonical ZA-PAYROLL-2027 Draft pack from
engine/countries/south_africa_content.py, plus the Phase 4 workflows that need
persistence rather than the pure engine:
  * tax directives (ZA-007) — capture with evidence, FOUR-EYES approval, revoke,
    and the APPROVED-in-force lookup the engine applies;
  * the ETI ledger (ZA-010) — the qualifying-month history, one row per employee
    per claim month, a content hash, and reversal-plus-replacement instead of
    edits.
The platform hooks (calc_inputs, run preflight, pack activation refusal,
retention, service-registry transition) are added with the engine and are
registered in jurisdiction_hooks._MODULES only then — until that point
nothing on the shared platform reaches this module.
"""

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

ZA = "ZA"
SPEC = "ZP-ZA-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"
DIRECTIVE_TYPES = ("FIXED_PERCENTAGE", "FIXED_AMOUNT", "LUMP_SUM", "OTHER")
ETI_LEDGER_STATUSES = ("CALCULATED", "CLAIMED")
EMPLOYMENT_TYPES = ("STANDARD", "NON_STANDARD")
TAX_RESIDENCIES = ("RESIDENT", "NON_RESIDENT")

ZA_COMPONENT_BY_PAY_KEY = {
    "bonus": "BONUS",
    "commission": "COMMISSION",
    "leave_payout": "LEAVE_PAYOUT",
    "travel_allowance": "TRAVEL_FIXED",
    "reimbursive_travel": "TRAVEL_REIMBURSIVE",
    "fringe_benefit": "FRINGE_BENEFIT",
}


def seed_south_africa_pack(db: Session, *, effective_from: date = date(2026, 3, 1),
                           status: str = "Draft") -> "JurisdictionPack":
    """Write south_africa_content.py into the ZA-PAYROLL-2027 tax pack:
      * one SourceArtifact per evidence-register entry (S1–S14), reused if present;
      * every scalar parameter (ContributionRate) with its real value in the
        slot its kind names (employee/employer pct, flat_amount, text_value)
        and its own legal effective_from / effective_to where it has one;
      * every PAYE band (TaxSlab rule_type="ZA_PAYE_BAND");
      * every ETI band (TaxSlab rule_type="ZA_ETI_BAND", filing_status =
        qualifying period, tax_regime = formula);
      * every earning-classification row (TaxSlab rule_type="ZA_EARNING_CLASS",
        filing_status = component, tax_regime = obligation,
        assessment_basis = treatment; tax_table_number left empty until the
        BRS source-code catalogue is archived).

    Draft by default; a pack that has left Draft is never rewritten, and a
    Draft pack's canonical rows are replaced wholesale from the content."""
    from app.modules.payroll.engine.countries import south_africa_content as content
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    if status != "Draft":
        raise ValueError("seed_south_africa_pack only writes Draft content")
    pack_id, window_from, window_to = content.ZA_2027
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")

    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-ZA-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form,
                                      source_url=content.SOURCE_URLS.get(code))
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id

    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=ZA, pack_type="tax",
                                effective_from=effective_from or window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_to = window_to
    pack.tax_year = content.TAX_YEAR
    pack.currency = content.CURRENCY
    pack.regulatory_authority = "SARS / Department of Employment and Labour"
    pack.source_document_id = sources["S1"]
    # Canonical rows only: org-scoped rows (organization_id IS NOT NULL) are an
    # organisation's overrides and are never deleted by a re-seed.
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.organization_id.is_(None)).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None)).delete()

    def dec(value):
        return Decimal(str(value)) if value is not None else None

    def pending(label, flag, limit):
        return (label + (PENDING_G1_SUFFIX if flag else ""))[:limit]

    order = 0
    for (key, label, ee, er, flat, text, src, is_pending, eff_from, eff_to) in content.ZA_SCALAR_CONTENT:
        order += 1
        ee_shown = f"{ee}%" if ee is not None else "—"
        er_shown = f"{er}%" if er is not None else "—"
        if ee is not None or er is not None:
            total = " / ".join(s for s in (ee_shown, er_shown) if s != "—")
        elif text is None and flat is None:
            # Empty by design (content.ZA_EMPTY_BY_DESIGN): the specification gives
            # no value, so the row exists only to make "not configured" explicit.
            total = "NOT CONFIGURED"
        else:
            total = text if text is not None else str(flat)
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=ZA,
            component_key=key, label=pending(label, is_pending, 100),
            employee_share=ee_shown[:50], employer_share=er_shown[:50], total=total[:50],
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er),
            flat_amount=dec(flat), text_value=text,
            effective_from=eff_from, effective_to=eff_to,
            source_document_id=sources.get(src), sort_order=order))

    for (lo, hi, rate, base, label, src) in content.ZA_PAYE_BANDS:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=ZA,
            rule_type=content.ZA_PAYE_BAND_RULE,
            min_amount=dec(lo), max_amount=dec(hi), rate_pct=dec(rate), flat_amount=dec(base),
            rate_label=f"{Decimal(rate).normalize():f}%"[:150], tax_formula=label[:150],
            source_document_id=sources.get(src), sort_order=order))

    for (period, formula, lo, hi, rate, flat, label, src) in content.ZA_ETI_BANDS:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=ZA,
            rule_type=content.ZA_ETI_BAND_RULE,
            min_amount=dec(lo), max_amount=dec(hi),
            rate_pct=dec(rate) if rate is not None else Decimal("0"), flat_amount=dec(flat),
            rate_label=pending(label, True, 150), tax_formula=f"ETI {period}: {formula}"[:150],
            filing_status=period, tax_regime=formula,
            source_document_id=sources.get(src), sort_order=order))

    for (obligation, treatment, component, label, src) in content.ZA_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=ZA,
            rule_type=content.ZA_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=label[:150], tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))

    db.flush()
    return pack


# ── shared validation helpers ───────────────────────────────────────────────
def _as_date(value, field: str):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise BadRequestException(f"{field} must be an ISO date (YYYY-MM-DD).")


def _money(value, field: str):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{field} must be a decimal amount.")


def _month_start(value, field: str = "claimMonth") -> date:
    on = _as_date(value, field)
    return date(on.year, on.month, 1)


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)


def _content_hash(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _employee_or_refuse(db: Session, organization_id: int, employee_id: int):
    from app.modules.payroll.models import PayrollEmployee

    employee = (db.query(PayrollEmployee)
                .filter(PayrollEmployee.id == employee_id,
                        PayrollEmployee.organization_id == organization_id)
                .first())
    if employee is None:
        raise BadRequestException(f"employee #{employee_id} does not belong to organisation "
                                  f"#{organization_id}.")
    return employee


# ── tax directives (ZA-007) ─────────────────────────────────────────────────
def capture_za_directive(db: Session, *, organization_id: int, employee_id: int, directive_number: str,
                         directive_type: str, tax_year: str, issue_date, effective_from,
                         effective_to=None, rate_pct=None, amount=None, instruction: str = None,
                         evidence_artifact_id: int = None, evidence_sha256: str = None,
                         actor_id: int = None):
    """Record a SARS directive as CAPTURED with its evidence. Nothing here
    overrides PAYE: only an APPROVED directive in force for the employee, tax
    year and pay date is applied by the engine. The number is unique per
    organisation; a directive carries either a rate or an amount, never both."""
    from app.modules.payroll.models import PayrollZaTaxDirective

    _employee_or_refuse(db, organization_id, employee_id)
    number = (directive_number or "").strip()
    if not number:
        raise BadRequestException("A tax directive needs its SARS directive number.")
    if len(number) > 30:
        raise BadRequestException("A tax directive number is at most 30 characters.")
    kind = (directive_type or "").strip().upper()
    if kind not in DIRECTIVE_TYPES:
        raise BadRequestException(f"directiveType must be one of {', '.join(DIRECTIVE_TYPES)}; "
                                  f"got {directive_type!r}.")
    year = (tax_year or "").strip()
    if not year:
        raise BadRequestException("A tax directive needs its tax year.")
    if len(year) > 10:
        raise BadRequestException("A tax directive tax year is at most 10 characters.")
    rate = _money(rate_pct, "ratePct")
    value = _money(amount, "amount")
    if kind == "FIXED_PERCENTAGE":
        if rate is None or value is not None:
            raise BadRequestException("A FIXED_PERCENTAGE directive needs ratePct and no amount.")
        if rate < 0 or rate > 100:
            raise BadRequestException("ratePct must be between 0 and 100.")
    else:
        if value is None or rate is not None:
            raise BadRequestException(f"A {kind} directive needs amount and no ratePct.")
        if value < 0:
            raise BadRequestException("A tax directive amount cannot be negative.")
    if evidence_artifact_id is None and not (evidence_sha256 or "").strip():
        raise BadRequestException("A tax directive needs its source evidence (artifact id or sha256).")
    digest = (evidence_sha256 or "").strip() or None
    if digest is not None:
        if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
            raise BadRequestException("evidenceSha256 must be 64 hexadecimal characters.")
        digest = digest.lower()

    issued = _as_date(issue_date, "issueDate")
    starts = _as_date(effective_from, "effectiveFrom")
    ends = _as_date(effective_to, "effectiveTo") if effective_to is not None else None
    if ends is not None and ends < starts:
        raise BadRequestException("effectiveTo cannot be before effectiveFrom.")

    duplicate = (db.query(PayrollZaTaxDirective)
                 .filter(PayrollZaTaxDirective.organization_id == organization_id,
                         PayrollZaTaxDirective.directive_number == number)
                 .first())
    if duplicate is not None:
        raise BadRequestException(f"Tax directive {number!r} is already recorded for this organisation.")

    row = PayrollZaTaxDirective(
        organization_id=organization_id, employee_id=employee_id, directive_number=number,
        directive_type=kind, rate_pct=rate, amount=value, tax_year=year, issue_date=issued,
        effective_from=starts, effective_to=ends,
        instruction=(instruction or None), evidence_artifact_id=evidence_artifact_id,
        evidence_sha256=digest, status="CAPTURED", created_by_id=actor_id)
    db.add(row)
    db.flush()
    return row


def _za_directive_or_404(db: Session, directive_id: int, organization_id: Optional[int] = None):
    from app.modules.payroll.models import PayrollZaTaxDirective

    row = db.query(PayrollZaTaxDirective).filter(PayrollZaTaxDirective.id == directive_id).first()
    if row is None or (organization_id is not None and row.organization_id != organization_id):
        raise NotFoundException("PayrollZaTaxDirective", directive_id)
    return row


def approve_za_directive(db: Session, directive_id: int, *, approver_id: int,
                         organization_id: Optional[int] = None):
    """Four-eyes (ZA-007): only a CAPTURED directive can be approved, and the
    approver must differ from the operator who captured it."""
    from app.modules.payroll.models import PayrollZaTaxDirective

    row = _za_directive_or_404(db, directive_id, organization_id)
    if row.status != "CAPTURED":
        raise BadRequestException(f"Tax directive {row.id} is {row.status}; only a CAPTURED directive "
                                  "can be approved.")
    if approver_id is None or row.created_by_id == approver_id:
        raise BadRequestException("The same operator cannot approve their own tax directive (four-eyes).")
    row.status = "APPROVED"
    row.approved_by_id = approver_id
    row.approved_at = datetime.utcnow()
    db.flush()
    return row


def revoke_za_directive(db: Session, directive_id: int, *, actor_id: int = None,
                        organization_id: Optional[int] = None):
    """Remove a directive from the in-force lookup. Revocation is a status
    change, never a delete: the captured evidence stays on record."""
    from app.modules.payroll.models import PayrollZaTaxDirective

    row = _za_directive_or_404(db, directive_id, organization_id)
    if row.status != "REVOKED":
        row.status = "REVOKED"
        db.flush()
    return row


def list_za_directives(db: Session, organization_id: int, employee_id: int) -> list:
    from app.modules.payroll.models import PayrollZaTaxDirective

    _employee_or_refuse(db, organization_id, employee_id)
    rows = (db.query(PayrollZaTaxDirective)
            .filter(PayrollZaTaxDirective.organization_id == organization_id,
                    PayrollZaTaxDirective.employee_id == employee_id)
            .order_by(PayrollZaTaxDirective.id.desc())
            .all())
    return [{c.name: getattr(r, c.name) for c in PayrollZaTaxDirective.__table__.columns}
            for r in rows]


def za_directives_in_force(db: Session, employee_id: int, on) -> list:
    """The APPROVED directives covering `on` for one employee, as plain dicts
    the engine's fail-closed `apply_directive` re-validates. The employee and
    window filters here are a convenience; the engine never trusts them alone."""
    from app.modules.payroll.models import PayrollZaTaxDirective

    day = _as_date(on, "on")
    rows = (db.query(PayrollZaTaxDirective)
            .filter(PayrollZaTaxDirective.employee_id == employee_id,
                    PayrollZaTaxDirective.status == "APPROVED",
                    PayrollZaTaxDirective.effective_from <= day,
                    or_(PayrollZaTaxDirective.effective_to.is_(None),
                        PayrollZaTaxDirective.effective_to >= day))
            .order_by(PayrollZaTaxDirective.id)
            .all())
    return [{
        "id": r.id, "employee_id": r.employee_id, "directive_number": r.directive_number,
        "directive_type": r.directive_type, "rate_pct": r.rate_pct, "amount": r.amount,
        "tax_year": r.tax_year, "issue_date": r.issue_date, "effective_from": r.effective_from,
        "effective_to": r.effective_to, "status": r.status, "instruction": r.instruction,
        "evidence_artifact_id": r.evidence_artifact_id, "evidence_sha256": r.evidence_sha256,
        "applied_payslip_item_id": r.applied_payslip_item_id,
    } for r in rows]


# ── ETI ledger (ZA-010) ─────────────────────────────────────────────────────
def za_next_eti_month_no(db: Session, employee_id: int, claim_month) -> int:
    """The next qualifying month for the employee, counting prior CALCULATED /
    CLAIMED rows only. A month that already has a live row is refused; the
    unique index is the database backstop for the same rule."""
    from app.modules.payroll.models import PayrollZaEtiLedgerEntry

    target = _month_start(claim_month)
    live = (db.query(PayrollZaEtiLedgerEntry)
            .filter(PayrollZaEtiLedgerEntry.employee_id == employee_id,
                    PayrollZaEtiLedgerEntry.claim_month == target,
                    PayrollZaEtiLedgerEntry.status != "REVERSED")
            .first())
    if live is not None:
        raise BadRequestException(f"ETI for employee #{employee_id} in {target:%Y-%m} is already recorded "
                                  f"(ledger entry #{live.id}).")
    count = (db.query(PayrollZaEtiLedgerEntry)
             .filter(PayrollZaEtiLedgerEntry.employee_id == employee_id,
                     PayrollZaEtiLedgerEntry.status.in_(ETI_LEDGER_STATUSES),
                     PayrollZaEtiLedgerEntry.claim_month < target)
             .count())
    return count + 1


def record_za_eti_entry(db: Session, *, organization_id: int, employee_id: int, claim_month,
                        eti_result: dict, payroll_run_id: int = None, payslip_item_id: int = None,
                        actor_id: int = None, reverses_id: int = None):
    """Persist one ELIGIBLE ETI result for one claim month. The engine's result
    is the source of every figure; a non-ELIGIBLE result is never recorded as
    a claim. Corrections are a REVERSED original plus a new row (`reverses_id`),
    never an edit, and the canonical result hash stays stable."""
    from app.modules.payroll.models import PayrollZaEtiLedgerEntry

    result = eti_result or {}
    if (result.get("status") or "").upper() != "ELIGIBLE":
        raise BadRequestException("Only an ELIGIBLE ETI result can be recorded in the ledger.")
    _employee_or_refuse(db, organization_id, employee_id)
    target = _month_start(claim_month)
    month_no = result.get("qualifyingMonthNo")
    if month_no is None:
        raise BadRequestException("The ETI result has no qualifying month number.")
    month_no = int(month_no)
    if month_no < 1:
        raise BadRequestException("The ETI qualifying month number must be at least 1.")
    hours = _money(result.get("paidHours"), "paidHours")
    remuneration = _money(result.get("remuneration"), "remuneration")
    normalised = _money(result.get("normalisedRemuneration"), "normalisedRemuneration")
    amount = _money(result.get("amount"), "amount")
    missing = [name for name, value in (("paidHours", hours), ("remuneration", remuneration),
                                       ("normalisedRemuneration", normalised), ("amount", amount))
               if value is None]
    if missing:
        raise BadRequestException(f"The ETI result is missing {', '.join(missing)}.")
    if min(hours, remuneration, normalised, amount) < 0:
        raise BadRequestException("ETI ledger amounts cannot be negative.")
    live = (db.query(PayrollZaEtiLedgerEntry)
            .filter(PayrollZaEtiLedgerEntry.employee_id == employee_id,
                    PayrollZaEtiLedgerEntry.claim_month == target,
                    PayrollZaEtiLedgerEntry.status != "REVERSED")
            .first())
    if live is not None:
        raise BadRequestException(f"ETI for employee #{employee_id} in {target:%Y-%m} is already recorded "
                                  f"(ledger entry #{live.id}); reverse it before recording a replacement.")

    row = PayrollZaEtiLedgerEntry(
        organization_id=organization_id, employee_id=employee_id, claim_month=target,
        qualifying_month_no=month_no, paid_hours=hours, remuneration=remuneration,
        normalised_remuneration=normalised, eti_amount=amount,
        content_hash=_content_hash(result), status="CALCULATED",
        payroll_run_id=payroll_run_id, payslip_item_id=payslip_item_id,
        reverses_id=reverses_id, created_by_id=actor_id)
    db.add(row)
    db.flush()
    return row


def reverse_za_eti_entry(db: Session, entry_id: int, *, actor_id: int = None,
                         organization_id: Optional[int] = None):
    """Mark a ledger row REVERSED. The row and its content hash remain; the
    month is freed for a replacement row that points back at it."""
    from app.modules.payroll.models import PayrollZaEtiLedgerEntry

    row = db.query(PayrollZaEtiLedgerEntry).filter(PayrollZaEtiLedgerEntry.id == entry_id).first()
    if row is None or (organization_id is not None and row.organization_id != organization_id):
        raise NotFoundException("PayrollZaEtiLedgerEntry", entry_id)
    if row.status != "REVERSED":
        row.status = "REVERSED"
        db.flush()
    return row
# ══════════════════════════════════════════════════════════════════════════
# Employee scope and statutory profile (ZA-005)
# ══════════════════════════════════════════════════════════════════════════

def _za_employee(db: Session, employee_id: int, organization_id: int):
    from app.modules.payroll.models import PayrollEmployee

    employee = (db.query(PayrollEmployee)
                .filter(PayrollEmployee.id == employee_id,
                        PayrollEmployee.organization_id == organization_id)
                .first())
    if employee is None:
        raise BadRequestException(f"employee #{employee_id} does not belong to organisation "
                                  f"#{organization_id}.")
    if (employee.country_code or "").upper() != ZA:
        raise BadRequestException(f"employee #{employee_id} is not a South Africa employee")
    return employee


ZA_PROFILE_COLUMNS = (
    "za_employment_type", "za_tax_residency", "za_is_director",
    "za_medical_scheme_member", "za_medical_dependants", "za_travel_business_use_80",
    "za_uif_excluded", "za_uif_exclusion_reason", "za_eti_eligible",
    "za_eti_first_qualifying_month", "za_sez_employee", "za_voluntary_additional_paye",
    "za_evidence_ref",
)


def _za_statutory_profile_errors(data) -> list:
    errors = []
    employment = (getattr(data, "za_employment_type", None) or "").strip().upper()
    if employment and employment not in EMPLOYMENT_TYPES:
        errors.append(f"za_employment_type must be one of {', '.join(EMPLOYMENT_TYPES)}.")
    residency = (getattr(data, "za_tax_residency", None) or "").strip().upper()
    if residency and residency not in TAX_RESIDENCIES:
        errors.append(f"za_tax_residency must be one of {', '.join(TAX_RESIDENCIES)}.")
    dependants = getattr(data, "za_medical_dependants", None)
    if dependants is not None and (dependants < 0 or dependants > 20):
        errors.append("za_medical_dependants must be between 0 and 20.")
    if getattr(data, "za_medical_scheme_member", None) is True and dependants is None:
        errors.append("za_medical_dependants is required when the employee is a medical scheme member.")
    if getattr(data, "za_uif_excluded", None) is True and not (
            (getattr(data, "za_uif_exclusion_reason", None) or "").strip()):
        errors.append("za_uif_exclusion_reason is required when UIF is excluded.")
    voluntary = getattr(data, "za_voluntary_additional_paye", None)
    if voluntary is not None and voluntary < 0:
        errors.append("za_voluntary_additional_paye cannot be negative.")
    if getattr(data, "za_sez_employee", None) is True:
        errors.append("za_sez_employee is outside the certified South Africa scope (SEZ ETI is deferred).")
    return errors


def _za_profile_values(db: Session, employee, data, previous) -> dict:
    sent = data.model_fields_set
    values = {}
    for col in ZA_PROFILE_COLUMNS:
        if col in sent:
            value = getattr(data, col)
            if col in ("za_employment_type", "za_tax_residency"):
                value = (value or "").strip().upper() or None
            values[col] = value
        elif previous is not None and (previous.country_code or "").upper() == ZA:
            values[col] = getattr(previous, col)
    return values


# ══════════════════════════════════════════════════════════════════════════
# Employer registrations (ZA-011)
# ══════════════════════════════════════════════════════════════════════════

import re

_PAYE_REFERENCE = re.compile(r"^7\d{9}$")
_UIF_REFERENCE = re.compile(r"^U\d{9}$")
_SDL_REFERENCE = re.compile(r"^L\d{9}$")
_COIDA_REFERENCE = re.compile(r"^[A-Za-z0-9 /.-]{6,30}$")


def _field(data, name, default=None):
    if isinstance(data, dict):
        return data.get(name, default)
    return getattr(data, name, default)


def _za_registration_or_404(db: Session, registration_id: int, organization_id: Optional[int] = None):
    from app.modules.payroll.models import PayrollZaEmployerRegistration

    row = (db.query(PayrollZaEmployerRegistration)
           .filter(PayrollZaEmployerRegistration.id == registration_id).first())
    if row is None or (organization_id is not None and row.organization_id != organization_id):
        raise NotFoundException("PayrollZaEmployerRegistration", registration_id)
    return row


def list_za_employer_registrations(db: Session, organization_id: int) -> list:
    from app.modules.payroll.models import PayrollZaEmployerRegistration

    return (db.query(PayrollZaEmployerRegistration)
            .filter(PayrollZaEmployerRegistration.organization_id == organization_id)
            .order_by(PayrollZaEmployerRegistration.effective_from.desc(),
                      PayrollZaEmployerRegistration.id.desc())
            .all())


def get_za_employer_registration(db: Session, organization_id: int, as_of=None):
    from app.modules.payroll.models import PayrollZaEmployerRegistration

    on = _as_date(as_of, "asOf") if as_of is not None else date.today()
    return (db.query(PayrollZaEmployerRegistration)
            .filter(PayrollZaEmployerRegistration.organization_id == organization_id,
                    PayrollZaEmployerRegistration.status == "ACTIVE",
                    PayrollZaEmployerRegistration.effective_from <= on,
                    or_(PayrollZaEmployerRegistration.effective_to.is_(None),
                        PayrollZaEmployerRegistration.effective_to >= on))
            .order_by(PayrollZaEmployerRegistration.effective_from.desc())
            .first())


def _za_journal_accounts(raw) -> Optional[dict]:
    """The employer's chart-of-accounts map for the ZA journal (spec §10): only
    the known account keys, each a non-blank account code. Absent -> None (the
    journal then BLOCKS rather than using a default account)."""
    from app.modules.payroll.south_africa_journal import ACCOUNT_KEYS

    if raw in (None, {}):
        return None
    if not isinstance(raw, dict):
        raise BadRequestException("journalAccounts must be an object of account key -> account code.")
    unknown = sorted(set(raw) - set(ACCOUNT_KEYS))
    if unknown:
        raise BadRequestException(f"journalAccounts has unknown key(s) {unknown}; allowed: {list(ACCOUNT_KEYS)}.")
    blank = sorted(k for k, v in raw.items() if not str(v or "").strip())
    if blank:
        raise BadRequestException(f"journalAccounts has blank account code(s) for {blank}.")
    return {k: str(v).strip()[:40] for k, v in raw.items()}


def create_za_employer_registration(db: Session, organization_id: int, data, actor_id: Optional[int] = None):
    from app.modules.payroll.models import PayrollZaEmployerRegistration

    paye = (_field(data, "paye_reference") or _field(data, "payeReference") or "").strip().upper()
    if not _PAYE_REFERENCE.match(paye):
        raise BadRequestException("payeReference must be a 10-digit SARS PAYE reference starting with 7.")
    uif = (_field(data, "uif_reference") or _field(data, "uifReference") or "").strip().upper() or None
    if uif is not None and not _UIF_REFERENCE.match(uif):
        raise BadRequestException("uifReference must be U followed by 9 digits.")
    sdl = (_field(data, "sdl_reference") or _field(data, "sdlReference") or "").strip().upper() or None
    if sdl is not None and not _SDL_REFERENCE.match(sdl):
        raise BadRequestException("sdlReference must be L followed by 9 digits.")
    coida = (_field(data, "coida_reference") or _field(data, "coidaReference") or "").strip() or None
    if coida is not None and not _COIDA_REFERENCE.match(coida):
        raise BadRequestException("coidaReference must be 6-30 letters, digits, spaces or / . -")
    sdl_liable = _field(data, "sdl_liable", _field(data, "sdlLiable"))
    if sdl_liable is None:
        raise BadRequestException("sdlLiable is required.")
    sdl_liable = bool(sdl_liable)
    reason = (_field(data, "sdl_exemption_reason") or _field(data, "sdlExemptionReason") or "").strip() or None
    if not sdl_liable and reason is None:
        raise BadRequestException("sdlExemptionReason is required when the employer is not SDL-liable.")
    if sdl_liable and reason is not None:
        raise BadRequestException("sdlExemptionReason is only valid when the employer is not SDL-liable.")
    starts = _as_date(_field(data, "effective_from", _field(data, "effectiveFrom")), "effectiveFrom")
    ends_raw = _field(data, "effective_to", _field(data, "effectiveTo"))
    ends = _as_date(ends_raw, "effectiveTo") if ends_raw is not None else None
    if ends is not None and ends < starts:
        raise BadRequestException("effectiveTo cannot be before effectiveFrom.")
    accounts = _za_journal_accounts(_field(data, "za_journal_accounts", _field(data, "journalAccounts")))

    row = PayrollZaEmployerRegistration(
        organization_id=organization_id, effective_from=starts, effective_to=ends,
        paye_reference=paye, uif_reference=uif, sdl_reference=sdl, coida_reference=coida,
        sdl_liable=sdl_liable, sdl_exemption_reason=reason,
        eti_registered=bool(_field(data, "eti_registered", _field(data, "etiRegistered")) or False),
        sector_code=(_field(data, "sector_code", _field(data, "sectorCode")) or None),
        bargaining_council=(_field(data, "bargaining_council", _field(data, "bargainingCouncil")) or None),
        evidence_ref=(_field(data, "evidence_ref", _field(data, "evidenceRef")) or None),
        source_document_id=_field(data, "source_document_id", _field(data, "sourceDocumentId")),
        za_journal_accounts=accounts, status="DRAFT", created_by_id=actor_id)
    db.add(row)
    db.flush()
    return row


def approve_za_employer_registration(db: Session, registration_id: int, *, approver_id: int,
                                      organization_id: Optional[int] = None):
    from app.modules.payroll.models import PayrollZaEmployerRegistration

    row = _za_registration_or_404(db, registration_id, organization_id)
    if row.status != "DRAFT":
        raise BadRequestException(f"Registration {row.id} is {row.status}; only a DRAFT registration can be approved.")
    if approver_id is None or row.created_by_id == approver_id:
        raise BadRequestException("The same operator cannot approve their own employer registration (four-eyes).")

    active = (db.query(PayrollZaEmployerRegistration)
              .filter(PayrollZaEmployerRegistration.organization_id == row.organization_id,
                      PayrollZaEmployerRegistration.status == "ACTIVE",
                      PayrollZaEmployerRegistration.id != row.id)
              .first())
    if active is not None:
        if row.effective_from <= active.effective_from:
            raise BadRequestException(
                "A new employer registration must start after the currently active registration.")
        active.effective_to = row.effective_from - timedelta(days=1)
        active.status = "SUPERSEDED"
        row.previous_version_id = active.id

    row.status = "ACTIVE"
    row.approved_by_id = approver_id
    row.approved_at = datetime.utcnow()
    db.flush()
    return row


# ══════════════════════════════════════════════════════════════════════════
# Calculation inputs
# ══════════════════════════════════════════════════════════════════════════

def _za_first_qualifying_month_no(profile, claim_month: date) -> Optional[int]:
    first = getattr(profile, "za_eti_first_qualifying_month", None) if profile is not None else None
    if first is None:
        return None
    if isinstance(first, datetime):
        first = first.date()
    return (claim_month.year - first.year) * 12 + (claim_month.month - first.month) + 1


def _za_has_tax_number(employee) -> bool:
    fields = getattr(employee, "compliance_fields", None) or {}
    return bool(fields.get("tax_number") or fields.get("za_tax_number") or fields.get("income_tax_number"))


def _za_compliance_value(employee, *keys):
    fields = getattr(employee, "compliance_fields", None) or {}
    for key in keys:
        if fields.get(key) not in (None, ""):
            return fields[key]
    return None


def _za_hours(db: Session, employee, period_start: date, period_end: date) -> Optional[dict]:
    from app.modules.payroll import south_africa_lifecycle as lifecycle

    return lifecycle.za_hours(db, employee, period_start, period_end)


def _za_deduction_orders(db: Session, employee, on: date) -> Optional[list]:
    from app.modules.payroll import south_africa_lifecycle as lifecycle

    return lifecycle.za_deduction_orders(db, employee, on)


def _za_overrides_for(db: Session, employee, run, on: date) -> Optional[list]:
    from app.modules.payroll import south_africa_lifecycle as lifecycle

    return lifecycle.za_overrides_for(db, employee, run, on)


def resolve_za_calc_inputs(db: Session, organization_id: int, employee, as_of: Optional[date] = None,
                            run=None) -> dict:
    from app.modules.payroll import service

    on = as_of or date.today()
    period_start = getattr(run, "period_start", None) or date(on.year, on.month, 1)
    period_end = getattr(run, "period_end", None) or on
    profile = service.resolve_employee_statutory_profile(db, employee.id, organization_id, on)
    if profile is not None and (profile.country_code or "").upper() != ZA:
        profile = None
    registration = get_za_employer_registration(db, organization_id, on)
    claim_month = date(on.year, on.month, 1)
    qualifying_no = _za_first_qualifying_month_no(profile, claim_month)
    if qualifying_no is None and getattr(profile, "za_eti_eligible", None) is True:
        from app.modules.payroll.models import PayrollZaEtiLedgerEntry
        qualifying_no = (db.query(PayrollZaEtiLedgerEntry)
                         .filter(PayrollZaEtiLedgerEntry.employee_id == employee.id,
                                 PayrollZaEtiLedgerEntry.status.in_(ETI_LEDGER_STATUSES),
                                 PayrollZaEtiLedgerEntry.claim_month < claim_month)
                         .count() + 1)
    components = _za_compliance_value(employee, "za_components")
    if not isinstance(components, dict):
        components = None
    variable_items = _za_compliance_value(employee, "za_variable_items")
    if not isinstance(variable_items, list):
        variable_items = None
    paid_hours = _za_compliance_value(employee, "za_eti_paid_hours", "eti_paid_hours")
    retirement = _za_compliance_value(employee, "za_retirement_fund_contribution",
                                     "retirement_fund_contribution")
    return {
        "za_statutory_profile": profile,
        "za_organization_id": organization_id,
        "za_employee_id": employee.id,
        "za_employer_registration": registration,
        "za_has_tax_number": _za_has_tax_number(employee),
        "za_components": components,
        "za_retirement_fund_contribution": retirement,
        "za_directives": za_directives_in_force(db, employee.id, on),
        "za_variable_items": variable_items,
        "za_eti_paid_hours": paid_hours,
        "za_eti_qualifying_month_no": qualifying_no,
        # Phase 9 (spec §5, ZA-013, ZA-017) — plain JSON-safe values only.
        "za_hours": _za_hours(db, employee, period_start, period_end),
        "za_deduction_orders": _za_deduction_orders(db, employee, on),
        "za_overrides": _za_overrides_for(db, employee, run, on),
    }


def calc_inputs(db: Session, run=None, employee=None, resolved_pack=None, as_of: Optional[date] = None) -> dict:
    on = as_of or getattr(run, "pay_date", None) or date.today()
    return resolve_za_calc_inputs(db, employee.organization_id, employee, on, run=run)


# ══════════════════════════════════════════════════════════════════════════
# Run-approval preflight
# ══════════════════════════════════════════════════════════════════════════

def _za_run_has_payslips(db: Session, run) -> bool:
    from app.modules.payroll.models import PayslipItem

    return (db.query(PayslipItem.id)
            .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == ZA)
            .first() is not None)


def _za_before_run_transition(db: Session, run, next_status, actor_id) -> None:
    from fastapi import HTTPException, status as http_status

    from app.modules.payroll.models import PayrollStatus, PayslipItem

    if not _za_run_has_payslips(db, run):
        return
    if next_status == PayrollStatus.APPROVED:
        missing = (db.query(PayslipItem.id)
                   .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == ZA,
                           PayslipItem.za_calculation_snapshot.is_(None))
                   .count())
        if missing:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                f"South Africa: {missing} payslip(s) have no frozen ZA calculation snapshot - "
                "recalculate the run before approval."))
        from app.modules.payroll import south_africa_lifecycle as lifecycle

        lifecycle.before_approval(db, run, actor_id)
    elif next_status == PayrollStatus.PAID:
        from app.modules.payroll import south_africa_lifecycle as lifecycle

        lifecycle.commit_run(db, run, actor_id)


# ══════════════════════════════════════════════════════════════════════════
# Service registry, retention and owner decisions
# ══════════════════════════════════════════════════════════════════════════

def transition_za_service_registry(db: Session, target: str, reason: str,
                                   actor_id: Optional[int] = None, as_of: Optional[date] = None):
    from app.modules.payroll import service, south_africa_readiness

    def readiness():
        unmet = south_africa_readiness.ga_preconditions(db)
        unmet_list = [u for u in unmet if not u.get("met")]
        return unmet_list, {u["key"]: u["detail"] for u in unmet_list}

    return service.transition_service_registry(
        db, ZA, target, reason, actor_id, label="South Africa", readiness=readiness,
        invalid_target_message=lambda t: (
            f"South Africa availability can only be {service.SERVICE_REGISTRY_OPEN} or "
            f"{service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no South Africa registry row - seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"South Africa is {a}; only PLANNED moves to AVAILABLE.")


ZA_RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and the frozen ZA calculation trace"),
    ("SARS_RECORDS", "PAYE / UIF / SDL / ETI records and SARS submissions"),
    ("DIRECTIVES", "SARS tax directives and their evidence"),
    ("EMPLOYEE_IDENTITY", "Identity, tax number and statutory profile data"),
    ("LABOUR_RECORDS", "Leave, hours and labour-law records"),
    ("ACCESS_LOGS", "South Africa access events and download logs"),
    ("CORRECTIONS", "Payslip corrections and their evidence"),
)

ZA_DECISIONS = {
    "D-1": ("Retention period per data category", True),
    "D-2": ("Deletion vs anonymisation at end of retention", True),
    "D-3": ("South Africa payroll-run approval four-eyes", True),
    "D-4": ("Parallel-cycle materiality threshold (rand per employee per concept)", True),
    "D-5": ("POPIA posture and data location (hosting region, cross-border transfer basis)", True),
    "D-6": ("Values or 'not applicable' for the deliberately empty rows: BCEA overtime / Sunday / public-holiday multipliers, damage-deduction limit, four-eyes variable-pay % and bank-change window", True),
    "D-7": ("ETI treatment: EMP201 offset policy (za_eti_offset_policy) and accounting (incentive income vs reduction of PAYE payable)", True),
}


def _reviewed_by_other(artifact) -> bool:
    return bool(artifact is not None and artifact.reviewer_id and artifact.file_path is not None
                and artifact.reviewer_id != artifact.created_by_id)


def _evidence(db: Session, tag: str):
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact)
            .filter(SourceArtifact.form_number == tag, SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    return next((r for r in rows if _reviewed_by_other(r)), None), bool(rows)


def owner_decisions(db: Session) -> list:
    out = []
    for key, (label, blocks) in ZA_DECISIONS.items():
        accepted, submitted = _evidence(db, f"ZA-DECISION-{key}")
        out.append({"key": key, "label": label, "blocksLaunch": blocks,
                    "evidenceTag": f"ZA-DECISION-{key}",
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


def _decision_state(db: Session, key: str) -> str:
    return next((d["state"] for d in owner_decisions(db) if d["key"] == key), "OPEN")


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    from app.modules.payroll.models import PayrollZaEtiLedgerEntry, PayrollZaTaxDirective

    for model, label in ((PayrollZaTaxDirective, "tax directives"),
                         (PayrollZaEtiLedgerEntry, "ETI ledger entries")):
        if db.query(model.id).filter(model.employee_id == employee_id).first():
            return label
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    from app.modules.payroll.models import EmployeeStatutoryProfile

    return (db.query(EmployeeStatutoryProfile.id)
            .filter(EmployeeStatutoryProfile.employee_id == employee_id,
                    EmployeeStatutoryProfile.country_code == ZA)
            .first() is not None)


def is_za_report(report) -> bool:
    return bool(report is not None
                and (str(getattr(report, "jurisdiction_country", "") or "").upper() == ZA
                     or str(getattr(report, "report_type", "") or "").startswith("ZA_")))


def retention_settings():
    from app.modules.payroll import retention_service

    return retention_service.RetentionJurisdiction(
        country=ZA, label="South Africa", categories=ZA_RETENTION_CATEGORIES,
        period_decision="D-1", end_decision="D-2", decision_reference="ZA-DECISION-D-1",
        decision_state=_decision_state,
        validate_employee=lambda db, employee_id, organization_id: _za_employee(
            db, employee_id, organization_id),
        retained_record_label=_retained_record_label, has_statutory_profile=_has_statutory_profile,
        report_matches=is_za_report, audit_spec=SPEC)


def za_activation_evidence_refusal(db: Session, pack) -> Optional[str]:
    from app.modules.payroll.models import ContributionRate, TaxSlab

    marker = "%[PENDING G1]%"
    pending_rates = (db.query(ContributionRate)
                     .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                             ContributionRate.organization_id.is_(None),
                             or_(ContributionRate.label.like(marker),
                                 ContributionRate.text_value == "PENDING_G1"))
                     .count())
    pending_slabs = (db.query(TaxSlab)
                     .filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None),
                             TaxSlab.rate_label.like(marker))
                     .count())
    if pending_rates or pending_slabs:
        return (f"{pending_rates + pending_slabs} South Africa pack row(s) are still PENDING G1 - "
                "they must be signed at gate G1 before the pack can be activated")
    return None


def statutory_editors(db: Session, pack) -> set:
    return set()


def template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    """Phase 8 (ZA-015/018): a template that would feed a SARS reconciliation or
    certificate export cannot go live while the BRS source-code catalogue for
    the configured version is empty — the export would have to guess codes."""
    from app.modules.payroll.engine.countries import south_africa_content as content

    report_type = str(getattr(template, "report_type", "") or "").upper()
    if not (report_type.startswith("ZA_EMP501") or report_type.startswith("ZA_IRP5")):
        return None
    version = next((row[5] for row in content.ZA_SCALAR_CONTENT if row[0] == "za_brs_version"), None)
    if not (content.ZA_BRS_CATALOG.get(version) or {}).get("source_codes"):
        return (f"South Africa: SARS PAYE BRS v{version} source-code catalogue is not archived (evidence S4) - "
                f"{report_type} templates stay inactive until it is.")
    return None


def _za_pack_holidays(db: Session, year: int) -> list:
    from app.modules.payroll import south_africa_lifecycle as lifecycle

    return lifecycle.za_public_holidays(year)


def payment_treatment(db: Session, organization_id: int, run, items: list) -> dict:
    return {}


def _za_payslip_hold_view(item) -> Optional[dict]:
    return None


def statutory_summary(db: Session) -> dict:
    from app.modules.payroll import south_africa_readiness
    from app.modules.payroll.models import (JurisdictionPack, PayrollZaEtiLedgerEntry,
                                            PayrollZaEmployerRegistration, PayrollZaTaxDirective)

    packs = (db.query(JurisdictionPack)
             .filter(JurisdictionPack.jurisdiction_country == ZA,
                     JurisdictionPack.pack_type == "tax")
             .order_by(JurisdictionPack.effective_from.desc()).all())
    registrations = (db.query(PayrollZaEmployerRegistration)
                     .filter(PayrollZaEmployerRegistration.status == "ACTIVE").count())
    directives = (db.query(PayrollZaTaxDirective)
                  .filter(PayrollZaTaxDirective.status == "APPROVED").count())
    eti_entries = (db.query(PayrollZaEtiLedgerEntry)
                   .filter(PayrollZaEtiLedgerEntry.status.in_(ETI_LEDGER_STATUSES)).count())
    gates = south_africa_readiness.gate_states(db)
    signed_gates = sum(1 for g in gates if g.get("state") == "SIGNED")
    return {
        "jurisdiction": ZA, "spec": SPEC, "available": False,
        "packs": [{"id": p.id, "packId": p.pack_id, "version": p.version, "status": p.status,
                   "effectiveFrom": _iso_date(p.effective_from), "effectiveTo": _iso_date(p.effective_to)}
                  for p in packs],
        "activeEmployerRegistrations": registrations,
        "approvedDirectives": directives,
        "liveEtiEntries": eti_entries,
        "decisions": owner_decisions(db),
        "gates": gates,
        "signedGates": signed_gates,
        "gateChecklists": south_africa_readiness.gate_checklists(db),
        "gaPreconditions": south_africa_readiness.ga_preconditions(db),
        "codeChecks": south_africa_readiness.code_check_rows(db),
        "noGo": list(south_africa_readiness.NO_GO),
        "openPoints": south_africa_readiness.open_points(),
        "documents": {"releaseGates": "docs/south-africa/release-gates/README.md"},
        "note": f"South Africa remains PLANNED; activation gates G0–G7 are not yet evidenced ({signed_gates}/8 signed).",
    }


# ══════════════════════════════════════════════════════════════════════════
# Frozen calculation context and payslip snapshot
# ══════════════════════════════════════════════════════════════════════════

def _iso_date(value) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


_ZA_CTX_DECIMALS = ("gross", "basic", "hra", "special_allowance", "overtime",
                    "additional_compensation")
_ZA_CTX_PLAIN = ("pay_frequency", "za_organization_id", "za_employee_id", "za_has_tax_number",
                 "za_components", "za_retirement_fund_contribution", "za_directives",
                 "za_variable_items", "za_eti_paid_hours", "za_eti_qualifying_month_no",
                 "za_hours", "za_deduction_orders", "za_overrides",
                 "unpaid_leave_days", "date_of_joining")
# date_of_birth: the age rebates and ETI age test need it, so a replay without it BLOCKS.
_ZA_CTX_DATES = ("pay_date", "period_start", "period_end", "date_of_birth")
_ZA_RATE_FIELDS = ("employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value",
                   "effective_from", "effective_to")
# flat_amount: the PAYE band's base tax and the ETI flat amount — a replay without it cannot compute.
_ZA_SLAB_FIELDS = ("rule_type", "filing_status", "tax_regime", "assessment_basis", "rate_pct",
                   "employer_rate_pct", "min_amount", "max_amount", "flat_amount", "rate_label",
                   "effective_from", "effective_to")
_ZA_REGISTRATION_FIELDS = ("id", "sdl_liable", "sdl_exemption_reason", "eti_registered",
                           "effective_from", "effective_to")


def _za_profile_facts(profile) -> Optional[dict]:
    if profile is None:
        return None
    return {n: getattr(profile, n, None) for n in ZA_PROFILE_COLUMNS}


def _za_registration_facts(registration) -> Optional[dict]:
    if registration is None:
        return None
    return {n: getattr(registration, n, None) for n in _ZA_REGISTRATION_FIELDS}


def za_freeze_context(ctx, calculation_mode: str = "standard") -> dict:
    return _json_safe({
        "version": 1, "calculationMode": calculation_mode,
        "ctx": {k: getattr(ctx, k, None) for k in _ZA_CTX_DECIMALS + _ZA_CTX_PLAIN + _ZA_CTX_DATES},
        "profile": _za_profile_facts(getattr(ctx, "za_statutory_profile", None)),
        "registration": _za_registration_facts(getattr(ctx, "za_employer_registration", None)),
        "rateMap": {k: {f: getattr(r, f, None) for f in _ZA_RATE_FIELDS}
                    for k, r in (getattr(ctx, "rate_map", None) or {}).items()},
        "slabs": [{f: getattr(s, f, None) for f in _ZA_SLAB_FIELDS}
                  for s in (getattr(ctx, "slabs", None) or [])],
    })


def _dec_or_none(value):
    return Decimal(str(value)) if value not in (None, "") else None


def _date_or_none(value):
    return date.fromisoformat(str(value)[:10]) if value not in (None, "") else None


def za_thaw_context(frozen: dict):
    from types import SimpleNamespace

    from app.modules.payroll.engine.base import PayrollContext

    c = frozen.get("ctx") or {}
    rate_map = {}
    for k, v in (frozen.get("rateMap") or {}).items():
        view = dict(v)
        for f in ("employee_rate_pct", "employer_rate_pct", "flat_amount"):
            view[f] = _dec_or_none(view.get(f))
        view["effective_from"], view["effective_to"] = (
            _date_or_none(view.get("effective_from")), _date_or_none(view.get("effective_to")))
        rate_map[k] = SimpleNamespace(**view)
    slabs = []
    for s in frozen.get("slabs") or []:
        view = dict(s)
        for f in ("rate_pct", "employer_rate_pct", "min_amount", "max_amount", "flat_amount"):
            view[f] = _dec_or_none(view.get(f))
        view["effective_from"], view["effective_to"] = (
            _date_or_none(view.get("effective_from")), _date_or_none(view.get("effective_to")))
        slabs.append(SimpleNamespace(**view))
    ctx = PayrollContext(
        gross=Decimal(str(c.get("gross") or 0)), basic=Decimal(str(c.get("basic") or 0)),
        country=ZA, rate_map=rate_map, slabs=slabs,
        pay_frequency=c.get("pay_frequency") or "Monthly")
    for k in _ZA_CTX_DECIMALS[2:]:
        setattr(ctx, k, Decimal(str(c.get(k) or 0)))
    for k in _ZA_CTX_DATES:
        setattr(ctx, k, _date_or_none(c.get(k)))
    for k in _ZA_CTX_PLAIN:
        if c.get(k) is not None:
            setattr(ctx, k, c.get(k))
    profile = frozen.get("profile")
    ctx.za_statutory_profile = SimpleNamespace(**profile) if profile is not None else None
    registration = frozen.get("registration")
    ctx.za_employer_registration = (SimpleNamespace(**registration)
                                    if registration is not None else None)
    return ctx


ZA_TOTAL_KEYS = ("za_paye", "za_uif_employee", "za_uif_employer", "za_sdl",
                 "za_retirement_contribution", "za_eti_amount")


def za_totals_all(result) -> dict:
    r = getattr(result, "za_result", None) if not isinstance(result, dict) else result
    return {k: str((r or {}).get(k) or "0") for k in ZA_TOTAL_KEYS}


def za_payslip_snapshot(result, frozen: Optional[dict] = None) -> Optional[dict]:
    r = getattr(result, "za_result", None)
    if not r:
        return None
    snap = {**r, "totalsAll": za_totals_all(r)}
    if frozen is not None:
        snap["frozenContext"] = frozen
    return _json_safe(snap)


def mark_za_directive_applied(db: Session, payslip_item, result) -> None:
    from app.modules.payroll.models import PayrollZaTaxDirective

    r = getattr(result, "za_result", None) or {}
    applied = ((r.get("trace") or {}).get("directive") or {}).get("applied") or {}
    directive_id = applied.get("id")
    if not directive_id:
        return
    row = db.query(PayrollZaTaxDirective).filter(PayrollZaTaxDirective.id == directive_id).first()
    if row is not None:
        row.applied_payslip_item_id = payslip_item.id
        db.flush()


def list_za_eti_ledger(db: Session, organization_id: int, employee_id: Optional[int] = None) -> list:
    from app.modules.payroll.models import PayrollZaEtiLedgerEntry

    query = (db.query(PayrollZaEtiLedgerEntry)
             .filter(PayrollZaEtiLedgerEntry.organization_id == organization_id))
    if employee_id is not None:
        _za_employee(db, employee_id, organization_id)
        query = query.filter(PayrollZaEtiLedgerEntry.employee_id == employee_id)
    return query.order_by(PayrollZaEtiLedgerEntry.claim_month.desc(),
                          PayrollZaEtiLedgerEntry.id.desc()).all()


JURISDICTION_HOOKS = {
    "calc_inputs": "calc_inputs",
    "before_run_transition": "_za_before_run_transition",
    "statutory_profile_errors": "_za_statutory_profile_errors",
    "statutory_profile_values": "_za_profile_values",
    "pack_activation_refusal": "za_activation_evidence_refusal",
    "retention_settings": "retention_settings",
    "service_registry_transition": "transition_za_service_registry",
    "statutory_summary": "statutory_summary",
    "statutory_editors": "statutory_editors",
    "template_activation_refusal": "template_activation_refusal",
    "pack_holidays": "_za_pack_holidays",
    "payment_treatment": "payment_treatment",
    "payslip_hold_view": "_za_payslip_hold_view",
}
