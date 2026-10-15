# Mexico (MX) — Phase 0 Implementation Report

**Spec:** ZP-MX-ENG-001 v1.0
**Plan:** `docs/mexico/MEXICO_IMPLEMENTATION_PLAN.md`
**Gap assessment:** `docs/mexico/MEXICO_PHASE_0_GAP_ASSESSMENT.md`. Decisions are in §12 of that document.
**Branch:** `nikhil`, main checkout. The work is staged only and the user commits it.
**Date:** 2026-10-15

Phase 0 is registration scaffolding.

- The engine now dispatches Mexico, and every MX hook exists. Every MX hook and calculation either blocks or refuses — except `retention_settings`, which has to return a valid value (see "Hook behaviour"). Mexico payroll is not calculated and cannot be activated.
- Every other jurisdiction behaves as before.
- There are **no migrations** and no statutory values.

---

## 1. Files created

| File | Purpose |
|---|---|
| `backend/app/modules/payroll/engine/countries/mexico.py` | The calculator entry point, which blocks. Contains:<br>• `ENGINE_VERSION = "MX-ENGINE-2026.0"`<br>• `MexicoCalculationBlockedError(MissingComplianceConfigurationError)`, aliased as `MXBlock`<br>• `MX_NO_FALLBACK = None` (a defined sentinel)<br>• `calculate(ctx)`: returns `{}` for a non-MX context and raises `MX_ENGINE_NOT_IMPLEMENTED` for MX |
| `backend/app/modules/payroll/engine/countries/mexico_content.py` | The content skeleton. Contains:<br>• `SPEC` and `PACK_STATUS="Draft"`<br>• `MX_2026` pack id tuple<br>• ISN pack-id format and `MX_ISN_STATES_IN_SCOPE=("CDMX",)` (decision 7)<br>• `MX_*` TaxSlab `rule_type` constants<br>• `SOURCE_REFERENCES` S1–S23, verbatim from spec §22, and `SOURCE_CODES`<br>• `GATES` G1–G8<br>• An empty `MX_PARAMETER_KEYS`<br>**It contains no statutory values** (decision 3: Phase 1 adds them from saved official sources). |
| `backend/app/modules/payroll/engine/jurisdictions/mexico/__init__.py` | An empty package with a docstring listing the planned Phase 5 modules. |
| `backend/app/modules/payroll/mexico_service.py` | The jurisdiction module. It implements the full 13-hook `JURISDICTION_HOOKS` contract (same keys as NL and SA); see "Hook behaviour" below. |
| `backend/app/modules/payroll/mexico_schemas.py` | `MXGateState` and `MXReadinessResponse` (camelCase, NL style). |
| `backend/app/modules/payroll/mexico_router.py` | `/api/super-admin/compliance/mexico`. Has one route, `GET /readiness`, which is Super Admin only. |
| `backend/tests/test_mexico_scaffolding.py` | 23 tests (see §4). Every `app.*` import is lazy, because of the collection-order hazard. |
| `docs/mexico/OUT_OF_SCOPE_DEFECTS.md` | The NL and other-jurisdiction defects found during Phase 0, for ticketing (decision 9). Nothing in it was fixed. |
| `docs/mexico/MEXICO_PHASE_0_IMPLEMENTATION_REPORT.md` | This report. |
| `docs/mexico/Zoiko_Payroll_Mexico_Engineering_Wireframe_and_Implementation_Specification_v1.0.docx` | A copy of the spec. It is byte-identical to `../juris_docs/…` (decision 8). |

### Hook behaviour (`mexico_service.JURISDICTION_HOOKS`)

| Hook | Phase 0 behaviour |
|---|---|
| `pack_activation_refusal` | Always refuses, because the MX content and golden vectors are not built. |
| `template_activation_refusal` | Always refuses. |
| `service_registry_transition` | Goes through the shared governed `service.transition_service_registry`. Its readiness check reports G1–G8 as all unmet, so AVAILABLE is refused and the refusal is audited. |
| `calc_inputs` | Raises `MexicoCalculationBlockedError("MX_ENGINE_NOT_IMPLEMENTED")`. |
| `before_run_transition` | Raises `MX_RUN_NOT_SUPPORTED` on the move to APPROVED, AUTHORIZED or PAID. Moving back to Draft or Review is not blocked. It is reached only for runs that contain MX payslips. |
| `statutory_profile_errors` | Returns an error, so an MX statutory profile cannot be saved until Phase 4. |
| `statutory_profile_values` | Returns `{}`. |
| `pack_holidays` | Returns `[]`. No holiday is invented. |
| `statutory_editors` | Returns `set()`. |
| `payment_treatment` | Returns `{}`. |
| `payslip_hold_view` | Returns `None`. |
| `statutory_summary` | Returns `{jurisdiction:"MX", available:false, phase:0, gates:[G1–G8 OPEN], …}`. |
| `retention_settings` | Returns a valid, inert `RetentionJurisdiction`: no categories, decisions OPEN, and it matches only MX reports. **This hook must not raise** (see §5, deviation 1). |

---

## 2. Files modified

| File | Change | Why |
|---|---|---|
| `backend/app/core/jurisdiction.py` | • `JURISDICTION_TAX_SCHEMAS["MX"]`: schema only, with a comment. RFC is the primary field (`^[A-ZÑ&]{3}[0-9]{6}[A-Z0-9]{3}$`, the 12-character legal-entity RFC). `registro_patronal` is `^[A-Z0-9]{11}$` (format only, no check digit).<br>• Name→code entries for `mexico`, `méxico` and `estados unidos mexicanos`.<br>• `CODE_TO_COUNTRY_NAME["MX"]="Mexico"`.<br>• **Not** added to `REGISTRATION_COUNTRIES`. | This is the registry entry. Decision 1 keeps Mexico out of registration. The name map is required because `organizations/router.py`'s `/jurisdictions/tax-schemas` would otherwise raise a KeyError. |
| `backend/app/modules/payroll/jurisdiction_hooks.py` | Adds `_MODULES["MX"]`. | Registers the hook module. |
| `backend/app/modules/payroll/engine/standard.py` | • Imports `mexico`.<br>• `_calc_mexico`.<br>• `_COUNTRY_CALC["MX"]`.<br>• Adds `mx_employee_total` to the employee-deduction sum.<br>• Maps `mx_result` onto `PayrollResult`. | MX must never fall through to `_calc_generic`. The additions use `.get` with defaults, so other countries are unchanged. |
| `backend/app/modules/payroll/engine/base.py` | • Adds 14 `mx_*` context fields, all defaulting to None.<br>• Adds `PayrollResult.mx_result: dict = None`. | These are the inputs and output the Phase 5 engine will use. |
| `backend/app/modules/payroll/engine/resolver.py` | • Simple mode for MX raises `MexicoCalculationBlockedError("MX_SIMPLE_MODE_UNSUPPORTED")`.<br>• Adds a `mexico_inputs` kwarg and splat to `build_context_from_employee`. | Fail closed. Unlike NL's `NLError`, this error has a handler (see the out-of-scope defects list, OOS-1). |
| `backend/app/modules/payroll/service.py` | `_get_currency_symbol` gets `"MX": "MX$"` and `_get_currency_code` gets `"MX": "MXN"`. Four lines in total. | Without them MX would silently fall back to `"$"` and `"USD"`. |
| `backend/app/main.py` | Imports `mexico_router` and adds `include_router(mexico_router, prefix="/api")`. Two lines. | Mounts the router. **Only these two lines are staged.** The user's unrelated uncommitted deployment-verification hunk in this file is left unstaged. |
| `frontend/src/components/jurisdiction/CountryFlag.jsx` | Adds a `Mexico` SVG flag and `FLAGS.MX`. | Lets the compliance and statutory landing grids show a Mexico flag. |
| `docs/mexico/MEXICO_MASTER_PROMPT.md` | • Spec path fixed.<br>• Exception name changed to the NL-style error.<br>• Git rule changed to "nikhil branch, stage only". | Decisions 2, 5 and 8, plus the user's later instruction not to use a worktree. |
| `docs/mexico/MEXICO_IMPLEMENTATION_PLAN.md` | • Spec path fixed.<br>• `[P0 decision]` markers added for decisions 1, 2, 3, 4, 6 and 7.<br>• Corrections from the gap assessment: fallback approach, where seeding happens, the filing-calendar location, the approval-fingerprint hook, `TaxabilityMatrixTab`, and `_NO_TAX_SLAB_COUNTRIES`. | Decision 1 asked for the plan to be updated. The rest are the corrections the gap assessment confirmed. |
| `docs/mexico/MEXICO_PHASE_0_GAP_ASSESSMENT.md` | Adds §12, the decisions record. | Traceability. |

**Not changed, as decided:**
- `core/exceptions.py` (decision 2)
- `enterprise/service.py` `SUPPORTED_COUNTRY_CODES` (decision 1)
- `REGISTRATION_COUNTRIES`, backend and frontend (decision 1)
- `organizations/router.py` (data-driven)
- `utils/currency.js` and `utils/registrationRegions.js` (MX was already present)
- `service/errorClassification.js` (it has no registry)
- `hardcoded_defaults.py` (no MX fallbacks)
- The three NL defects (decision 9)

---

## 3. Migrations

None. Phase 0 adds no table or column. The Alembic head is unchanged at `f4b8d2a6c9e1`.

---

## 4. Tests

`backend/tests/test_mexico_scaffolding.py` has 23 tests:

- **Registry (5)**
  - The MX schema is present and is schema-only. Mexico is not in `REGISTRATION_COUNTRIES` or enterprise `SUPPORTED_COUNTRY_CODES`.
  - Name→code resolution works for "Mexico", "méxico" and "Estados Unidos Mexicanos".
  - The RFC and Registro Patronal patterns reject the wrong lengths.
  - `GET /api/jurisdictions/tax-schemas` lists Mexico.
  - Currency maps: MX gives MXN and MX$; NL still gives EUR and €; US still gives USD.
- **Content (1)**
  - S1–S23 are present, the pack status is Draft, the ISN scope is CDMX only, G1–G8 are listed, and `MX_PARAMETER_KEYS` is empty.
- **Engine (7)**
  - The blocked error is a `MissingComplianceConfigurationError`.
  - `_COUNTRY_CALC["MX"]` is the MX calculator, not `_calc_generic`.
  - Standard and enterprise modes raise `MX_ENGINE_NOT_IMPLEMENTED`; simple mode raises `MX_SIMPLE_MODE_UNSUPPORTED`.
  - The MX calculator ignores contexts for other countries.
  - The `mx_*` context fields and `mx_result` default to None.
  - `build_context_from_employee` accepts `mexico_inputs`.
  - A US calculation still works, with `mx_result=None`.
- **Hooks (7)**
  - All 13 hooks are registered and callable, and the other hook modules are unchanged.
  - Pack and template activation are refused.
  - `calc_inputs` blocks. Run approve, authorize and pay block; Draft and Review do not.
  - The profile, holiday, payment and hold hooks behave as described.
  - The registry cannot move to AVAILABLE and stays PLANNED. The shared `_registry_refused` path writes the audit row; this test does not assert it.
  - **Retention regression test:** with MX registered, `_report_country` still returns None for a US report, NL for an NL report, and MX for an MX report.
- **Router (3)**
  - `/readiness` returns 403 for an org admin.
  - For a Super Admin it returns 200 with G1–G8 all OPEN.
  - The shared `/compliance/jurisdictions/MX/statutory-summary` route serves MX.

### Results

**Backend (full suite, `pytest tests/`, not a subset):** **1 failed, 5896 passed, 39 skipped, 2 xfailed** in 21 min.
- All 23 Mexico tests pass.
- **The single failure is not caused by Mexico.** It is `test_hong_kong_configuration.py::test_every_hk_configuration_row_is_governed_documented_sourced_consumed_and_exposed`, which reads an untracked, stale local HK matrix CSV. See `OUT_OF_SCOPE_DEFECTS.md` OOS-4.

**How I got here:**
- **Run 1 (9 failures).** The first full run failed 7 Mexico tests and 1 HK privacy test (`test_hong_kong_privacy.py::test_access_log_records_hk_reports_only_and_is_tenant_scoped`). The cause was my bug: the `JURISDICTION_HOOKS` values were function objects, but `jurisdiction_hooks.get` resolves attribute-name strings.
  - The HK privacy failure confirmed the retention hazard behind deviation 1: with any MX `retention_settings` failure, a UK report download raised.
  - I fixed the values to strings (NL style) and re-ran the full suite, which gave the result above.
- **An earlier interrupted run** showed one `E` at about 40% that did not recur in either complete run.

**Frontend:**
- `npm run build`: exit 0.
- `npx eslint src/components/jurisdiction/CountryFlag.jsx`: clean.
- `npm run lint` across the repo reports 368 problems (184 errors, 184 warnings), **none of them in the changed file**. These are existing errors elsewhere in the codebase; Phase 0 adds none.

---

## 5. Spec rules covered

- **MX-001:** an unsupported Mexico calculation BLOCKS with a coded error, in every mode and through every hook.
- **MX-003 / MX-004:** structural only. The content module is Draft-only; `mx_payroll_date` is the pay-date input that will select law, never the server date. The values arrive in Phase 1.
- **§22 gates:** G1–G8 are modelled. The registry cannot open, and nothing can be activated.

---

## 6. Deviations from the plan or gap assessment

1. **`retention_settings` returns a valid, inert config instead of raising.** The gap assessment (§2a) proposed that it raise. While implementing, I found that `retention_service._report_country` (L119–125) calls `settings(country)` for **every** registered module on **every** report download. A raising MX stub would have broken report downloads for every country. A regression test now guards this.
2. **`before_run_transition` blocks only the forward approve, authorize and pay steps.** The gap assessment said "raise if the run has MX payslips". Blocking every transition would also stop a run that holds legacy MX payslips from being sent back to Draft or Review.
3. **The Registro Patronal pattern is `^[A-Z0-9]{11}$`.** It checks only the plan's "11 chars". No check-digit rule is invented.
4. **Gate states are fixed at OPEN in Phase 0.** They are not yet read from evidence artifacts. That reading arrives with gate evidence in Phase 10. This fails closed.
5. **Git:** I briefly created a separate worktree and branch (`../zpp-mexico`, `feature/mexico-phase-0`). On the user's instruction I removed both, after unlinking the `node_modules` junction first so the real `node_modules` was untouched. All work is on `nikhil` in the main checkout.

---

## 7. Behaviour change to note

Before Phase 0, a context with `country="MX"` fell through to `_calc_generic`, a generic progressive tax with no Mexican content. It now BLOCKS. This is the intended fail-closed change (MX-001).

Mexico was never in `REGISTRATION_COUNTRIES`, so no self-registered organisation can have MX employees. Any MX record created another way, such as by direct data entry, now blocks instead of being calculated with generic tax.

---

## 8. Open items for Phase 1

- **Decision 3:** download the source PDFs to `docs/mexico/sources/`:
  - SAT RMF 2026 Annex 8 (S1/S2);
  - the DOF subsidy decree (S3);
  - INEGI UMA 2025 and 2026 (S6/S7);
  - the CONASAMI/DOF minimum wages (S8/S9);
  - the 2020 pension-reform decree (S11);
  - the DOF workweek reform (S18);
  - the CDMX Fiscal Code (S22).

  If sat.gob.mx or dof.gob.mx is unreachable, I will ask the user to download them.
- **Decision 4:** the CEAV 1.00-minimum-wage band reference becomes a [PENDING G2] content parameter. Until SUA reconciliation confirms it, only ZLFN employees whose SBC falls in that band are blocked.
- **Decision 6:** ISN readiness rows use `program="OTHER_STATE_PAYROLL"`, with a code comment saying it is Mexico ISN.
- **Phase 1 additions:**
  - add MX to `_CANONICAL_PACK_ONLY_COUNTRIES` and `_VALIDATION_ENABLED_COUNTRIES`;
  - add the fallback-registry rows (`MX_NO_FALLBACK`);
  - build `seed_mexico_canonical_packs.py`, using NL's stricter `_require_confirmed_target` guard, with the registry row seeded PLANNED.

---

## 9. Staged files

There are 21 staged paths. Nothing is committed and nothing is pushed.

**Backend, new files:**
- `backend/app/modules/payroll/engine/countries/mexico.py`
- `backend/app/modules/payroll/engine/countries/mexico_content.py`
- `backend/app/modules/payroll/engine/jurisdictions/mexico/__init__.py`
- `backend/app/modules/payroll/mexico_service.py`
- `backend/app/modules/payroll/mexico_schemas.py`
- `backend/app/modules/payroll/mexico_router.py`
- `backend/tests/test_mexico_scaffolding.py`

**Backend, modified files:**
- `backend/app/core/jurisdiction.py`
- `backend/app/modules/payroll/jurisdiction_hooks.py`
- `backend/app/modules/payroll/engine/standard.py`
- `backend/app/modules/payroll/engine/base.py`
- `backend/app/modules/payroll/engine/resolver.py`
- `backend/app/modules/payroll/service.py`
- `backend/app/main.py`: **only the two Mexico router lines are staged.** The user's unrelated deployment-verification hunk is still unstaged in the working tree.

**Frontend:**
- `frontend/src/components/jurisdiction/CountryFlag.jsx`

**Docs (`docs/mexico/`):**
- `MEXICO_IMPLEMENTATION_PLAN.md`
- `MEXICO_MASTER_PROMPT.md`
- `MEXICO_PHASE_0_GAP_ASSESSMENT.md`
- `MEXICO_PHASE_0_IMPLEMENTATION_REPORT.md`
- `OUT_OF_SCOPE_DEFECTS.md`
- the spec `.docx`

**Not staged.** These belong to the user and were left untouched:
- `backend/.env.example`
- the unrelated hunk in `backend/app/main.py`
- `frontend/vite.config.js`
- `docs/SINGAPORE_*`
- `docs/HONG_KONG_*`
- `backend/scripts/validate_environment.py`

Suggested commit message:

```
mx: Phase 0 scaffolding — registry, fail-closed engine dispatch, hook module, readiness route

ZP-MX-ENG-001 Phase 0. MX tax schema (schema only, not in REGISTRATION_COUNTRIES),
_COUNTRY_CALC["MX"] blocking calculator, MexicoCalculationBlockedError, 13-hook
mexico_service (activation/registry refused, calc/run approval blocked, inert
retention settings), /super-admin/compliance/mexico/readiness, MX flag, 23 tests.
No migrations, no statutory values. Docs: gap assessment, decisions, plan updates,
out-of-scope defects.
```

---

## 10. Pre-commit verification (requested on Phase 0 approval)

- **MX `retention_settings`** returns this value:

  ```
  RetentionJurisdiction(
      country='MX', label='Mexico', categories=(),
      period_decision='MX-D-RETENTION-PERIOD', end_decision='MX-D-RETENTION-END',
      decision_reference='MX-DECISION-RETENTION',
      decision_state=mexico_service._decision_state,
      validate_employee=<lambda: mexico_service._employee(db, employee_id, organization_id)>,
      retained_record_label=mexico_service._retained_record_label,
      has_statutory_profile=mexico_service._has_statutory_profile,
      report_matches=mexico_service.is_mx_report,
      audit_spec='ZP-MX-ENG-001 v1.0')
  ```

  - `_decision_state` always returns `"OPEN"`.
  - `_retained_record_label` always returns `None`.
- **No purge or retention job can delete MX data because of this setting:**
  - `retention_service` performs no deletion at all. Its only guard for a future purge, `purge_refusal`, has **no callers**.
  - No scheduler or job reads `RetentionPolicy`. The only scheduled "retention" job is the Assist chat-session sweep (`assist/scheduler.py`), which does not use payroll retention.
  - With `categories=()`, `retention_policies("MX")` lists no category, so there is no `purgePermitted` entry.
  - `propose_retention_policy("MX", …)` is refused twice over: "unknown record category", and the period decision is OPEN.
  - The only behaviour this setting enables for MX:
    - access logging of MX payslip and report downloads;
    - MX legal holds;
    - the legal-hold check on employee delete (`assert_employee_deletable`). That check can only **refuse** a deletion. It never deletes.
- **Staged `main.py`:** exactly the two Mexico router lines. The user's deployment-verification hunk stays unstaged.
- **HK failure on a clean tree:**
  - The 21 MX paths were stashed (tagged entry, applied back by SHA with `--index`, then dropped by tag).
  - With the MX changes stashed, the same HK test was run against a throwaway SQLite (`PAYROLL_DATABASE_URL`/`DATABASE_URL` forced). It **fails identically**: the same 10 findings and a byte-identical assertion block.
  - After the restore, the staged diff's SHA-256 is unchanged and every working file's content matches the pre-stash backup. The only difference is CRLF line endings on checkout (`core.autocrlf=true`); the index is unaffected.
