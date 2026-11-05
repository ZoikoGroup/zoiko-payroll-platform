"""
modules/payroll/poland_service.py
---------------------------------
Poland statutory workflows (ZP-PL-ENG-001) — the ONLY Poland service module,
on the shared platform the same way south_africa_service.py and
new_zealand_service.py are.

Phase 1: seeding the canonical PL-PAYROLL-2026 Draft pack from
engine/countries/poland_content.py, and the activation refusal that keeps a
pack carrying unsigned ([PENDING G1]) or empty content from ever becoming
Active.

Phase 4 (this module's platform half, registered in
jurisdiction_hooks._MODULES with all 13 hooks):
  * versioned records with a second person's approval — employer
    registrations (+ verification), worker statutory profiles, PPK
    participation; never edited in place (a change is a new version);
  * employee statements (PL-005): received / effective dates, evidence,
    source channel, four-eyes approval, supersession and withdrawal; a
    statement stays effective until changed (PL-007); an approved
    prior-employer cap statement posts evidenced PRIOR_EMPLOYER ledger
    entries (PL-010);
  * the identifier vault (spec §13, PL-025): PESEL / NIP / NRS encrypted,
    masked everywhere, single-use reveal requested and approved by two people;
  * calculation inputs selected by the PAY DATE, the frozen snapshot / replay,
    the approval fingerprint, run preflight and the year-to-date ledger
    posted exactly once at PAID.
"""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

PL = "PL"
SPEC = "ZP-PL-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"
NOT_CONFIGURED = "NOT CONFIGURED"
STATUS_DRAFT, STATUS_ACTIVE, STATUS_SUPERSEDED = "DRAFT", "ACTIVE", "SUPERSEDED"


def seed_poland_pack(db: Session, *, effective_from: date = date(2026, 1, 1),
                     status: str = "Draft") -> "JurisdictionPack":
    """Write poland_content.py into the PL-PAYROLL-2026 tax pack:
      * one SourceArtifact per evidence-register entry (S1–S12), reused if present;
      * every scalar parameter (ContributionRate) with its value in the slot its
        kind names (employee/employer pct, flat_amount, text_value) and its own
        legal effective_from / effective_to where it has one; empty-by-design
        rows are written as NOT CONFIGURED and pending;
      * the PIT scale (TaxSlab rule_type="PL_PIT_BAND", published bases);
      * every earning-classification row (TaxSlab rule_type="PL_EARNING_CLASS",
        filing_status = component, tax_regime = obligation,
        assessment_basis = treatment).

    Draft only; a pack that has left Draft is never rewritten, and a Draft
    pack's canonical rows are replaced wholesale from the content (org-scoped
    rows are an organisation's overrides and are never touched)."""
    from app.modules.payroll.engine.countries import poland_content as content
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    if status != "Draft":
        raise ValueError("seed_poland_pack only writes Draft content")
    pack_id, window_from, window_to = content.PL_2026
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")

    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-PL-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency[:200]).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form,
                                      source_url=content.SOURCE_URLS.get(code))
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id

    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=PL, pack_type="tax",
                                effective_from=effective_from or window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_to = window_to
    pack.tax_year = content.TAX_YEAR
    pack.currency = content.CURRENCY
    pack.regulatory_authority = "Ministry of Finance (KAS) / ZUS / PFR (PPK) / Ministry of Family, Labour and Social Policy"
    pack.source_document_id = sources["S3"]
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.organization_id.is_(None)).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None)).delete()

    def dec(value):
        return Decimal(str(value)) if value is not None else None

    def pending(label, flag, limit):
        return (label[:limit - len(PENDING_G1_SUFFIX)] + PENDING_G1_SUFFIX) if flag else label[:limit]

    order = 0
    for (key, label, ee, er, flat, text, src, is_pending, eff_from, eff_to, _basis) in content.POLAND_SCALAR_CONTENT:
        order += 1
        ee_shown = f"{ee}%" if ee is not None else "—"
        er_shown = f"{er}%" if er is not None else "—"
        if ee is not None or er is not None:
            total = " / ".join(s for s in (ee_shown, er_shown) if s != "—")
        elif text is None and flat is None:
            total = NOT_CONFIGURED          # content.POLAND_EMPTY_BY_DESIGN
        else:
            total = text if text is not None else str(flat)
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=PL,
            component_key=key, label=pending(label, is_pending, 100),
            employee_share=ee_shown[:50], employer_share=er_shown[:50], total=total[:50],
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er),
            flat_amount=dec(flat), text_value=text,
            effective_from=eff_from, effective_to=eff_to,
            source_document_id=sources.get(src), sort_order=order))

    for (lo, hi, rate, base, label, src) in content.POLAND_PIT_BANDS:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=PL,
            rule_type=content.PL_PIT_BAND_RULE,
            min_amount=dec(lo), max_amount=dec(hi), rate_pct=dec(rate), flat_amount=dec(base),
            rate_label=f"{Decimal(rate).normalize():f}%"[:150], tax_formula=label[:150],
            source_document_id=sources.get(src), sort_order=order))

    for (obligation, treatment, component, label, src) in content.POLAND_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=PL,
            rule_type=content.PL_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=label[:150], tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))

    db.flush()
    return pack


def pl_pack_activation_refusal(db: Session, pack, actor_id: Optional[int] = None) -> Optional[str]:
    """Why a Polish pack must NOT be activated, or None.

    A pack is refused while ANY canonical row still carries the [PENDING G1]
    marker or is NOT CONFIGURED (spec §15 G1: NO-GO if any supported result
    relies on guessed or uncited content), or while a scalar row has no
    source document. Becomes the `pack_activation_refusal` hook in Phase 4;
    four-eyes approval is enforced separately by the shared approval lists."""
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if (getattr(pack, "jurisdiction_country", None) or "").upper() != PL:
        return None
    rates = (db.query(ContributionRate)
             .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                     ContributionRate.organization_id.is_(None)).all())
    if not rates:
        return "Poland pack has no statutory content — seed it from poland_content.py first."
    unsigned = sorted(r.component_key for r in rates
                      if (r.label or "").endswith(PENDING_G1_SUFFIX.strip()) or r.total == NOT_CONFIGURED
                      or (r.text_value or "") == "PENDING_G1")
    if unsigned:
        shown = ", ".join(unsigned[:8]) + (f" (+{len(unsigned) - 8} more)" if len(unsigned) > 8 else "")
        return (f"Poland pack {pack.pack_id} still has {len(unsigned)} unsigned or unconfigured row(s): "
                f"{shown}. Gate G1 must sign them before activation (ZP-PL-ENG-001 §15).")
    unsourced = sorted(r.component_key for r in rates if r.source_document_id is None)
    if unsourced:
        return f"Poland pack {pack.pack_id} has rows without a source document: {', '.join(unsourced[:8])}."
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                      TaxSlab.organization_id.is_(None)).all())
    if not any(s.rule_type == "PL_PIT_BAND" for s in slabs):
        return f"Poland pack {pack.pack_id} has no PIT scale."
    return None


# ══════════════════════════════════════════════════════════════════════════
# Phase 4 — records, statements, vault, calculation inputs, run lifecycle
# ══════════════════════════════════════════════════════════════════════════
def _models():
    from app.modules.payroll import models as m

    return m


def _content():
    from app.modules.payroll.engine.countries import poland_content as content

    return content


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


def _decimal(value, field: str) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{field} must be a decimal number.")


def _bool(value, field: str) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise BadRequestException(f"{field} must be true or false.")


def _reason(reason) -> str:
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("A reason is required for every Poland statutory change (spec §13 audit).")
    return text[:300]


def _audit(db: Session, actor_id, action: str, entity_type: str, entity_id: int, old=None, new=None,
           reason: Optional[str] = None) -> None:
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     old_value=old, new_value=new, reason=reason, legal_reference=SPEC, auto_commit=False)


def _employee(db: Session, organization_id: int, employee_id: int):
    from app.core.authz.scopes import organization_scoped
    from app.modules.payroll.models import PayrollEmployee

    employee = (organization_scoped(db, PayrollEmployee, organization_id)
                .filter(PayrollEmployee.id == employee_id).first())
    if employee is None:
        raise NotFoundException("Polish employee")
    return employee


def _legal_entity(db: Session, organization_id: int, legal_entity_id) -> None:
    if legal_entity_id is None:
        return
    from app.modules.organizations.models import LegalEntity

    found = (db.query(LegalEntity.id)
             .filter(LegalEntity.id == legal_entity_id, LegalEntity.organization_id == organization_id).first())
    if found is None:
        raise NotFoundException("Legal entity in this organisation")


def _facts(row) -> Optional[dict]:
    """Plain-value dict of a model row (the engine reads dicts)."""
    if row is None:
        return None
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


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


def _in_force(query, model, on: date):
    return query.filter(model.effective_from <= on, (model.effective_to.is_(None)) | (model.effective_to >= on))


def _enum(data: dict, key: str, allowed) -> None:
    value = data.get(key)
    if value is None:
        return
    value = str(value).strip().upper()
    if value not in allowed:
        raise BadRequestException(f"{key} must be one of: {', '.join(allowed)}.")
    data[key] = value


# ── field whitelists (anything else is refused; the server owns status) ────
PL_REGISTRATION_FIELDS = (
    "effective_from", "effective_to", "legal_entity_id", "legal_name", "nip", "regon", "krs", "tax_office_code",
    "zus_deadline_class", "zus_deadline_evidence_ref", "accident_rate_pct", "accident_rate_source",
    "accident_rate_from", "accident_rate_to", "accident_rate_evidence_ref", "small_payer", "ppk_institution",
    "ppk_agreement_ref", "ppk_employer_additional_pct", "fp_fs_applicable", "fgsp_applicable",
    "pl_journal_accounts", "bank_export_ref", "filing_credential_ref", "source_document_id", "evidence_ref")
PL_PROFILE_FIELDS = (
    "effective_from", "effective_to", "legal_entity_id", "contract_type", "insurance_title_code", "cov_pension",
    "cov_disability", "cov_sickness", "cov_accident", "cov_health", "fte_numerator", "fte_denominator",
    "working_time_system", "pay_frequency", "tax_residency", "is_student", "is_pensioner",
    "other_titles_declared", "other_titles_evidence_ref", "a1_certificate", "fep_qualifying", "fep_evidence_ref",
    "fep_from", "fep_to", "fund_exemption_code", "fund_exemption_evidence_ref", "service_credit_months",
    "pesel_vault_id", "nip_vault_id", "evidence_ref")
PL_PPK_FIELDS = ("effective_from", "effective_to", "legal_entity_id", "state", "enrolment_date", "notice_state",
                 "opt_out_declaration_id", "next_reenrolment_date", "evidence_ref")
PL_DECLARATION_FIELDS = ("declaration_type", "value", "received_at", "effective_from", "effective_to",
                         "source_channel", "legal_entity_id", "evidence_ref")

_DATE_FIELDS = {"effective_from", "effective_to", "accident_rate_from", "accident_rate_to", "fep_from", "fep_to",
                "enrolment_date", "next_reenrolment_date"}
_DECIMAL_FIELDS = {"accident_rate_pct", "ppk_employer_additional_pct"}
_INT_FIELDS = {"legal_entity_id", "source_document_id", "fte_numerator", "fte_denominator", "service_credit_months",
               "pesel_vault_id", "nip_vault_id", "opt_out_declaration_id"}
_BOOL_FIELDS = {"small_payer", "fp_fs_applicable", "fgsp_applicable", "cov_pension", "cov_disability",
                "cov_sickness", "cov_accident", "cov_health", "is_student", "is_pensioner", "other_titles_declared",
                "a1_certificate", "fep_qualifying"}
_JSON_FIELDS = {"pl_journal_accounts", "value"}


def _clean(payload: dict, fields, *, required=()) -> dict:
    if not isinstance(payload, dict):
        raise BadRequestException("The request body must be an object.")
    unknown = sorted(set(payload) - set(fields))
    if unknown:
        raise BadRequestException(f"unknown field(s): {', '.join(unknown)}")
    data = {}
    for key, value in payload.items():
        if value is None or value == "":
            data[key] = None
        elif key in _DATE_FIELDS:
            data[key] = _as_date(value, key)
        elif key == "received_at":
            data[key] = _as_datetime(value, key)
        elif key in _DECIMAL_FIELDS:
            data[key] = _decimal(value, key)
        elif key in _INT_FIELDS:
            try:
                data[key] = int(value)
            except (TypeError, ValueError):
                raise BadRequestException(f"{key} must be a whole number.")
        elif key in _BOOL_FIELDS:
            data[key] = _bool(value, key)
        elif key in _JSON_FIELDS:
            if not isinstance(value, dict):
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


# ── versioned records with a second person's approval (spec §13 four-eyes) ─
def _scope(query, model, employee_id, legal_entity_id, entity_scoped: bool):
    if employee_id is not None:
        query = query.filter(model.employee_id == employee_id)
    if entity_scoped:
        query = query.filter(model.legal_entity_id.is_(None) if legal_entity_id is None
                             else model.legal_entity_id == legal_entity_id)
    return query


def _create_version(db: Session, model, organization_id: int, employee_id: Optional[int], data: dict, actor_id,
                    label: str, reason: str, *, entity_scoped: bool = False):
    query = _scope(db.query(model).filter(model.organization_id == organization_id), model, employee_id,
                   data.get("legal_entity_id"), entity_scoped)
    prior = query.order_by(model.effective_from.desc(), model.id.desc()).first()
    row = model(organization_id=organization_id, status=STATUS_DRAFT, created_by_id=actor_id,
                previous_version_id=getattr(prior, "id", None), **data)
    if employee_id is not None:
        row.employee_id = employee_id
    db.add(row)
    db.flush()
    _audit(db, actor_id, "created", label, row.id, new={"effective_from": data["effective_from"].isoformat()},
           reason=reason)
    return row


def _approve_version(db: Session, model, organization_id: int, row_id: int, actor_id, label: str,
                     *, entity_scoped: bool = False):
    from app.modules.payroll.service import require_four_eyes

    row = db.query(model).filter(model.id == row_id, model.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException(f"Poland {label.replace('pl_', '').replace('_', ' ')}")
    if row.status != STATUS_DRAFT:
        raise BadRequestException(f"Only a DRAFT {label.replace('_', ' ')} can be approved.")
    require_four_eyes(row.created_by_id, actor_id, f"Approving a Poland {label.replace('_', ' ')}",
                      db=db, entity_type=label, entity_id=row.id, current_status=row.status)
    start = row.effective_from
    query = _scope(db.query(model).filter(model.organization_id == organization_id,
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
    _audit(db, actor_id, "approved", label, row.id, old={"status": STATUS_DRAFT},
           new={"status": STATUS_ACTIVE, "effective_from": start.isoformat()})
    return row


def _one_active(db: Session, model, organization_id: int, employee_id, on: date, label: str,
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
        raise BadRequestException(f"Two ACTIVE Poland {label} versions overlap on {on.isoformat()}.")
    return rows[0] if rows else None


# ── employer registrations (spec §11 PLEmployerRegistration, PL-001) ────────
def record_pl_employer_registration(db: Session, organization_id: int, payload: dict, actor_id, reason=None):
    from app.modules.payroll.employee_validation import pl_nip_is_valid, pl_regon_is_valid

    reason = _reason(reason)
    content = _content()
    data = _clean(payload, PL_REGISTRATION_FIELDS,
                  required=("effective_from", "legal_name", "nip", "zus_deadline_class"))
    _legal_entity(db, organization_id, data.get("legal_entity_id"))
    _enum(data, "zus_deadline_class", content.ZUS_DEADLINE_CLASSES)
    _enum(data, "accident_rate_source", content.ACCIDENT_RATE_SOURCES)
    data["nip"] = data["nip"].replace("-", "").replace(" ", "")
    if not pl_nip_is_valid(data["nip"]):
        raise BadRequestException("NIP must be 10 digits with a valid check digit.")
    if data.get("regon"):
        data["regon"] = data["regon"].replace(" ", "")
        if not pl_regon_is_valid(data["regon"]):
            raise BadRequestException("REGON must be 9 or 14 digits with valid check digits.")
    if data.get("krs") and not (data["krs"].isdigit() and len(data["krs"]) == 10):
        raise BadRequestException("KRS must be 10 digits.")
    if (data.get("accident_rate_pct") is None) != (data.get("accident_rate_source") is None):
        raise BadRequestException("An accident rate needs its source, and a source needs its rate.")
    if data.get("accident_rate_pct") is not None and not (data.get("accident_rate_from")
                                                          and data.get("accident_rate_evidence_ref")):
        raise BadRequestException("An accident rate needs its contribution-year start and evidence.")
    return _create_version(db, _models().PayrollPlEmployerRegistration, organization_id, None, data, actor_id,
                           "pl_employer_registration", reason, entity_scoped=True)


def approve_pl_employer_registration(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollPlEmployerRegistration, organization_id, row_id, actor_id,
                            "pl_employer_registration", entity_scoped=True)


def verify_pl_employer_registration(db: Session, organization_id: int, row_id: int, actor_id, outcome, reason):
    from app.modules.payroll.service import require_four_eyes

    reason = _reason(reason)
    m = _models()
    row = (db.query(m.PayrollPlEmployerRegistration)
           .filter(m.PayrollPlEmployerRegistration.id == row_id,
                   m.PayrollPlEmployerRegistration.organization_id == organization_id).first())
    if row is None:
        raise NotFoundException("Poland employer registration")
    outcome = str(outcome or "").strip().upper()
    if outcome not in ("VERIFIED", "REJECTED"):
        raise BadRequestException("outcome must be VERIFIED or REJECTED.")
    if row.status != STATUS_ACTIVE:
        raise BadRequestException("Only an ACTIVE employer registration is verified.")
    require_four_eyes(row.created_by_id, actor_id, "Verifying a Poland employer registration", db=db,
                      entity_type="pl_employer_registration", entity_id=row.id, current_status=row.status)
    old = row.verification_state
    row.verification_state = outcome
    db.flush()
    _audit(db, actor_id, "verified", "pl_employer_registration", row.id, old={"verification_state": old},
           new={"verification_state": outcome}, reason=reason)
    return row


# ── worker statutory profile (spec §3 / §11, PL-002) ────────────────────────
def record_pl_worker_profile(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id,
                             reason=None):
    reason = _reason(reason)
    content = _content()
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, PL_PROFILE_FIELDS, required=("effective_from", "contract_type"))
    _enum(data, "contract_type", content.CONTRACT_TYPES_SUPPORTED + content.CONTRACT_TYPES_BLOCKED)
    _enum(data, "pay_frequency", ("MONTHLY", "WEEKLY", "FORTNIGHTLY", "OTHER"))
    _enum(data, "tax_residency", ("RESIDENT", "NON_RESIDENT"))
    code = data.get("insurance_title_code")
    if code is not None and not (code.isdigit() and len(code) == 6):
        raise BadRequestException("insurance_title_code must be the 6-digit ZUS title code.")
    if data.get("other_titles_declared") is True and not data.get("other_titles_evidence_ref"):
        raise BadRequestException("Other insurance titles need declaration evidence (PL-010).")
    if data.get("fep_qualifying") is True and not (data.get("fep_evidence_ref") and data.get("fep_from")):
        raise BadRequestException("FEP needs working-condition evidence and a start date (PL-012).")
    if data.get("fund_exemption_code") and not data.get("fund_exemption_evidence_ref"):
        raise BadRequestException("A named employer-fund exemption needs evidence (spec §6).")
    for key, kind in (("pesel_vault_id", "PESEL"), ("nip_vault_id", "NIP")):
        if data.get(key) is not None:
            _vault_for_employee(db, organization_id, employee.id, data[key], kind)
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    return _create_version(db, _models().PayrollPlWorkerProfile, organization_id, employee.id, data, actor_id,
                           "pl_worker_profile", reason)


def approve_pl_worker_profile(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollPlWorkerProfile, organization_id, row_id, actor_id,
                            "pl_worker_profile")


# ── PPK participation (spec §7) ─────────────────────────────────────────────
def record_pl_ppk_participation(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id,
                                reason=None):
    reason = _reason(reason)
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, PL_PPK_FIELDS, required=("effective_from", "state"))
    _enum(data, "state", _content().PPK_STATES)
    _enum(data, "notice_state", ("NOT_SENT", "SENT", "ACKNOWLEDGED"))
    if data["state"] == "ENROLLED" and not data.get("enrolment_date"):
        raise BadRequestException("An ENROLLED participant needs the enrolment date.")
    if data["state"] == "OPTED_OUT":
        declaration_id = data.get("opt_out_declaration_id")
        m = _models()
        D = m.PayrollPlDeclaration
        found = (db.query(D).filter(D.id == declaration_id, D.organization_id == organization_id,
                                    D.employee_id == employee.id, D.declaration_type == "PPK_OPT_OUT",
                                    D.status == "APPROVED").first()) if declaration_id else None
        if found is None:
            raise BadRequestException("OPTED_OUT needs the employee's APPROVED PPK_OPT_OUT statement.")
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    return _create_version(db, _models().PayrollPlPpkParticipation, organization_id, employee.id, data, actor_id,
                           "pl_ppk_participation", reason)


def approve_pl_ppk_participation(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollPlPpkParticipation, organization_id, row_id, actor_id,
                            "pl_ppk_participation")


def pl_ppk_reenrolment_due(db: Session, organization_id: int, on: date) -> list:
    """ACTIVE opted-out participations whose re-enrolment checkpoint has come."""
    P = _models().PayrollPlPpkParticipation
    rows = (db.query(P).filter(P.organization_id == organization_id, P.status == STATUS_ACTIVE,
                               P.state == "OPTED_OUT", P.next_reenrolment_date.isnot(None),
                               P.next_reenrolment_date <= on).order_by(P.next_reenrolment_date).all())
    return [{"participationId": r.id, "employeeId": r.employee_id,
             "nextReenrolmentDate": r.next_reenrolment_date.isoformat()} for r in rows]


# ── statements (PL-005 / PL-007 / PL-010) ───────────────────────────────────
def _declaration_value(kind: str, value) -> dict:
    content = _content()
    value = dict(value or {})
    if kind == "PIT2":
        allocation = str(value.get("allocation") or "").strip().upper()
        if allocation not in content.PIT2_ALLOCATIONS:
            raise BadRequestException("A PIT-2 statement must state allocation FULL, HALF or THIRD.")
        value["allocation"] = allocation
    elif kind == "PPK_REDUCED_RATE":
        for name in ("ratePct", "otherSourcesIncome"):
            number = _decimal(value.get(name), name)
            if number is None or number < 0:
                raise BadRequestException(f"A reduced PPK statement needs {name} (PL-013).")
            value[name] = str(number)
    elif kind == "PPK_ADDITIONAL":
        number = _decimal(value.get("ratePct"), "ratePct")
        if number is None or number < 0:
            raise BadRequestException("An additional PPK statement needs ratePct.")
        value["ratePct"] = str(number)
    elif kind == "PRIOR_EMPLOYER_CAP":
        for name in ("pensionBase", "disabilityBase"):
            number = _decimal(value.get(name), name)
            if number is None or number < 0:
                raise BadRequestException(f"A prior-employer cap statement needs {name} (PL-010).")
            value[name] = str(number)
    return value


def record_pl_declaration(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id):
    content = _content()
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, PL_DECLARATION_FIELDS,
                  required=("declaration_type", "received_at", "effective_from", "source_channel", "evidence_ref"))
    _enum(data, "declaration_type", content.DECLARATION_TYPES)
    _enum(data, "source_channel", ("PAPER", "ELECTRONIC", "EMPLOYEE_PORTAL", "IMPORT"))
    data["value"] = _declaration_value(data["declaration_type"], data.get("value"))
    if data["declaration_type"] == "PRIOR_EMPLOYER_CAP" and data["effective_from"].year != (
            data.get("effective_to") or data["effective_from"]).year:
        raise BadRequestException("A prior-employer cap statement covers one calendar year.")
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    D = _models().PayrollPlDeclaration
    row = D(organization_id=organization_id, employee_id=employee.id, status="RECEIVED", created_by_id=actor_id,
            **data)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "received", "pl_declaration", row.id,
           new={"type": row.declaration_type, "effective_from": row.effective_from.isoformat()},
           reason=f"{row.declaration_type} received {row.received_at.isoformat()}")
    return row


def _declaration(db: Session, organization_id: int, row_id: int):
    D = _models().PayrollPlDeclaration
    row = db.query(D).filter(D.id == row_id, D.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Poland statement")
    return row


def approve_pl_declaration(db: Session, organization_id: int, row_id: int, actor_id):
    """Four-eyes approval. An earlier APPROVED statement of the same type that
    is still open is superseded from this statement's start (never edited
    away); a later one refuses. An approved PRIOR_EMPLOYER_CAP posts its
    evidenced cap bases to the ledger (PL-010)."""
    from app.modules.payroll.service import require_four_eyes

    D = _models().PayrollPlDeclaration
    row = _declaration(db, organization_id, row_id)
    if row.status != "RECEIVED":
        raise BadRequestException("Only a RECEIVED statement can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a Poland statement", db=db,
                      entity_type="pl_declaration", entity_id=row.id, current_status=row.status)
    start = row.effective_from
    for old in (db.query(D).filter(D.organization_id == organization_id, D.employee_id == row.employee_id,
                                   D.declaration_type == row.declaration_type, D.status == "APPROVED",
                                   D.id != row.id).all()):
        if row.declaration_type == "PRIOR_EMPLOYER_CAP":
            continue                     # several prior employers can each be evidenced
        if old.effective_from >= start:
            raise BadRequestException("An APPROVED statement of this type already starts on or after this one.")
        if old.effective_to is None or old.effective_to >= start:
            old.effective_to = date.fromordinal(start.toordinal() - 1)
            old.status = "SUPERSEDED"
            old.superseded_by_id = row.id
    row.status = "APPROVED"
    row.approved_by_id = actor_id
    row.approved_at = datetime.utcnow()
    db.flush()
    if row.declaration_type == "PRIOR_EMPLOYER_CAP":
        _post_prior_employer(db, row, actor_id)
    _audit(db, actor_id, "approved", "pl_declaration", row.id, old={"status": "RECEIVED"},
           new={"status": "APPROVED", "type": row.declaration_type})
    return row


def withdraw_pl_declaration(db: Session, organization_id: int, row_id: int, actor_id, reason, effective_to):
    """A statement ends only when withdrawn or replaced (PL-007): the end date
    is recorded, the history is kept."""
    reason = _reason(reason)
    row = _declaration(db, organization_id, row_id)
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED statement can be withdrawn.")
    if row.declaration_type == "PRIOR_EMPLOYER_CAP":
        raise BadRequestException("A posted prior-employer cap statement is corrected by a reversing statement.")
    end = _as_date(effective_to, "effectiveTo")
    if end < row.effective_from:
        raise BadRequestException("The withdrawal date cannot be before the statement started.")
    row.effective_to = end
    row.status = "WITHDRAWN"
    row.withdrawn_at = datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "withdrawn", "pl_declaration", row.id, old={"status": "APPROVED"},
           new={"status": "WITHDRAWN", "effective_to": end.isoformat()}, reason=reason)
    return row


def _post_prior_employer(db: Session, row, actor_id) -> None:
    Entry = _models().PayrollPlAccumulatorEntry
    for accumulator, name in (("ZUS_CAP_PENSION_BASE", "pensionBase"), ("ZUS_CAP_DISABILITY_BASE", "disabilityBase")):
        amount = Decimal(str(row.value[name]))
        if amount == 0:
            continue
        db.add(Entry(organization_id=row.organization_id, legal_entity_id=row.legal_entity_id,
                     employee_id=row.employee_id, year=row.effective_from.year, accumulator=accumulator,
                     pay_date=row.effective_from, amount=amount, entry_kind="PRIOR_EMPLOYER",
                     declaration_id=row.id, evidence_ref=row.evidence_ref, created_by_id=row.created_by_id,
                     approved_by_id=actor_id, approved_at=datetime.utcnow()))
    db.flush()


# ── identifier vault (spec §13, PL-025): masked; reveal requested + approved ─
def _vault(db: Session, organization_id: int, vault_id: int):
    V = _models().PayrollPlIdentifierVault
    row = db.query(V).filter(V.id == vault_id, V.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Polish identifier")
    return row


def _vault_for_employee(db: Session, organization_id: int, employee_id: int, vault_id: int, kind: str):
    row = _vault(db, organization_id, vault_id)
    if row.employee_id != employee_id or row.identifier_type != kind or row.status != "ACTIVE":
        raise BadRequestException(f"{kind} vault reference does not belong to this employee.")
    return row


def _vault_owner(row) -> str:
    from app.modules.payroll import pl_identifiers as pid

    subject = row.employee_id if row.subject_type == pid.SUBJECT_EMPLOYEE else row.legal_entity_id
    return pid.vault_owner(row.organization_id, row.subject_type, subject, row.identifier_type, row.id)


def _vault_event(db: Session, row, action: str, actor_id, reason=None, purpose=None, previous_id=None):
    Event = _models().PayrollPlIdentifierAccessEvent
    event = Event(organization_id=row.organization_id, legal_entity_id=row.legal_entity_id,
                  employee_id=row.employee_id, vault_id=row.id, actor_id=actor_id, created_by_id=actor_id,
                  action=action, purpose=purpose, reason=(reason or None) and reason[:300],
                  previous_version_id=previous_id)
    db.add(event)
    db.flush()
    return event


def identifier_view(row) -> dict:
    from app.modules.payroll import pl_identifiers as pid

    active = row.status == "ACTIVE"
    return {"id": row.id, "subjectType": row.subject_type, "identifierType": row.identifier_type,
            "employeeId": row.employee_id, "legalEntityId": row.legal_entity_id, "onFile": active,
            "masked": pid.masked(row.identifier_type) if active else None, "status": row.status,
            "keyVersion": row.key_version}


def create_pl_identifier(db: Session, organization_id: int, identifier_type: str, raw, actor_id, *,
                         employee_id=None, legal_entity_id=None):
    from app.modules.payroll import pl_identifiers as pid

    V = _models().PayrollPlIdentifierVault
    identifier_type = str(identifier_type or "").strip().upper()
    if identifier_type in (pid.PESEL, pid.NIP):
        subject_type = pid.SUBJECT_EMPLOYEE
        employee = _employee(db, organization_id, employee_id)
        legal_entity_id = getattr(employee, "legal_entity_id", None)
    elif identifier_type == pid.NRS:
        subject_type, employee_id = pid.SUBJECT_EMPLOYER, None
        _legal_entity(db, organization_id, legal_entity_id)
    else:
        raise BadRequestException("identifierType must be PESEL, NIP or NRS.")
    try:
        plain = pid.normalise(identifier_type, raw)
        fingerprint = pid.fingerprint(identifier_type, plain)
    except pid.PlIdentifierError as error:
        raise BadRequestException(str(error))
    if db.query(V.id).filter(V.organization_id == organization_id, V.identifier_type == identifier_type,
                             V.fingerprint == fingerprint, V.status == "ACTIVE").first():
        raise BadRequestException(f"This {identifier_type} is already on file in this organisation.")
    if subject_type == pid.SUBJECT_EMPLOYEE and db.query(V.id).filter(
            V.organization_id == organization_id, V.employee_id == employee_id,
            V.identifier_type == identifier_type, V.status == "ACTIVE").first():
        raise BadRequestException(f"The employee already has a {identifier_type} on file; delete it first.")
    row = V(organization_id=organization_id, legal_entity_id=legal_entity_id, employee_id=employee_id,
            subject_type=subject_type, identifier_type=identifier_type, ciphertext="pending", key_version=0,
            fingerprint=fingerprint, collected_at=datetime.utcnow(), status="ACTIVE", created_by_id=actor_id)
    db.add(row)
    db.flush()
    try:
        row.ciphertext, row.key_version = pid.encrypt(plain, _vault_owner(row))
    except pid.PlIdentifierError as error:
        raise BadRequestException(str(error))
    plain = None
    db.flush()
    _vault_event(db, row, "CREATE", actor_id, purpose=pid.PURPOSE)
    return row


def list_pl_identifiers(db: Session, organization_id: int, employee_id=None) -> list:
    V = _models().PayrollPlIdentifierVault
    q = db.query(V).filter(V.organization_id == organization_id)
    if employee_id is not None:
        _employee(db, organization_id, employee_id)
        q = q.filter(V.employee_id == employee_id)
    return [identifier_view(r) for r in q.order_by(V.id)]


def _last_event(db: Session, row, action: str, after_id: int = 0):
    Event = _models().PayrollPlIdentifierAccessEvent
    return (db.query(Event).filter(Event.vault_id == row.id, Event.action == action, Event.id > after_id)
            .order_by(Event.id.desc()).first())


def request_pl_identifier_reveal(db: Session, organization_id: int, vault_id: int, reason, actor_id):
    row = _vault(db, organization_id, vault_id)
    if row.status != "ACTIVE" or not row.ciphertext:
        raise BadRequestException("The identifier has been deleted.")
    return _vault_event(db, row, "REVEAL_REQUESTED", actor_id, reason=_reason(reason), purpose="REVEAL")


def approve_pl_identifier_reveal(db: Session, organization_id: int, vault_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    row = _vault(db, organization_id, vault_id)
    request = _last_event(db, row, "REVEAL_REQUESTED")
    if request is None:
        raise BadRequestException("There is no reveal request to approve.")
    if _last_event(db, row, "REVEAL_APPROVED", request.id) is not None:
        raise BadRequestException("This reveal request has already been approved.")
    require_four_eyes(request.actor_id, actor_id, "Approving a Polish identifier reveal", db=db,
                      entity_type="pl_identifier_access_event", entity_id=request.id,
                      current_status="REVEAL_REQUESTED")
    return _vault_event(db, row, "REVEAL_APPROVED", actor_id, reason=request.reason, purpose="REVEAL",
                        previous_id=request.id)


def reveal_pl_identifier(db: Session, organization_id: int, vault_id: int, actor_id) -> dict:
    from app.modules.payroll import pl_identifiers as pid

    row = _vault(db, organization_id, vault_id)
    if row.status != "ACTIVE" or not row.ciphertext:
        raise BadRequestException("The identifier has been deleted.")
    request = _last_event(db, row, "REVEAL_REQUESTED")
    approval = _last_event(db, row, "REVEAL_APPROVED", request.id) if request is not None else None
    if request is None or approval is None:
        raise BadRequestException("A reveal needs a request and a second person's approval.")
    if _last_event(db, row, "REVEALED", approval.id) is not None:
        raise BadRequestException("This approval has already been used; request a new reveal.")
    if request.actor_id != actor_id:
        raise BadRequestException("Only the person who requested the reveal can see the identifier.")
    try:
        value = pid.decrypt(row.ciphertext, row.key_version, _vault_owner(row))
    except pid.PlIdentifierError as error:
        raise BadRequestException(str(error))
    _vault_event(db, row, "REVEALED", actor_id, reason=request.reason, purpose="REVEAL", previous_id=approval.id)
    return {"vaultId": row.id, "identifierType": row.identifier_type, "value": value}


def delete_pl_identifier(db: Session, organization_id: int, vault_id: int, actor_id, reason):
    reason = _reason(reason)
    row = _vault(db, organization_id, vault_id)
    if row.status == "DELETED":
        raise BadRequestException("The identifier has already been deleted.")
    row.status = "DELETED"
    row.deleted_at = datetime.utcnow()
    row.ciphertext = None
    db.flush()
    _vault_event(db, row, "DELETED", actor_id, reason=reason)
    return row


def set_pl_employer_nrs(db: Session, organization_id: int, registration_id: int, raw, actor_id):
    """Put the employer's ZUS contribution account (NRS) on file and link it to
    a DRAFT registration version (an ACTIVE version is never edited)."""
    R = _models().PayrollPlEmployerRegistration
    registration = db.query(R).filter(R.id == registration_id, R.organization_id == organization_id).first()
    if registration is None:
        raise NotFoundException("Poland employer registration")
    if registration.status != STATUS_DRAFT:
        raise BadRequestException("Link the NRS to a DRAFT registration version (never edit an ACTIVE one).")
    row = create_pl_identifier(db, organization_id, "NRS", raw, actor_id,
                               legal_entity_id=registration.legal_entity_id)
    registration.nrs_vault_id = row.id
    db.flush()
    return row


# ── year-to-date ledger (spec §11 Accumulator, PL-010 / PL-018) ─────────────
def pl_ytd_snapshot(db: Session, organization_id: int, employee_id: int, legal_entity_id, pay_date: date) -> dict:
    """Year-to-date sums BEFORE the pay date for the pay date's calendar year,
    every accumulator present (an explicit zero means 'known to be zero')."""
    from sqlalchemy import func

    Entry = _models().PayrollPlAccumulatorEntry
    query = (db.query(Entry.accumulator, func.sum(Entry.amount))
             .filter(Entry.organization_id == organization_id, Entry.employee_id == employee_id,
                     Entry.year == pay_date.year, Entry.pay_date < pay_date))
    query = query.filter(Entry.legal_entity_id.is_(None) if legal_entity_id is None
                         else Entry.legal_entity_id == legal_entity_id)
    totals = {name: Decimal(str(amount or 0)) for name, amount in query.group_by(Entry.accumulator)}
    return {name: totals.get(name, Decimal("0")) for name in _content().ACCUMULATORS}


def pl_annual_cap_view(db: Session, organization_id: int, employee_id: int, year: int) -> dict:
    """The annual cap panel (spec §12): YTD pension / disability bases, the
    entries behind them (with prior-employer evidence) — no recalculation."""
    employee = _employee(db, organization_id, employee_id)
    Entry = _models().PayrollPlAccumulatorEntry
    rows = (db.query(Entry).filter(Entry.organization_id == organization_id, Entry.employee_id == employee.id,
                                   Entry.year == year,
                                   Entry.accumulator.in_(("ZUS_CAP_PENSION_BASE", "ZUS_CAP_DISABILITY_BASE")))
            .order_by(Entry.pay_date, Entry.id).all())
    totals = {"ZUS_CAP_PENSION_BASE": Decimal("0"), "ZUS_CAP_DISABILITY_BASE": Decimal("0")}
    for r in rows:
        totals[r.accumulator] += Decimal(str(r.amount))
    return {"employeeId": employee.id, "year": year, "totals": _json_safe(totals),
            "entries": [{"id": r.id, "accumulator": r.accumulator, "payDate": r.pay_date.isoformat(),
                         "amount": str(r.amount), "kind": r.entry_kind, "evidenceRef": r.evidence_ref,
                         "runId": r.run_id, "declarationId": r.declaration_id} for r in rows]}


# ── annual leave entitlement (spec §8, Phase 5) ─────────────────────────────
def pl_leave_entitlement(db: Session, organization_id: int, employee_id: int, as_of) -> dict:
    """Whole-year entitlement from the ACTIVE worker profile and the pack in
    force on `as_of`. Refused (with the engine's own reason) when the service
    credit, FTE or a needed signed rule is missing — never a guessed figure."""
    from app.modules.payroll.engine.jurisdictions.poland import leave
    from app.modules.payroll.engine.jurisdictions.poland.errors import PLCalculationBlockedError
    from app.modules.payroll.engine.jurisdictions.poland.pack import PlPack
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    on = _as_date(as_of, "asOf")
    employee = _employee(db, organization_id, employee_id)
    profile = _one_active(db, _models().PayrollPlWorkerProfile, organization_id, employee.id, on, "worker profile")
    if profile is None:
        raise BadRequestException("No ACTIVE Poland worker profile is in force on that date.")
    try:
        rates, slabs, pack = resolve_tax_configuration(db, PL, payroll_date=on)
    except Exception:  # an unresolvable pack is "no pack"
        pack = None
    if pack is None:
        raise BadRequestException("No active Poland rule pack is in force on that date.")
    try:
        out = leave.annual_entitlement(PlPack({r.component_key: r for r in rates}, slabs, organization_id, on),
                                       _facts(profile))
    except PLCalculationBlockedError as blocked:
        raise BadRequestException(f"Annual leave cannot be determined ({blocked.key}): {blocked.reason}")
    return {"employeeId": employee.id, "asOf": on.isoformat(), **out}


# ── calculation inputs (selected by the PAY DATE, PL-003) ───────────────────
def resolve_pl_calc_inputs(db: Session, organization_id: int, employee, pay_date: date, run=None) -> dict:
    """Every Polish input in force ON THE PAY DATE. Nothing is inferred: a
    missing record stays None and the engine refuses with its own reason."""
    m = _models()
    entity = getattr(employee, "legal_entity_id", None)
    registration = _one_active(db, m.PayrollPlEmployerRegistration, organization_id, None, pay_date,
                               "employer registration", legal_entity_id=entity, entity_scoped=True)
    profile = _one_active(db, m.PayrollPlWorkerProfile, organization_id, employee.id, pay_date, "worker profile")
    ppk = _one_active(db, m.PayrollPlPpkParticipation, organization_id, employee.id, pay_date, "PPK participation")
    D = m.PayrollPlDeclaration
    declarations = (db.query(D).filter(D.organization_id == organization_id, D.employee_id == employee.id,
                                       D.status == "APPROVED", D.effective_from <= pay_date,
                                       (D.effective_to.is_(None)) | (D.effective_to >= pay_date))
                    .order_by(D.declaration_type, D.effective_from, D.id).all())
    return {
        "pl_pay_date": pay_date, "pl_profile": _facts(profile), "pl_registration": _facts(registration),
        "pl_ppk": _facts(ppk), "pl_declarations": [_facts(d) for d in declarations],
        "pl_ytd": pl_ytd_snapshot(db, organization_id, employee.id, entity, pay_date),
        "pl_organization_id": organization_id, "pl_legal_entity_id": entity, "pl_employee_id": employee.id,
    }


def calc_inputs(db: Session, run=None, employee=None, resolved_pack=None, as_of: Optional[date] = None,
                period=None) -> dict:
    pay_date = getattr(run, "pay_date", None) or as_of
    if pay_date is None:
        raise BadRequestException("Polish payroll needs the run's pay date: every rule is selected by it (PL-003).")
    return resolve_pl_calc_inputs(db, employee.organization_id, employee, pay_date, run=run)


# ── frozen snapshot, replay and approval fingerprint (spec §14 Replay) ─────
_CTX_DECIMALS = ("gross", "basic", "hra", "special_allowance", "overtime", "additional_compensation")
_CTX_PLAIN = ("pay_frequency", "pl_components", "pl_overtime_events", "unpaid_leave_days", "pl_organization_id",
              "pl_legal_entity_id", "pl_employee_id", "trace_id")
_CTX_DATES = ("pay_date", "pl_pay_date", "period_start", "period_end")
_RECORD_KEYS = ("pl_profile", "pl_registration", "pl_ppk")
_RATE_FIELDS = ("component_key", "label", "employee_rate_pct", "employer_rate_pct", "flat_amount", "text_value",
                "effective_from", "effective_to")
_SLAB_FIELDS = ("id", "rule_type", "filing_status", "tax_regime", "assessment_basis", "rate_label", "rate_pct",
                "min_amount", "max_amount", "flat_amount", "sort_order", "effective_from", "effective_to")
# Never frozen: identifier references and free-text evidence stay in their tables.
_FROZEN_RECORD_EXCLUDE = ("pesel_vault_id", "nip_vault_id", "nrs_vault_id", "filing_credential_ref",
                          "bank_export_ref")


def _record_for_freeze(record):
    if record is None:
        return None
    return {k: v for k, v in dict(record).items() if k not in _FROZEN_RECORD_EXCLUDE}


def pl_freeze_context(ctx, calculation_mode: str = "standard") -> dict:
    def pick(row, fields):
        return {f: (row.get(f) if isinstance(row, dict) else getattr(row, f, None)) for f in fields}

    return _json_safe({
        "version": 1, "calculationMode": calculation_mode,
        "ctx": {k: getattr(ctx, k, None) for k in _CTX_DECIMALS + _CTX_PLAIN + _CTX_DATES},
        "records": {k: _record_for_freeze(getattr(ctx, k, None)) for k in _RECORD_KEYS},
        "declarations": list(getattr(ctx, "pl_declarations", None) or []),
        "ytd": getattr(ctx, "pl_ytd", None),
        "rateMap": {k: pick(r, _RATE_FIELDS) for k, r in (getattr(ctx, "rate_map", None) or {}).items()},
        "slabs": [pick(s, _SLAB_FIELDS) for s in (getattr(ctx, "slabs", None) or [])],
    })


def pl_thaw_context(frozen: dict):
    """The engine reads records, rows and dates through tolerant readers (ISO
    strings, decimal strings), so the frozen JSON is replayed as-is; only the
    platform's money fields are restored to Decimal."""
    from app.modules.payroll.engine.base import PayrollContext

    if not frozen or frozen.get("version") != 1:
        raise BadRequestException("This payslip has no replayable Poland calculation context.")
    ctx = {}
    for key, value in (frozen.get("ctx") or {}).items():
        if key in _CTX_DECIMALS:
            ctx[key] = None if value in (None, "") else Decimal(str(value))
        elif key in _CTX_DATES:
            ctx[key] = None if value in (None, "") else date.fromisoformat(str(value)[:10])
        else:
            ctx[key] = value
    for key in ("gross", "basic"):
        ctx[key] = ctx.get(key) if ctx.get(key) is not None else Decimal("0")
    records = frozen.get("records") or {}
    return PayrollContext(
        **{k: v for k, v in ctx.items() if v is not None}, country=PL,
        **{k: records.get(k) for k in _RECORD_KEYS},
        pl_declarations=list(frozen.get("declarations") or []),
        pl_ytd=frozen.get("ytd"),
        rate_map=dict(frozen.get("rateMap") or {}),
        slabs=list(frozen.get("slabs") or []),
    )


def pl_replay(frozen: dict):
    """Recalculate a frozen Poland payslip exactly as it was calculated."""
    from app.modules.payroll.engine.resolver import calculate_payroll

    return calculate_payroll(pl_thaw_context(frozen), frozen.get("calculationMode") or "standard")


def pl_payslip_snapshot(result, frozen: Optional[dict] = None) -> Optional[dict]:
    r = result.get("pl_result") if isinstance(result, dict) else getattr(result, "pl_result", None)
    if not r:
        return None
    snapshot = dict(r)
    if frozen is not None:
        snapshot["frozenContext"] = frozen
    return _json_safe(snapshot)


def _run_items(db: Session, run) -> list:
    from app.modules.payroll.models import PayslipItem

    return (db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == PL)
            .order_by(PayslipItem.id).all())


def pl_approval_fingerprint(db: Session, run) -> Optional[str]:
    items = _run_items(db, run)
    if not items:
        return None
    payload = [{"employeeId": item.employee_id, "hashes": (item.pl_calculation_snapshot or {}).get("hashes"),
                "net": (item.pl_calculation_snapshot or {}).get("pl_net")} for item in items]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ── preflight and run transitions (spec §12 payroll preflight) ──────────────
def _pack_in_force(db: Session, on: date):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    try:
        _rates, _slabs, pack = resolve_tax_configuration(db, PL, payroll_date=on)
    except Exception:  # an unresolvable pack is "no pack"; the engine blocks on its own
        return None
    return pack


def pl_run_preflight(db: Session, run) -> list:
    from app.modules.payroll.models import PayrollEmployee

    problems = []
    if _pack_in_force(db, run.pay_date) is None:
        problems.append({"code": "CONTENT_PACK_OUT_OF_DATE", "employeeId": None,
                         "message": "No active Poland rule pack is in force on the pay date."})
    m = _models()
    for item in _run_items(db, run):
        employee = db.get(PayrollEmployee, item.employee_id)
        snapshot = item.pl_calculation_snapshot
        if snapshot is None:
            problems.append({"code": "PL_SNAPSHOT_MISSING", "employeeId": item.employee_id,
                             "message": "No frozen Poland calculation; recalculate the run."})
        else:
            for exception in snapshot.get("exceptions") or []:
                problems.append({"code": exception.get("code"), "employeeId": item.employee_id,
                                 "message": exception.get("detail") or "A statutory exception needs resolving."})
        registration = _one_active(db, m.PayrollPlEmployerRegistration, run.organization_id, None, run.pay_date,
                                   "employer registration",
                                   legal_entity_id=getattr(employee, "legal_entity_id", None), entity_scoped=True)
        if registration is None:
            problems.append({"code": "PL_REGISTRATION_MISSING", "employeeId": item.employee_id,
                             "message": "No ACTIVE Poland employer registration covers the pay date."})
        elif registration.verification_state != "VERIFIED":
            problems.append({"code": "PL_REGISTRATION_NOT_VERIFIED", "employeeId": item.employee_id,
                             "message": "The Poland employer registration is not verified (PL-001)."})
        profile = _one_active(db, m.PayrollPlWorkerProfile, run.organization_id, item.employee_id, run.pay_date,
                              "worker profile")
        passport = (getattr(employee, "compliance_fields", None) or {}).get("passport_number")
        if profile is None or (profile.pesel_vault_id is None and not passport):
            problems.append({"code": "MISSING_IDENTIFIER", "employeeId": item.employee_id,
                             "message": "A PESEL in the vault (or a passport number) is required for ZUS reporting."})
        if profile is not None and profile.insurance_title_code is None:
            problems.append({"code": "ZUS_TITLE_MISSING", "employeeId": item.employee_id,
                             "message": "The ZUS insurance title code is not recorded."})
    return problems


def post_accumulators(db: Session, run, actor_id) -> int:
    """Post every PL payslip's accumulator deltas once (idempotent per
    payslip + accumulator; the database also refuses a second RUN post)."""
    from app.modules.payroll.models import PayrollEmployee

    Entry = _models().PayrollPlAccumulatorEntry
    added = 0
    for item in _run_items(db, run):
        snapshot = item.pl_calculation_snapshot or {}
        employee = db.get(PayrollEmployee, item.employee_id)
        result_hash = (snapshot.get("hashes") or {}).get("input")
        for accumulator, amount in (snapshot.get("accumulatorDeltas") or {}).items():
            if db.query(Entry.id).filter(Entry.payslip_item_id == item.id, Entry.accumulator == accumulator,
                                         Entry.entry_kind == "RUN").first():
                continue
            db.add(Entry(organization_id=run.organization_id,
                         legal_entity_id=getattr(employee, "legal_entity_id", None), employee_id=item.employee_id,
                         year=run.pay_date.year, accumulator=accumulator, pay_date=run.pay_date,
                         amount=Decimal(str(amount)), entry_kind="RUN", run_id=run.id, payslip_item_id=item.id,
                         result_hash=result_hash, created_by_id=actor_id))
            added += 1
    db.flush()
    return added


def before_run_transition(db: Session, run, next_status, actor_id) -> None:
    """Approval needs every PL payslip frozen, a verified employer registration,
    the identifiers ZUS reporting needs and no open statutory exception; later
    steps re-verify the approval fingerprint; PAID posts the year-to-date
    ledger exactly once."""
    from fastapi import HTTPException, status as http_status

    from app.modules.payroll.models import PayrollStatus

    if not _run_items(db, run):
        return
    if next_status == PayrollStatus.APPROVED:
        problems = pl_run_preflight(db, run)
        if problems:
            listing = "; ".join(f"{p['code']}" + (f" (employee #{p['employeeId']})" if p["employeeId"] else "")
                                for p in problems)
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=f"Poland: the run cannot be approved: {listing}")
        run.pl_approval_fingerprint = pl_approval_fingerprint(db, run)
        return
    if next_status in (PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        if not run.pl_approval_fingerprint or pl_approval_fingerprint(db, run) != run.pl_approval_fingerprint:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                "Poland: the approved calculation no longer matches this run - recalculate and approve again."))
    if next_status == PayrollStatus.PAID:
        post_accumulators(db, run, actor_id)


# ── platform hooks ──────────────────────────────────────────────────────────
def _pl_statutory_profile_errors(data) -> list:
    # Polish statutory facts live in the effective-dated payroll_pl_* records,
    # never on the shared statutory profile.
    return []


def _pl_profile_values(db: Session, employee, data, previous) -> dict:
    return {}


def _pl_pack_activation_refusal(db: Session, pack, actor_id=None) -> Optional[str]:
    return pl_pack_activation_refusal(db, pack, actor_id)


def _pl_pack_holidays(db: Session, year: int) -> list:
    # Polish public holidays arrive as signed content with the labour phase (P5);
    # nothing is seeded from a guessed list.
    return []


def _pl_template_activation_refusal(db: Session, template, actor_id=None) -> Optional[str]:
    country = (getattr(template, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(template, "report_type", "") or "").upper()
    if country != PL and not report_type.startswith("PL_"):
        return None
    return ("Poland ZUS / PIT form templates stay inactive until the official schemas are archived and the "
            "filing path is certified (gate G4, PL-019).")


def _pl_payment_treatment(db: Session, organization_id: int, run, items: list) -> dict:
    return {}


def _pl_payslip_hold_view(item) -> Optional[dict]:
    return None


def _pl_statutory_editors(db: Session, pack) -> set:
    # The governed Poland signing console arrives in Phase 7.
    return set()


PL_RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and the frozen PL calculation snapshot"),
    ("TAX_RECORDS", "PIT advances, PIT-2 / cost / relief statements and the year-to-date ledger"),
    ("SOCIAL_INSURANCE_RECORDS", "ZUS, health, employer funds and PPK records"),
    ("EMPLOYEE_IDENTITY", "Identifier vault metadata (PESEL / NIP) and worker statutory profiles"),
    ("ACCESS_LOGS", "Identifier access events"),
)
PL_DECISIONS = {
    "D-1": ("Hybrid architecture: ZA layout, NZ-style engine and records", False),
    "D-2": ("First release: umowa o pracę on monthly pay only", False),
    "D-3": ("Content pack PL-PAYROLL-2026; 2027 only when sourced", False),
    "D-4": ("Append-only accumulator ledger", False),
    "D-5": ("Filing payloads only; no live authority transport", False),
    "D-6": ("No override table; explicit correction objects", False),
    "D-7": ("Retention period for Polish payroll and filing records", True),
}


def _evidence(db: Session, tag: str):
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact).filter(SourceArtifact.form_number == tag,
                                            SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    accepted = next((r for r in rows if r.reviewer_id and r.file_path and r.reviewer_id != r.created_by_id), None)
    return accepted, bool(rows)


def owner_decisions(db: Session) -> list:
    out = []
    for key, (label, blocks) in PL_DECISIONS.items():
        accepted, submitted = _evidence(db, f"PL-DECISION-{key}")
        out.append({"key": key, "label": label, "blocksLaunch": blocks, "evidenceTag": f"PL-DECISION-{key}",
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


def _decision_state(db: Session, key: str) -> str:
    return next((d["state"] for d in owner_decisions(db) if d["key"] == key), "OPEN")


def _retention_employee(db: Session, employee_id: int, organization_id: int) -> None:
    employee = _employee(db, organization_id, employee_id)
    if (getattr(employee, "country_code", None) or "").upper() != PL:
        raise NotFoundException("Polish employee")


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    m = _models()
    for model, label in ((m.PayrollPlWorkerProfile, "worker statutory profiles"),
                         (m.PayrollPlDeclaration, "employee statements"),
                         (m.PayrollPlAccumulatorEntry, "year-to-date ledger")):
        if db.query(model.id).filter(model.organization_id == organization_id,
                                     model.employee_id == employee_id).first():
            return label
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    m = _models()
    return db.query(m.PayrollPlWorkerProfile.id).filter(
        m.PayrollPlWorkerProfile.employee_id == employee_id).first() is not None


def _is_report(report) -> bool:
    country = (getattr(report, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(report, "report_type", "") or "").upper()
    return country == PL or report_type.startswith("PL_")


def _pl_retention_settings():
    # The platform calls this hook with NO arguments (retention_service.settings).
    from app.modules.payroll.retention_service import RetentionJurisdiction

    return RetentionJurisdiction(
        country=PL, label="Poland", categories=PL_RETENTION_CATEGORIES, period_decision="D-7", end_decision="D-7",
        decision_reference="PL-RETENTION", decision_state=_decision_state,
        validate_employee=_retention_employee, retained_record_label=_retained_record_label,
        has_statutory_profile=_has_statutory_profile, report_matches=_is_report)


def pl_unmet_requirements(db: Session) -> list:
    """Every unmet launch requirement. The G1-G7 release-gate evaluation is
    built in Phase 9; until then Poland can never leave PLANNED."""
    out = [{"key": "PL-GATES", "label": "Release gates G1-G7",
            "detail": "The Poland release-gate evaluation is not built yet (Phase 9)."}]
    out += [{"key": f"PL-DECISION-{d['key']}", "label": d["label"], "detail": d["state"]}
            for d in owner_decisions(db) if d["blocksLaunch"] and d["state"] != "RECORDED"]
    return out


def statutory_summary(db: Session) -> dict:
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    m = _models()
    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == PL)
             .order_by(JurisdictionPack.effective_from.desc()).all())
    marker = f"%{PENDING_G1_SUFFIX.strip()}%"
    pending = sum(
        db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == p.id,
                                          ContributionRate.label.like(marker)).count()
        + db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == p.id, TaxSlab.rate_label.like(marker)).count()
        for p in packs)

    def active(model):
        return db.query(model).filter(model.status == STATUS_ACTIVE).count()

    return {
        "jurisdiction": PL, "spec": SPEC, "available": False,
        "packs": [{"id": p.id, "packId": p.pack_id, "version": p.version, "status": p.status,
                   "effectiveFrom": p.effective_from.isoformat() if p.effective_from else None,
                   "effectiveTo": p.effective_to.isoformat() if p.effective_to else None} for p in packs],
        "pendingRows": pending,
        "activeEmployerRegistrations": active(m.PayrollPlEmployerRegistration),
        "verifiedEmployerRegistrations": db.query(m.PayrollPlEmployerRegistration).filter(
            m.PayrollPlEmployerRegistration.status == STATUS_ACTIVE,
            m.PayrollPlEmployerRegistration.verification_state == "VERIFIED").count(),
        "activeWorkerProfiles": active(m.PayrollPlWorkerProfile),
        "approvedStatements": db.query(m.PayrollPlDeclaration).filter(
            m.PayrollPlDeclaration.status == "APPROVED").count(),
        "decisions": owner_decisions(db),
        "unmet": pl_unmet_requirements(db),
        "note": "Poland stays PLANNED until every release gate G1-G7 and owner decision passes.",
    }


def _pl_service_registry_transition(db: Session, target: str, reason: str, actor_id=None, as_of=None):
    from app.modules.payroll import service

    def readiness():
        return pl_unmet_requirements(db), {}

    return service.transition_service_registry(
        db, PL, target, reason, actor_id, label="Poland", readiness=readiness,
        invalid_target_message=lambda t: (f"Poland availability can only be {service.SERVICE_REGISTRY_OPEN} "
                                          f"or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no Poland registry row - seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Poland is {a}; only PLANNED moves to AVAILABLE.")


JURISDICTION_HOOKS = {
    "calc_inputs": "calc_inputs",
    "before_run_transition": "before_run_transition",
    "statutory_profile_errors": "_pl_statutory_profile_errors",
    "statutory_profile_values": "_pl_profile_values",
    "pack_activation_refusal": "_pl_pack_activation_refusal",
    "retention_settings": "_pl_retention_settings",
    "service_registry_transition": "_pl_service_registry_transition",
    "statutory_summary": "statutory_summary",
    "statutory_editors": "_pl_statutory_editors",
    "template_activation_refusal": "_pl_template_activation_refusal",
    "pack_holidays": "_pl_pack_holidays",
    "payment_treatment": "_pl_payment_treatment",
    "payslip_hold_view": "_pl_payslip_hold_view",
}


# ── employee summary (for the Phase 7 panel; identifiers masked) ────────────
def employee_summary(db: Session, organization_id: int, employee_id: int) -> dict:
    m = _models()
    _employee(db, organization_id, employee_id)

    def versions(model):
        return [_json_safe(_facts(r)) for r in db.query(model).filter(
            model.organization_id == organization_id, model.employee_id == employee_id).order_by(model.id)]

    return {"employeeId": employee_id, "identifiers": list_pl_identifiers(db, organization_id, employee_id),
            "workerProfiles": versions(m.PayrollPlWorkerProfile),
            "statements": versions(m.PayrollPlDeclaration),
            "ppk": versions(m.PayrollPlPpkParticipation)}
