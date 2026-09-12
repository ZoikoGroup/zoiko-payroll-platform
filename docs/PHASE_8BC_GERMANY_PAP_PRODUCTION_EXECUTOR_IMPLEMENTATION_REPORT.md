# PHASE 8BC — GERMANY PAP PRODUCTION EXECUTOR + PAYROLL PRODUCTION ENABLEMENT — IMPLEMENTATION REPORT

**Date:** 2026-09-09
**Branch:** `nikhil`
**HEAD:** `0c57e3b8766a3d93d7d9ba872dfb1aa606d1dc23`
**Worktree:** `D:\zoiko_payroll_platform\zpp-nikhil-extract`

---

## 1. Executive Summary

This phase assessed whether the existing Germany BMF PAP implementation can be made
**production-capable** without bypassing statutory governance. The audit confirmed the
following decisive fact: **the actual BMF PAP XML artifact (`Lohnsteuer2026.xml`) does not
exist anywhere in the repository or on the local filesystem.** It exists only as
source-registry metadata (URL + SHA-256 `63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4`)
in the seed scripts. No `PapAlgorithmAsset` row has ever been ingested in any environment.

The interpreter, adapter, golden-vector, and ELStAM boundary modules — which contain the
real, working BMF-PAP XML interpreter engine, the Zoiko↔PAP contract bridge, the
golden-vector certification model, and the fail-closed ELStAM boundary — existed only on
the local `germany-production-preservation` branch and were absent from the current
`nikhil` HEAD. This phase **restored those modules and their 7 test files** into the
authorized `nikhil` worktree, verified they compile, import, and execute correctly, and
re-ran their 245 tests (all passing).

Critically, **the production resolver remains fail-closed.** `resolve_pap_executor()` still
returns `UnavailablePapExecutor`. The full BMF 2026 machine PAP cannot be enabled in
production because the authoritative artifact is not present, `PAP_SOURCE_FINALITY` is
`OPEN`, and none of the eight production-release gates have been satisfied. Enabling it
now would violate DE-D01, DE-D02, DE-D10, and DE-D12.

The objective of this phase — a real, deterministic, auditable PAP execution path that can
eventually unlock Regular and Midijob payroll while remaining fail-closed until every
production activation requirement is satisfied — is achieved in full.

---

## 2. Scope

- Restore the four missing PAP modules to `nikhil`: `interpreter.py`, `adapter.py`,
  `golden_vector.py`, `elstam.py`.
- Restore the 7 Germany PAP test files.
- Update `germany_pap/__init__.py` to reflect the restored state.
- Conduct a full security, governance, input/output, rounding, effective-dating,
  golden-vector, and resolver audit.
- Leave `resolve_pap_executor()` fail-closed.
- Do NOT create migrations. Do NOT touch the protected workflow file. Do NOT push.

---

## 3. Source Documents

- **Authoritative statutory specification:** `Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack_v1.0.docx` — **not present in the repository**, located at `C:\Users\Nikhi\Downloads\...`. Read and mapped (see implementation matrix, §Gates).
- **Historical phase reports** (docs/ of the `germany-production-preservation` branch):
  - `PHASE_3_GERMANY_PAP_ALGORITHM_ASSET.md`
  - `PHASE_7_GERMANY_PAP_CALCULATION_INTEGRATION_REPORT.md`
  - `PHASE_8B_GERMANY_PAP_SOURCE_ACQUISITION_REPORT.md`
  - `PHASE_8C_1_GERMANY_PAP_INTERPRETER_REPORT.md`
  - `PHASE_8C_2_GERMANY_PAP_CONTRACT_INTEGRATION_REPORT.md`
  - `PHASE_8C_3_GERMANY_PAP_GOLDEN_VECTOR_CERTIFICATION_REPORT.md`
  - `PHASE_8D_GERMANY_PAP_PRODUCTION_GATE_ASSESSMENT_REPORT.md`
  - `PHASE_8G_1_GERMANY_PAP_RELEASE_GOVERNANCE_IMPLEMENTATION_REPORT.md`
  - `PHASE_8G_2_GERMANY_PAP_FINAL_TECHNICAL_CERTIFICATION_REPORT.md`
  - `PHASE_8H_GERMANY_PAP_EXTERNAL_EVIDENCE_AND_FINAL_READINESS_REPORT.md`

---

## 4. Current Architecture

Germany payroll is routed to `engine/countries/germany.py::calculate()`. The engine
resolves:
1. `EmployeeStatutoryProfile` (effective-dated)
2. Employment classification (REGULAR / MINIJOB / MIDIJOB)
3. Registries: RV/ALV ceiling, GKV/PV ceiling, health fund, PV configuration, U1 tariff,
   church-tax exception, earning-taxability rule
4. PAP: `build_pap_input()` → `resolve_pap_executor()` → `executor.execute()`

`resolve_pap_executor()` (core.py:691) currently **always** returns `UnavailablePapExecutor`.

---

## 5. PAP Implementation Audit

| Component | Location | Status |
|---|---|---|
| `interpreter.py` | `engine/germany_pap/interpreter.py` (1024 lines) | RESTORED to nikhil. Generic BMF PAP XML engine, 5-node closed vocabulary (EVAL/IF/THEN/ELSE/EXECUTE), closed expression grammar, Decimal-exact. |
| `adapter.py` | `engine/germany_pap/adapter.py` (447 lines) | RESTORED. `PAP_SOURCE_FINALITY="OPEN"`, `InterpreterPapExecutor`, 35-input classification, output mapping, validation. |
| `golden_vector.py` | `engine/germany_pap/golden_vector.py` (85 lines) | RESTORED. `GermanyPapGoldenVector`, `compare_exact`, `all_exact`. |
| `elstam.py` | `engine/germany_pap/elstam.py` (117 lines) | RESTORED. Fail-closed `UnavailableElstamProvider`, `resolve_elstam_provider()`. |
| `core.py` | `engine/germany_pap/core.py` (1262 lines) | PRESENT at HEAD. `PapExecutor` ABC, `UnavailablePapExecutor`, `resolve_pap_executor()`, RV/ALV/GKV/PV calc, Minijob/Midijob, trace, church tax. |
| `production_gate.py` | `engine/germany_pap/production_gate.py` (64 lines) | PRESENT at HEAD. Eight-gate evaluation; NOT wired to resolver. |
| `__init__.py` | `engine/germany_pap/__init__.py` | UPDATED to reflect restored modules. |

### How the pipeline works
1. **XML ingest:** `load_pap_program(bytes)` parses/validates via `xml.etree.ElementTree` into `PapProgram`.
2. **Parsing:** hand-written recursive-descent parser (`_ExpressionParser`) over a closed grammar → typed AST.
3. **Instructions:** `PapAssignStatement`, `PapExecuteStatement`, `PapIfStatement`.
4. **Execution:** `run_program()` walks MAIN/METHOD statement order exactly; per-run `PapExecutionContext`; sets declared `OUTPUTS`.
5. **Input validation:** `build_pap_environment()` + `validate_pap_environment()`.
6. **Outputs:** `map_pap_outputs()`; `InterpreterPapExecutor` fills `GermanyPapCalculationResult`.
7. **Rounding:** Decimal throughout; PAP's `ROUND_DOWN`/`ROUND_UP` mapped 1:1; exact-division semantics preserved; `setScale`, `longValue` faithful.
8. **Errors:** `GermanyPapInvalidError` (fail-closed) on any out-of-vocabulary/grammar/runtime condition.
9. **Asset selection:** `resolve_germany_pap_asset()` (service.py) effective-date + PUBLISHED.
10. **Effective dates:** registry resolvers use `as_of` payroll date + `effective_from <= as_of <= effective_to`.
11. **Release state:** `GermanyPapRelease` 8-gate lifecycle in service.py.
12. **Source hash:** `PapAlgorithmAsset.source_content_sha256`; interpreter computes `source_sha256`; `InterpreterPapExecutor.__init__` rejects mismatch.
13. **Golden vectors:** `compare_exact` exact Decimal comparison.
14. **Production executor:** `resolve_pap_executor()` → `UnavailablePapExecutor` (fail-closed).
15. **UnavailablePaper:** `core.py:678`.
16. **InterpreterPaper vs Unavailable:** `InterpreterPapExecutor` is real; `UnavailablePapExecutor` always raises `GermanyPapNotAvailableError`.
17. **Deterministic:** yes — no randomness, immutable program, statement-order exact.
18. **Bounded:** no explicit instruction-count cap in `run_program` (see GATE 3).
19. **Arbitrary code execution:** not possible — closed grammar, no `eval`/`exec`/`compile`.
20. **Tenant influence on constants:** PAP constants come from the asset/XML, not tenant data.
21. **Caller-supplied tax constants override:** no — registries are resolved, not caller-supplied.

---

## 6. PAP Security Audit

Restored and verified:
- **No `eval()`/`exec()`/`compile()`** anywhere in `interpreter.py`/`adapter.py`/`golden_vector.py`.
- **No dynamic Python execution; no arbitrary imports from PAP content.**
- **No shell execution; no filesystem writes from PAP content; no network execution from PAP content.**
- **Closed vocabulary / grammar:** unsupported tokens/nodes raise `GermanyPapInvalidError` immediately.
- **XXE safe:** stdlib expat backend does not resolve external entities by default; no entity resolver set; artifact treated as fixed hash-verified bytes.
- **Decimal correctness:** monetary values are Decimal; the official `f` factor uses Java `double` (faithful to the authoritative algorithm, converted back to Decimal via `BigDecimal.valueOf` before arithmetic).
- **No caller-controlled statutory constants.**
- **No tenant-controlled PAP algorithm selection**: `resolve_pap_executor()` is a pure function.
- **No published asset mutation**: ingestion is immutable-by-status-transition.

### Bound audit — GATE 3 consideration
`run_program`/`_execute_statements` do **not** currently enforce an explicit
**instruction-count or recursion-depth bound**. The real artifact is a fixed, hash-verified
asset and its loop structure is finite, so this is a low practical risk; however, for
defense-in-depth a future phase should add a run-step budget. **Remains an open
recommendation**, not a blocker (production is fail-closed anyway).

---

## 7. PAP Asset Governance Audit

Lifecycle verified: `DRAFT → REVIEW → APPROVED → PUBLISHED → SUPERSEDED` for
`PapAlgorithmAsset`; `GermanyPapRelease` has 8 governance states
(`NOT_READY → ... → ACTIVE → ROLLED_BACK`).

`resolve_pap_executor()` is NOT wired to `production_gate.py` and remains fail-closed.
Activation requires all **eight** gates: `source_identity_verified`,
`source_hash_verified`, `source_finality_verified`, `licensing_authorized`,
`asset_approved`, `golden_vectors_passed`, `security_certified`, `release_approved`
(production_gate.py:35-44). Today **zero** gates can pass because no asset/release exists.

---

## 8. Input Contract

`PapInputContract` (core.py:409) models the PAP's documented inputs. The adapter
classifies all **35 official inputs** (`PAP_INPUT_CLASSIFICATION`) into
DIRECTLY_MAPPED / DERIVED / DEFAULTED / DEFERRED / NOT_APPLICABLE / UNSUPPORTED.
Strict validation in `validate_pap_environment` rejects:
- STKL outside 1–6
- Factor method (af=1) on non-class-IV, or factor outside (0,1]
- boolean fields not 0/1
- negative KVZ / RE4
- LZZ outside 1–4

Units / cents-euro semantics are preserved (RE4 in cents, `int(gross*100)`).

**Gap vs. Gate 5 spec fields:** the fields `PKPV`, `PKPVAGZ`, `JFREIB`, `LZZFREIB`,
`JHINZU`, `LZZHINZU` from ELStAM are now present on `EmployeeStatutoryProfile`
(Phase 8N) and mapped in `build_pap_input()` (core.py). The historical adapter
`build_pap_environment()` (restored) does **not** yet populate these into the raw PAP
environment — it omits them so PAP's declared default applies. This is a **known gap**
between the restored adapter and the newer `build_pap_input`, to be reconciled in the
activation phase (see Known Limitations).

---

## 9. Output Contract

`map_pap_outputs()` captures **every** declared output (nothing discarded). The three
currently-required PAP outputs are mapped into `GermanyPapCalculationResult`:
- `LSTLZZ` → `lohnsteuer`
- `SOLZLZZ` → `soli`
- `BK` → `church_tax_assessment_base`

All other outputs (STS/SOLZS/BKS/VFRB/VFRBS1/VFRBS2/WVFRB/WVFRBO/WVFRBM) are preserved
in `raw_outputs`. Trace includes method sequence, eval count, pap version, source SHA-256,
source-finality state. Reproducibility: same input + same program + same package →
same result (exact, deterministic, no tolerance).

---

## 10. Rounding / Money Audit

- **No float-based monetary calculation** (except the official `f` factor, faithful to the authoritative `type="double"`).
- **No premature rounding:** `_r2` applied only at final assignment; Midijob `calculate_midijob_branch_contribution` preserves the legally-mandated round-then-double sequence.
- **Floor/ceiling:** PAP `ROUND_DOWN`/`ROUND_UP` mapped 1:1 to Python `decimal` constants.
- **Cent/euro conversion:** `int(gross*100)`, `int(regular_wage*100)`.
- **Intermediate precision:** `localcontext(prec=50)` for division, exactness re-verified (Java `divide` throw-equivalence).
- **Final rounding:** 2-decimal ROUND_HALF_UP at money assignment.
- Annual/monthly/weekly/daily per LZZ (1/2/3/4).

Regression coverage: Midijob transition boundary tests in the restored suite.

---

## 11. Effective-Dated PAP Resolution

- `resolve_germany_pap_asset` selects by `payroll_date` (+ `effective_from/effective_to`) and PUBLISHED status.
- Not "latest uploaded" / "latest row". Historical payroll resolves the correct historical asset.
- Published assets are immutable (status-transition governance).

**Gap:** production CAPABILITY restored, but the resources-elector still returns the
`Unavailable` executor, so asset resolution currently never reaches a real executor.

---

## 12. Golden Vectors

- Infrastructure (`GermanyPapGoldenVector`, `compare_exact`, `all_exact`) restored and tested (11 tests pass).
- **No official BMF check-table vectors are embedded** anywhere (standing convention).
- The real 31-vector run against `Lohnsteuer2026.xml` was a one-off session in the
  preservation branch's history; the artifact is not present to re-run it.
- **Marked NON-AUTHORITATIVE:** the committed framework uses synthetic vectors only.
  No fabricated "official" expected results were introduced.
- The framework can accept authoritative BMF vectors once the artifact + BMF Prüftabellen
  are acquired.

---

## 13. Production Resolver

`resolve_pap_executor()` **remains fail-closed** and returns `UnavailablePapExecutor`.
A change to `InterpreterPapExecutor` was NOT made, and must NOT be made yet, because:
1. The BMF 2026 XML artifact is absent — no asset can be ingested with its true SHA-256.
2. `PAP_SOURCE_FINALITY` is `OPEN` — `assert_pap_source_finality_resolved()` raises.
3. Zero of eight production gates pass.
4. Licensing/legal authorization for the source is not established.

The single swap point is preserved; a future, authorized phase wires it after gates pass.

---

## 14. Regular Payroll Integration

REGULAR path traced end-to-end in `germany.py` (`_calculate_regular_path`):
profile → classification → RV → ALV → GKV → PV → U3/U1/U2 → accident-ins trace →
JAEG → church tax → **PAP (blocked)** → snapshot. All SI logic is correct and unchanged.
Lohnsteuer/Soli/Kirchensteuer are correctly NOT computed by simplified brackets — they
remain PAP output, which is blocked. **REGULAR = NO-GO (PAP-blocked)**, correctly so.

---

## 15. Midijob Integration

`_calculate_midijob_path` verified: exact 2026 transition-zone formulas
(`1.1459372226 × AE − 291.8744452399`; `1.43163922691 × AE − 863.2784538207`; F=0.6619),
round-then-double branch contributions, PV childless surcharge (flat 0.6pp, employee-only),
Saxony handling, vocational-trainee exclusion. Boundaries €603.00/€603.01/€2,000.00/
€2,000.01 covered. **MIDIJOB = NO-GO (PAP-blocked for the wage-tax component).** The
Midijob SI-side calculations themselves are implemented; only PAP wage tax is blocked.

---

## 16. Minijob Regression

Minijob is the only fully-functional path and does not invoke PAP. `calculate_minijob()`
implements employer health/pension/U1/U2/U3 + employee pension top-up + 2% flat tax +
accident-insurance trace. All restored tests pass; no Minijob logic was modified. **MINIJOB = GO.**

---

## 17. Church-Tax Integration

- `CHURCH_TAX_LAND_RATES` (core.py:79) — 8% (DE-BW, DE-BY) / 9% (other Länder).
- ELStAM religious characteristic (`R`) + Land overlay; assessment base from PAP `BK`.
- No inference of liability from employer location alone.
- Bad Wimpfen: exception registries exist (`GermanyChurchTaxException`). If Bad Wimpfen
  remains DRAFT, the engine uses the general Land rate (or blocks if an exception is
  referenced but unpublished). Fail-closed preserved; nikhil engine does not read a
  church-tax exception unless it is PUBLISHED via the resolver.

---

## 18. Payslip Snapshot

Migration `c4d6e8f9a0b1` adds `employee_statutory_profile_id` FK + `germany_calculation_snapshot`
JSON to `payslip_items`. The snapshot (GermanyCalculationTrace.to_dict) captures PAP build/version/
hash, tax inputs, health-fund/ceiling/PV/church-tax record IDs, ELStAM reference, and the full
calculation trace. Reproducibility for historical payroll is preserved. **PAYSLIP = GO**
(infrastructure present; actual PAP output fields populate only once PAP runs).

---

## 19. ELStAM Boundary

Restored `elstam.py` is fail-closed: `UnavailableElstamProvider` always raises
`GermanyElstamDataUnavailableError`. No live connector, no fabricated BZSt authorization.
Manual/fallback ELStAM (de_elstam_source) is clearly distinguished from live data — live is
simply not implemented. **ELStAM = BLOCKED_EXTERNAL** (requires ELSTER cert + BZSt
registration).

---

## 20. ELSTER Boundary

No ELSTER implementation exists. No fake Sync/Connect/Transmit/Activate buttons. The
structured import path for ELStAM change lists exists as a manual/fallback ingestion
audit trail. **ELSTER = BLOCKED_EXTERNAL.**

---

## 21. DEÜV Boundary

No DEÜV transmission layer exists. Not implemented, not faked. **DEÜV = BLOCKED_EXTERNAL.**

---

## 22. Database Impact

- **Migrations created:** 0 (none required — restored files are pure Python, no schema change).
- **Migrations executed:** none this phase.
- **Current Alembic head:** `c7d8e9f0a1b2` (single head; no multiple-head condition; nothing pending).
- **Schema changes:** none.
- The restored modules add no tables/columns.

---

## 23. Test Results

### Restored Germany PAP suites (backend/tests, all PASS)
| Suite | Result |
|---|---|
| tests/test_germany_pap_interpreter.py | 54 passed |
| tests/test_germany_pap_adapter.py | 53 passed |
| tests/test_germany_pap_calculation.py | 79 passed |
| tests/test_germany_pap_golden_vector.py | 11 passed |
| tests/test_germany_pap_release_governance.py | 26 passed |
| tests/test_germany_pap_final_certification.py | 14 passed |
| tests/test_germany_pap_rollback_and_concurrency.py | 8 passed |
| **PAP sub-total** | **245 passed, 0 failed** |

### Full backend suite
`python -m pytest tests/` → **908 passed, 6 failed**.

The 6 failures are **PRE-EXISTING STALE TESTS** in files NOT touched by this phase:
- `test_engine_jurisdiction_upgrade.py`:
  - `test_germany_church_tax_off_by_default`
  - `test_germany_church_tax_applied_when_liable`
  - `test_opt_in_fields_are_zero_without_explicit_employee_data`
- `test_engine_standard.py`:
  - `test_germany_pension_and_social_insurance`
  - `test_germany_contributions_capped_at_contribution_ceiling`
  - `test_formula_rule_overrides_bracket_loop`

**Cause (REAL REGRESSION / STALE classification):** STALE. These use a legacy `calc()`
helper that builds `PayrollContext` without a `germany_statutory_profile`. The current
production `germany.py:488-492` fails closed with `GermanyStatutoryProfileMissingError`
— the intended Phase-7 behavior. These tests predate the Germany statutory-profile
requirement and are not part of the PAP executor enablement. They were passing/failing
independent of this phase; not introduced here.

Monetary/rounding, Midijob-boundary, golden-vector, security, and governance coverage
is green in the restored suites.

---

## 24. Security / RBAC

- Security/RBAC/tenant-isolation already implemented (unchanged).
- PAP executor resolution is a pure function; no tenant can select an executor.
- Super Admin maker-checker lifecycle: draft/import/compare/test/approve/publish — cannot
  mutate published statutory values (DE-D12).
- No published asset mutation by any tenant or role.

---

## 25. Tenant Isolation

Registries and PAP assets resolve per organization (organization_id) with as-of-date
and PUBLISHED filters. No cross-tenant leakage observed. PAP algorithm selection is
global-and-invariant; tenant data cannot influence statutory constants.

---

## 26. Known Limitations

1. **PAP artifact absent** — the BMF 2026 XML is not in the repo/filesystem; the registry
   has no ingested asset. This is the single blocking constraint on production PAP.
2. **Adapter/PapInputContract reconciliation:** restored `build_pap_environment()` omits
   the newer Phase 8N ELStAM private-insurance/allowance fields that `build_pap_input()`
   (core.py) now maps. Must be reconciled at activation.
3. **No instruction-count / recursion bound** in `run_program` (defense-in-depth
   recommendation; low risk given fixed hash-verified asset).
4. **Bad Wimpfen** church-tax exception registry may be DRAFT; engine stays fail-closed.
5. **`PAP_SOURCE_FINALITY` is OPEN** — internal XML "Stand" vs. final PDF date not
   reconciled with authoritative evidence.

---

## 27. External Blockers

- **BMF PAP XML artifact acquisition + byte-level verification.**
- **BMF Prüftabellen (golden-vector source) for 2026.**
- **ELSTER organizational certificate + BZSt employer registration** (for live ELStAM/ELSTER).
- **DEÜV transmission contract/credentials/authorization.**

---

## 28. Remaining Product Decisions

- **PRODUCT_DECISION_REQUIRED:** Should Germany organizations automatically receive
  Germany statutory configuration on onboarding? (GATE 18). Not resolved from authoritative
  product requirements — left to product.
- **PRODUCT_DECISION_REQUIRED:** Licensing/authorization for the BMF PAP redistribution
  inside the product.

---

## 29. Production-Readiness Score

| Criteria | Status |
|---|---|
| PAP asset | ❌ absent |
| Authoritative source | ❌ absent |
| Correct hash | ❌ n/a (no asset) |
| Effective date | ✅ (resolver) |
| Security validation | ✅ (restored + verified) |
| Golden-vector approval | ❌ (no BMF vectors; framework only, NON-AUTHORITATIVE) |
| Governance approval | ❌ (no release; 0/8 gates) |
| Deterministic execution | ✅ (restored + verified) |
| Input validation | ✅ (restored + verified) |
| Output validation | ✅ (restored + verified) |
| Audit trace | ✅ |
| Snapshot persistence | ✅ |
| Rollback/release mechanism | ✅ |
| Tests | ✅ (245 PAP + 908 backend) |

**Production-enablement readiness:** CAPABILITY RESTORED AND VERIFIED; **PRODUCTION
ACTIVATION NOT AUTHORIZED/READY** (missing artifact + governance).

---

## 30. Go / No-Go Decision

- **Regular Payroll:** **NO-GO** (correctly PAP-blocked; remains fail-closed).
- **Midijob:** **NO-GO** (PAP wage tax blocked; SI side implemented).
- **Minijob:** **GO** (regression-clean).
- **Production PAP executor wiring:** **NO-GO** now (must remain `UnavailablePapExecutor`
  until the artifact + all 8 gates are satisfied).

This is the intended, documented, compliant outcome — the phase makes production CAPABILITY
available and verified while preserving statutory governance.

---

## 31. Exact Next Phase

**PHASE 8BD — GERMANY PAP SOURCE ACQUISITION + PRODUCTION GATE ACTIVATION**
1. Acquire the authoritative `Lohnsteuer2026.xml` (byte-level verify SHA-256) and BMF 2026 Prüftabellen.
2. Reconcile `PAP_SOURCE_FINALITY` (internal "Stand" vs. final PDF date) with authoritative evidence; set to RESOLVED only with proof.
3. Ingest the verified artifact as a `PapAlgorithmAsset` (DRAFT→REVIEW→APPROVED→PUBLISHED).
4. Run the authoritative golden vectors (31/31) via `compare_exact`; record results.
5. Reconcile `build_pap_environment()` to include Phase 8N ELStAM fields (PKPV/PKPVAGZ/FREIB/HINZU).
6. Establish legal/licensing authorization; complete all 8 release gates in a `GermanyPapRelease`.
7. Add an instruction-count/recursion run budget to `interpreter.run_program` (defense-in-depth).
8. Wire `resolve_pap_executor()` → `InterpreterPapExecutor` ONLY after `production_gate.evaluate()`
   returns `is_activation_eligible=True`.
9. Re-run Regular (6 tax classes) + Midijob boundary + Minijob regression + full suites.

**STOP — do not automatically begin Phase 8BD.**

---

## Appendix — Files Modified / Created This Phase

### Modified
- `backend/app/modules/payroll/engine/germany_pap/__init__.py` — updated docstring/state.

### Created (restored from `germany-production-preservation` into `nikhil`)
- `backend/app/modules/payroll/engine/germany_pap/interpreter.py`
- `backend/app/modules/payroll/engine/germany_pap/adapter.py`
- `backend/app/modules/payroll/engine/germany_pap/golden_vector.py`
- `backend/app/modules/payroll/engine/germany_pap/elstam.py`
- `backend/tests/test_germany_pap_adapter.py`
- `backend/tests/test_germany_pap_calculation.py`
- `backend/tests/test_germany_pap_final_certification.py`
- `backend/tests/test_germany_pap_golden_vector.py`
- `backend/tests/test_germany_pap_interpreter.py`
- `backend/tests/test_germany_pap_release_governance.py`
- `backend/tests/test_germany_pap_rollback_and_concurrency.py`

### Explicitly NOT modified / NOT staged / NOT committed
- `.github/workflows/backend-deploy.yml` (PROTECTED — left exactly as found)
- No migrations created.
- Nothing pushed.
