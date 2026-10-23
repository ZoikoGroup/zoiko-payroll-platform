# Mexico (MX) — Phase 10e Plan: Two-level activation (general availability and a non-binding pilot)

Spec ZP-MX-ENG-001 v1.0 §22 · requested in the PR #119 review (2026-10-22) · `mexico_dormancy.py` docstring ("Phase 10 replaces the flag with the service-registry AVAILABLE state").

**Base.** `main` = `2473ed6` (PR #119), deployed; production is at `b3f7c1e9d5a2`. `nikhil` is that plus the doc commits from the review.

**Status.** **Approved 2026-10-22** with the changes in §9 (D2 adjusted; D5 extended). Built: see `MEXICO_PHASE_10E_IMPLEMENTATION_REPORT.md`.

## 1. The problem

Today **one environment variable**, `MX_TENANT_ONBOARDING_ENABLED`, opens Mexico for every organisation (`mexico_dormancy.onboarding_enabled()`). The gates G1–G8, the registry and Q9 are not consulted. A premature or mistaken deployment change would open Mexico.

Requiring all eight gates before anything runs would **deadlock G8**, though: G8 *is* two parallel payroll cycles, which need Mexico to run.

## 2. The design — two levels

| Level | Who | Opens when | Output |
|---|---|---|---|
| **General availability** | Every Mexican organisation | The registry is **AVAILABLE**. The platform refuses that transition unless **G1–G8 are SIGNED**, **Q9 is RECORDED** and **`MX_IDENTITY_TOKEN_KEY` is configured**, all re-checked in code. | Binding |
| **Pilot** | **Named organisations only**, each with an approved, unexpired, unrevoked pilot grant | A grant approved by a second Super Admin, while the registry is still PLANNED | **Non-binding** (§4) |

**The env flag alone never opens Mexico.** It becomes a deployment **kill switch**:

> `onboarding_enabled(org)` = flag on **AND** (registry AVAILABLE **OR** the org has an active pilot grant).

With the flag off, nothing is open, even with the registry AVAILABLE. With the flag on and nothing else, nothing is open either.

## 3. General availability (level 1)

- `transition_mx_service_registry` → AVAILABLE adds two checks to the existing "every gate SIGNED" check, each refusing with a named reason:
  - Q9 RECORDED: evidence tag `MX-DECISION-Q9`. It becomes a fourth owner decision in the readiness view.
  - `MX_IDENTITY_TOKEN_KEY` set. Only its presence is checked; the key is never read into a response or a log.
- `onboarding_enabled()` takes the organisation and reads the registry row on every call. Every caller is updated: the 8 call sites, the Phase 4a guard, `tax_resolver` and the company-jurisdiction back-fill. No other country's resolution changes.
- If any condition stops holding later (a gate's evidence is superseded, or the key is removed), general availability is **not** withdrawn automatically. The readiness view shows the gap, and a Super Admin moves the registry back to PLANNED. This is decision D4 below.

## 4. Pilot (level 2) — non-binding by construction

**Grant lifecycle** (new table `payroll_mx_pilot_grants`):
- A Super Admin proposes a grant for one organisation, with a reason, a scope note and an **expiry** (D3).
- **A different Super Admin approves it.**
- Either Super Admin can **revoke** it at any time, with a reason. Revocation takes effect on the next request.
- Every step is audited, and the grant history is append-only.

**Preconditions to approve a grant** (D2): an **EVALUATION** workspace; the flag on; G1, G2, G4, G5 and G7 SIGNED; Q9 and the hosting decision RECORDED; the identity key configured.

**Pilot output is non-binding.** Each rule is enforced in code with a named refusal:

| Area | Pilot rule | Refusal |
|---|---|---|
| CFDI | Stamping and cancelling only through a PAC adapter registered for environment **SANDBOX**; a production PAC environment is refused. Each document is flagged `pilot`. | `MX_PILOT_SANDBOX_ONLY` |
| Payments | No SPEI file and no payment batch or worklist at all, because the pilot runs alongside the real payroll provider. | `MX_PILOT_NO_PAYMENTS` |
| Authority filings | No IMSS movement export or filing, no liability filed or paid, no ISN return filed, no SUA payment. **Reconciliation stays allowed**: entering SUA figures and comparing them is what G8 needs. | `MX_PILOT_NO_FILINGS` |
| Payslips | Every pilot payslip PDF is watermarked **"PILOT — PARALLEL RUN — NOT A PAYSLIP"**. The flag is recorded on the run when it is committed, so converting the workspace later never removes it (unlike today's evaluation watermark, which reads the live workspace type). | — |
| Journal | The export banner reads "PILOT — NOT FOR POSTING". | — |

**After the pilot** (D5): pilot data never becomes live data. Going live happens in a **new** live organisation, so pilot runs, accumulators and ledgers can never feed live ISR, SBC or PTU figures.

## 5. Data model

**One migration**, `mx_pilot_m14`:
- A new table, `payroll_mx_pilot_grants`: organisation, status (PROPOSED / APPROVED / REVOKED / EXPIRED), reason, scope note, expiry, proposer, approver, revoker, timestamps.
- RLS on this table only, as a tenant table.

**No shared column.** The pilot flag on runs and CFDI documents goes in the existing Mexico JSON fields: the approval fingerprint and the CFDI document metadata.

## 6. Routes and screens

- **Super Admin:** list, propose, approve and revoke pilot grants. The readiness view shows the level (DORMANT / PILOT (n organisations) / AVAILABLE), the grants and Q9.
- **Organisation:** a banner on every Mexico screen of a pilot organisation, stating that the output is non-binding.

## 7. Tests and verification

- **Unit tests:** each refusal; four-eyes approval; revoke and expiry; flag off closes everything; the registry needs gates, Q9 and the key; a pilot never opens a non-pilot organisation.
- **Test helpers:** the 14 test files that set the flag today get a registry or pilot fixture, mostly through the shared `_mx_employer_helpers` helper.
- **PostgreSQL 17:** the migration (lock time, fail fast, RLS) and the production upgrade path.
- **Browser:** pilot proposed, approved by a second Super Admin, the organisation opens with its banner; payments and filings refused on screen; a watermarked payslip; revoke closes the organisation; a non-pilot organisation stays refused.
- **Full suite.**

## 8. What this does in production when merged

- One new, empty table with its RLS policy.
- The flag is off in production, so nothing opens, exactly as today.
- The existing registry check becomes stricter (adds Q9 and the key).
- No other country is affected.

## 9. Decisions (approved 2026-10-22)

| # | Decision | Recommendation |
|---|---|---|
| D1 | The env flag's role | **Approved:** kill switch only — required at both levels and sufficient for neither. |
| D2 | What a pilot grant requires | **Approved, adjusted:** **G1, G2, G4, G5 and G7 SIGNED** (G3 moved to *during* the pilot: its credit reconciliation needs INFONAVIT's own figures for real workers), **Q9 RECORDED**, **the hosting / cross-border decision RECORDED** (real Mexican employee data enters for the first time; `organizations.data_region` defaults to EU), and `MX_IDENTITY_TOKEN_KEY` configured. Every gate checklist now tags its evidence PRE-PILOT, PILOT-GENERATED or GO-LIVE CHECK. |
| D3 | Pilot expiry | **Approved:** required, at most 120 days; renewal is a new grant with the same four-eyes approval. |
| D4 | Losing a condition after AVAILABLE | **Approved:** no automatic withdrawal; the readiness view shows it and a Super Admin closes the registry deliberately. |
| D5 | Pilot data at go-live | **Approved, extended:** a new live organisation, plus a **governed copy of the pilot's master data** (employer, registrations, establishments, employees, labour policy — never payroll results) into it: proposed by one Super Admin, approved by another, audited, with a diff report, so the live organisation matches what G8 proved. |
| D6 | Journal in a pilot | **Approved:** allowed, with the PILOT banner. |
