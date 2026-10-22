"""Mexico Phase 10a — salary payments (plan D2–D5). SYNTHETIC CLABEs. The file
is a Zoiko worklist (no bank layout saved): never a bank file, the full CLABE
read only when it is built and never stored (MX-061)."""

import json
from decimal import Decimal as D

import pytest

from tests import _mx_authority_helpers as ah

CLABE = "002180700012345678"           # SYNTHETIC, 18 digits
NEW_CLABE = "012180001234567897"       # SYNTHETIC


def _P():
    from app.modules.payroll import mexico_payment_service as P

    return P


def _set_clabe(db, emp, clabe):
    fields = dict(emp.compliance_fields or {})
    if clabe is None:
        fields.pop("clabe", None)
    else:
        fields["clabe"] = clabe
    emp.compliance_fields = fields
    db.commit()


def _world(db, monkeypatch, code, clabe=CLABE):
    w = ah.committed_world(db, monkeypatch, code=code)
    _set_clabe(db, w.employee, clabe)
    return w


def _released(db, w):
    b = _P().create_batch(db, w.org.id, w.run.id, w.users[0].id)
    return _P().release_batch(db, w.org.id, b["id"], w.users[1].id)


# ── batches ─────────────────────────────────────────────────────────────────

def test_a_batch_pays_each_payslip_net_and_needs_a_clabe(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollMxPaymentBatch

    w = _world(db, monkeypatch, "MXPAY1", clabe=None)
    with pytest.raises(MXBlock) as exc:
        _P().create_batch(db, w.org.id, w.run.id, w.users[0].id)
    assert exc.value.key == "MX_CLABE_MISSING" and CLABE not in str(exc.value)
    assert db.query(PayrollMxPaymentBatch).count() == 0
    _set_clabe(db, w.employee, CLABE)
    b = _P().create_batch(db, w.org.id, w.run.id, w.users[0].id)
    (item,) = ah.rh.mx_items(db, w.run)
    (pay,) = b["items"]
    assert b["status"] == "DRAFT" and b["fileMode"] == "WORKLIST"
    assert D(pay["amount"]) == D(str(item.net_pay)) > 0 and D(b["totalAmount"]) == D(pay["amount"])
    assert pay["clabeLast4"] == CLABE[-4:] and CLABE not in json.dumps(b)
    with pytest.raises(Exception, match="already has payment batch"):
        _P().create_batch(db, w.org.id, w.run.id, w.users[0].id)


def test_only_a_committed_run_is_paid(db, monkeypatch):
    w = _world(db, monkeypatch, "MXPAY2")
    draft = ah.new_run(db, w)
    from app.modules.payroll import service

    service.generate_payslips_for_run(db, draft, w.org.id, [w.employee.id])
    with pytest.raises(Exception, match="committed"):
        _P().create_batch(db, w.org.id, draft.id, w.users[0].id)


def test_release_is_four_eyes_and_only_a_draft_is_cancelled(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock

    w = _world(db, monkeypatch, "MXPAY3")
    b = _P().create_batch(db, w.org.id, w.run.id, w.users[0].id)
    with pytest.raises(Exception, match="released batch"):
        _P().export_worklist(db, w.org.id, b["id"], w.users[0].id)
    with pytest.raises(MXBlock) as exc:
        _P().release_batch(db, w.org.id, b["id"], w.users[0].id)
    assert exc.value.key == "MX_FOUR_EYES_REQUIRED"
    out = _P().release_batch(db, w.org.id, b["id"], w.users[1].id)
    assert out["status"] == "RELEASED" and out["checkerId"] == w.users[1].id
    with pytest.raises(Exception, match="Only a DRAFT batch"):
        _P().cancel_batch(db, w.org.id, b["id"], "SYNTHETIC", w.users[0].id)


# ── the worklist ────────────────────────────────────────────────────────────

def test_the_worklist_is_labelled_not_a_bank_file_and_the_clabe_is_never_stored(db, monkeypatch):
    from app.modules.payroll.engine.countries.mexico import MXBlock
    from app.modules.payroll.models import PayrollMxPaymentBatch, PayrollMxPaymentItem

    w = _world(db, monkeypatch, "MXPAY4")
    b = _released(db, w)
    out = _P().export_worklist(db, w.org.id, b["id"], w.users[0].id)
    lines = out["content"].splitlines()
    assert lines[0].startswith("ZOIKO PAYMENT WORKLIST - NOT A BANK FILE")
    assert CLABE in out["content"] and f"ZP-{b['id']}-" in out["content"]
    batch = db.get(PayrollMxPaymentBatch, b["id"])
    assert batch.last_export_sha256 == out["sha256"] and batch.exports == 1
    stored = [json.dumps({c.name: str(getattr(r, c.name)) for c in r.__table__.columns})
              for r in [batch, *db.query(PayrollMxPaymentItem).all()]]
    assert not [s for s in stored if CLABE in s]                                     # MX-061
    _set_clabe(db, w.employee, NEW_CLABE)
    with pytest.raises(MXBlock) as exc:
        _P().export_worklist(db, w.org.id, b["id"], w.users[0].id)
    assert exc.value.key == "MX_CLABE_CHANGED"


# ── outcomes, re-issue ──────────────────────────────────────────────────────

def test_outcomes_need_a_reference_and_close_the_batch(db, monkeypatch):
    w = _world(db, monkeypatch, "MXPAY5")
    b = _released(db, w)
    item_id = b["items"][0]["id"]
    with pytest.raises(Exception, match="reference"):
        _P().record_item_outcome(db, w.org.id, item_id, {"outcome": "SETTLED"}, w.users[0].id)
    assert _P().record_item_outcome(db, w.org.id, item_id, {"outcome": "UNKNOWN"}, w.users[0].id)["status"] == "UNKNOWN"
    assert _P().get_batch(db, w.org.id, b["id"])["status"] == "RELEASED"               # UNKNOWN keeps it open
    _P().record_item_outcome(db, w.org.id, item_id, {"outcome": "SETTLED", "reference": "SYN-SPEI-1"}, w.users[0].id)
    assert _P().get_batch(db, w.org.id, b["id"])["status"] == "CLOSED"
    with pytest.raises(Exception, match="already SETTLED"):
        _P().record_item_outcome(db, w.org.id, item_id, {"outcome": "RETURNED", "reference": "X", "reason": "Y"},
                                 w.users[0].id)


def test_a_returned_payment_is_reissued_in_a_new_batch_with_the_current_clabe(db, monkeypatch):
    w = _world(db, monkeypatch, "MXPAY6")
    b = _released(db, w)
    item_id = b["items"][0]["id"]
    with pytest.raises(Exception, match="reason"):
        _P().record_item_outcome(db, w.org.id, item_id, {"outcome": "RETURNED", "reference": "SYN-RET-1"},
                                 w.users[0].id)
    _P().record_item_outcome(db, w.org.id, item_id, {"outcome": "RETURNED", "reference": "SYN-RET-1",
                                                     "reason": "SYNTHETIC: account closed"}, w.users[0].id)
    _set_clabe(db, w.employee, NEW_CLABE)
    again = _P().reissue(db, w.org.id, b["id"], w.users[0].id)
    (copy,) = again["items"]
    assert again["status"] == "DRAFT" and again["reissueOfBatchId"] == b["id"]
    assert copy["reissueOfItemId"] == item_id and copy["clabeLast4"] == NEW_CLABE[-4:]
    assert D(copy["amount"]) == D(b["items"][0]["amount"])
    assert _P().get_batch(db, w.org.id, b["id"])["items"][0]["reissuedByItemId"] == copy["id"]
    with pytest.raises(Exception, match="No failed or returned"):
        _P().reissue(db, w.org.id, b["id"], w.users[0].id)
    _P().cancel_batch(db, w.org.id, again["id"], "SYNTHETIC", w.users[0].id)          # frees the original
    assert _P().get_batch(db, w.org.id, b["id"])["items"][0]["reissuedByItemId"] is None


# ── the run's reset (Phase 6 rule) ──────────────────────────────────────────

def test_a_released_batch_refuses_the_reset_and_a_draft_one_is_cancelled_by_it(db, monkeypatch):
    from fastapi import HTTPException

    from app.modules.payroll import mexico_run_service

    w = _world(db, monkeypatch, "MXPAY7")
    b = _released(db, w)
    with pytest.raises(HTTPException) as exc:
        mexico_run_service.reset_run(db, w.run, w.users[0].id, "SYNTHETIC")
    assert exc.value.status_code == 409 and f"payment batch {b['id']} is RELEASED" in exc.value.detail
    w2 = _world(db, monkeypatch, "MXPAY8")
    d = _P().create_batch(db, w2.org.id, w2.run.id, w2.users[0].id)
    out = mexico_run_service.reset_run(db, w2.run, w2.users[0].id, "SYNTHETIC")
    assert out["removed"]["paymentBatchesCancelled"] == 1
    assert _P().get_batch(db, w2.org.id, d["id"])["status"] == "CANCELLED"


def test_payment_routes(db, monkeypatch):
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    w = _world(db, monkeypatch, "MXPAYAPI")
    w.org.workspace_type = "EVALUATION"
    db.commit()
    with http(db, principal(w.org.id, w.users[0].id)) as c:
        made = c.post(f"{ORG_BASE}/runs/{w.run.id}/payment-batch")
        assert made.status_code == 200, made.text
        own = c.post(f"{ORG_BASE}/payments/batches/{made.json()['id']}/release")
        assert own.status_code == 400 and "MX_FOUR_EYES_REQUIRED" in own.text
    with http(db, principal(w.org.id, w.users[1].id)) as c:
        bid = made.json()["id"]
        assert c.post(f"{ORG_BASE}/payments/batches/{bid}/release").json()["status"] == "RELEASED"
        f = c.post(f"{ORG_BASE}/payments/batches/{bid}/worklist")
        assert f.status_code == 200 and f.headers["cache-control"].split(",")[0].strip() == "no-store"
        assert "attachment" in f.headers["content-disposition"] and f.text.startswith("ZOIKO PAYMENT WORKLIST")
        assert c.get(f"{ORG_BASE}/payments/batches", params={"run_id": w.run.id}).json()[0]["id"] == bid
