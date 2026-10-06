# Singapore — Final Closure Report

Status date: 2026-09-29 · Branch `nikhil` over `264c585` (uncommitted) · Engine `SG-2026.10` · Alembic head `445abd6a9083` (153 revisions)

**Verdict.** There is no engineering, configuration, Super Admin, report-template, security, migration, test or documentation gap left in the repository. Singapore is **not live**: the service registry is `PLANNED` and no production gate has evidence.
What remains can't be done in code: external evidence (G1–G8), owner decisions (D1–D3), MOM data that hasn't been published, IRAS AIS-API credentials, and a controlled production deployment.

Companion documents:
- `SINGAPORE_FINAL_IMPLEMENTATION_STATUS.md`: the detailed record and the file-by-file hunk list;
- `SINGAPORE_PRODUCTION_ACTIVATION_RUNBOOK.md`: the steps;
- `SINGAPORE_EXTERNAL_EVIDENCE_HANDOFF.md`: what each owner must supply;
- `SINGAPORE_RELEASE_CHECKLIST.md`: sign-off.

---

## 1. Architecture

| Layer | Where |
|---|---|
| Calculation engine (pure, fail-closed) | `backend/app/modules/payroll/engine/countries/singapore.py`, covering CPF, SDL, SHG, FWL, LQS and PWM. A missing statutory value is `BLOCKED`, never guessed. |
| Jurisdiction package | `engine/jurisdictions/singapore/`: labour, preflight, EZPay layout (`statutory/ezpay.py`), the statutory summary (`statutory_summary.py`) |
| Statutory data | Database only: the `JurisdictionPack` + `ContributionRate` / `TaxSlab` rows, each linked to a `SourceArtifact` (authority, URL, retrieval time, SHA-256). PWM overtime schedules are in `sgp_pwm_overtime_schedules`. |
| Services and routes | `service.py` (the Singapore generators, lifecycles, governance and summary), `payroll/router.py` (tenant routes), `super_admin/router.py` (the platform control plane) |
| Super Admin UI | `frontend/src/components/jurisdiction/singapore/*`, rendering exactly what the backend summary returns. There are no statutory values in the frontend. |
| Seeds | `scripts/seed_singapore_canonical_pack.py` and `scripts/seed_statutory_report_templates.py` (local-DB guarded). Both are idempotent; the second run changes nothing, proven by row versions. |

## 2. Statutory configuration

- **Packs:** `SG-PAYROLL-2026 v1.2` and `SG-PAYROLL-2027 v1.0`, both **Draft**.
- **Contents:** 596 contribution rates, 336 slabs and 55 source artifacts. Every value has its source, effective dates, lifecycle and version.
- **PWM:** 6,132 rows / 84 schedules / overtime hours 0–72 / 6 source documents. Read-only, Super Admin only, filterable and paginated. Each query is 2 SQL statements taking at most 26 ms.
- **Unavailable official values are `EXTERNAL_DATA_REQUIRED` and fail closed** (section 9).

## 3. Super Admin control plane

Singapore Compliance shows:
- Overview, Statutory summary, Statutory components, PWM schedules, Report templates;
- Readiness & Operations: the 16-category dashboard, service availability, hotfix policy, AIS mode states, external dependencies, gates and decisions.

For every component it shows the configuration state, source, hash, retrieval date, effective dates, version and activation state, all read from the backend.

New in this pass:
- **Evidence review:** accept (with an optional validity date) or reject (with notes).
- **Decision recording:** option plus reason.
- **Each gate shows** its blocking reason, next action and acceptance criterion.
- **Dashboard status names:** PASS / BLOCKED / EXTERNAL_REQUIRED / BUSINESS_DECISION_REQUIRED.

## 4. Report templates

There are 11 templates, all seeded Draft:
- SG-PAYROLL-REGISTER, SG-PAYROLL-SUMMARY
- SG-CPF-CONTRIBUTION, SG-SHG-MONTHLY, SG-FWL-MONTHLY
- SG-PWM-COMPLIANCE, SG-IR21-REGISTER, SG-LQS-COMPLIANCE
- SG-IR8A, SG-SDL-MONTHLY, SG-CPF-EZPAY

**Lifecycle:** Draft → Review → Approved → Published → Active → Superseded. Superseded is final.

**Controls:**
- an edit after approval clears the approval;
- a released approval can't be replaced;
- self-approval is refused;
- every refusal is audited;
- re-seeding never demotes or rewrites a released template.

## 5. Generators

There are 12 generation paths: the generic template path for the 5 payroll/contribution reports, plus the dedicated IR8A, IR8A modification, SDL, PWM, LQS, IR21 register and EZPay generators. Each one:
- takes the organisation from the logged-in user, never from the client (checked across all 31 SG routes);
- requires an Active template;
- pins the template version and the payslips' own pack;
- over several pack versions, pins no single version and lists every pack in `taxPacksUsed`, sorted (fixed this programme, and now tested for every report type);
- masks NRIC/FIN;
- keeps history when regenerating (the previous report becomes Superseded, and this is audited).

Download rules:
- **EZPay:** the file downloads only from APPROVED onwards, is rebuilt and hash-checked, and every download is audited.
- **IR8A:** maker-checker applies to the manual submission, and revisions and amendments are tracked.
- **Templates:** all SG templates are AGGREGATE, so the generic certificate-PDF routes refuse them.

## 6. Security and tenant isolation

- Every Singapore governance route resolves `get_current_super_admin`, which refuses org admins, payroll admins and an org-bound super admin. This is swept by a test across 20+ routes.
- Tenant B can't read tenant A's reports or IR8A (PostgreSQL end-to-end run).
- Hotfix controls:
  - the initiator can't review their own hotfix, and a review is final;
  - activation and the hotfix record are written atomically;
  - a refusal is audited and leaves no phantom approval;
  - all three policies (RESTRICTED / PROHIBITED / FOLLOW_UP_REQUIRED) are tested.
- The in-tree secret scan is clean.

## 7. Database and migration

- There is one head, `445abd6a9083`. The four migrations carried from `main` are byte-identical.
- The shared database (read-only inspection) is at `998877665544`, with 146 tables and no SG rows.
- Rehearsed on a restored copy of that schema:
  - 7 additive migrations, 0 columns removed, no drift;
  - a second run does nothing;
  - the empty leftover table `sgp_ir21_cases` is kept.
- Data was deliberately **not** copied: the rehearsal restores the schema only, so production personal data never reaches a scratch database.
- `alembic stamp` is used nowhere.

## 8. Deployment

`scripts/deploy_migrate.sh`, rehearsed against the version on `main`:
- an unknown revision with drift is refused with **zero** schema changes (the original script added 11 columns in that case);
- an unknown revision with a matching schema is handled;
- a normal upgrade reaches head;
- a re-run is a no-op;
- it never stamps.

## 9. Evidence, decisions and external dependencies

- **Gates G1–G8:**
  - lifecycle `EVIDENCE_REQUIRED → SUBMITTED → UNDER_REVIEW → PASS | REJECTED | EXPIRED`;
  - server SHA-256, maker-checker review, supersession that keeps the old record, audit.
  - **Today:** every gate is `EVIDENCE_REQUIRED`, except G3 (`BUSINESS_DECISION_REQUIRED`).
- **Decisions D1–D3:**
  - each records the option, decision maker, reason, reviewer and review status;
  - a decision counts only after the memo is uploaded and a second Super Admin accepts it;
  - recording one never changes behaviour; a difference from the value in force is flagged.
  - **Today:** all `BUSINESS_DECISION_REQUIRED`. What runs today is EXPORT_ONLY / RESTRICTED / SG_ONLY.
- **AIS:**
  - export mode is complete (extract, validation, masking, maker-checker, revision / amendment, rejected / unknown outcomes, audit);
  - AIS-API 2.0 is `EXTERNAL_INTEGRATION_REQUIRED`. The Readiness page lists its six prerequisites, each with owner and status:
    - D1 decision;
    - APEX onboarding;
    - the API specification;
    - credentials in a secrets store;
    - employer Corppass authorisations;
    - a sandbox pass.
  - No credential is configured and no submission path exists, so nothing can be sent. An organisation selecting `DIRECT_API` is BLOCKED in its own readiness.
- **MOM data:**

| Item | Status |
|---|---|
| Levy end-day rule on pass cancellation | Available |
| Pre-July part-time LQS rate | Available |
| Levy end-day rule on pass expiry | EXTERNAL_DATA_REQUIRED, calculation blocked |
| Work Permit levy before 24 Sep 2026 | EXTERNAL_DATA_REQUIRED, calculation blocked |
| Foreign-worker quota tables | EXTERNAL_DATA_REQUIRED, plus a scope decision |
| Retail PWM 3-month averaging | **Implemented** (MOM Annex D), from each month's own payslip classification; months the source doesn't cover stay flagged |

## 10. Tests (2026-09-29)

| Suite | Pass | Fail | Skip |
|---|---|---|---|
| Singapore group (all SG files + golden + deploy + alembic metadata) | 823 | 0 | 2 (see note) |
| Real-organization validation (3 tenants, 4 cycles, 11 reports, HTTP isolation) | 44 | 0 | 0 |
| Real-browser UI check (Super Admin → Compliance → Singapore, all tabs, 11 templates + lifecycle) | 20 | 0 | 0 |
| Full backend `pytest tests/` | 3,308 | 0 | 7 |
| PostgreSQL end-to-end product scenario | 42 | 0 | 0 |
| PostgreSQL activation rehearsal | 172 | 0 | 0 (1 INFO) |
| Frontend: ESLint (Singapore files) / `vite build` | exit 0 / exit 0 (2,704 modules) | — | — |

Note on the 2 SG skips:
- one is the PostgreSQL-only Phase 6.0 check, which was run separately against a disposable database and passed (15/15 in its file);
- the other is the intentionally empty "sample" golden slot.

## 11. Remaining blockers (none can be closed in code)

| Blocker | Type | Owner | Required |
|---|---|---|---|
| G1 CPF certification | Evidence | Statutory compliance owner | Signed independent comparison report |
| G2 CPF operations | Evidence | Employer payroll operations | CPF acknowledgement plus reconciliation |
| G3 IRAS AIS | Decision, then evidence | Product owner | D1, then an IRAS-acknowledged original plus amendment |
| G4 IR21 | Evidence | Statutory compliance owner | Guidance review plus an acknowledged filing |
| G5 Foreign workforce | Evidence and data | Statutory compliance owner | Levy-bill reconciliation plus the MOM values in section 9 |
| G6 Employment Act | Evidence | Legal and compliance | Counsel memo |
| G7 PDPA / security | Evidence | DPO and security | DPO sign-off, security review, restore test |
| G8 Parallel run | Evidence | Implementation lead | Two-cycle design-partner reconciliation |
| D1–D3 | Business decision | Product / business owner | A decision recorded in the product, plus a signed memo |
| AIS-API 2.0 | External integration | Product owner / IRAS | APEX onboarding, Corppass, credentials, sandbox |
| Production deployment | Deployment | Deploy owner | Merge, then runbook sections A–O |

## 12. Activation procedure

Follow `SINGAPORE_PRODUCTION_ACTIVATION_RUNBOOK.md`, sections A–O:
1. **Before:** pre-checks, backup, restore rehearsal.
2. **Migrate:** `upgrade head`.
3. **Seed twice.** The second run must show `rowChanges` 0 / 0.
4. **Golden vectors:** all 37 must pass.
5. **Pack:** approve by a second Super Admin, then activate by a different admin (only after G1).
6. **Templates:** promote all 11 under maker-checker.
7. **Test tenant** and audit check.
8. **Registry:** switch to `AVAILABLE` **last**, only when G1–G8 pass and D1–D3 are recorded.
9. **After:** monitor two cycles, with the rollback plan (section N) ready.
