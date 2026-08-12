"""
modules/assist/gateway.py
-------------------------
Model gateway for Zoiko Payroll Assist.

Provides a deterministic, evidence-grounded answering engine (default) and an
optional OpenAI-compatible chat completions provider used automatically when
configured. Structured outputs are validated by guardrails before rendering.
The deterministic engine guarantees a working, governed assistant with no
external credentials.
"""

import json
import logging
import urllib.request

from app.config import settings
from app.modules.assist import prompts

logger = logging.getLogger("zoiko_payroll.assist.gateway")


def model_configured() -> bool:
    return bool(
        settings.ASSIST_MODEL_PROVIDER == "openai-compatible"
        and settings.ASSIST_MODEL_BASE_URL
        and settings.ASSIST_MODEL_API_KEY
    )


def active_engine() -> str:
    return "llm" if model_configured() else "deterministic"


def _post_json(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers.setdefault("User-Agent", "zoiko-payroll-assist/1.0")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def generate_llm_answer(
    user_text: str,
    evidence: list[dict],
    knowledge: list[dict],
    intent_id: str,
    jurisdiction_codes: list[str],
    tool_result: dict | None = None,
) -> dict:
    """Call the configured OpenAI-compatible provider and validate the result."""
    system_prompt = prompts.build_system_prompt()
    evidence_envelope = prompts.build_evidence_envelope(evidence, knowledge, tool_result)
    task_prompt = prompts.build_task_prompt(intent_id, user_text, jurisdiction_codes)

    url = f"{settings.ASSIST_MODEL_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.ASSIST_MODEL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.ASSIST_MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{evidence_envelope}\n\n{task_prompt}"},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    result = _post_json(url, headers, payload, settings.ASSIST_MODEL_TIMEOUT_SECONDS)
    content = result["choices"][0]["message"]["content"]
    try:
        answer = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned non-JSON content: %s", exc)
        return {
            "answer": "The model gateway returned an unreadable response. Using the safe fallback.",
            "facts": [],
            "inferences": [],
            "limitations": ["model_output_invalid"],
            "next_steps": ["Re-run the request or open the payroll run directly."],
            "sources": [],
            "confidence": "LOW",
            "safety_state": "SAFE_FALLBACK",
        }
    if not isinstance(answer, dict):
        answer = {}
    answer.setdefault("answer", "")
    answer.setdefault("facts", [])
    answer.setdefault("inferences", [])
    answer.setdefault("limitations", [])
    answer.setdefault("next_steps", [])
    answer.setdefault("sources", [])
    answer.setdefault("confidence", "LOW")
    answer.setdefault("safety_state", "SAFE")
    return answer


# ── Deterministic answer builder ────────────────────────────────────────

def build_answer_text(intent_id: str, tool_result: dict | None, run_summary: dict | None) -> str:
    """Compose a clear, governed answer from a deterministic tool result."""
    if intent_id in ("action.approve_payroll", "action.release_payment", "action.submit_filing", "action.change_protected_data"):
        return "That action is outside what Assist is allowed to do."

    if not tool_result or not tool_result.get("found"):
        reason = (tool_result or {}).get("reason") or "No payroll record is visible in your authorized scope."
        if reason == "No visible payroll run.":
            reason = (
                "I don't see any payroll run in your authorized scope yet. "
                "Create or open a payroll run first, then ask me about its status, readiness and exceptions."
            )
        return f"I couldn't find a payroll run to answer this. {reason}"

    if intent_id == "review.run_readiness":
        blockers = tool_result.get("blockers", [])
        run = tool_result.get("run", {})
        if blockers:
            lines = [f"The {run.get('period')} run is not ready for approval. Blockers:"]
            lines += [f"  - {b['description']} ({b['severity']})" for b in blockers]
            return "\n".join(lines)
        return f"The {run.get('period')} run has no open blockers and is in {run.get('status')} state. I can open the approval screen for the authorized decision."

    if intent_id == "review.exception":
        exceptions = tool_result.get("exceptions", [])
        if not exceptions:
            return f"No exceptions are recorded for the {tool_result.get('run', {}).get('period')} run."
        lines = [f"{len(exceptions)} exception(s) recorded for {tool_result.get('run', {}).get('period')}:"]
        for exc in exceptions:
            owner = f"assigned to {exc['assignee_role']}" if exc.get("assignee_role") else "unassigned"
            lines.append(f"  - {exc['description']} ({exc['severity']}, {owner})")
        return "\n".join(lines)

    if intent_id == "review.variance":
        a, b = tool_result.get("period_a", {}), tool_result.get("period_b", {})
        deltas = tool_result.get("deltas", {})
        return (
            f"Comparing {a.get('period')} to {b.get('period')}:\n"
            f"  Gross: {_fmt_delta(deltas.get('gross'))}\n"
            f"  Deductions: {_fmt_delta(deltas.get('deductions'))}\n"
            f"  Taxes: {_fmt_delta(deltas.get('taxes'))}\n"
            f"  Net: {_fmt_delta(deltas.get('net'))}\n"
            "This comparison uses the approved payroll run records."
        )

    # explain.status / find.object / kb.answer defaults
    if run_summary:
        return (
            f"The {run_summary.get('period')} payroll run is currently **{run_summary.get('status')}** "
            f"({run_summary.get('employees')} employees, net {run_summary.get('net'):,.2f}). "
            "You can open it from Payroll Runs."
        )
    return "I found the payroll record you asked about. Open it from Payroll Runs for the full detail."


def _fmt_delta(value) -> str:
    try:
        value = float(value or 0)
        sign = "+" if value > 0 else ""
        return f"{sign}{value:,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def deterministic_answer(
    intent_id: str,
    user_text: str,
    tool_result: dict | None,
    knowledge_items: list[dict],
) -> dict:
    """Build a fully grounded structured answer using only deterministic data."""
    if intent_id in ("action.approve_payroll", "action.release_payment", "action.submit_filing", "action.change_protected_data"):
        return {
            "answer": (
                "I can summarize the payroll run and its unresolved exceptions, but I cannot approve payroll, "
                "release payments, submit filings, or change protected data. Use the relevant screen inside "
                "Zoiko Payroll to make the authorized decision."
            ),
            "facts": [],
            "inferences": [],
            "limitations": ["prohibited_action", "human_decision_required"],
            "next_steps": ["Open the Payroll Runs screen to review and decide."],
            "sources": [],
            "confidence": "HIGH",
            "safety_state": "REFUSED",
        }

    sources: list[dict] = []
    facts: list[str] = []

    run_summary = None
    if tool_result and tool_result.get("found"):
        run_summary = tool_result.get("run")

    if tool_result and tool_result.get("found") and run_summary:
        facts.append(
            f"{run_summary.get('period')} payroll run: status {run_summary.get('status')}, "
            f"{run_summary.get('employees')} employees, net {float(run_summary.get('net') or 0):,.2f}."
        )

    if knowledge_items:
        top = knowledge_items[0]
        facts.append(top.get("summary") or top.get("title"))

    kb_requested = intent_id in ("kb.answer", "explain.field")
    if kb_requested:
        if knowledge_items:
            top = knowledge_items[0]
            answer = f"{top.get('summary')}\n\n{top.get('body')}"
            sources = [
                {"evidence_id": 0, "title": top.get("title"), "source_type": "KNOWLEDGE", "authority": top.get("authority")}
            ]
        else:
            answer = (
                "No matching knowledge article was found for that question. "
                "Try asking about a specific payroll concept, or ask me about the current payroll run's "
                "status, readiness and exceptions."
            )
    else:
        answer = build_answer_text(intent_id, tool_result, run_summary)

    limitations = []
    if kb_requested and not knowledge_items:
        limitations.append("no_matching_knowledge")
    if not kb_requested and (not tool_result or not tool_result.get("found")):
        limitations.append("no_visible_payroll_record")

    next_steps = ["Open the payroll run for the full detail."]
    if intent_id in ("review.run_readiness", "review.exception"):
        next_steps = ["Open the Payroll Runs screen to review exceptions and decide."]

    return {
        "answer": answer,
        "facts": facts,
        "inferences": [],
        "limitations": limitations,
        "next_steps": next_steps,
        "sources": sources,
        "confidence": "HIGH" if sources or facts else "MEDIUM",
        "safety_state": "SAFE",
    }
