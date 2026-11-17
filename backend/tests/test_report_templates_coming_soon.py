"""Report templates for the jurisdictions that used to show "Coming soon" in
Super Admin > Report Templates: BE, FR, IT, JP, MY, NZ, PL, SA (ZA was already
seeded).

Pins:
  * every PAYSLIP_ITEM_JSON path the new seeds use is a catalogued path, every
    aggregated field is aggregatable, every source_column fits String(50);
  * only _DEFAULT_REPORT_COMPONENTS keys; employer-side amounts never in a
    deductions / tax / contributions component;
  * run summaries are SUM_RUN, certificate previews SUM_YTD; JP / SA previews
    read only scalar columns (their correction payslips keep the FULL corrected
    result in the snapshot, so a snapshot SUM_YTD would double-count);
  * the seeds land Draft through the validated service upserts and re-run
    without writing anything;
  * every new catalog path exists in a real engine result of its country;
  * the activation gates are untouched (refusing countries still refuse).

All app imports are lazy (see tests/test_assist.py / _db_safety.py)."""

import pytest

NEW = ("BE", "FR", "IT", "JP", "MY", "NZ", "PL", "SA")
CATALOGUED_HERE = ("BE", "FR", "IT", "JP", "NZ", "PL", "SA")          # MY was already catalogued
EMPLOYEE_SIDE = ("deductions", "tax", "contributions")


def _seed_module():
    from scripts import seed_statutory_report_templates as seed

    return seed


def _definitions():
    seed = _seed_module()
    return {"BE": seed._be_templates(), "FR": seed._fr_templates(), "IT": seed._it_templates(),
            "JP": seed._jp_templates(), "MY": seed._my_templates(), "NZ": seed._nz_templates(),
            "PL": seed._pl_templates(), "SA": seed._sa_templates()}


def _all_fields():
    for country, templates in _definitions().items():
        for key, t in templates.items():
            for component_key, _label, fields in t["components"]:
                for field in fields:
                    yield country, key, t, component_key, field


def _is_employer_amount(kind, column):
    from app.modules.payroll import service

    if kind == "PAYSLIP_ITEM":
        return column.startswith("employer_")
    if kind == "PAYSLIP_ITEM_JSON":
        label = service._REPORT_FIELD_ALLOWED_COLUMNS[kind][column][0]
        return "(Employer)" in label
    return False


# ── catalog ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("country", CATALOGUED_HERE)
def test_catalog_paths_are_well_formed(country):
    from app.modules.payroll import service

    catalog = service._PAYSLIP_ITEM_JSON_FIELD_CATALOG[country]
    assert catalog
    prefix = f"{country.lower()}_calculation_snapshot."
    for path, spec in catalog.items():
        assert path.startswith(prefix), path
        assert len(path) <= 50, (path, len(path))
        label, field_type, aggregatable = spec
        assert field_type in ("currency", "text"), path
        assert not (field_type == "text" and aggregatable), path


def test_new_catalogs_sit_before_the_payroll_run_catalog_and_are_allowed():
    from app.modules.payroll import service

    allowed = service._REPORT_FIELD_ALLOWED_COLUMNS["PAYSLIP_ITEM_JSON"]
    for country in CATALOGUED_HERE:
        for path in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG[country]:
            assert path in allowed, path


# ── seed definitions (static) ────────────────────────────────────────────────
def test_every_seeded_field_is_catalogued_aggregatable_and_fits():
    from app.modules.payroll import service

    default_components = {key for key, _ in service._DEFAULT_REPORT_COMPONENTS}
    problems = []
    for country, key, t, component_key, field in _all_fields():
        field_key, label, field_type, kind, column, aggregation = field
        catalog = service._REPORT_FIELD_ALLOWED_COLUMNS[kind]
        if column not in catalog:
            problems.append((key, field_key, "not catalogued", column))
            continue
        if kind == "PAYSLIP_ITEM_JSON" and column not in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG[country]:
            problems.append((key, field_key, "path of another country", column))
        if aggregation and not catalog[column][2]:
            problems.append((key, field_key, "aggregated but not aggregatable", column))
        if len(column) > 50:
            problems.append((key, field_key, "source_column > 50", column))
        if component_key not in default_components:
            problems.append((key, component_key, "component not in _DEFAULT_REPORT_COMPONENTS", None))
        if t["report_type"].upper() in service._REPORT_COMPONENTS_BY_TYPE:
            problems.append((key, t["report_type"], "report type has its own component list", None))
    assert problems == []


def test_employer_amounts_never_sit_in_an_employee_component():
    leaks = [(key, component_key, field[0]) for _c, key, _t, component_key, field in _all_fields()
             if component_key in EMPLOYEE_SIDE and _is_employer_amount(field[3], field[4])]
    assert leaks == []


def test_every_employer_component_holds_only_employer_amounts():
    wrong = [(key, field[0]) for _c, key, _t, component_key, field in _all_fields()
             if component_key == "employer_contributions" and not _is_employer_amount(field[3], field[4])]
    assert wrong == []


def test_template_shapes_per_country():
    expected = {
        "BE": {"BE-PAYROLL-REGISTER", "BE-DMFA-274-SUMMARY"},
        "FR": {"FR-PAYROLL-REGISTER", "FR-DSN-SUMMARY", "FR-NET-IMPOSABLE-YTD"},
        "IT": {"IT-PAYROLL-REGISTER", "IT-F24-SUMMARY", "IT-CU-PREVIEW"},
        "JP": {"JP-PAYROLL-REGISTER", "JP-WHT-SI-SUMMARY", "JP-GENSEN-PREVIEW"},
        "MY": {"MY-PAYROLL-REGISTER", "MY-STATUTORY-SUMMARY", "MY-EA-PREVIEW"},
        "NZ": {"NZ-PAYROLL-REGISTER", "NZ-EI-SUMMARY"},
        "PL": {"PL-PAYROLL-REGISTER", "PL-ZUS-DRA-SUMMARY", "PL-PIT11-PREVIEW"},
        "SA": {"SA-PAYROLL-REGISTER", "SA-GOSI-SUMMARY", "SA-GOSI-STATEMENT"},
    }
    definitions = _definitions()
    assert {c: set(t) for c, t in definitions.items()} == expected
    for country, templates in definitions.items():
        register = templates[f"{country}-PAYROLL-REGISTER"]
        assert register["report_type"] == f"{country}_PAYROLL_REGISTER" and register["scope"] == "AGGREGATE"
        assert [c[0] for c in register["components"]] == [
            "employer_info", "employee_info", "earnings", "deductions", "employer_contributions"]
        assert register["components"][2][2][0][3:5] == ("PAYSLIP_ITEM", "gross_pay")
        for key, t in templates.items():
            amounts = [f for c in t["components"] if c[0] not in ("employer_info", "employee_info") for f in c[2]]
            if key.endswith("-SUMMARY"):
                assert t["scope"] == "AGGREGATE" and {f[5] for f in amounts} == {"SUM_RUN"}, key
            elif key != f"{country}-PAYROLL-REGISTER":
                assert t["scope"] == "PER_EMPLOYEE" and {f[5] for f in amounts} == {"SUM_YTD"}, key


@pytest.mark.parametrize("key", ["JP-GENSEN-PREVIEW", "SA-GOSI-STATEMENT"])
def test_ytd_previews_with_full_snapshot_corrections_read_scalar_columns_only(key):
    country = key[:2]
    t = _definitions()[country][key]
    kinds = {f[3] for c in t["components"] for f in c[2] if f[5] == "SUM_YTD"}
    assert kinds == {"PAYSLIP_ITEM"}


# ── seeding through the validated service upserts ────────────────────────────
def test_seeds_land_draft_and_rerun_writes_nothing(db, capsys):
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponentField

    seed = _seed_module()
    for fn in seed.SEED_COMING_SOON_COUNTRIES:
        fn(db)
    rows = db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country.in_(NEW)).all()
    keys = {r.template_key for r in rows}
    for templates in _definitions().values():
        assert set(templates) <= keys
    assert {r.status for r in rows} == {"Draft"}
    from app.modules.payroll import belgium_reports

    be_document_keys = {spec[0] for spec in belgium_reports.TEMPLATES.values()}
    assert be_document_keys <= keys                                    # be_seed_report_templates ran

    field_count = db.query(ReportTemplateComponentField).count()
    capsys.readouterr()
    for fn in seed.SEED_COMING_SOON_COUNTRIES:
        fn(db)
    out = capsys.readouterr().out
    assert " seeded " not in out                                       # every template "unchanged"
    assert db.query(ReportTemplateComponentField).count() == field_count
    assert db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country.in_(NEW)).count() == len(rows)


def test_activation_gates_are_unchanged(db):
    """BE / JP / MY / NZ / PL refuse every template of theirs; SA has no extra
    gate; FR / IT have no statutory module (maker-checker only)."""
    from app.modules.payroll import jurisdiction_hooks
    from app.modules.payroll.models import ReportTemplate

    seed = _seed_module()
    for fn in seed.SEED_COMING_SOON_COUNTRIES:
        fn(db)
    for template in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country.in_(NEW)):
        country = template.jurisdiction_country
        if country in ("FR", "IT"):
            assert not jurisdiction_hooks.has_module(country)
            continue
        refusal = jurisdiction_hooks.call(country, "template_activation_refusal", db, template, None)
        if country == "SA":
            assert refusal is None
        else:
            assert refusal, template.template_key


# ── every new path exists in a real engine result ────────────────────────────
# Keys the engine writes only in some cases (a bonus, an applicable fund, a
# manual worker); a sample that does not exercise them reports them absent.
CONDITIONAL = {
    "be_calculation_snapshot.bases.ONSS_MANUAL_108",
    "jp_calculation_snapshot.jp_bonus.jp_bonus", "jp_calculation_snapshot.jp_bonus.jp_bonus_wht",
    "pl_calculation_snapshot.pl_funds.FP_FS", "pl_calculation_snapshot.pl_funds.FGSP",
    "pl_calculation_snapshot.pl_funds.FEP",
}


def _walk(blob, path):
    """(present, value) — mirrors service._resolve_field_value's dotted walk."""
    for segment in path.split("."):
        if blob is None:
            return True, None                     # a conditional parent the engine left empty
        if not isinstance(blob, dict) or segment not in blob:
            return False, None
        blob = blob[segment]
    return True, blob


def _snapshot(country, monkeypatch):
    from types import SimpleNamespace

    if country == "BE":
        from app.modules.payroll.belgium_service import be_payslip_snapshot
        from app.modules.payroll.engine.resolver import calculate_payroll
        from tests._be_engine_helpers import context

        return be_payslip_snapshot(calculate_payroll(context(), "standard"))
    if country == "FR":
        from app.modules.payroll.service import _fr_payslip_snapshot
        from tests.test_france_payroll import TEST_GRID, _neutral_ctx

        return _fr_payslip_snapshot(_neutral_ctx(3000, TEST_GRID))
    if country == "IT":
        from app.modules.payroll.italy_service import it_payslip_snapshot
        from tests.test_italy_engine import GOLDEN, _run

        result = _run(GOLDEN[0])
        return it_payslip_snapshot(SimpleNamespace(**result) if isinstance(result, dict) else result)
    if country == "JP":
        from app.modules.payroll.engine.countries import japan
        from app.modules.payroll.japan_service import jp_payslip_snapshot
        from tests.test_japan_engine import _context

        return jp_payslip_snapshot(japan.calculate(_context())["jp_result"])
    if country == "MY":
        from app.modules.payroll.engine.countries import malaysia
        from app.modules.payroll.engine.jurisdictions.malaysia import pcb
        from app.modules.payroll.malaysia_service import my_payslip_snapshot
        from decimal import Decimal
        from tests._my_engine_helpers import ctx

        # Stand-in PCB, as test_malaysia_engine does: the real PCB blocks until
        # the HASiL specification is archived.
        monkeypatch.setattr(pcb, "compute", lambda pack, **_: {"pcb": Decimal("100.00"), "trace": {"stub": True}})
        return my_payslip_snapshot(SimpleNamespace(my_result=malaysia.calculate(ctx())["my_result"]))
    if country == "NZ":
        from app.modules.payroll.engine.countries import new_zealand
        from app.modules.payroll.new_zealand_service import nz_payslip_snapshot
        from tests.test_nz_engine import _worked_example

        return nz_payslip_snapshot(new_zealand.calculate(_worked_example()))
    if country == "PL":
        from app.modules.payroll.engine.countries import poland
        from app.modules.payroll.poland_service import pl_payslip_snapshot
        from tests._pl_engine_helpers import ctx

        return pl_payslip_snapshot(poland.calculate(ctx()))
    if country == "SA":
        from app.modules.payroll.saudi_arabia_service import sa_payslip_snapshot
        from tests.test_saudi_arabia_labour import _calc

        return sa_payslip_snapshot(SimpleNamespace(sa_result=_calc()["sa_result"]))
    raise AssertionError(country)


@pytest.mark.parametrize("country", NEW)
def test_every_catalogued_path_exists_in_a_real_result(country, monkeypatch):
    from app.modules.payroll import service

    snapshot = _snapshot(country, monkeypatch)
    assert snapshot, country
    column = f"{country.lower()}_calculation_snapshot"
    missing = []
    for path in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG[country]:
        name, _, rest = path.partition(".")
        assert name == column
        present, _value = _walk(snapshot, rest)
        if not present and path not in CONDITIONAL:
            missing.append(path)
    assert missing == []


@pytest.mark.parametrize("country", NEW)
def test_seeded_amounts_resolve_to_numbers_in_a_real_result(country, monkeypatch):
    """Every PAYSLIP_ITEM_JSON currency field a new template reads yields a
    number (or None for a conditional key) through the resolver's converter."""
    from app.modules.payroll import service

    snapshot = _snapshot(country, monkeypatch)
    bad = []
    for _c, key, _t, _comp, field in _all_fields():
        if _c != country or field[3] != "PAYSLIP_ITEM_JSON" or field[2] != "currency":
            continue
        present, value = _walk(snapshot, field[4].partition(".")[2])
        if not present:
            if field[4] not in CONDITIONAL:
                bad.append((key, field[4], "absent"))
            continue
        if value is not None and service._report_json_number(value, "currency") is None:
            bad.append((key, field[4], value))
    assert bad == []
