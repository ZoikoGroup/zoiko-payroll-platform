"""D-01 what-if: the X2 sandbox on the real Draft packs, scratch SQLite only.
Prints a JSON table of the §21 fixtures under each D-01 reading (D-03 held at
GENERAL, as the sandbox tests do). SYNTHETIC inputs; nothing is a decision."""
import json
import os
import sys

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, url
BACKEND = r"D:\zoiko_payroll_platform\Zoiko-payroll-platform\backend"
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from app.database import SessionLocal, initialize_database  # noqa: E402

initialize_database()
from app.modules.payroll import mexico_decision_service, mexico_sandbox_service  # noqa: E402
from scripts.seed_mexico_canonical_packs import seed_mexico  # noqa: E402

db = SessionLocal()
seed_mexico(db)
mexico_decision_service.seed_decisions(db)
db.commit()

BASE = {"payDate": "2026-06-15", "periodStart": "2026-06-01", "periodEnd": "2026-06-15", "dailySalary": "600",
        "zone": "GENERAL", "workState": "CDMX", "payFrequencyCode": "04", "seniorityDate": "2026-01-01"}
FIXTURES = [
    ("F1 Jan (UMA 113.14), 600/day", {"payDate": "2026-01-15", "periodStart": "2026-01-01", "periodEnd": "2026-01-15"}),
    ("F1 Feb (UMA 117.31), 600/day", {"payDate": "2026-02-15", "periodStart": "2026-02-01", "periodEnd": "2026-02-15"}),
    ("F2 first-year SBC, 600/day", {}),
    ("F3 CEAV high band, 1000/day", {"dailySalary": "1000"}),
    ("F4 general zone, 400/day", {"dailySalary": "400"}),
    ("F4 ZLFN, 400/day", {"dailySalary": "400", "zone": "ZLFN"}),
    ("F4 ZLFN, 500/day", {"dailySalary": "500", "zone": "ZLFN"}),
]
READINGS = [None, "HALF_UP:0.01", "HALF_EVEN:0.01", "HALF_DOWN:1"]
out = []
for reading in READINGS:
    for name, over in FIXTURES:
        cands = [] if reading is None else [{"decision": "D-01", "value": reading},
                                            {"decision": "D-03", "value": "GENERAL"}]
        r = mexico_sandbox_service.run_mx_sandbox(db, {**BASE, **over, "candidates": cands})
        row = {"reading": reading or "(none)", "fixture": name, "outcome": r["outcome"], "marks": r["watermarks"]}
        if r["outcome"] == "CALCULATED":
            res = r["result"]["mx_result"]
            row.update({k: str(res.get(k)) for k in ("gross", "isr_withheld", "imss_employee", "imss_employer",
                                                      "infonavit_employer", "employer_total")})
            row["subsidy_applied"] = str((res.get("subsidy") or {}).get("applied"))
            row["isn"] = str((res.get("isn") or {}).get("amount"))
            row["net"] = str(r["result"].get("net_pay", r["result"].get("net")))
        else:
            row["block"] = r["block"]["code"]
        out.append(row)
db.rollback()
print(json.dumps(out, ensure_ascii=False, indent=0))
