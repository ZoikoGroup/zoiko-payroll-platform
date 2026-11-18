"""
payroll/mexico_cfdi_lifecycle.py
--------------------------------
Mexico CFDI lifecycle L1-L5 (docs/mexico/MEXICO_CFDI_LIFECYCLE_REPORT.md).

The fiscal state machine in mexico_cfdi_service (GENERATED ... VOIDED, with
UNKNOWN's query-before-retry rule) is NOT changed. This module maps the design
pack's CFDI_DOCUMENT and PAYROLL_RUN states onto it, derives the common
envelope, keeps the immutable delivery / access log, computes the pay-event
idempotency key, and records the two outcomes the machine had no place for
(publish, delivery). Rules:
  * no lifecycle advances another: payment never implies a stamp and a stamp
    never implies payment; publishing needs a STAMPED document whose stored
    stamped XML carries a TimbreFiscalDigital;
  * nothing here holds or logs an identifier in clear: RFCs enter the
    idempotency hash only, the envelope carries ids and hashes, the access
    log carries actor / time / channel / artifact.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.modules.payroll.engine.countries.mexico import MXRefuse

LOCALE = "es-MX"
RETENTION_POLICY_PENDING = "PENDING_C15"      # the XML retention period is gap C15 (release owner + legal)
EXTRAORDINARY = ("AGUINALDO", "PTU", "FINIQUITO")

# ── L1: state mapping ────────────────────────────────────────────────────────

# repo status -> design CFDI_DOCUMENT state (before outcomes are applied)
DOCUMENT_STATE_MAP = {
    "GENERATED": "SIGNING_REQUESTED",
    "SIGNED": "SIGNING_REQUESTED",          # signed locally, STAMP queued in the outbox, not yet sent
    "SUBMITTED": "PAC_SUBMITTED",
    "UNKNOWN": "UNKNOWN",                   # kept: stricter than the design (query before any retry)
    "REJECTED": "PAC_REJECTED",
    "STAMPED": "STAMPED",
    "CANCEL_REQUESTED": "CANCEL_REQUESTED",
    "CANCELLED": "CANCEL_ACCEPTED",
    "REPLACED": "CANCEL_ACCEPTED",          # cancelled and its replacement stamped (lineage on both rows)
    "VOIDED": "VOIDED",                     # never transmitted; voided by a run reset (no design equivalent)
}

# repo run status -> design PAYROLL_RUN state (the fiscal and bank lanes are separate)
RUN_STATE_MAP = {
    "Draft": "CALCULATED",                  # OPEN when it has no payslip yet; inputs freeze into the snapshot
    "Review": "REVIEWED",
    "Approved": "APPROVED",
    "Authorized": "APPROVED",
    "Paid": "APPROVED",                     # the generic Paid status never implies a bank settlement for MX
    "Closed": "APPROVED",
}


def _models():
    from app.modules.payroll import models as m

    return m


def latest_validation(db: Session, run_id: int) -> Optional[dict]:
    """The latest validate-only (Phase 11c) summary of a run, from its audit row."""
    from app.modules.payroll import mexico_cfdi_preview

    A = _models().TaxConfigurationAudit
    row = (db.query(A).filter(A.entity_type == mexico_cfdi_preview.ENTITY, A.action == "validate",
                              A.entity_id == run_id).order_by(A.id.desc()).first())
    return row.new_value if row is not None else None


def design_state(db: Session, item, doc=None) -> dict:
    """The design pack's CFDI_DOCUMENT state for one payslip, from the repo state."""
    if doc is None:
        from app.modules.payroll import mexico_payslip_service

        doc = mexico_payslip_service.latest_document(db, item.id)
    if doc is None:
        v = latest_validation(db, item.payroll_run_id) or {}
        if item.id in (v.get("refusedPayslips") or []):
            state = "VALIDATION_FAILED"
        elif item.id in (v.get("validPayslips") or []):
            state = "VALIDATED_LOCAL"
        else:
            state = "DRAFT"
        return {"state": state, "repoStatus": None, "documentId": None, "cancelOutcome": None}
    state = DOCUMENT_STATE_MAP[doc.status]
    if doc.status == "STAMPED":
        if doc.delivery_status:
            state = doc.delivery_status
        elif doc.published_at:
            state = "PUBLISHED"
    return {"state": state, "repoStatus": doc.status, "documentId": doc.id, "cancelOutcome": doc.cancel_outcome}


def run_states(db: Session, run) -> dict:
    """Design PAYROLL_RUN state plus the separate funding lane — derived side by side, never from each other."""
    m = _models()
    has_items = db.query(m.PayslipItem.id).filter(m.PayslipItem.payroll_run_id == run.id).first() is not None
    payroll = RUN_STATE_MAP.get(run.status, "CALCULATED") if has_items else "OPEN"
    return {"payroll": payroll, "funding": funding_state(db, run)}


def funding_state(db: Session, run) -> dict:
    """FUNDED / PAID from the Phase 10a payment batches only (MX-017: never from stamps or run status)."""
    m = _models()
    batches = db.query(m.PayrollMxPaymentBatch).filter(m.PayrollMxPaymentBatch.payroll_run_id == run.id,
                                                       m.PayrollMxPaymentBatch.status != "CANCELLED").all()
    if not batches:
        return {"state": "NOT_FUNDED", "detail": "no payment batch"}
    items = db.query(m.PayrollMxPaymentItem).filter(
        m.PayrollMxPaymentItem.batch_id.in_([b.id for b in batches]),
        m.PayrollMxPaymentItem.reissued_by_item_id.is_(None)).all()
    if items and all(i.status == "SETTLED" for i in items):
        return {"state": "PAID", "detail": f"{len(items)} payment(s) settled"}
    if any(b.status in ("RELEASED", "CLOSED") for b in batches):
        return {"state": "FUNDED", "detail": "payment batch released; not every payment settled"}
    return {"state": "NOT_FUNDED", "detail": "payment batch in DRAFT"}


# ── L4: the pay-event idempotency key ────────────────────────────────────────

def document_subtype(run, replaces=None) -> str:
    if replaces is not None:
        return f"REPLACEMENT:{replaces.id}"
    return "EXTRAORDINARY" if (getattr(run, "mx_run_type", None) or "ORDINARY").upper() in EXTRAORDINARY \
        else "ORDINARY"


def event_key(org_id: int, issuer_rfc: Optional[str], worker_rfc: Optional[str], run_id: int, pay_event_id: int,
              subtype: str, snapshot_version: Optional[str]) -> str:
    """hash(tenant + issuer_RFC + worker_RFC + run_id + pay_event_id + document_subtype + snapshot_version).
    The RFCs exist only inside this hash — never stored or logged."""
    parts = [str(org_id), (issuer_rfc or "").strip().upper(), (worker_rfc or "").strip().upper(), str(run_id),
             str(pay_event_id), subtype, snapshot_version or ""]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def cert_token(credential) -> Optional[str]:
    if credential is None:
        return None
    return hashlib.sha256(f"csd:{credential.id}:{credential.fingerprint_sha256 or ''}".encode()).hexdigest()


def ruleset_version(snapshot: dict) -> Optional[str]:
    pack = (snapshot or {}).get("pack") or {}
    pack_id = pack.get("pack_id") or pack.get("packId") or pack.get("id")
    version = pack.get("version")
    engine = (snapshot or {}).get("engineVersion")
    bits = [f"{pack_id}@{version}" if pack_id else None, f"engine {engine}" if engine else None]
    return " / ".join(b for b in bits if b) or None


def stamp_envelope_columns(db: Session, doc, run, item, version, root, credential, replaces=None) -> None:
    """Called when a document is generated: freeze the envelope facts and the event key on the row."""
    from app.modules.payroll import mexico_employee_service
    from app.modules.payroll.models import PayrollEmployee

    snap = item.mx_calculation_snapshot or {}
    employee = db.get(PayrollEmployee, item.employee_id)
    prof = mexico_employee_service._profile_on(db, item.employee_id, run.pay_date)
    subtype = document_subtype(run, replaces)
    doc.document_subtype = subtype
    doc.employer_profile_id = root
    doc.state_code = getattr(prof, "mx_work_state", None)
    doc.snapshot_hash = snap.get("inputHash")
    doc.ruleset_version = ruleset_version(snap)
    doc.issuing_cert_token = cert_token(credential)
    doc.document_locale = LOCALE
    doc.event_key = event_key(run.organization_id, getattr(version, "rfc", None),
                              ((getattr(employee, "compliance_fields", None) or {}).get("rfc")),
                              run.id, item.id, subtype, snap.get("inputHash"))


# ── L2: the envelope ─────────────────────────────────────────────────────────

def _stamped_xml_sha(db: Session, doc) -> Optional[str]:
    m = _models()
    ev = (db.query(m.PayrollMxCfdiEvent).filter(m.PayrollMxCfdiEvent.document_id == doc.id,
                                                m.PayrollMxCfdiEvent.event_type == "STAMPED_XML_STORED")
          .order_by(m.PayrollMxCfdiEvent.id.desc()).first())
    return (ev.detail or {}).get("sha256") if ev is not None else None


def _settled_on(db: Session, item_id: int) -> Optional[str]:
    m = _models()
    row = (db.query(m.PayrollMxPaymentItem).filter(m.PayrollMxPaymentItem.payslip_item_id == item_id,
                                                   m.PayrollMxPaymentItem.status == "SETTLED")
           .order_by(m.PayrollMxPaymentItem.id.desc()).first())
    when = (row.updated_at or row.created_at) if row is not None else None
    return when.date().isoformat() if when else None


def envelope(db: Session, org_id: int, doc_id: int) -> dict:
    """The common envelope of one CFDI document: every field stored or derived;
    no RFC, CURP, NSS, CLABE or postal code in clear."""
    from app.modules.payroll import mexico_cfdi_service, mexico_payslip_service

    m = _models()
    doc = mexico_cfdi_service._doc(db, org_id, doc_id)
    item = db.get(m.PayslipItem, doc.payslip_item_id)
    run = db.get(m.PayrollRun, doc.payroll_run_id)
    release = db.get(m.PayrollMxCfdiSchemaRelease, doc.schema_release_id)
    snap = item.mx_calculation_snapshot or {}
    derived = []

    def pick(stored, compute, name):
        if stored is not None:
            return stored
        derived.append(name)
        return compute()

    version, root, cred = mexico_cfdi_service._employer_for(db, item, run.pay_date)
    from app.modules.payroll import mexico_employee_service

    prof = mexico_employee_service._profile_on(db, item.employee_id, run.pay_date)
    delivered = (db.query(m.PayrollMxDocumentAccessEvent)
                 .filter(m.PayrollMxDocumentAccessEvent.document_id == doc.id,
                         m.PayrollMxDocumentAccessEvent.event_type == "DELIVERED")
                 .order_by(m.PayrollMxDocumentAccessEvent.id.desc()).first())
    from app.modules.payroll.mexico_cfdi_catalog_service import release_set_id

    return {
        "tenant_id": doc.organization_id,
        "employer_legal_entity_id": pick(doc.employer_profile_id, lambda: root, "employer_legal_entity_id"),
        "jurisdiction": "MX",
        "state_code": pick(doc.state_code, lambda: getattr(prof, "mx_work_state", None), "state_code"),
        "employee_id": doc.employee_id,
        "payroll_run_id": doc.payroll_run_id,
        "pay_period_start": run.period_start.isoformat(),
        "pay_period_end": run.period_end.isoformat(),
        "scheduled_payment_date": run.pay_date.isoformat(),
        "actual_payment_date": _settled_on(db, item.id),
        "payroll_snapshot_hash": pick(doc.snapshot_hash, lambda: snap.get("inputHash"), "payroll_snapshot_hash"),
        "effective_ruleset_version": pick(doc.ruleset_version, lambda: ruleset_version(snap),
                                          "effective_ruleset_version"),
        "sat_catalog_release": (getattr(release, "catalog_release", None) or release_set_id(release)) if release else None,
        "cfdi_schema_release": (f"CFDI {release.cfdi_version} / Nómina {release.complement_version}"
                                + (f" rev {release.revision}" if release.revision else "")) if release else None,
        "issuing_cert_id": pick(doc.issuing_cert_token, lambda: cert_token(cred), "issuing_cert_id"),
        "pac_transaction_id": doc.idempotency_key,        # the PAC request key every retry reuses (no PAC txn id exists yet)
        "cfdi_uuid": doc.uuid,
        "xml_sha256": _stamped_xml_sha(db, doc),
        "signed_xml_sha256": doc.payload_hash,
        "renderer_version": mexico_payslip_service.RENDERER_VERSION,
        "document_locale": doc.document_locale or LOCALE,
        "issue_status": design_state(db, item, doc)["state"],
        "repo_status": doc.status,
        "delivery_proof_id": delivered.id if delivered is not None else None,
        "retention_policy_id": RETENTION_POLICY_PENDING,
        "supersedes_uuid": doc.replaces_uuid,
        "superseded_by_uuid": doc.replaced_by_uuid,
        "event_key": doc.event_key,
        "document_subtype": doc.document_subtype or document_subtype(run),
        "derived_fields": derived,
    }


# ── L3: the access / delivery log ────────────────────────────────────────────

ARTIFACTS = ("RECIBO_VIEW", "RECIBO_PDF", "DUPLICATE_PDF", "STAMPED_XML", "CFDI_RECEIPT", "HISTORY", "ENVELOPE")
CHANNELS = ("API", "UI", "OPERATOR", "EMAIL", "PORTAL", "PRINT")


def record_access(db: Session, org_id: int, event_type: str, artifact: str, channel: str, actor_id: Optional[int],
                  *, item_id: Optional[int] = None, document_id: Optional[int] = None,
                  employee_id: Optional[int] = None, proof_reference: Optional[str] = None,
                  commit: bool = True):
    from app.modules.payroll import mexico_payslip_service

    if artifact not in ARTIFACTS or channel not in CHANNELS:
        raise BadRequestException(f"unknown artifact / channel {artifact!r} / {channel!r}")
    m = _models()
    row = m.PayrollMxDocumentAccessEvent(
        organization_id=org_id, payslip_item_id=item_id, document_id=document_id, employee_id=employee_id,
        event_type=event_type, artifact=artifact, channel=channel,
        renderer_version=mexico_payslip_service.RENDERER_VERSION if artifact in ("RECIBO_VIEW", "RECIBO_PDF",
                                                                                 "DUPLICATE_PDF") else None,
        proof_reference=(proof_reference or None) and str(proof_reference)[:120], actor_id=actor_id)
    db.add(row)
    if commit:
        db.commit()
    return row


def access_log(db: Session, org_id: int, *, document_id: Optional[int] = None,
               item_id: Optional[int] = None) -> list:
    m = _models()
    A = m.PayrollMxDocumentAccessEvent
    q = db.query(A).filter(A.organization_id == org_id)
    if document_id is not None:
        q = q.filter(A.document_id == document_id)
    if item_id is not None:
        q = q.filter(A.payslip_item_id == item_id)
    return [{"id": r.id, "event": r.event_type, "artifact": r.artifact, "channel": r.channel,
             "documentId": r.document_id, "payslipItemId": r.payslip_item_id, "employeeId": r.employee_id,
             "rendererVersion": r.renderer_version, "proofReference": r.proof_reference, "actorId": r.actor_id,
             "at": r.occurred_at.isoformat() if r.occurred_at else None} for r in q.order_by(A.id)]


# ── publish / deliver, with the conflict checks ──────────────────────────────

def _d(v) -> Decimal:
    return Decimal(str(v)) if v not in (None, "") else Decimal("0")


def stamped_receipt(db: Session, doc) -> dict:
    """The stored stamped XML, parsed — refuses when there is none (unsigned / unstamped XML is never 'issued')."""
    from app.core import object_storage
    from app.modules.payroll import mexico_cfdi_receipt, mexico_cfdi_service

    ref = mexico_cfdi_service.stamped_xml_ref(db, doc)
    if not ref:
        raise MXRefuse("MX_CFDI_NOT_STAMPED_XML", f"CFDI {doc.id} has no stored stamped XML — it is not presented "
                                                  "as issued", doc.organization_id)
    try:
        return mexico_cfdi_receipt.receipt_from_xml(object_storage.read_bytes(ref))
    except BadRequestException as exc:
        raise MXRefuse("MX_CFDI_NOT_STAMPED_XML", f"CFDI {doc.id}: {exc}", doc.organization_id) from exc


def conflict_checks(db: Session, doc) -> dict:
    """Before an employee view is published from a stamped CFDI: XML, snapshot
    and receipt must agree, and the receiver must match the configured records.
    Values are compared in memory only; a refusal names the field, never its value."""
    from app.modules.payroll import mexico_employee_service, mexico_payslip_service
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    if doc.status != "STAMPED":
        raise MXRefuse("MX_CFDI_NOT_CURRENT", f"CFDI {doc.id} is {doc.status} — only a current STAMPED CFDI is "
                                              "published", doc.organization_id)
    xml = stamped_receipt(db, doc)
    item = db.get(PayslipItem, doc.payslip_item_id)
    run = db.get(PayrollRun, doc.payroll_run_id)
    view = mexico_payslip_service.recibo_view(db, item, run)
    xml_total = _d(xml["comprobante"].get("Total"))
    snapshot_net = _d(item.net_pay)
    view_net = _d(view["totals"]["net"].replace(",", ""))
    if not (xml_total == snapshot_net == view_net):
        raise MXRefuse("MX_CFDI_NET_MISMATCH", f"CFDI {doc.id}: net pay differs between the stamped XML, the payroll "
                                               "snapshot and the receipt — not published", doc.organization_id)
    employee = db.get(PayrollEmployee, item.employee_id)
    ids = (employee.compliance_fields or {}) if employee is not None else {}
    prof = mexico_employee_service._profile_on(db, item.employee_id, run.pay_date)
    configured = {"RFC": (ids.get("rfc") or "").strip().upper(), "CURP": (ids.get("curp") or "").strip().upper(),
                  "postal code": (getattr(prof, "mx_fiscal_postal_code", None) or "").strip()}
    stamped = {"RFC": (xml["receiver"].get("rfc") or "").strip().upper(),
               "CURP": (xml["receiver"].get("curp") or "").strip().upper(),
               "postal code": (xml["receiver"].get("postalCode") or "").strip()}
    wrong = [k for k in configured if configured[k] != stamped[k]]
    if wrong:
        raise MXRefuse("MX_CFDI_IDENTITY_MISMATCH", f"CFDI {doc.id}: the stamped receiver's {', '.join(wrong)} does not "
                                                    "match the employee's configured record — not published",
                       doc.organization_id)
    return {"xmlTotal": str(xml_total), "netPay": str(snapshot_net), "uuid": xml["certification"].get("UUID")}


def publish(db: Session, org_id: int, doc_id: int, actor_id: Optional[int]) -> dict:
    """PUBLISHED: the employee view is generated FROM the stamped XML (after the conflict checks)."""
    from app.modules.payroll import mexico_cfdi_service

    doc = mexico_cfdi_service._doc(db, org_id, doc_id)
    checks = conflict_checks(db, doc)
    if doc.published_at is None:
        doc.published_at = datetime.now(timezone.utc)
    mexico_cfdi_service._event(db, doc, "DOCUMENT_PUBLISHED", actor_id, {"uuid": checks["uuid"]})
    record_access(db, org_id, "PUBLISHED", "RECIBO_VIEW", "OPERATOR", actor_id, item_id=doc.payslip_item_id,
                  document_id=doc.id, employee_id=doc.employee_id, commit=False)
    db.commit()
    return {"documentId": doc.id, "state": design_state(db, db.get(_models().PayslipItem, doc.payslip_item_id),
                                                        doc)["state"], **checks}


def record_delivery(db: Session, org_id: int, doc_id: int, outcome: str, channel: str, proof_reference: Optional[str],
                    actor_id: Optional[int]) -> dict:
    """DELIVERED / DELIVERY_FAILED — an outcome the operator records with its proof (no identifier)."""
    from app.modules.payroll import mexico_cfdi_service

    if outcome not in ("DELIVERED", "DELIVERY_FAILED"):
        raise BadRequestException("outcome is DELIVERED or DELIVERY_FAILED")
    if channel not in CHANNELS:
        raise BadRequestException(f"channel is one of {CHANNELS}")
    doc = mexico_cfdi_service._doc(db, org_id, doc_id)
    if doc.published_at is None or doc.status != "STAMPED":
        raise MXRefuse("MX_CFDI_NOT_PUBLISHED", f"CFDI {doc.id} is not a published STAMPED document — nothing to "
                                                "deliver", org_id)
    if outcome == "DELIVERED" and not (proof_reference or "").strip():
        raise BadRequestException("a delivery needs its proof reference")
    doc.delivery_status = outcome
    mexico_cfdi_service._event(db, doc, outcome, actor_id, {"channel": channel})
    row = record_access(db, org_id, outcome, "RECIBO_PDF", channel, actor_id, item_id=doc.payslip_item_id,
                        document_id=doc.id, employee_id=doc.employee_id, proof_reference=proof_reference, commit=False)
    db.commit()
    return {"documentId": doc.id, "deliveryStatus": outcome, "deliveryProofId": row.id}


def stamped_xml_download(db: Session, org_id: int, doc_id: int, actor_id: Optional[int]) -> tuple:
    """(bytes, filename) of the stored stamped XML — the legal artifact; logged on every access."""
    from app.core import object_storage
    from app.modules.payroll import mexico_cfdi_service

    doc = mexico_cfdi_service._doc(db, org_id, doc_id)
    ref = mexico_cfdi_service.stamped_xml_ref(db, doc)
    if not ref or doc.status not in ("STAMPED", "CANCEL_REQUESTED", "CANCELLED", "REPLACED"):
        raise MXRefuse("MX_CFDI_NOT_STAMPED_XML", f"CFDI {doc.id} has no stored stamped XML to download", org_id)
    data = object_storage.read_bytes(ref)
    record_access(db, org_id, "DOWNLOADED", "STAMPED_XML", "API", actor_id, item_id=doc.payslip_item_id,
                  document_id=doc.id, employee_id=doc.employee_id)
    return data, f"cfdi-{doc.uuid or doc.id}.xml"


# ── L5: stale catalog ────────────────────────────────────────────────────────

def catalog_stale_reason(release, pay_date: date) -> Optional[str]:
    """MX_CFDI_CATALOG_STALE when the release's recorded validity window does not cover the pay date."""
    if release is None:
        return None
    start, end = getattr(release, "effective_from", None), getattr(release, "effective_to", None)
    if end is not None and pay_date > end:
        return f"the CFDI release {release.id} is valid until {end.isoformat()} — pay date {pay_date.isoformat()} " \
               "needs a later release"
    if start is not None and pay_date < start:
        return f"the CFDI release {release.id} is valid from {start.isoformat()} — pay date {pay_date.isoformat()} " \
               "needs an earlier release"
    return None


def log_payslip_downloads(db: Session, org_id: Optional[int], actor_id: Optional[int], item_ids: list,
                          channel: str = "API") -> int:
    """The generic payslip download routes: one DOWNLOADED RECIBO_PDF event per
    MEXICAN payslip (no-op for every other country) — MX24-AUD-002."""
    if not org_id or not item_ids:
        return 0
    m = _models()
    rows = db.query(m.PayslipItem.id, m.PayslipItem.employee_id).filter(
        m.PayslipItem.id.in_(list(item_ids)), m.PayslipItem.organization_id == org_id,
        m.PayslipItem.country_code == "MX").all()
    from app.modules.payroll import mexico_payslip_service

    for item_id, employee_id in rows:
        doc = mexico_payslip_service.latest_document(db, item_id)
        record_access(db, org_id, "DOWNLOADED", "RECIBO_PDF", channel, actor_id, item_id=item_id,
                      document_id=doc.id if doc is not None else None, employee_id=employee_id, commit=False)
    if rows:
        db.commit()
    return len(rows)
