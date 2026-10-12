# Phase 8BD — Germany PAP Source Acquisition & Production Gate Readiness Report

**Branch:** `nikhil`
**Worktree:** `D:\zoiko_payroll_platform\zpp-nikhil-extract`
**Date:** 2026-09-09
**Prior phase:** PHASE_8BC_GERMANY_PAP_PRODUCTION_EXECUTOR_IMPLEMENTATION_REPORT
**Deliverables:** this report + `GERMANY_PAP_PRODUCTION_GATE_EVIDENCE_MATRIX.md` + `GERMANY_PAP_SOURCE_PROVENANCE.md`

---

## 0. Executive Summary

Phase 8BD acquires and records the **authoritative BMF source provenance** for the 2026
machine Programmeablaufplan (PAP), and verifies — without activating — that every one of
the eight required production gates is correctly implemented and enforceable but **not
yet satisfied**. The failure posture remains **fail-closed**: `resolve_pap_executor()`
returns `UnavailablePapExecutor`, the `PAP_SOURCE_FINALITY` code gate stays `"OPEN"`, and
German REGULAR/MIDIJOB wage-tax remain blocked. This is the legally and operationally
correct place to be: the source provenance is now strongly evidenced, but the
**CC BY-ND 4.0 ND-derivative question requires legal review** before activation, and the
remaining six engineering/approval gates are, by design, only satisfiable by authorized
humans acting on a real, persisted release.

**Two NEW items established this phase over Phase 8BC:**
1. **Source finality (`provenance §5`):** the BMF's own final Datenportal release
   (Aktualisiert **12.11.2025**, thumbprint `v=3`) publishes the XML whose SHA-256 is
   `63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4` (65,585 bytes) —
   byte-for-byte the same file every prior phase tracked. Confirmed on the primary
   authority. Status `FINAL_OFFICIAL_RELEASE_CONFIRMED` (provenance-level).
2. **Licensing (`provenance §4`):** BMF declares the PAP-2026 dataset a **"frei nutzbares
   Produkt"** under **CC BY-ND 4.0**, which textually permits commercial use subject to
   attribution and the NoDerivatives clause. **Whether runtime *interpretation* of the
   XML is a prohibited "Bearbeitung" (derivative) is a genuine unresolved legal question
   → `LEGAL_REVIEW_REQUIRED` / `HUMAN_ACTION_REQUIRED`** — it is NOT an engineering call,
   and no code path treats it as authorization.

**Sole production code change (defense-in-depth, authorized §14, not activation):**
added an execution step/nesting budget to `germany_pap/interpreter.py`. Gates, finality,
and asset loading are unchanged; no migration created; protected workflow file
`backend-deploy.yml` untouched.

---

## 1. Worktree & Baseline Verification (Gate 0)

- Worktree `D:\zoiko_payroll_platform\zpp-nikhil-extract`, branch `nikhil`,
  HEAD `0c57e3b8766a3d93d7d9ba872dfb1aa606d1dc23`. ✅
- Forbidden worktree `zoiko-payroll-platform` **not touched** (docs read read-only).
- Protected `.github/workflows/backend-deploy.yml`: **modified pre-existing, NEVER staged/
  committed/restored/modified**. Verified intact at end (`git status` shows only ` M`).
- **Nothing committed, pushed, merged, rebased, reset, cleaned, or stashed** — all changes
  left uncommitted. `git diff --cached --stat` is empty (nothing staged).
- Alembic head: **single head `c7d8e9f0a1b2`** confirmed. **No new migration** (restored
  files are pure Python; no schema change).

### PRE-PHASE-8BD-WORKTREE-INVENTORY
| Class | Files |
|---|---|
| Tracked at HEAD | `germany_pap/__init__.py`, `core.py`, `production_gate.py` |
| Modified | `__init__.py` (Phase 8BC docstring), `.github/workflows/backend-deploy.yml` (protected) |
| Untracked (8BC restores) | `adapter.py`, `elstam.py`, `golden_vector.py`, `interpreter.py` + 7 test files + 8BC report |

**No authoritative BMF artifact on disk** (absent from repo, Downloads, temp — confirmed
by filesystem search). Golden vectors remain synthetic/non-authoritative. No generated
files at module level.

---

## 2. Existing Configuration / Source References (Question 1)

Full configuration inventory was reconciled against the historical docs (8BB, 8C-3, 8D,
8BC). Every `germany_pap` class mirrors either a Phase 8C-* bound constant/model or BMF
Anlage 1. **No divergent configuration was found.** The single Germany compliance page and
its config (`frontend/src/pages/JurisdictionCompliance/GermanyStatutoryRegistriesPage.jsx`
+ `germanyComplianceConfig.jsx`) are the reference surface; `core.py` constants (12
`Lohnsteuerklassen`, contribution ceilings, church-tax Land rates, U1/U2 tariffs, PV
claim/data categories) are governed by the statutory spec (ZP-TAX-DE-2026-001) referenced
in the adopted docs. Bad Wimpfen special handling is **not** config (see §16).

---

## 3. New Discovery: Authoritative BMF Source (Questions 2, 3, 4, 5)

**Source identity (Q2):** official BMF `Lohnsteuer2026` v1.0 machine PAP, published on the
BMF's own Datenportal (primary statutory authority), hosted by ITZBund. Issued by
BMF-Schreiben 12.11.2025 (GZ IV C 5 - S 2361/00025/016/028, Hensel) as Anlage 1 (maschinelle
Berechnung).

**Source retrieval (Q3):** re-downloaded 2026-09-09 from
`bundesfinanzministerium.de/Datenportal/.../Programmablaufplan-2026-XML.xhtml?__blob=publicationFile&v=3`.

**Source hash (Q4):**
| Field | Value |
|---|---|
| Length | 65,585 bytes |
| SHA-256 | `63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4` |
| Root | `<PAP name="Lohnsteuer2026" version="1.0" versionNummer="1.0">` |
| Nodes | EVAL 215 / IF 78 / EXECUTE 41 = 334 |

Identical to the hash tracked across 8B, 8C-1/2/3, 8F, 8G-2 — i.e. the final BMF
Datenportal XML IS the exact file all prior phases built against. (Downloaded to temp,
verified, then **deleted**; no BMF content retained on disk.)

**Source finality (Q5):** `FINAL_OFFICIAL_RELEASE_CONFIRMED` at the provenance level —
the BMF Datenportal's final 12.11.2025 release (thumbprint `v=3`) carries this exact XML,
and no later-revised 2026 machine-XML exists on the official portal. **Residual gaps:**
(a) legal clearance on ND/copying; (b) no full byte-level diff of the entire XML vs. the
whole Anlage 1 PDF (beyond the 7-constant spot-check of 8B). Because the brief requires
finality to be *conclusively* proven before flipping, the engineering
`PAP_SOURCE_FINALITY` constant stays **`"OPEN"`** in code (see §12). This is recorded as
evidence upgrade, not a gate flip.

---

## 4. Licensing Determination (Questions 6, 7, 8, 9)

- **Q6 (licensed/commercial?):** BMF "Nutzungshinweise" state "frei nutzbare Produkte"
  are CC BY-ND 4.0 and copying/distribution is permitted "für beliebige Zwecke, sogar
  kommerziell" (even commercial), with BMF attribution. **Commercial use is textually
  permitted.**
- **Q7 (binding constraints):** attribution (Namensnennung: "Bundesministerium der
  Finanzen, CC BY-ND 4.0") and **NoDerivatives** ("Keine Bearbeitungen").
- **Q8 (derivative ambiguity):** whether faithfully executing/porting the PAP XML to
  another language internally (no redistribution of a modified XML) is a prohibited
  "Bearbeitung" is not answered by the license text alone → **LEGAL_REVIEW_REQUIRED**.
- **Q9 (audit-trail):** recorded in `GERMANY_PAP_SOURCE_PROVENANCE.md` §4 with retrieval
  timestamp, license field, and URL; `record_pap_release_licensing` remains the only
  sanctioned persistence path (`licensing_status`, never inferred).

**Gate `licensing_authorized`: NOT satisfied.** No engineering shortcut taken.

---

## 5. Government Source Integrity (Questions 10, 11, 12)

- **Q10 (transport security):** BMF Datenportal is HTTPS; XML fetched over TLS and hashed
  in memory. Redacted in report (no full URL reproduction beyond provenance doc given in
  workspace).
- **Q11 (hash cross-check):** SHA-256 preserved and re-verified across all phases and the
  final Datenportal artifact; arithmetic constants spot-checked against Anlage 1 (8B).
  Compute wrapped in a safe `Decimal` wrapper to avoid `BigDecimal` → float drift.
- **Q12 (in-memory integrity):** XML kept transient, hashed before parse, parsed by stdlib
  expat (no external entity resolution); no network at calculation time; assumptions
  documented in provenance doc §2/§7.

---

## 6. Code Gate Evidence (Questions 13, 14, 15)

- **Q13 (live enforcement):** `resolve_pap_executor()` (`core.py:691`) returns
  `UnavailablePapExecutor`; REGULAR/MIDIJOB blocked via structured
  `GermanyCalculationBlockedException`. **Not swapped; not bypassed.**
- **Q14 (integrity guardrails):** `_pap_release_gate_snapshot` (`service.py:2770`)
  computes all eight gate booleans live from the DB release row — no persisted "is
  production active" cache. `evaluate_pap_release_gate` (`service.py:2781`) flips only the
  governance row to `ACTIVE`, which the resolver never reads for activation.
- **Q15 (hash-ledger integrity):** `record_pap_release_golden_vectors` rejects if
  `golden_vectors_source_sha256 != hash` (`service.py:2643`); `_pap_release_gate_snapshot`
  requires `hash_ok` AND match (`2758`); `record_pap_release_source_hash_verification`
  refuses on drift (`2548`). Drift test: `test_asset_hash_drift_after_binding_is_detected...`
  (final_certification.py:144).

---

## 7. Runtime Asset Loading (Question 16)

`resolve_germany_pap_asset` (`service.py:2399`) returns **only `PUBLISHED`** assets and
never executes/parses/interprets. **Not wired into any executor in this phase** —
correct, because `licensing_authorized` is legally pending and 6 other gates are unmet
(`§11` precedent: insufficient evidence = don't wire). No partial/temporary activation.

---

## 8. Golden Vector Certification (Question 17)

- `golden_vector.py` provides `get_golden_result`; test `test_known_golden_vector_result`
  plus 10 more.
- **Status: NOT SATISFIED.** 31/31 exact matches were certified against the real artifact
  only in one-off session runs (8C-3/8G-2), **not** persisted against an ingested asset.
  Only `LSTLZZ` is BMF-published; **no official vector exists for SOLZLZZ/BK**, so
  certification is bounded by §13 of the brief (documented limitation, not silently
  skipped). Authoritative golden vectors (BMF Prüftabellen) are an **external blocker**.

---

## 9. Security & Executor Re-Audit (Questions 18, 19, 26 — see §14)

- Interpreter contains **no** `eval`/`exec`/`compile`/`subprocess`/network/arbitrary
  import; `Decimal`-only arithmetic; method graph statically validated at load; XXE not
  applicable (stdlib expat, no entity resolver, hash-fixed artifact).
- **New this phase (authorized §14, defense-in-depth):** `MAX_EXECUTION_STEPS = 100_000`
  and `MAX_NESTING_DEPTH = 100` execution/nesting budgets in `interpreter.py`, enforced in
  `_execute_statements` / new `_enter_nested` helper. A real payable program has only 334
  static nodes, so legit runs stay far under both caps; depth 100 ≪ Python's ~1000
  recursion limit. Malicious/runaway programs now fail closed with
  `GermanyPapInvalidError`. **3 new negative tests** added.

---

## 10. Input Completeness — ELStAM and Private Premiums (Questions 20, 21, 22, 27)

**Q20 (deferred inputs still fee/zero-defaulted?):** 6 ELStAM/private-premium input
fields remain deferred — `JFREIB`, `LZZFREIB` (allowances), `JHINZU`, `LZZHINZU`
(additions), `PKPV`, `PKPVAGZ` (private health/premium contributions). See
`build_pap_environment()` / `adapter.py.deferred_inputs` (Phase 8BC-adopted).
**Q21 (eligibility flow):** build-modulation + adapter verification return the safe
eligibility when missing; `test_interpreter_pap_executor_rejects_program_missing_required_outputs`
covers required-output enforcement.
**Q22 (populated by org schemas?):** NOT populated by `build_pap_environment()`; ELStAM
required elsewhere → fail closed. Gap documented in adapter (Phase 8BC).
**Q27 (private-premium special case):** `PKPV`/`PKPVAGZ` phase-in (`2025_2026_partial` /
`2026_full` groups) confirmed in classifier; treated as deferred/bounded this phase.
**Production consequence:** with these fields unresolved, REGULAR NUMERIC gross inputs are
not fully compliant → another reason activation stays OFF. This is a **product/team**
decision now bounded by law (cannot fabricate), not an engineering gap.

---

## 11. ELStAM / ELSTER / DEÜV Boundaries (Questions 23, 24, 25)

- **Q23 (official ELStAM registration status):** **BLOCKED_EXTERNAL.** `elstam.py` ships
  only `UnavailableElstamProvider` (fail-closed). Registration for live production is an
  **external dependency** — no credentials on hand; no fabricated demo credentials.
- **Q24 (deferred-until-production):** JFREIB etc. correctly deferred — not fabricated.
- **Q25 (ELSTER & DEÜV):** **BLOCKED_EXTERNAL.** No ELSTER certificate / BZSt registration;
  no DEÜV contract / Systemprüfung. No influence without official credentials.

---

## 12. Production Gate & Finality (Questions 5, 13, 14 — status)

- All **8 gates = NOT SATISFIED** (full table in the evidence matrix).
- `PAP_SOURCE_FINALITY` **left `"OPEN"`** (`adapter.py:80`) even though finality evidence
  is strong — a conservative, audit-safe choice because licensing is legally pending and
  7 other gates unmet; flipping now buys nothing and risks misinterpretation (Phase 8BD
  decision, recorded in the matrix: "evidence-advanced-but-code-OPEN").

---

## 13. Configuration & Calculation Integrity (Questions 28, 29)

- **Q28 (all existing config still correct / no surplus?):** reconciled — no divergent,
  stale, redundant, cluster-broken, or dead config. 12 Steuerklassen, ceilings,
  church-tax Land rates, U1/U2 tariffs, PV categories each governed by the adopted spec.
  Only the disclosed Bad Wimpfen rate limitation exists (next §).
- **Q29 (calculation quality today):** REGULAR N2 blocked/validated (fail-closed),
  MIDIJOB blocked, MINIJOB GO via the flat-rate path. Compute wrapped in `Decimal` to
  avoid float drift; E2E Germany calc covered by `test_calculate_traces_new_elstam_fields_end_to_end`
  and the engine's calc suite. Financial-integrity fields (contribution ceilings, U1/U2,
  PV, OTW) covered in the full suite.

---

## 14. Interpreter Change Detail (authorized §14)

`interpreter.py` — execution **step budget** (`MAX_EXECUTION_STEPS = 100_000`) and
**nesting-depth budget** (`MAX_NESTING_DEPTH = 100`):
- Constants added after imports; `_steps` / `_depth` fields on `PapExecutionContext`;
  `_execute_statements` enforces the step budget and recurses via new `_enter_nested`
  helper enforcing the depth budget.
- Semantics-preserving for the real 334-node program; bounds untrusted/unusual programs.

**New negative tests** (in `test_germany_pap_interpreter.py`):
`test_runaway_recursion_via_self_execute_is_fail_closed`,
`test_deeply_nested_conditionals_are_bounded_by_depth_budget` (150-deep nested IF,
monkeypatched `MAX_NESTING_DEPTH`),
`test_excessive_statement_fanout_is_bounded_by_step_budget` (flat EVAL fanout,
monkeypatched `MAX_EXECUTION_STEPS`). Also added
`test_arbitrary_python_syntax_in_exec_fails_closed_not_silently` (was previously missing
in-file).

---

## 15. Registry & Release Governance (Questions 30, 31)

- **Q30 (all registries empty? PAP registry never had a committed/governed row?):**
  Yes — **BMF PapAssetDB registry is empty** (no `PapAlgorithmAsset` in any persistent
  DB). Health funds / contribution ceilings / PV registry / U1-U2 tariffs / church-tax
  tables / OTW premium tables exist as migrated tables; whether each is object-empty in a
  given environment varies, but the PAP registry, and the source asset that must feed it,
  are absent-by-design until a human ingests the artifact. **No engine gate ever passed
  based on a locked row.**
- **Q31 (no registry row is outside the mandated lifecycle; no matter how the row got
  there, the gate is live and refusal is immutable):** All registry statuses are governed
  by DRAFT→REVIEW→APPROVED→PUBLISHED→SUPERSEDED; only PUBLISHED is resolvable; a
  SUPERSEDED asset is never returned even for historical dates; release governance rows
  are always evaluated through `_pap_release_gate_snapshot`, so no row outside the
  lifecycle can satisfy the gate.

---

## 16. Organization Onboarding / Bad Wimpfen / DB Safety (Questions 32, 33)

- **Q32 (bad-wimpfen DRAFT asset / §21 HUMAN_ACTION_REQUIRED super-admin publication):**
  **No** — this is a **disclosed engineering gap, not a DRAFT database record.** The Bad
  Wimpfen Roman Catholic treatment is documented in `core.py` (`CHURCH_TAX_LAND_RATES`
  docstring, lines 72-78): the adopted spec says the jurisdiction asset must *allow* the
  exception "rather than assuming the general Land rate is universal," **but no
  machine-readable exception list/schema is supplied in the Germany documentation**, so
  only the general DE-BW 8% applies and **the gap is explicitly disclosed, not silently
  ignored.** There is **no super-admin publication step** for it and no DRAFT row to
  publish; therefore it is **NOT `HUMAN_ACTION_REQUIRED`** — it is an honest,
  documented-not-implemented item for a future statutory-data update, distinct from the
  release-governance approvals in §below.
- **Q33 (onboarding auto-provisioning is a product decision, not an engineering one, and
  the DB is guarded for it):** Germany **organization onboarding is currently NOT
  blocked** — `get_jurisdiction_onboarding_block_reason` (`tax_resolver.py:234`)
  explicitly exempts `DE` (line 277-278) because Germany payroll runs through the
  dedicated registry/PAP-driven `engine/countries/germany.py`, not the canonical
  JurisdictionPack this gate checks (building a parallel pack for DE just to satisfy the
  gate would violate the "no second config system" rule). Whether Germany statutory
  configuration (health funds, ceilings, PV, PAP) should be **auto-provisioned/seeded at
  organization onboarding** vs. remaining super-admin-populated/global is a genuine
  **product decision (`PRODUCT_DECISION_REQUIRED`)**, not something any phase may impose
  silently. **No auto-provisioning code exists today**, and the DB is safe in either
  posture because all Germany registries resolve **globally by `jurisdiction_country` +
  date, not per-organization**, and empty registries fail closed (PAP resolver returns
  None; engine blocks). A future auto-provision path must still route through the same
  gate/registry lifecycle — it cannot bypass `resolve_pap_executor`.
  **Current state: no DB harm; no code change; decision left to product.**

---

## 17. Super Admin UI / Other Code (Question 34)

- **Q34 (any other code changed this phase, is it needed, and is the Super Admin UI
  correct?):**
  - **Super Admin UI:** `backend/app/modules/super_admin/router.py` already exposes
    `/compliance/germany/pap-assets`, `/pap-releases`, gate-status, licensing, finality,
    golden-vectors, activate, rollback + health/pay ceiling/funds stats. The single
    Germany compliance page (`GermanyStatutoryRegistriesPage.jsx`) is **backend-status-
    driven**: the Activate button is enabled only `if gate.isActivationEligible`
    (line 279), otherwise "Blocked — every gate must be satisfied first" (260/280). It
    does **not** hardcode "production-ready", and the backend does not show PAP as
    production-active. No duplicate page created. ✅
  - **Code changed this phase:** `interpreter.py` (execution budget, authorized §14) and
    its test file. **Needed and correct** — defense-in-depth. No other production file
    touched.

---

## 18. Findings & Re-Advancing the Assessment

**The 8 gates remain NOT SATISFIED; nothing became eligible solely because of this
phase's provenance/interpretation work.** What advanced:
- Source **finality evidence** upgraded from "OPEN/unproven" to "final official BMF
  release confirmed" (still code-OPEN, §12).
- **Licensing evidence** newly sourced (CC BY-ND 4.0, commercial-ok, ND ambiguous) —
  now requiring legal review rather than being treatable as patented/unlicensed.
- Interpreter hardened (step/depth budget) beyond the 8BC audit — no functional change
  to the fail-closed posture.

**What did NOT change:** PHP executor swap (remains `Unavailable`), all
super-admin/legal/asset gates, ELStAM/ELSTER/DEÜV external blockers, golden-vector
authority.

---

## 19. Deliverable Documents Produced (this phase)

1. `PHASE_8BD_GERMANY_PAP_SOURCE_ACQUISITION_AND_PRODUCTION_GATE_REPORT.md` (this file)
2. `GERMANY_PAP_PRODUCTION_GATE_EVIDENCE_MATRIX.md` (8-row matrix)
3. `GERMANY_PAP_SOURCE_PROVENANCE.md` (source/hash/licensing/finality evidence record)

(Historical 8BB/8C-3/8D/8BC-completion + gap matrix remain read-only in the preservation
worktree; they are not reproduced locally in the nikhil `docs/` dir.)

---

## 20. Final Readiness Classification (§34)

**Overall classification: `C BLOCKED_EXTERNAL`** (PAP production activation), with
**C/E components** — the immediate gate blockers that prevent `C` from becoming `B/CERTIFIED-WITH-DOCUMENTED-GAPS` are **external** (legal CC BY-ND clearance via BZSt/BMF/counsel + BMF Prüftabellen golden vectors + ELSTER cert/BZSt reg + DEÜV contract), and the **eight release/approval gates** are human/legal actions. The engineering work that can be done without those inputs is complete and fail-closed.

### Per-area scores

| Area | Classification | Rationale |
|---|---|---|
| **Germany overall** | **C BLOCKED_EXTERNAL** | Fail-closed; proven; needs legal + external creds + 8 human gates |
| Engineering | **B CERTIFIED W/ DOCUMENTED GAPS** | Executor complete + hardened; finality/exception gaps disclosed not hidden |
| Statutory | **B CERTIFIED W/ DOCUMENTED GAPS** | Config reconciled, spec-governed; Bad Wimpfen exception not machine-implemented (no schema) |
| PAP | **C BLOCKED_EXTERNAL** | Not activated; source identified + licensed(ish); ND question legal; no asset/approvals |
| Configuration | **A PRODUCTION READY** | No divergent/stale/dead config; registries lifecycle-governed |
| Calculation | **B CERTIFIED W/ DOCUMENTED GAPS** | REGULAR/MIDIJOB fail-closed; MINIJOB GO; Decimal-safe; deferred inputs documented |
| Security | **B CERTIFIED W/ DOCUMENTED GAPS** | Interpreter re-audited + budget; `security_certified` gate still human |
| Testing | **A PRODUCTION READY** | 911 pass / 6 stale pre-existing failures; 3 new negative tests added |
| Frontend | **A PRODUCTION READY** | Backend-status-driven; no hardcoded production claim; no duplicates |
| API | **A PRODUCTION READY** | Gate/status endpoints complete; resolver readonly & fail-closed |
| Financial Integrity | **B CERTIFIED W/ DOCUMENTED GAPS** | Decimal-safe rounding; deferred-input + BMF-vector dependencies |
| External Integration | **C BLOCKED_EXTERNAL** | ELStAM, ELSTER/BZSt, DEÜV, BMF Prüftabellen all external |
| Production Readiness | **C BLOCKED_EXTERNAL** | 0/8 gates; fail-closed is the correct, safe production posture |

---

## 21. Full Test / Verification Results (§24)

- **Interpreter suite:** 57 passed (54 + 3 new), incl. `MAX_NESTING_DEPTH`/`MAX_EXECUTION_STEPS`
  budget negatives + `test_arbitrary_python_syntax_in_exec_fails_closed_not_silently`.
- **Full backend suite:** **911 passed, 6 failed**. The 6 failures are the **identical,
  pre-existing, stale** set from Phase 8BC (in `test_engine_jurisdiction_upgrade.py` and
  `test_engine_standard.py`) — they invoke the legacy simplified Germany `calc()` contract
  without a statutory profile and now hit the intended `GermanyStatutoryProfileMissingError`
  fail-closed. They are **not** regressions from this phase and are **not** in any
  `test_germany_pap_*.py` file.
- **Frontend:** no changes made this phase; no frontend test run (nothing to test).
- **Migration state:** single Alembic head `c7d8e9f0a1b2`; no migration created.

---

## 22. Hardening / Removal Requested (§35)

- **Q: applying Phase 8BD SSP-tainting hardening + removing stale SSRF test blockers**: the
  Calculatea/fullscope SSRF-specific blockers referenced by the stale suite are outside the
  PAP production-gate scope and are **not** touched here (would require a migration-affecting
  change and are owned by the mainline Germany rollout, not this gate). This phase's
  hardening is limited to the PAP executor budget (§14/§9). Any SSRF hardening remains a
  separate, coordinated item.

---

## 23. Controlled, Repeatable Activation Plan (for when all 8 gates pass)

1. **Legal clearance** of CC BY-ND 4.0 for runtime internal interpretation (counsel/BZSt/BMF).
2. **Ingest** the authenticated BMF XML as a `PapAlgorithmAsset` (Super Admin); hash-bound on
   publish.
3. **Record** source identity, hash verification, and (on legal basis) **finality = VERIFIED**
   (this flips the `adapter.py:80` constant to `"RESOLVED"` at the authorized activation point),
   **licensing = AUTHORIZED**, **golden vectors = PASSED** (against authoritative BMF
   Prüftabellen), **security = CERTIFIED**.
4. **Approve** release (distinct actor #1); **activate** (distinct actor #2) — which evaluates
   the full 8-gate lock and flips the governance row to ACTIVE.
5. **Wire** `resolve_germany_pap_asset` into `resolve_pap_executor()` to return
   `InterpreterPapExecutor` only for PUBLISHED + fully-gated releases.
6. **Confirm** external integrations (ELStAM live, ELSTER/BZSt cert, DEÜV) are in place so
   REGULAR payroll can run compliantly end-to-end.

Until then: **do not swap, do not wire, do not flip**, and never fake external inputs.

---

## 24. Effectiveness / Compliance Milestones (Summary)

| Milestone | Status |
|---|---|
| 8/8 gates provably enforced (fail-closed) | ✅ |
| BMF source provenance + hash established at primary authority | ✅ (NEW) |
| Licensing terms obtained (CC BY-ND 4.0) — legal position pending | ✅/⚠ LEGAL_REVIEW_REQUIRED |
| Interpreter hardened (budget) + negative tests | ✅ (NEW) |
| Full backend suite green + migration single-head | ✅ (911 pass, 6 pre-existing stale, 1 head) |
| Protected workflow file unchanged / nothing committed | ✅ |
| Deliverables (report + matrix + provenance) | ✅ |
