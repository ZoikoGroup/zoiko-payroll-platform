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

