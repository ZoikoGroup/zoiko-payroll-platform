# G1 — Statutory content review memo (DRAFT for review)

**Status:** DRAFT — Zoiko internal, internally reviewed – pending approval. Not accepted evidence, and not a specialist certification.
**Gate:** HK-GATE-G1 — "Hong Kong specialist signs effective-dated wage, MPF, Employment Ordinance and IRD mappings" (wireframe v1.0 §16).
**Worksheet:** `G1_governed_values_worksheet.csv` — SHA-256 `2f1d25fe4867fd0e50a097cdeced7668d38c30c742be00791bade3aff94b0901` (re-exported 2026-10-13T08:54Z; it now also lists the general-holiday open items). The export command, run time and per-pack counts are in `G1_export_run.json`.

## 1. What is being reviewed

These are all the governed Hong Kong values Zoiko Payroll holds, exactly as the Super Admin Statutory Configuration tab shows them (`hong_kong_service.domains()`), for both rule packs:

| Pack | Year of assessment | Values | UNVERIFIED — G1 | SOURCE_HASH_REQUIRED |
|---|---|---|---|---|
| HK-PAYROLL-2026 v1.0 | 2026/27 (in force 1 Apr 2026 – 31 Mar 2027) | 152 | 28 | 1 |
| HK-PAYROLL-2025 v1.0 | 2025/26 (historic, still used for re-runs) | 153 | 28 | 1 |

The export came from a scratch database seeded with the same canonical seed functions used for production. Production was verified read-only on 2026-10-13: its HK packs and templates exist and are all Draft. Before signing, the reviewer should re-run `python -m scripts.hk_export_g1_worksheet` on production (it opens a read-only session) and compare the digest with the one above.

### Values by domain (2026/27 pack)

| Domain | Values | Authority source (wireframe evidence register) |
|---|---|---|
| MPF | 14 | S3 MPFA (rates, HK$7,100 / HK$30,000 levels, 60-day rule, contribution day and its deferral rule) |
| Minimum Wage | 4 | S5 Labour Department SMW (HK$42.10 to 30 Apr 2026, HK$43.10 from 1 May 2026; HK$17,600 hours-record cap) |
| Continuous Contract | 7 | S6 (17-hour / 68-hour rule from 18 Jan 2026) |
| Average Wage | 4 | S7 Concise Guide Appendix 1 |
| Employment Ordinance Entitlements | 13 | S7 Concise Guide ch. 4–7 |
| Leave & Holidays | 39 | S7 (2026 and 2027 statutory holidays, annual leave scale) |
| SP / LSP | 9 | S7 ch. 11 / S8 MPF offsetting abolition |
| IRD timing | 8 | S1 IRD employer obligations |
| Salaries Tax — informational | 30 | **Outside S1–S10:** IRD PAM 61(e) tax table and the home-loan deduction ceiling notice. These values are informational only, because payroll never withholds Salaries Tax |
| Earning Classification | 24 | Specialist mapping, all `[G1]` |

The wireframe register has no IRD source for the Salaries Tax table (S1 covers employer reporting only). The reviewer should either add a register entry for IRD PAM 61(e) or confirm that these values stay informational.

## 2. Values the reviewer must decide on (same in both packs)

**SOURCE_HASH_REQUIRED (1)** — the value has no hashed official source:

* `eo_week_start_day` = `SUNDAY`. This is the Employment Ordinance "week" used by the 468 / 17-68-hour continuous-contract test. Its source is recorded as "[UNVERIFIED — G1] Employment Ordinance Cap. 57 s.2 definition of 'week'". Needed: the exact Cap. 57 text, archived and hashed, and the specialist's confirmation that a Sunday-to-Saturday week is correct.

**UNVERIFIED — G1 (28)** — the value has a source, but the mapping needs specialist judgement:

* `mpf_contribution_day_deferral` = `NEXT_DAY_NOT_SAT_SUN_OR_GENERAL_HOLIDAY` (added 2026-10-13, source S3). The rule moves the contribution day (10th of the following month) to the next day that is not a Saturday, Sunday or general holiday. Black-rainstorm / No. 8+ days are recorded by an operator. **Open items for the specialist:**
  * Is the rule right?
  * Should it be the "next working day" or the "preceding working day"?
  * Which holiday list governs? The pack holds statutory holidays only; general holidays that are not statutory are not seeded and must come from the official gazetted list.
  * How are partial-day signals treated?

  In 2026/27 it moves 4 dates (G6 calendar).
* `mpf_partial_month_threshold_basis` = `MONTHLY_LEVELS`: which MPF minimum/maximum levels apply to an incomplete monthly wage period.
* `eo_average_wage_days_per_year` = `365`: the divisor for the 12-month average wage (Appendix 1 Example 4 method).
* `eo_overtime_aw_test_share_pct` = `20`: the overtime-inclusion test for the average wage, and its comparison base.
* The 24 `HK_EARNING_CLASS` rows: whether each pay element counts as EO wages, MPF relevant income, SMW wages payable, and IRD-reportable income. The elements are basic pay, housing allowance (hra), special allowance, named allowances, overtime and additional compensation, giving 6 × 4 rows.

**General-holiday lists (open items, `UNVERIFIED / SOURCE_REQUIRED`):** the worksheet now has 4 explicit rows, one per pack per year: 2025 and 2026 in the 2025/26 pack, and 2026 and 2027 in the 2026/27 pack. Each says "General holidays YYYY — list not loaded". These lists feed only the MPF contribution-day deferral. They are loaded from the archived official list with `scripts/hk_load_general_holidays.py`, which records the source SHA-256 and marks the rows [G1]. No date has been typed in. Until a year is loaded, the deferral uses Saturdays, Sundays and recorded signal days only, and flags "general-holiday list not loaded".

## 3. What has been checked internally (Zoiko, not a specialist)

* Every non-flagged value links to an archived source document with a SHA-256 recorded on the platform (column `platform_recorded_sha256`).
* The golden vectors reproduce from each pack's own rows (`test_golden_vectors_reproduce_from_each_packs_own_rows`, part of the G4 run, PASSED).
* Activation refuses a pack that still holds UNVERIFIED or SOURCE_HASH_REQUIRED values. This was observed on 2026-10-13: the scratch activation attempt was refused with "1 SOURCE_HASH_REQUIRED (eo_week_start_day); 27 UNVERIFIED — G1".

No value was changed and none was marked `specialist_verified`.

## 4. What the reviewer is asked to do

1. For each worksheet row, confirm the value, unit and effective dates against the cited source. Then fill `source_document_sha256` from the archived PDF (see `../G2/hk_authority_document_register.md` for the archiving script) and check it equals `platform_recorded_sha256`.
2. For each of the 29 flagged rows: confirm the value, or give the correct value with its source. A correction is made as a new Draft pack version through the Statutory Configuration tab. It is never edited in place.
3. Decide whether the IRD tax-table values need a register entry.
4. Sign below. If the reviewer is not an external Hong Kong specialist, see the optional decision record `../decisions/D-G1-internal-review-in-lieu-of-specialist.md` first.

## 5. Sign-off (leave blank until signed by the named person)

Hong Kong payroll / statutory specialist — Name / Role / Date / Signature: ________
Zoiko Payroll Operations reviewer — Name / Role / Date / Signature: ________
Platform Super Admin who uploads and reviews this evidence (must differ from the registrant) — Name / Role / Date / Signature: ________
