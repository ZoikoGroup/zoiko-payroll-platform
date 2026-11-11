"""
payroll/belgium_service.py
--------------------------
Belgium (ZP-BE-ENG-001) jurisdiction statutory module — Phase 1 fail-closed
scaffold, registered in jurisdiction_hooks._MODULES with all 13 hooks.

Nothing Belgian can be calculated, approved, paid, activated or opened yet.
Each hook follows how the platform calls it (Phase 1 hook caller table):

* Hooks called only for something whose country is BE (type a) fail closed:
  they raise a clear Belgium-blocked error or return a refusal.
* retention_settings is ALSO called for every registered country on every
  report download (retention_service._report_country, type b), so it never
  raises there: it returns an inert settings object that matches only Belgian
  reports, has no record categories and keeps every decision OPEN, so nothing
  is purged. Deleting a Belgian employee is refused while the Belgian retention
  decisions are OPEN (gap G-21) — enforced inside retained_record_label, which
  only the deletion check (retention_service.assert_employee_deletable) calls.
* pack_holidays returns [] (no guessed dates), statutory_summary reports
  NOT_BUILT, payslip_hold_view returns None (read-only display).

No statutory value lives here. No NISS/INSZ is read, logged or returned.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

BE = "BE"
SPEC = "ZP-BE-ENG-001 v1.0"

NOT_BUILT_MESSAGE = ("Belgian payroll is not built yet (ZP-BE-ENG-001); it stays disabled until the Belgium "
                     "release gates G1-G7 are signed.")
RELEASE_GATES_UNMET = "Belgium release gates G1–G7 not met"
DELETION_REFUSED_MESSAGE = ("Belgium: employee records cannot be deleted until Belgian statutory retention rules "
                            "are approved (spec §15).")
RETENTION_PERIOD_DECISION = "BE-G21-RETENTION"


def _conflict(detail: str):
    from fastapi import HTTPException, status as http_status

    return HTTPException(http_status.HTTP_409_CONFLICT, detail=detail)


def _run_has_belgian_items(db: Session, run) -> bool:
    from app.modules.payroll.models import PayslipItem

    return db.query(PayslipItem.id).filter(PayslipItem.payroll_run_id == run.id,
                                           PayslipItem.country_code == BE).first() is not None


# ── 1. calc_inputs (type a; no BE caller before Phase 5) ────────────────────
def calc_inputs(db: Session, run=None, employee=None, resolved_pack=None, as_of=None, period=None, **_kwargs) -> dict:
    from app.modules.payroll.engine.jurisdictions.belgium import errors as E

    raise E.BECalculationBlockedError(E.ENGINE_NOT_BUILT, NOT_BUILT_MESSAGE,
                                      organization_id=getattr(employee, "organization_id", None))


# ── 2. before_run_transition (loop, but only for runs with BE payslips) ─────
def before_run_transition(db: Session, run, next_status, actor_id) -> None:
    if not _run_has_belgian_items(db, run):
        return
    raise _conflict(f"Belgium: the run cannot move to {getattr(next_status, 'value', next_status)} — "
                    + NOT_BUILT_MESSAGE)


# ── 3./4. shared statutory profile (type a) ─────────────────────────────────
def _be_statutory_profile_errors(data) -> list:
    # Belgian statutory facts (worker category, Joint Committee, tax status,
    # NISS/INSZ in the vault) live in the effective-dated payroll_be_* records
    # (Phase 4), never on the shared statutory profile.
    return ["Belgian statutory facts are not held on the shared statutory profile; the Belgian worker profile "
            "arrives with ZP-BE-ENG-001 Phase 4."]


def _be_profile_values(db: Session, employee, data, previous) -> dict:
    # Unreachable after _be_statutory_profile_errors refuses; a backstop.
    raise BadRequestException("Belgium: the shared statutory profile is refused for Belgian employees.")


# ── 5. pack_activation_refusal (type a) ─────────────────────────────────────
def _be_pack_activation_refusal(db: Session, pack, actor_id=None) -> Optional[str]:
    return ("Belgium packs cannot be activated: the Belgian engine and governed content console are not built "
            "and the release gates G1-G7 are not signed (ZP-BE-ENG-001).")


# ── 6. retention_settings (type b + a) ──────────────────────────────────────
BE_RETENTION_CATEGORIES: tuple = ()      # none declared until G-21 is decided


def _decision_state(db: Session, key: str) -> str:
    return "OPEN"                         # G-21: no approved Belgian retention rule exists


def _retention_employee(db: Session, employee_id: int, organization_id: int) -> None:
    from app.core.authz.scopes import organization_scoped
    from app.modules.payroll.models import PayrollEmployee

    employee = (organization_scoped(db, PayrollEmployee, organization_id)
                .filter(PayrollEmployee.id == employee_id).first())
    if employee is None or (getattr(employee, "country_code", None) or "").upper() != BE:
        raise NotFoundException("Belgian employee")


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    """Called only by retention_service.assert_employee_deletable. While the
    Belgian retention decision is OPEN (G-21), deletion is refused outright."""
    if _decision_state(db, RETENTION_PERIOD_DECISION) != "RECORDED":
        raise _conflict(DELETION_REFUSED_MESSAGE)
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return False


def _is_report(report) -> bool:
    if report is None:
        return False
    country = (getattr(report, "jurisdiction_country", None) or "").upper()
    report_type = str(getattr(report, "report_type", "") or "").upper()
    return country == BE or report_type.startswith("BE_")


def _be_retention_settings():
    # The platform calls this hook with NO arguments (retention_service.settings),
    # including once per registered country on every report download: never raise.
    from app.modules.payroll.retention_service import RetentionJurisdiction

    return RetentionJurisdiction(
        country=BE, label="Belgium", categories=BE_RETENTION_CATEGORIES,
        period_decision=RETENTION_PERIOD_DECISION, end_decision=RETENTION_PERIOD_DECISION,
        decision_reference="BE-RETENTION-G21", decision_state=_decision_state,
        validate_employee=_retention_employee, retained_record_label=_retained_record_label,
        has_statutory_profile=_has_statutory_profile, report_matches=_is_report, audit_spec=SPEC)


# ── 7. service_registry_transition (type a) ─────────────────────────────────
def be_unmet_requirements(db: Session) -> list:
    """Phase 1: the release gates are never met (readiness arrives in Phase 10)."""
    return [{"key": "BE_RELEASE_GATES_G1_G7", "label": RELEASE_GATES_UNMET,
             "detail": "ZP-BE-ENG-001 §17; the Belgian engine is not built"}]


def _be_service_registry_transition(db: Session, target: str, reason: str, actor_id=None, as_of=None):
    from app.modules.payroll import service

    def readiness():
        return be_unmet_requirements(db), {}

    return service.transition_service_registry(
        db, BE, target, reason, actor_id, label="Belgium", readiness=readiness,
        invalid_target_message=lambda t: (f"Belgium availability can only be {service.SERVICE_REGISTRY_OPEN} "
                                          f"or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no Belgium registry row - seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Belgium is {a}; only PLANNED moves to AVAILABLE.")


def ensure_be_service_registry_row(db: Session) -> str:
    """Belgium's jurisdiction_service_registry row, PLANNED, created only when
    missing — an existing row is never changed."""
    from app.modules.billing.models import JurisdictionServiceRegistry

    existing = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == BE).first()
    if existing is not None:
        return existing.availability
    db.add(JurisdictionServiceRegistry(country=BE, availability="PLANNED",
                                       payment_execution_responsibility="NOT_OFFERED",
                                       filing_responsibility="NOT_OFFERED", remittance_responsibility="NOT_OFFERED"))
    db.flush()
    return "PLANNED"


# ── 8. statutory_summary (type a; read-only status) ─────────────────────────
def statutory_summary(db: Session) -> dict:
    return {"country": BE, "status": "NOT_BUILT"}


# ── 9. statutory_editors (type a) ───────────────────────────────────────────
def _be_statutory_editors(db: Session, pack) -> set:
    # An empty set would let anyone approve a Belgian pack: refuse instead.
    raise BadRequestException("Belgium pack approval is refused: the governed Belgium content console "
                              "(ZP-BE-ENG-001 Phase 3) does not exist yet.")


# ── 10. template_activation_refusal (type a) ────────────────────────────────
def _be_template_activation_refusal(db: Session, template, actor_id=None) -> Optional[str]:
    return ("Belgium form templates (Dimona, DmfA, 281.10, payslip) stay inactive until the authority schemas are "
            "archived and the filing path is certified (gate G3).")


# ── 11. pack_holidays (type a) ──────────────────────────────────────────────
def _be_pack_holidays(db: Session, year: int) -> list:
    # Belgian public holidays and substitute days arrive as signed content
    # (Phase 6, D15); nothing is seeded from a guessed list.
    return []


# ── 12. payment_treatment (loop, but only for runs with BE items) ───────────
def _be_payment_treatment(db: Session, organization_id: int, run, items: list) -> dict:
    if not any((getattr(i, "country_code", None) or "").upper() == BE for i in items):
        return {}
    raise _conflict("Belgium: no payment file can include Belgian payslips — " + NOT_BUILT_MESSAGE)


# ── 13. payslip_hold_view (type a; read-only display) ───────────────────────
def _be_payslip_hold_view(item) -> Optional[dict]:
    return None


JURISDICTION_HOOKS = {
    "calc_inputs": "calc_inputs",
    "before_run_transition": "before_run_transition",
    "statutory_profile_errors": "_be_statutory_profile_errors",
    "statutory_profile_values": "_be_profile_values",
    "pack_activation_refusal": "_be_pack_activation_refusal",
    "retention_settings": "_be_retention_settings",
    "service_registry_transition": "_be_service_registry_transition",
    "statutory_summary": "statutory_summary",
    "statutory_editors": "_be_statutory_editors",
    "template_activation_refusal": "_be_template_activation_refusal",
    "pack_holidays": "_be_pack_holidays",
    "payment_treatment": "_be_payment_treatment",
    "payslip_hold_view": "_be_payslip_hold_view",
}
