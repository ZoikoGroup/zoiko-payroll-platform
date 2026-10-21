# Mexico Phase 9e -- browser check (mode OFF)

7/7 PASS

| Check | Result |
|---|---|
| off-1 GET /annual-adjustments refused while Mexico is dormant | PASS |
| off-1 POST /annual-adjustments/compute refused while Mexico is dormant | PASS |
| off-1 POST /annual-adjustments/apply refused while Mexico is dormant | PASS |
| off-1 GET /annual-adjustments/exclusion-reasons refused while Mexico is dormant | PASS |
| off-2 the annual-adjustment panel shows the dormancy refusal | PASS |
| off-3 NL compliance page has no Mexico panels | PASS |
| off-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: GET /api/payroll/mexico/annual-adjustments 403, GET /api/payroll/mexico/annual-adjustments/exclusion-reasons 403, GET /api/payroll/mexico/collective-agreements 403, GET /api/payroll/mexico/employers 403, GET /api/payroll/mexico/ptu/cycles 403, GET /api/payroll/mexico/ptu/exclusion-reasons 403, GET /api/payroll/mexico/readiness?on=2026-10-21 403
Console errors: 9
