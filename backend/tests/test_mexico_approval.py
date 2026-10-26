"""Mexico (ZP-MX-ENG-001) pack APPROVAL gate (Phase 2, open item 5) — the
Mexico-only, signature-gated pack_approval_refusal hook called from
service.set_jurisdiction_pack_approver — plus the pinned, unchanged approver
behaviour of every other country (OUT_OF_SCOPE_DEFECTS.md OOS-5).

Every Mexico content row and source here is SYNTHETIC test data."""

from datetime import datetime, timezone

import pytest

APPROVER = 21


def _seed_ready(db, monkeypatch, status):
    import tempfile
    from pathlib import Path

    from app.modules.payroll import mexico_sources
    from app.modules.payroll.models import SourceArtifact
    from scripts.seed_mexico_canonical_packs import seed_mexico
    from tests.test_mexico_activation_gates import _manifest, _synthetic_national_content, _write_manifest

    _synthetic_national_content(monkeypatch)
    # Phase 11d: approval also needs every cited source VERIFIED, with its
    # verification-log entry — a SYNTHETIC manifest and log on disk.
    manifest_path = Path(tempfile.mkdtemp()) / "SOURCES_MANIFEST.csv"
    _write_manifest(manifest_path, list(_manifest().values()))
    monkeypatch.setattr(mexico_sources, "MANIFEST_PATH", manifest_path)
    pack = seed_mexico(db, manifest=_manifest())["national"]
    for artifact in db.query(SourceArtifact).all():
        artifact.reviewer_id, artifact.reviewer_approved_at = 99, datetime.now(timezone.utc)
    pack.status = status
    db.commit()
    return pack


def _approve(db, pack, actor=APPROVER):
    from app.modules.payroll import service

    return service.set_jurisdiction_pack_approver(db, pack.id, actor_id=actor)


def test_an_empty_draft_pack_can_no_longer_reach_approved(db):
    """The browser-pass finding: before this gate, one Approve click moved the
    empty MX Draft pack straight to Approved."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import JurisdictionPack, TaxConfigurationAudit
    from scripts.seed_mexico_canonical_packs import load_manifest, seed_mexico

    out = seed_mexico(db, manifest=load_manifest())
    db.commit()
    for pack in (out["national"], out["isn"]["CDMX"]):
        with pytest.raises(BadRequestException, match="move it through In Review to QA first"):
            _approve(db, pack)
        row = db.get(JurisdictionPack, pack.id)
        assert (row.status, row.approved_by_id) == ("Draft", None)
    refusals = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.action == "refused").count()
    assert refusals == 2                                            # each refusal is audited


def test_a_draft_pack_is_refused_even_with_exact_content(db, monkeypatch):
    from app.core.exceptions import BadRequestException

    pack = _seed_ready(db, monkeypatch, "Draft")
    with pytest.raises(BadRequestException, match="is Draft"):
        _approve(db, pack)
    assert pack.status == "Draft"


def test_a_qa_pack_with_empty_content_is_refused_by_gate_1(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.engine.countries import mexico_content as c
    from scripts.seed_mexico_canonical_packs import seed_mexico

    for table in ("MX_SCALAR_CONTENT", "MX_ISR_TARIFFS", "MX_MIN_WAGES", "MX_ZLFN_MUNICIPALITIES", "MX_CEAV_SCHEDULE",
                  "MX_WORKWEEK", "MX_VACATION_DAYS"):          # empty content (Batches 1-2 filled the real one)
        monkeypatch.setattr(c, table, ())
    pack = seed_mexico(db, manifest={})["national"]
    pack.status = "QA"
    db.commit()
    with pytest.raises(BadRequestException, match="awaiting transcription"):
        _approve(db, pack)
    assert pack.approved_by_id is None


def test_a_qa_pack_with_an_unlinked_row_is_refused_by_gate_2(db, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import ContributionRate

    pack = _seed_ready(db, monkeypatch, "QA")
    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id).first().source_document_id = None
    db.commit()
    with pytest.raises(BadRequestException, match="has no source_document_id"):
        _approve(db, pack)


def test_a_qa_pack_with_exact_linked_content_is_approved_without_auto_advance(db, monkeypatch):
    pack = _seed_ready(db, monkeypatch, "QA")
    row = _approve(db, pack)
    assert (row.status, row.approved_by_id) == ("QA", APPROVER)  # QA -> Approved stays an explicit transition


def test_the_approval_hook_is_declared_for_mexico_only():
    import inspect

    from app.modules.payroll import jurisdiction_hooks, mexico_service

    assert jurisdiction_hooks.declares("MX", "pack_approval_refusal")
    for country in ("HK", "SA", "NL", "US", "SG", "ZZ"):
        assert not jurisdiction_hooks.declares(country, "pack_approval_refusal"), country
    params = inspect.signature(mexico_service.mx_pack_approval_refusal).parameters
    assert "actor_id" in params and not any(p.kind is p.VAR_KEYWORD for p in params.values())   # no **kwargs


def test_oos5_other_countries_keep_the_draft_to_approved_auto_advance(db):
    """PINNED CURRENT BEHAVIOUR — OUT_OF_SCOPE_DEFECTS.md OOS-5, not changed on
    this branch. For every non-Mexico country, set_jurisdiction_pack_approver
    still auto-advances a Draft tax pack straight to Approved, bypassing the
    Draft -> In Review -> QA -> Approved transition graph even for opted-in
    countries. Shown on the Netherlands (opted in to the transition graph).
    When OOS-5 is fixed, this test must change with it."""
    from app.modules.payroll import service
    from app.modules.payroll.models import JurisdictionPack
    from scripts.seed_netherlands_canonical_packs import MAIN_PACK_ID, seed_netherlands

    assert "NL" in service._PACK_TRANSITION_GRAPH_COUNTRIES
    seed_netherlands(db)
    db.commit()
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == MAIN_PACK_ID).one()
    assert pack.status == "Draft"
    row = _approve(db, pack)
    assert (row.status, row.approved_by_id) == ("Approved", APPROVER)


def test_a_qa_pack_with_batch1_content_is_still_refused(db):
    """Today's real national pack (Batch 1: ISR, UMA, subsidy, on archive
    copies) cannot be approved: the required text rules are not transcribed
    and no cited source is VERIFIED."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_service
    from scripts.seed_mexico_canonical_packs import load_manifest, seed_mexico

    pack = seed_mexico(db, manifest=load_manifest())["national"]
    pack.status = "QA"
    db.commit()
    checks = {ch["key"]: ch for ch in mexico_service.activation_checks(db, pack, actor_id=APPROVER)}
    assert checks["evidence"]["met"] is True                       # every Batch 1 row links its hashed source
    assert checks["content"]["met"] is False and checks["sources_verified"]["met"] is False
    with pytest.raises(BadRequestException, match="approval is refused"):
        _approve(db, pack)
    assert pack.approved_by_id is None
