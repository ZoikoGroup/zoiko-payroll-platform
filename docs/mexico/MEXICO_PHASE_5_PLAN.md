# Mexico (MX) — Phase 5 Plan: Calculation engine

Spec ZP-MX-ENG-001 v1.0 §3–§10, §15–§17, §21 (fixtures F1–F5, F7; QA T1, T3, T4, T6), MX-003–MX-033, MX-048–MX-053, MX-063 · plan v1.1 §8.
Baseline: `main` = `nikhil` after PR #104 (Phase 4b deployed; production DB head `8b2f6d4e1a93`; Mexico dormant). **Plan only — nothing is built.**

Standing rules apply: stage only; zero behaviour change for other jurisdictions; **never infer or invent a statutory value** — the spec's own numbers (UMA 113.14 / 117.31, 315.04 / 440.87, 15.59 % / 15.02 %, the Annex 8 table, CEAV 7.513 %, CDMX 4 %, factor 1.049315) are **not** sources and are never typed into code or fixtures; fail closed; nothing Active by code; merging to `main` deploys to production (§11).

---

## 1. What Phase 5 is — and is not

**Is:** the pure Mexican calculator — functions that take a fully resolved `PayrollContext` (pack rows + Mexico facts) and return a traceable `mx_result`, or a coded `MexicoCalculationBlockedError`. No database access, no server date (MX-004), no hard-coded statutory value: every rate, tariff, threshold, divisor and rule comes from the context's `rate_map` / `slabs` (resolved from the canonical pack by pay date) or from the Mexico facts (profile, registration, premium, labour policy, classifications, notices).

**Is not:**
- **Not reachable in production.** `mexico_service.calc_inputs` (the hook that builds the context for a real run) keeps raising `MX_ENGINE_NOT_IMPLEMENTED` until Phase 6; no Mexican employee can exist while the flag is off; the national pack cannot be activated while `mx_golden` is empty (Phase 2 gate 4).
- **Not real Mexican figures yet.** Only S22 is saved; S1–S21 and S24–S33 are not. Until Batch A/B are saved, transcribed into `mexico_content`, G1-reviewed and seeded, the engine is proven on **synthetic** content only. Real golden vectors (F1–F5, F7) are authored after transcription — §8.
- No persistence: SBC history, variable accumulators and benefit accruals (deferred from Phase 4) are written by the run integration and move to **Phase 6** with the code that writes them → **no migration in Phase 5** (§11, Q10).
- No CFDI (Phase 7), no SUA/IDSE (Phase 8), no aguinaldo/PTU/finiquito/annual adjustment (Phase 9).

## 2. Package layout (`engine/jurisdictions/mexico/`, NL pattern)

| Module | Responsibility | Spec |
|---|---|---|
| `content.py` | Typed read access over `ctx.rate_map` / `ctx.slabs` in force on the pay date: `scalar(key)`, `isr_tariff(period)`, `ceav_bands(year)`, `min_wage(code)`, `workweek()`, `vacation_days()`, `isn_rate(state)`. Missing → `MXBlock("MX_CONTENT_MISSING", key, date)`. Never a default. | MX-003 |
| `period.py` | Payment period → ISR tariff period (`DAILY`, `WEEKLY_7`, `DECENAL_10`, `QUINCENAL_15`, `MONTHLY`), days paid, contribution days, the UMA in force per contribution date (Jan/Feb split). A period with no Annex 8 tariff → BLOCK (Q3). | MX-004, MX-008, MX-021 |
| `classification.py` | Splits each earning line by its multi-axis classification in force on the pay date (Phase 2 rows): ISR taxable/exempt, SBC fixed/variable/excluded, INFONAVIT, ISN (state override), PTU base, CFDI node. A code with no classification → BLOCK. Exempt portions only via a named exemption rule whose content exists (S24); otherwise BLOCK. | MX-005–MX-007, MX-009, MX-022 |
| `isr.py` | Ordinary withholding: `fixed_quota + (base − lower) × rate%` from the period's tariff row; bracket by `lower ≤ base ≤ upper`. | §4, MX-008 |
| `subsidy.py` | Eligibility vs the monthly ceiling, amount = `rate% × monthly UMA in force`, `< 1 month` via the days divisor, offset against ISR; remainder handling per the transcribed decree rule (Q4). | §5, MX-012, MX-013 |
| `sbc.py` | Fixed component = daily salary × integration factor derived from the labour policy (aguinaldo days, vacation days for the seniority year, vacation premium %) and other integrated fixed benefits; variable component from the supplied bimester accumulator (input, Phase 6 data); minimum and maximum (`mx_sbc_max_uma_multiple` × UMA per contribution period); full component trace. | §7, MX-019–MX-022 |
| `imss.py` | Every branch separately (MX-023): E&M fixed quota (× daily UMA × days), E&M excess over the threshold (UMA multiple) employer/employee, cash benefits, pensioner medical, Invalidez y Vida, Guarderías, Retiro, Riesgos de Trabajo (the registration's approved premium for the period, Phase 3 — MX-024). | §8 |
| `ceav.py` | Employee CEAV % and the employer band by SBC in UMA/SM multiples for the year (2023–2030 schedule content). The lowest band's minimum-wage reference stays [PENDING G2]: a ZLFN employee in that band BLOCKS (Phase 0 decision 4). | §9, MX-029 |
| `infonavit.py` | Employer housing % × SBC × days; employee credit deduction **only** from a notice in force (MX-031), method per notice; a method whose computation rule is not transcribed → BLOCK (Q7). | §10 |
| `isn.py` | State ISN: base = Σ earnings whose classification includes ISN for the work state; rate from the **Active** state pack; unsupported or non-Active state → BLOCK (MX-045). Federal bases unchanged (F7). | §15 |
| `labor.py` | Minimum-wage check (zone derived from work state/municipality, professional minimum override); weekly limit and overtime tiers from the workweek content applied to **approved hours supplied as input** (MX-049; no hours → no overtime earning, never a generic OT code); Sunday premium ≥ floor; mandatory rest days only from content. | §16, MX-048–MX-050 |
| `entitlements.py` | Statutory vs employer-enhanced entitlement **amounts** separated (MX-051) — reported in the trace for Phase 9; no special-pay withholding here (Q8). | §17 |
| `preflight.py` | Collects every BLOCK reason before computing (missing profile facts, identifier `MISMATCH`, no registration/premium, unsupported state, missing content) → one coded error listing all reasons. | MX-001, MX-036 |
| `rounding.py` | The single place for monetary rounding. Mode and point of rounding come from the transcribed `mx_rounding_rule` (Q2); full precision is kept internally, and while the rule is missing no amount is emitted (BLOCK `MX_ROUNDING_RULE_MISSING`). | — |
| `trace.py` | The MX-007 / MX-063 trace: per concept gross / exempt / taxable / bases; SBC components; each IMSS branch base × rate; CEAV band; INFONAVIT; ISN; subsidy; content row ids + source codes + pack id/version. | MX-007, MX-063 |

`engine/countries/mexico.py` `calculate(ctx)` becomes the orchestrator: country guard → preflight → classification → SBC → IMSS/CEAV/INFONAVIT → ISR + subsidy → ISN → labour checks → result. Returns the generic keys (`tds` = ISR after subsidy, employee social-security total in `mx_employee_total` — already summed by `standard.py`) and `mx_result` (employer totals inside it, NL pattern). Simple mode stays blocked (resolver, Phase 0).

**Context inputs** (`engine/base.py`, additive fields, all `None` for other countries): existing `mx_*` fields plus `mx_earnings` (lines: code, amount, units), `mx_period` (start, end, days paid, contribution days), `mx_hours` (approved ordinary/overtime/Sunday/holiday hours), `mx_variable_accumulator` (prior bimester total + days). Phase 6 fills them; Phase 5 tests construct them directly.

## 3. Content the engine needs — what exists, what is missing

| Rule | Content today | Gap → behaviour |
|---|---|---|
| ISR tariffs per period, subsidy %, ceiling, divisor, UMA daily/monthly/annual, SBC max multiple, IMSS branch rates, E&M excess threshold, CEAV bands + employee %, INFONAVIT %, benefit floors, workweek, vacation days, minimum wages, ZLFN list | keys / rule types exist (Phase 1), **values empty** | BLOCK `MX_CONTENT_MISSING` until Batch A transcription (S1–S3, S6–S10, S15, S17–S20, S26, S27) |
| Monetary rounding (mode, where) | none | **Q2** |
| ISR for intervals without a tariff (e.g. 14-day, other) | none | BLOCK (**Q3**) |
| Subsidy remainder when subsidy > ISR | none | **Q4** — value-free text key, from S3 |
| SBC minimum (floor) | none | **Q5** — value-free key/rule from S10 |
| Absence / incapacity contribution-day rules | none | BLOCK any period with absence/incapacity days (**Q6**) |
| INFONAVIT credit methods (VSM, UMA factor, period basis) | none | BLOCK those methods (**Q7**) |
| Special-pay ISR (aguinaldo, vacation premium, PTU, separation — Art. 93 exemptions, RLISR 174) | keys not named (S24/S25 unsaved) | BLOCK special-pay earnings in Phase 5 (**Q8**) |
| Overtime tiers (2026: double up to 9 h/week, then triple) | `MX_WORKWEEK.overtime_rules` structure, empty | BLOCK overtime until transcribed (S26/S18) |
| Mandatory rest days | none (`pack_holidays` returns []) | holiday-premium hours BLOCK |
| CDMX ISN rate / base | S22 saved; content empty, pack Draft | BLOCK until transcribed + Active (F7) |

New **value-free** keys/rules added to `mexico_content` (names only, `None`/empty, each with its expected source): `mx_rounding_rule` (text), `mx_subsidy_remainder_rule` (text, S3), `mx_sbc_min_rule` (text, S10), `MX_INFONAVIT_METHOD_RULES` (S27/S15), `MX_ISR_SPECIAL_PAY_RULES` placeholder (S24/S25, Phase 9). Activation gate 1 (exact content) automatically requires them once listed as required — new keys are marked **required: no** where the engine can BLOCK per case instead (Q11).

## 4. Fail-closed contract

Every function returns a value only when all its inputs and content are present; otherwise it raises `MexicoCalculationBlockedError(key, reason)` with a stable code (`MX_CONTENT_MISSING`, `MX_PERIOD_UNSUPPORTED`, `MX_CLASSIFICATION_MISSING`, `MX_SPECIAL_PAY_PHASE9`, `MX_ABSENCE_RULES_MISSING`, `MX_INFONAVIT_METHOD_UNSUPPORTED`, `MX_STATE_UNSUPPORTED`, `MX_CEAV_LOWEST_BAND_PENDING_G2`, `MX_IDENTIFIER_MISMATCH`, `MX_NO_RISK_PREMIUM`, `MX_OVERTIME_RULES_MISSING`, …). Preflight reports **all** reasons at once. Nothing degrades to a generic calculator or a zero.

## 5. Determinism and dates

- Law is selected by the pay date / contribution date from the context — never `date.today()` (pinned by a test that freezes the clock to a different year).
- A period spanning 31 Jan → 1 Feb uses the January UMA for January contribution days and the February UMA for February days (MX-021); ISR/subsidy by the pay date's month (MX-013).
- `Decimal` throughout; no float.
- The trace carries content row ids, the pack id/version and source codes, so a result is reproducible from its inputs (MX-006: historical classification versions).

## 6. Tests (synthetic content — clearly labelled SYNTHETIC)

| File | Covers |
|---|---|
| `test_mexico_engine_content.py` | content accessor: in-force selection by date, missing → BLOCK, no defaults |
| `test_mexico_engine_isr_subsidy.py` | bracket selection at every boundary of a synthetic 11-bracket table (T1); period tariffs; non-tariff period BLOCK; subsidy eligibility at the ceiling ±0.01; Jan vs Feb UMA + % switch (F5 mechanics); `< 1 month` divisor; offset against ISR |
| `test_mexico_engine_sbc.py` | factor from labour policy (directional test: more aguinaldo days ⇒ larger factor; F2 mechanics with synthetic floors); variable component from accumulator; min/max per contribution period; Jan/Feb ceiling split (F1 mechanics) |
| `test_mexico_engine_imss_ceav_infonavit.py` | every branch separately; threshold excess; risk premium from the registration; CEAV band boundaries (T4); lowest-band ZLFN BLOCK; INFONAVIT % and notice methods; unsupported method BLOCK |
| `test_mexico_engine_isn_labor.py` | ISN base by classification + state override; non-Active state BLOCK; minimum-wage geography (F4 mechanics); workweek/overtime from approved hours; 2026→2027 workweek boundary (MX-004/MX-050) |
| `test_mexico_engine_orchestrator.py` | end-to-end synthetic case → `mx_result` + trace fields (MX-063 list); preflight lists all reasons; `standard.py` dispatch sums `mx_employee_total`; server-date independence; non-MX contexts untouched |
| `test_mexico_engine_unreachable.py` | `calc_inputs` still raises; flag off → no MX employee; `mx_golden` empty → activation gate 4 still refuses |

Directional tests wherever a formula halves/doubles or compares (the splitting-formula lesson).

## 7. Other jurisdictions

Shared code touched: `engine/base.py` (additive `mx_*` context fields, default `None`); possibly `standard.py` only if the result mapping needs one more key (already has `mx_employee_total` / `mx_result`). No change to `resolver.py`, `tax_resolver.py`, `service.py`. Proof: full suite in chunks; `test_engine_standard.py` and every country engine suite unchanged; the shared-helper snapshot unchanged.

## 8. Golden vectors (`tests/fixtures/mx_golden/`)

**Stays empty in Phase 5.** The activation gate replays every `mx_golden` vector against the pack's rows, so a vector with synthetic values would either fail the real pack or, worse, be "fixed" to match it. Real vectors F1–F5 and F7 are authored **after** transcription, from the transcribed content plus an independent reference (SUA / PAC / state return — spec §21 "Final golden values require independent reconciliation"), each recording its pay date, tariff, UMA/minimum-wage version, SBC trace, every IMSS branch and ISN (MX-063). Phase 5 builds the harness binding (`pack_golden_check` already exists) and a fixture schema check.

## 9. Browser checks

None needed for correctness (no UI in Phase 5). One check: the Super Admin Mexico workspace and the Readiness G1–G8 tab still load, and the activation-readiness card for `MX-PAYROLL-2026` still lists "Pack-bound golden PASS: no Mexico golden vector" (gate 4 unmet).

## 10. Order of work

1. Context fields (`base.py`) + `content.py` + `period.py` + `rounding.py` stub per Q2, with tests.
2. `classification.py`, `isr.py`, `subsidy.py`.
3. `sbc.py`, `imss.py`, `ceav.py`, `infonavit.py`.
4. `isn.py`, `labor.py`, `entitlements.py`, `preflight.py`, `trace.py`, orchestrator.
5. Value-free content keys (Q2/Q4/Q5/Q7/Q8) + content tests.
6. Full suite in chunks, lint/build, report `MEXICO_PHASE_5_IMPLEMENTATION_REPORT.md` with the §11 table, stage, stop.

## 11. What this does in production when merged

| Change | Production effect |
|---|---|
| New engine modules under `engine/jurisdictions/mexico/`, orchestrator in `countries/mexico.py` | Code deployed but **unreachable**: the only production entry to a Mexican calculation is `mexico_service.calc_inputs`, which still raises `MX_ENGINE_NOT_IMPLEMENTED` (Phase 6 replaces it); no Mexican employee can exist (`MX_TENANT_ONBOARDING_ENABLED` off); a run with no Mexican payslips never dispatches to `countries/mexico.py`. |
| `engine/base.py` additive context fields | Default `None`; no other country reads them; no behaviour change (engine suites + snapshot). |
| `mexico_content.py` value-free keys | Names only; empty values; seeds unchanged in production (no seed runs on deploy). If any new key is marked required for activation, the pack simply stays non-activatable (it already is). |
| Migration | **None** (SBC history / accumulators / accruals move to Phase 6 — Q10). Production DB stays at `8b2f6d4e1a93`. |
| Routes / UI | None. |
| `mx_golden` | Stays empty → national pack activation remains refused (gate 4). |

Net effect: no production behaviour change. PR description: "engine code only, unreachable (calc_inputs still blocks), no migration, Mexico dormant".

## 12. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| Q1 | Prove the engine on **synthetic** content now and author real F1–F5/F7 golden vectors only after Batch A/B transcription + independent reference? | Yes. |
| Q2 | Monetary rounding: no saved source states it. Hold full precision internally and require a transcribed `mx_rounding_rule` (from S1/S2 Annex 8 notes, S10, or confirmed by SUA/PAC reconciliation) before any figure is emitted — BLOCK until then? | Yes — rounding is statutory-adjacent; don't guess HALF_UP. |
| Q3 | Pay intervals without an Annex 8 tariff (e.g. 14-day): BLOCK until the regulatory method (RLISR) is transcribed? | Yes. |
| Q4 | Subsidy greater than ISR: remainder handling taken from the 2026 decree text (S3) as a value-free rule; BLOCK the remainder case until transcribed? | Yes. |
| Q5 | SBC floor (minimum): value-free rule from S10; until then BLOCK an SBC below the zone minimum wage? | Yes. |
| Q6 | Absences / incapacity: BLOCK any period with absence or incapacity days until the IMSS contribution-day rules are transcribed? | Yes (spec: "do not simply zero the SBC"). |
| Q7 | INFONAVIT VSM / UMA-factor methods and the per-period basis of fixed/percentage credits: BLOCK until transcribed from S27/S15? | Yes. |
| Q8 | Special payments (aguinaldo, vacation premium, PTU, separation): BLOCK in Phase 5 and build their withholding (Art. 96 vs RLISR 174 election, Art. 93 exemptions) in Phase 9 with S24/S25? | Yes — Phase 5 is ordinary payroll only. |
| Q9 | Overtime only from approved hours supplied as context input (no time-system integration yet); no hours → no overtime? | Yes (MX-049). |
| Q10 | Move `payroll_mx_sbc_history`, `payroll_mx_variable_accumulators`, `payroll_mx_benefit_accruals` to Phase 6 (written by the run commit), so Phase 5 has no migration? | Yes. |
| Q11 | New value-free keys (rounding, subsidy remainder, SBC floor): **required for activation** (pack cannot go Active without them) rather than per-case BLOCK? | Rounding and SBC floor required; subsidy remainder per-case BLOCK. |
