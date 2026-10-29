"""modules/payroll/engine/countries/japan.py
-------------------------------------------
Japan (ZP-JP-ENG-001) - fail-closed scaffold on the shared engine.

This is a controlled scaffold following the ZA pattern. Full NTA table
compilation, insurer-aware SMR/SBA logic, resident tax application from
imported schedules, and year-end adjustment require certified authority
artefacts and fixtures before production activation. Simple mode is blocked
by the resolver.
"""

from datetime import date
from decimal import Decimal

from app.modules.payroll.engine.base import PayrollContext
from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

_COUNTRY = "JP"
ZERO = Decimal("0")
HUNDRED = Decimal("100")


class JPCalculationBlockedError(MissingComplianceConfigurationError):
    def __init__(self, key: str, reason: str, organization_id: int = None):
        super().__init__(key, _COUNTRY, organization_id)
        self.reason = reason
        self.args = (f"Japan calculation blocked ({key}): {reason}",)


def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


class JPPack:
    def __init__(self, rate_map: dict, organization_id):
        self.rate_map = rate_map or {}
        self.organization_id = organization_id

    def block(self, key: str, reason: str):
        raise JPCalculationBlockedError(key, reason, self.organization_id)

    def _row(self, key: str):
        row = self.rate_map.get(key)
        if row is None:
            self.block(key, "no configured parameter row")
        return row

    def require_text(self, key: str, allowed=None) -> str:
        value = getattr(self._row(key), "text_value", None)
        if value is None or str(value).strip() == "":
            self.block(key, "row has no value configured")
        value = str(value).strip().upper()
        if allowed is not None and value not in allowed:
            self.block(key, f"{value!r} is not one of {', '.join(allowed)}")
        return value


def calculate(ctx: PayrollContext) -> dict:
    """Scaffold entrypoint - fail-closed until certified packs/fixtures are wired."""
    org_id = getattr(ctx, "organization_id", None) or getattr(ctx, "jp_organization_id", None)
    rate_map = getattr(ctx, "rate_map", {}) or {}
    pack = JPPack(rate_map, org_id)

    if ctx.pay_date is None:
        pack.block("pay_date", "payment date is required")

    # No global rounding (JP-002): each statutory amount names its own
    # rounding row in japan_content.JP_SCALAR_CONTENT.
    frequencies = pack.require_text("jp_supported_pay_frequencies")
    if (ctx.pay_frequency or "").upper() not in frequencies.split(","):
        pack.block("jp_supported_pay_frequencies", f"pay frequency {ctx.pay_frequency!r} is not supported")

    # Check for required JP context (mirrors ZA pattern)
    if getattr(ctx, "jp_employer_registration", None) is None:
        pack.block("jp_employer_registration", "Active Japan employer registration required")
    if getattr(ctx, "jp_worker_tax_profile", None) is None:
        pack.block("jp_worker_tax_profile", "Active Japan worker tax profile required")
    if getattr(ctx, "jp_social_insurance_enrollment", None) is None:
        pack.block("jp_social_insurance_enrollment", "Active Japan social insurance enrollment required")

    pack.block(
        "jp_calculation_not_implemented",
        "Japan calculation scaffolded: wire certified NTA/JPS/insurer packs, fixtures and full logic before activation (resident tax must come from imported municipality schedules)",
    )
