"""South Africa G6 parallel payroll cycles (ZP-ZA-ENG-001 §13; Phase 10). An
incumbent's results for a committed ZA run are compared with Zoiko's frozen
payslips, never recomputed; identifiers are refused unechoed; four-eyes on
every acceptance; no cycle is clean until the materiality threshold (D-4) is
recorded; nothing ever changes a payslip. "ZA" is South Africa."""
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import south_africa_parallel as parallel
from app.modules.payroll import south_africa_readiness as readiness
from app.modules.payroll.models import PayslipItem

from tests._za_run_helpers import APPROVER, PREPARER, THIRD, employee, payslip, run

MAPPING = {"employeeCode": "Emp", "gross": "Gross", "paye": "PAYE", "uif_employee": "UIF EE",
           "uif_employer": "UIF ER", "sdl": "SDL", "net": "Net"}
HEADER = "Emp,Gross,PAYE,UIF EE,UIF ER,SDL,Net"
F1 = "50000.00,11075.58,177.12,177.12,500.00,38747.30"
F2 = "30000.00,3115.25,177.12,177.12,300.00,26707.63"


@pytest.fixture()
def committed(db, organization):
    r = run(db, organization, status="Paid")
    e1, e2 = employee(db, organization, "ZA-P1"), employee(db, organization, "ZA-P2")
    i1 = payslip(db, organization, r, e1, "f1_monthly_salary_age_40")
    i2 = payslip(db, organization, r, e2, "f2_age_68_one_medical_dependant")
    return r, (e1, i1), (e2, i2)


def _import(db, organization, r, csv_text, actor=PREPARER, mapping=MAPPING):
    return parallel.import_za_parallel(db, organization.id, {"payrollRunId": r.id, "sourceLabel": "Bureau X",
                                                             "csv": csv_text, "columnMapping": mapping}, actor)


def _materiality(monkeypatch, value):
    monkeypatch.setattr(parallel, "materiality", lambda: None if value is None else Decimal(value))


def test_identical_results_produce_no_differences(db, organization, committed):
    r, *_ = committed
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,{F1}\nZA-P2,{F2}\n")
    assert (out["matchedCount"], out["unmatchedCount"], out["differences"]) == (2, 0, [])
    assert out["status"] == "OPEN" and len(out["fileSha256"]) == 64


def test_amounts_come_from_the_committed_payslip_not_a_recalculation(db, organization, committed):
    r, (e1, i1), _ = committed
    i1.tds = Decimal("11000.00")                    # what was committed is what is compared
    db.flush()
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,{F1}\nZA-P2,{F2}\n")
    assert [(d["employeeId"], d["concept"], d["delta"]) for d in out["differences"]] == [(e1.id, "paye", "-75.58")]


def test_unknown_and_missing_employees_are_counted(db, organization, committed):
    r, *_ = committed
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,{F1}\nNOBODY,{F2}\n")
    assert (out["matchedCount"], out["unmatchedCount"]) == (1, 1)


@pytest.mark.parametrize("csv_text, message", [
    (f"Emp,ID Number,Gross\nZA-P1,8001015009087,50000\n", "name a personal identifier"),
    (f"Emp,Gross\nZA-P1,8001015009087\n", "shaped like a personal"),
    (f"Emp,Gross\n8001015009087,50000\n", "shaped like a personal"),
    (f"Emp,Gross\nZA-P1,0123456789\n", "shaped like a personal"),
])
def test_identifiers_are_refused_and_never_echoed(db, organization, committed, csv_text, message):
    r, *_ = committed
    with pytest.raises(BadRequestException) as exc:
        _import(db, organization, r, csv_text, mapping={"employeeCode": "Emp", "gross": "Gross"})
    assert message in str(exc.value) and "8001015009087" not in str(exc.value)
    assert "0123456789" not in str(exc.value)


def test_an_employee_id_header_on_the_code_column_is_allowed(db, organization, committed):
    r, *_ = committed
    out = _import(db, organization, r, "Employee ID,Gross\nZA-P1,50000\nZA-P2,30000\n",
                  mapping={"employeeCode": "Employee ID", "gross": "Gross"})
    assert out["matchedCount"] == 2 and out["differences"] == []


@pytest.mark.parametrize("data, message", [
    ({"payrollRunId": None}, "payrollRunId"),
    ({"sourceLabel": ""}, "sourceLabel"),
    ({"columnMapping": {"employeeCode": "Missing"}}, "employeeCode"),
    ({"columnMapping": {"employeeCode": "Emp"}}, "at least one concept"),
    ({"csv": ""}, "csv"),
])
def test_import_validation(db, organization, committed, data, message):
    r, *_ = committed
    base = {"payrollRunId": r.id, "sourceLabel": "Bureau X", "csv": f"{HEADER}\nZA-P1,{F1}\n",
            "columnMapping": MAPPING}
    with pytest.raises(BadRequestException, match=message):
        parallel.import_za_parallel(db, organization.id, {**base, **data}, PREPARER)


def test_only_a_committed_run_is_compared(db, organization):
    r = run(db, organization, status="Approved")
    payslip(db, organization, r, employee(db, organization, "ZA-OPEN"))
    with pytest.raises(BadRequestException, match="committed"):
        _import(db, organization, r, f"{HEADER}\nZA-OPEN,{F1}\n")


def test_explain_and_accept_are_four_eyes(db, organization, committed):
    r, *_ = committed
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,50000.00,11070.00,177.12,177.12,500.00,38752.88\n"
                                       f"ZA-P2,{F2}\n")
    diff = out["differences"][0]["id"]
    with pytest.raises(BadRequestException, match="explained"):
        parallel.accept_za_parallel_difference(db, organization.id, diff, APPROVER)
    with pytest.raises(BadRequestException, match="reason"):
        parallel.explain_za_parallel_difference(db, organization.id, diff, " ", PREPARER)
    parallel.explain_za_parallel_difference(db, organization.id, diff, "bureau rounds PAYE to the rand", PREPARER)
    with pytest.raises(BadRequestException, match="four-eyes"):
        parallel.accept_za_parallel_difference(db, organization.id, diff, PREPARER)
    out = parallel.accept_za_parallel_difference(db, organization.id, diff, APPROVER)
    assert out["counts"]["ACCEPTED"] == 1


def test_never_clean_while_the_materiality_threshold_is_unrecorded(db, organization, committed, monkeypatch):
    r, *_ = committed
    _materiality(monkeypatch, None)
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,{F1}\nZA-P2,{F2}\n")
    assert out["clean"] is False and "D-4" in out["reason"]
    with pytest.raises(BadRequestException, match="not clean"):
        parallel.accept_za_parallel_import(db, organization.id, out["id"], APPROVER)


def test_the_real_content_row_is_empty_by_design():
    assert parallel.materiality() is None


def test_a_clean_cycle_is_accepted_by_a_second_person_only(db, organization, committed, monkeypatch):
    r, *_ = committed
    _materiality(monkeypatch, "10")
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,50000.00,11070.00,177.12,177.12,500.00,38752.88\n"
                                       f"ZA-P2,{F2}\n")
    assert out["clean"] is True                                     # |5.58| <= R10
    with pytest.raises(BadRequestException, match="four-eyes"):
        parallel.accept_za_parallel_import(db, organization.id, out["id"], PREPARER)
    out = parallel.accept_za_parallel_import(db, organization.id, out["id"], APPROVER)
    assert out["status"] == "ACCEPTED" and out["acceptedById"] == APPROVER
    with pytest.raises(BadRequestException, match="OPEN"):
        parallel.withdraw_za_parallel_import(db, organization.id, out["id"])


def test_a_material_difference_needs_acceptance_before_the_cycle_is_clean(db, organization, committed, monkeypatch):
    r, *_ = committed
    _materiality(monkeypatch, "1")
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,50000.00,11070.00,177.12,177.12,500.00,38752.88\n"
                                       f"ZA-P2,{F2}\n")
    assert out["clean"] is False and "above R1" in out["reason"]
    for d in out["differences"]:
        parallel.explain_za_parallel_difference(db, organization.id, d["id"], "known bureau rounding", PREPARER)
        out = parallel.accept_za_parallel_difference(db, organization.id, d["id"], THIRD)
    assert out["clean"] is True


def test_missing_payslips_keep_the_cycle_unclean(db, organization, committed, monkeypatch):
    r, *_ = committed
    _materiality(monkeypatch, "10")
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,{F1}\n")
    assert out["clean"] is False and "missing from the file" in out["reason"]


def test_withdrawn_imports_freeze_their_differences(db, organization, committed):
    r, *_ = committed
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,50000.00,1.00,177.12,177.12,500.00,38747.30\n")
    parallel.withdraw_za_parallel_import(db, organization.id, out["id"])
    with pytest.raises(BadRequestException, match="no longer open"):
        parallel.explain_za_parallel_difference(db, organization.id, out["differences"][0]["id"], "x", PREPARER)


def test_nothing_changes_a_payslip(db, organization, committed, monkeypatch):
    r, (_e1, i1), (_e2, i2) = committed
    before = [(i.gross_pay, i.net_pay, i.tds, dict(i.za_calculation_snapshot)) for i in (i1, i2)]
    _materiality(monkeypatch, "10")
    out = _import(db, organization, r, f"{HEADER}\nZA-P1,50000.00,11070.00,177.12,177.12,500.00,38752.88\n"
                                       f"ZA-P2,{F2}\n")
    parallel.accept_za_parallel_import(db, organization.id, out["id"], APPROVER)
    after = [(i.gross_pay, i.net_pay, i.tds, dict(i.za_calculation_snapshot))
             for i in db.query(PayslipItem).filter(PayslipItem.id.in_([i1.id, i2.id])).order_by(PayslipItem.id)]
    assert after == before


def test_two_accepted_months_satisfy_the_g6_code_check(db, organization, monkeypatch):
    _materiality(monkeypatch, "10")
    emp = employee(db, organization, "ZA-M")
    for pay_date in (date(2026, 8, 31), date(2026, 9, 30)):
        r = run(db, organization, pay_date=pay_date, status="Paid")
        payslip(db, organization, r, emp)
        out = _import(db, organization, r, f"{HEADER}\nZA-M,{F1}\n")
        assert readiness.code_checks(db)["parallel_cycles"][0] is False
        parallel.accept_za_parallel_import(db, organization.id, out["id"], APPROVER)
    met, detail = readiness.code_checks(db)["parallel_cycles"]
    assert met and detail.startswith("2 pay month(s)")


def test_eti_is_not_a_compared_concept():
    assert "eti" not in " ".join(parallel.CONCEPTS)
