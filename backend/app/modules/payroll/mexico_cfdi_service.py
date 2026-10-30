"""
modules/payroll/mexico_cfdi_service.py
--------------------------------------
Mexico CFDI 4.0 + Nómina 1.2 lifecycle (ZP-MX-ENG-001 Phase 7,
docs/mexico/MEXICO_PHASE_7_PLAN.md): preconditions (§2), generation through the
builder / signer seams (both refuse in production), durable XML storage via
app/core/object_storage with its production refusal of the /tmp fallback (D4),
the state machine with an append-only event per transition (§4), the outbox
(§5.3), the UNKNOWN rule (§4.2 revised: same payload + same idempotency key on
retry; no automatic retry; operator confirmation recorded), cancellation /
substitution lineage from the catalog (§4.3), and the reset rule (§6).

MX-016: only a committed run's payslips are stamped. MX-017 / MX-041: a stamp is
a fiscal-document state only — nothing here touches payroll, authority or bank
state. MX-061: XML never in the DB or logs.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import mexico_cfdi_builder as _builder
from app.modules.payroll import mexico_pac as _pac
from app.modules.payroll.engine.countries.mexico import MXBlock, MXRefuse

MX = "MX"
STATUSES = ("GENERATED", "SIGNED", "SUBMITTED", "STAMPED", "REJECTED", "UNKNOWN", "CANCEL_REQUESTED", "CANCELLED",
            "REPLACED", "VOIDED")
_TRANSITIONS = {
    "GENERATED": {"SIGNED", "VOIDED"},
    "SIGNED": {"SUBMITTED", "VOIDED", "STAMPED"},        # STAMPED only by a late FOUND before a retry is sent
    "SUBMITTED": {"STAMPED", "REJECTED", "UNKNOWN"},
    "UNKNOWN": {"STAMPED", "REJECTED", "SIGNED", "CANCEL_REQUESTED", "CANCELLED"},
    "STAMPED": {"CANCEL_REQUESTED", "UNKNOWN"},           # UNKNOWN only on a UUID conflict
    "CANCEL_REQUESTED": {"CANCELLED", "STAMPED", "UNKNOWN"},
    "CANCELLED": {"REPLACED"},
}
# Documents a downstream lifecycle has acted on — they refuse a run reset (D2).
ACTED = ("SUBMITTED", "UNKNOWN", "STAMPED", "CANCEL_REQUESTED", "CANCELLED", "REPLACED")
LIVE = ("GENERATED", "SIGNED", "SUBMITTED", "STAMPED", "UNKNOWN", "CANCEL_REQUESTED")
CANCEL_REASON_CATALOG = "c_MotivoCancelacion"


def _now():
    return datetime.now(timezone.utc)


def _models():
    from app.modules.payroll import models as m

    return m


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── events + transitions ────────────────────────────────────────────────────

def _event(db: Session, doc, event_type: str, actor_id=None, detail=None, from_status=None, to_status=None):
    m = _models()
    db.add(m.PayrollMxCfdiEvent(document_id=doc.id, event_type=event_type, from_status=from_status,
                                to_status=to_status, payload_hash=doc.payload_hash, detail=detail, actor_id=actor_id))


def _transition(db: Session, doc, to: str, event_type: str, actor_id=None, detail=None):
    frm = doc.status
    if to not in _TRANSITIONS.get(frm, set()):
        raise MXRefuse("MX_CFDI_ILLEGAL_TRANSITION", f"a CFDI document cannot go from {frm} to {to}",
                      doc.organization_id)
    doc.status = to
    if to == "UNKNOWN":
        doc.unknown_since = _now()
    elif frm == "UNKNOWN":
        doc.unknown_action, doc.unknown_since = None, None
    _event(db, doc, event_type, actor_id, detail, frm, to)


# ── preconditions (§2) ──────────────────────────────────────────────────────

def _active_release(db: Session):
    m = _models()
    return (db.query(m.PayrollMxCfdiSchemaRelease).filter(m.PayrollMxCfdiSchemaRelease.status == "Active")
            .order_by(m.PayrollMxCfdiSchemaRelease.id.desc()).first())


def _employer_for(db: Session, item, on):
    """(employer profile version in force, root id, CSD credential) for a
    Mexican payslip — via the employee's IMSS registration."""
    from app.modules.payroll import mexico_employee_service, mexico_employer_service

    m = _models()
    prof = mexico_employee_service._profile_on(db, item.employee_id, on)
    reg = db.get(m.PayrollMxImssRegistration, prof.mx_imss_registration_id) if prof and prof.mx_imss_registration_id else None
    if reg is None:
        return None, None, None
    root = reg.employer_profile_id
    version = mexico_employer_service.version_in_force(db, root, on)
    cred = (db.query(m.PayrollMxCredentialRef)
            .filter(m.PayrollMxCredentialRef.employer_profile_id == root, m.PayrollMxCredentialRef.kind == "CSD",
                    m.PayrollMxCredentialRef.status == "ACTIVE").order_by(m.PayrollMxCredentialRef.id.desc()).first())
    return version, root, cred


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run_guard(db: Session, run) -> None:
    from app.modules.payroll import mexico_dormancy, mexico_run_service

    if not mexico_dormancy.onboarding_enabled(db, run.organization_id):
        raise MXRefuse("MX_DORMANT", mexico_dormancy.DORMANT_MESSAGE, run.organization_id)
    if not mexico_run_service._org_runs_mexico(db, run.organization_id):
        raise MXRefuse("MX_ORG_NOT_MEXICAN", "Mexico is not one of the organisation's payroll countries", run.organization_id)


def preflight(db: Session, run) -> dict:
    """Every reason a CFDI cannot be generated for this run, without raising."""
    from app.modules.payroll import mexico_run_service

    run_guard(db, run)
    reasons = []
    fp = run.mx_approval_fingerprint or {}
    if run.status != "Approved" or not fp.get("committedAt"):
        reasons.append(("MX_CFDI_RUN_NOT_COMMITTED", "only a committed (Approved) Mexican run can be stamped (MX-016)"))
    elif mexico_run_service.approval_drift(db, run):
        reasons.append(("MX_APPROVAL_INVALIDATED", "the run's approval no longer matches its inputs — reset and "
                                                   "re-approve before stamping"))
    release = _active_release(db)
    if release is None:
        reasons.append(("MX_CFDI_NO_ACTIVE_SCHEMA_RELEASE", "no Active CFDI 4.0 / Nómina 1.2 schema release (Phase 2)"))
    items = mexico_run_service._mx_items(db, run)
    for item in items:
        snap = item.mx_calculation_snapshot or {}
        if snap.get("blocked") or not snap.get("inputHash"):
            reasons.append(("MX_CFDI_PAYSLIP_NOT_CALCULATED", f"payslip {item.id} has no Mexican calculation"))
            continue
        version, _root, cred = _employer_for(db, item, run.pay_date)
        if version is None:
            reasons.append(("MX_CFDI_EMPLOYER_MISSING", f"payslip {item.id}: no employer / IMSS registration"))
            continue
        if cred is None or (_aware(cred.valid_to) and _aware(cred.valid_to) <= _now()):
            reasons.append(("MX_CFDI_CSD_UNAVAILABLE", f"payslip {item.id}: no ACTIVE, unexpired CSD credential"))
        if not version.pac_provider or not version.pac_environment:
            reasons.append(("MX_CFDI_PAC_NOT_SET", f"payslip {item.id}: the employer has no PAC provider / environment"))
        elif version.pac_environment == "PRODUCTION" and version.stamp_test_status != "PASSED":
            reasons.append(("MX_CFDI_STAMP_TEST_REQUIRED", f"payslip {item.id}: PRODUCTION stamping needs a passed "
                                                           "sandbox stamp test (D7)"))
    seen, unique = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return {"runId": run.id, "ready": not unique, "reasons": [{"code": c, "message": t} for c, t in unique]}


# ── generation (builder / signer seams, durable storage) ────────────────────

def _next_folio(db: Session, org_id: int) -> str:
    m = _models()
    folios = [d.folio for d in db.query(m.PayrollMxCfdiDocument).filter(m.PayrollMxCfdiDocument.organization_id == org_id)]
    nums = [int(f) for f in folios if f and f.isdigit()]
    return str((max(nums) if nums else 0) + 1)


def _live_doc(db: Session, item_id: int):
    m = _models()
    return (db.query(m.PayrollMxCfdiDocument)
            .filter(m.PayrollMxCfdiDocument.payslip_item_id == item_id, m.PayrollMxCfdiDocument.status.in_(LIVE)).first())


def _generate_one(db: Session, run, item, release, actor_id, replaces=None):
    from app.core import object_storage

    from app.modules.payroll import mexico_dormancy, mexico_pilot_service

    m = _models()
    version, _root, _cred = _employer_for(db, item, run.pay_date)
    mexico_pilot_service.refuse_non_sandbox_pac(db, run.organization_id, version.pac_environment)   # Phase 10e
    pilot = mexico_dormancy.is_pilot_organization(db, run.organization_id)
    refusal = object_storage.durable_storage_refusal("Mexico CFDI XML storage")
    if refusal:
        raise MXRefuse("MX_CFDI_STORAGE_NOT_DURABLE", refusal, run.organization_id)
    folio = _next_folio(db, run.organization_id)        # Phase 11b: the receipt carries its Folio
    base = {"payslipItemId": item.id, "employeeId": item.employee_id, "runId": run.id,
            "payDate": run.pay_date.isoformat(), "periodStart": run.period_start.isoformat(),
            "periodEnd": run.period_end.isoformat(), "result": (item.mx_calculation_snapshot or {}).get("result"),
            "schemaRelease": {"id": release.id, "cfdi": release.cfdi_version, "nomina": release.complement_version},
            "replacesUuid": getattr(replaces, "uuid", None), "folio": folio, "issuedAtUtc": _now()}
    builder = _builder.active_builder()
    document_input = builder.prepare(db, run, item, release, base)
    payload = builder.build(document_input)
    del document_input                                  # MX-061: identifiers never outlive the build
    signed, cert_no = _builder.active_signer().sign(payload, _pac.CredentialHandle(getattr(_cred, "id", None), "CSD",
                                                                                   getattr(_cred, "fingerprint_sha256", None)))
    payload_hash = _sha(signed)
    # One key per DOCUMENT (folio is unique per organisation): every retry of
    # this document reuses it; a new document (e.g. after a rejection) gets its own.
    key = "mxcfdi-" + _sha(f"{run.organization_id}:{item.id}:{folio}:{payload_hash}".encode())[:56]
    ref = object_storage.save_upload(subdir=f"mx_cfdi/{run.organization_id}/{run.id}", filename=f"{folio}.xml",
                                     data=signed)
    doc = m.PayrollMxCfdiDocument(
        organization_id=run.organization_id, payroll_run_id=run.id, payslip_item_id=item.id,
        employee_id=item.employee_id, series=None, folio=folio, schema_release_id=release.id,
        payload_hash=payload_hash, xml_storage_ref=ref, status="GENERATED", pac_provider=version.pac_provider,
        pac_environment=version.pac_environment, sat_certificate_number=None, idempotency_key=key,
        replaces_document_id=getattr(replaces, "id", None), replaces_uuid=getattr(replaces, "uuid", None),
        created_by_id=actor_id)
    db.add(doc)
    db.flush()
    _event(db, doc, "GENERATED", actor_id, {"folio": folio, "schemaReleaseId": release.id, "pilot": pilot}, None,
           "GENERATED")
    _transition(db, doc, "SIGNED", "SIGNED", actor_id, {"certificateNumber": cert_no})
    db.add(m.PayrollMxCfdiOutboxItem(document_id=doc.id, action="STAMP", attempt_no=1, payload_hash=payload_hash,
                                     idempotency_key=key, status="PENDING"))
    return doc


def generate(db: Session, run, actor_id: Optional[int]) -> dict:
    from app.modules.payroll import mexico_run_service

    pre = preflight(db, run)
    if not pre["ready"]:
        first = pre["reasons"][0]
        raise MXRefuse(first["code"], "; ".join(f"{r['code']}: {r['message']}" for r in pre["reasons"]),
                      run.organization_id, reasons=[(r["code"], r["message"]) for r in pre["reasons"]])
    release = _active_release(db)
    created = []
    is_correction = (run.mx_run_type or "ORDINARY") == "CORRECTION"
    for item in mexico_run_service._mx_items(db, run):
        if _live_doc(db, item.id) is None:
            replaces = None
            if is_correction:                      # Phase 9a: substitution of the original's stamped CFDI
                from app.modules.payroll import mexico_correction_service

                replaces = mexico_correction_service.cfdi_original(db, item, actor_id)
            doc = _generate_one(db, run, item, release, actor_id, replaces=replaces)
            if replaces is not None:
                _event(db, replaces, "REPLACEMENT_LINKED", actor_id, {"replacementDocumentId": doc.id})
            created.append(doc)
    db.commit()
    return {"runId": run.id, "created": [document_view(d) for d in created]}


def create_replacement(db: Session, original, run, item, actor_id: Optional[int]):
    """Substitution (MX-018, F6): a new document for a corrected, committed
    payslip that names the original's UUID. The correction run itself is
    Phase 9; this records the lineage."""
    if original.status not in ("STAMPED", "CANCEL_REQUESTED", "CANCELLED"):
        raise BadRequestException("Only a stamped (or cancelling) CFDI can be replaced")
    pre = preflight(db, run)
    if not pre["ready"]:
        raise MXRefuse(pre["reasons"][0]["code"], pre["reasons"][0]["message"], run.organization_id)
    doc = _generate_one(db, run, item, _active_release(db), actor_id, replaces=original)
    _event(db, original, "REPLACEMENT_LINKED", actor_id, {"replacementDocumentId": doc.id})
    db.commit()
    return doc


# ── outbox processing (§5.3) ────────────────────────────────────────────────

def _doc_ref(doc) -> "_pac.DocumentRef":
    return _pac.DocumentRef(document_id=doc.id, issuer_rfc=None, folio=doc.folio, series=doc.series,
                            payload_hash=doc.payload_hash)


def _credential(db: Session, doc):
    m = _models()
    item = db.get(m.PayslipItem, doc.payslip_item_id)
    run = db.get(m.PayrollRun, doc.payroll_run_id)
    _v, _root, cred = _employer_for(db, item, run.pay_date)
    return _pac.CredentialHandle(getattr(cred, "id", None), "CSD", getattr(cred, "fingerprint_sha256", None))


def _adopt_uuid(db: Session, doc, uuid: str, result, event_type: str, actor_id=None) -> bool:
    """Record the PAC's UUID. A different UUID for the same idempotency key is
    a conflict: UNKNOWN for manual reconciliation, never a second document."""
    if doc.uuid and uuid and doc.uuid != uuid:
        _transition(db, doc, "UNKNOWN", "UUID_CONFLICT", actor_id, {"code": "MX_CFDI_UUID_CONFLICT",
                                                                   "known": doc.uuid, "reported": uuid})
        doc.unknown_action = "STAMP"
        return False
    if doc.status == "STAMPED":
        _event(db, doc, event_type + "_ALREADY_STAMPED", actor_id, {"uuid": uuid})
        return True
    doc.uuid = uuid
    doc.stamped_at = getattr(result, "stamped_at", None) or _now()
    doc.sat_certificate_number = getattr(result, "sat_certificate_number", None)
    doc.pac_response_code, doc.pac_message = getattr(result, "code", None), (getattr(result, "message", None) or "")[:500]
    _transition(db, doc, "STAMPED", event_type, actor_id, {"uuid": uuid})
    _complete_replacement(db, doc, actor_id)
    return True


def _store_stamped_xml(db: Session, doc, result, actor_id=None) -> None:
    """W4-3b: keep the PAC's stamped CFDI beside the signed one (no new column:
    its reference is the STAMPED_XML_STORED event's detail). A stamped XML that
    does not carry the adopted UUID is not kept — the receipt then refuses."""
    xml = getattr(result, "stamped_xml", None)
    if not xml:
        return
    if (doc.uuid or "").encode() not in xml:
        _event(db, doc, "STAMPED_XML_MISMATCH", actor_id, {"uuid": doc.uuid, "sha256": _sha(xml)})
        return
    from app.core import object_storage

    ref = object_storage.save_upload(subdir=f"mx_cfdi/{doc.organization_id}/{doc.payroll_run_id}",
                                     filename=f"{doc.folio}.stamped.xml", data=xml)
    _event(db, doc, "STAMPED_XML_STORED", actor_id, {"ref": ref, "sha256": _sha(xml)})


def stamped_xml_ref(db: Session, doc):
    """The stored stamped XML's reference, or None (W4-3b)."""
    m = _models()
    ev = (db.query(m.PayrollMxCfdiEvent).filter(m.PayrollMxCfdiEvent.document_id == doc.id,
                                                m.PayrollMxCfdiEvent.event_type == "STAMPED_XML_STORED")
          .order_by(m.PayrollMxCfdiEvent.id.desc()).first())
    return (ev.detail or {}).get("ref") if ev is not None else None


def _complete_replacement(db: Session, doc, actor_id=None):
    """original CANCELLED + replacement STAMPED -> original REPLACED."""
    m = _models()
    if doc.status == "STAMPED" and doc.replaces_document_id:
        original = db.get(m.PayrollMxCfdiDocument, doc.replaces_document_id)
        if original is not None and original.status == "CANCELLED":
            original.replaced_by_uuid = doc.uuid
            _transition(db, original, "REPLACED", "REPLACED", actor_id, {"replacedByUuid": doc.uuid})
    if doc.status == "CANCELLED":
        repl = (db.query(m.PayrollMxCfdiDocument)
                .filter(m.PayrollMxCfdiDocument.replaces_document_id == doc.id,
                        m.PayrollMxCfdiDocument.status == "STAMPED").first())
        if repl is not None:
            doc.replaced_by_uuid = repl.uuid
            _transition(db, doc, "REPLACED", "REPLACED", actor_id, {"replacedByUuid": repl.uuid})


def _process_stamp(db: Session, item, doc, adapter, actor_id):
    if doc.status != "SIGNED" or item.payload_hash != doc.payload_hash or item.idempotency_key != doc.idempotency_key:
        item.status, item.last_error = "FAILED", "document is not SIGNED with this payload / key"
        return
    _transition(db, doc, "SUBMITTED", "STAMP_SENT", actor_id, {"attempt": item.attempt_no})
    item.status, item.sent_at = "SENT", _now()
    db.commit()                                   # SUBMITTED is durable BEFORE the outward call (restore → UNKNOWN)
    from app.core import object_storage

    try:
        result = adapter.stamp(object_storage.read_bytes(doc.xml_storage_ref), doc.idempotency_key, _credential(db, doc))
    except Exception as exc:                      # transport / timeout → UNKNOWN, never REJECTED (MX-062)
        result = _pac.StampResult(outcome=_pac.UNKNOWN, code="TRANSPORT", message=type(exc).__name__)
    if result.outcome == _pac.ACCEPTED and result.uuid:
        if _adopt_uuid(db, doc, result.uuid, result, "STAMPED", actor_id):
            _store_stamped_xml(db, doc, result, actor_id)
        item.status, item.acknowledged_at = "ACKNOWLEDGED", _now()
    elif result.outcome == _pac.REJECTED:
        doc.pac_response_code, doc.pac_message = result.code, (result.message or "")[:500]
        _transition(db, doc, "REJECTED", "REJECTED", actor_id, {"code": result.code})
        item.status, item.acknowledged_at = "ACKNOWLEDGED", _now()
    else:
        _transition(db, doc, "UNKNOWN", "STAMP_UNKNOWN", actor_id, {"code": result.code, "attempt": item.attempt_no})
        doc.unknown_action = "STAMP"
        item.status = "UNKNOWN"


def _process_status_query(db: Session, item, doc, adapter, actor_id):
    try:
        result = adapter.query_status(_doc_ref(doc), doc.idempotency_key, _credential(db, doc))
    except Exception as exc:
        result = _pac.StatusResult(outcome=_pac.UNKNOWN, code="TRANSPORT", message=type(exc).__name__)
    item.status, item.acknowledged_at = "ACKNOWLEDGED", _now()
    if result.outcome == _pac.FOUND and result.uuid:
        if doc.status in ("UNKNOWN", "STAMPED"):
            _adopt_uuid(db, doc, result.uuid, result, "STATUS_FOUND", actor_id)
        elif doc.status == "SIGNED":
            # Late FOUND after a confirmed retry that has not been sent yet:
            # adopt the PAC's UUID and withdraw the pending retry — nothing is
            # sent a second time.
            m = _models()
            for pending in db.query(m.PayrollMxCfdiOutboxItem).filter(
                    m.PayrollMxCfdiOutboxItem.document_id == doc.id, m.PayrollMxCfdiOutboxItem.action == "STAMP",
                    m.PayrollMxCfdiOutboxItem.status == "PENDING"):
                pending.status, pending.last_error = "FAILED", "withdrawn: a status query found the stamped CFDI"
            _adopt_uuid(db, doc, result.uuid, result, "STATUS_FOUND_LATE", actor_id)
        else:
            _event(db, doc, "STATUS_FOUND_LATE", actor_id, {"uuid": result.uuid, "status": doc.status})
    elif result.outcome == _pac.NOT_FOUND:
        _event(db, doc, "STATUS_NOT_FOUND", actor_id, {"query": item.attempt_no})
    else:
        _event(db, doc, "STATUS_UNKNOWN", actor_id, {"code": result.code})


def _process_cancel(db: Session, item, doc, adapter, actor_id):
    if doc.status != "CANCEL_REQUESTED":
        item.status, item.last_error = "FAILED", "document is not CANCEL_REQUESTED"
        return
    item.status, item.sent_at = "SENT", _now()
    db.commit()
    try:
        result = adapter.cancel(doc.uuid, doc.cancellation_reason_code, doc.replaced_by_uuid or _replacement_uuid(db, doc),
                                item.idempotency_key, _credential(db, doc))
    except Exception as exc:
        result = _pac.CancelResult(outcome=_pac.UNKNOWN, code="TRANSPORT", message=type(exc).__name__)
    _apply_cancel_outcome(db, item, doc, result.outcome, result.code, actor_id)


def _replacement_uuid(db: Session, doc):
    m = _models()
    repl = (db.query(m.PayrollMxCfdiDocument).filter(m.PayrollMxCfdiDocument.replaces_document_id == doc.id,
                                                     m.PayrollMxCfdiDocument.status == "STAMPED").first())
    return repl.uuid if repl else None


def _apply_cancel_outcome(db: Session, item, doc, outcome, code, actor_id):
    if outcome in (_pac.ACCEPTED, _pac.CANCELLED):
        doc.cancelled_at = _now()
        _transition(db, doc, "CANCELLED", "CANCELLED", actor_id, {"code": code})
        _complete_replacement(db, doc, actor_id)
        item.status, item.acknowledged_at = "ACKNOWLEDGED", _now()
    elif outcome == _pac.PENDING:
        if doc.status == "UNKNOWN":
            _transition(db, doc, "CANCEL_REQUESTED", "CANCEL_PENDING", actor_id, {"code": code})
        else:
            _event(db, doc, "CANCEL_PENDING", actor_id, {"code": code})
        item.status, item.acknowledged_at = "ACKNOWLEDGED", _now()
    elif outcome in (_pac.REJECTED, _pac.STILL_ACTIVE):
        _transition(db, doc, "STAMPED", "CANCEL_REJECTED", actor_id, {"code": code})
        item.status, item.acknowledged_at = "ACKNOWLEDGED", _now()
    else:
        if doc.status != "UNKNOWN":
            _transition(db, doc, "UNKNOWN", "CANCEL_UNKNOWN", actor_id, {"code": code})
        doc.unknown_action = "CANCEL"
        item.status = "UNKNOWN"


def _process_cancel_status(db: Session, item, doc, adapter, actor_id):
    try:
        result = adapter.query_cancel_status(doc.uuid, _credential(db, doc))
    except Exception as exc:
        result = _pac.CancelStatusResult(outcome=_pac.UNKNOWN, code="TRANSPORT", message=type(exc).__name__)
    if result.outcome == _pac.UNKNOWN:
        _event(db, doc, "CANCEL_STATUS_UNKNOWN", actor_id, {"code": result.code})
        item.status, item.acknowledged_at = "ACKNOWLEDGED", _now()
        return
    _apply_cancel_outcome(db, item, doc, result.outcome, result.code, actor_id)


_HANDLERS = {"STAMP": _process_stamp, "STATUS_QUERY": _process_status_query, "CANCEL": _process_cancel,
             "CANCEL_STATUS_QUERY": _process_cancel_status}


def process_outbox(db: Session, organization_id: int, actor_id: Optional[int], limit: int = 20) -> dict:
    """Explicit, operator-triggered processing (D5). One item per commit; a
    PostgreSQL row lock (SKIP LOCKED) keeps two operators from sending the
    same item."""
    m = _models()
    q = (db.query(m.PayrollMxCfdiOutboxItem).join(m.PayrollMxCfdiDocument,
                                                  m.PayrollMxCfdiDocument.id == m.PayrollMxCfdiOutboxItem.document_id)
         .filter(m.PayrollMxCfdiDocument.organization_id == organization_id,
                 m.PayrollMxCfdiOutboxItem.status == "PENDING")
         # Status queries FIRST in every batch: an outward action is never
         # retransmitted before a pending reconciliation (MX-062).
         .order_by(case((m.PayrollMxCfdiOutboxItem.action.in_(("STATUS_QUERY", "CANCEL_STATUS_QUERY")), 0), else_=1),
                   m.PayrollMxCfdiOutboxItem.id).limit(limit))
    if db.get_bind().dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True, of=m.PayrollMxCfdiOutboxItem)
    done = []
    for item in q.all():
        if item.status != "PENDING":            # withdrawn by an earlier item of this batch (e.g. a late FOUND)
            done.append({"outboxItemId": item.id, "skipped": f"no longer pending ({item.status})"})
            continue
        doc = db.get(m.PayrollMxCfdiDocument, item.document_id)
        if item.action in ("STAMP", "CANCEL") and doc.status == "UNKNOWN":
            done.append({"outboxItemId": item.id, "skipped": "document is UNKNOWN — query its status first (MX-062)"})
            continue
        try:
            from app.modules.payroll import mexico_pilot_service

            mexico_pilot_service.refuse_non_sandbox_pac(db, doc.organization_id, doc.pac_environment)   # Phase 10e
            adapter = _pac.get_adapter(doc.pac_provider, doc.pac_environment)
        except MXBlock as exc:
            item.last_error = f"{exc.key}: {exc.reason}"[:500]
            db.commit()
            done.append({"outboxItemId": item.id, "error": exc.key})
            continue
        _HANDLERS[item.action](db, item, doc, adapter, actor_id)
        db.commit()
        done.append({"outboxItemId": item.id, "action": item.action, "status": item.status, "document": doc.status})
    return {"processed": done}


# ── UNKNOWN handling (§4.2) ─────────────────────────────────────────────────

def _doc(db: Session, org_id: int, doc_id: int):
    m = _models()
    doc = db.get(m.PayrollMxCfdiDocument, doc_id)
    if doc is None or doc.organization_id != org_id:
        raise NotFoundException("Mexico CFDI document", doc_id)
    return doc


def _events_since(db: Session, doc, event_type: str):
    """Events of `event_type` after the document last ENTERED UNKNOWN (by event
    id — timestamps are too coarse on some backends to order reliably)."""
    m = _models()
    db.flush()
    last_unknown = (db.query(m.PayrollMxCfdiEvent.id)
                    .filter(m.PayrollMxCfdiEvent.document_id == doc.id, m.PayrollMxCfdiEvent.to_status == "UNKNOWN")
                    .order_by(m.PayrollMxCfdiEvent.id.desc()).first())
    q = db.query(m.PayrollMxCfdiEvent).filter(m.PayrollMxCfdiEvent.document_id == doc.id,
                                              m.PayrollMxCfdiEvent.event_type == event_type)
    if last_unknown is not None:
        q = q.filter(m.PayrollMxCfdiEvent.id > last_unknown[0])
    return q.order_by(m.PayrollMxCfdiEvent.id).all()


def request_status_query(db: Session, org_id: int, doc_id: int, actor_id: Optional[int]) -> dict:
    m = _models()
    doc = _doc(db, org_id, doc_id)
    if doc.status not in ("UNKNOWN", "CANCEL_REQUESTED"):
        raise BadRequestException("A status query is only for an UNKNOWN (or cancelling) document")
    action = "CANCEL_STATUS_QUERY" if (doc.status == "CANCEL_REQUESTED" or doc.unknown_action == "CANCEL") else "STATUS_QUERY"
    n = db.query(m.PayrollMxCfdiOutboxItem).filter(m.PayrollMxCfdiOutboxItem.document_id == doc.id,
                                                   m.PayrollMxCfdiOutboxItem.action == action).count() + 1
    db.add(m.PayrollMxCfdiOutboxItem(document_id=doc.id, action=action, attempt_no=n, payload_hash=doc.payload_hash,
                                     idempotency_key=f"{doc.idempotency_key}:q{n}"[:100], status="PENDING"))
    _event(db, doc, "STATUS_QUERY_REQUESTED", actor_id, {"action": action, "query": n})
    db.commit()
    return document_view(doc)


def definitively_not_found(db: Session, doc) -> dict:
    """{definitive, notFoundQueries, config} — needs provider config (no default)."""
    nf = _events_since(db, doc, "STATUS_NOT_FOUND")
    found = _events_since(db, doc, "STATUS_FOUND")
    cfg = _pac.retry_config(doc.pac_provider)
    out = {"definitive": False, "notFoundQueries": len(nf), "providerConfig": cfg is not None}
    if cfg is None or found:
        return out
    m = _models()
    sent = (db.query(m.PayrollMxCfdiEvent).filter(m.PayrollMxCfdiEvent.document_id == doc.id,
                                                  m.PayrollMxCfdiEvent.event_type == "STAMP_SENT")
            .order_by(m.PayrollMxCfdiEvent.id.desc()).first())
    last_send = _aware(sent.occurred_at) if sent is not None else _aware(doc.unknown_since)
    waited = (_now() - last_send).total_seconds() if last_send else 0
    out["definitive"] = len(nf) >= cfg.min_not_found_queries and waited >= cfg.min_wait_seconds
    return out


def confirm_retry(db: Session, org_id: int, doc_id: int, actor_id: Optional[int], reason: str) -> dict:
    """The ONLY way out of UNKNOWN back to a send (§4.2): an org admin
    confirms, with a reason, after at least one NOT_FOUND status answer. The
    retry reuses the SAME payload and the SAME idempotency key."""
    m = _models()
    doc = _doc(db, org_id, doc_id)
    if not (reason or "").strip():
        raise BadRequestException("A retry confirmation needs a reason")
    if doc.status != "UNKNOWN" or doc.unknown_action != "STAMP":
        raise BadRequestException("Only an UNKNOWN stamp can be retried")
    state = definitively_not_found(db, doc)
    if state["notFoundQueries"] < 1:
        raise MXRefuse("MX_CFDI_STATUS_QUERY_REQUIRED",
                      "query the PAC for this document first — a retry is never sent blind (MX-062)", org_id)
    n = db.query(m.PayrollMxCfdiOutboxItem).filter(m.PayrollMxCfdiOutboxItem.document_id == doc.id,
                                                   m.PayrollMxCfdiOutboxItem.action == "STAMP").count() + 1
    _event(db, doc, "OPERATOR_RETRY_CONFIRMED", actor_id, {"reason": reason.strip()[:300], "attempt": n, **state})
    _transition(db, doc, "SIGNED", "RETRY_READY", actor_id, {"attempt": n})
    db.add(m.PayrollMxCfdiOutboxItem(document_id=doc.id, action="STAMP", attempt_no=n, payload_hash=doc.payload_hash,
                                     idempotency_key=doc.idempotency_key, status="PENDING",
                                     operator_confirmed_by_id=actor_id))
    db.commit()
    return document_view(doc)


def reconcile_after_restore(db: Session, org_id: int, actor_id: Optional[int]) -> dict:
    """After a timeout / restore every in-flight outward action is UNKNOWN until
    reconciled (MX-062)."""
    m = _models()
    moved = 0
    for doc in db.query(m.PayrollMxCfdiDocument).filter(m.PayrollMxCfdiDocument.organization_id == org_id,
                                                        m.PayrollMxCfdiDocument.status.in_(("SUBMITTED", "CANCEL_REQUESTED"))):
        action = "CANCEL" if doc.status == "CANCEL_REQUESTED" else "STAMP"
        _transition(db, doc, "UNKNOWN", "RESTORE_RECONCILED", actor_id, {"action": action})
        doc.unknown_action = action
        moved += 1
    for item in (db.query(m.PayrollMxCfdiOutboxItem).join(m.PayrollMxCfdiDocument,
                 m.PayrollMxCfdiDocument.id == m.PayrollMxCfdiOutboxItem.document_id)
                 .filter(m.PayrollMxCfdiDocument.organization_id == org_id, m.PayrollMxCfdiOutboxItem.status == "SENT")):
        item.status = "UNKNOWN"
    db.commit()
    return {"movedToUnknown": moved}


# ── cancellation (§4.3) ─────────────────────────────────────────────────────

def _cancel_reason(db: Session, code: str):
    m = _models()
    rows = (db.query(m.PayrollMxCfdiCatalogEntry).join(m.PayrollMxCfdiSchemaRelease,
            m.PayrollMxCfdiSchemaRelease.id == m.PayrollMxCfdiCatalogEntry.schema_release_id)
            .filter(m.PayrollMxCfdiSchemaRelease.status == "Active",
                    m.PayrollMxCfdiCatalogEntry.catalog_name == CANCEL_REASON_CATALOG,
                    m.PayrollMxCfdiCatalogEntry.code == code).all())
    return rows[0] if rows else None


def cancel(db: Session, org_id: int, doc_id: int, reason_code: str, replacement_uuid: Optional[str],
           actor_id: Optional[int]) -> dict:
    m = _models()
    doc = _doc(db, org_id, doc_id)
    if doc.status != "STAMPED":
        raise BadRequestException("Only a STAMPED CFDI can be cancelled")
    entry = _cancel_reason(db, (reason_code or "").strip())
    if entry is None:
        raise MXRefuse("MX_CFDI_CANCEL_REASON_UNAVAILABLE",
                      f"cancellation reason {reason_code!r} is not in an Active {CANCEL_REASON_CATALOG} catalog "
                      "(S30 not transcribed)", org_id)
    needs_related = bool((entry.attributes or {}).get("requiresRelatedUuid"))
    if needs_related:
        repl = (db.query(m.PayrollMxCfdiDocument)
                .filter(m.PayrollMxCfdiDocument.organization_id == org_id, m.PayrollMxCfdiDocument.uuid == replacement_uuid,
                        m.PayrollMxCfdiDocument.replaces_document_id == doc.id,
                        m.PayrollMxCfdiDocument.status == "STAMPED").first()) if replacement_uuid else None
        if repl is None:
            raise BadRequestException(f"Reason {entry.code} needs the UUID of this document's STAMPED replacement")
    doc.cancellation_reason_code, doc.cancel_requested_at = entry.code, _now()
    _transition(db, doc, "CANCEL_REQUESTED", "CANCEL_REQUESTED", actor_id,
                {"reason": entry.code, "replacementUuid": replacement_uuid if needs_related else None})
    n = db.query(m.PayrollMxCfdiOutboxItem).filter(m.PayrollMxCfdiOutboxItem.document_id == doc.id,
                                                   m.PayrollMxCfdiOutboxItem.action == "CANCEL").count() + 1
    db.add(m.PayrollMxCfdiOutboxItem(document_id=doc.id, action="CANCEL", attempt_no=n, payload_hash=doc.payload_hash,
                                     idempotency_key=f"{doc.idempotency_key}:c{n}"[:100], status="PENDING"))
    db.commit()
    return document_view(doc)


# ── reset rule (§6) and views ───────────────────────────────────────────────

def _run_docs(db: Session, run):
    m = _models()
    return (db.query(m.PayrollMxCfdiDocument).filter(m.PayrollMxCfdiDocument.payroll_run_id == run.id)
            .order_by(m.PayrollMxCfdiDocument.id).all())


def downstream_reasons(db: Session, run) -> list:
    return [f"CFDI folio {d.folio} (payslip {d.payslip_item_id}) is {d.status}" for d in _run_docs(db, run)
            if d.status in ACTED]


def void_untransmitted(db: Session, run, actor_id: Optional[int]) -> int:
    m = _models()
    n = 0
    for doc in _run_docs(db, run):
        if doc.status in ("GENERATED", "SIGNED"):
            _transition(db, doc, "VOIDED", "VOIDED_ON_RESET", actor_id)
            for item in db.query(m.PayrollMxCfdiOutboxItem).filter(m.PayrollMxCfdiOutboxItem.document_id == doc.id,
                                                                   m.PayrollMxCfdiOutboxItem.status == "PENDING"):
                item.status, item.last_error = "FAILED", "document voided on run reset"
            n += 1
    return n


def run_summary(db: Session, run) -> dict:
    docs = _run_docs(db, run)
    counts = {}
    for d in docs:
        counts[d.status] = counts.get(d.status, 0) + 1
    if not docs:
        return {"status": "NOT_STARTED", "counts": {}, "detail": "no CFDI generated for this run"}
    # The lane reads each payslip's LATEST document (a rejected or voided one
    # that was regenerated is history): any UNKNOWN wins, then anything still
    # moving; a settled run is STAMPED, or REPLACED / CANCELLED / REJECTED /
    # VOIDED when every payslip's chain ended that way.
    latest = {}
    for d in docs:
        latest[d.payslip_item_id] = d.status
    states = set(latest.values())
    if "UNKNOWN" in states:
        status = "UNKNOWN"
    elif states & {"GENERATED", "SIGNED", "SUBMITTED", "CANCEL_REQUESTED"}:
        status = "IN_PROGRESS"
    elif "REJECTED" in states:
        status = "REJECTED"
    elif not states - {"VOIDED"}:
        status = "VOIDED"
    elif states - {"VOIDED"} == {"STAMPED"}:
        status = "STAMPED"
    else:
        status = "CANCELLED" if "CANCELLED" in states else "REPLACED"
    return {"status": status, "counts": counts, "detail": ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))}


def document_view(doc) -> dict:
    return {"id": doc.id, "runId": doc.payroll_run_id, "payslipItemId": doc.payslip_item_id,
            "employeeId": doc.employee_id, "series": doc.series, "folio": doc.folio, "status": doc.status,
            "unknownAction": doc.unknown_action, "uuid": doc.uuid,
            "stampedAt": doc.stamped_at.isoformat() if doc.stamped_at else None,
            "satCertificateNumber": doc.sat_certificate_number, "pacProvider": doc.pac_provider,
            "pacEnvironment": doc.pac_environment, "pacResponseCode": doc.pac_response_code,
            "pacMessage": doc.pac_message, "payloadHash": doc.payload_hash,
            "cancellationReasonCode": doc.cancellation_reason_code, "replacesUuid": doc.replaces_uuid,
            "replacedByUuid": doc.replaced_by_uuid, "schemaReleaseId": doc.schema_release_id}


def document_detail(db: Session, org_id: int, doc_id: int) -> dict:
    m = _models()
    doc = _doc(db, org_id, doc_id)
    events = db.query(m.PayrollMxCfdiEvent).filter(m.PayrollMxCfdiEvent.document_id == doc.id).order_by(m.PayrollMxCfdiEvent.id)
    outbox = (db.query(m.PayrollMxCfdiOutboxItem).filter(m.PayrollMxCfdiOutboxItem.document_id == doc.id)
              .order_by(m.PayrollMxCfdiOutboxItem.id))
    return {**document_view(doc), "retry": definitively_not_found(db, doc) if doc.status == "UNKNOWN" else None,
            "events": [{"id": e.id, "type": e.event_type, "from": e.from_status, "to": e.to_status, "detail": e.detail,
                        "actorId": e.actor_id, "at": e.occurred_at.isoformat() if e.occurred_at else None} for e in events],
            "outbox": [{"id": o.id, "action": o.action, "attempt": o.attempt_no, "status": o.status,
                        "idempotencyKey": o.idempotency_key, "payloadHash": o.payload_hash, "lastError": o.last_error,
                        "operatorConfirmedById": o.operator_confirmed_by_id} for o in outbox]}


def run_documents(db: Session, run) -> dict:
    return {**preflight(db, run), "documents": [document_view(d) for d in _run_docs(db, run)],
            "summary": run_summary(db, run)}


def cancellation_reasons(db: Session) -> list:
    """Cancellation reasons of the Active catalog (empty until S30 — D6)."""
    m = _models()
    rows = (db.query(m.PayrollMxCfdiCatalogEntry).join(m.PayrollMxCfdiSchemaRelease,
            m.PayrollMxCfdiSchemaRelease.id == m.PayrollMxCfdiCatalogEntry.schema_release_id)
            .filter(m.PayrollMxCfdiSchemaRelease.status == "Active",
                    m.PayrollMxCfdiCatalogEntry.catalog_name == CANCEL_REASON_CATALOG)
            .order_by(m.PayrollMxCfdiCatalogEntry.code).all())
    return [{"code": r.code, "description": r.description,
             "requiresRelatedUuid": bool((r.attributes or {}).get("requiresRelatedUuid"))} for r in rows]


def lifecycle_overview(db: Session, organization_id: Optional[int] = None) -> dict:
    """Super Admin, read-only (§7): counts by status, UNKNOWN items, the pinned
    schema release, and why generation cannot run yet."""
    m = _models()
    q = db.query(m.PayrollMxCfdiDocument)
    if organization_id is not None:
        q = q.filter(m.PayrollMxCfdiDocument.organization_id == organization_id)
    docs = q.all()
    counts = {}
    for d in docs:
        counts[d.status] = counts.get(d.status, 0) + 1
    release = _active_release(db)
    blocked = [{"code": b.key, "message": b.reason}
               for b in (_builder.active_builder().blocked(), _builder.active_signer().blocked()) if b is not None]
    if not _pac._ADAPTERS:
        blocked.append({"code": "MX_PAC_NOT_CONFIGURED", "message": "no PAC adapter is configured (Phase 7 D10)"})
    return {"organizationId": organization_id, "counts": counts, "total": len(docs),
            "unknown": [document_view(d) for d in docs if d.status == "UNKNOWN"],
            "schemaRelease": None if release is None else {"id": release.id, "cfdiVersion": release.cfdi_version,
                                                           "complementVersion": release.complement_version,
                                                           "status": release.status},
            "blocked": blocked}
