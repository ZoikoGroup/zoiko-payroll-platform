# Mexico Phase 9d -- browser check (mode RULES)

12/12 PASS

| Check | Result |
|---|---|
| rules-1 a PTU cycle is recorded in the Compliance Centre (DRAFT) | PASS |
| rules-2 the recorder cannot approve the amount (four-eyes) | PASS |
| rules-3 a second person approves the amount; the pay-by date is from the rule | PASS |
| rules-4 an operator exclusion: catalog reason + evidence, approved by the other person | PASS |
| rules-5 allocated from committed runs: worker 1 paid, worker 2 excluded with the reason and evidence | PASS |
| rules-6 the allocator cannot approve the allocation (four-eyes) | PASS |
| rules-7 a second person approves the allocation; the PTU run opens | PASS |
| rules-8 the PTU payslip: one MX_PTU line, special withholding, no IMSS; the excluded worker has none | PASS |
| rules-9 committing the run marks the cycle DISTRIBUTED | PASS |
| rules-10 the employee screen shows the worker's PTU | PASS |
| rules-z1 NL compliance page unchanged | PASS |
| rules-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico/ptu/cycles/1/approve-allocation 400, POST /api/payroll/mexico/ptu/cycles/1/approve-amount 400
Console errors: 2
