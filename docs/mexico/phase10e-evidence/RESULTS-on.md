# Mexico Phase 10e -- browser check (mode ON)

11/11 PASS

| Check | Result |
|---|---|
| on-1 the kill switch alone opens nothing: flag on, no registry, no grant -> refused | PASS |
| on-2 readiness: level DORMANT; every pilot precondition met (kill switch, G1 G2 G4 G5 G7, Q9, hosting, key) | PASS |
| on-3 the proposer cannot approve the grant (four-eyes) | PASS |
| on-4 a second Super Admin approves: grant ACTIVE, level PILOT (1 organisation) | PASS |
| on-5 the pilot organisation opens, with the non-binding banner | PASS |
| on-6 a salary payment batch is refused on screen (MX_PILOT_NO_PAYMENTS) | PASS |
| on-7 an IDSE worklist export is refused (MX_PILOT_NO_FILINGS) | PASS |
| on-8 a run committed in the pilot is recorded as pilot; its payslip PDF carries the PILOT watermark | PASS |
| on-9 revoking closes the organisation at once (and the level returns to DORMANT) | PASS |
| on-z1 NL compliance page unchanged | PASS |
| on-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: GET /api/payroll/mexico/annual-adjustments 403, GET /api/payroll/mexico/annual-adjustments/exclusion-reasons 403, GET /api/payroll/mexico/collective-agreements 403, GET /api/payroll/mexico/employers 403, GET /api/payroll/mexico/journal/mappings 403, GET /api/payroll/mexico/payments/batches 403, GET /api/payroll/mexico/pilot-status 403, GET /api/payroll/mexico/ptu/cycles 403, GET /api/payroll/mexico/ptu/exclusion-reasons 403, GET /api/payroll/mexico/readiness?on=2026-10-22 403, POST /api/payroll/mexico/runs/2/payment-batch 400, POST /api/super-admin/compliance/mexico/pilot-grants/1/approve 400
Console errors: 26
