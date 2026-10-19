# Evidence index (control F05)

Status: TEMPLATE - awaiting the independent reviewer's signature (HP-09). Management status: NOT ATTESTED.
Nothing listed here is a pass. Engineering statuses are limited to `NT`, `ENGINEERING_COMPLETE_AWAITING_REVIEW`
and `FAIL` (see `control_register.yaml`).

A machine-readable version of this index is produced by `backend/scripts/run_privacy_attestation.py`
(referenced by the register; not present in the repo at time of writing). It stamps the git SHA it ran on;
any later change under a CODEOWNERS privacy path invalidates it (F07).

## 1. Build under review

| Field | Value |
|---|---|
| Git commit SHA (full) | |
| Branch / tag | |
| CI build number / run URL | |
| Backend image or release artefact hash (SHA-256) | |
| Alembic head | |
| Route registry hash (`backend/app/core/authz/route_registry.json` SHA-256) | |
| `route_policy_inventory.csv` SHA-256 | |
| `control_register.yaml` SHA-256 | |

## 2. Environments

| Environment | URL (placeholder) | Region (`DATA_REGION`) | DB role enforces RLS (`check_row_level_security` report) | `DB_RLS_REQUIRE_ENFORCED` | Deployed SHA | Date (UTC) |
|---|---|---|---|---|---|---|
| CI (SQLite + disposable Postgres) | n/a | EU | | n/a | | |
| Staging | https://staging.example.test | | | | | |
| Production | https://app.example.test | | | | | |

## 3. Test run

| Field | Value |
|---|---|
| Test date (UTC) | YYYY-MM-DDTHH:MM:SSZ |
| Command | `python -m pytest backend/tests/privacy -q` (+ `ZP_TEST_POSTGRES_URL` for Postgres guards) |
| Result summary (counts only) | |
| Evidence JSON folder | `backend/tests/privacy/evidence/` |
| Executed by | |

## 4. Sample tenants (synthetic only)

| Tenant | Code | Contents | Source |
|---|---|---|---|
| A | PRIVA | 2 legal entities, 2 pay groups, workers A1, A2 | `backend/tests/privacy/conftest.py` |
| B | PRIVB | 2 legal entities, 2 pay groups, worker B1 | `backend/tests/privacy/conftest.py` |
| Staging synthetic | SYN001..SYNnnn | generated | `backend/scripts/generate_synthetic_data.py` |

Personas: SA (super_admin), SP (support_operator), APP and PS2 (platform_security), TA / TB (org_admin),
PA (payroll_admin scoped to entity A-E1), EA (employee persona of A1, policy only). All emails are on
reserved domains (`*.example`).

## 5. Evidence pack folders (`docs/privacy/evidence_pack/`)

The folder does not exist yet at time of writing; each line states what must be placed there.

| Folder | Contents | Controls | Produced by | Present (Y/N) |
|---|---|---|---|---|
| EP-01 | Architecture and decision-point inventory: route registry (`route_registry.json`), `route_policy_inventory.csv`, PDP decision order, data-class matrix (`MATRIX` in `core/authz/policy.py`), indirect paths audit | A01-A07, B01-B03 | engineering | |
| EP-02 | Effective roles and entitlements export, privileged inventory (`privileged_inventory.json` from `GET /api/super-admin/privileged-inventory`), machine-client inventory, service-account and cloud IAM exports, JML reconciliation sample, restore-drill result JSON | E04, E05, D01, D02 | engineering + infra | |
| EP-03 | Negative-test evidence: `backend/tests/privacy/evidence/*.json` and log samples (T01-T12, D03-D05, PG_*) | A, B, C, D | CI run | |
| EP-04 | Support-access and break-glass records: grant list, tenant audit sample, break-glass review record (ids only) | C01-C08 | platform_security | |
| EP-05 | Audit samples, alert drill (`alert_drill.json`), alert rules (`docs/privacy/alert_rules.json`), immutability config (triggers, purge flag off), chain verify output, anchor receipts | E01-E03 | security engineering | |
| EP-06 | CI gate run (privacy-isolation job), post-deploy smoke output, QA report (`qa_report_template.md` filled), defect register snapshot, build manifest | E06, E07, F06, F07 | engineering + QA | |
| EP-07 | Privacy and legal review pack: DPA role mapping, region policy, incident playbook + tabletop record, test-data lineage, deviations DEV-1..7 with acceptance | F01-F04, D09 | DPO / counsel | |

## 6. Human and infrastructure proofs

| Id | Proof | Owner | Artefact | Status |
|---|---|---|---|---|
| HP-01 | PAM / JIT infra access with session recording | Infrastructure owner | `deploy/security/pam_runbook.md`, `iam_roles.tf` | awaiting Infrastructure owner proof |
| HP-02 | Backup IAM applied + restore drill | Infrastructure owner | `backup_iam.tf`, `deploy/scripts/restore_drill.sh` | awaiting Infrastructure owner proof |
| HP-03 | NOBYPASSRLS non-owner app role; `DB_RLS_REQUIRE_ENFORCED=true` | Infrastructure owner | `docs/privacy/rls_runbook.md` | awaiting Infrastructure owner proof |
| HP-04 | Retention-locked anchor bucket + anchor job | Infrastructure owner | `anchor_bucket.tf` | awaiting Infrastructure owner proof |
| HP-05 | JML feed + quarterly reconciliation signed | HR / IdP owner | `backend/scripts/jml_reconcile.py` | awaiting HR / IdP owner proof |
| HP-06 | Independent tester executes handover pack | Independent QA | `independent_tester_handover.md` | awaiting Independent QA proof |
| HP-07 | DPA role mapping | Privacy counsel / DPO | `dpa_role_mapping.md` | awaiting counsel proof |
| HP-08 | Tabletop run and recorded | Security lead | `tabletop_record_template.md` | awaiting Security lead proof |
| HP-09 | This index signed | Independent reviewer | this file | awaiting Independent reviewer proof |
| HP-10 | Branch protection + staging smoke | Repository admin | workflows | awaiting Repository admin proof |
| HP-11 | Stripe webhook secret rotated | Platform owner | none | awaiting Platform owner proof |

## 7. Independent reviewer

| Field | Value |
|---|---|
| Name | |
| Organisation | |
| Independence statement (not involved in building the controls) | |
| Reviewed git SHA | |
| Scope reviewed | |
| Exceptions accepted (defect register ids) | |

## Signatures

| Role | Name | Signature | Date (UTC) |
|---|---|---|---|
| Independent reviewer | | | |
| Platform Engineering owner | | | |
| Security lead | | | |
| DPO | | | |
