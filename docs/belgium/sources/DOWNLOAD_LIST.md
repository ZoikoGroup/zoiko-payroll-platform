# Belgium — official documents to download (Block F2)

Audience: the person collecting the official sources. Save each file **unchanged** in
`docs/belgium/sources/inbox/` (do not rename). The next parse run records each file as a source artifact with
its SHA-256, extracts the values with page / section references and fills the workbook
`docs/belgium/content/BE_2026_AI_DRAFT.xlsx`. URLs were found on 2026-11-13; where the exact file was not found,
the official site and the section to search are given.

Workbook rows are named by their catalogue key (sheet "Scalar keys" unless another sheet is named).

## A. Professional withholding — Annex III (FPS Finance) — highest payroll impact

| # | Document | Version wanted | Where | Fills |
|---|----------|----------------|-------|-------|
| A1 | Annex III AR/CIR 92 — **key formula (formule-clé / sleutelformule) 2026**, as applicable from 1 Jan 2026 | 2026 (from 01/01/2026) | finances.belgium.be → Entreprises → Personnel et rémunération → Précompte professionnel → Calcul → 2026 (official site; exact file not found) | be_wht_annex3_regular_scale (Slab keys), be_wht_family_reductions, be_wht_period_strategy, be_wht_taxable_basis_rule, be_rounding_withholding |
| A2 | Royal Decree of 24 Jul 2026 amending Annex III (published 30 Jul 2026) + the adapted key formula | from 01/08/2026 | Moniteur belge (ejustice.just.fgov.be) + finances.belgium.be (same section) | be_wht_annex3_amendment_2026, be_wht_overtime_rule (180 h), be_wht_fiscal_work_bonus (63% since 1 Aug 2026) |
| A3 | Royal Decree of 27 Sep 2026 (published 2 Oct 2026) — Annex III scales for pay from 1 Nov 2026 (exempt quota 11 550 EUR per secondary source) + key formula | from 01/11/2026 | Moniteur belge + finances.belgium.be | be_wht_annex3_regular_scale (dated rows 1 Nov), be_wht_annex3_amendment_2026 |
| A4 | Annex III sections on exceptional remuneration, holiday pay, arrears, non-residents | 2026 | inside A1-A3 | be_wht_exceptional_rule, be_wht_holiday_pay_rule, be_wht_arrears_rule, be_wht_nonresident_rule, be_wht_applicability_rule |
| A5 | Withholding declaration / payment frequency rules and the **quarterly threshold** (prior-year amount) | current | finances.belgium.be → Précompte professionnel → Déclaration / FinProf (threshold not found publicly) | G-30 decision; employer registration frequency |

Secondary context (not to archive as official): Partena https://www.partena-professional.be/fr/nos-connaissances/infoflashes/precompte-professionnel-nouvelles-regles-partir-du-1er-novembre-2026 ; Securex https://www.securex.be/en/lex4you/employer/news/new-rules-on-professional-withholding-tax-for-2026

## B. ONSS / RSZ contributions (socialsecurity.be)

| # | Document | Version wanted | Where | Fills |
|---|----------|----------------|-------|-------|
| B1 | Administrative instructions DmfA **2026/3** — contributions chapter (save the page as PDF / HTML) | 2026/3 | https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/socialsecuritycontributions/contributions.html | be_onss_employee_rate, be_onss_manual_base_uplift, be_onss_employee_base_rule (confirms HIGH rows) |
| B2 | Quarterly **rate file** (contribution percentages by employer category / worker code) from TechLib | 2026 Q1-Q4 | https://www.socialsecurity.be/site_fr/employer/general/techlib.htm | be_onss_employer_base_rate (EC x WC bands), be_onss_fund_contributions, be_onss_rate_file_quarter, be_onss_supported_employer_categories, be_onss_supported_worker_codes |
| B3 | Special contributions — **special social security contribution (BSSC) scale** (current version; the page found is the 2022/1 edition) | 2026/3 | https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/other_specialcontributions/specialsocialsecuritycontribution.html | be_bssc_pending (G-06 / G-17) |
| B4 | Special contributions — index centime / wage moderation, 1.60 %, 8.86 % | 2026/3 | https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/pennyindex_wagemoderationcontribution.html | be_onss_wage_moderation, be_onss_special_160 (+ threshold rule), be_onss_pension_special, be_wage_index_centime_rule |
| B5 | **Social work bonus** (bonus à l'emploi) — amounts and formula 2026 (changes during 2026) | 2026/3 | https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/deductions/workers_reductions/workbonus.html | be_red_social_work_bonus (Slab keys) |
| B6 | **Structural reduction** parameters 2026 | 2026/3 | https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/deductions/structuralreduction_targetgroupreductions/structuralreduction.html | be_red_structural |
| B7 | **Target-group reductions** (first hires, older workers, …) | 2026/3 | socialsecurity.be → instructions 2026/3 → réductions de cotisations → réductions groupes-cibles | be_red_target_group |
| B8 | Company car CO2 solidarity contribution 2026 | 2026 | socialsecurity.be → instructions 2026/3 → cotisations spéciales → véhicule de société | be_onss_company_car, be_bik_valuation_rules |

## C. Holiday pay (manual-worker holiday fund) and holiday rules

| # | Document | Version wanted | Where | Fills |
|---|----------|----------------|-------|-------|
| C1 | Manual-worker holiday contribution — quarterly rate and annual debit for the **current holiday year** | holiday year 2026 (service year 2025) | ONVA / RJV (rjv.fgov.be / onva.fgov.be) and socialsecurity.be instructions → cotisations vacances annuelles | be_hol_manual_quarterly_contribution, be_hol_manual_annual_debit (the 10.27 % found is an older year) |
| C2 | White-collar simple / double holiday pay rules, departure holiday pay, additional holidays | current | FPS Employment (emploi.belgique.be) → vacances annuelles; ONVA | be_hol_wc_simple_rule, be_hol_wc_double_pct, be_hol_wc_double_contribution_rule, be_hol_departure_rule, be_hol_additional_rule, be_hol_entitlement_weeks |

## D. Absence

| # | Document | Version wanted | Where | Fills |
|---|----------|----------------|-------|-------|
| D1 | **Guaranteed salary** — manual-worker day bands and percentages, white-collar 30 days, relapse window (8 weeks from 2026) | 2026 | FPS Employment (emploi.belgique.be) → maladie / salaire garanti; Employment Contracts Act 3 Jul 1978 art. 52-75 | be_abs_manual_day_bands (Slab keys), be_abs_manual_insurance_cap, be_abs_wc_guaranteed_days / _pct / _min_contract_months, be_abs_relapse_window_weeks |
| D2 | Maternity (incl. multiple birth weeks) and birth leave (20 days, window, employer days) | 2026 | INAMI-RIZIV (inami.fgov.be) and FPS Employment | be_abs_maternity_weeks, be_abs_maternity_multiple_weeks (Slab keys), be_abs_birth_leave_* |

## E. Wages and working time

| # | Document | Version wanted | Where | Fills |
|---|----------|----------------|-------|-------|
| E1 | National minimum (RMMMG, CCT 43) — every 2026 amount with its effective date (1 Apr and 1 Jul 2026 conflict) | 2026 | National Labour Council (cnt-nar.be) / FPS Employment | be_wage_rmmmg (dated rows), be_wage_rmmmg_min_age |
| E2 | Programme law of 30 May 2026 (index-centime limitation; ceiling 4 000 EUR) | 2026 | Moniteur belge | be_wage_index_centime_threshold, be_wage_index_centime_rule, be_wage_norm_margin |
| E3 | Working-time limits, overtime premiums, compensatory rest (Labour Act 16 Mar 1971) | current | FPS Employment | be_wt_*, be_ot_* |
| E4 | **Public holidays 2026 and substitution rules** (AR 18 Apr 1974; replacement days) | 2026 | FPS Employment (emploi.belgique.be) → jours fériés | be_public_holidays (confirms MEDIUM rows), be_public_holiday_substitution_rule |

## F. Authority schemas and technical documentation (G-31 / G-33)

| # | Document | Version wanted | Where | Fills |
|---|----------|----------------|-------|-------|
| F1 | **DmfA XSD 2026/3** (and 2026/2) | 2026/2, 2026/3 | TechLib https://www.socialsecurity.be/site_fr/employer/general/techlib.htm ; change note https://www.socialsecurity.be/portail/glossaires/dmfa.nsf/ConsultFrImprPDF/373470249E00C0ADC1258E13002A91B8/$FILE/VersModifDMFA263_F.pdf | Filing schema versions (DMFA), payload mapping |
| F2 | **Dimona XSD** (current) | current | TechLib (same) | be_filing_dimona_schema_versions |
| F3 | DmfA glossary codes (worker codes, remuneration, contribution codes) | 2026/3 | https://www.socialsecurity.be/lambda/portail/glossaires/dmfa.nsf/web/Welcome_fr ; worker codes annex https://www.socialsecurity.be/portail/glossaires/dmfa.nsf/be8ba64d95a2ed0ec125686200574ff5/a4b399a47819e4a2c12579b90038d142/$FILE/AN2012-2-FR2.pdf | G-33 codes; be_onss_supported_worker_codes |
| F4 | **FinProf** technical specification | current | finances.belgium.be → FinProf (not found publicly; see authority request 02) | be_filing_finprof_schema_versions |
| F5 | **Belcotax-on-web** technical documentation and schema for income year 2026 (281.10 box codes). Secondary sources say the income-2026 version opens around Feb 2027 (JSON schemas mentioned) | income 2026 | finances.belgium.be → Belcotax-on-web → documentation technique; https://finanzen.belgium.be/sites/default/files/downloads/161-belcotax-organisations-internationales-creation-fiches.pdf (related) | be_filing_belcotax_schema_versions |
| F6 | DmfA quarterly deadline table (all 2026 quarters) | 2026 | https://www.socialsecurity.be/site_fr/employer/applics/dmfa/index.htm | Calendar rows (BE_DMFA) |

## G. Decisions needing a legal source

| # | Document | Where | Fills |
|---|----------|-------|-------|
| G1 | Language decrees (Flemish 19 Jul 1973, French Community 30 Jun 1982, coordinated laws 18 Jul 1966) | Moniteur belge / Justel | G-13 language rule |
| G2 | Retention of social documents (AR 8 Aug 1980), tax (CIR 92), accounting (Code of Economic Law) | Justel | G-21 |
| G3 | NISS / BIS / KBO structure and check digits | Registre national / BCSS (ksz-bcss.fgov.be), KBO (economie.fgov.be) | G-16 |

## Rows this list does not cover (product decisions, not documents)

- Parallel-run tolerances (all six): agreed with each design partner (spec §16).
- G-11 (decided: MONTHLY), G-12, G-13 operator language (decided).
