"""
tests/privacy/_evidence.py
--------------------------
ZP-PRIV evidence writer. Every privacy test calls :func:`record` once so the
run leaves a per-test JSON artifact under ``tests/privacy/evidence/`` with the
fields the checklist asks for:

    test id, UTC timestamp, environment, git SHA, principal role, token SCOPE,
    synthetic tenant ids, endpoint, expected status, actual status (redacted
    response), correlation id, security/audit event id and run id.

The response is redacted before it is written: any value under a
name/email/code/SSN-shaped key is replaced with ``"***"`` so the evidence file
can be attached to a review without carrying personal data itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
RUN_ID = os.environ.get("ZP_PRIV_RUN_ID") or uuid.uuid4().hex[:12]

_SENSITIVE_KEYS = (
    "name", "first_name", "last_name", "email", "employee_code", "code",
    "national_id", "ssn", "pan", "aadhaar", "nino", "phone", "address",
)


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        if out.returncode == 0:
            return out.stdout.strip()[:40]
    except Exception:
        pass
    return "unknown"


GIT_SHA = _git_sha()


def _redact(value: Any, key: str = "") -> Any:
    lk = key.lower()
    if any(s in lk for s in _SENSITIVE_KEYS):
        return "***"
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def record(
    *,
    test_id: str,
    role: str,
    endpoint: str,
    expected_status: int,
    actual_status: int,
    body: Optional[Any] = None,
    scope: Optional[str] = None,
    tenant_ids: Optional[Any] = None,
    correlation_id: Optional[str] = None,
    security_event_id: Optional[Any] = None,
    decision_id: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    payload = {
        "testId": test_id,
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
        "environment": os.environ.get("PAYROLL_ENVIRONMENT", "test"),
        "gitSha": GIT_SHA,
        "runId": RUN_ID,
        "role": role,
        "tokenScope": scope,
        "syntheticTenantIds": tenant_ids,
        "endpoint": endpoint,
        "expectedStatus": expected_status,
        "actualStatus": actual_status,
        "redactedResponse": _redact(body),
        "correlationId": correlation_id,
        "securityEventId": security_event_id,
        "decisionId": decision_id,
        "note": note,
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    safe = test_id.replace("/", "_").replace(":", "_")
    (EVIDENCE_DIR / f"{safe}.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8",
    )
    return payload
