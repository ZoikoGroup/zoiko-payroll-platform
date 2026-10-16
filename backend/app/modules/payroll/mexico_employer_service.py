"""
payroll/mexico_employer_service.py
----------------------------------
Mexico (ZP-MX-ENG-001) Phase 3 — employer onboarding and registrations
(spec §11 panels A–H; docs/mexico/MEXICO_PHASE_3_PLAN.md §19 overrides).

Kept out of mexico_service.py (the jurisdiction-hook module) so the hooks
other modules reach stay small; this module is reached only by the Mexico
routers.

Rules every function follows:
  * Statutory facts are never typed in. Floors, the premium range and the
    premium period come from content (the Active national pack, or the
    value-free rules in mexico_content) and BLOCK while missing.
  * Secrets are never accepted: credentials are gcp-sm:// references plus
    public certificate metadata (MX-035). A value that looks like key
    material is refused without being echoed back.
  * RFCs and Registros Patronales are masked in audit rows (MX-061).
  * Readiness is computed for an explicit date; nothing here can make an
    employer LIVE-eligible while any gate G1–G8 is unsigned.
"""

from __future__ import annotations

import hashlib as _hashlib
import re as _re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import mexico_service as _mx
from app.modules.payroll.engine.countries import mexico_content as _content

MX = "MX"

# ── spec §22 gate definitions (verbatim) — every readiness item cites the
#    definition of each gate it feeds; an item with no clear gate is "unmapped".
GATE_DEFINITIONS = {
    "G1": "ISR / CFDI — 2026 Annex 8, subsidy, special-pay tax treatment and CFDI 4.0/Nómina 1.2 reconciled to "
          "SAT/PAC validation.",
    "G2": "IMSS / SUA — SBC and every launch IMSS branch including 2026 CEAV reconcile to current SUA on signed cases.",
    "G3": "INFONAVIT — 5% employer contribution and credit-withholding/reconciliation flow proven.",
    "G4": "State ISN — Each enabled work state has signed current base/rate/exemption/return content; unsupported "
          "states are hard-blocked.",
    "G5": "Labor — Minimum wage zones/professions, 2026 workweek/overtime, vacations, aguinaldo and PTU validated.",
    "G6": "External operations — PAC, SAT payment, IDSE/SUA/SIPARE, INFONAVIT and bank workflows have "
          "unknown/reject/recovery paths.",
    "G7": "Security/privacy — Certificates/secrets, personal identifiers, 2025 privacy-law controls and restore "
          "procedures signed.",
    "G8": "Parallel payroll — At least two consecutive payroll cycles plus one IMSS/INFONAVIT and one tax-period "
          "reconciliation show zero unexplained material differences.",
}

PASS, WARNING, BLOCKED, NOT_STARTED = "PASS", "WARNING", "BLOCKED", "NOT_STARTED"

_RFC_PATTERNS = {"MORAL": _re.compile(r"^[A-ZÑ&]{3}([0-9]{6})[A-Z0-9]{3}$"),
                 "FISICA": _re.compile(r"^[A-ZÑ&]{4}([0-9]{6})[A-Z0-9]{3}$")}
_REGISTRO_PATRONAL = _re.compile(r"^[A-Z0-9]{11}$")          # core/jurisdiction.py JURISDICTION_TAX_SCHEMAS["MX"]
_POSTAL = _re.compile(r"^[0-9]{5}$")
_SHORT_CODE = _re.compile(r"^[A-Z0-9.\-]{1,10}$")
_KINDS = ("CSD", "PAC", "IDSE", "SUA", "BANK")
_REGISTRATION_KINDS = ("IDSE", "SUA")
_EMPLOYER_KINDS = ("CSD", "PAC")
_CERTIFICATE_KINDS = ("CSD", "IDSE")
MAX_CERTIFICATE_BYTES = 16 * 1024
_GCP_SM_REF = _re.compile(r"^gcp-sm://projects/([a-z][a-z0-9-]{4,28}[a-z0-9]|[0-9]{1,20})/secrets/[A-Za-z0-9_-]{1,255}"
                          r"(/versions/(latest|[0-9]{1,10}))?$")
_KEY_MATERIAL = (_re.compile(r"-----BEGIN", _re.I), _re.compile(r"PRIVATE\s*KEY", _re.I),
                 _re.compile(r"[A-Za-z0-9+/=]{64,}"), _re.compile(r"\s"))


# ── small helpers ────────────────────────────────────────────────────────────

def _iso(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _s(value):
    return None if value is None else str(value)


def _mask(value: Optional[str], keep: int = 4) -> Optional[str]:
    if not value:
        return value
    return "•" * max(len(value) - keep, 0) + value[-keep:]


def _audit(db, **kw):
    _mx._audit(db, **kw)


def _refuse(db, entity_type, entity_id, attempted, actor_id, message):
    _mx._refuse(db, entity_type, entity_id, attempted, actor_id, message)


def _dec(value, field: str, *, positive: bool = False) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BadRequestException(f"{field} must be a number")
    if not d.is_finite() or d < 0 or (positive and d == 0):
        raise BadRequestException(f"{field} must be {'greater than zero' if positive else 'zero or more'}")
    return d


def _owned(db: Session, model, row_id: int, org_id: int, label: str):
    row = db.query(model).filter(model.id == row_id, model.organization_id == org_id).first()
    if row is None:
        raise NotFoundException(label, row_id)
    return row


def _org_admin_count(db: Session, org_id: int) -> int:
    from app.modules.auth.models import User, UserRole

    return db.query(User).filter(User.organization_id == org_id, User.role == UserRole.ORG_ADMIN,
                                 User.is_active.is_(True)).count()


# ── identifiers (plan §5) ────────────────────────────────────────────────────

def _yymmdd_is_a_date(digits: str) -> bool:
    yy, mm, dd = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
    for century in (1900, 2000):
        try:
            date(century + yy, mm, dd)
            return True
        except ValueError:
            continue
    return False


def validate_rfc(rfc: str, taxpayer_type: str) -> str:
    """Format only (12 characters for a persona moral, 13 for a persona
    física) plus a real YYMMDD date part. The SAT check digit is in no saved
    source and is not checked; the SAT registry/name match is the Phase 7
    stamp test. Upper-cased and trimmed — never otherwise rewritten."""
    if taxpayer_type not in _RFC_PATTERNS:
        raise BadRequestException("taxpayerType must be MORAL (legal entity) or FISICA (individual employer)")
    value = (rfc or "").strip().upper()
    match = _RFC_PATTERNS[taxpayer_type].match(value)
    if not match:
        size = 12 if taxpayer_type == "MORAL" else 13
        raise BadRequestException(f"rfc: a {taxpayer_type} RFC is {size} characters — "
                                  f"{size - 9} letters, a YYMMDD date and a 3-character homoclave")
    if not _yymmdd_is_a_date(match.group(1)):
        raise BadRequestException("rfc: the six digits after the letters must be a real date (YYMMDD)")
    return value


def validate_registro_patronal(value: str) -> str:
    v = (value or "").strip().upper()
    if not _REGISTRO_PATRONAL.match(v):
        raise BadRequestException("registroPatronal: 11 letters or digits (format only — no check digit is applied, "
                                  "it is in no saved source)")
    return v


def _postal(value, field):
    v = (value or "").strip()
    if not _POSTAL.match(v):
        raise BadRequestException(f"{field}: a 5-digit postal code")
    return v


# ── employer profile (panels A and B) ────────────────────────────────────────

def _root_id(db: Session, row) -> int:
    from app.modules.payroll.models import PayrollMxEmployerProfile as P

    seen = set()
    while row.previous_version_id and row.id not in seen:
        seen.add(row.id)
        row = db.get(P, row.previous_version_id)
    return row.id


def _chain(db: Session, root_id: int) -> list:
    from app.modules.payroll.models import PayrollMxEmployerProfile as P

    rows, current = [], db.get(P, root_id)
    while current is not None:
        rows.append(current)
        current = db.query(P).filter(P.previous_version_id == current.id).first()
    return rows


def employer_root(db: Session, org_id: int, employer_id: int):
    """The chain root of any version id owned by the organisation — every
    child record (registration, establishment, …) hangs off the root, so a
    new profile version never orphans them."""
    from app.modules.payroll.models import PayrollMxEmployerProfile as P

    row = _owned(db, P, employer_id, org_id, "Mexico employer")
    return db.get(P, _root_id(db, row))


def version_in_force(db: Session, root_id: int, on: date):
    for row in _chain(db, root_id):
        if row.effective_from <= on and (row.effective_to is None or row.effective_to >= on):
            return row
    return None


def profile_view(row, *, masked: bool = False) -> dict:
    return {"id": row.id, "organizationId": row.organization_id, "version": row.version,
            "previousVersionId": row.previous_version_id, "effectiveFrom": _iso(row.effective_from),
            "effectiveTo": _iso(row.effective_to), "taxpayerType": row.taxpayer_type,
            "rfc": _mask(row.rfc) if masked else row.rfc, "legalName": row.legal_name,
            "fiscalRegimeCode": row.fiscal_regime_code, "fiscalPostalCode": row.fiscal_postal_code,
            "fiscalAddress": row.fiscal_address, "placeOfIssuePostalCode": row.place_of_issue_postal_code,
            "withholdingObligationActive": row.withholding_obligation_active, "taxContact": row.tax_contact,
            "bankContact": row.bank_contact, "pacProvider": row.pac_provider, "pacEnvironment": row.pac_environment,
            "stampTestStatus": row.stamp_test_status, "stampTestUuid": row.stamp_test_uuid,
            "stampTestedAt": _iso(row.stamp_tested_at)}


def _profile_values(data: dict) -> dict:
    taxpayer_type = (data.get("taxpayer_type") or "").strip().upper()
    legal_name = (data.get("legal_name") or "").strip()
    regime = (data.get("fiscal_regime_code") or "").strip().upper()
    if not legal_name:
        raise BadRequestException("legalName is required")
    if not regime or not _SHORT_CODE.match(regime):
        raise BadRequestException("fiscalRegimeCode: the SAT c_RegimenFiscal code (checked against the Active CFDI "
                                  "catalog once one exists)")
    if not isinstance(data.get("withholding_obligation_active"), bool):
        raise BadRequestException("withholdingObligationActive must be true or false")
    if not isinstance(data.get("effective_from"), date):
        raise BadRequestException("effectiveFrom is required")
    env = data.get("pac_environment")
    if env is not None and env not in ("SANDBOX", "PRODUCTION"):
        raise BadRequestException("pacEnvironment must be SANDBOX or PRODUCTION")
    return {"taxpayer_type": taxpayer_type, "rfc": validate_rfc(data.get("rfc"), taxpayer_type),
            "legal_name": legal_name, "fiscal_regime_code": regime,
            "fiscal_postal_code": _postal(data.get("fiscal_postal_code"), "fiscalPostalCode"),
            "fiscal_address": data.get("fiscal_address"),
            "place_of_issue_postal_code": _postal(data.get("place_of_issue_postal_code"), "placeOfIssuePostalCode"),
            "withholding_obligation_active": data["withholding_obligation_active"],
            "tax_contact": data.get("tax_contact"), "bank_contact": data.get("bank_contact"),
            "pac_provider": (data.get("pac_provider") or "").strip() or None, "pac_environment": env,
            "effective_from": data["effective_from"]}


def create_employer(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """A new legal employer (RFC chain), version 1."""
    from app.modules.payroll.models import PayrollMxEmployerProfile as P

    values = _profile_values(data)
    if db.query(P.id).filter(P.organization_id == org_id, P.rfc == values["rfc"]).first():
        raise BadRequestException("this organisation already has a legal employer with that RFC — record a new "
                                  "version of it instead")
    row = P(organization_id=org_id, version=1, stamp_test_status="NOT_TESTED", created_by_id=actor_id, **values)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_employer_profile", entity_id=row.id,
           new={"rfc": _mask(row.rfc), "version": 1, "effectiveFrom": _iso(row.effective_from)})
    db.commit()
    db.refresh(row)
    return profile_view(row)


def create_employer_version(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """A change is a new version from its effective date; the open version is
    closed the day before. The RFC never changes inside a chain."""
    from app.modules.payroll.models import PayrollMxEmployerProfile as P

    root = employer_root(db, org_id, employer_id)
    chain = _chain(db, root.id)
    latest = chain[-1]
    values = _profile_values(data)
    if values["rfc"] != root.rfc:
        raise BadRequestException("the RFC cannot change inside an employer's history — a different RFC is a "
                                  "different legal employer")
    if values["effective_from"] <= latest.effective_from:
        raise BadRequestException(f"a new version must start after {latest.effective_from.isoformat()} "
                                  f"(version {latest.version})")
    latest.effective_to = values["effective_from"] - timedelta(days=1)
    db.flush()
    row = P(organization_id=org_id, version=latest.version + 1, previous_version_id=latest.id,
            stamp_test_status="NOT_TESTED", created_by_id=actor_id, **values)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="version", entity_type="mx_employer_profile", entity_id=row.id,
           old={"version": latest.version, "effectiveTo": _iso(latest.effective_to)},
           new={"rfc": _mask(row.rfc), "version": row.version, "effectiveFrom": _iso(row.effective_from)})
    db.commit()
    db.refresh(row)
    return profile_view(row)


def list_employers(db: Session, org_id: int, *, masked: bool = False) -> list:
    from app.modules.payroll.models import PayrollMxEmployerProfile as P

    roots = (db.query(P).filter(P.organization_id == org_id, P.previous_version_id.is_(None))
             .order_by(P.id).all())
    out = []
    for root in roots:
        versions = [profile_view(v, masked=masked) for v in _chain(db, root.id)]
        out.append({"employerId": root.id, "rfc": _mask(root.rfc) if masked else root.rfc,
                    "legalName": versions[-1]["legalName"], "versions": versions})
    return out


def employer_detail(db: Session, org_id: int, employer_id: int, *, masked: bool = False) -> dict:
    root = employer_root(db, org_id, employer_id)
    return {"employerId": root.id, "versions": [profile_view(v, masked=masked) for v in _chain(db, root.id)],
            "establishments": list_establishments(db, org_id, root.id),
            "imssRegistrations": list_registrations(db, org_id, root.id, masked=masked),
            "isnRegistrations": list_isn_registrations(db, org_id, root.id),
            "laborPolicies": list_labor_policies(db, org_id, root.id),
            "credentials": list_credentials(db, org_id, root.id)}


# ── establishments ───────────────────────────────────────────────────────────

def min_wage_zone(state_code: str, municipality: str) -> dict:
    """Derived from MX_ZLFN_MUNICIPALITIES (S9 transcription), never typed.
    While that content is empty the zone is UNRESOLVED — a GENERAL default
    would be a guess."""
    if not _content.MX_ZLFN_MUNICIPALITIES:
        return {"zone": "UNRESOLVED", "detail": "the ZLFN municipality list is not transcribed yet (S9)"}
    key = (state_code.upper(), municipality.strip().casefold())
    for m in _content.MX_ZLFN_MUNICIPALITIES:
        if (m.state.upper(), m.municipality.strip().casefold()) == key:
            return {"zone": "ZLFN", "detail": f"listed in {m.source} {m.source_ref}"}
    return {"zone": "GENERAL", "detail": "not in the transcribed ZLFN municipality list"}


def establishment_view(row) -> dict:
    return {"id": row.id, "employerId": row.employer_profile_id, "name": row.name, "stateCode": row.state_code,
            "municipality": row.municipality, "municipalityCode": row.municipality_code,
            "postalCode": row.postal_code, "imssRegistrationId": row.imss_registration_id,
            "isActive": row.is_active, "minWageZone": min_wage_zone(row.state_code, row.municipality)}


def create_establishment(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxEstablishment as E, PayrollMxImssRegistration as R

    root = employer_root(db, org_id, employer_id)
    name = (data.get("name") or "").strip()
    state = (data.get("state_code") or "").strip().upper()
    municipality = (data.get("municipality") or "").strip()
    if not name or not municipality:
        raise BadRequestException("name and municipality are required")
    if state not in {c for c, _ in _content.MX_FEDERAL_ENTITIES}:
        raise BadRequestException("stateCode must be one of the 32 federal-entity codes")
    reg_id = data.get("imss_registration_id")
    if reg_id is not None:
        reg = _owned(db, R, reg_id, org_id, "IMSS registration")
        if reg.employer_profile_id != root.id:
            raise BadRequestException("the IMSS registration belongs to a different legal employer")
    if db.query(E.id).filter(E.employer_profile_id == root.id, E.name == name, E.is_active.is_(True)).first():
        raise BadRequestException(f"this employer already has an active establishment named {name!r}")
    row = E(organization_id=org_id, employer_profile_id=root.id, name=name, state_code=state,
            municipality=municipality, municipality_code=(data.get("municipality_code") or None),
            postal_code=_postal(data.get("postal_code"), "postalCode"), imss_registration_id=reg_id,
            is_active=True, created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_establishment", entity_id=row.id,
           new={"employerId": root.id, "state": state})
    db.commit()
    db.refresh(row)
    return establishment_view(row)


def deactivate_establishment(db: Session, org_id: int, establishment_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxEstablishment as E

    row = _owned(db, E, establishment_id, org_id, "establishment")
    row.is_active = False
    _audit(db, actor_id=actor_id, action="deactivate", entity_type="mx_establishment", entity_id=row.id,
           new={"isActive": False})
    db.commit()
    db.refresh(row)
    return establishment_view(row)


def list_establishments(db: Session, org_id: int, root_id: int) -> list:
    from app.modules.payroll.models import PayrollMxEstablishment as E

    return [establishment_view(r) for r in db.query(E).filter(E.organization_id == org_id,
                                                              E.employer_profile_id == root_id).order_by(E.id)]


# ── IMSS registrations (panel C) + INFONAVIT model (panel D) ─────────────────

def registration_view(db: Session, row, *, masked: bool = False) -> dict:
    return {"id": row.id, "employerId": row.employer_profile_id,
            "registroPatronal": _mask(row.registro_patronal) if masked else row.registro_patronal,
            "riskClass": row.risk_class, "fraction": row.fraction, "subdelegationCode": row.subdelegation_code,
            "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to), "status": row.status,
            "infonavitOperatingModel": row.infonavit_operating_model,
            "riskPremiums": list_risk_premiums(db, row.id)}


def _overlaps(a_from, a_to, b_from, b_to) -> bool:
    return (a_to is None or a_to >= b_from) and (b_to is None or b_to >= a_from)


def create_registration(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxImssRegistration as R

    root = employer_root(db, org_id, employer_id)
    rp = validate_registro_patronal(data.get("registro_patronal"))
    risk_class = (data.get("risk_class") or "").strip().upper()
    fraction = (data.get("fraction") or "").strip().upper()
    if not _SHORT_CODE.match(risk_class) or not _SHORT_CODE.match(fraction):
        raise BadRequestException("riskClass and fraction are required, as shown on the IMSS registration "
                                  "(not checked against the classification catalogue, which is not transcribed)")
    eff_from, eff_to = data.get("effective_from"), data.get("effective_to")
    if not isinstance(eff_from, date):
        raise BadRequestException("effectiveFrom is required")
    if eff_to is not None and eff_to < eff_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom")
    model = data.get("infonavit_operating_model")
    if model is not None and model not in ("SUA", "SIPARE"):
        raise BadRequestException("infonavitOperatingModel must be SUA or SIPARE")
    for other in db.query(R).filter(R.organization_id == org_id, R.registro_patronal == rp).all():
        if _overlaps(other.effective_from, other.effective_to, eff_from, eff_to):
            raise BadRequestException("this Registro Patronal already has a registration overlapping those dates")
    row = R(organization_id=org_id, employer_profile_id=root.id, registro_patronal=rp, risk_class=risk_class,
            fraction=fraction, subdelegation_code=(data.get("subdelegation_code") or None),
            effective_from=eff_from, effective_to=eff_to, status="ACTIVE", infonavit_operating_model=model,
            created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_imss_registration", entity_id=row.id,
           new={"registroPatronal": _mask(rp), "employerId": root.id})
    db.commit()
    db.refresh(row)
    return registration_view(db, row)


def set_infonavit_model(db: Session, org_id: int, registration_id: int, model: str, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxImssRegistration as R

    row = _owned(db, R, registration_id, org_id, "IMSS registration")
    if model not in ("SUA", "SIPARE"):
        raise BadRequestException("infonavitOperatingModel must be SUA or SIPARE")
    old = row.infonavit_operating_model
    row.infonavit_operating_model = model
    _audit(db, actor_id=actor_id, action="update", entity_type="mx_imss_registration", entity_id=row.id,
           old={"infonavitOperatingModel": old}, new={"infonavitOperatingModel": model})
    db.commit()
    db.refresh(row)
    return registration_view(db, row)


def close_registration(db: Session, org_id: int, registration_id: int, effective_to: date,
                       actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxImssRegistration as R

    row = _owned(db, R, registration_id, org_id, "IMSS registration")
    if not isinstance(effective_to, date) or effective_to < row.effective_from:
        raise BadRequestException("effectiveTo is required and must not be before effectiveFrom")
    row.effective_to, row.status = effective_to, "CLOSED"
    _audit(db, actor_id=actor_id, action="close", entity_type="mx_imss_registration", entity_id=row.id,
           new={"effectiveTo": _iso(effective_to)})
    db.commit()
    db.refresh(row)
    return registration_view(db, row)


def list_registrations(db: Session, org_id: int, root_id: int, *, masked: bool = False) -> list:
    from app.modules.payroll.models import PayrollMxImssRegistration as R

    return [registration_view(db, r, masked=masked) for r in db.query(R).filter(
        R.organization_id == org_id, R.employer_profile_id == root_id).order_by(R.id)]


# ── work-risk premiums (MX-024 / MX-026) ─────────────────────────────────────

def _active_national_pack(db: Session, on: date):
    from app.modules.payroll.models import JurisdictionPack as J

    return (db.query(J).filter(J.jurisdiction_country == MX, J.jurisdiction_state.is_(None), J.pack_type == "tax",
                               J.status == "Active", J.effective_from <= on,
                               (J.effective_to.is_(None)) | (J.effective_to >= on))
            .order_by(J.id.desc()).first())


def _pack_content(db: Session, on: date) -> Optional[dict]:
    """The governed rows in force on `on` from the Active national pack (Q1):
    {"pack", "scalars": {key: ContributionRate}, "slabs": {rule_type: [TaxSlab]}}.
    None when no Active pack covers the date."""
    pack = _active_national_pack(db, on)
    if pack is None:
        return None
    rates, slabs = _mx._pack_rows(db, pack)
    out = {"pack": pack, "scalars": {}, "slabs": {}}
    for r in rates:
        if _mx._in_window(r, on):
            out["scalars"][r.component_key] = r
    for s in slabs:
        if _mx._in_window(s, on):
            out["slabs"].setdefault(s.rule_type, []).append(s)
    return out


def premium_period_for(period_from: date) -> Optional[tuple]:
    """(start, end) of the premium period starting on `period_from`, per the
    transcribed rule; None while MX_RISK_PREMIUM_PERIOD is not transcribed."""
    rule = _content.MX_RISK_PREMIUM_PERIOD
    if rule is None:
        return None
    start = date(period_from.year, rule.start_month, rule.start_day)
    end = date(period_from.year + 1, rule.start_month, rule.start_day) - timedelta(days=1)
    return start, end


def premium_view(row) -> dict:
    return {"id": row.id, "registrationId": row.registration_id, "determinationYear": row.determination_year,
            "premiumRatePct": _s(row.premium_rate_pct), "periodFrom": _iso(row.period_from),
            "periodTo": _iso(row.period_to), "evidenceDocumentId": row.evidence_document_id, "status": row.status,
            "createdById": row.created_by_id, "approvedById": row.approved_by_id, "approvedAt": _iso(row.approved_at)}


def _evidence(db: Session, org_id: int, doc_id):
    from app.modules.payroll.models import ComplianceDocument

    if doc_id is None:
        return None
    doc = db.query(ComplianceDocument).filter(ComplianceDocument.id == doc_id,
                                              ComplianceDocument.organization_id == org_id).first()
    if doc is None:
        raise NotFoundException("compliance document", doc_id)
    return doc


def create_risk_premium(db: Session, org_id: int, registration_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """Recorded as DRAFT. It applies only after a second org admin approves
    it — and approval is refused until the period rule and the legal range
    are transcribed."""
    from app.modules.payroll.models import PayrollMxImssRegistration as R, PayrollMxRiskPremium as RP

    reg = _owned(db, R, registration_id, org_id, "IMSS registration")
    rate = _dec(data.get("premium_rate_pct"), "premiumRatePct", positive=True)
    if rate >= 100:
        raise BadRequestException("premiumRatePct is a percentage below 100")
    p_from, p_to = data.get("period_from"), data.get("period_to")
    if not isinstance(p_from, date) or not isinstance(p_to, date) or p_to < p_from:
        raise BadRequestException("periodFrom and periodTo are required, periodTo not before periodFrom")
    year = data.get("determination_year")
    if not isinstance(year, int):
        raise BadRequestException("determinationYear is required")
    if not _overlaps(reg.effective_from, reg.effective_to, p_from, p_to):
        raise BadRequestException("the premium period does not overlap the registration's dates")
    _evidence(db, org_id, data.get("evidence_document_id"))
    row = RP(registration_id=reg.id, determination_year=year, premium_rate_pct=rate, period_from=p_from,
             period_to=p_to, evidence_document_id=data.get("evidence_document_id"), status="DRAFT",
             created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_risk_premium", entity_id=row.id,
           new={"registrationId": reg.id, "periodFrom": _iso(p_from), "status": "DRAFT"})
    db.commit()
    db.refresh(row)
    return premium_view(row)


def approve_risk_premium(db: Session, org_id: int, premium_id: int, actor_id: Optional[int],
                         actor_role: str) -> dict:
    """Four-eyes inside the tenant, no exception (Q4): an org admin who did
    not record it. Content first: the period shape (S10/S14/S29) and the
    legal range (S10) must be transcribed and Active, else refused."""
    from app.modules.payroll.models import PayrollMxImssRegistration as R, PayrollMxRiskPremium as RP

    row = db.query(RP).join(R, RP.registration_id == R.id).filter(RP.id == premium_id,
                                                                  R.organization_id == org_id).first()
    if row is None:
        raise NotFoundException("work-risk premium", premium_id)
    et = "mx_risk_premium"
    if row.status != "DRAFT":
        _refuse(db, et, row.id, "approve", actor_id, f"only a DRAFT premium can be approved (this one is {row.status})")
    if actor_role != "org_admin":
        _refuse(db, et, row.id, "approve", actor_id, "a work-risk premium is approved by an org admin of this "
                                                     "organisation")
    if actor_id is None or actor_id == row.created_by_id:
        extra = (" This organisation has only one active org admin — waiting for a second org admin."
                 if _org_admin_count(db, org_id) < 2 else "")
        _refuse(db, et, row.id, "approve", actor_id,
                "You recorded this premium — a second org admin must approve it (four-eyes, no exception)." + extra)
    shape = premium_period_for(row.period_from)
    if shape is None:
        _refuse(db, et, row.id, "approve", actor_id,
                "The premium period rule is awaiting transcription from S10 / S14 / S29 (RACERF) — no work-risk "
                "premium can be approved until the source is saved and transcribed (spec MX-026).")
    if (row.period_from, row.period_to) != shape:
        _refuse(db, et, row.id, "approve", actor_id,
                f"the premium period must run {shape[0].isoformat()} to {shape[1].isoformat()} under the transcribed "
                f"rule ({_content.MX_RISK_PREMIUM_PERIOD.source} {_content.MX_RISK_PREMIUM_PERIOD.source_ref})")
    if row.determination_year != row.period_from.year - 1:
        _refuse(db, et, row.id, "approve", actor_id,
                f"a premium for the period starting {row.period_from.isoformat()} is determined in "
                f"{row.period_from.year - 1}")
    content = _pack_content(db, row.period_from)
    lo = content and content["scalars"].get("mx_risk_premium_min_pct")
    hi = content and content["scalars"].get("mx_risk_premium_max_pct")
    if not lo or not hi or lo.employer_rate_pct is None or hi.employer_rate_pct is None:
        _refuse(db, et, row.id, "approve", actor_id,
                "the legal premium range (S10, LSS Art. 74) is not in an Active national pack for "
                f"{row.period_from.isoformat()} — approval stays blocked until it is transcribed and activated")
    if not (lo.employer_rate_pct <= row.premium_rate_pct <= hi.employer_rate_pct):
        _refuse(db, et, row.id, "approve", actor_id,
                f"{row.premium_rate_pct}% is outside the legal range {lo.employer_rate_pct}%–{hi.employer_rate_pct}%")
    if row.evidence_document_id is None:
        _refuse(db, et, row.id, "approve", actor_id, "attach the IMSS premium determination document first")
    for prior in db.query(RP).filter(RP.registration_id == row.registration_id, RP.status == "ACTIVE",
                                     RP.period_from == row.period_from).all():
        prior.status = "SUPERSEDED"
        _audit(db, actor_id=actor_id, action="supersede", entity_type=et, entity_id=prior.id,
               new={"status": "SUPERSEDED", "by": row.id})
    db.flush()
    row.status, row.approved_by_id, row.approved_at = "ACTIVE", actor_id, datetime.now(timezone.utc)
    _audit(db, actor_id=actor_id, action="approve", entity_type=et, entity_id=row.id, new={"status": "ACTIVE"})
    db.commit()
    db.refresh(row)
    return premium_view(row)


def list_risk_premiums(db: Session, registration_id: int) -> list:
    from app.modules.payroll.models import PayrollMxRiskPremium as RP

    return [premium_view(r) for r in db.query(RP).filter(RP.registration_id == registration_id)
            .order_by(RP.period_from, RP.id)]


# ── state ISN registrations (panel E, MX-045) ────────────────────────────────

def _isn_pack(db: Session, state: str):
    from app.modules.payroll.models import JurisdictionPack as J

    return (db.query(J).filter(J.jurisdiction_country == MX, J.jurisdiction_state == state, J.pack_type == "tax")
            .order_by(J.id.desc()).first())


def isn_view(db: Session, row) -> dict:
    from app.modules.payroll.models import JurisdictionPack as J

    pack = db.get(J, row.jurisdiction_pack_id)
    if row.status == "CLOSED":
        state = "CLOSED"
    else:
        state = "ACTIVE" if pack is not None and pack.status == "Active" else "PENDING_PACK"
    return {"id": row.id, "employerId": row.employer_profile_id, "stateCode": row.state_code,
            "localAccountNumber": row.local_account_number, "packId": pack.pack_id if pack else None,
            "packStatus": pack.status if pack else None, "returnFrequency": row.return_frequency,
            "returnFrequencySource": "awaiting state filing content", "effectiveFrom": _iso(row.effective_from),
            "effectiveTo": _iso(row.effective_to), "state": state}


def create_isn_registration(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxIsnRegistration as I

    root = employer_root(db, org_id, employer_id)
    state = (data.get("state_code") or "").strip().upper()
    if state not in {c for c, _ in _content.MX_FEDERAL_ENTITIES}:
        raise BadRequestException("stateCode must be one of the 32 federal-entity codes")
    if state not in _content.MX_ISN_STATES_IN_SCOPE:
        _refuse(db, "mx_isn_registration", 0, "create", actor_id,
                f"{state} is not supported for state payroll tax — payroll for employees working there is blocked "
                f"(MX-045). Supported: {', '.join(_content.MX_ISN_STATES_IN_SCOPE)}.")
    if data.get("return_frequency") not in (None, ""):
        raise BadRequestException("returnFrequency comes from the state's filing content, which is not transcribed "
                                  "yet — it cannot be typed in")
    account = (data.get("local_account_number") or "").strip()
    if not account or len(account) > 40:
        raise BadRequestException("localAccountNumber is required (up to 40 characters)")
    eff_from = data.get("effective_from")
    if not isinstance(eff_from, date):
        raise BadRequestException("effectiveFrom is required")
    pack = _isn_pack(db, state)
    if pack is None:
        raise BadRequestException(f"no ISN pack is seeded for {state}")
    if db.query(I.id).filter(I.employer_profile_id == root.id, I.state_code == state,
                             I.effective_to.is_(None)).first():
        raise BadRequestException(f"this employer already has an open {state} ISN registration")
    row = I(organization_id=org_id, employer_profile_id=root.id, state_code=state, local_account_number=account,
            jurisdiction_pack_id=pack.id, effective_from=eff_from, status="OPEN", created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_isn_registration", entity_id=row.id,
           new={"state": state, "packId": pack.pack_id, "packStatus": pack.status})
    db.commit()
    db.refresh(row)
    return isn_view(db, row)


def close_isn_registration(db: Session, org_id: int, isn_id: int, effective_to: date, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxIsnRegistration as I

    row = _owned(db, I, isn_id, org_id, "ISN registration")
    if not isinstance(effective_to, date) or effective_to < row.effective_from:
        raise BadRequestException("effectiveTo is required and must not be before effectiveFrom")
    row.effective_to, row.status = effective_to, "CLOSED"
    _audit(db, actor_id=actor_id, action="close", entity_type="mx_isn_registration", entity_id=row.id,
           new={"effectiveTo": _iso(effective_to)})
    db.commit()
    db.refresh(row)
    return isn_view(db, row)


def list_isn_registrations(db: Session, org_id: int, root_id: int) -> list:
    from app.modules.payroll.models import PayrollMxIsnRegistration as I

    return [isn_view(db, r) for r in db.query(I).filter(I.organization_id == org_id,
                                                        I.employer_profile_id == root_id).order_by(I.id)]


# ── labour policy and statutory floors (panels F and G, MX-051) ──────────────

def _vacation_bands(raw) -> list:
    if not isinstance(raw, list) or not raw:
        raise BadRequestException("vacationPolicy: a list of {serviceYearFrom, serviceYearTo, days} bands")
    bands = []
    for b in raw:
        try:
            y_from = int(b["serviceYearFrom"])
            y_to = None if b.get("serviceYearTo") in (None, "") else int(b["serviceYearTo"])
            days = _dec(b["days"], "vacationPolicy.days")
        except (KeyError, TypeError, ValueError):
            raise BadRequestException("vacationPolicy: each band needs serviceYearFrom, serviceYearTo (or null) and days")
        if y_from < 1 or (y_to is not None and y_to < y_from):
            raise BadRequestException("vacationPolicy: service years start at 1 and serviceYearTo ≥ serviceYearFrom")
        bands.append((y_from, y_to, days))
    bands.sort()
    for (a_from, a_to, _), (b_from, _bt, _bd) in zip(bands, bands[1:]):
        if a_to is None or a_to >= b_from:
            raise BadRequestException("vacationPolicy: bands overlap")
    return bands


def _days_at(bands, year):
    for y_from, y_to, days in bands:
        if y_from <= year and (y_to is None or year <= y_to):
            return days
    return None


def check_floors(db: Session, policy: dict, on: date) -> dict:
    """One date. Floors are read from the Active national pack (Q1); a
    missing floor is BLOCKED_CONTENT, never a default. The policy may be
    above a floor, never below — FAIL is never auto-raised."""
    findings, missing = [], []
    content = _pack_content(db, on)
    if content is None:
        return {"on": on.isoformat(), "status": "BLOCKED_CONTENT", "findings": [],
                "missing": ["no Active national pack (MX-PAYROLL) is in force on this date — statutory content not "
                            "active"], "dailyLimits": "not checked — Phase 5 (no content key)"}
    sc = content["scalars"]

    def scalar(key, attr):
        r = sc.get(key)
        value = getattr(r, attr) if r is not None else None
        if value is None:
            missing.append(f"{key} is not in the Active pack")
        return value

    for field, key, attr, label in (("aguinaldo_days", "mx_aguinaldo_min_days", "flat_amount", "aguinaldo days"),
                                    ("vacation_premium_pct", "mx_vacation_premium_min_pct", "employee_rate_pct",
                                     "vacation premium %"),
                                    ("sunday_premium_pct", "mx_sunday_premium_min_pct", "employee_rate_pct",
                                     "Sunday premium %")):
        floor = scalar(key, attr)
        if floor is not None:
            ok = Decimal(policy[field]) >= Decimal(floor)
            findings.append({"field": field, "label": label, "policy": str(policy[field]), "floor": str(floor),
                             "rule": f">= {key}", "result": "PASS" if ok else "FAIL",
                             "sourceDocumentId": sc[key].source_document_id})
    weeks = content["slabs"].get(_content.MX_WORKWEEK_RULE, [])
    if len(weeks) != 1 or weeks[0].flat_amount is None:
        missing.append("the workweek limit (MX_WORKWEEK) is not in the Active pack")
    else:
        ok = Decimal(policy["ordinary_weekly_hours"]) <= Decimal(weeks[0].flat_amount)
        findings.append({"field": "ordinary_weekly_hours", "label": "ordinary weekly hours",
                         "policy": str(policy["ordinary_weekly_hours"]), "floor": str(weeks[0].flat_amount),
                         "rule": "<= MX_WORKWEEK", "result": "PASS" if ok else "FAIL",
                         "sourceDocumentId": weeks[0].source_document_id})
    vac = content["slabs"].get(_content.MX_VACATION_DAYS_RULE, [])
    if not vac:
        missing.append("the vacation-days schedule (MX_VACATION_DAYS) is not in the Active pack")
    else:
        statutory = sorted((int(s.min_amount), None if s.max_amount is None else int(s.max_amount),
                            Decimal(s.flat_amount)) for s in vac)
        bands = policy["vacation_bands"]
        years = sorted({b[0] for b in statutory} | {b[0] for b in bands} |
                       {b[1] + 1 for b in statutory + bands if b[1] is not None})
        for year in years:
            floor = _days_at(statutory, year)
            if floor is None:
                continue
            mine = _days_at(bands, year)
            ok = mine is not None and mine >= floor
            findings.append({"field": "vacation_policy", "label": f"vacation days, service year {year}",
                             "policy": None if mine is None else str(mine), "floor": str(floor),
                             "rule": ">= MX_VACATION_DAYS", "result": "PASS" if ok else "FAIL",
                             "sourceDocumentId": vac[0].source_document_id})
    status = ("FAIL" if any(f["result"] == "FAIL" for f in findings)
              else "BLOCKED_CONTENT" if missing else "PASS")
    return {"on": on.isoformat(), "status": status, "findings": findings, "missing": missing,
            "dailyLimits": "not checked — Phase 5 (no content key)"}


def _content_boundaries(db: Session, start: date, end: Optional[date]) -> list:
    """Every date inside [start, end] where the Active national content can
    change: pack starts, row starts, and the day after a pack ends."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack as J, TaxSlab

    dates = set()
    for pack in db.query(J).filter(J.jurisdiction_country == MX, J.jurisdiction_state.is_(None),
                                   J.pack_type == "tax", J.status == "Active").all():
        dates.add(pack.effective_from)
        if pack.effective_to is not None:
            dates.add(pack.effective_to + timedelta(days=1))
        for model in (ContributionRate, TaxSlab):
            for (eff,) in db.query(model.effective_from).filter(model.jurisdiction_pack_id == pack.id,
                                                                model.effective_from.isnot(None)).all():
                dates.add(eff)
    return sorted(d for d in dates if d > start and (end is None or d <= end))


def policy_floor_check(db: Session, policy: dict) -> dict:
    """The policy start plus every content boundary inside its window — an
    open-ended 48-hour policy is re-checked against a later workweek row as
    soon as that row is Active (MX-048/MX-050)."""
    start = policy["effective_from"]
    later = _content_boundaries(db, start, policy.get("effective_to"))
    # Past the Active content horizon nothing can be checked yet: those dates
    # are reported, and re-checked once content for them is activated (the
    # readiness check always runs on its own date). The start date itself
    # must be covered — without Active content it is BLOCKED_CONTENT.
    horizon = [d for d in later if _active_national_pack(db, d) is None]
    checks = [check_floors(db, policy, d) for d in [start] + [d for d in later if d not in horizon]]
    results = [c["status"] for c in checks]
    status = "FAIL" if "FAIL" in results else "BLOCKED_CONTENT" if "BLOCKED_CONTENT" in results else "PASS"
    return {"status": status, "checks": checks,
            "notYetCheckable": [{"from": d.isoformat(), "reason": "no Active national content yet — re-checked "
                                                                  "when it is activated"} for d in horizon]}


def _policy_values(data: dict) -> dict:
    eff_from, eff_to = data.get("effective_from"), data.get("effective_to")
    if not isinstance(eff_from, date):
        raise BadRequestException("effectiveFrom is required")
    if eff_to is not None and eff_to < eff_from:
        raise BadRequestException("effectiveTo must not be before effectiveFrom")
    return {"effective_from": eff_from, "effective_to": eff_to,
            "ordinary_weekly_hours": _dec(data.get("ordinary_weekly_hours"), "ordinaryWeeklyHours", positive=True),
            "aguinaldo_days": _dec(data.get("aguinaldo_days"), "aguinaldoDays"),
            "vacation_premium_pct": _dec(data.get("vacation_premium_pct"), "vacationPremiumPct"),
            "sunday_premium_pct": _dec(data.get("sunday_premium_pct"), "sundayPremiumPct"),
            "vacation_bands": _vacation_bands(data.get("vacation_policy"))}


def policy_view(row) -> dict:
    return {"id": row.id, "employerId": row.employer_profile_id, "collectiveAgreementId": row.collective_agreement_id,
            "version": row.version, "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to),
            "ordinaryWeeklyHours": _s(row.ordinary_weekly_hours), "weeklySchedule": row.weekly_schedule,
            "aguinaldoDays": _s(row.aguinaldo_days), "vacationPolicy": row.vacation_policy,
            "vacationPremiumPct": _s(row.vacation_premium_pct), "sundayPremiumPct": _s(row.sunday_premium_pct),
            "savingsFund": row.savings_fund, "foodVouchers": row.food_vouchers, "otherBenefits": row.other_benefits,
            "timeRecordDependency": row.time_record_dependency, "floorCheckStatus": row.floor_check_status,
            "floorCheckDetail": row.floor_check_detail, "status": row.status}


def _row_policy(row) -> dict:
    return {"effective_from": row.effective_from, "effective_to": row.effective_to,
            "ordinary_weekly_hours": row.ordinary_weekly_hours, "aguinaldo_days": row.aguinaldo_days,
            "vacation_premium_pct": row.vacation_premium_pct, "sunday_premium_pct": row.sunday_premium_pct,
            "vacation_bands": _vacation_bands(row.vacation_policy)}


def create_labor_policy(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import CollectiveAgreement, PayrollMxLaborPolicy as L

    root = employer_root(db, org_id, employer_id)
    values = _policy_values(data)
    cba_id = data.get("collective_agreement_id")
    if cba_id is not None:
        cba = db.get(CollectiveAgreement, cba_id)
        if (cba is None or cba.jurisdiction_country != MX
                or cba.organization_id not in (None, org_id)):
            raise NotFoundException("Mexico collective agreement", cba_id)
    check = policy_floor_check(db, values)
    version = (db.query(L).filter(L.employer_profile_id == root.id).count()) + 1
    row = L(organization_id=org_id, employer_profile_id=root.id, collective_agreement_id=cba_id, version=version,
            effective_from=values["effective_from"], effective_to=values["effective_to"],
            ordinary_weekly_hours=values["ordinary_weekly_hours"], weekly_schedule=data.get("weekly_schedule"),
            aguinaldo_days=values["aguinaldo_days"], vacation_policy=data.get("vacation_policy"),
            vacation_premium_pct=values["vacation_premium_pct"], sunday_premium_pct=values["sunday_premium_pct"],
            savings_fund=data.get("savings_fund"), food_vouchers=data.get("food_vouchers"),
            other_benefits=data.get("other_benefits"), time_record_dependency=data.get("time_record_dependency"),
            floor_check_status=check["status"], floor_check_detail=check, status="DRAFT", created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="mx_labor_policy", entity_id=row.id,
           new={"employerId": root.id, "version": version, "floorCheck": check["status"]})
    db.commit()
    db.refresh(row)
    return policy_view(row)


def activate_labor_policy(db: Session, org_id: int, policy_id: int, actor_id: Optional[int]) -> dict:
    """Re-checks the floors now (content may have changed since creation);
    only PASS activates. The previous ACTIVE policy is superseded from the
    day before."""
    from app.modules.payroll.models import PayrollMxLaborPolicy as L

    row = _owned(db, L, policy_id, org_id, "labour policy")
    et = "mx_labor_policy"
    if row.status != "DRAFT":
        _refuse(db, et, row.id, "activate", actor_id, f"only a DRAFT policy can be activated (this one is {row.status})")
    check = policy_floor_check(db, _row_policy(row))
    row.floor_check_status, row.floor_check_detail = check["status"], check
    if check["status"] != "PASS":
        db.commit()
        reason = ("it is below a statutory floor" if check["status"] == "FAIL"
                  else "a statutory floor is not in Active content yet")
        _refuse(db, et, row.id, "activate", actor_id,
                f"The policy cannot be activated: floor check {check['status']} — {reason}.")
    for prior in db.query(L).filter(L.employer_profile_id == row.employer_profile_id, L.status == "ACTIVE",
                                    L.effective_to.is_(None)).all():
        if prior.effective_from >= row.effective_from:
            _refuse(db, et, row.id, "activate", actor_id,
                    f"version {prior.version} is ACTIVE from {prior.effective_from.isoformat()} — activate in date order")
        prior.effective_to, prior.status = row.effective_from - timedelta(days=1), "SUPERSEDED"
        _audit(db, actor_id=actor_id, action="supersede", entity_type=et, entity_id=prior.id,
               new={"status": "SUPERSEDED", "by": row.id})
    db.flush()
    row.status = "ACTIVE"
    _audit(db, actor_id=actor_id, action="activate", entity_type=et, entity_id=row.id, new={"status": "ACTIVE"})
    db.commit()
    db.refresh(row)
    return policy_view(row)


def floor_check_view(db: Session, org_id: int, policy_id: int, on: date) -> dict:
    from app.modules.payroll.models import PayrollMxLaborPolicy as L

    row = _owned(db, L, policy_id, org_id, "labour policy")
    return check_floors(db, _row_policy(row), on)


def list_labor_policies(db: Session, org_id: int, root_id: int) -> list:
    from app.modules.payroll.models import PayrollMxLaborPolicy as L

    return [policy_view(r) for r in db.query(L).filter(L.organization_id == org_id,
                                                       L.employer_profile_id == root_id).order_by(L.id)]


def list_collective_agreements(db: Session, org_id: int) -> list:
    from app.modules.payroll import service

    return [{"id": a.id, "code": a.agreement_code, "name": a.name, "version": a.version, "status": a.status,
             "organizationId": a.organization_id}
            for a in service.list_collective_agreements(db, MX, organization_id=org_id)]


# ── credential references (MX-035) ───────────────────────────────────────────

def allowed_schemes() -> list:
    from app.config import settings

    return [s.strip() for s in (settings.MX_SECRET_REF_SCHEMES or "").split(",") if s.strip()]


def validate_secret_ref(value) -> str:
    """A reference, never a secret. Anything that looks like key material is
    refused BEFORE any other check, and no message ever echoes the value."""
    ref = value if isinstance(value, str) else ""
    if not ref or len(ref) > 300 or any(p.search(ref) for p in _KEY_MATERIAL):
        raise BadRequestException("secretRef refused: it must be a short Secret Manager reference "
                                  "(gcp-sm://projects/<project>/secrets/<name>[/versions/<n|latest>]) — key material, "
                                  "passwords and certificates are never accepted here.")
    schemes = allowed_schemes()
    if not any(ref.startswith(s) for s in schemes):
        raise BadRequestException(f"secretRef refused: allowed scheme(s): {', '.join(schemes)}")
    if ref.startswith("gcp-sm://") and not _GCP_SM_REF.match(ref):
        raise BadRequestException("secretRef refused: expected gcp-sm://projects/<project>/secrets/<name>"
                                  "[/versions/<n|latest>]")
    return ref


def mask_ref(ref: str) -> str:
    scheme = ref.split("://", 1)[0] + "://" if "://" in ref else ""
    return f"{scheme}…{ref[-4:]}"


def credential_view(row, *, include_ref: bool = False) -> dict:
    out = {"id": row.id, "employerId": row.employer_profile_id, "imssRegistrationId": row.imss_registration_id,
           "kind": row.kind, "secretRefMasked": mask_ref(row.secret_ref), "certificateSerial": row.certificate_serial,
           "fingerprintSha256": row.fingerprint_sha256, "subjectSummary": row.subject_summary,
           "validFrom": _iso(row.valid_from), "validTo": _iso(row.valid_to), "status": row.status,
           "rotatedFromId": row.rotated_from_id, "rfcSubjectMatch": "not checked — the SAT certificate attribute "
                                                                    "carrying the RFC is not confirmed in a saved "
                                                                    "source (S4)" if row.kind == "CSD" else None}
    if include_ref:
        out["secretRef"] = row.secret_ref          # only in the write response, to the admin who set it
    return out


def create_credential(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxCredentialRef as C, PayrollMxImssRegistration as R

    root = employer_root(db, org_id, employer_id)
    kind = (data.get("kind") or "").strip().upper()
    if kind not in _KINDS:
        raise BadRequestException(f"kind must be one of {', '.join(_KINDS)}")
    try:
        ref = validate_secret_ref(data.get("secret_ref"))
    except BadRequestException as exc:
        _refuse(db, "mx_credential_ref", 0, f"create {kind}", actor_id, exc.message)
    reg_id = data.get("imss_registration_id")
    if kind in _REGISTRATION_KINDS and reg_id is None:
        raise BadRequestException(f"a {kind} credential belongs to an IMSS registration — give imssRegistrationId")
    if kind in _EMPLOYER_KINDS and reg_id is not None:
        raise BadRequestException(f"a {kind} credential belongs to the legal employer, not a registration")
    if reg_id is not None:
        reg = _owned(db, R, reg_id, org_id, "IMSS registration")
        if reg.employer_profile_id != root.id:
            raise BadRequestException("the IMSS registration belongs to a different legal employer")
    scope = C.imss_registration_id.is_(None) if reg_id is None else C.imss_registration_id == reg_id
    prior = db.query(C).filter(C.employer_profile_id == root.id, C.kind == kind, scope, C.status == "ACTIVE").first()
    if prior is not None:
        prior.status = "ROTATED"
        db.flush()
    row = C(organization_id=org_id, employer_profile_id=root.id, imss_registration_id=reg_id, kind=kind,
            secret_ref=ref, status="ACTIVE", rotated_from_id=prior.id if prior else None, created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="rotate" if prior else "create", entity_type="mx_credential_ref",
           entity_id=row.id, new={"kind": kind, "secretRefSet": True, "rotatedFrom": prior.id if prior else None})
    db.commit()
    db.refresh(row)
    return credential_view(row, include_ref=True)


def revoke_credential(db: Session, org_id: int, credential_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxCredentialRef as C

    row = _owned(db, C, credential_id, org_id, "credential reference")
    if row.status != "ACTIVE":
        raise BadRequestException(f"only an ACTIVE credential can be revoked (this one is {row.status})")
    row.status = "REVOKED"
    _audit(db, actor_id=actor_id, action="revoke", entity_type="mx_credential_ref", entity_id=row.id,
           new={"kind": row.kind, "status": "REVOKED"})
    db.commit()
    db.refresh(row)
    return credential_view(row)


def list_credentials(db: Session, org_id: int, root_id: int) -> list:
    from app.modules.payroll.models import PayrollMxCredentialRef as C

    return [credential_view(r) for r in db.query(C).filter(C.organization_id == org_id,
                                                           C.employer_profile_id == root_id).order_by(C.id)]


def _der_length(data: bytes, pos: int) -> tuple:
    """(length, next position) of a DER length field; raises ValueError."""
    if pos >= len(data):
        raise ValueError("truncated")
    first = data[pos]
    if first < 0x80:
        return first, pos + 1
    count = first & 0x7F
    if count == 0 or count > 4 or pos + 1 + count > len(data):
        raise ValueError("bad length")
    return int.from_bytes(data[pos + 1:pos + 1 + count], "big"), pos + 1 + count


_CERT_REFUSAL = "only a single public X.509 certificate (.cer), DER or PEM, is accepted"


def screen_certificate_bytes(raw: bytes) -> tuple:
    """Plan §19 correction 2 — checked BEFORE any parsing: size cap, then
    DER (an outer SEQUENCE whose first element is itself a SEQUENCE, i.e. a
    TBSCertificate — a PKCS#8 key or PKCS#12 bundle starts with an INTEGER
    version instead) or a PEM file holding exactly one CERTIFICATE block.
    Returns ("DER" | "PEM", bytes); raises BadRequestException."""
    if not raw:
        raise BadRequestException("the certificate file is empty")
    if len(raw) > MAX_CERTIFICATE_BYTES:
        raise BadRequestException(f"the certificate file is larger than {MAX_CERTIFICATE_BYTES // 1024} KB")
    head = raw.lstrip()
    if head.startswith(b"-----BEGIN"):
        try:
            text = head.decode("ascii")
        except UnicodeDecodeError:
            raise BadRequestException(_CERT_REFUSAL)
        labels = _re.findall(r"-----BEGIN ([A-Z0-9 ]+)-----", text)
        if labels != ["CERTIFICATE"] or text.count("-----END CERTIFICATE-----") != 1:
            raise BadRequestException(_CERT_REFUSAL + " — no private key, no bundle")
        return "PEM", head
    if raw[0] == 0x30:
        try:
            outer_len, pos = _der_length(raw, 1)
        except ValueError:
            raise BadRequestException(_CERT_REFUSAL)
        if pos + outer_len != len(raw) or pos >= len(raw) or raw[pos] != 0x30:
            raise BadRequestException(_CERT_REFUSAL + " — this looks like a key or a PKCS#12 bundle")
        return "DER", raw
    raise BadRequestException(_CERT_REFUSAL)


def parse_certificate(raw: bytes) -> dict:
    """In memory only — the bytes are never written anywhere and are dropped
    after the metadata is read."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization

    kind, data = screen_certificate_bytes(raw)
    try:
        cert = (x509.load_pem_x509_certificate(data) if kind == "PEM" else x509.load_der_x509_certificate(data))
    except Exception:  # noqa: BLE001 — any parse failure is the same refusal
        raise BadRequestException(_CERT_REFUSAL + " — the file is not a valid certificate")
    der = cert.public_bytes(serialization.Encoding.DER)
    return {"certificate_serial": format(cert.serial_number, "x")[:80],
            "fingerprint_sha256": _hashlib.sha256(der).hexdigest(),
            "subject_summary": cert.subject.rfc4514_string()[:500],
            "valid_from": cert.not_valid_before_utc, "valid_to": cert.not_valid_after_utc}


def attach_certificate(db: Session, org_id: int, credential_id: int, raw: bytes, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxCredentialRef as C

    row = _owned(db, C, credential_id, org_id, "credential reference")
    if row.kind not in _CERTIFICATE_KINDS or row.status != "ACTIVE":
        raise BadRequestException(f"a certificate can be attached only to an ACTIVE {' or '.join(_CERTIFICATE_KINDS)} "
                                  "credential")
    try:
        meta = parse_certificate(raw)
    except BadRequestException as exc:
        _refuse(db, "mx_credential_ref", row.id, "attach certificate", actor_id, exc.message)
    for key, value in meta.items():
        setattr(row, key, value)
    _audit(db, actor_id=actor_id, action="certificate", entity_type="mx_credential_ref", entity_id=row.id,
           new={"kind": row.kind, "fingerprint": meta["fingerprint_sha256"], "validTo": _iso(meta["valid_to"])})
    db.commit()
    db.refresh(row)
    return credential_view(row)


# ── readiness (panel H) and G1–G8 ────────────────────────────────────────────

def _item(key, panel, label, status, detail, gates=(), scope=None) -> dict:
    gates = list(gates)
    return {"key": key, "panel": panel, "label": label, "status": status, "detail": detail,
            "gates": gates, "gateMapping": "mapped" if gates else "unmapped",
            "gateBasis": {g: GATE_DEFINITIONS[g] for g in gates}, "scope": scope or {}}


def _credential_item(cred, key, panel, label, gates, on: date, scope=None, need_cert=False):
    from app.config import settings

    if cred is None:
        return _item(key, panel, label, NOT_STARTED, "no ACTIVE reference recorded", gates, scope)
    if need_cert and cred.valid_to is None:
        return _item(key, panel, label, NOT_STARTED, "reference recorded; attach the public certificate (.cer)",
                     gates, scope)
    if cred.valid_to is not None:
        valid_to = cred.valid_to if cred.valid_to.tzinfo else cred.valid_to.replace(tzinfo=timezone.utc)
        on_dt = datetime(on.year, on.month, on.day, tzinfo=timezone.utc)
        if valid_to < on_dt:
            return _item(key, panel, label, BLOCKED, f"expired {valid_to.date().isoformat()}", gates, scope)
        if valid_to - on_dt <= timedelta(days=settings.MX_CREDENTIAL_EXPIRY_WARNING_DAYS):
            return _item(key, panel, label, WARNING, f"expires {valid_to.date().isoformat()} (within "
                         f"{settings.MX_CREDENTIAL_EXPIRY_WARNING_DAYS} days)", gates, scope)
    return _item(key, panel, label, PASS, f"reference {mask_ref(cred.secret_ref)}"
                 + (f", certificate valid to {cred.valid_to.date().isoformat()}" if cred.valid_to else ""), gates, scope)


def _catalog_has(db: Session, catalog: str, code: str) -> Optional[bool]:
    """None when no Active CFDI catalog release exists (Phase 7)."""
    from app.modules.payroll.models import PayrollMxCfdiCatalogEntry as E, PayrollMxCfdiSchemaRelease as Rel

    active = db.query(Rel.id).filter(Rel.status == "Active").all()
    if not active:
        return None
    return db.query(E.id).filter(E.schema_release_id.in_([a[0] for a in active]), E.catalog_name == catalog,
                                 E.code == code).first() is not None


def employer_readiness(db: Session, org_id: int, root_id: int, on: date) -> dict:
    from app.modules.payroll.models import (
        PayrollMxCredentialRef as C, PayrollMxEstablishment as E, PayrollMxImssRegistration as R,
        PayrollMxIsnRegistration as I, PayrollMxLaborPolicy as L, PayrollMxRiskPremium as RP,
    )

    items = []
    profile = version_in_force(db, root_id, on)
    if profile is None:
        items.append(_item("employer_version", "A", "Employer version in force", BLOCKED,
                           f"no version of this employer is in force on {on.isoformat()}", ["G1"]))
        return _summarise(db, root_id, on, None, items)
    # Panel A
    items.append(_item("rfc_format", "A", "RFC format and legal name", PASS,
                       "format valid; SAT registry/name match is the Phase 7 stamp test", ["G1"]))
    for key, catalog, code, label in (("fiscal_regime_catalog", "c_RegimenFiscal", profile.fiscal_regime_code,
                                       "Fiscal regime in the SAT catalog"),
                                      ("fiscal_postal_catalog", "c_CodigoPostal", profile.fiscal_postal_code,
                                       "Fiscal postal code in the SAT catalog")):
        found = _catalog_has(db, catalog, code)
        status = BLOCKED if found is None or found is False else PASS
        detail = ("no Active CFDI catalog release — needs S30 (SAT CFDI 4.0 catalogs, catCFDI) loaded in Phase 7" if found is None
                  else ("not in the Active catalog" if not found else "found in the Active catalog"))
        items.append(_item(key, "A", label, status, detail, ["G1"]))
    # Panel B
    items.append(_item("withholding_obligation", "B", "ISR withholding obligation active",
                       PASS if profile.withholding_obligation_active else BLOCKED,
                       "recorded as active" if profile.withholding_obligation_active else "recorded as NOT active",
                       ["G1"]))

    def active_cred(kind, reg_id=None):
        q = db.query(C).filter(C.employer_profile_id == root_id, C.kind == kind, C.status == "ACTIVE")
        q = q.filter(C.imss_registration_id.is_(None) if reg_id is None else C.imss_registration_id == reg_id)
        return q.first()

    items.append(_credential_item(active_cred("CSD"), "csd_credential", "B", "CSD certificate reference",
                                  ["G1", "G7"], on, need_cert=True))
    pac = active_cred("PAC")
    pac_item = _credential_item(pac, "pac_credential", "B", "PAC credential reference", ["G6", "G7"], on)
    if pac is not None and not (profile.pac_provider and profile.pac_environment):
        pac_item.update(status=NOT_STARTED, detail="reference recorded; set the PAC provider and environment")
    items.append(pac_item)
    items.append(_item("stamp_test", "B", "SAT stamp test", BLOCKED,
                       "Phase 7 — PAC stamping is not built; needs GCP Secret Manager live for the CSD/PAC "
                       "credentials", ["G1", "G6"]))
    # Panel C / D
    regs = [r for r in db.query(R).filter(R.employer_profile_id == root_id, R.status == "ACTIVE").all()
            if r.effective_from <= on and (r.effective_to is None or r.effective_to >= on)]
    items.append(_item("imss_registration", "C", "At least one IMSS registration in force", PASS if regs else BLOCKED,
                       f"{len(regs)} registration(s) in force" if regs else "none in force on this date", ["G2"]))
    admins = _org_admin_count(db, org_id)
    for reg in regs:
        scope = {"registrationId": reg.id, "registroPatronal": _mask(reg.registro_patronal)}
        covering = [p for p in db.query(RP).filter(RP.registration_id == reg.id, RP.status == "ACTIVE").all()
                    if p.period_from <= on <= p.period_to]
        drafts = db.query(RP).filter(RP.registration_id == reg.id, RP.status == "DRAFT").count()
        if len(covering) == 1:
            items.append(_item("risk_premium", "C", "Work-risk premium covering the date", PASS,
                               f"{covering[0].premium_rate_pct}% for {covering[0].period_from.isoformat()}–"
                               f"{covering[0].period_to.isoformat()}", ["G2"], scope))
        else:
            why = ("premium period rule awaiting S10/S14/S29 transcription"
                   if _content.MX_RISK_PREMIUM_PERIOD is None else "no approved premium covers this date")
            items.append(_item("risk_premium", "C", "Work-risk premium covering the date", BLOCKED,
                               why + (f"; {drafts} DRAFT premium(s) awaiting approval" if drafts else ""),
                               ["G2"], scope))
        if drafts:
            items.append(_item("premium_second_admin", "C", "Four-eyes premium approval",
                               BLOCKED if admins < 2 else NOT_STARTED,
                               "waiting for a second org admin — this organisation has only one active org admin"
                               if admins < 2 else "waiting for approval by an org admin other than the one who "
                                                  "recorded it", [], scope))
        items.append(_credential_item(active_cred("IDSE", reg.id), "idse_credential", "C",
                                      "IDSE credential reference", ["G6", "G7"], on, scope))
        items.append(_credential_item(active_cred("SUA", reg.id), "sua_credential", "C",
                                      "SUA credential reference", ["G6", "G7"], on, scope))
        items.append(_item("sua_reconciliation", "C", "SUA reconciliation", BLOCKED,
                           "Phase 8 — at least one IMSS/SUA reconciliation must be proven (MX-034)", ["G2"], scope))
        items.append(_item("infonavit_model", "D", "INFONAVIT operating model",
                           PASS if reg.infonavit_operating_model else NOT_STARTED,
                           reg.infonavit_operating_model or "SUA or SIPARE not chosen", ["G3"], scope))
        items.append(_item("infonavit_reconciliation", "D", "INFONAVIT reconciliation", BLOCKED,
                           "Phase 8", ["G3"], scope))
    # Establishments: minimum-wage zone (G5) and state ISN (G4)
    estabs = db.query(E).filter(E.employer_profile_id == root_id, E.is_active.is_(True)).all()
    if not estabs:
        items.append(_item("establishments", "E", "Establishments", NOT_STARTED, "no active establishment", []))
    for e in estabs:
        zone = min_wage_zone(e.state_code, e.municipality)
        items.append(_item("min_wage_zone", "E", f"Minimum-wage zone — {e.name}",
                           BLOCKED if zone["zone"] == "UNRESOLVED" else PASS, f"{zone['zone']}: {zone['detail']}",
                           ["G5"], {"establishmentId": e.id}))
    for state in sorted({e.state_code for e in estabs}):
        scope = {"state": state}
        label = f"State ISN — {state}"
        if state not in _content.MX_ISN_STATES_IN_SCOPE:
            items.append(_item("isn_state", "E", label, BLOCKED,
                               "state not supported — payroll for this state is blocked (MX-045)", ["G4"], scope))
            continue
        reg = next((r for r in db.query(I).filter(I.employer_profile_id == root_id, I.state_code == state,
                                                  I.status == "OPEN").all()
                    if r.effective_from <= on and (r.effective_to is None or r.effective_to >= on)), None)
        if reg is None:
            items.append(_item("isn_state", "E", label, BLOCKED, "register for ISN in this state", ["G4"], scope))
        else:
            view = isn_view(db, reg)
            items.append(_item("isn_state", "E", label, PASS if view["state"] == "ACTIVE" else BLOCKED,
                               "registered; state pack Active" if view["state"] == "ACTIVE"
                               else f"registered; {state} ISN content not activated (pack {view['packStatus']})",
                               ["G4"], scope))
    # Panels F / G
    policy = next((p for p in db.query(L).filter(L.employer_profile_id == root_id, L.status == "ACTIVE").all()
                   if p.effective_from <= on and (p.effective_to is None or p.effective_to >= on)), None)
    if policy is None:
        latest = db.query(L).filter(L.employer_profile_id == root_id).order_by(L.id.desc()).first()
        if latest is None:
            items.append(_item("labor_policy", "F/G", "Labour policy (workweek and benefits)", NOT_STARTED,
                               "no labour policy recorded", ["G5"]))
        else:
            check = check_floors(db, _row_policy(latest), on)
            items.append(_item("labor_policy", "F/G", "Labour policy (workweek and benefits)", BLOCKED,
                               f"version {latest.version} is {latest.status}; floor check on {on.isoformat()}: "
                               f"{check['status']}" + (f" — {check['missing'][0]}" if check["missing"] else ""),
                               ["G5"]))
    else:
        check = check_floors(db, _row_policy(policy), on)
        items.append(_item("labor_policy", "F/G", "Labour policy (workweek and benefits)",
                           PASS if check["status"] == "PASS" else BLOCKED,
                           f"version {policy.version} ACTIVE; floor check {check['status']}", ["G5"]))
    items.append(_item("time_record", "F", "Electronic time-record dependency",
                       NOT_STARTED, "interface versioning only; not in any §22 gate definition", []))
    # Phase 4b: employees of this employer with a Mexico profile in force and
    # an unresolved identifier exception (a summary line — each employee's own
    # readiness carries the gate mapping).
    from app.modules.payroll.models import EmployeeStatutoryProfile as SP

    profiles = [p for p in db.query(SP).filter(SP.organization_id == org_id, SP.country_code == MX).all()
                if p.effective_from <= on and (p.effective_to is None or p.effective_to >= on)
                and (p.mx_establishment_id in {e.id for e in estabs} or p.mx_imss_registration_id in {r.id for r in regs})]
    exceptions = [p for p in profiles if p.mx_identifier_validation_status != "VALID"]
    items.append(_item("employee_exceptions", "H", "Employees with blocking exceptions",
                       NOT_STARTED if not profiles else (BLOCKED if exceptions else PASS),
                       "no Mexican employee assigned to this employer" if not profiles
                       else f"{len(exceptions)} of {len(profiles)} employee(s) with identifier exceptions", []))
    # Bank + parallel payroll
    items.append(_credential_item(active_cred("BANK"), "bank_credential", "H", "Payroll bank credential reference",
                                  ["G6", "G7"], on))
    items.append(_item("bank_workflow", "H", "Payroll bank workflow", BLOCKED, "Phase 10", ["G6"]))
    items.append(_item("parallel_payroll", "H", "Parallel payroll", BLOCKED, "Phase 10", ["G8"]))
    return _summarise(db, root_id, on, profile, items)


def _summarise(db: Session, root_id: int, on: date, profile, items: list) -> dict:
    gates = _mx.gate_states(db)
    all_pass = all(i["status"] == PASS for i in items)
    all_signed = all(g["state"] == "SIGNED" for g in gates)
    by_gate = {}
    for g, _label in _content.GATES:
        mine = [i for i in items if g in i["gates"]]
        by_gate[g] = {"items": len(mine), "passing": sum(1 for i in mine if i["status"] == PASS),
                      "definition": GATE_DEFINITIONS[g]}
    return {"employerId": root_id, "on": on.isoformat(),
            "employer": None if profile is None else {"version": profile.version, "legalName": profile.legal_name},
            "items": items, "byGate": by_gate,
            "unmapped": [i["key"] for i in items if i["gateMapping"] == "unmapped"],
            "liveEligible": all_pass and all_signed,
            "liveBlockedBy": ([] if all_pass else ["employer readiness items not all PASS"])
                             + ([] if all_signed else ["platform gates G1–G8 not all SIGNED"])}


def organisation_readiness(db: Session, org_id: int, on: date, *, masked: bool = False) -> dict:
    from app.modules.payroll.models import PayrollMxEmployerProfile as P

    if not isinstance(on, date):
        raise BadRequestException("on (YYYY-MM-DD) is required — readiness is always for an explicit date")
    roots = db.query(P).filter(P.organization_id == org_id, P.previous_version_id.is_(None)).order_by(P.id).all()
    employers = []
    for root in roots:
        r = employer_readiness(db, org_id, root.id, on)
        r["rfc"] = _mask(root.rfc) if masked else root.rfc
        employers.append(r)
    return {"on": on.isoformat(), "employers": employers, "gates": _mx.gate_states(db)}


def readiness_summary(db: Session, on: date) -> dict:
    """Super Admin: per gate, how many employers have every item feeding that
    gate passing — the input Phase 10's gate evidence will cite."""
    from app.modules.payroll.models import PayrollMxEmployerProfile as P

    rows = db.query(P.organization_id, P.id).filter(P.previous_version_id.is_(None)).order_by(P.id).all()
    per_gate = {g: {"employers": 0, "allPassing": 0} for g, _ in _content.GATES}
    employers = []
    for org_id, root_id in rows:
        r = employer_readiness(db, org_id, root_id, on)
        first_block = next((i for i in r["items"] if i["status"] != PASS), None)
        employers.append({"organizationId": org_id, "employerId": root_id, "liveEligible": r["liveEligible"],
                          "firstBlockingItem": None if first_block is None else
                          {"key": first_block["key"], "label": first_block["label"], "detail": first_block["detail"]}})
        for g, stats in r["byGate"].items():
            if stats["items"]:
                per_gate[g]["employers"] += 1
                per_gate[g]["allPassing"] += int(stats["items"] == stats["passing"])
    return {"on": on.isoformat(), "perGate": per_gate, "employers": employers, "gates": _mx.gate_states(db),
            "definitions": GATE_DEFINITIONS}
