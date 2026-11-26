"""
tests/test_report_catalog.py
----------------------------
GET /api/payroll/report-templates/catalog — the Org Admin Reports page's
per-country statutory form list. It comes from Super Admin's own
payroll_report_templates rows (not a hardcoded frontend map), so India shows
all three of its forms and a form Super Admin disables disappears.
"""

from datetime import date

import pytest

from app.modules.payroll import service
from app.modules.payroll.models import ReportTemplate, StatutoryFilingCalendar


@pytest.fixture()
def four_countries(monkeypatch):
    # The "Nikhil" org: India primary, plus Australia, Singapore, Switzerland.
    monkeypatch.setattr(service, "_org_report_countries", lambda db, org_id: ("IN", ["IN", "AU", "SG", "CH"]))


def _template(db, key, country, report_type, *, year="2026-27", status="Published", scope="AGGREGATE", state=None,
              name=None, version="1.0"):
    t = ReportTemplate(template_key=key, name=name or key, report_type=report_type, jurisdiction_country=country,
                       jurisdiction_state=state, reporting_year=year, version=version, status=status,
                       document_scope=scope)
    db.add(t)
    db.commit()
    return t


def _forms(catalog, country):
    return {f["reportType"]: f for c in catalog["countries"] if c["country"] == country for f in c["forms"]}


def test_india_shows_all_three_super_admin_forms_with_due_dates(db, organization, four_countries):
    _template(db, "IN-FORM-130", "IN", "FORM_130", scope="PER_EMPLOYEE", name="Salary TDS Certificate (Form 130)")
    _template(db, "IN-FORM-123", "IN", "FORM_123", scope="PER_EMPLOYEE", status="Active")
    _template(db, "IN-FORM-138", "IN", "FORM_138", name="Quarterly Salary TDS Statement (Form 138)")
    db.add(StatutoryFilingCalendar(jurisdiction_country="IN", report_type="FORM_138", reporting_year="2026-27",
                                   period_key="Q3", period_label="October-December", due_date=date(2027, 1, 31),
                                   status="Active"))
    db.commit()

    catalog = service.list_report_catalog_for_org(db, organization.id)
    assert catalog["defaultCountry"] == "IN"
    assert [c["country"] for c in catalog["countries"]] == ["IN", "AU", "SG", "CH"]

    india = _forms(catalog, "IN")
    assert set(india) == {"FORM_130", "FORM_123", "FORM_138"}
    assert india["FORM_138"]["generator"] == "in_form_138"
    assert india["FORM_130"]["generator"] == "in_form_130"
    assert india["FORM_130"]["documentScope"] == "PER_EMPLOYEE"
    assert india["FORM_138"]["filingCalendar"] == [{
        "reportingYear": "2026-27", "periodKey": "Q3", "periodLabel": "October-December",
        "dueDate": "2027-01-31", "paymentDueDate": None,
    }]
    # Countries without published forms are still listed (empty state in the UI).
    assert _forms(catalog, "SG") == {}


def test_draft_or_superseded_forms_are_hidden_and_active_wins(db, organization, four_countries):
    _template(db, "IN-FORM-130", "IN", "FORM_130", status="Draft")
    _template(db, "IN-FORM-123", "IN", "FORM_123", status="Superseded")
    published = _template(db, "IN-FORM-138", "IN", "FORM_138", status="Published")
    active = _template(db, "IN-FORM-138", "IN", "FORM_138", status="Active", version="1.1")

    india = _forms(service.list_report_catalog_for_org(db, organization.id), "IN")
    assert set(india) == {"FORM_138"}
    (year,) = india["FORM_138"]["years"]
    assert year["templateId"] == active.id != published.id


def test_generators_and_other_states_and_countries(db, organization, four_countries):
    _template(db, "AU-STP", "AU", "STP")
    _template(db, "AU-SUPERSTREAM", "AU", "SUPERSTREAM")
    _template(db, "AU-PAYROLL-TAX-NSW", "AU", "AU_PAYROLL_TAX_RETURN", state="NSW")  # not this org's state
    _template(db, "DE-LSTB", "DE", "LSTB", year="2026")                              # not this org's country

    catalog = service.list_report_catalog_for_org(db, organization.id)
    au = _forms(catalog, "AU")
    assert set(au) == {"STP", "SUPERSTREAM"}
    assert au["STP"]["generator"] == "generic_run"
    assert au["SUPERSTREAM"]["generator"] == "au_superstream"
    assert all(f["reportType"] != "LSTB" for c in catalog["countries"] for f in c["forms"])


def test_generated_reports_filter_by_country(db, organization):
    from app.modules.payroll.models import GeneratedReport

    t = _template(db, "IN-FORM-138", "IN", "FORM_138")
    for country in ("IN", "CH"):
        db.add(GeneratedReport(organization_id=organization.id, report_template_id=t.id, template_version="1.0",
                               report_type="FORM_138", jurisdiction_country=country, reporting_year="2026-27",
                               status="Generated", rendered_data={}))
    db.commit()
    rows = service.get_generated_reports(db, organization.id, country="CH")
    assert [r.jurisdiction_country for r in rows] == ["CH"]
