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

## W1-1 — 2026-10-26 (completion programme)

What Batch 2 left open: the SBC floor rule, the two INFONAVIT credit bases and the CEAV lowest-band reference; plus the de-indexation decree proposed as S34. Controls as before: a separate agent read only S10, S27 and S34 (blind), `compare` now also checks every wording a citation quotes, and tests pin each value to the engine vocabulary.

### TL-S34-1 · De-indexation decree saved (closes the source gap in TL-IMSS-3)

| | |
|---|---|
| Source | `S34/S34_DIP_CPEUM_ref226_27ene16.pdf`, SHA-256 `16c38e9fa2fdf8185413051f9f3e9573337cfd5705808a5f5718c1fec8d1c76e` (Diputados copy of the DOF decree of 27-01-2016; archive capture 20261015095600, digest OK; `ARCHIVE_COPY_VERIFIED`) |
| Text | Transitorio Tercero (PDF p. 2): "todas las menciones al salario mínimo como unidad de cuenta, índice, base, medida o referencia para determinar la cuantía de las obligaciones y supuestos previstos en las leyes federales … se entenderán referidas a la Unidad de Medida y Actualización" |
| Effect | The SBC ceiling (25×) and the E&M threshold (3×) rows now cite S34 for their UMA reading. Values unchanged |
| Blind | Same article, same wording, same page |
| Human G1 / G2 reviewer (name / date / verdict) | |

### TL-SBC-1 · SBC floor rule (gap register B11; Q5)

| | |
|---|---|
| Source | `S10/S10_IMSS_LSS.pdf`, SHA-256 `875efb2c8e6562f4236a343c27f3199dc04732890e484e95086f69da05aa632c`. Art. 28 (PDF p. 11): "estableciéndose como límite superior el equivalente a veinticinco veces el salario mínimo general que rija en el Distrito Federal y como límite inferior el salario mínimo general del área geográfica respectiva" |
| Row | `mx_sbc_min_rule` = `RAISE_TO_ZONE_MIN_WAGE` (engine vocabulary `sbc.SBC_MIN_RULES`) |
| Reading | A lower limit: an SBC below the zone minimum wage is raised to it. Nothing in Art. 28 makes a lower SBC an error, so `BLOCK_BELOW_ZONE_MIN_WAGE` has no support. The floor is the zone minimum wage itself (a wage), so S34 does not turn it into the UMA. **Interpretation for the G2 owner** (DECISIONS_PENDING D-04) |
| Blind | Same quote and page; chose RAISE, noting that "raise" is a reading of "límite inferior", not an explicit instruction |
| Machine | The quote is found in S10 (`compare` quote check) |
| Human G2 reviewer (name / date / verdict) | |

### TL-INF-2 · INFONAVIT credit bases (gap register B9; Q7)

| | |
|---|---|
| Source | `S27/S27_DIP_LIFNVT.pdf`, SHA-256 `9ee6e5ef336dee5700726bd3c570d24f91fc458136e298ae2e3806bd12217912`. Art. 29 III (PDF p. 16): "La integración y cálculo de la base salarial para efectos de los descuentos será la contenida en la fracción II del presente artículo". Fr. II (PDF p. 16): "En lo que corresponde a la integración y cálculo de la base y límite superior salarial para el pago de aportaciones, se aplicará lo contenido en la Ley del Seguro Social" |
| Row | `mx_infonavit_percentage_basis` = `SBC_TIMES_DAYS`: a percentage notice applies to the SBC (capped as the LSS caps it) × the period's days. **Interpretation for the G3 owner** (D-04): the law names the base, not the day count |
| Not transcribed | `mx_infonavit_fixed_amount_basis`. S27 has no per-period rule for a fixed-amount discount (blind: none found under "cuota fija", "amortiza*"). It sits in INFONAVIT's own payment regulation, which the Diputados compilation does not carry (index `regla.htm`, capture 20261012195540). **BLOCKED-ON-SOURCE**; a FIXED_AMOUNT notice keeps blocking (`MX_INFONAVIT_METHOD_UNSUPPORTED`) |
| Citation fix | TL-INF-1 and the `mx_infonavit_er_pct` row cited Art. 29 II on PDF p. 15. It is on **PDF p. 16** ("16 de 93"; p. 15 carries the Art. 29 heading). Corrected; the blind agent read p. 16 independently |
| Human G3 reviewer (name / date / verdict) | |

### Still open after W1-1

- **CEAV lowest-band reference:** a G2 decision (DECISIONS_PENDING D-03).
- **Rounding:** a G1 decision (D-01). On a scratch seed, gate 1b-1 now fails only on `mx_rounding_rule`.

## W1-2 — 2026-10-26 (completion programme)

### TL-ISN-1 · CDMX payroll-tax rate (gap register B10)

| | |
|---|---|
| Source | `S22/S22_SAF_Codigo_Fiscal_CDMX_2026.pdf`, SHA-256 `5d989b7e659206283c61532c150385a17367a16e85d801cec002f8a1250cfc5f` (SAF "CÓDIGO FISCAL 2026"; **VERIFIED** by a logged direct download; latest reform it names: Gaceta 19-12-2025, which does not touch Arts. 156–159) |
| Row | `MX-ISN-CDMX-2026`: `mx_isn_rate_pct` = 4 (employer). Art. 158 (PDF p. 91): "aplicando la tasa del 4% sobre el monto total de las erogaciones realizadas por concepto de remuneraciones al trabajo personal subordinado" |
| Spec | §15 says 4%: **same** (the WRONG_VERSION 2022 text said 3% and is not cited) |
| Machine | `compare`: the 4 and the quoted wording are found |
| Gate 1b-1 (scratch seed) | `MX-ISN-CDMX-2026`: 1 row, 0 missing, 0 extra, **content check passes**. Activation readiness: content, evidence and sources-verified **met**; G1 review and golden vectors not met |
| 2026 micro / small-employer benefit | **Found by the blind transcription, confirmed:** the 19-12-2025 decree's Transitorio TRIGÉSIMO SÉPTIMO (S22 PDF p. 815): "Para el ejercicio fiscal 2026, se aplicará un beneficio fiscal respecto al Impuesto sobre Nóminas … de conformidad con las reglas de carácter general que emita la Secretaría de Administración y Finanzas, únicamente a aquellos contribuyentes considerados micro empresas equivalente al 1% y para las pequeñas empresas equivalente al 0.5% respecto de la tasa". Micro: 0–10 workers; small: 11–50 (industry, services) or 11–30 (commerce). **Not modelled:** the SAF general rules are not saved, and "1% respecto de la tasa" may mean one percentage point or 1% of 4%. The pack carries 4%; a micro or small employer would be overcharged. **D-10**, a pre-pilot G4 checklist item. (TRIGÉSIMO SEXTO earmarks revenue only; it does not change the rate) |
| Blind second transcription | Same rate, article, page and wording; same latest reform (Gaceta 19-12-2025, in force 1 Jan 2026) |
| Human G4 reviewer (name / date / verdict) | |

### TL-ISN-2 · Which special payments are in the CDMX base (gap register B10, B12)

| Concept | In the base? | Wording (S22, PDF pp. 89–91) |
|---|---|---|
| Aguinaldo | **Yes** | Art. 156 V "Gratificaciones y aguinaldos" |
| Vacation premium | **Yes** (reading) | Art. 156 III "Premios, primas, bonos, estímulos e incentivos": the vacation premium read as a "prima". Blind: "IN only by inference" from 156 III with 156 ¶1. **Interpretation for G4** (D-04) |
| Seniority premium | **Yes** | Art. 156 VII "Primas de antigüedad" |
| PTU | **No** | Art. 157 XIII "Las participaciones en las utilidades de la empresa" |
| Vacation paid out at termination, separation payment, indemnity | **Not transcribed (they block)** | Neither article names them. Art. 156 taxes "erogaciones … por concepto de remuneración al trabajo personal subordinado, independientemente de la designación"; Art. 157 IV excludes only indemnities "por riesgos de trabajo". Whether a severance indemnity is "remuneration" is a **G4 decision (D-06)**. Blind: "DOES NOT SAY" for all three |

Ordinary earnings are not content: each earning classification carries its own ISN flag, per state, approved by a second Super Admin. Art. 157's exclusions (SAR and INFONAVIT contributions, IMSS quotas, travel expenses, social welfare benefits, …) are what a reviewer checks those flags against. The reductions of Arts. 276 ff. (recycling, hiring people with disabilities, …) are employer-specific and are not modelled.

| Human G4 reviewer (name / date / verdict) | |
|---|---|

## W1-3a — 2026-10-26 (completion programme): special-pay exemptions and withholding (gap register B12)

Rule objects in `engine/countries/mexico_rules.py`, wired into `MX_SPECIAL_PAY_RULES` / `MX_AGUINALDO_RULE`. Each cites the wording it rests on; `compare` finds every quote in its file.

Sources: `S24/S24_DIP_LISR.pdf` (SHA-256 `803c2875c09c751c1966b8eb4dca99f460b237da4ef67ee04b4fa325d8c2f786`, last reform DOF 01-04-2024), `S25/S25_DIP_RLISR.pdf` (`0538fd2fa3da9705370350b1e25a1656cc681d2c489545334079e1b35360d6e3`, last reform DOF 06-05-2016), `S26/S26_DIP_LFT.pdf` (`12f09393a1951a91c3f57f579bf611b034edf1a5f78cdbfb828e23ff3a9acbf7`), S34.

### TL-SP-1 · Exempt part (LISR Art. 93)

| Concept | Rule transcribed | Wording (PDF page) |
|---|---|---|
| Aguinaldo | Exempt up to **30 days** of the reference wage per calendar year | Art. 93 XIV, p. 123: "Las gratificaciones … durante un año de calendario, hasta el equivalente del salario mínimo general del área geográfica del trabajador elevado a 30 días" |
| Vacation premium, PTU | Exempt up to **15 days** each, per calendar year | Art. 93 XIV, p. 123: "las primas vacacionales … y la participación de los trabajadores en las utilidades … hasta por el equivalente a 15 días de salario mínimo general del área geográfica del trabajador, por cada uno de los conceptos señalados" |
| Seniority premium, separation payment, indemnity | Exempt up to **90 days** of the reference wage **per year of service**, one cap shared by all three; a fraction of more than six months counts as a year | Art. 93 XIII, pp. 122–123 |
| Vacation paid out | **No exemption** (Art. 93 names none) | — |
| A worker on the area minimum wage | **Blocks** (`MX_ART93_I_NOT_MODELLED`): Art. 93 I exempts in full the benefits within the legal minimums; not modelled | Art. 93 I, p. 121 |

- **Year to date.** The XIV caps are per calendar year, so each payslip now receives the exempt amounts already used that year (`_year_to_date_exempt`, with the same ordering and correction rules as the month-to-date subsidy accumulator; bound into the approval fingerprint).
- **Shared XIII cap.** The law gives one cap for every separation payment. Splitting it across the three CFDI kinds is not legislated: it is allocated **pro rata** (the total exempt is the law's; the split is an engineering choice, D-04).
- **Reference wage: D-07 (blocks).** XIII and XIV say "salario mínimo general del área geográfica". The LISR does use "Unidad de Medida y Actualización" in later-reformed articles, but not here. S34 Transitorio Tercero would read such a reference as the UMA; the text would read it as the worker's zone minimum wage (RLISR Art. 167: the place of work). The difference is about 2.7×. Both readings are built and tested; until the G1 owner decides, every special payment blocks with `MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED`.

### TL-SP-2 · Withholding (LISR Arts. 95, 96; RLISR Arts. 172, 174)

| Case | Rule | Wording |
|---|---|---|
| Aguinaldo, vacation premium, PTU, vacation paid out in an ordinary run | Taxable part withheld with the period's pay (`combine_with_ordinary`) | Art. 96 ¶2, p. 130: "aplicando a la totalidad de los ingresos obtenidos en un mes de calendario" |
| The same paid in their own run | **RLISR Art. 174** (fr. I–V: ÷365 ×30.4; add the monthly ordinary income; tax difference ÷ fr. I amount; that rate × the payment). Built and tested; the choice of method is **D-08 (blocks)**: Art. 96 makes RLISR 174 an option ("podrán"), and the default needs month-to-date income a special run does not carry | RLISR Art. 174, pp. 45–46 |
| Monthly ordinary income | **D-09 (blocks):** neither the LISR nor the RLISR says how the "último sueldo mensual ordinario" or "el ingreso ordinario … en el mes" is derived from a daily salary | LISR Arts. 95, 96; RLISR Art. 174 II |
| Separation payments | Not withheld with ordinary pay (`combine_with_ordinary = False`); the finiquito rule applies Art. 96's separation rate (W1-3b) | Art. 96 ¶7, p. 131; RLISR Art. 172 |

### Blind second transcription (W1-3a)

A separate agent read only S24, S25 and S26. It agreed on **every** limit, unit, period, page and formula in TL-SP-1 and TL-SP-2. In particular:
- **One cap for all separation payments:** RLISR Art. 172 nets the Art. 93 XIII amount off the combined total.
- **Art. 93 has no "Unidad de Medida y Actualización";** the law has it elsewhere (Art. 74 p. 89, Art. 79 p. 106).
- **"Último sueldo mensual ordinario": NOT FOUND.** 30.4 appears only in RLISR Arts. 174 I and 163 I and in the subsidy table.

It also raised three points, all now recorded:
1. **"cuando dichas gratificaciones se otorguen en forma general"** (Art. 93 XIV) is a condition of the aguinaldo exemption. The statutory aguinaldo (LFT Art. 87) is general by law, so the rule assumes it holds. That is a reading for the G1 owner (D-04). An employer bonus that is not general would need its own classification.
2. **Sunday premium** (one area minimum wage per Sunday worked) **and overtime** (Art. 93 I: 50%, at most five area minimum wages a week). These are ordinary hour-based lines, not special payments: they are the "Art. 93 exemptions for ordinary earnings" interface (gap register A15, W3).
3. **Art. 96 ¶1, "No se efectuará retención a las personas que en el mes únicamente perciban un salario mínimo general":** the ordinary ISR path does not apply this. Added to the gap register as **A16** (W3).

### TL-SP-3 · Aguinaldo rule (LFT Art. 87)

- **Payable by:** 19 December, from "antes del día veinte de diciembre" (p. 25).
- **Fraction:** days employed in the calendar year ÷ days in that year (365 or 366), both ends counted, for "la parte proporcional … conforme al tiempo que hubieren trabajado" (p. 25). The day count is a reading (D-04).
- Engine effect: an aguinaldo amount is now computed (it used to block with `MX_AGUINALDO_RULE_MISSING`). Its withholding still blocks on D-07 and D-08.

| Human G1 reviewer (name / date / verdict) | |
|---|---|

## W1-3b — 2026-10-26 (completion programme): termination reasons and the finiquito rule (gap register B14)

Rule objects in `engine/countries/mexico_rules.py`, wired into `MX_TERMINATION_REASONS` and `MX_FINIQUITO_RULE`. Every citation quotes S26 (LFT), S24 or S25, and `compare` finds each quote (501 checks, 0 misses).

### TL-TER-1 · The reason catalog and its separation components (LFT)

| Code | Reason | Components (kind) | Wording (PDF page) |
|---|---|---|---|
| `LFT_47_RESCISSION_BY_EMPLOYER` | Employer rescinds with cause | Seniority premium (022) | Art. 47 p. 15; Art. 162 III p. 52: "a los que sean separados de su empleo, independientemente de la justificación o injustificación del despido" |
| `LFT_48_DISMISSAL_INDEMNIFIED` | Dismissal; the worker takes the indemnity | 3 months of salary (025) + seniority premium | Art. 48 p. 16: "que se le indemnice con el importe de tres meses de salario" |
| `LFT_49_NO_REINSTATEMENT` | Employer exempt from reinstating | Art. 50 I or II by years (025) + 3 months (025) + seniority premium | Arts. 49 p. 18, 50 p. 19 |
| `LFT_51_RESCISSION_BY_WORKER` | Worker rescinds for cause | As Art. 50 (Art. 52) + seniority premium | Arts. 51, 52 p. 20 |
| `LFT_53_III_END_OF_TERM` | End of the work or the term | None | Art. 53 III p. 20 |
| `LFT_54_INCAPACITY` | Non-occupational incapacity | One month (023) + seniority premium (12 days a year "de conformidad con lo dispuesto en el artículo 162") | Art. 54 p. 21 |
| `LFT_162_VOLUNTARY_SEPARATION` | Voluntary separation | Seniority premium only from 15 whole years of service | Art. 162 III p. 52 |

**Amounts**
- **Art. 50 II (indefinite, c_TipoContrato 01):** 20 days per year of service.
- **Art. 50 I (fixed term, 03):**
  - under a year: the salary of half the time served;
  - over a year: six months for the first year plus 20 days for each later year.
- **Art. 50 III:** three months, read as **90 days**. LFT Art. 89 ¶3 converts a monthly salary to daily by ÷ 30. A reading (D-04).
- **Any other contract type** (02 obra determinada, 04–99): blocks with `MX_TERMINATION_CONTRACT_UNSUPPORTED`. Art. 50 I names only "tiempo determinado".
- **Seniority premium (Art. 162 I):** 12 days per year of service. The salary is bounded by Arts. 485–486: no lower than the minimum wage, no higher than twice "el salario mínimo del área geográfica de aplicación".
  - "Trabajadores de planta" is read as an indefinite contract (01): a reading (D-04).
  - Art. 162 IV's deferral when more than 10% of the workforce leaves voluntarily in a year is **not modelled**: the premium is paid at separation (IV a).

**Undecided, each blocking with its own code**
- **D-12, indemnity salary (Art. 89):** the daily rate "y la parte proporcional de las prestaciones mencionadas en el artículo 84". Built as the daily salary × the labour policy's integration factor (aguinaldo, vacation premium); the same question as gap C4. `MX_INDEMNITY_SALARY_UNDECIDED`.
- **D-13, part years:** do the "por cada año de servicios" counts take a part year pro rata? `MX_SERVICE_YEARS_COUNT_UNDECIDED`.
- **D-07b, the Art. 486 cap:** the zone minimum wage, or the UMA? `MX_SENIORITY_PREMIUM_WAGE_REFERENCE_UNDECIDED`.

**Not in the catalog (D-11)**
- **Mutual consent (Art. 53 I):** the LFT grants no component, but whether a voluntary-type premium applies is not settled by the text.
- **Death (Art. 53 II):** the premium goes to the beneficiaries of Art. 501, not the worker; the receipt has a different payee.
- **Art. 434 (collective) terminations.**
- **Back pay and interest (salarios vencidos, Art. 48 ¶2–3):** fixed by a tribunal, never by payroll.

### TL-TER-2 · The finiquito rule

- **Vacation owed:**
  - the year the termination falls in: its days in proportion to the time served in it (Art. 79 ¶2 p. 24, "remuneración proporcionada al tiempo de servicios prestados");
  - each completed year: its days not taken or paid out. The LFT does not say outright that untaken days of a completed year are paid at termination (Art. 79 ¶1 forbids paying instead of rest). A reading (D-04).
- **Separation withholding (LISR Art. 96 ¶7 p. 131, RLISR Art. 172 p. 45):** the separation's taxable total × (monthly ISR on the last monthly ordinary salary ÷ that salary). When the total is below that salary, the monthly tariff applies to it. Needs D-09.
- **Aguinaldo and vacation premium in the finiquito:** their own special-pay rule (RLISR Art. 174; D-08).
- **Vacation paid out:** ordinary income of the month (Art. 96). The finiquito run carries no month-to-date income, so it **blocks** (`MX_FINIQUITO_ORDINARY_INCOME_UNSUPPORTED`), new gap item **A17**.

### Blind second transcription (W1-3b)

A separate agent read only S26, plus S24 and S25 for the withholding. It agreed on **every** amount, condition and page in TL-TER-1 and TL-TER-2. Its NOT FOUND answers match the open points:
- untaken vacation of completed years paid at termination: not stated;
- how a part year counts (Arts. 50, 162): not stated (D-13);
- "tres meses" in days: not stated (Art. 89 gives only ÷ 7 and ÷ 30).

It added four details, now recorded:
1. **Art. 89 ¶2:** for variable pay, the indemnity salary is the average of the last 30 days actually worked (from a raise, if there was one). Part of D-12.
2. **Art. 486:** work in several areas is capped at twice the *average* of their minimum wages. Not modelled: the engine uses the worker's one zone.
3. **Art. 50 IV:** digital-platform workers have their own indemnity. Out of scope (no platform-worker contract type is supported).
4. **Art. 47, last paragraphs:** without the written notice of the cause, the separation is presumed unjustified. An operator recording `LFT_47_RESCISSION_BY_EMPLOYER` must hold that notice as evidence (the termination record already requires evidence). Added to D-11.

| Human G1 / G5 reviewer (name / date / verdict) | |
|---|---|

## W1-4 — 2026-10-26 (completion programme): PTU and the annual ISR adjustment (gap register B15, B16)

Rule objects in `engine/countries/mexico_rules.py`, wired into `MX_PTU_RULE`, `MX_PTU_EXCLUSION_REASONS`, `MX_ANNUAL_ADJUSTMENT_RULE` and `MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS`. The 2026 annual tariff is a new content table, `MX_ISR_ANNUAL_TARIFFS`. `compare`: 533 checks, 0 misses.

### TL-PTU-1 · PTU (LFT Arts. 122–127; LISR Arts. 76 V, 150)

| Element | Rule | Wording (S26 / S24, PDF page) |
|---|---|---|
| Split | Half the pool by days worked, half in proportion to salary | Art. 123 p. 31 |
| Salary | The cash daily rate: the gross of lines whose approved classification carries the PTU flag (`PTU_WAGE_BASE`); finiquito lines are not counted | Art. 124 p. 31: "la cantidad que perciba cada trabajador en efectivo por cuota diaria. No se consideran … las gratificaciones … ni … trabajo extraordinario" |
| Days | The days paid in committed ordinary and correction runs. A reading (D-04): Art. 127 IV counts maternity and work-risk incapacity as active service, and the engine pays those days; unpaid absences are not counted | Arts. 123, 127 IV |
| Exclusions (operator-asserted, with evidence and a second approver) | `LFT_127_I_DIRECTOR`, `LFT_127_VI_DOMESTIC`, `LFT_127_VII_EVENTUAL_UNDER_60_DAYS` | Art. 127 I, VI, VII p. 32 |
| Cap | The more favourable of three months of salary (90 × the year's average cash daily rate) and the average PTU received in the last three years (the employer's DISTRIBUTED cycles) | Art. 127 VIII p. 32 |
| Payment deadline | 60 days after the annual return is due: company (MORAL), three months after the fiscal year (31 March); individual (FISICA), April (30 April) | Art. 122 p. 31; LISR Art. 76 V p. 91, Art. 150 p. 180 |

**Not modelled.**
- Art. 127 II, the salary cap for trusted workers (120% of the highest unionised salary): the engine has neither fact. A pre-pilot G5 checklist item.
- Art. 127 III (one month's salary for workers of people living only from their own work).
- Art. 126 (exempt employers).
- Art. 127 V and IX.

**D-14, blocking only the case that needs it.**
- `MX_PTU_CAP_EXCESS_UNDECIDED`: the law does not say where an amount above the Art. 127 VIII cap goes ("UNDISTRIBUTED", kept as residue, is built).
- `MX_PTU_HISTORY_AVERAGE_UNDECIDED`: how the three-year average counts a worker with fewer than three years of PTU, when the choice changes the cap.

### TL-ANN-1 · Annual ISR adjustment (LISR Art. 97; S3 Art. Tercero; S2 Anexo 8 C.II)

| Element | Rule | Wording |
|---|---|---|
| Not adjusted by the employer | Started after 1 January; left before 1 December; annual income above $400,000.00; the worker told the employer in writing they will file (operator exclusion `LISR_97_C_WORKER_FILES_OWN_RETURN`) | Art. 97 a)–c), pp. 131–132 |
| The $400,000 test | Applied to **gross** income (`annual_gross`, new in the worker facts). Art. 97 b) says "ingresos anuales … que excedan de $400,000.00" without saying gross or taxable. A reading (D-04) | Art. 97 b) |
| Annual tax | The 2026 Art. 152 tariff on the year's taxable income, less the employment subsidy that "le correspondió" (`subsidy_due_total`, new in the worker facts: the subsidy computed each period, not only the part applied), never below zero | Art. 97 ¶2; S3 Art. Tercero I–III |
| Difference owed | Withheld in full in the run that applies it | Art. 97 ¶4: paid "a más tardar en el mes de febrero siguiente" |
| Difference in the worker's favour | Set against that run's withholding; the rest carried to the following withholdings | Art. 97 ¶4: "contra la retención del mes de diciembre y las retenciones sucesivas, a más tardar dentro del año de calendario posterior" |

**The 2026 annual tariff (S2 C.II, PDF pp. 18–19), 11 brackets:**

| Lower | Upper | Fixed quota | % |
|---|---|---|---|
| 0.01 | 10,135.11 | 0 | 1.92 |
| 10,135.12 | 86,022.11 | 194.59 | 6.40 |
| 86,022.12 | 151,176.19 | 5,051.37 | 10.88 |
| 151,176.20 | 175,735.66 | 12,140.13 | 16.00 |
| 175,735.67 | 210,403.69 | 16,069.64 | 17.92 |
| 210,403.70 | 424,353.97 | 22,282.14 | 21.36 |
| 424,353.98 | 668,840.14 | 67,981.92 | 23.52 |
| 668,840.15 | 1,276,925.98 | 125,485.07 | 30.00 |
| 1,276,925.99 | 1,702,567.97 | 307,910.81 | 32.00 |
| 1,702,567.98 | 5,107,703.92 | 444,116.23 | 34.00 |
| 5,107,703.93 | En adelante | 1,601,862.46 | 35.00 |

- **Checks:** continuous and quota-consistent (`test_annual_tariff_2026_…`); every bracket's four numbers are found on one line of S2 (`compare`).
- **Not modelled:** the deduction of a local tax on salaries of up to 5% (Art. 97 ¶2–3). No such tax applies in the states in scope.

### Blind second transcription (W1-4)

A separate agent read only S26, S24, S2 and S3. It agreed on **all 11** annual brackets (rows 1–7 on p. 18, rows 8–11 on p. 19, with a warning not to confuse them with the 2025 table C.I), and on every PTU and annual-adjustment rule. It confirmed the open points:
- **The law is silent** on where an amount above the Art. 127 VIII cap goes, and on averaging fewer than three years: **D-14**.
- **The $400,000 test is unclear** between gross and taxable ("ingresos anuales por los conceptos a que se refiere este Capítulo"; Art. 98 III e) uses the same words): a D-04 reading.
- **The subsidy wording is "le correspondió"** in Art. Tercero I–III; "aplicado" does not appear.

It added:
- **LISR Art. 9 (p. 14)** also states the company deadline: "dentro de los tres meses siguientes a la fecha en la que termine el ejercicio fiscal". It agrees with Art. 76 V.
- **Art. 122 ¶3:** unclaimed PTU is added to the next year's pool. Not modelled: the employer enters each year's distributable amount, so it includes any carried amount. Noted for G5.
- **Art. 122 ¶2:** an additional distribution after a tax-authority resolution. That is a new cycle the employer enters, not computed.

| Human G1 / G5 reviewer (name / date / verdict) | |
|---|---|

## W1-5 — 2026-10-26 (completion programme): filing calendar, movement deadline, holidays, risk-premium period (gap register B18, B11)

New source **S35**: `S35/S35_DIP_CFF.pdf` (Código Fiscal de la Federación, last reform DOF 09-04-2026), SHA-256 `be7427b20d3552775ab42018f8f87578078770095bf8cf46322c25e36ee3aa7d`. Archive capture 20261006134049, digest OK; `ARCHIVE_COPY_VERIFIED`.

### TL-CAL-1 · Filing calendar (`MX_FILING_CALENDAR`)

| Report type | Due | Wording |
|---|---|---|
| `MX_ISR_WITHHOLDING` | 17th of the month after the withholding period | **S35** CFF Art. 6 I (PDF p. 4): "en los casos de retención … las enterarán a más tardar el día 17 del mes de calendario inmediato posterior al de terminación del período de la retención". The LISR's own day-17 sentence (Art. 96, p. 131) covers only individuals and Title III non-profits, so the CFF is the general rule for any employer |
| `MX_IMSS` | **Not listed (D-15)**, removed after the blind transcription | LSS Art. 39 (p. 14) makes quotas monthly ("a más tardar el día diecisiete del mes inmediato siguiente"), but the 1997 LSS **Transitorio VIGÉSIMO SÉPTIMO** (p. 111) keeps retiro / CEAV "en forma bimestral, hasta en tanto no se homologuen los períodos de pago de las Leyes del ISSSTE e INFONAVIT". One IMSS liability carries every branch, so a single monthly date would misstate the RCV part |
| `MX_ISN_RETURN` (CDMX) | 17th of the following month | S22 Art. 159 (PDF p. 91) |
| `MX_INFONAVIT` | **Not listed (D-15)** | S27 Art. 35 (p. 22) says "por mensualidades vencidas … días diecisiete del mes inmediato siguiente", but the 1997 decree's Transitorio SEXTO (p. 57) says "continuará siendo de forma bimestral hasta que en la Ley del [ISSSTE] se establezca que la periodicidad de pagos se realizará mensualmente". That law is not saved |

- **Seeding.** Only S22 is VERIFIED, so a manual run of `seed_statutory_report_templates.py` would seed only the CDMX ISN due dates as live filing-calendar rows. The ISR rule (S35) rests on an archive copy and is skipped until it is VERIFIED. **No deploy runs that seed.**

**Blind second transcription (W1-5).** A separate agent read S10, S27, S29, S35, S26, S22 and S24. It agreed on every rule and page above, and on the 2026 dates of both holiday lists (its weekday arithmetic is shown in its report). It found what my search missed: **LSS Transitorio VIGÉSIMO SÉPTIMO** (p. 111, RCV bimonthly), which removed `MX_IMSS` from the calendar. It also noted:
- the 2016 INFONAVIT decree does not repeal the 1997 Transitorio SEXTO;
- RACERF Art. 45 allows registration on the working day before employment starts;
- LSS Art. 34 sets other deadlines for variable salary (the first five business days of odd months);
- CFF Art. 12 moves a deadline to the next business day when it falls on a non-working day;
- the CFF names 1 December for the change of Executive while the reformed LFT names 1 October (neither falls in 2026).

### TL-CAL-2 · Work-risk premium period (`MX_RISK_PREMIUM_PERIOD`)

S29 RACERF Art. 32 III (PDF p. 12), SHA-256 `78fb70d213053e46d3e739b9d80bf7da733d80f27446af7d5812fc6de80533c9`: the premium "tendrá vigencia desde el primero de marzo del año siguiente a aquel en que concluyó el periodo computado y hasta el día último de febrero del año subsecuente". LSS Art. 74 (S10 p. 26) delegates the period to the regulation. So the rule is **start 1 March**, ending the day before the next start. Engine effect: an employer risk premium can now be approved (before, `MX_NO_RISK_PREMIUM` was the only outcome).

### TL-CAL-3 · IMSS movement deadline and the business-day calendar

- **Deadline:** S10 LSS Art. 15 I (PDF p. 6), SHA-256 `875efb2c8e6562f4236a343c27f3199dc04732890e484e95086f69da05aa632c`: "comunicar sus altas y bajas, las modificaciones de su salario y los demás datos, dentro de plazos no mayores de cinco días hábiles". Counted from the day after the event: RACERF Art. 57 (p. 19, bajas: "contado a partir del día siguiente") and LSS Art. 34 I (salary changes). Transcribed: **5 business days**.
- **Which days are not business days: D-16 (decision).** LSS Art. 9 fills gaps with "la Ley Federal de Trabajo, del Código o del derecho común, en ese orden". Two lists exist:
  - **LFT** Arts. 74 (p. 23) and 715 (p. 318), which also excludes "los festivos que señale el calendario oficial" and days the labour authorities suspend work;
  - **CFF** Art. 12 (p. 7), which also excludes the fiscal authorities' general vacations.

  The 2026 dates each list gives, computed from the rules:

  | Date | LFT Art. 74 | CFF Art. 12 |
  |---|---|---|
  | Thu 1 Jan | Yes | Yes |
  | Mon 2 Feb (first Monday) | Yes | Yes |
  | Mon 16 Mar (third Monday) | Yes | Yes |
  | Fri 1 May | Yes | Yes |
  | Tue 5 May | No | **Yes** |
  | Wed 16 Sep | Yes | Yes |
  | Mon 16 Nov (third Monday) | Yes | Yes |
  | Fri 25 Dec | Yes | Yes |
  | 1 Oct / 1 Dec (change of Executive, every six years) | Not in 2026 | Not in 2026 |
  | Election days (LFT Art. 74 IX); authority vacations / official calendar | Not datable from saved sources | Not datable from saved sources |

  **`MX_OFFICIAL_HOLIDAYS` stays EMPTY** until D-16 is decided, so every movement stays `DUE_DATE_UNSOURCED`. The dates above are ready to transcribe once it is.

| Human G2 reviewer (name / date / verdict) | |
|---|---|

## W2-5 — 2026-10-26 (completion programme)

### TL-CAL-4 · INFONAVIT due date and the RCV / INFONAVIT periodicity (closes D-15)

- **New source S36:** `S36/S36_DIP_LISSSTE.pdf` (Ley del ISSSTE, last reform DOF 15-01-2026), SHA-256 `aa6e0e437331debd80d0086155e2d99885ea5e22cb13353c44eb0b1090f0b4d5`; archive capture 20261004141029, digest OK; `ARCHIVE_COPY_VERIFIED`.
- **What it says.** Art. 21 (PDF p. 11): "El entero de las Cuotas y Aportaciones al seguro de retiro, cesantía en edad avanzada y vejez y al Fondo de la Vivienda será por bimestres vencidos, a más tardar el día diecisiete de los meses de enero, marzo, mayo, julio, septiembre y noviembre de cada año".
- **Reading.** Both transitorios end only when the ISSSTE law pays monthly:
  - Ley INFONAVIT 1997 Transitorio SEXTO (S27 p. 57): "hasta que en la Ley del [ISSSTE] se establezca que la periodicidad de pagos se realizará mensualmente";
  - LSS Transitorio VIGÉSIMO SÉPTIMO (S10 p. 111): "hasta en tanto no se homologuen los períodos de pago de las Leyes del ISSSTE e INFONAVIT".

  The ISSSTE law still pays bimonthly, so **INFONAVIT and RCV are bimonthly**.
- **Transcribed:** `MX_INFONAVIT`, BIMONTHLY, due the 17th of the month after each bimester (Art. 35 "días diecisiete del mes inmediato siguiente", applied per bimester: 17 March for January–February, and so on). It cites S27, an archive copy, so the calendar seed skips it until S27 is VERIFIED.
- **IMSS:** RCV bimonthly and the other branches monthly (LSS Art. 39). One IMSS liability carries every branch, so no single date is right: new gap item **A18** (split the RCV branches into their own liability, then add two IMSS rules).

| Human G2 / G3 reviewer (name / date / verdict) | |
|---|---|

## W3 — 2026-10-26 (completion programme): content interfaces for the engine refusals

### TL-SUB-3 · Subsidy monthly cap (gap register A15)

- **Source:** `S3/S3_DOF_Decreto_subsidio_empleo_31122025.html`, Art. Segundo ¶4 as reformed: "Cuando los pagos por salarios sean por periodos menores a un mes, la cantidad del subsidio para el empleo que corresponda a la persona trabajadora, no podrá exceder el monto mensual máximo que resulte de multiplicar el valor mensual de la Unidad de Medida y Actualización por 15.02%".
- **Interface:** the text key `mx_subsidy_monthly_cap_rule` (vocabulary `subsidy.MONTHLY_CAP_RULES`). While it is absent, the engine still blocks with `MX_SUBSIDY_MONTHLY_CAP_RULE_MISSING`.
- **Transcribed:** `CAP_AT_MONTHLY_AMOUNT`. Once the month's earlier payments reach the monthly amount, a payment gets only what is left (`capped` in the trace). That the cap applies to the month's payments together, not to each payment, is a reading (D-04).
- **Blind second transcription:** pending; done for all W3 rows together.
