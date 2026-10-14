"""
Outbound delivery guard (G5 finding F-10).

Every outbound notification channel (email today; SMS and outbound webhooks
if they are ever added) asks this module before it opens a connection.

Rule:
  * production / staging / anything not positively identified as test or
    local -> real delivery as configured (staging keeps its own
    STAGING_SANDBOX_EMAIL redirect in email_service);
  * test (a pytest run, or ENVIRONMENT/APP_ENV = test|testing|ci) and local
    (ENVIRONMENT/APP_ENV = development|dev|local, or neither set and
    DEBUG true -- the same rule app/config.py uses for its fail-closed
    secret-key guard) -> NO delivery, unless LOCAL_MAIL_SANDBOX_ENABLED is
    true; then email goes ONLY to LOCAL_MAIL_SANDBOX_HOST:PORT (e.g. a
    Mailpit/MailHog container), never to the configured SMTP server, and
    without its credentials.

Why: a local backend reads backend/.env, which may hold real SMTP
credentials (and platform_settings smtp_* rows can override the host), so
a scratch browser run once delivered real break-glass notices. Blocking
here, at the send point, does not depend on what .env or the database say.
"""

import logging
import os
import sys

logger = logging.getLogger("zoiko_payroll")

PRODUCTION_LIKE = "production"
TEST = "test"
LOCAL = "local"

_TEST_NAMES = {"test", "testing", "ci"}
_LOCAL_NAMES = {"development", "dev", "local"}


def classify(env_name: str, debug, under_pytest: bool) -> str:
    """Pure rule behind delivery_mode(); an explicit ENVIRONMENT/APP_ENV wins, DEBUG only when neither is set."""
    env_name = (env_name or "").strip().lower()
    if under_pytest or env_name in _TEST_NAMES:
        return TEST
    if env_name in _LOCAL_NAMES:
        return LOCAL
    if env_name:
        return PRODUCTION_LIKE
    return LOCAL if str(debug).strip().lower() in {"1", "true", "yes", "on"} else PRODUCTION_LIKE


def delivery_mode() -> str:
    """TEST, LOCAL or PRODUCTION_LIKE (see module docstring)."""
    from app.config import settings

    return classify(os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "", getattr(settings, "DEBUG", False),
                    "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST")))


def sandbox_enabled() -> bool:
    from app.config import settings

    return bool(getattr(settings, "LOCAL_MAIL_SANDBOX_ENABLED", False))


def real_delivery_allowed(channel: str) -> bool:
    """True when `channel` may reach a real recipient through its configured provider."""
    return delivery_mode() == PRODUCTION_LIKE


def smtp_target(configured: dict) -> dict | None:
    """The SMTP endpoint a send may use, or None when delivery is blocked.

    PRODUCTION_LIKE: the configured endpoint, unchanged. TEST / LOCAL: the
    sandbox endpoint (no TLS, no login) when the sandbox is on, else None."""
    if real_delivery_allowed("email"):
        return configured
    if not sandbox_enabled():
        return None
    from app.config import settings

    return {**configured, "host": settings.LOCAL_MAIL_SANDBOX_HOST, "port": settings.LOCAL_MAIL_SANDBOX_PORT,
            "username": "", "password": "", "use_tls": "false", "sandbox": True}


def log_blocked(channel: str, recipient: str, detail: str = "") -> None:
    logger.warning(
        f"[outbound] BLOCKED {channel} to {recipient} ({delivery_mode()} mode, local sandbox off) - NOT delivered"
        + (f" | {detail}" if detail else "")
    )
