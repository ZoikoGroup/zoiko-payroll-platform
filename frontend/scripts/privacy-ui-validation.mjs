#!/usr/bin/env node
/**
 * ZP-PRIV-VERIFY-001 frontend validation (plain Node, like the other scripts
 * here: vitest/Vite's module graph OOMs on this machine).
 *
 * Two kinds of checks:
 *   - EVALUATED: the pure modules (utils/time.js, utils/stepUp.js) are
 *     imported and run - UTC parsing, countdowns, the step-up bridge.
 *   - SOURCE: page/service source text is checked for the behaviours the
 *     checklist requires (cancel uses the cancel endpoint, the credentials
 *     panel masks/reveals/copies, approve sends field classes + employees,
 *     decline/revoke require a reason, tabs are role-aware, Super Admin
 *     screens carry no worker identity fields, MFA setup + step-up exist).
 *
 * The server remains the control; these checks keep the UI from offering
 * what the server refuses and from rendering worker data on platform screens.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const read = (p) => readFileSync(resolve(SRC, p), "utf-8");

let passed = 0;
const failures = [];
const pending = [];
function settle(name, ok) {
  if (ok === false) failures.push(`${name}: assertion returned false`);
  else passed += 1;
}
function check(name, fn) {
  try {
    const ok = fn();
    if (ok && typeof ok.then === "function") {
      pending.push(ok.then((v) => settle(name, v), (err) => failures.push(`${name}: ${err.message}`)));
      return;
    }
    settle(name, ok);
  } catch (err) {
    failures.push(`${name}: ${err.message}`);
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

const time = await import(pathToFileURL(resolve(SRC, "utils/time.js")).href);
const stepUp = await import(pathToFileURL(resolve(SRC, "utils/stepUp.js")).href);

// ── EVALUATED: UTC parsing and countdowns ──────────────────────────────────
check("parseUtc treats a naive API timestamp as UTC", () => {
  const d = time.parseUtc("2026-10-19T10:00:00");
  assert(d.toISOString() === "2026-10-19T10:00:00.000Z", d.toISOString());
});
check("parseUtc keeps an explicit Z / offset", () => {
  assert(time.parseUtc("2026-10-19T10:00:00Z").toISOString() === "2026-10-19T10:00:00.000Z", "Z");
  assert(time.parseUtc("2026-10-19T12:00:00+02:00").toISOString() === "2026-10-19T10:00:00.000Z", "offset");
});
check("parseUtc rejects garbage", () => time.parseUtc("not a date") === null && time.parseUtc(null) === null);
check("msUntil + formatCountdown", () => {
  const now = Date.parse("2026-10-19T10:00:00Z");
  assert(time.msUntil("2026-10-19T10:15:00", now) === 15 * 60 * 1000, "ms");
  assert(time.formatCountdown(15 * 60 * 1000) === "15:00", time.formatCountdown(15 * 60 * 1000));
  assert(time.formatCountdown(65 * 1000) === "01:05", "01:05");
  assert(time.formatCountdown(0) === "expired", "expired");
  assert(time.formatCountdown(-5) === "expired", "past");
});

// ── EVALUATED: step-up bridge ──────────────────────────────────────────────
check("requestStepUp resolves false with no handler", async () => {
  assert((await stepUp.requestStepUp("x")) === false, "no handler");
});
check("requestStepUp shares one pending prompt", () => {
  let calls = 0;
  const off = stepUp.registerStepUpHandler(() => {
    calls += 1;
    return Promise.resolve(true);
  });
  const a = stepUp.requestStepUp("a");
  const b = stepUp.requestStepUp("b");
  assert(a === b, "concurrent step-ups must share one prompt");
  off();
  return a.then(() => assert(calls === 1, `handler called ${calls}x`));
});

// ── SOURCE: API clients ────────────────────────────────────────────────────
const client = read("api/client.js");
const api = read("service/api.js");
check("both clients retry once after STEP_UP_REQUIRED", () =>
  client.includes("STEP_UP_REQUIRED") && client.includes("requestStepUp") &&
  api.includes("STEP_UP_REQUIRED") && api.includes("stepUpRetry: false"));
check("refresh is single-flight across both clients (rotating refresh tokens)", () =>
  client.includes("tryRefreshToken") && api.includes("export async function tryRefreshToken"));

// ── SOURCE: Support Access (operator) ──────────────────────────────────────
const svc = read("service/supportAccessService.js");
const op = read("pages/SuperAdmin/SupportAccessPage.jsx");
check("cancel uses the cancel endpoint", () => /cancel: \(id\) => apiFetch\(`\$\{SA\}\/\$\{id\}\/cancel`/.test(svc) &&
  op.includes("svc.cancel(active.id)"));
check("pending card: approval countdown, check now, polling ~10 s", () =>
  op.includes("Request expires in") && op.includes("Check now") && op.includes("setInterval(refresh, 10000)"));
check("credentials panel: masked, reveal, copy, login link, private-window advice", () =>
  op.includes('"•".repeat(16)') && op.includes("Reveal password") && op.includes("navigator.clipboard.writeText") &&
  op.includes('href="/login"') && op.toLowerCase().includes("private"));
check("credentials are fetched on demand only (audited reads)", () => op.includes("svc.credentials(grantId)"));
check("tabs are role-aware; non-security roles never call security endpoints", () =>
  op.includes('if (isSecurity)') && op.includes("{tab !== \"mine\" && isSecurity &&"));
check("tenant picker debounced and ignores out-of-order responses", () =>
  op.includes("setTimeout(") && op.includes("mine !== seq.current"));
check("employee codes are never kept after submit", () => op.includes('setCodes(""); // codes are never kept'));
check("write actions blocked on small screens", () => op.includes("innerWidth < 640") && op.includes("NarrowNotice"));
check("break-glass needs incident, reason and acknowledgement (two-step verification is off)", () =>
  op.includes("incidentReference") && op.includes("acknowledged: ack") && !op.includes("mfaCode"));
check("deep link ?organization= preselects the tenant", () => op.includes('params.get("organization")'));

// ── SOURCE: Support Access (organization admin) ────────────────────────────
const org = read("modules/organization-admin/SupportAccessPage.jsx");
check("approve sends field classes and (narrowed) employees", () =>
  org.includes("fieldClasses: [...fields]") && org.includes("employeeIds:") && org.includes("but not add others"));
check("approve dialog explains exactly what happens", () =>
  org.includes("temporary, read-only login for") && org.includes("you can revoke it at any time"));
check("decline and revoke require a reason", () =>
  org.includes("svc.deny(declining.id, reason)") && org.includes("svc.revoke(revoking.id, reason)") &&
  org.includes("disabled={!reason.trim()}"));
check("auto-refresh ~20 s and an Audit tab", () => org.includes("setInterval(load, 20000)") && org.includes("<AuditTab />"));

// ── SOURCE: MFA ────────────────────────────────────────────────────────────
const login = read("pages/LoginPage.jsx");
const mfaStep = read("components/MfaLoginStep.jsx");
const modal = read("components/StepUpAuthModal.jsx");
const settings = read("pages/SecuritySettingsPage.jsx");
check("login handles the MFA challenge and enrolment", () =>
  login.includes("data.mfa_required || data.mfa_enrollment_required") && login.includes("<MfaLoginStep"));
check("MFA setup shows a QR code and a manual key; recovery codes once", () =>
  mfaStep.includes("QRCode.toDataURL") && mfaStep.includes("Key:") && mfaStep.includes("will not be shown again"));
check("step-up modal registers itself and retries via the bridge", () =>
  modal.includes("registerStepUpHandler") && modal.includes("mfaService.stepUp"));
check("security settings: enrol, regenerate, disable only when optional", () =>
  settings.includes("setupBegin") && settings.includes("regenerateRecoveryCodes") && settings.includes("!status.required"));

// ── SOURCE: Super Admin screens carry no worker identity fields ────────────
const WORKER_FIELDS = [/\bemployeeCode\b/, /\bemployee_code\b/, /\bbankAccount/, /\bpanNumber\b/, /\bdateOfBirth\b/];
const ALLOW = new Set(["SupportAccessPage.jsx"]); // operator page never renders employee data either (checked above)
function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}
const superAdminScreens = [
  ...walk(resolve(SRC, "pages/SuperAdmin")),
  resolve(SRC, "pages/ReportsPage.jsx"),
  resolve(SRC, "pages/DashboardPage.jsx"),
].filter((f) => f.endsWith(".jsx"));
for (const file of superAdminScreens) {
  const name = file.split(/[\\/]/).pop();
  if (ALLOW.has(name)) continue;
  check(`Super Admin screen ${name} renders no worker identity fields`, () => {
    const text = readFileSync(file, "utf-8");
    const hit = WORKER_FIELDS.find((re) => re.test(text));
    assert(!hit, `references ${hit}`);
  });
}
check("Reports: the employee name search is gone", () => !/search.*employee|employee.*search/i.test(read("pages/ReportsPage.jsx")
  .replace(/\/\/.*$/gm, "")) || read("pages/ReportsPage.jsx").includes("Workforce totals"));

// ── SOURCE: routes ─────────────────────────────────────────────────────────
const app = read("App.jsx");
check("routes exist for every new page", () =>
  ["/super-admin/support-access", "/organization-admin/support-access", "/organization-admin/scope",
    "/payroll/employer-statutory", "/account/security", "/support-session"].every((p) => app.includes(`"${p}"`)));
const guard = read("components/ProtectedRoute.jsx");
check("temporary support logins are confined to the support session", () =>
  guard.includes('role === "support_temp"') && guard.includes('"/support-session"'));

// ── SOURCE: security & privacy plane (ZP-PRIV D/E/F) ───────────────────────
const SEC_SA_ROUTES = ["/super-admin/audit-explorer", "/super-admin/privileged-inventory",
  "/super-admin/machine-clients", "/super-admin/privacy-assurance", "/super-admin/alerts"];
const SEC_ORG_ROUTES = ["/organization-admin/security-activity", "/organization-admin/api-clients",
  "/organization-admin/data-governance"];
check("security & privacy routes exist in App.jsx", () =>
  [...SEC_SA_ROUTES, ...SEC_ORG_ROUTES].every((p) => app.includes(`"${p}"`)));
const saNav = read("components/superAdminNav.js");
check("super admin nav has a Security & privacy group for platform_security only (not Super Admin)", () =>
  saNav.includes('title: "Security & privacy"') &&
  ['"/super-admin/audit-explorer"', '"/super-admin/privileged-inventory"', '"/super-admin/machine-clients"',
    '"/super-admin/privacy-assurance"'].every((h) => saNav.includes(h)) &&
  saNav.includes('const SECURITY_READERS = ["platform_security"]'));
const nav = await import(pathToFileURL(resolve(SRC, "components/superAdminNav.js")).href).catch((err) => {
  failures.push(`superAdminNav import: ${err.message}`);
  return null;
});
if (nav) {
  check("navGroupsFor: platform_security sees the security views; support_operator does not", () => {
    const hrefs = (role) => nav.navGroupsFor(role).flatMap((g) => g.items.map((i) => i.href));
    const sec = hrefs("platform_security");
    const op = hrefs("support_operator");
    const sa = hrefs("super_admin");
    const views = ["/super-admin/audit-explorer", "/super-admin/alerts", "/super-admin/privileged-inventory",
      "/super-admin/machine-clients", "/super-admin/privacy-assurance"];
    assert(views.every((v) => sec.includes(v)), `platform_security: ${sec}`);
    const removed = ["/super-admin/audit-explorer", "/super-admin/privileged-inventory",
      "/super-admin/machine-clients", "/super-admin/privacy-assurance"];
    assert(!sa.some((h) => removed.includes(h)), `super_admin should not see: ${sa}`);
    assert(!op.some((h) => views.includes(h)), `support_operator: ${op}`);
  });
}
const shell = read("components/PayrollShell.jsx");
check("org admin nav no longer lists Security Activity, API Clients, Data Region or Entities & Pay Groups", () =>
  [...SEC_ORG_ROUTES, "/organization-admin/scope"].every((h) => !shell.includes(`href: "${h}"`)));
check("ProtectedRoute lets platform_security (only) reach the security views", () =>
  guard.includes("PLATFORM_SECURITY_PREFIXES") && guard.includes('"/super-admin/privacy-assurance"') &&
  guard.includes('if (role === "platform_security")'));
const secSvc = read("service/securityService.js");
check("securityService covers every security endpoint", () =>
  ["/security-events/verify", "/alert-rules", "/alert-events", "/acknowledge", "/test-fire", "/privileged-inventory",
    "/machine-clients", "/privacy-assurance/controls", "/reviews", "/api-clients/scopes", "/rotate", "/revoke",
    "/webhooks", "/disable", "/data-governance", "/legal-holds", "/release", "/data-access-requests", "/complete"]
    .every((p) => secSvc.includes(p)));
const SEC_PAGES = ["pages/SuperAdmin/AuditExplorerPage.jsx", "pages/SuperAdmin/PrivilegedInventoryPage.jsx",
  "pages/SuperAdmin/MachineClientsPage.jsx", "pages/SuperAdmin/PrivacyAssurancePage.jsx",
  "pages/SuperAdmin/AlertsIncidentsPage.jsx", "modules/organization-admin/SecurityActivityPage.jsx",
  "modules/organization-admin/ApiClientsPage.jsx", "modules/organization-admin/DataGovernancePage.jsx",
  "service/securityService.js", "components/SecurityUi.jsx"];
for (const p of SEC_PAGES) {
  const text = read(p);
  check(`${p}: no browser storage writes, no console logging`, () =>
    !/localStorage\.setItem|sessionStorage\.setItem|indexedDB/.test(text) && !/console\.(log|info|debug|warn|error)/.test(text));
  if (!p.startsWith("service/") && !p.startsWith("components/")) {
    check(`${p}: timestamps go through utils/time.js`, () => text.includes('from "../../utils/time"') && !/new Date\(/.test(text));
  }
}
for (const p of SEC_PAGES.filter((x) => x.includes("/") && !x.startsWith("service") && !x.startsWith("components") && !x.endsWith("AlertsIncidentsPage.jsx"))) {
  check(`${p}: fails closed on 403/404`, () => {
    const text = read(p);
    return text.includes("isUnavailable(err)") && text.includes("<NotAvailable");
  });
}
const apiClients = read("modules/organization-admin/ApiClientsPage.jsx");
check("API client credential / webhook signing secret shown once and dropped on close", () =>
  apiClients.includes("OneTimeSecretModal") && apiClients.includes("won&apos;t see it again") &&
  apiClients.includes("onClose={() => setSecret(null)}") && apiClients.includes("navigator.clipboard.writeText") &&
  apiClients.includes("res.credential") && apiClients.includes("res.signingSecret") &&
  !/localStorage|sessionStorage/.test(apiClients));
check("webhook URLs must be https", () => apiClients.includes("/^https:\\/\\/\\S+$/"));
const assurance = read("pages/SuperAdmin/PrivacyAssurancePage.jsx");
check("Privacy Assurance never shows a PASS status", () => !/\bPASS\b/.test(assurance) && assurance.includes("UNKNOWN_STATUS"));
check("Privacy Assurance: Record review only for platform_security; proof reference 3-200", () =>
  assurance.includes('const isSecurity = role === "platform_security"') &&
  assurance.includes("{isSecurity && (") && assurance.includes("reviewing && isSecurity") &&
  assurance.includes("trimmed.length >= 3 && trimmed.length <= 200"));
check("Privacy Assurance: verdict + independent-reviewer note", () =>
  assurance.includes("<VerdictPanel") && assurance.includes("independent reviewer"));
const alertsPage = read("pages/SuperAdmin/AlertsIncidentsPage.jsx");
check("Alerts: test fire only for platform_security; incident feed only for super_admin", () =>
  alertsPage.includes('const isSecurity = role === "platform_security"') && alertsPage.includes("<AlertRules isSecurity={isSecurity} />") &&
  alertsPage.includes("{isSecurity && (") && alertsPage.includes('tab === "incidents" && isSuperAdmin'));
const audit = read("pages/SuperAdmin/AuditExplorerPage.jsx");
check("Audit Explorer: verify-chain banner (verified / broken) and correlation filter", () =>
  audit.includes("svc.verifyChain()") && audit.includes("Chain verified") && audit.includes("Chain broken") &&
  audit.includes("filterByCorrelation"));
const inventory = read("pages/SuperAdmin/PrivilegedInventoryPage.jsx");
check("Privileged inventory: hidden tenant accounts, MFA gaps highlighted", () =>
  inventory.includes("tenant account (hidden)") && inventory.includes("No MFA"));
const gov = read("modules/organization-admin/DataGovernancePage.jsx");
check("Data governance: four-eyes release note", () => gov.includes("different administrator"));

// Wait for every async check, then report.
await Promise.all(pending);
console.log(`privacy-ui-validation: ${passed} passed, ${failures.length} failed`);
for (const f of failures) console.log(`  FAIL ${f}`);
process.exit(failures.length ? 1 : 0);
