"""Report-template document scope (2026-11-18).

  - Rule: every seeded template whose key or report type ends in PREVIEW /
    STATEMENT / YTD is a per-employee document (PER_EMPLOYEE), across the whole
    seed (seed_statutory_report_templates.run).
  - The Super Admin detail returns the STORED scope and source document. It
    omitted both, so ReportTemplateResponse filled its defaults and every
    template read "Aggregate document" / "None linked" whatever the row held.
  - A PER_EMPLOYEE template with SUM_YTD fields generates one document per
    employee (each with that employee's own year-to-date), the per-employee
    certificate renders for each, and the history reports the scope.
SYNTHETIC data only."""
import re
from datetime import date

import pytest

YTD_DOCUMENT = re.compile(r"[-_](PREVIEW|STATEMENT|YTD)$")


def test_every_seeded_preview_statement_and_ytd_template_is_per_employee(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.modules.payroll.models import ReportTemplate
    from scripts import seed_statutory_report_templates as seed

    # run() opens its own session: bind it to the test database, never the configured one.
    monkeypatch.setattr(seed, "SessionLocal", sessionmaker(bind=db.get_bind()))
    seed.run()
    db.expire_all()
    rows = db.query(ReportTemplate).all()
    named = [t for t in rows if YTD_DOCUMENT.search(t.template_key) or YTD_DOCUMENT.search(t.report_type)]
    rollout = {"FR_NET_IMPOSABLE_YTD", "IT_CU_PREVIEW", "SA_GOSI_STATEMENT", "JP_GENSEN_PREVIEW", "MY_EA_PREVIEW",
               "PL_PIT11_PREVIEW", "ZA_IRP5_PREVIEW"}
    assert rollout <= {t.report_type for t in named}
    wrong = sorted(f"{t.template_key} ({t.report_type}) = {t.document_scope}" for t in named
                   if t.document_scope != "PER_EMPLOYEE")
    assert wrong == []


def test_the_detail_returns_the_stored_scope_and_source_document(db):
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate
    from app.modules.payroll.schemas import ReportTemplateResponse

    t = ReportTemplate(template_key="SCOPE-DETAIL-T", name="T", report_type="X_PREVIEW", jurisdiction_country="FR",
                       reporting_year="2026", version="1.0", status="Draft", document_scope="PER_EMPLOYEE")
    db.add(t)
    db.commit()
    out = ReportTemplateResponse.model_validate(service.get_report_template_detail(db, t.id)).model_dump(by_alias=True)
    assert out["documentScope"] == "PER_EMPLOYEE" and out["sourceDocumentId"] is None
    t.document_scope = "AGGREGATE"
    db.commit()
    out = ReportTemplateResponse.model_validate(service.get_report_template_detail(db, t.id)).model_dump(by_alias=True)
    assert out["documentScope"] == "AGGREGATE"


def _user(db, email):
    from app.modules.auth.models import User, UserRole

    u = User(email=email, hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="T", last_name="U")
    db.add(u)
    db.commit()
    return u


def test_per_employee_sum_ytd_generates_one_document_per_employee(db, organization):
    from app.modules.payroll import service
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem
    from app.modules.payroll.schemas import (ReportTemplateComponentUpsert, ReportTemplateFieldUpsert,
                                             ReportTemplateUpsert)

    author, approver = _user(db, "scope-author@example.com"), _user(db, "scope-approver@example.com")
    db.add(CompanyComplianceDetails(organization_id=organization.id, name="Acme (SYNTHETIC)", tax_no="X",
                                    jurisdiction_country="IN", jurisdiction_state=""))
    emps = []
    for code, name in (("S1", "Asha (SYNTHETIC)"), ("S2", "Ravi (SYNTHETIC)")):
        e = PayrollEmployee(organization_id=organization.id, employee_code=code, name=name)
        db.add(e)
        emps.append(e)
    db.commit()
    runs = []
    for label, start, end in (("Jul 2026", date(2026, 7, 1), date(2026, 7, 31)),
                              ("Aug 2026", date(2026, 8, 1), date(2026, 8, 31))):
        r = PayrollRun(organization_id=organization.id, period_label=label, period_start=start, period_end=end,
                       pay_date=end, status="Approved", total_gross=0, total_deductions=0, total_net=0)
        db.add(r)
        runs.append(r)
    db.commit()
    tds = {(0, 0): 100, (0, 1): 200, (1, 0): 1000, (1, 1): 2000}       # (run, employee) -> tds
    for (ri, ei), amount in tds.items():
        db.add(PayslipItem(payroll_run_id=runs[ri].id, employee_id=emps[ei].id, organization_id=organization.id,
                           employee_name=emps[ei].name, gross_pay=10 * amount, tds=amount,
                           total_deductions=amount, net_pay=9 * amount))
    db.commit()
    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey="SCOPE-YTD-PREVIEW", name="YTD preview (SYNTHETIC)", reportType="FORM_130",
        jurisdictionCountry="IN", reportingYear="2026-27", documentScope="PER_EMPLOYEE"), actor_id=author.id)
    comp = service.upsert_report_component(db, t.id, ReportTemplateComponentUpsert(componentKey="tax", label="Tax"),
                                           actor_id=author.id)
    service.upsert_report_field(db, comp.id, ReportTemplateFieldUpsert(
        fieldKey="tds_ytd", label="TDS (YTD)", fieldType="currency", dataSourceKind="PAYSLIP_ITEM",
        sourceColumn="tds", aggregation="SUM_YTD"), actor_id=author.id)
    service.set_report_template_approver(db, t.id, actor_id=approver.id)
    service.set_report_template_status(db, t.id, "Published", actor_id=author.id)
    service.set_report_template_status(db, t.id, "Active", actor_id=author.id)

    generated = service.generate_report_from_template(db, organization.id, t.id, runs[1].id,
                                                      reporting_period=runs[1].period_label, actor_id=author.id)
    employees = generated.rendered_data["employees"]
    assert sorted(e["employeeId"] for e in employees) == sorted(e.id for e in emps)   # one document per employee
    ytd = {e["employeeId"]: e["values"]["tds_ytd"] for e in employees}
    assert ytd == {emps[0].id: 1100.0, emps[1].id: 2200.0}                             # each employee's own YTD
    for e in emps:
        pdf = service.generate_report_certificate_pdf_bytes(db, organization.id, generated.id, e.id)
        assert pdf[:4] == b"%PDF"
    listed = service._attach_document_scope(db, [generated])
    assert listed[0].document_scope == "PER_EMPLOYEE"                                 # history / preview read this


# ── recovery script: scripts/fix_report_template_scope.py ────────────────────

def _published_preview(db, key, scope, author, approver, version="1.0"):
    """A released per-employee template stored with `scope` (the shape to recover)."""
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateComponentUpsert, ReportTemplateUpsert

    t = service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey=key, name=f"{key} (SYNTHETIC)", reportType=key.replace("-", "_"), jurisdictionCountry="FR",
        reportingYear="2026", version=version, documentScope=scope), actor_id=author.id)
    service.upsert_report_component(db, t.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Earnings"),
                                    actor_id=author.id)
    service.set_report_template_approver(db, t.id, actor_id=approver.id)
    return service.set_report_template_status(db, t.id, "Published", actor_id=author.id)


def _run_script(db, *args):
    from sqlalchemy.orm import sessionmaker

    from scripts import fix_report_template_scope as fix

    return fix.main(list(args), session_factory=sessionmaker(bind=db.get_bind()))


def _rows(db, key):
    from app.modules.payroll.models import ReportTemplate

    db.expire_all()
    return {t.version: t for t in db.query(ReportTemplate).filter(ReportTemplate.template_key == key)}


def test_scope_fix_dry_run_lists_only_wrongly_stored_published_rows_and_writes_nothing(db, capsys):
    a, b, runner = (_user(db, f"scope-fix-{n}@example.com") for n in ("a", "b", "runner"))
    _published_preview(db, "FR-BAD-YTD", "AGGREGATE", a, b)
    _published_preview(db, "FR-GOOD-PREVIEW", "PER_EMPLOYEE", a, b)
    _published_preview(db, "FR-PAYROLL-SUMMARY", "AGGREGATE", a, b)       # not a per-employee name: untouched
    assert _run_script(db, "--actor-email", runner.email) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "FR-BAD-YTD v1.0" in out and "new Draft v1.1 PER_EMPLOYEE" in out
    assert "FR-GOOD-PREVIEW" not in out and "FR-PAYROLL-SUMMARY" not in out
    assert set(_rows(db, "FR-BAD-YTD")) == {"1.0"}                         # nothing written


def test_scope_fix_apply_creates_a_draft_version_through_the_service(db, capsys):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplateComponent, TaxConfigurationAudit

    a, b, runner = (_user(db, f"scope-apply-{n}@example.com") for n in ("a", "b", "runner"))
    old = _published_preview(db, "FR-T-NET-IMPOSABLE-YTD", "AGGREGATE", a, b)
    before = (old.status, old.document_scope, old.approved_by_id, old.updated_by_id)
    assert _run_script(db, "--actor-email", runner.email, "--apply") == 0
    rows = _rows(db, "FR-T-NET-IMPOSABLE-YTD")
    old, new = rows["1.0"], rows["1.1"]
    assert (old.status, old.document_scope, old.approved_by_id, old.updated_by_id) == before   # never modified
    assert (new.status, new.document_scope, new.change_summary) == ("Draft", "PER_EMPLOYEE", "Scope fix: per-employee")
    assert new.created_by_id == new.content_editor_id == runner.id and new.approved_by_id is None
    assert new.previous_version_id == old.id
    assert [c.component_key for c in db.query(ReportTemplateComponent)
            .filter(ReportTemplateComponent.report_template_id == new.id)] == ["earnings"]     # content copied
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_id == new.id,
                                                  TaxConfigurationAudit.action == "create",
                                                  TaxConfigurationAudit.actor_id == runner.id).count() == 1
    # Four-eyes: the runner cannot release it; another Super Admin approves.
    service.set_report_template_approver(db, new.id, actor_id=runner.id)
    with pytest.raises(BadRequestException, match="no self-approval"):
        service.set_report_template_status(db, new.id, "Published", actor_id=a.id)
    db.rollback()
    service.set_report_template_approver(db, new.id, actor_id=b.id)
    assert service.set_report_template_status(db, new.id, "Published", actor_id=a.id).status == "Published"
    capsys.readouterr()
    assert _run_script(db, "--actor-email", runner.email, "--apply") == 0   # a re-run never duplicates the fix
    out = capsys.readouterr().out
    assert "SKIP FR FR-T-NET-IMPOSABLE-YTD v1.0: a later version already exists (v1.1, Published)" in out
    assert set(_rows(db, "FR-T-NET-IMPOSABLE-YTD")) == {"1.0", "1.1"}


def test_scope_fix_skips_a_template_with_a_later_version_and_refuses_a_non_super_admin(db, capsys):
    from app.modules.auth.models import User, UserRole

    a, b, runner = (_user(db, f"scope-skip-{n}@example.com") for n in ("a", "b", "runner"))
    _published_preview(db, "FR-LATER-PREVIEW", "AGGREGATE", a, b)
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateUpsert

    service.upsert_report_template(db, ReportTemplateUpsert(
        templateKey="FR-LATER-PREVIEW", name="x", reportType="FR_LATER_PREVIEW", jurisdictionCountry="FR",
        reportingYear="2026", version="2.0", documentScope="PER_EMPLOYEE"), actor_id=a.id)
    assert _run_script(db, "--actor-email", runner.email, "--apply") == 0
    assert "SKIP FR FR-LATER-PREVIEW v1.0: a later version already exists (v2.0, Draft)" in capsys.readouterr().out
    assert set(_rows(db, "FR-LATER-PREVIEW")) == {"1.0", "2.0"}
    admin = User(email="scope-org-admin@example.com", hashed_password="x", role=UserRole.PAYROLL_ADMIN,
                 first_name="T", last_name="U")
    db.add(admin)
    db.commit()
    assert _run_script(db, "--actor-email", admin.email, "--apply") == 2
    assert "is not an active Super Admin" in capsys.readouterr().out
