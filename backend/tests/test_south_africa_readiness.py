"""South Africa release gates G0-G7 (ZP-ZA-ENG-001 §13-§14; Phase 10). Gate state
comes only from uploaded evidence reviewed by a second Super Admin; nothing in
code signs a gate. AVAILABLE is refused while any gate, launch-blocking decision
or non-informational code check is unmet. "ZA" is South Africa."""
from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import south_africa_readiness as readiness
from app.modules.payroll import south_africa_service as svc
from app.modules.payroll.models import SourceArtifact, TestCertificationRun


def _evidence(db, tag, created_by=801, reviewer=802, file_path="evidence/za.pdf", superseded_by=None):
    row = SourceArtifact(agency="Zoiko (SYNTHETIC)", title=f"{tag} evidence", form_number=tag,
                         created_by_id=created_by, reviewer_id=reviewer, file_path=file_path,
                         superseded_by_id=superseded_by)
    db.add(row)
    db.flush()
    return row


def _states(db):
    return {g["gate"]: g["state"] for g in readiness.gate_states(db)}


# ── gates ───────────────────────────────────────────────────────────────────
def test_the_gates_are_g0_to_g7_and_all_open_today(db):
    states = _states(db)
    assert list(states) == ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert set(states.values()) == {"OPEN"}
    summary = svc.statutory_summary(db)
    assert summary["signedGates"] == 0 and "G0–G7" in summary["note"] and "G8" not in str(summary["gates"])


@pytest.mark.parametrize("kw, state", [
    ({"reviewer": None}, "SUBMITTED"),                       # uploaded, not reviewed
    ({"reviewer": 801}, "SUBMITTED"),                        # self-reviewed
    ({"file_path": None}, "SUBMITTED"),                      # no file
    ({}, "SIGNED"),                                          # reviewed by someone else
])
def test_a_gate_is_signed_only_by_evidence_reviewed_by_another_person(db, kw, state):
    _evidence(db, "ZA-GATE-G1", **kw)
    assert _states(db)["G1"] == state


def test_superseded_evidence_does_not_count(db):
    newer = _evidence(db, "ZA-GATE-G2", reviewer=None)
    _evidence(db, "ZA-GATE-G2", superseded_by=newer.id)
    assert _states(db)["G2"] == "SUBMITTED"


def test_decisions_d1_to_d7_block_launch(db):
    decisions = {d["key"]: d for d in svc.owner_decisions(db)}
    assert list(decisions) == ["D-1", "D-2", "D-3", "D-4", "D-5", "D-6", "D-7"]
    assert all(d["blocksLaunch"] and d["state"] == "OPEN" for d in decisions.values())
    _evidence(db, "ZA-DECISION-D-4")
    assert {d["key"]: d["state"] for d in svc.owner_decisions(db)}["D-4"] == "RECORDED"


# ── code checks ─────────────────────────────────────────────────────────────
def test_code_checks_report_todays_gaps_precisely(db):
    checks = readiness.code_checks(db)
    assert set(checks) == set(readiness.CODE_CHECKS)
    unmet = {k for k, (met, _d) in checks.items() if not met}
    assert {"pack_seeded", "pack_no_pending_g1", "content_no_pending_g1", "empty_by_design_resolved",
            "earning_class_no_review", "brs_catalog_present", "golden_pass", "bank_connector",
            "parallel_cycles"} <= unmet
    assert checks["unsupported_blocked"][0] is True and checks["holiday_calendar"][0] is True
    assert "seed_south_africa_canonical_packs" in checks["pack_seeded"][1]
    assert "za_parallel_materiality_amount" in checks["empty_by_design_resolved"][1]
    assert "REVIEW" in checks["earning_class_no_review"][1]
    assert "source-code catalogue is empty" in checks["brs_catalog_present"][1]
    assert all(detail and detail.strip() for _met, detail in checks.values())


def test_empty_by_design_is_met_by_a_recorded_d6(db):
    _evidence(db, "ZA-DECISION-D-6")
    met, detail = readiness.code_checks(db)["empty_by_design_resolved"]
    assert met and "D-6 is RECORDED" in detail


def test_golden_pass_needs_a_pass_covering_every_fixture(db):
    from pathlib import Path

    fixtures = len([p for p in (Path(__file__).parent / "fixtures" / "za_golden").glob("*.json")
                    if not p.name.startswith("_")])
    db.add(TestCertificationRun(jurisdiction_country="ZA", status="PASS", total_cases=fixtures - 1,
                                real_case_count=fixtures - 1, passed_cases=fixtures - 1, failed_cases=0))
    db.flush()
    met, detail = readiness.code_checks(db)["golden_pass"]
    assert not met and "re-run the certification" in detail
    db.add(TestCertificationRun(jurisdiction_country="ZA", status="PASS", total_cases=fixtures,
                                real_case_count=fixtures, passed_cases=fixtures, failed_cases=0))
    db.flush()
    assert readiness.code_checks(db)["golden_pass"][0] is True


def test_the_golden_certification_console_satisfies_golden_pass(db):
    svc_mod = __import__("app.modules.payroll.service", fromlist=["run_golden_test_certification"])
    svc_mod.run_golden_test_certification(db, jurisdiction_country="ZA", actor_id=203)
    assert readiness.code_checks(db)["golden_pass"][0] is True


def test_journal_accounts_check_counts_active_registrations_with_a_map(db, organization):
    from app.modules.payroll.models import PayrollZaEmployerRegistration

    db.add(PayrollZaEmployerRegistration(organization_id=organization.id, effective_from=date(2026, 3, 1),
                                         paye_reference="7000000000", sdl_liable=True, eti_registered=False,
                                         status="ACTIVE"))
    db.flush()
    met, detail = readiness.code_checks(db)["journal_accounts_configured"]
    assert not met and detail.startswith("0 of 1")


def test_informational_checks_never_block_general_availability(db):
    keys = {p["key"] for p in readiness.ga_preconditions(db)}
    for key, (_gates, informational) in readiness.CODE_CHECKS.items():
        assert (f"code_{key}" in keys) is (not informational), key
    assert {f"gate_G{i}" for i in range(8)} <= keys
    assert {f"decision_D-{i}" for i in range(1, 8)} <= keys


# ── checklists ──────────────────────────────────────────────────────────────
def test_every_gate_checklist_parses_and_every_code_tag_resolves(db):
    out = readiness.gate_checklists(db)
    assert [g["gate"] for g in out["gates"]] == [f"G{i}" for i in range(8)]
    for gate in out["gates"]:
        assert gate["available"], gate["gate"]
        assert gate["items"], gate["gate"]
        for item in gate["items"]:
            if item["kind"] == "code":
                assert item["code"] in readiness.CODE_CHECKS, item["code"]
                assert not item["detail"].startswith("unknown code check")
            else:
                assert item["met"] is False and "awaits" in item["detail"]


def test_the_release_gate_documents_exist():
    assert (readiness.RELEASE_GATES_DIR / "README.md").is_file()
    for i in range(8):
        assert (readiness.RELEASE_GATES_DIR / f"G{i}" / "CHECKLIST.md").is_file()


# ── the registry step ───────────────────────────────────────────────────────
def _registry(db):
    from app.modules.billing.models import JurisdictionServiceRegistry

    db.add(JurisdictionServiceRegistry(country="ZA", availability="PLANNED"))
    db.commit()


def test_available_is_refused_and_names_what_is_unmet(db):
    _registry(db)
    with pytest.raises(BadRequestException) as exc:
        svc.transition_za_service_registry(db, "AVAILABLE", "SYNTHETIC", actor_id=802)
    detail = str(exc.value)
    assert "ZA-GATE-G1 is OPEN" in detail and "ZA-DECISION-D-4 is OPEN" in detail
    assert "bank connector" in detail


def test_available_is_allowed_only_when_everything_is_met(db, monkeypatch):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import south_africa_dormancy

    _registry(db)
    for i in range(8):
        _evidence(db, f"ZA-GATE-G{i}")
    for i in range(1, 8):
        _evidence(db, f"ZA-DECISION-D-{i}")
    db.commit()
    with pytest.raises(BadRequestException, match="bank connector"):         # code checks still unmet
        svc.transition_za_service_registry(db, "AVAILABLE", "SYNTHETIC", actor_id=802)
    real = readiness.code_checks
    monkeypatch.setattr(readiness, "code_checks",
                        lambda d: {k: (True, "SYNTHETIC") for k in real(d)})
    svc.transition_za_service_registry(db, "AVAILABLE", "SYNTHETIC: every gate signed", actor_id=802)
    row = db.query(JurisdictionServiceRegistry).filter_by(country="ZA").one()
    assert row.availability == "AVAILABLE"
    assert south_africa_dormancy.onboarding_enabled() is False            # the deployment flag is untouched


def test_summary_carries_the_readiness_view(db):
    out = svc.statutory_summary(db)
    for key in ("gates", "signedGates", "gateChecklists", "gaPreconditions", "codeChecks", "noGo", "openPoints",
                "documents"):
        assert key in out, key
    assert len(out["noGo"]) == 10 and out["available"] is False
    assert {r["key"] for r in out["codeChecks"]} == set(readiness.CODE_CHECKS)
