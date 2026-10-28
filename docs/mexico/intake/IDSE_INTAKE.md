# Intake: IMSS IDSE affiliation movements (gap C8)

**For:** the release owner and the employer's IMSS contact.
**Today:**
- Zoiko generates the affiliation movements (alta, baja, modificación de salario) from committed events.
- It exports them as a **worklist**, banner "ZOIKO WORKLIST - NOT AN IMSS / IDSE FILE", which the operator keys into IDSE.
- The operator records each outcome back in Zoiko.

No IDSE layout is invented.

## What we need (send all of it)

| # | Item | Why |
|---|---|---|
| 1 | **Decision:** does Zoiko transmit to IDSE, or does the employer keep keying it in? | Decides whether a file is needed at all (gap C8) |
| 2 | The IMSS **IDSE batch file layout** (the "dispositivo magnético" or text-file specification) for altas, bajas and modificaciones, with its version and date, from imss.gob.mx | The only source a layout may be built from |
| 3 | Field rules: positions, lengths, types, the movement-type codes, salary-type codes, worker-type codes, the date format, the check digits of NSS and the Registro Patronal | Building and validation |
| 4 | The **response or acuse format** IDSE returns (the lote number, accepted and rejected items, reason codes) | Recording outcomes |
| 5 | Two accepted sample files (synthetic) and one rejected file with its acuse | Golden tests |
| 6 | If Zoiko transmits: how authentication works (the employer's **e.firma** or a certificate), and who holds it | Security lead (as for the CSD; never stored by Zoiko) |
| 7 | The deadlines per movement type (today `DUE_DATE_UNSOURCED`; see decision D-16) | Due dates |

## Where it plugs in

| Zoiko today | File | What changes |
|---|---|---|
| `generate_movements(...)`: altas, bajas and salary changes from committed facts (idempotent) | `backend/app/modules/payroll/mexico_imss_service.py` | Unchanged |
| `export_worklist(db, org_id, actor_id, movement_ids)`: freezes each movement's payload and marks it EXPORTED. A retry re-exports exactly the same facts | same file | A layout writer from item 2 takes the **same frozen rows**. The worklist stays as the fallback |
| `record_outcome(...)`: FILED, ACCEPTED, REJECTED, with a reference; `regenerate` for a REJECTED movement | same file | An acuse reader from item 4 feeds the same outcomes |
| Report MX-IDSE-MOVEMENTS ("NOT AN OFFICIAL FILE") and MX-SBC-MOVEMENTS | `mexico_report_service.py` | The banner is removed only for the layout-built file |

**Owner:** release owner and the employer. **Gates:** G2, G6.
