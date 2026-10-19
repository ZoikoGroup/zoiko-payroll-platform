# Incident playbook: suspected staff or partner access to tenant PII (control F04)

Status: awaiting Security lead proof (HP-08): the tabletop must be run and recorded in
`tabletop_record_template.md`. This playbook has not been exercised yet.
Companion files: `tabletop_script.md`, `tabletop_record_template.md`.

Scope: any suspicion that a Zoiko employee, contractor, support operator, machine client or partner
(sub-processor, integrator) accessed, exported or attempted to access a tenant's worker personal data
without a valid instruction or grant.

## 0. Roles

| Role | Responsibility | Who (fill in) |
|---|---|---|
| Incident commander (IC) | Owns the incident, decisions, timeline | Security lead |
| Evidence lead | Preservation, chain of custody | platform_security officer (not a subject) |
| Engineering lead | Containment actions in the product and infra | Platform Engineering on-call |
| DPO / counsel | Breach assessment, notifications | Privacy counsel / DPO |
| Communications | Customer and internal messages | Customer Success lead |

A person who is a subject of the suspicion never holds any of these roles and is excluded from the incident channel.

## 1. Detection sources

| Source | Where | Notes |
|---|---|---|
| Alert `cross_tenant_access` | `alert_events` / Super Admin Alerts page / `SECURITY_ALERT_EMAILS` | Threshold 1 (DEC-8) |
| Alert `employee_enumeration` | same | 25 distinct employee ids / 10 min |
| Alert `large_export` | same | 1,000 rows or 10 MB |
| Alert `unscheduled_elevation` | same | Grants outside 07:00-20:00 UTC and every break-glass |
| Alert `mfa_failures` | same | 5 / 15 min per user |
| Alert `overdue_break_glass_review` | same | Review not closed within 24 h |
| Alert `failed_audit_write` | same | Audit could not be written: treat as possible tampering |
| Alert `machine_client_new_network` | same | Client used from a new network |
| Security events | `GET /api/super-admin/security-events` (metadata only) | PDP denials, `PRIVILEGED_READ`, `EXPORT_STARTED`, `JOB_DENIED`, grant events |
| Support-access audit | Tenant tab `GET /api/organization-admin/support-access/audit`; platform `.../support-access/live` | Named attribution (C07) |
| Tenant report | Support ticket, email to the DPO | Customer is the controller |
| Infra signals | Cloud audit logs, PAM session recordings (HP-01), DB logs | Outside the app |
| Hash chain break | `GET /api/super-admin/security-events/verify` returns `ok: false` | Treat as tampering until disproven (see note on N6 in `indirect_paths_audit.md`) |

Alerts carry ids and counts only. Never paste worker data into tickets, chat or email.

## 2. Triage (target: 1 hour from detection)

1. IC opens an incident record (id `INC-YYYY-NNN`) with detection time in UTC (`Z`).
2. Classify:
   - **S1**: confirmed or likely access to identifiable worker data by an unauthorized person.
   - **S2**: attempts denied by the PDP (no data returned) with a pattern (enumeration, cross-tenant).
   - **S3**: single denied attempt, misconfiguration, false positive.
3. Identify principal(s): user id, role, grant id, machine client key, correlation ids.
4. Check whether any response actually returned data: `result=allow` rows in security events for the
   principal, `PRIVILEGED_READ` / `EXPORT_STARTED` events, support-audit `API_CALL` rows.
5. Decide containment (section 4) before deep analysis if S1.

## 3. Evidence preservation (before containment changes anything, where safe)

| Step | Action |
|---|---|
| Hash chain | Call `GET /api/super-admin/security-events/verify`; save the JSON response with UTC time and caller |
| Anchors | List `security_event_anchors`; compare the latest head with the external anchor object in the retention-locked bucket (HP-04) |
| Support audit chain | Tenant audit tab verifies its chain; export the grant rows (ids, timestamps, events) |
| Exports | Export metadata of security events for the window (Audit Explorer) - ids only |
| Do not purge | Confirm `AUDIT_PURGE_ON_ORG_HARD_DELETE=false`; freeze any organization hard-delete; nobody sets `zoiko.audit_purge` |
| Legal hold | Ask the tenant's org_admin to place a platform-wide legal hold if worker records may be needed as evidence (tenant-placed, four-eyes release) |
| Infra | Preserve cloud audit logs, PAM recordings, VM auth logs, nginx logs for the window; snapshot affected hosts if a staff machine or the VM is involved |
| Custody | Record every artefact with SHA-256, location, who collected it, UTC time |

## 4. Containment

| Target | Action | How |
|---|---|---|
| Support grant | Revoke now | `POST /api/super-admin/support-access/{grant_id}/revoke` (platform_security, reason) or tenant `POST /api/organization-admin/support-access/{grant_id}/revoke` |
| Staff account | Deactivate and end sessions | Deactivate the user (`deactivate_user` route), then run the JML reconciliation `backend/scripts/jml_reconcile.py` against the HR/IdP feed (script referenced by HP-05; not present in the repo at time of writing) |
| Machine client | Revoke, then rotate | `POST /api/organization-admin/api-clients/{client_id}/revoke` (tenant) ; issue a new client via `/rotate` only after root cause |
| Webhook endpoint | Disable | `POST /api/organization-admin/webhooks/{webhook_id}/disable` |
| Partner / sub-processor | Suspend the integration credentials; invoke DPA audit rights | Counsel |
| Infra access | Revoke PAM / IAM bindings, rotate DB credentials, rotate `PAYROLL_SECRET_KEY` only with a planned re-login | `deploy/security/pam_runbook.md` |
| Assist | Kill switch if model egress is suspected | Super Admin Assist kill switch |
| Committed secret | Rotate at the provider (example: Stripe webhook secret, HP-11) | Platform owner |

## 5. Breach assessment (DPO / counsel)

Engineering provides facts; counsel decides.

| Question | Input from engineering |
|---|---|
| Was personal data accessed, disclosed, altered or lost? | Allowed events, rows / fields returned (field classes), exports |
| Which tenants and how many workers? | Counts only, from tenant-scoped queries run by the tenant or under a break-glass with review |
| Risk to individuals? | Data classes involved (bank, tax id, salary, contact) |
| Clock | GDPR Art. 33: a controller notifies the supervisory authority within 72 h of awareness; Zoiko as processor must notify the controller without undue delay. Counsel confirms the applicable regime per region (UK, IN, US states, ME, APAC) |
| Customer notification | The customer (controller) owns notification to its workers and authority under the DPA; Zoiko supports with facts |

Record the time Zoiko became aware (UTC `Z`) in the incident record; every clock runs from there.

## 6. Communications

1. Internal: incident channel restricted to the roles in section 0; no worker data in messages.
2. Customer: initial notice to the tenant's org_admin(s) and DPA contact once S1 is likely; approved by counsel.
3. Updates: at agreed intervals until closure.
4. Regulators / data subjects: only by the controller, or by Zoiko for controller-role data, as counsel decides.

Templates (fill in, never include worker data):
- "On <date Z> we detected <type of event> affecting your Zoiko Payroll workspace <org code>. Access was <contained at time Z>. We are investigating and will update you by <time Z>. Reference: INC-..."

## 7. Post-incident review (within 10 working days)

- Timeline (UTC), root cause, which control failed or worked (control ids).
- Defects filed in `docs/privacy/defect_register.csv` (type `defect`, severity, owner).
- Alert threshold changes require a new decision entry (DEC-n) in the register.
- Break-glass reviews closed (C06).
- Lessons learned and owner/date per action.
- Sign-off by IC and DPO.

## Sign-off

| Role | Name | Signature | Date (UTC) |
|---|---|---|---|
| Security lead | | | |
| DPO / counsel | | | |
