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
