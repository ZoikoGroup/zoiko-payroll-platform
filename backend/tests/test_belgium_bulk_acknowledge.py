"""Belgium (ZP-BE-ENG-001) Block J3: bulk acknowledge of a run's engine exceptions.

* a bulk acknowledgement writes exactly what the same acknowledgements one by one write: the approval-record
  entries and one audit row per item with the same content;
* the same authorization (org admin, own organisation, Belgian tenant guard) and the same refusals;
* all or nothing: one item that is not raised refuses the whole request and writes nothing.
"""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException, NotFoundException

REASON = "Settled outside the engine (TEST ONLY)"


@pytest.fixture
def demo(db, monkeypatch):
    from app.config import settings
    from app.core import code_generation
    from app.modules.payroll import belgium_demo
    from tests._mx_employer_helpers import make_org

    counter = iter(range(1, 10_000))
    monkeypatch.setattr(code_generation, "generate_business_code",
                        lambda db, org, prefix, *a, **k: f"TEST{prefix}{next(counter) * 1000:05d}")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "BE_DEMO_PACKS_ENABLED", True)
    t = make_org(db, name="DEMO Bulk BV", code="BEBULK", admins=2, country="BE")
    monkeypatch.setattr(settings, "BE_DEMO_ORG_IDS", str(t.org.id))
    belgium_demo.be_seed_demo_pack(db)
    db.commit()
    belgium_demo.be_seed_demo_month(db, t.org.id, t.users[0].id, t.users[1].id)    # employees + records
    return t


def _review_run(db, t, month: int):
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun

    end = date(2026, month, 30 if month in (4, 6, 9, 11) else 31)
    run = PayrollRun(organization_id=t.org.id, period_label=f"Bulk {month}", period_start=end.replace(day=1),
                     period_end=end, pay_date=end, created_by=t.users[0].id)
    db.add(run)
    db.commit()
    service.generate_payslips_for_run(db, run, t.org.id)
    db.commit()
    service.advance_payroll_run_status(db, run.id, t.users[0].id, t.org.id)               # Draft -> Review
    db.commit()
    return run


def _exceptions(db, run):
    from app.modules.payroll import belgium_service as be

    return [(p["employeeId"], p["code"]) for p in be.be_run_preflight(db, run)
            if p.get("exception") and p["severity"] == "BLOCK"]


def _audit_rows(db, run_id):
    from app.modules.payroll.models import TaxConfigurationAudit as A

    return sorted((r.action, r.entity_type, str(r.new_value), r.reason, r.actor_id)
                  for r in db.query(A).filter(A.entity_type == "be_run_exception", A.entity_id == run_id))


def _acks(run):
    return sorted((a["employeeId"], a["code"], a["reason"], a["by"])
                  for a in (run.be_approval_fingerprint or {}).get("acknowledgements", []))


def test_bulk_writes_exactly_what_one_by_one_writes(db, demo):
    from app.modules.payroll import belgium_service as be

    t, actor = demo, demo.users[0].id
    single, bulk = _review_run(db, t, 10), _review_run(db, t, 11)
    wanted_single, wanted_bulk = _exceptions(db, single), _exceptions(db, bulk)
    assert wanted_single and wanted_single == wanted_bulk
    for employee_id, code in wanted_single:
        be.acknowledge_be_run_exception(db, t.org.id, single.id, {"employeeId": employee_id, "code": code,
                                                                   "reason": REASON}, actor)
    db.commit()
    out = be.acknowledge_be_run_exceptions(db, t.org.id, bulk.id, {
        "items": [{"employeeId": e, "code": c} for e, c in wanted_bulk] + [{"employeeId": wanted_bulk[0][0],
                                                                             "code": wanted_bulk[0][1]}],  # duplicate
        "reason": REASON}, actor)
    db.commit()
    assert out["count"] == len(wanted_bulk)                                              # duplicate collapsed
    db.refresh(single)
    db.refresh(bulk)
    assert _acks(single) == _acks(bulk)                                                  # same approval record
    assert _audit_rows(db, single.id) == _audit_rows(db, bulk.id)                        # same audit, per item
    assert len(_audit_rows(db, bulk.id)) == len(wanted_bulk)
    assert _exceptions(db, single) == [] and _exceptions(db, bulk) == []                 # both now approvable


def test_all_or_nothing_and_the_same_refusals(db, demo):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import PayrollRun

    t, actor = demo, demo.users[0].id
    run = _review_run(db, t, 10)
    wanted = _exceptions(db, run)
    items = [{"employeeId": e, "code": c} for e, c in wanted] + [{"employeeId": wanted[0][0], "code": "BE_NOT_RAISED"}]
    with pytest.raises(BadRequestException, match="nothing was acknowledged"):
        be.acknowledge_be_run_exceptions(db, t.org.id, run.id, {"items": items, "reason": REASON}, actor)
    db.rollback()
    assert _acks(db.get(PayrollRun, run.id)) == [] and _audit_rows(db, run.id) == []        # nothing written
    for payload, message in (({"items": [], "reason": REASON}, "non-empty"),
                             ({"items": [{"employeeId": "x", "code": "C"}], "reason": REASON}, "employeeId"),
                             ({"items": [{"employeeId": wanted[0][0]}], "reason": REASON}, "code"),
                             ({"items": items[:1]}, "(?i)reason")):
        with pytest.raises(BadRequestException, match=message):
            be.acknowledge_be_run_exceptions(db, t.org.id, run.id, payload, actor)
    with pytest.raises(NotFoundException):                                               # another organisation
        be.acknowledge_be_run_exceptions(db, t.org.id + 999, run.id, {"items": items[:1], "reason": REASON}, actor)
    be.acknowledge_be_run_exceptions(db, t.org.id, run.id, {"items": items[:-1], "reason": REASON}, actor)
    db.commit()
    from app.modules.payroll import service

    service.advance_payroll_run_status(db, run.id, demo.users[1].id, t.org.id)            # approved (four-eyes)
    db.commit()
    with pytest.raises(BadRequestException, match="before the run is approved"):
        be.acknowledge_be_run_exceptions(db, t.org.id, run.id, {"items": items[:1], "reason": REASON}, actor)


def test_the_bulk_route_has_exactly_the_single_routes_authorization():
    from app.modules.payroll.be_org_router import require_be_tenant, router

    routes = {r.path: r for r in router.routes}
    single = routes["/belgium/runs/{run_id}/exceptions/acknowledge"]
    bulk = routes["/belgium/runs/{run_id}/exceptions/acknowledge-bulk"]
    deps = lambda r: sorted(d.call.__name__ for d in r.dependant.dependencies)          # noqa: E731
    assert deps(bulk) == deps(single) and "get_current_org_admin" in deps(bulk)
    assert bulk.methods == single.methods == {"POST"}
    assert any(d.dependency is require_be_tenant for d in router.dependencies)          # Belgian tenant guard
