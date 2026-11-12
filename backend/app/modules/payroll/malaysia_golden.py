"""Malaysia golden check (ZP-MY-ENG-001 Phase 10; release gate G1).

Every MY_AUTHORITY_EXAMPLE row of a pack is one official (or independently
prepared) 2026 worked example — an EPF / PERKESO / EIS schedule example, an
HRD levy example or, once Phase 4 is built, a HASiL PCB test question — added
through the governed Super Admin console with a reviewed source document. It
is replayed through the pure engine with THAT pack's own canonical rows (so a
Draft pack can be checked before it is approved) and every expected figure
must match exactly — no tolerance.

An example is stored compactly in the row's tax_formula (150 characters):

    G=5000;D=2026-03-31;CLS=MY_PR_BELOW_60 => epfEe=550;epfEr=650;socsoEe=24.75;eisEe=9.90

  inputs    G     monthly basic wage (required)
            D     pay date (default: the pack's first day; the month is the period)
            CIT   CITIZEN / PERMANENT_RESIDENT / NON_CITIZEN (default CITIZEN)
            DOB   date of birth (default 1990-01-01)
            CLS   EPF member class (default MY_PR_BELOW_60)
            SOC   SOCSO category (default EI_AND_INVALIDITY)
            EIS   EIS state (default COVERED)
            HRD   HRD category (default COMPULSORY)
            T     labour territory (default PENINSULAR_LABUAN; holiday state follows)
  expected  any of EXPECTED_KEYS: epfEe / epfEr, socsoEe / socsoEr, eisEe /
            eisEr, hrd, pcb, net.

While PCB is blocked (the HASiL specification is not archived, Phase 4) the
engine still computes every other obligation: an example naming only
contribution figures is compared with those; one naming pcb or net fails
until PCB is built. The synthetic employee is a full-time contract-of-service
employee on monthly pay with a reviewed residence; nothing is read from or
written to any organisation.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Optional

from sqlalchemy.orm import Session

MAX_LENGTH = 150
INPUT_KEYS = ("G", "D", "CIT", "DOB", "CLS", "SOC", "EIS", "HRD", "T")
EXPECTED_KEYS = ("epfEe", "epfEr", "socsoEe", "socsoEr", "eisEe", "eisEr", "hrd", "pcb", "net")
CONTRIBUTION_KEYS = ("epfEe", "epfEr", "socsoEe", "socsoEr", "eisEe", "eisEr", "hrd")
_STATE_OF_TERRITORY = {"PENINSULAR_LABUAN": "SGR", "SABAH": "SBH", "SARAWAK": "SWK"}


def _amount(value: str, name: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError(f"{name} must be a number")


def parse_example(text: Optional[str]) -> dict:
    """{'inputs': {...}, 'expected': {...}} or ValueError naming what is wrong."""
    from app.modules.payroll.engine.countries import malaysia_content as content

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
    if "G" not in inputs:
        raise ValueError("input G is required")
    inputs["G"] = _amount(inputs["G"], "G")
    if inputs["G"] < 0:
        raise ValueError("G cannot be negative")
    choices = {"CIT": (content.CITIZENSHIP, "CITIZEN"), "CLS": (content.EPF_MEMBER_CLASSES, "MY_PR_BELOW_60"),
               "SOC": (content.SOCSO_CATEGORIES, "EI_AND_INVALIDITY"), "EIS": (content.EIS_STATES, "COVERED"),
               "HRD": (content.HRD_CATEGORIES, "COMPULSORY"), "T": (content.TERRITORIES, "PENINSULAR_LABUAN")}
    for key, (allowed, default) in choices.items():
        inputs[key] = inputs.get(key, default).upper()
        if inputs[key] not in allowed:
            raise ValueError(f"{key} must be one of {', '.join(allowed)}")
    for key, default in (("D", None), ("DOB", "1990-01-01")):
        if key in inputs or default:
            try:
                inputs[key] = date.fromisoformat(inputs.get(key, default))
            except ValueError:
                raise ValueError(f"{key} must be a date (YYYY-MM-DD)")
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
    from app.modules.payroll.engine.countries import malaysia_content as content

    i = spec["inputs"]
    pay_date = i.get("D") or default_pay_date
    start = date(pay_date.year, pay_date.month, 1)
    end = date(pay_date.year, pay_date.month, calendar.monthrange(pay_date.year, pay_date.month)[1])
    year_start = date(pay_date.year, 1, 1)
    foreign = i["CIT"] == "NON_CITIZEN"
    profile = SimpleNamespace(
        contract_type="CONTRACT_OF_SERVICE", pay_frequency="MONTHLY", citizenship=i["CIT"], date_of_birth=i["DOB"],
        tax_residence="NON_RESIDENT" if foreign else "RESIDENT",
        work_pass_type="EMPLOYMENT_PASS" if foreign else None, work_pass_valid_to=None,
        epf_member_class=i["CLS"], socso_category=i["SOC"], eis_state=i["EIS"], manual_worker=False,
        normal_hours_week=None, rest_day=None, service_start=year_start, status="ACTIVE",
        effective_from=year_start, effective_to=None)
    registration = SimpleNamespace(
        hrd_category=i["HRD"], hrd_category_from=year_start if i["HRD"] != "NOT_REGISTERED" else None,
        verification_state="VERIFIED", status="ACTIVE", effective_from=year_start, effective_to=None)
    assignment = SimpleNamespace(labour_territory=i["T"], holiday_state=_STATE_OF_TERRITORY[i["T"]], status="ACTIVE",
                                 effective_from=year_start, effective_to=None, id=0)
    gross = i["G"]
    return PayrollContext(
        gross=gross, basic=gross, country="MY", rate_map=rate_map, slabs=slabs, pay_date=pay_date,
        my_pay_date=pay_date, my_period_start=start, my_period_end=end, my_profile=profile,
        my_registration=registration, my_assignment=assignment, my_assignments=[assignment],
        my_components={"BASIC_SALARY": gross}, my_declarations=[],
        my_ytd={key: Decimal("0") for key in content.ACCUMULATORS}, my_organization_id=0, my_employee_id=0)


def _figures_from_result(result: dict) -> dict:
    def side(name, which):
        return Decimal(str((result.get(name) or {}).get(which) or "0"))

    return {"epfEe": side("my_epf", "employee"), "epfEr": side("my_epf", "employer"),
            "socsoEe": side("my_socso", "employee"), "socsoEr": side("my_socso", "employer"),
            "eisEe": side("my_eis", "employee"), "eisEr": side("my_eis", "employer"),
            "hrd": Decimal(str(result.get("my_hrd") or "0")), "pcb": Decimal(str(result.get("my_pcb") or "0")),
            "net": Decimal(str(result.get("my_net") or "0"))}


def _figures_from_partial(partial: dict) -> dict:
    """Contribution figures from a blocked calculation's trace (PCB pending)."""
    obligations = (partial or {}).get("obligations") or {}

    def side(name, which):
        value = (obligations.get(name) or {}).get(which)
        return Decimal(str(value)) if value not in (None, "") else Decimal("0")

    return {"epfEe": side("EPF", "employee"), "epfEr": side("EPF", "employer"),
            "socsoEe": side("SOCSO", "employee"), "socsoEr": side("SOCSO", "employer"),
            "eisEe": side("EIS", "employee"), "eisEr": side("EIS", "employer"), "hrd": side("HRD", "levy")}


def my_golden_check(db: Session, pack) -> dict:
    """Replay every MY_AUTHORITY_EXAMPLE row of `pack`. passed only when there is
    at least one example and every expected figure matches exactly."""
    from app.modules.payroll.engine.countries import malaysia as engine
    from app.modules.payroll.engine.countries import malaysia_content as content
    from app.modules.payroll.engine.jurisdictions.malaysia.errors import OBLIGATIONS_BLOCKED, MYCalculationBlockedError

    rate_map, slabs = _pack_rows(db, pack)
    examples = [s for s in slabs if (s.rule_type or "").upper() == content.MY_AUTHORITY_EXAMPLE_RULE]
    results = []
    for row in examples:
        name = row.filing_status or f"row {row.id}"
        entry = {"example": name, "rowId": row.id, "ok": False, "failures": [], "error": None, "partial": False}
        figures = None
        try:
            spec = parse_example(row.tax_formula)
            result = engine.calculate(example_context(spec, rate_map, slabs, pack.effective_from))["my_result"]
            figures = _figures_from_result(result)
        except ValueError as exc:
            entry["error"] = f"malformed example: {exc}"
        except MYCalculationBlockedError as exc:
            only_pcb = exc.key == OBLIGATIONS_BLOCKED and set(exc.blocked) == {"PCB"}
            if only_pcb and set(spec["expected"]) <= set(CONTRIBUTION_KEYS):
                figures, entry["partial"] = _figures_from_partial(exc.partial), True
            else:
                entry["error"] = str(exc)
        if figures is not None:
            for key, expected in spec["expected"].items():
                if figures[key] != expected:
                    entry["failures"].append({"field": key, "expected": str(expected), "actual": str(figures[key])})
            entry["ok"] = not entry["failures"]
        results.append(entry)
    return {"packId": pack.pack_id, "packRowId": pack.id, "examples": len(examples),
            "passed": bool(examples) and all(r["ok"] for r in results),
            "pcbProven": any(r["ok"] and not r["partial"] for r in results), "results": results}
