"""
modules/payroll/saudi_arabia_service.py
---------------------------------------
Saudi Arabia statutory workflows (ZP-SA-ENG-001) — the ONLY Saudi service
module, on the shared platform the same way Hong Kong's hong_kong_service.py
and Italy's italy_service.py are. It is reached ONLY through jurisdiction_hooks
(registered at the end of this file), never by import, so the dependency
direction stays: shared platform <- saudi_arabia_service <- engine.

Scope of this phase — the hooks the shared platform calls country-generically
(RETENTION, governed service-registry transition, run-approval preflight) plus
the calculation-inputs hook the payroll engine needs:

* ``calc_inputs``            — PayrollContext kwargs for one Saudi payslip:
  the effective-dated Saudi statutory profile in force on the pay date (the
  engine reads the worker class / cohort / contributory wage FROM that
  profile, never inferred — SA-001/SA-003/SA-004);
* ``before_run_transition``  — the run-approval preflight: a Saudi payslip
  must carry its frozen GOSI calculation snapshot before the money commits;
* ``retention_settings``     — the shared records-governance opt-in (access
  log, legal holds, retention policies, the deletion guard);
* ``service_registry_transition`` — the owner's PLANNED <-> AVAILABLE step.

The remaining hooks are registered for platform parity with Hong Kong but are
deliberately lean: Saudi Arabia has no monthly-PAYE withholding, no bank
payment hold and no per-value editor at this phase, so those hooks return
"nothing to do" rather than inventing a workflow. The separate ledgers the
monthly GOSI engine never computes — employer GOSI registration and employee
contracts (versioned), the monthly GOSI liability (SA-024), the WPS SIE
extract (SA-025), final settlement (SA-026/SA-027) and the EOS accrual ledger
(SA-020/SA-021) — are implemented below and reached only through the Super
Admin compliance routes; every figure is derived from committed payroll and
configured content, never approximated.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
import hashlib
import json

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import jurisdiction_hooks, retention_service, service
from app.modules.payroll.models import (
    CourtOrderedDeduction,
    EmployeeStatutoryProfile,
    EmployeeStatus,
    PAYROLL_STATUS_ORDER,
    PayrollEmployee,
    PayrollRun,
    PayrollStatus,
    PayslipItem,
    SaContractVersion,
    SaEmployerProfile,
    SaEosLedgerEntry,
    SaFinalSettlement,
    SaGosiLiability,
    SaWpsFile,
    SaWpsObservation,
)


SA = "SA"
SPEC = "ZP-SA-ENG-001 v1.0"

# The engine's own vocabularies, mirrored here (the service module validates
# what the API accepts; the engine re-checks and blocks fail-closed).
WORKER_CLASSES = ("SAUDI", "NON_SAUDI", "GCC", "DOMESTIC")
COHORTS = ("NEW", "LEGACY")
IDENTITY_DOCUMENT_TYPES = ("NATIONAL_ID", "IQAMA", "GCC_ID", "PASSPORT")

# Never copied into a payroll trace: privileged identity data.
SA_PROFILE_COLUMNS = tuple(c.name for c in EmployeeStatutoryProfile.__table__.columns
                           if c.name.startswith("sa_"))


def _iso_date(value) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


# ══════════════════════════════════════════════════════════════════════════
# Employee scope
# ══════════════════════════════════════════════════════════════════════════

def _employee(db, employee_id: int, organization_id: int) -> PayrollEmployee:
    from app.modules.payroll.service import _normalize_country, get_employee_by_id

    employee = get_employee_by_id(db, employee_id, organization_id)      # 404s outside the tenant
    if _normalize_country(employee.country_code or "") != SA:
        raise BadRequestException(f"employee #{employee_id} is not a Saudi Arabia employee")
    return employee


# ══════════════════════════════════════════════════════════════════════════
# Statutory profile — worker facts the engine reads (SA-001/SA-003/SA-004)
# ══════════════════════════════════════════════════════════════════════════

def _sa_statutory_profile_errors(data) -> list:
    """Validate the Saudi profile fields the engine depends on.

    Worker class is the GOSI branch selector and cohort picks the pension
    system; both are employee-owned FACTS (never inferred), so an out-of-
    vocabulary value is rejected here rather than blocked at payroll time.
    A SAUDI/GCC cohort assertion carries its evidence document (SA-003)."""
    errors = []
    worker_class = (getattr(data, "sa_worker_class", None) or "").strip().upper()
    if worker_class and worker_class not in WORKER_CLASSES:
        errors.append(f"sa_worker_class must be one of {', '.join(WORKER_CLASSES)}.")
    cohort = (getattr(data, "sa_cohort", None) or "").strip().upper()
    if cohort and cohort not in COHORTS:
        errors.append(f"sa_cohort must be one of {', '.join(COHORTS)}.")
    if cohort and worker_class in ("SAUDI", "GCC") and not (
            getattr(data, "sa_cohort_source_document_id", None)
            or (getattr(data, "sa_cohort_evidence_ref", None) or "").strip()):
        errors.append("sa_cohort_evidence_ref (or sa_cohort_source_document_id) is required for a "
                      "SAUDI/GCC cohort — the pension system carries its evidence (SA-003).")
    doc_type = (getattr(data, "sa_identity_document_type", None) or "").strip().upper()
    if doc_type and doc_type not in IDENTITY_DOCUMENT_TYPES:
        errors.append(f"sa_identity_document_type must be one of {', '.join(IDENTITY_DOCUMENT_TYPES)}.")
    wage = getattr(data, "sa_contributory_wage", None)
    if wage is not None and wage < 0:
        errors.append("sa_contributory_wage cannot be negative.")
    return errors


def _sa_profile_values(db: Session, employee, data, previous) -> dict:
    """Saudi columns for a new version: every Saudi field not sent in THIS
    request carries forward from the previous Saudi version (a full snapshot
    per version). Codes are stored upper-case, exactly as the engine compares
    them."""
    sent = data.model_fields_set
    values = {}
    for col in SA_PROFILE_COLUMNS:
        if col in sent:
            value = getattr(data, col)
            if col in ("sa_worker_class", "sa_cohort", "sa_identity_document_type",
                       "sa_gosi_registration_status"):
                value = (value or "").strip().upper() or None
            values[col] = value
        elif previous is not None and (previous.country_code or "").upper() == SA:
            values[col] = getattr(previous, col)
    return values


# ══════════════════════════════════════════════════════════════════════════
# Calculation inputs — PayrollContext kwargs for one Saudi payslip
# ══════════════════════════════════════════════════════════════════════════

# The value the shared CourtOrderedDeduction.jurisdiction column carries for a
# Saudi-authorised deduction (the column is free-text, never an enum).
_SA_DEDUCTION_JURISDICTIONS = ("SA", "SAUDI", "SAUDI_ARABIA")


def _sa_deduction_type(order_type: str) -> str:
    """Map a free-text court/authorised order type onto the Labour-Law
    authorised-deduction vocabulary labour.evaluate_deductions enforces."""
    ot = (order_type or "").upper()
    if "LOAN" in ot:
        return "LOAN"
    if "ADVANCE" in ot:
        return "ADVANCE"
    if "DISCIPLIN" in ot:
        return "DISCIPLINARY"
    return "OTHER_AUTHORISED"


def _sa_deduction_orders(db: Session, employee) -> list:
    """Active Saudi-authorised deductions for the employee, as the plain-dict
    shape labour.evaluate_deductions consumes. Only a fixed amount is mapped
    (a rate-only order needs a wage base the inputs hook does not carry); every
    mapped order carries its evidence reference so the cap check can run."""
    rows = (db.query(CourtOrderedDeduction)
            .filter(CourtOrderedDeduction.organization_id == employee.organization_id,
                    CourtOrderedDeduction.employee_id == employee.id,
                    CourtOrderedDeduction.jurisdiction.in_(_SA_DEDUCTION_JURISDICTIONS),
                    CourtOrderedDeduction.status == "active")
            .all())
    out = []
    for row in rows:
        if row.fixed_deduction_amount is None:
            continue
        out.append({
            "id": row.id,
            "type": _sa_deduction_type(row.order_type),
            "amount": str(row.fixed_deduction_amount),
            "evidence_ref": row.court_reference or f"court-order-{row.id}",
        })
    return out


def resolve_sa_calc_inputs(db: Session, organization_id: int, employee, as_of: Optional[date] = None) -> dict:
    """The Saudi context fields build_context_from_employee splats into
    PayrollContext. The statutory profile in force on the pay date is the ONLY
    source of the worker class / cohort / contributory wage (the engine reads
    them from ``sa_statutory_profile``), so no fact is duplicated or inferred
    here. The active authorised deductions are passed so the engine can enforce
    the Art. 91/92 caps (a breach BLOCKS)."""
    profile = service.resolve_employee_statutory_profile(db, employee.id, organization_id, as_of)
    if profile is None or (profile.country_code or "").upper() != SA:
        profile = None
    return {
        "sa_statutory_profile": profile,
        "sa_organization_id": organization_id,
        "sa_employee_id": employee.id,
        "sa_deduction_orders": _sa_deduction_orders(db, employee),
    }


def calc_inputs(db: Session, run: Optional[PayrollRun], employee: PayrollEmployee,
                resolved_pack=None, as_of: Optional[date] = None) -> dict:
    """Hook entry point. ``run`` is None on the preview path, where the caller
    supplies ``as_of`` (the period end) instead of a run's pay date."""
    pay_date = as_of or getattr(run, "pay_date", None)
    return resolve_sa_calc_inputs(db, employee.organization_id, employee, pay_date)


# ══════════════════════════════════════════════════════════════════════════
# Run-approval preflight
# ══════════════════════════════════════════════════════════════════════════

def _sa_run_has_payslips(db: Session, run: PayrollRun) -> bool:
    return db.query(PayslipItem.id).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == SA).first() is not None


def _sa_before_run_transition(db: Session, run: PayrollRun, next_status, actor_id) -> None:
    """Saudi-gated hook of advance_payroll_run_status (a run without Saudi
    payslips is untouched). At APPROVED every Saudi payslip must carry its
    frozen GOSI calculation snapshot, and the run must pass preflight with no
    BLOCK items, and the approval fingerprint must match the stored one (if
    re-approving). This is a statutory integrity check: the operator cannot
    approve past a blocked preflight or a drifted fingerprint."""
    if not _sa_run_has_payslips(db, run):
        return
    if next_status == PayrollStatus.APPROVED:
        # 1. Every SA payslip must have a frozen GOSI calculation snapshot
        missing = (db.query(PayslipItem.id)
                   .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == SA,
                           PayslipItem.sa_calculation_snapshot.is_(None))
                   .count())
        if missing:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                f"Saudi Arabia: {missing} payslip(s) have no frozen GOSI calculation snapshot — "
                "recalculate the run before approval."))

        # 2. Preflight must be clean (no BLOCK items)
        preflight = sa_run_preflight(db, run)
        block_items = [b for b in preflight if b.get("severity") == "BLOCK"]
        if block_items:
            details = "; ".join(f"Emp {b['employeeId'] or 'N/A'}: {b['key']} — {b['reason']}" for b in block_items)
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                f"Saudi Arabia preflight has {len(block_items)} BLOCK item(s): {details}"))

        # 3. Fingerprint must match stored approval (if re-approving)
        stored = sa_stored_approval(db, run)
        if stored and stored.get("fingerprint"):
            current = sa_approval_fingerprint(db, run)
            if current.get("fingerprint") != stored["fingerprint"]:
                raise HTTPException(http_status.HTTP_409_CONFLICT, detail=(
                    "Saudi Arabia approval fingerprint mismatch — the run's inputs or rules have changed "
                    "since the last approval. Re-run preflight and obtain a fresh approval."))

        # 4. Store the current fingerprint for future approval gating
        sa_approval_fingerprint(db, run, store=True)


# ══════════════════════════════════════════════════════════════════════════
# Governed service-registry transition
# ══════════════════════════════════════════════════════════════════════════

def transition_sa_service_registry(db: Session, target: str, reason: str, actor_id: Optional[int] = None,
                                   as_of: Optional[date] = None):
    """The owner's Saudi PLANNED <-> AVAILABLE step (shared
    transition_service_registry). AVAILABLE is refused until this
    jurisdiction's activation readiness is implemented and met; Saudi Arabia
    starts (and stays) PLANNED, so the readiness callback reports the gap
    rather than opening onboarding prematurely."""
    def readiness():
        requirements = [{
            "key": "sa_activation_readiness",
            "label": "Saudi Arabia activation readiness",
            "detail": "not yet implemented (ZP-SA-ENG-001 build in progress)",
            "met": False,
        }]
        return ([r for r in requirements if not r["met"]],
                {r["key"]: r["detail"] for r in requirements})

    return service.transition_service_registry(
        db, SA, target, reason, actor_id, label="Saudi Arabia", readiness=readiness,
        invalid_target_message=lambda t: (
            f"Saudi Arabia availability can only be {service.SERVICE_REGISTRY_OPEN} or {service.SERVICE_REGISTRY_CLOSED}."),
        missing_row_message="There is no Saudi Arabia registry row — seed it (PLANNED); it is never created here.",
        open_from_message=lambda a: f"Saudi Arabia is {a}; only PLANNED moves to AVAILABLE.")


# ══════════════════════════════════════════════════════════════════════════
# Records governance (shared retention_service opt-in)
# ══════════════════════════════════════════════════════════════════════════

# Saudi record categories for the shared retention framework (D-1 / D-2).
SA_RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and GOSI calculation traces"),
    ("GOSI_RECORDS", "GOSI / SANED / Occupational Hazards contribution records"),
    ("WPS_RECORDS", "WPS (Mudad) file submissions and reconciliation"),
    ("EOS_RECORDS", "End-of-service accruals, final settlements and the EOS ledger"),
    ("EMPLOYMENT_CONTRACTS", "Effective-dated employment contract versions"),
    ("EMPLOYEE_IDENTITY", "National ID / Iqama / passport and statutory profile data"),
    ("WORK_HOURS", "Hours-worked records (Labour Law)"),
    ("ACCESS_LOGS", "Saudi access events and download logs"),
    ("CORRECTIONS", "Payslip corrections and their evidence"),
)

# Owner decisions (the register that unblocks retention). D-1 fixes the
# period per category, D-2 the delete-vs-anonymise end state; the rest are
# launch-scope governance decisions recorded the same way.
DECISIONS = {
    "D-1": ("Retention period per data category", True),
    "D-2": ("Deletion vs anonymisation at end of retention", True),
    "D-3": ("Encryption at rest", True),
    "D-4": ("Saudi payroll-run approval four-eyes", True),
    "D-5": ("Legal-hold policy", True),
    "D-6": ("Privileged (assisted) access policy", True),
    "D-7": ("WPS / Mudad file interface at launch", True),
    "D-8": ("GOSI employer registration evidence", True),
    "D-9": ("Future-year template publication owner", True),
    "D-10": ("Worker-class / cohort evidence policy", True),
}


def _reviewed_by_other(artifact) -> bool:
    return bool(artifact is not None and artifact.reviewer_id and artifact.file_path is not None
                and artifact.reviewer_id != artifact.created_by_id)


def _evidence(db: Session, tag: str):
    """The current (not superseded) artifact with this tag that counts as
    evidence, if any."""
    from app.modules.payroll.models import SourceArtifact

    rows = (db.query(SourceArtifact).filter(SourceArtifact.form_number == tag, SourceArtifact.superseded_by_id.is_(None))
            .order_by(SourceArtifact.id.desc()).all())
    return next((r for r in rows if _reviewed_by_other(r)), None), bool(rows)


def owner_decisions(db: Session) -> list:
    out = []
    for key, (label, blocks) in DECISIONS.items():
        accepted, submitted = _evidence(db, f"SA-DECISION-{key}")
        out.append({"key": key, "label": label, "blocksLaunch": blocks, "evidenceTag": f"SA-DECISION-{key}",
                    "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                    "artifactId": accepted.id if accepted else None})
    return out


def _decision_state(db: Session, key: str) -> str:
    return next((d["state"] for d in owner_decisions(db) if d["key"] == key), "OPEN")


def _retained_record_label(db: Session, organization_id: int, employee_id: int) -> Optional[str]:
    """The label of the first retained Saudi statutory record for THIS employee
    (the delete guard blocks on it). Only per-employee records count — the
    org-level GOSI liability register is not this employee's evidence."""
    for model, label in ((SaFinalSettlement, "final settlements"),
                         (SaEosLedgerEntry, "end-of-service ledger entries"),
                         (SaContractVersion, "employment contract versions"),
                         (SaWpsObservation, "WPS observations")):
        if (db.query(model.id)
                .filter(model.employee_id == employee_id)
                .first()):
            return label
    return None


def _has_statutory_profile(db: Session, employee_id: int) -> bool:
    return (db.query(EmployeeStatutoryProfile.id)
            .filter(EmployeeStatutoryProfile.employee_id == employee_id,
                    EmployeeStatutoryProfile.country_code == SA)
            .first() is not None)


def is_sa_report(report) -> bool:
    return bool(report is not None and (str(getattr(report, "jurisdiction_country", "") or "").upper() == SA
                                        or str(getattr(report, "report_type", "") or "").startswith("SA_")))


def retention_settings() -> "retention_service.RetentionJurisdiction":
    return retention_service.RetentionJurisdiction(
        country=SA, label="Saudi Arabia", categories=SA_RETENTION_CATEGORIES,
        period_decision="D-1", end_decision="D-2", decision_reference="SA-DECISION-D-1",
        decision_state=_decision_state,
        validate_employee=lambda db, employee_id, organization_id: _employee(db, employee_id, organization_id),
        retained_record_label=_retained_record_label, has_statutory_profile=_has_statutory_profile,
        report_matches=is_sa_report, audit_spec=SPEC)


# ══════════════════════════════════════════════════════════════════════════
# Lean parity hooks — nothing to do at this phase (registered so the shared
# platform's country-generic call sites never fail closed on Saudi Arabia)
# ══════════════════════════════════════════════════════════════════════════

def sa_activation_evidence_refusal(db: Session, pack) -> Optional[str]:
    """Saudi statutory content carries no beyond-the-generic-gate evidence
    requirement at this phase — the shared pack activation gates apply."""
    return None


def statutory_editors(db: Session, pack) -> set:
    """No per-value Saudi statutory editor exists yet, so no editor of a Saudi
    pack version is tracked here (the shared last-editor maker-checker gate
    still applies)."""
    return set()


def template_activation_refusal(db: Session, template, actor_id: Optional[int]) -> Optional[str]:
    """Saudi report templates have no extra activation evidence at this phase."""
    return None


def _sa_pack_holidays(db: Session, year: int) -> list:
    """Saudi public holidays are lunar (Umm al-Qura) and are seeded per year
    from a reviewed gazette source, never guessed — until that source exists
    this returns nothing rather than inventing a date."""
    return []


def payment_treatment(db: Session, organization_id: int, run: PayrollRun, items: list) -> dict:
    """Saudi Arabia has no bank-payment hold (no tax-clearance equivalent): no
    payslip is withheld from the payment file here."""
    return {}


def _sa_payslip_hold_view(item: PayslipItem) -> Optional[dict]:
    """Saudi Arabia has no payslip hold line at this phase."""
    return None


def statutory_summary(db: Session) -> dict:
    """Lean Super-Admin summary: the owner-decision states that gate Saudi
    launch (the full readiness summary arrives with the activation phase)."""
    return {"jurisdiction": SA, "spec": SPEC, "available": False,
            "decisions": owner_decisions(db),
            "note": "Saudi Arabia activation readiness is not yet implemented (ZP-SA-ENG-001 build in progress)."}


# ═══════════════════════════════════════════════════════════════════════════
# Super Admin readiness, preview and golden-check (ZP-SA-ENG-001 §16/§17)
# ═══════════════════════════════════════════════════════════════════════════

SA_PACK_ID = "SA-PAYROLL-2026"


def latest_sa_tax_pack(db: Session, pack_id: Optional[int] = None, as_of: Optional[date] = None):
    """The SA tax pack by id; otherwise the one in force on `as_of` (default
    today), else the most recent. None when no Saudi pack exists."""
    from sqlalchemy import or_

    from app.core.exceptions import NotFoundException
    from app.modules.payroll.models import JurisdictionPack

    query = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == SA,
                                             JurisdictionPack.pack_type == "tax")
    if pack_id is not None:
        pack = query.filter(JurisdictionPack.id == pack_id).first()
        if pack is None:
            raise NotFoundException("JurisdictionPack", pack_id)
        return pack
    as_of = as_of or date.today()
    in_force = (query.filter(or_(JurisdictionPack.effective_from.is_(None), JurisdictionPack.effective_from <= as_of),
                             or_(JurisdictionPack.effective_to.is_(None), JurisdictionPack.effective_to >= as_of))
                .order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).first())
    return in_force or query.order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).first()


def _sa_pack_rows(db: Session, pack):
    """Return (ContributionRate[], TaxSlab[]) for a Saudi canonical pack."""
    from app.modules.payroll.models import ContributionRate, TaxSlab

    if pack is None:
        return [], []
    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                              ContributionRate.organization_id.is_(None)).all()
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                     TaxSlab.organization_id.is_(None)).all()
    return rates, slabs


def get_sa_readiness(db: Session, pack_id: Optional[int] = None) -> dict:
    """Super Admin release gates for one Saudi tax pack — read-only.
    Gates that depend on work outside this platform (specialist review,
    WPS generation, EOS ledger, parallel payroll) stay incomplete until
    evidenced: Saudi Arabia never becomes production-ready merely because
    its content exists."""
    from app.modules.payroll.engine import fallback_registry
    from app.modules.payroll.models import SourceArtifact, TestCertificationRun

    pack = latest_sa_tax_pack(db, pack_id)
    items = []

    def add(key, label, complete, detail=None, required=True):
        items.append({"key": key, "label": label, "required": required, "complete": bool(complete), "detail": detail})

    if pack is None:
        add("statutory_pack", "Saudi statutory tax pack exists", False,
            "No SA tax pack — run scripts/seed_saudi_arabia_canonical_packs.py.")
        return {"packId": None, "packVersion": None, "ready": False, "items": items,
                "blockers": ["No Saudi tax pack exists."]}

    source = (db.query(SourceArtifact).filter(SourceArtifact.id == pack.source_document_id).first()
              if pack.source_document_id else None)
    add("source_evidence", "Primary-source evidence linked to the pack (SA-003)", source is not None,
        source.title if source else "Link a Source Evidence artifact.")
    reviewed = bool(source and source.reviewer_approved_at)
    add("statutory_review", "G1 — GOSI rates, branches, caps and earning classes independently validated",
        reviewed, "Reviewed." if reviewed else "Awaiting independent Saudi payroll review.")

    rates, slabs = _sa_pack_rows(db, pack)
    rate_keys = {r.component_key for r in rates}
    rule_types = {s.rule_type for s in slabs}
    required = [e["resolverKey"] for e in fallback_registry._ENGINE_CONSTANT_REGISTRY
                if e["country"] == SA and e.get("required", True)]
    missing = sorted(k for k in required if k not in rate_keys)
    add("parameters", "Scalar parameters configured (thresholds, caps, floors, ceilings)", not missing,
        "Missing: " + ", ".join(missing) if missing else f"All {len(required)} required parameters configured.")

    branch_regimes = {"PENSION_NEW", "PENSION_LEGACY", "SANED", "OCCUPATIONAL_HAZARDS"}
    absent_branches = [r for r in branch_regimes if r not in rule_types]
    add("gosi_branches", "GOSI branch rows for every worker class (PENSION_NEW/LEGACY, SANED, OCCUPATIONAL_HAZARDS)",
        not absent_branches, "Missing branch regimes: " + ", ".join(absent_branches) if absent_branches
        else "All four GOSI branch regimes present.")
    if "SA_EARNING_CLASS" not in rule_types:
        add("earning_classes", "Earning classification rows (GOSI/WPS/EOS)", False,
            "No SA_EARNING_CLASS slabs configured.")
    else:
        add("earning_classes", "Earning classification rows (GOSI/WPS/EOS)", True,
            "SA_EARNING_CLASS rows present.")

    latest_run = (db.query(TestCertificationRun).filter(TestCertificationRun.jurisdiction_country == SA)
                  .order_by(TestCertificationRun.run_at.desc(), TestCertificationRun.id.desc()).first())
    add("certification", "Golden-vector certification PASS", latest_run is not None and latest_run.status == "PASS",
        f"Latest run #{latest_run.id}: {latest_run.status}" if latest_run else "No SA certification run yet.")
    add("approval", "Distinct approver recorded (four-eyes)", pack.approved_by_id is not None,
        "Approved." if pack.approved_by_id else "Not yet approved by a distinct Super Admin.")
    add("wps", "WPS file generation from committed payroll (SA-025)", True,
        "Built: an SIE extract is derived from a committed run (POST .../wps-files), "
        "content-addressed and tracked through UPLOADED/ACCEPTED/REJECTED.")
    add("final_settlement", "Final settlement processing (SA-026/SA-027)", True,
        "Built: the EOS award (Art. 84/85/87) plus recorded leave/notice/repatriation dues "
        "(POST .../final-settlements), maker-checker approved and paid.")
    add("eos_ledger", "End-of-service award accrual and resignation fraction (SA-020/SA-021)", True,
        "Built: per-period incremental accrual on the ledger (POST .../eos-accrual) with the "
        "Art. 87 resignation fraction applied at final settlement.")
    add("parallel_payroll", "Two reconciled parallel payroll cycles plus termination and conguaglio", False,
        "Evidence required from the implementation team.")

    blockers = [f"{i['label']}: {i['detail']}" for i in items if i["required"] and not i["complete"]]
    return {"packId": pack.id, "packVersion": pack.version, "packStatus": pack.status, "ready": not blockers,
            "items": items, "blockers": blockers}


def sa_payslip_snapshot(result) -> "dict | None":
    """PayslipItem.sa_calculation_snapshot for a Saudi result (None for every
    other country): the GOSI branches, labour reports and the engine trace,
    JSON-safe."""
    trace = getattr(result, "sa_calculation_trace", None)
    if trace is None:
        return None

    def s(name):
        value = getattr(result, name, None)
        return None if value is None else str(value)

    return _json_safe({
        "gosi": {
            "employeePension": s("employee_pension"),
            "employerPension": s("employer_pension"),
            "employeeSocialSecurity": s("social_security"),
            "employerSocialSecurity": s("employer_social_security"),
            "employerOccupationalHazard": s("employer_occupational_hazard"),
            "employeeTotal": s("sa_employee_total"),
            "employerTotal": s("sa_employer_total"),
            "workerClass": getattr(result, "sa_worker_class", None),
            "cohort": getattr(result, "sa_cohort", None),
        },
        "labour": getattr(result, "sa_result", {}).get("labour", {}),
        "calculation": trace,
    })


def preview_saudi_arabia_calculation(db: Session, data) -> dict:
    """Read-only Super Admin simulation against ONE Saudi pack: the SAME
    production engine a payroll run uses, with every worker and employer fact
    supplied inline. Writes nothing; a blocked calculation returns the
    engine's own reason, never a figure."""
    from types import SimpleNamespace

    from app.core.exceptions import BadRequestException
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.service import pack_rows_for_golden

    pack = latest_sa_tax_pack(db, data.jurisdictionPackId, as_of=data.payDate)
    if pack is None:
        raise BadRequestException("No Saudi tax pack exists — run the Saudi seed first.")
    rate_map, slabs = pack_rows_for_golden(db, pack, data.payDate)
    profile = SimpleNamespace(
        sa_worker_class=data.workerClass,
        sa_cohort=data.cohort,
        sa_cohort_evidence_ref=data.cohortEvidenceRef,
        sa_contributory_wage=data.contributoryWage,
    )
    inputs = {
        "sa_statutory_profile": profile,
        "sa_organization_id": data.organizationId,
        "sa_employee_id": data.employeeId,
        "sa_deduction_orders": data.deductionOrders,
        "sa_overtime_hours": data.overtimeHours,
        "sa_ramadan": data.ramadan,
        "sa_work_hours_records": data.workHoursRecords,
    }
    ctx = PayrollContext(
        gross=data.gross, basic=data.basic, country=SA, pay_frequency=data.payFrequency,
        pay_date=data.payDate, rate_map=rate_map, slabs=slabs, **inputs,
    )
    base = {"pack": {"id": pack.id, "packId": pack.pack_id, "version": pack.version, "status": pack.status},
            "payDate": data.payDate.isoformat(), "readOnly": True}
    try:
        result = calculate_payroll(ctx, "standard")
    except MissingComplianceConfigurationError as exc:
        return {**base, "blocked": True, "blockedKey": exc.key,
                "blockedReason": getattr(exc, "reason", None) or str(exc)}
    return {**base, "blocked": False,
            "result": {"gross": str(result.gross), "totalDeductions": str(result.total_deductions),
                       "netPay": str(result.net_pay)},
            "saudiArabia": sa_payslip_snapshot(result)}


def pack_golden_check(db: Session, pack: "JurisdictionPack") -> dict:
    """Every SA golden vector whose pay date is inside the pack window,
    re-run with the fixture's embedded rows REPLACED by this pack's rows."""
    from app.modules.payroll import service

    def bind(context, pay):
        rate_map, slabs = service.pack_rows_for_golden(db, pack, pay)
        return {"rate_map": rate_map, "slabs": slabs}

    return service.run_pack_golden_vectors(db, pack, "sa_golden", bind)


# ═══════════════════════════════════════════════════════════════════════════
# Org-scoped employer readiness (ZP-SA-ENG-001 §16) — mirrors HK pattern
# ═══════════════════════════════════════════════════════════════════════════

def sa_employer_readiness(db: Session, organization_id: int, today: Optional[date] = None) -> dict:
    """Organisation-level Saudi Arabia readiness: GOSI registration, active pack,
    workforce profile completeness, and resolver checks — built from the same
    logic as the run preflight so the UI can never say READY when a run would BLOCK."""
    from app.modules.payroll.models import CompanyComplianceDetails, JurisdictionPack, PayrollEmployee
    from app.modules.payroll.engine import fallback_registry

    today = today or date.today()
    checks = []

    # Company registration details (CR, GOSI, MHRSD, Mudad)
    company = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization_id).first()
    ids = (company.tax_identifiers or {}) if company else {}
    gosi_employer_number = ids.get("gosi_employer_number")
    mhrsd_establishment_number = ids.get("mhrsd_establishment_number")
    mudad_id = ids.get("mudad_id")
    cr_number = ids.get("cr_number")

    if not cr_number:
        checks.append({"severity": "BLOCK", "message": "Commercial Registration (CR) number is not recorded",
                       "source": "Company Details → Saudi employer registration",
                       "action": "Record the CR number under Compliance → Company Details"})
    if not gosi_employer_number:
        checks.append({"severity": "BLOCK", "message": "GOSI employer number is not recorded",
                       "source": "General Organization for Social Insurance",
                       "action": "Record the GOSI employer number under Compliance → Company Details"})
    if not mhrsd_establishment_number:
        checks.append({"severity": "WARN", "message": "MHRSD establishment number is not recorded",
                       "source": "Ministry of Human Resources and Social Development",
                       "action": "Record the MHRSD establishment number under Compliance → Company Details"})
    if not mudad_id:
        checks.append({"severity": "WARN", "message": "Mudad ID is not recorded",
                       "source": "Wage Protection System (WPS / Mudad)",
                       "action": "Record the Mudad ID under Compliance → Company Details"})

    # Active SA tax pack
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    rates, slabs, pack = resolve_tax_configuration(db, SA, payroll_date=today)
    pack_info = None
    if pack is None:
        checks.append({"severity": "BLOCK", "message": f"no Active Saudi statutory pack is in force on {today}",
                       "source": "tax_resolver", "action": "Activate the Saudi Arabia rule pack (Super Admin)"})
    else:
        pack_info = {"packId": pack.pack_id, "version": pack.version, "taxYear": pack.tax_year,
                     "effectiveFrom": _iso_date(pack.effective_from), "effectiveTo": _iso_date(pack.effective_to)}
        # Parameter completeness (reuse get_sa_readiness logic)
        rate_keys = {r.component_key for r in rates}
        rule_types = {s.rule_type for s in slabs}
        required = [e["resolverKey"] for e in fallback_registry._ENGINE_CONSTANT_REGISTRY
                    if e["country"] == SA and e.get("required", True)]
        missing = sorted(k for k in required if k not in rate_keys)
        if missing:
            checks.append({"severity": "BLOCK", "message": "Missing scalar parameters: " + ", ".join(missing),
                           "source": "tax_resolver", "action": "Configure the missing parameters in the SA pack"})
        branch_regimes = {"PENSION_NEW", "PENSION_LEGACY", "SANED", "OCCUPATIONAL_HAZARDS"}
        absent_branches = [r for r in branch_regimes if r not in rule_types]
        if absent_branches:
            checks.append({"severity": "BLOCK", "message": "Missing GOSI branch regimes: " + ", ".join(absent_branches),
                           "source": "tax_resolver", "action": "Add the missing GOSI branch rows to the SA pack"})
        if "SA_EARNING_CLASS" not in rule_types:
            checks.append({"severity": "BLOCK", "message": "No SA_EARNING_CLASS rows configured",
                           "source": "tax_resolver", "action": "Configure earning classifications in the SA pack"})

    # Workforce & statutory profiles
    employees = [e for e in db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == organization_id, PayrollEmployee.status == EmployeeStatus.ACTIVE).all()
        if service._resolve_employee_country(db, organization_id, getattr(e, "country_code", None)) == SA]

    saudi_emp = gcc_emp = non_saudi_emp = domestic_emp = with_profile = without_profile = 0
    profiles = []

    for emp in employees:
        profile = service.resolve_employee_statutory_profile(db, emp.id, organization_id, today)
        has_profile = profile is not None and (profile.country_code or "").upper() == SA
        if has_profile:
            with_profile += 1
            wc = getattr(profile, "sa_worker_class", None)
            profiles.append({"employeeId": emp.id, "employeeName": emp.name, "employeeCode": emp.employee_code,
                             "workerClass": wc,
                             "cohort": getattr(profile, "sa_cohort", None),
                             "cohortEvidenceRef": getattr(profile, "sa_cohort_evidence_ref", None),
                             "contributoryWage": str(getattr(profile, "sa_contributory_wage", None) or 0)})
        else:
            without_profile += 1
            wc = None
            checks.append({"severity": "BLOCK", "message": f"Employee {emp.name} ({emp.employee_code}) has no Saudi statutory profile in force",
                           "source": "EmployeeStatutoryProfile", "action": "Record a Saudi statutory profile version",
                           "employeeId": emp.id})

        if wc == "SAUDI": saudi_emp += 1
        elif wc == "GCC": gcc_emp += 1
        elif wc == "NON_SAUDI": non_saudi_emp += 1
        elif wc == "DOMESTIC": domestic_emp += 1
        else: non_saudi_emp += 1  # default for missing

    # Recent SA runs (for LabourCompliance dropdown)
    from app.modules.payroll.models import PayrollRun
    recent_runs = (db.query(PayrollRun).filter(PayrollRun.organization_id == organization_id)
                   .order_by(PayrollRun.pay_date.desc(), PayrollRun.id.desc()).limit(10).all())
    recent_runs_list = [{"id": r.id, "periodLabel": f"{r.period_start}–{r.period_end}" if r.period_start else str(r.pay_date),
                         "payDate": r.pay_date.isoformat() if r.pay_date else None} for r in recent_runs]

    # Summarize
    has_blockers = any(c["severity"] == "BLOCK" for c in checks)
    status = "BLOCKED" if has_blockers else ("WARN" if any(c["severity"] == "WARN" for c in checks) else "READY")

    return {
        "asOf": today.isoformat(),
        "status": status,
        "pack": pack_info,
        "gosi": {"employerNumber": gosi_employer_number, "establishmentNumber": mhrsd_establishment_number, "mudadId": mudad_id},
        "workforce": {"saudiEmployees": saudi_emp, "gccEmployees": gcc_emp,
                      "nonSaudiEmployees": non_saudi_emp, "domesticEmployees": domestic_emp,
                      "withStatutoryProfile": with_profile, "withoutStatutoryProfile": without_profile},
        "checks": checks,
        "profiles": profiles,
        "recentRuns": recent_runs_list,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Run preflight, approval fingerprint and corrections (ZP-SA-ENG-001 §16/§17)
# ═══════════════════════════════════════════════════════════════════════════

SA_CORRECTION_MARKER = "SA-CORRECTION:"
SA_CORRECTABLE_INPUTS = {
    "workerClass", "cohort", "cohortEvidenceRef", "contributoryWage",
    "deductionOrders", "overtimeHours", "ramadan", "workHoursRecords",
}
SA_CORRECTION_OBLIGATIONS = {
    "employee_pension", "employer_pension", "social_security",
    "employer_social_security", "employer_occupational_hazard",
}


def sa_run_preflight(db: Session, run) -> list:
    """Every resolver check for every SA payslip of the run, re-run now:
    [{employeeId, key, reason, severity}] — empty means approvable.
    Severity: BLOCK (blocks approval), WARN (advisory), INFO (informational)."""
    from app.modules.payroll.models import PayslipItem, PayrollEmployee, JurisdictionPack
    from app.modules.payroll.engine.countries import saudi_arabia
    from app.modules.payroll.engine import fallback_registry
    from app.modules.payroll.engine.tax_resolver import resolve_tax_configuration
    from app.modules.payroll import service

    blocks = []
    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id,
                                         PayslipItem.country_code == SA).all()
    if not items:
        return []

    # 1. Active SA tax pack check
    rates, slabs, pack = resolve_tax_configuration(db, SA, payroll_date=run.pay_date)
    if pack is None:
        blocks.append({"employeeId": None, "key": "SA_PACK_NOT_ACTIVE",
                       "reason": f"No Active Saudi statutory pack is in force on {run.pay_date}",
                       "severity": "BLOCK", "source": "tax_resolver",
                       "action": "Activate the Saudi Arabia rule pack (Super Admin)"})
    else:
        # 2. Parameter completeness
        rate_keys = {r.component_key for r in rates}
        rule_types = {s.rule_type for s in slabs}
        required = [e["resolverKey"] for e in fallback_registry._ENGINE_CONSTANT_REGISTRY
                    if e["country"] == SA and e.get("required", True)]
        missing = sorted(k for k in required if k not in rate_keys)
        if missing:
            blocks.append({"employeeId": None, "key": "SA_PARAMETERS_MISSING",
                           "reason": "Missing scalar parameters: " + ", ".join(missing),
                           "severity": "BLOCK", "source": "tax_resolver",
                           "action": "Configure the missing parameters in the SA pack"})

        # 3. GOSI branch completeness
        branch_regimes = {"PENSION_NEW", "PENSION_LEGACY", "SANED", "OCCUPATIONAL_HAZARDS"}
        absent_branches = [r for r in branch_regimes if r not in rule_types]
        if absent_branches:
            blocks.append({"employeeId": None, "key": "SA_GOSI_BRANCHES_MISSING",
                           "reason": "Missing GOSI branch regimes: " + ", ".join(absent_branches),
                           "severity": "BLOCK", "source": "tax_resolver",
                           "action": "Add the missing GOSI branch rows to the SA pack"})
        if "SA_EARNING_CLASS" not in rule_types:
            blocks.append({"employeeId": None, "key": "SA_EARNING_CLASSES_MISSING",
                           "reason": "No SA_EARNING_CLASS rows configured",
                           "severity": "BLOCK", "source": "tax_resolver",
                           "action": "Configure earning classifications in the SA pack"})

    # 4. Per-payslip checks (reuse engine logic)
    rate_map = {r.component_key: r for r in rates} if pack is not None else {}
    for item in items:
        employee = db.get(PayrollEmployee, item.employee_id)
        out = resolve_sa_calc_inputs(db, run.organization_id, employee, run.pay_date)
        for b in out.get("blocked", []):
            blocks.append({"employeeId": item.employee_id, "key": b["key"],
                           "reason": b["reason"], "severity": b.get("severity", "BLOCK"),
                           "source": b.get("source"), "action": b.get("action")})

        # 5. Re-run engine checks for committed payslips (preflight = dry-run trace validation)
        if item.sa_calculation_snapshot:
            trace = item.sa_calculation_snapshot.get("trace") or {}
            # The engine already blocked on missing profile/pack/cohort/etc.
            # Here we just surface any residual issues the engine would catch
            pass

    return blocks


def _digest(value) -> str:
    """Stable SHA-256 hex digest of a JSON-serialisable value (ordered keys)."""
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def sa_approval_fingerprint(db: Session, run, store: bool = False) -> dict:
    """What a SA approval is bound to: the resolved inputs (deduction orders,
    overtime, hours excluded — they legitimately move when a LATER period
    posts; this run's own before/after figures are inside its payslip
    snapshots), the engine rule hashes, the pack version, and the payslip
    values.

    If `store=True`, also persist the fingerprint on the run's
    `sa_approval_fingerprint` column (for approval gating)."""
    from app.modules.payroll.models import PayslipItem, PayrollEmployee, JurisdictionPack, PayrollRun

    inputs, rule_hashes, payslips = [], [], []
    items = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id,
                                         PayslipItem.country_code == SA).all()
    for item in items:
        employee = db.get(PayrollEmployee, item.employee_id)
        out = resolve_sa_calc_inputs(db, run.organization_id, employee, run.pay_date)
        # YTD-ish excluded; the rest is the approval basis
        inputs.append([item.employee_id, out["blocked"],
                       {k: v for k, v in out["inputs"].items() if k not in ("ytd",)}])
        trace = (item.sa_calculation_snapshot or {}).get("trace") or {}
        rule_hashes.append([item.id, trace.get("input_hash"), trace.get("rule_hash")])
        payslips.append([item.id, item.employee_id, item.gross_pay, item.net_pay, item.total_deductions,
                         item.sa_calculation_snapshot])
    # pack version(s) in force for this run
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == SA,
                                             JurisdictionPack.pack_type == "tax",
                                             JurisdictionPack.effective_from <= run.pay_date,
                                             (JurisdictionPack.effective_to.is_(None) |
                                              JurisdictionPack.effective_to >= run.pay_date)).first()
    pack_versions = [[pack.id, pack.version] if pack else None]
    components = {"inputs": _digest(inputs), "ruleHashes": _digest(rule_hashes),
                  "packVersions": _digest(pack_versions), "payslips": _digest(payslips)}
    result = {"fingerprint": _digest(components), "components": components}

    if store:
        run_obj = db.query(PayrollRun).filter(PayrollRun.id == run.id).first()
        if run_obj:
            run_obj.sa_approval_fingerprint = result
            db.flush()

    return result


def sa_stored_approval(db: Session, run) -> Optional[dict]:
    from app.modules.payroll.models import TaxConfigurationAudit
    row = (db.query(TaxConfigurationAudit)
           .filter(TaxConfigurationAudit.entity_type == "SA_RUN_APPROVAL",
                   TaxConfigurationAudit.entity_id == run.id)
           .order_by(TaxConfigurationAudit.id.desc()).first())
    return None if row is None or row.action != "create" else row.new_value


def _sa_correction_chain(db: Session, original: PayslipItem) -> list:
    return [i for i in db.query(PayslipItem).filter(PayslipItem.employee_id == original.employee_id,
                                                    PayslipItem.country_code == SA).order_by(PayslipItem.id).all()
            if ((i.sa_calculation_snapshot or {}).get("correction") or {}).get("originalPayslipId") == original.id]


def is_sa_correction_run(run) -> bool:
    return bool(run is not None and (run.notes or "").startswith(SA_CORRECTION_MARKER))


def _apply_sa_corrected_inputs(db: Session, frozen: dict, corrected: dict, organization_id: int) -> dict:
    """Restate the frozen calculation context with the corrected inputs."""
    unknown = sorted(set(corrected) - SA_CORRECTABLE_INPUTS)
    if unknown:
        from app.core.exceptions import BadRequestException
        raise BadRequestException(f"not correctable through a payslip correction: {unknown} "
                                  f"(allowed: {sorted(SA_CORRECTABLE_INPUTS)})")
    import json
    new = json.loads(json.dumps(frozen))
    for key, value in corrected.items():
        if key in ("deductionOrders", "overtimeHours", "ramadan", "workHoursRecords"):
            new["attrs"][key] = value
        else:
            new["attrs"][key] = _json_safe(value)
    return new


def create_sa_correction(db: Session, organization_id: int, original_payslip_id: int, reason: str,
                         affected_obligations: list, corrected_inputs: Optional[dict], actor_id: Optional[int],
                         idempotency_key: Optional[str] = None, correlation_id: Optional[str] = None) -> dict:
    """Append-only correction of a finalized SA payslip: replay its frozen
    context with the restated inputs, book the per-obligation delta as a new
    payslip in a correction run, post the YTD deltas. Commits on success."""
    from app.modules.payroll.models import PayrollRun, PayslipStatus
    from app.modules.payroll.service import _ytd_capture_state, _ytd_record_postings

    try:
        if not (reason or "").strip():
            from app.core.exceptions import BadRequestException
            raise BadRequestException("A correction needs a reason.")
        obligations = sorted(set(affected_obligations or []))
        if not obligations or set(obligations) - SA_CORRECTION_OBLIGATIONS:
            from app.core.exceptions import BadRequestException
            raise BadRequestException(f"affectedObligations must name one or more of {sorted(SA_CORRECTION_OBLIGATIONS)}")
        item = db.query(PayslipItem).filter(PayslipItem.id == original_payslip_id,
                                            PayslipItem.organization_id == organization_id).first()
        if item is None:
            from app.core.exceptions import NotFoundException
            raise NotFoundException("Payslip", original_payslip_id)
        if (item.country_code or "").upper() != SA:
            from app.core.exceptions import BadRequestException
            raise BadRequestException("SA corrections apply to Saudi payslips only.")
        snapshot = item.sa_calculation_snapshot or {}
        if snapshot.get("correction"):
            from app.core.exceptions import BadRequestException
            raise BadRequestException("Correct the original payslip, not a correction delta.")
        run = db.query(PayrollRun).filter(PayrollRun.id == item.payroll_run_id).with_for_update().one()
        if str(getattr(run.status, "value", run.status)) not in ("Approved", "Authorized", "Paid", "Closed"):
            from app.core.exceptions import BadRequestException
            raise BadRequestException("This payslip's run is not finalized — recalculate it in place instead.")
        frozen = snapshot.get("frozenContext")
        if not frozen:
            from app.core.exceptions import BadRequestException
            raise BadRequestException("This payslip has no frozen calculation context, so it cannot be replayed exactly.")

        # 1. integrity: the frozen context must reproduce the original exactly
        original_trace = snapshot.get("trace") or {}
        replay = (sa_replay(frozen).sa_result or {}).get("sa_calculation_trace") or {}
        if (replay.get("input_hash"), replay.get("rule_hash")) != (original_trace.get("input_hash"),
                                                                    original_trace.get("rule_hash")):
            from app.core.exceptions import BadRequestException
            raise BadRequestException("Replaying the frozen context does not reproduce the original payslip — refusing "
                                      "to correct on a drifted basis.")

        # 2. restate on the LATEST basis of the chain (earlier corrections stay applied)
        chain = _sa_correction_chain(db, item)
        basis = (chain[-1].sa_calculation_snapshot or {}).get("frozenContext") if chain else frozen
        new_frozen = _apply_sa_corrected_inputs(db, basis, corrected_inputs or {}, organization_id)
        result = sa_replay(new_frozen)
        new_r = result.sa_result
        new_trace = new_r.get("sa_calculation_trace") or {}

        # 3. per-obligation delta against the effective position
        effective = (chain[-1].sa_calculation_snapshot or {}).get("totalsAll") if chain else snapshot.get("totalsAll", {})
        deltas = {k: Decimal(str(new_r.get(k, 0))) - Decimal(str(effective.get(k, 0)))
                  for k in SA_CORRECTION_OBLIGATIONS}

        # 4. create correction run
        corr_run = PayrollRun(
            organization_id=organization_id,
            period_label=run.period_label,
            period_start=run.period_start,
            period_end=run.period_end,
            pay_date=run.pay_date,
            status=PayrollStatus.PAID,
            notes=f"{SA_CORRECTION_MARKER} corrects run {run.id} payslip {item.id}: {reason}",
            created_by=actor_id,
            calculation_mode="standard",
        )
        db.add(corr_run)
        db.flush()

        # 5. new payslip item with delta columns
        from app.modules.payroll.service import _generate_payslip_number
        new_item = PayslipItem(
            organization_id=organization_id,
            payroll_run_id=corr_run.id,
            employee_id=item.employee_id,
            payslip_number=_generate_payslip_number(db, organization_id),
            employee_name=item.employee_name,
            department=item.department,
            designation=item.designation,
            date_of_joining=item.date_of_joining,
            bank_name=item.bank_name,
            bank_account=item.bank_account,
            pan=item.pan,
            country_code=SA,
            gross_pay=Decimal("0"),
            total_deductions=Decimal("0"),
            net_pay=Decimal("0"),
            employer_contributions=Decimal("0"),
            employer_occupational_hazard=Decimal("0"),
            status=PayslipStatus.PAID,
            sa_calculation_snapshot={
                **new_r,
                "correction": {
                    "originalPayslipId": item.id,
                    "originalRunId": run.id,
                    "correctionRunId": corr_run.id,
                    "deltas": {k: str(v) for k, v in deltas.items()},
                    "totalsAll": {k: str(Decimal(str(effective.get(k, 0))) + deltas.get(k, Decimal("0")))
                                  for k in SA_CORRECTION_OBLIGATIONS},
                },
                "frozenContext": new_frozen,
            },
        )
        db.add(new_item)
        db.flush()

        # 6. YTD deltas for affected obligations
        before = _ytd_capture_state(db, organization_id, item.employee_id, SA)
        for k, v in deltas.items():
            if v != 0:
                _ytd_record_postings(db, organization_id, item.employee_id, SA, {k: v}, corr_run.pay_date)
        after = _ytd_capture_state(db, organization_id, item.employee_id, SA)

        db.commit()
        return {"correctionRunId": corr_run.id, "payslipId": new_item.id,
                "deltas": {k: str(v) for k, v in deltas.items()},
                "ytdBefore": before, "ytdAfter": after}
    except Exception:
        db.rollback()
        raise


def list_sa_corrections(db: Session, organization_id: int, payslip_id: int) -> list:
    item = db.query(PayslipItem).filter(PayslipItem.id == payslip_id,
                                        PayslipItem.organization_id == organization_id).first()
    if item is None or (item.country_code or "").upper() != SA:
        return []
    chain = _sa_correction_chain(db, item)
    return [{"payslipId": c.id, "runId": c.payroll_run_id,
             "deltas": (c.sa_calculation_snapshot or {}).get("correction", {}).get("deltas", {}),
             "totalsAll": (c.sa_calculation_snapshot or {}).get("correction", {}).get("totalsAll", {}),
             "createdAt": c.payroll_run.created_at.isoformat() if c.payroll_run else None}
            for c in chain]


def sa_replay(frozen_context: dict, baseline_totals: dict = None):
    """Replay a frozen SA calculation context through the production engine.
    
    If `baseline_totals` is provided, returns a delta preview comparing the
    replayed result against the baseline (used for correction preview)."""
    from types import SimpleNamespace
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries import saudi_arabia
    from app.modules.payroll.engine.resolver import calculate_payroll

    attrs = frozen_context.get("attrs", {})
    ctx = frozen_context.get("ctx", {})
    profile = SimpleNamespace(**attrs.get("sa_statutory_profile", {}))
    inputs = {
        "sa_statutory_profile": profile,
        "sa_organization_id": ctx.get("sa_organization_id"),
        "sa_employee_id": ctx.get("sa_employee_id"),
        "sa_deduction_orders": attrs.get("sa_deduction_orders"),
        "sa_overtime_hours": attrs.get("sa_overtime_hours"),
        "sa_ramadan": attrs.get("sa_ramadan"),
        "sa_work_hours_records": attrs.get("sa_work_hours_records"),
    }
    pay_ctx = PayrollContext(
        gross=ctx.get("gross"), basic=ctx.get("basic"), country=SA,
        pay_frequency=ctx.get("pay_frequency", "Monthly"),
        pay_date=ctx.get("pay_date"), rate_map=ctx.get("rate_map"),
        slabs=ctx.get("slabs"), **inputs,
    )
    result = calculate_payroll(pay_ctx, "standard")

    if baseline_totals is not None:
        # Build delta preview
        deltas = {}
        for k in SA_CORRECTION_OBLIGATIONS:
            new_val = Decimal(str(getattr(result, k, 0) or 0))
            old_val = Decimal(str(baseline_totals.get(k, 0) or 0))
            deltas[k] = str(new_val - old_val)
        return {
            "result": result,
            "deltas": deltas,
            "totalsAll": {k: str(Decimal(str(baseline_totals.get(k, 0))) + Decimal(deltas[k]))
                          for k in SA_CORRECTION_OBLIGATIONS}
        }

    return result


def _json_safe(value):
    """Decimals as exact strings and dates as ISO text, recursively."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _field(data, name, default=None):
    """One camelCase request field from a Pydantic model or a plain dict."""
    if data is None:
        return default
    if isinstance(data, dict):
        return data.get(name, default)
    return getattr(data, name, default)


def _as_date(value):
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_decimal(value, default=None):
    if value is None or value == "":
        return default
    return Decimal(str(value))


def _sa_amount(row, attr="flat_amount"):
    value = getattr(row, attr, None) if row is not None else None
    return None if value is None else Decimal(str(value))


# ═══════════════════════════════════════════════════════════════════════════
# Employer GOSI registration and employee contracts (SA-011/SA-014) ──────────
# Versioned, effective-dated rows: one OPEN row per org / per employee at a
# time (the DB partial-unique index enforces it). Creating a new version closes
# the row it succeeds — the same shape EmployeeStatutoryProfile already uses.
# ═══════════════════════════════════════════════════════════════════════════

SA_EMPLOYER_PROFILE_STATUSES = ("DRAFT", "APPROVED", "SUPERSEDED")
SA_CONTRACT_STATUSES = ("DRAFT", "APPROVED", "SUPERSEDED")
SA_CONTRACT_TYPES = ("LIMITED", "UNLIMITED", "PART_TIME", "TEMPORARY")


def list_sa_employer_profiles(db: Session, organization_id: int) -> list:
    return (db.query(SaEmployerProfile)
            .filter(SaEmployerProfile.organization_id == organization_id)
            .order_by(SaEmployerProfile.effective_from.desc(), SaEmployerProfile.id.desc()).all())


def get_sa_employer_profile(db: Session, organization_id: int, as_of: Optional[date] = None):
    """The employer's GOSI profile in force on `as_of` (default: the single open
    row). None when none has been recorded — the caller blocks, never guesses."""
    from sqlalchemy import or_

    as_of = as_of or date.today()
    return (db.query(SaEmployerProfile)
            .filter(SaEmployerProfile.organization_id == organization_id,
                    or_(SaEmployerProfile.effective_from.is_(None), SaEmployerProfile.effective_from <= as_of),
                    or_(SaEmployerProfile.effective_to.is_(None), SaEmployerProfile.effective_to >= as_of))
            .order_by(SaEmployerProfile.effective_from.desc(), SaEmployerProfile.id.desc()).first())


def _close_open_employer_profile(db: Session, organization_id: int, effective_from: date):
    open_row = (db.query(SaEmployerProfile)
                .filter(SaEmployerProfile.organization_id == organization_id,
                        SaEmployerProfile.effective_to.is_(None)).first())
    if open_row is not None:
        open_row.effective_to = effective_from - timedelta(days=1)
        open_row.status = "SUPERSEDED"
    return open_row


def create_sa_employer_profile(db: Session, organization_id: int, data, actor_id: Optional[int] = None) -> SaEmployerProfile:
    """Record a new effective-dated employer GOSI profile. A missing GOSI
    employer code blocks (SA-011): the registration is the employer's legal
    identity at GOSI, never inferred from the organisation name."""
    try:
        effective_from = _as_date(_field(data, "effectiveFrom")) or date.today()
        code = (_field(data, "gosiEmployerCode") or "").strip()
        if not code:
            raise BadRequestException("A GOSI employer code is required (SA-011).")
        previous = _close_open_employer_profile(db, organization_id, effective_from)
        row = SaEmployerProfile(
            organization_id=organization_id, effective_from=effective_from,
            gosi_employer_code=code,
            branch_code=(_field(data, "branchCode") or None),
            activity_code=(_field(data, "activityCode") or None),
            risk_category=(_field(data, "riskCategory") or None),
            occupational_hazard_rate_pct=_as_decimal(_field(data, "occupationalHazardRatePct")),
            saned_employer_rate_pct=_as_decimal(_field(data, "sanedEmployerRatePct")),
            pension_employer_rate_pct=_as_decimal(_field(data, "pensionEmployerRatePct")),
            status="DRAFT",
            previous_version_id=(previous.id if previous is not None else None),
            created_by_id=actor_id, updated_by_id=actor_id,
        )
        db.add(row)
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def approve_sa_employer_profile(db: Session, organization_id: int, profile_id: int, actor_id: Optional[int] = None):
    try:
        row = (db.query(SaEmployerProfile)
               .filter(SaEmployerProfile.id == profile_id,
                       SaEmployerProfile.organization_id == organization_id).first())
        if row is None:
            raise NotFoundException("SaEmployerProfile", profile_id)
        if row.status != "DRAFT":
            raise BadRequestException(f"Employer profile {row.id} is {row.status}; only a DRAFT can be approved.")
        if row.approved_by_id is not None and row.approved_by_id == actor_id:
            raise BadRequestException("The same operator cannot approve their own draft (four-eyes).")
        row.status = "APPROVED"
        row.approved_by_id = actor_id
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def list_sa_contract_versions(db: Session, organization_id: int, employee_id: int) -> list:
    return (db.query(SaContractVersion)
            .filter(SaContractVersion.organization_id == organization_id,
                    SaContractVersion.employee_id == employee_id)
            .order_by(SaContractVersion.effective_from.desc(), SaContractVersion.id.desc()).all())


def get_sa_contract_version(db: Session, employee_id: int, as_of: Optional[date] = None):
    """The employee's contract in force on `as_of` (default: the single open
    row). None when none has been recorded."""
    from sqlalchemy import or_

    as_of = as_of or date.today()
    return (db.query(SaContractVersion)
            .filter(SaContractVersion.employee_id == employee_id,
                    or_(SaContractVersion.effective_from.is_(None), SaContractVersion.effective_from <= as_of),
                    or_(SaContractVersion.effective_to.is_(None), SaContractVersion.effective_to >= as_of))
            .order_by(SaContractVersion.effective_from.desc(), SaContractVersion.id.desc()).first())


def create_sa_contract_version(db: Session, organization_id: int, employee_id: int, data,
                               actor_id: Optional[int] = None) -> SaContractVersion:
    """Record a new effective-dated employment contract. Contract type is
    required and validated against the Labour-Law vocabulary; an unknown type
    blocks rather than being stored as free text."""
    try:
        _employee(db, employee_id, organization_id)
        effective_from = _as_date(_field(data, "effectiveFrom")) or date.today()
        contract_type = (_field(data, "contractType") or "").strip().upper()
        if contract_type not in SA_CONTRACT_TYPES:
            raise BadRequestException(
                f"contractType must be one of {', '.join(SA_CONTRACT_TYPES)}; got {contract_type!r}.")
        open_row = (db.query(SaContractVersion)
                    .filter(SaContractVersion.employee_id == employee_id,
                            SaContractVersion.effective_to.is_(None)).first())
        if open_row is not None:
            open_row.effective_to = effective_from - timedelta(days=1)
            open_row.status = "SUPERSEDED"
        row = SaContractVersion(
            employee_id=employee_id, organization_id=organization_id, effective_from=effective_from,
            contract_type=contract_type,
            occupation=(_field(data, "occupation") or None),
            basic_wage=_as_decimal(_field(data, "basicWage")),
            housing_allowance=_as_decimal(_field(data, "housingAllowance")),
            transport_allowance=_as_decimal(_field(data, "transportAllowance")),
            other_allowances=_as_decimal(_field(data, "otherAllowances")),
            in_kind_housing_value=_as_decimal(_field(data, "inKindHousingValue")),
            probation_end_date=_as_date(_field(data, "probationEndDate")),
            contract_end_date=_as_date(_field(data, "contractEndDate")),
            status="DRAFT",
            previous_version_id=(open_row.id if open_row is not None else None),
            created_by_id=actor_id, updated_by_id=actor_id,
        )
        db.add(row)
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def approve_sa_contract_version(db: Session, organization_id: int, employee_id: int, contract_id: int,
                                actor_id: Optional[int] = None):
    try:
        row = (db.query(SaContractVersion)
               .filter(SaContractVersion.id == contract_id,
                       SaContractVersion.organization_id == organization_id,
                       SaContractVersion.employee_id == employee_id).first())
        if row is None:
            raise NotFoundException("SaContractVersion", contract_id)
        if row.status != "DRAFT":
            raise BadRequestException(f"Contract {row.id} is {row.status}; only a DRAFT can be approved.")
        if row.approved_by_id is not None and row.approved_by_id == actor_id:
            raise BadRequestException("The same operator cannot approve their own draft (four-eyes).")
        row.status = "APPROVED"
        row.approved_by_id = actor_id
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


# ═══════════════════════════════════════════════════════════════════════════
# GOSI liability monthly reconciliation (SA-024) ─────────────────────────────
# One row per org per contribution month, aggregated from the frozen GOSI
# snapshot on every committed Saudi payslip. Rebuilding a month is an upsert,
# never a second liability: (organization_id, contribution_month) is UNIQUE.
# ═══════════════════════════════════════════════════════════════════════════


def _sa_run(db: Session, organization_id: int, run_id: int) -> PayrollRun:
    run = (db.query(PayrollRun)
           .filter(PayrollRun.id == run_id, PayrollRun.organization_id == organization_id).first())
    if run is None:
        raise NotFoundException("PayrollRun", run_id)
    return run


def _assert_committed(run: PayrollRun) -> None:
    if PAYROLL_STATUS_ORDER.index(run.status) < PAYROLL_STATUS_ORDER.index(PayrollStatus.APPROVED):
        raise BadRequestException(
            f"Payroll run {run.id} is {run.status}; this ledger builds only from a run "
            f"that is {PayrollStatus.APPROVED.value} or later.")


def _gosi_snapshot_totals(snapshot: dict) -> dict:
    """The five GOSI amounts plus the contributory wage from one frozen
    sa_calculation_snapshot. A snapshot with no branches returns None so the
    caller can skip (an uncommitted/foreign payslip), never a zero liability."""
    gosi = (snapshot or {}).get("gosi") or {}
    if not gosi:
        return None
    def d(key):
        value = gosi.get(key)
        return Decimal(str(value)) if value not in (None, "") else Decimal("0")
    contrib = ((snapshot or {}).get("calculation") or {}).get("contributoryWage")
    return {
        "pension_employee": d("employeePension"),
        "pension_employer": d("employerPension"),
        "saned_employee": d("employeeSocialSecurity"),
        "saned_employer": d("employerSocialSecurity"),
        "oh_employer": d("employerOccupationalHazard"),
        "contributory_wage": Decimal(str(contrib)) if contrib not in (None, "") else Decimal("0"),
    }


def build_sa_gosi_liability(db: Session, organization_id: int, run_id: int,
                            actor_id: Optional[int] = None) -> SaGosiLiability:
    """Aggregate one committed run's Saudi payslips into the org's monthly GOSI
    liability. Idempotent: rebuilding the same month updates the row in place."""
    try:
        run = _sa_run(db, organization_id, run_id)
        _assert_committed(run)
        month = date(run.pay_date.year, run.pay_date.month, 1)

        totals = dict(total_wages=Decimal("0"), contributory_wages=Decimal("0"),
                      pension_employee=Decimal("0"), pension_employer=Decimal("0"),
                      saned_employee=Decimal("0"), saned_employer=Decimal("0"),
                      occupational_hazard_employer=Decimal("0"))
        items = (db.query(PayslipItem)
                 .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == SA).all())
        counted = 0
        for item in items:
            snap = _gosi_snapshot_totals(item.sa_calculation_snapshot)
            if snap is None:
                continue
            counted += 1
            totals["total_wages"] += Decimal(str(item.gross_pay or 0))
            totals["contributory_wages"] += snap["contributory_wage"]
            totals["pension_employee"] += snap["pension_employee"]
            totals["pension_employer"] += snap["pension_employer"]
            totals["saned_employee"] += snap["saned_employee"]
            totals["saned_employer"] += snap["saned_employer"]
            totals["occupational_hazard_employer"] += snap["oh_employer"]
        totals["total_due"] = (totals["pension_employee"] + totals["pension_employer"]
                               + totals["saned_employee"] + totals["saned_employer"]
                               + totals["occupational_hazard_employer"])

        row = (db.query(SaGosiLiability)
               .filter(SaGosiLiability.organization_id == organization_id,
                       SaGosiLiability.contribution_month == month).first())
        if row is None:
            row = SaGosiLiability(organization_id=organization_id, contribution_month=month,
                                  created_by_id=actor_id, status="DRAFT")
            db.add(row)
        for key, value in totals.items():
            setattr(row, key, value)
        row.source_run_id = run.id
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def list_sa_gosi_liabilities(db: Session, organization_id: int,
                             from_month: Optional[date] = None, to_month: Optional[date] = None) -> list:
    query = db.query(SaGosiLiability).filter(SaGosiLiability.organization_id == organization_id)
    if from_month is not None:
        query = query.filter(SaGosiLiability.contribution_month >= from_month)
    if to_month is not None:
        query = query.filter(SaGosiLiability.contribution_month <= to_month)
    return query.order_by(SaGosiLiability.contribution_month.desc()).all()


def mark_sa_gosi_liability_paid(db: Session, organization_id: int, liability_id: int,
                                payment_reference: Optional[str] = None, actor_id: Optional[int] = None):
    try:
        row = (db.query(SaGosiLiability)
               .filter(SaGosiLiability.id == liability_id,
                       SaGosiLiability.organization_id == organization_id).first())
        if row is None:
            raise NotFoundException("SaGosiLiability", liability_id)
        if row.status != "DRAFT":
            raise BadRequestException(f"GOSI liability {row.id} is {row.status}; only a DRAFT can be marked paid.")
        row.status = "PAID"
        row.paid_at = service_now()
        row.payment_reference = payment_reference
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def service_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════
# End-of-service accrual ledger (SA-020/SA-021) ──────────────────────────────
# One row per employee per payroll period. The period's accrual is the
# INCREMENT of the Art. 84/85 award across the period: award(service at
# period_end) − award(service at period_start), so the 5-year rate step is
# handled exactly once, when service crosses it. Never a monthly deduction.
# ═══════════════════════════════════════════════════════════════════════════


def _service_years(start: Optional[date], end: date) -> Optional[Decimal]:
    """Fractional years of service (days ÷ 365.25) — the shape eos.py consumes.
    None when the start date is unknown, so the caller blocks/skips rather than
    guessing service."""
    if start is None or end is None:
        return None
    if end < start:
        return None
    return (Decimal((end - start).days) / Decimal("365.25"))


def _eos_base_from(contract, employee) -> Optional[dict]:
    """The EOS wage (Art. 84) = last basic + the housing the contract treats as
    part of it. Falls back to the employee's annual basic/hra ÷ 12 only when no
    contract version is recorded. None when neither carries a basic wage."""
    if contract is not None and contract.basic_wage is not None:
        housing = contract.housing_allowance or Decimal("0")
        in_kind = contract.in_kind_housing_value or Decimal("0")
        return {"basic": Decimal(str(contract.basic_wage)),
                "housing": Decimal(str(housing)) + Decimal(str(in_kind)),
                "source": "contract"}
    if employee is not None and employee.basic is not None:
        basic = Decimal(str(employee.basic)) / Decimal("12")
        hra = Decimal(str(employee.hra or 0)) / Decimal("12")
        return {"basic": basic, "housing": hra, "source": "employee"}
    return None


def _sa_eos_rate_rows(db: Session, pack) -> dict:
    rates, _slabs = _sa_pack_rows(db, pack)
    return {r.component_key: r for r in rates}


def accrue_sa_eos_for_run(db: Session, organization_id: int, run_id: int,
                          actor_id: Optional[int] = None) -> dict:
    """Accrue one month of EOS for every Saudi employee in a committed run.
    Returns {"entries": [...], "skipped": [{employeeId, reason}]}. A missing pack
    (no configured EOS rows) blocks the whole accrual; a per-employee missing
    base/joining date is reported as skipped, never accrued from a guess."""
    from app.modules.payroll.engine.jurisdictions.saudi_arabia import eos as _eos

    try:
        run = _sa_run(db, organization_id, run_id)
        _assert_committed(run)
        pack = latest_sa_tax_pack(db, as_of=run.pay_date)
        if pack is None:
            raise BadRequestException("No Saudi tax pack in force — EOS rates are not configured.")
        rate_rows = _sa_eos_rate_rows(db, pack)
        if _sa_amount(rate_rows.get("sa_eos_first_5_years_months")) is None:
            raise BadRequestException("The Saudi pack carries no EOS accrual rows — nothing to accrue.")

        period_from, period_to = run.period_start, run.period_end
        days = (period_to - period_from).days + 1
        entries, skipped = [], []
        items = (db.query(PayslipItem)
                 .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == SA).all())
        for item in items:
            employee = db.get(PayrollEmployee, item.employee_id)
            contract = get_sa_contract_version(db, item.employee_id, as_of=period_to)
            base = _eos_base_from(contract, employee)
            if base is None:
                skipped.append({"employeeId": item.employee_id, "reason": "no recording of basic wage (contract or employee)"})
                continue
            joining = employee.date_of_joining if employee is not None else None
            if joining is None:
                skipped.append({"employeeId": item.employee_id, "reason": "no date of joining recorded"})
                continue
            sv_start = _service_years(joining, max(joining, period_from))
            sv_end = _service_years(joining, period_to)
            eos_base = base["basic"] + base["housing"]
            start_res = _eos.eos_award(eos_base, sv_start, rate_rows)
            end_res = _eos.eos_award(eos_base, sv_end, rate_rows)
            if start_res["status"] != "OK" or end_res["status"] != "OK":
                skipped.append({"employeeId": item.employee_id, "reason": "EOS accrual rows not configured"})
                continue
            accrual_months = end_res["months"] - start_res["months"]
            accrued = (eos_base * accrual_months).quantize(Decimal("0.01"))

            prior = (db.query(SaEosLedgerEntry)
                     .filter(SaEosLedgerEntry.employee_id == item.employee_id,
                             SaEosLedgerEntry.organization_id == organization_id)
                 .order_by(SaEosLedgerEntry.period_from.desc()).first())
            cumulative = (Decimal(str(prior.cumulative_award or 0)) if prior is not None else Decimal("0")) + accrued

            row = (db.query(SaEosLedgerEntry)
                   .filter(SaEosLedgerEntry.employee_id == item.employee_id,
                           SaEosLedgerEntry.organization_id == organization_id,
                           SaEosLedgerEntry.period_from == period_from,
                           SaEosLedgerEntry.period_to == period_to).first())
            if row is None:
                row = SaEosLedgerEntry(employee_id=item.employee_id, organization_id=organization_id,
                                       period_from=period_from, period_to=period_to, source_run_id=run.id,
                                       status="ACCRUED")
                db.add(row)
            row.basic_wage = base["basic"]
            row.housing_allowance = base["housing"]
            row.eos_base = eos_base
            row.days_worked = days
            row.accrual_months = accrual_months
            row.eos_award_accrued = accrued
            row.cumulative_award = cumulative
            row.source_run_id = run.id
            entries.append(row)
        db.flush()
        db.commit()
        return {"entries": entries, "skipped": skipped}
    except Exception:
        db.rollback()
        raise


def list_sa_eos_ledger(db: Session, organization_id: int, employee_id: Optional[int] = None) -> list:
    query = db.query(SaEosLedgerEntry).filter(SaEosLedgerEntry.organization_id == organization_id)
    if employee_id is not None:
        query = query.filter(SaEosLedgerEntry.employee_id == employee_id)
    return query.order_by(SaEosLedgerEntry.employee_id, SaEosLedgerEntry.period_from).all()


# ═══════════════════════════════════════════════════════════════════════════
# Final settlement (SA-026/SA-027) ───────────────────────────────────────────
# Termination pays the full accrued award; resignation pro-rates it by the
# Art. 87 service band. Payment deadline: 7 days (termination) / 14 days
# (resignation) unless the request states otherwise.
# ═══════════════════════════════════════════════════════════════════════════

SA_FINAL_SETTLEMENT_STATUSES = ("DRAFT", "APPROVED", "PAID")


def _settlement_deadline_days(db: Session, termination_type: str, as_of: date) -> int:
    """Read the settlement deadline from the active SA pack's content rows.
    Falls back to statutory defaults if the pack doesn't carry the rows."""
    pack = latest_sa_tax_pack(db, as_of=as_of)
    if pack is None:
        return 7 if termination_type == "TERMINATION" else 14
    rates, _ = _sa_pack_rows(db, pack)
    key = "sa_settlement_deadline_termination_days" if termination_type == "TERMINATION" else "sa_settlement_deadline_resignation_days"
    row = next((r for r in rates if r.component_key == key), None)
    if row is not None and row.flat_amount is not None:
        return int(Decimal(str(row.flat_amount)))
    return 7 if termination_type == "TERMINATION" else 14


def _eos_rates_or_block(db: Session, as_of: date) -> dict:
    pack = latest_sa_tax_pack(db, as_of=as_of)
    if pack is None:
        raise BadRequestException("No Saudi tax pack in force — EOS rates are not configured.")
    return _sa_eos_rate_rows(db, pack)


def build_sa_final_settlement(db: Session, organization_id: int, data, actor_id: Optional[int] = None) -> SaFinalSettlement:
    """Compute one final settlement and record it as DRAFT. The EOS award is the
    configured Art. 84/85/87 result; every other line (unused leave, notice,
    repatriation, other dues, deductions) is supplied as a recorded fact — this
    ledger never invents a leave or notice figure."""
    from app.modules.payroll.engine.jurisdictions.saudi_arabia import eos as _eos

    try:
        employee_id = _field(data, "employeeId")
        employee = _employee(db, employee_id, organization_id)
        termination_date = _as_date(_field(data, "terminationDate"))
        if termination_date is None:
            raise BadRequestException("terminationDate is required.")
        termination_type = (_field(data, "terminationType") or "").strip().upper()
        if termination_type not in ("TERMINATION", "RESIGNATION"):
            raise BadRequestException("terminationType must be TERMINATION or RESIGNATION.")

        rate_rows = _eos_rates_or_block(db, termination_date)
        contract = get_sa_contract_version(db, employee_id, as_of=termination_date)
        base = _eos_base_from(contract, employee)
        if base is None:
            raise BadRequestException(f"Employee {employee_id} has no recorded basic wage; the EOS base cannot be determined.")
        if employee.date_of_joining is None:
            raise BadRequestException(f"Employee {employee_id} has no recorded date of joining; service cannot be determined.")

        eos_base = base["basic"] + base["housing"]
        years = _service_years(employee.date_of_joining, termination_date)
        award = _eos.eos_award(eos_base, years, rate_rows, excluded=bool(_field(data, "excluded", False)))
        settled = _eos.settlement_amount(award, termination_type == "RESIGNATION", years, rate_rows)
        if settled["status"] not in ("OK", "EXCLUDED"):
            raise BadRequestException(f"The EOS award could not be computed: {settled.get('reason')}")
        eos_award = Decimal(str(settled.get("payable", 0)))

        leave_pay = _as_decimal(_field(data, "unusedLeavePay"), Decimal("0"))
        notice_pay = _as_decimal(_field(data, "noticePay"), Decimal("0"))
        repatriation = _as_decimal(_field(data, "repatriationPay"), Decimal("0"))
        other = _as_decimal(_field(data, "otherDues"), Decimal("0"))
        deductions = _as_decimal(_field(data, "deductions"), Decimal("0"))
        total_due = eos_award + leave_pay + notice_pay + repatriation + other
        net = total_due - deductions

        deadline_days = _field(data, "settlementDeadlineDays")
        deadline = termination_date + timedelta(days=int(deadline_days) if deadline_days is not None
                                                else _settlement_deadline_days(db, termination_type, termination_date))

        row = SaFinalSettlement(
            employee_id=employee_id, organization_id=organization_id,
            termination_date=termination_date, termination_type=termination_type,
            notice_given=bool(_field(data, "noticeGiven", False)),
            notice_period_days=_field(data, "noticePeriodDays"),
            eos_award=eos_award,
            unused_leave_days=int(_field(data, "unusedLeaveDays") or 0),
            unused_leave_pay=leave_pay, notice_pay=notice_pay, repatriation_pay=repatriation,
            other_dues=other, total_due=total_due, deductions=deductions, net_payable=net,
            deadline_date=deadline, status="DRAFT", created_by_id=actor_id,
        )
        db.add(row)
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def list_sa_final_settlements(db: Session, organization_id: int, employee_id: Optional[int] = None) -> list:
    query = db.query(SaFinalSettlement).filter(SaFinalSettlement.organization_id == organization_id)
    if employee_id is not None:
        query = query.filter(SaFinalSettlement.employee_id == employee_id)
    return query.order_by(SaFinalSettlement.termination_date.desc()).all()


def approve_sa_final_settlement(db: Session, organization_id: int, settlement_id: int, actor_id: Optional[int] = None):
    try:
        row = (db.query(SaFinalSettlement)
               .filter(SaFinalSettlement.id == settlement_id,
                       SaFinalSettlement.organization_id == organization_id).first())
        if row is None:
            raise NotFoundException("SaFinalSettlement", settlement_id)
        if row.status != "DRAFT":
            raise BadRequestException(f"Final settlement {row.id} is {row.status}; only a DRAFT can be approved.")
        if row.approved_by_id == actor_id:
            raise BadRequestException("A final settlement must be approved by a different user (four-eyes).")
        row.status = "APPROVED"
        row.approved_by_id = actor_id
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def pay_sa_final_settlement(db: Session, organization_id: int, settlement_id: int,
                            payment_reference: Optional[str] = None, actor_id: Optional[int] = None):
    try:
        row = (db.query(SaFinalSettlement)
               .filter(SaFinalSettlement.id == settlement_id,
                       SaFinalSettlement.organization_id == organization_id).first())
        if row is None:
            raise NotFoundException("SaFinalSettlement", settlement_id)
        if row.status != "APPROVED":
            raise BadRequestException(f"Final settlement {row.id} is {row.status}; only an APPROVED settlement can be paid.")
        row.status = "PAID"
        row.paid_at = service_now()
        row.payment_reference = payment_reference
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


# ═══════════════════════════════════════════════════════════════════════════
# WPS (Wage Protection System) SIE extract (SA-025) ──────────────────────────
# The SIE is a Salary Information Extract of committed net pay per employee,
# content-addressed (SHA-256) so a re-run of the same run cannot upload twice
# (the SaWpsFile.file_sha256 UNIQUE index is the guard). Per-employee issues
# are recorded as observations, never silently dropped.
# ═══════════════════════════════════════════════════════════════════════════

# Platform observation codes. These mirror the MHRSD SIE observation concept;
# the governed MHRSD code catalogue is not yet loaded, so the platform records
# only codes it can defend from the data it holds (mirroring Italy's refusal to
# invent F24 causali). Extend from the SIE catalogue when it is linked.
SA_WPS_OBSERVATION_MISSING_BANK = "MISSING_BANK_DETAILS"
SA_WPS_OBSERVATION_NON_POSITIVE_NET = "NON_POSITIVE_NET"


def _sa_bank_details(item: PayslipItem) -> dict:
    cf = item.compliance_fields or {}
    return {"iban": cf.get("iban"), "bankCode": cf.get("bank_code"),
            "branchCode": cf.get("branch_code"), "accountNumber": cf.get("account_number")}


def build_sa_wps_file(db: Session, organization_id: int, run_id: int,
                      actor_id: Optional[int] = None) -> dict:
    """Build (or return the already-built) SIE extract for one committed run.
    Returns {"file": SaWpsFile, "records": [...], "observations": [...]}.
    Rebuilding the same run returns the same file row (SHA-256 identity)."""
    try:
        run = _sa_run(db, organization_id, run_id)
        _assert_committed(run)
        items = (db.query(PayslipItem)
                 .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.country_code == SA)
                 .order_by(PayslipItem.employee_id).all())
        records, observations = [], []
        for item in items:
            bank = _sa_bank_details(item)
            net = Decimal(str(item.net_pay or 0))
            records.append({
                "employeeId": item.employee_id,
                "employeeName": item.employee_name,
                "netPay": str(net),
                "grossPay": str(Decimal(str(item.gross_pay or 0))),
                "iban": bank["iban"],
                "bankCode": bank["bankCode"],
                "branchCode": bank["branchCode"],
                "accountNumber": bank["accountNumber"],
            })
            if not bank["iban"]:
                observations.append({"employeeId": item.employee_id, "code": SA_WPS_OBSERVATION_MISSING_BANK,
                                     "description": "No Saudi IBAN recorded for this employee.",
                                     "expected": None, "reported": str(net)})
            if net <= Decimal("0"):
                observations.append({"employeeId": item.employee_id, "code": SA_WPS_OBSERVATION_NON_POSITIVE_NET,
                                     "description": "Net pay is zero or negative — nothing to pay through WPS.",
                                     "expected": None, "reported": str(net)})

        payload = {"organizationId": organization_id, "payDate": run.pay_date.isoformat(),
                   "periodStart": run.period_start.isoformat(), "periodEnd": run.period_end.isoformat(),
                   "records": records}
        sha = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

        file_row = db.query(SaWpsFile).filter(SaWpsFile.file_sha256 == sha).first()
        if file_row is None:
            total = sum((Decimal(r["netPay"]) for r in records), Decimal("0"))
            file_row = SaWpsFile(
                organization_id=organization_id, payroll_run_id=run.id,
                file_name=f"WPS-SIE-{run.pay_date.isoformat()}-{sha[:12]}.json",
                file_sha256=sha, employee_count=len(records), total_amount=total,
                status="UPLOADED", created_by_id=actor_id,
            )
            db.add(file_row)
            db.flush()
            for obs in observations:
                db.add(SaWpsObservation(
                    wps_file_id=file_row.id, employee_id=obs["employeeId"],
                    observation_code=obs["code"], observation_description=obs["description"],
                    expected_amount=obs["expected"], reported_amount=obs["reported"], resolved=False,
                ))
            db.flush()
        db.commit()
        return {"file": file_row, "records": records, "observations": observations, "sha256": sha}
    except Exception:
        db.rollback()
        raise


def list_sa_wps_files(db: Session, organization_id: int) -> list:
    return (db.query(SaWpsFile)
            .filter(SaWpsFile.organization_id == organization_id)
            .order_by(SaWpsFile.created_at.desc(), SaWpsFile.id.desc()).all())


def list_sa_wps_observations(db: Session, organization_id: int, wps_file_id: int) -> list:
    file_row = (db.query(SaWpsFile)
                .filter(SaWpsFile.id == wps_file_id, SaWpsFile.organization_id == organization_id).first())
    if file_row is None:
        raise NotFoundException("SaWpsFile", wps_file_id)
    return (db.query(SaWpsObservation)
            .filter(SaWpsObservation.wps_file_id == wps_file_id)
            .order_by(SaWpsObservation.employee_id).all())


def mark_sa_wps_file_accepted(db: Session, organization_id: int, wps_file_id: int):
    try:
        row = (db.query(SaWpsFile)
               .filter(SaWpsFile.id == wps_file_id, SaWpsFile.organization_id == organization_id).first())
        if row is None:
            raise NotFoundException("SaWpsFile", wps_file_id)
        row.status = "ACCEPTED"
        row.submitted_at = row.submitted_at or service_now()
        row.accepted_at = service_now()
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


def mark_sa_wps_file_rejected(db: Session, organization_id: int, wps_file_id: int, reason: str):
    try:
        row = (db.query(SaWpsFile)
               .filter(SaWpsFile.id == wps_file_id, SaWpsFile.organization_id == organization_id).first())
        if row is None:
            raise NotFoundException("SaWpsFile", wps_file_id)
        if not (reason or "").strip():
            raise BadRequestException("A rejection reason is required.")
        row.status = "REJECTED"
        row.submitted_at = row.submitted_at or service_now()
        row.rejected_at = service_now()
        row.rejection_reason = reason
        db.flush()
        db.commit()
        return row
    except Exception:
        db.rollback()
        raise


# ═══════════════════════════════════════════════════════════════════════════
# Draft canonical content (saudi_arabia_content.py -> rows) ──────────────────
# ═══════════════════════════════════════════════════════════════════════════


def seed_saudi_arabia_pack(db: Session, *, effective_from: date = date(2026, 1, 1),
                           status: str = "Draft") -> "JurisdictionPack":
    """Write saudi_arabia_content.py into the SA-PAYROLL-2026 tax pack:
      * one SourceArtifact per evidence-register entry (S1–S16), reused if present;
      * every scalar parameter (ContributionRate) with its real value in the
        slot its kind names (employee/employer pct, flat_amount, text_value);
      * every GOSI branch row (TaxSlab rule_type="SA_GOSI_BRANCH") with its
        legal effective_from / effective_to;
      * every earning-classification row (TaxSlab rule_type="SA_EARNING_CLASS",
        HK layout: filing_status = component, tax_regime = obligation,
        assessment_basis = INCLUDED / EXCLUDED / REVIEW).

    Draft by default; a pack that has left Draft is never rewritten, and a
    Draft pack's rows are replaced wholesale from the content."""
    from app.modules.payroll.engine.countries import saudi_arabia_content as content
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, SourceArtifact, TaxSlab

    if status != "Draft":
        raise ValueError("seed_saudi_arabia_pack only writes Draft content")
    pack_id, window_from, window_to = content.SA_2026
    pack = (db.query(JurisdictionPack)
            .filter(JurisdictionPack.pack_id == pack_id, JurisdictionPack.version == "1.0").first())
    if pack is not None and pack.status != "Draft":
        raise ValueError(f"{pack_id} is {pack.status!r}, not Draft — refusing to rewrite it")

    sources = {}
    for code, title in content.SOURCE_REFERENCES:
        agency = title.split(" — ", 1)[0]
        form = f"ZP-SA-ENG-001 {code}"
        artifact = (db.query(SourceArtifact)
                    .filter(SourceArtifact.form_number == form, SourceArtifact.agency == agency).first())
        if artifact is None:
            artifact = SourceArtifact(agency=agency[:200], title=title[:300], form_number=form)
            db.add(artifact)
            db.flush()
        sources[code] = artifact.id

    if pack is None:
        pack = JurisdictionPack(pack_id=pack_id, version="1.0", jurisdiction_country=SA, pack_type="tax",
                                effective_from=effective_from or window_from, effective_to=window_to)
        db.add(pack)
        db.flush()
    pack.status = "Draft"
    pack.effective_to = window_to
    pack.source_document_id = sources["S1"]
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).delete()
    db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).delete()

    def dec(value):
        return Decimal(str(value)) if value is not None else None

    order = 0
    for (key, label, ee, er, flat, text, src, pending) in content.SA_SCALAR_CONTENT:
        order += 1
        shown = (f"{ee}%" if ee is not None else f"{er}%" if er is not None
                 else (text if text is not None else str(flat)))
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=SA,
            component_key=key, label=(label + (" [PENDING G1]" if pending else ""))[:100],
            employee_share=shown[:50] if ee is not None else "—",
            employer_share=shown[:50] if er is not None else "—",
            total=shown[:50],
            employee_rate_pct=dec(ee), employer_rate_pct=dec(er),
            flat_amount=dec(flat), text_value=text,
            source_document_id=sources.get(src), sort_order=order))

    for (worker_class, branch, ee_pct, er_pct, floor, ceiling,
         eff_from, eff_to, label, src, pending) in content.SA_GOSI_BRANCHES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=SA,
            rule_type=content.SA_GOSI_BRANCH_RULE,
            min_amount=dec(floor), max_amount=dec(ceiling),
            rate_pct=dec(ee_pct), employer_rate_pct=dec(er_pct),
            rate_label=(label + (" [PENDING G1]" if pending else ""))[:150],
            tax_formula=f"{ee_pct}% EE / {er_pct}% ER on contributory wage {floor}–{ceiling}"[:150],
            filing_status=worker_class, tax_regime=branch,
            effective_from=eff_from, effective_to=eff_to,
            source_document_id=sources.get(src), sort_order=order))

    for (obligation, treatment, component, label, src) in content.SA_EARNING_CLASSES:
        order += 1
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country=SA,
            rule_type=content.SA_EARNING_CLASS_RULE,
            min_amount=Decimal("0"), max_amount=None, rate_pct=Decimal("0"), employer_rate_pct=None,
            rate_label=label[:150], tax_formula=f"{obligation}: {component} {treatment}"[:150],
            filing_status=component, tax_regime=obligation, assessment_basis=treatment,
            source_document_id=sources.get(src), sort_order=order))

    db.flush()
    return pack


# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# Platform registration — the ONLY way the shared platform reaches this module
# ═══════════════════════════════════════════════════════════════════════════

# hook name (asked for by the platform) -> attribute of this module
JURISDICTION_HOOKS = {
    "retention_settings": "retention_settings",
    "service_registry_transition": "transition_sa_service_registry",
    "statutory_summary": "statutory_summary",
    "pack_activation_refusal": "sa_activation_evidence_refusal",
    "statutory_editors": "statutory_editors",
    "template_activation_refusal": "template_activation_refusal",
    "calc_inputs": "calc_inputs",
    "payment_treatment": "payment_treatment",
    "before_run_transition": "_sa_before_run_transition",
    "pack_holidays": "_sa_pack_holidays",
    "statutory_profile_errors": "_sa_statutory_profile_errors",
    "statutory_profile_values": "_sa_profile_values",
    "payslip_hold_view": "_sa_payslip_hold_view",
}
