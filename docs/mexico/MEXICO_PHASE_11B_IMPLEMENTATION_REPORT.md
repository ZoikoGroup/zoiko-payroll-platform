# Mexico (MX) — Phase 11b Implementation Report: the CFDI 4.0 + Nómina 1.2 builder

Requested 2026-10-23, with six conditions. Covers sub-phase **11b** of `MEXICO_PHASE_11_PLAN.md`: X1, the builder, and X2, XSD validation, plus the separation engine gap. 11c (the validate-only preview) is not started.

> **Do not merge before Rugvedh's review (ZP-PRIV).** 11b is the first code that reads the raw RFC / CURP / NSS out of `compliance_fields` and writes them into a document (§6). It also surfaced a platform-wide finding for him: payslips keep a plaintext copy of every employee's identifiers (§6).

**Base and production.**
- **PR #127 (11a) was merged into `main` at 08:33Z, with no review on the PR.** It was described to me as open for Rugvedh's review. That merge deployed 11a (migration `a8e4c1f7d3b5`); the deploy result is in `PRODUCTION_STATE.md` and §9.
- `nikhil` = `29f2b5c` (11a).

**Alembic.** Unchanged: a single head, `a8e4c1f7d3b5` (221 revisions). **11b adds no migration.**

**Git.** **Staged on `nikhil`, not committed.**

## 1. Result

| Check | Result |
|---|---|
| Full backend suite | **7,212 passed**, with the same 4 local-only failures, none Mexico (§8) |
| 11b tests | `test_mexico_cfdi_builder.py`: 25 passed |
| Separation tests | `test_mexico_termination.py` and the orchestrator tests: 44 passed, including 3 new |
| Phase 7 CFDI tests | 57 passed. Two were changed on purpose: the real builder no longer refuses outright (§9) |
| Golden vector (S4 pp. 111–114) | Rebuilt node by node. **SAT's own example breaks two of SAT's own rules** (§4) |
| XSD validation | Against the pinned CFDI 4.0 + Nómina 1.2 schemas together, offline (a socket guard proves no network) |
| Route registry | Dry-run regeneration: no change |
| Browser | None: 11b has no screen (the preview is 11c) |

## 2. The six conditions

| # | Condition | Done |
|---|---|---|
| 1 | G1 item: re-download S4, S28, S30 from sat.gob.mx and confirm the SHA-256 | `release-gates/G1/CHECKLIST.md`: the item, with "a mismatch blocks the gate until the set is rebuilt" |
| 2 | `SUBSIDY_APPLIED` stays unmapped; record that the 2023 guide likely predates the 2024 reform; a new source is needed | Code proposals and G1 checklist. **Evidence it predates the reform:** the guide's legal basis for the subsidy is the 11 December 2013 decree (S4 pp. 25, 68, 70). A receipt with a subsidy is refused (`MX_CFDI_CONCEPT_UNMAPPED`) |
| 3 | Separation into sub-kinds 022 / 023 / 025, tax treatment from content (empty → block), the finiquito emits them | §5 |
| 4 | Golden vector: the worked receipt on S4 pp. 112–114, compared node by node | §4 |
| 5 | Privacy: identifiers in memory only; every lxml message redacted; an invalid-CURP test across DB, events, audit, logs and responses | §6 |
| 6 | Manifest note: the source binaries live in the team evidence store | `SOURCES_MANIFEST.csv`: the note on all 8 archive-copy rows, with **"[location to be provided by the release owner]"**. Please send the location |

## 3. The builder: `mexico_cfdi_xml.py` (pure) and `mexico_cfdi_input.py` (assembly)

**Pure builder.** No database, network or clock. Everything arrives in `document_input` plus the pinned set it names.
- **Every SAT value it writes itself is in one cited table** (`FIXED`; for example `TipoDeComprobante` "N" S4 p. 9, `ClaveProdServ` 84111505 p. 16, `UsoCFDI` CN01 p. 15, `Descripcion` "Pago de nómina" p. 17), and so is every code group the guide names.
  - A test checks every fixed value against its pinned catalog and every code group against the catalog's descriptions. For example, the three separation codes read "Prima por antigüedad", "Pagos por separación", "Indemnizaciones".
  - A static test fails on any SAT-shaped literal outside those tables. It caught one (the seniority format `P…W`), which was moved into the table.
- **Catalog codes are checked against the 4.0 catalog, valid on the issue date.** The XSD alone would accept codes 4.0 dropped. Decimals come from c_Moneda's `Decimales` column.
- **Each S4 rule is a named check that cites its page:** totals (pp. 7, 17, 19, 23–25, 43, 60), the employer registration and its required receiver fields (p. 26), contract type vs regime type (p. 34), periodicity (p. 38), dates (pp. 21, 31), days paid (p. 22), issuer CURP (p. 25), positive amounts (pp. 63, 69), detail nodes (pp. 47–48, 67) and separation (pp. 34–35, 47, 56–59). Every problem is reported at once (`MX_CFDI_RULE_FAILED`).
- **Totals** are computed from the lines and compared with the committed result's own figures (`gross`, `isr_withheld`, `employee_total`, the subsidy and the annual adjustment). A one-centavo difference refuses with `MX_CFDI_TOTALS_MISMATCH`; the builder never adjusts a figure.
- **Validation (X2).** The document is validated against a combined schema importing both pinned main schemas, because `Complemento` validates its content strictly.
  - `Sello`, `NoCertificado` and `Certificado` belong to the signer (X4). The builder never writes them; validation fills them on a throwaway copy only.
  - The `xsi:schemaLocation` pairs come from the pinned manifest. Each namespace is read from its XSD and each location from its official URL in `SOURCES_MANIFEST.csv`.

**What the builder refuses (it does not build these yet):**

| Case | Why |
|---|---|
| Separation perceptions (022 / 023 / 025) | They need TipoRegimen 13 and the `SeparacionIndemnizacion` node (last ordinary monthly salary, accumulable / non-accumulable income, S4 pp. 56–59), which the engine does not produce. The guide's contract-type rule (p. 34) and separation rule (p. 35) also conflict for a separation receipt and must be settled against the PAC's test environment |
| Overtime (019) | `HorasExtra` needs the **days** on which overtime was worked (S4 p. 51); the engine records hours per week only |
| 014, 039, 044, 045 | Their detail nodes (S4 pp. 47–48) |
| Other payment 002 (subsidy) or 004 | `SubsidioAlEmpleo` / `CompensacionSaldosAFavor` (S4 p. 67) |

**Not emitted, by design:**
- Bank details: optional (S4 pp. 38–39), and the builder never writes an account number.
- `Sindicalizado`: no union-membership field exists. S4 p. 33 says to register it; the XSD makes it optional.
- `SalarioBaseCotApor`: optional (S4 p. 39).

**Assembly** (`document_input(db, run, item, release, base)`) reads:
- the employer version and IMSS registration in force on the pay date;
- the employee's profile;
- `compliance_fields` (RFC / CURP / NSS, **in memory only**);
- the release's APPROVED system-concept mappings.

It refuses by name, never by value:

| Refusal | When |
|---|---|
| `MX_CFDI_SCHEMA_SET_UNUSABLE` | The release was not loaded from a verified pinned set |
| `MX_CFDI_INPUT_MISSING` | A needed field is not recorded |
| `MX_CFDI_CONCEPT_UNMAPPED` | A non-zero amount has no APPROVED mapping (the concept is named) |
| `MX_CFDI_TIMEZONE_UNSUPPORTED` | The place of issue's UTC offset changes during the year (§7) |

Other assembly rules:
- **ClaveEntFed** is the c_Estado code: the internal code where SAT uses it, otherwise the c_Estado row with the same name. Only `CDMX` → `CMX` differs.
- **Fecha** is local time at the place of issue, using c_CodigoPostal's offset (S4 p. 6, S30).
- **TipoNomina** is E for aguinaldo, PTU and finiquito runs (S4 p. 20), with periodicity 99 (p. 38).
- **SalarioDiarioIntegrado has no source yet** (§7: a G1 decision), so a receipt with an employer registration is refused until one is recorded.

**Wiring.**
- `CfdiPayloadBuilder.prepare()`: `SatBuilder` runs the assembly; the synthetic test builders keep the old input unchanged.
- The folio is now taken before building, because the receipt carries it.
- The input dict is discarded right after the build.
- `SatBuilder.blocked()` is clear whenever a verified pinned set is installed.

## 4. The golden vector: SAT's worked receipt, S4 pp. 111–114

The receipt is printed as a two-column rendering. Its values were transcribed and decoded with the pinned catalogs (for example "Clase II" → `2`, "SANTANDER" → `014`, "Ciudad de México" → `CMX`). The decoding is cross-checked by the seniority: from 2021-02-01 to 2022-01-15 is 348 days, i.e. `P49W`, as printed.

**SAT's example breaks two of SAT's own rules.** The test keeps the example as printed and asserts both refusals:

| Printed | The rule it breaks | The builder |
|---|---|---|
| Contract type 09 ("Modalidades de contratación donde no existe relación de trabajo") with regime type 02 | S4 p. 34: contract 09+ takes regime 05–99 | Refused, `R-CONTRACT-REGIME (S4 p. 34)` |
| Receiver CURP `LOAV890607HDFTTR1X` | tdCFDI `t_CURP`: the final character is a digit | Refused, `Receptor@Curp: SCHEMAV_CVC_PATTERN_VALID` (no value in the message) |

**The comparison variant** differs only in contract type 01 and the CURP's final character. It builds, validates, and matches **every value p. 114 prints** for the nodes the builder writes:
- comprobante: SubTotal 6000.00, Descuento 1589.70, Total 4410.30, MXN, N, PUE, 06300, Fecha;
- issuer RFC and regime 601;
- receiver RFC, name, postal code, 605, CN01;
- the concept: 84111505, 1, ACT, "Pago de nómina", 6000.00, 1589.70;
- the nómina dates and totals;
- registro patronal;
- NSS, start date, P49W, Sindicalizado No, jornada 01, régimen 02, employee no. 1, Cajero, riesgo 2, periodicidad 04, SDI 233.00, CMX;
- the percepción 001 "Sueldo" 6000.00 / 0.00;
- the three deducciones 001 200.00, 002 591.26 and 101 798.44, with TotalOtrasDeducciones 998.44 and TotalImpuestosRetenidos 591.26.

The builder computed every total itself.

**Not compared:**
- the issuer name (blank on p. 114);
- bank details (§3);
- a CURP printed near the issuer block (the issuer is a persona moral, which has none, S4 p. 25);
- the printed "Total otros pagos 0" (S4 p. 25: the field is omitted when there are none);
- the seal and certificate (X4).

**One more inconsistency inside S4:** p. 50 says ImporteExento "debe ser mayor a cero", but the XSD requires the attribute and SAT's own example writes `0.00`. The builder writes `0.00`.

## 5. Separation: three kinds (condition 3)

- `termination.SEPARATION_KINDS` = `SEPARATION_SENIORITY_PREMIUM`, `SEPARATION_PAYMENT`, `SEPARATION_INDEMNITY`, matching S28 022 / 023 / 025. The SAT codes are not in the engine: they come from the system-concept mappings, which are now unambiguous (proposals doc).
- **The content interface changed:** a termination reason's `separation_components()` must give each component a `kind`. A component without one blocks (`MX_TERMINATION_RULE_INVALID`).
- **Each kind needs its own transcribed tax rule and ISN inclusion.** One missing blocks (`MX_SPECIAL_PAY_RULE_MISSING`). Content is empty, so every finiquito still blocks, as before.
- **The finiquito (9c) emits each component as its own kind**, and the run's separation detail records the kind.
- The special-pay concepts, finiquito run concepts and line kinds now carry the three kinds instead of `SEPARATION`. The system concepts carry the three kinds plus `VACATION_PAYOUT`, which is new and also needs a code.
- Tests: all three emitted with their amounts; a component without a kind blocks; one kind without a rule blocks; the orchestrator blocks each kind without its rule.

## 6. Privacy (condition 5), for Rugvedh

- **Identifiers live only in memory.** The assembly reads RFC / CURP / NSS into the input dict; the builder writes them into the XML; the dict is deleted after the build. The XML goes only to object storage, as in Phase 7, with the durable-storage refusal.
- **No message carries a value.** XSD errors are rebuilt from element, attribute and lxml's error type only, e.g. `Receptor@Curp: SCHEMAV_CVC_PATTERN_VALID`; lxml's own text, which quotes the value, is never used. Rule failures name fields, never values. This doesn't depend on the generic redaction patterns, which a malformed identifier can slip past.
- **The invalid-CURP test.** It uses `AAAA000000HZZZZZ0Q`, chosen because it fails `t_CURP` **and** escapes the generic CURP redaction pattern, and runs a real generation through the HTTP route. It then checks that neither the CURP nor its middle characters appear in:
  - the API responses (the generate refusal and the run's CFDI page);
  - any log line or stdout;
  - **any column of any table**: CFDI documents and events, audit rows and everything else.
- **Finding for ZP-PRIV, not caused by 11b:** the scan found the CURP in **`payslip_items.compliance_fields`**. That is a platform-wide snapshot of every country's identifiers, taken when a payroll run is generated (`models.py`: "Snapshot of PayrollEmployee.compliance_fields"). It is a second plaintext copy at rest, alongside the employee's own `compliance_fields`. Both fall under the open decision **Q9 / HK D-4**. The test excludes exactly those two source columns and says why.

## 7. Decisions the builder refuses without (G1 owner; listed in the G1 checklist)

| Decision | Why |
|---|---|
| Source of `SalarioDiarioIntegrado` | S4 p. 40 (LFT Art. 84) vs the IMSS SBC the engine computes, which S4 p. 39 treats as `SalarioBaseCotApor`. Every receipt with an employer registration is refused until this is decided (`mexico_cfdi_input.SDI_SOURCE`) |
| `INFONAVIT_CREDIT` | 009 or 010 |
| `VACATION_PAYOUT` | 001 or 038 |
| `ANNUAL_ADJUSTMENT_REFUND` | 004 or 005 |
| `SUBSIDY_APPLIED` | Unmapped until SAT's current subsidy instructions are saved (condition 2) |
| Separation receipts | TipoRegimen 13 vs the contract-type rule; the node's data. To be settled against the PAC test environment |
| Places of issue with seasonal offsets (border zones) | The change-over dates are not in the sources. Refused until a source gives them |
| Overtime (019) | The engine must record the days on which overtime was worked |

## 8. Full suite

Five sequential chunks on scratch SQLite, run alone: **7,212 passed**, 123 skipped, 2 xfailed, and **4 local-only failures**, none Mexico. These are the same four as in 10f–11a.

| Chunk | Result |
|---|---|
| 0 | 853 passed, 15 skipped, 3 failed (route registry: only `/health/version`, `/health/ready` and their `/api` twins, the uncommitted routes in `main.py`) |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed (`test_hong_kong_configuration…`: the uncommitted Hong Kong docs) |
| 2 | 1,337 passed, 35 skipped (includes the separation and orchestrator tests) |
| 3 | 1,685 passed, 66 skipped (includes `test_mexico_cfdi_builder.py` and the Phase 7 CFDI tests) |
| 4 | 1,054 passed, 6 skipped |

## 9. What this does in production when merged

| Change | Production effect |
|---|---|
| No migration | None |
| Builder, assembly and validation | Code only. `generate` still refuses: no release is Active (activation needs PAC validation, D3), and the signer refuses (X4). **No CFDI can be created.** |
| Super Admin CFDI overview | "Builder blocked" no longer appears when the pinned set is installed. Signing and PAC remain listed as blocked |
| Separation kinds | A content-interface change. No termination content is transcribed, so nothing that runs changes |
| Pinned manifest | `schemaLocations` added. The XSD checksum and catalogs are unchanged, so a release loaded from `sat_2026_08` still verifies |
| Docs | G1 checklist, proposals, `SOURCES_MANIFEST.csv` notes |

**Net:** Mexico stays dormant, and no other jurisdiction changes.

## 10. Open

- **Rugvedh's review before merging this PR.** PR #127 (11a) also needs his review: it was merged without one.
- The evidence-store location for the manifest note (condition 6).
- The G1 decisions (§7).
- 11c: the validate-only preview (D5), which needs at least the SDI decision before a real-shaped receipt can pass.
