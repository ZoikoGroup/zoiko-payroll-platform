# Mexico Phase 9c -- browser check (mode OFF)

9/9 PASS

| Check | Result |
|---|---|
| off-1 GET /termination-reasons refused while Mexico is dormant | PASS |
| off-1 GET /employees/1/terminations refused while Mexico is dormant | PASS |
| off-1 POST /employees/1/terminations refused while Mexico is dormant | PASS |
| off-1 POST /terminations/1/approve refused while Mexico is dormant | PASS |
| off-1 POST /terminations/1/cancel refused while Mexico is dormant | PASS |
| off-1 POST /terminations/1/finiquito-run refused while Mexico is dormant | PASS |
| off-2 the employee screen renders; no termination panel or form while dormant | PASS |
| off-3 NL compliance page has no Mexico panels | PASS |
| off-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: GET /api/payroll/mexico/employees/1 403, GET /api/payroll/mexico/employees/1/readiness?on=2026-10-21 403, GET /api/payroll/mexico/employers 403
Console errors: 3
