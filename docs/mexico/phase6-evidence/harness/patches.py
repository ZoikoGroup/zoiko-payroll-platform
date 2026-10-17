"""Harness-only SYNTHETIC content patches, applied in the setup process AND
the server process (the same mappings the tests monkeypatch). Never imported
by the application; never production."""


def apply(flag_on: bool):
    from app.config import settings
    from app.modules.payroll.engine.countries import mexico_content as c

    settings.MX_TENANT_ONBOARDING_ENABLED = flag_on
    c.MX_PAY_FREQUENCY_ISR_PERIOD = {"04": "QUINCENAL_15", "05": "MONTHLY", "02": "WEEKLY_7"}   # SYNTHETIC
    c.MX_ZLFN_MUNICIPALITIES = (c.ZlfnMunicipality("BCN", "Tijuana", "S9", "SYNTHETIC"),)
