# Independent tester handover pack (control E07)

Status: awaiting Independent QA proof (HP-06). Control E07 is `NT` until an independent tester executes this
pack and files the results. Engineering has not run this pack as an independent party.

## 1. Scope

Verify, from outside the engineering team, that the 46 controls of ZP-PRIV-VERIFY-001 behave as claimed on a
staging deployment of the build named in `docs/privacy/evidence_index.md`. Priority: the P0 controls in
sections A-C and the testable parts of D-E. Out of scope: human/infra proofs HP-01..HP-11 (separate owners),
load testing, and any production environment.

Rules:
- Staging only. Never use production data, production tenants or real people. Use reserved domains
  (`*.example`, `*.test`) for every email.
- Do not try to bypass MFA by editing the database; report anything you can only do with DB access.
- Record every request with UTC time (`Z`), persona, endpoint, expected and actual status.

## 2. Getting the API surface

| Item | How |
|---|---|
| OpenAPI spec | `GET https://<staging-host>/openapi.json` (save the file and its SHA-256 with your report) |
| Interactive docs | `https://<staging-host>/docs` if enabled on staging |
| Entry-point inventory | `docs/privacy/route_policy_inventory.csv` (one row per method + path; generated from `backend/app/core/authz/route_registry.json`) |

Inventory columns:

| Column | Meaning |
|---|---|
| `method`, `path` | Route as mounted (prefix `/api`) |
| `data_class` | `public`, `self`, `platform`, `aggregate`, `tenant_lifecycle`, `tenant_config`, `worker`, `support`, `security` |
| `action` | `read`, `export`, `create`, `update`, `delete`, `approve` (read never implies write) |
| `resource` | Last path segment / resource name |
| `principals` | Roles allowed by the route (pipe-separated). Empty = nobody |
| `scope_level` | `public`, `self`, `tenant`, `platform` |
| `field_classes` | Field classes the route can return (projection per role) |
| `retired_reason` | Non-empty = route is retired and must deny everyone |
| `scan_worker_tables` | Worker tables a call-graph scan found behind the route |
| `overridden` | `yes` when a reviewed manual override changed the generated entry |
| `note` | Reviewer note for overrides |

Any route in `openapi.json` that is missing from the inventory is a defect (it should be denied as unregistered).

## 3. Test accounts

### 3.1 Synthetic tenants

1. Ask engineering for a staging database built from Alembic (not `create_all`) and seeded with
   `python -m scripts.generate_synthetic_data --tenants 2 --workers 25` (tenant codes `SYN001`, `SYN002`;
   identifiers deliberately fail real checksums) or with the PRIVA / PRIVB layout of `backend/tests/privacy/conftest.py`.
2. Each tenant needs two legal entities and two pay groups so scoped personas can be tested.

### 3.2 Personas

| Persona | Role | How it is created | Notes |
|---|---|---|---|
| SA | super_admin | `python -m scripts.seed_super_admin` on staging (engineering) | MFA mandatory |
| SP | support_operator | Provisioned by engineering on staging (no self-service route) | MFA mandatory |
| PS1, PS2 | platform_security (two different people) | Provisioned by engineering | Needed for zoiko-approve and independent break-glass review |
| TA / TB | org_admin of tenant A / B | `scripts/seed_org.py` or tenant registration, emails `ta@tenant-a.example`, `tb@tenant-b.example` | |
| PA | payroll_admin of tenant A scoped to entity A-E1 | TA creates via `POST /api/auth/admin/users`, then `PUT /api/organization-admin/users/{user_id}/scope` | |
| EA | employee persona of worker A1 | Policy-only persona (DEC-2: no employee login is shipped); engineering mints a token for tests | Expect self-only behaviour |
| MC | machine client of tenant A | TA: `POST /api/organization-admin/api-clients` (step-up needed; secret shown once) | |
| ST | temporary support login | Issued by an approved grant (`GET /api/super-admin/support-access/{grant_id}/credentials`) | Max 30 min |

### 3.3 MFA enrolment

Privileged roles must enrol TOTP at first sign-in: `POST /api/auth/login` -> `POST /api/auth/mfa/enroll/begin`
-> `POST /api/auth/mfa/enroll/confirm`. Later sign-ins use `POST /api/auth/mfa/challenge`. Sensitive actions
(approving grants, issuing credentials) need `POST /api/auth/mfa/step-up` within 300 s. Use a test
authenticator dedicated to staging; store recovery codes in the QA vault only.

## 4. Test catalogue (T01-T12)

Automated equivalents live in `backend/tests/privacy/test_t01_t08.py` and `test_t09_t12.py`; evidence JSON in
`backend/tests/privacy/evidence/`. Your job is to reproduce them independently against staging.

| Test | Persona | Action | Expected result | Controls |
|---|---|---|---|---|
| T01 | SA | Open Super Admin registry, reports and BI | Organization metadata and k-suppressed aggregates only (cells < 5, money cells < 2 orgs suppressed); no names, ids of workers, salaries | A01, A02, A06 |
| T02 | SA | `GET /api/payroll/employees`, `/employees/{employee_id}`, `/payslips` | 403 (or 404 per convention), denial recorded as a security event | A01 |
| T03 | SA | Salary, bank, tax, statutory profile, payslip download, bank-transfer file, export routes | 403; export attempts recorded as `EXPORT_DENIED` | A01, A02 |
| T04 | TA | Change tenant / worker ids in URL, body, headers to tenant B values | 404 with no existence leak (same response for "exists elsewhere" and "does not exist") | A04, A07 |
| T05 | TA, PA, EA | TA reads tenant B; PA reads worker A2 (outside entity A-E1); EA reads A2 | All denied; PA lists only A-E1 workers; EA only own record | A04, B03 |
| T06 | SP | Read tenant A worker without a grant; request without reason/ticket | Denied; request needs reason + ticket and tenant approval | C01 |
| T07 | ST (grant for A1, read-only) | Read A1; read A2; read tenant B; write; export; payslip download | A1 readable with field projection; everything else denied | C04, B04 |
| T08 | ST | Revoke the grant (TA or PS1), then replay the old token; let a grant expire, replay before the sweep | Denied immediately in both cases | C03, C05 |
| T09 | SA, all platform roles | Sweep every worker / tenant workflow route; search parameters; file URLs; job result URLs; check `Cache-Control` on responses | Denied; no worker identity in any platform response; `Cache-Control: no-store, private` on credentialed responses | A01, B03, B06, B07 |
| T10 | MC, job | MC names tenant B in path/body/header; deactivate / demote the job requester or suspend the org, then retry a queued payslip job | Denied and audited (`JOB_DENIED`, reason code) | A04, D06, D08 |
| T11 | TA, PA, EA, SA | Assist questions across tenants, parameter tampering, prompt injection asking for names/wages; kill switch on | Tool denials neutral and audited; no names, wages, identifiers in model egress (needs engineering capture); kill switch stops every path | D07 |
| T12 | PS1, PS2 | Probe sequence then a break-glass drill (fresh MFA + incident ref), tenant notice, review by PS2 within 24 h | Every probe attributable by correlation id; alert fired; review closed by a different officer | C06, E01, E03 |

Also exercise: self-approval (C02), 30-minute maximum (C03), tenant audit tab (C07), hash chain verify
(`GET /api/super-admin/security-events/verify`), legal hold four-eyes (F03), cross-region refusal (F02).

Known open items to retest (from `indirect_paths_audit.md`): a support temporary login downloading
`GET /api/payroll/generated-reports/{id}/certificate/{employee_id}` (classified read), and
`/generated-reports/{id}/rti-xml` emitting no export event.

## 5. Filing defects

Add rows to `docs/privacy/defect_register.csv`:

```
id,title,control_id,control_priority,type,severity,status,owner,opened_at,closed_at,notes
```

| Column | Allowed values / format |
|---|---|
| `id` | `PD-NNN`, next free number |
| `title` | One line, no personal data |
| `control_id` | A01..F07 |
| `control_priority` | `P0` or `P1` (from the register) |
| `type` | `defect` or `exception` |
| `severity` | `critical`, `high`, `medium`, `low` |
| `status` | `open`, `closed`, `resolved`, `wont_fix_accepted` |
| `owner` | Team or role |
| `opened_at`, `closed_at` | `YYYY-MM-DDTHH:MM:SSZ` (closed_at empty while open) |
| `notes` | Test id, evidence file, reproduction pointer |

`backend/scripts/check_privacy_defects.py` (F06) fails the release on any open critical privacy defect or open
P0 exception. Do not mark anything closed yourself unless you retested it.

## 6. Report

Fill in `docs/privacy/qa_report_template.md`, attach evidence to `docs/privacy/evidence_pack/EP-06/`
(QA report) and `EP-03` (your request logs), and send the defect register diff to the Platform Engineering owner.

## Sign-off

| Role | Name | Organisation | Signature | Date (UTC) |
|---|---|---|---|---|
| Independent tester | | | | |
| Platform Engineering (handover given) | | | | |
