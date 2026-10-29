# Mexico (MX) — Phase 11a Implementation Report: SAT sources, pinned schema set, system concepts

Requested 2026-10-23 ("approved, continue"; then "try it yourself and proceed"). Covers **D1** (the sources) and sub-phase **11a** of `MEXICO_PHASE_11_PLAN.md`. 11b (the builder) and 11c (the preview) are not started.

> **Review required: Rugvedh (ZP-PRIV)** for the 6 new routes, which are platform Super Admin routes and touch no tenant or worker data, and for the migration. Nothing in 11a reads an employee identifier. His after-the-fact reviews of 10c, 10f and 10g remain open.

**Base.**
- `nikhil` = `57ba489`; `main` = `2690517` (PR #125 and the `PRODUCTION_STATE.md` commit).
- Production is at `f6c2a9d1e4b7` (deploy 39897555054 green).

**Alembic.**
- Before: a single head, `f6c2a9d1e4b7` (220 revisions).
- Now: a single head, **`a8e4c1f7d3b5`** (221 revisions).

**Git.** **Staged on `nikhil`, not committed.** The SAT source files themselves are **not** staged (§1).

## 1. D1: the sources, and how they were obtained

**sat.gob.mx cannot be reached from this network.** Its name does not resolve through the router, Google or Cloudflare, and SAT's own name servers (200.33.74.41, 200.57.3.8, 52.55.198.38) did not answer direct queries. Cloudflare reports "No Reachable Authority at delegation sat.gob.mx". `gob.mx` and everything else resolve.

**So every file was taken from the Internet Archive's capture of its official SAT URL**, in raw mode (`id_`: the bytes SAT served, nothing added). Each download was checked against the archive's own SHA-1 digest of the capture: all 8 match. Three XSDs were served gzip-encoded by SAT; the decompressed file is what is saved. Status in `SOURCES_MANIFEST.csv`: **`ARCHIVE_COPY_VERIFIED`**, with the capture time and digest in the note; re-verify against sat.gob.mx when reachable.

| Code | File saved (`docs/mexico/sources/`) | Capture | What it states |
|---|---|---|---|
| S30 | `S30_SAT_cfdv40.xsd` | 2026-08-02 | Comprobante Version fixed `4.0` |
| S30 | `S30_SAT_tdCFDI.xsd`, `S30_SAT_catCFDI.xsd` | 2026-08-02 | imported by both main schemas |
| S30 | `S30_SAT_catCFDI.xls` (`catCFDI_V_4_20260731.xls`) | 2026-08-02 | CFDI 4.0 catalogs; c_CodigoPostal revision 8, published 2026-01-22 |
| S28 | `S28_SAT_nomina12.xsd`, `S28_SAT_catNomina.xsd` | 2024 (only version since 2024) | Nomina Version fixed `1.2` |
| S28 | `S28_SAT_catNomina.xls` | 2022-08 (newest capture) | 13 catalogs; **its codes equal `catNomina.xsd` (2024) exactly in all 13** |
| S4 | `S4_SAT_Guia_llenado_Nomina.pdf` | 2023-06 | "Aplicable para la versión 4.0 del CFDI y el complemento de nómina versión 1.2"; created 2023-03-09; 125 pages; newest edition the archive holds |

Cross-checks, all derived from the files:
- **The five XSDs form a closed set:** cfdv40 imports catCFDI and tdCFDI; nomina12 imports those two plus catNomina. Both main schemas compile **offline**, with every import resolved to a pinned file.
- **SAT's catalog XSD is a superset of the 4.0 workbook.** It still accepts codes the 4.0 catalog has dropped, for example c_RegimenFiscal 609/628/629/630, c_UsoCFDI `P01` and c_TipoRelacion 08/09. **XSD validation alone is therefore not enough:** the builder (11b) must also check codes against the workbook's 4.0 entries, as the plan said.
- **One inconsistency inside SAT's files:** the workbook spells unit code `Dx`, while the XSD accepts only `DX`. The set uses the XSD spelling and records it in `manifest.json` (`caseNormalised`).

**Gaps to state plainly:**
- The S4 guide is the 2023 edition. Any later SAT instruction (for example on the employment subsidy) is not in the saved sources.
- The nómina workbook's newest capture is 2022, but its codes match the 2024 XSD exactly.

**What is in git:**
- Only the 8 new `SOURCES_MANIFEST.csv` rows.
- The source binaries are not staged: the PDF is gitignored, and the 48.7 MB workbook should never be committed.

## 2. The pinned schema set (D2): `backend/app/modules/payroll/mx_cfdi_schemas/sat_2026_08/`

Built by `backend/scripts/mx_build_cfdi_schema_set.py` from the saved sources. The generator refuses unless each source matches its `SOURCES_MANIFEST.csv` hash. It is deterministic: a rebuild is byte-identical, which was checked.

| File | What |
|---|---|
| `cfdv40.xsd`, `nomina12.xsd`, `tdCFDI.xsd`, `catCFDI.xsd`, `catNomina.xsd` | Byte-identical to the sources (7 MB, of which 6 MB is SAT's catCFDI.xsd) |
| `catalogs.json.gz` (1.2 MB) | 29 catalogs, **151,650 rows**: the 13 nómina catalogs plus the CFDI catalogs a payroll receipt uses (customs, colonia, localidad and tax-rate catalogs are not extracted) |
| `manifest.json` | Per-file SHA-256, the XSD checksum, the extract's hash, per-catalog counts, the sources with their hashes and status, case normalisations |
| `../.gitattributes` | `* -text`: **this machine has `core.autocrlf=true` and the repo had no `.gitattributes`**, so git would have rewritten the XSDs' CRLF line endings and production would hold bytes that fail the checksum. A test pins this. |

How the generator reads the files:
- **Every code is spelled as SAT's own XSD enumeration spells it**, so `1.0` in the workbook becomes `001`.
- A workbook code the XSD does not contain stops the build.
- Catalog version metadata is kept as written (for example `Versión 2.0`, `Revisión 1.0`, `Fecha de publicación 2019-12-05`).

`mexico_cfdi_schema.py` (runtime):
- `verify()` refuses a set with any changed or missing file.
- `schema()` compiles with `no_network=True` and a resolver that **refuses any import outside the pinned set**.
- `catalogs()` and `catalog_rows()` stream the extract.

Deploy ships it: production deploys by `git pull`, the same way `route_registry.json` ships.

## 3. Loading a release, and the catalog-name fix

**Loading** (Super Admin → Mexico → CFDI catalogs: **Load sat_2026_08** on a release row):
- Only into an **empty Draft** release of the same versions (4.0 / 1.2), from a verified set.
- One transaction, bulk-inserted in chunks of 5,000 (about 5 s for 151,650 rows on SQLite).
- The row count is checked against the manifest. The release records the set id (`revision`), its XSD checksum and the catalog revision. Audited (`load_pinned_set`).
- The existing four-eyes submit → approve flow applies unchanged; activation is still refused (PAC validation, D3).

**Entries listing:**
- It used to return every row of a release, which would be 151,650 rows in one response.
- It is now filtered (catalog, code or description search), capped (default 200, at most 1,000; a larger `limit` is refused with 422) and returns per-catalog counts.
- The screen has a catalog selector and a search box.

**Fix (existing bug):** approving a canonical earning classification checked its SAT code against **every** catalog of every approved release. A percepción could therefore pass with a code SAT lists only as a deduction.
- It now checks the catalog of the row's own node type: PERCEPCION and SEPARACION → c_TipoPercepcion, DEDUCCION → c_TipoDeduccion, OTRO_PAGO → c_TipoOtroPago.
- Test: a percepción carrying a deduction-only code (taken from the pinned set) is refused; a deducción carrying it is approved.

## 4. System concepts (D4): migration `a8e4c1f7d3b5` (mx_cfdi_system_concepts_m17)

One platform table, `payroll_mx_cfdi_system_concepts`: per release, an engine amount → node type + SAT code + source citation.

**The engine amounts:** `ISR_WITHHELD`, `IMSS_EMPLOYEE`, `INFONAVIT_CREDIT`, `SUBSIDY_APPLIED`, `AGUINALDO`, `VACATION_PREMIUM`, `PTU`, `SEPARATION`, `ANNUAL_ADJUSTMENT_REFUND`, `ANNUAL_ADJUSTMENT_CHARGE`. The special payments are here because the engine emits their lines with no SAT code at all.

**Rules:**
- The code must exist in **that release's** catalog for the node.
- The citation must start "S28" or "S4".
- Only one proposal per concept can wait at a time.
- **A different Super Admin approves.** A newer approval supersedes the old one, enforced by a partial unique index (one APPROVED per release and concept).
- Every step is audited, including refusals.

**Migration on PostgreSQL 17**, 6/6 on three runs:
- SHARE ROW EXCLUSIVE on `users` and `payroll_mx_cfdi_schema_releases` for **37–69 ms**; never on `organizations`; reads continue.
- With a writer on `users`, it fails fast in **5.09–5.27 s** with nothing created.
- No RLS statement; `classify()` puts the table in neither class.

**Proposals (D6): `MEXICO_PHASE_11A_CODE_PROPOSALS.md`.** Every candidate cites its S28 sheet and row and, where the guide speaks, the S4 page.
- **Six are unambiguous:**
  - ISR → deducción 002 (S4 p. 113);
  - IMSS → 001;
  - aguinaldo → percepción 002;
  - vacation premium → 021;
  - PTU → 003;
  - annual-adjustment charge → deducción 101 (S4 p. 112).
- **Four are left to the G1 owner:**
  - INFONAVIT credit: 009 vs 010, and S4 names neither.
  - Subsidy: 002 is clear in S4, but S4 is the 2023 edition.
  - Separation: one engine kind against three SAT codes. That is an **engine gap** for 11b.
  - Annual-adjustment refund: 004 needs a node the engine cannot fill, vs 005.
- No mapping is approved anywhere; these are inputs for two Super Admins.
- **S4 pp. 112–114 contain a complete worked receipt**, the first golden-vector candidate for 11b.

## 5. Tests

| File | Covers |
|---|---|
| `test_mexico_cfdi_schema_set.py` (9) | The set verifies; both schemas compile offline; byte-for-byte storage plus `.gitattributes`; the manifest's sources equal `SOURCES_MANIFEST.csv`; every extracted code is accepted by SAT's XSD, and the five key nómina catalogs equal the XSD exactly; an outside import is refused; a changed XSD, extract or manifest is detected; bad set ids are refused; the generator rebuild is identical (skipped where `xlrd` and the gitignored sources are absent, i.e. in CI) |
| `test_mexico_cfdi_catalog_load.py` (6) | Full load of 151,650 rows; refusals (version, unknown set, non-empty, non-Draft, tampered set with nothing loaded); the catalog-name fix; the system-concept four-eyes flow, supersede, withdraw and audit; routes |
| `test_mexico_cfdi_concept_migrations.py` (6, of which 4 run on PostgreSQL) | m17 SQLite idempotence; PostgreSQL lock mode and duration, fail-fast, real CLI and schema drift |
| Pins | Head and 221 revisions; MX_M17_TABLES; pending objects after `f6c2a9d1e4b7`; production upgrade path (`PLATFORM_TABLES` exempts the new table from the RLS assertion) |

PostgreSQL 17:
- m17: 6/6 on three runs.
- Production upgrade path from `e1a3c5e7f9b2` with a live reader on `users`, plus the named RLS exceptions and m16: **11/11**.

Route registry: regenerated; it adds **exactly the 6 new routes**, all platform `super_admin`, and nothing else changed. Manifest: regenerated; +1 line. Frontend: ESLint clean on the changed files; `check:undefined` reports 566 files with no undefined names; `vite build` passes.

## 6. Browser

Real Chrome (headless) against a scratch database. The harness is in `phase11a-evidence/harness/`. **on 9/9 PASS** (the first run was 8/9: my check expected a silent clamp, but the route correctly refuses `limit` > 1,000 with 422; the check was corrected and the whole run repeated).

| # | Check |
|---|---|
| on-1 | Pinned set `sat_2026_08` listed: Verified, 4.0 / 1.2, 151,650 rows |
| on-2 | Register a Draft release → **Load sat_2026_08** → every row loaded; the row shows the set |
| on-3 | Filter c_TipoPercepcion (44); search "Aguinaldo" → 002 "Gratificación Anual (Aguinaldo)" |
| on-4 | The loader cannot approve; a second Super Admin approves |
| on-5 | ISR proposed as OTRO_PAGO "101" → refused ("not in c_TipoOtroPago") |
| on-6 | ISR → DEDUCCION 002 citing "S28 c_TipoDeduccion row 7; S4 p. 113": refused to the proposer, approved by the second Super Admin |
| on-7 | c_CodigoPostal: `limit` 5,000 refused (422); 1,000 returns 1,000 of more than 90,000 |
| on-z1 / z2 | NL unchanged; no 5xx, no page errors |

The only 4xx responses were the three deliberate refusals, which also account for the three console errors. Screenshots, inspected:
- `on_01_pinned_set.png`: the verified set;
- `on_02_entries_filtered.png`: c_TipoPercepcion (44), "Aguinaldo", 1 match;
- `on_03_system_concept_approved.png`: ISR_WITHHELD DEDUCCION 002, APPROVED, with its citation.

## 7. Full suite

Five sequential chunks on scratch SQLite, run alone (never alongside the browser check): **7,182 passed**, 123 skipped, 2 xfailed, and **4 local-only failures**, none Mexico. These are the same four as in 10f and 10g. (The first run was cut off when the session ended; chunks 0–3 were rerun in full.)

| Chunk | Result |
|---|---|
| 0 | 853 passed, 15 skipped, 3 failed (route registry) |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed (Hong Kong docs) |
| 2 | 1,335 passed, 35 skipped |
| 3 | 1,657 passed, 66 skipped (includes the three 11a test files) |
| 4 | 1,054 passed, 6 skipped |

**The 4 local-only failures:**
- **3 route-registry tests.** They name only `/health/version`, `/health/ready` and their `/api` twins: the uncommitted routes in `main.py`. The 6 new routes are registered.
- **`test_hong_kong_configuration…`.** It reads the uncommitted Hong Kong docs.

## 8. What this does in production when merged

| Change | Production effect |
|---|---|
| Migration `a8e4c1f7d3b5` | One new, empty platform table (no RLS). About 40–70 ms SHARE ROW EXCLUSIVE on `users` and the (empty) schema-release table; fails fast after about 5 s. |
| Pinned set in the repo | About 8 MB of files; read only when a Super Admin loads a release. |
| 6 Super Admin routes | New; platform only. Nothing happens until a Super Admin registers and loads a release. |
| Entries listing | Now filtered and capped (only the Super Admin catalogs tab calls it). |
| Classification approval | Stricter: the code must be in its own node's catalog. No canonical classification exists in production, so nothing changes state. |

**Net:** additive. Mexico stays dormant; no CFDI can be generated (the builder and signer still refuse); no other jurisdiction changes.

## 9. Open

- **11b**: the builder and validation. It starts with the four undecided mappings (§4) and the separation-kind gap, using S4 pp. 112–114 as the first golden vector.
- Rugvedh's review of this PR, and his pending reviews of 10c, 10f and 10g.
- Re-verify the 8 source files against sat.gob.mx from a network that can reach it. The manifest notes say so.
