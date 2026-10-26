"""
payroll/brazil_employer_service.py
----------------------------------
Brazil (ZP-BR-ENG-001) employer onboarding — Phase 3
(docs/brazil/BRAZIL_PHASE_3_PLAN.md). Mirrors mexico_employer_service.

  * Legal employer = a version chain (eSocial S-1000 validity periods): a
    change is a new version from its effective date and the open version is
    closed the day before. The CNPJ root never changes inside a chain. Every
    child record hangs off the chain ROOT, so a new version orphans nothing.
  * Establishments (S-1005): CNPJ check digits, the first 8 characters equal
    the employer's CNPJ root, at most one active headquarters. FPAS / third
    parties are DECLARED (with evidence) until checked against eSocial
    Tabela 04.
  * RAT / FAP per establishment per calendar year (the FAP is published each
    year), with evidence; DRAFT → ACTIVE supersedes the year's previous one.
  * CPRB option per calendar year (Lei 14.973/2024); sector eligibility is not
    sourced, so an opted year is a WARNING, never a PASS.
  * Credentials (eSocial A1, bank): gcp-sm:// REFERENCES only; the PKCS#12
    bundle (it contains the private key) is never accepted; the PUBLIC
    certificate may be attached and is parsed in memory, bytes discarded.
  * Readiness per legal employer on an explicit date, mapped onto G1–G8.
    It never signs a gate, and LIVE-eligible is unreachable in this phase.

Every write is audited (record_tax_audit) with CNPJ / CPF masked; a refusal is
audited too, without echoing a refused secret.
"""

from __future__ import annotations

import hashlib as _hashlib
import re as _re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import brazil_service as _br
from app.modules.payroll.employee_validation import cnpj_is_valid, cpf_is_valid

BR = "BR"
SPEC = _br.SPEC

# Spec §24 "Must be true before LIVE", verbatim — every readiness item cites
# the definition of each gate it feeds.
GATE_DEFINITIONS = {
    "G1": "Federal calculation — 2026 INSS, IRRF/reduction, minimum wage, salary-family and employee statutory "
          "content independently validated.",
    "G2": "Employer contributions — CPP/RAT/FAP/FPAS/third parties and any CPRB launch regime signed and reconciled.",
    "G3": "eSocial — Current production S-1.3 schemas/events/table catalogs implemented and acceptance/rejection/"
          "reopen flows proven.",
    "G4": "DCTFWeb — Payroll liabilities and DARF/payment reconciliation proven from accepted eSocial source data.",
    "G5": "FGTS Digital — Monthly and rescisory guide generation/reconciliation and D+10 edge cases proven.",
    "G6": "Labor/CCT — 13th, vacation, work-time/OT, VT, collective floors/benefits and termination launch cases "
          "accepted.",
    "G7": "Security/privacy — LGPD, CPF/bank/health-data controls, certificate custody, tenant/CNPJ isolation and "
          "restore procedures signed.",
    "G8": "Parallel payroll — Two consecutive cycles plus annual/termination scenarios show zero unexplained "
          "material differences.",
}

PASS, WARNING, BLOCKED, NOT_STARTED = "PASS", "WARNING", "BLOCKED", "NOT_STARTED"

_CNPJ_ROOT = _re.compile(r"^[0-9A-Z]{8}$")
_CNAE = _re.compile(r"^[0-9]{7}$")
_TAX_CLASSIFICATION = _re.compile(r"^[0-9]{2}$")
_FPAS = _re.compile(r"^[0-9]{3}$")
_THIRD_PARTY_CODE = _re.compile(r"^[0-9]{4}$")
_CEP = _re.compile(r"^[0-9]{8}$")
_IBGE = _re.compile(r"^[0-9]{7}$")
_LOTACAO = _re.compile(r"^[A-Za-z0-9_\-./]{1,30}$")
_EMAIL = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UFS = ("AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
        "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO")
_ENVIRONMENTS = ("RESTRICTED_PRODUCTION", "PRODUCTION")
# The valid RAT grades and FAP range are statutory content (BR_RAT_FAP rows,
# brazil_content.rat_fap_bounds), not constants here.
_KINDS = ("ESOCIAL_A1", "BANK")
_CERTIFICATE_KINDS = ("ESOCIAL_A1",)
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


def _audit(db: Session, *, actor_id, action, entity_type, entity_id, old=None, new=None, reason=None):
    from app.modules.payroll import service

    service.record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                             old_value=old, new_value=new, reason=reason, legal_reference=SPEC, auto_commit=False)


def _refuse(db: Session, entity_type, entity_id, attempted, actor_id, message):
    db.rollback()
    _audit(db, actor_id=actor_id, action="refused", entity_type=entity_type, entity_id=entity_id or 0,
           new={"attempted": attempted, "result": "REFUSED"}, reason=message)
    db.commit()
    raise BadRequestException(message)


def _dec(value, field: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BadRequestException(f"{field} must be a number")
    if not d.is_finite():
        raise BadRequestException(f"{field} must be a number")
    return d


def _owned(db: Session, model, row_id: int, org_id: int, label: str):
    row = db.query(model).filter(model.id == row_id, model.organization_id == org_id).first()
    if row is None:
        raise NotFoundException(label, row_id)
    return row


def _required(data: dict, key: str, label: str) -> str:
    value = (data.get(key) or "").strip() if isinstance(data.get(key), str) else data.get(key)
    if value in (None, ""):
        raise BadRequestException(f"{label} is required")
    return value


def _match(pattern, value, message):
    value = (value or "").strip().upper() if isinstance(value, str) else value
    if not isinstance(value, str) or not pattern.match(value):
        raise BadRequestException(message)
    return value


def _year(value, field="calendarYear") -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 2026 <= value <= 2100:
        raise BadRequestException(f"{field} must be a year from 2026")
    return value


# ── legal employer (version chain) ───────────────────────────────────────────

def _root_id(db: Session, row) -> int:
    from app.modules.payroll.models import PayrollBrEmployerProfile as P

    current = row
    while current.previous_version_id is not None:
        current = db.get(P, current.previous_version_id)
    return current.id


def _chain(db: Session, root_id: int) -> list:
    from app.modules.payroll.models import PayrollBrEmployerProfile as P

    rows, current = [], db.get(P, root_id)
    while current is not None:
        rows.append(current)
        current = db.query(P).filter(P.previous_version_id == current.id).first()
    return rows


def employer_root(db: Session, org_id: int, employer_id: int):
    from app.modules.payroll.models import PayrollBrEmployerProfile as P

    row = _owned(db, P, employer_id, org_id, "Brazil employer")
    return db.get(P, _root_id(db, row))


def version_in_force(db: Session, root_id: int, on: date):
    for row in _chain(db, root_id):
        if row.effective_from <= on and (row.effective_to is None or row.effective_to >= on):
            return row
    return None


def profile_view(row, *, masked: bool = False) -> dict:
    return {"id": row.id, "organizationId": row.organization_id, "version": row.version,
            "previousVersionId": row.previous_version_id, "effectiveFrom": _iso(row.effective_from),
            "effectiveTo": _iso(row.effective_to), "cnpjRoot": _mask(row.cnpj_root) if masked else row.cnpj_root,
            "legalName": row.legal_name, "tradeName": row.trade_name, "taxClassification": row.tax_classification,
            "cnaePreponderant": row.cnae_preponderant, "esocialEnvironment": row.esocial_environment,
            "esocialActiveVersion": row.esocial_active_version, "contactName": row.contact_name,
            "contactCpf": _mask(row.contact_cpf), "contactEmail": row.contact_email,
            "contactPhone": row.contact_phone, "status": row.status}


def _profile_values(data: dict) -> dict:
    if not isinstance(data.get("effective_from"), date):
        raise BadRequestException("effectiveFrom is required")
    cnpj_root = _match(_CNPJ_ROOT, data.get("cnpj_root"),
                       "cnpjRoot must be the first 8 characters of the CNPJ (digits or capital letters)")
    environment = (data.get("esocial_environment") or "").strip().upper()
    if environment not in _ENVIRONMENTS:
        raise BadRequestException(f"esocialEnvironment must be one of {', '.join(_ENVIRONMENTS)}")
    cpf = _re.sub(r"[\s.\-]", "", str(data.get("contact_cpf") or ""))
    if not cpf_is_valid(cpf):
        raise BadRequestException("contactCpf fails the CPF check digits")
    email = _required(data, "contact_email", "contactEmail")
    if not _EMAIL.match(email):
        raise BadRequestException("contactEmail is not an email address")
    return {"effective_from": data["effective_from"], "cnpj_root": cnpj_root,
            "legal_name": _required(data, "legal_name", "legalName"),
            "trade_name": (data.get("trade_name") or "").strip() or None,
            "tax_classification": _match(_TAX_CLASSIFICATION, data.get("tax_classification"),
                                         "taxClassification must be the 2-digit eSocial Tabela 08 code"),
            "cnae_preponderant": _match(_CNAE, data.get("cnae_preponderant"),
                                        "cnaePreponderant must be the 7-digit CNAE code"),
            "esocial_environment": environment, "contact_name": _required(data, "contact_name", "contactName"),
            "contact_cpf": cpf, "contact_email": email,
            "contact_phone": (data.get("contact_phone") or "").strip() or None}


def create_employer(db: Session, org_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """A new legal employer (CNPJ-root chain), version 1."""
    from app.modules.payroll.models import PayrollBrEmployerProfile as P

    values = _profile_values(data)
    if db.query(P.id).filter(P.organization_id == org_id, P.cnpj_root == values["cnpj_root"]).first():
        raise BadRequestException("this organisation already has a legal employer with that CNPJ root — record a "
                                  "new version of it instead")
    row = P(organization_id=org_id, version=1, status="ACTIVE", created_by_id=actor_id, **values)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="br_employer_profile", entity_id=row.id,
           new={"cnpjRoot": _mask(row.cnpj_root), "version": 1, "effectiveFrom": _iso(row.effective_from)})
    db.commit()
    db.refresh(row)
    return profile_view(row)


def create_employer_version(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """A change is a new version from its effective date; the open version is
    closed the day before. The CNPJ root never changes inside a chain."""
    from app.modules.payroll.models import PayrollBrEmployerProfile as P

    root = employer_root(db, org_id, employer_id)
    latest = _chain(db, root.id)[-1]
    values = _profile_values(data)
    if values["cnpj_root"] != root.cnpj_root:
        raise BadRequestException("the CNPJ root cannot change inside an employer's history — a different CNPJ "
                                  "root is a different legal employer")
    if values["effective_from"] <= latest.effective_from:
        raise BadRequestException(f"a new version must start after {latest.effective_from.isoformat()} "
                                  f"(version {latest.version})")
    latest.effective_to = values["effective_from"] - timedelta(days=1)
    db.flush()
    row = P(organization_id=org_id, version=latest.version + 1, previous_version_id=latest.id, status="ACTIVE",
            created_by_id=actor_id, **values)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="version", entity_type="br_employer_profile", entity_id=row.id,
           old={"version": latest.version, "effectiveTo": _iso(latest.effective_to)},
           new={"cnpjRoot": _mask(row.cnpj_root), "version": row.version, "effectiveFrom": _iso(row.effective_from)})
    db.commit()
    db.refresh(row)
    return profile_view(row)


def list_employers(db: Session, org_id: int, *, masked: bool = False) -> list:
    from app.modules.payroll.models import PayrollBrEmployerProfile as P

    roots = (db.query(P).filter(P.organization_id == org_id, P.previous_version_id.is_(None)).order_by(P.id).all())
    out = []
    for root in roots:
        versions = [profile_view(v, masked=masked) for v in _chain(db, root.id)]
        out.append({"employerId": root.id, "cnpjRoot": _mask(root.cnpj_root) if masked else root.cnpj_root,
                    "legalName": versions[-1]["legalName"], "versions": versions})
    return out


def employer_detail(db: Session, org_id: int, employer_id: int, *, masked: bool = False) -> dict:
    root = employer_root(db, org_id, employer_id)
    return {"employerId": root.id, "versions": [profile_view(v, masked=masked) for v in _chain(db, root.id)],
            "establishments": list_establishments(db, org_id, root.id, masked=masked),
            "cprbOptions": list_cprb_options(db, org_id, root.id),
            "credentials": list_credentials(db, org_id, root.id)}


# ── establishments ───────────────────────────────────────────────────────────

def establishment_view(row, *, masked: bool = False, risk: Optional[list] = None) -> dict:
    out = {"id": row.id, "employerId": row.employer_profile_id,
           "cnpj": _mask(row.cnpj) if masked else row.cnpj, "establishmentName": row.establishment_name,
           "isHeadquarters": bool(row.is_headquarters), "cnae": row.cnae, "fpasCode": row.fpas_code,
           "thirdPartyCode": row.third_party_code, "thirdPartyPct": _s(row.third_party_pct),
           "fpasStatus": row.fpas_status, "fpasEvidenceRef": row.fpas_evidence_ref, "lotacaoCode": row.lotacao_code,
           "postalCode": row.postal_code, "streetAddress": row.street_address, "neighborhood": row.neighborhood,
           "cityIbgeCode": row.city_ibge_code, "stateUf": row.state_uf, "judicialProcessId": row.judicial_process_id,
           "activeFrom": _iso(row.active_from), "activeTo": _iso(row.active_to)}
    if risk is not None:
        out["riskAssignments"] = risk
    return out


def _active_on(row, on: date) -> bool:
    return row.active_from <= on and (row.active_to is None or row.active_to >= on)


def create_establishment(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrEstablishment as E

    root = employer_root(db, org_id, employer_id)
    if not isinstance(data.get("active_from"), date):
        raise BadRequestException("activeFrom is required")
    cnpj = _re.sub(r"[\s./\-]", "", str(data.get("cnpj") or "")).upper()
    if not cnpj_is_valid(cnpj):
        raise BadRequestException("cnpj fails the CNPJ check digits")
    if cnpj[:8] != root.cnpj_root:
        raise BadRequestException("the establishment CNPJ must start with the employer's CNPJ root")
    if db.query(E.id).filter(E.employer_profile_id == root.id, E.cnpj == cnpj).first():
        raise BadRequestException("this employer already has an establishment with that CNPJ")
    is_hq = data.get("is_headquarters")
    if not isinstance(is_hq, bool):
        raise BadRequestException("isHeadquarters must be true or false")
    if is_hq and db.query(E.id).filter(E.employer_profile_id == root.id, E.is_headquarters.is_(True),
                                       E.active_to.is_(None)).first():
        raise BadRequestException("this employer already has an active headquarters — deactivate it first")
    third_pct = _dec(data.get("third_party_pct"), "thirdPartyPct")
    if not Decimal("0") <= third_pct <= Decimal("100"):
        raise BadRequestException("thirdPartyPct is a percent between 0 and 100")
    uf = (data.get("state_uf") or "").strip().upper()
    if uf not in _UFS:
        raise BadRequestException("stateUf must be one of the 27 Brazilian federative units")
    row = E(organization_id=org_id, employer_profile_id=root.id, cnpj=cnpj,
            establishment_name=_required(data, "establishment_name", "establishmentName"), is_headquarters=is_hq,
            cnae=_match(_CNAE, data.get("cnae"), "cnae must be the 7-digit CNAE code"),
            fpas_code=_match(_FPAS, data.get("fpas_code"), "fpasCode must be the 3-digit eSocial Tabela 04 code"),
            third_party_code=_match(_THIRD_PARTY_CODE, data.get("third_party_code"),
                                    "thirdPartyCode must be the 4-digit eSocial Tabela 04 terceiros code"),
            third_party_pct=third_pct, fpas_status="DECLARED",
            fpas_evidence_ref=_required(data, "fpas_evidence_ref", "fpasEvidenceRef")[:300],
            lotacao_code=_match(_LOTACAO, data.get("lotacao_code"), "lotacaoCode: 1–30 characters, no spaces"),
            postal_code=_match(_CEP, _re.sub(r"\D", "", str(data.get("postal_code") or "")),
                               "postalCode must be the 8-digit CEP"),
            street_address=_required(data, "street_address", "streetAddress"),
            neighborhood=_required(data, "neighborhood", "neighborhood"),
            city_ibge_code=_match(_IBGE, data.get("city_ibge_code"), "cityIbgeCode must be the 7-digit IBGE code"),
            state_uf=uf, judicial_process_id=(data.get("judicial_process_id") or "").strip() or None,
            active_from=data["active_from"], created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="br_establishment", entity_id=row.id,
           new={"cnpj": _mask(cnpj), "headquarters": is_hq, "fpas": row.fpas_code, "fpasStatus": "DECLARED"})
    db.commit()
    db.refresh(row)
    return establishment_view(row)


def deactivate_establishment(db: Session, org_id: int, establishment_id: int, active_to: date,
                             actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrEstablishment as E

    row = _owned(db, E, establishment_id, org_id, "establishment")
    if row.active_to is not None:
        raise BadRequestException("this establishment is already deactivated")
    if not isinstance(active_to, date) or active_to < row.active_from:
        raise BadRequestException("activeTo must be on or after the establishment's activeFrom")
    row.active_to = active_to
    _audit(db, actor_id=actor_id, action="deactivate", entity_type="br_establishment", entity_id=row.id,
           new={"cnpj": _mask(row.cnpj), "activeTo": _iso(active_to)})
    db.commit()
    db.refresh(row)
    return establishment_view(row)


def list_establishments(db: Session, org_id: int, root_id: int, *, masked: bool = False) -> list:
    from app.modules.payroll.models import PayrollBrEstablishment as E

    rows = db.query(E).filter(E.organization_id == org_id, E.employer_profile_id == root_id).order_by(E.id).all()
    return [establishment_view(r, masked=masked, risk=list_risk_assignments(db, org_id, r.id)) for r in rows]


# ── RAT / FAP per year ───────────────────────────────────────────────────────

def risk_view(row) -> dict:
    return {"id": row.id, "establishmentId": row.establishment_id, "calendarYear": row.calendar_year,
            "ratPct": _s(row.rat_pct), "fapFactor": _s(row.fap_factor), "evidenceRef": row.evidence_ref,
            "status": row.status}


def create_risk_assignment(db: Session, org_id: int, establishment_id: int, data: dict,
                           actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrEstablishment as E, PayrollBrRiskAssignment as R

    est = _owned(db, E, establishment_id, org_id, "establishment")
    year = _year(data.get("calendar_year"))
    from app.modules.payroll.engine.countries import brazil_content

    try:
        rat_values, fap_min, fap_max = brazil_content.rat_fap_bounds(date(year, 1, 1))
    except brazil_content.BrazilContentMissing as exc:
        raise BadRequestException(f"No Brazil RAT / FAP content for {year}: {exc}")
    rat = _dec(data.get("rat_pct"), "ratPct")
    if rat not in rat_values:
        allowed = [f"{v.normalize():f}" for v in rat_values]
        raise BadRequestException(f"ratPct must be {', '.join(allowed[:-1])} or {allowed[-1]} (percent)")
    fap = _dec(data.get("fap_factor"), "fapFactor")
    if not fap_min <= fap <= fap_max or fap != fap.quantize(Decimal("0.0001")):
        raise BadRequestException(f"fapFactor must be between {fap_min:.4f} and {fap_max:.4f} (at most 4 decimals)")
    row = R(organization_id=org_id, establishment_id=est.id, calendar_year=year, rat_pct=rat, fap_factor=fap,
            evidence_ref=_required(data, "evidence_ref", "evidenceRef")[:300], status="DRAFT", created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="create", entity_type="br_risk_assignment", entity_id=row.id,
           new={"establishment": _mask(est.cnpj), "year": year, "rat": str(rat), "fap": str(fap)})
    db.commit()
    db.refresh(row)
    return risk_view(row)


def activate_risk_assignment(db: Session, org_id: int, risk_id: int, actor_id: Optional[int]) -> dict:
    """DRAFT → ACTIVE; the year's previous ACTIVE row becomes SUPERSEDED."""
    from app.modules.payroll.models import PayrollBrRiskAssignment as R

    row = _owned(db, R, risk_id, org_id, "risk assignment")
    if row.status != "DRAFT":
        raise BadRequestException(f"only a DRAFT risk assignment can be activated (this one is {row.status})")
    prior = db.query(R).filter(R.establishment_id == row.establishment_id, R.calendar_year == row.calendar_year,
                               R.status == "ACTIVE").first()
    if prior is not None:
        prior.status = "SUPERSEDED"
        db.flush()
    row.status = "ACTIVE"
    _audit(db, actor_id=actor_id, action="activate", entity_type="br_risk_assignment", entity_id=row.id,
           new={"year": row.calendar_year, "superseded": prior.id if prior else None})
    db.commit()
    db.refresh(row)
    return risk_view(row)


def list_risk_assignments(db: Session, org_id: int, establishment_id: int) -> list:
    from app.modules.payroll.models import PayrollBrRiskAssignment as R

    return [risk_view(r) for r in db.query(R).filter(R.organization_id == org_id,
                                                     R.establishment_id == establishment_id)
            .order_by(R.calendar_year, R.id)]


def risk_in_force(db: Session, establishment_id: int, year: int):
    from app.modules.payroll.models import PayrollBrRiskAssignment as R

    return db.query(R).filter(R.establishment_id == establishment_id, R.calendar_year == year,
                              R.status == "ACTIVE").first()


# ── CPRB option per year ─────────────────────────────────────────────────────

def cprb_view(row) -> dict:
    return {"id": row.id, "employerId": row.employer_profile_id, "calendarYear": row.calendar_year,
            "opted": bool(row.opted), "sectorReference": row.sector_reference, "cprbRatePct": _s(row.cprb_rate_pct),
            "evidenceRef": row.evidence_ref, "status": row.status}


def create_cprb_option(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """Records the year's option; a later record for the same year supersedes it."""
    from app.modules.payroll.models import PayrollBrCprbOption as O

    root = employer_root(db, org_id, employer_id)
    year = _year(data.get("calendar_year"))
    opted = data.get("opted")
    if not isinstance(opted, bool):
        raise BadRequestException("opted must be true or false")
    rate = data.get("cprb_rate_pct")
    sector = (data.get("sector_reference") or "").strip() or None
    if opted:
        if rate is None or sector is None:
            raise BadRequestException("an opted year needs cprbRatePct and sectorReference")
        rate = _dec(rate, "cprbRatePct")
        if not Decimal("0") < rate <= Decimal("100"):
            raise BadRequestException("cprbRatePct is a percent above 0")
    elif rate is not None:
        raise BadRequestException("cprbRatePct applies only to an opted year")
    prior = db.query(O).filter(O.employer_profile_id == root.id, O.calendar_year == year, O.status == "ACTIVE").first()
    if prior is not None:
        prior.status = "SUPERSEDED"
        db.flush()
    row = O(organization_id=org_id, employer_profile_id=root.id, calendar_year=year, opted=opted,
            sector_reference=sector, cprb_rate_pct=rate if opted else None,
            evidence_ref=_required(data, "evidence_ref", "evidenceRef")[:300], status="ACTIVE",
            created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="supersede" if prior else "create", entity_type="br_cprb_option",
           entity_id=row.id, new={"year": year, "opted": opted, "superseded": prior.id if prior else None})
    db.commit()
    db.refresh(row)
    return cprb_view(row)


def list_cprb_options(db: Session, org_id: int, root_id: int) -> list:
    from app.modules.payroll.models import PayrollBrCprbOption as O

    return [cprb_view(r) for r in db.query(O).filter(O.organization_id == org_id, O.employer_profile_id == root_id)
            .order_by(O.calendar_year, O.id)]


# ── credential references ────────────────────────────────────────────────────

def allowed_schemes() -> list:
    from app.config import settings

    return [s.strip() for s in (settings.BR_SECRET_REF_SCHEMES or "").split(",") if s.strip()]


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
    out = {"id": row.id, "employerId": row.employer_profile_id, "kind": row.kind,
           "secretRefMasked": mask_ref(row.secret_ref), "certificateSerial": row.certificate_serial,
           "fingerprintSha256": row.fingerprint_sha256, "subjectSummary": row.subject_summary,
           "validFrom": _iso(row.valid_from), "validTo": _iso(row.valid_to), "status": row.status,
           "rotatedFromId": row.rotated_from_id}
    if include_ref:
        out["secretRef"] = row.secret_ref          # only in the write response, to the admin who set it
    return out


def create_credential(db: Session, org_id: int, employer_id: int, data: dict, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrCredentialRef as C

    root = employer_root(db, org_id, employer_id)
    kind = (data.get("kind") or "").strip().upper()
    if kind not in _KINDS:
        raise BadRequestException(f"kind must be one of {', '.join(_KINDS)}")
    try:
        ref = validate_secret_ref(data.get("secret_ref"))
    except BadRequestException as exc:
        _refuse(db, "br_credential_ref", 0, f"create {kind}", actor_id, exc.message)
    prior = db.query(C).filter(C.employer_profile_id == root.id, C.kind == kind, C.status == "ACTIVE").first()
    if prior is not None:
        prior.status = "ROTATED"
        db.flush()
    row = C(organization_id=org_id, employer_profile_id=root.id, kind=kind, secret_ref=ref, status="ACTIVE",
            rotated_from_id=prior.id if prior else None, created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id=actor_id, action="rotate" if prior else "create", entity_type="br_credential_ref",
           entity_id=row.id, new={"kind": kind, "secretRefSet": True, "rotatedFrom": prior.id if prior else None})
    db.commit()
    db.refresh(row)
    return credential_view(row, include_ref=True)


def revoke_credential(db: Session, org_id: int, credential_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrCredentialRef as C

    row = _owned(db, C, credential_id, org_id, "credential reference")
    if row.status != "ACTIVE":
        raise BadRequestException(f"only an ACTIVE credential can be revoked (this one is {row.status})")
    row.status = "REVOKED"
    _audit(db, actor_id=actor_id, action="revoke", entity_type="br_credential_ref", entity_id=row.id,
           new={"kind": row.kind, "status": "REVOKED"})
    db.commit()
    db.refresh(row)
    return credential_view(row)


def list_credentials(db: Session, org_id: int, root_id: int) -> list:
    from app.modules.payroll.models import PayrollBrCredentialRef as C

    return [credential_view(r) for r in db.query(C).filter(C.organization_id == org_id,
                                                           C.employer_profile_id == root_id).order_by(C.id)]


def _der_length(data: bytes, pos: int) -> tuple:
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
    """Checked BEFORE any parsing: size cap, then DER (an outer SEQUENCE whose
    first element is itself a SEQUENCE — a TBSCertificate; a PKCS#8 key or a
    PKCS#12 bundle starts with an INTEGER version instead) or a PEM file
    holding exactly one CERTIFICATE block. Returns ("DER" | "PEM", bytes)."""
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
    """In memory only — the bytes are never written anywhere."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    kind, data = screen_certificate_bytes(raw)
    try:
        cert = x509.load_pem_x509_certificate(data) if kind == "PEM" else x509.load_der_x509_certificate(data)
    except Exception:  # noqa: BLE001 — any parse failure is the same refusal
        raise BadRequestException(_CERT_REFUSAL + " — the file is not a valid certificate")
    der = cert.public_bytes(serialization.Encoding.DER)
    return {"certificate_serial": format(cert.serial_number, "x")[:80],
            "fingerprint_sha256": _hashlib.sha256(der).hexdigest(),
            "subject_summary": cert.subject.rfc4514_string()[:500],
            "valid_from": cert.not_valid_before_utc, "valid_to": cert.not_valid_after_utc}


def attach_certificate(db: Session, org_id: int, credential_id: int, raw: bytes, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrCredentialRef as C

    row = _owned(db, C, credential_id, org_id, "credential reference")
    if row.kind not in _CERTIFICATE_KINDS or row.status != "ACTIVE":
        raise BadRequestException("a certificate can be attached only to an ACTIVE ESOCIAL_A1 credential")
    try:
        meta = parse_certificate(raw)
    except BadRequestException as exc:
        _refuse(db, "br_credential_ref", row.id, "attach certificate", actor_id, exc.message)
    for key, value in meta.items():
        setattr(row, key, value)
    _audit(db, actor_id=actor_id, action="certificate", entity_type="br_credential_ref", entity_id=row.id,
           new={"kind": row.kind, "fingerprint": meta["fingerprint_sha256"], "validTo": _iso(meta["valid_to"])})
    db.commit()
    db.refresh(row)
    return credential_view(row)


# ── readiness and G1–G8 ──────────────────────────────────────────────────────

def _item(key, section, label, status, detail, gates=(), scope=None) -> dict:
    gates = list(gates)
    return {"key": key, "section": section, "label": label, "status": status, "detail": detail, "gates": gates,
            "gateBasis": {g: GATE_DEFINITIONS[g] for g in gates}, "scope": scope or {}}


def _credential_item(cred, on: date) -> dict:
    from app.config import settings

    key, section, label, gates = "esocial_a1", "credentials", "eSocial A1 certificate reference", ("G3", "G7")
    if cred is None:
        return _item(key, section, label, NOT_STARTED, "no ACTIVE ESOCIAL_A1 reference recorded", gates)
    if cred.valid_to is None:
        return _item(key, section, label, NOT_STARTED, "reference recorded; attach the PUBLIC certificate (.cer) "
                     "so its validity can be checked", gates)
    valid_to = cred.valid_to if cred.valid_to.tzinfo else cred.valid_to.replace(tzinfo=timezone.utc)
    on_dt = datetime(on.year, on.month, on.day, tzinfo=timezone.utc)
    if valid_to < on_dt:
        return _item(key, section, label, BLOCKED, f"certificate expired {valid_to.date().isoformat()}", gates)
    window = settings.BR_CREDENTIAL_EXPIRY_WARNING_DAYS
    if valid_to - on_dt <= timedelta(days=window):
        return _item(key, section, label, WARNING, f"certificate expires {valid_to.date().isoformat()} (within "
                     f"{window} days)", gates)
    return _item(key, section, label, PASS, f"reference {mask_ref(cred.secret_ref)}, certificate valid to "
                 f"{valid_to.date().isoformat()}", gates)


# Items that only a later phase can satisfy — always BLOCKED in Phase 3.
_LATER_PHASE_ITEMS = (
    ("engine_certified", "platform", "Brazil calculation engine certified", "Phase 5", ("G1",)),
    ("esocial_events", "platform", "eSocial S-1.3 events (S-1000/S-1005/S-1020…) accepted", "Phase 9", ("G3",)),
    ("dctfweb", "platform", "DCTFWeb / DARF reconciliation", "Phase 10", ("G4",)),
    ("fgts_digital", "platform", "FGTS Digital guides and D+10 reconciliation", "Phase 10", ("G5",)),
    ("labor_cct", "platform", "13th / vacation / termination / collective agreements", "Phases 7–8", ("G6",)),
    ("parallel_payroll", "platform", "Two consecutive parallel payroll cycles", "Phase 11", ("G8",)),
)


def employer_readiness(db: Session, org_id: int, root_id: int, on: date) -> dict:
    from app.modules.payroll.models import (
        PayrollBrCprbOption as O, PayrollBrCredentialRef as C, PayrollBrEstablishment as E,
    )

    if not isinstance(on, date):
        raise BadRequestException("on is required")
    root = employer_root(db, org_id, root_id)
    items = []
    version = version_in_force(db, root.id, on)
    if version is None:
        items.append(_item("employer_version", "employer", "Employer version in force", NOT_STARTED,
                           f"no employer version covers {on.isoformat()}", ("G1",)))
    else:
        items.append(_item("employer_version", "employer", "Employer version in force", PASS,
                           f"version {version.version} from {version.effective_from.isoformat()}", ("G1",)))
        items.append(_item("tax_classification", "employer", "Tax classification (eSocial Tabela 08)", WARNING,
                           f"code {version.tax_classification} recorded; the code list is not yet checked against "
                           "a saved Tabela 08", ("G3",)))

    establishments = [e for e in db.query(E).filter(E.organization_id == org_id, E.employer_profile_id == root.id)
                      .order_by(E.id).all() if _active_on(e, on)]
    hq = [e for e in establishments if e.is_headquarters]
    if not establishments:
        items.append(_item("establishments", "establishments", "At least one active establishment", NOT_STARTED,
                           f"no establishment active on {on.isoformat()}", ("G2",)))
    else:
        items.append(_item("establishments", "establishments", "Active establishments with one headquarters",
                           PASS if len(hq) == 1 else BLOCKED,
                           f"{len(establishments)} active, {len(hq)} headquarters", ("G2",)))
    for est in establishments:
        scope = {"establishmentId": est.id, "cnpj": _mask(est.cnpj)}
        risk = risk_in_force(db, est.id, on.year)
        items.append(_item("risk", "risk", f"RAT / FAP for {on.year}",
                           PASS if risk else BLOCKED,
                           f"RAT {risk.rat_pct}% × FAP {risk.fap_factor}" if risk else
                           f"no ACTIVE risk assignment for {on.year}", ("G2",), scope))
        items.append(_item("fpas", "establishments", "FPAS / third parties checked against eSocial Tabela 04",
                           PASS if est.fpas_status == "VERIFIED" else BLOCKED,
                           "VERIFIED" if est.fpas_status == "VERIFIED" else
                           f"FPAS {est.fpas_code} / {est.third_party_code} at {est.third_party_pct}% is DECLARED — "
                           "not yet checked against Tabela 04", ("G2",), scope))

    option = db.query(O).filter(O.employer_profile_id == root.id, O.calendar_year == on.year,
                                O.status == "ACTIVE").first()
    if option is None:
        items.append(_item("cprb", "cprb", f"CPRB option for {on.year}", NOT_STARTED,
                           "no CPRB option recorded for the year (record opted = false for standard CPP)", ("G2",)))
    elif option.opted:
        items.append(_item("cprb", "cprb", f"CPRB option for {on.year}", WARNING,
                           f"opted at {option.cprb_rate_pct}% ({option.sector_reference}); sector eligibility "
                           "under Lei 14.973/2024 is not verified against a saved source", ("G2",)))
    else:
        items.append(_item("cprb", "cprb", f"CPRB option for {on.year}", PASS, "not opted — standard CPP", ("G2",)))

    cred = db.query(C).filter(C.employer_profile_id == root.id, C.kind == "ESOCIAL_A1",
                              C.status == "ACTIVE").first()
    items.append(_credential_item(cred, on))
    for key, section, label, phase, gates in _LATER_PHASE_ITEMS:
        items.append(_item(key, section, label, BLOCKED, f"built in {phase}", gates))

    gates = _br.gate_states(db)
    all_pass = all(i["status"] == PASS for i in items)
    return {"employerId": root.id, "cnpjRoot": _mask(root.cnpj_root),
            "legalName": (version or _chain(db, root.id)[-1]).legal_name, "on": on.isoformat(), "items": items,
            "allItemsPass": all_pass,
            "liveEligible": all_pass and all(g["state"] == "SIGNED" for g in gates)}


def organisation_readiness(db: Session, org_id: int, on: date) -> dict:
    from app.modules.payroll.models import PayrollBrEmployerProfile as P

    if not isinstance(on, date):
        raise BadRequestException("on is required")
    roots = db.query(P).filter(P.organization_id == org_id, P.previous_version_id.is_(None)).order_by(P.id).all()
    return {"on": on.isoformat(), "employers": [employer_readiness(db, org_id, r.id, on) for r in roots],
            "gates": _br.gate_states(db)}


def readiness_summary(db: Session, on: date) -> dict:
    """Super Admin: per gate, how many legal employers have every item that
    feeds that gate passing. The input Phase 11's gate evidence will cite."""
    from app.modules.payroll.models import PayrollBrEmployerProfile as P

    roots = db.query(P).filter(P.previous_version_id.is_(None)).order_by(P.id).all()
    per_gate = {g: 0 for g in GATE_DEFINITIONS}
    for root in roots:
        items = employer_readiness(db, root.organization_id, root.id, on)["items"]
        for gate in per_gate:
            fed = [i for i in items if gate in i["gates"]]
            if fed and all(i["status"] == PASS for i in fed):
                per_gate[gate] += 1
    return {"on": on.isoformat(), "employers": len(roots), "passingByGate": per_gate, "gates": _br.gate_states(db)}
