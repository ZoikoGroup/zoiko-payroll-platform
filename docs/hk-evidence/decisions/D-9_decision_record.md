# D-9 — Legal-hold policy (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-9` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Legal-hold policy (who may place / release; review cadence)

## Options

per counsel

## Engineering recommendation (not a decision)

the technical four-eyes release already enforced

Adviser named in the register: counsel. Register blocker reference: B-06.

## Consequences (from the code as of 2026-10-13)

* Placing and releasing legal holds is implemented; release requires a different user and is audited (retention_service.release_legal_hold, four-eyes with a refusal audit row). The policy of who may place / release and the review cadence is not encoded and must be set by the owner.
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-9` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-9`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
