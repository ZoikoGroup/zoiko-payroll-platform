"""
tests/test_singapore_phase66_hotfix.py
--------------------------------------
Phase 6.6 Workstream A — hotfix governance.

  Gap A (Singapore opt-in, _HOTFIX_DISTINCT_REVIEWER_COUNTRIES): the
    retrospective review of a hotfix activation is the deferred maker-checker
    (PackHotfixActivation's own docstring), so the Super Admin who ran the
    hotfix cannot review it, and a completed review is final. Refusals are
    audited. Other countries keep their existing review behaviour.
  Gap B (all countries — transactional correctness, no policy content): the
    Active status and its PackHotfixActivation record are persisted in ONE
    commit. A failure writing the record leaves neither — never an Active
    pack without hotfix evidence.

Emergency semantics are unchanged: a lone Super Admin may still hotfix-
activate an evidenced, golden-PASS Singapore pack; the normal maker-checker
path is untouched. app.* imports are lazy (tests/_db_safety.py).
"""

import pytest

A, B, C = 101, 202, 303


def _sg_pack(db):
    from app.modules.payroll import service
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    assert service.run_golden_test_certification(db, "SG", actor_id=A).status == "PASS"
    from tests._sg_evidence import accept_sg_gate

    accept_sg_gate(db)                       # Phase 6.10: SG activation needs G1 accepted
    return pack


def _hotfix(db, pack, actor=A):
    from app.modules.payroll import service

    return service.activate_jurisdiction_pack_hotfix(db, pack.id, "INC-66", "Emergency statutory fix", actor_id=actor)


def _activation(db, pack):
    from app.modules.payroll.models import PackHotfixActivation

    return db.query(PackHotfixActivation).filter(PackHotfixActivation.jurisdiction_pack_id == pack.id).one()


def _refused(db, pack):
    from app.modules.payroll.models import TaxConfigurationAudit

    return [a for a in db.query(TaxConfigurationAudit).filter(
        TaxConfigurationAudit.entity_type == "jurisdiction_pack", TaxConfigurationAudit.entity_id == pack.id,
        TaxConfigurationAudit.action == "refused").order_by(TaxConfigurationAudit.id)]


# ── Gap A ──────────────────────────────────────────────────────────────────

def test_hotfix_initiator_cannot_review_their_own_sg_hotfix(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _sg_pack(db)
    _hotfix(db, pack, actor=A)
    act = _activation(db, pack)
    with pytest.raises(BadRequestException, match="cannot review it"):
        service.review_pack_hotfix_activation(db, act.id, "looks fine", actor_id=A)
    db.refresh(act)
    assert (act.reviewed, act.reviewed_by_id, act.review_notes) == (False, None, None)
    [row] = _refused(db, pack)
    assert (row.actor_id, row.new_value) == (A, {"attempted": "hotfix_review", "result": "REFUSED", "path": "hotfix"})


def test_distinct_reviewer_succeeds_and_identity_is_recorded(db):
    from app.modules.payroll import service

    pack = _sg_pack(db)
    _hotfix(db, pack, actor=A)
    act = service.review_pack_hotfix_activation(db, _activation(db, pack).id, "Verified against CPF Board tables", actor_id=B)
    assert (act.reviewed, act.reviewed_by_id, act.review_notes) == (True, B, "Verified against CPF Board tables")
    assert act.reviewed_at is not None and act.activated_by_id == A
    assert service.list_pack_hotfix_activations(db, reviewed=False) == []


def test_a_completed_sg_review_cannot_be_replaced(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    pack = _sg_pack(db)
    _hotfix(db, pack, actor=A)
    act = service.review_pack_hotfix_activation(db, _activation(db, pack).id, "first review", actor_id=B)
    reviewed_at = act.reviewed_at
    for actor in (B, C):
        with pytest.raises(BadRequestException, match="already been reviewed"):
            service.review_pack_hotfix_activation(db, act.id, "overwrite attempt", actor_id=actor)
    db.refresh(act)
    assert (act.reviewed_by_id, act.review_notes, act.reviewed_at) == (B, "first review", reviewed_at)
    assert len(_refused(db, pack)) == 2


def test_other_countries_keep_their_existing_review_behaviour(db):
    """Opt-in scope: a UK hotfix may still be reviewed by its activator
    (single-Super-Admin operations), exactly as before Phase 6.6."""
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id="UK-P66", jurisdiction_country="UK", pack_type="tax", version="1.0", status="Approved")
    db.add(pack)
    db.commit()
    _hotfix(db, pack, actor=A)
    assert service.review_pack_hotfix_activation(db, _activation(db, pack).id, "ok", actor_id=A).reviewed is True


# ── Gap B ──────────────────────────────────────────────────────────────────

def _fail_hotfix_record_writes(db):
    from sqlalchemy import event

    from app.modules.payroll.models import PackHotfixActivation

    def before_flush(session, flush_context, instances):
        if any(isinstance(o, PackHotfixActivation) for o in session.new):
            raise RuntimeError("simulated failure writing the hotfix record")
    event.listen(db, "before_flush", before_flush)
    return lambda: event.remove(db, "before_flush", before_flush)


@pytest.mark.parametrize("country", ["SG", "UK"])
def test_failure_writing_the_hotfix_record_never_leaves_an_active_pack_without_evidence(db, country):
    from app.modules.payroll.models import JurisdictionPack, PackHotfixActivation

    if country == "SG":
        pack = _sg_pack(db)
    else:
        pack = JurisdictionPack(pack_id="UK-P66B", jurisdiction_country="UK", pack_type="tax", version="1.0",
                                status="Approved")
        db.add(pack)
        db.commit()
    before = pack.status
    undo = _fail_hotfix_record_writes(db)
    try:
        with pytest.raises(RuntimeError, match="simulated failure"):
            _hotfix(db, pack, actor=A)
    finally:
        undo()
    db.expire_all()
    assert db.query(JurisdictionPack).get(pack.id).status == before                      # activation rolled back
    assert db.query(PackHotfixActivation).count() == 0
    assert db.query(JurisdictionPack).get(pack.id).approved_by_id is None                 # no phantom approval


def test_successful_hotfix_persists_status_and_record_together(db):
    from app.modules.payroll.models import JurisdictionPack

    pack = _sg_pack(db)
    row = _hotfix(db, pack, actor=A)                                                       # lone Super Admin
    db.expire_all()
    stored = db.query(JurisdictionPack).get(pack.id)
    act = _activation(db, pack)
    assert (stored.status, stored.approved_by_id, row.status) == ("Active", A, "Active")
    assert (act.incident_id, act.activated_by_id, act.reviewed, act.activated_at is not None) == ("INC-66", A, False, True)


def test_refused_hotfix_leaves_no_record_and_no_approval(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import PackHotfixActivation
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)                                                              # no golden run -> refused
    db.commit()
    with pytest.raises(BadRequestException, match="golden-vector"):
        _hotfix(db, pack)
    db.refresh(pack)
    assert (pack.status, pack.approved_by_id, db.query(PackHotfixActivation).count()) == ("Draft", None, 0)


# ── unchanged paths + route security ──────────────────────────────────────

def test_normal_maker_checker_activation_is_unchanged_and_writes_no_hotfix_record(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import PackHotfixActivation

    pack = _sg_pack(db)
    service.set_jurisdiction_pack_status(db, pack.id, "In Review", actor_id=A)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)
    with pytest.raises(BadRequestException, match="cannot also activate"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=B)
    assert service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A).status == "Active"
    assert db.query(PackHotfixActivation).count() == 0


@pytest.mark.parametrize("path,method", [
    ("/api/super-admin/compliance/policies/{id}/hotfix-activate", "PUT"),
    ("/api/super-admin/compliance/hotfix-activations", "GET"),
    ("/api/super-admin/compliance/hotfix-activations/{activation_id}/review", "PUT"),
])
def test_hotfix_routes_are_platform_super_admin_only(path, method):
    """Hotfix records are platform-level (no organization): every route sits
    behind get_current_super_admin, which refuses org admins, payroll admins
    and tenant-bound Super Admins (test_singapore_phase56_admin)."""
    from app.core.dependencies import get_current_super_admin
    from app.main import app
    from app.modules.payroll.models import PackHotfixActivation

    route = next(r for r in app.routes if getattr(r, "path", None) == path and method in getattr(r, "methods", ()))

    def calls(dep, out):
        for d in dep.dependencies:
            out.add(d.call)
            calls(d, out)
        return out
    assert get_current_super_admin in calls(route.dependant, set())
    assert "organization_id" not in PackHotfixActivation.__table__.columns
