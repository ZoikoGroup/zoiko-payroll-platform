"""
config.py
---------
Environment configuration for the standalone Zoiko Payroll Platform.

Fully independent of the main ZoikoOne platform: its own database
(PAYROLL_DATABASE_URL), its own JWT secret (PAYROLL_SECRET_KEY), its own
CORS origins and its own token namespace. Nothing here is shared with the
old repo's app.config.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database (own, separate from the main platform) ────────────────
    PAYROLL_DATABASE_URL: str = ""
    # Neon (production/dev default) always requires SSL. A local/docker-
    # compose Postgres container has no SSL configured at all, so this must
    # be overridable rather than hardcoded — see docker-compose.yml's
    # backend service, which sets this to "disable".
    PAYROLL_DB_SSL_MODE: str = "require"

    # ── JWT / Auth (own secret — never reuse the main platform's) ──────
    PAYROLL_SECRET_KEY: str = "change-me-payroll-platform-secret"
    ALGORITHM: str = "HS256"
    # Distinct issuer/token-namespace so tokens from this platform can
    # never be confused with (or accepted by) the main platform.
    JWT_ISSUER: str = "zoiko-payroll-platform"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── App Info ──────────────────────────────────────────────────────
    APP_NAME: str = "Zoiko Payroll Platform Backend"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    @field_validator("DEBUG", mode="before")
    @classmethod
    def normalize_debug(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"dev", "development"}:
                return True
        return value

    # ── CORS ──────────────────────────────────────────────────────────
    PAYROLL_CORS_ORIGINS: str = (
        "http://localhost:5173,http://localhost:5174,http://localhost:5175,"
        "http://127.0.0.1:5173,http://127.0.0.1:5174"
    )

    # ── Public-facing links (e.g. "Send Template" form-fill emails) ────
    FRONTEND_URL: str = "http://localhost:5173"

    # ── Email / SMTP ──────────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: str = "587"
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@payroll.zoiko.example"
    SMTP_USE_TLS: str = "true"

    # ── Super Admin setup key ─────────────────────────────────────────
    # Required to run scripts/seed_super_admin.py and to create Super
    # Admin accounts. Never create a Super Admin through public /auth/register.
    SETUP_KEY: str = ""

    # ── Zoiko Payroll Assist ───────────────────────────────────────────
    # Deterministic engine is always available. When an OpenAI-compatible
    # provider is configured, the model gateway uses it to generate grounded
    # answers (with deterministic fallback on failure). Left empty by default.
    ASSIST_MODEL_PROVIDER: str = ""                 # "openai-compatible" | "" (deterministic only)
    ASSIST_MODEL_BASE_URL: str = ""                 # e.g. https://api.openai.com/v1
    ASSIST_MODEL_API_KEY: str = ""
    ASSIST_MODEL_NAME: str = "gpt-4o-mini"
    ASSIST_MODEL_TIMEOUT_SECONDS: int = 30
    ASSIST_POLICY_VERSION: str = "1.0.0"
    # Inbox that receives a notification whenever a chat conversation is
    # escalated to support (see confirm_handoff in modules/assist/service.py).
    # Left empty to skip the support-side notification (the requester's own
    # confirmation email still sends regardless).
    ASSIST_SUPPORT_EMAIL: str = ""
    # Background sweep of expired KB items / retention-expired sessions,
    # mirroring the existing manual admin endpoints (run_kb_expiry_sweep,
    # run_retention_cleanup) on a timer instead of requiring a click.
    ASSIST_SWEEP_ENABLED: bool = True
    ASSIST_SWEEP_INTERVAL_HOURS: int = 24
    # Platform-wide incident kill-switch for Assist (see modules/assist/router.py).
    # Live-toggleable via PlatformSetting, not just this startup default.
    ASSIST_KILL_SWITCH_ENABLED: bool = False


settings = Settings()
