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


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
