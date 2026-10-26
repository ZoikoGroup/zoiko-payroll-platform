# Mexico (MX) — Transcription Log

One section per transcribed table. Each records the source file and its SHA-256, the page or article, the engineering controls run, and any discrepancy found. The controls follow the Phase 1 plan §3 and §6:

- **Blind second transcription:** a separate agent read only the saved source files, without seeing these values. Its output was machine-diffed against the content module.
- **Machine extraction:** `verify_mexico_sources.py compare` finds every transcribed number in the cited file's text.
- **Arithmetic tests:** in `test_mexico_content.py`.

The rules:
- **Source wins.** The spec's own figures are not a source. Where a source differs from the spec, the source is transcribed and the difference is listed here.
- **The blind transcription is an engineering control. It does not count as G1.** Every row stays `[PENDING G1]` until a human G1 reviewer signs the last column.
- **Citations.** Every row cites its file as `CODE/file`.

All Batch 1 sources are `ARCHIVE_COPY_VERIFIED` (Internet Archive captures checked against the archive's digest). They may feed the **Draft** pack only. Activation and G1 need each file `VERIFIED` through a logged direct download (`VERIFICATION_LOG.csv`).

---

## Batch 1 — 2026-10-26

### TL-ISR-1 · ISR Art. 96 retention tariffs (gap register B1)

| | |
|---|---|
| Source | `S2/S2_SAT_Anexo8_RMF2026.pdf`, SHA-256 `69ebaf8a78a3bde5d631ad2a994e81ec6d07e2d4e39085c8c948d138f782c1f4` (Anexo 8 RMF 2026, DOF 28-12-2025) |
| Location | Section B "Tarifas aplicables a retenciones", tables I–V, each "correspondiente a 2026" / "durante 2026" and citing Arts. 96 LISR and 175 RLISR and rule 3.12.2. B.I (calculated in days) is on PDF p. 4; B.II (7 days) pp. 4–5; B.III (10 days) p. 5; B.IV (15 days) pp. 5–6; B.V (monthly) p. 6 |
| Rows | 5 periods × 11 brackets = 55 `IsrBracket` rows, effective 2026-01-01 to 2026-12-31 |
| Content | `mexico_content.MX_ISR_TARIFFS` (periods DAILY = B.I, WEEKLY_7 = B.II, DECENAL_10 = B.III, QUINCENAL_15 = B.IV, MONTHLY = B.V) |
| Blind second transcription | **0 differences** in 55 rows (lower, upper, quota, rate), and the same pages |
| Machine extraction | `compare`: each bracket's four numbers found **on one line** of the S2 text: 55/55 |
| Arithmetic | DAILY and MONTHLY close under the previous-bracket quota formula with no exceptions; every table starts at 0.01, has no gaps, rising rates and an open top bracket. For the 7-, 10- and 15-day tables, see TL-ISR-2 |
| Spec cross-check | Spec §4 (monthly table) equals B.V exactly: **no difference** |
| Human G1 reviewer (name / date / verdict) | |

### TL-ISR-2 · Source-wins exceptions: the 7-, 10- and 15-day tables

**What S2 prints:** in B.II, B.III and B.IV, every upper limit and every fixed quota is exactly the B.I (daily) value × 7, 10 and 15 days. For example, bracket 2's quota is 0.53 × 7 = 3.71. The rates are the same as B.I. Lower limits are the previous upper limit + 0.01.

**Why exceptions are needed:** because the quotas are scaled, not built up bracket by bracket, 20 quotas don't close under the previous-bracket formula. The gaps are between 0.02 and 0.09 (for example, 7-day bracket 2: printed 3.71, formula 3.73).

**What was done:** the values are kept as printed (source wins). The 20 brackets are listed in `MX_ISR_ARITHMETIC_EXCEPTIONS`, each pointing to this entry:
- WEEKLY_7: 2, 3, 7, 9, 11
- DECENAL_10: 2, 3, 4, 7, 8, 9, 11
- QUINCENAL_15: 2, 3, 4, 5, 7, 8, 9, 11

**Replacement checks:**
- `test_the_7_10_and_15_day_tariffs_are_the_daily_tariff_times_days` asserts the "B.I × days" relationship exactly, for every upper limit and quota.
- `test_documented_isr_exceptions_are_exactly_the_failing_brackets` proves the list matches the failing brackets exactly, and that every failure is a quota failure.

| Human G1 reviewer (name / date / verdict) | |
|---|---|

### TL-UMA-1 · UMA 2025 and 2026 (gap register B2)

| | |
|---|---|
| Sources | `S7/S7_INEGI_UMA_2025.pdf`, SHA-256 `eb88864cb07d7cbea007d48c3aec3d05ef07eb70376ab4d8208c967d82d8eaf4` (INEGI bulletin of 9 Jan 2025). `S6/S6_INEGI_UMA_2026.pdf`, SHA-256 `9c9c4ff3da9b34852d5e3b8165c50c346ff3ef7ba74737489f6d1f544c353e1c` (INEGI bulletin of 8 Jan 2026) |
| Location | p. 1 of each, Cuadro 1 (daily, monthly, annual); each bulletin states its values are in force "a partir del 1 de febrero" of its year |
| Rows | 6 `ScalarRow`: `mx_uma_daily` / `_monthly` / `_annual`. 2025 values effective 2025-02-01 to 2026-01-31 (the end date comes from S6's 1 Feb 2026 start); 2026 values from 2026-02-01 |
| Blind second transcription | **0 differences** (values and in-force dates) |
| Machine extraction | `compare`: 6/6 found. INEGI prints thousands with a space ("3 566.22"); `numbers_in` now reads that form too |
| Spec cross-check | "UMA — January" and "UMA — from 1 Feb" rows: **no difference** |
| Human G1 reviewer (name / date / verdict) | |

### TL-SUB-1 · Employment subsidy (gap register B3)

| | |
|---|---|
| Source | `S3/S3_DOF_Decreto_subsidio_empleo_31122025.html`, SHA-256 `14c0b1d7448739ca80b210372ffdb3fb35f6b57dcca930be22f609492bb96cef` (DOF 31-12-2025, "DECRETO por el que se modifica el diverso que otorga el subsidio para el empleo"; in force 1 Jan 2026 under Transitorio PRIMERO) |
| Location | The Artículo Único reforms Artículo Segundo ¶¶ 1, 3, 4 and 5 of the decree of 1 May 2024 (as modified 31-12-2024). ¶1: the ceiling and "valor mensual de la UMA por 15.02%". ¶3: ÷ 30.4 × days for periods under a month. ¶4: the cap for periods under a month. ¶5: payments covering two or more months. Transitorio SEGUNDO: January 2026 uses 15.59% in place of 15.02% |
| Rows | `mx_subsidy_rate_pct`: 15.59 for 2026-01-01 to 2026-01-31, then 15.02 from 2026-02-01. `mx_subsidy_income_ceiling_monthly`: 11492.66 from 2026-01-01. `mx_subsidy_period_days_divisor`: 30.4 from 2026-01-01 |
| Not transcribed | **`mx_subsidy_remainder_rule`**: S3 states no rule for a subsidy larger than the ISR. It says only that the subsidy "se aplicará contra el impuesto sobre la renta… en términos del artículo 96". The unreformed ¶2 appears as "…". This key stays empty, so a case that needs it blocks |
| Blind second transcription | Rate, ceiling, divisor, January substitution and entry into force: **no differences**. The blind transcriber also found no remainder rule |
| Machine extraction | `compare`: 4/4 found |
| Note on the source | The DOF HTML carries DOF's own warning that the HTML conversion may mis-render text and that the PDF edition is the reference. A truncated display line ("…por 15.") was checked against the raw HTML, which reads "por 15.02%. Dicho subsidio…" |
| Spec cross-check | Ceiling 11,492.66; January 15.59% of the 2025 monthly UMA; 15.02% from February; ÷ 30.4 × days: **no difference** |
| Human G1 reviewer (name / date / verdict) | |

### TL-PER-1 · Pay frequency → Art. 96 period (gap register B13)

| | |
|---|---|
| Sources | `S28/S28_SAT_catNomina.xls`, SHA-256 `6e61a49d7b966dbcf730ef46a5fde1cb3b505114b69b4ecbf8fa2ba5d882a3c3`, sheet `c_PeriodicidadPago` (version 1.1, revision 0, in force from 2017-01-01; 11 codes). `S2/S2_SAT_Anexo8_RMF2026.pdf` B.I–B.V headings (above) |
| Mapped | 02 Semanal → WEEKLY_7 (B.II "periodo de 7 días"); 04 Quincenal → QUINCENAL_15 (B.IV "15 días"); 05 Mensual → MONTHLY (B.V "pagos provisionales mensuales"); 10 Decenal → DECENAL_10 (B.III "10 días"). Citations in `MX_PAY_FREQUENCY_ISR_PERIOD_SOURCES` |
| Not mapped (they block) | **01 Diario: a G1 decision.** B.I is headed "en función de la cantidad de trabajo realizado y no de días laborados… calculada en días", and RMF rule 3.12.2 (S1, PDF p. 425) says only to apply "las tarifas correspondientes del Anexo 8". Neither says a daily pay frequency uses B.I. The other codes have no Art. 96 table in S2: 03 Catorcenal, 06 Bimestral, 07 Unidad obra, 08 Comisión, 09 Precio alzado and 99 Otra Periodicidad |
| Blind second transcription | The 11 catalog codes and descriptions: **no differences** |
| Human G1 reviewer (name / date / verdict) | |

### Spec versus source — Batch 1

No difference was found. The monthly ISR table (§4), the UMA rows and the subsidy rows of the spec all match their sources.

---

## Batch 2 — 2026-10-26

**Controls for this batch:**
- **Blind second transcription:** a separate agent read only S10, S11, S27, S9, S26 and S18.
- **Machine extraction:** `compare` now also reads numbers written in Spanish words, which is how the LSS, LFT and Ley del INFONAVIT print most rates. It checks derived values through their printed components, and municipality names in the S9 text.
- **Result:** 343 rows checked, 0 misses. 56 CEAV cells sit in an image table and are covered as described in TL-CEAV-1.

### TL-IMSS-1 · IMSS branch rates printed in S10 (gap register B4)

| | |
|---|---|
| Source | `S10/S10_IMSS_LSS.pdf`, SHA-256 `875efb2c8e6562f4236a343c27f3199dc04732890e484e95086f69da05aa632c` (LSS, consolidated text, last reform DOF 15-01-2026) |
| Rows (printed in words) | Pensioner medical (Art. 25 ¶2, p. 10): 1.05 employer / 0.375 worker. I&V (Art. 147, p. 45): 1.75 / 0.625. Guarderías (Art. 211, p. 62): 1. Retiro (Art. 168 I, p. 51): 2. CEAV worker (Art. 168 II b), p. 51): 1.125. SBC ceiling multiple (Art. 28, p. 11): 25. E&M excess threshold (Art. 106 II, p. 35): 3. Work-risk premium (Art. 74 ¶2, p. 26): minimum 0.5, maximum 15 |
| Blind second transcription | **0 differences** |
| Machine extraction | All found (in words) |
| Spec cross-check | §8 matches |
| Human G1 reviewer (name / date / verdict) | |

### TL-IMSS-2 · DERIVED IMSS rates (no source prints the 2026 figure)

**The base rates.** Art. 106 prints only the original rates:
- I: fixed quota 13.9% of the daily minimum wage.
- II: above 3× the minimum wage, 6% employer and 2% worker.

**The steps.** The 1995 LSS Transitorio DECIMO NOVENO (PDF p. 110) changes them every 1 July from 1998 to 2007, which is 10 steps: +0.65 points for I, −0.49 points (employer) and −0.16 points (worker) for II.

**The cash-benefit split.** Art. 107 prints a 1% quota split 70% employer and 25% worker.

**The values transcribed** (`MX_DERIVED_VALUES`):

| Key | Calculation | Value |
|---|---|---|
| Fixed quota (employer) | 13.9 + 10 × 0.65 | **20.40** |
| Excess (employer) | 6 − 10 × 0.49 | **1.10** |
| Excess (worker) | 2 − 10 × 0.16 | **0.40** |
| Cash benefits (employer) | 1 × 70% | **0.70** |
| Cash benefits (worker) | 1 × 25% | **0.25** |

**Checks:**
- **Machine extraction** finds every component.
- **`test_derived_values_are_rebuilt_from_their_printed_components`** recomputes each value from its components.
- **The blind transcriber** recorded the same base rates and steps.
- **Spec:** §8 states the same results.

**For G1:** confirm that the step schedule is fully applied (10 steps, the last on 1 July 2007).

| Human G1 reviewer (name / date / verdict) | |
|---|---|

### TL-IMSS-3 · "Salario mínimo" read as UMA (open: source to save)

**What the LSS says:** Art. 28 (ceiling) and Art. 106 (fixed quota, excess threshold) still say "salario mínimo general… para el Distrito Federal".

**The basis for reading it as UMA:** the constitutional de-indexation decree, DOF 27-01-2016, Transitorio Tercero: "todas las menciones al salario mínimo como unidad de cuenta, índice, base, medida o referencia… en las leyes federales… se entenderán referidas a la Unidad de Medida y Actualización".

**Status of that decree:**
- Found as the Diputados copy `ref/dof/CPEUM_ref_226_27ene16.pdf`, Internet Archive capture 20160222060026, digest OK, SHA-256 `16c38e9fa2fdf8185413051f9f3e9573337cfd5705808a5f5718c1fec8d1c76e`.
- **Not in the register.** It's proposed as a new source, pending your decision.

**Until then:** the rows hold the multiples (25, 3), and their UMA reading rests on that decree.

| Human G1 reviewer (name / date / verdict) | |
|---|---|

### TL-CEAV-1 · CEAV employer schedule 2023–2030 (gap register B5)

| | |
|---|---|
| Source | `S11/S11_DIP_LSS_ref25_16dic20.pdf`, SHA-256 `1078f08acbda8435d830c36c1699c8feb97f670dba9394419673c618d8027e92` (DOF 16-12-2020 decree, Transitorio Segundo) |
| The table | **A scanned image** on PDF p. 7 (DOF p. 32) with no text layer. It was read by eye, independently, in both transcriptions |
| Rows | 8 bands × 8 years = 64 `CeavBand`; only 2026 is seeded. 2026: 3.150, 3.676, 4.851, 5.556, 6.026, 6.361, 6.613, 7.513 |
| Blind second transcription | **0 value differences in 64 cells.** One representational difference: band 1 is printed "1.0 SM" as a single point. I store its upper bound as 1.0 SM (the blind transcription left it empty), because an empty upper bound would make the engine treat band 1 as open-ended. This lowest band is already [PENDING G2] |
| Machine checks | The 2030 column equals S10 Art. 168 II a), the final schedule in the text layer: 8/8 by `compare`, and again by `test_ceav_2030_column_equals_the_lss_art_168_text_table`. Each band rises in near-equal annual steps (spread ≤ 0.002): `test_ceav_schedule_shape_and_steps` |
| Spec cross-check | §9's 2026 rates match |
| Human G1 reviewer (name / date / verdict) | |

### TL-INF-1 · INFONAVIT employer rate (gap register B9)

`S27/S27_DIP_LIFNVT.pdf`, SHA-256 `9ee6e5ef336dee5700726bd3c570d24f91fc458136e298ae2e3806bd12217912`. Art. 29 II (PDF p. 15): "aportaciones del cinco por ciento sobre el salario de los trabajadores", so 5.
- **Blind:** same.
- **Compare:** found.
- **Spec:** same.
- **Not transcribed:** the INFONAVIT credit bases. They aren't in Art. 29.

| Human G1 reviewer (name / date / verdict) | |
|---|---|

### TL-MW-1 · Minimum wages and ZLFN municipalities (gap register B6)

| | |
|---|---|
| Source | `S9/S9_DOF_Resolucion_salarios_minimos_2026.html`, SHA-256 `a3f6f184088073987be637e60c9f87f06630954f6237bc22732f03409f6a3b49` (DOF 09-12-2025 CONASAMI resolution) |
| Rows | Resolutivo TERCERO: GENERAL 315.04 and ZLFN 440.87, from 1 Jan 2026. Resolutivo OCTAVO: 61 professions × 2 zones = 122 rows, codes `PROF_01`–`PROF_61`. Resolutivo PRIMERO: 45 ZLFN municipalities in BCN 7, SON 11, CHH 8, COA 8, NLE 1, TAM 10. "Guerrero" appears twice, once in Coahuila and once in Tamaulipas |
| Resolutivo SEXTO | If a ZLFN professional amount were below its general-zone amount, the general-zone amount would apply in both. **None is** (tested) |
| Blind second transcription | **0 differences** in the 61 professions (name and both amounts) and the 45 municipalities |
| Machine extraction | Every amount and municipality name found |
| Spec cross-check | 315.04 and 440.87 match |
| Human G1 reviewer (name / date / verdict) | |

### TL-LFT-1 · Benefit floors (gap register B8)

`S26/S26_DIP_LFT.pdf`, SHA-256 `12f09393a1951a91c3f57f579bf611b034edf1a5f78cdbfb828e23ff3a9acbf7` (LFT, last reform DOF 14-05-2026):
- **Aguinaldo:** 15 days (Art. 87).
- **Vacation premium:** 25% (Art. 80).
- **Sunday premium:** 25% (Art. 71 ¶2, reformed DOF 01-05-2026 with the same 25%).

All three are written in words and all were found. Blind and spec agree.

| Human G1 reviewer (name / date / verdict) | |
|---|---|

### TL-VAC-1 · DERIVED vacation schedule (gap register B8)

**What the law says:** Art. 76 (PDF p. 24, reformed DOF 27-12-2022) gives no table, only the wording: "no podrá ser inferior a doce días laborables, y que aumentará en dos días laborables, hasta llegar a veinte, por cada año subsecuente… A partir del sexto año… aumentará en dos días por cada cinco de servicios".

**What was transcribed:**
- **Rows built from that wording:** year 1: 12, year 2: 14, year 3: 16, year 4: 18, year 5: 20, years 6–10: 22, 11–15: 24, and so on, ending with years 46–50: 38 (14 rows). Service beyond 50 years finds no row and blocks.
- **Checks:** `compare` finds the rule's numbers (12, 2, 20, 5), and `test_vacation_rows_follow_the_art_76_wording` rebuilds every row from them.
- **Blind:** recorded the same wording.
- **Spec:** its table (12/14/16/18/20, then +2 per 5-year band) matches.

**For G1:** confirm the "+2 per five years" bands start at year 6.

| Human G1 reviewer (name / date / verdict) | |
|---|---|

### TL-WW-1 · Working week and overtime phase-in (gap register B7)

**Source:** `S18/S18_DOF_Decreto_LFT_jornada_01052026.html`, SHA-256 `681d34ae8bbac0b9eed103dc920513fb45f3776c233909c71043e280995e3747` (DOF 01-05-2026, in force 1 May 2026).

**The transitory articles** (each from 1 January of the year):
- **Segundo (ordinary week):** 2026: 48, 2027: 46, 2028: 44, 2029: 42, 2030: 40.
- **Cuarto (overtime hours):** 2026: 9, 2027: 9, 2028: 10, 2029: 11, 2030: 12.
- **Rows:** 5 `WorkweekRow`, plus dated `mx_overtime_double_weekly_max_hours` rows. A test checks the two agree.

**Cross-check against S26 (consolidated LFT):**
- The body already shows the end state: Art. 59 says 40 hours and Art. 66 says 12 hours a week.
- It reproduces the decree's transitory articles (PDF p. 454), identical to S18.
- So there's no conflict: the transitory articles govern 2026–2029.

**Every difference from the spec's 48/46/44/42/40 table:**
1. **The hours themselves: no difference.**
2. **Overtime phase-in:** the spec gives only "9 weekly overtime hours" for 2026, and S18 agrees. The spec doesn't list 9/10/11/12 for 2027–2030; S18 does, and those values are transcribed.
3. **Timing in 2026:** the spec says 48 hours "remains operative for 2026". S18 states 48 for 2026 from 1 January, although the decree itself only entered into force on 1 May 2026. For January–April 2026, the row cites a transitory article published later.
4. **Second overtime tier:** the spec doesn't mention it. S18 Art. 68 caps hours beyond the Art. 66 limit at 4 a week. That cap is recorded in `overtime_rules` but isn't enforced by the engine (which pays all remaining hours at the second tier).

| Human G1 reviewer (name / date / verdict) | |
|---|---|

### TL-WW-2 · DERIVED overtime multipliers

**What S18 says:** Art. 66: "un cien por ciento más de lo fijado para las horas ordinarias". Art. 68: "un doscientos por ciento más".

**What was transcribed:** read as total-pay multipliers of 2 and 3 (1 + premium / 100), which is how `labor.hour_lines` applies them. Recorded in `MX_DERIVED_VALUES`. `compare` finds 100 and 200, and the test recomputes 2 and 3.

**For G1:** confirm the reading.

| Human G1 reviewer (name / date / verdict) | |
|---|---|

### TL-SUB-2 · Subsidy remainder rule (gap register B3)

**Source:** `S3/S3_DOF_Decreto_subsidio_empleo_01052024.html`, SHA-256 `84d244c2af8625fde24f83d7a468905fc7470cfcb37d4b054131f04573e63cbf` (DOF 01-05-2024, the base decree).

**What it says:** Art. Segundo ¶2: "En los casos en que el impuesto a cargo del trabajador sea menor que el subsidio para el empleo mensual… la diferencia no podrá aplicarse contra el impuesto que resulte a su cargo posteriormente, ni se entregará cantidad alguna…".

**Why it is still in force:** the 31-12-2024 amendment (`S3_DOF_Decreto_subsidio_empleo_31122024.html`, SHA-256 `1767215f…`) and the 31-12-2025 decree (S3) both reform ¶¶1, 3, 4, 5 only, and show ¶2 as "…".

**What was transcribed:** `mx_subsidy_remainder_rule` = **NOT_PAYABLE**, the engine's word for "neither carried forward nor paid". This mapping of the wording is for G1.

| Human G1 reviewer (name / date / verdict) | |
|---|---|
