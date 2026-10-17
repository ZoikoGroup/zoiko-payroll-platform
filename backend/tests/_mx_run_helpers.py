"""Builders for the Mexico Phase 6 run-integration tests.

Everything here is SYNTHETIC (tests/_mx_engine_helpers.py values, @example.com
users, a test-only Active pack inserted directly — the activation gates are
tested elsewhere). Nothing may be copied into mexico_content or a golden
vector."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from tests import _mx_engine_helpers as eh
from tests._mx_employer_helpers import enable_mx_onboarding, make_org, mx_workplace, new_mx_employee, save_mx_profile

PERIOD = (date(2026, 6, 1), date(2026, 6, 15))
PAY_DATE = date(2026, 6, 15)
FREQ = {"04": "QUINCENAL_15", "05": "MONTHLY", "02": "WEEKLY_7"}   # SYNTHETIC code → period mapping


def _pack_rows(db, pack, rates, slabs):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    for i, (key, row) in enumerate(rates.items()):
        db.add(ContributionRate(
            jurisdiction_pack_id=pack.id, jurisdiction_country="MX", component_key=key, label=key, employee_share="—",
            employer_share="—", total="—", sort_order=i,
            employee_rate_pct=None if row["employee_rate_pct"] is None else Decimal(row["employee_rate_pct"]),
            employer_rate_pct=None if row["employer_rate_pct"] is None else Decimal(row["employer_rate_pct"]),
            flat_amount=None if row["flat_amount"] is None else Decimal(row["flat_amount"]),
            text_value=row["text_value"], effective_from=row.get("effective_from"), effective_to=row.get("effective_to")))
    for i, s in enumerate(slabs):
        db.add(TaxSlab(
            jurisdiction_pack_id=pack.id, jurisdiction_country="MX", rule_type=s["rule_type"],
            filing_status=s.get("filing_status"), assessment_basis=s.get("assessment_basis"),
            jurisdiction_state=s.get("jurisdiction_state"),
            min_amount=Decimal(s.get("min_amount") or "0"),
            max_amount=None if s.get("max_amount") in (None, "") else Decimal(s["max_amount"]),
            flat_amount=None if s.get("flat_amount") in (None, "") else Decimal(s["flat_amount"]),
            rate_pct=Decimal(s.get("rate_pct") or "0"), rate_label="SYNTHETIC", tax_formula="SYNTHETIC", sort_order=i,
            effective_from=s.get("effective_from"), effective_to=s.get("effective_to")))


def national_pack(db, rates=None, slabs=None):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id="MX-PAYROLL-TEST", jurisdiction_country="MX", version="1.0", pack_type="tax",
                            status="Active", effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
                            tax_year="2026", currency="MXN")
    db.add(pack)
    db.flush()
    _pack_rows(db, pack, eh.SYN_RATES if rates is None else rates, eh.base_slabs() if slabs is None else slabs)
    db.commit()
    return pack


def isn_pack(db, state="CDMX", status="Active"):
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    pack = JurisdictionPack(pack_id=f"MX-ISN-{state}-TEST", jurisdiction_country="MX", jurisdiction_state=state,
                            version="1.0", pack_type="tax", status=status, effective_from=date(2026, 1, 1),
                            effective_to=date(2026, 12, 31), tax_year="2026", currency="MXN")
    db.add(pack)
    db.flush()
    db.add(ContributionRate(jurisdiction_pack_id=pack.id, jurisdiction_country="MX", jurisdiction_state=state,
                            component_key="mx_isn_rate_pct", label="ISN", employee_share="—", employer_share="—",
                            total="—", employer_rate_pct=Decimal("3")))
    db.commit()
    return pack


def classify(db, code, *, org_id=None, sbc="FIXED", isn=True, **over):
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    row = C(organization_id=org_id, earning_code=code, label=code, version=1, effective_from=date(2026, 1, 1),
            isr_treatment="TAXABLE", sbc_treatment=sbc, infonavit_included=True, isn_default_included=isn,
            ptu_wage_base_included=True, cfdi_node_type="PERCEPCION", status="ACTIVE", sha256="0" * 64, **over)
    db.add(row)
    db.commit()
    return row


def world(db, monkeypatch, *, salary="600", salary_type="FIXED", convention="CALENDAR", freq="04", admins=2,
          period=PERIOD, pay_date=PAY_DATE, code="MXRUN"):
    from app.modules.payroll.engine.countries import mexico_content as c
    from app.modules.payroll.models import (
        PayrollMxImssRegistration, PayrollMxLaborPolicy, PayrollMxRiskPremium, PayrollRun,
    )

    enable_mx_onboarding(monkeypatch)
    raw = db.connection().connection.dbapi_connection
    if hasattr(raw, "create_function"):          # SQLite: the business-code generator's advisory lock
        raw.create_function("pg_advisory_xact_lock", 1, lambda key: 1)
    monkeypatch.setattr(c, "MX_PAY_FREQUENCY_ISR_PERIOD", dict(FREQ))
    monkeypatch.setattr(c, "MX_ZLFN_MUNICIPALITIES", (c.ZlfnMunicipality("BCN", "Tijuana", "S9", "SYNTHETIC"),))
    o = make_org(db, name=f"{code} Org", code=code, admins=admins)
    from app.modules.payroll.models import JurisdictionPack as J

    pack = db.query(J).filter(J.pack_id == "MX-PAYROLL-TEST").first() or national_pack(db)
    isn = db.query(J).filter(J.pack_id == "MX-ISN-CDMX-TEST").first() or isn_pack(db)
    wp = mx_workplace(db, o.org.id)
    reg = db.get(PayrollMxImssRegistration, wp.registration["id"])
    db.add(PayrollMxRiskPremium(registration_id=reg.id, determination_year=2026, premium_rate_pct=Decimal("0.5"),
                                period_from=date(2026, 3, 1), period_to=date(2027, 2, 28), status="ACTIVE"))
    policy = PayrollMxLaborPolicy(
        organization_id=o.org.id, employer_profile_id=reg.employer_profile_id, version=1,
        effective_from=date(2026, 1, 1), ordinary_weekly_hours=Decimal("40"), aguinaldo_days=Decimal("15"),
        vacation_policy=[{"serviceYearFrom": 1, "serviceYearTo": 1, "days": 12},
                         {"serviceYearFrom": 2, "serviceYearTo": 2, "days": 14},
                         {"serviceYearFrom": 3, "serviceYearTo": None, "days": 16}],
        vacation_premium_pct=Decimal("25"), sunday_premium_pct=Decimal("25"), floor_check_status="PASS",
        status="ACTIVE", salary_days_convention=convention)
    db.add(policy)
    db.commit()
    from app.modules.payroll.models import PayrollMxEarningClassification as C

    if not db.query(C).filter(C.earning_code == "MX_SALARY", C.organization_id.is_(None)).first():
        classify(db, "MX_SALARY")
    emp = new_mx_employee(db, o.org.id, code=f"{code}-1", email=f"emp.{code.lower()}@example.com")
    save_mx_profile(db, emp, o.org.id, effective_from=date(2026, 1, 1), mx_daily_salary=Decimal(salary),
                    mx_seniority_date=date(2024, 3, 1), mx_salary_type=salary_type, mx_pay_frequency_code=freq,
                    mx_establishment_id=wp.establishment["id"], mx_imss_registration_id=reg.id)
    run = PayrollRun(organization_id=o.org.id, period_label="Jun 1-15, 2026", period_start=period[0],
                     period_end=period[1], pay_date=pay_date, status="Draft", created_by=o.users[0].id)
    db.add(run)
    db.commit()
    return SimpleNamespace(org=o.org, users=o.users, pack=pack, isn=isn, workplace=wp, registration=reg,
                           policy=policy, employee=emp, run=run)


def generate(db, w):
    from app.modules.payroll import service

    service.generate_payslips_for_run(db, w.run, w.org.id, [w.employee.id])
    db.refresh(w.run)
    return mx_items(db, w.run)


def mx_items(db, run):
    from app.modules.payroll.models import PayslipItem

    return db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).order_by(PayslipItem.id).all()


def advance(db, w, actor_index=1):
    from app.modules.payroll import service

    return service.advance_payroll_run_status(db, w.run.id, w.users[actor_index].id, w.org.id)
