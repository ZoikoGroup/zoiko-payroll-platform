"""Harness-only SYNTHETIC patches for the Mexico Phase 10g (no-new-organisations switch) browser check,
applied in the setup process AND the server process. Never imported by the
application; never production.

mode "off"   — onboarding flag off (production).
mode "on"    — flag on, Phase 6 synthetic content; NO annual-adjustment rule
               or exclusion catalog: the production reality once Mexico opens,
               before S24 is transcribed (nothing is computed).
mode "rules" — as "on" plus a SYNTHETIC annual-adjustment rule and exclusion
               catalog, to show the adjustment end to end.
Both "on" modes set the harness's "today" to 2027-03-01, so fiscal year 2026
(the synthetic world's year) has ended."""
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


class SynReason:
    source, source_ref = "S26", "SYNTHETIC"

    def __init__(self, label, days_of_salary=None):
        self.label, self.days = label, days_of_salary

    def separation_components(self, facts):
        if self.days is None:
            return []
        return [{"code": "INDEMNITY", "label": "Synthetic indemnity", "amount": facts["daily_salary"] * self.days}]


class SynFiniquitoRule:
    source, source_ref = "S26/S24", "SYNTHETIC"

    def vacation_days_owed(self, years, termination_date):
        cur = years[-1]
        elapsed = Decimal((cur["end"] - cur["start"]).days + 1) / Decimal(365)
        owed = (cur["policy_days"] * elapsed).quantize(Decimal("0.01"), ROUND_HALF_UP) + cur["opening"] \
            - cur["taken"] - cur["paid_out"]
        return {cur["service_year"]: max(owed, Decimal("0"))}

    def isr(self, taxable_by_concept, facts):
        return (sum(taxable_by_concept.values(), Decimal("0")) * Decimal("0.10")).quantize(Decimal("0.01"),
                                                                                           ROUND_HALF_UP)


CONCEPTS = ("AGUINALDO", "VACATION_PAYOUT", "VACATION_PREMIUM", "SEPARATION", "PTU")


class SynPtuRule:
    """Half by days, half by ordinary salary, pro rata, floored to the cent;
    operator-excluded workers get nothing; no cap (recorded as such)."""
    source, source_ref = "S26", "SYNTHETIC"

    def allocate(self, pool, workers, fiscal_year):
        from decimal import ROUND_DOWN

        live = [w for w in workers if not w.get("operator_exclusion")]
        days = sum((w["days"] for w in live), Decimal("0"))
        salary = sum((w["salary_by_kind"].get("ORDINARY_SALARY", Decimal("0")) for w in live), Decimal("0"))
        out, total = [], Decimal("0")
        for w in workers:
            if w in live:
                ds = (pool / 2 * w["days"] / days).quantize(Decimal("0.01"), ROUND_DOWN) if days else Decimal("0")
                ss = (pool / 2 * w["salary_by_kind"].get("ORDINARY_SALARY", Decimal("0")) / salary).quantize(
                    Decimal("0.01"), ROUND_DOWN) if salary else Decimal("0")
                out.append({"employee_id": w["employee_id"], "eligible": True, "exclusion_reason": None,
                            "days_share": ds, "salary_share": ss, "cap_reference": {"cap": "none (SYNTHETIC)"},
                            "cap_applied": False, "final_amount": ds + ss})
                total += ds + ss
            else:
                out.append({"employee_id": w["employee_id"], "eligible": False,
                            "exclusion_reason": w["operator_exclusion"], "days_share": Decimal("0"),
                            "salary_share": Decimal("0"), "cap_reference": {}, "cap_applied": False,
                            "final_amount": Decimal("0")})
        return {"workers": out, "residue": pool - total, "residue_rule": "SYNTHETIC"}

    def payment_deadline(self, fiscal_year, employer):
        return date(fiscal_year + 1, 5, 30)


class SynExclusion:
    source, source_ref, label = "S26", "SYNTHETIC", "Synthetic director"


class SynAnnualRule:
    """Everyone eligible; annual ISR = taxable × 30%; the difference applied in
    full when the period's withholding allows it, else carried forward."""
    source, source_ref = "S24", "SYNTHETIC"

    def eligibility(self, worker, fiscal_year):
        return True, None

    def annual_isr(self, annual_taxable, fiscal_year, facts):
        return (annual_taxable * Decimal("0.30")).quantize(Decimal("0.01"), ROUND_HALF_UP)

    def apply_in_run(self, period_withheld, difference, facts):
        total = period_withheld + difference
        if total >= 0:
            return {"withheld": total, "carry_forward": Decimal("0")}
        return {"withheld": Decimal("0"), "carry_forward": total}


class SynAnnualExclusion:
    source, source_ref, label = "S24", "SYNTHETIC", "Synthetic written notice"


def apply(mode: str):
    from sqlalchemy import event

    from app.config import settings
    from app.database import engine

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _advisory_lock_stub(dbapi_conn, _record):
            dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda key: 1)

    settings.MX_TENANT_ONBOARDING_ENABLED = mode in ("on", "rules")
    settings.MX_IDENTITY_TOKEN_KEY = settings.MX_IDENTITY_TOKEN_KEY or "SYNTHETIC-harness-identity-key"
    if mode == "off":
        return
    from app.modules.payroll import mexico_ptu_service

    mexico_ptu_service._today = lambda: date(2027, 3, 1)       # SYNTHETIC: fiscal year 2026 has ended
    from app.modules.payroll import mexico_annual_service

    mexico_annual_service._today = lambda: date(2027, 3, 1)
    from app.modules.payroll.engine.countries import mexico_content as c

    c.MX_PAY_FREQUENCY_ISR_PERIOD = {"04": "QUINCENAL_15", "05": "MONTHLY", "02": "WEEKLY_7"}   # SYNTHETIC
    c.MX_ZLFN_MUNICIPALITIES = (c.ZlfnMunicipality("BCN", "Tijuana", "S9", "SYNTHETIC"),)
    if mode == "rules":
        c.MX_AGUINALDO_RULE = SynAguinaldoRule()
        c.MX_SPECIAL_PAY_RULES = {k: SynSpecialPayRule("100") for k in CONCEPTS}
        c.MX_SPECIAL_PAY_ISN_INCLUSION = {("CDMX", k): (True, "S22", "SYNTHETIC") for k in CONCEPTS}
        c.MX_TERMINATION_REASONS = {"SYN_DISMISSAL": SynReason("Synthetic dismissal", 90),
                                    "SYN_RESIGNATION": SynReason("Synthetic resignation")}
        c.MX_FINIQUITO_RULE = SynFiniquitoRule()
        c.MX_PTU_RULE = SynPtuRule()
        c.MX_PTU_EXCLUSION_REASONS = {"SYN_DIRECTOR": SynExclusion()}
        c.MX_ANNUAL_ADJUSTMENT_RULE = SynAnnualRule()
        c.MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS = {"SYN_OWN_RETURN": SynAnnualExclusion()}
