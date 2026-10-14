# Sign-off packet 02: QA lead (gate G4, edge cases)

> **Status:** prepared by engineering on 2026-10-14. It contains no decision, value, result or signature made on anyone's behalf. Every evidence link gives the file's SHA-256 when this packet was generated: if the file you open has a different digest, stop and ask engineering.

## What you need to do

1. Read the G4 report. It maps each of the 10 wireframe §16 edge-case rows (R1–R10) to the tests that cover it **end to end** (timesheet or input → committed payroll run → payslip / entitlement / filing).
2. Re-run the command at the top of `G4_test_run_output.txt` on a clean checkout of `nikhil` against a throwaway database, and confirm you get the same result: **50 passed, 0 failed**.
3. Optionally re-run the full backend suite (`python -m pytest tests/ -q`). The latest engineering run is recorded in `../STATUS.md`.
4. Sign. The signed report is uploaded under `HK-GATE-G4`.

## What to check

* Every R-row has at least one end-to-end test, not just a unit test.
* No test is skipped or marked xfail in the G4 run.
* The golden vectors are unchanged. The tests compare against them, so they must not have been edited to pass.
* The two open items are accepted: the contribution-day deferral rule and the general-holiday lists are still G1-unverified (packet 01). Their tests prove the mechanism, not the statutory rule.

## Time estimate

About half a day: 1–2 hours to read, under 10 minutes to re-run, and the remainder to spot-check tests.

## Evidence

* `../G4/G4_edge_case_test_report.md` — SHA-256 `7695dfc5beca5c4dfef937ca332e654834f70622b8864bade149e260af1c9fec`
* `../G4/G4_test_run_output.txt` — SHA-256 `e68061ff2d8ee08978c2761c08f29a980861d51d20ab3a285e9329c4327b9f98`
* `../STATUS.md` — SHA-256 `4a41111be5c7a576f91533160122156558884f41d221185094ffb4ead4fba574`

## Sign-off

| Name | Role | Date | Decision / conditions | Signature |
|---|---|---|---|---|
| | | | | |
