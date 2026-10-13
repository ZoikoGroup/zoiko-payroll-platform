# Hong Kong launch work — STATUS (2026-10-13, third pass)

**Bottom line:** every engineering item that can be done safely is done and tested. The evidence drafts and upload kit are regenerated and rehearsed. The work is committed **locally** on `feature/hk-launch-readiness`: no push, no PR, no deploy, no production write. Nothing is accepted, signed, marked specialist-verified or activated. Launch remains blocked on the decision and external items in `BLOCKERS.md`.

## 1. What changed in this pass

| Task | Result |
|---|---|
| 1 Owner-pack integrity | Of the 23 owner files whose digests were recorded earlier, only `G6/OPERATIONS_RUNBOOK.md` differs (row #22, as requested). My earlier edit had also converted that whole file from LF to CRLF. I found this, rebuilt the original (its SHA-256 matches the recorded `eba17069…`), and restored LF, so **only line 53 differs**. Its current digest is `750cf274…`, and the G6 cover cites it (four places refreshed). Configuration matrix CSV: the content of all 255 original rows is unchanged (the 2 deferral rows were added); it was LF before and after; byte identity of the untouched rows **cannot be proven**, because no pre-edit copy or valid recorded digest exists (the one in `G1/G1_EVIDENCE_MANIFEST.md` predates a later regeneration). No other evidence draft cited a stale owner digest. Commit 8 (owner pack baseline) is prepared but **not** made |
| 2 Migration review | `ops/MIGRATION_8b14824fb575_REVIEW.md`: additive only; no backfill; catalog-only column adds on PG 14; one FK validation scan over `assisted_access_sessions` (row count unknown: the production copy is schema-only); short locks on `users` / `organizations`. **Not a STOP condition** |
| 3 General holidays | Governed `HK_GENERAL_HOLIDAY` rows plus the loader `scripts/hk_load_general_holidays.py`: archived source, SHA-256 recorded, [G1] UNVERIFIED, Draft packs only, a reseed keeps the rows. 2026 / 2027 are **empty** and listed as `UNVERIFIED / SOURCE_REQUIRED` in the G1 worksheet (4 open-item rows). The deferral uses general holidays + weekends + signal days; with an empty list it behaves as weekends only and flags "general-holiday list not loaded". The 2026/27 calendar is unchanged; golden vectors are unchanged and pass |
| 4 Durable storage (F-8) | In production mode without Cloud Storage, evidence and HK document uploads are refused before writing (400 / 409), with an audited refusal. No excluded file was edited |
| 5 Break-glass notification | *Before:* the email was only queued, "notified" was recorded regardless, and there was no alert. *Now:* synchronous send with delivery confirmed. On failure, or with no active org admin, the session stays audited, a `TENANT_NOTIFICATION_FAILED` event is written, and a high-severity Security alert appears in Super Admin → Alerts. Runbook #22 updated (digest refreshed) |
| 6 eMPF guard | A code tripwire (no new reader of `mpf_member_account` outside the audited paths) plus a contract test on the filing view. Builder TODO is B-28 |
| 7 Design notes | `ops/DESIGN_F4_…` and `ops/DESIGN_F5_F6_…`; neither needs a `main.py` change |
| 8 Self-contained commits | Replayed one by one in a throwaway worktree, with an import check and focused HK + SG tests after each (HEAD baseline: 1253 passed, 0 failed). Commits 2, 2b and 3 fail on their own (snapshot fixture and route-count pins reach final values only in commit 4), so they are **merged into commit 4**. Every other commit passes alone. The final replayed tree equals the working tree on all 99 paths |
| 9 Verification | Full suite **5212 passed, 0 failed, 7 skipped, 2 xfailed**. Browser **10/10**. Upload kit: 32 MISSING → 32 registered (digests equal, none reviewed) → 32 MATCH → a tampered digest gives DIGEST_MISMATCH |

## 2. Incident: real email sent during scratch browser runs

The scratch backend reads `backend/.env`, which configures a real SMTP server. During the break-glass browser checks (second and third passes), the platform therefore **sent real emails through that server to the test address `hkadmin@zoikotest.dev`**. The backend log shows `[email] Sent to hkadmin@zoikotest.dev | template=privileged_access_break_glass.html`.

As far as the code shows, these break-glass notices were the only emails these runs sent: consent requests send no mail, and the API tests stub the sender. No production data was read or written. The scratch start scripts now force `SMTP_HOST=""`, so future scratch runs cannot send mail. Someone should check the SMTP account's sent log for these messages.

## 3. Tests

| Run | Started (UTC) | Result | Output SHA-256 |
|---|---|---|---|
| Full suite `python -m pytest tests/ -q -p no:cacheprovider -rf --tb=short` | 2026-10-13T11:40:36Z | **5212 passed, 0 failed, 7 skipped, 2 xfailed** | `b0382a08628cab4e9e2a379ee862d7f2f89b54dcd800bc66976e88cb66f56a7d` (`full_test_suite_output_2026-10-13.txt`) |
| G4 matrix | 08:54:53Z | 50 passed | `e68061ff…` |
| G5 security / privacy | 08:55:12Z | 41 passed | `9d490ef0…` |
| Per-commit focused (HK + SG + assisted + snapshots + alembic) | 2026-10-13 | 1: 1253 · 2+2b+3+4: 1271 · 5: 1281 · 5b: 1286 · 6: 1291 · 7: 1291 (0 failed after each group) | — |

## 4. Findings

**Closed:** F-1, F-3, F-7, F-8, F-9 (break-glass notification); the R-row coverage gaps; the contribution-day engineering; the general-holiday engineering; the banner time-zone bug.

**Open:** F-2 (D-4); F-4, F-5 and F-6 (design notes ready); the G1 items (29 flagged values plus 4 general-holiday open items); G2; G3.

## 5. Human actions per gate

| Gate | Action before a second Super Admin may Accept |
|---|---|
| G1 | Specialist certifies the 29 flagged values and the deferral rule. Archive and load the 2026 / 2027 general-holiday lists. Archive the authority PDFs and fill `source_document_sha256` |
| G2 | IRD schemas / software approval and eMPF credentials; run the test plan; build the eMPF builder via the filing view (B-28) |
| G3 | Set tolerances; run two real parallel cycles |
| G4 | QA lead signs (50/50, all rows end to end) |
| G5 | Security lead decides F-4, F-5 and F-6 (design notes) and D-4; counsel sets retention; sign |
| G6 | Payroll Ops fixes runbook #30 and names a monitoring owner; signs |
| G7 | Six signatures after G1–G6 PASS |
| D-1…D-14 | The owner signs each record |
| Production | Before deploy: review the migration (`ops/MIGRATION_8b14824fb575_REVIEW.md`) and rehearse it on a fresh schema copy. Deploy. Re-run the HK seed on the Draft packs. Provision `HK_IDENTITY_TOKEN_KEY`. Configure Cloud Storage (otherwise uploads are refused). Run the read-only verification. Upload the 32 kit items (A) and review them (B). Each tenant grants `HK_MPF_ACCOUNT_REVEAL` to its eMPF filer |
