# D-8 — HK payroll-run approval four-eyes (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-8` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

HK payroll-run approval four-eyes

## Options

keep platform single approval / HK-gated four-eyes

## Engineering recommendation (not a decision)

HK-gated four-eyes (small, HK-only)

Adviser named in the register: Ops. Register blocker reference: B-14.

## Consequences (from the code as of 2026-10-13)

* Today a normal HK payroll run is approved by one operator; the HK hook only refuses approval while the HK preflight has BLOCK findings (hong_kong_service._hk_before_run_transition). Correction runs already need a different approver. Choosing HK-gated four-eyes on normal runs is a small HK-only engineering change.
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-8` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-8`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
