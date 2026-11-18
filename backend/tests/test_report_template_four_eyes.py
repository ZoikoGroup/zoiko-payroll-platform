"""Report-template four-eyes rules over the last CONTENT editor (2026-11-18).

MAKER-CHECKER CHANGE — requires ZP-PRIV review (Rugvedh) before merge.

The rules compared the approver with updated_by_id, which every status change
overwrote: an approver who clicked Published became the "editor" and Active was
then refused for everyone (the Published trap). content_editor_id is set only
by content edits (metadata, components, fields); the rules
(service.report_template_four_eyes_refusal + set_report_template_approver) read it.
  R1 no self-approval (Approve; and the approver != content editor at Published / Active)
  R2 Published needs a recorded approver
  R3 the approver may not activate (countries in _APPROVER_NOT_ACTIVATOR_COUNTRIES, as for packs)
Country template_activation_refusal hooks are unchanged. SYNTHETIC data only."""
import importlib.util
from pathlib import Path

import pytest

OPT_IN = "PL"        # in _APPROVER_NOT_ACTIVATOR_COUNTRIES (R3 applies)
OTHER = "DE"         # not in it: the checker may approve and activate (owner decision 2026-09-28)


def _user(db, email):
    from app.modules.auth.models import User, UserRole

    u = User(email=email, hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="T", last_name="U")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def admins(db):
    return [_user(db, f"four-eyes-{n}@example.com") for n in ("a", "b", "c")]


@pytest.fixture
def no_country_hook(monkeypatch):
    """The country activation hooks are tested for themselves below; here only
    the shared four-eyes rules are under test."""
    from app.modules.payroll import jurisdiction_hooks

    monkeypatch.setattr(jurisdiction_hooks, "has_module", lambda country: False)


def _template(db, author, country, key):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateComponentUpsert, ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=key, name=f"{key} (SYNTHETIC)", reportType="FOUR_EYES_TEST", jurisdictionCountry=country,
        reportingYear="2026", version="1.0"), actor_id=author.id)
    service.upsert_report_component(db, t.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Earnings"),
                                    actor_id=author.id)
    db.refresh(t)
    return t


def _status(db, t, status, who):
    from app.modules.payroll import service

    return service.set_report_template_status(db, t.id, status, actor_id=who.id)


def test_status_only_changes_never_change_the_content_editor(db, admins):
    from app.modules.payroll import service

    a, b, c = admins
    t = _template(db, a, OTHER, "FE-STATUS")
    assert t.content_editor_id == a.id
    _status(db, t, "Review", b)
    _status(db, t, "Draft", c)
    _status(db, t, "Approved", b)
    service.set_report_template_approver(db, t.id, actor_id=b.id)
    db.refresh(t)
    assert t.content_editor_id == a.id                       # status changes and Approve: not content edits
    assert t.updated_by_id == b.id                           # updated_by_id still tracks the last actor


def test_a_content_edit_makes_its_author_the_content_editor_and_clears_the_approval(db, admins):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateComponentUpsert

    a, b, _ = admins
    t = _template(db, a, OTHER, "FE-EDIT")
    service.set_report_template_approver(db, t.id, actor_id=b.id)
    service.upsert_report_component(db, t.id, ReportTemplateComponentUpsert(componentKey="tax", label="Tax"),
                                    actor_id=b.id)
    db.refresh(t)
    assert t.content_editor_id == b.id and t.approved_by_id is None and t.status == "Draft"


def test_outside_the_opt_in_list_self_approval_is_recorded_but_never_released(db, admins):
    """Unchanged order for other countries: the self-approval is recorded at
    Approve and refused at Published (R1, now over the content editor)."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    a, b, _ = admins
    t = _template(db, a, OTHER, "FE-SELF-OTHER")
    assert service.set_report_template_approver(db, t.id, actor_id=a.id).approved_by_id == a.id
    with pytest.raises(BadRequestException, match=r"no self-approval — a distinct approver is required.*user #%d"
                       % a.id):
        _status(db, t, "Published", b)
    db.rollback()
    service.set_report_template_approver(db, t.id, actor_id=b.id)
    assert _status(db, t, "Published", a).status == "Published"


def test_the_author_cannot_approve_their_own_content(db, admins):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    country = OPT_IN
    a, b, _ = admins
    t = _template(db, a, country, f"FE-SELF-{country}")
    with pytest.raises(BadRequestException, match=r"no self-approval.*not user #%d" % a.id):
        service.set_report_template_approver(db, t.id, actor_id=a.id)
    db.rollback()
    db.refresh(t)
    assert t.approved_by_id is None
    # Moving it to Approved yourself does not make you able to approve it either.
    _status(db, t, "Approved", a)
    with pytest.raises(BadRequestException, match="no self-approval"):
        service.set_report_template_approver(db, t.id, actor_id=a.id)
    db.rollback()
    assert service.set_report_template_approver(db, t.id, actor_id=b.id).approved_by_id == b.id


def test_published_needs_a_recorded_approver(db, admins):
    from app.core.exceptions import BadRequestException

    a, b, _ = admins
    t = _template(db, a, OTHER, "FE-NOAPPROVER")
    _status(db, t, "Approved", b)
    with pytest.raises(BadRequestException, match=r"approval required.*other than its last content editor \(user #%d\)"
                       % a.id):
        _status(db, t, "Published", b)


def test_the_approver_who_publishes_cannot_activate_but_another_admin_can(db, admins, no_country_hook):
    """The Published trap: B approves AND publishes. Before, B became the
    'editor' and nobody could activate. Now B (the approver) is refused by R3
    with who may act instead, and A or C activates."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    a, b, c = admins
    t = _template(db, a, OPT_IN, "FE-TRAP")
    service.set_report_template_approver(db, t.id, actor_id=b.id)
    _status(db, t, "Published", b)
    db.refresh(t)
    assert t.content_editor_id == a.id and t.approved_by_id == b.id and t.updated_by_id == b.id
    with pytest.raises(BadRequestException, match=r"the approver may not activate.*not user #%d" % b.id):
        _status(db, t, "Active", b)
    db.rollback()
    assert _status(db, t, "Active", c).status == "Active"


def test_the_author_may_activate_what_another_admin_approved(db, admins, no_country_hook):
    from app.modules.payroll import service

    a, b, _ = admins
    t = _template(db, a, OPT_IN, "FE-AUTHOR-ACTIVATES")
    service.set_report_template_approver(db, t.id, actor_id=b.id)
    _status(db, t, "Published", b)
    assert _status(db, t, "Active", a).status == "Active"


def test_other_countries_keep_checker_approves_and_activates(db, admins, no_country_hook):
    """Owner decision 2026-09-28 (as for packs): outside the opt-in list the
    approver may activate — and publishing no longer blocks them (the trap)."""
    from app.modules.payroll import service

    a, b, _ = admins
    t = _template(db, a, OTHER, "FE-CHECKER-ACTIVATES")
    service.set_report_template_approver(db, t.id, actor_id=b.id)
    _status(db, t, "Published", b)
    assert _status(db, t, "Active", b).status == "Active"


def test_activator_not_approver_matches_the_pack_opt_in_list():
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate

    for country in service._APPROVER_NOT_ACTIVATOR_COUNTRIES:
        row = ReportTemplate(template_key="K", version="1", jurisdiction_country=country, approved_by_id=2,
                             content_editor_id=1)
        assert "the approver may not activate" in service.report_template_four_eyes_refusal(row, "Active", 2)
        assert service.report_template_four_eyes_refusal(row, "Active", 3) is None
        assert service.report_template_four_eyes_refusal(row, "Published", 2) is None   # R3 is about Active only
    row = ReportTemplate(template_key="K", version="1", jurisdiction_country=OTHER, approved_by_id=2, content_editor_id=1)
    assert service.report_template_four_eyes_refusal(row, "Active", 2) is None
    row.content_editor_id = 2
    assert "no self-approval" in service.report_template_four_eyes_refusal(row, "Active", 3)


def test_country_activation_hooks_still_run_unchanged_after_the_four_eyes_rules(db, admins, monkeypatch):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import jurisdiction_hooks

    """Order: R1 / R2, then the country hook (unchanged, its own message wins),
    then R3 (the approver may not activate) for a hook that allows it."""
    calls, answer = [], {"refusal": "country hook refusal (SYNTHETIC)"}
    monkeypatch.setattr(jurisdiction_hooks, "has_module", lambda country: country == OPT_IN)
    monkeypatch.setattr(jurisdiction_hooks, "call",
                        lambda country, name, db_, row, actor: calls.append((country, name, row.id, actor))
                        or answer["refusal"])
    a, b, c = admins
    t = _template(db, a, OPT_IN, "FE-HOOK")
    from app.modules.payroll import service

    _status(db, t, "Approved", b)
    with pytest.raises(BadRequestException, match="approval required"):
        _status(db, t, "Published", b)                  # R2 before anything: the hook is not reached
    db.rollback()
    service.set_report_template_approver(db, t.id, actor_id=b.id)
    _status(db, t, "Published", b)
    with pytest.raises(BadRequestException, match="country hook refusal"):
        _status(db, t, "Active", c)                     # R1 / R2 pass: the country hook decides, unchanged
    db.rollback()
    assert calls == [(OPT_IN, "template_activation_refusal", t.id, c.id)]
    answer["refusal"] = None                            # the hook allows it ...
    with pytest.raises(BadRequestException, match="approver may not activate"):
        _status(db, t, "Active", b)                     # ... R3 still refuses the approver
    db.rollback()
    assert _status(db, t, "Active", c).status == "Active"


def test_mexico_new_version_copy_is_content_edited_by_its_copier(db, admins):
    from app.modules.payroll import mexico_report_service as R
    from app.modules.payroll.models import ReportTemplate
    from tests.test_mexico_report_generators import _seed

    a, b, _ = admins
    src = _seed(db)["MX-PAYROLL-REGISTER"]
    out = R.mx_template_new_version(db, src.id, "1.0-fe", "SYNTHETIC four-eyes check", b.id)
    copy = db.get(ReportTemplate, out["id"])
    assert copy.content_editor_id == b.id and copy.approved_by_id is None


# ── the production shape: seeded templates one admin approved AND published ──

def _seeded_and_trapped(db, approver, country, key):
    """A seed-written template (actor None), then ONE Super Admin clicked
    Approve and Published — then, before the fix, Active was refused for all."""
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateComponentUpsert, ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=key, name=key, reportType="FOUR_EYES_TEST", jurisdictionCountry=country, reportingYear="2026",
        version="1.0"), actor_id=None)
    service.upsert_report_component(db, t.id, ReportTemplateComponentUpsert(componentKey="earnings", label="E"),
                                    actor_id=None)
    service.set_report_template_approver(db, t.id, actor_id=approver.id)
    _status(db, t, "Published", approver)
    db.refresh(t)
    assert t.approved_by_id == t.updated_by_id == approver.id      # the trapped shape
    return t


def test_a_seeded_template_the_approver_published_is_recovered_without_data_edits(db, admins, no_country_hook):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    venu, other, _ = admins
    t = _seeded_and_trapped(db, venu, OPT_IN, "FE-PROD-SHAPE")
    assert t.content_editor_id is None                              # the seed wrote the content
    assert service.report_template_content_editor_from_audit(db, t)[0] is None
    with pytest.raises(BadRequestException, match="approver may not activate"):
        _status(db, t, "Active", venu)
    db.rollback()
    assert _status(db, t, "Active", other).status == "Active"       # manual, four-eyes; no data edit needed
    t2 = _seeded_and_trapped(db, venu, OTHER, "FE-PROD-SHAPE-DE")
    assert _status(db, t2, "Active", venu).status == "Active"       # outside the opt-in list: as before the trap


def test_dry_run_report_groups_and_never_writes(db, admins, monkeypatch):
    from app.modules.payroll import jurisdiction_hooks, service
    from app.modules.payroll.models import ReportTemplate, TaxConfigurationAudit
    from scripts import report_stuck_published_templates as rep

    venu, other, _ = admins
    a = _seeded_and_trapped(db, venu, OPT_IN, "FE-DRY-A")
    b = _seeded_and_trapped(db, venu, "ZZ", "FE-DRY-B")
    c = _seeded_and_trapped(db, venu, OTHER, "FE-DRY-C")
    # C: legacy row where the approver had also edited the content (possible before R1 applied everywhere)
    db.add(TaxConfigurationAudit(actor_id=venu.id, action="update", entity_type="report_template_field",
                                 entity_id=c.id, old_value={}, new_value={}))
    db.commit()
    monkeypatch.setattr(jurisdiction_hooks, "has_module", lambda country: country in (OPT_IN, "ZZ"))
    monkeypatch.setattr(jurisdiction_hooks, "call", lambda country, name, db_, row, actor:
                        "ZZ gate: source evidence missing (SYNTHETIC)" if country == "ZZ" else None)
    before = {r.id: (r.status, r.approved_by_id, r.updated_by_id, r.content_editor_id)
              for r in db.query(ReportTemplate).filter(ReportTemplate.id.in_((a.id, b.id, c.id)))}
    got = {t.id: rep.classify(db, t) for t in (a, b, c)}
    assert got[a.id]["group"] == "A" and "except the approver" in got[a.id]["mayActivate"]
    assert got[b.id]["group"] == "B" and "source evidence missing" in got[b.id]["hook"]
    assert got[c.id]["group"] == "C" and got[c.id]["editor"] == venu.id
    db.expire_all()
    after = {r.id: (r.status, r.approved_by_id, r.updated_by_id, r.content_editor_id)
             for r in db.query(ReportTemplate).filter(ReportTemplate.id.in_((a.id, b.id, c.id)))}
    assert after == before                                          # statuses and editors untouched
    assert all(service.report_template_content_editor_from_audit(db, t)[0] in (None, venu.id) for t in (a, b, c))


# ── migration d7a3f1c9e5b2: the backfill rules ───────────────────────────────

def _run_upgrade(conn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "d7a3f1c9e5b2_report_template_content_editor.py"
    spec = importlib.util.spec_from_file_location("mig_d7a3f1c9e5b2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with Operations.context(MigrationContext.configure(conn)):
        mod.upgrade()


def test_migration_backfills_the_content_editor_from_the_audit_log():
    import sqlalchemy as sa

    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text("CREATE TABLE payroll_report_templates (id INTEGER PRIMARY KEY, updated_by_id INTEGER)"))
        conn.execute(sa.text("CREATE TABLE payroll_tax_configuration_audit (id INTEGER PRIMARY KEY, entity_id INTEGER, "
                             "entity_type VARCHAR, action VARCHAR, actor_id INTEGER, reason VARCHAR, created_at TIMESTAMP)"))
        # 1: edited by 7 (component), later approved by 8 and published by 8 (the trap): editor 7
        # 2: created by 5, then a field edit by 6: editor 6
        # 3: seeded (system create), then only status changes by 9: NULL (9 never edited content) — the
        #    production shape: approver 18 clicked Approve + Published on seeded templates
        # 4: no audit history at all: NULL — never updated_by_id (the status changer)
        # 5: a human edit by 7, then the seed rewrote it (Draft): the seed's (NULL)
        conn.execute(sa.text("INSERT INTO payroll_report_templates VALUES (1, 8), (2, 6), (3, 9), (4, 4), (5, 9)"))
        conn.execute(sa.text(
            "INSERT INTO payroll_tax_configuration_audit (entity_id, entity_type, action, actor_id, reason, created_at) "
            "VALUES (1, 'report_template', 'create', NULL, NULL, '2026-10-01'),"
            "       (1, 'report_template_component', 'create', 7, NULL, '2026-10-02'),"
            "       (1, 'report_template', 'update', 8, 'Approver set', '2026-10-03'),"
            "       (1, 'report_template', 'status_change', 8, NULL, '2026-10-04'),"
            "       (2, 'report_template', 'create', 5, NULL, '2026-10-01'),"
            "       (2, 'report_template_field', 'update', 6, NULL, '2026-10-02'),"
            "       (3, 'report_template', 'create', NULL, NULL, '2026-10-01'),"
            "       (3, 'report_template', 'status_change', 9, NULL, '2026-10-02'),"
            "       (3, 'report_template', 'refused', 9, 'x', '2026-10-03'),"
            "       (5, 'report_template_field', 'update', 7, NULL, '2026-10-01'),"
            "       (5, 'report_template_field', 'update', NULL, NULL, '2026-10-02'),"
            "       (5, 'report_template', 'status_change', 9, NULL, '2026-10-03')"))
        _run_upgrade(conn)
        got = dict(conn.execute(sa.text("SELECT id, content_editor_id FROM payroll_report_templates")).fetchall())
        assert got == {1: 7, 2: 6, 3: None, 4: None, 5: None}
        _run_upgrade(conn)                                   # idempotent
        assert dict(conn.execute(sa.text("SELECT id, content_editor_id FROM payroll_report_templates")).fetchall()) == got
