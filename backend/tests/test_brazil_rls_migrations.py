"""Row-level security for the Brazil tables (ZP-PRIV d7f9b1c3e5a6).

d7f9b1c3e5a6 put a policy only on tables that existed when it ran, so each
Brazil revision after it gives its own tables the policy d7f9b1c3e5a6 would
derive (the mx_ptu_m10 pattern):

  a6ca8aab2043  payroll_br_establishments  — gains organization_id: TENANT
  64424fd61652  risk assignments, CPRB options, credential refs: TENANT
  b9f3a7c2e5d1  concurrent-INSS, alimony, VT: WORKER, strategy "org"

The real classify() runs on the model schema (its _schema() swapped for the
metadata, the only database-specific part), and each revision's emitted SQL is
captured — so a model change that reclassifies a table, or a revision that
applies the wrong predicate, fails here without a PostgreSQL server.
"""
import importlib.util
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

TENANT = ("payroll_br_establishments", "payroll_br_risk_assignments", "payroll_br_cprb_options",
          "payroll_br_credential_refs")
WORKER_ORG = ("payroll_br_concurrent_inss_declarations", "payroll_br_alimony_orders",
              "payroll_br_vale_transporte_elections")
# Created by b7a1c9e3d5f2 with organization_id, so d7f9b1c3e5a6 already covers them.
COVERED_BY_D7F9 = ("payroll_br_employer_profiles", "payroll_br_rubrics")


def _load(prefix):
    path = next(VERSIONS.glob(f"{prefix}_*.py"))
    spec = importlib.util.spec_from_file_location(f"rev_{prefix}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def classified():
    import app.modules.payroll.models  # noqa: F401
    from app.database import Base

    rls = _load("d7f9b1c3e5a6")
    cols, fks = {}, {}
    for name, table in Base.metadata.tables.items():
        cols[name] = {c.name for c in table.columns}
        fks[name] = {fk.column.table.name for fk in table.foreign_keys}
    rls._schema = lambda bind: (cols, fks, set(Base.metadata.tables))
    worker, tenant = rls.classify(None)
    return rls, worker, set(tenant)


class _CaptureBind:
    class dialect:
        name = "postgresql"

    def __init__(self):
        self.sql = []

    def execute(self, clause, *a, **k):
        self.sql.append(" ".join(str(clause).split()))


def _policies(statements):
    """{table: predicate} from the CREATE POLICY statements a revision emits."""
    out = {}
    for s in statements:
        if s.startswith("CREATE POLICY"):
            table = s.split(' ON "', 1)[1].split('"', 1)[0]
            out[table] = s.split(" USING ", 1)[1].split(" WITH CHECK ", 1)[0]
    return out


def test_classify_agrees_with_the_policies_the_revisions_apply(classified):
    rls, worker, tenant = classified
    for table in TENANT + COVERED_BY_D7F9:
        assert table in tenant and table not in worker, table
    for table in WORKER_ORG:
        assert worker.get(table) == "org", table


def test_every_brazil_table_has_a_policy_source(classified):
    _rls, worker, tenant = classified
    brazil = {t for t in set(worker) | tenant if t.startswith("payroll_br_")}
    assert brazil == set(TENANT + WORKER_ORG + COVERED_BY_D7F9)


@pytest.mark.parametrize("prefix, fn, expected", [
    ("64424fd61652", "_rls_for_new_tables", {t: "tenant" for t in TENANT[1:]}),
    ("b9f3a7c2e5d1", "_rls_for_new_tables", {t: "org" for t in WORKER_ORG}),
    ("a6ca8aab2043", "_rls_for_establishments", {"payroll_br_establishments": "tenant"}),
])
def test_revision_emits_the_derived_policy(classified, prefix, fn, expected):
    rls = classified[0]
    bind = _CaptureBind()
    getattr(_load(prefix), fn)(bind)
    want = {t: " ".join((rls._TENANT_PREDICATE if kind == "tenant" else rls._worker_predicate(kind)).split())
            for t, kind in expected.items()}
    assert _policies(bind.sql) == want
    for table in expected:
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in bind.sql
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in bind.sql
