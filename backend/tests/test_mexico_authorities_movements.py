"""Mexico Phase 8 B1 / B2 — IMSS movements from committed events, their due
dates (sourced only), the operator worklist (file-export, D1 / D12) and the
outcomes. SYNTHETIC world, deadline and holidays."""

import csv
import io
from datetime import date
from decimal import Decimal as D

import pytest

from tests import _mx_authority_helpers as ah


def test_alta_once_from_the_committed_run_and_never_from_a_draft(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    out = s.I.generate_movements(db, w.org.id, w.users[0].id)
    (alta,) = ah.movements(db, w)
    assert alta.movement_type == "ALTA" and alta.event_date == w.employee.date_of_joining
    assert alta.registration_id == w.registration.id and alta.payroll_run_id == w.run.id and alta.status == "PENDING"
    assert out["skipped"] == []
    assert s.I.generate_movements(db, w.org.id, w.users[0].id)["created"] == []        # idempotent
    view = out["created"][0]
    assert view["nssMasked"] and "12345678901" not in str(view)                       # MX-061
    draft = ah.new_run(db, w)
    from app.modules.payroll import service

    ah.raise_salary(db, w, "700")
    service.generate_payslips_for_run(db, draft, w.org.id, [w.employee.id])           # calculated, NOT committed
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    assert [m.movement_type for m in ah.movements(db, w)] == ["ALTA"]


def test_modificacion_for_a_committed_sbc_change_only(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    ah.commit(db, w, ah.new_run(db, w))                                                # same salary: no change
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    assert [m.movement_type for m in ah.movements(db, w)] == ["ALTA"]
    ah.raise_salary(db, w, "700", effective_from=date(2026, 7, 1))
    run3 = ah.commit(db, w, ah.new_run(db, w, "Jul 1-15, 2026", date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 15)))
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    moves = ah.movements(db, w)
    assert [m.movement_type for m in moves] == ["ALTA", "MODIFICACION"]
    mod = moves[1]
    assert mod.payroll_run_id == run3.id and mod.event_date == date(2026, 7, 1) and mod.sbc > moves[0].sbc


def test_baja_only_from_an_approved_termination(db, monkeypatch):
    """Phase 9c D6: a date of leaving alone generates nothing; an APPROVED
    termination is the only BAJA source (a DRAFT one is not)."""
    from app.modules.payroll.models import PayrollMxTermination

    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    assert [m.movement_type for m in ah.movements(db, w)] == ["ALTA"]
    w.employee.date_of_leaving = date(2026, 6, 20)
    db.commit()
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    assert [m.movement_type for m in ah.movements(db, w)] == ["ALTA"]
    term = PayrollMxTermination(organization_id=w.org.id, employee_id=w.employee.id, termination_date=date(2026, 6, 20),
                                reason_code="SYNTHETIC", evidence_ref="letter", status="DRAFT")
    db.add(term)
    db.commit()
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    assert [m.movement_type for m in ah.movements(db, w)] == ["ALTA"]
    term.status = "APPROVED"
    db.commit()
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    baja = ah.movements(db, w)[-1]
    assert (baja.movement_type, baja.event_date, baja.payroll_run_id) == ("BAJA", date(2026, 6, 20), None)
    assert baja.source_kind == "TERMINATION"
    assert s.I.generate_movements(db, w.org.id, w.users[0].id)["created"] == []


def test_no_hire_date_no_alta(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    w.employee.date_of_joining = None
    db.commit()
    out = s.I.generate_movements(db, w.org.id, w.users[0].id)
    assert out["created"] == [] and [x["code"] for x in out["skipped"]] == ["MX_HIRE_DATE_MISSING"]


def test_movement_due_dates_only_from_the_transcribed_rule_and_holidays(db, monkeypatch):
    from app.modules.payroll import mexico_due_dates as due
    from app.modules.payroll import service
    from app.modules.payroll.engine.countries import mexico_content as c

    def _never(*a, **k):
        raise AssertionError("the weekend-only shared helper must never date a Mexican movement")

    monkeypatch.setattr(service, "_add_business_days", _never)
    # W1-5 transcribed the real deadline (LSS Art. 15 I) but no holiday list (D-16): still no due date
    assert c.MX_IMSS_MOVEMENT_DEADLINE.business_days == 5 and c.MX_OFFICIAL_HOLIDAYS == {}
    assert due.movement_due(date(2026, 6, 15)) == (None, due.UNSOURCED)
    monkeypatch.setattr(c, "MX_IMSS_MOVEMENT_DEADLINE", None)
    assert due.movement_due(date(2026, 6, 15)) == (None, due.UNSOURCED)
    monkeypatch.setattr(c, "MX_IMSS_MOVEMENT_DEADLINE", c.MovementDeadlineRule(5, "S13", "SYNTHETIC"))
    assert due.movement_due(date(2026, 6, 15)) == (None, due.UNSOURCED)              # no holiday list for 2026
    monkeypatch.setattr(c, "MX_OFFICIAL_HOLIDAYS", {2026: ((date(2026, 6, 17),), "S26", "SYNTHETIC")})
    # Mon 15 Jun: 16 (Tue), [17 holiday], 18, 19, [20-21 weekend], 22, 23 -> Tue 23 Jun
    assert due.movement_due(date(2026, 6, 15)) == (date(2026, 6, 23), "S13 SYNTHETIC")
    # Directional: a later event never gets an earlier due date.
    dates = [due.movement_due(date(2026, 6, d))[0] for d in range(1, 29)]
    assert dates == sorted(dates)
    assert due.movement_due(date(2026, 12, 28)) == (None, due.UNSOURCED)              # crosses into 2027: no list
    w = ah.committed_world(db, monkeypatch)
    ah.svc().I.generate_movements(db, w.org.id, w.users[0].id)
    (alta,) = ah.movements(db, w)
    assert alta.due_date is not None and alta.due_rule_ref == "S13 SYNTHETIC"


def test_worklist_export_carries_the_nss_only_in_the_file_and_freezes_the_payload(db, monkeypatch):
    from app.modules.payroll.models import TaxConfigurationAudit as T

    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    out = s.I.export_worklist(db, w.org.id, w.users[0].id)
    lines = list(csv.reader(io.StringIO(out["content"])))
    assert lines[0][0].startswith("ZOIKO WORKLIST - NOT AN IMSS / IDSE FILE") and lines[0][1] == out["batchRef"]
    assert lines[1][5] == "nss" and lines[2][5] == "12345678901" and lines[2][1] == "ALTA"
    (alta,) = ah.movements(db, w)
    assert alta.status == "EXPORTED" and alta.payload_hash and alta.export_batch_ref == out["batchRef"]
    audit = db.query(T).filter(T.entity_type == "mx_imss_worklist").all()
    assert len(audit) == 1 and "12345678901" not in str(audit[0].new_value)       # audited without the NSS
    with pytest.raises(Exception, match="No PENDING"):
        s.I.export_worklist(db, w.org.id, w.users[0].id)


def test_export_refused_whole_when_an_nss_is_missing(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    w.employee.compliance_fields = {k: v for k, v in (w.employee.compliance_fields or {}).items() if k != "nss"}
    db.commit()
    with pytest.raises(MXBlock) as exc:
        s.I.export_worklist(db, w.org.id, w.users[0].id)
    assert exc.value.key == "MX_NSS_MISSING"
    assert [m.status for m in ah.movements(db, w)] == ["PENDING"]


def test_outcomes_reference_four_eyes_rejection_and_regeneration(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    s.I.export_worklist(db, w.org.id, w.users[0].id)
    (alta,) = ah.movements(db, w)
    with pytest.raises(Exception):
        s.I.record_outcome(db, w.org.id, alta.id, "FILED", w.users[0].id, reference="")
    s.I.record_outcome(db, w.org.id, alta.id, "FILED", w.users[0].id, reference="SYN-IDSE-1")
    with pytest.raises(MXBlock) as exc:
        s.I.record_outcome(db, w.org.id, alta.id, "ACCEPTED", w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    s.I.record_outcome(db, w.org.id, alta.id, "REJECTED", w.users[1].id, reason="SYNTHETIC rejection")
    new = s.I.regenerate(db, w.org.id, alta.id, w.users[0].id)
    assert new["status"] == "PENDING" and new["replacesMovementId"] == alta.id
    assert new["idempotencyKey"] != alta.idempotency_key
    assert s.I.generate_movements(db, w.org.id, w.users[0].id)["created"] == []        # the event is covered


def test_withdraw_needs_a_reason_and_a_never_exported_movement(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    (alta,) = ah.movements(db, w)
    with pytest.raises(Exception, match="reason"):
        s.I.withdraw(db, w.org.id, alta.id, " ", w.users[0].id)
    out = s.I.withdraw(db, w.org.id, alta.id, "SYNTHETIC: already registered by the previous provider", w.users[0].id)
    assert out["status"] == "WITHDRAWN"
    assert s.I.generate_movements(db, w.org.id, w.users[0].id)["created"] == []        # stays withdrawn
