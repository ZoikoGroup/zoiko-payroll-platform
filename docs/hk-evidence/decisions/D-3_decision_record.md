# D-3 — Deletion vs anonymisation at end of retention (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-3` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Deletion vs anonymisation at end of retention, and who runs it

## Options

a new shared subsystem / manual

## Engineering recommendation (not a decision)

decide after D-2

Adviser named in the register: counsel. Register blocker reference: B-06.

## Consequences (from the code as of 2026-10-13)

* No automated deletion / anonymisation job exists. Retained HK statutory records block a hard delete (test_retained_hk_statutory_records_block_a_hard_delete). Choosing automated deletion or anonymisation is new shared-platform engineering.
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-3` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-3`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
