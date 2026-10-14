# D-1 — eMPF submission interface at launch (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-1` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

eMPF interface at launch (E1)

## Options

manual portal / bulk file / API

## Engineering recommendation (not a decision)

manual portal at launch (works today); file upload once E6 exists

Adviser named in the register: Ops. Register blocker reference: B-03, G2.

## Consequences (from the code as of 2026-10-13)

* The eMPF configuration method is one of EMPF_PORTAL_MANUAL / EMPF_FILE_UPLOAD / EMPF_API (hong_kong_service.EMPF_METHODS). With EMPF_PORTAL_MANUAL the readiness centre marks eMPF interface certification NOT_APPLICABLE; any other method stays BLOCKED until a reviewed HK-EMPF-CERTIFICATION exists.
* Choosing file upload or API adds engineering work: no eMPF file layout or API client exists (G2).
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-1` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-1`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
