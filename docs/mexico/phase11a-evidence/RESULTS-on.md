# Mexico Phase 11a -- browser check (mode ON)

9/9 PASS

| Check | Result |
|---|---|
| on-1 the pinned SAT set is listed and verified | PASS |
| on-2 loading fills the Draft release from the set (every catalog row, the set recorded) | PASS |
| on-3 entries are filtered by catalog and searchable (not one 150,000-row list) | PASS |
| on-4 the loaded release is approved four-eyes (the loader cannot approve it) | PASS |
| on-5 a code outside the node's own catalog is refused | PASS |
| on-6 ISR_WITHHELD -> DEDUCCION 002 proposed, refused to its proposer, approved by a second Super Admin | PASS |
| on-7 a large catalog is capped per request (c_CodigoPostal: over 1000 refused, 1000 returned) | PASS |
| on-z1 NL compliance page unchanged | PASS |
| on-z2 no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/super-admin/compliance/mexico/cfdi-system-concepts 400, POST /api/super-admin/compliance/mexico/cfdi-system-concepts/1/approve 400, PUT /api/super-admin/compliance/mexico/cfdi-catalogs/1/approve 400
Console errors: 3
