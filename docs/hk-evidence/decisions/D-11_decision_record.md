# D-11 — Future-year template publication owner (DRAFT decision record)

**Status:** DRAFT — Zoiko internal, prepared for the owner. **No decision has been taken.** Internally reviewed – pending approval.
**Evidence tag:** `HK-DECISION-D-11` · **Blocks launch:** Yes (from `hong_kong_service.DECISIONS`)
**Source of options / recommendation:** `docs/HONG_KONG_RELEASE_EVIDENCE/HK_OWNER_DECISION_REGISTER.md` (SHA-256 `aa97e6a6cebf7b24df1db4e7905580da061ef59850384748acc8e7d687b103fc`), quoted, not re-decided.

## Question

Future-year report template publication: who publishes each year's IRD (YA) and MPF / termination (calendar-year) template, and by when

## Options

Super Admin team with the HK specialist / external provider

## Engineering recommendation (not a decision)

name an accountable Super Admin owner; publish before the first filing / issue date per `HK_REPORT_TEMPLATE_COMPLETENESS_MATRIX.md` §4 (no fallback exists by design)

Adviser named in the register: HK specialist. Register blocker reference: B-16.

## Consequences (from the code as of 2026-10-13)

* Report templates are year-specific with no fallback by design: a missing year's IR56 / MPF template blocks that year's report. Someone accountable must publish each new year's template before its first filing or issue date.
* Until it is RECORDED (decision document uploaded under the tag and accepted by a second Super Admin), `activation_readiness` lists `DECISION_D-11` as unmet and the Hong Kong service registry cannot be made AVAILABLE (hong_kong_service.py, readiness requirements; readiness-center row "Owner decisions").

## Decision (to be completed by the owner — leave blank until decided)

Selected option: ________
Reason: ________
Effective from: ________

Decision owner — Name / Role / Date / Signature: ________
Adviser consulted — Name / Role / Date / Signature: ________

After signing: upload this record (signed) under `HK-DECISION-D-11`; a Super Admin other than the uploader accepts or rejects it in Activation & Governance.
