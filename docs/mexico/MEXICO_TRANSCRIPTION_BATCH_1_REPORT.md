# Mexico (MX) — Transcription Batch 1 Report, with the S11 / S22 / S1 source decisions and the `hash` fix

Requested 2026-10-26 after the Step 1 and Step 2 review. Contents: the S11 and S22 decisions, the source tool's `hash` fix, S1 (RMF 2026), then transcription Batch 1 (moved ahead of Phase 12a, since it is the critical path): ISR tariffs, UMA, the employment subsidy and the pay-frequency map.

> **Rugvedh (ZP-PRIV) review:** not required by rule 7. There is no change to authz, redaction, RLS, migrations or cross-tenant data.

**Base.**
- `nikhil` = `a0da835`. Step 1 (11d) and Step 2 (Batch A manifest) are staged, not committed.
- Production should be at `b9f3d5a1c7e2`. Mexico is dormant: registry PLANNED, flag off.

**No migration, no new route, no frontend change.**

## 1. Result

| Item | Result |
|---|---|
| S11 | Saved from the Cámara de Diputados copy of the DOF 16-12-2020 decree: `ARCHIVE_COPY_VERIFIED`, noted as a copy of the DOF decree |
| S22 | **Stopped at check 2.** The SAF "CÓDIGO FISCAL 2026" is saved as a **CANDIDATE** (`UNVERIFIED`, not usable). Check 1 passed: Art. 158 reads 4%. Check 2, the Gaceta decree, could not be done (§3) |
| `hash` fix | It never overwrites an existing row. Proven on the real manifest: all 23 earlier rows are byte-identical after the S11 / S1 / S22 rows were added (§4) |
| S1 | RMF 2026 (DOF 28-12-2025) and its first amending resolution (DOF 09-07-2026): `ARCHIVE_COPY_VERIFIED`. Rule 2.7.1.7 is on PDF p. 99, rule 2.7.5.2 on PDF p. 162; the amendment touches neither (§5) |
| Batch 1 | 55 ISR brackets, 6 UMA rows, 4 subsidy rows and 4 pay-frequency codes. Every row is `[PENDING G1]` and cites `CODE/file` (§6) |
| Blind second transcription | **0 differences** (ISR 55/55, UMA, subsidy, catalog) |
| Machine extraction | `compare`: **65/65 rows found, 0 misses** |
| Arithmetic | DAILY and MONTHLY close exactly. The 7-, 10- and 15-day tables are B.I × days, with 20 documented source-wins exceptions (§6.1) |
| Spec versus source | **No difference** in Batch 1 |
| Full suite | §8 |

## 2. S11 — the 2020 pension-reform decree

- **File:** `S11_DIP_LSS_ref25_16dic20.pdf`, from `https://www.diputados.gob.mx/LeyesBiblio/ref/lss/LSS_ref25_16dic20.pdf`.
- **Capture:** Internet Archive capture 20230203060107. Its SHA-1 digest `32YDTTBZ…` matches the downloaded bytes.
- **Content:** 9 pages: the DOF 16-12-2020 decree reforming the LSS and the Ley de los SAR, as published in the DOF (pp. 26 ff).
- **Note:** the spec's congreso.gob.mx URL was never archived.

## 3. S22 — CANDIDATE only; stopped at check 2

| Check | Result |
|---|---|
| The candidate | SAF "CÓDIGO FISCAL 2026", downloaded directly (HTTP 200, 58,814,901 bytes, SHA-256 `5d989b7e…`). 820 pages, PDF created 2026-02-18, server Last-Modified 2026-09-01. **It states no reform date** |
| 1. Art. 158 reads 4% | **PASS.** PDF p. 91: "El Impuesto sobre Nóminas se determinará, aplicando la tasa del 4% sobre el monto total de las erogaciones…" (read for this check only; no ISN value is transcribed) |
| 2. Gaceta decree for 2026, plus a spot-check of 2–3 articles | **NOT DONE: the decree was not found.** See below |

**Where I looked for the decree:**
- **The Consejería Jurídica site** (the Gaceta Oficial's publisher) does not answer from this network.
- **The Internet Archive:** nothing on that domain was captured between 22 and 30 December 2025, apart from the Gaceta index page. I fetched and checked all six Gaceta PDFs captured from 30 Dec 2025 to 29 Jan 2026. Each matches its archive digest; none carries the Fiscal Code decree (they are the issues of 5 Dec 2025, 14 and 28 Jan 2026, and three older ones).
- **SAF's "Proyecto de Paquete Económico" page** links only `INICIATIVA_CODIGO_FISCAL_2026.pdf`. That is the government's proposal, not the decree Congress passed. I did not use it.
- **The Consejería consolidated text** (`CODIGO_FISCAL_DE_LA_CDMX_5.pdf`, capture 2026-10-17) still states "última reforma… 27 de diciembre de 2022".

**State:** S22 stays `WRONG_VERSION` (the old file). The SAF file is a second S22 row, `UNVERIFIED`, with "CANDIDATE" in its note. Neither is usable by the seed, and no ISN value is transcribed.

**Decision needed:** S22 can become the 2026 source once the Gaceta decree is saved. That needs someone who can reach data.consejeria.cdmx.gob.mx (the late-December 2025 Gaceta issues), or a copy of the decree.

## 4. The `hash` fix (`verify_mexico_sources.py`)

**New behaviour:**
- An existing manifest row is **never overwritten**; only its blank fields are filled.
- A saved file whose hash no longer matches its row makes the whole command **refuse, writing nothing**. Before, it silently re-hashed the file and reset the row to UNVERIFIED.
- New files are added as UNVERIFIED, as before.

**Tests:**
- `test_hash_never_overwrites_an_existing_row`: curated fields survive a re-hash, a blank field is filled and a new file is added.
- `test_hash_adds_new_files_unverified_and_detects_changes`: now expects the refusal, with the manifest byte-identical.
- **On the real manifest:** running `hash` with no new files leaves it byte-identical. Adding 4 files left all 23 earlier rows unchanged.

**Two related tool changes:**
- **`compare`** (the machine extraction) now accepts `CODE/file` cites and any file usable for a Draft pack (VERIFIED with its log entry, or an archive copy).
- **`numbers_in`** also reads amounts whose thousands are separated by a space, as INEGI prints them ("3 566.22"). These tokens are added alongside the existing ones.

## 5. S1 — RMF 2026

| File | Source | State |
|---|---|---|
| `S1_SAT_RMF2026_DOF28122025.pdf` | Capture 20260108075315 of `…/documentos2026/rmf/rmf/RMF_2026-DOF-28122025.pdf`, digest OK. 666 pages, DOF 28-12-2025 | Rule **2.7.1.7** (minimum data on a printed CFDI): PDF p. 99. Rule **2.7.5.2** (payroll CFDI printed representation): PDF p. 162. Rule 3.12.2 (used in §6.4): PDF p. 425 |
| `S1_SAT_1aRM_RMF2026.pdf` | Capture 20260929191958 of `…/rmf/rmf/1aRM_RMF2026.pdf`, digest OK. 17 pages, DOF 09-07-2026 | Mentions neither 2.7.1.7 nor 2.7.5.2 |

**Open:** the archive also holds SAT **advance versions** ("anticipadas") of the 2nd–4th amending resolutions, the latest dated 15-10-2026. They aren't DOF publications, so I didn't save them. Before 12c, check whether a published amendment changes 2.7.1.7 or 2.7.5.2.

## 6. Transcription Batch 1

Everything is in `mexico_content.py`; the log is `MEXICO_PHASE_1_TRANSCRIPTION_LOG.md`. All four tables rest on archive copies, so they can feed a **Draft** pack only: the `sources_verified` gate refuses approval and activation until each file is VERIFIED.

### 6.1 ISR tariffs: S2, Anexo 8 B.I–B.V (B1)

- **Rows:** 5 periods × 11 brackets, effective 2026-01-01 to 2026-12-31: DAILY = B.I (p. 4), WEEKLY_7 = B.II, DECENAL_10 = B.III, QUINCENAL_15 = B.IV, MONTHLY = B.V (p. 6).
- **Controls:** blind 0 differences, machine extraction 55/55 on one line, spec §4 identical.
- **Source-wins finding:** S2 prints the 7-, 10- and 15-day tables as **B.I × days**; every upper limit and quota matches exactly. So 20 of their quotas don't close under the previous-bracket formula, by 0.02–0.09.
  - The values stay as printed.
  - The 20 brackets are listed in `MX_ISR_ARITHMETIC_EXCEPTIONS` (log TL-ISR-2).
  - Two new tests assert the "× days" relationship exactly, and that the exceptions are exactly the failing brackets.

### 6.2 UMA: S7 (2025) and S6 (2026), dated rows (B2)

| Key | 2025-02-01 → 2026-01-31 (S7) | From 2026-02-01 (S6) |
|---|---|---|
| `mx_uma_daily` | 113.14 | 117.31 |
| `mx_uma_monthly` | 3439.46 | 3566.22 |
| `mx_uma_annual` | 41273.52 | 42794.64 |

The 2025 rows end on 2026-01-31 because S6 states the 2026 values apply from 1 February 2026.

### 6.3 Employment subsidy: S3 (B3)

| Key | Value | Window | Source text |
|---|---|---|---|
| `mx_subsidy_rate_pct` | 15.59 | 2026-01-01 → 2026-01-31 | Transitorio SEGUNDO |
| `mx_subsidy_rate_pct` | 15.02 | from 2026-02-01 | Art. Segundo ¶1 as reformed (also ¶¶3–5) |
| `mx_subsidy_income_ceiling_monthly` | 11492.66 | from 2026-01-01 | Art. Segundo ¶1 |
| `mx_subsidy_period_days_divisor` | 30.4 | from 2026-01-01 | Art. Segundo ¶3 |

**The remainder rule is not in S3.** S3 states no rule for a subsidy larger than the ISR, so `mx_subsidy_remainder_rule` stays empty and a case that needs it blocks. The blind transcriber found the same. The rule is expected in the 1 May 2024 decree or its 31-12-2024 modification (neither is saved), or in SAT's CFDI subsidy instructions (gap register C6).

### 6.4 Pay frequency → Art. 96 period: S28 c_PeriodicidadPago v1.1 + S2 (B13)

- **Mapped:** 02 Semanal → WEEKLY_7, 04 Quincenal → QUINCENAL_15, 05 Mensual → MONTHLY, 10 Decenal → DECENAL_10. Each code cites the catalog row and the S2 table whose heading names the period (`MX_PAY_FREQUENCY_ISR_PERIOD_SOURCES`).
- **Decision needed (G1), 01 Diario:** it is left unmapped, so a daily-paid employee blocks. B.I's heading is "en función de la cantidad de trabajo realizado y no de días laborados… calculada en días". RMF rule 3.12.2 says only to apply "las tarifas correspondientes del Anexo 8". Neither source says a daily pay frequency uses B.I, so I did not infer it.
- **Never mapped:** 03 Catorcenal, 06 Bimestral, 07 Unidad obra, 08 Comisión, 09 Precio alzado and 99 Otra. S2 has no Art. 96 table for them.

### 6.5 Spec versus source

No difference. The spec's monthly ISR table, UMA rows and subsidy rows (ceiling, 15.59% / 15.02%, ÷ 30.4) match their sources. Per the new rule, a future difference won't stop the work: the source wins, and the difference is listed in the log and the report. The spec cross-check test's message now says this.

## 7. Tests changed for real content

Until Batch 1, several tests relied on the real content tables being empty. They now say what they mean:

| Test | Change |
|---|---|
| `test_mexico_seed.py` | An autouse fixture empties the real ISR and scalar tables: these tests exercise the seed on SYNTHETIC rows only |
| `test_mexico_activation_gates::test_the_real_seeded_packs_are_refused_today` | Seeds the **real** Batch 1 content with the real manifest: 55 ISR slabs and 10 rates. Asserts each check: national has evidence met; content, sources_verified (archive copies are "not VERIFIED"), G1 and golden unmet. CDMX: all unmet |
| `test_mexico_approval` | Real packs are seeded from the real manifest. The "empty content" test empties the tables explicitly. **New:** `test_a_qa_pack_with_batch1_content_is_still_refused` |
| `test_mexico_isn_registrations`, `test_mexico_labor_policy`, `test_mexico_scaffolding` | Seed today's real packs with the real manifest. The skeleton test now pins the Batch 1 keys and checks that every other table is still empty |
| `test_mexico_engine_content` | Asserts that no Phase 5 rule key (rounding, SBC floor, remainder, INFONAVIT bases, overtime) has a row yet |
| `test_mexico_router` fixture | Synthetic UMA rows only (the ISR table is emptied for these route tests) |
| `test_mexico_content` | Provenance: cites resolve in the tracked manifest. The hash check skips only where the source binaries aren't checked out, as in CI (they live outside git). New: the ×days, exact-exceptions and pay-frequency tests |
| `test_mexico_source_tool` | The `compare` tests run on SYNTHETIC content only. `numbers_in` handles space thousands |

## 8. Full suite

Run 2026-10-26 on SQLite, in five sequential chunks, alone.

| Chunk | Result |
|---|---|
| 0 | 867 passed, 15 skipped, **3 failed**: the known local-only `tests/privacy/test_route_registry.py` tests (your uncommitted `/health` routes in `backend/app/main.py`) |
| 1 | 2283 passed, 1 skipped, 2 xfailed, **1 failed**: the known local-only HK docs test (`test_hong_kong_configuration.py`) |
| 2 | 1490 passed, 32 skipped, 0 failed |
| 3 | 1735 passed, 69 skipped, 0 failed |
| 4 | 1059 passed, 6 skipped, 0 failed |

**Total: 7434 passed, 123 skipped, 2 xfailed. The only failures are the 4 known local-only ones.** Every Mexico test passes in the suite.

## 9. Production effect

| Area | Effect when merged |
|---|---|
| Database / Alembic | **None.** No migration |
| Mexico in production | Stays dormant. The engine reads pack rows from the database, and **no deploy runs the seed**, so no Batch 1 row reaches a production pack unless someone runs `seed_mexico_canonical_packs.py` by hand. If they do, the rows land in the **Draft** pack only, and approval and activation stay refused (archive copies are not VERIFIED; content still lacks the required rules) |
| Super Admin readiness view | The content check now compares a pack with the 65 Batch 1 rows. Its detail text changes from "awaiting transcription" to a content mismatch for a pack seeded before Batch 1 |
| Pay-frequency map | `mexico_run_service.payment_period` now maps 4 codes instead of none. Mexico runs stay blocked by dormancy and by the remaining content (rounding and SBC floor rules, IMSS, and others) |
| Source tool | `hash` never overwrites; `compare` checks archive copies too |
| Other jurisdictions | **None.** Every edit is in Mexico-only modules, scripts, tests and docs. The pinned NL / IE / SE / HK / SG / DE tests pass (§8) |
| Identifiers | Not touched |

## 10. Staged

- **Code:** `engine/countries/mexico_content.py` and `scripts/verify_mexico_sources.py`.
- **Tests:** `test_mexico_content.py`, `test_mexico_source_tool.py`, `test_mexico_seed.py`, `test_mexico_activation_gates.py`, `test_mexico_approval.py`, `test_mexico_isn_registrations.py`, `test_mexico_labor_policy.py`, `test_mexico_scaffolding.py`, `test_mexico_engine_content.py`, `test_mexico_router.py`.
- **Docs:** `SOURCES_MANIFEST.csv` (+4 rows), `MEXICO_PHASE_1_TRANSCRIPTION_LOG.md` (new), a "Progress" section added to `MEXICO_COMPLETION_GAP_REGISTER.md`, this report.
- **Not staged:** the source binaries (untracked, as before) and your own uncommitted files. Nothing is committed or pushed.

**Next:** Step 4 (Phase 12a), after your review.
