"""Harness-only SYNTHETIC patches for the Mexico Phase 9b browser check,
applied in the setup process AND the server process. Never imported by the
application; never production.

mode "off"   — onboarding flag off (production).
mode "on"    — flag on, Phase 6 synthetic content; NO special-pay rules: the
               production reality once Mexico opens, before S24 / S25 / S26
               are transcribed (aguinaldo and vacation premium BLOCK).
mode "rules" — as "on" plus SYNTHETIC special-pay / aguinaldo / ISN-inclusion
               rules, to show the computation end to end."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


class SynAguinaldoRule:
    source, source_ref = "S26", "SYNTHETIC"

    def fraction(self, year, employed_from, employed_to):
        start = max(date(year, 1, 1), employed_from or date(year, 1, 1))
        end = min(date(year, 12, 31), employed_to or date(year, 12, 31))
        return Decimal(max((end - start).days + 1, 0)) / Decimal((date(year, 12, 31) - date(year, 1, 1)).days + 1)

    def payable_by(self, year):
        return date(year, 12, 20)


class SynSpecialPayRule:
    source, source_ref = "S24", "SYNTHETIC"
    combine_with_ordinary = True

    def __init__(self, cap):
        self.cap = Decimal(cap)

    def exempt(self, concept, amount, facts):
        return min(amount, self.cap)

    def standalone_isr(self, taxable, facts):
        return (taxable * Decimal("0.10")).quantize(Decimal("0.01"), ROUND_HALF_UP)


def apply(mode: str):
    from sqlalchemy import event

    from app.config import settings
    from app.database import engine

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _advisory_lock_stub(dbapi_conn, _record):
            dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda key: 1)

    settings.MX_TENANT_ONBOARDING_ENABLED = mode in ("on", "rules")
    if mode == "off":
        return
    from app.modules.payroll.engine.countries import mexico_content as c

    c.MX_PAY_FREQUENCY_ISR_PERIOD = {"04": "QUINCENAL_15", "05": "MONTHLY", "02": "WEEKLY_7"}   # SYNTHETIC
    c.MX_ZLFN_MUNICIPALITIES = (c.ZlfnMunicipality("BCN", "Tijuana", "S9", "SYNTHETIC"),)
    if mode == "rules":
        c.MX_AGUINALDO_RULE = SynAguinaldoRule()
        c.MX_SPECIAL_PAY_RULES = {"AGUINALDO": SynSpecialPayRule("100"), "VACATION_PREMIUM": SynSpecialPayRule("50")}
        c.MX_SPECIAL_PAY_ISN_INCLUSION = {("CDMX", "AGUINALDO"): (True, "S22", "SYNTHETIC"),
                                          ("CDMX", "VACATION_PREMIUM"): (True, "S22", "SYNTHETIC")}
