# D-10 — Privileged (assisted) access policy (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-10` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Who may grant privileged (assisted) access to HK tenants; session length

## Options

per Security

## Engineering recommendation (not a decision)

existing time-boxed module; HK reads already logged

Adviser named in the register: Security. Register blocker reference: G5.

## Consequences (from the code as of 2026-10-13)

* Implemented 2026-10-13 (G5 F-3 / F-7 closed): CONSENT by default — an org admin of the tenant approves a Super Admin's request before any token exists; BREAK_GLASS — a different Super Admin approves, the session is capped (ASSISTED_ACCESS_BREAK_GLASS_MINUTES, default 60) and the tenant's admins are notified at once (delivery confirmed; a failed notice is audited and raises a high-severity Super Admin alert); every step and refusal is audited (tests/test_assisted_access.py). HK reads in a session are in the HK access log. Still owner policy: which Super Admins may request / approve break-glass, what counts as an emergency, and the session / approval-window lengths (settings ASSISTED_ACCESS_SESSION_MINUTES = 30, ASSISTED_ACCESS_APPROVAL_WINDOW_MINUTES = 60, ASSISTED_ACCESS_BREAK_GLASS_MINUTES = 60).
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-10` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-10`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
