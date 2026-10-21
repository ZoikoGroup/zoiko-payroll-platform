"""
tests/privacy/test_data_layer.py
--------------------------------
Data-layer enforcement (ZP-PRIV B02/B03/C03), field classes (B04/C04) and
small-cohort aggregates (A06).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.privacy._evidence import record

APP = Path(__file__).resolve().parents[2] / "app"


# ── Session-level tenant context (SQLite equivalent of RLS) ────────────────

def test_platform_context_cannot_read_worker_tables(db, world):
    from app.core.authz import tenant_context as tc
    from app.modules.payroll.models import PayrollEmployee

    tc.set_context(db, tc.TenantContext(tc.KIND_PLATFORM))
    try:
        with pytest.raises(tc.WorkerDataAccessDenied):
            db.query(PayrollEmployee).all()
        with pytest.raises(tc.WorkerDataAccessDenied):
            db.query(PayrollEmployee.name).filter(PayrollEmployee.id == world.employees["A1"].id).first()
    finally:
        tc.set_context(db, None)


def test_platform_aggregate_context_may_count_but_handlers_return_counts_only(db, world):
    from sqlalchemy import func

    from app.core.authz import tenant_context as tc
    from app.modules.payroll.models import PayrollEmployee

    tc.set_context(db, tc.TenantContext(tc.KIND_PLATFORM, allow_worker_aggregate=True))
    try:
        assert db.query(func.count(PayrollEmployee.id)).scalar() == 3
    finally:
        tc.set_context(db, None)


def test_tenant_context_filters_every_worker_query_to_its_scope(db, world):
    from sqlalchemy import func

    from app.core.authz import tenant_context as tc
    from app.modules.payroll.models import PayrollEmployee

    a = world.orgs["A"].id
    tc.set_context(db, tc.TenantContext(tc.KIND_TENANT, organization_id=a))
    try:
        assert {e.id for e in db.query(PayrollEmployee).all()} == {world.employees["A1"].id,
                                                                    world.employees["A2"].id}
        # Even an explicit filter on another tenant's id finds nothing.
        assert db.query(PayrollEmployee).filter(PayrollEmployee.id == world.employees["B1"].id).first() is None
        assert db.query(func.count(PayrollEmployee.id)).scalar() == 2
    finally:
        tc.set_context(db, None)
    tc.set_context(db, tc.TenantContext(tc.KIND_TENANT, organization_id=a,
                                        employee_ids=frozenset({world.employees["A1"].id})))
    try:
        assert [e.id for e in db.query(PayrollEmployee).all()] == [world.employees["A1"].id]
    finally:
        tc.set_context(db, None)


def test_child_worker_tables_without_organization_inherit_the_scope(db, world):
    from app.core.authz import tenant_context as tc
    from app.modules.payroll.models import EmployeeEstablishment

    for key in ("A1", "B1"):
        db.add(EmployeeEstablishment(employee_id=world.employees[key].id, province="ON",
                                     time_allocation_pct=100))
    db.commit()
    tc.set_context(db, tc.TenantContext(tc.KIND_TENANT, organization_id=world.orgs["A"].id))
    try:
        assert {r.employee_id for r in db.query(EmployeeEstablishment).all()} == {world.employees["A1"].id}
    finally:
        tc.set_context(db, None)


def test_every_worker_table_has_a_scoping_strategy():
    from app.core.authz import tenant_context as tc

    mappers, tables = tc._worker_mappers()
    assert len(tables) >= 59, "worker tables are derived from metadata"
    assert "unscopable" not in set(mappers.values())
    assert {m.__tablename__ for m in mappers} == set(tables)


_RAW_EMPLOYEE_QUERY = re.compile(r"query\(\s*PayrollEmployee\b")
# Ratchet (ZP-PRIV C.2): legacy call sites, all executed under the session-
# level tenant context (the data layer scopes them whatever they filter on).
# New code must use core/authz/scopes.py; this number may only go down.
_LEGACY_RAW_EMPLOYEE_QUERIES = 121


def test_no_new_raw_payroll_employee_queries():
    found = []
    for path in APP.rglob("*.py"):
        if path.name == "scopes.py" and path.parent.name == "authz":
            continue
        text = path.read_text(encoding="utf-8")
        found += [f"{path.relative_to(APP)}:{text[:m.start()].count(chr(10)) + 1}"
                  for m in _RAW_EMPLOYEE_QUERY.finditer(text)]
    assert len(found) <= _LEGACY_RAW_EMPLOYEE_QUERIES, (
        f"{len(found)} raw db.query(PayrollEmployee) call sites (ratchet {_LEGACY_RAW_EMPLOYEE_QUERIES}). "
        "Use app.core.authz.scopes.tenant_scoped(...) for new code.")


# ── Field classes ──────────────────────────────────────────────────────────

def test_every_payroll_employee_column_and_alias_has_a_field_class():
    from app.core.authz import fields
    from app.modules.payroll.models import PayrollEmployee
    from app.modules.payroll.schemas import EmployeeResponse

    columns = [c.name for c in PayrollEmployee.__table__.columns]
    missing = [c for c in columns if fields.field_class_of(c) is None]
    missing += [fields.to_camel(c) for c in columns if fields.field_class_of(fields.to_camel(c)) is None]
    missing += [n for n in EmployeeResponse.model_fields if fields.field_class_of(n) is None]
    missing += [f.serialization_alias for f in EmployeeResponse.model_fields.values()
                if f.serialization_alias and fields.field_class_of(f.serialization_alias) is None]
    assert not missing, f"unclassified worker fields: {missing}"
    assert set(fields.COLUMN_FIELD_CLASS.values()) <= fields.FIELD_CLASSES


def test_projection_drops_unticked_classes_and_unknown_keys_and_masks():
    from app.core.authz import fields

    rec = {"id": 1, "name": "N", "email": "e@x", "ctc": 1, "bankAccount": "GB00SYNTH12345678",
           "pan": "ABCDE1234F", "dateOfBirth": "1990-01-01", "unexpectedNewKey": "x"}
    out = fields.project_record(rec, {"identifier", "contact", "bank"}, "support_temp")
    assert "ctc" not in out and "pan" not in out and "unexpectedNewKey" not in out
    assert out["bankAccount"].endswith("5678") and out["bankAccount"].startswith("*")
    assert out["dateOfBirth"].startswith("*")
    assert fields.project_record(rec, {"identifier", "contact", "bank"}, "payroll_admin")["bankAccount"] == \
        "GB00SYNTH12345678", "tenant operators keep full values (bank files)"


# ── Aggregates: suppression and differencing ───────────────────────────────

def test_complementary_suppression_hides_a_recoverable_cell():
    from app.modules.super_admin import aggregates as ag

    cells = [{"n": 20}, {"n": 7}, {"n": 2}]
    ag.suppress_group(cells, "n", ())
    hidden = [c for c in cells if c["n"] == ag.SUPPRESSED]
    assert len(hidden) >= 2, "a lone hidden cell would be total minus the visible ones"


def test_money_cells_need_k_workers_and_two_organizations():
    from app.modules.super_admin import aggregates as ag

    row = {"gross": 100}
    assert ag.suppress_money_row(dict(row), 50, 1, ("gross",))["gross"] == ag.SUPPRESSED
    assert ag.suppress_money_row(dict(row), 4, 3, ("gross",))["gross"] == ag.SUPPRESSED
    assert ag.suppress_money_row(dict(row), 5, 2, ("gross",))["gross"] == 100


def test_two_overlapping_filters_cannot_isolate_one_person(client, world, db):
    from app.modules.payroll.models import PayrollEmployee

    a = world.orgs["A"].id
    for i in range(6):
        db.add(PayrollEmployee(organization_id=a, employee_code=f"A-1{i:03d}", name=f"Bulk {i}"))
    db.add(PayrollEmployee(organization_id=a, employee_code="A-TERM", name="The Leaver", status="Inactive"))
    db.commit()
    h = world.headers("SA")
    first = client.get(f"/api/super-admin/reports/employees?organization_id={a}", headers=h)
    assert first.status_code == 200
    second = client.get(f"/api/super-admin/reports/employees?organization_id={a}&status=Active", headers=h)
    assert second.status_code == 403
    assert second.json()["error"] == "AGGREGATE_DIFFERENCING_DETECTED"
    record(test_id="A06_differencing", role="super_admin", scope="platform", tenant_ids=world.tenant_ids(),
           endpoint="GET /api/super-admin/reports/employees", expected_status=403,
           actual_status=second.status_code, body=second.json(),
           note="9 vs 8 workers: the second, nested filter would isolate 1 person")


def test_query_budget_per_principal(client, world, monkeypatch):
    from app.modules.super_admin import aggregates as ag

    monkeypatch.setattr(ag, "BUDGET_MAX", 3)
    h = world.headers("SA")
    codes = [client.get("/api/super-admin/dashboard/stats", headers=h).status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


def test_finance_cells_are_suppressed_for_a_single_tenant(client, world, db):
    from datetime import date

    from app.modules.payroll.models import PayrollRun, PayslipItem

    a = world.orgs["A"].id
    run = PayrollRun(organization_id=a, run_code="R-1", period_label="Jan", period_start=date(2026, 1, 1),
                     period_end=date(2026, 1, 31), pay_date=date(2026, 1, 31), status="PAID",
                     total_gross=99999, total_net=88888, employee_count=2)
    db.add(run)
    db.flush()
    for key in ("A1", "A2"):
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=world.employees[key].id, organization_id=a,
                           employee_name="x"))
    db.commit()
    h = world.headers("SA")
    overview = client.get("/api/super-admin/finance/overview", headers=h).json()
    assert overview["items"] and all(c["grossPay"] == "<5, hidden" for c in overview["items"])
    assert "99999" not in str(overview) and "R-1" not in str(overview)
    by_org = client.get("/api/super-admin/finance/by-organization", headers=h).json()
    assert all("grossPay" not in o for o in by_org["organizations"])
    runs = client.get("/api/super-admin/payroll/runs", headers=h).json()
    assert "R-1" not in str(runs) and "88888" not in str(runs) and "Tenant A" not in str(runs)


def test_super_admin_tax_audit_feed_excludes_worker_entity_types(client, world, db):
    from app.modules.payroll.service import record_tax_audit

    record_tax_audit(db, actor_id=world.users["TA"].id, action="update", entity_type="payslip_item",
                     entity_id=world.employees["A1"].id, old_value={"net": 1}, new_value={"net": 2},
                     reason="correction")
    record_tax_audit(db, actor_id=world.users["SA"].id, action="update", entity_type="jurisdiction_pack",
                     entity_id=1, old_value={"v": 1}, new_value={"v": 2}, reason="pack")
    db.commit()
    feed = client.get("/api/super-admin/compliance/tax-configuration/audit", headers=world.headers("SA")).json()
    assert {e["entityType"] for e in feed} == {"jurisdiction_pack"}
    sec = client.get("/api/super-admin/security/audit?source=compliance", headers=world.headers("SA")).json()
    assert {e["entity_type"] for e in sec["entries"]} == {"jurisdiction_pack"}
