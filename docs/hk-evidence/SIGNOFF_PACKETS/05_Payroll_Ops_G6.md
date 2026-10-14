# Sign-off packet 05: Payroll Operations lead (gate G6, and G3 thresholds)

> **Status:** prepared by engineering on 2026-10-14. It contains no decision, value, result or signature made on anyone's behalf. Every evidence link gives the file's SHA-256 when this packet was generated: if the file you open has a different digest, stop and ask engineering.

## What you need to do

1. **Fix runbook #30** in the owner pack (`docs/HONG_KONG_RELEASE_EVIDENCE/G6/OPERATIONS_RUNBOOK.md`, line 131). It still says:
   * title "Database migration (HK release `cd62503afe26`)";
   * precondition "head is `445abd6a9083`";
   * validation "`alembic current` = `cd62503afe26`".

   The HK migration is now **`8b14824fb575`**, on top of production's `b08f04497195`. If engineering merges `nikhil` into `main` first, its parent becomes `main`'s head; see `../ops/HK_DEPLOY_RUNBOOK.md`. Validation should read: `alembic current` = `8b14824fb575`, with the tables `payroll_user_permissions` and `payroll_hk_contribution_day_disruptions` present and 9 new columns on `assisted_access_sessions`. The owner pack is owner-controlled, so engineering has not edited it.
2. **Name a monitoring owner**: the person or team that watches Super Admin → Alerts, including the new high-severity "Security" alert for a break-glass notice that could not be delivered, and the eMPF and IRD deadlines in the G6 calendar.
3. **Set the G3 thresholds**, which engineering has only proposed:
   * absolute tolerance per amount (proposed HKD 1.00, rounding only);
   * percentage tolerance (proposed 0);
   * what counts as a "material" variance (proposed: any unexplained difference on net pay or MPF employee / employer).
4. **Signal days.** Agree who records black-rainstorm / No. 8+ signal days in Statutory Summary → Contribution-day disruptions, and when.
5. Sign G6.

## What to check

* The G6 calendar: contribution days for 2026/27, with 4 weekend deferrals. It is computed **without** general holidays (lists not loaded; packet 01).
* Runbook #22 (privileged access) matches the product: consent, break-glass, and the alert on a failed notice.

## Time estimate

About 2–3 hours, plus the runbook edit.

## Evidence

* `../G6/G6_operations_runbook_cover.md` — SHA-256 `e043f6ace1e09323dc431cdd511053c3aa377761dc2da59691cfe9d7c9679750`
* `../G6/G6_contribution_day_calendar_2026_27.json` — SHA-256 `4b6795b9a07a8aa74b60655e201f550c3c01c4bb29ab2f886b831ea3fab8112a`
* `../G3/G3_parallel_payroll_reconciliation.md` — SHA-256 `991df30c3d932ccc1980472dfd739448effa801945fdd56fbb7a546bd72ff291`
* `../ops/HK_DEPLOY_RUNBOOK.md` — SHA-256 `89ba33cf5726f7d27918341404f30b2a81fd32b40abe15a3f5bc142300bb29b3`
* `../../HONG_KONG_RELEASE_EVIDENCE/G6/OPERATIONS_RUNBOOK.md` — SHA-256 `750cf2745c48a43fc8f9e25c20f20e475ea9f85c25cd34aaa0c35f5914492b46`

## Sign-off

| Item | Decision |
|---|---|
| Runbook #30 corrected (yes / date) | |
| Monitoring owner (name / team) | |
| G3 absolute tolerance (HKD) | |
| G3 percentage tolerance | |
| G3 "material variance" definition | |
| Who records signal days | |

| Name | Role | Date | Decision / conditions | Signature |
|---|---|---|---|---|
| | | | | |
