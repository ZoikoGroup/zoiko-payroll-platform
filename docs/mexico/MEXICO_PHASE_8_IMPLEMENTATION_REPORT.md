# Mexico (MX) — Phase 8 Implementation Report: Authorities (IMSS / SUA / INFONAVIT / ISR / state ISN)

Spec ZP-MX-ENG-001 v1.0 §8 (MX-023–MX-026), §10 (MX-031–MX-033), §14 (MX-042–MX-044), §15 (MX-045–MX-047) · plan `MEXICO_PHASE_8_PLAN.md`.

**Base.** `nikhil` = `9e00a20`, the same tree as `origin/main` `b041ead` (PR #109, Phase 7). PR #109's deploy run `39200794145` and frontend build `39200794149` were green, so production should be at `d8b3e5f1a2c7`.

**Alembic.** Before this phase there was a single head, `d8b3e5f1a2c7` (202 revisions). Now there is a single head, **`e3b9c2d7f4a1`** (203 revisions).

**Decisions.** The instruction was "start implementing next phase" with D1–D12 unanswered, so **every recommendation in plan §12 was built**:
- D1: file-export only;
- D2: movement sources (every committed SBC change, withdrawable with a reason);
- D3: no due-date fallback;
- D4: calendar-month accrual;
- D5: zero tolerance, Zoiko template;
- D6: four-eyes;
- D7: reset scope;
- D8: no writes to `statutory_filings`;
- D9: reference-only evidence;
- D10: work-risk deferred;
- D11: Active-pack states only;
- D12: on-request, audited worklist.

Each remains yours to change.

The work is **staged on `nikhil`**. Nothing is committed, pushed or merged.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite, 5 chunks (324 files) on scratch SQLite, after every change in this report | **6,705 passed, 1 failed, 62 skipped, 2 xfailed** (6,770 tests). The failure is **OOS-4**: the HK test that reads the untracked local HK owner pack. It does not depend on code and is not Mexico. |
| Phase 8 tests | `test_mexico_authorities_liabilities.py` (8), `_movements.py` (9), `_unknown.py` (6), `_sua_isn.py` (7), `_reset.py` (6), `_routes.py` (2), `_migrations.py` (6, of which 4 run on PostgreSQL). All pass. `test_mexico_dormancy.py` lists the 30 new org routes: all 403 with the flag off. |
| Migration on **PostgreSQL 17** (throwaway cluster) | 4/4 PG tests, including the real `alembic upgrade head` through `env.py`, `alembic current` and `check_schema_drift`. Lock times are in §3. The Phase 6 and 7 PG tests also pass after their CLI assertion fix (§6.4); 18/18 across the three files. |
| Browser, flag **off** (the production setting) | **12/12.** `phase8-evidence/RESULTS-off.md`; screenshots inspected. |
| Browser, flag **on** (synthetic world, two admins) | **16/16**, with no 5xx and no page errors. `phase8-evidence/RESULTS-on.md`; screenshots inspected. The two 400s in the log are the deliberate refusals of check on-6b. |
| ESLint | **0 errors** in every new or changed Mexico file. `CompliancePage.jsx` has 1 error, identical to HEAD. |
| `check:undefined` / `vite build` | 520 files clean / passes. |

## 2. What was built (plan order §10)

**Migration `e3b9c2d7f4a1` (mx_authorities_m6)** creates seven **new** tables and no shared column:
- `payroll_mx_imss_movements`;
- `payroll_mx_authority_liabilities` and `payroll_mx_authority_liability_sources`;
- `payroll_mx_sua_periods` and `payroll_mx_sua_differences`;
- `payroll_mx_isn_returns`;
- `payroll_mx_authority_events`.

Each has a literal `op.create_table`. The migration is guarded, runs under `SET LOCAL lock_timeout = '5s'`, and its downgrade drops only these seven tables. Constraints:
- unique `idempotency_key` on every transmittable object;
- `uq_mx_liability_source_row` (source table + row): a committed row is linked once;
- a partial unique "one live movement per committed event".

**Content (value-free, `mexico_content.py`).** Every one of these is empty until a source is saved:
- `MovementDeadlineRule` / `MX_IMSS_MOVEMENT_DEADLINE = None` (S13 / S10);
- `MX_OFFICIAL_HOLIDAYS = {}`, a list per year;
- `MX_AUTHORITY_RETRY_CONFIG = {}`, with no default;
- `MX_LIABILITY_REPORT_TYPES`, the structural map of authority → filing-calendar report type.

**Backend**

- **`mexico_due_dates.py`** (B2). A liability or return is dated only by an **Active** row of the shared filing calendar, which is seeded only from verified `MX_FILING_CALENDAR` rules. A movement is dated only by the transcribed deadline in business days, skipping the transcribed holidays of every year the count crosses. Otherwise the answer is `DUE_DATE_UNSOURCED`. The shared weekend-only `_add_business_days` is never used, and a test proves it.
- **`mexico_authority_lifecycle.py`** (§4, B7). It holds the state machine of each object and the append-only events. It enforces the **UNKNOWN rule**:
  - each object has one transmission step;
  - an unknown outcome is UNKNOWN, never FAILED;
  - a status check comes first (FOUND adopts the reference; NOT_FOUND is recorded);
  - a retry only after a NOT_FOUND, confirmed by an admin with a reason, reusing **the same row, payload hash and idempotency key**;
  - a late FOUND after a confirmed but unsent retry adopts the reference, so nothing is sent twice;
  - a changed payload can never be re-sent (`MX_AUTHORITY_PAYLOAD_CHANGED`);
  - "definitively not found" needs channel config with ≥ 2 checks and a wait, and has no default.

  It also holds the four-eyes check (`MX_FOUR_EYES_REQUIRED`).
- **`mexico_filing_service.py`** covers:
  - **B3 ledger:** SAT_ISR per organisation, IMSS and INFONAVIT per IMSS registration, ISN per state, by pay-date month, accrued only from committed runs. Accrual is idempotent, each amount traces to its payslip, and rows committed after a period left Zoiko go to a complementary liability (`sequence` + 1). Filing and payment are recorded references; reconciliation is four-eyes and needs the RECONCILED SUA period (IMSS / INFONAVIT) or the ACCEPTED return (ISN).
  - **B4 SUA:** Zoiko per-worker × per-branch × per-side totals against the SUA figures the operator enters. Zero tolerance; each difference is OPEN → EXPLAINED (Zoiko workflow code + text) → APPROVED by someone else. A period reconciles only with every difference approved, only by someone other than whoever entered the figures, and is refused if committed amounts changed since (`MX_SUA_STALE`). The SIPARE payment is recorded by reference.
  - **B5 ISN returns:** one per state × month, with the MX-046 three-way check (employee detail = return = ledger) required before filing. Filing a return files the state's liabilities. A later committed run means an **amendment**, a new row with `amendment_of_id`; the original is never edited. An OPEN ISN registration is required.
  - **B6:** the ISR remittance record is the SAT_ISR liability.
  - **B8 reset:** `downstream_reasons` and `withdraw_on_reset`.
  - The run's Authorities lane.
- **`mexico_imss_service.py`** covers:
  - **B1 movement generation** (D2):
    - ALTA from the first committed SBC row under a registration, dated by `date_of_joining` (required);
    - MODIFICACION for every committed SBC change;
    - BAJA only from a recorded `date_of_leaving`.

    Generation is idempotent and never runs from a preview, Draft or uncommitted run.
  - **The worklist export** (D1 / D12):
    - a CSV whose first row says it is **not an IMSS / IDSE file**;
    - carries the NSS, built on request, never stored;
    - audited without the NSS;
    - refused whole if any NSS is missing.
  - Outcomes: FILED (reference required), ACCEPTED (four-eyes) and REJECTED (reason), plus re-issue after a rejection and withdrawal (reason, never exported).
  - The **Social Security Center summary** (§14 cards) and the **blocks** (X1–X7).
- **`mexico_run_service.py`**:
  - `run_downstream_actions` = CFDI + authorities;
  - `reset_run` calls `withdraw_on_reset` before deleting the ledgers;
  - `run_status["authorities"]` is the real lane.
- **Routes:**
  - 30 org routes under `/api/payroll/mexico/authorities/…`, behind the Phase 4a guard; reads need a payroll operator, writes an org admin;
  - Super Admin `GET /super-admin/compliance/mexico/authorities` (read-only).

**Frontend**

- **Compliance → "Mexico Social Security"** is a new tab, shown for MX organisations only. It holds `MXSocialSecurityCenter`:
  - the §14 cards and the "Not available yet" blocks;
  - movements (generate, export worklist, FILED / ACCEPTED / REJECTED, withdraw, re-issue);
  - liabilities (accrue, sources drill-down, file, pay, reconcile);
  - SUA reconciliation (open period, SUA figure grid, differences, explain, approve, reconcile, payment);
  - ISN returns (draft / refresh / amend, three-way reconciliation, file, outcome);
  - the UNKNOWN banner and actions on every object.
- When the API answers 403 (Mexico dormant), the tab shows only the refusal.
- **Super Admin:** an "Authorities" tab (read-only counts and the blocks).
- **Run badges:** tones for ACCRUED / PAID / RECONCILED, and the caption updated.

## 3. Migration `e3b9c2d7f4a1` — measured on PostgreSQL 17

| Measurement | Result |
|---|---|
| SHARE ROW EXCLUSIVE on `payslip_items` / `payroll_runs` / `payroll_employees`, from the first FK-creating statement to commit | **319–408 ms** over three runs (331.99, 318.67 and 407.63 ms). This is longer than Phase 7's 105–118 ms, because there are seven tables rather than three. |
| In flight | The migration holds AccessShare + ShareRowExclusive on the three tables. `payslip_items` stays **readable**, and a writer's `ROW EXCLUSIVE NOWAIT` is refused, so writes wait for up to about 0.4 s. |
| A writer holding `payslip_items` | The upgrade gives up after **5.28–5.30 s** with **nothing created**, so a re-run is safe. |
| Real CLI path | `alembic upgrade head` through `env.py`, `alembic current` = the repository head, and `check_schema_drift` clean. |

The FKs to `organizations`, `users`, `payroll_mx_imss_registrations` and `payroll_mx_isn_registrations` take the same lock mode in the same transaction, so they are held for at most the same window.

## 4. What this does in production when merged (plan §8)

`MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False.

| Change | Production effect |
|---|---|
| Migration `e3b9c2d7f4a1` | **Seven new, empty tables.** No column on any shared table. The head moves `d8b3e5f1a2c7` → `e3b9c2d7f4a1`. FK creation briefly takes SHARE ROW EXCLUSIVE on `payroll_runs` / `payslip_items` / `payroll_employees` (measured 0.32–0.41 s); reads continue and writes wait. If a long writer holds a table, the migration **fails after about 5.3 s with nothing created** and can be re-run. |
| Movement / liability / SUA / ISN services | **Unreachable.** All 30 org routes are behind the Phase 4a guard (403, verified in the browser with the flag off). No Mexican run can be committed in production, so no object can exist. |
| Due dates | No due-date content is Active or transcribed, so every date would be `DUE_DATE_UNSOURCED`. Nothing is defaulted. |
| Transmissions | None: file-export mode, no adapter, no outbound call. With no data there is no worklist to download. |
| `run_downstream_actions` | Also queries the new empty tables and returns `[]`, so **reset behaviour is unchanged**. |
| Evidence | Reference strings only (D9). No file is stored. |
| Secrets | Nothing is read. The NSS is read only when a worklist is requested; there is none. |
| Compliance page | Mexican organisations get one more tab, "Mexico Social Security", which shows the dormancy refusal. **No other country's tabs change** (NL verified with the flag on and off). |
| Super Admin | One new read-only "Authorities" tab: counts all "none", plus the blocks. |

**Net effect:** an additive schema change and two read-only or refusing screens. No behaviour change for any jurisdiction.

## 5. Browser evidence (`docs/mexico/phase8-evidence/`)

The harness lives in `harness/`:
- `setup_db.py` builds a synthetic scratch DB;
- `serve.py on|off` starts the backend;
- `patches.py` holds the Phase 6 synthetic content only (no due-date content patched);
- `acceptance.py` drives installed Chrome against `vite preview` of the current build.

The harness CORS origin is passed as a process environment variable; `backend/.env` was not touched. The flag-on run was launched from a detached script because session restarts kept killing the backend mid-run.

**Flag off (12/12):**
- NL shows no Mexico tabs.
- The Mexican organisation's Social Security tab shows only the dormancy refusal.
- 8 authority routes → 403.
- The Super Admin Authorities tab shows zero counts and the blocks.

**Flag on (16/16):**
1. The Center shows the registration card (VERIFIED), the counts, and the blocks (`MX_IDSE_SUA_SIPARE_LAYOUTS`, `DUE_DATE_UNSOURCED`, `MX_FILING_CALENDAR_EMPTY`, …).
2. Accrue produces SAT ISR, IMSS, INFONAVIT and ISN rows from the committed run; every due date reads **DUE DATE UNSOURCED**.
3. An ALTA is generated, with the NSS masked on screen. The worklist downloads labelled not-an-IDSE-file and carries the NSS; the movement becomes EXPORTED.
4. **UNKNOWN in the browser:**
   - "Outcome unknown" → banner, and the confirmed retry is disabled;
   - NOT FOUND → a reasoned retry → PENDING with **the same idempotency key and payload hash**;
   - re-exported, then FILED with the IDSE reference.
5. The ISR declaration is filed. The run badges show Authorities **IN PROGRESS** while Payroll (Approved), CFDI (NOT STARTED) and Bank (HELD) are unchanged.
6. **SUA:**
   - a one-cent difference is BLOCKING;
   - reconcile is refused (`MX_SUA_DIFFERENCES_OPEN`);
   - the explainer cannot approve their own explanation (`MX_FOUR_EYES_REQUIRED`);
   - the second admin approves and reconciles.
7. The ISN return reconciles (detail = return = ledger), is filed by the first admin and ACCEPTED by the second.
8. Reset → 409 `MX_RESET_DOWNSTREAM_ACTED`, naming the IMSS movement, the liabilities, the SUA period and the ISN return.
9. NL is unchanged.
10. The Super Admin tab counts FILED, RECONCILED and ACCEPTED objects.

## 6. Deviations and findings

1. **IMSS liabilities use the payslip's rounded per-branch amounts, not the Phase 6 branch-line ledger.** The browser pass showed IMSS summing to 2101.9151 from `payroll_mx_imss_branch_lines`, against 2101.90 on the payslip. The branch-line ledger stores the unrounded segment lines (4 dp, the trace); the engine emits per-branch / per-side amounts rounded once (`_by_branch`). The authority ledger therefore reads the committed snapshot's emitted branch amounts, so a liability equals what the payslips charged. The Phase 6 ledger is unchanged. Anyone summing it should know it is pre-rounding.
2. **INFONAVIT employer 5% comes from the committed snapshot.** Phase 6's `commit_run` writes no INFONAVIT branch line (the engine keeps INFONAVIT outside `res["imss"]`), so the 5% is read from `infonavit_employer` and the credit from `infonavit_credit`, the same way ISR is.
3. **"DUE" is a display state, not a stored status.** Liabilities are stored as ACCRUED / FILED / PAID / RECONCILED / UNKNOWN / WITHDRAWN. Overdue, due-soon and unsourced are computed from the sourced due date.
4. **Phase 6 and 7 PG CLI tests were pinned to "their" revision being current.** After a newer migration exists, `alembic current` shows the newer head, so the Phase 6 test would fail on PostgreSQL as soon as Phase 7 existed (inferred from the assertion; it was not run before the fix). CI skips it because it has no PG URL. Both now assert the repository head, with the revision in its history.
5. **Autoflush is off** in this codebase. Event reads and reset recomputation flush first. Without that, a NOT_FOUND recorded in the same transaction was invisible to the retry check (found by the tests).
6. **Four-eyes messages carry the engine's prefix** ("Mexico calculation blocked (MX_FOUR_EYES_REQUIRED): …"), because the refusals reuse `MXBlock`. The code is correct; the wording could be specialised later.
7. **SIPARE payments and the work-risk review have no tables** (plan X1 / X4 / X6). The SIPARE payment is recorded on the SUA period (capture line + reference).
8. **A withdrawn, never-sent liability / return / SUA period is re-used** (REACCRUED / REDRAFTED / REOPENED) when the reset run is re-committed. It does not become a "complementary" row.

## 7. Open / prerequisites

- **D1 integration mode**: built as file-export. Integration would be its own phase (X3).
- **X1 layouts** S12 / S13 / S16.
- **X2 due-date rules**: S24 / S10 / S27 / S22, plus S13 and S5, and the official holiday calendar.
- **X4 bank payment** (Phase 10).
- **X5 bimonthly periods.**
- **X6 work-risk review** (S10 / S14 / S29).
- **X7 Cloud Storage** in production (shared with Phase 7 D4 and the HK F-8 item).
- **Carried over:** Phase 7 D10–D12 (PAC, S28 / S30 / S4, Secret Manager), G1–G8, Q9 (NSS plaintext at rest — it now also feeds the worklist), and OOS-4.
