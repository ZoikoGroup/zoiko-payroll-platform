Master Prompt — Mexico (MX) Final Mile: Super Admin Governance, Report Templates, and Readiness for Every External Input

You are continuing the Mexico payroll jurisdiction on zoiko-payroll-platform (branch nikhil). The completion programme (W1–W8, MEXICO_COMPLETION_MASTER_PROMPT.md) is finished, A17 and A18 are on main (PR #136, run 40472214932) and deployed, and Mexico is dormant in production. Its report counts 21 DONE, 16 EXTERNAL, 16 BLOCKED-ON-DECISION, 5 BLOCKED-ON-SOURCE, 2 OPEN of 60.

Your job in this programme is different from the last one. Most remaining gap-register items cannot be finished by engineering: they wait for a human decision, a source, a provider or a review. Your job is to build everything that makes each of those inputs land inside the product with the least possible engineering afterwards, finish the Super Admin compliance configuration surface, complete the report-template catalog against the spec, and package the reviews and decisions so the people who own them can act quickly. You are not allowed to make the decisions, verify the sources, sign the gates or activate anything yourself.

When this programme ends, the success test is: when D-01 is decided, a source is downloaded, a PAC is chosen, or Rugvedh approves, the next step is a governed action in the Super Admin UI or a single small adapter commit — not a new engineering phase.

## 0. Read first, every session

- docs/mexico/MEXICO_COMPLETION_REPORT.md — final state of every gap-register item (A1–A18, B1–B22, C1–C20).
- docs/mexico/DECISIONS_PENDING.md — D-01 … D-22 with options, sources and the block code each one clears.
- docs/mexico/PRODUCTION_STATE.md — including the local commit cd98323 (PR #136 result) if it is present locally.
- docs/mexico/MEXICO_COMPLETION_GAP_REGISTER.md, MEXICO_COMPLETION_PROGRESS.md, MEXICO_PHASE_12_PLAN.md.
- docs/mexico/release-gates/G*/CHECKLIST.md and EVIDENCE_DRAFT.md.
- docs/mexico/sources/SOURCES_MANIFEST.csv and VERIFICATION_LOG.csv.
- The spec, docs/mexico/Zoiko_Payroll_Mexico_Engineering_Wireframe_and_Implementation_Specification_v1.0.docx (§11–§14 wireframes, §20 controls, §21 fixtures, §22 gates).
- The Hong Kong Super Admin workspace (frontend/src/components/jurisdiction/hong_kong/: HKCalculationPreviewTab, HKGovernanceTab, HKEvidencePanel) — the reference pattern for the Mexico gaps below.

Then verify git state (branch, HEAD, staged and unstaged files, origin/main, whether cd98323 has been pushed) and the latest deploy run before touching anything. Never assume it.

## 1. Session-zero checks (do these before X1, report results, change nothing)

- **Production head.** Ask the associate to run `alembic current` on the production server and paste the output. Expected: c7d2e9a4f1b6. Record the answer in PRODUCTION_STATE.md §1 against PR #136. If it differs, stop (stop condition 4).
- **Unpushed docs commit.** If cd98323 is still local, list it first in the hand-off as "push when convenient, docs only". Do not push it.
- **Live app check, read-only.** In a real browser, open https://app.zoikopayroll.com with the associate signed in as a Super Admin. Confirm and screenshot: /super-admin/compliance/mexico renders every tab; the readiness view shows all eight gates OPEN; a Mexican organisation route still refuses with MX_DORMANT; no Mexican pack, release or registry entry is Active. Make no write of any kind in production, do not record credentials or tokens anywhere, and do not screenshot any real employee identifier. If the frontend build on the server differs from main (see PR #115 history), record it.
- **Skipped privacy smoke.** The post-deploy privacy smoke step was skipped (its secrets are not configured, HP-10). Write down exactly which secrets it needs and who can configure them. Do not configure them.

## 2. Non-negotiable rules (all rules from the completion programme still apply)

- **Git.** After each step, commit locally on nikhil with a message starting with the step name (Mexico X1: …). Never push, merge, open PRs, rebase or reset. Ask before pull, stash, merge or checkout. Never stage the associate's own files (backend/app/main.py, backend/.env.example, frontend/vite.config.js, backend/scripts/validate_environment.py, docs/SINGAPORE_*, docs/HONG_KONG_*) or any source binary. No `git commit -a`, no `git add .`.
- **Production.** Merging to main deploys and runs Alembic. Mexico stays dormant and fail-closed. Every migration is additive and guarded, sets lock_timeout = '5s', keeps a single head with c7d2e9a4f1b6 as its parent, enables RLS on new tenant tables through the existing helper (never apply_rls() over all tables — see the PR #115 incident), and is tested on PostgreSQL 17 (lock mode, hold time, fail-fast, upgrade from c7d2e9a4f1b6). Prefer one migration for the whole programme if the steps can share it; otherwise one per step.
- **Nothing statutory from you.** You never choose a decision, a rounding mode, a materiality threshold, a SAT code or a source version. Where a step needs one, build the mechanism, leave the value empty, and block with a named code.
- **Decisions are recorded, not inferred.** A recorded decision never changes a calculation by itself. It becomes a content row only through the existing path: seed into a Draft pack, [PENDING G1], four-eyes approval, activation gated on VERIFIED sources and signed gates.
- **Sources.** VERIFIED is set only by verify_mexico_sources.py verify from a direct download, logged in VERIFICATION_LOG.csv. Nothing in this programme may create a second path to VERIFIED.
- **Identifiers** (RFC, CURP, NSS, CLABE): never logged, never in messages, never unmasked in API responses or generated reports. The printed CFDI receipt (W4-3b) remains the only exception and is still awaiting Rugvedh's review; do not add a second one. Every new report is scanned for full identifiers in its tests.
- **ZP-PRIV.** Any change to authz, redaction, RLS, migrations, roles, cross-tenant data, or code that reads raw identifiers is flagged at the top of its report section as "Review required: Rugvedh (ZP-PRIV) before merge". Since PRs #123–#136 merged before his review, add to every flagged commit's report: "Do not merge until reviewed — branch protection does not enforce this (C17)."
- **Other jurisdictions.** Zero behaviour change, proven by pinned tests. Shared-code changes are additive and called out.
- **Tests.** Full backend suite in 5 sequential chunks, run alone (8 GB machine). Known local-only failures: the 3 /health route-registry tests and the Hong Kong docs test. Real-Chrome browser checks on scratch SQLite with @example.com users for every screen change, screenshots inspected. Frontend: lint (no new errors), check:undefined, vite build.
- **Synthetic data only** for every preview, sandbox, import or fixture. No real person's name, RFC, CURP, NSS or CLABE anywhere in the repo.
- **Roles.** Reuse the existing Super Admin and four-eyes model. If a step needs a role that does not exist (for example "G1 owner"), do not invent a privileged role; record the question in DECISIONS_PENDING.md (next free number, D-23 onward), store the role name as text on the record, and require a second Super Admin as the interim four-eyes control.

## 3. Workstreams (in this order)

Each numbered item is one step: build, test, write its section in MEXICO_FINAL_MILE_PROGRESS.md, commit locally, update the gap register, move on.

### X1 — Decision Register in the Super Admin workspace (unblocks D-01 … D-22, C4, C5, C12)

Today decisions live only in a markdown file and are applied by an engineer transcribing a content row. Build a governed register so gate owners can record them in the product.

- **Model.** payroll_mx_decisions (platform table, no tenant data): code (D-01 …), title, owning gate(s), question, options (each with its source citations, from DECISIONS_PENDING.md), block codes it clears, the content key(s) it would populate (for D-01: mx_rounding_rule), status, chosen option, rationale, cited sources, recorded-by, approved-by, timestamps, and a content hash of the record. States: OPEN → PROPOSED → APPROVED → TRANSCRIBED plus WITHDRAWN. APPROVED needs a second, different Super Admin. Approved records are immutable; a change is a new record that supersedes the old one.
- **Seeding.** A seed script loads D-01 … D-22, C4, C5 and C12 from DECISIONS_PENDING.md as OPEN, idempotently. It requires an explicit confirmed target and never runs on deploy.
- **Typed answers.** Where the content row has a grammar, validate the chosen option against it before approval: D-01 must parse through rounding.parse() (MODE:QUANTUM); D-02 maps to an existing Art. 96 period or "unmapped"; D-21 must be one of the readings already built. Free-text decisions stay free text.
- **Transcription hand-off.** An approved decision produces a transcription ticket (the exact content key, value and Draft pack it belongs in). The existing seed may read approved decision records as a source citation (DECISION/D-01#<hash>) into a Draft pack only. It never touches an Active pack.
- **Traceability.** Every engine block message whose code a decision clears links to its decision in the Super Admin UI. The readiness view (W5-3) counts open decisions per gate.
- **UI.** A "Decisions" tab in MXCompliancePage, modelled on HKGovernanceTab: filter by gate and status, the options with their sources side by side, the impact (block codes, affected calculations), propose / approve / withdraw with confirmation dialogs.
- ZP-PRIV flag (new table, new routes, four-eyes rule). Browser-check every state transition.

### X2 — Calculation sandbox and decision-impact preview (supports X1, prepares W7)

Build a platform-level Mexico calculation sandbox, modelled on HKCalculationPreviewTab.

- **Inputs:** a synthetic employee and employer (pay frequency, daily salary, zone, work state, SBC mode, seniority, special pay lines), a pay date, and the content in force on that date (Draft packs allowed, labelled).
- **Output:** the full calculation trace up to the first MXBlock, then the block code, its message, and the decision or source that would clear it (from X1). Today every run stops at MX_ROUNDING_RULE_MISSING; that is the expected result and must be shown clearly.
- **What-if mode for decisions.** The operator may supply a candidate value for an OPEN decision (for example a candidate rounding rule) as a request parameter. It is never persisted and the result is watermarked CANDIDATE — NOT APPROVED — NOT A GOLDEN VECTOR on screen and in any export. It is refused for any content key that is not linked to an OPEN decision. This lets the G1 owner see what each D-01 option does to the §21 fixtures before deciding.
- **No database writes**, no organisation, no accumulator, no outbox. Prove that with tests (row counts before and after).
- ZP-PRIV flag (new route). Browser-check with the F1 (UMA boundary), F2 (SBC factor), F3 (CEAV high band) and F4 (minimum-wage geography) inputs from spec §21.

### X3 — Report-template catalog completion against the spec

The catalog has 19 MX templates (register, employer cost, ISR monthly, subsidy, IMSS branch, SUA reconciliation, SIPARE, IDSE movements, INFONAVIT, ISN return, CFDI status, CFDI receipt, aguinaldo, vacation accrual, PTU distribution, finiquito, annual adjustment, journal). First write a coverage matrix (spec section → template → status) in the progress file. Then build the missing ones the spec calls for, using the existing snapshot-bound or dedicated-generator patterns:

| Proposed template | Spec basis | Notes |
|---|---|---|
| MX-RUN-VARIANCE | §13 stage 4 (variance vs prior, high-value deltas) | Employee net, employer cost and each statutory line vs the prior committed run. The high-value threshold is a release-owner setting: build the setting, leave it empty, refuse to flag deltas until it is set. |
| MX-PREFLIGHT-EXCEPTIONS | §13 stage 1 and 3 | Every blocking and material exception with its code, employee reference (masked) and clearing action. |
| MX-SBC-MOVEMENTS | §7, §12 IMSS, MX-019, MX-020 | Fixed/variable/mixed SBC per employee, integration components, bimester accumulator snapshot, generated modification events and due dates. |
| MX-WORK-RISK-ANNUAL | §14 card, MX-026, MX-044 | Review-year cases and inputs, premium history per Registro Patronal. Labelled "not an official file" until the IMSS form layout is a saved source. |
| MX-INFONAVIT-NOTICES | §10, MX-031 | Notice register: status, method, effective date, authority reference; no notice means no deduction. |
| MX-LABOR-COMPLIANCE | §13 stage 3, §16, §17 | Minimum wage by zone, 48-hour / overtime checks, Sunday and holiday premium, vacation and aguinaldo accrual exceptions. |
| MX-PAYMENT-WORKLIST | §20, Phase 10a | Net-pay settlement worklist with masked CLABE (last 4 only) and settlement status; explicitly not a bank file (C7). |
| MX-PARALLEL-DIFF | §22 G8, MX-064 | See X4. |
| MX-IDENTIFIER-ACCESS-AUDIT | §20, MX-061 | Who rendered the CFDI receipt (the one unmasked view) and when; no identifier in the report itself. ZP-PRIV flag. |

For every template: bind only to fields in the MX snapshot catalog; prove every path resolves on a committed synthetic payslip of each run type; generated figures equal the engine's; identifier scan passes; the activation gate (E6) still refuses until gates are SIGNED and content is Active; browser-check the template in the Super Admin template library and in the org report screen (where it refuses with MX_DORMANT). NL / IE / SE / DE report paths pinned unchanged.

Also add, in the Super Admin template library for Mexico: a preview against the X2 sandbox's synthetic run (watermarked), the field-path proof result per template, and a version diff between template versions. If any of these already exist for another country, reuse that component.

### X4 — Parallel-payroll comparison tooling (prepares G8)

G8 needs two parallel cycles with zero unexplained material differences. Build the tooling now so the pilot can start the day it is approved.

- Import of a legacy payroll's results per employee and concept (CSV with a documented column mapping, employees matched by an internal reference, never by RFC/CURP/NSS in the file name or logs).
- Comparison against a committed Zoiko run: per employee, per concept (net, ISR, subsidy, each IMSS branch, CEAV, INFONAVIT, ISN, employer cost), per period.
- Each difference gets a state (UNEXPLAINED → EXPLAINED / ACCEPTED) with a reason and a second reviewer for ACCEPTED.
- The materiality threshold is a release-owner decision: record it as the next free D-number, build the setting, and refuse to declare a cycle "clean" while it is empty.
- The MX-PARALLEL-DIFF report from X3 renders the result. Synthetic data only in tests.
- ZP-PRIV flag (tenant table, imported payroll data). One migration, additive, RLS through the helper.

### X5 — Ready-to-plug kits for the external inputs (C1, C3, C15, C7, C8)

No vendor code, no credentials, no production wiring. Build the parts that are independent of the vendor so the vendor-specific part becomes one small class.

- **PAC (C1).** A conformance test kit for any PacAdapter implementation: stamp accepted, stamp rejected, timeout → UNKNOWN then query_status reconciliation (MX-043, MX-062), duplicate idempotency key, cancel with and without replacement UUID, cancel status polling, CSD expired. A test-only fake adapter that passes the kit lives under tests/ and is never registered in mexico_pac._ADAPTERS. Write docs/mexico/PAC_SELECTION_CHECKLIST.md: the requirements a provider must meet (from spec §6, §20, MX-015 to MX-018, MX-062), the questions to send them, and what their sandbox must allow.
- **CSD custody (C3).** A credential-provider interface the signer reads through (fingerprint, expiry, status; never the private key outside the signer), a local test fake, and expiry alerts surfaced in the Super Admin employer view. The Secret Manager implementation waits for the security lead's decision; record the interface contract it must meet.
- **Durable XML storage (C15).** A storage interface for stamped XML with write-once semantics, content hash on write and read, and a retention field. Local filesystem implementation for tests only. The GCS implementation and the retention period wait for C15 and legal; document the contract.
- **SPEI (C7) and IDSE / SUA / SIPARE (C8).** For each, a one-page intake template listing exactly what file specification or layout source is needed and where the existing worklist output will plug in. No invented layout (rule: "no invented layouts").

### X6 — The IMSS incapacity record: proposal only (A10 Incapacidades)

This is worker health data. Write no code and no migration. Produce docs/mexico/INCAPACITY_RECORD_PROPOSAL.md for Rugvedh and legal: the minimum fields the CFDI Incapacidades node and the LSS Art. 31 contribution-day logic actually need (cite S4 / S28 and the W3-3 interface), what is deliberately not stored (diagnosis, medical notes), the legal basis question under the 2025 Federal Personal Data Protection Law (S23), access roles, encryption, retention, audit, redaction in reports, and the exact files and tests a build would touch. End with the questions they must answer. Mark it ZP-PRIV.

### X7 — Review and decision packets (make the owners' work fast)

- **Rugvedh (C16).** One packet per post-merge item: the sources gate (52af6eb), W4-2, W4-3b, W5-1, W5-2, W5-3, the A18 migration c7d2e9a4f1b6, plus every ZP-PRIV commit from this programme. Each packet: what changed (files, routes, tables, RLS), what data it touches, what is masked and where, the threat considerations, the tests that prove the controls, and a clear "approve / change requested" line. Put W4-3b first (it renders raw RFC / CURP / NSS) and Phase 11b's payslip_items.compliance_fields platform-wide finding in a separate note. File: docs/mexico/ZP_PRIV_REVIEW_PACKETS.md.
- **G1 owner (D-01 first).** docs/mexico/D01_ROUNDING_DECISION_BRIEF.md: one page, the candidate readings with what each source says (from MEXICO_TRANSCRIPTION_BATCH_2_REPORT.md §3), and the X2 sandbox's what-if results for the §21 fixtures under each candidate (watermarked). No recommendation. Then a short priority list for D-07, D-08, D-09, D-12, D-13, D-17 with the block codes each clears.
- **Sources (C2).** docs/mexico/SOURCE_DOWNLOAD_RUNBOOK.md: for each source a VERIFIED status would unlock, the official URL, the expected SHA-256 from the manifest, the exact verify_mexico_sources verify command, and which gate item it closes — so a colleague in Mexico or on a VPN can do it in one sitting.

### X8 — Super Admin configuration audit (close W5 for good)

Re-audit the Mexico Super Admin workspace against spec §11 panels A–H and §14 cards, now including the X1–X5 additions. For each configuration item, record: where it is configured, who can change it, whether it is four-eyes, whether it is effective-dated, and whether anything statutory can be changed outside a governed path. Fix gaps that are pure UI or wiring. Anything that needs a decision becomes a D-number. Browser-check every screen touched and add the screenshots to the progress file.

### X9 — Close-out

Full backend suite (5 chunks), frontend checks, then update MEXICO_COMPLETION_GAP_REGISTER.md, release-gates/G*/EVIDENCE_DRAFT.md (what the new tooling now produces) and write docs/mexico/MEXICO_FINAL_MILE_REPORT.md (§6).

## 4. Stop conditions — stop and ask only for these

1. alembic current in production is not c7d2e9a4f1b6, or the live app shows anything Mexican as Active.
2. A step cannot be built without choosing a statutory value, a threshold, a role or a source version (record it as a decision and continue with the next step; stop only if every remaining step depends on it).
3. A test failure you cannot fix without changing another jurisdiction's behaviour.
4. Any action that needs push, merge, production writes, credentials or secrets.
5. Machine resource exhaustion that persists after a clean rerun.

## 5. What you must not attempt

Choosing any decision; marking any source VERIFIED or creating another path to it; activating any pack, release, template, registry entry or pilot grant; signing or approving any gate; writing vendor-specific PAC, bank, IDSE, SUA or SIPARE code; storing any health data; any production write; configuring secrets; pushing or merging.

## 6. Reporting

- Per step: a section in docs/mexico/MEXICO_FINAL_MILE_PROGRESS.md — what changed, tests, a production-effect table, the ZP-PRIV flag if any, gap-register items moved, screenshots for UI steps.
- At the end: docs/mexico/MEXICO_FINAL_MILE_REPORT.md with
  1. session-zero results (production head, live-app check, privacy smoke secrets);
  2. every gap-register item and its state, with the item's next action and owner and whether that action is now in-product (X1–X5) or still outside;
  3. the local commits in order, each with production effect, migration (if any) and ZP-PRIV flag, grouped into reviewable PRs, with cd98323 first;
  4. the path to pilot as a dependency list: D-01 → golden vectors → … with each owner named;
  5. anything you found that contradicts an earlier report.

Start with §0, then §1, then X1.
