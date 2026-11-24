#!/usr/bin/env node
/**
 * Report Templates (Super Admin, every jurisdiction) — UI validation.
 *
 * The rules are the backend's: activationReadiness is a dry run of the status
 * change (service.report_template_activation_readiness). These checks prove the
 * UI only presents it — the disabled "Active" option and its reason, the
 * banner, the list badges and "Not available — engine not built" — and that it
 * stays generic (no country code decides anything in the layout).
 * Plain-JS helpers are evaluated under Node; the layout is checked by source.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(__dirname, "..", "src");
const read = (p) => readFileSync(resolve(SRC, p), "utf-8");
const load = (p) => import(pathToFileURL(resolve(SRC, p)).href);

let passed = 0;
const failures = [];
const check = (name, ok) => (ok ? (passed += 1) : failures.push(name));

const R = await load("components/reportTemplates/readiness.js");
const layout = read("components/reportTemplates/ReportTemplateLayout.jsx");
const STATUSES = ["Draft", "Review", "Approved", "Published", "Active", "Superseded"];

// Fixtures shaped like the backend's responses.
const G3 = "Belgium form templates (Dimona, DmfA, 281.10, payslip) stay inactive until the authority schemas are archived and the filing path is certified (gate G3).";
const NOT_BUILT_MSG = "Brazil report-template activation is refused: Brazil report templates are not built yet (ZP-BR-ENG-001 Phase 0 scaffolding).";
const gate = (blockerKind, message, g = null) => ({ allowed: false, message, blockerKind, gate: g });
const OPEN = { allowed: true, message: null, blockerKind: null, gate: null };
const full = (status, over = {}) => ({
  status,
  activationReadiness: {
    canActivate: false, blockedReason: null, blockerKind: null, gate: null, countryGate: OPEN, deferredChecks: [],
    nextStatuses: { Draft: ["Review", "Approved"], Review: ["Draft", "Approved"], Approved: ["Draft", "Review", "Published"],
      Published: ["Active", "Superseded"], Active: ["Superseded"], Superseded: [] }[status],
    ...over,
  },
});
const be = full("Published", { blockedReason: G3, blockerKind: "jurisdiction_gate", gate: "G3", countryGate: gate("jurisdiction_gate", G3, "G3") });
const br = full("Published", { blockedReason: NOT_BUILT_MSG, blockerKind: "not_built", countryGate: gate("not_built", NOT_BUILT_MSG) });
const fourEyes = full("Published", { blockedReason: "Four-eyes rule (the approver may not activate): you approved K v1.0.", blockerKind: "four_eyes" });
const ready = full("Published", { canActivate: true });
const draftBe = full("Draft", { blockedReason: "K v1.0 cannot move from Draft to Active (allowed: Review, Approved).",
  blockerKind: "transition", countryGate: gate("jurisdiction_gate", G3, "G3") });
const listRow = (status, countryGate) => ({ status, activationReadiness: { countryGate, partial: true } });

// ── disabled Active option + its reason ─────────────────────────────────────
const opt = (t, v) => R.statusOptions(STATUSES, t).find((o) => o.value === v);
check("blocked Belgium: Active disabled with the backend's exact reason", opt(be, "Active").disabled && opt(be, "Active").reason === G3);
check("not-built Brazil: Active disabled with its reason", opt(br, "Active").disabled && opt(br, "Active").reason === NOT_BUILT_MSG);
check("four-eyes: Active disabled with the four-eyes message", opt(fourEyes, "Active").disabled && /approver may not activate/.test(opt(fourEyes, "Active").reason));
check("activatable template: Active enabled", !opt(ready, "Active").disabled && opt(ready, "Active").reason === null);
check("current status option is never disabled", !opt(be, "Published").disabled);
check("moves the lifecycle does not allow are disabled (Published -> Draft)",
  opt(be, "Draft").disabled && opt(be, "Draft").reason === "Not allowed from Published.");
check("allowed non-Active move stays enabled (Published -> Superseded)", !opt(be, "Superseded").disabled);
check("Draft: Active disabled by the transition rule", opt(draftBe, "Active").disabled && /cannot move from Draft/.test(opt(draftBe, "Active").reason));
check("activeOptionReason gives the text shown beside the dropdown", R.activeOptionReason(STATUSES, be) === G3 && R.activeOptionReason(STATUSES, ready) === null);
check("no readiness (older response): nothing disabled", R.statusOptions(STATUSES, { status: "Published" }).every((o) => !o.disabled));
check("list-only (partial) readiness never drives the dropdown",
  R.statusOptions(STATUSES, listRow("Published", gate("jurisdiction_gate", G3, "G3"))).every((o) => !o.disabled));

// ── list badges and "Not available — engine not built" ──────────────────────
const b1 = R.listBadge(listRow("Draft", gate("jurisdiction_gate", G3, "G3")));
check("list badge: Blocked · G3 with the reason as tooltip", b1?.label === "Blocked · G3" && b1.title === G3 && b1.key === "blocked");
const b2 = R.listBadge(listRow("Published", gate("not_built", NOT_BUILT_MSG)));
check("list badge: Not built", b2?.label === "Not built" && b2.key === "not-built");
check("list badge: none when the country gate is open", R.listBadge(listRow("Published", OPEN)) === null);
check("list badge: none for a four-eyes item inside a country gate (workflow, not blocked)",
  R.listBadge(listRow("Published", gate("four_eyes", "approve it first"))) === null);
check("list badge: none for Active / Superseded", R.listBadge(listRow("Active", gate("jurisdiction_gate", G3, "G3"))) === null
  && R.listBadge(listRow("Superseded", gate("not_built", NOT_BUILT_MSG))) === null);
check("availability: engine not built", R.availabilityLabel(br) === "Not available — engine not built" && R.availabilityLabel(be) === null);

// ── detail banner ───────────────────────────────────────────────────────────
const bn = R.activationBanner(be);
check("banner: country gate -> 'Cannot activate yet', reason, link to release readiness", bn?.title === "Cannot activate yet"
  && bn.message === G3 && bn.gate === "G3" && bn.linkToReadiness === true && bn.tone === "error");
check("banner: not built", R.activationBanner(br)?.title === "Not available — engine not built" && R.activationBanner(br).linkToReadiness === false);
check("banner: shown for a Draft already blocked by its country gate", R.activationBanner(draftBe)?.message === G3);
check("banner: Published + four-eyes -> warning with the message", R.activationBanner(fourEyes)?.tone === "warning");
check("banner: none when activatable and nothing deferred", R.activationBanner(ready) === null);
check("banner: deferred checks listed (Mexico payslip proof)",
  R.activationBanner(full("Published", { canActivate: true, deferredChecks: ["Each field must resolve…"] }))?.deferred.length === 1);
check("banner: none for Active", R.activationBanner(full("Active", { countryGate: gate("jurisdiction_gate", G3, "G3") })) === null);

// ── audit: names and collapsed repeated refusals ────────────────────────────
const A = await load("components/reportTemplates/auditView.js");
const refused = (id, at, over = {}) => ({ id, action: "refused", entityType: "report_template", actorId: 1, actorName: "Ada Lovelace",
  oldValue: { status: "Published" }, newValue: { attempted: "Active", result: "REFUSED" }, reason: G3, createdAt: at, ...over });
const change = (id) => ({ id, action: "status_change", entityType: "report_template", actorId: 2, oldValue: { status: "Approved" },
  newValue: { status: "Published" }, createdAt: "2026-11-20T10:00:00Z" });
const log = [refused(9, "2026-11-24T10:04:00Z"), refused(8, "2026-11-24T10:03:00Z"), refused(7, "2026-11-24T10:02:00Z"),
  refused(6, "2026-11-24T10:01:00Z"), change(5), refused(4, "2026-11-19T09:00:00Z"),
  refused(3, "2026-11-18T09:00:00Z", { actorId: 3, actorName: null }), refused(2, "2026-11-18T08:00:00Z", { reason: "other" })];
const grouped = A.groupAuditEntries(log);
check("audit: 4 consecutive identical refusals collapse into one ×4 group",
  grouped[0].kind === "refusals" && grouped[0].count === 4 && grouped[0].latest.id === 9 && grouped[0].entries.map((e) => e.id).join() === "9,8,7,6");
check("audit: a different row breaks the run; a lone refusal stays a plain row", grouped[1].entry?.id === 5 && grouped[2].kind === "entry");
check("audit: a different actor or reason is not grouped", grouped.length === 5 && grouped[3].entry.id === 3 && grouped[4].entry.id === 2);
check("audit: grouping keeps every record (nothing dropped or altered)",
  grouped.flatMap((g) => (g.kind === "refusals" ? g.entries : [g.entry])).map((e) => e.id).join() === log.map((e) => e.id).join()
  && JSON.stringify(log[0]) === JSON.stringify(refused(9, "2026-11-24T10:04:00Z")));
check("audit: actor name, else User #id, else System",
  A.actorLabel(log[0]) === "Ada Lovelace" && A.actorLabel(log[6]) === "User #3" && A.actorLabel({ actorId: null }) === "System");
check("layout renders grouped audit rows with names",
  layout.includes("groupAuditEntries(audit).map") && layout.includes("Refused ×${count} — last at") && layout.includes("by {actorLabel(a)}")
  && !layout.includes("by user #{a.actorId}"));

// ── Approve / Delete per status (the backend's rules) ───────────────────────
const X = await load("components/reportTemplates/actions.js");
const tpl = (status, over = {}) => ({ status, name: "Form", version: "1.0", approvedById: 7, ...over });
check("Approve offered on Draft / Review / Approved only (backend _EDITABLE_TEMPLATE_STATUSES)",
  ["Draft", "Review", "Approved"].every((st) => X.canApprove(tpl(st))) && ["Published", "Active", "Superseded"].every((st) => !X.canApprove(tpl(st))));
check("Delete allowed on Draft / Review / Approved", ["Draft", "Review", "Approved"].every((st) => X.deleteState(tpl(st)).allowed));
check("Delete disabled on Published / Active with the supersede reason",
  ["Published", "Active"].every((st) => !X.deleteState(tpl(st)).allowed && X.deleteState(tpl(st)).reason.includes("supersede")));
check("Delete disabled on Superseded (kept as version history)", !X.deleteState(tpl("Superseded")).allowed
  && /version history/.test(X.deleteState(tpl("Superseded")).reason));
check("deleting an Approved template warns its approval record will be lost",
  /approval record \(user #7\) will be lost/.test(X.deleteState(tpl("Approved")).confirmMessage)
  && !/approval record/.test(X.deleteState(tpl("Draft")).confirmMessage));
check("layout: Approve hidden outside pre-release, Delete uses the shared disabled pattern",
  layout.includes("{canApprove(detail) && (") && layout.includes("<DisabledReason reason={deletion.reason}>")
  && layout.includes('aria-disabled="true"') && layout.includes("deleteState(deletingTemplate).confirmMessage"));

// ── generic wiring (no country-specific branch decides readiness) ───────────
check("layout renders options from statusOptions with disabled + reason",
  layout.includes("statusOptions(STATUS_OPTIONS, detail).map") && layout.includes("disabled={o.disabled}") && layout.includes("title={o.reason || undefined}"));
check("layout shows the Active reason as text (unless the banner says the same), linked to the select", layout.includes("activeReason && activeReason !== banner?.message") && layout.includes('data-testid="active-blocked-reason"')
  && layout.includes('aria-describedby={activeReason ? "active-blocked-reason" : undefined}'));
check("layout shows the banner through the shared Notice", layout.includes("<Notice tone={banner.tone}") && layout.includes("?tab=release-readiness"));
check("layout shows list + header badges", (layout.match(/<ReadinessBadge badge=\{listBadge\(/g) || []).length === 2);
check("no country code decides readiness in the layout or helpers",
  !/(jurisdictionCountry|country)\s*===\s*"[A-Z]{2}"/.test(layout) && !/"[A-Z]{2}"/.test(read("components/reportTemplates/readiness.js")));
const routes = (p) => Object.fromEntries([...read(p).split("COUNTRY_CODE_TO_ROUTE = {")[1].split("};")[0]
  .matchAll(/^\s*([A-Z]{2}):\s*"([a-z-]+)"/gm)].map((m) => [m[1], m[2]]));
const complianceRoutes = routes("pages/JurisdictionCompliance/index.js");
const reportRoutes = routes("pages/ReportTemplates/index.js");
check("report-template and compliance slugs are identical (the banner link derives one from the other)",
  Object.keys(reportRoutes).length >= 31
  && JSON.stringify(Object.entries(reportRoutes).sort()) === JSON.stringify(Object.entries(complianceRoutes).sort()));
check("layout derives the compliance link from its own URL (no compliance-page import)",
  layout.includes("/super-admin/report-templates/<slug>") && layout.includes(".exec(pathname)") && !layout.includes("pages/JurisdictionCompliance"));
const jl = read("components/jurisdiction/JurisdictionLayout.jsx");
check("compliance pages accept ?tab= (through tabAliases, unknown -> Overview)",
  jl.includes('searchParams.get("tab")') && jl.includes("setTabRaw((tabAliases && tabAliases[requestedTab]) || requestedTab)"));
check("Belgium maps release-readiness to its Release Readiness tab",
  read("config/jurisdictions/belgiumComplianceConfig.jsx").includes('"release-readiness": "be-release"'));

if (failures.length) {
  console.error(`report-template UI validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`report-template UI validation: ${passed} checks passed`);
