"""Harness-only SYNTHETIC patches for the final mile X4 browser check, applied in
the setup process AND the server process. Never imported by the application;
never production.

mode "off" — onboarding flag off (production).
mode "on"  — flag on (this process only), with the synthetic pay-frequency
             mapping and ZLFN list the test world needs to calculate."""


def apply(mode: str):
    from sqlalchemy import event

    from app.config import settings
    from app.database import engine

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _advisory_lock_stub(dbapi_conn, _record):     # SQLite has no pg_advisory_xact_lock
            dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda key: 1)

    settings.MX_TENANT_ONBOARDING_ENABLED = mode == "on"
    if mode != "on":
        return
    from app.modules.payroll.engine.countries import mexico_content as c

    c.MX_PAY_FREQUENCY_ISR_PERIOD = {"04": "QUINCENAL_15", "05": "MONTHLY", "02": "WEEKLY_7"}   # SYNTHETIC
    c.MX_ZLFN_MUNICIPALITIES = (c.ZlfnMunicipality("BCN", "Tijuana", "S9", "SYNTHETIC"),)
