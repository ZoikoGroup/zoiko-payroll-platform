"""
payroll/mexico_service.py
-------------------------
Mexico (ZP-MX-ENG-001) jurisdiction module — the statutory workflows the
shared payroll service reaches through jurisdiction_hooks (one-way
dependency: platform <- this module <- engine).

Phase 0 (scaffolding): every hook exists and fails CLOSED for Mexico only —
pack / template activation and the registry's move to AVAILABLE are refused,
calculation inputs and run approval BLOCK, a Mexican statutory profile cannot
be saved. Hooks the shared service reaches for every jurisdiction module
(retention_settings via retention_service._report_country) return an inert,
valid answer instead of raising, so no other country is affected.

Each hook is replaced by its real implementation in the phase that builds it
(see docs/mexico/MEXICO_IMPLEMENTATION_PLAN.md).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.modules.payroll import retention_service, service
from app.modules.payroll.engine.countries.mexico import ENGINE_VERSION, MXBlock
from app.modules.payroll.engine.countries.mexico_content import GATES, SPEC
from app.modules.payroll.models import (
    EmployeeStatutoryProfile, PayrollEmployee, PayrollRun, PayrollStatus, PayslipItem,
)

MX = "MX"
_NOT_BUILT = "not built yet (ZP-MX-ENG-001 Phase 0 scaffolding)"


def _employee(db: Session, employee_id: int, organization_id: int) -> PayrollEmployee:
    employee = service.get_employee_by_id(db, employee_id, organization_id)  # 404s outside the tenant
    if service._normalize_country(employee.country_code or "") != MX:
        raise BadRequestException(f"employee #{employee_id} is not a Mexico employee")
    return employee


# ---- Readiness (spec §22) ----

def gate_states(db: Session) -> list:
    """G1–G8. Nothing is evidenced at Phase 0, so every gate is OPEN; gate
    evidence review arrives with Phase 10."""
    return [{"gate": key, "label": label, "state": "OPEN"} for key, label in GATES]


def statutory_summary(db: Session) -> dict:
    return {"jurisdiction": MX, "spec": SPEC, "available": False, "engineVersion": ENGINE_VERSION,
            "phase": 0, "gates": gate_states(db),
            "note": "Live Mexican payroll stays gated until G1–G8 are signed (ZP-MX-ENG-001 §22); "
                    "the Mexico engine is not built yet, so every Mexican calculation is BLOCKED."}


# ---- Governance hooks ----

def transition_mx_service_registry(db: Session, target: str, reason: str, actor_id: Optional[int] = None,
                                   as_of: Optional[date] = None):
    """PLANNED <-> AVAILABLE. AVAILABLE is refused until every gate G1–G8 is
    signed (spec §22: approval of the build is not approval of live payroll)."""
    def readiness():
        unmet = [{"key": f"mx_gate_{g['gate'].lower()}", "label": f"Gate {g['gate']} — {g['label']}",
                  "detail": f"gate {g['gate']} is {g['state']}", "met": False}
                 for g in gate_states(db) if g["state"] != "SIGNED"]
        return unmet, {u["key"]: u["detail"] for u in unmet}

    return service.transition_service_registry(
        db, MX, target, reason, actor_id, label="Mexico", readiness=readiness,
        invalid_target_message=lambda t: (
            f"Mexico availability can only be {service.SERVICE_REGISTRY_OPEN} or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no Mexico registry row — seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Mexico is {a}; only PLANNED moves to AVAILABLE.")


def mx_activation_evidence_refusal(db: Session, pack) -> Optional[str]:
    """No Mexican statutory pack can become Active before its content, source
    evidence and golden vectors exist (MX-003, MX-064)."""
    return (f"Mexico pack activation is refused: the Mexico statutory content and golden vectors are {_NOT_BUILT}. "
            "No Mexican pack can be activated until its evidence (G1–G8) is in place.")


def statutory_editors(db: Session, pack) -> set:
    return set()


def template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    return (f"Mexico report-template activation is refused: Mexico report templates are {_NOT_BUILT}.")


# ---- Calculation and run hooks ----

def calc_inputs(db: Session, run: Optional[PayrollRun], employee: PayrollEmployee,
                resolved_pack=None, as_of: Optional[date] = None) -> dict:
    raise MXBlock("MX_ENGINE_NOT_IMPLEMENTED",
                  f"Mexico calculation inputs are {_NOT_BUILT}; no Mexican payroll is calculated until then",
                  getattr(employee, "organization_id", None))


def _mx_before_run_transition(db: Session, run: PayrollRun, next_status, actor_id) -> None:
    """Reached only for a run with Mexican payslips (service.advance_payroll_run_
    status). None can be approved, authorized or paid before Phase 6 (approval
    fingerprint, MX-040); moving back (Draft / Review) is not blocked."""
    if next_status in (PayrollStatus.APPROVED, PayrollStatus.AUTHORIZED, PayrollStatus.PAID):
        raise MXBlock("MX_RUN_NOT_SUPPORTED",
                      f"Mexico payroll-run approval is {_NOT_BUILT}; a run with Mexican payslips cannot be "
                      f"{getattr(next_status, 'value', next_status)}",
                      getattr(run, "organization_id", None))


def payment_treatment(db: Session, organization_id: int, run: PayrollRun, items: list) -> dict:
    """No MX payment hold at this phase (bank settlement lifecycle is Phase 10)."""
    return {}


def _mx_pack_holidays(db: Session, year: int) -> list:
    """Mexican mandatory rest days are not seeded from a reviewed source yet —
    none is invented here."""
    return []


def _mx_statutory_profile_errors(data) -> list:
    return [f"Mexico statutory profiles are {_NOT_BUILT} (Phase 4); no Mexican profile can be saved yet."]


def _mx_profile_values(db: Session, employee, data, previous) -> dict:
    return {}


def _mx_payslip_hold_view(item: PayslipItem) -> Optional[dict]:
    return None


# ---- Records governance (retention_service) ----
# retention_service._report_country asks EVERY jurisdiction module for its
# settings on each report download, so this must answer (never raise). No
# record category and no owner decision exist yet: retention stays
# BLOCKED_UNDECIDED for Mexico, and only Mexico's own reports match.

def _decision_state(db: Session, key: str) -> str:
    return "OPEN"


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return db.query(EmployeeStatutoryProfile.id).filter(EmployeeStatutoryProfile.employee_id == employee_id,
                                                        EmployeeStatutoryProfile.country_code == MX).first() is not None


def is_mx_report(report) -> bool:
    return bool(report is not None and (str(getattr(report, "jurisdiction_country", "") or "").upper() == MX
                                        or str(getattr(report, "report_type", "") or "").startswith("MX_")))


def retention_settings() -> "retention_service.RetentionJurisdiction":
    return retention_service.RetentionJurisdiction(
        country=MX, label="Mexico", categories=(),
        period_decision="MX-D-RETENTION-PERIOD", end_decision="MX-D-RETENTION-END",
        decision_reference="MX-DECISION-RETENTION", decision_state=_decision_state,
        validate_employee=lambda db, employee_id, organization_id: _employee(db, employee_id, organization_id),
        retained_record_label=_retained_record_label, has_statutory_profile=_has_statutory_profile,
        report_matches=is_mx_report, audit_spec=SPEC)


JURISDICTION_HOOKS = {
    "retention_settings": "retention_settings",
    "service_registry_transition": "transition_mx_service_registry",
    "statutory_summary": "statutory_summary",
    "pack_activation_refusal": "mx_activation_evidence_refusal",
    "statutory_editors": "statutory_editors",
    "template_activation_refusal": "template_activation_refusal",
    "calc_inputs": "calc_inputs",
    "payment_treatment": "payment_treatment",
    "before_run_transition": "_mx_before_run_transition",
    "pack_holidays": "_mx_pack_holidays",
    "statutory_profile_errors": "_mx_statutory_profile_errors",
    "statutory_profile_values": "_mx_profile_values",
    "payslip_hold_view": "_mx_payslip_hold_view",
}
