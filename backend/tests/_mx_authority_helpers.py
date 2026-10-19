"""Builders for the Mexico Phase 8 authority tests. Everything is SYNTHETIC:
the run world is tests/_mx_run_helpers.py (test-only Active packs), the ISN
registration points at the test ISN pack, due-date content is monkeypatched
only where a test says so."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from tests import _mx_run_helpers as rh
from tests._mx_employer_helpers import save_mx_profile


def isn_registration(db, w, state="CDMX"):
    from app.modules.payroll.models import PayrollMxIsnRegistration

    row = PayrollMxIsnRegistration(organization_id=w.org.id, employer_profile_id=w.registration.employer_profile_id,
                                   state_code=state, local_account_number="SYN-ISN-001",
                                   jurisdiction_pack_id=w.isn.id, effective_from=date(2026, 1, 1), status="OPEN")
    db.add(row)
    db.commit()
    return row


def commit(db, w, run):
    from app.modules.payroll import service

    service.generate_payslips_for_run(db, run, w.org.id, [w.employee.id])
    for _ in range(2):
        service.advance_payroll_run_status(db, run.id, w.users[1].id, w.org.id)
    db.refresh(run)
    assert run.status == "Approved" and (run.mx_approval_fingerprint or {}).get("committedAt")
    return run


def committed_world(db, monkeypatch, code="MXAUTH", **kw):
    w = rh.world(db, monkeypatch, code=code, **kw)
    commit(db, w, w.run)
    isn = isn_registration(db, w)
    return SimpleNamespace(**vars(w), isn_registration=isn)


def new_run(db, w, label="Jun 16-30, 2026", start=date(2026, 6, 16), end=date(2026, 6, 30), pay=date(2026, 6, 30)):
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=w.org.id, period_label=label, period_start=start, period_end=end, pay_date=pay,
                     status="Draft", created_by=w.users[0].id)
    db.add(run)
    db.commit()
    return run


def raise_salary(db, w, daily, effective_from=date(2026, 6, 16)):
    """A new profile version with a different daily salary (an SBC change)."""
    reg = w.registration
    save_mx_profile(db, w.employee, w.org.id, effective_from=effective_from, mx_daily_salary=Decimal(daily),
                    mx_seniority_date=date(2024, 3, 1), mx_salary_type="FIXED", mx_pay_frequency_code="04",
                    mx_establishment_id=w.workplace.establishment["id"], mx_imss_registration_id=reg.id)


def svc():
    from app.modules.payroll import mexico_authority_lifecycle as L
    from app.modules.payroll import mexico_filing_service as F
    from app.modules.payroll import mexico_imss_service as I

    return SimpleNamespace(F=F, I=I, L=L)


def liabilities(db, w, authority=None):
    from app.modules.payroll.models import PayrollMxAuthorityLiability as A

    q = db.query(A).filter(A.organization_id == w.org.id)
    if authority:
        q = q.filter(A.authority == authority)
    return q.order_by(A.authority, A.scope_key, A.period_key, A.sequence).all()


def movements(db, w):
    from app.modules.payroll.models import PayrollMxImssMovement as M

    return db.query(M).filter(M.organization_id == w.org.id).order_by(M.id).all()


def events(db, entity_type, obj):
    from app.modules.payroll import mexico_authority_lifecycle as L

    return [e.event_type for e in L.events(db, entity_type, obj)]
