# G5 — Security / privacy assessment (DRAFT for review)

**Status:** DRAFT — Zoiko internal, internally reviewed – pending approval. This is not a PDPO legal opinion and not a penetration test.
**Gate:** HK-GATE-G5 — "PDPO/HR privacy review, privileged-access test, retention/deletion policy, encryption and audit controls pass" (wireframe v1.0 §16; PCPD source S10).
**Related owner-controlled documents (read, not modified):** `docs/HONG_KONG_RELEASE_EVIDENCE/G5/G5_PRIVACY_EVIDENCE_PACKAGE.md` (596246b8…), `G5/ENCRYPTION_AT_REST_ASSESSMENT.md` (4cb47e18…), `G5/PEN_TEST_SCOPE.md` (c3be81d8…), `HK_PDPO_TECHNICAL_READINESS_MATRIX.md` (b5241ca1…).

Every statement below is cited to the code (paths under `backend/app/`) as of 2026-10-13. Where something is absent, it says so.

## 1. Privileged-access and control tests (actually run)

| Item | Value |
|---|---|
| Output | `G5_privileged_access_test_run_output.txt`, SHA-256 `9d490ef04f42d43d7e0d31328d3f77e62b35bcdfde9683d6e024d13d4d1ee388` |
| Started (UTC) | 2026-10-13T08:55:12Z, throwaway SQLite database |
| Result | **41 passed, 0 failed** (the 30 of the second run, plus 2 eMPF-guard tests, 4 break-glass notification tests and 5 durable-storage tests) |

What these tests prove:
* The HK route inventory is pinned at 66 routes.
* Every HK route refuses an unauthenticated caller and a non-operator role over HTTP, and every route admits the right role.
* The HK identity token is keyed, versioned and never the raw value. Legacy tokens are re-derived only on write.
* Legal holds block deletion, need a different user to release, are tenant- and jurisdiction-scoped, and can be organisation-wide.
* Retained HK statutory records block a hard delete.
* The access log records HK report, profile and certificate access per tenant, including during an assisted-access session.
* Evidence review is maker-checker, and a rejection is retained.
* The registry route refuses non-Super-Admins and unidentified actors.
* The eMPF configuration holds no secrets and activates four-eyes.
* Retention stays blocked until the owner decides, then needs four-eyes.

Added in this pass (all in the run above):
* **MPF account (F-1):** masked by default in the employee and payslip APIs; a reveal needs `HK_MPF_ACCOUNT_REVEAL` plus a stated purpose; every read and every refusal is in the HK access log; the eMPF filing view carries the full number while the stored batch stays masked.
* **Assisted access (F-3 / F-7), `tests/test_assisted_access.py`:**
  * Consent is required before any token exists. Approval by anyone other than an org admin of that organisation is refused and audited; that covers a Super Admin, another tenant's admin, a payroll admin and the support session itself.
  * Only the requester can activate.
  * A request lapses after the approval window, and the sweep expires approved-but-unactivated requests.
  * A pending or rejected session's token is refused.
  * Break-glass needs a mandatory reason and a second Super Admin; the requester and the tenant cannot approve it. It is capped at 60 minutes, and the tenant's admins are notified immediately (audited).
  * Legacy sessions keep working.
  * Org admins are refused on the Super Admin endpoints over HTTP.

## 2. Personal data inventory (HK)

| Data | How stored | Where masked | Citation |
|---|---|---|---|
| HKID, passport number | **Raw**, in the `PayrollEmployee.compliance_fields` JSON column (no column encryption) | API responses (first character + last 4 kept); eMPF rows; IR56 reports (raw HKID never written into a GeneratedReport); payslips; field exports | `modules/payroll/models.py:585`; `employee_validation.py:1110, 1336-1377`; `hong_kong_service.py:1395, 3902-3934` |
| HK identity token | HMAC-SHA256, versioned `v2:`, keyed by `HK_IDENTITY_TOKEN_KEY` (falls back to a key derived from `PAYROLL_SECRET_KEY` when unset) | Kept out of payroll traces | `hong_kong_service.py:150-174`; `config.py:33-36` |
| MPF member account number | **Raw**, in `compliance_fields` | **Last 4 only everywhere:** API responses (`SENSITIVE_FIELDS`), payslips and eMPF rows (`mask_account_last4`). The full value only through the audited `HK_MPF_ACCOUNT_REVEAL` reveal or eMPF filing view | `employee_validation.py` (`mask_account_last4`, `SENSITIVE_FIELDS`); `hong_kong_service.reveal_mpf_member_account`, `empf_filing_view` |
| Personal-data access events | Append-only design: `PersonalDataAccessEvent` with action, client IP, user agent and assisted-session id | — | `models.py:7394-7419`; `retention_service.py:42-43, 84-99` |

## 3. Findings for the reviewer

| # | Finding | Severity (proposed) | Proposed action (not taken) |
|---|---|---|---|
| F-1 | MPF member account numbers were returned unmasked by employee and payslip API responses | Medium | **CLOSED 2026-10-13:** masked to the last 4 by default. The full number goes only to a user holding `HK_MPF_ACCOUNT_REVEAL` (granted by another org admin, reason required, audited), with a stated purpose; every read and refusal is logged |
| F-2 | HKID, passport and MPF account are stored raw at rest; there is no application-level encryption | Depends on D-4 | Owner decision D-4: verify provider encryption (GCS / managed PostgreSQL), or choose app-level encryption (platform-wide) |
| F-3 | A Super Admin started assisted access alone, with no tenant approval | Medium | **CLOSED 2026-10-13:** tenant org-admin consent by default (the org admin sees the reason); emergency break-glass needs a second Super Admin, is capped at 60 min and notifies the tenant immediately. Runbook #22 updated to match. D-10 still sets who may request and the session lengths (settings) |
| F-4 | Assisted-access request audit is best-effort (failures are swallowed) | Low–Medium | Design note: `../ops/DESIGN_F4_privileged_access_audit_fail_closed.md` (pre-execution intent record, no `main.py` change). Security lead to decide |
| F-5 | No login / auth-event audit table (login writes only a log line) | Medium | Design note: `../ops/DESIGN_F5_F6_login_audit_and_immutable_audit_rows.md`. Platform-wide |
| F-6 | `TaxConfigurationAudit` has no database-level immutability (no trigger or ORM guard) | Low | Design note: same as F-5 (PostgreSQL triggers and a retention-gated purge) |
| F-7 | No assisted-access test coverage | Medium | **CLOSED 2026-10-13:** `tests/test_assisted_access.py`, 6 tests, PASSED |
| F-8 | Local storage fallback writes uploads to `/tmp/uploads` when GCS is not configured | Low (ops) | **CLOSED 2026-10-13 (third pass):** in production mode without Cloud Storage, evidence and HK document uploads are refused before any write, with a clear error and a `refused` audit row (cause NON_DURABLE_STORAGE). Tests cover the refusal and dev / test / production-with-GCS behaviour |
| F-9 | Break-glass tenant notification could fail silently ("notified" recorded even when no email was sent) | Medium | **CLOSED 2026-10-13 (third pass):** synchronous send with delivery confirmed; on failure the session stays audited, a TENANT_NOTIFICATION_FAILED event is written, and a high-severity Security alert appears in Super Admin Alerts. Runbook #22 updated |
| F-10 | Local test runs could deliver real email: a local backend reads `backend/.env` (real SMTP credentials) and nothing stopped a test / local backend from sending. One break-glass notice to `hkadmin@zoikotest.dev` confirmed (2026-10-13 11:59 UTC); earlier runs unknown | Medium (incident) | **ENGINEERING FIXED 2026-10-14; INCIDENT OPEN.** Outbound guard (`app/core/outbound.py`): test and local modes never deliver unless the local sandbox is explicitly enabled, and then only to it; run-wide SMTP tripwire in the test suite; test addresses moved to reserved domains. Human checks and the notification decision: `../ops/INCIDENT_F10_test_emails.md` §6 |
| F-11 | The assisted-access request audit stores the query string after a redaction pattern that only matches `token=` / `code=` when preceded by `?` or `&`. `request.url.query` has no leading `?`, so a **first** `token=` parameter is stored unredacted in `assisted_access_audit_events.payload` (found 2026-10-14 by the F-4 tests) | Low–Medium | **OPEN.** The fix (anchor the pattern at the start of the string) is in `../ops/patches/f4_audit_fail_closed.patch`, which is not applied. To check existing rows: `SELECT count(*) FROM assisted_access_audit_events WHERE payload->>'query' ~* '^(token\|code)='` (read-only) |

## 4. Encryption and transport (from code)

* Database TLS: `sslmode = PAYROLL_DB_SSL_MODE`, default `require`, overridable (`database.py:71`, `config.py:25-29`).
* Files: Google Cloud Storage via `blob.upload_from_string`, with no KMS / CMEK setting in code (`core/object_storage.py`). GCS encrypts at rest by default on Google's side; this must be verified for the production bucket (D-4).
* Passwords: bcrypt via passlib (`core/security.py:32`). JWT: HS256 with `PAYROLL_SECRET_KEY`; access 60 min, refresh 7 days, revocation by jti. The code default secret is a placeholder, which `scripts/validate_environment.py` flags.
* HK identity token key: see `../ops/HK_IDENTITY_TOKEN_KEY_provisioning.md` (D-5).

## 5. Access control (from code)

* `/api/payroll/hong-kong/*`: `get_current_payroll_operator`, which allows org_admin, payroll_admin, super_admin and assisted_access. Writes also need `require_writeable_workspace()` (`modules/payroll/router.py:4297-4298`; `core/dependencies.py:253-263`).
* `/api/super-admin/compliance/hong-kong/*`: `get_current_super_admin` (role super_admin, no organisation) (`core/dependencies.py:233-239`).
* Assisted access (`assisted_access/*`):
  * **Request:** a reason is always required. CONSENT approval comes from an org admin of that organisation. BREAK_GLASS approval comes from a different Super Admin, and the tenant is notified at once.
  * **Activation:** only the requester activates. A session is 30 min (consent) or 60 min (break-glass) and is never extended. The approval window is 60 min.
  * **Enforcement:** the hourly sweep expires sessions and lapsed requests. Each request re-checks approval, expiry, organisation and Super Admin status.
  * **Audit:** every lifecycle step and every refusal is audited, and every API call under the token is logged.

## 6. Retention, deletion and legal hold

The draft policy for the owner and counsel is in `G5_retention_deletion_policy_draft.md`.

## 7. PDPO data-protection principles: where the product stands

| DPP | Product position | Open item |
|---|---|---|
| DPP1 Collection (purpose, PICS) | Only statutory identifiers needed for MPF / IRD are collected. PICS issuance is part of employer setup (runbook #1) | Counsel to confirm the PICS template; the product does not generate a PICS |
| DPP2 Accuracy and retention | Identifiers validated (HKID check digit); retention periods owner-set and not yet decided | D-2 / D-3 |
| DPP3 Use | Identifiers are used only for statutory outputs, which are masked | — |
| DPP4 Security | Role gates, masking, access log, four-eyes on sensitive actions | F-1 to F-10 |
| DPP5 Openness | Not a product function | Customer policy |
| DPP6 Access and correction | Runbook #26 (privacy request) | Counsel review |

## Sign-off (leave blank until signed by the named person)

Security lead — Name / Role / Date / Signature: ________
Privacy counsel / DPO — Name / Role / Date / Signature: ________
