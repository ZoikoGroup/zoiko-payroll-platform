# Mexico Phase 10a -- browser check (mode OFF)

7/7 PASS

| Check | Result |
|---|---|
| off-1 GET /payments/batches refused while Mexico is dormant | PASS |
| off-1 POST /runs/1/payment-batch refused while Mexico is dormant | PASS |
| off-1 POST /payments/batches/1/release refused while Mexico is dormant | PASS |
| off-1 POST /payments/batches/1/worklist refused while Mexico is dormant | PASS |
| off-2 the payments panel shows the dormancy refusal | PASS |
| off-3 NL compliance page has no Mexico panels | PASS |
| off-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: GET /api/payroll/mexico/annual-adjustments 403, GET /api/payroll/mexico/annual-adjustments/exclusion-reasons 403, GET /api/payroll/mexico/collective-agreements 403, GET /api/payroll/mexico/employers 403, GET /api/payroll/mexico/payments/batches 403, GET /api/payroll/mexico/ptu/cycles 403, GET /api/payroll/mexico/ptu/exclusion-reasons 403, GET /api/payroll/mexico/readiness?on=2026-10-21 403
Console errors: 10
