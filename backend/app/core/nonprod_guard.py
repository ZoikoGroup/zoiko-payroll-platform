"""
core/nonprod_guard.py
---------------------
Production data never silently lands in a non-production environment
(ZP-PRIV D09).

* A production deployment stamps its database with ``data_origin=production``
  (platform_settings) at startup.
* A non-production deployment refuses to start against a database carrying
  that stamp unless ``scripts/deidentify_database.py`` has run on it (which
  records ``data_deidentified_at``). Local development only logs a critical
  warning, so a developer can still diagnose; every named non-production
  environment (staging, test, qa, demo, uat, ...) fails closed.
* ``assert_safe_restore`` is the same rule for restore / copy tooling.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("zoiko_payroll.nonprod_guard")

ORIGIN_KEY = "data_origin"
DEIDENTIFIED_KEY = "data_deidentified_at"
PRODUCTION = "production"
_PRODUCTION_NAMES = {"production", "prod"}
_DEVELOPMENT_NAMES = {"development", "dev", "local", ""}


class NonProductionDataError(RuntimeError):
    pass


def environment_name() -> str:
    return (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "").strip().lower()


def is_production(env: str | None = None) -> bool:
    return (environment_name() if env is None else env) in _PRODUCTION_NAMES


def _get(db, key):
    from app.modules.super_admin.models import PlatformSetting

    row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
    return row.value if row is not None else None


def _set(db, key, value, description):
    from app.modules.super_admin.models import PlatformSetting

    row = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
    if row is None:
        row = PlatformSetting(key=key, description=description)
        db.add(row)
    row.value = value
    db.commit()


def assert_safe_restore(source_origin: str | None, target_env: str, deidentified: bool) -> None:
    """Refuse copying production-origin data into a non-production target
    unless it has been de-identified."""
    if source_origin == PRODUCTION and not is_production(target_env) and not deidentified:
        raise NonProductionDataError(
            f"Refusing to restore production data into '{target_env or 'unnamed'}' without de-identification "
            "(run scripts/deidentify_database.py on the restored copy first).")


def enforce(db, env: str | None = None) -> str:
    """Startup check. Returns what it did: marked / production / ok / warned."""
    env = environment_name() if env is None else env
    origin = _get(db, ORIGIN_KEY)
    if is_production(env):
        if origin != PRODUCTION:
            _set(db, ORIGIN_KEY, PRODUCTION, "Origin of the data in this database (ZP-PRIV D09).")
            return "marked"
        return "production"
    if origin == PRODUCTION and not _get(db, DEIDENTIFIED_KEY):
        message = (f"This '{env or 'unnamed'}' environment is connected to a database of production origin that "
                   "has not been de-identified. Production personal data must not be used outside production.")
        if env in _DEVELOPMENT_NAMES:
            logger.critical("[nonprod-guard] %s", message)
            return "warned"
        raise NonProductionDataError(message)
    return "ok"


def mark_deidentified(db) -> str:
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    _set(db, DEIDENTIFIED_KEY, stamp, "When this copy was de-identified (ZP-PRIV D09).")
    return stamp
