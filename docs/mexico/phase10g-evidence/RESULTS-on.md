# Mexico Phase 10g -- browser check (mode ON)

10/10 PASS

| Check | Result |
|---|---|
| on-1 the switch shows new Mexican organisations OPEN | PASS |
| on-2 the proposer cannot approve the pause (four-eyes) | PASS |
| on-3 a second Super Admin approves: PAUSED; the pilot precondition shows it | PASS |
| on-4 while paused, a new organisation cannot become Mexican (the pause message) | PASS |
| on-5 while paused, a pilot grant cannot be approved | PASS |
| on-6 an organisation that is already Mexican keeps running | PASS |
| on-7 resumed by two Super Admins: OPEN, with both changes listed | PASS |
| on-8 after resume, the new organisation can become Mexican | PASS |
| on-z1 NL compliance page unchanged | PASS |
| on-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/super-admin/compliance/mexico/onboarding-pause/1/approve 400
Console errors: 1
