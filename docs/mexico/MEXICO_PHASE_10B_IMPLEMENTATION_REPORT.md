# Mexico (MX) — Phase 10b Implementation Report: Payroll journal

Spec ZP-MX-ENG-001 v1.0 §20 · plan `MEXICO_PHASE_10_PLAN.md` (approved 2026-10-21 as recommended; this is 10b, built under D1 and D6) · Phase 6 reset rule.

**Base.**
- `main` = `78bc913` (PR #117). Production is at `e7a2c4f9b1d6`.
- `nikhil` = `7124fc8` (Phase 10a, committed, not merged yet).

**Alembic.**
- Before: a single head, `a1d5e8c2f7b4` (215 revisions).
- Now: a single head, **`b3f7c1e9d5a2`** (216 revisions).

**Git.** Committed on `nikhil`, **not pushed**.

**What is real and what is not.**
- The journal needs no tax rule. It is built from the **committed** payslip snapshots, the same amounts the Phase 8 authority ledger trusts, so **the whole lifecycle works now**, once Mexico is opened.
- What it does not do is **post** anything. No ERP or ledger is integrated, so the journal is a CSV that the employer imports or keys into its own accounting system (D6).

## 1. Result

| Check | Result |
|---|---|
| Full backend suite | **7,073 passed**, 5 failed: all local-only or one pre-existing flaky test, none Mexico (§5). |
| Phase 10b tests | `test_mexico_journal.py` (10) and `test_mexico_journal_migrations.py` (6, of which 4 run on PostgreSQL). All pass. |
| Production upgrade path on PostgreSQL 17 | `test_privacy_mexico_merge_migration.py` 2/2, from `e1a3c5e7f9b2` with a live reader on `users` through to `b3f7c1e9d5a2`. |
| Migration on PostgreSQL 17 | 6/6, three runs. |
| Browser | **off 7/7**, **on 11/11** (no rules needed). No 5xx and no page errors. The only 4xx responses are the dormancy refusals (off) and the deliberate four-eyes refusal (on). Screenshots inspected. |
| ESLint / `check:undefined` / `vite build` | The new panel and the tab are clean. `payrollService.js` has the same 32 pre-existing problems as at `HEAD`, none in the new lines. 561 files have no undefined names. The build passes. |
| Route registry | Regenerated. The diff adds **only the 7 new routes**; no other route's class or principals changed. |

## 2. What was built

**Migration `b3f7c1e9d5a2` (mx_journal_m13).**
- **Two new tables:** `payroll_mx_journal_mappings` and `payroll_mx_journal_exports`. No shared column is added.
- **RLS on these tables only:** both as tenant tables. Neither holds a worker column, and the export is aggregated, so no worker appears in it.
- `ck_mx_journal_export_balanced`: an export row cannot record debits ≠ credits.

**`mexico_journal_service.py`.** Its helper names are distinctive (`_journal_mapping`, `_journal_run`, `_post_payslip`, …), following the 9e registry name-collision lesson.

**Line types.** There are 12, each with a natural side:

| Debit (cost) | Credit (owed) |
|---|---|
| `WAGES_EXPENSE`, by earning kind | `NET_PAY_PAYABLE` |
| `IMSS_EMPLOYER_EXPENSE`, by registration | `ISR_PAYABLE` (SAT) |
| `INFONAVIT_EMPLOYER_EXPENSE`, by registration | `IMSS_EMPLOYEE_PAYABLE` and `IMSS_EMPLOYER_PAYABLE`, by registration |
| `ISN_EXPENSE`, by state | `INFONAVIT_EMPLOYER_PAYABLE` and `INFONAVIT_CREDIT_PAYABLE`, by registration |
| | `ISN_PAYABLE`, by state |
| | `OTHER_DEDUCTIONS_PAYABLE` |

**Never netted (§20).**
- Every (line type, registration or state) pair is its own line, even when two of them map to the same account.
- The employee and employer sides of IMSS stay apart.

**Balance.**
- Gross = net + ISR + IMSS (employee) + INFONAVIT credit + other deductions.
- "Other" covers deductions Zoiko does not compute, and must be ≥ 0. If a payslip's net is more than gross less its deductions, the journal is refused with `MX_JOURNAL_UNBALANCED`. There is **never a plug line**.
- If a payslip's earning lines do not add up to its gross, it is refused the same way.

**Correction runs (Phase 9a).** The journal posts **corrected − original**. A negative delta moves to the other side.

**Mapping (D6).**
- The employer's own account codes, one per line type. `WAGES_EXPENSE:<KIND>` can override the wages account for one earning kind.
- Keys are validated (unknown line type or malformed code is refused). A blank entry is dropped.
- Versioned. One DRAFT at a time.
- **Approved by someone other than its maker** (`MX_FOUR_EYES_REQUIRED`). Approving a version supersedes the previous one. A DRAFT can be withdrawn.

**Export.**
- Refused without an approved mapping (`MX_JOURNAL_MAPPING_MISSING`), with any line unmapped (`MX_JOURNAL_ACCOUNT_UNMAPPED`, naming the line types) or when unbalanced.
- The CSV's first line is `ZOIKO PAYROLL JOURNAL - NOT POSTED TO ANY LEDGER - …`. Then come the run, mapping version and currency; one row per line (type, dimension, account, debit, credit); and a `TOTAL` row.
- Deterministic: the same run and mapping give the same hash.
- Recorded with the mapping version, totals and SHA-256; the file itself is not kept. Audited.
- Served with `Cache-Control: no-store`, UTF-8.

**Run reset (Phase 6 rule).**
- `run_downstream_actions` now includes the journal: **a CURRENT export refuses the reset** (409), because it may already be in the employer's ledger.
- It is voided **with a reason** once it is reversed or was never posted; after that it no longer blocks.
- A committed run is properly fixed with a correction run, which journals its deltas.

**Routes (7, behind the Phase 4a guard).**
- Mappings: list (with the line types), propose, approve, withdraw.
- Run journal: preview; export.
- Void an export.

**Frontend.**
- `MXJournalPanel` in the Mexico Compliance Centre: propose a mapping (prefilled from the approved one), approve or withdraw it, show a run's journal with its accounts, totals and balance, export the CSV, and void an export.
- No worker is shown or exported.

## 3. Migration `b3f7c1e9d5a2` — measured on PostgreSQL 17

| Measurement | Result |
|---|---|
| SHARE ROW EXCLUSIVE on `organizations` / `payroll_runs` / `users` | **58–99 ms** over three runs (99.08, 58.14 and 65.31 ms). `payroll_employees` and `payslip_items` are not touched. |
| In flight | Reads of `payroll_runs` continue; a writer's ROW EXCLUSIVE NOWAIT is refused; no ACCESS EXCLUSIVE on any existing table. |
| A writer holding `payroll_runs` | Gives up after **5.11–5.17 s** with nothing created. |
| RLS | ENABLE + FORCE plus `zoiko_rls` on both tables; `classify()` agrees (both tenant). |
| CLI path and drift | Clean. |

## 4. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration | Two new, empty tables with their RLS policies. About 0.1 s of SHARE ROW EXCLUSIVE; fails fast after about 5 s. |
| Routes | Refused while Mexico is dormant (verified, off 7/7). |
| Run reset | A new downstream check, which can only find an export, and none can exist. |
| Screens | Dormancy refusal only. |

**Net:** additive, and no behaviour change for any jurisdiction.

## 5. Full suite

Five sequential chunks on scratch SQLite, run 2026-10-22: **7,073 passed**, 104 skipped, 2 xfailed, **5 failed**. **None of the 5 failures is Mexico's, and none comes from 10b.**

| Chunk | Result |
|---|---|
| 0 | 852 passed, 15 skipped, 4 failed |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed |
| 2 | 1,281 passed, 31 skipped |
| 3 | 1,615 passed, 51 skipped |
| 4 | 1,042 passed, 6 skipped (includes the 16 Phase 10b tests) |

The 5 failures:
- **`tests/privacy/test_route_registry.py`, 3 tests:** every difference is the 4 uncommitted `/health/version` and `/health/ready` routes in the working-tree `main.py`. They are deliberately kept out of the registry, and CI does not have them. The regeneration without them adds only the 7 journal routes (§1).
- **`test_hong_kong_configuration.py::test_every_hk_configuration_row_is_governed_documented_sourced_consumed_and_exposed`:** checks against the uncommitted Hong Kong docs in the working tree. It also failed in the 10a run, and it is not Mexico.
- **`test_communications_dispatch.py::test_deactivate_organization_response_precedes_email_send`: flaky.** Rerun on its own five times, it failed once and passed four times. It is a timing race between the response start and the email background task under the ZP-PRIV middleware layers, in an organisation-status route that 10b does not touch. **It can fail CI too** (see §6).

## 6. Open / next

- **ERP posting:** none. If an employer wants a specific import layout (per ERP), it is a later content seam; until then, the generic CSV.
- **Employer-cost accruals** for aguinaldo, vacation premium and PTU over the year are not journalled. Only what a committed run charged is. They would be an accounting-policy choice of the employer.
- **Flaky CI test (not Mexico):** `test_deactivate_organization_response_precedes_email_send` fails about 1 run in 5. If CI fails on it, re-run the job. A robust fix (asserting that the e-mail is scheduled as a background task, not that it lands after the response start) is a small separate change.
- **Next:** 10c (privacy and retention; the redaction part with Rugvedh's review).
