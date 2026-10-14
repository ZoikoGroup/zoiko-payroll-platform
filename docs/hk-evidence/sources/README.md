# Archived official sources for the Hong Kong packs

Fetched 2026-10-14 with `python -m scripts.hk_archive_authority_documents --manifest sources_manifest.csv --archive archive --fetch` (official domains only). Each file is stored as `<sha256>__<name>`; `archive/register.csv` / `register.json` record the URL, HTTP status, retrieval time and bytes. Values loaded from these sources stay **sourced – pending specialist review** ([G1]); nothing is marked specialist-verified.

## Figures the wireframe states, checked against the archive

| Wireframe figure | Confirmed in (archived file) | Result |
|---|---|---|
| SMW HK$43.10 from 1 May 2026 | `isd_smw_2026`, `ld_smw` | found ("43.1") |
| SMW HK$42.10 before | `isd_smw_2025` | found ("42.1") |
| Hours-record cap HK$17,600 | `ld_smw` | found |
| MPF HK$7,100 / HK$30,000; HK$1,500 cap | `mpfa_employees` | found |
| MPF daily HK$280 / HK$1,000 | `mpfa_employees` | found |
| Continuous contract 17 h / 68 h from 18 Jan 2026 | `ld_eao2025` | found |
| SP/LSP HK$22,500 → HK$15,000, 2/3, HK$390,000 | `ld_cg_11` (Concise Guide ch. 11), `ld_aoa` | found |

**No mismatch** between the wireframe and the archived official sources.

## Register (30 documents; 23 identical to the hashes the seed recorded on 2026-09-30)

| Id | Authority | Title | URL | Retrieved (UTC) | SHA-256 | Against the seed's 2026-09-30 hash |
|---|---|---|---|---|---|---|
| `ird_pam61e` | Inland Revenue Department | PAM 61(e) Allowances, Deductions and Tax Rate Table (Aug 2026) | <https://www.ird.gov.hk/eng/pdf/pam61e.pdf> | 2026-10-14T09:53:18Z | `357f13eb3f93bfaf…` | identical to the 2026-09-30 seed hash |
| `ird_budget_2627` | Inland Revenue Department | 2026-27 Budget — Tax Measures | <https://www.ird.gov.hk/eng/tax/budget.htm> | 2026-10-14T09:53:19Z | `34aa86e582fcfa6c…` | identical to the 2026-09-30 seed hash |
| `ird_example2627` | Inland Revenue Department | 2026-27 Budget — Tax Measures: worked examples | <https://www.ird.gov.hk/eng/pdf/2026/example2627.pdf> | 2026-10-14T09:53:19Z | `52aea360758c7b21…` | identical to the 2026-09-30 seed hash |
| `ird_employers` | Inland Revenue Department | Employers — BIR56A/IR56B, IR56E/F/G obligations | <https://www.ird.gov.hk/eng/tax/ere.htm> | 2026-10-14T09:53:20Z | `f3c47471346d6b50…` | identical to the 2026-09-30 seed hash |
| `ird_pam46e` | Inland Revenue Department | PAM 46(e) You or your employee is going to leave Hong Kong | <https://www.ird.gov.hk/eng/pdf/pam46e.pdf> | 2026-10-14T09:53:20Z | `fee4eaa115d6f4b0…` | identical to the 2026-09-30 seed hash |
| `mpfa_employees` | Mandatory Provident Fund Schemes Authority | Mandatory Contributions — Employees | <https://www.mpfa.org.hk/en/mpf-system/mandatory-contributions/employees> | 2026-10-14T09:53:25Z | `0068f8fde7b2626f…` | **changed since 2026-09-30** |
| `mpfa_coverage` | Mandatory Provident Fund Schemes Authority | MPF Coverage (regular employees, exempt persons) | <https://www.mpfa.org.hk/en/mpf-system/mpf-coverage> | 2026-10-14T09:53:29Z | `330e13b7e41c285f…` | **changed since 2026-09-30** |
| `ld_smw` | Labour Department | Statutory Minimum Wage | <https://www.labour.gov.hk/eng/news/mwo.htm> | 2026-10-14T09:53:30Z | `11e750937bf71eab…` | identical to the 2026-09-30 seed hash |
| `isd_smw_2026` | HKSAR Government (ISD) | New SMW rate of $43.1 per hour takes effect today (1 May 2026) | <https://www.info.gov.hk/gia/general/202605/01/P2026043000261.htm> | 2026-10-14T09:53:31Z | `25f1e8b7485aa32e…` | identical to the 2026-09-30 seed hash |
| `isd_smw_2025` | HKSAR Government (ISD) | New SMW rate of $42.1 per hour takes effect today (1 May 2025) | <https://www.info.gov.hk/gia/general/202505/01/P2025042900231.htm> | 2026-10-14T09:53:31Z | `f0125621b0b89ea7…` | identical to the 2026-09-30 seed hash |
| `ld_eao2025` | Labour Department | Revise the 'Continuous Contract' Requirement (Employment (Amendment) O | <https://www.labour.gov.hk/eng/news/EAO2025.htm> | 2026-10-14T09:53:32Z | `abe141556c48541f…` | identical to the 2026-09-30 seed hash |
| `ird_adc` | Inland Revenue Department | Increasing ceiling amount for concessionary deductions allowable for h | <https://www.ird.gov.hk/eng/tax/adc.htm> | 2026-10-14T09:53:32Z | `cfaca97642542753…` | identical to the 2026-09-30 seed hash |
| `ld_cc_edutool` | Labour Department | Education Tool on New 'Continuous Contract' Requirement (Note 1: the 4 | <https://www.labour.gov.hk/eng/labour/Continuous_Contract_EduTool.htm> | 2026-10-14T09:53:33Z | `b92a44121ad8d0f1…` | identical to the 2026-09-30 seed hash |
| `ld_cg_01` | Labour Department | Concise Guide to the Employment Ordinance — Ch.1 Application (continuo | <https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/01.pdf> | 2026-10-14T09:53:33Z | `c328c40a98d9bf24…` | identical to the 2026-09-30 seed hash |
| `ld_cg_03` | Labour Department | Concise Guide — Ch.3 Wages | <https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/03.pdf> | 2026-10-14T09:53:34Z | `dd61788183c75fca…` | identical to the 2026-09-30 seed hash |
| `ld_cg_04` | Labour Department | Concise Guide — Ch.4 Rest Days, Holidays and Leave | <https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/04.pdf> | 2026-10-14T09:53:34Z | `9cc70ff9e4fdc62a…` | identical to the 2026-09-30 seed hash |
| `ld_cg_05` | Labour Department | Concise Guide — Ch.5 Sickness Allowance | <https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/05.pdf> | 2026-10-14T09:53:35Z | `f368735f9f77240a…` | identical to the 2026-09-30 seed hash |
| `ld_cg_06` | Labour Department | Concise Guide — Ch.6 Maternity Protection | <https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/06.pdf> | 2026-10-14T09:53:35Z | `23988131d3fd53ab…` | identical to the 2026-09-30 seed hash |
| `ld_cg_07` | Labour Department | Concise Guide — Ch.7 Paternity Leave | <https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/07.pdf> | 2026-10-14T09:53:36Z | `bb4ada8c1ac3c472…` | identical to the 2026-09-30 seed hash |
| `ld_cg_11` | Labour Department | Concise Guide — Ch.11 Severance Payment and Long Service Payment | <https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/11.pdf> | 2026-10-14T09:53:36Z | `ef8fe29153964c3a…` | identical to the 2026-09-30 seed hash |
| `ld_cg_app1` | Labour Department | Concise Guide — Appendix 1: 12-Month Average Wages | <https://www.labour.gov.hk/eng/public/wcp/ConciseGuide/Appendix1.pdf> | 2026-10-14T09:53:37Z | `dc9e32d8be3f5f48…` | identical to the 2026-09-30 seed hash |
| `ld_holidays_2025` | Labour Department | Statutory Holidays for 2025 | <https://www.labour.gov.hk/eng/news/latest_holidays2025.htm> | 2026-10-14T09:53:37Z | `dcf353421d6ce60c…` | identical to the 2026-09-30 seed hash |
| `ld_holidays_2026` | Labour Department | Statutory Holidays for 2026 | <https://www.labour.gov.hk/eng/news/latest_holidays2026.htm> | 2026-10-14T09:53:38Z | `4fe56c8677a98a26…` | identical to the 2026-09-30 seed hash |
| `ld_holidays_2027` | Labour Department | Statutory Holidays for 2027 | <https://www.labour.gov.hk/eng/news/latest_holidays2027.htm> | 2026-10-14T09:53:38Z | `9eebdd134cfe17c2…` | identical to the 2026-09-30 seed hash |
| `ld_aoa` | Labour Department | Abolition of MPF Offsetting — employment commencing before 1 May 2025 | <https://www.op.labour.gov.hk/en/before-1-may.html> | 2026-10-14T09:53:40Z | `4c40afaa941fd852…` | identical to the 2026-09-30 seed hash |
| `pcpd_hr_code` | Office of the Privacy Commissioner for Personal Data | Code of Practice on Human Resource Management | <https://www.pcpd.org.hk/english/data_privacy_law/code_of_practices/code_hrm.html> | 2026-10-14T09:53:45Z | `3d3bf23ccdbfd038…` | **changed since 2026-09-30** |
| `g1_eo_week` | Hong Kong specialist (G1) — pending | [UNVERIFIED — G1] Employment Ordinance Cap. 57 s.2 definition of 'week | <https://www.elegislation.gov.hk/hk/cap57> | 2026-10-14T09:53:49Z | `7f1f4cd5cb87c91b…` | new |
| `govhk_general_holidays_2025` | HKSAR Government (GovHK) | General holidays for 2025 | <https://www.gov.hk/en/about/abouthk/holiday/2025.htm> | 2026-10-14T09:53:50Z | `4cd19434413b2c32…` | new |
| `govhk_general_holidays_2026` | HKSAR Government (GovHK) | General holidays for 2026 | <https://www.gov.hk/en/about/abouthk/holiday/2026.htm> | 2026-10-14T09:53:50Z | `1d16f285c01e080f…` | new |
| `govhk_general_holidays_2027` | HKSAR Government (GovHK) | General holidays for 2027 | <https://www.gov.hk/en/about/abouthk/holiday/2027.htm> | 2026-10-14T09:53:51Z | `a2659fe0209a1311…` | new |

The three changed pages (two MPFA pages and the PCPD HR code) are dynamic HTML. Their figures are re-confirmed above, but the seed still cites the old hashes. The **specialist should review the new copies** (G1).

## General holidays 2025, 2026, 2027 (new)

`general_holidays_<year>_extracted.csv` was parsed **from the archived gov.hk page, not typed**: 17 dates per year, and every row's weekday matches the weekday printed on the page. Each `.provenance.txt` sidecar names the URL, retrieval time and SHA-256.

* **Local check:** loaded on a local scratch database through `scripts/hk_load_general_holidays.py`, the governed path (Draft packs only; archived file uploaded; SHA-256 recorded; audit row; rows marked [G1]). After loading, the golden-vector certification still gives **PASS 11/11**.
* **Production:** a person runs the same loader for HK-PAYROLL-2025 (years 2025, 2026) and HK-PAYROLL-2026 (years 2026, 2027) after the deploy. The commands are in `../ops/HK_DEPLOY_RUNBOOK.md`.
