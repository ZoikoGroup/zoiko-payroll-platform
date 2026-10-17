# Mexico Phase 6 — browser check (flag OFF)

8/8 PASS

| Check | Result |
|---|---|
| off-1 NL org run screen loads, no Mexico panels | PASS |
| off-2 the Mexican run's Mexico panels show only the dormancy refusal (no badges, no trace) | PASS |
| off-3 /api/payroll/mexico/runs/1/preflight → 403 | PASS |
| off-3 /api/payroll/mexico/runs/1/status → 403 | PASS |
| off-3 /api/payroll/mexico/employees/1/hours → 403 | PASS |
| off-4 a Mexican payroll preview is refused while dormant (MX_DORMANT) | PASS |
| off-5 Super Admin Mexico workspace still loads | PASS |
| off-z no 5xx responses and no page errors | PASS |

4xx/5xx responses seen: GET /api/payroll/mexico/runs/1/preflight 403, GET /api/payroll/mexico/runs/1/status 403
Console errors: 2
