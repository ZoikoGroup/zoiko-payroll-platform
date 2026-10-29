# Mexico (MX) — Phase 11 Plan: the CFDI 4.0 + Nómina 1.2 builder (X1) and XSD validation (X2)

**Status: PLAN — AWAITING APPROVAL. Nothing is built.** Written 2026-10-23, after Phase 10g (PR #125, production `f6c2a9d1e4b7`).

**Why this is next.**
- Gate **G1 (pre-pilot)** needs "CFDI 4.0 / Nómina 1.2 reconciled to SAT / PAC validation" (`release-gates/README.md`).
- Every later piece (PAC adapter, sandbox stamp test, pilot) consumes the XML this builder produces.
- It is the only remaining integration piece that needs **only public SAT documents**: no PAC contract, no bank, no credentials.

> **Review required: Rugvedh (ZP-PRIV).** The builder is the first code that reads the raw RFC / CURP / NSS out of `compliance_fields` and writes them into a document (§4.6). It needs his review before merge. His after-the-fact reviews of 10c, 10f and 10g come first (`PRODUCTION_STATE.md`).

## 0. What already exists (Phase 2 and Phase 7): this phase fills a seam, it does not add a subsystem

| Piece | Where | State |
|---|---|---|
| Builder seam `CfdiPayloadBuilder.build(document_input) -> bytes` | `mexico_cfdi_builder.py` | `SatBuilder` **refuses** (`MX_CFDI_BUILDER_BLOCKED`: S28, S30, S4 not saved) |
| Signer seam (cadena original + sello, CSD in GCP Secret Manager) | `mexico_cfdi_builder.py` | `GcpSmSigner` **refuses** (`MX_CSD_SIGNING_BLOCKED`), X4, **out of scope** |
| Lifecycle: preflight, folio, idempotency key, durable XML storage, state machine, outbox, UNKNOWN rule, cancellation and substitution | `mexico_cfdi_service.py` | Built and tested with synthetic builders |
| PAC adapter interface | `mexico_pac.py` | Interface only, X3, **out of scope** |
| Schema release (`cfdi_version`, `complement_version`, `xsd_checksum`, `catalog_release`, maker-checker) | `PayrollMxCfdiSchemaRelease` | Draft → Approved works; **activate is refused** ("needs the Phase 7 PAC validation") |
| SAT catalog entries per release | `PayrollMxCfdiCatalogEntry` | Table exists, **empty** |
| Earning classification with `cfdi_node_type` / `cfdi_concept_code` | `PayrollMxEarningClassification` | No `cfdi_concept_code` seeded ("none until VERIFIED" against S28) |
| Calculation result | `mx_result` (`countries/mexico.py`) | Has per-concept gross / exempt / taxable, `cfdi_node`, `cfdi_concept_code`, `days_paid`, `isr_withheld`, subsidy, `imss_employee`, `infonavit_credit`, SBC |
| Issuer data | `PayrollMxEmployerProfile`, IMSS registrations | RFC, legal name, `fiscal_regime_code`, fiscal and place-of-issue postal codes, `registro_patronal` |
| Receiver data | employee `mx_*` columns + `compliance_fields` | Fiscal postal code, receiver regime, contract / regime / workday / risk / frequency codes, seniority date, work state; **raw RFC / CURP / NSS in `compliance_fields`** (masked in every response; at-rest protection = open decision **Q9**) |

## 1. Scope

**In.**
- **X1:** the XML builder.
- **X2:** offline XSD validation against the pinned release.
- Loading a schema release (the XSDs plus the SAT catalogs) under maker-checker.
- The release-controlled mapping for amounts that are not earning classifications (ISR withheld, IMSS employee quota, INFONAVIT credit, subsidy).
- A validate-only preview that produces G1 evidence without creating a document.

**Out, unchanged.**
- **X4 signing:** cadena original and sello. It needs GCP Secret Manager and a CSD (D12 in the Phase 7 plan).
- **X3 the PAC adapter**, and **X5 the stamp test**.
- Employee delivery, SPEI, IDSE / SUA.
- Activating a release for real stamping, which keeps needing PAC validation (D3).

**Production effect when merged:** none that anyone can see.
- Mexico is dormant.
- `generate` still stops at the signer (`MX_CSD_SIGNING_BLOCKED`), so **no CFDI document can be created in production**.

## 2. Prerequisite: the sources (blocking; nothing in §4 starts without them)

Nothing is typed from memory. Every SAT value in the builder must cite one of these saved files: fixed attribute values, catalog codes, formatting and rounding rules, and node rules.

| Code | What | Why |
|---|---|---|
| **S28** | Complemento de Nómina 1.2: `nomina12.xsd` **and** the catalog workbook (c_TipoPercepcion, c_TipoDeduccion, c_TipoOtroPago, c_TipoNomina, c_TipoContrato, c_TipoRegimen, c_PeriodicidadPago, c_RiesgoPuesto, …) | Node structure and every payroll concept code |
| **S30** | CFDI 4.0 (Anexo 20): `cfdv40.xsd`, **the XSDs it imports** (`tdCFDI.xsd`, `catCFDI.xsd`, and `catNomina.xsd` with the nómina schema), and the catCFDI workbook (c_RegimenFiscal, c_CodigoPostal, c_UsoCFDI, …) | The comprobante envelope, issuer and receiver catalogs |
| **S4** | SAT "Guía de llenado" for the payroll receipt and its complement | The filling rules the XSD cannot express: which fixed values, totals, and when a node is required or forbidden |

Each file is saved byte-for-byte to `docs/mexico/sources/`, with URL, SHA-256, size, retrieval time and the revision it states in `SOURCES_MANIFEST.csv`, per the S24–S33 rules. This is decision **D1**: who saves them.

## 3. Sub-phases

| | Delivers | Exit |
|---|---|---|
| **11a** | Sources transcribed; a schema release **loaded** from them (XSD set + catalogs), Draft → Approved by two Super Admins; the system-concept mapping; S28 concept codes proposed for the earning classifications (each still approved by a second Super Admin) | An Approved release whose XSD checksums match the saved files; catalog counts match the workbooks |
| **11b** | Input assembly, the builder, offline XSD validation, the S4 filling rules as coded checks | Synthetic payslips of every result shape (ordinary, special pay, subsidy, annual adjustment, termination, correction) produce XML that **validates against the official XSDs** |
| **11c** | Validate-only preview (screen + route), G1 evidence pack material, report | Browser-verified; full suite; PostgreSQL |

## 4. Design

### 4.1 Loading a schema release (11a)
- The XSD set is stored in the repo under `backend/app/modules/payroll/mx_cfdi_schemas/<release>/` (decision **D2**):
  - byte-identical to the saved sources;
  - its SHA-256 recorded on the release (`xsd_checksum` = a hash over the sorted per-file hashes).
- A loader script reads the S28 / S30 workbooks and inserts `PayrollMxCfdiCatalogEntry` rows **into a Draft release only**. Approved releases are frozen, as the model already says.
  - `c_CodigoPostal` is loaded, never hand-transcribed (S30 checklist).
  - Each catalog's row count is printed for the four-eyes approver to compare with the workbook.
- No network access at any point. Validation resolves imports through a local resolver that **refuses** any URL outside the pinned folder.

### 4.2 Which release the builder may use (decision D3)
- Today `preflight` requires an **Active** release, and activation is refused until PAC validation exists.
- Proposal:
  - **Approved** is enough for **validation builds** (the preview, §4.7);
  - **Active** stays required for `generate`, and activation stays refused until X3 / X4 exist and one sandbox stamp has passed.
- So nothing about real stamping is loosened.

### 4.3 Amounts that are not earning classifications (decision D4)
- `isr_withheld`, `imss_employee`, `infonavit_credit` and the applied subsidy have no classification row, so no SAT code.
- A new table, `payroll_mx_cfdi_system_concepts`, maps a fixed list of engine keys (`ISR_WITHHELD`, `IMSS_EMPLOYEE`, `INFONAVIT_CREDIT`, `SUBSIDY_APPLIED`, and the annual-adjustment keys) to a node type and an S28 code, **per schema release**.
  - It uses maker-checker like the earning classifications, with each row citing its S28 / S4 location.
  - A builder run with an unmapped non-zero amount refuses (`MX_CFDI_CONCEPT_UNMAPPED`).
- This is the only migration of the phase: one platform table, no organisation, no RLS.

### 4.4 Input assembly (11b)
`_generate_one` passes only the result today. A new `cfdi_document_input(db, run, item, release)` assembles one in-memory structure. The builder stays pure (no DB access) and is unit-testable.

| Part | From |
|---|---|
| Issuer | The employer profile **version in force on the pay date** (RFC, legal name, regime, place-of-issue postal code) + the employee's IMSS registration (`registro_patronal`) |
| Receiver | Name; RFC / CURP / NSS **from `compliance_fields`, in memory only**; fiscal postal code; receiver regime; contract, regime, workday, risk and frequency codes; seniority date; work state |
| Nómina | Payroll type from the run type (ordinary / extraordinary, codes from S28); period start / end; pay date; `days_paid`; SBC / SDI from the result |
| Lines | `result.concepts` (gross, exempt, taxable, node, code) + the system concepts (§4.3) |
| Correction | `replacesUuid` → the CFDI relation node, relation code from S30 |

Every catalog code is checked **against the release's catalog entries, valid on the pay date**. A code that is missing or out of window refuses (`MX_CFDI_CATALOG_CODE_INVALID`) and names the field, never the value of an identifier.

### 4.5 The builder and validation (11b)
- `SatBuilder.build()` uses `lxml` (already pinned, 6.1.1). The output is deterministic:
  - fixed namespace prefixes and `schemaLocation` from the release;
  - attribute order as the XSD declares it;
  - UTF-8;
  - amounts formatted by the rule S4 states (no float anywhere: `Decimal` only).
- It leaves `Sello`, `NoCertificado` and `Certificado` to the signer seam.
- **Totals are recomputed from the lines and compared with the committed result. A difference refuses** (`MX_CFDI_TOTALS_MISMATCH`). The builder never "fixes" a figure (MX-017).
- Validation runs in two passes before any byte leaves the builder:
  1. **XSD** against the pinned set (X2);
  2. **S4 filling rules**, each a named check with its S4 page reference (for example, which totals must equal which sums, and which nodes are required for which contract types).
- A failure refuses (`MX_CFDI_XSD_INVALID` / `MX_CFDI_RULE_FAILED`), and no document row is created.
- `SatBuilder.blocked()` returns `None` only when the release's XSD files are present and match their checksum.

### 4.6 Privacy (for Rugvedh)
- **Plain identifiers live only in memory**, inside the assembly and builder call. They are never put in the document row, events, audit, logs, exceptions or API responses (MX-061).
- **lxml's XSD error messages quote the offending value.** Every validation message is passed through `app/core/redaction.py` (RFC / CURP / NSS patterns) and reduced to element + rule before it is stored or returned. A test feeds a deliberately invalid CURP and asserts that neither it nor its middle characters appear anywhere.
- The produced XML (which necessarily contains the identifiers) goes only to object storage via the existing `save_upload` with its durable-storage refusal, exactly as today. **Access to and encryption of that storage is part of Q9 / HK D-4** and is not changed here; this is stated in the report so G7 can sign it knowingly.
- The preview (§4.7) **never returns the XML body**. It returns pass/fail, the rule findings (redacted) and a SHA-256 of the would-be payload.

### 4.7 Validate-only preview (11c)
- Org admin, on a committed run: **Validate CFDI**.
  - It builds and validates each payslip's XML in memory against the Approved release, and shows per payslip: valid / which rule failed.
  - It stores nothing except an audited summary (counts, hashes, rule ids).
- Super Admin sees the same summary across organisations for G1 evidence.
- Route classes as the existing CFDI routes (worker data, org-scoped, tenant session).

## 5. Tests and proof

| What | How |
|---|---|
| Structure | Every synthetic payslip shape validates against the **official** pinned XSDs; a mutated document (missing node, wrong code, bad total) fails with the expected rule |
| Worked examples | If S4 contains example receipts, each is rebuilt from equivalent inputs and compared node by node (a golden vector per example, citing its page) |
| Totals | Directional and equality checks: the sum of exempt + taxable = gross per line; document totals = the committed result; a one-centavo drift refuses |
| Catalog window | A code valid before / after the pay date refuses |
| No network | Validation with sockets disabled passes; an import pointing outside the pinned folder refuses |
| Privacy | Redaction of lxml messages; no identifier in DB rows, events, audit, logs or responses (scan) |
| Source citation | A static test: every SAT literal in the builder and rules module comes from a table that names its source (S4 / S28 / S30 + location); no bare literals |
| Migration | PostgreSQL 17: locks, fail-fast, upgrade from production head, as for m14–m16 |
| Browser | Preview flow: valid run, failing run with a readable rule, NL unchanged |
| Full suite | Sequential chunks, alone |

## 6. What this phase will not give

- **G1 still cannot be signed by this phase alone.** "Reconciled to PAC validation" needs a real PAC sandbox stamp, which needs X3 (a chosen PAC), X4 (CSD signing in Secret Manager) and the stamp test. After 11, the open G1 items are exactly those, plus the Annex 8 / subsidy content sign-off.
- No document is created in production (the signer refuses).

## 7. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| **D1** | Who saves S28, S30 (with the imported XSDs) and S4? | **I fetch them from the official SAT URLs** listed in the sources addendum, byte-for-byte, record hashes, and you confirm the revisions before 11a uses them. (Until now I have not fetched sources unasked.) |
| **D2** | Where do the pinned XSDs live? | **In the repo** (public files, reviewable diffs, checksum-verified at load), not in the database or object storage |
| **D3** | May an **Approved** (not Active) release be used for validate-only builds? | **Yes**; `generate` keeps requiring Active, and activation keeps requiring PAC validation |
| **D4** | System concepts (ISR withheld, IMSS, INFONAVIT credit, subsidy) via a new release-controlled mapping table with maker-checker? | **Yes** (one platform table, the only migration) |
| **D5** | Build the validate-only preview (§4.7)? | **Yes**: it is the G1 evidence path without signing |
| **D6** | Earning-classification `cfdi_concept_code` values: proposed by me from S28, approved by a second Super Admin through the existing classification flow? | **Yes**: proposed with the S28 row cited; nothing goes ACTIVE without the second approval |

## 8. Order of work once approved

1. D1: the sources saved and hashed; I report the revisions they state, and **stop for your confirmation**.
2. 11a: loader + release + system-concept mapping (+ migration), staged, report.
3. 11b: assembly + builder + validation, staged, report.
4. 11c: preview + evidence + browser, staged, report. Rugvedh reviews before merge.
