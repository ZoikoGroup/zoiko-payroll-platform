"""Japan My Number redaction proof (ZP-JP-ENG-001 §12, release gate G6).

A valid My Number is GENERATED here (check digit computed at run time) — the
repository holds no 12-digit literal. It is then taken through every path
that handles it: capture, duplicate refusal, a bad check digit, the reveal
flow, the masked list, the employee summary, the vault access log, the tax
audit trail, logs, a parallel-run file and a frozen payroll context. Only the
explicit, approved reveal may return the digits; nothing else may carry them,
in plain or grouped form.
"""
import json
import logging
import random
from datetime import date
from types import SimpleNamespace

import pytest

from app.config import settings
from app.core.exceptions import BadRequestException
from app.modules.payroll import japan_parallel as parallel
from app.modules.payroll import japan_service as jp
from app.modules.payroll.models import (
    PayrollEmployee, PayrollJpMyNumberAccessEvent, PayrollRun, PayslipItem, TaxConfigurationAudit,
)

WEIGHTS = (6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def _generated_number(seed: int) -> str:
    rng = random.Random(seed)
    body = "".join(str(rng.randint(0, 9)) for _ in range(11))
    total = sum(int(d) * w for d, w in zip(body, WEIGHTS))
    check = 11 - (total % 11)
    return body + str(0 if check >= 10 else check)


def _forms(number: str) -> tuple:
    return number, f"{number[:4]} {number[4:8]} {number[8:]}", f"{number[:4]}-{number[4:8]}-{number[8:]}"


def _absent(number: str, text: str, where: str):
    for form in _forms(number):
        assert form not in text, f"My Number found in {where}"


def _rows(db, model, **filters) -> str:
    rows = db.query(model).filter_by(**filters).all()
    return json.dumps([{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows], default=str)


@pytest.fixture()
def keys(monkeypatch):
    monkeypatch.setattr(settings, "JP_MY_NUMBER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", "p" * 32)


@pytest.fixture()
def employee(db, organization):
    row = PayrollEmployee(organization_id=organization.id, employee_code="JP-PRIV-1",
                          name="Synthetic Employee", country_code="JP")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_my_number_never_leaves_the_vault_except_through_an_approved_reveal(
        db, organization, employee, keys, caplog):
    caplog.set_level(logging.DEBUG)
    number = _generated_number(20261102)
    created = jp.create_my_number(db, organization.id, employee.id, {"myNumber": number}, 1)
    db.commit()
    vault_id = created["id"] if isinstance(created, dict) else created.id
    _absent(number, json.dumps(created if isinstance(created, dict) else {}, default=str), "the create response")

    # A duplicate and a bad check digit are refused without echoing the digits.
    with pytest.raises(BadRequestException) as duplicate:
        jp.create_my_number(db, organization.id, employee.id, {"myNumber": number}, 1)
    _absent(number, str(duplicate.value.detail), "the duplicate refusal")
    bad = number[:11] + str((int(number[11]) + 1) % 10)
    with pytest.raises(BadRequestException) as invalid:
        jp.create_my_number(db, organization.id, employee.id, {"myNumber": bad}, 1)
    _absent(bad, str(invalid.value.detail), "the check-digit refusal")
    db.rollback()

    jp.request_my_number_reveal(db, organization.id, vault_id, "payroll filing", 1)
    db.commit()
    jp.approve_my_number_reveal(db, organization.id, vault_id, 2)
    db.commit()
    revealed = jp.reveal_my_number(db, organization.id, vault_id, 2)
    db.commit()
    assert revealed["myNumber"] == number                               # the one sanctioned path

    _absent(number, json.dumps(jp.list_my_numbers(db, organization.id, employee.id), default=str), "the masked list")
    _absent(number, json.dumps(jp.employee_summary(db, organization.id, employee.id), default=str),
            "the employee summary")
    _absent(number, _rows(db, PayrollJpMyNumberAccessEvent, organization_id=organization.id), "the access log")
    _absent(number, _rows(db, TaxConfigurationAudit), "the audit trail")
    _absent(number, caplog.text, "the logs")


def test_a_parallel_run_file_holding_a_my_number_is_refused_without_echo(db, organization, employee):
    number = _generated_number(7)
    run = PayrollRun(organization_id=organization.id, period_label="2026-06", period_start=date(2026, 6, 1),
                     period_end=date(2026, 6, 30), pay_date=date(2026, 6, 25), status="Paid", created_by=1)
    db.add(run)
    db.flush()
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=employee.id, organization_id=organization.id,
                       employee_name=employee.name, country_code="JP", jp_calculation_snapshot={"jp_wht_total": "0"}))
    db.commit()
    for cell in _forms(number):
        with pytest.raises(BadRequestException) as refused:
            parallel.import_jp_parallel(db, organization.id, {
                "payrollRunId": run.id, "sourceLabel": "Incumbent",
                "csv": f"Employee,Gross,Memo\nJP-PRIV-1,300000,{cell}\n",
                "columnMapping": {"employeeCode": "Employee", "gross": "Gross"}}, 1)
        _absent(number, str(refused.value.detail), "the parallel-run refusal")


def test_a_frozen_payroll_context_carries_the_vault_id_never_the_number():
    number = _generated_number(99)
    ctx = SimpleNamespace(
        jp_worker_tax_profile=SimpleNamespace(id=1, residency_status="RESIDENT", declaration_class="PRIMARY",
                                              my_number_vault_id=42, dependants_count=0),
        rate_map={}, slabs=[])
    frozen = jp.jp_freeze_context(ctx)
    assert frozen["profile"]["my_number_vault_id"] == 42
    _absent(number, json.dumps(frozen, default=str), "the frozen context")
    assert not any("my_number" in key and key != "my_number_vault_id" for key in frozen["profile"])
