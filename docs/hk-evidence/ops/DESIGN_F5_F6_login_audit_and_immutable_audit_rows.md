# Design note — F-5 login / authentication audit; F-6 immutable audit rows

**Status:** design only, not implemented. Platform-wide (every country), so out of scope for the HK launch branch. For the Security lead (BLOCKERS B-11, G5).

## F-5 — No login / authentication audit trail

### Problem

`app/modules/auth/service.py::login_user` raises `UnauthorizedException` on a bad password or an inactive account. On success it writes only a log line (`logger.info("User %s (%s) logged in", ...)`). No database record exists of:
* successful logins;
* failed logins;
* lock-outs;
* token refreshes;
* logouts / revocations, beyond the `revoked_tokens` rows;
* password resets, beyond `auth_email_events`, which records the email but not the authentication event.

Investigating suspected access to HK personal data (PDPO DPP4, runbook #27) therefore cannot answer "who signed in, from where, when".

### Options

| | Option | Pros | Cons |
|---|---|---|---|
| A | **New append-only `auth_audit_events` table (recommended)** — `occurred_at, event_type (LOGIN_SUCCESS / LOGIN_FAILED / ACCOUNT_INACTIVE / REFRESH / LOGOUT / PASSWORD_RESET / ROLE_CHANGED), user_id (nullable for an unknown email), email_hash, client_ip, user_agent, organization_id, reason` | Queryable; same shape as `payroll_personal_data_access_events`; no raw passwords; the email is hashed for unknown users so failed-login rows hold no PII | New migration; one insert per auth event |
| B | Structured logs shipped to Cloud Logging only | No schema change | Retention and query depend on log infrastructure; not inside the evidence pack; easy to lose |
| C | Reuse `TaxConfigurationAudit` | No new table | Wrong domain (configuration audit); harms its meaning |

### Recommended approach

Option A. Write in `login_user`, `refresh_user_token`, logout and password-reset flows, plus role and active-state changes in user administration. A failed login records `user_id` only when the email exists, and always records `email_hash`, never a plaintext unknown email. The write is in the same transaction as the response; if it fails on login, refuse the login (fail-closed, as in the F-4 design).

### Files affected

* `backend/app/modules/auth/service.py`: login, refresh, logout, reset.
* `backend/app/modules/auth/models.py`: the new model.
* `backend/app/modules/auth/router.py`: pass the request for IP / user agent.
* A new migration.
* Super Admin Security & Audit page: add the source "auth".
* **`backend/app/main.py`: no change needed.**

### Test plan

* Success, failure (bad password, unknown email, inactive) and refresh each write exactly one row of the right type.
* No password or token is ever stored.
* An unknown email is stored only as a hash.
* Rows appear in the merged Security & Audit feed.
* The failure path is covered: if the audit insert fails, the login is refused.

### Risks

Write load on login (small). PII minimisation for failed logins (handled by hashing). A brute-force attack generates rows, so it needs retention under D-2 (category ACCESS_LOGS).

## F-6 — Audit rows are not immutable at the database level

### Problem

`payroll_tax_configuration_audit` (`TaxConfigurationAudit`) and the other audit tables are append-only **by convention**: the code only inserts. But any database user with write rights (or a future bug) can UPDATE or DELETE rows without trace. The same applies to:
* `assisted_access_audit_events`;
* `payroll_personal_data_access_events`;
* the proposed `auth_audit_events`.

### Options

| | Option | Pros | Cons |
|---|---|---|---|
| A | **PostgreSQL trigger that rejects UPDATE / DELETE on the audit tables (recommended)**, plus a separate DB role for retention purges (D-2/D-3) that may delete only rows past retention, through a SECURITY DEFINER function | Enforced by the database, not by code discipline; covers bugs and ad-hoc SQL | Migration with triggers (PostgreSQL-specific; SQLite test DB needs equivalent triggers or a skip); purge path must be designed with retention |
| B | Revoke UPDATE/DELETE grants from the application role | Simple | Depends on the deployment's role setup; one shared app role today |
| C | Hash-chain each row (row hash includes the previous row's hash), verified by a job | Detects tampering even by a DBA | Detects but does not prevent; more complex |

### Recommended approach

Option A now, Option C later for tamper evidence against privileged DB users. Retention deletion goes only through the purge function, gated by an approved retention policy (`retention_service.purge_refusal`).

### Files affected

* A new migration (triggers + function) for each audit table.
* `backend/app/modules/payroll/retention_service.py` (purge path).
* Tests.
* **No application code path updates audit rows today, so no service change is expected.** Verify with a search for `.update(` / `delete(` on these models.

### Migration needs

Additive: `CREATE FUNCTION` and `CREATE TRIGGER ... BEFORE UPDATE OR DELETE ... FOR EACH ROW`. Locks are brief (SHARE ROW EXCLUSIVE on each audit table while creating the trigger). It needs the same production-schema rehearsal as `8b14824fb575`.

### Test plan

* On PostgreSQL (the scratch cluster), UPDATE and DELETE on each audit table raise; INSERT works.
* The purge function deletes only rows past an APPROVED retention period, and records its own audit row.
* SQLite test runs install equivalent triggers, so the unit suite enforces the same rule.

### Risks

* A legitimate correction can no longer be made in place. That is intended: corrections are new rows.
* The retention purge must exist before retention periods are approved.
* Triggers must be included in restore rehearsals.

Security lead decision — Name / Role / Date / Signature: ________
