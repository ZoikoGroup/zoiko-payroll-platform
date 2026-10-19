# Mexico Phase 8 -- browser check (flag ON)

16/16 PASS

| Check | Result |
|---|---|
| on-1 Social Security Center: registration card, counts and the blocks | PASS |
| on-2 accrue: SAT ISR / IMSS / INFONAVIT / ISN from the committed run, every due date unsourced | PASS |
| on-3a ALTA generated from the committed run; NSS masked on screen | PASS |
| on-3b worklist download: labelled not-an-IDSE-file, carries the NSS; movement EXPORTED | PASS |
| on-4a outcome unknown -> UNKNOWN banner; confirmed retry disabled before any NOT FOUND | PASS |
| on-4b confirmed retry -> PENDING with the same idempotency key and payload hash | PASS |
| on-4c re-exported (same record) and recorded FILED with the IDSE reference | PASS |
| on-5 ISR declaration filed; the run's Authorities lane moved, Payroll / CFDI / Bank did not | PASS |
| on-6a a one-cent difference is BLOCKING (zero tolerance) | PASS |
| on-6b reconcile refused while open; the explainer cannot approve their own explanation | PASS |
| on-6c a second person approves and reconciles the SUA period | PASS |
| on-7 ISN return = employee detail = ledger; filed, then ACCEPTED by a second person | PASS |
| on-8 reset refused once filings acted (MX_RESET_DOWNSTREAM_ACTED, naming them) | PASS |
| on-9 NL compliance page unchanged — no Mexico tabs | PASS |
| on-10 Super Admin Authorities tab counts the objects (read-only) | PASS |
| on-z no 5xx responses and no page errors | PASS |

4xx/5xx responses seen in the browser: POST /api/payroll/mexico/authorities/sua-differences/1/approve 400, POST /api/payroll/mexico/authorities/sua-periods/1/reconcile 400
Console errors: 2
