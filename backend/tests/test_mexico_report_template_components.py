"""Mexico report templates — the component catalog (2026-11-18).

A Mexico report built by a dedicated generator (mexico_report_service.MX_REPORT_SPECS)
or rendered from the stamped CFDI has no components. Its component catalog is
empty, so the Components tab offers nothing and a component cannot be added. Before
this change it fell back to the generic default list (Earnings / Tax / YTD ...).
Snapshot-field reports keep their catalog. Other countries are unchanged.
SYNTHETIC data only."""

import pytest


def test_dedicated_and_receipt_types_are_exactly_the_mexico_service_built_reports():
    from app.modules.payroll import mexico_report_service as R
    from app.modules.payroll import service

    assert set(service.MX_DEDICATED_GENERATOR_REPORT_TYPES) == set(R.MX_REPORT_SPECS) | {"MX_CFDI_RECEIPT"}


def test_dedicated_and_receipt_types_offer_no_component():
    from app.modules.payroll import service

    for report_type in service.MX_DEDICATED_GENERATOR_REPORT_TYPES:
        assert service.get_available_report_components(report_type) == [], report_type
        assert service.get_available_report_components(report_type.lower()) == [], report_type


def test_every_snapshot_field_type_keeps_its_own_catalog_not_the_generic_one():
    from app.modules.payroll import mexico_report_service as R
    from app.modules.payroll import service

    generic = [{"key": k, "label": lbl} for k, lbl in service._DEFAULT_REPORT_COMPONENTS]
    engine = [t for t in R.MX_REPORT_GATES if t not in service.MX_DEDICATED_GENERATOR_REPORT_TYPES]
    assert {"MX_REGISTER", "MX_EMPLOYER_COST", "MX_AGUINALDO", "MX_FINIQUITO", "MX_ANNUAL_ISR"} <= set(engine)
    for report_type in engine:
        options = service.get_available_report_components(report_type)
        assert options and options != generic, report_type
    assert {o["key"] for o in service.get_available_report_components("MX_AGUINALDO")} == {
        "employer_info", "employee_info", "aguinaldo"}


def test_other_countries_and_unknown_types_are_unchanged():
    from app.modules.payroll import service

    generic = [{"key": k, "label": lbl} for k, lbl in service._DEFAULT_REPORT_COMPONENTS]
    assert service.get_available_report_components("SOME_UNCATALOGUED_TYPE") == generic
    assert service.get_available_report_components(None) == generic
    for report_type, options in service._REPORT_COMPONENTS_BY_TYPE.items():
        if report_type in service.MX_DEDICATED_GENERATOR_REPORT_TYPES:
            continue
        assert service.get_available_report_components(report_type) == [
            {"key": k, "label": lbl} for k, lbl in options], report_type


def test_gate_text_mentions_the_payslip_field_proof_only_where_activation_runs_it(db):
    from app.modules.payroll import mexico_report_service as R
    from tests.test_mexico_report_generators import _seed

    templates = _seed(db)
    engine = R._mx_platform_gate_text(db, templates["MX-PAYROLL-REGISTER"])
    dedicated = R._mx_platform_gate_text(db, templates["MX-IDSE-MOVEMENTS"])
    receipt = R._mx_platform_gate_text(db, templates["MX-CFDI-NOMINA-RECEIPT"])
    assert engine.endswith("(and the payslip field proof at activation)") and "not SIGNED" in engine
    for text in (dedicated, receipt):
        assert "not SIGNED" in text and "payslip field proof" not in text


def test_a_component_cannot_be_added_to_a_seeded_dedicated_template(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import ReportTemplateComponentUpsert
    from tests.test_mexico_report_generators import _seed

    templates = _seed(db)
    idse = templates["MX-IDSE-MOVEMENTS"]
    assert idse.status == "Draft"
    with pytest.raises(BadRequestException, match="not an available component"):
        service.upsert_report_component(
            db, idse.id, ReportTemplateComponentUpsert(componentKey="earnings", label="Earnings", sortOrder=0))
    db.rollback()
    # A snapshot-field template still takes a component from its own catalog.
    aguinaldo = templates["MX-AGUINALDO"]
    comp = service.upsert_report_component(
        db, aguinaldo.id, ReportTemplateComponentUpsert(componentKey="aguinaldo", label="Aguinaldo", sortOrder=2))
    assert comp.component_key == "aguinaldo"
