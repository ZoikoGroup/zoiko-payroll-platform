# Sign-off packet 04: Legal / privacy counsel (retention, deletion, legal hold)

> **Status:** prepared by engineering on 2026-10-14. It contains no decision, value, result or signature made on anyone's behalf. Every evidence link gives the file's SHA-256 when this packet was generated: if the file you open has a different digest, stop and ask engineering.

## What you need to do

1. **D-2, retention periods.** For each Hong Kong data category in the retention draft (section 2), state the retention period and the legal basis (for example the Employment Ordinance, the Inland Revenue Ordinance, the MPF Schemes Ordinance, or PDPO DPP2). Engineering has deliberately proposed **no** periods.
2. **D-3, end of retention.** Choose deletion or anonymisation, and who runs it (a new shared subsystem, or a manual procedure).
3. **D-9, legal hold.** State who may place and release a hold, and how often holds are reviewed. Release by a different person is already enforced and audited.
4. **F-10 input.** Advise the Security lead whether the test emails (packet 03, incident note §6c) require any notification.
5. Sign. The signed records are uploaded under `HK-DECISION-D-2`, `D-3` and `D-9`.

## What to check

* While D-2 is unrecorded, the product refuses to approve retention policies, and purge stays blocked. Retained statutory records block hard deletes.
* The PDPO principles table in the G5 assessment, section 7.

## Time estimate

About half a day to 1 day, depending on how many categories need research.

## Evidence

* `../G5/G5_retention_deletion_policy_draft.md` — SHA-256 `09721353352d047a857f6e77f6dd07e7361b0dbcb7459b6fa79e050b7cc64857`
* `../G5/G5_security_privacy_assessment.md` — SHA-256 `9b770fc855d5827002647ba0332ce62d14300d3ad8d675fb82b1c62db8453d05`
* `../decisions/D-2_decision_record.md` — SHA-256 `823446ef96f0f0fd0a3a30fd33ab7a07bb035de2c2b839bb9d842771bd7742aa`
* `../decisions/D-3_decision_record.md` — SHA-256 `82c84428025a3bac01205c38cc9ed3b0f1cbd86b92c4bfe5e4885882e4e74b1a`
* `../decisions/D-9_decision_record.md` — SHA-256 `59a4e3d77647166a168c46c3a20293e9dbdd3bf8aabea09c2cfec4cb37d2742b`
* `../ops/INCIDENT_F10_test_emails.md` — SHA-256 `3c4c1f1a3ec0b141a12ccffd6f7bf21d72592ba38df78398b7c5956a294dec31`

## Sign-off

| Name | Role | Date | Decision / conditions | Signature |
|---|---|---|---|---|
| | | | | |
