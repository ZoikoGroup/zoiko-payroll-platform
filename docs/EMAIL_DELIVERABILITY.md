# Email delivery: configuration, deliverability and verification

How to make organization, payment and invoice emails reliably reach inboxes, and how to check that they do.

## 1. Server settings (backend `.env` / process environment)

| Setting | Required value | Why |
|---|---|---|
| `ENVIRONMENT` | `production` (in the **process environment**, e.g. the systemd `EnvironmentFile`) | `app/core/outbound.py` blocks all outbound email in `development`/`local`/`test` mode. |
| `DEBUG` | `false` | With `ENVIRONMENT` unset, `DEBUG=true` (the config default) is read as local mode, which blocks all email. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS` | Your provider's SMTP relay (e.g. 587 + STARTTLS) | Empty `SMTP_HOST`: emails are only logged. |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Provider credentials, stored in the secret store | |
| `SMTP_FROM_EMAIL` | An address on the **verified sending domain**, e.g. `no-reply@zoikopayroll.com` | The default `no-reply@payroll.zoiko.example` is not deliverable. |
| `FRONTEND_URL` | `https://app.zoikopayroll.com` | Login, subscription and retry links in emails. |
| `STRIPE_WEBHOOK_SECRET` | The signing secret of the production webhook endpoint | Without it every Stripe webhook is rejected (400). |

At startup the backend logs `[startup] Email delivery: …` at ERROR level for each problem it finds. Super Admin → Subscriptions & Billing → **Email log** shows the same list.

An email that did not leave the server is recorded in `communication_events` with `outcome = 'not_delivered'` and the reason. Before this change it was recorded as `sent`.

## 2. DNS for the sending domain (SPF, DKIM, DMARC)

Configure these on the domain used in `SMTP_FROM_EMAIL`. Take the exact values from your email provider (SES, SendGrid, Postmark, Google Workspace, Microsoft 365, …).

| Record | Host | Example value |
|---|---|---|
| SPF (TXT) | `zoikopayroll.com` | `v=spf1 include:<provider-spf-domain> ~all`: **one** SPF record per domain; merge includes if one exists |
| DKIM (TXT or CNAME) | `<selector>._domainkey.zoikopayroll.com` | Public key / CNAME given by the provider; enable DKIM signing in the provider |
| DMARC (TXT) | `_dmarc.zoikopayroll.com` | Start with `v=DMARC1; p=none; rua=mailto:dmarc@zoikopayroll.com; adkim=s; aspf=s`, then move to `p=quarantine` and later `p=reject` once reports are clean |
| Return-Path / bounce (CNAME) | as the provider specifies | Aligns SPF with the From domain |

Verify:

```bash
dig +short TXT zoikopayroll.com            # SPF
dig +short TXT <selector>._domainkey.zoikopayroll.com
dig +short TXT _dmarc.zoikopayroll.com
```

Then send a test email to a Gmail address and choose **Show original**: `SPF: PASS`, `DKIM: PASS`, `DMARC: PASS`. Or use mail-tester.com.

## 3. Stripe

In Stripe Dashboard → Developers → Webhooks, the endpoint `https://app.zoikopayroll.com/api/billing/webhooks/stripe` must send:

- `checkout.session.completed`
- `customer.subscription.updated`, `customer.subscription.deleted`
- `invoice.paid`: receipt (BIL-001) and invoice email with PDF (BIL-002)
- `invoice.payment_failed`: payment failed with retry link (BIL-003)
- `invoice.upcoming`: renewal reminder (BIL-004). Also turn on **Settings → Billing → Subscriptions and emails → Upcoming renewal events** and pick how many days ahead
- `charge.refunded`, `charge.dispute.created`, `charge.dispute.closed`

If the webhook does not reach the environment, the success page (`POST /billing/checkout/confirm`) still records the first invoice and sends the receipt and invoice. The two paths share idempotency keys, so a late webhook never sends a duplicate.

## 4. Emails and where they come from

| Template | Event | Trigger |
|---|---|---|
| COM-001 `org_created.html` | `commercial.organization_created` | Self-serve registration / Super Admin creates an org |
| COM-003 `trial_org_created.html` | `commercial.evaluation_created` | 30-day evaluation signup |
| BIL-001 `payment_succeeded.html` | `billing.payment_succeeded` | `invoice.paid` with money collected |
| BIL-002 `invoice_issued.html` | `billing.invoice_issued` | Same; Stripe's invoice PDF attached (link always included) |
| BIL-003 `payment_failed.html` | `billing.payment_failed` | `invoice.payment_failed`, one per failed attempt |
| BIL-004 `subscription_renewal_reminder.html` | `billing.renewal_upcoming` | `invoice.upcoming` |

Recipients: the organization's active Org Admins, else the organization email, else the email Stripe holds for the customer.

Every send goes through `communications.dispatch_email`:

- an audit row in `communication_events` (type, recipient, status, attempts, error, time);
- an idempotency key;
- up to 3 attempts with backoff (2 s, 5 s) on transient SMTP failures.

## 5. Checking a specific organization

```sql
SELECT created_at, event_type, recipient_email, outcome, attempt_count, provider_response
FROM communication_events
WHERE organization_id = <org id>
ORDER BY created_at DESC;
```

Or in the UI:

- Org Admin → Subscription & Billing → **Email log**
- Super Admin → Subscriptions & Billing → **Invoices & emails** (per organization) or **Email log** (all organizations)

Both offer **Resend invoice / receipt**.
