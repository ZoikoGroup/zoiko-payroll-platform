# ZP-MX-ENG-001 — Addendum to the §22 Evidence Register (S24–S36)

**Status: PENDING SPEC-OWNER APPROVAL.** These sources extend the "Official evidence register — reviewed for 2026 design" in spec §22. They were added at the user's direction on 2026-10-15 (Phase 1, answers to Q1–Q3), because the primary legal text for these rules is not among S1–S23. Until the spec owner approves them, every value transcribed from S24–S33 stays `[PENDING G1]`, like every other Phase 1 value.

| Code | Authority | Document | Official URL | Rules it evidences | Why it is needed |
|---|---|---|---|---|---|
| S24 | Cámara de Diputados (consolidated text) | Ley del Impuesto sobre la Renta (LISR), Art. 93 | https://www.diputados.gob.mx/LeyesBiblio/pdf/LISR.pdf | MX-009, MX-052 | The ISR exempt limits for aguinaldo, vacation premium, PTU, overtime, Sunday premium and separation payments are set in LISR Art. 93. No S1–S23 source contains them. |
| S25 | Cámara de Diputados (consolidated text) | Reglamento de la LISR (RLISR), Art. 174 | https://www.diputados.gob.mx/LeyesBiblio/regley/Reg_LISR_060516.pdf | MX-009 | RLISR Art. 174 is the optional withholding method for special remuneration (aguinaldo, PTU, vacation premium). Before saving, check the index page https://www.diputados.gob.mx/LeyesBiblio/regla.htm for a newer consolidated version. |
| S26 | Cámara de Diputados (consolidated text) | Ley Federal del Trabajo (LFT) | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf | MX-048–MX-053 | The primary law for the overtime rules (Arts. 66–68), the Sunday premium (Art. 71), mandatory rest days (Arts. 74–75), vacations and the vacation premium (Arts. 76–80) and aguinaldo (Art. 87). S19 and S20 (PROFEDET explainers) are kept as **cross-checks** only. |
| S27 | Cámara de Diputados (consolidated text) | Ley del INFONAVIT (LIFNVT), Art. 29 | https://www.diputados.gob.mx/LeyesBiblio/pdf/LIFNVT.pdf | MX-031, MX-032 | The primary law for the 5% employer housing contribution. S15 (INFONAVIT portal) is kept as a **cross-check** only. |
| S28 | SAT | Complemento de Nómina 1.2 — catalog workbook (c_TipoPercepcion, c_TipoDeduccion, c_TipoOtroPago, …) **and** `nomina12.xsd` | XSD: http://www.sat.gob.mx/sitio_internet/cfd/nomina/nomina12.xsd · catalog workbook: SAT "Complemento de nómina" page (the catalog spreadsheet linked there — confirm the current revision on the SAT site before saving) | MX-005, MX-014, MX-015 | Added in Phase 2 (Q3). The SAT payroll concept codes for the earning-classification catalogue and the CFDI schema release come from these two files; none of S1–S27 contains them. Until S28 is saved and VERIFIED, **no canonical classification can go live** (a canonical row needs its SAT code in an approved catalog release). |
| S29 | Cámara de Diputados (consolidated text) | Reglamento de la Ley del Seguro Social en materia de Afiliación, Clasificación de Empresas, Recaudación y Fiscalización (RACERF) | Index: https://www.diputados.gob.mx/LeyesBiblio/regla.htm (open the RACERF entry and save the PDF it links; confirm the current consolidated version there before saving) | MX-024, MX-026 | Added in Phase 3 (Q3). The validity window of an employer's work-risk premium (expected 1 March to the end of February of the following year, spec MX-026) and the annual determination rules are expected here if they are not in S10 (LSS) or S14. Until the window is transcribed from a saved source, **no risk premium can be approved**. |
| S30 | SAT | CFDI 4.0 catalog workbook (catCFDI: c_RegimenFiscal, c_CodigoPostal, …) — Anexo 20 | SAT "Anexo 20" page (Comprobante Fiscal Digital por Internet, versión 4.0) — save the catalog spreadsheet linked there; confirm the current revision on the SAT site before saving | MX-015, spec §6 "Employer issuer" | Added in Phase 3 follow-up. The employer's fiscal regime (`c_RegimenFiscal`) and postal codes (`c_CodigoPostal`) are checked against these CFDI 4.0 catalogs, which are **not** in the Nómina 1.2 workbook (S28). Until S30 is saved, VERIFIED and loaded into an Active CFDI release (Phase 7), both employer readiness items stay BLOCKED. |
| S31 | RENAPO (Secretaría de Gobernación) | CURP — official structure and check-digit rules (instructivo normativo para la asignación de la CURP) | RENAPO / gob.mx CURP page — save the normative document it links; confirm the current version before saving | MX-036, spec §12 Identity | Added in Phase 4 (Q2/Q3). The CURP structure, its check digit and which characters must agree with the RFC / name / date of birth. Until saved, CURP is format-checked only (`FORMAT_ONLY`) and the RFC↔CURP cross-check reports "not checked — source pending". |
| S32 | IMSS | NSS (Número de Seguridad Social) — structure and check digit | IMSS official page or published standard describing the NSS (confirm on imss.gob.mx before saving) | MX-036, spec §12 Identity / IMSS | Added in Phase 4 (Q2). Until saved, NSS is checked as 11 digits only. |
| S33 | Banco de México / ABM | CLABE (Clave Bancaria Estandarizada) — 18-digit structure and check digit | Banxico / ABM published CLABE standard (confirm the current document before saving) | spec §12 Pay, §20 Bank settlement | Added in Phase 4 (Q2). Until saved, CLABE is checked as 18 digits only; no payment file exists before Phase 10. |
| S34 | DOF (copy kept by the Cámara de Diputados) | DECRETO … en materia de desindexación del salario mínimo (DOF 27-01-2016), Transitorio Tercero | https://www.diputados.gob.mx/LeyesBiblio/ref/dof/CPEUM_ref_226_27ene16.pdf | MX-021, MX-022, MX-029 | Added 2026-10-26 (completion programme W2-5; proposed in the Transcription Batch 2 report). LSS Arts. 28 and 106 still word the SBC ceiling and the E&M threshold in "salario mínimo"; Transitorio Tercero is what makes those references read as the UMA. Saved as an archive copy (Draft only). |
| S35 | Cámara de Diputados (consolidated text) | Código Fiscal de la Federación (CFF), Arts. 12 and 20 | https://www.diputados.gob.mx/LeyesBiblio/pdf/CFF.pdf | MX-025, Q2 | Added 2026-10-26 (completion programme W2-5). Art. 12 lists the days not counted in fiscal deadlines (a candidate for the IMSS movement deadline, D-16); Art. 20 is a rounding candidate (D-01). Archive copy (Draft only). |
| S36 | Cámara de Diputados (consolidated text) | Ley del ISSSTE, Art. 21 | https://www.diputados.gob.mx/LeyesBiblio/pdf/LISSSTE.pdf | MX-030, MX-032 | Added 2026-10-26 (completion programme W2-5). The bimonthly cycle of INFONAVIT (Ley INFONAVIT 1997 Transitorio SEXTO) and of the LSS RCV quotas (Transitorio VIGÉSIMO SÉPTIMO) lasts until the ISSSTE law pays monthly; Art. 21 shows it still pays "por bimestres vencidos". Archive copy (Draft only). |

**S29 fetch checklist (Phase 3):**
1. Open https://www.diputados.gob.mx/LeyesBiblio/regla.htm and find the RACERF entry under "Ley del Seguro Social".
2. Save the linked PDF byte-for-byte as `docs/mexico/sources/S29_RACERF.pdf`; record URL, SHA-256, size, retrieval time and the "Última reforma DOF" date in `SOURCES_MANIFEST.csv`.
3. Find the articles on the risk-premium determination and its validity period; record article numbers and pages in the transcription log.
4. Check S10 (LSS) at the same time for Art. 74 (premium range and annual revision) — the range belongs to S10; the validity window to whichever source states it.
5. Stop and ask if S10, S14 and S29 disagree, or if none states the window.

**S30 fetch checklist (Phase 3 follow-up):**
1. Open SAT's Anexo 20 page for CFDI 4.0 and find the catalog workbook (catCFDI) link; confirm it is the current revision.
2. Save the workbook byte-for-byte as `docs/mexico/sources/S30_SAT_catCFDI.xls` (or `.xlsx` as published); record URL, SHA-256, size and retrieval time in `SOURCES_MANIFEST.csv`, plus the revision/version stated in the workbook.
3. Record which sheets hold `c_RegimenFiscal` and `c_CodigoPostal` and their validity columns in the transcription log.
4. `c_CodigoPostal` is large; it is loaded as catalog entries of a CFDI schema release (Phase 2 table), never transcribed by hand.
5. Stop and ask if the workbook's catalog names or columns differ from the CFDI 4.0 schema the PAC validates against (Phase 7).

**S31–S33 fetch checklist (Phase 4):**
1. For each source, find the issuer's own normative document (not a third-party explainer); confirm it is the current version.
2. Save byte-for-byte as `docs/mexico/sources/S31_RENAPO_CURP.pdf`, `S32_IMSS_NSS.pdf`, `S33_BANXICO_CLABE.pdf`; record URL, SHA-256, size, retrieval time and the version/date stated in the document in `SOURCES_MANIFEST.csv`.
3. Record the exact page/section of each structure and check-digit rule (and, for S31, the RFC↔CURP agreement rule) in the transcription log.
4. Implement a check digit only from the saved text, with the document's own worked example as a test vector.
5. Stop and ask if a document gives no algorithm, or two sources disagree.

**Rules for S24–S33 (same as S1–S23):**
- Each file is saved byte-for-byte to `docs/mexico/sources/`, and its SHA-256 is recorded in `SOURCES_MANIFEST.csv`.
- Each file becomes a `SourceArtifact` holding the URL, the SHA-256 and the `file_path`.
- Where a primary source (S24–S27) and its cross-check (S15, S19, S20) disagree, the primary source wins. The disagreement is recorded in the transcription log, and work stops for a decision.
- The consolidated texts show a "Última reforma DOF" date in their header. That date is recorded in the transcription log for each file.

**Spec-owner approval:** ______________________ (name / date)
