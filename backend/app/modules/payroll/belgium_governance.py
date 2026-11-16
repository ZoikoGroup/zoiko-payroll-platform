"""Belgium (ZP-BE-ENG-001) Blocks K2 / K3: release-gate evidence and owner-decision records (Super Admin).

K2 — gate evidence (payroll_be_gate_evidence). A Super Admin records evidence for a gate against one of the evidence
tags the readiness checks require (belgium_readiness: BE-CONNECTIVITY-*, BE-FILING-E2E, BE-SIGNOFF-*, BE-OWNER-*),
or as SUPPORTING (never counted). ANOTHER Super Admin accepts or rejects it (four-eyes in the service and in the
database). Readiness counts an ACCEPTED row only for the exact tag a gate check requires; every other check of the
gate (signed content, certified adapters, accepted filings, parallel cycles, keys …) is still derived from data.
Evidence alone never marks a gate met.

K3 — decision records (payroll_be_decisions). Per gap key (G-01 …): a proposal (question, text, sources, linked
content keys) by one person, DECIDED (decided value) by another; a later decision of the same gap supersedes the
earlier one (linked, kept). A decision does NOT change content: its value reaches the engine only when the linked
content rows are entered and signed through the governed console (four-eyes) — the record shows whether they are.
Nothing is pre-decided: imported proposals stay PROPOSED until reviewers act.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import belgium_service as be

SUPPORTING = "SUPPORTING"
GATE_KEYS = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")

# Decision gaps under governance and the content rows each decided value feeds (none = a product / legal decision
# recorded only; G-30 feeds the employer registration vocabulary, G-21 the retention decision of readiness G6).
DECISION_GAPS = {
    "G-01": ("Consolidated calculation order", ()),
    "G-02": ("Rounding per obligation", ("be_rounding_onss", "be_rounding_withholding", "be_rounding_holiday")),
    "G-06": ("Special social security contribution (BSSC; G-06 / G-17)", ()),
    "G-11": ("Pay-frequency scope", ("be_supported_pay_frequencies",)),
    "G-12": ("Definition of a high-risk change for four-eyes", ()),
    "G-13": ("Legal language of employee documents", ()),
    "G-16": ("Identifier formats and check digits (KBO/BCE, ONSS, NISS)", ()),
    "G-21": ("Statutory retention periods", ()),
    "G-26": ("Allocation of employee ONSS between regular and exceptional withholding bases",
             ("be_wht_taxable_basis_rule",)),
    "G-30": ("Withholding declaration frequencies", ()),
}
WORKBOOK = Path(__file__).resolve().parents[4] / "docs" / "belgium" / "content" / "BE_2026_AI_DRAFT.xlsx"
REGISTER = Path(__file__).resolve().parents[4] / "docs" / "belgium" / "BELGIUM_GAPS_AND_DECISIONS.md"


def _models():
    from app.modules.payroll import models

    return models


def _text(value, name: str, limit: int, required: bool = True) -> Optional[str]:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise BadRequestException(f"{name} is required.")
    return text[:limit] or None


# ── K2: gate evidence ──────────────────────────────────────────────────────────
def be_gate_evidence_requirements() -> dict:
    """{gate: [evidence tags its readiness checks require]} — taken from belgium_readiness, never restated here."""
    from app.modules.payroll import belgium_readiness as r

    required = {g: [] for g in GATE_KEYS}
    required["G3"] = list(r.CONNECTIVITY_TAGS)
    required["G5"] = [r.FILING_E2E_TAG]
    required["G6"] = list(r.SECURITY_TAGS)
    required["G7"] = list(r.OWNER_TAGS)
    return required


def be_record_gate_evidence(db: Session, data: dict, actor_id) -> object:
    E = _models().PayrollBeGateEvidence
    data = dict(data or {})
    gate = str(data.get("gate") or "").strip().upper()
    if gate not in GATE_KEYS:
        raise BadRequestException(f"gate must be one of {', '.join(GATE_KEYS)}.")
    evidence_type = str(data.get("evidenceType") or "").strip().upper()
    allowed = be_gate_evidence_requirements()[gate] + [SUPPORTING]
    if evidence_type not in allowed:
        raise BadRequestException(f"evidenceType for {gate} must be one of {', '.join(allowed)} (SUPPORTING evidence "
                                  "is kept but never counted by a gate check).")
    source_id = data.get("sourceArtifactId")
    if source_id not in (None, ""):
        from app.modules.payroll.models import SourceArtifact

        if db.get(SourceArtifact, int(source_id)) is None:
            raise BadRequestException("sourceArtifactId does not exist.")
    row = E(gate=gate, evidence_type=evidence_type, reference=_text(data.get("reference"), "reference", 300),
            note=_text(data.get("note"), "note", 500, required=False),
            source_artifact_id=int(source_id) if source_id not in (None, "") else None, status="PENDING",
            recorded_by_id=actor_id)
    db.add(row)
    db.flush()
    be._audit(db, actor_id, "recorded", "be_gate_evidence", row.id,
              new={"gate": gate, "type": evidence_type, "reference": row.reference})
    return row


def be_decide_gate_evidence(db: Session, evidence_id: int, outcome: str, reason, actor_id) -> object:
    """ACCEPTED / REJECTED by a person other than the recorder; a decided row is never changed again."""
    E = _models().PayrollBeGateEvidence
    row = db.get(E, evidence_id)
    if row is None:
        raise NotFoundException("Belgian gate evidence")
    outcome = str(outcome or "").strip().upper()
    if outcome not in ("ACCEPTED", "REJECTED"):
        raise BadRequestException("outcome must be ACCEPTED or REJECTED.")
    if row.status != "PENDING":
        raise BadRequestException(f"This evidence is already {row.status}; record new evidence instead.")
    if actor_id is None or actor_id == row.recorded_by_id:
        raise BadRequestException("Evidence is accepted or rejected by a person other than the one who recorded it "
                                  "(four-eyes).")
    row.status, row.decided_by_id, row.decided_at = outcome, actor_id, datetime.utcnow()
    row.decision_reason = _text(reason, "reason", 300)
    db.flush()
    be._audit(db, actor_id, outcome.lower(), "be_gate_evidence", row.id,
              old={"status": "PENDING"}, new={"status": outcome}, reason=row.decision_reason)
    return row


def be_accepted_gate_evidence(db: Session, tag: str):
    """The latest ACCEPTED evidence row for exactly this tag, or None (what readiness counts)."""
    E = _models().PayrollBeGateEvidence
    return (db.query(E).filter(E.evidence_type == tag, E.status == "ACCEPTED")
            .order_by(E.decided_at.desc(), E.id.desc()).first())


def be_gate_evidence_view(row) -> dict:
    return {"id": row.id, "gate": row.gate, "evidenceType": row.evidence_type, "reference": row.reference,
            "note": row.note, "sourceArtifactId": row.source_artifact_id, "status": row.status,
            "recordedBy": row.recorded_by_id, "recordedAt": row.recorded_at.isoformat() if row.recorded_at else None,
            "decidedBy": row.decided_by_id, "decidedAt": row.decided_at.isoformat() if row.decided_at else None,
            "decisionReason": row.decision_reason, "counted": row.status == "ACCEPTED" and row.evidence_type != SUPPORTING}


def be_list_gate_evidence(db: Session) -> dict:
    E = _models().PayrollBeGateEvidence
    rows = db.query(E).order_by(E.gate, E.id.desc()).all()
    required = be_gate_evidence_requirements()
    return {g: {"requiredEvidence": required[g], "evidence": [be_gate_evidence_view(r) for r in rows if r.gate == g]}
            for g in GATE_KEYS}


# ── K3: decision records ───────────────────────────────────────────────────────
def be_propose_decision(db: Session, data: dict, actor_id) -> object:
    D = _models().PayrollBeDecision
    data = dict(data or {})
    gap = str(data.get("gapKey") or "").strip().upper()
    if gap not in DECISION_GAPS:
        raise BadRequestException(f"gapKey must be one of {', '.join(DECISION_GAPS)}.")
    row = D(gap_key=gap, question=_text(data.get("question") or DECISION_GAPS[gap][0], "question", 300),
            proposal_text=_text(data.get("proposal"), "proposal", 4000),
            source_references=_text(data.get("sources"), "sources", 4000, required=False),
            content_keys=list(DECISION_GAPS[gap][1]), status="PROPOSED", proposed_by_id=actor_id)
    db.add(row)
    db.flush()
    be._audit(db, actor_id, "proposed", "be_decision", row.id, new={"gap": gap})
    return row


def be_decide(db: Session, decision_id: int, data: dict, actor_id) -> object:
    """DECIDED by a person other than the proposer; the gap's previous DECIDED record becomes SUPERSEDED (linked)."""
    D = _models().PayrollBeDecision
    row = db.get(D, decision_id)
    if row is None:
        raise NotFoundException("Belgian decision record")
    if row.status != "PROPOSED":
        raise BadRequestException(f"Only a PROPOSED record is decided (this one is {row.status}); propose again to "
                                  "change a decision.")
    if actor_id is None or actor_id == row.proposed_by_id:
        raise BadRequestException("A decision is made by a person other than the proposer (four-eyes).")
    data = dict(data or {})
    value = _text(data.get("decidedValue"), "decidedValue", 4000)
    reason = _text(data.get("reason"), "reason", 300)
    previous = (db.query(D).filter(D.gap_key == row.gap_key, D.status == "DECIDED", D.id != row.id)
                .order_by(D.id).all())
    row.status, row.decided_value, row.decided_by_id = "DECIDED", value, actor_id
    row.decided_at, row.decision_reason = datetime.utcnow(), reason
    db.flush()
    for old in previous:
        old.status, old.superseded_by_id = "SUPERSEDED", row.id
        be._audit(db, actor_id, "superseded", "be_decision", old.id, new={"supersededBy": row.id})
    db.flush()
    be._audit(db, actor_id, "decided", "be_decision", row.id, new={"gap": row.gap_key}, reason=reason)
    return row


def be_current_decision(db: Session, gap_key: str):
    D = _models().PayrollBeDecision
    return db.query(D).filter(D.gap_key == gap_key, D.status == "DECIDED").order_by(D.id.desc()).first()


def _content_state(db: Session, keys) -> list:
    """For each linked content key: signed or not in the canonical Belgian pack (read-only)."""
    if not keys:
        return []
    from app.modules.payroll.engine.countries import belgium_content as content
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    pack = (db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == content.BE_2026[0])
            .order_by(JurisdictionPack.id.desc()).first())
    out = []
    for key in keys:
        row = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                                 ContributionRate.component_key == key).first() if pack else None)
        out.append({"key": key, "signed": bool(row is not None and content.PENDING_MARK not in (row.label or ""))})
    return out


def be_decision_view(db: Session, row) -> dict:
    return {"id": row.id, "gapKey": row.gap_key, "question": row.question, "proposal": row.proposal_text,
            "sources": row.source_references, "status": row.status, "decidedValue": row.decided_value,
            "proposedBy": row.proposed_by_id, "proposedAt": row.proposed_at.isoformat() if row.proposed_at else None,
            "decidedBy": row.decided_by_id, "decidedAt": row.decided_at.isoformat() if row.decided_at else None,
            "reason": row.decision_reason, "supersededBy": row.superseded_by_id,
            "contentKeys": _content_state(db, row.content_keys or [])}


def be_list_decisions(db: Session) -> list:
    D = _models().PayrollBeDecision
    rows = db.query(D).order_by(D.gap_key, D.id.desc()).all()
    out = []
    for gap, (question, keys) in DECISION_GAPS.items():
        history = [be_decision_view(db, r) for r in rows if r.gap_key == gap]
        current = next((h for h in history if h["status"] == "DECIDED"), None)
        out.append({"gapKey": gap, "question": question, "state": "DECIDED" if current else
                    ("PROPOSED" if any(h["status"] == "PROPOSED" for h in history) else "OPEN"),
                    "current": current, "history": history, "contentKeys": _content_state(db, keys)})
    return out


def _register_text(gap: str) -> Optional[str]:
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 3 and cells[1] == gap:
            return cells[3]
    return None


def be_import_decision_proposals(db: Session, actor_id) -> list:
    """PROPOSED records from the AI-drafted workbook's "Decision proposals" sheet, and for G-11 / G-12 the text of
    the gaps register. Only for gaps with no record yet; the importer is the proposer; nothing is decided."""
    import openpyxl

    D = _models().PayrollBeDecision
    have = {g for (g,) in db.query(D.gap_key).distinct()}
    proposals = {}
    sheet = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)["Decision proposals"]
    for row in list(sheet.iter_rows(values_only=True))[1:]:
        if not row or not row[0]:
            continue
        gap = str(row[0]).split("/")[0].strip().upper()
        if gap in DECISION_GAPS:
            proposals[gap] = {"question": row[1], "proposal": row[2], "sources": row[3]}
    for gap in ("G-11", "G-12"):
        text = _register_text(gap)
        if text:
            proposals.setdefault(gap, {"question": DECISION_GAPS[gap][0], "proposal": text,
                                       "sources": "docs/belgium/BELGIUM_GAPS_AND_DECISIONS.md (product decision)"})
    created = []
    for gap in DECISION_GAPS:
        if gap in have or gap not in proposals:
            continue
        p = proposals[gap]
        created.append(be_propose_decision(db, {"gapKey": gap, "question": p["question"], "proposal": p["proposal"],
                                                "sources": p["sources"]}, actor_id))
    return created
