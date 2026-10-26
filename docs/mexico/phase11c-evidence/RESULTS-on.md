# Mexico Phase 11c -- browser check (mode ON)

7/7 PASS

| Check | Result |
|---|---|
| on-1 Validate CFDI shows the preview with the G1 decision banner first | PASS |
| on-2 the payslip is REFUSED with MX_CFDI_INPUT_MISSING and no payload hash | PASS |
| on-3 the preview response carries no XML and no identifier | PASS |
| on-4 nothing was signed, stored or queued | PASS |
| on-5 the Super Admin sees the audited summary: counts and codes, awaiting a G1 decision | PASS |
| on-z1 NL compliance page unchanged | PASS |
| on-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: none
Console errors: none
