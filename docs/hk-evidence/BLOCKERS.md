# Hong Kong launch — blockers, triaged (updated 2026-10-13, third pass)

Each item is something Claude could not complete without inventing a result, credential, signature or statutory value, or something that is not Claude's to decide. The groups are: **(a) engineering**, which Claude can fix; **(b) decision for a named owner role**; **(c) external dependency** (credentials, specialist, real payroll cycles).

## (a) Engineering

| # | Item | Status |
|---|---|---|
| B-8 | G5 F-1: MPF member account unmasked in API responses | **FIXED.** Masked to the last 4 everywhere. Full number only via the `HK_MPF_ACCOUNT_REVEAL` permission (granted by another org admin, reason required) plus a stated purpose; every read and refusal is in the HK access log; the eMPF filing view carries the full number while the stored batch stays masked. 4 tests |
| B-10 | G5 F-3 / F-7: assisted access had no tenant approval and no tests; runbook #22 said "tenant consent" | **FIXED.** Tenant-admin consent by default. Break-glass needs a mandatory reason and a second Super Admin, cannot be self-approved, runs 60 min by default (configurable) and notifies the tenant immediately; every step and refusal is audited. Runbook #22 rewritten to match. `tests/test_assisted_access.py` (6 tests). Migration `8b14824fb575` |
| B-7 | MPF contribution day never moved off weekends / holidays | **FIXED in engineering:** governed rule `mpf_contribution_day_deferral` (pack row, [G1] UNVERIFIED, source S3) plus an operator override for signal days (reason required, audited, Super Admin UI). 4 dates move in 2026/27. The statutory confirmation moves to (c) as B-7c |
| B-20 | Migration discrepancy (main could not deploy onto production's `b08f04497195`) | **FIXED** (first pass). Single head is now `8b14824fb575`; rehearsed up, down and up on a copy of production's schema. Venu note: `ops/MIGRATION_ALIGNMENT_NOTE.md` |
| B-21 | G4 rows R2, R3, R4, R5, R9 were not end to end | **FIXED.** End-to-end tests added; all 10 rows are now end to end (47/47 passed) |
| B-25 | G5 F-8: evidence / HK documents could be written to the `/tmp` fallback in production | **FIXED (third pass).** In production mode (`ENVIRONMENT`/`APP_ENV`=production) with no Cloud Storage, evidence upload and HK document upload refuse before writing anything: a clear error (400 / 409) plus a `refused` audit row with cause NON_DURABLE_STORAGE. Dev / test and production-with-GCS are unchanged. 5 tests. No excluded file was edited |
| B-26 | Break-glass tenant notification could fail silently (queued email; "notified" recorded regardless) | **FIXED (third pass).** Sent synchronously with delivery confirmed. On failure, or when there is no active org admin: the session stays active and audited, an `ASSISTED_ACCESS_TENANT_NOTIFICATION_FAILED` event records why, `tenant_notified_at` stays empty, and Super Admin → Alerts shows a high-severity Security alert. Runbook #22 updated. 4 tests |
| B-27 | General-holiday calendar for the contribution-day deferral | **ENGINEERING DONE (third pass).** Governed `HK_GENERAL_HOLIDAY` pack rows; `scripts/hk_load_general_holidays.py` loads a year from an archived official file (SHA-256 recorded, [G1] UNVERIFIED, Draft packs only; a reseed keeps the rows). The deferral uses general holidays + weekends + recorded signal days. With an empty list it behaves as weekends only and flags "general-holiday list not loaded". **Data for 2026 / 2027 deliberately empty**: see (c) B-7c |
| B-28 | TODO: the eMPF file / API submission builder does not exist yet (G2) | Contract in place: `test_no_new_code_reads_the_mpf_member_account_outside_the_audited_paths` (a code tripwire) and `test_empf_filing_payload_contract_full_number_only_via_the_filing_view`. The future builder must take its rows from `hong_kong_service.empf_filing_view` (permission + purpose + access log) and never read the field or the masked stored batch. Owner: Engineering, when G2 credentials and the eMPF spec exist |
| B-11 | G5 F-5 / F-6: no login / auth audit table; configuration audit not immutable at the database level | **Not fixed. Design note ready:** `ops/DESIGN_F5_F6_login_audit_and_immutable_audit_rows.md` (recommended: an append-only `auth_audit_events` table; PostgreSQL triggers that reject UPDATE/DELETE on audit tables, with a retention-gated purge function). Platform-wide; its own change and migration; no `main.py` change needed |
| B-22 | G5 F-4: assisted-access request audit is best-effort (a failed audit write does not block the request) | **Not fixed. Design note ready:** `ops/DESIGN_F4_privileged_access_audit_fail_closed.md`. Recommended: a pre-execution intent record in `core/dependencies.py` (503 if it cannot be written), plus an alert on missing completion rows. This **avoids editing `main.py`**. Needs the Security lead's decision |

## (b) Decision for a named owner role

| # | Item | Owner role | Unblocks |
|---|---|---|---|
| B-13 | Owner decisions D-1 … D-14 (draft records in `decisions/`, sign-offs blank) | Product owner (advisers per record) | The DECISION_D-n readiness rows |
| B-12 | PDPO legal assessment; retention periods and deletion vs anonymisation (D-2, D-3); legal-hold policy (D-9) | Privacy counsel + product owner | G5; retention categories (0/8 approved) |
| B-9 | G5 F-2: HKID / passport / MPF account stored raw at rest (D-4) | Security lead | G5 |
| B-19 | Bilingual output (D-6) | Legal / Product | Launch scope |
| B-23 | Optional exception "G1 by internal review in lieu of a specialist" (`decisions/D-G1-…`) | Product owner (risk acceptance) | G1, if chosen |
| B-24 | G3 tolerance and "material variance" definition | Payroll Operations | G3 tool thresholds |
| B-18 | Runbook #30 still names migration `cd62503afe26`; monitoring ownership (alerts not wired) | Payroll Operations (owner-controlled pack) | G6 |
| B-22 | Assisted-access audit: fail-closed or best-effort plus alert (see (a)) | Security lead | G5 F-4 |
| B-15 | Production `HK_IDENTITY_TOKEN_KEY` (`ops/HK_IDENTITY_TOKEN_KEY_provisioning.md`) | Ops / Security | D-5 readiness row |
| B-16 | Run the production read-only verification (`ops/…instructions.md`) | Ops | HK-PRODUCTION-VERIFICATION |
| B-17 | Upload the evidence in production (`UPLOAD_KIT/`), and re-run the canonical seed on the Draft packs so the new deferral row reaches production | Super Admin A (uploads) + Super Admin B (reviews); Ops (seed) | Gates move from EVIDENCE_REQUIRED to SUBMITTED |
| B-14 | G7 signatures | Six named roles | Launch |

## (c) External dependency

| # | Item | Needs |
|---|---|---|
| B-1 | G1 certification of the 29 flagged values (24 earning classifications, MPF partial-month basis, average-wage divisor, overtime test, EO week start, contribution-day deferral) | Hong Kong payroll / statutory specialist |
| B-7c | Contribution-day deferral rule (UNVERIFIED) and the 2026 / 2027 general-holiday lists (empty, SOURCE_REQUIRED in the G1 worksheet) | Specialist confirms the rule; a person archives the official general-holiday list for each year and loads it with `scripts/hk_load_general_holidays.py` |
| B-2 | `eo_week_start_day` has no hashed source (Cap. 57 s.2) | Archive the ordinance text; specialist confirms |
| B-3 | `source_document_sha256` column of the G1 worksheet is empty | Team downloads and archives the authority PDFs (`hk_archive_authority_documents.py`) |
| B-4 / B-5 | IRD XML schemas, sample files, software-approval route; eMPF interface spec and credentials; all G2 tests | IRD / eMPF credentials and documents |
| B-6 | G3 results | Two real parallel payroll cycles against the incumbent payroll |
