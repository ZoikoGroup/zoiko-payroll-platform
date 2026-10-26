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
