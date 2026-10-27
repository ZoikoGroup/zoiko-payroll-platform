"""Mexico (ZP-MX-ENG-001) Phase 2 activation gates — each gate refuses on
its own, the real seeded pack is refused today, a pack satisfying every gate
CAN be activated through the governed path, [PENDING G2] is a warning (never
a block), the hotfix path runs the same gates, and the governance opt-in
tuples changed by exactly "MX".

Every content row and source here is SYNTHETIC test data (values like 1),
inserted by monkeypatching mexico_content — never a statutory figure."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

APPROVER, REVIEWER, ACTIVATOR = 7, 8, 9


def _c():
    from app.modules.payroll.engine.countries import mexico_content

    return mexico_content


def _synthetic_national_content(monkeypatch, *, with_g2=False):
    """One row per required national key and 11 contiguous brackets per ISR
    period — the exact shape gate 1b-1 demands. SYNTHETIC values."""
    c = _c()
    rows = []
    for key, (kind, _label, scope) in c.MX_PARAMETER_KEYS.items():
        if scope != "national" or (kind == "text" and not with_g2 and key not in c.MX_REQUIRED_TEXT_KEYS):
            continue
        rows.append(c.ScalarRow(
            key, "1" if kind == "employee_pct" else None, "1" if kind == "employer_pct" else None,
            "1" if kind == "amount" else None, "SYNTHETIC" if kind == "text" else None, None, None, "S6",
            "SYNTHETIC", pending_g2=key in c.MX_PENDING_G2_KEYS))
    brackets = []
    for period in c.MX_ISR_PERIODS:
        for i in range(11):
            lower = Decimal(i * 100) + Decimal("0.01")
            upper = None if i == 10 else Decimal((i + 1) * 100)
            brackets.append(c.IsrBracket(period, str(lower), None if upper is None else str(upper), str(i),
                                         str(i + 1), None, None, "S2", "SYNTHETIC"))
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", tuple(rows))
    monkeypatch.setattr(c, "MX_ISR_TARIFFS", tuple(brackets))
    for table in ("MX_MIN_WAGES", "MX_ZLFN_MUNICIPALITIES", "MX_CEAV_SCHEDULE", "MX_WORKWEEK", "MX_VACATION_DAYS"):
        monkeypatch.setattr(c, table, ())                       # SYNTHETIC packs carry only the rows above
    monkeypatch.setattr(c, "MX_ISN_CONTENT", {state: () for state in c.MX_ISN_CONTENT})   # W1-2 filled CDMX


def _manifest():
    def row(code, sha):
        return {"code": code, "title": f"SYNTHETIC {code}", "issuer": "Test", "url": f"https://example.test/{code}",
                "file": f"{code}_synthetic.pdf", "sha256": sha, "bytes": "1", "retrieved_at": "2026-10-15T00:00:00Z",
                "content_type": "application/pdf", "header_version": "t", "text_layer": "yes", "status": "VERIFIED",
                "note": ""}
    return {"S2": row("S2", "a" * 64), "S6": row("S6", "b" * 64)}


def _write_log(manifest_path, rows):
    """A MATCH verification-log entry for every VERIFIED row (what
    verify_mexico_sources.py writes after a direct download)."""
    import csv

    from app.modules.payroll import mexico_sources

    with open(mexico_sources.log_path(manifest_path), "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=mexico_sources.LOG_COLUMNS)
        writer.writeheader()
        for r in rows:
            if r["status"] == "VERIFIED":
                writer.writerow({"code": r["code"], "file": r["file"], "url": r["url"], "final_url": r["url"],
                                 "downloaded_at": "2026-10-26T00:00:00Z", "downloader": "test@example.com",
                                 "response_bytes": r.get("bytes") or "1", "sha256": r["sha256"], "result": "MATCH"})


def _write_manifest(path, rows, log=True):
    import csv

    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(next(iter(rows))))
        writer.writeheader()
        writer.writerows(rows)
    if log:
        _write_log(path, rows)


@pytest.fixture()
def ready_pack(db, monkeypatch, tmp_path):
    """An MX national pack satisfying EVERY activation gate (test-only):
    synthetic exact content, hashed sources reviewed by REVIEWER, Approved by
    APPROVER, a PASS certification run and a passing pack-bound golden check."""
    from app.modules.payroll import mexico_service
    from app.modules.payroll.models import SourceArtifact, TestCertificationRun
    from scripts.seed_mexico_canonical_packs import seed_mexico

    from app.modules.payroll import mexico_sources

    _synthetic_national_content(monkeypatch)
    manifest_path = tmp_path / "SOURCES_MANIFEST.csv"           # Phase 11d: the gate reads the manifest file
    _write_manifest(manifest_path, list(_manifest().values()))
    monkeypatch.setattr(mexico_sources, "MANIFEST_PATH", manifest_path)
    pack = seed_mexico(db, manifest=_manifest())["national"]
    for artifact in db.query(SourceArtifact).all():
        artifact.reviewer_id, artifact.reviewer_approved_at = REVIEWER, datetime.now(timezone.utc)
    pack.status, pack.approved_by_id = "Approved", APPROVER
    db.add(TestCertificationRun(jurisdiction_country="MX", status="PASS", real_case_count=1, total_cases=1,
                                passed_cases=1, failed_cases=0))
    db.commit()
    monkeypatch.setattr(mexico_service, "pack_golden_check",
                        lambda db, pack: {"casesInWindow": 1, "passed": 1, "failures": []})
    return pack


def _refusal(db, pack, actor=ACTIVATOR):
    from app.modules.payroll import mexico_service

    return mexico_service.mx_activation_evidence_refusal(db, pack, actor_id=actor)


def test_a_pack_meeting_every_gate_is_accepted_by_the_mexico_hook(db, ready_pack):
    from app.modules.payroll import mexico_service

    assert _refusal(db, ready_pack) is None
    view = mexico_service.activation_readiness(db, ready_pack.id, actor_id=ACTIVATOR)
    assert view["activatable"] and all(c["met"] for c in view["checks"]) and view["warnings"] == []


def test_the_governed_path_activates_it_with_four_eyes(db, ready_pack):
    from app.modules.payroll import service

    service.set_jurisdiction_pack_status(db, ready_pack.id, "Active", actor_id=ACTIVATOR)
    assert ready_pack.status == "Active"


def test_the_approver_cannot_activate(db, ready_pack):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, ready_pack.id, "Active", actor_id=APPROVER)


# ── each gate refuses on its own ────────────────────────────────────────────

def test_gate_content_refuses_a_missing_row(db, ready_pack):
    from app.modules.payroll.models import ContributionRate

    db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == ready_pack.id,
                                      ContributionRate.component_key == "mx_imss_iv_er_pct").delete()
    db.commit()
    assert "1 expected row(s) missing" in _refusal(db, ready_pack)


def test_gate_content_refuses_an_extra_row(db, ready_pack):
    from app.modules.payroll.models import TaxSlab

    db.add(TaxSlab(jurisdiction_pack_id=ready_pack.id, jurisdiction_country="MX", organization_id=None,
                   rule_type="MX_ISR_TARIFF", filing_status="MONTHLY", min_amount=Decimal("5000"), max_amount=None,
                   rate_pct=Decimal("9"), flat_amount=Decimal("0"), rate_label="SYNTHETIC", tax_formula="x"))
    db.commit()
    assert "1 unexpected row(s) present" in _refusal(db, ready_pack)


def test_gate_content_requires_eleven_brackets_per_period(db, monkeypatch, ready_pack):
    c = _c()
    monkeypatch.setattr(c, "MX_ISR_TARIFFS", tuple(b for b in c.MX_ISR_TARIFFS
                                                   if not (b.period == "DAILY" and b.lower == "0.01")))
    assert "exactly 11 brackets for DAILY" in _refusal(db, ready_pack)


def test_gate_content_refuses_empty_content(db, monkeypatch, ready_pack):
    monkeypatch.setattr(_c(), "MX_SCALAR_CONTENT", ())
    monkeypatch.setattr(_c(), "MX_ISR_TARIFFS", ())
    assert "awaiting transcription" in _refusal(db, ready_pack)


def test_gate_evidence_refuses_an_unlinked_row(db, ready_pack):
    from app.modules.payroll.models import ContributionRate

    row = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == ready_pack.id).first()
    row.source_document_id = None
    db.commit()
    assert "has no source_document_id" in _refusal(db, ready_pack)


def test_gate_evidence_refuses_an_artifact_without_its_saved_file(db, ready_pack):
    from app.modules.payroll.models import SourceArtifact

    db.query(SourceArtifact).first().file_path = None
    db.commit()
    assert "lack a URL, SHA-256 or saved file" in _refusal(db, ready_pack)


def test_gate_g1_refuses_an_unreviewed_source(db, ready_pack):
    from app.modules.payroll.models import SourceArtifact

    db.query(SourceArtifact).first().reviewer_approved_at = None
    db.commit()
    assert "G1 human review is missing" in _refusal(db, ready_pack)


def test_gate_g1_refuses_when_the_reviewer_is_the_activator(db, ready_pack):
    assert "may not be the activator" in _refusal(db, ready_pack, actor=REVIEWER)


def test_gate_golden_refuses_without_a_vector_in_the_window(db, monkeypatch, ready_pack):
    from app.modules.payroll import mexico_service

    monkeypatch.setattr(mexico_service, "pack_golden_check",
                        lambda db, pack: {"casesInWindow": 0, "passed": 0, "failures": []})
    assert "no Mexico golden vector falls inside" in _refusal(db, ready_pack)


def test_gate_golden_refuses_a_failing_vector(db, monkeypatch, ready_pack):
    from app.modules.payroll import mexico_service

    monkeypatch.setattr(mexico_service, "pack_golden_check",
                        lambda db, pack: {"casesInWindow": 2, "passed": 1, "failures": [{"case": "F1", "error": "x"}]})
    assert "do not reproduce 1 of 2 golden vector(s): F1" in _refusal(db, ready_pack)


def test_the_real_golden_directory_has_no_cases_so_the_real_check_refuses(db, ready_pack):
    from app.modules.payroll import service

    real = service.run_pack_golden_vectors(db, ready_pack, "mx_golden", lambda context, pay: {})
    assert real == {"casesInWindow": 0, "passed": 0, "failures": []}


# ── G2 is a warning, never a block (Q2 b dropped) ──────────────────────────

def test_pending_g2_parameter_is_a_warning_not_a_block(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_service, mexico_sources
    from app.modules.payroll.models import SourceArtifact, TestCertificationRun
    from scripts.seed_mexico_canonical_packs import seed_mexico

    _synthetic_national_content(monkeypatch, with_g2=True)
    _write_manifest(tmp_path / "m.csv", list(_manifest().values()))
    monkeypatch.setattr(mexico_sources, "MANIFEST_PATH", tmp_path / "m.csv")
    pack = seed_mexico(db, manifest=_manifest())["national"]
    for artifact in db.query(SourceArtifact).all():
        artifact.reviewer_id, artifact.reviewer_approved_at = REVIEWER, datetime.now(timezone.utc)
    db.commit()
    monkeypatch.setattr(mexico_service, "pack_golden_check",
                        lambda db, pack: {"casesInWindow": 1, "passed": 1, "failures": []})
    view = mexico_service.activation_readiness(db, pack.id, actor_id=ACTIVATOR)
    assert view["activatable"] is True
    assert [w["key"] for w in view["warnings"]] == ["pending_g2"]
    assert "ZLFN" in view["warnings"][0]["detail"]


# ── today's real packs, and the hotfix path ─────────────────────────────────

def test_the_real_seeded_packs_are_refused_today(db):
    from app.modules.payroll import mexico_service
    from app.modules.payroll.models import ContributionRate, TaxSlab
    from scripts.seed_mexico_canonical_packs import load_manifest, seed_mexico

    out = seed_mexico(db, manifest=load_manifest())                 # Batch 1 content, real manifest
    national, cdmx = out["national"], out["isn"]["CDMX"]
    expected_rows = _c().expected_national_signatures(national.effective_from, national.effective_to)
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == national.id).count()
    rates = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == national.id).count()
    assert (slabs, rates) == (sum(s[0] == "SLAB" for s in expected_rows), sum(s[0] == "RATE" for s in expected_rows))
    assert slabs > 55 and rates > 10                                  # Batch 2 rows are seeded too
    assert db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == cdmx.id).count() == 1
    expected = {national.id: {"content": False, "evidence": True, "sources_verified": False, "g1_review": False,
                              "golden": False},
                # W1-2: the CDMX rate rests on S22, VERIFIED by a logged direct download, so content,
                # evidence and sources pass; the human G1 review and the golden vectors still refuse it
                cdmx.id: {"content": True, "evidence": True, "sources_verified": True, "g1_review": False,
                          "golden": False}}
    for pack in (national, cdmx):
        view = mexico_service.activation_readiness(db, pack.id, actor_id=ACTIVATOR)
        assert view["activatable"] is False
        assert {c["key"]: c["met"] for c in view["checks"]} == expected[pack.id]
        assert _refusal(db, pack).startswith("Mexico pack activation is refused")
    # Batch 1 rests on archive copies: activation needs each one VERIFIED
    checks = {c["key"]: c for c in mexico_service.activation_checks(db, national, actor_id=ACTIVATOR)}
    assert "not VERIFIED" in checks["sources_verified"]["detail"]


def test_the_hotfix_path_runs_the_same_mexico_gates(db, monkeypatch, ready_pack):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import mexico_service, service

    monkeypatch.setattr(mexico_service, "pack_golden_check",
                        lambda db, pack: {"casesInWindow": 0, "passed": 0, "failures": []})
    ready_pack.status = "Approved"
    db.commit()
    with pytest.raises(BadRequestException, match="golden vector"):
        service.activate_jurisdiction_pack_hotfix(db, ready_pack.id, "INC-1", "test", actor_id=ACTIVATOR)
    assert ready_pack.status == "Approved"


def test_actor_reaches_only_hooks_that_declare_it(db, monkeypatch):
    """The shared call site passes actor_id only to a hook whose signature
    declares it; HK / SA / NL hooks keep their exact (db, pack) call."""
    import inspect

    from app.modules.payroll import hong_kong_service, mexico_service, netherlands_service, saudi_arabia_service

    assert "actor_id" in inspect.signature(mexico_service.mx_activation_evidence_refusal).parameters
    for module in (hong_kong_service, netherlands_service, saudi_arabia_service):
        name = module.JURISDICTION_HOOKS["pack_activation_refusal"]
        assert "actor_id" not in inspect.signature(getattr(module, name)).parameters, module.__name__


# ── governance tuples: exactly + "MX" ───────────────────────────────────────

_BEFORE = ("SG", "SE", "HK", "CH", "SA", "NL")


def test_governance_opt_in_tuples_gain_only_mexico():
    from app.modules.payroll import service

    for name in ("_APPROVER_NOT_ACTIVATOR_COUNTRIES", "_SELF_APPROVAL_REFUSED_COUNTRIES",
                 "_REFUSAL_AUDIT_COUNTRIES", "_PACK_TRANSITION_GRAPH_COUNTRIES"):
        # + Brazil (ZP-BR-ENG-001) at the venu/main merge and + South Africa
        # (ZP-ZA-ENG-001 Phase 5), all opt-in with the same four-eyes/fail-closed rules.
        assert getattr(service, name) == _BEFORE + ("MX", "BR", "ZA"), name
    assert service._GATED_PACK_COUNTRY_NAMES["MX"] == "Mexico"
    assert set(service._GATED_PACK_COUNTRY_NAMES) == {
        "US", "DE", "SG", "SE", "HK", "CH", "SA", "NL", "MX", "BR", "ZA"}
    assert service._GOLDEN_FIXTURES_DIR_BY_COUNTRY["MX"] == "mx_golden"
    assert len(service._GOLDEN_FIXTURES_DIR_BY_COUNTRY) == 14
    assert service._CANONICAL_PACK_ONLY_COUNTRIES == ("SG", "HK", "SA", "NL", "MX", "BR", "ZA")


# -- Phase 11d (gap register A9): archive copies feed Draft packs only --

def test_gate_sources_verified_refuses_an_archive_copy_at_activation_and_approval(db, monkeypatch, tmp_path,
                                                                                  ready_pack):
    from app.modules.payroll import mexico_service, mexico_sources

    rows = list(_manifest().values())
    rows[0] = {**rows[0], "status": "ARCHIVE_COPY_VERIFIED"}                 # an Internet Archive capture
    path = tmp_path / "archive.csv"
    _write_manifest(path, rows)
    monkeypatch.setattr(mexico_sources, "MANIFEST_PATH", path)
    refusal = _refusal(db, ready_pack)
    assert refusal and "not VERIFIED" in refusal
    ready_pack.status = "QA"
    approval = mexico_service.mx_pack_approval_refusal(db, ready_pack, actor_id=APPROVER)
    assert approval and "not VERIFIED" in approval


def test_gate_sources_verified_refuses_when_the_manifest_cannot_be_read(db, monkeypatch, tmp_path, ready_pack):
    from app.modules.payroll import mexico_service, mexico_sources

    monkeypatch.setattr(mexico_sources, "MANIFEST_PATH", tmp_path / "missing.csv")
    checks = {c["key"]: c for c in mexico_service.activation_checks(db, ready_pack, actor_id=ACTIVATOR)}
    assert checks["sources_verified"]["met"] is False and "cannot be read" in checks["sources_verified"]["detail"]
    assert "cannot be read" in _refusal(db, ready_pack)


def test_gate_sources_verified_refuses_a_verified_row_without_a_log_entry(db, monkeypatch, tmp_path, ready_pack):
    """VERIFIED is real only with its MATCH entry in VERIFICATION_LOG.csv — a
    row marked VERIFIED by hand fails the check (and approval)."""
    from app.modules.payroll import mexico_service, mexico_sources

    unlogged = tmp_path / "unlogged"
    unlogged.mkdir()
    _write_manifest(unlogged / "SOURCES_MANIFEST.csv", list(_manifest().values()), log=False)
    monkeypatch.setattr(mexico_sources, "MANIFEST_PATH", unlogged / "SOURCES_MANIFEST.csv")
    checks = {c["key"]: c for c in mexico_service.activation_checks(db, ready_pack, actor_id=ACTIVATOR)}
    assert checks["sources_verified"]["met"] is False
    assert "VERIFICATION_LOG.csv" in checks["sources_verified"]["detail"]
    ready_pack.status = "QA"
    assert "not VERIFIED" in mexico_service.mx_pack_approval_refusal(db, ready_pack, actor_id=APPROVER)
    # a MISMATCH entry, or one for a different hash, does not count either
    rows = list(_manifest().values())
    _write_log(unlogged / "SOURCES_MANIFEST.csv", [{**r, "sha256": "f" * 64} for r in rows])
    assert mexico_service.mx_activation_evidence_refusal(db, ready_pack, actor_id=ACTIVATOR)
    _write_log(unlogged / "SOURCES_MANIFEST.csv", rows)                      # the matching entries: met
    checks = {c["key"]: c for c in mexico_service.activation_checks(db, ready_pack, actor_id=ACTIVATOR)}
    assert checks["sources_verified"]["met"] is True
