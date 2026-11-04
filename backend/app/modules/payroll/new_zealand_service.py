"""
modules/payroll/new_zealand_service.py
--------------------------------------
New Zealand statutory workflows (ZP-NZ-ENG-001) — the ONLY New Zealand service
module, on the shared platform the same way japan_service.py is.

Phase 1: seeding the canonical NZ-PAYROLL-2026-27 Draft pack (and the empty
NZ-ELA-2028 staging pack) from engine/countries/new_zealand_content.py, and the
pack activation refusal.

Phase 4: versioned statutory records with a second person's approval (NZ-020,
NZ-024), the IRD-number vault workflow, calculation inputs selected by the
payday (NZ-008), frozen snapshots and replay (NZ-005/022), run approval and
year-to-date posting (NZ-013), and the 13 platform hooks registered in
jurisdiction_hooks._MODULES.
"""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

NZ = "NZ"
SPEC = "ZP-NZ-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"


def _ensure_sources(db: Session, content) -> dict:
    from app.modules.payroll.models import SourceArtifact

    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-NZ-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form,
                                      source_url=content.SOURCE_URLS.get(code))
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id
    return sources


def _draft_pack(db: Session, pack_id: str, window_from: date, window_to: Optional[date]):
    from app.modules.payroll.models import JurisdictionPack

    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")
    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=NZ, pack_type="tax",
                                effective_from=window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_from = window_from
    pack.effective_to = window_to
    return pack


def seed_nz_pack(db: Session, *, status: str = "Draft") -> "JurisdictionPack":
    """Write new_zealand_content.py into the NZ-PAYROLL-2026-27 tax pack:
      * one SourceArtifact per evidence-register entry (S1–S10), reused if present;
      * every scalar parameter (ContributionRate) with its value in the slot
        its kind names and its own legal effective_from / effective_to;
      * the PAYE and ESCT bands (TaxSlab NZ_PAYE_BAND / NZ_ESCT_BAND);
      * the tax-code catalogue (TaxSlab NZ_TAX_CODE);
      * every earning-classification row (TaxSlab NZ_EARNING_CLASS).
    The authority tables the specification does not reproduce
    (content.NZ_EMPTY_TABLES) write no rows: they are filled from archived
    artefacts at their gate, and until then the engine BLOCKS. Every row is
    labelled PENDING G1.

    Also writes the Employment Leave Act 2026 staging pack NZ-ELA-2028 as an
    EMPTY Draft (spec §8, AC-NZ-08); nz_pack_activation_refusal keeps it
    from ever being activated before 6 August 2028.

    Draft only; a pack that has left Draft is never rewritten, and a Draft
    pack's canonical rows are replaced wholesale from the content."""
    from app.modules.payroll.engine.countries import new_zealand_content as content
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if status != "Draft":
        raise ValueError("seed_nz_pack only writes Draft content")
    pack_id, window_from, window_to = content.NZ_2026_27
    pack = _draft_pack(db, pack_id, window_from, window_to)
    sources = _ensure_sources(db, content)
    pack.tax_year = content.TAX_YEAR
    pack.currency = content.CURRENCY
    pack.regulatory_authority = "Inland Revenue / Employment New Zealand / ACC"
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
    for (key, label, ee, er, flat, text, src, is_pending, eff_from, eff_to) in content.NZ_SCALAR_CONTENT:
        order += 1
        if text is None and flat is None:
            # Empty by design (content.NZ_EMPTY_BY_DESIGN): the specification gives
            # no value, so the row exists only to make "not configured" explicit.
            total = "NOT CONFIGURED"
        elif content.NZ_PARAMETER_KEYS[key] == "pct_total":
            total = f"{flat}%"
        else:
            total = text if text is not None else str(flat)
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=NZ,
            component_key=key, label=pending(label, is_pending, 100),
            employee_share="—", employer_share="—", total=total[:50],
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er),
            flat_amount=dec(flat), text_value=text,
            effective_from=eff_from, effective_to=eff_to,
            source_document_id=sources.get(src), sort_order=order))

    for rule_type, bands, src, what in ((content.NZ_PAYE_BAND_RULE, content.NZ_PAYE_BANDS, "S3", "PAYE band"),
                                        (content.NZ_ESCT_BAND_RULE, content.NZ_ESCT_BANDS, "S3", "ESCT band")):
        for low, high, rate in bands:
            order += 1
            span = f"over {low}" + (f" to {high}" if high is not None else "")
            db.add(TaxSlab(
                jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=NZ,
                rule_type=rule_type, min_amount=dec(low), max_amount=dec(high), rate_pct=dec(rate),
                rate_label=pending(f"{what} {span}: {rate}%", True, 150), tax_formula=f"{what} {span}"[:150],
                effective_from=window_from, effective_to=window_to,
                source_document_id=sources.get(src), sort_order=order))

    for code, income_class, code_status, student_loan, ietc, label in content.NZ_TAX_CODES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=NZ,
            rule_type=content.NZ_TAX_CODE_RULE, min_amount=Decimal("0"), max_amount=None,
            rate_pct=Decimal("0"), rate_label=pending(f"{code}: {label}", True, 150),
            tax_formula=f"{code} {income_class} {code_status}"[:150],
            filing_status=code, tax_regime=income_class, assessment_basis=code_status,
            tax_column="SL" if student_loan else None, tax_table_number="IETC" if ietc else None,
            source_document_id=sources.get("S1"), sort_order=order))

    for (obligation, treatment, component, label, src) in content.NZ_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=NZ,
            rule_type=content.NZ_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=pending(label, True, 150), tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))

    ela_id, ela_from, ela_to = content.NZ_ELA_2028
    ela = _draft_pack(db, ela_id, ela_from, ela_to)
    ela.regulatory_authority = "Employment New Zealand"
    ela.source_document_id = sources["S8"]
    ela.change_summary = ("Employment Leave Act 2026 staging pack — empty; cannot be activated before "
                          f"{content.ELA_EARLIEST_EFFECTIVE.isoformat()} (ZP-NZ-ENG-001 §8, AC-NZ-08).")
    db.flush()
    return pack


# ── shared validation helpers ───────────────────────────────────────────────
def nz_pack_activation_refusal(db: Session, pack, actor_id: Optional[int] = None,
                               today: Optional[date] = None) -> Optional[str]:
    """Why a New Zealand pack may not be activated, or None.

    * NZ-ELA-2028 (Employment Leave Act 2026): never before 6 August 2028
      (AC-NZ-08), and never while it holds no signed content.
    * Any NZ pack: refused while a canonical row is still PENDING G1, or while
      an authority table the engine needs (content.NZ_EMPTY_TABLES) has no
      rows (gate G1/G2)."""
    from app.modules.payroll.engine.countries import new_zealand_content as content
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if pack is None or (pack.jurisdiction_country or "").upper() != NZ:
        return None
    today = today or date.today()
    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                              ContributionRate.organization_id.is_(None))
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                     TaxSlab.organization_id.is_(None))
    ela_id, _from, _to = content.NZ_ELA_2028
    if pack.pack_id == ela_id:
        if today < content.ELA_EARLIEST_EFFECTIVE:
            return (f"{ela_id} (Employment Leave Act 2026) cannot be activated before "
                    f"{content.ELA_EARLIEST_EFFECTIVE.isoformat()}; the Holidays Act 2003 stays in force until then")
        if not rates.count() and not slabs.count():
            return f"{ela_id} holds no signed content and cannot be activated"
    marker = f"%{PENDING_G1_SUFFIX.strip()}%"
    pending_rows = (rates.filter(ContributionRate.label.like(marker)).count()
                    + slabs.filter(TaxSlab.rate_label.like(marker)).count())
    if pending_rows:
        return (f"{pending_rows} New Zealand pack row(s) are still PENDING G1 - "
                "they must be signed at gate G1 before the pack can be activated")
    if pack.pack_id != ela_id:
        missing = [name for name, table in content.NZ_EMPTY_TABLES.items()
                   if not table.get("employer_content")
                   and not slabs.filter(TaxSlab.rule_type == table["rule_type"]).count()]
        if missing:
            return ("New Zealand authority tables are empty: " + ", ".join(sorted(missing))
                    + " — they are filled from archived authority evidence at their release gate")
    return None


# ======================================================================
# New Zealand Phase 4: statutory records, IRD vault, calculation inputs,
# frozen snapshots, run binding and platform hooks
# ======================================================================

STATUS_DRAFT, STATUS_ACTIVE, STATUS_SUPERSEDED = "DRAFT", "ACTIVE", "SUPERSEDED"
REGULAR = "REGULAR"
OPENING_REQUEST = "nz_opening_balance_request"
OPENING_DECIDED = "nz_opening_balance_decided"
ACCUMULATOR_OBLIGATIONS = ("ACC_LIABLE_EARNINGS", "PAYE_GROSS", "PAYE", "ACC_LEVY", "KS_GROSS", "KS_EMPLOYEE",
                           "KS_EMPLOYER_GROSS", "ESCT", "STUDENT_LOAN", "CHILD_SUPPORT")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _nz_models():
    from app.modules.payroll import models as m

    return m


def _content():
    from app.modules.payroll.engine.countries import new_zealand_content as content

    return content


# ── shared helpers ──────────────────────────────────────────────────────────
def _as_date(value, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise BadRequestException(f"{field} must be an ISO date (YYYY-MM-DD).")


def _as_datetime(value, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise BadRequestException(f"{field} must be an ISO date-time.")


def _money(value, field: str) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{field} must be a decimal amount.")


def _nz_bool(value, field: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise BadRequestException(f"{field} must be true or false.")


def _nz_reason(reason) -> str:
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("A reason is required for every New Zealand statutory change (NZ-024).")
    return text[:300]


def _nz_audit(db: Session, actor_id, action: str, entity_type: str, entity_id: int, old=None, new=None,
              reason: Optional[str] = None) -> None:
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     old_value=old, new_value=new, reason=reason, legal_reference=SPEC, auto_commit=False)


def _nz_employee(db: Session, organization_id: int, employee_id: int):
    from app.modules.payroll.models import PayrollEmployee

    employee = (db.query(PayrollEmployee)
                .filter(PayrollEmployee.id == employee_id, PayrollEmployee.organization_id == organization_id)
                .first())
    if employee is None:
        raise NotFoundException("New Zealand employee")
    return employee


def _nz_legal_entity(db: Session, organization_id: int, legal_entity_id) -> None:
    if legal_entity_id is None:
        return
    from app.modules.organizations.models import LegalEntity

    found = (db.query(LegalEntity.id)
             .filter(LegalEntity.id == legal_entity_id, LegalEntity.organization_id == organization_id).first())
    if found is None:
        raise NotFoundException("Legal entity in this organisation")


def _nz_enum(data: dict, key: str, allowed) -> None:
    value = data.get(key)
    if value is None:
        return
    value = str(value).strip().upper()
    if value not in allowed:
        raise BadRequestException(f"{key} must be one of: {', '.join(allowed)}.")
    data[key] = value


def _facts(row) -> Optional[dict]:
    """Plain-value dict of a model row (the engine reads dicts)."""
    if row is None:
        return None
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _in_force(query, model, on: date):
    return query.filter(model.effective_from <= on,
                        (model.effective_to.is_(None)) | (model.effective_to >= on))


def _nz_pack_in_force(db: Session, on: date):
    """(rate_map, slabs, pack) of the NZ pack in force on `on`, or (None, None, None)."""
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    try:
        rates, slabs, pack = resolve_tax_configuration(db, NZ, payroll_date=on)
    except Exception:  # an unresolvable pack is "no pack"; the engine blocks on its own
        return None, None, None
    if pack is None:
        return None, None, None
    return {r.component_key: r for r in rates}, slabs, pack


# ── field whitelists (anything else is refused; the server owns status) ────
NZ_EMPLOYER_FIELDS = (
    "effective_from", "effective_to", "legal_entity_id", "legal_name", "filing_method",
    "filing_method_evidence_ref", "annual_paye_esct_basis", "annual_paye_esct_amount", "remittance_class",
    "connected_business_group_ref", "connected_business_evidence_ref", "acc_classification_unit",
    "acc_metadata", "timezone", "bank_mandate_ref", "filing_credential_ref", "source_document_id",
    "evidence_ref")
NZ_TAX_PROFILE_FIELDS = (
    "effective_from", "effective_to", "legal_entity_id", "ird_number_state", "tax_code", "tax_code_source",
    "declaration_received_on", "declaration_ref", "residency_status", "tailored_certificate_ref",
    "tailored_rate_pct", "tailored_valid_from", "tailored_valid_to", "sl_certificate_type",
    "sl_certificate_ref", "sl_certificate_rate_pct", "sl_certificate_valid_from", "sl_certificate_valid_to",
    "min_wage_category", "min_wage_evidence_ref", "evidence_ref")
NZ_KIWISAVER_FIELDS = (
    "effective_from", "effective_to", "legal_entity_id", "membership_state", "enrolment_route",
    "opt_out_evidence_ref", "employee_rate_pct", "employer_rate_pct", "reduction_ref", "reduction_from",
    "reduction_to", "employer_matches_reduction", "suspension_ref", "suspension_from", "suspension_to",
    "esct_rate_pct", "esct_basis", "esct_basis_amount", "esct_tax_year", "employer_contribution_treatment",
    "settlement_destination", "complying_fund_ref", "evidence_ref")
NZ_WORK_PATTERN_FIELDS = (
    "effective_from", "effective_to", "legal_entity_id", "pattern_type", "contracted_hours_per_week",
    "contracted_days_per_week", "weekly_schedule", "roster_cycle_weeks", "roster_schedule", "hours_source",
    "evidence_ref")
NZ_NOTICE_FIELDS = (
    "deduction_type", "notice_id", "issuer", "received_at", "effective_from", "effective_to",
    "amount_per_payday", "rate_pct", "protected_earnings_policy", "protected_earnings_amount", "reason_code",
    "legal_entity_id", "evidence_ref")

_NZ_DATE_FIELDS = {"effective_from", "effective_to", "declaration_received_on", "tailored_valid_from",
                   "tailored_valid_to", "sl_certificate_valid_from", "sl_certificate_valid_to", "reduction_from",
                   "reduction_to", "suspension_from", "suspension_to"}
_NZ_DECIMAL_FIELDS = {"annual_paye_esct_amount", "tailored_rate_pct", "sl_certificate_rate_pct",
                      "employee_rate_pct", "employer_rate_pct", "esct_rate_pct", "esct_basis_amount",
                      "contracted_hours_per_week", "contracted_days_per_week", "amount_per_payday", "rate_pct",
                      "protected_earnings_amount"}
_NZ_INT_FIELDS = {"legal_entity_id", "source_document_id", "roster_cycle_weeks"}
_NZ_BOOL_FIELDS = {"employer_matches_reduction"}
_NZ_JSON_FIELDS = {"acc_metadata", "weekly_schedule", "roster_schedule"}


def _nz_clean(payload: dict, fields, *, required=()) -> dict:
    if not isinstance(payload, dict):
        raise BadRequestException("The request body must be an object.")
    unknown = sorted(set(payload) - set(fields))
    if unknown:
        raise BadRequestException(f"unknown field(s): {', '.join(unknown)}")
    data = {}
    for key, value in payload.items():
        if value is None or value == "":
            data[key] = None
        elif key in _NZ_DATE_FIELDS:
            data[key] = _as_date(value, key)
        elif key == "received_at":
            data[key] = _as_datetime(value, key)
        elif key in _NZ_DECIMAL_FIELDS:
            data[key] = _money(value, key)
        elif key in _NZ_INT_FIELDS:
            try:
                data[key] = int(value)
            except (TypeError, ValueError):
                raise BadRequestException(f"{key} must be a whole number.")
        elif key in _NZ_BOOL_FIELDS:
            data[key] = _nz_bool(value, key)
        elif key in _NZ_JSON_FIELDS:
            if not isinstance(value, (dict, list)):
                raise BadRequestException(f"{key} must be a JSON object.")
            data[key] = value
        else:
            data[key] = str(value).strip()
    missing = [key for key in required if data.get(key) in (None, "")]
    if missing:
        raise BadRequestException(f"required field(s): {', '.join(missing)}")
    if data.get("effective_to") and data.get("effective_from") and data["effective_to"] < data["effective_from"]:
        raise BadRequestException("effective_to cannot be before effective_from.")
    return data


# ── versioned records (NZ-020) with a second person's approval (NZ-024) ─────
def _nz_scope(query, model, employee_id, legal_entity_id, entity_scoped: bool):
    if employee_id is not None:
        query = query.filter(model.employee_id == employee_id)
    if entity_scoped:
        query = query.filter(model.legal_entity_id.is_(None) if legal_entity_id is None
                             else model.legal_entity_id == legal_entity_id)
    return query


def _nz_create_version(db: Session, model, organization_id: int, employee_id: Optional[int], data: dict,
                       actor_id, label: str, reason: str, *, entity_scoped: bool = False):
    query = _nz_scope(db.query(model).filter(model.organization_id == organization_id), model, employee_id,
                      data.get("legal_entity_id"), entity_scoped)
    prior = query.order_by(model.effective_from.desc(), model.id.desc()).first()
    row = model(organization_id=organization_id, status=STATUS_DRAFT, created_by_id=actor_id,
                previous_version_id=getattr(prior, "id", None), **data)
    if employee_id is not None:
        row.employee_id = employee_id
    db.add(row)
    db.flush()
    _nz_audit(db, actor_id, "created", label, row.id,
              new={"effective_from": data["effective_from"].isoformat()}, reason=reason)
    return row


def _nz_approve_version(db: Session, model, organization_id: int, row_id: int, actor_id, label: str,
                        *, entity_scoped: bool = False):
    from app.modules.payroll.service import require_four_eyes

    row = db.query(model).filter(model.id == row_id, model.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException(f"New Zealand {label.replace('nz_', '').replace('_', ' ')}")
    if row.status != STATUS_DRAFT:
        raise BadRequestException(f"Only a DRAFT {label.replace('_', ' ')} can be approved.")
    require_four_eyes(row.created_by_id, actor_id, f"Approving a New Zealand {label.replace('_', ' ')}",
                      db=db, entity_type=label, entity_id=row.id, current_status=row.status)
    start = row.effective_from
    query = _nz_scope(db.query(model).filter(model.organization_id == organization_id,
                                             model.status == STATUS_ACTIVE, model.id != row.id),
                      model, getattr(row, "employee_id", None), row.legal_entity_id, entity_scoped)
    for old in query.all():
        if old.effective_from >= start:
            raise BadRequestException("An ACTIVE version on or after this effective date already exists.")
        if old.effective_to is None or old.effective_to >= start:
            old.effective_to = date.fromordinal(start.toordinal() - 1)
            old.status = STATUS_SUPERSEDED
    row.status = STATUS_ACTIVE
    row.approved_by_id = actor_id
    row.approved_at = datetime.utcnow()
    db.flush()
    _nz_audit(db, actor_id, "approved", label, row.id, old={"status": STATUS_DRAFT},
              new={"status": STATUS_ACTIVE, "effective_from": start.isoformat()})
    return row


def record_nz_employer_profile(db: Session, organization_id: int, payload: dict, actor_id, reason=None):
    content, m = _content(), _nz_models()
    reason = _nz_reason(reason)
    data = _nz_clean(payload, NZ_EMPLOYER_FIELDS,
                     required=("effective_from", "legal_name", "filing_method", "remittance_class"))
    _nz_enum(data, "filing_method", content.FILING_METHODS)
    _nz_enum(data, "remittance_class", content.REMITTANCE_CLASSES)
    _nz_enum(data, "annual_paye_esct_basis", ("PRIOR_YEAR", "ESTIMATE"))
    if data.get("timezone") is not None and data["timezone"] not in content.TIMEZONES:
        raise BadRequestException(f"timezone must be one of: {', '.join(content.TIMEZONES)}.")
    _nz_legal_entity(db, organization_id, data.get("legal_entity_id"))
    if data.get("connected_business_group_ref") and not data.get("connected_business_evidence_ref"):
        raise BadRequestException("A connected-business group needs its evidence reference.")
    if data.get("annual_paye_esct_amount") is not None:
        rate_map, _slabs, _pack = _nz_pack_in_force(db, data["effective_from"])
        threshold = getattr((rate_map or {}).get("nz_large_employer_threshold"), "flat_amount", None)
        if threshold is not None:
            expected = "TWICE_MONTHLY" if data["annual_paye_esct_amount"] >= Decimal(str(threshold)) else "MONTHLY"
            if data["remittance_class"] != expected:
                raise BadRequestException(
                    f"remittance_class must be {expected} for annual PAYE and ESCT of "
                    f"{data['annual_paye_esct_amount']} (the signed large-employer threshold).")
    return _nz_create_version(db, m.PayrollNzEmployerProfile, organization_id, None, data, actor_id,
                              "nz_employer_profile", reason, entity_scoped=True)


def approve_nz_employer_profile(db: Session, organization_id: int, row_id: int, actor_id):
    return _nz_approve_version(db, _nz_models().PayrollNzEmployerProfile, organization_id, row_id, actor_id,
                               "nz_employer_profile", entity_scoped=True)


def verify_nz_employer_profile(db: Session, organization_id: int, row_id: int, actor_id, outcome: str, reason):
    from app.modules.payroll.service import require_four_eyes

    m = _nz_models()
    reason = _nz_reason(reason)
    row = (db.query(m.PayrollNzEmployerProfile)
           .filter(m.PayrollNzEmployerProfile.id == row_id,
                   m.PayrollNzEmployerProfile.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("New Zealand employer profile")
    outcome = (outcome or "").strip().upper()
    if outcome not in ("VERIFIED", "REJECTED"):
        raise BadRequestException("outcome must be VERIFIED or REJECTED.")
    if row.status != STATUS_ACTIVE:
        raise BadRequestException("Only an ACTIVE employer profile can be verified.")
    if outcome == "VERIFIED" and row.employer_ird_vault_id is None:
        raise BadRequestException("The employer IRD number must be on file before verification.")
    require_four_eyes(row.created_by_id, actor_id, "Verifying a New Zealand employer profile", db=db,
                      entity_type="nz_employer_profile", entity_id=row.id, current_status=row.verification_state)
    old = row.verification_state
    row.verification_state = outcome
    db.flush()
    _nz_audit(db, actor_id, "verified", "nz_employer_profile", row.id, old={"verification_state": old},
              new={"verification_state": outcome}, reason=reason)
    return row


def record_nz_tax_profile(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id,
                          reason=None):
    content, m = _content(), _nz_models()
    reason = _nz_reason(reason)
    _nz_employee(db, organization_id, employee_id)
    data = _nz_clean(payload, NZ_TAX_PROFILE_FIELDS,
                     required=("effective_from", "ird_number_state", "tax_code", "tax_code_source"))
    _nz_enum(data, "ird_number_state", content.IRD_NUMBER_STATES)
    _nz_enum(data, "tax_code_source", content.TAX_CODE_SOURCES)
    _nz_enum(data, "residency_status", content.RESIDENCY_STATUSES)
    _nz_enum(data, "min_wage_category", content.MIN_WAGE_CATEGORIES)
    _nz_enum(data, "sl_certificate_type", ("SPECIAL_DEDUCTION_RATE", "NIL_DEDUCTION"))
    code = data["tax_code"].upper()
    if code in content.REFUSED_TAX_CODES:
        raise BadRequestException(f"Tax code {code} is outside the first New Zealand release.")
    if code not in content.SUPPORTED_TAX_CODES:
        raise BadRequestException(f"Tax code {code!r} is not a New Zealand tax code.")
    data["tax_code"] = code
    if code == "STC" and not (data.get("tailored_certificate_ref") and data.get("tailored_rate_pct") is not None
                              and data.get("tailored_valid_from")):
        raise BadRequestException("A tailored tax code needs its certificate reference, rate and start date.")
    if data.get("min_wage_category") not in (None, "ADULT") and not data.get("min_wage_evidence_ref"):
        raise BadRequestException("A starting-out, training or exemption category needs its evidence reference.")
    vault = (db.query(m.PayrollNzIrdVault)
             .filter(m.PayrollNzIrdVault.organization_id == organization_id,
                     m.PayrollNzIrdVault.employee_id == employee_id,
                     m.PayrollNzIrdVault.subject_type == "EMPLOYEE",
                     m.PayrollNzIrdVault.status == "ACTIVE").first())
    if data["ird_number_state"] == "VALID" and vault is None:
        raise BadRequestException("IRD number state VALID needs the employee's IRD number on file.")
    data["ird_vault_id"] = vault.id if vault is not None else None
    return _nz_create_version(db, m.PayrollNzEmployeeTaxProfile, organization_id, employee_id, data, actor_id,
                              "nz_tax_profile", reason)


def approve_nz_tax_profile(db: Session, organization_id: int, row_id: int, actor_id):
    return _nz_approve_version(db, _nz_models().PayrollNzEmployeeTaxProfile, organization_id, row_id, actor_id,
                               "nz_tax_profile")


def record_nz_kiwisaver_election(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id,
                                 reason=None):
    content, m = _content(), _nz_models()
    reason = _nz_reason(reason)
    _nz_employee(db, organization_id, employee_id)
    data = _nz_clean(payload, NZ_KIWISAVER_FIELDS, required=("effective_from", "membership_state"))
    _nz_enum(data, "membership_state", content.KS_MEMBERSHIP_STATES)
    _nz_enum(data, "enrolment_route", ("AUTO_ENROLLED", "OPT_IN", "EXISTING_MEMBER"))
    _nz_enum(data, "esct_basis", content.ESCT_BASES)
    _nz_enum(data, "employer_contribution_treatment", content.EMPLOYER_CONTRIBUTION_TREATMENTS)
    _nz_enum(data, "settlement_destination", content.KS_SETTLEMENT_DESTINATIONS)
    if data.get("membership_state") == "SAVINGS_SUSPENSION" and not (data.get("suspension_ref")
                                                                     and data.get("suspension_from")):
        raise BadRequestException("A savings suspension needs its reference and start date (NZ-009).")
    if bool(data.get("reduction_ref")) != bool(data.get("reduction_from")):
        raise BadRequestException("A temporary rate reduction needs both its reference and its start date.")
    if data.get("settlement_destination") == "COMPLYING_FUND" and not data.get("complying_fund_ref"):
        raise BadRequestException("A complying-fund destination needs the fund reference.")
    if data.get("employee_rate_pct") is not None:
        rate_map, _slabs, _pack = _nz_pack_in_force(db, data["effective_from"])
        allowed = getattr((rate_map or {}).get("nz_ks_employee_rates"), "text_value", None)
        if allowed and data["employee_rate_pct"] not in [Decimal(x) for x in allowed.split(",") if x.strip()]:
            raise BadRequestException(f"{data['employee_rate_pct']}% is not a standard KiwiSaver rate.")
    return _nz_create_version(db, m.PayrollNzKiwiSaverElection, organization_id, employee_id, data, actor_id,
                              "nz_kiwisaver_election", reason)


def approve_nz_kiwisaver_election(db: Session, organization_id: int, row_id: int, actor_id):
    return _nz_approve_version(db, _nz_models().PayrollNzKiwiSaverElection, organization_id, row_id, actor_id,
                               "nz_kiwisaver_election")


def record_nz_work_pattern(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id,
                           reason=None):
    m = _nz_models()
    reason = _nz_reason(reason)
    _nz_employee(db, organization_id, employee_id)
    data = _nz_clean(payload, NZ_WORK_PATTERN_FIELDS, required=("effective_from", "pattern_type", "hours_source"))
    _nz_enum(data, "pattern_type", ("FIXED", "ROSTERED", "VARIABLE"))
    _nz_enum(data, "hours_source", ("CONTRACT", "TIMESHEET", "ROSTER"))
    schedule = data.get("weekly_schedule")
    if data["pattern_type"] == "FIXED" and not schedule:
        raise BadRequestException("A fixed work pattern needs its weekly schedule.")
    if schedule is not None:
        if not isinstance(schedule, dict) or set(schedule) - set(WEEKDAYS):
            raise BadRequestException("weekly_schedule keys must be MON..SUN.")
        for day, hours in schedule.items():
            value = _money(hours, f"weekly_schedule.{day}")
            if value is None or value < 0 or value > 24:
                raise BadRequestException("weekly_schedule hours must be between 0 and 24.")
    if data["pattern_type"] == "ROSTERED" and not (data.get("roster_cycle_weeks") and data.get("roster_schedule")):
        raise BadRequestException("A rostered work pattern needs its cycle length and roster.")
    return _nz_create_version(db, m.PayrollNzWorkPatternVersion, organization_id, employee_id, data, actor_id,
                              "nz_work_pattern", reason)


def approve_nz_work_pattern(db: Session, organization_id: int, row_id: int, actor_id):
    return _nz_approve_version(db, _nz_models().PayrollNzWorkPatternVersion, organization_id, row_id, actor_id,
                               "nz_work_pattern")


# ── authority notices (NZ-010): immutable versions, hash only ──────────────
def import_nz_authority_notice(db: Session, organization_id: int, employee_id: int, meta: dict,
                               file_bytes: bytes, actor_id):
    content, m = _content(), _nz_models()
    _nz_employee(db, organization_id, employee_id)
    if not file_bytes:
        raise BadRequestException("The authority notice file is required.")
    data = _nz_clean(meta, NZ_NOTICE_FIELDS,
                     required=("deduction_type", "notice_id", "issuer", "received_at", "effective_from",
                               "protected_earnings_policy"))
    _nz_enum(data, "deduction_type", content.AUTHORITY_DEDUCTION_TYPES)
    _nz_enum(data, "issuer", ("INLAND_REVENUE", "COURT", "MSD", "OTHER_AUTHORITY"))
    _nz_enum(data, "protected_earnings_policy", ("IRD_PROTECTED_NET", "COURT_SPECIFIED", "NONE"))
    if data.get("amount_per_payday") is None and data.get("rate_pct") is None:
        raise BadRequestException("A notice needs an amount per payday or a rate.")
    if data["protected_earnings_policy"] == "COURT_SPECIFIED" and data.get("protected_earnings_amount") is None:
        raise BadRequestException("A court-specified protected amount is required.")
    _nz_legal_entity(db, organization_id, data.get("legal_entity_id"))
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    Notice = m.PayrollNzAuthorityDeduction
    latest = (db.query(Notice)
              .filter(Notice.organization_id == organization_id, Notice.employee_id == employee_id,
                      Notice.deduction_type == data["deduction_type"], Notice.notice_id == data["notice_id"])
              .order_by(Notice.version.desc()).first())
    if latest is not None and latest.file_hash == file_hash:
        return latest                                    # the same notice uploaded again
    row = Notice(organization_id=organization_id, employee_id=employee_id, created_by_id=actor_id,
                 file_hash=file_hash, version=(latest.version + 1) if latest else 1,
                 replaces_id=latest.id if latest else None, status="IMPORTED", **data)
    db.add(row)
    db.flush()
    _nz_audit(db, actor_id, "imported", "nz_authority_notice", row.id,
              new={"type": row.deduction_type, "version": row.version, "fileHash": file_hash})
    return row


def _nz_notice(db: Session, organization_id: int, row_id: int):
    m = _nz_models()
    row = (db.query(m.PayrollNzAuthorityDeduction)
           .filter(m.PayrollNzAuthorityDeduction.id == row_id,
                   m.PayrollNzAuthorityDeduction.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("New Zealand authority notice")
    return row


def approve_nz_authority_notice(db: Session, organization_id: int, row_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    row = _nz_notice(db, organization_id, row_id)
    if row.status != "IMPORTED":
        raise BadRequestException("Only an IMPORTED notice can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a New Zealand authority notice", db=db,
                      entity_type="nz_authority_notice", entity_id=row.id, current_status=row.status)
    if row.replaces_id is not None:
        replaced = _nz_notice(db, organization_id, row.replaces_id)
        if replaced.status == "APPROVED":
            replaced.status = "SUPERSEDED"
    row.status = "APPROVED"
    row.approved_by_id = actor_id
    row.approved_at = datetime.utcnow()
    db.flush()
    _nz_audit(db, actor_id, "approved", "nz_authority_notice", row.id, old={"status": "IMPORTED"},
              new={"status": "APPROVED"})
    return row


def revoke_nz_authority_notice(db: Session, organization_id: int, row_id: int, actor_id, reason):
    from app.modules.payroll.service import require_four_eyes

    reason = _nz_reason(reason)
    row = _nz_notice(db, organization_id, row_id)
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED notice can be revoked.")
    require_four_eyes(row.created_by_id, actor_id, "Revoking a New Zealand authority notice", db=db,
                      entity_type="nz_authority_notice", entity_id=row.id, current_status=row.status)
    row.status = "REVOKED"
    db.flush()
    _nz_audit(db, actor_id, "revoked", "nz_authority_notice", row.id, old={"status": "APPROVED"},
              new={"status": "REVOKED"}, reason=reason)
    return row


# ── opening balances (accumulators carried in from an incumbent payroll) ────
def request_nz_opening_balance(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id):
    from app.modules.payroll.models import TaxConfigurationAudit

    employee = _nz_employee(db, organization_id, employee_id)
    obligation = str(payload.get("obligation") or "").strip().upper()
    if obligation not in ACCUMULATOR_OBLIGATIONS:
        raise BadRequestException(f"obligation must be one of: {', '.join(ACCUMULATOR_OBLIGATIONS)}.")
    amount = _money(payload.get("amount"), "amount")
    if amount is None or amount < 0:
        raise BadRequestException("amount must be zero or more.")
    tax_year = str(payload.get("tax_year") or "").strip()
    if not tax_year:
        raise BadRequestException("tax_year is required (e.g. 2026-27).")
    evidence = str(payload.get("evidence_ref") or "").strip()
    if not evidence:
        raise BadRequestException("An opening balance needs its evidence (the incumbent payroll's figures).")
    reason = _nz_reason(payload.get("reason"))
    request = {"organizationId": organization_id, "employeeId": employee_id, "obligation": obligation,
               "amount": str(amount), "taxYear": tax_year, "evidenceRef": evidence,
               "legalEntityId": employee.legal_entity_id, "requestedBy": actor_id}
    _nz_audit(db, actor_id, "requested", OPENING_REQUEST, employee_id, new=request, reason=reason)
    db.flush()
    row = (db.query(TaxConfigurationAudit)
           .filter(TaxConfigurationAudit.entity_type == OPENING_REQUEST,
                   TaxConfigurationAudit.entity_id == employee_id)
           .order_by(TaxConfigurationAudit.id.desc()).first())
    return {"requestId": row.id, **request}


def list_nz_opening_balance_requests(db: Session, organization_id: int, employee_id: int) -> list:
    from app.modules.payroll.models import TaxConfigurationAudit

    _nz_employee(db, organization_id, employee_id)
    decided = {r.entity_id for r in db.query(TaxConfigurationAudit)
               .filter(TaxConfigurationAudit.entity_type == OPENING_DECIDED)}
    rows = (db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.entity_type == OPENING_REQUEST,
                    TaxConfigurationAudit.entity_id == employee_id).order_by(TaxConfigurationAudit.id))
    return [{"requestId": r.id, "decided": r.id in decided, **(r.new_value or {})} for r in rows
            if (r.new_value or {}).get("organizationId") == organization_id]


def approve_nz_opening_balance(db: Session, organization_id: int, request_id: int, actor_id):
    from app.modules.payroll.models import TaxConfigurationAudit
    from app.modules.payroll.service import require_four_eyes

    m = _nz_models()
    request = db.get(TaxConfigurationAudit, request_id)
    payload = (request.new_value or {}) if request is not None else {}
    if request is None or request.entity_type != OPENING_REQUEST or payload.get("organizationId") != organization_id:
        raise NotFoundException("Opening-balance request")
    if db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == OPENING_DECIDED,
                                              TaxConfigurationAudit.entity_id == request_id).first():
        raise BadRequestException("This opening balance has already been decided.")
    require_four_eyes(payload.get("requestedBy"), actor_id, "Approving a New Zealand opening balance", db=db,
                      entity_type=OPENING_REQUEST, entity_id=request_id, current_status="REQUESTED")
    _rate_map, _slabs, pack = _nz_pack_for_tax_year(db, payload["taxYear"])
    entry = m.PayrollNzAccumulatorEntry(
        organization_id=organization_id, legal_entity_id=payload.get("legalEntityId"),
        employee_id=payload["employeeId"], tax_year=payload["taxYear"], obligation=payload["obligation"],
        pay_date=pack.effective_from if pack is not None else date(int(payload["taxYear"][:4]), 4, 1),
        amount=Decimal(payload["amount"]), entry_kind="OPENING_BALANCE", evidence_ref=payload["evidenceRef"],
        created_by_id=payload.get("requestedBy"), approved_by_id=actor_id, approved_at=datetime.utcnow())
    db.add(entry)
    db.flush()
    _nz_audit(db, actor_id, "approved", OPENING_DECIDED, request_id, new={"entryId": entry.id})
    return entry


def _nz_pack_for_tax_year(db: Session, tax_year: str):
    from app.modules.payroll.models import JurisdictionPack

    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.jurisdiction_country == NZ, JurisdictionPack.tax_year == tax_year,
                    JurisdictionPack.pack_type == "tax").order_by(JurisdictionPack.id.desc()).first())
    return None, None, pack


# ── IRD-number vault (spec §13, NZ-023): masked everywhere, reveal is
# requested, approved by a second person and used once ──────────────────────
def _nz_vault(db: Session, organization_id: int, vault_id: int):
    m = _nz_models()
    row = (db.query(m.PayrollNzIrdVault)
           .filter(m.PayrollNzIrdVault.id == vault_id, m.PayrollNzIrdVault.organization_id == organization_id)
           .first())
    if row is None:
        raise NotFoundException("IRD number")
    return row


def _nz_vault_owner(row) -> str:
    from app.modules.payroll import nz_ird_number as ird

    subject = row.employee_id if row.subject_type == ird.SUBJECT_EMPLOYEE else row.legal_entity_id
    return ird.vault_owner(row.organization_id, row.subject_type, subject, row.id)


def _nz_vault_event(db: Session, row, action: str, actor_id, reason=None, purpose=None, previous_id=None):
    m = _nz_models()
    event = m.PayrollNzIrdAccessEvent(organization_id=row.organization_id, legal_entity_id=row.legal_entity_id,
                                      employee_id=row.employee_id, vault_id=row.id, actor_id=actor_id,
                                      created_by_id=actor_id, action=action, purpose=purpose,
                                      reason=(reason or None) and reason[:300], previous_version_id=previous_id)
    db.add(event)
    db.flush()
    return event


def nz_ird_view(row) -> dict:
    from app.modules.payroll import nz_ird_number as ird

    return {"id": row.id, "subjectType": row.subject_type, "employeeId": row.employee_id,
            "legalEntityId": row.legal_entity_id, "onFile": row.status == "ACTIVE",
            "masked": ird.masked() if row.status == "ACTIVE" else None, "status": row.status,
            "keyVersion": row.key_version}


def create_nz_ird_number(db: Session, organization_id: int, subject_type: str, raw, actor_id, *,
                         employee_id=None, legal_entity_id=None):
    from app.modules.payroll import nz_ird_number as ird

    m = _nz_models()
    subject_type = (subject_type or "").strip().upper()
    if subject_type == ird.SUBJECT_EMPLOYEE:
        employee = _nz_employee(db, organization_id, employee_id)
        legal_entity_id = employee.legal_entity_id
    elif subject_type == ird.SUBJECT_EMPLOYER:
        employee_id = None
        _nz_legal_entity(db, organization_id, legal_entity_id)
    else:
        raise BadRequestException("subjectType must be EMPLOYEE or EMPLOYER.")
    try:
        plain = ird.normalise(raw)
        fingerprint = ird.fingerprint(plain)
    except ird.IrdNumberError as error:
        raise BadRequestException(str(error))
    Vault = m.PayrollNzIrdVault
    if (db.query(Vault.id).filter(Vault.organization_id == organization_id, Vault.subject_type == subject_type,
                                  Vault.fingerprint == fingerprint, Vault.status == "ACTIVE").first()):
        raise BadRequestException("This IRD number is already on file in this organisation.")
    if subject_type == ird.SUBJECT_EMPLOYEE and (db.query(Vault.id).filter(
            Vault.organization_id == organization_id, Vault.employee_id == employee_id,
            Vault.subject_type == subject_type, Vault.status == "ACTIVE").first()):
        raise BadRequestException("The employee already has an IRD number on file; delete it first.")
    row = Vault(organization_id=organization_id, legal_entity_id=legal_entity_id, employee_id=employee_id,
                subject_type=subject_type, ciphertext="pending", key_version=0, fingerprint=fingerprint,
                collected_at=datetime.utcnow(), status="ACTIVE", created_by_id=actor_id)
    db.add(row)
    db.flush()
    try:
        row.ciphertext, row.key_version = ird.encrypt(plain, _nz_vault_owner(row))
    except ird.IrdNumberError as error:
        raise BadRequestException(str(error))
    db.flush()
    _nz_vault_event(db, row, "CREATE", actor_id, purpose=ird.PURPOSE)
    return row


def list_nz_ird_numbers(db: Session, organization_id: int, employee_id=None) -> list:
    m = _nz_models()
    q = db.query(m.PayrollNzIrdVault).filter(m.PayrollNzIrdVault.organization_id == organization_id)
    if employee_id is not None:
        _nz_employee(db, organization_id, employee_id)
        q = q.filter(m.PayrollNzIrdVault.employee_id == employee_id)
    return [nz_ird_view(r) for r in q.order_by(m.PayrollNzIrdVault.id)]


def _nz_last_event(db: Session, row, action: str, after_id: int = 0):
    m = _nz_models()
    Event = m.PayrollNzIrdAccessEvent
    return (db.query(Event).filter(Event.vault_id == row.id, Event.action == action, Event.id > after_id)
            .order_by(Event.id.desc()).first())


def request_nz_ird_reveal(db: Session, organization_id: int, vault_id: int, reason, actor_id):
    row = _nz_vault(db, organization_id, vault_id)
    if row.status != "ACTIVE" or not row.ciphertext:
        raise BadRequestException("The IRD number has been deleted.")
    return _nz_vault_event(db, row, "REVEAL_REQUESTED", actor_id, reason=_nz_reason(reason), purpose="REVEAL")


def approve_nz_ird_reveal(db: Session, organization_id: int, vault_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    row = _nz_vault(db, organization_id, vault_id)
    request = _nz_last_event(db, row, "REVEAL_REQUESTED")
    if request is None:
        raise BadRequestException("There is no reveal request to approve.")
    if _nz_last_event(db, row, "REVEAL_APPROVED", request.id) is not None:
        raise BadRequestException("This reveal request has already been approved.")
    require_four_eyes(request.actor_id, actor_id, "Approving an IRD-number reveal", db=db,
                      entity_type="nz_ird_access_event", entity_id=request.id, current_status="REVEAL_REQUESTED")
    return _nz_vault_event(db, row, "REVEAL_APPROVED", actor_id, reason=request.reason, purpose="REVEAL",
                           previous_id=request.id)


def reveal_nz_ird_number(db: Session, organization_id: int, vault_id: int, actor_id) -> dict:
    from app.modules.payroll import nz_ird_number as ird

    row = _nz_vault(db, organization_id, vault_id)
    if row.status != "ACTIVE" or not row.ciphertext:
        raise BadRequestException("The IRD number has been deleted.")
    request = _nz_last_event(db, row, "REVEAL_REQUESTED")
    approval = _nz_last_event(db, row, "REVEAL_APPROVED", request.id) if request is not None else None
    if request is None or approval is None:
        raise BadRequestException("A reveal needs a request and a second person's approval.")
    if _nz_last_event(db, row, "REVEALED", approval.id) is not None:
        raise BadRequestException("This approval has already been used; request a new reveal.")
    if request.actor_id != actor_id:
        raise BadRequestException("Only the person who requested the reveal can see the number.")
    try:
        number = ird.decrypt(row.ciphertext, row.key_version, _nz_vault_owner(row))
    except ird.IrdNumberError as error:
        raise BadRequestException(str(error))
    _nz_vault_event(db, row, "REVEALED", actor_id, reason=request.reason, purpose="REVEAL",
                    previous_id=approval.id)
    return {"vaultId": row.id, "irdNumber": number}


def delete_nz_ird_number(db: Session, organization_id: int, vault_id: int, actor_id, reason):
    reason = _nz_reason(reason)
    row = _nz_vault(db, organization_id, vault_id)
    if row.status == "DELETED":
        raise BadRequestException("The IRD number has already been deleted.")
    row.status = "DELETED"
    row.deleted_at = datetime.utcnow()
    row.ciphertext = None
    db.flush()
    _nz_vault_event(db, row, "DELETED", actor_id, reason=reason)
    return row


def set_nz_employer_ird(db: Session, organization_id: int, profile_id: int, raw, actor_id):
    """Put the employer IRD number on file and link it to a DRAFT employer
    profile version (an ACTIVE version is never edited: record a new one)."""
    m = _nz_models()
    profile = (db.query(m.PayrollNzEmployerProfile)
               .filter(m.PayrollNzEmployerProfile.id == profile_id,
                       m.PayrollNzEmployerProfile.organization_id == organization_id).first())
    if profile is None:
        raise NotFoundException("New Zealand employer profile")
    if profile.status != STATUS_DRAFT:
        raise BadRequestException("Link the IRD number to a DRAFT profile version (NZ-020).")
    row = create_nz_ird_number(db, organization_id, "EMPLOYER", raw, actor_id,
                               legal_entity_id=profile.legal_entity_id)
    profile.employer_ird_vault_id = row.id
    db.flush()
    return row


# ── calculation inputs (selected by the PAYDAY, NZ-008) ─────────────────────
def _nz_one_active(db: Session, model, organization_id: int, employee_id, on: date, label: str,
                   legal_entity_id=None, entity_scoped=False):
    query = _in_force(db.query(model).filter(model.organization_id == organization_id,
                                             model.status == STATUS_ACTIVE), model, on)
    if employee_id is not None:
        query = query.filter(model.employee_id == employee_id)
    if entity_scoped:
        rows = query.filter(model.legal_entity_id == legal_entity_id).all() if legal_entity_id is not None else []
        if not rows:
            rows = query.filter(model.legal_entity_id.is_(None)).all()
    else:
        rows = query.all()
    if len(rows) > 1:
        raise BadRequestException(f"Two ACTIVE New Zealand {label} versions overlap on {on.isoformat()}.")
    return rows[0] if rows else None


def _nz_tax_year(db: Session, on: date) -> Optional[str]:
    _rate_map, _slabs, pack = _nz_pack_in_force(db, on)
    return getattr(pack, "tax_year", None)


def _nz_accumulators(db: Session, organization_id: int, employee_id: int, legal_entity_id, tax_year,
                     pay_date: date) -> Optional[dict]:
    """Year-to-date sums before the payday; every obligation present (an
    explicit zero means 'known to be zero'). None when no pack is in force."""
    from sqlalchemy import func

    if tax_year is None:
        return None
    Entry = _nz_models().PayrollNzAccumulatorEntry
    query = (db.query(Entry.obligation, func.sum(Entry.amount))
             .filter(Entry.organization_id == organization_id, Entry.employee_id == employee_id,
                     Entry.tax_year == tax_year, Entry.pay_date < pay_date))
    query = query.filter(Entry.legal_entity_id.is_(None) if legal_entity_id is None
                         else Entry.legal_entity_id == legal_entity_id)
    totals = {obligation: Decimal(str(amount or 0)) for obligation, amount in query.group_by(Entry.obligation)}
    return {obligation: totals.get(obligation, Decimal("0")) for obligation in ACCUMULATOR_OBLIGATIONS}


def _nz_hours(db: Session, organization_id: int, employee_id: int, start, end, pattern):
    if start is None or end is None:
        return None, None
    from app.modules.payroll.models import PayrollAttendanceRecord as Att

    rows = (db.query(Att).filter(Att.organization_id == organization_id, Att.employee_id == employee_id,
                                 Att.date >= start, Att.date <= end).all())
    if rows:
        total = Decimal("0")
        for row in rows:
            if (row.status or "").lower() in ("absent", "leave"):
                continue
            try:
                total += Decimal(str(row.hours))
            except (InvalidOperation, ValueError, TypeError):
                return None, None                     # an unreadable record: hours are not reliable
        return total, "ATTENDANCE"
    if pattern is not None and pattern.pattern_type in ("FIXED", "ROSTERED") \
            and pattern.contracted_hours_per_week is not None:
        weeks = Decimal((end - start).days + 1) / Decimal("7")
        return (Decimal(str(pattern.contracted_hours_per_week)) * weeks).quantize(Decimal("0.01")), "WORK_PATTERN"
    return None, None


def resolve_nz_calc_inputs(db: Session, organization_id: int, employee, pay_date: date, run=None,
                           period=None) -> dict:
    """Every New Zealand input in force ON THE PAYDAY. Nothing is inferred: a
    missing record stays None and the engine refuses with its own reason."""
    m = _nz_models()
    entity = getattr(employee, "legal_entity_id", None)
    employer = _nz_one_active(db, m.PayrollNzEmployerProfile, organization_id, None, pay_date,
                              "employer profile", legal_entity_id=entity, entity_scoped=True)
    profile = _nz_one_active(db, m.PayrollNzEmployeeTaxProfile, organization_id, employee.id, pay_date,
                             "tax profile")
    kiwisaver = _nz_one_active(db, m.PayrollNzKiwiSaverElection, organization_id, employee.id, pay_date,
                               "KiwiSaver election")
    pattern = _nz_one_active(db, m.PayrollNzWorkPatternVersion, organization_id, employee.id, pay_date,
                             "work pattern")
    Notice = m.PayrollNzAuthorityDeduction
    notices = (_in_force(db.query(Notice).filter(Notice.organization_id == organization_id,
                                                 Notice.employee_id == employee.id, Notice.status == "APPROVED"),
                         Notice, pay_date)
               .order_by(Notice.deduction_type, Notice.notice_id, Notice.version).all())
    start, end = period if period else (getattr(run, "period_start", None), getattr(run, "period_end", None))
    hours, source = _nz_hours(db, organization_id, employee.id, start, end, pattern)
    kind = str(getattr(run, "nz_payment_kind", None) or REGULAR).strip().upper()
    if kind not in _content().PAYMENT_KINDS:
        raise BadRequestException(f"nz_payment_kind must be one of: {', '.join(_content().PAYMENT_KINDS)}.")
    return {
        "nz_employer_profile": _facts(employer), "nz_tax_profile": _facts(profile),
        "nz_kiwisaver": _facts(kiwisaver), "nz_work_pattern": _facts(pattern),
        "nz_authority_deductions": [_facts(n) for n in notices],
        "nz_accumulators": _nz_accumulators(db, organization_id, employee.id, entity,
                                            _nz_tax_year(db, pay_date), pay_date),
        "nz_hours": hours, "nz_hours_source": source, "nz_payment_kind": kind, "nz_pay_date": pay_date,
        "nz_date_of_birth": getattr(employee, "date_of_birth", None),
        "nz_organization_id": organization_id, "nz_legal_entity_id": entity, "nz_employee_id": employee.id,
    }


def calc_inputs(db: Session, run=None, employee=None, resolved_pack=None, as_of: Optional[date] = None,
                period=None) -> dict:
    payday = getattr(run, "pay_date", None) or as_of
    if payday is None:
        raise BadRequestException("New Zealand payroll needs the run's pay date: every rule is selected "
                                  "by the payday (NZ-008).")
    return resolve_nz_calc_inputs(db, employee.organization_id, employee, payday, run=run, period=period)


# ── frozen snapshot, replay and approval fingerprint (NZ-005/006/022) ───────
_NZ_CTX_DECIMALS = ("gross", "basic", "hra", "special_allowance", "overtime", "additional_compensation", "nz_hours")
_NZ_CTX_PLAIN = ("pay_frequency", "nz_payment_kind", "nz_hours_source", "nz_components", "nz_organization_id",
                 "nz_legal_entity_id", "nz_employee_id", "trace_id")
_NZ_CTX_DATES = ("pay_date", "nz_pay_date", "period_start", "period_end", "nz_date_of_birth", "date_of_birth")
_NZ_RECORD_KEYS = ("nz_employer_profile", "nz_tax_profile", "nz_kiwisaver", "nz_work_pattern")
_NZ_RATE_FIELDS = ("component_key", "label", "employee_rate_pct", "employer_rate_pct", "flat_amount",
                   "text_value", "effective_from", "effective_to")
_NZ_SLAB_FIELDS = ("id", "rule_type", "filing_status", "tax_regime", "assessment_basis", "tax_column",
                   "tax_table_number", "tax_formula", "formula_expression", "jurisdiction_state", "rate_label",
                   "rate_pct", "min_amount", "max_amount", "flat_amount", "sort_order", "effective_from",
                   "effective_to")
_NZ_DECIMAL_SUFFIXES = ("_pct", "_amount", "_per_payday", "_per_week")
_NZ_DECIMAL_KEYS = {"flat_amount", "min_amount", "max_amount", "rate_pct", "amount"}
_NZ_DATE_SUFFIXES = ("_from", "_to", "_on")


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


def _nz_thaw_value(key: str, value):
    if value is None or value == "" or not isinstance(value, str):
        return value
    if key in _NZ_DECIMAL_KEYS or key.endswith(_NZ_DECIMAL_SUFFIXES):
        return Decimal(value)
    if key.endswith(_NZ_DATE_SUFFIXES) or key in ("pay_date", "date_of_birth"):
        return date.fromisoformat(value[:10])
    if key == "received_at":
        return datetime.fromisoformat(value)
    return value


def _nz_thaw_row(row):
    return None if row is None else {k: _nz_thaw_value(k, v) for k, v in row.items()}


def nz_freeze_context(ctx, calculation_mode: str = "standard") -> dict:
    return _json_safe({
        "version": 1, "calculationMode": calculation_mode,
        "ctx": {k: getattr(ctx, k, None) for k in _NZ_CTX_DECIMALS + _NZ_CTX_PLAIN + _NZ_CTX_DATES},
        "records": {k: getattr(ctx, k, None) for k in _NZ_RECORD_KEYS},
        "notices": list(getattr(ctx, "nz_authority_deductions", None) or []),
        "accumulators": getattr(ctx, "nz_accumulators", None),
        "rateMap": {k: {f: getattr(r, f, None) if not isinstance(r, dict) else r.get(f) for f in _NZ_RATE_FIELDS}
                    for k, r in (getattr(ctx, "rate_map", None) or {}).items()},
        "slabs": [{f: getattr(s, f, None) if not isinstance(s, dict) else s.get(f) for f in _NZ_SLAB_FIELDS}
                  for s in (getattr(ctx, "slabs", None) or [])],
    })


def nz_thaw_context(frozen: dict):
    from app.modules.payroll.engine.base import PayrollContext

    if not frozen or frozen.get("version") != 1:
        raise BadRequestException("This payslip has no replayable New Zealand calculation context.")
    ctx = {}
    for key, value in (frozen.get("ctx") or {}).items():
        if key in _NZ_CTX_DECIMALS:
            ctx[key] = None if value in (None, "") else Decimal(str(value))
        elif key in _NZ_CTX_DATES:
            ctx[key] = None if value in (None, "") else date.fromisoformat(str(value)[:10])
        else:
            ctx[key] = value
    for key in ("gross", "basic"):
        ctx[key] = ctx.get(key) if ctx.get(key) is not None else Decimal("0")
    records = frozen.get("records") or {}
    accumulators = frozen.get("accumulators")
    return PayrollContext(
        **{k: v for k, v in ctx.items() if v is not None or k in ("nz_hours",)}, country=NZ,
        **{k: _nz_thaw_row(records.get(k)) for k in _NZ_RECORD_KEYS},
        nz_authority_deductions=[_nz_thaw_row(n) for n in frozen.get("notices") or []],
        nz_accumulators=None if accumulators is None else {k: Decimal(str(v)) for k, v in accumulators.items()},
        rate_map={k: _nz_thaw_row(row) for k, row in (frozen.get("rateMap") or {}).items()},
        slabs=[_nz_thaw_row(row) for row in frozen.get("slabs") or []],
    )


def nz_replay(frozen: dict):
    """Recalculate a frozen New Zealand payslip exactly as it was calculated."""
    from app.modules.payroll.engine.resolver import calculate_payroll

    return calculate_payroll(nz_thaw_context(frozen), frozen.get("calculationMode") or "standard")


def nz_payslip_snapshot(result, frozen: Optional[dict] = None) -> Optional[dict]:
    r = result.get("nz_result") if isinstance(result, dict) else getattr(result, "nz_result", None)
    if not r:
        return None
    snapshot = dict(r)
    if frozen is not None:
        snapshot["frozenContext"] = frozen
    return _json_safe(snapshot)


def _nz_run_items(db: Session, run) -> list:
    from app.modules.payroll.models import PayslipItem

    return (db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == NZ)
            .order_by(PayslipItem.id).all())


def nz_approval_fingerprint(db: Session, run) -> Optional[str]:
    items = _nz_run_items(db, run)
    if not items:
        return None
    payload = [{"employeeId": item.employee_id,
                "hashes": (item.nz_calculation_snapshot or {}).get("hashes")} for item in items]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ── preflight and run transitions ───────────────────────────────────────────
def nz_run_preflight(db: Session, run) -> list:
    from app.modules.payroll.models import PayrollEmployee

    problems = []
    rate_map, _slabs, pack = _nz_pack_in_force(db, run.pay_date)
    if pack is None:
        problems.append({"code": "NZ_NO_PACK_IN_FORCE", "employeeId": None,
                         "message": "No New Zealand rule pack is in force on the payday."})
    m = _nz_models()
    for item in _nz_run_items(db, run):
        employee = db.get(PayrollEmployee, item.employee_id)
        snapshot = item.nz_calculation_snapshot
        if snapshot is None:
            problems.append({"code": "NZ_SNAPSHOT_MISSING", "employeeId": item.employee_id,
                             "message": "No frozen New Zealand calculation; recalculate the run."})
        else:
            for exception in snapshot.get("exceptions") or []:
                problems.append({"code": exception.get("code"), "employeeId": item.employee_id,
                                 "message": "A statutory exception needs resolving before approval."})
        employer = _nz_one_active(db, m.PayrollNzEmployerProfile, run.organization_id, None, run.pay_date,
                                  "employer profile", legal_entity_id=getattr(employee, "legal_entity_id", None),
                                  entity_scoped=True)
        if employer is None:
            problems.append({"code": "NZ_EMPLOYER_PROFILE_MISSING", "employeeId": item.employee_id,
                             "message": "No ACTIVE New Zealand employer profile covers the payday."})
        elif employer.verification_state != "VERIFIED":
            problems.append({"code": "NZ_EMPLOYER_NOT_VERIFIED", "employeeId": item.employee_id,
                             "message": "The New Zealand employer profile is not verified."})
    return problems


def post_accumulators(db: Session, run, actor_id) -> int:
    from app.modules.payroll.models import PayrollEmployee

    m = _nz_models()
    Entry = m.PayrollNzAccumulatorEntry
    tax_year = _nz_tax_year(db, run.pay_date)
    if tax_year is None:
        from fastapi import HTTPException, status as http_status

        raise HTTPException(http_status.HTTP_409_CONFLICT,
                            detail="New Zealand: no rule pack is in force on the payday; cannot post year-to-date.")
    kind = "CORRECTION" if (getattr(run, "nz_payment_kind", None) or "").upper() == "CORRECTION" else "RUN"
    added = 0
    for item in _nz_run_items(db, run):
        snapshot = item.nz_calculation_snapshot or {}
        employee = db.get(PayrollEmployee, item.employee_id)
        result_hash = (snapshot.get("hashes") or {}).get("resultHash")
        for obligation, amount in (snapshot.get("accumulatorDeltas") or {}).items():
            exists = (db.query(Entry.id).filter(Entry.payslip_item_id == item.id, Entry.obligation == obligation,
                                                Entry.entry_kind == kind).first())
            if exists:
                continue
            db.add(Entry(organization_id=run.organization_id,
                         legal_entity_id=getattr(employee, "legal_entity_id", None), employee_id=item.employee_id,
                         tax_year=tax_year, obligation=obligation, pay_date=run.pay_date, amount=Decimal(amount),
                         entry_kind=kind, run_id=run.id, payslip_item_id=item.id, result_hash=result_hash,
                         created_by_id=actor_id))
            added += 1
    db.flush()
    return added


def before_run_transition(db: Session, run, next_status, actor_id) -> None:
    """Approval needs every NZ payslip frozen, the employer verified and no
    open statutory exception (minimum wage NZ-015, child-support shortfall
    NZ-012); later steps re-verify the approval fingerprint; PAID posts the
    year-to-date ledger exactly once (NZ-013)."""
    from fastapi import HTTPException, status as http_status

    from app.modules.payroll.models import PayrollStatus

    if not _nz_run_items(db, run):
        return
    if next_status == PayrollStatus.APPROVED:
        problems = nz_run_preflight(db, run)
        if problems:
            listing = "; ".join(f"{p['code']}" + (f" (employee #{p['employeeId']})" if p["employeeId"] else "")
                                for p in problems)
            raise HTTPException(http_status.HTTP_409_CONFLICT,
                                detail=f"New Zealand: the run cannot be approved: {listing}")
        run.nz_approval_fingerprint = nz_approval_fingerprint(db, run)
        return
    if next_status in (PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        if not run.nz_approval_fingerprint or nz_approval_fingerprint(db, run) != run.nz_approval_fingerprint:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                "New Zealand: the approved calculation no longer matches this run - recalculate and approve again."))
    if next_status == PayrollStatus.PAID:
        post_accumulators(db, run, actor_id)


# ── platform hooks ──────────────────────────────────────────────────────────
def _nz_statutory_profile_errors(data) -> list:
    errors = []
    content = _content()
    code = getattr(data, "nz_tax_code", None)
    if code is not None and str(code).strip().upper() not in content.SUPPORTED_TAX_CODES:
        errors.append("nz_tax_code is not a supported New Zealand tax code.")
    state = getattr(data, "nz_ird_number_state", None)
    if state is not None and str(state).strip().upper() not in content.IRD_NUMBER_STATES:
        errors.append(f"nz_ird_number_state must be one of: {', '.join(content.IRD_NUMBER_STATES)}.")
    return errors


def _nz_profile_values(db: Session, employee, data, previous) -> dict:
    return {}


def _nz_pack_activation_refusal(db: Session, pack, actor_id=None) -> Optional[str]:
    return nz_pack_activation_refusal(db, pack, actor_id)


def _nz_pack_holidays(db: Session, year: int) -> list:
    """National public holidays from the in-force NZ packs' own rows; regional
    anniversary days are resolved per employee (Phase 5), never seeded here.
    No pack / no rows means nothing is seeded, never a guessed date."""
    content = _content()
    seen, out = set(), []
    for on in (date(year, 1, 1), date(year, 12, 31)):
        _rate_map, slabs, pack = _nz_pack_in_force(db, on)
        for row in slabs or []:
            if (row.rule_type or "").upper() != content.NZ_PUBLIC_HOLIDAY_RULE or row.jurisdiction_state:
                continue
            day = row.effective_from
            if day is None or day.year != year or day in seen or "[PENDING G1]" in (row.rate_label or ""):
                continue
            seen.add(day)
            out.append({"date": day.isoformat(), "name": row.rate_label or "Public holiday"})
    return sorted(out, key=lambda h: h["date"])


def _nz_template_activation_refusal(db: Session, template, actor_id=None) -> Optional[str]:
    country = (getattr(template, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(template, "report_type", "") or "").upper()
    if country != NZ and not report_type.startswith("NZ_"):
        return None
    return ("New Zealand filing and payment templates stay inactive until the payday-filing schema is "
            "certified (gate G3).")


def _nz_payment_treatment(db: Session, organization_id: int, run, items: list) -> dict:
    return {}


def _nz_payslip_hold_view(item) -> Optional[dict]:
    return None


def _nz_statutory_editors(db: Session, pack) -> set:
    return set()


NZ_RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and the frozen NZ calculation snapshot"),
    ("WAGE_TIME_RECORDS", "Hours, pay rates and gross pay"),
    ("HOLIDAY_LEAVE_RECORDS", "Holidays Act entitlement and leave records"),
    ("TAX_RECORDS", "PAYE, KiwiSaver, ESCT, student loan and child-support records"),
    ("EMPLOYEE_IDENTITY", "IRD-number vault metadata and tax profiles"),
    ("ACCESS_LOGS", "IRD-number access events"),
    ("AUTHORITY_NOTICES", "Authority notice versions (file hash and evidence reference only)"),
)
NZ_DECISIONS = {
    "D-1": ("Legal employer = organisation + legal entity", False),
    "D-2": ("Specification values seeded as PENDING G1", False),
    "D-3": ("Payday filing: JSON preview only until gate G3", False),
    "D-4": ("IRD numbers held only in the encrypted vault", False),
    "D-5": ("Full Holidays Act; Employment Leave Act 2028 staged only", False),
    "D-6": ("Deferred scope refused with reason codes", False),
    "D-7": ("Retention period for New Zealand tax records", True),
}


def _nz_evidence(db: Session, tag: str):
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact).filter(SourceArtifact.form_number == tag,
                                            SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    accepted = next((r for r in rows if r.reviewer_id and r.file_path and r.reviewer_id != r.created_by_id), None)
    return accepted, bool(rows)


def owner_decisions(db: Session) -> list:
    out = []
    for key, (label, blocks) in NZ_DECISIONS.items():
        accepted, submitted = _nz_evidence(db, f"NZ-DECISION-{key}")
        out.append({"key": key, "label": label, "blocksLaunch": blocks, "evidenceTag": f"NZ-DECISION-{key}",
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


def _nz_decision_state(db: Session, key: str) -> str:
    return next((d["state"] for d in owner_decisions(db) if d["key"] == key), "OPEN")


def _nz_retention_employee(db: Session, employee_id: int, organization_id: int) -> None:
    employee = _nz_employee(db, organization_id, employee_id)
    if (getattr(employee, "country_code", None) or "").upper() != NZ:
        raise NotFoundException("New Zealand employee")


def _nz_retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    m = _nz_models()
    for model, label in ((m.PayrollNzEmployeeTaxProfile, "tax profiles"),
                         (m.PayrollNzAuthorityDeduction, "authority notices"),
                         (m.PayrollNzAccumulatorEntry, "year-to-date ledger")):
        if db.query(model.id).filter(model.organization_id == organization_id,
                                     model.employee_id == employee_id).first():
            return label
    return None


def _nz_has_statutory_profile(db: Session, employee_id: int) -> bool:
    m = _nz_models()
    return db.query(m.PayrollNzEmployeeTaxProfile.id).filter(
        m.PayrollNzEmployeeTaxProfile.employee_id == employee_id).first() is not None


def _nz_is_report(report) -> bool:
    country = (getattr(report, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(report, "report_type", "") or "").upper()
    return country == NZ or report_type.startswith("NZ_")


def _nz_retention_settings():
    # The platform calls this hook with NO arguments (retention_service.settings).
    from app.modules.payroll.retention_service import RetentionJurisdiction

    return RetentionJurisdiction(
        country=NZ, label="New Zealand", categories=NZ_RETENTION_CATEGORIES, period_decision="D-7",
        end_decision="D-7", decision_reference="NZ-RETENTION", decision_state=_nz_decision_state,
        validate_employee=_nz_retention_employee, retained_record_label=_nz_retained_record_label,
        has_statutory_profile=_nz_has_statutory_profile, report_matches=_nz_is_report)


def nz_unmet_requirements(db: Session) -> list:
    """Release gates G1-G7 arrive with Phase 9; until then New Zealand can never open."""
    return ["New Zealand release gates G1-G7 are not implemented yet (Phase 9)."]


def statutory_summary(db: Session) -> dict:
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    content, m = _content(), _nz_models()
    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == NZ)
             .order_by(JurisdictionPack.effective_from.desc()).all())
    marker = f"%{PENDING_G1_SUFFIX.strip()}%"
    pending = sum(
        db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == p.id,
                                          ContributionRate.label.like(marker)).count()
        + db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == p.id, TaxSlab.rate_label.like(marker)).count()
        for p in packs)
    empty = [name for name, table in content.NZ_EMPTY_TABLES.items()
             if not db.query(TaxSlab.id).filter(TaxSlab.jurisdiction_country == NZ,
                                                TaxSlab.rule_type == table["rule_type"]).first()]

    def active(model):
        return db.query(model).filter(model.status == STATUS_ACTIVE).count()

    return {
        "jurisdiction": NZ, "spec": SPEC, "available": False,
        "packs": [{"id": p.id, "packId": p.pack_id, "version": p.version, "status": p.status,
                   "effectiveFrom": p.effective_from.isoformat() if p.effective_from else None,
                   "effectiveTo": p.effective_to.isoformat() if p.effective_to else None} for p in packs],
        "pendingRows": pending, "emptyAuthorityTables": empty,
        "activeEmployerProfiles": active(m.PayrollNzEmployerProfile),
        "verifiedEmployerProfiles": db.query(m.PayrollNzEmployerProfile).filter(
            m.PayrollNzEmployerProfile.status == STATUS_ACTIVE,
            m.PayrollNzEmployerProfile.verification_state == "VERIFIED").count(),
        "activeTaxProfiles": active(m.PayrollNzEmployeeTaxProfile),
        "activeKiwiSaverElections": active(m.PayrollNzKiwiSaverElection),
        "approvedNotices": db.query(m.PayrollNzAuthorityDeduction).filter(
            m.PayrollNzAuthorityDeduction.status == "APPROVED").count(),
        "decisions": owner_decisions(db),
        "readiness": {"gatesImplemented": False, "unmet": nz_unmet_requirements(db)},
        "note": "New Zealand remains PLANNED: no statutory row is signed and the release gates are not built.",
    }


def _nz_service_registry_transition(db: Session, target: str, reason: str, actor_id=None, as_of=None):
    from app.modules.payroll import service

    def readiness():
        return nz_unmet_requirements(db), {}

    return service.transition_service_registry(
        db, NZ, target, reason, actor_id, label="New Zealand", readiness=readiness,
        invalid_target_message=lambda t: (f"New Zealand availability can only be {service.SERVICE_REGISTRY_OPEN} "
                                          f"or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no New Zealand registry row - seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"New Zealand is {a}; only PLANNED moves to AVAILABLE.")


JURISDICTION_HOOKS = {
    "calc_inputs": "calc_inputs",
    "before_run_transition": "before_run_transition",
    "statutory_profile_errors": "_nz_statutory_profile_errors",
    "statutory_profile_values": "_nz_profile_values",
    "pack_activation_refusal": "_nz_pack_activation_refusal",
    "retention_settings": "_nz_retention_settings",
    "service_registry_transition": "_nz_service_registry_transition",
    "statutory_summary": "statutory_summary",
    "statutory_editors": "_nz_statutory_editors",
    "template_activation_refusal": "_nz_template_activation_refusal",
    "pack_holidays": "_nz_pack_holidays",
    "payment_treatment": "_nz_payment_treatment",
    "payslip_hold_view": "_nz_payslip_hold_view",
}


# ── employee summary (for the Phase 7 panel) ────────────────────────────────
def employee_summary(db: Session, organization_id: int, employee_id: int) -> dict:
    m = _nz_models()
    _nz_employee(db, organization_id, employee_id)

    def versions(model):
        return [_json_safe(_facts(r)) for r in db.query(model).filter(
            model.organization_id == organization_id, model.employee_id == employee_id).order_by(model.id)]

    vault = [nz_ird_view(r) for r in db.query(m.PayrollNzIrdVault).filter(
        m.PayrollNzIrdVault.organization_id == organization_id, m.PayrollNzIrdVault.employee_id == employee_id,
        m.PayrollNzIrdVault.status == "ACTIVE")]
    notices = [{"id": n.id, "type": n.deduction_type, "noticeId": n.notice_id, "version": n.version,
                "status": n.status, "effectiveFrom": n.effective_from.isoformat(),
                "amountPerPayday": None if n.amount_per_payday is None else str(n.amount_per_payday)}
               for n in db.query(m.PayrollNzAuthorityDeduction).filter(
                   m.PayrollNzAuthorityDeduction.organization_id == organization_id,
                   m.PayrollNzAuthorityDeduction.employee_id == employee_id)
               .order_by(m.PayrollNzAuthorityDeduction.id)]
    return {"employeeId": employee_id, "irdNumber": vault[0] if vault else {"onFile": False, "masked": None},
            "taxProfiles": versions(m.PayrollNzEmployeeTaxProfile),
            "kiwisaver": versions(m.PayrollNzKiwiSaverElection),
            "workPatterns": versions(m.PayrollNzWorkPatternVersion), "notices": notices}
