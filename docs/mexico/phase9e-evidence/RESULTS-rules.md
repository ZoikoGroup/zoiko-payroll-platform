# Mexico Phase 9e -- browser check (mode RULES)

9/9 PASS

| Check | Result |
|---|---|
| rules-1 the 2026 adjustment is computed from committed runs (2 workers, COMPUTED) | PASS |
| rules-2 the person who computed cannot approve (four-eyes) | PASS |
| rules-3 a second person approves | PASS |
| rules-4 assigned to the open January 2027 run | PASS |
| rules-5 the January payslip shows the 2026 adjustment as its own section | PASS |
| rules-6 committing the run marks the adjustments APPLIED, linked to their payslips | PASS |
| rules-7 the employee screen shows the worker's adjustment | PASS |
| rules-z1 NL compliance page unchanged | PASS |
| rules-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico/annual-adjustments/approve 400
Console errors: 1
