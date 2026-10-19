# Mexico Phase 9b -- browser check (mode OFF)

8/8 PASS

| Check | Result |
|---|---|
| off-1 the aguinaldo panel is refused while Mexico is dormant | PASS |
| off-2 GET /employees/1/vacation -> 403 | PASS |
| off-2 POST /employees/1/vacation -> 403 | PASS |
| off-2 POST /vacation/1/approve -> 403 | PASS |
| off-2 POST /vacation/1/withdraw -> 403 | PASS |
| off-2 POST /aguinaldo-runs -> 403 | PASS |
| off-3 NL compliance page has no Mexico panels | PASS |
| off-z no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: GET /api/payroll/mexico/collective-agreements 403, GET /api/payroll/mexico/employers 403, GET /api/payroll/mexico/readiness?on=2026-10-19 403, POST /api/payroll/mexico/aguinaldo-runs 403
Console errors: 4
