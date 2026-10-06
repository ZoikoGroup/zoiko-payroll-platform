"""
scripts/hk_parallel_run_compare.py
----------------------------------
G3 parallel-payroll comparison (READ-ONLY). Takes the reference payroll's
figures in the G3 ``VARIANCE_TEMPLATE.csv`` layout (``reference_value``
filled in by Payroll Operations) and fills ``zoiko_value`` / ``variance`` /
``within_tolerance`` from Zoiko's COMMITTED Hong Kong payroll for the same
organisation, employee and period.

It never writes to the database and never decides that a variance is
acceptable: an out-of-tolerance row is classified UNEXPLAINED, and only the
reviewer may change it to EXPLAINED (with the cause) when signing
``RUN_RECORD.md``. Measures it cannot derive mechanically (final wages,
SP / LSP, average wage, IR56G hold, eMPF totals, BIR56A status) are marked
MANUAL_REVIEW — compared by the reviewer from the named Zoiko screen.

Usage (from backend/):
  python scripts/hk_parallel_run_compare.py --org <id> --in reference.csv --out variance.csv
"""

import argparse
import csv
import sys
from datetime import date
from decimal import Decimal, InvalidOperation

AUTO = ("gross_paid", "mpf_employee", "mpf_employer", "net_pay", "income_tax_withheld", "ir56b_total")
MANUAL_SOURCE = {
    "smw_top_up": "payslip trace → minimum wage", "mpf_employer_catch_up": "payslip trace → MPF accrued pending",
    "final_wages": "termination statement", "annual_leave_pay": "termination statement",
    "net_statutory_payment": "termination statement (SP / LSP after offset)",
    "average_daily_wage": "average-wage snapshot", "held_amount": "tax-clearance hold (IR56G)",
    "remittance_total_employer": "eMPF submission totals", "remittance_total_employee": "eMPF submission totals",
    "reconciliation_status": "BIR56A annual return reconciliation",
}
COLUMNS = ["cycle", "period", "employee_ref", "category", "measure", "reference_value", "zoiko_value", "variance",
           "tolerance", "within_tolerance", "classification", "explanation", "resolution", "reviewer", "approved_by",
           "date"]


def _dec(v):
    try:
        return Decimal(str(v).strip())
    except (InvalidOperation, AttributeError):
        return None


def _month_bounds(period: str):
    y, m = (int(x) for x in period.split("-"))
    end = date(y + (m == 12), m % 12 + 1, 1)
    return date(y, m, 1), date.fromordinal(end.toordinal() - 1)


def zoiko_value(db, organization_id: int, row: dict):
    """Zoiko's figure for one template row, or None when it is not mechanically derivable."""
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import HongKongIrdReportingCase, PayrollEmployee

    measure, period, ref = row["measure"], row["period"], row["employee_ref"]
    if measure not in AUTO or ref == "ALL":
        return None
    emp = (db.query(PayrollEmployee).filter(PayrollEmployee.organization_id == organization_id,
                                            PayrollEmployee.employee_code == ref).first())
    if emp is None:
        return "EMPLOYEE_NOT_FOUND"
    if measure == "ir56b_total":
        case = (db.query(HongKongIrdReportingCase)
                .filter(HongKongIrdReportingCase.organization_id == organization_id, HongKongIrdReportingCase.employee_id == emp.id,
                        HongKongIrdReportingCase.form_type == "IR56B", HongKongIrdReportingCase.year_of_assessment == period,
                        HongKongIrdReportingCase.status.notin_(("AMENDED", "CANCELLED")))
                .order_by(HongKongIrdReportingCase.id.desc()).first())
        return Decimal(case.payload["total"]) if case and case.payload else "NO_IR56B_CASE"
    start, end = _month_bounds(period)
    pairs = hong_kong_service._committed_hk_payslips(db, organization_id, start, end, employee_id=emp.id)
    if not pairs:
        return "NO_COMMITTED_PAYSLIP"
    total = Decimal("0")
    for item, _run in pairs:
        result = (item.hk_calculation_trace or {}).get("result") or {}
        if measure == "gross_paid":
            total += Decimal(str(item.gross_pay or 0)) - Decimal(str(getattr(item, "attendance_deduction", None) or 0))
        elif measure == "mpf_employee":
            total += Decimal(result.get("mpfEmployee", "0"))
        elif measure == "mpf_employer":
            total += Decimal(result.get("mpfEmployer", "0"))
        elif measure == "net_pay":
            total += Decimal(str(item.net_pay or 0))
        elif measure == "income_tax_withheld":
            total += Decimal(str(item.federal_income_tax or 0)) + Decimal(str(item.state_income_tax or 0))
    return total


def compare(db, organization_id: int, rows: list) -> list:
    out = []
    for row in rows:
        r = {c: row.get(c, "") for c in COLUMNS}
        r["explanation"] = row.get("explanation", "")
        if r["classification"] not in ("EXPLAINED",):           # a reviewer's EXPLAINED is kept; nothing else is
            r["classification"] = ""
        z = zoiko_value(db, organization_id, row)
        if z is None:
            r["zoiko_value"], r["within_tolerance"] = "", ""
            r["classification"] = r["classification"] or "MANUAL_REVIEW"
            r["explanation"] = r["explanation"] or f"compare from: {MANUAL_SOURCE.get(r['measure'], 'the named Zoiko record')}"
        elif isinstance(z, str):
            r["zoiko_value"], r["within_tolerance"], r["classification"] = z, "NO", r["classification"] or "UNEXPLAINED"
        else:
            ref, tol = _dec(row.get("reference_value")), _dec(row.get("tolerance")) or Decimal("0")
            r["zoiko_value"] = str(z)
            if ref is None:
                r["variance"], r["within_tolerance"] = "", "NO_REFERENCE"
                r["classification"] = r["classification"] or "UNEXPLAINED"
            else:
                diff = z - ref
                ok = abs(diff) <= tol
                r["variance"], r["within_tolerance"] = str(diff), "YES" if ok else "NO"
                r["classification"] = "WITHIN_TOLERANCE" if ok else (r["classification"] or "UNEXPLAINED")
        out.append(r)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--org", type=int, required=True)
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    from app.database import SessionLocal

    rows = list(csv.DictReader(open(a.inp, encoding="utf8")))
    db = SessionLocal()
    try:
        result = compare(db, a.org, rows)
        db.rollback()                                           # read-only: nothing is ever committed
    finally:
        db.close()
    with open(a.out, "w", encoding="utf8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(result)
    unexplained = sum(1 for r in result if r["classification"] == "UNEXPLAINED")
    print(f"{len(result)} rows · {unexplained} UNEXPLAINED · "
          f"{sum(1 for r in result if r['classification'] == 'MANUAL_REVIEW')} MANUAL_REVIEW")
    return 1 if unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
