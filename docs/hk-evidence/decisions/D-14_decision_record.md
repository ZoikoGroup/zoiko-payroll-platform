# D-14 — Audit correlation id (shared platform) (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-14` · **Blocks launch:** No (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Request correlation id + tenant id on configuration audit rows (shared audit schema)

## Options

as-is / extend platform-wide

## Engineering recommendation (not a decision)

extend platform-wide in a dedicated change

Adviser named in the register: Security. Register blocker reference: —.

## Consequences (from the code as of 2026-10-13)

* Not a launch blocker. Configuration audit rows carry actor, entity and values but no request correlation id or tenant id; adding them is a shared audit-schema change. (Note: code comments that say "D-14" next to payroll corrections refer to the separate correction design in docs/HONG_KONG_RELEASE_EVIDENCE/D14, not to this owner decision.)

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-14`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
