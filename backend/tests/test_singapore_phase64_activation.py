"""
tests/test_singapore_phase64_activation.py
------------------------------------------
Singapore Phase 6.4 — gaps found by the controlled activation rehearsal
(throwaway PostgreSQL, integration head 6247da96d605).

  - Template metadata: the three Phase 4/5 Singapore templates (IR8A, SDL
    monthly, CPF EZPay) were seeded with no description, regulatory
    authority or source reference. Every one of the 11 now carries the
    catalogue's "[classification] description", its authority, and a source
    reference; the three cite the official source artifact the canonical
    pack registers, with its SHA-256.
  - Activation gate: a Singapore pack cannot go Active while the latest SG
    golden-vector run is FAIL, and can after a later PASS run (maker-checker
    unchanged: B approves, A activates). The FAIL is produced by the real
    run_golden_test_certification with one injected harness mismatch — no
    fixture file is touched. "Latest run" breaks a run_at tie by id (found by
    this test in the full suite: two runs in the same SQLite second tied, and
    the gate read the older FAIL after a newer PASS).

app.* imports are lazy (tests/_db_safety.py). No regulator certification is
represented anywhere: a golden PASS is internal engineering evidence only.
"""

from datetime import date

import pytest

A, B = 101, 202          # two distinct Super Admin actors


def _seed_templates(db, monkeypatch):
    import scripts.seed_statutory_report_templates as seed

    monkeypatch.setattr(seed, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed.run()


def test_every_seeded_singapore_template_carries_catalogue_metadata_and_a_source(db, monkeypatch):
    from app.modules.payroll.engine.jurisdictions.singapore.statutory_summary import (
        SG_REPORT_TEMPLATES, template_catalog_entry)
    from app.modules.payroll.models import ReportTemplate
    from scripts.seed_singapore_canonical_pack import SOURCES

    _seed_templates(db, monkeypatch)
    rows = {t.template_key: t for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG")}
    assert sorted(rows) == sorted(t[0] for t in SG_REPORT_TEMPLATES) and len(rows) == 11
    for key, row in rows.items():
        entry = template_catalog_entry(key)
        assert row.status == "Draft", key
        assert row.description == f"[{entry['classification']}] {entry['description']}", key
        assert row.regulatory_authority == entry["regulatoryAuthority"], key
        assert row.source_references, key
        assert row.effective_from == date(2026, 1, 1), key
    for key, source_key in (("SG-IR8A", "iras_ais"), ("SG-SDL-MONTHLY", "cpf_sdl"), ("SG-CPF-EZPAY", "cpf_ezpay_ftp_spec")):
        publisher, title, url, sha256 = SOURCES[source_key][:4]
        ref = rows[key].source_references
        assert publisher in ref and url in ref and sha256 in ref, key          # traceable to the registered artifact
        assert "no official form layout is certified" in ref, key               # never presented as certified


def test_reseeding_keeps_the_metadata_and_never_touches_a_promoted_template(db, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate

    _seed_templates(db, monkeypatch)
    ir8a = db.query(ReportTemplate).filter(ReportTemplate.template_key == "SG-IR8A").one()
    service.set_report_template_approver(db, ir8a.id, actor_id=B)                 # Draft -> Approved
    before = {t.template_key: (t.id, t.status, t.description, t.source_references)
              for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG")}
    _seed_templates(db, monkeypatch)
    db.expire_all()
    after = {t.template_key: (t.id, t.status, t.description, t.source_references)
             for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG")}
    assert after == before
    assert after["SG-IR8A"][1] == "Approved"


def test_sg_activation_is_refused_while_the_latest_golden_run_fails_and_allowed_after_a_pass(db, monkeypatch):
    import app.modules.payroll.hmrc_golden_harness as harness
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    real = harness.run_golden_case
    seen = {"n": 0}

    def one_mismatch(case):
        seen["n"] += 1
        if seen["n"] == 1:
            raise harness.GoldenCaseMismatch("injected", [{"field": "employee_pension", "expected": "1", "actual": "2"}])
        return real(case)

    monkeypatch.setattr(harness, "run_golden_case", one_mismatch)
    failing = service.run_golden_test_certification(db, "SG", actor_id=A)
    assert (failing.status, failing.failed_cases, failing.passed_cases) == ("FAIL", 1, failing.total_cases - 1)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=B)
    with pytest.raises(BadRequestException, match="unresolved failure"):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A)
    db.refresh(pack)
    assert pack.status == "Approved"

    monkeypatch.setattr(harness, "run_golden_case", real)
    passing = service.run_golden_test_certification(db, "SG", actor_id=A)
    assert passing.status == "PASS" and passing.passed_cases == passing.total_cases == 36
    # run_at is server-side now() (whole seconds on SQLite): force the tie, so
    # the newer run (higher id) must win for both the gate and the readiness view.
    passing.run_at = failing.run_at
    db.commit()
    assert service.list_test_certification_runs(db, limit=1, jurisdiction_country="SG")[0].id == passing.id
    with pytest.raises(BadRequestException, match="cannot also activate"):          # F2 still holds
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=B)
    assert service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=A).status == "Active"
