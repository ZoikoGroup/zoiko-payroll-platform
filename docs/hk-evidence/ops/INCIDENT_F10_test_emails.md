# Incident F-10: real email sent from local test runs

**Status:** OPEN. Engineering cause fixed (see §5). A human must check the mail server log (§6).
**Prepared:** 2026-10-14 by engineering (Claude). Nobody accessed the mail server or its logs to prepare this note.
**Severity (proposed, for the Security lead to confirm):** Low. The one confirmed message went to a made-up test address and carried test data only.

## 1. What happened

A local backend started from `backend/` reads `backend/.env`. That file holds the company's real SMTP account (host `smtpout.secureserver.net`, with a username and password). The app had no rule stopping a local or test backend from using it.

On 2026-10-13, during browser checks of the new break-glass feature, the local backend therefore **delivered at least one real email** through the company mail server to `hkadmin@zoikotest.dev`.

## 2. Confirmed sends (from retained local logs)

| When | Recipient | Template | Source |
|---|---|---|---|
| 2026-10-13 17:29:52 IST (11:59:52 UTC) | `hkadmin@zoikotest.dev` | `privileged_access_break_glass.html` | `scratchpad/bui/backend_evidence.log` line 142: `[email] Sent to hkadmin@zoikotest.dev` |

This is the only real send found in any retained log or in this project's Claude session transcripts (searched 2026-10-14). An earlier STATUS note said the second **and** third passes sent mail. Only the third pass is confirmed. The second pass's log was overwritten when the backend restarted at 11:58 UTC, so it is **unknown**, not ruled out (§3).

**Not ours, but the same failure:** the committed file `backend/uvicorn_fresh.log` (added in commit `4bd2d8c`, last changed in `e51fded`, both by another developer) records a local run on 2026-09-23 19:46 IST that "Sent to" `admin@test.com`, `info@zoikopayroll.com`, `zzz.throwaway.superadmin@zoiko.internal` and `pending-eval3-1790172971005@example.com`. `test.com` is a real, registered domain.

## 3. Every local browser or backend run in this project

Source: tool calls in this project's Claude Code transcripts, from the first browser run on 2026-09-16 to the last on 2026-10-13. Times are UTC. "Could send" means the backend was started from a directory whose `backend/.env` held real SMTP settings, and SMTP was not blanked.

| Session | Window (UTC) | What ran | Backend directory | Could send? | Log retained? |
|---|---|---|---|---|---|
| 2bdc89c1 | 2026-09-16 08:42 – 11:37 | browser checks (7) + local backend | `zpp-nikhil-extract` worktree (since removed), SQLite, `ENVIRONMENT=development` | Unknown: whether that worktree had a `.env` cannot be checked now | No |
| 45399e97 | 2026-09-17 10:31 – 10:40 | local backend, no browser | `zpp-8dl-activation-reconciliation` worktree (removed) | Unknown | No |
| f00c9084 | 2026-09-18 07:35 – 07:36 | local backend, no browser | `zpp-nikhil-extract` | Unknown | No |
| 959a667d | 2026-09-21 04:27 | 1 browser command, no backend start | – | Only if it used a backend started elsewhere | No |
| be6d0739 | 2026-09-23 09:48 – 2026-09-24 10:23 | browser checks (20) + local backend | main repo `backend/` (real `.env`) | **Yes** | No |
| 72243809 | 2026-09-25 08:27 – 2026-09-28 13:06 | browser checks (27); no backend start found in its commands | unknown | Unknown | No |
| 27267377 | 2026-09-29 03:46 – 12:26 | browser checks (23) + local backend | main repo `backend/` | **Yes** | No |
| de174a28 | 2026-09-30 04:09 – 04:12 | browser checks (2) + local backend | scratch export | Unknown | No |
| 61463e2f | 2026-10-01 03:24 – 2026-10-06 | Super Admin / tenant browser suites | main repo `backend/` | **Yes** | No |
| 61463e2f | 2026-10-13 03:47 – 05:45 | `browse`, `explore`, `lifecycle`, `chk`, `evcheck` (no break-glass) | main repo `backend/`, local PG scratch DB | **Yes** | Partly (`bui/backend.log`: no `[email]` lines) |
| 61463e2f | 2026-10-13 06:48 – 06:53 | `consent.cjs` (×2), `dbg.cjs`: **break-glass approvals** | same | **Yes** | **No** (overwritten at 11:58) |
| 61463e2f | 2026-10-13 11:58 – 12:00 | `consent.cjs`: break-glass approval | same | **Yes: 1 confirmed send** | Yes |
| all | from 2026-10-13 12:00 | scratch start scripts force `SMTP_HOST=""`; from this fix, the app blocks it anyway | – | No | – |

**Which mail paths those runs could reach.** All app email goes through one function, `email_service.send_approval_email`; the communications module calls it too. A browser run could therefore trigger any notice for the flows it exercised, such as organisation created/updated, jurisdiction or pack changes, evidence and report notices, payroll run notices, invites, password resets and break-glass. The app has no SMS sender and no outbound-webhook sender (checked by code scan and pinned by a test).

**Possible recipients on 2026-10-13.** The scratch databases `hk_browser` and `hk_evidence` contain exactly three users: `sa1@zoikotest.dev`, `sa2@zoikotest.dev` and `hkadmin@zoikotest.dev`. They hold no organisation contact emails and no employees. For the September and early-October runs the recipients are unknown; the databases those runs used are not retained.

## 4. Exact content of the break-glass notice

Built by `send_break_glass_access_notice_email` (template `privileged_access_break_glass.html`, wrapped in the standard branded layout). It went to each active org admin of the scratch organisation.

| Field | Value in the confirmed message |
|---|---|
| Subject | `Emergency support access to your payroll workspace \| Zoiko Payroll` |
| Preheader | `Zoiko support was granted emergency access to your organisation.` |
| Heading | `Emergency support access granted` |
| Session | `#<scratch session id>` |
| Reason given | `TEST-ONLY: P1 payroll stuck` (the `dbg.cjs` run used `dbg`) |
| Access window (UTC) | start – expiry of the scratch session (about 60 minutes) |
| From / branding | the configured SMTP sender, with the scratch organisation's branding (defaults) |

The message contained no payroll, employee or customer data. The scratch databases hold none.

## 5. Engineering fix (commit a on `nikhil`)

* `backend/app/core/outbound.py`: test mode (any pytest run, or `ENVIRONMENT`/`APP_ENV` = test, testing, ci) and local mode (`ENVIRONMENT`/`APP_ENV` = development, dev, local, or neither set with `DEBUG` true) **never deliver**. The only exception is `LOCAL_MAIL_SANDBOX_ENABLED=true`, and then mail goes only to `LOCAL_MAIL_SANDBOX_HOST:PORT`, without the real server's credentials. This rule overrides both `.env` and the `smtp_*` platform settings.
* `email_service.send_approval_email` asks the guard before opening any SMTP connection. A blocked send logs `[outbound] BLOCKED email to … NOT delivered`.
* `tests/conftest.py`: a run-wide tripwire replaces `smtplib.SMTP` and `SMTP_SSL`. Any test that reaches a real SMTP constructor fails, and the whole run exits non-zero. Tests that fake the transport must opt in explicitly (`fake_smtp_transport`).
* `tests/test_outbound_delivery_guard.py`: covers the mode classification, blocking in test and local mode, sandbox-only delivery, production behaviour, the tripwire, and a code scan proving only the guarded chokepoint opens SMTP and that no SMS or webhook client exists.
* 382 test email addresses on real domains (`test.com`, `acme.com`, `x.com`, `zoiko.dev`, `zoikotest.dev`) were changed to reserved `*.example.com` addresses in 25 test files. `.test` and `.invalid` were not used, because the app's email validator rejects them.

**Production caution.** `.env.production.example` sets `DEBUG=false` but no `ENVIRONMENT`. If production also left `DEBUG` unset (default `true`), the guard would treat it as local and block mail. Before deploying, confirm that production sets `ENVIRONMENT=production`, or at least `DEBUG=false` (`HK_DEPLOY_RUNBOOK.md`, pre-check P-6).

## 6. Checklist for a human (Claude did none of these)

**(a) Mail server sent log**
- [ ] Log in to the company mail account's provider (the SMTP host in `backend/.env`) as its administrator.
- [ ] Export the sent / outbound log for **2026-09-16 00:00 UTC to 2026-10-13 12:05 UTC**. Check these windows first:
  - 2026-10-13 06:45–06:55 and 11:55–12:05 UTC (break-glass);
  - 2026-10-13 03:45–05:50 UTC;
  - 2026-10-01 to 2026-10-06;
  - 2026-09-29 03:40–12:30 UTC;
  - 2026-09-23 09:40 to 2026-09-24 10:30 UTC;
  - 2026-09-23 around 14:16 UTC (the other developer's run in `uvicorn_fresh.log`).
- [ ] List every message sent to `*@zoikotest.dev`, `*@test.com`, `*@acme.com`, `*@x.com`, `*@zoiko.dev`, `*@zoiko.internal` and `*@example.com`, plus any other address that is not a real Zoiko colleague or customer.
- [ ] Record for each message: time, recipient, subject, and whether it was delivered or bounced. Attach the export to this incident.

**(b) Who owns `zoikotest.dev`**
- [ ] Look up the registrant with WHOIS / RDAP and check whether it has MX records. If Zoiko does not own it, mail to it may have reached a third party.
- [ ] Do the same for any other non-reserved domain found in (a).

**(c) Notification decision (Security lead, with legal counsel if needed)**
- [ ] Decide whether any recipient is outside Zoiko and whether the content (§4) needs a notice. On current evidence it contained only test text.
- [ ] Record the decision, its reason and the date on the blank lines below.

**(d) Local configuration**
- [ ] Remove the real SMTP username and password from every developer's local `backend/.env`. Use the sandbox (§7).
- [ ] Rotate the SMTP password, because it sits in plaintext in local `.env` files.
- [ ] Ask the owner of `backend/uvicorn_fresh.log` to delete it from the repository. It is a committed runtime log that contains email addresses.

## 7. Recommended local mail setup

```bash
docker run -d --name mailpit -p 1025:1025 -p 8025:8025 axllent/mailpit   # web UI: http://localhost:8025
```

In local `backend/.env`:
```
SMTP_HOST=
SMTP_USERNAME=
SMTP_PASSWORD=
LOCAL_MAIL_SANDBOX_ENABLED=true      # optional: only to see rendered mail in Mailpit
LOCAL_MAIL_SANDBOX_HOST=127.0.0.1
LOCAL_MAIL_SANDBOX_PORT=1025
```

A local `.env` must never hold real mail credentials. Only production (and staging, with its `STAGING_SANDBOX_EMAIL` redirect) should.

## Sign-off (leave blank)

| Role | Name | Decision / notes | Date | Signature |
|---|---|---|---|---|
| Security lead | | | | |
| Mail account administrator (log pulled) | | | | |
