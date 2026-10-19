# Mexico Phase 7 -- browser check (flag OFF)

11/11 PASS

| Check | Result |
|---|---|
| off-1 NL org run screen loads, no Mexico CFDI panel | PASS |
| off-2 the Mexican run shows only the dormancy refusal (no CFDI stage, no badges) | PASS |
| off-3 GET /runs/1/cfdi -> 403 | PASS |
| off-3 POST /runs/1/cfdi/generate -> 403 | PASS |
| off-3 POST /cfdi/outbox/process -> 403 | PASS |
| off-3 GET /cfdi/documents/1 -> 403 | PASS |
| off-3 POST /cfdi/documents/1/status-query -> 403 | PASS |
| off-3 GET /cfdi/cancellation-reasons -> 403 | PASS |
| off-3 POST /cfdi/reconcile -> 403 | PASS |
| off-4 Super Admin 'CFDI lifecycle' tab: zero documents and the three production blocks | PASS |
| off-z no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: GET /api/payroll/mexico/runs/1/cfdi 403, GET /api/payroll/mexico/runs/1/preflight 403, GET /api/payroll/mexico/runs/1/status 403
Console errors: 3
