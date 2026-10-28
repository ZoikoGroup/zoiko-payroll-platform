# Mexico final mile X4 -- parallel payroll browser check (on)

10/10 PASS

| Check | Result |
|---|---|
| x4-1 the parallel panel is in the Mexico Compliance Centre | PASS |
| x4-2 a file carrying an identifier value is refused, the value never echoed | PASS |
| x4-3 import compares by employee code: 2 match, 1 unexplained (net 12.50), unmatched listed | PASS |
| x4-4 with D-25 unset the cycle is never declared clean | PASS |
| x4-5 the explainer cannot accept their own explanation (four-eyes) | PASS |
| x4-6 a second admin accepts; the verdict stays undecidable without D-25 | PASS |
| x4-7 no full RFC / CURP / NSS / CLABE in the panel or the API (MX-061) | PASS |
| x4-8 NL compliance page has no Mexico panels | PASS |
| x4-9 the NL admin is refused the Mexico parallel API | PASS |
| z1 no 5xx responses and no page errors | PASS |

4xx responses seen in the browser (expected: the refusals checked above): POST /api/payroll/mexico/parallel/differences/1/accept 403, POST /api/payroll/mexico/parallel/imports 400
Console errors: Failed to load resource: the server responded with a status of 400 (Bad Request); Failed to load resource: the server responded with a status of 403 (Forbidden)
