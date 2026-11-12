# Mexico sweep S1 -- org-admin decision inputs, browser check

7/7 PASS

| Check | Result |
|---|---|
| s1f-1 the profile form offers union member (C12) and the operator-entered SDI + evidence (C4) | PASS |
| s1f-2 an SDI without its evidence is refused on screen | PASS |
| s1f-3 with its evidence the new profile version is recorded | PASS |
| s1f-4 the termination form offers the indemnity daily salary and its evidence (D-12 c) | PASS |
| s1f-5 the labour-policy form offers the daily-hours figure (D-17 c) and the employer's special-pay method (D-08 per employer) | PASS |
| s1f-6 the policy is recorded with both figures and reads back | PASS |
| z1 no 5xx responses and no page errors | PASS |

4xx responses seen (expected: the refused SDI without evidence): POST /api/payroll/employees/1/statutory-profile 400
Console errors: Failed to load resource: the server responded with a status of 400 (Bad Request)
