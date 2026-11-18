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
| Withholding | NOT FOUND 19 | after the A1 run (2026-11-16, B10 + B11): **HIGH 8, NOT FOUND 11** — be_rounding_withholding CENT_HALF_UP importable; scale, family reductions, exceptional / holiday pay and overtime on the 'Annex III 2026 (proposal)' sheet (engine gap M-WHT); period strategy and taxable basis as proposed text (no vocabulary yet). After the A2 / A3 run (2026-11-17, B12 + B13): **HIGH 9, NOT FOUND 10** — be_wht_annex3_amendment_2026 sourced; dated rows (1 Jan / 1 Aug / 1 Nov) on the 'Annex III 2026 (proposal)' sheet |
| ONSS | HIGH 4, MEDIUM 1, LOW 2, NOT FOUND 11 | HIGH 11, MEDIUM 2, NOT FOUND 5 |
| BSSC | NOT FOUND 1 | HIGH 1 (scale on its proposal sheet; not importable — engine gap) |
| Work bonus | NOT FOUND 4 | HIGH 2 (social bonus tables, B5; fiscal work bonus 33.14 % A + 52.54 % B from 1 Jan 2026, B10 n° 46, component B 63 % from 1 Aug 2026, A2 art. 4 — both on proposal sheets, engine gaps), NOT FOUND 2 |
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

| B10 (A1) | 6482239b-fcca-4596-96eb-b9749bc296ea.pdf | ZP-BE-SRC-b7c7d3af3469 | ARCHIVED — Annex III to the Royal Decree of 11 Dec 2025, withholding on income paid from 1 Jan 2026 (official, 44 p.) |
| B11 (A1) | 919cc022-3014-4263-a479-4c4add557859.pdf | ZP-BE-SRC-fca893502b97 | ARCHIVED — FPS Finance Formule-clé ESS-SR/2025-0928, from 1 Jan 2026 (official, 31 p.); all 35 regular-pay figures identical to B10 |
| B12 (A2) | Belgisch StaatsbladA2.pdf | ZP-BE-SRC-49b8cd3adf38 | ARCHIVED 2026-11-17 — Royal Decree 24 Jul 2026 (numac 2026005690, published 30 Jul 2026); NL, browser print of the official gazette page, 4 p. |
| B13 (A3) | Belgisch StaatsbladA3.pdf | ZP-BE-SRC-f894796781f3 | ARCHIVED 2026-11-17 — Royal Decree 27 Sep 2026 (numac 2026007167, published 2 Oct 2026; pay from 1 Nov 2026); NL with bilingual tables, 7 p. |

In a shared environment a Super Admin registers these archived files BEFORE importing the workbook (the
workbook's 'Draft sources' sheet otherwise creates UNVERIFIED placeholders under the same references, which can
never be used to sign).

## 1a. Review in this order (highest payroll impact first) — Block F4

1. **Withholding (Annex III)** — every be_wht_* row and the withholding rounding: the three 2026 versions are sourced
   (1 Jan B10 / B11, 1 Aug A2 = B12, 1 Nov A3 = B13) on the 'Annex III 2026 (proposal)' sheet; engine gap M-WHT.
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
Inbox at the last run (2026-11-17): 16 files (B1, B2 x 8, B3, B5, B9, B10, B11, B12 = A2, B13 = A3); the FPS Finance key formulas for pay from 1 Aug / 1 Nov 2026 and A4 / A5 still missing (FPS Finance and the Moniteur belge answer automated requests with a human-verification check — download them in a browser).

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
| `be_wht_annex3_regular_scale` | **SOURCED — B10 / B11 (1 Jan), A3 = B13 (1 Nov):** dated rows on the 'Annex III 2026 (proposal)' sheet (HIGH); scale unchanged all year; engine gap M-WHT. Key formulas for 1 Aug / 1 Nov not archived. |
| `be_wht_annex3_amendment_2026` | **SOURCED 2026-11-17 — A2 = B12, A3 = B13** (HIGH; see 2.3). |
| `be_wht_family_reductions` | Annex III family reductions (FPS Finance). |
| `be_wht_fiscal_work_bonus` | **SOURCED — B10 (to 31 Jul) and A2 art. 4 (from 1 Aug: component B 63 %, CONFIRMED):** proposal sheet; engine gaps M-WHT / M-WORKBONUS. |
| `be_wht_exceptional_rule` | Annex III exceptional-remuneration scale (FPS Finance). |
| `be_wht_holiday_pay_rule` | Annex III holiday-pay withholding (FPS Finance). |
| `be_wht_arrears_rule` | Annex III arrears rule (FPS Finance). |
| `be_wht_overtime_rule` | **SOURCED — B10 n° 45 + A2 arts 2-3:** 180 h from 1 Jan 2026 (retroactive), wider exception from 1 Apr 2026; SQ-WHT-3 open. |
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

- **Withholding (A1, B10 / B11) from 1 Jan 2026; amended by A2 (B12) and A3 (B13) — parse run 2026-11-17.**
  - *Fiscal work bonus:* the rumoured **63 % is confirmed — for component B only** (A2 art. 4, n° 46.2.2, from
    1 Aug 2026); component A stays 33.14 %.
  - *Scale / bands:* **the scale (n° 31) is not amended by either decree**; professional expenses (n° 28), the
    n° 53 exceptional rates and the n° 55 reductions are unchanged too. A3 sets **new values** (not date
    extensions) from 1 Nov 2026: exempt amount 11,550 (its tax 3,089.63, was 2,987.98), marital-quotient cap
    11,780 / 12,790 (was 13,790), 6,179.26 (was 5,975.96), a new children table (1: 684; 2-8 LOWER than B10, e.g.
    1,644 vs 1,656; + 3,780 per child above 8), 648 / 636 for the other family charges (was 624), the n° 54
    exemption limits, and the 'single' threshold of n° 4.2 (11,550, was 13,790). Arithmetic checks pass
    (11,550 × 26.75 % = 3,089.63; 2 × 3,089.63 = 6,179.26; caps ÷ 30 % = the printed reach amounts).
  - *Method:* the five steps are unchanged. A2 changes one percentage and the overtime hour limits. A3 adds **two new
    conditions**: the marital-quotient cap depends on **both spouses having reached 66 on 1 Jan 2027** (the lower
    cap applies when the payer lacks the information), and a spouse's **study-grant income** above 11,550 makes the
    employee 'single' (n° 4.2). Both are new household inputs (SQ-WHT-4; the ZP-PRIV note must cover them).
  - *Retroactivity:* A2 art. 2 (overtime 180 h) has effect **from 1 Jan 2026** although published on 30 Jul 2026;
    art. 3 from 1 Apr 2026 (SQ-WHT-3). A3 is not retroactive (pay from 1 Nov 2026; not for n° 80 / Part 5 income).
  - *Not archived:* the FPS Finance key formulas for pay from 1 Aug / 1 Nov 2026 — the A2 / A3 rows rest on the
    decree text alone (B11 gave the 1 Jan rows an independent cross-check).
- **Engine gap M-WHT:** withholding.py applies one band to the monthly taxable pay; Annex III annualises, deducts
  flat-rate professional expenses, applies the annual scale, subtracts the exempt-amount tax (or the marital quotient)
  and the annual family reductions, divides by 12, then applies the other reductions (overtime, fiscal work bonus
  split A / B). The figures stay on the proposal sheet until the engine follows the five steps of B11.
- `be_wht_taxable_basis_rule`, `be_wht_period_strategy`: stated by B10 (n° 25.1, 26, 42) but no vocabulary exists to
  import them. G-26 (ONSS allocation between regular and exceptional bases) is not settled by the text.

## 3. Worked payslip examples (for comparison with an independent Belgian payroll calculator)

> **⚠ These 10 examples are manually calculated from the sourced formula for cross-check purposes. The engine cannot
> yet compute withholding (M-WHT, M-WORKBONUS, M-BSSC still open). Do not treat these as system-verified output.**

**Scope:** all 10 reach full net pay for **July 2026**, the one month in which every archived source applies: Annex III
and the Formule-clé from 1 Jan 2026 (B10 / B11, before the 1 Aug amendment A2), the work-bonus table 'juillet et août
2026' (B5), the Q3 2026 ONSS rates (B1 / B2) and the BSSC scale (B3). A2 / A3 are now sourced (B12 / B13):
the July figures do not change — see 3.0a.

### 3.0 Assumptions — each one changes the figures if it is wrong

**⚑ ASSUMPTION 1 — every worker is single, or married / cohabiting with a spouse who has own professional income**
(B10 n° 32: scale tax − 2,987.98). *If wrong* — the spouse has no professional income (or only a pension up to
174 EUR net / month, n° 33) — the marital quotient applies (n° 34: 30 % of the net base imputed to the spouse, max
13,790; − 5,975.96) and the withholding falls sharply: Example 1 162.32 → 0.00, Example 2 742.98 → 341.14,
Example 3 1,920.76 → 1,378.20, Example 7 1,250.80 → 755.88 (net pay + 160 to + 545 EUR a month). Spouse incomes up to
290 / 579 EUR net a month add the n° 40 reductions. The household status must be recorded per worker.

**⚑ ASSUMPTION 2 — "dependants" in the inputs are dependent CHILDREN** (B10 n° 38: 1 → 624, 2 → 1,656 a year).
*If wrong* — they are other dependants under art. 136 2°-4° CIR 92 (n° 39: 624 each, 1,992 for a dependant aged 66+
in dependency) — Example 4's withholding rises 604.98 → 638.98 (2 × 624 = 1,248 instead of 1,656); Example 7 (one
dependant, 624 either way) is unchanged. A disabled dependant counts double (n° 8) and changes both.

**⚑ ASSUMPTION 3 — the BSSC is NOT deducted from the withholding base — UNCONFIRMED.** Neither B10 nor B11
mentions the BSSC at all. Both define the base as gross minus *"retenues effectuées en exécution de la législation
sociale"* (B10 n° 25.1, B11 n° 7) without saying whether the BSSC (Loi du 30 mars 1994) is one of them. The only
basis for the assumption is B3 (ONSS), which says the BSSC is withheld *after* the personal contributions and the
withholding — an order of deduction, not a definition of the base. *If wrong* (BSSC deducted from the base), the
withholding falls: Example 1 162.32 → 157.38, Example 2 742.98 → 728.79, Example 3 1,920.76 → 1,888.15, Example 7
1,250.80 → 1,223.70 (net + 5 to + 33 EUR a month). **Needs the Belgian specialist's confirmation.**

**⚑ ASSUMPTION 4 — the overtime in Examples 8 and 9 is eligible legal overtime** (a legal premium under art. 29 of
the Labour Act of 16 March 1971, within the first **180 h** of the year — A2 art. 2, with effect from 1 Jan 2026, replacing
B10's 130 h — and not overtime under art. 38 § 1 29°/1 or 30° CIR 92 (A2 art. 3, from 1 Apr 2026); B10 n° 45: reduction of
57.75 % of the social gross base of the premium hours). *If wrong* (not eligible, or beyond the yearly hour limit), there is no reduction:
the withholding rises by 79.97 (Example 8) and 47.70 (Example 9).

### 3.0a The 2026 amendments A2 / A3 and these July examples (checked 2026-11-17)

**The July 2026 figures above do not change.** A2 (B12, Royal Decree 24 Jul 2026) and A3 (B13, Royal Decree 27 Sep
2026) were read article by article against B10 / B11:

| Decree article | In force | Touches the July examples? |
|---|---|---|
| A2 art. 4 — fiscal work bonus component B 52.54 % → **63 %** | 1 Aug 2026 | **No** (after July). Examples 1 and 5 would get a larger reduction from August. |
| A2 art. 2 — overtime limit **180 h** for all sectors (B10: 130 h) | **retroactive to 1 Jan 2026** | **Assumption 4's wording only** (130 → 180 h). 6 h and 4 h are within either limit, so Examples 8 / 9 are unchanged — unless the worker already had 130-180 h of overtime in 2026, where A2 now GIVES the reduction B10 refused. |
| A2 art. 3 — no reduction for overtime under art. 38 § 1 29°/1 CIR 92 too (B10: 30° only) | 1 Apr 2026 | **Assumption 4 extended**: the overtime must not qualify under 29°/1 or 30° (what 29°/1 covers is not in our sources — SQ-WHT-3). |
| A2 arts 1, 5, 6 (maintenance payments, leefloon, young sportspeople) | various | No — not employee pay in scope. |
| A3 arts 1-9 (exempt amount, marital quotient, family reductions, n° 54) | 1 Nov 2026 | **No** (after July). |

**Overtime check, stated explicitly (Examples 8 and 9).** The overtime hours were checked against BOTH yearly limits:
Example 8 has 6 h and Example 9 has 4 h, each the only overtime of the year in the example's inputs. Both are within
the **old 130 h limit** (B10 n° 45.2, as published) AND within the **new 180 h limit** (A2 art. 2, retroactive to
1 Jan 2026). The overtime reduction (−79.97 and −47.70) is therefore due in full under either limit, and the July
figures are the same whichever limit is taken to have applied in July 2026. The retroactive change could only matter
for a worker whose cumulative 2026 overtime before or in July passed 130 h (SQ-WHT-3) — not the case in these examples.

Decree-only effect on the SAME payslips (July inputs kept: Q3 ONSS, the July-August work-bonus table, BSSC; a real
August / November payslip also changes with the 1 Sep work-bonus table and the Q4 rates):

| Example | Withholding July (B10) | A2 rules (from 1 Aug) | A2 + A3 rules (from 1 Nov) |
|---|---:|---:|---:|
| 1 | 162.32 | 144.33 (−17.99) | 135.86 (−26.46) |
| 2 | 742.98 | 742.98 | 734.51 (−8.47) |
| 3 | 1,920.76 | 1,920.76 | 1,912.29 (−8.47) |
| 4 | 604.98 | 604.98 | 597.51 (−7.47) |
| 5 | 151.67 | 132.24 (−19.43) | 123.77 (−27.90) |
| 6 | 560.80 | 560.80 | 552.33 (−8.47) |
| 7 | 1,250.80 | 1,250.80 | 1,237.33 (−13.47) |
| 8 | 749.96 | 749.96 | 741.49 (−8.47) |
| 9 | 579.06 | 579.06 | 570.58 (−8.48) |
| 10 (regular part) | 742.98 | 742.98 | 734.51 (−8.47) |

The −8.47 is the higher exempt amount (3,089.63 − 2,987.98 = 101.65 a year / 12). Example 4 gains less (2 children:
1,644 from 1 Nov instead of 1,656). Example 10's holiday-pay withholding is unchanged (n° 53 not amended).

Assumption 1 variant (marital quotient) from 1 Nov is **not** a uniform fall: the cap drops from 13,790 to 11,780
(12,790 only if BOTH spouses are 66 on 1 Jan 2027): Example 2 341.14 → 324.20, Example 3 1,378.20 → 1,397.10
(**+18.90**), Example 7 755.88 → 769.78 (+13.90); Example 1 stays 0.00. With both spouses 66: 324.20 / 1,379.09 /
751.77.

Other conventions (not assumptions about the law): full-time complete month; employer category 000, worker codes
495 / 015; employer with fewer than 10 workers (no 1.60 %); BSSC for individual taxation (B3); rounding cent half-up at
every step (B10 n° 12); double holiday pay ONSS share from the LOW earning-class rule.

| Example | Gross | Employee ONSS (after bonus) | Withholding | BSSC | Net pay |
|---------|------:|----------------------------:|------------:|-----:|--------:|
| 1 | 2300.00 | 1.08 | 162.32 | 11.54 | **2125.06** |
| 2 | 3800.00 | 496.66 | 742.98 | 29.48 | **2530.88** |
| 3 | 6500.00 | 849.55 | 1920.76 | 60.94 | **3668.75** |
| 4 | 3800.00 | 496.66 | 604.98 | 29.48 | **2668.88** |
| 5 | 2300.00 | 1.17 | 151.67 | 13.56 | **2133.60** |
| 6 | 3400.00 | 479.93 | 560.80 | 26.63 | **2332.64** |
| 7 | 5200.00 | 734.01 | 1250.80 | 56.29 | **3158.90** |
| 8 | 4007.72 | 523.81 | 749.96 | 36.50 | **2697.45** |
| 9 | 3565.20 | 503.25 | 579.06 | 31.18 | **2451.71** |
| 10 | 7296.00 | 953.59 | 2031.24 | 29.48 | **4281.69** |


### Example 1 — White-collar, low pay, no dependants

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 2300 | — |
| Gross pay | sum | 2300.00 | — |
| Employee ONSS | 2300.00 x 13.07% | 300.61 | B1 + B2 (HIGH) |
| Social work bonus | S = 2300.00: A 127.54 + B 171.99 | -299.53 | B5 'juillet et août 2026', employés (HIGH) |
| Employee ONSS after the bonus | 300.61 - 299.53 | 1.08 | — |
| Withholding: annual gross base | (2300.00 - 1.08) x 12 | 27587.04 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 27587.04 - 6070.00 | 21517.04 | — |
| Scale tax | B10 n° 31 on 21517.04 | 6527.34 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 6527.34 - 2,987.98 | 3539.36 | B10 n° 32 (HIGH) |
| Monthly withholding before other reductions | 3539.36 / 12 | 294.95 | B10 n° 42 / B11 n° 16 (HIGH) |
| Fiscal work bonus | 33.14% x 127.54 + 52.54% x 171.99 | -132.63 | B10 n° 46.2 / B11 n° 20 (HIGH) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **162.32** | — |
| Special social security contribution | individual taxation, m = 2300.00: 30.99/3 + 1.10% x (2300 - 2190.18) | 11.54 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - withholding - BSSC | **2125.06** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 % of 2300.00 | 575.69 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

### Example 2 — White-collar, median pay, no dependants

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Gross pay | sum | 3800.00 | — |
| Employee ONSS | 3800.00 x 13.07% | 496.66 | B1 + B2 (HIGH) |
| Social work bonus | S = 3800.00: A 0.00 + B 0.00 | -0.00 | B5 'juillet et août 2026', employés (HIGH) |
| Employee ONSS after the bonus | 496.66 - 0.00 | 496.66 | — |
| Withholding: annual gross base | (3800.00 - 496.66) x 12 | 39640.08 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 39640.08 - 6070.00 | 33570.08 | — |
| Scale tax | B10 n° 31 on 33570.08 | 11903.79 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 11903.79 - 2,987.98 | 8915.81 | B10 n° 32 (HIGH) |
| Monthly withholding before other reductions | 8915.81 / 12 | 742.98 | B10 n° 42 / B11 n° 16 (HIGH) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **742.98** | — |
| Special social security contribution | individual taxation, m = 3800.00: 82.05/3 + 3.38% x (3800 - 3737.00) | 29.48 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - withholding - BSSC | **2530.88** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 % of 3800.00 | 951.14 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

### Example 3 — White-collar, high pay, no dependants

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 6500 | — |
| Gross pay | sum | 6500.00 | — |
| Employee ONSS | 6500.00 x 13.07% | 849.55 | B1 + B2 (HIGH) |
| Social work bonus | S = 6500.00: A 0.00 + B 0.00 | -0.00 | B5 'juillet et août 2026', employés (HIGH) |
| Employee ONSS after the bonus | 849.55 - 0.00 | 849.55 | — |
| Withholding: annual gross base | (6500.00 - 849.55) x 12 | 67805.40 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 67805.40 - 6070.00 | 61735.40 | — |
| Scale tax | B10 n° 31 on 61735.40 | 26037.07 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 26037.07 - 2,987.98 | 23049.09 | B10 n° 32 (HIGH) |
| Monthly withholding before other reductions | 23049.09 / 12 | 1920.76 | B10 n° 42 / B11 n° 16 (HIGH) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **1920.76** | — |
| Special social security contribution | individual taxation, m = 6500.00: 182.82/3 (top bracket) | 60.94 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - withholding - BSSC | **3668.75** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 % of 6500.00 | 1626.95 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

### Example 4 — White-collar, median pay, 2 dependants

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Gross pay | sum | 3800.00 | — |
| Employee ONSS | 3800.00 x 13.07% | 496.66 | B1 + B2 (HIGH) |
| Social work bonus | S = 3800.00: A 0.00 + B 0.00 | -0.00 | B5 'juillet et août 2026', employés (HIGH) |
| Employee ONSS after the bonus | 496.66 - 0.00 | 496.66 | — |
| Withholding: annual gross base | (3800.00 - 496.66) x 12 | 39640.08 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 39640.08 - 6070.00 | 33570.08 | — |
| Scale tax | B10 n° 31 on 33570.08 | 11903.79 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 11903.79 - 2,987.98 | 8915.81 | B10 n° 32 (HIGH) |
| Children reduction (2 children) | annual | -1656 | B10 n° 38 (HIGH) |
| Monthly withholding before other reductions | 7259.81 / 12 | 604.98 | B10 n° 42 / B11 n° 16 (HIGH) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **604.98** | — |
| Special social security contribution | individual taxation, m = 3800.00: 82.05/3 + 3.38% x (3800 - 3737.00) | 29.48 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - withholding - BSSC | **2668.88** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 % of 3800.00 | 951.14 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

### Example 5 — Manual worker, low pay, no dependants

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 2300 | — |
| Gross pay | sum | 2300.00 | — |
| ONSS base (manual 108%) | 2300.00 x 108% | 2484.00 | B1 (HIGH) |
| Employee ONSS | 2484.00 x 13.07% | 324.66 | B1 + B2 (HIGH) |
| Social work bonus | S = 2300.00: A 137.74 + B 185.75 | -323.49 | B5 'juillet et août 2026', ouvriers (HIGH) |
| Employee ONSS after the bonus | 324.66 - 323.49 | 1.17 | — |
| Withholding: annual gross base | (2300.00 - 1.17) x 12 | 27585.96 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 27585.96 - 6070.00 | 21515.96 | — |
| Scale tax | B10 n° 31 on 21515.96 | 6526.88 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 6526.88 - 2,987.98 | 3538.90 | B10 n° 32 (HIGH) |
| Monthly withholding before other reductions | 3538.90 / 12 | 294.91 | B10 n° 42 / B11 n° 16 (HIGH) |
| Fiscal work bonus | 33.14% x 137.74 + 52.54% x 185.75 | -143.24 | B10 n° 46.2 / B11 n° 20 (HIGH) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **151.67** | — |
| Special social security contribution | individual taxation, m = 2484.00: 30.99/3 + 1.10% x (2484.00 - 2190.18) | 13.56 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - withholding - BSSC | **2133.60** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 + 5.57 holiday % of 2484.00 | 760.11 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

### Example 6 — Manual worker, median pay, no dependants

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 3400 | — |
| Gross pay | sum | 3400.00 | — |
| ONSS base (manual 108%) | 3400.00 x 108% | 3672.00 | B1 (HIGH) |
| Employee ONSS | 3672.00 x 13.07% | 479.93 | B1 + B2 (HIGH) |
| Social work bonus | S = 3400.00: A 0.00 + B 0.00 | -0.00 | B5 'juillet et août 2026', ouvriers (HIGH) |
| Employee ONSS after the bonus | 479.93 - 0.00 | 479.93 | — |
| Withholding: annual gross base | (3400.00 - 479.93) x 12 | 35040.84 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 35040.84 - 6070.00 | 28970.84 | — |
| Scale tax | B10 n° 31 on 28970.84 | 9717.57 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 9717.57 - 2,987.98 | 6729.59 | B10 n° 32 (HIGH) |
| Monthly withholding before other reductions | 6729.59 / 12 | 560.80 | B10 n° 42 / B11 n° 16 (HIGH) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **560.80** | — |
| Special social security contribution | individual taxation, m = 3672.00: 30.99/3 + 1.10% x (3672.00 - 2190.18) | 26.63 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - withholding - BSSC | **2332.64** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 + 5.57 holiday % of 3672.00 | 1123.63 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

### Example 7 — Manual worker, high pay, 1 dependant

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 5200 | — |
| Gross pay | sum | 5200.00 | — |
| ONSS base (manual 108%) | 5200.00 x 108% | 5616.00 | B1 (HIGH) |
| Employee ONSS | 5616.00 x 13.07% | 734.01 | B1 + B2 (HIGH) |
| Social work bonus | S = 5200.00: A 0.00 + B 0.00 | -0.00 | B5 'juillet et août 2026', ouvriers (HIGH) |
| Employee ONSS after the bonus | 734.01 - 0.00 | 734.01 | — |
| Withholding: annual gross base | (5200.00 - 734.01) x 12 | 53591.88 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 53591.88 - 6070.00 | 47521.88 | — |
| Scale tax | B10 n° 31 on 47521.88 | 18621.59 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 18621.59 - 2,987.98 | 15633.61 | B10 n° 32 (HIGH) |
| Children reduction (1 child) | annual | -624 | B10 n° 38 (HIGH) |
| Monthly withholding before other reductions | 15009.61 / 12 | 1250.80 | B10 n° 42 / B11 n° 16 (HIGH) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **1250.80** | — |
| Special social security contribution | individual taxation, m = 5616.00: 118.83/3 + 1.10% x (5616.00 - 4100.00) | 56.29 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - withholding - BSSC | **3158.90** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 + 5.57 holiday % of 5616.00 | 1718.49 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

### Example 8 — White-collar, median pay, 6 h weekday overtime

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Overtime (6 h at +50%) | 23.08 x 6 x 150% | 207.72 | premium 50% (MEDIUM) |
| Gross pay | sum | 4007.72 | — |
| Employee ONSS | 4007.72 x 13.07% | 523.81 | B1 + B2 (HIGH) |
| Social work bonus | S = 4007.72: A 0.00 + B 0.00 | -0.00 | B5 'juillet et août 2026', employés (HIGH) |
| Employee ONSS after the bonus | 523.81 - 0.00 | 523.81 | — |
| Withholding: annual gross base | (4007.72 - 523.81) x 12 | 41806.92 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 41806.92 - 6070.00 | 35736.92 | — |
| Scale tax | B10 n° 31 on 35736.92 | 12947.13 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 12947.13 - 2,987.98 | 9959.15 | B10 n° 32 (HIGH) |
| Monthly withholding before other reductions | 9959.15 / 12 | 829.93 | B10 n° 42 / B11 n° 16 (HIGH) |
| Overtime reduction | 57.75% x 138.48 (hourly base of the premium hours) | -79.97 | B10 n° 45 (HIGH; assumes eligible legal overtime within 180 h, A2 art. 2) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **749.96** | — |
| Special social security contribution | individual taxation, m = 4007.72: 82.05/3 + 3.38% x (4007.72 - 3737.00) | 36.50 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - withholding - BSSC | **2697.45** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 % of 4007.72 | 1003.13 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

### Example 9 — Manual worker, median pay, 4 h Sunday overtime

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 3400 | — |
| Overtime (4 h at +100%) | 20.65 x 4 x 200% | 165.20 | premium 100% (MEDIUM) |
| Gross pay | sum | 3565.20 | — |
| ONSS base (manual 108%) | 3565.20 x 108% | 3850.42 | B1 (HIGH) |
| Employee ONSS | 3850.42 x 13.07% | 503.25 | B1 + B2 (HIGH) |
| Social work bonus | S = 3565.20: A 0.00 + B 0.00 | -0.00 | B5 'juillet et août 2026', ouvriers (HIGH) |
| Employee ONSS after the bonus | 503.25 - 0.00 | 503.25 | — |
| Withholding: annual gross base | (3565.20 - 503.25) x 12 | 36743.40 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 36743.40 - 6070.00 | 30673.40 | — |
| Scale tax | B10 n° 31 on 30673.40 | 10509.04 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 10509.04 - 2,987.98 | 7521.06 | B10 n° 32 (HIGH) |
| Monthly withholding before other reductions | 7521.06 / 12 | 626.76 | B10 n° 42 / B11 n° 16 (HIGH) |
| Overtime reduction | 57.75% x 82.60 (hourly base of the premium hours) | -47.70 | B10 n° 45 (HIGH; assumes eligible legal overtime within 180 h, A2 art. 2) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **579.06** | — |
| Special social security contribution | individual taxation, m = 3850.42: 82.05/3 + 3.38% x (3850.42 - 3737.00) | 31.18 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - withholding - BSSC | **2451.71** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 + 5.57 holiday % of 3850.42 | 1178.23 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

### Example 10 — White-collar, median pay, double holiday pay month

| Line | Calculation | Amount (EUR) | Source (confidence) |
|------|-------------|--------------|---------------------|
| Monthly salary | input (illustrative, not statutory) | 3800 | — |
| Double holiday pay | 3800 x 92% | 3496.00 | 92% (MEDIUM) |
| Gross pay | sum | 7296.00 | — |
| Employee ONSS | 3800.00 x 13.07% | 496.66 | B1 + B2 (HIGH) |
| Social work bonus | S = 3800.00: A 0.00 + B 0.00 | -0.00 | B5 'juillet et août 2026', employés (HIGH) |
| Employee ONSS after the bonus | 496.66 - 0.00 | 496.66 | — |
| Employee ONSS on double holiday pay | 3496.00 x 13.07% (class rule LOW) | 456.93 | earning class LOW (not sourced) |
| Withholding: annual gross base | (3800.00 - 496.66) x 12 | 39640.08 | B11 n° 7 / B10 n° 25-26 (HIGH) |
| Flat-rate professional expenses | 6,070 maximum | -6070.00 | B10 n° 28 / B11 n° 8 (HIGH) |
| Annual net taxable | 39640.08 - 6070.00 | 33570.08 | — |
| Scale tax | B10 n° 31 on 33570.08 | 11903.79 | B10 n° 31 (HIGH) |
| Base tax (single / spouse with income) | 11903.79 - 2,987.98 | 8915.81 | B10 n° 32 (HIGH) |
| Monthly withholding before other reductions | 8915.81 / 12 | 742.98 | B10 n° 42 / B11 n° 16 (HIGH) |
| **Professional withholding (regular)** | never negative (B11 n° 21) | **742.98** | — |
| Withholding on double holiday pay | (3496.00 - 456.93) x 42.39% (annual normal gross 45600) | 1288.26 | B10 n° 53 'pécules de vacances' (HIGH) |
| Special social security contribution | individual taxation, m = 3800.00: 82.05/3 + 3.38% x (3800 - 3737.00) | 29.48 | B3 (HIGH; quarterly / 3, interpretation flagged) |
| **NET PAY** | gross - ONSS after bonus - ONSS on holiday pay - withholding - BSSC | **4281.69** | full net (July 2026) |
| Employer ONSS before structural reduction | 19.88 + 5.12 + 0.02 + 0.01 % of 3800.00 | 951.14 | B1 + B2 Q3 (HIGH); structural reduction / FFE not applied |

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
