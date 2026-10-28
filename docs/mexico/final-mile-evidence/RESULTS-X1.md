# Mexico final mile X1 -- decision register browser check

13/13 PASS

| Check | Result |
|---|---|
| x1-1 the register lists the seeded decisions, all OPEN | PASS |
| x1-2 filtering by gate keeps only that gate's decisions | PASS |
| x1-3 D-01 shows its question, both options with sources, the block code and the content key | PASS |
| x1-4 an answer outside the rounding grammar is refused | PASS |
| x1-5 propose: D-01 becomes PROPOSED with its answer | PASS |
| x1-6 the proposer cannot approve (four-eyes), refused on screen | PASS |
| x1-7 approve by a second Super Admin: APPROVED with a transcription ticket (Draft pack only) | PASS |
| x1-8 mark transcribed with its reference | PASS |
| x1-9 revise: a new OPEN version 2 appears; version 1 stays in force | PASS |
| x1-10 withdrawing a proposal returns the decision to OPEN | PASS |
| x1-11 withdrawing an OPEN decision closes it (WITHDRAWN) | PASS |
| x1-12 readiness counts the open decisions per gate | PASS |
| z1 no 5xx responses and no page errors | PASS |

4xx responses seen (expected: the refused proposal and the refused self-approval): POST /api/super-admin/compliance/mexico/decisions/1/approve 400, POST /api/super-admin/compliance/mexico/decisions/1/propose 400
Console errors: Failed to load resource: the server responded with a status of 400 (Bad Request); Failed to load resource: the server responded with a status of 400 (Bad Request)
