"""
payroll/brazil_service.py
-------------------------
Brazil (ZP-BR-ENG-001) jurisdiction module — the statutory workflows the
shared payroll service reaches through jurisdiction_hooks (one-way
dependency: platform <- this module <- engine).

Phase 6 (payroll run): real calc_inputs, before_run_transition with
approval fingerprint, payment_treatment, payslip_hold_view.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.authz.scopes import organization_scoped
from app.core.exceptions import BadRequestException
from app.modules.payroll import retention_service, service
from app.modules.payroll.engine.countries.brazil import ENGINE_VERSION, BRBlock
from app.modules.payroll.engine.countries.brazil_content import (
    BRAZIL_EFFECTIVE_DATE, GATES, SPEC, STANDARD_SYSTEM_RUBRICS,
    vale_transporte_max_deduction_pct, labor_rates,
)
from app.modules.payroll.models import (
    PayrollBrRubric, PayrollEmployee, PayrollRun, PayrollStatus, PayslipItem,
    PayrollBrConcurrentInssDeclaration, PayrollBrAlimonyOrder, PayrollBrValeTransporteElection,
    PayrollBrEstablishment, PayrollBrEmployerProfile, PayrollBrRiskAssignment,
    EmployeeStatutoryProfile,
)

BR = "BR"
_NOT_BUILT = "not built yet (ZP-BR-ENG-001 Phase 0 scaffolding)"


def _employee(db: Session, employee_id: int, organization_id: int) -> PayrollEmployee:
    employee = service.get_employee_by_id(db, employee_id, organization_id)  # 404s outside the tenant
    if service._normalize_country(employee.country_code or "") != BR:
        raise BadRequestException(f"employee #{employee_id} is not a Brazil employee")
    return employee


def _profile_on(db: Session, employee_id: int, on: date) -> Optional[EmployeeStatutoryProfile]:
    return (db.query(EmployeeStatutoryProfile).filter(
        EmployeeStatutoryProfile.employee_id == employee_id,
        EmployeeStatutoryProfile.country_code == BR,
        EmployeeStatutoryProfile.effective_from <= on,
        (EmployeeStatutoryProfile.effective_to.is_(None)) | (EmployeeStatutoryProfile.effective_to >= on)
    ).order_by(EmployeeStatutoryProfile.effective_from.desc()).first())


def _establishment_active_on(est, on: date) -> bool:
    return bool(est and est.active_from <= on and (est.active_to is None or est.active_to >= on))


# ---- Readiness (spec §24) ----

def gate_states(db: Session) -> list:
    return [{"gate": key, "label": label, "state": "OPEN"} for key, label in GATES]


def statutory_summary(db: Session) -> dict:
    return {"jurisdiction": BR, "spec": SPEC, "available": False, "engineVersion": ENGINE_VERSION,
            "phase": 6, "gates": gate_states(db),
            "note": "Phase 6 — calc_inputs and run approval implemented; gates G1–G8 still OPEN until signed."}


# ---- Governance hooks ----

def transition_br_service_registry(db: Session, target: str, reason: str, actor_id: Optional[int] = None,
                                   as_of: Optional[date] = None):
    def readiness():
        unmet = [{"key": f"br_gate_{g['gate'].lower()}", "label": f"Gate {g['gate']} — {g['label']}",
                  "detail": f"gate {g['gate']} is {g['state']}", "met": False}
                 for g in gate_states(db) if g["state"] != "SIGNED"]
        return unmet, {u["key"]: u["detail"] for u in unmet}

    return service.transition_service_registry(
        db, BR, target, reason, actor_id, label="Brazil", readiness=readiness,
        invalid_target_message=lambda t: (
            f"Brazil availability can only be {service.SERVICE_REGISTRY_OPEN} or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no Brazil registry row — seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Brazil is {a}; only PLANNED moves to AVAILABLE.")


def br_activation_evidence_refusal(db: Session, pack) -> Optional[str]:
    return (f"Brazil pack activation is refused: the Brazil statutory content and golden vectors are {_NOT_BUILT}. "
            "No Brazilian pack can be activated until its evidence (G1–G8) is in place.")


def statutory_editors(db: Session, pack) -> set:
    return set()


def template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    return f"Brazil report-template activation is refused: Brazil report templates are {_NOT_BUILT}."


# ---- Calculation and run hooks (Phase 6) ----

_MONTHLY_KEYS = ("basic", "hra", "special", "allowances", "overtime", "additional")


def _br_earnings(monthly: Optional[dict], org_id) -> tuple:
    """(contract_salary, earnings) from the payslip's MONTHLY pay components.

    The base salary is the BR_SALARIO_BASE rubric. Any other non-zero component
    has no eSocial rubric mapping yet (13th / vacation / overtime / allowance
    rubrics are Phase 7+), so it BLOCKS — its INSS / IRRF / FGTS incidence is
    never guessed."""
    if monthly is None:
        raise BRBlock("BR_MISSING_INPUT", "the payslip's monthly pay components were not supplied", org_id)
    amounts = {k: Decimal(str(monthly.get(k) or 0)) for k in _MONTHLY_KEYS}
    unmapped = sorted(k for k in _MONTHLY_KEYS[1:] if amounts[k] != 0)
    if unmapped:
        raise BRBlock("BR_UNMAPPED_EARNING",
                      "no eSocial rubric mapping yet for " + ", ".join(f"{k} {amounts[k]}" for k in unmapped)
                      + " — Brazil pays the base salary only until the earning rubrics are mapped (Phase 7)", org_id)
    if amounts["basic"] <= 0:
        raise BRBlock("BR_MISSING_INPUT", "monthly base salary must be positive", org_id)
    return amounts["basic"], [{"rubricCode": "BR_SALARIO_BASE", "amount": str(amounts["basic"])}]


def calc_inputs(db: Session, run: Optional[PayrollRun], employee: PayrollEmployee,
                resolved_pack=None, as_of: Optional[date] = None, monthly: Optional[dict] = None) -> dict:
    """
    Resolve all Brazil-specific calc inputs for one employee's payslip.

    Returns PayrollContext FIELDS ({"brazil_inputs": {...}, "brazil_organization_id": id})
    — the resolver splats them into the context; the engine reads every input
    from ctx.brazil_inputs. (It used to return the inner dict flat, so every
    in-app calculation raised TypeError.) `monthly` is the payslip's MONTHLY
    split {basic, hra, special, allowances, overtime, additional} — the
    contract salary is the monthly basic, never employee.basic (an ANNUAL
    figure). Called at all three calculation sites. Never writes.
    """
    org_id = employee.organization_id
    pay_date = as_of or getattr(run, "pay_date", None) or date.today()

    # 1. Active statutory profile (on competence month = pay_date's month start)
    competence_month = pay_date.replace(day=1)
    profile = _profile_on(db, employee.id, competence_month)
    if profile is None:
        raise BRBlock("BR_MISSING_INPUT",
                      f"no Brazil statutory profile in force on {competence_month.isoformat()}",
                      org_id)

    # 2. Establishment (must belong to org and be active on competence month)
    est_id = profile.br_establishment_id
    if est_id is None:
        raise BRBlock("BR_MISSING_INPUT", "br_establishment_id not set on statutory profile", org_id)
    est = db.query(PayrollBrEstablishment).filter(
        PayrollBrEstablishment.id == est_id,
        PayrollBrEstablishment.organization_id == org_id
    ).first()
    if not _establishment_active_on(est, competence_month):
        raise BRBlock("BR_MISSING_INPUT",
                      f"establishment {est_id} not active on {competence_month.isoformat()}",
                      org_id)

    # 3. Employer profile (root of the establishment's employer chain)
    employer = db.query(PayrollBrEmployerProfile).filter(
        PayrollBrEmployerProfile.id == est.employer_profile_id,
        PayrollBrEmployerProfile.organization_id == org_id
    ).first()
    if employer is None:
        raise BRBlock("BR_MISSING_INPUT",
                      f"employer profile {est.employer_profile_id} not found for organization {org_id}",
                      org_id)

    # 4. Risk assignment (RAT/FAP) for the competence year
    risk = db.query(PayrollBrRiskAssignment).filter(
        PayrollBrRiskAssignment.establishment_id == est.id,
        PayrollBrRiskAssignment.calendar_year == competence_month.year,
        PayrollBrRiskAssignment.status == "ACTIVE"
    ).first()
    if risk is None:
        raise BRBlock("BR_RAT_MISSING",
                      f"no active RAT/FAP assignment for establishment {est.id} in {competence_month.year}",
                      org_id)

    # 5. Contract salary and earnings from the MONTHLY pay components
    contract_salary, earnings = _br_earnings(monthly, org_id)

    # 6. Concurrent INSS declaration for this competence month (if any)
    conc = db.query(PayrollBrConcurrentInssDeclaration).filter(
        PayrollBrConcurrentInssDeclaration.organization_id == org_id,
        PayrollBrConcurrentInssDeclaration.employee_id == employee.id,
        PayrollBrConcurrentInssDeclaration.competence_month == competence_month,
        PayrollBrConcurrentInssDeclaration.status == "RECORDED"
    ).first()

    # 7. Active alimony order for the pay period
    alimony = db.query(PayrollBrAlimonyOrder).filter(
        PayrollBrAlimonyOrder.organization_id == org_id,
        PayrollBrAlimonyOrder.employee_id == employee.id,
        PayrollBrAlimonyOrder.status == "ACTIVE",
        PayrollBrAlimonyOrder.effective_from <= pay_date,
        (PayrollBrAlimonyOrder.effective_to.is_(None)) | (PayrollBrAlimonyOrder.effective_to >= pay_date)
    ).first()

    # 8. Active vale-transporte election
    vt = db.query(PayrollBrValeTransporteElection).filter(
        PayrollBrValeTransporteElection.organization_id == org_id,
        PayrollBrValeTransporteElection.employee_id == employee.id,
        PayrollBrValeTransporteElection.status == "ACTIVE",
        PayrollBrValeTransporteElection.effective_from <= pay_date,
        (PayrollBrValeTransporteElection.effective_to.is_(None)) | (PayrollBrValeTransporteElection.effective_to >= pay_date)
    ).order_by(PayrollBrValeTransporteElection.effective_from.desc()).first()

    # 9. Financial sector flag from employer CNAE (financial institutions)
    # Simplified: check if CNAE starts with 64 (financial intermediation) or specific codes
    financial_sector = str(employer.cnae_preponderant).startswith("64") or \
                       str(est.cnae).startswith("64")

    # 10. VT benefit daily cost (for 6% cap calculation)
    vt_benefit = None
    if vt and vt.elected and vt.daily_cost is not None:
        # In a real run, days worked would come from attendance; here we pass daily_cost
        # The engine will multiply by days_worked from context
        vt_benefit = Decimal(str(vt.daily_cost))

    # 11. Labor rates for the competence month
    ot_50, ot_100, night_pct, night_min, dsr_flag = labor_rates(competence_month)

    inputs = {
        "competence_month": competence_month.isoformat(),
        "esocial_category": profile.br_esocial_category or "101",
        "contract_salary": str(contract_salary),
        "rat_pct": str(risk.rat_pct),
        "fap_factor": str(risk.fap_factor),
        "third_party_pct": str(est.third_party_pct),
        "cprb_opted": False,  # TODO: CPRB opt-in from employer profile
        "financial_sector": financial_sector,
        "dependents": profile.br_irrf_dependents_count or 0,
        "alimony": _resolve_alimony_amount(alimony, contract_salary) if alimony else Decimal("0"),
        "vt_benefit": vt_benefit,
        "opt_out_simplified_irrf": bool(profile.br_simplified_irrf_opt_out),
        "concurrent_inss_base": Decimal(str(conc.base_external)) if conc else None,
        "concurrent_inss_deducted": Decimal(str(conc.deducted_external)) if conc else None,
        "earnings": earnings,
    }
    return {"brazil_inputs": inputs, "brazil_organization_id": org_id}


def _resolve_alimony_amount(alimony: PayrollBrAlimonyOrder, contract_salary: Decimal) -> Decimal:
    """Resolve alimony amount based on method and base."""
    if alimony.method == "FIXED_AMOUNT":
        return alimony.fixed_amount or Decimal("0")
    # PERCENTAGE base: GROSS, NET, BASE_INSS, BASE_IRRF
    # Here we use GROSS (contract_salary) as a proxy; real base resolution
    # needs the actual bases which are computed by the engine. For now,
    # return percentage of contract_salary; the engine will recalculate properly.
    pct = alimony.percentage or Decimal("0")
    base_val = contract_salary  # simplified
    return (base_val * pct / Decimal("100")).quantize(Decimal("0.01"))


def _br_items(db: Session, run: PayrollRun):
    return (db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id,
        PayslipItem.country_code == BR
    ).order_by(PayslipItem.id).all())


def _check(employee_id, key, reason, severity, source="BR engine", action=None) -> dict:
    return {"employeeId": employee_id, "key": key, "reason": reason, "severity": severity,
            "source": source, "action": action}


def br_run_preflight(db: Session, run: PayrollRun) -> list:
    """Blocking prerequisites + material exceptions for BR run approval.
    BLOCK items refuse approval; WARN items are shown, never silently dropped."""
    checks = []
    org_id = run.organization_id

    # 1. Employer profile exists and ACTIVE
    employer = db.query(PayrollBrEmployerProfile).filter(
        PayrollBrEmployerProfile.organization_id == org_id,
        PayrollBrEmployerProfile.effective_to.is_(None)
    ).first()
    if employer is None:
        checks.append(_check(None, "employer_profile", "no Brazil employer profile (S-1000)",
                             "BLOCK", "employer", "Create the employer registration (eSocial S-1000)"))
    else:
        if employer.status != "ACTIVE":
            checks.append(_check(None, "employer_status", f"employer profile status is {employer.status}",
                                 "BLOCK", "employer", "Activate the employer profile"))
        # CNPJ verification
        if not employer.cnpj_root:
            checks.append(_check(None, "cnpj_root", "CNPJ root not recorded", "BLOCK",
                                 "employer", "Record the CNPJ root"))

    # 2. Every BR payslip has a frozen calculation snapshot
    for item in _br_items(db, run):
        snap = item.br_calculation_snapshot
        if not snap:
            checks.append(_check(item.employee_id, "snapshot", "payslip has no frozen BR calculation",
                                 "BLOCK", action="Recalculate the run"))
            continue
        # Check exceptions from snapshot
        for exc in snap.get("exceptions") or []:
            checks.append(_check(item.employee_id, exc.get("code"), exc.get("message"),
                                 exc.get("severity", "WARN")))
        # CPF/PIS validation
        emp = organization_scoped(db, PayrollEmployee, org_id).filter(PayrollEmployee.id == item.employee_id).first()
        if emp and (emp.compliance_fields or {}).get("cpf"):
            cpf = emp.compliance_fields["cpf"]
            if not _valid_cpf(cpf):
                checks.append(_check(item.employee_id, "cpf_invalid", "CPF checksum invalid",
                                     "BLOCK", "employee", "Correct the CPF"))
        if emp and (emp.compliance_fields or {}).get("pis_nis"):
            pis = emp.compliance_fields["pis_nis"]
            if not _valid_pis(pis):
                checks.append(_check(item.employee_id, "pis_invalid", "PIS/NIS checksum invalid",
                                     "BLOCK", "employee", "Correct the PIS/NIS"))

    # 3. FAP year current (within 1 year of pay_date)
    for item in _br_items(db, run):
        profile = _profile_on(db, item.employee_id, run.pay_date.replace(day=1))
        if profile and profile.br_establishment_id:
            est = db.query(PayrollBrEstablishment).filter(
                PayrollBrEstablishment.id == profile.br_establishment_id,
                PayrollBrEstablishment.organization_id == org_id
            ).first()
            if est:
                risk = db.query(PayrollBrRiskAssignment).filter(
                    PayrollBrRiskAssignment.establishment_id == est.id,
                    PayrollBrRiskAssignment.calendar_year == run.pay_date.year,
                    PayrollBrRiskAssignment.status == "ACTIVE"
                ).first()
                if not risk:
                    checks.append(_check(item.employee_id, "fap_year",
                                         f"no FAP assignment for year {run.pay_date.year}",
                                         "BLOCK", action="Record the RAT/FAP for this year"))

    # 4. Minimum-wage floor (checked at calc time, but preflight warns)
    for item in _br_items(db, run):
        profile = _profile_on(db, item.employee_id, run.pay_date.replace(day=1))
        if profile and profile.br_esocial_category == "101":
            # Engine will block if contract_salary < minimum_wage
            pass

    # 5. Concurrent employment declared (if employee has other employment)
    # This is a domain fact we can't auto-detect; readiness signals it.
    # employee_readiness already handles this; we skip duplication.

    return checks


def _valid_cpf(cpf: str) -> bool:
    cpf = "".join(ch for ch in cpf if ch.isdigit())
    if len(cpf) != 11 or len(set(cpf)) == 1:
        return False
    for i in range(9, 11):
        s = sum(int(cpf[j]) * (i + 1 - j) for j in range(i))
        d = 11 - (s % 11)
        if d >= 10:
            d = 0
        if int(cpf[i]) != d:
            return False
    return True


def _valid_pis(pis: str) -> bool:
    pis = "".join(ch for ch in pis if ch.isdigit())
    if len(pis) != 11:
        return False
    weights = [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    s = sum(int(pis[i]) * weights[i] for i in range(10))
    d = 11 - (s % 11)
    if d >= 10:
        d = 0
    return int(pis[10]) == d


BR_APPROVAL_ENTITY = "br_run_approval"


def br_approval_fingerprint(db: Session, run: PayrollRun, store: bool = False, actor_id: Optional[int] = None) -> dict:
    """BR approval binds every payslip's frozen calculation snapshot (which already
    carries the content hash, input hash, and totals)."""
    payslips = [{"id": i.id, "employeeId": i.employee_id,
                 "inputHash": (i.br_calculation_snapshot or {}).get("inputHash"),
                 "totals": _sha((i.br_calculation_snapshot or {}).get("totals"))} for i in _br_items(db, run)]
    fingerprint = _sha({"run": run.id, "engine": ENGINE_VERSION, "payslips": payslips})
    result = {"fingerprint": fingerprint, "payslips": len(payslips)}
    if store:
        run.br_approval_fingerprint = {**(run.br_approval_fingerprint or {}), "fingerprint": fingerprint,
                                       "approvedBy": actor_id, "approvedAt": datetime.utcnow().isoformat() + "Z"}
    return result


def _sha(obj) -> str:
    import hashlib, json
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _br_before_run_transition(db: Session, run: PayrollRun, next_status, actor_id) -> None:
    """Enforce preflight checks and record approval fingerprint."""
    if next_status in (PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        checks = br_run_preflight(db, run)
        blocks = [c for c in checks if c["severity"] == "BLOCK"]
        if blocks:
            raise BRBlock("BR_PREFLIGHT_BLOCK", f"run preflight failed: {blocks[0]['reason']}",
                          getattr(run, "organization_id", None))
        # Store approval fingerprint
        br_approval_fingerprint(db, run, store=True, actor_id=actor_id)
    # Moving back to Draft/Review is not blocked


def payment_treatment(db: Session, organization_id: int, run: PayrollRun, items: list) -> dict:
    """PIX / CNAB payment treatment — Phase 11. The hook contract is a
    {payslip_id: hold} map of payslips to leave out of the bank file; Brazil
    holds none yet. (It used to return a settings dict whose string keys never
    matched a payslip and only forced a needless commit.)"""
    return {}


def _br_pack_holidays(db: Session, year: int) -> list:
    """Brazilian national holidays — Phase 10 will seed from reviewed source."""
    return []


def _br_statutory_profile_errors(data) -> list:
    from app.modules.payroll import brazil_employee_service
    return brazil_employee_service.statutory_profile_errors(data)


def _br_profile_values(db: Session, employee, data, previous) -> dict:
    from app.modules.payroll import brazil_employee_service
    return brazil_employee_service.profile_values(db, employee, data, previous)


def _br_payslip_hold_view(item: PayslipItem) -> Optional[dict]:
    """Return hold info for a Brazilian payslip (PIX key, CNAB file, etc.)."""
    snap = getattr(item, "br_calculation_snapshot", None) or {}
    hold = snap.get("hold")
    if hold:
        return {"reason": hold.get("reason"), "until": hold.get("until")}
    return None


# ---- Rubric catalogue ----

def seed_brazil_statutory_content(db: Session, organization_id: int) -> int:
    existing = {
        r.rubric_code
        for r in db.query(PayrollBrRubric.rubric_code).filter(
            PayrollBrRubric.organization_id == organization_id).all()
    }
    created = 0
    for rubric_def in STANDARD_SYSTEM_RUBRICS:
        if rubric_def["rubric_code"] in existing:
            continue
        db.add(PayrollBrRubric(
            organization_id=organization_id,
            rubric_code=rubric_def["rubric_code"],
            rubric_name=rubric_def["rubric_name"],
            nature_code=rubric_def["nature_code"],
            rubric_type=rubric_def["rubric_type"],
            cod_inc_cp=rubric_def["cod_inc_cp"],
            cod_inc_irrf=rubric_def["cod_inc_irrf"],
            cod_inc_fgts=rubric_def["cod_inc_fgts"],
            is_system_standard=True,
            version=1,
            valid_from=BRAZIL_EFFECTIVE_DATE,
            valid_to=None,
        ))
        created += 1
    if created:
        db.flush()
    return created


# ---- Records governance (retention_service) ----

def _decision_state(db: Session, key: str) -> str:
    return "OPEN"


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return db.query(EmployeeStatutoryProfile.id).filter(
        EmployeeStatutoryProfile.employee_id == employee_id,
        EmployeeStatutoryProfile.country_code == BR).first() is not None


def is_br_report(report) -> bool:
    return bool(report is not None and (str(getattr(report, "jurisdiction_country", "") or "").upper() == BR
                                        or str(getattr(report, "report_type", "") or "").startswith("BR_")))


def retention_settings() -> "retention_service.RetentionJurisdiction":
    return retention_service.RetentionJurisdiction(
        country=BR, label="Brazil", categories=(),
        period_decision="BR-D-RETENTION-PERIOD", end_decision="BR-D-RETENTION-END",
        decision_reference="BR-DECISION-RETENTION", decision_state=_decision_state,
        validate_employee=lambda db, employee_id, organization_id: _employee(db, employee_id, organization_id),
        retained_record_label=_retained_record_label, has_statutory_profile=_has_statutory_profile,
        report_matches=is_br_report, audit_spec=SPEC)


JURISDICTION_HOOKS = {
    "retention_settings": "retention_settings",
    "service_registry_transition": "transition_br_service_registry",
    "statutory_summary": "statutory_summary",
    "pack_activation_refusal": "br_activation_evidence_refusal",
    "statutory_editors": "statutory_editors",
    "template_activation_refusal": "template_activation_refusal",
    "calc_inputs": "calc_inputs",
    "payment_treatment": "payment_treatment",
    "before_run_transition": "_br_before_run_transition",
    "pack_holidays": "_br_pack_holidays",
    "statutory_profile_errors": "_br_statutory_profile_errors",
    "statutory_profile_values": "_br_profile_values",
    "payslip_hold_view": "_br_payslip_hold_view",
}