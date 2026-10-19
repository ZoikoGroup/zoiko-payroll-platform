# Mexico Phase 9b -- browser check (mode ON)

8/8 PASS

| Check | Result |
|---|---|
| on-1 aguinaldo run opened from the Compliance Centre | PASS |
| on-2 every aguinaldo payslip is BLOCKED: the proportion rule is not transcribed (S26) | PASS |
| on-4 vacation TAKEN recorded from the employee screen (DRAFT) | PASS |
| on-5 the recorder cannot approve their own record (four-eyes) | PASS |
| on-6 a second person approves; the ledger shows the balance | PASS |
| on-7 the Jun 16-30 payslip with the vacation premium is BLOCKED (special-pay rule, S24) | PASS |
| on-9 NL compliance page unchanged | PASS |
| on-z no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico/vacation/1/approve 400
Console errors: 1
