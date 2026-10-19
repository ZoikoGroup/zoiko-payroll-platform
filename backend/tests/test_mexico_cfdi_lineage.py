"""Mexico Phase 7 — cancellation / substitution lineage (MX-018, F6) with
reason codes ONLY from an Active catalog (D6; SYNTHETIC rows SYN1 needs a
related UUID, SYN2 does not). The original UUID is retained; the chain ends
CANCELLED → REPLACED with replaced_by_uuid set."""

from datetime import date

import pytest

from tests import _mx_cfdi_helpers as ch
from tests import _mx_run_helpers as rh


def _S():
    from app.modules.payroll import mexico_cfdi_service as S

    return S


def _stamped(db, monkeypatch, tmp_path, **script):
    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    pac = ch.mock(monkeypatch, **script)
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    (doc,) = ch.docs(db, w.run)
    assert doc.status == "STAMPED"
    return S, w, pac, doc


def _second_committed_run(db, w):
    """Stands in for the Phase 9 correction run: another committed Mexican
    run of the same employee (the lineage is what Phase 7 records)."""
    from app.modules.payroll import service
    from app.modules.payroll.models import PayrollRun

    run = PayrollRun(organization_id=w.org.id, period_label="Jun 16-30, 2026", period_start=date(2026, 6, 16),
                     period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30), status="Draft", created_by=w.users[0].id)
    db.add(run)
    db.commit()
    service.generate_payslips_for_run(db, run, w.org.id, [w.employee.id])
    for _ in range(2):
        service.advance_payroll_run_status(db, run.id, w.users[1].id, w.org.id)
    db.refresh(run)
    (item,) = rh.mx_items(db, run)
    return run, item


def test_cancel_refused_without_a_catalog_reason(db, monkeypatch, tmp_path):
    S, w, pac, doc = _stamped(db, monkeypatch, tmp_path)
    with pytest.raises(Exception) as exc:
        S.cancel(db, w.org.id, doc.id, "99", None, w.users[0].id)
    assert exc.value.key == "MX_CFDI_CANCEL_REASON_UNAVAILABLE"
    assert S.cancellation_reasons(db) == [
        {"code": "SYN1", "description": "SYNTHETIC — with related UUID", "requiresRelatedUuid": True},
        {"code": "SYN2", "description": "SYNTHETIC — no related UUID", "requiresRelatedUuid": False}]


def test_cancel_without_related_uuid(db, monkeypatch, tmp_path):
    S, w, pac, doc = _stamped(db, monkeypatch, tmp_path)
    uuid = doc.uuid
    S.cancel(db, w.org.id, doc.id, "SYN2", None, w.users[0].id)
    assert doc.status == "CANCEL_REQUESTED"
    ch.process(db, w)
    db.refresh(doc)
    assert doc.status == "CANCELLED" and doc.uuid == uuid and doc.cancellation_reason_code == "SYN2"
    assert S.run_summary(db, w.run)["status"] == "CANCELLED"
    assert ("cancel", f"{doc.idempotency_key}:c1", f"{uuid}|SYN2|None") in pac.calls


def test_reason_requiring_related_uuid_needs_the_stamped_replacement(db, monkeypatch, tmp_path):
    S, w, pac, doc = _stamped(db, monkeypatch, tmp_path)
    with pytest.raises(Exception):
        S.cancel(db, w.org.id, doc.id, "SYN1", None, w.users[0].id)
    with pytest.raises(Exception):
        S.cancel(db, w.org.id, doc.id, "SYN1", "SYN-NOT-A-REPLACEMENT", w.users[0].id)


def test_substitution_chain_ends_replaced_and_keeps_the_original_uuid(db, monkeypatch, tmp_path):
    S, w, pac, original = _stamped(db, monkeypatch, tmp_path)
    original_uuid = original.uuid
    run2, item2 = _second_committed_run(db, w)
    repl = S.create_replacement(db, original, run2, item2, w.users[0].id)
    assert repl.replaces_uuid == original_uuid and repl.replaces_document_id == original.id
    ch.process(db, w)
    db.refresh(repl)
    assert repl.status == "STAMPED" and repl.uuid != original_uuid
    S.cancel(db, w.org.id, original.id, "SYN1", repl.uuid, w.users[0].id)
    ch.process(db, w)
    db.refresh(original)
    assert original.status == "REPLACED" and original.uuid == original_uuid and original.replaced_by_uuid == repl.uuid
    assert ch.events(db, original)[-3:] == ["CANCEL_REQUESTED", "CANCELLED", "REPLACED"]
    assert ("cancel", f"{original.idempotency_key}:c1", f"{original_uuid}|SYN1|{repl.uuid}") in pac.calls
    # The run lanes: the original run's chain ended REPLACED (settled, not
    # "in progress"); the correction run's replacement is STAMPED.
    assert S.run_summary(db, w.run)["status"] == "REPLACED"
    assert S.run_summary(db, run2)["status"] == "STAMPED"


def test_cancel_rejected_returns_to_stamped_and_unknown_needs_a_cancel_query(db, monkeypatch, tmp_path):
    S, w, pac, doc = _stamped(db, monkeypatch, tmp_path, cancel=["reject", "timeout"], cancel_status=["cancelled"])
    S.cancel(db, w.org.id, doc.id, "SYN2", None, w.users[0].id)
    ch.process(db, w)
    db.refresh(doc)
    assert doc.status == "STAMPED" and "CANCEL_REJECTED" in ch.events(db, doc)
    S.cancel(db, w.org.id, doc.id, "SYN2", None, w.users[0].id)
    ch.process(db, w)
    db.refresh(doc)
    assert doc.status == "UNKNOWN" and doc.unknown_action == "CANCEL"
    S.request_status_query(db, w.org.id, doc.id, w.users[0].id)
    from app.modules.payroll.models import PayrollMxCfdiOutboxItem as O

    assert db.query(O).filter(O.document_id == doc.id, O.action == "CANCEL_STATUS_QUERY").count() == 1
    ch.process(db, w)
    db.refresh(doc)
    assert doc.status == "CANCELLED"


def test_only_stamped_documents_can_be_cancelled(db, monkeypatch, tmp_path):
    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    S.generate(db, w.run, w.users[0].id)
    (doc,) = ch.docs(db, w.run)
    with pytest.raises(Exception):
        S.cancel(db, w.org.id, doc.id, "SYN2", None, w.users[0].id)
