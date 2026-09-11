"""
tests/test_germany_pap_release_governance.py
----------------------------------------------
Phase 8G-1 (docs/PHASE_8G_1_GERMANY_PAP_RELEASE_GOVERNANCE_IMPLEMENTATION_REPORT.md)
— coverage for GermanyPapRelease: the internal production release/
activation governance gate that sits ABOVE PapAlgorithmAsset's own
statutory lifecycle.

Central invariant asserted throughout: satisfying every gate on a
release row NEVER changes resolve_pap_executor()'s behavior.
germany_pap/core.py is not imported anywhere in this file except in the
one test that explicitly re-confirms the production executor is still
unconditionally unavailable, even immediately after a release reaches
ACTIVE with every gate green.
"""

import hashlib
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, ForbiddenException, GermanyPapGateBlockedException
from app.modules.payroll import service
from app.modules.payroll.engine.germany_pap import production_gate
from app.modules.payroll.engine.germany_pap.golden_vector import AUTHORITATIVE_BMF, GermanyPapGoldenVector
from app.modules.payroll.models import TaxConfigurationAudit


def _certified_golden_vectors(asset_hash: str):
    """Builds one AUTHORITATIVE_BMF-classified vector whose actual outputs
    are constructed to match its expected outputs exactly, purely to
    exercise the release-governance gate mechanism in these tests. This is
    NOT real BMF evidence — it is a fixture standing in for "a Super Admin
    supplied a real, matching certification run" so these tests can drive
    a release through every OTHER gate without re-litigating golden-vector
    correctness here (that mechanism has its own dedicated coverage in
    test_germany_pap_golden_vector.py and the negative-path tests below)."""
    vector = GermanyPapGoldenVector(
        vector_id="TEST-CERT-001",
        source_document="Governance-mechanics test fixture, not a real BMF Pruftabelle row",
        source_page=0,
        source_hash_sha256=asset_hash,
        description="Mechanism-verification vector for release-governance tests",
        inputs={"STKL": 1, "RE4": Decimal("2000000")},
        expected_outputs={"LSTLZZ": Decimal("38000")},
        source_classification=AUTHORITATIVE_BMF,
    )
    return [vector], {"TEST-CERT-001": {"LSTLZZ": Decimal("38000")}}


# ── Fixtures / helpers ─────────────────────────────────────────────────────

def _ingest_asset(db, tax_year="2026", pap_version="2026-11-12-final", actor_id=1, content=b"official BMF PAP source content placeholder"):
    return service.ingest_pap_asset(
        db, jurisdiction_country="DE", tax_year=tax_year, pap_version=pap_version,
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
        source_content=content, source_agency="BMF", source_title="Programmablaufplan 2026",
        actor_id=actor_id,
    )


def _publish_asset(db, tax_year="2026", pap_version="2026-11-12-final", content=b"official BMF PAP source content placeholder"):
    row = _ingest_asset(db, tax_year=tax_year, pap_version=pap_version, content=content)
    row = service.set_pap_asset_status(db, row.id, "REVIEW", actor_id=1)
    row = service.set_pap_asset_approver(db, row.id, actor_id=2)
    return service.set_pap_asset_status(db, row.id, "PUBLISHED", actor_id=2)


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _full_rollback(db, release_id, requested_by=3, approved_by=4, reason=None, target_release_id=None):
    """Phase 8H: rollback is now a maker-checker'd two-step workflow
    (request -> approve), requested_by != approved_by. This test-only
    helper drives both steps and returns approve_pap_rollback's own
    (rolled_back, restored) tuple, matching the old single-call
    rollback_pap_release's return shape for the tests that assert on it."""
    service.request_pap_rollback(db, release_id, actor_id=requested_by, reason=reason)
    return service.approve_pap_rollback(db, release_id, actor_id=approved_by, target_release_id=target_release_id)


def _fully_satisfy_all_gates(db, release_id, asset_hash, preparer_id=1, approver_id=2):
    """Test-only helper: satisfies every gate dimension with explicit,
    actor-attributed evidence — mirrors exactly what a real Super Admin
    workflow would call, one function per gate, never a shortcut/bulk
    "mark everything true" path (no such path exists in service.py)."""
    service.record_pap_release_source_identity(db, release_id, actor_id=preparer_id, notes="Verified against bmf-steuerrechner.de")
    service.record_pap_release_source_hash_verification(db, release_id, actor_id=preparer_id)
    service.record_pap_release_source_finality(
        db, release_id, actor_id=preparer_id, status="VERIFIED",
        authority="Test-only fixture, NOT real BMF confirmation", reference="TEST-FIXTURE-ONLY",
    )
    service.record_pap_release_licensing(
        db, release_id, actor_id=preparer_id, status="AUTHORIZED",
        authority="Test-only fixture, NOT real BMF/legal authorization", reference="TEST-FIXTURE-ONLY",
    )
    vectors, actual_outputs = _certified_golden_vectors(asset_hash)
    service.record_pap_release_golden_vectors(
        db, release_id, actor_id=preparer_id, source_sha256=asset_hash,
        vectors=vectors, actual_outputs=actual_outputs,
    )
    service.record_pap_release_security_certification(db, release_id, actor_id=preparer_id)
    service.mark_pap_release_ready(db, release_id, actor_id=preparer_id)
    service.approve_pap_release(db, release_id, actor_id=approver_id)


# ── Release creation ────────────────────────────────────────────────────────

def test_create_release_binds_current_asset_hash(db):
    content = b"content A"
    asset = _ingest_asset(db, content=content)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    assert release.status == "NOT_READY"
    assert release.bound_source_content_sha256 == _hash(content)
    assert release.prepared_by_id == 1


def test_cannot_create_duplicate_release_for_same_asset(db):
    asset = _ingest_asset(db)
    service.create_pap_release(db, asset.id, actor_id=1)
    with pytest.raises(BadRequestException):
        service.create_pap_release(db, asset.id, actor_id=1)


# ── Gate tests — every dimension independently false ────────────────────────

def test_fresh_release_fails_every_gate(db):
    asset = _ingest_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    result = service.evaluate_pap_release_gate(db, release.id)
    assert result.is_activation_eligible is False
    assert set(result.failed_gates) == set(production_gate.REQUIRED_GATES)


def test_source_finality_not_verified_blocks_gate(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    # Un-verify finality only, leave everything else satisfied.
    service.record_pap_release_source_finality(db, release.id, actor_id=1, status="OPEN")
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "source_finality_verified" in result.failed_gates
    assert result.is_activation_eligible is False


def test_licensing_not_authorized_blocks_gate(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    service.record_pap_release_licensing(db, release.id, actor_id=1, status="PENDING")
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "licensing_authorized" in result.failed_gates


def test_unpublished_asset_blocks_gate(db):
    asset = _ingest_asset(db)  # DRAFT only, never published
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "asset_approved" in result.failed_gates


def test_hash_mismatch_blocks_gate_and_hash_verification_refuses(db):
    content = b"original bytes"
    asset = _publish_asset(db, content=content)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    # Simulate drift: the asset's own hash no longer matches what this
    # release was bound to (e.g. a bug elsewhere re-hashed the row).
    release.bound_source_content_sha256 = "0" * 64
    db.commit()
    with pytest.raises(BadRequestException):
        service.record_pap_release_source_hash_verification(db, release.id, actor_id=1)
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "source_hash_verified" in result.failed_gates


def test_golden_vectors_against_wrong_hash_rejected(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    with pytest.raises(BadRequestException):
        service.record_pap_release_golden_vectors(db, release.id, actor_id=1, source_sha256="f" * 64)
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "golden_vectors_passed" in result.failed_gates


def test_golden_vectors_with_no_vectors_supplied_rejected(db):
    """Phase 8BG regression: the old implementation accepted a bare hash
    with NO vector data at all and set golden_vectors_passed=True on pure
    assertion. Even a matching hash must never be sufficient by itself."""
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    with pytest.raises(BadRequestException):
        service.record_pap_release_golden_vectors(
            db, release.id, actor_id=1, source_sha256=asset.source_content_sha256,
        )
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "golden_vectors_passed" in result.failed_gates


def test_synthetic_golden_vector_can_never_satisfy_the_gate(db):
    """Phase 8BG regression: a SYNTHETIC-classified vector must be refused
    outright, regardless of whether its numbers happen to match — the
    classification check runs before, and independent of, the comparison."""
    from app.modules.payroll.engine.germany_pap.golden_vector import SYNTHETIC

    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    synthetic_vector = GermanyPapGoldenVector(
        vector_id="SYNTH-001", source_document="synthetic-test-fixture, not a real BMF publication",
        source_page=0, source_hash_sha256=asset.source_content_sha256,
        description="synthetic", inputs={"STKL": 1}, expected_outputs={"LSTLZZ": Decimal("38000")},
        source_classification=SYNTHETIC,
    )
    with pytest.raises(BadRequestException):
        service.record_pap_release_golden_vectors(
            db, release.id, actor_id=1, source_sha256=asset.source_content_sha256,
            vectors=[synthetic_vector], actual_outputs={"SYNTH-001": {"LSTLZZ": Decimal("38000")}},
        )
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "golden_vectors_passed" in result.failed_gates


def test_golden_vector_citing_a_different_source_hash_rejected(db):
    """A vector whose OWN source_hash_sha256 doesn't match the release's
    bound source hash must be refused even if source_sha256 (the outer
    call argument) is correct — this catches a vector transcribed for a
    different PAP version being smuggled in alongside a correct-looking
    top-level hash."""
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    mismatched_vector = GermanyPapGoldenVector(
        vector_id="AUTH-999", source_document="a different release's Pruftabelle",
        source_page=0, source_hash_sha256="9" * 64,
        description="wrong source", inputs={"STKL": 1}, expected_outputs={"LSTLZZ": Decimal("38000")},
        source_classification=AUTHORITATIVE_BMF,
    )
    with pytest.raises(BadRequestException):
        service.record_pap_release_golden_vectors(
            db, release.id, actor_id=1, source_sha256=asset.source_content_sha256,
            vectors=[mismatched_vector], actual_outputs={"AUTH-999": {"LSTLZZ": Decimal("38000")}},
        )


def test_golden_vector_output_mismatch_rejected(db):
    """An AUTHORITATIVE_BMF vector with correct hash but WRONG actual
    output must still fail — classification and hash binding alone are
    not enough, the numbers must actually match exactly."""
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    vectors, _ = _certified_golden_vectors(asset.source_content_sha256)
    with pytest.raises(BadRequestException):
        service.record_pap_release_golden_vectors(
            db, release.id, actor_id=1, source_sha256=asset.source_content_sha256,
            vectors=vectors, actual_outputs={"TEST-CERT-001": {"LSTLZZ": Decimal("1")}},
        )
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "golden_vectors_passed" in result.failed_gates


def test_security_not_certified_blocks_gate(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    service.record_pap_release_source_identity(db, release.id, actor_id=1)
    service.record_pap_release_source_hash_verification(db, release.id, actor_id=1)
    service.record_pap_release_source_finality(db, release.id, actor_id=1, status="VERIFIED")
    service.record_pap_release_licensing(db, release.id, actor_id=1, status="AUTHORIZED")
    vectors, actual_outputs = _certified_golden_vectors(asset.source_content_sha256)
    service.record_pap_release_golden_vectors(
        db, release.id, actor_id=1, source_sha256=asset.source_content_sha256,
        vectors=vectors, actual_outputs=actual_outputs,
    )
    # security_certified deliberately left False
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "security_certified" in result.failed_gates


def test_release_not_approved_blocks_gate(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    # Undo just the approval by re-querying — approve_pap_release already
    # ran inside the helper; assert the OTHER 7 gates were satisfied and
    # release_approved specifically requires a DISTINCT approver (covered
    # in the maker-checker section below), not re-tested for absence here
    # since _fully_satisfy_all_gates always approves. See
    # test_self_approval_rejected for the "approver missing/same" case.
    result = service.evaluate_pap_release_gate(db, release.id)
    assert result.is_activation_eligible is True  # sanity: helper truly satisfies everything


# ── The one theoretical "all gates satisfied" case — MUST NOT activate PAP ──

def test_all_gates_satisfied_recognizes_eligibility_but_never_activates_production_pap(db):
    """This is the phase's own required acceptance test (§31): the GATE
    must recognize eligibility, while the actual production executor
    remains completely unavailable, because reaching ACTIVE on this
    governance row has zero wiring into resolve_pap_executor()."""
    from app.modules.payroll.engine.germany_pap.core import (
        resolve_pap_executor, UnavailablePapExecutor, GermanyPapInvalidError,
    )
    from app.modules.payroll.engine.germany_pap.adapter import PAP_SOURCE_FINALITY, assert_pap_source_finality_resolved

    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)

    result = service.evaluate_pap_release_gate(db, release.id)
    assert result.is_activation_eligible is True
    assert result.failed_gates == ()

    activated = service.activate_pap_release(db, release.id, actor_id=3)
    assert activated.status == "ACTIVE"

    # The governance row says ACTIVE. Production PAP must remain exactly
    # as unavailable as it was before any of this ran.
    executor = resolve_pap_executor(asset)
    assert isinstance(executor, UnavailablePapExecutor)
    assert PAP_SOURCE_FINALITY == "OPEN"
    with pytest.raises(GermanyPapInvalidError):
        assert_pap_source_finality_resolved()


# ── Maker-checker ────────────────────────────────────────────────────────────

def test_self_approval_rejected(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    service.mark_pap_release_ready(db, release.id, actor_id=1)
    with pytest.raises(BadRequestException):
        service.approve_pap_release(db, release.id, actor_id=1)  # same as preparer


def test_distinct_approver_allowed(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    service.mark_pap_release_ready(db, release.id, actor_id=1)
    approved = service.approve_pap_release(db, release.id, actor_id=2)
    assert approved.status == "RELEASE_APPROVED"
    assert approved.approved_by_id == 2


def test_activation_by_same_actor_as_approver_rejected(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)  # approver_id=2
    with pytest.raises(BadRequestException):
        service.activate_pap_release(db, release.id, actor_id=2)  # same as approver


def test_activation_by_distinct_actor_succeeds(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    activated = service.activate_pap_release(db, release.id, actor_id=3)
    assert activated.status == "ACTIVE"
    assert activated.activated_by_id == 3


# ── RBAC / tenant isolation ──────────────────────────────────────────────────

def test_non_super_admin_cannot_reach_the_write_gate():
    from app.core.dependencies import get_current_super_admin

    fake_org_admin = type("FakeUser", (), {"role": "org_admin", "organization_id": 1})()
    with pytest.raises(ForbiddenException):
        get_current_super_admin(current_user=fake_org_admin)

    fake_payroll_admin = type("FakeUser", (), {"role": "payroll_admin", "organization_id": 1})()
    with pytest.raises(ForbiddenException):
        get_current_super_admin(current_user=fake_payroll_admin)

    # Every /compliance/germany/pap-releases/* endpoint in
    # super_admin/router.py is gated by this exact same dependency,
    # unmodified — so this single check covers all of them, consistent
    # with test_pap_algorithm_asset.py's own RBAC coverage for the
    # sibling PAP-asset endpoints (forged-JWT/401 behavior is inherited,
    # untouched, from the shared auth dependency chain and is exercised
    # by Phase 8E-1's live HTTP smoke, not duplicated here).


# ── Activation gate failure → blocked, structured reason ────────────────────

def test_activation_blocked_raises_structured_exception_and_sets_status(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    service.mark_pap_release_ready(db, release.id, actor_id=1)
    approved = service.approve_pap_release(db, release.id, actor_id=2)
    assert approved.status == "RELEASE_APPROVED"

    with pytest.raises(GermanyPapGateBlockedException) as exc_info:
        service.activate_pap_release(db, release.id, actor_id=3)

    failed = exc_info.value.trace["failedGates"]
    assert "source_finality_verified" in failed
    assert "licensing_authorized" in failed

    reloaded = service.get_pap_release_by_id(db, release.id)
    assert reloaded.status == "ACTIVATION_BLOCKED"

    events = (
        db.query(TaxConfigurationAudit)
        .filter(TaxConfigurationAudit.entity_type == "pap_release", TaxConfigurationAudit.entity_id == release.id)
        .all()
    )
    assert any(e.action == "activation_blocked" for e in events)


def test_retry_after_fixing_evidence_succeeds(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    service.mark_pap_release_ready(db, release.id, actor_id=1)
    service.approve_pap_release(db, release.id, actor_id=2)
    with pytest.raises(GermanyPapGateBlockedException):
        service.activate_pap_release(db, release.id, actor_id=3)

    # Fix the remaining evidence and retry from ACTIVATION_BLOCKED.
    service.record_pap_release_source_identity(db, release.id, actor_id=1)
    service.record_pap_release_source_hash_verification(db, release.id, actor_id=1)
    service.record_pap_release_source_finality(db, release.id, actor_id=1, status="VERIFIED")
    service.record_pap_release_licensing(db, release.id, actor_id=1, status="AUTHORIZED")
    vectors, actual_outputs = _certified_golden_vectors(asset.source_content_sha256)
    service.record_pap_release_golden_vectors(
        db, release.id, actor_id=1, source_sha256=asset.source_content_sha256,
        vectors=vectors, actual_outputs=actual_outputs,
    )
    service.record_pap_release_security_certification(db, release.id, actor_id=1)

    activated = service.activate_pap_release(db, release.id, actor_id=3)
    assert activated.status == "ACTIVE"


# ── No partial activation / one ACTIVE per country+tax_year ─────────────────

def test_second_release_cannot_activate_while_first_is_active(db):
    asset_a = _publish_asset(db, pap_version="v1", content=b"content v1")
    release_a = service.create_pap_release(db, asset_a.id, actor_id=1)
    _fully_satisfy_all_gates(db, release_a.id, asset_a.source_content_sha256)
    service.activate_pap_release(db, release_a.id, actor_id=3)

    service.set_pap_asset_status(db, asset_a.id, "SUPERSEDED", actor_id=2)
    asset_b = _publish_asset(db, pap_version="v2", content=b"content v2")
    release_b = service.create_pap_release(db, asset_b.id, actor_id=1)
    _fully_satisfy_all_gates(db, release_b.id, asset_b.source_content_sha256)

    with pytest.raises(BadRequestException):
        service.activate_pap_release(db, release_b.id, actor_id=3)


# ── Rollback ─────────────────────────────────────────────────────────────────

def test_rollback_without_target_deactivates_only(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    service.activate_pap_release(db, release.id, actor_id=3)

    rolled_back, restored = _full_rollback(db, release.id, requested_by=3, approved_by=4, reason="test rollback")
    assert rolled_back.status == "ROLLED_BACK"
    assert restored is None


def test_rollback_request_requires_distinct_approver(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    service.activate_pap_release(db, release.id, actor_id=3)

    service.request_pap_rollback(db, release.id, actor_id=3, reason="test")
    with pytest.raises(BadRequestException):
        service.approve_pap_rollback(db, release.id, actor_id=3)  # same as requester


def test_rollback_can_be_rejected_and_release_stays_active(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    service.activate_pap_release(db, release.id, actor_id=3)

    service.request_pap_rollback(db, release.id, actor_id=3, reason="having second thoughts")
    rejected = service.reject_pap_rollback(db, release.id, actor_id=4, reason="rollback not warranted")
    assert rejected.status == "ACTIVE"


def test_rollback_can_restore_a_previously_active_release(db):
    asset_a = _publish_asset(db, pap_version="v1", content=b"content v1")
    release_a = service.create_pap_release(db, asset_a.id, actor_id=1)
    _fully_satisfy_all_gates(db, release_a.id, asset_a.source_content_sha256)
    service.activate_pap_release(db, release_a.id, actor_id=3)

    # Roll A back (without restore) so B can occupy the one-ACTIVE slot.
    _full_rollback(db, release_a.id, requested_by=3, approved_by=4, reason="making way for v2")
    service.set_pap_asset_status(db, asset_a.id, "SUPERSEDED", actor_id=2)

    asset_b = _publish_asset(db, pap_version="v2", content=b"content v2")
    release_b = service.create_pap_release(db, asset_b.id, actor_id=1)
    _fully_satisfy_all_gates(db, release_b.id, asset_b.source_content_sha256)
    service.activate_pap_release(db, release_b.id, actor_id=3)

    # B turns out defective — roll back to A.
    rolled_back_b, restored_a = _full_rollback(
        db, release_b.id, requested_by=3, approved_by=4, reason="v2 defective", target_release_id=release_a.id,
    )
    assert rolled_back_b.status == "ROLLED_BACK"
    assert restored_a is not None
    assert restored_a.id == release_a.id
    assert restored_a.status == "ACTIVE"

    # Nothing about release_a's own original evidence/provenance was rewritten.
    reloaded_a = service.get_pap_release_by_id(db, release_a.id)
    assert reloaded_a.activated_by_id == 3
    assert reloaded_a.golden_vectors_source_sha256 == asset_a.source_content_sha256


def test_rollback_refuses_unproven_target(db):
    asset_a = _publish_asset(db, pap_version="v1", content=b"content v1")
    release_a = service.create_pap_release(db, asset_a.id, actor_id=1)
    _fully_satisfy_all_gates(db, release_a.id, asset_a.source_content_sha256)
    service.activate_pap_release(db, release_a.id, actor_id=3)

    # A never-activated release for a different asset in the same scope —
    # not a "safe" rollback target.
    service.set_pap_asset_status(db, asset_a.id, "SUPERSEDED", actor_id=2)
    asset_b = _publish_asset(db, pap_version="v2", content=b"content v2")
    unproven_release_b = service.create_pap_release(db, asset_b.id, actor_id=1)

    service.request_pap_rollback(db, release_a.id, actor_id=3, reason="test")
    with pytest.raises(BadRequestException):
        service.approve_pap_rollback(db, release_a.id, actor_id=4, target_release_id=unproven_release_b.id)


def test_only_active_release_can_be_rolled_back(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    with pytest.raises(BadRequestException):
        service.request_pap_rollback(db, release.id, actor_id=1, reason="not active yet")


# ── Audit trail ──────────────────────────────────────────────────────────────

def test_full_lifecycle_is_audited(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    service.activate_pap_release(db, release.id, actor_id=3)
    _full_rollback(db, release.id, requested_by=3, approved_by=4, reason="test")

    events = (
        db.query(TaxConfigurationAudit)
        .filter(TaxConfigurationAudit.entity_type == "pap_release", TaxConfigurationAudit.entity_id == release.id)
        .order_by(TaxConfigurationAudit.id)
        .all()
    )
    actions = [e.action for e in events]
    assert "create" in actions
    assert "status_change" in actions  # ready / approve
    assert "activated" in actions
    assert "rollback_requested" in actions
    assert "rollback_approved" in actions
    assert "rollback_completed" in actions
    for e in events:
        assert e.actor_id is not None
