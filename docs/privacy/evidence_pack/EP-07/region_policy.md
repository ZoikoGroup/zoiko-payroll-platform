# Data region, retention, legal hold and DSAR policy (controls F02, F03)

Status: F02 / F03 engineering complete, awaiting review. Nothing here is verified.
Code: `backend/app/modules/security/governance.py`, `backend/app/modules/security/router.py`.
Decisions: DEC-9 (regions), DEC-10 (retention 7 years after leaving), DEC-7 (audit 7 years, purge off).

## 1. Region per tenant

| Item | Value |
|---|---|
| Field | `organizations.data_region` (`String(8)`, NOT NULL, default and server default `EU`; added by migration `e1a3c5e7f9b2`) |
| Supported regions | `EU`, `UK`, `US`, `IN`, `ME`, `APAC` (`governance.SUPPORTED_REGIONS`, DEC-9) |
| Deployment region | `settings.DATA_REGION` (default `EU`). `home_region()` raises at use if the value is not a supported region |
| Tenant view | `GET /api/organization-admin/data-governance` returns `dataRegion`, `deploymentRegion`, `supportedRegions`, retention, holds, requests |

## 2. Enforcement hooks

`governance.assert_region(org, operation, target_region=None)` refuses when the tenant's region differs
from the target (default: this deployment's region). Failure is `RegionPolicyViolation`: HTTP 403,
error code `DATA_REGION_POLICY`.

| Hook | Where | Behaviour |
|---|---|---|
| Support access request | `support_access/service.py` `request_grant` (`assert_region(org, "Support access")`) | Request refused with 403 `DATA_REGION_POLICY` |
| Break-glass | `support_access/service.py` `open_break_glass` (`assert_region(org, "Emergency access")`) | Refused |
| Temporary support login (every request) | `core/authz/policy.py` `_support_temp_denial` (`assert_region_for_org_id`) | PDP deny, reason `DATA_REGION_POLICY` |
| Backup / replication / restore targets | `assert_region(org, "backup", target_region=<target>)` | Function and test exist. No backup or restore script calls it yet (see Gaps) |
| Processing jobs | not wired | `authorized_job` does not call `assert_region` (see Gaps) |

## 3. Setting and changing a tenant's region

| Item | Today | Required policy |
|---|---|---|
| Set at creation | Always the default `EU`; registration does not capture a region | The region is chosen at onboarding by Zoiko Sales Ops from the contract and recorded |
| Change | No API. Only a direct database change is possible | A change is a data migration, not a settings edit: needs a signed customer request, approval by platform_security and the DPO (four-eyes), a migration plan that moves data to the new region's deployment, and a security event. Until an API exists, ops must not edit the column by hand |
| Who may change | n/a | Nobody alone. No platform role has a route for it |

## 4. Retention (DEC-10, DEC-7)

| Data | Period | Mechanism |
|---|---|---|
| Worker payroll data | 7 years after `payroll_employees.date_of_leaving` (`WORKER_DATA_RETENTION_YEARS=7`) | `governance.retention_candidates()` lists workers past the cutoff and not under any hold. The purge is an explicit, logged operator action, never automatic |
| Audit and security events | 7 years (`AUDIT_RETENTION_YEARS=7`) | `AUDIT_PURGE_ON_ORG_HARD_DELETE=false` by default: an organization hard-delete is refused while audit rows exist |
| Security anchors | 7 years, retention-locked bucket | `deploy/security/anchor_bucket.tf` (HP-04) |

## 5. Legal hold

| Rule | Implementation |
|---|---|
| Scope | Platform-wide: hold rows use `jurisdiction_country = "XX"` and cover every jurisdiction of the organization, or of one worker (`employee_id`) |
| Placing | `POST /api/organization-admin/legal-holds` (org_admin, reason required); emits `LEGAL_HOLD_PLACED` |
| Effect | `assert_not_on_hold` (409 `LEGAL_HOLD`) blocks employee delete, bulk delete, organization hard-delete, retention purge and DSAR erasure completion |
| Release | `POST /api/organization-admin/legal-holds/{hold_id}/release`; must be a different administrator from the one who placed it (four-eyes); reason required; emits `LEGAL_HOLD_RELEASED` |

## 6. Data subject requests (DSAR)

| Step | Implementation |
|---|---|
| Received | `POST /api/organization-admin/data-access-requests` (types `access`, `erasure`, `rectification`); employee must be in the admin's scope; status `received`; `due_at = received_at + 30 days` |
| Fulfilment | Tenant-side by the org_admin using tenant routes. No platform role sees the subject's data |
| Completed | `POST /api/organization-admin/data-access-requests/{request_id}/complete` with outcome; erasure is refused while the worker is on hold |
| Tracking | Listed with due dates in `GET /api/organization-admin/data-governance` |

Zoiko (as processor) assists the controller; it does not answer data subjects directly (see `dpa_role_mapping.md`).

## 7. Tests

| Test | Proves |
|---|---|
| `tests/privacy/test_redaction_federation_governance.py::test_cross_region_privileged_retrieval_is_blocked` | Support access to a tenant in another region gets 403 `DATA_REGION_POLICY`; `assert_region(..., "backup", target_region=...)` refuses a cross-region target |
| `tests/privacy/test_redaction_federation_governance.py::test_legal_hold_blocks_every_deletion_path_and_needs_four_eyes` | Hold blocks delete paths; same admin cannot release |
| `tests/privacy/test_redaction_federation_governance.py::test_retention_candidates_respect_holds_and_dsar_lifecycle` | Retention candidates exclude held workers; DSAR lifecycle and due date |

## 8. Gaps (open)

1. No API to set or change `data_region`; every tenant is `EU` by default.
2. The governance docstring says backup / restore scripts and processing jobs call `assert_region`; in code only support access, break-glass and the PDP do. Backup tooling and `authorized_job` should call it.
3. `scripts/audit_retention.py` (referenced as the explicit purge) is not present in the repo at time of writing.
4. One deployment / one region exists; multi-region hosting is not built.

## Sign-off

| Role | Name | Decision | Signature | Date (UTC) |
|---|---|---|---|---|
| Platform Engineering owner | | | | |
| DPO | | | | |
| Independent reviewer | | | | |
