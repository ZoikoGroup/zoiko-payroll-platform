"""Named RLS exceptions (app/core/authz/rls_exceptions.py, Mexico Phase 10g).

A re-run of the ZP-PRIV ``apply_rls()`` (migration d7f9b1c3e5a6, applied and
never edited) narrows every table back to its generic predicate — including a
table that deliberately has another one (payroll_mx_master_releases: the owner
AND the named target may read). So:

  * statically: every migration or script that calls ``apply_rls(`` must also
    call ``reapply_named_exceptions(`` (the two that ran before any exception
    existed are listed as historical);
  * on PostgreSQL (MX_PG6_TEST_URL → a throwaway database): the installed
    policy is captured, ``apply_rls()`` is re-run (and is shown to narrow it),
    then ``reapply_named_exceptions()`` restores it exactly, and its two-party
    behaviour is proven again with a non-bypass role.
"""

import ast
import os
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND = Path(__file__).resolve().parents[1]
# Ran before any named exception existed (both applied in production, never edited).
HISTORICAL = {
    "d7f9b1c3e5a6_postgres_row_level_security.py",
    "e1a3c5e7f9b2_security_events_alerts_machine_clients.py",
    # This migration was authored on the country-entitlement branch before
    # the Mexico named exception existed in its ancestry. It is immutable;
    # the follow-up merge migration reapplies exceptions after both heads.
    "b4d6f8a0c2e3_organization_jurisdictions.py",
}


def _calls(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None))
    return names


def test_every_apply_rls_rerun_also_reapplies_the_named_exceptions():
    offenders = []
    for folder in (BACKEND / "alembic" / "versions", BACKEND / "scripts", BACKEND / "app"):
        for path in folder.rglob("*.py"):
            if path.name in HISTORICAL:
                continue
            calls = _calls(path)
            if "apply_rls" in calls and "reapply_named_exceptions" not in calls:
                offenders.append(str(path.relative_to(BACKEND)))
    assert not offenders, ("these re-run apply_rls() without reapply_named_exceptions(bind) afterwards — the "
                           f"named exceptions would be narrowed back: {offenders}")


def test_the_registry_names_its_reason_and_origin():
    from app.core.authz.rls_exceptions import named_exceptions

    ex = named_exceptions()
    assert set(ex) == {"payroll_mx_master_releases"}
    p = ex["payroll_mx_master_releases"]
    assert p.introduced_by == "e5b1d8f3a7c2" and p.reason
    assert "target_organization_id = zoiko_rls_tenant()" in p.using and "target_organization_id" not in p.with_check


PG_URL = os.getenv("MX_PG6_TEST_URL")
pg = pytest.mark.skipif(not PG_URL, reason="MX_PG6_TEST_URL not set (throwaway PostgreSQL only)")


def _module(name):
    import importlib.util

    path = next((BACKEND / "alembic" / "versions").glob(f"{name}_*.py"))
    spec = importlib.util.spec_from_file_location(f"zp_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _policy(c):
    return tuple(c.execute(sa.text("SELECT qual, with_check FROM pg_policies "
                                   "WHERE tablename = 'payroll_mx_master_releases'")).one())


@pytest.fixture()
def pg_engine():
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    assert "mx6run" in PG_URL and "127.0.0.1" in PG_URL, "refusing a non-throwaway PostgreSQL URL"
    eng = sa.create_engine(PG_URL)
    with eng.begin() as c:
        c.execute(sa.text("DROP SCHEMA public CASCADE"))
        c.execute(sa.text("CREATE SCHEMA public"))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pg
def test_pg_a_rerun_of_apply_rls_then_the_helper_preserves_the_two_party_predicate(pg_engine):
    from sqlalchemy.orm import Session

    from app.core.authz.rls_exceptions import reapply_named_exceptions
    from app.modules.organizations.models import Organization

    eng = pg_engine
    rls, m15 = _module("d7f9b1c3e5a6"), _module("e5b1d8f3a7c2")
    with eng.begin() as c:                                         # production: d7f9 applied, then m15's policy
        rls.apply_rls(c, unset_mode="system")
        m15._rls_for_release_table(c)
        installed = _policy(c)
    with eng.begin() as c:                                         # the hazard: a later re-run narrows it
        rls.apply_rls(c)
        narrowed = _policy(c)
    assert "target_organization_id" in installed[0] and "target_organization_id" not in narrowed[0]
    with eng.begin() as c:                                         # the fix: the helper right after the re-run
        assert reapply_named_exceptions(c) == ["payroll_mx_master_releases"]
        restored = _policy(c)
    assert restored == installed
    print(f"\nMEASURED: apply_rls() re-run narrowed the release policy; reapply_named_exceptions() restored it "
          f"exactly (USING and WITH CHECK identical to m15's)")

    with Session(eng) as s:                                        # and it behaves as before
        orgs = [Organization(organization_name=x, organization_code=x, workspace_type="EVALUATION")
                for x in ("RXA", "RXB", "RXC")]
        s.add_all(orgs)
        s.commit()
        owner, target, other = (o.id for o in orgs)
    with eng.begin() as c:
        c.execute(sa.text("SELECT set_config('app.rls_mode', 'system', true)"))
        c.execute(sa.text("INSERT INTO payroll_mx_master_releases (organization_id, target_organization_id, status, "
                          "reason, plan, plan_sha256) VALUES (:o, :t, 'RELEASED', 'SYNTHETIC', '{}', :h)"),
                  {"o": owner, "t": target, "h": "0" * 64})
    with eng.connect() as c:
        if not c.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'zp_rls_probe'")).scalar():
            c.execute(sa.text("CREATE ROLE zp_rls_probe NOLOGIN NOBYPASSRLS"))
        for grant in ("GRANT USAGE ON SCHEMA public TO zp_rls_probe",
                      "GRANT SELECT ON zoiko_rls_settings TO zp_rls_probe",
                      "GRANT SELECT, INSERT ON payroll_mx_master_releases TO zp_rls_probe",
                      "GRANT USAGE ON SEQUENCE payroll_mx_master_releases_id_seq TO zp_rls_probe"):
            c.execute(sa.text(grant))
        c.commit()

    def seen(org):
        with eng.connect() as c:
            c.execute(sa.text("SET ROLE zp_rls_probe"))
            c.execute(sa.text("SELECT set_config('app.rls_mode', 'tenant', false), set_config('app.tenant_id', :t, false)"),
                      {"t": str(org)})
            n = c.execute(sa.text("SELECT count(*) FROM payroll_mx_master_releases")).scalar()
            c.execute(sa.text("RESET ROLE"))
            return n

    assert (seen(owner), seen(target), seen(other)) == (1, 1, 0)
