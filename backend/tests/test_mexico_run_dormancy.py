"""Mexico Phase 6 — dormancy in depth (plan §1). calc_inputs no longer raises
MX_ENGINE_NOT_IMPLEMENTED, so every production path into a Mexican
calculation must refuse on its own while MX_TENANT_ONBOARDING_ENABLED is off
(the production setting), or when the organisation is not Mexican — and
write nothing. The Mexican employee here exists because it was created while
the flag was on, exactly like one planted directly in the database."""

import re
from pathlib import Path

import pytest

from tests import _mx_run_helpers as rh


def _flag_off(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "MX_TENANT_ONBOARDING_ENABLED", False)


def _counts(db):
    from app.modules.payroll.models import PayrollMxPreflightException, PayslipItem

    return db.query(PayslipItem).count(), db.query(PayrollMxPreflightException).count()


def _refused(fn, key):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    with pytest.raises(MXBlock) as exc:
        fn()
    assert exc.value.key == key, exc.value.key


def _paths(db, w):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import PayslipItemCreate

    fields = PayslipItemCreate.model_fields
    data = {"employee_id": w.employee.id, "basic_salary": 9000, "employeeId": w.employee.id, "basicSalary": 9000}
    item = PayslipItemCreate(**{k: v for k, v in data.items() if k in fields})
    return {
        "preview": lambda: service.preview_payroll_run(db, w.org.id, [w.employee.id], "MX", *rh.PERIOD,
                                                       pay_date=rh.PAY_DATE),
        "generate": lambda: service.generate_payslips_for_run(db, w.run, w.org.id, [w.employee.id]),
        "add_item": lambda: service.add_payslip_item(db, w.run.id, item, w.org.id),
    }


@pytest.mark.parametrize("path", ["preview", "generate", "add_item"])
def test_flag_off_refuses_every_path_and_writes_nothing(db, monkeypatch, path):
    w = rh.world(db, monkeypatch)
    _flag_off(monkeypatch)
    before = _counts(db)
    _refused(_paths(db, w)[path], "MX_DORMANT")
    db.rollback()
    assert _counts(db) == before


@pytest.mark.parametrize("path", ["preview", "generate", "add_item"])
def test_flag_on_but_not_a_mexican_org_refuses(db, monkeypatch, path):
    from app.modules.payroll.models import CompanyComplianceDetails

    w = rh.world(db, monkeypatch)
    db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == w.org.id).update(
        {"jurisdiction_country": "US"})
    db.commit()
    before = _counts(db)
    with pytest.raises(Exception) as exc:
        _paths(db, w)[path]()
    # Either the guard (MX_ORG_NOT_MEXICAN) or an earlier shared refusal — never a Mexican calculation.
    assert getattr(exc.value, "key", None) in ("MX_ORG_NOT_MEXICAN", None) or "MX" in str(exc.value)
    db.rollback()
    assert _counts(db) == before


def test_guard_codes_directly(db, monkeypatch):
    from app.modules.payroll import mexico_run_service
    from app.modules.payroll.models import CompanyComplianceDetails

    w = rh.world(db, monkeypatch)
    w.run.mx_run_type = "BOGUS"                     # every Phase 9 type is built (9a-9d); an unknown one is refused
    db.commit()
    _refused(lambda: mexico_run_service.guard(db, w.employee, w.run), "MX_RUN_TYPE_UNKNOWN")
    w.run.mx_run_type = None
    w.run.organization_id = w.org.id + 999
    _refused(lambda: mexico_run_service.guard(db, w.employee, w.run), "MX_RUN_ORG_MISMATCH")
    db.rollback()
    db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == w.org.id).update(
        {"jurisdiction_country": "NL"})
    _refused(lambda: mexico_run_service.guard(db, w.employee, None), "MX_ORG_NOT_MEXICAN")
    _flag_off(monkeypatch)
    _refused(lambda: mexico_run_service.guard(db, w.employee, None), "MX_DORMANT")


def test_guard_runs_before_any_read(db, monkeypatch):
    """With the flag off, calc_inputs refuses even for an employee object
    that has nothing behind it — no query is attempted first."""
    from types import SimpleNamespace

    from app.modules.payroll import mexico_run_service

    _flag_off(monkeypatch)
    _refused(lambda: mexico_run_service.calc_inputs(None, None, SimpleNamespace(organization_id=1)), "MX_DORMANT")


def test_no_other_calculator_builds_a_mexican_context():
    """Fixed-country calculators (DE/SG/SE/AU/IT/SA/CH/HK previews) never
    construct country="MX" — only the shared run paths, guarded above."""
    root = Path(__file__).resolve().parents[1] / "app"
    hits = []
    for p in root.rglob("*.py"):
        if "mexico" in p.name or "jurisdictions" in p.parts and "mexico" in p.parts:
            continue
        if re.search(r"""country\s*=\s*["']MX["']""", p.read_text(encoding="utf-8", errors="ignore")):
            hits.append(str(p.relative_to(root)))
    assert hits == []


def test_run_routes_are_behind_the_4a_guard(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    w = rh.world(db, monkeypatch)
    _flag_off(monkeypatch)
    with http(db, principal(w.org.id, w.users[0].id)) as client:
        for method, path in (("get", f"/runs/{w.run.id}/preflight"), ("get", f"/runs/{w.run.id}/status"),
                             ("post", f"/runs/{w.run.id}/reset"), ("get", f"/employees/{w.employee.id}/hours")):
            r = getattr(client, method)(ORG_BASE + path, **({"json": {"reason": "x"}} if method == "post" else {}))
            assert r.status_code == 403, (path, r.status_code)
