"""Harness-only SYNTHETIC patches for the Mexico Phase 8 browser check,
applied in the setup process AND the server process. Never imported by the
application; never production.

flag_on=False: only the onboarding flag (off), as in production.
flag_on=True: the Phase 6 synthetic content mappings (test-only Active packs
come from tests/_mx_run_helpers.py). No due-date content is patched: every
due date must show DUE_DATE_UNSOURCED, as in production today."""


def apply(flag_on: bool):
    from app.config import settings

    settings.MX_TENANT_ONBOARDING_ENABLED = flag_on
    if not flag_on:
        return
    from app.modules.payroll.engine.countries import mexico_content as c

    c.MX_PAY_FREQUENCY_ISR_PERIOD = {"04": "QUINCENAL_15", "05": "MONTHLY", "02": "WEEKLY_7"}   # SYNTHETIC
    c.MX_ZLFN_MUNICIPALITIES = (c.ZlfnMunicipality("BCN", "Tijuana", "S9", "SYNTHETIC"),)
