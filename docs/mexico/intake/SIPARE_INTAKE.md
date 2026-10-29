# Intake: SIPARE payment of IMSS / INFONAVIT contributions (gap C8)

**For:** the release owner and the employer's treasury.
**Today:**
- Zoiko accrues the IMSS and INFONAVIT liabilities from committed runs.
- The payment is made **outside Zoiko**; the operator records the reference and the capture line with `record_sua_payment`.
- Report MX-SIPARE says "NOT A SIPARE FILE".

No SIPARE format is invented.

## What we need (send all of it)

| # | Item | Why |
|---|---|---|
| 1 | **Decision:** will Zoiko ever prepare the SIPARE payment (the propuesta de pago or línea de captura), or only record it? | Decides whether anything is built (gap C8) |
| 2 | If prepared: the IMSS **SIPARE file or propuesta layout**, with its version and date | The only source a layout may be built from |
| 3 | The format of the **línea de captura** and the payment receipt the bank returns | Recording the payment and reconciling it |
| 4 | Which bank or banks the employer pays through, and whether that is the same channel as SPEI (see `SPEI_INTAKE.md`) | Channel |
| 5 | Samples (synthetic) | Golden tests |

## Where it plugs in

| Zoiko today | File | What changes |
|---|---|---|
| `accrue(...)`: IMSS / INFONAVIT liabilities per registration and period, from committed results | `backend/app/modules/payroll/mexico_filing_service.py` | Unchanged |
| `record_sua_payment(db, org_id, period_id, reference, capture_line, …)`: the payment made outside Zoiko | same file | A receipt reader from item 3 feeds the same call |
| `pay_liability(...)`, `reconcile_liability(...)` (four-eyes) | same file | Unchanged |
| Report MX-SIPARE ("NOT A SIPARE FILE") | `mexico_report_service.py` | A writer from item 2 is added beside it; the report stays |

**Owner:** release owner and the employer. **Gates:** G2, G3, G6.
