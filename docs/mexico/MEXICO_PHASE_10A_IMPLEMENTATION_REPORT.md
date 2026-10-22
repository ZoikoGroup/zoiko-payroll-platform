# Mexico (MX) — Phase 10a Implementation Report: Salary payments

Spec ZP-MX-ENG-001 v1.0 §20, MX-061 / MX-062 · plan `MEXICO_PHASE_10_PLAN.md` (approved 2026-10-21 as recommended, D1–D10; this is 10a, built under D2–D5) · Phase 6 reset rule.

**Base.** `main` = `78bc913` (PR #117). Its deploy `39584366118` was green; production is at `e7a2c4f9b1d6`. `nikhil` = `d63542c` (the Phase 10 plan).

**Alembic.**
- Before: a single head, `e7a2c4f9b1d6` (214 revisions).
- Now: a single head, **`a1d5e8c2f7b4`** (215 revisions).

**Git.** Committed on `nikhil`, **not pushed**.

**What is real and what is not.**
- Payments need no tax rule, so the **whole lifecycle works now**, once Mexico is opened.
- What does not exist is a **bank file**: no bank's SPEI layout is saved, so the file is a Zoiko **worklist** that an operator keys into online banking (D2), as the Phase 8 IMSS worklist is.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite | **7,055 passed**, 4 failed, all local-only and not Mexico (§5). |
| Phase 10a tests | `test_mexico_payments.py` (8) and `test_mexico_payments_migrations.py` (6, of which 4 run on PostgreSQL). All pass. |
| Production upgrade path on PostgreSQL 17 | `test_privacy_mexico_merge_migration.py` 2/2, from `e1a3c5e7f9b2` with a live reader on `users` through to `a1d5e8c2f7b4`. |
| Migration on PostgreSQL 17 | 6/6, three runs. |
| Browser | **off 7/7**, **on 9/9** (no rules needed). No 5xx and no page errors; the only 4xx is the deliberate four-eyes refusal. Screenshots inspected. |
| ESLint / `check:undefined` / `vite build` | 0 errors in new or changed files; 560 files clean; the build passes. |
| Route registry | Regenerated. The diff adds **only the 8 new routes**; no other route's class or principals changed (checked after the 9e name-collision lesson). |

## 2. What was built

**Migration `a1d5e8c2f7b4` (mx_payments_m12).**
- **Two new tables:** `payroll_mx_payment_batches` and `payroll_mx_payment_items`. No shared column.
- **RLS on these tables only:** batches as a tenant table, items as a worker table ("org").
- **The full CLABE is never stored**, only its last 4 digits.

**`mexico_payment_service.py`.** Helpers have distinctive names (`_payment_batch`, `_payment_item`, …), so the ZP-PRIV call graph cannot link unrelated routes to these tables.
- **Batch:**
  - one per committed run, one item per payslip with net pay > 0;
  - **any worker without an 18-digit CLABE refuses the whole batch** (`MX_CLABE_MISSING`, employee ids only, never a CLABE). The CLABE check digit is S33, not saved; the existing validation says so;
  - a second batch for the same run is refused.
- **Release:** by someone other than the maker (`MX_FOUR_EYES_REQUIRED`). Only a DRAFT batch can be cancelled.
- **Worklist (D2):**
  - built for a RELEASED / CLOSED batch, on request;
  - first line: `ZOIKO PAYMENT WORKLIST - NOT A BANK FILE - …`, then one row per payment with a `ZP-{batch}-{item}` reference and the **full CLABE, read only now**;
  - the export is audited (hash and count, never the CLABE) and served with `Cache-Control: no-store`, UTF-8;
  - if a worker's CLABE changed since the batch was built: `MX_CLABE_CHANGED` (cancel and rebuild, or re-issue).
- **Outcomes (D4):**
  - SETTLED / FAILED / RETURNED, each with the bank reference; FAILED / RETURNED also with the reason;
  - **UNKNOWN**: never retried automatically, resolved later to a final outcome;
  - the batch is **CLOSED** when no item is PENDING or UNKNOWN.
- **Re-issue (D5):**
  - FAILED / RETURNED items go into a new DRAFT batch, each linked both ways, using the worker's **current** CLABE (often the reason for the return);
  - cancelling that batch frees the originals;
  - the payslip is never edited.
- **Run reset (Phase 6 rule):**
  - `run_downstream_actions` now includes the payment reasons: a **RELEASED or CLOSED batch refuses the reset** (409);
  - a DRAFT batch is cancelled by the reset.

**Routes (8, behind the Phase 4a guard).**
- Batches: list (optionally for one run), build for a run, detail.
- Release; cancel.
- Worklist download.
- Record an item's outcome.
- Re-issue.

**Frontend.**
- `MXPaymentsPanel` in the Mexico Compliance Centre: build, release, download the worklist, record outcomes with the SPEI reference, re-issue.
- Only the CLABE's last 4 digits are ever shown.

**Also fixed.** The Phase 8 IMSS worklist response is now served as UTF-8 (`text/csv; charset=utf-8`). Without it, accented Mexican names (e.g. "Sintética") were garbled in the download, which was the same bug the payment worklist had. Phase 8 tests: 40 passed.

## 3. Migration `a1d5e8c2f7b4` — measured on PostgreSQL 17

| Measurement | Result |
|---|---|
| SHARE ROW EXCLUSIVE on `payroll_runs` / `payroll_employees` / `payslip_items` / `users` / `organizations` | **80–90 ms** over three runs (86.87, 89.68 and 80.37 ms). |
| A writer holding `payroll_runs` | Gives up after **5.09–5.22 s** with nothing created. |
| RLS | ENABLE + FORCE plus `zoiko_rls` on both tables; `classify()` agrees (batches tenant, items worker "org"). |
| CLI path and drift | Clean. |

## 4. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration | Two new, empty tables with their RLS policies. About 0.1 s of SHARE ROW EXCLUSIVE; fails fast after about 5 s. |
| Routes | Refused while Mexico is dormant (verified, off 7/7). |
| Run reset | A new downstream check, which can only find a batch, and none can exist. |
| IMSS worklist charset | UTF-8 (dormant route). |
| Screens | Dormancy refusal only. |

**Net:** additive, and no behaviour change for any jurisdiction.

## 5. Full suite

Five sequential chunks on scratch SQLite, run 2026-10-21/22: **7,055 passed**, 100 skipped, 2 xfailed, **4 failed**. **None of the 4 failures is Mexico's, and none comes from 10a.**

| Chunk | Result |
|---|---|
| 0 | 853 passed, 15 skipped, 3 failed |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed |
| 2 | 1,274 passed, 31 skipped |
| 3 | 1,615 passed, 51 skipped |
| 4 | 1,030 passed, 2 skipped |

The 4 failures are local only:
- **`tests/privacy/test_route_registry.py`, 3 tests:** every difference is the 4 uncommitted `/health/version` and `/health/ready` routes in the working-tree `main.py`. They are not part of this change and are deliberately kept out of the registry. CI does not have them.
- **`test_hong_kong_configuration.py::test_every_hk_configuration_row_is_governed_documented_sourced_consumed_and_exposed`:** it reports "undocumented" HK rows against the uncommitted Hong Kong docs in the working tree. It failed in the previous run too, and it is not Mexico.

## 6. Open / next

- **Bank file:** the SPEI bulk-file layout of the employer's bank (per bank, a content seam). Until then, worklist only.
- **The CLABE check digit:** source S33.
- **Settlement confirmation:** Banxico CEP. No integration.
- **Next:** 10b (payroll journal).
