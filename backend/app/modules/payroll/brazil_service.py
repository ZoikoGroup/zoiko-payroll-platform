"""
payroll/brazil_service.py
-------------------------
Brazil (ZP-BR-ENG-001) jurisdiction module — the statutory workflows the
shared payroll service reaches through jurisdiction_hooks (one-way
dependency: platform <- this module <- engine).

Phase 0 (scaffolding): every hook exists and fails CLOSED for Brazil only —
pack / template activation and the registry's move to AVAILABLE are refused,
calculation inputs and run approval BLOCK, a Brazilian statutory profile
cannot be saved through the shared profile editor. Hooks the shared service
reaches for every jurisdiction module (retention_settings via
retention_service._report_country) return an inert, valid answer instead of
raising, so no other country is affected.

Each hook is replaced by its real implementation in the phase that builds it
(see docs/brazil/BRAZIL_IMPLEMENTATION_PLAN.md).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.modules.payroll import retention_service, service
from app.modules.payroll.engine.countries.brazil_content import (
    BRAZIL_EFFECTIVE_DATE, GATES, SPEC, STANDARD_SYSTEM_RUBRICS,
)
from app.modules.payroll.engine.countries.brazil import ENGINE_VERSION, BRBlock
from app.modules.payroll.models import (
    PayrollBrRubric, PayrollBrStatutoryProfile, PayrollEmployee, PayrollRun, PayrollStatus, PayslipItem,
)

BR = "BR"
_NOT_BUILT = "not built yet (ZP-BR-ENG-001 Phase 0 scaffolding)"


def _employee(db: Session, employee_id: int, organization_id: int) -> PayrollEmployee:
    employee = service.get_employee_by_id(db, employee_id, organization_id)  # 404s outside the tenant
    if service._normalize_country(employee.country_code or "") != BR:
        raise BadRequestException(f"employee #{employee_id} is not a Brazil employee")
    return employee


# ---- Readiness (spec §24) ----

def gate_states(db: Session) -> list:
    """G1–G8. Nothing is evidenced at Phase 0, so every gate is OPEN; gate
    evidence review arrives with Phase 11."""
    return [{"gate": key, "label": label, "state": "OPEN"} for key, label in GATES]


def statutory_summary(db: Session) -> dict:
    return {"jurisdiction": BR, "spec": SPEC, "available": False, "engineVersion": ENGINE_VERSION,
            "phase": 0, "gates": gate_states(db),
            "note": "Live Brazilian payroll stays gated until G1–G8 are signed (ZP-BR-ENG-001 §24); "
                    "the Brazil engine is not certified yet, so every Brazilian calculation is BLOCKED."}


# ---- Governance hooks ----

def transition_br_service_registry(db: Session, target: str, reason: str, actor_id: Optional[int] = None,
                                   as_of: Optional[date] = None):
    """PLANNED <-> AVAILABLE. AVAILABLE is refused until every gate G1–G8 is
    signed (spec §24: approval of the build is not approval of live payroll)."""
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
    """No Brazilian statutory pack can become Active before its content, source
    evidence and golden vectors exist (BR-003, BR-004)."""
    return (f"Brazil pack activation is refused: the Brazil statutory content and golden vectors are {_NOT_BUILT}. "
            "No Brazilian pack can be activated until its evidence (G1–G8) is in place.")


def statutory_editors(db: Session, pack) -> set:
    return set()


def template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    return f"Brazil report-template activation is refused: Brazil report templates are {_NOT_BUILT}."


# ---- Calculation and run hooks ----

def calc_inputs(db: Session, run: Optional[PayrollRun], employee: PayrollEmployee,
                resolved_pack=None, as_of: Optional[date] = None) -> dict:
    raise BRBlock("BR_ENGINE_NOT_CERTIFIED",
                  f"Brazil calculation inputs are {_NOT_BUILT}; no Brazilian payroll is calculated until then",
                  getattr(employee, "organization_id", None))


def _br_before_run_transition(db: Session, run: PayrollRun, next_status, actor_id) -> None:
    """Reached only for a run with Brazilian payslips (service.advance_payroll_
    run_status). None can be approved, authorized or paid before Phase 6
    (approval fingerprint); moving back (Draft / Review) is not blocked."""
    if next_status in (PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        raise BRBlock("BR_RUN_NOT_SUPPORTED",
                      f"Brazil payroll-run approval is {_NOT_BUILT}; a run with Brazilian payslips cannot be "
                      f"{getattr(next_status, 'value', next_status)}",
                      getattr(run, "organization_id", None))


def payment_treatment(db: Session, organization_id: int, run: PayrollRun, items: list) -> dict:
    """No BR payment hold at this phase (PIX / CNAB settlement is Phase 11)."""
    return {}


def _br_pack_holidays(db: Session, year: int) -> list:
    """Brazilian national holidays are not seeded from a reviewed source yet —
    none is invented here."""
    return []


def _br_statutory_profile_errors(data) -> list:
    return [f"Brazil statutory profiles are {_NOT_BUILT} (Phase 4); no Brazilian profile can be saved yet."]


def _br_profile_values(db: Session, employee, data, previous) -> dict:
    return {}


def _br_payslip_hold_view(item: PayslipItem) -> Optional[dict]:
    return None


# ---- Rubric catalogue ----
# Moved here from the removed modules/payroll/brazil_content.py so the content
# module stays pure data. Not called by any route yet: organisation rubric
# adoption is Phase 3, and the codes themselves are unverified (BR-K3, D6).

def seed_brazil_statutory_content(db: Session, organization_id: int) -> int:
    """Idempotently seed the standard eSocial Table 03 rubrics for one
    organisation (by rubric_code; an existing code is never changed).
    Returns the number of rubrics created."""
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
# retention_service._report_country asks EVERY jurisdiction module for its
# settings on each report download, so this must answer (never raise). No
# record category and no owner decision exist yet: retention stays
# BLOCKED_UNDECIDED for Brazil (LGPD retention is decided in Phase 11), and
# only Brazil's own reports match.

def _decision_state(db: Session, key: str) -> str:
    return "OPEN"


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return db.query(PayrollBrStatutoryProfile.id).filter(
        PayrollBrStatutoryProfile.employee_id == employee_id).first() is not None


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
