"""
tests/test_germany_pap_final_certification.py
------------------------------------------------
Phase 8G-2 (docs/PHASE_8G_2_GERMANY_PAP_FINAL_TECHNICAL_CERTIFICATION_REPORT.md)
— closes the specific certification gaps Phase 8G-1's own test file did not
yet cover: architectural bypass boundaries (no direct InterpreterPapExecutor
construction outside tests, no BMF live-service calls anywhere in the
backend), idempotency of every release-governance mutation, DB integrity
guards, a combined historical-reproducibility scenario across
PapAlgorithmAsset supersession + GermanyPapRelease governance, and one
full end-to-end workflow narrative test.

Real BMF-derived numeric content (the 31/31 golden-vector re-run, the
factor-path rounding re-check, and the church-tax R-field re-check) was
re-executed live, this session, against a freshly re-downloaded XML —
see the phase report's own §9/§13. Consistent with every prior PAP phase's
standing discipline, that real content is NOT committed here as a test
fixture; this file's own tests use synthetic/structural assertions only.
"""

import inspect
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.engine.germany_pap.golden_vector import AUTHORITATIVE_BMF, GermanyPapGoldenVector
from app.modules.payroll.models import GermanyPapRelease


def _certified_golden_vectors(asset_hash: str):
    """Same governance-mechanics fixture as
    test_germany_pap_release_governance.py's helper of the same name —
    an AUTHORITATIVE_BMF-classified vector whose actual outputs are
    constructed to match exactly, standing in for a real Super Admin
    certification run so these tests can exercise the OTHER release
    gates/workflows without re-litigating golden-vector correctness."""
    vector = GermanyPapGoldenVector(
        vector_id="TEST-CERT-001",
        source_document="Governance-mechanics test fixture, not a real BMF Pruftabelle row",
        source_page=0,
        source_hash_sha256=asset_hash,
        description="Mechanism-verification vector for final-certification tests",
        inputs={"STKL": 1, "RE4": Decimal("2000000")},
        expected_outputs={"LSTLZZ": Decimal("38000")},
        source_classification=AUTHORITATIVE_BMF,
    )
    return [vector], {"TEST-CERT-001": {"LSTLZZ": Decimal("38000")}}


def _publish_asset(db, tax_year="2026", pap_version="2026-11-12-final", content=b"official BMF PAP source content placeholder"):
    row = service.ingest_pap_asset(
        db, jurisdiction_country="DE", tax_year=tax_year, pap_version=pap_version,
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
        source_content=content, source_agency="BMF", source_title="Programmablaufplan 2026",
        actor_id=1,
    )
    row = service.set_pap_asset_status(db, row.id, "REVIEW", actor_id=1)
    row = service.set_pap_asset_approver(db, row.id, actor_id=2)
    return service.set_pap_asset_status(db, row.id, "PUBLISHED", actor_id=2)


def _full_rollback(db, release_id, requested_by=3, approved_by=4, reason=None, target_release_id=None):
    """Phase 8H: rollback is a maker-checker'd two-step workflow
    (request -> approve), requested_by != approved_by."""
    service.request_pap_rollback(db, release_id, actor_id=requested_by, reason=reason)
    return service.approve_pap_rollback(db, release_id, actor_id=approved_by, target_release_id=target_release_id)


def _drive_release_to_active(db, asset, preparer_id=1, approver_id=2, activator_id=3):
    release = service.create_pap_release(db, asset.id, actor_id=preparer_id)
    service.record_pap_release_source_identity(db, release.id, actor_id=preparer_id)
    service.record_pap_release_source_hash_verification(db, release.id, actor_id=preparer_id)
    service.record_pap_release_source_finality(
        db, release.id, actor_id=preparer_id, status="VERIFIED",
        authority="Test-only fixture, NOT real BMF confirmation",
    )
    service.record_pap_release_licensing(
        db, release.id, actor_id=preparer_id, status="AUTHORIZED",
        authority="Test-only fixture, NOT real legal/BMF authorization",
    )
    vectors, actual_outputs = _certified_golden_vectors(asset.source_content_sha256)
    service.record_pap_release_golden_vectors(
        db, release.id, actor_id=preparer_id, source_sha256=asset.source_content_sha256,
        vectors=vectors, actual_outputs=actual_outputs,
    )
    service.record_pap_release_security_certification(db, release.id, actor_id=preparer_id)
    service.mark_pap_release_ready(db, release.id, actor_id=preparer_id)
    service.approve_pap_release(db, release.id, actor_id=approver_id)
    return service.activate_pap_release(db, release.id, actor_id=activator_id)


# ── Architectural bypass boundaries ──────────────────────────────────────

def test_no_direct_interpreter_executor_construction_outside_adapter_and_tests():
    """InterpreterPapExecutor may be DEFINED in adapter.py and CONSTRUCTED
    by tests, but no production module (service.py, super_admin/router.py,
    payroll/router.py, countries/germany.py) may construct it directly —
    the only sanctioned path to a real executor is resolve_pap_executor()
    itself (which, today, still always returns UnavailablePapExecutor)."""
    from app.modules.payroll import service as payroll_service
    from app.modules.super_admin import router as super_admin_router
    from app.modules.payroll import router as payroll_router
    from app.modules.payroll.engine.countries import germany

    for module in (payroll_service, super_admin_router, payroll_router, germany):
        src = inspect.getsource(module)
        assert "InterpreterPapExecutor" not in src, f"{module.__name__} must not reference InterpreterPapExecutor directly"


def test_no_bmf_live_service_calls_anywhere_in_backend():
    """Zoiko must never call the BMF live calculation service as a
    production shortcut (Phase 8F §10/§12 — explicitly NOT APPROVED).
    Scans every backend source file for the BMF domain / its known
    interface paths; the only permitted appearances are inside doc
    comments quoting the phase's own explicitly-restricted evidence
    (which this test allows for, since those are prose citations, not
    executable HTTP calls) — so this test greps for an actual outbound
    call shape, not merely the domain string."""
    import pathlib
    import re

    backend_root = pathlib.Path(__file__).resolve().parent.parent / "app"
    call_shape = re.compile(r"(requests|httpx|urllib|aiohttp)\.[a-zA-Z_]*\(\s*[\"'][^\"']*bmf-steuerrechner", re.IGNORECASE)
    offenders = []
    for path in backend_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if call_shape.search(text):
            offenders.append(str(path))
    assert offenders == [], f"Found outbound HTTP calls to the BMF live service in: {offenders}"


def test_production_gate_module_has_zero_dependencies_on_db_or_network():
    """production_gate.py must remain pure — no SQLAlchemy, no requests/
    httpx, no filesystem access — confirming it cannot itself become a
    channel for bypassing the gate via I/O side effects."""
    from app.modules.payroll.engine.germany_pap import production_gate

    src = inspect.getsource(production_gate)
    for forbidden in ("import requests", "import httpx", "sqlalchemy", "open(", "urlopen"):
        assert forbidden not in src


# ── Exact asset/hash binding ──────────────────────────────────────────────

def test_release_has_no_mutator_for_its_own_asset_binding(db):
    """There must be no service function that can repoint an existing
    GermanyPapRelease at a different PapAlgorithmAsset — the binding is
    set once, at create_pap_release, and is otherwise immutable for the
    life of the row (a new asset version requires a new release row,
    never an in-place repoint)."""
    import app.modules.payroll.service as service_module

    release_functions = [
        name for name in dir(service_module)
        if "pap_release" in name and callable(getattr(service_module, name))
    ]
    # None of the release-governance functions accept a parameter that
    # could repoint pap_asset_id after creation.
    for name in release_functions:
        fn = getattr(service_module, name)
        params = inspect.signature(fn).parameters
        assert "pap_asset_id" not in params or name == "create_pap_release", (
            f"{name} must not accept pap_asset_id — only create_pap_release binds a release to an asset"
        )


def test_asset_hash_drift_after_binding_is_detected_not_silently_accepted(db):
    asset = _publish_asset(db, content=b"original bytes")
    release = service.create_pap_release(db, asset.id, actor_id=1)
    bound_before = release.bound_source_content_sha256

    # Simulate the asset's own hash changing under the release (should
    # never happen through any real ingestion path — PapAlgorithmAsset's
    # own hash is set once at ingestion and never re-written — but the
    # gate must fail closed even in this adversarial scenario).
    asset.source_content_sha256 = "f" * 64
    db.commit()

    reloaded = service.get_pap_release_by_id(db, release.id)
    assert reloaded.bound_source_content_sha256 == bound_before  # never silently re-bound
    result = service.evaluate_pap_release_gate(db, release.id)
    assert "source_hash_verified" in result.failed_gates


# ── Idempotency ──────────────────────────────────────────────────────────

def test_repeated_approve_call_is_rejected_not_duplicated(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    service.mark_pap_release_ready(db, release.id, actor_id=1)
    service.approve_pap_release(db, release.id, actor_id=2)
    with pytest.raises(BadRequestException):
        service.approve_pap_release(db, release.id, actor_id=2)  # already RELEASE_APPROVED


def test_repeated_activate_call_is_rejected_not_duplicated(db):
    asset = _publish_asset(db)
    activated = _drive_release_to_active(db, asset)
    assert activated.status == "ACTIVE"
    with pytest.raises(BadRequestException):
        service.activate_pap_release(db, activated.id, actor_id=4)  # already ACTIVE


def test_repeated_rollback_call_is_rejected(db):
    asset = _publish_asset(db)
    activated = _drive_release_to_active(db, asset)
    _full_rollback(db, activated.id, requested_by=3, approved_by=4, reason="first rollback")
    with pytest.raises(BadRequestException):
        # already ROLLED_BACK — cannot request another rollback of it
        service.request_pap_rollback(db, activated.id, actor_id=3, reason="second rollback")


# ── Database integrity ───────────────────────────────────────────────────

def test_create_release_rejects_unknown_asset(db):
    with pytest.raises(NotFoundException):
        service.create_pap_release(db, 999999, actor_id=1)


def test_ready_transition_rejected_from_non_not_ready_status(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    service.mark_pap_release_ready(db, release.id, actor_id=1)
    with pytest.raises(BadRequestException):
        service.mark_pap_release_ready(db, release.id, actor_id=1)  # already READY_FOR_RELEASE


def test_only_one_active_release_row_can_exist_per_scope_at_the_db_level(db):
    """Complements 8G-1's service-layer conflict test with a direct query
    against the table itself: after driving one release ACTIVE, a raw
    query for other ACTIVE rows in the same scope must return none."""
    from app.modules.payroll.models import PapAlgorithmAsset

    asset = _publish_asset(db)
    activated = _drive_release_to_active(db, asset)

    active_rows = (
        db.query(GermanyPapRelease)
        .join(PapAlgorithmAsset, GermanyPapRelease.pap_asset_id == PapAlgorithmAsset.id)
        .filter(
            GermanyPapRelease.status == "ACTIVE",
            PapAlgorithmAsset.jurisdiction_country == "DE",
            PapAlgorithmAsset.tax_year == "2026",
        )
        .all()
    )
    assert [r.id for r in active_rows] == [activated.id]


# ── Sequential "concurrency" — two actors racing to activate different
# releases for the same scope; the second must observe the first's
# already-committed state (the realistic guarantee available in this
# single-writer-per-request backend architecture; see the phase report's
# own disclosed limitation on true multi-connection race testing). ──────

def test_second_activation_attempt_observes_first_committed_activation(db):
    asset_a = _publish_asset(db, pap_version="v1", content=b"content v1")
    release_a = service.create_pap_release(db, asset_a.id, actor_id=1)
    service.record_pap_release_source_identity(db, release_a.id, actor_id=1)
    service.record_pap_release_source_hash_verification(db, release_a.id, actor_id=1)
    service.record_pap_release_source_finality(db, release_a.id, actor_id=1, status="VERIFIED")
    service.record_pap_release_licensing(db, release_a.id, actor_id=1, status="AUTHORIZED")
    vectors_a, actual_outputs_a = _certified_golden_vectors(asset_a.source_content_sha256)
    service.record_pap_release_golden_vectors(
        db, release_a.id, actor_id=1, source_sha256=asset_a.source_content_sha256,
        vectors=vectors_a, actual_outputs=actual_outputs_a,
    )
    service.record_pap_release_security_certification(db, release_a.id, actor_id=1)
    service.mark_pap_release_ready(db, release_a.id, actor_id=1)
    service.approve_pap_release(db, release_a.id, actor_id=2)

    # "Actor 1" activates A first — while asset A is still PUBLISHED.
    service.activate_pap_release(db, release_a.id, actor_id=3)

    # A new asset version can only be PUBLISHED once A is superseded
    # (PapAlgorithmAsset's own one-PUBLISHED-per-year rule, unchanged) —
    # note this does NOT retroactively touch release_a, which is already
    # ACTIVE and stays that way until an explicit rollback.
    service.set_pap_asset_status(db, asset_a.id, "SUPERSEDED", actor_id=2)
    asset_b = _publish_asset(db, pap_version="v2", content=b"content v2")
    release_b = service.create_pap_release(db, asset_b.id, actor_id=1)
    service.record_pap_release_source_identity(db, release_b.id, actor_id=1)
    service.record_pap_release_source_hash_verification(db, release_b.id, actor_id=1)
    service.record_pap_release_source_finality(db, release_b.id, actor_id=1, status="VERIFIED")
    service.record_pap_release_licensing(db, release_b.id, actor_id=1, status="AUTHORIZED")
    vectors_b, actual_outputs_b = _certified_golden_vectors(asset_b.source_content_sha256)
    service.record_pap_release_golden_vectors(
        db, release_b.id, actor_id=1, source_sha256=asset_b.source_content_sha256,
        vectors=vectors_b, actual_outputs=actual_outputs_b,
    )
    service.record_pap_release_security_certification(db, release_b.id, actor_id=1)
    service.mark_pap_release_ready(db, release_b.id, actor_id=1)
    service.approve_pap_release(db, release_b.id, actor_id=2)

    # "Actor 2" then attempts to activate B for the same scope — must be
    # rejected because it observes A's already-committed ACTIVE row.
    with pytest.raises(BadRequestException):
        service.activate_pap_release(db, release_b.id, actor_id=3)


# ── Historical reproducibility across asset supersession + release governance ──

def test_historical_release_governance_survives_a_new_version_being_published_and_activated(db):
    """Payroll-A-equivalent scenario: release A reaches ACTIVE for asset
    v1. A new asset v2 is later published and its own release reaches
    ACTIVE (after A is rolled back, per the one-ACTIVE-per-scope rule).
    Release A's own historical evidence/identity fields must remain
    exactly as they were — nothing about A is rewritten by B's existence,
    matching PapAlgorithmAsset's own superseded-but-never-mutated
    guarantee (test_pap_algorithm_asset.py's
    test_resolve_does_not_return_superseded_asset_for_historical_date)."""
    asset_a = _publish_asset(db, pap_version="v1", content=b"content v1")
    release_a = _drive_release_to_active(db, asset_a, preparer_id=1, approver_id=2, activator_id=3)
    original_snapshot = {
        "id": release_a.id,
        "bound_source_content_sha256": release_a.bound_source_content_sha256,
        "golden_vectors_source_sha256": release_a.golden_vectors_source_sha256,
        "prepared_by_id": release_a.prepared_by_id,
        "approved_by_id": release_a.approved_by_id,
        "activated_by_id": release_a.activated_by_id,
    }

    _full_rollback(db, release_a.id, requested_by=3, approved_by=4, reason="making way for v2")
    service.set_pap_asset_status(db, asset_a.id, "SUPERSEDED", actor_id=2)

    asset_b = _publish_asset(db, pap_version="v2", content=b"content v2")
    _drive_release_to_active(db, asset_b, preparer_id=1, approver_id=2, activator_id=3)

    reloaded_a = service.get_pap_release_by_id(db, release_a.id)
    assert reloaded_a.status == "ROLLED_BACK"
    assert reloaded_a.bound_source_content_sha256 == original_snapshot["bound_source_content_sha256"]
    assert reloaded_a.golden_vectors_source_sha256 == original_snapshot["golden_vectors_source_sha256"]
    assert reloaded_a.prepared_by_id == original_snapshot["prepared_by_id"]
    assert reloaded_a.approved_by_id == original_snapshot["approved_by_id"]
    assert reloaded_a.activated_by_id == original_snapshot["activated_by_id"]
    # Asset A itself is also untouched by B's existence, mirroring the
    # already-certified PapAlgorithmAsset guarantee.
    reloaded_asset_a = service.get_pap_asset_by_id(db, asset_a.id)
    assert reloaded_asset_a.status == "SUPERSEDED"
    assert reloaded_asset_a.source_content_sha256 == asset_a.source_content_sha256


# ── Full end-to-end workflow narrative ────────────────────────────────────

def test_full_release_governance_workflow_end_to_end(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    assert release.status == "NOT_READY"

    gate = service.evaluate_pap_release_gate(db, release.id)
    assert gate.is_activation_eligible is False
    assert len(gate.failed_gates) == 7  # asset_approved is already true; all others still false

    service.record_pap_release_source_identity(db, release.id, actor_id=1, notes="checked bmf-steuerrechner.de")
    service.record_pap_release_source_hash_verification(db, release.id, actor_id=1)
    service.record_pap_release_source_finality(db, release.id, actor_id=1, status="VERIFIED", authority="TEST-FIXTURE-ONLY")
    service.record_pap_release_licensing(db, release.id, actor_id=1, status="AUTHORIZED", authority="TEST-FIXTURE-ONLY")
    vectors, actual_outputs = _certified_golden_vectors(asset.source_content_sha256)
    service.record_pap_release_golden_vectors(
        db, release.id, actor_id=1, source_sha256=asset.source_content_sha256,
        vectors=vectors, actual_outputs=actual_outputs,
    )
    service.record_pap_release_security_certification(db, release.id, actor_id=1)

    gate = service.evaluate_pap_release_gate(db, release.id)
    assert gate.failed_gates == ("release_approved",)  # everything else now satisfied

    service.mark_pap_release_ready(db, release.id, actor_id=1)
    approved = service.approve_pap_release(db, release.id, actor_id=2)
    assert approved.status == "RELEASE_APPROVED"

    gate = service.evaluate_pap_release_gate(db, release.id)
    assert gate.is_activation_eligible is True

    activated = service.activate_pap_release(db, release.id, actor_id=3)
    assert activated.status == "ACTIVE"

    rolled_back, restored = _full_rollback(db, release.id, requested_by=3, approved_by=4, reason="end of workflow test")
    assert rolled_back.status == "ROLLED_BACK"
    assert restored is None
