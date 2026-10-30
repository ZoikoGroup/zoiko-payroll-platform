"""
ZP-ZA-ENG-001 §13-§14 release gates G0-G7. Read-only: nothing here signs a gate,
records a decision or changes content. A gate is SIGNED only by an uploaded
evidence file reviewed by a Super Admin other than its uploader.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.modules.payroll import south_africa_service

REPO_ROOT = Path(__file__).resolve().parents[4]


ZA_GATES = (
    ("G0", "Architecture"),
    ("G1", "Statutory content"),
    ("G2", "Labour & onboarding"),
    ("G3", "Filing / reconciliation"),
    ("G4", "Payments / accounting"),
    ("G5", "Security / privacy"),
    ("G6", "QA"),
    ("G7", "Production"),
)
GATE_DEFINITIONS = {
    "G0": "Country capability assessment, interfaces, data model, rule-pack contract, no duplicated country logic",
    "G1": "Signed 2026/27 pack: PAYE, rebates, MTC, retirement, travel, UIF, SDL, ETI, directives, source codes, BRS, filing dates, statutory fixtures. Zero unresolved production candidates",
    "G2": "Supported cohort; BCEA/NMW/sector applicability; payslip/deduction/leave/final-pay matrix; unsupported cases explicitly blocked",
    "G3": "BRS-conformant export; EMP201/EMP501/IRP5 balancing; e@syFile/eFiling operator runbook; rejection/correction evidence; 2026 interim rehearsal",
    "G4": "Bank connector validation, beneficiary controls, payment-state reconciliation, balanced journals, failed/returned payment recovery",
    "G5": "POPIA posture, access controls, secrets/encryption, logging minimisation, retention/data-location decision, incident and disaster-recovery tests",
    "G6": "Automated suites + reviewer golden fixtures + two parallel cycles; no unexplained material difference; regression on historic packs/BRS versions",
    "G7": "Runbook, monitoring, support ownership, customer implementation checklist, rollback/freeze plan, signed go-live record",
}
GATE_OWNERS = {
    "G0": "Engineering lead",
    "G1": "Payroll/Tax lead + SA reviewer",
    "G2": "Product + Legal/Implementation",
    "G3": "Tax Ops",
    "G4": "Finance + Treasury",
    "G5": "Security + Privacy",
    "G6": "QA lead",
    "G7": "CTO + Product + Tax Ops",
}
NO_GO = (
    "the current SARS deduction algorithm and test tables",
    "UIF/SDL/ETI eligibility semantics",
    "source-code/BRS validation",
    "the tax-directive workflow",
    "reconciliation balancing",
    "mandatory tax-reference handling",
    "sector/bargaining scope",
    "POPIA/data-location posture",
    "bank/payment recovery",
    "independent payroll/tax sign-off",
)
RELEASE_GATES_DIR = REPO_ROOT / "docs" / "south-africa" / "release-gates"

_CHECKLIST_ITEM = re.compile(r"^- \[[ xX]\] (?:\*\*\[(?P<phase>[A-Z -]+)\]\*\* )?(?P<text>.*?)"
                              r"(?: <!-- code: (?P<code>[a-z0-9_]+) -->)?\s*$")


def _plain_markdown(text: str) -> str:
    return re.sub(r"\*\*|`", "", text).strip()


def gate_states(db: Session) -> list:
    out = []
    for key, label in ZA_GATES:
        accepted, submitted = south_africa_service._evidence(db, f"ZA-GATE-{key}")
        out.append({
            "gate": key,
            "label": label,
            "owner": GATE_OWNERS[key],
            "definition": GATE_DEFINITIONS[key],
            "state": "SIGNED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
            "evidenceTag": f"ZA-GATE-{key}",
            "artifactId": accepted.id if accepted else None,
            "checklist": f"docs/south-africa/release-gates/{key}/CHECKLIST.md",
        })
    return out


# key -> (gates, informational). Informational checks are shown but never block GA.
CODE_CHECKS = {
    "pack_seeded": ("G1", False),
    "pack_no_pending_g1": ("G1", False),
    "content_no_pending_g1": ("G1", False),
    "empty_by_design_resolved": ("G1/G2", False),
    "earning_class_no_review": ("G1", False),
    "brs_catalog_present": ("G1/G3", False),
    "golden_pass": ("G1/G6", False),
    "unsupported_blocked": ("G2", False),
    "holiday_calendar": ("G3", True),
    "journal_accounts_configured": ("G4", True),
    "bank_connector": ("G4", False),
    "parallel_cycles": ("G6", False),
    "onboarding_flag": ("G7", True),
}


def _pack(db: Session):
    from app.modules.payroll.engine.countries import south_africa_content as content
    from app.modules.payroll.models import JurisdictionPack

    return (db.query(JurisdictionPack)
            .filter(JurisdictionPack.jurisdiction_country == south_africa_service.ZA,
                    JurisdictionPack.pack_type == "tax", JurisdictionPack.pack_id == content.ZA_2027[0])
            .order_by(JurisdictionPack.version.desc()).first())


def code_checks(db: Session) -> dict:
    """key -> (met, detail): what the platform can prove itself, evaluated now."""
    from app.modules.payroll import south_africa_dormancy, south_africa_lifecycle, south_africa_parallel
    from app.modules.payroll.engine.countries import south_africa_content as content
    from app.modules.payroll.models import PayrollZaEmployerRegistration, TestCertificationRun

    out = {}
    pack = _pack(db)
    if pack is not None:
        out["pack_seeded"] = (True, f"{pack.pack_id} v{pack.version} is seeded ({pack.status})")
        refusal = south_africa_service.za_activation_evidence_refusal(db, pack)
        out["pack_no_pending_g1"] = (refusal is None, refusal or "no pack row is PENDING G1")
    else:
        out["pack_seeded"] = (False, f"no {content.ZA_2027[0]} tax pack is seeded "
                                     "(scripts/seed_south_africa_canonical_packs.py has not run)")
        out["pack_no_pending_g1"] = (False, "no ZA pack is seeded, so its rows cannot be checked")

    pending = sorted(r[0] for r in content.ZA_SCALAR_CONTENT if r[7] is True)
    out["content_no_pending_g1"] = (
        (False, f"{len(pending)} content row(s) still PENDING_G1, e.g. {', '.join(pending[:4])}") if pending
        else (True, "no content row is PENDING_G1"))

    values = {r[0]: r for r in content.ZA_SCALAR_CONTENT}
    empty = sorted(k for k in content.ZA_EMPTY_BY_DESIGN if all(values[k][i] in (None, "") for i in (2, 3, 4, 5)))
    d6 = next((d["state"] for d in south_africa_service.owner_decisions(db) if d["key"] == "D-6"), "OPEN")
    if not empty:
        out["empty_by_design_resolved"] = (True, "every deliberately empty row now has a value")
    elif d6 == "RECORDED":
        out["empty_by_design_resolved"] = (True, f"decision D-6 is RECORDED for the {len(empty)} row(s) left empty")
    else:
        out["empty_by_design_resolved"] = (False, f"{len(empty)} row(s) have no value and decision D-6 is {d6}: "
                                                  f"{', '.join(empty)}")

    review = sorted(f"{r[0]}:{r[2]}" for r in content.ZA_EARNING_CLASSES if r[1] == "REVIEW")
    out["earning_class_no_review"] = (
        (False, f"{len(review)} earning-class row(s) still REVIEW, e.g. {', '.join(review[:4])}") if review
        else (True, "no earning-class row is REVIEW"))

    version = values["za_brs_version"][5] if "za_brs_version" in values else None
    catalog = content.ZA_BRS_CATALOG.get(version) or {}
    out["brs_catalog_present"] = (
        (True, f"BRS v{version} catalogue has {len(catalog['source_codes'])} source code(s)")
        if catalog.get("source_codes")
        else (False, f"the SARS PAYE BRS v{version} source-code catalogue is empty - IRP5 / EMP501 export is "
                     "blocked"))

    fixtures = len([f for f in (REPO_ROOT / "backend" / "tests" / "fixtures" / "za_golden").glob("*.json")
                    if not f.name.startswith("_")])
    run = (db.query(TestCertificationRun).filter(TestCertificationRun.jurisdiction_country == south_africa_service.ZA)
           .order_by(TestCertificationRun.id.desc()).first())
    if run is None:
        out["golden_pass"] = (False, "no ZA golden certification run exists")
    elif run.status != "PASS":
        out["golden_pass"] = (False, f"the newest ZA golden certification run is {run.status}")
    elif fixtures and run.total_cases != fixtures:
        out["golden_pass"] = (False, f"the newest PASS covered {run.total_cases} case(s) but {fixtures} golden "
                                     "fixtures exist - re-run the certification")
    else:
        out["golden_pass"] = (True, f"the newest ZA golden certification PASSED {run.total_cases} case(s)")

    supported = values["za_supported_pay_frequencies"][5] if "za_supported_pay_frequencies" in values else None
    out["unsupported_blocked"] = (
        (True, "only MONTHLY pay is certified; weekly / fortnightly, non-residents, non-standard employment and "
               "SEZ ETI block in the engine") if supported == "MONTHLY"
        else (False, f"za_supported_pay_frequencies is {supported!r}, not MONTHLY - the certified cohort widened "
                     "without a G2 review"))

    year = datetime.date.today().year
    counts = {y: len(south_africa_lifecycle.za_public_holidays(y)) for y in (year, year + 1)}
    out["holiday_calendar"] = (all(c >= 12 for c in counts.values()),
                               f"Public Holidays Act calendar: {counts[year]} day(s) in {year}, {counts[year + 1]} in "
                               f"{year + 1}; ad-hoc s2A days are added by hand")

    active = db.query(PayrollZaEmployerRegistration).filter(PayrollZaEmployerRegistration.status == "ACTIVE").all()
    mapped = sum(1 for r in active if r.za_journal_accounts)
    out["journal_accounts_configured"] = (bool(active) and mapped == len(active),
                                          f"{mapped} of {len(active)} ACTIVE employer registration(s) have a "
                                          "journal account map")

    out["bank_connector"] = (False, "no South African bank connector or payment-state integration exists "
                                    "(spec §10, ZA-021) - G4 cannot be met by code today")

    months = south_africa_parallel.accepted_cycle_months(db)
    out["parallel_cycles"] = (len(months) >= 2, f"{len(months)} pay month(s) with an ACCEPTED parallel cycle; "
                                                "two are required")

    enabled = south_africa_dormancy.onboarding_enabled()
    out["onboarding_flag"] = (not enabled, "ZA_TENANT_ONBOARDING_ENABLED is " + ("ON" if enabled else "off") +
                              " (deployment setting; never changed by code)")
    return out


def code_check_rows(db: Session) -> list:
    """code_checks as JSON rows for the API / UI."""
    return [{"key": key, "gates": CODE_CHECKS[key][0], "informational": CODE_CHECKS[key][1], "met": met,
             "detail": detail} for key, (met, detail) in code_checks(db).items()]


def gate_checklists(db: Session) -> dict:
    root = RELEASE_GATES_DIR
    states = {g["gate"]: g["state"] for g in gate_states(db)}
    results = None
    gates = []
    for key, label in ZA_GATES:
        path = root / key / "CHECKLIST.md"
        if not path.is_file():
            gates.append({"gate": key, "label": label, "state": states[key], "available": False, "items": []})
            continue
        items = []
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            gates.append({"gate": key, "label": label, "state": states[key], "available": False, "items": []})
            continue
        for line in text.splitlines():
            m = _CHECKLIST_ITEM.match(line)
            if not line.startswith("- [") or not m:
                continue
            item = {"phase": m.group("phase"), "text": _plain_markdown(m.group("text")), "code": m.group("code")}
            if item["code"]:
                if results is None:
                    results = code_checks(db)
                met, detail = results.get(item["code"], (False, f"unknown code check {item['code']}"))
                item.update(kind="code", met=met, detail=detail)
            else:
                signed = states[key] == "SIGNED"
                item.update(kind="evidence", met=signed,
                            detail="in the signed gate evidence" if signed else "awaits the gate's signed evidence")
            items.append(item)
        code_items = [i for i in items if i.get("kind") == "code"]
        gates.append({"gate": key, "label": label, "state": states[key], "available": True, "items": items,
                      "codeMet": sum(1 for i in code_items if i.get("met")), "codeTotal": len(code_items),
                      "evidenceItems": len(items) - len(code_items)})
    return {"gates": gates, "note": "Code items are evaluated now; evidence items are met only when the gate is SIGNED (uploaded evidence reviewed by a second Super Admin). Nothing here signs a gate."}


def ga_preconditions(db: Session) -> list:
    """General availability: every gate SIGNED, every launch-blocking decision
    RECORDED and every non-informational code check met."""
    out = [{"key": f"gate_{g['gate']}", "label": f"Gate {g['gate']} - {g['label']} signed",
            "met": g["state"] == "SIGNED", "detail": f"{g['evidenceTag']} is {g['state']}"} for g in gate_states(db)]
    out += [{"key": f"decision_{d['key']}", "label": f"Decision {d['key']} - {d['label']}",
             "met": d["state"] == "RECORDED", "detail": f"{d['evidenceTag']} is {d['state']}"}
            for d in south_africa_service.owner_decisions(db) if d["blocksLaunch"]]
    out += [{"key": f"code_{r['key']}", "label": r["key"].replace("_", " "), "met": r["met"], "detail": r["detail"]}
            for r in code_check_rows(db) if not r["informational"]]
    return out


def open_points() -> list:
    return [
        {"key": "7b_timing_basis", "gate": "G1", "item": "7B timing basis (za_variable_remuneration_basis, PENDING_G1). Any bonus or commission paid outside its earned period blocks.", "whereItBlocks": "G1"},
        {"key": "paye_tax_year_date_basis", "gate": "G1", "item": "PAYE tax-year date basis (za_paye_tax_year_date_basis, PENDING_G1).", "whereItBlocks": "G1"},
        {"key": "earning_classes_review", "gate": "G1", "item": "Earning classes still REVIEW (BONUS/COMMISSION/travel for UIF and SDL).", "whereItBlocks": "G1"},
        {"key": "bcea_multipliers_empty", "gate": "G1/G2", "item": "BCEA premium multipliers, damage limit and four-eyes thresholds (empty by design).", "whereItBlocks": "G1/G2, D-6"},
        {"key": "eti_offset_accounting", "gate": "G1/G4", "item": "ETI offset policy and accounting.", "whereItBlocks": "G1/G4, D-7"},
        {"key": "brs_catalog", "gate": "G1/G3", "item": "SARS PAYE BRS v25.3.0 source-code catalogue (empty; IRP5/EMP501 export blocked).", "whereItBlocks": "G1/G3"},
        {"key": "emp501_windows_tolerance", "gate": "G3", "item": "EMP501 windows and reconciliation tolerance (PENDING_G1).", "whereItBlocks": "G3"},
        {"key": "bank_change_history", "gate": "G4/G5", "item": "Bank-change history: the platform doesn't record it, so every ZA run carries a BANK_CHANGE_HISTORY_UNAVAILABLE exception.", "whereItBlocks": "G4/G5 dependency"},
        {"key": "adhoc_holidays", "gate": "G3", "item": "Ad-hoc s2A public holidays must be added to the calendar by hand.", "whereItBlocks": "G3"},
        {"key": "no_bank_connector", "gate": "G4", "item": "No bank connector or payment states.", "whereItBlocks": "G4"},
        {"key": "retention_deletion_datalocation", "gate": "G5", "item": "Retention and deletion decisions (D-1, D-2) and data location (D-5).", "whereItBlocks": "G5"},
        {"key": "two_parallel_cycles", "gate": "G6", "item": "Two parallel cycles plus a recorded materiality threshold (D-4).", "whereItBlocks": "G6"},
    ]
