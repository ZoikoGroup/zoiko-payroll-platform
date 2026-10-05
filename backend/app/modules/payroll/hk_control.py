"""
modules/payroll/hk_control.py
-----------------------------
Hong Kong platform control records (Super Admin; production-readiness pass).
HK-only; no shared-platform behaviour changes.

* IRD software approval register — whether the IRD has approved Zoiko's
  employer's-return data-file output. Recorded only from the IRD's own
  documents; no internal validation result can set APPROVAL_RECEIVED. Without
  an unexpired approval covering the form, a Zoiko data file is never recorded
  as submitted in ONLINE / MIXED mode (``software_approval_refusal``).
* eMPF integration configuration — versioned statuses and non-secret
  descriptors only; a credential, key or certificate is never stored here.
* Retention policies — the technical framework for D-2 / D-3: every record
  category is BLOCKED_UNDECIDED (no purge) until the owner decision is
  recorded and a period approved by a second Super Admin. The platform never
  picks a period.
* Production readiness center — every launch requirement in one place with
  PASS / FAIL / PENDING / BLOCKED / NOT_APPLICABLE, owner, evidence, next
  action and blocker, re-derived from the database on every read.
"""

import re
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll.models import (
    HkgEmpfConfiguration, HkgIrdSoftwareApproval, HkgRetentionPolicy, SourceArtifact,
)

SPEC = "ZP-HK-ENG-001 production readiness"
IRD_FORMS = ("BIR56A", "IR56B", "IR56E", "IR56F", "IR56G")


# Transaction-scoped advisory-lock keys ("HK" + n) for transitions that INSERT
# rows, which row locks cannot serialize (there may be no row to lock yet).
_LOCK_IRD_SOFTWARE_APPROVAL = 0x484B0001
_LOCK_EMPF_CONFIGURATION = 0x484B0002


def _serialize(db, key: int) -> None:
    """Serialize a short critical section across sessions (PostgreSQL
    pg_advisory_xact_lock; released at commit / rollback). SQLite already
    serializes writers, so nothing is needed there."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


def _audit(db, actor_id, action, entity_type, entity_id, old=None, new=None, reason=None, commit=True):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                     legal_reference=SPEC, old_value=old, new_value=new, reason=reason, auto_commit=commit)


def _iso(value):
    return value.isoformat() if value else None


def _date(value, what):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise BadRequestException(f"{what} must be a date (YYYY-MM-DD)")


IRD_APPROVAL_TAG = "HK-IRD-SOFTWARE-APPROVAL"
EMPF_CERTIFICATION_TAG = "HK-EMPF-CERTIFICATION"


def _reviewed_artifact(db, artifact_id, what, tag) -> SourceArtifact:
    """An uploaded document, filed under its evidence tag (form number), not
    superseded, reviewed by a Super Admin other than its uploader — the same
    evidence rule as the gates. The tag stops an unrelated reviewed document
    (e.g. a gate package) being recorded as an IRD approval or eMPF certification."""
    art = db.get(SourceArtifact, artifact_id) if artifact_id else None
    if art is None:
        raise BadRequestException(f"{what}: the document must be uploaded to Source Evidence first")
    if not (art.form_number or "").startswith(tag):
        raise BadRequestException(f"{what}: upload it to Source Evidence with form / tag {tag}")
    if art.superseded_by_id:
        raise BadRequestException(f"{what}: this document has been superseded — use the current version")
    if not (art.file_path and art.checksum_sha256):
        raise BadRequestException(f"{what}: the document has no stored file / SHA-256")
    if not art.reviewer_id or art.reviewer_id == art.created_by_id:
        raise BadRequestException(f"{what}: the document must be reviewed by a Super Admin other than its uploader")
    return art


# ── IRD software approval register ──────────────────────────────────────

SOFTWARE_TRANSITIONS = {
    "NOT_APPLIED": ("APPLICATION_PREPARED",),
    "APPLICATION_PREPARED": ("APPLICATION_SUBMITTED", "NOT_APPLIED"),
    "APPLICATION_SUBMITTED": ("TEST_DATA_SUBMITTED", "REQUIRES_REAPPLICATION"),
    "TEST_DATA_SUBMITTED": ("APPROVAL_RECEIVED", "REQUIRES_REAPPLICATION"),
    "APPROVAL_RECEIVED": ("APPROVAL_EXPIRED", "APPROVAL_REVOKED"),
    "APPROVAL_EXPIRED": ("REQUIRES_REAPPLICATION",),
    "APPROVAL_REVOKED": ("REQUIRES_REAPPLICATION",),
    "REQUIRES_REAPPLICATION": ("APPLICATION_PREPARED",),
}


def _software_row(db, lock: bool = False) -> Optional[HkgIrdSoftwareApproval]:
    q = db.query(HkgIrdSoftwareApproval).order_by(HkgIrdSoftwareApproval.id.desc())
    return (q.with_for_update() if lock else q).first()


def _effective_software_status(row, on: date) -> str:
    if row is None:
        return "NOT_APPLIED"
    if row.status == "APPROVAL_RECEIVED" and row.expires_on and on > row.expires_on:
        return "APPROVAL_EXPIRED"                                # expiry is never ignored, even before it is recorded
    return row.status


def software_approval(db: Session, on: Optional[date] = None) -> dict:
    on = on or date.today()
    row = _software_row(db)
    status = _effective_software_status(row, on)
    base = {"status": status, "recordedStatus": row.status if row else "NOT_APPLIED", "allowedNext": list(SOFTWARE_TRANSITIONS[
        row.status if row else "NOT_APPLIED"]), "forms": list(IRD_FORMS),
        "dataFileSubmissionPermitted": status == "APPROVAL_RECEIVED",
        "notice": ("Internal validation of the IRD payload is NOT IRD approval. ONLINE / MIXED mode submission of a "
                   "Zoiko data file is refused until the IRD's approval is recorded here from its own letter.")}
    if row is None:
        return {**base, "id": None}
    return {**base, "id": row.id, "formsCovered": row.forms_covered or [], "specificationVersion": row.specification_version,
            "applicationReference": row.application_reference, "applicationSubmittedOn": _iso(row.application_submitted_on),
            "testDataSubmittedOn": _iso(row.test_data_submitted_on), "approvalReference": row.approval_reference,
            "approvalReceivedOn": _iso(row.approval_received_on), "expiresOn": _iso(row.expires_on),
            "approvalDocumentId": row.approval_document_id, "documentSha256": row.document_sha256,
            "reviewerId": row.reviewer_id, "notes": row.notes, "createdById": row.created_by_id}


def transition_software_approval(db: Session, target: str, data: dict, actor_id: Optional[int]) -> dict:
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequestException("a reason is required")
    _serialize(db, _LOCK_IRD_SOFTWARE_APPROVAL)               # incl. the row-inserting (re)application
    row = _software_row(db, lock=True)
    current = row.status if row else "NOT_APPLIED"
    if target not in SOFTWARE_TRANSITIONS.get(current, ()):
        raise BadRequestException(f"the IRD software approval cannot move from {current} to {target}")
    old = software_approval(db)
    if target == "APPLICATION_PREPARED":
        forms = data.get("formsCovered") or []
        if not forms or any(f not in IRD_FORMS for f in forms):
            raise BadRequestException("formsCovered must list the forms applied for: " + ", ".join(IRD_FORMS))
        if not data.get("specificationVersion"):
            raise BadRequestException("the IRD specification version the output follows is required")
        # a (re)application starts a new register row; the history stays intact
        row = HkgIrdSoftwareApproval(status=target, forms_covered=sorted(set(forms)),
                                     specification_version=data["specificationVersion"], created_by_id=actor_id)
        db.add(row)
    elif target == "NOT_APPLIED":
        row.status = target
    elif target == "APPLICATION_SUBMITTED":
        if not data.get("applicationReference"):
            raise BadRequestException("the IRD application reference is required")
        row.application_reference = data["applicationReference"]
        row.application_submitted_on = _date(data.get("applicationSubmittedOn"), "applicationSubmittedOn") or date.today()
        row.status = target
    elif target == "TEST_DATA_SUBMITTED":
        row.test_data_submitted_on = _date(data.get("testDataSubmittedOn"), "testDataSubmittedOn") or date.today()
        row.status = target
    elif target == "APPROVAL_RECEIVED":
        if not data.get("approvalReference"):
            raise BadRequestException("the IRD approval reference (from the IRD's approval letter) is required")
        art = _reviewed_artifact(db, data.get("approvalDocumentId"), "IRD approval letter", IRD_APPROVAL_TAG)
        received = _date(data.get("approvalReceivedOn"), "approvalReceivedOn")
        if not received or received > date.today():
            raise BadRequestException("approvalReceivedOn is required and cannot be in the future")
        expires = _date(data.get("expiresOn"), "expiresOn")
        if expires and expires < received:
            raise BadRequestException("expiresOn cannot be before approvalReceivedOn")
        if actor_id is not None and actor_id == row.created_by_id:
            raise BadRequestException("the approval must be recorded by a Super Admin other than the one who prepared the application")
        row.approval_reference, row.approval_received_on, row.expires_on = data["approvalReference"], received, expires
        row.approval_document_id, row.document_sha256, row.reviewer_id = art.id, art.checksum_sha256, actor_id
        row.status = target
    else:                                                       # APPROVAL_EXPIRED / APPROVAL_REVOKED / REQUIRES_REAPPLICATION
        row.status = target
    if data.get("notes"):
        row.notes = data["notes"]
    db.flush()
    _audit(db, actor_id, "status_change", "hkg_ird_software_approval", row.id, old={"status": old["status"]},
           new={"status": target, "formsCovered": row.forms_covered, "approvalReference": row.approval_reference,
                "documentSha256": row.document_sha256, "expiresOn": _iso(row.expires_on)}, reason=reason)
    return software_approval(db)


def software_approval_refusal(db: Session, form_type: str, on: date) -> Optional[str]:
    """None when a Zoiko data file for ``form_type`` may be recorded as
    submitted on ``on`` (ONLINE / MIXED mode); otherwise the reason it may not."""
    row = _software_row(db)
    status = _effective_software_status(row, on)
    if status != "APPROVAL_RECEIVED":
        return (f"IRD software approval is {status}: a Zoiko data file cannot be recorded as submitted in ONLINE / "
                "MIXED mode. If the employer filed through its own channel, record INTERNAL_PREPARATION_ONLY.")
    if form_type not in (row.forms_covered or []):
        return f"the IRD software approval does not cover {form_type}"
    return None


# ── eMPF integration configuration ──────────────────────────────────────

EMPF_METHODS = ("EMPF_PORTAL_MANUAL", "EMPF_FILE_UPLOAD", "EMPF_API")
EMPF_ENVIRONMENTS = ("NOT_CONFIGURED", "TEST", "PRODUCTION")
EMPF_SECRET_STATUSES = ("NOT_CONFIGURED", "CONFIGURED_IN_SECRET_STORE")
_SECRETISH = re.compile(r"(://[^/\s]*:[^/\s]*@)|(password|passwd|secret|token|apikey|api_key|private[_ ]key|BEGIN )", re.I)


def empf_configurations(db: Session) -> dict:
    rows = db.query(HkgEmpfConfiguration).order_by(HkgEmpfConfiguration.version.desc()).all()
    active = next((r for r in rows if r.status == "ACTIVE"), None)
    return {"active": _empf_view(active) if active else None, "versions": [_empf_view(r) for r in rows],
            "methods": list(EMPF_METHODS), "environments": list(EMPF_ENVIRONMENTS),
            "secretStatuses": list(EMPF_SECRET_STATUSES),
            "notice": ("Statuses only — credentials, keys and certificates are held in the deployment secret store, "
                       "never here. Zoiko holds no certified eMPF interface (G2): every submission is made by the "
                       "employer through eMPF itself and recorded from its evidence.")}


def _empf_view(r: HkgEmpfConfiguration) -> dict:
    return {"id": r.id, "version": r.version, "status": r.status, "submissionMethod": r.submission_method,
            "fileFormat": r.file_format, "formatVersion": r.format_version, "environment": r.environment,
            "endpointReference": r.endpoint_reference, "credentialStatus": r.credential_status,
            "certificateStatus": r.certificate_status, "certificationStatus": r.certification_status,
            "certificationEvidenceId": r.certification_evidence_id, "reason": r.reason,
            "createdById": r.created_by_id, "approvedById": r.approved_by_id, "activatedAt": _iso(r.activated_at)}


def create_empf_configuration(db: Session, data: dict, actor_id: Optional[int]) -> dict:
    if not (data.get("reason") or "").strip():
        raise BadRequestException("a reason is required")
    method, env = data.get("submissionMethod"), data.get("environment")
    if method not in EMPF_METHODS:
        raise BadRequestException("submissionMethod must be one of " + ", ".join(EMPF_METHODS))
    if env not in EMPF_ENVIRONMENTS:
        raise BadRequestException("environment must be one of " + ", ".join(EMPF_ENVIRONMENTS))
    for k in ("credentialStatus", "certificateStatus"):
        if data.get(k, "NOT_CONFIGURED") not in EMPF_SECRET_STATUSES:
            raise BadRequestException(f"{k} must be one of " + ", ".join(EMPF_SECRET_STATUSES))
    for k in ("endpointReference", "fileFormat", "formatVersion", "reason"):
        if data.get(k) and _SECRETISH.search(str(data[k])):
            raise BadRequestException(f"{k} looks like it contains a secret — secrets are never stored in configuration")
    certification, evidence_id = "NOT_CERTIFIED", None
    if data.get("certificationEvidenceId"):
        art = _reviewed_artifact(db, data["certificationEvidenceId"], "eMPF certification evidence", EMPF_CERTIFICATION_TAG)
        certification, evidence_id = "CERTIFIED", art.id
    if method != "EMPF_PORTAL_MANUAL" and env == "PRODUCTION" and certification != "CERTIFIED":
        raise BadRequestException("an automated eMPF method in PRODUCTION needs reviewed eMPF certification evidence (G2)")
    _serialize(db, _LOCK_EMPF_CONFIGURATION)                  # next version number: no duplicate under concurrency
    last = db.query(HkgEmpfConfiguration).order_by(HkgEmpfConfiguration.version.desc()).first()
    row = HkgEmpfConfiguration(version=(last.version + 1) if last else 1, status="DRAFT", submission_method=method,
                               file_format=data.get("fileFormat"), format_version=data.get("formatVersion"),
                               environment=env, endpoint_reference=data.get("endpointReference"),
                               credential_status=data.get("credentialStatus", "NOT_CONFIGURED"),
                               certificate_status=data.get("certificateStatus", "NOT_CONFIGURED"),
                               certification_status=certification, certification_evidence_id=evidence_id,
                               reason=data["reason"].strip(), created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "create", "hkg_empf_configuration", row.id, new=_empf_view(row), reason=row.reason)
    return _empf_view(row)


def activate_empf_configuration(db: Session, config_id: int, actor_id: Optional[int], reason: str) -> dict:
    # lock every version (id order) so two concurrent activations cannot both end ACTIVE
    db.query(HkgEmpfConfiguration).order_by(HkgEmpfConfiguration.id).with_for_update().all()
    row = db.get(HkgEmpfConfiguration, config_id)
    if row is None:
        raise NotFoundException("eMPF configuration not found")
    if row.status != "DRAFT":
        raise BadRequestException(f"only a DRAFT configuration can be activated (this one is {row.status})")
    if not (reason or "").strip():
        raise BadRequestException("a reason is required")
    if actor_id is None or actor_id == row.created_by_id:
        raise BadRequestException("the configuration must be activated by a Super Admin other than its maker")
    for prev in db.query(HkgEmpfConfiguration).filter(HkgEmpfConfiguration.status == "ACTIVE"):
        prev.status = "SUPERSEDED"
    row.status, row.approved_by_id, row.activated_at = "ACTIVE", actor_id, datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "activate", "hkg_empf_configuration", row.id, old={"status": "DRAFT"},
           new={"status": "ACTIVE", "version": row.version}, reason=reason)
    return _empf_view(row)


# ── retention policies (D-2 / D-3 technical framework) ──────────────────

RETENTION_CATEGORIES = (
    ("PAYROLL_RECORDS", "Payroll runs, payslips and calculation traces"),
    ("MPF_RECORDS", "MPF contribution records and eMPF submissions"),
    ("IRD_RETURNS", "IRD returns and notifications (BIR56A / IR56B / E / F / G)"),
    ("TERMINATION_RECORDS", "Termination statements, SP / LSP and average-wage snapshots"),
    ("EMPLOYEE_IDENTITY", "HKID / passport and statutory profile data"),
    ("WORK_HOURS", "Hours-worked records (minimum wage)"),
    ("ACCESS_LOGS", "HK access events and download logs"),
    ("CORRECTIONS", "Payslip corrections and their evidence"),
)


def _decision_state(db, key) -> str:
    from app.modules.payroll import hk_governance

    return next((d["state"] for d in hk_governance.owner_decisions(db) if d["key"] == key), "OPEN")


def retention_policies(db: Session) -> dict:
    d2, d3 = _decision_state(db, "D-2"), _decision_state(db, "D-3")
    out = []
    for key, label in RETENTION_CATEGORIES:
        rows = (db.query(HkgRetentionPolicy).filter(HkgRetentionPolicy.record_category == key)
                .order_by(HkgRetentionPolicy.id.desc()).all())
        approved = next((r for r in rows if r.status == "APPROVED"), None)
        draft = next((r for r in rows if r.status == "DRAFT"), None)
        state = "APPROVED" if approved else "BLOCKED_UNDECIDED"
        out.append({"category": key, "label": label, "state": state, "purgePermitted": approved is not None,
                    "retentionYears": approved.retention_years if approved else None,
                    "endOfRetention": approved.end_of_retention if approved else None,
                    "legalBasis": approved.legal_basis if approved else None,
                    "approved": _policy_view(approved) if approved else None,
                    "draft": _policy_view(draft) if draft else None,
                    "blocker": None if approved else (
                        "owner decision D-2 (retention period) is not recorded" if d2 != "RECORDED" else
                        "no approved retention period for this category")})
    return {"decisions": {"D-2": d2, "D-3": d3}, "categories": out,
            "notice": ("No retention period is chosen by the platform. Until a period is approved for a category, "
                       "nothing in it may be purged; legal holds always prevail.")}


def _policy_view(r) -> dict:
    return {"id": r.id, "status": r.status, "retentionYears": r.retention_years, "endOfRetention": r.end_of_retention,
            "legalBasis": r.legal_basis, "decisionReference": r.decision_reference, "reason": r.reason,
            "createdById": r.created_by_id, "approvedById": r.approved_by_id, "approvedAt": _iso(r.approved_at)}


def propose_retention_policy(db: Session, data: dict, actor_id: Optional[int]) -> dict:
    category = data.get("recordCategory")
    if category not in dict(RETENTION_CATEGORIES):
        raise BadRequestException("unknown record category")
    if _decision_state(db, "D-2") != "RECORDED":
        raise BadRequestException("blocked: owner decision D-2 (retention period per data category) is not recorded — "
                                  "the period is a legal decision, never guessed by the platform")
    years = data.get("retentionYears")
    if not isinstance(years, int) or years < 1:
        raise BadRequestException("retentionYears must be a whole number of years taken from the D-2 decision")
    end = data.get("endOfRetention")
    if end not in ("DELETE", "ANONYMISE"):
        raise BadRequestException("endOfRetention must be DELETE or ANONYMISE (owner decision D-3)")
    if _decision_state(db, "D-3") != "RECORDED":
        raise BadRequestException("blocked: owner decision D-3 (deletion vs anonymisation) is not recorded")
    if not (data.get("legalBasis") or "").strip() or not (data.get("reason") or "").strip():
        raise BadRequestException("legalBasis and reason are required")
    row = HkgRetentionPolicy(record_category=category, status="DRAFT", retention_years=years, end_of_retention=end,
                             legal_basis=data["legalBasis"].strip(), decision_reference="HK-DECISION-D-2",
                             reason=data["reason"].strip(), created_by_id=actor_id)
    db.add(row)
    db.flush()
    _audit(db, actor_id, "create", "hkg_retention_policy", row.id, new=_policy_view(row), reason=row.reason)
    return _policy_view(row)


def approve_retention_policy(db: Session, policy_id: int, actor_id: Optional[int]) -> dict:
    row = db.get(HkgRetentionPolicy, policy_id)
    if row is None:
        raise NotFoundException("retention policy not found")
    # lock the category's policies so two concurrent approvals cannot both end APPROVED
    db.query(HkgRetentionPolicy).filter(HkgRetentionPolicy.record_category == row.record_category)         .order_by(HkgRetentionPolicy.id).with_for_update().all()
    db.refresh(row)
    if row.status != "DRAFT":
        raise BadRequestException(f"only a DRAFT policy can be approved (this one is {row.status})")
    if actor_id is None or actor_id == row.created_by_id:
        raise BadRequestException("a retention policy must be approved by a Super Admin other than its maker")
    for prev in db.query(HkgRetentionPolicy).filter(HkgRetentionPolicy.record_category == row.record_category,
                                                    HkgRetentionPolicy.status == "APPROVED"):
        prev.status = "SUPERSEDED"
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, datetime.utcnow()
    db.flush()
    _audit(db, actor_id, "approve", "hkg_retention_policy", row.id, old={"status": "DRAFT"},
           new={"status": "APPROVED", "category": row.record_category, "years": row.retention_years}, reason=row.reason)
    return _policy_view(row)


def purge_refusal(db: Session, category: str) -> Optional[str]:
    """The guard any HK purge must call first: None only when the category has
    an approved retention period."""
    entry = next((c for c in retention_policies(db)["categories"] if c["category"] == category), None)
    if entry is None:
        return "unknown record category"
    return None if entry["purgePermitted"] else f"purge refused: {entry['blocker']}"



# ── monitoring signals ──────────────────────────────────────────────────

def monitoring_signals(db: Session, as_of: Optional[date] = None) -> dict:
    """Platform-wide HK operational signals for monitoring / alerting — COUNTS
    only (no employee data). An alert rule fires when a signal with a
    threshold is above it; wiring these into the deployment's alerting is the
    PROD_MONITORING production procedure."""
    from datetime import timedelta

    from app.modules.payroll.models import (
        HkgEmpfSubmission, HkgIrdReportingCase, HkgLegalHold, HkgPayslipCorrection, HkgTaxClearanceHold,
    )

    as_of = as_of or date.today()
    open_ird = ("DUE", "PREPARED", "VALIDATED")
    ird = db.query(HkgIrdReportingCase).filter(HkgIrdReportingCase.status.in_(open_ird))
    signals = [
        ("IRD_OVERDUE", "IRD returns / notifications past their due date and not filed",
         ird.filter(HkgIrdReportingCase.due_date < as_of).count(), 0),
        ("IRD_DUE_30_DAYS", "IRD returns / notifications due within 30 days and not filed",
         ird.filter(HkgIrdReportingCase.due_date >= as_of, HkgIrdReportingCase.due_date <= as_of + timedelta(days=30)).count(), None),
        ("IRD_REJECTED", "IRD submissions recorded as rejected (awaiting re-preparation)",
         db.query(HkgIrdReportingCase).filter(HkgIrdReportingCase.status == "REJECTED").count(), 0),
        ("EMPF_PAST_CONTRIBUTION_DAY", "eMPF remittances not submitted after their contribution day",
         db.query(HkgEmpfSubmission).filter(HkgEmpfSubmission.status.in_(("PREPARED", "VALIDATED")),
                                            HkgEmpfSubmission.contribution_day < as_of).count(), 0),
        ("EMPF_REJECTED_OR_PARTIAL", "eMPF remittances rejected or partially accepted",
         db.query(HkgEmpfSubmission).filter(HkgEmpfSubmission.status.in_(("REJECTED", "PARTIAL"))).count(), 0),
        ("IR56G_DEADLINE_PASSED", "IR56G departure cases past their filing deadline and not filed",
         db.query(HkgTaxClearanceHold).filter(HkgTaxClearanceHold.state.in_(("DEPARTURE_IDENTIFIED", "IR56G_DUE")),
                                              HkgTaxClearanceHold.filing_deadline < as_of).count(), 0),
        ("IR56G_HOLDS_ACTIVE", "IR56G tax-clearance holds active (money held)",
         db.query(HkgTaxClearanceHold).filter(HkgTaxClearanceHold.state == "IR56G_FILED_HOLD_ACTIVE").count(), None),
        ("CORRECTIONS_AWAITING_APPROVAL", "payslip corrections awaiting a second approver",
         db.query(HkgPayslipCorrection).filter(HkgPayslipCorrection.status == "REQUESTED").count(), None),
        ("LEGAL_HOLDS_ACTIVE", "legal holds active (deletion blocked)",
         db.query(HkgLegalHold).filter(HkgLegalHold.status == "ACTIVE").count(), None),
    ]
    row = _software_row(db)
    expiring = bool(row and row.status == "APPROVAL_RECEIVED" and row.expires_on
                    and as_of <= row.expires_on <= as_of + timedelta(days=60))
    signals.append(("IRD_SOFTWARE_APPROVAL_EXPIRING", "IRD software approval expires within 60 days", int(expiring), 0))
    out = [{"key": k, "label": label, "value": v, "threshold": t, "alert": t is not None and v > t}
           for k, label, v, t in signals]
    return {"asOf": as_of.isoformat(), "signals": out, "alerts": sum(1 for x in out if x["alert"]),
            "notice": "Counts only. Alert delivery (paging / e-mail) is wired by the deployment — production procedure PROD_MONITORING."}


# ── production readiness center ─────────────────────────────────────────

GATE_OWNERS = {"G1": "HK payroll / statutory specialist", "G2": "IRD / eMPF (external) + engineering",
               "G3": "Payroll operations (parallel run)", "G4": "Engineering (technical certification)",
               "G5": "Security + privacy counsel", "G6": "Operations", "G7": "Product owner (launch authority)"}
PRODUCTION_PROCEDURES = (
    ("PROD_DB", "Production database migrated to the HK head and drift-checked", "Platform engineering"),
    ("PROD_SECRETS", "HK identity-token secret provisioned in the secret store (D-5)", "Platform engineering"),
    ("PROD_DEPLOY", "HK release deployed and the running revision verified", "Platform engineering"),
    ("PROD_BACKUP_RESTORE", "Backup taken and a restore rehearsal completed on a production snapshot", "Operations"),
    ("PROD_MONITORING", "HK monitoring signals and alerts wired (calculation blocks, filing deadlines, eMPF)", "Operations"),
)


def readiness_center(db: Session, as_of: Optional[date] = None) -> dict:
    from app.modules.payroll import hk_governance

    as_of = as_of or date.today()
    readiness = hk_governance.activation_readiness(db, as_of)
    items = []

    def add(category, key, label, status, owner, evidence, next_action, blocker=None, due=None):
        items.append({"category": category, "key": key, "item": label, "status": status, "owner": owner,
                      "evidence": evidence, "nextAction": next_action, "dueDate": due,
                      "blockerReason": blocker if status in ("FAIL", "BLOCKED", "PENDING") else None})

    for r in readiness["requirements"]:
        k = r["key"]
        if k.startswith("GATE_"):
            g = k[5:]
            status = "PASS" if r["met"] else ("PENDING" if r["detail"] == "SUBMITTED" else "BLOCKED")
            add("Certification gates", k, r["label"], status, GATE_OWNERS[g], f"HK-GATE-{g} ({r['detail']})",
                "none" if r["met"] else f"upload the {g} evidence package and have a second Super Admin review it",
                None if r["met"] else f"{g} evidence not accepted — external / owner action required")
        elif k.startswith("TEMPLATE_"):
            add("Report templates", k, r["label"], "PASS" if r["met"] else "FAIL", "Compliance (Super Admin)",
                r["detail"], "none" if r["met"] else "attach reviewed source evidence; approve and activate (four-eyes)",
                None if r["met"] else r["detail"])
        else:
            add("Statutory configuration" if k in ("ACTIVE_PACK", "GOLDEN") else "Production verification", k, r["label"],
                "PASS" if r["met"] else "FAIL" if k in ("ACTIVE_PACK", "GOLDEN") else "BLOCKED",
                "Compliance (Super Admin)" if k in ("ACTIVE_PACK", "GOLDEN") else "Operations", r["detail"],
                "none" if r["met"] else "see the activation runbook", None if r["met"] else r["detail"])
    # The activation guard refuses any pack with a value that is not SOURCED;
    # show the same count here so the blocker is visible before an attempt.
    from app.modules.payroll import hk_configuration

    pending, open_versions = 0, []
    for v in hk_configuration.versions(db, as_of):
        if v["versionState"] in ("SUPERSEDED", "RETIRED", "PAST_ACTIVE"):
            continue
        cfg = hk_configuration.domains(db, v["id"])
        n = sum(1 for d in cfg["domains"] for r in d["rows"] if r["status"] != "SOURCED") + len(cfg["unmapped"])
        pending += n
        open_versions.append(f"{v['packId']} v{v['version']}: {n}")
    add("Statutory configuration", "VALUES_SOURCE_VERIFIED",
        "every value of each open version is source-verified (no UNVERIFIED — G1 / SOURCE_HASH_REQUIRED)",
        "PASS" if pending == 0 else "BLOCKED", "HK specialist (G1) + Compliance (Super Admin)",
        "; ".join(open_versions) or "no open version",
        "none" if pending == 0 else "record each specialist confirmation with a reviewed, hashed source (governed edit, Draft version)",
        None if pending == 0 else f"{pending} value(s) not source-verified — activation is refused")
    sw = software_approval(db, as_of)
    add("IRD", "IRD_SOFTWARE_APPROVAL", "IRD software approval for the employer's-return data file",
        "PASS" if sw["status"] == "APPROVAL_RECEIVED" else "BLOCKED", "Engineering + IRD (external)",
        sw.get("approvalReference") or sw["status"],
        "none" if sw["status"] == "APPROVAL_RECEIVED" else "apply to the IRD with the specification and test data (G2)",
        None if sw["status"] == "APPROVAL_RECEIVED" else
        f"{sw['status']} — until approved, returns can only be recorded as INTERNAL_PREPARATION_ONLY")
    empf = empf_configurations(db)["active"]
    if empf is None:
        add("eMPF", "EMPF_CONFIGURATION", "eMPF integration configuration (active version)", "PENDING",
            "Operations", "none", "create and activate the eMPF configuration (maker + approver)",
            "no active eMPF configuration")
    else:
        add("eMPF", "EMPF_CONFIGURATION", "eMPF integration configuration (active version)", "PASS", "Operations",
            f"v{empf['version']} {empf['submissionMethod']} / {empf['environment']}", "none")
    certified = bool(empf and empf["certificationStatus"] == "CERTIFIED")
    manual = bool(empf and empf["submissionMethod"] == "EMPF_PORTAL_MANUAL")
    add("eMPF", "EMPF_CERTIFICATION", "eMPF interface certification",
        "PASS" if certified else "NOT_APPLICABLE" if manual else "BLOCKED", "eMPF (external) + engineering",
        "certified" if certified else "manual portal submission — no interface to certify" if manual else "NOT_CERTIFIED",
        "none" if certified or manual else "decide D-1, then complete eMPF onboarding (G2)",
        None if certified or manual else "no certified eMPF interface")
    for d in hk_governance.owner_decisions(db):
        status = "PASS" if d["state"] == "RECORDED" else "PENDING" if d["state"] == "SUBMITTED" else (
            "BLOCKED" if d["blocksLaunch"] else "NOT_APPLICABLE")
        add("Owner decisions", f"DECISION_{d['key']}", f"{d['key']} {d['label']}", status, "Product owner",
            d["evidenceTag"], "none" if status in ("PASS", "NOT_APPLICABLE") else "record the decision document and its review",
            None if status in ("PASS", "NOT_APPLICABLE") else f"{d['key']} {d['state']}")
    ret = retention_policies(db)
    approved = sum(1 for c in ret["categories"] if c["state"] == "APPROVED")
    add("Privacy (PDPO)", "RETENTION", f"Retention periods approved ({approved}/{len(ret['categories'])} categories)",
        "PASS" if approved == len(ret["categories"]) else "BLOCKED", "Privacy counsel + product owner",
        f"D-2 {ret['decisions']['D-2']}, D-3 {ret['decisions']['D-3']}",
        "record D-2 / D-3, then propose and approve each category",
        None if approved == len(ret["categories"]) else "retention undecided — purge blocked")
    prod_ok = next((r["met"] for r in readiness["requirements"] if r["key"] == "PRODUCTION_VERIFICATION"), False)
    for key, label, owner in PRODUCTION_PROCEDURES:
        add("Production procedures", key, label, "PASS" if prod_ok else "PENDING", owner,
            hk_governance.PRODUCTION_EVIDENCE_TAG, "none" if prod_ok else "perform it and record it in the production-verification evidence",
            None if prod_ok else "no production evidence recorded")
    counts = {s: sum(1 for i in items if i["status"] == s) for s in ("PASS", "FAIL", "PENDING", "BLOCKED", "NOT_APPLICABLE")}
    ready = counts["FAIL"] == counts["PENDING"] == counts["BLOCKED"] == 0
    return {"asOf": as_of.isoformat(), "registry": readiness["registry"], "counts": counts, "total": len(items),
            "productionReady": ready, "items": items,
            "classification": "PRODUCTION READY" if ready else "NOT PRODUCTION READY — see BLOCKED / FAIL / PENDING items"}
