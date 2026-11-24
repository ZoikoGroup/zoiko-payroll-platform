"""Report-template activation readiness — a pure dry run of the status change.

service.report_template_activation_readiness runs the status change's own
checks (report_template_status_check) without the row lock and without writing
anything; the detail response carries it, the list carries only the country
gate (report_template_list_readiness). The real status change still runs every
check — Mexico's payslip proof included — and still writes its refusal audit row.
SYNTHETIC data only."""
from types import SimpleNamespace

import pytest
from sqlalchemy import event

READINESS_KEYS = {"canActivate", "blockedReason", "blockerKind", "gate", "countryGate", "deferredChecks",
                  "nextStatuses"}


def _user(db, email):
    from app.modules.auth.models import User, UserRole

    u = User(email=email, hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="Rea", last_name="Diness")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def admins(db):
    return [_user(db, f"readiness-{n}@example.com") for n in ("a", "b", "c")]


def _template(db, author, country, key, report_type="READINESS_TEST", state=None):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=key, name=f"{key} (SYNTHETIC)", reportType=report_type, jurisdictionCountry=country,
        jurisdictionState=state, reportingYear="2026", version="1.0"), actor_id=author.id)
    db.refresh(t)
    return t


def _force(db, t, **cols):
    """Put a row in a state the API would not produce today (an older row, a
    manual edit) — the checks must still answer the same way."""
    from app.modules.payroll.models import ReportTemplate

    db.query(ReportTemplate).filter(ReportTemplate.id == t.id).update(cols, synchronize_session=False)
    db.commit()
    db.refresh(t)
    return t


def _published(db, t, approver):
    return _force(db, t, status="Published", approved_by_id=approver.id)


def _real_refusal(db, t, actor):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    with pytest.raises(BadRequestException) as exc:
        service.set_report_template_status(db, t.id, "Active", actor_id=actor.id)
    db.rollback()
    db.refresh(t)
    return exc.value.message


def _readiness(db, t, actor):
    from app.modules.payroll import service

    db.refresh(t)
    return service.report_template_activation_readiness(db, t, actor.id)


# ── parity: for every current refusal the dry run gives the real message ─────
def _scenarios(db, a, b, c):
    """(label, template, activating admin, expected blocker kind, expected gate)."""
    out = [("transition (Draft)", _template(db, a, "DE", "RD-TRANSITION"), c, "transition", None)]
    out.append(("four-eyes R2 (no approver)", _force(db, _template(db, a, "DE", "RD-R2"), status="Published"),
                c, "four_eyes", None))
    out.append(("four-eyes R1 (self-approval)",
                _force(db, _template(db, a, "DE", "RD-R1"), status="Published", approved_by_id=a.id), c,
                "four_eyes", None))
    for country, gate in (("BE", "G3"), ("MY", "G3"), ("NZ", "G3"), ("PL", "G4"), ("JP", None)):
        out.append((f"{country} country gate", _published(db, _template(db, a, country, f"RD-{country}"), b), c,
                    "jurisdiction_gate", gate))
    out.append(("BR not built", _published(db, _template(db, a, "BR", "RD-BR"), b), c, "not_built", None))
    out.append(("ZA BRS catalogue", _published(db, _template(db, a, "ZA", "RD-ZA", "ZA_IRP5_PREVIEW"), b), c,
                "jurisdiction_gate", None))
    out.append(("HK no source evidence", _published(db, _template(db, a, "HK", "RD-HK"), b), c,
                "jurisdiction_gate", None))
    out.append(("MX gates (service-view report)", _published(db, _template(db, a, "MX", "RD-MX-IDSE", "MX_IDSE"), b),
                c, "jurisdiction_gate", None))
    out.append(("MX gates + no fields (template engine)",
                _published(db, _template(db, a, "MX", "RD-MX-REG", "MX_REGISTER"), b), c, "jurisdiction_gate", None))
    out.append(("MX unknown report type", _published(db, _template(db, a, "MX", "RD-MX-X", "MX_NOT_A_TYPE"), b), c,
                "jurisdiction_gate", None))
    out.append(("four-eyes R3 (approver activates)", _published(db, _template(db, a, "SG", "RD-R3"), b), b,
                "four_eyes", None))
    return out


def test_readiness_matches_every_current_refusal(db, admins):
    a, b, c = admins
    scenarios = _scenarios(db, a, b, c)
    # one Active version per slot: a second Published version of the same slot
    from app.modules.payroll import service
    first = _published(db, _template(db, a, "DE", "RD-SLOT-1", "RD_SLOT"), b)
    service.set_report_template_status(db, first.id, "Active", actor_id=c.id)
    scenarios.append(("conflict (slot taken)", _published(db, _template(db, a, "DE", "RD-SLOT-2", "RD_SLOT"), b), c,
                      "conflict", None))
    assert len(scenarios) >= 16
    for label, t, actor, kind, gate in scenarios:
        ready = _readiness(db, t, actor)
        assert set(ready) == READINESS_KEYS, label
        assert ready["canActivate"] is False, label
        assert (ready["blockerKind"], ready["gate"]) == (kind, gate), label
        assert ready["blockedReason"] == _real_refusal(db, t, actor), label


def test_readiness_allows_what_the_status_change_allows(db, admins):
    from app.modules.payroll import service

    a, b, c = admins
    t = _published(db, _template(db, a, "DE", "RD-OK"), b)
    ready = _readiness(db, t, c)
    assert ready["canActivate"] is True and ready["blockedReason"] is None and ready["blockerKind"] is None
    assert ready["countryGate"]["allowed"] is True and ready["nextStatuses"] == ["Active", "Superseded"]
    service.set_report_template_status(db, t.id, "Active", actor_id=c.id)       # the real change agrees


def test_country_gate_is_reported_whatever_the_status(db, admins):
    a, _, c = admins
    ready = _readiness(db, _template(db, a, "BE", "RD-BE-DRAFT"), c)          # Draft: transition comes first ...
    assert ready["blockerKind"] == "transition" and ready["nextStatuses"] == ["Review", "Approved"]
    gate = ready["countryGate"]                                                # ... but the badge knows G3 already
    assert (gate["allowed"], gate["blockerKind"], gate["gate"]) == (False, "jurisdiction_gate", "G3")
    assert "gate G3" in gate["message"]


def test_readiness_depends_on_who_asks(db, admins):
    a, b, c = admins
    t = _published(db, _template(db, a, "SG", "RD-PER-USER"), b)
    assert _readiness(db, t, b)["blockerKind"] == "four_eyes"                 # the approver may not activate
    assert _readiness(db, t, c)["canActivate"] is True                        # another admin may


# ── the dry run writes nothing ───────────────────────────────────────────────
def _counts(db):
    from app.modules.auth.models import AuthAuditEvent
    from app.modules.payroll.models import TaxConfigurationAudit
    from app.modules.security.models import SecurityEvent

    return tuple(db.query(m).count() for m in (TaxConfigurationAudit, AuthAuditEvent, SecurityEvent))


def test_readiness_is_a_pure_dry_run(db, admins):
    from app.modules.payroll import service

    a, b, c = admins
    blocked = [_published(db, _template(db, a, cc, f"RD-DRY-{cc}"), b) for cc in ("BE", "BR", "HK", "MX", "SG")]
    blocked.append(_template(db, a, "DE", "RD-DRY-DRAFT"))
    before = _counts(db)
    writes = []

    def spy(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE"):
            writes.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", spy)
    try:
        for t in blocked:
            for actor in (b, c):
                service.report_template_activation_readiness(db, t, actor.id)
                service.report_template_list_readiness(db, t, actor.id)
        assert not (db.new or db.dirty or db.deleted)
        db.flush()
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert writes == []
    assert _counts(db) == before                       # zero audit rows, zero security / auth events


def test_the_real_refusal_still_writes_its_audit_row(db, admins):
    from app.modules.payroll.models import TaxConfigurationAudit

    a, b, c = admins
    t = _published(db, _template(db, a, "BE", "RD-AUDIT"), b)
    q = db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "report_template",
                                               TaxConfigurationAudit.entity_id == t.id,
                                               TaxConfigurationAudit.action == "refused")
    _readiness(db, t, c)
    assert q.count() == 0
    message = _real_refusal(db, t, c)
    assert q.count() == 1 and q.one().reason == message


# ── Mexico: readiness leaves the tenant-payslip proof to the real activation ──
def test_mexico_readiness_skips_only_the_payslip_proof(db, admins, monkeypatch):
    from app.modules.payroll import mexico_report_service as mx

    a, b, c = admins
    t = _published(db, _template(db, a, "MX", "RD-MX-PROOF", "MX_REGISTER"), b)
    monkeypatch.setattr(mx, "_mx_activation_platform_reasons", lambda db, template: [])   # platform part passes
    monkeypatch.setattr(mx, "_mx_report_fields", lambda db, template: [object()])        # it has fields
    proofs = []
    monkeypatch.setattr(mx, "_mx_report_fields_proven",
                        lambda db, template: proofs.append(template.id) or "field x does not resolve")
    ready = _readiness(db, t, c)
    assert proofs == []                                               # the dry run never reads tenant payslips
    assert ready["countryGate"]["allowed"] is True
    assert ready["deferredChecks"] == [
        "Each field must resolve on a committed Mexican payslip — checked when the template is activated."]
    message = _real_refusal(db, t, c)                                 # ... the real activation does
    assert proofs == [t.id] and "field x does not resolve" in message


# ── wiring: detail carries full readiness, list the country gate only ────────
def test_detail_and_list_responses(db, admins):
    from app.modules.payroll.schemas import ReportTemplateResponse
    from app.modules.super_admin import router

    a, b, c = admins
    be = _published(db, _template(db, a, "BE", "RD-WIRE-BE"), b)
    me = SimpleNamespace(id=c.id)
    detail = ReportTemplateResponse.model_validate(router.get_report_template_detail(be.id, current_user=me, db=db))
    out = detail.model_dump(by_alias=True)["activationReadiness"]
    assert set(out) == READINESS_KEYS and out["gate"] == "G3" and out["canActivate"] is False
    rows = router.list_report_templates(country="BE", state=None, reportingYear=None, reportType=None, status=None,
                                        search=None, includeStates=True, current_user=me, db=db)
    listed = [ReportTemplateResponse.model_validate(r).model_dump(by_alias=True) for r in rows]
    mine = next(r for r in listed if r["id"] == be.id)["activationReadiness"]
    assert mine["partial"] is True and set(mine) == {"countryGate", "partial"}
    assert (mine["countryGate"]["blockerKind"], mine["countryGate"]["gate"]) == ("jurisdiction_gate", "G3")
