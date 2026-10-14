# Hong Kong launch work: STATUS (2026-10-14, nikhil pass)

## 0. This pass (2026-10-14)

| Task | Result |
|---|---|
| 0 Move to `nikhil` | The 6 commits were cherry-picked onto local `nikhil` (`e9da6d4`, already up to date with `origin/nikhil`) **with no conflicts**. Each new commit's tree is identical to the original's. Single head `8b14824fb575`. Rehearsed on the production-schema copy: upgrade → downgrade → re-upgrade, exit 0. Re-parenting onto `main`'s head `2f905bb1c296` was also proven (needed when `nikhil` is merged into `main`; `ops/patches/reparent_8b14824fb575_onto_main_head.patch`). Focused tests 1291 passed; full suite **5212 passed, 0 failed, 7 skipped, 2 xfailed** on `b5b63b3` |
| 1 F-10 email incident | Test and local modes now never deliver email unless a local sandbox is explicitly enabled. A run-wide test tripwire fails any real SMTP attempt. 382 test addresses on real domains were moved to `*.example.com`. Incident note: `ops/INCIDENT_F10_test_emails.md` |
| 2 Owner pack | Proposal only, nothing committed: `ops/owner_pack_proposal/` (`gitattributes.proposed`, `MANIFEST.sha256` for 163 files) and `ops/OWNER_PACK_CSV_REVIEW.md` (255 existing rows: content columns unchanged against a regeneration; byte identity **not provable**; 2 added rows) |
| 3 Migration scan | Statement #11 (`ADD COLUMN approved_by_user_id … REFERENCES users`) reads every `assisted_access_sessions` row. Measured: 2,000,000 rows read; the patched version (`NOT VALID`) reads 0. Validating 2M rows costs about 0.3 s. A read-only row-count check was added to `hk_production_readonly_verification.py` |
| 4 Sign-off packets | `SIGNOFF_PACKETS/` (README + 9 packets) |
| 5 Deploy runbook | `ops/HK_DEPLOY_RUNBOOK.md` |
| 6 Draft code | `ops/patches/f4_audit_fail_closed.patch`, `ops/patches/f5_f6_audit_immutability.patch` (not applied; results in `ops/patches/README.md`). New finding F-11 (unredacted first `token=` in the assisted audit) |

### Tests in this pass (throwaway SQLite; no `backend/.env`; mail disabled)

| Run | Tree | Started (UTC) | Result | Log SHA-256 |
|---|---|---|---|---|
| Focused HK + SG | `nikhil` `b5b63b3` (after cherry-picks) | 03:09:14Z | 1291 passed, 0 failed, 1 skipped | `3f88995d…` |
| Full suite | `nikhil` `b5b63b3` | 03:46:42Z | **5212 passed, 0 failed, 7 skipped, 2 xfailed** | `4935f74d…` |
| Full suite | `b5b63b3` + everything committed in this pass | 04:08:01Z | **5231 passed, 0 failed, 7 skipped, 2 xfailed** | `f96a5ca0…` |
| Commit a alone (import + focused + every changed test file) | `b5b63b3` + commit a | 05:33:34Z | 1792 passed, 0 failed, 1 skipped | `3e215a8d…` |
| Commit a + b (same selection) | `b5b63b3` + a + b | 05:42:31Z | 1795 passed, 0 failed, 1 skipped | `046c6993…` |
| F-4 patch, full suite | as row 3 + `f4_audit_fail_closed.patch` | 04:58:24Z | 5235 passed, 0 failed | `9c15e358…` |
| F-5/F-6 patch, full suite | as row 3 + `f5_f6_audit_immutability.patch` | 05:15:22Z | 5239 passed, 0 failed | `615cc37d…` |

Commits on local `nikhil` (not pushed): a `a0be05f` test/config: fail-closed outbound delivery in test and local (F-10); b `6131fbb` hk: production row-count check in read-only verification script; c is the commit containing this file (docs/ops).

**Correction to section 2 below.** It said the second **and** third passes sent real email. Only one send is confirmed (2026-10-13 11:59:52 UTC, third pass). The second-pass break-glass runs (06:51–06:52 UTC) are **unknown**: their log was overwritten. See `ops/INCIDENT_F10_test_emails.md`.

**Production schema copy.** The schema-only copy used for every rehearsal (`prod_schema.sql`) came from a read-only `pg_dump` that Claude itself ran against production on 2026-10-13. From now on, production is read only through scripts a human runs.

---

# Previous pass (2026-10-13, third pass)


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
