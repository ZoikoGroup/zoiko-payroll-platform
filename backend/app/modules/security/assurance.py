"""
modules/security/assurance.py
-----------------------------
Privacy assurance: the ZP-PRIV control register, recorded independent
reviews and the attestation verdict (ZP-PRIV Part 12).

One source of truth for the Privacy Assurance page and
scripts/run_privacy_attestation.py:

* the register is docs/privacy/control_register.yaml (46 controls);
* engineering statuses are only NT, ENGINEERING_COMPLETE_AWAITING_REVIEW or
  FAIL - anything else in the file blocks the attestation;
* reviews come from the register's ``reviews:`` list and from
  CONTROL_REVIEW_RECORDED security events (append-only, hash-chained; written
  by the "Record review" action);
* the verdict is BLOCKED or NOT VERIFIED. VERIFIED is only possible when every
  control has an accepted review by a named reviewer AND the register names
  the independent reviewer - this module never infers it otherwise.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTER_PATH = REPO_ROOT / "docs" / "privacy" / "control_register.yaml"
DEFECTS_PATH = REPO_ROOT / "docs" / "privacy" / "defect_register.csv"

ALLOWED_STATUSES = ("NT", "ENGINEERING_COMPLETE_AWAITING_REVIEW", "FAIL")
EXPECTED_TOTAL, EXPECTED_P0, EXPECTED_P1 = 46, 41, 5
EXPECTED_P1_IDS = {"A06", "D09", "E07", "F03", "F07"}
REVIEW_EVENT = "CONTROL_REVIEW_RECORDED"
DECISIONS = ("accepted", "rejected")

VERDICT_BLOCKED, VERDICT_NOT_VERIFIED, VERDICT_VERIFIED = "BLOCKED", "NOT VERIFIED", "VERIFIED"


class RegisterError(Exception):
    pass


def _z(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_register(path: Path = REGISTER_PATH) -> dict:
    import yaml

    if not path.exists():
        raise RegisterError(f"control register not found at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("controls"), list):
        raise RegisterError("control register has no controls list")
    return data


def control_ids(path: Path = REGISTER_PATH) -> set:
    return {c["id"] for c in load_register(path)["controls"]}


def open_blocking_defects(path: Path = DEFECTS_PATH) -> list:
    """Open critical privacy defects and open P0 exceptions (F06)."""
    if not path.exists():
        return [{"id": "-", "reason": f"defect register missing: {path.name}"}]
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    blocking = []
    for row in rows:
        status = (row.get("status") or "").strip().lower()
        if status in ("closed", "resolved", "wont_fix_accepted"):
            continue
        severity = (row.get("severity") or "").strip().lower()
        kind = (row.get("type") or "").strip().lower()
        priority = (row.get("control_priority") or "").strip().upper()
        if severity == "critical" or (kind == "exception" and priority == "P0"):
            blocking.append({"id": row.get("id"), "reason": f"{severity or kind} {row.get('control_id') or ''}".strip()})
    return blocking


CODEOWNERS_PATH = REPO_ROOT / ".github" / "CODEOWNERS"


def privacy_paths(path: Path = CODEOWNERS_PATH) -> list:
    """The change-controlled privacy paths (F07), read from CODEOWNERS."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.split()[0].lstrip("/"))
    return out


def changed_privacy_paths(since_sha: str, head: str = "HEAD") -> Optional[list]:
    """Files under the privacy paths changed since ``since_sha`` (None when
    git cannot answer - callers treat that as invalidated)."""
    import subprocess

    paths = privacy_paths()
    try:
        out = subprocess.run(["git", "diff", "--name-only", f"{since_sha}..{head}", "--", *paths],
                             capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT))
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0:
        return None
    return [line for line in out.stdout.splitlines() if line.strip()]


def db_reviews(db) -> list:
    """Reviews recorded through the API (security events)."""
    from app.modules.auth.models import User
    from app.modules.security.models import SecurityEvent

    rows = (db.query(SecurityEvent).filter(SecurityEvent.event_type == REVIEW_EVENT)
            .order_by(SecurityEvent.id).all())
    emails = {}
    ids = {r.actor_user_id for r in rows if r.actor_user_id}
    if ids:
        emails = {u.id: u.email for u in db.query(User).filter(User.id.in_(ids)).all()}
    return [{"control": r.target_id, "reviewerUserId": r.actor_user_id,
             "reviewer": emails.get(r.actor_user_id), "reviewerEmail": emails.get(r.actor_user_id),
             "decision": (r.reason_code or "").lower(), "proofReference": r.ticket_reference,
             "recordedAt": _z(r.occurred_at), "source": "platform"} for r in rows]


def _register_reviews(register: dict) -> list:
    out = []
    for r in register.get("reviews") or []:
        out.append({"control": r.get("control"), "reviewerUserId": None, "reviewer": r.get("reviewer"),
                    "reviewerEmail": None, "decision": str(r.get("decision") or "").lower(),
                    "proofReference": r.get("proof_reference"), "recordedAt": _z(r.get("recorded_at")),
                    "source": "register"})
    return out


def compute_verdict(register: dict, reviews: list, defects: Optional[list] = None, test_failures: int = 0) -> dict:
    """Counts + verdict. Pure function (no I/O) so it is easy to test."""
    controls = register["controls"]
    reasons_blocked, reasons_open = [], []
    by_id = {}
    for c in controls:
        if c.get("id") in by_id:
            reasons_blocked.append(f"duplicate control id {c.get('id')}")
        by_id[c.get("id")] = c
        if c.get("status") not in ALLOWED_STATUSES:
            reasons_blocked.append(f"{c.get('id')}: status {c.get('status')!r} is not allowed "
                                   f"(only {', '.join(ALLOWED_STATUSES)}; PASS is never recorded by engineering)")
    p0 = [c for c in controls if c.get("priority") == "P0"]
    p1 = [c for c in controls if c.get("priority") == "P1"]
    if len(controls) != EXPECTED_TOTAL or len(p0) != EXPECTED_P0 or len(p1) != EXPECTED_P1:
        reasons_blocked.append(f"register has {len(controls)} controls ({len(p0)} P0 / {len(p1)} P1); "
                               f"expected {EXPECTED_TOTAL} ({EXPECTED_P0} / {EXPECTED_P1})")
    if {c.get("id") for c in p1} != EXPECTED_P1_IDS:
        reasons_blocked.append("P1 set differs from A06, D09, E07, F03, F07")

    latest = {}
    for r in reviews:
        if r.get("control") in by_id and r.get("decision") in DECISIONS and r.get("reviewer"):
            latest[r["control"]] = r
    for cid, r in latest.items():
        if r["decision"] == "rejected":
            reasons_blocked.append(f"{cid}: rejected by reviewer {r['reviewer']} ({r.get('proofReference')})")
    failed = [c["id"] for c in controls if c.get("status") == "FAIL"]
    if failed:
        reasons_blocked.append(f"controls failing: {', '.join(failed)}")
    for d in defects or []:
        reasons_blocked.append(f"open blocking defect {d['id']}: {d['reason']}")
    if test_failures:
        reasons_blocked.append(f"{test_failures} privacy test(s) failed in this run")

    def bucket(group):
        out = {s: 0 for s in ALLOWED_STATUSES}
        out["REVIEWED_ACCEPTED"] = 0
        for c in group:
            r = latest.get(c["id"])
            if r and r["decision"] == "accepted" and c.get("status") != "FAIL":
                out["REVIEWED_ACCEPTED"] += 1
            elif c.get("status") in out:
                out[c["status"]] += 1
        return out

    unreviewed = [c["id"] for c in controls
                  if not (latest.get(c["id"]) and latest[c["id"]]["decision"] == "accepted")]
    if unreviewed:
        reasons_open.append(f"{len(unreviewed)} of {len(controls)} controls have no accepted independent review")
    nt = [c["id"] for c in controls if c.get("status") == "NT"]
    if nt:
        reasons_open.append(f"not tested / awaiting human or infrastructure proof: {', '.join(nt)}")
    reviewer = (register.get("attestation") or {}).get("independent_reviewer")
    if not reviewer:
        reasons_open.append("no independent reviewer named in the register (attestation.independent_reviewer)")

    if reasons_blocked:
        verdict = VERDICT_BLOCKED
    elif not reasons_open:
        verdict = VERDICT_VERIFIED       # only reachable with every control reviewed by a named human
    else:
        verdict = VERDICT_NOT_VERIFIED
    return {
        "verdict": verdict,
        "reasons": reasons_blocked + reasons_open,
        "p0": bucket(p0), "p1": bucket(p1),
        "total": len(controls), "reviewed": len(controls) - len(unreviewed),
        "latestReviews": latest,
    }


def control_view(control: dict, reviews: list, proofs: dict) -> dict:
    deviation = control.get("deviation")
    return {
        "id": control["id"], "title": control.get("title"), "section": control.get("section"),
        "priority": control.get("priority"), "owner": control.get("owner"), "status": control.get("status"),
        "testIds": [str(t) for t in control.get("tests") or []],
        "evidencePath": ", ".join(control.get("evidence") or []) or None,
        "humanProofs": [f"{p}: {proofs.get(p, {}).get('proof', '')}".strip(": ")
                        for p in control.get("human_proofs") or []],
        "deviation": str(deviation) if deviation else None,
        "reviews": [{k: r.get(k) for k in ("reviewerUserId", "reviewerEmail", "reviewer", "decision",
                                           "proofReference", "recordedAt", "source")}
                    for r in reviews if r.get("control") == control["id"]],
    }


def assurance_report(db=None, path: Path = REGISTER_PATH, defects_path: Path = DEFECTS_PATH) -> dict:
    """The Privacy Assurance page payload. Fails closed to BLOCKED."""
    now = _z(datetime.now(timezone.utc))
    try:
        register = load_register(path)
    except Exception as exc:  # noqa: BLE001 - a missing / broken register blocks, never verifies
        return {"controls": [], "summary": {"total": 0, "byStatus": {}, "reviewed": 0},
                "attestation": {"verdict": VERDICT_BLOCKED, "reasons": [f"control register unavailable: {exc}"]},
                "generatedAt": now}
    reviews = _register_reviews(register) + (db_reviews(db) if db is not None else [])
    result = compute_verdict(register, reviews, open_blocking_defects(defects_path))
    proofs = {p["id"]: p for p in register.get("human_and_infrastructure_proofs") or []}
    by_status: dict = {}
    for c in register["controls"]:
        by_status[c.get("status")] = by_status.get(c.get("status"), 0) + 1
    return {
        "controls": [control_view(c, reviews, proofs) for c in register["controls"]],
        "summary": {"total": result["total"], "byStatus": by_status, "reviewed": result["reviewed"],
                    "p0": result["p0"], "p1": result["p1"]},
        "attestation": {"verdict": result["verdict"], "reasons": result["reasons"],
                        "independentReviewer": (register.get("attestation") or {}).get("independent_reviewer")},
        "humanProofs": list(proofs.values()),
        "generatedAt": now,
    }


def record_review(db, user, control_id: str, decision: str, proof_reference: str, request=None) -> dict:
    """Append a review as a hash-chained security event. The reviewer is the
    authenticated platform_security user; nothing in the register file is
    changed (engineering statuses stay as they are)."""
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.security import events

    if control_id not in control_ids():
        raise NotFoundException("Control")
    decision = (decision or "").strip().lower()
    proof_reference = (proof_reference or "").strip()
    if decision not in DECISIONS:
        raise BadRequestException("decision must be 'accepted' or 'rejected'")
    if not (3 <= len(proof_reference) <= 200):
        raise BadRequestException("A proof reference (3-200 characters) is required")
    row = events.emit(db, REVIEW_EVENT, result="allow", actor_user_id=user.id,
                      actor_role=getattr(user.role, "value", user.role), target_type="privacy_control",
                      target_id=control_id, action="review", reason_code=decision.upper(),
                      ticket_reference=proof_reference, request=request)
    if row is None:
        from app.core.exceptions import ZoikoException

        raise ZoikoException(503, "AUDIT_UNAVAILABLE", "The review could not be recorded. Nothing was changed.")
    return {"reviewerUserId": user.id, "reviewerEmail": user.email, "reviewer": user.email, "decision": decision,
            "proofReference": proof_reference, "recordedAt": _z(row.occurred_at), "source": "platform"}
