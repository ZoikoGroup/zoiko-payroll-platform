# Mexico (MX) — Transcription Batch 2 Report, with the subsidy-decree, S22 and rounding findings

Requested 2026-10-26 after the Batch 1 review. This report covers:
1. The 01 Diario decision, recorded.
2. The 2024 subsidy decrees: what they say on the excess over ISR and on CFDI reporting.
3. S22: the transitory-article search, the Gaceta fetch and the spot-check.
4. Rounding-rule candidates (research only; nothing decided).
5. Batch 2 transcription: IMSS and the SBC ceiling, CEAV 2023–2030, INFONAVIT, minimum wages and ZLFN, benefit floors and vacations, working week and overtime.

> **Rugvedh (ZP-PRIV) review:** not required by rule 7. There is no change to authz, redaction, RLS, migrations or cross-tenant data.

**Base.**
- `nikhil` = `a0da835`. 11d, Batch A and Batch 1 are staged, not committed.
- Production should be at `b9f3d5a1c7e2`. Mexico is dormant.

**No migration, no new route, no frontend change.**

## 1. Result

| Item | Result |
|---|---|
| 01 Diario | Stays blocked. Recorded in the G1 checklist as a decision for the payroll specialist |
| 2024 subsidy decrees | Both saved as S3 files (`ARCHIVE_COPY_VERIFIED`). (a) The excess over ISR is **neither carried forward nor paid** (base decree, Art. Segundo ¶2, still in force). (b) **Neither decree says how the subsidy is reported on the CFDI** (§2) |
| Subsidy remainder rule | **Transcribed:** `NOT_PAYABLE`, from Art. Segundo ¶2 of the base decree |
| S22 | **Both checks passed; it is now S22, and VERIFIED.** The latest reform the SAF edition names is the Gaceta of 19-12-2025. That issue was found in the Internet Archive, saved, and spot-checked on 3 amended articles. The SAF file then passed `verify` (fresh direct download, MATCH logged) (§3) |
| Rounding | **Research only; nothing decided.** Five candidate sources are quoted in §4 for the G1 owner |
| Batch 2 | 27 scalar rows (counting the remainder rule), 124 minimum-wage rows, 45 ZLFN municipalities, 64 CEAV bands, 5 working-week rows and 14 vacation rows. Every row is `[PENDING G1]` and cites `CODE/file` |
| Blind second transcription | **0 value differences** across every Batch 2 table. One representational difference: the upper bound of CEAV band 1 (TL-CEAV-1) |
| Machine extraction | `compare`: **343 rows checked, 0 misses.** 56 CEAV cells are in an image table (§5.2) |
| Spec versus source | Every value matches. The differences are where values come from (derived, SM versus UMA) and what the spec leaves out (§5.7) |
| Full suite | §7 |

## 2. The 2024 subsidy decrees

| File | Official URL | Capture | Stated |
|---|---|---|---|
| `S3_DOF_Decreto_subsidio_empleo_01052024.html` | `dof.gob.mx/nota_detalle.php?codigo=5725287&fecha=01/05/2024` | 20240502200731, digest OK | "DECRETO que otorga el subsidio para el empleo", DOF 01/05/2024, in force 1 May 2024 |
| `S3_DOF_Decreto_subsidio_empleo_31122024.html` | `dof.gob.mx/nota_detalle.php?codigo=5746529&fecha=31/12/2024` | 20250105140823, digest OK | "DECRETO por el que se modifica el diverso…", DOF 31/12/2024 (Vespertina), in force 1 Jan 2025 |

The codigos were found through the archive's DOF indexes and confirmed by page title; none comes from memory. A second candidate dated 1 May 2024 (5725285, the Fondo de Pensiones decree) was rejected.

**(a) The subsidy exceeding the ISR**
- **Base decree, Art. Segundo ¶2:** "En los casos en que el impuesto a cargo del trabajador sea menor que el subsidio para el empleo mensual obtenido conforme a este artículo, la diferencia no podrá aplicarse contra el impuesto que resulte a su cargo posteriormente, ni se entregará cantidad alguna por concepto del subsidio para el empleo establecido en este artículo."
- **It is still in force.** The 31-12-2024 and 31-12-2025 decrees each reform only ¶¶1, 3, 4, 5 and print ¶2 as "…". I read this in the saved files myself.
- **Transcribed** as `mx_subsidy_remainder_rule` = `NOT_PAYABLE` (log TL-SUB-2).
- **Related:** Art. Tercero III (the annual calculation) also says no amount is delivered.

**(b) How the subsidy is reported on the CFDI (gap C6)**
- **The decrees say nothing on it.** The base decree's only mention is the employer's "comprobantes fiscales". The 31-12-2024 decree has no mention at all.
- **Where the CFDI rules actually sit (context, not from the decrees):**
  - **S4 (the 2023 payroll guide, still framed on the 2013 decree):**
    - p. 66: OtrosPagos with TipoOtroPago 002, or TipoDeduccion 071 when more subsidy was delivered than was due.
    - p. 67: when 002 is used, the `SubsidioAlEmpleo` node is required.
    - p. 70: SubsidioCausado "conforme a la tabla… del Anexo 8".
  - **S1 (RMF 2026), p. 452:** rule 3.17.13 says the subsidy is not creditable "cuando, no se haya anotado el monto… de manera expresa y por separado en los comprobantes fiscales de nómina". It too is framed on the 2013 decree.
- **So C6 stays open:** SAT's current CFDI instructions for the 2024-decree subsidy still need to be saved.

## 3. S22: becomes S22, and VERIFIED

**Search.** The SAF "CÓDIGO FISCAL 2026" carries each amending decree's transitory articles. The latest it names is: "Decreto por el que se reforman, adicionan y derogan diversas disposiciones del Código Fiscal de la Ciudad de México, publicado en la Gaceta Oficial de la Ciudad de México el **19 de diciembre de 2025**". It sits on PDF p. 482, with Artículo Primero: "entrará en vigor el 1º de enero de 2026".

**Fetch.** The Consejería Jurídica site doesn't answer from this network. I scanned all 79 Gaceta PDFs the archive captured on that site from 19 Dec 2025 onward, checking each against its digest. One is **Gaceta Oficial No. 1762, Tomo II, 19 de diciembre de 2025**, carrying the decree:
- Capture 20261014035515, SHA-1 digest OK, 55,878,339 bytes.
- Saved as `S22_GOCDMX_Gaceta_19122025_No1762.pdf`, status `ARCHIVE_COPY_VERIFIED`.
- The archived URL has a referrer query appended; the recorded URL is the official path.

**What the decree changes.** Its ÚNICO article reforms mostly fees ("en sus cuotas") and adds fractions to Arts. 73, 76, 77 and 219. **It does not touch Art. 158** (ISN).

**Spot-check against the SAF consolidated edition:**

| Article | Gaceta 19-12-2025 | SAF "CÓDIGO FISCAL 2026" |
|---|---|---|
| 58 II and VII (thresholds) | $38,707,156.00; $14,913,178.00 | Both present |
| 77 I, III, IV (reformed) and V (added) | Text of each fraction | Identical wording |
| 177 (value) | $1,366,042.00 | Present |

**Result:**
- **Both checks passed.** Check 1 (Art. 158 reads 4%, PDF p. 91) passed earlier.
- **S22 is now the SAF edition.**
- **It is VERIFIED.** Because it was a direct download, I ran `verify_mexico_sources.py verify S22 file=S22_SAF_Codigo_Fiscal_CDMX_2026.pdf`. It downloaded the official URL afresh (HTTP 200, 58,814,901 bytes), the SHA-256 matched the saved copy, and a MATCH row is logged in `VERIFICATION_LOG.csv`. **This is the first VERIFIED Mexico source.**
- **The old row** (`S22_CDMX_Codigo_Fiscal_2026.pdf`) stays `WRONG_VERSION`.
- **No ISN value is transcribed yet.** That's a later batch.

## 4. Rounding rule (`mx_rounding_rule`): candidates for the G1 owner

Nothing decided. Each quote was checked in the saved file; the c_Moneda and CFF ones I re-read myself.

| # | Source | What it says |
|---|---|---|
| 1 | **S30 catCFDI.xls, sheet c_Moneda** (CFDI 4.0, catalog v1.0 r1.0, in force 2022-01-01) | MXN: **2 decimals** ("Decimales" = 2), "Porcentaje variación" 5 |
| 2 | **S30 Anexo 20 standard** (DOF 13-01-2022), p. 71, Moneda | For TipoDeComprobante "N" the currency is MXN; amounts "deben ser redondeados hasta esa cantidad de decimales". Pp. 76–78: validation bounds truncate the lower bound and round up the upper bound (924.224956 gives 924.22 / 924.23) |
| 3 | **S30 Anexo 20 Guía de llenado** (file dated 2026-01-16) | Q37 (p. 88): concepts may carry up to 6 decimals, "en los totales se debe redondear al final del cálculo… al número de decimales que soporta la moneda". Q39 (p. 90): "Redondear al final del cálculo y no antes". **No tie-breaking rule (what happens at exactly .5) is stated** |
| 4 | **CFF Art. 20 ¶10** (Diputados consolidated text, last reform DOF 09-04-2026, capture 20261006134049, digest OK; **not saved as a source**) | "Para determinar las contribuciones se considerarán, inclusive, las fracciones del peso. No obstante lo anterior, para efectuar su pago, el monto se ajustará para que las que contengan cantidades que incluyan de 1 hasta 50 centavos se ajusten a la unidad inmediata anterior y las que contengan cantidades de 51 a 99 centavos, se ajusten a la unidad inmediata superior." (PDF p. 31). This governs **paying** a contribution to the authority, not a worker's payslip lines. Art. 17-A (p. 17) adds: factors and proportions "hasta el diezmilésimo" |
| 5 | **Schemas** S30 `tdCFDI.xsd` / S28 `nomina12.xsd` | `t_ImporteMXN` allows up to 2 decimals; 31 Nómina attributes use it |

**Nothing found in:**
- **S2 (Anexo 8), S3 and S1 (RMF 2026):** no payroll ISR or subsidy rounding provision. RMF p. 547 refers only to CFF 17-A factors.
- **S10 (LSS):** no rounding provision for IMSS contributions.
- **S4:** two-decimal examples only, plus field-specific rules (NumDiasPagados up to 3 decimals; HorasExtra fractions rounded; NumAñosServicio more than 6 months rounds up).

**The decision the G1 owner faces:**
- **The CFDI sources** give 2 decimals and "round at the end", but no tie-breaking rule.
- **CFF Art. 20** gives whole pesos with 50 centavos rounding down, but only for payments to the authority.
- **Saving the CFF:** if it is to back the rule, save it as a source.

## 5. Batch 2 transcription

The detail is in `MEXICO_PHASE_1_TRANSCRIPTION_LOG.md`, entries TL-IMSS-1 to TL-SUB-2.

### 5.1 IMSS and the SBC ceiling (S10, B4)

Printed in words and read as numbers:
- **Pensioner medical (Art. 25):** 1.05 employer / 0.375 worker.
- **Invalidez y Vida (Art. 147):** 1.75 / 0.625.
- **Guarderías (Art. 211):** 1.
- **Retiro (Art. 168 I):** 2.
- **CEAV worker (Art. 168 II b):** 1.125.
- **SBC ceiling (Art. 28):** 25×.
- **E&M excess threshold (Art. 106 II):** 3×.
- **Work-risk premium (Art. 74):** minimum 0.5, maximum 15.

**Derived (no source prints the 2026 figure), TL-IMSS-2:**
- **E&M fixed quota 20.40:** 13.9 + 10 × 0.65.
- **E&M excess 1.10 / 0.40:** 6 − 10 × 0.49 and 2 − 10 × 0.16 (Art. 106 plus the 1995 Transitorio DECIMO NOVENO).
- **Cash benefits 0.70 / 0.25:** the 1% Art. 107 quota × 70% / 25%.
- **Tests:** each is rebuilt from its printed components.

**Open (TL-IMSS-3):** Arts. 28 and 106 say "salario mínimo… del Distrito Federal". Reading that as the UMA comes from the de-indexation decree, DOF 27-01-2016, Transitorio Tercero. I found it (Diputados copy `CPEUM_ref_226_27ene16.pdf`, capture 20160222060026, digest OK) but **did not add it to the register**: that is your decision (proposed S34).

### 5.2 CEAV 2023–2030 (S11, B5)

- **The table is a scanned image** on PDF p. 7, with no text layer. Both transcriptions read it by eye: **64/64 values identical.**
- **Checks:**
  - The 2030 column equals S10 Art. 168's text table (`compare` 8/8 plus a test).
  - Each band rises in near-equal annual steps (tested).
  - The 2026 bands match spec §9.
- **One representational choice:** band 1 is printed "1.0 SM" as a single point. I store its upper bound as 1.0 SM so the engine can't treat it as open-ended. The band is already `[PENDING G2]`.

### 5.3 INFONAVIT (S27, B9)

Employer 5% (Art. 29 II). The credit bases are not in Art. 29 and stay untranscribed.

### 5.4 Minimum wages and ZLFN (S9, B6)

- **Zones:** GENERAL 315.04 and ZLFN 440.87, from 1 Jan 2026.
- **Professions:** 61, each with a ZLFN and a general-zone amount (122 rows).
- **ZLFN municipalities:** 45. Tijuana now resolves to ZLFN and Guadalajara to GENERAL (tested).
- **Resolutivo SEXTO** (ZLFN never below the general zone) holds for every profession.
- **Blind and machine checks:** 0 differences, all found.

### 5.5 Benefit floors and vacations (S26, B8)

- **Floors:** aguinaldo 15 days (Art. 87), vacation premium 25% (Art. 80), Sunday premium 25% (Art. 71, reformed DOF 01-05-2026).
- **Vacations are DERIVED from Art. 76's wording** (no table is printed): years 1–5 give 12/14/16/18/20, then +2 per 5-year band to years 46–50 (TL-VAC-1).
- **Beyond 50 years** of service, no row exists and the case blocks.

### 5.6 Working week and overtime (S18, B7)

- **Phase-in from the transitory articles:**
  - Ordinary week (Segundo): **48/46/44/42/40** for 2026–2030.
  - Overtime hours at the first tier (Cuarto): **9/9/10/11/12**.
- **Premiums:** Art. 66 "cien por ciento más" and Art. 68 "doscientos por ciento más" are read as ×2 and ×3 (DERIVED, TL-WW-2).
- **Cross-check against S26:** the consolidated LFT shows the end state (40 h; 12 h overtime a week) and reproduces the same transitory articles (PDF p. 454). There's no conflict.

### 5.7 Every difference from the spec

| Area | Spec | Source | Effect |
|---|---|---|---|
| Working week 48/46/44/42/40 | As stated | S18 Transitorio Segundo: same | **None** |
| Overtime phase-in | Only "9 weekly overtime hours" in 2026 | S18 Transitorio Cuarto: 9/9/10/11/12 | Source values transcribed. The spec doesn't list 2027–2030 |
| 48 h "operative for 2026" | Whole of 2026 | S18 says 2026: 48 "a partir del 1 de enero", but the decree is in force only from 1 May 2026 | The January–April row cites a transitory article published later. **G1 to confirm** |
| Second overtime tier | Not mentioned | S18 Art. 68: at most 4 h a week beyond the Art. 66 limit, at "doscientos por ciento más" | Recorded in `overtime_rules`; the engine doesn't enforce the 4 h cap |
| E&M 20.40 / 1.10 / 0.40; cash benefits 0.70 / 0.25 | Stated as rates | Not printed; derived from base plus steps or shares | Same values; derived |
| SBC ceiling and E&M threshold in UMA | "25 UMA", "3 UMA" | LSS says minimum wage (DF); the UMA reading rests on the 2016 decree (not saved) | Same multiples; source decision open |
| CEAV band 1 | "1.00 minimum wage" | S11 "1.0 SM*" (LSS "1.00 SM*") | Format only |
| All other Batch 2 values | — | — | **No difference** |

## 6. Machine extraction and tests

**`verify_mexico_sources.py`:**
- `numbers_in` now reads Spanish number words ("uno punto cero cinco", "sesenta y cinco centésimas", "por ciento" not read as 100, "un cien" not read as 101).
- `compare` checks DERIVED rows through their printed components, CEAV through the 2030 cross-check (the image cells are counted, not missed), and ZLFN municipality names. HTML entities are decoded first.

**`test_mexico_content.py`, new tests:**
- derived values rebuilt from their components;
- the vacation rule;
- CEAV shape and steps;
- the CEAV 2030 column against Art. 168 (skipped where the binaries aren't checked out);
- minimum wages and SEXTO;
- ZLFN membership;
- the overtime phase-in against the working-week rows;
- the remainder rule's vocabulary.

**`test_mexico_source_tool.py`, new test:** Spanish number words.

**Tests updated because the real tables are no longer empty:**
- **Synthetic-only fixtures** empty every content table: seed, router, approval, and the activation-gate synthetic pack.
- **"While content is empty" tests empty S9 explicitly:** employee and employer readiness, and IMSS registrations. The IMSS-registration test now also proves that the real S9 list resolves Tijuana and Guerrero (Tamaulipas) to ZLFN.
- **Real-pack counts** are computed from the content instead of being hard-coded.
- **The skeleton test** pins the five keys still missing: rounding, SBC floor, the two INFONAVIT bases, and the CEAV lowest-band reference (G2).

## 7. Full suite

Run 2026-10-26 on SQLite, in five sequential chunks, alone.

| Chunk | Result |
|---|---|
| 0 | 866 passed, 15 skipped, **4 failed**. Three are the known local-only `test_route_registry.py` tests (your uncommitted `/health` routes). The fourth is `test_communications_dispatch.py::test_deactivate_organization_response_precedes_email_send`, which is **intermittent and unrelated**: alone it passed 4/4 times, and three runs of its whole file gave pass, pass, fail. Nothing in this change touches communications |
| 1 | 2283 passed, 1 skipped, 2 xfailed, **1 failed**: the known local-only HK docs test |
| 2 | 1501 passed, 29 skipped, 0 failed |
| 3 | 1736 passed, 69 skipped, 0 failed |
| 4 | 1059 passed, 6 skipped, 0 failed |

**Total: 7445 passed, 120 skipped, 2 xfailed.** The failures are the 4 known local-only ones plus one intermittent communications test. Every Mexico test passes in the suite.

## 8. Decisions needed

1. **Rounding rule:** the G1 owner chooses from §4. Nothing calculates until then.
2. **De-indexation decree (DOF 27-01-2016):** save it as **S34**? The UMA reading of the LSS SBC ceiling and the E&M threshold rests on it.
3. **CFF (consolidated, DOF 09-04-2026):** save it as a source, if Art. 20 is to back the rounding rule.
4. **Interpretations for G1:**
   - The derived E&M rates and cash-benefit shares.
   - Overtime ×2 / ×3.
   - The CEAV band-1 upper bound.
   - The vacation bands (from year 6, to year 50).
   - The working-week row for January–April 2026.
   - Remainder = NOT_PAYABLE.
5. **CFDI subsidy reporting (C6):** SAT's current instructions still need to be found and saved.

## 9. Production effect

| Area | Effect when merged |
|---|---|
| Database / Alembic | **None.** No migration |
| Mexico in production | Stays dormant. **No deploy runs the seed.** If someone ran it by hand, Batch 1–2 rows would land in the **Draft** pack only. Approval and activation stay refused: content still lacks the rounding and SBC-floor rules, and the national sources are archive copies |
| ZLFN zone in the employer view | `min_wage_zone` now resolves from the transcribed S9 list: an establishment in a listed municipality shows ZLFN, any other shows GENERAL. Before, every establishment showed UNRESOLVED. It is visible only to Mexico organisations, which are behind the dormancy flag |
| Super Admin readiness view | The content check compares packs with the Batch 1–2 rows |
| `VERIFICATION_LOG.csv` | One MATCH entry (S22, the SAF edition) |
| Other jurisdictions | **None.** Every edit is in Mexico-only modules, scripts, tests and docs (§7) |
| Identifiers | Not touched |

## 10. Staged

- **Code:** `mexico_content.py` and `verify_mexico_sources.py`.
- **Tests:**
  - New content and source-tool tests: `test_mexico_content.py`, `test_mexico_source_tool.py`.
  - Fixtures for real content: `test_mexico_seed.py`, `test_mexico_router.py`, `test_mexico_approval.py`, `test_mexico_activation_gates.py`, `test_mexico_employee_readiness.py`, `test_mexico_employer_readiness.py`, `test_mexico_imss_registrations.py`, `test_mexico_engine_content.py`, `test_mexico_scaffolding.py`.
- **Docs:**
  - `SOURCES_MANIFEST.csv`: +2 S3 decrees and +1 S22 Gaceta; the SAF row promoted to S22 and VERIFIED.
  - `VERIFICATION_LOG.csv`: the S22 MATCH entry.
  - `MEXICO_PHASE_1_TRANSCRIPTION_LOG.md`: the Batch 2 entries.
  - `release-gates/G1/CHECKLIST.md`: 01 Diario and rounding.
  - `MEXICO_COMPLETION_GAP_REGISTER.md`: progress.
  - This report.
- **Not staged:** the source binaries (untracked) and your own files. Nothing is committed or pushed.

**Next:** Phase 12a, after your review.
