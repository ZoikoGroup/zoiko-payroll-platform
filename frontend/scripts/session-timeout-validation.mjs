#!/usr/bin/env node
/**
 * Session timeout validation (QA bug: "signed out automatically after
 * 30-40 minutes"). Plain Node, like the other scripts here.
 *
 *   - EVALUATED: service/api.js is loaded against a stub browser
 *     (localStorage, fetch, Web Locks) and its session logic is exercised:
 *     idle deadline bookkeeping, step-up not moving the deadline, activity-
 *     driven refresh, cross-tab refresh de-duplication, client sign-out.
 *   - SOURCE: the warning modal is mounted and a 403 no longer signs out.
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const read = (p) => readFileSync(resolve(SRC, p), "utf-8");

let passed = 0;
const failures = [];
async function check(name, fn) {
  try {
    const ok = await fn();
    if (ok === false) failures.push(`${name}: assertion returned false`);
    else passed += 1;
  } catch (err) {
    failures.push(`${name}: ${err.message}`);
  }
}

// ── Stub browser ────────────────────────────────────────────────────────────
// Controllable clock so per-tab activity throttling can be stepped past.
const realNow = Date.now.bind(Date);
let clockOffset = 0;
Date.now = () => realNow() + clockOffset;
const advanceClock = (ms) => { clockOffset += ms; };
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
const dispatched = [];
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init) {
    this.type = type;
    this.detail = init?.detail;
  }
};
globalThis.window = {
  addEventListener: () => {},
  dispatchEvent: (e) => dispatched.push(e),
};
globalThis.document = { addEventListener: () => {}, visibilityState: "visible" };
let lockHook = null;
Object.defineProperty(globalThis, "navigator", {
  value: {
    locks: {
      request: async (_name, fn) => {
        if (lockHook) lockHook();
        return fn();
      },
    },
  },
  configurable: true,
});
const fetchCalls = [];
let nextRefreshResponse = null;
globalThis.fetch = async (url, init) => {
  fetchCalls.push({ url, body: init?.body });
  return nextRefreshResponse;
};

function jwt(expSeconds) {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "none" })}.${b64({ exp: expSeconds })}.sig`;
}

// Load service/api.js with its Vite-only bits replaced.
const apiSrc = read("service/api.js")
  .replace(/^import \{ requestStepUp, STEP_UP_REQUIRED \} from "\.\.\/utils\/stepUp";$/m,
    'const requestStepUp = async () => false; const STEP_UP_REQUIRED = "STEP_UP_REQUIRED";')
  .replace("import.meta.env.VITE_API_BASE_URL", '"http://api.test"');
const dir = mkdtempSync(join(tmpdir(), "zoiko-session-"));
const modPath = join(dir, "api.mjs");
writeFileSync(modPath, apiSrc);
const api = await import(pathToFileURL(modPath).href);

const MIN = 60 * 1000;
const nowSec = () => Math.floor(Date.now() / 1000);

function freshPrivilegedSession(refreshToken = "rt-1") {
  store.clear();
  fetchCalls.length = 0;
  dispatched.length = 0;
  api.setSession({
    accessToken: jwt(nowSec() + 15 * 60),
    refreshToken,
    user: { role: "org_admin" },
    refresh_idle_timeout_seconds: 1800,
  });
}

function setLastRefreshAt(ms) {
  const meta = JSON.parse(store.get("zoiko_payroll_session_meta"));
  meta.lastRefreshAt = ms;
  store.set("zoiko_payroll_session_meta", JSON.stringify(meta));
}

// ── EVALUATED ───────────────────────────────────────────────────────────────
await check("login stores a 30-minute idle deadline for a privileged session", () => {
  freshPrivilegedSession();
  const d = api.getSessionDeadline();
  return d !== null && Math.abs(d - (Date.now() + 30 * MIN)) < 2000;
});

await check("step-up (access token only) does not move the idle deadline", () => {
  freshPrivilegedSession();
  setLastRefreshAt(Date.now() - 10 * MIN);
  const before = api.getSessionDeadline();
  api.setSession({ accessToken: jwt(nowSec() + 15 * 60), user: { role: "org_admin" } });
  return api.getSessionDeadline() === before;
});

await check("non-privileged session (server sends null) has no idle deadline", () => {
  store.clear();
  api.setSession({ accessToken: jwt(nowSec() + 3600), refreshToken: "rt-p", user: { role: "payroll_admin" },
    refresh_idle_timeout_seconds: null });
  return api.getSessionDeadline() === null;
});

await check("older backend without the field falls back to 30 min for org_admin", () => {
  store.clear();
  api.setSession({ accessToken: jwt(nowSec() + 900), refreshToken: "rt-o", user: { role: "org_admin" } });
  const d = api.getSessionDeadline();
  return d !== null && Math.abs(d - (Date.now() + 30 * MIN)) < 2000;
});

await check("activity past half the idle window refreshes and moves the deadline", async () => {
  freshPrivilegedSession("rt-a");
  setLastRefreshAt(Date.now() - 16 * MIN);
  const oldDeadline = api.getSessionDeadline();
  nextRefreshResponse = {
    status: 200, ok: true,
    json: async () => ({ access_token: jwt(nowSec() + 900), refresh_token: "rt-b", refresh_idle_timeout_seconds: 1800 }),
  };
  api.markUserActivity();
  await new Promise((r) => setTimeout(r, 20));
  return fetchCalls.length === 1
    && fetchCalls[0].url.endsWith("/api/auth/refresh")
    && api.getRefreshToken() === "rt-b"
    && api.getSessionDeadline() > oldDeadline + 15 * MIN;
});

await check("activity early in the idle window does not refresh", async () => {
  freshPrivilegedSession("rt-c");
  // Step past the 15s per-tab activity throttle so the activity is really
  // evaluated (and the "1 minute into the window" state is real).
  advanceClock(60 * 1000);
  fetchCalls.length = 0;
  api.markUserActivity();
  await new Promise((r) => setTimeout(r, 20));
  const lastActivity = Number(store.get("zoiko_payroll_last_activity"));
  return fetchCalls.length === 0 && Math.abs(lastActivity - Date.now()) < 1000;
});

await check("a refresh another tab completed while waiting for the lock is not replayed", async () => {
  freshPrivilegedSession("rt-d");
  lockHook = () => store.set("zoiko_payroll_refresh", "rt-from-other-tab");
  try {
    const result = await api.tryRefreshToken();
    return result.ok === true && fetchCalls.length === 0 && api.getRefreshToken() === "rt-from-other-tab";
  } finally {
    lockHook = null;
  }
});

await check("endSession clears tokens and announces the sign-out", () => {
  freshPrivilegedSession("rt-e");
  api.endSession("idle_timeout");
  return api.getAccessToken() === null
    && api.getRefreshToken() === null
    && store.get("zoiko_payroll_session_meta") === undefined
    && dispatched.some((e) => e.type === api.AUTH_INVALID_EVENT && e.detail?.reason === "idle_timeout");
});

// ── SOURCE ──────────────────────────────────────────────────────────────────
await check("SessionTimeoutWarning is mounted in main.jsx", () =>
  /<SessionTimeoutWarning \/>/.test(read("main.jsx")));
await check("warning offers Stay signed in and Sign out", () => {
  const src = read("components/SessionTimeoutWarning.jsx");
  return src.includes("Stay signed in") && src.includes("Sign out") && src.includes("SESSION_WARNING_MS");
});
await check("DashboardPage no longer signs out on 403", () => !/status === 403/.test(read("pages/DashboardPage.jsx")));
await check("UsersPage no longer signs out on 403", () => !/status === 403/.test(read("pages/UsersPage.jsx")));

if (failures.length) {
  console.error(`session-timeout-validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`session-timeout-validation: ${passed} checks passed`);
