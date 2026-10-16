# Mexico Phase 3 — real-browser acceptance

Installed Chrome (Playwright `channel="chrome"`), `vite build` + `vite preview`, uvicorn on a throwaway SQLite DB (`harness/setup_db.py`, scratch path asserted). Users are throwaway `@example.com` accounts that exist only in that DB.

**30/30 checks passed.**

Provoked MX refusals (HTTP 400): 6. Pre-existing non-Mexico shell probe (payroll_admin → /api/organization-admin/assisted-access/status 403): 1 call(s).

| Check | Result |
|---|---|
| 01 MX org sees 'Mexico Compliance Centre' and no 'Tax Configuration' tab | PASS |
| 01 Employer & Registrations section renders | PASS |
| 02 a 13-character RFC for a persona moral is refused with the field message | PASS |
| 02 a valid RFC is accepted and panels A–H render | PASS |
| 02 new version recorded; v1 closed 2026-06-30 | PASS |
| 03 two IMSS registrations listed | PASS |
| 03 premium approval refused: waiting for a second org admin (four-eyes, no exception) | PASS |
| 04 CDMX ISN registration shows PENDING_PACK | PASS |
| 04 JAL refused with the MX-045 text | PASS |
| 04 establishment minimum-wage zone UNRESOLVED (S9 not transcribed) | PASS |
| 05 labour policy floor check is BLOCKED_CONTENT with its reason | PASS |
| 05 activation refused | PASS |
| 06 pasted private key refused and not shown back | PASS |
| 06 vault:// scheme refused (only gcp-sm://) | PASS |
| 06 gcp-sm:// reference accepted and shown masked only | PASS |
| 06 .cer upload shows serial, fingerprint and expiry | PASS |
| 07 readiness date bar shows a date and the LIVE line is BLOCKED | PASS |
| 07 picking 2026-03-01 re-reads readiness for that date | PASS |
| 07 items show gates, unmapped items and Phase 7/8/10 blocks | PASS |
| 08 operator sees the employer data | PASS |
| 08 operator write over the API → 403 | PASS |
| 09 another tenant has no legal employer and none of org A's data | PASS |
| 09 another tenant → 404 on org A's employer id | PASS |
| 10 Super Admin Employer tab: panels render read-only, RFC masked | PASS |
| 10 Super Admin readiness: per-gate employer summary | PASS |
| 12 NL org: Netherlands Compliance Centre, no Tax Configuration, no MX tab | PASS |
| 13 HK org: Hong Kong Compliance Centre and Tax Configuration kept, no MX tab | PASS |
| 14 Super Admin NL workspace still loads | PASS |
| 15 no unexpected 4xx/5xx (only the provoked MX refusals) | PASS |
| 15 no page or console errors beyond the provoked refusals | PASS |
