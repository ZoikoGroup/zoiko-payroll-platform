# Sign-off packet 07: Engineering lead (G2 authority conformance and G3 parallel runs: plan)

> **Status:** prepared by engineering on 2026-10-14. It contains no decision, value, result or signature made on anyone's behalf. Every evidence link gives the file's SHA-256 when this packet was generated: if the file you open has a different digest, stop and ask engineering.

## What you need to do

### G2: credentials and documents to request

| Need | From whom | Unblocks |
|---|---|---|
| IRD employer's-return software approval route and test-data submission (BIR56A / IR56B), and the current XML schemas | Inland Revenue Department, via its published process for approving computer-generated employer's returns. The owner or a named contact applies | IRD-01, IRD-02 |
| eMPF test environment access and credentials, and the remittance file / API specification | The eMPF Platform operator, via the employer's MPF trustee or eMPF onboarding contact. The interface follows owner decision D-1 | EMPF-01 … EMPF-04 |
| Secret storage for those credentials | Ops / Security (secret store; nothing in `.env` or the repository) | `EMPF_SECRET_STATUSES = CONFIGURED_IN_SECRET_STORE` |

Then run the G2 test plan. Engineering also has three builds to schedule:
* build the eMPF submission builder (BLOCKERS B-28). It must take rows only from `hong_kong_service.empf_filing_view`; a test enforces this;
* implement Security's choices for F-4, F-5 and F-6 (draft patches in `../ops/patches/`);
* apply or drop `../ops/patches/migration_lock_safety.patch`, per the pre-deploy row count.

### G3: two parallel cycles

1. **Prerequisites:**
   * Payroll Ops has set the thresholds (packet 05);
   * the owner and Security agree **where** parallel runs happen (real employee data must stay under the agreed controls);
   * the HK deploy is done (`../ops/HK_DEPLOY_RUNBOOK.md`).
2. **For each of two representative cycles** (ideally one plain month and one with leave, overtime or a termination):
   * run payroll in the existing system and in Zoiko for the same employees and period;
   * export both;
   * run `python -m scripts.hk_parallel_reconciliation` with the agreed tolerances;
   * explain every variance;
   * fill in the cycle sheet.
3. Upload `recon.csv`, `recon.json` and the signed cycle sheets under `HK-GATE-G3`.

## What to check

No G2 or G3 result exists yet. Every test in the G2 plan is marked PENDING, and the G3 tables are templates. Nothing may be reported as passed until it has actually run.

## Time estimate

* Requests: about 1 day of effort. Approval and credential lead times are set by IRD and the eMPF operator, so they are unknown.
* Parallel runs: two payroll cycles, which is calendar time (about 2 months), plus about 1 day of reconciliation per cycle.

## Evidence

* `../G2/G2_conformance_test_plan.md` — SHA-256 `d166bb42f1f65a7ca3b22203e9c2d6e581309ae66ee8720866a59311d9da8556`
* `../G2/hk_authority_document_register.md` — SHA-256 `0e3979e59807b62082357558d029b7ba1e744c793a84af03a39299c0ddaa428c`
* `../G2/authority_documents.csv` — SHA-256 `4b4cf0ce54a6fda93865b9bc934f900911c4432b10f1fed7fbb07da77743bb2e`
* `../G3/G3_parallel_payroll_reconciliation.md` — SHA-256 `991df30c3d932ccc1980472dfd739448effa801945fdd56fbb7a546bd72ff291`
* `../BLOCKERS.md` — SHA-256 `b405eeb6339be0d543da44c48a3e3b5788d32c137a6589dca1ceb6e69a0d2675`

## Sign-off (plan agreed; results are signed in the G2 / G3 evidence later)

| Name | Role | Date | Decision / conditions | Signature |
|---|---|---|---|---|
| | | | | |
