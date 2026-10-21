# Mexico Phase 9c -- browser check (mode RULES)

11/11 PASS

| Check | Result |
|---|---|
| rules-1 the termination panel is on the Mexican employee's screen | PASS |
| rules-2 the reason is chosen only from the transcribed catalog | PASS |
| rules-3 termination recorded from the employee screen (DRAFT) | PASS |
| rules-4 the recorder cannot approve it (four-eyes) | PASS |
| rules-5 a second person approves: date of leaving set, IMSS BAJA generated and shown | PASS |
| rules-6 the finiquito run opens from the panel; Cancel is no longer offered | PASS |
| rules-7 finiquito computed (SYNTHETIC rules): aguinaldo, vacation paid out + premium, separation | PASS |
| rules-8 committing the finiquito marks the termination COMMITTED and writes PAID_OUT vacation | PASS |
| rules-9 the final ordinary period pays to the termination date (16-20 June = 5 days) | PASS |
| rules-z1 NL compliance page unchanged | PASS |
| rules-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico/terminations/1/approve 400
Console errors: 1
