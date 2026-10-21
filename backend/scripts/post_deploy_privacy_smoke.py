"""
scripts/post_deploy_privacy_smoke.py
------------------------------------
ZP-PRIV E06 post-deploy privacy smoke. After every deploy, signs in as the
synthetic smoke identities (platform roles that must NEVER see worker data)
and asserts that worker endpoints of the synthetic smoke tenant are denied.

Configuration (environment; secrets come from the CI secret store):
  ZP_SMOKE_BASE_URL          e.g. https://staging-api.example.test
  ZP_SMOKE_IDENTITIES        JSON list: [{"role": "super_admin", "email": "...",
                             "password": "...", "totp_secret": "..."}, ...]
                             (super_admin, support_operator, platform_security)
  ZP_SMOKE_EMPLOYEE_ID       an employee id of the synthetic smoke tenant
  ZP_SMOKE_RUN_ID            optional; defaults to a UTC timestamp
  ZP_SMOKE_ALERT_WEBHOOK     optional; POSTed a JSON summary on failure

Writes a result JSON (no tokens, no passwords, no personal data) and exits
1 on any failure, so the deploy job fails and the run id is recorded.

    python -m scripts.post_deploy_privacy_smoke --output smoke_result.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WORKER_PATHS = ("/api/payroll/employees", "/api/payroll/employees/{employee_id}", "/api/payroll/payslips",
                "/api/payroll/runs", "/api/payroll/dashboard/summary")
DENIED = (401, 403, 404)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _request(base: str, method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Correlation-ID", f"privacy-smoke-{os.getpid()}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else None
        except ValueError:
            return exc.code, None


def _login(base: str, identity: dict) -> str | None:
    status, body = _request(base, "POST", "/api/auth/login",
                            body={"email": identity["email"], "password": identity["password"]})
    if status != 200 or not isinstance(body, dict):
        return None
    if body.get("access_token"):
        return body["access_token"]
    if body.get("mfa_token") and identity.get("totp_secret"):
        import pyotp

        status, body = _request(base, "POST", "/api/auth/mfa/challenge",
                                body={"mfa_token": body["mfa_token"],
                                      "code": pyotp.TOTP(identity["totp_secret"]).now()})
        if status == 200 and isinstance(body, dict):
            return body.get("access_token")
    return None


def run(base: str, identities: list, employee_id: str, run_id: str) -> dict:
    checks = []

    def check(role, path, status):
        checks.append({"role": role, "path": path, "status": status, "ok": status in DENIED})

    for path in WORKER_PATHS:
        check("anonymous", path, _request(base, "GET", path.format(employee_id=employee_id))[0])
    for identity in identities:
        role = identity.get("role", "unknown")
        token = _login(base, identity)
        if token is None:
            checks.append({"role": role, "path": "/api/auth/login", "status": None, "ok": False,
                           "note": "smoke identity could not sign in"})
            continue
        for path in WORKER_PATHS:
            check(role, path, _request(base, "GET", path.format(employee_id=employee_id), token)[0])
    failed = [c for c in checks if not c["ok"]]
    return {"runId": run_id, "ranAt": _now(), "baseUrl": base, "checks": checks,
            "failed": len(failed), "result": "FAIL" if failed or not identities else "OK"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Post-deploy privacy smoke.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    base = os.environ.get("ZP_SMOKE_BASE_URL", "").strip()
    run_id = os.environ.get("ZP_SMOKE_RUN_ID") or datetime.now(timezone.utc).strftime("smoke-%Y%m%dT%H%M%SZ")
    if not base:
        print(f"[{run_id}] FAIL: ZP_SMOKE_BASE_URL is not set", file=sys.stderr)
        return 1
    identities = json.loads(os.environ.get("ZP_SMOKE_IDENTITIES") or "[]")
    result = run(base, identities, os.environ.get("ZP_SMOKE_EMPLOYEE_ID", "1"), run_id)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for c in result["checks"]:
        print(f"{'ok ' if c['ok'] else 'FAIL'} {c['role']:<18} {c['status']} {c['path']}")
    print(f"[{run_id}] privacy smoke: {result['result']} ({result['failed']} failed)")
    if result["result"] != "OK":
        hook = os.environ.get("ZP_SMOKE_ALERT_WEBHOOK", "").strip()
        if hook:
            try:
                req = urllib.request.Request(hook, method="POST", data=json.dumps(
                    {"runId": run_id, "result": result["result"], "failed": result["failed"]}).encode(),
                    headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10).close()
            except Exception as exc:  # noqa: BLE001
                print(f"[{run_id}] alert webhook failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
