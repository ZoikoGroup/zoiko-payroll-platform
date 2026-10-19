# Mexico Phase 7 -- browser check (flag ON)

16/16 PASS

| Check | Result |
|---|---|
| on-1 committed run: CFDI preflight blocks (no Active schema release), Generate disabled | PASS |
| on-2a with the synthetic release the preflight clears | PASS |
| on-2b Generate -> SIGNED, Process PAC queue -> STAMPED with a UUID | PASS |
| on-2c badges: CFDI -> STAMPED; Payroll / Authorities / Bank unchanged | PASS |
| on-3a forced PAC timeout -> UNKNOWN banner; the stage has no retry button | PASS |
| on-3b UNKNOWN drawer: 'Query status' offered, confirmed retry disabled before any NOT FOUND | PASS |
| on-4a after NOT FOUND the operator can confirm a retry (reason required) | PASS |
| on-4b confirmed retry -> STAMPED; same idempotency key and payload hash on both attempts | PASS |
| on-5a replacement CFDI (synthetic correction run) stamped and names the original | PASS |
| on-5b cancel dialog: catalog reasons only; SYN1 asks for the replacement UUID | PASS |
| on-6 lineage drawer: original REPLACED, original UUID kept, 'Replaced by' = replacement UUID | PASS |
| on-7 reset refused once CFDI acted (MX_RESET_DOWNSTREAM_ACTED) | PASS |
| on-8 badges after cancel/replace: CFDI REPLACED; Payroll / Authorities / Bank unchanged | PASS |
| on-9 NL org run screen unchanged -- no Mexico CFDI panel | PASS |
| on-10 Super Admin CFDI lifecycle counts the documents (read-only) | PASS |
| on-z no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: none
Console errors: none
