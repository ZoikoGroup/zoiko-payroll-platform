# Sign-off packet 03: Security / Privacy lead (gate G5)

> **Status:** prepared by engineering on 2026-10-14. It contains no decision, value, result or signature made on anyone's behalf. Every evidence link gives the file's SHA-256 when this packet was generated: if the file you open has a different digest, stop and ask engineering.

## What you need to do

Choose an option for each finding below (or write your own), then sign. Engineering implements the choices. F-4 and F-5 / F-6 already have draft code saved as patch files for your review, **not applied**: `../ops/patches/`.

| Finding | Problem in one line | Options | Engineering recommendation | Your choice |
|---|---|---|---|---|
| **F-2 / D-4** | HKID, passport and MPF account numbers are stored unencrypted by the application. Masking and access logs are in place | A: verify and rely on the provider's encryption at rest · B: application-level encryption (platform-wide) · C: A plus customer-managed keys | Verify the provider settings, then A or C; B on the platform roadmap | |
| **F-4** | An assisted-access action is audited "best effort": if the audit write fails, the action still runs | A: write an intent record before the action and refuse if it fails · B: middleware fail-closed (needs `main.py`) · C: keep best-effort plus an alert | A, plus C's alert for failed completion rows | |
| **F-5** | No login / authentication audit trail | A: new append-only `auth_audit_events` table · B: logs only · C: reuse the configuration audit table | A | |
| **F-6** | Audit rows can be changed by anyone with database write access | A: a database trigger rejects UPDATE / DELETE, with purges only through a retention function · B: revoke grants · C: hash chain | A now, C later | |
| **F-10** | Local test runs sent real email through the company SMTP account (one confirmed notice to `hkadmin@zoikotest.dev`) | Engineering fixed: test and local modes never deliver. **Open:** pull the mail sent log, check who owns `zoikotest.dev`, decide on notification, remove real credentials from local `.env` files and rotate the password | Follow the checklist in the incident note §6 | |
| **F-11** | The assisted-access audit can store a first `token=` query parameter unredacted | apply the one-line fix (in the F-4 patch) on its own or with F-4 | apply now | |
| **D-5** | Production `HK_IDENTITY_TOKEN_KEY` | provision a separate secret / keep the derived key | Provision a separate secret before launch | |
| **D-10** | Who may grant privileged (assisted) access, and for how long | per Security | Keep the time-boxed module: tenant consent, plus second-Super-Admin break-glass with tenant notice | |

## What to check

* Section 1 of the G5 assessment: the privileged-access tests were actually run (41 passed). The output file is linked below.
* The design notes say which files change. Neither F-4 option A nor F-5 / F-6 option A needs `backend/app/main.py`.
* F-10: the guard (`backend/app/core/outbound.py`) and its tests (`backend/tests/test_outbound_delivery_guard.py`).

## Time estimate

About 2–3 hours to read and decide. F-10 needs the mail administrator for about 1 hour.

## Evidence

* `../G5/G5_security_privacy_assessment.md` — SHA-256 `9b770fc855d5827002647ba0332ce62d14300d3ad8d675fb82b1c62db8453d05`
* `../G5/G5_privileged_access_test_run_output.txt` — SHA-256 `9d490ef04f42d43d7e0d31328d3f77e62b35bcdfde9683d6e024d13d4d1ee388`
* `../ops/DESIGN_F4_privileged_access_audit_fail_closed.md` — SHA-256 `404cc0820440015bf6a5f034e9168e75d334d38733627460a07d3676622e2cf1`
* `../ops/DESIGN_F5_F6_login_audit_and_immutable_audit_rows.md` — SHA-256 `519f09f630e74415cf6ee9fb3d23e85f6d6232f8174dc8facfc264d37e78582e`
* `../ops/INCIDENT_F10_test_emails.md` — SHA-256 `3c4c1f1a3ec0b141a12ccffd6f7bf21d72592ba38df78398b7c5956a294dec31`
* `../decisions/D-4_decision_record.md` — SHA-256 `6b55f9d65ffa9458d5443ae174b95a552a980687b7ee00259386f0a23410cd2e`
* `../decisions/D-5_decision_record.md` — SHA-256 `6a0393d985dbc33a10c70ef01d3292eb53da4a32b294da0b01b12d1e0f0623ce`
* `../decisions/D-10_decision_record.md` — SHA-256 `8796e34c6714e68d15ffa91367ec52c6a949a14f00aed822160c143b94b3ac3b`
* `../ops/HK_IDENTITY_TOKEN_KEY_provisioning.md` — SHA-256 `674f5a51e89bfb7aeae8f6ef30e4cfe2a18f660257ab256969f26b06af7be742`

## Sign-off

G5 can be accepted when F-2 / D-4, F-4, F-5, F-6, F-10 and F-11 each have a recorded decision (and any fix is verified), and counsel has signed packet 04.

| Name | Role | Date | Decision / conditions | Signature |
|---|---|---|---|---|
| | | | | |
