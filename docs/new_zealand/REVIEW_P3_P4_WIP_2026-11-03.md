# Review of the uncommitted NZ P3/P4 work (2026-11-03)

**Scope:** every uncommitted change on `venu` on top of `c8b1494` (P2), compared with:
- `IMPLEMENTATION_HANDOFF_P3_P10.md`
- `P3_CALCULATION_ENGINE_PLAN.md`
- `P3_CODE_ARCHITECTURE.md`
- `P4_SERVICE_HOOKS_AND_API_PLAN.md`

**Method:** I read every changed and new file and ran the NZ and cross-country test suites, without modifying any code.

## Verdict
**Do not commit this work as it stands.**
- It breaks P0/P1 behaviour that was already committed and green.
- It introduces a **platform-wide regression for every country**.
- The engine is not runnable: several modules raise `NameError` / `TypeError` on import or on first use.
- Where the engine does run, there are fail-open paths that would silently under-deduct tax (PAYE ÷ 26 twice, bonuses untaxed, ESCT 0, employer KiwiSaver 0).
- The P4 service and router do not implement the plan. The service fabricates statutory inputs; the router is written for Flask, while this app is FastAPI.

## Test evidence
| Suite | Result |
|---|---|
| NZ suites (scaffold, content, migrations, IRD, engine pack/components/paye) | **33 failed / 110 passed**. At commit `c8b1494` all NZ suites passed. |
| Cross-country subset (Japan P5/P9, Mexico scaffolding, entitlement, route registry, Hong Kong) | **2 failed**: `test_mexico_scaffolding::test_retention_settings_never_break_other_countries_reports` and `::test_other_hook_modules_unchanged` |

---

## A. Critical: breaks committed work or other countries

| # | File | Finding | Impact |
|---|---|---|---|
| A1 | `jurisdiction_hooks.py` + `new_zealand_service.py` | `"NZ"` was added to `_MODULES`, but `new_zealand_service.py` has a **SyntaxError** (line 710: `return` outside a function) and **no `JURISDICTION_HOOKS` dict**. `retention_service._report_country` loops over every registered country and calls `retention_settings`. | Report-download logging fails for **every country whose report reaches NZ in the loop** (IN, UK, US, CA, AU, ...). The test that guards exactly this is now red. It is the same incident class Japan had. |
| A2 | `new_zealand_service.py` | **`seed_nz_pack` and `nz_pack_activation_refusal` (P1, committed in `2293e11`) were deleted.** `scripts/seed_nz_canonical_packs.py` still imports them. | 9 P1 tests fail; the seed script is broken; there is no activation refusal for the ELA 2028 pack (AC-NZ-08). |
| A3 | `new_zealand_service.py` imports | It imports `Organization, Employee, CalculationSnapshot, AuditLog` from `payroll.models` (none exist there) and `service._calc_inputs` (does not exist; also a circular import with `service.py`). | The module cannot import even after A1's syntax error is fixed. |
| A4 | `errors.py` | `NZCalculationBlockedError.__init__` calls `super().__init__(f"NZ_{key}: …")`, but `MissingComplianceConfigurationError.__init__(key, country, organization_id)` needs three arguments, so every block raises **`TypeError`**. The message would also double-prefix (`NZ_NZ_…`). | **Fail-closed is gone.** Every intended block becomes an unhandled 500 instead of a clean refusal. All P0 scaffold "blocked" tests fail. |
| A5 | `nz_org_router.py` | Written for **Flask** (`from flask import Blueprint, request, jsonify`), while the app is **FastAPI**. It imports the non-existent `app.core.authz.require_nz_tenant` and the dependencies from the wrong module. It defines 0 FastAPI routes and is not mounted. | No P4 API exists. Importing it would fail. |
| A6 | `employee_validation.py` | `NZEmployeeValidation` was added to `_DORMANT_STRATEGIES`, but `_dormant_strategy()` was **not** given an NZ branch, so NZ falls through to `mexico_dormancy.flag_enabled()`. | NZ employee onboarding is controlled by the **Mexico** switch. Turning Mexico on opens NZ. |
| A7 | `employee_validation.py` | Stores **`ird_number` as a plaintext compliance field** with a `^\d{7,10}$` pattern (no mod-11 check). | Violates D-4 / NZ-023 / spec §13: IRD numbers must only live in the encrypted vault (`nz_ird_number.py`). |

## B. Engine correctness (P3): fail-open or wrong numbers

| # | File | Finding | Spec / plan |
|---|---|---|---|
| B1 | `paye.py` MAIN | Divides by the period factor **twice** (`tax = rnd(tax_annual/factor)`, then `final_tax = rnd(tax/factor)`), and subtracts the **annual** IETC from the **per-period** tax. | PAYE ≈ 1/26 of the correct amount for fortnightly pay. NZ-005 / §3. |
| B2 | `paye.py` `band_tax` | `hi = dec(max_amount)` turns `None` into `0`, so the "open top band" branch (`hi is None`) never runs and the top-band part becomes negative. | Wrong tax for income in the 39% band. |
| B3 | `paye.py` | `pack.table(..., required=False)` for bands, methods and secondary rates. Empty bands give **0 tax** instead of `NZ_TABLE_EMPTY`. | Fail-open (R5). |
| B4 | `paye.py` SECONDARY | Matches `filing_status` on the full code (`"S SL"`), but rate rows are keyed by the base code (`"S"`), so SL secondary codes never match. `base_code = code[:-3]` is wrong for `"SB"` and unused. | §3 secondary codes. |
| B5 | `components.py` | `earning_classes` reads non-existent fields `obligation` / `component` (rows use `tax_regime` / `filing_status`), so the map is empty and every component is "missing". Empty rows default everything to REVIEW instead of blocking `TABLE_EMPTY`. `field` is not imported, and `E.EARNING_CLASS_MISSING` does not exist. | P3 plan §2.3. |
| B6 | `components.py` | **`LUMP_SUM_PATH` amounts are silently excluded** from every base instead of blocking (`NZ_LUMP_SUM_UNSUPPORTED`). | A bonus would be paid with **no PAYE, ACC, SL or KiwiSaver**. Fail-open. |
| B7 | `components.py` | Unknown component names are silently ignored (the "unknown" check runs after filtering). An explicit `SALARY: 0` is replaced by `ctx.basic`. | P3 plan §2.3. |
| B8 | `pack.py` `as_date` | `value[:10]` on a real `date` object raises and is swallowed, returning **None**, so **every effective date on ORM/date rows is ignored** and every row counts as "in force". | Breaks payday-based selection (NZ-008) and the KiwiSaver 1-April rule. |
| B9 | `pack.py` `amount()` | A row whose `flat_amount` is None returns **0** instead of blocking. `nz_ks_employer_max_age` (empty by design) becomes 0, so `compulsory = min_age <= age < 0` is always False. | **Employer KiwiSaver silently 0** for everyone. Fail-open (R5, D-2). |
| B10 | `pack.py` `table()` | Uses an undefined variable `key`, so the first non-empty table raises `NameError`. `row()` also treats `text_value` as a label for the pending check. | Runtime crash. |
| B11 | `esct.py` | `_band_rate` returns a **fraction** (0.30) and compares it with `esct_rate_pct` stored as a **percent** (30), so every ESCT lookup fails. It ignores band upper bounds. `field` is not imported. `calculate_esct` divides by 100 again. | §4 ESCT. |
| B12 | `kiwisaver.py` | Suspension checks `reduction_ref` instead of `suspension_ref`. A suspension outside its window **raises** instead of contributing normally. A missing ESCT rate is treated as **0 ESCT** (fail-open). It calls an undefined `_age_on` and lacks the `date` import. It does not check `status == ACTIVE`. The window failure uses the wrong code (`KS_RATE_UNSUPPORTED`). | NZ-009, NZ-007, R5. |
| B13 | `acc_earner_levy.py` | `E`, `HUNDRED` and `money` are not imported, so it raises `NameError`. | Runtime crash. |
| B14 | `student_loan.py` | `_certificate` picks NIL vs RATE by **whether a ref exists** instead of `sl_certificate_type`, so a NIL certificate with a ref becomes RATE with rate 0. Many names are not imported (`field`, `upper`, `in_window`, `as_date`, `date`, `Optional`, `money`, `normalise_frequency`). It reads the monthly threshold first and returns it in the trace. | §5. |
| B15 | `child_support.py` | `pay_date` is undefined inside `calculate_child_support` (NameError), with several missing imports. **COURT_ATTACHMENT / IRD_DEDUCTION_NOTICE are silently ignored** (the plan says block). `max_allowed` is rounded *before* `min()`, so half-up rounding can exceed 40% by a cent. | NZ-010/012, R5. |
| B16 | `new_zealand.py` | `PROFILE_NOT_ACTIVE` is used without `E.` (NameError). The empty `nz_organization_id` attribute access breaks on a plain ctx. Residency is read from `ctx.residency_status` (always defaulted) instead of the tax profile. **The approved precedence is fetched but never used** (the order is hard-coded). `app["period_factor"]` raises KeyError. There are no `accumulatorDeltas`, so P4 cannot post accumulators (NZ-013). The result holds raw Decimals and diverges from the documented `nz_result` schema. | P3 plan §2.12 / §3. |
| B17 | `errors.py` `keyed()` | Joins with `"."`, while the plan and tests use `":"` (`NZ_TABLE_EMPTY:paye_main_method`). | Contract mismatch. |
| B18 | `tests/test_nz_content.py::…no_statutory_literal` | Fails: a bare `8` appears in `new_zealand.py` (the content's PAYG 8%). | R4 check. |

## C. P4 service: does not implement the plan

| # | Finding |
|---|---|
| C1 | `resolve_nz_calc_inputs` **fabricates statutory inputs** from `getattr` defaults: tax code `"M SL"`, IRD state `"VALID"`, KiwiSaver 3.50% / 3.50%, 38 h/week, the employer profile hard-coded `ACTIVE`, accumulators **always 0** (so the ACC cap is never applied), frequency `"FORTNIGHTLY"`, gross from `run.gross_amount`. It **never queries the P2 tables**. This defeats the whole fail-closed design (R4, R5, NZ-013, NZ-020). |
| C2 | `before_run_transition` returns `True` for every status and checks nothing: no snapshot, no VERIFIED employer, no minimum-wage block, no fingerprint, no accumulator posting. The `PAID` branch is unreachable (caught by the earlier `in ("AUTHORIZED","PAID")`). |
| C3 | Hook functions have the wrong names and signatures, e.g. `_nz_retention_settings()` returns a dict instead of `RetentionJurisdiction`, `pack_holidays(pack, as_of)` instead of `(db, year)`, and `statutory_editors()` takes no arguments. None are registered, because there is no `JURISDICTION_HOOKS`. |
| C4 | Copy-paste from another country: the "decisions" list is **Germany's** (Bad Wimpfen church tax, ELSTER, BZSt, DEÜV). It contains literal `db.query(...)` placeholders. `template_activation_status` is defined twice. |
| C5 | Not implemented: freeze/thaw/replay, fingerprint, preflight, versioned writers + four-eyes, the IRD vault workflow, the notice import, opening balances, the `service.py` call sites, `resolver.nz_inputs`, router mounting, route registry regeneration. Extra out-of-scope functions appear instead (IRD filing payload, off-cycle runs, Super Admin dashboards), which belong to P6/P8. |
| C6 | `schemas.py`: `nzPaymentKind` was put on `PayslipItemResponse` (it belongs on the run create/update/response schemas). |

## D. Tests written by the other agent
- `tests/_nz_engine_helpers.py` imports a non-existent `D` from `pack.py`, so every engine test errors at import.
- `test_nz_engine_components.py` calls `app.NzPack`, which does not exist.
- `test_nz_scaffold.py` was not updated for the post-stub engine.
- None of the planned P4 tests (`test_nz_phase4_*`) exist.

## E. What is acceptable and can be kept
- `engine/base.py`: the `nz_*` context fields and `PayrollResult.nz_result`. Still missing are `nz_legal_entity_id` and `nz_employee_id`; `nz_pay_frequency` / `nz_pay_date` are redundant with the existing `pay_frequency` / `pay_date`.
- `engine/standard.py`: the two lines adding `nz_employee_total` and `nz_result`, exactly as planned.
- `pack.py`'s overall shape (frequency aliases, rounding vocabulary, used-rows recording), once B8–B10 are fixed.
- `hashing.py`: the structure is as planned (only lightly checked).
- `minimum_wage.py` and `deduction_precedence.py`: broadly as planned.
- The route-registry and privacy-CSV "changes" are **line endings only** (no content change).

---

## Recommended recovery (needs Venu's go-ahead; nothing has been changed)

1. **Stop the regression first.** Restore the files to their state at `c8b1494` (that is, P2):
   - restore `new_zealand_service.py` with `git checkout c8b1494 -- backend/app/modules/payroll/new_zealand_service.py` (this also brings back the P1 seeder and activation refusal);
   - remove `"NZ"` from `jurisdiction_hooks._MODULES` until all 13 hooks exist;
   - revert the NZ hunk in `employee_validation.py`;
   - revert `errors.py`, or fix its `__init__` to call `super().__init__(key, "NZ", organization_id)` and keep the reason.
2. **Back up the WIP** (patch plus untracked tar in the session scratchpad) before reverting, as was done for Japan.
3. **Rebuild P3 to `P3_CODE_ARCHITECTURE.md`**, fixing B1–B18. Gate it on: all NZ suites green, the no-literal test green, and the worked example (fortnightly M SL, net 1,195.85) passing to the cent.
4. **Rebuild P4 to `P4_SERVICE_HOOKS_AND_API_PLAN.md`**, as a FastAPI router mirroring `japan_org_router.py` with service queries against the P2 tables. Register NZ in `_MODULES` **only in the commit that has all 13 hooks** plus `test_retention_settings_never_break_other_countries_reports` green.
5. Commit P3 and P4 separately. Push nothing until Venu says so.
