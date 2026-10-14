# Design note — F-4: make privileged (assisted) access auditing fail-closed

**Status:** design only, not implemented. For the Security lead's decision (BLOCKERS B-22, G5).

## Problem

Every HTTP request made under an assisted-access (support) token is meant to be audited. Today:
* `app/main.py` registers `assisted_access_audit_middleware`. It calls `record_request_if_assisted(request, status)` **after** `call_next(request)`, i.e. after the endpoint has already run and committed.
* `app/modules/assisted_access/audit.py` is documented as best-effort: it swallows every exception. If the audit insert fails (database error, pool exhaustion), the request still succeeds and **leaves no trace** of what the support session did.
* Lifecycle events (requested / approved / started / ended / refused / notification failed) are written by the service inside the business transaction. Those are not best-effort. F-4 concerns only the per-request `ORG_API_CALL` rows.

## Options

| | Option | How | Pros | Cons |
|---|---|---|---|---|
| A | **Pre-execution intent record (recommended)** | In `app/core/dependencies.py::_resolve_assisted_principal`, which already runs for every assisted request before the endpoint, insert and commit an `ORG_API_CALL_STARTED` audit row on its own session. If the insert fails, raise HTTP 503 "audit unavailable", so the endpoint never runs. Keep the middleware as the completion record (status code); a completion failure is then visible as a STARTED row with no matching completion | Fail-closed with **no change to `main.py`**; no unaudited action is possible; small change | One extra insert per assisted request; a completion row can still be missing (detectable) |
| B | Middleware fail-closed | In `main.py`, write the audit row before `call_next` and return 503 on failure | Single chokepoint | **Requires editing `backend/app/main.py`** (excluded from this work); middleware sessions are outside the request's DB session |
| C | Keep best-effort, add alerting | On swallowed audit errors, increment a counter and show a high-severity alert in Super Admin Alerts (as for break-glass notification failures) | Never blocks support | Not fail-closed: an action can still go unaudited |

## Recommendation

Option A, plus C's alert for completion-row failures. It meets "no assisted action without an audit record" without touching `main.py`.

## Files affected (Option A)

* `backend/app/core/dependencies.py`: the intent insert in `_resolve_assisted_principal` (or in a thin wrapper used only for assisted principals).
* `backend/app/modules/assisted_access/audit.py`: pair the completion with the intent (store the intent id on `request.state`); on completion failure, record for the alert instead of swallowing silently.
* `backend/app/modules/super_admin/command_center_router.py`: a "security" alert for STARTED rows with no completion.
* `backend/app/main.py`: **no change** under Option A (Option B would need it).

## Migration needs

None for the intent row: `assisted_access_audit_events` already has `event_type`, `method`, `path` and `payload`. Optionally an index on `(assisted_access_session_id, recorded_at)` for the pairing query, as a new additive migration.

## Test plan

* When the audit insert fails (monkeypatched to raise), an assisted request returns 503, the endpoint body never runs, and there is no business write.
* When the insert succeeds, there is a STARTED row before the endpoint runs and a completion row after, with matching ids.
* When the completion insert fails, the request succeeds (it already ran), and a high-severity security alert appears.
* Normal (non-assisted) requests: no extra writes and no behaviour change.
* Load: one extra insert per assisted request only.

## Risks

* An audit-database outage blocks support sessions (intended, but support must know the 503 meaning).
* The intent row commits on a separate session. If the endpoint later fails, the row shows an attempted action with an error status, which is correct for audit.

Security lead decision — Name / Role / Date / Signature: ________
