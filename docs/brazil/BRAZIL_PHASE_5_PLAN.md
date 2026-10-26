# Brazil (BR) — Phase 5 Plan (Calculation engine)

Spec: ZP-BR-ENG-001 §7–§8 (fail-closed inputs, rubric-incidence bases, payment/competence dating, labor
rules, golden vectors). Master roadmap: `docs/brazil/BRAZIL_IMPLEMENTATION_PLAN.md` §8 (Phase 5).
Head today: `b9f3a7c2e5d1` (br_employer_m3 child chain; Phase 4b).
Companion: `docs/brazil/BRAZIL_PHASE_5_ANALYSIS.md` (requirement-by-requirement analysis).
Status: **plan — awaiting approval (§11). Nothing here has been built.**
Defects closed: **BR-K4** (silent employer-charge defaults), **BR-K5** (bases, alimony net, concurrent
flag, dependants). Open after it: **BR-K3** (rubric incidence codes, D6) and the labor-rate sourcing (§6).

## 1. Requirement set (verbatim from the Phase 5 brief)

| # | Requirement | Where it lands |
|---|---|---|
| R1 | Refuse instead of defaulting: every required input has its own block key | §2 |
| R2 | Tax bases from the rubric incidence codes; an unmapped earning blocks | §3 |
| R3 | Dates: IRRF uses the **payment date**; INSS and FGTS use the **competence month** | §2.2 |
| R4 | Alimony is deducted from **net pay** | §4.1 |
| R5 | **Contracted base salary** for vale-transporte; apprentice status from the **eSocial category** | §4.2, §4.3 |
| R6 | Employer side: **CPRB on covered payroll only**; financial-sector surcharge | §4.4 |
| R7 | Working-time rules in `engine/jurisdictions/brazil/labor.py`: overtime 50% **or the CCT rate**, DSR on overtime and variable pay, 52m30s night hour, minimum-wage floor | §5 |
| R8 | Golden fixtures **F1–F6** as JSON in `br_golden/` | §7 |
| R9 | Boundary tests at R$8,214.98 and R$8,475.55; IRRF at R$5,500, R$7,350 and R$7,350.01 | §10 |

## 2. Fail-closed inputs and dating

### 2.1 Refuse instead of defaulting (R1, BR-K4)
`calculate()` is promoted from `_calculate_draft()` (delete the draft) and every required input comes off
`ctx.brazil_inputs` (`engine/base.py:1028`) / `ctx.brazil_is_apprentice` (`:1032`). The silent trio
`brazil.py:518–530` (RAT 2% / FAP 1.0 / third-party 0%) is **removed**. A missing key raises
`BrazilCalculationBlockedError` with a stable key — never a default:

| Missing input | Block key |
|---|---|
| `rat_pct` | `BR_RAT_MISSING` |
| `fap_factor` | `BR_FAP_MISSING` |
| `third_party_pct` | `BR_THIRD_PARTY_MISSING` |
| `cprb_opted` present but regime undecided | `BR_CPRB_REGIME_MISSING` |
| `financial_sector` | `BR_CPP_SEGMENT_MISSING` |
| `competence_month` | `BR_COMPETENCE_MISSING` |
| concurrent employment known but external INSS absent (BR-009) | `BR_CONCURRENT_INSS_MISSING` |
| any earning whose rubric is unmapped | `BR_RUBRIC_UNMAPPED` |
| eSocial category absent / not 101 or 103 | `BR_ESOCIAL_CATEGORY_INVALID` |
| contracted salary absent where a base needs it | `BR_CONTRACT_SALARY_MISSING` |

Booleans (`cprb_opted`, `financial_sector`) must be **explicitly present** (not defaulted `False`): a
missing key blocks, so a financial-sector employer can never be silently rated at the ordinary CPP.
`dependents`, `alimony` and `vt_benefit` may legitimately be `0`; the "exists but unknown" case (BR-009
concurrent data) uses an explicit presence flag, never a zero.

### 2.2 Dates — payment vs competence (R3, BR-014)
The engine stops using the module-level constants pinned to `_AS_OF_2026 = date(2026,1,1)` and reads the
content **per date** via `brazil_content.rows_in_force(rule_type, as_of)`:

| Rule set | Date used |
|---|---|
| IRRF table + IRRF reduction + IRRF dependant/simplified deductions | `ctx.pay_date` (payment date) |
| INSS bands, FGTS rate, salário-família, minimum wage | competence month's first day |

`brazil_inputs["competence_month"]` (a `date`) is required; `ctx.pay_date` is required for IRRF. If
`pay_date` is absent → IRRF blocks; if either date falls outside a content window →
`BR_CONTENT_YEAR_UNAVAILABLE` (already raised by `rows_in_force`). The hardcoded `tax_year: 2026` in the
trace becomes the resolved years.

## 3. Bases from rubric incidence (R2, BR-005)

New pure module `engine/jurisdictions/brazil/bases.py`:
- Input: `brazil_inputs["earnings"]` — a list of `{"rubricCode", "amount"}` (the golden harness and
  Phase 6 both supply this shape) — plus the canonical catalogue
  (`brazil_content.STANDARD_SYSTEM_RUBRICS`, keyed by `rubric_code`).
- Output: `base_cp`, `base_irrf`, `base_fgts`, computed by summing each earning into the base its rubric's
  `cod_inc_cp` / `cod_inc_irrf` / `cod_inc_fgts` assigns it (`11`/`12` → base; `00` → exempt; `13`, `31`,
  `51` → their special handling).
- An earning with no matching rubric raises `BR_RUBRIC_UNMAPPED`; an instance rubric not in the catalogue
  blocks too.
- Standard component mapping (`basic`→`BR_SALARIO_BASE`, `overtime`→`BR_HORA_EXTRA_50/100`,
  premium→`BR_ADIC_NOTURNO`, …) is an explicit, unit-tested table so the golden harness can derive
  `earnings` from the context scalars.
- **The incidence codes are unverified (BR-K3, D6)**, so every fixture produced here is `PROVISIONAL`;
  G1/D6 sign-off converts them to `OFFICIAL`. `br_base_inss` / `br_base_irrf` / `br_base_fgts` in the
  result and trace come from this module, never from `gross`.

## 4. Employee and employer flows

### 4.1 Alimony from net pay (R4, BR-K5)
Today alimony only lowers the IRRF base (`brazil.py:563`). Phase 5 keeps that **and** adds a net-pay
deduction: `standard.py` gains an `br_alimony_deduction` slot alongside `br_vale_transporte_deduction`
(`standard.py:328`). The pure engine receives a resolved `alimony_amount` (fixed, or percentage × a named
base). **Circularity note:** a percentage-of-NET alimony depends on net, which depends on alimony — the
order is fixed: compute gross-based bases first (INSS, IRRF, VT), resolve the alimony from its declared
base (`GROSS`/`BASE_INSS`/`BASE_IRRF` are non-circular), subtract it last; a `NET`-based order is resolved
against gross-minus-statutory-deductions-before-alimony, documented in the trace.

### 4.2 Vale-transporte on contracted base salary (R5)
Base = `brazil_inputs["vt_base_salary"]` (the contracted monthly salary), **required** — no
`ctx.basic else gross` fallback (`brazil.py:580`). Deduction = `min(6% × base, actual benefit)`
(BR-029); the actual benefit is a resolved input (Phase 6 derives it from the Phase 4 VT election's
`daily_cost` × days).

### 4.3 Apprentice from the eSocial category (R5)
`is_apprentice` is derived from eSocial category **103** (Phase 4 `br_esocial_category`), not an ad-hoc
flag: category 101 → ordinary FGTS 8%, category 103 → apprentice FGTS 2% (`BR_FGTS_RATE/APPRENTICE`). The
engine reads the derived boolean; Phase 6 sets it from the profile. Category outside {101,103} blocks.

### 4.4 Employer side (R6)
- **CPRB on covered payroll only** (BR-020): `cpp_base` = CPP-covered payroll (earnings whose incidence
  includes CP), not total gross; under CPRB the covered subset only. The standard 20% / CPRB 10% selection
  is unchanged (`brazil.py:337–348`).
- **Financial-sector surcharge:** the +2.5% CPP add-on applies only when `financial_sector` is explicitly
  true (now required, §2.1), never defaulted.

## 5. Working-time rules — `engine/jurisdictions/brazil/labor.py` (R7)

Pure module (anticipated by `engine/jurisdictions/brazil/__init__.py`):
- **Overtime** at **50%** or the **collective-agreement rate** when a CCT/ACT rate is supplied (CLT
  art. 59). `brazil_inputs["overtime_rate_pct"]` overrides the 50% statutory default; absent → 50%. The
  CCT source itself is **Phase 8** — Phase 5 only accepts the override.
- **DSR** on overtime and variable pay (CLT art. 67/71; Lei 605/1949): paid weekly rest computed over the
  variable components; needs the period's Sundays/holidays count as an input.
- **Night premium** 20% on the **52m30s** legal night hour (CLT art. 73).
- **Minimum-wage floor**: block `BR_BELOW_MINIMUM_WAGE` when the contracted monthly/daily/hourly rate is
  below the `BR_MIN_WAGE` row in force (S4) — sourced, so this lands in 5a.
- Rates for OT/DSR/night are **not yet sourced**; they require CLT art. 59/73 + Lei 605/1949 in
  `docs/brazil/sources/` and `SOURCES_MANIFEST.csv` (see §6) or the module is deferred (§11 Q7).

## 6. Content additions

| Row | Rule type | Source |
|---|---|---|
| VT max deduction 6% (Lei 7.418/1985 art. 4º) — replaces the UNSOURCED `brazil_content.py:276` constant | new `BR_VT_RATE` | new S-code |
| Overtime 50/100, night 20%, DSR | new `BR_LABOR` rows (or labor.py constants) | new S-code (CLT) |

Content stays year-dated; `calculate_content_hash` (BR-K7) already covers new rows.

## 7. Golden fixtures and harness (R8)

Extend `hmrc_golden_harness.build_context` with a `_brazil_context(case)` helper (mirrors
`_sweden_context`/`_saudi_context`, `hmrc_golden_harness.py:310`): reads `country:"BR"`, `brazil_inputs`
(all §2 keys + `competence_month`, `vt_base_salary`, `earnings`) and `brazil_is_apprentice` from the case
`context`; expected keys are the flat `br_*` result fields (`standard.py:656–671`) plus `br_result.trace…`.

`backend/tests/fixtures/br_golden/` (spec §18), each `PROVISIONAL` with a hand calculation in
`source.formulas`:

| ID | Case | Phase-5 status |
|---|---|---|
| F1 | Ordinary CLT monthly wage (INSS, IRRF with reduction, FGTS) | **live (5a)** |
| F2 | Wage with variable/premium components (needs labor.py) | **live (5b)** |
| F3 | 13th salary (décimo terceiro) | file created, `blockedBy: Phase 7`, skipped by the harness |
| F4 | Vacation (férias + one-third) | file created, `blockedBy: Phase 7`, skipped |
| F5 | Termination (rescisão) + FGTS fine | file created, `blockedBy: Phase 7`, skipped |
| F6 | Minimum-wage floor | **live (5a)** |

This honours "F1–F6 as JSON in `br_golden/`" while respecting that F3–F5 need the Phase 7 engines (spec
§18) — they exist as JSON but do not run until Phase 7. The existing Super Admin runner
(`service.run_pack_golden_vectors`, dir `br_golden`) picks them up unchanged.

## 8. Files

**Backend modified:** `engine/countries/brazil.py` (real `calculate()`, delete `_calculate_draft`,
fail-closed inputs, date-driven content, alimony net, VT base), `engine/countries/brazil_content.py`
(`BR_VT_RATE` / `BR_LABOR` rows), `engine/base.py` (`brazil_inputs` additions), `engine/standard.py`
(`br_alimony_deduction` slot).
**Backend new:** `engine/jurisdictions/brazil/bases.py`, `engine/jurisdictions/brazil/labor.py`.
**Backend unchanged:** `brazil_service.calc_inputs` keeps blocking (Phase 6).
**Fixtures new:** `tests/fixtures/br_golden/F1…F6*.json`.
**Tests new:** `test_brazil_engine_failclosed.py`, `test_brazil_bases.py`, `test_brazil_labor.py`,
`test_brazil_employee_flows.py`, `test_brazil_boundaries.py`, `test_brazil_golden.py`; convert the BR-K2
xfails in `test_brazil_phase2_engine.py`.
**Docs:** this plan + the analysis report; a Phase 5 implementation report on completion.

## 9. No migration
No schema change; `test_alembic_metadata.py` unchanged. Production stays dormant
(`BR_TENANT_ONBOARDING_ENABLED` off; `calc_inputs` still blocks until Phase 6).

## 10. Tests — including the required boundaries (R9)

- `test_brazil_engine_failclosed.py` — one test per §2.1 block key; no RAT/FAP/third-party default;
  concurrent-INSS block; missing competence_month/pay_date block.
- `test_brazil_bases.py` — incidence bases; unmapped earning blocks; SF/13th/IRRF-exempt rubrics.
- `test_brazil_labor.py` — OT 50% + CCT override, night 20% × 52m30s, DSR, min-wage floor.
- `test_brazil_employee_flows.py` — alimony net deduction + non-circular order, VT on contracted base + 6%
  cap, apprentice via category 103 (2% FGTS), CPRB on covered payroll, financial surcharge explicit.
- **`test_brazil_boundaries.py` (R9)** — pinned to the real content (values verified against
  `brazil_content` on 2026-10-19):
  | Case | Expected (rounded once) |
  |---|---|
  | INSS on R$8,214.98 | **951.61** (below ceiling — the old 951.62 cap point) |
  | INSS on R$8,475.55 | **988.09** (top bracket boundary = ceiling) |
  | INSS on R$8,475.56 | **988.09** (flat above the ceiling) |
  | IRRF on R$5,500 (INSS 571.51) | **190.47** (reduction 246.32, SIMPLIFIED) |
  | IRRF on R$7,350 (INSS 830.51) | **884.13** (reduction 0.00, LEGAL) |
  | IRRF on R$7,350.01 (INSS 830.52) | **884.13** (reduction 0.00 — just past the phase ceiling) |
  R$5,500 and R$7,350 already exist in `test_brazil_phase2_engine.py::TestIRRFReductionBasis`; the rest are
  added. These directly pin **BR-K1/BR-K10** (INSS) and **BR-K2** (IRRF reduction on gross).

## 11. Decisions needed before I build
| # | Question | Recommendation |
|---|---|---|
| Q1 | Promote `_calculate_draft` to real `calculate()` while `calc_inputs` stays blocked (Phase 6)? | **Yes** |
| Q2 | `earnings: [{"rubricCode","amount"}]` on `brazil_inputs` as the base input shape? | **Yes** |
| Q3 | Incidence codes unverified (BR-K3/D6) → fixtures `PROVISIONAL` until G1? | **Yes** |
| Q4 | Overtime CCT-rate override accepted in Phase 5 (CCT source itself is Phase 8)? | **Yes** |
| Q5 | F3–F5 created as JSON but `blockedBy: Phase 7` (do not run until Phase 7)? | **Yes** |
| Q6 | Source CLT art. 59/73 + Lei 605/1949 **now** and build `labor.py` in 5b, or defer `labor.py`? | **Source now** |
| Q7 | Split: **5a** = R1–R6 + min-wage floor + F1/F6 + boundaries; **5b** = `labor.py` + F2? | **Yes** |

## 11a. Approval
Awaiting answers to Q1–Q7 (or a single "go ahead" to accept every recommendation). On approval I build
**5a**, run the phase gate (import, targeted pytest, `check:undefined`, build), then **5b**.
