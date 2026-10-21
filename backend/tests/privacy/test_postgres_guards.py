"""
tests/privacy/test_postgres_guards.py
-------------------------------------
Real PostgreSQL proof of the database-level guarantees (ZP-PRIV C.2, D.2,
D.4): row-level security, append-only audit triggers (JSON compared as
jsonb, set-once hash), the 30-minute window CHECK and self-approval CHECKs.

Runs only when ZP_TEST_POSTGRES_URL points at a DISPOSABLE database whose
user may create roles (CI: the privacy-isolation job's postgres service).
The schema is rebuilt from the models, the exact DDL of migrations
c5e7a9b1d3f4 / d7f9b1c3e5a6 is applied, and the assertions run as a
NOBYPASSRLS, non-owner application role - the production requirement.
"""

from __future__ import annotations

import importlib.util
import importlib
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from tests.privacy._evidence import record

PG_URL = os.environ.get("ZP_TEST_POSTGRES_URL")
if not PG_URL and os.environ.get("ZP_REQUIRE_POSTGRES_TESTS") == "1":
    # The CI privacy-isolation job provides a Postgres service: a missing URL
    # there is a broken gate, not a reason to skip.
    raise RuntimeError("ZP_REQUIRE_POSTGRES_TESTS=1 but ZP_TEST_POSTGRES_URL is not set")
pytestmark = pytest.mark.skipif(not PG_URL, reason="ZP_TEST_POSTGRES_URL not set (disposable Postgres only)")

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
APP_ROLE, APP_PASSWORD = "zp_priv_app", "zp_priv_app_pw"
_GENERIC_AUDIT = ("payroll_tax_configuration_audit", "assisted_access_audit_events",
                  "payroll_personal_data_access_events", "auth_audit_events", "authz_decision_events")


def _ddl(conn, statement):
    conn.execute(text(statement))


def _migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pg():
    from app.database import Base
    for module in ("organizations", "auth", "payroll", "billing", "communications", "support_access",
                   "security", "assisted_access"):  # register every table (incl. audit trigger tables)
        importlib.import_module(f"app.modules.{module}.models")

    owner = create_engine(PG_URL, connect_args={"sslmode": "disable"} if "sslmode" not in PG_URL else {})
    with owner.begin() as conn:
        _ddl(conn, "DROP SCHEMA public CASCADE")
        _ddl(conn, "CREATE SCHEMA public")
    Base.metadata.create_all(owner)
    with owner.begin() as conn:
        _ddl(conn, """
            CREATE OR REPLACE FUNCTION zoiko_reject_audit_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' AND current_setting('zoiko.audit_purge', true) = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'audit rows are append-only (%: % refused)', TG_TABLE_NAME, TG_OP
                    USING ERRCODE = 'insufficient_privilege';
            END;
            $$;
        """)
        for table in _GENERIC_AUDIT:
            _ddl(conn, f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                                 f"FOR EACH ROW EXECUTE FUNCTION zoiko_reject_audit_mutation()")
        _migration("c5e7a9b1d3f4_mfa_refresh_rotation_support_access").install_postgres_guards(conn)
        _migration("e1a3c5e7f9b2_security_events_alerts_machine_clients").install_postgres_guards(conn)
        rls = _migration("d7f9b1c3e5a6_postgres_row_level_security").apply_rls(conn)
        _ddl(conn, f"DROP ROLE IF EXISTS {APP_ROLE}")
        _ddl(conn, f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS")
        _ddl(conn, f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
        _ddl(conn, f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
        _ddl(conn, f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    # Seed two tenants through the ORM (system context: no tenant set).
    from app.modules.auth.models import User, UserRole
    from app.modules.organizations.models import Organization
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee

    seed = sessionmaker(bind=owner)()
    for oid, code, country in ((1, "PGA", "GB"), (2, "PGB", "NL")):
        seed.add(Organization(id=oid, organization_name=f"Tenant {code}", organization_code=code,
                              workspace_type="EVALUATION", is_active=True))
        seed.flush()
        seed.add(CompanyComplianceDetails(organization_id=oid, jurisdiction_country=country))
        for e in (1, 2):
            seed.add(PayrollEmployee(organization_id=oid, employee_code=f"{code}-{e}", name=f"Synthetic {code}{e}"))
    seed.add(User(id=901, email="op@x.example", hashed_password="x", role=UserRole.SUPPORT_OPERATOR,
                  first_name="o", last_name="p", is_active=True, is_verified=True))
    seed.add(User(id=902, email="ad@x.example", hashed_password="x", role=UserRole.ORG_ADMIN, organization_id=1,
                  first_name="a", last_name="d", is_active=True, is_verified=True))
    seed.commit()
    seed.close()
    url = make_url(PG_URL).set(username=APP_ROLE, password=APP_PASSWORD)
    app_engine = create_engine(url, connect_args={"sslmode": "disable"} if "sslmode" not in PG_URL else {})
    yield {"owner": owner, "app": app_engine, "rls": rls}
    app_engine.dispose()
    owner.dispose()


def _rows(engine, sql, mode=None, tenant=None):
    with engine.begin() as conn:
        if mode is not None:
            conn.execute(text("SELECT set_config('app.rls_mode', :m, true), set_config('app.tenant_id', :t, true)"),
                         {"m": mode, "t": str(tenant or "")})
        return conn.execute(text(sql)).fetchall()


def test_rls_policies_exist_on_every_derived_worker_and_tenant_table(pg):
    assert "payroll_employees" in pg["rls"]["worker"] and "payslip_items" in pg["rls"]["worker"]
    assert len(pg["rls"]["worker"]) >= 59
    with pg["owner"].connect() as conn:
        forced = {r[0] for r in conn.execute(text(
            "SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity"))}
    assert set(pg["rls"]["worker"]) | set(pg["rls"]["tenant"]) <= forced


def test_raw_select_without_tenant_context_returns_nothing(pg):
    assert _rows(pg["app"], "SELECT id FROM payroll_employees") == []
    assert _rows(pg["app"], "SELECT organization_id FROM payroll_company_compliance") == []
    record(test_id="PG_RLS_no_context", role="app_role(NOBYPASSRLS)", scope="none",
           tenant_ids={"A": 1, "B": 2}, endpoint="SELECT payroll_employees", expected_status=0, actual_status=0,
           note="raw SELECT with no app.rls_mode returns 0 rows")


def test_tenant_context_sees_only_its_own_rows_and_cross_tenant_is_empty(pg):
    own = _rows(pg["app"], "SELECT organization_id FROM payroll_employees", "tenant", 1)
    assert {r[0] for r in own} == {1} and len(own) == 2
    assert _rows(pg["app"], "SELECT id FROM payroll_employees WHERE organization_id = 2", "tenant", 1) == []
    with pytest.raises(DBAPIError):
        with pg["app"].begin() as conn:
            conn.execute(text("SELECT set_config('app.rls_mode', 'tenant', true), "
                              "set_config('app.tenant_id', '1', true)"))
            conn.execute(text("INSERT INTO payroll_employees (organization_id, employee_code, name, employment_type, "
                              "status, compliance_fields, custom_fields, pay_frequency, w4_step2_checkbox, "
                              "is_nonresident_alien, remote_work_agreement, reciprocity_certificate_on_file, "
                              "residency_certification_on_file, has_postgrad_loan) VALUES (2, 'X', 'X', 'Full-time', "
                              "'Active', '{}', '{}', 'Monthly', false, false, false, false, false, false)"))


def test_platform_mode_sees_no_worker_rows_but_the_registry(pg):
    assert _rows(pg["app"], "SELECT id FROM payroll_employees", "platform") == []
    assert len(_rows(pg["app"], "SELECT organization_id FROM payroll_company_compliance", "platform")) == 2
    assert _rows(pg["app"], "SELECT count(*) FROM payroll_employees", "platform_aggregate")[0][0] == 4


def test_orm_tenant_context_survives_a_mid_request_commit(pg):
    from app.core.authz import tenant_context as tc
    from app.modules.payroll.models import PayrollEmployee

    session = sessionmaker(bind=pg["app"])()
    try:
        tc.set_context(session, tc.TenantContext(tc.KIND_TENANT, organization_id=2))
        assert {e.organization_id for e in session.query(PayrollEmployee).all()} == {2}
        session.commit()  # new transaction: after_begin re-applies SET LOCAL
        assert {e.organization_id for e in session.query(PayrollEmployee).all()} == {2}
    finally:
        tc.set_context(session, None)
        session.close()


def test_application_role_is_reported_as_enforcing_rls(pg):
    from app.database import check_row_level_security

    assert check_row_level_security(pg["app"])["enforced"] is True
    assert check_row_level_security(pg["owner"])["enforced"] is False  # superuser bypasses


def test_support_audit_is_append_only_with_set_once_hash_and_jsonb_compare(pg):
    with pg["owner"].begin() as conn:
        _ddl(conn, "SELECT set_config('app.rls_mode', 'system', true)")
        rid = conn.execute(text(
            "INSERT INTO support_access_audit_events (recorded_at, event_type, detail) "
            "VALUES (now(), 'REQUESTED', CAST(:d AS json)) RETURNING id"), {"d": '{"a": 1}'}).scalar()
    with pg["owner"].begin() as conn:  # NULL -> value, everything else unchanged: allowed once
        conn.execute(text("UPDATE support_access_audit_events SET row_hash = 'h1' WHERE id = :i"), {"i": rid})
    for sql in ("UPDATE support_access_audit_events SET row_hash = 'h2' WHERE id = :i",
                "UPDATE support_access_audit_events SET reason = 'x' WHERE id = :i",
                "UPDATE support_access_audit_events SET detail = CAST('{\"a\": 2}' AS json) WHERE id = :i",
                "DELETE FROM support_access_audit_events WHERE id = :i"):
        with pytest.raises(DBAPIError):
            with pg["owner"].begin() as conn:
                conn.execute(text(sql), {"i": rid})
    record(test_id="PG_support_audit_tamper", role="table owner", scope="support_access_audit_events",
           tenant_ids=None, endpoint="UPDATE/DELETE", expected_status=0, actual_status=0,
           note="hash set once; re-hash, field edit, json edit and delete all refused")


def test_generic_audit_tables_refuse_update_and_delete(pg):
    with pg["owner"].begin() as conn:
        _ddl(conn, "SELECT set_config('app.rls_mode', 'system', true)")
        rid = conn.execute(text(
            "INSERT INTO authz_decision_events (decision_id, created_at, principal_role, method, route_template, "
            "action, resource, data_class, reason_code, status_code) VALUES ('d1', now(), 'super_admin', 'GET', "
            "'/x', 'read', 'x', 'worker', 'ROLE_NOT_PERMITTED', 403) RETURNING id")).scalar()
    for sql in ("UPDATE authz_decision_events SET reason_code = 'ALLOW' WHERE id = :i",
                "DELETE FROM authz_decision_events WHERE id = :i"):
        with pytest.raises(DBAPIError):
            with pg["owner"].begin() as conn:
                conn.execute(text(sql), {"i": rid})


def test_grant_window_and_self_approval_checks(pg):
    now = datetime.utcnow()
    base = ("INSERT INTO support_access_grants (organization_id, requested_by_user_id, reason, ticket_reference, "
            "requested_minutes, status, correlation_id, scope_type, requested_at, activated_at, expires_at, "
            "approved_by_user_id, scope_narrowed, zoiko_required, is_break_glass) VALUES (1, :req, 'r', 't', 30, "
            ":st, 'c', 'diagnostics', :now, :act, :exp, :appr, false, false, false)")
    bad = [
        {"req": 901, "st": "active", "now": now, "act": now, "exp": now + timedelta(minutes=31), "appr": 902},
        {"req": 901, "st": "expired", "now": now, "act": now, "exp": now + timedelta(minutes=5), "appr": 901},
    ]
    for params in bad:
        with pytest.raises(IntegrityError):
            with pg["owner"].begin() as conn:
                _ddl(conn, "SELECT set_config('app.rls_mode', 'system', true)")
                conn.execute(text(base), params)
    with pg["owner"].begin() as conn:
        _ddl(conn, "SELECT set_config('app.rls_mode', 'system', true)")
        conn.execute(text(base), {"req": 901, "st": "active", "now": now, "act": now,
                                  "exp": now + timedelta(minutes=30), "appr": 902})
    with pytest.raises(IntegrityError):  # one live grant per operator
        with pg["owner"].begin() as conn:
            _ddl(conn, "SELECT set_config('app.rls_mode', 'system', true)")
            conn.execute(text(base), {"req": 901, "st": "pending_approval", "now": now, "act": None,
                                      "exp": None, "appr": None})


def test_security_events_chain_on_postgres_and_tamper_is_refused(pg):
    """E02 on real Postgres: emit() chains rows, the owner cannot edit or
    delete them (trigger), and verify_chain() still passes afterwards."""
    from sqlalchemy.orm import sessionmaker

    from app.modules.security import events

    session = sessionmaker(bind=pg["owner"])()
    try:
        session.execute(text("SELECT set_config('app.rls_mode', 'system', false)"))
        first = events.emit(pg["owner"], "PDP_DENY", result="deny", actor_user_id=901, actor_role="super_admin",
                            reason_code="ROLE_NOT_PERMITTED", correlation_id="pg-e02-1")
        second = events.emit(pg["owner"], "PRIVILEGED_READ", result="allow", actor_user_id=901,
                             correlation_id="pg-e02-2")
        assert first is not None and second is not None and second.prev_hash == first.row_hash
        for sql in ("UPDATE security_events SET reason_code = 'ALLOW' WHERE id = :i",
                    "UPDATE security_events SET row_hash = 'forged' WHERE id = :i",
                    "DELETE FROM security_events WHERE id = :i"):
            with pytest.raises(DBAPIError):
                with pg["owner"].begin() as conn:
                    conn.execute(text(sql), {"i": first.id})
        assert events.verify_chain(session)["ok"] is True
        sink = events.FakeSink()
        anchor = events.anchor(session, sink)
        assert anchor.last_row_hash == second.row_hash
        with pytest.raises(DBAPIError):
            with pg["owner"].begin() as conn:
                conn.execute(text("UPDATE security_event_anchors SET last_row_hash = 'x' WHERE id = :i"),
                             {"i": anchor.id})
    finally:
        session.close()
    record(test_id="PG_security_events_tamper", role="table owner", scope="security_events",
           tenant_ids=None, endpoint="UPDATE/DELETE", expected_status=0, actual_status=0,
           note="chained on Postgres; edit, re-hash and delete refused by trigger; anchor append-only")


def test_security_event_chain_survives_concurrent_writers(pg, monkeypatch):
    """E02: several writers (separate connections, as separate workers would
    be) never fork the chain - the advisory lock serializes the head read."""
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy.orm import sessionmaker

    import contextlib

    from app.modules.security import events

    # Disable the in-process lock: only the database advisory lock may
    # serialize the writers, exactly as for separate worker processes.
    monkeypatch.setattr(events, "_chain_lock", contextlib.nullcontext())

    def write(i):
        return events.emit(pg["owner"], "PRIVILEGED_READ", result="allow", actor_user_id=901,
                           correlation_id=f"pg-concurrent-{i}") is not None

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(write, range(40)))
    session = sessionmaker(bind=pg["owner"])()
    try:
        session.execute(text("SELECT set_config('app.rls_mode', 'system', false)"))
        assert events.verify_chain(session)["ok"] is True
    finally:
        session.close()


def test_audit_purge_flag_alone_does_not_unlock_deletes(pg):
    """E02: any role can set zoiko.audit_purge; only members of
    zoiko_audit_purger (never the application role) can purge with it."""
    def insert():
        with pg["owner"].begin() as conn:
            _ddl(conn, "SELECT set_config('app.rls_mode', 'system', true)")
            return conn.execute(text(
                "INSERT INTO authz_decision_events (decision_id, created_at, principal_role, method, route_template, "
                "action, resource, data_class, reason_code, status_code) VALUES ('purge', now(), 'x', 'GET', '/x', "
                "'read', 'x', 'worker', 'R', 403) RETURNING id")).scalar()

    def purge(rid):  # as the NOBYPASSRLS, non-superuser application role
        with pg["app"].begin() as conn:
            _ddl(conn, "SELECT set_config('app.rls_mode', 'system', true)")
            _ddl(conn, "SELECT set_config('zoiko.audit_purge', 'on', true)")
            conn.execute(text("DELETE FROM authz_decision_events WHERE id = :i"), {"i": rid})

    rid = insert()
    with pg["owner"].begin() as conn:
        _ddl(conn, "DROP ROLE IF EXISTS zoiko_audit_purger")
    with pytest.raises(DBAPIError):
        purge(rid)                                   # flag set, role does not exist
    with pg["owner"].begin() as conn:
        _ddl(conn, "CREATE ROLE zoiko_audit_purger NOLOGIN")
    with pytest.raises(DBAPIError):
        purge(rid)                                   # role exists, app role not a member
    try:
        with pg["owner"].begin() as conn:
            _ddl(conn, f"GRANT zoiko_audit_purger TO {APP_ROLE}")
        purge(rid)                                   # member + flag: allowed
        with pg["owner"].connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM authz_decision_events WHERE id = :i"),
                                {"i": rid}).scalar() == 0
    finally:
        with pg["owner"].begin() as conn:
            _ddl(conn, f"REVOKE zoiko_audit_purger FROM {APP_ROLE}")
            _ddl(conn, "DROP ROLE IF EXISTS zoiko_audit_purger")


def test_exceptions_stuck_review_count_handles_tz_aware_timestamps(pg):
    """Postgres returns tz-aware updated_at; the stuck-review check compared
    it with a naive cutoff and raised (HTTP 500) once any run was in Review."""
    from datetime import date, datetime, timedelta, timezone

    from sqlalchemy.orm import sessionmaker

    from app.modules.payroll.models import PayrollRun
    from app.modules.super_admin.command_center_router import list_exceptions

    db = sessionmaker(bind=pg["owner"])()
    try:
        db.execute(text("SELECT set_config('app.rls_mode', 'system', false)"))
        old = datetime.now(timezone.utc) - timedelta(days=10)
        db.add(PayrollRun(organization_id=1, period_label="Stuck", period_start=date(2026, 1, 1),
                          period_end=date(2026, 1, 31), pay_date=date(2026, 2, 1), status="Review",
                          created_at=old, updated_at=old))
        db.commit()
        out = list_exceptions(stuck_review_days=3, db=db, _admin=None)
        assert out["stuck_reviews"]["run_count"] >= 1
    finally:
        db.close()
