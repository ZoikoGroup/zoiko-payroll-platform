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

# Sensitive-identifier patterns. Any match fails the response closed (the
# whole answer is replaced by safe_fallback_response) rather than being
# masked in place — partial redaction risks missing a multi-part identifier,
# while fail-closed can't leak anything it doesn't fully suppress.
_SENSITIVE_PATTERNS = [
    # Long digit runs that are more likely PII (bank/account) than payroll totals.
    re.compile(r"\b\d{9,}\b"),
    # SSN-shaped (###-##-####).
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # IBAN-shaped (2 letters, 2 digits, up to 30 alphanumeric).
    re.compile(r"\b[A-Za-z]{2}\d{2}[A-Za-z0-9]{10,30}\b"),
    # Digits immediately following a labeled sensitive field.
    re.compile(r"\b(?:routing|account|iban|swift)\s*(?:number|no\.?|#)?\s*[:\-]?\s*\d{4,}\b", re.IGNORECASE),
]

# Common prompt-injection markers. This is a deterministic phrase scanner,
# not a real classifier — it catches the well-known injection idioms, not
# every possible phrasing.
_INJECTION_PATTERNS = [
    re.compile(r"ignore (all )?(the )?(previous|prior|above) instructions", re.IGNORECASE),
    re.compile(r"disregard (the )?(above|previous|prior)", re.IGNORECASE),
    re.compile(r"you are now\b", re.IGNORECASE),
    re.compile(r"\bsystem prompt\b", re.IGNORECASE),
    re.compile(r"\bdeveloper mode\b", re.IGNORECASE),
    re.compile(r"reveal (your|the) (instructions|system prompt|prompt)", re.IGNORECASE),
    re.compile(r"print (your|the) (instructions|system prompt|prompt)", re.IGNORECASE),
    re.compile(r"act as (if you are|a) ", re.IGNORECASE),
    re.compile(r"new instructions?:", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
]


def detect_prompt_injection(text: str) -> list[str]:
    """Return descriptions of any prompt-injection markers found in `text`.

    An empty list means nothing suspicious was found. This scans user input
    (and can be used on retrieved KB/tool content) before it reaches the LLM
    gateway — matches should short-circuit the LLM call rather than being
    passed through and hoped the model ignores them.
    """
    matches = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text or ""):
            matches.append(f"Possible prompt injection marker: /{pattern.pattern}/")
    return matches


def _contains_sensitive_pattern(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _SENSITIVE_PATTERNS)


def validate_grounded_response(response: dict, allowed_evidence_ids: set[int]) -> dict:
    """Validate a structured answer_v1 against grounding rules.

    Returns {"passed": bool, "issues": [str]}.
    """
    issues = []
    answer = response.get("answer") or ""
    for pattern in _PROHIBITED_CLAIM_PATTERNS:
        if pattern.search(answer):
            issues.append("Response contains a prohibited completion claim (approve/release/submit).")

    facts_text = " ".join(str(f) for f in (response.get("facts") or []))
    next_steps_text = " ".join(str(s) for s in (response.get("next_steps") or []))
    if any(_contains_sensitive_pattern(t) for t in (answer, facts_text, next_steps_text)):
        issues.append("Response contains a sequence that may expose a sensitive identifier.")

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
