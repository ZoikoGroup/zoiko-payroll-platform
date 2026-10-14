# Sign-off packet 08: G7 launch approval (six signers)

> **Status:** prepared by engineering on 2026-10-14. It contains no decision, value, result or signature made on anyone's behalf. Every evidence link gives the file's SHA-256 when this packet was generated: if the file you open has a different digest, stop and ask engineering.

## Do not use this packet until

All of the following are **ACCEPTED** in the product (Super Admin → Jurisdictions → Hong Kong → Statutory Summary & Gates, and Activation & Governance → Owner decisions), each by a Super Admin other than its uploader:

* [ ] G1 statutory content (packet 01)
* [ ] G2 authority conformance (packet 07 results)
* [ ] G3 parallel payroll (packet 07 results)
* [ ] G4 edge cases (packet 02)
* [ ] G5 security / privacy (packets 03 and 04)
* [ ] G6 operations (packet 05)
* [ ] D-1 to D-11 recorded (packet 06)
* [ ] `HK-PRODUCTION-VERIFICATION` uploaded (read-only verification after deploy)

If any box is unticked, stop. The product will also refuse activation.

## What you need to do

Each of the six roles reads the G7 sheet, checks the gate states in the product, and signs the sheet: Product owner, Engineering lead, QA lead, Payroll Operations lead, Security / Privacy lead, and Local statutory reviewer (Hong Kong). The signed sheet is uploaded under `HK-GATE-G7` and reviewed by a different Super Admin.

## What to check

* The digest of each accepted evidence item in the product matches its signed file.
* No gate was accepted on a draft whose sign-off block is blank.

## Time estimate

About 30 minutes per signer once G1–G6 are accepted.

## Evidence

* `../G7/G7_launch_approval_sheet.md` — SHA-256 `5af7cfc104754497aefc208b2fe8c88dba050602d8955c7bce00b168ca78fd3f`
* `../STATUS.md` — SHA-256 `4a41111be5c7a576f91533160122156558884f41d221185094ffb4ead4fba574`
* `../BLOCKERS.md` — SHA-256 `b405eeb6339be0d543da44c48a3e3b5788d32c137a6589dca1ceb6e69a0d2675`

## Sign-off

Sign on the G7 sheet itself, not here.
