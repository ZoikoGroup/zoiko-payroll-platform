# D-5 — Production HK identity-token secret (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-5` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Production `HK_IDENTITY_TOKEN_KEY`

## Options

provision a separate secret / keep the derived key

## Engineering recommendation (not a decision)

provision a separate secret before launch

Adviser named in the register: Security. Register blocker reference: B-08.

## Consequences (from the code as of 2026-10-13)

* Readiness requirement IDENTITY_TOKEN_KEY is unmet while HK_IDENTITY_TOKEN_KEY is blank or equals PAYROLL_SECRET_KEY (constant-time comparison). Provisioning is an ops action — see ../ops/HK_IDENTITY_TOKEN_KEY_provisioning.md. Changing the key later needs `python -m scripts.rehash_hk_identity_tokens`.
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-5` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-5`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
