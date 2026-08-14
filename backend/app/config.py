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


settings = Settings()
