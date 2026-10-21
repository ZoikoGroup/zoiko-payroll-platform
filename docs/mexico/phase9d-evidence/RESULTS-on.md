# Mexico Phase 9d -- browser check (mode ON)

7/7 PASS

| Check | Result |
|---|---|
| on-1 a PTU cycle is recorded in the Compliance Centre (DRAFT) | PASS |
| on-2 the recorder cannot approve the amount (four-eyes) | PASS |
| on-3 a second person approves the amount; the pay-by date is unsourced | PASS |
| on-4 operator exclusions are blocked: the catalog is not transcribed (S26) | PASS |
| on-5 allocation is blocked with the named code (PTU rule not transcribed, S26) | PASS |
| on-z1 NL compliance page unchanged | PASS |
| on-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico/ptu/cycles/1/allocate 400, POST /api/payroll/mexico/ptu/cycles/1/approve-amount 400
Console errors: 2
