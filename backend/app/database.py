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
        _seed_reference_content()
    except exc.SQLAlchemyError as exc_info:
        logger.error("Database initialization failed: %s", exc_info)
        raise


def _seed_reference_content() -> None:
    """Seed Assist reference content (governed KB, capabilities, suggestions)."""
    try:
        from app.modules.assist import knowledge as assist_knowledge
        from app.modules.assist.models import (
            AssistCapability,
            AssistNotice,
            AssistSuggestion,
        )

        db = SessionLocal()
        try:
            assist_knowledge.ensure_default_kb(db)

            if db.query(AssistCapability).count() == 0:
                db.add_all(
                    [
                        AssistCapability(
                            capability_id="assist.answer",
                            name="Ask about payroll",
                            description="Explain payroll concepts and procedures using governed knowledge.",
                            risk_tier="A1",
                            requires_confirmation=0,
                            enabled=1,
                            order_index=1,
                        ),
                        AssistCapability(
                            capability_id="payroll.getRunReadiness",
                            name="Run readiness summary",
                            description="Summarize payroll run readiness and blockers.",
                            risk_tier="A1",
                            requires_confirmation=0,
                            enabled=1,
                            order_index=2,
                        ),
                        AssistCapability(
                            capability_id="payroll.listExceptions",
                            name="List exceptions",
                            description="List exceptions for a payroll run.",
                            risk_tier="A1",
                            requires_confirmation=0,
                            enabled=1,
                            order_index=3,
                        ),
                        AssistCapability(
                            capability_id="payroll.assignException",
                            name="Assign exception",
                            description="Assign an exception to an owner for follow-up.",
                            risk_tier="A3",
                            requires_confirmation=1,
                            enabled=1,
                            order_index=4,
                        ),
                        AssistCapability(
                            capability_id="payroll.addExceptionNote",
                            name="Add exception note",
                            description="Attach a note to an exception.",
                            risk_tier="A3",
                            requires_confirmation=1,
                            enabled=1,
                            order_index=5,
                        ),
                        AssistCapability(
                            capability_id="case.createHandoff",
                            name="Create handoff",
                            description="Create a handoff to a support or compliance team.",
                            risk_tier="A3",
                            requires_confirmation=1,
                            enabled=1,
                            order_index=6,
                        ),
                    ]
                )
                db.commit()

            if db.query(AssistSuggestion).count() == 0:
                db.add_all(
                    [
                        AssistSuggestion(
                            intent_id="run.readiness",
                            context_type="PAYROLL_RUN",
                            prompt="Is the payroll run ready for approval?",
                            position=1,
                        ),
                        AssistSuggestion(
                            intent_id="exception.list",
                            context_type="PAYROLL_RUN",
                            prompt="What exceptions exist on this run?",
                            position=2,
                        ),
                        AssistSuggestion(
                            intent_id="run.status",
                            context_type="PAYROLL_RUN",
                            prompt="What is the current status of this run?",
                            position=3,
                        ),
                        AssistSuggestion(
                            intent_id="kb.answer",
                            context_type="GLOBAL",
                            prompt="Can Assist approve payroll or release payments?",
                            position=4,
                        ),
                        AssistSuggestion(
                            intent_id="variance.compare",
                            context_type="GLOBAL",
                            prompt="Compare this payroll period with the previous one.",
                            position=5,
                        ),
                    ]
                )
                db.commit()

            if db.query(AssistNotice).count() == 0:
                db.add(
                    AssistNotice(
                        notice_version="assist-policy-1.0.0",
                        title="Assist policy notice",
                        content=(
                            "Zoiko Payroll Assist is governed: it explains, finds and prepares payroll work, "
                            "but it can never approve payroll, release payments, submit filings or change "
                            "protected data. All controlled actions are previewed and confirmed by you before "
                            "execution. Verify material decisions against the authoritative payroll record."
                        ),
                        required=1,
                    )
                )
                db.commit()
        finally:
            db.close()
    except Exception as exc_info:  # noqa: BLE001
        logger.error("Failed to seed Assist reference content: %s", exc_info)


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
import app.modules.super_admin.models  # noqa: F401,E402
import app.modules.payroll.models  # noqa: F401,E402
import app.modules.payroll.policy.models  # noqa: F401,E402
import app.modules.payroll.enterprise.models  # noqa: F401,E402
import app.modules.payroll.mail.models  # noqa: F401,E402
import app.modules.assist.models  # noqa: F401,E402
