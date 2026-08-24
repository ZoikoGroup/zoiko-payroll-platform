# Zoiko Payroll — Employee Leave Decision Email Templates
**ELC Family (Employee Lifecycle, Data and Sensitive-Change Controls)**
*Derived from Zoiko Payroll Email Communications System v2.0.0 — Canonical Implementation Baseline*

---

## Overview

The v2.0.0 catalog (280 templates) did not include an employee-facing leave **decision** email.
The nearest entry — **ELC-014 (Termination or leave event recorded)** — notifies the
payroll/HR data owner that a lifecycle event was *recorded*; it is not a decision email
sent back to the requesting employee.

**ELC-015** and **ELC-016** fill that gap and inherit every applicable rule from v2.0.0.

| Rule (source section) | Applied here |
|---|---|
| §07 Prohibited content | No leave dates, reason, medical/absence detail, or balance values in the email — only the decision and timestamp. Full detail lives behind the secure link. |
| §10 Canonical wrapper | Both use the exact `Subject / Preheader / Hello / headline / core_message / details_block / primary_cta / secondary_guidance / reference / security notice / footer` structure. |
| §04 Priority classes | Approved = **P2** (confirmation). Rejected = **P1** (action/decision required). |
| §06 Recipient resolution | Sent only to the current, authorized requesting employee — no manager CC by default. |
| §07 Secure-action controls | Destination is an opaque, authenticated link; reauthentication required before the underlying leave record is shown. |
| §05 Employer context | Message identifies the correct employing/responsible organization via `organization_name`. |

---

## Template 1 — ELC-015: Leave Request Approved

| Field | Value |
|---|---|
| **Trigger** | `employee.leave_request.approved` |
| **Class** | P2 |
| **Audience** | Employee (requester) |
| **React component** | `src/components/emails/LeaveApprovalEmail.jsx` |
| **Mandatory variables** | `recipient_first_name`, `organization_name`, `approved_at_local`, `reference_id`, `approved_support_and_legal_footer` |

**Canonical plain-text template:**

```
Subject: Your Zoiko Payroll leave request has been approved

Preheader: Review the approved status and any payroll impact securely.

Hello {{recipient_first_name}},

Your leave request for {{organization_name}} was approved at {{approved_at_local}}.

The secure workspace contains the approved dates, payroll treatment and any
required documentation. No leave dates, reasons or absence details are
included in this email.

[Primary action: Review leave decision]

Secondary guidance: If you believe this decision does not reflect your
current request, contact your organization's designated support route
before relying on it for other arrangements.

Reference: {{reference_id}}

Zoiko Payroll will never ask you to send your password, multifactor
authentication code, bank details, tax identifiers or payroll files by email.

{{approved_support_and_legal_footer}}
```

---

## Template 2 — ELC-016: Leave Request Rejected

| Field | Value |
|---|---|
| **Trigger** | `employee.leave_request.rejected` |
| **Class** | P1 |
| **Audience** | Employee (requester) |
| **React component** | `src/components/emails/LeaveReviewEmail.jsx` |
| **Mandatory variables** | `recipient_first_name`, `organization_name`, `decided_at_local`, `reference_id`, `approved_support_and_legal_footer` |

**Canonical plain-text template:**

```
Subject: Action required: your Zoiko Payroll leave request needs review

Preheader: Review the decision and available next steps securely.

Hello {{recipient_first_name}},

Your leave request for {{organization_name}} was not approved. The decision
was recorded at {{decided_at_local}}.

The secure workspace contains the reason, the decision owner and any
options available to you, including resubmission where permitted. No
leave dates, reasons or absence details are included in this email.

[Primary action: Review leave request decision]

Secondary guidance: If you have questions about this decision, use your
organization's designated support route rather than replying to this email.

Reference: {{reference_id}}

Zoiko Payroll will never ask you to send your password, multifactor
authentication code, bank details, tax identifiers or payroll files by email.

{{approved_support_and_legal_footer}}
```

---

## Content Assembly Implementation Prompt

Use this as the system/build prompt for the Content Assembly stage (LLM-based, templating
service, or developer spec) so any output stays compliant with ECS v2.0.0.

```
You are the Content Assembly stage of the Zoiko Payroll Email
Communications System (v2.0.0, canonical implementation baseline). You
render production emails for the ELC (Employee Lifecycle, Data and
Sensitive-Change Controls) family, specifically templates ELC-015
(leave request approved) and ELC-016 (leave request rejected).

INPUT you will receive per send:
- event_type: "employee.leave_request.approved" | "employee.leave_request.rejected"
- event metadata: event_id, occurred_at, tenant_id, organization_id,
  legal_entity_id, recipient_user_id, recipient_first_name, locale,
  time_zone, reference_id
- decision_timestamp (approved_at_local or decided_at_local)
- organization_name
- a pre-resolved secure destination URL (opaque, short-lived, already
  authorized — you never construct or guess this URL)
- an approved support-and-legal footer string for the current
  jurisdiction/brand pack

YOU MUST:
1. Select ELC-015 for "approved" events, ELC-016 for "rejected" events.
   Do not blend or invent a third variant.
2. Render only the canonical wrapper: Subject, Preheader, greeting,
   headline, core message, details block, one primary CTA, optional
   secondary guidance, Reference line, the mandatory security notice
   verbatim, then the approved footer.
3. Never include, infer, or summarize: leave dates, leave reason or
   category, absence/medical/disciplinary detail, balances, or any
   other payroll or personal data. State only that a decision exists,
   its class (approved/rejected) and its timestamp. All specifics live
   behind the secure link.
4. Assign priority class P2 to approved, P1 to rejected. Do not
   escalate rejected to P0 — it is a normal decision-required
   notification, not a continuity/security/deadline risk.
5. Use exactly one primary action verb ("Review leave decision" /
   "Review leave request decision"). Do not add a second competing CTA.
6. Do not imply the process is "complete" on rejection — use "was not
   approved," never "denied and closed," unless the workspace record
   confirms no further action is possible.
7. Do not invite email replies containing personal, medical, or
   payroll information. Any "contact support" guidance must point to
   the organization's approved support route, not a reply-to address.
8. Do not substitute a manager, HR contact, or shared mailbox as
   recipient. Send only to the current authorized requesting employee
   as resolved by the Recipient Service at send time.
9. Cancel any pending reminder tied to this leave request once a
   decision event is received — a decided request must not continue
   to generate "pending" notifications.
10. Emit the required audit fields on send: rendered_content_hash,
    template_id (ELC-015/ELC-016), template_version, secure_destination_id,
    sent_at, and delivery_state per the standard state machine
    (Created → Eligible → Rendered → Queued → Provider accepted →
    Delivered/Deferred → Bounced/Complained/Suppressed/Expired).
11. If any mandatory variable is missing or the event schema is
    unrecognized, do not render — route to the exception/dead-letter
    path instead of guessing a value.

OUTPUT: the fully rendered email (subject, preheader, body) as plain
text/HTML per the approved brand pack, plus the plain-text alternative
required for accessibility, with no residual template tokens.
```

---

## Compliance Checklist

| Check | ELC-015 | ELC-016 |
|---|---|---|
| No leave dates in body | ✅ | ✅ |
| No leave reason / category | ✅ | ✅ |
| No absence / medical detail | ✅ | ✅ |
| No balance or payroll values | ✅ | ✅ |
| Single primary CTA | ✅ | ✅ |
| Mandatory security notice present verbatim | ✅ | ✅ |
| Correct priority class assigned | P2 ✅ | P1 ✅ |
| "Was not approved" (not "denied and closed") | — | ✅ |
| No reply-to email invite for sensitive data | ✅ | ✅ |
| Organization name in body | ✅ | ✅ |
| Reference ID in body | ✅ | ✅ |
