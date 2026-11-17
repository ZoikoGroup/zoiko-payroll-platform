# Belgium specialist pack (ZP-BE-ENG-001)

Audience: the Belgian payroll specialist (and the Super Admin who enters / signs content). Generated from
`backend/app/modules/payroll/engine/countries/belgium_content.py` (Block D4). Every item below is seeded
`[PENDING G1]` with no value; the engine blocks with a named reason until it is signed. Spec-proposed figures
appear only as labels and are never used by the engine.

How to deliver: Super Admin > Compliance > Belgium > Signing status > **Export workbook**; fill the value
columns with a source document per row; **Import** (dry run first, then confirm) — the import never signs;
a second Super Admin who did not import or edit the rows **bulk-signs** them with reviewed, archived sources.

## 1. Catalogue items (83 keys)

### Scope, Policy & Rounding — gate G1

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_supported_pay_frequencies` (Supported pay frequencies) | text-choice | BE-004, G-11 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) — subset of MONTHLY, SEMI_MONTHLY, FORTNIGHTLY, WEEKLY |  | Scalar keys |
| `be_supported_pay_bases` (Supported pay bases (salaried / hourly)) | text-choice | BE-004 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) — subset of SALARIED, HOURLY |  | Scalar keys |
| `be_supported_worker_categories` (Supported worker categories) | text-choice | BE-002, D6, §1 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) — subset of MANUAL, EMPLOYEE, APPRENTICE, STUDENT, FLEXI, OCCASIONAL, OTHER | MANUAL,EMPLOYEE (special regimes blocked) | Scalar keys |
| `be_supported_contract_types` (Supported contract types) | text-choice | BE-002, BE-004 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) — subset of INDEFINITE, FIXED_TERM, SPECIFIC_WORK, REPLACEMENT, STUDENT, FLEXI, OCCASIONAL, APPRENTICESHIP |  | Scalar keys |
| `be_rounding_onss` (ONSS rounding rule) | text-choice | D8, G-02, G-19 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) — one of CENT_HALF_UP, CENT_DOWN, EURO_HALF_UP, EURO_DOWN |  | Scalar keys |
| `be_rounding_withholding` (Professional withholding rounding rule) | text-choice | D8, G-02, G-19 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) — one of CENT_HALF_UP, CENT_DOWN, EURO_HALF_UP, EURO_DOWN |  | Scalar keys |
| `be_rounding_holiday` (Holiday pay rounding rule) | text-choice | D8, G-02, G-19 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) — one of CENT_HALF_UP, CENT_DOWN, EURO_HALF_UP, EURO_DOWN |  | Scalar keys |
| `be_bssc_pending` (Special social security contribution (awaiting specialist)) | text-choice | G-06 / G-17 (no spec ID) | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |

### Professional Withholding (Annex III) — gate G1

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_wht_applicability_rule` (Withholding applicability) | text-choice | §5 stage 1 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_wht_nonresident_rule` (Non-resident withholding treatment) | text-choice | §5 stage 1 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_wht_taxable_basis_rule` (Withholding taxable basis) | text-choice | §5 stage 2, BE-007 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_wht_period_strategy` (Withholding period strategy) | text-choice | §5 stage 3 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_wht_annex3_regular_scale` (Annex III regular withholding scale) | band | §5 stage 4, BE-010, S20 | sign SLAB_ROWS + supply the band rows; row fields minAmount |  | Scalar keys (marker) + Slab keys (rows) |
| `be_wht_annex3_amendment_2026` (Annex III amendments (RD 24 Jul 2026)) | formula | §5 stage 7, §3, S21 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_wht_family_reductions` (Family / reduction layer) | band | §5 stage 5 | sign SLAB_ROWS + supply the band rows; row fields minAmount |  | Scalar keys (marker) + Slab keys (rows) |
| `be_wht_fiscal_work_bonus` (Fiscal work bonus) | formula | §5 stage 7, BE-012 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_wht_exceptional_rule` (Exceptional remuneration withholding) | band | §5 stage 6, BE-011 | sign SLAB_ROWS + supply the band rows; row fields minAmount |  | Scalar keys (marker) + Slab keys (rows) |
| `be_wht_holiday_pay_rule` (Holiday pay withholding) | formula | §5 stage 6, BE-011 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_wht_arrears_rule` (Arrears withholding) | formula | BE-009, BE-011 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_wht_overtime_rule` (Overtime withholding changes) | formula | §5 stage 7 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |

### ONSS/RSZ Employee — gate G1

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_onss_employee_rate` (Employee ordinary ONSS contribution) | rate | §3, §6 | sign the rate (employee / employer %) | 13.07% ordinary | Scalar keys |
| `be_onss_employee_base_rule` (Employee ONSS base rule) | text-choice | BE-007 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_onss_manual_base_uplift` (Manual-worker base uplift) | rate | §3, BE-016, S1 | sign the rate (employee / employer %) | 108% (gross + 8%) | Scalar keys |
| `be_onss_manual_base_categories` (Categories on the manual-worker base) | text-choice | BE-016 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) | MANUAL + assimilated | Scalar keys |

### ONSS/RSZ Employer (reference; by employer/worker code) — gate G1

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_onss_supported_employer_categories` (Supported ONSS employer categories) | text-choice | BE-015, §2 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_onss_supported_worker_codes` (Supported ONSS worker codes) | text-choice | BE-015, §2 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_onss_rate_file_quarter` (ONSS rate file quarter) | date | BE-015, S2 | sign the date |  | Scalar keys |
| `be_onss_employer_base_rate` (Employer base) | band | §3, §6, BE-015 | sign SLAB_ROWS + supply the band rows; row fields minAmount; dimension EC=...;WC=... (reference only; resolved by employer category / worker code) | 24.92% globalised base | Scalar keys (marker) + Slab keys (rows) |
| `be_onss_wage_moderation` (Wage moderation contribution) | rate | §6, G-05 | sign the rate (employee / employer %) (reference only; resolved by employer category / worker code) |  | Scalar keys |
| `be_onss_special_160` (Special (workforce-size test)) | rate | §6 | sign the rate (employee / employer %) (reference only; resolved by employer category / worker code) | 1.60% | Scalar keys |
| `be_onss_special_160_threshold_rule` (Special contribution workforce test) | text-choice | §6, G-05 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_onss_pension_special` (Occupational pension special) | rate | §6 | sign the rate (employee / employer %) (reference only; resolved by employer category / worker code) | 8.86% | Scalar keys |
| `be_onss_company_car` (Company car contribution) | formula | §6, G-15 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_onss_fund_contributions` (Fund contributions) | band | §6, G-05 | sign SLAB_ROWS + supply the band rows; row fields minAmount; dimension EC=...;WC=... (reference only; resolved by employer category / worker code) |  | Scalar keys (marker) + Slab keys (rows) |

### Reductions — gate G1

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_red_social_work_bonus` (Social work bonus) | band | §6, BE-012, S24 | sign SLAB_ROWS + supply the band rows; row fields minAmount |  | Scalar keys (marker) + Slab keys (rows) |
| `be_red_structural` (Structural reduction) | formula | §6 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_red_target_group` (Target-group reductions) | band | §6 | sign SLAB_ROWS + supply the band rows; row fields minAmount |  | Scalar keys (marker) + Slab keys (rows) |

### Annual Holiday Pay — gate G1

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_hol_entitlement_weeks` (Holiday entitlement (weeks)) | amount | §8, S13 | sign the amount | 4 weeks max | Scalar keys |
| `be_hol_wc_simple_rule` (White-collar simple holiday pay) | text-choice | §8 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_hol_wc_double_pct` (White-collar double holiday pay) | rate | §8, S15 | sign the rate (employee / employer %) | 92% of monthly wage | Scalar keys |
| `be_hol_wc_double_contribution_rule` (Double holiday pay contribution rule) | text-choice | §8, S15 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_hol_additional_rule` (Additional holidays) | formula | BE-026 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_hol_departure_rule` (Departure holiday pay) | formula | §8, BE-027 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_hol_manual_quarterly_contribution` (Manual-worker holiday contribution (quarterly)) | rate | §3, §6, §8, S14 | sign the rate (employee / employer %) | 5.57% quarterly | Scalar keys |
| `be_hol_manual_annual_debit` (Manual-worker holiday contribution (annual debit)) | rate | §3, §8, S14 | sign the rate (employee / employer %) | 10.27% annual debit | Scalar keys |

### Wages, RMMMG & Indexation — gate G1 (and G2 for sector floors)

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_wage_rmmmg` (RMMMG fallback (monthly)) | amount | §3, §7, S8 | sign the amount | EUR 2,233.61 from 1 Jul 2026 | Scalar keys |
| `be_wage_rmmmg_min_age` (RMMMG minimum age) | amount | §3 | sign the amount | 18 | Scalar keys |
| `be_wage_index_centime_threshold` (Index-centime reference threshold) | amount | §3, §7, S10 | sign the amount | EUR 4,000 from 1 Jun 2026 | Scalar keys |
| `be_wage_index_centime_rule` (Index-centime limitation rule) | formula | §7, G-10 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_wage_norm_margin` (Wage-norm margin (warning only)) | rate | §3, §7, S11 | sign the rate (employee / employer %) | 0% (2025-2026) | Scalar keys |

### Working Time & Overtime — gate G1 (and G2)

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_wt_daily_limit_hours` (Daily working-time limit (hours)) | amount | §7, S12 | sign the amount | 8 | Scalar keys |
| `be_wt_weekly_limit_hours` (Weekly working-time limit (hours)) | amount | §7, S12 | sign the amount | 40 | Scalar keys |
| `be_wt_weekly_reduced_hours` (Reduced weekly hours) | amount | §7, S12 | sign the amount | 38 | Scalar keys |
| `be_ot_threshold_rule` (Overtime threshold rule) | text-choice | BE-022 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_ot_premium_weekday` (Overtime premium, weekday / Saturday) | rate | §7 | sign the rate (employee / employer %) | 50% | Scalar keys |
| `be_ot_premium_sunday_holiday` (Overtime premium, Sunday / public holiday) | rate | §7 | sign the rate (employee / employer %) | 100% | Scalar keys |
| `be_ot_compensatory_rest_rule` (Compensatory rest rule) | formula | §7 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |

### Absence & Guaranteed Salary — gate G1

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_abs_wc_guaranteed_days` (White-collar guaranteed salary days) | amount | §9, S16 | sign the amount | 30 days | Scalar keys |
| `be_abs_wc_guaranteed_pct` (White-collar guaranteed salary rate) | rate | §9, S16 | sign the rate (employee / employer %) | 100% | Scalar keys |
| `be_abs_wc_min_contract_months` (Guaranteed salary contract condition) | amount | §9, S16 | sign the amount | indefinite or >= 3 months | Scalar keys |
| `be_abs_manual_day_bands` (Manual-worker guaranteed salary day bands) | band | §9, G-07 | sign SLAB_ROWS + supply the band rows; row fields minAmount |  | Scalar keys (marker) + Slab keys (rows) |
| `be_abs_manual_insurance_cap` (Manual-worker insurance cap) | amount | §9, G-07 | sign the amount |  | Scalar keys |
| `be_abs_relapse_window_weeks` (Relapse window (weeks)) | amount | §3, BE-030, S16 | sign the amount | 8 weeks (from 1 Jan 2026) | Scalar keys |
| `be_abs_maternity_weeks` (Maternity leave (weeks)) | amount | §9, S17 | sign the amount | 15 weeks | Scalar keys |
| `be_abs_maternity_multiple_weeks` (Maternity, multiple birth (by children)) | band | §9, S17 | sign SLAB_ROWS + supply the band rows; row fields minAmount; dimension CHILDREN=... | 17-19 weeks (multiple birth) | Scalar keys (marker) + Slab keys (rows) |
| `be_abs_birth_leave_days` (Birth leave (days)) | amount | §9, S18 | sign the amount | 20 days | Scalar keys |
| `be_abs_birth_leave_window_months` (Birth leave window (months)) | amount | §9, S18 | sign the amount | 4 months | Scalar keys |
| `be_abs_birth_leave_employer_days` (Birth leave employer-paid days) | amount | §9, S18 | sign the amount | 3 days | Scalar keys |

### Public Holidays — gate G1

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_public_holidays` (Public holidays) | table | BE-023, §8, G-09 | sign SLAB_ROWS + supply the dated rows; row fields date, name | ten statutory holidays; dates none in spec (G-09) | Scalar keys (marker) + Slab keys (rows) |
| `be_public_holiday_substitution_rule` (Public holiday substitution) | text-choice | BE-023, G-09 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |

### Earning Classification — gate G1

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_bik_valuation_rules` (Benefit-in-kind valuation) | formula | BE-008, G-15 | sign SLAB_ROWS + supply the formula (restricted grammar); row fields formulaText, name |  | Scalar keys (marker) + Slab keys (rows) |
| `be_meal_voucher_treatment` (Meal voucher treatment) | text-choice | BE-008, G-15 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |
| `be_ecocheque_treatment` (Ecocheque treatment) | text-choice | BE-008, G-15 | choose and sign a value from the vocabulary (or NOT_SUPPORTED) |  | Scalar keys |

### Authority Filing Schemas — gate G1 + G3

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_filing_dimona_schema_versions` (Dimona schema versions) | schema-version | §10, BE-033, G-08 | sign SLAB_ROWS + one row per schema version and submission window; row fields name, effectiveFrom |  | Filing schema versions (marker on Scalar keys) |
| `be_filing_dmfa_schema_versions` (DmfA schema versions) | schema-version | §10, BE-034, G-08 | sign SLAB_ROWS + one row per schema version and submission window; row fields name, effectiveFrom | 2026/2 to 30 Sep, 2026/3 from 1 Oct | Filing schema versions (marker on Scalar keys) |
| `be_filing_finprof_schema_versions` (FinProf schema versions) | schema-version | §10, G-08 | sign SLAB_ROWS + one row per schema version and submission window; row fields name, effectiveFrom |  | Filing schema versions (marker on Scalar keys) |
| `be_filing_belcotax_schema_versions` (Belcotax fiche schema versions) | schema-version | §10, BE-014, G-08 | sign SLAB_ROWS + one row per schema version and submission window; row fields name, effectiveFrom |  | Filing schema versions (marker on Scalar keys) |

### Parallel-Run Tolerances — gate G4

| Key | Kind | Spec reference | What is needed | Spec-proposed (label only) | Workbook sheet |
|-----|------|----------------|----------------|-----------------------------|----------------|
| `be_parallel_tolerance_gross` (Parallel-run tolerance: gross (EUR)) | amount | §16, G4 | sign the amount |  | Parallel tolerances |
| `be_parallel_tolerance_withholding` (Parallel-run tolerance: withholding (EUR)) | amount | §16, G4 | sign the amount |  | Parallel tolerances |
| `be_parallel_tolerance_onss_employee` (Parallel-run tolerance: employee ONSS (EUR)) | amount | §16, G4 | sign the amount |  | Parallel tolerances |
| `be_parallel_tolerance_work_bonus_social` (Parallel-run tolerance: social work bonus (EUR)) | amount | §16, G4 | sign the amount |  | Parallel tolerances |
| `be_parallel_tolerance_net` (Parallel-run tolerance: net pay (EUR)) | amount | §16, G4 | sign the amount |  | Parallel tolerances |
| `be_parallel_tolerance_employer_onss` (Parallel-run tolerance: employer contributions (EUR)) | amount | §16, G4 | sign the amount |  | Parallel tolerances |

## 2. Other content

| Item | What is needed | Workbook sheet / place | Gate |
|------|----------------|------------------------|------|
| Earning classification | treatment INCLUDED / EXCLUDED for each of 18 components x 10 obligations (180 rows, all REVIEW today) | Earning classification | G1 |
| ONSS employer codes | the supported employer categories and worker codes (code lists) and the employer base / fund band rows per EC x WC | Scalar keys + Slab keys | G1 |
| Public holidays | the dated BE_PUBLIC_HOLIDAY rows per year (G-09) | Slab keys | G1 |
| Authority worked examples | official / independent examples with exact expected figures, registered with their case (`G=..;EC=..;WC=..;JC=.. => wht=..;onssEe=..;net=..`) for the golden certification | Super Admin > Belgium > Overview (golden certification) | G1 |
| Joint Committee packs | per launch employer: the Joint Committee / sub-committee agreement (BE-PC-<committee>[-<sub>]-<version>) with wage scales (function class, seniority, regime, minimums) and any overtime override | Super Admin > Belgium > Joint Committees | G2 |
| Parallel-run tolerances | agreed rounding tolerance per concept (unsigned = exact) | Parallel tolerances | G4 |
| Calendar rows | operational due dates with their source (with the authority team) | Calendar rows | G5 |

## 3. Open owner decisions

| Decision | Question | Unblocks |
|----------|----------|----------|
| G-01 | Confirm the consolidated calculation order (plan §8). | G1 |
| G-02 | Rounding rule per obligation (ONSS, withholding, holiday): be_rounding_* rows (G-19). | G1 |
| G-06 / G-17 | Special social security contribution (BSSC): method and content (today every payslip carries the BE_BSSC_PENDING exception that must be acknowledged). | G1 |
| G-11 | Pay-frequency scope of the release (be_supported_pay_frequencies). | G1 / G2 |
| G-12 | Which changes are high-risk and need four-eyes beyond those already enforced. | G6 |
| G-13 | Legal language of employment documents (nl / fr / de). | G6 / G7 |
| G-16 | Formats and check digits of KBO/BCE, ONSS and NISS (today format only). | G6 |
| G-21 | Statutory retention periods for payroll / social documents (employee deletion stays blocked). | G6 |
| G-26 | How employee ONSS is allocated between the regular and exceptional withholding bases (be_wht_taxable_basis_rule). | G1 |
| G-30 | Confirm the professional-withholding declaration frequencies supported (engineering default: MONTHLY / QUARTERLY). | G5 |

Each decision is recorded as a reviewed source artifact tagged `BE-DECISION-<key>` (uploader != reviewer);
the Overview lists their state.

## 4. Blocking questions for the specialist — professional withholding (added 2026-11-16)

**All four questions — SQ-WHT-1, SQ-WHT-2, SQ-WHT-3, SQ-WHT-4 — have the SAME priority: blocking.** Each blocks the
withholding engine (M-WHT) and the signing of the withholding rows at gate G1; none is secondary, and the later
numbering only reflects when the source was read (SQ-WHT-3 / 4 came from the A2 / A3 decrees on 2026-11-17). Answer
each as a decision record (Super Admin > Belgium > Decision records; proposer ≠ decider).

| Question | Priority | Blocks |
|---|---|---|
| SQ-WHT-1 — BSSC and the withholding base | BLOCKING (G1) | the withholding base of every payslip |
| SQ-WHT-2 — G-26 ONSS split regular / exceptional | BLOCKING (G1) | every month with regular + exceptional pay |
| SQ-WHT-3 — retroactive 180 h overtime limit; 29°/1 exception | BLOCKING (G1) | **operational:** whether any January-July 2026 payroll run (B10's 130 h) needs a retroactive correction, and how the yearly overtime hours are counted from 1 Jan |
| SQ-WHT-4 — age-based marital-quotient cap; study-grant spouse | BLOCKING (G1) | every married employee's withholding from 1 Nov 2026; new household inputs (ZP-PRIV) |

### SQ-WHT-1 — Is the BSSC deducted before or after calculating the withholding base?

- **The ambiguity.** B10 (Annex III to the Royal Decree of 11 Dec 2025, n° 25.1) and B11 (Formule-clé
  ESS-SR/2025-0928, n° 7) define the withholding base as the gross pay minus *"les retenues effectuées en exécution
  de la législation sociale ou d'un statut légal ou réglementaire y assimilé"* — neither mentions the special social
  security contribution (BSSC, Loi du 30 mars 1994). B3 (ONSS administrative instructions 2026/3, cotisation
  spéciale pour la sécurité sociale) says the BSSC is withheld *after* the personal social security contributions
  and the professional withholding — an order of deduction, not a definition of the withholding base.
- **The choice:**
  - **(a) BSSC NOT deducted** — the base is gross − employee ONSS (after the social work bonus); the BSSC is
    withheld afterwards from the net. (The assumption used in the reviewer guide's worked examples.)
  - **(b) BSSC deducted** — the base is gross − employee ONSS − BSSC.
- **What it changes** (reviewer guide §3.0, Assumption 3): withholding lower by about 5-33 EUR a month in the
  worked examples under (b).
- **Please cite** the provision or administrative guidance the answer rests on.

### SQ-WHT-2 — G-26: how is employee ONSS allocated between regular and exceptional pay?

- **Already in the pack** as decision G-26 (§3 above, key `be_wht_taxable_basis_rule`). Repeated here because it
  decides the base of every withholding line.
- **The ambiguity.** B10 n° 25.1 deducts the social withholdings from the gross pay, and n° 53 applies the
  exceptional rates to the allowance itself; neither says how the employee ONSS of a month that holds both regular and
  exceptional pay (e.g. a double holiday pay or bonus month) is split between the two bases.
- **The choice:**
  - **(a) Pro rata** to the ONSS-liable amount of each part (what the engine does today: `_allocate`).
  - **(b) Each part's own ONSS** computed separately on its own component (e.g. ONSS on the double holiday pay
    deducted only from that allowance's base).
  - **(c) Another rule** the specialist specifies, with its source.
- **What it changes:** the split of the month's withholding between the regular scale and the exceptional rate, and
  so the total withholding in every mixed month (worked example 10).

### SQ-WHT-3 — Overtime: the retroactive 180 h limit and the new exception (added 2026-11-17)

- **Priority: BLOCKING, same tier as SQ-WHT-1 / SQ-WHT-2.** This is an operational question, not only a data one:
  until it is answered nobody can say whether a January-July 2026 payroll run that applied B10's 130 h limit needs a
  retroactive correction (hours 131-180 already worked before publication on 30 Jul 2026).

- **The text.** A2 (B12, Royal Decree 24 Jul 2026, published 30 Jul 2026) art. 2 replaces Annex III n° 45.2: the
  overtime reduction applies to the premium base of the first **180 h** a year for all sectors (B10: 130 h; 360 h
  hotel; 280 h road / rail works), **with effect from 1 Jan 2026** (art. 7). Art. 3 adds art. 38 § 1, first
  paragraph, **29°/1** CIR 92 to the n° 45.3 exception (no reduction), with effect from 1 Apr 2026.
- **The questions:**
  - **(a)** Payslips paid between 1 Jan and 30 Jul 2026 applied B10's 130 h. Must the employer regularise
    hours 131-180 already worked (e.g. on the next payslip, or only through the annual tax assessment), or does
    the retroactive limit only matter for hours counted after publication?
  - **(b)** What overtime falls under art. 38 § 1 29°/1 CIR 92 (the CIR 92 text is not in our sources), and how is
    it identified on the payslip so the reduction is not applied?
- **What it changes:** whether the engine counts the yearly hours from 1 Jan with 180 h, and whether it needs a
  regularisation line; whether an overtime component needs a 29°/1 flag.
- **Please cite** the provision or FPS Finance guidance.

### SQ-WHT-4 — Marital quotient and 'single' status from 1 Nov 2026 (added 2026-11-17)

- **Priority: BLOCKING, same tier as SQ-WHT-1 / SQ-WHT-2** (every married employee's withholding from 1 Nov 2026).

- **The text.** A3 (B13, Royal Decree 27 Sep 2026, pay from 1 Nov 2026) art. 3: the income imputed to the spouse is
  capped at **12,790 when both spouses have reached 66 on 1 Jan 2027**, otherwise — *"ook wanneer de schuldenaar van
  de bedrijfsvoorheffing niet over de nodige informatie beschikt"* — at **11,780**. Art. 1: a married employee is
  treated as single when the spouse has more than 11,550 a year of treaty-exempt income or of a **study grant** that
  builds social-security rights but is not taxed.
- **The questions:**
  - **(a)** Which document may the employer rely on for the spouses' ages and the study-grant income (the employee's
    declaration, as for the other family data)? Is the employer obliged to ask, or only to apply the lower cap when
    the information is missing?
  - **(b)** From which date does a declared change take effect (n° 5: the situation on 1 January, with the n° 5.2
    exceptions)?
- **What it changes:** two new household fields (spouse date of birth or an 'both 66 on 1 Jan 2027' flag; spouse
  study-grant income above the threshold), a default when missing, and the ZP-PRIV note on household data. The
  marital-quotient withholding can RISE from 1 Nov (reviewer guide §3.0a: Example 3 +18.90).
- **Please cite** the provision or FPS Finance guidance.
