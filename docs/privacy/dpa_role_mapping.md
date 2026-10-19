# DPA role mapping (control F01)

Status: awaiting Privacy counsel / DPO proof (HP-07). This is a template prepared by engineering. It is
not legal advice and nothing here has been reviewed by counsel. Every cell marked "to be confirmed by
counsel" must be completed and the signature block signed before F01 can be reviewed.

Prepared: 2026-10-19T00:00:00Z. Register: `docs/privacy/control_register.yaml`.

## 1. Roles per service model

| Processing activity | Data | Zoiko role (proposed) | Customer role (proposed) | Basis for the proposal | Counsel decision |
|---|---|---|---|---|---|
| Payroll processing for a customer organization (workers, pay, bank, tax, statutory filings) | Worker personal data, special identifiers (tax / national ids), bank details | Processor | Controller | Zoiko processes only on the customer's documented instructions (workspace configuration, runs it approves) | to be confirmed by counsel |
| Statutory filings submitted by the customer through Zoiko (tenant-run, DEC-3) | Worker identifiers, pay, contributions | Processor | Controller (filing obligation is the employer's) | Super Admin keeps catalog/config only | to be confirmed by counsel |
| Customer account, users, login, MFA, security logs | Customer staff contact and authentication data | Controller | n/a | Zoiko decides purpose and means (security, service delivery) | to be confirmed by counsel |
| Billing, subscriptions, invoicing (Stripe) | Customer billing contact, billable worker counts | Controller | n/a | Zoiko's own commercial relationship | to be confirmed by counsel |
| Platform aggregates / BI (k = 5 suppressed, DEC-1) | Aggregated counts and amounts, no identities | Processor (aggregates derived from customer data) or controller of anonymised output | Controller | Aggregates are suppressed below k = 5 and >= 2 organizations for money cells | to be confirmed by counsel |
| Security event log, alerts, support-access audit | Ids, codes, IPs, user agents of staff and customer users | Controller (security of the service) | Receives its own audit view (C07) | Needed for integrity and incident response | to be confirmed by counsel |
| Assist (in-product help; optional external model provider) | Questions, scrubbed context | Processor | Controller | Customer-initiated; egress scrubbed (D07) | to be confirmed by counsel |
| Public website Assist widget | Anonymous questions | Controller | n/a | No customer data | to be confirmed by counsel |

## 2. Sub-processors

| Service | Purpose | Data categories | Location / region | Transfer mechanism | Status |
|---|---|---|---|---|---|
| Google Cloud Platform (VM, Cloud Storage, KMS) | Hosting, object storage, security anchors, backups | All tenant data (encrypted at rest) | per tenant region (see `region_policy.md`) | to be confirmed by counsel | to be confirmed by counsel |
| Database provider (Neon Postgres per the original specification, or Cloud SQL / self-managed on GCP) | Primary database, backups / PITR | All tenant data | to be confirmed | to be confirmed by counsel | to be confirmed by counsel |
| Redis (Celery broker / result backend, cache) | Job queue | Job ids, status; tax reference data | Same host / region as the application | n/a if self-hosted on the VM | to be confirmed by counsel |
| SMTP email provider | Transactional email (payslip ready, notices, alerts) | Recipient email, names, payslip PDF attachment (DEV-7) | to be confirmed | to be confirmed by counsel | to be confirmed by counsel |
| Sentry | Error telemetry (scrubbed, no request bodies or frame locals) | Error metadata, user id only | to be confirmed | to be confirmed by counsel | to be confirmed by counsel |
| LLM provider for Assist (OpenAI-compatible endpoint, `ASSIST_MODEL_BASE_URL`) | Answer generation | Scrubbed question and context | to be confirmed | to be confirmed by counsel | to be confirmed by counsel |
| Stripe | Payments, subscriptions | Billing contact, payment method tokens | to be confirmed | to be confirmed by counsel | to be confirmed by counsel |
| Identity provider (Zoiko One, integration pending, DEV-6) | Federated login | Login email, tenant id | to be confirmed | to be confirmed by counsel | to be confirmed by counsel |

Statutory authorities (tax and social security agencies) receive data as independent recipients on the
controller's legal obligation; they are not sub-processors. To be confirmed by counsel.

## 3. Documented instructions

The customer's documented instructions are (proposal, to be confirmed by counsel):

1. The DPA and the order form.
2. The workspace configuration the customer's org_admin sets (jurisdictions, pay groups, entities, policies).
3. Actions the customer's users take (create runs, approve, file, export).
4. Support-access approvals given by the customer's org_admin (section 5).

Zoiko staff do not act on worker data outside these instructions. Platform roles have no standing access
to identifiable worker data (controls A01-A07, B01-B08).

## 4. Lawful access and government requests

| Rule | Proposal | Counsel decision |
|---|---|---|
| Any request for customer data from a public authority is routed to counsel / DPO, never handled by support | Required | to be confirmed by counsel |
| Notify the customer (controller) before disclosure unless legally prohibited | Required | to be confirmed by counsel |
| Challenge over-broad requests; disclose the minimum | Required | to be confirmed by counsel |
| Technical path: no platform role can read worker data; any disclosure would need a break-glass grant (C06) with incident reference, fresh MFA, tenant notice and independent review within 24 h | Engineering fact (C06, DEC-5) | n/a |
| Record every request in a register (date, authority, scope, outcome) kept by the DPO | Required | to be confirmed by counsel |
| Transparency reporting | Optional | to be confirmed by counsel |

## 5. Zoiko staff access rules (JIT support access)

| Control | Rule |
|---|---|
| C01 | Access only through a request with reason and ticket, approved by the tenant's org_admin |
| C02 | Independent approvals; no self-approval (service and DB constraint). Worker-scope grants also need platform_security (DEC-4) |
| C03 | Time-bound credentials, 30-minute hard maximum (DEC-6) |
| C04 | Read-only, scope- and field-class-limited, never export |
| C05 | Access ends on expiry, exit, revoke and logout; old tokens are refused |
| C06 | Break-glass: fresh MFA + incident reference, alert, tenant notice, independent review within 24 h (DEC-5) |
| C07 | Tenant sees its own support-access audit with named attribution |
| C08 | Support-access audit is append-only and hash-chained |

Infrastructure staff (DBA, cloud console, production shell) are covered by D01 / HP-01
(`deploy/security/pam_runbook.md`).

## 6. Sub-processor change notice

| Item | Proposal | Counsel decision |
|---|---|---|
| Notice period before a new or replaced sub-processor | 30 days | to be confirmed by counsel |
| Channel | Email to the customer's org_admin contacts + published list | to be confirmed by counsel |
| Objection right and remedy | Customer may object; termination of the affected service if unresolved | to be confirmed by counsel |
| Emergency replacement | Notice as soon as possible after the change | to be confirmed by counsel |

## 7. International transfers per region

Supported regions (DEC-9): EU, UK, US, IN, ME, APAC. Each organization has `organizations.data_region`;
privileged retrieval outside the region is refused (`region_policy.md`, F02).

| Tenant region | Hosting region (deployment `DATA_REGION`) | Transfers to sub-processors outside the region | Mechanism | Counsel decision |
|---|---|---|---|---|
| EU | EU | Sentry, LLM provider, SMTP, Stripe (if outside EU) | SCCs / adequacy (to be confirmed) | to be confirmed by counsel |
| UK | UK | as above | UK IDTA / addendum (to be confirmed) | to be confirmed by counsel |
| US | US | as above | to be confirmed | to be confirmed by counsel |
| IN | IN | as above | DPDP Act rules (to be confirmed) | to be confirmed by counsel |
| ME | ME | as above | local law (to be confirmed) | to be confirmed by counsel |
| APAC | APAC | as above | local law (to be confirmed) | to be confirmed by counsel |

Engineering note: at time of writing one deployment exists (default `DATA_REGION=EU`) and there is no API
to set a tenant's region other than the default; see `region_policy.md`.

## 8. Open questions for counsel

1. Are platform aggregates (k = 5) anonymous data or still personal data processed as processor?
2. Is the security event log (staff and customer user ids, IPs) controller processing under legitimate interest?
3. Is emailing payslip PDFs as unencrypted attachments (DEV-7) acceptable under the DPA's security annex?
4. Retention: 7 years after a worker leaves (DEC-10) and 7 years for audit (DEC-7) - confirm against each jurisdiction.

## Signature

| Role | Name | Organisation | Decision | Signature | Date (UTC) |
|---|---|---|---|---|---|
| Privacy counsel | | | | | |
| DPO | | | | | |
| Engineering owner (factual sections only) | | | | | |
