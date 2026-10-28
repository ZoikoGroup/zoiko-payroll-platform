# Mexico final mile X4 -- parallel payroll browser check (off)

8/8 PASS

| Check | Result |
|---|---|
| off-1 GET /parallel/imports refused while Mexico is dormant | PASS |
| off-1 POST /parallel/imports refused while Mexico is dormant | PASS |
| off-1 GET /parallel/imports/1 refused while Mexico is dormant | PASS |
| off-1 POST /parallel/imports/1/withdraw refused while Mexico is dormant | PASS |
| off-1 POST /parallel/differences/1/explain refused while Mexico is dormant | PASS |
| off-1 POST /parallel/differences/1/accept refused while Mexico is dormant | PASS |
| off-2 the parallel panel shows the dormancy refusal | PASS |
| z1 no 5xx responses and no page errors | PASS |

4xx responses seen in the browser (expected: the refusals checked above): GET /api/payroll/mexico/annual-adjustments 403, GET /api/payroll/mexico/annual-adjustments/exclusion-reasons 403, GET /api/payroll/mexico/collective-agreements 403, GET /api/payroll/mexico/employers 403, GET /api/payroll/mexico/journal/mappings 403, GET /api/payroll/mexico/parallel/imports 403, GET /api/payroll/mexico/payments/batches 403, GET /api/payroll/mexico/pilot-status 403, GET /api/payroll/mexico/ptu/cycles 403, GET /api/payroll/mexico/ptu/exclusion-reasons 403, GET /api/payroll/mexico/readiness?on=2026-10-27 403
Console errors: Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden); Failed to load resource: the server responded with a status of 403 (Forbidden)
