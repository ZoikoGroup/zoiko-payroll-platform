"""Mexico Phase 8 B7 — the UNKNOWN rule for any transmission (MX-043, the
Phase 7 §4.2 rule): no automatic retry; a retry needs a recorded NOT_FOUND
and an operator's confirmation with a reason; the same row, payload hash and
idempotency key are reused; a late FOUND after NOT_FOUND adopts the
reference and nothing is sent twice; "definitively not found" needs channel
config with no default."""

import pytest

from tests import _mx_authority_helpers as ah


def _exported_alta(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    s.I.export_worklist(db, w.org.id, w.users[0].id)
    (alta,) = ah.movements(db, w)
    return s, w, alta


def test_unknown_is_never_failed_and_never_retried_without_a_status_check(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s, w, alta = _exported_alta(db, monkeypatch)
    s.L.mark_unknown(db, w.org.id, "MOVEMENT", alta, w.users[0].id, "uploaded; IDSE gave no acuse")
    db.commit()
    assert alta.status == "UNKNOWN" and alta.unknown_since is not None
    with pytest.raises(MXBlock) as exc:
        s.L.confirm_retry(db, w.org.id, "MOVEMENT", alta, w.users[0].id, "try again")
    assert exc.value.key == "MX_AUTHORITY_STATUS_CHECK_REQUIRED"
    s.I.generate_movements(db, w.org.id, w.users[0].id)
    assert len(ah.movements(db, w)) == 1                                    # nothing regenerated behind it


def test_retry_reuses_the_same_row_payload_and_key(db, monkeypatch):
    s, w, alta = _exported_alta(db, monkeypatch)
    key, payload = alta.idempotency_key, alta.payload_hash
    s.L.mark_unknown(db, w.org.id, "MOVEMENT", alta, w.users[0].id)
    s.L.record_status_check(db, w.org.id, "MOVEMENT", alta, False, None, w.users[0].id)
    with pytest.raises(Exception, match="reason"):
        s.L.confirm_retry(db, w.org.id, "MOVEMENT", alta, w.users[0].id, "  ")
    s.L.confirm_retry(db, w.org.id, "MOVEMENT", alta, w.users[0].id, "IDSE shows nothing for this worker")
    db.commit()
    assert alta.status == "PENDING" and (alta.idempotency_key, alta.payload_hash) == (key, payload)
    out = s.I.export_worklist(db, w.org.id, w.users[0].id)                   # re-sent: the same facts
    (again,) = ah.movements(db, w)
    assert again.id == alta.id and (again.idempotency_key, again.payload_hash) == (key, payload)
    assert again.status == "EXPORTED" and out["count"] == 1
    assert ah.events(db, "MOVEMENT", alta)[-4:] == ["STATUS_NOT_FOUND", "OPERATOR_RETRY_CONFIRMED", "RETRY_READY",
                                                     "RE_EXPORTED"]


def test_a_late_found_after_not_found_files_once_and_nothing_is_sent_again(db, monkeypatch):
    s, w, alta = _exported_alta(db, monkeypatch)
    s.L.mark_unknown(db, w.org.id, "MOVEMENT", alta, w.users[0].id)
    s.L.record_status_check(db, w.org.id, "MOVEMENT", alta, False, None, w.users[0].id)
    s.L.confirm_retry(db, w.org.id, "MOVEMENT", alta, w.users[0].id, "not in IDSE")
    db.commit()
    # Before the retry is re-exported, IDSE shows the original after all.
    with pytest.raises(Exception, match="FOUND"):
        s.L.record_status_check(db, w.org.id, "MOVEMENT", alta, False, None, w.users[0].id)
    s.L.record_status_check(db, w.org.id, "MOVEMENT", alta, True, "SYN-IDSE-LATE", w.users[0].id)
    db.commit()
    assert alta.status == "FILED" and alta.authority_reference == "SYN-IDSE-LATE"
    assert "LATE_FOUND" in ah.events(db, "MOVEMENT", alta)
    with pytest.raises(Exception, match="No PENDING"):
        s.I.export_worklist(db, w.org.id, w.users[0].id)                   # no second filing
    assert len(ah.movements(db, w)) == 1


def test_definitively_not_found_needs_channel_config_with_no_default(db, monkeypatch):
    from datetime import timedelta

    from app.modules.payroll.engine.countries import mexico_content as c

    s, w, alta = _exported_alta(db, monkeypatch)
    s.L.mark_unknown(db, w.org.id, "MOVEMENT", alta, w.users[0].id)
    for _ in range(3):
        s.L.record_status_check(db, w.org.id, "MOVEMENT", alta, False, None, w.users[0].id)
    db.commit()
    assert c.MX_AUTHORITY_RETRY_CONFIG == {}
    assert s.L.definitively_not_found(db, "MOVEMENT", alta) is False
    monkeypatch.setattr(c, "MX_AUTHORITY_RETRY_CONFIG", {"IDSE": {"min_wait_seconds": 3600, "min_not_found_checks": 1}})
    assert s.L.definitively_not_found(db, "MOVEMENT", alta) is False            # one check is never enough
    monkeypatch.setattr(c, "MX_AUTHORITY_RETRY_CONFIG", {"IDSE": {"min_wait_seconds": 3600, "min_not_found_checks": 2}})
    assert s.L.definitively_not_found(db, "MOVEMENT", alta) is False            # the wait has not passed
    alta.unknown_since = alta.unknown_since - timedelta(hours=2)
    assert s.L.definitively_not_found(db, "MOVEMENT", alta) is True
    # Even then the retry is the operator's, never automatic.
    assert alta.status == "UNKNOWN"


def test_a_liability_declaration_with_an_unknown_outcome(db, monkeypatch):
    s = ah.svc()
    w = ah.committed_world(db, monkeypatch)
    s.F.accrue(db, w.org.id, w.users[0].id)
    (isr,) = ah.liabilities(db, w, "SAT_ISR")
    s.L.mark_unknown(db, w.org.id, "LIABILITY", isr, w.users[0].id, "declaration submitted, no acuse")
    db.commit()
    payload = isr.payload_hash
    assert payload is not None
    run2 = ah.commit(db, w, ah.new_run(db, w))                             # rows arriving while UNKNOWN
    s.F.accrue(db, w.org.id, w.users[0].id)
    rows = ah.liabilities(db, w, "SAT_ISR")
    assert [(r.sequence, r.status) for r in rows] == [(0, "UNKNOWN"), (1, "ACCRUED")]
    assert rows[0].payload_hash == payload                                  # the sent figures never change
    s.L.record_status_check(db, w.org.id, "LIABILITY", isr, True, "SYN-SAT-ACUSE", w.users[0].id)
    db.commit()
    assert isr.status == "FILED" and isr.declaration_reference == "SYN-SAT-ACUSE"
    assert run2.id in {x["runId"] for x in s.F.liability_view(db, rows[1], with_sources=True)["sources"]}


def test_a_changed_payload_can_never_be_resent(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    s, w, alta = _exported_alta(db, monkeypatch)
    s.L.mark_unknown(db, w.org.id, "MOVEMENT", alta, w.users[0].id)
    s.L.record_status_check(db, w.org.id, "MOVEMENT", alta, False, None, w.users[0].id)
    s.L.confirm_retry(db, w.org.id, "MOVEMENT", alta, w.users[0].id, "resend")
    db.commit()
    alta.sbc = alta.sbc + 1                                                 # a tampered fact
    db.commit()
    with pytest.raises(MXBlock) as exc:
        s.I.export_worklist(db, w.org.id, w.users[0].id)
    assert exc.value.key == "MX_AUTHORITY_PAYLOAD_CHANGED"
