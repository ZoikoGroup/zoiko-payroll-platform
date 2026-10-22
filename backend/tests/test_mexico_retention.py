"""Mexico Phase 10c (plan D8): records governance. The Mexican record
categories are declared, but no retention period is decided (legal), so every
category stays BLOCKED_UNDECIDED and nothing can be purged; legal holds work
now; an employee with retained Mexican statutory records is never deleted.
SYNTHETIC world."""

import pytest
from fastapi import HTTPException

from tests import _mx_authority_helpers as ah


def _RS():
    from app.modules.payroll import retention_service

    return retention_service


def test_every_mexican_category_is_blocked_undecided_and_nothing_is_purgeable(db):
    RS = _RS()
    out = RS.retention_policies(db, "MX")
    cats = {c["category"]: c for c in out["categories"]}
    assert set(cats) == {"PAYROLL_RECORDS", "CFDI", "IMSS_INFONAVIT", "AUTHORITY_FILINGS", "PAYMENTS_AND_JOURNAL",
                         "TERMINATIONS", "PTU_AND_ANNUAL", "EMPLOYEE_IDENTITY"}
    assert all(c["state"] == "BLOCKED_UNDECIDED" and not c["purgePermitted"] for c in cats.values())
    assert "MX-D-RETENTION-PERIOD" in cats["CFDI"]["blocker"]
    assert all(RS.purge_refusal(db, "MX", c) for c in cats)                     # every purge refused
    with pytest.raises(Exception, match="MX-D-RETENTION-PERIOD"):
        RS.propose_retention_policy(db, "MX", {"recordCategory": "PAYROLL_RECORDS", "retentionYears": 5,
                                               "endOfRetention": "DELETE", "legalBasis": "x", "reason": "y"}, 1)


def test_an_employee_with_retained_mexican_records_is_never_deleted(db, monkeypatch):
    from app.modules.payroll import mexico_payment_service as P
    from app.modules.payroll import service

    w = ah.committed_world(db, monkeypatch, code="MXRET1")
    fields = dict(w.employee.compliance_fields or {})
    fields["clabe"] = "002180700012345678"                                       # SYNTHETIC
    w.employee.compliance_fields = fields
    db.commit()
    P.create_batch(db, w.org.id, w.run.id, w.users[0].id)
    assert _RS().settings("MX").retained_record_label(db, w.org.id, w.employee.id) == "salary payments"
    with pytest.raises(HTTPException) as exc:
        service.delete_employee(db, w.employee.id, w.org.id)
    assert exc.value.status_code == 409 and "retained statutory records (salary payments)" in exc.value.detail


def test_a_legal_hold_blocks_deletion_and_its_release_needs_a_second_person(db, monkeypatch):
    from app.modules.payroll import service

    RS = _RS()
    w = ah.committed_world(db, monkeypatch, code="MXRET2")
    hold = RS.place_legal_hold(db, "MX", w.org.id, w.employee.id, "SYNTHETIC: labour claim", "SYN-JUNTA-1",
                               w.users[0].id)
    with pytest.raises(Exception) as exc:                 # the ZP-PRIV platform check sees the hold first
        service.delete_employee(db, w.employee.id, w.org.id)
    assert exc.value.status_code == 409 and "legal hold" in exc.value.detail
    with pytest.raises(Exception):
        RS.release_legal_hold(db, "MX", w.org.id, hold.id, "SYNTHETIC: settled", w.users[0].id)
    RS.release_legal_hold(db, "MX", w.org.id, hold.id, "SYNTHETIC: settled", w.users[1].id)
    assert RS.active_legal_holds(db, "MX", w.org.id, w.employee.id) == []
