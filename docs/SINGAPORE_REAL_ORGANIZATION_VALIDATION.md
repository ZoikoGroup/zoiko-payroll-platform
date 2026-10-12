# Singapore — Real-Organization Functional Validation

Run date: 2026-09-29 · Code: working tree over `264c585` · Alembic head `445abd6a9083`.

**What this is.** The Singapore product was exercised on a **disposable PostgreSQL database**. The database was built from a read-only schema copy of the shared database (revision `998877665544`) and the working tree's `scripts/deploy_migrate.sh`. The run used three disposable tenants: A for payroll, B for isolation, and C for the fail-closed case.

Everything ran through the product's own service functions and its HTTP API with real JWTs:
- 4 payroll cycles (Aug, Sep, Oct 2026 and Jan 2027), each reaching Approved through the Singapore preflight;
- a pack version change (v1.2 → v1.3);
- the 2027 CPF pack;
- a correction;
- all 11 reports.

**Where the expected values come from.** Each one is either a sourced golden fixture (`backend/tests/fixtures/sg_golden`) or a seeded, source-linked pack or MOM schedule row. None was typed into the harness.

**What this is not.** It is **internal engineering evidence**: it is not CPF Board, IRAS, MOM or PDPC evidence, and it is not the G8 design-partner parallel run. No gate is marked passed because of it.

**Result: 44 PASS / 0 FAIL.**

Found and fixed while running it (both are regression-tested):
1. **Creating a new pack version dropped row values.** The documented correction path (`_clone_pack_rates`) lost effective dates, sources and the CPF `assessment_basis`, so every Singapore payroll under a new version was BLOCKED and effective-dated rows became open-ended.
2. **Refused evidence-review actions were not audited.**

Two behaviours were confirmed:
- the preflight refuses a CPF-liable employee with a foreign identifier prefix (`CPF_ACCOUNT_PREFIX`);
- an ACTIVE employee past their leaving date is refused by the engine until offboarded (status Inactive).

| # | Area | Scenario | Input | Expected | Actual | Result | Source / configuration | Pack | Payslip |
|---|---|---|---|---|---|---|---|---|---|
| 1 | configuration | golden-vector certification | tests/fixtures/sg_golden | PASS | {"status": "PASS", "passed": 37, "total": 37} | **PASS** | golden fixtures | — | — |
| 2 | configuration | packs Active via maker-checker (approver B, activator C) | SG-PAYROLL-2026 v1.2 + 2027 v1.0 | Active, Active | ["Active", "Active"] | **PASS** | pack lifecycle | SG-PAYROLL-2026 v1.2 | — |
| 3 | templates | all 11 SG templates Approved(B) -> Published -> Active | seeded Draft | 11 | 11 | **PASS** | template lifecycle | — | — |
| 4 | lifecycle | cycle 1 (Aug 2026) reaches APPROVED through the SG preflight | generate -> advance x N | APPROVED | {"status": "Approved", "errors": []} | **PASS** | advance_payroll_run_status | — | — |
| 5 | calculation | CPF — citizen age 40, OW 6,000 | ctc 72,000 (OW 6,000/month) | {"employee_pension": "1200", "employer_pension": "1020", "employer_payroll_tax": "11.25"} | {"employee_pension": "1200.00", "employer_pension": "1020.00", "sdl": "11.25"} | **PASS** | golden f1 (ZP-SG-ENG-001 §17, CPF Board Table 1) | SG-PAYROLL-2026 v1.2 | 1 |
| 6 | calculation | CPF — citizen age 57 (55–60 band), OW 5,000 | dob 1969-06-15, ctc 60,000 | {"employee_pension": "900", "employer_pension": "800"} | {"employee_pension": "900.00", "employer_pension": "800.00", "cohort": "SC_SPR3"} | **PASS** | golden cpf_2026_age57_ow_5000_december (CPF Board 2026 table) | SG-PAYROLL-2026 v1.2 | 2 |
| 7 | calculation | FWL — S Pass, full month (employer cost, no CPF) | FOREIGN, S_PASS issued 2025-01-01 | {"employer_eht": "650.00", "employee_pension": 0} | {"employer_eht": "650.00", "employee_pension": "0.00", "fwl": "CALCULATED"} | **PASS** | pack row fwl_s_pass_monthly (MOM source #9) | SG-PAYROLL-2026 v1.2 | 3 |
| 8 | calculation | SHG — CDAC instructed S$5.00 (evidence recorded) | shg CDAC=5.00, ctc 72,000 | {"professional_tax": "5.00", "employee_pension": "1200", "net_pay": "4795.00"} | {"professional_tax": "5.00", "employee_pension": "1200.00", "net_pay": "4795.00"} | **PASS** | golden shg_instructed_amount | SG-PAYROLL-2026 v1.2 | 4 |
| 9 | calculation | SHG — CDAC band at S$3,000 | shg CDAC, ctc 36,000 | {"professional_tax": "1.00"} | {"professional_tax": "1.00"} | **PASS** | pack SHG slab SHG-2026-CDAC-B2 (CPF Board SHG table) | SG-PAYROLL-2026 v1.2 | 5 |
| 10 | calculation | CPF low-wage phase-in 600 + SDL floor | ctc 7,200 (600/month) | {"employee_pension": "60", "employer_pension": "102", "sdl": "2.00"} | {"employee_pension": "60.00", "employer_pension": "102.00", "sdl": "2.00"} | **PASS** | golden cpf_low_wage_phase_in_600; pack row sdl_min_monthly | SG-PAYROLL-2026 v1.2 | 6 |
| 11 | calculation | Overtime — Part 4 workman, 6 OT hours at the statutory minimum (CPF OW) | basic 4,000; attendance 3 × 10 h vs 8 h policy | {"overtime": "188.82", "employee_pension": "837", "employer_pension": "713"} | {"overtime": "188.82", "hours": "6", "status": "PAID", "employee_pension": "837.00", "employer_pension": "713.00"} | **PASS** | golden part4_overtime_is_ow (MOM Part 4 formula) | SG-PAYROLL-2026 v1.2 | 7 |
| 12 | calculation | every payslip records its month's PWM classification | cycle 1 | 10 | 10 | **PASS** | _sg_trace_with_pwm_classification | SG-PAYROLL-2026 v1.2 | — |
| 13 | calculation | WP employee joining 1 Oct has no Aug payslip | date_of_joining 2026-10-01 | 0 | 0 | **PASS** | joiner handling | — | — |
| 14 | MOM data | WP levy before 24 Sep 2026 is EXTERNAL_DATA_REQUIRED: calculation BLOCKED, run approval refused | Work Permit services T2 R2, Aug 2026 | {"fwl": "BLOCKED", "employer_eht": 0, "approval": "refused"} | {"fwl": "BLOCKED", "employer_eht": "0.00", "runStatus": "Review", "errors": ["Singapore preflight blocks approval: FWL_BLOCKED (SGVC1)"]} | **PASS** | fail-closed (no pre-24-Sep MOM WP rate seeded) | — | — |
| 15 | lifecycle | cycle 2 (Sep 2026) APPROVED | generate -> advance | APPROVED | {"status": "Approved", "errors": []} | **PASS** | advance_payroll_run_status | — | — |
| 16 | two-cycle | cycle 2: same CPF for the same population; YTD OW subject carries cycle 1 | CPF40 Aug vs Sep | {"sameCpf": true, "ytdOwSubjectBeforeSep": ">= Aug OW (6000.00)"} | {"aug": ["1200.00", "1020.00"], "sep": ["1200.00", "1020.00"], "ytdOwSubjectBeforeSep": "6000.00"} | **PASS** | engine YTD accumulator | SG-PAYROLL-2026 v1.2 | 12 |
| 17 | configuration | pack v1.3 created (rows cloned), approved B, activated C; v1.2 Superseded | upsert_jurisdiction_pack | {"v12": "Superseded", "v13": "Active"} | {"v12": "Superseded", "v13": "Active", "v13Rates": 298} | **PASS** | pack lifecycle | SG-PAYROLL-2026 v1.3 | — |
| 18 | lifecycle | cycle 3 (Oct 2026) APPROVED | generate -> advance | APPROVED | {"status": "Approved", "errors": []} | **PASS** | advance_payroll_run_status | — | — |
| 19 | calculation | FWL — Work Permit services T2 R2, full Oct 2026 (after 24 Sep) | issued/joined 2026-10-01, ctc 24,000 | {"employer_eht": "600", "employee_pension": "0", "sdl": "5.00"} | {"employer_eht": "600.00", "employee_pension": "0.00", "sdl": "5.00"} | **PASS** | golden wp_services_tier2_basic_full_month (MOM WP levy from 24 Sep 2026) | SG-PAYROLL-2026 v1.3 | 24 |
| 20 | calculation | AW — bonus S$2,000 on OW 6,000 (TW 8,000, AW ceiling not binding) | attendance bonus 2,000 | {"additional_compensation": "2000", "awClassified": "2000", "employee_pension": "1600", "employer_pension": "1360"} | {"additional_compensation": "2000.00", "awClassified": "2000.00", "employee_pension": "1600.00", "employer_pension": "1360.00", "sdl": "11.25"} | **PASS** | CPF Board Table 1 on TW 8,000 (= golden f2's capped OW 8,000: 1,600 / 1,360) | SG-PAYROLL-2026 v1.3 | 30 |
| 21 | multi-pack | cycle 3 payslips pin pack v1.3; cycle 1 payslips keep v1.2 | pack change between cycles | {"aug": 1, "oct": 3} | {"aug": 1, "oct": 3} | **PASS** | payslip pinning | — | — |
| 22 | IR21 | IR21 case opened on cessation, file-by date from the pack lead-time row | S Pass ceasing 2026-12-31 | {"status": "DRAFT", "fileBy": "on/before the trigger"} | {"status": "DRAFT", "fileBy": "2026-11-30"} | **PASS** | pack ir21_filing_lead_months | — | — |
| 23 | correction | append-only correction: original unchanged, delta carries the CDAC deduction | Oct payslip, CDAC added | {"originalShg": "0.00", "deltaShg": "2.00"} | {"originalShg": "0.00", "originalEe": "1200.00", "deltaShg": "2.00", "chain": {"originalPayslipId": 22, "deltaPayslipId": 33, "sequence": 1}} | **PASS** | correct_sg_finalized_payslip; pack SHG slab | SG-PAYROLL-2026 v1.3 | 33 |
| 24 | reports | SG-PAYROLL-REGISTER (Oct 2026): tenant, rows, every payslip-column total = payslip sum, versions, masking | run 3 | match | {"employees": 11, "totals(report, payslips)": {"gross_pay": ["44800.00", "44800.00"], "total_deductions": ["7406.00", "7406.00"], "net_pay": ["37394.00", "37394.00"]}, "pack": "1.3", "template": "1.0"} | **PASS** | generate_report_from_template | SG-PAYROLL-2026 v1.3 | — |
| 25 | reports | SG-PAYROLL-SUMMARY (Oct 2026): tenant, rows, every payslip-column total = payslip sum, versions, masking | run 3 | match | {"employees": 0, "totals(report, payslips)": {"gross_pay": ["44800.00", "44800.00"], "net_pay": ["37394.00", "37394.00"], "employee_pension": ["7400.00", "7400.00"], "professional_tax": ["6.00", "6.00"], "employer_pension": ["6376.00", "6376.00"], "employer… | **PASS** | generate_report_from_template | SG-PAYROLL-2026 v1.3 | — |
| 26 | reports | SG-CPF-CONTRIBUTION (Oct 2026): tenant, rows, every payslip-column total = payslip sum, versions, masking | run 3 | match | {"employees": 11, "totals(report, payslips)": {"employee_pension": ["7400.00", "7400.00"], "employer_pension": ["6376.00", "6376.00"], "gross_pay": ["44800.00", "44800.00"], "total_deductions": ["7406.00", "7406.00"], "net_pay": ["37394.00", "37394.00"]}, "… | **PASS** | generate_report_from_template | SG-PAYROLL-2026 v1.3 | — |
| 27 | reports | SG-SHG-MONTHLY (Oct 2026): tenant, rows, every payslip-column total = payslip sum, versions, masking | run 3 | match | {"employees": 11, "totals(report, payslips)": {"professional_tax": ["6.00", "6.00"], "gross_pay": ["44800.00", "44800.00"], "total_deductions": ["7406.00", "7406.00"], "net_pay": ["37394.00", "37394.00"]}, "pack": "1.3", "template": "1.0"} | **PASS** | generate_report_from_template | SG-PAYROLL-2026 v1.3 | — |
| 28 | reports | SG-FWL-MONTHLY (Oct 2026): tenant, rows, every payslip-column total = payslip sum, versions, masking | run 3 | match | {"employees": 11, "totals(report, payslips)": {"employer_eht": ["1250.00", "1250.00"], "gross_pay": ["44800.00", "44800.00"], "total_deductions": ["7406.00", "7406.00"], "net_pay": ["37394.00", "37394.00"]}, "pack": "1.3", "template": "1.0"} | **PASS** | generate_report_from_template | SG-PAYROLL-2026 v1.3 | — |
| 29 | reports | SG-SDL-MONTHLY (Oct): employer total = sum of payslip SDL | Oct 2026 | 93.75 | {"employer_name": "SG Validation A Pte Ltd", "total_employee_count": 11, "total_sdl_before_rounding": "93.75", "total_sdl_payable": "93"} | **PASS** | generate_sg_sdl_monthly | SG-PAYROLL-2026 v1.3 | — |
| 30 | PWM | retail averaging: Oct shortfall (2,300 < Sep-2026 floor) met by the 3-month average | SITI: 2,600 / 2,600 / 2,300; ASSISTANT_CASHIER | {"result": "MET_BY_AVERAGING", "averaging": "MET"} | {"result": "MET_BY_AVERAGING", "averaging": "MET", "requirements": ["2305.00", "2435.00", "2435.00"], "avgPaid": "2500.00", "avgReq": "2391.67"} | **PASS** | MOM Retail Annex D; sgp_pwm_overtime_schedules | SG-PAYROLL-2026 v1.3 | — |
| 31 | PWM | role change: each month averaged at ITS job level (Annex D §3) | HO: Senior Aug/Sep, Asst Supervisor Oct | ["SENIOR_CASHIER_ASSISTANT", "SENIOR_CASHIER_ASSISTANT", "ASSISTANT_SUPERVISOR"] | {"levels": ["SENIOR_CASHIER_ASSISTANT", "SENIOR_CASHIER_ASSISTANT", "ASSISTANT_SUPERVISOR"], "jobLevelOct": "ASSISTANT_SUPERVISOR", "result": "MET_BY_AVERAGING"} | **PASS** | payslip pwmClassification | SG-PAYROLL-2026 v1.3 | — |
| 32 | LQS | LQS: locals evaluated against the seeded floor (employer hires foreign workers) | Oct 2026 | {"SGV07 (600)": "below LQS", "SGV01 (6,000)": "meets"} | {"SGV07": {"result": "BELOW"}, "SGV01": {"result": "MET"}} | **PASS** | engine trace['lqs'] | SG-PAYROLL-2026 v1.3 | — |
| 33 | reports | SG-CPF-EZPAY: download refused before approval, preparer cannot approve, 150-byte ASCII records | Oct 2026 | {"gated": true, "selfApproveRefused": true, "recordLength": 150} | {"gated": true, "selfApproveRefused": true, "records": 17, "lengths": [150]} | **PASS** | EZPay lifecycle | SG-PAYROLL-2026 v1.3 | — |
| 34 | multi-pack | SG-IR8A 2026 over payslips from v1.2 and v1.3: no single version, both listed | income year 2026 | {"applicableVersion": null, "taxPacksUsed": [1, 3]} | {"applicableVersion": null, "taxPacksUsed": [1, 3], "rows": 11} | **PASS** | _sg_pinned_pack | v1.2 + v1.3 | — |
| 35 | reports | SG-IR21-REGISTER lists the open case, masked | 2026 | {"cases": 1, "open": 1} | {"cases": 1, "open": 1} | **PASS** | generate_sg_ir21_register | SG-PAYROLL-2026 v1.3 | — |
| 36 | determinism | regenerating cycle-1 reports after 3 cycles, a pack change and a correction is identical | SDL Aug + CPF contribution Aug | {"identical": true, "pack": "1.2", "previousSuperseded": true} | {"sdlIdentical": true, "cpfIdentical": true, "pack": "1.2", "previous": "Superseded"} | **PASS** | report regeneration | SG-PAYROLL-2026 v1.2 | — |
| 37 | calculation | CPF — 2027 tables from 1 Jan 2027 (age 57, OW 5,000) | Jan 2027 cycle, pack SG-PAYROLL-2027 | {"employee_pension": "950", "employer_pension": "825", "pack": 2} | {"employee_pension": "950.00", "employer_pension": "825.00", "pack": 2, "run": "Approved"} | **PASS** | golden cpf_2027_age57_ow_5000_january (CPF Board 2027 table) | SG-PAYROLL-2027 v1.0 | 35 |
| 38 | tenant isolation | tenant B cannot read tenant A's employee / payslip / report / IR21 / EZPay (A can) | HTTP GET with each tenant's JWT | {"A": "2xx", "B": "404/403"} | {"A": {"employee": 200, "payslip": 200, "generated report": 200, "IR21 case": 200, "EZPay file": 200}, "B": {"employee": 404, "payslip": 404, "generated report": 404, "IR21 case": 404, "EZPay file": 404}} | **PASS** | HTTP API | — | — |
| 39 | tenant isolation | tenant B cannot alter tenant A's employee | HTTP PUT | {"status": "403/404", "name": "unchanged"} | {"status": 404, "name": "TAN CPF FORTY"} | **PASS** | HTTP API | — | — |
| 40 | super admin | summary is Super Admin only and carries no tenant payroll data | HTTP GET | {"denied": "403", "leaks": []} | {"denied": {"org_admin": 403, "payroll_admin": 403}, "superAdmin": 200, "leaks": []} | **PASS** | HTTP API | — | — |
| 41 | super admin | readiness tells the truth: templates Active, gates external, decisions required, activation BLOCKED | GET statutory-summary | {"templates": "PASS", "external_evidence": "EXTERNAL_REQUIRED", "business_decisions": "BUSINESS_DECISION_REQUIRED", "production_activation": "BLOCKED"} | {"report_templates": "PASS", "generators": "PASS", "external_evidence": "EXTERNAL_REQUIRED", "business_decisions": "BUSINESS_DECISION_REQUIRED", "external_integrations": "EXTERNAL_REQUIRED", "production_activation": "BLOCKED", "templatesActive": 11} | **PASS** | HTTP API | — | — |
| 42 | super admin | PWM reference data: 6,132 rows through the Super Admin API | GET pwm-schedules | 6132 | 6132 | **PASS** | HTTP API | — | — |
| 43 | super admin | evidence maker-checker over HTTP: self-review refused; probe REJECTED by B; G8 never PASS | PUT sg-review | {"self": 400, "reject": 200, "G8": "REJECTED"} | {"self": 400, "reject": 200, "G8": "REJECTED"} | **PASS** | HTTP API | — | — |
| 44 | governance | refused governance actions are audited (EZPay self-approval, evidence self-review) | refusals attempted above | {"sg_cpf_ezpay": ">= 1", "source_artifact": ">= 1"} | {"sg_cpf_ezpay": 1, "source_artifact": 1} | **PASS** | audit | — | — |

Harness: `sg_org_validation.py` (the release owner's scratch workspace). Direct database writes in it are labelled HARNESS: only the tenant's billing subscription (commercial setup outside Singapore).

## Real-browser UI verification: Super Admin → Compliance → Jurisdictions → Singapore

**Environment.** The real frontend (Vite dev server, port 5175) talked to the working-tree backend (uvicorn, port 8011, from the disposable tree, which has no `.env`), and that backend used the disposable database populated by the run above. Headless Google Chrome was driven by Playwright. The session logged in through the **real login form** as a Super Admin.

**Proof it was not the shared database.** The backend reported packs v1.2 Superseded / v1.3 Active / 2027 Active and 6,132 PWM rows. None of these exist on the shared database.

**Result: 20 PASS / 0 FAIL.** Full-page screenshots were reviewed as part of the check.

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | login through the real login form | **PASS** | {"url": "http://localhost:5175/super-admin/dashboard"} |
| 2 | Compliance landing lists Singapore as a link | **PASS** |  |
| 3 | Singapore compliance page opens | **PASS** | {"url": "http://localhost:5175/super-admin/compliance/singapore"} |
| 4 | landing shows the Singapore control-center tabs without an extra click | **PASS** |  |
| 5 | tab "Overview" renders backend data | **PASS** | {"missing": []} |
| 6 | tab "Statutory Summary" renders backend data | **PASS** | {"missing": []} |
| 7 | tab "Readiness & Operations" renders backend data | **PASS** | {"missing": []} |
| 8 | tab "Statutory Components" renders backend data | **PASS** | {"missing": []} |
| 9 | tab "Source Evidence" renders backend data | **PASS** | {"missing": []} |
| 10 | tab "PWM Schedules" renders backend data | **PASS** | {"missing": []} |
| 11 | tab "Report Templates" renders backend data | **PASS** | {"missing": []} |
| 12 | tab "Golden Vectors" renders backend data | **PASS** | {"missing": []} |
| 13 | embedded lifecycle list shows every Singapore template | **PASS** | {"count": 11} |
| 14 | template detail shows Approve + status control + versions/audit tabs | **PASS** |  |
| 15 | template audit history renders (approve / status changes) | **PASS** |  |
| 16 | no browser console errors before the deliberate illegal transition | **PASS** | {"consoleErrors": []} |
| 17 | UI status control: Active → Draft refused by the server (message shown) | **PASS** |  |
| 18 | Report Templates hub links Singapore (not 'Coming soon') | **PASS** |  |
| 19 | Singapore Report Templates page lists the templates | **PASS** |  |
| 20 | after it: only the server's 400 refusal of Active → Draft | **PASS** | {"consoleErrors": ["Failed to load resource: the server responded with a status of 400 (Bad Request)"]} |

The browser check found two UI gaps; both are fixed and re-verified:
1. **Landing.** The Singapore page opened on "Select a pack from the list", so none of the Singapore tabs were visible until a pack was clicked. It now opens on the Active pack in force, using the opt-in `autoSelectPack` of `JurisdictionLayout` (Singapore only).
2. **Template lifecycle.** The Report Templates tab was view-only and pointed at a module where Singapore was not reachable: there was no Singapore Report Templates page, route or map entry. It now embeds the shared lifecycle module under the 11-template catalogue: Approve, status control, versions and audit. The same module is also at `/super-admin/report-templates/singapore`.

One transition was tried on purpose: setting an Active template to Draft through the UI control. The server refused it: "SG-SDL-MONTHLY v1.0 cannot move from Active to Draft (allowed: Superseded)". The refusal appears in that template's audit history. The browser console shows only that 400 response.
