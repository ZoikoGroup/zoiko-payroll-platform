"""Independent reference calculator for the Switzerland golden cases.

STANDALONE ON PURPOSE: this file imports nothing from `app` — standard
library only. Every expected figure in this directory's *.json files is
computed HERE, from the Swiss rules written out below, never copied from the
engine's output. A golden case is only meaningful when the arithmetic that
produced its expected value is independent of the code under test.

Run `python calc_reference.py --write` to (re)write the *.json cases; the test
suite (tests/test_switzerland_golden.py) also re-derives every expected value
from this module and fails if a fixture has drifted from it.

Statutory parameters (2026, typed from the published sources, NOT read from
switzerland_content.py):
  AHV 8.7 % (4.35 / 4.35), IV 1.4 % (0.70 / 0.70), EO 0.5 % (0.25 / 0.25)
  ALV 2.2 % (1.10 / 1.10) up to CHF 148,200 insured annual salary
  UVG max insured annual salary CHF 148,200; NBU compulsory from 8 h / week
  BVG Art. 2 / 7 / 8: entry threshold 22,680; insured ("coordinated") salary =
      annual salary CAPPED at 90,720 minus the 26,460 coordination deduction,
      raised to the 3,780 minimum
  FAK federal minimums: child CHF 215 / education CHF 268 per month
  Rounding: every amount to the nearest 5 Rappen (CHF 0.05), half up

Everything else — QST tariff tables, BVG / UVG / KTG plan rates, the
compensation-office admin cost, canton FAK amounts, wage floors — is
SYNTHETIC test data, defined below.
"""
import json
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal as D
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUNDRED = D("100")
ZERO = D("0")

# ── statutory 2026 parameters (published values) ────────────────────────
FEDERAL = {
    "ch_ahv": (D("4.35"), D("4.35")), "ch_iv": (D("0.70"), D("0.70")),
    "ch_eo": (D("0.25"), D("0.25")), "ch_alv": (D("1.10"), D("1.10")),
}
ALV_CEILING = D("148200")
UVG_CEILING = D("148200")
NBU_MIN_WEEKLY_HOURS = D("8")
BVG_ENTRY_THRESHOLD = D("22680")
BVG_COORDINATION_DEDUCTION = D("26460")
BVG_UPPER_SALARY = D("90720")
BVG_MIN_COORDINATED = D("3780")
FAK_MIN = {"CHILD": D("215"), "EDUCATION": D("268")}

# ── synthetic employer / canton data ────────────────────────────────────
ADMIN_COST_PCT = D("1.0")
FAK_EMPLOYER_PCT = D("1.2")
BVG_PLAN = [  # (component, age_from, age_to, employee_pct, employer_pct)
    ("MANDATORY", 18, 24, D("0"), D("0.5")),
    ("MANDATORY", 25, 34, D("3.5"), D("3.5")),
    ("MANDATORY", 35, 44, D("5"), D("5")),
    ("MANDATORY", 45, 54, D("7.5"), D("7.5")),
    ("MANDATORY", 55, 65, D("9"), D("9")),
]
UVG_RISK_CLASS = {"code": "A1", "bu_employer_pct": D("0.3"), "nbu_pct": D("0.9"), "nbu_employee_share_pct": D("100")}
CANTON_FAK = {"CH-ZH": {"CHILD": D("250"), "EDUCATION": D("300")},
              "CH-GE": {"CHILD": D("311"), "EDUCATION": D("415")}}
# QST tariff tables: code -> [(income_from, income_to or None, rate_pct, min_tax or None, row_id)]
QST_TARIFFS = {
    "CH-ZH": {"A0N": [(D("0"), D("5000"), D("2"), None, 101), (D("5000"), None, D("8"), None, 102)],
              "B0N": [(D("0"), D("5000"), D("1"), None, 103), (D("5000"), None, D("6"), None, 104)]},
    "CH-BE": {"A0N": [(D("0"), D("6000"), D("3"), None, 201), (D("6000"), None, D("9"), None, 202)]},
    # the ZH table as corrected by a later ESTV file (top band 8 % -> 7.5 %)
    "CH-ZH-CORRECTED": {"A0N": [(D("0"), D("5000"), D("2"), None, 301), (D("5000"), None, D("7.5"), None, 302)]},
}
GE_MINIMUM_HOURLY = D("24.00")


def r05(x: D) -> D:
    """Nearest 5 Rappen, half up."""
    return (D(x) * 20).quantize(D("1"), rounding=ROUND_HALF_UP) / 20


def age_on(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def coordinated_salary(annual: D) -> D:
    """BVG Art. 8: (min(annual, upper) - coordination deduction), at least the minimum."""
    return max(min(annual, BVG_UPPER_SALARY) - BVG_COORDINATION_DEDUCTION, BVG_MIN_COORDINATED)


def bvg(annual: D, dob: date, on: date):
    if annual < BVG_ENTRY_THRESHOLD or age_on(dob, on) < 17:
        return ZERO, ZERO
    age = age_on(dob, on)
    band = next(b for b in BVG_PLAN if b[0] == "MANDATORY" and b[1] <= age <= b[2])
    monthly = coordinated_salary(annual) / 12
    return r05(monthly * band[3] / HUNDRED), r05(monthly * band[4] / HUNDRED)


def qst_row(canton_table: str, code: str, income: D):
    for lo, hi, rate, min_tax, row_id in QST_TARIFFS[canton_table][code]:
        if income >= lo and (hi is None or income < hi):
            return rate, min_tax, row_id
    raise ValueError(f"no {code} band for {income} in {canton_table}")


def payslip(s: dict) -> dict:
    """Every figure of one Swiss monthly payslip, from first principles."""
    gross = sum((D(v) for v in s["earnings"].values()), ZERO)
    on = date.fromisoformat(s["pay_date"])
    out = {}
    ee_total = er_total = ZERO
    for key, (ee_pct, er_pct) in FEDERAL.items():
        base = gross
        if key == "ch_alv":
            base = min(gross, max(ZERO, ALV_CEILING - D(s.get("ytd_alv_wages", "0"))))
        ee, er = r05(base * ee_pct / HUNDRED), r05(base * er_pct / HUNDRED)
        out[f"{key}_employee"], out[f"{key}_employer"] = ee, er
        ee_total += ee
        er_total += er
    bvg_ee, bvg_er = bvg(D(s["annual_salary"]), date.fromisoformat(s["date_of_birth"]), on)
    out["ch_bvg_employee"], out["ch_bvg_employer"] = bvg_ee, bvg_er
    ee_total += bvg_ee
    er_total += bvg_er
    uvg_insurable = min(gross, max(ZERO, UVG_CEILING - D(s.get("ytd_uvg_wages", "0"))))
    bu = r05(uvg_insurable * UVG_RISK_CLASS["bu_employer_pct"] / HUNDRED)
    nbu_ee = nbu_er = ZERO
    if D(s["weekly_hours"]) >= NBU_MIN_WEEKLY_HOURS:
        ee_rate = UVG_RISK_CLASS["nbu_pct"] * UVG_RISK_CLASS["nbu_employee_share_pct"] / HUNDRED
        nbu_ee = r05(uvg_insurable * ee_rate / HUNDRED)
        nbu_er = r05(uvg_insurable * (UVG_RISK_CLASS["nbu_pct"] - ee_rate) / HUNDRED)
    out.update(ch_uvg_bu_employer=bu, ch_uvg_nbu_employee=nbu_ee, ch_uvg_nbu_employer=nbu_er)
    ee_total += nbu_ee
    er_total += bu + nbu_er
    qst_total = ZERO
    if s.get("qst"):
        q = s["qst"]
        rate, min_tax, _row = qst_row(q["table"], q["code"], gross)
        tax = gross * rate / HUNDRED
        if min_tax is not None and tax < min_tax:
            tax = min_tax
        qst_total = r05(tax)
    out["ch_qst_total"] = qst_total
    ee_total += qst_total
    admin = r05(gross * ADMIN_COST_PCT / HUNDRED)
    fak_er = r05(gross * FAK_EMPLOYER_PCT / HUNDRED)
    out.update(ch_admin_cost_employer=admin, ch_fak_employer=fak_er)
    er_total += admin + fak_er
    fak_paid = ZERO
    for ent in s.get("fak_entitlements", []):
        amount = CANTON_FAK[ent["canton"]][ent["type"]]
        assert amount >= FAK_MIN[ent["type"]], "canton amount below the federal minimum is never paid"
        fak_paid += r05(amount)
    out["ch_family_allowance_total"] = fak_paid
    out["ch_employee_total"], out["ch_employer_total"] = ee_total, er_total
    out["total_deductions"] = ee_total
    out["net_pay"] = gross - ee_total + fak_paid
    out["gross"] = gross
    return out


def wage_floor_blocks(s: dict) -> bool:
    """A canton minimum applies only where the worker works; hourly pay =
    countable pay / hours in the period; below the floor = blocked."""
    floor = s.get("floor")
    if not floor or floor["canton"] != s["work_canton"]:
        return False
    hourly = sum((D(v) for v in s["earnings"].values()), ZERO) / D(floor["period_hours"])
    return hourly < D(floor["hourly"])


# ── scenarios (spec §16) ────────────────────────────────────────────────
BASE = {"pay_date": "2026-03-31", "date_of_birth": "1990-05-01", "weekly_hours": "42", "work_canton": "CH-ZH",
        "earnings": {"base_salary": "8000"}, "annual_salary": "96000"}


def _s(name, description, **over):
    return {"name": name, "description": description, **{**BASE, **over}}


SCENARIOS = [
    _s("alv_cap_mid_year", "ALV ceiling reached mid-year: CHF 15,000 / month with CHF 140,000 ALV wages already "
       "insured — only CHF 8,200 remains insurable; AHV continues on the full salary. BVG capped at the "
       "upper salary (coordinated 64,260).",
       pay_date="2026-10-31", earnings={"base_salary": "15000"}, annual_salary="180000",
       ytd_alv_wages="140000", ytd_uvg_wages="140000"),
    _s("bvg_threshold_below", "BVG: annual salary 20,000 is below the 22,680 entry threshold — no BVG.",
       earnings={"base_salary": "1666.65"}, annual_salary="20000"),
    _s("bvg_threshold_crossed", "BVG: a raise to 30,000 crosses the entry threshold — coordinated salary "
       "30,000 - 26,460 = 3,540 is raised to the 3,780 minimum.",
       pay_date="2026-06-30", earnings={"base_salary": "2500"}, annual_salary="30000"),
    _s("nbu_7_5_hours", "UVG: 7.5 h / week is below the 8 h NBU minimum — BU (employer) only, no NBU.",
       weekly_hours="7.5"),
    _s("nbu_9_hours", "UVG: 9 h / week meets the 8 h NBU minimum — NBU applies (fully employee-borne).",
       weekly_hours="9"),
    _s("qst_canton_zh_march", "QST: March in Zurich — monthly model, ZH tariff A0N, 8,000 falls in the 8 % band.",
       qst={"canton": "CH-ZH", "table": "CH-ZH", "code": "A0N"}),
    _s("qst_canton_be_april", "QST: April after moving the QST canton to Bern — the BE tariff applies in full "
       "(9 % band); no blend with March's ZH rate.",
       pay_date="2026-04-30", qst={"canton": "CH-BE", "table": "CH-BE", "code": "A0N"}),
    _s("qst_corrected_tariff", "QST: March recalculated on the corrected ZH tariff (top band 7.5 %).",
       qst={"canton": "CH-ZH", "table": "CH-ZH-CORRECTED", "code": "A0N"}),
    _s("geneva_floor_met", "Wage floor: Geneva canton minimum CHF 24.00 / h applies (works in GE); "
       "4,500 / 173.33 h = 25.96 — met.",
       work_canton="CH-GE", earnings={"base_salary": "4500"}, annual_salary="54000",
       floor={"canton": "CH-GE", "hourly": "24.00", "period_hours": "173.33"}),
    _s("geneva_floor_shortfall", "Wage floor: 4,000 / 173.33 h = 23.08 < 24.00 — BLOCKED, no automatic top-up.",
       work_canton="CH-GE", earnings={"base_salary": "4000"}, annual_salary="48000",
       floor={"canton": "CH-GE", "hourly": "24.00", "period_hours": "173.33"}),
    _s("geneva_floor_out_of_scope", "Wage floor: the Geneva minimum does not apply to a worker in Zurich.",
       earnings={"base_salary": "3000"}, annual_salary="36000",
       floor={"canton": "CH-GE", "hourly": "24.00", "period_hours": "173.33"}),
    _s("fak_canton_above_minimum", "FAK: two approved CHILD entitlements in Zurich — canton amount 250 "
       "(above the 215 federal minimum) each, paid on top of net.",
       fak_entitlements=[{"id": 1, "type": "CHILD", "canton": "CH-ZH"}, {"id": 2, "type": "CHILD", "canton": "CH-ZH"}]),
]


# ── golden case JSON (the frozen-context shape a CH payslip stores) ─────
def _row(ee=None, er=None, amount=None, text=None):
    return {"employee_rate_pct": None if ee is None else str(ee), "employer_rate_pct": None if er is None else str(er),
            "flat_amount": None if amount is None else str(amount), "text_value": text}


def golden_context(s: dict) -> dict:
    rate_map = {k: _row(ee, er) for k, (ee, er) in FEDERAL.items()}
    rate_map.update({
        "ch_alv_ceiling": _row(amount=ALV_CEILING), "ch_uvg_ceiling": _row(amount=UVG_CEILING),
        "ch_nbu_min_weekly_hours": _row(amount=NBU_MIN_WEEKLY_HOURS),
        "ch_bvg_entry_threshold": _row(amount=BVG_ENTRY_THRESHOLD),
        "ch_bvg_coordination_deduction": _row(amount=BVG_COORDINATION_DEDUCTION),
        "ch_bvg_upper_salary": _row(amount=BVG_UPPER_SALARY), "ch_bvg_min_coordinated": _row(amount=BVG_MIN_COORDINATED),
        "ch_fak_child_min": _row(amount=FAK_MIN["CHILD"]), "ch_fak_education_min": _row(amount=FAK_MIN["EDUCATION"]),
        "ch_rounding_rule": _row(amount=D("0.05")),
    })
    earnings = {k: str(D(v)) for k, v in s["earnings"].items()}
    gross = sum((D(v) for v in earnings.values()), ZERO)
    classification = {obl: {"base_salary": True} for obl in ("ch_ahv", "ch_iv", "ch_eo", "ch_alv", "ch_uvg")}
    attrs = {
        "organization_id": None, "payroll_date": s["pay_date"], "earnings": earnings,
        "ytd": {"ch_alv": {"wages": s.get("ytd_alv_wages", "0"), "withheld": "0", "recorded": "ytd_alv_wages" in s},
                "ch_uvg": {"wages": s.get("ytd_uvg_wages", "0"), "withheld": "0", "recorded": "ytd_uvg_wages" in s}},
        "ch_classification": classification, "ch_qst_treatment": {},
        "ch_federal_pack_id": 0, "ch_federal_pack_version": "golden",
        "ch_alv_proration_rule": "annual", "ch_work_canton": s["work_canton"],
        "ch_canton_rate_maps": {c: {f"ch_fak_{t.lower()}": _row(amount=a) for t, a in amounts.items()}
                                for c, amounts in CANTON_FAK.items()},
        "ch_scheme_rules": {"admin_cost_pct": str(ADMIN_COST_PCT)},
        "ch_fak_scheme_id": 2, "ch_fak_scheme_rules": {"employer_pct": str(FAK_EMPLOYER_PCT)},
        "ch_bvg_plan_scheme_id": 3, "ch_bvg_scheme_rules": {"bands": [
            {"component": c, "age_from": a, "age_to": b, "employee_pct": str(ee), "employer_pct": str(er)}
            for c, a, b, ee, er in BVG_PLAN]},
        "ch_uvg_policy_scheme_id": 4, "ch_uvg_scheme_rules": {"insurer": "SYNTHETIC", "risk_classes": [
            {k: str(v) for k, v in UVG_RISK_CLASS.items()}]},
        "ch_uvg_risk_class": UVG_RISK_CLASS["code"], "ch_weekly_hours": s["weekly_hours"],
        "ch_annual_salary": s["annual_salary"], "ch_date_of_birth": s["date_of_birth"],
        "ch_multiple_employment": False, "ch_other_employment_pct": None,
        "ch_occupation": None, "ch_grade": None, "ch_experience_years": None,
        "ch_wage_floor_agreements": [], "ch_fak_entitlements": [], "ch_absence_earnings": [],
        "ch_qst_subject": "NO",
    }
    if s.get("fak_entitlements"):
        attrs["ch_fak_entitlements"] = [{"id": e["id"], "allowance_type": e["type"], "entitlement_basis": "PRIMARY",
                                         "canton": e["canton"], "primary_amount": None} for e in s["fak_entitlements"]]
    if s.get("floor"):
        f = s["floor"]
        attrs["ch_wage_floor_agreements"] = [{
            "id": 11, "agreement_type": "CH_CANTON_MINIMUM", "agreement_code": "CH-GE-MIN-SYNTHETIC",
            "version": "1.0", "canton": f["canton"], "assigned": False,
            "wage_floor": {"basis": "HOURLY", "amount": f["hourly"], "scales": []}}]
        attrs["ch_period_hours"] = f["period_hours"]
        attrs["ch_classification"]["ch_wage_floor"] = {"base_salary": True}
    if s.get("qst"):
        q = s["qst"]
        rate, min_tax, row_id = qst_row(q["table"], q["code"], gross)
        attrs.update(ch_qst_subject="YES", ch_qst_canton=q["canton"], ch_qst_model="MONTHLY",
                     ch_qst_tariff_code=q["code"][0], ch_qst_tariff_file_id=row_id // 100,
                     ch_qst_tariff_file_sha256=f"synthetic-{q['table'].lower()}", ch_qst_children=0,
                     ch_qst_church_tax=False,
                     ch_qst_rate={"rate_pct": str(rate), "min_tax": None if min_tax is None else str(min_tax),
                                  "row_id": row_id})
        attrs["ch_classification"]["ch_qst"] = {"base_salary": True}
        attrs["ch_qst_treatment"] = {"base_salary": "PERIODIC"}
    return {
        "version": 1, "calculationMode": "standard",
        "ctx": {"gross": str(gross), "basic": str(D(earnings.get("base_salary", "0"))), "hra": "0",
                "special_allowance": "0", "overtime": "0", "additional_compensation": "0",
                "unpaid_leave_days": 0, "payroll_days": 30, "calendar_days": None,
                "pay_frequency": "Monthly", "pay_date": s["pay_date"]},
        "rateMap": rate_map, "attrs": attrs,
    }


EXPECTED_FIELDS = ("gross", "net_pay", "total_deductions", "ch_employee_total", "ch_employer_total",
                   "ch_ahv_employee", "ch_ahv_employer", "ch_alv_employee", "ch_alv_employer",
                   "ch_bvg_employee", "ch_bvg_employer", "ch_uvg_bu_employer", "ch_uvg_nbu_employee",
                   "ch_uvg_nbu_employer", "ch_qst_total", "ch_admin_cost_employer", "ch_fak_employer",
                   "ch_family_allowance_total")


def golden_case(s: dict) -> dict:
    case = {"description": s["description"],
            "source": "tests/fixtures/ch_golden/calc_reference.py (independent standalone calculator; "
                      "synthetic tariff / scheme / canton data)",
            "context": {"country": "CH", "ch_frozen_context": golden_context(s)}}
    if wage_floor_blocks(s):
        case["expected_blocked_key"] = "ch_wage_floor_shortfall"
        case["expected"] = {}
    else:
        figures = payslip(s)
        case["expected"] = {k: str(figures[k]) for k in EXPECTED_FIELDS}
    return case


def write_all() -> list:
    written = []
    for s in SCENARIOS:
        path = HERE / f"{s['name']}.json"
        path.write_text(json.dumps(golden_case(s), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path.name)
    return written


if __name__ == "__main__":
    if "--write" in sys.argv:
        print("\n".join(write_all()))
    else:
        for s in SCENARIOS:
            print(s["name"], "BLOCKED" if wage_floor_blocks(s) else payslip(s)["net_pay"])
