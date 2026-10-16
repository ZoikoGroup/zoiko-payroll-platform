# ZP-MX-ENG-001 — Addendum to the §22 Evidence Register (S24–S29)

**Status: PENDING SPEC-OWNER APPROVAL.** These sources extend the "Official evidence register — reviewed for 2026 design" in spec §22. They were added at the user's direction on 2026-10-15 (Phase 1, answers to Q1–Q3), because the primary legal text for these rules is not among S1–S23. Until the spec owner approves them, every value transcribed from S24–S29 stays `[PENDING G1]`, like every other Phase 1 value.

| Code | Authority | Document | Official URL | Rules it evidences | Why it is needed |
|---|---|---|---|---|---|
| S24 | Cámara de Diputados (consolidated text) | Ley del Impuesto sobre la Renta (LISR), Art. 93 | https://www.diputados.gob.mx/LeyesBiblio/pdf/LISR.pdf | MX-009, MX-052 | The ISR exempt limits for aguinaldo, vacation premium, PTU, overtime, Sunday premium and separation payments are set in LISR Art. 93. No S1–S23 source contains them. |
| S25 | Cámara de Diputados (consolidated text) | Reglamento de la LISR (RLISR), Art. 174 | https://www.diputados.gob.mx/LeyesBiblio/regley/Reg_LISR_060516.pdf | MX-009 | RLISR Art. 174 is the optional withholding method for special remuneration (aguinaldo, PTU, vacation premium). Before saving, check the index page https://www.diputados.gob.mx/LeyesBiblio/regla.htm for a newer consolidated version. |
| S26 | Cámara de Diputados (consolidated text) | Ley Federal del Trabajo (LFT) | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf | MX-048–MX-053 | The primary law for the overtime rules (Arts. 66–68), the Sunday premium (Art. 71), mandatory rest days (Arts. 74–75), vacations and the vacation premium (Arts. 76–80) and aguinaldo (Art. 87). S19 and S20 (PROFEDET explainers) are kept as **cross-checks** only. |
| S27 | Cámara de Diputados (consolidated text) | Ley del INFONAVIT (LIFNVT), Art. 29 | https://www.diputados.gob.mx/LeyesBiblio/pdf/LIFNVT.pdf | MX-031, MX-032 | The primary law for the 5% employer housing contribution. S15 (INFONAVIT portal) is kept as a **cross-check** only. |
| S28 | SAT | Complemento de Nómina 1.2 — catalog workbook (c_TipoPercepcion, c_TipoDeduccion, c_TipoOtroPago, …) **and** `nomina12.xsd` | XSD: http://www.sat.gob.mx/sitio_internet/cfd/nomina/nomina12.xsd · catalog workbook: SAT "Complemento de nómina" page (the catalog spreadsheet linked there — confirm the current revision on the SAT site before saving) | MX-005, MX-014, MX-015 | Added in Phase 2 (Q3). The SAT payroll concept codes for the earning-classification catalogue and the CFDI schema release come from these two files; none of S1–S27 contains them. Until S28 is saved and VERIFIED, **no canonical classification can go live** (a canonical row needs its SAT code in an approved catalog release). |
| S29 | Cámara de Diputados (consolidated text) | Reglamento de la Ley del Seguro Social en materia de Afiliación, Clasificación de Empresas, Recaudación y Fiscalización (RACERF) | Index: https://www.diputados.gob.mx/LeyesBiblio/regla.htm (open the RACERF entry and save the PDF it links; confirm the current consolidated version there before saving) | MX-024, MX-026 | Added in Phase 3 (Q3). The validity window of an employer's work-risk premium (expected 1 March to the end of February of the following year, spec MX-026) and the annual determination rules are expected here if they are not in S10 (LSS) or S14. Until the window is transcribed from a saved source, **no risk premium can be approved**. |

**S29 fetch checklist (Phase 3):**
1. Open https://www.diputados.gob.mx/LeyesBiblio/regla.htm and find the RACERF entry under "Ley del Seguro Social".
2. Save the linked PDF byte-for-byte as `docs/mexico/sources/S29_RACERF.pdf`; record URL, SHA-256, size, retrieval time and the "Última reforma DOF" date in `SOURCES_MANIFEST.csv`.
3. Find the articles on the risk-premium determination and its validity period; record article numbers and pages in the transcription log.
4. Check S10 (LSS) at the same time for Art. 74 (premium range and annual revision) — the range belongs to S10; the validity window to whichever source states it.
5. Stop and ask if S10, S14 and S29 disagree, or if none states the window.

**Rules for S24–S29 (same as S1–S23):**
- Each file is saved byte-for-byte to `docs/mexico/sources/`, and its SHA-256 is recorded in `SOURCES_MANIFEST.csv`.
- Each file becomes a `SourceArtifact` holding the URL, the SHA-256 and the `file_path`.
- Where a primary source (S24–S27) and its cross-check (S15, S19, S20) disagree, the primary source wins. The disagreement is recorded in the transcription log, and work stops for a decision.
- The consolidated texts show a "Última reforma DOF" date in their header. That date is recorded in the transcription log for each file.

**Spec-owner approval:** ______________________ (name / date)
