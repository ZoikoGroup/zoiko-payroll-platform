# Intake: bank / SPEI payment file (gap C7)

**For:** the release owner and the employer's treasury, when a bank is chosen.
**Today:** Zoiko produces a **settlement worklist**, banner "ZOIKO PAYMENT WORKLIST - NOT A BANK FILE". It is not a bank file. No layout is invented (rule: no invented layouts).

## What we need from the bank (send all of it)

| # | Item | Why |
|---|---|---|
| 1 | The bank's **name** and the product: host-to-host, a portal upload, or an API | Decides file or call |
| 2 | The **file specification document** for bulk SPEI payroll payments, with its version and date | The only source a layout may be built from |
| 3 | Field list: position or delimiter, length, type, padding, mandatory or optional, allowed values | Building and validation |
| 4 | Header and trailer rules: totals, counts, control digits, the file name pattern, encoding (ASCII or UTF-8), line ending | Building and validation |
| 5 | **Two sample files** the bank accepts (synthetic data) and one it rejects, with the rejection | Golden tests |
| 6 | The **return / rejection file** specification (devoluciones) and its reason codes | Recording each item's outcome |
| 7 | How the employer's **ordering account** and contract number appear | Header |
| 8 | Cut-off times, value dates, maximum items per file | Release timing |
| 9 | Signing or encryption of the file, if required, and who holds the key | Security lead (as for the CSD) |
| 10 | A test environment, or a contact who validates test files | Acceptance |

## Where it plugs in

| Zoiko today | File | What changes once the specification is in hand |
|---|---|---|
| Batches of net pay per committed run, four-eyes release, outcomes per item, re-issue | `backend/app/modules/payroll/mexico_payment_service.py` | Unchanged |
| `export_worklist(db, org_id, batch_id, actor_id)`: reads each full CLABE at export time only, never stores it, records an audited SHA-256 | same file | A second writer beside it, `export_bank_file(...)`, built **only** from item 2. The worklist stays |
| `file_mode` is restricted to `'WORKLIST'` by a check constraint (`ck_mx_payment_batch_mode`) | `models.py`, `PayrollMxPaymentBatch` | An additive migration allows the new mode, with ZP-PRIV review |
| `record_item_outcome(...)`: PAID, RETURNED and so on, typed in by the operator | same service | A return-file reader from item 6 feeds the same outcomes |
| Report MX-PAYMENT-WORKLIST (final mile X3): accounts shown by their last four digits only | `mexico_report_service.py` | Unchanged |

**Owner:** release owner and the employer (bank choice). **Gate:** G6.
