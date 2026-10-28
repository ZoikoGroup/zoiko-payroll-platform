# Intake: IMSS SUA (gap C8)

**For:** the release owner and the employer's IMSS contact.
**Today:**
- Zoiko opens a SUA period per IMSS registration and bimester or month, and computes its own totals from committed results.
- The operator **types in** the figures SUA produced, through the Zoiko template.
- Zoiko lists the differences; each is explained and approved four-eyes, then reconciled.
- Report MX-SUA-RECON says "NOT A SUA FILE".

No SUA file format is invented.

## What we need (send all of it)

| # | Item | Why |
|---|---|---|
| 1 | **Decision:** import the SUA's figures from a file, export Zoiko's data into SUA, or keep typing figures in | Decides which direction (gap C8) |
| 2 | For an **export into SUA**: the SUA import layout for workers and movements (the "archivo de importación" of the SUA version in use), with its version, from IMSS | The only source a layout may be built from |
| 3 | For an **import of SUA results**: the export or report layout of the SUA version in use (per worker, per branch, per side) | Replaces typing |
| 4 | The SUA **version** the employer runs, and how upgrades are announced | Pinning (`sua_version` is already recorded per period) |
| 5 | Sample files from that version (synthetic workers), accepted by SUA | Golden tests |

## Where it plugs in

| Zoiko today | File | What changes |
|---|---|---|
| `open_sua_period(...)`; `_zoiko_totals(...)` from committed snapshots | `backend/app/modules/payroll/mexico_filing_service.py` | Unchanged |
| `enter_sua_figures(db, org_id, period_id, rows, sua_version, …)`: one row per worker × branch × side | same file | A file reader from item 3 produces **the same rows** and calls the same function. Differences, explanations and four-eyes approval stay |
| `reconcile_sua(...)`, `record_sua_payment(...)` | same file | Unchanged |
| Report MX-SUA-RECON ("NOT A SUA FILE") | `mexico_report_service.py` | Unchanged; an export into SUA is a new writer from item 2 |

**Owner:** release owner and the employer. **Gates:** G2, G6.
