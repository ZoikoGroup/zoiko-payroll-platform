# Mexico (MX) — Completion Gap Register

**Verified against the code on 2026-10-26** (`main` = `cf055ac`, `nikhil` = `a0da835`), not against the phase reports. Paths are relative to `backend/` unless stated; `payroll/` = `app/modules/payroll/`.

**Where Mexico stands.**
- All phases through 11c are built: the engine, runs, special runs, CFDI lifecycle and builder, IMSS / INFONAVIT / ISN / SUA worklists, payments worklist, journal, pilot and GA gating.
- Mexico is **dormant in production**: the registry is PLANNED and the flag is off (`mexico_dormancy.py:52-63`).
- **It cannot run a single real payroll today**, because every statutory table is empty (§B) and four outside integrations do not exist (§C).

**Groups.**
- **A. Code buildable now:** needs only engineering.
- **B. Content / configuration needing sources:** needs saved official sources, transcription, and a second Super Admin's approval. Code exists, or is a small seam.
- **C. Decisions and external inputs:** needs a person, a contract or a credential.

**Owners** are roles: **Eng** (Zoiko engineering), **Transcriber + Reviewer** (two Super Admins: one transcribes, a different one approves), **G1–G8 owner** (the Super Admins who sign that gate), **Release owner**, **ZP-PRIV** (Rugvedh), **Security lead**, **Employer** (each organisation's own data).

**Gates** (`docs/mexico/release-gates/README.md`):
- **G1** ISR / CFDI, **G2** IMSS / SUA, **G4** State ISN, **G5** Labor, **G7** Security / privacy: pre-pilot.
- **G3** INFONAVIT, **G6** External operations: during the pilot.
- **G8** Parallel payroll: the pilot itself.

## Summary

| Group | Items | Blocks a real payroll? |
|---|---|---|
| A. Code | 15 | No, except A9 (the seed path) and A10 (CFDI nodes). The rest are reports, gating and hygiene |
| B. Content | 22 | **Yes, every item.** With the tables empty, every ordinary run blocks (B1, B13) |
| C. Decisions / external | 20 | Yes, for CFDI stamping, payment and filing; the pilot also needs G1, G2, G4, G5, G7 |

---

## A. Code buildable now

| # | Item | Current state (verified) | Unblocks it | Owner | Gate |
|---|---|---|---|---|---|
| A1 | **15 report templates are empty shells** | `scripts/seed_statutory_report_templates.py:2114-2131` (14 national: "Draft shell — filled in Phase N") and `:2176-2182` (MX-ISN-RETURN-CDMX). `components=[]`. The phases they wait for are built | **Phase 12** (plan below) | Eng | G1–G6 evidence (reports are how gates are shown) |
| A2 | **MX-EMPLOYER-COST shows 0** | Reads `employer_social_security` / `employer_pension` (seed `:2143-2152`). `engine/standard.py:425,427` defaults them to 0 and the Mexico calculator never sets them (`engine/countries/mexico.py:111,198` returns only `tds`, `mx_employee_total`, `mx_result`). The real figures live only in `mx_calculation_snapshot.result` | Phase 12: bind to the snapshot (`imss_employer`, `infonavit_employer`, `isn.amount`, `employer_total`) | Eng | G2, G3, G4 |
| A3 | **MX-PAYROLL-REGISTER lacks the IMSS employee quota and INFONAVIT credit** | Fields are only `employee_name`, `gross_pay`, `tds` (ISR), `total_deductions`, `net_pay` (seed `:2133-2142`). IMSS employee and INFONAVIT credit are folded into `total_deductions` (`standard.py:275,320-323`). No subsidy line | Phase 12: snapshot lines `imss_employee`, `infonavit_credit`, `subsidy.applied`, `isr` | Eng | G1, G2, G3 |
| A4 | **No Mexico entry in the snapshot-field catalog** | `_PAYSLIP_ITEM_JSON_FIELD_CATALOG` has IE, SE, NL only (`payroll/service.py:9605,9642,9666`), so any `mx_calculation_snapshot.*` path is rejected (`:10969-10973`). Mexico has no `_PAYSLIP_FIELDS_BY_COUNTRY` entry, so its field picker shows every country's columns (`:9815-9936`, `:10039`) | Phase 12 | Eng | — |
| A5 | **The per-branch IMSS list cannot be addressed** | `result.imss` is a list of branch rows; the path resolver walks dict keys only (`service.py:11830`) | Phase 12: either a keyed path (`imss[branch=…,side=…]`) or a dict copy of the branches in the result | Eng | G2 |
| A6 | **Mexico template activation is refused forever** | `template_activation_refusal` always refuses (`payroll/mexico_service.py:195-197`). The message says templates go live "with the outputs they describe (Phases 6–10)", which are now built | Phase 12: replace with a real gate (fields bound, the report's content Active, its gate SIGNED) | Eng | per report |
| A7 | **OOS-6: the Mexico policy page falls back to India's** | `frontend/src/pages/PolicyConfigPage.jsx:22` uses `COUNTRY_CODE_TO_POLICY_PAGE[country] \|\| INPolicyPage`. `PolicyModule/index.js` has no MX page. The Mexico compliance page links to `/policy/new?…country=MX` (`JurisdictionLayout.jsx:295`) | A "no policy page" state for countries without one, and a Mexico policy page if Mexico needs one (OOS-6) | Eng | — |
| A8 | **Stale "not implemented" text** | `tests/fixtures/mx_golden/README.md` and `engine/countries/mexico.py:17` still cite `MX_ENGINE_NOT_IMPLEMENTED` | Rewrite both | Eng | — |
| A9 | **The pack seed cannot load what has been saved** | `scripts/seed_mexico_canonical_packs.py`: three defects, below | Fix the seed (with the C2 decision) | Eng | G1, G2, G4, G5 |
| A10 | **CFDI nodes the builder still refuses** | `mexico_cfdi_xml.py`; details below | Build each node; most also need a §B / §C input | Eng | G1 |
| A11 | **Triple-rate overtime cannot be reported** | `mexico_cfdi_input._overtime_detail:151-153` refuses any week with triple-rate hours: dates alone don't say which days | Record hours per date on the approved hours (extends 11c) | Eng | G1, G5 |
| A12 | **Runs stop at Approved** | `MX_RUN_NOT_SUPPORTED` for AUTHORIZED / PAID / CLOSED (`mexico_run_service.py:1036`) | Build after stamping (C1, C3) and bank settlement (C7) exist | Eng | G6 |
| A13 | **A canonical SEPARACION classification still blocks** | `classification.py:101` (`MX_SPECIAL_PAY_PHASE9`) for a classification with node SEPARACION. Separation now comes only from the termination reasons (11b) | Decide whether a SEPARACION classification is allowed at all; if not, refuse it at approval instead | Eng | G1 |
| A14 | **Dead code** | `MX_RUN_TYPE_PHASE9` (`mexico_run_service.py:108`: `BUILT_RUN_TYPES == RUN_TYPES`); `classification.py:87` (special kinds are split out first, `preflight.py:91-92`); `MX_ISR_ARITHMETIC_EXCEPTIONS` (no reader); `mx_uma_annual` (required at activation, no engine reader) | Remove the dead paths, or document why they stay | Eng | — |
| A15 | **Engine seams with no table at all** | Hard-coded refusals with no content table to fill: hourly rate (`mexico_run_service.py:325-328`), Art. 93 exemptions for ordinary earnings (`classification.py:107-111`), FIXED SBC integration of non-salary items (`sbc.py:105-108`), IMSS absence / incapacity days (`period.py:94-98`), rest-day work (`labor.py:108-109`), INFONAVIT proration (`infonavit.py:62-69`), subsidy monthly cap (`subsidy.py:58-60`), fixed-days proration at termination (`mexico_run_service.py:466-471`) | Define each content interface (as was done for special pay, PTU and annual adjustment) so it can be transcribed; then the content is §B | Eng | G1, G2, G5 |
| A16 | **No ISR withholding for a worker who earns only the minimum wage** (found W1-3a) | LISR Art. 96 ¶1 (S24 p. 130): "No se efectuará retención a las personas que en el mes únicamente perciban un salario mínimo general correspondiente al área geográfica del contribuyente". The ordinary ISR path does not apply it | A rule in the W3 interfaces, checked against the zone minimum wage (RLISR Art. 167) | Eng | G1 |
| A17 | **Special runs carry no month-to-date income** (found W1-3b) | A finiquito / aguinaldo / PTU run builds `mx_month_to_date` as zeros, so ordinary income paid in it (vacation paid out at termination) cannot be withheld under LISR Art. 96 (the month's whole income); it blocks `MX_FINIQUITO_ORDINARY_INCOME_UNSUPPORTED`. The Art. 96 default for aguinaldo and PTU (D-08 option b) needs the same | Build the month-to-date accumulator for special runs (as `_month_to_date`) | Eng | G1 |

**A9: the three seed defects.**
1. It accepts only sources whose manifest status is exactly `VERIFIED` (`:62`, `:93-94`). The SAT files saved in 11a are `ARCHIVE_COPY_VERIFIED`, and S22 is `WRONG_VERSION`, so any transcribed row citing them makes the seed refuse (`:98-103`).
   **Decided 2026-10-26 (rule 4):** an `ARCHIVE_COPY_VERIFIED` source may back rows in a **Draft** pack only; activation and G1 need `VERIFIED` (a direct download). The fix: the seed (which only ever writes Draft packs) accepts both statuses, and pack activation refuses any row whose source is not `VERIFIED`.
2. `load_manifest` keys the manifest by source code (`:93-94`). S28 and S30 each have several rows (one per file), which collapse to the last row.
3. `_add_slab` always writes `jurisdiction_state=None` (`:202`). `MinWageRow.zone` is never stored, so the zone filter in `content.min_wage` (`engine/jurisdictions/mexico/content.py:114`) can never restrict a professional minimum wage.

**A10: the CFDI nodes still refused.**

| Node | Refused when | Also needs |
|---|---|---|
| `SeparacionIndemnizacion` + TipoRegimen 13 | Percepción 022 / 023 / 025 (`:204-208`) | Last ordinary monthly salary and the accumulable / non-accumulable split from the finiquito rule (B11), and the PAC check (C10) |
| `SubsidioAlEmpleo` | Other payment 002 (`:222-223`) | The subsidy source (C6) |
| `CompensacionSaldosAFavor` | Other payment 004 | The refund mapping (C5) |
| `Incapacidades` | Percepción 014 (`:193-194`) | The absence / incapacity rules (A15, B) |
| `AccionesOTitulos` | Percepción 045 | Out of scope unless an employer pays in shares |
| `JubilacionPensionRetiro` | Percepciones 039 / 044 | Out of scope: Mexico runs pay no pensions |

---

## B. Content / configuration needing sources

**What every item here has in common.**
- The code exists and blocks cleanly while the content is empty.
- Each item needs its source saved and hashed in `docs/mexico/sources/`, transcribed, and approved by a second Super Admin.
- Only S4, S22, S28 and S30 are saved today. S22 is the wrong version, and S4 / S28 / S30 are archive copies (C2). **No other S1–S33 source is in the repo.**

**Pack-borne tables** (`engine/countries/mexico_content.py`; written to the DB by the seed, read through `engine/jurisdictions/mexico/content.py`):

| # | Content | Seam, today | Source (spec code, as `MEXICO_PHASE_1_PLAN.md` and the code's own messages name it) | Block while empty | Gate |
|---|---|---|---|---|---|
| B1 | **ISR monthly / period tariffs** (5 periods × 11 brackets) | `MX_ISR_TARIFFS = ()` (:285) | **S2** (Art. 96 tariffs; S1 evidence) | `MX_CONTENT_MISSING` (`isr.py:25`) | G1 |
| B2 | **UMA** (daily, monthly) | `MX_SCALAR_CONTENT = ()` (:284), keys `mx_uma_*` | **S6** (UMA 2026, from 1 Feb), **S7** (UMA 2025, January) | `MX_CONTENT_MISSING` (`sbc.py:128`, `subsidy.py:49`) | G1, G2 |
| B3 | **Employment subsidy** (rate, income ceiling, period divisor, remainder rule, monthly cap) | `mx_subsidy_*` keys | **S3**, plus SAT's current CFDI subsidy instructions, not yet a source (C6) | `subsidy.py:45-77` | G1 |
| B4 | **IMSS rates** (13 `mx_imss_*` keys) and the SBC ceiling | scalars | **S10** (LSS) | `imss.py:30-41,81`; `sbc.py:129` | G2 |
| B5 | **CEAV 2026 schedule** and its lowest-band reference | `MX_CEAV_SCHEDULE = ()` (:288); `mx_ceav_lowest_band_min_wage_ref` | **S11** (+ S10); the lowest-band reference is decision 4 | `ceav.py:28-49` (`MX_CEAV_LOWEST_BAND_PENDING_G2`) | G2 |
| B6 | **Minimum wages** (general, ZLFN, professional) + **ZLFN municipalities** | `MX_MIN_WAGES = ()` (:286); `MX_ZLFN_MUNICIPALITIES = ()` (:287) | **S9** (S8 cross-check) | `MX_CONTENT_MISSING`; `MX_MIN_WAGE_ZONE_UNRESOLVED` (`labor.py:48`) | G5 |
| B7 | **Workweek maximum**, **overtime tiers**, **hourly-rate rule** | `MX_WORKWEEK = ()` (:289); `mx_overtime_*`; no table for the hourly rate (A15) | **S18** (S17 cross-check); overtime tiers S26 / S18; hourly rate S26 | `labor.py:58-77`; `MX_HOURLY_RATE_RULE_MISSING` | G5 |
| B8 | **Vacation days by service year**, benefit floors (aguinaldo days, vacation premium %, Sunday premium %) | `MX_VACATION_DAYS = ()` (:290); `mx_aguinaldo_min_days`, `mx_vacation_premium_min_pct`, `mx_sunday_premium_min_pct` | **S26** (S19, S20 cross-checks) | `entitlements.py:32-36`; `labor.py:96` | G5 |
| B9 | **INFONAVIT** employer % and the credit bases (percentage / fixed amount), proration | `mx_infonavit_*` keys | **S27** (S15 cross-check) | `infonavit.py:27-79` | G3 |
| B10 | **State ISN**: CDMX rate, base, exemptions, special-pay inclusion; any other state in scope | `MX_ISN_CONTENT = {"CDMX": ()}` (:291); `MX_SPECIAL_PAY_ISN_INCLUSION = {}` (:366); `MX_ISN_STATES_IN_SCOPE = ("CDMX",)` | **S22 is saved but is the WRONG_VERSION (2022 text, 3% vs the spec's 4%)**; the current CDMX fiscal code is needed | `isn.py:25-41`; `MX_STATE_UNSUPPORTED` | G4 |
| B11 | **Rounding rule**, **SBC floor rule**, **work-risk premium range** | `mx_rounding_rule`, `mx_sbc_min_rule`, `mx_risk_premium_min/max_pct` | Rounding: no spec code (ask); SBC floor **S10**; risk-premium range S10 / S29 | `rounding.py:45`; `sbc.py:123`; `mexico_employer_service.py:606` | G1, G2 |

**Module-direct rule objects** (duck-typed interfaces; **no concrete class exists**):

| # | Content | Seam, today | Source | Block | Gate |
|---|---|---|---|---|---|
| B12 | **Special-pay rules** (aguinaldo, vacation premium, vacation payout, PTU, the three separation kinds: exempt part + standalone ISR) and the **aguinaldo rule** | `MX_SPECIAL_PAY_RULES = {}` (:364); `MX_AGUINALDO_RULE = None` (:365) | **S24**, **S25**, **S26** | `special_pay.py:55,64` | G1, G5 |
| B13 | **Pay-frequency → Art. 96 period map** | `MX_PAY_FREQUENCY_ISR_PERIOD = {}` (:423). **Every ordinary run blocks** (`mexico_run_service.py:155-158`) | **S28** c_PeriodicidadPago (saved) + **S2** Art. 96 periods | `MX_PAY_FREQUENCY_MAPPING_MISSING` | G1 |
| B14 | **Termination reasons** and their separation components (each with its kind, 11b); **finiquito rule** | `MX_TERMINATION_REASONS = {}` (:376); `MX_FINIQUITO_RULE = None` (:377) | **S26**, **S24** / **S25** | `termination.py:58,77` | G1, G5 |
| B15 | **PTU rule** and **exclusion reasons** | `MX_PTU_RULE = None` (:387); `MX_PTU_EXCLUSION_REASONS = {}` (:388) | **S26** (payment window **S21**) | `ptu.py:51,59` | G5 |
| B16 | **Annual ISR adjustment rule** and **exclusion reasons** | `MX_ANNUAL_ADJUSTMENT_RULE = None` (:397); `..._EXCLUSION_REASONS = {}` (:398) | **S24** | `annual_adjustment.py:44,57` | G1 |
| B17 | **Art. 93 exemptions for ordinary earnings**, FIXED SBC integration, absence / incapacity, rest-day work | No table (A15) | S24, LSS Art. 27, LFT | `classification.py:109`; `sbc.py:107`; `period.py:96`; `labor.py:109` | G1, G2, G5 |
| B18 | **Filing calendar**, IMSS movement deadline, official holidays, work-risk premium period, authority retry configuration | `MX_FILING_CALENDAR = ()` (:310); `MX_IMSS_MOVEMENT_DEADLINE = None` (:344); `MX_OFFICIAL_HOLIDAYS = {}` (:345); `MX_RISK_PREMIUM_PERIOD = None` (:327); `MX_AUTHORITY_RETRY_CONFIG = {}` (:356) | Calendar: S5 / S27 / S26 / S22 per filing; risk-premium period S10, S14 or S29; movement deadline and holidays: no spec code yet (ask) | `DUE_DATE_UNSOURCED`; `MX_NO_RISK_PREMIUM` (no premium can be approved, `mexico_employer_service.py:591`) | G2, G4, G6 |

**Mappings, vectors and remaining sources:**

| # | Content | Current state | Unblocks it | Owner | Gate |
|---|---|---|---|---|---|
| B19 | **System-concept SAT codes** (ISR 002, IMSS 001, aguinaldo 002, vacation premium 021, PTU 003, annual charge 101, separation 022 / 023 / 025) | Proposed in `MEXICO_PHASE_11A_CODE_PROPOSALS.md`; **none approved**, because no release has been loaded in production | Load `sat_2026_08` into a release, two Super Admins approve it, then propose and approve each mapping | Transcriber + Reviewer | G1 |
| B20 | **SAT codes on earning classifications** | No canonical classification exists (organisations define their own codes) | Per employer: each classification gets its c_TipoPercepcion code; a second Super Admin approves | Employer + Reviewer | G1 |
| B21 | **Golden vectors** | `tests/fixtures/mx_golden/` holds **only README.md, 0 vectors**. Activation needs them (`mexico_service.py:426-437`); `test_mexico_engine_unreachable.py:35-36` pins the directory empty | After B1–B18: ordinary, aguinaldo, PTU, vacation premium, finiquito / liquidación and annual-adjustment cases, each matched to an independent calculation (G1 checklist) | Transcriber + G1 / G2 owner | G1, G2 |
| B22 | **CFDI cancellation reasons** (`c_MotivoCancelacion`) | Not in the 11a extract; cancellation refuses `MX_CFDI_CANCEL_REASON_UNAVAILABLE` (`mexico_cfdi_service.py:595`) | Save the SAT cancellation catalog; add it to the pinned set | Transcriber + Reviewer | G1, G6 |

---

## C. Decisions and external inputs

| # | Item | Current state | Unblocks it | Owner | Gate |
|---|---|---|---|---|---|
| C1 | **PAC: choice, contract, sandbox credentials** (X3) | `_ADAPTERS = {}` (`mexico_pac.py:113`); `MX_PAC_NOT_CONFIGURED`. Only the test mock exists | Choose a PAC, sign the contract, get sandbox credentials; then build its adapter (Eng) | Release owner | G1, G6 |
| C2 | **Archive copies of S4 / S28 / S30** | Status `ARCHIVE_COPY_VERIFIED`. **Policy decided 2026-10-26: they may feed Draft packs only**; activation and G1 need `VERIFIED` | Re-download from sat.gob.mx (VPN or a colleague in Mexico) and compare the SHA-256 (G1 checklist), before any activation | Release owner + G1 owner | G1 |
| C3 | **CSD custody and signing** (X4) | `GcpSmSigner` always refuses (`mexico_cfdi_builder.py:74-81`) | GCP Secret Manager project and IAM, plus a test CSD behind a `gcp-sm://` reference (D12); then cadena original + sello (Eng) | Security lead + Release owner | G1, G7 |
| C4 | **Source of SalarioDiarioIntegrado** | `SDI_SOURCE = None` (`mexico_cfdi_input.py:42`): every receipt with an IMSS registration is refused, including in the 11c preview | Decide LFT Art. 84 integrated salary vs the IMSS SBC (S4 pp. 39-40) | G1 owner | G1 |
| C5 | **Undecided SAT codes** | `INFONAVIT_CREDIT` 009 / 010; `VACATION_PAYOUT` 001 / 038; `ANNUAL_ADJUSTMENT_REFUND` 004 / 005 | Decide each, with its source | G1 owner | G1, G3 |
| C6 | **Employment subsidy in the CFDI after the 2024 reform** | `SUBSIDY_APPLIED` deliberately unmapped; the saved guide cites the 2013 decree | Save SAT's current instructions as a new source | G1 owner | G1 |
| C7 | **Bank / SPEI payment file** | Worklist CSV only, "NOT A BANK FILE" (`mexico_payment_service.py:12-15,40`) | Choose the bank(s) and get their layout | Release owner + Employer | G6 |
| C8 | **IMSS IDSE / SUA / SIPARE layouts and transmission** | Worklists only, "NOT AN IMSS / IDSE FILE" (`mexico_imss_service.py:6-7,43`); SUA reconciled against figures the operator types in (`mexico_filing_service.py:406-485`) | IMSS layout documents; IDSE credentials (employer e.firma); a decision whether Zoiko transmits or the employer does | Release owner + Employer | G2, G6 |
| C9 | **State ISN return transmission** | Manual references only (`mexico_filing_service.py:578-676`) | The state portal process per state in scope | Release owner | G4, G6 |
| C10 | **Separation receipt validation** | TipoRegimen 13 conflicts with the contract-type rule (S4 pp. 34-35) | Settle against the PAC test environment (needs C1) | G1 owner | G1 |
| C11 | **830 CHH postal codes with an inconsistent time-zone row** | Refused `MX_CFDI_TIMEZONE_RULE_INVALID` (`mexico_cfdi_input.py:114-116`) | Decide whether SAT's row is wrong and what to use (a later catalog or a source) | G1 owner | G1 |
| C12 | **Union membership (`Sindicalizado`)** | No field; not emitted (S4 p. 33 says to register it) | Decide whether to add the field | Release owner | G1 |
| C13 | **Q9: identifiers at rest** | Plaintext in `payroll_employees.compliance_fields` **and in `payslip_items.compliance_fields`**, a platform-wide snapshot found in 11b | Security lead decision (Q9 / HK D-4); a pilot needs Q9 RECORDED | Security lead + ZP-PRIV | G7 |
| C14 | **`MX_IDENTITY_TOKEN_KEY`** in production | GA and pilot precondition | Provision in Secret Manager | Security lead | G7 |
| C15 | **Durable XML storage** | `MX_CFDI_STORAGE_NOT_DURABLE` refuses without GCS (`mexico_cfdi_service.py:192`) | Configure GCS for CFDI XML in each environment | Release owner + Eng | G6, G7 |
| C16 | **ZP-PRIV reviews owed** | 10c, 10f, 10g, 11a, 11b and 11c were merged without Rugvedh's review (`PRODUCTION_STATE.md`) | His reviews; any change he asks for lands before a pilot grant | ZP-PRIV | G7 |
| C17 | **Code-owner review not enforced** | PRs merge with no review (10g report §9) | Create the `@ZoikoGroup/privacy-reviewers` team; require code-owner review on `main` | Release owner (lead) | G7 |
| C18 | **Employer chart of accounts** | Journal refuses `MX_JOURNAL_MAPPING_MISSING` (`mexico_journal_service.py:339,346`) | Per employer: map accounts | Employer | G8 |
| C19 | **Hosting decision; Q9; the pilot organisation** | Pilot preconditions (D2) | Record them; name the pilot organisation | Release owner | Pilot |
| C20 | **G1–G8 sign-off and the activation path** | No gate is SIGNED; the registry is PLANNED; the flag is off | Evidence packs signed by two Super Admins per gate; then the pilot (G1, G2, G4, G5, G7) → G3, G6, G8 in the pilot → GA | Gate owners + Release owner | all |

---

## Order that completes Mexico

1. **C2, then B13, B1–B11, B12, B14–B18:** the content. This is the critical path: nothing calculates without it.
2. **A9** (the seed), so that content can be loaded; then **B21** (golden vectors) → **G1, G2, G4, G5**.
3. **C4, C5, C6, C11, B19, B22**, then **A10**: CFDI completeness.
4. **C1, C3, C15:** stamping in the PAC sandbox → G1 complete.
5. **C13, C14, C16, C17** → G7.
6. **Phase 12 (A1–A6)**, which can run in parallel from today: the reports the gate evidence needs.
7. **The pilot** (C19): G3, G6 (C7, C8, C9, A12), G8 (C18).
8. **General availability.**

---

## Progress

| Date | Items | State |
|---|---|---|
| 2026-10-26 | A8, A9, A14 | Phase 11d (staged). The seed accepts archive copies for Draft; approval and activation need VERIFIED, which only a logged direct download can set (`VERIFICATION_LOG.csv`) |
| 2026-10-26 | Sources | Batch A plus S1 and S11 saved as archive copies (Draft only). **S22 is a CANDIDATE only:** Art. 158 reads 4%, but the Gaceta decree for 2026 was not found |
| 2026-10-26 | **B1, B2** | Transcribed, `[PENDING G1]` (Batch 1). Log: TL-ISR-1/2, TL-UMA-1 |
| 2026-10-26 | **B3** (partial) | Rate, ceiling and divisor transcribed (TL-SUB-1). **The remainder rule is not in S3** and is still open |
| 2026-10-26 | **B13** (partial) | Codes 02, 04, 05 and 10 mapped (TL-PER-1). **01 Diario is a G1 decision**; the other codes have no Art. 96 table |
| 2026-10-26 | **B3** (complete) | Remainder rule `NOT_PAYABLE` from the DOF 01-05-2024 base decree, Art. Segundo para 2, which is still in force (TL-SUB-2). CFDI reporting of the subsidy (C6) is still open |
| 2026-10-26 | **B4, B5, B6, B7, B8, B9** (Batch 2) | Transcribed, `[PENDING G1]`. Derived rows: the E&M rates, the cash-benefit shares, overtime x2/x3 and the vacation bands. The SM-to-UMA reading needs the DOF 27-01-2016 decree (proposed as S34). The INFONAVIT credit bases and the SBC floor rule are not transcribed |
| 2026-10-26 | **S22** | VERIFIED (SAF "CODIGO FISCAL 2026"; checks 1 and 2 passed; Gaceta 19-12-2025 saved). B10 (ISN) is now transcribable |
| 2026-10-26 | **B11** (rounding) | Candidate sources reported for the G1 owner; it still blocks every calculation |
| 2026-10-26 | **B9, B11** (W1-1) | SBC floor `RAISE_TO_ZONE_MIN_WAGE` (LSS Art. 28) and INFONAVIT percentage basis `SBC_TIMES_DAYS` (Ley INFONAVIT Art. 29 III) transcribed. S34 (de-indexation decree) saved. **Fixed-amount INFONAVIT basis: BLOCKED-ON-SOURCE** (INFONAVIT's payment regulation is not in the Diputados compilation). Open decisions moved to `DECISIONS_PENDING.md` |
| 2026-10-26 | **B10** (W1-2) | CDMX ISN 4% (S22 Art. 158, VERIFIED source) and the special-pay inclusions (Arts. 156, 157) transcribed; gate 1b-1 passes for the CDMX pack. Open: D-06 (separation lines), D-10 (2026 micro / small-employer benefit) |
| 2026-10-26 | **B12** (W1-3a) | Special-pay exemptions (LISR Art. 93 XIII, XIV), RLISR 174 withholding and the LFT 87 aguinaldo rule transcribed as rule objects; the year-to-date exempt accumulator added. Blocked on D-07 (unit), D-08 (method), D-09 (monthly income). New item A16 |
| 2026-10-26 | **B14** (W1-3b) | Termination-reason catalog (LFT Arts. 47–54, 162; 7 reasons) and finiquito rule (LFT Art. 79; LISR Art. 96 separation rate) transcribed. Blocked on D-12 (indemnity salary, = C4), D-13 (part years), D-07b, D-09; reasons outside the catalog D-11. New item A17 |
