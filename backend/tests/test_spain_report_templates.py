"""Spain (ZP-ES-ENG-001, docs/spain) Phase 8: the three Draft report templates
seeded by scripts/seed_statutory_report_templates.py, reading the scalar payslip
columns and the frozen es_calculation_snapshot through PAYSLIP_ITEM_JSON
(per-family lines and solidarity tranches via the keyed-list selector).

Pins: every catalogued path exists in a real engine result and is allowed;
every seeded field is catalogued, aggregatable where aggregated and fits the
column; employer amounts never sit in an employee component; Draft only and
idempotent; no activation gate of its own; generation against an approved
Spanish run returns the engine's own figures. IRPF is Phase 4 (AEAT document),
so a fixed stand-in replaces irpf.compute here, as in test_spain_calculator."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

ES_KEYS = {"ES-PAYROLL-REGISTER", "ES-SS-SUMMARY", "ES-IRPF-SUMMARY"}
EMPLOYEE_SIDE = ("deductions", "tax", "contributions")
SNAP = "es_calculation_snapshot"
STUB_IRPF = Decimal("500.00")


@pytest.fixture(autouse=True)
def stub_irpf(monkeypatch):
    from app.modules.payroll.engine.jurisdictions.spain import irpf as IRPF

    monkeypatch.setattr(IRPF, "compute", lambda **kw: {"version": IRPF.version_for(kw["pay_date"]),
                                                       "rate": Decimal("0.10"), "amount": STUB_IRPF, "stub": True})


def _seed_module():
    from scripts import seed_statutory_report_templates as seed

    return seed


def _definitions():
    return _seed_module()._es_templates()


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


def _engine_result(basic, facts=None, **kwargs):
    from app.modules.payroll.engine.countries import spain
    from tests.test_spain_calculator import ctx_for

    result = spain.calculate(ctx_for(facts, basic=basic, **kwargs))
    return result, json.loads(json.dumps(result["es_result"]))


# ── catalog ──────────────────────────────────────────────────────────────────
def test_catalog_paths_are_well_formed_and_allowed():
    from app.modules.payroll import service

    catalog = service._PAYSLIP_ITEM_JSON_FIELD_CATALOG["ES"]
    allowed = service._REPORT_FIELD_ALLOWED_COLUMNS["PAYSLIP_ITEM_JSON"]
    for path, (label, field_type, aggregatable) in catalog.items():
        assert path.startswith(SNAP + "."), path
        assert len(path) <= 100, path
        assert field_type in ("currency", "text") and not (field_type == "text" and aggregatable), path
        assert path in allowed, path


def test_every_catalogued_path_resolves_in_a_real_result():
    """€8,000 with overtime: every family, all three tranches and IRPF present."""
    from app.modules.payroll import service

    _result, snapshot = _engine_result(8000, overtime=200)
    missing = []
    for path in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG["ES"]:
        segments = [s for s in path.partition(".")[2].split(".") if s]
        if not service._report_json_walk(snapshot, segments):
            missing.append(path)
    assert missing == []


def test_per_family_selector_reads_the_engine_figures():
    from app.modules.payroll import service

    _result, snapshot = _engine_result(5500)
    value = lambda path: service._report_json_path_value(snapshot, path.split("."))  # noqa: E731
    assert value("social_security.lines[family=common_contingencies].employee") == "239.76"
    assert value("social_security.lines[family=fogasa].employer") == "10.20"
    assert value("solidarity.tranches[tranche=t1].amount") == "398.80"


# ── seed definitions (static) ────────────────────────────────────────────────
def test_template_shapes():
    from app.modules.payroll import service

    definitions = _definitions()
    assert set(definitions) == ES_KEYS
    register = definitions["ES-PAYROLL-REGISTER"]
    assert register["report_type"] == "ES_PAYROLL_REGISTER" and register["scope"] == "AGGREGATE"
    assert [c[0] for c in register["components"]] == [
        "employer_info", "employee_info", "earnings", "deductions", "employer_contributions"]
    for key in ("ES-SS-SUMMARY", "ES-IRPF-SUMMARY"):
        amounts = [f for c in definitions[key]["components"] if c[0] != "employer_info" for f in c[2]]
        assert definitions[key]["scope"] == "AGGREGATE" and {f[5] for f in amounts} == {"SUM_RUN"}, key
    for t in definitions.values():
        assert t["report_type"].upper() not in service._REPORT_COMPONENTS_BY_TYPE
    tax_fields = [f[4] for c in definitions["ES-IRPF-SUMMARY"]["components"] if c[0] == "tax" for f in c[2]]
    assert tax_fields == ["tds"]


def test_every_seeded_field_is_catalogued_aggregatable_and_fits():
    from app.modules.payroll import service

    default_components = {key for key, _ in service._DEFAULT_REPORT_COMPONENTS}
    problems = []
    for key, _t, component_key, (field_key, _label, _ftype, kind, column, aggregation) in _all_fields():
        catalog = service._REPORT_FIELD_ALLOWED_COLUMNS[kind]
        if column not in catalog:
            problems.append((key, field_key, "not catalogued"))
            continue
        if kind == "PAYSLIP_ITEM_JSON" and column not in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG["ES"]:
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
    assert seed.seed_spain in seed.SEED_COMING_SOON_COUNTRIES
    seed.seed_spain(db)
    rows = db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "ES").all()
    assert {r.template_key for r in rows} == ES_KEYS and {r.status for r in rows} == {"Draft"}
    fields = db.query(ReportTemplateComponentField).count()
    capsys.readouterr()
    seed.seed_spain(db)
    assert " seeded " not in capsys.readouterr().out
    assert db.query(ReportTemplateComponentField).count() == fields


def test_no_country_activation_gate_only_maker_checker():
    from app.modules.payroll import jurisdiction_hooks

    assert not jurisdiction_hooks.has_module("ES")


# ── generation against an approved Spanish run ───────────────────────────────
def _user(db, email):
    from app.modules.auth.models import User, UserRole

    user = User(email=email, hashed_password="x", role=UserRole.PAYROLL_ADMIN, first_name="T", last_name="U")
    db.add(user)
    db.commit()
    return user


def _activate(db, template):
    from app.modules.payroll import service

    approver = _user(db, f"es-approver-{template.id}@test.example.com")
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    service.set_report_template_status(db, template.id, "Published", actor_id=None)
    return service.set_report_template_status(db, template.id, "Active", actor_id=None)


@pytest.fixture()
def es_run(db, organization):
    from app.modules.payroll.models import CompanyComplianceDetails, PayrollEmployee, PayrollRun, PayslipItem

    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="Spain"))
    run = PayrollRun(organization_id=organization.id, period_label="2026-07", period_start=date(2026, 7, 1),
                     period_end=date(2026, 7, 31), pay_date=date(2026, 7, 31), status="Approved",
                     attendance_override_reason="TEST synthetic run - no attendance records")
    db.add(run)
    db.flush()
    people = {}
    for code, basic in (("ES-HIGH", 8000), ("ES-STD", 3000)):
        result, snapshot = _engine_result(basic)
        emp = PayrollEmployee(organization_id=organization.id, employee_code=code, name=f"Test {code}",
                              country_code="ES", ctc=Decimal(basic) * 12, basic=Decimal(basic), hra=Decimal(0),
                              date_of_joining=date(2024, 1, 1), pay_frequency="Monthly",
                              compliance_fields={"contract_type": "INDEFINITE", "contribution_group": "5",
                                                 "extra_pay_policy": "PRORATED_12"})
        db.add(emp)
        db.flush()
        deductions = result["social_security"] + result["tds"]
        db.add(PayslipItem(payroll_run_id=run.id, employee_id=emp.id, organization_id=organization.id,
                           country_code="ES", employee_name=emp.name, basic_salary=Decimal(basic), hra=Decimal(0),
                           gross_pay=Decimal(basic), social_security=result["social_security"], tds=result["tds"],
                           employer_social_security=result["employer_social_security"],
                           employer_occupational_hazard=result["employer_occupational_hazard"],
                           employer_payroll_tax=result["employer_payroll_tax"], total_deductions=deductions,
                           net_pay=Decimal(basic) - deductions, es_calculation_snapshot=snapshot))
        people[code] = (result, snapshot)
    db.commit()
    return SimpleNamespace(org=organization, run=run, people=people)


def _generate(db, es_run, key):
    from app.modules.payroll import service
    from scripts.seed_statutory_report_templates import seed_spain

    templates = {t.template_key: t for t in seed_spain(db)}
    template = _activate(db, templates[key])
    return service.generate_report_from_template(db, es_run.org.id, template.id, es_run.run.id,
                                                 reporting_period=es_run.run.period_label, actor_id=None)


def test_ss_summary_totals_are_the_engines_figures(db, es_run):
    generated = _generate(db, es_run, "ES-SS-SUMMARY")
    totals = generated.rendered_data["employer"]
    (high, high_snap), (std, std_snap) = es_run.people["ES-HIGH"], es_run.people["ES-STD"]
    assert totals["common_base"] == 5101.20 + 3000.00                            # the €8,000 base is capped
    assert totals["excess_over_maximum"] == 2898.80                              # only the €8,000 worker
    assert totals["solidarity_employee"] == 6.10 and totals["solidarity_employer"] == 30.37
    cc = lambda s: float(Decimal(next(l["employee"] for l in s["social_security"]["lines"]  # noqa: E731
                                      if l["family"] == "common_contingencies")))
    assert totals["common_contingencies_employee"] == round(cc(high_snap) + cc(std_snap), 2)
    assert totals["at_ep"] == float(high["employer_occupational_hazard"] + std["employer_occupational_hazard"])


def test_irpf_summary_totals_the_withholding(db, es_run):
    generated = _generate(db, es_run, "ES-IRPF-SUMMARY")
    totals = generated.rendered_data["employer"]
    assert totals["irpf"] == float(STUB_IRPF * 2)
    assert totals["gross_pay"] == 11000.0


def test_register_keeps_employer_cost_out_of_deductions(db, es_run):
    generated = _generate(db, es_run, "ES-PAYROLL-REGISTER")
    rows = {r["values"]["employee_name"]: r["values"] for r in generated.rendered_data["employees"]}
    high = rows["Test ES-HIGH"]
    result, _snap = es_run.people["ES-HIGH"]
    assert high["social_security"] == float(result["social_security"]) and high["irpf"] == float(STUB_IRPF)
    assert high["employer_social_security"] == float(result["employer_social_security"])
    assert high["contract_type"] == "INDEFINITE" and str(high["contribution_group"]) == "5"
    components = {c["componentKey"]: [f["fieldKey"] for f in c["fields"]]
                  for c in generated.rendered_data["templateSnapshot"]["components"]}
    assert not {"employer_social_security", "at_ep", "short_contract_surcharge"} & set(components["deductions"])
