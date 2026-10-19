# Mexico Phase 9b -- browser check (mode RULES)

10/10 PASS

| Check | Result |
|---|---|
| rules-1 aguinaldo run opened from the Compliance Centre | PASS |
| rules-2 aguinaldo computed (SYNTHETIC rules): 15 days × 600 × full year; no IMSS; ISR by the special rule | PASS |
| rules-3 the aguinaldo run approves and commits | PASS |
| rules-4 vacation TAKEN recorded from the employee screen (DRAFT) | PASS |
| rules-5 the recorder cannot approve their own record (four-eyes) | PASS |
| rules-6 a second person approves; the ledger shows the balance | PASS |
| rules-7 the premium is a line of the Jun 16-30 payslip (2 days × 600 × 25%) | PASS |
| rules-8 approving the run marks the record PAID, linked to the run | PASS |
| rules-9 NL compliance page unchanged | PASS |
| rules-z no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico/vacation/1/approve 400
Console errors: 1
