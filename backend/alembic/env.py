import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool

from alembic import context

# So `alembic` commands work when run from the backend/ directory (where
# alembic.ini lives) without needing the app already on PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Reuse the app's own engine/Base instead of duplicating URL-resolution
# logic (PAYROLL_DATABASE_URL / .env / sqlite dev fallback) here — this
# guarantees Alembic always targets the exact same database the app itself
# connects to. Importing app.database also imports every model module (see
# its own bottom-of-file imports), so Base.metadata is fully populated for
# autogenerate without listing each model here.
from app.database import Base, engine  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Neon auto-provisions this sample table in every new database — it's not
# part of the app schema, so exclude it or every autogenerate/check run
# proposes dropping it.
_IGNORED_TABLES = {"playing_with_neon"}


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and reflected and compare_to is None and name in _IGNORED_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection — uses the app's
    resolved URL so `alembic upgrade head --sql` matches the real target."""
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _command_name():
    """The alembic CLI command being run (upgrade, current, ...), or None when
    Alembic is driven programmatically."""
    cmd = getattr(getattr(config, "cmd_opts", None), "cmd", None)
    return getattr(cmd[0], "__name__", None) if cmd else None


def run_migrations_online() -> None:
    # Refuse a schema WRITE against a non-local database before connecting,
    # unless the deploy pipeline set the override (see scripts/_local_db_guard.py).
    from scripts._local_db_guard import assert_migration_target_allowed

    assert_migration_target_allowed(_command_name(), str(engine.url))
    with engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            # ZP-PRIV C.2: row-level security policies hide every row from a
            # connection that sets no context; migrations are system work.
            from sqlalchemy import text

            connection.execute(text("SELECT set_config('app.rls_mode', 'system', false)"))
            # Session-level setting (is_local=false) survives this commit. The
            # commit ends the transaction the execute() auto-began; without it
            # alembic's begin_transaction() below would nest inside it and the
            # migrations would be rolled back when the connection closes.
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
