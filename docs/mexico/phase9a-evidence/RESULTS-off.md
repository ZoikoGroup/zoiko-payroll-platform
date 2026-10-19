# Mexico Phase 9a -- browser check (flag OFF)

6/6 PASS

| Check | Result |
|---|---|
| off-1 the Mexican run shows no corrections panel (dormant) | PASS |
| off-2 GET /runs/1/corrections -> 403 | PASS |
| off-2 POST /runs/1/corrections -> 403 | PASS |
| off-2 POST /corrections/1/void -> 403 | PASS |
| off-3 NL run screen loads | PASS |
| off-z no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: GET /api/payroll/mexico/runs/1/cfdi 403, GET /api/payroll/mexico/runs/1/corrections 403, GET /api/payroll/mexico/runs/1/preflight 403, GET /api/payroll/mexico/runs/1/status 403
Console errors: 4
