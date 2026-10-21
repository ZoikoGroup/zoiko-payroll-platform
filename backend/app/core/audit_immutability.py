"""
G5 F-6: audit rows are append-only at the database level.

PostgreSQL: migration d1e5a7c3b9f2 installs zoiko_reject_audit_mutation() and a
BEFORE UPDATE OR DELETE trigger on every table in AUDIT_TABLES. SQLite (tests):
the same rule is installed after `metadata.create_all` (listener below), so the
unit suite enforces it too.

The only way to remove audit rows is an explicit, logged purge scope
(`audit_purge_scope`): PostgreSQL sets the transaction-local setting
zoiko.audit_purge=on, which the trigger function honours for DELETE only;
SQLite uses a one-row flag table. UPDATE is never allowed. Today the only
caller is the Super Admin organisation hard-delete; retention purges will use
it once D-2 / D-3 are decided. Whether hard-delete may purge audit rows at all
is a Security / counsel decision (sign-off packet 03).
"""

import logging
from contextlib import contextmanager

from sqlalchemy import event, inspect, text

logger = logging.getLogger("zoiko_payroll.audit_immutability")

AUDIT_TABLES = (
    "payroll_tax_configuration_audit",
    "assisted_access_audit_events",
    "payroll_personal_data_access_events",
    "auth_audit_events",
    "authz_decision_events",
    "support_access_audit_events",
    "security_events",
    "security_event_anchors",
)
_SQLITE_FLAG = "zoiko_audit_purge_flag"


def install_sqlite_triggers(connection) -> None:
    connection.execute(text(f"CREATE TABLE IF NOT EXISTS {_SQLITE_FLAG} (reason TEXT)"))
    have = set(inspect(connection).get_table_names())
    for table in AUDIT_TABLES:
        if table not in have:
            continue
        connection.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'audit rows are append-only ({table})'); END"))
        connection.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
            f"WHEN (SELECT count(*) FROM {_SQLITE_FLAG}) = 0 "
            f"BEGIN SELECT RAISE(ABORT, 'audit rows are append-only ({table})'); END"))


def register(metadata) -> None:
    @event.listens_for(metadata, "after_create")
    def _after_create(target, connection, **kw):
        if connection.dialect.name == "sqlite":
            install_sqlite_triggers(connection)


@contextmanager
def audit_purge_scope(db, reason: str):
    """Allow DELETE (never UPDATE) of audit rows inside this block only."""
    dialect = db.get_bind().dialect.name
    logger.warning("[audit] purge scope opened: %s", reason)
    if dialect == "postgresql":
        db.execute(text("SELECT set_config('zoiko.audit_purge', 'on', true)"))
        try:
            yield
        finally:
            db.execute(text("SELECT set_config('zoiko.audit_purge', 'off', true)"))
    elif dialect == "sqlite":
        db.execute(text(f"CREATE TABLE IF NOT EXISTS {_SQLITE_FLAG} (reason TEXT)"))
        db.execute(text(f"INSERT INTO {_SQLITE_FLAG} (reason) VALUES (:r)"), {"r": reason[:200]})
        try:
            yield
        finally:
            db.execute(text(f"DELETE FROM {_SQLITE_FLAG}"))
    else:
        yield
