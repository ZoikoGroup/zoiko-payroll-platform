# Belgium reviewer guide — AI-drafted 2026 content (Block E3)

Audience: the two internal reviewers and the Belgian payroll specialist. Workbook:
`docs/belgium/content/BE_2026_AI_DRAFT.xlsx` (every row of BE-PAYROLL-2026, proposed by AI on 2026-11-13 with
its source, retrieval date and confidence). Nothing in it is signed; the engine keeps blocking until humans sign.

## 1. Counts

| Confidence | Rows | Meaning |
|------------|------|---------|
| HIGH | 9 | the spec and an official source agree |
| MEDIUM | 36 | one source (mostly the spec alone) |
| LOW | 187 | inferred (180 of them are earning-class treatments) |
| NOT FOUND | 72 | left empty; where it should come from is stated |


## 1a. Review in this order (highest payroll impact first) — Block F4

1. **Withholding (Annex III)** — every be_wht_* row and the withholding rounding: all NOT FOUND; needs DOWNLOAD_LIST
   A1-A5 (three 2026 versions: 1 Jan, 1 Aug, 1 Nov). Without it no net pay exists.
2. **ONSS** — the HIGH rows (13.07 %, 8 % manual uplift, 1.60 % / 1.69 %, 8.86 %), the employer EC x WC bands (Band
   proposals sheet; B2 rate file), wage moderation (B4), fund contributions.
3. **BSSC** — the special social security contribution scale (B3).
4. **Work bonus** — social (B5) and fiscal (A2) work bonus.
5. **Holiday** — manual-worker contributions for the current holiday year (C1), white-collar double holiday 92 %,
   departure / additional holidays (C2).
6. **Absence** — guaranteed-salary days and manual-worker day bands (D1), maternity / birth leave (D2).
7. Then wages and working time (E1-E4), earning-class patterns (section 2.4), filing schemas (F1-F6), calendar
   rows, tolerances.

Sources to collect: `docs/belgium/sources/DOWNLOAD_LIST.md` (30 documents); save them unchanged in
`docs/belgium/sources/inbox/` and ask for the parse run (scripts/be_source_inbox.py + reviewed extraction).
Inbox at the last run (2026-11-13): 0 documents, so counts are unchanged.

## 2. Check these first

### 2.1 NOT FOUND (empty — must be supplied)

| Item | Where it should come from |
|------|---------------------------|
| `be_rounding_onss` | G-02: rounding rule per obligation - ONSS instructions do not publish a single rule; specialist. |
| `be_rounding_withholding` | G-02: Annex III (FPS Finance) rounding rules. |
| `be_rounding_holiday` | G-02: holiday-pay rounding - specialist / holiday fund (ONVA/RJV). |
| `be_bssc_pending` | G-06/G-17: special social security contribution scale - ONSS instructions 'cotisation speciale de securite sociale'. |
| `be_wht_applicability_rule` | Annex III AR/CIR 92 (FPS Finance) - needs a vocabulary before it can be signed. |
| `be_wht_nonresident_rule` | Annex III non-resident rules (FPS Finance). |
| `be_wht_taxable_basis_rule` | Annex III + G-26 allocation. |
| `be_wht_period_strategy` | Annex III period strategy (FPS Finance). |
| `be_wht_annex3_regular_scale` | Annex III 2026 formule-cle: three versions in 2026 (Jan, 1 Aug, 1 Nov per AR 27 Sep 2026); download the official key formula from FPS Finance (financien.belgium.be). |
| `be_wht_annex3_amendment_2026` | AR 24 Jul 2026 / AR 27 Sep 2026 amendments (Moniteur belge). |
| `be_wht_family_reductions` | Annex III family reductions (FPS Finance). |
| `be_wht_fiscal_work_bonus` | Annex III fiscal work bonus (63% for very low wages since 1 Aug 2026 per a secondary source; formula needed from FPS Finance). |
| `be_wht_exceptional_rule` | Annex III exceptional-remuneration scale (FPS Finance). |
| `be_wht_holiday_pay_rule` | Annex III holiday-pay withholding (FPS Finance). |
| `be_wht_arrears_rule` | Annex III arrears rule (FPS Finance). |
| `be_wht_overtime_rule` | Annex III overtime reduction (180 hours per a secondary source; formula from FPS Finance). |
| `be_onss_employee_base_rule` | Needs a vocabulary (rule text); ONSS 'notion de remuneration'. |
| `be_onss_manual_base_categories` | Needs a vocabulary; spec says 'MANUAL + assimilated'. |
| `be_onss_rate_file_quarter` | ONSS TechLib quarterly rate file (S2). |
| `be_onss_wage_moderation` | G-05: ONSS shows 5.67% for the OLD regime and a 2026 reform (programme law 30 May 2026); specialist to confirm the 2026 mechanism. |
| `be_onss_special_160_threshold_rule` | Needs a vocabulary; ONSS: average >= 10 workers in the reference period. |
| `be_onss_company_car` | G-15: CO2 solidarity contribution formula (ONSS). |
| `be_onss_fund_contributions` | Fund contributions per EC x WC (ONSS rate file). |
| `be_red_social_work_bonus` | ONSS work-bonus bands 2026 (S3 page lists the formula; amounts change 1 Apr / 1 Aug). |
| `be_red_structural` | ONSS structural reduction formula 2026. |
| `be_red_target_group` | ONSS target-group reductions. |
| `be_hol_wc_simple_rule` | Needs a vocabulary (rule text). |
| `be_hol_wc_double_contribution_rule` | Needs a vocabulary (rule text). |
| `be_hol_additional_rule` | Additional holidays formula (FPS Employment / ONVA). |
| `be_hol_departure_rule` | Departure holiday-pay formula (FPS Employment). |
| `be_wage_index_centime_rule` | Index-centime limitation formula (programme law 30 May 2026; G-10). |
| `be_ot_threshold_rule` | Needs a vocabulary (overtime threshold rule). |
| `be_ot_compensatory_rest_rule` | Compensatory rest formula (Labour Act 16 Mar 1971). |
| `be_abs_manual_day_bands` | G-07: manual-worker guaranteed-salary day bands (Employment Contracts Act art. 52). |
| `be_abs_manual_insurance_cap` | G-07: insurance cap (INAMI/RIZIV). |
| `be_public_holiday_substitution_rule` | Needs a vocabulary (substitution rule, AR 18 Apr 1974). |
| `be_bik_valuation_rules` | G-15: benefit-in-kind valuation (Art. 18 AR/CIR 92). |
| `be_meal_voucher_treatment` | G-15: meal-voucher conditions (needs a vocabulary). |
| `be_ecocheque_treatment` | G-15: ecocheque conditions (needs a vocabulary). |
| `be_filing_dimona_schema_versions` | G-31: Dimona XSD versions (ONSS TechLib). |
| `be_filing_finprof_schema_versions` | G-31: FinProf technical specification (FPS Finance). |
| `be_filing_belcotax_schema_versions` | G-31: Belcotax-on-web income-year XSD (FPS Finance). |
| `be_parallel_tolerance_gross` | Agreed with each design partner (spec §16); product + specialist. |
| `be_parallel_tolerance_withholding` | Agreed with each design partner (spec §16). |
| `be_parallel_tolerance_onss_employee` | Agreed with each design partner (spec §16). |
| `be_parallel_tolerance_work_bonus_social` | Agreed with each design partner (spec §16). |
| `be_parallel_tolerance_net` | Agreed with each design partner (spec §16). |
| `be_parallel_tolerance_employer_onss` | Agreed with each design partner (spec §16). |
| `be_onss_employer_base_rate (rows)` | Specialist to supply. |
| `calendar rows other than DmfA 2026Q3` | ONSS DmfA table for the other quarters; FinProf / Belcotax / advance / holiday-fund calendars (FPS Finance, ONSS) - G-32. |

### 2.2 LOW (inferred — verify before signing)

| Item | Proposed | What to check | Where |
|------|----------|---------------|-------|
| `be_supported_contract_types` | INDEFINITE, FIXED_TERM, SPECIFIC_WORK, REPLACEMENT | release-1 contract set (student / flexi / occasional / apprentice excluded) | spec §1; product |
| `be_onss_supported_employer_categories` | 000 | the launch employers' ONSS category | each employer's ONSS notice; ONSS rate file |
| `be_onss_supported_worker_codes` | 015, 495 | manual / white-collar worker codes in use | DmfA worker-code annex (Draft source D11) |
| `be_abs_maternity_multiple_weeks` | CHILDREN=2 -> 17 weeks, CHILDREN=3 -> 19 weeks | the per-child split (spec only says 17-19) | FPS Employment / INAMI-RIZIV |
| DmfA schema 2026/2 window start | 2026-07-01 | the production date of version 2026/2 | ONSS DmfA glossary version history |
| Earning classification (180 rows) | see the sheet; INCLUDED / EXCLUDED with a one-line reason each | every component x obligation, especially double / departure holiday pay, bonus vs regular withholding, benefit in kind, meal vouchers, ecocheques, profit sharing | ONSS instructions 'notion de remuneration'; Annex III (FPS Finance) |
| Employer band rows (Band proposals sheet) | EC=000 x WC=015/495 at 24.92% | to be added only after the EC / WC code lists are signed; reference-only rate | ONSS rate file per quarter |


### 2.4 Earning-class patterns (Block F4) — approve per pattern

The 180 earning-class cells form 8 patterns: components that share the same INCLUDED / EXCLUDED
treatment in all ten obligations. The workbook sheet **Patterns** lists each pattern's member cells (sheet!cell),
reason, source and a reviewerDecision column. Approve per pattern; in the console the Bulk sign panel's
"Earning-class patterns" list selects a pattern's pending cells in one click — each cell is still signed and
audited on its own, by a Super Admin who did not edit it (four-eyes unchanged).

| Pattern | Name | Components | INCLUDED in | Cells |
|---------|------|------------|-------------|-------|
| P01 | ecocheque, meal voucher employer, profit sharing, reimbursement | ECOCHEQUE, MEAL_VOUCHER_EMPLOYER, PROFIT_SHARING, REIMBURSEMENT | none | 40 |
| P02 | arrears, bonus, thirteenth month | ARREARS, BONUS, THIRTEENTH_MONTH | ONSS_EMPLOYEE, ONSS_EMPLOYER, ONSS_MANUAL_108, TAX_FICHE_281_10, WITHHOLDING_EXCEPTIONAL | 30 |
| P03 | benefit in kind, holiday pay simple | BENEFIT_IN_KIND, HOLIDAY_PAY_SIMPLE | ONSS_EMPLOYEE, ONSS_EMPLOYER, TAX_FICHE_281_10, WITHHOLDING_REGULAR | 20 |
| P04 | birth leave pay, guaranteed salary | BIRTH_LEAVE_PAY, GUARANTEED_SALARY | HOLIDAY_BASE, ONSS_EMPLOYEE, ONSS_EMPLOYER, ONSS_MANUAL_108, TAX_FICHE_281_10, WITHHOLDING_REGULAR | 20 |
| P05 | departure holiday pay, holiday pay double | DEPARTURE_HOLIDAY_PAY, HOLIDAY_PAY_DOUBLE | ONSS_EMPLOYEE, TAX_FICHE_281_10, WITHHOLDING_EXCEPTIONAL | 20 |
| P06 | Regular pay | HOURLY_PAY, SALARY | HOLIDAY_BASE, ONSS_EMPLOYEE, ONSS_EMPLOYER, ONSS_MANUAL_108, OVERTIME_BASE, SECTOR_MIN_WAGE, SICK_PAY_BASE, TAX_FICHE_281_10, WITHHOLDING_REGULAR | 20 |
| P07 | overtime premium, sunday holiday premium | OVERTIME_PREMIUM, SUNDAY_HOLIDAY_PREMIUM | ONSS_EMPLOYEE, ONSS_EMPLOYER, ONSS_MANUAL_108, TAX_FICHE_281_10, WITHHOLDING_REGULAR | 20 |
| P08 | sector premium | SECTOR_PREMIUM | HOLIDAY_BASE, ONSS_EMPLOYEE, ONSS_EMPLOYER, ONSS_MANUAL_108, SECTOR_MIN_WAGE, SICK_PAY_BASE, TAX_FICHE_281_10, WITHHOLDING_REGULAR | 10 |

### 2.3 Conflicts found

- `be_wage_rmmmg`: the spec proposes EUR 2,233.61 from 1 Jul 2026; Securex shows EUR 2,189.81 from 1 Apr 2026. Confirm every 2026 period with the National Labour Council (CCT 43) and split the row by effective date.
- `be_onss_special_160`: 1.60% (spec, ONSS) becomes 1.69% with the wage-moderation effect per the ONSS page. Decide which figure the row holds and whether wage moderation is a separate row (G-05).
- `be_hol_manual_annual_debit` 10.27%: the official page found is for an earlier holiday year.

## 3. Worked payslip examples (for comparison with an independent Belgian payroll calculator)

**Status after Block F4: all 10 examples are still PARTIAL** — withholding (Annex III), the work bonus and the BSSC are not sourced yet (inbox empty), so no example reaches full net pay. They are recomputed to full net pay by the parse run as soon as DOWNLOAD_LIST A1-A3, B3 and B5 are in the inbox and extracted.

Inputs are illustrative. Every rate is a DRAFTED value (confidence shown). Rounding: cent half-up as an
assumption (rounding is G-02, NOT FOUND). Withholding, the work bonus and the special social security
contribution are NOT drafted, so these examples stop at 'net before withholding and BSSC'. That is exactly
what the reviewer compares; the missing lines are the specialist's to supply.

### Example 1 — White-collar, low pay, no dependants

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 2300 | — |
| Gross pay | sum | 2300.00 | — |
| Employee ONSS | 2300 x 13.07% | 300.61 | 13.07% (HIGH) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 2300 - 300.61 | 1999.39 | — |
| Professional withholding (Annex III) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 1999.39 | not a net pay |
| Employer ONSS (reference only) | 2300 x 24.92% | 573.16 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 2300 x 1.60% | 36.80 | 1.60% (HIGH) |

### Example 2 — White-collar, median pay, no dependants

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Gross pay | sum | 3800.00 | — |
| Employee ONSS | 3800 x 13.07% | 496.66 | 13.07% (HIGH) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 3800 - 496.66 | 3303.34 | — |
| Professional withholding (Annex III) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 3303.34 | not a net pay |
| Employer ONSS (reference only) | 3800 x 24.92% | 946.96 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 3800 x 1.60% | 60.80 | 1.60% (HIGH) |

### Example 3 — White-collar, high pay, no dependants

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 6500 | — |
| Gross pay | sum | 6500.00 | — |
| Employee ONSS | 6500 x 13.07% | 849.55 | 13.07% (HIGH) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 6500 - 849.55 | 5650.45 | — |
| Professional withholding (Annex III) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 5650.45 | not a net pay |
| Employer ONSS (reference only) | 6500 x 24.92% | 1619.80 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 6500 x 1.60% | 104.00 | 1.60% (HIGH) |

### Example 4 — White-collar, median pay, 2 dependants

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Gross pay | sum | 3800.00 | — |
| Employee ONSS | 3800 x 13.07% | 496.66 | 13.07% (HIGH) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 3800 - 496.66 | 3303.34 | — |
| Professional withholding (Annex III) with 2 dependant(s) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 3303.34 | not a net pay |
| Employer ONSS (reference only) | 3800 x 24.92% | 946.96 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 3800 x 1.60% | 60.80 | 1.60% (HIGH) |

With 2 dependant(s) only the (undrafted) withholding line changes; every other line equals the same pay without dependants.

### Example 5 — Manual worker, low pay, no dependants

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 2300 | — |
| Gross pay | sum | 2300.00 | — |
| ONSS base (manual 108%) | 2300 x 108% | 2484.00 | uplift 8% (HIGH) |
| Employee ONSS | 2484.00 x 13.07% | 324.66 | 13.07% (HIGH) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 2300 - 324.66 | 1975.34 | — |
| Professional withholding (Annex III) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 1975.34 | not a net pay |
| Employer ONSS (reference only) | 2484.00 x 24.92% | 619.01 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 2484.00 x 1.60% | 39.74 | 1.60% (HIGH) |
| Holiday-fund contribution (quarterly, employer) | 2484.00 x 5.57% | 138.36 | 5.57% (MEDIUM) |

### Example 6 — Manual worker, median pay, no dependants

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3400 | — |
| Gross pay | sum | 3400.00 | — |
| ONSS base (manual 108%) | 3400 x 108% | 3672.00 | uplift 8% (HIGH) |
| Employee ONSS | 3672.00 x 13.07% | 479.93 | 13.07% (HIGH) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 3400 - 479.93 | 2920.07 | — |
| Professional withholding (Annex III) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 2920.07 | not a net pay |
| Employer ONSS (reference only) | 3672.00 x 24.92% | 915.06 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 3672.00 x 1.60% | 58.75 | 1.60% (HIGH) |
| Holiday-fund contribution (quarterly, employer) | 3672.00 x 5.57% | 204.53 | 5.57% (MEDIUM) |

### Example 7 — Manual worker, high pay, 1 dependant

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 5200 | — |
| Gross pay | sum | 5200.00 | — |
| ONSS base (manual 108%) | 5200 x 108% | 5616.00 | uplift 8% (HIGH) |
| Employee ONSS | 5616.00 x 13.07% | 734.01 | 13.07% (HIGH) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 5200 - 734.01 | 4465.99 | — |
| Professional withholding (Annex III) with 1 dependant(s) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 4465.99 | not a net pay |
| Employer ONSS (reference only) | 5616.00 x 24.92% | 1399.51 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 5616.00 x 1.60% | 89.86 | 1.60% (HIGH) |
| Holiday-fund contribution (quarterly, employer) | 5616.00 x 5.57% | 312.81 | 5.57% (MEDIUM) |

With 1 dependant(s) only the (undrafted) withholding line changes; every other line equals the same pay without dependants.

### Example 8 — White-collar, median pay, 6 h weekday overtime

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Hourly rate | 3800 x 3 / (13 x 38) (convention to confirm) | 23.08 | weekly hours 38 (MEDIUM) |
| Overtime (6 h at +50%) | 23.08 x 6 x 150% | 207.72 | premium 50% (MEDIUM) |
| Gross pay | sum | 4007.72 | — |
| Employee ONSS | 4007.72 x 13.07% | 523.81 | 13.07% (HIGH) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 4007.72 - 523.81 | 3483.91 | — |
| Professional withholding (Annex III) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 3483.91 | not a net pay |
| Employer ONSS (reference only) | 4007.72 x 24.92% | 998.72 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 4007.72 x 1.60% | 64.12 | 1.60% (HIGH) |

### Example 9 — Manual worker, median pay, 4 h Sunday overtime

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3400 | — |
| Hourly rate | 3400 x 3 / (13 x 38) (convention to confirm) | 20.65 | weekly hours 38 (MEDIUM) |
| Overtime (4 h at +100%) | 20.65 x 4 x 200% | 165.20 | premium 100% (MEDIUM) |
| Gross pay | sum | 3565.20 | — |
| ONSS base (manual 108%) | 3565.20 x 108% | 3850.42 | uplift 8% (HIGH) |
| Employee ONSS | 3850.42 x 13.07% | 503.25 | 13.07% (HIGH) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 3565.20 - 503.25 | 3061.95 | — |
| Professional withholding (Annex III) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 3061.95 | not a net pay |
| Employer ONSS (reference only) | 3850.42 x 24.92% | 959.52 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 3850.42 x 1.60% | 61.61 | 1.60% (HIGH) |
| Holiday-fund contribution (quarterly, employer) | 3850.42 x 5.57% | 214.47 | 5.57% (MEDIUM) |

### Example 10 — White-collar, median pay, double holiday pay month

| Line | Calculation | Amount (EUR) | Drafted value used (confidence) |
|------|-------------|--------------|---------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Double holiday pay | 3800 x 92% | 3496.00 | 92% (MEDIUM) |
| Gross pay | sum | 7296.00 | — |
| Employee ONSS | 3800 x 13.07% | 496.66 | 13.07% (HIGH) |
| Employee ONSS on double holiday pay | 3496.00 x 13.07% (class rule LOW) | 456.93 | HOLIDAY_PAY_DOUBLE x ONSS_EMPLOYEE INCLUDED (LOW) |
| Social work bonus (reduction) | NOT DRAFTED — be_red_social_work_bonus NOT FOUND | — | — |
| Amount before withholding (regular) | 3800 - 496.66 | 3303.34 | — |
| Professional withholding (Annex III) | NOT DRAFTED — Annex III scale / family reductions NOT FOUND | — | — |
| Withholding on double holiday pay (exceptional) | NOT DRAFTED — be_wht_holiday_pay_rule NOT FOUND | — | — |
| Special social security contribution | NOT DRAFTED — G-06 / G-17 | — | — |
| Net BEFORE withholding and BSSC | gross - employee ONSS | 6342.41 | not a net pay |
| Employer ONSS (reference only) | 3800 x 24.92% | 946.96 | 24.92% band proposal (MEDIUM; resolved by EC x WC) |
| Special contribution (only if >= 10 workers) | 3800 x 1.60% | 60.80 | 1.60% (HIGH) |

## 4. Review and sign — two internal reviewers

Roles: the **importer** (any Super Admin who imports the workbook) and two **reviewers / signers** who are
NOT the importer and did not edit the rows. The console refuses a signer who imported or edited a selected row.

1. Importer: Super Admin > Compliance > Belgium > Signing status > Import: upload `BE_2026_AI_DRAFT.xlsx`, reason
   "AI draft for review", **Dry run**, check 0 errors, **Confirm import**. Every imported row is PENDING.
2. Reviewer A (content): open the workbook; for each row check proposedValue against the source in
   sourceUrlOrSpec; for LOW / NOT FOUND follow section 2. Record corrections in a copy of the workbook.
3. Reviewer A: replace each draft source with the archived official document (upload the file, a different
   Super Admin reviews it) — signing needs a stored, hashed, reviewed source; the D01-D11 draft references are
   UNVERIFIED and can never be used to sign.
4. Importer: re-import the corrected workbook (dry run, then confirm). Rows stay PENDING.
5. Reviewer B (signer, not the importer, not an editor): Signing status > Bulk sign: select the rows reviewed
   in step 2, reason, Sign. Each row is signed and audited individually.
6. Neither reviewer approves or activates the pack: pack approval and activation are further four-eyes steps
   (an editor or signer of the version can never approve or activate it).

## 5. Golden certification — not satisfied by these examples

The examples in section 3 are self-generated from AI-drafted values. They do **NOT** satisfy the golden
certification of gate G1: that needs official or independently prepared authority examples (FPS Finance,
ONSS, a certified Belgian payroll provider) registered with their exact expected figures, replayed exactly and
recorded as a PASS certification run. No release gate is met by this draft.
