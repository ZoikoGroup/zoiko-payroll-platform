"""
Hong Kong G3 parallel payroll reconciliation: Zoiko vs the incumbent payroll,
per employee, per element, with variance thresholds.

    # 1. export Zoiko's committed run (read-only session; employee codes only, no names / HKIDs)
    python -m scripts.hk_parallel_reconciliation export --run-id 123 --out zoiko_2026-07.csv

    # 2. compare with the incumbent's export, mapped into the same columns
    python -m scripts.hk_parallel_reconciliation compare --zoiko zoiko_2026-07.csv \
        --incumbent incumbent_2026-07.csv --out recon_2026-07 [--abs 1.00] [--pct 0.5]

Both CSVs use the columns: employee_ref, period, element, amount.
Elements: basic_salary, hra, special_allowance, overtime, additional_compensation,
gross_pay, mpf_employee, mpf_employer, total_deductions, net_pay.

A line is MATCH when |Zoiko − incumbent| ≤ max(abs, pct% of |incumbent|), and
VARIANCE otherwise. MISSING_IN_ZOIKO and MISSING_IN_INCUMBENT are always
reported. The thresholds are inputs: their values are a G3 owner decision,
not something this tool decides. Every VARIANCE needs a written explanation
in the report's "explanation" column before the cycle can be signed. A
VARIANCE with no explanation is unexplained, and G3 requires none.

Outputs <out>.csv (every line) and <out>.json (summary, inputs' SHA-256, the
thresholds used, and the report's own SHA-256).
"""

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ELEMENTS = {   # report element -> PayslipItem column
    "basic_salary": "basic_salary", "hra": "hra", "special_allowance": "special_allowance", "overtime": "overtime",
    "additional_compensation": "additional_compensation", "gross_pay": "gross_pay",
    "mpf_employee": "employee_pension", "mpf_employer": "employer_pension",
    "total_deductions": "total_deductions", "net_pay": "net_pay",
}
FIELDS = ["employee_ref", "period", "element", "amount"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dec(v, where) -> Decimal:
    try:
        return Decimal(str(v).replace(",", "").strip())
    except InvalidOperation:
        raise SystemExit(f"not a number: {v!r} ({where})")


def export(run_id: int, out: Path) -> int:
    from sqlalchemy import text

    from app.database import SessionLocal
    from app.modules.payroll.models import PayrollEmployee as Employee, PayrollRun, PayslipItem

    db = SessionLocal()
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET SESSION default_transaction_read_only = on"))
        db.commit()
    run = db.get(PayrollRun, run_id)
    if run is None:
        raise SystemExit(f"payroll run {run_id} not found")
    rows = []
    for item, code in (db.query(PayslipItem, Employee.employee_code).join(Employee, Employee.id == PayslipItem.employee_id)
                       .filter(PayslipItem.payroll_run_id == run_id).order_by(Employee.employee_code)):
        for element, column in ELEMENTS.items():
            value = getattr(item, column, None)
            rows.append({"employee_ref": code, "period": run.period_label, "element": element,
                         "amount": str(value if value is not None else Decimal("0"))})
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"run {run_id} ({run.period_label}, status {run.status}): {len(rows)} lines -> {out}  sha256={_sha(out)}")
    return 0


def _load(path: Path) -> dict:
    out = {}
    for i, r in enumerate(csv.DictReader(path.open(encoding="utf-8-sig")), start=2):
        if r.get("element") not in ELEMENTS:
            raise SystemExit(f"{path}:{i}: unknown element {r.get('element')!r}")
        key = (r["employee_ref"].strip(), r["period"].strip(), r["element"])
        if key in out:
            raise SystemExit(f"{path}:{i}: duplicate line for {key}")
        out[key] = _dec(r["amount"], f"{path}:{i}")
    return out


def compare(zoiko: Path, incumbent: Path, out: Path, abs_tol: Decimal, pct_tol: Decimal) -> dict:
    z, inc = _load(zoiko), _load(incumbent)
    lines = []
    for key in sorted(set(z) | set(inc)):
        emp, period, element = key
        zv, iv = z.get(key), inc.get(key)
        if zv is None or iv is None:
            status, diff = ("MISSING_IN_ZOIKO" if zv is None else "MISSING_IN_INCUMBENT"), None
        else:
            diff = zv - iv
            allowed = max(abs_tol, abs(iv) * pct_tol / Decimal("100"))
            status = "MATCH" if abs(diff) <= allowed else "VARIANCE"
        lines.append({"employee_ref": emp, "period": period, "element": element,
                      "zoiko": "" if zv is None else str(zv), "incumbent": "" if iv is None else str(iv),
                      "difference": "" if diff is None else str(diff), "status": status, "explanation": ""})
    csv_path = out.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(lines[0]) if lines else FIELDS)
        w.writeheader()
        w.writerows(lines)
    by_status = {}
    for ln in lines:
        by_status[ln["status"]] = by_status.get(ln["status"], 0) + 1
    by_element = {}
    for ln in lines:
        if ln["status"] != "MATCH":
            by_element[ln["element"]] = by_element.get(ln["element"], 0) + 1
    summary = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "inputs": {"zoiko": {"file": str(zoiko), "sha256": _sha(zoiko)},
                   "incumbent": {"file": str(incumbent), "sha256": _sha(incumbent)}},
        "thresholds": {"absoluteHKD": str(abs_tol), "percentOfIncumbent": str(pct_tol)},
        "employees": len({k[0] for k in set(z) | set(inc)}), "lines": len(lines), "byStatus": by_status,
        "nonMatchingByElement": by_element,
        "unexplainedVariances": sum(1 for ln in lines if ln["status"] != "MATCH"),
        "reportCsv": str(csv_path), "reportCsvSha256": _sha(csv_path),
    }
    out.with_suffix(".json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hong Kong G3 parallel payroll reconciliation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--run-id", type=int, required=True)
    e.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("--zoiko", type=Path, required=True)
    c.add_argument("--incumbent", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--abs", type=Decimal, required=True, help="absolute tolerance in HKD (owner decision)")
    c.add_argument("--pct", type=Decimal, required=True, help="tolerance as % of the incumbent amount (owner decision)")
    args = ap.parse_args(argv)
    if args.cmd == "export":
        return export(args.run_id, args.out)
    s = compare(args.zoiko, args.incumbent, args.out, args.abs, args.pct)
    print(json.dumps(s, indent=1))
    return 0 if s["unexplainedVariances"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
