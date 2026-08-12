"""
modules/assist/guardrails.py
----------------------------
Output validation for Zoiko Payroll Assist responses (AIG-013, AIG-025,
AIG-026, KB-SRC-001..003).

A material response is only rendered when it is grounded in accepted
evidence. Claims that the assistant approved/released/submitted something,
unknown citations, and A4/A5 action candidates are rejected or refused.
"""

import re

# Assistant must never claim these outcomes regardless of wording.
_PROHIBITED_CLAIM_PATTERNS = [
    re.compile(r"\b(i|i've|assist|we)\b[^.]*\b(approv|approved)\b", re.IGNORECASE),
    re.compile(r"\b(paid|released|submitted)\b[^.]*\b(payment|payroll|filing)\b", re.IGNORECASE),
    re.compile(r"\b(payment|payroll|filing)\b[^.]*\b(successfully|completed)\b", re.IGNORECASE),
]

# Long digit runs that are more likely PII (bank/account) than payroll totals.
_SENSITIVE_DIGIT_RUN = re.compile(r"\b\d{9,}\b")


def validate_grounded_response(response: dict, allowed_evidence_ids: set[int]) -> dict:
    """Validate a structured answer_v1 against grounding rules.

    Returns {"passed": bool, "issues": [str]}.
    """
    issues = []
    answer = response.get("answer") or ""
    for pattern in _PROHIBITED_CLAIM_PATTERNS:
        if pattern.search(answer):
            issues.append("Response contains a prohibited completion claim (approve/release/submit).")
    if _SENSITIVE_DIGIT_RUN.search(answer):
        issues.append("Response contains a long numeric sequence that may expose sensitive identifiers.")

    sources = response.get("sources") or []
    for src in sources:
        eid = src.get("evidence_id")
        try:
            eid = int(eid)
        except (TypeError, ValueError):
            issues.append(f"Source reference without a valid evidence id: {src}")
            continue
        if eid not in allowed_evidence_ids:
            issues.append(f"Source reference {eid} is not in the authorized evidence envelope.")

    material_claims = response.get("facts") or []
    if answer and material_claims and not sources and response.get("confidence") in ("HIGH", "MEDIUM"):
        issues.append("Material factual response has no source references.")

    return {"passed": not issues, "issues": issues}


def safe_fallback_response(reason_code: str, safe_alternatives: list[str] | None = None) -> dict:
    """Construct a canonical safe-fallback structured response."""
    return {
        "answer": (
            "I could not verify enough material information to answer this safely. "
            f"Reason: {reason_code}. "
            "I can show the current payroll run state or route this to an authorized team if you prefer."
        ),
        "facts": [],
        "inferences": [],
        "limitations": [reason_code, "No material conclusion could be verified."],
        "next_steps": safe_alternatives or ["Open the payroll run to review current state."],
        "sources": [],
        "confidence": "LOW",
        "safety_state": "SAFE_FALLBACK",
    }
