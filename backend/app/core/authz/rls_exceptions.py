"""
core/authz/rls_exceptions.py
----------------------------
Named exceptions to the generic ZP-PRIV row-level-security predicates
(migration d7f9b1c3e5a6, ``apply_rls()``).

``apply_rls()`` derives one predicate per table from the live schema: a table
with ``organization_id`` gets the tenant predicate (owner only). A table that
deliberately needs a DIFFERENT predicate is registered here, by name, with its
reason — and every migration that re-runs ``apply_rls()`` must call
``reapply_named_exceptions(bind)`` right after it, or the re-run silently
narrows the exception back to the generic predicate.
``tests/test_rls_named_exceptions.py`` enforces that statically (any migration
calling ``apply_rls(`` must also call ``reapply_named_exceptions(``) and proves
on PostgreSQL that a re-run followed by this helper restores each exception
exactly.

d7f9b1c3e5a6 itself is applied and never edited (alembic/MIGRATIONS_MANIFEST.txt):
this registry lives outside it on purpose. Owner: ZP-PRIV (review required).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

_VERSIONS = Path(__file__).resolve().parents[3] / "alembic" / "versions"


def _rls_base():
    spec = importlib.util.spec_from_file_location(
        "zp_rls_d7f9_exceptions", _VERSIONS / "d7f9b1c3e5a6_postgres_row_level_security.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class NamedPredicate:
    table: str
    introduced_by: str          # the migration that created the exception
    reason: str
    using: str                  # who may READ a row
    with_check: str             # who may WRITE a row


def named_exceptions() -> Dict[str, NamedPredicate]:
    rls = _rls_base()
    own = rls._TENANT_PREDICATE
    return {
        "payroll_mx_master_releases": NamedPredicate(
            table="payroll_mx_master_releases",
            introduced_by="e5b1d8f3a7c2",
            reason=("Mexico Phase 10f: a pilot organisation's one-time master-data release must be readable by the "
                    "owner (organization_id) AND the named live organisation (target_organization_id); only the "
                    "owner writes it. The row holds counts, masked RFCs and a hash — never a worker value."),
            # the generic tenant predicate, plus: the named target may read
            using=own[:-1] + f" OR ({rls._TENANT_MODE} AND target_organization_id = zoiko_rls_tenant()))",
            with_check=own,
        ),
    }


def reapply_named_exceptions(bind) -> List[str]:
    """Re-create each named exception's policy on PostgreSQL (tables that exist
    only). Call it right after any ``apply_rls()`` re-run. Returns the tables done."""
    if bind.dialect.name != "postgresql":
        return []
    from sqlalchemy import inspect

    rls = _rls_base()
    present = set(inspect(bind).get_table_names())
    done = []
    for table, p in named_exceptions().items():
        if table not in present:
            continue
        rls._sql(bind, f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        rls._sql(bind, f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        rls._sql(bind, f'DROP POLICY IF EXISTS {rls.POLICY} ON "{table}"')
        rls._sql(bind, f'CREATE POLICY {rls.POLICY} ON "{table}" USING {p.using} WITH CHECK {p.with_check}')
        done.append(table)
    return done
