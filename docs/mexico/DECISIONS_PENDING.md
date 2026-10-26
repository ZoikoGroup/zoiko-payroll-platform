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
| D-11 | Termination reasons outside the catalog: mutual consent, death, Art. 434 | G5 owner | Recording those terminations (`MX_TERMINATION_REASON_UNKNOWN`) | Open |
| D-12 | Indemnity salary (LFT Art. 89 integrated salary; same question as gap C4) | G1 / G5 owners | Every indemnity and the Art. 54 month (`MX_INDEMNITY_SALARY_UNDECIDED`) | Open |
| D-13 | Does "por cada año de servicios" count a part year? | G5 owner | Art. 50, 54 and 162 amounts (`MX_SERVICE_YEARS_COUNT_UNDECIDED`) | Open |
| D-14 | PTU cap (LFT Art. 127 VIII): where the excess goes; the three-year average with fewer years | G5 owner | Only an allocation where it changes the result (`MX_PTU_CAP_EXCESS_UNDECIDED`, `MX_PTU_HISTORY_AVERAGE_UNDECIDED`) | Open |
| D-15 | INFONAVIT and RCV payment periodicity (monthly or bimonthly) | G2 / G3 owners | — | **Resolved by sources (W2-5):** S36 Art. 21 still pays bimonthly, so both stay bimonthly. INFONAVIT transcribed; IMSS waits for gap A18 |
| D-16 | Which days are not business days for an IMSS deadline (LFT Arts. 74 / 715 or CFF Art. 12) | G2 owner | Every IMSS movement due date (`DUE_DATE_UNSOURCED`) | Open |
| D-17 | Hourly rate for overtime: daily salary ÷ the LFT Art. 61 working-day length? | G5 owner | Every overtime line (`MX_HOURLY_RATE_RULE_MISSING`) | Open |
| D-18 | FIXED SBC items (LSS Art. 30 I): how a periodic amount becomes a daily SBC amount | G2 owner | Any FIXED SBC item other than the salary (`MX_SBC_FIXED_RULE_MISSING`) | Open |
| D-19 | Fixed salary days (e.g. 15 a fortnight) when employment ends inside the period | G5 owner | That final period (`MX_SALARY_DAYS_PARTIAL_PERIOD`) | Open |
| D-07 | Unit of the LISR Art. 93 exempt limits (and, D-07b, of the LFT Art. 486 seniority-premium cap): UMA or the zone minimum wage | G1 owner (D-07b: G5) | Every special payment (`MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED`); every seniority premium (`MX_SENIORITY_PREMIUM_WAGE_REFERENCE_UNDECIDED`) | Open |
| D-08 | Withholding method for a special payment paid in its own run | G1 owner | Aguinaldo and PTU runs (`MX_SPECIAL_PAY_METHOD_UNDECIDED`) | Open |
| D-09 | Monthly ordinary income from a daily salary (LISR Arts. 95, 96; RLISR Art. 174) | G1 owner | RLISR 174 withholding and separation withholding (`MX_MONTHLY_ORDINARY_INCOME_UNDECIDED`) | Open |

---

## D-01 · Monetary rounding rule (`mx_rounding_rule`)

- **Question.** How is each monetary amount rounded (mode and quantum), and when (each line, or only totals)?
- **Options.**
  1. 2 decimals, rounded at the end of the calculation (CFDI sources), with a tie-breaking rule chosen by the owner (HALF_UP or HALF_EVEN): none of the sources states one.
  2. Whole pesos, 1–50 centavos down and 51–99 up (CFF Art. 20 ¶10, **now saved as S35, PDF p. 31**). That paragraph governs **paying** a contribution to the authority, not a payslip line.
- **Sources.** S30 catCFDI c_Moneda (MXN: 2 decimals); S30 Anexo 20 p. 71 and Guía de llenado Q37/Q39 ("redondear al final del cálculo y no antes"); S30 `tdCFDI.xsd` / S28 `nomina12.xsd` (`t_ImporteMXN`, 2 decimals); CFF Art. 20 ¶10 (S35, PDF p. 31: "Para determinar las contribuciones se considerarán, inclusive, las fracciones del peso. No obstante lo anterior, para efectuar su pago, …"). Detail: `MEXICO_TRANSCRIPTION_BATCH_2_REPORT.md` §4.
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
| Aguinaldo exemption assumes "se otorguen en forma general" holds (the statutory aguinaldo is general by law) | LISR Art. 93 XIV condition (blind transcription) | S24 Art. 93 XIV | G1 |
| Separation exemption split pro rata across the three CFDI kinds | LISR Art. 93 XIII gives one cap for every separation payment; the split per kind is an engineering allocation (the total exempt is unchanged) (TL-SP-1) | S24 Art. 93 XIII | G1 |
| Aguinaldo fraction = days employed in the year ÷ days in the year (365 / 366) | "la parte proporcional … conforme al tiempo que hubieren trabajado" (TL-SP-3) | S26 Art. 87 | G5 |
| "Tres meses de salario" = 90 days; "un mes" = 30 days | LFT Art. 89 ¶3 converts a monthly salary to daily by ÷ 30 (TL-TER-1) | S26 Arts. 48, 50, 54, 89 | G5 |
| "Trabajadores de planta" = indefinite contract (c_TipoContrato 01) | Art. 162 grants the premium to "trabajadores de planta" (TL-TER-1) | S26 Art. 162; S28 c_TipoContrato | G5 |
| Untaken vacation of completed years is paid at termination | The LFT does not say so outright; Art. 79 ¶2 covers only the part year (TL-TER-2) | S26 Arts. 76, 79 | G5 |
| Art. 162 IV deferral (more than 10% leaving voluntarily in a year) not modelled: premium paid at separation | Art. 162 IV a) (TL-TER-1) | S26 Art. 162 IV | G5 |
| PTU days = days paid in committed ordinary and correction runs | Art. 123 "días trabajados"; Art. 127 IV counts maternity and work-risk incapacity as active (TL-PTU-1) | S26 Arts. 123, 127 IV | G5 |
| PTU three months = 90 × the year's average cash daily rate | Art. 127 VIII "tres meses del salario"; Art. 124 salary (TL-PTU-1) | S26 Arts. 124, 127 VIII | G5 |
| Annual adjustment: the $400,000 test on gross income | Art. 97 b) "ingresos anuales" (TL-ANN-1) | S24 Art. 97 b) | G1 |
| Annual adjustment: subtract the subsidy computed each period ("le correspondió"), not only the applied part | S3 Art. Tercero I (TL-ANN-1) | S3 (01-05-2024) | G1 |
| Subsidy monthly cap applies to the month's payments together | S3 Art. Segundo ¶4 "no podrá exceder el monto mensual máximo" (TL-SUB-3) | S3 (31-12-2025) | G1 |
| Rest-day work = 2 daily salaries on top of the rest day's own salary | LFT Arts. 73, 75 "independientemente del salario que les corresponda por el descanso obligatorio, un salario doble" (TL-LFT-2) | S26 Arts. 73, 75 | G5 |
| LSS Art. 31: fewer than 8 absence days counted per period; a sick-leave attendance row treated as IMSS-certified incapacity; the INFONAVIT "aviso oportuno" assumed given | Art. 31 I, IV; the attendance rows hold no certificate (TL-IMSS-4) | S10 Art. 31; S27 Art. 29 | G2 |
| LISR Art. 96 ¶1 (no withholding at the minimum wage) tested per payslip, on the actual zone wage | Art. 96 ¶1 "en el mes únicamente perciban un salario mínimo general" (TL-ISR-3) | S24 Art. 96 | G1 |
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

## D-07 · Unit of the LISR Art. 93 exempt limits

- **Question.** Art. 93 XIII (separation: 90 per year of service) and XIV (aguinaldo 30, vacation premium 15, PTU 15) count their limits in "salario mínimo general del área geográfica". Is that (a) the **UMA**, because S34 Transitorio Tercero reads every mention of the minimum wage "como unidad de cuenta, índice, base, medida o referencia para determinar la cuantía de las obligaciones" as the UMA, or (b) the worker's **zone minimum wage**, as the text says (RLISR Art. 167: the zone of the place of work, unless the worker asks in writing for that of their home)?
- **What weighs on it.**
  - The LISR does use "Unidad de Medida y Actualización" in articles reformed after 2016 (for example the agricultural regime), but not in Art. 93.
  - The two readings differ by about 2.7× (UMA 117.31 against the general minimum wage of 315.04 in 2026; 440.87 in the ZLFN).
  - No saved SAT source (RMF 2026, the payroll guide) states which applies.
- **Sources.** S24 Art. 93 XIII, XIV (pp. 122–123); S34 Transitorio Tercero (p. 2); S25 Art. 167 (p. 44). Log TL-SP-1.
- **Blocks.** Every special payment's exempt part: `MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED`. One switch (`mexico_rules.MX_EXEMPTION_WAGE_REFERENCE`); both readings are tested.
- **Same question elsewhere.** LFT Arts. 485–486 (the seniority-premium salary floor and cap, W1-3b) and Art. 93 I also word their limits in the minimum wage.

## D-08 · Withholding method for a special payment in its own run

- **Question.** For aguinaldo and PTU paid in their own run, does the employer withhold (a) under **RLISR Art. 174** (an option the payer "podrá" take: Art. 96 ¶3), or (b) under the Art. 96 default (the monthly tariff on all the month's income)?
- **State.** (a) is built and tested. (b) needs the month-to-date ordinary income inside a special run, which special runs do not carry today (engineering follow-up, if chosen). Arguably a per-employer option; today it is one switch.
- **Sources.** S24 Art. 96 ¶2–3 (p. 130); S25 Art. 174 (pp. 45–46). Log TL-SP-2.
- **Blocks.** Aguinaldo and PTU runs: `MX_SPECIAL_PAY_METHOD_UNDECIDED`.

## D-09 · Monthly ordinary income from a daily salary

- **Question.** LISR Arts. 95 and 96 use the "último sueldo mensual ordinario" (separation withholding), and RLISR Art. 174 II "el ingreso ordinario … que perciba el trabajador en forma regular en el mes". Neither says how to derive it from a daily salary: × 30, × 30.4, or the month's actual ordinary pay?
- **What weighs on it.** RLISR Art. 174 I (and Art. 163 I, for back pay over several months) uses 30.4 (for the special payment, not for ordinary income). LFT Art. 89 ¶3 divides a monthly salary by 30 (for indemnities, a different law).
- **Blocks.** RLISR 174 withholding and the separation withholding: `MX_MONTHLY_ORDINARY_INCOME_UNDECIDED`.

## D-11 · Termination reasons outside the catalog

- **Question.** Should the catalog carry (a) mutual consent (LFT Art. 53 I), (b) death (Art. 53 II: the seniority premium is paid to the Art. 501 beneficiaries, a different payee on the receipt), (c) Art. 434 terminations? If so, with which components?
- **Sources.** S26 Arts. 53, 162 III, V, 434, 501. Log TL-TER-1.
- **Blocks.** Recording such a termination: `MX_TERMINATION_REASON_UNKNOWN`.
- **Also for the owner.** LFT Art. 47 presumes a separation unjustified without the written notice of the cause: confirm that the evidence a `LFT_47_RESCISSION_BY_EMPLOYER` record requires must be that notice.

## D-12 · Indemnity salary (LFT Art. 89; gap C4)

- **Question.** Art. 89 counts indemnities on "la cuota diaria y la parte proporcional de las prestaciones mencionadas en el artículo 84" (Art. 84: cash, gratificaciones, habitación, primas, comisiones, prestaciones en especie, …). Is it (a) the daily salary × the labour policy's integration factor (aguinaldo, vacation premium: built), (b) the IMSS SBC, or (c) something an operator enters per worker with evidence? For variable pay, Art. 89 ¶2 uses the average of the last 30 days worked, which the engine does not compute.
- **Blocks.** Every Art. 48, 50 and 54 amount: `MX_INDEMNITY_SALARY_UNDECIDED`. The same choice settles C4 (the CFDI `SalarioDiarioIntegrado`).

## D-13 · Part years of service

- **Question.** LFT Arts. 50 ("veinte días … por cada uno de los años"), 54 and 162 ("doce días … por cada año de servicios") do not say how a part year counts: pro rata, or whole years only? (LISR Art. 93 XIII does say it: more than six months counts as a year; that rule is for the exemption only.)
- **Blocks.** Those amounts: `MX_SERVICE_YEARS_COUNT_UNDECIDED`. Both options are built.

## D-14 · PTU cap (LFT Art. 127 VIII)

- **Question.** (a) Where does the part of a share above the cap ("tres meses del salario del trabajador o el promedio de la participación recibida en los últimos tres años … el monto que resulte más favorable") go: kept undistributed, or shared among the others? (b) For a worker with fewer than three years of PTU, is the average ÷ 3 or ÷ the years received?
- **State.** (a) "UNDISTRIBUTED" (residue) is built; (b) both are built. Each blocks only an allocation where it changes the result.
- **Sources.** S26 Art. 127 VIII (p. 32). Log TL-PTU-1.
- **Blocks.** `MX_PTU_CAP_EXCESS_UNDECIDED`, `MX_PTU_HISTORY_AVERAGE_UNDECIDED`.

## D-15 · INFONAVIT and RCV payment periodicity

- **Found in the blind transcription:** the 1997 LSS Transitorio VIGÉSIMO SÉPTIMO (S10 p. 111): RCV quotas are paid "en forma bimestral, hasta en tanto no se homologuen los períodos de pago de las Leyes del ISSSTE e INFONAVIT". Both bimonthly rules end on the same unsaved condition. `MX_IMSS` is therefore not in the calendar either.
- **Question.** Ley INFONAVIT Art. 35 says "por mensualidades vencidas, a más tardar los días diecisiete del mes inmediato siguiente". The 1997 decree's Transitorio SEXTO keeps it "de forma bimestral hasta que en la Ley del Instituto de Seguridad y Servicios Sociales de los Trabajadores del Estado se establezca que la periodicidad de pagos se realizará mensualmente". Has that condition been met? And do retiro and CEAV (LSS) follow the monthly Art. 39 or a bimonthly cycle (Art. 184 speaks of "la cuota correspondiente al bimestre")?
- **Needs.** The ISSSTE law (not saved; a W2-5 source to find), or an owner's decision on the operating practice.
- **Blocks.** INFONAVIT and IMSS due dates (neither is in `MX_FILING_CALENDAR`). Engineering option once decided: split the RCV branches into their own liability with a bimonthly rule, and date the other IMSS branches monthly (LSS Art. 39).

## D-16 · Business days for IMSS deadlines

- **Question.** LSS Art. 15 I gives "cinco días hábiles" but does not define them. LSS Art. 9 fills gaps with the LFT first, then the CFF. Which list applies: LFT Arts. 74 / 715 (rest days, official holidays, days labour authorities suspend work) or CFF Art. 12 (adds 5 May; excludes the fiscal authorities' general vacations)?
- **The 2026 dates** are worked out in TL-CAL-3. They differ only on 5 May, plus days no saved source dates (election days, official-calendar holidays, authority vacations).
- **Blocks.** `MX_OFFICIAL_HOLIDAYS` stays empty, so every movement is `DUE_DATE_UNSOURCED`.

## D-17 · Hourly rate for overtime

- **Question.** LFT Arts. 66–68 pay overtime as a multiple of "las horas ordinarias", and Art. 61 sets the working-day length (8 day, 7 night, 7.5 mixed). Neither says how the hourly rate is derived from the daily salary. Is it the daily salary ÷ that length (built: `DAILY_SALARY_OVER_JORNADA_HOURS`), ÷ the weekly hours ÷ days, or the employer's own figure?
- **Blocks.** Every overtime line: `MX_HOURLY_RATE_RULE_MISSING`. The Art. 61 lengths are transcribed (TL-LFT-3).

## D-18 · FIXED SBC items

- **Question.** LSS Art. 30 I: fixed periodic payments "de cuantía previamente conocida … se sumarán a dichos elementos fijos". How is a periodic amount (e.g. a monthly bonus) turned into a daily SBC amount: ÷ the period's days, or annualised ÷ 365?
- **Blocks.** An earning classified FIXED for the SBC other than the salary: `MX_SBC_FIXED_RULE_MISSING`. Interface: `MX_SBC_FIXED_INTEGRATION_RULE.daily_amount(line, facts)`.

## D-19 · Fixed salary days at termination

- **Question.** When the employer's labour policy pays fixed salary days (e.g. 15 a fortnight, 30 a month) and employment ends inside the period, how many days are paid? (The LFT does not say; it is a pay convention.)
- **Blocks.** That final period: `MX_SALARY_DAYS_PARTIAL_PERIOD`. Interface: `MX_FIXED_DAYS_TERMINATION_RULE.days_paid(tariff, period_start, period_end, termination_date)`.
