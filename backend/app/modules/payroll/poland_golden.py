"""Poland golden check (ZP-PL-ENG-001 Phase 9; AC-PL-02, release gate G1).

Every PL_AUTHORITY_EXAMPLE row of a pack is one official (or independently
prepared) 2026 worked example, added through the governed Super Admin console
with a reviewed source document. It is replayed through the pure engine with
THAT pack's own canonical rows (so a Draft pack can be checked before it is
approved) and every expected figure must match exactly — no tolerance.

An example is stored compactly in the row's tax_formula (150 characters):

    G=8000;D=2026-03-31;PIT2=FULL;PPK=ENROLLED;AR=1.67 => pit=513;zusEe=1096.80;health=621.29;net=5608.91

  inputs    G     gross for the month (required)
            AR    the employer's accident-insurance rate % (required; employer-specific)
            D     pay date (default: the pack's first day)
            PIT2  FULL / HALF / THIRD / NONE (default NONE: no PIT-2 statement)
            PPK   ENROLLED / OPTED_OUT / NOT_ELIGIBLE (default NOT_ELIGIBLE)
            FUNDS Y / N — FP/FS and FGŚP apply (default Y)
  expected  any of EXPECTED_KEYS:
            pit (PIT advance), zusEe / zusEr (employee / employer ZUS),
            health, ppkEe / ppkEr, funds (FP/FS + FGŚP + FEP), net

The synthetic employee is a resident, full-time employee on umowa o pracę,
monthly pay, full ZUS coverage, no other titles, nothing earned earlier in
the year; nothing is read from or written to any organisation.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Optional

from sqlalchemy.orm import Session

MAX_LENGTH = 150
INPUT_KEYS = ("G", "AR", "D", "PIT2", "PPK", "FUNDS")
EXPECTED_KEYS = ("pit", "zusEe", "zusEr", "health", "ppkEe", "ppkEr", "funds", "net")
PIT2_CHOICES = ("FULL", "HALF", "THIRD", "NONE")
PPK_CHOICES = ("ENROLLED", "OPTED_OUT", "NOT_ELIGIBLE")


def _amount(value: str, name: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError(f"{name} must be a number")


def parse_example(text: Optional[str]) -> dict:
    """{'inputs': {...}, 'expected': {...}} or ValueError naming what is wrong."""
    text = (text or "").strip()
    if len(text) > MAX_LENGTH:
        raise ValueError(f"an example is at most {MAX_LENGTH} characters")
    if "=>" not in text:
        raise ValueError("an example is 'inputs => expected'")
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
    for key in ("G", "AR"):
        if key not in inputs:
            raise ValueError(f"input {key} is required")
    inputs["G"], inputs["AR"] = _amount(inputs["G"], "G"), _amount(inputs["AR"], "AR")
    if inputs["G"] < 0 or inputs["AR"] < 0:
        raise ValueError("G and AR cannot be negative")
    inputs["PIT2"] = inputs.get("PIT2", "NONE").upper()
    if inputs["PIT2"] not in PIT2_CHOICES:
        raise ValueError(f"PIT2 must be one of {', '.join(PIT2_CHOICES)}")
    inputs["PPK"] = inputs.get("PPK", "NOT_ELIGIBLE").upper()
    if inputs["PPK"] not in PPK_CHOICES:
        raise ValueError(f"PPK must be one of {', '.join(PPK_CHOICES)}")
    inputs["FUNDS"] = inputs.get("FUNDS", "Y").upper()
    if inputs["FUNDS"] not in ("Y", "N"):
        raise ValueError("FUNDS must be Y or N")
    if "D" in inputs:
        try:
            inputs["D"] = date.fromisoformat(inputs["D"])
        except ValueError:
            raise ValueError("D must be a date (YYYY-MM-DD)")
    if not expected:
        raise ValueError("at least one expected figure is required")
    return {"inputs": inputs, "expected": {k: _amount(v, k) for k, v in expected.items()}}


def _pack_rows(db: Session, pack) -> tuple:
    from app.modules.payroll.models import ContributionRate, TaxSlab

    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None)).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .order_by(TaxSlab.sort_order, TaxSlab.id).all())
    return {r.component_key: r for r in rates}, slabs


def example_context(spec: dict, rate_map: dict, slabs: list, default_pay_date: date):
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries import poland_content as content

    inputs = spec["inputs"]
    pay_date = inputs.get("D") or default_pay_date
    year_start = date(pay_date.year, 1, 1)
    gross = inputs["G"]
    profile = SimpleNamespace(
        contract_type="UMOWA_O_PRACE", pay_frequency="MONTHLY", tax_residency="RESIDENT", fte_numerator=1,
        fte_denominator=1, service_credit_months=None, cov_pension=True, cov_disability=True, cov_sickness=True,
        cov_accident=True, cov_health=True, other_titles_declared=False, a1_certificate=False, is_student=False,
        is_pensioner=False, fep_qualifying=False, fep_from=None, fep_to=None, fund_exemption_code=None,
        status="ACTIVE", effective_from=year_start, effective_to=None)
    funds = inputs["FUNDS"] == "Y"
    registration = SimpleNamespace(
        status="ACTIVE", effective_from=year_start, effective_to=None, accident_rate_pct=inputs["AR"],
        accident_rate_source="ZUS_NOTICE", accident_rate_from=year_start, accident_rate_to=None,
        fp_fs_applicable=funds, fgsp_applicable=funds, ppk_employer_additional_pct=None)
    declarations = []
    if inputs["PIT2"] != "NONE":
        declarations.append({"id": 0, "declaration_type": "PIT2", "status": "APPROVED", "effective_from": year_start,
                             "effective_to": None, "value": {"allocation": inputs["PIT2"]}})
    return PayrollContext(
        gross=gross, basic=gross, country="PL", rate_map=rate_map, slabs=slabs, pay_date=pay_date,
        pl_pay_date=pay_date, pl_profile=profile, pl_registration=registration, pl_components={"SALARY": gross},
        pl_declarations=declarations, pl_ppk=SimpleNamespace(state=inputs["PPK"]),
        pl_ytd={key: Decimal("0") for key in content.ACCUMULATORS}, pl_organization_id=0, pl_employee_id=0)


def _figures(result: dict) -> dict:
    def total(key):
        return sum((Decimal(str(v)) for v in (result.get(key) or {}).values()), Decimal("0"))

    return {"pit": Decimal(str(result["pl_pit_advance"])), "zusEe": total("pl_zus_employee"),
            "zusEr": total("pl_zus_employer"), "health": Decimal(str(result["pl_health"])),
            "ppkEe": total("pl_ppk_employee"), "ppkEr": total("pl_ppk_employer"), "funds": total("pl_funds"),
            "net": Decimal(str(result["pl_net"]))}


def pl_golden_check(db: Session, pack) -> dict:
    """Replay every PL_AUTHORITY_EXAMPLE row of `pack`. passed only when there is
    at least one example and every expected figure matches exactly."""
    from app.modules.payroll.engine.countries import poland as engine
    from app.modules.payroll.engine.countries import poland_content as content
    from app.modules.payroll.engine.jurisdictions.poland.errors import PLCalculationBlockedError

    rate_map, slabs = _pack_rows(db, pack)
    examples = [s for s in slabs if (s.rule_type or "").upper() == content.PL_AUTHORITY_EXAMPLE_RULE]
    results = []
    for row in examples:
        name = row.filing_status or f"row {row.id}"
        entry = {"example": name, "rowId": row.id, "ok": False, "failures": [], "error": None}
        try:
            spec = parse_example(row.tax_formula)
            result = engine.calculate(example_context(spec, rate_map, slabs, pack.effective_from))["pl_result"]
        except ValueError as exc:
            entry["error"] = f"malformed example: {exc}"
        except PLCalculationBlockedError as exc:
            entry["error"] = str(exc)
        else:
            figures = _figures(result)
            for key, expected in spec["expected"].items():
                if figures[key] != expected:
                    entry["failures"].append({"field": key, "expected": str(expected), "actual": str(figures[key])})
            entry["ok"] = not entry["failures"]
        results.append(entry)
    return {"packId": pack.pack_id, "packRowId": pack.id, "examples": len(examples),
            "passed": bool(examples) and all(r["ok"] for r in results), "results": results}
