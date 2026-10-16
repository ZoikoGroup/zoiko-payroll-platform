# Netherlands golden vectors (ZP-NL-ENG-001 §18, NL-054)

Run by `tests/test_netherlands_golden.py`. Each JSON file records:

| Key | Meaning |
|-----|---------|
| `status` | `PROVISIONAL` (engineering control) or `OFFICIAL` (certified vector) |
| `source.spec` / `source.formulas` | Where every expected figure comes from, with the hand calculation |
| `source.tableRow` | The wage-tax table row used. `SYNTHETIC` for every current fixture |
| `periods[].inputs` | Gross, pay date, contract (`LOW` / `FIXED`), tax-credit instruction, expat decision; `chainVcr` carries the previous period's VCR state forward |
| `periods[].expected` | Outputs (dotted paths into `tds` / `nl` = the frozen `nl_result`) |
| `periods[].intermediates` | Unrounded intermediates: wage bases, VCR cumulative wage/max/base, hourly minimum-wage figures |
| `traceCodes` / `exceptionCodes` | Trace steps and exceptions that must be present |
| `loonaangifte` | Expected return line fields and totals after run -> approval -> return build (F1/F2) |

## Status: all PROVISIONAL — blocked on gate G1

The official 2026 Belastingdienst wage-tax tables are not in the repository, so
the F1 wage-tax figure (EUR 1,325.08 on EUR 5,000/month with the credit) is a
synthetic row equal to the spec's published example. Premiums, VCR, AWf class,
expat and minimum-wage figures follow the spec's stated rates and are exact.

To make a vector `OFFICIAL` the harness requires `source.tableRow.kind =
"OFFICIAL"`, the table file's 64-character `fileSha256`, and `source.reviewedBy`
/ `source.reviewedOn` from an independent reviewer (NL-054, NL-055).
