"""
tests/test_platform_shared_helper_snapshots.py
----------------------------------------------
Behaviour snapshots taken BEFORE the Hong Kong architecture convergence
(2026-10-05) moved the Singapore / Hong Kong copies of platform logic into
shared, country-parameterised helpers: service-registry transition (refusals
and their audit rows), evidence gate state, pack golden check, activation
evidence refusal, statutory summary, calculation preview and the four-eyes
refusal. Each case renders the function's observable output (return value,
raised message, audit rows written) to normalised JSON and compares it with
tests/fixtures/platform_shared_helper_snapshots.json — any byte difference
fails. Record (once, before the refactor): PLATFORM_SNAPSHOT_RECORD=1.

app.* imports are lazy (tests/_db_safety.py).
"""

import json
import os
import re
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "platform_shared_helper_snapshots.json"
AS_OF = date(2026, 10, 1)
A, B = 101, 202
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _norm(value):
    """JSON-safe, deterministic: timestamps -> "<ts>", Decimals/dates -> str."""
    if isinstance(value, dict):
        return {str(k): ("<ts>" if str(k).lower().endswith(("at", "_at")) and value[k] else _norm(value[k]))
                for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, (D, date)):
        return str(value)
    if isinstance(value, str) and _TS.match(value):
        return "<ts>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _audits(db, since_id):
    from app.modules.payroll.models import TaxConfigurationAudit

    return [{"action": a.action, "entity": a.entity_type, "actor": a.actor_id, "old": a.old_value, "new": a.new_value,
             "reason": a.reason}
            for a in db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.id > since_id)
            .order_by(TaxConfigurationAudit.id)]


def _last_audit_id(db):
    from sqlalchemy import func

    from app.modules.payroll.models import TaxConfigurationAudit

    return db.query(func.coalesce(func.max(TaxConfigurationAudit.id), 0)).scalar()


def _outcome(db, fn):
    """{result | error} plus the audit rows the call wrote."""
    start = _last_audit_id(db)
    try:
        out = {"result": fn()}
    except Exception as exc:                                       # noqa: BLE001
        db.rollback()
        out = {"error": type(exc).__name__, "message": str(getattr(exc, "detail", exc))}
    out["audits"] = _audits(db, start)
    return _norm(out)


def _check(name, observed):
    recorded = json.loads(FIXTURE.read_text(encoding="utf8")) if FIXTURE.is_file() else {}
    if os.environ.get("PLATFORM_SNAPSHOT_RECORD") == "1":
        recorded[name] = observed
        recorded["__recorded_on__"] = date.today().isoformat()
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(recorded, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf8")
        return
    assert name in recorded, f"no recorded snapshot for {name} (record before refactoring)"
    # A summary computed "as of today" carries the run date: the recording day
    # on one side and today on the other is the same point in its own run.
    then, now = recorded.get("__recorded_on__", ""), date.today().isoformat()
    expected = json.dumps(recorded[name], sort_keys=True, ensure_ascii=False)
    actual = json.dumps(observed, sort_keys=True, ensure_ascii=False)
    if then:
        expected = expected.replace(then, "<run-date>")
    assert actual.replace(now, "<run-date>") == expected, name


def _art(db, tag, *, file_path="evidence.pdf", created_by=A, reviewer=None):
    from app.modules.payroll.models import SourceArtifact

    a = SourceArtifact(agency="Zoiko test", title=f"TEST {tag}", form_number=tag, checksum_sha256="0" * 64,
                       file_path=file_path, created_by_id=created_by, reviewer_id=reviewer)
    db.add(a)
    db.commit()
    return a


# ── Singapore ───────────────────────────────────────────────────────────

@pytest.fixture
def sg_pack(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore

    return seed_singapore(db)


def test_sg_registry_transition_refusals(db, sg_pack):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import service

    def go(target, reason="TEST", actor=A):
        return lambda: service.transition_sg_service_registry(db, target, reason, actor_id=actor, as_of=AS_OF)

    cases = {"no_actor": _outcome(db, go("AVAILABLE", actor=None)),
             "bad_target": _outcome(db, go("LIMITED_AVAILABILITY"))}
    if db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "SG").first() is None:
        cases["no_row"] = _outcome(db, go("AVAILABLE"))
        db.add(JurisdictionServiceRegistry(country="SG", availability="PLANNED"))
        db.commit()
    cases.update(no_reason=_outcome(db, go("AVAILABLE", reason="")),
                 already=_outcome(db, go("PLANNED")),
                 unmet=_outcome(db, go("AVAILABLE")))
    _check("sg_registry_transition", cases)


def test_sg_gate_states(db):
    from app.modules.payroll import service

    _art(db, "SG-GATE-G1", reviewer=B)
    _art(db, "SG-GATE-G2", reviewer=None)
    _art(db, "SG-GATE-G3", reviewer=A)
    _art(db, "SG-GATE-G4", file_path=None, reviewer=B)
    _check("sg_gate_state", {g: service._sg_gate_state(db, f"SG-GATE-{g}", AS_OF)
                             for g in ("G1", "G2", "G3", "G4", "G5")})


def test_sg_golden_and_activation_refusal(db, sg_pack):
    from app.modules.payroll import service

    _check("sg_golden_check", _outcome(db, lambda: service.sg_pack_golden_check(db, sg_pack)))
    _check("sg_activation_evidence_refusal", _outcome(db, lambda: service._sg_activation_evidence_refusal(db, sg_pack)))


def test_sg_statutory_summary(db, sg_pack):
    from app.modules.payroll import service

    _check("sg_statutory_summary", _outcome(db, lambda: service.get_sg_statutory_summary(db, AS_OF)))


def test_sg_preview(db, sg_pack):
    from app.modules.payroll import service
    from tests.test_singapore import _preview_data

    _check("sg_preview", _outcome(db, lambda: service.preview_singapore_calculation(db, _preview_data(sg_pack.id))))


def test_sg_four_eyes_refusal(db):
    from app.modules.payroll import service

    _check("sg_four_eyes", _outcome(db, lambda: service._sg_refuse_self_approval(
        db, "sgp_ir21_case", 7, A, "PREPARED", "approve", "TEST self-approval refused")))


# ── Hong Kong ───────────────────────────────────────────────────────────

@pytest.fixture
def hk_draft(db):
    from scripts.seed_hong_kong_canonical_pack import seed_hong_kong_all

    return seed_hong_kong_all(db)


def test_hk_registry_transition_refusals(db, hk_draft):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll import hong_kong_service

    def go(target, reason="TEST", actor=A):
        return lambda: hong_kong_service.transition_hk_service_registry(db, target, reason, actor_id=actor, as_of=AS_OF)

    if db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "HK").first() is None:
        db.add(JurisdictionServiceRegistry(country="HK", availability="PLANNED"))
        db.commit()
    _check("hk_registry_transition", {
        "no_actor": _outcome(db, go("AVAILABLE", actor=None)), "bad_target": _outcome(db, go("LIMITED_AVAILABILITY")),
        "no_reason": _outcome(db, go("AVAILABLE", reason="")), "already": _outcome(db, go("PLANNED")),
        "unmet": _outcome(db, go("AVAILABLE"))})


def test_hk_gate_states_readiness_golden_and_summary(db, hk_draft):
    from app.modules.payroll import hong_kong_service

    _art(db, "HK-GATE-G1", reviewer=B)
    _art(db, "HK-GATE-G2", reviewer=None)
    _art(db, "HK-GATE-G3", reviewer=A)
    _check("hk_gate_state", {g: hong_kong_service.gate_state(db, g) for g in ("G1", "G2", "G3", "G4")})
    p25, p26 = hk_draft
    _check("hk_golden_check", _outcome(db, lambda: hong_kong_service.pack_golden_check(db, p26)))
    _check("hk_activation_evidence_refusal", _outcome(db, lambda: hong_kong_service.hk_activation_evidence_refusal(db, p26)))
    _check("hk_activation_readiness", _outcome(db, lambda: hong_kong_service.activation_readiness(db, AS_OF)))
    _check("hk_statutory_summary", _outcome(db, lambda: hong_kong_service.statutory_summary(db)))


def test_hk_preview(db, hk_draft):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.schemas import HKCalculationPreviewRequest

    _check("hk_preview", _outcome(db, lambda: hong_kong_service.preview_calculation(db, HKCalculationPreviewRequest(
        payDate=date(2026, 6, 30), gross="45000", dateOfBirth=date(1990, 1, 1), dateOfJoining=date(2024, 1, 1)))))
