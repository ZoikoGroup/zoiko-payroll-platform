"""list_report_templates(include_states=...) — Super Admin > Report Templates
lists a country's national AND state-level templates (AU state payroll-tax
returns, MX ISN, ...) without the operator typing a state code.

Pins:
  * include_states=True with a country and no state returns national + state;
  * the default (include_states=False) still returns national only — every
    other caller (e.g. the SG compliance summary) is unchanged;
  * state=X returns only X, with or without include_states;
  * the super-admin route exposes it as the optional includeStates param,
    defaulting to False.

All app imports are lazy (see tests/test_assist.py / _db_safety.py)."""


def _add(db, key, country, state=None, report_type="T"):
    from app.modules.payroll.models import ReportTemplate

    db.add(ReportTemplate(template_key=key, name=key, report_type=report_type, jurisdiction_country=country,
                          jurisdiction_state=state, reporting_year="2026", version="1.0", status="Draft",
                          document_scope="AGGREGATE"))
    db.flush()


def _seed(db):
    _add(db, "AU-STP", "AU")
    _add(db, "AU-PTR-NSW", "AU", "NSW", "AU_PAYROLL_TAX_RETURN")
    _add(db, "AU-PTR-VIC", "AU", "VIC", "AU_PAYROLL_TAX_RETURN")
    _add(db, "MX-ISN-CDMX", "MX", "CDMX")
    _add(db, "SG-IR8A", "SG")
    db.commit()


def _keys(rows):
    return sorted(r.template_key for r in rows)


def test_include_states_returns_national_and_state_templates(db):
    from app.modules.payroll.service import list_report_templates

    _seed(db)
    assert _keys(list_report_templates(db, country="AU", include_states=True)) == ["AU-PTR-NSW", "AU-PTR-VIC", "AU-STP"]
    assert _keys(list_report_templates(db, country="MX", include_states=True)) == ["MX-ISN-CDMX"]


def test_default_still_returns_national_only(db):
    from app.modules.payroll.service import list_report_templates

    _seed(db)
    assert _keys(list_report_templates(db, country="AU")) == ["AU-STP"]
    assert _keys(list_report_templates(db, country="MX")) == []
    assert _keys(list_report_templates(db, country="SG")) == ["SG-IR8A"]


def test_a_state_narrows_to_that_state_only(db):
    from app.modules.payroll.service import list_report_templates

    _seed(db)
    for include in (False, True):
        assert _keys(list_report_templates(db, country="AU", state="NSW", include_states=include)) == ["AU-PTR-NSW"]


def test_include_states_does_not_cross_countries(db):
    from app.modules.payroll.service import list_report_templates

    _seed(db)
    assert all(r.jurisdiction_country == "AU" for r in list_report_templates(db, country="AU", include_states=True))


def test_super_admin_route_exposes_include_states_defaulting_false(db):
    import inspect

    from app.modules.super_admin import router

    param = inspect.signature(router.list_report_templates).parameters["includeStates"]
    assert param.default.default is False
    _seed(db)
    common = dict(country="AU", state=None, reportingYear=None, reportType=None, status=None, search=None,
                  current_user=None, db=db)
    assert _keys(router.list_report_templates(includeStates=True, **common)) == ["AU-PTR-NSW", "AU-PTR-VIC", "AU-STP"]
    assert _keys(router.list_report_templates(includeStates=False, **common)) == ["AU-STP"]
