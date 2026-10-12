"""
tests/test_us_locality_dataset_manager.py
--------------------------------------------
DB-integration coverage for the US Locality Dataset Manager (ZP-TAX-US-
2026-001 §10/§11.1, gap-closure Plan Phase 3, 2026-09-14) — the real
import/diff/stage/approve/activate/rollback workflow, exercised against
synthetic locality data (no real PSD-code/county registry has been
supplied yet — see the plan's own "explicitly not scheduled" list).
"""

from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.payroll import service
from app.modules.payroll.models import LocalityDataset, LocalityRate

IMPORTER_ID = 101
APPROVER_ID = 202


def _row(code, resident=None, nonresident=None, name=None, locality_type="MUNICIPAL"):
    return dict(
        localityCode=code, localityType=locality_type, localityName=name,
        residentRatePct=resident, nonresidentRatePct=nonresident, flatAmount=None, taxCollectorId=None,
    )


def test_import_creates_draft_with_real_checksum(db, organization):
    rows = [_row("CO001", resident=Decimal("1.5")), _row("CO002", resident=Decimal("2.0"))]
    dataset = service.import_locality_dataset(
        db, "US", "ZZ", "SYNTH-1", rows, actor_id=IMPORTER_ID,
    )
    assert dataset.status == "Draft"
    assert dataset.imported_by_id == IMPORTER_ID
    assert dataset.checksum_sha256 is not None and len(dataset.checksum_sha256) == 64
    rate_rows = service.list_locality_dataset_rates(db, dataset.id)
    assert {r.locality_code for r in rate_rows} == {"CO001", "CO002"}


def test_import_rejects_empty_rows(db, organization):
    with pytest.raises(BadRequestException):
        service.import_locality_dataset(db, "US", "ZZ", "SYNTH-EMPTY", [], actor_id=IMPORTER_ID)


def test_import_rejects_duplicate_locality_code_within_batch(db, organization):
    rows = [_row("CO001", resident=Decimal("1.5")), _row("CO001", resident=Decimal("9.9"))]
    with pytest.raises(BadRequestException):
        service.import_locality_dataset(db, "US", "ZZ", "SYNTH-DUP", rows, actor_id=IMPORTER_ID)


def test_diff_against_no_active_dataset_shows_everything_added(db, organization):
    rows = [_row("CO001", resident=Decimal("1.5")), _row("CO002", resident=Decimal("2.0"))]
    dataset = service.import_locality_dataset(db, "US", "ZZ2", "SYNTH-1", rows, actor_id=IMPORTER_ID)
    diff = service.diff_locality_dataset(db, dataset.id)
    assert diff["comparedAgainstDatasetId"] is None
    assert sorted(diff["added"]) == ["CO001", "CO002"]
    assert diff["removed"] == []
    assert diff["changed"] == []


def _stage_approve_activate(db, dataset, effective_from, importer_id=IMPORTER_ID, approver_id=APPROVER_ID):
    service.stage_locality_dataset(db, dataset.id, actor_id=importer_id)
    dataset.effective_from = effective_from
    db.commit()
    service.approve_locality_dataset(db, dataset.id, actor_id=approver_id)
    return service.activate_locality_dataset(db, dataset.id, actor_id=approver_id)


def test_full_lifecycle_activate_then_diff_then_rollback(db, organization):
    import datetime

    rows_v1 = [_row("CO001", resident=Decimal("1.5")), _row("CO002", resident=Decimal("2.0"))]
    v1 = service.import_locality_dataset(db, "US", "ZZ3", "SYNTH-V1", rows_v1, actor_id=IMPORTER_ID)
    activated_v1 = _stage_approve_activate(db, v1, datetime.date(2026, 1, 1))
    assert activated_v1.status == "Active"

    # A second import (added CO003, removed CO002, changed CO001's rate)
    # diffed against the now-Active v1 dataset.
    rows_v2 = [_row("CO001", resident=Decimal("3.0")), _row("CO003", resident=Decimal("4.0"))]
    v2 = service.import_locality_dataset(db, "US", "ZZ3", "SYNTH-V2", rows_v2, actor_id=IMPORTER_ID)
    diff = service.diff_locality_dataset(db, v2.id)
    assert diff["comparedAgainstDatasetId"] == v1.id
    assert diff["added"] == ["CO003"]
    assert diff["removed"] == ["CO002"]
    assert len(diff["changed"]) == 1
    assert diff["changed"][0]["localityCode"] == "CO001"
    # LocalityRate.resident_rate_pct is Numeric(6,4) — the DB round-trips
    # the value at that fixed precision, not the input's own string form.
    assert diff["changed"][0]["changes"]["resident_rate_pct"] == {"before": "1.5000", "after": "3.0000"}

    activated_v2 = _stage_approve_activate(db, v2, datetime.date(2026, 6, 1))
    assert activated_v2.status == "Active"

    # Only one Active dataset per (country, state) — v1 must now be Retired.
    db.refresh(v1)
    assert v1.status == "Retired"
    active_count = (
        db.query(LocalityDataset)
        .filter(LocalityDataset.jurisdiction_country == "US", LocalityDataset.jurisdiction_state == "ZZ3", LocalityDataset.status == "Active")
        .count()
    )
    assert active_count == 1

    # Roll back to v1 — v2 must now be Retired, v1 Active again.
    rolled_back = service.rollback_locality_dataset(db, v1.id, actor_id=APPROVER_ID)
    assert rolled_back.status == "Active"
    db.refresh(v2)
    assert v2.status == "Retired"
    active_count_after_rollback = (
        db.query(LocalityDataset)
        .filter(LocalityDataset.jurisdiction_country == "US", LocalityDataset.jurisdiction_state == "ZZ3", LocalityDataset.status == "Active")
        .count()
    )
    assert active_count_after_rollback == 1


def test_stage_only_allowed_from_draft(db, organization):
    dataset = service.import_locality_dataset(db, "US", "ZZ4", "SYNTH-1", [_row("CO001")], actor_id=IMPORTER_ID)
    service.stage_locality_dataset(db, dataset.id, actor_id=IMPORTER_ID)
    with pytest.raises(BadRequestException):
        service.stage_locality_dataset(db, dataset.id, actor_id=IMPORTER_ID)  # already Staged, not Draft


def test_activate_requires_effective_from(db, organization):
    dataset = service.import_locality_dataset(db, "US", "ZZ5", "SYNTH-1", [_row("CO001")], actor_id=IMPORTER_ID)
    service.stage_locality_dataset(db, dataset.id, actor_id=IMPORTER_ID)
    service.approve_locality_dataset(db, dataset.id, actor_id=APPROVER_ID)
    with pytest.raises(BadRequestException):
        service.activate_locality_dataset(db, dataset.id, actor_id=APPROVER_ID)  # no effective_from set


def test_activate_requires_distinct_approver_from_importer(db, organization):
    import datetime

    dataset = service.import_locality_dataset(db, "US", "ZZ6", "SYNTH-1", [_row("CO001")], actor_id=IMPORTER_ID)
    service.stage_locality_dataset(db, dataset.id, actor_id=IMPORTER_ID)
    dataset.effective_from = datetime.date(2026, 1, 1)
    db.commit()
    service.approve_locality_dataset(db, dataset.id, actor_id=IMPORTER_ID)  # same person as importer
    with pytest.raises(BadRequestException):
        service.activate_locality_dataset(db, dataset.id, actor_id=IMPORTER_ID)


def test_get_locality_dataset_404_for_missing_id(db, organization):
    with pytest.raises(NotFoundException):
        service.get_locality_dataset(db, 999999)
