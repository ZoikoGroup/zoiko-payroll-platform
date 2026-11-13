"""Belgium golden check (ZP-BE-ENG-001 Block C2; spec §16 "Replay", gate G1).

Every BE_AUTHORITY_EXAMPLE row of a pack is one official (or independently
prepared) worked example, registered through the governed Super Admin console
with a reviewed source document (be_super_admin.add_authority_example). Its
replayable CASE is stored in the row's formula_expression:

    G=3500;D=2026-03-31;CAT=EMPLOYEE;EC=<cat>;WC=<code>;JC=<committee>;H=38 => wht=..;net=..

  inputs    G    gross for the month (required)
            EC   ONSS employer category, WC ONSS worker code (required; codes
                 from the signed code lists)
            D    pay date (default: the pack's first day)
            CAT  EMPLOYEE / MANUAL (default EMPLOYEE)
            H    contractual weekly hours (default: none -> the engine decides)
            JC   Joint Committee (required: the engine blocks without one)
  expected  any of EXPECTED_KEYS: wht (professional withholding), onssEe
            (employee ONSS after the social work bonus), workBonus (social work
            bonus), employer (employer contributions), net

The example is replayed through the pure engine with THAT pack's canonical rows
(a Draft pack can be checked before approval); every expected figure must
match exactly — no tolerance. The synthetic worker is a resident, salaried,
indefinite-contract worker with no declarations and nothing earned earlier;
nothing is read from or written to any organisation.

record_be_golden_certification() writes the outcome as the shared
TestCertificationRun of jurisdiction BE (the certification the activation path
reads); be_pack_activation_refusal requires the live check AND the latest BE
certification run to PASS.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

INPUT_KEYS = ("G", "D", "CAT", "EC", "WC", "H", "JC")
EXPECTED_KEYS = ("wht", "onssEe", "workBonus", "employer", "net")
CATEGORIES = ("EMPLOYEE", "MANUAL")
MAX_LENGTH = 400


def _amount(value: str, name: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError(f"{name} must be a number")


def be_parse_example(text: Optional[str]) -> dict:
    """{'inputs': {...}, 'expected': {...}} or ValueError naming what is wrong."""
    text = (text or "").strip()
    if not text:
        raise ValueError("the example has no replayable case (inputs => expected)")
    if len(text) > MAX_LENGTH:
        raise ValueError(f"a case is at most {MAX_LENGTH} characters")
    if "=>" not in text:
        raise ValueError("a case is 'inputs => expected'")
    left, right = (part.strip() for part in text.split("=>", 1))

    def pairs(part, allowed, what):
        out = {}
        for item in filter(None, (p.strip() for p in part.split(";"))):
            key, sep, value = item.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or not value:
                raise ValueError(f"'{item}' is not KEY=VALUE")
            if key not in allowed:
                raise ValueError(f"unknown {what} '{key}' (allowed: {', '.join(allowed)})")
            out[key] = value
        return out

    inputs = pairs(left, INPUT_KEYS, "input")
    expected = pairs(right, EXPECTED_KEYS, "expected figure")
    for key in ("G", "EC", "WC", "JC"):
        if key not in inputs:
            raise ValueError(f"input {key} is required")
    inputs["G"] = _amount(inputs["G"], "G")
    if inputs["G"] < 0:
        raise ValueError("G cannot be negative")
    inputs["CAT"] = inputs.get("CAT", "EMPLOYEE").upper()
    if inputs["CAT"] not in CATEGORIES:
        raise ValueError(f"CAT must be one of {', '.join(CATEGORIES)}")
    inputs["EC"], inputs["WC"] = inputs["EC"].upper(), inputs["WC"].upper()
    if "H" in inputs:
        inputs["H"] = _amount(inputs["H"], "H")
    if "D" in inputs:
        try:
            inputs["D"] = date.fromisoformat(inputs["D"])
        except ValueError:
            raise ValueError("D must be a date (YYYY-MM-DD)")
    if not expected:
        raise ValueError("at least one expected figure is required")
    return {"inputs": inputs, "expected": {k: _amount(v, k) for k, v in expected.items()}}


def _be_golden_pack_rows(db: Session, pack) -> tuple:
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None)).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .order_by(TaxSlab.sort_order, TaxSlab.id).all())
    return {r.component_key: r for r in rates}, slabs


def be_example_context(spec: dict, rate_map: dict, slabs: list, default_pay_date: date, pack_version: str = None):
    from app.modules.payroll.engine.base import PayrollContext

    inputs = spec["inputs"]
    pay_date = inputs.get("D") or default_pay_date
    start = date(pay_date.year, 1, 1)
    gross = inputs["G"]
    registration = {"id": 0, "legal_entity_id": None, "status": "ACTIVE", "verification_state": "VERIFIED",
                    "employer_category_code": inputs["EC"], "onss_special_160_status": "NOT_APPLICABLE",
                    "effective_from": start, "effective_to": None}
    profile = {"id": 0, "status": "ACTIVE", "worker_category": inputs["CAT"], "onss_worker_code": inputs["WC"],
               "residency": "RESIDENT", "special_status": None, "pay_basis": "SALARIED", "effective_from": start,
               "effective_to": None}
    classification = {"id": 0, "employment_line": "MAIN", "status": "ACTIVE", "joint_committee": inputs.get("JC"),
                      "sub_committee": None, "collective_agreement_id": None, "function_class": None,
                      "seniority_months": None, "establishment_unit_id": None,
                      "work_schedule_id": 0 if "H" in inputs else None, "contract_type": "INDEFINITE",
                      "effective_from": start, "effective_to": None}
    schedules = ([{"id": 0, "status": "ACTIVE", "regime": "EFFECTIVE", "weekly_hours": str(inputs["H"]),
                   "effective_from": start, "effective_to": None}] if "H" in inputs else [])
    return PayrollContext(
        gross=gross, basic=gross, country="BE", rate_map=rate_map, slabs=slabs, pay_date=pay_date,
        be_pay_date=pay_date, be_components=None, be_registration=registration, be_profile=profile,
        be_classifications=[classification], be_schedules=schedules, be_agreements={}, be_units={},
        be_declarations=[], be_pay_frequency="Monthly", be_component_mappings={"PLATFORM_FIELD:basic": "SALARY"},
        be_ytd={}, be_pack_version=pack_version, be_organization_id=0, be_date_of_birth=None)


def _be_golden_figures(result: dict) -> dict:
    return {"wht": Decimal(str(result["be_withholding"])), "onssEe": Decimal(str(result["be_employee_total"])),
            "workBonus": Decimal(str(result["be_social_work_bonus"])),
            "employer": Decimal(str(result["be_employer_total"])), "net": Decimal(str(result["be_net"]))}


def be_golden_check(db: Session, pack) -> dict:
    """Replay every BE_AUTHORITY_EXAMPLE row of `pack`. passed only when there
    is at least one example and every expected figure matches exactly."""
    from app.modules.payroll.engine.countries import belgium as engine
    from app.modules.payroll.engine.countries import belgium_content as content
    from app.modules.payroll.engine.jurisdictions.belgium.errors import BECalculationBlockedError

    rate_map, slabs = _be_golden_pack_rows(db, pack)
    examples = [s for s in slabs if (s.rule_type or "").upper() == content.AUTHORITY_EXAMPLE_RULE]
    results = []
    for row in examples:
        name = row.filing_status or f"row {row.id}"
        entry = {"example": name, "rowId": row.id, "ok": False, "failures": [], "error": None,
                 "signed": content.PENDING_MARK not in (row.rate_label or "")}
        try:
            spec = be_parse_example(row.formula_expression)
            ctx = be_example_context(spec, rate_map, slabs, pack.effective_from, f"{pack.pack_id}@{pack.version}")
            result = engine.calculate(ctx)["be_result"]
        except ValueError as exc:
            entry["error"] = f"malformed example: {exc}"
        except BECalculationBlockedError as exc:
            entry["error"] = str(exc)
        else:
            figures = _be_golden_figures(result)
            for key, expected in spec["expected"].items():
                if figures[key] != expected:
                    entry["failures"].append({"field": key, "expected": str(expected), "actual": str(figures[key])})
            entry["ok"] = not entry["failures"] and entry["signed"]
            if not entry["signed"]:
                entry["error"] = "the example row is not signed (gate G1)"
        results.append(entry)
    return {"packId": pack.pack_id, "packRowId": pack.id, "examples": len(examples),
            "passed": bool(examples) and all(r["ok"] for r in results), "results": results}


def record_be_golden_certification(db: Session, pack, actor_id=None):
    """Run the check and store it as the shared TestCertificationRun of BE
    (PASS / FAIL / NO_REAL_CASES)."""
    from app.modules.payroll.models import TestCertificationRun

    check = be_golden_check(db, pack)
    failures = [{"case": r["example"], "diffs": r["failures"] or [{"field": "error", "expected": "",
                                                                    "actual": r["error"] or ""}]}
                for r in check["results"] if not r["ok"]]
    total = check["examples"]
    status = "NO_REAL_CASES" if total == 0 else ("PASS" if not failures else "FAIL")
    run = TestCertificationRun(triggered_by_id=actor_id, jurisdiction_country="BE", real_case_count=total,
                               total_cases=total, passed_cases=total - len(failures), failed_cases=len(failures),
                               status=status, failure_details=failures or None)
    db.add(run)
    db.flush()
    return run, check


def be_latest_certification(db: Session):
    from app.modules.payroll.models import TestCertificationRun as T

    return (db.query(T).filter(T.jurisdiction_country == "BE").order_by(T.run_at.desc(), T.id.desc()).first())


def be_golden_refusal(db: Session, pack) -> Optional[str]:
    """Why the golden certification does not allow activating `pack`, or None."""
    check = be_golden_check(db, pack)
    if not check["passed"]:
        bad = [r["example"] for r in check["results"] if not r["ok"]]
        return (f"Belgium pack {pack.pack_id}: the authority examples do not replay exactly "
                + (f"({', '.join(bad[:5])})" if bad else "(none is registered)") + " — gate G1.")
    run = be_latest_certification(db)
    if run is None or run.status != "PASS":
        return (f"Belgium pack {pack.pack_id}: the latest Belgian golden-vector certification run is "
                f"{getattr(run, 'status', 'missing')}; run the certification first.")
    return None
