# Mexico (MX) — Completion Programme Progress

One section per step of `MEXICO_COMPLETION_MASTER_PROMPT.md`. Each step is one local commit on `nikhil` (never pushed). Open decisions are in `DECISIONS_PENDING.md`; item states are in `MEXICO_COMPLETION_GAP_REGISTER.md`.

**Base (verified 2026-10-26):**
- `nikhil` = `52af6eb`, two local commits ahead of `origin/main` = `cf055ac` (PR #131 merge).
- Production should be at `b9f3d5a1c7e2` (deploy 40265941034, per `PRODUCTION_STATE.md`; `gh` is not installed here, so the run was not re-checked).
- Mexico is dormant.

**How tests run in this programme.**
- Every pytest run pins `PAYROLL_DATABASE_URL` to a scratch SQLite file, so a partial run can never reach the `.env` database.
- Each step runs every `tests/test_mexico_*.py` file.
- The full backend suite (5 sequential chunks, alone) runs at the end of each workstream, and after any step that touches shared code.

---

## W1-1 — What Batch 2 left open (SBC floor, INFONAVIT bases, S34)

**ZP-PRIV:** not required. No change to authz, redaction, RLS, migrations, cross-tenant data or identifiers.

**What changed**
- **S34 saved.** The DOF 27-01-2016 de-indexation decree (Diputados copy, archive capture verified against its digest). Status `ARCHIVE_COPY_VERIFIED`, so it can back Draft content only. Registered in the content module, the addendum and the manifest. The SBC-ceiling and E&M-threshold rows now cite its Transitorio Tercero for their UMA reading (TL-S34-1).
- **`mx_sbc_min_rule` = `RAISE_TO_ZONE_MIN_WAGE`.** From LSS Art. 28, "límite inferior el salario mínimo general del área geográfica respectiva" (TL-SBC-1).
- **`mx_infonavit_percentage_basis` = `SBC_TIMES_DAYS`.** From Ley INFONAVIT Art. 29 III, which points to fr. II and so to the LSS base (TL-INF-2).
- **Citation fix.** The INFONAVIT 5% row cited Art. 29 II on PDF p. 15; it is on p. 16.
- **`compare` checks quoted wording.** Every wording a row's citation quotes (12+ characters) must be found in the cited file. Text rules had no machine check before. Result: 365 checks, 0 misses (56 CEAV image cells are checked by the blind transcription and tests).
- **Still blocked:**
  - `mx_infonavit_fixed_amount_basis`: the regulation is not saved (BLOCKED-ON-SOURCE).
  - The CEAV lowest-band reference: G2 decision D-03.
  - Rounding: G1 decision D-01.
- **New:** `DECISIONS_PENDING.md` (D-01 to D-05).

**Controls**
- Blind second transcription (separate agent; only S10, S27, S34): same quotes, same pages, same choices. It also placed Art. 29 II on p. 16 independently.
- Gate 1b-1 on a scratch SQLite seed: `MX-PAYROLL-2026` has 238 rows, **0 missing and 0 extra**. The check now fails **only** on `mx_rounding_rule` (D-01). `MX-ISN-CDMX-2026` is empty until W1-2.

**Tests**
- New: the SBC-floor and INFONAVIT-basis vocabulary tests, the S34 citation test, and the quote-check test (`test_mexico_source_tool.py`).
- Updated: the missing-key pins in `test_mexico_scaffolding.py` and `test_mexico_engine_content.py`; the source-code range now runs to S34.
- All 78 `tests/test_mexico_*.py` files: **937 passed, 63 skipped, 0 failed.**

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None. No migration |
| Mexico in production | Dormant. No deploy runs the seed. Run by hand, it writes the two new rows to the Draft pack only |
| Engine | An SBC below the zone minimum wage is raised to it (it used to block with `MX_SBC_MIN_RULE_MISSING`). A PERCENTAGE INFONAVIT notice is computed (it used to block). Neither is reachable in production while Mexico is dormant and no pack is Active |
| Other jurisdictions | None. Mexico-only modules, tests and docs |

**Gap register:** B9 narrowed (percentage basis done; fixed-amount basis BLOCKED-ON-SOURCE). B11 narrowed (SBC floor done; rounding = D-01).

---

## W1-2 — CDMX state ISN (gap register B10)

**ZP-PRIV:** not required.

**What changed**
- **`MX-ISN-CDMX-2026` gets its rate:** `mx_isn_rate_pct` = 4, from S22 Art. 158 (TL-ISN-1). S22 is the SAF 2026 edition and **VERIFIED** (logged direct download), so this is the first Mexican content row with a VERIFIED source.
- **CDMX special-pay inclusion** (TL-ISN-2), from Arts. 156 and 157:
  - in the base: aguinaldo, vacation premium (reading), seniority premium;
  - out: PTU.
- **Still blocking (`MX_ISN_SPECIAL_PAY_RULE_MISSING`):** vacation paid out at termination, the separation payment and the indemnity. Neither article names them: decision **D-06** (G4).
- **`compare` covers module-direct rules.** Every rule object (ISN inclusion now; special pay, termination, PTU, annual adjustment and calendar as they arrive) must quote the wording it rests on, and each quote must be found in the cited file. A rule that quotes nothing is a miss. Result: 371 checks, 0 misses.
- **D-02 note.** RLISR Art. 175 ties the daily tariff to piece-work pay, not to 01 Diario.

**Controls**
- Blind second transcription (separate agent; S22 only): same rate, article, page and wording; same inclusions; "DOES NOT SAY" for the three concepts left blocked. **It also found** the 2026 micro / small-employer ISN benefit (Transitorio TRIGÉSIMO SÉPTIMO, PDF p. 815), which I confirmed in the text. It is not modelled: the SAF rules it depends on are not saved, and the wording is ambiguous. Recorded as **D-10** and as a pre-pilot item in the G4 checklist. Until it is settled, a micro or small CDMX employer would be computed at the full 4% (no CDMX pack is Active).
- Scratch seed: `MX-ISN-CDMX-2026` has 1 row, 0 missing, 0 extra. **Gate 1b-1 passes for CDMX.** Its activation readiness now shows content, evidence and sources-verified met; the G1 review and the golden vectors are not.

**Tests**
- New: the CDMX rate and inclusion tests, and the compare rule-quote test.
- Updated: the synthetic fixtures (seed, approval, activation gates, router) now also empty the ISN table; the benefits fixture empties the inclusion map when a test needs it absent; the real-pack readiness pin now expects CDMX content, evidence and sources met.
- All `tests/test_mexico_*.py`: **940 passed, 63 skipped, 0 failed.**

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None |
| Mexico in production | Dormant. A hand-run seed would write one row into the Draft CDMX pack |
| Engine | ISN is computed at 4% once a CDMX pack is Active (none is). Aguinaldo, vacation premium and seniority premium count toward the base; PTU does not |
| Super Admin readiness | The CDMX pack now shows 3 of 5 activation checks met |
| Other jurisdictions | None |

**Gap register:** B10 done for CDMX, except D-06 and D-10.

---

## W1-3a — Special-pay exemptions, withholding and the aguinaldo rule (gap register B12)

**ZP-PRIV:** not required. No change to authz, redaction, RLS, migrations or identifiers.

**Shared code (additive):** `engine/base.py` `PayrollContext` gains two optional fields, `mx_year_to_date_exempt` and `mx_separation_date`, both defaulting to None. Only the Mexico engine reads them; no other jurisdiction's path changes.

**What changed**
- **New `engine/countries/mexico_rules.py`:** the rule objects, wired into `MX_SPECIAL_PAY_RULES` and `MX_AGUINALDO_RULE` (log TL-SP-1 to TL-SP-3).
  - LISR Art. 93 XIV: aguinaldo 30 days, vacation premium 15, PTU 15, per calendar year.
  - LISR Art. 93 XIII: separation 90 days per year of service, one shared cap allocated pro rata.
  - Vacation paid out: no exemption.
  - A worker on the area minimum wage blocks (`MX_ART93_I_NOT_MODELLED`).
  - RLISR Art. 174 standalone withholding.
  - LFT Art. 87: aguinaldo fraction and payable-by date (19 December).
- **Three decisions, each one switch, each blocking with its own code:**
  - **D-07** unit of the Art. 93 caps (UMA or zone minimum wage);
  - **D-08** the withholding method for a special run;
  - **D-09** monthly ordinary income from a daily salary.
  Both D-07 readings are built and tested.
- **Engine seam:** `_year_to_date_exempt` gives every payslip the special-pay exempt amounts already committed in the calendar year. It uses the same payment order, replaced chain and correction deltas as the month-to-date accumulator, and is bound into the input hash (`yearToDateExempt`). Preflight passes the rules the zone, the seniority date, the separation date and the separation total.
- **`compare`:** 438 checks, 0 misses. Every quoted wording of the new rules is found in S24, S25, S26 or S34.

**Effect on runs (none reachable in production)**
- An aguinaldo amount is now computed (LFT Art. 87).
- Any special payment's exempt part blocks with `MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED` (D-07), where it used to block with `MX_SPECIAL_PAY_RULE_MISSING`.
- Aguinaldo and PTU runs will then block on D-08 and D-09.

**Tests**
- New: `test_mexico_rules.py` (14 tests: every switch undecided, both units, the year-to-date cap, Art. 93 I, the six-month rounding of years of service, the shared XIII cap, RLISR 174 fractions I–V, the LFT 87 fraction in 365- and 366-day years). Also the accumulator test and the real-rules tests (aguinaldo run, orchestrator).
- Updated: the "rule missing" tests now empty the rule maps themselves, because the real ones are transcribed.
- All `tests/test_mexico_*.py`: **958 passed, 63 skipped, 0 failed.** The accumulator test, added during that run, passes with its file (51 passed across benefits, rules and orchestrator).

**Controls.** Blind second transcription (separate agent; S24, S25, S26 only): agreement on every limit, unit, page and formula. It also raised the "en forma general" condition (D-04), the Sunday-premium and overtime exemptions (A15, W3) and Art. 96 ¶1 (new gap item **A16**).

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None |
| Shared engine | `PayrollContext` gains two optional Mexico fields (default None). No other jurisdiction reads them |
| Mexico in production | Dormant. Special payments move from "rule missing" to the named decision codes |
| Approval fingerprint | Mexican payslips gain the `yearToDateExempt` input component. No Mexican run exists in production, so nothing is invalidated |
| Other jurisdictions | None (the full suite runs at the end of W1) |

**Gap register:** B12 narrowed (special-pay rules transcribed; D-07, D-08, D-09 open). New A16.


---

## W1-3b — Termination reasons and the finiquito rule (gap register B14)

**ZP-PRIV:** not required.

**What changed**
- **Termination-reason catalog (7 LFT reasons) and the finiquito rule** in `mexico_rules.py`, wired into `MX_TERMINATION_REASONS` and `MX_FINIQUITO_RULE` (log TL-TER-1, TL-TER-2):
  - Arts. 47, 48, 49–50, 51–52, 53 III, 54 and 162 III;
  - Art. 50 I / II by contract type (c_TipoContrato 01 / 03);
  - the seniority premium bounded by Arts. 485–486;
  - vacation owed (Art. 79);
  - the separation withholding rate (LISR Art. 96 ¶7, RLISR Art. 172).
- **New decisions, each one switch that blocks with its own code:**
  - **D-12** indemnity salary (Art. 89; the same question as C4);
  - **D-13** part years of service;
  - **D-07b** the Art. 486 cap unit;
  - **D-11** reasons left out of the catalog (mutual consent, death, Art. 434).
- **New gap A17:** special runs carry no month-to-date income, so vacation paid out at termination blocks.
- **Finiquito facts:** they now carry the contract type and the labour policy, and the contract type is bound into the input hash.
- **`compare`:** 501 checks, 0 misses.

**Controls**
- Blind second transcription (separate agent; S26, with S24 and S25): agreement on every amount, condition and page. Its NOT FOUND answers match D-13 and the two readings. It added four details (Art. 89 ¶2 variable pay, the Art. 486 several-areas average, the Art. 50 IV platform workers, the Art. 47 notice), all recorded.

**Tests**
- `test_mexico_rules.py`: 9 more tests (23 in all). They cover each switch, both service-year counts, the Art. 485–486 bounds under both units, every reason's components, Art. 50 I both branches, unsupported contract types, the 15-year voluntary rule, vacation owed, the separation rate and the below-salary tariff, and the vacation-payout block.
- Termination tests: the empty-catalog tests empty the map themselves, and the real catalog is pinned.
- All `tests/test_mexico_*.py`: **969 passed, 63 skipped, 0 failed.**

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None |
| Mexico in production | Dormant. Organisations would now see the 7 LFT reasons when recording a termination (Mexico organisations are behind the dormancy flag) |
| Engine | A finiquito's components and withholding now come from the LFT / LISR. Each amount blocks until D-12, D-13, D-07b and D-09 are decided, and rounding (D-01) still blocks every amount |
| Other jurisdictions | None |

**Gap register:** B14 narrowed (catalog and rule transcribed; D-11, D-12, D-13, D-07b open). New A17.

---

## W1-4 — PTU and the annual ISR adjustment (gap register B15, B16)

**ZP-PRIV:** not required.

**What changed**
- **PTU rule** (LFT Arts. 122–127; LISR Arts. 9, 76 V, 150), with 3 exclusion reasons (Art. 127 I, VI, VII). Log TL-PTU-1:
  - half the pool by days, half by the cash daily-rate salary (the classifications' PTU flag);
  - the Art. 127 VIII cap, the more favourable of three months and the three-year average;
  - the deadline, 60 days after the annual return (31 March for a company, 30 April for an individual).
- **Annual adjustment rule** (LISR Art. 97; S3 Art. Tercero), with 1 exclusion reason (Art. 97 c). Log TL-ANN-1:
  - eligibility a) and b);
  - the 2026 Art. 152 tariff less the subsidy that corresponded, never below zero;
  - tax owed withheld in full; a balance in the worker's favour set against the following withholdings.
- **New content table `MX_ISR_ANNUAL_TARIFFS`:** 2026, 11 brackets from S2 Anexo 8 C.II. It is continuous, quota-consistent and machine-checked.
- **Additive service facts:**
  - PTU: each worker's PTU history from DISTRIBUTED cycles, and the employer's taxpayer type for the deadline.
  - Annual: the subsidy due (`subsidy_due_total`) and gross income (`annual_gross`).
- **New decision D-14** (PTU cap excess; the average over fewer years). It blocks only an allocation where it changes the result.
- **New G5 item:** the Art. 127 II trusted-worker cap is not modelled.
- **`compare`:** 533 checks, 0 misses.

**Controls**
- Blind second transcription (separate agent; S26, S24, S2, S3): all 11 brackets and every rule agree. It confirmed the law's silence behind D-14, the gross-or-taxable ambiguity (D-04) and the "le correspondió" wording, and added LISR Art. 9 and Art. 122 ¶2–3, both recorded.

**Tests**
- `test_mexico_rules.py`: 6 more (29 in all): the PTU split and exclusions, the cap and both D-14 blocks, the deadlines, the Art. 97 eligibility edges (1 January, 1 December, $400,000.00 / .01), the annual tax with and without the subsidy, and applying a difference.
- `test_mexico_content.py`: the annual tariff.
- The PTU and annual fixtures now set "absent" explicitly; the source-tool synthetic fixture empties the annual table.
- All `tests/test_mexico_*.py`: 972 passed and 4 failed in the full run; those 4 (the synthetic fixture not yet emptying the annual table) were fixed and pass (14/14 in their file). **0 failing.**

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None |
| Mexico in production | Dormant. PTU allocation and the annual adjustment now follow the LFT / LISR. Both still need rounding (D-01) to emit amounts |
| Other jurisdictions | None |

**Gap register:** B15 and B16 done, except D-14 and the Art. 127 II item.

---

## W1-5 — Filing calendar, movement deadline, holidays, risk-premium period (gap register B18, B11)

**ZP-PRIV:** not required.

**What changed**
- **S35 saved:** Código Fiscal de la Federación, last reform DOF 09-04-2026 (archive copy, digest verified). Registered in the manifest, the addendum and the content module.
- **`MX_FILING_CALENDAR`:**
  - ISR withholding, the 17th of the next month (CFF Art. 6 I, the general rule for every employer);
  - CDMX ISN, the 17th of the next month (S22 Art. 159).
  - **IMSS and INFONAVIT are held back (D-15).** RCV (LSS Transitorio VIGÉSIMO SÉPTIMO) and INFONAVIT (1997 Transitorio SEXTO) stay bimonthly until the ISSSTE law changes, and that law is not saved. One IMSS liability carries every branch.
- **`MX_RISK_PREMIUM_PERIOD`:** from 1 March (RACERF Art. 32 III). An employer risk premium can now be approved once the range is in an Active pack.
- **`MX_IMSS_MOVEMENT_DEADLINE`:** 5 business days (LSS Art. 15 I), counted from the day after the event (RACERF Art. 57; LSS Art. 34).
- **`MX_OFFICIAL_HOLIDAYS` stays empty: D-16.** The LFT (Arts. 74 / 715) and CFF (Art. 12) lists differ; both sets of 2026 dates are worked out in TL-CAL-3. Movements remain `DUE_DATE_UNSOURCED`.
- **Not transcribed:** the authority retry configuration. It is provider- and portal-specific (C1, the PAC).
- **`compare`:** 538 checks, 0 misses.

**Controls**
- Blind second transcription (separate agent; 7 sources): agreement on every rule, page and 2026 date. It found the LSS RCV transitory, which removed the IMSS rule, plus five details recorded in TL-CAL.
- The real filing-calendar seed is pinned: on the real manifest only the CDMX ISN rule (VERIFIED source) seeds its 12 dates, from 17 Feb 2026 to 17 Jan 2027.

**Tests**
- New: the calendar, deadline and period content test, and the real-calendar seed test.
- The four tests that pinned these as empty now empty them themselves. The movement test also proves that the real 5-day rule still gives no due date without a holiday list.
- All `tests/test_mexico_*.py`: in the full run, 972 passed and the 4 empty-pinning tests failed. They were fixed and pass in their files, and the affected files pass after the IMSS rule was removed (62 passed). **0 failing.**

**Production effect**

| Area | Effect when merged |
|---|---|
| Database / Alembic | None |
| Filing calendar | **No deploy runs the template seed.** If someone ran it by hand, it would write 12 live `MX_ISN_RETURN` / CDMX calendar rows (S22 is VERIFIED). The ISR rule is skipped until S35 is VERIFIED |
| Mexico in production | Dormant. Risk premiums can now pass the period check (approval still needs the legal range in an Active pack). Movements still have no due date |
| Other jurisdictions | None |

**Gap register:** B18 narrowed (ISR and CDMX ISN calendar, movement deadline and risk-premium period done; IMSS / INFONAVIT D-15; holidays D-16; retry configuration with C1). B11 risk-premium period done.

---

## W1-6 — Subsidy remainder rule and CFDI subsidy reporting (gap register B3, C6)

**ZP-PRIV:** not required. No code change.

- **Remainder rule: done in Batch 2.** `mx_subsidy_remainder_rule` = `NOT_PAYABLE`, from the DOF 01-05-2024 base decree, Art. Segundo ¶2 (TL-SUB-2). W1-4 added its annual counterpart (Art. Tercero III: no tax and nothing paid when the subsidy exceeds the annual tax).
- **CFDI reporting (C6): BLOCKED-ON-SOURCE.** Searched again on 2026-10-26:
  - **The 2024 and 2025 decrees (S3):** say nothing on how the subsidy is reported on the CFDI.
  - **RMF 2026 (S1), rules 3.17.12 and 3.17.13 (PDF p. 452):** still framed on the 2013 decree ("Decreto DOF 11/12/2013 Décimo"). They say the subsidy is creditable only if noted "de manera expresa y por separado en los comprobantes fiscales de nómina", and that the CFDI must follow the "Guía de llenado del comprobante del recibo de pago de nómina", whose newest saved edition (S4, 2023) predates the 2024 decree.
  - **Still needed:** SAT's current instructions for reporting the 2024-decree subsidy (TipoOtroPago 002 / `SubsidioAlEmpleo`). The CFDI concept `SUBSIDY_APPLIED` stays unmapped, and A10's `SubsidioAlEmpleo` node stays refused.
- **Production effect:** none.
- **Gap register:** B3 done; C6 BLOCKED-ON-SOURCE (W2-5).

---

## End of W1 — full backend suite

Run 2026-10-26 15:19–15:43 on `7b55b46`, in five sequential chunks on scratch SQLite, alone.

| Chunk | Result |
|---|---|
| 0 | 976 passed, 16 skipped, **3 failed**: the known local-only `tests/privacy/test_route_registry.py` tests (your uncommitted `/health` routes in `backend/app/main.py`) |
| 1 | 2,488 passed, 2 skipped, 2 xfailed, **1 failed**: the known local-only Hong Kong docs test |
| 2 | 1,264 passed, 32 skipped |
| 3 | 1,142 passed, 67 skipped |
| 4 | 1,621 passed, 3 skipped |

**Total: 7,491 passed, 120 skipped, 2 xfailed.** The only failures are the 4 known local-only ones. No other jurisdiction's behaviour changed.


---

## W2 — Sources still missing

**ZP-PRIV:** not required. Sources, content and docs only.

| Step | Result |
|---|---|
| W2-1 S22 (CDMX fiscal code) | **Done in Batch 2.** Latest reform the SAF 2026 edition names: Gaceta of 19-12-2025, saved and spot-checked on 3 amended articles. The SAF edition is **VERIFIED** (logged direct download) |
| W2-2 2024 subsidy decrees | **Done in Batch 2.** DOF 01-05-2024 and its DOF 31-12-2024 amendment saved (archive copies) |
| W2-3 SAT `c_MotivoCancelacion` (B22) | **BLOCKED-ON-SOURCE.** Not in the saved catCFDI workbook or XSDs (S30), in RMF 2026 (S1) or in the Anexo 20 standard. The Anexo 20 guide (S30, p. 92) mentions only code "01" (Comprobante emitido con errores con relación) in one worked example. No file with that catalog appears in the archive's 249 captures of SAT's `tramitesyservicios/Paginas/documentos/` folder. Cancellation keeps refusing `MX_CFDI_CANCEL_REASON_UNAVAILABLE`, and the pinned set `sat_2026_08` is unchanged |
| W2-4 DOF RMF 2026 amendments touching rules 2.7.1.7 / 2.7.5.2 | **None found.** The 1st amendment (S1, DOF 09-07-2026) does not amend them. The 2nd–4th amendments exist in the archive only as SAT advance versions (not law). Neither the 2nd's twelfth advance version (17-09-2026) nor the 4th's second (15-10-2026) mentions either rule (checked in the text; not saved as sources) |
| W2-5 Other sources | See below |

**W2-5 detail**
- **S36, Ley del ISSSTE** (Diputados consolidated text, last reform DOF 15-01-2026; archive capture 20261004141029, digest OK; `ARCHIVE_COPY_VERIFIED`).
  - Art. 21 (p. 11): the RCV and housing-fund quotas are paid "por bimestres vencidos, a más tardar el día diecisiete de los meses de enero, marzo, mayo, julio, septiembre y noviembre de cada año".
  - So the ISSSTE law has **not** moved to monthly payment. The condition that ends the bimonthly cycle in Ley INFONAVIT's 1997 Transitorio SEXTO and in the LSS's Transitorio VIGÉSIMO SÉPTIMO is not met.
  - **D-15 is resolved by the sources:** INFONAVIT and RCV are bimonthly. The INFONAVIT due date is transcribed (TL-CAL-4).
  - **IMSS still has no calendar row.** Its non-RCV branches are monthly (LSS Art. 39) and RCV is bimonthly, but one IMSS liability carries both. New gap item **A18**: split the RCV branches into their own liability.
- **S35, CFF:** saved in W1-5 (Arts. 6, 12, 20). It now backs the D-01 rounding candidate (Art. 20) and D-16.
- **Not found (BLOCKED-ON-SOURCE):**
  - the INFONAVIT payment regulation (the fixed-amount credit basis; not in the Diputados regulations index);
  - SAT's current CFDI instructions for the 2024-decree subsidy (C6);
  - SAF's general rules for the 2026 CDMX ISN benefit (D-10);
  - SAT's CFDI cancellation-reason catalog (W2-3 above).
- **Rounding (B11):** candidates recorded in D-01; nothing chosen (a G1 decision).

---

## W3-1 — Subsidy monthly cap (gap register A15)

**ZP-PRIV:** not required.

- **Interface:** `mx_subsidy_monthly_cap_rule`. When absent, the engine blocks exactly as before (`MX_SUBSIDY_MONTHLY_CAP_RULE_MISSING`).
- **Transcribed** from S3 Art. Segundo ¶4: `CAP_AT_MONTHLY_AMOUNT` (TL-SUB-3). A short-period payment is cut to what is left of the monthly amount; the trace says `capped`.
- **Tests:** the engine cap test (left over, nothing left, under the cap, unknown rule) and the content vocabulary test. Affected files: 164 passed. `compare`: 541 checks, 0 misses.
- **Production effect:** none reachable (Mexico dormant). The national Draft pack gains one text row on the next manual seed.
- **Blind second transcription:** pending (all W3 rows together).

---

## W3-2 — Work on a rest day (gap register A15)

**ZP-PRIV:** not required.

- **Interface:** `mx_rest_day_work_multiplier` (per case, so not required for activation), a new line kind `REST_DAY_WORK` from approved hours, and the earning code `MX_REST_DAY_WORK` (it needs an approved classification, like overtime). The result trace gains `labor.rest_day`.
- **Transcribed** from LFT Arts. 73 and 75: **2** extra daily salaries per rest day worked (TL-LFT-2; a D-04 reading).
- **Tests:** the engine tests (amount, missing code, none worked) and the content test. All Mexico tests: 982 passed. `compare`: 544 checks, 0 misses.
- **Production effect:** none reachable. The engine module changes are Mexico-only.

---

## W3-3 — IMSS / INFONAVIT contribution days with absences and incapacity (gap register A15)

**ZP-PRIV:** not required.

- **Interface:** `MX_CONTRIBUTION_DAYS_RULE` (a rule object). The period carries the absence and incapacity counts; the orchestrator sets per-branch days on the segment; `imss`, `ceav` and `infonavit` read a branch's days when set and the segment's days otherwise. Absent, the engine blocks exactly as before.
- **Transcribed** from LSS Art. 31 and Ley INFONAVIT Art. 29 (TL-IMSS-4). Still blocked: 8 or more absence days (the Art. 37 procedure) and absences in a multi-segment period.
- **`compare`** now includes the rule: 549 checks, 0 misses.
- **Tests:**
  - rule tests: branch days, never negative, the three blocks;
  - period tests: resolves with fewer than 8 days, blocks at 8;
  - the old "absence blocks" tests now empty the rule themselves.
  - All Mexico tests: 985 passed.
- **Production effect:** none reachable. Mexico engine modules only.

---

## W3-4 — LISR Art. 93 exemptions for ordinary earnings (gap register A15, B17)

**ZP-PRIV:** not required.

- **Interface:** `MX_ORDINARY_EXEMPTION_RULES`, keyed by `isr_exempt_rule_key`. `classification.classify` takes optional facts; the orchestrator passes the weekly overtime and Sundays worked for the hour lines.
- **Transcribed:** the overtime rule (Art. 93 I: 50% within the legal limit, at most 5 reference wages a week) and the Sunday-premium rule (Art. 93 XIV: 1 reference wage per Sunday). Log TL-SP-4. Both wait for D-07.
- **Not transcribed:** the rest-day share of the Art. 93 I cap (no weekly dating).
- **`compare`:** 557 checks, 0 misses.
- **Tests:** 4 rule tests (overtime by week and cap, Sunday premium, the D-07 and Art. 93 I blocks, `classify` applying a named rule versus an unknown key). All Mexico tests: 989 passed.
- **Blind second transcription (W3-1 to W3-4, one agent):** agreement on every rule. It corrected one citation (Ley INFONAVIT Art. 29: the second-to-last paragraph, not the last) and added the "aviso oportuno" condition to the D-04 reading.
- **Production effect:** none reachable. Mexico engine modules only.

---

## W3-5 — Interfaces for the remaining seams, and gap A16

**ZP-PRIV:** not required.

| Seam (gap register A15) | Interface | State |
|---|---|---|
| Hourly rate | `mx_hourly_rate_rule` + `MX_JORNADA_DAILY_HOURS`; the engine derives the rate (`labor.hourly_rate`). The run service no longer refuses before the engine and passes the workday type, now bound into the input hash | Working-day lengths **transcribed** (LFT Art. 61); the rule is **D-17**, so overtime still blocks |
| INFONAVIT notice for part of a period | `mx_infonavit_partial_period_rule` (`PRORATE_BY_DAYS_IN_FORCE`: days in force per segment; overlapping notices block) | **BLOCKED-ON-SOURCE** (INFONAVIT payment regulation) |
| FIXED SBC items | `MX_SBC_FIXED_INTEGRATION_RULE.daily_amount(line, facts)` | **D-18** |
| Fixed days at termination | `MX_FIXED_DAYS_TERMINATION_RULE.days_paid(…)` | **D-19** |
| **A16** no withholding at the minimum wage | `mx_min_wage_no_withholding_rule` | **Transcribed** (LISR Art. 96 ¶1, TL-ISR-3) |

- With each interface empty, the engine blocks exactly as before (each existing block test still passes).
- **`compare`:** 561 checks, 0 misses.
- **Tests:** hourly-rate rule (D-17 block, three working-day lengths, unsupported type, supplied rate); INFONAVIT proration (block, 20 of 30 days, overlap); the A16 orchestrator test (no ISR at exactly the minimum wage with the rule; ISR without the rule or one peso above); the content pins.
- All Mexico tests: 991 passed on the full run; its 2 failures (a parameter label over the length limit, and the hourly-rate block order) were fixed and pass (112 passed in the affected files).
- **Production effect:** none reachable. Mexico modules only (the run service's input hash gains the workday type).

**W3 summary:** every A15 seam has a content interface; 6 are transcribed or partly transcribed, 4 wait for D-17, D-18, D-19 or a source. A16 is done.

---

## End of W3 — full backend suite

Run 2026-10-26 16:55–17:20 on `84847ab`, in five sequential chunks on scratch SQLite, alone.

| Chunk | Result |
|---|---|
| 0 | 975 passed, 16 skipped, **4 failed**: the 3 known local-only route-registry tests, and `test_communications_dispatch.py::test_deactivate_organization_response_precedes_email_send`. That test is the **intermittent** one recorded in Batch 2: run alone afterwards it passed 3 of 3, and no Mexico change touches communications |
| 1 | 2,488 passed, 2 skipped, 2 xfailed, **1 failed**: the known local-only Hong Kong docs test |
| 2 | 1,270 passed, 32 skipped |
| 3 | 1,151 passed, 67 skipped |
| 4 | 1,621 passed, 3 skipped |

**Total: 7,505 passed, 120 skipped, 2 xfailed.** No other jurisdiction's behaviour changed.
