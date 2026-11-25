"""United Arab Emirates (ZP-AE-ENG-001) report templates: the three Draft
templates seeded by scripts/seed_statutory_report_templates.py, reading the
scalar payslip columns and the frozen ae_calculation_snapshot through
PAYSLIP_ITEM_JSON.

Pins: every catalogued path exists in a real engine result and is allowed;
every seeded field is catalogued, aggregatable where aggregated and fits the
column; employer amounts (pension gross / support / cash, end of service) never
sit in an employee component; Draft only and idempotent; no activation gate of
its own (maker-checker only); generation against an approved UAE run returns the
engine's own figures."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

AE_KEYS = {"AE-PAYROLL-REGISTER", "AE-PENSION-SUMMARY", "AE-GRATUITY-LIABILITY"}
EMPLOYEE_SIDE = ("deductions", "tax", "contributions")
SNAP = "ae_calculation_snapshot"


def _seed_module():
    from scripts import seed_statutory_report_templates as seed

    return seed


def _definitions():
    return _seed_module()._ae_templates()


def _all_fields():
    for key, t in _definitions().items():
        for component_key, _label, fields in t["components"]:
            for field in fields:
                yield key, t, component_key, field


def _is_employer_amount(kind, column):
    from app.modules.payroll import service

    if kind == "PAYSLIP_ITEM":
        return column.startswith("employer_")
    if kind == "PAYSLIP_ITEM_JSON":
        return "(Employer)" in service._REPORT_FIELD_ALLOWED_COLUMNS[kind][column][0]
    return False


def _engine_result(facts, **ctx):
    from app.modules.payroll.engine.countries import uae
    from tests.test_uae_calculator import ctx_for

    result = uae.calculate(ctx_for(facts, **ctx))
    return result, json.loads(json.dumps(result["ae_result"]))


EXPAT = {"nationality_category": "EXPATRIATE", "eos_regime": "TRADITIONAL", "work_pattern": "FULL_TIME"}
SAVINGS = {"nationality_category": "EXPATRIATE", "eos_regime": "SAVINGS_SCHEME", "work_pattern": "FULL_TIME",
           "savings_enrollment_date": "2025-01-01", "savings_enrollment_basic_wage": "8000"}
LAW57 = {"nationality_category": "UAE_NATIONAL", "pension_scheme": "GPSSA_LAW_57_2023",
         "pension_contribution_salary": "15000", "government_support_eligible": "YES", "work_pattern": "FULL_TIME"}


# ── catalog ──────────────────────────────────────────────────────────────────
def test_catalog_paths_are_well_formed_and_allowed():
    from app.modules.payroll import service

    catalog = service._PAYSLIP_ITEM_JSON_FIELD_CATALOG["AE"]
    allowed = service._REPORT_FIELD_ALLOWED_COLUMNS["PAYSLIP_ITEM_JSON"]
    for path, (label, field_type, aggregatable) in catalog.items():
        assert path.startswith(SNAP + "."), path
        assert len(path) <= 100, path
        assert field_type in ("currency", "text") and not (field_type == "text" and aggregatable), path
        assert path in allowed, path


@pytest.mark.parametrize("facts", [EXPAT, SAVINGS, LAW57], ids=["traditional", "savings", "law57"])
def test_every_catalogued_path_exists_in_a_real_result(facts):
    from app.modules.payroll import service

    conditional = {  # end-of-service keys only one regime writes
        "end_of_service.service_years", "end_of_service.entitlement_days", "end_of_service.entitlement",
        "end_of_service.accrual", "end_of_service.subscription", "end_of_service.unpaid_absence_days",
    }
    _result, snapshot = _engine_result(facts, basic=Decimal(8000), hra=Decimal(2000), gross=Decimal(10000))
    missing = []
    for path in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG["AE"]:
        node, rest = snapshot, path.partition(".")[2]
        for segment in rest.split("."):
            if not isinstance(node, dict) or segment not in node:
                node = missing
                break
            node = node[segment]
        if node is missing and rest not in conditional:
            missing.append(path)
    assert missing == []


def test_traditional_and_savings_together_cover_every_end_of_service_path():
    _r, traditional = _engine_result(EXPAT, basic=Decimal(8000), gross=Decimal(8000), hra=Decimal(0))
    _r, savings = _engine_result(SAVINGS, basic=Decimal(8000), gross=Decimal(8000), hra=Decimal(0))
    keys = set(traditional["end_of_service"]) | set(savings["end_of_service"])
    assert {"service_years", "entitlement_days", "entitlement", "accrual", "subscription",
            "unpaid_absence_days", "employer_amount"} <= keys


# ── seed definitions (static) ────────────────────────────────────────────────
def test_template_shapes():
    from app.modules.payroll import service

    definitions = _definitions()
    assert set(definitions) == AE_KEYS
    register = definitions["AE-PAYROLL-REGISTER"]
    assert register["report_type"] == "AE_PAYROLL_REGISTER" and register["scope"] == "AGGREGATE"
    assert [c[0] for c in register["components"]] == [
        "employer_info", "employee_info", "earnings", "deductions", "employer_contributions"]
    summary = definitions["AE-PENSION-SUMMARY"]
    amounts = [f for c in summary["components"] if c[0] != "employer_info" for f in c[2]]
    assert summary["scope"] == "AGGREGATE" and {f[5] for f in amounts} == {"SUM_RUN"}
    liability = definitions["AE-GRATUITY-LIABILITY"]
    assert liability["scope"] == "AGGREGATE"
    for t in definitions.values():
        assert t["report_type"].upper() not in service._REPORT_COMPONENTS_BY_TYPE
        for component in t["components"]:
            for field in component[2]:
                assert "tds" != field[4]                                      # no income tax in the UAE


def test_every_seeded_field_is_catalogued_aggregatable_and_fits():
    from app.modules.payroll import service

    default_components = {key for key, _ in service._DEFAULT_REPORT_COMPONENTS}
    problems = []
    for key, _t, component_key, (field_key, _label, _ftype, kind, column, aggregation) in _all_fields():
        catalog = service._REPORT_FIELD_ALLOWED_COLUMNS[kind]
        if column not in catalog:
            problems.append((key, field_key, "not catalogued"))
            continue
        if kind == "PAYSLIP_ITEM_JSON" and column not in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG["AE"]:
            problems.append((key, field_key, "path of another country"))
        if aggregation and not catalog[column][2]:
            problems.append((key, field_key, "aggregated but not aggregatable"))
        if len(column) > 100:
            problems.append((key, field_key, "too long"))
        if component_key not in default_components:
            problems.append((key, component_key, "unknown component"))
    assert problems == []


def test_employer_amounts_never_sit_in_an_employee_component_and_vice_versa():
    leaks = [(key, c, f[0]) for key, _t, c, f in _all_fields()
             if c in EMPLOYEE_SIDE and _is_employer_amount(f[3], f[4])]
    wrong = [(key, f[0]) for key, _t, c, f in _all_fields()
             if c == "employer_contributions" and not _is_employer_amount(f[3], f[4])]
    assert leaks == [] and wrong == []


# ── seeding through the validated service upserts ────────────────────────────
def test_seed_lands_draft_and_rerun_writes_nothing(db, capsys):
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponentField

    seed = _seed_module()
    assert seed.seed_united_arab_emirates in seed.SEED_COMING_SOON_COUNTRIES
    seed.seed_united_arab_emirates(db)
    rows = db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "AE").all()
    assert {r.template_key for r in rows} == AE_KEYS
    assert {r.status for r in rows} == {"Draft"}
    fields = db.query(ReportTemplateComponentField).count()
    capsys.readouterr()
    seed.seed_united_arab_emirates(db)
    assert " seeded " not in capsys.readouterr().out
    assert db.query(ReportTemplateComponentField).count() == fields
    assert db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "AE").count() == len(rows)


def test_no_country_activation_gate_only_maker_checker(db):
    from app.modules.payroll import jurisdiction_hooks

    assert not jurisdiction_hooks.has_module("AE")


# ── generation against an approved UAE run ──────────────────────────────────
def _user(db, email):
    from app.modules.auth.models import User, UserRole

    user = User(email=email, hashed_password="x", role=UserRole.PAYROLL_ADMIN, first_name="T", last_name="U")
    db.add(user)
    db.commit()
    return user


def _activate(db, template):
    from app.modules.payroll import service

    approver = _user(db, f"ae-approver-{template.id}@test.example.com")
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=None)
    return service.set_report_template_status(db, template.id, "Active", actor_id=None)


@pytest.fixture()
def ae_run(db, organization):
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem

    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="United Arab Emirates"))
    run = PayrollRun(organization_id=organization.id, period_label="2026-07", period_start=date(2026, 7, 1),
                     period_end=date(2026, 7, 31), pay_date=date(2026, 7, 31), status="Approved",
                     attendance_override_reason="TEST synthetic run - no attendance records")
    db.add(run)
    db.flush()
    people = {}
    for code, facts, basic, hra in (("AE-EXP", EXPAT, 8000, 2000), ("AE-NAT", LAW57, 12000, 3000)):
        result, snapshot = _engine_result(facts, basic=Decimal(basic), hra=Decimal(hra),
                                          gross=Decimal(basic + hra))
        emp = PayrollEmployee(organization_id=organization.id, employee_code=code, name=f"Test {code}",
                              country_code="AE", ctc=Decimal(basic + hra) * 12, basic=Decimal(basic),
                              hra=Decimal(hra), date_of_joining=date(2020, 1, 1), pay_frequency="Monthly",
                              compliance_fields=facts)
        db.add(emp)
        db.flush()
        gross = Decimal(basic + hra)
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
                           country_code="AE", employee_name=emp.name, basic_salary=Decimal(basic), hra=Decimal(hra),
                           gross_pay=gross, employee_pension=result["employee_pension"],
                           employer_pension=result["employer_pension"],
                           employer_payroll_tax=result["employer_payroll_tax"], tds=Decimal(0),
                           total_deductions=result["employee_pension"],
                           net_pay=gross - result["employee_pension"], ae_calculation_snapshot=snapshot))
        people[code] = (result, snapshot)
    db.commit()
    return SimpleNamespace(org=organization, run=run, people=people)


def _generate(db, ae_run, key):
    from app.modules.payroll import service
    from scripts.seed_statutory_report_templates import seed_united_arab_emirates

    templates = {t.template_key: t for t in seed_united_arab_emirates(db)}
    template = _activate(db, templates[key])
    return service.generate_report_from_template(db, ae_run.org.id, template.id, ae_run.run.id,
                                                 reporting_period=ae_run.run.period_label, actor_id=None)


def test_pension_summary_totals_are_the_engines_figures(db, ae_run):
    generated = _generate(db, ae_run, "AE-PENSION-SUMMARY")
    totals = generated.rendered_data["employer"]
    _r, nat = ae_run.people["AE-NAT"]
    assert totals["pension_salary"] == 15000.0
    assert totals["pension_employee"] == 1650.0                     # 11 % of 15,000
    assert totals["pension_employer_gross"] == 2250.0               # 15 %
    assert totals["government_support"] == 375.0                    # 2.5 %, state-funded
    assert totals["pension_employer_cash"] == 1875.0 == float(Decimal(nat["pension"]["employer_cash"]))


def test_gratuity_liability_rows_show_the_expatriates_position(db, ae_run):
    generated = _generate(db, ae_run, "AE-GRATUITY-LIABILITY")
    rows = {r["values"]["employee_name"]: r["values"] for r in generated.rendered_data["employees"]}
    expat = rows["Test AE-EXP"]
    _result, snapshot = ae_run.people["AE-EXP"]
    eos = snapshot["end_of_service"]
    assert expat["eos_regime"] == "TRADITIONAL"
    assert expat["gratuity_entitlement"] == float(Decimal(eos["entitlement"])) > 0
    assert expat["gratuity_accrual"] == float(Decimal(eos["accrual"])) > 0
    assert expat["end_of_service"] == float(Decimal(eos["employer_amount"]))
    assert expat["basic_wage"] == 8000.0 and expat["total_wage"] == 10000.0


def test_register_keeps_employer_cost_out_of_deductions(db, ae_run):
    generated = _generate(db, ae_run, "AE-PAYROLL-REGISTER")
    rows = {r["values"]["employee_name"]: r["values"] for r in generated.rendered_data["employees"]}
    national = rows["Test AE-NAT"]
    assert national["pension_employee"] == 1650.0 and national["pension_scheme"] == "GPSSA_LAW_57_2023"
    assert national["pension_employer_cash"] == 1875.0 and national["government_support"] == 375.0
    components = {c["componentKey"]: [f["fieldKey"] for f in c["fields"]]
                  for c in generated.rendered_data["templateSnapshot"]["components"]}
    assert "pension_employer_cash" in components["employer_contributions"]
    assert not {"pension_employer_cash", "government_support", "end_of_service"} & set(components["deductions"])
