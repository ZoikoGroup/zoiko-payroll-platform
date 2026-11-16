"""Belgium (ZP-BE-ENG-001) Block L1: the rollback guarantee — dormancy + fix-forward (owner decision 2026-11-16).

The Belgian schema is permanent (main's migrations build on it), so rolling Belgium back means switching it OFF:
BE_TENANT_ONBOARDING_ENABLED unset, BE_CANARY_ORG_IDS empty, demo packs off, identifier keys unset, no Active
Belgian pack, the registry row PLANNED or absent. With the full schema present (21 payroll_be_* tables) and that
state, this proves:

  * every /api/payroll/belgium/* route answers 404;
  * calculate_payroll for BE raises its blocked error in every calculation mode, and a Belgian preview is refused;
  * the Super Admin Belgium console loads read-only and writes nothing;
  * other countries' payroll is identical whether the Belgian tables are empty or hold the full Draft pack and
    Belgian test data: Australia (Generation 1, through the database: add_payslip_item), Poland and Malaysia
    (Generation 2, through the shared engine dispatcher calculate_payroll);
  * the app starts with no Belgian setting at all (tests/test_belgium_production_startup.py, run from here).

CI runs this file as the rollback proof (privacy-isolation job). SYNTHETIC data only.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException

NISS = "12312312312"  # privacy-scan: allow (synthetic TEST ONLY value)
BE_TABLES = 21


@pytest.fixture
def dormant(monkeypatch):
    """Belgium switched off by every setting (the rollback state)."""
    from app.config import settings

    for name, value in (("BE_TENANT_ONBOARDING_ENABLED", False), ("BE_CANARY_ORG_IDS", ""),
                        ("BE_DEMO_PACKS_ENABLED", False), ("BE_DEMO_ORG_IDS", ""),
                        ("BE_IDENTIFIER_KEYRING", ""), ("BE_IDENTIFIER_FINGERPRINT_KEY", "")):
        monkeypatch.setattr(settings, name, value)
    return settings


def _belgian_tables(db):
    import sqlalchemy as sa

    return [t for t in sa.inspect(db.get_bind()).get_table_names() if t.startswith("payroll_be_")]


def _fill_belgium(db, monkeypatch, settings):
    """The full Draft pack and Belgian test data in every kind of Belgian record (keys only while writing)."""
    from app.modules.payroll import belgium_governance as gov, belgium_service as be
    from app.modules.payroll.models import PayrollEmployee
    from scripts.seed_belgium_canonical_packs import seed_belgium
    from tests._mx_employer_helpers import make_org

    seed_belgium(db)
    t = make_org(db, name="Dormant BV", code="BEDORM", admins=2, country="BE")
    a, b = t.users[0].id, t.users[1].id
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="BE-D1", name="Synthetic Belgian",
                               country_code="BE", ctc=Decimal("3800"), basic=Decimal("3800"), hra=Decimal("0"))
    db.add(employee)
    db.commit()

    def two(record, approve, *args):
        row = record(*args)
        db.flush()
        return approve(db, t.org.id, row.id, b)

    two(be.record_be_employer_registration, be.approve_be_employer_registration, db, t.org.id,
        {"effective_from": "2026-01-01", "legal_name": "Dormant BV", "enterprise_number": "0999999999",
         "employer_category_code": "000"}, a, "TEST ONLY")
    two(be.record_be_worker_profile, be.approve_be_worker_profile, db, t.org.id, employee.id,
        {"effective_from": "2026-01-01", "worker_category": "EMPLOYEE", "residency": "RESIDENT"}, a, "TEST ONLY")
    two(be.record_be_work_schedule, be.approve_be_work_schedule, db, t.org.id, employee.id,
        {"effective_from": "2026-01-01", "regime": "EFFECTIVE", "weekly_hours": "38"}, a, "TEST ONLY")
    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "f" * 32)
    be.create_be_identifier(db, t.org.id, "NISS", NISS, a, employee_id=employee.id)
    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", "")
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "")
    be.record_be_holiday_certificate(db, t.org.id, employee.id, {"direction": "OUT", "service_year": 2025}, a,
                                     "TEST ONLY")
    gov.be_record_gate_evidence(db, {"gate": "G7", "evidenceType": "BE-OWNER-CONTENT", "reference": "TEST ONLY"}, a)
    gov.be_import_decision_proposals(db, a)
    db.commit()
    return t


# ── Belgium itself is off ───────────────────────────────────────────────────
def test_every_belgian_route_answers_404_with_the_full_schema(db, dormant, monkeypatch):
    import re

    from app.main import app
    from tests._mx_employer_helpers import http, principal

    assert len(_belgian_tables(db)) == BE_TABLES
    t = _fill_belgium(db, monkeypatch, dormant)
    routes = sorted({(m, r.path) for r in app.routes if getattr(r, "path", "").startswith("/api/payroll/belgium")
                     for m in (getattr(r, "methods", None) or ()) if m != "HEAD"})
    assert len(routes) >= 20
    statuses = {}
    with http(db, principal(t.org.id, t.users[0].id)) as client:
        for method, path in routes:
            res = client.request(method, re.sub(r"\{[^}]+\}", "1", path), json={} if method != "GET" else None)
            statuses[f"{method} {path}"] = res.status_code
    assert set(statuses.values()) == {404}, {k: v for k, v in statuses.items() if v != 404}


def test_the_belgian_calculation_is_blocked_in_every_mode(db, dormant, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError
    from app.modules.payroll.engine.resolver import calculate_payroll
    from app.modules.payroll.models import PayrollEmployee

    t = _fill_belgium(db, monkeypatch, dormant)
    for mode in ("standard", "simple"):
        with pytest.raises(MissingComplianceConfigurationError):
            calculate_payroll(PayrollContext(country="BE", gross=Decimal("3800"), basic=Decimal("3800"),
                                             pay_date=date(2026, 9, 30)), mode)
    employee = db.query(PayrollEmployee).filter_by(organization_id=t.org.id).first()
    from fastapi import HTTPException

    with pytest.raises(Exception) as refused:
        service.preview_payroll_run(db, t.org.id, [employee.id], "BE", period_start=date(2026, 9, 1),
                                    period_end=date(2026, 9, 30), pay_date=date(2026, 9, 30))
    assert isinstance(refused.value, (MissingComplianceConfigurationError, BadRequestException, HTTPException)),         repr(refused.value)                                                      # a refusal, not a crash


def test_the_super_admin_console_loads_read_only(db, dormant, monkeypatch):
    from sqlalchemy import event

    from tests._mx_employer_helpers import SUPER_ADMIN, http

    _fill_belgium(db, monkeypatch, dormant)
    writes = []

    def watch(_conn, _cursor, statement, *_a, **_k):
        if statement.lstrip().split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE"):
            writes.append(statement[:80])

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", watch)
    try:
        with http(db, SUPER_ADMIN) as client:
            base = "/api/super-admin/compliance/belgium"
            for path in ("/packs", "/decisions", "/joint-committees", "/readiness", "/gate-evidence",
                         "/decision-records"):
                res = client.get(base + path)
                assert res.status_code == 200, (path, res.status_code, res.text[:200])
    finally:
        event.remove(engine, "before_cursor_execute", watch)
    assert writes == []


def test_the_app_starts_with_no_belgian_setting(tmp_path):
    from tests.test_belgium_production_startup import test_app_starts_with_no_belgian_settings_and_belgium_is_dormant

    test_app_starts_with_no_belgian_settings_and_belgium_is_dormant(tmp_path)


# ── other countries are unaffected by the Belgian tables' content ───────────
def _au_payslip(db, org_id, code):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollEmployee, PayrollRun
    from app.modules.payroll.schemas import PayslipItemCreate

    emp = PayrollEmployee(organization_id=org_id, employee_code=code, name=f"Employee {code}", country_code="AU",
                          ctc=Decimal("96000"))
    run = PayrollRun(organization_id=org_id, period_label=f"AU {code}", period_start=date(2026, 8, 1),
                     period_end=date(2026, 8, 31), pay_date=date(2026, 9, 1))
    db.add_all([emp, run])
    db.commit()
    item = service.add_payslip_item(db, run.id, PayslipItemCreate(employee_id=emp.id, basic_salary=Decimal("8000")),
                                    org_id)
    db.commit()
    return {k: str(getattr(item, k)) for k in ("gross_pay", "net_pay", "tds", "total_deductions",
                                              "au_statutory_deductions_total", "status")}


def _engine_result(country):
    from app.modules.payroll.engine.resolver import calculate_payroll

    if country == "PL":
        from tests._pl_engine_helpers import ctx
    else:
        from tests._my_engine_helpers import ctx
    try:
        result = calculate_payroll(ctx(), "standard")
    except Exception as blocked:  # noqa: BLE001 — a blocked outcome must be identical too
        return f"blocked: {type(blocked).__name__}: {blocked}"
    data = {k: v for k, v in vars(result).items() if k != "trace_id"}
    return json.dumps(data, sort_keys=True, default=str)


def test_other_countries_are_identical_with_empty_or_full_belgian_tables(db, organization, dormant, monkeypatch):
    from app.modules.payroll.engine.jurisdictions.malaysia import pcb

    # Malaysia's PCB is not built yet (it blocks until the HASiL specification is archived); the Malaysia tests'
    # own stand-in is used so the comparison covers a fully computed Malaysian result.
    monkeypatch.setattr(pcb, "compute", lambda pack, **_: {"pcb": Decimal("100.00"), "trace": {"stub": True}})
    empty = {"AU": _au_payslip(db, organization.id, "AU-E1"), "PL": _engine_result("PL"), "MY": _engine_result("MY")}
    _fill_belgium(db, monkeypatch, dormant)
    import sqlalchemy as sa

    filled = [t for t in _belgian_tables(db) if db.execute(sa.text(f'SELECT count(*) FROM "{t}"')).scalar()]
    assert len(filled) >= 8                                                         # Belgian data really present
    full = {"AU": _au_payslip(db, organization.id, "AU-E2"), "PL": _engine_result("PL"), "MY": _engine_result("MY")}
    assert full == empty
    assert empty["AU"]["status"] and "blocked" not in empty["PL"] and "blocked" not in empty["MY"]
