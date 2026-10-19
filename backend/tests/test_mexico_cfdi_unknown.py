"""Mexico Phase 7 — the UNKNOWN rule (§4.2 revised 2026-10-17, MX-062):
no automatic retry; the only automatic action is a status query; a retry
needs operator confirmation (recorded) after at least one NOT_FOUND and
reuses the SAME payload and the SAME idempotency key; "definitively not
found" needs provider config with no default; a late FOUND never produces a
second stamp; restore reconciliation; UUID conflict. SYNTHETIC."""

from datetime import timedelta

import pytest

from tests import _mx_cfdi_helpers as ch


def _S():
    from app.modules.payroll import mexico_cfdi_service as S

    return S


def _unknown(db, monkeypatch, tmp_path, stamp="timeout", **script):
    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    pac = ch.mock(monkeypatch, stamp=[stamp] + script.pop("then", []), **script)
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    (doc,) = ch.docs(db, w.run)
    assert doc.status == "UNKNOWN" and doc.unknown_action == "STAMP"
    return S, w, pac, doc


def _query(db, S, w, doc):
    S.request_status_query(db, w.org.id, doc.id, w.users[0].id)
    ch.process(db, w)
    db.refresh(doc)


def test_timeout_is_unknown_and_never_retried_automatically(db, monkeypatch, tmp_path):
    S, w, pac, doc = _unknown(db, monkeypatch, tmp_path)
    for _ in range(3):
        out = ch.process(db, w)
        assert all("action" not in r or r["action"] != "STAMP" for r in out["processed"])
    assert [c[0] for c in pac.calls] == ["stamp"]
    assert "STAMP_UNKNOWN" in ch.events(db, doc)


def test_query_found_adopts_the_uuid_without_a_second_stamp(db, monkeypatch, tmp_path):
    S, w, pac, doc = _unknown(db, monkeypatch, tmp_path, stamp="timeout_after_stamp")
    _query(db, S, w, doc)
    assert doc.status == "STAMPED" and doc.uuid == pac.uuid_by_key[doc.idempotency_key]
    assert [c[0] for c in pac.calls] == ["stamp", "status"] and pac.stamps_by_key[doc.idempotency_key] == 1


def test_retry_needs_a_query_first_then_operator_confirmation(db, monkeypatch, tmp_path):
    S, w, pac, doc = _unknown(db, monkeypatch, tmp_path)
    with pytest.raises(Exception) as exc:                       # never blind
        S.confirm_retry(db, w.org.id, doc.id, w.users[0].id, "resend")
    assert exc.value.key == "MX_CFDI_STATUS_QUERY_REQUIRED"
    _query(db, S, w, doc)                                       # NOT_FOUND
    assert doc.status == "UNKNOWN" and "STATUS_NOT_FOUND" in ch.events(db, doc)
    with pytest.raises(Exception):                              # a reason is required
        S.confirm_retry(db, w.org.id, doc.id, w.users[0].id, "  ")
    S.confirm_retry(db, w.org.id, doc.id, w.users[0].id, "PAC confirmed it never received it")
    assert "OPERATOR_RETRY_CONFIRMED" in ch.events(db, doc) and doc.status == "SIGNED"


def test_retry_reuses_the_same_payload_and_the_same_key(db, monkeypatch, tmp_path):
    S, w, pac, doc = _unknown(db, monkeypatch, tmp_path)
    _query(db, S, w, doc)
    S.confirm_retry(db, w.org.id, doc.id, w.users[0].id, "operator confirmed")
    ch.process(db, w)
    db.refresh(doc)
    stamps = [c for c in pac.calls if c[0] == "stamp"]
    assert len(stamps) == 2 and stamps[0][1] == stamps[1][1] == doc.idempotency_key   # SAME key
    assert stamps[0][2] == stamps[1][2] == doc.payload_hash                             # SAME payload
    assert doc.status == "STAMPED" and pac.stamps_by_key[doc.idempotency_key] == 1
    from app.modules.payroll.models import PayrollMxCfdiOutboxItem as O

    rows = db.query(O).filter(O.document_id == doc.id, O.action == "STAMP").order_by(O.attempt_no).all()
    assert [r.attempt_no for r in rows] == [1, 2] and {r.idempotency_key for r in rows} == {doc.idempotency_key}
    assert rows[1].operator_confirmed_by_id == w.users[0].id


def test_late_found_after_not_found_produces_no_second_stamp(db, monkeypatch, tmp_path):
    """The PAC stamped but its answer was lost; the first query lags
    (NOT_FOUND); the operator confirms a retry; a second query then answers
    FOUND before the retry is sent → the UUID is adopted, the pending retry is
    withdrawn, and nothing is stamped a second time."""
    S, w, pac, doc = _unknown(db, monkeypatch, tmp_path, stamp="timeout_after_stamp", status=["not_found", "auto"])
    _query(db, S, w, doc)
    assert doc.status == "UNKNOWN"
    S.confirm_retry(db, w.org.id, doc.id, w.users[0].id, "operator confirmed")
    from app.modules.payroll.models import PayrollMxCfdiOutboxItem as O

    retry = db.query(O).filter(O.document_id == doc.id, O.action == "STAMP", O.attempt_no == 2).one()
    # The reconciling operator queries again before the retry goes out; the
    # outbox always processes status queries before stamps (MX-062).
    db.add(O(document_id=doc.id, action="STATUS_QUERY", attempt_no=2, payload_hash=doc.payload_hash,
             idempotency_key=f"{doc.idempotency_key}:q2", status="PENDING"))
    db.commit()
    ch.process(db, w)
    db.refresh(doc)
    assert doc.status == "STAMPED" and doc.uuid == pac.uuid_by_key[doc.idempotency_key]
    assert pac.stamps_by_key[doc.idempotency_key] == 1
    assert len([c for c in pac.calls if c[0] == "stamp"]) == 1                          # the retry was never sent
    db.refresh(retry)
    assert retry.status == "FAILED" and "withdrawn" in retry.last_error


def test_late_found_after_a_sent_retry_keeps_one_uuid(db, monkeypatch, tmp_path):
    """A deduplicating PAC answers the retry (same key) with the existing UUID;
    a later FOUND for the same key is a no-op."""
    S, w, pac, doc = _unknown(db, monkeypatch, tmp_path, stamp="timeout_after_stamp", status=["not_found", "auto"])
    _query(db, S, w, doc)
    S.confirm_retry(db, w.org.id, doc.id, w.users[0].id, "operator confirmed")
    ch.process(db, w)
    db.refresh(doc)
    first_uuid = doc.uuid
    assert doc.status == "STAMPED" and pac.stamps_by_key[doc.idempotency_key] == 1
    from app.modules.payroll.models import PayrollMxCfdiOutboxItem as O

    db.add(O(document_id=doc.id, action="STATUS_QUERY", attempt_no=9, payload_hash=doc.payload_hash,
             idempotency_key=f"{doc.idempotency_key}:q9", status="PENDING"))
    db.commit()
    ch.process(db, w)
    db.refresh(doc)
    assert doc.uuid == first_uuid and doc.status == "STAMPED" and "STATUS_FOUND_ALREADY_STAMPED" in ch.events(db, doc)


def test_definitively_not_found_needs_provider_config_without_default(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_pac as P
    from app.modules.payroll.models import PayrollMxCfdiEvent as E

    S, w, pac, doc = _unknown(db, monkeypatch, tmp_path)
    for _ in range(3):
        _query(db, S, w, doc)
    state = S.definitively_not_found(db, doc)
    assert state == {"definitive": False, "notFoundQueries": 3, "providerConfig": False}      # no config → never
    monkeypatch.setitem(P._PROVIDER_RETRY_CONFIG, "MOCK", P.ProviderRetryConfig(min_wait_seconds=600,
                                                                                min_not_found_queries=2))
    assert S.definitively_not_found(db, doc)["definitive"] is False                          # wait not met
    sent = db.query(E).filter(E.document_id == doc.id, E.event_type == "STAMP_SENT").one()
    sent.occurred_at = sent.occurred_at - timedelta(hours=1)
    db.commit()
    assert S.definitively_not_found(db, doc)["definitive"] is True
    ch.process(db, w)
    assert db.get(type(doc), doc.id).status == "UNKNOWN"                                      # still no auto-retry
    monkeypatch.setitem(P._PROVIDER_RETRY_CONFIG, "MOCK", P.ProviderRetryConfig(min_wait_seconds=1,
                                                                                min_not_found_queries=1))
    assert P.retry_config("MOCK") is None                                                    # one query is never definitive


def test_restore_moves_in_flight_documents_to_unknown(db, monkeypatch, tmp_path):
    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    ch.mock(monkeypatch)
    S.generate(db, w.run, w.users[0].id)
    (doc,) = ch.docs(db, w.run)
    S._transition(db, doc, "SUBMITTED", "STAMP_SENT")         # a crash right after the send
    db.commit()
    assert S.reconcile_after_restore(db, w.org.id, w.users[0].id) == {"movedToUnknown": 1}
    db.refresh(doc)
    assert doc.status == "UNKNOWN" and doc.unknown_action == "STAMP" and "RESTORE_RECONCILED" in ch.events(db, doc)


def test_uuid_conflict_goes_to_unknown(db, monkeypatch, tmp_path):
    from app.modules.payroll.mexico_pac import StatusResult

    S, w, pac, doc = _unknown(db, monkeypatch, tmp_path, stamp="timeout_after_stamp")
    _query(db, S, w, doc)
    assert doc.status == "STAMPED"
    S._adopt_uuid(db, doc, "SYN-DIFFERENT-UUID", StatusResult(outcome="FOUND"), "STATUS_FOUND")
    db.commit()
    assert doc.status == "UNKNOWN" and "UUID_CONFLICT" in ch.events(db, doc)
