"""actorName on report-template audit rows: first + last name only, "User #<id>"
when there is no name, None for a system process; resolving it writes no
security / auth event. SYNTHETIC data only."""
from types import SimpleNamespace


def _user(db, email, first, last):
    from app.modules.auth.models import User, UserRole

    u = User(email=email, hashed_password="x", role=UserRole.SUPER_ADMIN, first_name=first, last_name=last)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_audit_rows_carry_the_actor_name_only(db):
    from app.modules.auth.models import AuthAuditEvent
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateUpsert, TaxConfigurationAuditResponse
    from app.modules.security.models import SecurityEvent
    from app.modules.super_admin import router

    named = _user(db, "audit-name-a@example.com", "Ada", "Lovelace")
    nameless = _user(db, "audit-name-b@example.com", "", "")
    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey="AN-1", name="AN (SYNTHETIC)", reportType="AN_TEST", jurisdictionCountry="DE",
        reportingYear="2026", version="1.0"), actor_id=named.id)
    service.set_report_template_status(db, t.id, "Review", actor_id=nameless.id)
    service.record_tax_audit(db, actor_id=None, action="update", entity_type="report_template", entity_id=t.id,
                             tax_version="1.0", old_value={"x": 1}, new_value={"x": 2}, reason="system")
    events = (db.query(SecurityEvent).count(), db.query(AuthAuditEvent).count())

    rows = router.get_report_template_audit(t.id, current_user=SimpleNamespace(id=named.id), db=db)
    out = [TaxConfigurationAuditResponse.model_validate(r).model_dump(by_alias=True) for r in rows]
    by_actor = {r["actorId"]: r["actorName"] for r in out}
    assert by_actor[named.id] == "Ada Lovelace"
    assert by_actor[nameless.id] == f"User #{nameless.id}"
    assert by_actor[None] is None
    assert all("@" not in str(r.get("actorName")) for r in out)            # never an email
    assert (db.query(SecurityEvent).count(), db.query(AuthAuditEvent).count()) == events


def test_names_for_missing_users_fall_back():
    from app.modules.payroll import service

    class _Q:
        def filter(self, *a):
            return []

    db = SimpleNamespace(query=lambda *cols: _Q())
    assert service.audit_actor_names(db, [7, None, 7]) == {7: "User #7"}
    assert service.audit_actor_names(db, [None]) == {}
