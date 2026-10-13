"""G1 evidence: export every Hong Kong governed value (each HK pack) to a worksheet CSV.

    python -m scripts.hk_export_g1_worksheet <out.csv>

Read-only (the session is switched to default_transaction_read_only before any
query). Values come from hong_kong_service.domains() — exactly what the Super
Admin Statutory Configuration tab shows. The "source_document_sha256" column is
left blank on purpose: it is filled when the team archives the exact official
PDF (scripts/hk_archive_authority_documents.py). Rows flagged UNVERIFIED — G1 or
SOURCE_HASH_REQUIRED need the Hong Kong specialist / a hashed source; nothing
here marks anything verified."""
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from app.database import SessionLocal
from app.modules.payroll import hong_kong_service
from app.modules.payroll.models import JurisdictionPack

OUT = sys.argv[1]

# Wireframe v1.0 evidence register S1–S10, matched on the archived source's agency + title.
RULES = [
    ("S2", lambda a, t: "IRD" in a.upper() or "Inland Revenue" in a, ("computerized", "computerised", "electronic", "xml")),
    ("S1", lambda a, t: "Inland Revenue" in a, ("employer", "bir56a", "ir56", "leave hong kong", "pam 46")),
    ("S4", lambda a, t: "MPF" in a or "Mandatory Provident" in a, ("empf",)),
    ("S3", lambda a, t: "Mandatory Provident" in a or "MPF" in a, ("",)),
    ("S8", lambda a, t: "Labour" in a, ("offsetting",)),
    ("S6", lambda a, t: "Labour" in a or "specialist" in a.lower(), ("continuous contract", "continuous-contract", "'week'", "468")),
    ("S5", lambda a, t: True, ("smw", "minimum wage")),
    ("S9", lambda a, t: "Labour" in a, ("compensation",)),
    ("S7", lambda a, t: "Labour" in a, ("concise guide", "holiday", "wages", "rest day", "leave", "sickness", "maternity",
                                         "paternity", "severance", "average wage", "application")),
    ("S10", lambda a, t: "PCPD" in a or "Privacy" in a, ("",)),
]


def authority_id(src):
    if not src:
        return "NONE (no source linked)"
    a, t = src.get("agency") or "", (src.get("title") or "").lower()
    for sid, agency_ok, words in RULES:
        if agency_ok(a, t) and any(w in t for w in words):
            return sid
    return f"outside S1–S10 ({a})"


db = SessionLocal()
if db.bind.dialect.name == "postgresql":
    db.execute(text("SET SESSION default_transaction_read_only = on"))
    db.commit()
packs = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "HK").order_by(JurisdictionPack.effective_from).all()
rows, totals = [], {}
for p in packs:
    d = hong_kong_service.domains(db, p.id)
    for dom in d["domains"]:
        for r in dom["rows"]:
            src = r["source"] or {}
            flag = ("SOURCE_HASH_REQUIRED" if r["status"] == "SOURCE_HASH_REQUIRED" else
                    "UNVERIFIED — G1" if r["status"].startswith("UNVERIFIED") else "")
            rows.append({
                "pack": f"{p.pack_id} v{p.version}", "pack_status": p.status, "domain": dom["label"],
                "row_kind": r["kind"], "row_id": r["id"], "key": r["key"], "label": r["label"], "value": r["value"],
                "unit": r["unit"], "effective_from": r["effectiveFrom"], "effective_to": r["effectiveTo"],
                "authority_source_id": authority_id(src), "source_agency": src.get("agency", ""),
                "source_title": src.get("title", ""), "source_url": src.get("url", ""),
                "platform_recorded_sha256": src.get("sha256") or "",
                "platform_status": r["status"], "flag": flag,
                "source_document_sha256": "",  # filled once the team archives the exact PDF (G2 archiving script)
                "review_status": "internally reviewed – pending approval" if not flag else "PENDING – specialist / source",
            })
    # General holidays (MPF contribution-day deferral): an EMPTY year is an open
    # G1 item, so it is listed explicitly rather than disappearing from the sheet.
    loaded_years = {int(r["raw"]["taxFormula"][:4]) for dom in d["domains"]
                    for r in dom["rows"] if r["key"] == "HK_GENERAL_HOLIDAY"}
    for y in range(p.effective_from.year, p.effective_to.year + 1):
        if y not in loaded_years:
            rows.append({
                "pack": f"{p.pack_id} v{p.version}", "pack_status": p.status, "domain": "Leave & Holidays",
                "row_kind": "open-item", "row_id": "", "key": "HK_GENERAL_HOLIDAY",
                "label": f"General holidays {y} — list not loaded (MPF contribution-day deferral)",
                "value": "(not loaded)", "unit": "dates", "effective_from": f"{y}-01-01", "effective_to": f"{y}-12-31",
                "authority_source_id": "SOURCE_REQUIRED (official general-holiday list)", "source_agency": "",
                "source_title": "", "source_url": "", "platform_recorded_sha256": "",
                "platform_status": "SOURCE_REQUIRED", "flag": "UNVERIFIED / SOURCE_REQUIRED",
                "source_document_sha256": "",
                "review_status": "PENDING – load with scripts/hk_load_general_holidays.py from the archived list",
            })
    totals[f"{p.pack_id} v{p.version}"] = d["total"]
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
digest = hashlib.sha256(open(OUT, "rb").read()).hexdigest()
summary = {"ranAt": datetime.now(timezone.utc).isoformat(), "packs": totals, "rows": len(rows),
           "flagged": {k: sum(1 for r in rows if r["flag"] == k)
                       for k in ("UNVERIFIED — G1", "SOURCE_HASH_REQUIRED", "UNVERIFIED / SOURCE_REQUIRED")},
           "flaggedByPack": {pk: {k: sum(1 for r in rows if r["pack"] == pk and r["flag"] == k)
                                  for k in ("UNVERIFIED — G1", "SOURCE_HASH_REQUIRED")} for pk in totals},
           "authorityCounts": {}, "csvSha256": digest}
for r in rows:
    summary["authorityCounts"][r["authority_source_id"]] = summary["authorityCounts"].get(r["authority_source_id"], 0) + 1
print(json.dumps(summary, ensure_ascii=False, indent=1))
