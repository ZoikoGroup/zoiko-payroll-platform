"""
Hong Kong production READ-ONLY verification (evidence for HK-PRODUCTION-VERIFICATION / G7).

    python -m scripts.hk_production_readonly_verification [--out report.json]

Run by a human operator on a host that already has production database access.
Guarantees:

* every statement is a SELECT (checked before it is sent) and the session is
  switched to default_transaction_read_only=on and SET TRANSACTION READ ONLY,
  so PostgreSQL itself refuses any write (session and transaction);
* aggregate facts only — counts, statuses, revision ids, digests. No employee,
  HKID, member-account, salary or credential value is read or printed;
* the report ends with the SHA-256 of its own canonical JSON, so the file the
  operator uploads as evidence can be matched to this run.

It does not change anything, activate anything or decide anything: a human
compares the facts with the expected values printed next to them.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from app.database import engine as app_engine

EXPECTED_ALEMBIC_HEAD = "b08f04497195"
_SELECT_ONLY = re.compile(r"^\s*SELECT\b", re.I)
_FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|CREATE|TRUNCATE|GRANT|REVOKE|COPY|CALL|DO)\b", re.I)

CHECKS = [
    ("alembic_version", "SELECT version_num FROM alembic_version ORDER BY version_num",
     f"exactly one row: {EXPECTED_ALEMBIC_HEAD}"),
    ("hk_service_registry", "SELECT availability FROM jurisdiction_service_registry WHERE country = 'HK'",
     "PLANNED until G1–G7 are accepted and launch is authorised"),
    ("hk_packs", "SELECT pack_id, version, status, effective_from, effective_to FROM payroll_jurisdiction_packs "
                 "WHERE jurisdiction_country = 'HK' ORDER BY effective_from, version",
     "Draft / Approved only — none Active before launch"),
    ("hk_templates_by_status", "SELECT status, count(*) AS n FROM payroll_report_templates "
                               "WHERE jurisdiction_country = 'HK' GROUP BY status ORDER BY status",
     "Draft only before launch"),
    ("hk_canonical_rows_without_source", "SELECT count(*) AS n FROM payroll_contribution_rates "
                                         "WHERE jurisdiction_country = 'HK' AND organization_id IS NULL "
                                         "AND source_document_id IS NULL",
     "0 before activation"),
    ("hk_certification_runs", "SELECT status, count(*) AS n, max(run_at) AS latest FROM payroll_test_certification_runs "
                              "WHERE jurisdiction_country = 'HK' GROUP BY status ORDER BY status",
     "a latest PASS before any pack activation"),
    ("hk_governed_evidence", "SELECT form_number, count(*) AS current_artifacts, "
                             "count(*) FILTER (WHERE file_path IS NOT NULL) AS with_file, "
                             "count(*) FILTER (WHERE reviewer_id IS NOT NULL AND reviewer_id <> created_by_id) AS independently_reviewed "
                             "FROM payroll_source_artifacts WHERE superseded_by_id IS NULL "
                             "AND (form_number LIKE 'HK-GATE-%' OR form_number LIKE 'HK-DECISION-%' "
                             "OR form_number = 'HK-PRODUCTION-VERIFICATION') GROUP BY form_number ORDER BY form_number",
     "each HK-GATE-G1..G7 and blocking HK-DECISION-D-1..D-11 independently reviewed before launch"),
    ("hk_tenant_workflow_rows", "SELECT 'payroll_hk_ird_reporting_cases' AS t, count(*) AS n FROM payroll_hk_ird_reporting_cases "
                                "UNION ALL SELECT 'payroll_hk_empf_submissions', count(*) FROM payroll_hk_empf_submissions "
                                "UNION ALL SELECT 'payroll_hk_termination_results', count(*) FROM payroll_hk_termination_results "
                                "UNION ALL SELECT 'payroll_hk_payslip_corrections', count(*) FROM payroll_hk_payslip_corrections "
                                "UNION ALL SELECT 'payroll_hk_tax_clearance_holds', count(*) FROM payroll_hk_tax_clearance_holds "
                                "UNION ALL SELECT 'payroll_hk_average_wage_snapshots', count(*) FROM payroll_hk_average_wage_snapshots "
                                "UNION ALL SELECT 'payroll_hk_work_hours', count(*) FROM payroll_hk_work_hours ORDER BY 1",
     "0 everywhere before launch (no HK tenant processing)"),
    ("hk_organizations", "SELECT count(*) AS n FROM organizations WHERE upper(coalesce(country, '')) IN ('HK', 'HONG KONG')",
     "informational — tenants configured for Hong Kong"),
]


def _guard(sql: str) -> None:
    if not _SELECT_ONLY.match(sql) or _FORBIDDEN.search(sql) or ";" in sql.strip().rstrip(";"):
        raise SystemExit(f"refusing a non-SELECT statement: {sql[:80]}")


def _plain(v):
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None and not isinstance(v, (int, float, str)) else v)


def run() -> dict:
    eng = app_engine
    report = {"script": "hk_production_readonly_verification", "ranAt": datetime.now(timezone.utc).isoformat(),
              "database": {"host": eng.url.host, "name": eng.url.database}, "checks": []}
    with eng.connect() as conn:
        conn.execute(text("SET SESSION default_transaction_read_only = on"))
        conn.commit()
        conn.execute(text("SET TRANSACTION READ ONLY"))
        report["transactionReadOnly"] = conn.execute(text("SHOW transaction_read_only")).scalar()
        for key, sql, expected in CHECKS:
            _guard(sql)
            rows = [{k: _plain(v) for k, v in r._mapping.items()} for r in conn.execute(text(sql))]
            report["checks"].append({"key": key, "expected": expected, "rows": rows})
        conn.rollback()
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
    report["reportSha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", help="write the JSON report here (default: stdout)")
    args = ap.parse_args(argv)
    report = run()
    if report["transactionReadOnly"] != "on":
        print("ABORT: session is not read-only", file=sys.stderr)
        return 2
    body = json.dumps(report, indent=1, default=str)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"written {args.out}  reportSha256={report['reportSha256']}")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
