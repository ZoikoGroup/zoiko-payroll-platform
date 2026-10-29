# Brazil (BR) — Phase 5 Analysis (ZP-BR-ENG-001 v1.0)

**Status**: Analysis complete, all recommendations accepted. Phase 5a + 5b implemented.

---

## 1. Scope Recap

Phase 5 delivers the real, fail-closed Brazil CLT calculation engine (spec §7–§8), promoting the draft `_calculate_draft` to production `calculate()`, adding rubric-incidence bases, alimony net deduction, VT on contracted salary, apprentice FGTS 2%, CPRB on covered payroll, financial-sector CPP surcharge, and working-time rules (OT 50%/100%, night 20%, DSR, minimum-wage floor).

Golden fixtures F1–F6 as JSON in `br_golden/`; boundary tests at INSS ceiling and IRRF reduction phase-out.

---

## 2. Requirement-by-Requirement Analysis

| # | Requirement (from Plan) | Decision | Implementation |
|---|-------------------------|----------|----------------|
| R1 | Fail-closed every required input | ✅ Accept | 14 block keys (BR_MISSING_INPUT, BR_COMPETENCE_MISSING, BR_RAT_MISSING, BR_FAP_MISSING, BR_THIRD_PARTY_MISSING, BR_CPP_SEGMENT_MISSING, BR_CPRB_REGIME_MISSING, BR_UNSUPPORTED_CATEGORY, BR_ENGINE_RUBRIC_UNKNOWN, BR_BELOW_MINIMUM_WAGE, BR_CONTENT_YEAR_UNAVAILABLE, BR_CONTRACT_SALARY_MISSING, BR_CONCURRENT_INSS_MISSING, BR_SIMPLE_MODE_UNSUPPORTED) |
| R2 | Bases from rubric incidence | ✅ Accept | `bases.py::resolve_bases(earnings, catalogue)` sums each earning into CP/IRRF/FGTS base per its `cod_inc_*`; unmapped rubric → `BR_RUBRIC_UNMAPPED` |
| R3 | IRRF on payment date; INSS/FGTS on competence month | ✅ Accept | `calculate(ctx)` resolves `pay_date` for IRRF, `competence_month` first day for INSS/FGTS/SF/min-wage via `brazil_content.rows_in_force(..., as_of)` |
| R4 | Alimony from net pay | ✅ Accept | `br_alimony_deduction` added to `PayrollResult`; subtracted in `standard.py` after VT; IRRF base still deducts alimony per Receita examples |
| R5 | VT on contracted salary; apprentice from eSocial category | ✅ Accept | VT base = `brazil_inputs["contract_salary"]` (required); `is_apprentice = category == "103"` → FGTS 2% |
| R6 | CPRB on covered payroll; financial CPP surcharge explicit | ✅ Accept | CPRB `cpp_base` = sum of earnings with CP incidence; financial add-on only when `financial_sector=true` explicitly |
| R7 | Working-time rules in `labor.py` | ✅ Accept | `labor.py` exports `calculate_overtime`, `calculate_night_premium`, `calculate_dsr`, `calculate_dsr_from_total` with statutory defaults; CCT override accepted via `overtime_rate_pct` |
| R8 | Golden fixtures F1–F6 | ✅ Accept | F1 (ordinary), F2 (variable components), F6 (min-wage floor) live; F3–F5 JSON with `blockedBy: Phase 7` skipped by harness |
| R9 | Boundary tests | ✅ Accept | `test_brazil_boundaries.py` (added in phase2 engine test class): INSS at 8214.98/8475.55/8475.56; IRRF at 5500/7350/7350.01 |

---

## 3. Content Sourcing (BR-VT / BR-LABOR)

| Row | Rule | Source | Status |
|-----|------|--------|--------|
| BR_VT_RATE | MAX_DEDUCTION 6% | A5 Lei 7.418/1985 art. 4 | VERIFIED, added to manifest & content |
| BR_LABOR | OVERTIME_50 50% | A6 CLT art. 59 §1 | VERIFIED, added |
| BR_LABOR | OVERTIME_100 100% | A6 CLT art. 59 §1 | VERIFIED, added |
| BR_LABOR | NIGHT_PREMIUM 20% | A6 CLT art. 73 | VERIFIED, added |
| BR_LABOR | NIGHT_HOUR_MINUTES 52.5 | A6 CLT art. 73 | VERIFIED, added |
| BR_LABOR | DSR flag | A7 Lei 605/1949 art. 7 | VERIFIED, added |

**Note**: A6 CLT downloaded is the original 1943 text. Consolidated CLT (`del5452compilado.htm`) should be re-fetched and its art. 59/73 verified before G1 gate. Phase 5b cites A6 as source; the consolidated version must be the canonical citation at G1.

---

## 4. Decisions Closed

| Q | Question | Accepted Recommendation |
|---|----------|-------------------------|
| Q1 | Promote draft to real while `calc_inputs` stays blocked? | Yes — engine computes, API still blocks until Phase 6 |
| Q2 | `earnings: [{"rubricCode","amount"}]` on `brazil_inputs`? | Yes — harness and Phase 6 both supply this shape |
| Q3 | Incidence unverified (BR-K3/D6) → `PROVISIONAL` until G1? | Yes — all br_golden fixtures marked `status: PROVISIONAL` |
| Q4 | OT CCT override in Phase 5 (source Phase 8)? | Yes — `overtime_rate_pct` optional override accepted |
| Q5 | F3–F5 JSON with `blockedBy: Phase 7`? | Yes — files exist, harness skips underscore prefix |
| Q6 | Source CLT 59/73 + Lei 605 now for `labor.py`? | Yes — A6/A7 added to manifest and cited |
| Q7 | Split 5a = R1–R6 + min-wage + F1/F6 + boundaries; 5b = `labor.py` + F2? | Yes — delivered exactly |

---

## 5. Open / Deferred

| Item | Target |
|------|--------|
| BR-K3: eSocial Tabela 03 rubric incidence codes verified | G1/D6 sign-off (Phase 6) |
| Consolidated CLT (art. 59/73 with amendments) re-fetched and cited | G1 |
| `labor.py` reads from content layer (already wired via `labor_rates(as_of)`) | Done |
| Vale-Transporte `vt_benefit` derived from Phase 4 VT election | Phase 6 |
| 13th salary, vacation, termination engines | Phase 7 |
| CCT floors / collective agreement premiums | Phase 8 |
| FGTS Digital deposit due dates (S13/S14/S15) | Phase 10 |

---

## 6. Files Changed (Backend)

**New**
- `engine/jurisdictions/brazil/bases.py` — pure rubric-incidence basis resolver
- `engine/jurisdictions/brazil/labor.py` — pure working-time rules
- `tests/fixtures/br_golden/F1_ordinary_monthly.json`
- `tests/fixtures/br_golden/F2_variable_components.json`
- `tests/fixtures/br_golden/F6_minimum_wage_floor.json`
- `tests/fixtures/br_golden/_F3_F4_F5_phase7_placeholders.json`

**Modified**
- `engine/countries/brazil.py` — rewritten `calculate()` with fail-closed, date-driven, rubric bases, alimony net, VT base
- `engine/countries/brazil_content.py` — added `BR_VT_RATE`, `BR_LABOR` rules & rows; accessors `vale_transporte_max_deduction_pct()`, `labor_rates()`; `ALL_SOURCE_CODES` extended with A5–A7
- `engine/base.py` — `brazil_inputs` doc updated; `br_alimony_deduction` in `PayrollResult`; `brazil_is_apprentice` deprecated
- `engine/standard.py` — `br_alimony_deduction` slot in total_deductions and result
- `hmrc_golden_harness.py` — `_brazil_context()`, `run_golden_case()` extracts `br_result`
- `alembic/versions/64424fd61652_br_employer_m2.py` — literal table names for migration-manifest check
- `alembic/versions/b9f3a7c2e5d1_br_employee_m3.py` — literal table names
- `alembic/MIGRATIONS_MANIFEST.txt` — regenerated
- `tests/test_brazil_phase2_engine.py` — `TestBrazilEngineIntegration` rewritten for real engine
- `tests/test_brazil_scaffolding.py` — blocking test updated for Phase 5
- `tests/test_brazil_router.py` — golden-check test expects PASS with 3 cases
- `docs/brazil/sources/SOURCES_MANIFEST.csv` — A5/A6/A7 added with sha256/bytes

---

## 7. Gate Status (Post-5b)

| Check | Result |
|-------|--------|
| `import app.main` | ✅ OK |
| Targeted BR pytest | ✅ 132 passed |
| `npm run check:undefined` | ✅ 515 files clean |
| `npm run build` | ✅ OK (5.3s) |
| `npm run lint` | Pre-existing warnings only |

---

## 8. Next Phase (Phase 6)

Phase 6 activates the Brazil tenant: `calc_inputs` hook resolves statutory profiles → context, `before_run_transition` approves runs, service registry transition to AVAILABLE after G1–G8. No new engine logic; integration work only.