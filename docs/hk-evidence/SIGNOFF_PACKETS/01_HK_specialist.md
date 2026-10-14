# Sign-off packet 01: Hong Kong payroll / statutory specialist (gate G1)

> **Status:** prepared by engineering on 2026-10-14. It contains no decision, value, result or signature made on anyone's behalf. Every evidence link gives the file's SHA-256 when this packet was generated: if the file you open has a different digest, stop and ask engineering.

## What you need to do

1. For each of the **29 flagged values** below, confirm the value or give the correct one, citing the ordinance, guide or circular you relied on. The same 29 keys exist in both Draft packs (2025/26 and 2026/27); their values are identical.
2. Confirm or correct the **MPF contribution-day deferral rule** (row `mpf_contribution_day_deferral`).
3. For the **general-holiday lists** (2025, 2026, 2027), provide the official gazetted list for each year as a file (for example the Government Notice PDF), with its URL. Please do not type dates: engineering loads the archived file with `scripts/hk_load_general_holidays.py`, which records the file's SHA-256 and keeps every date marked [G1] until you sign this packet.
4. Sign at the end. Your signed packet and worksheet are uploaded under `HK-GATE-G1`. A second Super Admin must accept them before the gate passes.

## What to check

The other 123 values in each pack (rates, thresholds, tax bands) already have an archived official source and pass the golden test vectors. They are listed in the worksheet for completeness, and you may spot-check them.

| # | Item | Current value | Source | What to confirm | Confirmed? (Y / corrected value) | Authority you relied on |
|---|---|---|---|---|---|---|
| 1 | `mpf_contribution_day_deferral` | `NEXT_DAY_NOT_SAT_SUN_OR_GENERAL_HOLIDAY` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `97b6c8c42685…` | Is the rule right: when the contribution day falls on a Saturday, Sunday, general holiday or a black-rainstorm / No. 8+ signal day, it moves to the next day that is none of these? Should it be the next or the preceding working day? How are partial-day signals treated? | | |
| 2 | `mpf_partial_month_threshold_basis` | `MONTHLY_LEVELS` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `97b6c8c42685…` | For an incomplete monthly wage period, do the monthly minimum / maximum relevant-income levels apply (as configured), or pro-rated / daily levels? | | |
| 3 | `eo_week_start_day` | `SUNDAY` | Hong Kong specialist (G1) — pending, **no archived source** | Is Sunday the statutory week start used for the Employment Ordinance continuous-contract (468) test? No archived source has a recorded hash yet: please name the provision. | | |
| 4 | `eo_average_wage_days_per_year` | `365` | Labour Department, archived SHA-256 `dc9e32d8be3f…` | Is the 12-month average daily wage divided by the 365 days of the period (less excluded days), as configured? | | |
| 5 | `eo_overtime_aw_test_share_pct` | `20` | Labour Department, archived SHA-256 `dc9e32d8be3f…` | Is overtime pay included in the 12-month average wage only when it is regular, tested as at least 20 % of the period's wages, as configured? | | |
| 6 | `basic` → EO_WAGES | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Does pay element `basic` count as Employment Ordinance wages? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 7 | `basic` → MPF_RI | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `97b6c8c42685…` | Does pay element `basic` count as MPF relevant income? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 8 | `basic` → SMW_WAGES | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | Does pay element `basic` count as wages for the Statutory Minimum Wage? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 9 | `basic` → IRD | `SALARY_WAGES` | Inland Revenue Department, archived SHA-256 `f3c47471346d…` | Is pay element `basic` reported in the IRD return category shown? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 10 | `hra` → EO_WAGES | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Does pay element `hra` count as Employment Ordinance wages? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 11 | `hra` → MPF_RI | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `97b6c8c42685…` | Does pay element `hra` count as MPF relevant income? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 12 | `hra` → SMW_WAGES | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | Does pay element `hra` count as wages for the Statutory Minimum Wage? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 13 | `hra` → IRD | `OTHER_REWARDS_ALLOWANCES` | Inland Revenue Department, archived SHA-256 `f3c47471346d…` | Is pay element `hra` reported in the IRD return category shown? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 14 | `special_allowance` → EO_WAGES | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Does pay element `special_allowance` count as Employment Ordinance wages? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 15 | `special_allowance` → MPF_RI | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `97b6c8c42685…` | Does pay element `special_allowance` count as MPF relevant income? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 16 | `special_allowance` → SMW_WAGES | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | Does pay element `special_allowance` count as wages for the Statutory Minimum Wage? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 17 | `special_allowance` → IRD | `OTHER_REWARDS_ALLOWANCES` | Inland Revenue Department, archived SHA-256 `f3c47471346d…` | Is pay element `special_allowance` reported in the IRD return category shown? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 18 | `named_allowances` → EO_WAGES | `REVIEW` | Labour Department, archived SHA-256 `dd61788183c7…` | Does pay element `named_allowances` count as Employment Ordinance wages? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 19 | `named_allowances` → MPF_RI | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `97b6c8c42685…` | Does pay element `named_allowances` count as MPF relevant income? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 20 | `named_allowances` → SMW_WAGES | `REVIEW` | Labour Department, archived SHA-256 `11e750937bf7…` | Does pay element `named_allowances` count as wages for the Statutory Minimum Wage? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 21 | `named_allowances` → IRD | `OTHER_REWARDS_ALLOWANCES` | Inland Revenue Department, archived SHA-256 `f3c47471346d…` | Is pay element `named_allowances` reported in the IRD return category shown? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 22 | `overtime` → EO_WAGES | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Does pay element `overtime` count as Employment Ordinance wages? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 23 | `overtime` → MPF_RI | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `97b6c8c42685…` | Does pay element `overtime` count as MPF relevant income? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 24 | `overtime` → SMW_WAGES | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | Does pay element `overtime` count as wages for the Statutory Minimum Wage? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 25 | `overtime` → IRD | `SALARY_WAGES` | Inland Revenue Department, archived SHA-256 `f3c47471346d…` | Is pay element `overtime` reported in the IRD return category shown? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 26 | `additional_compensation` → EO_WAGES | `REVIEW` | Labour Department, archived SHA-256 `dd61788183c7…` | Does pay element `additional_compensation` count as Employment Ordinance wages? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 27 | `additional_compensation` → MPF_RI | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `97b6c8c42685…` | Does pay element `additional_compensation` count as MPF relevant income? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 28 | `additional_compensation` → SMW_WAGES | `REVIEW` | Labour Department, archived SHA-256 `11e750937bf7…` | Does pay element `additional_compensation` count as wages for the Statutory Minimum Wage? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |
| 29 | `additional_compensation` → IRD | `UNMAPPED_REQUIRES_CLASSIFICATION` | Inland Revenue Department, archived SHA-256 `f3c47471346d…` | Is pay element `additional_compensation` reported in the IRD return category shown? (`REVIEW` = the product refuses it until classified; `UNMAPPED_REQUIRES_CLASSIFICATION` = no IRD box yet) | | |

### General-holiday lists (open items, currently empty)

| List | Pack | Current | Status | Official file / URL you provide | Notes |
|---|---|---|---|---|---|
| General holidays 2025 | pack 2025 | `(not loaded)` | UNVERIFIED / SOURCE_REQUIRED | | |
| General holidays 2026 | pack 2025 | `(not loaded)` | UNVERIFIED / SOURCE_REQUIRED | | |
| General holidays 2026 | pack 2026 | `(not loaded)` | UNVERIFIED / SOURCE_REQUIRED | | |
| General holidays 2027 | pack 2026 | `(not loaded)` | UNVERIFIED / SOURCE_REQUIRED | | |

While a list is empty, the product defers only for weekends and recorded signal days, and shows "general-holiday list not loaded" on the payslip trace and eMPF deadline.

## Time estimate

Engineering's estimate, not a commitment: about 1–2 working days for a specialist to review 29 items and the deferral rule, plus about 1 hour to provide the three holiday files.

## Evidence

* `../G1/G1_statutory_content_review_memo.md` — SHA-256 `ab1d81cc4e11dacfa713e944838ba6a0280442d1fc6335f49f16e0acb6656b0a`
* `../G1/G1_governed_values_worksheet.csv` — SHA-256 `2f1d25fe4867fd0e50a097cdeced7668d38c30c742be00791bade3aff94b0901`
* `../G1/G1_export_run.json` — SHA-256 `6b4e7433926b628ef91e42d23ed16b7fc2bd42265b965e95321dc48b681f8c2e`
* `../decisions/D-G1-internal-review-in-lieu-of-specialist.md` — SHA-256 `5b1c0b111a327b4318d41e6db422627310a37013221989627cbc10b2595459c8`

## Sign-off

I have reviewed every row above. Rows marked Y are correct for the stated period. Rows with a corrected value must be changed and re-reviewed before G1 can pass.

| Name | Role | Date | Decision / conditions | Signature |
|---|---|---|---|---|
| | | | | |
