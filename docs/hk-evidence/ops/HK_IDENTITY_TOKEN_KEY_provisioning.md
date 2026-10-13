# Ops instruction: provision HK_IDENTITY_TOKEN_KEY in production (owner decision D-5)

**For:** the person who manages production secrets. **Do this before** Hong Kong is activated. No real value appears in this document, in git or in `.env.example`.

## Why

HKID and passport identity tokens are HMAC-SHA256, keyed by `HK_IDENTITY_TOKEN_KEY` (`hong_kong_service.py:150-174`). When the variable is blank, the key is derived from `PAYROLL_SECRET_KEY`. Activation readiness then shows `IDENTITY_TOKEN_KEY` as unmet. It is also unmet if the value equals `PAYROLL_SECRET_KEY`, which is checked with a constant-time comparison.

## Steps

1. On a trusted machine, or in the secret manager's own generator, create 32 random bytes:
   `python -c "import secrets; print(secrets.token_hex(32))"`
   Do not paste the output into chat, tickets, logs or files.
2. Store it in the production secret store as `HK_IDENTITY_TOKEN_KEY`, the same mechanism that supplies `PAYROLL_SECRET_KEY` to the backend service.
3. Restart or redeploy the backend so it reads the new environment.
4. If any HK employee rows already exist (production had 0 HK workflow rows on 2026-10-13), run `python -m scripts.rehash_hk_identity_tokens` on the production host after the restart. Runbook #29 covers secret rotation.
5. Verify without exposing the value: `python -m scripts.validate_environment --env production` prints names and status only. Then, in Super Admin → Hong Kong → Activation & Governance, the row "HK_IDENTITY_TOKEN_KEY configured as a dedicated secret (D-5)" should show met.
6. Record what was done (date, who, verification output; no value) in the D-5 decision record and in the production-verification evidence.

## Never

* Reuse `PAYROLL_SECRET_KEY`, or any other existing secret.
* Commit the value, or put it in `.env.example`. `.env.example` only documents the name and the generation command.

Performed by — Name / Role / Date / Signature: ________
Verified by (a different person) — Name / Role / Date / Signature: ________
