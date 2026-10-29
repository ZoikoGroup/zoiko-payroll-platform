# Mexico final mile X2 -- calculation sandbox browser check

9/9 PASS

| Check | Result |
|---|---|
| x2-1 today the run stops at MX_ROUNDING_RULE_MISSING, cleared by D-01, on the Draft pack | PASS |
| x2-2 with a D-01 candidate it stops at D-03 (every employee: the X2 finding) | PASS |
| x2-3 F2: with both candidates the run is CALCULATED, watermarked, SBC factor 1.049315… | PASS |
| x2-4 F1: January uses UMA 113.14, February 117.31 (25-UMA cap moves with it) | PASS |
| x2-5 F3: CEAV employer 7.513 % in band 4.01UMA, employee 1.125 %, retiro 2 % | PASS |
| x2-6 F4: 400 / day is lawful in the general zone (floor 315.04) and below the ZLFN floor | PASS |
| x2-7 a candidate for a module switch (D-07) is refused on screen | PASS |
| x2-8 nothing was written: every table's row count unchanged | PASS |
| z1 no 5xx responses and no page errors | PASS |

4xx responses seen (expected: the refused D-07 candidate): POST /api/super-admin/compliance/mexico/sandbox/calculate 400
Console errors: Failed to load resource: the server responded with a status of 400 (Bad Request)

Candidate values used (D-01 HALF_UP:0.01, D-03 GENERAL) are SYNTHETIC test inputs, not decisions.
