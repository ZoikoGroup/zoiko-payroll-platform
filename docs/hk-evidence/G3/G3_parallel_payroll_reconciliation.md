# G3 — Parallel payroll reconciliation (DRAFT tool and report template)

**Status:** DRAFT — Zoiko internal, internally reviewed – pending approval. Not accepted evidence.
**Gate:** HK-GATE-G3 — "At least two representative parallel cycles show no unexplained material variance" (wireframe v1.0 §16).
**Results:** **PENDING – requires two real cycles.** No parallel cycle has been run. The tables below are a template, and no figure in them is a result.

## 1. Tool

`backend/scripts/hk_parallel_reconciliation.py`

* `export --run-id N --out zoiko.csv` exports a committed Zoiko run per employee per element. It opens a read-only session and writes employee codes only: no names, HKIDs or member accounts.
* `compare --zoiko zoiko.csv --incumbent incumbent.csv --out recon --abs A --pct P` classifies each line as MATCH, VARIANCE, MISSING_IN_ZOIKO or MISSING_IN_INCUMBENT. It writes `recon.csv` (one line per employee and element, with an empty `explanation` column) and `recon.json` (input digests, thresholds, counts and the report digest). It exits with code 1 while any line is not a MATCH.
* The elements compared are basic_salary, hra, special_allowance, overtime, additional_compensation, gross_pay, mpf_employee, mpf_employer, total_deductions and net_pay.
* Tested on 2026-10-13 in `test_hong_kong_e2e.py::test_g3_reconciliation_export_and_compare_on_a_committed_hk_run` (synthetic employee, PASSED): the export is by employee code only, and a seeded HK$25 MPF difference is reported as the single VARIANCE.

## 2. Decisions needed before the first cycle

| Decision | Proposed (owner to confirm) | Owner |
|---|---|---|
| Tolerance `--abs` (HKD) | 1.00, rounding only | Payroll Operations |
| Tolerance `--pct` | 0, so every non-rounding difference needs an explanation | Payroll Operations |
| What counts as "material" | Any unexplained VARIANCE on net_pay, mpf_employee or mpf_employer | Payroll Operations + Product |
| Representative population | Covers monthly and non-monthly, new joiners in their 60-day window, leavers, a departure (IR56G), overtime, and an SMW-boundary worker | Payroll Operations |
| Incumbent export mapping | Each incumbent pay code mapped to one element above | Payroll Operations |

## 3. Per-cycle procedure

1. Run payroll in the incumbent system as usual (it remains the system of record).
2. Run the same period in Zoiko, then commit it (approved run).
3. `export` the Zoiko run, and map the incumbent's export into the same CSV columns.
4. Run `compare` with the agreed thresholds.
5. Write an explanation for every non-MATCH line in `recon.csv` (cause, which system is right, and the corrective action).
6. Upload `recon.csv`, `recon.json` and the signed cycle sheet below as HK-GATE-G3 evidence.

## 4. Cycle sheet template (one per cycle)

| Field | Cycle 1 | Cycle 2 |
|---|---|---|
| Period | PENDING | PENDING |
| Zoiko run id / status | PENDING | PENDING |
| Zoiko export SHA-256 | PENDING | PENDING |
| Incumbent export SHA-256 | PENDING | PENDING |
| Thresholds used | PENDING | PENDING |
| Employees | PENDING | PENDING |
| MATCH / VARIANCE / MISSING | PENDING | PENDING |
| Unexplained variances | PENDING | PENDING |
| recon.json reportCsvSha256 | PENDING | PENDING |

Cycle reviewer (Payroll Operations) — Name / Role / Date / Signature: ________
Independent checker — Name / Role / Date / Signature: ________
