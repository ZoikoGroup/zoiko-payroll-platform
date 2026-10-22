"""Netherlands (ZP-NL-ENG-001 §16) report templates — the five Draft templates
seeded by scripts/seed_statutory_report_templates.py, read from the frozen
nl_calculation_snapshot through PAYSLIP_ITEM_JSON.

Pins: Draft only and idempotent; employer premiums never under deductions
(NL-048); no BSN mapped (NL-051); every mapped path exists in a real NL
result; and generation against a committed Dutch run returns the engine's
own figures — including run totals, which used to sum to 0 because the NL
snapshot stores amounts as decimal strings."""

from decimal import Decimal

from app.modules.payroll import service
from tests.test_netherlands_service_integration import _approve, _run, nlx  # noqa: F401

NL_KEYS = {"NL-PAYROLL-REGISTER", "NL-LOONSTROOK", "NL-EMPLOYER-COST", "NL-LOONAANGIFTE-SUMMARY", "NL-JOURNAL"}
EMPLOYER_PATHS = ("employeeInsurance.", "zvw.employerLevy", "totals.employerPremiums", "totals.pensionEmployer",
                  "totals.employerCost")


def _seed(db):
    from scripts.seed_statutory_report_templates import seed_netherlands

    return seed_netherlands(db)


def _templates(db):
    from app.modules.payroll.models import ReportTemplate

    return {t.template_key: t for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "NL")}


def _fields(db, template):
    from app.modules.payroll.models import ReportTemplateComponent, ReportTemplateComponentField

    out = []
    for comp in db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == template.id):
        for f in db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.component_id == comp.id):
            out.append((comp.component_key, f))
    return out


def _user(db, email):
    from app.modules.auth.models import User, UserRole

    user = User(email=email, hashed_password="x", role=UserRole.PAYROLL_ADMIN, first_name="T", last_name="U")
    db.add(user)
    db.commit()
    return user


def _activate(db, template):
    approver = _user(db, f"nl-approver-{template.id}@test.example.com")
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=None)
    return service.set_report_template_status(db, template.id, "Active", actor_id=None)


def _committed_run(db, nlx):
    run = _run(db, nlx.org, 3)
    service.generate_payslips_for_run(db, run, nlx.org.id)
    _approve(db, run, nlx.org)
    return run


def test_five_draft_templates_seeded_and_idempotent(db):
    from app.modules.payroll.models import ReportTemplateComponentField

    _seed(db)
    templates = _templates(db)
    assert set(templates) == NL_KEYS
    assert {t.status for t in templates.values()} == {"Draft"}
    assert {t.report_type for t in templates.values()} == {k.replace("-", "_") for k in NL_KEYS}
    first = (len(templates), db.query(ReportTemplateComponentField).count())
    _seed(db)
    assert (len(_templates(db)), db.query(ReportTemplateComponentField).count()) == first


def test_employer_premiums_are_never_deductions(db):
    _seed(db)
    for template in _templates(db).values():
        for component, field in _fields(db, template):
            path = (field.source_column or "").removeprefix("nl_calculation_snapshot.")
            if component in ("deductions", "earnings"):
                assert not path.startswith(EMPLOYER_PATHS), (template.template_key, component, field.field_key)


def test_no_bsn_is_mapped(db):
    _seed(db)
    for template in _templates(db).values():
        for _component, field in _fields(db, template):
            assert "bsn" not in (field.source_column or "").lower() and "bsn" not in field.field_key.lower()


def test_every_mapped_path_exists_in_a_real_nl_result(db):
    from tests.test_netherlands_engine import _nl

    snapshot = {"nl_calculation_snapshot": _nl()["nl_result"]}
    _seed(db)
    for template in _templates(db).values():
        for _component, field in _fields(db, template):
            if field.data_source_kind != "PAYSLIP_ITEM_JSON":
                continue
            node = snapshot
            for part in field.source_column.split("."):
                assert isinstance(node, dict) and part in node, (template.template_key, field.source_column)
                node = node[part]


def test_employer_cost_totals_are_the_engines_figures(db, nlx):
    from app.modules.payroll.models import PayslipItem

    run = _committed_run(db, nlx)
    snap = db.query(PayslipItem).filter(PayslipItem.payroll_run_id == run.id).one().nl_calculation_snapshot
    _seed(db)
    template = _activate(db, _templates(db)["NL-EMPLOYER-COST"])
    generated = service.generate_report_from_template(db, nlx.org.id, template.id, run.id,
                                                      reporting_period=run.period_label, actor_id=None)
    header = generated.rendered_data["employer"]
    expected = {"awf": snap["employeeInsurance"]["awf"], "aof": snap["employeeInsurance"]["aof"],
                "wko": snap["employeeInsurance"]["wko"], "whk": snap["employeeInsurance"]["whk"],
                "zvw_employer": snap["zvw"]["employerLevy"], "employer_cost": snap["totals"]["employerCost"]}
    for key, value in expected.items():
        assert header[key] == float(Decimal(value)), (key, header[key], value)
    assert header["awf"] == 137.0 and header["zvw_employer"] == 305.0      # F2, not 0 from string summing


def test_loonstrook_shows_hours_minimum_wage_and_separate_employer_cost(db, nlx):
    run = _committed_run(db, nlx)
    _seed(db)
    template = _activate(db, _templates(db)["NL-LOONSTROOK"])
    generated = service.generate_report_from_template(db, nlx.org.id, template.id, run.id,
                                                      reporting_period=run.period_label, actor_id=None)
    rows = generated.rendered_data["employees"]
    assert len(rows) == 1
    values = rows[0]["values"]
    assert values["wage_tax"] == 1325.08 and values["net_pay"] == 3674.92
    assert values["minimum_wage_hourly"] == 14.71 and values["hours"] == "173.33"
    assert values["contract_term"] == "INDEFINITE"
    assert values["awf"] == 137.0                                           # in the employer-cost component
    components = {c["componentKey"]: [f["fieldKey"] for f in c["fields"]]
                  for c in generated.rendered_data["templateSnapshot"]["components"]}
    assert "awf" in components["employer_cost"] and "awf" not in components["deductions"]


def test_text_that_looks_numeric_is_never_summed():
    assert service._report_json_number("1325.08", "currency") == Decimal("1325.08")
    assert service._report_json_number("1234567", "text") is None
    assert service._report_json_number(True, "currency") is None
    assert service._report_json_number("n/a", "currency") is None
    assert service._report_json_number(12.5, "text") == Decimal("12.5")    # real numbers keep the old behaviour
