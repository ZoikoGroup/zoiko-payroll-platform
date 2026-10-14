# Owner pack: configuration CSV review (for the owner's decision on commit 8)

**File:** `docs/HONG_KONG_RELEASE_EVIDENCE/CONFIGURATION/HK_CONFIGURATION_MASTER_MATRIX.csv` (owner-controlled, untracked, not committed)
**Reviewed:** 2026-10-14. All numbers below come from the commands listed in §5.

## 1. Bottom line

* The file has **257 data rows**: the **255 rows that existed before** plus **2 rows added on 2026-10-13** for the governed MPF contribution-day deferral rule (one per pack).
* In all 255 existing rows, every **content** column is the same as in a fresh regeneration from code. That covers KEY, PACK, YA, LABEL, VALUE, UNIT, EFFECTIVE_FROM / TO, SOURCE, SOURCE_URL, SOURCE_DATE, SOURCE_SHA256, G1_REQUIRED and STATUS. 100 existing rows differ only in the two code-derived columns, CODE_CONSUMER (85 rows) and TEST (76 rows). Those list which code and tests read each value, and code has gained consumers since the file was written.
* **The byte identity of the 255 existing rows to their pre-edit state cannot be proven.** No copy of the file from before 2026-10-13 exists in git, in any worktree or in scratch storage. The only recorded digest, `1f7427cd…` in `G1/G1_EVIDENCE_MANIFEST.md` line 58, matches neither the current file nor the regenerated one. It predates a later regeneration of the pack, so it cannot serve as a baseline. The comparison in §3 is against a regeneration from code, **not** against the original.
* The file is LF, UTF-8 without BOM, and `csv.writer` round-trips it byte for byte, so it is consistently formatted with no stray quoting.

## 2. The 2 added rows

| Row | KEY | PACK | YA | VALUE | STATUS |
|---|---|---|---|---|---|
| 62 | `mpf_contribution_day_deferral` | HK-PAYROLL-2025 v1.0 | 2025/26 | `NEXT_DAY_NOT_SAT_SUN_OR_GENERAL_HOLIDAY` | USED – UNVERIFIED (G1) |
| 189 | `mpf_contribution_day_deferral` | HK-PAYROLL-2026 v1.0 | 2026/27 | `NEXT_DAY_NOT_SAT_SUN_OR_GENERAL_HOLIDAY` | USED – UNVERIFIED (G1) |

Both rows have G1_REQUIRED = YES. Their source is the MPFA "Mandatory Contributions – Employees" page, whose archived SHA-256 is `97b6c8c4…`. They differ from the regenerated rows only in CODE_CONSUMER and REPORT_IMPACT, which were written by hand when the rows were added. The value is an interpretation that the HK specialist must confirm (G1).

## 3. Existing rows vs a regeneration from code

| Measure | Result |
|---|---|
| Existing rows compared (same order in both files) | 255 |
| Rows with any content-column difference | **0** |
| Rows differing only in code-derived columns | 100 (CODE_CONSUMER 85, TEST 76) |
| Header | identical (17 columns) |

The row-by-row list of every differing cell is in the appendix.

## 4. Digests for the record

| What | SHA-256 |
|---|---|
| Current file (bytes) | `e587a51871d57fa4f014428fbfec6d945e7f511051ea917aa5585bfdf17ecfea` |
| Header + the 255 existing rows, re-serialised with `csv.writer` (LF): a baseline for future comparison | `5c595d0b88e06c3bcbec5c50a98fbedef854ae90b3ecff38d8c519c7c665ad89` |
| Regenerated comparison copy (scratch, CRLF, 2026-10-13 14:09 IST) | `086f9305f30c4b62f9c643ba131e6206f6cc34a4a7f8ebda9d1713a9d517aa68` |
| Stale digest recorded in `G1/G1_EVIDENCE_MANIFEST.md` | `1f7427cdd37d74852d818985dc5ae58a59ac98b5a31168172c261cc63334b186` (matches no known version) |
| Whole-pack manifest (`owner_pack_proposal/MANIFEST.sha256`, 163 files) | see that file |

## 5. How this was produced

Python `csv` module: rows compared by position after removing the two `mpf_contribution_day_deferral` rows from each file. KEY is not unique (it repeats per pack), and neither is KEY+PACK+YA (slab rows repeat), so a keyed comparison would collide. The regenerated copy came from `_gen_regen.py` (scratch) on 2026-10-13.

## 6. What the owner can decide

1. **Accept as the baseline.** Commit the pack with `gitattributes.proposed` (exact bytes kept) and `MANIFEST.sha256`, and correct the stale digest in `G1/G1_EVIDENCE_MANIFEST.md` (owner edit).
2. **Restore and re-apply.** If the owner holds an earlier copy (email, download, backup), compare it with this file. Only the 2 added rows should differ.
3. **Regenerate.** Replace the file with a fresh regeneration from code. That keeps the content and updates the code-derived columns, and gives the file a new digest.

Owner decision (leave blank): ______________________   Date: __________

## Appendix: every differing cell in the existing rows

| # (existing row) | KEY | PACK | Column | Current file | Regenerated from code |
|---|---|---|---|---|---|
| 9 | eo_days_per_year | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/termination.py | app/modules/payroll/engine/jurisdictions/hong_kong/termination.py; app/modules/payroll/hong_kong_service.py |
| 10 | eo_four_fifths_factor | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/average_wage.py; app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/average_wage.py; app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 25 | eo_week_start_day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/continuous_contract.py | app/modules/payroll/engine/jurisdictions/hong_kong/continuous_contract.py; app/modules/payroll/hong_kong_service.py |
| 25 | eo_week_start_day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 26 | hk_allowance_basic | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 49 | hk_tax_reduction_cap | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_engineering_remediation.py |
| 61 | mpf_contribution_day | HK-PAYROLL-2025 v1.0 | TEST | test_hong_kong_report_closure.py | test_hong_kong.py; test_hong_kong_e2e.py; test_hong_kong_report_closure.py |
| 63 | mpf_employee_rate | HK-PAYROLL-2025 v1.0 | TEST | test_hong_kong_report_closure.py | test_hong_kong_configuration.py; test_hong_kong_control.py; test_hong_kong_engineering_remediation.py; test_hong_kong_governance.py; test_hong_kong_report_closure.py |
| 64 | mpf_employer_rate | HK-PAYROLL-2025 v1.0 | TEST | test_hong_kong.py | test_hong_kong.py; test_hong_kong_configuration.py; test_hong_kong_engineering_remediation.py |
| 69 | mpf_min_relevant_income_monthly | HK-PAYROLL-2025 v1.0 | TEST | test_hong_kong.py | test_hong_kong.py; test_hong_kong_configuration.py |
| 70 | mpf_offset_transition_date | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/termination.py | app/modules/payroll/engine/jurisdictions/hong_kong/termination.py; app/modules/payroll/hong_kong_service.py |
| 75 | smw_hourly_rate | HK-PAYROLL-2025 v1.0 | TEST | test_hong_kong.py | test_hong_kong.py; test_hong_kong_configuration.py |
| 76 | smw_hourly_rate | HK-PAYROLL-2025 v1.0 | TEST | test_hong_kong.py | test_hong_kong.py; test_hong_kong_configuration.py |
| 84 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y1 | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 85 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y2 | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 86 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y3 | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 87 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y4 | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 88 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y5 | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 89 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y6 | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 90 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y7 | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 91 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y8 | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 92 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y9 | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 100 | HK_STATUTORY_HOLIDAY:The first day of January | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 100 | HK_STATUTORY_HOLIDAY:The first day of January | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 101 | HK_STATUTORY_HOLIDAY:Lunar New Year's Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 101 | HK_STATUTORY_HOLIDAY:Lunar New Year's Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 102 | HK_STATUTORY_HOLIDAY:The second day of Lunar New Year | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 102 | HK_STATUTORY_HOLIDAY:The second day of Lunar New Year | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 103 | HK_STATUTORY_HOLIDAY:The third day of Lunar New Year | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 103 | HK_STATUTORY_HOLIDAY:The third day of Lunar New Year | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 104 | HK_STATUTORY_HOLIDAY:Ching Ming Festival | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 104 | HK_STATUTORY_HOLIDAY:Ching Ming Festival | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 105 | HK_STATUTORY_HOLIDAY:Labour Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 105 | HK_STATUTORY_HOLIDAY:Labour Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 106 | HK_STATUTORY_HOLIDAY:The Birthday of the Buddha | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 106 | HK_STATUTORY_HOLIDAY:The Birthday of the Buddha | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 107 | HK_STATUTORY_HOLIDAY:Tuen Ng Festival | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 107 | HK_STATUTORY_HOLIDAY:Tuen Ng Festival | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 108 | HK_STATUTORY_HOLIDAY:HKSAR Establishment Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 108 | HK_STATUTORY_HOLIDAY:HKSAR Establishment Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 109 | HK_STATUTORY_HOLIDAY:National Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 109 | HK_STATUTORY_HOLIDAY:National Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 110 | HK_STATUTORY_HOLIDAY:The day following the Chinese Mid-Autumn Festival | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 110 | HK_STATUTORY_HOLIDAY:The day following the Chinese Mid-Autumn Festival | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 111 | HK_STATUTORY_HOLIDAY:Chung Yeung Festival | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 111 | HK_STATUTORY_HOLIDAY:Chung Yeung Festival | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 112 | HK_STATUTORY_HOLIDAY:Chinese Winter Solstice Festival (or 25 Dec, employer's option) | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 112 | HK_STATUTORY_HOLIDAY:Chinese Winter Solstice Festival (or 25 Dec, employer's option) | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 113 | HK_STATUTORY_HOLIDAY:The first weekday after Christmas Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 113 | HK_STATUTORY_HOLIDAY:The first weekday after Christmas Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 114 | HK_STATUTORY_HOLIDAY:The first day of January | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 114 | HK_STATUTORY_HOLIDAY:The first day of January | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 115 | HK_STATUTORY_HOLIDAY:Lunar New Year's Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 115 | HK_STATUTORY_HOLIDAY:Lunar New Year's Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 116 | HK_STATUTORY_HOLIDAY:The second day of Lunar New Year | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 116 | HK_STATUTORY_HOLIDAY:The second day of Lunar New Year | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 117 | HK_STATUTORY_HOLIDAY:The third day of Lunar New Year | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 117 | HK_STATUTORY_HOLIDAY:The third day of Lunar New Year | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 118 | HK_STATUTORY_HOLIDAY:Ching Ming Festival | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 118 | HK_STATUTORY_HOLIDAY:Ching Ming Festival | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 119 | HK_STATUTORY_HOLIDAY:Easter Monday | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 119 | HK_STATUTORY_HOLIDAY:Easter Monday | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 120 | HK_STATUTORY_HOLIDAY:Labour Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 120 | HK_STATUTORY_HOLIDAY:Labour Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 121 | HK_STATUTORY_HOLIDAY:The Birthday of the Buddha | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 121 | HK_STATUTORY_HOLIDAY:The Birthday of the Buddha | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 122 | HK_STATUTORY_HOLIDAY:Tuen Ng Festival | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 122 | HK_STATUTORY_HOLIDAY:Tuen Ng Festival | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 123 | HK_STATUTORY_HOLIDAY:HKSAR Establishment Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 123 | HK_STATUTORY_HOLIDAY:HKSAR Establishment Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 124 | HK_STATUTORY_HOLIDAY:The day following the Chinese Mid-Autumn Festival | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 124 | HK_STATUTORY_HOLIDAY:The day following the Chinese Mid-Autumn Festival | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 125 | HK_STATUTORY_HOLIDAY:National Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 125 | HK_STATUTORY_HOLIDAY:National Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 126 | HK_STATUTORY_HOLIDAY:Chung Yeung Festival | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 126 | HK_STATUTORY_HOLIDAY:Chung Yeung Festival | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 127 | HK_STATUTORY_HOLIDAY:Chinese Winter Solstice Festival (or 25 Dec, employer's option) | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 127 | HK_STATUTORY_HOLIDAY:Chinese Winter Solstice Festival (or 25 Dec, employer's option) | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 128 | HK_STATUTORY_HOLIDAY:The first weekday after Christmas Day | HK-PAYROLL-2025 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 128 | HK_STATUTORY_HOLIDAY:The first weekday after Christmas Day | HK-PAYROLL-2025 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 137 | eo_days_per_year | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/termination.py | app/modules/payroll/engine/jurisdictions/hong_kong/termination.py; app/modules/payroll/hong_kong_service.py |
| 138 | eo_four_fifths_factor | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/average_wage.py; app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/average_wage.py; app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 153 | eo_week_start_day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/continuous_contract.py | app/modules/payroll/engine/jurisdictions/hong_kong/continuous_contract.py; app/modules/payroll/hong_kong_service.py |
| 153 | eo_week_start_day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 154 | hk_allowance_basic | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 187 | mpf_contribution_day | HK-PAYROLL-2026 v1.0 | TEST | test_hong_kong_report_closure.py | test_hong_kong.py; test_hong_kong_e2e.py; test_hong_kong_report_closure.py |
| 189 | mpf_employee_rate | HK-PAYROLL-2026 v1.0 | TEST | test_hong_kong_report_closure.py | test_hong_kong_configuration.py; test_hong_kong_control.py; test_hong_kong_engineering_remediation.py; test_hong_kong_governance.py; test_hong_kong_report_closure.py |
| 190 | mpf_employer_rate | HK-PAYROLL-2026 v1.0 | TEST | test_hong_kong.py | test_hong_kong.py; test_hong_kong_configuration.py; test_hong_kong_engineering_remediation.py |
| 195 | mpf_min_relevant_income_monthly | HK-PAYROLL-2026 v1.0 | TEST | test_hong_kong.py | test_hong_kong.py; test_hong_kong_configuration.py |
| 196 | mpf_offset_transition_date | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/termination.py | app/modules/payroll/engine/jurisdictions/hong_kong/termination.py; app/modules/payroll/hong_kong_service.py |
| 201 | smw_hourly_rate | HK-PAYROLL-2026 v1.0 | TEST | test_hong_kong.py | test_hong_kong.py; test_hong_kong_configuration.py |
| 202 | smw_hourly_rate | HK-PAYROLL-2026 v1.0 | TEST | test_hong_kong.py | test_hong_kong.py; test_hong_kong_configuration.py |
| 210 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y1 | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 211 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y2 | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 212 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y3 | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 213 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y4 | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 214 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y5 | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 215 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y6 | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 216 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y7 | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 217 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y8 | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 218 | HK_ANNUAL_LEAVE_SCALE:HKEO-AL-Y9 | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 226 | HK_STATUTORY_HOLIDAY:The first day of January | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 226 | HK_STATUTORY_HOLIDAY:The first day of January | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 227 | HK_STATUTORY_HOLIDAY:Lunar New Year's Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 227 | HK_STATUTORY_HOLIDAY:Lunar New Year's Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 228 | HK_STATUTORY_HOLIDAY:The second day of Lunar New Year | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 228 | HK_STATUTORY_HOLIDAY:The second day of Lunar New Year | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 229 | HK_STATUTORY_HOLIDAY:The third day of Lunar New Year | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 229 | HK_STATUTORY_HOLIDAY:The third day of Lunar New Year | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 230 | HK_STATUTORY_HOLIDAY:Ching Ming Festival | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 230 | HK_STATUTORY_HOLIDAY:Ching Ming Festival | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 231 | HK_STATUTORY_HOLIDAY:Easter Monday | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 231 | HK_STATUTORY_HOLIDAY:Easter Monday | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 232 | HK_STATUTORY_HOLIDAY:Labour Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 232 | HK_STATUTORY_HOLIDAY:Labour Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 233 | HK_STATUTORY_HOLIDAY:The Birthday of the Buddha | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 233 | HK_STATUTORY_HOLIDAY:The Birthday of the Buddha | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 234 | HK_STATUTORY_HOLIDAY:Tuen Ng Festival | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 234 | HK_STATUTORY_HOLIDAY:Tuen Ng Festival | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 235 | HK_STATUTORY_HOLIDAY:HKSAR Establishment Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 235 | HK_STATUTORY_HOLIDAY:HKSAR Establishment Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 236 | HK_STATUTORY_HOLIDAY:The day following the Chinese Mid-Autumn Festival | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 236 | HK_STATUTORY_HOLIDAY:The day following the Chinese Mid-Autumn Festival | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 237 | HK_STATUTORY_HOLIDAY:National Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 237 | HK_STATUTORY_HOLIDAY:National Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 238 | HK_STATUTORY_HOLIDAY:Chung Yeung Festival | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 238 | HK_STATUTORY_HOLIDAY:Chung Yeung Festival | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 239 | HK_STATUTORY_HOLIDAY:Chinese Winter Solstice Festival (or 25 Dec, employer's option) | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 239 | HK_STATUTORY_HOLIDAY:Chinese Winter Solstice Festival (or 25 Dec, employer's option) | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 240 | HK_STATUTORY_HOLIDAY:The first weekday after Christmas Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 240 | HK_STATUTORY_HOLIDAY:The first weekday after Christmas Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 241 | HK_STATUTORY_HOLIDAY:The first day of January | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 241 | HK_STATUTORY_HOLIDAY:The first day of January | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 242 | HK_STATUTORY_HOLIDAY:Lunar New Year's Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 242 | HK_STATUTORY_HOLIDAY:Lunar New Year's Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 243 | HK_STATUTORY_HOLIDAY:The third day of Lunar New Year | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 243 | HK_STATUTORY_HOLIDAY:The third day of Lunar New Year | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 244 | HK_STATUTORY_HOLIDAY:The fourth day of Lunar New Year | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 244 | HK_STATUTORY_HOLIDAY:The fourth day of Lunar New Year | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 245 | HK_STATUTORY_HOLIDAY:Easter Monday | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 245 | HK_STATUTORY_HOLIDAY:Easter Monday | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 246 | HK_STATUTORY_HOLIDAY:Ching Ming Festival | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 246 | HK_STATUTORY_HOLIDAY:Ching Ming Festival | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 247 | HK_STATUTORY_HOLIDAY:Labour Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 247 | HK_STATUTORY_HOLIDAY:Labour Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 248 | HK_STATUTORY_HOLIDAY:The Birthday of the Buddha | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 248 | HK_STATUTORY_HOLIDAY:The Birthday of the Buddha | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 249 | HK_STATUTORY_HOLIDAY:Tuen Ng Festival | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 249 | HK_STATUTORY_HOLIDAY:Tuen Ng Festival | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 250 | HK_STATUTORY_HOLIDAY:HKSAR Establishment Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 250 | HK_STATUTORY_HOLIDAY:HKSAR Establishment Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 251 | HK_STATUTORY_HOLIDAY:The day following the Chinese Mid-Autumn Festival | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 251 | HK_STATUTORY_HOLIDAY:The day following the Chinese Mid-Autumn Festival | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 252 | HK_STATUTORY_HOLIDAY:National Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 252 | HK_STATUTORY_HOLIDAY:National Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 253 | HK_STATUTORY_HOLIDAY:Chung Yeung Festival | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 253 | HK_STATUTORY_HOLIDAY:Chung Yeung Festival | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 254 | HK_STATUTORY_HOLIDAY:Chinese Winter Solstice Festival (or 25 Dec, employer's option) | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 254 | HK_STATUTORY_HOLIDAY:Chinese Winter Solstice Festival (or 25 Dec, employer's option) | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
| 255 | HK_STATUTORY_HOLIDAY:The first weekday after Christmas Day | HK-PAYROLL-2026 v1.0 | CODE_CONSUMER | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py | app/modules/payroll/engine/jurisdictions/hong_kong/entitlements.py; app/modules/payroll/hong_kong_service.py |
| 255 | HK_STATUTORY_HOLIDAY:The first weekday after Christmas Day | HK-PAYROLL-2026 v1.0 | TEST | (pack-wide tests) | test_hong_kong_configuration.py |
