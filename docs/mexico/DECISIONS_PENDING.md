# Mexico (MX) — Decisions Pending

Kept under the completion master prompt (`MEXICO_COMPLETION_MASTER_PROMPT.md` §3 stop condition 2). Each entry is a decision engineering may not take: the question, the options, the saved sources that bear on it, and what stays blocked (with its named code) until it is made. Engineering keeps working on everything the decision does not block.

**Owners** are roles, as in the gap register: **G1 owner** (ISR / CFDI), **G2 owner** (IMSS / SUA), **G3 owner** (INFONAVIT), **G4 owner** (State ISN), **G5 owner** (Labor), **Release owner**, **Security lead**, **Spec owner**.

| # | Decision | Owner | Blocks (code) | Status |
|---|---|---|---|---|
| D-01 | Monetary rounding rule | G1 owner | Every calculation; pack activation (`mx_rounding_rule` is required) | Open |
| D-02 | Pay frequency 01 Diario → Art. 96 DAILY? | G1 owner | Daily-paid employees (`MX_PAY_FREQUENCY_MAPPING_MISSING`) | Open |
| D-03 | CEAV lowest band: which minimum wage anchors "1.0 SM" | G2 owner | ZLFN employees in band 1 (`MX_CEAV_LOWEST_BAND_PENDING_G2`) | Open |
| D-04 | Interpretations behind transcribed rows (Batch 2, W1-1) | G1 / G2 / G3 / G5 owners | Nothing today (rows are Draft, `[PENDING G1]`); activation needs them confirmed | Open |
| D-05 | 48-hour week for January–April 2026 | G5 owner | Nothing today; the January–April row cites a decree in force only from 1 May 2026 | Open |
| D-06 | CDMX ISN: are vacation paid out at termination, the separation payment and the indemnity in the base? | G4 owner | Any finiquito with those lines for a CDMX worker (`MX_ISN_SPECIAL_PAY_RULE_MISSING`) | Open |
| D-10 | CDMX ISN 2026 benefit for micro (1%) and small (0.5%) employers | G4 owner | G4 sign-off / CDMX pack activation; until then a micro or small CDMX employer would be computed at the full 4% | Open |

---

## D-01 · Monetary rounding rule (`mx_rounding_rule`)

- **Question.** How is each monetary amount rounded (mode and quantum), and when (each line, or only totals)?
- **Options.**
  1. 2 decimals, rounded at the end of the calculation (CFDI sources), with a tie-breaking rule chosen by the owner (HALF_UP or HALF_EVEN): none of the sources states one.
  2. Whole pesos, 1–50 centavos down and 51–99 up (CFF Art. 20 ¶10) — but that paragraph governs **paying** a contribution to the authority, not a payslip line.
- **Sources.** S30 catCFDI c_Moneda (MXN: 2 decimals); S30 Anexo 20 p. 71 and Guía de llenado Q37/Q39 ("redondear al final del cálculo y no antes"); S30 `tdCFDI.xsd` / S28 `nomina12.xsd` (`t_ImporteMXN`, 2 decimals); CFF Art. 20 ¶10 (read in the archive, **not saved**: save it if it is to back the rule). Detail: `MEXICO_TRANSCRIPTION_BATCH_2_REPORT.md` §4.
- **Blocks.** Every calculation (`rounding.py`: the rule is read before any amount is produced) and pack activation (`MX_REQUIRED_TEXT_KEYS`). Gate 1b-1 on the scratch seed fails only on this key (W1-1).

## D-02 · Pay frequency 01 Diario

- **Question.** Does a daily pay frequency (S28 c_PeriodicidadPago 01) use the Art. 96 daily tariff (S2 B.I)?
- **Options.** Map 01 → DAILY; or keep it unmapped (daily-paid employees stay blocked).
- **Sources.** S2 B.I heading ("en función de la cantidad de trabajo realizado y no de días laborados… calculada en días"); S1 rule 3.12.2 (PDF p. 425). Log TL-PER-1; G1 checklist.
- **Found in W1-3 reading (2026-10-26):** RLISR Art. 175 (S25, PDF p. 46) lets a payer who pays "en función de cantidad de trabajo realizado y no de días laborados" use "la tarifa del artículo 96 de la Ley calculada en días". This ties B.I to piece-work pay (c_PeriodicidadPago 07 Unidad obra), not to a daily pay frequency. Art. 176 ties the 7-, 10- and 15-day tables to payments covering those periods. Neither names 01 Diario.
- **Blocks.** Employees paid daily: `MX_PAY_FREQUENCY_MAPPING_MISSING`.

## D-03 · CEAV lowest band reference (`mx_ceav_lowest_band_min_wage_ref`)

- **Question.** S11's band 1 is "1.0 SM*" (the LSS prints "1.00 SM*"). Which minimum wage anchors it for a ZLFN worker: the general zone or the ZLFN amount? And does S34 Transitorio Tercero (minimum wage "como unidad de cuenta, índice, base, medida o referencia" read as the UMA) apply to it, given S11 writes the other bands in UMA?
- **Options.** GENERAL; ZONE (the worker's own zone); UMA.
- **Sources.** S11 Transitorio Segundo table (PDF p. 7, image); S10 Art. 168 II a) table (PDF p. 51); S34 Transitorio Tercero (PDF p. 2); S9 (both zones).
- **Blocks.** ZLFN employees whose SBC falls in band 1: `MX_CEAV_LOWEST_BAND_PENDING_G2`. Phase 0 decision 4 assigned it to the G2 owner (SUA reconciliation).

## D-04 · Interpretations behind transcribed rows

Each is transcribed and cited, `[PENDING G1]`; the owner confirms or rejects it at sign-off. Rejecting one means changing that row only.

| Row(s) | Reading taken | Source | Owner |
|---|---|---|---|
| E&M 20.40 / 1.10 / 0.40; cash benefits 0.70 / 0.25 | DERIVED from the printed base plus the printed annual steps / shares (TL-IMSS-2) | S10 Arts. 106, 107; 1995 Transitorio DECIMO NOVENO | G2 |
| SBC ceiling 25×, E&M threshold 3× "salario mínimo" | Read as UMA multiples (TL-IMSS-3) | S10 Arts. 28, 106 II; **S34 Transitorio Tercero** (saved W1-1) | G2 |
| SBC floor `RAISE_TO_ZONE_MIN_WAGE` | "límite inferior el salario mínimo general del área geográfica respectiva" read as: an SBC below the zone minimum wage is raised to it. The floor is the zone minimum wage itself (a wage, not a unit of measure), so S34 does not turn it into the UMA (TL-SBC-1) | S10 Art. 28 | G2 |
| INFONAVIT credit, PERCENTAGE basis `SBC_TIMES_DAYS` | Art. 29 III points the discount base to fr. II, whose base is the LSS one (the SBC); the percentage applies to SBC × days of the period (TL-INF-2) | S27 Art. 29 II, III | G3 |
| Overtime ×2 / ×3 | "cien / doscientos por ciento más" read as ×2 / ×3 of the ordinary hourly pay (TL-WW-2) | S18 Arts. 66, 68 | G5 |
| CEAV band 1 upper bound 1.0 SM | Stored as a closed band so the engine never treats it as open-ended (TL-CEAV-1) | S11 | G2 |
| Vacation bands years 6–50 | DERIVED from Art. 76's wording; no row beyond 50 years (TL-VAC-1) | S26 Art. 76 | G5 |
| CDMX ISN on the vacation premium: in the base | Art. 156 III "Premios, primas, bonos…" read as covering the vacation premium (TL-ISN-2) | S22 Art. 156 III | G4 |
| Subsidy remainder `NOT_PAYABLE` | Art. Segundo ¶2 of the base decree, still in force (TL-SUB-2) | S3 (DOF 01-05-2024) | G1 |

## D-05 · 48-hour week for January–April 2026

- **Question.** S18 Transitorio Segundo gives 48 hours for 2026 "a partir del 1 de enero", but the decree is in force only from 1 May 2026. Does the January–April row stand?
- **Sources.** S18 Transitorios Primero, Segundo; S26 (consolidated LFT, PDF p. 454).
- **Blocks.** Nothing computed today; it is a G5 confirmation (Batch 2 report §5.7).

## D-06 · CDMX ISN on termination payments

- **Question.** Are (a) vacation paid out at termination, (b) the separation payment and (c) the indemnity part of the CDMX payroll-tax base?
- **Options.** Each one: in the base (as "remuneración al trabajo personal subordinado, independientemente de la designación", Art. 156 ¶1); or out.
- **Sources.** S22 Art. 156 ¶1 and I–IX (PDF p. 89); Art. 157 I–XV (pp. 90–91), whose fr. IV excludes only "las indemnizaciones por riesgos de trabajo". Log TL-ISN-2.
- **Blocks.** A CDMX finiquito carrying any of the three lines: `MX_ISN_SPECIAL_PAY_RULE_MISSING`. The seniority premium (Art. 156 VII, in) and PTU (Art. 157 XIII, out) are transcribed.

## D-10 · CDMX ISN 2026 benefit for micro and small employers

- **Question.** How is the 2026 benefit applied, and to whom? (a) Is "equivalente al 1% … respecto de la tasa" one percentage point (4% → 3%) or 1% of the rate? (b) What do the SAF general rules require (application, proof of size, sector)? (c) Where does Zoiko record an employer's size and sector?
- **Sources.** S22, decree of 19-12-2025, Transitorio TRIGÉSIMO SÉPTIMO (PDF p. 815; quoted in TL-ISN-1). The SAF "reglas de carácter general" it refers to are **not saved** (W2-5 source to find).
- **Blocks.** G4 sign-off of the CDMX pack. The engine applies the pack's 4% to every CDMX employer; it must not reach a micro or small employer in 2026 until this is decided and modelled.
