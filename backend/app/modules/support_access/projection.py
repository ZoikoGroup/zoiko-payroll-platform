"""
modules/support_access/projection.py
------------------------------------
Field-class projection of worker records for temporary support users
(ZP-PRIV B04 / D.1 step 6).

The PDP decides WHICH records a support user may read (grant scope, applied
in the data layer). This middleware decides WHICH FIELDS of those records
leave the API: only the field classes the tenant ticked on approval (default
identifier + contact), with the dedicated sensitive columns masked even
inside an allowed class. Any key that is not in the field-class map is
dropped (fail closed), so a new column never leaks by default.

It only acts on worker-class responses of support_temp principals; every
other response passes through untouched. A response that cannot be parsed
as JSON is replaced by a 403 rather than passed through.
"""

from __future__ import annotations

import json
import logging
from typing import Any, FrozenSet

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.authz import fields

logger = logging.getLogger("zoiko_payroll.support_access.projection")


def _project(value: Any, allowed: FrozenSet[str], role: str) -> Any:
    if isinstance(value, list):
        return [_project(v, allowed, role) for v in value]
    if isinstance(value, dict):
        return fields.project_record(value, allowed, role)
    return value


async def project_support_response(request: Request, response: Response) -> Response:
    principal = getattr(request.state, "authz_principal", None)
    policy = getattr(request.state, "authz_policy", None)
    if principal is None or policy is None or principal.role not in ("support_temp", "machine_client"):
        return response
    if policy.data_class != "worker" or response.status_code >= 400:
        return response

    allowed = getattr(request.state, "support_field_classes", None) or frozenset()
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    try:
        data = json.loads(body or b"null")
    except ValueError:
        logger.error("[support-access] non-JSON worker response refused for support user %s", principal.user_id)
        return JSONResponse(status_code=403, content={
            "success": False, "error": "ACCESS_DENIED",
            "message": "You do not have permission to perform this action.",
            "detail": "You do not have permission to perform this action."})
    projected = _project(data, frozenset(allowed), principal.role)
    headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")}
    return JSONResponse(status_code=response.status_code, content=projected, headers=headers)
