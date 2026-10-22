# Mexico Phase 10f -- browser check (mode ON)

12/12 PASS

| Check | Result |
|---|---|
| on-1 the run screen of a pilot run shows PILOT (banner and badge) | PASS |
| on-2 the payslip view of a pilot payslip shows PILOT | PASS |
| on-3 the proposing pilot admin cannot release it (four-eyes) | PASS |
| on-4 a second pilot admin releases it: AVAILABLE, expiring in 7 days, employer RFC masked | PASS |
| on-5 the live admin reviews the diff: employees listed, identifiers masked | PASS |
| on-6 the proposing live admin cannot approve the import (four-eyes) | PASS |
| on-7 a second live admin approves: EXECUTED, 0 differences | PASS |
| on-8 the live organisation now has the pilot's 2 employees and no payroll result | PASS |
| on-9 the pilot sees its release USED (one use only) | PASS |
| on-10 every step is audited on the live side too, with no identifier or name in the audit | PASS |
| on-z1 NL compliance page unchanged | PASS |
| on-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico-transfer/imports/1/approve 400, POST /api/payroll/mexico-transfer/releases/1/release 400
Console errors: 2
