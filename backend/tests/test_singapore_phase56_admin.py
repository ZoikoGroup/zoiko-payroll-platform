"""
tests/test_singapore_phase56_admin.py
-------------------------------------
Singapore Phase 5.6 — Super Admin administration layer:

  - GET /super-admin/compliance/singapore/pwm-schedules (read-only,
    paginated, filtered, deterministic, tenant-independent, bounded queries);
  - GET /super-admin/compliance/singapore/statutory-summary (sections from
    persisted rows only, NOT_CONFIGURED when absent, Draft values never
    presented as Active, tenant-independent);
  - the Singapore report-template set (11 templates, classification, no
    official-certification claim, Draft, seed idempotency, lifecycle
    preserved on re-run), the dedicated-generator guard and the
    employer_eht field-catalog fix;
  - RBAC: the real dependency functions and route dependant trees (this
    codebase's convention — see test_germany_rbac_hardening.py).

Every app.* import is lazy (inside tests) — see tests/_db_safety.py.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

SUMMARY = "/api/super-admin/compliance/singapore/statutory-summary"
PWM = "/api/super-admin/compliance/singapore/pwm-schedules"
STATUTORY_SECTIONS = ("cpf", "sdl", "shg", "fwl", "lqs", "pwm", "iras", "ir21", "ezpay")


# ── helpers ────────────────────────────────────────────────────────────────

def _routes(path):
    from app.main import app

    return [r for r in app.routes if getattr(r, "path", None) == path]


def _dependency_calls(route):
    calls = set()

    def walk(dep):
        for d in dep.dependencies:
            calls.add(d.call)
            walk(d)
    walk(route.dependant)
    return calls


def _source(db, title="MOM PWM overtime table"):
    from app.modules.payroll.models import SourceArtifact

    s = SourceArtifact(agency="MOM", title=title, source_url="https://www.mom.gov.sg/example",
                       checksum_sha256="a" * 64)
    db.add(s)
    db.commit()
    return s


def _pwm_rows(db, source):
    """Small synthetic schedule: 2 sectors × 2 levels × 2 windows × hours 0–3."""
    from app.modules.payroll.models import SgpPwmOvertimeSchedule

    windows = ((date(2025, 7, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2027, 6, 30)))
    rows = []
    for sector, group in (("RETAIL", "ALL"), ("FOOD_SERVICES", "A_QUICK")):
        for level in ("LEVEL_1", "LEVEL_2"):
            for w, (eff_from, eff_to) in enumerate(windows):
                for hours in range(4):
                    rows.append(SgpPwmOvertimeSchedule(
                        jurisdiction_country="SG", sector=sector, occupation_group=group, job_level=level,
                        role_label=f"{sector.title()} {level}", effective_from=eff_from, effective_to=eff_to,
                        overtime_hours=hours, required_gross=Decimal("2000") + 10 * hours + 100 * w,
                        source_document_id=source.id, source_sha256=source.checksum_sha256,
                        retrieved_at=datetime(2026, 9, 25, 9, tzinfo=timezone.utc),
                        status="Active" if w else "Superseded"))
    db.add_all(rows)
    db.commit()
    return len(rows)


def _list(db, **kw):
    from app.modules.payroll import service

    return service.list_sg_pwm_schedules(db, **kw)


def _tenant_payroll_data(db, organization):
    from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

    emp = PayrollEmployee(organization_id=organization.id, employee_code="SG56", name="Tenant Worker",
                          country_code="SG", compliance_fields={"pwm_sector": "RETAIL"})
    db.add(emp)
    db.flush()
    run = PayrollRun(organization_id=organization.id, run_code="SG56-RUN", period_label="Jun 2026",
                     period_start=date(2026, 6, 1), period_end=date(2026, 6, 30), pay_date=date(2026, 6, 30))
    db.add(run)
    db.flush()
    db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
                       employee_name="Tenant Worker", country_code="SG", gross_pay=Decimal("1500")))
    db.commit()


def _seed_templates(db, monkeypatch):
    import scripts.seed_statutory_report_templates as seed

    monkeypatch.setattr(seed, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    seed.run()


# ── RBAC ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [SUMMARY, PWM])
def test_new_routes_are_get_only_and_gated_by_the_real_super_admin_dependency(path):
    from app.core.dependencies import get_current_super_admin

    routes = _routes(path)
    assert routes, path
    assert {m for r in routes for m in r.methods} <= {"GET", "HEAD"}          # no mutation endpoint exists
    for r in routes:
        assert get_current_super_admin in _dependency_calls(r)


@pytest.mark.parametrize("role,org_id", [("org_admin", 1), ("payroll_admin", 1), ("employee", 1),
                                         ("super_admin", 7)])
def test_super_admin_dependency_denies_every_other_principal(role, org_id):
    from app.core.dependencies import get_current_super_admin
    from app.core.exceptions import ForbiddenException

    with pytest.raises(ForbiddenException):
        get_current_super_admin(SimpleNamespace(role=role, organization_id=org_id))


def test_super_admin_dependency_allows_platform_super_admin():
    from app.core.dependencies import get_current_super_admin

    user = SimpleNamespace(role="super_admin", organization_id=None)
    assert get_current_super_admin(user) is user


def test_tenant_routers_expose_no_pwm_or_summary_mutation():
    """No payroll (tenant) route can write the global PWM table or the SG
    summary: no tenant path mentions them at all."""
    from app.main import app

    tenant = [r for r in app.routes if str(getattr(r, "path", "")).startswith("/api/payroll")]
    assert not [r.path for r in tenant if "pwm-schedule" in r.path or "statutory-summary" in r.path]


# ── PWM schedules API ──────────────────────────────────────────────────────

def test_pwm_pagination_is_complete_disjoint_and_deterministic(db):
    total = _pwm_rows(db, _source(db))
    first = _list(db, skip=0, limit=10)
    assert first["total"] == total and len(first["items"]) == 10 and first["readOnly"] is True
    seen = []
    for skip in range(0, total, 10):
        page = _list(db, skip=skip, limit=10)
        assert page["total"] == total
        seen += [i["id"] for i in page["items"]]
    assert len(seen) == len(set(seen)) == total                                 # every row once, no overlap
    assert _list(db, skip=0, limit=10)["items"] == first["items"]              # repeatable
    keys = [(i["sector"], i["occupationGroup"], i["jobLevel"], i["effectiveFrom"], i["overtimeHours"], i["id"])
            for i in _list(db, skip=0, limit=200)["items"]]
    assert keys == sorted(keys)                                                 # documented total order


def test_pwm_filters(db):
    _pwm_rows(db, _source(db))
    assert {i["sector"] for i in _list(db, sector="RETAIL")["items"]} == {"RETAIL"}
    assert _list(db, sector="RETAIL")["total"] == 16
    assert _list(db, occupation_group="A_QUICK")["total"] == 16
    assert _list(db, job_level="LEVEL_2", sector="FOOD_SERVICES")["total"] == 8
    assert _list(db, overtime_hours=3)["total"] == 8
    assert {i["overtimeHours"] for i in _list(db, overtime_hours=3)["items"]} == {3}
    on = _list(db, effective_on=date(2026, 7, 1), limit=200)["items"]
    assert len(on) == 16 and {i["effectiveFrom"] for i in on} == {"2026-07-01"}
    assert _list(db, effective_on=date(2026, 6, 30))["total"] == 16            # window boundary is inclusive
    assert _list(db, effective_on=date(2028, 1, 1))["total"] == 0
    assert _list(db, effective_from=date(2026, 7, 1))["total"] == 16
    assert _list(db, effective_to=date(2026, 6, 30))["total"] == 16
    assert _list(db, status="Superseded")["total"] == 16
    assert _list(db, search="retail")["total"] == 16
    assert _list(db, sector="NOT_A_SECTOR")["total"] == 0


def test_pwm_row_shape_carries_source_evidence(db):
    src = _source(db, title="MOM retail PWM overtime")
    _pwm_rows(db, src)
    row = _list(db, sector="RETAIL", job_level="LEVEL_1", overtime_hours=2, effective_on=date(2026, 7, 1))["items"]
    assert len(row) == 1
    r = row[0]
    assert r["requiredGross"] == "2120.00" and isinstance(r["requiredGross"], str)   # Decimal, never float
    assert (r["sourceDocumentId"], r["sourceTitle"], r["sourceSha256"]) == (src.id, "MOM retail PWM overtime", "a" * 64)
    assert r["jurisdiction"] == "SG" and r["retrievedAt"].startswith("2026-09-25")
    assert set(r) >= {"id", "sector", "occupationGroup", "jobLevel", "roleLabel", "effectiveFrom", "effectiveTo",
                      "overtimeHours", "status"}


def test_pwm_list_uses_a_bounded_number_of_queries(db):
    from sqlalchemy import event

    _pwm_rows(db, _source(db))
    statements = []
    engine = db.get_bind()
    listener = lambda *a: statements.append(a[2])  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        _list(db, skip=0, limit=200)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert len(statements) == 2                                                # one COUNT + one page SELECT (no N+1)
    assert "LIMIT" in statements[1].upper()


def test_pwm_is_tenant_independent(db, organization):
    _pwm_rows(db, _source(db))
    before = _list(db, limit=200)
    _tenant_payroll_data(db, organization)
    after = _list(db, limit=200)
    assert before == after
    assert not any("organization" in k.lower() for k in after["items"][0])


def test_pwm_real_seed_counts(db):
    """The seeded MOM tables: 6,132 rows = 84 schedules × 73 hours (0–72)."""
    from scripts.seed_singapore_canonical_pack import seed_singapore

    seed_singapore(db)
    db.commit()
    assert _list(db, limit=1)["total"] == 6132
    pwm = next(s for s in _summary(db)["sections"] if s["key"] == "pwm")["values"]["overtimeSchedule"]
    assert (pwm["totalRows"], pwm["schedules"], pwm["overtimeHoursMin"], pwm["overtimeHoursMax"]) == (6132, 84, 0, 72)


# ── Statutory summary ──────────────────────────────────────────────────────

def _summary(db, as_of=date(2026, 9, 25)):
    from app.modules.payroll import service

    return service.get_sg_statutory_summary(db, as_of)


def _section(summary, key):
    return next(s for s in summary["sections"] if s["key"] == key)


def test_summary_returns_every_section_in_order(db):
    keys = [s["key"] for s in _summary(db)["sections"]]
    assert keys == ["pack"] + list(STATUTORY_SECTIONS) + ["reportTemplates", "readiness"]      # 5.7: + Statutory Pack
    for s in _summary(db)["sections"]:
        assert {"configured", "status", "effectiveDate", "values", "sources", "notes"} <= set(s)


def test_summary_empty_database_fabricates_nothing(db):
    summary = _summary(db)
    assert summary["activePack"] is None and summary["valuesFromPack"] is None
    for key in STATUTORY_SECTIONS:
        s = _section(summary, key)
        assert s["status"] == "NOT_CONFIGURED" and s["configured"] is False, key
        assert all(v is None for v in s["values"].values()), key                # no default value anywhere
    templates = _section(summary, "reportTemplates")
    assert templates["values"]["present"] == 0 and len(templates["missing"]) == 11
    readiness = _section(summary, "readiness")
    assert readiness["status"] == "BLOCKED"
    assert "not a CPF Board, IRAS, MOM or PDPC" in summary["certification"]


def test_summary_draft_pack_values_are_shown_but_never_as_active(db):
    from scripts.seed_singapore_canonical_pack import RATES

    seeded = {k: kw for k, _l, _s, kw in RATES}
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    summary = _summary(db)
    assert summary["activePack"] is None and summary["valuesFromActivePack"] is False
    assert (summary["valuesFromPack"]["version"], summary["valuesFromPack"]["status"]) == (pack.version, "Draft")
    active_item = next(i for i in _section(summary, "readiness")["values"]["items"] if i["key"] == "active_pack")
    assert active_item["status"] == "BLOCKED" and "not in force" in active_item["evidence"]
    cpf = _section(summary, "cpf")
    assert (cpf["status"], cpf["configurationStatus"], cpf["inForce"]) == ("BLOCKED", "CONFIGURED", False)   # 5.7: Draft not in force
    assert Decimal(cpf["values"]["owCeilingMonthly"]["flatAmount"]) == Decimal(seeded["cpf_ow_ceiling_monthly"]["flat_amount"])
    assert cpf["values"]["rateBands"] == 7 * 5 * 4
    assert cpf["sources"] and all(not s.get("missing") for s in cpf["sources"])
    assert Decimal(_section(summary, "sdl")["values"]["rate"]["employerRatePct"]) == Decimal(seeded["sdl"]["employer_rate_pct"])
    shg = _section(summary, "shg")["values"]
    assert shg["fundCount"] == 4 and shg["funds"] == sorted(shg["funds"])
    lqs = _section(summary, "lqs")["values"]["fullTimeMonthly"]
    assert Decimal(lqs["flatAmount"]) == Decimal("1800") and lqs["effectiveFrom"] == "2026-07-01"   # point-in-time row
    early = _section(_summary(db, date(2026, 3, 1)), "lqs")["values"]["fullTimeMonthly"]
    assert Decimal(early["flatAmount"]) == Decimal("1600")
    fwl = _section(summary, "fwl")
    assert fwl["values"]["sPassEndDayBasis"] is None and fwl["notes"]          # unseeded row reported, not invented
    assert _section(summary, "iras")["values"]["aisFilingCalendar"]["dueDate"] == "2027-03-01"


def test_summary_prefers_the_active_pack(db):
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    pack.status = "Active"
    db.commit()
    summary = _summary(db)
    assert summary["activePack"]["id"] == pack.id and summary["valuesFromActivePack"] is True
    active_item = next(i for i in _section(summary, "readiness")["values"]["items"] if i["key"] == "active_pack")
    assert active_item["status"] == "PASS"
    assert _section(summary, "readiness")["status"] == "BLOCKED"               # G1–G8 still unevidenced


def test_summary_is_tenant_independent(db, organization):
    from scripts.seed_singapore_canonical_pack import seed_singapore

    seed_singapore(db)
    db.commit()
    before = _summary(db)
    _tenant_payroll_data(db, organization)
    assert _summary(db) == before
    assert "Tenant Worker" not in repr(before) and "organizationId" not in repr(before)


# ── Report templates ───────────────────────────────────────────────────────

def test_catalog_has_eleven_unique_uncertified_templates():
    from app.modules.payroll.engine.jurisdictions.singapore.statutory_summary import (
        SG_DEDICATED_GENERATOR_REPORT_TYPES, SG_REPORT_TEMPLATES, template_catalog_entry,
    )

    keys = [t[0] for t in SG_REPORT_TEMPLATES]
    assert len(keys) == len(set(keys)) == 11 and all(k.startswith("SG-") for k in keys)
    assert len({t[1] for t in SG_REPORT_TEMPLATES}) == 11
    assert {"SG-PAYROLL-REGISTER", "SG-PAYROLL-SUMMARY", "SG-CPF-CONTRIBUTION", "SG-SHG-MONTHLY", "SG-FWL-MONTHLY",
            "SG-PWM-COMPLIANCE", "SG-IR21-REGISTER", "SG-LQS-COMPLIANCE", "SG-IR8A", "SG-SDL-MONTHLY",
            "SG-CPF-EZPAY"} == set(keys)
    for key in keys:
        e = template_catalog_entry(key)
        assert e["officialCertification"] is False
        assert e["classification"] in ("EXPORT_READY", "SUBMISSION_SUPPORT", "INTERNAL_REPORT", "STATUTORY_WORKSPACE")
        assert "not approved or certified" in e["description"]
        assert "certified by" not in e["description"].replace("not approved or certified by", "")
    assert SG_DEDICATED_GENERATOR_REPORT_TYPES == {"SG_PWM_COMPLIANCE", "SG_IR21_REGISTER", "SG_LQS_COMPLIANCE"}


def test_seed_creates_all_eleven_as_draft_and_is_idempotent(db, monkeypatch):
    from sqlalchemy import func
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponent, ReportTemplateComponentField

    _seed_templates(db, monkeypatch)
    sg = db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "SG").all()
    assert len(sg) == 11 and {t.status for t in sg} == {"Draft"}
    assert all(t.jurisdiction_state is None and t.reporting_year == "2026" for t in sg)
    counts = (db.query(func.count(ReportTemplate.id)).scalar(), db.query(func.count(ReportTemplateComponent.id)).scalar(),
              db.query(func.count(ReportTemplateComponentField.id)).scalar())
    snapshot = {t.id: (t.template_key, t.version, t.status, t.name, t.description) for t in db.query(ReportTemplate)}
    _seed_templates(db, monkeypatch)
    assert (db.query(func.count(ReportTemplate.id)).scalar(), db.query(func.count(ReportTemplateComponent.id)).scalar(),
            db.query(func.count(ReportTemplateComponentField.id)).scalar()) == counts   # 0 inserted on re-run
    assert {t.id: (t.template_key, t.version, t.status, t.name, t.description) for t in db.query(ReportTemplate)} == snapshot
    dup = db.query(ReportTemplate.template_key, ReportTemplate.version).group_by(
        ReportTemplate.template_key, ReportTemplate.version).having(func.count() > 1).all()
    assert dup == []
    new = {t.template_key: t for t in sg if t.template_key not in ("SG-IR8A", "SG-SDL-MONTHLY", "SG-CPF-EZPAY")}
    assert all(t.description.startswith("[") and t.effective_from == date(2026, 1, 1) and t.source_document_id is None
               for t in new.values())


def test_seed_rerun_preserves_a_template_that_left_draft(db, monkeypatch):
    from app.modules.payroll.models import ReportTemplate

    _seed_templates(db, monkeypatch)
    row = db.query(ReportTemplate).filter(ReportTemplate.template_key == "SG-PAYROLL-REGISTER").one()
    row.status, row.approved_by_id = "Approved", None
    db.commit()
    _seed_templates(db, monkeypatch)
    db.refresh(row)
    assert row.status == "Approved"                                            # previously demoted to Draft


def test_seeded_fields_are_real_columns_with_employer_eht(db, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponent, ReportTemplateComponentField

    _seed_templates(db, monkeypatch)
    fields = (db.query(ReportTemplateComponentField.source_column, ReportTemplateComponentField.data_source_kind)
              .join(ReportTemplateComponent, ReportTemplateComponent.id == ReportTemplateComponentField.component_id)
              .join(ReportTemplate, ReportTemplate.id == ReportTemplateComponent.report_template_id)
              .filter(ReportTemplate.template_key == "SG-FWL-MONTHLY").all())
    assert ("employer_eht", "PAYSLIP_ITEM") in fields
    # The SG data-field picker listed employer_eht, which the catalog lacked (KeyError → 500).
    picker = service.get_available_report_data_fields("SG")
    assert any(f["key"] == "employer_eht" and f["label"] == "Foreign Worker Levy (Employer)" for f in picker)


def test_summary_reports_template_presence_and_classification(db, monkeypatch):
    _seed_templates(db, monkeypatch)
    section = _section(_summary(db), "reportTemplates")
    assert section["status"] == "CONFIGURED" and section["values"]["present"] == 11
    rows = {r["templateKey"]: r for r in section["values"]["templates"]}
    assert rows["SG-PWM-COMPLIANCE"]["classification"] == "STATUTORY_WORKSPACE"
    assert rows["SG-PWM-COMPLIANCE"]["generator"] == "POST /api/payroll/singapore/reports/pwm-compliance"
    assert rows["SG-IR8A"]["classification"] == "EXPORT_READY"
    assert all(r["status"] == "Draft" and r["officialCertification"] is False for r in rows.values())
    assert section["values"]["unexpectedTemplateKeys"] == []


def test_generic_generator_refuses_structure_only_sg_templates(db, organization):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate

    t = ReportTemplate(template_key="SG-PWM-COMPLIANCE", name="PWM", report_type="SG_PWM_COMPLIANCE",
                       jurisdiction_country="SG", reporting_year="2026", version="1.0", status="Active",
                       document_scope="AGGREGATE")
    db.add(t)
    db.commit()
    with pytest.raises(BadRequestException, match="dedicated Singapore generator"):
        service.generate_report_from_template(db, organization.id, t.id, payroll_run_id=999999)


# ── Phase 5.6 (re-run) gap closure: schemas, role_label, lifecycle counts,
#    provenance, determinism, listing, IDOR ────────────────────────────────

@pytest.mark.parametrize("path,schema", [(SUMMARY, "SgpStatutoryAdminSummaryResponse"), (PWM, "SgpPwmSchedulePageResponse")])
def test_routes_declare_typed_response_schemas(path, schema):
    from app.modules.super_admin import schemas

    assert _routes(path)[0].response_model is getattr(schemas, schema)


def test_responses_validate_against_their_schemas(db):
    from app.modules.super_admin.schemas import SgpPwmSchedulePageResponse, SgpStatutoryAdminSummaryResponse

    _pwm_rows(db, _source(db))
    page = SgpPwmSchedulePageResponse.model_validate(_list(db, limit=5))
    assert page.total == 32 and len(page.items) == 5 and page.readOnly is True
    SgpStatutoryAdminSummaryResponse.model_validate(_summary(db))


def test_pwm_role_label_filter_is_exact(db):
    _pwm_rows(db, _source(db))
    rows = _list(db, role_label="Retail LEVEL_1", limit=200)
    assert rows["total"] == 8 and {i["roleLabel"] for i in rows["items"]} == {"Retail LEVEL_1"}
    assert _list(db, role_label="Retail")["total"] == 0                        # exact, not a partial match


def test_summary_is_deterministic_and_reports_pwm_provenance(db):
    from scripts.seed_singapore_canonical_pack import RETRIEVED_AT_PHASE53, seed_singapore

    seed_singapore(db)
    db.commit()
    first, second = _summary(db), _summary(db)
    assert first == second
    pwm = _section(first, "pwm")["values"]["overtimeSchedule"]
    assert pwm["latestRetrievedAt"].startswith(RETRIEVED_AT_PHASE53.date().isoformat())   # from the rows, not a constant
    assert pwm["lastSeededAt"] is not None


def test_template_status_counts_cover_every_lifecycle_state(db, monkeypatch):
    from app.modules.payroll.engine.jurisdictions.singapore.statutory_summary import TEMPLATE_STATUSES
    from app.modules.payroll.models import ReportTemplate

    _seed_templates(db, monkeypatch)
    row = db.query(ReportTemplate).filter(ReportTemplate.template_key == "SG-FWL-MONTHLY").one()
    row.status = "Superseded"
    db.commit()
    values = _section(_summary(db), "reportTemplates")["values"]
    assert set(values["statusCounts"]) == set(TEMPLATE_STATUSES)
    assert values["statusCounts"]["Draft"] == 10 and values["statusCounts"]["Superseded"] == 1
    assert sum(values["statusCounts"].values()) == values["present"] == 11
    assert all(r["description"] for r in values["templates"] if r["templateKey"] not in ("SG-IR8A", "SG-SDL-MONTHLY", "SG-CPF-EZPAY"))


def test_template_listing_and_non_sg_templates_untouched_by_reseed(db, monkeypatch):
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplate

    _seed_templates(db, monkeypatch)
    listed = service.list_report_templates(db, country="SG")
    assert len(listed) == 11 and {t.jurisdiction_country for t in listed} == {"SG"}
    assert all(t.version == "1.0" and t.status == "Draft" for t in listed)
    assert all(t.effective_from == date(2026, 1, 1) for t in listed
               if t.template_key not in ("SG-IR8A", "SG-SDL-MONTHLY", "SG-CPF-EZPAY"))
    snapshot = lambda: {t.id: (t.template_key, t.version, t.status, t.name, t.description, t.updated_at)  # noqa: E731
                        for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country != "SG")}
    before = snapshot()
    assert before                                                              # other countries are seeded too
    _seed_templates(db, monkeypatch)
    after = snapshot()
    assert {k: v[:5] for k, v in after.items()} == {k: v[:5] for k, v in before.items()}   # same rows, same content


def test_summary_and_template_listing_carry_no_tenant_data(db, organization, monkeypatch):
    _seed_templates(db, monkeypatch)
    _tenant_payroll_data(db, organization)
    summary = _summary(db)
    text = repr(summary)
    assert "Tenant Worker" not in text and "SG56" not in text and "SG56-RUN" not in text

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)
    assert not {k for k in keys(summary) if "organization" in k.lower() or k in ("employeeId", "payslipId", "runId")}


def test_ir21_case_idor_is_refused_across_tenants(db, organization):
    from app.core.exceptions import NotFoundException
    from app.modules.payroll import service
    from app.modules.payroll.models import SgpIr21Case
    from app.modules.organizations.models import Organization

    other = Organization(organization_name="Org B", organization_code="ORGB56")
    db.add(other)
    db.commit()
    from app.modules.payroll.models import PayrollEmployee

    emp = PayrollEmployee(organization_id=other.id, employee_code="B1", name="B", country_code="SG")
    db.add(emp)
    db.commit()
    case = SgpIr21Case(organization_id=other.id, employee_id=emp.id, trigger_type="CESSATION",
                       trigger_date=date(2026, 12, 31), aware_date=date(2026, 10, 1), file_by_date=date(2026, 11, 30))
    db.add(case)
    db.commit()
    with pytest.raises(NotFoundException):
        service.get_sg_ir21_case(db, organization.id, case.id)                 # Tenant A asking for Tenant B's case
    assert service.list_sg_ir21_cases(db, organization.id) == []
