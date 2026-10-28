# Mexico final mile — progress

Master prompt: `docs/mexico/MEXICO_FINAL_MILE_MASTER_PROMPT.md`. One section per step; the final report is `MEXICO_FINAL_MILE_REPORT.md`.

---

## §0 / §1 — Session zero (2026-10-27)

**Nothing was changed in production or in the code.**

### Git state

| Item | State |
|---|---|
| Branch | `nikhil` |
| Local HEAD | `cd98323`: the PRODUCTION_STATE record of PRs #134–#136, docs only |
| `origin/main` | `7075623` (PR #136: A17 + A18) |
| `cd98323` | **Local only, not pushed.** First in the hand-off: push when convenient, docs only |
| Uncommitted | Only your own files (`backend/app/main.py`, `backend/.env.example`, `frontend/vite.config.js`, three `docs/SINGAPORE_*`), plus untracked HK / SG docs and source binaries. None staged |

### Latest deploy runs (public GitHub Actions API)

| Run | Commit | Result |
|---|---|---|
| 40472214932 Deploy Backend | `7075623` (PR #136, migration `c7d2e9a4f1b6`) | success: test, single-head check, SSH deploy with head verification, drift check; the privacy smoke was skipped |
| 40458986909 Deploy Backend / 40458986971 Build Frontend | `262cc1f` (PR #135) | success / success |

PR #136 changed no frontend file, so no frontend build ran for it. The frontend served in production should be the PR #135 build; the live-app check below confirms what the server actually serves.

### Production head — confirmed by the deploy's own check, not by a manual `alembic current`

The associate has no access to the production server. Instead, the PR #136 deploy (run 40472214932, step "SSH and deploy backend", success at 08:35Z) runs on the server, after `deploy_migrate.sh`:
- `alembic current --check-heads`, which exits non-zero unless the database is at every head;
- a script that raises `SystemExit` unless the database heads equal the repository heads.

The repository's single head is `c7d2e9a4f1b6`, so production was at `c7d2e9a4f1b6` when that step passed. PR #137 was docs only and ran no deploy.

**Still worth doing** by someone with server access: `alembic current` on the VM. The job log is not readable here without repository admin rights. Recorded as the session-zero evidence; the programme continues.

### Live app check (read-only) — OPEN: needs a Super Admin sign-in (deferred to the hand-off)

This needs a Super Admin session on https://app.zoikopayroll.com. I have no credentials and must not record any. The proposed way: a headed Chrome window opened by the harness, where you sign in yourself. I then only navigate and take screenshots:
- `/super-admin/compliance/mexico`, every tab;
- the readiness view (all eight gates OPEN);
- no Mexican pack, release or registry entry Active;
- an org-route refusal (`MX_DORMANT`).

No write of any kind; the session is never saved; no real employee screen is opened.

### The skipped post-deploy privacy smoke (HP-10)

`backend-deploy.yml` runs "Post-deploy privacy smoke" only when `HAS_SMOKE` is true, which it is when the secret `ZP_SMOKE_BASE_URL` is non-empty. That is why run 40472214932 skipped it. The step (`backend/scripts/post_deploy_privacy_smoke.py`) needs these GitHub Actions repository secrets:

| Secret | Required | What it holds |
|---|---|---|
| `ZP_SMOKE_BASE_URL` | yes (switches the step on) | The API base URL the smoke calls |
| `ZP_SMOKE_IDENTITIES` | yes | JSON list of **synthetic** platform identities: `[{"role": "super_admin", "email": …, "password": …, "totp_secret": …}, …]`. These are platform roles that must never see worker data; the script logs in with TOTP (`pyotp`) |
| `ZP_SMOKE_EMPLOYEE_ID` | yes | An employee id in a **synthetic** smoke tenant, which those identities must be refused |
| `ZP_SMOKE_ALERT_WEBHOOK` | optional | Receives a JSON summary on failure |
| `ZP_SMOKE_RUN_ID` | set by the workflow | — |

**Who can configure them:** a ZoikoGroup repository admin (Actions secrets need admin rights on `zoiko-payroll-platform`). The synthetic tenant and identities must exist in production first, which is a decision for the release owner and the ZP-PRIV owner. Not configured here (rule: no secrets).

---

## X1 — The decision register in the Super Admin workspace

**Review required: Rugvedh (ZP-PRIV) before merge.** It adds a migration (`d3f8b2a6c1e9`, one new platform table), 8 Super Admin routes and a four-eyes rule. **Do not merge until reviewed — branch protection does not enforce this (C17).**

**What changed**
- **Table `payroll_mx_decisions`** (migration `d3f8b2a6c1e9` `mx_final_mile_m20`, child of `c7d2e9a4f1b6`). Each record holds:
  - code, version, title, gates, owner role (text);
  - the question and the sources it rests on;
  - the options, each with its sources;
  - the block codes it clears and the content keys it would populate;
  - the answer kind and the allowed values;
  - status, chosen option, rationale, the proposal's cited sources and a SHA-256 content hash;
  - the record it supersedes;
  - proposed-, approved- and transcribed-by, each with a timestamp, and the transcription reference.

  It is a platform table (no organisation, no worker data), so it has no RLS policy, like every Mexico platform table. User ids are plain integers, so the migration locks no existing table.
- **`mexico_decision_service`**, the state machine:
  - OPEN → PROPOSED → APPROVED (a **different** Super Admin) → TRANSCRIBED;
  - withdrawing a proposal returns it to OPEN; withdrawing an OPEN decision (with a reason) makes it WITHDRAWN;
  - revising an APPROVED record creates a new OPEN version; once that version is approved, the old one becomes SUPERSEDED.

  Approved records are immutable, and every action and every refusal is audited.
- **Typed answers**, validated at proposal and again at approval against the code that reads them:
  - D-01 through `rounding.parse` (MODE:QUANTUM);
  - D-02 against the Art. 96 periods or `UNMAPPED`;
  - D-07, D-07b, D-13, D-21 and D-22 against the values that are built.

  Everything else is free text.
- **Finding, and a fix that decides nothing:** D-01 option 2 is the CFF Art. 20 ¶10 whole-peso rule (S35 p. 31: "de 1 hasta 50 centavos … unidad inmediata anterior", "51 a 99 … superior"). That is round-half-down to 1, which the rounding grammar could not express. `HALF_DOWN` was added as a mode, so the option can be written `HALF_DOWN:1`. No content row uses it.
- **Seed** `scripts/seed_mexico_decisions.py`: every Open decision in `DECISIONS_PENDING.md` (D-15, which sources resolved, is skipped), D-07b (its own switch), D-23 and the gap register's C4, C5 and C12 — **26 records**. It is idempotent, needs the same confirmed target as the pack seed, and never runs on deploy. Markdown marks are stripped for display.
- **Transcription ticket** on every APPROVED record: the content key(s), the value, the citation `DECISION/<code>#<hash12>`, and the target "the next Draft version of the pack that carries the key (never an Active pack)". It is followed by seed, [PENDING G1], four-eyes approval, then activation gated on VERIFIED sources and signed gates.
- **Not built:** the canonical seed does not read decision records itself. The prompt allows it ("may"), but a decision-cited row would never pass the activation check `sources_verified`, which requires a VERIFIED manifest file. Whether a decision can stand as a row's source at activation is a question for the G1 owner and the ZP-PRIV owner, added to D-23's follow-ups. Today an engineer transcribes from the ticket.
- **Traceability:**
  - `GET …/decisions/by-block/{code}` lists the live decisions that clear an engine block code;
  - the W5-3 readiness view shows "open decisions N" per gate.
- **Routes** (all Super Admin, `platform` in the registry; 8 rows added, no other route reclassified):
  - `GET /decisions`, `/decisions/{id}`, `/decisions/by-block/{code}`;
  - `POST /decisions/{id}/propose`, `/approve`, `/withdraw`, `/revise`, `/transcribed`.

  The service functions have unique names: the first registry run classified `approve` and `withdraw` as worker routes through the name-collision gotcha.
- **UI:** a "Decisions" tab with filters by gate and status. Each decision shows its question, options with sources, the block codes it clears, the content keys it populates and its owner. It offers a propose form (a select when the answer is typed), and approve / withdraw / revise / mark-transcribed buttons, each behind a confirmation dialog. The ticket is shown once a decision is approved.
- **D-23 added:** no gate-owner role exists; until decided, any second Super Admin approves and the owner is text on the record.

**Tests**
- New `test_mexico_decisions.py` (9):
  - the seed reads the documents and is idempotent;
  - typed answers are refused outside their grammar;
  - `HALF_DOWN:1` gives the CFF whole-peso results (10.50 → 10, 10.51 → 11);
  - four-eyes, the hash and ticket, immutability and transcription;
  - a revision supersedes only once approved;
  - withdrawing a proposal reopens it and keeps the question's sources, and refusals are audited;
  - **an approved decision changes no calculation** (no `mx_rounding_rule` row appears; the engine still blocks `MX_ROUNDING_RULE_MISSING`);
  - traceability by block code and open decisions per gate;
  - the routes are Super Admin only and four-eyes over HTTP.
- New `test_mexico_final_mile_migrations.py`:
  - SQLite: idempotent upgrade and downgrade, no other table touched, no `organization_id` column.
  - **PostgreSQL 17, 3 of 3 runs:** in flight, no lock on any user table, only catalogue reads; `lock_timeout` is 5 s; about 0.11–0.21 s; `organizations` and `payslip_items` readable. The real `alembic upgrade head` from `c7d2e9a4f1b6`, no RLS policy on the table, and `check_schema_drift` all pass.
- Alembic head pins (`d3f8b2a6c1e9`, 230 revisions), the manifest, and the deploy-script pending-object pins (the new table is pending from `c7d2e9a4f1b6`; the migration names it literally so the self-heal sees it).
- Mexico + privacy tests: **1,324 passed, 81 skipped**. The only failures are the 3 known local-only `/health` route-registry tests. One more test (`test_mexico_migrations.py`, the Mexico table list) needed the new table and passes after it was added.
- Frontend: ESLint is clean on the changed files; `check:undefined` reports 582 files with no undefined names; the build passes.

**Browser: 13/13 PASS** (`docs/mexico/final-mile-evidence/RESULTS-X1.md`, harness `final-mile-evidence/harness/`). Every transition was done through the UI:
- the seeded list, the gate filter, and D-01's details;
- a refused non-grammar answer, then propose;
- self-approval refused on screen ("four-eyes");
- a second Super Admin approves, and the ticket appears;
- mark transcribed, then revise (v2 OPEN, v1 still in force);
- withdraw a proposal (back to OPEN), then withdraw an OPEN decision;
- readiness shows the open decisions.

The only 4xx responses are the two deliberate refusals, and the two console lines are the browser's own records of them.

Screenshots were inspected. The first pass showed two display defects, both fixed: markdown marks in titles and options, and C12 / C5 reading the wrong column for their gate. A third, the question's sources being lost on withdrawal, is fixed by the separate `question_sources` column.

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | **One migration** `d3f8b2a6c1e9`: a new empty platform table; no existing table locked. Production `c7d2e9a4f1b6` → `d3f8b2a6c1e9` |
| API | 8 new Super Admin routes (platform data) |
| Engine | None. `HALF_DOWN` is a new rounding mode no row uses |
| Seeding | None on deploy; the register is empty in production until someone runs the seed with a confirmed target |
| Other jurisdictions | None |

**Gap register:** D-01 … D-23, C4, C5 and C12 now have an in-product path: propose, then approve, then a ticket, then a Draft pack.

---

## X2 — Calculation sandbox and decision-impact preview

**Review required: Rugvedh (ZP-PRIV) before merge.** One new Super Admin route. It reads platform content only, writes nothing, and holds no organisation or worker data. **Do not merge until reviewed — branch protection does not enforce this (C17).**

**What changed**
- **`mexico_sandbox_service.run_mx_sandbox`.** It takes SYNTHETIC inputs:
  - pay date and period;
  - daily salary, minimum-wage zone, work state and pay frequency;
  - seniority date and work-risk premium;
  - a synthetic labour policy at the floors the spec's fixtures use (15 / 12 / 25%).

  It builds a `PayrollContext` and runs the production engine (`countries/mexico.calculate`) against the national and state packs covering the pay date. Draft packs are allowed and labelled "NOT ACTIVE — treated as in force for the sandbox only".
- **The answer** is either:
  - the engine's full result (ISR, subsidy, SBC segments with UMA, cap and floor, the SBC factor, every IMSS branch and side with its rate and band, INFONAVIT, ISN); or
  - the first block, with every preflight reason and, for each, the decisions that clear it (by block code; `MX_CONTENT_MISSING` by the missing content key).

  The engine raises without a partial trace, so a blocked answer shows the inputs and content used and the block, not the steps before it.
- **What-if.** `candidates` holds one or more `{decision, value}` pairs. Each is allowed only for a decision that is not yet approved (OPEN or PROPOSED) and populates exactly one pack-row key; a module switch is never patched, because that would touch code shared with real runs. The value is validated with the decision's grammar (X1), injected into an in-memory copy of the rows, never persisted, and the answer carries **CANDIDATE — NOT APPROVED — NOT A GOLDEN VECTOR**. Every answer also carries **SANDBOX — SYNTHETIC INPUTS — NOT A PAYSLIP**.
- **No writes.** The service never flushes or commits, and the route rolls back after every call. Tests compare every table's row count before and after, including after a commit.
- **Route:** `POST /super-admin/compliance/mexico/sandbox/calculate` (Super Admin; `platform` in the registry, the only registry change).
- **UI:** a "Sandbox" tab with the input form, presets for the spec's §21 fixtures F1–F4, a candidates editor, watermark badges, the content labels, and either the calculated tables or the block with "cleared by D-xx — see the Decisions tab".

**Findings (from the sandbox)**
1. **Even with D-01 decided, every calculation stops next at D-03.** The CEAV lowest-band reference `mx_ceav_lowest_band_min_wage_ref` is read for **every** SBC, not only for ZLFN employees in band 1. `ceav.band_for` evaluates band 1 first, and its lower bound "1.0 SM" needs the reference. This contradicts `DECISIONS_PENDING.md` D-03, which said it blocked only ZLFN band 1; corrected there. It is not an engineering fix: band 1 is in minimum-wage units and band 2 in UMA units, and with the 2026 values (UMA 117.31, minimum wage 315.04) the ranges overlap, so which band an SBC in the gap belongs to is part of D-03. **The path to the first computable case is D-01 and D-03.**
2. With D-01 and D-03 supplied as SYNTHETIC candidates, the engine reproduces the spec §21 control expectations on the transcribed Draft content:
   - **F1:** UMA 113.14 in January, 117.31 in February, and the 25-UMA cap moves with it;
   - **F2:** a first-year SBC factor of 1.049315;
   - **F3:** CEAV employer 7.513% in band 4.01 UMA, employee 1.125%, retiro 2% separate;
   - **F4:** a daily floor of 315.04 against 440.87, and 400 / day refused in ZLFN.

   These are engineering controls, not golden values: those still need independent reconciliation (spec §21), and the candidate values are test inputs, not decisions.

**Tests**
- New `test_mexico_sandbox.py` (14):
  - no pack means nothing is calculated;
  - today every run stops at `MX_ROUNDING_RULE_MISSING`, linked to D-01, on the labelled Draft pack;
  - D-01 alone stops at D-03;
  - F1, F2, F3 and F4;
  - candidates refused for a module switch, outside the grammar, for an unknown decision and for a malformed code;
  - an approved decision cannot be a candidate;
  - **nothing is written** (every table's count unchanged, even after a commit);
  - the route is Super Admin only and the candidate watermark is set.
- The X1 parser no longer treats the generic `MX_CONTENT_MISSING` as a decision's block code; it is traced by content key.
- Mexico + privacy tests: **1,338 passed, 81 skipped**. The only failures are the 3 known local-only `/health` route-registry tests.
- Frontend: ESLint is clean on the changed files; `check:undefined` reports 583 files with no undefined names; the build passes.

**Browser: 9/9 PASS** (`final-mile-evidence/RESULTS-X2.md`):
- x2-1: the expected D-01 block on the labelled Draft pack;
- x2-2: the D-01 → D-03 chain;
- x2-3 to x2-6: F2, F1, F3 and F4 through the presets, each watermarked CANDIDATE;
- x2-7: a D-07 candidate refused on screen;
- x2-8: no row written to the scratch database (the harness signs in before the snapshot);
- no 5xx and no page errors.

The only 4xx is the deliberate D-07 refusal. Screenshots inspected, including the watermark (`x2_02b`); the first pass showed the sticky header covering it, so a dedicated shot was added.

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None |
| API | One new Super Admin route; read-only, rolled back |
| Engine | None. The sandbox calls the engine with in-memory content |
| Other jurisdictions | None |

**Gap register / W7:** the G1 owner can now see every D-01 option's effect on the §21 fixtures before deciding. W7 (golden vectors) stays blocked on D-01 **and** D-03.

---

## X3 — Report-template catalog completion against the spec

**Review required: Rugvedh (ZP-PRIV) before merge.** **Do not merge until reviewed — branch protection does not enforce this (C17).** Four things need his eye:
1. Every render of the printed CFDI receipt (W4-3b, the one view that shows RFC / CURP / NSS) is now recorded as a `RECEIPT_RENDERED` CFDI event (who, when; no identifier), and a new report lists those renders.
2. The existing org route `POST /reports/{template_id}/generate` now reads more Mexico tables: SBC history, variable accumulators, benefit accruals and payment items. Its registry row's worker-table list grew accordingly; it is still `worker` / `org_admin` / tenant-scoped.
3. Three new read-only Super Admin routes, all `platform`.
4. The coverage view was deliberately kept from reading tenant payslips (below).

### Coverage matrix: spec → template → state

| Spec | Report | Template | State |
|---|---|---|---|
| §13 stage 2, §20 journal | Payroll register; employer cost; journal | MX-PAYROLL-REGISTER, MX-EMPLOYER-COST, MX-JOURNAL | Existing (W4-1) |
| §9, §10 | IMSS branches; INFONAVIT | MX-IMSS-BRANCH, MX-INFONAVIT | Existing (W4-1) |
| §6 / MX-009–011 | Subsidy; aguinaldo; finiquito; annual adjustment | MX-SUBSIDY, MX-AGUINALDO, MX-FINIQUITO, MX-ANNUAL-ISR-ADJ | Existing (W4-1) |
| §14, §15 | ISR monthly; SUA; SIPARE; IDSE; CDMX ISN return | MX-ISR-MONTHLY, MX-SUA-RECON, MX-SIPARE, MX-IDSE-MOVEMENTS, MX-ISN-RETURN-CDMX | Existing (W4-2), "not an official file" |
| §5, MX-017–018 | CFDI status; printed receipt | MX-CFDI-STATUS, MX-CFDI-NOMINA-RECEIPT | Existing (W4-2, W4-3b) |
| §16, MX-055 | Vacation accrual; PTU distribution | MX-VACATION-ACCRUAL, MX-PTU-DISTRIBUTION | Existing (W4-2) |
| §13 stage 4 | Variance vs prior, high-value deltas | **MX-RUN-VARIANCE** | **New.** Deltas flagged only against D-24 |
| §13 stages 1 and 3 | Preflight exceptions | **MX-PREFLIGHT-EXCEPTIONS** | **New** |
| §7, §12 IMSS, MX-019–020 | SBC, bimester accumulators, movements | **MX-SBC-MOVEMENTS** | **New** |
| §14 card, MX-026, MX-044 | Work-risk premium history | **MX-WORK-RISK-ANNUAL** | **New**, "not an official file"; review-year cases are not recorded (no source) |
| §10, MX-031 | INFONAVIT notices | **MX-INFONAVIT-NOTICES** | **New**; credit numbers masked to their last four digits |
| §13 stage 3, §16, §17 | Labour compliance exceptions | **MX-LABOR-COMPLIANCE** | **New** |
| §20, Phase 10a | Net-pay settlement worklist | **MX-PAYMENT-WORKLIST** | **New**, "NOT A BANK FILE" (C7); account shown as its last four digits |
| §20, MX-061 | Who rendered the unmasked receipt | **MX-IDENTIFIER-ACCESS-AUDIT** | **New** |
| §22 G8, MX-064 | Parallel-payroll differences | MX-PARALLEL-DIFF | In **X4**, with the import it reports |

### What changed
- **`mexico_report_service`.** The eight new report types are built from Mexico's own views and tables, never recomputed:
  - run variance (committed payslips of the run and of the prior committed run);
  - preflight (`run_preflight`);
  - SBC history, accumulators and IMSS movements;
  - registrations with their premiums;
  - INFONAVIT notices;
  - labour results and benefit accruals;
  - payment batches and items;
  - receipt-render events.

  Employees appear by employee code; no RFC, CURP, NSS or CLABE appears.
- Each type has its gate mapping for the activation gate (W4-3a) and is added to `service.MX_DEDICATED_GENERATOR_REPORT_TYPES`, a shared list that grows additively, so the generic generator refuses them.
- Eight Draft templates are seeded, each with a "No components: generated by …" description.
- **D-24** (release owner): the variance high-value threshold, an `AMOUNT` decision in the register (the `AMOUNT` answer kind was added to the migration's check, which is not yet merged). The report flags nothing until D-24 is approved.
- **Receipt render audit:** `mexico_cfdi_receipt.record_render` is called by the receipt route after each PDF render.
- **Library tools (X3b).** All three routes are Super Admin and `platform`:
  - `GET …/report-templates/coverage`: each template's build kind, gates and a **catalogue check**. The real-payslip half of the field proof reads tenant payslips, so it stays only inside the activation gate. Keeping it out of this platform view is what kept the route `platform`; the first registry run classified it `worker`.
  - `GET …/report-templates/compare?from&to`: the field and metadata diff, with content hashes.
  - `POST …/report-templates/{id}/sandbox-preview`: a snapshot-field template's fields resolved against one sandbox (X2) result. It is watermarked **SANDBOX PREVIEW — SYNTHETIC — NOT A REPORT** plus the X2 marks, never stored, rolled back, and refused for a dedicated-generator template.
- **UI:** a "Mexico template library" panel on the Mexico report-templates page, with coverage, compare and preview.

### Tests
- New `test_mexico_report_x3.py` (10):
  - every X3 template is seeded as Draft and refused by the generic generator;
  - each X3 report is built from the views, with **no full RFC / CURP / NSS / CLABE** in any rendered report;
  - variance flags nothing until D-24 is approved (a non-amount answer is refused; an approved `0` flags);
  - variance needs a committed run of the organisation, and missing or foreign runs are refused;
  - receipt renders are audited and reported without identifiers, and another tenant's render records nothing;
  - the activation gate covers every X3 type;
  - coverage, compare, the watermarked preview (blocked without candidates, `9000.0000` gross with them), and Super-Admin-only routes.
- Mexico + privacy + shared report-template tests: **1,441 passed, 81 skipped**. The only failures are the 3 known local-only `/health` route-registry tests. The Mexico template-count pin went from 18 to 26.
- Frontend: ESLint is clean on the changed files; `check:undefined` reports 584 files with no undefined names; the build passes.

**Browser: 7/7 PASS** (`final-mile-evidence/RESULTS-X3.md`), with no 4xx and no console errors:
- the eight new templates listed as Draft, built by their dedicated generators;
- the catalogue checks;
- a version diff with hashes;
- the preview blocked at D-01 without candidates, then resolved and watermarked with them;
- the organisation report route refused while Mexico is dormant (an NL org admin).

Screenshots inspected.

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None beyond X1's migration (one check value, `AMOUNT`, added before merge) |
| API | Three read-only Super Admin routes. The org report route gains eight report types; it refuses while Mexico is dormant |
| CFDI | Each receipt render writes one CFDI event (no identifier) |
| Templates | Eight more Draft templates when someone runs the template seed by hand |
| Other jurisdictions | None. `MX_DEDICATED_GENERATOR_REPORT_TYPES` grew; NL / IE / SE / DE report paths are pinned by the shared report tests run here |

---

## X4 — Parallel-payroll comparison (spec §22 G8, MX-064)

**Review required: Rugvedh (ZP-PRIV) before merge.** **Do not merge until reviewed — branch protection does not enforce this (C17).** What needs his eye:
1. **Migration.** Two new tables join the programme's one revision `d3f8b2a6c1e9`:
   - `payroll_mx_parallel_imports` is a TENANT table;
   - `payroll_mx_parallel_differences` is a WORKER table (it has `employee_id`).

   The revision puts row-level security on these two tables only, with the predicate `d7f9b1c3e5a6.classify()` derives (tenant / worker-org). It is never a sweep over every table.
2. **Six org routes**, all tenant-scoped and dormancy-guarded:
   - the registry classifies five as `worker` and the withdraw route as `tenant_config`;
   - reads need a payroll operator, writes an org admin.
3. **Imported payroll data.** Legacy amounts per employee are stored, but never the file: only the column mapping, the SHA-256 and counts.
4. **Identifier refusal.** A column named like an identifier, or a cell shaped like an RFC, CURP, NSS or CLABE, refuses the whole file, and the refusal names only the row. Reasons are scanned the same way.
5. The existing `POST /reports/{template_id}/generate` registry row gains `payroll_mx_parallel_differences`.

### What was built
- **Import.** `mexico_parallel_service.import_parallel` takes the CSV text from the browser plus a column mapping for the employee code and any of 12 concepts:
  - net; ISR withheld; subsidy applied;
  - IMSS employee and employer; retiro; CEAV employee and employer;
  - INFONAVIT employer and credit;
  - ISN; employer total.

  It runs against a **committed** run of the caller's organisation. Employees are matched by **employee code only**. Zoiko's side is read from each payslip's frozen snapshot, never recomputed. Unmatched codes are listed on both sides. A re-import supersedes the CURRENT import, which then cannot be edited.
- **Review.** Each employee × concept is either MATCH or UNEXPLAINED. **EXPLAINED** needs a reason; **ACCEPTED** needs a **different** org admin (four-eyes). Nothing here ever changes a payslip.
- **D-25 (new decision: release owner, G8, AMOUNT)** sets the materiality threshold. While it is unapproved, **no cycle is ever declared clean**: the verdict is "not decidable". With it approved, a cycle is clean only when no unaccepted difference exceeds the threshold and no employee is unmatched. Zoiko picks no tolerance.
- **Report.** `MX_PARALLEL_DIFF` (template `MX-PARALLEL-DIFF`, Draft, gate G8) is a dedicated generator reading the import view. Employees appear by code.
- **UI.** A "Parallel payroll" panel in the Mexico Compliance Centre: file, column mapping, differences, explain / accept, and the verdict.

### Tests
- **New `test_mexico_parallel.py` (9):**
  - D-25 is seeded as an Open G8 AMOUNT decision;
  - an identical cycle matches but is not clean until D-25 is approved;
  - a reason, then a second reviewer, are required, with materiality applied against D-25;
  - identifier columns, values, match keys and reasons are refused without echoing the value, and nothing is recorded;
  - bad mapping, amounts and duplicates are refused, and unmatched employees are listed;
  - another tenant's import or run returns 404;
  - re-import supersedes and freezes the old import, and withdraw works;
  - an uncommitted run is refused;
  - the report has no full identifier;
  - the routes enforce four-eyes over HTTP.
- **Pins updated:**
  - `MX_M20_TABLES`;
  - the deploy pending-object pins (`MX_X4_TABLES`);
  - the template count, now 27;
  - the dormancy `ORG_ROUTES` (+6);
  - the route registry and inventory, regenerated with only the six new rows and one changed row.
- **PostgreSQL 17** (throwaway cluster, `test_mexico_final_mile_migrations.py`): **6/6** pass. Measured:
  - in flight, no existing table is locked exclusively;
  - organizations, payroll_runs and payroll_employees hold SHARE ROW EXCLUSIVE: reads continue and a writer's NOWAIT is refused;
  - the revision was held about 208 ms;
  - with a writer on payroll_runs, the upgrade gave up after **5.14 s** with nothing applied;
  - RLS is enabled and forced with the `zoiko_rls` policy on the two X4 tables, `classify()` agrees, and the decisions table has no policy;
  - the real CLI upgrades from `c7d2e9a4f1b6` and `check_schema_drift` passes.
- **Full suite** (5 sequential chunks, scratch SQLite): **7,624 passed**, 127 skipped, 2 xfailed. The only failures are the known local-only ones: the three `/health` route-registry tests (the associate's uncommitted `main.py`) and the HK configuration docs test. One manifest failure appeared because the migration docstring was edited after the manifest was regenerated; the manifest was regenerated again (this revision is unmerged) and its tests now pass.
- **Frontend.** ESLint is clean on the new panel and the tab. The 32 `no-useless-catch` errors in `payrollService.js` are at existing lines 2146–2240, not in the eight added lines. `check:undefined` reports 585 files with no undefined names, and the build passes.

**Browser:** **10/10 PASS** with the flag on and **8/8** with it off (`final-mile-evidence/RESULTS-X4-on.md` and `RESULTS-X4-off.md`). The new harness files are `setup_x4.py`, `serve_x4.py`, `x4_patches.py` and `x4_legacy.csv`; the synthetic identifiers for the leak scan stay in the scratchpad.

With the flag on:
- the identifier file is refused (row named, value not shown);
- the import shows 2 matches, 1 unexplained net difference of 12.50, the unmatched legacy employee, and **NOT DECIDABLE (D-25 unset)**;
- the explainer's own accept is refused;
- the second admin accepts;
- no identifier appears in the panel or the API;
- the NL admin sees no Mexico panel and gets 403 from the API.

With the flag off, all six routes are refused and the panel shows the dormancy message. Screenshots inspected.

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | Two more tables in the unmerged `d3f8b2a6c1e9` (still one head). The brief SHARE ROW EXCLUSIVE lock on organizations, payroll_runs and payroll_employees is measured above; deploy at a quiet time |
| API | Six org routes, all refused while Mexico is dormant (production) |
| Templates | One more Draft template when the template seed is run by hand |
| Other jurisdictions | None. `MX_DEDICATED_GENERATOR_REPORT_TYPES` grew by one; dormancy and registry tests cover the rest |

---

## X5 — Ready-to-plug kits for the external inputs (C1, C3, C15, C7, C8)

**Review required: Rugvedh (ZP-PRIV) before merge.** **Do not merge until reviewed — branch protection does not enforce this (C17).** What needs his eye:
1. A new Super Admin route, `GET /super-admin/compliance/mexico/csd-expiry`. It is classified `platform` / `super_admin` and reads tenant CSD credential metadata **across every organisation**: the organisation's name, employer profile id, certificate serial, validity and the **first 12 hex characters** of the fingerprint. It never returns the secret reference or the RFC.
2. The CSD custody interface: the key never leaves custody, and nothing in the interface can return it.

No migration, no new tenant table, and nothing installed in production.

### What was built (no vendor code, no credentials, no production wiring)

| Gap | Built | Production state |
|---|---|---|
| **C1 PAC** | **Conformance kit** `tests/_mx_pac_conformance.py`: 10 checks (stamp accepted / rejected, timeout → UNKNOWN then status FOUND with the same UUID on retry, timeout before stamp → NOT_FOUND, duplicate idempotency key, cancel with and without replacement, cancel-status polling, expired CSD, no XML in messages). A driver tells the kit how to provoke each scenario in a sandbox; a scenario it cannot provoke is NOT_RUN, never PASS. **Fake adapter** `tests/_mx_fake_pac.py` passes all 10. It is never registered in `_ADAPTERS`. **`PAC_SELECTION_CHECKLIST.md`**: 15 requirements, 13 questions for candidates, the sandbox facilities per kit check, and the steps after the choice | `_ADAPTERS` still empty: `MX_PAC_NOT_CONFIGURED` |
| **C3 CSD custody** | `mexico_csd_custody.py`: the `CsdCustodyProvider` interface (`describe` → public facts; `sign` → signature + public certificate). **`CustodySigner`** checks the CSD is ACTIVE, the fingerprint matches the recorded one, and the certificate is in force, all **before** any signature, then hands the signature to a sealer. **Expiry alerts** (expired / missing / within `MX_CREDENTIAL_EXPIRY_WARNING_DAYS`) on the Super Admin Mexico → Employer tab, for every organisation. Test provider `tests/_mx_fake_csd.py`. **`CSD_CUSTODY_CONTRACT.md`** | `_PROVIDERS` empty; the active signer is still `GcpSmSigner` (`MX_CSD_SIGNING_BLOCKED`); `CustodySigner` without a sealer refuses with `MX_CSD_SEALER_NOT_BUILT` |
| **C15 XML storage** | `mexico_xml_store.py`: the `StampedXmlStore` interface with shared rules: write-once (same bytes idempotent, different bytes `MX_CFDI_XML_WRITE_ONCE`), SHA-256 and size checked on read (`MX_CFDI_XML_INTEGRITY`), `retention_until` (None = undecided, so deletion refuses), and a key check (no traversal, no identifier). Local filesystem store **in tests only**. **`CFDI_XML_STORAGE_CONTRACT.md`** | `_STORE` None: `MX_CFDI_STORAGE_NOT_DURABLE`. The existing CFDI path is unchanged |
| **C7 SPEI**, **C8 IDSE / SUA / SIPARE** | One-page intake templates, `intake/SPEI_INTAKE.md`, `IDSE_INTAKE.md`, `SUA_INTAKE.md`, `SIPARE_INTAKE.md`: exactly which specification, samples and decisions are needed, and the function each will plug into (`export_worklist`, `record_item_outcome`, `enter_sua_figures`, `record_sua_payment` …) | Worklists only. **No layout invented** |

Nothing here chooses a provider, custody, bucket or retention period. Those are named as decisions in each document. The storage contract cites no retention law: the period is legal's decision.

### Tests
- New:
  - `test_mexico_pac_conformance.py` (7): the fake passes all checks; the kit **catches** a timeout reported as REJECTED, a second CFDI for the same key, an expired CSD that stamps, and a cancellation that never settles; an unprovokable scenario is NOT_RUN; nothing reaches `app/`;
  - `test_mexico_csd_custody.py` (10): production refuses; a custodied signature verifies against the public certificate; six custody refusals sign nothing; expiry alerts (expired / expiring / missing / fine / other org); the Super Admin route and an org admin's refusal;
  - `test_mexico_xml_store.py` (10): put/get with the hash, write-once, a tampered file refused, retention, key checks, and production with no store.
- Route registry regenerated: **one** new row (`csd-expiry`, `platform`).
- **Full suite** (5 sequential chunks, scratch SQLite): **7,651 passed**. The only failures are the known local-only ones: the three `/health` route-registry tests, the HK configuration docs test, and the intermittent communications dispatch test (alone it failed once and then passed twice; X5 does not touch it).
- Frontend: ESLint is clean on the new and changed files; `check:undefined` reports 586 files with no undefined names; the build passes.

**Browser: 6/6 PASS** (`final-mile-evidence/RESULTS-X5.md`; harness `setup_x5.py` adds a SYNTHETIC expiring CSD and a PAC reference to the X4 scratch DB):
- the Employer tab lists the EXPIRING CSD with its organisation, serial and masked fingerprint;
- the PAC reference is not listed;
- no `gcp-sm` reference appears in the page or the API;
- an org admin is refused.

Screenshot inspected (`x5_01_csd_expiry_alerts.jpg`).

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None |
| API | One read-only Super Admin route |
| UI | A CSD-expiry card on the Super Admin Mexico Employer tab |
| CFDI | None. The new interfaces are not installed, and generation, signing and stamping refuse exactly as before |
| Other jurisdictions | None |

---

## X6 — The IMSS incapacity record: proposal only (A10 Incapacidades)

**ZP-PRIV. Review required: Rugvedh (ZP-PRIV) and legal before any build.** Documentation only: no code, no migration, no table.

`INCAPACITY_RECORD_PROPOSAL.md` covers:
- the minimum fields, from the pinned `nomina12.xsd` (S28 lines 609–642: `DiasIncapacidad` required ≥ 1, `TipoIncapacidad` required from `c_TipoIncapacidad`, `ImporteMonetario` optional) and the W3-3 interface (`Lss31ContributionDays.branch_days`, S10 Art. 31, S27 Art. 29);
- what is deliberately not stored (diagnosis, medical notes, prognosis, free text);
- the S23 legal-basis question, access roles, encryption, retention (a new `HEALTH_INCAPACITY` category starting BLOCKED_UNDECIDED), audit and redaction;
- the exact files and tests a build would touch, and ten questions for Rugvedh and legal.

**Finding (reported, not changed):** `mexico_run_service._attendance_counts` counts any "sick" leave row as an IMSS incapacity day. LSS Art. 31 IV covers only IMSS-certified incapacity; an uncertified sick day is an Art. 31 I absence, and the two give different contribution days. No production effect (Mexico is dormant), but it must be fixed before G2, by the record this proposal asks permission for. Question 9 asks the owners to confirm the reading.

**S23 (the 2025 personal data law) is not saved** in `docs/mexico/sources/`, so no article is cited; saving it goes into the X7 source runbook.

**Production effect:** none (documents only).

---

## X7 — Review and decision packets

Documents only; no code and no production effect.

- **`ZP_PRIV_REVIEW_PACKETS.md` (Rugvedh, C16):** 13 packets.
  - **W4-3b first.** It renders raw RFC / CURP / NSS. Its controls are org_admin only, organisation-scoped, rendered on demand, `no-store`, and every render audited since X3.
  - **One test gap is flagged honestly:** no test asks for another organisation's *real* receipt. Only a non-existent id is tested; the code does check the organisation.
  - Then the sources gate, W4-2, W5-1, W5-2, W5-3, the A18 migration, and X1–X6, each with what changed, the data, the masking, the threats, the proving tests and an approve / change-requested line.
  - A separate note on `payslip_items.compliance_fields` (the platform-wide plaintext identifier snapshot, Phase 11b finding, Q9 / HK D-4).
  - It also lists the earlier reviews still pending: 10c, 10f, 10g, 11a, 11b.
- **`D01_ROUNDING_DECISION_BRIEF.md` (G1 owner):** no recommendation. It gives what each source says, three candidate readings (`HALF_UP:0.01`, `HALF_EVEN:0.01`, `HALF_DOWN:1`), and the "when" question, which the `MODE:QUANTUM` grammar cannot record.
  - It includes the **X2 what-if results** for the §21 fixtures under each reading, watermarked, with D-03 held at the candidate GENERAL. Script `final-mile-evidence/harness/d01_whatif.py`; output `D01_WHATIF_RESULTS.json`.
  - **Facts:** HALF_UP and HALF_EVEN are identical on every fixture (no exact half centavo), and whole pesos change every amount by up to 0.99.
  - Then the order for D-03 (the second blocker on every calculation), D-07, D-08, D-09, D-17, D-12 and D-13, with the block codes each clears.
- **`SOURCE_DOWNLOAD_RUNBOOK.md` (C2):** generated from the manifest. For each of the 32 non-VERIFIED files: the official URL, the full expected SHA-256, the exact `verify` command (with `file=` where a code has several files), what it unlocks and its gate.
  - It also covers the WRONG_VERSION S22 file, what a MISMATCH means for the consolidated laws, and the sources the gates cite that are not saved at all (S5, S8, S12–S17, S19–S21, S23, S31–S33).
  - `verify_mexico_sources check` passes locally (exit 0).

**Contradiction found:** the master prompt points to `MEXICO_TRANSCRIPTION_BATCH_2_REPORT.md` **§3** for the rounding candidates. They are in **§4** (§3 is S22). The brief cites §4.

---

## Incident — PR #138 left two Alembic heads (fixed by merge revision 92c67cab49fc)

PR #138 merged Mexico m20 (`d3f8b2a6c1e9`) and South Africa (`447f57564983 → c15d5b87d6f5`, Venu) into `main`. Both grow from production's `c7d2e9a4f1b6`, so `main` had two heads. Git's auto-merge also kept **both** sides' pins in `test_alembic_metadata.py` and `test_deploy_migrate_script.py`.

- **Deploy run 40628518029 failed at the test stage; the backend deploy was skipped**, and production stayed at `c7d2e9a4f1b6`.
- **The frontend deployed anyway** (it is a separate workflow), so the new Super Admin Mexico screens called routes that were not yet live.

**Fix** (`8635a7e`, merged as PR #139):
- an empty merge revision `92c67cab49fc`, touching neither author's migration;
- pins rewritten from the real merged chain (`pending_objects()`), including a one-line change in Venu's `test_south_africa_migrations.py`;
- the manifest regenerated.

**Proof:** on PostgreSQL 17, `alembic upgrade head` from `c7d2e9a4f1b6` succeeds and `check_schema_drift` passes. The full suite passed 7,899 (known local-only failures only). The GitHub-reported failures, including the Singapore snapshot fallout, pass (53/53).

**Lesson** (recorded in memory): before a merge to `main`, compute the heads of the merge result.

---

## X8 — Super Admin configuration re-audit

**Review required: Rugvedh (ZP-PRIV) before merge.** **Do not merge until reviewed — branch protection does not enforce this (C17).** The fixes change a shared statutory write path (`service.py`, Mexico-only checks) and the governed-evidence rules.

The full audit table (platform and organisation, every item: where configured, who, four-eyes, effective-dated, any ungoverned path) is in **`MEXICO_SUPER_ADMIN_CONFIG_AUDIT.md`**.

**Fixed:**
1. **A statutory value could change outside a governed path.** The generic slab and rate editors checked only the *target* pack, so a row of an Active Mexico pack could be moved into another country's editable pack and changed. `_existing_row_pack` now checks the row's current pack first. **The same hole exists for every other country**; it is reported, not changed.
2. Mexico gate and decision evidence is governed: review needs an uploaded file, and a reviewed file is never replaced (previously a gate stayed SIGNED on a replaced file).
3. No editor of a Mexico report-template version may approve it (MX joins HK).
4. A Super Admin who added CFDI catalog entries may not approve that release.
5. UI: "Reconcile after restore" on the run's CFDI stage (the UNKNOWN-state runbook step had no screen), and the Readiness text on evidence.

**Decisions added:**
- **D-26:** four-eyes on general availability.
- **D-27:** four-eyes on retiring Active content.
- **D-28:** organisation-side four-eyes and effective dating.

**Reported, not changed:**
- org payroll operators can create MX *policy* packs (no Mexico code reads them);
- NULL-maker four-eyes (system rows);
- the master-copy routes versus the UI;
- pack status changes from the UI send no reason (shared screen).

**Tests:** new `test_mexico_config_audit_x8.py` (7):
- a row move is refused and both packs are untouched;
- another country's editor is unchanged;
- MX evidence: review without a file is refused, and replacement after review is refused (G1 still SIGNED);
- an ordinary source is not governed;
- the template any-editor rule;
- catalog entry authors are refused.

The W5-2 and HK remediation tests still pass (62/62 with the new file).

- **Full suite** (5 sequential chunks, scratch SQLite): **7,906 passed**. The only failures are the known local-only ones (the three `/health` route-registry tests and the HK configuration docs test).
- Frontend: ESLint is clean on the changed files, and `check:undefined` reports 602 files. The build passes.

**Browser: 5/5 PASS** (`final-mile-evidence/RESULTS-X8.md`, harness `acceptance_x8.py` on the X4 scratch world):
- the reconcile button is shown;
- cancelling sends nothing;
- confirming sends one POST;
- the Readiness rule text appears;
- no 5xx and no page errors.

Screenshots inspected.

**Production effect:**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None |
| Super Admin | Mexico rows can no longer be moved by the generic editors. Mexico evidence files are frozen once reviewed. Stricter template and catalog approval |
| Organisation | One new button (dormant while Mexico is off) |
| Other jurisdictions | None. Each change is a Mexico entry in a per-country list or a Mexico-only check |
