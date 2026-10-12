# Germany BMF PAP 2026 — Source Provenance

**Phase:** 8BD
**Branch:** `nikhil`
**Worktree:** `D:\zoiko_payroll_platform\zpp-nikhil-extract`
**Date:** 2026-09-09
**Type:** Document-only evidence record (no production activation; no code gate flipped)

This document records the authoritative provenance of the official German federal
(BMF) Programmeablaufplan (PAP) 2026 machine-readable artifact that Zoiko's Germany
wage-tax implementation is built against. It deliberately **does not** assert that
production activation is authorized — it records *what the source is, where it comes
from, that it is the final official publication*, and the licensing terms as published
by the BMF. The separate production-gate decision is in the main Phase 8BD report and
the evidence matrix.

---

## 1. Official Publication Identity

| Field | Value |
|---|---|
| Tax year | 2026 |
| Machine PAP name | `Lohnsteuer2026` |
| Version | `version="1.0"` / `versionNummer="1.0"` |
| Root element | `<PAP name="Lohnsteuer2026" version="1.0" versionNummer="1.0">` |
| Internal metadata comment | `Stand: 2025-10-23 12:40`, `ITZBund Berlin` |
| Issuing authority | Bundesministerium der Finanzen (BMF), ITZBund (Informationstechnikzentrum Bund) |
| Governing statute | § 39b Abs. 6 / § 51 Abs. 4 Nr. 1a EStG (after § 39c EStG / wage-tax deduction attributes) |
| Official linking page (BMF) | https://www.bundesfinanzministerium.de/Datenportal/Daten/frei-nutzbare-produkte/Anwendungen/Programmablaufplan-2026/Programmablaufplan-2026.html |
| Developer interface page (BMF) | https://www.bmf-steuerrechner.de/interface/pseudocodes.xhtml |

The BMF-Schreiben dated **12 November 2025** (GZ IV C 5 - S 2361/00025/016/028, signed
Hensel, Matthias) formally transmits the final 2026 PAPs as Anlage 1 (maschinelle
Berechnung), Anlage 2 (Lohnsteuertabellen, manuell), and Anlage 3 (DBA limit for
pension benefits).

---

## 2. The Authoritative Machine Artifact

The official final XML pseudocode is `Lohnsteuer2026.xml`, published on the BMF's own
Datenportal under the "Programmablaufpläne zur Lohnsteuer für/ab 2026" dataset.

| Field | Value |
|---|---|
| Dataset title | Programmablaufpläne zur Lohnsteuer für/ab 2026 |
| Dataset "Aktualisiert" (updated) | **12.11.2025** |
| Akt.-Intervall | Jährlich |
| Zeitbezug | Nov. 2025 – heute |
| Veröffentlicher | Bundesministerium der Finanzen |
| Lizenz (as published) | **CC BY-ND 4.0** |
| XML download format | APPLICATION/XHTML+XML |
| Download URL | https://www.bundesfinanzministerium.de/Datenportal/Daten/frei-nutzbare-produkte/Anwendungen/Programmablaufplan-2026/Programmablaufplan-2026-XML.xhtml?__blob=publicationFile&v=3 |
| Also mirrored on | https://www.bmf-steuerrechner.de/javax.faces.resource/daten/xmls/Lohnsteuer2026.xml.xhtml |

---

## 3. Hash, Size, Content Identity (Re-verified 2026-09-09)

Re-downloaded this phase directly from the authoritative BMF Datenportal URL above and
hashed with SHA-256:

| Field | Value |
|---|---|
| **Byte length** | **65,585** |
| **SHA-256** | **`63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4`** |
| Root identity | `<PAP name="Lohnsteuer2026" version="1.0" versionNummer="1.0">` (confirmed) |
| Internal comment | `Stand: 2025-10-23 12:40`, `ITZBund Berlin` (confirmed present) |
| EVAL nodes | 215 |
| IF nodes | 78 |
| EXECUTE nodes | 41 |
| Total executable nodes | 334 |
| Input fields | 35 |
| Output fields | 12 |
| Encoding | UTF-8 with BOM |
| Well-formed | Yes (stdlib expat parses cleanly) |

**This hash is byte-for-byte identical** to the hash recorded across every prior phase
(8B, 8C-1, 8C-2, 8C-3, 8F, 8G-2) from the `bmf-steuerrechner.de` mirror. The file the
BMF publishes on its final (12.11.2025) Datenportal release is therefore the **exact
same bytes** as the file all prior phases tracked.

> Note: the file's internal `Stand` comment remains `2025-10-23` (the date the file's
> content was frozen), while the Datenportal *dataset* metadata says "Aktualisiert:
> 12.11.2025" (the formal publication). This is a documentation/publication-timing
> distinction: the BMF's final official data-portal release carries precisely this XML
> and no other, and no later-revised 2026 XML exists on the portal. See §5.

---

## 4. Licensing Terms (As Published by BMF)

The BMF Datenportal categorizes this dataset as a **"frei nutzbares Produkt"** (freely
usable product) and its `Nutzungshinweise` (usage notes) — which the dataset's license
field links to — state verbatim:

> Alle als **"frei nutzbares Produkt"** gekennzeichneten Inhalte unterliegen der
> Creative Commons Lizenz **"Namensnennung – Keine Bearbeitungen 4.0 International"**
> (**CC BY-ND 4.0**).
>
> Demnach dürfen Sie: **Teilen** — das Material in jedwedem Format oder Medium
> vervielfältigen und weiterverbreiten und zwar für **beliebige Zwecke, sogar
> kommerziell**.
>
> Unter den folgenden Bedingungen:
> - **Namensnennung**: Bundesministerium der Finanzen, CC BY-ND 4.0
> - **Keine Bearbeitungen** — Wenn Sie das Material remixen, verändern oder darauf
>   anderweitig direkt aufbauen, dürfen Sie die **bearbeitete Fassung** des Materials
>   **nicht verbreiten**.
> - **Keine weiteren Einschränkungen**

Source: https://www.bundesfinanzministerium.de/Datenportal/Nutzungshinweise/nutzungshinweise.html

### What this establishes
- **Commercial use is explicitly permitted** by the license text ("sogar kommerziell").
- **Attribution to the BMF is required.**
- **NoDerivatives**: redistribution of *modified/derived* copies of the material is
  prohibited.

### What this does NOT by itself establish (Action Required — Legal)
Whether **implementing / porting the PAP XML algorithm into another programming
language and running it internally** (as Zoiko's interpreter does, without
redistributing a modified XML file) constitutes a "Bearbeitung" (derivative) that the
ND clause restricts, is a **genuine legal question** that only qualified legal counsel
can answer. The pragmatic separation — *execute faithfully, never redistribute a
modified XML, attribute BMF* — is the conservative reading, but it must be confirmed
by legal review before commercial/production activation is treated as licensed.

**This is recorded as `LEGAL_REVIEW_REQUIRED` / `HUMAN_ACTION_REQUIRED`, NOT as an
engineering authorization.** No code path infers `licensing_authorized = true` from
this document.

---

## 5. Source Finality Assessment

Prior phases held `PAP_SOURCE_FINALITY = "OPEN"` because the XML's internal `Stand`
comment (2025-10-23) predates the PDF's final publication date (12.11.2025), and no
primary-source reconciliation had been obtained.

**New evidence this phase:** the BMF's own final Datenportal release — metadata
"Aktualisiert: 12.11.2025", dataset thumbprint `v=3`, matching the date and the same
publication family as the final 12.11.2025 BMF-Schreiben and Anlage 1 PDF — publishes
the XML that carries hash `63d898…`/`Lohnsteuer2026` v1.0. There is **no other,** newer,
or differently-hashed 2026 machine-XML on the official portal. This is direct BMF
confirmation that the tracked XML **is** the final official 2026 machine PAP.

### Classification
- **Status:** `FINAL_OFFICIAL_RELEASE_CONFIRMED` (provenance-level).
- **Residual gap:** a *full* byte-level diff of the XML against the whole Anlage 1 PDF
  (beyond the 7-constant spot-check recorded in Phase 8B) has not been performed, and
  the textual `Stand` comment vs. publication-date difference remains a
  documentation-timing artifact rather than a demonstrated content difference.
- **Decision:** The engineering `PAP_SOURCE_FINALITY` code constant in
  `germany_pap/adapter.py` is **left `"OPEN"`** this phase. The evidence upgrade is
  recorded here and in the report, but the `OPEN → RESOLVED` flip is deferred to the
  activation decision point, where it must be combined with (a) the legal licensing
  clearance and (b) all eight production gates actually satisfied. This is the
  conservative posture mandated by the phase instructions ("If source finality cannot
  be proven conclusively, keep it OPEN") — we have strong provenance but not the
  formal legal + byte-level finality package.

---

## 6. Source Provenance Chain (for the governed asset registry)

When a `PapAlgorithmAsset` is ingested, each field below is recorded/re-verifiable from
this document:

| Provenance field | Value |
|---|---|
| source identifier | `Lohnsteuer2026` v1.0 |
| official authority | BMF; hosting ITZBund |
| publication identity | PAP 2026, Anlage 1 (maschinelle Berechnung), BMF-Schreiben 12.11.2025 |
| publication date | 12.11.2025 (dataset metadata) / file internal Stand 2025-10-23 |
| retrieval timestamp | 2026-09-09 (this phase re-download) |
| SHA-256 | `63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4` |
| byte length | 65,585 |
| effective period | Tax year 2026 |
| source document | Official BMF Datenportal XML download (see §2 URL) |
| licensing | CC BY-ND 4.0 (as published); L̵egal review pending for runtime-interpretation use |
| verification status | SOURCE_HASH_MATCH across 8B, 8C-1/2/3, 8F, 8G-2, 8BD |
| reviewer / approval | Human/legal review required before production activation |

---

## 7. Third-Party Corroboration (not statutory authority)

The IHK Rhein-Neckar and IHK Darmstadt pages and `govdata.de` independently describe the
same 12.11.2025 final PAP-2026 publication (Anlagen 1–3) and the "geringfügige
redaktionelle Änderungen" vs. the 25.9.2025 draft. These are corroborating evidence
only; the BMF Datenportal + Nutzungshinweise are the statutory authority cited above.
