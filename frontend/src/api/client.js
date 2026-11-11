import {
  tryRefreshToken,
  getAccessToken,
  getRefreshToken,
  getStoredUser,
  setStoredUser,
  setSession,
  clearSession,
} from "../service/api";
import { requestStepUp, STEP_UP_REQUIRED } from "../utils/stepUp";

export const API_BASE = import.meta.env.VITE_API_BASE_URL || `${window.location.protocol}//${window.location.hostname}:8000`;

export { getAccessToken, getRefreshToken, getStoredUser, setStoredUser, setSession, clearSession };

async function refreshSession() {
  // Rotating refresh tokens: use the shared single-flight refresh (ZP-PRIV B08).
  const result = await tryRefreshToken();
  if (!result.ok && result.invalidSession) clearSession();
  return result.ok;
}

export async function apiFetch(path, { method = "GET", body, params } = {}) {
  const url = new URL(API_BASE + path);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== "" && v !== undefined && v !== null) {
        url.searchParams.set(k, v);
      }
    });
  }

  let attempt = true;
  let res = await rawFetch(url, method, body);

  if (res.status === 401 && attempt && (await refreshSession())) {
    attempt = false;
    res = await rawFetch(url, method, body);
  }

  let data = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }

  if (res.status === 403 && (data?.error === STEP_UP_REQUIRED) && (await requestStepUp(data.detail))) {
    // ZP-PRIV B08 step-up: one retry with the freshly minted access token.
    res = await rawFetch(url, method, body);
    try {
      data = await res.json();
    } catch {
      data = {};
    }
  }

  if (!res.ok) {
    const detail = data.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
    const err = new Error(msg || `Request failed (${res.status})`);
    err.status = res.status;
    err.errorCode = data?.error || data?.error_code || null;
    err.trace = data?.trace || null;
    throw err;
  }
  return data;
}

function rawFetch(url, method, body) {
  const headers = { "Content-Type": "application/json" };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}
