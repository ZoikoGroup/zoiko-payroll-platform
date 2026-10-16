# Mexico (MX) — Phase 3 Implementation Report: Employer onboarding and registrations

Spec ZP-MX-ENG-001 v1.0 §11 (panels A–H) · plan `MEXICO_PHASE_3_PLAN.md` (§19 = approved answers and corrections, 2026-10-16) · branch `nikhil` over 651948a · **staged, not committed**.

## 1. Result

| Area | Result |
|---|---|
| Backend Phase 3 tests | **95 new tests** in 9 files, all pass (plus the updated migration/content tests) — §7 |
| Full backend suite (system Python 3.11, `pytest tests/`) | **6170 passed, 1 failed, 48 skipped, 2 xfailed** (23 min). The one failure is the known **OOS-4** (`test_hong_kong_configuration`, the same 10 HK paternity/termination findings from the stale untracked HK matrix CSV) |
| Browser acceptance (real Chrome, `vite build` + `vite preview`, scratch SQLite) | **30/30** — `phase3-evidence/RESULTS.md`, 16 screenshots, the key ones inspected |
| `npm run check:undefined` | 494 files, no undefined names |
| ESLint (whole `src`) | 184 errors — unchanged from the Phase 2 baseline; the new files add none |
| `vite build` | passes |
| Shared `service.py` | **untouched** |
| SG shared-helper snapshot | not re-recorded (no change needed) — see §8 |

Nothing is set Active by code, no statutory value was typed or inferred, and every check fails closed while its content is empty.

## 2. What was built

**Backend**
- `models.py` + migration **`6e4a1d9c3f27_mx_employer_m2`** (guarded, idempotent, single child of `5d2c8f1a7b3e`; single head; 198 revisions) — seven tables:
  `payroll_mx_employer_profiles`, `payroll_mx_imss_registrations`, `payroll_mx_establishments`, `payroll_mx_risk_premiums`, `payroll_mx_isn_registrations`, `payroll_mx_labor_policies`, `payroll_mx_credential_refs`.
  Partial unique indexes (postgres + sqlite predicates, as `ContributionRate`): `uq_mx_employer_org_rfc_open`, `uq_mx_imss_org_rp_open`, `uq_mx_estab_profile_name_active`, `uq_mx_riskprem_reg_period_active`, `uq_mx_isn_profile_state_open`, `uq_mx_laborpol_profile_open`, `uq_mx_cred_profile_kind_active`, `uq_mx_cred_registration_kind_active`.
- **`mexico_employer_service.py`** (new) — profile chains, establishments, registrations, premiums, ISN, labour policy + floor checks, credential references, certificate screening/parsing, readiness. Kept out of `mexico_service.py` (the jurisdiction-hook module) — **deviation** from plan §12, which named `mexico_service.py`.
- **`mexico_org_router.py`** (new) — `/api/payroll/mexico/...`, 20 routes, mounted in `router.py` with one `include_router` (NL pattern). Org always the caller's own; reads = payroll operator, writes = org admin.
- `mexico_router.py` — four **read-only** Super Admin routes (`/employers`, `/employers/{id}`, `/employer-readiness`, `/employer-readiness/summary`), identifiers masked.
- `mexico_service.list_organizations` — the Super Admin org picker now also lists orgs with a Mexico legal employer or MX company jurisdiction (before: only orgs with MX employees, which would hide an org that has onboarded but not hired). Mexico-only function.
- `mexico_schemas.py` — Phase 3 request schemas, `extra="forbid"`, no statutory/identity defaults.
- `config.py` — `MX_SECRET_REF_SCHEMES = "gcp-sm://"` (Q9), `MX_CREDENTIAL_EXPIRY_WARNING_DAYS = 30` (Q8).
- `mexico_content.py` — value-free additions only: keys `mx_risk_premium_min_pct` / `mx_risk_premium_max_pct` (national; expected LSS Art. 74, S10), `RiskPremiumPeriodRule` + `MX_RISK_PREMIUM_PERIOD = None`, addendum source **S29** (RACERF). The fallback registry picks the new keys up automatically (value `None`).

**Frontend**
- Org: **Payroll → Compliances → Mexico Compliance Centre → Employer & Registrations** (`MXComplianceCentreTab.jsx`, `MXReadinessPanel.jsx`); `CompliancePage.jsx` adds the tab and hides *Tax Configuration* for MX orgs only (Q6).
- Shared panels `components/jurisdiction/mexico/employer/` (`MXEmployerPanels.jsx` A–G + credentials, `MXEmployerReadiness.jsx` H, `employerShared.jsx`, `employerUtils.js`, `useMexicoOrgData.js`, `mxStateCodes.js`) — `readOnly` omits every write control.
- Super Admin: **Employer** tab (`MXEmployerProfileTab.jsx`, read-only, Q5) in `mexicoComplianceConfig.jsx`; *Readiness G1–G8* tab gains the per-gate employer summary.
- `payrollService.js` (MX org block incl. raw-body `.cer` upload), `superAdminService.js` (read-only employer calls).
- Readiness date: the user's **local date** is sent explicitly as `on`, shown in a date bar with a picker; the API still requires `on` (correction 3).

**Docs**: plan §19 (answers/corrections), addendum S29 + fetch checklist, this report, `phase3-evidence/` (RESULTS.md, 16 screenshots, harness), `OUT_OF_SCOPE_DEFECTS.md` OOS-6.

## 3. Decisions applied (plan §19)

| # | Applied as |
|---|---|
| Q1 | Floors read from the **Active** national pack (`_pack_content`) — a Draft pack does not count (tested). |
| Q2 | `taxpayer_type` MORAL (12) / FISICA (13); both formats + real YYMMDD date. |
| Q3 | Period rule = `MX_RISK_PREMIUM_PERIOD` content rule, `None` → approval refused ("awaiting transcription from S10 / S14 / S29"). March–February is documented as coming from spec **MX-026**; dates are never coded from the spec text. Range = new keys from S10 Art. 74 (confirm on saving S10). S29 RACERF added with a fetch checklist. |
| Q4 | Four-eyes, no exception: approver must be an org admin who did not record it; with one active org admin readiness says **"waiting for a second org admin"** (item unmapped — no §22 gate covers it). |
| Q5 | Super Admin Employer tab read-only; SA routes are GET only (tested). |
| Q6 | Tax Configuration hidden for MX orgs only; NL unchanged, HK keeps it (browser-checked). |
| Q7 | Daily limits not checked — every floor result says "not checked — Phase 5 (no content key)". |
| Q8 | `MX_CREDENTIAL_EXPIRY_WARNING_DAYS = 30`, a setting (tested at 30 and 45). |
| Q9 | Only `gcp-sm://projects/<project>/secrets/<name>[/versions/<n|latest>]`; vault/aws/azure refused (tested + browser). |
| C1 | Every readiness item carries `gates` + `gateBasis` = the **verbatim §22 definition** of each gate, or `gateMapping: "unmapped"` (§5). |
| C2 | `.cer`: ≤16 KB, DER or single-block PEM, screened **before** parsing (a DER key / PKCS#12 starts with an INTEGER, a certificate with a SEQUENCE); raw request body streamed in memory with a hard cap — no multipart `UploadFile` (it spools to a temp file); bytes zeroed after; nothing written to disk (test patches every temp-file / write-open path to fail). |
| C3 | Local date as `on` + picker (org and Super Admin). |
| C4 | Dependency table — §6. |

## 4. Secrets (MX-035) — and an infrastructure lead-time item

Only `kind`, the `gcp-sm://` reference, certificate serial / SHA-256 fingerprint / subject / validity and status + rotation link are stored. A value that looks like key material (PEM header, `PRIVATE KEY`, any whitespace, a ≥64-char base64 run) is refused **before** any other check and never echoed — in the response, the audit row or the log (tested). The full reference is returned once, in the write response; afterwards only `gcp-sm://…<last 4>`. Audit rows record `secretRefSet`, never the reference. The credential route validates its own body so FastAPI's default 422 cannot echo a pasted secret back (tested).

> **Infrastructure lead time (Q9).** Production is GCP: per `GCP_DEPLOYMENT.md`, application secrets live today in a VM `.env`, and Secret Manager is the *target*, not yet in place. Per-employer CSD and PAC credentials need **GCP Secret Manager live (with a service account allowed to access the per-employer secrets) before Phase 7**, because Phase 7 is the first phase that resolves a reference (stamping). Nothing in Phase 3 resolves one; the readiness stamp-test item says so.

## 5. Readiness → G1–G8 mapping (cites spec §22)

| Item (panel) | Gate(s) | §22 basis (abridged; the API returns it verbatim) |
|---|---|---|
| RFC format, catalog regime / postal code (A), withholding obligation (B) | G1 | "ISR / CFDI — … CFDI 4.0/Nómina 1.2 reconciled to SAT/PAC validation" |
| CSD certificate reference (B) | G1, G7 | G1 as above; G7 "Certificates/secrets … signed" |
| PAC reference (B) | G6, G7 | G6 "PAC … workflows have unknown/reject/recovery paths"; G7 |
| SAT stamp test (B) | G1, G6 | as above |
| IMSS registration in force, work-risk premium covering the date, SUA reconciliation (C) | G2 | "IMSS / SUA — … every launch IMSS branch … reconcile to current SUA" |
| IDSE / SUA credential references (C) | G6, G7 | G6 "IDSE/SUA/SIPARE"; G7 |
| INFONAVIT model, INFONAVIT reconciliation (D) | G3 | "INFONAVIT — … reconciliation flow proven" |
| State ISN per establishment state (E) | G4 | "each enabled work state has signed … content; unsupported states are hard-blocked" |
| Minimum-wage zone per establishment (E), labour policy floors (F/G) | G5 | "Labor — Minimum wage zones/professions, 2026 workweek/overtime, vacations, aguinaldo …" |
| Payroll bank reference, bank workflow (H) | G6 (+G7 for the reference) | "… and bank workflows …" |
| Parallel payroll (H) | G8 | "Parallel payroll — at least two consecutive payroll cycles …" |
| **Four-eyes premium approval** (C) | **unmapped** | no §22 gate covers tenant four-eyes |
| **Electronic time-record dependency** (F) | **unmapped** | not in any §22 definition |
| Establishments present | unmapped | structural |

Employer readiness never signs a gate. `liveEligible` = every item PASS **and** every gate SIGNED — unreachable in Phase 3 by construction (stamp test, SUA/INFONAVIT reconciliation, bank workflow, parallel payroll are BLOCKED; a test configures everything else and asserts it stays false).

## 6. Dependency table — what stays BLOCKED / UNRESOLVED until which source or phase

| Phase 3 item | State now | Unblocked by |
|---|---|---|
| Minimum-wage zone of an establishment | **UNRESOLVED** | S9 transcription (`MX_ZLFN_MUNICIPALITIES`) |
| Work-risk premium approval — period shape | refused ("awaiting … S10 / S14 / S29") | S10 / S14 / **S29** saved + `MX_RISK_PREMIUM_PERIOD` transcribed |
| Work-risk premium approval — legal range | refused | S10 (LSS Art. 74) transcribed into `mx_risk_premium_min/max_pct` **and** the national pack Activated |
| Work-risk premium coverage (readiness) | BLOCKED | the two rows above + a second org admin's approval |
| Premium for a brand-new registration (before its first determination) | BLOCKED (not guessed) | the applicable statutory rule transcribed (S10/S29) |
| Risk class / fraction validity | format only | IMSS classification catalogue (RACERF, S29) if wanted |
| Fiscal regime / postal code catalog checks | BLOCKED | **S30** (SAT CFDI 4.0 catalog workbook, catCFDI — `c_RegimenFiscal`, `c_CodigoPostal`; added to the addendum in the follow-up) saved and VERIFIED, then loaded into an **Active** CFDI catalog release — Phase 7. These catalogs are not in the Nómina 1.2 workbook (S28) |
| CSD subject ↔ RFC match | "not checked" | the SAT certificate attribute confirmed from a saved source (S4) |
| SAT stamp test | BLOCKED | Phase 7 (+ Secret Manager live, §4) |
| State ISN (CDMX) | PENDING_PACK | S22 CDMX content transcribed + `MX-ISN-CDMX-2026` Activated |
| ISN return frequency / due date | "awaiting state filing content" | CDMX filing rule transcribed (S22) |
| Any other state's ISN | refused (MX-045) | a new state pack + its source (plan decision log: open) |
| Labour-policy floors | BLOCKED_CONTENT | S26 (LFT) / S19–S20 cross-checks transcribed + national pack Activated |
| Daily-hours limits | not checked | Phase 5 |
| SUA / INFONAVIT reconciliation | BLOCKED | Phase 8 |
| Payroll bank workflow, parallel payroll | BLOCKED | Phase 10 |
| G1–G8 | OPEN | Phase 10 evidence sign-off |

## 7. Tests

New (all SYNTHETIC; app imports lazy): `test_mexico_employer_profile.py`, `test_mexico_imss_registrations.py`, `test_mexico_risk_premiums.py`, `test_mexico_isn_registrations.py`, `test_mexico_labor_policy.py`, `test_mexico_credential_refs.py`, `test_mexico_employer_readiness.py`, `test_mexico_org_router.py`, `test_mexico_employer_migrations.py`, helper `_mx_employer_helpers.py` (not collected).
Updated: `test_alembic_metadata.py` (head `6e4a1d9c3f27`, 198), `test_migration_idempotency.py` (`_GUARDED`), `test_mexico_migrations.py` (M2 chain + literal guards + model parity), `test_mexico_content.py` (S1–S29), `MIGRATIONS_MANIFEST.txt`.

Highlights: per-org RFC uniqueness and several RFCs per tenant; one open row per partial index (ORM and raw SQL); four-eyes incl. the single-admin message; leap-year period end (29 Feb 2028); a 48-hour policy PASSes on its start date and FAILs from a later synthetic 46-hour row (MX-048/050); a CCT never relaxes a floor; key material refused and not echoed in response/audit/log; DER/PEM certificates parsed, keys/PKCS#12/bundles rejected **without the parser being called**; upload never touches disk; tenant isolation (404) and role gates (403) over HTTP.

## 8. Proof other jurisdictions are unaffected

- Shared files: `config.py` (+2 settings), `router.py` (+1 import, +1 include), `models.py` (+7 classes, appended), `CompliancePage.jsx` (MX tab + `isNetherlands || isMexico`), `payrollService.js` / `superAdminService.js` (new exports only). **`service.py`, `CollectiveAgreement` and its service: no change.** `git diff` of those files contains only Mexico hunks.
- Full suite — §1. The SG shared-helper snapshot did not need re-recording.
- Browser: NL org tabs exactly Overview / Company Details / Contribution Rates / Documents / Netherlands Compliance Centre (screenshot 12); HK org keeps Tax Configuration and has no MX tab (13); Super Admin NL workspace loads (14).
- The only non-Mexico HTTP error in the browser run is a **pre-existing** app-shell probe: a `payroll_admin` user's sidebar calls `/api/organization-admin/assisted-access/status` and gets 403 on every page — not introduced here, recorded in RESULTS.md.

## 9. Credentials used by tests and the harness — throwaway

- Harness users are `@example.com` addresses (RFC 2606 reserved) — `sa-a@mx.example.com`, `admin@mxorg.example.com`, `operator@mxorg.example.com`, `admin@mxother.example.com`, `admin@nlorg.example.com`, `admin@hkorg.example.com` — with the throwaway password in `harness/setup_db.py`. They exist only in a scratch SQLite file; `setup_db.py` asserts the URL is `sqlite:///` inside the scratchpad and refuses anything else.
- The `.cer` used by the browser check is a self-signed **public** certificate generated at run time next to the scratch DB (never in the repo); its key lives only in memory. Test certificates are generated in memory per test; none is committed.
- Secret references in tests/harness are fake `gcp-sm://projects/zoiko-test-project/...` / `zoiko-browser-check` strings; the "private key" pasted in the browser check is a fake PEM text.
- Org admins in the browser org: exactly one (so four-eyes must wait), by design.

## 10. Deviations from the plan text (all minor)

1. Service code in `mexico_employer_service.py`, not `mexico_service.py` (keeps the hook module small).
2. ISN registration stores `OPEN`/`CLOSED`; `PENDING_PACK`/`ACTIVE` is computed from the pack on read (a stored copy would go stale on pack activation).
3. IMSS registration status `ACTIVE`/`CLOSED` (no DRAFT — a registration is an employer fact, not reviewed content).
4. Credential uniqueness = two partial indexes (employer-level / registration-level) instead of one expression index.
5. Floor check reports dates past the Active content horizon as `notYetCheckable` (re-checked when that content is activated) instead of blocking an open-ended policy forever.
6. Super Admin org picker widened (§2).
7. `pages/PolicyModule/MXPolicyPage.jsx` not built (plan §12: pay-structure defaults belong to Phase 6). The plan's check found that MX — like NL, SA, SG, CH and IT — currently falls back to India's Policy page from the shared Policy toggle; logged as **OOS-6**, shared code unchanged.

## 11. Staged files / suggested commit

See the staging summary given with this report.

## 12. Follow-up (after the Phase 3 commit)

**Sensitive-file check.** `git show --name-only HEAD` and the Phase 3 commit `45d822a` contain no `.cer/.der/.pem/.p12/.pfx/.key/.db/.sqlite` file, and neither does the tracked tree. (Phase 3 was already pushed and merged to `main` by PR #101.)

**`.cer` upload cap — streams and refuses early (confirmed, no code change needed).** The route refuses on a declared `Content-Length` above 16 KB before reading any body, and otherwise reads the request stream chunk by chunk with a running byte count, refusing at the first chunk that crosses 16 KB. Measured by driving the full ASGI app (all middleware) with a paced 10 MB body (160 × 64 KB chunks) — `TestClient` cannot show this because it buffers the body before calling the app:

| Body | Chunks read by the route before refusing | Chunks pulled in total |
|---|---|---|
| 10 MB with `Content-Length` | 0 | 1 |
| 10 MB streamed, no length | 1 | 2 |
| exactly 16 KB + 1 byte, 1 KB chunks | stops at byte 16 385 | — |

The one extra chunk is Starlette's `BaseHTTPMiddleware` (the app's existing `assisted_access_audit_middleware`) listening for a client disconnect while the 400 is written: it reads and **discards** whatever arrives in that moment and stops with the response — nothing is accumulated. Tests: `test_a_10_mb_body_is_refused_without_reading_it_all[True/False]`, `test_a_body_of_exactly_16_kb_plus_one_byte_is_refused_while_streaming`.

**nginx (`deploy/nginx/zoiko-payroll.conf`, `location /api/`)** — `client_max_body_size 20m`, request buffering on (nginx default). Two consequences for the certificate route, outside the app:
1. nginx accepts up to 20 MB before the app's 16 KB cap applies (the app still refuses; nginx just carries more than needed).
2. nginx buffers request bodies and writes any body larger than `client_body_buffer_size` (default 8 KB/16 KB by platform) to a **temporary file on disk** before proxying — so in production a `.cer` can touch disk at the nginx layer, which correction 2 rules out.

Recommended (infrastructure change, **not made** — production config is yours to change):
```nginx
# A regex location wins over the `location /api/` prefix block (nginx matching order); it cannot carry a URI in proxy_pass.
location ~ ^/api/payroll/mexico/credentials/[0-9]+/certificate$ {
    proxy_pass              http://127.0.0.1:8000;
    proxy_set_header        Host              $host;
    proxy_set_header        X-Real-IP         $remote_addr;
    proxy_set_header        X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header        X-Forwarded-Proto $scheme;
    client_max_body_size    16k;     # refuse at the edge (413), matching the app cap
    client_body_buffer_size 16k;     # a body that fits stays in memory, never in a temp file
}
```
(`client_body_buffer_size ≥ client_max_body_size` means an accepted body always fits the in-memory buffer; an oversized one is refused with 413 before it is buffered.) Until this is in place, the "never written to disk" guarantee holds for the application, not for nginx.
