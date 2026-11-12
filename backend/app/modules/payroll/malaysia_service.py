"""
modules/payroll/malaysia_service.py
-----------------------------------
Malaysia statutory workflows (ZP-MY-ENG-001) — the ONLY Malaysia service
module, on the shared platform the same way poland_service.py is.

Phase 1 (this section): seeding the canonical MY-PAYROLL-2026 Draft pack
from engine/countries/malaysia_content.py, the activation refusal that keeps
a pack carrying any unsigned, unconfigured or empty content from ever
becoming Active, and Malaysia's PLANNED service-registry row.

Every seeded row is UNSIGNED ("[PENDING G1]"): a value taken from a document
— even the specification — is "extracted", not verified. Rows become usable
only when signed through my_super_admin (source stored, hashed and reviewed
by a second Super Admin).
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

MY = "MY"
SPEC = "ZP-MY-ENG-001 v1.0"
PENDING_G1_SUFFIX = " [PENDING G1]"
NOT_CONFIGURED = "NOT CONFIGURED"


def _content():
    from app.modules.payroll.engine.countries import malaysia_content as content

    return content


def pending_label(label: str, limit: int) -> str:
    """An UNSIGNED label: the [PENDING G1] marker always fits."""
    return label[:limit - len(PENDING_G1_SUFFIX)] + PENDING_G1_SUFFIX


def rate_total(ee, er, flat, text) -> str:
    """The display `total` of a ContributionRate row."""
    if ee is not None or er is not None:
        return " / ".join(f"{v}%" for v in (ee, er) if v is not None)[:50]
    if text is None and flat is None:
        return NOT_CONFIGURED
    return str(text if text is not None else flat)[:50]


def seed_sources(db: Session) -> dict:
    """One SourceArtifact per evidence-register entry (S1–S15), reused if present.
    Seeded artifacts carry no file: they are references, not archived evidence."""
    from app.modules.payroll.models import SourceArtifact

    content = _content()
    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-MY-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency[:200]).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form,
                                      source_url=content.SOURCE_URLS.get(code))
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id
    return sources


def seed_malaysia_pack(db: Session, *, effective_from: date = date(2026, 1, 1),
                       status: str = "Draft") -> "JurisdictionPack":
    """Write malaysia_content.py into the MY-PAYROLL-2026 tax pack:
      * every scalar parameter (ContributionRate) in the slot its kind names,
        with its own legal effective dates where it has one, territorial rows
        carrying jurisdiction_state = territory;
      * every earning-classification row (TaxSlab rule_type="MY_EARNING_CLASS");
      * NO schedule, holiday or PCB-table rows — those come from the official
        documents through the workbook.
    Every row is written UNSIGNED. Draft only; a pack that has left Draft is
    never rewritten, and a Draft pack's canonical rows are replaced wholesale
    (organisation-scoped rows are never touched)."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    content = _content()
    if status != "Draft":
        raise ValueError("seed_malaysia_pack only writes Draft content")
    pack_id, window_from, window_to = content.MY_2026
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")
    sources = seed_sources(db)

    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=MY, pack_type="tax",
                                effective_from=effective_from or window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_to = window_to
    pack.tax_year = content.TAX_YEAR
    pack.currency = content.CURRENCY
    pack.regulatory_authority = "HASiL / KWSP (EPF) / PERKESO / HRD Corp / MOHR (JTK Peninsular, Sabah, Sarawak)"
    pack.source_document_id = sources["S1"]
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                      ContributionRate.organization_id.is_(None)).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                             TaxSlab.organization_id.is_(None)).delete()

    def dec(value):
        return Decimal(str(value)) if value is not None else None

    order = 0
    for (key, label, ee, er, flat, text, src, _spec, eff_from, eff_to, _basis, territory) \
            in content.MALAYSIA_SCALAR_CONTENT:
        order += 1
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=MY,
            jurisdiction_state=territory, component_key=key, label=pending_label(label, 100),
            employee_share=(f"{ee}%" if ee is not None else "—")[:50],
            employer_share=(f"{er}%" if er is not None else "—")[:50],
            total=rate_total(ee, er, flat, text),
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er), flat_amount=dec(flat), text_value=text,
            effective_from=eff_from, effective_to=eff_to, source_document_id=sources.get(src), sort_order=order))

    for (obligation, treatment, component, label, src) in content.MALAYSIA_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=MY,
            rule_type=content.MY_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=pending_label(label, 150), tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))
    db.flush()
    return pack


def my_pack_activation_refusal(db: Session, pack, actor_id: Optional[int] = None) -> Optional[str]:
    """Why a Malaysian pack must NOT be activated, or None.

    Refused while ANY canonical row is unsigned ([PENDING G1]), NOT
    CONFIGURED or PENDING_G1, while a row has no source document, or while a
    required table (EPF / PERKESO / EIS / foreign-worker schedules, public
    holidays) holds no rows (spec §16 G1: NO-GO if a supported result relies
    on guessed or uncited content; MY-005 schedules are legal content)."""
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if (getattr(pack, "jurisdiction_country", None) or "").upper() != MY:
        return None
    content = _content()
    marker = PENDING_G1_SUFFIX.strip()
    rates = (db.query(ContributionRate)
             .filter(ContributionRate.jurisdiction_pack_id == pack.id,
                     ContributionRate.organization_id.is_(None)).all())
    if not rates:
        return "Malaysia pack has no statutory content — seed it from malaysia_content.py first."
    unsigned = sorted(r.component_key for r in rates
                      if marker in (r.label or "") or r.total == NOT_CONFIGURED
                      or (r.text_value or "") == content.PENDING)
    if unsigned:
        shown = ", ".join(unsigned[:8]) + (f" (+{len(unsigned) - 8} more)" if len(unsigned) > 8 else "")
        return (f"Malaysia pack {pack.pack_id} still has {len(unsigned)} unsigned or unconfigured row(s): "
                f"{shown}. Gate G1 must sign them before activation (ZP-MY-ENG-001 §16).")
    unsourced = sorted(r.component_key for r in rates if r.source_document_id is None)
    if unsourced:
        return f"Malaysia pack {pack.pack_id} has rows without a source document: {', '.join(unsourced[:8])}."
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                      TaxSlab.organization_id.is_(None)).all())
    unsigned_slabs = [s for s in slabs if marker in (s.rate_label or "")]
    if unsigned_slabs:
        kinds = sorted({s.rule_type for s in unsigned_slabs})
        return (f"Malaysia pack {pack.pack_id} still has {len(unsigned_slabs)} unsigned table row(s) "
                f"({', '.join(kinds)}).")
    present = {s.rule_type for s in slabs}
    missing = [rule for rule in content.REQUIRED_TABLES if rule not in present]
    if missing:
        return (f"Malaysia pack {pack.pack_id} has no rows for: {', '.join(missing)} — load them from the "
                "official schedules (MY-005).")
    return None


def ensure_my_service_registry_row(db: Session) -> str:
    """Malaysia's jurisdiction_service_registry row, PLANNED, created only when
    missing — an existing row is never changed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == MY).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=MY, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


# ══════════════════════════════════════════════════════════════════════════
# Phase 5 — records, declarations, vault, calculation inputs, run lifecycle,
# and the 13 platform hooks (registered in jurisdiction_hooks._MODULES).
#
#   * versioned records with a second person's approval — employer
#     registrations (+ verification), worker statutory profiles, work
#     assignments (territory + holiday state, MY-003); never edited in place;
#   * tax declarations TP1 / TP3 / CP38 / zakat / tax borne / EPF voluntary
#     excess (MY-010): evidence, four-eyes, supersession, withdrawal; an
#     approved TP3 posts evidenced PRIOR_EMPLOYER ledger entries;
#   * the identifier vault (spec §15, MY-029): NRIC / TIN / EPF / SOCSO /
#     work-pass numbers encrypted, masked everywhere, single-use reveal
#     requested and approved by two people;
#   * calculation inputs selected by the PAY DATE (+ the pay period, MY-006),
#     frozen snapshot / replay, approval fingerprint, run preflight and the
#     year-to-date ledger posted exactly once at PAID.
# ══════════════════════════════════════════════════════════════════════════
import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402
from decimal import InvalidOperation  # noqa: E402

from app.core.exceptions import BadRequestException, NotFoundException  # noqa: E402

STATUS_DRAFT, STATUS_ACTIVE, STATUS_SUPERSEDED = "DRAFT", "ACTIVE", "SUPERSEDED"


def _models():
    from app.modules.payroll import models as m

    return m


def _as_date(value, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise BadRequestException(f"{name} must be an ISO date (YYYY-MM-DD).")


def _as_datetime(value, name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise BadRequestException(f"{name} must be an ISO date-time.")


def _decimal(value, name: str) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BadRequestException(f"{name} must be a decimal number.")


def _bool(value, name: str) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise BadRequestException(f"{name} must be true or false.")


def _reason(reason) -> str:
    text = (reason or "").strip()
    if not text:
        raise BadRequestException("A reason is required for every Malaysia statutory change (spec §15 audit).")
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
        raise NotFoundException("Malaysian employee")
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
MY_REGISTRATION_FIELDS = (
    "effective_from", "effective_to", "legal_entity_id", "legal_name", "hasil_employer_no", "epf_employer_no",
    "perkeso_employer_code", "hrd_category", "hrd_registration_no", "hrd_category_from",
    "hrd_category_evidence_ref", "my_journal_accounts", "bank_export_ref", "filing_credential_ref",
    "source_document_id", "evidence_ref")
MY_PROFILE_FIELDS = (
    "effective_from", "effective_to", "legal_entity_id", "contract_type", "pay_frequency", "citizenship",
    "date_of_birth", "tax_residence", "residence_evidence_ref", "residence_from", "residence_to", "work_pass_type",
    "work_pass_valid_from", "work_pass_valid_to", "epf_member_class", "epf_member_since", "socso_category",
    "eis_state", "manual_worker", "normal_hours_week", "rest_day", "service_start", "nric_vault_id",
    "tin_vault_id", "epf_vault_id", "socso_vault_id", "work_pass_vault_id", "evidence_ref")
MY_ASSIGNMENT_FIELDS = ("effective_from", "effective_to", "legal_entity_id", "labour_territory", "holiday_state",
                        "work_location_label", "remote", "assignment_reason", "evidence_ref")
MY_DECLARATION_FIELDS = ("declaration_type", "tax_year", "value", "received_at", "effective_from", "effective_to",
                         "source_channel", "legal_entity_id", "evidence_ref")
CONTRACT_TYPES = ("CONTRACT_OF_SERVICE", "GIG_PLATFORM", "DOMESTIC", "PUBLIC_SECTOR", "OTHER")
PAY_FREQUENCIES = ("MONTHLY", "SEMI_MONTHLY", "WEEKLY", "OTHER")
ASSIGNMENT_REASONS = ("HIRE", "TRANSFER", "ASSIGNMENT", "CORRECTION")
REST_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
SOURCE_CHANNELS = ("PAPER", "ELECTRONIC", "EMPLOYEE_PORTAL", "AUTHORITY", "IMPORT")
# Holiday states that lie in the Sabah / Sarawak labour territories; every
# other state and federal territory (Labuan included) is Peninsular + Labuan
# (MY-024: geography, not statutory content).
_TERRITORY_OF_STATE = {"SBH": "SABAH", "SWK": "SARAWAK"}
# Profile vault references -> the identifier type each must hold.
_PROFILE_VAULT_KEYS = {"nric_vault_id": "NRIC", "tin_vault_id": "TIN", "epf_vault_id": "EPF_NO",
                       "socso_vault_id": "SOCSO_NO", "work_pass_vault_id": "WORK_PASS_NO"}

_DATE_FIELDS = {"effective_from", "effective_to", "hrd_category_from", "date_of_birth", "residence_from",
                "residence_to", "work_pass_valid_from", "work_pass_valid_to", "epf_member_since", "service_start"}
_DECIMAL_FIELDS = {"normal_hours_week"}
_INT_FIELDS = {"legal_entity_id", "source_document_id", "tax_year", *_PROFILE_VAULT_KEYS}
_BOOL_FIELDS = {"manual_worker", "remote"}
_JSON_FIELDS = {"my_journal_accounts", "value"}


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


# ── versioned records with a second person's approval (spec §15 four-eyes) ─
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
        raise NotFoundException(f"Malaysia {label.replace('my_', '').replace('_', ' ')}")
    if row.status != STATUS_DRAFT:
        raise BadRequestException(f"Only a DRAFT {label.replace('_', ' ')} can be approved.")
    require_four_eyes(row.created_by_id, actor_id, f"Approving a Malaysia {label.replace('_', ' ')}",
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
        raise BadRequestException(f"Two ACTIVE Malaysia {label} versions overlap on {on.isoformat()}.")
    return rows[0] if rows else None


def _reference(data: dict, key: str, label: str) -> None:
    """Employer reference numbers: letters / digits only, at most 20 (the exact
    authority formats are pending G1 - never a guessed pattern)."""
    value = data.get(key)
    if value is None:
        return
    value = value.replace(" ", "").replace("-", "").upper()
    if not (value.isalnum() and 1 <= len(value) <= 20):
        raise BadRequestException(f"{label} must be 1-20 letters or digits.")
    data[key] = value


# ── employer registrations (spec §12, MY-016) ───────────────────────────────
_REFERENCE_LABELS = (("hasil_employer_no", "The HASiL employer number"), ("epf_employer_no", "The EPF employer number"),
                     ("perkeso_employer_code", "The PERKESO employer code"),
                     ("hrd_registration_no", "The HRD Corp registration number"))


def record_my_employer_registration(db: Session, organization_id: int, payload: dict, actor_id, reason=None):
    reason = _reason(reason)
    content = _content()
    data = _clean(payload, MY_REGISTRATION_FIELDS,
                  required=("effective_from", "legal_name", "hasil_employer_no", "hrd_category"))
    _legal_entity(db, organization_id, data.get("legal_entity_id"))
    _enum(data, "hrd_category", content.HRD_CATEGORIES)
    for key, label in _REFERENCE_LABELS:
        _reference(data, key, label)
    if data["hrd_category"] != "NOT_REGISTERED" and not (data.get("hrd_registration_no")
                                                         and data.get("hrd_category_from")
                                                         and data.get("hrd_category_evidence_ref")):
        raise BadRequestException("An HRD category needs the registration number, its start date and evidence "
                                  "(MY-016: never inferred from headcount).")
    return _create_version(db, _models().PayrollMyEmployerRegistration, organization_id, None, data, actor_id,
                           "my_employer_registration", reason, entity_scoped=True)


def approve_my_employer_registration(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollMyEmployerRegistration, organization_id, row_id, actor_id,
                            "my_employer_registration", entity_scoped=True)


def verify_my_employer_registration(db: Session, organization_id: int, row_id: int, actor_id, outcome, reason):
    from app.modules.payroll.service import require_four_eyes

    reason = _reason(reason)
    R = _models().PayrollMyEmployerRegistration
    row = db.query(R).filter(R.id == row_id, R.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Malaysia employer registration")
    outcome = str(outcome or "").strip().upper()
    if outcome not in ("VERIFIED", "REJECTED"):
        raise BadRequestException("outcome must be VERIFIED or REJECTED.")
    if row.status != STATUS_ACTIVE:
        raise BadRequestException("Only an ACTIVE employer registration is verified.")
    require_four_eyes(row.created_by_id, actor_id, "Verifying a Malaysia employer registration", db=db,
                      entity_type="my_employer_registration", entity_id=row.id, current_status=row.status)
    old = row.verification_state
    row.verification_state = outcome
    db.flush()
    _audit(db, actor_id, "verified", "my_employer_registration", row.id, old={"verification_state": old},
           new={"verification_state": outcome}, reason=reason)
    return row


# ── worker statutory profile (spec §4, MY-004 / MY-007) ─────────────────────
def record_my_worker_profile(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id,
                             reason=None):
    reason = _reason(reason)
    content = _content()
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, MY_PROFILE_FIELDS, required=("effective_from", "contract_type", "pay_frequency"))
    _enum(data, "contract_type", CONTRACT_TYPES)
    _enum(data, "pay_frequency", PAY_FREQUENCIES)
    _enum(data, "citizenship", content.CITIZENSHIP)
    _enum(data, "tax_residence", content.TAX_RESIDENCE)
    _enum(data, "work_pass_type", content.WORK_PASS_TYPES)
    _enum(data, "epf_member_class", content.EPF_MEMBER_CLASSES)
    _enum(data, "socso_category", content.SOCSO_CATEGORIES)
    _enum(data, "eis_state", content.EIS_STATES)
    _enum(data, "rest_day", REST_DAYS)
    data["tax_residence"] = data.get("tax_residence") or "REVIEW_REQUIRED"
    if data["tax_residence"] != "REVIEW_REQUIRED" and not (data.get("residence_evidence_ref")
                                                           and data.get("residence_from")):
        raise BadRequestException("A tax residence needs its evidence and start date; it is never inferred "
                                  "from citizenship (MY-007).")
    if data.get("citizenship") == "NON_CITIZEN" and data.get("work_pass_type") in (None, "NONE"):
        raise BadRequestException("A non-citizen needs the work pass type.")
    if data.get("normal_hours_week") is not None and data["normal_hours_week"] <= 0:
        raise BadRequestException("normal_hours_week must be positive.")
    for key, kind in _PROFILE_VAULT_KEYS.items():
        if data.get(key) is not None:
            _vault_for_employee(db, organization_id, employee.id, data[key], kind)
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    return _create_version(db, _models().PayrollMyWorkerProfile, organization_id, employee.id, data, actor_id,
                           "my_worker_profile", reason)


def approve_my_worker_profile(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollMyWorkerProfile, organization_id, row_id, actor_id,
                            "my_worker_profile")


# ── work assignment: labour territory + holiday state (MY-001 / MY-003) ─────
def record_my_work_assignment(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id,
                              reason=None):
    reason = _reason(reason)
    content = _content()
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, MY_ASSIGNMENT_FIELDS,
                  required=("effective_from", "labour_territory", "holiday_state", "assignment_reason"))
    _enum(data, "labour_territory", content.TERRITORIES)
    _enum(data, "holiday_state", content.HOLIDAY_STATES)
    _enum(data, "assignment_reason", ASSIGNMENT_REASONS)
    expected = _TERRITORY_OF_STATE.get(data["holiday_state"], "PENINSULAR_LABUAN")
    if data["labour_territory"] != expected:
        raise BadRequestException(f"Holiday state {data['holiday_state']} lies in {expected}, not "
                                  f"{data['labour_territory']} (MY-003: a conflicting location is never resolved "
                                  f"by guessing).")
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    return _create_version(db, _models().PayrollMyWorkAssignment, organization_id, employee.id, data, actor_id,
                           "my_work_assignment", reason)


def approve_my_work_assignment(db: Session, organization_id: int, row_id: int, actor_id):
    return _approve_version(db, _models().PayrollMyWorkAssignment, organization_id, row_id, actor_id,
                            "my_work_assignment")


# ── tax declarations (MY-010) ───────────────────────────────────────────────
_TP3_ACCUMULATORS = ("PCB_GROSS_NORMAL", "PCB_GROSS_ADDITIONAL", "PCB_PAID", "PCB_EPF_RELIEF_USED", "ZAKAT_PAID")


def _money_value(value: dict, name: str, *, positive: bool = False) -> None:
    number = _decimal(value.get(name), name)
    if number is None or number < 0 or (positive and number == 0):
        raise BadRequestException(f"The declaration needs {name} ({'> 0' if positive else '>= 0'}).")
    value[name] = str(number)


def _declaration_value(kind: str, value) -> dict:
    """Shape checks only; how PCB treats each value is Phase 4 (S1)."""
    value = dict(value or {})
    if kind == "TP3":
        amounts = value.get("accumulators")
        if not isinstance(amounts, dict) or not amounts:
            raise BadRequestException("A TP3 declaration needs the prior employer's accumulators.")
        if set(amounts) - set(_TP3_ACCUMULATORS):
            raise BadRequestException(f"TP3 accumulators must be among: {', '.join(_TP3_ACCUMULATORS)}.")
        for name in list(amounts):
            _money_value(amounts, name)
        if not str(value.get("priorEmployer") or "").strip():
            raise BadRequestException("A TP3 declaration names the prior employer.")
    elif kind == "CP38":
        _money_value(value, "amount", positive=True)
        if not str(value.get("instructionRef") or "").strip():
            raise BadRequestException("A CP38 instruction needs its HASiL reference.")
    elif kind == "ZAKAT":
        _money_value(value, "amount", positive=True)
    elif kind == "TP1":
        claims = value.get("claims")
        if not isinstance(claims, dict) or not claims:
            raise BadRequestException("A TP1 declaration needs its claims.")
        for name in list(claims):
            _money_value(claims, name)
    elif kind == "EPF_VOLUNTARY_EXCESS":
        _money_value(value, "ratePct", positive=True)
    return value


def record_my_declaration(db: Session, organization_id: int, employee_id: int, payload: dict, actor_id):
    content = _content()
    employee = _employee(db, organization_id, employee_id)
    data = _clean(payload, MY_DECLARATION_FIELDS,
                  required=("declaration_type", "received_at", "effective_from", "source_channel", "evidence_ref"))
    _enum(data, "declaration_type", content.DECLARATION_TYPES)
    _enum(data, "source_channel", SOURCE_CHANNELS)
    data["tax_year"] = data.get("tax_year") or data["effective_from"].year
    if data["tax_year"] != data["effective_from"].year or (
            data.get("effective_to") and data["effective_to"].year != data["tax_year"]):
        raise BadRequestException("A Malaysian tax declaration covers one tax year (its effective dates lie "
                                  "inside it).")
    data["value"] = _declaration_value(data["declaration_type"], data.get("value"))
    data.setdefault("legal_entity_id", getattr(employee, "legal_entity_id", None))
    D = _models().PayrollMyTaxDeclaration
    row = D(organization_id=organization_id, employee_id=employee.id, status="RECEIVED", created_by_id=actor_id,
            **data)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "received", "my_declaration", row.id,
           new={"type": row.declaration_type, "effective_from": row.effective_from.isoformat()},
           reason=f"{row.declaration_type} received {row.received_at.isoformat()}")
    return row


def _declaration(db: Session, organization_id: int, row_id: int):
    D = _models().PayrollMyTaxDeclaration
    row = db.query(D).filter(D.id == row_id, D.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Malaysia tax declaration")
    return row


def approve_my_declaration(db: Session, organization_id: int, row_id: int, actor_id):
    """Four-eyes approval. An earlier APPROVED declaration of the same type and
    tax year that is still open is superseded from this one's start (never
    edited away); a later one refuses. TP3 (one per prior employer) posts its
    evidenced accumulators to the ledger as PRIOR_EMPLOYER entries."""
    from app.modules.payroll.service import require_four_eyes

    D = _models().PayrollMyTaxDeclaration
    row = _declaration(db, organization_id, row_id)
    if row.status != "RECEIVED":
        raise BadRequestException("Only a RECEIVED declaration can be approved.")
    require_four_eyes(row.created_by_id, actor_id, "Approving a Malaysia tax declaration", db=db,
                      entity_type="my_declaration", entity_id=row.id, current_status=row.status)
    start = row.effective_from
    if row.declaration_type != "TP3":
        for old in (db.query(D).filter(D.organization_id == organization_id, D.employee_id == row.employee_id,
                                       D.declaration_type == row.declaration_type, D.tax_year == row.tax_year,
                                       D.status == "APPROVED", D.id != row.id).all()):
            if old.effective_from >= start:
                raise BadRequestException("An APPROVED declaration of this type already starts on or after "
                                          "this one.")
            if old.effective_to is None or old.effective_to >= start:
                old.effective_to = date.fromordinal(start.toordinal() - 1)
                old.status = "SUPERSEDED"
                old.superseded_by_id = row.id
    row.status = "APPROVED"
    row.approved_by_id = actor_id
    row.approved_at = datetime.utcnow()
    db.flush()
    if row.declaration_type == "TP3":
        _post_prior_employer(db, row, actor_id)
    _audit(db, actor_id, "approved", "my_declaration", row.id, old={"status": "RECEIVED"},
           new={"status": "APPROVED", "type": row.declaration_type})
    return row


def withdraw_my_declaration(db: Session, organization_id: int, row_id: int, actor_id, reason, effective_to):
    reason = _reason(reason)
    row = _declaration(db, organization_id, row_id)
    if row.status != "APPROVED":
        raise BadRequestException("Only an APPROVED declaration can be withdrawn.")
    if row.declaration_type == "TP3":
        raise BadRequestException("A posted TP3 is corrected by a reversing declaration, never withdrawn.")
    end = _as_date(effective_to, "effectiveTo")
    if end < row.effective_from:
        raise BadRequestException("The withdrawal date cannot be before the declaration started.")
    row.effective_to = end
    row.status = "WITHDRAWN"
    row.withdrawn_at = datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "withdrawn", "my_declaration", row.id, old={"status": "APPROVED"},
           new={"status": "WITHDRAWN", "effective_to": end.isoformat()}, reason=reason)
    return row


def _post_prior_employer(db: Session, row, actor_id) -> None:
    Entry = _models().PayrollMyAccumulatorEntry
    for accumulator, amount in sorted((row.value or {}).get("accumulators", {}).items()):
        amount = Decimal(str(amount))
        if amount == 0:
            continue
        db.add(Entry(organization_id=row.organization_id, legal_entity_id=row.legal_entity_id,
                     employee_id=row.employee_id, year=row.tax_year, accumulator=accumulator,
                     pay_date=row.effective_from, amount=amount, entry_kind="PRIOR_EMPLOYER",
                     declaration_id=row.id, evidence_ref=row.evidence_ref, created_by_id=row.created_by_id,
                     approved_by_id=actor_id, approved_at=datetime.utcnow()))
    db.flush()


# ── identifier vault (spec §15, MY-029): masked; reveal requested + approved ─
def _vault(db: Session, organization_id: int, vault_id: int):
    V = _models().PayrollMyIdentifierVault
    row = db.query(V).filter(V.id == vault_id, V.organization_id == organization_id).first()
    if row is None:
        raise NotFoundException("Malaysian identifier")
    return row


def _vault_for_employee(db: Session, organization_id: int, employee_id: int, vault_id: int, kind: str):
    row = _vault(db, organization_id, vault_id)
    if row.employee_id != employee_id or row.identifier_type != kind or row.status != "ACTIVE":
        raise BadRequestException(f"{kind} vault reference does not belong to this employee.")
    return row


def _vault_owner(row) -> str:
    from app.modules.payroll import my_identifiers as mid

    return mid.vault_owner(row.organization_id, row.employee_id, row.identifier_type, row.id)


def _vault_event(db: Session, row, action: str, actor_id, reason=None, purpose=None, previous_id=None):
    Event = _models().PayrollMyIdentifierAccessEvent
    event = Event(organization_id=row.organization_id, legal_entity_id=row.legal_entity_id,
                  employee_id=row.employee_id, vault_id=row.id, actor_id=actor_id, created_by_id=actor_id,
                  action=action, purpose=purpose, reason=(reason or None) and reason[:300],
                  previous_version_id=previous_id)
    db.add(event)
    db.flush()
    return event


def identifier_view(row) -> dict:
    from app.modules.payroll import my_identifiers as mid

    active = row.status == "ACTIVE"
    return {"id": row.id, "identifierType": row.identifier_type, "employeeId": row.employee_id,
            "legalEntityId": row.legal_entity_id, "onFile": active,
            "masked": mid.masked(row.identifier_type) if active else None, "status": row.status,
            "keyVersion": row.key_version}


def create_my_identifier(db: Session, organization_id: int, identifier_type: str, raw, actor_id, *, employee_id):
    from app.modules.payroll import my_identifiers as mid

    V = _models().PayrollMyIdentifierVault
    identifier_type = str(identifier_type or "").strip().upper()
    if identifier_type not in mid.IDENTIFIER_TYPES:
        raise BadRequestException(f"identifierType must be one of: {', '.join(mid.IDENTIFIER_TYPES)}.")
    employee = _employee(db, organization_id, employee_id)
    try:
        plain = mid.normalise(identifier_type, raw)
        fingerprint = mid.fingerprint(identifier_type, plain)
    except mid.MyIdentifierError as error:
        raise BadRequestException(str(error))
    if db.query(V.id).filter(V.organization_id == organization_id, V.identifier_type == identifier_type,
                             V.fingerprint == fingerprint, V.status == "ACTIVE").first():
        raise BadRequestException(f"This {identifier_type} is already on file in this organisation.")
    if db.query(V.id).filter(V.organization_id == organization_id, V.employee_id == employee.id,
                             V.identifier_type == identifier_type, V.status == "ACTIVE").first():
        raise BadRequestException(f"The employee already has a {identifier_type} on file; delete it first.")
    row = V(organization_id=organization_id, legal_entity_id=getattr(employee, "legal_entity_id", None),
            employee_id=employee.id, identifier_type=identifier_type, ciphertext="pending", key_version=0,
            fingerprint=fingerprint, purpose=mid.PURPOSE, collected_at=datetime.utcnow(), status="ACTIVE",
            created_by_id=actor_id)
    db.add(row)
    db.flush()
    try:
        row.ciphertext, row.key_version = mid.encrypt(plain, _vault_owner(row))
    except mid.MyIdentifierError as error:
        raise BadRequestException(str(error))
    plain = None
    db.flush()
    _vault_event(db, row, "CREATE", actor_id, purpose=mid.PURPOSE)
    return row


def list_my_identifiers(db: Session, organization_id: int, employee_id=None) -> list:
    V = _models().PayrollMyIdentifierVault
    q = db.query(V).filter(V.organization_id == organization_id)
    if employee_id is not None:
        _employee(db, organization_id, employee_id)
        q = q.filter(V.employee_id == employee_id)
    return [identifier_view(r) for r in q.order_by(V.id)]


def _last_event(db: Session, row, action: str, after_id: int = 0):
    Event = _models().PayrollMyIdentifierAccessEvent
    return (db.query(Event).filter(Event.vault_id == row.id, Event.action == action, Event.id > after_id)
            .order_by(Event.id.desc()).first())


def request_my_identifier_reveal(db: Session, organization_id: int, vault_id: int, reason, actor_id):
    row = _vault(db, organization_id, vault_id)
    if row.status != "ACTIVE" or not row.ciphertext:
        raise BadRequestException("The identifier has been deleted.")
    return _vault_event(db, row, "REVEAL_REQUESTED", actor_id, reason=_reason(reason), purpose="REVEAL")


def approve_my_identifier_reveal(db: Session, organization_id: int, vault_id: int, actor_id):
    from app.modules.payroll.service import require_four_eyes

    row = _vault(db, organization_id, vault_id)
    request = _last_event(db, row, "REVEAL_REQUESTED")
    if request is None:
        raise BadRequestException("There is no reveal request to approve.")
    if _last_event(db, row, "REVEAL_APPROVED", request.id) is not None:
        raise BadRequestException("This reveal request has already been approved.")
    require_four_eyes(request.actor_id, actor_id, "Approving a Malaysian identifier reveal", db=db,
                      entity_type="my_identifier_access_event", entity_id=request.id,
                      current_status="REVEAL_REQUESTED")
    return _vault_event(db, row, "REVEAL_APPROVED", actor_id, reason=request.reason, purpose="REVEAL",
                        previous_id=request.id)


def reveal_my_identifier(db: Session, organization_id: int, vault_id: int, actor_id) -> dict:
    from app.modules.payroll import my_identifiers as mid

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
        value = mid.decrypt(row.ciphertext, row.key_version, _vault_owner(row))
    except mid.MyIdentifierError as error:
        raise BadRequestException(str(error))
    _vault_event(db, row, "REVEALED", actor_id, reason=request.reason, purpose="REVEAL", previous_id=approval.id)
    return {"vaultId": row.id, "identifierType": row.identifier_type, "value": value}


def delete_my_identifier(db: Session, organization_id: int, vault_id: int, actor_id, reason):
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


def rotate_my_identifier_keys(db: Session, *, dry_run: bool = True) -> dict:
    """Re-encrypt every ACTIVE vault row not under the newest MY_IDENTIFIER_KEYRING
    version, keeping its owner binding. Any row that fails to decrypt or match
    its fingerprint stops the run: nothing is written. Counts and row ids
    only - never an identifier."""
    from app.modules.payroll import my_identifiers as mid

    V = _models().PayrollMyIdentifierVault
    keyring = mid._keyring()
    if not keyring:
        raise BadRequestException("MY_IDENTIFIER_KEYRING is not configured.")
    newest = max(keyring)
    out = {"newestKeyVersion": newest, "examined": 0, "current": 0, "rotated": 0, "failed": [], "dryRun": dry_run}
    plan = []
    for row in db.query(V).filter(V.status == "ACTIVE").order_by(V.id):
        out["examined"] += 1
        if row.key_version == newest:
            out["current"] += 1
            continue
        owner = _vault_owner(row)
        try:
            plain = mid.decrypt(row.ciphertext, row.key_version, owner)
            matches = mid.fingerprint(row.identifier_type, plain) == row.fingerprint
        except mid.MyIdentifierError:
            out["failed"].append({"id": row.id, "reason": "does not decrypt with its owner binding"})
            continue
        plain = None
        if not matches:
            out["failed"].append({"id": row.id, "reason": "fingerprint mismatch"})
            continue
        plan.append((row, owner))
    out["rotated"] = len(plan)
    if dry_run or out["failed"]:
        out["written"] = False
        return out
    for row, owner in plan:
        row.ciphertext, row.key_version = mid.reencrypt(row.ciphertext, row.key_version, owner)
        _vault_event(db, row, "ROTATED", None, reason=f"re-encrypted under key version {newest}")
    db.flush()
    out["written"] = True
    return out


# ── year-to-date ledger (spec §12 accumulators) ─────────────────────────────
def my_ytd_snapshot(db: Session, organization_id: int, employee_id: int, legal_entity_id, pay_date: date) -> dict:
    """Year-to-date sums BEFORE the pay date for the pay date's calendar year,
    every accumulator present (an explicit zero means 'known to be zero')."""
    from sqlalchemy import func

    Entry = _models().PayrollMyAccumulatorEntry
    query = (db.query(Entry.accumulator, func.sum(Entry.amount))
             .filter(Entry.organization_id == organization_id, Entry.employee_id == employee_id,
                     Entry.year == pay_date.year, Entry.pay_date < pay_date))
    query = query.filter(Entry.legal_entity_id.is_(None) if legal_entity_id is None
                         else Entry.legal_entity_id == legal_entity_id)
    totals = {name: Decimal(str(amount or 0)) for name, amount in query.group_by(Entry.accumulator)}
    return {name: totals.get(name, Decimal("0")) for name in _content().ACCUMULATORS}


# ── calculation inputs (selected by the PAY DATE; the period by MY-006) ─────
def resolve_my_calc_inputs(db: Session, organization_id: int, employee, pay_date: date, period=None) -> dict:
    """Every Malaysian input in force ON THE PAY DATE. Nothing is inferred: a
    missing record stays None and the engine refuses with its own reason."""
    m = _models()
    entity = getattr(employee, "legal_entity_id", None)
    registration = _one_active(db, m.PayrollMyEmployerRegistration, organization_id, None, pay_date,
                               "employer registration", legal_entity_id=entity, entity_scoped=True)
    profile = _one_active(db, m.PayrollMyWorkerProfile, organization_id, employee.id, pay_date, "worker profile")
    # The work location in force at the END of the pay period decides the
    # territory of that period's wages (MY-003); the pay date when no period.
    start, end = period or (None, None)
    assignment = _one_active(db, m.PayrollMyWorkAssignment, organization_id, employee.id, end or pay_date,
                             "work assignment")
    # Every approved assignment overlapping the period (ACTIVE or since
    # SUPERSEDED): a transfer inside the period needs the signed split rule
    # (Phase 6, MY-003).
    A = m.PayrollMyWorkAssignment
    window_start = start or end or pay_date
    overlapping = (db.query(A).filter(A.organization_id == organization_id, A.employee_id == employee.id,
                                      A.status.in_((STATUS_ACTIVE, STATUS_SUPERSEDED)),
                                      A.effective_from <= (end or pay_date),
                                      (A.effective_to.is_(None)) | (A.effective_to >= window_start))
                   .order_by(A.effective_from, A.id).all())
    D = m.PayrollMyTaxDeclaration
    declarations = (db.query(D).filter(D.organization_id == organization_id, D.employee_id == employee.id,
                                       D.status == "APPROVED", D.effective_from <= pay_date,
                                       (D.effective_to.is_(None)) | (D.effective_to >= pay_date))
                    .order_by(D.declaration_type, D.effective_from, D.id).all())
    return {
        "my_pay_date": pay_date, "my_period_start": start, "my_period_end": end,
        "my_profile": _facts(profile), "my_registration": _facts(registration), "my_assignment": _facts(assignment),
        "my_assignments": [{**_facts(a), "status": STATUS_ACTIVE} for a in overlapping],
        "my_declarations": [_facts(d) for d in declarations],
        "my_ytd": my_ytd_snapshot(db, organization_id, employee.id, entity, pay_date),
        "my_organization_id": organization_id, "my_legal_entity_id": entity, "my_employee_id": employee.id,
    }


def calc_inputs(db: Session, run=None, employee=None, resolved_pack=None, as_of: Optional[date] = None,
                period=None) -> dict:
    pay_date = getattr(run, "pay_date", None) or as_of
    if pay_date is None:
        raise BadRequestException("Malaysian payroll needs the run's pay date: every rule is selected by it.")
    if period is None and getattr(run, "period_start", None) and getattr(run, "period_end", None):
        period = (run.period_start, run.period_end)
    return resolve_my_calc_inputs(db, employee.organization_id, employee, pay_date, period=period)


# ── frozen snapshot, replay and approval fingerprint (spec §13 replay) ─────
_CTX_DECIMALS = ("gross", "basic", "hra", "special_allowance", "overtime", "additional_compensation")
_CTX_PLAIN = ("pay_frequency", "my_components", "my_overtime_events", "unpaid_leave_days", "my_organization_id",
              "my_legal_entity_id", "my_employee_id", "trace_id")
_CTX_DATES = ("pay_date", "my_pay_date", "period_start", "period_end", "my_period_start", "my_period_end")
_RECORD_KEYS = ("my_profile", "my_registration", "my_assignment")
_RATE_FIELDS = ("id", "component_key", "label", "jurisdiction_state", "employee_rate_pct", "employer_rate_pct",
                "flat_amount", "text_value", "effective_from", "effective_to")
_SLAB_FIELDS = ("id", "rule_type", "filing_status", "tax_regime", "assessment_basis", "rate_label", "tax_formula",
                "jurisdiction_state", "rate_pct", "min_amount", "max_amount", "flat_amount", "sort_order",
                "effective_from", "effective_to")
# Never frozen: identifier references, credential and bank references.
_FROZEN_RECORD_EXCLUDE = (*_PROFILE_VAULT_KEYS, "filing_credential_ref", "bank_export_ref")


def _record_for_freeze(record):
    if record is None:
        return None
    data = record if isinstance(record, dict) else {k: v for k, v in vars(record).items() if not k.startswith("_")}
    return {k: v for k, v in data.items() if k not in _FROZEN_RECORD_EXCLUDE}


def my_freeze_context(ctx, calculation_mode: str = "standard") -> dict:
    def pick(row, fields):
        return {f: (row.get(f) if isinstance(row, dict) else getattr(row, f, None)) for f in fields}

    return _json_safe({
        "version": 1, "calculationMode": calculation_mode,
        "ctx": {k: getattr(ctx, k, None) for k in _CTX_DECIMALS + _CTX_PLAIN + _CTX_DATES},
        "records": {k: _record_for_freeze(getattr(ctx, k, None)) for k in _RECORD_KEYS},
        "declarations": [_record_for_freeze(d) for d in (getattr(ctx, "my_declarations", None) or [])],
        "assignments": [_record_for_freeze(a) for a in (getattr(ctx, "my_assignments", None) or [])],
        "ytd": getattr(ctx, "my_ytd", None),
        "rateMap": {k: pick(r, _RATE_FIELDS) for k, r in (getattr(ctx, "rate_map", None) or {}).items()},
        "slabs": [pick(s, _SLAB_FIELDS) for s in (getattr(ctx, "slabs", None) or [])],
    })


def my_thaw_context(frozen: dict):
    """The engine reads records, rows and dates through tolerant readers (ISO
    strings, decimal strings), so the frozen JSON is replayed as-is; only the
    platform's money and date fields are restored."""
    from app.modules.payroll.engine.base import PayrollContext

    if not frozen or frozen.get("version") != 1:
        raise BadRequestException("This payslip has no replayable Malaysia calculation context.")
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
        **{k: v for k, v in ctx.items() if v is not None}, country=MY,
        **{k: records.get(k) for k in _RECORD_KEYS},
        my_declarations=list(frozen.get("declarations") or []),
        my_assignments=list(frozen.get("assignments") or []),
        my_ytd=frozen.get("ytd"),
        rate_map=dict(frozen.get("rateMap") or {}),
        slabs=list(frozen.get("slabs") or []),
    )


def my_replay(frozen: dict):
    """Recalculate a frozen Malaysia payslip exactly as it was calculated."""
    from app.modules.payroll.engine.resolver import calculate_payroll

    return calculate_payroll(my_thaw_context(frozen), frozen.get("calculationMode") or "standard")


def my_payslip_snapshot(result, frozen: Optional[dict] = None) -> Optional[dict]:
    r = result.get("my_result") if isinstance(result, dict) else getattr(result, "my_result", None)
    if not r:
        return None
    snapshot = dict(r)
    if frozen is not None:
        snapshot["frozenContext"] = frozen
    return _json_safe(snapshot)


def _run_items(db: Session, run) -> list:
    from app.modules.payroll.models import PayslipItem

    return (db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == MY)
            .order_by(PayslipItem.id).all())


def my_approval_fingerprint(db: Session, run) -> Optional[str]:
    items = _run_items(db, run)
    if not items:
        return None
    payload = [{"employeeId": item.employee_id, "hashes": (item.my_calculation_snapshot or {}).get("hashes"),
                "net": (item.my_calculation_snapshot or {}).get("my_net")} for item in items]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ── preflight and run transitions ───────────────────────────────────────────
def _pack_in_force(db: Session, on: date):
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    try:
        _rates, _slabs, pack = resolve_tax_configuration(db, MY, payroll_date=on)
    except Exception:  # an unresolvable pack is "no pack"; the engine blocks on its own
        return None
    return pack


def my_run_preflight(db: Session, run) -> list:
    from app.modules.payroll.models import PayrollEmployee

    problems = []

    def problem(code, employee_id, message):
        problems.append({"code": code, "employeeId": employee_id, "message": message})

    if _pack_in_force(db, run.pay_date) is None:
        problem("CONTENT_PACK_OUT_OF_DATE", None, "No active Malaysia rule pack is in force on the pay date.")
    m = _models()
    for item in _run_items(db, run):
        employee = db.get(PayrollEmployee, item.employee_id)
        entity = getattr(employee, "legal_entity_id", None)
        snapshot = item.my_calculation_snapshot
        if snapshot is None:
            problem("MY_SNAPSHOT_MISSING", item.employee_id, "No frozen Malaysia calculation; recalculate the run.")
        else:
            for exception in snapshot.get("exceptions") or []:
                problem(exception.get("code"), item.employee_id,
                        exception.get("detail") or "A statutory exception needs resolving.")
        registration = _one_active(db, m.PayrollMyEmployerRegistration, run.organization_id, None, run.pay_date,
                                   "employer registration", legal_entity_id=entity, entity_scoped=True)
        if registration is None:
            problem("MY_REGISTRATION_MISSING", item.employee_id,
                    "No ACTIVE Malaysia employer registration covers the pay date.")
        elif registration.verification_state != "VERIFIED":
            problem("MY_REGISTRATION_NOT_VERIFIED", item.employee_id,
                    "The Malaysia employer registration is not verified.")
        if _one_active(db, m.PayrollMyWorkAssignment, run.organization_id, item.employee_id,
                       run.period_end or run.pay_date, "work assignment") is None:
            problem("MY_ASSIGNMENT_MISSING", item.employee_id,
                    "No ACTIVE work assignment (labour territory) covers the period (MY-003).")
        profile = _one_active(db, m.PayrollMyWorkerProfile, run.organization_id, item.employee_id, run.pay_date,
                              "worker profile")
        if profile is None:
            problem("MY_PROFILE_MISSING", item.employee_id, "No ACTIVE worker statutory profile covers the pay date.")
            continue
        passport = (getattr(employee, "compliance_fields", None) or {}).get("passport_number")
        if profile.nric_vault_id is None and not passport:
            problem("MISSING_IDENTIFIER", item.employee_id,
                    "An NRIC in the vault (or a passport number) is required for statutory reporting.")
        if profile.tax_residence == "REVIEW_REQUIRED":
            problem("MY_TAX_RESIDENCE_REVIEW", item.employee_id,
                    "Tax residence is not reviewed; it is never inferred from citizenship (MY-007).")
        if profile.citizenship == "NON_CITIZEN" and (profile.work_pass_valid_to is None
                                                     or profile.work_pass_valid_to < run.pay_date):
            problem("MY_WORK_PASS_EXPIRED", item.employee_id, "No work pass validity covers the pay date.")
    return problems


def post_accumulators(db: Session, run, actor_id) -> int:
    """Post every MY payslip's accumulator deltas once (idempotent per payslip
    + accumulator; the database also refuses a second RUN post)."""
    from app.modules.payroll.models import PayrollEmployee

    Entry = _models().PayrollMyAccumulatorEntry
    added = 0
    for item in _run_items(db, run):
        snapshot = item.my_calculation_snapshot or {}
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
    """Approval needs every MY payslip frozen, a verified employer registration,
    a work assignment, the identifiers statutory reporting needs and no open
    statutory exception; later steps re-verify the approval fingerprint; PAID
    posts the year-to-date ledger exactly once (filings / settlements: Phase 9)."""
    from fastapi import HTTPException, status as http_status

    from app.modules.payroll.models import PayrollStatus

    if not _run_items(db, run):
        return
    if next_status == PayrollStatus.APPROVED:
        problems = my_run_preflight(db, run)
        if problems:
            listing = "; ".join(f"{p['code']}" + (f" (employee #{p['employeeId']})" if p["employeeId"] else "")
                                for p in problems)
            raise HTTPException(http_status.HTTP_409_CONFLICT,
                                detail=f"Malaysia: the run cannot be approved: {listing}")
        run.my_approval_fingerprint = my_approval_fingerprint(db, run)
        return
    if next_status in (PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        if not run.my_approval_fingerprint or my_approval_fingerprint(db, run) != run.my_approval_fingerprint:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                "Malaysia: the approved calculation no longer matches this run - recalculate and approve again."))
    if next_status == PayrollStatus.PAID:
        post_accumulators(db, run, actor_id)


# ── platform hooks ──────────────────────────────────────────────────────────
def _my_statutory_profile_errors(data) -> list:
    # Malaysian statutory facts live in the effective-dated payroll_my_*
    # records, never on the shared statutory profile.
    return []


def _my_profile_values(db: Session, employee, data, previous) -> dict:
    return {}


def _my_pack_activation_refusal(db: Session, pack, actor_id=None) -> Optional[str]:
    return my_pack_activation_refusal(db, pack, actor_id)


def _my_pack_holidays(db: Session, year: int) -> list:
    """Signed NATIONAL holidays of `year` from the in-force pack's own rows;
    state holidays are resolved per employee by holiday state. No pack / no
    signed rows means nothing is seeded, never a guessed date."""
    from app.modules.payroll.engine.jurisdictions.malaysia import holidays
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    try:
        _rates, slabs, pack = resolve_tax_configuration(db, MY, payroll_date=date(year, 12, 31))
    except Exception:  # an unresolvable pack is "no pack"
        return []
    return holidays.national_rows(slabs, year) if pack is not None else []


def _my_template_activation_refusal(db: Session, template, actor_id=None) -> Optional[str]:
    country = (getattr(template, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(template, "report_type", "") or "").upper()
    if country != MY and not report_type.startswith("MY_"):
        return None
    return ("Malaysia statutory form templates stay inactive until the official authority layouts are archived "
            "and the filing path is certified (gate G3, MY-022).")


def _my_payment_treatment(db: Session, organization_id: int, run, items: list) -> dict:
    return {}


def _my_payslip_hold_view(item) -> Optional[dict]:
    # Tax-clearance holds (MY-019 / MY-020) arrive in Phase 7.
    return None


def _my_statutory_editors(db: Session, pack) -> set:
    """Super Admins who edited or signed a statutory row of this pack version:
    the pack approval refuses every one of them."""
    from app.modules.payroll import my_super_admin

    return my_super_admin.statutory_editors(db, pack)


MY_RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and the frozen MY calculation snapshot"),
    ("TAX_RECORDS", "PCB / CP38, TP1 / TP3 / zakat declarations and the year-to-date ledger"),
    ("SOCIAL_SECURITY_RECORDS", "EPF, PERKESO, EIS and HRD levy records"),
    ("EMPLOYEE_IDENTITY", "Identifier vault metadata (NRIC / TIN / member numbers) and worker profiles"),
    ("ACCESS_LOGS", "Identifier access events"),
    ("WORK_LOCATION", "Work assignments (labour territory, holiday state)"),
)
MY_DECISIONS = {
    "D-1": ("Poland template: split engine, versioned four-eyes records, vault, signing console", False),
    "D-2": ("Statutory values by workbook import from day 1", False),
    "D-3": ("All three labour territories in release 1", False),
    "D-4": ("No override table; explicit correction objects", False),
    "D-5": ("Filing payloads only; no live authority transport", False),
    "D-6": ("Release 1 pays MONTHLY only", False),
    "D-7": ("Contribution schedules stored as rows, never percentages", False),
    "D-8": ("Retention period for Malaysian payroll and filing records", True),
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
    for key, (label, blocks) in MY_DECISIONS.items():
        accepted, submitted = _evidence(db, f"MY-DECISION-{key}")
        out.append({"key": key, "label": label, "blocksLaunch": blocks, "evidenceTag": f"MY-DECISION-{key}",
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


def _decision_state(db: Session, key: str) -> str:
    return next((d["state"] for d in owner_decisions(db) if d["key"] == key), "OPEN")


def _retention_employee(db: Session, employee_id: int, organization_id: int) -> None:
    employee = _employee(db, organization_id, employee_id)
    if (getattr(employee, "country_code", None) or "").upper() != MY:
        raise NotFoundException("Malaysian employee")


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    m = _models()
    for model, label in ((m.PayrollMyWorkerProfile, "worker statutory profiles"),
                         (m.PayrollMyTaxDeclaration, "tax declarations"),
                         (m.PayrollMyAccumulatorEntry, "year-to-date ledger"),
                         (m.PayrollMyWorkAssignment, "work assignments")):
        if db.query(model.id).filter(model.organization_id == organization_id,
                                     model.employee_id == employee_id).first():
            return label
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    m = _models()
    return db.query(m.PayrollMyWorkerProfile.id).filter(
        m.PayrollMyWorkerProfile.employee_id == employee_id).first() is not None


def _is_report(report) -> bool:
    country = (getattr(report, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(report, "report_type", "") or "").upper()
    return country == MY or report_type.startswith("MY_")


def _my_retention_settings():
    # The platform calls this hook with NO arguments (retention_service.settings).
    from app.modules.payroll.retention_service import RetentionJurisdiction

    return RetentionJurisdiction(
        country=MY, label="Malaysia", categories=MY_RETENTION_CATEGORIES, period_decision="D-8", end_decision="D-8",
        decision_reference="MY-RETENTION", decision_state=_decision_state,
        validate_employee=_retention_employee, retained_record_label=_retained_record_label,
        has_statutory_profile=_has_statutory_profile, report_matches=_is_report)


def my_unmet_requirements(db: Session) -> list:
    """Every unmet launch requirement. The G1-G7 release-gate evaluation is
    built in Phase 10; until then Malaysia can never leave PLANNED."""
    out = [{"key": "MY-GATES", "label": "Release gates G1-G7",
            "detail": "The Malaysia release-gate evaluation is not built yet (Phase 10)."},
           {"key": "MY-PCB", "label": "PCB / MTD engine",
            "detail": "PCB is blocked until the HASiL 2026 computerised specification is archived (Phase 4)."}]
    out += [{"key": f"MY-DECISION-{d['key']}", "label": d["label"], "detail": d["state"]}
            for d in owner_decisions(db) if d["blocksLaunch"] and d["state"] != "RECORDED"]
    return out


def statutory_summary(db: Session) -> dict:
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    m = _models()
    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == MY)
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
        "jurisdiction": MY, "spec": SPEC, "available": False,
        "packs": [{"id": p.id, "packId": p.pack_id, "version": p.version, "status": p.status,
                   "effectiveFrom": p.effective_from.isoformat() if p.effective_from else None,
                   "effectiveTo": p.effective_to.isoformat() if p.effective_to else None} for p in packs],
        "pendingRows": pending,
        "activeEmployerRegistrations": active(m.PayrollMyEmployerRegistration),
        "verifiedEmployerRegistrations": db.query(m.PayrollMyEmployerRegistration).filter(
            m.PayrollMyEmployerRegistration.status == STATUS_ACTIVE,
            m.PayrollMyEmployerRegistration.verification_state == "VERIFIED").count(),
        "activeWorkerProfiles": active(m.PayrollMyWorkerProfile),
        "activeWorkAssignments": active(m.PayrollMyWorkAssignment),
        "approvedDeclarations": db.query(m.PayrollMyTaxDeclaration).filter(
            m.PayrollMyTaxDeclaration.status == "APPROVED").count(),
        "decisions": owner_decisions(db),
        "unmet": my_unmet_requirements(db),
        "note": "Malaysia stays PLANNED until every release gate G1-G7 and owner decision passes.",
    }


def _my_service_registry_transition(db: Session, target: str, reason: str, actor_id=None, as_of=None):
    from app.modules.payroll import service

    def readiness():
        return my_unmet_requirements(db), {}

    return service.transition_service_registry(
        db, MY, target, reason, actor_id, label="Malaysia", readiness=readiness,
        invalid_target_message=lambda t: (f"Malaysia availability can only be {service.SERVICE_REGISTRY_OPEN} "
                                          f"or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no Malaysia registry row - seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Malaysia is {a}; only PLANNED moves to AVAILABLE.")


JURISDICTION_HOOKS = {
    "calc_inputs": "calc_inputs",
    "before_run_transition": "before_run_transition",
    "statutory_profile_errors": "_my_statutory_profile_errors",
    "statutory_profile_values": "_my_profile_values",
    "pack_activation_refusal": "_my_pack_activation_refusal",
    "retention_settings": "_my_retention_settings",
    "service_registry_transition": "_my_service_registry_transition",
    "statutory_summary": "statutory_summary",
    "statutory_editors": "_my_statutory_editors",
    "template_activation_refusal": "_my_template_activation_refusal",
    "pack_holidays": "_my_pack_holidays",
    "payment_treatment": "_my_payment_treatment",
    "payslip_hold_view": "_my_payslip_hold_view",
}


# ── labour by territory (Phase 6): leave entitlement and holiday calendar ──
def _labour_context(db: Session, organization_id: int, employee_id: int, on: date):
    from app.modules.payroll.engine.jurisdictions.malaysia import jurisdiction
    from app.modules.payroll.engine.jurisdictions.malaysia.pack import MyPack
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration

    m = _models()
    employee = _employee(db, organization_id, employee_id)
    assignment = _one_active(db, m.PayrollMyWorkAssignment, organization_id, employee.id, on, "work assignment")
    try:
        rates, slabs, pack = resolve_tax_configuration(db, MY, payroll_date=on)
    except Exception:  # an unresolvable pack is "no pack"
        pack = None
    if pack is None:
        raise BadRequestException("No active Malaysia rule pack is in force on that date.")
    my_pack = MyPack({r.component_key: r for r in rates}, slabs, organization_id, on)
    place = jurisdiction.resolve(my_pack, _facts(assignment), None, on, on)
    return employee, my_pack, place


def my_leave_entitlement(db: Session, organization_id: int, employee_id: int, as_of) -> dict:
    """Whole-year entitlements for the employee's territory on `as_of`, from
    the signed territorial rows. Refused with the engine's own reason when a
    fact or a signed rule is missing - never a guessed figure."""
    from app.modules.payroll.engine.jurisdictions.malaysia import leave
    from app.modules.payroll.engine.jurisdictions.malaysia.errors import MYCalculationBlockedError

    on = _as_date(as_of, "asOf")
    try:
        employee, pack, place = _labour_context(db, organization_id, employee_id, on)
        profile = _one_active(db, _models().PayrollMyWorkerProfile, organization_id, employee.id, on,
                              "worker profile")
        if profile is None:
            raise BadRequestException("No ACTIVE Malaysia worker profile is in force on that date.")
        out = leave.entitlements(pack, place["territory"], _facts(profile), on)
    except MYCalculationBlockedError as blocked:
        raise BadRequestException(f"Leave cannot be determined ({blocked.key}): {blocked.reason}")
    return {"employeeId": employee.id, "asOf": on.isoformat(), **out}


def my_holiday_calendar(db: Session, organization_id: int, employee_id: int, year: int) -> dict:
    """The employee's federal + state holidays for `year` (signed rows only)."""
    from app.modules.payroll.engine.jurisdictions.malaysia import holidays
    from app.modules.payroll.engine.jurisdictions.malaysia.errors import MYCalculationBlockedError

    on = date(int(year), 12, 31)
    try:
        employee, pack, place = _labour_context(db, organization_id, employee_id, on)
        days = holidays.calendar(pack, place["holidayState"], on.year)
    except MYCalculationBlockedError as blocked:
        raise BadRequestException(f"The holiday calendar cannot be determined ({blocked.key}): {blocked.reason}")
    return {"employeeId": employee.id, "year": on.year, "territory": place["territory"],
            "holidayState": place["holidayState"],
            "holidays": [{"date": d.isoformat(), "name": n} for d, n in sorted(days.items())]}


# ── employee summary (for the Phase 8 panel; identifiers masked) ────────────
def employee_summary(db: Session, organization_id: int, employee_id: int) -> dict:
    m = _models()
    _employee(db, organization_id, employee_id)

    def versions(model):
        return [_json_safe(_facts(r)) for r in db.query(model).filter(
            model.organization_id == organization_id, model.employee_id == employee_id).order_by(model.id)]

    return {"employeeId": employee_id, "identifiers": list_my_identifiers(db, organization_id, employee_id),
            "workerProfiles": versions(m.PayrollMyWorkerProfile),
            "workAssignments": versions(m.PayrollMyWorkAssignment),
            "declarations": versions(m.PayrollMyTaxDeclaration)}
