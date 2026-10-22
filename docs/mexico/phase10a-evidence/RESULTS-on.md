# Mexico Phase 10a -- browser check (mode ON)

9/9 PASS

| Check | Result |
|---|---|
| on-1 a batch is built from the committed run: 2 payments, CLABE last 4 only | PASS |
| on-2 the maker cannot release it (four-eyes) | PASS |
| on-3 a second person releases it | PASS |
| on-4 the worklist downloads, labelled NOT A BANK FILE, with the full CLABE (never shown on screen) | PASS |
| on-5 outcomes recorded with references; the batch CLOSES when none is pending | PASS |
| on-6 the returned payment is re-issued in a new DRAFT batch, linked | PASS |
| on-7 a released batch refuses the run's reset (Phase 6 rule) | PASS |
| on-z1 NL compliance page unchanged | PASS |
| on-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico/payments/batches/1/release 400
Console errors: 1
