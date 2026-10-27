"""
modules/payroll/mexico_decision_service.py
------------------------------------------
Mexico final mile X1: the decision register. Each open decision
(docs/mexico/DECISIONS_PENDING.md D-01 …, gap register C4 / C5 / C12) becomes a
governed record a gate owner can answer in the Super Admin workspace:

    OPEN --propose--> PROPOSED --approve (a different Super Admin)--> APPROVED
    APPROVED --transcribed (the value is seeded into a Draft pack)--> TRANSCRIBED
    PROPOSED --withdraw--> OPEN (the proposal is cleared, audited)
    OPEN --withdraw (with a reason)--> WITHDRAWN
    APPROVED / TRANSCRIBED --revise--> a new OPEN version; once that version is
        approved, the old one becomes SUPERSEDED

A recorded decision NEVER changes a calculation by itself. Approval produces a
transcription ticket: the content key(s), the value and the Draft pack it
belongs in; the value reaches the engine only through the existing path (seed
into a Draft pack, [PENDING G1], four-eyes approval, activation gated on
VERIFIED sources and signed gates). An APPROVED record is never edited.

Where the content has a grammar the chosen option is validated against it
before proposal and again before approval: D-01 through rounding.parse
(MODE:QUANTUM), D-02 against the Art. 96 periods, and the switches whose
readings are built (D-07, D-07b, D-13, D-14, D-21, D-22) against those values.
Every other decision is free text.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException, NotFoundException

ENTITY = "mx_decision"
STATUSES = ("OPEN", "PROPOSED", "APPROVED", "TRANSCRIBED", "WITHDRAWN", "SUPERSEDED")
LIVE = ("OPEN", "PROPOSED", "APPROVED", "TRANSCRIBED")


def _specs() -> dict:
    """code -> what the decision populates and how its answer is checked.
    Allowed values are read from the code that consumes them, never retyped."""
    from app.modules.payroll import mexico_cfdi_input as cfdi_input
    from app.modules.payroll.engine.countries import mexico_content as c
    from app.modules.payroll.engine.countries import mexico_rules as r

    return {
        "D-01": {"keys": ["mx_rounding_rule"], "kind": "ROUNDING_RULE", "codes": ["MX_ROUNDING_RULE_MISSING"]},
        "D-02": {"keys": ["mexico_content.MX_PAY_FREQUENCY_ISR_PERIOD['01']"], "kind": "PAY_PERIOD",
                 "allowed": list(c.MX_ISR_PERIODS) + ["UNMAPPED"]},
        "D-03": {"keys": ["mx_ceav_lowest_band_min_wage_ref"]},
        "D-04": {"keys": []},
        "D-05": {"keys": ["mexico_content.MX_WORKWEEK (January–April 2026 row)"]},
        "D-06": {"keys": ["mexico_content.MX_SPECIAL_PAY_ISN_INCLUSION[('CDMX', …)]"]},
        "D-07": {"keys": ["mexico_rules.MX_EXEMPTION_WAGE_REFERENCE"], "kind": "ENUM",
                 "allowed": list(r.WAGE_REFERENCES)},
        "D-07b": {"keys": ["mexico_rules.MX_SENIORITY_PREMIUM_WAGE_REFERENCE"], "kind": "ENUM",
                  "allowed": list(r.WAGE_REFERENCES), "codes": ["MX_SENIORITY_PREMIUM_WAGE_REFERENCE_UNDECIDED"],
                  "title": "Seniority-premium wage reference (LFT Arts. 485–486)", "from": "D-07", "gates": ["G5"],
                  "question": "LFT Arts. 485–486 bound the seniority-premium salary by the minimum wage and by twice "
                              "\"el salario mínimo del área geográfica de aplicación\". Since the 2016 de-indexation "
                              "decree (S34), is that reference the zone minimum wage or the UMA?"},
        "D-08": {"keys": ["mexico_rules.MX_SPECIAL_PAY_WITHHOLDING_METHOD"]},
        "D-09": {"keys": ["mexico_rules.MX_MONTHLY_ORDINARY_INCOME_DAYS"]},
        "D-10": {"keys": ["CDMX ISN pack (micro / small-employer benefit)"]},
        "D-11": {"keys": ["mexico_content.MX_TERMINATION_REASONS"]},
        "D-12": {"keys": ["mexico_rules.MX_INDEMNITY_SALARY_BASIS"]},
        "D-13": {"keys": ["mexico_rules.MX_SERVICE_YEARS_COUNT"], "kind": "ENUM",
                 "allowed": list(r.SERVICE_YEARS_COUNTS)},
        "D-14": {"keys": ["mexico_rules.MX_PTU_CAP_EXCESS", "mexico_rules.MX_PTU_HISTORY_AVERAGE"]},
        "D-16": {"keys": ["mexico_content.MX_OFFICIAL_HOLIDAYS"]},
        "D-17": {"keys": ["mx_hourly_rate_rule"]},
        "D-18": {"keys": ["mexico_content.MX_SBC_FIXED_INTEGRATION_RULE"]},
        "D-19": {"keys": ["mexico_content.MX_FIXED_DAYS_TERMINATION_RULE"]},
        "D-20": {"keys": ["mexico_cfdi_receipt.qr_total"]},
        "D-21": {"keys": ["mexico_cfdi_input.TIMEZONE_INCONSISTENT_ROW_READING"], "kind": "ENUM",
                 "allowed": list(cfdi_input.TIMEZONE_READINGS) + ["KEEP_REFUSING"]},
        "D-22": {"keys": ["mexico_rules.MX_FINIQUITO_ORDINARY_WITHHOLDING"], "kind": "ENUM",
                 "allowed": list(r.FINIQUITO_ORDINARY_METHODS)},
        "D-23": {"keys": []},
        "D-24": {"keys": ["report MX-RUN-VARIANCE: high-value delta threshold (MXN)"], "kind": "AMOUNT"},
        "D-25": {"keys": ["parallel payroll (X4): materiality threshold per difference (MXN)"], "kind": "AMOUNT",
                 "gates": ["G8"]},
        "C4": {"keys": ["mexico_cfdi_input.SDI_SOURCE"], "codes": ["MX_CFDI_INPUT_MISSING"]},
        "C5": {"keys": ["CFDI system concepts: INFONAVIT_CREDIT, VACATION_PAYOUT, ANNUAL_ADJUSTMENT_REFUND"]},
        "C12": {"keys": ["CFDI Receptor Sindicalizado field"]},
    }


# ── reading DECISIONS_PENDING.md and the gap register (the seed's source) ────

_CODES = re.compile(r"`(MX_[A-Z0-9_]+)`")
_SOURCES = re.compile(r"\bS(\d{1,2})\b")
_GATES = re.compile(r"\bG([1-8])\b")


def _sections(text: str) -> dict:
    out, current = {}, None
    for line in text.splitlines():
        m = re.match(r"^## (D-\d+) · (.+)$", line)
        if m:
            current = m.group(1)
            out[current] = {"title": m.group(2).strip(), "lines": []}
        elif line.startswith("## "):
            current = None
        elif current:
            out[current]["lines"].append(line)
    return out


def _bullet(lines: list, label: str) -> tuple:
    """(the text after "**<label>**", the sub-bullets under it)."""
    for i, line in enumerate(lines):
        if line.startswith(f"- **{label}"):
            head = re.sub(r"^- \*\*[^*]+\*\*\s*", "", line).strip()
            subs = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("  ") and nxt.strip():
                    subs.append(re.sub(r"^\s*(?:\d+\.|-)\s*", "", nxt).strip())
                elif nxt.strip():
                    break
            return head, subs
    return "", []


def _plain(text: str) -> str:
    """Markdown emphasis and code marks removed (the UI shows plain text)."""
    return re.sub(r"\*\*|`", "", text or "").strip()


def _sources(text: str) -> list:
    return sorted({f"S{int(n)}" for n in _SOURCES.findall(text)}, key=lambda s: int(s[1:]))


def parse_decisions(decisions_md: str, gap_register_md: str) -> list:
    """The OPEN decisions as seed records, from the two documents. A decision
    whose index row is not Open (D-15: resolved by sources) is skipped."""
    specs = _specs()
    index = {}
    for line in decisions_md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"D-\d+", cells[0]):
            index[cells[0]] = {"title": cells[1], "owner": cells[2], "blocks": cells[3], "status": cells[4]}
    sections = _sections(decisions_md)
    records = []

    def record(code, title, owner, question, options, block_text, section_text, gate_text=None):
        spec = specs.get(code, {})
        gates = sorted(set(spec.get("gates") or [f"G{g}" for g in _GATES.findall(gate_text or owner)]))
        # MX_CONTENT_MISSING is generic (any missing row): traced by content key, never as a block code
        codes = sorted((set(_CODES.findall(block_text)) | set(spec.get("codes", []))) - {"MX_CONTENT_MISSING"})
        return {"code": code, "title": _plain(title)[:200], "gates": gates, "owner_role": _plain(owner)[:60] or None,
                "question": _plain(question),
                "options": [{"label": _plain(o), "sources": _sources(o)} for o in options],
                "block_codes": codes, "content_keys": spec.get("keys", []),
                "answer_kind": spec.get("kind", "FREE_TEXT"), "allowed_values": spec.get("allowed"),
                "question_sources": _sources(section_text)}

    for code, row in index.items():
        if not row["status"].lower().startswith("open"):
            continue
        sec = sections.get(code, {"title": row["title"], "lines": []})
        question, _ = _bullet(sec["lines"], "Question")
        head, subs = _bullet(sec["lines"], "Options")
        options = subs or ([head] if head else [])
        text = "\n".join(sec["lines"])
        records.append(record(code, sec["title"], row["owner"], question or row["title"], options,
                              row["blocks"], text))
    for code, spec in specs.items():                      # records with no index row of their own (D-07b)
        if spec.get("from") and code not in index and spec["from"] in sections:
            sec = sections[spec["from"]]
            text = "\n".join(sec["lines"])
            question = spec.get("question") or _bullet(sec["lines"], "Question")[0]
            records.append(record(code, spec["title"], "G5 owner", question,
                                  [f"{v}" for v in spec.get("allowed") or []], "", text))
    for line in gap_register_md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[0] in ("C4", "C5", "C12"):
            title = re.sub(r"\*\*", "", cells[1])
            records.append(record(cells[0], title, cells[4], f"{title}. Today: {cells[2]}", [cells[3]],
                                  cells[2], " ".join(cells), gate_text=cells[5]))
    return records


def _docs_root() -> Path:
    from app.modules.payroll import mexico_sources

    return mexico_sources.REPO_ROOT / "docs" / "mexico"


def seed_decisions(db: Session, decisions_md: Optional[str] = None, gap_register_md: Optional[str] = None) -> dict:
    """Load every OPEN decision that has no record yet (idempotent: an existing
    code is never touched, whatever its state). Never run on deploy: the
    script scripts/seed_mexico_decisions.py requires a confirmed target."""
    from app.modules.payroll.models import PayrollMxDecision as D

    root = _docs_root()
    decisions_md = decisions_md if decisions_md is not None else (root / "DECISIONS_PENDING.md").read_text("utf-8")
    gap_register_md = gap_register_md if gap_register_md is not None else \
        (root / "MEXICO_COMPLETION_GAP_REGISTER.md").read_text("utf-8")
    existing = {code for (code,) in db.query(D.code).distinct()}
    added = []
    for rec in parse_decisions(decisions_md, gap_register_md):
        if rec["code"] in existing:
            continue
        db.add(D(version=1, status="OPEN", **rec))
        added.append(rec["code"])
    db.flush()
    return {"added": added, "skipped": sorted(existing)}


# ── answers ──────────────────────────────────────────────────────────────────

def validate_answer(row, chosen: str) -> None:
    """Refuse an answer the consuming code could not read."""
    chosen = (chosen or "").strip()
    if not chosen:
        raise BadRequestException("A proposal needs the chosen option")
    if row.answer_kind == "ROUNDING_RULE":
        from app.modules.payroll.engine.jurisdictions.mexico import rounding
        from app.modules.payroll.engine.jurisdictions.mexico.errors import MXBlock

        try:
            rounding.parse(chosen)
        except MXBlock as exc:
            raise BadRequestException(f"{row.code}: {exc.reason}")
    elif row.answer_kind == "AMOUNT":
        from decimal import Decimal, InvalidOperation

        try:
            amount = Decimal(chosen)
        except (InvalidOperation, ValueError):
            amount = None
        if amount is None or not amount.is_finite() or amount < 0:
            raise BadRequestException(f"{row.code}: {chosen!r} is not an amount (MXN, zero or more)")
    elif row.answer_kind in ("ENUM", "PAY_PERIOD") and chosen not in (row.allowed_values or []):
        raise BadRequestException(f"{row.code}: {chosen!r} is not one of {', '.join(row.allowed_values or [])}")


def _hash(row) -> str:
    body = {"code": row.code, "version": row.version, "chosen": row.chosen_option, "rationale": row.rationale,
            "sources": row.cited_sources or [], "keys": row.content_keys or []}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def ticket(row) -> Optional[dict]:
    """The transcription hand-off of an APPROVED decision: what an engineer
    seeds, where, and the citation the row carries. Draft packs only."""
    if row.status not in ("APPROVED", "TRANSCRIBED"):
        return None
    return {"decision": row.code, "version": row.version, "contentKeys": row.content_keys or [],
            "value": row.chosen_option, "citation": f"DECISION/{row.code}#{(row.content_hash or '')[:12]}",
            "target": "the next Draft version of the pack that carries the key (never an Active pack)",
            "then": "seed it, mark it [PENDING G1], four-eyes approval; activation still needs VERIFIED sources "
                    "and the signed gates",
            "transcribed": row.status == "TRANSCRIBED", "transcriptionRef": row.transcription_ref}


def view(row) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"id": row.id, "code": row.code, "version": row.version, "title": row.title, "gates": row.gates or [],
            "ownerRole": row.owner_role, "question": row.question, "options": row.options or [],
            "blockCodes": row.block_codes or [], "contentKeys": row.content_keys or [],
            "questionSources": row.question_sources or [],
            "answerKind": row.answer_kind, "allowedValues": row.allowed_values, "status": row.status,
            "chosenOption": row.chosen_option, "rationale": row.rationale, "citedSources": row.cited_sources or [],
            "contentHash": row.content_hash, "supersedesId": row.supersedes_id,
            "proposedById": row.proposed_by_id, "proposedAt": iso(row.proposed_at),
            "approvedById": row.approved_by_id, "approvedAt": iso(row.approved_at),
            "transcribedAt": iso(row.transcribed_at), "transcriptionRef": row.transcription_ref,
            "ticket": ticket(row), "editable": False}


def _row(db: Session, decision_id: int):
    from app.modules.payroll.models import PayrollMxDecision as D

    row = db.get(D, decision_id)
    if row is None:
        raise NotFoundException("Mexico decision", decision_id)
    return row


def _now():
    return datetime.now(timezone.utc)


def _audit(db, actor_id, action, row, old=None, new=None, reason=None):
    from app.modules.payroll import mexico_service

    mexico_service._audit(db, actor_id=actor_id, action=action, entity_type=ENTITY, entity_id=row.id, old=old,
                          new=new, reason=reason)


def _refuse(db, row, attempted, actor_id, message):
    from app.modules.payroll import mexico_service

    mexico_service._refuse(db, ENTITY, row.id if row is not None else 0, attempted, actor_id, message)


def list_mx_decisions(db: Session, gate: Optional[str] = None, status: Optional[str] = None) -> list:
    from app.modules.payroll.models import PayrollMxDecision as D

    rows = db.query(D).order_by(D.code, D.version).all()
    if gate:
        rows = [r for r in rows if gate in (r.gates or [])]
    if status:
        rows = [r for r in rows if r.status == status]
    return [view(r) for r in rows]


def get_mx_decision(db: Session, decision_id: int) -> dict:
    return view(_row(db, decision_id))


def propose_mx_decision(db: Session, decision_id: int, data: dict, actor_id: Optional[int]) -> dict:
    row = _row(db, decision_id)
    if actor_id is None:
        _refuse(db, row, "propose", actor_id, "A proposal needs an identified Super Admin.")
    if row.status != "OPEN":
        _refuse(db, row, "propose", actor_id, f"only an OPEN decision can be proposed (this one is {row.status})")
    chosen = str((data or {}).get("chosen_option") or "").strip()
    rationale = str((data or {}).get("rationale") or "").strip()
    sources = [str(s).strip() for s in ((data or {}).get("cited_sources") or []) if str(s).strip()]
    if not rationale:
        _refuse(db, row, "propose", actor_id, "A proposal needs its rationale")
    if not sources:
        _refuse(db, row, "propose", actor_id, "A proposal cites at least one source (a saved S-code or a document)")
    try:
        validate_answer(row, chosen)
    except BadRequestException as exc:
        _refuse(db, row, "propose", actor_id, str(exc.detail if hasattr(exc, "detail") else exc))
    row.chosen_option, row.rationale, row.cited_sources = chosen, rationale, sources
    row.owner_role = str((data or {}).get("owner_role") or row.owner_role or "")[:60] or None
    row.status, row.proposed_by_id, row.proposed_at = "PROPOSED", actor_id, _now()
    row.content_hash = _hash(row)
    _audit(db, actor_id, "propose", row, old={"status": "OPEN"},
           new={"status": "PROPOSED", "chosen": chosen, "hash": row.content_hash})
    db.commit()
    db.refresh(row)
    return view(row)


def approve_mx_decision(db: Session, decision_id: int, actor_id: Optional[int]) -> dict:
    from app.modules.payroll.models import PayrollMxDecision as D

    row = _row(db, decision_id)
    if actor_id is None:
        _refuse(db, row, "approve", actor_id, "Approval needs an identified Super Admin.")
    if row.status != "PROPOSED":
        _refuse(db, row, "approve", actor_id, f"only a PROPOSED decision can be approved (this one is {row.status})")
    if row.proposed_by_id == actor_id:
        _refuse(db, row, "approve", actor_id,
                "You proposed this decision — a different Super Admin must approve it (four-eyes).")
    try:
        validate_answer(row, row.chosen_option)
    except BadRequestException as exc:
        _refuse(db, row, "approve", actor_id, str(exc.detail if hasattr(exc, "detail") else exc))
    if row.content_hash != _hash(row):
        _refuse(db, row, "approve", actor_id, "the proposal changed after it was hashed — propose it again")
    row.status, row.approved_by_id, row.approved_at = "APPROVED", actor_id, _now()
    if row.supersedes_id is not None:
        old = db.get(D, row.supersedes_id)
        if old is not None and old.status in ("APPROVED", "TRANSCRIBED"):
            _audit(db, actor_id, "supersede", old, old={"status": old.status}, new={"status": "SUPERSEDED",
                                                                                    "by": row.id})
            old.status = "SUPERSEDED"
    _audit(db, actor_id, "approve", row, old={"status": "PROPOSED"},
           new={"status": "APPROVED", "hash": row.content_hash})
    db.commit()
    db.refresh(row)
    return view(row)


def withdraw_mx_decision(db: Session, decision_id: int, data: dict, actor_id: Optional[int]) -> dict:
    row = _row(db, decision_id)
    reason = str((data or {}).get("reason") or "").strip()
    if actor_id is None or not reason:
        _refuse(db, row, "withdraw", actor_id, "Withdrawing needs an identified Super Admin and a reason.")
    if row.status == "PROPOSED":                           # the proposal goes; the question stays open
        old = {"status": "PROPOSED", "chosen": row.chosen_option, "hash": row.content_hash}
        row.chosen_option = row.rationale = row.cited_sources = row.content_hash = None
        row.proposed_by_id = row.proposed_at = None
        row.status = "OPEN"
    elif row.status == "OPEN":
        old = {"status": "OPEN"}
        row.status = "WITHDRAWN"
    else:
        _refuse(db, row, "withdraw", actor_id,
                f"an {row.status} decision is not withdrawn — revise it (a new version) instead")
    _audit(db, actor_id, "withdraw", row, old=old, new={"status": row.status}, reason=reason)
    db.commit()
    db.refresh(row)
    return view(row)


def revise_mx_decision(db: Session, decision_id: int, actor_id: Optional[int]) -> dict:
    """A change to an APPROVED decision is a new OPEN version; the approved one
    stays in force until the new version is approved."""
    from app.modules.payroll.models import PayrollMxDecision as D

    row = _row(db, decision_id)
    if actor_id is None:
        _refuse(db, row, "revise", actor_id, "A revision needs an identified Super Admin.")
    if row.status not in ("APPROVED", "TRANSCRIBED"):
        _refuse(db, row, "revise", actor_id, f"only an APPROVED decision is revised (this one is {row.status})")
    if db.query(D).filter(D.code == row.code, D.status.in_(("OPEN", "PROPOSED"))).first() is not None:
        _refuse(db, row, "revise", actor_id, f"{row.code} already has an open revision")
    latest = max(v for (v,) in db.query(D.version).filter(D.code == row.code))
    new = D(code=row.code, version=latest + 1, title=row.title, gates=list(row.gates or []),
            owner_role=row.owner_role, question=row.question, options=list(row.options or []),
            question_sources=list(row.question_sources or []),
            block_codes=list(row.block_codes or []), content_keys=list(row.content_keys or []),
            answer_kind=row.answer_kind, allowed_values=row.allowed_values, status="OPEN", supersedes_id=row.id)
    db.add(new)
    db.flush()
    _audit(db, actor_id, "revise", new, new={"status": "OPEN", "supersedes": row.id, "version": new.version})
    db.commit()
    db.refresh(new)
    return view(new)


def mark_mx_decision_transcribed(db: Session, decision_id: int, data: dict, actor_id: Optional[int]) -> dict:
    row = _row(db, decision_id)
    ref = str((data or {}).get("reference") or "").strip()
    if actor_id is None or not ref:
        _refuse(db, row, "transcribed", actor_id,
                "Marking a decision transcribed needs an identified Super Admin and the reference (commit / Draft "
                "pack) that carries it.")
    if row.status != "APPROVED":
        _refuse(db, row, "transcribed", actor_id,
                f"only an APPROVED decision is transcribed (this one is {row.status})")
    row.status, row.transcribed_by_id, row.transcribed_at, row.transcription_ref = "TRANSCRIBED", actor_id, \
        _now(), ref[:200]
    _audit(db, actor_id, "transcribed", row, old={"status": "APPROVED"}, new={"status": "TRANSCRIBED", "ref": ref})
    db.commit()
    db.refresh(row)
    return view(row)


# ── traceability ─────────────────────────────────────────────────────────────

def mx_decisions_for_block(db: Session, block_code: str) -> list:
    """The live decisions whose answer would clear an engine block code."""
    from app.modules.payroll.models import PayrollMxDecision as D

    return [{"id": r.id, "code": r.code, "version": r.version, "title": r.title, "status": r.status}
            for r in db.query(D).filter(D.status.in_(LIVE)).order_by(D.code, D.version)
            if block_code in (r.block_codes or [])]


def open_by_gate(db: Session) -> dict:
    """{gate: number of decisions not yet APPROVED} (OPEN or PROPOSED)."""
    from app.modules.payroll.models import PayrollMxDecision as D

    out: dict = {}
    for r in db.query(D).filter(D.status.in_(("OPEN", "PROPOSED"))):
        for g in r.gates or []:
            out[g] = out.get(g, 0) + 1
    return out
