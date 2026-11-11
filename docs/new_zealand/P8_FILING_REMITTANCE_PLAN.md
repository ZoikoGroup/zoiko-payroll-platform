# New Zealand P8: payday filing, remittance, run exceptions, amendments, journal: detailed plan

**Status:** plan only, for review. Nothing is built until Venu says "go ahead".
**Builds on:** P0–P7 (backend to `c6ea8c6c35ce`, frontend P7 `a39f53b`). **Template:** Japan P8 (`f76e783`: `japan_filing.py`, `japan_journal.py`, run exceptions).
**Spec:** ZP-NZ-ENG-001 §9 (payday filing, remittance), §12 (blocking states), NZ-006 (corrections), NZ-012 (child-support shortfall), NZ-015 (minimum wage), NZ-018 (idempotent filing), NZ-019 (filing acceptance is not payment); gate **G3** (export schema certification).

---

## 0. What P8 delivers, and what it deliberately does not

| Delivers | Does not deliver (fail-closed) |
|---|---|
| A **filing record per legal employer and payday**, generated only from PAID runs: an Employment Information schedule (EI) and an Employee Details schedule (ED: starters and leavers), each with a hash, a version and an idempotent key | **No file is ever sent or exported** while `content.NZ_EXPORT_SCHEMAS == {}` (decision D-3; G3). Submit is refused with `NZ_EXPORT_SCHEMA_NOT_CERTIFIED`; only the JSON preview exists |
| **Due dates** (filing: payday + the signed number of working days; remittance: 20th / 5th / 15 Jan rules) | No due date is guessed: if the working-day rule is not signed, `due_on` stays empty and is shown as "rule not signed" |
| **Remittance periods** with per-run lines, **settlements** and matching; acceptance of a filing **never** marks money paid (NZ-019) | No bank file or payment initiation |
| **Run exceptions**: a second person approves a documented exception, bound to the run's fingerprint | A minimum-wage **FAIL** is never approvable |
| **Amendment filings** from P6 corrections (NZ-006) | |
| An **accounting journal** that must balance, using the employer's own account map | Never posts to a guessed account: an incomplete map BLOCKS |

---

## 1. Decisions (recorded 2026-11-04, Venu: "go head with your recommendation" — all four recommendations: D-P8-1 (a), D-P8-2 content row, D-P8-3 (a), D-P8-4 (a))

| # | Question | Options | Recommendation |
|---|---|---|---|
| **D-P8-1** | Which statutory exceptions may a second person approve so a run can proceed? | (a) only the child-support shortfall (`NZ_CS_SHORTFALL`, reported to IR with its variation code); (b) (a) plus minimum-wage UNDETERMINABLE with evidence | **(a)**. A minimum-wage FAIL is never approvable. UNDETERMINABLE means the hours are missing, and the right fix is to record them. |
| **D-P8-2** | The "working day" used for the 2-working-day filing deadline | The spec says "2 working days" but does not define the term. The Tax Administration Act definition excludes weekends, public holidays and 25 Dec–15 Jan. | **New content row** `nz_working_day_rule` (text, empty by design until G1): `WEEKDAYS_EXCL_PUBLIC_HOLIDAYS_AND_25DEC_15JAN`. Until it is signed, `due_on` is empty and flagged. |
| **D-P8-3** | Where a correction's money lands | (a) an AMENDMENT of the **original payday's** filing, plus a delta line in the **original** remittance period (flagged as late); (b) the current period | **(a)**. It matches how IR amendments work. The payroll shows the late flag and does not shift periods silently. |
| **D-P8-4** | How the filing payload carries IRD numbers | (a) the vault id and masked form only; decrypt only inside a certified exporter (G3); (b) store plaintext in the payload | **(a)**. No IRD number in plaintext anywhere at rest (§13, NZ-023). |

---

## 2. Content additions (`new_zealand_content.py`)

| key | kind | value | why |
|---|---|---|---|
| `nz_working_day_rule` | text | **empty by design** (G1), vocabulary `WEEKDAYS_EXCL_PUBLIC_HOLIDAYS_AND_25DEC_15JAN` | D-P8-2 |
| `nz_filing_payload_version` | amount | **empty by design** (G3) | the IR schema version the payload targets |

These are added to `NZ_EMPTY_BY_DESIGN`, the P7a console vocabulary (`nz_super_admin._vocabulary`) and the P7b page groups (Filing & remittance tab). The existing spec rows are now **consumed**:
- `nz_payday_filing_working_days` (2), `nz_paper_filing_working_days` (10);
- `nz_efiling_threshold` (50 000) / `nz_efiling_threshold_after_months` (6);
- `nz_large_employer_threshold` (500 000);
- `nz_remit_monthly_due_day` (20), `nz_remit_first_half_due_day` (20), `nz_remit_second_half_due_day` (5), `nz_remit_december_second_half_due` (01-15).

---

## 3. Database: migration `<hex12>_nz_filings.py` (down_revision `c6ea8c6c35ce`)

The same conventions as P2/P5/P6: `_common()`, literal names, `lock_timeout`, idempotent both ways, and RLS derived by `d7f9b1c3e5a6.classify()`. These tables carry no `employee_id`, so they get **TENANT** RLS; `payroll_nz_run_exceptions` has `employee_id`, so it gets **WORKER "org"**.

### 3.1 `payroll_nz_filings` (TENANT)
| column | type | notes |
|---|---|---|
| *(_common)* | | `legal_entity_id` = the legal employer (D-1) |
| pay_date | Date NOT NULL | |
| filing_type | String(24) NOT NULL | `EMPLOYMENT_INFORMATION` \| `EMPLOYEE_DETAILS` |
| version | SmallInteger NOT NULL default 1 | a regenerated DRAFT replaces its payload; a new version only after APPROVED |
| run_ids | JSON NOT NULL | every PAID run of this payday and legal employer |
| payload | JSON NOT NULL | generated only from frozen PAID payslips; IRD numbers as vault id and masked form (D-P8-4) |
| payload_hash | String(64) NOT NULL | sha256 of the canonical payload |
| channel | String(20) NOT NULL | from the employer profile `filing_method`: `PAYDAY_GATEWAY` \| `MYIR_FILE_UPLOAD` \| `MYIR_ONSCREEN` \| `PAPER` |
| due_on | Date NULL | NULL while the working-day rule is unsigned (D-P8-2) |
| status | String(12) NOT NULL default `DRAFT` | `DRAFT` \| `APPROVED` \| `SUBMITTED` \| `ACCEPTED` \| `REJECTED` \| `SUPERSEDED` |
| kind | String(10) NOT NULL default `ORIGINAL` | `ORIGINAL` \| `AMENDMENT` |
| amends_id | FK self SET NULL | the filing it amends |
| correction_id | FK payroll_nz_corrections SET NULL | the P6 correction behind an amendment |
| authority_reference | String(100) | |
| authority_errors | JSON | structured codes only, no free text |
| submitted_by_id | FK users | |
| submitted_at, responded_at | DateTime(tz) | |

**CHECKs:** the enums; `kind <> 'AMENDMENT' OR amends_id IS NOT NULL`; `version >= 1`.
**Unique (NZ-018):** `uq_nz_filing_version` on (organization_id, legal_entity_id, pay_date, filing_type, kind, version). Because legal_entity_id can be NULL, there is a second partial unique for the NULL legal entity, the same pattern as the P2 employer profile.
**Index:** (organization_id, due_on).

### 3.2 `payroll_nz_remittances` (TENANT): one row per period, obligation and destination
| column | type | notes |
|---|---|---|
| *(_common)* | | |
| period_start, period_end | Date NOT NULL | a monthly period, or 1–15 / 16–end (twice-monthly) |
| remittance_class | String(15) NOT NULL | `MONTHLY` \| `TWICE_MONTHLY`, frozen from the employer profile at the first line |
| obligation | String(20) NOT NULL | `PAYE` (incl. ACC earner levy) \| `STUDENT_LOAN` \| `KS_EMPLOYEE` \| `KS_EMPLOYER_NET` \| `ESCT` \| `CHILD_SUPPORT` |
| destination | String(16) NOT NULL | `INLAND_REVENUE` \| `COMPLYING_FUND` (+ `fund_ref`) |
| fund_ref | String(100) | |
| amount | Numeric(14,2) NOT NULL | the sum of its lines, kept in step |
| settled | Numeric(14,2) NOT NULL default 0 | the sum of matched settlements |
| due_on | Date NULL | content rules; NULL if a rule is unsigned |
| status | String(10) NOT NULL default `OPEN` | `OPEN` \| `PART_PAID` \| `PAID` (driven **only** by settlements, NZ-019) |
| late | Boolean NOT NULL default false | set when a correction delta lands after `due_on` (D-P8-3) |

**Unique:** (organization_id, legal_entity_id, period_start, obligation, destination, fund_ref), plus the partial for the NULL legal entity.

### 3.3 `payroll_nz_remittance_lines` (TENANT): append-only
`_common(with_updated=False)`, plus:
- remittance_id FK CASCADE;
- run_id FK SET NULL;
- payslip_item_id FK SET NULL;
- amount Numeric(14,2);
- source `RUN` \| `CORRECTION`;
- correction_id FK SET NULL.

**Unique:** (payslip_item_id, remittance_id) WHERE source = 'RUN'. A PAID retry therefore never doubles.

### 3.4 `payroll_nz_settlements` (TENANT)
`_common`, plus:
- remittance_id FK;
- paid_on Date;
- amount Numeric(14,2) > 0;
- payment_reference String(100) (a reference only, never bank details);
- status `RECORDED` \| `MATCHED` \| `REVERSED`;
- matched_by_id FK users (a **second person**).

### 3.5 `payroll_nz_run_exceptions` (WORKER "org")
`_common`, plus:
- run_id FK CASCADE, payslip_item_id FK SET NULL, employee_id FK;
- code String(40);
- detail JSON (the shortfall and variation code, no narrative);
- run_fingerprint String(64) (the `nz_approval_fingerprint` input at approval);
- status `REQUESTED` \| `APPROVED` \| `REJECTED`.

**CHECK:** `code <> 'NZ_MIN_WAGE_FAIL'`, so it is never approvable even at DB level (D-P8-1).
**Unique:** (run_id, payslip_item_id, code, run_fingerprint).

### 3.6 Column
`payroll_nz_employer_profiles.nz_journal_accounts` JSON NULL (literal `op.add_column`). It holds the employer's account map and is edited outside the statutory versioning but audited.

---

## 4. Services

### 4.1 `payroll/nz_filing.py` (new)
```python
nz_working_days_after(start: date, n: int, holidays: set[date], rule: str) -> date
    # pure; rule WEEKDAYS_EXCL_PUBLIC_HOLIDAYS_AND_25DEC_15JAN; holidays = signed NZ_PUBLIC_HOLIDAY rows
    # (national only - the IR deadline is national)
filing_due_on(db, pay_date, channel) -> date | None
    # n = nz_payday_filing_working_days (electronic) | nz_paper_filing_working_days (PAPER);
    # None while nz_working_day_rule is unsigned or the holiday table is empty for the year
build_filings(db, organization_id, legal_entity_id, pay_date, actor_id) -> list[filing]
    # called from before_run_transition at PAID (after post_accumulators / ledgers):
    # gathers EVERY PAID NZ run of that payday and legal employer; EI payload per employee:
    #   {employeeId, irdVaultId, irdMasked, taxCode, gross (PAYE base + extra), paye, accLevy (inside PAYE),
    #    studentLoan, ksEmployee, ksEmployerGross, esct, childSupport, lumpSum / extra-pay amounts,
    #    payPeriod, hours (if known)}  - every figure copied from the frozen nz_result
    # ED payload: starters / leavers from P5 employments starting / ending in the period (+ tax code, KiwiSaver state)
    # DRAFT exists -> replace payload + hash (same version); APPROVED+ exists -> new version, old SUPERSEDED
approve_filing(db, org, filing_id, actor_id)            # four-eyes vs created_by; DRAFT -> APPROVED
submit_filing(db, org, filing_id, actor_id)             # NZ_EXPORT_SCHEMAS == {} -> 409 NZ_EXPORT_SCHEMA_NOT_CERTIFIED
record_authority_response(db, org, filing_id, outcome, reference, error_codes, actor_id)
    # SUBMITTED -> ACCEPTED / REJECTED; NEVER touches remittances (NZ-019); a rejection leaves payroll unchanged
amend_for_correction(db, correction, actor_id)          # P6 apply_correction -> AMENDMENT of the original payday
preview(filing) -> dict                                 # masked; no IRD digits ever
```

### 4.2 `payroll/nz_remittance.py` (new)
```python
remittance_class(db, profile, on) -> str     # profile.remittance_class, cross-checked against the
                                             # nz_large_employer_threshold rule with the connected-business group (evidenced)
period_for(pay_date, remittance_class) -> (start, end)
remittance_due_on(period_start, period_end, remittance_class, pack) -> date | None
    # MONTHLY: nz_remit_monthly_due_day of the next month; TWICE: 1-15 -> first_half day same month,
    # 16-end -> second_half day next month, except 16-31 Dec -> nz_remit_december_second_half_due
post_run(db, run, actor_id)                  # at PAID: one line per payslip and obligation (idempotent), sums kept
post_correction(db, correction, run, actor_id)   # delta lines into the ORIGINAL period; late flag (D-P8-3)
record_settlement(db, org, remittance_id, paid_on, amount, reference, actor_id)
match_settlement(db, org, settlement_id, actor_id)   # second person; settled += amount; status OPEN / PART_PAID / PAID
reverse_settlement(...)                              # reason; status and settled restored
```
The obligation mapping comes from `nz_result.obligations` and `kiwisaver.destination`. For example, `paye` already includes the ACC levy, and `ksEmployerNet` goes to the KiwiSaver destination.

### 4.3 `payroll/nz_journal.py` (new; mirrors `japan_journal.py`)
| Side | Line |
|---|---|
| DR | salary expense (gross) |
| DR | employer KiwiSaver expense (employer gross) |
| CR | PAYE payable (incl. ACC levy) |
| CR | student loan payable |
| CR | KiwiSaver payable (employee + employer net) |
| CR | ESCT payable |
| CR | child support payable |
| CR | other deductions payable |
| CR | net pay payable |

The journal must balance, or it returns BLOCKED with the difference. An incomplete `nz_journal_accounts` returns BLOCKED with the missing keys.

### 4.4 Run exceptions (`nz_lifecycle.py`)
- `request_run_exception(db, org, run_id, payslip_item_id, code, actor_id)`: only codes present in that payslip's `exceptions`, and only `NZ_CS_SHORTFALL` (D-P8-1).
- `approve_run_exception(...)`: four-eyes, bound to the run's current fingerprint input.
- **`new_zealand_service.nz_run_preflight` change:** an exception with an APPROVED run exception for the **same** fingerprint no longer blocks. A changed payslip makes the approval stale, so it blocks again.

### 4.5 Wiring
`before_run_transition` at PAID, in order:
1. `post_accumulators`
2. `write_gross_earnings`
3. `mark_paid`
4. `on_final_run_paid`
5. **`nz_remittance.post_run`**
6. **`nz_filing.build_filings`**

`apply_correction` (P6) additionally calls `amend_for_correction` and `post_correction` when the correction run is PAID.

---

## 5. Routes (`nz_org_router.py`, about 16)
| Method / path | Purpose |
|---|---|
| GET `/filings` (`?payDate`, `?status`) · GET `/filings/{id}` (masked preview) | list / preview |
| POST `/filings/{id}/approve` · `/submit` (refused until G3) · `/response` | workflow |
| GET `/remittances` (`?periodStart`) · GET `/remittances/{id}` (with lines) | periods |
| POST `/remittances/{id}/settlements` · `/settlements/{id}/match` · `/settlements/{id}/reverse` | money |
| GET `/runs/{id}/exceptions` · POST `/runs/{id}/exceptions` · POST `/run-exceptions/{id}/approve` · `/reject` | exceptions |
| GET `/runs/{id}/journal` · PUT `/employer-profiles/{id}/journal-accounts` | journal |

Plus a route-registry regeneration in a no-.env worktree.

## 6. Frontend
| File | What |
|---|---|
| `Compliances/NZFilingsPanel.jsx` | Paydays with EI/ED status, due date ("rule not signed" when NULL), masked JSON preview, approve, **Submit shown disabled with the G3 reason**, record response, amendment chain |
| `Compliances/NZRemittancePanel.jsx` | Periods × obligations, due dates, late flags; record settlement; match (second user); reverse |
| `PayRollRuns/NZRunExceptionsPanel.jsx` | On run details: the payslips' exceptions; request / approve child-support shortfall exceptions; a minimum-wage FAIL is shown as "fix the pay or hours"; never approvable |
| `PayRollRuns/NZJournalPanel.jsx` | The balanced journal, or the BLOCKED reason |
| Employer profile (P7c) | Account-map editor |
| `nz-compliance-ui-validation.mjs` | + every new client call matches a route; no IRD digits in filing previews; Submit stays disabled while schemas are empty |

## 7. Tests (`test_nz_phase8.py`, `test_nz_filings_migration.py`)
- **Filing deadline:** 2 working days across a weekend, across a public holiday, and across 25 Dec–15 Jan. An unsigned rule gives a NULL due date. PAPER uses 10 working days.
- **Filing generation and NZ-018:**
  - a PAID retry creates no duplicate;
  - two runs on one payday make **one** EI schedule;
  - a regenerated DRAFT keeps its version, and an APPROVED filing gets a new version, with the old one SUPERSEDED;
  - starters and leavers appear on ED.
- **Submit and responses:**
  - submit is refused while `NZ_EXPORT_SCHEMAS` is empty;
  - a rejection leaves payroll and remittances unchanged;
  - **acceptance never marks a remittance PAID** (NZ-019).
- **Remittance:**
  - monthly → 20th of the next month;
  - twice-monthly: 1–15 → 20th, 16–end → 5th of the next month, 16–31 Dec → 15 Jan;
  - ≥ the large-employer threshold with connected-business evidence;
  - lines are idempotent;
  - a settlement needs a second person to match, and a reversal restores it.
- **Corrections:** a correction makes an AMENDMENT of the original payday and a delta line in the original period, with the late flag (D-P8-3).
- **Run exceptions:**
  - a CS shortfall approved by a second person unblocks approval, and a changed payslip re-blocks it;
  - a min-wage FAIL is refused at service **and** DB level.
- **Journal:** balances on the worked example (net 1,195.85 with child support), and is BLOCKED on a missing account.
- **Privacy:** no IRD digits in any payload, preview, log or audit.
- **Migration:** RLS classes, model equality, replay, downgrade, drift filter, manifest.

## 8. Order and size
1. Content rows + migration + models (with head pins).
2. `nz_filing.py` + `nz_remittance.py` + wiring.
3. Run exceptions + journal.
4. Routes + registry.
5. Frontend panels + UI checks.

One local commit, targeted tests (the full suite at the end, per the agreed policy). Estimated size: similar to P6.

## 9. Build notes (2026-11-05)

### What was built
- Migration `dd8a60634320` (head, 250 revisions).
- 16 routes (registry 1,446).
- Frontend:
  - `NZFilingRemittanceSection` (filings with masked preview, remittances with settlements, journal account map) in the NZ Compliance Centre;
  - `NZRunFilingPanel` (child-support shortfall approvals and the journal) on run details;
  - NZ UI validation: 35 checks.

### Changes from the plan, found while testing
- `uq_nz_run_exception` is partial (`status <> 'REJECTED'`). A rejected request no longer blocks a new request for the same calculation.
- An amendment with the same payload hash is not created twice.
- `record_settlement` checks the reason before writing anything.

### Still blocked on content and gates
- Due dates stay empty until `nz_working_day_rule`, the filing working-day counts, the remittance due-day rows and the national public holidays are signed (G1/G2).
- Submission stays refused until G3 certifies the schema.
