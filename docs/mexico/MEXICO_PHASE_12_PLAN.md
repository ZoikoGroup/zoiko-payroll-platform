# Mexico (MX) — Phase 12 Plan: report templates

**Status: PLAN — AWAITING APPROVAL. Nothing is built.** Written 2026-10-26. It covers gap register items **A1–A6**: the 15 shells, the MX-EMPLOYER-COST and MX-PAYROLL-REGISTER fixes, the snapshot catalog, list addressing and the activation gate.

**Principle:** every field is bound to data Phases 6–10 already produce. No figure is recomputed for a report, and no official layout is invented: where one is content-blocked, the report is a register explicitly labelled "not an official file".

## 1. How the shared engine can read a Mexico snapshot (verified)

The report-template engine already binds per-payslip JSON snapshots through a data source kind:
- **Kind:** `PAYSLIP_ITEM_JSON`, with `source_column = "<snapshot column>.<dotted.path>"`.
- **Resolver:** `payroll/service.py:11808-11871`, supporting SUM_RUN and SUM_YTD. Amounts stored as strings become numbers for currency fields (`_report_json_number`, `:11881-11895`). A missing path gives None, not 0.
- **Allowed paths** come only from the per-country catalog `_PAYSLIP_ITEM_JSON_FIELD_CATALOG` (`:9605`). Today it has IE, SE and NL; any other path is refused at `upsert_report_field` (`:10969-10973`).
- **The Netherlands is the model to copy:** `_nl()` in `scripts/seed_statutory_report_templates.py:2227-2231`, five templates (`:2266-2320`), and `tests/test_netherlands_report_templates.py`, which proves every path exists in a real `nl_result` and that generation returns the engine's figures.

**What Mexico's snapshot holds:**
- `payslip_items.mx_calculation_snapshot = {"result": mx_result, "inputHash", "components", "pack", "engineVersion", "pilot"}` (`mexico_run_service.py:788-793`).
- Engine figures sit under `.result.`, all as strings (`engine/jurisdictions/mexico/trace.py`):
  - `isr`, `isr_withheld`, `isr_taxable`, `subsidy.{amount, applied}`
  - `imss_employee`, `imss_employer`, `infonavit_employer`, `infonavit_credit`, `isn.amount`
  - `employee_total`, `employer_total`, `gross`, `days_paid`
  - `annual_adjustment.{…}`, `special.{run_type, concept, isr_exempt, detail.{aguinaldo, vacation, separation[]}}`
  - **lists:** `imss[]` (one row per branch and side) and `concepts[]` (one per earning line, with `kind`, `gross`, `isr_exempt`, `isr_taxable`, `cfdi_concept_code`).

**What the engine cannot do:**
1. It can't address an item inside a JSON list, so the IMSS branches and the separation / special-pay concepts are out of reach (D1).
2. It reads only payslip, run, employer-profile and employee rows. Mexico's own tables (CFDI documents, IMSS movements, SUA periods, ISN returns, vacation records, PTU allocations, annual adjustments) need **dedicated generators**, the pattern Hong Kong already uses: `_HK_DEDICATED_GENERATOR_REPORT_TYPES` (`service.py:19200`), refused by the generic generator at `:11961-11971`, persisted by `_hk_write_report` (`hong_kong_service.py`) as immutable `GeneratedReport` rows with supersession.

## 2. Engine changes (shared, additive)

| # | Change | Where | Effect on other countries |
|---|---|---|---|
| E1 | `_PAYSLIP_ITEM_JSON_FIELD_CATALOG["MX"]`: every `mx_calculation_snapshot.result.*` path the templates use, each labelled | `service.py` | None (a new key) |
| E2 | **Keyed list selector** in the path resolver: `result.imss[branch=EM_CUOTA_FIJA,side=employer].amount`, `result.concepts[kind=AGUINALDO].gross`, with SUM when several items match. Only segments containing `[` take the new path; every existing path is unchanged | `_json_path_value` (`service.py:11826-11832`) | None: no existing catalog path contains `[` (a test proves it). **Decision D1** |
| E3 | `_PAYSLIP_FIELDS_BY_COUNTRY["MX"]`: Mexico's picker shows only Mexico-relevant columns (today it falls back to every country's) | `service.py:9815-9936` | None |
| E4 | `_REPORT_COMPONENTS_BY_TYPE` entries for the 15 MX report types (today they fall back to the default list) | `service.py:10070-10627` | None |
| E5 | `MX_DEDICATED_GENERATOR_REPORT_TYPES` (refused by the generic generator, as for HK); a `mexico_report_service.py` that persists through a shared-shape writer (as `_hk_write_report` does) | new + `service.py:11936` | None |
| E6 | **Replace Mexico's always-refuse activation hook** (`mexico_service.py:195-197`) with a gate: every field bound and resolving on a real committed payslip; the report's statutory content Active (its pack, plus the ISN state pack for an ISN report); for a statutory filing report, its gate SIGNED (G1 ISR, G2 IMSS / SUA, G3 INFONAVIT, G4 ISN). **Decision D3** | `mexico_service.py` | None (Mexico's own hook) |

## 3. The 18 templates

The kinds below:
- **T** = template engine (snapshot paths, generic generator);
- **D** = dedicated generator from Mexico's tables;
- **T + D** = both: the template carries the per-payslip fields, and the dedicated part adds the table data.

| Template | Kind | Components → fields (binding) | Official layout | Gate |
|---|---|---|---|---|
| **MX-PAYROLL-REGISTER** (fix) | T | `employer_info` (as today); `employee_info.employee_name`; `earnings`: `gross` (`result.gross`), `days_paid`; `deductions`: `isr` (`result.isr_withheld`), **`imss_employee`** (`result.imss_employee`), **`infonavit_credit`** (`result.infonavit_credit`), `total_deductions`, `net_pay`; `other_payments`: **`subsidy_applied`** (`result.subsidy.applied`) | None required (internal register) | G1, G2, G3 |
| **MX-EMPLOYER-COST** (fix) | T | `employer_contributions`, all SUM_RUN: **`imss_employer`** (`result.imss_employer`), **`infonavit_employer`** (`result.infonavit_employer`), **`isn`** (`result.isn.amount`), **`employer_total`** (`result.employer_total`), `gross_pay`. **The two shared columns that are always 0 are removed** | None required | G2, G3, G4 |
| MX-JOURNAL | — | Unchanged (the journal export is Phase 10b's own) | — | G8 |
| **MX-SUBSIDY** | T | `employee_info`; `subsidy`: `amount` (`result.subsidy.amount`), `applied` (`result.subsidy.applied`), `remainder`, `isr_before` (`result.isr`), `isr_withheld`; totals SUM_RUN | None required | G1 |
| **MX-IMSS-BRANCH** | T (E2) | `employee_info`; `sbc`: the daily SBC of each segment (`result.sbc.segments[…]`, a list, so via E2; one value per payslip when the period has one segment); `employee_quota` / `employer_quota` per branch via `result.imss[branch=…,side=…].amount` for each branch the pack defines; `imss_employee`, `imss_employer`; totals SUM_RUN. The branch keys come from the pack's IMSS keys, not typed | SUA layout content-blocked (C8): labelled a register | G2 |
| **MX-INFONAVIT** | T | `employee_info`; `infonavit_employer` (`result.infonavit_employer`), `infonavit_credit` (`result.infonavit_credit`); totals SUM_RUN. Bimonthly totals come from the INFONAVIT liability (D) | INFONAVIT / SIPARE layout content-blocked (C8) | G3 |
| **MX-AGUINALDO** (per employee) | T | `employee_info`; `aguinaldo`: `days` / `fraction` (`result.special.detail.aguinaldo.*`), `gross` (`result.concepts[kind=AGUINALDO].gross`), `exempt` (`.isr_exempt`), `taxable`, `isr_withheld`, `rule_source` (`result.special.rule_source`) | None required | G1, G5 |
| **MX-FINIQUITO** (per employee) | T (E2) | `employee_info`; `aguinaldo` (as above); `vacation`: `days` (`result.special.detail.vacation.days`), `payout`, `premium`; `separation`: `seniority_premium` / `separation_payment` / `indemnity` via `result.concepts[kind=SEPARATION_*].gross` with exempt / taxable; `isr_withheld`; `net_pay` | None required (statement) | G1, G5 |
| **MX-ANNUAL-ISR-ADJ** | T + D | **T** (the run that applies it): `result.annual_adjustment.{fiscal_year, difference, period_withheld, withheld, change, carry_forward}`. **D** (the employer-year view): rows from `PayrollMxAnnualIsrAdjustment` (`mexico_annual_service.employer_year_view`) | Annual return content-blocked (B16) | G1 |
| **MX-CFDI-NOMINA-RECEIPT** (per employee) | D | Rendered **only from the stored stamped XML** of a STAMPED document (`PayrollMxCfdiDocument.xml_storage_ref`), never from engine figures. Fields: those the printed example on S4 p. 114 shows (issuer, receiver, nómina header, perceptions, deductions, other payments, totals, UUID, certificate numbers, seal). **Production: blocked until stamping exists (C1, C3).** Built and tested with the synthetic signer | Printed representation: the example on S4 p. 114; the binding rule for its content is not in the saved sources (a source to add) | G1 |
| **MX-CFDI-STATUS** | D | `mexico_cfdi_service.run_summary` / `lifecycle_overview`: counts by status, UNKNOWN items with age, rejections and cancellations; per document folio, payslip, status, UUID. **Never XML** | None required | G1, G6 |
| **MX-ISR-MONTHLY** | D | `mexico_filing_service.list_liabilities` (authority SAT, report type MX_ISR_WITHHOLDING): period, amount, its source runs, status filed / paid / reconciled, references | SAT declaration: no file layout in scope; labelled a register | G1 |
| **MX-IDSE-MOVEMENTS** | D | `mexico_imss_service.list_movements`: movement type, effective date, worker (masked NSS), SBC, status, outcome reference | **IDSE layout content-blocked (C8)**: labelled "not an IDSE file" | G2 |
| **MX-SUA-RECON** | D | `PayrollMxSuaPeriod` / `PayrollMxSuaDifference` via `mexico_filing_service`: registration, bimester, Zoiko vs SUA figures by branch, differences and their resolution | SUA content-blocked (C8) | G2 |
| **MX-SIPARE** | D | The IMSS / INFONAVIT bimonthly liability (`list_liabilities`): line amount, period, payment reference recorded outside Zoiko | **SIPARE layout content-blocked (C8)** | G2, G3 |
| **MX-VACATION-ACCRUAL** | D | `PayrollMxVacationRecord` + `PayrollMxBenefitAccrual` (`mexico_benefits_service.vacation_view`): per worker and service year, entitlement, taken, paid out, balance, premium | None required | G5 |
| **MX-PTU-DISTRIBUTION** | D | `PayrollMxPtuCycle` / `PayrollMxPtuAllocation` (`mexico_ptu_service.cycle_view` / `allocation_view`): fiscal year, distributable amount, per-worker days and salary shares, exclusions, amounts paid | None required (the LFT notice content is B15) | G5 |
| **MX-ISN-RETURN-CDMX** | D | `PayrollMxIsnReturn` / `PayrollMxIsnLiability` (filing service): base, rate, amount, period, return status and reference | **CDMX return form content-blocked (B10 wrong version, C9)**: labelled a register | G4 |

**Identifiers in reports (MX-061):**
- No report carries a full RFC, CURP or NSS: names, employee codes and masked identifiers only.
- The CFDI receipt is the one exception, because a receipt must show them. It is rendered only on demand for the organisation, never stored as a `GeneratedReport` body, and is subject to Rugvedh's review.

## 4. Tests and proof

- **Every catalog path resolves on a real committed payslip:** an ordinary, an aguinaldo, a finiquito (synthetic rules) and an annual-adjustment run. Mirrors `test_netherlands_report_templates.py:95`.
- **Generation returns the engine's own figures** (no recomputation), including SUM_RUN over string amounts.
- **EMPLOYER-COST** totals equal `result.employer_total`, and no longer show 0.
- **E2:** the keyed selector proves single and multiple matches and a missing key (None). Every existing IE / SE / NL path still resolves unchanged (no `[` in any existing path).
- **Dedicated generators:** the immutability and supersession tests the HK generators have. A pilot / dormant organisation is refused with Mexico's own codes.
- **The activation gate (E6):** a template whose content is Draft is refused; one with every precondition met activates.
- **No full identifier in any generated report:** a scan, like 11b's.
- `test_mexico_report_templates.py:32` (only the 3 templates have components) is updated; idempotence is kept.
- **Browser:** each template's preview in the Super Admin report screens; one generated report per kind; NL / HK report screens unchanged.

## 5. Decisions

| # | Question | Recommendation |
|---|---|---|
| D1 | Keyed list selector in the shared resolver (E2), or dedicated generators for the per-branch IMSS and finiquito / aguinaldo concepts? | **The selector.** It is additive, keeps those reports on the template engine (editable fields, previews) and is also useful to other countries |
| D2 | The dedicated generators for the 10 table-based reports (§3 kind D) | **Yes**, following the HK pattern |
| D3 | The Mexico activation gate (E6) in place of the permanent refusal | **Yes.** Today no Mexico report can ever go Active |
| D4 | The CFDI printed receipt (MX-CFDI-NOMINA-RECEIPT): build now from stored stamped XML (production-blocked until stamping), or defer until C1 / C3? | **Build now.** It is fully testable with the synthetic signer, and it is G1 evidence once the PAC sandbox stamps |
| D5 | Sub-phases | **12a:** E1–E4 + REGISTER / EMPLOYER-COST fixes + the 6 template-engine shells. **12b:** E5 + the 9 dedicated reports. **12c:** E6 + the CFDI receipt + browser. Each staged and reported separately |

## 6. What Phase 12 will not do

- It doesn't produce an official SUA, IDSE, SIPARE, ISN-return or SAT file. Those layouts are content-blocked (gap register C8, C9, B10), and each such report says so on its face.
- It doesn't make any report show real figures in production. Mexico stays dormant, and every figure needs the §B content first.
- It doesn't change any other country's template, path or report.
