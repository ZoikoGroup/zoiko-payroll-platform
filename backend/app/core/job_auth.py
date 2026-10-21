"""
core/job_auth.py
----------------
Authorization for work that runs outside the request (ZP-PRIV D08): Celery
tasks, FastAPI BackgroundTasks and scheduled report runs.

A job never trusts its payload. The enqueuer passes only ids
(``job_context(...)``): the requesting user, the tenant and the correlation
id. At execution - and again on every retry or replay - ``authorized_job``
re-loads that user and requires, from the database:

  * the user still exists, is active, is not an expired temporary login;
  * still holds one of the roles the job requires;
  * still belongs to the SAME organization the job names (a payload naming
    another tenant is a tenant swap and is refused);
  * the organization is still active (not suspended).

It then re-computes the user's object scope (entity / pay-group / grant) from
the database - never from the payload - binds the tenant context (ORM
criteria + PostgreSQL ``SET LOCAL app.tenant_id``) to the job's session and
re-binds the correlation id for its logs and audit rows. Any failure raises
JobAuthorizationError (the job fails closed, is not retried) and is recorded
as a ``JOB_DENIED`` security event.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import FrozenSet, Iterable, Iterator, Optional

from sqlalchemy.orm import Session

from app.core import correlation


class JobAuthorizationError(RuntimeError):
    """A job's principal or tenant no longer authorizes it."""


def job_context(user, *, organization_id: Optional[int] = None) -> dict:
    """What an enqueuer passes - ids only, never data."""
    return {
        "principal_user_id": getattr(user, "id", None),
        "organization_id": organization_id if organization_id is not None else getattr(user, "organization_id", None),
        "correlation_id": correlation.current() or correlation.new_id(),
    }


def _deny(db: Session, ctx: dict, task_name: str, reason: str) -> None:
    from app.modules.security import events as security_events

    security_events.emit(db, "JOB_DENIED", result="deny", actor_user_id=(ctx or {}).get("principal_user_id"),
                         organization_id=(ctx or {}).get("organization_id"), target_type="job",
                         target_id=task_name, reason_code=reason,
                         correlation_id=(ctx or {}).get("correlation_id"))
    raise JobAuthorizationError(f"{task_name}: {reason}")


@contextmanager
def authorized_job(db: Session, ctx: Optional[dict], *, task_name: str,
                   roles: Iterable[str] = ("org_admin", "payroll_admin"),
                   organization_id: Optional[int] = None, org_wide: bool = False) -> Iterator[dict]:
    """Re-authorize and scope one execution (or retry) of a job.

    ``org_wide`` keeps the tenant boundary but not the requester's object
    scope - for tenant-level system work the requester merely triggered
    (e.g. notifying every worker on a run they approved)."""
    from app.core.authz import scopes, tenant_context as tc
    from app.core.authz.principal import principal_from_user
    from app.modules.auth.models import User
    from app.modules.organizations.models import Organization

    if not ctx or not ctx.get("principal_user_id") or not ctx.get("organization_id"):
        _deny(db, ctx or {}, task_name, "MISSING_PRINCIPAL_CONTEXT")
    if organization_id is not None and organization_id != ctx["organization_id"]:
        _deny(db, ctx, task_name, "TENANT_SWAP")

    user = db.query(User).filter(User.id == ctx["principal_user_id"]).first()
    if user is None or not user.is_active:
        _deny(db, ctx, task_name, "PRINCIPAL_INACTIVE")
    if user.is_temporary and (user.access_expires_at is None or user.access_expires_at <= datetime.utcnow()):
        _deny(db, ctx, task_name, "TEMPORARY_ACCESS_ENDED")
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role not in set(roles):
        _deny(db, ctx, task_name, "ROLE_NO_LONGER_PERMITTED")
    if user.organization_id != ctx["organization_id"]:
        _deny(db, ctx, task_name, "TENANT_SWAP")
    org = db.query(Organization).filter(Organization.id == ctx["organization_id"]).first()
    if org is None or not org.is_active:
        _deny(db, ctx, task_name, "TENANT_SUSPENDED")

    principal = principal_from_user(user)
    employee_ids: Optional[FrozenSet[int]] = None if org_wide else scopes.employee_scope(db, principal)
    with correlation.bind(ctx.get("correlation_id")):
        with tc.tenant_session(db, ctx["organization_id"], employee_ids):
            yield {"user": user, "principal": principal, "employee_ids": employee_ids}


def scoped_employee_ids(db: Session, user) -> Optional[FrozenSet[int]]:
    """The employee scope to bake into a job at enqueue time (re-checked at
    execution anyway)."""
    from app.core.authz import scopes
    from app.core.authz.principal import principal_from_user

    return scopes.employee_scope(db, principal_from_user(user))


def requires_job_principal(task_name: str, *, roles: Iterable[str] = ("org_admin", "payroll_admin"),
                           org_wide: bool = True):
    """Decorator for Celery task bodies that open their own session: re-runs
    ``authorized_job`` (principal still active, same tenant, role still
    permitted, tenant not suspended) before EVERY execution, retry or replay.
    The task must be enqueued with ``job_ctx=job_context(user)``; a missing or
    stale context returns a "not authorized" result instead of raising, so
    autoretry never replays a denied job. The organization is the task's
    first positional argument (or ``organization_id=``)."""
    import functools

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(task_self, *args, job_ctx: Optional[dict] = None, **kwargs):
            import sys

            # The task module's own session factory (the one its body uses and
            # that tests and workers configure), never a second engine.
            session_factory = getattr(sys.modules.get(fn.__module__), "SessionLocal", None)
            if session_factory is None:
                from app.database import SessionLocal as session_factory
            organization_id = kwargs.get("organization_id", args[0] if args else None)
            db = session_factory()
            try:
                with authorized_job(db, job_ctx, task_name=task_name, roles=roles,
                                    organization_id=organization_id, org_wide=org_wide):
                    pass
            except JobAuthorizationError as exc:
                return {"error": "not authorized", "reason": str(exc).rsplit(": ", 1)[-1]}
            finally:
                db.close()
            with correlation.bind((job_ctx or {}).get("correlation_id")):
                return fn(task_self, *args, **kwargs)
        return wrapper
    return decorate
