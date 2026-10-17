# Mexico (MX) — Phase 5 Implementation Report: Calculation engine

Spec ZP-MX-ENG-001 v1.0 §3–§10, §15–§17 · plan `MEXICO_PHASE_5_PLAN.md` (Q1–Q11 approved as recommended) · staged on `nikhil`, not committed.
Baseline: `main` after PR #104 (production DB head `8b2f6d4e1a93`, Mexico dormant).

## 1. Result

| Check | Result |
|---|---|
| Full backend suite, run locally in 5 chunks (303 files) on scratch SQLite DBs | **6 403 passed, 1 failed, 50 skipped, 2 xfailed**. The one failure is the known **OOS-4** (`test_hong_kong_configuration`), the same as Phase 4. |
| New Phase 5 tests (7 files, 131 tests) | `test_mexico_engine_content` (27), `_isr_subsidy` (24), `_sbc` (17), `_imss_ceav_infonavit` (23), `_isn_labor` (15), `_orchestrator`, `_unreachable`. All pass. |
| Browser, flag **off** (production setting) | **7/7**: `phase5-evidence/RESULTS.md`, 3 screenshots, inspected |
| `vite build` | passes. No frontend source changed. |
| Migration | **none** |

## 2. What was built

**Engine package `engine/jurisdictions/mexico/`.** All modules are pure: no ORM and no server clock.

| Module | What it does |
|---|---|
| `errors.py` | `MexicoCalculationBlockedError` / `MXBlock` (moved here, and still re-exported from `countries/mexico.py`), now carrying `reasons` |
| `content.py` | `Content` gives typed access over `rate_map` and `slabs`: `amount`, `pct` (the key's own side ÷ 100), `text`, `isr_tariff`, `min_wage`, `ceav_bands`, `workweek_max_hours`, `vacation_days`. A missing row raises `MX_CONTENT_MISSING`, never a default. Every row read is recorded for the trace. |
| `period.py` | Art. 96 tariff period. Any other period raises `MX_PERIOD_UNSUPPORTED` (Q3). Absence or incapacity days raise `MX_ABSENCE_RULES_MISSING` (Q6). Contribution segments each carry their own rows, which is how the Jan/Feb UMA split works (MX-021). |
| `rounding.py` | `mx_rounding_rule` = `MODE:QUANTUM`. While it is missing, nothing is emitted (`MX_ROUNDING_RULE_MISSING`, Q2). |
| `classification.py` | Multi-axis split by the version in force on the pay date. A superseded row still applies inside its own window (MX-006). These all block: a missing classification; one not in force; EXEMPT/PARTIAL (`MX_EXEMPTION_RULE_MISSING`); special pays (`MX_SPECIAL_PAY_PHASE9`, Q8); lines that are not perceptions. |
| `isr.py` | fixed quota + (base − lower) × rate, using the bracket with the greatest lower limit ≤ base. |
| `subsidy.py` | Ceiling test, using month-to-date figures for periods shorter than a month. Amount = rate × monthly UMA, scaled by the days divisor, then offset against ISR. Remainder rule (Q4): `NOT_PAYABLE` sets withholding to 0; `CASH_PAYABLE` blocks (it needs a CFDI otro-pago line, Phase 7); a missing rule blocks. Exceeding the monthly amount blocks, because no cap rule is transcribed. |
| `sbc.py` | Factor = (365 + aguinaldo + vacation days × premium %) / 365, from the labour policy and the service year. The variable part comes from the accumulator. Floor rule (Q5): `RAISE_TO_ZONE_MIN_WAGE` / `BLOCK_BELOW_ZONE_MIN_WAGE`, and a missing rule blocks only when the SBC is below the floor. The cap is the multiple × daily UMA, per segment. Other FIXED items block. |
| `imss.py` | Each branch and side is its own line with base × days × rate. Riesgos de Trabajo uses only the registration's ACTIVE premium covering the period. |
| `ceav.py` | Employer band chosen in the band's own units (UMA, or SM via `mx_ceav_lowest_band_min_wage_ref`). An SBC between bands raises `MX_CEAV_BAND_GAP`. ZLFN in the lowest band raises `MX_CEAV_LOWEST_BAND_PENDING_G2`. |
| `infonavit.py` | Employer % × SBC × days. A credit deduction comes only from a notice covering the whole period, with the method's basis rule (Q7). VSM, UMA_FACTOR, a missing basis, or a mid-period notice all block. A SUSPENSION in force means no deduction. |
| `isn.py` | Base = lines included for the work state, with the state override applied. Rate comes from the state pack, which must be in scope and Active. |
| `labor.py` | Checks: zone or professional minimum wage; the policy's weekly hours against the statutory maximum in the pay-date rows. Overtime only from approved hours, using the tier content (Q9). Sunday premium: policy rate, never below the floor. Rest-day work blocks. |
| `entitlements.py` | Statutory vs employer aguinaldo, vacation days and vacation premium, in days and amounts (MX-051). A policy below a floor blocks. |
| `preflight.py` | Collects every reason before computing and raises `MX_PREFLIGHT_BLOCKED` with the full list. |
| `trace.py` | MX-063 trace, JSON-safe strings. |

**Orchestrator.** `countries/mexico.py` `calculate(ctx)` runs these steps in order:
1. preflight;
2. labour and hour lines;
3. classification;
4. gross check (`ctx.gross` must equal the classified lines, else `MX_GROSS_MISMATCH`);
5. SBC;
6. IMSS, CEAV and INFONAVIT;
7. ISR and subsidy;
8. ISN and entitlements.

It returns:
- `tds`: ISR after subsidy;
- `mx_employee_total`: IMSS employee branches + INFONAVIT credit, already summed by `standard.py`;
- `mx_result`: employer totals plus the trace.

`ENGINE_VERSION` is now `MX-ENGINE-2026.1`.

**Shared and Mexico code touched**
- `engine/base.py`: additive `mx_earnings`, `mx_period`, `mx_hours`, `mx_variable_accumulator`, `mx_min_wage_zone`, `mx_month_to_date` and `mx_pack`, all defaulting to `None`.
- `mexico_content.py`: value-free keys (§4). `MX_REQUIRED_TEXT_KEYS = (mx_rounding_rule, mx_sbc_min_rule)`. `MX_PER_CASE_KEYS` holds the three overtime keys.
- `mexico_service.py`:
  - `_content_check` now requires the two text keys and excludes the per-case keys;
  - `statutory_summary` is now phase 5, with a new note.
- `fallback_registry.py`: per-case keys are not readiness requirements.
- `mexico_service.calc_inputs` is **unchanged**: it still raises `MX_ENGINE_NOT_IMPLEMENTED`.

**Tests**
- New: `tests/_mx_engine_helpers.py` (synthetic content only, deliberately unlike published figures) and the 7 files above.
- Updated pins: `test_mexico_scaffolding.py` (no-facts context now gives `MX_PREFLIGHT_BLOCKED`; phase is 5), `test_mexico_seed.py` (required keys exclude the per-case keys), `test_mexico_activation_gates.py` (the fixture includes the required text keys).

## 3. Approved decisions applied

| Q | Applied as |
|---|---|
| Q1 | Synthetic content only. `tests/fixtures/mx_golden/` stays empty (pinned), and a fixture-schema check is added for future vectors. |
| Q2 | `MX_ROUNDING_RULE_MISSING` blocks every amount. The rule is required for activation. |
| Q3 | Non-Art. 96 periods raise `MX_PERIOD_UNSUPPORTED`. |
| Q4 | `mx_subsidy_remainder_rule` is blocked per case. |
| Q5 / Q11 | `mx_sbc_min_rule` is required for activation and blocks below the floor while missing. |
| Q6 | Absence or incapacity days block. |
| Q7 | INFONAVIT methods need their basis rule. VSM and UMA_FACTOR block. |
| Q8 | Special pays raise `MX_SPECIAL_PAY_PHASE9`. |
| Q9 | Overtime and Sunday premium come only from `mx_hours`. A supplied OT line raises `MX_OVERTIME_NOT_FROM_HOURS`. |
| Q10 | No migration. |

## 4. New value-free content keys

None of these has a value. Each is filled at transcription from the named source.

| Key | Kind | Source | Required for activation |
|---|---|---|---|
| `mx_rounding_rule` | text `MODE:QUANTUM` | S1/S2 notes, S10 or SUA/PAC reconciliation | **yes** |
| `mx_sbc_min_rule` | text (`RAISE_TO_ZONE_MIN_WAGE` / `BLOCK_BELOW_ZONE_MIN_WAGE`) | S10 | **yes** |
| `mx_subsidy_remainder_rule` | text (`NOT_PAYABLE` / `CASH_PAYABLE`) | S3 | no — blocks per case |
| `mx_infonavit_percentage_basis` | text (`SBC_TIMES_DAYS`) | S27/S15 | no |
| `mx_infonavit_fixed_amount_basis` | text (`DAILY_TIMES_DAYS`) | S27/S15 | no |
| `mx_overtime_double_weekly_max_hours`, `mx_overtime_double_multiplier`, `mx_overtime_triple_multiplier` | amount | S26/S18 | no (`MX_PER_CASE_KEYS`) |

The text vocabularies are the engine's names for the options it can compute. A transcribed rule that matches none of them blocks with `MX_RULE_UNRECOGNISED`, and the code is extended at that point.

## 5. What this does in production when merged (plan §11)

| Change | Production effect (`MX_TENANT_ONBOARDING_ENABLED` unset, so False) |
|---|---|
| Engine modules plus orchestrator | Deployed but **unreachable**. The only production entry is `mexico_service.calc_inputs`, which still raises `MX_ENGINE_NOT_IMPLEMENTED` (pinned). No Mexican employee can exist (the flag is off; `MX` is not in `_STRATEGIES`, pinned). A run with no Mexican payslips never dispatches to `countries/mexico.py`. |
| `engine/base.py` fields | Default `None`; no other country reads them. The suite is unchanged apart from Mexico. |
| `mexico_content.py` keys | Names only, no rows. No seed runs on deploy. The national pack becomes "more required", but it is already non-activatable: content is empty and there are no golden vectors. |
| Activation `_content_check` | Requires two more text keys. It only affects Mexico packs, which already fail gate 1. |
| `fallback_registry` | MX readiness requirements lose the three overtime keys. Mexico-only; there are no MX orgs. |
| `statutory_summary` | Super Admin Readiness tab now shows "Engine MX-ENGINE-2026.1" and the new note (browser-verified). |
| Migration | **None**. The database stays at `8b2f6d4e1a93`, and `check_schema_drift` is unaffected (no model change). |
| Routes / UI code | None. |
| `mx_golden` | Stays empty, so gate 4 still refuses both MX packs (browser-verified). |

Net effect: no production behaviour change beyond the Mexico readiness text. Suggested PR description: "Mexico Phase 5 — engine code only, unreachable (calc_inputs still blocks), no migration, Mexico dormant".

## 6. Browser evidence (`docs/mexico/phase5-evidence/`)

Setup:
- the vite preview of the current build;
- uvicorn on a scratch SQLite DB built by `phase4-evidence/harness/setup_db.py`, with `MX_TENANT_ONBOARDING_ENABLED=false`;
- `harness/acceptance.py` driving installed Chrome.

All 7 checks pass:
1. The Super Admin Mexico workspace loads.
2. The Readiness G1–G8 tab shows all gates.
3. It shows "Engine MX-ENGINE-2026.1 · Available: No".
4. The new note is shown.
5. Activation readiness for MX-PAYROLL-2026 and MX-ISN-CDMX-2026 shows "Pack-bound golden PASS: no Mexico golden vector…" as unmet.
6. The org Mexico Compliance Centre still shows the dormancy message.
7. There are no 5xx responses or page errors.

The three 403s are the org admin's Mexico routes, refused by the 4a guard with the flag off, as expected.

## 7. Deviations and design notes

1. **Point of rounding.** The rule supplies mode and quantum. The engine rounds once per emitted concept total: each IMSS branch/side, CEAV, INFONAVIT employer, INFONAVIT credit, ISR, subsidy and ISN. The subsidy offset uses the rounded ISR and subsidy. This must be confirmed against SUA/PAC with the first real golden vectors.
2. **Integration-factor formula.** It uses the day count 365 from spec §7. Every other input comes from the labour policy.
3. **Error class moved.** `MexicoCalculationBlockedError` moved to `jurisdictions/mexico/errors.py` to avoid a circular import. Its import path from `countries.mexico` is unchanged.
4. **Added for the trace.** `mx_pack` (pack id/version/source codes) was added to the context. The plan's §2 listed only the other five fields.
5. **Gross check.** `ctx.gross` must equal the classified lines (`MX_GROSS_MISMATCH`), so Phase 6 must include the hour-derived lines in gross.
6. **Extra fail-closed blocks the plan did not list.** All of these are cases with no transcribed rule:
   - subsidy month cap;
   - an INFONAVIT notice starting or ending mid-period;
   - a CEAV band gap;
   - non-perception lines;
   - a missing salary line.

## 8. Phase 6 contract (what `calc_inputs` must supply)

- **Pay date, period and content:** `mx_payroll_date`, `mx_payment_period` (Art. 96 code), `mx_period` with segments split wherever a content row changes (each with its own `rate_map`/`slabs`), and the pay-date `rate_map`/`slabs`.
- **Lines and classifications:** `mx_earnings` with exactly one `ORDINARY_SALARY` line and no OT/Sunday lines; `mx_classifications` as dicts.
- **Hours and running totals:** `mx_hours`, `mx_variable_accumulator`, `mx_month_to_date`.
- **Employee and employer facts:** `mx_min_wage_zone`; registration, premium and labour policy as dicts; `mx_infonavit_notices`; `mx_isn_state_pack` with status and rows; `mx_pack`.
- **Gross:** `gross` equal to Σ lines, including hour lines.

## 9. Open / prerequisites (unchanged)

- Batch A/B transcription, including the new rule keys.
- G1–G8.
- Real golden vectors F1–F5, F7 with an independent reference.
- Q9 security decision, `MX_IDENTITY_TOKEN_KEY`, OOS-4 and OOS-7.
