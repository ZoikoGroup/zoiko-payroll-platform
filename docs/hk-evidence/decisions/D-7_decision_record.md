# D-7 — Launch-scope exclusions (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-7` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Launch-scope exclusions (domestic helpers, Industry Scheme, contractors, voluntary MPF, pre-1-May-2025 terminations)

## Options

accept / extend

## Engineering recommendation (not a decision)

accept for launch; all are blocked fail-closed

Adviser named in the register: HK specialist. Register blocker reference: B-15.

## Consequences (from the code as of 2026-10-13)

* Out-of-scope populations (domestic helpers, Industry Scheme casual employees, contractors, voluntary MPF, pre-1-May-2025 terminations per the register) are refused fail-closed by the engine rather than calculated. Extending scope means new statutory content (G1) and tests before activation.
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-7` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-7`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
