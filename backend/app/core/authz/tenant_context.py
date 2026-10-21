"""
core/authz/tenant_context.py
----------------------------
Data-layer enforcement of tenant and object scope (ZP-PRIV B02 / C03).

The PDP (policy.py) decides whether a request may run. This module makes
sure that, once it runs, the ORM can only ever see the rows the principal
is entitled to — even if a handler or service forgets a filter.

The context lives on the request's SQLAlchemy Session (``session.info``),
set by the PDP after an allow decision, so it follows exactly the session
the handler uses and never leaks between requests:

  * ``tenant``   — every SELECT/UPDATE/DELETE that touches a worker-level
    table (derived from Base.metadata, callgraph.worker_tables) gets an
    automatic ``organization_id = :org`` criterion, plus the principal's
    object scope (an employee-id set for a scoped payroll admin, a JIT
    support user, or an employee's own record).
  * ``platform`` — a platform principal (super_admin, support_operator,
    platform_security). Any ORM statement touching a worker-level table
    RAISES WorkerDataAccessDenied, unless the route is a reviewed aggregate
    or tenant-lifecycle route (``allow_worker_aggregate``), whose responses
    are k-suppressed counts only (super_admin/aggregates.py).
  * no context   — system code: schedulers, Celery tasks, migrations and the
    unit tests that call services directly. These set an explicit context
    when they act for one tenant (``tenant_session``).

On PostgreSQL the same context is pushed into the transaction with
``set_config('app.tenant_id', ..., true)`` at every transaction start, which
the RLS policies read (migration b8d4f2a6c1e3). SQLite has no RLS; this ORM
guard is the test-path equivalent.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, FrozenSet, Iterator, Optional, Tuple

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session, with_loader_criteria

logger = logging.getLogger("zoiko_payroll.authz.tenant_context")

INFO_KEY = "zp_tenant_ctx"

KIND_TENANT = "tenant"
KIND_PLATFORM = "platform"
KIND_SYSTEM = "system"


class WorkerDataAccessDenied(RuntimeError):
    """A platform principal's request reached a worker-level table."""


@dataclass(frozen=True)
class TenantContext:
    kind: str
    organization_id: Optional[int] = None
    # None = every worker in the organization. A frozenset restricts the
    # request to those PayrollEmployee ids (scoped admin, JIT grant, self).
    employee_ids: Optional[FrozenSet[int]] = None
    # Platform plane only: the route is a reviewed aggregate / lifecycle route.
    allow_worker_aggregate: bool = False

    @property
    def rls_tenant_id(self) -> str:
        return str(self.organization_id) if self.kind == KIND_TENANT and self.organization_id else ""


def set_context(db: Session, ctx: Optional[TenantContext]) -> None:
    if ctx is None:
        db.info.pop(INFO_KEY, None)
    else:
        db.info[INFO_KEY] = ctx
    _push_rls(db)


def get_context(db: Session) -> Optional[TenantContext]:
    return db.info.get(INFO_KEY)


@contextmanager
def tenant_session(db: Session, organization_id: int,
                   employee_ids: Optional[FrozenSet[int]] = None) -> Iterator[Session]:
    """Run system code (a job, a sweep) for exactly one tenant."""
    previous = get_context(db)
    set_context(db, TenantContext(KIND_TENANT, organization_id, employee_ids))
    try:
        yield db
    finally:
        set_context(db, previous)


@contextmanager
def platform_aggregate_scope(db: Session) -> Iterator[Session]:
    """Let a platform request compute k-suppressed aggregates over worker
    tables. Only super_admin/aggregates.py and the reviewed aggregate routes
    use this; the response must never carry an identity."""
    previous = get_context(db)
    if previous is not None and previous.kind == KIND_PLATFORM:
        set_context(db, TenantContext(KIND_PLATFORM, allow_worker_aggregate=True))
    try:
        yield db
    finally:
        if previous is not None and previous.kind == KIND_PLATFORM:
            set_context(db, previous)


# ── Worker-table registry (from metadata, not a hand list) ──────────────────

@lru_cache(maxsize=1)
def _worker_mappers() -> Tuple[Dict[type, str], FrozenSet[str]]:
    """mapped class -> scoping strategy, and the worker table-name set.

    Strategies: 'employee' (PayrollEmployee itself), 'org' (has
    organization_id), 'via_employee' (employee_id only), 'via_payslip'
    (payslip_item_id only)."""
    from app.core.authz.callgraph import worker_tables
    from app.database import Base

    tables = frozenset(worker_tables(Base.metadata))
    out: Dict[type, str] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = getattr(cls, "__tablename__", None)
        if table not in tables:
            continue
        cols = mapper.local_table.c
        if table == "payroll_employees":
            out[cls] = "employee"
        elif "organization_id" in cols:
            out[cls] = "org"
        elif "employee_id" in cols:
            out[cls] = "via_employee"
        elif "payslip_item_id" in cols:
            out[cls] = "via_payslip"
        else:  # pragma: no cover - worker_tables() guarantees one of these
            out[cls] = "unscopable"
    return out, tables


def worker_table_names() -> FrozenSet[str]:
    return _worker_mappers()[1]


def _criteria(ctx: TenantContext):
    from app.modules.payroll.models import PayrollEmployee, PayslipItem

    org = ctx.organization_id
    ids = tuple(sorted(ctx.employee_ids)) if ctx.employee_ids is not None else None
    if ids is None:
        emp_sub = select(PayrollEmployee.id).where(PayrollEmployee.organization_id == org)
    else:
        emp_sub = select(PayrollEmployee.id).where(
            PayrollEmployee.organization_id == org, PayrollEmployee.id.in_(ids))
    payslip_sub = select(PayslipItem.id).where(PayslipItem.employee_id.in_(emp_sub))

    opts = []
    for cls, strategy in _worker_mappers()[0].items():
        if strategy == "employee":
            if ids is None:
                opts.append(with_loader_criteria(
                    cls, lambda c: c.organization_id == org, include_aliases=True,
                    track_closure_variables=True))
            else:
                opts.append(with_loader_criteria(
                    cls, lambda c: (c.organization_id == org) & c.id.in_(ids),
                    include_aliases=True, track_closure_variables=True))
        elif strategy == "org":
            if ids is not None and "employee_id" in cls.__table__.c:
                opts.append(with_loader_criteria(
                    cls, lambda c: (c.organization_id == org) & c.employee_id.in_(ids),
                    include_aliases=True, track_closure_variables=True))
            elif ids is not None and "payslip_item_id" in cls.__table__.c:
                opts.append(with_loader_criteria(
                    cls, lambda c: (c.organization_id == org) & c.payslip_item_id.in_(payslip_sub),
                    include_aliases=True, track_closure_variables=True))
            else:
                opts.append(with_loader_criteria(
                    cls, lambda c: c.organization_id == org, include_aliases=True,
                    track_closure_variables=True))
        elif strategy == "via_employee":
            opts.append(with_loader_criteria(
                cls, lambda c: c.employee_id.in_(emp_sub), include_aliases=True,
                track_closure_variables=True))
        elif strategy == "via_payslip":
            opts.append(with_loader_criteria(
                cls, lambda c: c.payslip_item_id.in_(payslip_sub), include_aliases=True,
                track_closure_variables=True))
    return opts


def _statement_worker_tables(state) -> FrozenSet[str]:
    names = set()
    for mapper in state.all_mappers:
        table = getattr(mapper.class_, "__tablename__", None)
        if table:
            names.add(table)
    return frozenset(names) & worker_table_names()


@event.listens_for(Session, "do_orm_execute")
def _enforce_tenant_context(state) -> None:
    ctx: Optional[TenantContext] = state.session.info.get(INFO_KEY)
    if ctx is None or ctx.kind == KIND_SYSTEM:
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.is_column_load or state.is_relationship_load:
        # Lazy/relationship loads inherit criteria (propagate_to_loaders).
        return
    if ctx.kind == KIND_PLATFORM:
        if ctx.allow_worker_aggregate:
            return
        touched = _statement_worker_tables(state)
        if touched:
            raise WorkerDataAccessDenied(
                "platform principal statement touches worker-level tables: "
                + ", ".join(sorted(touched)))
        return
    if ctx.kind == KIND_TENANT:
        if ctx.organization_id is None:
            raise WorkerDataAccessDenied("tenant context without an organization")
        if _statement_worker_tables(state):
            state.statement = state.statement.options(*_criteria(ctx))


# ── PostgreSQL RLS session variable ─────────────────────────────────────────

def _push_rls(db: Session) -> None:
    """Apply the context to the CURRENT transaction (if one is open); the
    after_begin hook re-applies it to every later transaction of the
    session, so a mid-request commit cannot drop it."""
    try:
        bind = db.get_bind()
    except Exception:  # noqa: BLE001 - unbound session (tests), nothing to push
        return
    if bind.dialect.name != "postgresql" or not db.in_transaction():
        return
    _apply_pg_settings(db.connection(), get_context(db))


def _apply_pg_settings(connection, ctx: Optional[TenantContext]) -> None:
    tenant = ctx.rls_tenant_id if ctx else ""
    # app.rls_mode: 'tenant' | 'platform' | 'platform_aggregate' | 'system'
    if ctx is None or ctx.kind == KIND_SYSTEM:
        mode = "system"
    elif ctx.kind == KIND_PLATFORM:
        mode = "platform_aggregate" if ctx.allow_worker_aggregate else "platform"
    else:
        mode = "tenant"
    connection.execute(
        text("SELECT set_config('app.tenant_id', :t, true), set_config('app.rls_mode', :m, true)"),
        {"t": tenant, "m": mode},
    )


@event.listens_for(Session, "after_begin")
def _after_begin(session, transaction, connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    _apply_pg_settings(connection, session.info.get(INFO_KEY))
