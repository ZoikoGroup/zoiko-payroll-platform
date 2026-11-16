
import { requestStepUp, STEP_UP_REQUIRED } from "../utils/stepUp";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || `${window.location.protocol}//${window.location.hostname}:8000`;
const TOKEN_KEY = "zoiko_payroll_access";
const REFRESH_KEY = "zoiko_payroll_refresh";
const USER_KEY = "zoiko_payroll_user";
const AUTH_INVALID_EVENT = "zoiko-payroll-auth-session-invalid";
const BROADCAST_CHANNEL_NAME = "zoiko_payroll_auth";
// Idle-timeout bookkeeping, shared by every tab through localStorage:
// { idleTimeoutMs, lastRefreshAt }. Privileged roles (org/super admin, ...) must
// refresh at least once every PRIVILEGED_REFRESH_IDLE_MINUTES or the server
// demands a fresh sign-in; the client uses this to keep active users signed
// in and to warn idle users before the deadline.
const SESSION_META_KEY = "zoiko_payroll_session_meta";
const LAST_ACTIVITY_KEY = "zoiko_payroll_last_activity";
const REFRESH_LOCK_NAME = "zoiko_payroll_refresh";
// Fallback when the server did not send refresh_idle_timeout_seconds (older
// backend, or a session stored before this change). Mirrors MFA_REQUIRED_ROLES.
const PRIVILEGED_ROLES = ["super_admin", "support_operator", "platform_security", "org_admin"];
const DEFAULT_PRIVILEGED_IDLE_MS = 30 * 60 * 1000;
const ACTIVITY_THROTTLE_MS = 15 * 1000;
export const SESSION_WARNING_MS = 5 * 60 * 1000;

let refreshPromise = null;
let sessionInvalidNotified = false;
let authChannel = null;

// ── Cross-tab token synchronization (ZP-PRIV B08) ──────────────────────────
// Refresh tokens rotate on every use. When one tab refreshes, all other tabs
// holding the old refresh token would trigger reuse detection and get logged
// out. BroadcastChannel lets the refreshing tab announce new tokens so every
// tab can update immediately instead of stale-refreshing and getting revoked.

function getAuthChannel() {
  if (typeof window === "undefined" || typeof window.BroadcastChannel === "undefined") return null;
  if (!authChannel) {
    authChannel = new window.BroadcastChannel(BROADCAST_CHANNEL_NAME);
    authChannel.onmessage = (event) => {
      if (!event.data || event.data.type !== "TOKEN_REFRESHED") return;
      const { accessToken, refreshToken } = event.data;
      if (accessToken) localStorage.setItem(TOKEN_KEY, accessToken);
      if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken);
      // Proactively refresh with the new token so this tab never tries the
      // revoked one on its next request.
      scheduleProactiveRefresh();
    };
  }
  return authChannel;
}

function broadcastTokens(accessToken, refreshToken) {
  const ch = getAuthChannel();
  if (ch) {
    ch.postMessage({ type: "TOKEN_REFRESHED", accessToken, refreshToken });
  }
}

export function getAccessToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function getStoredUser() {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

function readSessionMeta() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_META_KEY)) || {};
  } catch {
    return {};
  }
}

function writeSessionMeta(meta) {
  try {
    localStorage.setItem(SESSION_META_KEY, JSON.stringify(meta));
  } catch {
    // storage unavailable - the idle warning simply won't show
  }
}

// Milliseconds a session may go without a token refresh before the server
// requires a new sign-in, or null when there is no idle limit.
export function getIdleTimeoutMs() {
  const meta = readSessionMeta();
  if (typeof meta.idleTimeoutMs === "number") return meta.idleTimeoutMs > 0 ? meta.idleTimeoutMs : null;
  let role = null;
  try {
    role = getStoredUser()?.role || null;
  } catch {
    role = null;
  }
  return PRIVILEGED_ROLES.includes(role) ? DEFAULT_PRIVILEGED_IDLE_MS : null;
}

// Epoch ms when the server will stop accepting this session's refresh token
// for inactivity, or null when unknown / not applicable.
export function getSessionDeadline() {
  const idle = getIdleTimeoutMs();
  const { lastRefreshAt } = readSessionMeta();
  if (!idle || !lastRefreshAt || !getRefreshToken()) return null;
  return lastRefreshAt + idle;
}

function getLastActivityAt() {
  return Number(localStorage.getItem(LAST_ACTIVITY_KEY)) || 0;
}

// Real user input keeps the session alive: refresh when the access token is
// close to expiry, or when half of the idle window has passed. Driven by
// activity rather than only a timer because browsers throttle or freeze
// timers in background tabs and on sleep - the old timer-only refresh could
// miss the idle window and sign out someone who was actively working.
function refreshIfDueForActivity() {
  const token = getAccessToken();
  if (!token || !getRefreshToken() || refreshPromise) return;
  const now = Date.now();
  const expMs = getTokenExpMs(token);
  const nearExpiry = Boolean(expMs) && expMs - now < 3 * 60 * 1000;
  const idle = getIdleTimeoutMs();
  const lastRefreshAt = readSessionMeta().lastRefreshAt || 0;
  const idleHalfPassed = Boolean(idle) && now - lastRefreshAt > idle / 2;
  if (nearExpiry || idleHalfPassed) tryRefreshToken();
}

let lastActivityMarked = 0;

export function markUserActivity() {
  const now = Date.now();
  if (now - lastActivityMarked < ACTIVITY_THROTTLE_MS) return;
  lastActivityMarked = now;
  try {
    localStorage.setItem(LAST_ACTIVITY_KEY, String(now));
  } catch {
    // ignore
  }
  refreshIfDueForActivity();
}

export function setStoredUser(user) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else localStorage.removeItem(USER_KEY);
}

function getTokenExpMs(token) {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
    return payload.exp ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

let proactiveTimer = null;

export function scheduleProactiveRefresh() {
  if (typeof window === "undefined") return;
  if (proactiveTimer) {
    clearTimeout(proactiveTimer);
    proactiveTimer = null;
  }

  const token = getAccessToken();
  const refreshToken = getRefreshToken();
  if (!token || !refreshToken) return;

  const expMs = getTokenExpMs(token);
  if (!expMs) return;

  const now = Date.now();
  // Target refresh 2 minutes before access token expiry
  const refreshDelay = Math.max(expMs - now - 2 * 60 * 1000, 1000);

  // If token is already expired, let normal request handling or focus take care of it
  if (now >= expMs) return;

  proactiveTimer = setTimeout(async () => {
    if (!getAccessToken() || !getRefreshToken()) return;
    // With an idle limit, only keep the session alive for a user who did
    // something since the last refresh; an idle user gets the expiry warning
    // instead of being silently kept signed in forever by an open tab.
    if (getIdleTimeoutMs() && getLastActivityAt() <= (readSessionMeta().lastRefreshAt || 0)) return;
    await tryRefreshToken();
  }, refreshDelay);
}

export function setSession(data = {}) {
  const accessToken = data.accessToken || data.access_token;
  const refreshToken = data.refreshToken || data.refresh_token;
  const user = data.user || data.employee;

  if (accessToken) localStorage.setItem(TOKEN_KEY, accessToken);
  if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  if (accessToken || refreshToken || user) sessionInvalidNotified = false;
  // A new refresh token restarts the server's idle window. (A step-up only
  // replaces the access token and must not move the deadline.)
  if (refreshToken) {
    const meta = readSessionMeta();
    if ("refresh_idle_timeout_seconds" in data) {
      const seconds = Number(data.refresh_idle_timeout_seconds);
      meta.idleTimeoutMs = seconds > 0 ? seconds * 1000 : 0;
    }
    meta.lastRefreshAt = Date.now();
    writeSessionMeta(meta);
  }
  scheduleProactiveRefresh();
  // Notify other tabs of the new tokens so they don't try to use a revoked
  // refresh token and get their whole session family ended.
  broadcastTokens(accessToken, refreshToken);
}

export function clearSession() {
  if (proactiveTimer) {
    clearTimeout(proactiveTimer);
    proactiveTimer = null;
  }
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(SESSION_META_KEY);
}

// Sign out from the client (idle timeout reached, or the user chose to).
export function endSession(reason = "signed_out") {
  clearSession();
  notifySessionInvalid(reason);
}

if (typeof window !== "undefined") {
  // Listen for token rotations from other tabs from the start - not only
  // after this tab itself first calls setSession.
  getAuthChannel();
  scheduleProactiveRefresh();

  for (const type of ["pointerdown", "keydown", "wheel", "touchstart", "mousemove"]) {
    window.addEventListener(type, markUserActivity, { passive: true, capture: true });
  }

  window.addEventListener("storage", (event) => {
    if (event.key === TOKEN_KEY && event.newValue) {
      scheduleProactiveRefresh();
    } else if (event.key === TOKEN_KEY && !event.newValue) {
      notifySessionInvalid("cross_tab_logout");
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      const token = getAccessToken();
      const expMs = token ? getTokenExpMs(token) : null;
      if (expMs && (expMs - Date.now() < 3 * 60 * 1000)) {
        tryRefreshToken();
      }
    }
  });
}

function notifySessionInvalid(reason) {
  if (sessionInvalidNotified) return;
  sessionInvalidNotified = true;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(AUTH_INVALID_EVENT, { detail: { reason } }));
  }
}

function createApiError(message, status, extra = {}) {
  const error = new Error(message || `Request failed with status ${status}`);
  error.status = status;
  Object.assign(error, extra);
  return error;
}

/**
 * Low level request helper. Talks to the FastAPI backend at VITE_API_BASE_URL.
 * Automatically attaches the bearer token (if present) and JSON headers,
 * and attempts a single silent refresh on a 401 response.
 */
export async function apiRequest(path, { method = "GET", body, headers = {}, auth = true, retry = true, stepUpRetry = true, params, signal } = {}) {
  let url = path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
  if (params) {
    const query = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join("&");
    if (query) url += `${url.includes("?") ? "&" : "?"}${query}`;
  }

  const finalHeaders = { ...headers };
  if (body !== undefined && !(body instanceof FormData)) {
    finalHeaders["Content-Type"] = "application/json";
  }
  if (auth) {
    const token = getAccessToken();
    if (token) finalHeaders["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(url, {
    method,
    headers: finalHeaders,
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
    signal,
  });

  if (res.status === 401 && auth && retry) {
    const refreshResult = await tryRefreshToken();
    if (refreshResult.ok) {
      return apiRequest(path, { method, body, headers, auth, retry: false, signal });
    }
    if (refreshResult.invalidSession) {
      clearSession();
      notifySessionInvalid(refreshResult.reason);
      throw createApiError("Your session has expired. Please sign in again.", 401, {
        authInvalid: true,
        refreshStatus: refreshResult.status,
      });
    }
  }

  if (!res.ok) {
    let detail;
    let errorCode;
    let trace;
    try {
      const data = await res.json();
      detail = data?.detail || data?.message;
      errorCode = data?.error || data?.error_code || null;
      trace = data?.trace || null;
      if (Array.isArray(detail)) {
        // Handle FastAPI 422 validation errors nicely
        detail = detail.map(err => {
          const field = err.loc ? err.loc[err.loc.length - 1] : "Field";
          return `${field}: ${err.msg}`;
        }).join(", ");
      } else if (typeof detail === "object" && detail !== null) {
        detail = JSON.stringify(detail);
      }
    } catch {
      detail = res.statusText;
    }
    if (res.status === 403 && errorCode === STEP_UP_REQUIRED && auth && stepUpRetry) {
      // ZP-PRIV B08: ask for a fresh code once, then retry the same request.
      if (await requestStepUp(detail)) {
        return apiRequest(path, { method, body, headers, auth, retry, stepUpRetry: false, params, signal });
      }
    }
    throw createApiError(detail, res.status, { errorCode, trace });
  }

  if (res.status === 204) return null;

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return res.json();
  return res.text();
}

// Single-flight refresh shared by BOTH API clients (service/api.js and
// api/client.js). Refresh tokens rotate (ZP-PRIV B08): two concurrent
// refreshes with the same token would look like token theft and end the
// session, so every caller must go through this one promise.
// Serialise refreshes across tabs: every tab's proactive timer reads the same
// token expiry and fires together, and two tabs presenting the same rotating
// refresh token looks like token theft to the server (whole session revoked).
function withRefreshLock(fn) {
  if (typeof navigator !== "undefined" && navigator.locks?.request) {
    return navigator.locks.request(REFRESH_LOCK_NAME, fn);
  }
  return fn();
}

export async function tryRefreshToken() {
  if (refreshPromise) return refreshPromise;
  const startingRefreshToken = getRefreshToken();
  refreshPromise = withRefreshLock(async () => {
    // Another tab rotated the token while this one waited for the lock -
    // use the new tokens instead of replaying the old refresh token.
    const current = getRefreshToken();
    if (current && startingRefreshToken && current !== startingRefreshToken) {
      scheduleProactiveRefresh();
      return { ok: true, refreshedElsewhere: true };
    }
    // Try up to 3 times. A refresh can fail with invalidSession when another
    // tab rotated the refresh token first (ZP-PRIV B08 reuse detection).
    // After a failed attempt, another tab may have already refreshed and
    // broadcast new tokens via BroadcastChannel — re-read localStorage and
    // try again before giving up.
    for (let attempt = 0; attempt < 3; attempt++) {
      const result = await refreshAccessToken();
      if (result.ok) return result;
      if (!result.invalidSession) return result; // transient failure, don't retry
      // invalidSession: another tab may have refreshed. Re-read localStorage
      // (BroadcastChannel may have updated it) and retry once before quitting.
      const rt = getRefreshToken();
      const at = getAccessToken();
      if (!rt || !at) return result; // nothing to retry with
      // Small delay to let any in-flight broadcast from another tab settle.
      await new Promise((r) => setTimeout(r, 150 * (attempt + 1)));
    }
    return { ok: false, invalidSession: true, reason: "refresh_exhausted_retries" };
  })
    .then((result) => {
      if (!result.ok && result.invalidSession) {
        clearSession();
        notifySessionInvalid(result.reason);
      }
      return result;
    })
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

async function refreshAccessToken() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    return { ok: false, invalidSession: true, reason: "missing_refresh_token" };
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (res.status === 401) {
      return {
        ok: false,
        invalidSession: true,
        status: res.status,
        reason: "refresh_rejected",
      };
    }

    if (!res.ok) {
      return {
        ok: false,
        invalidSession: false,
        status: res.status,
        reason: "refresh_transient_failure",
      };
    }

    const data = await res.json();
    if (data?.access_token) {
      setSession({
        accessToken: data.access_token,
        refreshToken: data.refresh_token || refreshToken,
        user: data.employee || data.user,
        ...("refresh_idle_timeout_seconds" in data
          ? { refresh_idle_timeout_seconds: data.refresh_idle_timeout_seconds }
          : {}),
      });
      return { ok: true };
    }
    return { ok: false, invalidSession: false, reason: "refresh_missing_access_token" };
  } catch (error) {
    return { ok: false, invalidSession: false, reason: "refresh_network_error", error };
  }
}

export const api = {
  get: (path, opts) => apiRequest(path, { ...opts, method: "GET" }),
  post: (path, body, opts) => apiRequest(path, { ...opts, method: "POST", body }),
  put: (path, body, opts) => apiRequest(path, { ...opts, method: "PUT", body }),
  patch: (path, body, opts) => apiRequest(path, { ...opts, method: "PATCH", body }),
  delete: (path, opts) => apiRequest(path, { ...opts, method: "DELETE" }),
};

export { API_BASE_URL, AUTH_INVALID_EVENT };

// Reset after a successful sign-in so a later expiry is announced again.
export function resetSessionInvalidNotice() {
  sessionInvalidNotified = false;
}
