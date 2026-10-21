# Privileged access management runbook (D01 / HP-01)

Status: awaiting Infrastructure owner proof (HP-01). Template - not in force until applied, exercised and signed.
IaC: `deploy/security/iam_roles.tf` (not applied).

## 1. Principles

- No standing human access to production data stores, the production VM shell or the cloud console admin role.
- Access is just-in-time, for one justified task, at most **30 minutes** per grant (mirrors support access, DEC-6).
- The approver is a platform_security member who is not the requester.
- Every session is recorded or logged; recordings are kept with the incident / change record.
- Infrastructure access is separate from application roles: a DBA credential is never the application DB role
  (`zoiko_app`) and never the migration role used by CI (see `docs/privacy/rls_runbook.md`).

## 2. Access paths

| Need | Group | Mechanism | Recording / logging |
|---|---|---|---|
| Production shell on the VM (`zoiko-payroll-backend`, `/var/www/zoiko-payroll`) | `zp-prod-shell` | PAM entitlement `zp-prod-shell` -> `roles/compute.osAdminLogin` + `roles/iap.tunnelResourceAccessor`; connect with `gcloud compute ssh --tunnel-through-iap` (OS Login, no SSH keys in metadata) | IAP and OS Login audit logs; session recording via `tlog` / `auditd` TTY logging shipped to Cloud Logging (install on the VM) |
| Cloud console admin | `zp-cloud-console-admin` | PAM entitlement `zp-console-admin` | Cloud Audit Logs (Admin Activity + Data Access) |
| DBA break-glass | `zp-dba-breakglass` | PAM entitlement `zp-dba-breakglass` -> read of the DBA secret in Secret Manager; for Cloud SQL `roles/cloudsql.client` via Auth Proxy over IAP | DB statement logging for the DBA role (`log_statement = 'all'` on that role), Secret Manager access logs |
| Backup restore | `zp-restore-operators` | Bucket read on the backup bucket (`backup_iam.tf`), ideally via PAM | Storage data-access logs |
| CI deploy | service account `zp-ci-deployer` | GitHub OIDC workload identity, IAP + OS Login non-admin | Audit logs; no human use |

Fallback when PAM is unavailable: the approver applies a time-bound IAM condition
(`request.time` window <= 30 minutes, `fallback_timebound_shell` in `iam_roles.tf`) and removes it afterwards.

## 3. Request and approval flow

1. Requester opens a change or incident ticket (id required) stating task, systems, expected duration.
2. Requester raises a PAM grant request with the ticket id as justification, duration <= 30 minutes.
3. Approver (platform_security, not the requester) checks: ticket exists, scope is minimal, time is
   necessary. Out-of-hours (outside 07:00-20:00 UTC) requests need an incident reference.
4. Grant activates; requester connects through IAP only.
5. Work is done. No exports of tenant data to laptops; if a file is unavoidable (for example a
   statutory evidence query) it is aggregate-only and stored in the ticket's evidence location.
6. Grant expires automatically or the requester ends it early.
7. Requester records in the ticket: start/end UTC (`Z`), commands summary, recording reference.

Emergency: if no approver is reachable, the incident commander may approve; an independent review
within 24 h is mandatory (same rule as application break-glass, DEC-5).

## 4. Review

| Review | Frequency | Owner | Output |
|---|---|---|---|
| All PAM grants vs tickets | Weekly | Security lead | Unmatched grants filed as defects |
| Group membership (prod shell, console admin, DBA, restore) | Quarterly, and on every leaver (JML, HP-05) | Infrastructure owner | Signed reconciliation |
| Sample of session recordings | Monthly, 10 % of sessions | platform_security | Review notes |
| Standing bindings scan (`gcloud projects get-iam-policy`) | Monthly | Infrastructure owner | Zero human owner/editor bindings |

## 5. Proof record (HP-01)

| Item | Value |
|---|---|
| `iam_roles.tf` applied (date UTC, plan hash) | |
| PAM entitlements listed (export attached to EP-02) | |
| Test grant: request, approval, expiry at 30 min (ids, UTC times) | |
| Session recording sample reference | |
| Standing-binding scan result | |
| Infrastructure owner signature / date | |
| Reviewer signature / date | |
