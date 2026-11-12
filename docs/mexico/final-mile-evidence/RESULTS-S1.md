# Mexico sweep S1 -- decisions as configuration, browser check

8/8 PASS

| Check | Result |
|---|---|
| s1-1 unanswered, the sandbox still stops at D-01's block code; no approved decisions in force | PASS |
| s1-2 D-28 offers one choice per part (6) and its configuration panel: what answering changes, what is not built | PASS |
| s1-3 the per-part choices are proposed as one PARTS answer | PASS |
| s1-4 the proposer cannot approve (four-eyes) | PASS |
| s1-5 D-01 and D-03 proposed | PASS |
| s1-6 a second Super Admin approves: each is APPROVED and 'In force' at once (no transcription needed) | PASS |
| s1-7 with D-01 and D-03 APPROVED (no candidates) the sandbox CALCULATES, not watermarked CANDIDATE, and names the answers and the pack rows they filled | PASS |
| z1 no 5xx responses and no page errors | PASS |

4xx responses seen (expected: the refused self-approval): POST /api/super-admin/compliance/mexico/decisions/24/approve 400
Console errors: Failed to load resource: the server responded with a status of 400 (Bad Request)
