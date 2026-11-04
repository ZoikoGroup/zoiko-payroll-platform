# New Zealand P6: Holidays Act II (leave pay, cash-up, final pay) and non-standard payments: detailed plan and code architecture

**Read first:** `IMPLEMENTATION_HANDOFF_P3_P10.md` §0 (R1–R13). P3, P4 and P5 must be merged.

**Spec coverage:**

| Spec item | P6 coverage |
|---|---|
| §8 | OWP vs AWE (annual holidays); RDP vs ADP (sick, bereavement, family violence, public holidays); public holiday worked = time-and-a-half + alternative holiday; pay-as-you-go 8%; cash-up up to 1 week |
| §10 | out-of-cycle, lump sum / bonus, holiday pay in advance, final pay, rehire |
| NZ-006 | corrections are compensating results, never overwrites |
| NZ-017 | both candidates and the winning reason are preserved; missing evidence blocks |
| NZ-021 | termination never zeroes balances |
| AC-NZ-04 / AC-NZ-08 | AC-NZ-04 is satisfied here; AC-NZ-08 gets its ELA isolation harness here |

**Approach:** content-driven and fail-closed. The statutory formulas (lookback windows, divisors, extra-pay method) are **not stated in the spec**. They become content rows that are **empty by design** until gate G2 (leave pay) or G1 (PAYE methods) signs them. P6 builds and tests the machinery with **TEST** rows. The shipped pack still blocks.

---

## 1. Content additions (`new_zealand_content.py`)

Add scalar rows to `NZ_SCALAR_CONTENT` and `NZ_PARAMETER_KEYS`, every one `pending_g1=True`. These are **all in `NZ_EMPTY_BY_DESIGN` (value None)**, because the spec does not state them:

| key | kind | gate | meaning |
|---|---|---|---|
| `nz_hol_awe_lookback_months` | amount | G2 | AWE gross-earnings lookback (months) |
| `nz_hol_awe_divisor_weeks` | amount | G2 | AWE divisor (weeks) |
| `nz_hol_owp_fallback_weeks` | amount | G2 | OWP fallback lookback when the agreement cannot determine OWP (weeks) |
| `nz_hol_adp_lookback_weeks` | amount | G2 | ADP lookback (weeks) |
| `nz_hol_owp_method` | text | G2 | e.g. `AGREEMENT_THEN_FALLBACK` |
| `nz_hol_rdp_method` | text | G2 | e.g. `AGREEMENT_DAILY` |
| `nz_hol_adp_use_rule` | text | G2 | when ADP replaces RDP (e.g. `RDP_UNDETERMINABLE_OR_VARIES`) |
| `nz_hol_final_pay_unvested_method` | text | G2 | e.g. `PCT_OF_GROSS_SINCE_ANNIVERSARY` |
| `nz_out_of_cycle_paye_method` | text | G1 | `EXTRA_PAY` \| `PERIOD_MAIN` |
| `nz_lump_sum_paye_method` | text | G1 | e.g. `EXTRA_PAY_FOUR_WEEK_ANNUALISE` |

**Spec-stated rows already present and now consumed:**
- `nz_hol_payg_pct` (8)
- `nz_hol_cashup_max_weeks` (1)
- `nz_hol_ph_worked_multiplier` (1.5)
- `nz_hol_annual_weeks` (4)

**Authority tables already declared, now consumed:**
- `NZ_LUMP_SUM` (`lump_sum_method`): method parameters, e.g. the annualisation factor for the extra-pay method.
- `NZ_HOLIDAY_ADVANCE` (`holiday_pay_advance_method`): STANDARD / ALTERNATIVE treatment rows.

**Earning classes:**
- `HOLIDAY_PAY` stays `REVIEW` in the shipped content.
- The `BONUS` and `LUMP_SUM` LUMP_SUM_PATH rows are now **handled** instead of blocking.

The classification of holiday pay for PAYE, ACC, KiwiSaver and student loan is decided at G1. Tests use a TEST pack where it is INCLUDED. **Do not change shipped treatments.**

Update `tests/test_nz_content.py` (catalogue counts, empty-by-design set, slot rules) in the same commit.

---

## 2. File tree after P6

```
backend/alembic/versions/<hex12>_nz_leave_pay.py               (NEW)  4 tables + 2 columns; down_revision = P5 revision
backend/app/modules/payroll/
├── models.py                                                 (EDIT) 4 models + 2 columns
├── engine/jurisdictions/new_zealand/
│   ├── leave_pay.py              (NEW)  pure OWP/AWE/RDP/ADP, PAYG, cash-up, public holiday worked, final pay maths
│   ├── extra_pay.py              (NEW)  pure lump-sum / extra-pay PAYE, ACC, SL and KS treatment
│   ├── components.py             (EDIT) LUMP_SUM_PATH routed instead of blocked
│   └── errors.py                 (EDIT) new codes
├── engine/countries/new_zealand.py                           (EDIT) payment kinds; extra-pay branch; leave-pay lines
├── engine/countries/new_zealand_content.py                   (EDIT) §1 rows
├── nz_leave_pay_service.py       (NEW)  builds leave-pay inputs from the ledger; records calculations; cash-up workflow
├── nz_lifecycle.py               (NEW)  final pay cases, corrections, out-of-cycle / lump-sum / advance runs
├── new_zealand_service.py        (EDIT) calc_inputs adds nz_leave_lines / nz_extra_pay_context; PAID writes calcs
├── nz_leave_service.py           (EDIT) leave events -> PAID; entitlement paid_out
├── nz_org_router.py              (EDIT) +16 routes
backend/tests/ (see §9)
```

---

## 3. Database: migration `<hex12>_nz_leave_pay.py` (WORKER RLS for all tables)

### 3.1 `payroll_nz_leave_pay_calculations` (append-only; NZ-017)
| column | type | null | notes |
|---|---|---|---|
| *(_common, with_updated=False)* | | | |
| employee_id, employment_id | FKs | no | |
| leave_event_id | FK payroll_nz_leave_events SET NULL | yes | |
| public_holiday_decision_id | FK payroll_nz_public_holiday_decisions SET NULL | yes | |
| final_pay_case_id | FK payroll_nz_final_pay_cases SET NULL | yes | |
| run_id, payslip_item_id | FKs SET NULL | yes | filled when paid |
| purpose | String(24) | no | `ANNUAL_LEAVE` \| `SICK` \| `BEREAVEMENT` \| `FAMILY_VIOLENCE` \| `PUBLIC_HOLIDAY_NOT_WORKED` \| `PUBLIC_HOLIDAY_WORKED` \| `ALTERNATIVE_HOLIDAY` \| `CASH_UP` \| `PAYG` \| `FINAL_VESTED` \| `FINAL_UNVESTED` |
| method_pair | String(10) | no | `OWP_AWE` \| `RDP_ADP` \| `PAYG_PCT` \| `PCT_GROSS` |
| candidate_a_name | String(4) | yes | `OWP` / `RDP` |
| candidate_a_amount | Numeric(14,2) | yes | |
| candidate_b_name | String(4) | yes | `AWE` / `ADP` |
| candidate_b_amount | Numeric(14,2) | yes | |
| chosen | String(4) | no | `OWP` / `AWE` / `RDP` / `ADP` / `PCT` |
| statutory_reason | String(200) | no | e.g. `"greater of OWP and AWE (Holidays Act annual holiday pay)"` |
| units | Numeric(8,4) | no | weeks or days paid |
| unit | String(6) | no | `WEEKS` / `DAYS` / `HOURS` |
| rate_amount | Numeric(14,4) | no | per unit |
| amount | Numeric(14,2) | no | `units × rate_amount` (rounded by `nz_hol_pay_rounding`, see below) |
| inputs | JSON | no | lookback window, ledger row ids used, divisor, days worked, agreement figures |
| pack_hash | String(64) | no | |
| status | String(10) | no, default `CALCULATED` | `CALCULATED` \| `PAID` \| `VOID` |

**CHECKs:** the enums; `amount >= 0`; and `chosen IN (candidate_a_name, candidate_b_name, 'PCT')`.

Add a content row **`nz_hol_pay_rounding`** (text, PENDING), also in §1.

### 3.2 `payroll_nz_cash_up_requests`
| column | type | null | notes |
|---|---|---|---|
| *(_common)* | | | |
| employee_id, employment_id, entitlement_id | FKs | no | |
| requested_on | Date | no | |
| written_request_ref | String(300) | no | the evidence of the employee's written request (§8) |
| weeks | Numeric(6,4) | no | checked against `nz_hol_cashup_max_weeks` and the entitlement year's minimum |
| leave_pay_calculation_id | FK | yes | |
| status | String(10) | no, default `REQUESTED` | `REQUESTED` \| `APPROVED` \| `PAID` \| `REJECTED` |

**CHECK:** `weeks > 0`. **Unique** partial: one `REQUESTED|APPROVED` per entitlement.

### 3.3 `payroll_nz_final_pay_cases`
| column | type | null | notes |
|---|---|---|---|
| *(_common)* | | | |
| employee_id, employment_id | FKs | no | |
| termination_date | Date | no | |
| termination_reason | String(30) | no | |
| last_anniversary | Date | yes | computed |
| outstanding | JSON | yes | per entitlement: balance, units, the calculation ids |
| run_id | FK payroll_runs SET NULL | yes | the FINAL run |
| status | String(12) | no, default `OPEN` | `OPEN` \| `CALCULATED` \| `APPROVED` \| `PAID` \| `CANCELLED` |

**Unique** partial: one non-CANCELLED case per employment.

### 3.4 `payroll_nz_corrections` (NZ-006)
| column | type | null | notes |
|---|---|---|---|
| *(_common)* | | | |
| employee_id | FK | no | |
| original_payslip_item_id | FK payslip_items RESTRICT | no | never deleted while corrections exist |
| correction_run_id | FK payroll_runs SET NULL | yes | |
| correction_payslip_item_id | FK payslip_items SET NULL | yes | |
| reason | String(300) | no | operator reason (not HR narrative) |
| input_delta | JSON | no | which inputs changed (component amounts, profile version ids) |
| result_delta | JSON | yes | per obligation: corrected − original |
| status | String(10) | no, default `DRAFT` | `DRAFT` \| `APPROVED` \| `APPLIED` \| `VOID` |

### 3.5 New columns
- **`payslip_items.nz_correction_of_id`** (Integer FK payslip_items SET NULL, nullable). A correction payslip points to the payslip it corrects. Literal `op.add_column("payslip_items", ...)`.
- **`payroll_nz_leave_events.leave_pay_calculation_id`** (FK, nullable). Literal `op.add_column("payroll_nz_leave_events", ...)`.

Update the head pins and the drift-filter column sets (R9): `payslip_items` gains `nz_correction_of_id`, and `payroll_nz_leave_events` gains `leave_pay_calculation_id`.

---

## 4. Pure engine: `engine/jurisdictions/new_zealand/leave_pay.py`

```python
@dataclass
class Candidate: name: str; rate: Decimal | None; steps: list; missing: str | None   # missing = why it can't be computed
@dataclass
class LeavePay:  purpose: str; method_pair: str; a: Candidate | None; b: Candidate | None
                 chosen: str; reason: str; units: Decimal; unit: str; rate: Decimal; amount: Decimal; steps: list

LedgerRow = dict   # {"payDate","periodStart","periodEnd","component","amount","included","treatment","daysWorked"}

def _window(rows, end: date, months=None, weeks=None) -> list   # included rows with period_end in (end - window, end]
def _require_reviewed(rows, pack)        # any row with treatment REVIEW in the window -> block HOL_GROSS_UNREVIEWED (NZ-017)

def owp(agreement_weekly: Decimal | None, ledger, last_period_end, pack) -> Candidate
    # method = pack.text("nz_hol_owp_method")  (empty -> ROW_MISSING blocks)
    # agreement_weekly given -> Candidate("OWP", agreement_weekly, "employment agreement")
    # else fallback: weeks = pack.amount("nz_hol_owp_fallback_weeks"); rows = _window(ledger, last_period_end, weeks=weeks)
    #      excluding components flagged irregular (treatment of BONUS/LUMP_SUM rows -> not counted)
    #      no rows -> Candidate("OWP", None, missing="no gross earnings in the OWP fallback window")
    #      rate = sum(rows) / weeks

def awe(ledger, last_period_end, pack) -> Candidate
    # months = pack.amount("nz_hol_awe_lookback_months"); divisor = pack.amount("nz_hol_awe_divisor_weeks")
    # rows = _window(ledger, last_period_end, months=months); _require_reviewed(rows, pack)
    # no rows -> missing; rate = sum(included) / divisor

def rdp(agreement_daily: Decimal | None, pack) -> Candidate
    # pack.text("nz_hol_rdp_method"); agreement_daily None -> missing "relevant daily pay cannot be determined"

def adp(ledger, last_period_end, pack) -> Candidate
    # weeks = pack.amount("nz_hol_adp_lookback_weeks"); rows = _window(..., weeks=weeks); _require_reviewed
    # days = sum(daysWorked) (any row missing daysWorked -> missing "days worked unknown")
    # days == 0 -> missing; rate = sum(included) / days

def annual_leave_pay(weeks_taken, agreement_weekly, ledger, last_period_end, pack) -> LeavePay
    # a, b = owp(...), awe(...)
    # both missing -> block LEAVE_EVIDENCE_MISSING (NZ-017: missing OWP/AWE evidence is blocking)
    # one missing  -> block LEAVE_EVIDENCE_MISSING as well (the greater-of comparison needs both; never assume)
    # chosen = "OWP" if a.rate >= b.rate else "AWE"; reason "greater of OWP and AWE"
    # amount = rnd(weeks_taken * chosen_rate)  [rnd = pack.rounder("nz_hol_pay_rounding")]

def daily_leave_pay(purpose, days, agreement_daily, ledger, last_period_end, pack) -> LeavePay
    # rule = pack.text("nz_hol_adp_use_rule")
    # a = rdp(...); b = adp(...)
    # rule RDP_UNDETERMINABLE_OR_VARIES: use RDP when a.rate is not None and not ctx["daily_pay_varies"], else ADP
    # the chosen candidate missing -> block LEAVE_EVIDENCE_MISSING; both candidates are stored either way
    # amount = rnd(days * rate)

def public_holiday_worked_pay(hours_on_holiday, hourly_rate, pack) -> LeavePay
    # multiplier = pack.amount("nz_hol_ph_worked_multiplier"); hourly_rate None -> block LEAVE_EVIDENCE_MISSING
    # amount = rnd(hours * hourly_rate * multiplier); purpose PUBLIC_HOLIDAY_WORKED; chosen "RDP"
    # (the alternative holiday itself was created in P5)

def payg_holiday_pay(gross_this_period, employment, pack) -> LeavePay
    # employment.payg_eligible False -> block PAYG_NOT_ELIGIBLE (never a default for "casual")
    # pct = pack.pct("nz_hol_payg_pct"); amount = rnd(gross_this_period * pct / 100); method_pair PAYG_PCT; chosen PCT

def cash_up_pay(weeks, entitlement, agreement_weekly, ledger, last_period_end, pack) -> LeavePay
    # weeks > pack.amount("nz_hol_cashup_max_weeks") -> block CASHUP_LIMIT
    # weeks > balance -> block CASHUP_LIMIT; else annual_leave_pay(weeks, ...) with purpose CASH_UP

def final_pay(entitlements, employment, termination_date, ledger, agreement_weekly, last_period_end, pack) -> list[LeavePay]
    # vested: each ANNUAL entitlement balance (weeks) > 0 -> annual_leave_pay(balance, ...) purpose FINAL_VESTED
    #         (alternative-holiday balances -> daily_leave_pay purpose ALTERNATIVE_HOLIDAY)
    # unvested: method = pack.text("nz_hol_final_pay_unvested_method") (PCT_OF_GROSS_SINCE_ANNIVERSARY)
    #           gross = included ledger since the last anniversary (or start), minus holiday pay already paid in advance
    #           amount = rnd(gross * pack.pct("nz_hol_payg_pct") / 100); purpose FINAL_UNVESTED
    #           (skipped when employment.payg_eligible - already paid as you go)
    # sick, bereavement and family-violence balances are NOT paid out (no entitlement to payment on termination)
    #   -> listed in the result with amount 0 and reason "not payable on termination" (NZ-021: resolved, not zeroed)
```

## 5. Pure engine: `engine/jurisdictions/new_zealand/extra_pay.py`

```python
@dataclass
class ExtraPayResult: paye: Decimal; acc_levy: Decimal; student_loan: Decimal; ks_employee: Decimal
                      ks_employer_gross: Decimal; esct: Decimal; method: str; steps: list

def extra_pay_paye(extra, prior_four_week_gross, code, pack) -> (Decimal, list)
    # method = pack.text("nz_lump_sum_paye_method"); rows = pack.table(NZ_LUMP_SUM_RULE, "lump_sum_method")
    # EXTRA_PAY_FOUR_WEEK_ANNUALISE: factor = the row named ANNUALISATION_FACTOR (flat_amount)
    #   annual = prior_four_week_gross * factor
    #   tax = band_tax(annual + extra) - band_tax(annual)   (P3 paye.band_tax with the NZ_PAYE_BAND table)
    #   ME codes: IETC effect per the method rows (none signed -> block TABLE_EMPTY:lump_sum_method)
    #   SECONDARY / ND / STC codes: flat rate of that branch × extra (P3 functions)
    # unknown method -> block ROW_MISSING:nz_lump_sum_paye_method
def calculate_extra_pay(extra, prior_four_week_gross, code, profile, election, dob, pay_date, accumulators, notices, pack)
    -> ExtraPayResult
    # PAYE: extra_pay_paye; ACC: acc_earner_levy.calculate_levy(extra, accumulators, pack) (cap shared - NZ-013)
    # SL: code SL -> extra × nz_sl_rate (no pay-period threshold on extra pay - confirm at G1; method row
    #     SL_ON_EXTRA_PAY=WHOLE in NZ_LUMP_SUM rows, else block)
    # KiwiSaver: on extra pay only when the KIWISAVER class of the component is INCLUDED (content decides);
    #            employer contribution + ESCT as P3
```

## 6. Engine changes in `engine/countries/new_zealand.py`

**Payment kinds** (`ctx.nz_payment_kind`):

| kind | Behaviour |
|---|---|
| REGULAR | P3 pipeline, plus leave-pay lines added as `HOLIDAY_PAY` components (§6.1) |
| OUT_OF_CYCLE | `nz_out_of_cycle_paye_method`: `PERIOD_MAIN` → the P3 pipeline as a separate payment; `EXTRA_PAY` → the extra-pay branch |
| LUMP_SUM | BONUS / LUMP_SUM components → the extra-pay branch; any SALARY / OVERTIME in the same payslip → block `LUMP_SUM_MIXED` (lump sums are their own payment) |
| HOLIDAY_PAY_ADVANCE | `NZ_HOLIDAY_ADVANCE` row STANDARD or ALTERNATIVE (`ctx.nz_holiday_advance_method`, chosen by the operator per run, allowed values from the table); STANDARD spreads PAYE over the covered periods (`ctx.nz_advance_periods`), ALTERNATIVE taxes it as extra pay |
| FINAL | the REGULAR pipeline for final wages, plus final-pay `LeavePay` lines taxed as extra pay (§6.2) |
| CORRECTION | the REGULAR pipeline on corrected inputs; the result carries `correctionOf` and `deltas` (§7.2) |

### 6.1 Leave-pay lines in a regular pay
- `ctx.nz_leave_lines` (supplied by `calc_inputs`) is a list of `{"calculationId", "purpose", "amount"}` for leave taken in the period. These are pre-calculated by `nz_leave_pay_service`, so the engine stays pure.
- The engine adds their sum to the `HOLIDAY_PAY` component (or `PUBLIC_HOLIDAY_WORKED` amounts to `OVERTIME`, if the content says so; default `HOLIDAY_PAY`).
- It does **not** recompute leave pay. The calculation row is the source of truth and is listed in `nz_result["leavePay"]`.
- Under the shipped content `HOLIDAY_PAY` is REVIEW, so any regular pay with leave blocks until G1/G2 sign the classification. This is the intended state.

### 6.2 Final pay
- `ctx.nz_final_pay_lines` holds `LeavePay` results (from `nz_lifecycle.calculate_final_pay`).
- The engine taxes the sum through `extra_pay.calculate_extra_pay`.
- `nz_result["finalPay"]` holds the lines plus the extra-pay result.

### 6.3 New error codes (`errors.py`)
`LEAVE_EVIDENCE_MISSING`, `HOL_GROSS_UNREVIEWED`, `PAYG_NOT_ELIGIBLE`, `CASHUP_LIMIT`, `LUMP_SUM_MIXED`, `ADVANCE_METHOD_INVALID`, `CORRECTION_POLICY_PENDING`, `FINAL_PAY_OPEN`.

### 6.4 `components.py`
`LUMP_SUM_PATH` no longer blocks. `obligation_base` returns `{"base", "lines", "lumpSum": Decimal}`; LUMP_SUM_PATH amounts go to `lumpSum` and never into the regular base.

---

## 7. Services

### 7.1 `nz_leave_pay_service.py`
```python
def ledger_for(db, org_id, employee_id, employment_id) -> list[LedgerRow]    # from payroll_nz_gross_earnings_ledger
def agreement_rates(db, org_id, employee_id, on) -> (weekly | None, daily | None, hourly | None, varies: bool)
    # from the ACTIVE work pattern + employee pay: FIXED pattern + salary -> weekly = salary per period / weeks per period;
    # daily = weekly / contracted_days; hourly = weekly / contracted_hours; VARIABLE -> (None, None, None, True)
def calculate_for_event(db, org_id, event_id, actor_id) -> LeavePayCalculation row
    # ANNUAL -> leave_pay.annual_leave_pay; SICK / BEREAVEMENT_* / FAMILY_VIOLENCE / ALTERNATIVE -> daily_leave_pay
    # writes payroll_nz_leave_pay_calculations (status CALCULATED, both candidates, reason, inputs, pack_hash)
    # family-violence rows: purpose FAMILY_VIOLENCE kept, and the row is filtered by the P5 restricted-view rules
def calculate_for_public_holiday(db, org_id, decision_id, actor_id) -> row
    # APPROVED decision: worked -> public_holiday_worked_pay(hours_on_holiday, hourly);
    #                    not worked and OWD YES -> daily_leave_pay(PUBLIC_HOLIDAY_NOT_WORKED, 1 day)
def leave_lines_for_run(db, run, employee) -> list[dict]
    # CALCULATED rows whose event / decision dates fall in [run.period_start, run.period_end] and are not yet PAID
def request_cash_up(db, org_id, employee_id, entitlement_id, weeks, written_request_ref, actor_id) -> row
def approve_cash_up(db, org_id, request_id, actor_id) -> row     # four-eyes; computes cash_up_pay; links the calculation
def mark_paid(db, run) -> None
    # at PAID: calculations -> PAID (run_id, payslip_item_id); events -> PAID; cash-ups -> PAID;
    # entitlements paid_out += units for CASH_UP / FINAL_*
```

### 7.2 `nz_lifecycle.py`
```python
def open_final_pay_case(db, org_id, employee_id, termination_date, termination_reason, actor_id, reason) -> case
    # one per employment; employment must be ACTIVE; termination_date >= start
def calculate_final_pay(db, org_id, case_id, actor_id) -> case
    # vest_entitlements(as_of=termination_date) first (P5) so nothing vested is missed
    # lines = leave_pay.final_pay(...); write a calculation row per line (final_pay_case_id); case.outstanding; CALCULATED
def approve_final_pay(db, org_id, case_id, actor_id) -> case      # four-eyes
def on_final_run_paid(db, run) -> None
    # case PAID; employment.end_date = termination_date, status ENDED, termination_reason
    # entitlements: paid ones -> PAID_OUT; non-payable (sick / bereavement / FV) -> remain with status ACTIVE and expires_on =
    #   termination_date (history kept - NZ-021 "never simply zero")
def create_out_of_cycle_run(db, org_id, *, kind, pay_date, period_start, period_end, employee_ids, actor_id, reason) -> run
    # PayrollRun(nz_payment_kind=kind ∈ OUT_OF_CYCLE | LUMP_SUM | HOLIDAY_PAY_ADVANCE | FINAL), via the existing run create
def create_correction(db, org_id, original_item_id, input_delta, reason, actor_id) -> correction
    # pack.text("nz_correction_policy") PENDING -> 409 CORRECTION_POLICY_PENDING (shipped behaviour)
    # original must be PAID; never modified (NZ-006)
    # replay the original frozen context (P4 nz_thaw_context), apply input_delta, recalculate
    # result_delta = corrected − original per obligation; status DRAFT
def approve_correction(db, org_id, correction_id, actor_id)        # four-eyes
def apply_correction(db, org_id, correction_id, actor_id)
    # creates a CORRECTION run (or adds to an open one) with a payslip carrying ONLY the deltas;
    # payslip.nz_correction_of_id = original id; at PAID the accumulators post entry_kind="CORRECTION"
    # (P4 post_accumulators: kind from the run's nz_payment_kind); P8 later links an AMENDMENT filing
def rehire(db, org_id, employee_id, start_date, continuity_rule, actor_id, reason, evidence_ref=None)
    # previous employment must be ENDED; creates a P5 employment (NEW_INSTANCE by default)
```

### 7.3 `new_zealand_service.py` edits
- **`resolve_nz_calc_inputs`:** add
  - `nz_leave_lines = nz_leave_pay_service.leave_lines_for_run(db, run, employee)` for REGULAR / FINAL;
  - `nz_final_pay_lines` from an APPROVED case whose run is this run;
  - `nz_prior_four_week_gross` = the sum of PAYE_GROSS accumulator entries with pay_date in the 4 weeks before the payday (LUMP_SUM / OUT_OF_CYCLE / FINAL / ALTERNATIVE advance);
  - `nz_holiday_advance_method` and `nz_advance_periods` from the run, read from the new `payroll_runs.nz_run_options` JSON column (below), not from separate columns or the approval fingerprint.
- **`before_run_transition` PAID:** `nz_leave_pay_service.mark_paid(db, run)`, then `nz_lifecycle.on_final_run_paid(db, run)` for FINAL runs.
- **`post_accumulators`:** `entry_kind = "CORRECTION"` when `run.nz_payment_kind == "CORRECTION"`.
- **`nz_run_preflight`:** add `NZ_LEAVE_PAY_UNCALCULATED` (an approved leave event in the period without a calculation) and `NZ_FINAL_PAY_OPEN` (FINAL run without an APPROVED case).

The migration therefore adds a third column, **`payroll_runs.nz_run_options`** (JSON, nullable). It holds `{"holidayAdvanceMethod", "advancePeriods", "finalPayCaseId"}`.

---

## 8. Routes (add to `nz_org_router.py`)

| Method / path | Handler | Auth |
|---|---|---|
| POST `/leave-events/{event_id}/calculate-pay` | `nz_calculate_leave_pay` | admin |
| POST `/public-holiday-decisions/{id}/calculate-pay` | `nz_calculate_public_holiday_pay` | admin |
| GET `/employees/{eid}/leave-pay-calculations` | `nz_list_leave_pay` (restricted filter) | operator |
| POST `/employees/{eid}/cash-ups` | `nz_request_cash_up` | admin |
| POST `/cash-ups/{id}/approve` · `/reject` | `nz_approve_cash_up`, `nz_reject_cash_up` | admin |
| POST `/employees/{eid}/final-pay-cases` | `nz_open_final_pay` | admin |
| POST `/final-pay-cases/{id}/calculate` · `/approve` · `/cancel` | `nz_calculate_final_pay`, `nz_approve_final_pay`, `nz_cancel_final_pay` | admin |
| GET `/final-pay-cases/{id}` | `nz_get_final_pay` | operator |
| POST `/runs/out-of-cycle` (`{kind, payDate, periodStart, periodEnd, employeeIds, options, reason}`) | `nz_create_out_of_cycle_run` | admin |
| POST `/payslips/{item_id}/corrections` | `nz_create_correction` | admin |
| POST `/corrections/{id}/approve` · `/apply` · `/void` | `nz_approve_correction`, `nz_apply_correction`, `nz_void_correction` | admin |
| POST `/employees/{eid}/rehire` | `nz_rehire` | admin |

Regenerate the route registry (R10).

---

## 9. Tests

All tests use the TEST pack (P3 helpers), extended with TEST rows for every §1 key and the `NZ_LUMP_SUM` / `NZ_HOLIDAY_ADVANCE` tables. The TEST pack also sets `HOLIDAY_PAY` to INCLUDED **in the fixture only**.

| File | Tests |
|---|---|
| `test_nz_leave_pay_engine.py` | `test_owp_beats_awe`, `test_awe_beats_owp`, `test_equal_prefers_owp_and_records_reason`, `test_owp_fallback_window`, `test_awe_window_and_divisor_from_content`, `test_missing_owp_or_awe_blocks`, `test_unreviewed_gross_row_blocks`, `test_rdp_used_when_determinable`, `test_adp_when_rdp_undeterminable`, `test_adp_when_daily_pay_varies`, `test_adp_days_unknown_blocks`, `test_public_holiday_worked_time_and_half`, `test_payg_eligible_only`, `test_cash_up_limit_and_balance`, `test_final_pay_vested_and_unvested`, `test_final_pay_skips_unvested_when_payg`, `test_final_pay_sick_not_paid_but_listed`, `test_every_number_from_content` |
| `test_nz_extra_pay_engine.py` | `test_extra_pay_annualise_difference`, `test_extra_pay_secondary_flat`, `test_extra_pay_acc_shares_cap`, `test_extra_pay_sl_whole`, `test_lump_sum_mixed_with_salary_blocks`, `test_shipped_lump_sum_table_empty_blocks`, `test_holiday_advance_standard_vs_alternative`, `test_out_of_cycle_method` |
| `test_nz_leave_pay_service.py` | `test_calculation_row_keeps_both_candidates`, `test_leave_lines_feed_regular_run`, `test_leave_pay_marked_paid_once`, `test_cash_up_requires_written_request_and_second_person`, `test_cash_up_reduces_entitlement_on_paid`, `test_family_violence_calculations_restricted` |
| `test_nz_final_pay.py` | `test_open_case_once_per_employment`, `test_calculate_vests_first`, `test_approve_four_eyes`, `test_final_run_paid_ends_employment_without_zeroing`, `test_preflight_blocks_final_run_without_case`, `test_rehire_new_instance_new_anniversaries` |
| `test_nz_corrections.py` | `test_correction_refused_while_policy_pending`, `test_original_never_modified`, `test_delta_payslip_only_differences`, `test_correction_accumulator_entries_kind`, `test_replay_of_original_unchanged_after_correction` |
| `test_nz_ela_isolation.py` | `test_ela_pack_never_resolves_before_2028_08_06` (`tax_resolver` for every month to 2028-08-05), `test_ela_pack_activation_refused`, `test_calc_inputs_never_select_ela`, `test_holidays_act_rules_still_used_on_2028_08_05` |
| migration tests | `test_nz_leave_pay_migration.py`: RLS, contract, replay, downgrade, drift, manifest, `test_chosen_must_be_a_candidate`, `test_cash_up_one_open_per_entitlement`, `test_one_final_case_per_employment`, `test_original_payslip_restrict_on_delete` |

---

## 10. Worked example (TEST content; illustrative)

**Annual leave of 1 week.**
- The agreement's OWP is 1,200.00 / week.
- The ledger over the AWE window (TEST: 12 months, divisor 52) sums 67,600.00 → AWE = 1,300.00.
- Greater of the two = **AWE 1,300.00**, with reason `"greater of OWP and AWE"`.
- The calculation row stores both candidates. The regular payslip gets `HOLIDAY_PAY` 1,300.00, taxed in the normal pipeline.

**Final pay.**
- Termination falls 5 months after the last anniversary.
- Vested balance 1.5 weeks × AWE 1,300.00 = 1,950.00.
- Unvested: TEST gross since the anniversary is 26,000.00 × 8% = 2,080.00.
- Total final holiday pay is 4,030.00, taxed through the extra-pay method (TEST annualisation row).
- Sick balance of 6 days: listed, amount 0, `"not payable on termination"`.

## 11. Definition of done
- [ ] With the shipped content, every leave-pay, lump-sum, advance and correction path blocks with a named content key. With the TEST content, all §9 tests pass.
- [ ] Every leave-pay calculation row stores both candidates, the winner and the statutory reason (NZ-017).
- [ ] A final pay resolves every entitlement; no balance is silently zeroed (NZ-021).
- [ ] Corrections never modify the original; accumulators post `CORRECTION` entries (NZ-006).
- [ ] ELA 2028 cannot be selected or activated (AC-NZ-08).
- [ ] The migration has a single head, the manifest and head pins are updated, the route registry is regenerated, and the full suite is green. One local commit, not pushed.
