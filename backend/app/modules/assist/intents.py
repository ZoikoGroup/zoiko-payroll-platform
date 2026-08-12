"""
modules/assist/intents.py
-------------------------
Intent classification and the controlled action registry.

Classification is deterministic (keyword-based) in the default engine so the
assistant works without any model credentials while still honoring the
governance rules: A4/A5 prohibited intents are classified and refused,
A3 actions require preview + explicit confirmation, A1/A2 intents answer
from authorized records and approved knowledge.

Intent registry mirrors the approved Intent & Action Registry (Appendix B,
ZP-AI-UX-001).
"""

import re

# ── Intent registry ─────────────────────────────────────────────────────

INTENT_REGISTRY = [
    # A5 — prohibited acts. Classified first so they are always refused.
    {
        "id": "action.approve_payroll",
        "risk_tier": "A5",
        "blocked": True,
        "keywords": ["approve payroll", "approve the run", "approve the payroll run", "approve this run", "mark approved", "mark as approved", "mark the run as approved", "mark the payroll as approved", "approve run", "finalize approval", "authorize payroll", "approve the run now"],
        "description": "Approve a payroll run. Prohibited — Assist cannot approve payroll.",
        "refusal": (
            "I can summarize the payroll run and its unresolved exceptions, but I cannot approve payroll. "
            "Use the approval screen to make the authorized decision."
        ),
    },
    {
        "id": "action.release_payment",
        "risk_tier": "A5",
        "blocked": True,
        "keywords": ["release payment", "release the payment", "release the payroll", "release bank", "pay everyone", "send payment", "pay employees", "submit payment", "release payroll"],
        "description": "Release or submit payments. Prohibited — Assist cannot release payments.",
        "refusal": (
            "I cannot release payments or bank files. I can show the current payment state and open the "
            "authorized release workflow."
        ),
    },
    {
        "id": "action.submit_filing",
        "risk_tier": "A5",
        "blocked": True,
        "keywords": ["submit filing", "submit the filing", "file return", "file the return", "submit tax filing", "submit the tax filing", "submit tax", "file taxes", "submit statutory"],
        "description": "Submit statutory filings. Prohibited — Assist cannot submit filings.",
        "refusal": (
            "I cannot submit a statutory filing. I can show the filing status, checklist and the approved "
            "submission route."
        ),
    },
    {
        "id": "action.change_protected_data",
        "risk_tier": "A5",
        "blocked": True,
        "keywords": ["change bank", "change bank account", "update bank account", "update bank", "change pan", "change tax id", "change role", "change permission", "reset password", "change salary"],
        "description": "Change protected data (bank, tax, identity, permissions). Prohibited.",
        "refusal": (
            "I cannot change bank, tax, identity or permission data. Please use the employee or user "
            "management screens to make protected changes."
        ),
    },
    # A3 — reversible low-materiality mutations. Preview + confirm required.
    {
        "id": "action.assign_exception",
        "risk_tier": "A3",
        "keywords": ["assign exception", "assign owner", "assign this exception", "who owns this exception", "assign to"],
        "description": "Assign an allowlisted exception to a permitted owner role.",
        "tool_id": "payroll.assignException",
    },
    {
        "id": "action.add_note",
        "risk_tier": "A3",
        "keywords": ["add a note", "add note", "add comment", "note on the run", "comment on run", "add an exception note"],
        "description": "Add an approved non-sensitive note to a payroll run.",
        "tool_id": "payroll.addExceptionNote",
    },
    {
        "id": "action.create_case",
        "risk_tier": "A3",
        "keywords": ["create case", "create handoff", "escalate", "raise a case", "open a case", "hand off", "handoff"],
        "description": "Create a governed support or compliance task/case.",
        "tool_id": "case.createHandoff",
    },
    # A2 — drafts / prep
    {
        "id": "prepare.note",
        "risk_tier": "A2",
        "keywords": ["draft a note", "prepare a note", "write a note", "draft email", "draft a summary", "prepare a summary"],
        "description": "Prepare a draft note or summary from authorized context.",
    },
    # A1 — reads / explain
    {
        "id": "review.run_readiness",
        "risk_tier": "A1",
        "keywords": ["readiness", "ready for approval", "what is blocking", "blocker", "can we approve", "is the run ready", "approval readiness", "pending approval"],
        "description": "Summarize deterministic run readiness and blockers.",
        "tool_id": "payroll.getRunReadiness",
    },
    {
        "id": "review.exception",
        "risk_tier": "A1",
        "keywords": ["exception", "exceptions", "issues", "problems with the run", "validation issues", "unresolved items"],
        "description": "List authorized exceptions for a payroll run.",
        "tool_id": "payroll.listExceptions",
    },
    {
        "id": "explain.status",
        "risk_tier": "A1",
        "keywords": ["status", "what state", "what stage", "where is the run", "progress", "current status"],
        "description": "Explain the current status of a payroll run.",
        "tool_id": "payroll.getRunSummary",
    },
    {
        "id": "review.variance",
        "risk_tier": "A1",
        "keywords": ["compare", "difference between", "vs", "variance", "period over period", "how does this month compare", "versus"],
        "description": "Compare two payroll periods deterministically.",
        "tool_id": "payroll.comparePeriods",
    },
    {
        "id": "explain.field",
        "risk_tier": "A1",
        "keywords": ["what is", "what does", "explain", "how does", "meaning", "tell me about", "how do i", "how to"],
        "description": "Explain a field, concept or process from approved knowledge.",
        "tool_id": "kb.answer",
    },
    {
        "id": "find.object",
        "risk_tier": "A1",
        "keywords": ["find", "show", "list", "where is", "which", "latest run", "last run", "runs"],
        "description": "Find payroll objects from authorized records.",
        "tool_id": "payroll.getRunSummary",
    },
    {
        "id": "kb.answer",
        "risk_tier": "A1",
        "description": "General governed knowledge answer.",
        "tool_id": "kb.answer",
    },
]

_BLOCKED_INTENT_IDS = {i["id"] for i in INTENT_REGISTRY if i.get("blocked")}

A3_ACTION_TOOL_IDS = {
    "action.assign_exception": "payroll.assignException",
    "action.add_note": "payroll.addExceptionNote",
    "action.create_case": "case.createHandoff",
}

ALLOWED_A3_TOOL_IDS = {"payroll.assignException", "payroll.addExceptionNote", "case.createHandoff"}

# Protected-data change detection is token-based (verbs and data tokens can
# be interleaved with other words, so substring keywords miss real attempts
# like "change the employee's bank account to ...").
_PROTECTED_CHANGE_VERBS = {"change", "update", "reset", "modify", "swap"}
_PROTECTED_DATA_TOKENS = {"bank", "account", "pan", "password", "permission", "role", "salary", "tax", "identity"}


def _is_protected_change(lowered: str, tokens: set[str]) -> bool:
    if not (_PROTECTED_CHANGE_VERBS & tokens):
        return False
    if not (_PROTECTED_DATA_TOKENS & tokens):
        return False
    return True


def classify_intent(text: str) -> dict:
    """Return the highest-priority matching intent for a user message."""
    lowered = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    tokens = set(lowered.split())

    if _is_protected_change(lowered, tokens):
        intent = next((i for i in INTENT_REGISTRY if i["id"] == "action.change_protected_data"), None)
        if intent is not None:
            return {
                "intent_id": intent["id"],
                "risk_tier": intent["risk_tier"],
                "blocked": intent.get("blocked", False),
                "tool_id": intent.get("tool_id"),
                "refusal": intent.get("refusal"),
                "confidence": "HIGH",
                "method": "deterministic",
            }

    for intent in INTENT_REGISTRY:
        if not intent.get("keywords"):
            continue
        for kw in intent["keywords"]:
            if kw in lowered or (len(kw.split()) == 1 and kw in tokens):
                return {
                    "intent_id": intent["id"],
                    "risk_tier": intent["risk_tier"],
                    "blocked": intent.get("blocked", False),
                    "tool_id": intent.get("tool_id"),
                    "refusal": intent.get("refusal"),
                    "confidence": "HIGH",
                    "method": "deterministic",
                }
    return {
        "intent_id": "kb.answer",
        "risk_tier": "A1",
        "blocked": False,
        "tool_id": "kb.answer",
        "confidence": "MEDIUM",
        "method": "deterministic",
    }


def get_action_registry_entry(action_id: str) -> dict | None:
    for entry in INTENT_REGISTRY:
        if entry.get("tool_id") == action_id:
            return entry
    return None


def get_tool_id_for_action(action_id: str) -> str | None:
    return A3_ACTION_TOOL_IDS.get(action_id)
