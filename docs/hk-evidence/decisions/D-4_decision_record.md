# D-4 — Encryption at rest (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-4` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Encryption at rest

## Options

A verified provider encryption / B app-level (platform-wide) / C = A + CMEK

## Engineering recommendation (not a decision)

verify F1–F7, then A or C; B on the platform roadmap

Adviser named in the register: Security, counsel. Register blocker reference: B-07.

## Consequences (from the code as of 2026-10-13)

* The application does not encrypt columns or files itself. Encryption at rest therefore depends on the database / storage provider configuration, which must be verified (see the existing docs/HONG_KONG_RELEASE_EVIDENCE/G5/ENCRYPTION_AT_REST_ASSESSMENT.md). Option B (app-level) is platform-wide work.
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-4` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-4`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
