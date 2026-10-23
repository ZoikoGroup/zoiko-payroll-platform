# Mexico (MX) — Phase 10e Implementation Report: Two-level activation

Plan `MEXICO_PHASE_10E_PLAN.md`, approved 2026-10-22 with D1–D6 (D2 adjusted, D5 extended) · spec §22.

**Base.** `main` = `11dccf3` (PR #121, docs), deployed; production is at `b3f7c1e9d5a2`. `nikhil` = `6dc960e`, the same content as `main`.

**Alembic.**
- Before: a single head, `b3f7c1e9d5a2` (217 revisions).
- Now: a single head, **`d2a7c9e4f1b8`** (218 revisions).

**Git.** **Staged on `nikhil`, not committed**, as instructed.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite | **7,146 passed**, 5 failed: all local-only or the known flaky test, none Mexico (§6). |
| Phase 10e tests | `test_mexico_pilot.py` (11) and `test_mexico_pilot_migrations.py` (6, of which 4 run on PostgreSQL). All pass. Every Mexico test passes under the new gate. |
| Migration on PostgreSQL 17 | 6/6, three runs. |
| Production upgrade path on PostgreSQL 17 | `test_privacy_mexico_merge_migration.py` 2/2: from `e1a3c5e7f9b2` with a live reader on `users`, through `f84626be0cb1` and `b3f7c1e9d5a2`, to `d2a7c9e4f1b8`. |
| Browser | **on 11/11** (§5). |
| ESLint / `check:undefined` / `vite build` | The new and changed files are clean; `payrollService.js` keeps its 32 pre-existing problems (none in the new lines); 563 files have no undefined names; the build passes. |
| Route registry | Regenerated. It adds **only the 10 new routes**; no other route's class or principals changed. Two of them are **retired** (§4). |

## 2. What was built

### Level 1 — general availability; the flag is a kill switch (D1)

`mexico_dormancy.onboarding_enabled(db, org_id)`:
- **The flag must be on**, but it is never sufficient on its own.
- Every other organisation is open only when the registry is **AVAILABLE**.
- A **pilot organisation** (one that ever had an approved grant) is open only while its grant is active. **It never becomes live** (D5).
- No session means closed.

Every caller now passes the session and the organisation:
- the Mexico organisation API guard;
- the run, CFDI and filing guards;
- the country-change gate, through `get_jurisdiction_change_block_reason(…, organization_id)`, for both `PUT /organizations/me` and the Super Admin update;
- the company-jurisdiction update;
- the back-fill.

**One exception:** the employee-validation strategy lookup has no session and keeps the kill switch only. It cannot open Mexico, because a Mexican employee only matters in a Mexican organisation, and that is gated.

**Registry → AVAILABLE** is refused unless **G1–G8 are SIGNED, Q9 is RECORDED and `MX_IDENTITY_TOKEN_KEY` is configured**. Q9 is a fourth owner decision (`MX-DECISION-Q9`). The key's presence is checked; its value is never read out.

### Level 2 — the pilot (D2, D3)

`payroll_mx_pilot_grants` and `mexico_pilot_service`:

| Step | Rule |
|---|---|
| Propose (Super Admin) | An **EVALUATION** organisation only; a reason; an expiry in the future and **at most 120 days** away; one proposal at a time. |
| Approve | **A different Super Admin.** Every D2 precondition is met: the kill switch on; **G1, G2, G4, G5 and G7 SIGNED**; **Q9 and the hosting decision RECORDED**; the identity key configured. Each unmet one is named. |
| Withdraw / revoke | Withdraw a proposal; **revoke** an approved grant with a reason, effective on the next request. |
| Expiry | A grant past its expiry closes the organisation, with no job needed. |

Everything is audited.

**The pilot organisation's output is non-binding**, with named refusals:

| Area | Rule | Where |
|---|---|---|
| Payments | Every payment write is refused (`MX_PILOT_NO_PAYMENTS`). | `mexico_payment_service` |
| Filings | IDSE worklist export, movement outcomes, liability filed or paid, ISN return filed or its outcome, SUA payment: all refused (`MX_PILOT_NO_FILINGS`). Accrual and SUA reconciliation stay open. | `mexico_imss_service`, `mexico_filing_service` |
| CFDI | Generation and the outbox refuse a non-SANDBOX PAC environment (`MX_PILOT_SANDBOX_ONLY`); the GENERATED event records `pilot`. | `mexico_cfdi_service` |
| Payslips | The commit records `pilot` on the run's approval fingerprint, and its payslip PDF carries **"PILOT — PARALLEL RUN — NOT A PAYSLIP"**. It is read from the run, so converting the workspace never removes it. The shared watermark function only gained an optional text parameter; its default is unchanged. | `mexico_run_service`, `service.generate_payslip_pdf_bytes` |
| Journal | The CSV banner reads "PILOT - NOT FOR POSTING" (D6). | `mexico_journal_service` |

### The governed master-data copy (D5)

`payroll_mx_master_copies` and `mexico_pilot_service.propose_copy` / `approve_copy`.

**What is copied** from the pilot into a **new live** organisation:
- the open employer profiles;
- IMSS and ISN registrations;
- active establishments;
- open labour policies;
- the Mexican employees and their open statutory profiles.

References between these are **remapped** to the copies. The environment-bound **stamp test is reset**, and organisation-scoped legal-entity and pay-group links are cleared.

**What is never copied**, and is listed in the plan: payroll results, risk-premium approvals, credential references, INFONAVIT notices with their evidence, and collective agreements (the copy refuses those).

**Preconditions:**
- the source is a pilot organisation;
- the target is a live (non-EVALUATION), Mexican organisation with no Mexican data yet;
- general availability is open.

**The flow:**
1. A Super Admin proposes; the source's content hash is kept.
2. **A different Super Admin approves.** The source must be **unchanged since the proposal** (`MX_COPY_SOURCE_CHANGED`).
3. The copy runs in **one transaction**.
4. A **diff report** compares every copied row with its source, column by column. Tested: no differences.

## 3. Documents

- **Release-gate checklists:** every checklist now states when its evidence is produced, and tags each item:

  | Tag | Meaning |
  |---|---|
  | **PRE-PILOT** | Produced before any real Mexican data: from sources, synthetic cases or a test environment. |
  | **PILOT-GENERATED** | Produced by the non-binding pilot. |
  | **GO-LIVE CHECK** | A real filing or payment, possible only after general availability. |

- **G3 moved to during the pilot:** its credit reconciliation needs INFONAVIT's own figures for real workers. D2 therefore reads **G1, G2, G4, G5, G7**.
- **Real filings are GO-LIVE CHECKs:** the IDSE filing (G2), the INFONAVIT payment (G3), the ISN return (G4) and the first real declarations and payments (G6). Without that change, G2 and G4 could never be signed: the pilot never files, and general availability needs them signed first.
- **Register, runbook, checklist and plan:**
  - The register shows when each gate's evidence is produced.
  - The runbook has the two-level switch-on (§4) and **§6 Go-live checks**.
  - The release checklist and the plan record the approved decisions.
- **Incident note, open question 5:** the guard trusts a loopback host, and an SSH tunnel makes production look like `127.0.0.1`. **Proposal, not built:** a database-side environment marker that `env.py` reads before any write.

## 4. Open decision — the copy's routes stay retired (ZP-PRIV)

The copy reads and writes **worker rows in two tenants**, so the generator classes its two routes as `worker`. ZP-PRIV then decides:
- `route_overrides.py` enforces **"no worker route may list super_admin"**;
- **decision 3** says statutory actions on worker data are **tenant-run**;
- the policy check denies a Super Admin on worker data, and the data layer refuses a platform request that touches worker tables.

The approved D5 says "four-eyes", not whose. Rather than bypass ZP-PRIV, `POST /master-copies` and `POST /master-copies/{id}/approve` are **retired** (`R_TENANT`), with a note naming the open decision — the same way Rugvedh retired Mexico's Super Admin employee routes. The copy itself is fully built and tested at the service level, and its plan and report carry no worker values (tested).

**Decision needed (you, with Rugvedh):**

| Option | What | Trade-off |
|---|---|---|
| **A** | A reviewed `tenant_lifecycle` override for the two routes. The precedent is the Super Admin organisation hard delete. Super Admins run the copy, four-eyes. | Small. It widens a platform role onto worker tables for one reviewed operation. |
| **B** | A **tenant-run handshake**. The pilot organisation's admin releases its master data to a named live organisation, and the live organisation's admins propose and approve the import (four-eyes in the tenant). | Matches decision 3; more to build (a release record and two tenant routes). |

**Recommendation: B**, because ZP-PRIV's rule is that platform roles never handle worker data. The service already does the copy, so B adds only the release and the tenant routes.

## 5. Browser

**on 11/11.** Run with installed Chrome against the current build and a scratch backend, with **the flag on and no registry row**. The actors were SYNTHETIC: two Super Admins, two org admins and an NL admin. Screenshots inspected (`phase10e-evidence/`).

| Check | Result |
|---|---|
| on-1 The kill switch alone opens nothing: flag on, no registry, no grant, so the organisation sees the dormancy refusal | PASS |
| on-2 Readiness shows level DORMANT and all 9 pilot preconditions met: kill switch; G1, G2, G4, G5, G7; Q9; hosting; key (`01_pilot_preconditions.png`) | PASS |
| on-3 A grant proposed on screen; its proposer's approval is refused (`MX_FOUR_EYES_REQUIRED`) | PASS |
| on-4 A second Super Admin approves: grant ACTIVE, level **PILOT (1 organisation)** (`02_pilot_active.png`) | PASS |
| on-5 The pilot organisation opens, with the non-binding banner (`03_pilot_banner.png`) | PASS |
| on-6 Building a salary payment batch is refused on screen, `MX_PILOT_NO_PAYMENTS` (`04_no_payments.png`) | PASS |
| on-7 An IDSE worklist export is refused, `MX_PILOT_NO_FILINGS` | PASS |
| on-8 A run committed during the pilot is recorded `pilot: true`; its payslip PDF (`05_pilot_payslip.pdf`) contains **"PILOT — PARALLEL RUN — NOT A PAYSLIP"** | PASS |
| on-9 Revoking with a reason closes the organisation at once; the level returns to DORMANT (`06_revoked.png`) | PASS |
| on-z1 The NL compliance page is unchanged | PASS |
| on-z2 No 5xx and no page errors | PASS |

**Notes.**
- **Expected 4xx responses:** the 403s are the deliberate dormancy refusals, before the grant and after the revocation. The two 400s are the payment and four-eyes refusals.
- **How the watermark is checked:** the PDF embeds a TrueType font, so its text is checked with pypdf, not a byte search.
- **The first two attempts were not app failures:**
  - Attempt 1 failed on-8 because of that byte search.
  - Attempt 2 hit a `MemoryError`, because I ran it alongside the full suite.
  - Run alone, it passed 11/11.
- **Cosmetic:** the shared Mexico error handler prefixes every refusal with "Mexico calculation blocked", including `MX_PILOT_NO_PAYMENTS`. This is an existing pattern, unchanged here.

## 6. Full suite

Five sequential chunks on scratch SQLite: **7,146 passed**, 108 skipped, 2 xfailed, **5 failed**. **None of the 5 is Mexico's, and none comes from 10e.**

| Chunk | Result |
|---|---|
| 0 | 852 passed, 15 skipped, 4 failed |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed |
| 2 | 1,335 passed, 35 skipped (includes the 10e tests) |
| 3 | 1,622 passed, 51 skipped |
| 4 | 1,054 passed, 6 skipped |

The 5 failures:
- **`tests/privacy/test_route_registry.py`, 3 tests:** caused only by the 4 uncommitted `/health/version` and `/health/ready` routes in the working-tree `main.py` (verified in the failure text); CI does not have them.
- **`test_hong_kong_configuration.py::…documented_sourced_consumed_and_exposed`:** it checks the uncommitted Hong Kong docs. Not Mexico.
- **`test_communications_dispatch.py::test_deactivate_organization_response_precedes_email_send`:** the known flaky timing test (10b report).

Chunks 0 and 2 were rerun on their own after the parallel browser run exhausted memory. Their first attempts crashed or stopped without a summary; those were not test failures.

## 7. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration `d2a7c9e4f1b8` | Two new, empty tables (`payroll_mx_pilot_grants`, `payroll_mx_master_copies`) with their RLS policies. About 0.07 s of SHARE ROW EXCLUSIVE on `organizations` and `users` only; fails fast after about 5 s. |
| The gate | Production has the flag **off**, so nothing opens, exactly as today. Turning the flag on now opens **nothing** by itself. |
| Registry → AVAILABLE | Stricter: now also requires Q9 RECORDED and the identity key. |
| Pilot rules | Apply only to an organisation with an approved grant; none exists. |
| Payslip renderer | The shared watermark function gained an optional text parameter, with its default unchanged. Only a run recorded as pilot draws the pilot watermark, and none exists. **No other country's PDF changes.** |
| Country-change gate | Now passes the organisation id. For a non-Mexican change it returns exactly as before (the dormancy test proves this for every pair of registered countries). |
| Routes | 10 new: 7 Super Admin (pilot grants ×5, master-copies list and cancel) and 1 organisation (`/pilot-status`), plus 2 retired (the copy's propose and approve). All are refused while dormant or for non-Super Admins. |

**Net:** additive and stricter, Mexico stays dormant, and no other jurisdiction's behaviour changes.
