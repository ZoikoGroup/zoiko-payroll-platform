# Mexico — UNKNOWN-state recovery runbook (MX-062)

**For:** payroll operators and Org Admins running Mexican payroll in Zoiko, and the on-call engineer after an outage or a database restore.

**Rule.** When Zoiko cannot tell whether something that left Zoiko arrived, the object is **UNKNOWN**, never FAILED. Nothing is ever retried automatically. A retry happens only after a recorded check, a reason and an admin's confirmation, and it reuses **the same payload and the same idempotency key**, so the authority, the PAC or the bank can never receive it twice as two different things.

Every route below is under `/api/payroll/mexico` and needs an Org Admin, unless stated otherwise.

## 1. What can be UNKNOWN

| Object | Leaves Zoiko when | Becomes UNKNOWN when | Where it is shown |
|---|---|---|---|
| **CFDI** (payslip receipt) | sent to the PAC for stamping or cancellation | the PAC call times out or fails in transport; a database restore leaves it in flight; a UUID conflict | Mexico Compliance Centre → CFDI |
| **IMSS movement** | the operator uploads the IDSE worklist | the operator records that the upload's outcome is not known | Authorities → IMSS movements |
| **Authority liability** (SAT ISR, IMSS, INFONAVIT, ISN) | the declaration is submitted or paid | the operator records that the outcome is not known | Authorities → liabilities |
| **ISN return** | the state return is filed | the operator records that the outcome is not known | Authorities → ISN returns |
| **SUA period** | paid through SIPARE | the operator records that the outcome is not known | Authorities → SUA |
| **Salary payment item** (Phase 10a) | keyed into online banking from the worklist | the operator records UNKNOWN (the bank shows no clear result) | Salary payments |

## 2. CFDI (PAC)

1. **Do not generate a new CFDI.** The UNKNOWN document keeps its folio, payload and idempotency key.
2. **Query the PAC:** `POST /cfdi/documents/{id}/status-query`. This queues a status query, and the outbox processes it.
   - **Stamped** at the PAC: Zoiko adopts the UUID and the document becomes STAMPED. Done.
   - **Rejected:** the document becomes REJECTED with the PAC's code. Fix the cause, then regenerate.
   - **Not found:** recorded. Repeat the query later. The PAC can lag.
3. **Retry only when definitively not found.** That needs the channel's retry configuration, which ships empty, so it is never automatic. Then:
   `POST /cfdi/documents/{id}/confirm-retry` with `{"reason": "…"}`. The same payload and key are re-sent.
4. **A late "stamped" result** after a retry was confirmed but not yet sent: the UUID is adopted and nothing is sent twice.
5. **UUID conflict** (the PAC returns a UUID that belongs to another document): the document stays UNKNOWN for manual reconciliation with the PAC. Never stamp a second document for the same payslip.

## 3. Authority objects (IMSS, SAT, INFONAVIT, ISN, SUA)

`{kind}` is one of `movements`, `liabilities`, `isn-returns` or `sua-periods`.

1. **Record that the outcome is not known:** `POST /authorities/{kind}/{id}/unknown` with an optional `note`. The object becomes UNKNOWN and is frozen: its payload hash cannot change.
2. **Check with the authority** (IDSE, SAT, the state portal, SIPARE), then record the check:
   `POST /authorities/{kind}/{id}/status-check` with `{"found": true, "reference": "…"}` or `{"found": false}`.
   - **FOUND** with the authority's reference: the object moves on (filed or paid). Done.
   - **NOT_FOUND:** recorded. Nothing moves.
3. **Retry after a NOT_FOUND:** an admin confirms with a reason, using `POST /authorities/{kind}/{id}/confirm-retry` with `{"reason": "…"}`. The same row, payload hash and idempotency key go back to the pre-transmission state (RETRY_READY). Then upload or submit again **the same file**.
4. **A late FOUND** while the retry is still unsent: the reference is adopted and nothing is sent twice.

## 4. Salary payments (Phase 10a)

1. Record **UNKNOWN** on the item when the bank shows no clear result. The batch stays RELEASED, not CLOSED.
2. **Never re-pay an UNKNOWN item.** Check the bank statement or the SPEI tracking (the Banxico CEP), using the worklist reference `ZP-{batch}-{item}`.
3. Resolve it to **SETTLED** (with the SPEI reference), or to **FAILED** or **RETURNED** (with the reference and the reason).
4. Only a FAILED or RETURNED item can be **re-issued**, in a new batch linked to it. The payslip is never edited.

## 5. After an outage or a database restore

1. **Before** the outbox runs again, an Org Admin of each Mexican organisation calls `POST /cfdi/reconcile`. Every CFDI that was in flight (SUBMITTED or CANCEL_REQUESTED) and every SENT outbox item becomes UNKNOWN.
2. Work through §2 for each UNKNOWN CFDI.
3. For authority objects and payments, compare the restored state with what was uploaded, filed or paid since the backup was taken (the operator's own records and the portals), and follow §3 and §4.
4. Record what was done in the incident log, with the object ids and the references.

## 6. What never happens

- No automatic retry, on any channel.
- No second CFDI, filing or payment for the same thing while one is UNKNOWN.
- No UNKNOWN object is deleted or edited. Its events are append-only.
- A run with an UNKNOWN CFDI, filing or payment cannot be reset (Phase 6 rule).
