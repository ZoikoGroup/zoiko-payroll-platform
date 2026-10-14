# Sign-off packet 06: Product owner (decisions D-1 to D-14, and the owner pack)

> **Status:** prepared by engineering on 2026-10-14. It contains no decision, value, result or signature made on anyone's behalf. Every evidence link gives the file's SHA-256 when this packet was generated: if the file you open has a different digest, stop and ask engineering.

## What you need to do

1. Decide D-1 to D-14. Each has a draft record in `../decisions/` with options and consequences. Write your choice, reason and date in each record and sign it. A record is uploaded under `HK-DECISION-D-n`, and a second Super Admin accepts it.
2. **D-1 to D-11 block launch.** The product will not make the HK service available until each is recorded and accepted. D-12 to D-14 concern the shared platform and do not block HK.
3. Some decisions need advice first: D-2, D-3 and D-9 from counsel (packet 04); D-4, D-5 and D-10 from Security (packet 03).
4. Two further owner decisions:
   * **Owner pack (commit 8).** Read `../ops/OWNER_PACK_CSV_REVIEW.md` and choose how to baseline the configuration CSV (§6 there). The pack is not committed until you decide.
   * **Optional G1 exception.** `../decisions/D-G1-internal-review-in-lieu-of-specialist.md` (engineering does not recommend it).

| # | Question | Options | Engineering recommendation (not a decision) | Blocks launch | Your choice | Date |
|---|---|---|---|---|---|---|
| D-1 | eMPF interface at launch | manual portal / bulk file / API | manual portal at launch; file upload once the builder exists | **yes** | | |
| D-2 | Retention period per data category | per counsel (packet 04) | none: engineering must not invent periods | **yes** | | |
| D-3 | Deletion vs anonymisation at end of retention | new shared subsystem / manual | decide after D-2 | **yes** | | |
| D-4 | Encryption at rest | A provider / B application-level / C A + CMEK | verify provider settings, then A or C (packet 03) | **yes** | | |
| D-5 | Production HK identity-token secret | separate secret / derived key | provision a separate secret before launch | **yes** | | |
| D-6 | Bilingual (Chinese) employee output at launch | yes / no / later | see `HK-BILINGUAL-REQUIREMENT-DECISION.md` (owner pack) | **yes** | | |
| D-7 | Launch-scope exclusions (domestic helpers, Industry Scheme, contractors, voluntary MPF, pre-1-May-2025 terminations) | accept / extend | accept for launch; all are refused fail-closed | **yes** | | |
| D-8 | HK payroll-run approval four-eyes | keep platform single approval / HK-gated four-eyes | HK-gated four-eyes (small, HK-only) | **yes** | | |
| D-9 | Legal-hold policy | per counsel (packet 04) | the technical four-eyes release is already enforced | **yes** | | |
| D-10 | Who may grant privileged access; session length | per Security (packet 03) | the existing time-boxed consent / break-glass module | **yes** | | |
| D-11 | Who publishes each year's IRD / MPF / termination templates, and by when | Super Admin team with the HK specialist / external provider | name an accountable owner; publish before the first filing date | **yes** | | |
| D-12 | Per-value reviewer columns (shared platform) | keep pack-level four-eyes / add per-row columns | keep pack-level four-eyes; revisit platform-wide | no | | |
| D-13 | Platform-wide template compare | HK-only (built) / platform-wide | platform-wide later | no | | |
| D-14 | Audit correlation id (shared platform) | as-is / extend platform-wide | extend platform-wide in a dedicated change | no | | |

## What to check

Each record's "Consequences" section says what the product does until the decision is recorded. In most cases it refuses the action, fail-closed.

## Time estimate

About half a day for the decisions that need no advice; the rest once packets 03 and 04 are signed.

## Evidence

* `../decisions/D-1_decision_record.md` — SHA-256 `e169546be5b08816cad298ac90daefab503228653398b03e45c07d20ceff29f8`
* `../decisions/D-2_decision_record.md` — SHA-256 `823446ef96f0f0fd0a3a30fd33ab7a07bb035de2c2b839bb9d842771bd7742aa`
* `../decisions/D-3_decision_record.md` — SHA-256 `82c84428025a3bac01205c38cc9ed3b0f1cbd86b92c4bfe5e4885882e4e74b1a`
* `../decisions/D-4_decision_record.md` — SHA-256 `6b55f9d65ffa9458d5443ae174b95a552a980687b7ee00259386f0a23410cd2e`
* `../decisions/D-5_decision_record.md` — SHA-256 `6a0393d985dbc33a10c70ef01d3292eb53da4a32b294da0b01b12d1e0f0623ce`
* `../decisions/D-6_decision_record.md` — SHA-256 `45b2aed9aa855e97c0fc4a75ce1e592f1affb7d2618b05704e5b976d0f3d2995`
* `../decisions/D-7_decision_record.md` — SHA-256 `674c70c879bfedba0956cb368100efafad648d515738ca8b2a77fcec0d3de5e3`
* `../decisions/D-8_decision_record.md` — SHA-256 `0edaab157c6e738f7ace1e7b3f1e3eefe3acd05b9f21f58f5c793c2a519e4200`
* `../decisions/D-9_decision_record.md` — SHA-256 `59a4e3d77647166a168c46c3a20293e9dbdd3bf8aabea09c2cfec4cb37d2742b`
* `../decisions/D-10_decision_record.md` — SHA-256 `8796e34c6714e68d15ffa91367ec52c6a949a14f00aed822160c143b94b3ac3b`
* `../decisions/D-11_decision_record.md` — SHA-256 `34cb6a8ad7b23347254ad5c8db1558a499cff505e80ef42c4c6a4fa77d37c72f`
* `../decisions/D-12_decision_record.md` — SHA-256 `4df011167688431a511ae3eeebe75c02a97363b43ddd0bd0921d13884b1060fa`
* `../decisions/D-13_decision_record.md` — SHA-256 `0ea94b6a37420f0804e0b20ed41f649949968157ae60329924cc47d0bdc34c13`
* `../decisions/D-14_decision_record.md` — SHA-256 `da09b9c97e4ec6f90330251d75a5d7957415e1790a3b2f8b935804d03fa9b6fa`
* `../decisions/D-G1-internal-review-in-lieu-of-specialist.md` — SHA-256 `5b1c0b111a327b4318d41e6db422627310a37013221989627cbc10b2595459c8`
* `../ops/OWNER_PACK_CSV_REVIEW.md` — SHA-256 `5d773d4f7113a259c45ce5ed7868a01c8058b515721dcaed9c2eeeb380a5d23c`
* `../ops/owner_pack_proposal/MANIFEST.sha256` — SHA-256 `9fc0122176c4673ba165f6460162ea2a3632adfcaea9d8377038f372f11dc0ff`

## Sign-off (for this packet as a whole; each D-n record is signed separately)

| Name | Role | Date | Decision / conditions | Signature |
|---|---|---|---|---|
| | | | | |
