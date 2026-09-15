/**
 * service/errorClassification.js
 * ------------------------------------------------------------
 * Classifies an API error thrown by service/api.js's apiRequest() (or
 * api/client.js's apiFetch — both throw the same shapes) so a page can
 * render an honest, distinct state instead of a generic error banner.
 * Found necessary during the Super Admin stabilization audit: several
 * Germany registry endpoints return HTTP 503 with
 * error: "SCHEMA_UNAVAILABLE" when a required database migration has
 * not been applied to the connected environment — a deployment gap, not
 * an application defect, and never a "no records yet" empty state.
 *
 * Phase 8AW: also distinguishes a genuine NETWORK-level failure (the
 * backend unreachable — down, wrong host/port, or blocked by CORS) from
 * an ordinary application error. Root-caused live: the browser's own
 * `fetch()` throws a plain TypeError with message "Failed to fetch" and
 * NO `.status` property at all when it never got an HTTP response back
 * (CORS rejection, connection refused, DNS failure, timeout) — every
 * OTHER error this app throws (apiFetch's own Error for a non-2xx
 * response, api.js's createApiError) always sets `.status` to the real
 * HTTP status code. So "no `.status` at all" reliably means "never
 * reached the server," and the raw browser string was leaking straight
 * through to the user instead of an actionable message — never showing
 * database DSNs, stack traces, or other internal detail, just plain
 * "the backend could not be reached."
 *
 * Kept as a plain, DOM-free function (rather than inline in a React
 * component) so it can be unit-tested the same way this project already
 * tests service/payrollService.js — no component-rendering test
 * infrastructure exists in this repo yet, and adding one is out of
 * scope for this stabilization pass.
 */

export function isSchemaUnavailableError(err) {
  return Boolean(err) && err.status === 503;
}

export function isNetworkError(err) {
  // A real network failure is a thrown Error-like object (has a message —
  // the browser's own "Failed to fetch"/"NetworkError when attempting to
  // fetch resource"/"Load failed") that never got an HTTP response at all
  // (no `.status`). A bare `{}` (no message, no status — this codebase's
  // own defensive "something failed with no detail" fallback shape) is
  // deliberately NOT classified as a network error — it falls through to
  // the generic "Failed to load." message instead, unchanged from before.
  return Boolean(err) && typeof err.status !== "number" && Boolean(err.message);
}

export function describeLoadError(err) {
  const networkError = isNetworkError(err);
  return {
    message: networkError
      ? "Could not reach the backend server. Check your network connection, or contact an administrator if this continues."
      : (err && err.message) || "Failed to load.",
    errorCode: (err && err.errorCode) || null,
    trace: (err && err.trace) || null,
    schemaUnavailable: isSchemaUnavailableError(err),
    networkError,
  };
}
