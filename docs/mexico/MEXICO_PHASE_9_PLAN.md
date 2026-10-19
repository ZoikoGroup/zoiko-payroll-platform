# Mexico (MX) — Phase 9 Plan: Annual and event modules — corrections, aguinaldo, vacation, termination / finiquito, PTU, annual ISR adjustment

Spec ZP-MX-ENG-001 v1.0:
- §4 (MX-008–MX-011);
- §17 (MX-051–MX-053);
- §18 (MX-054–MX-056);
- §19 (MX-057–MX-059);
- implementation plan v1.1 §12;
- the work later phases deferred here: Phase 6 (`RUN_TYPES` AGUINALDO / PTU / FINIQUITO / CORRECTION refused with `MX_RUN_TYPE_PHASE9`), Phase 7 (the correction run behind CFDI substitution) and Phase 8 (BAJA from a recorded termination, D2).

**Base.** `main` = `422d4d2` (PR #110, Phase 8 `8ee13dd`); single Alembic head `e3b9c2d7f4a1`. PR #110's deploy run `39214061815` was green at every step (tests, single-head, SSH deploy with `deploy_migrate.sh` and head verification, schema drift) and frontend build `39214061602` was green, so production should be at `e3b9c2d7f4a1` (confirm with `alembic current`).

**Status.** Approved 2026-10-19 as recommended (D1–D12). **9a (correction runs) merged** (PR #111). **9b (aguinaldo + vacation) built and staged** — `MEXICO_PHASE_9B_IMPLEMENTATION_REPORT.md`. 9c–9e not started.

**Ground rules (unchanged):**
- source wins and fail closed;
- no statutory value, method, deadline or catalog is inferred from the spec text;
- seeds stay Draft and nothing is set Active by code;
- zero behaviour change for other jurisdictions;
- every migration is additive and guarded;
- Mexico stays dormant behind `MX_TENANT_ONBOARDING_ENABLED`.

**The constraint that shapes this phase: no Phase 9 source is saved.** `docs/mexico/sources/` holds only S22, and that file is the stale CDMX code. Every rule Phase 9 needs is in an unsaved source:
- LISR Art. 93 exemptions, Art. 96 / 97 annual adjustment, Art. 152 annual tariff → **S24**, S1 / S2;
- RLISR Art. 174 → **S25**;
- the Federal Labour Law for aguinaldo proportionality, vacation taking, termination indemnities, seniority premium and PTU eligibility, split and caps → **S26**;
- PTU 2026 payment windows → **S21**;
- the CFDI perception / separation catalogs → **S28**.

So, as in Phases 5–8, Phase 9 builds the **mechanics** (records, workflows, run types, approvals, ledgers, lifecycles) with every rule read from content that is empty today. Each calculation blocks with a named code until its source is transcribed, and is proved with SYNTHETIC test content.

## 1. What Phase 9 is — split explicitly

### Recommended sub-phases (D1) — five PRs, each small, merged and verified in turn

| Sub-phase | Scope | Why this order |
|---|---|---|
| **9a** | Special-run foundation + **correction runs** | Every other module produces runs that sometimes need correcting. Phase 7 CFDI substitution and Phase 8 complementary liabilities already wait on a correction run. |
| **9b** | **Aguinaldo** run + **vacation** ledger (taken / paid / balance) | The entitlement accruals already exist (Phase 6). The aguinaldo is due every December. |
| **9c** | **Termination / finiquito** | Replaces Phase 8's interim BAJA source (`date_of_leaving`) with an approved termination record. |
| **9d** | **PTU** cycle, allocation and PTU run | Annual and employer-input driven. The 2026 payment window has passed; the next is 2027. |
| **9e** | **Annual ISR adjustment** | Year-end; first needed for fiscal 2026 in early 2027. |

### Buildable now — no source, provider or credential needed

| # | Item | What it does |
|---|---|---|
| B1 | **Special run types** (9a) | The guard admits AGUINALDO / PTU / FINIQUITO / CORRECTION. Each runs through the existing lifecycle (generate → review → approve → commit; four-eyes; approval fingerprint; reset rule; CFDI / authorities lanes) with **its own calculation path**. MX-009: a special payment is never added to ordinary salary. |
| B2 | **Correction runs** (9a, MX-040, Phase 7 F6) | A CORRECTION run recalculates selected committed payslips with corrected inputs. It **never edits the original**: it records per-ledger **deltas** (SBC history, accumulators, ISN, liabilities) and links each corrected payslip to its original. It feeds Phase 7 `create_replacement` (CFDI substitution) and Phase 8 complementary liabilities and MODIFICACION movements. |
| B3 | **Content seams** (all) | `MX_SPECIAL_PAY_RULES` (exempt limits and withholding method per concept), the aguinaldo proportionality rule, the termination-reason catalog with its components, PTU rules (split, eligibility, caps, window) and the annual-adjustment rules / tariff. **All empty.** Rule names are fixed at transcription, never anticipated. While empty, each calculation blocks: `MX_SPECIAL_PAY_RULE_MISSING`, `MX_TERMINATION_RULE_MISSING`, `MX_PTU_RULE_MISSING`, `MX_ANNUAL_ADJUSTMENT_RULE_MISSING`. |
| B4 | **Aguinaldo run** (9b) | Days come from the labour policy (statutory floor MX-051 already enforced). Service days in the year come from employment dates. The proportional amount and the special ISR come from content. The payable-by date comes from content (none → unsourced, the Phase 8 rule). |
| B5 | **Vacation ledger** (9b, MX-051 / MX-053) | Statutory and employer entitlement per service year (anniversary-exact, from `mx_seniority_date`). Taken days come from **approved vacation records** (maker-checker, D4). The premium is paid when the vacation is enjoyed, and the balance is per year. |
| B6 | **Termination record** (9c, MX-057 / MX-058) | Reason from the content catalog plus evidence, approved by a second person (operators cannot choose a tax treatment). Components are decomposed (earned salary, proportional aguinaldo / vacation / premium, PTU right preserved, severance and seniority premium only where the transcribed reason triggers them). It creates a FINIQUITO run and the IMSS **BAJA** movement (D6). |
| B7 | **PTU cycle** (9d, MX-054–MX-056) | The employer enters the distributable amount with evidence (four-eyes); Zoiko never derives it from payroll. Qualifying days and salary are aggregated from **committed** runs of the fiscal year. Eligibility and exclusion reasons, the split, the caps and the full audit trail are kept per worker. A PTU run pays it. |
| B8 | **Annual ISR adjustment** (9e, MX-010) | Per-employee eligibility and exclusions, annual income from committed runs, annual ISR from the transcribed annual tariff, the withheld total, and the difference. The difference is **applied as a separate line in a chosen later run**; a historical CFDI is never touched. |
| B9 | **Cross-phase wiring** | Special runs reuse Phase 6 commit, Phase 7 CFDI (builder still refuses) and Phase 8 accrual (ISR withheld → SAT_ISR, SBC deltas → movements). Reset of a special or correction run follows the same downstream rule. |
| B10 | **UI** | Run creation by type; correction picker (committed payslips); aguinaldo panel; vacation ledger (employee); termination wizard (four-eyes); PTU cycle wizard; annual-adjustment tab; Super Admin read-only views plus the blocks. |

### Blocked — not computed in Phase 9 until the source is saved and transcribed

| # | Item | Blocked on |
|---|---|---|
| X1 | ISR for aguinaldo / vacation premium / PTU / separation: exempt parts and withholding method | **S24** (LISR Art. 93, 96), **S25** (RLISR Art. 174) |
| X2 | Aguinaldo proportionality and payable-by date | **S26** (LFT Art. 87) |
| X3 | Vacation taking rules beyond the entitlement table (scheduling, payment in lieu at termination) | **S26** (LFT Arts. 76–81) |
| X4 | Termination reasons, indemnity components, seniority premium (trigger, days, cap) | **S26** (LFT Arts. 47–53, 162) |
| X5 | PTU pool rule, split, eligibility, caps, payment window | **S26** (LFT Arts. 117–131), **S21** |
| X6 | Annual adjustment: eligibility, exclusions, annual tariff, refund / charge rules | **S24** (Arts. 97, 152), S1 / S2 |
| X7 | CFDI for special runs: perception codes and the separation node | **S28** + the Phase 7 builder (X1–X4 there) |
| X8 | Paying any of it | **Phase 10** (bank) |

## 2. Preconditions the code enforces (fail closed, in order)

1. The org / run guard (Phase 4a / 6). The run type must be one of `RUN_TYPES`, and its sub-phase must be built.
2. Special and correction runs act only on **committed** history. A correction targets committed payslips only, and never an original that is mid-reset.
3. Every rule comes from Active content in force on the pay date. Otherwise the payslip blocks with its named code, nothing is posted, and preview stays non-mutating (MX-039).
4. Inputs the law makes a legal fact need evidence plus a second person: termination reason, PTU distributable amount, annual-adjustment exclusion.
5. The original committed payslip, its CFDI and its ledgers are never edited. Every correction is a new row with a link.

## 3. Data model — one migration per sub-phase, new tables only

| Sub-phase | Migration | New tables (shared tables untouched) |
|---|---|---|
| 9a | `mx_corrections_m7` | `payroll_mx_run_corrections` (correction run, original run / payslip, corrected payslip, reason, approved_by, deltas JSON, status) |
| 9b | `mx_benefits_m8` | `payroll_mx_vacation_records` (employee, service year, days, kind TAKEN / PAID_OUT / OPENING, dates, recorded_by / approved_by, run link); `payroll_mx_aguinaldo_lines` (run, employee, days policy / statutory, service days, base, amount, rule refs) |
| 9c | `mx_terminations_m9` | `payroll_mx_terminations` (employee, date, reason_code, evidence_ref, recorded_by / approved_by, components JSON, status DRAFT / APPROVED / PAID / CANCELLED, finiquito run, imss movement) |
| 9d | `mx_ptu_m10` | `payroll_mx_ptu_cycles` (plan v1.1 columns + evidence, four-eyes); `payroll_mx_ptu_allocations` (plan v1.1 columns + exclusion reason, cap comparison, rule refs) |
| 9e | `mx_annual_adjustment_m11` | `payroll_mx_annual_isr_adjustments` (plan v1.1 columns + applied run / line, approved_by) |

`payroll_runs.mx_run_type` already exists (Phase 6). No column is added to a shared table; links live on the new tables. Every FK to `payroll_runs` / `payslip_items` / `payroll_employees` is created under `lock_timeout` 5 s and measured on PG17, as in Phases 7–8.

## 4. Lifecycles (summary)

- **Correction:**
  - pick committed payslips and a reason;
  - a CORRECTION run is generated (recalculated with current inputs);
  - review and approve (four-eyes) → commit;
  - commit writes the deltas;
  - Phase 7: a replacement CFDI is linked (substitution);
  - Phase 8: complementary liabilities and MODIFICACION movements arise from the deltas.
- **Aguinaldo:** AGUINALDO run → lines per employee → approve / commit. Accruals are drawn down; ISR uses the special method (X1).
- **Vacation:** records are DRAFT → APPROVED (second person). A TAKEN record drives the premium line in the next ordinary run; PAID_OUT happens only at termination.
- **Termination:** DRAFT → APPROVED (second person, evidence) → FINIQUITO run committed → PAID (Phase 10) / CANCELLED (only before the run commits). APPROVED generates the Phase 8 BAJA.
- **PTU:** cycle DRAFT → AMOUNT_APPROVED (four-eyes, evidence) → ALLOCATED (preview, auditable) → APPROVED → PTU run committed.
- **Annual adjustment:** COMPUTED → APPROVED (four-eyes) → APPLIED (a line in a chosen run) / WAIVED (excluded, with reason).

Every one keeps an append-only event timeline (the Phase 8 pattern) and refuses illegal transitions.

## 5. Services and routes (per sub-phase)

- **Services:** `mexico_correction_service.py` (9a), `mexico_benefits_service.py` (9b), `mexico_termination_service.py` (9c), `mexico_ptu_service.py` (9d), `mexico_annual_service.py` (9e).
- **Engine:** `engine/jurisdictions/mexico/special_pay.py`, `termination.py`, `ptu.py`, `annual_adjustment.py`. Each is pure, reads content, and blocks when content is missing.
- **Org routes:** under `/api/payroll/mexico/…`, behind the guard.
- **Super Admin:** read-only views.

## 6. Reset rule and cross-phase effects

- A special or correction run is a run: the Phase 6–8 reset rule applies unchanged (refused once a CFDI, filing or payment has acted).
- **A committed original that has a committed correction cannot be reset** (the correction depends on it). New reason in `run_downstream_actions`, with a test.
- **A termination whose FINIQUITO run is committed cannot be cancelled.** Cancelling an APPROVED termination before that withdraws its PENDING BAJA (Phase 8 withdraw path).

## 7. Frontend

- The run creator offers a run type for MX organisations; Phase 9 types appear only once their sub-phase is built.
- **9a:** correction picker on a committed run (choose payslips and a reason).
- **9b:** aguinaldo run panel; vacation records and ledger on the employee.
- **9c:** termination wizard (reason → evidence → components preview → approval).
- **9d:** PTU cycle wizard.
- **9e:** annual-adjustment tab.
- **Super Admin:** read-only tabs, each listing its blocks (X1–X8).
- **Flag off:** nothing renders for a refused organisation (the Phase 7–8 rule).

## 8. What this does in production when merged

`MX_TENANT_ONBOARDING_ENABLED` is unset in production, so it is False. This is per sub-phase; each PR repeats this table with its own measurements.

| Change | Production effect |
|---|---|
| Migration (one per sub-phase) | New, empty tables only; no column on any shared table. The head moves one revision per PR. Brief SHARE ROW EXCLUSIVE on `payroll_runs` / `payslip_items` / `payroll_employees` under `lock_timeout` 5 s (measured before merge). Fails fast with nothing created if a writer holds a table. |
| Special / correction run types | **Unreachable.** The run guard refuses every Mexican run while dormant (`MX_DORMANT`), and no Mexican run can be committed in production. Run creation for other countries is unchanged: the type selector is MX-only. |
| Calculations | Content is empty, so every Phase 9 calculation would block with its named code. Nothing is defaulted. |
| `run_downstream_actions` | Also queries the new empty tables and returns `[]`, so reset behaviour is unchanged. |
| Phase 8 BAJA source (9c) | Switches from `date_of_leaving` to approved terminations for MX only. There are no MX employees, so there is nothing to switch. |
| Secrets / storage | Nothing new is read or stored. |

**Net effect per sub-phase:** additive schema, no behaviour change for any jurisdiction.

## 9. Tests (synthetic, labelled)

- **Correction:** the original is never edited; deltas equal corrected − original per ledger; the substitution link is created; a complementary liability appears for a filed period; a MODIFICACION movement appears for an SBC delta; the original cannot be reset after a committed correction.
- **Aguinaldo:**
  - blocks without its rule;
  - with synthetic content: correct days × salary, proportional for a partial year (directional: fewer service days never pay more);
  - a policy below the floor blocks;
  - ISR never takes the ordinary path (MX-009).
- **Vacation:** anniversary-exact entitlement (directional by seniority); a taken record needs a second approver; the premium appears only when vacation is taken; balance arithmetic.
- **Termination:** no reason → block; a reason with no evidence or approver is refused; components only from the transcribed reason; seniority premium only where triggered; BAJA generated once and withdrawn on cancel; finiquito ISR never on the ordinary path.
- **PTU:** the amount needs evidence and four-eyes; days and salary come only from committed runs; every exclusion carries a reason; the cap comparison is kept; allocations sum to the pool exactly (rounding residue rule from content); the payment never enters ordinary accumulators (MX-056).
- **Annual adjustment:** eligibility and exclusions recorded; the difference is applied as a new line; historical payslips and CFDIs are unchanged (byte-compared).
- **Dormancy:** every new route 403s with the flag off.
- **Migrations:** SQLite + PG17 with lock measurement; browser checks with the flag off and on for each sub-phase.

## 10. Order of work

For each sub-phase, in turn:
1. Migration + models.
2. Engine module (content seams).
3. Service.
4. Run-type wiring.
5. Reset reasons.
6. Routes.
7. Frontend.
8. Full suite in chunks, PG17 measurement, browser checks, report with the §8 table, stage.

## 11. Decisions needed from you

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Sub-phasing and order | **9a corrections → 9b aguinaldo + vacation → 9c termination → 9d PTU → 9e annual adjustment**, one PR each. |
| D2 | Special-pay ISR while S24 / S25 are not transcribed | Block (`MX_SPECIAL_PAY_RULE_MISSING`). **Never** fall back to the ordinary tariff (MX-009). |
| D3 | Aguinaldo proportionality | A content rule from S26 with no default; block until transcribed. |
| D4 | Source of vacation taken | Mexico's own **approved vacation records** (maker-checker, like Phase 6 approved hours). The shared leave types don't carry the MX premium / anniversary semantics. |
| D5 | Termination reason | A content catalog from S26 with the component rules per reason. Evidence plus a second approver are required. No operator-selectable tax treatment (MX-057). |
| D6 | Phase 8 BAJA source after 9c | **Approved terminations only** for MX (`date_of_leaving` stops generating BAJA). One source, with evidence. |
| D7 | PTU base | Employer-entered amount + evidence document reference + four-eyes. Zoiko never computes it (MX-054). |
| D8 | PTU and aguinaldo payment | Their own run types through the normal lifecycle (approval, commit, CFDI lane, liabilities). Never lines in an ordinary run. |
| D9 | Applying the annual adjustment | A separate, approved line in an operator-chosen later run. Historical runs and CFDIs are never edited (MX-010). |
| D10 | Correction scope | Committed payslips only. Recalculation with the **current** inputs for the original period (inputs fixed by the operator first). The original stays committed; only deltas post. |
| D11 | Special pays in the subsidy month-to-date and SBC | By content only (S3 / S10 / earning classification). Block where not transcribed. |
| D12 | Evidence | Reference strings (the Phase 8 D9 rule) until Cloud Storage exists in production. |

**Open, unchanged:** Phase 7 D10–D12 (PAC, S28 / S30 / S4, Secret Manager), Phase 8 X1–X7 (layouts, due-date rules, transmission mode, bank, bimonthly periods, work-risk review, Cloud Storage), G1–G8, Q9.
