# Mexico Phase 10b -- browser check (mode ON)

11/11 PASS

| Check | Result |
|---|---|
| on-1 a mapping is proposed as DRAFT v1 with every line type | PASS |
| on-2 its maker cannot approve it (four-eyes) | PASS |
| on-3 a second person approves it | PASS |
| on-4 the run's journal balances, each liability on its own line, accounts from v1 | PASS |
| on-5 no worker is named in the journal | PASS |
| on-6 the CSV downloads, labelled NOT POSTED, and its debits equal its credits | PASS |
| on-7 a current journal export refuses the run's reset | PASS |
| on-8 the export is voided with its reason | PASS |
| on-9 once voided, the journal no longer blocks the reset | PASS |
| on-z1 NL compliance page unchanged | PASS |
| on-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico/journal/mappings/1/approve 400
Console errors: 1
