# Belgium reviewer guide — AI-drafted 2026 content (Block E3)

> **Employer base rate conflict — 24.92% (spec) vs 19.88% (2026/3 rate file, employer category 000) — requires a Belgian-payroll-literate reviewer to confirm which category applies to typical private-sector employers before signing. Do not resolve this by picking the number that matches the spec.**

Audience: the two internal reviewers and the Belgian payroll specialist. Workbook:
`docs/belgium/content/BE_2026_AI_DRAFT.xlsx` (every row of BE-PAYROLL-2026, proposed by AI on 2026-11-13 with
its source, retrieval date and confidence). Nothing in it is signed; the engine keeps blocking until humans sign.

## 1. Counts

Parse run 2026-11-16 (official ONSS documents B1, B2, B3, B5 archived; see section 1.1). Counted over every
importable row (Scalar keys, Parallel tolerances, Slab keys, Filing schema versions, Earning classification,
Calendar rows; 305 rows):

| Confidence | Before (2026-11-13) | After (2026-11-16) | Meaning |
|------------|--------------------:|-------------------:|---------|
| HIGH | 9 | 20 | an archived official 2026 document states the value (page section in reviewerNote) |
| MEDIUM | 34 | 33 | one source, or an official file that does not itself state the meaning |
| LOW | 187 | 185 | inferred (180 of them are earning-class treatments) |
| NOT FOUND | 71 | 63 | left empty; where it should come from is stated |
| (blank) | 4 | 4 | instruction / template lines |

Per section (Scalar + Slab key rows):

| Section | Before | After |
|---------|--------|-------|
| Withholding | NOT FOUND 19 | NOT FOUND 19 (A1-A3 not fetched: human check on finances.belgium.be / ejustice) |
| ONSS | HIGH 4, MEDIUM 1, LOW 2, NOT FOUND 11 | HIGH 11, MEDIUM 2, NOT FOUND 5 |
| BSSC | NOT FOUND 1 | HIGH 1 (scale on its proposal sheet; not importable — engine gap) |
| Work bonus | NOT FOUND 4 | HIGH 1 (social bonus tables on their proposal sheet; not importable — engine gap), NOT FOUND 3 (fiscal work bonus: A2) |
| Holiday | MEDIUM 4, NOT FOUND 7 | HIGH 2, MEDIUM 2, NOT FOUND 7 |
| Absence | MEDIUM 8, LOW 3, NOT FOUND 3, blank 1 | unchanged (no absence document in this run) |

Not imported (proposal sheets, HIGH, dated): 'Band proposals (post code list)' 22 rows (employer base 19.88 % and
two fund contributions per quarter, EC 000 x WC 015 / 495); 'BSSC scale 2026-3 (proposal)' 12 rows; 'Work bonus
2026-3 (proposal)' 31 rows. Three HIGH rows carry a proposed text that cannot be imported yet because the key has
no vocabulary (be_onss_employee_base_rule, be_onss_manual_base_categories, be_onss_special_160_threshold_rule).

### 1.1 Sources archived on 2026-11-16 (inbox → source artifacts)

| Item | File | Reference | Status |
|------|------|-----------|--------|
| B1 | B1_dmfa_2026-3_contributions.html | ZP-BE-SRC-4095714c43ce | ARCHIVED (official ONSS 2026/3) |
| B3 | B3_dmfa_2026-3_bssc_special_social_security_contribution.html | ZP-BE-SRC-6fa87a993e00 | ARCHIVED |
| B5 | B5_dmfa_2026-3_social_work_bonus.html | ZP-BE-SRC-b743a81a3b8c | ARCHIVED |
| B2 Q1-Q4 | B2_dmfa_rate_2026_{1..4}.zip (XML + XSD) | ZP-BE-SRC-91d403c48b7e / af557def6941 / e31183128f08 / 0f09ea196668 | ARCHIVED — extraction source |
| B2 Q1-Q4 | B2_tauxdmfa_2026_{1..4}_F.xlsm | ZP-BE-SRC-01ded63884c1 / 3059dfd7ef83 / a33b7c058e10 / 841e46913f68 | UNVERIFIED by rule (genuine ONSS files, used only for a read-only cross-check: sheet TB1 = XML, 0 differences in ~3,075 records per quarter; no macro run) |

In a shared environment a Super Admin registers these archived files BEFORE importing the workbook (the
workbook's 'Draft sources' sheet otherwise creates UNVERIFIED placeholders under the same references, which can
never be used to sign).

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
Inbox at the last run (2026-11-16): 11 files (B1, B2 x 8, B3, B5); A1-A3 still missing (FPS Finance and the Moniteur belge answer automated requests with a human-verification check — download them in a browser).

## 2. Check these first

### 2.1 NOT FOUND (empty — must be supplied)

| Item | Where it should come from |
|------|---------------------------|
| `be_rounding_onss` | G-02: rounding rule per obligation - ONSS instructions do not publish a single rule; specialist. |
| `be_rounding_withholding` | G-02: Annex III (FPS Finance) rounding rules. |
| `be_rounding_holiday` | G-02: holiday-pay rounding - specialist / holiday fund (ONVA/RJV). |
| `be_bssc_pending` | **SOURCED 2026-11-16 — see section 1 / 2.3:** B3 2026/3 scale on the 'BSSC scale 2026-3 (proposal)' sheet (HIGH); not importable until the engine gains a BSSC key (Block M1). |
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
| `be_onss_employee_base_rule` | **SOURCED 2026-11-16 — see section 1 / 2.3:** B1 states the rule (quarterly gross; 108 % for manual workers) — HIGH proposed text, still needs a vocabulary to import. |
| `be_onss_manual_base_categories` | **SOURCED 2026-11-16 — see section 1 / 2.3:** B1 states it (manual + assimilated under the private-sector holiday scheme; artists) — HIGH proposed text, needs a vocabulary. |
| `be_onss_rate_file_quarter` | **SOURCED 2026-11-16 — see section 1 / 2.3:** B2: 2026-10-01 (Q4 file; Q1-Q3 archived, identical rates for EC 000 x WC 015 / 495) — HIGH. |
| `be_onss_wage_moderation` | **SOURCED 2026-11-16 — see section 1 / 2.3:** B2 Q1-Q4: 5.12 % for EC 000 x WC 015 / 495 (B1: 4.27 + 19.88 x 0.0427) — HIGH; no 2026 change visible in the rate files. |
| `be_onss_special_160_threshold_rule` | **SOURCED 2026-11-16 — see section 1 / 2.3:** B1 states the rule (average >= 10 workers, reference period) — HIGH proposed text, needs a vocabulary. |
| `be_onss_company_car` | G-15: CO2 solidarity contribution formula (ONSS). |
| `be_onss_fund_contributions` | **SOURCED 2026-11-16 — see section 1 / 2.3:** B2: accident special 0.02 % (Q1-Q4) + asbestos fund 0.01 % (Q1-Q3) as dated band proposals — HIGH; closure fund (FFE) still NOT FOUND. |
| `be_red_social_work_bonus` | **SOURCED 2026-11-16 — see section 1 / 2.3:** B5 2026/3: dated tables (1 Jul, 1 Sep 2026) on the 'Work bonus 2026-3 (proposal)' sheet — HIGH; Jan-Jun 2026 NOT FOUND; engine gap. |
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
| `be_onss_employer_base_rate (rows)` | **SOURCED 2026-11-16 — see section 1 / 2.3:** B2: 19.88 % per quarter for EC 000 x WC 015 / 495 on 'Band proposals' — HIGH (needs the code lists signed first). |
| `calendar rows other than DmfA 2026Q3` | ONSS DmfA table for the other quarters; FinProf / Belcotax / advance / holiday-fund calendars (FPS Finance, ONSS) - G-32. |

### 2.2 LOW (inferred — verify before signing)

| Item | Proposed | What to check | Where |
|------|----------|---------------|-------|
| `be_supported_contract_types` | INDEFINITE, FIXED_TERM, SPECIFIC_WORK, REPLACEMENT | release-1 contract set (student / flexi / occasional / apprentice excluded) | spec §1; product |
| `be_onss_supported_employer_categories` | 000 | the launch employers' ONSS category | each employer's ONSS notice; ONSS rate file; B2 confirms EC 000 exists (MEDIUM: meaning not stated) |
| `be_onss_supported_worker_codes` | 015, 495 | manual / white-collar worker codes in use | DmfA worker-code annex (Draft source D11); B2 confirms both codes (MEDIUM: 015 combines with the ONVA holiday code) |
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

### 2.3 Conflicts and open points found

- `be_wage_rmmmg`: the spec proposes EUR 2,233.61 from 1 Jul 2026; Securex shows EUR 2,189.81 from 1 Apr 2026. Confirm every 2026 period with the National Labour Council (CCT 43) and split the row by effective date.
- `be_onss_employer_base_rate`: spec / B1 nominal private-sector rate **24.92 %** (B1 § 'Le pourcentage de cotisation globalisé') vs **19.88 %** applied by the B2 rate files Q1-Q4 for EC 000 x WC 015 / 495 (tax-shift, structural-reduction categories 1 and 3; B1 § 'Conséquence du tax-shift'). Both are cited; the dated band proposals use 19.88. Reviewer: confirm the launch employer's category.
- `be_onss_special_160`: RESOLVED by B1 + B2 code 855 — 1.60 % employer + 0.09 % wage moderation on it = 1.69 %. The row holds 1.60. **Engine gap:** the engine does not add the 0.09 %.
- `be_hol_manual_annual_debit` 10.27 %: RESOLVED — B1 2026/3 states 15.84 % = 5.57 % quarterly + 10.27 % annual debit.
- `be_onss_fund_contributions`: asbestos fund 0.01 % is due **Q1-Q3 2026 only** (B1 and B2 agree: absent from the Q4 file) — dated rows. The closure fund (FFE) is NOT sourced (TechLib FFE_2026.xls not fetched).
- `be_red_social_work_bonus`: the formula changes on **1 Jul 2026** and **1 Sep 2026** (B5); **January-June 2026 are not in the 2026/3 edition** (need 2026/1 and 2026/2). Two tables (employés / ouvriers), components A + B, S at 100 %, annual cap EUR 3,594.36 from 1 Jul 2026. **Engine gap:** one band key, no category dimension, read on the 108 % base for manual workers — kept on the proposal sheet (fail closed).
- BSSC (B3): the page gives quarterly brackets with percentages of the monthly pay; the guide reads the quarterly amount as 3x the monthly one (the page's monthly-practice figures 14.44 x 3 = 43.32 and 51.64 x 3 = 154.92 confirm it; brackets join within EUR 0.03). Household status (individual / joint with or without a working spouse) must be recorded per worker. **Engine gap:** no catalogue key holds a scale; the engine never computes BSSC (D7).
- `be_onss_supported_employer_categories`: importer defect **FIXED 2026-11-16** — codes were stored without leading zeros (`000` → `0`). Text columns now keep their exact characters, a numeric cell for a code list is refused (format the cell as Text), and a re-import repairs a mangled value. Verified on a local copy: stored `000`.

## 3. Worked payslip examples (for comparison with an independent Belgian payroll calculator)

**Status after the 2026-11-16 parse run: all 10 examples still STOP before withholding** — Annex III (A1-A3) is not
sourced, so no example reaches full net pay. Every line up to 'Net before withholding' now uses values sourced
from the archived ONSS documents: employee ONSS (B1), the social work bonus (B5), the BSSC (B3) and the employer
lines (B2 rate file Q3, B1).

Assumptions: pay month **September 2026** (Q3 rate file; work-bonus table 'from 1 September 2026'); full-time,
complete month (P = R); employer category 000, worker code 495 (white-collar) / 015 (manual); BSSC for
**individual taxation** (the household status is not given in the inputs — joint-taxation amounts differ, see the
BSSC sheet); employer with fewer than 10 workers (the 1.69 % line is shown separately); rounding cent half-up per
line (G-02 is NOT FOUND). The engine cannot yet apply the work bonus or the BSSC as shown here (engine gaps,
section 2.3) — these lines are what the reviewer and the future engine must reproduce. Employer cost is before the
structural reduction (B6 not sourced) and without the closure fund (FFE not sourced).

| Example | Work bonus | BSSC | Net before withholding | Employer ONSS (before reduction) | Stops at |
|---------|-----------:|-----:|-----------------------:|---------------------------------:|----------|
| 1 | 299.53 | 11.54 | 2287.38 | 575.69 | withholding (A1-A3) |
| 2 | 0.00 | 29.48 | 3273.86 | 951.14 | withholding (A1-A3) |
| 3 | 0.00 | 60.94 | 5589.51 | 1626.95 | withholding (A1-A3) |
| 4 | 0.00 | 29.48 | 3273.86 | 951.14 | withholding (A1-A3) |
| 5 | 323.49 | 13.56 | 2285.27 | 760.11 | withholding (A1-A3) |
| 6 | 1.06 | 26.63 | 2894.50 | 1123.63 | withholding (A1-A3) |
| 7 | 0.00 | 56.29 | 4409.70 | 1718.49 | withholding (A1-A3) |
| 8 | 0.00 | 36.50 | 3447.41 | 1003.13 | withholding (A1-A3) |
| 9 | 0.00 | 31.18 | 3030.77 | 1178.23 | withholding (A1-A3) |
| 10 | 0.00 | 29.48 | 6312.93 | 951.14 | withholding (A1-A3) |

### Example 1 — White-collar, low pay, no dependants

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 2300 | — |
| Gross pay | sum | 2300.00 | — |
| Employee ONSS | 2300.00 x 13.07% | 300.61 | 13.07% (HIGH, B1 + B2) |
| Social work bonus (reduction) | S = 2300.00 (100%): A 127.54 + B 171.99 | -299.53 | B5 table 'à partir du 1er septembre 2026', employés (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 300.61 - 299.53 | 1.08 | — |
| Special social security contribution (BSSC) | individual taxation, m = 2300.00: 30.99/3 + 1.10% x (2300 - 2190.18) | 11.54 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - BSSC | **2287.38** | not a net pay |
| Employer ONSS base | 2300.00 x 19.88% | 457.24 | EC 000 x WC 495 19.88% (HIGH, B2 Q3) |
| Wage moderation | 2300.00 x 5.12% | 117.76 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 2300.00 x 0.02% | 0.46 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 2300.00 x 0.01% | 0.23 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| **Employer ONSS before structural reduction** | sum | **575.69** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 2300.00 x 1.69% | 38.87 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

### Example 2 — White-collar, median pay, no dependants

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Gross pay | sum | 3800.00 | — |
| Employee ONSS | 3800.00 x 13.07% | 496.66 | 13.07% (HIGH, B1 + B2) |
| Social work bonus (reduction) | S = 3800.00 (100%): A 0.00 + B 0.00 | -0.00 | B5 table 'à partir du 1er septembre 2026', employés (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 496.66 - 0.00 | 496.66 | — |
| Special social security contribution (BSSC) | individual taxation, m = 3800.00: 82.05/3 + 3.38% x (3800 - 3737.00) | 29.48 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - BSSC | **3273.86** | not a net pay |
| Employer ONSS base | 3800.00 x 19.88% | 755.44 | EC 000 x WC 495 19.88% (HIGH, B2 Q3) |
| Wage moderation | 3800.00 x 5.12% | 194.56 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 3800.00 x 0.02% | 0.76 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 3800.00 x 0.01% | 0.38 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| **Employer ONSS before structural reduction** | sum | **951.14** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 3800.00 x 1.69% | 64.22 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

### Example 3 — White-collar, high pay, no dependants

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 6500 | — |
| Gross pay | sum | 6500.00 | — |
| Employee ONSS | 6500.00 x 13.07% | 849.55 | 13.07% (HIGH, B1 + B2) |
| Social work bonus (reduction) | S = 6500.00 (100%): A 0.00 + B 0.00 | -0.00 | B5 table 'à partir du 1er septembre 2026', employés (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 849.55 - 0.00 | 849.55 | — |
| Special social security contribution (BSSC) | individual taxation, m = 6500.00: 182.82/3 (top bracket) | 60.94 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - BSSC | **5589.51** | not a net pay |
| Employer ONSS base | 6500.00 x 19.88% | 1292.20 | EC 000 x WC 495 19.88% (HIGH, B2 Q3) |
| Wage moderation | 6500.00 x 5.12% | 332.80 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 6500.00 x 0.02% | 1.30 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 6500.00 x 0.01% | 0.65 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| **Employer ONSS before structural reduction** | sum | **1626.95** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 6500.00 x 1.69% | 109.85 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

### Example 4 — White-collar, median pay, 2 dependants

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Gross pay | sum | 3800.00 | — |
| Employee ONSS | 3800.00 x 13.07% | 496.66 | 13.07% (HIGH, B1 + B2) |
| Social work bonus (reduction) | S = 3800.00 (100%): A 0.00 + B 0.00 | -0.00 | B5 table 'à partir du 1er septembre 2026', employés (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 496.66 - 0.00 | 496.66 | — |
| Special social security contribution (BSSC) | individual taxation, m = 3800.00: 82.05/3 + 3.38% x (3800 - 3737.00) | 29.48 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - BSSC | **3273.86** | not a net pay |
| Employer ONSS base | 3800.00 x 19.88% | 755.44 | EC 000 x WC 495 19.88% (HIGH, B2 Q3) |
| Wage moderation | 3800.00 x 5.12% | 194.56 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 3800.00 x 0.02% | 0.76 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 3800.00 x 0.01% | 0.38 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| **Employer ONSS before structural reduction** | sum | **951.14** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 3800.00 x 1.69% | 64.22 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

### Example 5 — Manual worker, low pay, no dependants

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 2300 | — |
| Gross pay | sum | 2300.00 | — |
| ONSS base (manual 108%) | 2300.00 x 108% | 2484.00 | uplift 8% (HIGH, B1) |
| Employee ONSS | 2484.00 x 13.07% | 324.66 | 13.07% (HIGH, B1 + B2) |
| Social work bonus (reduction) | S = 2300.00 (100%): A 137.74 + B 185.75 | -323.49 | B5 table 'à partir du 1er septembre 2026', ouvriers (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 324.66 - 323.49 | 1.17 | — |
| Special social security contribution (BSSC) | individual taxation, m = 2484.00: 30.99/3 + 1.10% x (2484.00 - 2190.18) | 13.56 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - BSSC | **2285.27** | not a net pay |
| Employer ONSS base | 2484.00 x 19.88% | 493.82 | EC 000 x WC 015 19.88% (HIGH, B2 Q3) |
| Wage moderation | 2484.00 x 5.12% | 127.18 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 2484.00 x 0.02% | 0.50 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 2484.00 x 0.01% | 0.25 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| Holiday-fund contribution (quarterly, employer) | 2484.00 x 5.57% | 138.36 | 5.57% (HIGH, B1 + B2 code 253) |
| **Employer ONSS before structural reduction** | sum | **760.11** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 2484.00 x 1.69% | 41.98 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

### Example 6 — Manual worker, median pay, no dependants

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3400 | — |
| Gross pay | sum | 3400.00 | — |
| ONSS base (manual 108%) | 3400.00 x 108% | 3672.00 | uplift 8% (HIGH, B1) |
| Employee ONSS | 3672.00 x 13.07% | 479.93 | 13.07% (HIGH, B1 + B2) |
| Social work bonus (reduction) | S = 3400.00 (100%): A 1.06 + B 0.00 | -1.06 | B5 table 'à partir du 1er septembre 2026', ouvriers (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 479.93 - 1.06 | 478.87 | — |
| Special social security contribution (BSSC) | individual taxation, m = 3672.00: 30.99/3 + 1.10% x (3672.00 - 2190.18) | 26.63 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - BSSC | **2894.50** | not a net pay |
| Employer ONSS base | 3672.00 x 19.88% | 729.99 | EC 000 x WC 015 19.88% (HIGH, B2 Q3) |
| Wage moderation | 3672.00 x 5.12% | 188.01 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 3672.00 x 0.02% | 0.73 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 3672.00 x 0.01% | 0.37 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| Holiday-fund contribution (quarterly, employer) | 3672.00 x 5.57% | 204.53 | 5.57% (HIGH, B1 + B2 code 253) |
| **Employer ONSS before structural reduction** | sum | **1123.63** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 3672.00 x 1.69% | 62.05 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

### Example 7 — Manual worker, high pay, 1 dependant

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 5200 | — |
| Gross pay | sum | 5200.00 | — |
| ONSS base (manual 108%) | 5200.00 x 108% | 5616.00 | uplift 8% (HIGH, B1) |
| Employee ONSS | 5616.00 x 13.07% | 734.01 | 13.07% (HIGH, B1 + B2) |
| Social work bonus (reduction) | S = 5200.00 (100%): A 0.00 + B 0.00 | -0.00 | B5 table 'à partir du 1er septembre 2026', ouvriers (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 734.01 - 0.00 | 734.01 | — |
| Special social security contribution (BSSC) | individual taxation, m = 5616.00: 118.83/3 + 1.10% x (5616.00 - 4100.00) | 56.29 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - BSSC | **4409.70** | not a net pay |
| Employer ONSS base | 5616.00 x 19.88% | 1116.46 | EC 000 x WC 015 19.88% (HIGH, B2 Q3) |
| Wage moderation | 5616.00 x 5.12% | 287.54 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 5616.00 x 0.02% | 1.12 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 5616.00 x 0.01% | 0.56 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| Holiday-fund contribution (quarterly, employer) | 5616.00 x 5.57% | 312.81 | 5.57% (HIGH, B1 + B2 code 253) |
| **Employer ONSS before structural reduction** | sum | **1718.49** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 5616.00 x 1.69% | 94.91 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

### Example 8 — White-collar, median pay, 6 h weekday overtime

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Overtime (6 h at +50%) | 23.08 x 6 x 150% | 207.72 | premium 50% (MEDIUM) |
| Gross pay | sum | 4007.72 | — |
| Employee ONSS | 4007.72 x 13.07% | 523.81 | 13.07% (HIGH, B1 + B2) |
| Social work bonus (reduction) | S = 4007.72 (100%): A 0.00 + B 0.00 | -0.00 | B5 table 'à partir du 1er septembre 2026', employés (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 523.81 - 0.00 | 523.81 | — |
| Special social security contribution (BSSC) | individual taxation, m = 4007.72: 82.05/3 + 3.38% x (4007.72 - 3737.00) | 36.50 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - BSSC | **3447.41** | not a net pay |
| Employer ONSS base | 4007.72 x 19.88% | 796.73 | EC 000 x WC 495 19.88% (HIGH, B2 Q3) |
| Wage moderation | 4007.72 x 5.12% | 205.20 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 4007.72 x 0.02% | 0.80 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 4007.72 x 0.01% | 0.40 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| **Employer ONSS before structural reduction** | sum | **1003.13** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 4007.72 x 1.69% | 67.73 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

### Example 9 — Manual worker, median pay, 4 h Sunday overtime

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3400 | — |
| Overtime (4 h at +100%) | 20.65 x 4 x 200% | 165.20 | premium 100% (MEDIUM) |
| Gross pay | sum | 3565.20 | — |
| ONSS base (manual 108%) | 3565.20 x 108% | 3850.42 | uplift 8% (HIGH, B1) |
| Employee ONSS | 3850.42 x 13.07% | 503.25 | 13.07% (HIGH, B1 + B2) |
| Social work bonus (reduction) | S = 3565.20 (100%): A 0.00 + B 0.00 | -0.00 | B5 table 'à partir du 1er septembre 2026', ouvriers (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 503.25 - 0.00 | 503.25 | — |
| Special social security contribution (BSSC) | individual taxation, m = 3850.42: 82.05/3 + 3.38% x (3850.42 - 3737.00) | 31.18 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - BSSC | **3030.77** | not a net pay |
| Employer ONSS base | 3850.42 x 19.88% | 765.46 | EC 000 x WC 015 19.88% (HIGH, B2 Q3) |
| Wage moderation | 3850.42 x 5.12% | 197.14 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 3850.42 x 0.02% | 0.77 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 3850.42 x 0.01% | 0.39 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| Holiday-fund contribution (quarterly, employer) | 3850.42 x 5.57% | 214.47 | 5.57% (HIGH, B1 + B2 code 253) |
| **Employer ONSS before structural reduction** | sum | **1178.23** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 3850.42 x 1.69% | 65.08 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

### Example 10 — White-collar, median pay, double holiday pay month

| Line | Calculation | Amount (EUR) | Value used (confidence, source) |
|------|-------------|--------------|----------------------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Double holiday pay | 3800 x 92% | 3496.00 | 92% (MEDIUM) |
| Gross pay | sum | 7296.00 | — |
| Employee ONSS | 3800.00 x 13.07% | 496.66 | 13.07% (HIGH, B1 + B2) |
| Employee ONSS on double holiday pay | 3496.00 x 13.07% (class rule LOW) | 456.93 | HOLIDAY_PAY_DOUBLE x ONSS_EMPLOYEE INCLUDED (LOW, not sourced in this run) |
| Social work bonus (reduction) | S = 3800.00 (100%): A 0.00 + B 0.00 | -0.00 | B5 table 'à partir du 1er septembre 2026', employés (HIGH) — engine cannot apply it yet |
| Employee ONSS after the bonus | 496.66 - 0.00 | 496.66 | — |
| Special social security contribution (BSSC) | individual taxation, m = 3800.00: 82.05/3 + 3.38% x (3800 - 3737.00) | 29.48 | B3 2026/3 scale (HIGH; quarterly / 3, interpretation flagged) — engine cannot apply it yet |
| Professional withholding (Annex III) | **STOP — NOT SOURCED** (DOWNLOAD_LIST A1-A3 behind the FPS Finance / Moniteur belge human check) | — | — |
| Withholding on double holiday pay (exceptional) | **STOP — NOT SOURCED** (A1-A4) | — | — |
| Fiscal work bonus (inside withholding) | **STOP — NOT SOURCED** (A2) | — | — |
| **Net before withholding** | gross - employee ONSS after bonus - ONSS on double holiday pay - BSSC | **6312.93** | not a net pay |
| Employer ONSS base | 3800.00 x 19.88% | 755.44 | EC 000 x WC 495 19.88% (HIGH, B2 Q3) |
| Wage moderation | 3800.00 x 5.12% | 194.56 | 5.12% (HIGH, B2 Q3; B1 4.27 + 19.88 x 0.0427) |
| Work-accident special contribution | 3800.00 x 0.02% | 0.76 | code 255 (HIGH, B2 Q3 + B1) |
| Asbestos fund | 3800.00 x 0.01% | 0.38 | code 256, Q1-Q3 2026 only (HIGH, B2 Q3 + B1) |
| **Employer ONSS before structural reduction** | sum | **951.14** | structural reduction NOT sourced (B6) |
| Only if >= 10 workers: 1.60% + wage moderation 0.09% | 3800.00 x 1.69% | 64.22 | B1 + B2 code 855 (HIGH) — the engine omits the 0.09% |
| Closure fund (FFE) | not sourced (TechLib FFE_2026.xls not fetched) | — | — |

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
