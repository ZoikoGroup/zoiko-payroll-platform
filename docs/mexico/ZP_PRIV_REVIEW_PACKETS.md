# ZP-PRIV review packets — Mexico (gap C16)

**For:** Rugvedh (ZP-PRIV).
**Written:** 2026-10-28, final mile X7.

One packet per item. Each lists:
- what changed;
- what data it touches;
- what is masked;
- the threats;
- the tests that prove the controls;
- an approval line.

**Branch protection does not enforce this review (C17):** items 1–7 are already on `main` and in production, so these are post-merge reviews. Items 8–13 are committed on `nikhil` and **not pushed**. Do not merge them until reviewed.

| # | Item | Commit | Where | Why ZP-PRIV |
|---|---|---|---|---|
| 1 | **W4-3b printed CFDI receipt** | `3a44dc1` | main, prod | **Renders raw RFC / CURP / NSS** (the one exception to MX-061) |
| 2 | Sources gate (Phase 11d) | `52af6eb` | main, prod | The only path to VERIFIED, which gates activation |
| 3 | W4-2 dedicated report generators | `df94606` | main, prod | New org route reading worker tables |
| 4 | W5-1 content views | `512b8ce` | main, prod | Two Super Admin routes |
| 5 | W5-2 generic editor refused for Mexico | `5485762` | main, prod | Changes shared write paths |
| 6 | W5-3 readiness per gate | `89a444a` | main, prod | One Super Admin route |
| 7 | A18 migration `c7d2e9a4f1b6` | `cc105e3` | main, prod | Migration (constraint) |
| 8 | X1 decision register + migration `d3f8b2a6c1e9` | `8ffe7f4` | nikhil (local) | Migration, 8 routes, four-eyes |
| 9 | X2 calculation sandbox | `06e9480` | nikhil (local) | One Super Admin route |
| 10 | X3 report catalogue + render audit | `bafb287` | nikhil (local) | Org report route reads more tables; receipt renders audited; 3 Super Admin routes |
| 11 | X4 parallel payroll (+ 2 tables in `d3f8b2a6c1e9`) | `db9eeb7` | nikhil (local) | New TENANT and WORKER tables with RLS, 6 org routes, imported payroll data |
| 12 | X5 kits + CSD expiry route | `80fbf09` | nikhil (local) | Cross-organisation Super Admin read of credential metadata; custody interface |
| 13 | X6 incapacity proposal | `e47d433` | nikhil (local) | Documents only: health data (also legal) |
| N | **Separate note:** `payslip_items.compliance_fields` | — | platform-wide | Plaintext identifier copy at rest |

Also still pending from earlier phases (reviewed after merge, outside this list): **10c** redaction, **10f** transfer, **10g** (PR #125), **11a** (PR #127), **11b** (PR #128). Each was merged without a review on its PR.

---

## 1. W4-3b — printed CFDI receipt (`3a44dc1`) — FIRST

- **What changed:**
  - `mexico_cfdi_receipt.py` (new): builds the receipt data and a PDF in memory.
  - `mexico_cfdi_service._store_stamped_xml`: the PAC's stamped XML is now kept in object storage beside the signed XML.
  - `mexico_pac.StampResult.stamped_xml` (new field).
  - Route `GET /api/payroll/mexico/cfdi/documents/{document_id}/receipt`: `worker` / read, **org_admin only**, tenant-scoped, reads `payroll_mx_cfdi_documents`.
- **Data touched:** the stored stamped XML. That XML contains the issuer's and the **receiver's RFC, CURP and NSS** (SAT requires them on the receipt: CFF Art. 29-A, RMF 2.7.1.7 / 2.7.5.2).
- **What is masked:** nothing on the PDF; that is the deliberate exception. Everywhere else stays masked.
  - The PDF is rendered **on demand, never stored**, and sent with `Cache-Control: no-store`.
  - It is refused unless the document belongs to the caller's organisation (`doc.organization_id != org_id` → 404) and is STAMPED / CANCEL_REQUESTED / CANCELLED / REPLACED.
  - It is refused while the organisation is dormant or a pilot (`mexico_filing_service.guard`).
  - Since X3, **each render is recorded** as a `RECEIPT_RENDERED` CFDI event (who, when; no identifier), listed by report MX-IDENTIFIER-ACCESS-AUDIT.
- **Threats:**
  1. An org admin downloads many receipts, which means bulk identifier export. There is no rate limit, but renders are audited.
  2. A payroll operator role cannot render (org_admin only). Should the worker see their own receipt? Not built.
  3. Browser or proxy caching (mitigated by `no-store`).
  4. A PDF forwarded by email is outside Zoiko.
  5. The XML at rest in object storage holds identifiers. Its storage controls are gap C15 (`CFDI_XML_STORAGE_CONTRACT.md`).
- **Tests:**
  - `test_mexico_cfdi_receipt.py` (5): reads only the stored stamped XML; QR per Anexo 20; PDF built in memory with the legend; only stamped documents; missing id → 404.
  - `test_mexico_report_x3.py`: renders audited, no identifier in the audit report, and another tenant's render records nothing.
  - `test_mexico_dormancy.py`: the route is refused while dormant.
- **Gap in the tests (to fix whichever way you decide):** no test asks for **another organisation's real document id**. Only a non-existent id is tested. The code checks the organisation, but the control is not proven by a test.
- **Decisions for you:** keep org_admin only? Add a rate limit? Should the worker see their own receipt?

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 2. Sources gate — Phase 11d (`52af6eb`)

- **What changed:**
  - `mexico_sources.py` (new): reads `docs/mexico/sources/SOURCES_MANIFEST.csv`.
  - A source counts as VERIFIED **only** with a matching MATCH entry (same code, file, URL and SHA-256) in `VERIFICATION_LOG.csv`, written only by `scripts/verify_mexico_sources.py verify` after a fresh direct download.
  - `ARCHIVE_COPY_VERIFIED` can back **Draft** content only.
  - Activation and G1 read this gate (`mexico_service`).
- **Data touched:** none personal. Repository files and statutory content.
- **Threats:**
  1. Someone edits the manifest or log by hand to fake VERIFIED. Mitigated: a row needs a matching log entry, and both are in git, so the change is reviewed in the PR.
  2. A second path to VERIFIED. The rule is "there must be none"; please confirm.
  3. If the manifest can't be read, nothing is verified (fail-closed).
- **Tests:** `test_mexico_seed.py`, `test_mexico_activation_gates.py`, `test_mexico_content.py` (archive copy refused at activation; hand-marked VERIFIED without a log entry not usable).

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 3. W4-2 — dedicated report generators (`df94606`)

- **What changed:** `mexico_report_service.py` builds Mexico reports from service views. New route `POST /api/payroll/mexico/reports/{template_id}/generate`: `worker` / create, org_admin, tenant, dormancy-guarded.
- **Data touched:**
  - reads `payroll_employees`, payslip snapshots, the authority-liability, IMSS, ISN, CFDI-document, PTU and vacation tables;
  - writes `payroll_generated_reports`.
- **What is masked:** employees appear by **employee code**; no RFC, CURP or NSS in any report body. Reports are immutable, and regenerating supersedes.
- **Threats:** a stored report holding an identifier, or a cross-tenant run or cycle id.
- **Tests:**
  - `test_mexico_report_generators.py::test_no_report_carries_a_full_identifier`;
  - wrong template or missing parameters refused;
  - `test_mexico_dormancy.py`.

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 4. W5-1 — Super Admin content views (`512b8ce`)

- **What changed:** `GET /api/super-admin/compliance/mexico/statutory-rules` and `…/isn-content`, both `platform` / read / super_admin.
- **Data touched:** statutory content with its sources. No tenant data.
- **Threats:** none identified beyond the Super Admin boundary.
- **Tests:** `test_mexico_statutory_rules_view.py`.

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 5. W5-2 — no statutory edit outside the governed paths (`5485762`)

- **What changed:** `service.py`. The **shared** generic pack row editor and the hotfix path now **refuse a Mexico pack** (any status). Other countries are unchanged. The UI hides those buttons for Mexico (`JurisdictionLayout.jsx`).
- **Data touched:** none personal. Shared write paths change behaviour for one country.
- **Threats:** a regression for other countries (tested), or a remaining bypass.
- **Tests:** `test_mexico_generic_edit_refused.py`: every generic write is refused for a Mexico pack in each status, over HTTP too, and other countries keep the generic editor.

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 6. W5-3 — readiness per gate (`89a444a`)

- **What changed:** `GET /api/super-admin/compliance/mexico/readiness/gate-checklists`, `platform` / read / super_admin. It shows per gate what is confirmed in code versus awaiting evidence.
- **Data touched:** gate checklist files and evidence status. No tenant data.
- **Tests:** `test_mexico_gate_checklists.py`.

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 7. A18 — migration `c7d2e9a4f1b6` (`cc105e3`)

- **What changed:** widens CHECK `ck_mx_liability_authority` on `payroll_mx_authority_liabilities` to allow `IMSS_RCV` (retirement branches as their own bimonthly liability, LSS Transitorio XXVII). No table or column is created.
  - It is added NOT VALID, then VALIDATEd.
  - It runs under `lock_timeout = '5s'` and takes a brief ACCESS EXCLUSIVE lock on that Mexico table only.
  - **No RLS change** (the policy names no column).
  - Downgrade refuses while any IMSS_RCV row exists.
- **Production:** deployed green; production is at `c7d2e9a4f1b6`.
- **Tests:** `test_mexico_imss_rcv_migrations.py`, run on PostgreSQL 17:
  - links;
  - SQLite idempotent with rows kept;
  - only the liability table locked in flight;
  - a reader makes it fail fast;
  - the real CLI path plus schema drift.

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 8. X1 — decision register (`8ffe7f4`) — NOT MERGED

- **What changed:**
  - Table `payroll_mx_decisions`, a **platform** table: no `organization_id`, no worker column, so **no RLS policy**, like other platform tables. User ids are plain integers, with no foreign key to users.
  - Migration `d3f8b2a6c1e9` (single head; parent `c7d2e9a4f1b6`).
  - Eight routes under `/api/super-admin/compliance/mexico/decisions`, all `platform` / super_admin: list, get, by-block, propose, approve, revise, withdraw, transcribed.
  - Four-eyes: the approver must differ from the proposer.
  - An approved decision **changes no calculation**; it must be transcribed.
- **Data touched:** decision text, options and sources; actor ids. No tenant data.
- **Threats:**
  1. One Super Admin approving their own proposal (blocked).
  2. A "gate owner" role does not exist (D-23): the interim control is a second Super Admin.
  3. An approved answer silently changing pay (it cannot: transcription is separate).
- **Tests:**
  - `test_mexico_decisions.py` (9): idempotent seed from the documents; typed answers checked against the code that reads them; four-eyes, hash ticket and immutability; a revision supersedes only once approved; withdrawals reopen and refusals are audited; **a decision never changes a calculation by itself**; traceability from block codes; routes Super Admin only and four-eyes over HTTP;
  - `test_mexico_final_mile_migrations.py` on PostgreSQL 17.

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 9. X2 — calculation sandbox (`06e9480`) — NOT MERGED

- **What changed:** `POST /api/super-admin/compliance/mexico/sandbox/calculate`, `platform` / super_admin. Runs the real engine on **synthetic input** with what-if decision answers.
  - Every result is watermarked "SANDBOX — SYNTHETIC" and "CANDIDATE — NOT APPROVED".
  - The transaction is **always rolled back**; nothing is stored.
- **Data touched:** none personal (no employee is read; the input is typed).
- **Threats:** a sandbox result mistaken for a real one (watermarks), or a write leaking (rollback, tested).
- **Tests:** `test_mexico_sandbox.py` (11): `test_the_sandbox_writes_nothing`; candidates only for open pack-row decisions, and an approved decision cannot be one; watermarks and Super Admin only; the §21 fixtures F1–F4.

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 10. X3 — report catalogue + render audit (`bafb287`) — NOT MERGED

- **What changed:**
  - Eight new report types on the existing org report route. Its worker-table list grew: SBC history, variable accumulators, benefit accruals, payment items.
  - Receipt renders recorded (item 1).
  - Three Super Admin `platform` routes: `report-templates/coverage`, `compare`, `{id}/sandbox-preview`. The coverage check deliberately **does not read tenant payslips**, so the route stays `platform`.
- **What is masked:**
  - employees by code;
  - INFONAVIT credit numbers and CLABEs as their **last four digits**;
  - the payment worklist report states "NOT A BANK FILE".
- **Tests:** `test_mexico_report_x3.py`, including a scan of every rendered X3 report for full RFC / CURP / NSS / CLABE, render audit, other-tenant isolation and missing or foreign runs.

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 11. X4 — parallel payroll (`db9eeb7`) — NOT MERGED

- **What changed:**
  - Two tables join migration `d3f8b2a6c1e9`:
    - `payroll_mx_parallel_imports` (**TENANT**: `organization_id`);
    - `payroll_mx_parallel_differences` (**WORKER**: `employee_id`).
  - The migration enables and forces RLS with the `zoiko_rls` policy **on these two tables only**, using the predicate `d7f9b1c3e5a6.classify()` derives (tenant / worker-org). It is not an `apply_rls()` sweep.
  - Foreign keys take a brief SHARE ROW EXCLUSIVE lock on `organizations`, `payroll_runs` and `payroll_employees`.
  - Six org routes `/api/payroll/mexico/parallel/...`: five `worker`, one `tenant_config`, all tenant-scoped and dormancy-guarded. Reads: payroll operator. Writes: org admin. Accept: a **different** org admin.
- **Data touched:** a legacy payroll's per-employee amounts.
  - **The file is never stored**, only its column mapping, SHA-256 and counts.
  - Matching is by **employee code only**.
- **What is masked / refused:**
  - a column named like an identifier, or any cell shaped like an RFC, CURP, NSS (11 digits) or CLABE (18 digits), refuses the whole file;
  - the error names the **row**, never the value;
  - explanation texts are scanned the same way.
- **Threats:**
  1. A legacy export carrying identifiers (refused).
  2. Cross-tenant ids (404, tested).
  3. The pattern match refusing a legitimate 11- or 18-digit code (accepted: false refusals are safe).
- **Tests:**
  - `test_mexico_parallel.py` (9): identifier refusal without echo; four-eyes; tenant isolation; supersession; uncommitted run refused; report without identifiers.
  - `test_mexico_final_mile_migrations.py` on PostgreSQL 17 (6/6): RLS on the two tables only with the derived predicate; locks measured; fail-fast after 5.14 s.
  - `test_mexico_dormancy.py` (+6 routes).

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 12. X5 — kits and CSD expiry route (`80fbf09`) — NOT MERGED

- **What changed:**
  - `GET /api/super-admin/compliance/mexico/csd-expiry`, `platform` / super_admin. It reads `payroll_mx_credential_refs` **across all organisations** and returns, for CSDs that are expired, missing or expiring:
    - the organisation's name and the employer profile id;
    - the certificate serial and validity;
    - the **first 12 hex characters** of the fingerprint.
  - It **never returns the secret reference or the RFC**.
  - Also: the CSD custody interface (`mexico_csd_custody.py`: the private key cannot be returned by any call; not installed) and the XML store interface (`mexico_xml_store.py`: not installed).
- **Threats:**
  1. Cross-tenant metadata in a platform route. Is the organisation name plus serial acceptable for Super Admin?
  2. The fingerprint prefix.
- **Tests:**
  - `test_mexico_csd_custody.py` (10): production refuses; custody checked before signing; the interface offers no key method; alerts carry no secret reference; org admin refused.
  - `test_mexico_xml_store.py`, `test_mexico_pac_conformance.py`.

**Decision:** ☐ approve  ☐ change requested: ________________________________

## 13. X6 — incapacity proposal (`e47d433`) — documents only

`INCAPACITY_RECORD_PROPOSAL.md`: health data. It ends with ten questions for you and legal. Nothing is built.

It also contains a finding: uncertified "sick" leave is counted today as IMSS incapacity days. There is no production effect while Mexico is dormant.

**Decision:** ☐ approve the approach  ☐ change requested: ________________________________

---

## Separate note — `payslip_items.compliance_fields` (Phase 11b finding)

- **What:** when a payroll run is generated, every payslip stores a copy of the employee's `compliance_fields` (`models.py`: "Snapshot of PayrollEmployee.compliance_fields"). That copy is **plaintext**, for **every country**: RFC / CURP / NSS for Mexico, and national identifiers elsewhere. It is a second identifier copy at rest, beside the employee's own `compliance_fields`.
- **Found by:** the 11b identifier scan (`MEXICO_PHASE_11B_IMPLEMENTATION_REPORT.md` §6). The scan excludes exactly those two source columns and says why.
- **Not caused by Mexico, and not changed by it.** It falls under open decision **Q9 / HK D-4** (encryption or tokenisation of identifiers at rest).
- **Question for you:** keep the snapshot (immutability of what was paid), tokenise it, or drop identifiers from it? Whichever you choose is platform-wide, not Mexico's.
