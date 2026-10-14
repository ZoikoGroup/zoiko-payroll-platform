# D-2 — Retention period per data category (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-2` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Retention period per data category

## Options

per counsel

## Engineering recommendation (not a decision)

none proposed: engineering must not invent periods

Adviser named in the register: privacy counsel. Register blocker reference: B-06, G5.

## Consequences (from the code as of 2026-10-13)

* Retention policies for HK data categories cannot be approved until D-2 is recorded (retention_service; test_retention_is_blocked_until_the_owner_decides_and_then_four_eyes). Purge stays blocked.
* Engineering has proposed no periods and must not: the periods come from privacy counsel.
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-2` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-2`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
