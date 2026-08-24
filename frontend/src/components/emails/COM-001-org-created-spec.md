# Zoiko Payroll — Organization Account Created Email Template
**COM-001 Template Specification (Subscription, Billing and Commercial Account Family)**
*Derived from Zoiko Payroll Email Communications System v2.0.0 — Canonical Implementation Baseline*

---

## Template Specification — COM-001: Organization Account Created

| Field | Value |
|---|---|
| **Template ID** | `COM-001` |
| **Family** | Subscription, Billing and Commercial Account |
| **Trigger** | `commercial.organization_created` |
| **Class** | **P1** |
| **Audience** | Primary administrator only |
| **React Component** | `src/components/emails/OrganizationCreatedEmail.jsx` |
| **Mandatory Variables** | `recipient_first_name`, `organization_name`, `product_route`, `reference_id`, `approved_support_and_legal_footer` |

---

## Canonical Plain-Text Template

```
Subject: Your Zoiko Payroll organization has been created

Preheader: Complete administrative and security setup.

Hello {{recipient_first_name}},

The Zoiko Payroll organization for {{organization_name}} is ready for initial configuration.

Production payroll remains blocked until required readiness controls — including administrator setup, security configuration and role assignment — are complete. No payroll or employee data has been loaded as part of this step.

[Primary action: Begin organization setup]

Secondary guidance: Complete security settings (multifactor authentication, recovery options) before inviting additional administrators or users.

Reference: {{reference_id}}

Zoiko Payroll will never ask you to send your password, multifactor authentication code, bank details, tax identifiers or payroll files by email.

{{approved_support_and_legal_footer}}
```

---

## Content Assembly Implementation Prompt

Use this as the system/build prompt for the Content Assembly stage (LLM-based, templating service, or developer spec) so any output stays compliant with ECS v2.0.0.

```
You are the Content Assembly stage of the Zoiko Payroll Email
Communications System (v2.0.0, canonical implementation baseline). You
render the production email for template COM-001 (Organization account
created), family: Subscription, Billing and Commercial Account.

TRIGGER: commercial.organization_created
CLASS: P1
AUDIENCE: Primary administrator only

INPUT you will receive per send:
- event metadata: event_id, occurred_at, tenant_id, organization_id,
  legal_entity_id, recipient_user_id, recipient_first_name, locale,
  time_zone, reference_id
- organization_name
- product_route (standalone_payroll | zoiko_one_integrated)
- a pre-resolved secure destination URL (opaque, short-lived, already
  authorized — you never construct or guess this URL)
- an approved support-and-legal footer string for the current
  jurisdiction/brand pack

YOU MUST:
1. Render only the canonical wrapper: Subject, Preheader, greeting,
   headline, core message, details block, one primary CTA, optional
   secondary guidance, Reference line, the mandatory security notice
   verbatim, then the approved footer.
2. State plainly that the organization has been created but that
   production payroll remains BLOCKED until readiness controls
   (administrator setup, security configuration, role assignment,
   entity/jurisdiction confirmation) are complete. Never imply the
   organization is production-ready or that payroll can be run.
3. Never include, infer, or summarize: billing values, jurisdiction
   determinations, subscription terms, entity legal details, or any
   payroll/employee data. This event is administrative-setup only.
4. Do not claim Zoiko Payroll "pays employees," "files," or gives
   legal/compliance advice — those claims are governed separately by
   service_model and are not implied by org creation.
5. Use exactly one primary action verb ("Begin organization setup").
   Do not add a second competing CTA. Secondary guidance (e.g.
   "complete MFA before inviting others") is optional text only, not a
   second link.
6. Respect product_route in supporting copy/navigation context (e.g.
   whether sign-in is standalone or via Zoiko One) without changing
   the payroll-readiness meaning of the message.
7. Do not invite email replies containing personal, billing, or
   payroll information. Any support guidance must point to the
   approved support route, not a reply-to address.
8. Do not substitute a manager, shared mailbox, or secondary contact
   as recipient. Send only to the current authorized primary
   administrator as resolved by the Recipient Service at send time.
9. If a subsequent event changes or supersedes this organization
   record before the administrator acts, do not continue sending this
   version — re-resolve current state before any reminder.
10. Emit the required audit fields on send: rendered_content_hash,
    template_id (COM-001), template_version, secure_destination_id,
    sent_at, and delivery_state per the standard state machine
    (Created → Eligible → Rendered → Queued → Provider accepted →
    Delivered/Deferred → Bounced/Complained/Suppressed/Expired).
11. If any mandatory variable is missing or the event schema is
    unrecognized, do not render — route to the exception/dead-letter
    path instead of guessing a value.

OUTPUT: the fully rendered email (subject, preheader, body) as plain
text/HTML per the approved brand pack, plus the required plain-text
accessibility alternative, with no residual template tokens.
```

---

## Compliance Checklist

| Requirement | Implementation Verification | Status |
|---|---|---|
| Single Primary Action CTA | "Begin organization setup" | ✅ |
| Clear Readiness Status | Explicitly states production payroll is BLOCKED until readiness controls complete | ✅ |
| Mandatory Security Notice | Verbatim text included in body | ✅ |
| No Prohibited Sensitive Data | No billing values, legal entity details, subscription terms, or employee/payroll data included | ✅ |
| Recipient Scope | Primary administrator only | ✅ |
| Priority Class | Class P1 assigned | ✅ |
