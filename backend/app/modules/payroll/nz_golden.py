"""New Zealand golden check (ZP-NZ-ENG-001 Phase 9; AC-NZ-01, release gate G1).

Every NZ_IRD_EXAMPLE row of a pack is one Inland Revenue worked example. It is
replayed through the pure engine with THAT pack's own canonical rows (so a
Draft pack can be checked before it is approved) and every expected figure
must match exactly — no tolerance.

An example is stored compactly in the row's tax_formula (150 characters):

    F=FORTNIGHTLY;C=M SL;G=3000;D=2026-04-08;KS=3.5;ESCT=30;EB=80730 => payeTotal=653.29;studentLoan=248.64

  inputs    F   pay frequency (required)       C   tax code (required)
            G   gross for the period (required) D   payday (default: the pack's first day)
            KS  employee KiwiSaver rate %  (absent = not a member)
            ER  employer KiwiSaver rate %  ESCT / EB the ESCT rate % and its basis amount
                                               (both required with KS)
  expected  any of EXPECTED_KEYS (engine obligations, plus netPay)

The synthetic employee is a resident adult with an ACTIVE, verified employer;
nothing is read from or written to any organisation.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy.orm import Session

MAX_LENGTH = 150
INPUT_KEYS = ("F", "C", "G", "D", "KS", "ER", "ESCT", "EB")
EXPECTED_KEYS = ("paye", "accLevy", "payeTotal", "studentLoan", "ksEmployee", "ksEmployerGross", "esct",
                 "ksEmployerNet", "childSupport", "netPay")
_PERIOD_DAYS = {"WEEKLY": 7, "FORTNIGHTLY": 14, "FOUR_WEEKLY": 28, "MONTHLY": 30}


def _amount(value: str, name: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError(f"{name} must be a number")


def parse_example(text: Optional[str]) -> dict:
    """{'inputs': {...}, 'expected': {...}} or ValueError naming what is wrong."""
    from app.modules.payroll.engine.countries import new_zealand_content as content

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
    for key in ("F", "C", "G"):
        if key not in inputs:
            raise ValueError(f"input {key} is required")
    inputs["F"] = inputs["F"].upper()
    if inputs["F"] not in content.PAY_FREQUENCIES:
        raise ValueError(f"F must be one of {', '.join(content.PAY_FREQUENCIES)}")
    inputs["C"] = " ".join(inputs["C"].upper().split())
    if "KS" in inputs and not {"ESCT", "EB"} <= set(inputs):
        raise ValueError("ESCT and EB are required with KS")
    for key in ("G", "KS", "ER", "ESCT", "EB"):
        if key in inputs:
            inputs[key] = _amount(inputs[key], key)
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


def example_context(spec: dict, rate_map: dict, slabs: list, default_payday: date):
    from app.modules.payroll.engine.base import PayrollContext

    inputs = spec["inputs"]
    pay_date = inputs.get("D") or default_payday
    start = pay_date - timedelta(days=_PERIOD_DAYS[inputs["F"]] - 1)
    active = {"status": "ACTIVE", "effective_from": start - timedelta(days=365), "effective_to": None}
    tax_profile = {**active, "id": 0, "tax_code": inputs["C"], "tax_code_source": "IR330_DECLARATION",
                   "ird_number_state": "VALID", "residency_status": "RESIDENT", "min_wage_category": "ADULT",
                   "tailored_rate_pct": None, "tailored_valid_from": None, "tailored_valid_to": None,
                   "sl_certificate_type": None, "sl_certificate_ref": None, "sl_certificate_rate_pct": None,
                   "sl_certificate_valid_from": None, "sl_certificate_valid_to": None}
    member = "KS" in inputs
    kiwisaver = {**active, "id": 0, "membership_state": "CONTRIBUTING" if member else "NOT_MEMBER",
                 "employee_rate_pct": inputs.get("KS"), "employer_rate_pct": inputs.get("ER"),
                 "reduction_ref": None, "reduction_from": None, "reduction_to": None,
                 "employer_matches_reduction": False, "suspension_ref": None, "suspension_from": None,
                 "suspension_to": None, "esct_rate_pct": inputs.get("ESCT"), "esct_basis": "PRIOR_YEAR" if member else None,
                 "esct_basis_amount": inputs.get("EB"), "esct_tax_year": None, "employer_contribution_treatment": "ESCT",
                 "settlement_destination": "INLAND_REVENUE", "complying_fund_ref": None}
    employer = {**active, "id": 0, "legal_entity_id": None, "verification_state": "VERIFIED"}
    gross = inputs["G"]
    return PayrollContext(
        gross=gross, basic=gross, country="NZ", rate_map=rate_map, slabs=slabs, pay_frequency=inputs["F"],
        pay_date=pay_date, period_start=start, period_end=pay_date, nz_employer_profile=employer,
        nz_tax_profile=tax_profile, nz_kiwisaver=kiwisaver, nz_authority_deductions=[],
        nz_accumulators={"ACC_LIABLE_EARNINGS": Decimal("0")}, nz_hours=None, nz_hours_source=None,
        nz_date_of_birth=date(pay_date.year - 35, 1, 1), nz_organization_id=0)


def nz_golden_check(db: Session, pack) -> dict:
    """Replay every NZ_IRD_EXAMPLE row of `pack`. passed only when there is at
    least one example and every expected figure matches exactly."""
    from app.modules.payroll.engine.countries import new_zealand as engine
    from app.modules.payroll.engine.countries import new_zealand_content as content
    from app.modules.payroll.engine.jurisdictions.new_zealand.errors import NZCalculationBlockedError

    rate_map, slabs = _pack_rows(db, pack)
    examples = [s for s in slabs if (s.rule_type or "").upper() == content.NZ_IRD_EXAMPLE_RULE]
    results = []
    for row in examples:
        name = row.filing_status or f"row {row.id}"
        entry = {"example": name, "rowId": row.id, "ok": False, "failures": [], "error": None}
        try:
            spec = parse_example(row.tax_formula)
            result = engine.calculate(example_context(spec, rate_map, slabs, pack.effective_from))["nz_result"]
        except ValueError as exc:
            entry["error"] = f"malformed example: {exc}"
        except NZCalculationBlockedError as exc:
            entry["error"] = str(exc)
        else:
            figures = {**result["obligations"], "netPay": result["netPay"]}
            for key, expected in spec["expected"].items():
                actual = Decimal(str(figures.get(key) or "0"))
                if actual != expected:
                    entry["failures"].append({"field": key, "expected": str(expected), "actual": str(actual)})
            entry["ok"] = not entry["failures"]
        results.append(entry)
    return {"packId": pack.pack_id, "packRowId": pack.id, "examples": len(examples),
            "passed": bool(examples) and all(r["ok"] for r in results), "results": results}
