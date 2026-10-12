"""Italy (ZP-IT-ENG-001) end to end through the real payroll service.

The engine tests prove the arithmetic; these prove the WIRING: the canonical
pack seeded from italy_content.py, the input resolver feeding italy.py, the
payslip snapshot, and the year-to-date rows the next period reads back. Two
consecutive months run here, so a figure the first month posts is the figure
the second month consumes.

In-memory SQLite only (the `db` fixture) — nothing reaches a configured
database.
"""
from datetime import date
from decimal import Decimal as D

import pytest

from app.modules.payroll import italy_service, service
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
from app.modules.payroll.models import (
    CompanyComplianceDetails,
    EmployeeStatutoryProfile,
    EmployerItalyProfile,
    PayrollEmployee,
    PayrollRun,
    PayrollYtdAccumulator,
    PayslipItem,
)


def _stub_codes(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


@pytest.fixture()
def italy_org(db, organization, monkeypatch):
    _stub_codes(monkeypatch)
    pack = italy_service.seed_italy_pack(db, status="Active")   # Active for the test only
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="Italy",
                                    active_pack_id=pack.id))
    db.add(EmployerItalyProfile(organization_id=organization.id, csc_code="70501",
                                fund_status={"fund": "FIS", "fisBand": "UP_TO_5"},
                                prior_year_avg_headcount=10))
    db.commit()
    return organization


def _employee(db, org, code="IT-001", monthly=D("2500"), worker_class="OPERAIO"):
    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=f"Lavoratore {code}",
                          country_code="IT", ctc=monthly * 12, date_of_joining=date(2025, 1, 1))
    db.add(emp)
    db.flush()
    db.add(EmployeeStatutoryProfile(
        employee_id=emp.id, organization_id=org.id, country_code="IT", effective_from=date(2026, 1, 1),
        it_worker_class=worker_class, it_contract_type="INDETERMINATO", it_cigs_applies=False,
        it_tfr_destination="AZIENDA", it_tax_domicile_region="03", it_tax_domicile_comune="F205"))
    db.commit()
    db.refresh(emp)
    return emp


def _run(db, org, month):
    end = date(2026, month, 30 if month in (4, 6, 9, 11) else 31)
    run = PayrollRun(organization_id=org.id, period_label=f"2026-{month:02d}",
                     period_start=date(2026, month, 1), period_end=end, pay_date=end)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _item(db, run, emp):
    return (db.query(PayslipItem)
            .filter(PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id).one())


def _row(db, emp, year_key, component):
    return (db.query(PayrollYtdAccumulator)
            .filter(PayrollYtdAccumulator.employee_id == emp.id,
                    PayrollYtdAccumulator.tax_year == year_key,
                    PayrollYtdAccumulator.tax_component == component).one_or_none())


def test_an_employee_without_recorded_opening_balances_blocks(db, italy_org):
    """IT-008: the §5 opening position is never assumed to be zero."""
    _employee(db, italy_org)
    run = _run(db, italy_org, 3)
    with pytest.raises(MissingComplianceConfigurationError):
        service.generate_payslips_for_run(db, run, italy_org.id)


def test_two_months_post_and_consume_the_same_running_totals(db, italy_org):
    emp = _employee(db, italy_org)
    italy_service.record_opening_balances(db, emp.id, 2026, addreg_saldo_due=D("330"),
                                          addcom_saldo_due=D("110"), addcom_acconto_due=D("90"))
    db.commit()

    march = _run(db, italy_org, 3)
    service.generate_payslips_for_run(db, march, italy_org.id)
    item = _item(db, march, emp)
    snap = item.it_calculation_snapshot
    assert snap is not None and snap["calculation"]["jurisdiction"] == "IT"
    # §5 instalments from the recorded balances (9 left in March).
    assert snap["localTax"] == {"regionalSaldo": "36.67", "municipalSaldo": "12.22",
                                "municipalAcconto": "10.00", "terminationWithheld": "0"}
    key = italy_service.tax_year_key(2026)
    irpef = _row(db, emp, key, "it_irpef")
    assert D(str(irpef.ytd_taxable_wages)) == D(snap["calculation"]["taxableIncome"])
    assert D(str(irpef.ytd_tax_withheld)) == D(snap["irpef"]["withheld"])
    assert D(str(_row(db, emp, key, "it_addreg_saldo").ytd_tax_withheld)) == D("36.67")
    assert D(str(_row(db, emp, key, "it_mensilita").ytd_taxable_wages)) == D("1")

    # April reads what March posted: 293.33 left over 8 instalments.
    april = _run(db, italy_org, 4)
    service.generate_payslips_for_run(db, april, italy_org.id)
    april_snap = _item(db, april, emp).it_calculation_snapshot
    assert april_snap["localTax"]["regionalSaldo"] == "36.67"
    assert april_snap["calculation"]["mensilitaPaidPrior"] == 1
    assert D(str(_row(db, emp, key, "it_addreg_saldo").ytd_tax_withheld)) == D("73.34")
    irpef = _row(db, emp, key, "it_irpef")
    assert D(str(irpef.ytd_tax_withheld)) == (D(snap["irpef"]["withheld"])
                                              + D(april_snap["irpef"]["withheld"]))


def test_net_pay_includes_the_surtax_instalments(db, italy_org):
    emp = _employee(db, italy_org)
    italy_service.record_opening_balances(db, emp.id, 2026, addreg_saldo_due=D("330"),
                                          addcom_saldo_due=D("110"), addcom_acconto_due=D("90"))
    db.commit()
    run = _run(db, italy_org, 3)
    service.generate_payslips_for_run(db, run, italy_org.id)
    item = _item(db, run, emp)
    snap = item.it_calculation_snapshot
    employee_total = (D(snap["inps"]["employee"]) + D(snap["irpef"]["withheld"])
                      - D(snap["irpef"]["refund"]) + D("58.89"))
    assert D(str(item.net_pay)) == D(str(item.gross_pay)) - employee_total + D(snap["wedge"]["taxFreeSum"])


def test_the_inps_matrix_keeps_every_worker_class(db, italy_org):
    """The shared rate-map builder keys by component alone, which would keep
    ONE class's IVS row for everyone; italy_rate_map keys matrix rows by
    scope|class|family so each class resolves its own row."""
    for code, worker_class in (("IT-OP", "OPERAIO"), ("IT-IMP", "IMPIEGATO")):
        emp = _employee(db, italy_org, code=code, worker_class=worker_class)
        italy_service.record_opening_balances(db, emp.id, 2026, addreg_saldo_due=D("0"),
                                              addcom_saldo_due=D("0"), addcom_acconto_due=D("0"))
    db.commit()
    run = _run(db, italy_org, 3)
    service.generate_payslips_for_run(db, run, italy_org.id)
    classes = {i.it_calculation_snapshot["calculation"]["workerClass"]
               for i in db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id)}
    assert classes == {"OPERAIO", "IMPIEGATO"}


def test_record_opening_balances_refuses_an_unrecorded_amount(db, italy_org):
    emp = _employee(db, italy_org)
    with pytest.raises(ValueError):
        italy_service.record_opening_balances(db, emp.id, 2026, addreg_saldo_due=None,
                                              addcom_saldo_due=D("0"), addcom_acconto_due=D("0"))


def test_seed_refuses_to_rewrite_a_pack_that_left_draft(db):
    italy_service.seed_italy_pack(db, status="Active")
    with pytest.raises(ValueError):
        italy_service.seed_italy_pack(db)


def test_contributory_days_counts_a_joiners_working_days():
    # Joined Wednesday 18 March 2026: 18-31 March has 12 Monday-Saturday days.
    got = italy_service.contributory_days(date(2026, 3, 1), date(2026, 3, 31), date(2026, 3, 18), None)
    assert got == {"it_contributory_days": D("12")}
    full = italy_service.contributory_days(date(2026, 3, 1), date(2026, 3, 31), date(2025, 1, 1), None)
    assert full == {"it_contributory_full_month": True}


def test_work_days_in_year_runs_from_hiring_to_leaving():
    assert italy_service.work_days_in_year(2026, date(2025, 1, 1), None) == 365
    assert italy_service.work_days_in_year(2026, date(2026, 7, 1), None) == 184
    assert italy_service.work_days_in_year(2026, date(2025, 1, 1), date(2026, 3, 31)) == 90
