"""
payroll/mexico_employee_service.py
----------------------------------
Mexico (ZP-MX-ENG-001) Phase 4b — the employee statutory profile (spec §12:
Identity, Employment, Pay, IMSS, INFONAVIT, ISR, State ISN), INFONAVIT
credit notices (MX-031) and per-employee readiness.

Reached through the shared statutory-profile hooks (mexico_service wires
`statutory_profile_errors` / `statutory_profile_values` here) and the Mexico
routers. Nothing here is reachable in production while
MX_TENANT_ONBOARDING_ENABLED is off: no Mexican employee can exist.

Rules: identifiers are format-checked only until S31–S33 are saved (status
FORMAT_ONLY, never VALID); mismatches are recorded as findings, never fixed
(MX-036); the minimum-wage zone and subsidy / annual-adjustment eligibility
are derived, never stored; an INFONAVIT deduction exists only from an
authority notice with evidence (MX-031).
"""

from __future__ import annotations

import re as _re
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import mexico_employer_service as _employer
from app.modules.payroll import mexico_identity as _identity
from app.modules.payroll.engine.countries import mexico_content as _content

MX = "MX"
SALARY_TYPES = ("FIXED", "VARIABLE", "MIXED")
NOTICE_TYPES = ("RETENCION", "SUSPENSION", "MODIFICACION")
DISCOUNT_METHODS = ("FIXED_AMOUNT", "PERCENTAGE", "VSM", "UMA_FACTOR")
_CODE = _re.compile(r"^[A-Z0-9._-]{1,20}$")
_POSTAL = _re.compile(r"^[0-9]{5}$")
EDITABLE_COLUMNS = (
    "mx_fiscal_postal_code", "mx_receiver_fiscal_regime", "mx_establishment_id", "mx_imss_registration_id",
    "mx_work_state", "mx_work_municipality", "mx_remote_state_exception_ref", "mx_seniority_date",
    "mx_contract_type_code", "mx_regime_type_code", "mx_workday_type_code", "mx_job_risk_code",
    "mx_professional_min_code", "mx_pay_frequency_code", "mx_daily_salary", "mx_salary_type",
    "mx_annual_adjustment_exclusion", "mx_annual_adjustment_exclusion_evidence_ref",
)
_UPPER = ("mx_receiver_fiscal_regime", "mx_work_state", "mx_contract_type_code", "mx_regime_type_code",
          "mx_workday_type_code", "mx_job_risk_code", "mx_professional_min_code", "mx_pay_frequency_code",
          "mx_salary_type", "mx_annual_adjustment_exclusion")
_STATE_CODES = {c for c, _ in _content.MX_FEDERAL_ENTITIES}
CATALOG_FIELDS = (  # (column, SAT catalog, source) — checked against an ACTIVE CFDI release only
    ("mx_contract_type_code", "c_TipoContrato", "S28"), ("mx_regime_type_code", "c_TipoRegimen", "S28"),
    ("mx_workday_type_code", "c_TipoJornada", "S28"), ("mx_job_risk_code", "c_RiesgoPuesto", "S28"),
    ("mx_pay_frequency_code", "c_PeriodicidadPago", "S28"), ("mx_receiver_fiscal_regime", "c_RegimenFiscal", "S30"),
    ("mx_fiscal_postal_code", "c_CodigoPostal", "S30"),
)


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


# ── statutory_profile_errors hook (shape only — no DB) ───────────────────

def statutory_profile_errors(data) -> list:
    errors = []
    for col in ("mx_contract_type_code", "mx_regime_type_code", "mx_workday_type_code", "mx_job_risk_code",
                "mx_professional_min_code", "mx_pay_frequency_code", "mx_receiver_fiscal_regime",
                "mx_annual_adjustment_exclusion"):
        value = (getattr(data, col, None) or "").strip().upper()
        if value and not _CODE.match(value):
            errors.append(f"{col}: letters, digits, '.', '_' or '-' (up to 20)")
    state = (getattr(data, "mx_work_state", None) or "").strip().upper()
    if state and state not in _STATE_CODES:
        errors.append("mx_work_state must be one of the 32 federal-entity codes")
    salary_type = (getattr(data, "mx_salary_type", None) or "").strip().upper()
    if salary_type and salary_type not in SALARY_TYPES:
        errors.append(f"mx_salary_type must be one of {', '.join(SALARY_TYPES)}")
    salary = getattr(data, "mx_daily_salary", None)
    if salary is not None and salary < 0:
        errors.append("mx_daily_salary cannot be negative")
    postal = (getattr(data, "mx_fiscal_postal_code", None) or "").strip()
    if postal and not _POSTAL.match(postal):
        errors.append("mx_fiscal_postal_code: a 5-digit postal code")
    if getattr(data, "mx_annual_adjustment_exclusion", None) and not getattr(
            data, "mx_annual_adjustment_exclusion_evidence_ref", None):
        errors.append("an annual-adjustment exclusion is the employee's declaration — attach its evidence reference")
    return errors


# ── statutory_profile_values hook (full validation, carry-forward, tokens) ─

def _registration_active_on(reg, on: date) -> bool:
    return reg.status == "ACTIVE" and reg.effective_from <= on and (reg.effective_to is None or reg.effective_to >= on)


def _identifier_view(employee) -> dict:
    """Tokens, last-4 and the validation status from the raw identifiers in
    compliance_fields. Q7: refuses outside dev/test without a dedicated key."""
    fields = employee.compliance_fields or {}
    rfc, curp, nss = (fields.get(k) for k in ("rfc", "curp", "nss"))
    findings = []
    for code, label in (("S31", "CURP structure / check digit"), ("S32", "NSS check digit")):
        findings.append({"check": label, "result": "NOT_CHECKED", "detail": f"source pending ({code})"})
    findings.append({"check": "RFC ↔ CURP ↔ name / date of birth agreement", "result": "NOT_CHECKED",
                     "detail": "rule pending (S31 / SAT text) — a mismatch will be an exception, never auto-fixed"})
    return {
        "mx_rfc_token": _identity.identity_token("rfc", rfc) if rfc else None,
        "mx_rfc_last4": rfc[-4:] if rfc else None,
        "mx_curp_token": _identity.identity_token("curp", curp) if curp else None,
        "mx_nss_token": _identity.identity_token("nss", nss) if nss else None,
        "mx_identifier_validation_status": "FORMAT_ONLY" if (rfc and curp and nss) else None,
        "mx_identifier_findings": findings,
    }


def profile_values(db: Session, employee, data, previous) -> dict:
    """Each version is a full Mexico snapshot: fields not sent carry forward
    from the previous Mexican version (NL pattern)."""
    from app.modules.payroll.models import PayrollMxEstablishment as E, PayrollMxImssRegistration as R

    sent = getattr(data, "model_fields_set", set())
    values = {}
    prev_mx = previous is not None and (previous.country_code or "").upper() == MX
    for col in EDITABLE_COLUMNS:
        if col in sent:
            value = getattr(data, col)
            if isinstance(value, str):
                value = value.strip()
                value = (value.upper() if col in _UPPER else value) or None
            values[col] = value
        elif prev_mx:
            values[col] = getattr(previous, col)
    on = data.effective_from
    org_id = employee.organization_id
    est = None
    if values.get("mx_establishment_id") is not None:
        est = db.query(E).filter(E.id == values["mx_establishment_id"], E.organization_id == org_id).first()
        if est is None or not est.is_active:
            raise BadRequestException("mx_establishment_id: an active establishment of this organisation is required")
    if values.get("mx_imss_registration_id") is not None:
        reg = db.query(R).filter(R.id == values["mx_imss_registration_id"], R.organization_id == org_id).first()
        if reg is None or not _registration_active_on(reg, on):
            raise BadRequestException("mx_imss_registration_id: the IMSS registration must be ACTIVE on the "
                                      f"profile's effective date ({on.isoformat()})")
        if est is not None and reg.employer_profile_id != est.employer_profile_id:
            raise BadRequestException("the IMSS registration and the establishment belong to different legal employers")
    if est is not None and not values.get("mx_work_state"):
        values["mx_work_state"] = est.state_code                      # default only — MX-038 keeps it the employee's own
        if not values.get("mx_work_municipality"):
            values["mx_work_municipality"] = est.municipality
    if est is not None and values.get("mx_work_state") and values["mx_work_state"] != est.state_code \
            and not values.get("mx_remote_state_exception_ref"):
        raise BadRequestException("the work state differs from the establishment's state — record the remote / "
                                  "multi-state exception reference (spec §12 State ISN, MX-038)")
    code = values.get("mx_professional_min_code")
    if code:
        content = _employer._pack_content(db, on)
        rows = (content or {}).get("slabs", {}).get(_content.MX_MIN_WAGE_RULE, [])
        if not any(r.filing_status == code for r in rows):
            raise BadRequestException("mx_professional_min_code: no professional minimum with that code is in Active "
                                      f"content on {on.isoformat()} (S8/S9 not transcribed and activated)")
    if not getattr(employee, "compliance_fields", None) or not (employee.compliance_fields or {}).get("curp"):
        raise BadRequestException("record the employee's RFC, CURP and NSS (employee details) before the Mexico profile")
    values.update(_identifier_view(employee))
    return values


# ── INFONAVIT credit notices (MX-031 / MX-032) ───────────────────────────

def _mx_employee(db: Session, org_id: int, employee_id: int):
    from app.core.authz.scopes import organization_scoped
    from app.modules.payroll.models import PayrollEmployee

    emp = organization_scoped(db, PayrollEmployee, org_id).filter(PayrollEmployee.id == employee_id).first()
    if emp is None:
        raise NotFoundException("PayrollEmployee", employee_id)
    if (emp.country_code or "").upper() != MX:
        raise BadRequestException("this employee is not on Mexico payroll")
    return emp


def notice_view(row) -> dict:
    return {"id": row.id, "employeeId": row.employee_id, "creditNumber": row.credit_number,
            "noticeType": row.notice_type, "discountMethod": row.discount_method,
            "discountValue": None if row.discount_value is None else str(row.discount_value),
            "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to),
            "authorityReference": row.authority_reference, "evidenceDocumentId": row.evidence_document_id,
            "status": row.status}


def record_infonavit_notice(db: Session, org_id: int, employee_id: int, data: dict, actor_id: Optional[int]) -> dict:
    """RETENCION opens a credit deduction; MODIFICACION supersedes the open one;
    SUSPENSION closes it. Method and value are copied from the notice (with
    evidence) — never typed as a rate of the operator's own."""
    from app.modules.payroll.models import PayrollMxInfonavitNotice as N

    emp = _mx_employee(db, org_id, employee_id)
    kind = (data.get("notice_type") or "").strip().upper()
    if kind not in NOTICE_TYPES:
        raise BadRequestException(f"noticeType must be one of {', '.join(NOTICE_TYPES)}")
    credit = (data.get("credit_number") or "").strip()
    reference = (data.get("authority_reference") or "").strip()
    eff = data.get("effective_from")
    if not credit or not reference or not isinstance(eff, date):
        raise BadRequestException("creditNumber, authorityReference and effectiveFrom are required")
    _employer._evidence(db, org_id, data.get("evidence_document_id"))
    if data.get("evidence_document_id") is None:
        raise BadRequestException("attach the INFONAVIT notice itself as evidence — a credit deduction exists only "
                                  "from the authority's notice (MX-031)")
    method = (data.get("discount_method") or "").strip().upper() or None
    value = data.get("discount_value")
    if kind in ("RETENCION", "MODIFICACION"):
        if method not in DISCOUNT_METHODS or value is None:
            raise BadRequestException(f"{kind} needs the notice's discount method ({', '.join(DISCOUNT_METHODS)}) and "
                                      "value, copied from the notice")
        value = _employer._dec(value, "discountValue", positive=True)
    elif method or value is not None:
        raise BadRequestException("a SUSPENSION notice carries no discount method or value")
    open_row = db.query(N).filter(N.employee_id == emp.id, N.credit_number == credit, N.status == "RECORDED",
                                  N.effective_to.is_(None)).first()
    if kind == "RETENCION" and open_row is not None:
        raise BadRequestException(f"credit {credit} already has an open notice — record a MODIFICACION or SUSPENSION")
    if kind in ("MODIFICACION", "SUSPENSION") and open_row is None:
        raise BadRequestException(f"credit {credit} has no open notice to {kind.lower()}")
    if open_row is not None:
        if eff <= open_row.effective_from:
            raise BadRequestException(f"the {kind} must start after {open_row.effective_from.isoformat()}")
        from datetime import timedelta

        open_row.effective_to = eff - timedelta(days=1)
        open_row.status = "SUPERSEDED" if kind == "MODIFICACION" else "CLOSED"
        db.flush()
    row = N(organization_id=org_id, employee_id=emp.id, credit_number=credit, notice_type=kind,
            discount_method=method if kind != "SUSPENSION" else None,
            discount_value=value if kind != "SUSPENSION" else None, effective_from=eff,
            effective_to=eff if kind == "SUSPENSION" else None, authority_reference=reference,
            evidence_document_id=data.get("evidence_document_id"),
            status="CLOSED" if kind == "SUSPENSION" else "RECORDED", recorded_by_id=actor_id)
    db.add(row)
    db.flush()
    _employer._audit(db, actor_id=actor_id, action="create", entity_type="mx_infonavit_notice", entity_id=row.id,
                     new={"employeeId": emp.id, "credit": credit[-4:], "type": kind})
    db.commit()
    db.refresh(row)
    return notice_view(row)


def list_infonavit_notices(db: Session, org_id: int, employee_id: int) -> list:
    from app.modules.payroll.models import PayrollMxInfonavitNotice as N

    return [notice_view(r) for r in db.query(N).filter(N.organization_id == org_id, N.employee_id == employee_id)
            .order_by(N.credit_number, N.effective_from, N.id)]


# ── employee view and readiness (spec §12, §22 gates) ────────────────────

def _profile_on(db: Session, employee_id: int, on: date):
    from app.modules.payroll.models import EmployeeStatutoryProfile as P

    return (db.query(P).filter(P.employee_id == employee_id, P.country_code == MX, P.effective_from <= on,
                               (P.effective_to.is_(None)) | (P.effective_to >= on))
            .order_by(P.effective_from.desc()).first())


def profile_view(row) -> Optional[dict]:
    if row is None:
        return None
    out = {"id": row.id, "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to),
           "rfcLast4": row.mx_rfc_last4, "identifierValidationStatus": row.mx_identifier_validation_status,
           "identifierFindings": row.mx_identifier_findings or []}
    for col in EDITABLE_COLUMNS:
        value = getattr(row, col)
        out[_camel(col)] = str(value) if isinstance(value, Decimal) else _iso(value)
    return out


def _camel(col: str) -> str:
    head, *rest = col.split("_")
    return head + "".join(w.capitalize() for w in rest)


def employee_record(db: Session, org_id: int, employee_id: int, on: Optional[date] = None, *, masked_ids=True) -> dict:
    from app.modules.payroll.employee_validation import mask_compliance_fields
    from app.modules.payroll.models import EmployeeStatutoryProfile as P

    emp = _mx_employee(db, org_id, employee_id)
    versions = (db.query(P).filter(P.employee_id == emp.id, P.country_code == MX).order_by(P.effective_from).all())
    return {"employeeId": emp.id, "name": emp.name, "employeeCode": emp.employee_code, "status": emp.status,
            "identifiers": mask_compliance_fields({k: (emp.compliance_fields or {}).get(k) for k in ("rfc", "curp", "nss")}),
            "profiles": [profile_view(v) for v in versions],
            "infonavitNotices": list_infonavit_notices(db, org_id, emp.id)}


def employee_readiness(db: Session, org_id: int, employee_id: int, on: date) -> dict:
    from app.modules.payroll.models import PayrollMxEstablishment as E, PayrollMxImssRegistration as R

    if not isinstance(on, date):
        raise BadRequestException("on (YYYY-MM-DD) is required — readiness is always for an explicit date")
    emp = _mx_employee(db, org_id, employee_id)
    item = _employer._item
    PASS, BLOCKED, NOT_STARTED = _employer.PASS, _employer.BLOCKED, _employer.NOT_STARTED
    items = []
    prof = _profile_on(db, emp.id, on)
    if prof is None:
        items.append(item("mx_profile", "Identity", "Mexico statutory profile in force", NOT_STARTED,
                          f"no Mexico profile version in force on {on.isoformat()}", ["G1"]))
        return {"employeeId": emp.id, "on": on.isoformat(), "items": items, "liveEligible": False}
    status = prof.mx_identifier_validation_status
    items.append(item("identifiers", "Identity", "RFC / CURP / NSS", BLOCKED if status != "VALID" else PASS,
                      "format-checked only — check digits and the RFC↔CURP rule await S31/S32"
                      if status == "FORMAT_ONLY" else (status or "identifiers missing"), ["G1", "G2"]))
    for col, catalog, source in CATALOG_FIELDS:
        code = getattr(prof, col)
        if not code:
            items.append(item(col, "Employment", f"{catalog} code", NOT_STARTED, "not recorded", ["G1"]))
            continue
        found = _employer._catalog_has(db, catalog, code)
        items.append(item(col, "Employment", f"{catalog} code", PASS if found else BLOCKED,
                          f"no Active CFDI catalog release — needs {source} loaded in Phase 7" if found is None
                          else ("in the Active catalog" if found else "not in the Active catalog"), ["G1"]))
    reg = db.get(R, prof.mx_imss_registration_id) if prof.mx_imss_registration_id else None
    items.append(item("imss_registration", "IMSS", "IMSS registration assigned and ACTIVE",
                      PASS if reg is not None and _registration_active_on(reg, on) else BLOCKED,
                      "assigned" if reg is not None else "no registration assigned", ["G2"]))
    state = prof.mx_work_state
    if not state:
        items.append(item("isn_state", "State ISN", "Work state", NOT_STARTED, "no work state recorded", ["G4"]))
    elif state not in _content.MX_ISN_STATES_IN_SCOPE:
        items.append(item("isn_state", "State ISN", f"Work state {state}", BLOCKED,
                          "state not supported — payroll for this state is blocked (MX-045)", ["G4"]))
    else:
        pack = _employer._isn_pack(db, state)
        items.append(item("isn_state", "State ISN", f"Work state {state}",
                          PASS if pack is not None and pack.status == "Active" else BLOCKED,
                          "state ISN content Active" if pack is not None and pack.status == "Active"
                          else f"{state} ISN content not activated", ["G4"]))
    if state and prof.mx_remote_state_exception_ref:
        items.append(item("remote_exception", "State ISN", "Remote / multi-state exception", PASS,
                          f"reference {prof.mx_remote_state_exception_ref}", []))
    zone = _employer.min_wage_zone(state or "", prof.mx_work_municipality or "") if state else \
        {"zone": "UNRESOLVED", "detail": "no work state"}
    items.append(item("min_wage_zone", "Employment", "Minimum-wage zone", BLOCKED if zone["zone"] == "UNRESOLVED"
                      else PASS, f"{zone['zone']}: {zone['detail']}", ["G5"]))
    items.append(_salary_vs_minimum(db, prof, zone["zone"], on))
    key = _identity.key_status()
    items.append(item("identity_token_key", "Identity", "Dedicated MX_IDENTITY_TOKEN_KEY",
                      PASS if key == "DEDICATED" else BLOCKED,
                      {"DEDICATED": "configured", "DEV_FALLBACK": "development/test fallback in use",
                       "MISSING": "not configured"}[key], ["G7"]))
    items.append(item("clabe", "Pay", "CLABE (bank)", BLOCKED, "check digit awaits S33; no payment file before Phase 10",
                      ["G6"]))
    est = db.get(E, prof.mx_establishment_id) if prof.mx_establishment_id else None
    if est is None:
        items.append(item("establishment", "Employment", "Establishment", NOT_STARTED, "no establishment assigned", []))
    return {"employeeId": emp.id, "on": on.isoformat(), "items": items,
            "unmapped": [i["key"] for i in items if i["gateMapping"] == "unmapped"],
            "liveEligible": False}


def _salary_vs_minimum(db: Session, prof, zone: str, on: date) -> dict:
    item = _employer._item
    if prof.mx_daily_salary is None:
        return item("salary_minimum", "Pay", "Daily salary ≥ minimum wage", _employer.NOT_STARTED,
                    "no daily salary recorded", ["G5"])
    content = _employer._pack_content(db, on)
    rows = (content or {}).get("slabs", {}).get(_content.MX_MIN_WAGE_RULE, [])
    code = prof.mx_professional_min_code or (zone if zone in ("GENERAL", "ZLFN") else None)
    row = next((r for r in rows if r.filing_status == code), None) if code else None
    if row is None or row.flat_amount is None:
        return item("salary_minimum", "Pay", "Daily salary ≥ minimum wage", _employer.BLOCKED,
                    "not checked — the minimum for this zone / profession is not in Active content", ["G5"])
    ok = Decimal(prof.mx_daily_salary) >= Decimal(row.flat_amount)
    return item("salary_minimum", "Pay", "Daily salary ≥ minimum wage", _employer.PASS if ok else _employer.BLOCKED,
                f"{prof.mx_daily_salary} vs minimum {row.flat_amount} ({code})"
                + ("" if ok else " — below the minimum: exception"), ["G5"])
