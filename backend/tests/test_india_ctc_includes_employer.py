"""
tests/test_india_ctc_includes_employer.py
----------------------------------------
India CTC convention (policy ctc_includes_employer_contributions,
migration 9ffb5ff78e85).

  * off (default): monthly gross = CTC / 12, exactly as before;
  * on: the fixed gross is solved so gross + employer PF + employer ESI +
    EDLI = CTC / 12 (never above it), with the payslip's own formulas —
    PF wage ceiling, ESI eligibility threshold, configured EDLI;
  * the run preview and a real run agree; non-India employees and Simple
    Payroll are untouched; reading the switch never creates a policy;
  * the policy API accepts and returns the switch.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem
from app.modules.payroll.policy.models import PayrollPolicy

D = Decimal


def _rates(edli=False):
    rows = {
        "pf": SimpleNamespace(employee_rate_pct=D("12"), employer_rate_pct=D("12"), flat_amount=None),
        "esi": SimpleNamespace(employee_rate_pct=D("0.75"), employer_rate_pct=D("3.25"), flat_amount=None),
    }
    if edli:
        rows["edli_rate"] = SimpleNamespace(employee_rate_pct=None, employer_rate_pct=D("0.5"), flat_amount=None)
        rows["edli_wage_ceiling"] = SimpleNamespace(employee_rate_pct=None, employer_rate_pct=None, flat_amount=D("15000"))
    return rows


def _employee(db, org, code, ctc, country="IN", **kw):
    emp = PayrollEmployee(organization_id=org.id, employee_code=code, name=f"Emp {code}", country_code=country,
                          ctc=D(ctc), compliance_fields={}, **kw)
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _switch(db, org, on=True):
    from app.modules.payroll.policy.service import get_active_policy
    policy = get_active_policy(db, org.id)
    policy.ctc_includes_employer_contributions = on
    db.commit()
    return policy


def _employer_cost(db, org, emp, gross, rates):
    """Employer PF + ESI + EDLI the payslip formulas give for this gross."""
    from app.modules.payroll.engine.countries.india import employer_statutory_contributions
    basic_pct, hra_pct = service._resolve_salary_split_pct(db, org.id)
    basic, hra = service._round2(gross * basic_pct / 100), service._round2(gross * hra_pct / 100)
    ctx = SimpleNamespace(rate_map=rates, basic=basic, hra=hra, special_allowance=gross - basic - hra,
                          overtime=D("0"), additional_compensation=D("0"), gross=gross,
                          code_wages_rules={}, epf_base_rules={}, esi_base_rules={})
    c = employer_statutory_contributions(ctx)
    return c["employer_pf"] + c["employer_esi"] + c["employer_edli"]


# ── switch ───────────────────────────────────────────────────────────────────

def test_switch_is_off_by_default_and_reading_it_never_creates_a_policy(db, organization):
    assert db.query(PayrollPolicy).filter(PayrollPolicy.organization_id == organization.id).count() == 0
    assert service._ctc_includes_employer_contributions(db, organization.id) is False
    assert db.query(PayrollPolicy).filter(PayrollPolicy.organization_id == organization.id).count() == 0
    _switch(db, organization, True)
    assert service._ctc_includes_employer_contributions(db, organization.id) is True


def test_off_means_ctc_over_twelve(db, organization):
    emp = _employee(db, organization, "OFF1", "1200000")
    assert service._monthly_gross_for(db, organization.id, emp, "IN", _rates(), []) == D("100000.00")


# ── solver ───────────────────────────────────────────────────────────────────

def test_above_pf_ceiling_employer_pf_is_carved_out(db, organization):
    """CTC 12,00,000: PF base capped at 15,000 -> employer PF 1,800; gross
    above the ESI threshold -> no ESI. Gross = 1,00,000 - 1,800."""
    _switch(db, organization)
    emp = _employee(db, organization, "HI1", "1200000")
    gross = service._monthly_gross_for(db, organization.id, emp, "IN", _rates(), [])
    assert gross == D("98200.00")
    assert gross + _employer_cost(db, organization, emp, gross, _rates()) == D("100000.00")


def test_edli_is_carved_out_when_configured(db, organization):
    _switch(db, organization)
    emp = _employee(db, organization, "ED1", "1200000")
    gross = service._monthly_gross_for(db, organization.id, emp, "IN", _rates(edli=True), [])
    assert gross == D("98125.00")                               # - PF 1,800 - EDLI 75
    assert gross + _employer_cost(db, organization, emp, gross, _rates(edli=True)) == D("100000.00")


def test_esi_employee_total_never_exceeds_ctc(db, organization):
    """CTC 2,40,000 (20,000/month): ESI applies, so PF and ESI both come out."""
    _switch(db, organization)
    emp = _employee(db, organization, "ES1", "240000")
    gross = service._monthly_gross_for(db, organization.id, emp, "IN", _rates(), [])
    total = gross + _employer_cost(db, organization, emp, gross, _rates())
    assert gross < D("20000") and D("19999.98") <= total <= D("20000.00")
    assert _employer_cost(db, organization, emp, gross, _rates()) > D("1000")   # PF + ESI, not PF alone


@pytest.mark.parametrize("annual", ["251000", "252000", "253000", "255000", "258000"])
def test_esi_threshold_never_pushes_total_above_ctc(db, organization, annual):
    """Around the 21,000 ESI threshold the employer cost jumps; the solver
    must still never exceed CTC / 12 and must not hang."""
    _switch(db, organization)
    emp = _employee(db, organization, f"TH{annual}", annual)
    target = service._round2(D(annual) / 12)
    gross = service._monthly_gross_for(db, organization.id, emp, "IN", _rates(), [])
    total = gross + _employer_cost(db, organization, emp, gross, _rates())
    assert total <= target and target - total < D("800")


def test_stored_basic_split_is_used(db, organization):
    _switch(db, organization)
    emp = _employee(db, organization, "SB1", "1200000", basic=D("600000"), hra=D("240000"))
    gross = service._monthly_gross_for(db, organization.id, emp, "IN", _rates(), [])
    assert gross == D("98200.00")                               # basic 50,000 > ceiling: PF 1,800


def test_non_india_and_simple_mode_are_untouched(db, organization):
    _switch(db, organization)
    uk = _employee(db, organization, "UK1", "1200000", country="UK")
    assert service._monthly_gross_for(db, organization.id, uk, "UK", _rates(), []) == D("100000.00")
    emp = _employee(db, organization, "SM1", "1200000")
    assert service._monthly_gross_for(db, organization.id, emp, "IN", _rates(), [],
                                      calculation_mode="simple") == D("100000.00")


# ── preview == run ───────────────────────────────────────────────────────────

def _period():
    return date(2026, 6, 1), date(2026, 6, 30)


def test_preview_and_run_use_the_solved_gross(db, organization):
    organization.country = "IN"
    db.commit()
    _switch(db, organization)
    emp = _employee(db, organization, "PR1", "1200000")
    start, end = _period()
    preview = service.preview_payroll_run(db, organization.id, [emp.id], "IN", period_start=start, period_end=end)
    row = next(r for r in preview["employees"] if r["employeeId"] == emp.id)
    gross = D(str(row["monthlyGross"]))
    assert gross == D("98200.00")
    assert gross + D(str(row["employerPf"])) + D(str(row["employerEsi"])) + D(str(row["employerEdli"])) == D("100000.00")

    run = PayrollRun(organization_id=organization.id, run_code="CTC-1", period_label="June 2026",
                     period_start=start, period_end=end, pay_date=end, status="Draft")
    db.add(run)
    db.commit()
    values = service._compute_payslip_values(db, run, emp, *service._resolve_effective_rate_inputs(
        db, organization.id, "IN", end, service._org_uses_canonical_tax_pack(db, organization.id))[:2], "IN")
    assert D(str(values["gross_pay"])) == gross


def test_switch_off_preview_is_ctc_over_twelve(db, organization):
    organization.country = "IN"
    db.commit()
    emp = _employee(db, organization, "PR2", "1200000")
    start, end = _period()
    preview = service.preview_payroll_run(db, organization.id, [emp.id], "IN", period_start=start, period_end=end)
    row = next(r for r in preview["employees"] if r["employeeId"] == emp.id)
    assert D(str(row["monthlyGross"])) == D("100000.00")


# ── policy API ───────────────────────────────────────────────────────────────

def test_policy_update_accepts_and_returns_the_switch(db, organization):
    from app.modules.payroll.policy.schemas import PayrollPolicyResponse, PayrollPolicyUpdate
    from app.modules.payroll.policy.service import get_active_policy, update_policy
    policy = get_active_policy(db, organization.id)
    updated = update_policy(db, policy.id, PayrollPolicyUpdate(ctcIncludesEmployerContributions=True), organization.id)
    assert updated.ctc_includes_employer_contributions is True
    out = PayrollPolicyResponse.model_validate(updated).model_dump(by_alias=True)
    assert out["ctcIncludesEmployerContributions"] is True
    with pytest.raises(Exception):
        PayrollPolicyUpdate(ctcIncludesEmployerContributions=None)


# ── migration ────────────────────────────────────────────────────────────────

def test_migration_adds_and_drops_the_column_idempotently():
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (Path(__file__).resolve().parent.parent / "alembic" / "versions"
            / "9ffb5ff78e85_policy_ctc_includes_employer_contributions.py")
    spec = importlib.util.spec_from_file_location("ctc_policy_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "c8d2f6a4e1b9"

    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.begin()
        connection.execute(sa.text("CREATE TABLE payroll_policies (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO payroll_policies (id) VALUES (1)"))
        module.op = Operations(MigrationContext.configure(connection))

        def cols():
            return {c["name"] for c in sa.inspect(connection).get_columns("payroll_policies")}

        module.upgrade()
        module.upgrade()                                   # second run is a no-op
        assert "ctc_includes_employer_contributions" in cols()
        # Existing organisations stay on today's behaviour.
        assert connection.execute(sa.text(
            "SELECT ctc_includes_employer_contributions FROM payroll_policies")).scalar() in (0, False, "false")
        module.downgrade()
        module.downgrade()
        assert cols() == {"id"}
