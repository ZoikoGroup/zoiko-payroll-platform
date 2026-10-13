# G6 — Operations: runbook cover, filing and payment calendar (DRAFT for review)

**Status:** DRAFT — Zoiko internal, internally reviewed – pending approval. Not accepted evidence.
**Gate:** HK-GATE-G6 — "Filing/payment responsibilities, maker-checker, reconciliation, support and incident runbooks are approved" (wireframe v1.0 §16).

## 1. The runbooks already exist; this is a cover, not a rewrite

The operating procedures are in the owner-controlled pack `docs/HONG_KONG_RELEASE_EVIDENCE/G6/`. They were read, not modified. Writing a second set would leave two versions to keep in step, so this cover indexes them, checks them against the code as of 2026-10-13, and adds the dated calendar the pack lacks.

| Topic requested | Where it is | SHA-256 (first 16) | Checked against code |
|---|---|---|---|
| Filing / payment responsibilities | `G6/FILING_RESPONSIBILITY_MATRIX.md`; runbook #8–#13 | 4b7c09c91791e0e2 / 750cf2745c48a43f | Yes: IRD forms and eMPF states match `ird.py` / `hong_kong_service.py:1335-1339` |
| Maker-checker | `G6/MAKER_CHECKER_MATRIX.md` | 5921d38029f056d7 | Yes: see §3 |
| Reconciliation | runbook #9 (eMPF), #13 (BIR56A/IR56B "Reconciled"), plus the new G3 tool | 750cf2745c48a43f | Yes |
| Support (privileged access) | runbook #22 (updated 2026-10-13 to match the consent / break-glass code) | 750cf2745c48a43f | **Yes:** tenant consent and break-glass are now implemented and tested (G5 F-3 / F-7 closed) |
| Incident response | `G6/INCIDENT_PROCEDURE.md`; runbook #23, #27, #39 | 538e26d9c7b814f8 | Yes |
| IR56G departure hold | runbook #12 | 750cf2745c48a43f | Yes: see §4 |
| DR / rollback | `G6/DR_PROCEDURE.md`; runbook #25, #30, #37–38 | 6ae42c7849c2fcc3 | **Stale:** #30 names migration `cd62503afe26`. The single head is now `b08f04497195`, which production is already at |
| Version upgrade | `G6/VERSION_UPGRADE_PROCEDURE.md` | dcdd5dacca9e0dfd | Yes |

Items the owner should correct in the pack (not done here):
* Runbook #30: update the migration id.
* Runbook #8 / monitoring: alert delivery is not wired in code. Monitoring is Super Admin counts only (`hong_kong_service.py:2785-2852`), so the PROD_MONITORING procedure must say who checks it and how often.

## 2. Filing and payment calendar, YA 2026/27

Computed on 2026-10-13 from the HK-PAYROLL-2026 v1.0 pack rows (scratch copy of the canonical seed) with the engine's own date functions (`mpf.period_contribution_day`, `mpf.contribution_due_date`, `ird.due_date`, `tax_clearance.statutory_hold_expiry`). The machine output is `G6_contribution_day_calendar_2026_27.json`. Pack rows used: `mpf_contribution_day` = 10; `ird_ir56e_months` = 3; `ird_ir56f_months_before` = 1; `ird_ir56g_months_before` = 1; `ird_ir56g_hold_months` = 1; `ird_ir56b_due_months` = 1; `ird_return_issue_month` = 4; `ird_return_issue_day` = 1. These values are G1 content and are not yet certified.

### MPF contribution days: base day vs the governed deferral rule

Recomputed 2026-10-13T08:54Z after the general-holiday change. The result is identical: the deferral now reads only the governed **general-holiday** list (`HK_GENERAL_HOLIDAY`), which is not loaded for 2026 / 2027, so weekends only apply, with the flag "general-holiday list not loaded". The deferral rule is the pack row `mpf_contribution_day_deferral` = `NEXT_DAY_NOT_SAT_SUN_OR_GENERAL_HOLIDAY`. It is **[G1] UNVERIFIED** (source MPFA "Mandatory Contributions — Employees", S3) until the Hong Kong specialist certifies it. The calendar below uses weekends only, because no general-holiday list is loaded and no disruption day is recorded.

| Wage period | Base (10th) | After deferral | Moved because |
|---|---|---|---|
| 2026-04 | **Sun 2026-05-10** | **Mon 2026-05-11** | Sunday |
| 2026-05 | Wed 2026-06-10 | Wed 2026-06-10 | — |
| 2026-06 | Fri 2026-07-10 | Fri 2026-07-10 | — |
| 2026-07 | Mon 2026-08-10 | Mon 2026-08-10 | — |
| 2026-08 | Thu 2026-09-10 | Thu 2026-09-10 | — |
| 2026-09 | **Sat 2026-10-10** | **Mon 2026-10-12** | Saturday, Sunday |
| 2026-10 | Tue 2026-11-10 | Tue 2026-11-10 | — |
| 2026-11 | Thu 2026-12-10 | Thu 2026-12-10 | — |
| 2026-12 | **Sun 2027-01-10** | **Mon 2027-01-11** | Sunday |
| 2027-01 | Wed 2027-02-10 | Wed 2027-02-10 | — |
| 2027-02 | Wed 2027-03-10 | Wed 2027-03-10 | — |
| 2027-03 | **Sat 2027-04-10** | **Mon 2027-04-12** | Saturday, Sunday |

**Still open for G1** (in the worksheet and `../BLOCKERS.md`):
* The rule itself needs specialist certification.
* The general-holiday lists for 2026 and 2027 are **not loaded** (SOURCE_REQUIRED in the G1 worksheet). A person archives the official list and loads it with `scripts/hk_load_general_holidays.py` (SHA-256 recorded, [G1]). Statutory-holiday rows are no longer used by the deferral.
* Black-rainstorm / No. 8+ signal days are recorded by a Super Admin under Statutory Summary & Gates → "MPF contribution-day disruption days" (reason required, audited). They then move the eMPF batch deadline. Nothing is taken from a weather feed.

### IRD returns

| Return | Rule (from pack) | 2026/27 date or example |
|---|---|---|
| BIR56A + IR56B | 1 month after the return is issued (default issue date 1 April) | Due **2027-05-01** if issued on 1 Apr 2027. If IRD issues it on another date, use 1 month after that date (`return_issue_date`) |
| IR56E | Within 3 months of commencement | Example: start 2026-06-15 → due 2026-09-15 |
| IR56F | 1 month before cessation | Example: cessation 2026-09-30 → due 2026-08-30 |
| IR56G | 1 month before departure (absence over 1 month) | Example: departure 2026-11-30 → due 2026-10-30 |
| IR56G hold | Money held after filing until a Letter of Release, or 1 month after filing | Example: filed 2026-10-30 → statutory period ends 2026-11-30; release still needs evidence and a second approver |

## 3. Maker-checker controls in code (each refuses approver = maker)

* IRD case FILED (`hong_kong_service.py:822`)
* Average-wage override (`:1161`)
* Termination approval (`:1325`)
* eMPF SUBMITTED (`:1482`)
* Payroll correction approval (`:3238`, `:3366`)
* Evidence review (`review_evidence`)
* eMPF configuration activation (`:2772`)
* IR56G hold release (`tax_clearance.py:81-84`)
* Legal-hold release and retention approval (`retention_service.py`)
* Pack approval and activation (shared)

Normal HK payroll-run approval is single-operator today, with the preflight blocking; see owner decision D-8.

## 4. IR56G departure hold (code behaviour the runbook relies on)

* Payslips that are HELD, FINAL_PAY_BLOCKED or RECOVERY_NOT_PAID are left out of the bank file (`service.py:31920-31930`; rules at `hong_kong_service.py:523-557`).
* Held net pay stays owed and is traced in hold lines. It is never deducted.
* Release is never automatic. It needs a LETTER_OF_RELEASE (with a reference) or STATUTORY_PERIOD_ELAPSED, plus evidence and a second approver.

Tested: G4 R6 (`test_case_i_ir56g_hold_bank_export_ledger_and_four_eyes_release`, `test_bank_export_leaves_out_held_payslips`, both PASSED).

## Sign-off (leave blank until signed by the named person)

Payroll Operations lead — Name / Role / Date / Signature: ________
Support lead — Name / Role / Date / Signature: ________
Engineering on-call lead — Name / Role / Date / Signature: ________
