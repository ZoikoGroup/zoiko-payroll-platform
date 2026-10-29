# Mexico source download runbook (gap C2)

**For:** a colleague in Mexico, or on a VPN that resolves `sat.gob.mx`, turning saved sources into **VERIFIED** in one sitting.
**Written:** 2026-10-28, final mile X7. The table is generated from `docs/mexico/sources/SOURCES_MANIFEST.csv`, so its URLs and hashes are the manifest's.

## 1. Why this matters

- Each source below is saved as an **Internet Archive capture** (`ARCHIVE_COPY_VERIFIED`). Such a copy can back **Draft** content only.
- **Activation and G1 need `VERIFIED`.** That means a fresh **direct** download from the official URL that hashes to the saved copy.
- The only path to VERIFIED is `scripts/verify_mexico_sources.py verify`. It appends every attempt to `VERIFICATION_LOG.csv`. Never edit the manifest's status by hand: a VERIFIED row without its MATCH log entry is ignored.

Today: 1 file VERIFIED, 31 archive copies, 1 wrong version, 33 files in total.

## 2. Before you start

1. Use a network from which `www.sat.gob.mx`, `omawww.sat.gob.mx`, `www.dof.gob.mx`, `www.imss.gob.mx`, `www.inegi.org.mx` and `www.diputados.gob.mx` load in a browser. From outside Mexico, `sat.gob.mx` often does not resolve.
2. Check out the repository on the `nikhil` branch with the source binaries in `docs/mexico/sources/`. They come from the team evidence store; the manifest notes say where.
3. Open a terminal in `backend/` and run:

   ```
   python -m scripts.verify_mexico_sources check
   ```

   It must report every file present and matching its recorded SHA-256. Stop if it does not.

## 3. For each row: run its command

| Code | File | Status | Unlocks | Gate | Official URL | Expected SHA-256 (the saved copy) | Command (in `backend/`) |
|---|---|---|---|---|---|---|---|
| S1 | `S1_SAT_1aRM_RMF2026.pdf` | ARCHIVE_COPY_VERIFIED | CFDI receipt rules 2.7.1.7 / 2.7.5.2 | G1 | https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE/documentos2026/rmf/rmf/1aRM_RMF2026.pdf | `ff4b0ed8957f4ff5cbb678f8fdd2e4da84b3a4a96d259027ed0d817c255e6e37` | `python -m scripts.verify_mexico_sources verify S1 downloader="YOUR NAME" file=S1_SAT_1aRM_RMF2026.pdf` |
| S1 | `S1_SAT_RMF2026_DOF28122025.pdf` | ARCHIVE_COPY_VERIFIED | CFDI receipt rules 2.7.1.7 / 2.7.5.2 | G1 | https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE/documentos2026/rmf/rmf/RMF_2026-DOF-28122025.pdf | `6f71ce0cccf430171fe858c5d244b1c321fa68306f962d44ec4977858a52919a` | `python -m scripts.verify_mexico_sources verify S1 downloader="YOUR NAME" file=S1_SAT_RMF2026_DOF28122025.pdf` |
| S2 | `S2_SAT_Anexo8_RMF2026.pdf` | ARCHIVE_COPY_VERIFIED | ISR tariffs (Anexo 8) | G1 | https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE/documentos2026/rmf/anexos/Anexo-8-RMF-2026_DOF-28122025.pdf | `69ebaf8a78a3bde5d631ad2a994e81ec6d07e2d4e39085c8c948d138f782c1f4` | `python -m scripts.verify_mexico_sources verify S2 downloader="YOUR NAME"` |
| S3 | `S3_DOF_Decreto_subsidio_empleo_01052024.html` | ARCHIVE_COPY_VERIFIED | employment subsidy | G1 | https://www.dof.gob.mx/nota_detalle.php?codigo=5725287&fecha=01/05/2024 | `84d244c2af8625fde24f83d7a468905fc7470cfcb37d4b054131f04573e63cbf` | `python -m scripts.verify_mexico_sources verify S3 downloader="YOUR NAME" file=S3_DOF_Decreto_subsidio_empleo_01052024.html` |
| S3 | `S3_DOF_Decreto_subsidio_empleo_31122024.html` | ARCHIVE_COPY_VERIFIED | employment subsidy | G1 | https://www.dof.gob.mx/nota_detalle.php?codigo=5746529&fecha=31/12/2024 | `1767215f9f380b1384c06d21ae96d073dadfa282b0cf9a03a78e1b66f9e9f41d` | `python -m scripts.verify_mexico_sources verify S3 downloader="YOUR NAME" file=S3_DOF_Decreto_subsidio_empleo_31122024.html` |
| S3 | `S3_DOF_Decreto_subsidio_empleo_31122025.html` | ARCHIVE_COPY_VERIFIED | employment subsidy | G1 | https://www.dof.gob.mx/nota_detalle.php?codigo=5777649&fecha=31/12/2025 | `14c0b1d7448739ca80b210372ffdb3fb35f6b57dcca930be22f609492bb96cef` | `python -m scripts.verify_mexico_sources verify S3 downloader="YOUR NAME" file=S3_DOF_Decreto_subsidio_empleo_31122025.html` |
| S4 | `S4_SAT_Guia_llenado_Nomina.pdf` | ARCHIVE_COPY_VERIFIED | CFDI Nómina filling rules | G1 | http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Guia_llenado_Nomina.pdf | `1436aff9bb46b790802989311b5d91e799dabd61be60d5d8a378780fb6e66287` | `python -m scripts.verify_mexico_sources verify S4 downloader="YOUR NAME"` |
| S6 | `S6_INEGI_UMA_2026.pdf` | ARCHIVE_COPY_VERIFIED | UMA 2026 | G2 | https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2026/uma/uma2026.pdf | `9c9c4ff3da9b34852d5e3b8165c50c346ff3ef7ba74737489f6d1f544c353e1c` | `python -m scripts.verify_mexico_sources verify S6 downloader="YOUR NAME"` |
| S7 | `S7_INEGI_UMA_2025.pdf` | ARCHIVE_COPY_VERIFIED | UMA 2025 (January 2026 periods) | G2 (UMA Jan 2026, F1) | https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2025/uma/uma2025.pdf | `eb88864cb07d7cbea007d48c3aec3d05ef07eb70376ab4d8208c967d82d8eaf4` | `python -m scripts.verify_mexico_sources verify S7 downloader="YOUR NAME"` |
| S9 | `S9_DOF_Resolucion_salarios_minimos_2026.html` | ARCHIVE_COPY_VERIFIED | minimum wages 2026 | G5 | https://www.dof.gob.mx/nota_detalle.php?codigo=5775534&fecha=09/12/2025 | `a3f6f184088073987be637e60c9f87f06630954f6237bc22732f03409f6a3b49` | `python -m scripts.verify_mexico_sources verify S9 downloader="YOUR NAME"` |
| S10 | `S10_IMSS_LSS.pdf` | ARCHIVE_COPY_VERIFIED | IMSS branches and rates (LSS) | G2 | https://www.imss.gob.mx/sites/all/statics/pdf/leyes/LSS.pdf | `875efb2c8e6562f4236a343c27f3199dc04732890e484e95086f69da05aa632c` | `python -m scripts.verify_mexico_sources verify S10 downloader="YOUR NAME"` |
| S11 | `S11_DIP_LSS_ref25_16dic20.pdf` | ARCHIVE_COPY_VERIFIED | CEAV bands 2023–2030 | G2 | https://www.diputados.gob.mx/LeyesBiblio/ref/lss/LSS_ref25_16dic20.pdf | `1078f08acbda8435d830c36c1699c8feb97f670dba9394419673c618d8027e92` | `python -m scripts.verify_mexico_sources verify S11 downloader="YOUR NAME"` |
| S18 | `S18_DOF_Decreto_LFT_jornada_01052026.html` | ARCHIVE_COPY_VERIFIED | workweek transition | G5 | https://www.dof.gob.mx/nota_detalle.php?codigo=5786537&fecha=01%2F05%2F2026 | `681d34ae8bbac0b9eed103dc920513fb45f3776c233909c71043e280995e3747` | `python -m scripts.verify_mexico_sources verify S18 downloader="YOUR NAME"` |
| S22 | `S22_CDMX_Codigo_Fiscal_2026.pdf` | WRONG_VERSION **WRONG_VERSION: do not verify this file; see §4** | CDMX payroll tax (ISN) | G4 | https://www.congresocdmx.gob.mx/archivo-45edcc764eb95c905412604e86eb20195b16f27e.pdf | `3246cbf3863b5c62905131f4397bbf2c037c879638c6149da84024f1a9b62b19` | `python -m scripts.verify_mexico_sources verify S22 downloader="YOUR NAME" file=S22_CDMX_Codigo_Fiscal_2026.pdf` |
| S22 | `S22_GOCDMX_Gaceta_19122025_No1762.pdf` | ARCHIVE_COPY_VERIFIED | CDMX payroll tax (ISN) | G4 | https://data.consejeria.cdmx.gob.mx/portal_old/uploads/gacetas/bbd22f0b2fab730aa4dc56e3e207b4c1.pdf | `e6b41866bd8d3a15a9dad9159746229806080d0e2a7feb8a01651b255aaf4f99` | `python -m scripts.verify_mexico_sources verify S22 downloader="YOUR NAME" file=S22_GOCDMX_Gaceta_19122025_No1762.pdf` |
| S24 | `S24_DIP_LISR.pdf` | ARCHIVE_COPY_VERIFIED | LISR Art. 93 exemptions | G1 | https://www.diputados.gob.mx/LeyesBiblio/pdf/LISR.pdf | `803c2875c09c751c1966b8eb4dca99f460b237da4ef67ee04b4fa325d8c2f786` | `python -m scripts.verify_mexico_sources verify S24 downloader="YOUR NAME"` |
| S25 | `S25_DIP_RLISR.pdf` | ARCHIVE_COPY_VERIFIED | RLISR Art. 174 | G1 | https://www.diputados.gob.mx/LeyesBiblio/regley/Reg_LISR_060516.pdf | `0538fd2fa3da9705370350b1e25a1656cc681d2c489545334079e1b35360d6e3` | `python -m scripts.verify_mexico_sources verify S25 downloader="YOUR NAME"` |
| S26 | `S26_DIP_LFT.pdf` | ARCHIVE_COPY_VERIFIED | LFT (vacations, aguinaldo, termination) | G5 | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf | `12f09393a1951a91c3f57f579bf611b034edf1a5f78cdbfb828e23ff3a9acbf7` | `python -m scripts.verify_mexico_sources verify S26 downloader="YOUR NAME"` |
| S27 | `S27_DIP_LIFNVT.pdf` | ARCHIVE_COPY_VERIFIED | INFONAVIT Art. 29 | G3 | https://www.diputados.gob.mx/LeyesBiblio/pdf/LIFNVT.pdf | `9ee6e5ef336dee5700726bd3c570d24f91fc458136e298ae2e3806bd12217912` | `python -m scripts.verify_mexico_sources verify S27 downloader="YOUR NAME"` |
| S28 | `S28_SAT_catNomina.xls` | ARCHIVE_COPY_VERIFIED | Nómina 1.2 schema + catalogues | G1 | http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/catNomina.xls | `6e61a49d7b966dbcf730ef46a5fde1cb3b505114b69b4ecbf8fa2ba5d882a3c3` | `python -m scripts.verify_mexico_sources verify S28 downloader="YOUR NAME" file=S28_SAT_catNomina.xls` |
| S28 | `S28_SAT_catNomina.xsd` | ARCHIVE_COPY_VERIFIED | Nómina 1.2 schema + catalogues | G1 | http://www.sat.gob.mx/sitio_internet/cfd/catalogos/Nomina/catNomina.xsd | `ee060521477a7e9435c47866243f55814b370efc63b66805c9b51c1c80faaf95` | `python -m scripts.verify_mexico_sources verify S28 downloader="YOUR NAME" file=S28_SAT_catNomina.xsd` |
| S28 | `S28_SAT_nomina12.xsd` | ARCHIVE_COPY_VERIFIED | Nómina 1.2 schema + catalogues | G1 | http://www.sat.gob.mx/sitio_internet/cfd/nomina/nomina12.xsd | `ac5db22ceee35c2224aad8745a3ab968c9c3d04d36adb50d056c83c4c1a29083` | `python -m scripts.verify_mexico_sources verify S28 downloader="YOUR NAME" file=S28_SAT_nomina12.xsd` |
| S29 | `S29_DIP_RACERF.pdf` | ARCHIVE_COPY_VERIFIED | IMSS RACERF | G2 | https://www.diputados.gob.mx/LeyesBiblio/regley/Reg_LSS_MACERF.pdf | `78fb70d213053e46d3e739b9d80bf7da733d80f27446af7d5812fc6de80533c9` | `python -m scripts.verify_mexico_sources verify S29 downloader="YOUR NAME"` |
| S30 | `S30_SAT_Anexo20_2022.pdf` | ARCHIVE_COPY_VERIFIED | CFDI 4.0 schema, catalogues, Anexo 20 | G1 | http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Anexo20_2022.pdf | `b3b6d63a97c859a31d7aacf0fe17b2d58207280df6f06caff3ceaf79954cf4bd` | `python -m scripts.verify_mexico_sources verify S30 downloader="YOUR NAME" file=S30_SAT_Anexo20_2022.pdf` |
| S30 | `S30_SAT_Anexo20_Guia_llenado.pdf` | ARCHIVE_COPY_VERIFIED | CFDI 4.0 schema, catalogues, Anexo 20 | G1 | http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Anexo_20_Guia_de_llenado_CFDI.pdf | `70e0c92df44b4f36975e4a0a5b1f0609f83c62deb029eda440fe4df6e2265a25` | `python -m scripts.verify_mexico_sources verify S30 downloader="YOUR NAME" file=S30_SAT_Anexo20_Guia_llenado.pdf` |
| S30 | `S30_SAT_catCFDI.xls` | ARCHIVE_COPY_VERIFIED | CFDI 4.0 schema, catalogues, Anexo 20 | G1 | http://omawww.sat.gob.mx/tramitesyservicios/paginas/documentos/catCFDI_V_4_20260731.xls | `5a2e95fb98f657e52552d2772154c4b1e0dbdfee2cefd6696ac003eba7326bcb` | `python -m scripts.verify_mexico_sources verify S30 downloader="YOUR NAME" file=S30_SAT_catCFDI.xls` |
| S30 | `S30_SAT_catCFDI.xsd` | ARCHIVE_COPY_VERIFIED | CFDI 4.0 schema, catalogues, Anexo 20 | G1 | http://www.sat.gob.mx/sitio_internet/cfd/catalogos/catCFDI.xsd | `6c58936cb77576f839a4d7915953ceaf252b9eb9319f9458fe5bb67ae2bb0bb1` | `python -m scripts.verify_mexico_sources verify S30 downloader="YOUR NAME" file=S30_SAT_catCFDI.xsd` |
| S30 | `S30_SAT_cfdv40.xsd` | ARCHIVE_COPY_VERIFIED | CFDI 4.0 schema, catalogues, Anexo 20 | G1 | http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd | `2489b5b535f5cbc6a6c2db6132620de1833f85372512d01deea62880e700e276` | `python -m scripts.verify_mexico_sources verify S30 downloader="YOUR NAME" file=S30_SAT_cfdv40.xsd` |
| S30 | `S30_SAT_tdCFDI.xsd` | ARCHIVE_COPY_VERIFIED | CFDI 4.0 schema, catalogues, Anexo 20 | G1 | http://www.sat.gob.mx/sitio_internet/cfd/tipoDatos/tdCFDI/tdCFDI.xsd | `b3b81fe4017b95d5477f23a32f47e8b0571683cfddfff1330508c75e02b504cd` | `python -m scripts.verify_mexico_sources verify S30 downloader="YOUR NAME" file=S30_SAT_tdCFDI.xsd` |
| S34 | `S34_DIP_CPEUM_ref226_27ene16.pdf` | ARCHIVE_COPY_VERIFIED | UMA de-indexation (D-03) | G2 (D-03) | https://www.diputados.gob.mx/LeyesBiblio/ref/dof/CPEUM_ref_226_27ene16.pdf | `16c38e9fa2fdf8185413051f9f3e9573337cfd5705808a5f5718c1fec8d1c76e` | `python -m scripts.verify_mexico_sources verify S34 downloader="YOUR NAME"` |
| S35 | `S35_DIP_CFF.pdf` | ARCHIVE_COPY_VERIFIED | CFF Arts. 12 / 20 (D-01, D-16) | G1 (D-01) | https://www.diputados.gob.mx/LeyesBiblio/pdf/CFF.pdf | `be7427b20d3552775ab42018f8f87578078770095bf8cf46322c25e36ee3aa7d` | `python -m scripts.verify_mexico_sources verify S35 downloader="YOUR NAME"` |
| S36 | `S36_DIP_LISSSTE.pdf` | ARCHIVE_COPY_VERIFIED | ISSSTE Art. 21 | G2 / G3 (RCV periodicity) | https://www.diputados.gob.mx/LeyesBiblio/pdf/LISSSTE.pdf | `aa6e0e437331debd80d0086155e2d99885ea5e22cb13353c44eb0b1090f0b4d5` | `python -m scripts.verify_mexico_sources verify S36 downloader="YOUR NAME"` |

**What each result means:**
- **MATCH:** the row becomes VERIFIED, and the log has the entry.
- **MISMATCH:** the official file **differs** from the saved copy. This usually means a newer reform or edition, especially for the consolidated laws on diputados.gob.mx, which change with every reform.
  - **Do not overwrite anything.**
  - Record the result: it is in the log already.
  - Tell the G1 owner. A new version has to be saved with `hash`, and its transcribed rows re-checked against it, which is a content change.
- **Download error** (DNS, 403, timeout): try another network. Nothing is written except the log line.

## 4. Special cases

- **S22 `S22_CDMX_Codigo_Fiscal_2026.pdf` is WRONG_VERSION:** do not verify it. S22's VERIFIED file is `S22_SAF_Codigo_Fiscal_CDMX_2026.pdf`.
- **Codes with several files** (S1, S3, S22, S28, S30) need `file=…`. The command column includes it.
- **S1 rows:** the manifest notes say later RMF modifications exist only as advance versions. Verify the saved files as they are; whether a later modification matters is a G1 question.
- **Sources the gates cite that are not saved at all:** S5, S8, S12–S17, S19–S21, **S23** (the 2025 personal data law, needed for the X6 incapacity proposal and G7), and S31–S33 (identifier structures, G7).
  1. Download each from its URL in `verify_mexico_sources.py`.
  2. Save it in `docs/mexico/sources/`.
  3. Run `python -m scripts.verify_mexico_sources hash` (adds it as UNVERIFIED).
  4. Record its title, issuer and URL with `set`.
  5. Then run `verify` as above.

## 5. Afterwards

1. Run `python -m scripts.verify_mexico_sources check` again. Then run `python -m scripts.verify_mexico_sources compare`, which checks every transcribed number against the text of its VERIFIED file.
2. Commit `SOURCES_MANIFEST.csv` and `VERIFICATION_LOG.csv` (and any newly saved files) in a PR. The status takes effect only in the deployed repository.
3. Record in the gate evidence (`release-gates/G*/EVIDENCE_DRAFT.md`) which sources moved to VERIFIED, who downloaded them, and when.

Verifying a source **decides nothing about its content**. The transcribed rows stay Draft until the gate owner signs.
