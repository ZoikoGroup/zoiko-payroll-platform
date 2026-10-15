# Hong Kong implementation gap matrix (wireframe v1.0, sections 3–15 and HK-001 to HK-023)

**Baseline audited:** `nikhil` at `d55326d`, 2026-10-14. Read-only code audit; no file was changed for it.
**Spec:** `Zoiko_Payroll_Hong_Kong_Engineering_Implementation_Wireframe_v1.0.docx` (SHA-256 prefix `c0e2e358ec3b1adc000f`).
**Rule for status:**
* **IMPLEMENTED** means the logic exists, is wired into the payroll run or service path, and is tested.
* **PARTIAL** means something exists but is unwired, untested, simplified, or missing a sub-branch.
* **MISSING** means nothing exists.

The key findings were re-checked by hand in the code (marked ✔).

## Summary (before Phase 2)

| Section | Rows | IMPLEMENTED | PARTIAL | MISSING |
|---|---|---|---|---|
| 3–6 Baseline, worker resolver, earnings, MPF / eMPF | 34 | 8 | 25 | 1 |
| 7–11 IRD, IR56G hold, EO entitlements, SMW, termination | 37 | 15 | 21 | 1 |
| 1–2 rules, 12–15 State machines, retention, domain model, screens, security | 29 | 4 | 23 | 2 |
| **Total** | **100** | **27** | **69** | **4** |

**MISSING:**
* S5-7 voluntary MPF contributions;
* S9-1 rest days;
* S12-5 entitlement lifecycle (entitlements are calculated but never stored or paid);
* S14-4 pay-result drawer.

## Delta 2026-10-15 (STEP 1–3 of the HK programme, `nikhil`, not pushed)

| Row | Before | After | By |
|---|---|---|---|
| S4-1 | PARTIAL | IMPLEMENTED | earning-code catalogue (STEP 3) |
| S4-2 | PARTIAL | IMPLEMENTED | D-A |
| S10-4 | PARTIAL | IMPLEMENTED | D-A (overtime hours count for SMW and continuous contract) |
| S11-1 | PARTIAL (defective) | IMPLEMENTED | D-B, D-J |
| S7-2 | IMPLEMENTED | IMPLEMENTED (gap closed) | D-L |
| D-M | Paternity leave pay granted for leave outside the statutory window (4 weeks before the expected date of delivery to 14 weeks beginning on the actual date); the document deadline was a yes/no flag | `entitlements.paternity_leave_pay` | Pay for leave the EO does not cover — **fixed (staged 2026-10-15)** |
| S7-4 / S7-5 / S7-9 / HK-017 / S15-6 | PARTIAL | PARTIAL (defect fixed, other gaps remain) | D-H / D-D / D-F / D-C / D-E |

**Totals after the delta:** 31 IMPLEMENTED, 65 PARTIAL, 4 MISSING (was 27 / 69 / 4).

**Defects found during the audit** (wrong behaviour, not just gaps; fix commits on `nikhil`):

| # | Defect | Where | Effect |
|---|---|---|---|
| D-A ✔ | HK overtime pay is hard-wired to 0 in the payroll run (only Singapore computes it) | `service.py` ~24928 | Contractual overtime can never be paid through an HK run — **fixed `b57ede2`** |
| D-B ✔ | Any employee with a leaving date raises the BLOCK `EO_TERMINATION_WAGES_DUE_IMMEDIATELY`, with no way to clear it | `preflight.py:242-246` | A leaver's final payroll run can never be approved — **fixed `f06b198`** |
| D-C ✔ | When the profile has no frozen pre-transition wage, `calculate_termination` uses the wage typed in the request | `hong_kong_service.py:1242-1248` | HK-017 can be bypassed — **fixed `2be8076`** |
| D-D ✔ | `record_ir56g_filed` sets the IRD case FILED directly | `hong_kong_service.py:389-404` | IR56G filing skips four-eyes, submission record and validation — **fixed `582fa70`** |
| D-E ✔ | Deleting a Draft pack deletes its `payroll_tax_configuration_audit` rows. Since `4c45af9` (F-6 append-only triggers) that delete is refused | `service.py:9413` | **A regression in our own unpushed commit:** Draft-pack delete fails once audit rows exist — **fixed `30ab73d`** |
| D-F | The BIR56A reconciliation compares reported totals (suppressed and excluded amounts removed) with full committed gross | `hong_kong_service.py` ~670 / 3864 | Shows a false "Variance" whenever an IR56B is suppressed or an amount excluded — **fixed `3af5575`** |
| D-G | IR56B gross = `gross_pay − attendance_deduction`, while the engine's unpaid-absence figure uses a hard-coded 30-day divisor | `countries/hong_kong.py` `_PAYROLL_DAYS_DEFAULT` | Possible reconciliation mismatch — **not reproduced**: the D-G regression test (`6d60fce`) passes; the 30-day divisor is a specialist question (packet 01) |
| D-H | IR56F can coexist with an IR56G departure case; the check uses only a profile fact, not an open hold | `hong_kong_service.py:626-628` | Wrong form filed — **fixed `9caad5b`** |
| D-I | `HongKongEmpfSubmission.amends_submission_id` is never written | models / service | eMPF correction chain incomplete — open (scheduled later) |
| D-J | A leaver whose employment ended before the wage period (still status ACTIVE) is selected by the run and paid a full month; the preflight selected the same way | `service._generate_payslips_for_run`; `_hk_run_employees` | Overpayment after leaving (found by the synthetic-company harness) — **fixed `aa7b110`** |
| D-K | The HK approval gate skipped mid-period joiners the run pays | `_hk_run_employees` | A joiner's BLOCKs (e.g. no HKID) never applied — **fixed `a8ae74d`** |
| D-L | An IR56B is prepared clean beside an open (unfiled) IR56F / IR56G for the same cessation | `ird.ir56b_suppression` | Duplicate forms once both are filed — **fixed `c8510a4`** |

## Sections 3–6

| ID | Requirement | Status | Code location(s) | Test(s) | What is missing |
|---|---|---|---|---|---|
| S3-1 | YA object ending 31 Mar | IMPLEMENTED | `common.year_of_assessment`; YA-window packs | test_hong_kong.py::test_ird_year_of_assessment_ends_31_march_not_calendar_year | 1 Apr / 31 Mar are code literals, not a first-class entity |
| S3-2 | No Salaries Tax withholding (only IR56G hold) | IMPLEMENTED | `countries/hong_kong.py` never sets `tds`; hold service | test_architecture_lock_normal_payroll_never_withholds_salaries_tax | — |
| S3-3 | SMW 43.10 from 1 May 2026, split crossing period | IMPLEMENTED | SEED SMW rows; `common.rule_segments`; `minimum_wage_due` | test_case_g_wage_period_crossing_1_may_2026_splits_rates; e2e test_r4_smw_crossover… | Top-up is not added to pay (see S10-2) |
| S3-4 | Hours-record trigger 17,600 | IMPLEMENTED | `minimum_wage.hours_record_cap/assess` | test_17600_is_a_record_keeping_trigger_not_a_monthly_minimum_wage | Non-monthly periods always flagged; a crossing period uses the higher cap |
| S3-5 | Continuous contract 4-18 → 17/68, rolling, replay | IMPLEMENTED | `continuous_contract.resolve`; append-only work hours | test_case_h_468…; test_pre_18_january_2026…; e2e test_r5… | 4-week and 7-day literals |
| S3-6 | 15 holidays 2026, year-versioned, substitution | PARTIAL | SEED HOLIDAYS; `entitlements.statutory_holidays` | test_statutory_holidays_2026_are_15_with_easter_monday | **No substitution / alternative-holiday logic**; calendar not used by the payroll run |
| S3-7 | MPF thresholds 7,100/30,000, 5%, daily 280/1,000 | IMPLEMENTED | SEED mpf_*; `mpf.thresholds` | test_case_a_b_c_threshold_branches_from_pack_rows; test_non_monthly_daily_levels_times_days | — |
| S3-8 | eMPF default channel | PARTIAL | `EMPF_METHODS`; eMPF configuration | test_empf_configuration_holds_no_secrets… | No default config; batch ignores configuration; nothing transmitted (G2) |
| S3-9 | Worker resolver states | PARTIAL | `EmployeeStatutoryProfile.hk_*`; `mpf.resolve_coverage` | test_mpf_exemptions_fail_closed…; test_mpf_inbound_13_month_rule | Domestic / casual / contractor only BLOCK; visa type unused; no overseas-scheme evidence field; no per-employee wage period or work pattern |
| HK-004 | MPF coverage ≠ continuous contract | IMPLEMENTED | `mpf.resolve_coverage` never reads CC | test_mpf_coverage_never_inferred_from_part_time_status | No explicit "COVERED while NOT_CONTINUOUS" test |
| S4-1 | Classification per obligation and effective date; default HK earning-code set | IMPLEMENTED (was PARTIAL) — 18 default codes × EO / MPF / SMW / IR56B, each sourced (archived SHA-256) or PENDING with the specialist question; pay sources bound by rows; row-level effective dating with a governed dated split; unknown / unbound / pending-MPF fail closed (`countries/hong_kong._classify_by_code`; `earning_code_catalogue`; Super Admin "Earning Codes" tab; `tests/test_hong_kong_earning_codes.py`). Remaining: per-employee variable-pay entry by code needs its own table (migration waits for the main merge); all mappings G1-unverified. Previously: | `countries/hong_kong.earning_components/classify`; SEED HK_EARNING_CLASS (G1) | test_one_earning_classified_per_obligation | **No HK earning-code set** (only 6 generic components); effective-dating only per pack; all unverified; additional_compensation unmapped for IRD |
| S4-2 | Contract overtime, OT hours count for SMW | IMPLEMENTED (was PARTIAL; D-A) | verified daily hours | — | **D-A**: overtime pay 0; no OT-hours field; no test |
| HK-007 | 7-day payment deadline flag | IMPLEMENTED | `preflight.wage_payment_timing/checks`; approval gate | test_wage_payment_timing_uses_the_pack_row…; e2e test_preflight_blocks_a_late_run… | Flagged at run preflight, not at calendar set-up |
| S5-1 | Coverage 18–64, 60 days, enrol in 60 days, HK-008 | PARTIAL | `mpf.resolve_coverage`; catch-up; `enrolment_checks` | test_case_f_leaver_before_60_days…; test_case_e_catch_up…; RC enrolment tests | Age 18/65 boundary inside a period BLOCKS instead of apportioning; no eMPF enrolment workflow |
| S5-2 | Employer 5% from day 1 | IMPLEMENTED | `mpf.contributions` | test_mpf_employer_still_pays_5_percent… | — |
| S5-3 | Employee holiday 30 days + next incomplete period | IMPLEMENTED | `mpf.employee_holiday_applies` | test_60_day_rule_first_contribution_day_and_holiday_boundary | Holiday end not in trace or UI |
| S5-4 | Threshold branches | IMPLEMENTED | `mpf.contributions` | test_case_a_b_c… | — |
| S5-5 | Non-monthly daily × days | PARTIAL | `mpf.thresholds` | test_non_monthly_daily_levels_times_days | `mpf_partial_month_threshold_basis` loaded but never applied; no incomplete-month branch for monthly-paid |
| S5-6 | Contribution day 10th + extension | PARTIAL | `mpf.contribution_due_date`; disruptions | contribution-day tests | Deferral rule [G1]; general holidays not loaded; signal days not on the payslip trace |
| S5-7 | Voluntary contributions | **MISSING** | (knownGaps) | asserts absence | No model, calculation or payload |
| S5-8 | Exemption states | PARTIAL | `mpf.EXEMPTION_CODES` | test_mpf_exemptions_fail_closed… | EXEMPT_DOMESTIC blocks instead of resolving; ORSO / statutory-scheme evidence is free text |
| S5-9 | eMPF remittance payload | PARTIAL | `prepare_empf_submission`; generator | e2e eMPF tests; RPT | No voluntary columns; internal identifiers; no per-member period or employment dates, new / terminated flags |
| HK-009 | eMPF routing default | PARTIAL | as S3-8 | — | as S3-8 |
| HK-010 | Employee MPF records + retention | PARTIAL | `generate_hong_kong_mpf_contribution_record` | RPT | No delivery tracking or deadline; retention period undecided (D-2) |
| S6-1 | MPF eligibility card | PARTIAL | HKStatutoryProfilePanel; preview tab | none | No per-employee card; holiday end not computed for display |
| S6-2 | Contribution preview | PARTIAL | HKCalculationPreviewTab (Super Admin) | none | No operator run preview; no relevant-income field; **no variance from the prior period** |
| S6-3 | Exception queue | PARTIAL | preflight + readiness panels | preflight tests | No HKID / name match, threshold-ambiguity or eMPF-rejection queue |
| S6-4 | eMPF batch screen | PARTIAL | HKComplianceCentreTab `Empf` | backend only | No frontend test |
| S6-5 | Submission receipt | PARTIAL | `transition_empf_submission`; UI | e2e eMPF tests | UI can't enter row outcomes, PAID, settlement or RECONCILED; **D-I** |

## Sections 7–11

| ID | Requirement | Status | Code location(s) | Test(s) | What is missing |
|---|---|---|---|---|---|
| S7-1 | BIR56A + IR56B, one row per employee, due date | IMPLEMENTED | `generate_annual_return`; `ird.due_date` | e2e test_annual_return_from_committed_payroll…; RPT bir56a tests | Manual trigger only; issue date assumed 1 April |
| S7-2 | No IR56B where IR56F/G covers the year | IMPLEMENTED | `ird.ir56b_suppression` | test_case_j_ir56b_suppressed… | Partial coverage only flags; ~~a PREPARED IR56F doesn't suppress~~ an open IR56F / IR56G now holds the IR56B for resolution (D-L) |
| S7-3 | IR56E within 3 months (event-driven) | PARTIAL | `create_event_cases` | test_ir56e_event_case_from_profile_facts | Manual trigger, not event-driven; no payload |
| S7-4 | IR56F one month before cessation | PARTIAL | same | test_ird_event_deadlines | Manual; **D-H**; no payload |
| S7-5 | IR56G one month before departure; hold | PARTIAL | `identify_departure`; `record_ir56g_filed` | e2e case I tests | **D-D**; no payload; changed departure doesn't move the case due date |
| S7-6 | Employee copies + delivery evidence | PARTIAL | `record_employee_copy_delivered`; generators | tenant_support copy tests | Evidence only in audit; masked internal copies, not IRD forms |
| S7-7 | IRD XML schema per form, modes, pre-submit validation | PARTIAL | `ird.py`; schema registry | release_audit / release_candidate schema tests | **No XML generated**; `schema_hash` never set; validation lacks name, address, date and total checks |
| S7-8 | Amendments, never overwrite | IMPLEMENTED | `amend_ird_case`, replacement | remediation + corrections tests | SUPPLEMENTARY refused |
| S7-9 | Annual reconciliation | PARTIAL | `ird.reconcile` | e2e annual return | Certified adjustments not modelled; near-circular check; **D-F**, **D-G** |
| HK-011 | Immutable YA accumulator | IMPLEMENTED | frozen per-payslip `trace.ird` | YA + corrections tests | No accumulator table |
| HK-012 | Tax estimate informational | IMPLEMENTED | `salaries_tax.py` | salaries-tax vector tests | — |
| S8 | IR56G hold states | PARTIAL | `tax_clearance.py`; hold service | case I tests | No automatic DEPARTURE_IDENTIFIED→IR56G_DUE; release letter not matched to the employee; elapsed-period release ends in the LETTER state |
| HK-013 | Hold is a legal hold, traceable | IMPLEMENTED | hold ledger; bank export skip | e2e case I | SP/LSP never enters the ledger; no release payment file |
| S9-1 | Rest day 1 in 7 | **MISSING** | — | — | Rule, roster, substitution |
| S9-2 | Holiday pay, ≥3 months CC, substitution | PARTIAL | `entitlements.holiday_pay` | holiday tests | No substitution; doesn't check the date is a holiday; not paid through payroll |
| S9-3 | Annual leave 7→14 days, accrual, pro-rata, final pay | PARTIAL | `entitlements.annual_leave_days/pay` | test_annual_leave_scale_7_to_14_days | `annual_leave_days` never called by the service; no leave ledger or balance; no pro-rata or payout |
| S9-4 | Sickness 4/5, 120 days | PARTIAL | `entitlements.sickness_*` | sickness tests | No ledger (used days not subtracted); evidence boolean only; not paid |
| S9-5 | Maternity 14 weeks | PARTIAL | `entitlements.maternity_leave_pay` | test_maternity_leave_pay_14_weeks… | No reimbursement claim; not stored or paid |
| S9-6 | Paternity 5 days | PARTIAL | `entitlements.paternity_leave_pay` | test_paternity_leave_pay_5_days_40_weeks; test_d_m_* | ~~40 weeks measured to the leave date, not the birth date~~ — corrected 2026-10-15: the archived Concise Guide ch.7 measures the 40 weeks "immediately before the day of paternity leave", as the code does. Leave window and document deadline now enforced (**D-M**). Remaining: no per-birth day tracking (5 days across separate leave requests); not paid through payroll |
| S9-7 | Average wage engine | IMPLEMENTED | `average_wage.py`; snapshot table | average-wage tests | Straddling payslip blocks instead of apportioning; exclusions typed by hand |
| HK-014 | Committed history, reasons, controlled override | IMPLEMENTED | `_average_wage_rows`; override four-eyes | e2e override test | Free-text reasons, not a statutory list |
| HK-015 | Two CC algorithms | IMPLEMENTED | `continuous_contract.py` | CC tests | 4-week window literal |
| S10-1 | SMW 43.10 / 42.10 split | IMPLEMENTED | as S3-3 | as S3-3 | — |
| S10-2 | SMW test + top-up | PARTIAL | `minimum_wage.assess`; preflight BLOCK | test_preflight_smw_breach_blocks_with_the_top_up_amount | No top-up earning line |
| S10-3 | Hours-record trigger | IMPLEMENTED | as S3-4 | as S3-4 | — |
| S10-4 | OT hours count for SMW | IMPLEMENTED (was PARTIAL; D-A) | daily hours | — | No OT-hours field or test |
| HK-016 | T&A intervals / verified totals | PARTIAL | `record_work_hours` | test_work_hours_are_append_only | Daily totals only, no intervals |
| S11-1 | Final wages deadline, subject to hold | IMPLEMENTED (was PARTIAL, defective; D-B, D-J) | preflight; `payment_treatment` | preflight leaver tests | **D-B** |
| S11-2 | Unused leave / statutory amounts on termination | PARTIAL | `termination.calculate` inputs | e2e case K | Typed by the operator, not calculated |
| S11-3 | SP/LSP eligibility | PARTIAL | `termination.eligibility` | test_sp_lsp_eligibility | Ill-health certificate, lay-off definition, LSP on death |
| S11-4 | 2/3 base, 12-month election, 22,500 → 15,000 | PARTIAL | `termination._portion_base` | case K | Wage typed by hand; not derived from payroll or the average-wage engine |
| S11-5 | 390,000 cap | IMPLEMENTED | termination cap block | cap tests | — |
| S11-6 | 1 May 2025 transition split | IMPLEMENTED | `termination.calculate` | case K | days ÷ 365 convention [G1] |
| S11-7 | Mandatory MPF offset pre-transition only | IMPLEMENTED | offsets loop | case K | Offset amounts typed by hand |
| S11-8 | Voluntary / gratuity offset | IMPLEMENTED | same | test_voluntary_mpf_and_gratuity… | Post-first ordering not evidenced |
| HK-017 | Frozen pre-transition wage | PARTIAL | profile frozen fields | frozen wage tests | **D-C**; never captured from payroll |
| HK-018 | Termination statement complete | PARTIAL | statement generator; four-eyes | statement tests | Subsidy reference not rendered; offsets not template fields; evidence chain not linked |

## Sections 1–2 rules and 12–15

| ID | Requirement | Status | Code location(s) | Test(s) | What is missing |
|---|---|---|---|---|---|
| HK-001 | Activation never implies all categories | IMPLEMENTED | `mpf._OUT_OF_SCOPE_RELATIONSHIPS`; readiness gate | test_mpf_exemptions_fail_closed…; onboarding block test | UI still offers unsupported relationships; profile save doesn't refuse |
| HK-002 | Plan tier never reduces correctness | PARTIAL | no tier reference in HK code | — | No invariant test |
| HK-003 | Outputs separately versioned | PARTIAL | XSD registry; eMPF config; template versions | schema / template tests | One pack per YA for all authorities; no IRD XML; no privacy version entity |
| S12-1 | Payroll state machine | PARTIAL | `PayrollStatus` Draft→Review→Approved→Authorized→Paid→Closed | approval-gate + corrections tests | No explicit VALIDATED / COMMITTED / CORRECTED states (mapped, not named) |
| S12-2 | eMPF state machine | PARTIAL | `EMPF_TRANSITIONS` | eMPF e2e tests | UI lacks VALIDATED / PAID / RECONCILED; RECONCILED has no logic |
| S12-3 | IRD state machine | IMPLEMENTED | `ird.TRANSITIONS`; four-eyes FILED | IRD e2e | No e-filing or ack ingestion |
| S12-4 | Hold state machine | PARTIAL | `tax_clearance.py` | case I | No RELEASE_EVIDENCE / RELEASED states |
| S12-5 | Entitlement lifecycle | **MISSING** | `calculate_entitlement` persists nothing | — | Record, state machine, approval, payroll link, correction |
| S12-6 / HK-019 | Retention classes | PARTIAL | `RETENTION_CATEGORIES`; `RetentionPolicy`; delete guards | privacy / retention tests | Statutory periods not encoded; no purge job; termination-driven clocks missing |
| S13 | Domain entities | PARTIAL | see audit notes | migration tests | No employer-registration table, MPF-result table or leave balances; snapshot hash not stored |
| HK-020 | Deterministic core | IMPLEMENTED | pure engine; pinned pack | purity + replay tests | Purity test covers `countries/hong_kong.py` only |
| HK-021 | Legal-employer scope | PARTIAL | org scoping everywhere | tenant isolation tests | Not by legal employer (`LegalEntity` unlinked) |
| S14-1 | Readiness dashboard | PARTIAL | HKReadinessPanel | readiness tests | No IRD calendar view; no SMW / wage risk roll-up; no FE tests |
| S14-2 | Payroll preflight | PARTIAL | `hk_payroll_preflight`; HKRunPreflightPanel | preflight tests | No CC-change diff; IR56E/F events not in run preflight |
| S14-3 | Worker statutory profile | PARTIAL | HKStatutoryProfilePanel / FormsModal | profile tests | No consolidated status view or CC timeline; no leave balances |
| S14-4 | Pay result drawer | **MISSING** | trace serialised, never read by FE | — | Whole drawer |
| S14-5 | IRD reporting center | PARTIAL | `IrdReporting` | RPT | No IR56E/F creation there; no XML validation, receipt upload or XML download |
| S14-6 | eMPF center | PARTIAL | `Empf` | eMPF tests | VALIDATE / PAID / RECONCILED actions, rejected-row input, amendment UI |
| S14-7 | Tax clearance workspace | IMPLEMENTED | `TaxClearance` | case I | No letter upload |
| S14-8 | Termination calculator | PARTIAL | `Termination` | case K | UI lacks final wages / leave / holiday / pay basis / offset types; no payroll link |
| S14-9 | Payslip (no tax label, hold separate, bilingual, masked) | PARTIAL | PDF + PayslipStub | payslip label tests | **Not bilingual**; PDF lacks the IR56G hold line and the "no Salaries Tax withheld" note; no employer-MPF line; HK not in `income_tax_labels` |
| S15-1 | Integrations | PARTIAL | profiles, work hours, bank file | assorted | No IRD XML / e-filing, eMPF file / API, bank maker-checker / checksum, T&A connector |
| S15-2 | Minimisation, PICS | PARTIAL | identity token; `pics_published` | privacy tests | PICS not checked or delivered; raw HKID still in `compliance_fields` |
| S15-3 | Encryption | PARTIAL | no secrets in eMPF config | control tests | No field-level encryption (D-4) |
| S15-4 | Masking | PARTIAL | sensitive fields; PDF masks | privacy tests | No log-redaction filter; export masking untested |
| S15-5 | RBAC + four-eyes roles | PARTIAL | `require_four_eyes` | role-gate tests | No separate prepare / approve / submit / release roles |
| S15-6 | Append-only audit | PARTIAL | `_audit`; triggers (`d1e5a7c3b9f2`) | audit tests | Reads of IRD / hold / eMPF lists not logged; **D-E** |
| HK-022 | Sensitive facts restricted | PARTIAL | MPF reveal; profile view logging | privacy tests | No field-level permission for departure / exemption facts |
| HK-023 | Cross-border support access | PARTIAL | assisted access | assisted tests | No residency policy; assisted principal is full-write (D-10) |

## Hard-coded statutory literals found (to move into the pack in Phase 2)

* `_PAYROLL_DAYS_DEFAULT = 30` (unpaid-absence divisor, affects MPF relevant income)
* the YA boundary 1 April – 31 March
* the 4-week window and 7-day week in continuous contract
* `* 7` days per week in maternity pay
* `MONTHLY_FREQUENCIES = ("Monthly",)`
* the termination wage deadline "immediately"
* the SP / LSP reason mapping
* the subsidy-scheme URL
* the higher-cap policy for a period that crosses an SMW cap change
* half-up cent rounding in MPF (labelled G1)
