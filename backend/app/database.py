"""
database.py
-----------
SQLAlchemy engine/session bootstrap for the standalone Payroll Platform.

Uses PAYROLL_DATABASE_URL (PostgreSQL in production; SQLite fallback in
development when the URL is empty). The schema is created fresh via
migrations/create_all on an empty database — there is no migration from,
or sync with, the main platform's database.
"""

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, exc, text  # type: ignore[import]
from sqlalchemy.orm import declarative_base, sessionmaker  # type: ignore[import]

from app.config import settings

logger = logging.getLogger("zoiko_payroll")


def _is_development_environment() -> bool:
    env_name = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()
    debug_flag = str(getattr(settings, "DEBUG", False)).strip().lower()
    return env_name == "development" or debug_flag in {"1", "true", "yes", "on"}


def resolve_database_url(raw_url: str | None = None) -> str:
    candidate_url = (raw_url or settings.PAYROLL_DATABASE_URL or "").strip()
    if not candidate_url:
        if _is_development_environment():
            logger.warning("PAYROLL_DATABASE_URL is empty. Using development SQLite fallback.")
            fallback_path = Path(__file__).resolve().parent / "data" / "payroll_dev.sqlite3"
            fallback_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{fallback_path.resolve()}"
        raise RuntimeError(
            "PAYROLL_DATABASE_URL is not configured. SQLite fallback is disabled in production. "
            "Please set PAYROLL_DATABASE_URL in your .env file."
        )

    parsed = urlparse(candidate_url)
    scheme = parsed.scheme.split("+")[0]
    if scheme in {"postgresql", "postgres"}:
        return candidate_url
    if candidate_url.startswith("sqlite"):
        return candidate_url
    if _is_development_environment():
        logger.warning("PAYROLL_DATABASE_URL has unrecognized scheme '%s'. Using development SQLite fallback.", scheme)
        fallback_path = Path(__file__).resolve().parent / "data" / "payroll_dev.sqlite3"
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{fallback_path.resolve()}"
    raise RuntimeError(
        f"PAYROLL_DATABASE_URL has unrecognized scheme '{parsed.scheme}'. "
        "Please verify your PAYROLL_DATABASE_URL configuration."
    )


resolved_database_url = resolve_database_url()

if resolved_database_url.startswith("sqlite"):
    engine = create_engine(
        resolved_database_url,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        resolved_database_url,
        connect_args={"sslmode": "require"},
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


Base = declarative_base()

def initialize_database() -> None:
    """Create all tables on the fresh, empty database (create_all).

    This is the intended bootstrap for the standalone platform: the DB
    starts empty and the schema is created in one shot. See
    migrations/create_all/README.md.
    """
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully.")
    except exc.SQLAlchemyError as exc_info:
        logger.error("Database initialization failed: %s", exc_info)
        raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# ── Model registration ─────────────────────────────────────────────────────
# Imported LAST (after every helper is defined) so that the payroll
# sub-package __init__ files — which eagerly import their routers, which in
# turn import get_db/SessionLocal from app.database — never see this module
# in a partially-initialized state. The standalone platform owns exactly
# these modules; nothing from the old platform (hr / employee / billing /
# comply / insights / time) is imported at runtime.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.organizations.models  # noqa: F401,E402
import app.modules.employee.models  # noqa: F401,E402
import app.modules.super_admin.models  # noqa: F401,E402
import app.modules.payroll.models  # noqa: F401,E402
import app.modules.payroll.policy.models  # noqa: F401,E402
import app.modules.payroll.enterprise.models  # noqa: F401,E402
import app.modules.payroll.mail.models  # noqa: F401,E402
