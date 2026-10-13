# D-12 — Per-value reviewer columns (shared platform) (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-12` · **Blocks launch:** No (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Per-value entered_by / reviewed_by / approved_by columns on every statutory configuration row (shared schema, every country)

## Options

keep pack-level four-eyes / add per-row columns platform-wide

## Engineering recommendation (not a decision)

keep pack-level four-eyes (edits already invalidate approval); revisit platform-wide

Adviser named in the register: Engineering + Security. Register blocker reference: — (no HK blocker).

## Consequences (from the code as of 2026-10-13)

* Not a launch blocker. Configuration rows keep pack-level four-eyes (any edit clears the pack's approval). Per-row reviewer columns would be a shared-schema change for every country.

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-12`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
