# Mexico Phase 8 -- browser check (flag OFF)

12/12 PASS

| Check | Result |
|---|---|
| off-1 NL compliance page: no Mexico tabs, no Social Security Center | PASS |
| off-2 Mexican org: the Social Security tab shows only the dormancy refusal | PASS |
| off-3 GET /authorities/summary -> 403 | PASS |
| off-3 POST /authorities/accrue -> 403 | PASS |
| off-3 POST /authorities/movements/generate -> 403 | PASS |
| off-3 POST /authorities/movements/export -> 403 | PASS |
| off-3 GET /authorities/liabilities -> 403 | PASS |
| off-3 POST /authorities/sua-periods -> 403 | PASS |
| off-3 POST /authorities/isn-returns -> 403 | PASS |
| off-3 POST /authorities/movements/1/unknown -> 403 | PASS |
| off-4 Super Admin 'Authorities' tab: zero counts and the blocks | PASS |
| off-z no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: GET /api/payroll/mexico/authorities/isn-returns 403, GET /api/payroll/mexico/authorities/liabilities 403, GET /api/payroll/mexico/authorities/movements 403, GET /api/payroll/mexico/authorities/sua-periods 403, GET /api/payroll/mexico/authorities/summary 403
Console errors: 5
