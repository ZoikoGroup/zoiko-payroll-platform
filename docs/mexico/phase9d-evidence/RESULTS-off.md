# Mexico Phase 9d -- browser check (mode OFF)

8/8 PASS

| Check | Result |
|---|---|
| off-1 GET /ptu/cycles refused while Mexico is dormant | PASS |
| off-1 POST /ptu/cycles refused while Mexico is dormant | PASS |
| off-1 POST /ptu/cycles/1/allocate refused while Mexico is dormant | PASS |
| off-1 POST /ptu/cycles/1/ptu-run refused while Mexico is dormant | PASS |
| off-1 GET /ptu/exclusion-reasons refused while Mexico is dormant | PASS |
| off-2 the PTU panel shows the dormancy refusal | PASS |
| off-3 NL compliance page has no Mexico panels | PASS |
| off-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: GET /api/payroll/mexico/collective-agreements 403, GET /api/payroll/mexico/employers 403, GET /api/payroll/mexico/ptu/cycles 403, GET /api/payroll/mexico/ptu/exclusion-reasons 403, GET /api/payroll/mexico/readiness?on=2026-10-21 403
Console errors: 6
