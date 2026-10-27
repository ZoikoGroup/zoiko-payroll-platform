# Mexico final mile — progress

Master prompt: `docs/mexico/MEXICO_FINAL_MILE_MASTER_PROMPT.md`. One section per step; the final report is `MEXICO_FINAL_MILE_REPORT.md`.

---

## §0 / §1 — Session zero (2026-10-27)

**Nothing was changed in production or in the code.**

### Git state

| Item | State |
|---|---|
| Branch | `nikhil` |
| Local HEAD | `cd98323`: the PRODUCTION_STATE record of PRs #134–#136, docs only |
| `origin/main` | `7075623` (PR #136: A17 + A18) |
| `cd98323` | **Local only, not pushed.** First in the hand-off: push when convenient, docs only |
| Uncommitted | Only your own files (`backend/app/main.py`, `backend/.env.example`, `frontend/vite.config.js`, three `docs/SINGAPORE_*`), plus untracked HK / SG docs and source binaries. None staged |

### Latest deploy runs (public GitHub Actions API)

| Run | Commit | Result |
|---|---|---|
| 40472214932 Deploy Backend | `7075623` (PR #136, migration `c7d2e9a4f1b6`) | success: test, single-head check, SSH deploy with head verification, drift check; the privacy smoke was skipped |
| 40458986909 Deploy Backend / 40458986971 Build Frontend | `262cc1f` (PR #135) | success / success |

PR #136 changed no frontend file, so no frontend build ran for it. The frontend served in production should be the PR #135 build; the live-app check below confirms what the server actually serves.

### Production head — WAITING FOR YOU

Run on the production server and paste the output:

```
cd /var/www/zoiko-payroll/backend/backend && source venv/bin/activate && alembic current
```

Expected: `c7d2e9a4f1b6 (head)`. If it differs, the programme stops (stop condition 1).

### Live app check (read-only) — WAITING FOR YOU

This needs a Super Admin session on https://app.zoikopayroll.com. I have no credentials and must not record any. The proposed way: a headed Chrome window opened by the harness, where you sign in yourself. I then only navigate and take screenshots:
- `/super-admin/compliance/mexico`, every tab;
- the readiness view (all eight gates OPEN);
- no Mexican pack, release or registry entry Active;
- an org-route refusal (`MX_DORMANT`).

No write of any kind; the session is never saved; no real employee screen is opened.

### The skipped post-deploy privacy smoke (HP-10)

`backend-deploy.yml` runs "Post-deploy privacy smoke" only when `HAS_SMOKE` is true, which it is when the secret `ZP_SMOKE_BASE_URL` is non-empty. That is why run 40472214932 skipped it. The step (`backend/scripts/post_deploy_privacy_smoke.py`) needs these GitHub Actions repository secrets:

| Secret | Required | What it holds |
|---|---|---|
| `ZP_SMOKE_BASE_URL` | yes (switches the step on) | The API base URL the smoke calls |
| `ZP_SMOKE_IDENTITIES` | yes | JSON list of **synthetic** platform identities: `[{"role": "super_admin", "email": …, "password": …, "totp_secret": …}, …]`. These are platform roles that must never see worker data; the script logs in with TOTP (`pyotp`) |
| `ZP_SMOKE_EMPLOYEE_ID` | yes | An employee id in a **synthetic** smoke tenant, which those identities must be refused |
| `ZP_SMOKE_ALERT_WEBHOOK` | optional | Receives a JSON summary on failure |
| `ZP_SMOKE_RUN_ID` | set by the workflow | — |

**Who can configure them:** a ZoikoGroup repository admin (Actions secrets need admin rights on `zoiko-payroll-platform`). The synthetic tenant and identities must exist in production first, which is a decision for the release owner and the ZP-PRIV owner. Not configured here (rule: no secrets).
