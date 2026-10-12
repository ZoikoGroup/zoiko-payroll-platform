# Germany PAP — Production Activation Runbook

This is a **forward-looking operational runbook**, not a record of anything executed this phase. Nothing in this document has been run. It exists so that once the external blockers in `docs/PHASE_8BG_GERMANY_PAP_PRODUCTION_ACTIVATION_REPORT.md` §23 clear, the exact sequence of steps needed to reach real PAP activation is unambiguous — and so that no step is ever skipped under time pressure.

**Do not execute any step below until the step immediately before it is genuinely, evidentially complete.** Every gate in this system is deliberately fail-closed; skipping ahead will not "unblock" anything — the resolver (`resolve_pap_executor()`) has no path from governance-table state to real execution today, by design (see the activation report §12), so nothing here is even capable of silently going live early.

## Step 0 — Preconditions (must already be true before starting)

- [ ] Legal counsel has issued an explicit, written determination on whether Zoiko's runtime interpretation of the BMF PAP (CC BY-ND 4.0) is permitted, and under what conditions. This is a **prerequisite to Step 1**, not something to resolve in parallel with it.
- [ ] The determination is recorded somewhere durable and citable (not just a verbal go-ahead) — this is what `record_pap_release_licensing()` will need to reference (`authority`, `reference`, `evidence_location`, `evidence_hash` — all already-existing parameters).

## Step 1 — Acquire and retain the authoritative BMF artifact

1. Download the current tax year's official PAP XML directly from the BMF Datenportal (not a third-party mirror).
2. **Retain the file** — do not repeat the prior pattern of "download, hash, discard." It must exist on a durable store before ingestion.
3. Compute its SHA-256 and compare against BMF's own published value, if BMF publishes one; document the comparison either way.
4. Ingest it via the existing endpoint: `POST /compliance/germany/pap-assets` (Super-Admin-only, already implemented and tested — `super_admin/router.py`). This computes the hash server-side (never trusts a caller-supplied hash) and persists the file bytes via `object_storage.save_upload`.

## Step 2 — Publish the asset (existing maker-checker flow, unchanged)

1. `PUT /compliance/germany/pap-assets/{id}/status` → `REVIEW`.
2. A **distinct** Super Admin sets the approver: `set_pap_asset_approver`.
3. `PUT .../status` → `PUBLISHED`. This requires a recorded `source_content_sha256` (already enforced — `service.py:2359-2360`).

## Step 3 — Certify golden vectors (Phase 8BG's hardened gate)

1. Obtain the official BMF Prüftabellen (or equivalent authoritative check-table data) for the same tax year/version as the asset just published. **Do not use engineering test fixtures for this step.**
2. For each official check-table row, actually execute the real PAP program (via the existing `interpreter.load_pap_program`/`run_program`, or the `adapter.InterpreterPapExecutor` wrapper) against the row's documented inputs, and record the outputs it actually produced.
3. Construct one `GermanyPapGoldenVector` per row with:
   - `source_classification="AUTHORITATIVE_BMF"` (mandatory — anything else is refused),
   - `source_hash_sha256` equal to the asset's real hash,
   - the row's real `expected_outputs`, transcribed exactly from the Prüftabelle.
4. Call `record_pap_release_golden_vectors(db, release_id, actor_id, source_sha256=<asset hash>, vectors=[...], actual_outputs={<vector_id>: <what step 2 actually produced>, ...})`. The function itself will:
   - reject any vector not classified `AUTHORITATIVE_BMF`,
   - reject any vector whose hash doesn't match,
   - recompute the exact-match comparison and reject the whole call on any mismatch.
5. If any vector fails, **stop** — do not proceed to activation with a partially-certified release. Investigate the mismatch (it may indicate an interpreter defect, a transcription error, or a genuine artifact discrepancy) before retrying.

## Step 4 — Record the remaining evidence gates

Using the existing, unchanged functions:

- `record_pap_release_source_identity(...)`
- `record_pap_release_source_hash_verification(...)`
- `record_pap_release_source_finality(..., status="VERIFIED", authority=<real BMF confirmation reference>, ...)` — do not set `VERIFIED` without real evidence closing the Stand-date/PDF-date discrepancy (`docs/PHASE_8BG_GERMANY_PAP_PRODUCTION_ACTIVATION_REPORT.md` §6).
- `record_pap_release_licensing(..., status="AUTHORIZED", authority=<Step 0's legal determination>, reference=..., evidence_location=..., evidence_hash=...)`.
- `record_pap_release_security_certification(...)` — should reference an actual security review of the interpreter/adapter, not just "tests pass."

## Step 5 — Release approval (existing maker-checker, unchanged)

1. `mark_pap_release_ready(...)`.
2. A **distinct** Super Admin: `approve_pap_release(...)`.
3. `evaluate_pap_release_gate(...)` — confirm `is_activation_eligible is True` and `failed_gates == ()`.

## Step 6 — Activation (existing maker-checker, unchanged) — and the one thing still missing after it

1. A **third distinct** Super Admin (not preparer, not approver): `activate_pap_release(...)`.
2. **Important — re-confirm this before treating the system as "live":** as of this writing, reaching `ACTIVE` on `GermanyPapRelease` does **not**, by itself, change `resolve_pap_executor()`'s behavior. That function is currently hard-coded to always return `UnavailablePapExecutor`, deliberately disconnected from this governance table (verified by `test_all_gates_satisfied_recognizes_eligibility_but_never_activates_production_pap`). **A separate, explicitly-reviewed engineering change is required to wire `resolve_pap_executor()` to actually consult the `ACTIVE` release/asset** before any real payroll calculation will use it. Do not assume Step 6 alone makes Germany wage tax live — verify the wiring change has been made, reviewed, and tested (including a full regression run) before relying on it in any real payroll run.

## Step 7 — Post-activation verification (before trusting any real payslip)

1. Run a real payroll calculation for a known test employee and manually cross-check the Lohnsteuer/Soli/Kirchensteuer against an independent source (e.g. the same BMF Prüftabelle rows used in Step 3, if any match a realistic employee profile).
2. Confirm the calculation trace records the asset version, source hash, and `PAP_SOURCE_FINALITY` status actually used (the `InterpreterPapExecutor.execute()` return value already includes `calculation_trace` with exactly this — no new code needed to observe it).
3. Re-run the full backend test suite; confirm no new failures beyond the already-known 6-test stale cluster.

## Rollback

If anything in Step 7 looks wrong, use the existing rollback flow (`request_pap_rollback` → `approve_pap_rollback`, maker-checker'd, already implemented and tested) rather than attempting to patch a live release in place.

## Phase 8BM note (does not alter any step)

Phase 8BM modified only the payslip **presentation** layer, and no step above changes:

- A blocked (FAILED) Germany payslip now downloads as an explicit **STATUS : BLOCKED** document carrying the persisted `blockedReasonCode`/`blockedReasonMessage` and **zero monetary figures**, rather than a €0.00 payslip. This is the expected, honest artifact while Wage-tax (Regular/Midijob) remains fail-closed — see Step 6 item 2's fail-closed wiring requirement.
- The Kirchensteuer line on a valid payslip now renders (plumbing fixed); it will still show €0.00 on every pre-activation payslip because Minijob pays no church tax at source.
- The `GET /payroll/germany/reports/summary` report (Phase 8BI) now has a frontend tab on Compliance → Germany that displays the period properly, including the number of PAP-blocked payslips.

See `docs/GERMANY_JURISDICTION_FINAL_COMPLETION_REPORT.md`.
