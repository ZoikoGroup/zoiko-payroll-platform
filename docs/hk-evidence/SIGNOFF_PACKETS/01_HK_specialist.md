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
| 6 | `HK_OVERTIME_CONTRACT` (Overtime pay at the contractual rate) → IR56B | `SALARY_WAGES (11(a))` (proposed; **PENDING** — not applied as certified) | Inland Revenue Department, archived SHA-256 `d43073a74315…` | The archived IR56B notes do not name overtime pay. Is contractual overtime pay reported in item 11(a) Salary/Wages (or another item)? | | |
| 7 | `HK_EXPENSE_REIMB` (Reimbursement of expenses incurred in the employment) → IR56B | `EXCLUDED` (proposed; **PENDING** — not applied as certified) | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 10(d) reports reimbursement of PERSONAL expenses in item 11(k). Are receipted reimbursements of expenses incurred in performing the employment duties left off the IR56B? | | |
| 8 | `HK_BONUS_CONTRACT` (Bonus / 13th-month pay due under the contract) → EO wages | `INCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3 excludes only gratuitous / discretionary end-of-year payments from wages. Is a contractual annual bonus or 13th-month pay 'wages' (e.g. for 12-month average wages and holiday pay)? | | |
| 9 | `HK_BONUS_CONTRACT` (Bonus / 13th-month pay due under the contract) → SMW wages | `INCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `11e750937bf7…` | Does a contractual annual bonus count towards SMW wages of the wage period in which it is paid? | | |
| 10 | `HK_ATTENDANCE_ALLOW` (Attendance allowance (contractual)) → IR56B | `OTHER_REWARDS_ALLOWANCES (11(k))` (proposed; **PENDING** — not applied as certified) | Inland Revenue Department, archived SHA-256 `d43073a74315…` | Is a contractual attendance allowance reported in item 11(k) (other rewards / allowances) or in item 11(a)? | | |
| 11 | `HK_LEAVE_PAY` (Holiday / annual leave / sickness allowance pay) → EO wages | `INCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `dd61788183c7…` | Is statutory holiday / annual leave pay / sickness allowance itself 'wages' for the EO wages base of later entitlements (12-month average), or excluded from that base? | | |
| 12 | `HK_LEAVE_PAY` (Holiday / annual leave / sickness allowance pay) → SMW wages | `INCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `11e750937bf7…` | How are paid leave days and their pay treated in the SMW hours / wages test? | | |
| 13 | `HK_LEAVE_PAY` (Holiday / annual leave / sickness allowance pay) → IR56B | `SALARY_WAGES (11(a))` (proposed; **PENDING** — not applied as certified) | Inland Revenue Department, archived SHA-256 `d43073a74315…` | The archived IR56B notes do not describe item 11(b) Leave pay. Is paid leave reported in 11(b) or within 11(a)? | | |
| 14 | `HK_PILON` (Payment in lieu of notice) → EO wages | `EXCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `dd61788183c7…` | Is payment in lieu of notice excluded from the EO wages base used for other entitlements? | | |
| 15 | `HK_PILON` (Payment in lieu of notice) → MPF relevant income | `INCLUDED` (proposed; **PENDING** — not applied as certified) | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | The archived MPFA examples table does not list payment in lieu of notice. Is it relevant income? | | |
| 16 | `HK_PILON` (Payment in lieu of notice) → SMW wages | `EXCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `11e750937bf7…` | Is payment in lieu of notice excluded from SMW wages? | | |
| 17 | `HK_SEVERANCE_LSP` (Statutory severance / long service payment) → EO wages | `EXCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `dd61788183c7…` | Confirm statutory SP / LSP is not 'wages' (it is calculated FROM wages). | | |
| 18 | `HK_SEVERANCE_LSP` (Statutory severance / long service payment) → SMW wages | `EXCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `11e750937bf7…` | Confirm statutory SP / LSP is excluded from SMW wages. | | |
| 19 | `HK_ALLOWANCE_UNSPEC` (Named allowance not yet given its own code) → EO wages | `INCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `dd61788183c7…` | Classify each named allowance: contractual (wages), gratuitous / discretionary, or reimbursement of expenses. | | |
| 20 | `HK_ALLOWANCE_UNSPEC` (Named allowance not yet given its own code) → SMW wages | `INCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `11e750937bf7…` | As for EO wages: classify each named allowance before it counts for SMW. | | |
| 21 | `HK_OTHER_UNCLASS` (Other earnings not yet classified) → EO wages | `INCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `dd61788183c7…` | Classify this earning (which code?) before it counts for EO wages. | | |
| 22 | `HK_OTHER_UNCLASS` (Other earnings not yet classified) → SMW wages | `INCLUDED` (proposed; **PENDING** — not applied as certified) | Labour Department, archived SHA-256 `11e750937bf7…` | Classify this earning before it counts for SMW. | | |
| 23 | `HK_OTHER_UNCLASS` (Other earnings not yet classified) → IR56B | `UNMAPPED_REQUIRES_CLASSIFICATION (—)` (proposed; **PENDING** — not applied as certified) | Inland Revenue Department, archived SHA-256 `d43073a74315…` | Which IR56B item does this earning belong to? | | |
| 24 | Unpaid-absence day rate | gross ÷ 30 per unpaid day (`_PAYROLL_DAYS_DEFAULT`) | engine convention, no archived source | Is a 30-day divisor right for the unpaid-absence deduction of a monthly-paid employee, or should it be calendar days of the month / working days / the contract's rule? | | |
| 25 | Overtime pay rounding | hours × contractual rate, rounded half-up to the cent | engine convention, no archived source | Is rounding contractual overtime pay half-up to the cent acceptable, or must it follow another rule? | | |
| 26 | Pre-1-May-2025 wage override evidence (HK-017) | reason + evidence reference + four-eyes approval | wireframe HK-017; ld_aoa | What evidence is sufficient to correct a frozen pre-transition monthly wage (e.g. payroll register for April 2025, signed contract)? | | |

#### Earning-code mappings quoted from an archived source (confirm or correct)

Each row below is applied as configured. The treatment is quoted from the archived source shown; it is still **pending specialist review** and nothing is marked specialist-verified.

| # | Code → obligation | Configured | Source | Basis quoted | Confirmed? (Y / corrected value) | Authority you relied on |
|---|---|---|---|---|---|---|
| 27 | `HK_BASIC_SALARY` (Basic salary / wages) → EO wages | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3: 'wages' = all remuneration, earnings, allowances, tips and service charges payable in respect of work done | | |
| 28 | `HK_BASIC_SALARY` (Basic salary / wages) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA: relevant income = all monetary payments paid or payable by an employer to an employee (wages, salary, leave pay, fees, commissions, bonuses, gratuities, perquisites or allowances) | | |
| 29 | `HK_BASIC_SALARY` (Basic salary / wages) → SMW wages | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 30 | `HK_BASIC_SALARY` (Basic salary / wages) → IR56B | `SALARY_WAGES (11(a))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 3(d): gross salary reported at item 11(a) | | |
| 31 | `HK_OVERTIME_CONTRACT` (Overtime pay at the contractual rate) → EO wages | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3: commission and overtime pay are within the definition of wages | | |
| 32 | `HK_OVERTIME_CONTRACT` (Overtime pay at the contractual rate) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA: relevant income = all monetary payments paid or payable by an employer to an employee (wages, salary, leave pay, fees, commissions, bonuses, gratuities, perquisites or allowances) | | |
| 33 | `HK_OVERTIME_CONTRACT` (Overtime pay at the contractual rate) → SMW wages | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 34 | `HK_HOUSING_CASH` (Housing allowance paid in cash) → EO wages | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3: 'wages' = all remuneration, earnings, allowances, tips and service charges payable in respect of work done; only accommodation PROVIDED (in kind) is excluded | | |
| 35 | `HK_HOUSING_CASH` (Housing allowance paid in cash) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: cash allowance — Y | | |
| 36 | `HK_HOUSING_CASH` (Housing allowance paid in cash) → SMW wages | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 37 | `HK_HOUSING_CASH` (Housing allowance paid in cash) → IR56B | `OTHER_REWARDS_ALLOWANCES (11(k))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 10(b): cash allowances for ... housing — item 11(k) | | |
| 38 | `HK_CASH_ALLOWANCE` (Cash allowance (contractual, recurrent)) → EO wages | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3: 'wages' = all remuneration, earnings, allowances, tips and service charges payable in respect of work done | | |
| 39 | `HK_CASH_ALLOWANCE` (Cash allowance (contractual, recurrent)) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: cash allowance — Y | | |
| 40 | `HK_CASH_ALLOWANCE` (Cash allowance (contractual, recurrent)) → SMW wages | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 41 | `HK_CASH_ALLOWANCE` (Cash allowance (contractual, recurrent)) → IR56B | `OTHER_REWARDS_ALLOWANCES (11(k))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 10(b): cash allowances for food, cost of living, etc. — item 11(k) | | |
| 42 | `HK_TRAVEL_ALLOWANCE` (Travelling allowance (recurrent, contractual)) → EO wages | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3: travelling allowances are within wages (non-recurrent / actual-expense ones are not) | | |
| 43 | `HK_TRAVEL_ALLOWANCE` (Travelling allowance (recurrent, contractual)) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: cash allowance / car subsidy in cash — Y | | |
| 44 | `HK_TRAVEL_ALLOWANCE` (Travelling allowance (recurrent, contractual)) → SMW wages | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 45 | `HK_TRAVEL_ALLOWANCE` (Travelling allowance (recurrent, contractual)) → IR56B | `OTHER_REWARDS_ALLOWANCES (11(k))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 10(b): cash allowances for travelling — item 11(k) | | |
| 46 | `HK_EXPENSE_REIMB` (Reimbursement of expenses incurred in the employment) → EO wages | `EXCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3 exclusions 4–5: travelling allowance for actual expenses; sums to defray special expenses | | |
| 47 | `HK_EXPENSE_REIMB` (Reimbursement of expenses incurred in the employment) → MPF relevant income | `EXCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: reimbursement of expenses necessary in the performance of employment duties — N | | |
| 48 | `HK_EXPENSE_REIMB` (Reimbursement of expenses incurred in the employment) → SMW wages | `EXCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 49 | `HK_COMMISSION` (Commission (contractual)) → EO wages | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3: commission is within the definition of wages | | |
| 50 | `HK_COMMISSION` (Commission (contractual)) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: commission — Y | | |
| 51 | `HK_COMMISSION` (Commission (contractual)) → SMW wages | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 52 | `HK_COMMISSION` (Commission (contractual)) → IR56B | `COMMISSION_FEES (11(d))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 4: commission / fees — item 11(d), the year the employee became entitled | | |
| 53 | `HK_COMMISSION_DISC` (Commission (gratuitous / at the employer's discretion)) → EO wages | `EXCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3 exclusion 3: commission of a gratuitous nature or payable only at the employer's discretion | | |
| 54 | `HK_COMMISSION_DISC` (Commission (gratuitous / at the employer's discretion)) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA: relevant income = all monetary payments paid or payable by an employer to an employee (wages, salary, leave pay, fees, commissions, bonuses, gratuities, perquisites or allowances) | | |
| 55 | `HK_COMMISSION_DISC` (Commission (gratuitous / at the employer's discretion)) → SMW wages | `EXCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 56 | `HK_COMMISSION_DISC` (Commission (gratuitous / at the employer's discretion)) → IR56B | `COMMISSION_FEES (11(d))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 4: commission / fees — item 11(d) | | |
| 57 | `HK_BONUS_CONTRACT` (Bonus / 13th-month pay due under the contract) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: 13th month pay (double pay) — Y | | |
| 58 | `HK_BONUS_CONTRACT` (Bonus / 13th-month pay due under the contract) → IR56B | `BONUS (11(e))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 5: bonus — item 11(e), the year the employee became entitled | | |
| 59 | `HK_BONUS_DISC` (Discretionary / performance bonus) → EO wages | `EXCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3 exclusion 6: end-of-year payment or annual bonus of a gratuitous nature or at the employer's discretion | | |
| 60 | `HK_BONUS_DISC` (Discretionary / performance bonus) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: bonus at employer's discretion / performance linked — Y | | |
| 61 | `HK_BONUS_DISC` (Discretionary / performance bonus) → SMW wages | `EXCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 62 | `HK_BONUS_DISC` (Discretionary / performance bonus) → IR56B | `BONUS (11(e))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 5: bonus — item 11(e) | | |
| 63 | `HK_ATTENDANCE_ALLOW` (Attendance allowance (contractual)) → EO wages | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3: attendance allowances are within wages (gratuitous ones are not) | | |
| 64 | `HK_ATTENDANCE_ALLOW` (Attendance allowance (contractual)) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: cash allowance — Y | | |
| 65 | `HK_ATTENDANCE_ALLOW` (Attendance allowance (contractual)) → SMW wages | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 66 | `HK_TIPS_SERVICE` (Tips / service charges distributed by the employer) → EO wages | `INCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3: wages include tips and service charges | | |
| 67 | `HK_TIPS_SERVICE` (Tips / service charges distributed by the employer) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: tips collected by the employer — Y | | |
| 68 | `HK_TIPS_SERVICE` (Tips / service charges distributed by the employer) → SMW wages | `INCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 69 | `HK_TIPS_SERVICE` (Tips / service charges distributed by the employer) → IR56B | `OTHER_REWARDS_ALLOWANCES (11(k))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 10(e): tips — item 11(k) | | |
| 70 | `HK_LEAVE_PAY` (Holiday / annual leave / sickness allowance pay) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: paid leave allowance (annual / sick leave) — Y | | |
| 71 | `HK_PILON` (Payment in lieu of notice) → IR56B | `BACK_PAY_PILON_GRATUITY (11(f))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 6(a)(ii): payment in lieu of notice — item 11(f) | | |
| 72 | `HK_EOC_GRATUITY` (Gratuity on completion / termination of the contract) → EO wages | `EXCLUDED` | Labour Department, archived SHA-256 `dd61788183c7…` | Concise Guide ch.3 exclusion 7: gratuity payable on completion or termination of a contract | | |
| 73 | `HK_EOC_GRATUITY` (Gratuity on completion / termination of the contract) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA examples: end-of-contract gratuity — Y | | |
| 74 | `HK_EOC_GRATUITY` (Gratuity on completion / termination of the contract) → SMW wages | `EXCLUDED` | Labour Department, archived SHA-256 `11e750937bf7…` | SMW countable wages follow the EO wages definition (Statutory Minimum Wage page; Concise Guide ch.3) | | |
| 75 | `HK_EOC_GRATUITY` (Gratuity on completion / termination of the contract) → IR56B | `BACK_PAY_PILON_GRATUITY (11(f))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 6(a)(i): gratuities on termination — item 11(f) | | |
| 76 | `HK_SEVERANCE_LSP` (Statutory severance / long service payment) → MPF relevant income | `EXCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA: relevant income excludes severance / long service payments under the EO | | |
| 77 | `HK_SEVERANCE_LSP` (Statutory severance / long service payment) → IR56B | `EXCLUDED` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 6(b): statutory SP / LSP is NOT reported (only any excess) | | |
| 78 | `HK_ALLOWANCE_UNSPEC` (Named allowance not yet given its own code) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA: relevant income = all monetary payments paid or payable by an employer to an employee (wages, salary, leave pay, fees, commissions, bonuses, gratuities, perquisites or allowances) | | |
| 79 | `HK_ALLOWANCE_UNSPEC` (Named allowance not yet given its own code) → IR56B | `OTHER_REWARDS_ALLOWANCES (11(k))` | Inland Revenue Department, archived SHA-256 `d43073a74315…` | IR56B note 10(b): cash allowances — item 11(k) | | |
| 80 | `HK_OTHER_UNCLASS` (Other earnings not yet classified) → MPF relevant income | `INCLUDED` | Mandatory Provident Fund Schemes Authority, archived SHA-256 `0068f8fde7b2…` | MPFA: relevant income = all monetary payments paid or payable by an employer to an employee (wages, salary, leave pay, fees, commissions, bonuses, gratuities, perquisites or allowances) | | |

Default pay-source bindings (employer configuration — confirm they fit your client's pay elements): `basic` → `HK_BASIC_SALARY`; `hra` → `HK_HOUSING_CASH`; `special_allowance` → `HK_CASH_ALLOWANCE`; `overtime` → `HK_OVERTIME_CONTRACT`; `named_allowances` → `HK_ALLOWANCE_UNSPEC`; `additional_compensation` → `HK_OTHER_UNCLASS`; `allowance:transport` → `HK_TRAVEL_ALLOWANCE`; `allowance:commission` → `HK_COMMISSION`; `attendance:bonus` → `HK_BONUS_DISC`; `attendance:rewards` → `HK_OTHER_UNCLASS`; `attendance:other_compensation` → `HK_OTHER_UNCLASS`.

### General-holiday lists (open items, currently empty)

| List | Pack | Current | Status | Official file / URL you provide | Notes |
|---|---|---|---|---|---|
| General holidays 2025 | pack 2025 | `(not loaded)` | UNVERIFIED / SOURCE_REQUIRED | | |
| General holidays 2026 | pack 2025 | `(not loaded)` | UNVERIFIED / SOURCE_REQUIRED | | |
| General holidays 2026 | pack 2026 | `(not loaded)` | UNVERIFIED / SOURCE_REQUIRED | | |
| General holidays 2027 | pack 2026 | `(not loaded)` | UNVERIFIED / SOURCE_REQUIRED | | |

While a list is empty, the product defers only for weekends and recorded signal days, and shows "general-holiday list not loaded" on the payslip trace and eMPF deadline.

## Time estimate

Engineering's estimate, not a commitment: about 2–3 working days for a specialist to review 80 items (26 questions incl. items 1–5) and the deferral rule, plus about 1 hour to provide the three holiday files.

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
