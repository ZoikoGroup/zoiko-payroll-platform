"""Structured report-template activation checks (refactor, no behaviour change).

service.report_template_status_check runs the lifecycle checks of the status
change in their original order and returns the first failure as
{allowed, message, blockerKind, gate}; the status change raises exactly that
message. Country template_activation_refusal hooks return ActivationRefusal — a
str subclass, so the message text and every existing caller are unchanged —
carrying the blocker kind and, where the rule names one, the release gate.
SYNTHETIC data only."""
from types import SimpleNamespace

import pytest


def _user(db, email):
    from app.modules.auth.models import User, UserRole

    u = User(email=email, hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="T", last_name="U")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def admins(db):
    return [_user(db, f"activation-checks-{n}@example.com") for n in ("a", "b", "c")]


def _template(db, author, country, key, report_type="ACTIVATION_CHECK_TEST"):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=key, name=f"{key} (SYNTHETIC)", reportType=report_type, jurisdictionCountry=country,
        reportingYear="2026", version="1.0"), actor_id=author.id)
    db.refresh(t)
    return t


def _to_published(db, t, author, approver):
    from app.modules.payroll import service

    service.set_report_template_status(db, t.id, "Approved", actor_id=author.id)
    service.set_report_template_approver(db, t.id, actor_id=approver.id)
    service.set_report_template_status(db, t.id, "Published", actor_id=approver.id)
    db.refresh(t)
    return t


def _refusal_of(db, t, status, actor):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    with pytest.raises(BadRequestException) as exc:
        service.set_report_template_status(db, t.id, status, actor_id=actor.id)
    db.rollback()
    return exc.value.message


# ── the refusal type ─────────────────────────────────────────────────────────
def test_activation_refusal_is_the_plain_message():
    from app.modules.payroll.template_activation import JURISDICTION_GATE, ActivationRefusal, as_result

    r = ActivationRefusal("blocked (gate G3).", JURISDICTION_GATE, gate="G3")
    assert r == "blocked (gate G3)." and isinstance(r, str) and "G3" in r and str(r) == "blocked (gate G3)."
    assert r.as_result() == {"allowed": False, "message": "blocked (gate G3).", "blockerKind": "jurisdiction_gate",
                             "gate": "G3"}
    assert as_result(None) == {"allowed": True, "message": None, "blockerKind": None, "gate": None}
    # a hook that still returns a plain string: reported with the default kind, no gate guessed
    assert as_result("plain (gate G9).") == {"allowed": False, "message": "plain (gate G9).",
                                             "blockerKind": "jurisdiction_gate", "gate": None}
    with pytest.raises(ValueError):
        ActivationRefusal("x", "made_up_kind")


# ── every structured country hook ────────────────────────────────────────────
def _t(**kw):
    return SimpleNamespace(**{"template_key": "K", "version": "1.0", "jurisdiction_country": "XX",
                              "report_type": "X", "approved_by_id": None, "content_editor_id": None, **kw})


@pytest.mark.parametrize("country,template,kind,gate", [
    ("BR", _t(jurisdiction_country="BR"), "not_built", None),
])
def test_static_country_hooks_carry_kind_and_gate(country, template, kind, gate):
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll.template_activation import ActivationRefusal

    refusal = jurisdiction_hooks.call(country, "template_activation_refusal", None, template, 1)
    assert isinstance(refusal, ActivationRefusal), country
    assert (refusal.blocker_kind, refusal.gate) == (kind, gate)



@pytest.mark.parametrize("country,template", [
    ("BE", _t(jurisdiction_country="BE")), ("JP", _t(jurisdiction_country="JP")),
    ("MY", _t(jurisdiction_country="MY")), ("NZ", _t(jurisdiction_country="NZ")),
    ("PL", _t(jurisdiction_country="PL")), ("ZA", _t(jurisdiction_country="ZA", report_type="ZA_IRP5_PREVIEW")),
])
def test_gate_removed_countries_have_no_template_gate(country, template):
    """gate removal 2026-11-25: these countries' templates follow the normal governance."""
    from app.modules.payroll import jurisdiction_hooks

    assert jurisdiction_hooks.call(country, "template_activation_refusal", None, template, 1) is None


def test_hong_kong_hook_kinds(db):
    from app.modules.payroll import hong_kong_service as hk

    no_source = hk.template_activation_refusal(db, _t(jurisdiction_country="HK", source_document_id=None), 1)
    assert no_source.blocker_kind == "jurisdiction_gate" and "no source evidence" in no_source


def test_mexico_hook_is_a_country_gate(db):
    from app.modules.payroll import jurisdiction_hooks

    refusal = jurisdiction_hooks.call("MX", "template_activation_refusal", db, _t(jurisdiction_country="MX",
                                                                                  report_type="NOT_AN_MX_TYPE"), 1)
    assert refusal.blocker_kind == "jurisdiction_gate" and refusal.startswith("Mexico report-template activation")


def test_hooks_that_allow_still_return_none():
    from app.modules.payroll import jurisdiction_hooks

    assert jurisdiction_hooks.call("NL", "template_activation_refusal", None, _t(jurisdiction_country="NL"), 1) is None
    assert jurisdiction_hooks.call("SA", "template_activation_refusal", None, _t(jurisdiction_country="SA"), 1) is None
    assert jurisdiction_hooks.call("ZA", "template_activation_refusal", None,
                                   _t(jurisdiction_country="ZA", report_type="ZA_PAYROLL_REGISTER"), 1) is None


# ── the shared check helper: structure + same message as the status change ───
def test_transition_check(db, admins):
    from app.modules.payroll import service

    a, _, _ = admins
    t = _template(db, a, "DE", "AC-TRANSITION")
    check = service.report_template_status_check(db, t, "Active", a.id)
    assert check["allowed"] is False and check["blockerKind"] == "transition" and check["gate"] is None
    assert check["message"] == _refusal_of(db, t, "Active", a)


def test_unknown_status_check(db, admins):
    from app.modules.payroll import service

    a, _, _ = admins
    t = _template(db, a, "DE", "AC-UNKNOWN")
    check = service.report_template_status_check(db, t, "Live", a.id)
    assert check["blockerKind"] == "unknown_status" and check["message"] == _refusal_of(db, t, "Live", a)


def test_four_eyes_r3_check(db, admins):
    from app.modules.payroll import service

    a, b, _ = admins
    t = _to_published(db, _template(db, a, "SG", "AC-R3"), a, b)       # SG: approver may not activate
    check = service.report_template_status_check(db, t, "Active", b.id)
    assert check["blockerKind"] == "four_eyes" and check["message"] == _refusal_of(db, t, "Active", b)


def test_country_gate_check(db, admins):
    from app.modules.payroll import service

    a, b, c = admins
    t = _to_published(db, _template(db, a, "HK", "AC-HK"), a, b)          # HK: no source evidence linked
    check = service.report_template_status_check(db, t, "Active", c.id)
    assert (check["blockerKind"], check["gate"]) == ("jurisdiction_gate", None)
    assert check["message"] == _refusal_of(db, t, "Active", c)


def test_conflict_check_and_allowed(db, admins):
    from app.modules.payroll import service

    a, b, c = admins
    first = _to_published(db, _template(db, a, "DE", "AC-SLOT-1", report_type="AC_SLOT"), a, b)
    assert service.report_template_status_check(db, first, "Active", c.id)["allowed"] is True
    service.set_report_template_status(db, first.id, "Active", actor_id=c.id)
    second = _to_published(db, _template(db, a, "DE", "AC-SLOT-2", report_type="AC_SLOT"), a, b)
    check = service.report_template_status_check(db, second, "Active", c.id)
    assert check["blockerKind"] == "conflict" and check["message"] == _refusal_of(db, second, "Active", c)
