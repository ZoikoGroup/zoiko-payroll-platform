"""
tests/test_payslip_single_employee_parity.py
---------------------------------------------
Phase 2.2 parity contract: generate_payslip_for_employee (the per-employee
entry point a Celery chord calls) must produce EXACTLY what the batch loop
in generate_payslips_for_run produces for the same employee.

The risk this file exists to close: _resolve_payslip_generation_inputs is
a shared helper, but "shared" is a claim about code, not about behaviour.
These tests compare persisted output — not the helper's return value — so a
future edit that routes one caller differently than the other (an extra
kwarg, a dropped branch, a differently-defaulted parameter) fails here
rather than in production as one employee's payslip being computed from
different inputs than their colleague's in the same run.

The Ontario EHT cases are the sharpest form of this: the org accumulator
is shared sequential state, so a single-employee call made against a
different processing order legitimately produces a different number. These
tests pin the order too — proving the single path reproduces the batch
result, not merely "a" result.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import (
    ContributionRate, TaxSlab, PayrollEmployee, PayrollRun, PayslipItem,
    OrganizationYtdAccumulator,
)
import app.modules.payroll.engine.countries.shared as shared


@pytest.fixture(autouse=True)
def _restore_org_levy_switch():
    original = set(shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


def _make_employee(db, org_id, code, country="CA", work_state="ON", ctc=Decimal("96000")):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code=country, work_state=work_state, ctc=ctc,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org_id, period_start, period_end, pay_date, label="Parity Run"):
    run = PayrollRun(
        organization_id=org_id, period_label=label,
        period_start=period_start, period_end=period_end, pay_date=pay_date,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _seed_on_eht_bands(db):
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON",
        min_amount=Decimal("0"), max_amount=Decimal("200000"), rate_pct=Decimal("0.98"),
        rate_label="EHT", tax_formula="", rule_type="ON_EHT_BAND",
    ))
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON",
        min_amount=Decimal("200000"), max_amount=None, rate_pct=Decimal("1.95"),
        rate_label="EHT", tax_formula="", rule_type="ON_EHT_BAND",
    ))
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON",
        component_key="on_eht_exemption", label="Ontario EHT Exemption",
        employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("1000000"),
    ))
    db.commit()


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


# Every persisted money/tax figure either path could diverge on. Compared
# field-by-field so a divergence names the exact column instead of just
# "the dicts differ".
_MONETARY_FIELDS = (
    "gross_pay", "net_pay", "total_deductions",
    "tds", "employer_eht", "employer_apprenticeship_levy",
    "employer_bc_eht", "employer_mb_he_levy", "employer_nl_hapset",
    "employer_qc_hsf", "employer_payroll_tax",
    "employer_pension", "employer_ni", "soli", "church_tax",
    "social_security", "medicare", "federal_income_tax", "state_income_tax",
    "pf", "esi", "professional_tax", "cpp2",
)


def _item_snapshot(item: PayslipItem) -> dict:
    return {f: getattr(item, f) for f in _MONETARY_FIELDS} | {
        "status": item.status,
        "country_code": item.country_code,
        "work_state": item.work_state,
        "tax_rule_snapshot": item.tax_rule_snapshot,
        "poe_snapshot": item.poe_snapshot,
    }


def _reset_run_state(db, run):
    """Clear everything a generation pass writes, so the second pass starts
    from the same state the first pass did — otherwise the org accumulator
    would already hold the first pass's total and the two passes could not
    be compared."""
    db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).delete(
        synchronize_session="fetch")
    db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == run.organization_id,
    ).delete(synchronize_session="fetch")
    db.commit()


def _batch_result(db, run, org_id, monkeypatch):
    _reset_run_state(db, run)
    service.generate_payslips_for_run(db, run, org_id)
    items = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id,
    ).order_by(PayslipItem.employee_id).all()
    return {i.employee_id: _item_snapshot(i) for i in items}


def _single_result(db, run, org_id, employee_ids):
    """Generate one employee at a time through the per-employee entry point,
    committing after each — the way a chord worker would (each task owns its
    own short transaction), NOT one transaction across all of them."""
    _reset_run_state(db, run)
    out = {}
    for emp_id in employee_ids:
        res = service.generate_payslip_for_employee(db, run, emp_id, org_id)
        db.commit()
        assert res["status"] == "generated", res
        item = db.query(PayslipItem).filter(PayslipItem.id == res["payslip_id"]).first()
        out[emp_id] = _item_snapshot(item)
    return out


def test_single_employee_parity_for_ca_ontario_run(db, organization, monkeypatch):
    """One Ontario employee: both paths must persist identical figures."""
    _stub_business_code_generation(monkeypatch)
    _seed_on_eht_bands(db)
    emp = _make_employee(db, organization.id, "PARITY-ON")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))

    batch = _batch_result(db, run, organization.id, monkeypatch)
    single = _single_result(db, run, organization.id, [emp.id])

    assert single[emp.id] == batch[emp.id]


def test_single_employee_parity_preserves_sequential_org_accumulation(
        db, organization, monkeypatch):
    """Two Ontario employees: the org accumulator is shared sequential
    state, so the ORDER of processing is part of the result. This proves
    the single-employee path, run in the batch's order, reproduces the
    batch's numbers exactly — the property a chord must preserve."""
    _stub_business_code_generation(monkeypatch)
    _seed_on_eht_bands(db)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    _make_employee(db, organization.id, "PARITY-A", ctc=Decimal("96000"))
    _make_employee(db, organization.id, "PARITY-B", ctc=Decimal("96000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))

    batch = _batch_result(db, run, organization.id, monkeypatch)
    emp_ids = sorted(batch)
    assert len(emp_ids) == 2

    single = _single_result(db, run, organization.id, emp_ids)

    assert single == batch
    # Both passes must also leave the SAME org accumulator state behind —
    # figure parity with a divergent accumulator would mean the next period
    # starts from a different total.
    row = db.query(OrganizationYtdAccumulator).filter(
        OrganizationYtdAccumulator.organization_id == organization.id,
        OrganizationYtdAccumulator.tax_component == "on_eht",
    ).first()
    assert row is not None
    assert row.ytd_taxable_wages == Decimal("16000.00")


def test_single_employee_parity_for_us_run(db, organization, monkeypatch):
    """A US run — no org-level accumulator involved — must match too. This
    is the common case for a chord: parallel-safe, no shared state."""
    _stub_business_code_generation(monkeypatch)
    _make_employee(db, organization.id, "PARITY-US", country="US", work_state="CA",
                   ctc=Decimal("120000"))
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))

    batch = _batch_result(db, run, organization.id, monkeypatch)
    single = _single_result(db, run, organization.id, sorted(batch))

    assert single == batch


def test_single_employee_entry_point_is_idempotent(db, organization, monkeypatch):
    """A second call for an employee who already has a real payslip in this
    run must NOT create a duplicate — the batch path's idempotency contract,
    enforced at the per-employee level a chord needs."""
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, "IDEM")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))

    first = service.generate_payslip_for_employee(db, run, emp.id, organization.id)
    db.commit()
    second = service.generate_payslip_for_employee(db, run, emp.id, organization.id)
    db.commit()

    assert first["status"] == "generated"
    assert second["status"] == "exists"
    assert second["payslip_id"] == first["payslip_id"]
    assert db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id, PayslipItem.employee_id == emp.id,
    ).count() == 1


def test_single_employee_entry_point_resolves_attendance_without_batch_map(
        db, organization, monkeypatch):
    """The batch path hands a pre-fetched {employee_id: [rows]} map to the
    shared resolver; the single-employee path passes none and must fetch the
    same rows itself. Dropping that branch would silently zero every
    employee's attendance-derived pay in the chord path while the batch path
    kept working — so assert the resolver returns rows both ways."""
    from app.modules.payroll.models import PayrollAttendanceRecord

    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, "PARITY-ATT")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    db.add(PayrollAttendanceRecord(
        organization_id=organization.id, employee_id=emp.id, date=date(2026, 1, 15),
        status="present", hours="8",
    ))
    db.commit()

    single = service._resolve_payslip_generation_inputs(
        db, run, emp, organization.id,
        calculation_mode="standard", allowance_components=[], org_opted_in=False,
    )
    assert len(single["attendance_records"]) == 1

    batch = service._resolve_payslip_generation_inputs(
        db, run, emp, organization.id,
        calculation_mode="standard", allowance_components=[], org_opted_in=False,
        calc_cache={}, attendance_by_employee={emp.id: [single["attendance_records"][0]]},
    )
    assert [r.id for r in batch["attendance_records"]] == [r.id for r in single["attendance_records"]]


def test_shared_resolver_output_is_accepted_by_generate_single_payslip(
        db, organization, monkeypatch):
    """Structural guard: the shared resolver's dict must be exactly the
    kwargs _generate_single_payslip accepts. If a key is renamed or a new
    one added on one side only, this fails immediately instead of at the
    first chord dispatch."""
    import inspect

    expected = set(inspect.signature(service._generate_single_payslip).parameters)
    expected -= {"db", "run", "employee"}   # supplied positionally by callers

    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, "KWARGS")
    run = _make_run(db, organization.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 1))
    resolved = service._resolve_payslip_generation_inputs(
        db, run, emp, organization.id,
        calculation_mode="standard", allowance_components=[], org_opted_in=False,
    )
    provided = set(resolved) - {"employee"}

    assert provided == expected, (
        f"resolver and _generate_single_payslip kwargs disagree: "
        f"only_resolver={sorted(provided - expected)} "
        f"only_target={sorted(expected - provided)}"
    )


def _called_names(func) -> set:
    """Every function/method name invoked anywhere inside `func`, via AST —
    so a mention in the docstring or a comment doesn't count as a call."""
    import ast
    tree = ast.parse(_source_without_docstring(func))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def _source_without_docstring(func) -> str:
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(func))
    body = tree.body[0].body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return ast.unparse(ast.Module(body=body, type_ignores=[]))


def test_single_employee_entry_point_does_not_recompute_run_aggregates(
        db, organization, monkeypatch):
    """generate_payslip_for_employee must NOT call _recompute_run_aggregates:
    a chord recomputes once in its callback. Recomputing per employee would
    be N full re-aggregations AND would leave run aggregates stale on a
    partially-failed chord if the callback never ran — so assert the caller,
    not the per-employee function, owns it."""
    assert "_recompute_run_aggregates" not in _called_names(
        service.generate_payslip_for_employee)


def test_single_employee_entry_point_does_not_commit(
        db, organization, monkeypatch):
    """The caller owns the transaction boundary — a chord header accumulates
    one session across its group, and the batch path keeps its single
    transaction. A hidden commit here would split the batch's transaction
    and break its atomicity."""
    assert "commit" not in _called_names(service.generate_payslip_for_employee)
