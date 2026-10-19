# Mexico (MX) — Phase 9b Implementation Report: Aguinaldo run and vacation

Spec ZP-MX-ENG-001 v1.0 §4 MX-009, §17 MX-051–MX-053 · plan `MEXICO_PHASE_9_PLAN.md` (approved 2026-10-19; this is 9b, built under D2, D3, D4 and D8).

**Base.** `nikhil` = `14bf883`, the same tree as `origin/main` `4adac17` (PR #111, Phase 9a). Deploy `39224575881` was green, so production should be at `f5c1a8d3e9b2`.

**Alembic.** Before: a single head, `f5c1a8d3e9b2` (204 revisions). Now: a single head, **`a6d2f9c4b8e1`** (205 revisions).

The work is **staged on `nikhil`**. Nothing is committed, pushed or merged.

**The constraint (unchanged).** No Phase 9 source is saved. Every rule here is a content seam that is **empty**, so in production every aguinaldo payslip and every vacation premium **blocks with a named code**. The computation is proved with SYNTHETIC rules in tests and in the browser.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite, 5 chunks (328 files) on scratch SQLite, after every change in this report | **6,741 passed, 1 failed, 70 skipped, 2 xfailed** (6,814 tests). The failure is **OOS-4**: the HK test reading the untracked local HK owner pack. Not code, not Mexico. |
| Phase 9b tests | `test_mexico_benefits.py` (10) and `test_mexico_benefits_migrations.py` (6, of which 4 run on PostgreSQL). All pass. All Mexico files pass. Three existing tests were updated for the intended change: the engine special-pay test now expects `MX_SPECIAL_PAY_RULE_MISSING`, and AGUINALDO is no longer listed as "refused" in two guard tests. |
| Migration on **PostgreSQL 17** | 4/4 (real CLI, current = head, schema drift clean). The 9a PG tests were re-run alongside; 12/12. |
| Browser | **off 8/8**, **on 8/8** (flag on, rules empty: the production reality once Mexico opens) and **rules 10/10** (SYNTHETIC rules). No 5xx and no page errors; the only 4xx in the on / rules runs is the deliberate four-eyes refusal. Screenshots inspected. |
| ESLint / `check:undefined` / `vite build` | 0 errors in every new or changed file. 523 files clean. The build passes. |

## 2. What was built

**Content seams (`mexico_content.py`, all empty).** Each is a rule *object* written at transcription with its own `source` / `source_ref`; no value is anticipated:
- `MX_SPECIAL_PAY_RULES` — per concept, the exempt part and the standalone withholding (S24 / S25);
- `MX_AGUINALDO_RULE` — the proportion for part of a year and the payable-by date (S26);
- `MX_SPECIAL_PAY_ISN_INCLUSION` — per state and concept, whether the concept is in the ISN base (state code).

**Engine (`engine/jurisdictions/mexico/special_pay.py`).** It fixes only the interface a transcribed rule must provide (`exempt`, `standalone_isr`, `combine_with_ordinary`; `fraction`, `payable_by`) and validates what a rule returns.
- **Missing rule:** `MX_SPECIAL_PAY_RULE_MISSING`, `MX_AGUINALDO_RULE_MISSING` or `MX_ISN_SPECIAL_PAY_RULE_MISSING`. It is **never** the ordinary tariff (MX-009).
- **Preflight** routes special-pay lines to this module instead of the earning classification. It also skips the ordinary-period requirements in a special run.
- **Orchestrator:** a special run (`AGUINALDO`) has no ordinary period, so it has:
  - no IMSS, CEAV or INFONAVIT (contributions are on the SBC per contribution day);
  - no employment subsidy;
  - ISR = the rule's standalone withholding;
  - ISN per the state inclusion rule.

  The result keeps the ordinary shape and adds a `special` trace section.

**Migration `a6d2f9c4b8e1` (mx_benefits_m8)** adds **one new table**, `payroll_mx_vacation_records`, and no shared column. The aguinaldo computation lives in the payslip snapshot (days, fraction, rule refs) like every Mexican line, so plan v1.1's `payroll_mx_aguinaldo_lines` was **not** created (deviation, §5).

**`mexico_benefits_service.py`**
- **Vacation records:**
  - TAKEN (with dates) or OPENING (with a note), per service year (anniversary-exact from the seniority date, MX-053);
  - recorded by one person and approved by another (`MX_FOUR_EYES_REQUIRED`);
  - the balance is checked at approval (`MX_VACATION_BALANCE_EXCEEDED`);
  - PAID_OUT is refused (it is written by the 9c termination workflow);
  - a record can be withdrawn while unpaid.
- **Ledger** per service year: policy days, statutory days ("not transcribed" when the content is missing), opening, taken, paid out, balance.
- **Vacation premium:** an approved TAKEN record adds one `VACATION_PREMIUM` line (days × daily salary × policy premium %) to the ordinary run whose period reaches its start date.
  - Commit marks the record **PAID**, linked to the run and payslip; a reset reopens it.
  - **Which records a run includes depends on its state:**
    - an uncommitted run uses the pending records;
    - a committed run uses the records it paid, so approving a later record never changes a committed run (no approval drift);
    - a correction run uses the records its replaced payslips paid.
  - Two draft runs reaching the same record are caught by the existing stale check after the first commits.
- **Aguinaldo run:** `create_aguinaldo_run(year, pay date)`, one per year, paid within the year, period 1 January – 31 December. It is atomic, as in 9a.
  - **Amount:** labour-policy days, never below the statutory minimum (`MX_LABOR_POLICY_BELOW_FLOOR`), × daily salary × the transcribed fraction, rounded by the content rounding rule.

**Run service / shared touch points**
- `BUILT_RUN_TYPES` now includes `AGUINALDO`; PTU and FINIQUITO stay refused.
- `calc_inputs` has an AGUINALDO branch (`_aguinaldo_inputs`) and adds premium lines to ordinary runs.
- The commit and reset hooks are wired in.
- `engine/base.py`: two MX-only context fields, `mx_run_type` and `mx_special_detail`, both defaulting to None.
- `service.generate_payslips_for_run`: an **MX-only** branch adds employees who joined during the year to an AGUINALDO run (§5.1).

**Routes** (behind the Phase 4a guard):
- `GET` / `POST /employees/{id}/vacation`;
- `POST /vacation/{id}/approve` and `/withdraw`;
- `POST /aguinaldo-runs`.

**Frontend**
- `MXVacationPanel`: in the employee's Mexico statutory panel (ledger, records, approve / withdraw, record form).
- `MXAguinaldoRunPanel`: in Compliance → Mexico Compliance Centre.

## 3. Migration `a6d2f9c4b8e1` — measured on PostgreSQL 17

| Measurement | Result |
|---|---|
| SHARE ROW EXCLUSIVE on `payslip_items` / `payroll_runs` / `payroll_employees` | **53–80 ms** over three runs (57.90, 52.57 and 80.29 ms). |
| In flight | Reads continue; a writer's `ROW EXCLUSIVE NOWAIT` is refused (writes wait about 0.1 s). |
| A writer holding `payslip_items` | Gives up after **5.09–5.22 s** with nothing created. |
| CLI path | `alembic upgrade head`, current = head, schema drift clean. |

## 4. What this does in production when merged

`MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False.

| Change | Production effect |
|---|---|
| Migration `a6d2f9c4b8e1` | **One new, empty table**, no shared column. The head moves `f5c1a8d3e9b2` → `a6d2f9c4b8e1`. About 0.1 s of SHARE ROW EXCLUSIVE; fails fast after about 5 s with nothing created if a writer holds a table. |
| Routes / services | **Unreachable.** The 5 routes return 403 (verified in the browser with the flag off). |
| Engine changes | MX-only. For an ordinary payslip with no special lines the path is unchanged; the special path runs only for AGUINALDO runs or special lines, and none can exist. |
| Content seams | Empty. Once Mexico opens, every aguinaldo payslip and vacation premium blocks with a named code until S24 / S25 / S26 are transcribed. |
| `engine/base.py` fields | Two new optional context fields, None for every country. |
| `generate_payslips_for_run` | A new branch runs only when `run.mx_run_type == "AGUINALDO"`. No other country is affected. |
| Screens | The Compliance Centre panel and the vacation panel show only the dormancy refusal. No other country's screen changes (NL verified in all three modes). |

**Net effect:** one additive table and no behaviour change for any jurisdiction.

## 5. Deviations and findings

1. **The shared selection silently left out mid-year joiners from an aguinaldo run** (found by the directional test). `generate_payslips_for_run` keeps only employees who joined by the period start (1 January), so anyone hired during the year was simply never paid an aguinaldo. An MX-only branch (`year_joiners`), modelled on Singapore's mid-period-joiner hook, now adds them. The directional test proves a July joiner gets a smaller aguinaldo than a full-year employee.
2. **No `payroll_mx_aguinaldo_lines` table.** The computation (days, statutory minimum, daily salary, fraction, payable-by, rule source) is in the payslip snapshot, which is already the audited record of every Mexican line.
3. **An aguinaldo run posts no IMSS / CEAV / INFONAVIT.** This follows the Phase 5 model, where contributions are on the SBC per contribution day and aguinaldo integrates the SBC through the factor. It is an engineering reading of §7 / §8 to confirm with S10.
4. **Leavers** (status not ACTIVE) are not selected for an aguinaldo run. Their proportional aguinaldo belongs to the finiquito (9c).
5. **Vacation premium in an ordinary run blocks that employee's whole payslip** until the special-pay rule exists (fail closed, D2). This was a design choice over silently omitting a legally owed premium.
6. **Whether a service year's days are "available" yet** (LFT Art. 76, S26) is not enforced. A record may use the current or an earlier service year; the balance is the employer policy days for that year.

## 6. Open / next

- **9c** (termination / finiquito) next: it also replaces Phase 8's interim BAJA source and writes PAID_OUT vacation.
- **Sources:** S24 / S25 / S26 / S21 for every Phase 9 rule; S10 confirmation for §5.3.
- **Carried over:** Phase 9a legal questions, Phase 8 X1–X7, Phase 7 D10–D12, G1–G8, Q9, OOS-4.
