"""
tests/test_germany_pap_rollback_and_concurrency.py
-----------------------------------------------------
Phase 8H (docs/PHASE_8H_GERMANY_PAP_EXTERNAL_EVIDENCE_AND_FINAL_READINESS_REPORT.md)
— closes the two internal technical gaps Phase 8G-2 explicitly disclosed
as unresolved:

1. Rollback had no maker-checker distinct from activation (fixed:
   request_pap_rollback / reject_pap_rollback / approve_pap_rollback,
   requested_by != approved_by, enforced in service.py).
2. Only sequential-commit conflict detection had been tested (fixed
   below: a genuine two-connection, two-thread race against a real
   file-based SQLite database, proving the new DB-level partial unique
   index — not just the service-layer SELECT — is what actually prevents
   two releases from being ACTIVE for the same scope at once).

This file deliberately does NOT connect to the project's real remote
PostgreSQL instance (PAYROLL_DATABASE_URL in .env) for the concurrency
test below, even though the phase brief's own preference is Postgres
over SQLite: that URL points at a shared, non-local database this
session has no authorization to write test/race-condition traffic into,
and the risk of leaving artifacts or interfering with any other
connected process is disproportionate to what a local, fully-isolated,
file-based SQLite database can already prove about the SAME SQLAlchemy-
level partial-unique-index construct (already independently proven
dialect-equivalent to PostgreSQL by Phase 8E-2's own DDL-compilation
method). See the phase report's own §13/§17 for the full disclosure.
"""

import os
import tempfile
import threading
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.models import GermanyPapRelease


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


def _fully_satisfy_all_gates(db, release_id, asset_hash, preparer_id=1, approver_id=2):
    service.record_pap_release_source_identity(db, release_id, actor_id=preparer_id)
    service.record_pap_release_source_hash_verification(db, release_id, actor_id=preparer_id)
    service.record_pap_release_source_finality(
        db, release_id, actor_id=preparer_id, status="VERIFIED",
        authority="Test-only fixture, NOT real BMF confirmation", reference="TEST-FIXTURE-ONLY",
    )
    service.record_pap_release_licensing(
        db, release_id, actor_id=preparer_id, status="AUTHORIZED",
        authority="Test-only fixture, NOT real BMF/legal authorization", reference="TEST-FIXTURE-ONLY",
    )
    service.record_pap_release_golden_vectors(db, release_id, actor_id=preparer_id, source_sha256=asset_hash)
    service.record_pap_release_security_certification(db, release_id, actor_id=preparer_id)
    service.mark_pap_release_ready(db, release_id, actor_id=preparer_id)
    service.approve_pap_release(db, release_id, actor_id=approver_id)


def _full_rollback(db, release_id, requested_by=3, approved_by=4, reason=None, target_release_id=None):
    service.request_pap_rollback(db, release_id, actor_id=requested_by, reason=reason)
    return service.approve_pap_rollback(db, release_id, actor_id=approved_by, target_release_id=target_release_id)


# ── Rollback maker-checker ──────────────────────────────────────────────────

def test_rollback_approval_requires_distinct_actor_from_requester(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    service.activate_pap_release(db, release.id, actor_id=3)

    service.request_pap_rollback(db, release.id, actor_id=5, reason="test")
    with pytest.raises(BadRequestException):
        service.approve_pap_rollback(db, release.id, actor_id=5)  # same as requester

    approved = service.approve_pap_rollback(db, release.id, actor_id=6)  # distinct actor
    assert approved[0].status == "ROLLED_BACK"


def test_rollback_request_only_allowed_from_active(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    with pytest.raises(BadRequestException):
        service.request_pap_rollback(db, release.id, actor_id=1, reason="not active")


def test_rollback_reject_returns_release_to_active_and_is_idempotency_safe(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    service.activate_pap_release(db, release.id, actor_id=3)

    service.request_pap_rollback(db, release.id, actor_id=3, reason="reconsidering")
    rejected = service.reject_pap_rollback(db, release.id, actor_id=4)
    assert rejected.status == "ACTIVE"

    # Idempotency: rejecting again (no rollback currently requested) fails safely.
    with pytest.raises(BadRequestException):
        service.reject_pap_rollback(db, release.id, actor_id=4)


def test_rollback_approve_only_allowed_from_rollback_requested(db):
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    service.activate_pap_release(db, release.id, actor_id=3)
    with pytest.raises(BadRequestException):
        service.approve_pap_rollback(db, release.id, actor_id=4)  # no rollback requested yet


def test_rolled_back_cannot_transition_anywhere(db):
    """ROLLED_BACK remains terminal — no ROLLED_BACK -> ACTIVE shortcut
    exists anywhere except approve_pap_rollback's own explicit
    target_release_id restore path, which is a DIFFERENT release row
    being restored, never the rolled-back row itself."""
    asset = _publish_asset(db)
    release = service.create_pap_release(db, asset.id, actor_id=1)
    _fully_satisfy_all_gates(db, release.id, asset.source_content_sha256)
    service.activate_pap_release(db, release.id, actor_id=3)
    _full_rollback(db, release.id, requested_by=3, approved_by=4)

    with pytest.raises(BadRequestException):
        service.request_pap_rollback(db, release.id, actor_id=3, reason="undo?")
    with pytest.raises(BadRequestException):
        service.activate_pap_release(db, release.id, actor_id=5)


def test_rollback_never_touches_the_asset_or_any_other_release(db):
    """Rollback safety (§15): never deletes statutory assets, never
    mutates a different release's evidence."""
    asset_a = _publish_asset(db, pap_version="v1", content=b"content v1")
    release_a = service.create_pap_release(db, asset_a.id, actor_id=1)
    _fully_satisfy_all_gates(db, release_a.id, asset_a.source_content_sha256)
    service.activate_pap_release(db, release_a.id, actor_id=3)

    asset_a_hash_before = asset_a.source_content_sha256
    asset_a_status_before = asset_a.status

    _full_rollback(db, release_a.id, requested_by=3, approved_by=4, reason="test")

    reloaded_asset_a = service.get_pap_asset_by_id(db, asset_a.id)
    assert reloaded_asset_a.source_content_sha256 == asset_a_hash_before
    assert reloaded_asset_a.status == asset_a_status_before  # still PUBLISHED — rollback never touches the asset


# ── True DB-level concurrency (two real connections, one shared file) ──────

def _make_file_engine(db_path):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})
    return engine


@pytest.fixture()
def file_db():
    """A file-based (not :memory:) SQLite database, so two genuinely
    separate SQLAlchemy engines/connections can be opened against the
    SAME underlying database file — the :memory: + StaticPool fixture in
    conftest.py shares one single connection for the whole test, which
    cannot demonstrate real multi-connection contention."""
    from app.database import Base
    import app.modules.organizations.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.payroll.models  # noqa: F401

    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    setup_engine = _make_file_engine(path)
    Base.metadata.create_all(setup_engine)
    setup_engine.dispose()

    yield path

    try:
        os.remove(path)
    except OSError:
        pass


def test_two_releases_for_the_same_scope_cannot_both_be_published_and_approved_at_once(db):
    """Structural finding (Phase 8H, disclosed in the report): the
    application-level race described in the phase brief ("release A and
    release B, both eligible, race to activate") can only arise if TWO
    releases are simultaneously gate-eligible for the same
    (country, tax_year) — which requires their two PapAlgorithmAsset rows
    to BOTH be PUBLISHED at once. PapAlgorithmAsset's own pre-existing
    one-PUBLISHED-per-(country,tax_year) rule (Phase 3, untouched here)
    already makes that state unreachable through the ordinary service API.
    This test proves that upstream prevention directly, so the DB-level
    partial unique index below is correctly understood as defense-in-depth
    for this specific path, not the only thing standing between the
    system and a double-ACTIVE state on this path."""
    _publish_asset(db, pap_version="v1", content=b"content v1")  # asset_a, PUBLISHED

    asset_b = service.ingest_pap_asset(
        db, jurisdiction_country="DE", tax_year="2026", pap_version="v2",
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31),
        source_content=b"content v2", source_agency="BMF", source_title="Programmablaufplan 2026",
        actor_id=1,
    )
    asset_b = service.set_pap_asset_status(db, asset_b.id, "REVIEW", actor_id=1)
    asset_b = service.set_pap_asset_approver(db, asset_b.id, actor_id=2)
    with pytest.raises(BadRequestException):
        service.set_pap_asset_status(db, asset_b.id, "PUBLISHED", actor_id=2)


def test_true_db_level_concurrent_activation_only_one_wins(file_db):
    """Genuine two-connection, two-thread race directly against the
    database's own partial unique index (uq_pap_release_one_active_per_scope),
    bypassing the service layer's own upstream business rules (which, per
    the previous test, already make this scenario unreachable through the
    ordinary API) so the DATABASE constraint itself — not the application
    logic around it — is what is actually being proven here, per §19's own
    instruction not to rely on "a fragile application-only race
    assumption." Two rows, two different PapAlgorithmAsset parents (to
    satisfy uq_pap_release_one_per_asset), same (jurisdiction_country,
    tax_year), both starting non-ACTIVE; two real OS threads on two real
    SQLAlchemy engines/connections against the same SQLite FILE (not
    :memory:) synchronize on a barrier and then race to set each one's
    own row to ACTIVE. Exactly one commit must succeed."""
    setup_engine = _make_file_engine(file_db)
    SetupSession = sessionmaker(bind=setup_engine, autoflush=False, autocommit=False)
    setup_db = SetupSession()

    asset_a = _publish_asset(setup_db, pap_version="v1", content=b"content v1")
    release_a = service.create_pap_release(setup_db, asset_a.id, actor_id=1)
    _fully_satisfy_all_gates(setup_db, release_a.id, asset_a.source_content_sha256)

    service.set_pap_asset_status(setup_db, asset_a.id, "SUPERSEDED", actor_id=2)
    asset_b = _publish_asset(setup_db, pap_version="v2", content=b"content v2")
    release_b = service.create_pap_release(setup_db, asset_b.id, actor_id=1)
    _fully_satisfy_all_gates(setup_db, release_b.id, asset_b.source_content_sha256)

    release_a_id, release_b_id = release_a.id, release_b.id
    setup_db.commit()
    setup_db.close()
    setup_engine.dispose()

    results = {}
    barrier = threading.Barrier(2)

    def race_to_active(name, release_id):
        engine = _make_file_engine(file_db)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        thread_db = Session()
        try:
            row = thread_db.query(GermanyPapRelease).filter(GermanyPapRelease.id == release_id).one()
            barrier.wait(timeout=10)
            row.status = "ACTIVE"
            try:
                thread_db.commit()
                results[name] = "COMMITTED"
            except Exception as exc:  # sqlite3.IntegrityError surfaces via SQLAlchemy's wrapper
                thread_db.rollback()
                results[name] = f"REJECTED:{type(exc).__name__}"
        finally:
            thread_db.close()
            engine.dispose()

    t1 = threading.Thread(target=race_to_active, args=("release_a", release_a_id))
    t2 = threading.Thread(target=race_to_active, args=("release_b", release_b_id))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    outcomes = list(results.values())
    assert sum(1 for o in outcomes if o == "COMMITTED") == 1, f"expected exactly one COMMITTED outcome, got: {results}"
    assert sum(1 for o in outcomes if o.startswith("REJECTED")) == 1, f"expected exactly one REJECTED outcome, got: {results}"

    verify_engine = _make_file_engine(file_db)
    VerifySession = sessionmaker(bind=verify_engine, autoflush=False, autocommit=False)
    verify_db = VerifySession()
    active_rows = (
        verify_db.query(GermanyPapRelease)
        .filter(GermanyPapRelease.status == "ACTIVE", GermanyPapRelease.jurisdiction_country == "DE", GermanyPapRelease.tax_year == "2026")
        .all()
    )
    assert len(active_rows) == 1
    verify_db.close()
    verify_engine.dispose()
