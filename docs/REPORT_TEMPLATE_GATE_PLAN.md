# Report templates blocked by a country activation gate: plan

> **Superseded 2026-11-25 (gate removal, owner decision).** The release gates, evidence, sign-offs and parallel-run requirements described here no longer apply: this country goes live like Spain once its pack is Active. See `docs/GATE_REMOVAL.md` and (for JP, NZ, PL, MY, ZA and BE: their template hooks no longer refuse). Kept for history.

*Read-only analysis, 2026-11-18. No code, data, evidence, gate or decision was created, changed, verified or signed.*

**Scope:** 38 Published report templates that the read-only dry run (`python -m scripts.report_stuck_published_templates`, group B) lists as refused by their country's `template_activation_refusal` hook:

| Country | Templates | Effort |
|---|---|---|
| Hong Kong | 8 | Small |
| South Africa | 1 (`ZA_IRP5_PREVIEW`) | Small–medium |
| Japan | 3 | Medium–large |
| Malaysia | 2 | Large |
| New Zealand | 2 | Large |
| Poland | 3 | Large |
| Belgium | 5 | Large |
| Mexico | 11 | Large |
| Brazil | 3 | Largest |

Countries are ordered by least effort.

**Where the gate sits:** `service._set_report_template_status`:
1. four-eyes R1/R2;
2. the **country hook**;
3. R3 ("the approver may not activate", for `_APPROVER_NOT_ACTIVATOR_COUNTRIES`).

See `docs/REPORT_TEMPLATE_GOVERNANCE.md`.

**Shared recording steps:**
- **Source evidence:** Super Admin → Compliance → *country* → **Sources** / **Source Evidence** tab (`SourceEvidencePanel`):
  1. **Add Source** (`POST /api/super-admin/compliance/source-artifacts`).
  2. **Upload File** (`POST …/source-artifacts/{id}/upload`), which records the SHA-256.
  3. A **different** Super Admin clicks **Mark reviewed** (`PUT …/source-artifacts/{id}/review`).
- **Template lifecycle:** Super Admin → Report Templates → *country* (`ReportTemplateLayout`): **Approve** (`PUT /api/super-admin/report-templates/{id}/approve`) and the status select (`PUT …/{id}/status`).
- **Published templates cannot be edited.** A Published template can only move to Active or Superseded (`REPORT_TEMPLATE_TRANSITIONS`). Anything that must change on the template itself, such as its linked source document, needs a **new version**.

## The structural finding

Only **Hong Kong, South Africa and Mexico** have gates that evidence can satisfy. The other six refuse **unconditionally**: the hook returns the refusal without reading any table, flag or evidence.

| Country | Hook (file:line) | Reads anything? |
|---|---|---|
| Belgium | `belgium_service.py:463-465` | No, always refuses |
| Brazil | `brazil_service.py:98-99` | No, always refuses ("not built yet") |
| Japan | `japan_service.py:862-868` | No, always refuses for JP |
| Malaysia | `malaysia_service.py:1462-1468` | No, always refuses for MY |
| New Zealand | `new_zealand_service.py:1570-1576` | No, always refuses for NZ |
| Poland | `poland_service.py:1411-1417` | No, always refuses for PL |
| South Africa | `south_africa_service.py:941-955` | Yes: a **code constant** (the BRS catalogue), not the database |
| Hong Kong | `hong_kong_service.py:2751-2779` | Yes: linked, reviewed, hashed source evidence + approval + activator ≠ approver |
| Mexico | `mexico_service.py:319` → `mexico_report_service.mx_report_activation_refusal` (`:542-554`) | Yes: gates SIGNED, pack Active, fields, payslip field proof |

**For the six unconditional gates, no evidence or sign-off can ever be enough.** The first step is a gate redesign: replace the fixed refusal with a condition that implements what the message already promises (schemas archived, filing path certified, the named G-gate passed). This is a governed code change:
- **It must not weaken the gate.** The new condition must be at least as strict as the gate's own stated requirement.
- **It is a maker-checker / activation-gate change**, so it needs the country owner's agreement and ZP-PRIV review (Rugvedh) before merge.
- **Splitting internal reports out of a filing gate is a policy relaxation, not an engineering default.** For example, letting a payroll register activate before the filing-certification gate G3 passes. Only the country owner can decide it.

---

## 1. Hong Kong (8): small

**Gate** (`hong_kong_service.py:2751-2779`). It refuses, in order, when:
1. the template has no `source_document_id`: "…has no source evidence — link the official source document (a SourceArtifact) before activation.";
2. the linked artifact is not reviewed by another Super Admin (`_reviewed_by_other`, `:2601-2603`: `reviewer_id` set, `file_path` set, `reviewer_id != created_by_id`);
3. the artifact has no `checksum_sha256`;
4. the artifact is superseded;
5. the artifact's title contains `[UNVERIFIED`;
6. the template has no `approved_by_id`;
7. the activator is the approver.

**Templates** (seed `seed_hong_kong`, `seed_statutory_report_templates.py:1785+`):
- `HK-BIR56A`, `HK-IR56B`, `HK-IR56E`, `HK-IR56F`, `HK-IR56G`, year 2025/26;
- `HK-EMPF-REMITTANCE`, `HK-MPF-CONTRIBUTION-RECORD`, `HK-TERMINATION-STATEMENT`, year 2026.

The seed never sets `source_document_id`, so all eight fail at check 1. All carry "[INTERNAL LAYOUT — NOT THE IRD/eMPF PRESCRIBED FORMAT, gate G2]". The template gate does not check G2.

**Already in the repo** (`docs/HONG_KONG_RELEASE_EVIDENCE/`):
- `HK_ACTIVATION_RUNBOOK.md:22`, step 5: "link reviewed source evidence → approve (≠ editor) → publish → activate (≠ approver)".
- `HK_SUPER_ADMIN_GOVERNANCE.md` §4.
- `HK_SOURCE_EVIDENCE_REGISTER.md`: sources #1–#25 have a URL and SHA, but "File stored: no", "Reviewed: no". Likely template sources:
  - #4, IRD employer obligations for BIR56A / IR56B / E / F / G;
  - #5, PAM 46(e);
  - #6 / #7, MPFA.
- `HK_G2_EVIDENCE_PACKAGE.md`: the official IRD schemas and the eMPF specification are **not** held.

**Remaining work:**
- **(a) Engineering (optional, small):**
  - The shared layout has no "New version" action, and Source Document is display-only on the Overview. A Hong Kong new-version helper, like Mexico's `mx_template_new_version`, that copies all metadata and lets the Draft link a source document would save re-typing.
  - Optionally roll the five IRD templates to YA 2026/27: the HK readiness check counts only the current year's templates (`hong_kong_service.py:2891-2909`).
- **(b) Human evidence:** the official document file for each template's source.
  - Uploading to an existing registered artifact must match its registered SHA. If the page has changed, register a new artifact.
  - **Decision needed:** are the IRD/MPFA guidance pages acceptable as "official source" for an internal layout, given that the prescribed schemas (gate G2) are not held?
- **(c) Sign-offs:**
  - Three distinct Super Admins: the creator of the new version, an approver who is not an editor (HK any-editor rule), and an activator who is not the approver.
  - The artifact's reviewer must differ from its registrant.
  - The platform owner authorises the release (`HK_ACTIVATION_RUNBOOK.md:8`).
- **(d) Steps, per template:**
  1. Compliance → Hong Kong → **Source Evidence**: **Add Source** with a descriptive title, not an `HK-GATE-*` tag, then **Upload File**.
  2. A different Super Admin clicks **Mark reviewed**.
  3. Report Templates → Hong Kong → **New Report** (`NewReportTemplateModal`):
     - same **Template Key**, a new **Version**, the correct **Reporting Year**;
     - **Document Scope**: the form defaults to AGGREGATE, so pick PER_EMPLOYEE where the template is per-employee;
     - **Source Document** = the reviewed artifact.

     This calls `POST /api/super-admin/report-templates` (`upsert_report_template`), which creates a Draft with `previous_version_id` and copies the components and fields.
  4. Super Admin B, who made none of its edits, clicks **Approve**.
  5. Status → Approved → **Published**.
  6. Super Admin C (not B) sets **Active**.
  7. Optionally move the old Published version to **Superseded**.
  8. Check Compliance → Hong Kong → **Activation & Governance** coverage, which flags "(no source)".

**Observation:** `_reviewed_by_other` compares the reviewer with the artifact's **registrant** (`created_by_id`), not with whoever uploaded the file. A seeded artifact with no registrant passes with any reviewer. This is not a change request, but a reviewer should know.

---

## 2. South Africa: ZA_IRP5_PREVIEW (1): small–medium

**Gate** (`south_africa_service.py:941-955`):
- It applies only to report types starting `ZA_EMP501` or `ZA_IRP5`, so `ZA_PAYROLL_REGISTER`, `ZA_EMP201_SUMMARY` and `ZA_COIDA_EARNINGS` pass.
- It refuses with "South Africa: SARS PAYE BRS v{version} source-code catalogue is not archived (evidence S4) - {type} templates stay inactive until it is." when `ZA_BRS_CATALOG[version]["source_codes"]` is empty.
- `version` is the code constant `za_brs_version = "25.3.0"` (`south_africa_content.py:288-289`).
- `ZA_BRS_CATALOG = {"25.3.0": {"source_codes": {}, "fields": {}, "evidence": "S4"}}` (`:377-379`).
- No ZA_EMP501 template is seeded.

**Already in the repo:**
- the readiness check `brs_catalog_present` (`south_africa_readiness.py:155-160`);
- `docs/south-africa/release-gates/G1/CHECKLIST.md:13` and `G3/CHECKLIST.md:8`;
- `backend/tests/fixtures/za_golden/` (about 50 fixtures).

No archived BRS document.

**Remaining work:**
- **(a) Engineering:**
  - Once the BRS exists, fill `ZA_BRS_CATALOG["25.3.0"]["source_codes"]` (and `fields`) from it. `map_to_brs` (`south_africa_filing.py:249-275`) needs a code for every non-zero `ZA_CERTIFICATE_LINES` line.
  - Update `tests/test_south_africa_filing.py:286-290`.
  - **Gate gap to raise with the owner:** the gate passes on the constant alone. It does not check that S4 is a reviewed SourceArtifact. Tightening it to also require reviewed S4 evidence would be stricter, not weaker.
- **(b) Human evidence:**
  - the official SARS PAYE BRS v25.3.0 (S4);
  - for G3, an e@syFile / eFiling rehearsal.
- **(c) Sign-offs (`docs/south-africa/release-gates/README.md:13-18`; no names given):**
  - G1: Payroll/Tax lead + SA reviewer;
  - G3: Tax Ops.
- **(d) Steps:**
  1. Compliance → South Africa → **Sources**: add the BRS (S4), Upload File; a different Super Admin clicks Mark reviewed.
  2. The reviewed code change fills the catalogue and is deployed.
  3. Check the **Readiness** tab (`GET /api/super-admin/compliance/south-africa/readiness`).
  4. Activate the template; the activator must not be the approver, since ZA is an R3 country.

---

## 3. Japan (3): medium–large

**Gate** (`japan_service.py:862-868`): unconditional for JP and `JP_*`. "Japan filing and payment-report templates stay inactive until the official form revision and the JP-1 evidence decision are recorded."
- **"JP-1" is not defined anywhere** in the code; it is mentioned only here and in a note at `:1011`.
- The existing decisions are `JP_DECISIONS` D-1 to D-5 (`:922-928`), recorded as `JP-DECISION-D-n` artifacts (`_jp_evidence`, `:931-940`).
- No "form revision" record exists. The closest is gate G5, with `JP_EXPORT_SCHEMAS = {}` (`japan_content.py:198`).
- JP is not in `_APPROVER_NOT_ACTIVATOR_COUNTRIES`.

**Templates:**
- `JP-PAYROLL-REGISTER` and `JP-WHT-SI-SUMMARY`: internal reconciliations.
- `JP-GENSEN-PREVIEW`: "internal labels only, not the NTA form layout" (seed `:2832-2858`).

**Already in the repo:**
- `docs/japan/release-gates/G0–G8.md` (tags `JP-GATE-Gn`; sign-off tables blank);
- `docs/japan/RUNBOOK_GO_LIVE.md`;
- `scripts/seed_japan_canonical_packs.py`.

There are no Japan source files and no `jp_golden` fixtures.

**Remaining work:**
- **(a) Engineering:**
  1. **First, the owner must define** what "JP-1" means and what record proves an "official form revision".
  2. Then rewrite the hook so it checks that record, at least as strictly as its message says. For example: GENSEN needs G5 plus an archived NTA form revision.
  3. Populate `JP_EXPORT_SCHEMAS` and build the exporters for the four `DOCUMENTS` (`japan_filing.py:36`).
  4. Optionally add JP to R3.
- **(b) Human evidence:**
  - the NTA Gensen Choshuhyo form revision;
  - "e-Tax / eLTAX / Japan Pension Service schema versions and a test submission receipt" (`G5.md`);
  - the G1 NTA tables with SHA-256.
- **(c) Sign-offs (`docs/japan/release-gates/README.md`; no names given):**
  - G5: Compliance;
  - G1: Payroll / tax lead;
  - G8: CTO, plus `JP-SIGNOFF-PRODUCT / -COMPLIANCE / -ENGINEERING`;
  - D-1 to D-5: owner decisions.

  **Decision needed:** whether the two internal reports may activate before G5. That is a relaxation, so it is the owner's call.
- **(d) Steps:** Compliance → Japan → **Sources**: add the artifact with the tag as Form/Publication # (e.g. `JP-GATE-G5`, `JP-DECISION-D-1`), Upload File, a second Super Admin clicks Mark reviewed. Check **Readiness** (`GET /api/payroll/japan/readiness`).

---

## 4. Malaysia (2): large

**Gate** (`malaysia_service.py:1462-1468`): unconditional for MY / `MY_*`. "Malaysia statutory form templates stay inactive until the official authority layouts are archived and the filing path is certified (gate G3, MY-022)."

**What G3 requires** (`malaysia_readiness.py:164-170`):
- every form in `IN_SCOPE_FORMS` has `versions` in `MY_FORM_SCHEMA_CATALOG`, which is deliberately empty (`malaysia_content.py:192-202`);
- the `G3_KEYS` due-date rows are signed;
- `MY-GATE-G3` is reviewed by another Super Admin.

**Templates:** `MY-PAYROLL-REGISTER`, `MY-STATUTORY-SUMMARY`, `MY-EA-PREVIEW`. The gate treats them identically; "2" is the number Published.

**Already in the repo:**
- `docs/malaysia/release-gates/G3.md` (owner "Integration + Payroll Ops"; sign-off table blank);
- `docs/malaysia/RUNBOOK_GO_LIVE.md:32`: layouts are added "through a reviewed code change".

There is no MY evidence folder and no golden fixtures.

**Remaining work:**
- **(a) Engineering:**
  - **Gate redesign:** require G3 passed (`my_readiness()`, `:196-214`) instead of always refusing. Update `tests/test_malaysia_service.py:449`.
  - Add archived layouts to `MY_FORM_SCHEMA_CATALOG`; there is no loader, it is a code edit.
- **(b) Human evidence:**
  - the HASiL / KWSP / PERKESO / HRD layouts for PCB, EPF, EIS, HRD, EA, Form E, CP8D, CP22, CP22A and CP21;
  - "a test submission and receipt per authority, and the correction / rejection procedure" (G3.md);
  - sources for the due-date rows.
- **(c) Sign-offs:** G3, Integration + Payroll Ops (no names).
- **(d) Steps:**
  1. Compliance → Malaysia → **Sources**: `MY-GATE-G3`, Upload, a second admin clicks Mark reviewed.
  2. Sign the due-date rows in **Events & forms / Signing status**.
  3. Check **Release gates** (`GET /api/super-admin/compliance/jurisdictions/MY/statutory-summary`).

## 5. New Zealand (2): large

**Gate** (`new_zealand_service.py:1570-1576`): unconditional for NZ / `NZ_*`. "New Zealand filing and payment templates stay inactive until the payday-filing schema is certified (gate G3)." This is documented as intended (`docs/new_zealand/IMPLEMENTATION_HANDOFF_P3_P10.md:320`).

**What G3 requires** (`nz_readiness.py:128-133`):
- `NZ_EXPORT_SCHEMAS` is non-empty (it is `{}`, `new_zealand_content.py:164`);
- the `G3_KEYS` rows are signed;
- `NZ-GATE-G3` is reviewed.

**Templates:** `NZ-PAYROLL-REGISTER`, `NZ-EI-SUMMARY`. The latter is "NOT the filing itself".

**Already in the repo:**
- `docs/new_zealand/release-gates/G3.md` (owner "Compliance (IRD gateway)");
- `RUNBOOK_GO_LIVE.md:48`;
- `nz_filing.py:326`, which refuses submission without a schema.

**Remaining work:**
- **(a) Engineering:** gate redesign to require G3 passed (update `tests/test_nz_phase4.py:75-76`); the schema entry in `NZ_EXPORT_SCHEMAS`.
- **(b) Human evidence:**
  - IRD gateway onboarding and schema certification, plus the payday-filing specification version;
  - sources for the `nz_*` filing and remittance rows.
- **(c) Sign-offs:**
  - G3: Compliance (IRD gateway).
  - Decision D-3 ("Payday filing: JSON preview only until gate G3") must be revisited.
- **(d) Steps:**
  1. Compliance → New Zealand → **Sources**: `NZ-GATE-G3`, Upload, a second admin clicks Mark reviewed.
  2. Sign the rows in **Filing & remittance**.
  3. Check **Release gates** (`GET /api/payroll/new-zealand/readiness`).

## 6. Poland (3): large

**Gate** (`poland_service.py:1411-1417`): unconditional for PL / `PL_*`. "Poland ZUS / PIT form templates stay inactive until the official schemas are archived and the filing path is certified (gate G4, PL-019)."

**What G4 requires** (`poland_readiness.py:150-157`):
- `versions` for DRA, RCA, RSA, ZUA, ZZA, ZWUA, PIT11 and PIT4R in `PL_FORM_SCHEMA_CATALOG` (empty, `poland_content.py:198-209`);
- the `G4_KEYS` rows are signed;
- `PL-GATE-G4` is reviewed.

**Templates:** `PL-PAYROLL-REGISTER`, `PL-ZUS-DRA-SUMMARY`, `PL-PIT11-PREVIEW`.

**Already in the repo:**
- `docs/poland/release-gates/G4.md` (owner "Integration + Payroll Ops");
- `RUNBOOK_GO_LIVE.md:43`;
- `backend/tests/fixtures/pl_golden/` (8 fixtures, "NOT the AC-PL-02 certification fixtures");
- `poland_filing.py:551`.

**Remaining work:**
- **(a) Engineering:** gate redesign to require G4 passed (update `tests/test_poland_service.py:414-415`); the catalogue `versions` entries.
- **(b) Human evidence:**
  - ZUS KEDU / e-Płatnik and e-Deklaracje schema versions;
  - "a submission / rejection / correction rehearsal with receipts, and an NRS / tax-micro-account settlement reconciliation (AC-PL-05)";
  - sources for the due-date rows.
- **(c) Sign-offs:** G4, Integration + Payroll Ops (no names).
- **(d) Steps:**
  1. Compliance → Poland → **Sources**: `PL-GATE-G4`, Upload, a second admin clicks Mark reviewed.
  2. Sign the rows in **Filing & operations**.
  3. Check **Release gates**.

---

## 7. Belgium (5): large

**Gate** (`belgium_service.py:463-465`): unconditional. "Belgium form templates (Dimona, DmfA, 281.10, payslip) stay inactive until the authority schemas are archived and the filing path is certified (gate G3)."

**What G3 requires** (`belgium_readiness.py:140-155`):
- a certified transmission adapter: impossible today, because `belgium_filing.adapter_for()` always returns `UncertifiedAdapter` (`belgium_filing.py:256-257`);
- a signed, SHA-matched archived XSD per form (DIMONA, DMFA, FINPROF, BELCOTAX);
- reviewed connectivity evidence `BE-CONNECTIVITY-{DIMONA,DMFA,FINPROF,BELCOTAX}`.

`belgium_filing.RENDERERS = {}` (`:77`).

**Templates:**
- `BE-PAYROLL-REGISTER` and `BE-DMFA-274-SUMMARY`: internal totals, "NOT the declarations themselves".
- `BE-INDIVIDUAL-ACCOUNT`, `BE-BELCOTAX-EMPLOYEE-COPY`, `BE-HOLIDAY-CERTIFICATE`: employee documents, generated only when Active (`belgium_reports.py:370`).

**Already in the repo:**
- `docs/belgium/sources/inbox/`: DmfA rate files 2026 Q1–Q4, the B9 glossary, Staatsblad PDFs, each with `.meta.txt`;
- `docs/belgium/sources/DOWNLOAD_LIST.md` §F: the XSDs still needed are F1–F5 (DmfA 2026/2–3, Dimona, FinProf, Belcotax);
- authority request letters (`docs/belgium/authority/01–04`);
- `BELGIUM_ACTIVATION_RUNBOOK.md`, `BELGIUM_AUTHORITY_ONBOARDING.md`, `STAGING_REHEARSAL.md`;
- `guides/SUPER_ADMIN_GUIDE.md`.

**Remaining work:**
- **(a) Engineering:**
  - Gate redesign implementing G3 per form.
  - Payload→XSD renderers in `RENDERERS`.
  - A certified `TransmissionAdapter`, once a channel exists.
  - Authority codes still `"PENDING_CONTENT"` (G-33).
- **(b) Human evidence:**
  - the F1–F5 XSDs and specifications (FinProf is "not found publicly");
  - channel certification and credentials, with accepted test submissions;
  - the DmfA / FinProf / Belcotax code lists;
  - each launch employer's mandate.
- **(c) Sign-offs (roles only):**
  - G3: Integration;
  - schemas and mappings: Integration lead + Belgian specialist;
  - channel: Integration lead + Security;
  - mandates: Payroll operations + each employer;
  - open items G-08, G-31 and G-33 (`BELGIUM_GAPS_AND_DECISIONS.md`).

  **Decision needed:** whether the internal register / summary may be decoupled from G3. That is a relaxation, so it is the owner's call.
- **(d) Steps:**
  - **XSD:** Compliance → Belgium → **Sources**, Upload, a second admin clicks Mark reviewed.
  - **Schema-version rows:** **Signing status** → export the workbook → fill the schema sheet → **Workbook (.xlsx)** dry run → **Confirm import** → a second admin clicks **Sign N selected**.
  - **Connectivity:** **Overview** → gate evidence → **Record evidence**, then another admin clicks **Accept** (`POST /api/super-admin/compliance/belgium/gate-evidence`, `…/{id}/decide`).
  - **Check:** `GET /api/super-admin/compliance/belgium/readiness`.

---

## 8. Mexico (11): large

**Gate:** `mx_report_activation_refusal` (`mexico_report_service.py:542-554`). It refuses with "Mexico report-template activation is refused: …" and the reasons:
- **release gate(s) not SIGNED** (`:523-525`): a gate is SIGNED by a current `MX-GATE-Gn` SourceArtifact with a file, a registrant, and a different reviewer (`mexico_service._mx_evidence`, `:71-79`);
- **pack `MX-PAYROLL-<year>` not Active** (`:528-535`; an ISN return also needs `MX-ISN-<state>-<year>`);
- **the template has no fields**, for snapshot-field templates;
- **the payslip field proof** (`:472-509`): a committed Mexican payslip of the report's run type must resolve every field.

**Templates and gates** (`MX_REPORT_GATES`, `:449-458`):
- Dedicated generators need gates + pack.
- Snapshot-field templates also need a committed pilot payslip: REGISTER, EMPLOYER-COST, SUBSIDY, IMSS-BRANCH, INFONAVIT, JOURNAL, AGUINALDO, FINIQUITO, ANNUAL-ISR-ADJ.

**Already in the repo:**
- `docs/mexico/release-gates/G1–G8` (checklists and evidence *drafts*, "not a signature");
- `docs/mexico/sources/`: 33 files, almost all `ARCHIVE_COPY_VERIFIED`; only S22 SAF is `VERIFIED`;
- `MEXICO_PRODUCTION_ACTIVATION_RUNBOOK.md`, `DECISIONS_PENDING.md`;
- `tests/fixtures/mx_golden/`: README only, 0 vectors;
- the template "new version" tool and the Versions & gates tab.

**Remaining work:**
- **(a) Engineering:**
  - golden vectors once the inputs exist (gap register B21);
  - integration pieces behind G1/G2/G6: PAC adapter, IDSE/SUA/SIPARE layouts (runbook §0).
- **(b) Human evidence:**
  - direct downloads of ~31 sources (`scripts/verify_mexico_sources.py verify`), plus the S22 version fix;
  - signed golden cases reconciled to SAT/PAC, SUA and INFONAVIT;
  - G1–G8 evidence packs (G3, G6 and G8 need a pilot);
  - committed pilot payslips per run type.
- **(c) Sign-offs:**
  - each gate: Preparer + Reviewer (different Super Admins) + Employer payroll owner (G5, G8);
  - D-01…D-29 (mostly Open; D-01 blocks pack activation);
  - pack activation (G1 review by a non-activator);
  - ZP-PRIV (Rugvedh) per runbook §3.4.
- **(d) Steps:**
  1. Compliance → Mexico → **Sources**: `MX-GATE-Gn`, Upload, a second admin clicks Mark reviewed.
  2. Check **Readiness G1–G8** and each pack's activation checks.
  3. Pack Draft → In Review → QA → Approved → Active.
  4. Template: Versions & gates → new version if needed → Approve (B) → Publish → Active (C ≠ B).

**Earliest possible:** even a G7-only template (IDENTIFIER-ACCESS-AUDIT) needs `MX-PAYROLL-2026` Active.

---

## 9. Brazil (3): largest

**Gate** (`brazil_service.py:98-99`): unconditional. "Brazil report-template activation is refused: Brazil report templates are not built yet (ZP-BR-ENG-001 Phase 0 scaffolding)." `gate_states()` hard-codes every G1–G8 to OPEN (`:61-62`), and **there is no mechanism to record gate evidence**.

**Templates:** **not found in the repository.** There is no Brazil seed, report type or test. The three Published rows were probably created through the UI; list them with the dry run.

**Already in the repo:**
- `docs/brazil/sources/` (16 files + manifest, including the eSocial S-1.3 layouts and Anexo I tables);
- `docs/brazil/working/TABELA_04_FPAS_TRANSCRIPTION_DRAFT.csv`;
- `tests/fixtures/br_golden/` (F1, F2, F6, PROVISIONAL);
- the implementation plan and Phase 0–6 reports.

**Remaining work:**
- **(a) Engineering:** Phases 7–11 of `BRAZIL_IMPLEMENTATION_PLAN.md` are not started:
  - 13th salary, vacation and termination / TRCT;
  - collective agreements;
  - **eSocial S-1.3 events and XML + XSD validation**;
  - DCTFWeb / FGTS Digital;
  - **PIX / CNAB 240, holerite and reports**.

  Then template definitions and a seeder, a real gate-evidence mechanism replacing the hard-coded OPEN, and an evidence-based hook (BR is already an R3 country).
- **(b) Human evidence:**
  - D6 official XSDs and code tables from the tax content team;
  - Tabela 03 verification (BR-K3);
  - sources S6, S7, S9–S20;
  - OFFICIAL golden vectors F1–F6;
  - eSocial acceptance receipts;
  - two parallel cycles (G8).
- **(c) Sign-offs:** G1–G8 and decisions D2–D6, from the "tax content team" (`BRAZIL_PHASE_0_GAP_ASSESSMENT.md:77`). No names.
- **(d) Steps:**
  - **Sources:** `SourceEvidencePanel`.
  - **Golden run:** `POST /api/super-admin/compliance/brazil/golden-check`.
  - **Gates:** read-only today (`GET …/brazil/gates`, `…/readiness`). There is no UI or API to record gate evidence.
  - **Recommendation:** Supersede the three UI-created Published rows once their owners confirm; they cannot be activated by any path.

---

## Cross-cutting

- **No named sign-off person exists in any of these countries' docs.** Every sign-off table is blank or names roles only.
- **Several Published rows have no seed.** Brazil's three, and possibly others, appear to have been created through the UI. Their provenance should be confirmed.
- **Three people per template.** Every activation needs at least three distinct Super Admin accounts: creator or editor, approver, activator. This applies where an editor may not approve and the approver may not activate.
- **How to verify after any step:** the read-only dry run (`python -m scripts.report_stuck_published_templates --all-published`) shows each template's current gate refusal, so it can confirm progress without changing anything.
