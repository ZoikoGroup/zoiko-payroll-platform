"""
tests/test_payslip_chord_tasks.py
----------------------------------
Phase 2.2 chord contract: the dispatcher, the per-employee header task and
the finalize callback in app/tasks/payroll_tasks.py.

These tests exist because a Celery chord's failure modes are invisible
until it runs in production:

  * a header task that raises never invokes the callback, leaving a run
    whose row says one thing and whose payslips say another;
  * a callback that recomputes aggregates after a partial failure
    publishes a "complete-looking" run that was never complete;
  * a callback that advances the run's status forks the async path away
    from the synchronous one, where DRAFT->REVIEW is the operator's
    Approve action and nothing else;
  * a parallel dispatch across a shared org-level accumulator silently
    changes payroll figures.

Each of those is asserted against here rather than reasoned about.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.tasks import payroll_tasks
from app.modules.payroll import service
from app.modules.payroll.models import (
    ContributionRate, TaxSlab, PayrollEmployee, PayrollRun, PayslipItem,
    PayrollStatus,
)
import app.modules.payroll.engine.countries.shared as shared


@pytest.fixture(autouse=True)
def _eager_result_backend(monkeypatch):
    """Run tasks in-process against an in-memory result backend.

    Celery's `apply()` executes locally but still RECORDS the result, and
    with no explicit result_backend configured the app falls back to the
    broker URL — which points at a Redis server that is neither running
    nor (see requirements) installed here. Pointing the backend at
    cache+memory:// keeps `.apply()` a pure in-process call, which is
    what these tests need: they assert on the tasks' DB effects and
    return values, never on message delivery.
    """
    conf = payroll_tasks.celery_app.conf
    monkeypatch.setitem(conf, "result_backend", "cache+memory://")
    monkeypatch.setitem(conf, "task_always_eager", True)
    monkeypatch.setitem(conf, "task_eager_propagates", True)
    yield


@pytest.fixture(autouse=True)
def _restore_org_levy_switch():
    original = set(shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES)
    yield
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.clear()
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.update(original)


@pytest.fixture()
def task_session(db, monkeypatch):
    """Point the tasks' SessionLocal at the test's session.

    The tasks open their own session via SessionLocal() and close it in a
    finally — pointing that at the fixture session means `close()` runs
    against it, which would expunge every object the test still holds a
    reference to (a later `db.refresh(run)` then fails with "not
    persistent within this Session"). `close()` is therefore neutralised:
    it only ever releases a transaction and connection, so suppressing it
    costs nothing here — the tasks already commit explicitly where they
    mean to, and StaticPool hands the same connection back regardless.
    """
    monkeypatch.setattr(payroll_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    return db


def _stub_business_code_generation(monkeypatch):
    import app.core.code_generation as code_generation
    counter = {"n": 0}

    def _fake(db, organization_id, prefix, table, code_column, date_format=None, seq_width=3):
        counter["n"] += 1
        return f"TEST{prefix}{counter['n']:05d}"

    monkeypatch.setattr(code_generation, "generate_business_code", _fake)


def _seed_on_eht_bands(db):
    db.add(TaxSlab(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON",
        min_amount=Decimal("0"), max_amount=Decimal("200000"), rate_pct=Decimal("0.98"),
        rate_label="EHT", tax_formula="", rule_type="ON_EHT_BAND",
    ))
    db.add(ContributionRate(
        organization_id=None, jurisdiction_country="CA", jurisdiction_state="ON",
        component_key="on_eht_exemption", label="Ontario EHT Exemption",
        employee_share="—", employer_share="—", total="—",
        flat_amount=Decimal("1000000"),
    ))
    db.commit()


def _make_employee(db, org_id, code, country="US", work_state="CA",
                   ctc=Decimal("120000")):
    emp = PayrollEmployee(
        organization_id=org_id, employee_code=code, name=f"Employee {code}",
        country_code=country, work_state=work_state, ctc=ctc,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _make_run(db, org_id, status=PayrollStatus.DRAFT):
    run = PayrollRun(
        organization_id=org_id, period_label="Chord Run",
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        pay_date=date(2026, 2, 1),
        status=status.value if isinstance(status, PayrollStatus) else status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _source_without_docstring(func) -> str:
    """The function's body with its docstring stripped, so an assertion
    about what the code DOES is not satisfied by what the docstring SAYS."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(func))
    body = tree.body[0].body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return ast.unparse(ast.Module(body=body, type_ignores=[]))


class _CapturedChord:
    """Replaces celery's chord: records the header group and callback
    signature instead of sending anything to a broker, so the dispatcher's
    decisions (who is in the header, what is bound to the callback) can be
    asserted without a worker running."""

    def __init__(self):
        self.header = None
        self.callback = None
        self.dispatched = False

    def __call__(self, header):
        self.header = header
        outer = self

        def _bind(callback):
            outer.callback = callback
            outer.dispatched = True
            return "chord-dispatched"

        return _bind

    @property
    def header_signatures(self):
        # NOTE: `list(group)` is wrong — celery's group is a dict-like
        # Signature, so iterating it yields the KEYS ('task', 'args',
        # 'kwargs', ...). The member signatures live on `.tasks`.
        return list(self.header.tasks)

    def run_header(self, results_collector=None):
        """Execute every header signature locally, in order, and return the
        list of results — the chord's collective result."""
        out = []
        for sig in self.header_signatures:
            out.append(sig.apply().get())
        if results_collector is not None:
            results_collector.extend(out)
        return out

    def run_callback(self, results):
        """Invoke the callback the way Celery would: header results
        prepended to the signature's own bound args."""
        task = payroll_tasks.celery_app.tasks[self.callback.task]
        return task.apply(
            args=[results] + list(self.callback.args),
            kwargs=dict(self.callback.kwargs),
        ).get()


@pytest.fixture()
def fake_chord(monkeypatch):
    cap = _CapturedChord()
    monkeypatch.setattr(payroll_tasks, "chord", cap)
    return cap


# --------------------------------------------------------------------------
# parallel_payslip_generation_blocker — the safety gate
# --------------------------------------------------------------------------

def test_blocker_allows_run_with_no_org_levy_countries(db, organization):
    _make_employee(db, organization.id, "BLK-US1", country="US")
    _make_employee(db, organization.id, "BLK-US2", country="US")
    run = _make_run(db, organization.id)

    assert service.parallel_payslip_generation_blocker(
        db, organization.id,
        db.query(PayrollEmployee).filter(
            PayrollEmployee.organization_id == organization.id).all(),
    ) is None


def test_blocker_stops_run_touching_a_shared_org_accumulator(db, organization):
    """Canada's org-level EHT accumulator is read-modify-write across
    employees — two workers reading the 'before' figure concurrently would
    both band against the same stale total and lose one increment. The
    gate must refuse that, naming the employee and the country."""
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    _make_employee(db, organization.id, "BLK-CA", country="CA", work_state="ON")
    employees = db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == organization.id).all()

    reason = service.parallel_payslip_generation_blocker(
        db, organization.id, employees)

    assert reason is not None
    assert "BLK-CA" in reason
    assert "CA" in reason


def test_blocker_allows_canada_when_the_org_levy_switch_is_off(db, organization):
    """With the rollout switch off, no accumulator row is read or written,
    so the ordering constraint genuinely does not exist — blocking anyway
    would sacrifice parallelism for a hazard that is not there."""
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.discard("CA")
    _make_employee(db, organization.id, "BLK-CA-OFF", country="CA", work_state="ON")
    employees = db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == organization.id).all()

    assert service.parallel_payslip_generation_blocker(
        db, organization.id, employees) is None


def test_blocker_ignores_per_employee_ytd_countries(db, organization):
    """US is in _YTD_ACCUMULATOR_ENABLED_COUNTRIES but those accumulators
    are keyed by employee_id — concurrent workers touch disjoint rows, so
    they must NOT block parallelism."""
    assert "US" in shared._YTD_ACCUMULATOR_ENABLED_COUNTRIES
    _make_employee(db, organization.id, "BLK-YTD", country="US")
    employees = db.query(PayrollEmployee).filter(
        PayrollEmployee.organization_id == organization.id).all()

    assert service.parallel_payslip_generation_blocker(
        db, organization.id, employees) is None


# --------------------------------------------------------------------------
# generate_payslips_for_run_task — the dispatcher
# --------------------------------------------------------------------------

def test_dispatcher_rejects_non_draft_run(task_session, organization):
    db = task_session
    _make_employee(db, organization.id, "DISP-A")
    run = _make_run(db, organization.id, status=PayrollStatus.REVIEW)

    with pytest.raises(ValueError) as exc:
        payroll_tasks.generate_payslips_for_run_task.apply(
            args=[run.id, organization.id]).get()

    assert "Review" in str(exc.value)


def test_dispatcher_rejects_unknown_run(task_session, organization):
    with pytest.raises(Exception) as exc:
        payroll_tasks.generate_payslips_for_run_task.apply(
            args=[999999, organization.id]).get()
    assert "PayrollRun 999999 not found" in str(exc.value)


def test_dispatcher_dispatches_chord_for_parallel_safe_run(
        task_session, organization, monkeypatch, fake_chord):
    db = task_session
    _stub_business_code_generation(monkeypatch)
    _make_employee(db, organization.id, "DISP-US1")
    _make_employee(db, organization.id, "DISP-US2")
    run = _make_run(db, organization.id)

    result = payroll_tasks.generate_payslips_for_run_task.apply(
        args=[run.id, organization.id]).get()

    assert fake_chord.dispatched is True
    assert result["parallel"] is True
    assert result["status"] == "dispatched"
    assert result["employee_count"] == 2
    # Two header signatures — one per pending employee — each bound to the
    # same run and org and to a distinct payslip number.
    sigs = fake_chord.header_signatures
    assert len(sigs) == 2
    assert all(s.task.endswith("generate_payslip_for_employee_task") for s in sigs)
    emp_ids = [s.args[2] for s in sigs]
    assert len(set(emp_ids)) == 2
    numbers = [s.args[3] for s in sigs]
    assert all(n is not None for n in numbers)
    assert len(set(numbers)) == 2, "payslip numbers must be unique within a batch"
    assert fake_chord.callback.task.endswith("finalize_payroll_run_task")
    # results, run_id, organization_id, expected_count
    assert fake_chord.callback.args == (run.id, organization.id, 2)


def test_dispatcher_falls_back_to_sequential_when_org_accumulator_at_risk(
        task_session, organization, monkeypatch, fake_chord):
    """The whole point of the gate: a run whose employees share an org
    levy accumulator must not be split across workers. The fallback runs
    the synchronous batch path in-process, so the caller still gets a
    result rather than a silent no-op."""
    db = task_session
    _stub_business_code_generation(monkeypatch)
    shared._ORG_LEVY_ACCUMULATOR_ENABLED_COUNTRIES.add("CA")
    _make_employee(db, organization.id, "DISP-CA", country="CA", work_state="ON")
    run = _make_run(db, organization.id)

    result = payroll_tasks.generate_payslips_for_run_task.apply(
        args=[run.id, organization.id]).get()

    assert fake_chord.dispatched is False
    assert result["parallel"] is False
    assert "CA" in result["reason"]
    assert result["employee_count"] == 1
    assert db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id).count() == 1


def test_dispatcher_skips_employees_already_paid_and_deletes_stale_failed(
        task_session, organization, monkeypatch, fake_chord):
    """Idempotency parity with the batch path: an employee with a real
    payslip is not re-dispatched, while a stale FAILED sentinel is cleared
    so a retry re-attempts them instead of skipping them forever."""
    from app.modules.payroll.models import PayslipStatus

    db = task_session
    _stub_business_code_generation(monkeypatch)
    done = _make_employee(db, organization.id, "DISP-DONE")
    retry = _make_employee(db, organization.id, "DISP-RETRY")
    fresh = _make_employee(db, organization.id, "DISP-FRESH")
    run = _make_run(db, organization.id)

    db.add(PayslipItem(
        payroll_run_id=run.id, employee_id=done.id, organization_id=organization.id,
        employee_name=done.name, country_code="US", status=PayslipStatus.PENDING,
    ))
    db.add(PayslipItem(
        payroll_run_id=run.id, employee_id=retry.id, organization_id=organization.id,
        employee_name=retry.name, country_code="US", status=PayslipStatus.FAILED,
    ))
    db.commit()

    payroll_tasks.generate_payslips_for_run_task.apply(
        args=[run.id, organization.id]).get()

    dispatched = [s.args[2] for s in fake_chord.header_signatures]
    assert done.id not in dispatched, "already-generated employee must not be re-dispatched"
    assert set(dispatched) == {retry.id, fresh.id}
    # The stale FAILED row for `retry` was cleared by the dispatcher, so
    # the retry can produce exactly one payslip (parity with the batch
    # path's cleanup) — assert no FAILED row survives for them.
    assert db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id,
        PayslipItem.employee_id == retry.id,
    ).count() == 0


def test_dispatcher_runs_callback_directly_when_nothing_to_generate(
        task_session, organization, monkeypatch, fake_chord):
    """An empty chord is a Celery edge case; the dispatcher short-circuits
    to the callback so aggregates still get recomputed (a run may have had
    payslips deleted) instead of dispatching nothing and returning
    silence."""
    db = task_session
    _stub_business_code_generation(monkeypatch)
    _make_run(db, organization.id)   # org with no employees at all
    run_id = db.query(PayrollRun).first().id

    result = payroll_tasks.generate_payslips_for_run_task.apply(
        args=[run_id, organization.id]).get()

    assert fake_chord.dispatched is False
    assert result["status"] == "finalized"
    assert result["summary"]["total"] == 0


def test_dispatcher_has_no_autoretry(
        task_session, organization, monkeypatch, fake_chord):
    """A chord dispatch that fails after some header tasks committed must
    surface as a visible failure, not be re-dispatched wholesale behind
    exponential backoff."""
    # No autoretry_for means no automatic re-dispatch on failure. The
    # `max_retries = 3` below is Celery's DEFAULT for every task and is
    # inert without autoretry_for — it only matters if someone calls
    # self.retry() explicitly, which this task never does.
    assert not getattr(payroll_tasks.generate_payslips_for_run_task,
                       "autoretry_for", None)
    assert "self.retry()" not in _source_without_docstring(
        payroll_tasks.generate_payslips_for_run_task.run)


# --------------------------------------------------------------------------
# generate_payslip_for_employee_task — the header member
# --------------------------------------------------------------------------

def test_header_task_generates_and_commits_one_payslip(
        task_session, organization, monkeypatch):
    db = task_session
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, "HDR-A")
    run = _make_run(db, organization.id)

    result = payroll_tasks.generate_payslip_for_employee_task.apply(
        args=[run.id, organization.id, emp.id, "TESTPSL00001"]).get()

    assert result["status"] == "generated"
    assert result["employee_id"] == emp.id
    item = db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id,
        PayslipItem.employee_id == emp.id,
    ).one()
    assert item.payslip_number == "TESTPSL00001"
    assert item.net_pay > 0


def test_header_task_is_idempotent_on_second_delivery(
        task_session, organization, monkeypatch):
    """Celery may redeliver a message. The second delivery must report
    'exists' and must not create a duplicate row."""
    db = task_session
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, "HDR-IDEM")
    run = _make_run(db, organization.id)
    args = [run.id, organization.id, emp.id, "TESTPSL00002"]

    first = payroll_tasks.generate_payslip_for_employee_task.apply(args=args).get()
    second = payroll_tasks.generate_payslip_for_employee_task.apply(args=args).get()

    assert first["status"] == "generated"
    assert second["status"] == "exists"
    assert second["payslip_id"] == first["payslip_id"]
    assert db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id,
        PayslipItem.employee_id == emp.id,
    ).count() == 1


def test_header_task_returns_error_result_instead_of_raising(
        task_session, organization, monkeypatch):
    """A raising header member aborts the chord before the callback runs,
    leaving committed payslips with stale run aggregates. Returning an
    'error' result keeps the chord whole so the callback can refuse to
    finalize — the failure stays visible without leaving a half-written
    run that looks complete to every reader of the run row."""
    db = task_session
    _stub_business_code_generation(monkeypatch)
    emp = _make_employee(db, organization.id, "HDR-BOOM")
    run = _make_run(db, organization.id)

    def _explode(*args, **kwargs):
        raise RuntimeError("synthetic resolver failure")

    monkeypatch.setattr(
        payroll_tasks.payroll_service, "generate_payslip_for_employee", _explode)

    result = payroll_tasks.generate_payslip_for_employee_task.apply(
        args=[run.id, organization.id, emp.id, None]).get()

    assert result["status"] == "error"
    assert "synthetic resolver failure" in result["error"]
    assert result["employee_id"] == emp.id
    # Nothing was persisted for the failed employee.
    assert db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id).count() == 0


def test_header_task_reports_error_for_unknown_run(task_session, organization):
    db = task_session
    result = payroll_tasks.generate_payslip_for_employee_task.apply(
        args=[999999, organization.id, 1, None]).get()
    assert result["status"] == "error"
    assert "not found" in result["error"]


# --------------------------------------------------------------------------
# finalize_payroll_run_task — the callback
# --------------------------------------------------------------------------

def _generated_result(run_id, employee_id, status="generated"):
    return {"run_id": run_id, "status": status, "employee_id": employee_id,
            "payslip_id": None}


def test_callback_recomputes_aggregates_exactly_once(
        task_session, organization, monkeypatch):
    """N per-employee commits must not become N full re-aggregations: the
    callback is the only place totals are computed."""
    db = task_session
    emp = _make_employee(db, organization.id, "FIN-A")
    run = _make_run(db, organization.id)
    db.add(PayslipItem(
        payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
        employee_name=emp.name, country_code="US", status="Pending",
        gross_pay=Decimal("10000.00"), net_pay=Decimal("8000.00"),
        total_deductions=Decimal("2000.00"), tds=Decimal("500.00"),
    ))
    db.commit()

    calls = {"n": 0}
    real = service._recompute_run_aggregates

    def _counting(db, run_):
        calls["n"] += 1
        return real(db, run_)

    monkeypatch.setattr(payroll_tasks.payroll_service,
                        "_recompute_run_aggregates", _counting)

    result = payroll_tasks.finalize_payroll_run_task.apply(
        args=[[_generated_result(run.id, emp.id)], run.id, organization.id, 1]).get()

    assert calls["n"] == 1, "callback must recompute aggregates exactly once"
    assert result["status"] == "finalized"
    db.refresh(run)
    assert run.employee_count == 1
    assert run.total_gross == Decimal("10000.00")


def test_callback_does_not_advance_run_status(task_session, organization):
    """DRAFT->REVIEW belongs to the operator's Approve action
    (advance_payroll_run_status), not to generation. An async run that
    skipped review would fork the two paths and put unreviewed numbers in
    front of an approver."""
    db = task_session
    emp = _make_employee(db, organization.id, "FIN-STAT")
    run = _make_run(db, organization.id, status=PayrollStatus.DRAFT)

    payroll_tasks.finalize_payroll_run_task.apply(
        args=[[_generated_result(run.id, emp.id)], run.id, organization.id, 1]).get()

    db.refresh(run)
    assert run.status == PayrollStatus.DRAFT.value


def test_callback_refuses_to_finalize_when_a_header_task_errored(
        task_session, organization, monkeypatch):
    """The dangerous case: some payslips ARE committed, so recomputing
    would publish totals describing a run that never finished. The
    callback must raise and leave the aggregates untouched."""
    db = task_session
    emp = _make_employee(db, organization.id, "FIN-ERR")
    run = _make_run(db, organization.id)
    # A sentinel no recompute would ever produce: if the callback
    # recomputed, this would become 0 (no payslips exist yet).
    run.employee_count = 999
    db.commit()

    calls = {"n": 0}
    real = service._recompute_run_aggregates

    def _counting(db, run_):
        calls["n"] += 1
        return real(db, run_)

    monkeypatch.setattr(payroll_tasks.payroll_service,
                        "_recompute_run_aggregates", _counting)

    results = [
        _generated_result(run.id, emp.id),
        {"run_id": run.id, "status": "error", "employee_id": 42,
         "error": "boom"},
    ]

    with pytest.raises(RuntimeError) as exc:
        payroll_tasks.finalize_payroll_run_task.apply(
            args=[results, run.id, organization.id, 2]).get()

    assert "incomplete" in str(exc.value)
    assert calls["n"] == 0, "must not recompute aggregates for an unfinished run"
    db.refresh(run)
    assert run.status == PayrollStatus.DRAFT.value
    assert run.employee_count == 999, "aggregates must be left untouched"


def test_callback_refuses_to_finalize_when_results_are_missing(
        task_session, organization, monkeypatch):
    """Fewer results than expected means a header task never reported —
    same refusal as an explicit error."""
    db = task_session
    emp = _make_employee(db, organization.id, "FIN-MISS")
    run = _make_run(db, organization.id)

    calls = {"n": 0}

    def _counting(db, run_):
        calls["n"] += 1
        return run_

    monkeypatch.setattr(payroll_tasks.payroll_service,
                        "_recompute_run_aggregates", _counting)

    with pytest.raises(RuntimeError) as exc:
        payroll_tasks.finalize_payroll_run_task.apply(
            args=[[_generated_result(run.id, emp.id)], run.id, organization.id, 5]).get()

    assert "1/5" in str(exc.value)
    assert calls["n"] == 0


def test_callback_treats_blocked_and_existing_as_terminal(
        task_session, organization):
    """A statutorily-refused employee is a real outcome, not a hang: the
    callback must finalize rather than waiting forever for a result that
    will never arrive."""
    db = task_session
    emp = _make_employee(db, organization.id, "FIN-BLK")
    run = _make_run(db, organization.id)

    results = [
        _generated_result(run.id, emp.id, status="generated"),
        _generated_result(run.id, emp.id, status="exists"),
        _generated_result(run.id, emp.id, status="blocked"),
    ]

    result = payroll_tasks.finalize_payroll_run_task.apply(
        args=[results, run.id, organization.id, 3]).get()

    assert result["status"] == "finalized"
    assert result["summary"] == {
        "total": 3, "generated": 1, "exists": 1, "blocked": 1,
    }
    db.refresh(run)
    assert run.status == PayrollStatus.DRAFT.value


def test_callback_tolerates_empty_results_for_a_run_with_no_payslips(
        task_session, organization):
    db = task_session
    run = _make_run(db, organization.id)

    result = payroll_tasks.finalize_payroll_run_task.apply(
        args=[[], run.id, organization.id, 0]).get()

    assert result["status"] == "finalized"
    db.refresh(run)
    assert run.employee_count == 0


def test_callback_returns_cleanly_for_unknown_run(task_session, organization):
    """Finalizing a run deleted mid-chord must not raise — there is
    nothing to finalize and nothing to warn an operator about beyond the
    log line."""
    db = task_session
    result = payroll_tasks.finalize_payroll_run_task.apply(
        args=[[], 999999, organization.id, 0]).get()
    assert result is None


def test_callback_does_not_commit_itself(task_session, organization, monkeypatch):
    """_recompute_run_aggregates commits; a second db.commit() here would
    be the double-commit this callback exists to avoid."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(payroll_tasks.finalize_payroll_run_task))
    commit_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
    ]
    assert not commit_calls, "finalize callback must not call db.commit()"


# --------------------------------------------------------------------------
# end-to-end: the chord, executed inline
# --------------------------------------------------------------------------

def test_chord_end_to_end_produces_the_same_payslips_as_the_batch_path(
        task_session, organization, monkeypatch, fake_chord):
    """The chord's real contract: dispatch, run every header task, run the
    callback, and end up with exactly the figures the synchronous batch
    path would have produced for the same employees."""
    db = task_session
    _stub_business_code_generation(monkeypatch)
    _make_employee(db, organization.id, "E2E-1")
    _make_employee(db, organization.id, "E2E-2")
    run = _make_run(db, organization.id)

    payroll_tasks.generate_payslips_for_run_task.apply(
        args=[run.id, organization.id]).get()
    results = fake_chord.run_header()
    fake_chord.run_callback(results)

    chord_items = {
        i.employee_id: (i.gross_pay, i.net_pay, i.total_deductions, i.tds)
        for i in db.query(PayslipItem).filter(
            PayslipItem.payroll_run_id == run.id).all()
    }
    assert len(chord_items) == 2

    # Same employees, same run shape, through the synchronous path —
    # clear what the chord wrote so the batch pass starts from nothing.
    db.query(PayslipItem).filter(
        PayslipItem.payroll_run_id == run.id).delete(synchronize_session="fetch")
    db.commit()
    db.refresh(run)

    service.generate_payslips_for_run(db, run, organization.id)
    batch_items = {
        i.employee_id: (i.gross_pay, i.net_pay, i.total_deductions, i.tds)
        for i in db.query(PayslipItem).filter(
            PayslipItem.payroll_run_id == run.id).all()
    }

    assert batch_items == chord_items
    db.refresh(run)
    assert run.employee_count == 2
    assert run.total_gross == sum(v[0] for v in batch_items.values())


def test_chord_header_task_count_matches_pending_employees(
        task_session, organization, monkeypatch, fake_chord):
    db = task_session
    _stub_business_code_generation(monkeypatch)
    for n in range(4):
        _make_employee(db, organization.id, f"COUNT-{n}")
    run = _make_run(db, organization.id)

    payroll_tasks.generate_payslips_for_run_task.apply(
        args=[run.id, organization.id]).get()

    assert len(fake_chord.header_signatures) == 4
    # callback args are (run_id, organization_id, expected_count)
    assert fake_chord.callback.args[2] == 4
