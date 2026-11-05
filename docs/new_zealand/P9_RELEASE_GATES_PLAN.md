# New Zealand P9: release gates, parallel cycles, privacy proof, key rotation

Spec: ZP-NZ-ENG-001 §13–§15 (AC-NZ-03, NZ-025, NZ-026).
Template: Japan P9 (`japan_readiness.py`, `japan_parallel.py`, `rotate_jp_my_number_keys.py`, `docs/japan/release-gates/`, `RUNBOOK_GO_LIVE.md`).
Base: `venu` at `fd190f3`. Single Alembic head `dd8a60634320`.

**This is a plan only. Nothing is built until Venu says "go ahead" for P9.**

---

## 0. Goal

P9 makes the decision to open New Zealand **re-derivable and evidence-backed**:
- `nz_unmet_requirements()` stops returning the fixed P4 stub. It returns the real unmet gates, so the service registry can move NZ to AVAILABLE only when every gate passes.
- Each gate passes only when two things hold:
  1. its **code checks** pass, re-derived from data on every request (nothing is ticked by hand);
  2. its **evidence artefact** `NZ-GATE-Gn` (a `SourceArtifact`) is reviewed by someone other than the uploader. The `_nz_evidence` helper for this already exists.
- Nothing in P9 turns NZ on:
  - `NZ_TENANT_ONBOARDING_ENABLED` stays off;
  - the registry move stays a separate Super Admin action;
  - no database is touched.

---

## 1. The seven gates (`backend/app/modules/payroll/nz_readiness.py`, new; mirrors `japan_readiness.py`)

`GATES = ((key, label, owner), …)`. The owners are taken from spec §15 at build time; the ones listed below are provisional. `SIGNOFFS = ("PRODUCT", "COMPLIANCE", "ENGINEERING", "COMMERCIAL")`.

| Gate | Label | Owner (provisional) | Code checks (all re-derived) |
|---|---|---|---|
| **G1** | Statutory content signed | Payroll / tax specialist | Canonical `NZ-PAYROLL-2026-27` pack seeded. No `[PENDING G1]` row left. Every G1 authority table (`NZ_EMPTY_TABLES`, `gate == "G1"`, not employer content) has rows. `NZ_IRD_EXAMPLE` rows present **and the golden check passes** (see §4). |
| **G2** | Holidays and leave content | Employment / leave specialist | `NZ_PUBLIC_HOLIDAY` national rows for every year of the pack window. An anniversary-day row for each of the 16 `NZ_REGIONS`. Every `nz_hol_*` parameter signed. |
| **G3** | Payday filing certified | Compliance (IRD gateway) | `NZ_EXPORT_SCHEMAS` not empty. Signed: `nz_working_day_rule`, the filing working-day counts, every remittance due-day row, `nz_filing_payload_version`. |
| **G4** | IRD number security and privacy | Security lead | `NZ_IRD_KEYRING` and `NZ_IRD_FINGERPRINT_KEY` configured (presence only — a key is never read into a result). Every ACTIVE vault row is under the newest key version (rotation done). |
| **G5** | Parallel cycles accepted | Payroll operations | At least 2 accepted cycles, in **distinct months**, for at least **2 distinct legal employers** (AC-NZ-03). |
| **G6** | Operations ready | Operations / support lead | Evidence only (`NZ-GATE-G6`, the reviewed runbook). Docs are not deployed, so the server cannot read them. |
| **G7** | Launch sign-off | CTO + commercial | `NZ-SIGNOFF-PRODUCT/COMPLIANCE/ENGINEERING/COMMERCIAL` recorded, and every launch-blocking owner decision recorded (D-7). |

### Functions
| Function | What it returns |
|---|---|
| `nz_code_checks(db)` | `{gate: [{key, ok, detail}]}` |
| `nz_readiness(db)` | `{jurisdiction, gates[{gate, label, owner, checks, evidence[{tag, state, artifactId}], passed, checklist}], decisions, allPassed}` |
| `nz_unmet_requirements(db)` | `[{key, label, detail}]` |

`new_zealand_service.nz_unmet_requirements` delegates to `nz_readiness`. The `_nz_service_registry_transition` hook is unchanged, so it now really gates AVAILABLE.

---

## 2. Parallel cycles (gate G5)

### Migration `<uuid12>_nz_parallel_cycles.py` (down_revision `dd8a60634320`)
It copies the `b8bd939fffca_jp_parallel_cycles.py` / `dd8a60634320` conventions:
- literal table names, `lock_timeout`, idempotent in both directions;
- RLS through the `d7f9b1c3e5a6` helpers;
- a manifest entry and head pins.

#### `payroll_nz_parallel_imports` (TENANT)
`_common` columns, plus:

| Column | Type / rule |
|---|---|
| `run_id` | FK `payroll_runs`, SET NULL |
| `pay_date` | Date |
| `cycle_month` | Date (first day of the payday's month) |
| `source_name` | String(100) — the incumbent system |
| `file_hash` | String(64) |
| `row_count` | Integer |
| `column_map` | JSON |
| `status` | `IMPORTED / ACCEPTED / WITHDRAWN` |
| `accepted_by_id`, `accepted_at` | |

- Checks: `row_count >= 0`, status enum.
- Unique `(organization_id, run_id, file_hash)` where status ≠ `WITHDRAWN`.

#### `payroll_nz_parallel_differences` (WORKER "org")
`_common(with_updated=False)` columns, plus:

| Column | Type / rule |
|---|---|
| `import_id` | FK, CASCADE |
| `employee_id` | FK `payroll_employees`, CASCADE |
| `payslip_item_id` | FK, SET NULL |
| `concept` | String(24) |
| `incumbent_amount`, `zoiko_amount`, `difference` | Numeric(14,2) |
| `explanation` | String(300) |
| `explained_by_id`, `accepted_by_id` | |
| `status` | `MATCHED / OPEN / EXPLAINED / ACCEPTED` |

- `concept` CHECK IN: `gross`, `paye_incl_acc`, `student_loan`, `ks_employee`, `ks_employer_gross`, `esct`, `child_support`, `net_pay`.
- Additional checks: `accepted_by_id <> explained_by_id`; ACCEPTED requires an explanation.

### `backend/app/modules/payroll/nz_parallel.py` (new; mirrors `japan_parallel.py`)
- **Import:** CSV of at most 2 MB and 5,000 rows, with a column map `{employee_code, <concept>…}`. It applies only to a **committed** (Paid / Closed) NZ run. Comparison is at **zero tolerance** against the frozen payslip, using `zoiko_amounts(item)` from the `nz_calculation_snapshot` obligations. Nothing is recomputed.
- **Identifier refusal (NZ-025):** the **whole file** is refused before any row is written if either of these holds:
  - a header names an identifier: `ird`, `tax number`, `bank`, `account`, `passport`, `driver`;
  - any cell is 8–9 digits that pass `nz_ird_number_valid`, or is shaped like an NZ bank account number (15–16 digits, with or without dashes).

  Only the employee code links a row to a payslip.
- **Workflow:**
  1. explain a difference (reason);
  2. accept the difference (a person other than the explainer);
  3. accept the cycle (a person other than the importer, once every difference is MATCHED or ACCEPTED);
  4. withdraw (reason).
- **G5 helper:** `nz_accepted_parallel_cycles(db)` returns `{(organization_id, legal_entity_id, cycle_month)}`. G5 needs at least 2 distinct months **and** at least 2 distinct employers.

### Routes (`nz_org_router.py`, 6 new; all dormant behind `require_nz_tenant`)
| Method | Path | Permission |
|---|---|---|
| GET | `/parallel-imports` | operator |
| POST | `/parallel-imports` | org admin |
| GET | `/parallel-imports/{id}` | operator |
| POST | `/parallel-differences/{id}/explain` | org admin |
| POST | `/parallel-differences/{id}/accept` | org admin, four-eyes |
| POST | `/parallel-imports/{id}/accept` | org admin, four-eyes |
| POST | `/parallel-imports/{id}/withdraw` | org admin; reason |

The existing `GET /readiness` changes from returning the stub to returning the full `nz_readiness()` view. The route registry is regenerated in a no-`.env` worktree (expected: about 1,460).

---

## 3. IRD-number key rotation (gate G4)
- **`new_zealand_service.rotate_nz_ird_keys(db, *, dry_run=True)`.** For every ACTIVE vault row not under the newest key version:
  - re-encrypt it with `nz_ird_number.reencrypt`, keeping the owner binding;
  - check that the fingerprint is unchanged (its key never rotates);
  - write a `ROTATED` access event.

  It returns counts and row ids only, never a number. Any decrypt failure is listed by row id, and the run stops without writing.
- **`backend/scripts/rotate_nz_ird_keys.py`.** Dry run by default; `--apply` writes. The local-database guard applies; `--confirm-remote` is only for the documented production rotation, run by the approved operator. **I never run it against any database.**

---

## 4. Golden check as a service (part of G1)
Today `tests/test_nz_golden.py` skips while `NZ_IRD_EXAMPLE` is empty.
- **New `backend/app/modules/payroll/nz_golden.py`.** `nz_golden_check(db, pack)` replays every `NZ_IRD_EXAMPLE` row through the pure engine with the pack's own rows, and returns `{examples, passed, failures[{example, field, expected, actual}]}`.
- **Who uses it:**
  - the G1 readiness check;
  - a Super Admin "Run golden check" action (read-only, `POST /api/super-admin/compliance/new-zealand/packs/{id}/golden-check`);
  - the test, rewritten to use it.

  Exact equality is required; there is no tolerance.
- **Example format:** `tax_formula` holds JSON `{inputs: {...}, expected: {paye, accLevy, studentLoan, ksEmployee, esct, netPay}}`. The console's add-table-row form already accepts `taxFormula`; P9 validates this JSON when the row is added.

---

## 5. Privacy proof (NZ-025) and isolation tests
- **`backend/tests/privacy/test_nz_ird_redaction.py`.** It creates an employee with a known valid IRD number, a bank reference and a child-support notice with narrative text, plus family-violence leave. It then exercises:
  - every NZ GET route;
  - payslip and run views;
  - the filing payload;
  - the remittance view;
  - the parallel summary;
  - retention export rows;
  - audit and activity logs (`caplog` plus the audit tables);
  - error messages from refused writes.

  It asserts that none of these contain:
  - the IRD digits (in any grouping);
  - the bank account;
  - the notice text;
  - family-violence details beyond "restricted".
- **Cross-tenant denial:** org B's admin gets 404 on every org-A NZ record id (employees, vault, notices, filings, remittances, settlements, exceptions, parallel imports).
- **Cross-legal-employer separation:** two legal entities in one org.
  - Their filings, remittance periods, ACC accumulator caps and parallel cycles never mix.
  - The journal refuses a run whose employers use different account maps (already in place; pinned here).
- **`backend/tests/test_nz_phase9.py`:**
  - every gate's checks on a seeded-and-signed pack (`sign_with_test_values`), and each check flipping;
  - evidence states OPEN / SUBMITTED / RECORDED, and a self-reviewed artefact refused;
  - the registry move to AVAILABLE refused until all gates pass, then allowed;
  - parallel import: zero tolerance, identifier refusal (header, IRD-valid cell, bank shape), four-eyes, distinct months / employers, withdrawal;
  - key rotation: dry run writes nothing; apply re-encrypts and keeps the fingerprint; a wrong key stops it with nothing written;
  - golden check: pass, mismatch report, malformed example refused.
- **`backend/tests/test_nz_parallel_migration.py`:** RLS classification, model equality, replay, downgrade, drift filter, manifest, and the CHECK constraints.

---

## 6. Documents
- **`docs/new_zealand/release-gates/README.md`** and **`G1.md` … `G7.md`.** Each has the owner, the evidence tag, the checks (the same words as `nz_readiness`), the evidence to record, and a sign-off table (Japan's format).
- **`docs/new_zealand/RUNBOOK_GO_LIVE.md`:**
  1. deploy;
  2. secrets (keyring, fingerprint key — never in `.env` in the repo);
  3. seeding (the Super Admin button, or the script with a dry run first);
  4. signing and the authority tables;
  5. parallel cycles;
  6. sign-off and switch-on (registry AVAILABLE, then the onboarding flag);
  7. **IRD outage and filing retry**;
  8. **payment recovery**;
  9. corrections;
  10. **breach runbook**, including the Privacy Commissioner notifiable-breach timing;
  11. **canary and rollback (NZ-026)** — rollback restores the prior signed pack and **never rewrites committed payroll**.

---

## 7. Frontend
| File | Content |
|---|---|
| `components/jurisdiction/new_zealand/NZReadinessTab.jsx` (new) | Super Admin view: the seven gates with checks, evidence states and owner decisions, plus a "Run golden check" button. Mounted as an extra tab in `newZealandComplianceConfig.jsx`. It reads `statutory_summary`, extended with `readiness`, as Japan does. |
| `modules/payroll/Compliances/NZParallelCyclesSection.jsx` (new) | Org screen: import a CSV (the file is read in the browser and sent as text with the column map); list imports; differences with explain / accept; accept or withdraw a cycle. Mounted in `NZComplianceCentreTab`. |
| `NZComplianceCentreTab.jsx` | The "Setup status" card shows the real readiness (gates passed x / 7). |
| `service/payrollService.js` | Client calls for the 6 new routes. |
| `service/superAdminService.js` | `runNzGoldenCheck`. |
| `scripts/nz-compliance-ui-validation.mjs` | New checks: the readiness tab is mounted; the parallel section never sends an identifier column; four-eyes actions exist; client calls cover every route. |

Checks before commit: build, `check:undefined`, `npm test`, and eslint on changed files (compared with HEAD for shared files).

---

## 8. Owner decisions in P9
- **D-7 (tax-record retention) — still open.** Proposal: a new content row `nz_tax_record_retention_years`, empty until signed (source: Tax Administration Act record-keeping). The retention hook reads it, so retention is no longer `PENDING_DECISION`. While it's empty, G7 stays unmet. *(Recommended — the value is signed, not coded.)*
- **Option 3 canary (saved reminder).** An allow-list `NZ_CANARY_ORG_IDS` (config, empty by default). `nz_dormancy.onboarding_enabled(org)` is true when the global flag is on **or** the org is listed. This lets one internal test organisation run NZ payroll in production on the Active pack while NZ stays PLANNED and dormant for everyone else. The runbook covers it.

---

## 9. Order (three local commits; push only on "push")
| Sub-phase | Contents |
|---|---|
| **P9a** | Migration and models, `nz_parallel.py`, `nz_readiness.py`, `nz_golden.py`, rotation service and script, the routes, D-7 content row (+ canary if chosen), registry; backend tests. |
| **P9b** | Privacy and isolation test suite (§5), and any redaction fixes it finds. |
| **P9c** | Frontend (§7), docs (§6), UI validation. |

Targeted tests per sub-phase. The full suite is for P10 (saved reminder), or as an interim run if wanted.

---

## 10. Decisions for Venu
| # | Decision | Recommendation |
|---|---|---|
| D-P9-1 | Gate set and checks as in §1 (owners confirmed against spec §15 at build) | As listed |
| D-P9-2 | G5 threshold: at least 2 accepted cycles, distinct months, at least 2 legal employers (AC-NZ-03) | As spec |
| D-P9-3 | D-7 retention as a signed content row (not a coded number) | Yes |
| D-P9-4 | Option 3 canary allow-list (`NZ_CANARY_ORG_IDS`, empty by default) | Yes |
| D-P9-5 | Golden check as a service + Super Admin action (G1 re-derived, not a test result) | Yes |
| D-P9-6 | Split into P9a / P9b / P9c, one local commit each | Yes |
