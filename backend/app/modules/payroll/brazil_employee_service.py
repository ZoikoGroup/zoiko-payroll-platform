"""
payroll/brazil_employee_service.py
----------------------------------
Brazil (ZP-BR-ENG-001) Phase 4b — the CLT employee statutory profile (spec §7)
plus the concurrent-employment INSS declarations (BR-009), court-ordered
alimony orders and vale-transporte elections, and per-employee readiness.

Reached through the shared statutory-profile hooks (brazil_service wires
`statutory_profile_errors` / `statutory_profile_values` here) and the
organisation / Super Admin routers. Every path is dormant behind
BR_TENANT_ONBOARDING_ENABLED (Phase 3) — no Brazilian employee can exist until
it is on.

Phase 4 only RECORDS statutory facts with their evidence. No figure is
calculated here: the INSS/IRRF arithmetic, the alimony deduction and the
vale-transporte 6% cap are all Phase 5.
"""

from __future__ import annotations

import re as _re
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.authz.scopes import organization_scoped
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import brazil_employer_service as _employer

BR = "BR"
ESOCIAL_CATEGORIES = ("101", "103")                     # launch wedge (spec §1)
CONTRACT_TYPES = ("INDEFINITE", "DETERMINED", "INTERMITTENT")
ALIMONY_METHODS = ("FIXED_AMOUNT", "PERCENTAGE")
ALIMONY_BASES = ("GROSS", "NET", "BASE_INSS", "BASE_IRRF")
CONCURRENT_STATUSES = ("RECORDED", "SUPERSEDED")
_CBO = _re.compile(r"^[0-9]{6}$")
_UPPER = ("br_esocial_category", "br_contract_type")

# The br_* columns on the shared payroll_employee_statutory_profiles table that
# this jurisdiction owns (see models.EmployeeStatutoryProfile's BR block).
EDITABLE_COLUMNS = (
    "br_establishment_id", "br_esocial_category", "br_cbo_code", "br_contract_type", "br_weekly_hours",
    "br_simplified_irrf_opt_out", "br_irrf_dependents_count", "br_irrf_dependents_evidence_ref",
    "br_salario_familia_dependents_count", "br_salario_familia_dependents_evidence_ref",
)

PASS, WARNING, BLOCKED, NOT_STARTED = _employer.PASS, _employer.WARNING, _employer.BLOCKED, _employer.NOT_STARTED


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


def _s(v):
    return None if v is None else str(v)


def _camel(col: str) -> str:
    head, *rest = col.split("_")
    return head + "".join(w.capitalize() for w in rest)


# ── statutory_profile_errors hook (shape only — no DB) ───────────────────

def statutory_profile_errors(data) -> list:
    """Field-level Brazil checks that need no DB state. Every value is the
    employer's declared fact; nothing is derived or invented here."""
    errors = []
    category = getattr(data, "br_esocial_category", None)
    if category is not None and str(category).strip().upper() not in ESOCIAL_CATEGORIES:
        errors.append(f"br_esocial_category must be one of {list(ESOCIAL_CATEGORIES)} "
                      "(ordinary CLT 101 / apprentice 103 — the launch wedge).")
    cbo = getattr(data, "br_cbo_code", None)
    if cbo not in (None, "") and not _CBO.match(str(cbo).strip()):
        errors.append("br_cbo_code must be a 6-digit CBO code.")
    contract = getattr(data, "br_contract_type", None)
    if contract is not None and str(contract).strip().upper() not in CONTRACT_TYPES:
        errors.append(f"br_contract_type must be one of {list(CONTRACT_TYPES)}.")
    hours = getattr(data, "br_weekly_hours", None)
    if hours is not None:
        try:
            value = Decimal(str(hours))
        except Exception:
            errors.append("br_weekly_hours must be a number.")
        else:
            if value <= 0 or value > 44:
                errors.append("br_weekly_hours must be greater than 0 and at most 44.")
    for count_col, evidence_col, label in (
        ("br_irrf_dependents_count", "br_irrf_dependents_evidence_ref", "IRRF"),
        ("br_salario_familia_dependents_count", "br_salario_familia_dependents_evidence_ref", "salário-família"),
    ):
        count = getattr(data, count_col, None)
        if count is not None:
            try:
                n = int(count)
            except (TypeError, ValueError):
                errors.append(f"{count_col} must be a whole number.")
                continue
            if n < 0:
                errors.append(f"{count_col} must not be negative.")
            elif n > 0 and not getattr(data, evidence_col, None):
                errors.append(f"{count_col} > 0 — attach the {label} dependants' evidence reference "
                              f"({evidence_col}).")
    return errors


# ── statutory_profile_values hook (carry-forward + FK validation) ─────────

def _establishment_active_on(est, on: date) -> bool:
    return bool(est.active_from <= on and (est.active_to is None or est.active_to >= on))


def profile_values(db: Session, employee, data, previous) -> dict:
    """Each version is a full Brazil snapshot: a field not sent carries forward
    from the previous Brazilian version (the Mexico pattern). The establishment
    must be the organisation's own and ACTIVE on the profile's effective date."""
    from app.modules.payroll.models import PayrollBrEstablishment as E

    sent = getattr(data, "model_fields_set", set())
    values: dict = {}
    prev_br = previous is not None and (previous.country_code or "").upper() == BR
    for col in EDITABLE_COLUMNS:
        if col in sent:
            value = getattr(data, col)
            if isinstance(value, str):
                value = value.strip()
                value = (value.upper() if col in _UPPER else value) or None
            if col == "br_weekly_hours" and value is not None:
                value = _employer._dec(value, "br_weekly_hours")
            if col.endswith("_count") and value is not None:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise BadRequestException(f"{col} must be a whole number")
            values[col] = value
        elif prev_br:
            values[col] = getattr(previous, col)

    on = data.effective_from
    org_id = employee.organization_id
    if values.get("br_establishment_id") is not None:
        est = db.query(E).filter(E.id == values["br_establishment_id"], E.organization_id == org_id).first()
        if est is None:
            raise BadRequestException("br_establishment_id: an establishment of this organisation is required")
        if not _establishment_active_on(est, on):
            raise BadRequestException("br_establishment_id: the establishment must be ACTIVE on the profile's "
                                      f"effective date ({on.isoformat()})")
    return values


# ── views ────────────────────────────────────────────────────────────────

def profile_view(row) -> Optional[dict]:
    if row is None:
        return None
    out = {"id": row.id, "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to)}
    for col in EDITABLE_COLUMNS:
        value = getattr(row, col)
        out[_camel(col)] = str(value) if isinstance(value, Decimal) else _iso(value)
    return out


def _br_employee(db: Session, org_id: int, employee_id: int):
    from app.modules.payroll.models import PayrollEmployee

    emp = organization_scoped(db, PayrollEmployee, org_id).filter(PayrollEmployee.id == employee_id).first()
    if emp is None:
        raise NotFoundException("PayrollEmployee", employee_id)
    if (emp.country_code or "").upper() != BR:
        raise BadRequestException("this employee is not on Brazil payroll")
    return emp


def _profile_on(db: Session, employee_id: int, on: date):
    from app.modules.payroll.models import EmployeeStatutoryProfile as P

    return (db.query(P).filter(P.employee_id == employee_id, P.country_code == BR, P.effective_from <= on,
                               (P.effective_to.is_(None)) | (P.effective_to >= on))
            .order_by(P.effective_from.desc()).first())


def profile_versions(db: Session, employee_id: int) -> list:
    from app.modules.payroll.models import EmployeeStatutoryProfile as P

    return (db.query(P).filter(P.employee_id == employee_id, P.country_code == BR)
            .order_by(P.effective_from).all())


# ── concurrent-employment INSS declarations (BR-009) ─────────────────────

def concurrent_view(row) -> dict:
    return {"id": row.id, "employeeId": row.employee_id, "competenceMonth": _iso(row.competence_month),
            "baseExternal": _s(row.base_external), "deductedExternal": _s(row.deducted_external),
            "evidenceRef": row.evidence_ref, "status": row.status, "createdAt": _iso(row.created_at)}


def record_concurrent_inss_declaration(db: Session, org_id: int, employee_id: int, data: dict,
                                       actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrConcurrentInssDeclaration as D

    emp = _br_employee(db, org_id, employee_id)
    month = data.get("competence_month")
    if not isinstance(month, date):
        raise BadRequestException("competenceMonth (YYYY-MM-DD, the first day of the month) is required")
    month = month.replace(day=1)
    base = _employer._dec(data.get("base_external"), "baseExternal")
    deducted = _employer._dec(data.get("deducted_external"), "deductedExternal")
    if base < 0 or deducted < 0:
        raise BadRequestException("baseExternal and deductedExternal must not be negative")
    prior = (db.query(D).filter(D.employee_id == emp.id, D.competence_month == month)
             .order_by(D.id.desc()).first())
    if prior is not None:
        prior.status = "SUPERSEDED"
        db.flush()
    row = D(organization_id=org_id, employee_id=emp.id, competence_month=month, base_external=base,
            deducted_external=deducted, evidence_ref=(data.get("evidence_ref") or "").strip() or None,
            status="RECORDED", created_by_id=actor_id)
    db.add(row)
    db.flush()
    _employer._audit(db, actor_id=actor_id, action="supersede" if prior else "create",
                     entity_type="br_concurrent_inss_declaration", entity_id=row.id,
                     new={"employeeId": emp.id, "competenceMonth": month.isoformat()})
    db.commit()
    db.refresh(row)
    return concurrent_view(row)


def list_concurrent_inss_declarations(db: Session, org_id: int, employee_id: int) -> list:
    from app.modules.payroll.models import PayrollBrConcurrentInssDeclaration as D

    return [concurrent_view(r) for r in db.query(D).filter(D.organization_id == org_id,
                                                           D.employee_id == employee_id)
            .order_by(D.competence_month.desc(), D.id.desc())]


# ── court-ordered alimony ────────────────────────────────────────────────

def alimony_view(row) -> dict:
    return {"id": row.id, "employeeId": row.employee_id, "orderReference": row.order_reference,
            "method": row.method, "fixedAmount": _s(row.fixed_amount), "percentage": _s(row.percentage),
            "base": row.base, "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to),
            "evidenceRef": row.evidence_ref, "status": row.status}


def record_alimony_order(db: Session, org_id: int, employee_id: int, data: dict,
                         actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrAlimonyOrder as A

    emp = _br_employee(db, org_id, employee_id)
    reference = (data.get("order_reference") or "").strip()
    method = (data.get("method") or "").strip().upper()
    eff = data.get("effective_from")
    if not reference or not isinstance(eff, date):
        raise BadRequestException("orderReference and effectiveFrom are required")
    if method not in ALIMONY_METHODS:
        raise BadRequestException(f"method must be one of {list(ALIMONY_METHODS)}")
    fixed = percentage = base = None
    if method == "FIXED_AMOUNT":
        fixed = _employer._dec(data.get("fixed_amount"), "fixedAmount")
        if fixed <= 0:
            raise BadRequestException("a fixed-amount order needs a positive fixedAmount")
    else:
        percentage = _employer._dec(data.get("percentage"), "percentage")
        base = (data.get("base") or "").strip().upper()
        if percentage <= 0 or percentage > 100:
            raise BadRequestException("percentage must be greater than 0 and at most 100")
        if base not in ALIMONY_BASES:
            raise BadRequestException(f"base must be one of {list(ALIMONY_BASES)}")
    open_row = (db.query(A).filter(A.employee_id == emp.id, A.order_reference == reference,
                                   A.status == "ACTIVE", A.effective_to.is_(None)).first())
    if open_row is not None:
        if eff <= open_row.effective_from:
            raise BadRequestException(f"the new order must start after {open_row.effective_from.isoformat()}")
        from datetime import timedelta

        open_row.effective_to = eff - timedelta(days=1)
        open_row.status = "SUPERSEDED"
        db.flush()
    row = A(organization_id=org_id, employee_id=emp.id, order_reference=reference, method=method,
            fixed_amount=fixed, percentage=percentage, base=base, effective_from=eff,
            evidence_ref=(data.get("evidence_ref") or "").strip() or None, status="ACTIVE", created_by_id=actor_id)
    db.add(row)
    db.flush()
    _employer._audit(db, actor_id=actor_id, action="create", entity_type="br_alimony_order", entity_id=row.id,
                     new={"employeeId": emp.id, "reference": reference[-6:], "method": method})
    db.commit()
    db.refresh(row)
    return alimony_view(row)


def close_alimony_order(db: Session, org_id: int, order_id: int, data: dict,
                        actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrAlimonyOrder as A

    row = _employer._owned(db, A, order_id, org_id, "Brazil alimony order")
    if row.status != "ACTIVE":
        raise BadRequestException("this alimony order is not ACTIVE")
    eff = data.get("effective_to")
    if not isinstance(eff, date):
        raise BadRequestException("effectiveTo is required to close an order")
    if eff < row.effective_from:
        raise BadRequestException("effectiveTo must not be before the order's effectiveFrom")
    row.effective_to = eff
    row.status = "CLOSED"
    _employer._audit(db, actor_id=actor_id, action="close", entity_type="br_alimony_order", entity_id=row.id,
                     new={"effectiveTo": eff.isoformat()})
    db.commit()
    db.refresh(row)
    return alimony_view(row)


def list_alimony_orders(db: Session, org_id: int, employee_id: int) -> list:
    from app.modules.payroll.models import PayrollBrAlimonyOrder as A

    return [alimony_view(r) for r in db.query(A).filter(A.organization_id == org_id, A.employee_id == employee_id)
            .order_by(A.order_reference, A.effective_from, A.id)]


# ── vale-transporte elections ────────────────────────────────────────────

def vt_view(row) -> dict:
    return {"id": row.id, "employeeId": row.employee_id, "elected": row.elected, "dailyCost": _s(row.daily_cost),
            "effectiveFrom": _iso(row.effective_from), "effectiveTo": _iso(row.effective_to),
            "evidenceRef": row.evidence_ref, "status": row.status}


def record_vale_transporte_election(db: Session, org_id: int, employee_id: int, data: dict,
                                    actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollBrValeTransporteElection as V
    from datetime import timedelta

    emp = _br_employee(db, org_id, employee_id)
    elected = bool(data.get("elected"))
    eff = data.get("effective_from")
    if not isinstance(eff, date):
        raise BadRequestException("effectiveFrom is required")
    daily = data.get("daily_cost")
    if elected:
        if daily is None:
            raise BadRequestException("a vale-transporte election needs the declared dailyCost")
        daily = _employer._dec(daily, "dailyCost")
        if daily < 0:
            raise BadRequestException("dailyCost must not be negative")
    else:
        daily = None
    open_row = (db.query(V).filter(V.employee_id == emp.id, V.status == "ACTIVE", V.effective_to.is_(None))
                .first())
    if open_row is not None:
        if eff <= open_row.effective_from:
            raise BadRequestException(f"the election must start after {open_row.effective_from.isoformat()}")
        open_row.effective_to = eff - timedelta(days=1)
        open_row.status = "SUPERSEDED"
        db.flush()
    row = V(organization_id=org_id, employee_id=emp.id, elected=elected, daily_cost=daily, effective_from=eff,
            evidence_ref=(data.get("evidence_ref") or "").strip() or None, status="ACTIVE", created_by_id=actor_id)
    db.add(row)
    db.flush()
    _employer._audit(db, actor_id=actor_id, action="supersede" if open_row else "create",
                     entity_type="br_vale_transporte_election", entity_id=row.id,
                     new={"employeeId": emp.id, "elected": elected})
    db.commit()
    db.refresh(row)
    return vt_view(row)


def list_vale_transporte_elections(db: Session, org_id: int, employee_id: int) -> list:
    from app.modules.payroll.models import PayrollBrValeTransporteElection as V

    return [vt_view(r) for r in db.query(V).filter(V.organization_id == org_id, V.employee_id == employee_id)
            .order_by(V.effective_from.desc(), V.id.desc())]


# ── employee view and readiness ──────────────────────────────────────────

def employee_record(db: Session, org_id: int, employee_id: int, on: Optional[date] = None, *,
                    masked_ids: bool = True) -> dict:
    from app.modules.payroll.employee_validation import mask_compliance_fields

    emp = _br_employee(db, org_id, employee_id)
    versions = [profile_view(v) for v in profile_versions(db, emp.id)]
    if on is not None:
        versions = [v for v in versions if v["effectiveFrom"] <= on.isoformat()
                    and (v["effectiveTo"] is None or v["effectiveTo"] >= on.isoformat())]
    return {"employeeId": emp.id, "name": emp.name, "employeeCode": emp.employee_code, "status": emp.status,
            "identifiers": mask_compliance_fields({k: (emp.compliance_fields or {}).get(k)
                                                   for k in ("cpf", "pis_nis", "pix_key", "bank_account")}),
            "profiles": versions,
            "concurrentInssDeclarations": list_concurrent_inss_declarations(db, org_id, emp.id),
            "alimonyOrders": list_alimony_orders(db, org_id, emp.id),
            "valeTransporteElections": list_vale_transporte_elections(db, org_id, emp.id)}


def employee_readiness(db: Session, org_id: int, employee_id: int, on: date) -> dict:
    from app.modules.payroll.models import PayrollBrAlimonyOrder as A, PayrollBrConcurrentInssDeclaration as D
    from app.modules.payroll.models import PayrollBrEstablishment as E, PayrollBrValeTransporteElection as V

    if not isinstance(on, date):
        raise BadRequestException("on (YYYY-MM-DD) is required — readiness is always for an explicit date")
    emp = _br_employee(db, org_id, employee_id)
    item = _employer._item
    items = []
    prof = _profile_on(db, emp.id, on)
    if prof is None:
        items.append(item("br_profile", "Identity", "Brazil statutory profile in force", NOT_STARTED,
                          f"no Brazil profile version in force on {on.isoformat()}", ["G1"]))
        return {"employeeId": emp.id, "on": on.isoformat(), "items": items, "liveEligible": False}

    est = db.get(E, prof.br_establishment_id) if prof.br_establishment_id else None
    est_ok = est is not None and _establishment_active_on(est, on)
    detail = ("active establishment of this organisation" if est_ok
              else "the recorded establishment is not ACTIVE on this date" if est is not None
              else "no establishment recorded")
    items.append(item("br_establishment", "Employment", "Establishment assigned and ACTIVE on the date",
                      PASS if est_ok else BLOCKED, detail, ["G1"]))
    items.append(item("br_category", "Employment", "eSocial category / CBO / contract",
                      PASS if prof.br_esocial_category and prof.br_cbo_code and prof.br_contract_type else BLOCKED,
                      f"category {prof.br_esocial_category or '—'}, CBO {prof.br_cbo_code or '—'}, "
                      f"{prof.br_contract_type or '—'}", ["G1"]))
    for count_col, evidence_col, key, label in (
        ("br_irrf_dependents_count", "br_irrf_dependents_evidence_ref", "br_irrf_dependants", "IRRF dependants"),
        ("br_salario_familia_dependents_count", "br_salario_familia_dependents_evidence_ref",
         "br_salario_familia_dependants", "Salário-família dependants"),
    ):
        count = getattr(prof, count_col) or 0
        has_evidence = bool(getattr(prof, evidence_col))
        ok = count == 0 or has_evidence
        items.append(item(key, "Dependants", label, PASS if ok else BLOCKED,
                          f"{count} dependant(s)" + ("" if ok else " — evidence reference required"), ["G1"]))

    month_start = on.replace(day=1)
    declared = (db.query(D).filter(D.organization_id == org_id, D.employee_id == emp.id,
                                   D.competence_month == month_start, D.status == "RECORDED").first())
    items.append(item("br_concurrent_inss", "INSS", "Concurrent-employment INSS declared for the competência",
                      PASS if declared is not None else NOT_STARTED,
                      f"declared for {month_start.isoformat()}" if declared is not None
                      else "no concurrent-employment declaration for this month (required if the employee has other employment)",
                      ["G3"]))

    vt = (db.query(V).filter(V.organization_id == org_id, V.employee_id == emp.id, V.status == "ACTIVE",
                             V.effective_from <= on, (V.effective_to.is_(None)) | (V.effective_to >= on))
          .order_by(V.effective_from.desc()).first())
    items.append(item("br_vale_transporte", "Benefits", "Vale-transporte election current",
                      PASS if vt is not None else NOT_STARTED,
                      ("elected" if vt.elected else "declined") if vt is not None
                      else "no vale-transporte election recorded", ["G1"]))

    alimony = (db.query(A).filter(A.organization_id == org_id, A.employee_id == emp.id, A.status == "ACTIVE",
                                  A.effective_from <= on,
                                  (A.effective_to.is_(None)) | (A.effective_to >= on)).first())
    items.append(item("br_alimony", "Deductions", "Alimony order in force", PASS if alimony else NOT_STARTED,
                      f"order {alimony.order_reference}" if alimony is not None else "no active alimony order", ["G5"]))

    for key, group, label, phase in (
        ("br_engine", "Calculation", "Certified Brazil engine (INSS / IRRF / FGTS)", "5/6"),
        ("br_esocial", "Filing", "eSocial S-1200 / S-1005 transmission", "9"),
        ("br_payment", "Payment", "PIX / CNAB settlement files", "11"),
    ):
        items.append(item(key, group, label, BLOCKED, f"BLOCKED — built in Phase {phase}", ["G6"]))
    return {"employeeId": emp.id, "on": on.isoformat(), "items": items, "liveEligible": False}
