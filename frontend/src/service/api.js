
import { requestStepUp, STEP_UP_REQUIRED } from "../utils/stepUp";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || `${window.location.protocol}//${window.location.hostname}:8000`;
const TOKEN_KEY = "zoiko_payroll_access";
const REFRESH_KEY = "zoiko_payroll_refresh";
const USER_KEY = "zoiko_payroll_user";
const AUTH_INVALID_EVENT = "zoiko-payroll-auth-session-invalid";

let refreshPromise = null;
let sessionInvalidNotified = false;

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
    if (getAccessToken() && getRefreshToken()) {
      await tryRefreshToken();
    }
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
  scheduleProactiveRefresh();
}

export function clearSession() {
  if (proactiveTimer) {
    clearTimeout(proactiveTimer);
    proactiveTimer = null;
  }
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

if (typeof window !== "undefined") {
  scheduleProactiveRefresh();

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
export async function tryRefreshToken() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = refreshAccessToken()
    .then((result) => {
      // A rejected refresh means the session is over (expired, revoked, or
      // issued by another server): clear it and tell the app once, so the
      // user is taken to sign in instead of every request failing in place.
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
